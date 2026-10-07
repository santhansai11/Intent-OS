"""Intent lifecycle state machine.

    NEW -> READY -> RUNNING -> COMPLETED
                  |          |-> WAITING -> RUNNING/READY
                  |          |-> RECOVERY -> READY (retry) / FAILED
                  |          |-> FAILED -> RECOVERY / READY
"""
from __future__ import annotations

from typing import Iterable

from .intent import (
    COMPLETED,
    FAILED,
    NEW,
    READY,
    RECOVERY,
    RUNNING,
    VALID_TRANSITIONS,
    WAITING,
    Intent,
    InvalidTransition,
)

STATE_DESCRIPTIONS = {
    NEW: "Intent created, not yet schedulable",
    READY: "Waiting in the scheduler queue",
    RUNNING: "Currently executing a plan step",
    WAITING: "Blocked on a resource or external condition",
    RECOVERY: "A step failed; retrying from the last checkpoint",
    COMPLETED: "All plan steps finished successfully",
    FAILED: "Intent exhausted its retries",
}

TERMINAL_STATES = {COMPLETED, FAILED}


def can_transition(intent: Intent, new_state: str) -> bool:
    return new_state in VALID_TRANSITIONS[intent.state]


def transition(intent: Intent, new_state: str) -> None:
    """Validate + apply a lifecycle transition (raises InvalidTransition)."""
    intent.transition(new_state)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def describe(state: str) -> str:
    return STATE_DESCRIPTIONS.get(state, "Unknown state")


def active_states() -> Iterable[str]:
    return (NEW, READY, RUNNING, WAITING, RECOVERY)
