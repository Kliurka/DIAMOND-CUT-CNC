"""LinuxCNC manual and AUTO control through NML; no direct stepgen writes."""
import math
from pathlib import Path
import time

from gcode_playback import parse_program
from machine_settings import save_limits, validate_limits, save_rapids

AXES = "XYZ"


class LinuxCNCControl:
    def __init__(self, api, ini, healthy=lambda: True, ini_path=None):
        self.api = api
        self.ini = ini
        self.ini_path = Path(ini_path).resolve() if ini_path else None
        self.limits_pending = False
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
        self.table_locked = False
        self.output_test_active = False
        self.output_test_stop = None
        self.program_running = False
        self.program_seen_busy = False
        self.program_started = 0

    def snapshot(self):
        self.stat.poll()
        s, api = self.stat, self.api
        healthy = bool(self.healthy())
        on = s.task_state == api.STATE_ON
        homing = any(j.get("homing", False) for j in s.joint[:3])
        if self.program_running:
            if not healthy or not on:
                self.stop()
            elif s.interp_state != api.INTERP_IDLE:
                self.program_seen_busy = True
            elif s.inpos and (self.program_seen_busy or time.monotonic() - self.program_started > 1):
                self.cmd.mode(api.MODE_MANUAL)
                self.program_running = False
        ready = (healthy and on and s.task_mode == api.MODE_MANUAL
                 and s.interp_state == api.INTERP_IDLE and not homing and not self.program_running)
        test_ready = ready
        ready = ready and not self.output_test_active
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
                "homed": bool(s.homed[0] and s.homed[2]), "homing": homing, "stationary": bool(s.inpos),
                "can_touch_off": bool(s.homed[0] and s.homed[2]), "table_locked": self.table_locked,
                "test_ready": test_ready, "running": self.program_running,
                "current_line": int(getattr(s, "motion_line", 0))}

    def require_ready(self, homed=False):
        state = self.snapshot()
        if not state["ready"]:
            raise RuntimeError("Requires healthy Mesa, machine ON and idle Manual mode")
        if homed and not state["can_touch_off"]:
            raise RuntimeError("Press Home All first, wait for Homed, then set Work X/Z zero. "
                               "X and Z must be homed; the manual table does not require homing.")
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
        if axis == "Y" and self.table_locked:
            raise RuntimeError("Table is locked")
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
            try:
                if self.output_test_stop is not None:
                    self.output_test_stop()
            finally:
                self.cmd.abort()
                if self.program_running:
                    try:
                        self.cmd.spindle(self.api.SPINDLE_OFF)
                    finally:
                        self.program_running = False
                        self.cmd.wait_complete(1)
                        self.cmd.mode(self.api.MODE_MANUAL)

    def coordinate_limits(self):
        return validate_limits({axis: (self.ini.find('AXIS_' + axis, 'MIN_LIMIT'),
                                      self.ini.find('AXIS_' + axis, 'MAX_LIMIT'))
                                for axis in AXES})

    def save_coordinate_limits(self, limits):
        state = self.snapshot()
        if (state['on'] or not state['stationary'] or state['homing']
                or self.program_running or self.output_test_active or self.active_jog is not None):
            raise RuntimeError('Turn Machine OFF and stop motion before saving limits')
        if self.ini_path is None:
            raise RuntimeError('Machine INI path is unavailable')
        save_limits(self.ini_path, limits)
        self.limits_pending = True

    def save_rapid_speeds(self, speeds):
        state = self.snapshot()
        if (state['on'] or not state['stationary'] or state['homing']
                or self.program_running or self.output_test_active or self.active_jog is not None):
            raise RuntimeError('Turn Machine OFF and stop motion before saving rapid speeds')
        if self.ini_path is None:
            raise RuntimeError('Machine INI path is unavailable')
        save_rapids(self.ini_path, speeds)
        self.limits_pending = True

    def run_program(self, path):
        if self.limits_pending:
            raise RuntimeError('Restart LinuxCNC to activate the saved machine settings')
        state = self.require_ready(homed=True)
        if not state["stationary"] or self.active_jog is not None:
            raise RuntimeError("Stop motion before Run")
        if getattr(self.stat, "g5x_index", 1) != 1 or self.stat.rotation_xy != 0:
            raise RuntimeError("Run requires G54 with zero XY rotation")
        path = Path(path).resolve()
        moves = parse_program(path.read_text(), start=(state["work"]["X"], state["work"]["Z"]), require_preamble=True)
        for move in moves:
            for axis, value, index in (("X", move.x, 0), ("Z", move.z, 2)):
                low = self.ini.find("AXIS_" + axis, "MIN_LIMIT")
                high = self.ini.find("AXIS_" + axis, "MAX_LIMIT")
                if low is None or high is None:
                    raise RuntimeError(f"Missing {axis} soft limits in INI")
                # The generated header uses G49: no active tool-length offset.
                machine = value + self.stat.g5x_offset[index] + self.stat.g92_offset[index]
                if not float(low) <= machine <= float(high):
                    raise RuntimeError(f"Line {move.line}: {axis} {machine:.4f} mm exceeds machine limits")
        self.stop_jog()
        try:
            self.cmd.mode(self.api.MODE_AUTO)
            if self.cmd.wait_complete(1) != self.api.RCS_DONE:
                raise RuntimeError("AUTO mode switch failed")
            self.cmd.program_open(str(path))
            if self.cmd.wait_complete(1) != self.api.RCS_DONE:
                raise RuntimeError("G-code load failed")
            # Recheck interlocks just before issuing the start command.
            self.stat.poll()
            if (not self.healthy() or self.stat.task_state != self.api.STATE_ON
                    or not self.stat.inpos or not (self.stat.homed[0] and self.stat.homed[2])
                    or self.output_test_active or self.stat.interp_state != self.api.INTERP_IDLE):
                raise RuntimeError("Run conditions changed while loading")
            self.program_running = True
            self.program_seen_busy = False
            self.program_started = time.monotonic()
            self.cmd.auto(self.api.AUTO_RUN, 0)
        except Exception:
            self.cmd.abort()
            self.program_running = False
            self.cmd.mode(self.api.MODE_MANUAL)
            raise

    def home_all(self):
        if not self.require_ready()["stationary"]:
            raise RuntimeError("Stop motion before homing")
        self.stop_jog()
        self.cmd.teleop_enable(0)
        if self.cmd.wait_complete(1.0) != self.api.RCS_DONE:
            raise RuntimeError("Joint mode switch did not complete")
        self.cmd.home(-1)

    def set_table_locked(self, locked):
        self.table_locked = bool(locked)
        if self.table_locked and self.active_jog is not None and self.active_jog[1] == 1:
            self.stop_jog()

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
            if self.cmd.wait_complete(1.0) != self.api.RCS_DONE:
                raise RuntimeError("Return to Manual mode did not complete")
