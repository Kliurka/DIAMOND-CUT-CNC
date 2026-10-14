"""Offscreen button workflow with NML and graph doubles; no machine motion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt5.QtCore import pyqtSignal, Qt, QSettings
from PyQt5.QtWidgets import QApplication, QWidget
from profile import Sample
from sim_app import Window
from test_linuxcnc_control import make_backend


class Preview(QWidget):
    preview_status = pyqtSignal(str)
    program_line_selected = pyqtSignal(int)

    def highlight_program_line(self, line):
        self.highlighted_line = line

    def set_simulated_work_position(self, position):
        self.position = position

    def refresh_work_coordinates(self):
        pass

    def reset_default_view(self):
        pass

    def load_program(self, unused, filename):
        self.filename = filename


class ExecutionUITests(unittest.TestCase):
    def test_independent_pass_modes_directions_and_feed_units(self):
        table = self.window.pass_table
        table.cellWidget(1, 5).setCurrentIndex(1)
        table.cellWidget(1, 6).setCurrentIndex(1)
        table.item(1, 2).setText('0.05')
        self.window.feed.setValue(60)
        rows = self.window.read_pass_rows()
        self.assertFalse(rows[0].use_css)
        self.assertEqual(rows[0].feed, 60)
        self.assertTrue(rows[1].use_css)
        self.assertEqual(rows[1].feed, .05)
        self.assertEqual(rows[1].cut_direction, 'center_to_outer')
        self.assertTrue(self.window.generate())
        self.assertIn('G96', self.window.code.toPlainText())
        self.window.run_gcode()
        self.assertFalse(self.backend.program_running)

    def test_keyboard_opens_for_touch_but_not_mouse(self):
        from PyQt5.QtCore import QEvent
        from PyQt5.QtWidgets import QLineEdit
        from unittest.mock import Mock
        keyboard = self.window.touch_keyboard
        field = self.window.feed.findChild(QLineEdit)
        mouse = QEvent(QEvent.MouseButtonPress)
        self.assertFalse(keyboard.eventFilter(field, mouse))
        touch = Mock()
        touch.type.return_value = QEvent.TouchBegin
        with patch('touch_keyboard.QTimer.singleShot') as schedule:
            self.assertTrue(keyboard.eventFilter(field, touch))
            self.assertTrue(schedule.called)
            touch.accept.assert_called_once()
        keyboard.busy = False

    def test_touch_keypad_accepts_decimal_comma_and_cancel_preserves_value(self):
        from PyQt5.QtWidgets import QDialog, QLineEdit
        keyboard = self.window.touch_keyboard
        field = self.window.feed.findChild(QLineEdit)
        def accept(dialog):
            dialog.findChild(QLineEdit).setText('12,5')
            return QDialog.Accepted
        with patch('touch_keyboard.QDialog.exec_', accept):
            keyboard.open_target(field)
        self.assertEqual(self.window.feed.value(), 12.5)
        with patch('touch_keyboard.QDialog.exec_', return_value=QDialog.Rejected):
            keyboard.open_target(field)
        self.assertEqual(self.window.feed.value(), 12.5)
        self.assertFalse(keyboard.busy)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend, self.status, self.commands = make_backend()
        self.status.homed = (1, 0, 1)
        self.status.tool_offset = (0, 0, 0)
        self.backend.x_center_reference = self.backend.center_signature()
        self.settings_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.settings_folder.cleanup)
        self.settings = QSettings(str(Path(self.settings_folder.name) / 'prefs.ini'), QSettings.IniFormat)
        self.window = Window(Preview, self.backend, self.settings)
        self.window.machine_timer.stop()
        self.window.loaded_profile = [Sample(0, 1, -20, 'spindle_center'), Sample(10, 1.1, -10, 'spindle_center')]
        self.warning = patch('sim_app.QMessageBox.warning').start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.window.close)
        self.addCleanup(self.window.shutdown)

    def test_old_edge_zero_csv_is_rejected_by_screen_generator(self):
        self.window.loaded_profile = [Sample(0, 1, 0), Sample(10, 1.1, 10)]
        self.assertFalse(self.window.generate())
        self.assertTrue(self.warning.called)
        self.assertEqual(self.commands.calls, [])

    def test_centered_css_ui_simulates_without_feedback_and_blocks_real_run(self):
        self.window.scan_start_x.setValue(-100)
        self.window.scan_end_x.setValue(-50)
        self.window.scan()
        self.window.loaded_profile = self.window.raw
        self.window.mode.setCurrentIndex(1)
        self.assertEqual(self.window.feed.value(), .1)
        self.assertEqual(self.window.feed_label.text(), 'Feed (mm/rev)')
        self.assertTrue(self.window.generate())
        self.assertIn('G96 D1200', self.window.code.toPlainText())
        self.assertIn('G95', self.window.code.toPlainText())
        self.window.simulate_gcode()
        self.assertIsNotNone(self.window.playback)
        self.assertEqual(self.commands.calls, [])
        self.window.stop_simulation()
        self.window.run_gcode()
        self.assertFalse(self.backend.program_running)
        self.assertFalse(any(name == 'auto' for name, _ in self.commands.calls))

    def test_radius_button_changes_work_reference_but_not_homing(self):
        self.window.known_radius.setValue(25)
        self.window.zero_buttons[0].click()
        self.assertIn(('mdi', ('G21 G49 G10 L20 P0 X-25.000000',)), self.commands.calls)
        self.assertEqual(self.window.zero_buttons[0].text(), 'R')
        self.assertFalse(any(name == 'home' for name, _ in self.commands.calls))

    def test_open_saved_gcode_simulates_and_runs_without_regenerating(self):
        from test_linuxcnc_control import ProgramTests
        path = Path(self.settings_folder.name) / 'saved.ngc'
        path.write_text(ProgramTests.code)
        self.window.loaded_profile = []
        with patch('sim_app.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            self.window.open_gcode_button.click()
        self.assertEqual(self.window.code.toPlainText(), ProgramTests.code)
        self.assertEqual(self.window.opened_gcode, path)
        self.assertEqual(self.commands.calls, [])
        self.window.simulate_gcode()
        self.assertIsNotNone(self.window.playback)
        self.assertEqual(self.commands.calls, [])
        self.window.stop_simulation()
        self.window.run_gcode()
        self.assertTrue(self.backend.program_running)
        filename = next(args[0] for name, args in self.commands.calls if name == 'program_open')
        self.assertEqual(Path(filename).read_text(), ProgramTests.code)
        self.assertFalse(self.warning.called)

    def test_open_failure_preserves_current_code_and_reset_button_calls_graph(self):
        self.window.generate()
        old = self.window.code.toPlainText()
        with patch('sim_app.QFileDialog.getOpenFileName', return_value=('/missing/file.ngc', '')):
            self.window.open_gcode()
        self.assertEqual(self.window.code.toPlainText(), old)
        self.assertIsNone(self.window.opened_gcode)
        with patch.object(self.window.native_widget, 'reset_default_view') as reset:
            self.window.reset_view_button.click()
            reset.assert_called_once()

    def test_ctrl_uses_axis_rapid_and_switches_back_while_held(self):
        self.window.continuous.setChecked(True)
        self.window.jog_speed.setValue(12)
        self.window.rapid_speed['X'].setValue(60)
        with patch('sim_app.QApplication.keyboardModifiers', return_value=Qt.NoModifier):
            self.window.jog_pressed('X', 1)
        self.assertEqual(self.commands.calls[-1], ('jog', (1, True, 0, .2)))
        with patch('sim_app.QApplication.keyboardModifiers', return_value=Qt.ControlModifier):
            self.window.refresh_machine()
        self.assertEqual(self.commands.calls[-1], ('jog', (1, True, 0, 1)))
        with patch('sim_app.QApplication.keyboardModifiers', return_value=Qt.NoModifier):
            self.window.refresh_machine()
        self.assertEqual(self.commands.calls[-1], ('jog', (1, True, 0, .2)))
        self.window.jog_released()
        self.assertEqual(self.commands.calls[-1], ('jog', (0, True, 0)))
        self.assertIsNone(self.window.held_jog)

    def test_ctrl_increment_keeps_distance_and_y_is_independent(self):
        self.window.continuous.setChecked(False)
        self.window.rapid_speed['Z'].setValue(60)
        with patch('sim_app.QApplication.keyboardModifiers', return_value=Qt.ControlModifier):
            self.window.jog_pressed('Z', -1)
        self.assertEqual(self.commands.calls[-1], ('jog', (2, True, 2, -1, 1)))
        self.assertIsNone(self.window.held_jog)
        self.window.jog_speed.setValue(12)
        self.window.table_speed.setValue(42)
        self.window.table_pressed(1)
        self.assertEqual(self.commands.calls[-1], ('jog', (1, True, 1, .7)))
        self.window.table_released()
        self.window.jog_speed.setValue(24)
        self.window.table_pressed(-1)
        self.assertEqual(self.commands.calls[-1], ('jog', (1, True, 1, -.7)))
        self.assertEqual(float(self.settings.value('table_speed')), 42)

    def test_number_gutter_toggle_preserves_text_and_selected_line(self):
        self.window.generate()
        text = self.window.code.toPlainText()
        self.window.show_program_line(12)
        self.assertGreater(self.window.code.number_width(), 0)
        self.window.show_code_numbers.setChecked(False)
        self.assertEqual(self.window.code.number_width(), 0)
        self.assertEqual(self.window.code.toPlainText(), text)
        self.assertEqual(self.window.selected_code_line, (12, False))
        self.assertFalse(self.settings.value('show_code_numbers', True, type=bool))
        self.window.show_code_numbers.setChecked(True)
        self.assertGreater(self.window.code.number_width(), 0)

    def test_graphic_selection_scrolls_text_without_commands(self):
        self.window.code.setPlainText('\n'.join(f'G1 X{i} Z0' for i in range(300)))
        self.window.centralWidget().widget(1).setCurrentIndex(1)
        self.window.show()
        self.app.processEvents()
        self.window.native_widget.program_line_selected.emit(250)
        self.assertEqual(self.window.code.textCursor().blockNumber(), 249)
        self.assertEqual(self.window.selected_code_line, (250, False))
        self.assertGreater(self.window.code.verticalScrollBar().value(), 0)
        self.assertEqual(len(self.window.code.extraSelections()), 1)
        self.assertEqual(self.commands.calls, [])
        self.window.native_widget.program_line_selected.emit(-1)
        self.assertEqual(self.window.selected_code_line, (250, False))

    def test_text_selection_highlights_matching_segment(self):
        self.window.generate()
        from PyQt5.QtGui import QTextCursor
        self.window.code.setTextCursor(QTextCursor(self.window.code.document().findBlockByNumber(10)))
        self.assertEqual(self.window.native_widget.highlighted_line, 11)
        self.assertEqual(self.window.selected_code_line, (11, False))
        self.assertEqual(self.commands.calls, [])

    def test_run_follows_motion_line_and_clears_executing_state_when_stopped(self):
        self.window.run_gcode()
        self.status.interp_state = 2
        self.status.motion_line = 12
        self.window.refresh_machine()
        self.assertEqual(self.window.selected_code_line, (12, True))
        self.assertEqual(self.window.code.textCursor().blockNumber(), 11)
        self.assertEqual(self.window.native_widget.highlighted_line, 12)
        self.window.native_widget.program_line_selected.emit(8)
        self.assertEqual(self.window.selected_code_line, (12, True))
        self.status.motion_line = 13
        self.window.refresh_machine()
        self.assertEqual(self.window.selected_code_line, (13, True))
        self.window.stop_execution()
        self.assertEqual(self.window.selected_code_line, (13, False))

    def test_pass_count_in_settings_rebuilds_rows_without_control_buttons(self):
        tabs = self.window.centralWidget().widget(1)
        self.assertTrue(tabs.widget(2).isAncestorOf(self.window.passes))
        from PyQt5.QtWidgets import QPushButton
        texts = [button.text() for button in self.window.findChildren(QPushButton)]
        for text in ('Create pass rows', 'Add pass', 'Remove selected pass'):
            self.assertNotIn(text, texts)
        self.window.passes.setValue(2)
        self.window.depth.setValue(.02)
        self.assertEqual(self.window.pass_table.rowCount(), 2)
        self.assertEqual([p.depth_mm for p in self.window.read_pass_rows()], [.01, .02])
        self.window.feed.setValue(77)
        self.assertEqual([p.feed for p in self.window.read_pass_rows()], [77, 77])
        self.window.pass_table.item(0, 1).setText('0.005')
        self.assertEqual(self.window.read_pass_rows()[0].depth_mm, .005)

    def test_simulate_is_graph_only_and_blocks_table_keyboard_jog(self):
        self.window.simulate_button.click()
        self.assertIsNotNone(self.window.playback)
        self.assertEqual(self.commands.calls, [])
        self.window.table_pressed(1)
        self.window.jog_pressed('X', 1)
        self.assertEqual(self.commands.calls, [])
        self.window.playback_time -= 10000
        self.window.playback_tick()
        self.assertIsNone(self.window.playback)
        self.assertIsNone(self.window.native_widget.position)
        self.assertEqual(self.commands.calls, [])
        self.assertFalse(self.warning.called)

    def test_run_button_starts_whole_program_and_stop_aborts(self):
        self.window.run_button.click()
        self.assertTrue(self.backend.program_running)
        self.assertEqual(self.commands.calls[-1], ('auto', (0, 0)))
        filename = next(args[0] for name, args in self.commands.calls if name == 'program_open')
        self.assertEqual(Path(filename).read_text(), self.window.code.toPlainText())
        self.assertIn('M3', Path(filename).read_text())
        self.assertIn('M5', Path(filename).read_text())
        self.assertFalse(self.window.simulate_button.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in self.window.table_buttons))
        self.window.stop_execution()
        self.assertFalse(self.backend.program_running)
        self.assertIn(('abort', ()), self.commands.calls)
        self.assertIn(('spindle', (0,)), self.commands.calls)
        self.assertFalse(self.warning.called)

    def test_stop_clears_graph_simulation(self):
        self.window.simulate_gcode()
        self.window.stop_execution()
        self.assertIsNone(self.window.playback)
        self.assertIsNone(self.window.native_widget.position)
