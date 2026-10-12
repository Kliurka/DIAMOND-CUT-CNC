"""Graph-only playback of this screen's generated metric X/Z programs."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Move:
    x: float
    z: float
    speed: float  # mm/min
    line: int


def parse_program(code, start=(0, 0), rapid=600, require_preamble=False):
    x, z = start
    rapid_axes = rapid if isinstance(rapid, dict) else {'X': rapid, 'Z': rapid}
    if set(rapid_axes) != set('XZ'):
        raise ValueError("Specify X and Z rapid speeds")
    if (not all(math.isfinite(v) for v in (x, z, *rapid_axes.values()))
            or any(v <= 0 for v in rapid_axes.values())):
        raise ValueError("Invalid playback start or rapid speed")
    feed = None
    moves = []
    modes = set()
    ended = False
    spindle_on = False
    for line, text in enumerate(code.splitlines(), 1):
        text = re.sub(r'\([^)]*\)', '', text).split(';')[0].strip().upper()
        if not text:
            continue
        words = re.findall(r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', text)
        if re.sub(r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', '', text).strip():
            raise ValueError(f'Unsupported G-code at line {line}')
        if require_preamble and ended:
            raise ValueError(f"Code after M2 at line {line}")
        motion = None
        axes = {}
        for letter, number in words:
            value = float(number)
            if not math.isfinite(value):
                raise ValueError('Non-finite G-code value')
            if letter == 'G':
                modes.add(value)
                if value in (0, 1):
                    motion = int(value)
                elif value not in (21, 90, 40, 49, 54, 8, 94, 97):
                    raise ValueError(f'Only generated G97/G94 X/Z programs are supported (line {line})')
            elif letter == 'M':
                if value not in (2, 3, 5):
                    raise ValueError(f'Unsupported M-code at line {line}')
                if require_preamble:
                    if value == 3:
                        if 97 not in modes:
                            raise ValueError('Declare G97 before M3')
                        spindle_on = True
                    elif value == 5:
                        spindle_on = False
                    elif value == 2:
                        if spindle_on:
                            raise ValueError('Include M5 before M2')
                        ended = True
            elif letter in ('X', 'Z'):
                axes[letter] = value
            elif letter == 'F':
                feed = value
                if feed <= 0:
                    raise ValueError('Feed must be positive')
            elif letter != 'S':
                raise ValueError(f'Unsupported {letter} word at line {line}')
        if axes:
            if require_preamble and not {21, 90, 40, 49, 54, 8, 94, 97}.issubset(modes):
                raise ValueError('Declare G21 G90 G40 G49 G54 G8 G94 G97 before motion')
            if motion is None or (motion == 1 and feed is None):
                raise ValueError(f'Missing motion/feed at line {line}')
            nx, nz = axes.get('X', x), axes.get('Z', z)
            duration = max(abs(nx - x) / rapid_axes['X'], abs(nz - z) / rapid_axes['Z'])
            rapid_speed = math.hypot(nx - x, nz - z) / duration if duration else min(rapid_axes.values())
            if not isinstance(rapid, dict):
                rapid_speed = rapid
            x, z = nx, nz
            moves.append(Move(x, z, rapid_speed if motion == 0 else feed, line))
    if require_preamble and not ended:
        raise ValueError('Program must end with M2')
    if not moves:
        raise ValueError('Generate G-code first')
    return moves


class Playback:
    def __init__(self, moves, start):
        self.moves = moves
        self.position = tuple(start)
        self.index = 0

    @property
    def done(self):
        return self.index == len(self.moves)

    def advance(self, seconds):
        while seconds > 0 and not self.done:
            move = self.moves[self.index]
            dx, dz = move.x - self.position[0], move.z - self.position[1]
            distance = math.hypot(dx, dz)
            duration = distance / (move.speed / 60)
            if duration <= seconds:
                self.position = (move.x, move.z)
                self.index += 1
                seconds -= duration
            else:
                fraction = seconds / duration
                self.position = (self.position[0] + dx * fraction,
                                 self.position[1] + dz * fraction)
                break
        return self.position
