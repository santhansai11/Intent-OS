"""Live smoke test: synthetic uploads -> reference-guided Gemini report.

Creates one labeled audit intent and local report; never sends mail or changes
Google data. Existing settings and user files are untouched.
"""
import json
import time
import urllib.request
import uuid
from pathlib import Path


def main():
    base = 'http://127.0.0.1:8765/api'
    with urllib.request.urlopen(base + '/session', timeout=10) as response:
        token = json.load(response)['token']

    def request(path, data=None, filename=None):
        headers = {'X-IntentOS-Token': token}
        if filename:
            headers.update({'Content-Type': 'application/octet-stream', 'X-Filename': filename})
            body = data.encode()
        else:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data).encode() if data is not None else None
        with urllib.request.urlopen(urllib.request.Request(base + path, body, headers), timeout=30) as response:
            return json.load(response)

    run = uuid.uuid4().hex[:8]
    output = Path(__file__).resolve().parents[1] / 'output' / 'feature-audit' / ('attachments-' + run)
    output.mkdir(parents=True)
    reference = request('/uploads', '# Overview\nBriefly describe the project.\n# Evidence\nUse only the provided source facts.\n# Next steps\nList the requested action.\n', 'audit-reference.txt')
    source = request('/uploads', 'Synthetic project: Juniper. Owner: Mira. Budget: 420 units. Assessment count: 3. Next action: review routing results. This is fictional test data.', 'audit-source.txt')
    task = request('/intents', {
        'text': 'Feature audit: use the reference attachment structure (Overview, Evidence, Next steps) and the source attachment facts to write a short report about Juniper. Read both attachments. Preserve owner Mira, budget 420 units and assessment count 3 accurately. Save as audit-report.md in the output folder. Do not contact anyone.',
        'scopes': ['system', 'files'], 'roots': [], 'search_roots': [],
        'output_folder': str(output), 'auto_outputs': True,
        'attachments': [{'id': reference['id'], 'role': 'reference'}, {'id': source['id'], 'role': 'source'}],
    })
    ident, last = task['id'], None
    for _ in range(150):
        task = next(t for t in request('/status')['intents'] if t['id'] == ident)
        if task['state'] != last:
            print(task['state'], flush=True)
            last = task['state']
        if task['state'] not in ('READY', 'RUNNING', 'RECOVERY'):
            break
        time.sleep(1)
    report = {'intent_id': ident, 'state': task['state'], 'error': task.get('error'),
              'question': task.get('question'), 'tools': [s['tool'] for s in task['steps']],
              'contract': task.get('contract')}
    target = output / 'audit-report.md'
    if target.exists():
        text = target.read_text(encoding='utf-8')
        report['checks'] = {s: s.casefold() in text.casefold() for s in ('Overview', 'Evidence', 'Next steps', 'Juniper', 'Mira', '420', '3')}
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    assert task['state'] == 'COMPLETED', task.get('error') or task.get('question') or task['state']
    assert all(report.get('checks', {}).values()) and report.get('checks'), 'Report content or structure did not match'
    print('REPORT ' + str(output / 'verification.json'), flush=True)


if __name__ == '__main__':
    main()
