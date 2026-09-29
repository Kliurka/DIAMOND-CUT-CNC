"""QtVCP screen wrapper. Motion controls inside sim_app remain simulated."""
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

        self.panel = Window(native_preview_factory=self.make_graphics)
        self.panel.setWindowFlags(Qt.Widget)
        self.w.screenHost.layout().addWidget(self.panel)
        self.panel.show()

    def make_graphics(self, parent):
        widget = GCodeGraphics(parent)
        widget.setObjectName("diamondcut_gcode")
        # QtVCP injects its screen context into HAL widgets before initialized__.
        # Register this dynamically created graphics widget through the supported path.
        widget.hal_init(HAL_NAME="diamondcut_gcode")
        return widget


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
