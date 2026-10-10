"""Bench controller regression checks without Qt or a connected board."""
import unittest
from bench_stepgen import BenchStepgen, STEPGEN


class BenchStepgenTests(unittest.TestCase):
    def setUp(self):
        self.writes = []
        self.healthy = True
        self.controller = BenchStepgen(self.write, lambda: self.healthy)

    def write(self, pin, value):
        self.writes.append((pin, value))

    def test_both_directions_and_stop(self):
        for direction in (-1, 1):
            self.controller.start(direction, 500)
            self.assertTrue(self.controller.active)
            self.assertIn((STEPGEN + ".velocity-cmd", str(direction * 500)), self.writes)
            self.controller.stop()
            self.assertFalse(self.controller.active)
            self.assertEqual(self.writes[-1], (STEPGEN + ".enable", "false"))

    def test_no_motion_from_construction(self):
        self.assertFalse(self.controller.active)
        self.assertEqual(self.writes, [])

    def test_fault_prevents_start_without_any_writes(self):
        self.healthy = False
        with self.assertRaises(RuntimeError):
            self.controller.start(1, 500)
        self.assertEqual(self.writes, [])

    def test_recovery_does_not_restart(self):
        self.controller.start(1, 500)
        self.healthy = False
        self.controller.stop()
        self.healthy = True
        self.assertFalse(self.controller.active)
        self.assertEqual(self.writes[-1], (STEPGEN + ".enable", "false"))

    def test_invalid_speed_and_direction(self):
        for speed in (0, -1, 2001, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.controller.start(1, speed)
        with self.assertRaises(ValueError):
            self.controller.start(0, 500)
        self.assertEqual(self.writes, [])

    def test_failure_after_enable_attempts_disable(self):
        def fail(pin, value):
            self.write(pin, value)
            if pin.endswith(".velocity-cmd") and value == "500":
                raise RuntimeError("write failed")
        self.controller.writer = fail
        with self.assertRaises(RuntimeError):
            self.controller.start(1, 500)
        self.assertFalse(self.controller.active)
        self.assertEqual(self.writes[-1], (STEPGEN + ".enable", "false"))

    def test_stop_attempts_disable_when_zero_write_fails(self):
        def fail(pin, value):
            self.write(pin, value)
            if pin.endswith(".velocity-cmd"):
                raise RuntimeError("write failed")
        self.controller.writer = fail
        with self.assertRaises(RuntimeError):
            self.controller.stop()
        self.assertEqual(self.writes[-1], (STEPGEN + ".enable", "false"))

    def test_fault_during_setup_never_enables(self):
        def fail_health(pin, value):
            self.write(pin, value)
            if pin.endswith(".steplen"):
                self.healthy = False
        self.controller.writer = fail_health
        with self.assertRaises(RuntimeError):
            self.controller.start(1, 500)
        self.assertNotIn((STEPGEN + ".enable", "true"), self.writes)
        self.assertEqual(self.writes[-1], (STEPGEN + ".enable", "false"))


if __name__ == "__main__":
    unittest.main()

