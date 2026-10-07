"""Document generation: convert generated Markdown into real file formats.

Pure standard library -- no reportlab/python-docx dependencies.

    * PDF  -- minimal but valid PDF 1.4 (Helvetica, letter pages, wrapped)
    * DOCX -- minimal Office Open XML package (opens in Word / Google Docs)
    * HTML -- styled standalone page
    * TXT  -- plain text with the markup stripped
"""
from __future__ import annotations

import html as _html
import re
import zipfile
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Markdown -> plain text
# ---------------------------------------------------------------------------
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITAL = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LIST = re.compile(r"^\s*[-*+]\s+")
_FENCE = re.compile(r"^\s*```.*$")


def _strip_inline(text: str) -> str:
    text = _IMG.sub(r"\1", text)
    text = _LINK.sub(r"\1 (\2)", text)
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _ITAL.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _CODE.sub(r"\1", text)
    return text


def markdown_to_text(md: str) -> str:
    """Markdown -> readable plain text (headings underlined, bullets kept)."""
    out: List[str] = []
    in_fence = False
    for line in (md or "").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(line)
            continue
        m = _HEADING.match(line)
        if m:
            title = _strip_inline(m.group(2)).strip()
            out.append(title)
            out.append("=" * min(len(title), 60) if m.group(1) == "#" else "-" * min(len(title), 60))
            continue
        bullet = _LIST.match(line)
        if bullet:
            out.append("  - " + _strip_inline(line[bullet.end():]).strip())
            continue
        out.append(_strip_inline(line))
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# ---------------------------------------------------------------------------
# Markdown -> HTML
# ---------------------------------------------------------------------------
def _inline_html(text: str) -> str:
    text = _IMG.sub(r'<img alt="\1" src="\2">', text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITAL.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    text = _CODE.sub(r"<code>\1</code>", text)
    return text


def markdown_to_html(md: str, title: str = "Document") -> str:
    body: List[str] = []
    in_list = False
    in_fence = False
    para: List[str] = []
    for raw in (md or "").splitlines():
        if _FENCE.match(raw):
            if in_fence:
                body.append("</code></pre>")
                in_fence = False
            else:
                if para:
                    body.append("<p>" + _inline_html(" ".join(para)) + "</p>")
                    para = []
                body.append("<pre><code>")
                in_fence = True
            continue
        if in_fence:
            body.append(_html.escape(raw))
            continue
        m = _HEADING.match(raw)
        if m:
            if para:
                body.append("<p>" + _inline_html(" ".join(para)) + "</p>")
                para = []
            if in_list:
                body.append("</ul>")
                in_list = False
            level = len(m.group(1))
            body.append(f"<h{level}>{_inline_html(m.group(2).strip())}</h{level}>")
            continue
        if _LIST.match(raw):
            if para:
                body.append("<p>" + _inline_html(" ".join(para)) + "</p>")
                para = []
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline_html(_LIST.sub('', raw).strip())}</li>")
            continue
        if raw.strip():
            para.append(raw.strip())
        elif para:
            body.append("<p>" + _inline_html(" ".join(para)) + "</p>")
            para = []
    if para:
        body.append("<p>" + _inline_html(" ".join(para)) + "</p>")
    if in_list:
        body.append("</ul>")
    if in_fence:
        body.append("</code></pre>")
    style = ("body{font:15px/1.65 Georgia,serif;max-width:760px;margin:40px auto;"
             "padding:0 20px;color:#222}h1,h2,h3{font-family:'Segoe UI',sans-serif}"
             "code{background:#f4f4f4;padding:1px 5px;border-radius:4px}"
             "pre{background:#f4f4f4;padding:12px;border-radius:8px;overflow:auto}"
             "a{color:#0b5394}")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title><style>{style}</style></head>"
            f"<body>{''.join(body)}</body></html>")


# ---------------------------------------------------------------------------
# Text -> PDF (minimal, valid PDF 1.4)
# ---------------------------------------------------------------------------
_PAGE_W, _PAGE_H = 612, 792          # US Letter, points
_MARGIN, _LINE_H = 72, 14
_FONT_SIZE = 11
_CHARS = 85                          # ~468pt text width at 11pt Helvetica
_LINES_PER_PAGE = (_PAGE_H - 2 * _MARGIN) // _LINE_H


def _pdf_escape(text: str) -> str:
    text = (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))
    return text.encode("latin-1", "replace").decode("latin-1")


