"""Durable, breadth-first file discovery followed by cached content extraction.

Only read-side work occurs here. Each batch commits its queue and counters before
yielding to the scheduler. Output copying begins only after discovery completes.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


class FileScan:
    def __init__(self, collections):
        self.owner = collections
        self.registry = collections.registry

    def batch(self, args, task, exclude=None, job_id=None):
        import sqlite3
        from services.collections import SKIP_DIRS, TEXT_TYPES
        topics = self.owner.terms(args['query'])
        patterns = {t: self.owner.pattern(t) for t in topics}
        roots = list(task.get('search_roots', task['roots']))
        if task.get('access_mode') == 'system':
            roots = [str(Path.home() / n) for n in ('Documents', 'Desktop', 'Downloads')] + roots
        excluded = Path(exclude).resolve() if exclude else None
        job_id = job_id or task.get('pending', {}).get('id') or uuid.uuid4().hex
        signature = hashlib.sha256(json.dumps([topics, roots, task['roots'], str(excluded)], sort_keys=True).encode()).hexdigest()
        started = time.monotonic()
        batch_items = self.registry.config.values.get('scan_batch_items', 250)
        batch_seconds = self.registry.config.values.get('scan_batch_seconds', 2)
        with closing(sqlite3.connect(self.owner.cache, timeout=10)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, stamp TEXT, content TEXT);
                CREATE TABLE IF NOT EXISTS scan_jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scan_queue(
                    seq INTEGER PRIMARY KEY, job TEXT, path TEXT, kind TEXT,
                    done INTEGER DEFAULT 0, match TEXT, UNIQUE(job,path));
                CREATE INDEX IF NOT EXISTS scan_work ON scan_queue(job,kind,done,seq);
            ''')
            row = db.execute('SELECT data FROM scan_jobs WHERE id=?', (job_id,)).fetchone()
            if row:
                state = json.loads(row[0])
                if state['signature'] != signature:
                    raise ValueError('Scan grants or query changed; start a new collection')
            else:
                state = {'signature': signature, 'phase': 'discover', 'scanned': 0, 'extracted': 0,
                         'cache_hits': 0, 'skipped_or_unreadable': 0, 'excluded_generated': 0, 'seconds': 0}
                for raw in roots:
                    try:
                        root = self.registry.path(raw, task)
                        if root.is_dir():
                            db.execute('INSERT OR IGNORE INTO scan_queue(job,path,kind) VALUES (?,?,?)', (job_id, str(root), 'entry'))
                    except (OSError, ValueError):
                        state['skipped_or_unreadable'] += 1

            def match_file(path, stat, content):
                name_hits = {t for t, p in patterns.items() if p.search(path.stem)}
                body_hits = {t: p.search(content) for t, p in patterns.items()}
                hits = [t for t in topics if t in name_hits or body_hits[t]]
                if not hits:
                    return None
                index = next((body_hits[t].start() for t in hits if body_hits[t]), 0)
                return json.dumps({'path': str(path), 'name': path.name, 'bytes': stat.st_size,
                    'modified_ns': stat.st_mtime_ns, 'score': sum(5 if t in name_hits else 1 for t in hits),
                    'matched_terms': hits, 'excerpt': content[max(0, index-80):index+300], 'name_only': not content})

            processed = 0
            while state['phase'] != 'complete' and processed < batch_items:
                if processed and time.monotonic() - started >= batch_seconds:
                    break
                kind = 'entry' if state['phase'] == 'discover' else 'content'
                row = db.execute('SELECT seq,path FROM scan_queue WHERE job=? AND kind=? AND done=0 ORDER BY seq LIMIT 1', (job_id, kind)).fetchone()
                if not row:
                    state['phase'] = 'extract' if kind == 'entry' else 'complete'
                    continue
                seq, raw = row
                processed += 1
                try:
                    candidate = Path(raw)
                    # Check links before canonicalizing, to avoid following aliases.
                    if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
                        raise ValueError('Link excluded')
                    path = self.registry.path(raw, task)
                    if excluded and path.is_relative_to(excluded):
                        db.execute('UPDATE scan_queue SET done=1 WHERE seq=?', (seq,))
                        continue
                    if kind == 'entry' and path.is_dir():
                        # Do not collect copies from earlier IntentOS collections.
                        manifest = path / 'manifest.json'
                        generated = False
                        if (path / 'collection.zip').is_file() and (path / 'files').is_dir() and manifest.is_file():
                            try:
                                with manifest.open('r', encoding='utf-8') as file:
                                    data = json.loads(file.read(2_000_000))
                                generated = data.get('source_files_modified') is False and isinstance(data.get('files'), list)
                            except (ValueError, OSError):
                                pass
                        if generated:
                            state['excluded_generated'] += 1
                        else:
                            with os.scandir(path) as entries:
                                def children():
                                    for entry in entries:
                                        if entry.name.startswith('.') or entry.is_symlink():
                                            continue
                                        if entry.is_dir(follow_symlinks=False) and entry.name.casefold() in SKIP_DIRS:
                                            continue
                                        yield (job_id, entry.path, 'entry')
                                db.executemany('INSERT OR IGNORE INTO scan_queue(job,path,kind) VALUES (?,?,?)', children())
                        db.execute('UPDATE scan_queue SET done=1 WHERE seq=?', (seq,))
                        continue
                    if not path.is_file():
                        raise ValueError('Unavailable file')
                    stat = path.stat()
                    if kind == 'entry':
                        state['scanned'] += 1
                        if stat.st_size > 100_000_000:
                            state['skipped_or_unreadable'] += 1
                            db.execute('UPDATE scan_queue SET done=1 WHERE seq=?', (seq,))
                            continue
                        matched = match_file(path, stat, '')
                        extract = path.suffix.lower() in TEXT_TYPES and stat.st_size <= 10_000_000
                        db.execute('UPDATE scan_queue SET kind=?,done=?,match=? WHERE seq=?',
                                   ('content' if extract else 'entry', 0 if extract else 1, matched, seq))
                    else:
                        state['extracted'] += 1
                        stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
                        cached = db.execute('SELECT stamp,content FROM documents WHERE path=?', (str(path),)).fetchone()
                        if cached and cached[0] == stamp:
                            content = cached[1]
                            state['cache_hits'] += 1
                        else:
                            content = self.registry.read({'path': str(path)}, task)['content']
                            db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)', (str(path), stamp, content))
                        db.execute('UPDATE scan_queue SET match=?,done=1 WHERE seq=?', (match_file(path, stat, content), seq))
                except Exception:
                    # Unsupported/encrypted documents keep any filename match.
                    state['skipped_or_unreadable'] += 1
                    db.execute('UPDATE scan_queue SET done=1 WHERE seq=?', (seq,))
            state['seconds'] += time.monotonic() - started
            db.execute('INSERT OR REPLACE INTO scan_jobs VALUES (?,?)', (job_id, json.dumps(state)))
            matched = db.execute('SELECT COUNT(*) FROM scan_queue WHERE job=? AND match IS NOT NULL', (job_id,)).fetchone()[0]
            remaining = db.execute('SELECT COUNT(*) FROM scan_queue WHERE job=? AND done=0', (job_id,)).fetchone()[0]
            result = {k: v for k, v in state.items() if k != 'signature'}
            result.update({'status': 'scanning' if state['phase'] != 'complete' else 'searched', 'scan_id': job_id,
                'query': args['query'], 'effective_topics': topics, 'matched': matched, 'remaining': remaining,
                'truncated': False, 'matching': 'whole topic phrases; comma-separated alternatives',
                'coverage': 'Readable non-system files; filenames and first 16000 characters of supported documents. No OCR. Prior IntentOS collections excluded.',
                'seconds': round(state['seconds'], 3),
                'note': 'Scan in progress; remaining folders and document contents will be checked.' if state['phase'] != 'complete' else 'Scan completed within the selected folders and exclusions.'})
            if state['phase'] == 'complete':
                result['matches'] = [json.loads(r[0]) for r in db.execute('SELECT match FROM scan_queue WHERE job=? AND match IS NOT NULL', (job_id,))]
                result['matches'].sort(key=lambda m: (-m['score'], m['path'].casefold()))
            return result
