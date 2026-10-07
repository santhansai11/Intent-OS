"""Intent process representation.

An Intent is the unit of execution and resource management in IntentOS,
analogous to a process in a traditional operating system. It carries a
goal, priority, deadline, resource requirements, an execution plan,
per-step state (checkpoints) and collected results.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Priorities
# ---------------------------------------------------------------------------
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
PRIORITY_WEIGHT = {HIGH: 3, MEDIUM: 2, LOW: 1}

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------
NEW = "NEW"
READY = "READY"
RUNNING = "RUNNING"
WAITING = "WAITING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
RECOVERY = "RECOVERY"

VALID_TRANSITIONS = {
    NEW: {READY, FAILED},
    READY: {RUNNING},
    RUNNING: {WAITING, COMPLETED, FAILED, RECOVERY, READY},
    WAITING: {RUNNING, READY, FAILED},
    RECOVERY: {READY, RUNNING, FAILED},
    FAILED: {RECOVERY, READY},
    COMPLETED: set(),
}

# ---------------------------------------------------------------------------
# Per-step states (checkpoints)
# ---------------------------------------------------------------------------
STEP_PENDING = "PENDING"
STEP_DONE = "DONE"
STEP_FAILED = "STEP_FAILED"
STEP_BLOCKED = "BLOCKED"


class InvalidTransition(Exception):
    """Raised when a lifecycle transition is not allowed."""


@dataclass
class Intent:
    """A user goal represented as a managed OS-level execution entity."""

    goal: str
    text: str = ""
    id: str = "I0"
    intent_type: str = "unknown"
    entities: Dict[str, Any] = field(default_factory=dict)
    priority: str = MEDIUM
    deadline: Optional[datetime] = None
    resource_requirements: Dict[str, Any] = field(default_factory=dict)
    plan: List[Dict[str, Any]] = field(default_factory=list)
    state: str = NEW
    step_state: Dict[str, str] = field(default_factory=dict)
    step_attempts: Dict[str, int] = field(default_factory=dict)
    step_results: Dict[str, Any] = field(default_factory=dict)
    blocked: List[Dict[str, Any]] = field(default_factory=list)
    execution_log: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    scheduled_at: Optional[float] = None  # last dispatch time (RR fairness)
    last_error: Optional[str] = None
    max_retries: int = 2

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def transition(self, new_state: str) -> None:
        allowed = VALID_TRANSITIONS[self.state]
        if new_state not in allowed:
            raise InvalidTransition(
                f"Intent {self.id}: illegal transition {self.state} -> {new_state}"
            )
        self.state = new_state

    # ------------------------------------------------------------------
    # Plan / step helpers
    # ------------------------------------------------------------------
    def init_step_state(self) -> None:
        for step in self.plan:
            self.step_state.setdefault(step["id"], STEP_PENDING)
            self.step_attempts.setdefault(step["id"], 0)

    def next_step(self) -> Optional[Dict[str, Any]]:
        """First pending step (None when every step is DONE/BLOCKED/FAILED)."""
        for step in self.plan:
            if self.step_state.get(step["id"]) == STEP_PENDING:
                return step
        return None

    def is_complete(self) -> bool:
        return all(
            self.step_state.get(s["id"]) in (STEP_DONE, STEP_BLOCKED, STEP_FAILED)
            for s in self.plan
        )

    def progress(self) -> Dict[str, int]:
        counts = {STEP_PENDING: 0, STEP_DONE: 0, STEP_FAILED: 0, STEP_BLOCKED: 0}
        for s in self.plan:
            counts[self.step_state.get(s["id"], STEP_PENDING)] += 1
        return counts

    def log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.execution_log.append(f"[{stamp}] {line}")

    # ------------------------------------------------------------------
    # Scheduling metrics
    # ------------------------------------------------------------------
    def deadline_ts(self) -> Optional[float]:
        return self.deadline.timestamp() if self.deadline else None

    def waiting_time(self) -> float:
        return max(0.0, (self.started_at or time.time()) - self.created_at)

    def turnaround_time(self) -> float:
        end = self.completed_at or time.time()
        return max(0.0, end - self.created_at)

    def deadline_missed(self) -> bool:
        dl = self.deadline_ts()
        end = self.completed_at
        return bool(dl and end and end > dl)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self, include_log: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "goal": self.goal,
            "text": self.text,
            "intent_type": self.intent_type,
            "entities": self.entities,
            "priority": self.priority,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "state": self.state,
            "plan": self.plan,
            "step_state": self.step_state,
            "step_attempts": self.step_attempts,
            "step_results": self.step_results,
            "blocked": self.blocked,
            "progress": self.progress(),
            "resource_requirements": self.resource_requirements,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "waiting_time": round(self.waiting_time(), 3),
            "turnaround_time": round(self.turnaround_time(), 3),
            "deadline_missed": self.deadline_missed(),
        }
        if include_log:
            data["execution_log"] = self.execution_log
        return data

    def describe(self) -> str:
        """Human-readable one-screen summary used by the CLI."""
        lines = [
            f"Intent {self.id}  [{self.intent_type}]  state={self.state}",
            f"  Goal      : {self.goal}",
            f"  Priority  : {self.priority}",
            f"  Deadline  : {self.deadline.strftime('%H:%M') if self.deadline else 'None'}",
            f"  Resources : {self.resource_requirements}",
        ]
        for step in self.plan:
            marker = {
                STEP_DONE: "OK  ",
                STEP_BLOCKED: "DENY",
                STEP_FAILED: "FAIL",
            }.get(self.step_state.get(step["id"], STEP_PENDING), " ..  ")
            lines.append(f"  {marker} {step['id']} {step['service']}.{step['capability']}")
        if self.last_error:
            lines.append(f"  Error     : {self.last_error}")
        return "\n".join(lines)
