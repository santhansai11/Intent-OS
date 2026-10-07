"""Base class for headless IntentOS services."""
from __future__ import annotations

from typing import Any, Dict, List

from intent_kernel.ipc.service_bus import ServiceError


class BaseService:
    """A headless service exposing named capabilities to the Intent Kernel."""

    name = "base"
    description = ""

    def __init__(self, latency: float = 0.0, fail_next: int = 0):
        self.latency = latency      # simulated execution latency (seconds)
        self.fail_next = fail_next  # fault injection: fail this many next calls

    # ------------------------------------------------------------------
    def capabilities(self) -> List[Dict[str, Any]]:
        """Return [{name, access, description}] for the service registry."""
        caps = []
        for attr in sorted(dir(self)):
            if attr.startswith("cap_") and callable(getattr(self, attr)):
                fn = getattr(self, attr)
                caps.append(
                    {
                        "name": attr[len("cap_"):],
                        "access": getattr(fn, "access", "USE"),
                        "description": (fn.__doc__ or "").strip().split("\n")[0],
                    }
                )
        return caps

    def has_capability(self, capability: str) -> bool:
        return callable(getattr(self, f"cap_{capability}", None))

    # ------------------------------------------------------------------
    def execute(self, capability: str, params: Dict[str, Any], intent=None) -> Any:
        """Dispatch a capability call; raises ServiceError on failure."""
        fn = getattr(self, f"cap_{capability}", None)
        if not callable(fn):
            raise ServiceError(f"'{self.name}' has no capability '{capability}'")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ServiceError(f"simulated failure in '{self.name}.{capability}' (fault injection)")
        if self.latency > 0:
            import time
            time.sleep(self.latency)
        return fn(params or {}, intent)
