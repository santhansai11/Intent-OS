"""Intent Planner: goal -> executable plan.

Each intent type maps to an ordered list of steps. Steps reference
service capabilities and may contain parameter placeholders:

    "@entities.time"          -> intent.entities["time"]
    "@result.S1.location"     -> step_results["S1"]["result"]["location"]
    "@summary"                -> kernel-composed aggregate summary
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

PLAN_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "prepare_meeting": [
        {
            "id": "S1", "service": "calendar", "capability": "find_event",
            "access": "READ", "params": {"time": "@entities.time"},
            "description": "Find the calendar event",
        },
        {
            "id": "S2", "service": "filesystem", "capability": "find_documents",
            "access": "READ", "params": {"related": "@result.S1.documents"},
            "description": "Find related documents",
        },
        {
            "id": "S3", "service": "maps", "capability": "calculate_route",
            "access": "USE", "params": {"destination": "@result.S1.location"},
            "description": "Calculate travel information",
        },
        {
            "id": "S4", "service": "messaging", "capability": "prepare_notification",
            "access": "WRITE", "params": {"summary": "@summary"},
            "description": "Prepare notification message",
        },
        {
            "id": "S5", "service": "reminder", "capability": "set_reminder",
            "access": "WRITE", "params": {"time": "@entities.time", "note": "@summary"},
            "description": "Set a pre-meeting reminder",
        },
    ],
    "collect_meeting_files": [
        {"id": "S1", "service": "calendar", "capability": "find_event",
         "access": "READ", "params": {"time": "@entities.time", "topic": "@entities.subject"},
         "description": "Identify the meeting and its attached materials"},
        {"id": "S2", "service": "filesystem", "capability": "collect_meeting_files",
         "access": "WRITE", "params": {"related": "@result.S1.documents", "topic": "@entities.subject", "destination": "@entities.output_path"},
         "description": "Find related files and copy them to the requested folder"},
    ],
    "get_schedule": [
        {
            "id": "S1", "service": "calendar", "capability": "get_events",
            "access": "READ", "params": {},
            "description": "List calendar events",
        },
    ],
    "send_message": [
        {
            "id": "S1", "service": "messaging", "capability": "send_message",
            "access": "WRITE",
            "params": {"recipient": "@entities.recipient", "message": "@entities.topic"},
            "description": "Send the message",
        },
    ],
    "download_files": [
        {
            "id": "S1", "service": "filesystem", "capability": "download",
            "access": "WRITE", "params": {},
            "description": "Download requested files",
        },
    ],
    "set_reminder": [
        {
            "id": "S1", "service": "reminder", "capability": "set_reminder",
            "access": "WRITE", "params": {"time": "@entities.time", "note": "@entities.topic"},
            "description": "Create the reminder",
        },
    ],
    "submit_assignment": [
        {
            "id": "S1", "service": "filesystem", "capability": "find_documents",
            "access": "READ", "params": {"related": "@entities.topic"},
            "description": "Locate the assignment document",
        },
        {
            "id": "S2", "service": "messaging", "capability": "send_message",
            "access": "WRITE",
            "params": {"recipient": "@entities.recipient", "message": "@entities.topic"},
            "description": "Submit to the recipient",
        },
    ],
    "find_file": [
        {
            "id": "S1", "service": "filesystem", "capability": "search_files",
            "access": "READ",
            "params": {"root": "@entities.folder", "keyword": "@entities.file"},
            "description": "Search for the file",
        },
    ],
    "read_file": [
        {
            "id": "S1", "service": "filesystem", "capability": "read_file",
            "access": "READ", "params": {"path": "@entities.path"},
            "description": "Read the file contents",
        },
    ],
    "summarize_document": [
        {"id": "S1", "service": "filesystem", "capability": "find_document_for_summary",
         "access": "READ", "params": {"path": "@entities.path", "file": "@entities.file", "topic": "@entities.subject"},
         "description": "Find the requested document automatically and extract its text"},
        {"id": "S2", "service": "ai", "capability": "summarize",
         "access": "USE", "params": {"text": "@result.S1.content", "topic": "@result.S1.name", "length": "@entities.length"},
         "description": "Summarize the document contents"},
    ],
    "organize_folder": [
        {
            "id": "S1", "service": "filesystem", "capability": "list_folder",
            "access": "READ", "params": {"path": "@entities.folder"},
            "description": "Scan the folder contents",
        },
        {
            "id": "S2", "service": "filesystem", "capability": "organize_folder",
            "access": "WRITE", "params": {"path": "@entities.folder"},
            "description": "Sort files into category subfolders",
        },
    ],
    "backup_folder": [
        {
            "id": "S1", "service": "filesystem", "capability": "backup_folder",
            "access": "WRITE", "params": {"path": "@entities.folder"},
            "description": "Create a timestamped backup copy",
        },
    ],
    "unknown": [],
}

# ---------------------------------------------------------------------------
# Content-generation plans: research -> generate -> write a real file
# ---------------------------------------------------------------------------
PLAN_TEMPLATES.update({
    "create_summary": [
        {
            "id": "S1", "service": "web", "capability": "search",
            "access": "READ",
            "params": {"query": "@entities.subject", "limit": 5},
            "description": "Research the topic on the live web",
        },
        {
            "id": "S2", "service": "web", "capability": "fetch_many",
            "access": "READ",
            "params": {"titles": "@result.S1.results", "limit": 3},
            "description": "Fetch source extracts",
        },
        {
            "id": "S3", "service": "ai", "capability": "summarize",
            "access": "USE",
            "params": {
                "topic": "@entities.subject",
                "sources": "@result.S2.pages",
                "abstract": "@result.S1.abstract",
                "length": "@entities.length",
            },
            "description": "Generate the summary with the AI service",
        },
        {
            "id": "S4", "service": "ai", "capability": "compose_document",
            "access": "USE",
            "params": {
                "topic": "@entities.subject",
                "summary": "@result.S3.summary",
                "bullets": "@result.S3.bullets",
                "sources": "@result.S2.pages",
                "length": "@entities.length",
                "format": "@entities.format",
            },
            "description": "Render the summary document",
        },
        {
            "id": "S5", "service": "filesystem", "capability": "write_file",
            "access": "WRITE",
            "params": {
                "filename": "@result.S4.filename",
                "content": "@result.S4.document",
                "topic": "@entities.subject",
                "path": "@entities.output_path",
                "format": "@entities.format",
            },
            "description": "Create the file in the workspace",
        },
    ],
    "research_topic": [
        {
            "id": "S1", "service": "web", "capability": "search",
            "access": "READ",
            "params": {"query": "@entities.subject", "limit": 8},
            "description": "Search the live web for the topic",
        },
        {
            "id": "S2", "service": "web", "capability": "fetch_many",
            "access": "READ",
            "params": {"titles": "@result.S1.results", "limit": 6},
            "description": "Fetch source extracts",
        },
        {
            "id": "S3", "service": "ai", "capability": "summarize",
            "access": "USE",
            "params": {
                "topic": "@entities.subject",
                "sources": "@result.S2.pages",
                "abstract": "@result.S1.abstract",
                "length": "@entities.length",
            },
            "description": "Summarise the research",
        },
        {
            "id": "S4", "service": "ai", "capability": "compose_document",
            "access": "USE",
            "params": {
                "topic": "@entities.subject",
                "summary": "@result.S3.summary",
                "bullets": "@result.S3.bullets",
                "sources": "@result.S2.pages",
                "length": "@entities.length",
                "kind": "research brief",
                "format": "@entities.format",
            },
            "description": "Compose the research brief",
        },
        {
            "id": "S5", "service": "filesystem", "capability": "write_file",
            "access": "WRITE",
            "params": {
                "filename": "@result.S4.filename",
                "content": "@result.S4.document",
                "topic": "@entities.subject",
                "path": "@entities.output_path",
                "format": "@entities.format",
                "subfolder": "research",
            },
            "description": "Save the brief to the workspace",
        },
    ],
    "write_document": [
        {
            "id": "S1", "service": "ai", "capability": "draft_document",
            "access": "USE",
            "params": {
                "topic": "@entities.subject",
                "length": "@entities.length",
                "kind": "@entities.doctype",
                "format": "@entities.format",
            },
            "description": "Draft the document with the AI service",
        },
        {
            "id": "S2", "service": "filesystem", "capability": "write_file",
            "access": "WRITE",
            "params": {
                "filename": "@result.S1.filename",
                "content": "@result.S1.document",
                "topic": "@entities.subject",
                "path": "@entities.output_path",
                "format": "@entities.format",
                "subfolder": "documents",
            },
            "description": "Create the file in the workspace",
        },
    ],
})

DEFAULT_PRIORITIES: Dict[str, str] = {
    "prepare_meeting": "HIGH",
    "collect_meeting_files": "HIGH",
    "submit_assignment": "HIGH",
    "send_message": "MEDIUM",
    "set_reminder": "MEDIUM",
    "organize_folder": "MEDIUM",
    "summarize_document": "MEDIUM",
    "create_summary": "MEDIUM",
    "research_topic": "MEDIUM",
    "write_document": "MEDIUM",
    "get_schedule": "LOW",
    "download_files": "LOW",
    "find_file": "LOW",
    "read_file": "LOW",
    "backup_folder": "LOW",
    "unknown": "MEDIUM",
}


class Planner:
    """Converts a classified intent into an ordered execution plan."""

    def __init__(self, templates: Dict[str, List[Dict[str, Any]]] = None):
        self.templates = templates or PLAN_TEMPLATES

    def available_intents(self):
        return sorted(self.templates.keys())

    def create_plan(self, intent_type: str, entities: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Deep-copy the template so intents never share step dicts."""
        import copy
        steps = copy.deepcopy(self.templates.get(intent_type, []))
        for step in steps:
            # Snapshot entity defaults into params where resolvable now
            params = step.get("params", {})
            resolved = {}
            for key, value in params.items():
                if isinstance(value, str) and value.startswith("@entities."):
                    resolved[key] = entities.get(value[len("@entities."):])
                else:
                    resolved[key] = value
            step["params"] = resolved
        self._apply_defaults(intent_type, entities, steps)
        return steps

    def _apply_defaults(self, intent_type: str, entities: Dict[str, Any],
                        steps: List[Dict[str, Any]]) -> None:
        """Fill in sensible defaults for parameters the user did not specify."""
        if not steps:
            return

        def fill(idx: int, key: str, value) -> None:
            if steps[idx]["params"].get(key) in (None, ""):
                steps[idx]["params"][key] = value

        if intent_type == "find_file":
            default_root = Path.home() / "Downloads"
            if not default_root.exists():
                default_root = Path.home()
            fill(0, "root", entities.get("folder") or str(default_root))
            fill(0, "keyword", entities.get("file") or entities.get("topic") or "")
        elif intent_type == "read_file":
            fill(0, "path", entities.get("path") or entities.get("file"))
        elif intent_type == "summarize_document":
            for key in ("path", "file", "topic"):
                if steps[0]["params"].get(key) in (None, ""):
                    steps[0]["params"][key] = entities.get(key)
            steps[1]["params"]["length"] = entities.get("length") or "brief"
        elif intent_type == "collect_meeting_files":
            if not steps[0]["params"].get("topic"):
                steps[0]["params"]["topic"] = entities.get("subject") or entities.get("topic")
            if not steps[1]["params"].get("topic"):
                steps[1]["params"]["topic"] = entities.get("subject") or entities.get("topic")
            if not steps[1]["params"].get("destination"):
                steps[1]["params"]["destination"] = str(
                    Path(__file__).resolve().parents[1] / "storage" / "workspace" /
                    (entities.get("subject") or "meeting-materials"))
        elif intent_type in ("organize_folder", "backup_folder"):
            fill(0, "path", entities.get("folder"))
            if intent_type == "organize_folder" and len(steps) > 1:
                fill(1, "path", entities.get("folder"))
        elif intent_type in ("create_summary", "research_topic", "write_document"):
            subject = (entities.get("subject") or entities.get("topic")
                       or entities.get("file") or "untitled topic")

            def fill_step(step: Dict[str, Any], key: str, value) -> None:
                if step["params"].get(key) in (None, ""):
                    step["params"][key] = value

            for step in steps:
                if step["service"] == "web":
                    fill_step(step, "query", subject)
                elif step["service"] == "ai":
                    fill_step(step, "topic", subject)
                    fill_step(step, "length", entities.get("length") or "brief")
                    fill_step(step, "kind", entities.get("doctype"))

    def default_priority(self, intent_type: str) -> str:
        return DEFAULT_PRIORITIES.get(intent_type, "MEDIUM")
