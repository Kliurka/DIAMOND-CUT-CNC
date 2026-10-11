"""Persistent machine-coordinate limits shared by the screen and INI setup."""
import json
import math
from pathlib import Path

FILENAME = 'diamondcut-limits.json'


def validate_limits(limits):
    result = {}
    if set(limits) != set('XYZ'):
        raise ValueError('Specify X, Y and Z limits')
    for axis in 'XYZ':
        try:
            low, high = map(float, limits[axis])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{axis}: specify numeric Min and Max") from exc
        if not all(math.isfinite(v) for v in (low, high)) or low >= high:
            raise ValueError(f'{axis}: Min must be finite and smaller than Max')
        result[axis] = (low, high)
    return result


def read_saved_limits(folder):
    path = Path(folder) / FILENAME
    if not path.exists():
        return None
    return validate_limits(json.loads(path.read_text(encoding='utf-8')))


def limit_sections(limits):
    limits = validate_limits(limits)
    changes = {}
    for joint, axis in enumerate('XYZ'):
        settings = dict(MIN_LIMIT=f'{limits[axis][0]:.6f}', MAX_LIMIT=f'{limits[axis][1]:.6f}')
        changes['AXIS_' + axis] = settings.copy()
        changes['JOINT_' + str(joint)] = settings.copy()
    return changes


def save_limits(ini_path, limits):
    from tools.setup_machine_qtvcp import change_sections
    ini_path = Path(ini_path).resolve()
    limits = validate_limits(limits)
    updated = change_sections(ini_path.read_text(encoding='utf-8'), limit_sections(limits))
    # Do not replace an unrelated configuration or lose the previous INI.
    backup = ini_path.with_suffix(ini_path.suffix + '.limits-backup')
    backup.write_text(ini_path.read_text(encoding='utf-8'), encoding='utf-8')
    temporary = ini_path.with_suffix(ini_path.suffix + '.limits-tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(ini_path)
    path = ini_path.parent / FILENAME
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(limits, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
