"""Authenticated, bounded uploads. Only explicit intent attachments become readable."""
import hashlib
import json
import re
import uuid
from pathlib import Path

MAX_UPLOAD = 100_000_000
EXTENSIONS = {'.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md', '.csv', '.json', '.png', '.jpg', '.jpeg', '.webp'}


class UploadStore:
    def __init__(self, config):
        self.root = config.root / 'attachments'
        self.root.mkdir(exist_ok=True)

    def receive(self, stream, name, length):
        name = Path(name.replace('\\', '/')).name
        if not name or len(name) > 160 or re.search(r'[\x00-\x1f<>:"|?*]', name) or name.startswith('.') or name.endswith((' ', '.')) or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
            raise ValueError('Use a simple filename without special characters')
        if Path(name).suffix.lower() not in EXTENSIONS:
            raise ValueError('Upload a PDF, Office document, text file, spreadsheet or image')
        if name.casefold() in {'credentials.json', 'secrets.json', 'passwords.txt', 'tokens.json'}:
            raise ValueError('Credential files cannot be attached')
        if not 0 < length <= MAX_UPLOAD:
            raise ValueError('Each upload must be between 1 byte and 100 MB')
        ident = uuid.uuid4().hex
        directory = self.root / ident
        directory.mkdir()
        path = directory / name
        remaining, digest = length, hashlib.sha256()
        try:
            with path.open('xb') as out:
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError('Upload interrupted; please try again')
                    remaining -= len(chunk)
                    digest.update(chunk)
                    out.write(chunk)
            metadata = {'id': ident, 'name': name, 'path': str(path), 'bytes': length, 'sha256': digest.hexdigest()}
            (directory / 'upload.json').write_text(json.dumps(metadata), encoding='utf-8')
            return metadata
        except Exception:
            path.unlink(missing_ok=True)
            (directory / 'upload.json').unlink(missing_ok=True)
            directory.rmdir()
            raise

    def resolve(self, refs):
        if not isinstance(refs, list) or len(refs) > 12:
            raise ValueError('Attach at most 12 files per intent')
        result, seen = [], set()
        for ref in refs:
            if not isinstance(ref, dict) or not re.fullmatch(r'[a-f0-9]{32}', str(ref.get('id', ''))):
                raise ValueError('Invalid attachment')
            if ref.get('role', 'source') not in ('source', 'reference'):
                raise ValueError('Choose source or reference for each attachment')
            if ref['id'] in seen:
                raise ValueError('The same attachment was selected twice')
            seen.add(ref['id'])
            try:
                data = json.loads((self.root / ref['id'] / 'upload.json').read_text(encoding='utf-8'))
                path = Path(data['path']).resolve()
                if not path.is_relative_to((self.root / ref['id']).resolve()) or not path.is_file():
                    raise ValueError('Attachment is no longer available')
            except (OSError, KeyError, json.JSONDecodeError):
                raise ValueError('Attachment is no longer available') from None
            result.append({**data, 'role': ref.get('role', 'source')})
        return result

    def remove(self, ident):
        data = self.resolve([{'id': ident}])[0]
        path = Path(data['path'])
        path.unlink()
        (path.parent / 'upload.json').unlink()
        path.parent.rmdir()
