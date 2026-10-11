"""Machine-oriented X/Z preview; display settings do not change kinematics."""
from math import cos, radians, sin

from OpenGL import GL
from qtvcp.widgets.gcode_graphics import GCodeGraphics


class DiamondCutGraphics(GCodeGraphics):
    def __init__(self, parent=None):
        super().__init__(parent)
        # The stock lathe renderer rotates the cone onto X. Our tool is on Z.
        self.lathe_option = False
        self.current_view = "y"
        self.show_small_origin = False
        self.show_extents_option = False
        self.show_overlay = False

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
        low = [min(mid[i] - size[i] / 2, origin[i], 0) for i in range(3)]
        high = [max(mid[i] + size[i] / 2, origin[i], 0) for i in range(3)]
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

    def user_plot(self):
        # Draw every frame so touch-off/G54/G92 changes immediately move Work 0.
        origin = self.work_origin()
        _, size = self.extents_info()
        radius = max(size[0], size[2], 2) * 0.015
        GL.glPushAttrib(GL.GL_ENABLE_BIT | GL.GL_CURRENT_BIT | GL.GL_LINE_BIT)
        GL.glDisable(GL.GL_LIGHTING)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glColor3f(0, 1, 1)
        GL.glLineWidth(2)
        GL.glPushMatrix()
        GL.glTranslatef(*origin)
        GL.glRotatef(-90, 1, 0, 0)  # readable text in the default X/Z view
        GL.glBegin(GL.GL_LINES)
        for x, y in ((-radius, 0), (radius, 0), (0, -radius), (0, radius)):
            GL.glVertex3f(x, y, 0)
        GL.glEnd()
        GL.glBegin(GL.GL_LINE_LOOP)
        for step in range(32):
            angle = step * 2 * 3.141592653589793 / 32
            GL.glVertex3f(radius * cos(angle), radius * sin(angle), 0)
        GL.glEnd()
        GL.glTranslatef(radius * 1.5, radius * 1.5, 0)
        GL.glScalef(radius, radius, radius)
        self.hershey.plot_string("Work 0", 0.1)
        GL.glPopMatrix()
        GL.glPopAttrib()
