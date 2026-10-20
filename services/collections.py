"""Local topic search with a persistent extraction cache and immutable-source collections."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

SKIP_DIRS = {'windows', 'program files', 'program files (x86)', 'programdata', 'appdata',
             'node_modules', '__pycache__', '$recycle.bin', 'system volume information',
             'venv', '.venv', 'site-packages', 'proc', 'sys', 'dev', 'run', 'lost+found'}
SKIP_DIRS |= {'dist', 'build', 'target', 'vendor', 'coverage', 'bower_components',
              'packages', 'env', 'envs', 'miniconda3', 'anaconda3', 'cuda', 'msys64'}
PROJECT_MARKERS = {'.git', 'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod',
                   'pom.xml', 'build.gradle', 'CMakeLists.txt', 'requirements.txt'}
TEXT_TYPES = {'.txt', '.md', '.csv', '.json', '.html', '.xml', '.yaml', '.yml', '.tex',
              '.py', '.js', '.ts', '.rst', '.pdf', '.docx', '.pptx', '.xlsx'}
STOP = set('a an the and or of to in on for with all files file related about topic documents document prepare meeting my me bring collect copy gather find search please that these those at into store save put move keep originals unchanged together'.split())


class FileCollections:
    def __init__(self, registry):
        self.registry = registry
        self.cache = registry.config.root / 'search-cache.sqlite3'

    @staticmethod
    def terms(query):
        from services.search_query import parse_query
        query, _ = parse_query(query)
        # A direct workflow is a topic search, not a natural-language planner.
        # Refuse path instructions rather than quietly searching for their words
        # and ignoring the user's requested destination.
        if re.search(r'[A-Za-z]:[\\/]|\\\\|(?:^|\s)/(?:\w|~)', query) or re.search(r'\b(?:store|save|put|move|copy)\b.+\b(?:at|to|in|into)\b', query, re.I):
            raise ValueError('Enter only topics here (for example: operating system, OS). Put the destination in New collection folder, or use Ask anything for a full instruction.')
        result = []
        # Commas/semicolons/newlines separate alternatives. Spaces retain a
        # phrase: "operating system" must not become "operating OR system".
        for alternative in re.split(r'[,;\n]+', query):
            words = [w.casefold() for w in re.findall(r'[^\W_]+', alternative)]
            while words and words[0] in STOP:
                words.pop(0)
            while words and words[-1] in STOP:
                words.pop()
            if words:
                phrase = ' '.join(words)
                if phrase not in result:
                    result.append(phrase)
        if not result:
            raise ValueError('Provide a topic or meaningful search terms')
        if len(result) > 20:
            raise ValueError('Use at most 20 comma-separated topic phrases')
        return result[:20]

    @staticmethod
    def pattern(term):
        words = term.split()
        # Treat underscores, dashes and whitespace as separators, and allow a
        # simple plural on the final word (system/systems, network/networks).
        ending = r'(?:s)?' if len(words[-1]) > 3 and not words[-1].endswith('s') else ''
        return re.compile(r'(?<![^\W_])' + r'[\W_]+'.join(re.escape(w) for w in words) + ending + r'(?![^\W_])', re.I)

    def search(self, args, task, exclude=None):
        from services.file_scan import FileScan
        import uuid
        scanner = FileScan(self)
        pending = task.get('pending') or {}
        job_id = pending.get('id') or uuid.uuid4().hex
        while True:
            result = scanner.batch(args, task, exclude, job_id)
            if result['status'] != 'scanning' or pending.get('id'):
                return result
            # Direct library callers run synchronously. Kernel calls yield after
            # each batch, retaining the action ID and durable scan cursor.

    def scan_incomplete(self, action_id):
        import sqlite3
        from contextlib import closing
        try:
            with closing(sqlite3.connect(self.cache, timeout=2)) as db:
                row = db.execute('SELECT data FROM scan_jobs WHERE id=?', (action_id,)).fetchone()
                return bool(row and json.loads(row[0])['phase'] != 'complete')
        except (sqlite3.Error, ValueError, KeyError):
            return False

    def collect(self, args, task):
        target = self.registry.path(args['destination'], task)
        if target.exists():
            raise ValueError('Choose a new collection folder; existing folders are never overwritten')
        found = self.search(args, task, target)
        if found['status'] == 'scanning':
            return found
        if not found['matches']:
            return {**found, 'status': 'no_matches', 'copied': 0, 'source_files_modified': False}
        if sum(m['bytes'] for m in found['matches']) > 500_000_000:
            raise ValueError('Collection exceeds 500 MB. Narrow the topic or source folders.')
        target.mkdir(parents=True, exist_ok=False)
        files_dir = target / 'files'
        files_dir.mkdir()
        copied = []
        # Persist after each file. Interrupted writes enter REVIEW in the kernel;
        # this manifest makes reconciliation possible without replaying copies.
        manifest = target / 'manifest.json'
        record = {k: v for k, v in found.items() if k != 'matches'}
        record.update({'files': copied, 'status': 'copying', 'source_files_modified': False})
        def save_manifest():
            temporary = target / '.manifest.tmp'
            temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
            temporary.replace(manifest)
        save_manifest()
        for match in found['matches']:
            source = self.registry.path(match['path'], task)
            stat = source.stat()
            if stat.st_mtime_ns != match['modified_ns'] or stat.st_size != match['bytes']:
                raise ValueError('A source changed during the scan. Existing copies and manifest were preserved for review.')
            name = source.name
            destination = files_dir / name
            if destination.exists():
                name = source.stem + '-' + hashlib.sha256(str(source).encode()).hexdigest()[:12] + source.suffix
                destination = files_dir / name
            digest = hashlib.sha256()
            with source.open('rb') as src, destination.open('xb') as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    digest.update(chunk)
                    dst.write(chunk)
            if source.stat().st_mtime_ns != stat.st_mtime_ns:
                raise ValueError('A source changed while copying; review the collection manifest.')
            copied.append({**match, 'copy': str(destination), 'sha256': digest.hexdigest()})
            save_manifest()
        record['status'] = 'complete'
        save_manifest()
        archive = target / 'collection.zip'
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(manifest, 'manifest.json')
            for item in copied:
                bundle.write(item['copy'], 'files/' + Path(item['copy']).name)
        return {**{k: v for k, v in found.items() if k != 'matches'}, 'status': 'collected',
                'folder': str(target), 'artifact': str(archive), 'manifest': str(manifest),
                'copied': len(copied), 'files': copied, 'source_files_modified': False}
