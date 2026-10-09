"""Bounded HTTP and Google OAuth. Tokens are kept in the OS credential store."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class ConnectionError(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def request_json(url, data=None, headers=None, timeout=30, form=False):
    body = None
    headers = dict(headers or {})
    if data is not None:
        body = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    req = urllib.request.Request(url, data=body, headers={'User-Agent': 'IntentOS/2.0', **headers})
    # Never forward credentials through redirects or use environment HTTP proxies for local inference.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ConnectionError('Service response exceeded the 2 MB limit')
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ConnectionError(f'{urllib.parse.urlsplit(url).hostname} returned HTTP {exc.code}',
                              exc.code == 429 or exc.code >= 500) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ConnectionError(f'Cannot reach {urllib.parse.urlsplit(url).hostname}; check the service and connection', True) from None
    except (ValueError, UnicodeError):
        raise ConnectionError('Service returned invalid JSON') from None


class CredentialStore:
    def __init__(self, namespace):
        self.namespace = 'IntentOS:' + hashlib.sha256(str(namespace).encode()).hexdigest()[:16]

    def get(self):
        try:
            import keyring
            raw = keyring.get_password(self.namespace, 'google')
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def save(self, data):
        try:
            import keyring
            backend = keyring.get_keyring()
            if backend.priority <= 0 or 'plaintext' in type(backend).__name__.lower():
                raise RuntimeError()
            keyring.set_password(self.namespace, 'google', json.dumps(data))
        except Exception:
            raise ConnectionError('A secure OS keyring is required. Install keyring and enable Windows Credential Manager or Linux Secret Service.') from None

    def delete(self):
        try:
            import keyring
            if keyring.get_password(self.namespace, 'google'):
                keyring.delete_password(self.namespace, 'google')
        except Exception:
            raise ConnectionError('Could not remove Google credentials from the OS keyring') from None


SCOPES = {
    'calendar': 'https://www.googleapis.com/auth/calendar.events',
    'gmail': 'https://www.googleapis.com/auth/gmail.send',
    'drive': 'https://www.googleapis.com/auth/drive.metadata.readonly',
}


class GoogleConnection:
    def __init__(self, config, store=None):
        self.store = store or CredentialStore(config.root)
        self.tokens = self.store.get()
        self.pending = {}
        self.lock = threading.RLock()
        self.client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
        self.client_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')
        self.redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8765/api/google/callback')

    def status(self):
        # Tokens are replaced as one object; status must never wait on a network refresh.
        tokens = self.tokens
        scopes = tokens.get('scope', '').split()
        return {'configured': bool(self.client_id and self.client_secret),
                'connected': bool(tokens.get('refresh_token') or tokens.get('access_token')),
                'services': [name for name, scope in SCOPES.items() if scope in scopes],
                'redirect_uri': self.redirect_uri,
                'maps': bool(os.environ.get('GOOGLE_MAPS_API_KEY'))}

    def begin(self, services):
        if not self.client_id or not self.client_secret:
            raise ValueError('Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, then restart IntentOS')
        if not isinstance(services, list) or not services or any(s not in SCOPES for s in services):
            raise ValueError('Choose calendar, gmail, or drive')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v[1] > time.time()}
            self.pending[state] = (verifier, time.time() + 600)
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
            'client_id': self.client_id, 'redirect_uri': self.redirect_uri, 'response_type': 'code',
            'scope': ' '.join(SCOPES[s] for s in services), 'access_type': 'offline',
            'include_granted_scopes': 'true', 'prompt': 'consent', 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def callback(self, state, code):
        with self.lock:
            pending = self.pending.pop(state, None)
            if not pending or pending[1] < time.time() or not code:
                raise ValueError('Invalid or expired Google sign-in. Connect again from IntentOS.')
            data = request_json('https://oauth2.googleapis.com/token', {
                'client_id': self.client_id, 'client_secret': self.client_secret,
                'redirect_uri': self.redirect_uri, 'code': code, 'code_verifier': pending[0],
                'grant_type': 'authorization_code'}, form=True)
            self._save(data)

    def _save(self, data):
        if not data.get('access_token'):
            raise ConnectionError('Google did not return an access token')
        tokens = {**self.tokens, **data, 'expires_at': time.time() + data.get('expires_in', 3600)}
        self.store.save(tokens)
        self.tokens = tokens

    def disconnect(self):
        with self.lock:
            self.store.delete()
            self.tokens = {}
            self.pending.clear()

    def call(self, service, url, data=None):
        with self.lock:
            if SCOPES[service] not in self.tokens.get('scope', '').split():
                raise ConnectionError(f'Connect Google {service} in Connections first')
            if self.tokens.get('expires_at', 0) < time.time() + 60:
                if not self.tokens.get('refresh_token'):
                    raise ConnectionError('Google authorization expired. Reconnect in Connections.')
                self._save(request_json('https://oauth2.googleapis.com/token', {
                    'client_id': self.client_id, 'client_secret': self.client_secret,
                    'refresh_token': self.tokens['refresh_token'], 'grant_type': 'refresh_token'}, form=True))
            token = self.tokens['access_token']
        return request_json(url, data, {'Authorization': 'Bearer ' + token})