def _wrap(text: str, width: int = _CHARS) -> List[str]:
    lines: List[str] = []
    for para in text.splitlines():
        para = para.rstrip()
        if not para:
            lines.append("")
            continue
        while len(para) > width:
            cut = para.rfind(" ", 0, width)
            cut = cut if cut > width * 0.6 else width
            lines.append(para[:cut])
            para = para[cut:].lstrip()
        lines.append(para)
    return lines


def text_to_pdf(title: str, body: str) -> bytes:
    """Render a title + plain-text body as a valid multi-page PDF."""
    pages: List[List[str]] = []
    current: List[str] = []
    for line in _wrap(body):
        if len(current) >= _LINES_PER_PAGE:
            pages.append(current)
            current = []
        current.append(line)
    if current or not pages:
        pages.append(current)

    streams: List[bytes] = []
    for idx, page_lines in enumerate(pages):
        parts: List[str] = []
        if idx == 0 and title:
            parts.append(f"1 0 0 1 {_MARGIN} {_PAGE_H - _MARGIN - 6} Tm")
            parts.append(f"/F2 16 Tf ({_pdf_escape(title)}) Tj")
        y0 = _PAGE_H - _MARGIN - (30 if idx == 0 and title else 6)
        parts.append(f"/F1 {_FONT_SIZE} Tf {_LINE_H} TL 1 0 0 1 {_MARGIN} {y0} Tm")
        for line in page_lines:
            parts.append(f"({_pdf_escape(line)}) Tj T*")
        streams.append(("BT " + " ".join(parts) + " ET")
                       .encode("latin-1", "replace"))

    n_pages = len(streams)
    objects: List[bytes] = []

    def _obj(num: int, body_text) -> None:
        while len(objects) < num:
            objects.append(b"")
        if isinstance(body_text, bytes):
            objects[num - 1] = body_text
        else:
            objects[num - 1] = body_text.encode("latin-1", "replace")

    _obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n_pages))
    _obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>")
    _obj(3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    _obj(4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    for i, stream in enumerate(streams):
        page_num, stream_num = 5 + 2 * i, 6 + 2 * i
        _obj(page_num,
             f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
             f"/Contents {stream_num} 0 R >>")
        _obj(stream_num,
             f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1", "replace")
             + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * len(objects)
    for i, obj in enumerate(objects, start=1):
        offsets[i - 1] = len(out)
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


# ---------------------------------------------------------------------------
# Markdown -> DOCX (minimal Office Open XML package)
# ---------------------------------------------------------------------------
def _docx_para(text: str, bold: bool = False, size: int = 22) -> str:
    rpr = (f'<w:rPr>{"<w:b/>" if bold else ""}'
           f'<w:sz w:val="{size}"/></w:rPr>')
    esc = _html.escape(text)
    return f"<w:p><w:r>{rpr}<w:t xml:space=\"preserve\">{esc}</w:t></w:r></w:p>"


def markdown_to_docx(md: str, title: str = "Document") -> bytes:
    """Markdown -> .docx (Word / Google Docs compatible minimal package)."""
    paragraphs: List[str] = []
    in_fence = False
    for raw in (md or "").splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            paragraphs.append(_docx_para(raw, size=20))
            continue
        m = _HEADING.match(raw)
        if m:
            size = {1: 36, 2: 30, 3: 26}.get(len(m.group(1)), 24)
            paragraphs.append(_docx_para(_strip_inline(m.group(2)).strip(),
                                         bold=True, size=size))
            continue
        if _LIST.match(raw):
            paragraphs.append(
                _docx_para("\u2022 " + _strip_inline(_LIST.sub("", raw)).strip()))
            continue
        if raw.strip():
            paragraphs.append(_docx_para(_strip_inline(raw.strip())))

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(paragraphs)}</w:body></w:document>')

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Entry point used by the filesystem service
# ---------------------------------------------------------------------------
def render(content: str, suffix: str, title: str = "Document"):
    """Convert markdown `content` into the payload for `suffix`.

    Returns (payload, is_binary). Markdown and unknown suffixes pass through.
    """
    suffix = (suffix or "").lower()
    if suffix == ".pdf":
        return text_to_pdf(title, markdown_to_text(content)), True
    if suffix == ".docx":
        return markdown_to_docx(content, title), True
    if suffix == ".html":
        return markdown_to_html(content, title), False
    if suffix in (".txt", ".text"):
        return markdown_to_text(content), False
    return content, False   # .md and everything else: write as-is
