"""Round Robin scheduling.

Each intent receives a fair share of dispatch decisions. The scheduler
keeps its own rotation state: after an intent consumes its quantum it
goes to the back of the rotation.
"""
from __future__ import annotations

import itertools
from typing import List, Optional

from ..intent import Intent
from .base import Scheduler


class RoundRobinScheduler(Scheduler):
    """Rotate execution across all READY intents (quantum = 1 step)."""

    name = "round_robin"

    def __init__(self, quantum: int = 1):
        if quantum < 1:
            raise ValueError("quantum must be >= 1")
        self.quantum = quantum
        self._runs_left: dict = {}
        self._last_served: dict = {}
        self._clock = itertools.count()

    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        if not runnable:
            return None
        # Prefer an intent with remaining quantum; otherwise least-recently run.
        for intent in runnable:
            if self._runs_left.get(intent.id, 0) > 0:
                self._runs_left[intent.id] -= 1
                return intent
        nxt = min(
            runnable,
            key=lambda i: (self._last_served.get(i.id, -1), i.id),
        )
        self._last_served[nxt.id] = next(self._clock)
        self._runs_left[nxt.id] = self.quantum - 1
        return nxt
