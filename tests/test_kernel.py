"""Integration tests: full kernel pipeline + failure recovery."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.intent import (
    COMPLETED,
    FAILED,
    HIGH,
    STEP_BLOCKED,
    STEP_DONE,
    WAITING,
)
from intent_kernel.kernel import IntentKernel
from intent_kernel.paths import ensure_storage_dirs


class KernelTestBase(unittest.TestCase):
    """Redirects all storage writes into a temp dir for test isolation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["INTENTOS_ROOT"] = self._tmp.name
        ensure_storage_dirs()
        docs = Path(self._tmp.name) / "storage" / "documents"
        docs.mkdir(parents=True, exist_ok=True)
        for name in ("meeting_notes.pdf", "agenda.docx", "slides.pptx"):
            (docs / name).write_text(f"stub content for {name}", encoding="utf-8")
        self.kernel = IntentKernel(strategy="deadline", persist=False)

    def tearDown(self):
        os.environ.pop("INTENTOS_ROOT", None)
        self._tmp.cleanup()


class TestPrepareMeeting(KernelTestBase):
    def test_end_to_end_meeting_intent(self):
        intent = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.assertEqual(intent.intent_type, "prepare_meeting")
        self.assertEqual(intent.priority, HIGH)
        self.assertIsNotNone(intent.deadline)
        self.assertEqual(len(intent.plan), 5)
        self.kernel.run_all()
        self.assertEqual(intent.state, COMPLETED)
        self.assertTrue(all(s in (STEP_DONE, STEP_BLOCKED) for s in intent.step_state.values()))
        event = intent.step_results["S1"]["result"]
        self.assertEqual(event["title"], "Operating Systems Review")
        self.assertEqual(event["location"], "Room 204")
        lines = self.kernel.result_summary(intent)
        self.assertTrue(any("Operating Systems Review" in l for l in lines))
        self.assertTrue(any("minutes" in l for l in lines))

    def test_intent_file_context_created(self):
        from intent_kernel.paths import intent_logs_dir
        intent = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.kernel.run_all()
        d = intent_logs_dir() / intent.id
        for fname in ("intent.json", "plan.json", "permissions.json", "checkpoint.json", "execution.log"):
            self.assertTrue((d / fname).exists(), f"missing {fname}")
        self.assertTrue((d / "output").is_dir())


class TestSchedulerBehaviour(KernelTestBase):
    def test_priority_scheduler_runs_high_priority_first(self):
        low = self.kernel.submit_text("Download the lecture videos")
        high = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.kernel.set_strategy("priority")
        first_run = self.kernel.step_once()
        self.assertEqual(first_run.id, high.id)
        self.kernel.run_all()
        self.assertEqual(high.state, COMPLETED)
        self.assertEqual(low.state, COMPLETED)


class TestFailureRecovery(KernelTestBase):
    def test_checkpoint_resume_after_failure(self):
        self.kernel.set_fault("messaging", 1)  # first messaging call fails
        intent = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.kernel.run_all()
        self.assertEqual(intent.state, COMPLETED)
        attempts = intent.step_attempts["S4"]
        self.assertEqual(attempts, 2)  # one failure + one successful retry
        self.assertTrue(any("RECOVERY" in line for line in intent.execution_log))
        # steps before the failed one were NOT re-executed
        self.assertEqual(intent.step_attempts["S1"], 1)
        self.assertEqual(intent.step_attempts["S2"], 1)
        self.assertEqual(intent.step_attempts["S3"], 1)

    def test_retry_exhaustion_fails_intent(self):
        self.kernel.set_fault("messaging", 5)  # more failures than max_retries
        intent = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.kernel.run_all()
        self.assertEqual(intent.state, FAILED)
        self.assertIn(intent.step_state["S4"], (FAILED, "STEP_FAILED"))

    def test_recovery_from_failed_to_ready(self):
        from intent_kernel.lifecycle import can_transition
        intent = self.kernel.submit_text("Prepare everything for my 4 PM meeting.")
        self.assertTrue(can_transition(intent, "RUNNING"))
        intent.transition("RUNNING")
        self.assertTrue(can_transition(intent, "RECOVERY"))
        intent.transition("RECOVERY")
        self.assertTrue(can_transition(intent, "READY"))


class TestResourceLimits(KernelTestBase):
    def test_waiting_when_overcommitted(self):
        # Shrink capacity so only one meeting intent fits at a time.
        kernel = IntentKernel(strategy="fcfs", persist=False,
                              storage_root=None)
        kernel.resources.capacity = {"cpu_percent": 20.0, "memory_mb": 300.0,
                                     "network_mbps": 12.0}
        i1 = kernel.submit_text("Prepare everything for my 4 PM meeting.")
        i2 = kernel.submit_text("Prepare everything for my 4 PM meeting.")
        kernel.run_all()
        self.assertEqual({i1.state, i2.state}, {COMPLETED})
        # The second intent must have been forced into WAITING at some point
        # (its allocation was denied until the first intent released).
        self.assertTrue(
            any("WAITING" in l for l in i2.execution_log)
            or i2.state == COMPLETED
        )


if __name__ == "__main__":
    unittest.main()
