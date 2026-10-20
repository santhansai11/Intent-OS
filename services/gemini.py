"""Gemini transport and OS-backed key storage. Never return credentials to callers."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from services.connections import ConnectionError


class AIKeys:
    def __init__(self, config):
        self.namespace = 'IntentOS:' + hashlib.sha256(str(config.root).encode()).hexdigest()[:16]

    def get(self):
        try:
            import keyring
            saved = keyring.get_password(self.namespace, 'gemini-api-key')
            if saved:
                return saved
        except Exception:
            pass
        return os.environ.get('GEMINI_API_KEY', '').strip()

    def save(self, key):
        if not isinstance(key, str) or not 15 <= len(key.strip()) <= 512 or any(c.isspace() for c in key.strip()):
            raise ValueError('Enter a valid Gemini API key')
        try:
            import keyring
            if keyring.get_keyring().priority <= 0 or 'plaintext' in type(keyring.get_keyring()).__name__.lower():
                raise RuntimeError()
            keyring.set_password(self.namespace, 'gemini-api-key', key.strip())
            if keyring.get_password(self.namespace, 'gemini-api-key') != key.strip():
                raise RuntimeError()
        except Exception:
            raise ValueError('Could not save the Gemini key. Enable a secure OS credential store and retry.') from None

    def delete(self):
        import keyring
        if keyring.get_password(self.namespace, 'gemini-api-key'):
            keyring.delete_password(self.namespace, 'gemini-api-key')


class Gemini:
    base = 'https://generativelanguage.googleapis.com/v1beta/'

    def __init__(self, config):
        self.config, self.keys = config, AIKeys(config)

    def call(self, path, body=None):
        key = self.keys.get()
        if not key:
            raise ConnectionError('Add your Gemini API key in Connections, or select local Ollama.')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(self.base + path,
            json.dumps(body).encode() if body is not None else None,
            {'x-goog-api-key': key, 'Content-Type': 'application/json', 'User-Agent': 'IntentOS/3'})
        try:
            with opener.open(request, timeout=45) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ConnectionError('Gemini response exceeded the size limit')
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Do not reflect arbitrary provider error text or request headers.
            if exc.code in (400, 401, 403):
                raise ConnectionError(f'Gemini rejected the request (HTTP {exc.code}). Check the API key, project access, and selected model.') from None
            if exc.code == 404:
                raise ConnectionError('Gemini model is unavailable. Refresh models in Connections.') from None
            if exc.code == 429:
                raise ConnectionError('Gemini free-tier quota or rate limit reached. Wait and resume, or select Ollama.', True) from None
            raise ConnectionError(f'Gemini service error (HTTP {exc.code})', exc.code >= 500) from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ConnectionError('Gemini request timed out or could not connect; no local tool was executed.', True) from None
        except (ValueError, UnicodeError):
            raise ConnectionError('Gemini returned an unreadable response') from None

    def models(self):
        result, page = [], ''
        for _ in range(5):
            data = self.call('models?pageSize=100' + ('&pageToken=' + urllib.parse.quote(page) if page else ''))
            result.extend(m['name'].removeprefix('models/') for m in data.get('models', [])
                          if 'generateContent' in m.get('supportedGenerationMethods', []))
            page = data.get('nextPageToken', '')
            if not page:
                break
        return sorted(set(result))

    def generate(self, system, context):
        model = self.config.gemini_model
        if not re.fullmatch(r'[a-zA-Z0-9._-]{1,120}', model):
            raise ConnectionError('Choose a valid Gemini model identifier')
        result = self.call('models/' + model + ':generateContent', {
            'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': json.dumps(context, ensure_ascii=False)}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 8192}})
        candidates = result.get('candidates', [])
        if not candidates or candidates[0].get('finishReason') not in (None, 'STOP'):
            raise ConnectionError('Gemini did not finish a usable response. Narrow the request or retry.', True)
        text = ''.join(p.get('text', '') for p in candidates[0].get('content', {}).get('parts', []) if not p.get('thought'))
        try:
            return json.loads(text), result.get('usageMetadata', {})
        except ValueError:
            raise ConnectionError('Gemini returned invalid action JSON; no tool was executed.', True) from None
