"""Automatic scheduling policy selection.

The user should never have to pick a scheduling algorithm: asking a person
to choose FCFS vs EDF is an implementation detail leaking into the
interface. `AutoScheduler` inspects the runnable set and adopts whichever
classical policy fits the current workload, then explains why.

Decision order (first match wins):

1. **Aging** -- if an intent has been waiting longer than `starvation_window`
   seconds, run it next. Prevents indefinite starvation under priority/EDF.
2. **Deadline (EDF)** -- if any runnable intent has a deadline inside
   `deadline_horizon` seconds, earliest-deadline-first minimises misses.
3. **Priority** -- if priorities are mixed (spread >= 2 weight levels),
   respect the user-declared importance.
4. **Round Robin** -- if 3+ intents of similar importance compete, interleave
   them for fairness and responsiveness.
5. **FCFS** -- otherwise there is nothing to optimise; keep arrival order.

The manager policies remain pluggable (run_intentos.py --scheduler,
/api/strategy, /api/simulation) because the project compares them; `auto`
is simply the sane default for real users.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from ..intent import PRIORITY_WEIGHT, Intent
from .base import Scheduler
from .deadline import DeadlineScheduler
from .fcfs import FCFSScheduler
from .priority import PriorityScheduler
from .round_robin import RoundRobinScheduler


class AutoScheduler(Scheduler):
    """Adaptive scheduler: chooses FCFS / Priority / Round Robin / EDF per workload."""

    name = "auto"

    def __init__(self, deadline_horizon: float = 43200.0,
                 starvation_window: float = 20.0,
                 fairness_threshold: int = 3):
        self.deadline_horizon = deadline_horizon      # 12h horizon -> EDF
        self.starvation_window = starvation_window    # aging threshold (s)
        self.fairness_threshold = fairness_threshold  # 3+ peers -> RR
        self._impl: Dict[str, Scheduler] = {
            "fcfs": FCFSScheduler(),
            "priority": PriorityScheduler(),
            "round_robin": RoundRobinScheduler(),
            "deadline": DeadlineScheduler(),
        }
        self.last_policy = "fcfs"
        self.last_reason = "no runnable intents"
        self.decisions: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    def decide(self, runnable: List[Intent]) -> tuple:
        """Return (policy_name, human_reason) for this workload snapshot."""
        now = time.time()

        # 1. Aging: nobody may starve.
        starved = [
            i for i in runnable
            if (now - (i.created_at or now)) > self.starvation_window
        ]
        if starved:
            victim = min(starved, key=lambda i: (i.created_at, i.id))
            return "fcfs", (
                f"aging: intent {victim.id} waited "
                f"{now - (victim.created_at or now):.0f}s - running it to prevent starvation"
            )

        # 2. Deadlines: minimise misses when a deadline is near.
        dated = [i for i in runnable if i.deadline_ts() is not None]
        if dated:
            due = min(i.deadline_ts() for i in dated)
            if due - now <= self.deadline_horizon:
                return "deadline", (
                    f"{len(dated)} intent(s) with deadlines, nearest in "
                    f"{max(0.0, due - now) / 60:.0f} min - earliest-deadline-first"
                )

        # 3. Priority spread: honour explicit importance.
        weights = {PRIORITY_WEIGHT.get(i.priority, 1) for i in runnable}
        if max(weights) - min(weights) >= 2:
            top = max(runnable, key=lambda i: PRIORITY_WEIGHT.get(i.priority, 1))
            return "priority", (
                f"mixed priorities (HIGH..LOW) - running {top.priority} intent {top.id} first"
            )

        # 4. Fairness: several equally important intents -> interleave.
        if len(runnable) >= self.fairness_threshold:
            return "round_robin", (
                f"{len(runnable)} equally important intents - round robin for fairness"
            )

        # 5. Nothing to optimise.
        first = min(runnable, key=lambda i: (i.created_at, i.id))
        return "fcfs", f"{len(runnable)} intent(s), same priority, no deadline - arrival order"

    # ------------------------------------------------------------------
    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        if not runnable:
            return None
        policy, reason = self.decide(runnable)
        self.last_policy = policy
        self.last_reason = reason
        self.decisions.append({"policy": policy, "reason": reason})
        del self.decisions[:-50]  # keep the log bounded
        return self._impl[policy].select(runnable)

    # ------------------------------------------------------------------
    def policy_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.decisions:
            counts[entry["policy"]] = counts.get(entry["policy"], 0) + 1
        return counts

    def describe(self) -> str:
        return (
            "Automatic policy selection (aging -> EDF -> priority -> round robin -> FCFS); "
            f"last: {self.last_policy} ({self.last_reason})"
        )
