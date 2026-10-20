"""Local application configuration. Credentials never enter the agent context."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def load_env():
    path = PROJECT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


class Config:
    def __init__(self, root=None):
        load_env()
        self.root = Path(root or os.environ.get('INTENTOS_DATA_DIR', PROJECT / 'storage' / 'runtime')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root.parent / 'workspace'
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'settings.json'
        self.values = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.ollama_url = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
        # Local inference is intentional; do not silently forward private files to a remote host.
        from urllib.parse import urlsplit
        parsed = urlsplit(self.ollama_url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username:
            raise ValueError('OLLAMA_HOST must be a local http:// loopback address')

    @property
    def model(self):
        return self.values.get('model') or os.environ.get('OLLAMA_MODEL', '')

    @property
    def roots(self):
        roots = self.values.get('roots', [])
        return list(dict.fromkeys([str(self.workspace.resolve()), *roots]))

    @property
    def provider(self):
        return self.values.get('provider', os.environ.get('AI_PROVIDER', 'ollama'))

    @property
    def gemini_model(self):
        return self.values.get('gemini_model', os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite'))

    @property
    def execution(self):
        return {**{'workers': 3, 'model_slots': 1, 'read_slots': 2, 'adaptive': True}, **self.values.get('execution', {})}

    @property
    def embedding_model(self):
        return self.values.get('embedding_model', '')

    @staticmethod
    def system_roots():
        if os.name == 'nt':
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            return [f'{chr(65 + i)}:\\' for i in range(26) if mask & (1 << i)]
        return ['/']

    def update(self, data):
        model = data.get('model', self.model)
        roots = data.get('roots', self.roots)
        if not isinstance(model, str) or len(model) > 200 or not isinstance(roots, list) or len(roots) > 20:
            raise ValueError('Invalid model or folder list')
        resolved = []
        for item in roots:
            if not isinstance(item, str) or not Path(item).expanduser().is_absolute() or not Path(item).expanduser().is_dir():
                raise ValueError(f'Folder does not exist: {item}')
            resolved.append(str(Path(item).expanduser().resolve()))
        provider = data.get('provider', self.provider)
        gemini_model = data.get('gemini_model', self.gemini_model)
        if provider not in ('ollama', 'gemini') or not isinstance(gemini_model, str) or not gemini_model.strip() or len(gemini_model) > 120:
            raise ValueError('Choose a supported AI provider and model')
        execution = {**self.execution, **data.get('execution', {})}
        if set(execution) != {'workers', 'model_slots', 'read_slots', 'adaptive'} or any(type(execution[k]) is not int or not 1 <= execution[k] <= 8 for k in ('workers', 'model_slots', 'read_slots')) or not isinstance(execution['adaptive'], bool):
            raise ValueError('Use 1–8 execution slots and a boolean adaptive setting')
        embedding_model = data.get('embedding_model', self.embedding_model)
        if not isinstance(embedding_model, str) or len(embedding_model) > 120:
            raise ValueError('Choose an installed local embedding model')
        values = {**self.values, 'model': model.strip(), 'roots': resolved, 'provider': provider, 'gemini_model': gemini_model.strip(), 'execution': execution, 'embedding_model': embedding_model.strip()}
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(values, indent=2), encoding='utf-8')
        temp.replace(self.path)
        self.values = values

    def public(self):
        from services.gemini import AIKeys
        return {'model': self.model, 'roots': self.roots, 'workspace': str(self.workspace),
                'ollama_url': self.ollama_url, 'local_only': self.provider == 'ollama',
                'provider': self.provider, 'gemini_model': self.gemini_model,
                'gemini_configured': bool(AIKeys(self).get()), 'system_roots': self.system_roots(),
                'execution': self.execution, 'embedding_model': self.embedding_model,
                'ocr_ready': (self.root / 'ocr' / 'eng.traineddata').is_file()}

