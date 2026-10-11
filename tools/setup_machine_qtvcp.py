#!/usr/bin/env python3
"""Add a separate Diamond Cut QtVCP launch INI beside a working PNCconf INI."""
import argparse
from pathlib import Path
import re
import shlex

SECTION = re.compile(r"^\s*\[([^]]+)\]\s*(?:[#;].*)?$")
SETTING = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$")


def values(contents):
    result, section = {}, ""
    for line in contents.splitlines():
        match = SECTION.match(line)
        if match:
            section = match.group(1).upper()
        else:
            match = SETTING.match(line)
            if match:
                result[section, match.group(1).upper()] = match.group(2).split("#")[0].strip()
    return result


def change_sections(contents, changes):
    result, section, seen = [], "", set()
    remaining = {key: dict(val) for key, val in changes.items()}

    def append_missing():
        for key, value in remaining.get(section, {}).items():
            result.append(f"{key} = {value}\n")
        remaining.pop(section, None)

    for line in contents.splitlines(keepends=True):
        match = SECTION.match(line)
        if match:
            append_missing()
            section = match.group(1).upper()
            seen.add(section)
        setting = SETTING.match(line)
        if setting and setting.group(1).upper() in changes.get(section, {}):
            continue
        result.append(line if line.endswith("\n") else line + "\n")
    append_missing()
    for section in changes:
        if section not in seen:
            result.append(f"\n[{section}]\n")
            for key, value in changes[section].items():
                result.append(f"{key} = {value}\n")
    return "".join(result)


def setup(source, repo_root):
    source = source.expanduser().resolve()
    repo_root = repo_root.resolve()
    if not source.is_file() or source.suffix.lower() != ".ini":
        raise ValueError("Choose a working PNCconf .ini")
    dest = source.parent / "diamondcut-control.ini"
    if source == dest:
        raise ValueError("Use the original PNCconf INI as source")
    contents = source.read_text(encoding="utf-8")
    data = values(contents)
    if data.get(("KINS", "KINEMATICS"), "").split()[:1] != ["trivkins"]:
        raise ValueError("Currently supports trivkins XYZ configurations")
    if "".join(data.get(("TRAJ", "COORDINATES"), "").split()).upper() != "XYZ":
        raise ValueError("Currently supports XYZ configurations")
    if data.get(("KINS", "JOINTS")) != "3":
        raise ValueError("Currently supports three joints")
    if data.get(("TRAJ", "LINEAR_UNITS"), "").lower() not in ("mm", "1", "1.0"):
        raise ValueError("Machine units must be millimeters")
    if data.get(("DISPLAY", "DISPLAY"), "").split()[:1] != ["axis"]:
        raise ValueError("Use the tested PNCconf AXIS configuration")
    maximum = min(float(data["AXIS_" + a, "MAX_VELOCITY"]) for a in "XYZ")
    if maximum <= 0:
        raise ValueError("Invalid axis velocity")
    links = []
    for name in ("diamondcut.ui", "diamondcut_handler.py"):
        target = repo_root / "qtvcp" / name
        link = source.parent / name
        if not target.is_file():
            raise ValueError(f"Missing {target}")
        if (link.exists() or link.is_symlink()) and not (link.is_symlink() and link.resolve() == target):
            raise ValueError(f"Existing unrelated file: {link}")
        links.append((link, target))
    if not (repo_root / "linuxcnc_control.py").is_file():
        raise ValueError("Update the repository with git pull first")
    updated = change_sections(contents, {
        "DISPLAY": {"DISPLAY": "qtvcp diamondcut", "DEFAULT_LINEAR_VELOCITY": str(min(0.5, maximum)),
                    "MAX_LINEAR_VELOCITY": str(maximum), "MIN_LINEAR_VELOCITY": "0.001",
                    "LATHE": "1", "GEOMETRY": "XZ"},
        "DIAMONDCUT": {"MOTION": "linuxcnc"},
        "TRAJ": {"NO_FORCE_HOMING": "1"},
        "JOINT_0": {"HOME_SEQUENCE": "2"},
        "JOINT_2": {"HOME_SEQUENCE": "1"},
    })
    # Screen limits survive PNCconf regeneration; original PNCconf INI stays intact.
    import sys
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from machine_settings import read_saved_limits, limit_sections, read_saved_rapids, rapid_sections
    saved_limits = read_saved_limits(source.parent)
    if saved_limits is not None:
        updated = change_sections(updated, limit_sections(saved_limits))
    saved_rapids = read_saved_rapids(source.parent)
    if saved_rapids is not None:
        updated = change_sections(updated, rapid_sections(updated, saved_rapids))
    # Y is a manual table with no home reference. LinuxCNC's global homing gate
    # must allow MDI with unhomed Y; the screen still requires X/Z homing.
    section = ""
    lines = []
    for line in updated.splitlines(keepends=True):
        match = SECTION.match(line)
        if match:
            section = match.group(1).upper()
        setting = SETTING.match(line)
        if section == "JOINT_1" and setting and setting.group(1).upper() == "HOME_SEQUENCE":
            continue
        lines.append(line)
    updated = "".join(lines)
    for link, target in links:
        if not link.is_symlink():
            link.symlink_to(target)
    temporary = dest.with_suffix(".ini.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    try:
        dest = setup(args.source, Path(__file__).resolve().parent.parent)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Setup failed: {exc}\n")
    print(f"Created real-control launch INI: {dest}")
    print("Original PNCconf INI and HAL are preserved. Shared HAL remains PNCconf-managed.")
    print("After PNCconf regeneration, test AXIS and rerun this script to refresh the launch INI.")
    print(f"Start: linuxcnc {shlex.quote(str(dest))}")


if __name__ == "__main__":
    main()
