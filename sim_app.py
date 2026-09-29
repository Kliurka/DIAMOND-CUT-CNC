"""Desktop-only PyQt5 mock machine and scan/turn workflow."""
import math
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QRadioButton,
    QSpinBox, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from profile import generate_gcode, save_csv, simulated_scan, smooth


class Plot(QWidget):
    def __init__(self):
        super().__init__()
        self.raw, self.filtered = [], []
        self.setMinimumSize(430, 300)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#161e29"))
        bounds = self.rect().adjusted(56, 24, -20, -48)
        painter.setPen(QColor("#8996a7"))
        painter.drawRect(bounds)
        painter.drawText(bounds.left(), self.height() - 12, "Outer edge  →  spindle center (X)")
        if not self.raw:
            painter.drawText(bounds, Qt.AlignCenter, "Run simulated scan")
            return
        points = self.raw + self.filtered
        x_max = max(s.edge_mm for s in points) or 1
        z_min = min(s.z_mm for s in points) - 0.2
        z_max = max(s.z_mm for s in points) + 0.2
        for series, color in ((self.raw, "#f27373"), (self.filtered, "#53bfff")):
            painter.setPen(QPen(QColor(color), 2))
            prev = None
            for sample in series:
                x = bounds.left() + sample.edge_mm / x_max * bounds.width()
                y = bounds.bottom() - (sample.z_mm - z_min) / (z_max - z_min) * bounds.height()
                if prev:
                    painter.drawLine(round(prev[0]), round(prev[1]), round(x), round(y))
                prev = x, y
        painter.setPen(QColor("#f27373"))
        painter.drawText(bounds.left() + 10, bounds.top() + 20, "Raw")
        painter.setPen(QColor("#53bfff"))
        painter.drawText(bounds.left() + 65, bounds.top() + 20, "Smoothed")


