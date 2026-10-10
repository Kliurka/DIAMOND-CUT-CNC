"""QtVCP wrapper with explicitly selected simulation or LinuxCNC control."""
import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from qtvcp.widgets.gcode_graphics import GCodeGraphics


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.hal = halcomp
        self.w = widgets
        self.paths = paths
        self.panel = None

    def initialized__(self):
        # The config directory contains symlinks to this handler and its UI.
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from sim_app import Window
        import hal
        import linuxcnc
        from mesa_io import MesaIOPanel, read_snapshot
        ini = linuxcnc.ini(os.environ["INI_FILE_NAME"])
        real = (ini.find("DIAMONDCUT", "MOTION") or "simulation").lower() == "linuxcnc"
        backend = None
        if real:
            from linuxcnc_control import LinuxCNCControl
            backend = LinuxCNCControl(linuxcnc, ini, lambda: read_snapshot(hal.get_value)["healthy"])
        self.panel = Window(native_preview_factory=self.make_graphics, machine_backend=backend)
        self.panel.setWindowFlags(Qt.Widget)
        self.w.screenHost.layout().addWidget(self.panel)
        self.panel.show()
        self.mesa_panel = MesaIOPanel(hal.get_value, self.panel,
                                     writer=None if real else hal.set_p, allow_bench=not real)
        tabs = self.panel.centralWidget().widget(1)
        tabs.addTab(self.mesa_panel, "4. Mesa I/O")
        if not real:
            self.panel.statusBar().showMessage("Axis controls and laser scan simulated — real bench controls in Mesa I/O")

    def make_graphics(self, parent):
        widget = GCodeGraphics(parent)
        widget.setObjectName("diamondcut_gcode")
        # QtVCP injects its screen context into HAL widgets before initialized__.
        # Register this dynamically created graphics widget through the supported path.
        widget.hal_init(HAL_NAME="diamondcut_gcode")
        return widget

    def closing_cleanup__(self):
        try:
            if self.panel is not None:
                self.panel.shutdown()
        finally:
            if hasattr(self, "mesa_panel"):
                self.mesa_panel.shutdown()


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]

