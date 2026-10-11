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


def parse_program(code, start=(0, 0), rapid=600):
    x, z = start
    if not all(math.isfinite(v) for v in (x, z, rapid)) or rapid <= 0:
        raise ValueError("Invalid playback start or rapid speed")
    feed = None
    moves = []
    for line, text in enumerate(code.splitlines(), 1):
        text = re.sub(r'\([^)]*\)', '', text).split(';')[0].strip().upper()
        if not text:
            continue
        words = re.findall(r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', text)
        if re.sub(r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', '', text).strip():
            raise ValueError(f'Unsupported G-code at line {line}')
        motion = None
        axes = {}
        for letter, number in words:
            value = float(number)
            if not math.isfinite(value):
                raise ValueError('Non-finite G-code value')
            if letter == 'G':
                if value in (0, 1):
                    motion = int(value)
                elif value not in (21, 90, 40, 49, 54, 8, 94, 97):
                    raise ValueError(f'Only generated G97/G94 X/Z programs are supported (line {line})')
            elif letter == 'M':
                if value not in (2, 3, 5):
                    raise ValueError(f'Unsupported M-code at line {line}')
            elif letter in ('X', 'Z'):
                axes[letter] = value
            elif letter == 'F':
                feed = value
                if feed <= 0:
                    raise ValueError('Feed must be positive')
            elif letter != 'S':
                raise ValueError(f'Unsupported {letter} word at line {line}')
        if axes:
            if motion is None or (motion == 1 and feed is None):
                raise ValueError(f'Missing motion/feed at line {line}')
            x, z = axes.get('X', x), axes.get('Z', z)
            moves.append(Move(x, z, rapid if motion == 0 else feed, line))
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
