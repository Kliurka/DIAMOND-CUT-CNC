import tempfile
import unittest
from pathlib import Path

from tools.setup_qtvcp_preview import setup


class PreviewSetupTest(unittest.TestCase):
    def test_copies_simulation_without_changing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "axis-sim"
            source_dir.mkdir()
            source = source_dir / "axis.ini"
            original = "[EMC]\nMACHINE = Example\n[DISPLAY]\nDISPLAY = axis\nGEOMETRY = XYZ\nOTHER = keep\n[HAL]\nHALFILE = axis.hal\n"
            source.write_text(original)
            (source_dir / "axis.hal").write_text("# original\n")
            repo = root / "repo" / "qtvcp"
            repo.mkdir(parents=True)
            for name in ("diamondcut.ui", "diamondcut_handler.py"):
                (repo / name).write_text("sample")
            dest = root / "diamondcut-preview"

            ini = setup(source, dest, repo.parent)

            self.assertEqual(source.read_text(), original)
            self.assertEqual((dest / "axis.hal").read_text(), "# original\n")
            self.assertIn("DISPLAY = qtvcp diamondcut", ini.read_text())
            self.assertIn("LATHE = 1", ini.read_text())
            self.assertIn("GEOMETRY = XZ", ini.read_text())
            self.assertIn("OTHER = keep", ini.read_text())
            self.assertEqual((dest / "diamondcut.ui").resolve(), repo / "diamondcut.ui")
            with self.assertRaisesRegex(ValueError, "already exists"):
                setup(source, dest, repo.parent)


if __name__ == "__main__":
    unittest.main()
