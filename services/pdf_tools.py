"""Copy-on-write PDF transformations. Input files are never opened for writing."""
from __future__ import annotations

import hashlib
import io
import os
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PdfTools:
    def __init__(self, resolve_path):
        self.resolve = resolve_path

    def source(self, raw, task):
        from pypdf import PdfReader
        path = self.resolve(raw, task)
        if path.suffix.lower() != '.pdf' or not path.is_file():
            raise ValueError('Choose an existing PDF file')
        if path.stat().st_size > 20_000_000:
            raise ValueError('PDF inputs must be smaller than 20 MB each')
        data = path.read_bytes()
        if not data.startswith(b'%PDF-'):
            raise ValueError('The file is not a valid PDF')
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError('Encrypted PDFs are not supported; provide an unlocked copy')
        if not 1 <= len(reader.pages) <= 200:
            raise ValueError('PDF inputs must contain between 1 and 200 pages')
        if reader.trailer['/Root'].get('/Perms') or any(
                field.get('/FT') == '/Sig' for field in (reader.get_fields() or {}).values()):
            raise ValueError('Signed PDFs are not transformed; provide an unsigned copy')
        return path, data, reader

    def destination(self, raw, task, sources):
        path = self.resolve(raw, task)
        if path.suffix.lower() != '.pdf':
            raise ValueError('The destination must end in .pdf')
        if path in sources:
            raise ValueError('Source PDFs are immutable: choose a separate output path')
        if path.exists():
            raise ValueError('The destination already exists; choose a new filename')
        return path

    def save_new(self, target, data):
        """Publish a complete file exclusively; even a concurrent destination is not overwritten."""
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.intentos-pdf-', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'artifact': str(target), 'bytes': len(data), 'sha256': digest(data)}

    def merge(self, args, task):
        from pypdf import PdfReader, PdfWriter
        sources = [self.resolve(raw, task) for raw in args['sources']]
        target = self.destination(args['destination'], task, sources)
        writer = PdfWriter()
        inputs, total_pages, total_bytes = [], 0, 0
        try:
            for index, source in enumerate(sources):
                path, data, reader = self.source(str(source), task)
                total_pages += len(reader.pages)
                total_bytes += len(data)
                if total_pages > 500 or total_bytes > 100_000_000:
                    raise ValueError('Merge limit: 500 pages and 100 MB combined input')
                # Preserve interactive fields without duplicate names across documents.
                if reader.get_fields():
                    reader.add_form_topname(f'input_{index + 1}')
                writer.append(reader, outline_item=path.stem)
                inputs.append({'path': str(path), 'pages': len(reader.pages), 'sha256': digest(data)})
            output = io.BytesIO()
            writer.write(output)
            data = output.getvalue()
            if len(PdfReader(io.BytesIO(data)).pages) != total_pages:
                raise ValueError('Merged page-count verification failed')
            return {**self.save_new(target, data), 'status': 'merged', 'pages': total_pages,
                    'inputs': inputs, 'source_files_modified': False}
        finally:
            writer.close()

    def replace_text(self, args, task):
        import pymupdf
        path, original, reader = self.source(args['source'], task)
        target = self.destination(args['destination'], task, [path])
        find, replacement = args['find'], args['replace']
        if not find or not replacement or find == replacement or len(find) > 500 or len(replacement) > 500:
            raise ValueError('Provide different non-empty find/replace text, at most 500 characters each')
        if any(ord(c) < 32 or ord(c) > 126 for c in find + replacement):
            raise ValueError('This text-edit tool supports single-line ASCII text; use an editable source for other scripts')
        if reader.get_fields():
            raise ValueError('Form PDFs need a form-specific editor; this tool edits plain page text only')
        changes = []
        with pymupdf.open(stream=original, filetype='pdf') as document:
            for page in document:
                hits = page.search_for(find)
                if not hits:
                    continue
                if page.rotation:
                    raise ValueError('Rotated text/pages require an editable source; no output was saved')
                if any(annotation.type[0] == pymupdf.PDF_ANNOT_REDACT for annotation in (page.annots() or [])):
                    raise ValueError('Resolve existing redaction annotations before editing this PDF')
                lines = [line for block in page.get_text('dict', flags=pymupdf.TEXTFLAGS_TEXT)['blocks']
                         for line in block.get('lines', [])]
                edits = []
                for rect in hits:
                    # search_for can be case-insensitive or match across lines. Restrict to
                    # an exact, single-span horizontal match so unrelated text stays intact.
                    if page.get_textbox(rect).strip() != find:
                        continue
                    span = next((span for line in lines if tuple(line['dir']) == (1.0, 0.0)
                                 for span in line['spans'] if pymupdf.Rect(span['bbox']).contains(rect)
                                 and find in span['text']), None)
                    if span is None:
                        raise ValueError('Match spans multiple styles/lines; use an editable source instead')
                    flags = span['flags']
                    bold, italic = bool(flags & 16), bool(flags & 2)
                    family = 'courier' if flags & 8 else ('times' if flags & 4 else 'helvetica')
                    fonts = {'courier': ('cour', 'cobo', 'coit', 'cobi'),
                             'times': ('tiro', 'tibo', 'tiit', 'tibi'),
                             'helvetica': ('helv', 'hebo', 'heit', 'hebi')}
                    fontname = fonts[family][int(bold) + 2 * int(italic)]
                    font = pymupdf.Font(fontname)
                    size = min(span['size'], rect.width / font.text_length(replacement, fontsize=1),
                               rect.height / (font.ascender - font.descender))
                    if size < 7:
                        raise ValueError('Replacement does not fit legibly in the existing space; use shorter text')
                    color = tuple(((span['color'] >> shift) & 255) / 255 for shift in (16, 8, 0))
                    edits.append((rect, fontname, size, color, rect.y0 + font.ascender * size))
                if len(changes) + len(edits) > 200:
                    raise ValueError('At most 200 text replacements are allowed per call')
                for rect, *_ in edits:
                    page.add_redact_annot(rect, fill=False, cross_out=False)
                if edits:
                    # Remove the old glyphs, preserving images and vector graphics.
                    page.apply_redactions(images=0, graphics=0, text=0)
                    for rect, fontname, size, color, baseline in edits:
                        page.insert_text((rect.x0, baseline), replacement, fontname=fontname, fontsize=size, color=color)
                        changes.append({'page': page.number + 1, 'rect': list(rect), 'font': fontname,
                                        'font_size': round(size, 2)})
            if not changes:
                raise ValueError('No exact editable text match found. Scanned PDFs require OCR; no output was saved.')
            data = document.tobytes(garbage=4, deflate=True)
        # Inspect the saved representation, not merely the in-memory operation result.
        with pymupdf.open(stream=data, filetype='pdf') as check:
            for change in changes:
                rect = pymupdf.Rect(change['rect']) + (-1, -1, 1, 1)
                if replacement not in check[change['page'] - 1].get_textbox(rect):
                    raise ValueError('Replacement verification failed; no output was saved')
        return {**self.save_new(target, data), 'status': 'edited', 'pages': len(reader.pages),
                'replacements': len(changes), 'changes': changes,
                'source': str(path), 'source_sha256': digest(original), 'source_files_modified': False,
                'note': 'Replacements use a matching standard font family and may shrink to fit. Review complex layouts.'}
