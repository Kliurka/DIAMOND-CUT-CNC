"""Preview projection and frame clearing integration without CNC hardware."""
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
            def update_highlight_variable(self, line):
                self.highlight_line = line
                self._block_line_selected = False
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
        self.widget.hershey = MagicMock()
        self.widget.distance = 4
        self.widget.winfo_width = lambda:400
        self.widget.winfo_height = lambda:300

    def tearDown(self):
        self.widget.close()

    def test_native_pick_emits_local_line_signal_but_external_update_does_not(self):
        lines = []
        self.widget.program_line_selected.connect(lines.append)
        self.widget.update_highlight_variable(12)
        self.assertEqual(lines, [12])
        self.widget._block_line_selected = True
        self.widget.update_highlight_variable(15)
        self.assertEqual(lines, [12])
        self.widget.highlight_graphics = lambda line: self.widget.update_highlight_variable(line)
        self.widget.makeCurrent = MagicMock()
        self.widget.doneCurrent = MagicMock()
        self.widget.updateGL = MagicMock()
        self.widget.highlight_program_line(20)
        self.assertEqual(self.widget.highlight_line, 20)
        self.assertEqual(lines, [12])
        self.widget.makeCurrent.assert_called_once()
        self.widget.doneCurrent.assert_called_once()
        self.widget.update_highlight_variable(21)
        self.assertEqual(lines, [12, 21])

    def test_simulation_marker_tracks_work_offsets_without_changing_status(self):
        self.widget.updateGL = MagicMock()
        actual = self.widget.stat.actual_position
        self.widget.set_simulated_work_position((25.4, 2.54))
        x, y, z = self.widget.tool_tip()
        self.assertAlmostEqual(x, 2)
        self.assertAlmostEqual(y, 0)
        self.assertAlmostEqual(z, 2.1)
        self.assertEqual(self.widget.stat.actual_position, actual)
        self.widget.set_simulated_work_position(None)
        self.assertEqual(self.widget.tool_tip(), (0, 0, 0))

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

    def test_native_early_return_still_draws_markers_and_reports_position(self):
        matrix = ((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1))
        self.gl.glGetDoublev.return_value = matrix
        self.widget.stat.actual_position = (50.8, 0, 76.2)
        self.widget.stat.tool_offset = (25.4, 0, 0)
        captions = []
        self.widget.preview_status.connect(captions.append)
        self.widget.draw_screen_markers = MagicMock()
        self.widget.paintGL()
        self.assertTrue(self.widget.native_painted)
        self.assertIn('X +0.000   Z +25.400 mm', captions[-1])
        origin,tip = self.widget.draw_screen_markers.call_args.args
        self.assertGreater(origin[0], 200)
        self.assertGreater(origin[1], 150)
        self.assertGreater(tip[1], origin[1])
        self.widget.stat.g5x_offset = (0,0,0)
        self.widget.paintGL()
        self.assertEqual(self.widget.draw_screen_markers.call_args.args[0], (200, 150))

    def test_every_frame_clears_before_native_render_and_markers(self):
        self.gl.glGetDoublev.return_value = ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
        for _ in range(3):
            self.widget.paintGL()
        self.assertEqual(self.gl.glClear.call_count, 3)
        self.assertEqual(self.gl.glColorMask.call_count, 3)
        self.assertEqual(self.widget.findChildren(QWidget), [])
        self.assertEqual(self.widget.hershey.plot_string.call_count, 3)
        # Actual LinuxCNC Hershey repertoire, not a general text font.
        supported = set('0123456789-.XYZGUVW')
        for call in self.widget.hershey.plot_string.call_args_list:
            self.assertTrue(set(call.args[0]) <= supported)

    def test_work_zero_reloads_same_file_after_status_poll_and_resets_view(self):
        self.widget._reload_filename = '/tmp/preview.ngc'
        events = []
        self.widget.stat.poll = lambda: events.append('poll')
        self.widget.clear_live_plotter = lambda: events.append('clear')
        self.widget.load_program = lambda _, path: events.append(path)
        self.widget.reset_default_view = lambda: events.append('view')
        self.widget.refresh_work_coordinates()
        self.assertEqual(events, ['poll', 'clear', '/tmp/preview.ngc', 'view'])
        self.assertFalse(self.widget.get_show_live_plot())

    def test_work_zero_without_program_only_clears_history_and_resets_view(self):
        self.widget._reload_filename = None
        self.widget.clear_live_plotter = MagicMock()
        self.widget.load_program = MagicMock()
        self.widget.reset_default_view = MagicMock()
        self.widget.refresh_work_coordinates()
        self.widget.load_program.assert_not_called()
        self.widget.reset_default_view.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
