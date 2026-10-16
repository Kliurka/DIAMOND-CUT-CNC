"""Five-place editor for the standard LinuxCNC lathe tool table."""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
import tempfile


@dataclass
class LatheTool:
    number: int
    values: dict = field(default_factory=dict)
    comment: str = ''

    def value(self, key):
        return self.values.get(key, 0.)

    def validate(self):
        if not 1 <= self.number <= 5:
            raise ValueError('Use tool numbers 1 to 5')
        if any(not math.isfinite(v) for v in self.values.values()):
            raise ValueError('Tool values must be finite')
        if self.value('D') < 0 or not 0 <= self.value('Q') <= 9 or not float(self.value('Q')).is_integer():
            raise ValueError('Nose diameter must be nonnegative; orientation Q must be 0–9')
        if any(not -360 <= self.value(k) <= 360 for k in ('I', 'J')):
            raise ValueError('Tool angles must be between -360 and 360 degrees')
        if 'P' in self.values and (not float(self.value('P')).is_integer() or not 1 <= self.value('P') <= 99999):
            raise ValueError('Use a positive integer tool pocket')
        if any(abs(self.value(k)) > 1e-9 for k in 'YABCUVW'):
            raise ValueError('This X/Z screen supports only X/Z tool offsets')
        if '\n' in self.comment or '\r' in self.comment:
            raise ValueError('Tool comment must be a single line')

    def fingerprint(self):
        self.validate()
        data = {k: float(self.value(k)) for k in 'XYZABCUVWDIJQ'}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]

    def line(self):
        self.validate()
        data = dict(self.values)
        data.setdefault('P', float(self.number))
        for key in 'XZDIJQ':
            data.setdefault(key, 0.)
        return f'T{self.number} ' + ' '.join(f'{k}{int(v)}' if k in 'PQ' else f'{k}{v:.6f}' for k, v in sorted(data.items())) + ';' + self.comment


class LatheToolTable:
    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        self.original = self.path.read_bytes() if self.path.exists() else None
        self.lines = (self.original or b'').decode('utf-8-sig').splitlines()
        self.tools = {}
        self.locations = {}
        for index, line in enumerate(self.lines):
            code, _, comment = line.partition(';')
            words = re.findall(r'([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', code)
            data = {key.upper(): float(value) for key, value in words}
            n = data.pop('T', 0.)
            if n not in range(1, 6):
                continue
            n = int(n)
            if n in self.tools:
                raise ValueError(f'Duplicate T{n} in tool table')
            self.tools[n] = LatheTool(n, data, comment)
            self.locations[n] = index
        for n in range(1, 6):
            self.tools.setdefault(n, LatheTool(n, comment=f'Tool {n}'))

    def save(self, tools):
        if len(tools) != 5 or {t.number for t in tools} != set(range(1, 6)):
            raise ValueError('Save exactly tools 1–5')
        for tool in tools:
            tool.validate()
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.original:
            raise ValueError('Tool table changed externally. Reload it before saving.')
        lines = list(self.lines)
        for tool in tools:
            if tool.number in self.locations:
                lines[self.locations[tool.number]] = tool.line()
            else:
                lines.append(tool.line())
        pockets = []
        for line in lines:
            words = dict(re.findall(r'([TP])\s*(\d+)', line.split(';')[0].upper()))
            if int(words.get('T', 0)) > 0 and int(words.get('P', 0)) > 0:
                pockets.append(int(words['P']))
        if len(pockets) != len(set(pockets)):
            raise ValueError('Tool pockets must be unique; check existing tool-table pockets')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if current is not None:
            shutil.copy2(self.path, self.path.with_name(self.path.name + '.bak'))
        fd, name = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write('\n'.join(lines) + '\n')
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
        self.reload()
