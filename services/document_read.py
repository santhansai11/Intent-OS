"""Bounded DOCX text extraction without decompressing embedded media."""
import re
import zipfile
from xml.etree import ElementTree as ET

DOCX_BYTES = 100_000_000
XML_BYTES = 20_000_000
TEXT_CHARS = 2_000_000
PAGE_CHARS = 16000
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def read_docx(path, offset=0):
    if path.stat().st_size > DOCX_BYTES:
        raise ValueError('DOCX exceeds the 100 MB document limit')
    try:
        with zipfile.ZipFile(path) as archive:
            # Media files can be large; only relevant text XML is decompressed.
            names = ['word/document.xml'] + sorted(n for n in archive.namelist()
                if re.fullmatch(r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml', n))
            if sum(archive.getinfo(n).file_size for n in names) > XML_BYTES:
                raise ValueError('Document text XML exceeds the 20 MB decompression limit')
            parts, characters, consumed, headings = [], 0, 0, []
            for name in names:
                with archive.open(name) as source:
                    raw = source.read(XML_BYTES - consumed + 1)
                consumed += len(raw)
                if consumed > XML_BYTES:
                    raise ValueError('Document text XML exceeds the 20 MB decompression limit')
                declarations = raw.replace(b'\x00', b'').upper()
                if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
                    raise ValueError('Document XML declarations are unsupported')
                root = ET.fromstring(raw)
                for paragraph in root.iter(W + 'p'):
                    text = ''.join(node.text or '' if node.tag == W + 't' else
                                   '\t' if node.tag == W + 'tab' else '\n'
                                   for node in paragraph.iter()
                                   if node.tag in (W + 't', W + 'tab', W + 'br', W + 'cr'))
                    if text.strip():
                        style = paragraph.find(W + 'pPr/' + W + 'pStyle')
                        if style is not None and 'heading' in style.get(W + 'val', '').lower():
                            headings.append(text.strip())
                        characters += len(text) + 1
                        if characters > TEXT_CHARS:
                            raise ValueError('Document text exceeds the 2 million character extraction limit')
                        parts.append(text)
            content = '\n'.join(parts)
            media_count = sum(n.startswith('word/media/') for n in archive.namelist())
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
        raise ValueError('Cannot read DOCX text: document is malformed, encrypted, or missing its main text part') from exc
    if offset > len(content):
        raise ValueError('Text offset is beyond the end of this document')
    end = min(offset + PAGE_CHARS, len(content))
    return {'path': str(path), 'content': content[offset:end], 'offset': offset,
            'total_characters': len(content), 'truncated': end < len(content),
            'next_offset': str(end) if end < len(content) else None,
            'embedded_media': media_count,
            'headings': headings[:80],
            'coverage': 'Document paragraphs, tables, headers, footers and notes. Embedded images are not OCRed.'}
