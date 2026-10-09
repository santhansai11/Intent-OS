"""Durability, scheduling, approval and HTTP boundary regressions (no live model/API)."""
import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from api.server import make_server
from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.agent import OllamaPlanner
from services.connections import ConnectionError, GoogleConnection, SCOPES


def action(tool, **arguments):
    return {'kind': 'tool', 'summary': 'Run ' + tool, 'tool': tool, 'arguments': arguments}


def finish(text='Complete'):
    return {'kind': 'finish', 'summary': text, 'tool': '', 'arguments': {}}


class ScriptedPlanner:
    """Deterministic test double only. The application uses PlannerRouter."""
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def decide(self, task, catalog):
        self.calls += 1
        value = self.items.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.keyring = patch('services.connections.CredentialStore.get', return_value={})
        self.keyring.start()
        self.kernel = Runtime(self.config, ScriptedPlanner())

    def tearDown(self):
        self.kernel.close()
        self.keyring.stop()
        self.temp.cleanup()

    def submit(self, *steps, **kwargs):
        self.kernel.planner = ScriptedPlanner(*steps)
        ident = self.kernel.submit('Test a real capability', **kwargs)['id']
        return self.kernel.tasks[ident]

    def approve(self, task):
        self.kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})

    def restart(self, planner=None):
        self.kernel.close()
        self.kernel = Runtime(self.config, planner or ScriptedPlanner())

    def test_write_waits_for_exact_approval_and_survives_restart(self):
        task = self.submit(action('files_write', path='report.md', content='Actual content'), finish())
        self.kernel.tick()
        self.assertEqual(task['state'], 'APPROVAL')
        self.assertFalse((self.config.workspace / 'report.md').exists())
        with self.assertRaises(ValueError):
            self.kernel.control(task['id'], 'approve', {'action_id': 'stale'})
        self.approve(task)
        self.kernel.tick()
        self.assertEqual((self.config.workspace / 'report.md').read_text(), 'Actual content')
        self.assertEqual(len(task['steps']), 1)
        self.restart(ScriptedPlanner(finish()))
        self.kernel.tick()
        restored = self.kernel.tasks[task['id']]
        self.assertEqual(restored['state'], 'COMPLETED')
        self.assertEqual(len(restored['steps']), 1)

    def test_approval_is_not_shared_between_intents(self):
        self.kernel.planner = ScriptedPlanner(action('files_write', path='one.md', content='one'),
                                             action('files_write', path='two.md', content='two'))
        one = self.kernel.submit('one')['id']
        two = self.kernel.submit('two')['id']
        self.kernel.tick()
        self.approve(self.kernel.tasks[one])
        self.kernel.tick()
        self.assertEqual(self.kernel.tasks[two]['state'], 'APPROVAL')
        self.assertFalse(self.kernel.tasks[two]['pending']['approved'])

    def test_read_grant_is_per_goal(self):
        task = self.submit(action('files_list', path='.'), scopes=['system'])
        self.kernel.tick()
        self.assertEqual(task['state'], 'APPROVAL')
        self.approve(task)
        self.kernel.tick()
        self.assertEqual(len(task['steps']), 1)

    def test_deny_never_dispatches(self):
        task = self.submit(action('files_write', path='no.md', content='no'), finish('Declined'))
        self.kernel.tick()
        self.kernel.control(task['id'], 'deny', {'action_id': task['pending']['id']})
        self.kernel.tick()
        self.assertFalse((self.config.workspace / 'no.md').exists())
        self.assertEqual(task['state'], 'COMPLETED')

    def test_path_traversal_and_private_state_denied(self):
        task = self.submit(action('files_read', path='../runtime/settings.json'))
        self.kernel.tick()
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(task['steps'], [])
        broad = {**task, 'roots': [self.temp.name]}
        with self.assertRaises(ValueError):
            self.kernel.registry.path(str(self.config.root / 'kernel.sqlite3'), broad)
        with self.assertRaises(ValueError):
            self.kernel.registry.path(str(Path(self.temp.name) / '.env'), broad)

    def test_symlink_escape_denied(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        link = self.config.workspace / 'link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation requires privileges on this Windows host')
        task = self.submit(action('files_read', path='link/secret.txt'))
        self.kernel.tick()
        self.assertEqual(task['state'], 'BLOCKED')

    def test_unknown_tool_and_extra_arguments_denied(self):
        for call in [action('shell', command='echo test'), action('system_status', arbitrary='value')]:
            task = self.submit(call)
            self.kernel.tick()
            self.assertEqual(task['state'], 'BLOCKED')

    def test_restart_never_replays_uncertain_write(self):
        task = self.submit(action('files_write', path='maybe.md', content='maybe'))
        self.kernel.tick()
        self.approve(task)
        task['state'] = 'RUNNING'
        self.kernel._save(task, 'dispatch', 'Simulated crash after dispatch')
        self.restart()
        restored = self.kernel.tasks[task['id']]
        self.assertEqual(restored['state'], 'REVIEW')
        self.assertFalse(self.kernel.tick())
        with self.assertRaises(ValueError):
            self.kernel.control(task['id'], 'retry', {})

    def test_restart_retries_interrupted_read(self):
        task = self.submit(action('system_status'))
        self.kernel.tick()
        task['state'] = 'RUNNING'
        self.kernel._save(task, 'dispatch', 'Interrupted read')
        self.restart()
        self.kernel.tick()
        self.assertEqual(len(self.kernel.tasks[task['id']]['steps']), 1)

    def test_write_failure_requires_review_and_no_automatic_retry(self):
        task = self.submit(action('files_write', path='file.md', content='x'))
        self.kernel.tick()
        self.approve(task)
        with patch.object(self.kernel.registry, 'execute', side_effect=ConnectionError('Timed out', True)) as execute:
            self.kernel.tick()
            self.assertEqual(task['state'], 'REVIEW')
            self.assertFalse(self.kernel.tick())
            self.assertEqual(execute.call_count, 1)

    def test_read_failure_backoff_then_checkpoint(self):
        task = self.submit(action('system_status'))
        self.kernel.tick()
        with patch.object(self.kernel.registry, 'execute', side_effect=ConnectionError('Unavailable', True)):
            self.kernel.tick()
        self.assertEqual(task['state'], 'RECOVERY')
        self.assertGreater(task['retry_at'], time.time())
        self.assertFalse(self.kernel.tick())
        task['retry_at'] = 0
        self.kernel.tick()
        self.assertEqual(len(task['steps']), 1)
        self.assertEqual(task['attempts'], 0)

    def test_invalid_model_decision_can_be_resumed(self):
        task = self.submit(ConnectionError('Select a model'), finish())
        self.kernel.tick()
        self.assertEqual(task['state'], 'BLOCKED')
        self.kernel.control(task['id'], 'resume')
        self.kernel.tick()
        self.assertEqual(task['state'], 'COMPLETED')

    def test_followup_question_is_persistent(self):
        task = self.submit({'kind': 'ask', 'summary': 'Which folder?', 'tool': '', 'arguments': {}})
        self.kernel.tick()
        self.restart(ScriptedPlanner(finish('Thanks')))
        self.kernel.control(task['id'], 'reply', {'text': 'The workspace'})
        self.kernel.tick()
        restored = self.kernel.tasks[task['id']]
        self.assertEqual(restored['state'], 'COMPLETED')
        self.assertEqual(restored['history'][-1]['user_reply'], 'The workspace')

    def test_equal_priorities_alternate_quanta(self):
        one = self.kernel.submit('one')['id']
        two = self.kernel.submit('two')['id']
        self.kernel.planner = ScriptedPlanner(action('system_status'), action('system_status'))
        self.kernel.tick()
        self.kernel.tick()
        self.assertIsNotNone(self.kernel.tasks[one]['pending'])
        self.assertIsNotNone(self.kernel.tasks[two]['pending'])
        self.assertEqual(self.kernel.tasks[one]['steps'], [])

    def test_deadline_then_aging_selection(self):
        ordinary = self.kernel.submit('ordinary')['id']
        urgent = self.kernel.submit('deadline', deadline=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())['id']
        self.assertEqual(self.kernel._choose()['id'], urgent)
        self.kernel.tasks[ordinary]['queued_at'] = time.time() - 60
        self.assertEqual(self.kernel._choose()['id'], ordinary)
        self.assertEqual(self.kernel.policy, 'aging')

    def test_resource_lock_excludes_dispatch(self):
        self.kernel.submit('one')
        self.kernel.locks['local-model'] = 'another-intent'
        self.assertIsNone(self.kernel._choose())

    def test_pause_and_cancel_at_safe_boundary(self):
        task = self.submit(action('system_status'))
        self.kernel.tick()
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            release.wait(3)
            return {'done': True}
        with patch.object(self.kernel.registry, 'execute', side_effect=slow):
            thread = threading.Thread(target=self.kernel.tick)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.kernel.control(task['id'], 'cancel')
            self.assertEqual(task['state'], 'CANCELLING')
            release.set()
            thread.join(3)
        self.assertEqual(task['state'], 'CANCELLED')
        self.assertEqual(len(task['steps']), 1)
        self.assertEqual(self.kernel.locks, {})

    def test_paused_goal_does_not_run(self):
        task = self.submit(finish())
        self.kernel.control(task['id'], 'pause')
        self.assertFalse(self.kernel.tick())
        self.kernel.control(task['id'], 'resume')
        self.kernel.tick()
        self.assertEqual(task['state'], 'COMPLETED')

    def test_second_kernel_is_rejected(self):
        with self.assertRaises(RuntimeError):
            Runtime(self.config, ScriptedPlanner())

    def test_second_http_listener_cannot_share_port(self):
        server = make_server(self.kernel, 0)
        try:
            with self.assertRaises(OSError):
                make_server(self.kernel, server.server_port)
        finally:
            server.server_close()

    def test_reject_unknown_root_and_unzoned_deadline(self):
        for args in [{'roots': [self.temp.name]}, {'deadline': '2026-12-01T12:00:00'}, {'scopes': ['shell']}, {'priority': 'invalid'}]:
            with self.assertRaises(ValueError):
                self.kernel.submit('invalid grant', **args)

    def test_empty_search_has_no_fabricated_matches(self):
        task = self.submit(action('files_search', path='.', query='absent'))
        self.kernel.tick()
        self.kernel.tick()
        self.assertEqual(task['steps'][0]['result']['matches'], [])

    def test_ollama_uses_configured_model_and_native_structured_protocol(self):
        self.config.update({'model': 'installed-local-model'})
        task = self.submit()
        with patch('planner.agent.request_json', return_value={'message': {'content': json.dumps(finish('A useful answer'))}}) as request:
            decision = OllamaPlanner(self.config).decide(task, self.kernel.registry.catalog())
            self.assertEqual(decision['summary'], 'A useful answer')
            endpoint, body = request.call_args.args[:2]
            self.assertTrue(endpoint.endswith('/api/chat'))
            self.assertEqual(body['model'], 'installed-local-model')
            self.assertFalse(body['stream'])
            self.assertNotIn('think', body)  # Preserve the model's default reasoning mode.
            self.assertNotIn('temperature', body['options'])
            self.assertIn('kind', body['format']['properties'])
            self.assertNotIn('Authorization', str(request.call_args))

    def test_malformed_model_response_never_executes(self):
        self.config.update({'model': 'installed-local-model'})
        task = self.submit()
        self.kernel.planner = OllamaPlanner(self.config)
        with patch('planner.agent.request_json', return_value={'message': {'content': 'not JSON'}}):
            self.kernel.tick()
        self.assertEqual(task['state'], 'RECOVERY')
        self.assertEqual(task['steps'], [])
        self.assertIsNone(task['pending'])

    def test_cloud_alias_rejected_before_private_context_is_sent(self):
        self.config.update({'model': 'innocent-looking-alias'})
        task = self.submit()
        with patch('planner.agent.request_json', return_value={'remote_host': 'https://ollama.com'}) as request:
            with self.assertRaises(ConnectionError):
                OllamaPlanner(self.config).decide(task, [])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[1], {'model': 'innocent-looking-alias'})

    def test_model_context_is_bounded_without_losing_checkpoint_summary(self):
        self.config.update({'model': 'installed-local-model'})
        task = self.submit()
        task['history'] = [{'action': None, 'observation': 'x' * 100000} for _ in range(30)]
        task['steps'] = [{'tool': 'files_write', 'summary': 'Saved the draft', 'result': {'artifact': 'draft.md'}}]
        with patch('planner.agent.request_json', return_value={'message': {'content': json.dumps(finish())}}) as request:
            OllamaPlanner(self.config).decide(task, [])
            context = json.loads(request.call_args.args[1]['messages'][1]['content'])
            self.assertLess(len(json.dumps(context)), 26000)
            self.assertEqual(context['completed_checkpoints'][0]['artifact'], 'draft.md')
            self.assertLess(len(json.dumps(request.call_args.args[1]['messages'])), 29000)

    def test_model_receives_completed_action_then_actual_observation(self):
        self.config.update({'model': 'installed-local-model'})
        task = self.submit()
        task['history'] = [{'action': {'tool': 'files_list', 'summary': 'Inspect folder',
                                      'arguments': {'path': '.'}},
                            'observation': {'entries': [{'name': 'actual.pdf'}]}}]
        with patch('planner.agent.request_json', return_value={'message': {'content': json.dumps(finish())}}) as request:
            OllamaPlanner(self.config).decide(task, [])
            messages = request.call_args.args[1]['messages']
            self.assertEqual(messages[2]['role'], 'assistant')
            self.assertEqual(json.loads(messages[2]['content'])['tool'], 'files_list')
            self.assertIn('actual.pdf', messages[3]['content'])
            self.assertIn('next unfinished', messages[-1]['content'])

    def test_artifact_and_audit_are_persisted_together(self):
        task = self.submit(action('files_write', path='file.txt', content='data'))
        self.kernel.tick()
        self.approve(task)
        self.kernel.tick()
        row = json.loads(self.kernel.db.execute('SELECT data FROM processes WHERE id=?', (task['id'],)).fetchone()[0])
        event = self.kernel.db.execute("SELECT kind FROM events WHERE intent_id=? ORDER BY seq DESC", (task['id'],)).fetchone()
        self.assertEqual(row['steps'][0]['result']['status'], 'written')
        self.assertEqual(event[0], 'checkpoint')

    def test_http_session_csrf_and_real_artifact_download(self):
        server = make_server(self.kernel, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(body, token='', origin=None):
            headers = {'Content-Type': 'application/json', 'X-IntentOS-Token': token}
            if origin:
                headers['Origin'] = origin
            return opener.open(urllib.request.Request(base + '/api/intents', json.dumps(body).encode(), headers), timeout=3)
        try:
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                post({'text': 'no token'})
            self.assertEqual(rejected.exception.code, 403)
            token = json.load(opener.open(base + '/api/session'))['token']
            with self.assertRaises(urllib.error.HTTPError):
                post({'text': 'foreign origin'}, token, 'https://example.com')
            self.kernel.planner = ScriptedPlanner(action('files_write', path='api.txt', content='from api'), finish())
            output_folder = str(Path(self.temp.name) / 'external-api-output')
            task = self.kernel.tasks[json.load(post({'text': 'write a file', 'output_folder': output_folder}, token))['id']]
            self.kernel.tick()
            self.approve(task)
            self.kernel.tick()
            self.assertEqual(task['steps'][0]['result']['artifact'], str(Path(output_folder) / 'api.txt'))
            self.assertFalse((self.config.workspace / 'api.txt').exists())
            url = base + '/api/artifact?intent=' + task['id'] + '&step=' + task['steps'][0]['id']
            response = opener.open(url)
            self.assertEqual(response.read(), b'from api')
            self.assertIn('attachment', response.headers['Content-Disposition'])
            request = urllib.request.Request(base + '/api/status', headers={'Host': 'attacker.example'})
            with self.assertRaises(urllib.error.HTTPError):
                opener.open(request)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class MemoryStore:
    def __init__(self):
        self.tokens = {}
    def get(self):
        return self.tokens.copy()
    def save(self, data):
        self.tokens = data.copy()
    def delete(self):
        self.tokens.clear()


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore()
        self.google = GoogleConnection(Config(Path(self.temp.name) / 'runtime'), self.store)
        self.google.client_id = 'test-client'
        self.google.client_secret = 'test-secret'

    def tearDown(self):
        self.temp.cleanup()

    def test_oauth_state_pkce_and_one_time_callback(self):
        from urllib.parse import urlsplit, parse_qs
        query = parse_qs(urlsplit(self.google.begin(['calendar'])).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['scope'], [SCOPES['calendar']])
        with self.assertRaises(ValueError):
            self.google.callback('bad-state', 'code')
        with patch('services.connections.request_json', return_value={'access_token': 'secret-access', 'refresh_token': 'secret-refresh', 'scope': SCOPES['calendar']}) as request:
            self.google.callback(query['state'][0], 'code')
            self.assertIn('code_verifier', request.call_args.args[1])
        self.assertTrue(self.google.status()['connected'])
        self.assertNotIn('secret-access', json.dumps(self.google.status()))
        with self.assertRaises(ValueError):
            self.google.callback(query['state'][0], 'code')

    def test_expired_oauth_state_is_rejected(self):
        self.google.pending['expired'] = ('verifier', time.time() - 1)
        with self.assertRaises(ValueError):
            self.google.callback('expired', 'code')

    def test_missing_scope_does_not_call_google(self):
        with patch('services.connections.request_json') as request:
            with self.assertRaises(ConnectionError):
                self.google.call('gmail', 'https://gmail.googleapis.com')
            request.assert_not_called()

    def test_refresh_preserves_refresh_token_and_disconnect_clears(self):
        self.google.tokens = {'refresh_token': 'refresh', 'scope': SCOPES['calendar'], 'expires_at': 0}
        with patch('services.connections.request_json', side_effect=[{'access_token': 'new', 'expires_in': 3600}, {'items': []}]) as request:
            result = self.google.call('calendar', 'https://www.googleapis.com/calendar/v3/calendars/primary/events')
            self.assertEqual(result, {'items': []})
            self.assertEqual(self.store.tokens['refresh_token'], 'refresh')
            self.assertEqual(request.call_args.args[2]['Authorization'], 'Bearer new')
        self.google.disconnect()
        self.assertFalse(self.google.status()['connected'])
