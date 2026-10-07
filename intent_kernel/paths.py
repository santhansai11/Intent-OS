"""Shared path resolution for IntentOS storage locations.

Paths are resolved at call time so that the INTENTOS_ROOT environment
variable can redirect ALL storage writes (used by tests to run in a
temporary directory without touching the real project storage).
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def root() -> Path:
    return Path(os.environ.get("INTENTOS_ROOT") or _DEFAULT_ROOT)


def storage_dir() -> Path:
    return root() / "storage"


def intent_logs_dir() -> Path:
    return storage_dir() / "intent_logs"


def documents_dir() -> Path:
    return storage_dir() / "documents"


def downloads_dir() -> Path:
    return storage_dir() / "downloads"


def db_path() -> Path:
    return storage_dir() / "intents.db"


def reminders_path() -> Path:
    return storage_dir() / "reminders.json"


def backups_dir() -> Path:
    return storage_dir() / "backups"


def workspace_dir() -> Path:
    """User-visible folder where intents write the files they produce."""
    return storage_dir() / "workspace"


def ensure_storage_dirs() -> None:
    """Create all runtime storage directories if missing."""
    for d in (storage_dir(), intent_logs_dir(), documents_dir(), downloads_dir(),
              backups_dir(), workspace_dir()):
        d.mkdir(parents=True, exist_ok=True)


def relative_to_root(path) -> str:
    """Best-effort project-relative display path (used by the UI)."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(root().resolve())).replace("\\", "/")
    except ValueError:
        return str(p)
