"""The capability boundary: schemas, per-intent paths, resource identities and real I/O."""
from __future__ import annotations

import base64
import os
import re
import shutil
import tempfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode

from intent_kernel.config import PROJECT
from intent_kernel.resource_manager.monitor import system_snapshot
from services.connections import request_json
from services.web.service import WebService


def string(description):
    return {'type': 'string', 'description': description}


class CapabilityRegistry:
    def __init__(self, config, google):
        self.config, self.google = config, google
        self.tools = {}
        self.add('system_status', 'Inspect actual host CPU, memory and platform.', 'system', False, {}, [], self.system)
        self.add('files_list', 'List a folder. Returns absolute paths, sizes and modification times.', 'files', False,
                 {'path': string('Folder; use . for the first granted folder')}, ['path'], self.list_files)
        self.add('files_search', 'Search names under a folder recursively; bounded to 5000 entries.', 'files', False,
                 {'path': string('Folder'), 'query': string('Filename substring')}, ['path', 'query'], self.search)
        self.add('files_read', 'Read text, PDF text, or Office document text. No OCR.', 'files', False,
                 {'path': string('File to read')}, ['path'], self.read)
        self.add('files_write', 'Create or replace a UTF-8 text file; exact content is shown for approval.', 'files', True,
                 {'path': string('Destination text file'), 'content': string('Complete file content')}, ['path', 'content'], self.write)
        self.add('files_copy', 'Copy a file to a new location; existing destinations are rejected.', 'files', True,
                 {'source': string('Existing file'), 'destination': string('New file path')}, ['source', 'destination'], self.copy)
        self.add('files_move', 'Move a file to a new location; existing destinations are rejected.', 'files', True,
                 {'source': string('Existing file'), 'destination': string('New file path')}, ['source', 'destination'], self.move)
        from services.pdf_tools import PdfTools
        pdf = PdfTools(self.path)
        from services.collections import FileCollections
        from services.documents import DocumentExporter, FORMATS
        self.collections = FileCollections(self)
        self.add('files_find_related', 'Search filenames and cached document text across ALL granted folders by topic. query may include synonyms. Returns ranked matches and explicit coverage limits.', 'files', False,
                 {'query': string('Topic phrases; separate alternative topics or synonyms with commas. Example: operating system, OS. No instructions or paths.')}, ['query'], self.collections.search)
        self.add('files_collect', 'Gather topic-related existing files across ALL granted folders into a NEW separate folder. Copy only; originals stay unchanged. Includes manifest and downloadable ZIP. Never use files_move for gathering.', 'files', True,
                 {'query': string('Topic phrases; separate alternative topics or synonyms with commas. Example: operating system, OS. No instructions or paths.'), 'destination': string('New collection folder, not a filename')}, ['query', 'destination'], self.collections.collect)
        self.add('document_export', 'Create a NEW summary/report in the format selected by destination extension. Supported: ' + ', '.join(FORMATS) + '. Provide real complete content, not a promise or placeholder.', 'files', True,
                 {'destination': string('New output file with the requested extension; folders are created'),
                  'title': string('Document title'), 'content': string('Complete Markdown content with headings and source URLs when available')},
                 ['destination', 'title', 'content'], DocumentExporter(self).export)
        self.add('pdf_replace_text', 'Replace exact single-line text in a PDF and save a NEW PDF copy. Source is never modified. ASCII text; no scanned, signed or form PDFs.', 'files', True,
                 {'source': string('Existing source PDF'), 'destination': string('New output .pdf path; parent folders are created'),
                  'find': string('Exact existing text'), 'replace': string('Replacement text that fits the original space')},
                 ['source', 'destination', 'find', 'replace'], pdf.replace_text)
        self.add('pdf_merge', 'Merge PDFs in the given order into a NEW PDF in a separate destination. Source files are never modified.', 'files', True,
                 {'sources': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 2, 'maxItems': 20,
                              'description': 'Ordered list of 2 to 20 existing PDF paths'},
                  'destination': string('New merged .pdf path; parent folders are created')}, ['sources', 'destination'], pdf.merge)
        self.add('web_search', 'Live Wikipedia and DuckDuckGo knowledge search; not a complete web index.', 'web', False,
                 {'query': string('Search query')}, ['query'], self.web_search)
        self.add('web_article', 'Fetch a Wikipedia article introduction by title.', 'web', False,
                 {'title': string('Wikipedia article title')}, ['title'], self.web_article)
        self.add('research_topic', 'Research a topic using free Wikipedia, Crossref and Open Library APIs. Returns real source titles, excerpts and URLs; partial provider failures are reported.', 'web', False,
                 {'query': string('Topic to research')}, ['query'], self.research_topic)
        self.add('calendar_list', 'Read real Google Calendar events in a specified time window.', 'calendar', False,
                 {'start': string('RFC3339 timestamp with timezone'), 'end': string('RFC3339 timestamp with timezone')}, ['start', 'end'], self.calendar_list)
        self.add('calendar_create', 'Create a Google Calendar event without inviting attendees.', 'calendar', True,
                 {k: string(v) for k, v in {'title': 'Event title', 'start': 'RFC3339 timestamp with timezone',
                  'end': 'RFC3339 timestamp with timezone', 'location': 'Location or empty string', 'description': 'Description'}.items()},
                 ['title', 'start', 'end', 'location', 'description'], self.calendar_create)
        self.add('drive_search', 'Search real Google Drive file metadata; does not download file content.', 'drive', False,
                 {'query': string('Filename substring')}, ['query'], self.drive_search)
        self.add('gmail_send', 'Send a real email through the connected Google account. Requires approval.', 'gmail', True,
                 {'to': string('One complete email address'), 'subject': string('Subject'), 'body': string('Plain text body')},
                 ['to', 'subject', 'body'], self.gmail_send)
        self.add('maps_route', 'Compute a real Google Maps route; requires a Routes API key.', 'maps', False,
                 {'origin': string('Starting address'), 'destination': string('Destination address'),
                  'mode': {'type': 'string', 'enum': ['DRIVE', 'WALK', 'BICYCLE', 'TRANSIT']}},
                 ['origin', 'destination', 'mode'], self.maps_route)

    def add(self, name, description, scope, writes, properties, required, function):
        self.tools[name] = {'name': name, 'description': description, 'scope': scope, 'writes': writes,
                            'parameters': {'type': 'object', 'properties': properties, 'required': required,
                                           'additionalProperties': False}, 'function': function}

    def catalog(self):
        return [{k: v for k, v in tool.items() if k != 'function'} for tool in self.tools.values()]

    def validate(self, action, task):
        if 'complete_after' in action and not isinstance(action['complete_after'], bool):
            raise ValueError('complete_after must be a boolean')
        name, args = action['tool'], action['arguments']
        if name not in self.tools:
            raise ValueError(f'Unknown capability: {name}')
        spec = self.tools[name]['parameters']
        if set(args) - set(spec['properties']) or set(spec['required']) - set(args):
            raise ValueError(f'Arguments do not match the schema for {name}')
        for key, value in args.items():
            prop = spec['properties'][key]
            if prop['type'] == 'array':
                if not isinstance(value, list) or not prop['minItems'] <= len(value) <= prop['maxItems']:
                    raise ValueError(f'Invalid {key}: expected {prop["minItems"]} to {prop["maxItems"]} paths')
                if any(not isinstance(item, str) or not item.strip() or len(item) > 4096 for item in value):
                    raise ValueError(f'Invalid {key}: expected file paths')
            elif not isinstance(value, str) or len(value) > 100000:
                raise ValueError(f'Invalid {key}: expected text within 100000 characters')
            if 'enum' in prop and value not in prop['enum']:
                raise ValueError(f'Invalid {key}')
        if self.tools[name]['scope'] == 'files':
            # Normalize before approval and validate again immediately before dispatch.
            for key in ('path', 'source', 'destination'):
                if key in args:
                    raw = args[key]
                    if task.get('output_folder') and not Path(raw).is_absolute() and (key == 'destination' or (key == 'path' and name == 'files_write')):
                        raw = str(Path(task['output_folder']) / raw)
                    resolved = str(self.path(raw, task))
                    if action.get('id') and resolved != args[key]:
                        raise ValueError('The path target changed after planning. Replan before using it.')
                    args[key] = resolved
            if 'sources' in args:
                resolved = [str(self.path(raw, task)) for raw in args['sources']]
                if action.get('id') and resolved != args['sources']:
                    raise ValueError('A source path changed after planning; replan before using it')
                args['sources'] = resolved
        return self.tools[name]

    def path(self, raw, task):
        if not task['roots']:
            raise ValueError('No folders are granted to this intent')
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path(task['roots'][0]) / path
        path = path.resolve()
        roots = [Path(r).resolve() for r in task['roots']]
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError('Path is outside this intent’s granted folders')
        if path.is_relative_to(self.config.root) or path == PROJECT / '.env':
            raise ValueError('IntentOS settings and runtime data are private')
        if any(p.startswith('.') or p.lower() in ('node_modules', '__pycache__') for p in path.parts):
            raise ValueError('Hidden and application metadata paths are excluded')
        from services.collections import SKIP_DIRS
        relative_parts = path.relative_to(min((r for r in roots if path.is_relative_to(r)), key=lambda r: len(r.parts))).parts
        if any(p.casefold() in SKIP_DIRS for p in relative_parts):
            raise ValueError('OS-managed directories and application caches are excluded')
        if path.name.casefold() in ('credentials.json', 'secrets.json', 'passwords.txt', 'tokens.json', 'id_rsa', 'id_ed25519'):
            raise ValueError('Credential files are excluded')
        if path.suffix.lower() in ('.pem', '.key', '.pfx', '.p12', '.kdbx'):
            raise ValueError('Credential files are excluded')
        return path

    def resource(self, action):
        if not action:
            return 'local-model'
        scope = self.tools[action['tool']]['scope']
        # Coarse exclusive locks intentionally serialize file operations, including aliases.
        return 'filesystem' if scope == 'files' else scope

    def execute(self, action, task):
        tool = self.validate(action, task)
        return tool['function'](action['arguments'], task)

    def system(self, args, task):
        return system_snapshot()

    def entries(self, root, task, recursive=False):
        if not root.is_dir():
            raise ValueError('The requested path is not a folder')
        count = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in sorted(dirs) if not d.startswith('.') and d not in ('node_modules', '__pycache__')]
            for name in sorted(dirs + files):
                count += 1
                if count > 5000:
                    return
                p = Path(directory) / name
                try:
                    p = self.path(str(p), task)
                    stat = p.stat()
                    yield {'name': p.name, 'path': str(p), 'directory': p.is_dir(),
                           'bytes': stat.st_size, 'modified': stat.st_mtime}
                except (OSError, ValueError):
                    continue
            if not recursive:
                return

    def list_files(self, args, task):
        from itertools import islice
        return {'entries': list(islice(self.entries(self.path(args['path'], task), task), 200)), 'limit': 200}

    def search(self, args, task):
        from itertools import islice
        matches = (p for p in self.entries(self.path(args['path'], task), task, True)
                   if args['query'].lower() in p['name'].lower())
        return {'matches': list(islice(matches, 100)), 'limit': 100, 'scan_limit': 5000}

    def read(self, args, task):
        path = self.path(args['path'], task)
        if not path.is_file() or path.stat().st_size > 10_000_000:
            raise ValueError('Choose a file smaller than 10 MB')
        if path.suffix.lower() == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            if reader.is_encrypted or len(reader.pages) > 200:
                raise ValueError('Choose an unlocked PDF with at most 200 pages')
            content = ''
            for page in reader.pages:
                content += (page.extract_text() or '') + '\n'
                if len(content) > 16000:
                    break
        elif path.suffix.lower() in ('.docx', '.pptx', '.xlsx'):
            if path.suffix.lower() != '.pdf':
                import zipfile
                with zipfile.ZipFile(path) as archive:
                    if sum(i.file_size for i in archive.infolist()) > 20_000_000:
                        raise ValueError('Document decompression limit exceeded')
            from services.filesystem.service import _extract_document_text
            content = _extract_document_text(path)
        else:
            with path.open('rb') as file:
                raw = file.read(60001)
            if b'\x00' in raw:
                raise ValueError('This binary file is not a supported document')
            content = raw.decode('utf-8', errors='replace')
        return {'path': str(path), 'content': content[:16000], 'truncated': len(content) > 16000}

    def write(self, args, task):
        path = self.path(args['path'], task)
        if path.suffix.lower() not in ('.txt', '.md', '.csv', '.json', '.html', '.css', '.py', '.js', '.tex', '.yaml', '.yml'):
            raise ValueError('files_write creates text formats only (for example .md or .txt)')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.intentos-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                file.write(args['content'])
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'artifact': str(path), 'bytes': path.stat().st_size, 'status': 'written'}

    def copy(self, args, task):
        source, target = self.path(args['source'], task), self.path(args['destination'], task)
        if not source.is_file() or source.stat().st_size > 100_000_000:
            raise ValueError('Copy requires a file smaller than 100 MB')
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        return {'artifact': str(target), 'status': 'copied'}

    def move(self, args, task):
        result = self.copy(args, task)
        self.path(args['source'], task).unlink()
        return {**result, 'status': 'moved'}

    def web_search(self, args, task):
        return WebService(timeout=12).cap_search({'query': args['query'], 'limit': 5})

    def web_article(self, args, task):
        return WebService(timeout=12).cap_fetch(args)

    def research_topic(self, args, task):
        from concurrent.futures import ThreadPoolExecutor
        query = args['query'][:300]
        def crossref():
            data = request_json('https://api.crossref.org/works?' + urlencode({'query.bibliographic': query, 'rows': 4}), timeout=12)
            return [{'title': (r.get('title') or ['Untitled'])[0], 'url': r.get('URL', ''),
                     'excerpt': re.sub('<[^>]+>', '', r.get('abstract', ''))[:900], 'provider': 'Crossref'} for r in data.get('message', {}).get('items', [])]
        def books():
            data = request_json('https://openlibrary.org/search.json?' + urlencode({'q': query, 'limit': 3, 'fields': 'key,title,author_name,first_publish_year'}), timeout=12)
            return [{'title': r['title'], 'url': 'https://openlibrary.org' + r['key'],
                     'excerpt': ', '.join(r.get('author_name', [])[:3]), 'provider': 'Open Library'} for r in data.get('docs', [])]
        def wiki():
            data = request_json('https://en.wikipedia.org/w/api.php?' + urlencode({'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': 4, 'format': 'json'}), timeout=12)
            return [{'title': r['title'], 'url': 'https://en.wikipedia.org/?curid=' + str(r['pageid']),
                     'excerpt': re.sub('<[^>]+>', '', r.get('snippet', '')), 'provider': 'Wikipedia'} for r in data.get('query', {}).get('search', [])]
        sources, errors = [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [(name, pool.submit(fn)) for name, fn in [('Wikipedia', wiki), ('Crossref', crossref), ('Open Library', books)]]
            for name, future in futures:
                try:
                    sources.extend(future.result())
                except Exception:
                    errors.append(name + ' unavailable')
        return {'query': query, 'sources': sources, 'provider_errors': errors,
                'note': 'Search excerpts and bibliographic metadata; not full-text access to every source.'}

    @staticmethod
    def dates(args):
        start, end = [datetime.fromisoformat(args[k].replace('Z', '+00:00')) for k in ('start', 'end')]
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError('Start and end need timezones; end must be later than start')

    def calendar_list(self, args, task):
        self.dates(args)
        url = 'https://www.googleapis.com/calendar/v3/calendars/primary/events?' + urlencode({
            'timeMin': args['start'], 'timeMax': args['end'], 'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 50})
        data = self.google.call('calendar', url)
        return {'events': [{k: e.get(k) for k in ('id', 'summary', 'start', 'end', 'location', 'description', 'htmlLink', 'attachments')}
                           for e in data.get('items', [])], 'more': bool(data.get('nextPageToken'))}

    def calendar_create(self, args, task):
        self.dates(args)
        import hashlib
        event_id = hashlib.sha256(task['pending']['id'].encode()).hexdigest()
        return self.google.call('calendar', 'https://www.googleapis.com/calendar/v3/calendars/primary/events', {
            'id': event_id, 'summary': args['title'], 'description': args['description'], 'location': args['location'],
            'start': {'dateTime': args['start']}, 'end': {'dateTime': args['end']}})

    def drive_search(self, args, task):
        query = args['query'].replace('\\', '\\\\').replace("'", "\\'")
        url = 'https://www.googleapis.com/drive/v3/files?' + urlencode({
            'q': f"trashed = false and name contains '{query}'", 'pageSize': 50,
            'fields': 'nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime)'})
        return self.google.call('drive', url)

    def gmail_send(self, args, task):
        if not re.fullmatch(r'[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+', args['to']):
            raise ValueError('Supply one complete recipient email address')
        mail = EmailMessage()
        mail['To'], mail['Subject'] = args['to'], args['subject']
        mail.set_content(args['body'])
        raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
        return self.google.call('gmail', 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send', {'raw': raw})

    def maps_route(self, args, task):
        key = os.environ.get('GOOGLE_MAPS_API_KEY')
        if not key:
            raise ValueError('Set GOOGLE_MAPS_API_KEY in .env and enable Google Routes API')
        data = request_json('https://routes.googleapis.com/directions/v2:computeRoutes', {
            'origin': {'address': args['origin']}, 'destination': {'address': args['destination']},
            'travelMode': args['mode']}, {'X-Goog-Api-Key': key,
            'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters,routes.description'})
        if not data.get('routes'):
            raise ValueError('Google found no route for these locations')
        return {**data, 'maps_url': 'https://www.google.com/maps/dir/?' + urlencode({
            'api': 1, 'origin': args['origin'], 'destination': args['destination']})}
