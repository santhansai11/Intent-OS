"""Calendar service: mock personal calendar."""
from __future__ import annotations

from typing import Any, Dict, Optional

from intent_kernel.ipc.service_bus import ServiceError
from services.base_service import BaseService

EVENTS = [
    {
        "title": "Operating Systems Review",
        "time": "16:00",
        "location": "Room 204",
        "documents": ["meeting_notes.pdf", "agenda.docx", "slides.pptx"],
    },
    {
        "title": "Project Sync",
        "time": "10:00",
        "location": "Room 110",
        "documents": ["project_status.xlsx"],
    },
    {
        "title": "Lab Session",
        "time": "14:00",
        "location": "Lab 3",
        "documents": ["lab_manual.pdf"],
    },
]


class CalendarService(BaseService):
    """Mock calendar: event lookup by time / listing all events."""

    name = "calendar"
    description = "Personal calendar events (mock data)"

    def cap_get_events(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """List all upcoming events."""
        return {"events": [dict(e) for e in EVENTS], "count": len(EVENTS)}

    def cap_find_event(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Find the event matching a time (falls back to the next event)."""
        target = params.get("time")
        event: Optional[Dict[str, Any]] = None
        topic = str(params.get("topic") or "").lower().strip()
        if topic:
            event = next((e for e in EVENTS if topic in e["title"].lower()
                          or e["title"].lower() in topic), None)
        if target:
            timed = next((e for e in EVENTS if e["time"] == target), None)
            # A named but unknown meeting is still the user's event; do not
            # attach unrelated files from an unrelated mock event at that time.
            event = event or ({"title": params.get("topic"), "time": target,
                               "location": "", "documents": []} if topic else timed)
        if event is None and topic:
            event = {"title": params.get("topic"), "time": target or "unspecified",
                     "location": "", "documents": []}
        if event is None:
            event = next((e for e in EVENTS if e["time"] >= "12:00"), EVENTS[0])
        return {"found": True, **event}
