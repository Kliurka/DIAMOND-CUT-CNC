import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from linuxcnc_control import LinuxCNCControl


class Ini:
    def __init__(self):
        self.data = {("KINS", "KINEMATICS"): "trivkins coordinates=XYZ",
                     ("KINS", "JOINTS"): "3", ("TRAJ", "COORDINATES"): "XYZ",
                     ("TRAJ", "LINEAR_UNITS"): "mm"}
        for a in "XYZ":
            self.data["AXIS_" + a, "MAX_VELOCITY"] = "1.5"
            self.data["AXIS_" + a, "MIN_LIMIT"] = "-100"
            self.data["AXIS_" + a, "MAX_LIMIT"] = "100"

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
                     MODE_MANUAL=1, MODE_MDI=3, MODE_AUTO=2, AUTO_RUN=0, SPINDLE_OFF=0, INTERP_IDLE=1,
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
    def test_scan_start_move_changes_only_x_and_finishes_asynchronously(self):
        b, s, c = make_backend()
        s.homed = (1, 0, 1)
        s.tool_offset = (0, 0, 0)
        s.g5x_offset = (250., 0, 0)
        s.g92_offset = (0., 0, 0)
        b.x_center_reference = b.center_signature()
        b.move_to_scan_x(-180, 30)
        self.assertIn(('mdi', ('G21 G90 G54 G94 G1 X-180.000000 F30.000000',)), c.calls)
        self.assertTrue(b.positioning)
        self.assertFalse(b.snapshot()['ready'])
        s.interp_state = 2
        s.inpos = False
        b.snapshot()
        s.interp_state = 1
        s.inpos = True
        s.joint_actual_position = (70., 20., 30.)
        b.snapshot()
        self.assertFalse(b.positioning)
        self.assertEqual(b.positioning_error, '')
        self.assertEqual(c.calls[-1], ('mode', (b.api.MODE_MANUAL,)))
        self.assertEqual(s.g5x_offset, (250., 0, 0))

    def test_scan_start_move_blocks_unreferenced_or_out_of_limits_targets(self):
        b, s, c = make_backend()
        s.homed = (1, 0, 1)
        s.tool_offset = (0, 0, 0)
        with self.assertRaises(RuntimeError):
            b.move_to_scan_x(-20, 30)
        b.x_center_reference = b.center_signature()
        with self.assertRaises(ValueError):
            b.move_to_scan_x(-200, 30)
        self.assertEqual(c.calls, [])

    def test_xz_homing_does_not_require_manual_table_homing(self):
        b, s, c = make_backend()
        s.homed = (1, 0, 1)
        self.assertTrue(b.snapshot()["homed"])
        b.zero("Z")
        self.assertIn(("mdi", ("G21 G10 L20 P0 Z0",)), c.calls)

    def test_table_lock_stops_table_and_blocks_restart_but_not_x(self):
        b, s, c = make_backend()
        b.jog("Y", 1, 30)
        b.set_table_locked(True)
        self.assertEqual(c.calls[-1], ("jog", (0, True, 1)))
        with self.assertRaises(RuntimeError):
            b.jog("Y", -1, 30)
        b.jog("X", 1, 30)
        b.stop_jog()
        b.set_table_locked(False)
        self.assertIsNone(b.active_jog)

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
            b.zero("Z")
        self.assertEqual(c.calls, [])
        s.homed = (1, 1, 1)
        b.zero("Z")
        self.assertIn(("mdi", ("G21 G10 L20 P0 Z0",)), c.calls)
        self.assertEqual(c.calls[-2:], [("mode", (1,)), ("wait_complete", (1.,))])

    def test_work_zero_always_requires_homing(self):
        ini = Ini()
        ini.data["TRAJ", "NO_FORCE_HOMING"] = "1"
        b, s, c = make_backend()
        b = LinuxCNCControl(b.api, ini)
        self.assertFalse(b.snapshot()["can_touch_off"])
        with self.assertRaises(RuntimeError):
            b.zero("Z")
        self.assertEqual(c.calls, [])

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
        for action in (b.home_all, lambda: b.zero("Z")):
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


