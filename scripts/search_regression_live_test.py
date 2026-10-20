"""Opt-in Gemini regression with synthetic documents only; preserves a report."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from intent_kernel.config import Config, PROJECT
from intent_kernel.runtime import Runtime
from services.gemini import AIKeys


def main():
    real = Config()
    run = PROJECT / 'storage_test' / ('search-regression-' + uuid.uuid4().hex[:10])
    config = Config(run / 'runtime')
    source = run / 'sources'
    source.mkdir()
    fixtures = {
        'notes.txt': ('AWS cloud architecture: EC2 and S3.', '2026-09-02'),
        'AWS-old.txt': ('AWS cloud architecture.', '2026-08-01'),
        'AWS-boundary.txt': ('AWS boundary day.', '2026-09-01T23:59:59'),
        'holiday.txt': ('Beach and sunshine.', '2026-09-03'),
        'project/package.json': ('{}', '2026-09-03'),
        'project/aws-tool.txt': ('AWS tool dependency.', '2026-09-03'),
    }
    for name, (content, date) in fixtures.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        stamp = datetime.fromisoformat(date).timestamp()
        os.utime(path, (stamp, stamp))
    def hashes():
        return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    before = hashes()
    config.update({'provider': 'gemini', 'gemini_model': real.gemini_model, 'roots': [str(source)]})
    runtime = Runtime(config)
    runtime.planner.gemini.keys = AIKeys(real)
    try:
        task = runtime.submit('Gather all AWS related files which were saved after September 1 2026 into a new AWS Related files folder. Preserve originals.',
                              roots=[str(source)], search_roots=[str(source)], output_folder=str(config.workspace), auto_outputs=True)
        started = time.monotonic()
        for _ in range(30):
            runtime.tick()
            task = runtime.tasks[task['id']]
            if task['state'] in ('COMPLETED', 'FAILED', 'BLOCKED', 'APPROVAL', 'WAITING_INPUT', 'REVIEW'):
                break
            if task['state'] == 'RECOVERY':
                time.sleep(min(5, max(0, task['retry_at'] - time.time())))
        collected = [s for s in task['steps'] if s['tool'] == 'files_collect']
        files = collected[-1]['result'].get('files', []) if collected else []
        report = {'state': task['state'], 'seconds': round(time.monotonic()-started, 2),
                  'copied': [f['name'] for f in files], 'originals_preserved': hashes() == before,
                  'steps': [{'tool': s['tool'], 'arguments': s.get('arguments'), 'result': s['result']} for s in task['steps']],
                  'error': task['error']}
        report['passed'] = task['state'] == 'COMPLETED' and report['copied'] == ['notes.txt'] and report['originals_preserved']
        (run / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({k: report[k] for k in ('passed', 'state', 'seconds', 'copied', 'originals_preserved', 'error')}))
        print('Report: ' + str(run / 'verification.json'))
        return 0 if report['passed'] else 1
    finally:
        runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())
