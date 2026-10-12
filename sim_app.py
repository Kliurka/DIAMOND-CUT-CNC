"""Desktop-only PyQt5 mock machine and scan/turn workflow."""
import sys
import tempfile
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QColor, QPainter, QPen, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QRadioButton,
    QSpinBox, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit, QScrollArea,
)

from profile import PassSpec, generate_gcode, load_csv, save_csv, simulated_scan_range, smooth
from gcode_playback import Playback, parse_program
from code_editor import GCodeText


class Plot(QWidget):
    def __init__(self):
        super().__init__()
        self.raw, self.filtered = [], []
        self.exaggerate_z = False
        self.setMinimumSize(430, 300)

    def set_exaggerate_z(self, enabled):
        self.exaggerate_z = enabled
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#161e29"))
        bounds = self.rect().adjusted(70, 36, -24, -56)
        painter.setPen(QColor("#8996a7"))
        painter.drawRect(bounds)
        painter.drawText(bounds.left(), self.height() - 12, "Distance from outer edge toward center (X, mm)")
        if not self.raw:
            painter.drawText(bounds, Qt.AlignCenter, "Run simulated scan")
            return
        points = self.raw + self.filtered
        x_min = min(s.edge_mm for s in points)
        x_max = max(s.edge_mm for s in points)
        z_min = min(s.z_mm for s in points) - 0.2
        z_max = max(s.z_mm for s in points) + 0.2
        x_span = max(x_max - x_min, 0.001)
        z_span = max(z_max - z_min, 0.001)
        if self.exaggerate_z:
            scale_x = bounds.width() / x_span
            scale_z = bounds.height() / z_span
        else:
            scale_x = scale_z = min(bounds.width() / x_span, bounds.height() / z_span)
        # Center the data while using identical pixels per mm in the true-scale view.
        x_center = (x_min + x_max) / 2
        z_center = (z_min + z_max) / 2
        for series, color in ((self.raw, "#f27373"), (self.filtered, "#53bfff")):
            painter.setPen(QPen(QColor(color), 2))
            prev = None
            for sample in series:
                x = bounds.center().x() + (sample.edge_mm - x_center) * scale_x
                y = bounds.center().y() - (sample.z_mm - z_center) * scale_z
                if prev is not None:
                    painter.drawLine(round(prev[0]), round(prev[1]), round(x), round(y))
                prev = x, y
        painter.setPen(QColor("#8996a7"))
        painter.drawText(bounds.left(), bounds.bottom() + 20, f"{x_min:.2f}")
        painter.drawText(bounds.right() - 65, bounds.bottom() + 20, f"{x_max:.2f}")
        ratio = scale_z / scale_x
        caption = f"Z magnified {ratio:.1f}x" if self.exaggerate_z else "X:Z = 1:1 (same mm scale)"
        painter.drawText(bounds.left(), bounds.top() - 10,
                         f"{caption}   |   Z data: {min(s.z_mm for s in points):.3f} to {max(s.z_mm for s in points):.3f} mm")
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
    def __init__(self, native_preview_factory=None, machine_backend=None, user_settings=None):
        super().__init__()
        self.backend = machine_backend
        self.preferences = user_settings if user_settings is not None else QSettings("DiamondCut", "Screen")
        self.held_jog = None
        self.live_state = None
        self.control_error = ""
        self.table_key = None
        self.native_preview_factory = native_preview_factory
        self.playback = None
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(30)
        self.playback_timer.timeout.connect(self.playback_tick)
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
        split.setSizes([350, 930])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)
        self.update_dros()
        self.statusBar().showMessage("SIMULATION ONLY — no machine or sensor connected")
        if self.backend is not None:
            self.setWindowTitle("Diamond Cut CNC — LinuxCNC control")
            self.continuous.setChecked(True)
            self.continuous.toggled.connect(lambda: self.control_action(self.backend.stop_jog))
            self.statusBar().showMessage("LinuxCNC control — Run executes real motion; laser scan is synthetic")
            self.machine_timer = QTimer(self)
            self.machine_timer.setInterval(100)
            self.machine_timer.timeout.connect(self.refresh_machine)
            self.machine_timer.start()
            QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
            self.refresh_machine()

    def build_controls(self):
        pane = QWidget()
        pane.setMinimumWidth(330)
        pane.setMaximumWidth(420)
        root = QVBoxLayout(pane)
        root.addWidget(QLabel("<h2>Machine control</h2><b>" +
                             ("LINUXCNC — REAL AXES" if self.backend else "SIMULATION ONLY") + "</b>"))
        group = QGroupBox("Position (mm)")
        grid = QGridLayout(group)
        for col, label in enumerate(("Axis", "Machine", "Work")):
            grid.addWidget(QLabel(label), 0, col)
        self.dros = {}
        for row, axis in enumerate(("X", "Z"), 1):
            grid.addWidget(QLabel(axis), row, 0)
            self.dros[axis] = (QLabel(), QLabel())
            grid.addWidget(self.dros[axis][0], row, 1)
            grid.addWidget(self.dros[axis][1], row, 2)
        self.zero_buttons = []
        for row, axis in enumerate(("X", "Z"), 1):
            button = QPushButton("0")
            button.setFixedWidth(28)
            button.setToolTip(f"Zero Work {axis}")
            button.setAccessibleName(f"Zero Work {axis}")
            button.clicked.connect(lambda _=False, a=axis: self.zero(a))
            grid.addWidget(button, row, 3)
            self.zero_buttons.append(button)
        root.addWidget(group)
        reset = QPushButton("Reset / E-stop")
        reset.clicked.connect(self.toggle_estop)
        root.addWidget(reset)
        if self.backend:
            power_row = QHBoxLayout()
            self.power_button = QPushButton("Machine ON")
            self.power_button.clicked.connect(lambda: self.control_action(self.backend.toggle_power))
            power_row.addWidget(self.power_button)
            stop = QPushButton("STOP")
            stop.setStyleSheet("background: #b00020; color: white; font-weight: bold")
            stop.clicked.connect(self.stop_execution)
            power_row.addWidget(stop)
            root.addLayout(power_row)
        self.estop_label = QLabel()
        self.estop_label.setWordWrap(True)
        root.addWidget(self.estop_label)
        machine_home = QPushButton("Home All" if self.backend else "Home Machine (simulated)")
        self.home_button = machine_home
        machine_home.clicked.connect(self.home_machine)
        root.addWidget(machine_home)
        work_home = QPushButton("Go to Work Home (simulated)")
        work_home.clicked.connect(self.go_work_home)
        root.addWidget(work_home)
        if self.backend:
            work_home.setText("Work-home move: not configured")
            work_home.setEnabled(False)
            work_home.setToolTip("Requires verified clearance and machine geometry")
        jog = QGroupBox("Jog X / Z")
        layout = QVBoxLayout(jog)
        self.continuous = QCheckBox("Continuous (hold button)")
        layout.addWidget(self.continuous)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Jog speed"))
        jog_max = min(self.backend.limits[a] for a in 'XZ') * 60 if self.backend else 60000
        self.jog_speed = number(min(30, jog_max), 0.1, jog_max, 1, " mm/min")
        speed_row.addWidget(self.jog_speed)
        layout.addLayout(speed_row)
        layout.addWidget(QLabel("Hold Ctrl for X/Z rapid speed"))
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
        self.jog_buttons = []
        for row, col, axis, sign in ((0, 1, "Z", -1), (2, 1, "Z", 1),
                                     (1, 0, "X", -1), (1, 2, "X", 1)):
            button = QPushButton(f"{axis}{'+' if sign > 0 else '−'}")
            button.pressed.connect(lambda a=axis, s=sign: self.jog_pressed(a, s))
            button.released.connect(self.jog_released)
            movement.addWidget(button, row, col)
            self.jog_buttons.append(button)
        movement.addWidget(QLabel("X / Z"), 1, 1, alignment=Qt.AlignCenter)
        layout.addLayout(movement)
        root.addWidget(jog)
        table = QGroupBox("Table lift")
        table_layout = QVBoxLayout(table)
        table_layout.addWidget(QLabel("Hold to raise or lower the table."))
        self.table_buttons = []
        for label, sign in (("Table Up", 1), ("Table Down", -1)):
            button = QPushButton(label)
            button.pressed.connect(lambda s=sign: self.table_pressed(s))
            button.released.connect(self.table_released)
            table_layout.addWidget(button)
            self.table_buttons.append(button)
            self.jog_buttons.append(button)
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
        self.scan_step = number(1, 0.01, 20, 2, " mm")
        self.scan_speed = number(600, 1, 10000, 1, " mm/min")
        for col, (label, field) in zip((0, 3), (("X start (work)", self.scan_start_x),
                                               ("X end (work)", self.scan_end_x))):
            scan_range.addWidget(QLabel(label), 0, col)
            scan_range.addWidget(field, 0, col + 1)
            capture = QPushButton("Use current X")
            capture.clicked.connect(lambda _=False, target=field: self.capture_work_x(target))
            scan_range.addWidget(capture, 0, col + 2)
        scan_range.addWidget(QLabel("Scan step"), 1, 0)
        scan_range.addWidget(self.scan_step, 1, 1)
        scan_range.addWidget(QLabel("X scan feedrate"), 1, 3)
        scan_range.addWidget(self.scan_speed, 1, 4)
        self.median_window = QComboBox()
        self.average_window = QComboBox()
        for value in (1, 3, 5, 7, 9, 11):
            self.median_window.addItem(str(value), value)
            self.average_window.addItem(str(value), value)
        self.median_window.setCurrentIndex(2)  # five samples
        scan_range.addWidget(QLabel("Median window (samples)"), 2, 0)
        scan_range.addWidget(self.median_window, 2, 1)
        scan_range.addWidget(QLabel("Mean window (samples)"), 2, 3)
        scan_range.addWidget(self.average_window, 2, 4)
        scan_layout.addLayout(scan_range)
        self.scan_summary = QLabel("Scan length and estimated time appear here after simulation.")
        scan_layout.addWidget(self.scan_summary)
        self.scan_plot = Plot()
        scan_layout.addWidget(self.scan_plot, 1)
        self.scan_z_detail = QCheckBox("Magnify Z for surface detail (changes display only)")
        self.scan_z_detail.toggled.connect(self.scan_plot.set_exaggerate_z)
        scan_layout.addWidget(self.scan_z_detail)
        buttons = QHBoxLayout()
        for label, callback in (("Run simulated scan", self.scan), ("Smooth profile", self.filter_scan),
                                ("Save raw CSV", self.save_raw), ("Save smoothed CSV", self.save_smoothed)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        scan_layout.addLayout(buttons)
        tabs.addTab(scan, "1. Scan")
        turning = QWidget()
        turn_root = QVBoxLayout(turning)
        turning_split = QSplitter(Qt.Vertical)
        turning_split.setChildrenCollapsible(False)
        upper_split = QSplitter(Qt.Horizontal)
        upper_split.setChildrenCollapsible(False)
        machining_controls = QWidget()
        turn_layout = QVBoxLayout(machining_controls)
        turn_layout.setContentsMargins(0, 0, 0, 0)
        upper_split.addWidget(machining_controls)
        self.loaded_profile = []
        self.opened_gcode = None
        self.loaded_path = QLabel("No smoothed profile loaded")
        self.loaded_path.setWordWrap(True)
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
        self.mode.model().item(1).setEnabled(False)
        self.mode.setToolTip("CSS requires X referenced to spindle center. Work-X profiles currently use G97.")
        self.mode.currentIndexChanged.connect(lambda index: self.feed.setValue(0.1 if index else 50))
        for index, (label, widget) in enumerate((
            ("Total depth", self.depth),
            ("Feed (mm/min)", self.feed), ("Starting RPM", self.rpm),
            ("Max RPM", self.max_rpm), ("Surface speed", self.surface_speed),
            ("Mode", self.mode),
        )):
            fields.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            fields.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        turn_layout.addLayout(fields)
        pass_hint = QLabel("Pass depths from Work Z0 (+Z). Double-click cells to edit.")
        pass_hint.setWordWrap(True)
        turn_layout.addWidget(pass_hint)
        self.pass_table = QTableWidget(0, 5)
        self.pass_table.setHorizontalHeaderLabels(["Use", "Target depth mm", "Feed", "RPM", "Surface m/min"])
        self.pass_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pass_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.pass_table.setMinimumHeight(110)
        turn_layout.addWidget(self.pass_table, 1)
        self.reset_pass_rows()
        self.passes.valueChanged.connect(self.reset_pass_rows)
        self.depth.valueChanged.connect(self.reset_pass_rows)
        self.feed.valueChanged.connect(lambda: self.update_pass_defaults(2, self.feed.value(), 4))
        self.rpm.valueChanged.connect(lambda: self.update_pass_defaults(3, self.rpm.value(), 0))
        self.surface_speed.valueChanged.connect(lambda: self.update_pass_defaults(4, self.surface_speed.value(), 3))
        actions = QHBoxLayout()
        for label, callback in (("Generate preview", self.generate), ("Save G-code", self.save_gcode)):
            button = QPushButton(label); button.clicked.connect(callback); actions.addWidget(button)
        self.open_gcode_button = QPushButton("Open G-code")
        self.open_gcode_button.clicked.connect(self.open_gcode)
        actions.addWidget(self.open_gcode_button)
        turn_layout.addLayout(actions)
        execution = QHBoxLayout()
        self.simulate_button = QPushButton("Simulate G-code")
        self.simulate_button.clicked.connect(self.simulate_gcode)
        self.simulation_stop_button = QPushButton("Stop simulation")
        self.simulation_stop_button.clicked.connect(self.stop_simulation)
        self.run_button = QPushButton("Run G-code")
        self.run_button.setStyleSheet(
            "QPushButton {background: #9acff2; color: #16394f; border: 1px solid #71acd2; "
            "border-radius: 3px; padding: 4px; font-weight: bold;}"
            "QPushButton:hover {background: #b3ddf8;} QPushButton:pressed {background: #73b8e5;}"
            "QPushButton:disabled {background: #dceaf3; color: #899ca9; border-color: #bfd3e0;}")
        self.run_button.clicked.connect(self.run_gcode)
        self.run_button.setEnabled(self.backend is not None)
        self.simulation_speed = number(10, .1, 100, 1, " ×")
        for widget in (self.simulate_button, self.simulation_stop_button, self.run_button):
            execution.addWidget(widget)
        turn_layout.addLayout(execution)
        simulation_options = QHBoxLayout()
        simulation_options.addWidget(QLabel("Simulation speed"))
        simulation_options.addWidget(self.simulation_speed)
        simulation_options.addStretch()
        self.reset_view_button = QPushButton("Reset X/Z view")
        self.reset_view_button.setEnabled(False)
        self.reset_view_button.clicked.connect(self.reset_graph_view)
        simulation_options.addWidget(self.reset_view_button)
        turn_layout.addLayout(simulation_options)
        self.execution_status = QLabel("", turning)
        self.execution_status.hide()

        self.code = GCodeText(); self.code.setPlaceholderText("Generated preview G-code appears here")
        self.syncing_code_line = False
        self.selected_code_line = None
        self.code.cursorPositionChanged.connect(self.code_cursor_changed)
        code_host = QWidget()
        code_layout = QVBoxLayout(code_host)
        code_layout.setContentsMargins(0, 0, 0, 0)
        self.code_line_label = QLabel("Select a code line or a path segment")
        code_layout.addWidget(self.code_line_label)
        code_layout.addWidget(self.code)
        upper_split.addWidget(code_host)
        upper_split.setSizes([560, 350])
        turning_split.addWidget(upper_split)
        self.native_host = QWidget()
        self.native_layout = QVBoxLayout(self.native_host)
        self.native_layout.setContentsMargins(0, 0, 0, 0)
        self.native_label = QLabel("LinuxCNC native GCodeGraphics is available in a running LinuxCNC/QtVCP context.\nNo substitute 3D plot is shown.")
        self.native_label.setWordWrap(True)
        self.native_layout.addWidget(self.native_label)
        self.native_widget = None
        self.native_host.setMinimumHeight(200)
        turning_split.addWidget(self.native_host)
        turning_split.setSizes([410, 290])
        turn_root.addWidget(turning_split, 1)
        self.init_native_preview()
        tabs.addTab(turning, "2. Toolpath & Turning")
        settings = QWidget()
        form = QFormLayout(settings)
        self.sensor_x = number(0, -1000, 1000, 3, " mm")
        self.sensor_z = number(0, -1000, 1000, 3, " mm")
        self.tool_x = number(0, -1000, 1000, 3, " mm")
        self.tool_z = number(0, -1000, 1000, 3, " mm")
        self.safe_z = number(5, 0.1, 100, 2, " mm")
        self.max_depth = number(0.5, 0.001, 10, 3, " mm")
        self.rapid_speed = {axis: number(self.backend.limits[axis] * 60 if self.backend else 600,
                                         .1, 60000, 1, " mm/min") for axis in 'XZ'}
        for axis in 'XZ':
            form.addRow(axis + " rapid / G0 speed", self.rapid_speed[axis])
        self.save_rapids_button = QPushButton("Save X/Z rapid speeds")
        self.save_rapids_button.setEnabled(self.backend is not None and self.backend.ini_path is not None)
        self.save_rapids_button.clicked.connect(self.save_rapid_settings)
        form.addRow(self.save_rapids_button)
        self.rapids_status = QLabel("X/Z: Machine OFF, save, then restart LinuxCNC. Also caps maximum axis feed speed.")
        self.rapids_status.setWordWrap(True)
        form.addRow(self.rapids_status)
        y_max = self.backend.limits['Y'] * 60 if self.backend else 60000
        self.table_speed = number(float(self.preferences.value('table_speed', min(30, y_max))),
                                  .1, y_max, 1, " mm/min")
        self.table_speed.valueChanged.connect(lambda value: self.preferences.setValue('table_speed', value))
        form.addRow("Y table speed (buttons / Page Up, Down)", self.table_speed)
        self.show_code_numbers = QCheckBox("Show G-code line numbers")
        self.show_code_numbers.setChecked(self.preferences.value('show_code_numbers', True, type=bool))
        self.code.set_line_numbers_visible(self.show_code_numbers.isChecked())
        self.show_code_numbers.toggled.connect(self.set_code_numbers)
        form.addRow(self.show_code_numbers)
        form.addRow("Passes", self.passes)
        form.addRow(QLabel("Changing Passes or Total depth rebuilds the pass table. Cells remain editable."))
        limits_group = QGroupBox("Machine coordinates — travel limits (mm)")
        limits_grid = QGridLayout(limits_group)
        for col, text in enumerate(("Axis", "Min", "Max")):
            limits_grid.addWidget(QLabel(text), 0, col)
        limits = (self.backend.coordinate_limits() if self.backend is not None
                  else {"X": (-1.01, 199), "Y": (-.01, 200), "Z": (-1.01, 99.01)})
        self.coordinate_limit_fields = {}
        for row, axis in enumerate(("X", "Z", "Y"), 1):
            limits_grid.addWidget(QLabel(axis + (" (table)" if axis == "Y" else "")), row, 0)
            boxes = tuple(number(v, -100000, 100000, 3) for v in limits[axis])
            self.coordinate_limit_fields[axis] = boxes
            for col, box in enumerate(boxes, 1):
                limits_grid.addWidget(box, row, col)
        form.addRow(limits_group)
        self.save_limits_button = QPushButton("Save machine limits")
        self.save_limits_button.clicked.connect(self.save_machine_limits)
        self.save_limits_button.setEnabled(self.backend is not None and self.backend.ini_path is not None)
        form.addRow(self.save_limits_button)
        self.limits_status = QLabel("Machine coordinates, independent of Work 0. Machine OFF required; restart LinuxCNC after saving.")
        self.limits_status.setWordWrap(True)
        form.addRow(self.limits_status)
        for label, widget in (
            ("Sensor X offset", self.sensor_x),
            ("Sensor Z offset", self.sensor_z), ("Tool X offset", self.tool_x),
            ("Tool Z offset", self.tool_z), ("Safe Z clearance", self.safe_z),
            ("Maximum total cut depth", self.max_depth),
        ):
            form.addRow(label, widget)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings)
        tabs.addTab(settings_scroll, "3. Settings")
        return tabs

    def update_dros(self):
        if self.backend is not None:
            return
        for axis, (machine, work) in self.dros.items():
            machine.setText(f"{self.machine[axis]:+.4f}")
            work.setText(f"{self.machine[axis] - self.offset.get(axis, 0):+.4f}")
        self.estop_label.setText("RESET REQUIRED" if self.estop else "Simulated control enabled")

    def toggle_estop(self):
        if self.backend is not None:
            self.control_action(self.backend.toggle_estop)
            return
        self.estop = not self.estop
        if self.estop:
            self.jog_released()
        self.update_dros()

    def zero(self, axis):
        if self.backend is not None:
            if not self.control_action(lambda: self.backend.zero(axis)):
                QMessageBox.warning(self, "Work zero", self.control_error)
            elif self.native_widget is not None:
                try:
                    self.native_widget.refresh_work_coordinates()
                except Exception as exc:
                    QMessageBox.warning(self, "Preview", f"Work zero set, but preview refresh failed: {exc}")
            return
        if self.estop: return
        self.offset[axis] = self.machine[axis]
        self.update_dros()

    def home_machine(self):
        if self.backend is not None:
            self.control_action(self.backend.home_all)
            return
        if self.estop: return
        self.machine.update(X=0.0, Z=0.0, Y=0.0)
        self.update_dros()

    def go_work_home(self):
        if self.backend is not None:
            return
        if self.estop: return
        self.machine["Z"] = self.offset["Z"] + self.safe_z.value()
        self.machine["X"] = self.offset["X"]
        self.update_dros()

    def jog_pressed(self, axis, sign):
        if self.playback is not None:
            return
        if self.backend is not None:
            selected = self.step_group.checkedButton()
            distance = None if self.continuous.isChecked() else selected.property("step")
            self.held_jog_ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
            speed = self.rapid_speed[axis].value() if self.held_jog_ctrl else self.jog_speed.value()
            self.held_jog = (axis, sign) if distance is None else None
            self.control_action(lambda: self.backend.jog(axis, sign, speed, distance))
            return
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
        self.held_jog = None
        if self.backend is not None:
            if self.continuous.isChecked():
                self.control_action(self.backend.stop_jog)
            return
        self.jog_timer.stop()
        self.jog_axis = None

    def table_pressed(self, sign):
        if self.playback is not None:
            return
        self.held_jog = None
        if self.backend is not None:
            self.control_action(lambda: self.backend.jog("Y", sign, self.table_speed.value()))
        elif not self.estop:
            self.jog_axis, self.jog_sign = "Y", sign
            self.jog_timer.start()
            self.continuous_tick()

    def table_released(self):
        if self.backend is not None:
            self.control_action(self.backend.stop_jog)
        else:
            self.jog_timer.stop()
            self.jog_axis = None

    def table_key_event(self, receiver, event, pressed):
        if event.key() not in (Qt.Key_PageUp, Qt.Key_PageDown):
            return False
        if event.isAutoRepeat():
            return True
        if not pressed:
            if self.table_key == event.key():
                self.table_key = None
                self.table_released()
            return True
        from PyQt5.QtWidgets import QAbstractSpinBox, QLineEdit, QDialog, QAbstractItemView
        widget = receiver
        while widget is not None:
            if isinstance(widget, (QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit, QDialog, QAbstractItemView)):
                return False
            widget = widget.parentWidget()
        if event.modifiers() != Qt.NoModifier or self.table_key is not None:
            return True
        self.table_key = event.key()
        self.table_pressed(1 if event.key() == Qt.Key_PageUp else -1)
        return True

    def continuous_tick(self):
        if self.backend is not None:
            return
        if self.estop or self.jog_axis is None or (self.jog_axis != "Y" and not self.continuous.isChecked()):
            self.jog_released()
            return
        axis = self.jog_axis
        if axis == 'Y':
            speed = self.table_speed.value()
        else:
            speed = (self.rapid_speed[axis].value() if QApplication.keyboardModifiers() & Qt.ControlModifier
                     else self.jog_speed.value())
        self.machine[axis] += self.jog_sign * speed / 60 * .08
        self.update_dros()

    def control_action(self, action):
        success = False
        try:
            action()
            self.control_error = ""
            success = True
        except Exception as exc:
            self.control_error = str(exc)
            self.statusBar().showMessage(f"LinuxCNC command failed: {exc}")
        self.refresh_machine()
        return success

    def refresh_machine(self):
        try:
            state = self.backend.snapshot()
            self.live_state = state
            self.machine = state["machine"]
            self.offset = {a: state["machine"][a] - state["work"][a] for a in ("X", "Y", "Z")}
            for axis, (machine, work) in self.dros.items():
                machine.setText(f"{state['machine'][axis]:+.4f}")
                work.setText(f"{state['work'][axis]:+.4f}")
            label = ("ESTOP — reset required" if state["estop"] else
                     "Machine ON" if state["on"] else "Machine OFF")
            label += " | Homed" if state["homed"] else " | Not homed"
            if state["homing"]:
                label += " | Homing"
            if not state["healthy"]:
                label += " | Mesa communication fault"
            if self.control_error:
                label += "\n" + self.control_error
            self.estop_label.setText(label)
            self.power_button.setText("Machine OFF" if state["on"] else "Machine ON")
            ready = state["ready"]
            if self.held_jog is not None:
                if not ready or self.backend.active_jog is None:
                    self.held_jog = None
                else:
                    ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
                    if ctrl != self.held_jog_ctrl:
                        axis, sign = self.held_jog
                        self.held_jog_ctrl = ctrl
                        speed = self.rapid_speed[axis].value() if ctrl else self.jog_speed.value()
                        self.backend.jog(axis, sign, speed)
            if state["running"]:
                self.set_execution_status(f"RUNNING — G-code line {state['current_line']}")
                self.show_program_line(state['current_line'], executing=True)
            elif getattr(self, "was_running", False):
                self.set_execution_status("Program stopped / completed")
                if self.selected_code_line is not None:
                    self.show_program_line(self.selected_code_line[0])
            self.open_gcode_button.setEnabled(not state["running"] and self.playback is None)
            self.was_running = state["running"]
            self.run_button.setEnabled(ready and state["homed"] and state["stationary"] and self.playback is None
                                       and not self.backend.limits_pending)
            self.simulate_button.setEnabled(not state["running"] and self.playback is None)
            ready = ready and self.playback is None
            for button in self.zero_buttons:
                button.setEnabled(ready and state["stationary"])
                button.setToolTip("Set current position to zero in the active work coordinate system"
                                  if state["can_touch_off"] else "Press Home All first and wait for Homed")
            self.home_button.setEnabled(ready and state["stationary"])
        except Exception as exc:
            self.live_state = None
            self.held_jog = None
            ready = False
            self.run_button.setEnabled(False)
            self.simulate_button.setEnabled(False)
            self.estop_label.setText(f"LinuxCNC unavailable: {exc}")
            for machine, work in self.dros.values():
                machine.setText("UNKNOWN")
                work.setText("UNKNOWN")
            for button in self.zero_buttons + [self.home_button]:
                button.setEnabled(False)
            try:
                self.backend.stop_jog()
            except Exception:
                pass
        for button in self.jog_buttons:
            button.setEnabled(ready)
        for button in self.table_buttons:
            button.setEnabled(ready and not (self.live_state or {}).get("table_locked", False))

    def application_state_changed(self, state):
        if self.backend is not None and state != Qt.ApplicationActive:
            self.table_key = None
            self.control_action(self.backend.stop_jog)

    def shutdown(self):
        self.preferences.sync()
        self.stop_simulation()
        if self.backend is not None:
            self.machine_timer.stop()
            self.backend.stop()

    def closeEvent(self, event):
        if self.backend is not None:
            try:
                self.shutdown()
            except Exception as exc:
                self.statusBar().showMessage(f"Stop failed: {exc}")
        super().closeEvent(event)

    def scan(self):
        try:
            self.raw = simulated_scan_range(self.scan_start_x.value(), self.scan_end_x.value(),
                                            self.scan_step.value())
            self.filtered = []
            self.scan_plot.raw, self.scan_plot.filtered = self.raw, []
            self.scan_plot.update()
            self.code.clear()
            estimate_sec = 60 * (self.scan_end_x.value() - self.scan_start_x.value()) / self.scan_speed.value()
            self.scan_summary.setText(
                f"Travel: {self.scan_end_x.value() - self.scan_start_x.value():.2f} mm  |  "
                f"Samples: {len(self.raw)}  |  Estimated machine travel: {estimate_sec:.1f} s")
            self.statusBar().showMessage(
                f"Synthetic scan X {self.scan_start_x.value():.3f} → {self.scan_end_x.value():.3f}: "
                f"{len(self.raw)} points, estimated travel {estimate_sec:.1f} s at {self.scan_speed.value():.1f} mm/min")
        except ValueError as exc:
            QMessageBox.warning(self, "Scan", str(exc))

    def capture_work_x(self, target):
        if self.backend is not None:
            self.refresh_machine()
            if self.live_state is None:
                return
            target.setValue(self.live_state["work"]["X"])
            return
        target.setValue(self.machine["X"] - self.offset["X"])

    def filter_scan(self):
        try:
            self.filtered = smooth(self.raw, self.median_window.currentData(),
                                   self.average_window.currentData())
            self.scan_plot.filtered = self.filtered
            self.scan_plot.update()
            self.code.clear()
        except ValueError as exc:
            QMessageBox.warning(self, "Profile", str(exc))

    def generate(self):
        if self.backend is not None and self.backend.program_running:
            return False
        try:
            self.stop_simulation()
            if not self.loaded_profile:
                raise ValueError("Load a saved smoothed CSV from the Scan tab first")
            settings = self.read_pass_rows()
            result = generate_gcode(
                self.loaded_profile, passes=self.passes.value(),
                total_depth=self.depth.value(), max_depth=self.max_depth.value(),
                feed=self.feed.value(), rpm=self.rpm.value(),
                surface_speed=self.surface_speed.value(), max_rpm=self.max_rpm.value(),
                safe_z=self.safe_z.value(), sensor_x_offset=self.sensor_x.value(),
                sensor_z_offset=self.sensor_z.value(), tool_x_offset=self.tool_x.value(),
                tool_z_offset=self.tool_z.value(), use_css=self.mode.currentIndex() == 1,
                pass_specs=settings)
            was_opened = self.opened_gcode is not None
            self.opened_gcode = None
            self.set_program_text(result)
            if was_opened:
                self.loaded_path.setText(f"Generated from loaded profile ({len(self.loaded_profile)} points)")
            self.update_native_preview(result)
            return True
        except ValueError as exc:
            QMessageBox.warning(self, "Toolpath", str(exc))
            return False

    def simulate_gcode(self):
        if self.native_widget is None:
            QMessageBox.warning(self, "Simulation", "Simulation requires the LinuxCNC QtVCP graph")
            return
        if self.backend is not None:
            state = self.backend.snapshot()
            if state["running"] or not state["stationary"] or self.backend.active_jog is not None:
                QMessageBox.warning(self, "Simulation", "Stop axis motion before simulation")
                return
            start = (state["work"]["X"], state["work"]["Z"])
        else:
            start = tuple(self.machine[a] - self.offset[a] for a in ("X", "Z"))
        if not self.prepare_program():
            return
        try:
            rapids = {axis: min(box.value(), self.backend.limits[axis] * 60) if self.backend else box.value()
                      for axis, box in self.rapid_speed.items()}
            moves = parse_program(self.code.toPlainText(), start=start, rapid=rapids, require_preamble=True)
            self.playback = Playback(moves, start)
            self.playback_time = time.monotonic()
            self.native_widget.set_simulated_work_position(start)
            self.playback_timer.start()
            self.run_button.setEnabled(False)
            self.simulate_button.setEnabled(False)
            self.set_execution_status("SIMULATION — graphic only, no machine commands")
        except Exception as exc:
            self.stop_simulation()
            QMessageBox.warning(self, "Simulation", str(exc))

    def playback_tick(self):
        if self.playback is None:
            return
        now = time.monotonic()
        position = self.playback.advance((now - self.playback_time) * self.simulation_speed.value())
        self.playback_time = now
        self.native_widget.set_simulated_work_position(position)
        if self.playback.done:
            self.stop_simulation()
            self.set_execution_status("Simulation completed — marker shows actual tool again")

    def stop_execution(self):
        self.stop_simulation()
        if self.backend is not None:
            self.control_action(self.backend.stop)

    def stop_simulation(self):
        self.playback_timer.stop()
        self.playback = None
        if getattr(self, "native_widget", None) is not None:
            self.native_widget.set_simulated_work_position(None)
        if hasattr(self, "simulate_button"):
            self.simulate_button.setEnabled(True)

    def run_gcode(self):
        if self.backend is None:
            return
        if self.playback is not None:
            QMessageBox.warning(self, "Run", "Stop simulation first")
            return
        if not self.prepare_program():
            return
        try:
            folder = Path(tempfile.mkdtemp(prefix="diamondcut-run-"))
            path = folder / "program.ngc"
            path.write_text(self.code.toPlainText(), encoding="utf-8")
            self.backend.run_program(path)
            self.set_execution_status("RUNNING — all enabled passes")
        except Exception as exc:
            self.set_execution_status(f"Run blocked: {exc}")
            QMessageBox.warning(self, "Run", str(exc))
        self.refresh_machine()

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
            if any(p.work_x_mm is None for p in self.loaded_profile):
                raise ValueError("This older CSV has no work X coordinates. Rescan and save the profile "
                                 "with this version before generating a toolpath.")
            self.opened_gcode = None
            self.loaded_path.setText(f"Loaded: {path} ({len(self.loaded_profile)} points)")
            self.code.clear()
        except (ValueError, OSError) as exc:
            self.loaded_profile = []
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

    def update_pass_defaults(self, column, value, decimals):
        for row in range(self.pass_table.rowCount()):
            self.pass_table.item(row, column).setText(f"{value:.{decimals}f}")

    def set_code_numbers(self, visible):
        self.code.set_line_numbers_visible(visible)
        self.preferences.setValue('show_code_numbers', visible)

    def save_rapid_settings(self):
        if self.backend is None:
            return
        try:
            if self.playback is not None:
                raise RuntimeError("Stop simulation before saving rapid speeds")
            self.backend.save_rapid_speeds({axis: box.value() for axis, box in self.rapid_speed.items()})
            self.rapids_status.setText("Saved — restart LinuxCNC to activate X/Z rapid speeds. Run is blocked until restart.")
            self.refresh_machine()
        except (RuntimeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Rapid speeds", str(exc))

    def save_machine_limits(self):
        if self.backend is None:
            return
        try:
            if self.playback is not None:
                raise RuntimeError("Stop simulation before saving limits")
            limits = {axis: tuple(box.value() for box in boxes)
                      for axis, boxes in self.coordinate_limit_fields.items()}
            self.backend.save_coordinate_limits(limits)
            self.limits_status.setText("Saved — restart LinuxCNC to activate the new limits. Run is blocked until restart.")
            self.refresh_machine()
        except (RuntimeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Machine limits", str(exc))

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

    def graphics_line_selected(self, line):
        if self.backend is not None and self.backend.program_running:
            return
        self.show_program_line(line, highlight_graphics=False)

    def code_cursor_changed(self):
        if self.syncing_code_line or not self.code.toPlainText():
            return
        if self.backend is not None and self.backend.program_running:
            return
        self.show_program_line(self.code.textCursor().blockNumber() + 1)

    def show_program_line(self, line, executing=False, highlight_graphics=True):
        # LinuxCNC/canon line numbers are one-based; QTextDocument blocks are zero-based.
        if line <= 0:
            return
        block = self.code.document().findBlockByNumber(line - 1)
        if not block.isValid() or not block.text():
            return
        selection_key = (line, executing)
        if (self.selected_code_line == selection_key
                and self.code.textCursor().blockNumber() == line - 1):
            return
        self.syncing_code_line = True
        try:
            cursor = QTextCursor(block)
            self.code.setTextCursor(cursor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor("#a6edaa" if executing else "#ffe083"))
            selection.format.setForeground(QColor("#171717"))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            self.code.setExtraSelections([selection])
            self.code.ensureCursorVisible()
            self.code_line_label.setText(f"{'Executing' if executing else 'Selected'} G-code line {line}")
            self.selected_code_line = selection_key
            if highlight_graphics and self.native_widget is not None:
                self.native_widget.highlight_program_line(line)
        finally:
            self.syncing_code_line = False

    def init_native_preview(self):
        if self.native_preview_factory is None:
            return
        try:
            self.native_widget = self.native_preview_factory(self.native_host)
            self.native_layout.removeWidget(self.native_label)
            self.native_label.hide()
            self.native_layout.addWidget(self.native_widget, 1)
            self.native_widget.program_line_selected.connect(self.graphics_line_selected)
            self.reset_view_button.setEnabled(True)
        except Exception as exc:
            self.native_label.setText(f"Native LinuxCNC preview unavailable: {exc}")

    def set_execution_status(self, text):
        self.execution_status.setText(text)
        self.statusBar().showMessage(text)

    def reset_graph_view(self):
        if self.native_widget is not None:
            self.native_widget.reset_default_view()

    def set_program_text(self, code):
        self.syncing_code_line = True
        try:
            self.code.setPlainText(code)
            self.code.setExtraSelections([])
            self.selected_code_line = None
            self.code_line_label.setText("Select a code line or a path segment")
        finally:
            self.syncing_code_line = False

    def prepare_program(self):
        if self.opened_gcode is not None:
            return bool(self.code.toPlainText().strip())
        return self.generate()

    def open_gcode(self):
        if self.backend is not None and self.backend.program_running:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", "", "G-code (*.ngc *.nc *.tap);;All files (*)")
        if not path:
            return
        try:
            code = Path(path).read_text(encoding="utf-8")
            if not code.strip():
                raise ValueError("G-code file is empty")
            self.stop_simulation()
            self.opened_gcode = Path(path)
            self.set_program_text(code)
            self.loaded_path.setText(f"Opened G-code: {path}")
            self.update_native_preview(code)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Open G-code", str(exc))

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

