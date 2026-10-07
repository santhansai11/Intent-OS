"""Service Bus: registry + dispatch for headless services.

IntentOS does not require graphical applications; functionality is
exposed through services that declare capabilities. The kernel asks
the bus: "execute calendar.find_event for intent I1024" and the bus
routes the call to the registered service.

In this prototype dispatch is in-process. The interface is transport
agnostic: a distributed deployment can back `execute()` with Unix
sockets, message queues or REST without changing the kernel.
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional


class ServiceError(Exception):
    """Raised by services to signal an operation failure."""


class ServiceBus:
    def __init__(self):
        self._services: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    def register(self, service) -> None:
        name = getattr(service, "name", None)
        if not name:
            raise ServiceError("Service must define a 'name' attribute")
        if name in self._services:
            raise ServiceError(f"Service '{name}' is already registered")
        self._services[name] = service

    def unregister(self, name: str) -> None:
        self._services.pop(name, None)

    def get(self, name: str):
        return self._services.get(name)

    def has(self, name: str) -> bool:
        return name in self._services

    def service_names(self) -> List[str]:
        return sorted(self._services)

    # ------------------------------------------------------------------
    def registry(self) -> List[Dict[str, Any]]:
        """Manifest of all registered services and their capabilities."""
        out = []
        for name in self.service_names():
            svc = self._services[name]
            out.append(
                {
                    "name": name,
                    "description": getattr(svc, "description", ""),
                    "capabilities": svc.capabilities(),
                }
            )
        return out

    # ------------------------------------------------------------------
    def execute(
        self,
        service_name: str,
        capability: str,
        params: Optional[Dict[str, Any]] = None,
        intent=None,
    ) -> Dict[str, Any]:
        """Execute a capability and wrap the outcome in a result envelope."""
        envelope: Dict[str, Any] = {
            "service": service_name,
            "capability": capability,
            "ok": False,
            "result": None,
            "error": None,
        }
        svc = self._services.get(service_name)
        if svc is None:
            envelope["error"] = f"service '{service_name}' is not registered"
            return envelope
        started = time.time()
        try:
            result = svc.execute(capability, dict(params or {}), intent)
            envelope["ok"] = True
            envelope["result"] = result
        except ServiceError as exc:
            envelope["error"] = str(exc)
        except Exception as exc:  # unexpected service crash
            envelope["error"] = f"{type(exc).__name__}: {exc}"
            envelope["traceback"] = traceback.format_exc(limit=3)
        envelope["elapsed_ms"] = round((time.time() - started) * 1000, 2)
        return envelope
