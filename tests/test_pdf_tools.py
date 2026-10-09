"""Real PDF transformations, source preservation, forms, and approval boundaries."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.capabilities import CapabilityRegistry
from tests.test_runtime import ScriptedPlanner, action, finish


def make_pdf(path, text='Status: Draft', pages=1, form=False):
    doc = canvas.Canvas(str(path), pagesize=(595, 842))
    for number in range(pages):
        doc.setFont('Helvetica', 12)
        doc.drawString(60, 740, text)
        doc.drawString(60, 700, f'Original page {number + 1}')
        if form:
            doc.acroForm.textfield(name='reviewer', value=text, x=60, y=620, width=200, height=25)
        doc.showPage()
    doc.save()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.root = self.config.workspace
        self.source = self.root / 'original.pdf'
        self.second = self.root / 'appendix.pdf'
        make_pdf(self.source, pages=2)
        make_pdf(self.second, text='Appendix content')
        self.registry = CapabilityRegistry(self.config, None)
        self.task = {'roots': [str(self.root)]}
        self.original_hashes = [sha(self.source), sha(self.second)]

    def tearDown(self):
        self.assertEqual([sha(self.source), sha(self.second)], self.original_hashes)
        self.temp.cleanup()

    def edit(self, **kw):
        params = dict(source=str(self.source), destination=str(self.root / 'results' / 'edited.pdf'),
                      find='Status: Draft', replace='Status: Final')
        params.update(kw)
        return self.registry.execute(action('pdf_replace_text', **params), self.task)

    def test_replace_is_real_text_edit_with_source_unchanged(self):
        result = self.edit()
        self.assertEqual(result['replacements'], 2)
        edited = PdfReader(result['artifact'])
        self.assertEqual(len(edited.pages), 2)
        for index, page in enumerate(edited.pages):
            self.assertIn('Status: Final', page.extract_text())
            self.assertNotIn('Status: Draft', page.extract_text())
            self.assertIn(f'Original page {index + 1}', page.extract_text())
        self.assertFalse(result['source_files_modified'])
        self.assertEqual(result['source_sha256'], self.original_hashes[0])

    def test_merge_preserves_order_and_originals(self):
        result = self.registry.execute(action('pdf_merge', sources=[str(self.source), str(self.second)],
            destination=str(self.root / 'results' / 'merged.pdf')), self.task)
        reader = PdfReader(result['artifact'])
        self.assertEqual(len(reader.pages), 3)
        self.assertIn('Original page 2', reader.pages[1].extract_text())
        self.assertIn('Appendix content', reader.pages[2].extract_text())
        self.assertEqual([i['sha256'] for i in result['inputs']], self.original_hashes)

    def test_merge_edited_copy_does_not_modify_it(self):
        edited = Path(self.edit()['artifact'])
        before = sha(edited)
        result = self.registry.execute(action('pdf_merge', sources=[str(edited), str(self.second)],
            destination=str(self.root / 'results' / 'combined.pdf')), self.task)
        self.assertEqual(sha(edited), before)
        self.assertIn('Status: Final', PdfReader(result['artifact']).pages[0].extract_text())

    def test_no_match_produces_no_output(self):
        with self.assertRaisesRegex(ValueError, 'No exact'):
            self.edit(find='Missing phrase')
        self.assertFalse((self.root / 'results').exists())

    def test_cannot_overwrite_input(self):
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.edit(destination=str(self.source))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.registry.execute(action('pdf_merge', sources=[str(self.source), str(self.second)],
                                  destination=str(self.second)), self.task)

    def test_existing_output_is_not_overwritten(self):
        target = self.root / 'already.pdf'
        target.write_bytes(b'preserve me')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.edit(destination=str(target))
        self.assertEqual(target.read_bytes(), b'preserve me')

    def test_source_and_output_paths_must_be_granted(self):
        for kw in [{'source': str(Path(self.temp.name) / 'outside.pdf')},
                   {'destination': str(Path(self.temp.name) / 'outside.pdf')}]:
            with self.assertRaisesRegex(ValueError, 'outside'):
                self.edit(**kw)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.registry.validate(action('pdf_merge', sources=[str(self.source), '../outside.pdf'],
                                         destination='results/a.pdf'), self.task)

    def test_merge_rejects_wrong_argument_types(self):
        for sources in ['original.pdf', [str(self.source)], [str(self.source), 42], [str(self.source)] * 21]:
            with self.assertRaises(ValueError):
                self.registry.validate(action('pdf_merge', sources=sources, destination='out.pdf'), self.task)

    def test_non_pdf_and_non_pdf_destination_rejected(self):
        false_pdf = self.root / 'fake.pdf'
        false_pdf.write_text('not a PDF')
        with self.assertRaisesRegex(ValueError, 'valid PDF'):
            self.edit(source=str(false_pdf))
        with self.assertRaisesRegex(ValueError, 'end in .pdf'):
            self.edit(destination=str(self.root / 'out.txt'))

    def test_oversized_replacement_fails_without_saving(self):
        with self.assertRaisesRegex(ValueError, 'fit legibly'):
            self.edit(replace='This is far too long to fit the original status label ' * 5)
        self.assertFalse((self.root / 'results').exists())

    def test_unsupported_text_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ASCII'):
            self.edit(replace='Status: Prêt')

    def test_pdf_read_uses_actual_page_text(self):
        result = self.registry.execute(action('files_read', path=str(self.source)), self.task)
        self.assertIn('Status: Draft', result['content'])
        self.assertIn('Original page 2', result['content'])

    def test_form_merge_keeps_separate_interactive_values(self):
        form_one, form_two = self.root / 'one.pdf', self.root / 'two.pdf'
        make_pdf(form_one, text='Alice', form=True)
        make_pdf(form_two, text='Bob', form=True)
        result = self.registry.execute(action('pdf_merge', sources=[str(form_one), str(form_two)],
            destination=str(self.root / 'forms.pdf')), self.task)
        reader = PdfReader(result['artifact'])
        fields = reader.get_fields()
        self.assertEqual(fields['input_1.reviewer']['/V'], 'Alice')
        self.assertEqual(fields['input_2.reviewer']['/V'], 'Bob')
        self.assertTrue(all(page.get('/Annots') for page in reader.pages))
        for page in reader.pages:
            widget = page['/Annots'][0].get_object()
            self.assertTrue(widget.get('/AP', {}).get('/N'))

    def test_text_edit_rejects_form_pdf(self):
        form = self.root / 'form.pdf'
        make_pdf(form, form=True)
        before = sha(form)
        with self.assertRaisesRegex(ValueError, 'Form PDFs'):
            self.edit(source=str(form))
        self.assertEqual(sha(form), before)

    def test_each_pdf_write_requires_approval_and_checkpoints(self):
        target, merged = self.root / 'results' / 'edited.pdf', self.root / 'results' / 'merged.pdf'
        kernel = Runtime(self.config, ScriptedPlanner(
            action('pdf_replace_text', source=str(self.source), destination=str(target), find='Status: Draft', replace='Status: Final'),
            action('pdf_merge', sources=[str(target), str(self.second)], destination=str(merged)), finish()))
        try:
            task = kernel.tasks[kernel.submit('Edit and merge copies')['id']]
            kernel.tick()
            self.assertEqual(task['state'], 'APPROVAL')
            self.assertFalse(target.exists())
            kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})
            kernel.tick()
            kernel.tick()
            self.assertEqual(task['state'], 'APPROVAL')
            self.assertEqual(len(task['steps']), 1)
            self.assertFalse(merged.exists())
            kernel.control(task['id'], 'approve', {'action_id': task['pending']['id']})
            kernel.tick()
            kernel.tick()
            self.assertEqual(task['state'], 'COMPLETED')
            self.assertEqual(len(task['steps']), 2)
        finally:
            kernel.close()
