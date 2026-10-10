"""Mesa I/O monitor and manual bench output controls for QtVCP."""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                            QTableWidgetItem, QCheckBox, QPushButton)

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
    def __init__(self, reader, parent=None, writer=None):
        super().__init__(parent)
        self.reader = reader
        self.writer = writer
        layout = QVBoxLayout(self)
        title = QLabel("<h2>Mesa 7i96S — I/O monitor</h2>")
        layout.addWidget(title)
        layout.addWidget(QLabel("Real board inputs. Motion and laser scanning remain simulated."))
        self.status = QLabel("Waiting for HAL")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.errors = QLabel()
        layout.addWidget(self.errors)
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
        self.refresh()

    def set_output(self, index, enabled):
        try:
            write_output(self.reader, self.writer, index, enabled)
            self.command_status.setText(f"OUT{index}: {'ON' if enabled else 'OFF'} command sent")
        except Exception as exc:
            self.command_status.setText(f"OUT{index} command failed: {exc}")
        self.refresh()

    def switch_all_off(self):
        failures = []
        for index in range(6):
            try:
                write_output(self.reader, self.writer, index, False)
            except Exception as exc:
                failures.append(f"OUT{index}: {exc}")
        self.command_status.setText("; ".join(failures) if failures else "All six OFF commands sent")
        self.refresh()

    def refresh(self):
        try:
            snapshot = read_snapshot(self.reader)
        except Exception as exc:
            self.status.setText(f"Mesa unavailable: {exc}")
            self.status.setStyleSheet("color: #b00020")
            self.errors.setText("Packet errors: unavailable")
            self.show_states(None)
            return
        self.errors.setText(f"Packet errors since start: {snapshot['errors']}")
        self.status.setText(snapshot["status"])
        self.status.setStyleSheet("color: #18702b" if snapshot["healthy"] else "color: #b00020")
        values = snapshot["inputs"] + snapshot["outputs"] if snapshot["healthy"] else None
        self.show_states(values)

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
            check.setEnabled(values is not None and self.writer is not None)

