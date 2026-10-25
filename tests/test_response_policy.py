"""Direct answers use the real finish protocol without requiring an export."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.agent import OllamaPlanner
from planner.router import PlannerRouter
from planner.response_policy import CONVERSATION_GUIDANCE


class DirectAnswerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Config(Path(temp.name) / 'runtime')
        self.answer = {'kind': 'finish', 'summary': 'A process is a running program.', 'tool': '', 'arguments': {}}
        self.task = {'goal': 'What is a process?', 'roots': [], 'scopes': ['system'], 'history': [], 'steps': []}

    def test_cloud_providers_receive_answer_without_export_guidance(self):
        router = PlannerRouter(self.config)
        for provider in ['gemini', 'groq']:
            with self.subTest(provider=provider), patch.object(getattr(router, provider), 'generate', return_value=(dict(self.answer), {})) as generate:
                answer = router.decide({**self.task, 'provider': provider}, [])
                self.assertEqual(answer['summary'], self.answer['summary'])
                self.assertIn(CONVERSATION_GUIDANCE, generate.call_args.args[0])

    def test_local_provider_receives_same_guidance(self):
        with patch.object(type(self.config), 'model', new_callable=PropertyMock, return_value='local-test'), patch('planner.agent.request_json', side_effect=[{}, {'message': {'content': json.dumps(self.answer)}}]) as request:
            answer = OllamaPlanner(self.config).decide(self.task, [])
        self.assertEqual(answer['summary'], self.answer['summary'])
        self.assertIn(CONVERSATION_GUIDANCE, request.call_args.args[1]['messages'][0]['content'])

    def test_finish_delivers_answer_without_a_file_or_permission_request(self):
        class Planner:
            def decide(inner, task, catalog):
                return dict(self.answer)
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config, Planner())
            try:
                submitted = kernel.submit('What is a process?', scopes=['system'], auto_outputs=False)
                kernel.tick()
                task = kernel.tasks[submitted['id']]
                self.assertEqual(task['state'], 'COMPLETED')
                self.assertEqual(task['answer'], self.answer['summary'])
                self.assertIsNone(task['pending'])
                self.assertEqual(task['steps'], [])
                self.assertEqual(list(self.config.workspace.iterdir()), [])
            finally:
                kernel.close()
