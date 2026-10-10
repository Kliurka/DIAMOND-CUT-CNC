"""Manual LinuxCNC control through NML; never writes Mesa stepgen pins."""
import math

AXES = "XYZ"


class LinuxCNCControl:
    def __init__(self, api, ini, healthy=lambda: True):
        self.api = api
        self.ini = ini
        self.stat = api.stat()
        self.cmd = api.command()
        self.healthy = healthy
        kins = ini.find("KINS", "KINEMATICS") or ""
        coords = "".join((ini.find("TRAJ", "COORDINATES") or "").split()).upper()
        if kins.split()[0:1] != ["trivkins"] or coords != "XYZ":
            raise ValueError("Real controls currently require trivkins XYZ with three joints")
        if int(ini.find("KINS", "JOINTS") or 0) != 3:
            raise ValueError("Real controls require exactly three XYZ joints")
        for part in kins.split()[1:]:
            if part.startswith("coordinates=") and part.split("=", 1)[1].upper() != coords:
                raise ValueError("Kinematics joint order must be XYZ")
        if (ini.find("TRAJ", "LINEAR_UNITS") or "").lower() not in ("mm", "1", "1.0"):
            raise ValueError("Real controls require millimeter machine units")
        self.limits = {a: float(ini.find("AXIS_" + a, "MAX_VELOCITY") or 0)
                       for a in AXES}
        if any(not math.isfinite(v) or v <= 0 for v in self.limits.values()):
            raise ValueError("Each axis needs a positive MAX_VELOCITY")
        self.active_jog = None

    def snapshot(self):
        self.stat.poll()
        s, api = self.stat, self.api
        healthy = bool(self.healthy())
        on = s.task_state == api.STATE_ON
        homing = any(j.get("homing", False) for j in s.joint[:3])
        ready = (healthy and on and s.task_mode == api.MODE_MANUAL
                 and s.interp_state == api.INTERP_IDLE and not homing)
        if self.active_jog is not None and not ready:
            self.stop_jog()
        machine = dict(zip(AXES, s.actual_position[:3]))
        # Before homing, trivkins joint coordinates provide the manual position.
        if s.motion_mode == api.TRAJ_MODE_FREE:
            machine = dict(zip(AXES, s.joint_actual_position[:3]))
        work = {a: machine[a] - s.g5x_offset[i] - s.g92_offset[i] - s.tool_offset[i]
                for i, a in enumerate(AXES)}
        angle = math.radians(s.rotation_xy)
        x, y = work["X"], work["Y"]
        work["X"] = x * math.cos(angle) + y * math.sin(angle)
        work["Y"] = -x * math.sin(angle) + y * math.cos(angle)
        return {"machine": machine, "work": work, "ready": ready, "healthy": healthy,
                "on": on, "estop": s.task_state == api.STATE_ESTOP,
                "homed": all(s.homed[:3]), "homing": homing, "stationary": bool(s.inpos)}

    def require_ready(self, homed=False):
        state = self.snapshot()
        if not state["ready"]:
            raise RuntimeError("Requires healthy Mesa, machine ON and idle Manual mode")
        if homed and not state["homed"]:
            raise RuntimeError("Home all joints before changing work zero")
        return state

    def toggle_estop(self):
        self.stat.poll()
        if self.stat.task_state == self.api.STATE_ESTOP:
            self.cmd.state(self.api.STATE_ESTOP_RESET)
        else:
            self.stop_jog()
            self.cmd.state(self.api.STATE_ESTOP)

    def toggle_power(self):
        self.stat.poll()
        if self.stat.task_state == self.api.STATE_ON:
            self.stop_jog()
            self.cmd.state(self.api.STATE_OFF)
        else:
            if not self.healthy():
                raise RuntimeError("Mesa communication fault")
            if self.stat.task_state == self.api.STATE_ESTOP:
                raise RuntimeError("Reset E-stop first")
            self.cmd.mode(self.api.MODE_MANUAL)
            self.cmd.state(self.api.STATE_ON)

    def jog(self, axis, sign, speed_mm_min, distance=None):
        if axis not in AXES or sign not in (-1, 1):
            raise ValueError("Invalid jog axis or direction")
        if not math.isfinite(speed_mm_min) or speed_mm_min <= 0:
            raise ValueError("Jog speed must be positive")
        if distance is not None and (not math.isfinite(distance) or distance <= 0):
            raise ValueError("Jog distance must be positive")
        self.require_ready()
        self.stop_jog()
        mode = self.stat.motion_mode
        if mode not in (self.api.TRAJ_MODE_FREE, self.api.TRAJ_MODE_TELEOP):
            raise RuntimeError("Motion controller is not in joint/axis jog mode")
        joint_mode = mode == self.api.TRAJ_MODE_FREE
        index = AXES.index(axis)
        speed = sign * min(speed_mm_min / 60, self.limits[axis])
        self.active_jog = (joint_mode, index)
        try:
            if distance is None:
                self.cmd.jog(self.api.JOG_CONTINUOUS, joint_mode, index, speed)
            else:
                self.cmd.jog(self.api.JOG_INCREMENT, joint_mode, index, speed, distance)
        except Exception:
            self.stop_jog()
            raise

    def stop_jog(self):
        if self.active_jog is not None:
            joint_mode, index = self.active_jog
            self.cmd.jog(self.api.JOG_STOP, joint_mode, index)
            self.active_jog = None

    def stop(self):
        try:
            self.stop_jog()
        finally:
            self.cmd.abort()

    def home_all(self):
        if not self.require_ready()["stationary"]:
            raise RuntimeError("Stop motion before homing")
        self.stop_jog()
        self.cmd.teleop_enable(0)
        if self.cmd.wait_complete(1.0) != self.api.RCS_DONE:
            raise RuntimeError("Joint mode switch did not complete")
        self.cmd.home(-1)

    def zero(self, axis):
        if axis not in AXES:
            raise ValueError("Invalid axis")
        if not self.require_ready(homed=True)["stationary"]:
            raise RuntimeError("Stop motion before changing work zero")
        self.stop_jog()
        self.cmd.mode(self.api.MODE_MDI)
        try:
            if self.cmd.wait_complete(1.0) != self.api.RCS_DONE:
                raise RuntimeError("MDI mode switch did not complete")
            # Explicit metric units; P0 selects the active work coordinate system.
            self.cmd.mdi(f"G21 G10 L20 P0 {axis}0")
            if self.cmd.wait_complete(1.0) != self.api.RCS_DONE:
                self.cmd.abort()
                raise RuntimeError("Work zero command did not complete")
        finally:
            self.cmd.mode(self.api.MODE_MANUAL)
