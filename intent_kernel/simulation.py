"""Scheduler comparison simulation (evaluation).

Runs the same synthetic workload through FCFS, Priority, Round Robin
and Deadline-aware scheduling on a single simulated resource, and
reports: completion order, average waiting time, average turnaround
time and deadline misses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .intent import HIGH, LOW, MEDIUM, PRIORITY_WEIGHT

INF = float("inf")


@dataclass
class SimTask:
    name: str
    priority: str = MEDIUM
    cost: int = 1                  # execution units required
    deadline: Optional[int] = None # absolute completion deadline (units)
    arrival: int = 0               # arrival time (units)


@dataclass
class SimResult:
    strategy: str
    order: List[str] = field(default_factory=list)     # completion order
    starts: Dict[str, int] = field(default_factory=dict)
    finishes: Dict[str, int] = field(default_factory=dict)
    avg_waiting: float = 0.0
    avg_turnaround: float = 0.0
    deadline_misses: int = 0

    def as_dict(self) -> Dict:
        return {
            "strategy": self.strategy,
            "completion_order": self.order,
            "avg_waiting": round(self.avg_waiting, 2),
            "avg_turnaround": round(self.avg_turnaround, 2),
            "deadline_misses": self.deadline_misses,
        }


# ---------------------------------------------------------------------------
def _pick(strategy: str, ready: List[SimTask], last_run: Dict[str, int]) -> SimTask:
    if strategy == "fcfs":
        return min(ready, key=lambda t: (t.arrival, t.name))
    if strategy == "priority":
        return min(ready, key=lambda t: (-PRIORITY_WEIGHT.get(t.priority, 1), t.arrival, t.name))
    if strategy == "deadline":
        return min(ready, key=lambda t: (
            t.deadline if t.deadline is not None else INF,
            -PRIORITY_WEIGHT.get(t.priority, 1),
            t.arrival, t.name,
        ))
    if strategy == "round_robin":
        return min(ready, key=lambda t: (last_run.get(t.name, -1), t.name))
    raise ValueError(f"unknown strategy '{strategy}'")


def simulate(strategy: str, tasks: List[SimTask], quantum: int = 2) -> SimResult:
    """Discrete-event simulation on one resource.

    FCFS / Priority / Deadline run non-preemptively; Round Robin
    preempts every `quantum` units (true round-robin rotation).
    """
    pending = sorted(tasks, key=lambda t: (t.arrival, t.name))
    ready: List[SimTask] = []
    result = SimResult(strategy=strategy)
    remaining: Dict[str, int] = {t.name: t.cost for t in tasks}
    last_run: Dict[str, int] = {}
    t = 0
    current: Optional[SimTask] = None
    slice_left = 0

    while pending or ready or current:
        while pending and pending[0].arrival <= t:
            ready.append(pending.pop(0))
        if current is None:
            if not ready:
                if pending:
                    t = max(t, pending[0].arrival)
                    continue
                break
            current = _pick(strategy, ready, last_run)
            ready.remove(current)
            result.starts.setdefault(current.name, t)
            slice_left = quantum if strategy == "round_robin" else 10 ** 9

        remaining[current.name] -= 1
        t += 1
        slice_left -= 1
        last_run[current.name] = t

        while pending and pending[0].arrival <= t:
            ready.append(pending.pop(0))

        if remaining[current.name] <= 0:
            result.finishes[current.name] = t
            result.order.append(current.name)
            current = None
        elif slice_left <= 0:
            ready.append(current)
            current = None

    by_name = {task.name: task for task in tasks}
    waits = [result.starts[name] - by_name[name].arrival for name in by_name]
    turns = [result.finishes[name] - by_name[name].arrival for name in by_name]
    n = len(tasks)
    result.avg_waiting = sum(waits) / n if n else 0.0
    result.avg_turnaround = sum(turns) / n if n else 0.0
    result.deadline_misses = sum(
        1 for task in tasks
        if task.deadline is not None and result.finishes.get(task.name, INF) > task.deadline
    )
    return result


DEFAULT_WORKLOAD: List[SimTask] = [
    SimTask("Prepare Meeting", priority=HIGH, cost=5, deadline=16),
    SimTask("Submit Assignment", priority=HIGH, cost=8, deadline=23),
    SimTask("Send Message", priority=MEDIUM, cost=3, deadline=12),
    SimTask("Set Reminder", priority=MEDIUM, cost=2, deadline=6),
    SimTask("Download Videos", priority=LOW, cost=10, deadline=None),
]


def compare_strategies(tasks: List[SimTask] = None, quantum: int = 2) -> List[Dict]:
    tasks = tasks or DEFAULT_WORKLOAD
    return [simulate(s, tasks, quantum).as_dict() for s in
            ("fcfs", "priority", "round_robin", "deadline")]
