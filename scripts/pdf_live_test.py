"""Explicit opt-in live-model smoke test. All writes are confined to a new fixture run.

Creates two synthetic source PDFs, submits a real natural-language intent through
the running HTTP API, approves only the two expected PDF transformations, and
verifies outputs plus a byte-for-byte manifest of the original folder.
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def manifest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def fixtures(originals):
    originals.mkdir(parents=True)
    def page(doc, title, page_number, lines):
        width, height = A4
        doc.setFillColor(colors.HexColor('#183d35'))
        doc.rect(0, height - 122, width, 122, fill=1, stroke=0)
        doc.setFillColor(colors.HexColor('#cce3bc'))
        doc.setFont('Helvetica-Bold', 9)
        doc.drawString(48, height - 37, 'INTENTOS / CONTROLLED PDF TEST')
        doc.setFillColor(colors.white)
        doc.setFont('Helvetica-Bold', 24)
        doc.drawString(48, height - 78, title)
        doc.setFillColor(colors.HexColor('#25352f'))
        doc.setFont('Helvetica', 12)
        y = height - 168
        for line in lines:
            doc.drawString(48, y, line)
            y -= 31
        doc.setStrokeColor(colors.HexColor('#d7e1d5'))
        doc.line(48, 70, width - 48, 70)
        doc.setFillColor(colors.HexColor('#677565'))
        doc.setFont('Helvetica', 9)
        doc.drawString(48, 48, 'Synthetic test document. No personal files used.')
        doc.drawRightString(width - 48, 48, f'Page {page_number}')
        doc.showPage()
    doc = canvas.Canvas(str(originals / 'project-brief.pdf'), pagesize=A4)
    page(doc, 'Project brief', 1, ['Status: Draft', 'Project: IntentOS PDF workflow',
        'Objective: edit a copy, merge documents, and preserve all originals.',
        'Owner: Test team', 'Source folder policy: read only during this test.'])
    page(doc, 'Acceptance checklist', 2, ['1. Change the status label in the copied brief.',
        '2. Preserve this page and its position in the document.',
        '3. Append the appendix after both brief pages.',
        '4. Save every output in the separate results folder.',
        '5. Compare source SHA-256 hashes before and after execution.'])
    doc.save()
    doc = canvas.Canvas(str(originals / 'appendix.pdf'), pagesize=A4)
    page(doc, 'Reference appendix', 1, ['Appendix identifier: PDF-TEST-APPENDIX',
        'This document must become the third page of the merged output.',
        'The original appendix must remain byte-for-byte unchanged.'])
    doc.save()
    (originals / 'keep.txt').write_text('This file is not part of the merge. Leave it unchanged.\n', encoding='utf-8')


def run(base, run_dir, timeout, resume=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {'Content-Type': 'application/json'}
        if data:
            headers['X-IntentOS-Token'] = token
        request = urllib.request.Request(base + '/api' + path, data, headers)
        with opener.open(request, timeout=15) as response:
            return json.load(response)
    token = api('/session')['token']
    snapshot = api('/status')
    installed = api('/models')
    if 'qwen3:4b' not in installed['models']:
        raise RuntimeError('qwen3:4b must be installed and Ollama must be reachable')
    originals, results = run_dir / 'originals', run_dir / 'results'
    if resume:
        saved = json.loads((run_dir / 'request.json').read_text())
        before = saved['before']
        if manifest(originals) != before:
            raise RuntimeError('Original fixtures changed; refusing to resume this test')
    else:
        fixtures(originals)
        before = manifest(originals)
    config = snapshot['config']
    api('/settings', {'model': 'qwen3:4b', 'roots': list(dict.fromkeys(config['roots'] + [str(run_dir)]))})
    edited, merged = results / 'edited-brief.pdf', results / 'merged-packet.pdf'
    source, appendix = originals / 'project-brief.pdf', originals / 'appendix.pdf'
    goal = (f'PDF validation test: In the PDF "{source}", replace the exact text "Status: Draft" '
            f'with "Status: Final" and save an edited PDF copy at "{edited}". Then merge that edited '
            f'copy followed by "{appendix}" into "{merged}". Keep both originals and every other '
            'file in the originals folder unchanged. Do not move or delete anything. The destination '
            'folder may be created. Finish by reporting both output paths.')
    if resume:
        created = next(t for t in api('/status')['intents'] if t['id'] == saved['id'])
        if created['state'] in ('PAUSED', 'BLOCKED'):
            created = api(f'/intents/{created["id"]}/resume', {})
    else:
        created = api('/intents', {'text': goal, 'roots': [str(run_dir)], 'scopes': ['files', 'system']})
    ident, started, observed, approvals = created['id'], time.monotonic(), None, []
    if not resume:
        (run_dir / 'request.json').write_text(json.dumps({'id': ident, 'goal': goal, 'before': before}, indent=2))
    print(f'Intent {ident}: real qwen3:4b test started', flush=True)
    expected = {
        'pdf_replace_text': {'source': str(source), 'destination': str(edited), 'find': 'Status: Draft', 'replace': 'Status: Final'},
        'pdf_merge': {'sources': [str(edited), str(appendix)], 'destination': str(merged)},
    }
    task = created
    while time.monotonic() - started < timeout:
        task = next(t for t in api('/status')['intents'] if t['id'] == ident)
        signature = (task['state'], task['active'], len(task['steps']), task['error'])
        if signature != observed:
            print(json.dumps({'state': task['state'], 'active': task['active'], 'checkpoints': len(task['steps']),
                              'error': task['error'], 'question': task['question']}, ensure_ascii=False), flush=True)
            observed = signature
        if task['state'] == 'APPROVAL':
            pending = task['pending']
            if pending['tool'] not in expected or pending['arguments'] != expected[pending['tool']]:
                api(f'/intents/{ident}/deny', {'action_id': pending['id']})
                raise RuntimeError('Unexpected action denied: ' + json.dumps(pending))
            api(f'/intents/{ident}/approve', {'action_id': pending['id']})
            approvals.append({'id': pending['id'], 'tool': pending['tool'], 'arguments': pending['arguments']})
            print('Approved bounded test operation: ' + pending['tool'], flush=True)
        if task['state'] in ('COMPLETED', 'FAILED', 'CANCELLED', 'BLOCKED', 'REVIEW', 'WAITING_INPUT'):
            break
        time.sleep(2)
    if task['state'] not in ('COMPLETED', 'FAILED', 'CANCELLED', 'BLOCKED', 'REVIEW', 'WAITING_INPUT'):
        api(f'/intents/{ident}/cancel', {})
    after = manifest(originals)
    checks = {'originals_unchanged': before == after, 'intent_completed': task['state'] == 'COMPLETED',
              'edited_exists': edited.is_file(), 'merged_exists': merged.is_file()}
    if edited.is_file() and merged.is_file():
        e, m = PdfReader(edited), PdfReader(merged)
        checks.update({'edited_has_two_pages': len(e.pages) == 2, 'merged_has_three_pages': len(m.pages) == 3,
                       'replacement_visible': 'Status: Final' in e.pages[0].extract_text(),
                       'old_text_removed': 'Status: Draft' not in e.pages[0].extract_text(),
                       'page_order_correct': 'Acceptance checklist' in m.pages[1].extract_text()
                                             and 'PDF-TEST-APPENDIX' in m.pages[2].extract_text(),
                       'merged_uses_edited_copy': 'Status: Final' in m.pages[0].extract_text()})
    report = {'model': 'qwen3:4b', 'intent_id': ident, 'resumed': resume, 'seconds': round(time.monotonic() - started, 2),
              'checks': checks, 'before': before, 'after': after, 'approvals': approvals, 'task': task}
    (run_dir / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks, 'report': str(run_dir / 'verification.json')}, indent=2), flush=True)
    return all(checks.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--run-dir', type=Path, default=Path('output/pdf') / ('validation-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--timeout', type=int, default=2400)
    parser.add_argument('--resume', action='store_true', help='Continue the saved intent in --run-dir without recreating originals')
    args = parser.parse_args()
    sys.exit(0 if run(args.base_url, args.run_dir.resolve(), args.timeout, args.resume) else 1)
