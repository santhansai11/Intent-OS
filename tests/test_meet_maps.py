"""Meet, Calendar conferencing, Maps keys and read-only service checks."""
import json
import os
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from api.server import make_server

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.capabilities import CapabilityRegistry
from services.connections import GoogleConnection, SCOPES, ConnectionError
from services.google_checks import check_service
from services.maps_keys import MapsKeys


class MeetMapsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.google = MagicMock()
        self.registry = CapabilityRegistry(self.config, self.google)
        self.task = {'scopes': ['meet', 'calendar', 'maps'], 'roots': [], 'pending': {'id': 'same-action'}}

    def call(self, tool, **args):
        return self.registry.execute({'tool': tool, 'arguments': args}, self.task)

    def test_meet_create_get_and_end_use_exact_endpoints(self):
        self.google.call.return_value = {'name': 'spaces/abc', 'meetingUri': 'https://meet.google.com/abc-defg-hij'}
        result = self.call('meet_create')
        self.assertEqual(result['name'], 'spaces/abc')
        self.assertEqual(self.google.call.call_args.args, ('meet', 'https://meet.googleapis.com/v2/spaces', {}))
        self.call('meet_get', name='spaces/abc')
        self.assertEqual(self.google.call.call_args.args[1], 'https://meet.googleapis.com/v2/spaces/abc')
        self.call('meet_end', name='spaces/abc')
        self.assertTrue(self.google.call.call_args.args[1].endswith('/spaces/abc:endActiveConference'))
        for name in ('meet_create', 'meet_end'):
            self.assertTrue(self.registry.tools[name]['writes'])

    def test_resource_validation_and_pagination(self):
        for name in ('https://evil.example', 'spaces/../bad', 'spaces/a?key=secret', 'spaces/a/members/b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.call('meet_get', name=name)
        self.google.call.assert_not_called()
        self.google.call.return_value = {'transcriptEntries': [{'text': 'Evidence'}], 'nextPageToken': 'next'}
        result = self.call('meet_transcript_entries', transcript='conferenceRecords/abc/transcripts/def', page_token='a&b')
        self.assertEqual(result['nextPageToken'], 'next')
        self.assertEqual(parse_qs(urlsplit(self.google.call.call_args.args[1]).query)['pageToken'], ['a&b'])

    def test_calendar_meet_request_has_stable_ids_and_no_attendees(self):
        args = {'title': 'Review', 'start': '2026-10-22T10:00:00+05:30', 'end': '2026-10-22T11:00:00+05:30', 'location': '', 'description': '', 'meet_link': 'true'}
        self.call('calendar_create', **args)
        url, body = self.google.call.call_args.args[1:]
        self.assertTrue(url.endswith('?conferenceDataVersion=1'))
        self.assertEqual(body['conferenceData']['createRequest']['requestId'], body['id'])
        self.assertNotIn('attendees', body)
        self.call('calendar_create', **args)
        self.assertEqual(self.google.call.call_args.args[2], body)
        args.pop('meet_link')
        self.call('calendar_create', **args)
        self.assertNotIn('conferenceData', self.google.call.call_args.args[2])

    def test_oauth_adds_meet_without_losing_existing_scopes(self):
        with patch.dict(os.environ, {'GOOGLE_CLIENT_ID': 'client', 'GOOGLE_CLIENT_SECRET': 'secret'}):
            google = GoogleConnection(self.config, MagicMock(get=MagicMock(return_value={})))
        query = parse_qs(urlsplit(google.begin(['calendar', 'drive', 'gmail', 'meet'])).query)
        self.assertIn(SCOPES['calendar'], query['scope'][0])
        self.assertIn('https://www.googleapis.com/auth/meetings.space.created', query['scope'][0])
        self.assertIn('https://www.googleapis.com/auth/meetings.space.readonly', query['scope'][0])
        self.assertEqual(query['code_challenge_method'], ['S256'])

    def test_service_host_and_scope_boundary(self):
        store = MagicMock(get=MagicMock(return_value={'scope': SCOPES['calendar'], 'access_token': 'hidden', 'expires_at': time.time()+3600}))
        google = GoogleConnection(self.config, store)
        with patch('services.connections.request_json') as request:
            with self.assertRaises(ConnectionError):
                google.call('meet', 'https://meet.googleapis.com/v2/spaces/abc')
            with self.assertRaises(ValueError):
                google.call('calendar', 'https://meet.googleapis.com/v2/spaces/abc')
            with self.assertRaises(ValueError):
                google.call('meet', 'https://meet.googleapis.com.evil.example/v2/spaces/abc')
            request.assert_not_called()

    def test_maps_key_precedence_and_no_ai_provider_change(self):
        original = self.config.provider
        with patch('keyring.get_password', return_value='saved-maps-key') as lookup, patch.dict(os.environ, {'GOOGLE_MAPS_API_KEY': 'env-key'}):
            self.assertEqual(MapsKeys(self.config).get(), 'saved-maps-key')
            self.assertEqual(lookup.call_args.args[1], 'maps-api-key')
        self.assertEqual(self.config.provider, original)

    def test_connection_checks_never_create_anything(self):
        for service in ('calendar', 'drive', 'gmail', 'meet'):
            self.assertTrue(check_service(self.config, self.google, self.registry, service)['ok'])
            self.assertEqual(len(self.google.call.call_args.args), 2)
        with patch.object(MapsKeys, 'get', return_value='key'), patch('services.google_tools.GoogleTools.maps_places', return_value={}), patch.object(self.registry, 'maps_route', side_effect=ConnectionError('Routes disabled')):
            result = check_service(self.config, self.google, self.registry, 'maps')
            self.assertFalse(result['ok'])
            self.assertTrue(result['checks']['places']['ok'])
            self.assertFalse(result['checks']['routes']['ok'])

    def test_meet_ending_requires_exact_action_approval(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            runtime = Runtime(self.config)
        self.addCleanup(runtime.close)
        task = runtime.submit('End my meeting', scopes=['meet'])
        action = {'kind': 'tool', 'tool': 'meet_end', 'arguments': {'name': 'spaces/abc'}, 'summary': 'End meeting'}
        with patch.object(runtime.planner, 'decide', return_value=action), patch.object(runtime.google, 'call') as call:
            runtime.tick()
            call.assert_not_called()
        self.assertEqual(runtime.tasks[task['id']]['state'], 'APPROVAL')

    def test_http_maps_save_redacts_key_and_meet_check_is_read_only(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            runtime = Runtime(self.config)
        self.addCleanup(runtime.close)
        server = make_server(runtime, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def post(path, data):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/{path}', json.dumps(data).encode(), {'Content-Type': 'application/json', 'X-IntentOS-Token': server.token})
            with urlopen(req) as response:
                return json.load(response)
        try:
            original = self.config.provider
            with patch.object(MapsKeys, 'save') as save, patch.object(MapsKeys, 'get', return_value='private-maps-key'):
                result = post('google/maps/key', {'key': 'private-maps-key'})
                save.assert_called_once_with('private-maps-key')
                self.assertEqual(result, {'configured': True})
                self.assertEqual(self.config.provider, original)
            with patch.object(runtime.google, 'call', return_value={}) as call:
                result = post('google/test', {'service': 'meet'})
                self.assertTrue(result['ok'])
                self.assertEqual(call.call_args.args, ('meet', 'https://meet.googleapis.com/v2/conferenceRecords?pageSize=1'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
