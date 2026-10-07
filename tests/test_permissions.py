"""Unit tests for the permission manager (least-privilege enforcement)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.permission_manager import ALLOW, ASK, DENY, PermissionManager


def fake_intent(intent_type="prepare_meeting"):
    return SimpleNamespace(intent_type=intent_type, id="I1024")


class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager()
        self.meeting = fake_intent("prepare_meeting")

    def test_allowed_read(self):
        decision, reason = self.pm.check(self.meeting, "calendar", "READ")
        self.assertEqual(decision, ALLOW)

    def test_denied_mode(self):
        decision, reason = self.pm.check(self.meeting, "calendar", "WRITE")
        self.assertEqual(decision, DENY)

    def test_protected_resources_always_denied(self):
        for resource in ("passwords", "system_files"):
            decision, _ = self.pm.check(self.meeting, resource, "READ")
            self.assertEqual(decision, DENY)

    def test_unknown_service_asks(self):
        decision, _ = self.pm.check(self.meeting, "contacts", "READ")
        self.assertEqual(decision, ALLOW)  # in policy
        decision, _ = self.pm.check(self.meeting, "printer", "USE")
        self.assertEqual(decision, ASK)  # not in policy, default-deny + ask

    def test_unknown_intent_type_gets_nothing(self):
        decision, _ = self.pm.check(fake_intent("whatever"), "calendar", "READ")
        self.assertEqual(decision, ASK)

    def test_kernel_itself_protected(self):
        decision, _ = self.pm.check(self.meeting, "intent_kernel", "EXECUTE")
        self.assertEqual(decision, DENY)

    def test_grant_revoke(self):
        self.pm.grant("prepare_meeting", "printer", "USE")
        decision, _ = self.pm.check(self.meeting, "printer", "USE")
        self.assertEqual(decision, ALLOW)
        self.pm.revoke("prepare_meeting", "printer")
        decision, _ = self.pm.check(self.meeting, "printer", "USE")
        self.assertEqual(decision, ASK)

    def test_audit_hook(self):
        calls = []
        pm = PermissionManager(auto_grant_ask=False, audit=lambda i, s, d, r: calls.append((i, s, d)))
        decision, _ = pm.check(self.meeting, "passwords", "READ")
        self.assertEqual(decision, DENY)
        self.assertEqual(calls, [("I1024", "passwords", DENY)])


if __name__ == "__main__":
    unittest.main()
