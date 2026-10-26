"""MIME, file disclosure and group-send regressions; never sends real mail."""
import base64
import io
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.contracts import contract_status
from services.mail_policy import explicit_recipient_group, authorize_send
from services.summary_policy import PlanCorrection


class MailAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        with patch('services.connections.CredentialStore.get', return_value={}):
            self.kernel = Runtime(self.config)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.kernel.close)

    def task(self, **kwargs):
        task = self.kernel.submit('Send the report to first@example.com and second@example.com in one email.',
                                  scopes=['files', 'gmail'], **kwargs)
        return self.kernel.tasks[task['id']]

    def action(self, paths, tool='gmail_send'):
        return {'kind': 'tool', 'tool': tool, 'summary': 'Review the email and files', 'complete_after': True,
                'arguments': {'to': 'first@example.com,second@example.com', 'subject': 'Report',
                              'body': 'Hello,\nThe report is attached.\nThanks', 'attachments': paths}}

    def file(self, name='report.txt', data=b'actual file bytes\x00\xff'):
        path = self.config.workspace / name
        path.write_bytes(data)
        return str(path)

    def test_common_group_phrasing_cannot_be_split_into_single_recipient_actions(self):
        self.assertEqual(explicit_recipient_group({'goal': 'Email to first@example.com a summary of messages from source@example.com.'}), ['first@example.com'])
        self.assertIsNone(explicit_recipient_group({'goal': 'Send the report to first@example.com and send a different email to second@example.com.'}))
        for text in ('Send the report to first@example.com and second@example.com in one email.',
                     'Send the report to first@example.com, second@example.com.',
                     'Send the report to first@example.com and second@example.com in one email, not separately.',
                     'Email to first@example.com and second@example.com. Do not send separate emails.',
                     'first@example.com, second@example.com: email both accounts the report.',
                     'Email the attached file. Recipients: first@example.com; second@example.com',
                     'Send an email with the report to [first@example.com,second@example.com].'):
            with self.subTest(text=text):
                self.assertEqual(explicit_recipient_group({'goal': text}), ['first@example.com', 'second@example.com'])
                task = self.task()
                task['goal'] = text
                action = self.action([])
                action['arguments']['to'] = 'first@example.com'
                with self.assertRaises(PlanCorrection):
                    self.kernel.registry.validate(action, task)

    def test_one_mime_message_contains_both_recipients_and_exact_binary_files(self):
        paths = [self.file('résumé.pdf', b'%PDF-test\x00\xff'), self.file('notes.txt', b'notes')]
        for tool in ('gmail_send', 'gmail_draft'):
            task, action = self.task(), self.action(paths, tool)
            self.kernel.registry.validate(action, task)
            with patch.object(self.kernel.google, 'call', return_value={'id': 'mock-id'}) as call:
                self.kernel.registry.tools[tool]['function'](action['arguments'], task)
            call.assert_called_once()
            payload = call.call_args.args[2]
            raw = payload['raw'] if tool == 'gmail_send' else payload['message']['raw']
            mail = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
            self.assertEqual([a.addr_spec for a in mail['To'].addresses], ['first@example.com', 'second@example.com'])
            self.assertEqual(mail.get_body(preferencelist=('plain',)).get_content().strip(), action['arguments']['body'])
            parts = list(mail.iter_attachments())
            self.assertEqual([p.get_filename() for p in parts], ['résumé.pdf', 'notes.txt'])
            self.assertEqual([p.get_payload(decode=True) for p in parts], [Path(p).read_bytes() for p in paths])

    def test_uploaded_email_file_is_required_but_not_a_summary_source(self):
        upload = self.kernel.uploads.receive(io.BytesIO(b'content'), 'report.pdf', 7)
        task = self.task(attachments=[{'id': upload['id'], 'role': 'email'}])
        self.assertEqual(contract_status(task)['required_attachments'], 0)
        with self.assertRaisesRegex(PlanCorrection, 'every upload'):
            self.kernel.registry.validate(self.action([]), task)
        action = self.action([upload['path']])
        self.kernel.registry.validate(action, task)
        self.assertEqual(action['mail_files'][0]['bytes'], 7)

    def test_source_upload_is_never_automatically_disclosed(self):
        upload = self.kernel.uploads.receive(io.BytesIO(b'private source'), 'source.txt', 14)
        task = self.task(attachments=[{'id': upload['id'], 'role': 'source'}])
        action = self.action([])
        self.kernel.registry.validate(action, task)
        self.assertEqual(action['mail_files'], [])

    def test_files_require_review_and_changed_bytes_block_dispatch(self):
        path = self.file(data=b'original')
        task, action = self.task(), self.action([path])
        task['goal'] = 'Send an email to first@example.com about the report.'
        action['arguments']['to'] = 'first@example.com'
        self.assertFalse(authorize_send(task, action))
        with patch.object(self.kernel.planner, 'decide', return_value=action):
            self.kernel.tick()
        self.assertEqual(task['state'], 'APPROVAL')
        self.assertEqual(task['pending']['mail_files'][0]['name'], 'report.txt')
        self.kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})
        Path(path).write_bytes(b'modified')
        with patch.object(self.kernel.google, 'call') as call:
            self.kernel.tick()
        call.assert_not_called()
        self.assertEqual(task['state'], 'RECOVERY')
        self.assertIn('changed', task['error'])

    def test_one_approval_sends_one_message_with_all_files_and_recipients(self):
        task, action = self.task(), self.action([self.file()])
        with patch.object(self.kernel.planner, 'decide', return_value=action), patch.object(self.kernel.google, 'call', return_value={'id': 'sent'}) as call:
            self.kernel.tick()
            call.assert_not_called()
            self.kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})
            self.kernel.tick()
            call.assert_called_once()
        self.assertEqual(task['state'], 'COMPLETED')
        self.assertFalse(self.kernel.tick())

    def test_denied_paths_missing_files_duplicates_and_limits_never_call_google(self):
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('not granted')
        path = self.file(data=b'123456')
        task = self.task()
        for paths in ([str(outside)], [str(self.config.workspace / 'missing.pdf')], [path, path], [path] * 13,
                      [str(self.config.workspace)], [str(self.config.workspace / 'credentials.json')]):
            with self.subTest(paths=paths), patch.object(self.kernel.google, 'call') as call:
                with self.assertRaises(ValueError):
                    self.kernel.registry.gmail_send(self.action(paths)['arguments'], task)
                call.assert_not_called()
        with patch('services.mail_message.MAX_ATTACHMENT_BYTES', 5), self.assertRaisesRegex(PlanCorrection, '18 MB'):
            self.kernel.registry.validate(self.action([path]), task)
        task['scopes'] = ['gmail']
        with self.assertRaisesRegex(PlanCorrection, 'Local files'):
            self.kernel.registry.validate(self.action([path]), task)

    def test_other_intents_uploads_are_not_available(self):
        upload = self.kernel.uploads.receive(io.BytesIO(b'content'), 'report.pdf', 7)
        with self.assertRaises(ValueError):
            self.kernel.registry.validate(self.action([upload['path']]), self.task())


if __name__ == '__main__':
    unittest.main()
