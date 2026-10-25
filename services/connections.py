"""Bounded HTTP and Google OAuth. Tokens are kept in the OS credential store."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class ConnectionError(RuntimeError):
    def __init__(self, message, retryable=False, request_rejected=False, status=None, reason=None, retry_after=0):
        super().__init__(message)
        self.retryable = retryable
        self.request_rejected = request_rejected
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


def http_error(url, exc):
    """Translate bounded provider error codes, never reflect credentials or raw text."""
    host = urllib.parse.urlsplit(url).hostname
    code = exc.code
    message = f'{host} returned HTTP {code}'
    reason = None
    retry_after = 0
    if host == 'api.groq.com' and code == 429:
        try:
            retry_after = min(3600, max(1, float(exc.headers.get('Retry-After', '60'))))
        except (ValueError, TypeError, AttributeError):
            retry_after = 60
    try:
        payload = json.loads(exc.read(32769))
        error = payload.get('error', {}) if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
        details = error.get('details', [])
        reasons = {item.get('reason') for item in [*error.get('errors', []), *details] if isinstance(item, dict)}
        known = ('SERVICE_DISABLED', 'accessNotConfigured', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT', 'insufficientPermissions', 'authError', 'domainPolicy', 'dailyLimitExceeded', 'userRateLimitExceeded', 'rateLimitExceeded')
        reason = next((r for r in known if r in reasons), None)
        service = ('Google Meet' if host == 'meet.googleapis.com' else
                   'Google Calendar' if host == 'www.googleapis.com' and urllib.parse.urlsplit(url).path.startswith('/calendar/') else
                   'Google Maps Routes' if host == 'routes.googleapis.com' else
                   'Google Maps Places' if host == 'places.googleapis.com' else None)
        if service:
            api = {'Google Meet': 'meet.googleapis.com', 'Google Calendar': 'calendar-json.googleapis.com',
                   'Google Maps Routes': 'routes.googleapis.com', 'Google Maps Places': 'places.googleapis.com'}[service]
            if reason in ('SERVICE_DISABLED', 'accessNotConfigured'):
                message = f'{service} API is disabled. Enable it in your Cloud project, then retry. https://console.cloud.google.com/apis/library/{api}'
            elif code in (401, 403):
                message = (f'{service} denied access. Check the Maps key restrictions, enabled APIs and billing in Google Cloud.' if 'Maps' in service else
                           f'{service} denied access. Reconnect it in Connections and approve its permissions. Account or administrator restrictions may also apply.')
        if host == 'www.googleapis.com' and urllib.parse.urlsplit(url).path.startswith(('/drive/', '/upload/drive/')):
            if reason in ('SERVICE_DISABLED', 'accessNotConfigured'):
                project = next((item.get('metadata', {}).get('consumer', '') for item in details if isinstance(item, dict) and isinstance(item.get('metadata'), dict)), '')
                suffix = '?project=' + project.split('/')[1] if re.fullmatch(r'projects/\d+', project) else ''
                message = 'Google Drive API is disabled for this Cloud project. Enable Google Drive API, wait for activation, then resume. https://console.cloud.google.com/apis/library/drive.googleapis.com' + suffix
            elif reason in ('ACCESS_TOKEN_SCOPE_INSUFFICIENT', 'insufficientPermissions'):
                message = 'Google Drive rejected the granted permissions. Reconnect Drive in Connections and approve access, then resume.'
            elif reason == 'authError' or code == 401:
                message = 'Google Drive authorization expired or is invalid. Reconnect Drive in Connections, then resume.'
            elif code == 403:
                message = 'Google Drive denied access. Check the selected file or folder permissions and your account’s Drive restrictions.'
        if host == 'gmail.googleapis.com':
            if reason in ('SERVICE_DISABLED', 'accessNotConfigured'):
                project = next((item.get('metadata', {}).get('consumer', '') for item in details if isinstance(item, dict) and isinstance(item.get('metadata'), dict)), '')
                suffix = '?project=' + project.split('/')[1] if re.fullmatch(r'projects/\d+', project) else ''
                message = 'Gmail API is disabled for the Google Cloud project. Enable Gmail API, wait a few minutes, then resume. https://console.cloud.google.com/apis/library/gmail.googleapis.com' + suffix
            elif reason in ('ACCESS_TOKEN_SCOPE_INSUFFICIENT', 'insufficientPermissions'):
                message = 'Gmail rejected the permissions. Reconnect Gmail in Connections and grant the requested access, then resume.'
            elif reason == 'authError' or code == 401:
                message = 'Gmail authorization is invalid or expired. Reconnect Gmail in Connections, then resume.'
            elif reason == 'domainPolicy':
                message = 'Your Google Workspace administrator has blocked Gmail API access. Ask the administrator to allow this app.'
            elif reason in ('dailyLimitExceeded', 'userRateLimitExceeded', 'rateLimitExceeded') or code == 429:
                message = 'Gmail rejected the request because a sending or API quota was reached. Wait for the limit to reset, then resume.'
            elif code == 403:
                message = 'Gmail rejected this request (HTTP 403). Check that Gmail API is enabled and reconnect Gmail with the requested permissions.'
    except (ValueError, TypeError, AttributeError, OSError):
        pass
    finally:
        exc.close()
    return ConnectionError(message, code == 429 or code >= 500,
                           request_rejected=code in (400, 401, 403, 404, 405, 413, 422, 429), status=code, reason=reason, retry_after=retry_after)


def request_json(url, data=None, headers=None, timeout=30, form=False, method=None, response_bytes=False, content_type=None):
    body = None
    headers = dict(headers or {})
    if data is not None:
        body = data if isinstance(data, bytes) else (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        headers['Content-Type'] = content_type or ('application/x-www-form-urlencoded' if form else 'application/json')
    req = urllib.request.Request(url, data=body, headers={'User-Agent': 'IntentOS/2.0', **headers}, method=method)
    # Never forward credentials through redirects or use environment HTTP proxies for local inference.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            limit = 10_000_000 if response_bytes else 2_000_000
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ConnectionError('Service response exceeded the download limit')
        return raw if response_bytes else json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise http_error(url, exc) from None
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
    'meet': 'https://www.googleapis.com/auth/meetings.space.created https://www.googleapis.com/auth/meetings.space.readonly',
    'calendar': 'https://www.googleapis.com/auth/calendar.events',
    'gmail': 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send',
    'drive': 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file',
}


class GoogleConnection:
    def __init__(self, config, store=None):
        self.config = config
        self.store = store or CredentialStore(config.root)
        self.tokens = self.store.get()
        self.pending = {}
        self.lock = threading.RLock()
        self.client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
        self.client_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')
        self.redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8765/api/google/callback')

    def status(self):
        from services.maps_keys import MapsKeys
        # Tokens are replaced as one object; status must never wait on a network refresh.
        tokens = self.tokens
        scopes = tokens.get('scope', '').split()
        return {'configured': bool(self.client_id and self.client_secret),
                'connected': bool(tokens.get('refresh_token') or tokens.get('access_token')),
                'services': [name for name, scope in SCOPES.items() if set(scope.split()) <= set(scopes)],
                'redirect_uri': self.redirect_uri,
                'maps': bool(MapsKeys(self.config).get())}

    def begin(self, services):
        if not self.client_id or not self.client_secret:
            raise ValueError('Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, then restart IntentOS')
        if not isinstance(services, list) or not services or any(s not in SCOPES for s in services):
            raise ValueError('Choose calendar, gmail, drive or meet')
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

    def call(self, service, url, data=None, **options):
        parsed = urllib.parse.urlsplit(url)
        endpoints = {'calendar': ('www.googleapis.com', ('/calendar/',)),
                     'drive': ('www.googleapis.com', ('/drive/', '/upload/drive/')),
                     'gmail': ('gmail.googleapis.com', ('/gmail/',)),
                     'meet': ('meet.googleapis.com', ('/v2/',))}
        if service not in endpoints:
            raise ValueError('Unknown Google service')
        host, prefixes = endpoints[service]
        if parsed.scheme != 'https' or parsed.hostname != host or not parsed.path.startswith(prefixes) or parsed.username or parsed.port not in (None, 443):
            raise ValueError('Google requests must use an approved HTTPS endpoint')
        with self.lock:
            if not set(SCOPES[service].split()) <= set(self.tokens.get('scope', '').split()):
                raise ConnectionError(f'Connect Google {service} in Connections first')
            if self.tokens.get('expires_at', 0) < time.time() + 60:
                if not self.tokens.get('refresh_token'):
                    raise ConnectionError('Google authorization expired. Reconnect in Connections.')
                self._save(request_json('https://oauth2.googleapis.com/token', {
                    'client_id': self.client_id, 'client_secret': self.client_secret,
                    'refresh_token': self.tokens['refresh_token'], 'grant_type': 'refresh_token'}, form=True))
            token = self.tokens['access_token']
        return request_json(url, data, {'Authorization': 'Bearer ' + token}, **options)
