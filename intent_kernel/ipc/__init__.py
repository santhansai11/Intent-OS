"""IPC / service registry package.

The prototype dispatches to in-process headless services. The same
interface can be backed by Unix sockets, message queues or REST in a
distributed deployment (see service_bus.py docstring).
"""
from __future__ import annotations

from .service_bus import ServiceBus, ServiceError

__all__ = ["ServiceBus", "ServiceError"]
