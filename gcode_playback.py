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
    css: bool = False
    feed_per_rev: bool = False
    start_x: float | None = None
    start_z: float | None = None
    max_speed: float = 0


class ProgramMoves(list):
    def __init__(self):
        super().__init__()
        self.uses_css = False


def parse_program(code, start=(0, 0), rapid=600, require_preamble=False):
    x, z = start
    rapid_axes = rapid if isinstance(rapid, dict) else {'X': rapid, 'Z': rapid}
    if set(rapid_axes) != set('XZ') or not all(math.isfinite(v) for v in (x, z, *rapid_axes.values())) or any(v <= 0 for v in rapid_axes.values()):
        raise ValueError("Invalid playback start or rapid speeds")
    feed = None
    feed_mode = None if require_preamble else 94
    spindle_mode, spindle_setting, rpm_limit = None, None, None
    modes, moves = set(), ProgramMoves()
    ended = spindle_on = False
    expression = r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))'
    for line, text in enumerate(code.splitlines(), 1):
        text = re.sub(r'\([^)]*\)', '', text).split(';')[0].strip().upper()
        if not text:
            continue
        words = [(letter, float(value)) for letter, value in re.findall(expression, text)]
        if re.sub(expression, '', text).strip() or any(not math.isfinite(v) for _, v in words):
            raise ValueError(f'Unsupported or non-finite G-code at line {line}')
        if require_preamble and ended:
            raise ValueError(f'Code after M2 at line {line}')
        groups = {}
        for letter, value in words:
            groups.setdefault(letter, []).append(value)
        if any(letter not in 'GMXZSD F'.replace(' ', '') for letter in groups):
            raise ValueError(f'Unsupported word at line {line}')
        gs = groups.get('G', [])
        if any(g not in (0, 1, 21, 90, 40, 49, 54, 8, 94, 95, 96, 97) for g in gs):
            raise ValueError(f'Only metric absolute straight X/Z programs are supported (line {line})')
        for modal_group in ((0, 1), (94, 95), (96, 97)):
            if sum(g in modal_group for g in gs) > 1:
                raise ValueError(f'Conflicting modal commands at line {line}')
        if any(len(groups.get(letter, [])) > 1 for letter in 'XZSD F'.replace(' ', '')):
            raise ValueError(f'Duplicate word at line {line}')
        if 96 in gs:
            moves.uses_css = True
            if 'D' not in groups or 'S' not in groups:
                raise ValueError('Every G96 block requires explicit S and a positive D RPM limit')
        modes.update(gs)
        for g in gs:
            if g in (94, 95):
                if g != feed_mode:
                    feed = None
                feed_mode = g
            if g in (96, 97):
                if g != spindle_mode and spindle_on and 'S' not in groups:
                    raise ValueError('Specify S when changing spindle mode while running')
                spindle_mode = g
        if 'S' in groups:
            spindle_setting = groups['S'][0]
            if spindle_setting <= 0:
                raise ValueError('Spindle setting must be positive')
        if 'D' in groups:
            if 96 not in gs or groups['D'][0] <= 0:
                raise ValueError('D requires G96 and a positive maximum RPM')
            rpm_limit = groups['D'][0]
        if 'F' in groups:
            feed = groups['F'][0]
            if feed <= 0:
                raise ValueError('Feed must be positive')
        for m in groups.get('M', []):
            if m == 3:
                if require_preamble and (spindle_mode is None or spindle_setting is None):
                    raise ValueError('Declare spindle mode and S before M3')
                spindle_on = True
            elif m == 5:
                spindle_on = False
            elif m == 2:
                if require_preamble and spindle_on:
                    raise ValueError('Include M5 before M2')
                ended = True
            else:
                raise ValueError(f'Unsupported M-code at line {line}')
        axes = {letter: groups[letter][0] for letter in 'XZ' if letter in groups}
        if not axes:
            continue
        if require_preamble and (not {21, 90, 40, 49, 54, 8}.issubset(modes) or feed_mode is None or spindle_mode is None):
            raise ValueError('Declare G21 G90 G40 G49 G54 G8 and feed/spindle modes before motion')
        motion = next((int(g) for g in gs if g in (0, 1)), None)
        if motion is None or (motion == 1 and feed is None):
            raise ValueError(f'Missing motion/feed at line {line}')
        nx, nz = axes.get('X', x), axes.get('Z', z)
        duration = max(abs(nx - x) / rapid_axes['X'], abs(nz - z) / rapid_axes['Z'])
        rapid_speed = math.hypot(nx - x, nz - z) / duration if duration else min(rapid_axes.values())
        if not isinstance(rapid, dict):
            rapid_speed = rapid
        speed = rapid_speed if motion == 0 else feed
        if spindle_mode == 96 and (rpm_limit is None or spindle_setting is None):
            raise ValueError('CSS requires G96 S and a positive D RPM limit')
        if motion == 1 and (spindle_mode == 96 or feed_mode == 95) and not spindle_on:
            raise ValueError('CSS/G95 cutting requires M3 spindle ON')
        max_speed = speed
        if motion == 1 and feed_mode == 95:
            if spindle_setting is None:
                raise ValueError('G95 requires a spindle speed setting')
            radius = abs((x + nx) / 2)
            rpm = (min(rpm_limit, spindle_setting * 1000 / (2 * math.pi * radius)) if radius else rpm_limit) if spindle_mode == 96 else spindle_setting
            speed = feed * rpm
            min_radius = min(abs(x), abs(nx))
            peak_rpm = (min(rpm_limit, spindle_setting * 1000 / (2 * math.pi * min_radius)) if min_radius else rpm_limit) if spindle_mode == 96 else spindle_setting
            max_speed = feed * peak_rpm
        moves.append(Move(nx, nz, speed, line, spindle_mode == 96, motion == 1 and feed_mode == 95, x, z, max_speed))
        x, z = nx, nz
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
