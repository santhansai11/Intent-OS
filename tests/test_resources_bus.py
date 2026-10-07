"""Unit tests for resource accounting and the service bus."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.intent import Intent
from intent_kernel.ipc.service_bus import ServiceBus, ServiceError
from intent_kernel.resource_manager import ResourceManager
from services import build_default_bus
from services.base_service import BaseService


class TestResourceManager(unittest.TestCase):
    def test_allocate_and_release(self):
        rm = ResourceManager()
        intent = Intent(id="I1", goal="g", intent_type="prepare_meeting",
                        resource_requirements=rm.requirements_for("prepare_meeting"))
        self.assertTrue(rm.allocate(intent))
        self.assertIn("I1", rm.usage()["active_intents"])
        rm.release("I1")
        self.assertNotIn("I1", rm.usage()["active_intents"])

    def test_overcommit_rejected(self):
        rm = ResourceManager()
        rm.capacity = {"cpu_percent": 20.0, "memory_mb": 8192.0, "network_mbps": 100.0}
        req = rm.requirements_for("prepare_meeting")
        i1 = Intent(id="I1", goal="g", intent_type="prepare_meeting", resource_requirements=dict(req))
        i2 = Intent(id="I2", goal="g", intent_type="prepare_meeting", resource_requirements=dict(req))
        self.assertTrue(rm.allocate(i1))
        self.assertFalse(rm.allocate(i2))  # cpu_percent 20/20 already used

    def test_double_allocate_is_noop(self):
        rm = ResourceManager()
        intent = Intent(id="I1", goal="g", intent_type="get_schedule",
                        resource_requirements=rm.requirements_for("get_schedule"))
        self.assertTrue(rm.allocate(intent))
        self.assertTrue(rm.allocate(intent))
        self.assertEqual(rm.usage()["allocated"]["cpu_percent"],
                         rm.requirements_for("get_schedule")["cpu_percent"])


class FakeService(BaseService):
    name = "fake"
    description = "fake test service"

    def cap_ping(self, params, intent=None):
        """Ping."""
        return {"pong": True}

    def cap_boom(self, params, intent=None):
        """Boom."""
        raise RuntimeError("exploded")


class TestServiceBus(unittest.TestCase):
    def setUp(self):
        self.bus = ServiceBus()
        self.bus.register(FakeService())

    def test_registry_lists_capabilities(self):
        entry = next(s for s in self.bus.registry() if s["name"] == "fake")
        names = {c["name"] for c in entry["capabilities"]}
        self.assertEqual(names, {"ping", "boom"})

    def test_execute_success_envelope(self):
        out = self.bus.execute("fake", "ping", {})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"], {"pong": True})
        self.assertIn("elapsed_ms", out)

    def test_unknown_service(self):
        out = self.bus.execute("ghost", "ping", {})
        self.assertFalse(out["ok"])
        self.assertIn("not registered", out["error"])

    def test_unknown_capability(self):
        out = self.bus.execute("fake", "teleport", {})
        self.assertFalse(out["ok"])
        self.assertIn("no capability", out["error"])

    def test_crash_is_contained(self):
        out = self.bus.execute("fake", "boom", {})
        self.assertFalse(out["ok"])
        self.assertIn("exploded", out["error"])

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ServiceError):
            self.bus.register(FakeService())

    def test_default_bus_has_all_services(self):
        bus = build_default_bus()
        self.assertEqual(bus.service_names(),
                         ["ai", "calendar", "filesystem", "maps", "messaging",
                          "reminder", "web"])


if __name__ == "__main__":
    unittest.main()
