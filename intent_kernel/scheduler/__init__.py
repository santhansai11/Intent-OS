"""Scheduler package.

Multiple scheduling strategies can be plugged into the Intent Kernel:
Automatic, FCFS, Priority, Round Robin and Deadline-aware (EDF).

`auto` is the default: it inspects the runnable set and adopts the policy
that fits the workload, so users never choose an algorithm themselves.
The explicit policies stay available for the evaluation/comparison study.
"""
from __future__ import annotations

from .base import Scheduler, SchedulerError
from .auto import AutoScheduler
from .fcfs import FCFSScheduler
from .priority import PriorityScheduler
from .round_robin import RoundRobinScheduler
from .deadline import DeadlineScheduler

SCHEDULERS = {
    "auto": AutoScheduler,
    "fcfs": FCFSScheduler,
    "priority": PriorityScheduler,
    "round_robin": RoundRobinScheduler,
    "deadline": DeadlineScheduler,
}


def get_scheduler(name: str):
    """Return a scheduler instance by name (raises KeyError on unknown)."""
    try:
        return SCHEDULERS[name]()
    except KeyError:
        raise KeyError(f"Unknown scheduler '{name}'. Available: {sorted(SCHEDULERS)}")

