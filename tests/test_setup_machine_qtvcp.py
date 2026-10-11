import tempfile
from pathlib import Path
import unittest
from tools.setup_machine_qtvcp import setup, values


SOURCE = """[DISPLAY]
DISPLAY = axis
[KINS]
JOINTS = 3
KINEMATICS = trivkins coordinates=XYZ
[TRAJ]
COORDINATES = XYZ
LINEAR_UNITS = mm
[HAL]
HALFILE = original.hal
HALFILE = custom.hal
[EMCMOT]
SERVO_PERIOD = 10000000
[AXIS_X]
MAX_VELOCITY = 1.5
[AXIS_Y]
MAX_VELOCITY = 1.5
[AXIS_Z]
MAX_VELOCITY = 1.5
[JOINT_0]
P = 100
STEP_SCALE = 320
"""


class SetupTests(unittest.TestCase):
    def test_source_preserved_shared_hal_and_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            (repo / "qtvcp").mkdir(parents=True)
            for name in ("diamondcut.ui", "diamondcut_handler.py"):
                (repo / "qtvcp" / name).write_text("test")
            (repo / "linuxcnc_control.py").write_text("test")
            config = root / "config"
            config.mkdir()
            source = config / "machine.ini"
            source.write_text(SOURCE)
            hal = config / "original.hal"
            hal.write_text("unchanged HAL")
            dest = setup(source, repo)
            self.assertEqual(source.read_text(), SOURCE)
            self.assertEqual(hal.read_text(), "unchanged HAL")
            data = values(dest.read_text())
            self.assertEqual(data["DIAMONDCUT", "MOTION"], "linuxcnc")
            self.assertEqual(data["DISPLAY", "DISPLAY"], "qtvcp diamondcut")
            self.assertEqual(data["DISPLAY", "LATHE"], "1")
            self.assertEqual(data["DISPLAY", "GEOMETRY"], "XZ")
            self.assertEqual(data["JOINT_0", "P"], "100")
            self.assertIn("HALFILE = original.hal\nHALFILE = custom.hal", dest.read_text())
            self.assertEqual((config / "diamondcut_handler.py").resolve(), repo / "qtvcp/diamondcut_handler.py")
            source.write_text(SOURCE.replace("STEP_SCALE = 320", "STEP_SCALE = 640"))
            setup(source, repo)
            self.assertEqual(values(dest.read_text())["JOINT_0", "STEP_SCALE"], "640")


if __name__ == "__main__":
    unittest.main()
