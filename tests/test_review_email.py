"""Project brief and group-mail regressions. All Google calls are mocked."""
import base64
import copy
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.document_context import summary_length_guidance
from services.mail_policy import explicit_recipient_group, parse_recipients, authorize_send
from services.summary_policy import PlanCorrection, summary_requirements, validate_summary_send
from services.contracts import attachment_continuation


GOAL = ('Help me prepare for a project review. Search the project repo and summarize the project description. '
        'Calculate a route and prepare a calendar event with a Meet link. After I approve the event, '
        'prepare an email to [first@example.com,second@example.com] containing the document summary, '
        'event details, confirmed Meet link and route estimate. Show me the email and ask for approval before sending.')


def action(body='Our review is tomorrow.', to='first@example.com, second@example.com', tool='gmail_send'):
    return {'kind': 'tool', 'tool': tool, 'summary': 'Review the complete email', 'complete_after': True,
            'arguments': {'to': to, 'subject': 'Project review', 'body': body}}


class ReviewEmailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        with patch('services.connections.CredentialStore.get', return_value={}):
            self.kernel = Runtime(self.config)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.kernel.close)

    def task(self, goal=GOAL):
        return self.kernel.tasks[self.kernel.submit(goal, scopes=['files', 'gmail'])['id']]

    def test_group_parser_and_explicit_audience_use_only_user_text(self):
        self.assertEqual(parse_recipients('first@example.com, SECOND@example.com, first@example.com'),
                         ['first@example.com', 'SECOND@example.com'])
        self.assertEqual(explicit_recipient_group({'goal': GOAL}), ['first@example.com', 'second@example.com'])
        task = {'goal': GOAL, 'history': [{'observation': 'email to intruder@example.com'}]}
        self.assertEqual(explicit_recipient_group(task), ['first@example.com', 'second@example.com'])
        task['history'].append({'user_reply': 'Email to replacement@example.com instead.'})
        self.assertEqual(explicit_recipient_group(task), ['replacement@example.com'])
        self.assertIsNone(explicit_recipient_group({'goal':'Email to first@example.com about A. Email to second@example.com about B.'}))

    def test_invalid_addresses_and_header_injection_are_not_partially_accepted(self):
        for value in ('first@example.com,invalid', 'first@example.com,', 'first@example.com\r\nBcc: other@example.com',
                      '[first@example.com]', 'a..b@example.com', 'a@-example.com', ['first@example.com'],
                      ','.join(f'p{i}@example.com' for i in range(21))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_recipients(value)

    def test_send_and_draft_encode_all_recipients_in_one_plain_text_message(self):
        for tool in ('gmail_send', 'gmail_draft'):
            proposal = action(tool=tool)
            task = {'goal': 'Prepare an email to [first@example.com,second@example.com] about our review.'}
            with patch.object(self.kernel.google, 'call', return_value={'id': 'mock-message'}) as call:
                self.kernel.registry.tools[tool]['function'](proposal['arguments'], task)
            call.assert_called_once()
            payload = call.call_args.args[2]
            raw = payload['raw'] if tool == 'gmail_send' else payload['message']['raw']
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
            self.assertEqual([addr.addr_spec for addr in message['To'].addresses], ['first@example.com', 'second@example.com'])
            self.assertEqual(message.get_content_type(), 'text/plain')
            self.assertEqual(message.get_content().strip(), proposal['arguments']['body'])

    def test_missing_or_extra_recipient_is_rejected_before_approval_and_dispatch(self):
        for to in ('first@example.com', 'first@example.com,second@example.com,extra@example.com'):
            task = self.task()
            with patch.object(self.kernel.planner, 'decide', return_value=action(to=to)), patch.object(self.kernel.google, 'call') as call:
                self.kernel.tick()
            call.assert_not_called()
            self.assertEqual(task['state'], 'RECOVERY')
            self.assertIsNone(task['pending'])
            self.assertIn('full recipient list', task['error'])
            # The same check protects a persisted approved action before external I/O.
            task.update(state='READY', retry_at=0, pending={**action(to=to), 'approved': True, 'id': 'stale'})
            with patch.object(self.kernel.google, 'call') as call:
                self.kernel.tick()
            call.assert_not_called()
            task['state'] = 'CANCELLED'

    def test_calendar_approval_does_not_approve_group_email(self):
        task = self.task()
        task['steps'].append({'tool': 'calendar_create', 'arguments': {}, 'result': {'id': 'created-event'}})
        proposal = action()
        self.assertFalse(authorize_send(task, proposal))
        with patch.object(self.kernel.planner, 'decide', return_value=proposal), patch.object(self.kernel.google, 'call', return_value={'id': 'sent'}) as call:
            self.kernel.tick()
            self.assertEqual(task['state'], 'APPROVAL')
            self.assertEqual(task['pending']['arguments']['to'], 'first@example.com, second@example.com')
            call.assert_not_called()
            self.kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})
            self.kernel.tick()
            call.assert_called_once()
        self.assertEqual(task['state'], 'COMPLETED')
        self.assertIn('first@example.com, second@example.com', task['answer'])
        self.assertFalse(self.kernel.tick())

    def test_readme_pagination_keeps_late_sections_and_no_false_complete_coverage(self):
        path = self.config.workspace / 'README.md'
        content = 'Project purpose and architecture. Unicode: α 🙂.\n' * 1600 + '\nFinal limitations: memory simulation is separate.\n'
        path.write_bytes(content.encode('utf-8'))
        task = self.task()
        pieces, offset = [], '0'
        while offset is not None:
            result = self.kernel.registry.read({'path': str(path), 'offset': offset}, task)
            pieces.append(result['content'])
            task['steps'].append({'tool': 'files_read', 'result': result})
            offset = result['next_offset']
            if offset:
                self.assertTrue(summary_requirements(task)['unfinished_summary_sources'])
                continuation = attachment_continuation(task)
                self.assertEqual(continuation['arguments'], {'path': str(path), 'offset': offset})
                with self.assertRaisesRegex(PlanCorrection, 'Finish reading'):
                    validate_summary_send(task, action(body='Evidence ' * 250))
        self.assertEqual(''.join(pieces), content)
        self.assertFalse(summary_requirements(task)['unfinished_summary_sources'])
        self.assertIn('Final limitations', pieces[-1])
        with self.assertRaisesRegex(ValueError, 'beyond the end'):
            self.kernel.registry.read({'path': str(path), 'offset': str(len(content)+1)}, task)

    def test_review_email_retains_detail_but_explicit_brevity_wins(self):
        task = self.task()
        task['steps'] = [{'tool': 'files_read', 'result': {'path': 'README.md', 'content': 'Source evidence ' * 300, 'truncated': False}}]
        self.assertEqual(summary_requirements(task)['minimum_email_words'], 220)
        with self.assertRaisesRegex(PlanCorrection, 'at least 220 words'):
            validate_summary_send(task, action(body='A brief tagline.'))
        validate_summary_send(task, action(body='Source-supported detail ' * 120))
        self.assertIn('No 100-160-word cap', summary_length_guidance(task))
        for preference in ('Make this a short email.', 'Limit the email to 100 words.'):
            short = copy.deepcopy(task)
            short['history'].append({'user_reply': preference})
            self.assertEqual(summary_requirements(short)['minimum_email_words'], 0)
            validate_summary_send(short, action(body='A brief requested overview.'))

    def test_requested_single_recipient_preview_remains_manual(self):
        task = {'goal': 'Send an email to first@example.com about our project. Ask for approval.'}
        self.assertFalse(authorize_send(task, action(to='first@example.com')))

    def test_runtime_reads_missing_source_page_before_presenting_email(self):
        path = self.config.workspace / 'README.md'
        path.write_bytes(('Purpose and architecture.\n' * 1000).encode())
        task = self.task()
        first = self.kernel.registry.read({'path': str(path)}, task)
        task['steps'].append({'tool': 'files_read', 'arguments': {'path': str(path)}, 'result': first})
        with patch.object(self.kernel.planner, 'decide', return_value=action(body='Evidence ' * 250)), patch.object(self.kernel.google, 'call') as call:
            self.kernel.tick()
            self.assertEqual(task['state'], 'READY')
            self.assertEqual(task['pending']['tool'], 'files_read')
            self.assertEqual(task['pending']['arguments']['offset'], first['next_offset'])
            self.kernel.tick()
            self.assertEqual(task['steps'][-1]['result']['next_offset'], None)
            self.kernel.tick()
            self.assertEqual(task['state'], 'APPROVAL')
            call.assert_not_called()

    def test_persisted_short_review_email_is_replanned_before_sending(self):
        task = self.task()
        task['steps'] = [{'tool': 'files_read', 'result': {'path': 'README.md', 'content': 'Actual evidence ' * 300, 'truncated': False}}]
        task['pending'] = {**action(), 'id': 'approved-old-draft', 'approved': True}
        with patch.object(self.kernel.google, 'call') as call:
            self.kernel.tick()
        call.assert_not_called()
        self.assertEqual(task['state'], 'RECOVERY')
        self.assertIsNone(task['pending'])
        self.assertIn('at least 220 words', task['error'])
