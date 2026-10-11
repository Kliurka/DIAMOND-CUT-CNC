"""Offscreen button workflow with NML and graph doubles; no machine motion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget
from profile import Sample
from sim_app import Window
from test_linuxcnc_control import make_backend


class Preview(QWidget):
    preview_status = pyqtSignal(str)

    def set_simulated_work_position(self, position):
        self.position = position

    def reset_default_view(self):
        pass

    def load_program(self, unused, filename):
        self.filename = filename


class ExecutionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend, self.status, self.commands = make_backend()
        self.status.homed = (1, 0, 1)
        self.window = Window(Preview, self.backend)
        self.window.machine_timer.stop()
        self.window.loaded_profile = [Sample(0, 1, 0), Sample(10, 1.1, 10)]
        self.warning = patch('sim_app.QMessageBox.warning').start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.window.close)
        self.addCleanup(self.window.shutdown)

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
