"""Manual lathe tool management backed by LinuxCNC's TOOL_TABLE."""
from pathlib import Path
import math
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QColor, QPolygonF
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QMessageBox)
from lathe_tools import LatheTool, LatheToolTable


class ToolShape(QWidget):
    def __init__(self):
        super().__init__()
        self.tool = None
        self.setMinimumHeight(150)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#161e29'))
        p.setPen(QColor('#eeeeee'))
        if self.tool is None:
            p.drawText(self.rect(), Qt.AlignCenter, 'Select a tool row')
            return
        t = self.tool
        p.drawText(12, 22, f'T{t.number}   R{t.value("D") / 2:g} mm   I{t.value("I"):g}°   J{t.value("J"):g}°   Q{int(t.value("Q"))}')
        # Angle schematic, not a compensated cutting path. Q is the native code.
        x, y = self.width() / 2, self.height() / 2 + 8
        orientation = int(t.value('Q'))
        center = {1: 135, 2: 45, 3: 315, 4: 225, 5: 180, 6: 90, 7: 0, 8: 270}.get(orientation, 0)
        angles = [t.value('I'), t.value('J')]
        if angles[0] == angles[1]:
            angles = [center - 30, center + 30]
        rays = [QPointF(x + 42 * math.sin(math.radians(a)), y + 42 * math.cos(math.radians(a))) for a in angles]
        p.setBrush(QColor('#e9c153'))
        if orientation == 9:
            p.drawEllipse(QPointF(x, y), 25, 25)
        else:
            p.drawPolygon(QPolygonF([QPointF(x, y), *rays]))
            if t.value('D') > 0:
                p.drawEllipse(QPointF(x, y), 5, 5)
        p.setPen(QColor('#89d3ec'))
        p.drawText(12, 46, '+X →   +Z ↓   (not to scale)')
        p.setPen(QColor('#eeeeee'))
        p.drawText(12, self.height() - 8, 'Geometry schematic; Q = LinuxCNC orientation (0–9)')


