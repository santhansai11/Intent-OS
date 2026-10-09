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
            if path == '/api/system':
                return self.send_body(200, system_snapshot())
            if path == '/api/models':
                try:
                    provider = query.get('provider', [self.runtime.config.provider])[0]
                    if provider not in ('ollama', 'gemini'):
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
            if path == '/api/intents':
                return self.send_body(201, self.runtime.submit(data.get('text'), data.get('priority', 'NORMAL'),
                    data.get('deadline'), data.get('roots'), data.get('scopes'), data.get('access_mode', 'selected'),
                    data.get('auto_outputs', False), data.get('workflow'), data.get('search_roots'), data.get('output_folder')))
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
                if data.get('remove') is True:
                    AIKeys(self.runtime.config).delete()
                else:
                    AIKeys(self.runtime.config).save(data.get('key'))
                return self.send_body(200, {'configured': bool(AIKeys(self.runtime.config).get())})
            if path == '/api/google/connect':
                return self.send_body(200, {'url': self.runtime.google.begin(data.get('services'))})
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
