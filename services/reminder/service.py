"""Reminder service: schedules reminders (persisted to reminders.json)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from intent_kernel.paths import reminders_path
from services.base_service import BaseService


class ReminderService(BaseService):
    """Mock reminder: writes scheduled reminders to storage/reminders.json."""

    name = "reminder"
    description = "Reminder scheduling (persisted mock)"

    def __init__(self, reminders_path_override=None, **kw):
        super().__init__(**kw)
        self.reminders_path = Path(reminders_path_override) if reminders_path_override else reminders_path()

    def cap_set_reminder(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Create a reminder at the requested time."""
        when = params.get("time") or "later"
        note = params.get("note") or params.get("summary") or "Reminder"
        reminder_id = f"R{int(time.time() * 1000) % 1000000:06d}"
        record = {
            "id": reminder_id,
            "time": when,
            "note": note[:200],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            self.reminders_path.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if self.reminders_path.exists():
                try:
                    existing = json.loads(self.reminders_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = []
            existing.append(record)
            self.reminders_path.write_text(
                json.dumps(existing, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # persistence is best-effort in the prototype
        return {"reminder_id": reminder_id, "time": when, "status": "scheduled"}
