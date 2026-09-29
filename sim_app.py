"""Desktop-only PyQt5 mock machine and scan/turn workflow."""
import os
import sys
import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QRadioButton,
    QSpinBox, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from profile import PassSpec, generate_gcode, load_csv, save_csv, simulated_scan_range, smooth


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
        self.jog_axis = None
        self.jog_sign = 0
        self.jog_timer = QTimer(self)
        self.jog_timer.setInterval(80)
        self.jog_timer.timeout.connect(self.continuous_tick)
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
        for row, col, axis, sign in ((0, 1, "Z", 1), (2, 1, "Z", -1),
                                     (1, 0, "X", -1), (1, 2, "X", 1)):
            button = QPushButton(f"{axis}{'+' if sign > 0 else '−'}")
            button.pressed.connect(lambda a=axis, s=sign: self.jog_pressed(a, s))
            button.released.connect(self.jog_released)
            movement.addWidget(button, row, col)
        movement.addWidget(QLabel("X / Z"), 1, 1, alignment=Qt.AlignCenter)
        layout.addLayout(movement)
        root.addWidget(jog)
        table = QGroupBox("Table control (Y)")
        table_layout = QVBoxLayout(table)
        table_layout.addWidget(QLabel("Y is held at its set position during scanning and turning."))
        for label, sign in (("Table Up (Y+)", 1), ("Table Down (Y−)", -1)):
            button = QPushButton(label)
            button.pressed.connect(lambda s=sign: self.jog_pressed("Y", s))
            button.released.connect(self.jog_released)
            table_layout.addWidget(button)
        root.addWidget(table)
        root.addStretch()
        return pane

    def build_tabs(self):
        tabs = QTabWidget()
        scan = QWidget()
        scan_layout = QVBoxLayout(scan)
        scan_layout.addWidget(QLabel("<h2>Scan</h2>Synthetic laser data, outer edge toward center."))
        scan_range = QGridLayout()
        self.scan_start_x = number(0, -1000, 1000, 3, " mm")
        self.scan_end_x = number(230, -1000, 1000, 3, " mm")
        for row, (label, field) in enumerate((("X start (work)", self.scan_start_x),
                                              ("X end (work)", self.scan_end_x))):
            scan_range.addWidget(QLabel(label), row, 0)
            scan_range.addWidget(field, row, 1)
            capture = QPushButton("Use current X")
            capture.clicked.connect(lambda _=False, target=field: self.capture_work_x(target))
            scan_range.addWidget(capture, row, 2)
        scan_layout.addLayout(scan_range)
        self.scan_plot = Plot()
        scan_layout.addWidget(self.scan_plot, 1)
        buttons = QHBoxLayout()
        for label, callback in (("Run simulated scan", self.scan), ("Smooth profile", self.filter_scan),
                                ("Save raw CSV", self.save_raw), ("Save smoothed CSV", self.save_smoothed)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        scan_layout.addLayout(buttons)
        tabs.addTab(scan, "1. Scan")
        turning = QWidget()
        turn_layout = QVBoxLayout(turning)
        self.loaded_profile = []
        self.loaded_path = QLabel("No smoothed profile loaded")
        turn_layout.addWidget(self.loaded_path)
        load_button = QPushButton("Load smoothed CSV")
        load_button.clicked.connect(self.load_smoothed)
        turn_layout.addWidget(load_button)
        fields = QGridLayout()
        self.passes = QSpinBox(); self.passes.setRange(1, 20); self.passes.setValue(4)
        self.depth = number(0.2, 0.001, 20, 3, " mm")
        self.feed = number(50, 0.001, 1000, 3)
        self.rpm = QSpinBox(); self.rpm.setRange(1, 10000); self.rpm.setValue(500)
        self.max_rpm = QSpinBox(); self.max_rpm.setRange(1, 10000); self.max_rpm.setValue(1200)
        self.surface_speed = number(150, 0.1, 5000, 1, " m/min")
        self.mode = QComboBox()
        self.mode.addItems(["G97 / G94 (RPM, mm/min)", "G96 / G95 (CSS, mm/rev)"])
        self.mode.currentIndexChanged.connect(lambda index: self.feed.setValue(0.1 if index else 50))
        for index, (label, widget) in enumerate((
            ("Passes", self.passes), ("Total depth", self.depth),
            ("Feed (mode dependent)", self.feed), ("Starting RPM", self.rpm),
            ("Max RPM", self.max_rpm), ("Surface speed", self.surface_speed),
            ("Mode", self.mode),
        )):
            fields.addWidget(QLabel(label), index // 4, (index % 4) * 2)
            fields.addWidget(widget, index // 4, (index % 4) * 2 + 1)
        turn_layout.addLayout(fields)
        turn_layout.addWidget(QLabel("Passes: target depth is measured from the scanned surface. Double-click cells to edit."))
        self.pass_table = QTableWidget(0, 5)
        self.pass_table.setHorizontalHeaderLabels(["Use", "Target depth mm", "Feed", "RPM", "Surface m/min"])
        self.pass_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pass_table.setMinimumHeight(160)
        turn_layout.addWidget(self.pass_table)
        pass_buttons = QHBoxLayout()
        for label, callback in (("Create pass rows", self.reset_pass_rows),
                                ("Add pass", self.add_pass), ("Remove selected pass", self.remove_pass)):
            button = QPushButton(label); button.clicked.connect(callback); pass_buttons.addWidget(button)
        turn_layout.addLayout(pass_buttons)
        self.reset_pass_rows()
        actions = QHBoxLayout()
        for label, callback in (("Generate preview", self.generate), ("Save G-code", self.save_gcode)):
            button = QPushButton(label); button.clicked.connect(callback); actions.addWidget(button)
        turn_layout.addLayout(actions)
        preview = QSplitter(Qt.Horizontal)
        self.code = QTextEdit(); self.code.setReadOnly(True); self.code.setPlaceholderText("Generated preview G-code appears here")
        preview.addWidget(self.code)
        self.native_host = QWidget()
        self.native_layout = QVBoxLayout(self.native_host)
        self.native_label = QLabel("LinuxCNC native GCodeGraphics is available in a running LinuxCNC/QtVCP context.\nNo substitute 3D plot is shown.")
        self.native_label.setWordWrap(True)
        self.native_layout.addWidget(self.native_label)
        self.native_widget = None
        preview.addWidget(self.native_host)
        preview.setSizes([440, 440])
        turn_layout.addWidget(preview, 1)
        self.init_native_preview()
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
            ("Rim radius at scan start (G-code X0 at center)", self.radius),
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
        if self.estop:
            self.jog_released()
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

    def jog_pressed(self, axis, sign):
        if self.estop:
            return
        if self.continuous.isChecked():
            self.jog_axis, self.jog_sign = axis, sign
            self.jog_timer.start()
            self.continuous_tick()
        else:
            selected = self.step_group.checkedButton()
            if selected:
                self.machine[axis] += sign * selected.property("step")
                self.update_dros()

    def jog_released(self):
        self.jog_timer.stop()
        self.jog_axis = None

    def continuous_tick(self):
        if self.estop or self.jog_axis is None or not self.continuous.isChecked():
            self.jog_released()
            return
        self.machine[self.jog_axis] += self.jog_sign * 0.8  # 10 mm/s, 80 ms simulated tick
        self.update_dros()

    def scan(self):
        try:
            self.raw = simulated_scan_range(self.scan_start_x.value(), self.scan_end_x.value(),
                                            self.scan_step.value(), self.radius.value())
            self.filtered = []
            self.scan_plot.raw, self.scan_plot.filtered = self.raw, []
            self.scan_plot.update()
            self.code.clear()
            self.statusBar().showMessage(
                f"Synthetic scan X {self.scan_start_x.value():.3f} → {self.scan_end_x.value():.3f}: {len(self.raw)} points")
        except ValueError as exc:
            QMessageBox.warning(self, "Scan", str(exc))

    def capture_work_x(self, target):
        target.setValue(self.machine["X"] - self.offset["X"])

    def filter_scan(self):
        try:
            self.filtered = smooth(self.raw)
            self.scan_plot.filtered = self.filtered
            self.scan_plot.update()
            self.code.clear()
        except ValueError as exc:
            QMessageBox.warning(self, "Profile", str(exc))

    def generate(self):
        try:
            if not self.loaded_profile:
                raise ValueError("Load a saved smoothed CSV from the Scan tab first")
            settings = self.read_pass_rows()
            result = generate_gcode(
                self.loaded_profile, rim_radius=self.radius.value(), passes=self.passes.value(),
                total_depth=self.depth.value(), max_depth=self.max_depth.value(),
                feed=self.feed.value(), rpm=self.rpm.value(),
                surface_speed=self.surface_speed.value(), max_rpm=self.max_rpm.value(),
                safe_z=self.safe_z.value(), sensor_x_offset=self.sensor_x.value(),
                sensor_z_offset=self.sensor_z.value(), tool_x_offset=self.tool_x.value(),
                tool_z_offset=self.tool_z.value(), use_css=self.mode.currentIndex() == 1,
                pass_specs=settings)
            self.code.setPlainText(result)
            self.update_native_preview(result)
        except ValueError as exc:
            QMessageBox.warning(self, "Toolpath", str(exc))

    def save_raw(self):
        if not self.raw: return
        path, _ = QFileDialog.getSaveFileName(self, "Save raw scan", "scan_raw.csv", "CSV (*.csv)")
        if path: save_csv(path, self.raw)

    def save_smoothed(self):
        if not self.filtered:
            QMessageBox.warning(self, "Scan", "Smooth the scan first")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save smoothed profile", "scan_smoothed.csv", "CSV (*.csv)")
        if path:
            save_csv(path, self.filtered)

    def load_smoothed(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load smoothed profile", "", "CSV (*.csv)")
        if not path: return
        try:
            self.loaded_profile = load_csv(path)
            self.loaded_path.setText(f"Loaded: {path} ({len(self.loaded_profile)} points)")
            self.code.clear()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Profile", str(exc))

    def add_pass(self, depth=None):
        row = self.pass_table.rowCount()
        self.pass_table.insertRow(row)
        values = [f"{depth if depth is not None else (row+1)*self.depth.value()/max(1,self.passes.value()):.4f}",
                  f"{self.feed.value():.4f}", str(self.rpm.value()), f"{self.surface_speed.value():.3f}"]
        enabled = QTableWidgetItem()
        enabled.setFlags(enabled.flags() | Qt.ItemIsUserCheckable)
        enabled.setCheckState(Qt.Checked)
        self.pass_table.setItem(row, 0, enabled)
        for col, value in enumerate(values, 1):
            self.pass_table.setItem(row, col, QTableWidgetItem(value))

    def reset_pass_rows(self):
        self.pass_table.setRowCount(0)
        for i in range(1, self.passes.value() + 1):
            self.add_pass(i * self.depth.value() / self.passes.value())

    def remove_pass(self):
        row = self.pass_table.currentRow()
        if row >= 0: self.pass_table.removeRow(row)

    def read_pass_rows(self):
        rows = []
        for row in range(self.pass_table.rowCount()):
            try:
                values = [self.pass_table.item(row, col).text() for col in range(1, 5)]
                rows.append(PassSpec(float(values[0]), float(values[1]), int(values[2]),
                                     float(values[3]), self.pass_table.item(row, 0).checkState() == Qt.Checked))
            except (AttributeError, ValueError):
                raise ValueError(f"Invalid value in pass row {row+1}")
        return rows

    def init_native_preview(self):
        if not os.environ.get("INI_FILE_NAME"):
            return
        try:
            from qtvcp.widgets.gcode_graphics import GCodeGraphics
            self.native_widget = GCodeGraphics(self.native_host)
            self.native_layout.removeWidget(self.native_label)
            self.native_label.hide()
            self.native_layout.addWidget(self.native_widget)
        except Exception as exc:
            self.native_label.setText(f"Native LinuxCNC preview unavailable: {exc}")

    def update_native_preview(self, code):
        if self.native_widget is None:
            return
        try:
            path = Path(tempfile.gettempdir()) / "diamond_cut_preview.ngc"
            path.write_text(code, encoding="utf-8")
            self.native_widget.load_program(None, str(path))
        except Exception as exc:
            self.native_label.setText(f"Native preview could not load G-code: {exc}")
            self.native_label.show()

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