def number(value, minimum, maximum, decimals=2, suffix=""):
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Diamond Cut CNC — Simulation")
        self.resize(1280, 790)
        self.raw, self.filtered = [], []
        self.machine = {"X": 0.0, "Z": 0.0, "Y": 0.0}
        self.offset = {"X": 0.0, "Z": 0.0}
        self.estop = True
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.build_controls())
        split.addWidget(self.build_tabs())
        split.setSizes([300, 980])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)
        self.update_dros()
        self.statusBar().showMessage("SIMULATION ONLY — no machine or sensor connected")

    def build_controls(self):
        pane = QWidget()
        pane.setMinimumWidth(240)
        pane.setMaximumWidth(420)
        root = QVBoxLayout(pane)
        root.addWidget(QLabel("<h2>Machine control</h2><b>SIMULATION ONLY</b>"))
        group = QGroupBox("Position (mm)")
        grid = QGridLayout(group)
        for col, label in enumerate(("Axis", "Machine", "Work")):
            grid.addWidget(QLabel(label), 0, col)
        self.dros = {}
        for row, axis in enumerate(("X", "Z", "Y"), 1):
            grid.addWidget(QLabel(axis), row, 0)
            self.dros[axis] = (QLabel(), QLabel())
            grid.addWidget(self.dros[axis][0], row, 1)
            grid.addWidget(self.dros[axis][1], row, 2)
        root.addWidget(group)
        zeros = QHBoxLayout()
        for axis in ("X", "Z"):
            button = QPushButton(f"Zero Work {axis}")
            button.clicked.connect(lambda _=False, a=axis: self.zero(a))
            zeros.addWidget(button)
        root.addLayout(zeros)
        reset = QPushButton("Reset / E-stop")
        reset.clicked.connect(self.toggle_estop)
        root.addWidget(reset)
        self.estop_label = QLabel()
        root.addWidget(self.estop_label)
        machine_home = QPushButton("Home Machine (simulated)")
        machine_home.clicked.connect(self.home_machine)
        root.addWidget(machine_home)
        work_home = QPushButton("Go to Work Home (simulated)")
        work_home.clicked.connect(self.go_work_home)
        root.addWidget(work_home)
        jog = QGroupBox("Jog X / Z")
        layout = QVBoxLayout(jog)
        self.continuous = QCheckBox("Continuous (hold button)")
        layout.addWidget(self.continuous)
        steps = QHBoxLayout()
        self.step_group = QButtonGroup(self)
        for index, value in enumerate((0.01, 0.1, 1, 5, 10)):
            radio = QRadioButton(str(value))
            radio.setProperty("step", value)
            self.step_group.addButton(radio)
            steps.addWidget(radio)
            if index == 2:
                radio.setChecked(True)
        layout.addLayout(steps)
        movement = QGridLayout()
        for row, axis in enumerate(("X", "Z")):
            movement.addWidget(QLabel(axis), row, 0)
            for col, sign in ((1, -1), (2, 1)):
                button = QPushButton(f"{axis}{'+' if sign > 0 else '−'}")
                button.clicked.connect(lambda _=False, a=axis, s=sign: self.jog(a, s))
                movement.addWidget(button, row, col)
        layout.addLayout(movement)
        root.addWidget(jog)
        root.addWidget(QLabel("Y table position is fixed during scan and turning."))
        root.addStretch()
        return pane

    def build_tabs(self):
        tabs = QTabWidget()
        scan = QWidget()
        scan_layout = QVBoxLayout(scan)
        scan_layout.addWidget(QLabel("<h2>Scan</h2>Synthetic laser data, outer edge toward center."))
        self.scan_plot = Plot()
        scan_layout.addWidget(self.scan_plot, 1)
        buttons = QHBoxLayout()
        for label, callback in (("Run simulated scan", self.scan), ("Save raw CSV", self.save_raw)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        scan_layout.addLayout(buttons)
        tabs.addTab(scan, "1. Scan")
        turning = QWidget()
        turn_layout = QVBoxLayout(turning)
        self.turn_plot = Plot()
        turn_layout.addWidget(self.turn_plot, 1)
        fields = QGridLayout()
        self.passes = QSpinBox(); self.passes.setRange(1, 20); self.passes.setValue(4)
        self.depth = number(0.2, 0.001, 20, 3, " mm")
        self.feed = number(0.1, 0.001, 1000, 3)
        self.rpm = QSpinBox(); self.rpm.setRange(1, 10000); self.rpm.setValue(500)
        self.max_rpm = QSpinBox(); self.max_rpm.setRange(1, 10000); self.max_rpm.setValue(1200)
        self.surface_speed = number(150, 0.1, 5000, 1, " m/min")
        self.mode = QComboBox()
        self.mode.addItems(["G97 / G94 (RPM, mm/min)", "G96 / G95 (CSS, mm/rev)"])
        for index, (label, widget) in enumerate((
            ("Passes", self.passes), ("Total depth", self.depth),
            ("Feed (mode dependent)", self.feed), ("Starting RPM", self.rpm),
            ("Max RPM", self.max_rpm), ("Surface speed", self.surface_speed),
            ("Mode", self.mode),
        )):
            fields.addWidget(QLabel(label), index // 4, (index % 4) * 2)
            fields.addWidget(widget, index // 4, (index % 4) * 2 + 1)
        turn_layout.addLayout(fields)
        actions = QHBoxLayout()
        for label, callback in (("Smooth profile", self.filter_scan), ("Generate preview", self.generate), ("Save G-code", self.save_gcode)):
            button = QPushButton(label); button.clicked.connect(callback); actions.addWidget(button)
        turn_layout.addLayout(actions)
        self.code = QTextEdit(); self.code.setReadOnly(True); self.code.setPlaceholderText("Generated preview G-code appears here")
        turn_layout.addWidget(self.code, 1)
        tabs.addTab(turning, "2. Toolpath & Turning")
        settings = QWidget()
        form = QFormLayout(settings)
        self.radius = number(230, 10, 1000, 2, " mm")
        self.scan_step = number(1, 0.1, 20, 2, " mm")
        self.sensor_x = number(0, -1000, 1000, 3, " mm")
        self.sensor_z = number(0, -1000, 1000, 3, " mm")
        self.tool_x = number(0, -1000, 1000, 3, " mm")
        self.tool_z = number(0, -1000, 1000, 3, " mm")
        self.safe_z = number(5, 0.1, 100, 2, " mm")
        self.max_depth = number(0.5, 0.001, 10, 3, " mm")
        self.y_position = number(0, -1000, 1000, 2, " mm")
        for label, widget in (
            ("Rim radius (X0 at spindle center)", self.radius),
            ("Scan step", self.scan_step), ("Sensor X offset", self.sensor_x),
            ("Sensor Z offset", self.sensor_z), ("Tool X offset", self.tool_x),
            ("Tool Z offset", self.tool_z), ("Safe Z clearance", self.safe_z),
            ("Maximum total cut depth", self.max_depth), ("Fixed Y table position", self.y_position),
        ):
            form.addRow(label, widget)
        tabs.addTab(settings, "3. Settings")
        return tabs

    def update_dros(self):
        for axis, (machine, work) in self.dros.items():
            machine.setText(f"{self.machine[axis]:+.4f}")
            work.setText(f"{self.machine[axis] - self.offset.get(axis, 0):+.4f}")
        self.estop_label.setText("RESET REQUIRED" if self.estop else "Simulated control enabled")

    def toggle_estop(self):
        self.estop = not self.estop
        self.update_dros()

    def zero(self, axis):
        if self.estop: return
        self.offset[axis] = self.machine[axis]
        self.update_dros()

    def home_machine(self):
        if self.estop: return
        self.machine.update(X=0.0, Z=0.0, Y=0.0)
        self.update_dros()

    def go_work_home(self):
        if self.estop: return
        self.machine["Z"] = self.offset["Z"] + self.safe_z.value()
        self.machine["X"] = self.offset["X"]
        self.update_dros()

    def jog(self, axis, sign):
        if self.estop: return
        if self.continuous.isChecked():
            QMessageBox.information(self, "Simulation", "Continuous hold jog requires LinuxCNC integration. Select a step size here.")
            return
        selected = self.step_group.checkedButton()
        if selected:
            self.machine[axis] += sign * selected.property("step")
            self.update_dros()

    def scan(self):
        try:
            self.raw = simulated_scan(self.radius.value(), self.scan_step.value())
            self.filtered = []
            self.scan_plot.raw, self.scan_plot.filtered = self.raw, []
            self.turn_plot.raw, self.turn_plot.filtered = self.raw, []
            self.scan_plot.update(); self.turn_plot.update()
            self.code.clear()
            self.statusBar().showMessage(f"Synthetic scan: {len(self.raw)} points")
        except ValueError as exc:
            QMessageBox.warning(self, "Scan", str(exc))

    def filter_scan(self):
        try:
            self.filtered = smooth(self.raw)
            self.turn_plot.filtered = self.filtered
            self.turn_plot.update()
            self.code.clear()
        except ValueError as exc:
            QMessageBox.warning(self, "Profile", str(exc))

    def generate(self):
        try:
            if not self.filtered:
                raise ValueError("Smooth the scan before generating G-code")
            result = generate_gcode(
                self.filtered, rim_radius=self.radius.value(), passes=self.passes.value(),
                total_depth=self.depth.value(), max_depth=self.max_depth.value(),
                feed=self.feed.value(), rpm=self.rpm.value(),
                surface_speed=self.surface_speed.value(), max_rpm=self.max_rpm.value(),
                safe_z=self.safe_z.value(), sensor_x_offset=self.sensor_x.value(),
                sensor_z_offset=self.sensor_z.value(), tool_x_offset=self.tool_x.value(),
                tool_z_offset=self.tool_z.value(), use_css=self.mode.currentIndex() == 1)
            self.code.setPlainText(result)
        except ValueError as exc:
            QMessageBox.warning(self, "Toolpath", str(exc))

    def save_raw(self):
        if not self.raw: return
        path, _ = QFileDialog.getSaveFileName(self, "Save raw scan", "scan_raw.csv", "CSV (*.csv)")
        if path: save_csv(path, self.raw)

    def save_gcode(self):
        if not self.code.toPlainText(): return
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code preview", "rim_preview.ngc", "G-code (*.ngc)")
        if path:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(self.code.toPlainText())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec_())