class ToolsPanel(QWidget):
    def __init__(self, backend, changed, parent=None):
        super().__init__(parent)
        self.backend, self.changed = backend, changed
        self.selected = None
        self.needs_selection = False
        self.table_file = None
        layout = QVBoxLayout(self)
        note = QLabel('Five manually mounted tools. X/Z offsets and nose radius are in mm (radius mode G8).\n'
                      'Save → physically mount tool → Use mounted tool → verify Z0. G43 applies offsets once.\n'
                      'D=2×nose radius, I/J=front/back angles, Q=LinuxCNC orientation. G41/G42 is not enabled.')
        note.setWordWrap(True); layout.addWidget(note)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(5, 8)
        self.table.setHorizontalHeaderLabels(['Tool', 'Name', 'X offset', 'Z offset', 'Nose R', 'Front I °', 'Back J °', 'Q 0–9'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(235)
        self.table.setToolTip('Double-click a cell to edit. X is radius, not diameter. Q: 1=135°, 2=45°, 3=315°, 4=225°, 5=180°, 6=90°, 7=0°, 8=270°, 9=round, 0=unspecified.')
        layout.addWidget(self.table)
        self.shape = ToolShape(); layout.addWidget(self.shape)
        self.table.itemSelectionChanged.connect(self.show_shape)
        self.table.itemChanged.connect(self.show_shape)
        buttons = QHBoxLayout()
        for text, action in [('Save tools', self.save), ('Reload tools', self.reload),
                             ('Use mounted tool', self.use), ('Cancel tool offsets', self.cancel)]:
            button = QPushButton(text); button.clicked.connect(lambda checked=False, fn=action: self.action(fn))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        try:
            path = backend.tool_table_path() if backend else Path.home() / '.config/diamondcut/preview-tool.tbl'
            self.table_file = LatheToolTable(path)
            self.populate()
        except Exception as exc:
            self.status.setText(f'Tool table unavailable: {exc}')
            self.table.setEnabled(False)

    def action(self, fn):
        try:
            if not self.table_file:
                raise ValueError('Configure [EMCIO] TOOL_TABLE first')
            fn()
        except Exception as exc:
            QMessageBox.warning(self, 'Tools', str(exc))

    def populate(self):
        self.table.blockSignals(True)
        for row, t in enumerate(self.table_file.tools.values()):
            vals = [str(t.number), t.comment, t.value('X'), t.value('Z'), t.value('D') / 2,
                    t.value('I'), t.value('J'), int(t.value('Q'))]
            # Place by tool number, even when the source table is unordered.
            row = t.number - 1
            for col, value in enumerate(vals):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.table.selectRow(0)
        self.status.setText(f'{self.table_file.path}\nActive selection: {"T" + str(self.selected) if self.selected else "none"}')
        self.show_shape()

    def row_tool(self, row):
        old = self.table_file.tools[row + 1]
        values = dict(old.values)
        for col, key in [(2, 'X'), (3, 'Z'), (4, 'D'), (5, 'I'), (6, 'J'), (7, 'Q')]:
            values[key] = float(self.table.item(row, col).text()) * (2 if key == 'D' else 1)
        tool = LatheTool(row + 1, values, self.table.item(row, 1).text())
        tool.validate()
        return tool

    def show_shape(self):
        try:
            self.shape.tool = self.row_tool(max(self.table.currentRow(), 0))
        except (ValueError, AttributeError, KeyError):
            self.shape.tool = None
        self.shape.update()

    def save(self):
        if self.backend:
            self.backend.require_tool_idle()
        self.table_file.save([self.row_tool(row) for row in range(5)])
        self.selected = None
        self.needs_selection = True
        self.changed(None)
        if self.backend:
            self.backend.reload_tools()
        self.populate()
        self.status.setText(self.status.text() + '\nSaved. Reapply mounted tool and verify Z0 before Run.')

    def reload(self):
        if self.backend:
            self.backend.require_tool_idle()
            self.backend.reload_tools()
        self.table_file.reload()
        self.selected = None
        self.needs_selection = True
        self.changed(None)
        self.populate()

    def use(self):
        row = max(self.table.currentRow(), 0)
        t = self.row_tool(row)
        if (self.table_file.path.read_bytes() if self.table_file.path.exists() else None) != self.table_file.original:
            raise ValueError('Tool table changed externally: reload before selecting a tool')
        if t.line() != self.table_file.tools[t.number].line() or t.number not in self.table_file.locations:
            raise ValueError('Save the tool before selecting it')
        if QMessageBox.question(self, 'Manually mounted tool',
                f'Confirm T{t.number} is physically mounted. Apply its X/Z offsets?\nNo axis movement is commanded.') != QMessageBox.Yes:
            return
        if self.backend:
            self.backend.select_tool(t.number)
        self.selected = t.number
        self.needs_selection = False
        self.selected_fingerprint = t.fingerprint()
        self.changed(t)
        self.status.setText(f'T{t.number} selected. Verify Z0 at scan start before Run.\n{self.table_file.path}')

    def cancel(self):
        if self.backend:
            self.backend.select_tool(0)
        self.selected = None
        self.needs_selection = True
        self.changed(None)
        self.needs_selection = False
        self.status.setText('Tool compensation cancelled (G49).')

    def program_tool(self):
        if self.needs_selection:
            raise ValueError('Select the mounted tool again after saving/reloading tools (or Cancel tool offsets)')
        if self.selected is None:
            return None
        current = LatheToolTable(self.table_file.path)
        tool = current.tools[self.selected]
        if tool.fingerprint() != self.selected_fingerprint or self.row_tool(self.selected - 1).fingerprint() != self.selected_fingerprint:
            raise ValueError('Tool changed: save and select the mounted tool again')
        return tool

    def program_tools(self):
        return LatheToolTable(self.table_file.path).tools if self.table_file else None
