"""Groq cloud planning transport. Capabilities still execute through IntentOS."""
import json
import re

from services.connections import ConnectionError, request_json
from services.gemini import AIKeys


class Groq:
    base = 'https://api.groq.com/openai/v1/'

    def __init__(self, config):
        self.config = config
        self.keys = AIKeys(config, 'groq')

    def call(self, path, body=None):
        key = self.keys.get()
        if not key:
            raise ConnectionError('Add your Groq API key in Connections.')
        try:
            data = request_json(self.base + path, body,
                                headers={'Authorization': 'Bearer ' + key}, timeout=45)
        except ConnectionError as exc:
            if exc.status in (401, 403):
                raise ConnectionError('Groq rejected access. Check your API key and model permissions.', status=exc.status) from None
            if exc.status in (400, 404, 422):
                raise ConnectionError('Groq rejected the model or request format. Refresh models and test a text model with JSON support.', status=exc.status) from None
            if exc.status == 413:
                raise ConnectionError('Groq rejected the compact request because it exceeds this account’s allowance. Select a model/provider with a larger allowance in Connections.', status=413) from None
            if exc.status == 429:
                raise ConnectionError('Groq rate limit reached. Waiting for the next available request window.', True, status=429, retry_after=exc.retry_after or 60) from None
            raise ConnectionError('Groq could not complete the request. No local capability was executed.', exc.retryable, status=exc.status) from None
        except (ValueError, UnicodeError):
            raise ConnectionError('Groq returned an unreadable response.') from None
        if not isinstance(data, dict):
            raise ConnectionError('Groq returned an invalid response.')
        return data

    def models(self):
        data = self.call('models')
        return sorted({m['id'] for m in data.get('data', [])
                       if isinstance(m, dict) and isinstance(m.get('id'), str)
                       and m.get('active', True)
                       and not re.search(r'whisper|orpheus|tts|guard|safeguard|compound', m['id'], re.I)})

    def generate(self, system, context, max_tokens=2048):
        model = self.config.groq_model
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,119}', model):
            raise ConnectionError('Choose a valid Groq model identifier.')
        body = {
            'model': model,
            'messages': [{'role': 'system', 'content': system + '\nReturn only a JSON object.'},
                         {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, separators=(',', ':'))}],
            'response_format': {'type': 'json_object'},
            'max_completion_tokens': max_tokens,
            'stream': False,
        }
        if model.startswith('openai/gpt-oss-'):
            body['reasoning_effort'] = 'low'
        result = self.call('chat/completions', body)
        try:
            choice = result['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ConnectionError('Groq did not finish a usable response. Narrow the request or retry.', True)
            action = json.loads(choice['message']['content'])
            if not isinstance(action, dict):
                raise ValueError()
            usage = result.get('usage') or {}
            return action, {'promptTokenCount': usage.get('prompt_tokens'),
                            'candidatesTokenCount': usage.get('completion_tokens')}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ConnectionError('Groq returned invalid action JSON; no capability was executed.', True) from None
