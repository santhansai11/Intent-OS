"""Intent-level resource management.

Every intent declares resource requirements (CPU, memory, network,
services, files). The Resource Manager grants allocations only when
capacity is available; otherwise the intent stays WAITING -- mirroring
how an OS refuses to overcommit RAM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..intent import Intent

# Capacity of the (simulated) machine the kernel manages.
DEFAULT_CAPACITY: Dict[str, float] = {
    "cpu_percent": 100.0,
    "memory_mb": 8192.0,
    "network_mbps": 100.0,
}

# Default resource requirement per intent type (unit: same keys as capacity).
REQUIREMENT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "prepare_meeting": {
        "cpu_percent": 15.0,
        "memory_mb": 256.0,
        "network_mbps": 10.0,
        "services": ["calendar", "filesystem", "maps", "messaging", "reminder"],
    },
    "collect_meeting_files": {
        "cpu_percent": 8.0, "memory_mb": 128.0, "network_mbps": 0.0,
        "services": ["calendar", "filesystem"],
    },
    "get_schedule": {
        "cpu_percent": 5.0,
        "memory_mb": 64.0,
        "network_mbps": 0.0,
        "services": ["calendar"],
    },
    "send_message": {
        "cpu_percent": 5.0,
        "memory_mb": 64.0,
        "network_mbps": 5.0,
        "services": ["messaging"],
    },
    "download_files": {
        "cpu_percent": 10.0,
        "memory_mb": 128.0,
        "network_mbps": 50.0,
        "services": ["filesystem"],
    },
    "set_reminder": {
        "cpu_percent": 2.0,
        "memory_mb": 32.0,
        "network_mbps": 0.0,
        "services": ["reminder"],
    },
    "submit_assignment": {
        "cpu_percent": 8.0,
        "memory_mb": 128.0,
        "network_mbps": 10.0,
        "services": ["filesystem", "messaging"],
    },
    "find_file": {
        "cpu_percent": 3.0,
        "memory_mb": 32.0,
        "network_mbps": 0.0,
        "services": ["filesystem"],
    },
    "read_file": {
        "cpu_percent": 2.0,
        "memory_mb": 32.0,
        "network_mbps": 0.0,
        "services": ["filesystem"],
    },
    "summarize_document": {
        "cpu_percent": 8.0, "memory_mb": 160.0, "network_mbps": 0.0,
        "services": ["filesystem", "ai"],
    },
    "organize_folder": {
        "cpu_percent": 8.0,
        "memory_mb": 64.0,
        "network_mbps": 0.0,
        "services": ["filesystem"],
    },
    "backup_folder": {
        "cpu_percent": 10.0,
        "memory_mb": 128.0,
        "network_mbps": 0.0,
        "services": ["filesystem"],
    },
    "unknown": {
        "cpu_percent": 5.0,
        "memory_mb": 64.0,
        "network_mbps": 0.0,
        "services": [],
    },
    # Network-bound and model-bound work: heavy on network + memory.
    "create_summary": {
        "cpu_percent": 12.0,
        "memory_mb": 256.0,
        "network_mbps": 25.0,
        "services": ["web", "ai", "filesystem"],
    },
    "research_topic": {
        "cpu_percent": 15.0,
        "memory_mb": 320.0,
        "network_mbps": 35.0,
        "services": ["web", "ai", "filesystem"],
    },
    "write_document": {
        "cpu_percent": 10.0,
        "memory_mb": 256.0,
        "network_mbps": 5.0,
        "services": ["ai", "filesystem"],
    },
}


class ResourceManager:
    """Tracks per-intent allocations against a fixed capacity budget."""

    def __init__(self, capacity: Optional[Dict[str, float]] = None):
        self.capacity: Dict[str, float] = dict(DEFAULT_CAPACITY)
        if capacity:
            self.capacity.update(capacity)
        self.allocations: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    def requirements_for(self, intent_type: str) -> Dict[str, Any]:
        template = REQUIREMENT_TEMPLATES.get(intent_type, REQUIREMENT_TEMPLATES["unknown"])
        return dict(template)

    def fits(self, requirements: Dict[str, Any], reserved: Optional[Dict[str, Any]] = None) -> bool:
        used = self._used(required_keys=requirements, exclude=None)
        extra = reserved or {}
        for key in ("cpu_percent", "memory_mb", "network_mbps"):
            need = float(requirements.get(key, 0.0)) + float(extra.get(key, 0.0))
            if used.get(key, 0.0) + need > self.capacity[key]:
                return False
        return True

    def allocate(self, intent: Intent) -> bool:
        """Grant resources to an intent. Returns False when capacity is short."""
        req = intent.resource_requirements or self.requirements_for(intent.intent_type)
        if intent.id in self.allocations:
            return True  # already holding
        if not self.fits(req):
            return False
        self.allocations[intent.id] = dict(req)
        return True

    def release(self, intent_id: str) -> None:
        self.allocations.pop(intent_id, None)

    # ------------------------------------------------------------------
    def _used(self, required_keys: Optional[Dict[str, Any]] = None,
              exclude: Optional[str] = None) -> Dict[str, float]:
        keys = ("cpu_percent", "memory_mb", "network_mbps")
        if required_keys:
            keys = tuple(k for k in required_keys if k in self.capacity)
        totals = {k: 0.0 for k in keys}
        for iid, alloc in self.allocations.items():
            if iid == exclude:
                continue
            for k in keys:
                totals[k] += float(alloc.get(k, 0.0))
        return totals

    def usage(self) -> Dict[str, Any]:
        totals = self._used()
        return {
            "capacity": self.capacity,
            "allocated": totals,
            "available": {
                k: round(self.capacity[k] - totals.get(k, 0.0), 2) for k in self.capacity
            },
            "active_intents": list(self.allocations.keys()),
        }
