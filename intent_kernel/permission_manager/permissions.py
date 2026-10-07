"""Intent-level security: least-privilege access control.

Each intent type declares which services it may access and how. The
Permission Manager returns ALLOW / DENY / ASK for every plan step,
creating an intent-level security boundary:

    Meeting Intent:  Calendar -> READ, Messaging -> WRITE, Passwords -> DENY
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

ALLOW = "ALLOW"
DENY = "DENY"
ASK = "ASK"  # not explicitly allowed; requires user confirmation

# Access modes a service capability may require.
READ = "READ"
WRITE = "WRITE"
USE = "USE"

# Per-intent-type policy: service -> set/list of permitted access modes.
DEFAULT_POLICIES: Dict[str, Dict[str, Any]] = {
    "prepare_meeting": {
        "calendar": {READ},
        "filesystem": {READ},
        "maps": {USE},
        "messaging": {WRITE},
        "reminder": {WRITE},
        "contacts": {READ},
    },
    "collect_meeting_files": {"calendar": {READ}, "filesystem": {READ, WRITE}},
    "get_schedule": {"calendar": {READ}},
    "send_message": {"messaging": {WRITE}, "contacts": {READ}},
    "download_files": {"filesystem": {WRITE, USE}},
    "set_reminder": {"reminder": {WRITE}, "calendar": {READ}},
    "submit_assignment": {"filesystem": {READ}, "messaging": {WRITE}},
    "find_file": {"filesystem": {READ}},
    "read_file": {"filesystem": {READ}},
    "summarize_document": {"filesystem": {READ}, "ai": {USE}},
    "organize_folder": {"filesystem": {READ, WRITE}},
    "backup_folder": {"filesystem": {READ, WRITE}},
    # Content generation: research is read-only, generation is a compute use,
    # and the only writes allowed are inside the workspace sandbox.
    "create_summary": {"web": {READ}, "ai": {USE}, "filesystem": {WRITE}},
    "research_topic": {
        "web": {READ}, "ai": {USE}, "filesystem": {WRITE}, "calendar": {READ},
    },
    "write_document": {"ai": {USE}, "filesystem": {WRITE}},
    "unknown": {},
}

# Resources that are never accessible to intents (hard security boundary).
PROTECTED_RESOURCES = {"passwords", "system_files", "kernel_internals"}


class PermissionManager:
    """Decides whether an intent may execute a given service capability."""

    def __init__(
        self,
        policies: Dict[str, Dict[str, Any]] = None,
        auto_grant_ask: bool = True,
        audit=None,
    ):
        self.policies = dict(DEFAULT_POLICIES)
        if policies:
            self.policies.update(policies)
        self.auto_grant_ask = auto_grant_ask
        self.audit = audit  # optional callable(intent_id, service, decision, reason)

    # ------------------------------------------------------------------
    def policy_for(self, intent_type: str) -> Dict[str, Any]:
        return self.policies.get(intent_type, {})

    def check(self, intent, service: str, required: str = USE) -> Tuple[str, str]:
        """Return (decision, reason) for service access with `required` mode."""
        if service in PROTECTED_RESOURCES:
            decision, reason = DENY, f"'{service}' is a protected resource"
        elif service == "intent_kernel":
            decision, reason = DENY, "intents cannot access the kernel itself"
        else:
            allowed = self.policy_for(intent.intent_type).get(service)
            if allowed is None:
                decision = ASK if self.auto_grant_ask else DENY
                reason = f"'{service}' is not in the '{intent.intent_type}' policy (default-deny)"
            elif required in allowed:
                decision, reason = ALLOW, f"'{service}' grants {required}"
            else:
                decision, reason = (
                    DENY,
                    f"'{service}' allows {sorted(allowed)}, not {required}",
                )
        if self.audit:
            self.audit(intent.id, service, decision, reason)
        return decision, reason

    def grant(self, intent_type: str, service: str, modes) -> None:
        """User-approved grant added to the policy (persistence is future work)."""
        modes = {modes} if isinstance(modes, str) else set(modes)
        self.policies.setdefault(intent_type, {}).setdefault(service, set()).update(modes)

    def revoke(self, intent_type: str, service: str) -> None:
        self.policies.get(intent_type, {}).pop(service, None)
