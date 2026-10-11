"""Password storage and bounded maintenance I/O sessions."""
import hashlib
import hmac
import json
import os
from pathlib import Path


class TestPassword:
    def __init__(self, path=None):
        self.path = Path(path or Path.home() / ".config/diamondcut/output-test-password.json")

    def exists(self):
        return self.path.exists()

    def set(self, password):
        if len(password) < 6:
            raise ValueError("Use at least 6 characters")
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"salt": salt.hex(), "hash": digest.hex()}, f)

    def verify(self, password):
        data = json.loads(self.path.read_text())
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(data["salt"]), 200000)
        return hmac.compare_digest(digest.hex(), data["hash"])


class OutputTest:
    def __init__(self, backend, output_writer):
        self.backend = backend
        self.output_writer = output_writer
        self.active = False

    def ready(self):
        s = self.backend.snapshot()
        return s["test_ready"] and s["stationary"]

    def begin(self):
        if not self.ready() or self.backend.active_jog is not None:
            raise RuntimeError("Requires healthy Mesa, machine ON, idle Manual mode and stopped axes")
        self.active = True
        self.backend.output_test_active = True

    def output(self, index, enabled):
        if index not in range(6):
            raise ValueError("Invalid output")
        if enabled and (not self.active or not self.ready()):
            raise RuntimeError("Output test is locked or machine is unavailable")
        self.output_writer(index, enabled)

    def spindle(self, enabled, rpm=0):
        if enabled and (not self.active or not self.ready() or rpm <= 0):
            raise RuntimeError("Spindle test is locked or machine is unavailable")
        api, cmd = self.backend.api, self.backend.cmd
        cmd.spindle(api.SPINDLE_FORWARD if enabled else api.SPINDLE_OFF, rpm if enabled else 0, 0)

    def end(self, force=False):
        if not self.active and not force:
            return []
        self.active = False
        failures = []
        for i in range(6):
            try:
                self.output(i, False)
            except Exception as exc:
                failures.append(f"OUT{i}: {exc}")
        try:
            self.spindle(False)
        except Exception as exc:
            failures.append(f"Spindle: {exc}")
        # Do not release axis controls if an OFF command could not be sent.
        self.backend.output_test_active = bool(failures)
        return failures
