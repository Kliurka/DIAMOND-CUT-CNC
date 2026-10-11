"""Read-only G-code text with optional one-based line numbers."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFontDatabase, QPainter
from PyQt5.QtWidgets import QPlainTextEdit, QWidget


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class GCodeText(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.numbers_visible = True
        self.number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_number_margin)
        self.updateRequest.connect(self.update_number_area)
        self.cursorPositionChanged.connect(self.number_area.update)
        self.update_number_margin()

    def number_width(self):
        if not self.numbers_visible:
            return 0
        return 12 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def set_line_numbers_visible(self, visible):
        self.numbers_visible = bool(visible)
        self.number_area.setVisible(self.numbers_visible)
        self.update_number_margin()
        self.resize_number_area()

    def update_number_margin(self, *unused):
        self.setViewportMargins(self.number_width(), 0, 0, 0)
        self.resize_number_area()
        self.number_area.update()

    def resize_number_area(self):
        rect = self.contentsRect()
        self.number_area.setGeometry(rect.left(), rect.top(), self.number_width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_number_area()

    def update_number_area(self, rect, dy):
        if dy:
            self.number_area.scroll(0, dy)
        else:
            self.number_area.update(0, rect.y(), self.number_width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_number_margin()

    def paint_line_numbers(self, event):
        painter = QPainter(self.number_area)
        painter.fillRect(event.rect(), QColor('#e5e8ec'))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        number = block.blockNumber()
        active = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(QColor('#111111' if number == active else '#67717d'))
                font = painter.font()
                font.setBold(number == active)
                painter.setFont(font)
                painter.drawText(0, top, self.number_area.width() - 5,
                                 self.fontMetrics().height(), Qt.AlignRight, str(number + 1))
            top += height
            block = block.next()
            number += 1
