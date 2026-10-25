import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.groq_context import ContextBudget, chunks, size
from services.connections import ConnectionError, http_error
from services.contracts import attachment_continuation


class GroqContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = SimpleNamespace(config=SimpleNamespace(root=Path(self.temp.name), groq_model='test'), generate=Mock(return_value=({'summary': 'Evidence from the entire fragment, with limitations.'}, {})))

    def test_utf8_chunking_preserves_every_character(self):
        text = ('abc\U0001f600\u4e2d\n' * 4000) + 'FINAL FINDING'
        fragments = list(chunks(text))
        self.assertEqual(''.join(fragments), text)
        self.assertTrue(all(len(f.encode()) <= 6000 for f in fragments))

    def test_complete_source_is_summarized_and_cached_without_mutating_checkpoints(self):
        source = ''.join(f'Finding {i}: documented result.\n' for i in range(1200)) + 'IMPORTANT FINAL RESULT'
        context = {'goal': 'Keep my recipient and request', 'document_sources': [{'path': 'report.docx', 'content': source, 'next_offset': None}], 'history': [{'action': {'tool': 'files_read'}, 'observation': {'path': 'report.docx', 'content': source}}, {'user_reply': 'Do not send yet'}], 'completed': [{'tool': 'gmail_send', 'artifact': None}]}
        original = copy.deepcopy(context)
        compact = ContextBudget(self.client).fit('policy', context, budget=5000)
        self.assertLessEqual(size(compact) + len('policy'), 5000)
        sent = ''.join(call.args[1]['source_fragment'] for call in self.client.generate.call_args_list)
        self.assertEqual(sent, source)
        self.assertEqual(context, original)
        self.assertEqual(compact['goal'], context['goal'])
        self.assertEqual(compact['history'][1], context['history'][1])
        self.assertEqual(compact['completed'], context['completed'])
        self.assertEqual(compact['document_sources'][0]['next_offset'], None)
        self.assertIn('summary', compact['document_sources'][0]['context_representation'])
        self.client.generate.reset_mock()
        self.assertEqual(ContextBudget(self.client).fit('policy', context, budget=5000), compact)
        self.client.generate.assert_not_called()

    def test_fixed_instructions_are_never_silently_truncated(self):
        with self.assertRaisesRegex(ConnectionError, 'goal, tool definitions'):
            ContextBudget(self.client).fit('policy', {'goal': 'x' * 9000}, budget=500)
        self.client.generate.assert_not_called()

    def test_schema_constraints_survive_compaction(self):
        tool = {'name': 'send', 'description': 'Send only when authorized', 'parameters': {'type': 'object', 'properties': {'to': {'type': 'string', 'description': 'Recipient', 'maxLength': 200}}, 'required': ['to'], 'additionalProperties': False}}
        result = ContextBudget(self.client).fit('policy', {'tools': [tool]})['tools'][0]
        self.assertEqual(result['description'], tool['description'])
        self.assertEqual(result['parameters']['required'], ['to'])
        self.assertFalse(result['parameters']['additionalProperties'])
        self.assertEqual(result['parameters']['properties']['to'], {'type': 'string', 'maxLength': 200})

    def test_nonreducing_summary_is_retried_not_cached(self):
        text = 'source text ' * 200
        self.client.generate.side_effect = [({'summary': text}, {}), ({'summary': 'Compact evidence.'}, {})]
        self.assertEqual(ContextBudget(self.client).summarize(text), 'Compact evidence.')
        self.assertEqual(self.client.generate.call_count, 2)
        self.assertEqual(len(list(Path(self.temp.name).rglob('*.json'))), 1)

    def test_failed_summary_never_becomes_evidence(self):
        self.client.generate.return_value = ({'summary': ''}, {})
        with self.assertRaises(ConnectionError):
            ContextBudget(self.client).summarize('source ' * 5000)
        self.assertEqual(list(Path(self.temp.name).rglob('*.json')), [])

    def test_partial_summary_cache_survives_rate_limit(self):
        self.client.generate.side_effect = [({'summary': 'First chunk finding'}, {}), ConnectionError('quota', True, retry_after=60)]
        source = 'a' * 6000 + 'b' * 6000
        with self.assertRaises(ConnectionError):
            ContextBudget(self.client).summarize(source)
        self.client.generate.reset_mock()
        self.client.generate.side_effect = None
        summary = ContextBudget(self.client).summarize(source)
        self.assertIn('First chunk finding', summary)
        self.assertEqual(self.client.generate.call_count, 1)
        self.assertEqual(self.client.generate.call_args.args[1]['source_fragment'], 'b' * 6000)

    def test_rate_limit_header_is_bounded_and_redacted(self):
        error = HTTPError('https://api.groq.com/openai/v1/chat/completions', 429, 'quota', {'Retry-After': '45'}, io.BytesIO(b'{"error":{"message":"private-data"}}'))
        result = http_error(error.url, error)
        self.assertEqual(result.retry_after, 45)
        self.assertNotIn('private-data', str(result))

    def test_kernel_waits_for_provider_reset(self):
        config = Config(Path(self.temp.name) / 'runtime')
        with patch('services.connections.CredentialStore.get', return_value={}):
            runtime = Runtime(config)
        self.addCleanup(runtime.close)
        task = runtime.submit('Say hello')
        with patch.object(runtime.planner, 'decide', side_effect=ConnectionError('rate limit', True, retry_after=60)):
            import time
            start = time.time()
            runtime.tick()
        current = runtime.tasks[task['id']]
        self.assertEqual(current['state'], 'RECOVERY')
        self.assertGreaterEqual(current['retry_at'], start + 60)

    def test_attachment_continuation_preserves_cursor_and_respects_denial(self):
        task = {'scopes': ['files'], 'goal': 'Summarize the attached report', 'attachments': [{'path': 'report.docx', 'name': 'report.docx'}], 'steps': [
            {'tool': 'files_read', 'result': {'path': 'report.docx', 'content': 'first', 'offset': 0, 'truncated': True, 'next_offset': '16000'}},
            {'tool': 'files_read', 'result': {'path': 'report.docx', 'content': 'second', 'offset': 16000, 'truncated': True, 'next_offset': '32000'}}]}
        action = attachment_continuation(task)
        self.assertEqual(action['arguments'], {'path': 'report.docx', 'offset': '32000'})
        self.assertFalse(action['complete_after'])
        task['history'] = [{'action': action, 'observation': 'USER DENIED this action. Do not repeat it.'}]
        self.assertIsNone(attachment_continuation(task))

        task['history'] = []
        task['steps'].append({'tool': 'files_read', 'result': {'path': 'report.docx', 'content': 'end', 'offset': 32000, 'truncated': False}})
        self.assertIsNone(attachment_continuation(task))

    def test_premature_completion_queues_read_instead_of_output(self):
        config = Config(Path(self.temp.name) / 'runtime')
        with patch('services.connections.CredentialStore.get', return_value={}):
            runtime = Runtime(config)
        self.addCleanup(runtime.close)
        path = config.workspace / 'report.docx'
        path.write_bytes(b'fixture; reading is mocked')
        task = runtime.submit('Summarize the attached report', scopes=['files'])
        current = runtime.tasks[task['id']]
        current['attachments'] = [{'path': str(path), 'name': path.name}]
        current['steps'] = [{'tool': 'files_read', 'result': {'path': str(path), 'content': 'first', 'offset': 0, 'truncated': True, 'next_offset': '16000'}}]
        with patch.object(runtime.planner, 'decide', return_value={'kind': 'finish', 'summary': 'Premature answer'}), patch.object(runtime.registry, 'execute') as execute:
            runtime.tick()
            execute.assert_not_called()
        self.assertEqual(current['pending']['tool'], 'files_read')
        self.assertEqual(current['pending']['arguments']['offset'], '16000')
