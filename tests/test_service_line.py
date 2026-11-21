"""Crowded real lines come back as ranges with "uncertain" visibility. A verified range whose
lower bound meets the threshold must be able to raise a task; an unverified one must not."""
import unittest

from backend.app.analysis import Policy, TaskState, is_clear, is_high
from backend.app.contracts import Scene


def scene(low, high, visibility="uncertain"):
    return Scene.model_validate(dict(queue_min=low, queue_max=high, visibility=visibility, summary="Buffet line",
                                     people=[], groups=[], evidence_frames=[1], inspection=None))


class ServiceLineTests(unittest.TestCase):
    def test_range_rules(self):
        self.assertFalse(is_high(scene(5, 8), 4))
        self.assertTrue(is_high(scene(5, 8), 4, verified=True))
        self.assertFalse(is_high(scene(3, 8), 4, verified=True))
        self.assertTrue(is_high(scene(5, 5, "clear"), 4))
        self.assertTrue(is_clear(scene(0, 1), 2, verified=True))
        self.assertFalse(is_clear(scene(0, 3), 2, verified=True))

    def test_verified_range_creates_task_after_persistence(self):
        state = TaskState(Policy(threshold=4, persistence_ms=2000, max_gap_ms=30000), "agent")
        self.assertIsNone(state.apply(scene(5, 8), 0, [0, 0], verified=True) and None)
        task = state.apply(scene(6, 10), 12700, [9000, 12500], verified=True)
        self.assertIsNotNone(task)
        self.assertEqual(task["action"], "create")

    def test_unverified_range_never_creates_task(self):
        state = TaskState(Policy(threshold=4, persistence_ms=2000, max_gap_ms=30000), "agent")
        self.assertIsNone(state.apply(scene(5, 8), 0, [0], verified=False))
        self.assertIsNone(state.apply(scene(6, 10), 12700, [9000, 12500], verified=False))


if __name__ == "__main__":
    unittest.main()
