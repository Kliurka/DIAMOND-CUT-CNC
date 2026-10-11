"""Check preview transforms without requiring a running CNC or GL context."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class GraphicsTests(unittest.TestCase):
    def setUp(self):
        self.gl = MagicMock()
        class GraphicsBase:
            def __init__(self, parent=None):
                pass
            def setBackgroundColor(self, color):
                self.background = color
        modules = {"OpenGL": SimpleNamespace(GL=self.gl),
                   "qtvcp.widgets.gcode_graphics": SimpleNamespace(GCodeGraphics=GraphicsBase)}
        spec = importlib.util.spec_from_file_location(
            "graphics_under_test", Path(__file__).resolve().parents[1] / "diamondcut_graphics.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        self.widget = module.DiamondCutGraphics()
        self.widget.stat = SimpleNamespace(g5x_offset=(25.4, 0, 50.8),
                                           g92_offset=(0, 0, 0), rotation_xy=0,
                                           poll=MagicMock())
        self.widget.stat.actual_position = (0, 0, 0)
        self.widget.stat.tool_offset = (0, 0, 0)
        self.widget.distance = 4
        self.widget.winfo_width = lambda: 400
        self.widget.to_internal_units = lambda values: tuple(v / 25.4 for v in values)
        self.widget.extents_info = lambda: ((4, 0, 6), (2, 0, 2))

    def test_work_origin_tracks_touch_off_and_rotated_g92(self):
        self.assertEqual(self.widget.work_origin(), (1, 0, 2))
        self.widget.stat.g5x_offset = (0, 0, 0)
        self.assertEqual(self.widget.work_origin(), (0, 0, 0))
        self.widget.stat.g92_offset = (25.4, 50.8, 76.2)
        self.widget.stat.rotation_xy = 90
        origin = self.widget.work_origin()
        self.assertAlmostEqual(origin[0], -2)
        self.assertAlmostEqual(origin[1], 1)
        self.assertAlmostEqual(origin[2], 3)

    def test_default_view_fits_home_and_work_origin_and_points_z_down(self):
        self.widget.reset = MagicMock()
        self.widget.set_eyepoint_from_extents = MagicMock()
        self.widget._redraw = MagicMock()
        self.widget.set_view_y()
        # Rx(+90): X -> screen +X, Z -> screen -Y; Y projects into depth.
        self.gl.glRotatef.assert_called_once_with(90, 1, 0, 0)
        self.gl.glTranslatef.assert_called_once_with(-2.5, 0, -3.5)
        self.widget.set_eyepoint_from_extents.assert_called_once_with(6, 8.4)
        self.assertFalse(self.widget.perspective)
        self.assertIsNone(self.widget.get_current_tool())

    def test_origin_marker_is_drawn_even_without_coordinate_offsets(self):
        self.widget.hershey = MagicMock()
        self.widget.stat.g5x_offset = (0, 0, 0)
        self.widget.draw_markers()
        self.gl.glTranslatef.assert_any_call(0, 0, 0)
        self.widget.hershey.plot_string.assert_called_once_with("Work 0", 0.1)
        self.widget.stat.g5x_offset = (25.4, 0, 50.8)
        self.widget.draw_markers()
        self.gl.glTranslatef.assert_any_call(1, 0, 2)

    def test_tool_marker_uses_actual_position_and_tool_offset(self):
        self.widget.hershey = MagicMock()
        self.widget.stat.actual_position = (254, 50.8, 127)
        self.widget.stat.tool_offset = (25.4, 0, 50.8)
        self.assertEqual(self.widget.tool_tip(), (9, 2, 3))
        self.widget.draw_markers()
        self.gl.glVertex3f.assert_any_call(9, 2, 3)
        self.gl.glDisable.assert_any_call(self.gl.GL_BLEND)
        self.gl.glDisable.assert_any_call(self.gl.GL_DEPTH_TEST)
        self.assertFalse(self.widget.get_show_tool())

    def test_reset_view_includes_tool_outside_program_extents(self):
        self.widget.stat.actual_position = (254, 0, 254)
        self.widget.reset = MagicMock()
        self.widget.set_eyepoint_from_extents = MagicMock()
        self.widget._redraw = MagicMock()
        self.widget.set_view_y()
        self.gl.glTranslatef.assert_called_once_with(-5, 0, -5)
        self.widget.set_eyepoint_from_extents.assert_called_once_with(12, 12)


if __name__ == "__main__":
    unittest.main()
