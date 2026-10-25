"""Groq transport, credential isolation and provider routing regressions."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from api.server import make_server
from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.router import PlannerRouter
from services.connections import ConnectionError
from services.gemini import AIKeys
from services.groq import Groq


class GroqTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.client = Groq(self.config)

    def test_credentials_are_isolated_and_never_public(self):
        def lookup(namespace, username):
            return {'groq-api-key': 'private-groq-value', 'gemini-api-key': 'private-gemini-value'}[username]
        with patch('keyring.get_password', side_effect=lookup):
            self.assertEqual(AIKeys(self.config, 'groq').get(), 'private-groq-value')
            self.assertEqual(AIKeys(self.config).get(), 'private-gemini-value')
            public = json.dumps(self.config.public())
            self.assertNotIn('private-', public)
        with patch('keyring.get_password', return_value=None), patch.dict(os.environ, {'GROQ_API_KEY': 'groq-env', 'GEMINI_API_KEY': 'gemini-env'}):
            self.assertEqual(self.client.keys.get(), 'groq-env')
        with patch('keyring.get_keyring') as backend, patch('keyring.set_password') as save, patch('keyring.get_password', return_value='fake-groq-key-value'):
            backend.return_value.priority = 1
            self.client.keys.save('fake-groq-key-value')
            self.assertEqual(save.call_args.args[1], 'groq-api-key')

    def test_json_request_and_token_accounting(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}
        with patch.object(AIKeys, 'get', return_value='fake-key'), patch('services.groq.request_json', return_value=response) as request:
            action, usage = self.client.generate('Test', {'message': 'Connection test'})
        self.assertTrue(action['ok'])
        self.assertEqual(usage['promptTokenCount'], 10)
        url, body = request.call_args.args
        self.assertEqual(url, 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(body['max_completion_tokens'], 2048)
        self.assertNotIn('fake-key', json.dumps(body))
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], 'Bearer fake-key')

    def test_partial_and_invalid_json_are_rejected(self):
        for response in ({}, {'choices': []}, {'choices': [{'finish_reason': 'length'}]}, {'choices': [{'finish_reason': 'stop', 'message': {'content': '[]'}}]}, {'choices': [{'finish_reason': 'stop', 'message': {'content': 'not json'}}]}):
            with self.subTest(response=response), patch.object(self.client, 'call', return_value=response), self.assertRaises(ConnectionError):
                self.client.generate('test', {})

    def test_errors_are_redacted_and_rate_limit_is_retryable(self):
        for status in (400, 401, 403, 404, 413, 429, 500):
            with self.subTest(status=status), patch.object(AIKeys, 'get', return_value='fake-key'), patch('services.groq.request_json', side_effect=ConnectionError('private-value', status >= 500, status=status)):
                with self.assertRaises(ConnectionError) as error:
                    self.client.generate('test', {})
                self.assertNotIn('private-value', str(error.exception))
                self.assertEqual(error.exception.retryable, status == 429 or status >= 500)

    def test_models_filter_non_planners(self):
        with patch.object(self.client, 'call', return_value={'data': [{'id': 'openai/gpt-oss-120b'}, {'id': 'whisper-v3'}, {'id': 'groq/compound'}, {'id': 'retired', 'active': False}]}):
            self.assertEqual(self.client.models(), ['openai/gpt-oss-120b'])

    def test_provider_pinning_metrics_and_no_fallback(self):
        router = PlannerRouter(self.config)
        task = {'provider': 'groq', 'goal': 'Say hello', 'roots': [], 'history': [], 'steps': []}
        with patch.object(router.groq, 'generate', return_value=({'kind': 'finish', 'summary': 'Hello'}, {'promptTokenCount': 42})) as groq, patch.object(router.gemini, 'generate') as gemini, patch.object(router.local, 'decide') as local:
            action = router.decide(task, [])
            self.assertEqual(action['metrics']['provider'], 'groq')
            self.assertEqual(action['metrics']['input_tokens'], 42)
            groq.side_effect = ConnectionError('rate limit', True)
            with self.assertRaises(ConnectionError):
                router.decide(task, [])
            gemini.assert_not_called()
            local.assert_not_called()
        with patch.object(router.groq, 'generate', return_value=({'kind': 'tool', 'summary': 'Bad', 'arguments': []}, {})), self.assertRaises(ConnectionError):
            router.decide(task, [])

    def test_size_rejection_retries_planning_once_with_smaller_budget(self):
        router = PlannerRouter(self.config)
        task = {'provider': 'groq', 'goal': 'Say hello', 'roots': [], 'history': [], 'steps': []}
        with patch.object(router.groq, 'generate', side_effect=[ConnectionError('size', status=413), ({'kind': 'finish', 'summary': 'Hello'}, {})]) as generate:
            self.assertEqual(router.decide(task, [])['kind'], 'finish')
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(generate.call_args.kwargs['max_tokens'], 1536)

    def test_http_key_save_and_connection_probe(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        self.addCleanup(kernel.close)
        server = make_server(kernel, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def post(path, data):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/{path}', json.dumps(data).encode(), {'Content-Type': 'application/json', 'X-IntentOS-Token': server.token})
            with urlopen(req) as response:
                return json.load(response)
        try:
            with patch.object(AIKeys, 'save') as save, patch.object(AIKeys, 'get', return_value='private-key'):
                result = post('ai/key', {'provider': 'groq', 'key': 'fake-groq-key-value'})
                save.assert_called_once()
                self.assertEqual(self.config.provider, 'groq')
                self.assertNotIn('private-key', json.dumps(result))
                self.assertNotIn('fake-groq', self.config.path.read_text())
            with patch.object(Groq, 'generate', return_value=({'ok': True}, {})) as generate:
                self.assertTrue(post('ai/test', {'provider': 'groq', 'model': 'openai/gpt-oss-120b'})['ok'])
                self.assertEqual(generate.call_args.args[1], {'message': 'Connection test'})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
