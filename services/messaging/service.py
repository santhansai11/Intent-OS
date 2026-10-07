"""Messaging service: notifications and message sending (mock)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from services.base_service import BaseService


class MessagingService(BaseService):
    """Mock messaging: prepares/sends notifications via a local outbox."""

    name = "messaging"
    description = "Message sending and notifications (mock outbox)"

    def cap_send_message(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Send a message to a recipient via the mock outbox."""
        recipient = params.get("recipient") or "team@local"
        message = params.get("message") or "(empty)"
        envelope = {
            "recipient": recipient,
            "message": message,
            "message_id": f"MSG-{abs(hash((recipient, message, intent.id if intent else ''))) % 99999:05d}",
            "status": "sent",
        }
        if intent is not None:
            try:
                from intent_kernel.paths import ensure_storage_dirs, storage_dir
                ensure_storage_dirs()
                outbox = storage_dir() / "outbox.jsonl"
                with open(outbox, "a", encoding="utf-8") as fh:
                    fh.write(str(envelope) + "\n")
            except Exception:
                pass  # outbox persistence is best-effort in the prototype
        return envelope

    def cap_prepare_notification(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Compose a notification from the aggregated intent summary."""
        summary = params.get("summary") or "No summary available"
        notification = {
            "channel": "email",
            "recipient": (getattr(intent, "entities", {}) or {}).get("recipient", "user@local"),
            "preview": summary[:140],
            "status": "queued",
        }
        if intent is not None:
            try:
                from intent_kernel.intent_file_manager import IntentFileManager
                IntentFileManager().save_output(intent.id, "notification.txt", summary)
            except Exception:
                pass
        return notification
