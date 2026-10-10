"""Manual STEPGEN0 bench control; no LinuxCNC trajectory planner integration."""
import math

STEPGEN = "hm2_7i96s.0.stepgen.00"
SETTINGS = (
    ("control-type", "1"), ("position-scale", "1"), ("step_type", "0"),
    ("steplen", "5000"), ("stepspace", "5000"),
    ("dirsetup", "10000"), ("dirhold", "10000"),
    ("maxvel", "2000"), ("maxaccel", "10000"),
)


class BenchStepgen:
    def __init__(self, writer, healthy):
        self.writer = writer
        self.healthy = healthy
        self.active = False

    def stop(self):
        self.active = False
        if self.writer is None:
            return
        failures = []
        # Attempt disable even if the zero-speed write fails.
        for pin, value in (("velocity-cmd", "0"), ("enable", "false")):
            try:
                self.writer(f"{STEPGEN}.{pin}", value)
            except Exception as exc:
                failures.append(f"{pin}: {exc}")
        if failures:
            raise RuntimeError("; ".join(failures))

    def start(self, direction, pulse_rate):
        if self.writer is None:
            raise RuntimeError("HAL output control unavailable")
        if direction not in (-1, 1):
            raise ValueError("Direction must be -1 or 1")
        if not math.isfinite(pulse_rate) or not 1 <= pulse_rate <= 2000:
            raise ValueError("Pulse rate must be 1 to 2000 pulses/s")
        if not self.healthy():
            raise RuntimeError("Mesa communication fault")
        try:
            self.stop()
            for pin, value in SETTINGS:
                self.writer(f"{STEPGEN}.{pin}", value)
            if not self.healthy():
                raise RuntimeError("Mesa communication fault")
            self.writer(f"{STEPGEN}.enable", "true")
            self.writer(f"{STEPGEN}.velocity-cmd", str(direction * pulse_rate))
            self.active = True
        except Exception as exc:
            try:
                self.stop()
            except Exception as stop_error:
                raise RuntimeError(f"{exc}; stop failed: {stop_error}") from exc
            raise

