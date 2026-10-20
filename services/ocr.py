"""Local OCR via MuPDF/Tesseract, with page limits and explicit provenance."""
from pathlib import Path


def read_ocr(path, config, page=0):
    import fitz
    tessdata = config.root / 'ocr'
    if not (tessdata / 'eng.traineddata').is_file():
        raise ValueError('Local OCR language data is missing. Install eng.traineddata in the runtime ocr folder.')
    if path.stat().st_size > 100_000_000:
        raise ValueError('OCR accepts files up to 100 MB')
    source = fitz.open(path)
    try:
        if source.needs_pass:
            raise ValueError('Unlock the document before OCR')
        if not source.is_pdf:
            pdf = source.convert_to_pdf()
            source.close()
            source = fitz.open('pdf', pdf)
        if not 0 <= page < len(source):
            raise ValueError('Choose a valid zero-based page number')
        p = source[page]
        if p.rect.width * p.rect.height > 30_000_000:
            raise ValueError('Image is too large for local OCR; resize it first')
        textpage = p.get_textpage_ocr(language='eng', dpi=150, full=True, tessdata=str(tessdata))
        content = p.get_text(textpage=textpage)
        return {'path': str(path), 'page': page + 1, 'pages': len(source), 'content': content[:16000],
                'truncated': len(content) > 16000, 'next_page': str(page + 1) if page + 1 < len(source) else None,
                'coverage': 'Local OCR of this page. Recognition can be inaccurate; verify names, numbers and equations.', 'ocr': True}
    finally:
        source.close()
