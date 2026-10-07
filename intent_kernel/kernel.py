"""The Intent Kernel.

Orchestrates the full intent lifecycle:

    User Input -> NLU -> Planner -> Intent Process -> Permission Check
      -> Resource Allocation -> Scheduling -> Service Execution
      -> Result Collection -> Completion / Recovery
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nlu.classifier import IntentClassifier
from nlu.entity_extractor import extract_entities, resolve_deadline
from planner.planner import Planner
from services import build_default_bus

from .db import IntentDatabase
from .intent import (
    COMPLETED,
    FAILED,
    HIGH,
    MEDIUM,
    NEW,
    READY,
    RECOVERY,
    RUNNING,
    STEP_BLOCKED,
    STEP_DONE,
    STEP_FAILED,
    STEP_PENDING,
    WAITING,
    Intent,
    InvalidTransition,
)
from .intent_file_manager import IntentFileManager
from .ipc.service_bus import ServiceBus
from .paths import ensure_storage_dirs
from .permission_manager import ASK, DENY, PermissionManager
from .recovery.checkpoint import CheckpointManager
from .resource_manager import ResourceManager
from .resource_manager.monitor import system_snapshot
from .scheduler import SCHEDULERS, get_scheduler


def build_bus(storage_root: Optional[Path] = None) -> ServiceBus:
    """Service bus with the prototype services (optionally sandboxed)."""
    if storage_root is None:
        return build_default_bus()
    from services import (
        AIService,
        CalendarService,
        FilesystemService,
        MapsService,
        MessagingService,
        ReminderService,
        WebService,
    )
    root = Path(storage_root)
    bus = ServiceBus()
    bus.register(CalendarService())
    bus.register(FilesystemService(
        documents_dir_path=root / "documents", downloads_dir_path=root / "downloads",
        workspace_dir_path=root / "workspace"))
    bus.register(MapsService())
    bus.register(MessagingService())
    bus.register(ReminderService(reminders_path_override=root / "reminders.json"))
    bus.register(WebService())
    bus.register(AIService(offline_only=True))
    return bus


# Capabilities whose successful result represents a file on disk.
ARTIFACT_CAPABILITIES = {"write_file", "download", "backup_folder"}


def _artifact_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise a service result into path-bearing artifact records."""
    records: List[Dict[str, Any]] = []
    if payload.get("display_path") and payload.get("bytes") is not None:
        records.append({
            "path": payload.get("path"),
            "display_path": payload.get("display_path"),
            "name": payload.get("name"),
            "bytes": payload.get("bytes"),
            "words": payload.get("words"),
            "format": payload.get("format"),
            "created": bool(payload.get("created")),
            "preview": payload.get("preview"),
            "kind": "file",
        })
    if payload.get("backup_path"):
        records.append({
            "path": payload.get("backup_path"),
            "display_path": payload.get("backup_path"),
            "name": Path(str(payload["backup_path"])).name,
            "bytes": payload.get("bytes"),
            "words": None,
            "format": "DIR",
            "created": True,
            "preview": None,
            "kind": "backup",
            "files": payload.get("files"),
        })
    return records


