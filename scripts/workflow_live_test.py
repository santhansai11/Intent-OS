"""Opt-in live Gemini + HTTP tests. Uses only newly created synthetic files.

Run with the app listening on port 8765 and a stored Gemini key. Existing
configured folders are restored; Gemini remains the selected provider.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
from datetime import datetime

BASE = 'http://127.0.0.1:8765/api'


def request(path, data=None):
    headers = {'Content-Type': 'application/json'}
    if data is not None:
        headers['X-IntentOS-Token'] = request.token
    req = urllib.request.Request(BASE + path, json.dumps(data).encode() if data is not None else None, headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def main():
    request.token = request('/session')['token']
    original = request('/status')['config']
    root = Path(__file__).resolve().parents[1] / 'storage_test' / ('live-workflows-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'originals'
    source.mkdir()
    (source / 'team-a').mkdir()
    (source / 'team-b').mkdir()
    (source / 'team-a' / 'notes.txt').write_text('Cloud computing meeting: elastic capacity, virtual machines and shared responsibility. Budget: 200 units.', encoding='utf-8')
    (source / 'team-b' / 'notes.txt').write_text('Cloud computing: compare compute costs, storage costs and disaster recovery. Review date: Friday.', encoding='utf-8')
    (source / 'architecture.md').write_text('# Cloud computing\nUse load balancing and backups. Encrypt stored data and review access grants.', encoding='utf-8')
    (source / 'holiday.txt').write_text('Holiday: visit the beach and take photos.', encoding='utf-8')
    def hashes():
        return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    before, reports = hashes(), []
    request('/settings', {'provider': 'gemini', 'roots': [*original['roots'], str(root), str(source)]})

    def run(label, text, **extra):
        start = time.monotonic()
        task = request('/intents', {'text': text, 'roots': [str(source), str(root)], 'search_roots': [str(source)], 'scopes': ['files', 'web'], 'auto_outputs': True, **extra})
        ident, last = task['id'], None
        while time.monotonic() - start < 180:
            task = next(t for t in request('/status')['intents'] if t['id'] == ident)
            if task['state'] != last:
                print(label, task['state'], flush=True)
                last = task['state']
            if task['state'] in ('COMPLETED', 'BLOCKED', 'REVIEW', 'WAITING_INPUT', 'APPROVAL', 'CANCELLED'):
                break
            time.sleep(.3)
        report = {'label': label, 'id': ident, 'seconds': round(time.monotonic()-start, 3),
                  'state': task['state'], 'model_calls': task['turns'], 'steps': task['steps'], 'answer': task['answer'], 'error': task['error']}
        reports.append(report)
        (root / 'verification.json').write_text(json.dumps({'tests': reports, 'originals_unchanged': before == hashes()}, indent=2), encoding='utf-8')
        print(json.dumps({k: report[k] for k in ('label', 'state', 'seconds', 'model_calls', 'error')}), flush=True)
        assert task['state'] == 'COMPLETED', task['error'] or task.get('question') or task['state']
        for step in task['steps']:
            if step['result'].get('artifact'):
                with urllib.request.urlopen(BASE + '/artifact?intent=' + ident + '&step=' + step['id']) as response:
                    assert response.read() == Path(step['result']['artifact']).read_bytes()
        assert before == hashes(), 'Source files changed'
        return task

    try:
        if '--combined-only' in sys.argv:
            task = run('gemini-meeting-pack', f'Prepare a cloud computing meeting pack: first gather related existing files from {source} into {root / "meeting-pack"}, preserving originals. Then summarize what those gathered files actually say in about 150 words, including the budget and review date if present. Save the brief as Markdown at {root / "meeting-brief.md"}.')
            assert any(s['tool'] == 'files_collect' for s in task['steps'])
            brief = (root / 'meeting-brief.md').read_text(encoding='utf-8')
            assert '200' in brief and 'Friday' in brief
            print('REPORT ' + str(root / 'verification.json'), flush=True)
            return
        direct = run('direct-collection', 'Gather cloud computing files', workflow={'type': 'collect', 'query': 'cloud computing', 'destination': str(root / 'direct-pack')})
        assert direct['turns'] == 0 and direct['steps'][0]['result']['copied'] == 3
        collected = run('gemini-collection', f'Collect existing files related to cloud computing from {source} into {root / "ai-pack"}. Copy them; preserve originals. Only gather the files; no summary needed.')
        assert any(s['tool'] == 'files_collect' for s in collected['steps'])
        assert next(s['result']['copied'] for s in collected['steps'] if s['tool'] == 'files_collect') == 3
        summary = run('gemini-pdf-summary', f'Write a concise 250-word introductory summary of cloud computing, including service models, benefits, costs and security responsibilities. Use general knowledge; no web research or local file reads needed. Save a PDF at {root / "reports" / "cloud-computing.pdf"}.')
        from pypdf import PdfReader
        pdf = root / 'reports' / 'cloud-computing.pdf'
        content = '\n'.join(p.extract_text() for p in PdfReader(pdf).pages)
        assert len(content) > 500 and 'cloud' in content.casefold()
        print('REPORT ' + str(root / 'verification.json'), flush=True)
    finally:
        request('/settings', {'roots': original['roots'], 'provider': 'gemini'})


if __name__ == '__main__':
    main()
