"""Loopback-only API and built React client for the durable IntentOS runtime."""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, quote

from intent_kernel.config import PROJECT
from intent_kernel.runtime import Runtime
from intent_kernel.resource_manager.monitor import system_snapshot
from services.connections import ConnectionError


class IntentOSHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def runtime(self):
        return self.server.runtime

    def send_body(self, code, body, content_type='application/json; charset=utf-8', extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def trusted_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        try:
            if not self.trusted_host():
                return self.send_body(403, {'error': 'Loopback host required'})
            parsed = urlsplit(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            if path == '/api/session':
                return self.send_body(200, {'token': self.server.token})
            if path == '/api/health':
                return self.send_body(200, {'status': 'ok', 'runtime': 'durable-local', 'version': 2})
            if path == '/api/status':
                return self.send_body(200, self.runtime.snapshot())
            if path == '/api/os-lab':
                return self.send_body(200, self.runtime.os_lab.snapshot())
            if path == '/api/knowledge':
                return self.send_body(200, self.runtime.registry.knowledge.status())
            if path == '/api/datasets':
                return self.send_body(200, {'datasets': self.runtime.registry.datasets.catalog()})
            if path == '/api/system':
                return self.send_body(200, system_snapshot())
            if path == '/api/models':
                try:
                    provider = query.get('provider', [self.runtime.config.provider])[0]
                    if provider not in ('ollama', 'gemini', 'groq'):
                        raise ValueError('Unknown AI provider')
                    return self.send_body(200, {'models': self.runtime.planner.models(provider), 'provider': provider, 'reachable': True})
                except ConnectionError as exc:
                    return self.send_body(200, {'models': [], 'reachable': False, 'error': str(exc)})
            if path == '/api/events':
                return self.events()
            if path == '/api/google/callback':
                try:
                    self.runtime.google.callback(query.get('state', [''])[0], query.get('code', [''])[0])
                    return self.send_body(303, b'', extra={'Location': '/?connected=google'})
                except (ValueError, ConnectionError):
                    return self.send_body(400, b'<h1>Google connection failed</h1><p>Return to IntentOS and connect again. Check your OAuth configuration and secure keyring.</p>', 'text/html; charset=utf-8')
            if path == '/api/artifact':
                ident, step_id = query.get('intent', [''])[0], query.get('step', [''])[0]
                with self.runtime.cv:
                    task = self.runtime.tasks.get(ident)
                    if not task:
                        raise ValueError('Intent not found')
                    step = next((s for s in task['steps'] if s['id'] == step_id), None)
                    if not step or not isinstance(step['result'], dict) or not step['result'].get('artifact'):
                        raise ValueError('Artifact not found')
                    target = self.runtime.registry.path(step['result']['artifact'], task)
                if not target.is_file() or target.stat().st_size > 100_000_000:
                    raise ValueError('Artifact missing or too large')
                return self.send_body(200, target.read_bytes(), 'application/octet-stream',
                                      {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(target.name)})
            if path.startswith('/api/'):
                return self.send_body(404, {'error': 'Route not found'})
            dist = (PROJECT / 'frontend' / 'dist').resolve()
            target = (dist / path.lstrip('/')).resolve() if path != '/' else dist / 'index.html'
            if not target.is_relative_to(dist) or not target.is_file():
                if path == '/':
                    return self.send_body(503, b'<h1>Build the IntentOS interface</h1><p>Run <code>npm --prefix frontend install</code>, then <code>npm --prefix frontend run build</code> and reload.</p>', 'text/html; charset=utf-8')
                return self.send_body(404, {'error': 'File not found'})
            return self.send_body(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError) as exc:
            self.send_body(400, {'error': str(exc)})

    def do_POST(self):
        try:
            if urlsplit(self.path).path == '/api/uploads':
                return self.receive_upload()
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 200000:
                return self.send_body(413, {'error': 'Request exceeds 200 KB'})
            self.connection.settimeout(10)
            # Consume the bounded body before rejecting a request. Closing a
            # Windows socket with unread bytes can reset it and hide the 403.
            # Authentication still precedes JSON parsing and all mutations.
            body = self.rfile.read(length)
            port = self.server.server_address[1]
            allowed = {f'http://127.0.0.1:{port}', f'http://localhost:{port}', 'http://localhost:5173', 'http://127.0.0.1:5173'}
            origin = self.headers.get('Origin')
            if not self.trusted_host() or (origin and origin not in allowed):
                return self.send_body(403, {'error': 'Untrusted origin'})
            if not secrets.compare_digest(self.headers.get('X-IntentOS-Token', ''), self.server.token):
                return self.send_body(403, {'error': 'Refresh IntentOS to establish a local session'})
            if self.headers.get_content_type() != 'application/json':
                return self.send_body(415, {'error': 'JSON required'})
            data = json.loads(body or b'{}')
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            path = urlsplit(self.path).path
            if path == '/api/chat':
                from services.companion_chat import chat_reply
                from services.companion_context import application_context
                completed = None
                ident = data.get('intent_id')
                if ident is not None:
                    if not isinstance(ident, str):
                        raise ValueError('Choose a completed intent to discuss.')
                    with self.runtime.cv:
                        task = self.runtime.tasks.get(ident)
                        if not task or task['state'] != 'COMPLETED':
                            raise ValueError('That completed intent is no longer available.')
                        answer = task.get('answer', '')
                        completed = {'goal': task['goal'][:4000], 'answer': answer[:12000], 'excerpt': len(answer) > 12000}
                if not self.server.chat_slots.acquire(blocking=False):
                    return self.send_body(429, {'error': 'Orbii is finishing another reply. Please try again shortly.'})
                try:
                    application = application_context(self.runtime.registry.catalog(), self.runtime.google.status())
                    return self.send_body(200, chat_reply(self.runtime.config, data.get('message'), data.get('history'), completed, application))
                finally:
                    self.server.chat_slots.release()
            if path == '/api/os-lab/reset':
                return self.send_body(200, self.runtime.os_lab.reset(data.get('scenario', 'preemption'), data.get('quantum', 2), data.get('frames', 3)))
            if path == '/api/os-lab/step':
                return self.send_body(200, self.runtime.os_lab.step())
            if path == '/api/intents':
                return self.send_body(201, self.runtime.submit(data.get('text'), data.get('priority', 'NORMAL'),
                    data.get('deadline'), data.get('roots'), data.get('scopes'), data.get('access_mode', 'selected'),
                    data.get('auto_outputs', False), data.get('workflow'), data.get('search_roots'), data.get('output_folder'), data.get('attachments'), data.get('depends_on')))
            if path == '/api/history/delete':
                return self.send_body(200, self.runtime.delete_history(data.get('ids'), data.get('remove_uploads') is True))
            if path == '/api/uploads/remove':
                ident = data.get('id')
                with self.runtime.cv:
                    if any(a['id'] == ident for t in self.runtime.tasks.values() for a in t.get('attachments', [])):
                        raise ValueError('This upload belongs to an intent. Manage it through history deletion.')
                    self.runtime.registry.knowledge.forget([self.runtime.uploads.resolve([{'id': ident}])[0]['path']])
                    self.runtime.uploads.remove(ident)
                return self.send_body(200, {'removed': True})
            if path == '/api/knowledge/search':
                roots = data.get('roots', self.runtime.config.roots)
                if not isinstance(roots, list) or any(r not in self.runtime.config.roots for r in roots):
                    raise ValueError('Choose configured folders')
                return self.send_body(200, self.runtime.registry.knowledge.search({'query': data.get('query', '')}, {'roots': roots, 'search_roots': roots}))
            if path == '/api/datasets/search':
                return self.send_body(200, self.runtime.registry.datasets.search(data))
            if path.startswith('/api/intents/'):
                parts = path.strip('/').split('/')
                if len(parts) != 4:
                    raise ValueError('Invalid intent action')
                return self.send_body(200, self.runtime.control(parts[2], parts[3], data))
            if path == '/api/settings':
                with self.runtime.cv:
                    self.runtime.config.update(data)
                return self.send_body(200, self.runtime.config.public())
            if path == '/api/ai/key':
                from services.gemini import AIKeys
                provider = data.get('provider', 'gemini')
                keys = AIKeys(self.runtime.config, provider)
                if data.get('remove') is True:
                    keys.delete()
                else:
                    keys.save(data.get('key'))
                    with self.runtime.cv:
                        self.runtime.config.update({'provider': provider})
                return self.send_body(200, {'configured': bool(keys.get()), 'provider': provider})
            if path == '/api/ai/test':
                from services.gemini import Gemini
                from services.groq import Groq
                from types import SimpleNamespace
                provider = data.get('provider', 'gemini')
                if provider not in ('gemini', 'groq'):
                    raise ValueError('Choose a supported cloud provider')
                model = data.get('model', getattr(self.runtime.config, provider + '_model'))
                if not isinstance(model, str):
                    raise ValueError('Choose a text model')
                probe = (Groq if provider == 'groq' else Gemini)(SimpleNamespace(root=self.runtime.config.root, **{provider + '_model': model}))
                answer, _ = probe.generate('Return JSON with ok=true.', {'message': 'Connection test'})
                if not isinstance(answer, dict) or answer.get('ok') is not True:
                    raise ConnectionError(f'{provider.title()} responded but failed the JSON connection test')
                return self.send_body(200, {'ok': True, 'model': model, 'provider': provider})
            if path == '/api/google/connect':
                return self.send_body(200, {'url': self.runtime.google.begin(data.get('services'))})
            if path == '/api/google/test':
                from services.google_checks import check_service
                return self.send_body(200, check_service(self.runtime.config, self.runtime.google, self.runtime.registry, data.get('service')))
            if path == '/api/google/maps/key':
                from services.maps_keys import MapsKeys
                keys = MapsKeys(self.runtime.config)
                if data.get('remove') is True:
                    keys.delete()
                else:
                    keys.save(data.get('key'))
                return self.send_body(200, {'configured': bool(keys.get())})
            if path == '/api/google/disconnect':
                self.runtime.google.disconnect()
                return self.send_body(200, {'disconnected': True})
            return self.send_body(404, {'error': 'Route not found'})
        except (ValueError, TypeError, ConnectionError) as exc:
            self.send_body(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send_body(500, {'error': 'Internal error. Check the local server and retry.'})

    def receive_upload(self):
        from urllib.parse import unquote
        # Large bodies are authenticated BEFORE they touch disk or memory.
        port = self.server.server_address[1]
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{port}', f'http://localhost:{port}', 'http://localhost:5173', 'http://127.0.0.1:5173'}
        if not self.trusted_host() or (origin and origin not in allowed) or not secrets.compare_digest(self.headers.get('X-IntentOS-Token', ''), self.server.token):
            # Windows can reset a socket closed with unread request bytes and
            # hide the 403. Discard only a small, bounded rejected body; no upload
            # storage is touched and large unauthenticated uploads are not read.
            try:
                rejected_length = int(self.headers.get('Content-Length', '0'))
                if 0 < rejected_length <= 8192:
                    self.connection.settimeout(1)
                    self.rfile.read(rejected_length)
            except (ValueError, OSError):
                pass
            self.close_connection = True
            return self.send_body(403, {'error': 'Refresh IntentOS to upload files'})
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 100_000_000:
            self.close_connection = True
            return self.send_body(413, {'error': 'Each file must be between 1 byte and 100 MB'})
        self.connection.settimeout(60)
        try:
            result = self.runtime.uploads.receive(self.rfile, unquote(self.headers.get('X-Filename', '')), length)
        except Exception:
            self.close_connection = True
            raise
        return self.send_body(201, result)

    def events(self):
        if not self.server.stream_slots.acquire(blocking=False):
            return self.send_body(429, {'error': 'Too many live connections'})
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.connection.settimeout(10)
            while not self.runtime.stopping:
                payload = json.dumps(self.runtime.snapshot(), ensure_ascii=False)
                self.wfile.write(('event: snapshot\ndata: ' + payload + '\n\n').encode('utf-8'))
                self.wfile.flush()
                with self.runtime.cv:
                    self.runtime.cv.wait(timeout=2)
        except (OSError, ConnectionError):
            pass
        finally:
            self.server.stream_slots.release()


class LocalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(runtime, port=8765):
    server = LocalHTTPServer(('127.0.0.1', port), IntentOSHandler)
    server.daemon_threads = True
    server.runtime, server.token = runtime, secrets.token_urlsafe(32)
    server.stream_slots = threading.BoundedSemaphore(16)
    server.chat_slots = threading.BoundedSemaphore(2)
    return server


def serve(port=8765, host='127.0.0.1', open_browser=False):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('IntentOS is a single-user local app; bind to loopback only')
    runtime = Runtime()
    try:
        server = make_server(runtime, port)
    except Exception:
        runtime.close()
        raise
    runtime.start()
    print(f'IntentOS running at http://127.0.0.1:{port} ({runtime.config.provider} + durable kernel)')
    if open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        server.server_close()