class IntentKernel:
    """Treats user goals as managed processes: schedule, authorize,
    allocate, execute, recover."""

    def __init__(
        self,
        strategy: str = "auto",
        bus: Optional[ServiceBus] = None,
        storage_root: Optional[Path] = None,
        persist: bool = True,
        auto_grant_ask: bool = True,
        latency: float = 0.0,
    ):
        ensure_storage_dirs()
        self.strategy = strategy
        self.scheduler = get_scheduler(strategy)
        self.bus = bus or build_bus(storage_root)
        if latency:
            for name in self.bus.service_names():
                self.bus.get(name).latency = latency
        self.permissions = PermissionManager(auto_grant_ask=auto_grant_ask)
        self.resources = ResourceManager()
        self.files = IntentFileManager()
        self.checkpoints = CheckpointManager(self.files)
        self.planner = Planner()
        self.classifier = IntentClassifier()
        self.db = IntentDatabase() if persist else None
        self.ready: List[Intent] = []
        self.intents: Dict[str, Intent] = {}
        self._ids = itertools.count(1024)
        self._context: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Submission pipeline
    # ------------------------------------------------------------------
    def submit_text(self, text, priority=None, deadline=None) -> Intent:
        """User Input -> NLU -> Planner -> Intent Process -> READY queue."""
        parsed = self.classifier.classify(text)
        intent_type = parsed["intent"]
        entities = extract_entities(text)
        intent = Intent(
            id=f"I{next(self._ids)}",
            goal=text,
            text=text,
            intent_type=intent_type,
            entities=entities,
            priority=priority or self.planner.default_priority(intent_type),
            deadline=deadline or resolve_deadline(entities),
            resource_requirements=self.resources.requirements_for(intent_type),
            plan=self.planner.create_plan(intent_type, entities),
        )
        intent.init_step_state()
        intent.transition(READY)
        intent.log(f"Classified as '{intent_type}' (confidence={parsed['confidence']})")
        self.files.initialize(intent)
        self.checkpoints.save(intent)
        self._context[intent.id] = {"entities": entities, "results": {}}
        self.intents[intent.id] = intent
        self.ready.append(intent)
        if self.db:
            self.db.upsert(intent)
        return intent

    def set_strategy(self, strategy: str) -> None:
        self.scheduler = get_scheduler(strategy)
        self.strategy = strategy

    def set_fault(self, service: str, count: int = 1) -> None:
        """Fault injection for the recovery demo/tests."""
        svc = self.bus.get(service)
        if svc is None:
            raise KeyError(f"unknown service '{service}'")
        svc.fail_next = count

    # ------------------------------------------------------------------
    # Scheduling / execution loop
    # ------------------------------------------------------------------
    def step_once(self) -> Optional[Intent]:
        """Pick the next intent (scheduler), execute ONE plan step.

        This step-level dispatch is what makes the schedulers comparable:
        Round Robin interleaves intents, FCFS/Priority/Deadline keep
        running the selected intent until it completes or blocks.
        """
        runnable = [i for i in self.ready if i.state == READY]
        intent = self.scheduler.select(runnable) if runnable else None
        if intent is None:
            return None
        intent.scheduled_at = time.time()
        step = intent.next_step()
        if step is None:
            self._finalize(intent)
            return intent
        self.execute_step(intent, step)
        if intent.state in (COMPLETED, FAILED):
            self._finalize(intent)
        return intent

    def run_all(self, max_steps: Optional[int] = None) -> int:
        """Drain the READY queue. Returns the number of steps executed."""
        steps = 0
        while True:
            acted = self.step_once()
            self._requeue_waiting()
            if acted is None:
                break
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break
        return steps

    def _requeue_waiting(self) -> None:
        """Promote WAITING intents when resources have become available."""
        for intent in list(self.ready):
            if intent.state == WAITING and self.resources.allocate(intent):
                intent.transition(READY)
                intent.log("Resources granted; WAITING -> READY")

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------
    def execute_step(self, intent: Intent, step: Dict[str, Any]) -> None:
        """Permission Check -> Resource Allocation -> Service Execution."""
        if intent.state == READY:
            intent.transition(RUNNING)
        if intent.started_at is None:
            intent.started_at = time.time()
            if not self.resources.allocate(intent):
                intent.transition(WAITING)
                intent.log("Resource allocation denied; intent is WAITING")
                return

        step_id = step["id"]
        intent.step_attempts[step_id] = intent.step_attempts.get(step_id, 0) + 1
        access = step.get("access", "USE")
        decision, reason = self.permissions.check(intent, step["service"], access)
        if decision == DENY:
            intent.step_state[step_id] = STEP_BLOCKED
            intent.blocked.append({
                "step": step_id,
                "service": step["service"],
                "capability": step["capability"],
                "decision": decision,
                "reason": reason,
            })
            intent.log(f"DENIED {step['service']}.{step['capability']}: {reason}")
        else:
            if decision == ASK:
                # Prototype: user confirms interactively; auto-grant + record.
                self.permissions.grant(intent.intent_type, step["service"], access)
                intent.log(f"GRANTED after user confirmation: {step['service']} ({access})")

            params = self._resolve_params(step, intent)
            intent.log(f"EXECUTE {step['service']}.{step['capability']} params={params}")
            result = self.bus.execute(step["service"], step["capability"], params, intent)
            if result.get("ok"):
                intent.step_results[step_id] = result
                intent.step_state[step_id] = STEP_DONE
                self._context[intent.id]["results"][step_id] = result.get("result")
                intent.log(f"DONE {step_id} in {result.get('elapsed_ms')} ms")
                self.checkpoints.save(intent)
            else:
                intent.log(f"FAILED {step_id}: {result.get('error')}")
                action = self.checkpoints.record_failure(intent, step, result.get("error"))
                if action == "abort":
                    self.resources.release(intent.id)

        # Yield the CPU back to the scheduler after every step
        if intent.state == RUNNING:
            intent.transition(READY)

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------
    def _finalize(self, intent: Intent) -> None:
        if intent.state == READY:
            intent.transition(RUNNING)
        intent.completed_at = intent.completed_at or time.time()
        if intent.is_complete() and intent.state != FAILED:
            intent.transition(COMPLETED)
        elif intent.state == RUNNING:
            intent.transition(FAILED)
        self.resources.release(intent.id)
        intent.log(f"FINAL state: {intent.state}")
        if intent in self.ready:
            self.ready.remove(intent)
        self.files.write_all(intent)
        self.files.log(intent.id, f"Intent finalized: {intent.state}")
        if self.db:
            self.db.upsert(intent)

    # ------------------------------------------------------------------
    # Parameter resolution (data flow between steps)
    # ------------------------------------------------------------------
    def _resolve_params(self, step: Dict[str, Any], intent: Intent) -> Dict[str, Any]:
        results = self._context.get(intent.id, {}).get("results", {})
        return {
            key: self._resolve_value(value, intent, results)
            for key, value in (step.get("params") or {}).items()
        }

    def _resolve_value(self, value: Any, intent: Intent, results: Dict[str, Any]) -> Any:
        if not isinstance(value, str) or not value.startswith("@"):
            return value
        token = value[1:]
        if token == "summary":
            return self._compose_summary(intent, results)
        if token.startswith("entities."):
            return intent.entities.get(token.split(".", 1)[1])
        if token.startswith("result."):
            parts = token.split(".", 2)  # ["result", "<sid>", "<key>"...]
            node = results.get(parts[1])
            for part in parts[2:]:
                if isinstance(node, dict):
                    node = node.get(part)
                else:
                    return None
            return node
        return None

    @staticmethod
    def _compose_summary(intent: Intent, results: Dict[str, Any]) -> str:
        """Aggregate prior step results into a human summary string."""
        parts: List[str] = []
        for payload in results.values():
            if not isinstance(payload, dict):
                continue
            if "title" in payload:
                parts.append(
                    f"Meeting '{payload['title']}' at {payload.get('time', '?')} "
                    f"in {payload.get('location', '?')}"
                )
            if "documents" in payload:
                parts.append(f"{payload.get('count', len(payload['documents']))} related document(s) found")
            if "travel_time_minutes" in payload:
                parts.append(f"~{payload['travel_time_minutes']} min travel estimated")
            if payload.get("status") == "queued":
                parts.append("notification queued")
            if "reminder_id" in payload:
                parts.append(f"reminder {payload['reminder_id']} scheduled")
        return "; ".join(parts) or "no details yet"

    # ------------------------------------------------------------------
    # Result collection: user-facing summary
    # ------------------------------------------------------------------
    def result_summary(self, intent: Intent) -> List[str]:
        lines: List[str] = []
        for step in intent.plan:
            state = intent.step_state.get(step["id"], STEP_PENDING)
            payload = (intent.step_results.get(step["id"]) or {}).get("result")
            if state == STEP_DONE and isinstance(payload, dict):
                if "title" in payload:
                    lines.append(f"Meeting : {payload['title']}")
                    lines.append(f"Time    : {payload.get('time', '?')}")
                    lines.append(f"Location: {payload.get('location', '?')}")
                if "documents" in payload and "count" in payload:
                    lines.append(f"Documents: {payload.get('count', 0)} related file(s) found")
                if "travel_time_minutes" in payload:
                    lines.append(f"Travel  : {payload['travel_time_minutes']} minutes ({payload.get('destination', '')})")
                if payload.get("status") == "queued":
                    lines.append(f"Notification: queued to {payload.get('recipient', 'user@local')}")
                if "reminder_id" in payload:
                    lines.append(f"Reminder: {payload['reminder_id']} at {payload.get('time', '?')}")
                if "events" in payload:
                    lines.append(f"Schedule: {payload.get('count', len(payload['events']))} event(s) today")
                if "message_id" in payload:
                    lines.append(f"Message : sent to {payload.get('recipient', '?')} ({payload['message_id']})")
                if "downloaded" in payload:
                    lines.append(f"Downloads: {payload.get('count', 0)} file(s) -> {payload.get('destination', '')}")
                if "matches" in payload:
                    lines.append(f"Search: {payload.get('count', 0)} match(es) for '{payload.get('keyword', '')}' in {payload.get('root', '')}")
                    for m in payload["matches"][:5]:
                        lines.append(f"    - {m['name']} ({m['size']} bytes)")
                if "content" in payload:
                    if payload.get("binary"):
                        lines.append(f"File: {payload.get('name')} ({payload.get('size')} bytes, binary)")
                    else:
                        lines.append(f"File: {payload.get('name')} ({payload.get('size')} bytes, {payload.get('lines')} lines)")
                        lines.append(f"Preview: {str(payload.get('preview', ''))[:150].replace(chr(10), ' ')}")
                if "moved" in payload:
                    cats = ", ".join(payload.get("folders", []))
                    lines.append(f"Organized: {payload.get('count', 0)} file(s) moved into {cats}")
                if "backup_path" in payload:
                    lines.append(f"Backup: {payload.get('files', 0)} file(s) -> {payload.get('backup_path', '')}")
