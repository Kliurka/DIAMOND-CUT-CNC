import unittest
from types import SimpleNamespace
from linuxcnc_control import LinuxCNCControl


class Ini:
    def __init__(self):
        self.data = {("KINS", "KINEMATICS"): "trivkins coordinates=XYZ",
                     ("KINS", "JOINTS"): "3", ("TRAJ", "COORDINATES"): "XYZ",
                     ("TRAJ", "LINEAR_UNITS"): "mm"}
        for a in "XYZ":
            self.data["AXIS_" + a, "MAX_VELOCITY"] = "1.5"

    def find(self, section, key):
        return self.data.get((section, key))


class Commands:
    def __init__(self):
        self.calls = []
        self.results = []

    def __getattr__(self, name):
        def command(*args):
            self.calls.append((name, args))
            if name == "wait_complete":
                return self.results.pop(0) if self.results else 1
        return command


def make_backend():
    constants = dict(STATE_ON=4, STATE_OFF=3, STATE_ESTOP=1, STATE_ESTOP_RESET=2,
                     MODE_MANUAL=1, MODE_MDI=3, INTERP_IDLE=1,
                     TRAJ_MODE_FREE=1, TRAJ_MODE_TELEOP=3,
                     JOG_STOP=0, JOG_CONTINUOUS=1, JOG_INCREMENT=2, RCS_DONE=1)
    status = SimpleNamespace(task_state=4, task_mode=1, interp_state=1, motion_mode=1,
                             actual_position=(10., 20., 30.), joint_actual_position=(10., 20., 30.),
                             g5x_offset=(1., 2., 3.), g92_offset=(.1, .2, .3),
                             tool_offset=(.4, .5, .6), rotation_xy=0., homed=(0, 0, 0),
                             joint=({}, {}, {}), inpos=True, poll=lambda: None)
    commands = Commands()
    api = SimpleNamespace(**constants, stat=lambda: status, command=lambda: commands)
    return LinuxCNCControl(api, Ini()), status, commands


class ControlTests(unittest.TestCase):
    def test_constructor_sends_no_commands(self):
        b, s, c = make_backend()
        self.assertEqual(c.calls, [])

    def test_joint_jog_axis_jog_and_saved_stop_mode(self):
        b, s, c = make_backend()
        b.jog("Z", -1, 30)
        self.assertEqual(c.calls[-1], ("jog", (1, True, 2, -.5)))
        s.motion_mode = 3
        b.stop_jog()
        self.assertEqual(c.calls[-1], ("jog", (0, True, 2)))
        b.jog("Y", 1, 30)
        self.assertEqual(c.calls[-1], ("jog", (1, False, 1, .5)))

    def test_increment_and_speed_limit(self):
        b, s, c = make_backend()
        b.jog("X", 1, 600, .1)
        self.assertEqual(c.calls[-1], ("jog", (2, True, 0, 1.5, .1)))

    def test_fault_blocks_start_and_stops_current_jog(self):
        b, s, c = make_backend()
        b.jog("X", 1, 30)
        b.healthy = lambda: False
        self.assertFalse(b.snapshot()["ready"])
        self.assertEqual(c.calls[-1], ("jog", (0, True, 0)))
        previous = list(c.calls)
        with self.assertRaises(RuntimeError):
            b.jog("X", 1, 30)
        b.healthy = lambda: True
        b.snapshot()
        self.assertEqual(previous, c.calls)

    def test_off_auto_and_homing_block_jog(self):
        for field, value in (("task_state", 3), ("task_mode", 2),
                             ("interp_state", 2), ("joint", ({"homing": True}, {}, {}))):
            b, s, c = make_backend()
            setattr(s, field, value)
            with self.assertRaises(RuntimeError):
                b.jog("X", 1, 30)
            self.assertEqual(c.calls, [])

    def test_work_coordinates_include_all_offsets_and_rotation(self):
        b, s, c = make_backend()
        state = b.snapshot()
        self.assertAlmostEqual(state["work"]["X"], 8.5)
        self.assertAlmostEqual(state["work"]["Y"], 17.3)
        s.rotation_xy = 90
        state = b.snapshot()
        self.assertAlmostEqual(state["work"]["X"], 17.3)
        self.assertAlmostEqual(state["work"]["Y"], -8.5)

    def test_home_all_switches_to_joint_mode(self):
        b, s, c = make_backend()
        b.home_all()
        self.assertEqual(c.calls, [("teleop_enable", (0,)), ("wait_complete", (1.,)), ("home", (-1,))])

    def test_zero_requires_homing_and_restores_manual_mode(self):
        b, s, c = make_backend()
        with self.assertRaises(RuntimeError):
            b.zero("X")
        self.assertEqual(c.calls, [])
        s.homed = (1, 1, 1)
        b.zero("X")
        self.assertIn(("mdi", ("G21 G10 L20 P0 X0",)), c.calls)
        self.assertEqual(c.calls[-2:], [("mode", (1,)), ("wait_complete", (1.,))])

    def test_zero_respects_existing_no_force_homing_setting(self):
        ini = Ini()
        ini.data["TRAJ", "NO_FORCE_HOMING"] = "1"
        b, s, c = make_backend()
        b = LinuxCNCControl(b.api, ini)
        self.assertTrue(b.snapshot()["can_touch_off"])
        b.zero("Z")
        self.assertIn(("mdi", ("G21 G10 L20 P0 Z0",)), c.calls)

    def test_zero_timeout_aborts_and_restores_manual(self):
        b, s, c = make_backend()
        s.homed = (1, 1, 1)
        c.results = [1, -1]
        with self.assertRaises(RuntimeError):
            b.zero("Z")
        self.assertIn(("abort", ()), c.calls)
        self.assertEqual(c.calls[-2:], [("mode", (1,)), ("wait_complete", (1.,))])

    def test_home_and_zero_reject_motion(self):
        b, s, c = make_backend()
        s.homed = (1, 1, 1)
        s.inpos = False
        for action in (b.home_all, lambda: b.zero("X")):
            with self.assertRaises(RuntimeError):
                action()
        self.assertEqual(c.calls, [])

    def test_estop_reset_never_enables_machine(self):
        b, s, c = make_backend()
        s.task_state = 1
        b.toggle_estop()
        self.assertEqual(c.calls, [("state", (2,))])

    def test_stop_aborts_even_when_jog_stop_fails(self):
        b, s, c = make_backend()
        b.active_jog = (True, 0)
        b.stop_jog = lambda: (_ for _ in ()).throw(RuntimeError("stop failed"))
        with self.assertRaises(RuntimeError):
            b.stop()
        self.assertEqual(c.calls[-1], ("abort", ()))


if __name__ == "__main__":
    unittest.main()
