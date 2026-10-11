"""Machine-oriented X/Z preview; display settings do not change kinematics."""
from math import cos, radians, sin

from OpenGL import GL
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget
from qtvcp.widgets.gcode_graphics import GCodeGraphics


class PreviewMarkers(QWidget):
    """Qt overlay independent of the native tool/DRO OpenGL rendering."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.origin = self.tip = None
        self.caption = ""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(6, 6, self.width() - 12, 46, QColor(24, 27, 32, 235))
        painter.setPen(QColor("white"))
        painter.drawText(self.rect().adjusted(12, 8, -12, -8),
                         Qt.AlignLeft | Qt.AlignTop, self.caption)
        if self.tip is not None:
            x, y = self.tip
            painter.setPen(QPen(QColor("#ffdb19"), 2))
            painter.setBrush(QColor("#ffdb19"))
            painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x - 9, y - 27),
                                            QPointF(x + 9, y - 27)]))
        if self.origin is not None:
            x, y = self.origin
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#00ffff"), 2))
            painter.drawEllipse(QPointF(x, y), 8, 8)
            painter.drawLine(QPointF(x - 12, y), QPointF(x + 12, y))
            painter.drawLine(QPointF(x, y - 12), QPointF(x, y + 12))
            painter.drawText(QPointF(x + 14, y - 12), "Work 0")


class DiamondCutGraphics(GCodeGraphics):
    def __init__(self, parent=None):
        super().__init__(parent)
        # The stock lathe renderer rotates the cone onto X. Our tool is on Z.
        self.lathe_option = False
        self.current_view = "y"
        self.show_small_origin = False
        self.show_extents_option = False
        self.show_overlay = False
        self.use_gradient_background = False
        self.setBackgroundColor(QColor(24, 27, 32))
        self.markers = PreviewMarkers(self)

    def get_show_tool(self):
        # Draw our opaque marker last, rather than the translucent stock cone.
        return False

    def tool_tip(self):
        return tuple(a - b for a, b in zip(
            self.to_internal_units(self.stat.actual_position)[:3],
            self.to_internal_units(self.stat.tool_offset)[:3]))

    def get_current_tool(self):
        # Always use a tip-position cone, even when a tool-table entry is loaded.
        return None

    def work_origin(self):
        """Active G5x + rotated G92 origin, in the renderer's inch units."""
        g5x = self.to_internal_units(self.stat.g5x_offset)
        g92 = self.to_internal_units(self.stat.g92_offset)
        angle = radians(self.stat.rotation_xy)
        return (g5x[0] + cos(angle) * g92[0] - sin(angle) * g92[1],
                g5x[1] + sin(angle) * g92[0] + cos(angle) * g92[1],
                g5x[2] + g92[2])

    def set_view_y(self):
        # +90 about X projects +X right and +Z down (home left/top).
        self.reset()
        GL.glRotatef(90, 1, 0, 0)
        self.stat.poll()
        mid, size = self.extents_info()
        origin = self.work_origin()
        tip = self.tool_tip()
        low = [min(mid[i] - size[i] / 2, origin[i], tip[i], 0) for i in range(3)]
        high = [max(mid[i] + size[i] / 2, origin[i], tip[i], 0) for i in range(3)]
        mid = [(a + b) / 2 for a, b in zip(low, high)]
        GL.glTranslatef(*[-value for value in mid])
        self.set_eyepoint_from_extents(1.2 * (high[0] - low[0]),
                                     1.2 * (high[2] - low[2]))
        self.perspective = False
        self.lat, self.lon = 90, 0
        self._redraw()

    def reset_default_view(self):
        self.set_view("y")

    def draw_axes(self, number, letters="XYZ"):
        # Suppress stock XYZ axes: Y is a table lift, not a cutting coordinate.
        GL.glNewList(number, GL.GL_COMPILE)
        GL.glEndList()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "markers"):
            self.markers.setGeometry(self.rect())
            self.markers.raise_()

    def project_xz(self, point, matrix):
        # OpenGL stores basis vectors/translation in columns. Use the current
        # modelview, including user pan/rotation, with native ortho scale.
        vector = (*point, 1)
        eye = [sum(vector[j] * matrix[j][i] for j in range(4)) for i in range(2)]
        scale = self.winfo_width() / (2 * abs(self.distance or 1) ** .55555)
        return (self.winfo_width() / 2 + eye[0] * scale,
                self.winfo_height() / 2 - eye[1] * scale)

    def paintGL(self):
        # Capture the view before native rendering; its paintGL catches errors
        # internally, so markers must not depend on reaching the end of redraw.
        matrix = GL.glGetDoublev(GL.GL_MODELVIEW_MATRIX)
        super().paintGL()
        self.stat.poll()
        origin, tip = self.work_origin(), self.tool_tip()
        self.markers.origin = self.project_xz(origin, matrix)
        self.markers.tip = self.project_xz(tip, matrix)
        units = (self.stat.linear_units or 1) * 25.4
        dx, dy, dz = (a - b for a, b in zip(tip, origin))
        angle = radians(self.stat.rotation_xy)
        work_x = (cos(angle) * dx + sin(angle) * dy) * units
        self.markers.caption = (
            f"Tool Work: X {work_x:+.3f}   Z {dz * units:+.3f} mm\n"
            "Work 0: X 0.000   Z 0.000  |  Cyan origin / Yellow tool")
        self.markers.setGeometry(self.rect())
        self.markers.raise_()
        self.markers.update()
