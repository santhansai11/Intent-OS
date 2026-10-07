"""Headless services package: registry builder."""
from __future__ import annotations

from intent_kernel.ipc.service_bus import ServiceBus

from .base_service import BaseService
from .ai import AIService
from .calendar import CalendarService
from .filesystem import FilesystemService
from .maps import MapsService
from .messaging import MessagingService
from .reminder import ReminderService
from .web import WebService


def build_default_bus() -> ServiceBus:
    """Create a service bus with all prototype services registered."""
    bus = ServiceBus()
    bus.register(CalendarService())
    bus.register(FilesystemService())
    bus.register(MapsService())
    bus.register(MessagingService())
    bus.register(ReminderService())
    bus.register(WebService())
    bus.register(AIService())
    return bus


__all__ = [
    "AIService",
    "BaseService",
    "CalendarService",
    "FilesystemService",
    "MapsService",
    "MessagingService",
    "ReminderService",
    "WebService",
    "build_default_bus",
    "ServiceBus",
]
