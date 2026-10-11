import json
import tempfile
from pathlib import Path
import unittest
from machine_settings import FILENAME, read_saved_limits, save_limits, validate_limits
from tools.setup_machine_qtvcp import setup, values
from test_linuxcnc_control import make_backend
from test_setup_machine_qtvcp import SOURCE


class LimitSettingsTests(unittest.TestCase):
    limits = {'X': (-1.01, 300), 'Y': (-.01, 200), 'Z': (-1.01, 100)}

    def test_save_and_pncconf_regeneration_preserve_limits_and_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ini = root / 'diamondcut-control.ini'
            ini.write_text(SOURCE)
            save_limits(ini, self.limits)
            data = values(ini.read_text())
            for i, axis in enumerate('XYZ'):
                self.assertEqual(float(data['AXIS_' + axis, 'MAX_LIMIT']), self.limits[axis][1])
                self.assertEqual(data['AXIS_' + axis, 'MAX_LIMIT'], data['JOINT_' + str(i), 'MAX_LIMIT'])
                self.assertEqual(data['AXIS_' + axis, 'MIN_LIMIT'], data['JOINT_' + str(i), 'MIN_LIMIT'])
            self.assertEqual(ini.with_suffix('.ini.limits-backup').read_text(), SOURCE)
            self.assertEqual(read_saved_limits(root), self.limits)
            repo = root / 'repo'
            (repo / 'qtvcp').mkdir(parents=True)
            for name in ('diamondcut.ui', 'diamondcut_handler.py'):
                (repo / 'qtvcp' / name).write_text('test')
            (repo / 'linuxcnc_control.py').write_text('test')
            source = root / 'machine.ini'
            source.write_text(SOURCE)
            setup(source, repo)
            self.assertEqual(source.read_text(), SOURCE)
            self.assertEqual(float(values(ini.read_text())['AXIS_X', 'MAX_LIMIT']), 300)

    def test_invalid_limits_leave_files_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            ini = Path(folder) / 'control.ini'
            ini.write_text(SOURCE)
            for pair in [(2, 1), (0, float('inf')), (0, float('nan'))]:
                with self.assertRaises(ValueError):
                    save_limits(ini, dict(self.limits, X=pair))
                self.assertEqual(ini.read_text(), SOURCE)
            self.assertFalse((ini.parent / FILENAME).exists())

    def test_machine_off_required_and_run_blocked_until_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            ini = Path(folder) / 'control.ini'
            ini.write_text(SOURCE)
            backend, stat, commands = make_backend()
            backend.ini_path = ini
            with self.assertRaisesRegex(RuntimeError, 'Machine OFF'):
                backend.save_coordinate_limits(self.limits)
            self.assertEqual(ini.read_text(), SOURCE)
            stat.task_state = backend.api.STATE_OFF
            backend.save_coordinate_limits(self.limits)
            self.assertTrue(backend.limits_pending)
            self.assertEqual(commands.calls, [])
            with self.assertRaisesRegex(RuntimeError, 'Restart LinuxCNC'):
                backend.run_program(ini)
            self.assertEqual(backend.coordinate_limits()['X'], (-100, 100))
