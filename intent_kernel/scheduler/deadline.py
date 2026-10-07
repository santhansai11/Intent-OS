"""Deadline-aware scheduling (Earliest Deadline First)."""
from __future__ import annotations

from typing import List, Optional

from ..intent import HIGH, MEDIUM, LOW, PRIORITY_WEIGHT, Intent
from .base import Scheduler

_INF = float("inf")


class DeadlineScheduler(Scheduler):
    """Earliest-deadline-first; tie-break on priority, then arrival order."""

    name = "deadline"

    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        if not runnable:
            return None
        return min(
            runnable,
            key=lambda i: (
                i.deadline_ts() if i.deadline_ts() is not None else _INF,
                -PRIORITY_WEIGHT.get(i.priority, 1),
                i.created_at,
                i.id,
            ),
        )