class ProgramTests(unittest.TestCase):
    code = "G21 G90 G40 G49 G54 G8 G94\nG97 S1000\nM3\nF60\nG0 Z-2\nG0 X0\nG1 Z0.01\nG1 X10 Z0.02\nG0 Z-2\nM5\nM2\n"

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'program.ngc'
        self.path.write_text(self.code)
        self.b, self.s, self.c = make_backend()
        self.s.homed = (1, 0, 1)

    def test_g95_velocity_limit_blocks_before_auto(self):
        self.path.write_text(self.code.replace('G1 Z0.01', 'G96 D1200 S150\nG95 F1\nG1 Z0.01').replace('X10', 'X-10'))
        self.s.tool_offset = (0, 0, 0)
        self.b.x_center_reference = self.b.center_signature()
        self.b.spindle_feedback = lambda: True
        self.b.rpm_feedback_verified = True
        with self.assertRaisesRegex(RuntimeError, 'G95 feed exceeds'):
            self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [])

    def test_radius_touch_off_sets_center_without_home_motion(self):
        self.s.tool_offset = (0, 0, 0)
        self.b.touch_off_x_radius(25)
        self.assertIn(('mdi', ('G21 G49 G10 L20 P0 X-25.000000',)), self.c.calls)
        self.assertEqual(self.b.x_center_reference, self.b.center_signature())
        self.assertFalse(any(name in ('home', 'auto', 'jog') for name, _ in self.c.calls))
        with self.assertRaises(ValueError):
            self.b.zero('X')
        self.assertEqual(self.b.x_center_reference, self.b.center_signature())

    def test_css_run_requires_center_and_real_feedback_and_checks_offset_changes(self):
        self.path.write_text(self.code.replace('G1 Z0.01', 'G96 D1200 S150\nG95 F0.05\nG1 Z0.01').replace('X10', 'X-10'))
        self.s.tool_offset = (0, 0, 0)
        with self.assertRaisesRegex(RuntimeError, 'known radius'):
            self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [])
        self.b.x_center_reference = self.b.center_signature()
        with self.assertRaisesRegex(RuntimeError, 'RPM feedback'):
            self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [])
        self.b.rpm_feedback_verified = True
        self.b.spindle_feedback = lambda: True
        self.b.run_program(self.path)
        self.assertTrue(self.b.program_running)
        self.b.spindle_feedback = lambda: False
        self.b.snapshot()
        self.assertFalse(self.b.program_running)
        self.assertIn(('spindle', (0,)), self.c.calls)
        self.b.spindle_feedback = lambda: True
        self.s.g5x_offset = (2, 2, 3)
        with self.assertRaisesRegex(RuntimeError, 'known radius'):
            self.b.run_program(self.path)

    def test_run_opens_full_program_then_starts_line_zero(self):
        self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [('mode', (2,)), ('wait_complete', (1,)),
            ('program_open', (str(self.path),)), ('wait_complete', (1,)), ('auto', (0, 0))])
        self.assertTrue(self.b.program_running)
        self.assertFalse(self.b.snapshot()['ready'])
        with self.assertRaises(RuntimeError):
            self.b.jog('Y', 1, 60)

    def test_interlocks_block_without_start_commands(self):
        for field, value in [('homed', (0, 0, 1)), ('inpos', False),
                ('task_state', 3), ('task_mode', 2), ('interp_state', 2), ('rotation_xy', 90)]:
            with self.subTest(field=field):
                b, s, c = make_backend()
                s.homed = (1, 0, 1)
                setattr(s, field, value)
                with self.assertRaises(RuntimeError):
                    b.run_program(self.path)
                self.assertEqual(c.calls, [])
        self.b.output_test_active = True
        with self.assertRaises(RuntimeError):
            self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [])

    def test_work_offsets_are_applied_to_soft_limits(self):
        self.s.g5x_offset = (95, 0, 0)
        with self.assertRaisesRegex(RuntimeError, 'X .* exceeds'):
            self.b.run_program(self.path)
        self.assertEqual(self.c.calls, [])

    def test_load_failure_aborts_and_restores_manual(self):
        self.c.results = [1, -1]
        with self.assertRaisesRegex(RuntimeError, 'load failed'):
            self.b.run_program(self.path)
        self.assertNotIn(('auto', (0, 0)), self.c.calls)
        self.assertEqual(self.c.calls[-2:], [('abort', ()), ('mode', (1,))])
        self.assertFalse(self.b.program_running)

    def test_health_rechecked_after_load(self):
        checks = iter([True, False])
        self.b.healthy = lambda: next(checks)
        with self.assertRaisesRegex(RuntimeError, 'conditions changed'):
            self.b.run_program(self.path)
        self.assertNotIn(('auto', (0, 0)), self.c.calls)

    def test_stop_aborts_and_stops_spindle(self):
        self.b.run_program(self.path)
        self.b.stop()
        self.assertEqual(self.c.calls[-4:], [('abort', ()), ('spindle', (0,)),
                                           ('wait_complete', (1,)), ('mode', (1,))])
        self.assertFalse(self.b.program_running)

    def test_completion_and_fault(self):
        self.b.run_program(self.path)
        self.s.interp_state = 2
        self.b.snapshot()
        self.s.interp_state = 1
        self.b.snapshot()
        self.assertFalse(self.b.program_running)
        self.assertEqual(self.c.calls[-1], ('mode', (1,)))
        self.b.run_program(self.path)
        self.b.healthy = lambda: False
        self.b.snapshot()
        self.assertFalse(self.b.program_running)
        self.assertIn(('spindle', (0,)), self.c.calls)


if __name__ == "__main__":
    unittest.main()
