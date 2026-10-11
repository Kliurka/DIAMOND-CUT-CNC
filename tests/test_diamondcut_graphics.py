"""Preview projection and Qt overlay integration without CNC hardware."""
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PyQt5.QtWidgets import QApplication, QWidget
except ImportError:
    QWidget = None


@unittest.skipIf(QWidget is None, 'PyQt5 unavailable')
class GraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.gl = MagicMock()
        class GraphicsBase(QWidget):
            def setBackgroundColor(self, color):
                self.background = color
            def paintGL(self):
                # Native QtVCP catches rendering errors and returns early.
                self.native_painted = True
        spec = importlib.util.spec_from_file_location(
            'graphics_under_test', Path(__file__).resolve().parents[1] / 'diamondcut_graphics.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
                'OpenGL': SimpleNamespace(GL=self.gl),
                'qtvcp.widgets.gcode_graphics': SimpleNamespace(GCodeGraphics=GraphicsBase)}):
            spec.loader.exec_module(module)
        self.widget = module.DiamondCutGraphics()
        self.widget.resize(400, 300)
        self.widget.stat = SimpleNamespace(g5x_offset=(25.4, 0, 50.8),
                                           g92_offset=(0, 0, 0), rotation_xy=0,
                                           actual_position=(0, 0, 0), tool_offset=(0, 0, 0),
                                           linear_units=1, poll=MagicMock())
        self.widget.to_internal_units = lambda p: tuple(v / 25.4 for v in p)
        self.widget.extents_info = lambda: ((4, 0, 6), (2, 0, 2))
        self.widget.distance = 4
        self.widget.winfo_width = lambda:400
        self.widget.winfo_height = lambda:300

    def tearDown(self):
        self.widget.close()

    def test_work_origin_tracks_touch_off_and_rotated_g92(self):
        self.assertEqual(self.widget.work_origin(), (1, 0, 2))
        self.widget.stat.g5x_offset = (0, 0, 0)
        self.assertEqual(self.widget.work_origin(), (0, 0, 0))
        self.widget.stat.g92_offset = (25.4, 50.8, 76.2)
        self.widget.stat.rotation_xy = 90
        x,y,z = self.widget.work_origin()
        self.assertAlmostEqual(x, -2)
        self.assertAlmostEqual(y, 1)
        self.assertAlmostEqual(z, 3)

    def test_default_view_fits_home_origin_and_actual_tool(self):
        self.widget.stat.actual_position = (254, 0, 254)
        self.widget.reset = MagicMock()
        self.widget.set_eyepoint_from_extents = MagicMock()
        self.widget._redraw = MagicMock()
        self.widget.set_view_y()
        self.gl.glRotatef.assert_called_once_with(90, 1, 0, 0)
        self.gl.glTranslatef.assert_called_once_with(-5, 0, -5)
        self.widget.set_eyepoint_from_extents.assert_called_once_with(12, 12)
        self.assertFalse(self.widget.perspective)

    def test_native_paint_early_return_still_updates_overlay_and_coordinates(self):
        matrix = ((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1))
        self.gl.glGetDoublev.return_value = matrix
        self.widget.stat.actual_position = (50.8, 0, 76.2)
        self.widget.stat.tool_offset = (25.4, 0, 0)
        self.widget.paintGL()
        self.assertTrue(self.widget.native_painted)
        self.assertIn('X +0.000   Z +25.400 mm', self.widget.markers.caption)
        self.assertGreater(self.widget.markers.origin[0], 200)
        self.assertGreater(self.widget.markers.origin[1], 150)
        self.assertGreater(self.widget.markers.tip[1], self.widget.markers.origin[1])
        self.widget.stat.g5x_offset = (0,0,0)
        self.widget.paintGL()
        self.assertEqual(self.widget.markers.origin, (200, 150))

    def test_qt_overlay_draws_cyan_origin_and_yellow_tool(self):
        self.widget.markers.setGeometry(0,0,400,300)
        self.widget.markers.origin = (100,150)
        self.widget.markers.tip = (280,200)
        self.widget.markers.caption = 'Tool Work: X +1.000 Z +2.000 mm'
        self.widget.show()
        self.app.processEvents()
        image = self.widget.markers.grab().toImage()
        cyan=yellow=0
        for y in range(image.height()):
            for x in range(image.width()):
                color=image.pixelColor(x,y)
                cyan += color.red()<30 and color.green()>220 and color.blue()>220
                yellow += color.red()>220 and color.green()>190 and color.blue()<60
        self.assertGreater(cyan,50)
        self.assertGreater(yellow,50)


if __name__ == '__main__':
    unittest.main()
