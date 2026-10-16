"""Mesa I/O monitor and manual bench output controls for QtVCP."""
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                            QTableWidgetItem, QCheckBox, QPushButton,
                            QGroupBox, QHBoxLayout, QSpinBox, QApplication,
    QMessageBox)
from bench_stepgen import BenchStepgen, STEPGEN

PREFIX = "hm2_7i96s.0"


def output_pin(index):
    if index not in range(6):
        raise ValueError("Output index must be 0 to 5")
    module = "ssr" if index < 4 else "outm"
    return f"{PREFIX}.{module}.00.out-{index:02d}"


def write_output(reader, writer, index, enabled):
    if writer is None:
        raise RuntimeError("Output control unavailable")
    pin = output_pin(index)
    # Check current health again at the click, not only at the previous UI refresh.
    if enabled and not read_snapshot(reader)["healthy"]:
        raise RuntimeError("Mesa communication fault: cannot enable output")
    writer(pin, "true" if enabled else "false")


def read_snapshot(reader):
    """Reject missing/faulted HAL data rather than displaying stale inputs as live."""
    prefix = PREFIX
    faults = {
        "Packet error": bool(reader(prefix + ".packet-error")),
        "Packet limit exceeded": bool(reader(prefix + ".packet-error-exceeded")),
        "Watchdog": bool(reader(prefix + ".watchdog.has_bit")),
    }
    errors = int(reader(prefix + ".packet-error-total"))
    active_faults = [name for name, active in faults.items() if active]
    if active_faults:
        return {"healthy": False, "status": " / ".join(active_faults),
                "errors": errors, "inputs": None, "outputs": None}
    inputs = [bool(reader(f"{prefix}.inm.00.input-{i:02d}")) for i in range(11)]
    outputs = [bool(reader(f"{prefix}.ssr.00.out-{i:02d}")) for i in range(4)]
    outputs += [bool(reader(f"{prefix}.outm.00.out-{i:02d}")) for i in range(4, 6)]
    return {"healthy": True, "status": "HAL communication active",
            "errors": errors, "inputs": inputs, "outputs": outputs}


