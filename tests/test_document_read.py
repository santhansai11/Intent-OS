"""Large document, source coverage and resumed summary regressions; no live APIs."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from planner.document_context import document_context
from services.capabilities import CapabilityRegistry
from services.document_read import read_docx
from services.mail_policy import authorize_send
from services.summary_policy import summary_requirements, validate_summary_send, PlanCorrection


def docx(path, text='A paragraph with evidence.', media_bytes=0):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table evidence</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        if media_bytes:
            archive.writestr('word/media/image.png', b'x' * media_bytes)


class DocumentRead(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root / 'runtime')
        self.registry = CapabilityRegistry(self.config, None)
        self.path = self.root / 'assessment.docx'
        self.task = {'roots': [str(self.root)], 'scopes': ['files']}

    def tearDown(self):
        self.temp.cleanup()

    def test_large_media_is_never_decompressed(self):
        docx(self.path, media_bytes=21_000_000)
        original = zipfile.ZipFile.open
        opened = []
        def tracked(archive, name, *args, **kwargs):
            opened.append(name)
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'open', tracked):
            result = self.registry.read({'path': str(self.path)}, self.task)
        self.assertEqual(opened, ['word/document.xml'])
        self.assertIn('Table evidence', result['content'])
        self.assertEqual(result['embedded_media'], 1)
        self.assertFalse(result['truncated'])

    def test_pages_reassemble_without_omitting_text(self):
        text = 'start ' + 'evidence ' * 4000 + 'end'
        docx(self.path, text)
        parts, offset = [], '0'
        while offset is not None:
            result = self.registry.read({'path': str(self.path), 'offset': offset}, self.task)
            parts.append(result['content'])
            offset = result['next_offset']
        self.assertEqual(''.join(parts), text + '\nTable evidence')
        self.assertGreater(len(parts), 2)

    def test_large_xml_and_entities_are_rejected(self):
        docx(self.path, 'x' * 20_000_001)
        with self.assertRaisesRegex(ValueError, 'decompression limit'):
            read_docx(self.path)
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('word/document.xml', '<!DOCTYPE x [<!ENTITY x "expanded">]><x>&x;</x>')
        with self.assertRaisesRegex(ValueError, 'declarations'):
            read_docx(self.path)

    def test_malformed_and_missing_files_have_clear_errors(self):
        with self.assertRaisesRegex(ValueError, 'existing file'):
            self.registry.read({'path': str(self.path)}, self.task)
        self.path.write_bytes(b'not a docx')
        with self.assertRaisesRegex(ValueError, 'malformed'):
            self.registry.read({'path': str(self.path)}, self.task)

    def test_path_grants_and_offsets_remain_enforced(self):
        docx(self.path)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.registry.read({'path': str(self.path)}, {'roots': [str(self.config.workspace)]})
        for offset in ('-1', 'foo', '10000000'):
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'numeric'):
                self.registry.read({'path': str(self.path), 'offset': offset}, self.task)
        with self.assertRaisesRegex(ValueError, 'beyond'):
            self.registry.read({'path': str(self.path), 'offset': '999999'}, self.task)

    def test_all_completed_read_evidence_survives_recent_history_window(self):
        steps = [{'tool': 'files_read', 'result': {'path': str(i), 'content': 'x' * 6000 + 'tail', 'truncated': False}} for i in range(8)]
        context = document_context({'steps': steps})
        self.assertEqual(len(context['document_sources']), 8)
        self.assertTrue(all(s['content'].endswith('tail') for s in context['document_sources']))
        limited = document_context({'steps': steps}, budget=10)
        self.assertEqual(limited['document_context_limits']['omitted_characters'], 8 * 6004 - 10)
        self.assertEqual(limited['document_context_limits']['character_budget'], 10)

    def test_resume_large_assessment_preserves_checkpoints(self):
        docx(self.path, media_bytes=10_100_000)
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        try:
            task = kernel.tasks[kernel.submit('Summarize all assessments')['id']]
            task['roots'] = [str(self.root)]
            task['steps'] = [{'id': 'earlier-read', 'tool': 'files_read', 'result': {'path': 'first', 'content': 'Earlier evidence'}}]
            task.update(state='BLOCKED', pending={'id': 'large-read', 'tool': 'files_read', 'summary': 'Read next assessment', 'arguments': {'path': str(self.path)}, 'complete_after': False}, error='Choose a file smaller than 10 MB')
            kernel._save(task, 'test', 'Blocked read')
            kernel.control(task['id'], 'resume')
            kernel.tick()
            self.assertEqual(task['state'], 'READY')
            self.assertEqual([s['id'] for s in task['steps']], ['earlier-read', 'large-read'])
            self.assertIn('Table evidence', task['steps'][-1]['result']['content'])
        finally:
            kernel.close()

    def test_compound_summary_send_authorizes_only_requested_recipient(self):
        task = {'goal': 'go to computer networks lab folder and send the detailed summary(more that 50 lines) of that to person@example.com i need summary of all assessments'}
        action = {'tool': 'gmail_send', 'arguments': {'to': 'person@example.com', 'subject': 'Assessments', 'body': 'Summary'}}
        self.assertTrue(authorize_send(task, action))
        action['arguments']['to'] = 'someoneelse@example.com'
        self.assertFalse(authorize_send(task, action))

    def test_coverage_requires_all_reads_and_deduplicates_pdf_copies(self):
        a, b = str(self.root / 'ASS1.docx'), str(self.root / 'ASS 2.docx')
        task = {'goal': 'Summarize all assessments in more that 50 lines', 'steps': [
            {'tool': 'files_list', 'result': {'entries': [{'name': Path(p).name, 'path': p} for p in (a, a.replace('.docx', '.pdf'), b)]}},
            {'tool': 'files_read', 'result': {'path': a, 'content': 'Read assessment one', 'truncated': False}}]}
        requirements = summary_requirements(task)
        self.assertEqual(requirements['remaining_assessment_documents'], [b])
        self.assertEqual(requirements['minimum_nonempty_lines'], 51)
        mail = {'tool': 'gmail_send', 'arguments': {'body': '\n'.join(['Evidence'] * 51)}}
        with self.assertRaisesRegex(PlanCorrection, 'Read these assessments'):
            validate_summary_send(task, mail)
        task['steps'].append({'tool': 'files_read', 'result': {'path': b, 'content': 'First chunk', 'truncated': True, 'next_offset': '16000'}})
        self.assertEqual(summary_requirements(task)['remaining_assessment_documents'], [b])
        task['steps'].append({'tool': 'files_read', 'result': {'path': b, 'content': 'Last chunk', 'offset': 16000, 'truncated': False}})
        validate_summary_send(task, mail)
        mail['arguments']['body'] = '\n'.join(['Evidence'] * 50) + '\n\n\n'
        with self.assertRaisesRegex(PlanCorrection, 'at least 51'):
            validate_summary_send(task, mail)

    def test_pending_short_email_replans_without_calling_gmail(self):
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(self.config)
        try:
            task = kernel.tasks[kernel.submit('Send an email to person@example.com summarizing notes in more than 50 lines')['id']]
            task['pending'] = {'id': 'send', 'tool': 'gmail_send', 'summary': 'Send summary', 'approved': True, 'arguments': {'to': 'person@example.com', 'subject': 'Notes', 'body': 'Too short'}}
            with patch.object(kernel.google, 'call') as send:
                kernel.tick()
            send.assert_not_called()
            self.assertEqual(task['state'], 'RECOVERY')
            self.assertIsNone(task['pending'])
            self.assertIn('at least 51', task['history'][-1]['planner_error'])
        finally:
            kernel.close()
