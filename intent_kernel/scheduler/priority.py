"""Priority scheduling (static priority, arrival-order tie-break)."""
from __future__ import annotations

from typing import List, Optional

from ..intent import HIGH, MEDIUM, LOW, PRIORITY_WEIGHT, Intent
from .base import Scheduler


class PriorityScheduler(Scheduler):
    """Always run the highest-priority READY intent first."""

    name = "priority"

    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        if not runnable:
            return None
        return min(
            runnable,
            key=lambda i: (-PRIORITY_WEIGHT.get(i.priority, 1), i.created_at, i.id),
        )
