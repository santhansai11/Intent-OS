"""First-Come, First-Served scheduling."""
from __future__ import annotations

from typing import List, Optional

from ..intent import Intent
from .base import Scheduler


class FCFSScheduler(Scheduler):
    """Run intents in strict arrival order (queue discipline)."""

    name = "fcfs"

    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        if not runnable:
            return None
        return min(runnable, key=lambda i: (i.created_at, i.id))
