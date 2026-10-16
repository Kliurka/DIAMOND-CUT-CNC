"""Persistent output tests across tab/window switches, with explicit/fault stops."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from mesa_io import MesaIOPanel
from test_linuxcnc_control import make_backend


class MesaTestSessionUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend, self.status, self.commands = make_backend()
        self.backend.api.SPINDLE_FORWARD = 1
        self.values = {}
        self.panel = MesaIOPanel(lambda pin: self.values.get(pin, 0),
            writer=lambda pin, value: self.values.__setitem__(pin, value == 'true'),
            allow_bench=False, backend=self.backend)
        self.panel.timer.stop()
        self.addCleanup(self.panel.close)
        self.addCleanup(self.panel.shutdown)
        self.confirm = patch.object(self.panel, 'confirm_on', return_value=True).start()
        self.addCleanup(patch.stopall)

    def test_no_password_and_tab_or_window_switch_does_not_stop_spindle(self):
        self.assertFalse(hasattr(self.panel, 'password'))
        self.panel.show()
        self.app.processEvents()
        self.panel.unlock_test()
        self.panel.start_spindle_test()
        self.assertTrue(self.panel.test.active)
        self.commands.calls.clear()
        self.panel.application_state_changed(Qt.ApplicationInactive)
        self.panel.hide()
        self.app.processEvents()
        for _ in range(20):
            self.panel.refresh()
        self.assertTrue(self.panel.test.active)
        self.assertFalse(any(name == 'spindle' for name, args in self.commands.calls))
        self.panel.stop_spindle_test()
        self.assertIn(('spindle', (0, 0, 0)), self.commands.calls)

    def test_fault_and_explicit_shutdown_still_stop_spindle(self):
        self.panel.unlock_test()
        self.panel.start_spindle_test()
        self.commands.calls.clear()
        self.backend.healthy = lambda: False
        self.panel.refresh()
        self.assertFalse(self.panel.test.active)
        self.assertIn(('spindle', (0, 0, 0)), self.commands.calls)
        self.backend.healthy = lambda: True
        self.panel.unlock_test()
        self.panel.start_spindle_test()
        self.commands.calls.clear()
        self.panel.shutdown()
        self.assertFalse(self.panel.test.active)
        self.assertIn(('spindle', (0, 0, 0)), self.commands.calls)
