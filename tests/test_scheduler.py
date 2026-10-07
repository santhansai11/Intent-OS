"""Unit tests for the four schedulers and the simulation module."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.intent import HIGH, LOW, MEDIUM, Intent
from intent_kernel.scheduler import get_scheduler
from intent_kernel.simulation import DEFAULT_WORKLOAD, SimTask, simulate, compare_strategies


def mk(id, priority=MEDIUM, deadline=None, created=None):
    return Intent(
        id=id,
        goal=id,
        priority=priority,
        deadline=deadline,
        created_at=created or 0.0,
    )


class TestSchedulers(unittest.TestCase):
    def test_fcfs_arrival_order(self):
        s = get_scheduler("fcfs")
        ready = [mk("I2", HIGH), mk("I1", LOW), mk("I3", MEDIUM)]
        self.assertEqual(s.select(ready).id, "I1")  # earliest arrival

    def test_priority_selects_high(self):
        s = get_scheduler("priority")
        ready = [mk("I1", LOW), mk("I2", HIGH), mk("I3", MEDIUM)]
        self.assertEqual(s.select(ready).id, "I2")

    def test_deadline_selects_earliest(self):
        base = datetime(2026, 1, 1, 10, 0)
        s = get_scheduler("deadline")
        ready = [
            mk("I1", HIGH, deadline=base + timedelta(hours=3)),
            mk("I2", LOW, deadline=base + timedelta(hours=1)),
            mk("I3", MEDIUM),
        ]
        self.assertEqual(s.select(ready).id, "I2")

    def test_deadline_tie_breaks_on_priority(self):
        base = datetime(2026, 1, 1, 10, 0)
        s = get_scheduler("deadline")
        ready = [
            mk("I1", MEDIUM, deadline=base),
            mk("I2", HIGH, deadline=base),
        ]
        self.assertEqual(s.select(ready).id, "I2")

    def test_round_robin_rotates(self):
        s = get_scheduler("round_robin")
        ready = [mk("I1"), mk("I2"), mk("I3")]
        picks = [s.select(ready).id for _ in range(3)]
        self.assertEqual(sorted(picks), ["I1", "I2", "I3"])  # rotation, no repeats

    def test_empty_queue(self):
        for name in ("fcfs", "priority", "round_robin", "deadline"):
            self.assertIsNone(get_scheduler(name).select([]))

    def test_unknown_strategy(self):
        with self.assertRaises(KeyError):
            get_scheduler("nope")


class TestSimulation(unittest.TestCase):
    def test_fcfs_order_follows_arrival(self):
        tasks = [
            SimTask("A", priority=HIGH, cost=4, arrival=0),
            SimTask("B", priority=LOW, cost=2, arrival=1),
        ]
        result = simulate("fcfs", tasks)
        self.assertEqual(result.order, ["A", "B"])

    def test_priority_beats_arrival(self):
        tasks = [
            SimTask("A", priority=LOW, cost=4, arrival=0),
            SimTask("B", priority=HIGH, cost=4, arrival=0),
        ]
        result = simulate("priority", tasks)
        self.assertEqual(result.order[0], "B")

    def test_deadline_minimizes_misses(self):
        tasks = [
            SimTask("Tight", priority=LOW, cost=2, deadline=2),
            SimTask("Loose", priority=HIGH, cost=8, deadline=None),
        ]
        results = {r["strategy"]: r for r in compare_strategies(tasks)}
        self.assertEqual(results["deadline"]["deadline_misses"], 0)
        self.assertEqual(results["priority"]["deadline_misses"], 1)

    def test_default_workload_runs_all(self):
        results = compare_strategies()
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertEqual(len(r["completion_order"]), len(DEFAULT_WORKLOAD))


if __name__ == "__main__":
    unittest.main()