# --- content generation: research -> AI -> file -------------
                if "top_title" in payload and "results" in payload:
                    providers = ", ".join(payload.get("providers", [])) or "web"
                    lines.append(
                        f"Research: {payload.get('count', 0)} result(s) for "
                        f"'{payload.get('query', '')}' via {providers}"
                    )
                    lines.append(f"Top hit : {payload['top_title']}")
                if "pages" in payload:
                    lines.append(f"Sources : {payload.get('count', 0)} article extract(s) fetched")
                    for page in payload["pages"][:3]:
                        lines.append(
                            f"    - {page.get('title', '?')} ({page.get('words', 0)} words)"
                        )
                if "summary" in payload and "bullets" in payload:
                    lines.append(
                        f"AI brief: {payload.get('words', 0)} words "
                        f"(provider: {payload.get('provider', 'extractive')})"
                    )
                    for bullet in payload["bullets"][:4]:
                        lines.append(f"    - {str(bullet)[:110]}")
                if "document" in payload and "filename" in payload:
                    lines.append(
                        f"Document: {payload['filename']} "
                        f"({payload.get('words', 0)} words, {payload.get('sections', 0)} sections)"
                    )
                if "display_path" in payload and "bytes" in payload:
                    verb = "Created" if payload.get("created") else "Updated"
                    lines.append(f"{verb} file : {payload['display_path']}")
                    lines.append(
                        f"          {payload.get('bytes', 0)} bytes, "
                        f"{payload.get('words', 0)} words, {payload.get('format', 'TXT')}"
                    )
                if payload.get("opened") and "path" in payload:
                    lines.append(f"Opened  : {payload['path']}")
            elif state == STEP_BLOCKED:
                lines.append(f"{step['description']}: BLOCKED by permission manager")
            elif state == STEP_FAILED:
                lines.append(f"{step['description']}: FAILED ({intent.last_error})")
        return lines or ["Intent produced no result details."]

    # ------------------------------------------------------------------
    # Artifacts: files the intents actually produced on disk
    # ------------------------------------------------------------------
    def artifacts(self, intent: Intent) -> List[Dict[str, Any]]:
        """Files written by this intent, newest first."""
        found: List[Dict[str, Any]] = []
        for step in intent.plan:
            if step.get("capability") not in ARTIFACT_CAPABILITIES:
                continue
            if intent.step_state.get(step["id"]) != STEP_DONE:
                continue
            payload = (intent.step_results.get(step["id"]) or {}).get("result")
            if not isinstance(payload, dict):
                continue
            for record in _artifact_records(payload):
                record["intent_id"] = intent.id
                record["goal"] = intent.goal
                record["step"] = step["id"]
                record["capability"] = step["capability"]
                found.append(record)
        return list(reversed(found))

    def all_artifacts(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Artifacts across every intent (the Artifacts panel of the UI)."""
        out: List[Dict[str, Any]] = []
        for intent in sorted(self.intents.values(), key=lambda i: i.id, reverse=True):
            out.extend(self.artifacts(intent))
        return out[:limit]

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    def metrics(self) -> Dict[str, Any]:
        all_intents = list(self.intents.values())
        completed = [i for i in all_intents if i.state == COMPLETED]
        failed = [i for i in all_intents if i.state == FAILED]
        retries = 0
        for intent in all_intents:
            retries += sum(max(0, a - 1) for a in intent.step_attempts.values())
        avg_wait = (
            round(sum(i.waiting_time() for i in all_intents) / len(all_intents), 4)
            if all_intents else 0.0
        )
        avg_turn = (
            round(sum(i.turnaround_time() for i in completed) / len(completed), 4)
            if completed else 0.0
        )
        return {
            "strategy": self.strategy,
            "submitted": len(all_intents),
            "completed": len(completed),
            "failed": len(failed),
            "avg_waiting_time": avg_wait,
            "avg_turnaround_time": avg_turn,
            "deadline_misses": sum(1 for i in all_intents if i.deadline_missed()),
            "steps_executed": sum(
                1 for i in all_intents for s in i.step_state.values() if s == STEP_DONE
            ),
            "retries": retries,
            "blocked_steps": sum(len(i.blocked) for i in all_intents),
        }

    def status(self) -> Dict[str, Any]:
        ordered = sorted(self.intents.values(), key=lambda i: i.id)
        scheduler = self.scheduler
        auto_policy = getattr(scheduler, "last_policy", None)
        auto_reason = getattr(scheduler, "last_reason", None)
        return {
            "strategy": self.strategy,
            "scheduler_policy": auto_policy,
            "scheduler_reason": auto_reason,
            "scheduler_policy_counts": (
                scheduler.policy_counts()
                if hasattr(scheduler, "policy_counts") else {}
            ),
            "ready_queue": [i.id for i in self.ready],
            "intents": [i.to_dict() for i in ordered],
            "artifacts": self.all_artifacts(limit=20),
            "services": self.bus.registry(),
            "resources": self.resources.usage(),
            "system": system_snapshot(),
            "metrics": self.metrics(),
        }
