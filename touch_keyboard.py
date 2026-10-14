"""Touch-only input dialog for the machine screen; mouse editing stays native."""
from PyQt5.QtCore import QObject, QEvent, Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QAbstractSpinBox, QDialog, QLineEdit,
                            QGridLayout, QVBoxLayout, QPushButton, QMessageBox)


class TouchKeyboard(QObject):
    def __init__(self, screen, table):
        super().__init__(screen)
        self.screen, self.table = screen, table
        self.busy = False
        for field in screen.findChildren(QLineEdit):
            field.setAttribute(Qt.WA_AcceptTouchEvents)
        table.viewport().setAttribute(Qt.WA_AcceptTouchEvents)
        QApplication.instance().installEventFilter(self)

    def shutdown(self):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ChildPolished:
            child = event.child()
            if isinstance(child, QLineEdit) and self.screen.isAncestorOf(child):
                child.setAttribute(Qt.WA_AcceptTouchEvents)
        if event.type() != QEvent.TouchBegin or self.busy:
            return False
        target = None
        if isinstance(watched, QLineEdit) and self.screen.isAncestorOf(watched):
            if watched.isEnabled() and not watched.isReadOnly():
                target = watched
        elif watched is self.table.viewport() and self.table.isEnabled():
            points = event.touchPoints()
            if points:
                item = self.table.itemAt(points[0].pos().toPoint())
                if item is not None and item.column() in (1, 2, 3, 4) and item.flags() & Qt.ItemIsEditable:
                    target = item
        if target is None:
            return False
        # Consume the original touch so Qt cannot also synthesize a mouse edit.
        event.accept()
        self.busy = True
        QTimer.singleShot(0, lambda: self.open_target(target))
        return True

    def open_target(self, target):
        try:
            backend = getattr(self.screen, 'backend', None)
            if backend is not None:
                backend.stop_jog()
            spin = target.parentWidget() if isinstance(target, QLineEdit) else None
            numeric = isinstance(spin, QAbstractSpinBox) or not isinstance(target, QLineEdit)
            original = spin.cleanText() if isinstance(spin, QAbstractSpinBox) else target.text()
            dialog = QDialog(self.screen)
            dialog.setWindowTitle('Enter number' if numeric else 'Enter text')
            layout = QVBoxLayout(dialog)
            entry = QLineEdit(original)
            entry.setMinimumHeight(45)
            if isinstance(target, QLineEdit):
                entry.setEchoMode(target.echoMode())
            layout.addWidget(entry)
            grid = QGridLayout()
            layout.addLayout(grid)
            shift = QPushButton('Shift')
            shift.setCheckable(True)
            if not numeric:
                layout.addWidget(shift)
            keys = ['789', '456', '123', '-0,'] if numeric else ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm', '-_./,: ']
            for row, chars in enumerate(keys):
                for col, char in enumerate(chars):
                    button = QPushButton(char if char != ' ' else 'Space')
                    button.setMinimumSize(55, 50)
                    button.clicked.connect(lambda checked=False, char=char: entry.insert(char.upper() if shift.isChecked() else char))
                    grid.addWidget(button, row, col)
            actions = [('⌫', entry.backspace), ('Clear', entry.clear),
                       ('OK', dialog.accept), ('Cancel', dialog.reject)]
            for col, (label, callback) in enumerate(actions):
                button = QPushButton(label)
                button.setMinimumSize(70, 50)
                button.clicked.connect(callback)
                grid.addWidget(button, len(keys), col)
            entry.selectAll()
            entry.setFocus()
            entry.returnPressed.connect(dialog.accept)
            for button in dialog.findChildren(QPushButton):
                button.setAutoDefault(False)
            while dialog.exec_() == QDialog.Accepted:
                value = entry.text()
                if numeric:
                    value = value.replace(',', '.')
                    try:
                        number = float(value)
                        if isinstance(spin, QAbstractSpinBox):
                            if not spin.minimum() <= number <= spin.maximum():
                                raise ValueError('Value outside allowed range')
                            if not hasattr(spin, 'decimals') or spin.decimals() == 0:
                                if not number.is_integer():
                                    raise ValueError('Enter a whole number')
                                number = int(number)
                            spin.setValue(number)
                        else:
                            import math
                            if not math.isfinite(number):
                                raise ValueError('Enter a finite number')
                            target.setText(value)
                        break
                    except ValueError as exc:
                        QMessageBox.warning(dialog, 'Input', str(exc))
                else:
                    target.setText(value)
                    target.editingFinished.emit()
                    break
        finally:
            self.busy = False
