"""Intent File Manager: per-intent execution context on the filesystem.

Each intent gets a directory under storage/intent_logs/:

    /storage/intent_logs/I1024/
        intent.json      # metadata snapshot
        plan.json        # execution plan
        permissions.json # permission decisions
        checkpoint.json  # recovery state (written by CheckpointManager)
        execution.log    # append-only activity log
        output/          # artifacts produced by services
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import intent_logs_dir


class IntentFileManager:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else intent_logs_dir()

    # ------------------------------------------------------------------
    def context_dir(self, intent_id: str) -> Path:
        d = self.base_dir / intent_id
        (d / "output").mkdir(parents=True, exist_ok=True)
        return d

    def output_dir(self, intent_id: str) -> Path:
        return self.context_dir(intent_id) / "output"

    # ------------------------------------------------------------------
    def initialize(self, intent) -> None:
        d = self.context_dir(intent.id)
        (d / "execution.log").touch(exist_ok=True)
        intent.log("Intent context directory created")
        self.write_all(intent)

    def write_all(self, intent) -> None:
        d = self.context_dir(intent.id)
        meta = intent.to_dict(include_log=True)
        plan = {"intent_id": intent.id, "steps": intent.plan}
        perms = {"intent_id": intent.id, "decisions": intent.blocked}
        self._write_json(d / "intent.json", meta)
        self._write_json(d / "plan.json", plan)
        self._write_json(d / "permissions.json", perms)

    def log(self, intent_id: str, line: str) -> None:
        d = self.context_dir(intent_id)
        with open(d / "execution.log", "a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")

    def save_output(self, intent_id: str, filename: str, content: str) -> Path:
        path = self.output_dir(intent_id) / filename
        path.write_text(content, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    def write_json(self, intent_id: str, filename: str, data: Any) -> None:
        self._write_json(self.context_dir(intent_id) / filename, data)

    def read_json(self, intent_id: str, filename: str) -> Optional[Any]:
        path = self.base_dir / intent_id / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