class MesaIOPanel(QWidget):
    def __init__(self, reader, parent=None, writer=None, allow_bench=True, backend=None):
        super().__init__(parent)
        self.reader = reader
        self.writer = writer
        self.test = None
        if backend is not None:
            from output_test import OutputTest
            self.test = OutputTest(backend, lambda i, on: write_output(reader, writer, i, on))
            backend.output_test_stop = self.test.end
        self.stepgen = BenchStepgen(writer if allow_bench else None,
                                   lambda: read_snapshot(self.reader)["healthy"])
        layout = QVBoxLayout(self)
        title = QLabel("<h2>Mesa 7i96S — I/O monitor</h2>")
        layout.addWidget(title)
        notice = QLabel("Real I/O and STEPGEN0 bench test. Left axis controls and laser scan are simulated."
                        if allow_bench else "Enable output test without a password. Outputs stay ON when switching tabs or windows; use OFF or Stop tests to stop.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        if self.test:
            controls = QHBoxLayout()
            self.unlock_button = QPushButton("Enable output test")
            self.unlock_button.clicked.connect(self.unlock_test)
            controls.addWidget(self.unlock_button)
            self.lock_button = QPushButton("Stop tests / Disable")
            self.lock_button.clicked.connect(self.lock_test)
            controls.addWidget(self.lock_button)
            self.rpm = QSpinBox()
            self.rpm.setRange(1, int(float(backend.ini.find("DISPLAY", "MAX_SPINDLE_0_SPEED") or 1200)))
            self.rpm.setValue(50)
            self.rpm.setSuffix(" RPM")
            controls.addWidget(self.rpm)
            self.spindle_on = QPushButton("Spindle ON (forward)")
            self.spindle_on.clicked.connect(self.start_spindle_test)
            self.spindle_on.setEnabled(False)
            controls.addWidget(self.spindle_on)
            off = QPushButton("Spindle OFF")
            off.clicked.connect(self.stop_spindle_test)
            controls.addWidget(off)
            layout.addLayout(controls)
        self.status = QLabel("Waiting for HAL")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.errors = QLabel()
        layout.addWidget(self.errors)
        motor = QGroupBox("STEPGEN0 — free motor bench test")
        motor_layout = QVBoxLayout(motor)
        fields = QHBoxLayout()
        fields.addWidget(QLabel("Pulse rate"))
        self.pulse_rate = QSpinBox()
        self.pulse_rate.setRange(1, 2000)
        self.pulse_rate.setValue(500)
        self.pulse_rate.setSuffix(" pulses/s")
        fields.addWidget(self.pulse_rate)
        fields.addWidget(QLabel("5 µs pulses; DM542: 1600 pulses/rev"))
        motor_layout.addLayout(fields)
        buttons = QHBoxLayout()
        self.motor_buttons = []
        for label, direction in (("Reverse (hold)", -1), ("Forward (hold)", 1)):
            button = QPushButton(label)
            button.setAutoRepeat(False)
            button.setEnabled(False)
            button.pressed.connect(lambda d=direction: self.start_motor(d))
            button.released.connect(self.stop_motor)
            buttons.addWidget(button)
            self.motor_buttons.append(button)
        self.motor_stop = QPushButton("STOP motor")
        self.motor_stop.setStyleSheet("background: #b00020; color: white; font-weight: bold")
        self.motor_stop.clicked.connect(self.stop_motor)
        buttons.addWidget(self.motor_stop)
        motor_layout.addLayout(buttons)
        self.motor_status = QLabel("Stopped — hold a direction button to run")
        self.motor_status.setWordWrap(True)
        motor_layout.addWidget(self.motor_status)
        layout.addWidget(motor)
        motor.setVisible(allow_bench)
        self.table = QTableWidget(17, 4)
        self.table.setHorizontalHeaderLabels(["Signal", "TB3 terminals", "State", "Output control"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i in range(11):
            self.table.setItem(i, 0, QTableWidgetItem(f"INPUT{i}"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{i + 1} (COMMON: 12)"))
        self.output_checks = []
        for i in range(6):
            self.table.setItem(11 + i, 0, QTableWidgetItem(f"OUT{i} command"))
            self.table.setItem(11 + i, 1, QTableWidgetItem(f"{13 + 2*i}, {14 + 2*i}"))
            check = QCheckBox(f"OUT{i} ON")
            check.setEnabled(False)
            check.toggled.connect(lambda enabled, index=i: self.set_output(index, enabled))
            self.output_checks.append(check)
            self.table.setCellWidget(11 + i, 3, check)
        for row in range(17):
            self.table.setItem(row, 2, QTableWidgetItem("UNKNOWN"))
        layout.addWidget(self.table)
        self.all_off = QPushButton("All outputs OFF")
        self.all_off.setEnabled(self.writer is not None)
        self.all_off.clicked.connect(self.switch_all_off)
        layout.addWidget(self.all_off)
        self.command_status = QLabel()
        self.command_status.setWordWrap(True)
        layout.addWidget(self.command_status)
        note = QLabel("Outputs show HAL command states; no physical output feedback is available.\n"
                      "Checkboxes directly switch real OUT0–OUT5 for bench testing.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self.application_state_changed)
        self.refresh()

    def start_motor(self, direction):
        try:
            self.stepgen.start(direction, self.pulse_rate.value())
            rpm = self.pulse_rate.value() * 60 / 1600
            self.motor_status.setText(f"{'Forward' if direction > 0 else 'Reverse'}: "
                                      f"{self.pulse_rate.value()} pulses/s (~{rpm:.2f} RPM at 1600 pulses/rev)")
            self.pulse_rate.setEnabled(False)
        except Exception as exc:
            self.motor_status.setText(f"Motor start failed: {exc}")

    def stop_motor(self):
        stopped = True
        try:
            self.stepgen.stop()
            self.motor_status.setText("Stopped — pulse generation disabled")
        except Exception as exc:
            stopped = False
            self.motor_status.setText(f"Motor stop failed: {exc}")
        self.pulse_rate.setEnabled(True)
        return stopped

    def application_state_changed(self, state):
        if state != Qt.ApplicationActive and self.stepgen.active:
            self.stop_motor()

    def hideEvent(self, event):
        if self.stepgen.active:
            self.stop_motor()
        super().hideEvent(event)

    def shutdown(self):
        self.timer.stop()
        if self.test:
            self.lock_test()
        self.stop_motor()

    def refresh_motor(self, healthy):
        ready = healthy and self.stepgen.writer is not None
        try:
            self.reader(STEPGEN + ".enable")
        except Exception:
            ready = False
        if not ready and self.stepgen.active:
            if self.stop_motor():
                self.motor_status.setText("Motor stopped: Mesa/STEPGEN0 unavailable; release and press again after recovery")
        for button in self.motor_buttons:
            button.setEnabled(ready)
        self.motor_stop.setEnabled(self.stepgen.writer is not None)
        self.pulse_rate.setEnabled(not self.stepgen.active)

    def set_output(self, index, enabled):
        try:
            if self.test:
                if enabled and not self.confirm_on(f"OUT{index}"):
                    self.refresh()
                    return
                self.test.output(index, enabled)
            else:
                write_output(self.reader, self.writer, index, enabled)
            self.command_status.setText(f"OUT{index}: {'ON' if enabled else 'OFF'} command sent")
        except Exception as exc:
            self.command_status.setText(f"OUT{index} command failed: {exc}")
        self.refresh()

    def switch_all_off(self):
        if self.test:
            failures = self.test.end(force=True)
            self.command_status.setText("; ".join(failures) if failures else "All outputs and spindle OFF commands sent")
            self.refresh()
            return
        failures = []
        for index in range(6):
            try:
                write_output(self.reader, self.writer, index, False)
            except Exception as exc:
                failures.append(f"OUT{index}: {exc}")
        self.command_status.setText("; ".join(failures) if failures else "All six OFF commands sent")
        self.refresh()

    def refresh(self):
        if self.test and self.test.active:
            try:
                ready = self.test.ready()
            except Exception:
                ready = False
            if not ready:
                failures = self.test.end()
                self.command_status.setText("Test locked: machine unavailable. " + "; ".join(failures))
        try:
            snapshot = read_snapshot(self.reader)
        except Exception as exc:
            self.status.setText(f"Mesa unavailable: {exc}")
            self.status.setStyleSheet("color: #b00020")
            self.errors.setText("Packet errors: unavailable")
            self.show_states(None)
            self.refresh_motor(False)
            return
        self.errors.setText(f"Packet errors since start: {snapshot['errors']}")
        self.status.setText(snapshot["status"])
        self.status.setStyleSheet("color: #18702b" if snapshot["healthy"] else "color: #b00020")
        values = snapshot["inputs"] + snapshot["outputs"] if snapshot["healthy"] else None
        self.show_states(values)
        self.refresh_motor(snapshot["healthy"])

    def show_states(self, values):
        from PyQt5.QtGui import QColor
        for row in range(17):
            value = values[row] if values is not None else None
            item = self.table.item(row, 2)
            item.setText("UNKNOWN" if value is None else ("ON / TRUE" if value else "OFF / FALSE"))
            item.setBackground(QColor("#d9e0e8" if value is None else ("#bce8c6" if value else "#f0f0f0")))
        for index, check in enumerate(self.output_checks):
            # Reflect terminal/external commands without writing them back to HAL.
            check.blockSignals(True)
            check.setChecked(bool(values[11 + index]) if values is not None else False)
            check.blockSignals(False)
            check.setEnabled(values is not None and self.writer is not None and
                             (self.test is None or self.test.active))
        if self.test:
            self.spindle_on.setEnabled(values is not None and self.test.active)
            self.unlock_button.setText("Output test ENABLED" if self.test.active else "Enable output test")

    def confirm_on(self, target):
        return QMessageBox.warning(self, "Real output test",
            f"Enable {target}? Connected equipment may move or start immediately.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def unlock_test(self):
        if self.test.active:
            return
        try:
            if not self.confirm_on("OUTPUT TEST MODE (OUT0–OUT5 and spindle)"):
                return
            self.test.begin()
            self.command_status.setText("Output test enabled — runs until OFF/STOP; axis jog and homing are blocked")
        except Exception as exc:
            QMessageBox.warning(self, "Output test", str(exc))
        self.refresh()

    def lock_test(self):
        failures = self.test.end()
        self.command_status.setText("; ".join(failures) if failures else "Test locked — OFF commands sent")
        self.refresh()

    def start_spindle_test(self):
        if not self.confirm_on(f"SPINDLE at {self.rpm.value()} RPM (forward)"):
            return
        try:
            self.test.spindle(True, self.rpm.value())
            self.command_status.setText("Spindle ON command sent")
        except Exception as exc:
            self.command_status.setText(str(exc))

    def stop_spindle_test(self):
        try:
            self.test.spindle(False)
            self.command_status.setText("Spindle OFF command sent")
        except Exception as exc:
            self.command_status.setText(str(exc))

