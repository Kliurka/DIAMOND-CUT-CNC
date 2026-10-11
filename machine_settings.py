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


SPEED_FILENAME = 'diamondcut-rapids.json'


def validate_rapids(speeds):
    if set(speeds) != set('XZ'):
        raise ValueError('Specify X and Z rapid speeds')
    result = {a: float(speeds[a]) for a in 'XZ'}
    if any(not math.isfinite(v) or v <= 0 for v in result.values()):
        raise ValueError('Rapid speeds must be finite and positive (mm/min)')
    return result


def read_saved_rapids(folder):
    path = Path(folder) / SPEED_FILENAME
    if not path.exists():
        return None
    return validate_rapids(json.loads(path.read_text(encoding='utf-8')))


def rapid_sections(contents, speeds):
    from tools.setup_machine_qtvcp import values
    data = values(contents)
    speeds = validate_rapids(speeds)
    changes = {}
    for axis, joint in [('X', 0), ('Z', 2)]:
        velocity = speeds[axis] / 60
        changes['AXIS_' + axis] = {'MAX_VELOCITY': f'{velocity:.8f}'}
        changes['JOINT_' + str(joint)] = {'MAX_VELOCITY': f'{velocity:.8f}'}
        section = 'JOINT_' + str(joint)
        if (section, 'STEPGEN_MAXVEL') in data:
            old_velocity = float(data[section, 'MAX_VELOCITY'])
            margin = max(1.25, float(data[section, 'STEPGEN_MAXVEL']) / old_velocity)
            changes[section]['STEPGEN_MAXVEL'] = f'{velocity * margin:.8f}'
    maximum = max(speeds['X'] / 60, speeds['Z'] / 60, float(data['AXIS_Y', 'MAX_VELOCITY']))
    changes['TRAJ'] = {'MAX_LINEAR_VELOCITY': f'{maximum:.8f}'}
    if ('TRAJ', 'MAX_VELOCITY') in data:
        changes['TRAJ']['MAX_VELOCITY'] = f'{maximum:.8f}'
    changes['DISPLAY'] = {'MAX_LINEAR_VELOCITY': f'{maximum:.8f}'}
    return changes


def save_rapids(ini_path, speeds):
    from tools.setup_machine_qtvcp import change_sections
    ini_path = Path(ini_path).resolve()
    speeds = validate_rapids(speeds)
    contents = ini_path.read_text(encoding='utf-8')
    updated = change_sections(contents, rapid_sections(contents, speeds))
    ini_path.with_suffix('.ini.speeds-backup').write_text(contents, encoding='utf-8')
    temporary = ini_path.with_suffix('.ini.speeds-tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(ini_path)
    path = ini_path.parent / SPEED_FILENAME
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(speeds, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
