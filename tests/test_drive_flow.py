"""Drive folder/upload regressions. All remote writes are mocked."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.capabilities import CapabilityRegistry
from services.connections import ConnectionError, http_error


class DriveFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.google = MagicMock()
        self.registry = CapabilityRegistry(self.config, self.google)
        self.task = {'roots': [str(self.config.workspace)], 'scopes': ['files', 'drive']}

    def test_folder_then_upload_uses_returned_parent(self):
        self.google.call.return_value = {'id': 'folder_123', 'name': 'case study dbms'}
        folder = self.registry.execute({'tool': 'drive_create_folder', 'arguments': {'name': 'case study dbms'}}, self.task)
        self.assertEqual(self.google.call.call_args.args[2], {'name': 'case study dbms', 'mimeType': 'application/vnd.google-apps.folder'})
        self.assertTrue(self.registry.tools['drive_create_folder']['writes'])
        path = self.config.workspace / 'report.docx'
        path.write_bytes(b'file-content')
        self.registry.execute({'tool': 'drive_upload', 'arguments': {'source': str(path), 'parent_id': folder['id']}}, self.task)
        self.assertIn(b'"parents": ["folder_123"]', self.google.call.call_args.args[2])
        self.assertIn(b'file-content', self.google.call.call_args.args[2])

    def test_invalid_folder_input_never_calls_google(self):
        for args in ({'name': ''}, {'name': 'bad\nname'}, {'name': 'x' * 201}, {'name': 'folder', 'parent_id': '../escape'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.registry.execute({'tool': 'drive_create_folder', 'arguments': args}, self.task)
        self.google.call.assert_not_called()

    def test_disabled_drive_error_links_to_correct_project_and_redacts_payload(self):
        payload = {'error': {'message': 'private-value', 'details': [{'reason': 'SERVICE_DISABLED', 'metadata': {'consumer': 'projects/123456'}}]}}
        for prefix in ('drive', 'upload/drive'):
            url = f'https://www.googleapis.com/{prefix}/v3/files'
            error = HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(json.dumps(payload).encode()))
            result = http_error(url, error)
            self.assertIn('Enable Google Drive API', str(result))
            self.assertIn('drive.googleapis.com?project=123456', str(result))
            self.assertNotIn('private-value', str(result))
            self.assertTrue(result.request_rejected)

    def test_rejected_creation_is_not_an_uncertain_side_effect(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            runtime = Runtime(self.config)
        self.addCleanup(runtime.close)
        t = runtime.submit('Create a folder in Drive', scopes=['drive'])
        action = {'kind': 'tool', 'tool': 'drive_create_folder', 'arguments': {'name': 'folder'}, 'summary': 'Create folder', 'complete_after': True}
        with patch.object(runtime.planner, 'decide', return_value=action):
            runtime.tick()
        current = runtime.tasks[t['id']]
        self.assertEqual(current['state'], 'APPROVAL')
        runtime.control(t['id'], 'approve', {'action_id': current['pending']['id']})
        with patch.object(runtime.google, 'call', side_effect=ConnectionError('API disabled', request_rejected=True, status=403)):
            runtime.tick()
        self.assertEqual(current['state'], 'BLOCKED')
        self.assertIsNone(current['pending'])
        self.assertIn('not created', current['error'])
