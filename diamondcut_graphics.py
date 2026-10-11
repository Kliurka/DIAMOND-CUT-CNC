"""Machine-oriented X/Z preview; display settings do not change kinematics."""
from math import cos, radians, sin

from OpenGL import GL
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor
from qtvcp.widgets.gcode_graphics import GCodeGraphics


class DiamondCutGraphics(GCodeGraphics):
    preview_status = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # The stock lathe renderer rotates the cone onto X. Our tool is on Z.
        self.lathe_option = False
        self.current_view = "y"
        self.show_small_origin = False
        self.show_extents_option = False
        self.show_overlay = False
        self.show_live_plot = False
        self.use_gradient_background = False
        self.setBackgroundColor(QColor(24, 27, 32))


    def get_show_tool(self):
        # Draw our opaque marker last, rather than the translucent stock cone.
        return False

    def get_show_live_plot(self):
        return False

    def refresh_work_coordinates(self):
        """Reparse the displayed file after a completed work-offset change."""
        self.stat.poll()
        self.clear_live_plotter()
        if self._reload_filename:
            self.load_program(None, self._reload_filename)
        self.reset_default_view()

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

    def project_xz(self, point, matrix):
        # OpenGL stores basis vectors/translation in columns. Use the current
        # modelview, including user pan/rotation, with native ortho scale.
        vector = (*point, 1)
        eye = [sum(vector[j] * matrix[j][i] for j in range(4)) for i in range(2)]
        scale = self.winfo_width() / (2 * abs(self.distance or 1) ** .55555)
        return (self.winfo_width() / 2 + eye[0] * scale,
                self.winfo_height() / 2 - eye[1] * scale)

    def paintGL(self):
        # One framebuffer for paths and markers. Always clear the full frame,
        # including when the native renderer catches an error and returns early.
        matrix = GL.glGetDoublev(GL.GL_MODELVIEW_MATRIX)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glColorMask(True, True, True, True)
        GL.glClearColor(24 / 255, 27 / 255, 32 / 255, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        super().paintGL()
        self.stat.poll()
        origin, tip = self.work_origin(), self.tool_tip()
        self.draw_screen_markers(self.project_xz(origin, matrix),
                                 self.project_xz(tip, matrix))
        units = (self.stat.linear_units or 1) * 25.4
        dx, dy, dz = (a - b for a, b in zip(tip, origin))
        angle = radians(self.stat.rotation_xy)
        work_x = (cos(angle) * dx + sin(angle) * dy) * units
        self.preview_status.emit(
            f"Tool Work: X {work_x:+.3f}   Z {dz * units:+.3f} mm\n"
            "Work 0: X 0.000   Z 0.000  |  Cyan origin / Yellow tool")

    def draw_screen_markers(self, origin, tip):
        width, height = self.winfo_width(), self.winfo_height()
        GL.glPushAttrib(GL.GL_ENABLE_BIT | GL.GL_CURRENT_BIT | GL.GL_LINE_BIT)
        GL.glDisable(GL.GL_LIGHTING)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glOrtho(0, width, height, 0, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        try:
            x, y = tip
            GL.glColor3f(1, .85, .1)
            GL.glBegin(GL.GL_TRIANGLES)
            for px, py in ((x, y), (x - 9, y - 27), (x + 9, y - 27)):
                GL.glVertex2f(px, py)
            GL.glEnd()
            x, y = origin
            GL.glColor3f(0, 1, 1)
            GL.glLineWidth(2)
            GL.glBegin(GL.GL_LINES)
            for px, py in ((x-12,y),(x+12,y),(x,y-12),(x,y+12)):
                GL.glVertex2f(px, py)
            GL.glEnd()
            GL.glBegin(GL.GL_LINE_LOOP)
            for step in range(32):
                angle = radians(step * 360 / 32)
                GL.glVertex2f(x + 8*cos(angle), y + 8*sin(angle))
            GL.glEnd()
            GL.glTranslatef(x + 14, y - 12, 0)
            GL.glScalef(8, -8, 1)
            # LinuxCNC Hershey only provides digits, XYZ/UVW, G, '-' and '.'.
            self.hershey.plot_string("X0Z0", .1)
        finally:
            GL.glPopMatrix()
            GL.glMatrixMode(GL.GL_PROJECTION)
            GL.glPopMatrix()
            GL.glMatrixMode(GL.GL_MODELVIEW)
            GL.glPopAttrib()
