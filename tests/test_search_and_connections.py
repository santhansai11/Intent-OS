"""Regressions for date searches, folder selection and account tool boundaries."""
import base64
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

from api.server import make_server
from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.capabilities import CapabilityRegistry
from services.connections import GoogleConnection, SCOPES, request_json
from services.gemini import AIKeys
from services.search_query import search_spec


class SearchRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.source = Path(self.temp.name) / 'documents'
        self.source.mkdir()
        self.registry = CapabilityRegistry(self.config, None)
        self.task = {'roots': [str(self.source)], 'search_roots': [str(self.source)], 'scopes': ['files']}

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, date, text='AWS architecture'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        stamp = datetime.fromisoformat(date).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def search(self, **args):
        return self.registry.collections.search(args, self.task)

    def test_screenshot_query_filters_before_content_reads(self):
        self.file('old.txt', '2026-08-30')
        self.file('boundary.txt', '2026-09-01T23:59:59')
        self.file('notes.txt', '2026-09-02')
        self.file('claws.txt', '2026-09-03', 'Claws are sharp')
        with patch.object(self.registry, 'read', wraps=self.registry.read) as read:
            result = self.search(query='gather all aws related files which were saved after september 1 2026')
        self.assertEqual(result['effective_topics'], ['aws'])
        self.assertEqual([m['name'] for m in result['matches']], ['notes.txt'])
        self.assertEqual(result['excluded_by_date'], 2)
        self.assertEqual(read.call_count, 2)

    def test_since_includes_day_and_before_excludes_day(self):
        self.file('first.txt', '2026-09-01')
        self.file('last.txt', '2026-09-02')
        result = self.search(query='AWS since September 1st, 2026 before 2026-09-02')
        self.assertEqual([m['name'] for m in result['matches']], ['first.txt'])

    def test_schema_date_filters_and_invalid_ranges(self):
        self.file('notes.txt', '2026-09-02')
        result = self.search(query='AWS', modified_after='2026-09-02', modified_before='2026-09-03')
        self.assertEqual(result['matched'], 1)
        for query in ('AWS after tomorrow', 'AWS after February 30 2026'):
            with self.assertRaises(ValueError):
                self.search(query=query)
        with self.assertRaises(ValueError):
            self.search(query='AWS', modified_after='2026-10-01', modified_before='2026-09-01')

    def test_original_file_date_survives_model_omission_or_wrong_timezone(self):
        self.file('notes.txt', '2026-09-02')
        self.task['goal'] = 'Gather AWS files which were saved after September 1 2026'
        for arguments in ({'query': 'AWS'}, {'query': 'AWS', 'modified_after': '2026-09-02T00:00:00Z'}):
            result = self.registry.execute({'tool': 'files_find_related', 'arguments': arguments}, self.task)
            self.assertEqual(result['matched'], 1)
            self.assertEqual(result['date_filters']['modified_after'], '2026-09-02T00:00:00')

    def test_project_pruning_and_explicit_override(self):
        self.file('repo/package.json', '2026-09-02', '{}')
        self.file('repo/aws.txt', '2026-09-02')
        self.file('tools/node_modules/aws.txt', '2026-09-02')
        self.file('notes.txt', '2026-09-02')
        result = self.search(query='AWS')
        self.assertEqual([m['name'] for m in result['matches']], ['notes.txt'])
        self.assertEqual(result['excluded_projects'], 1)
        self.assertEqual(result['scanned'], 1)
        result = self.search(query='AWS', include_projects='true')
        self.assertEqual(result['matched'], 2)
        self.task['search_roots'] = [str(self.source / 'repo')]
        self.assertEqual(self.search(query='AWS')['matched'], 1)

    def test_date_filter_is_part_of_resume_signature(self):
        self.file('notes.txt', '2026-09-02')
        self.task['pending'] = {'id': 'stable-action'}
        self.config.values['scan_batch_items'] = 1
        self.search(query='AWS', modified_after='2026-09-01')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.search(query='AWS', modified_after='2026-10-01')

    def test_default_runtime_roots_include_saved_sources(self):
        self.config.update({'roots': [str(self.source)]})
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        try:
            task = kernel.submit('Find AWS files')
            self.assertIn(str(self.source), task['search_roots'])
            normalized = kernel.submit('Find AWS files', roots=[self.source.as_posix()], search_roots=[self.source.as_posix()])
            self.assertEqual(normalized['search_roots'], [str(self.source)])
            empty = kernel.submit('No sources', roots=[], search_roots=[])
            self.assertEqual(empty['search_roots'], [])
        finally:
            kernel.close()

    def test_missing_reader_does_not_report_success_with_no_matches(self):
        self.file('notes.pdf', '2026-09-02')
        with patch.object(self.registry, 'read', side_effect=ModuleNotFoundError('pypdf')):
            with self.assertRaisesRegex(ValueError, 'document reader is missing'):
                self.search(query='AWS')


class ConnectionRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.google = MagicMock()
        self.registry = CapabilityRegistry(self.config, self.google)
        self.task = {'roots': [str(self.config.workspace)], 'scopes': ['files', 'drive', 'gmail', 'calendar', 'maps'], 'pending': {'id': 'test-action'}}

    def tearDown(self):
        self.temp.cleanup()

    def call(self, tool, **args):
        return self.registry.execute({'tool': tool, 'arguments': args}, self.task)

    def test_saved_gemini_key_precedes_environment_key(self):
        with patch('keyring.get_password', return_value='saved-key'), patch.dict(os.environ, {'GEMINI_API_KEY': 'stale-key'}):
            self.assertEqual(AIKeys(self.config).get(), 'saved-key')
        with patch('keyring.get_password', return_value=None), patch.dict(os.environ, {'GEMINI_API_KEY': 'env-key'}):
            self.assertEqual(AIKeys(self.config).get(), 'env-key')

    def test_keyring_errors_are_actionable_and_redacted(self):
        with patch('keyring.set_password', side_effect=RuntimeError('secret-value')), patch('keyring.get_keyring') as backend:
            backend.return_value.priority = 1
            with self.assertRaisesRegex(ValueError, 'secure OS credential store') as error:
                AIKeys(self.config).save('fake-key-long-enough')
            self.assertNotIn('secret-value', str(error.exception))

    def test_save_key_api_activates_gemini_and_test_sends_no_files(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        server = make_server(kernel, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def post(path, data):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/{path}', json.dumps(data).encode(),
                          {'Content-Type': 'application/json', 'X-IntentOS-Token': server.token})
            with urlopen(req) as response:
                return json.load(response)
        try:
            with patch.object(AIKeys, 'save') as save, patch.object(AIKeys, 'get', return_value='hidden-key'):
                response = post('ai/key', {'key': 'fake-key-long-enough'})
                self.assertTrue(response['configured'])
                self.assertEqual(self.config.provider, 'gemini')
                self.assertNotIn('hidden-key', json.dumps(response))
                save.assert_called_once()
            with patch('services.gemini.Gemini.generate', return_value=({'ok': True}, {})) as generate:
                self.assertTrue(post('ai/test', {'model': 'test-model'})['ok'])
                self.assertEqual(generate.call_args.args[1], {'message': 'Connection test'})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            kernel.close()

    def test_gmail_query_pagination_and_mime_read(self):
        self.call('gmail_search', query='from:a@example.com after:2026/09/01', page_token='next&token')
        self.assertIn('pageToken=next%26token', self.google.call.call_args.args[1])
        self.google.call.return_value = {'id': 'message1', 'payload': {'headers': [{'name': 'Subject', 'value': 'Hi'}], 'parts': [
            {'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(b'Hello').decode().rstrip('=')}},
            {'filename': 'file.pdf', 'body': {'attachmentId': 'att', 'size': 20}}]}}
        result = self.call('gmail_read', message_id='message1')
        self.assertEqual(result['content'], 'Hello')
        self.assertEqual(result['attachments'][0]['name'], 'file.pdf')

    def test_draft_does_not_send_and_rejects_header_injection(self):
        self.call('gmail_draft', to='a@example.com', subject='Hello', body='Draft')
        self.assertTrue(self.google.call.call_args.args[1].endswith('/drafts'))
        with self.assertRaises(ValueError):
            self.call('gmail_draft', to='a@example.com\nBcc:b@example.com', subject='Hello', body='Draft')

    def test_account_writes_require_approval_even_with_auto_outputs(self):
        for tool in ('gmail_draft', 'gmail_send', 'drive_upload', 'drive_download', 'calendar_update', 'calendar_delete'):
            self.assertTrue(self.registry.tools[tool]['writes'])
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        try:
            task = kernel.submit('Delete event', scopes=['calendar'], auto_outputs=True)
            action = {'tool': 'calendar_delete', 'arguments': {'event_id': 'event1'}, 'kind': 'tool', 'summary': 'Delete event'}
            with patch.object(kernel.planner, 'decide', return_value=action):
                kernel.tick()
            self.assertEqual(kernel.tasks[task['id']]['state'], 'APPROVAL')
        finally:
            kernel.close()

    def test_drive_download_preserves_existing_file_and_grants(self):
        existing = self.config.workspace / 'existing.txt'
        existing.write_text('keep')
        with self.assertRaises(ValueError):
            self.call('drive_download', file_id='file1', destination=str(existing))
        with self.assertRaises(ValueError):
            self.call('drive_download', file_id='file1', destination=str(Path(self.temp.name) / 'escape.txt'))
        self.google.call.assert_not_called()
        self.assertEqual(existing.read_text(), 'keep')

    def test_drive_download_exports_real_pdf_and_uploads_multipart(self):
        self.google.call.side_effect = [{'id': 'doc1', 'name': 'Doc', 'mimeType': 'application/vnd.google-apps.document'}, b'%PDF-test']
        result = self.call('drive_download', file_id='doc1', destination=str(self.config.workspace / 'doc.pdf'))
        self.assertEqual(Path(result['artifact']).read_bytes(), b'%PDF-test')
        self.assertIn('/export?mimeType=application%2Fpdf', self.google.call.call_args.args[1])
        self.google.call.side_effect = None
        self.call('drive_upload', source=result['artifact'])
        self.assertIn(b'%PDF-test', self.google.call.call_args.args[2])
        self.assertIn('multipart/related', self.google.call.call_args.kwargs['content_type'])

    def test_drive_read_and_denied_download(self):
        self.google.call.side_effect = [{'id': 'doc', 'name': 'Notes', 'mimeType': 'text/plain'}, b'notes']
        self.assertEqual(self.call('drive_read', file_id='doc')['content'], 'notes')
        self.google.call.side_effect = None
        self.google.call.return_value = {'capabilities': {'canDownload': False}}
        with self.assertRaisesRegex(ValueError, 'disabled'):
            self.call('drive_read', file_id='doc')

    def test_calendar_patch_delete_and_invalid_id(self):
        self.call('calendar_update', event_id='event1', title='Review', start='2026-10-12T10:00:00+05:30', end='2026-10-12T11:00:00+05:30', location='', description='')
        self.assertEqual(self.google.call.call_args.kwargs['method'], 'PATCH')
        self.assertEqual(self.call('calendar_delete', event_id='event1')['status'], 'deleted')
        self.assertEqual(self.google.call.call_args.kwargs['method'], 'DELETE')
        with self.assertRaises(ValueError):
            self.call('calendar_delete', event_id='../all')

    def test_maps_places_uses_key_header_and_field_mask(self):
        with patch.dict(os.environ, {'GOOGLE_MAPS_API_KEY': 'secret'}), patch('services.google_tools.request_json', return_value={'places': []}) as request:
            self.call('maps_places', query='cafes in Chennai')
            self.assertNotIn('secret', request.call_args.args[0])
            self.assertEqual(request.call_args.args[2]['X-Goog-Api-Key'], 'secret')
            self.assertIn('X-Goog-FieldMask', request.call_args.args[2])

    def test_transport_handles_204_and_binary_limits(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b''
        with patch('urllib.request.build_opener', return_value=opener):
            self.assertEqual(request_json('https://www.googleapis.com/test', method='DELETE'), {})
            self.assertEqual(opener.open.call_args.args[0].method, 'DELETE')
            opener.open.return_value.__enter__.return_value.read.return_value = b'raw bytes'
            self.assertEqual(request_json('https://www.googleapis.com/test', response_bytes=True), b'raw bytes')

    def test_oauth_expanded_scopes_and_no_offsite_tokens(self):
        store = MagicMock()
        store.get.return_value = {'scope': SCOPES['drive'], 'access_token': 'secret', 'expires_at': 9999999999}
        google = GoogleConnection(self.config, store)
        self.assertIn('drive', google.status()['services'])
        self.assertNotIn('secret', json.dumps(google.status()))
        with patch('services.connections.request_json') as request:
            with self.assertRaises(ValueError):
                google.call('drive', 'https://example.com/steal')
            request.assert_not_called()
