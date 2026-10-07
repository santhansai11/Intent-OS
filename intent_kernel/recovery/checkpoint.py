"""Checkpointing and failure recovery.

Instead of restarting a whole intent when one service fails, completed
steps are checkpointed after every step. Recovery resumes from the
failed step:

    Step 1 -> DONE        Step 1 -> DONE (from checkpoint)
    Step 2 -> DONE   =>   Step 2 -> DONE (from checkpoint)
    Step 3 -> DONE        Step 3 -> DONE (from checkpoint)
    Step 4 -> FAILED      Step 4 -> retry up to max_retries
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict

from ..intent import (
    FAILED,
    READY,
    RECOVERY,
    STEP_DONE,
    STEP_FAILED,
    STEP_PENDING,
    Intent,
)


class CheckpointManager:
    """Persists per-step state so failed intents resume where they stopped."""

    def __init__(self, file_manager=None):
        self.files = file_manager  # optional IntentFileManager for disk persistence

    # ------------------------------------------------------------------
    def save(self, intent: Intent) -> Dict[str, Any]:
        snapshot = {
            "intent_id": intent.id,
            "state": intent.state,
            "step_state": dict(intent.step_state),
            "step_attempts": dict(intent.step_attempts),
            "saved_at": time.time(),
        }
        if self.files is not None:
            self.files.write_json(intent.id, "checkpoint.json", snapshot)
        return snapshot

    def load(self, intent_id: str) -> Dict[str, Any]:
        if self.files is None:
            return {}
        return self.files.read_json(intent_id, "checkpoint.json") or {}

    # ------------------------------------------------------------------
    def record_failure(self, intent: Intent, step: Dict[str, Any], error: str) -> str:
        """Handle a failed step. Returns 'retry' or 'abort'.

        retry: intent goes RUNNING -> RECOVERY -> READY, resuming at this step.
        abort: retries exhausted; intent is FAILED (checkpoints preserved).
        """
        step_id = step["id"]
        attempts = intent.step_attempts.get(step_id, 0)
        if attempts <= intent.max_retries:
            intent.log(f"RECOVERY: '{step_id}' failed ({error}); retry {attempts}/{intent.max_retries}")
            intent.transition(RECOVERY)
            self.save(intent)
            intent.transition(READY)
            return "retry"
        intent.step_state[step_id] = STEP_FAILED
        intent.last_error = error
        intent.log(f"ABORT: '{step_id}' failed after {attempts} attempts: {error}")
        intent.transition(FAILED)
        self.save(intent)
        return "abort"

    # ------------------------------------------------------------------
    def resume_info(self, intent: Intent) -> Dict[str, Any]:
        """Summary of what a recovering intent will re-execute."""
        nxt = intent.next_step()
        return {
            "intent_id": intent.id,
            "attempts": dict(intent.step_attempts),
            "next_step": nxt["id"] if nxt else None,
            "completed_steps": [
                sid for sid, st in intent.step_state.items() if st == STEP_DONE
            ],
        }
