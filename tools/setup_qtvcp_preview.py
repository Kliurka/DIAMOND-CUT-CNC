#!/usr/bin/env python3
"""Create an isolated LinuxCNC simulation config for the Diamond Cut screen."""

import argparse
from pathlib import Path
import re
import shlex
import shutil


DISPLAY_VALUES = {"DISPLAY": "qtvcp diamondcut", "LATHE": "1", "GEOMETRY": "XZ"}
SECTION = re.compile(r"^\s*\[([^]]+)\]\s*(?:[;#].*)?$")
SETTING = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=")


def preview_ini(contents):
    lines = contents.splitlines(keepends=True)
    result = []
    in_display = False
    found_display = False
    inserted = False

    def add_display_values():
        for key, value in DISPLAY_VALUES.items():
            result.append(f"{key} = {value}\n")

    for line in lines:
        section = SECTION.match(line)
        if section:
            if in_display:
                add_display_values()
                inserted = True
            in_display = section.group(1).upper() == "DISPLAY"
            found_display |= in_display
        if in_display and not section:
            setting = SETTING.match(line)
            if setting and setting.group(1).upper() in DISPLAY_VALUES:
                continue
        result.append(line)
    if in_display and not inserted:
        if result and not result[-1].endswith("\n"):
            result[-1] += "\n"
        add_display_values()
    if not found_display:
        raise ValueError("Source INI has no [DISPLAY] section")
    return "".join(result)


def setup(source, dest, repo_root):
    source = source.expanduser().resolve()
    dest = dest.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".ini":
        raise ValueError(f"Choose an existing simulation .ini file: {source}")
    if dest.exists():
        raise ValueError(f"Destination already exists: {dest}")
    if dest.is_relative_to(source.parent):
        raise ValueError("Destination must be outside the source configuration folder")

    updated = preview_ini(source.read_text(encoding="utf-8"))
    for name in ("diamondcut.ui", "diamondcut_handler.py"):
        if not (repo_root / "qtvcp" / name).is_file():
            raise ValueError(f"Missing repository file: qtvcp/{name}")
        if (source.parent / name).exists():
            raise ValueError(f"Source folder already has {name}; choose another simulation")

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source.parent, dest, symlinks=True)
        copied_ini = dest / source.name
        copied_ini.write_text(updated, encoding="utf-8")
        for name in ("diamondcut.ui", "diamondcut_handler.py"):
            (dest / name).symlink_to(repo_root / "qtvcp" / name)
    except Exception:
        if dest.is_dir():
            shutil.rmtree(dest)
        raise
    return copied_ini


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="INI of an existing LinuxCNC simulation")
    parser.add_argument("--dest", type=Path,
                        default=Path("~/linuxcnc/configs/diamondcut-preview"),
                        help="New config directory (default: ~/linuxcnc/configs/diamondcut-preview)")
    args = parser.parse_args()
    if args.source is None:
        candidates = sorted(Path("~/linuxcnc/configs").expanduser().rglob("*.ini"))
        parser.error("specify --source with a working SIMULATION INI. Available local INIs:\n" +
                     ("\n".join(str(p) for p in candidates) or "(none found)"))
    try:
        ini = setup(args.source, args.dest, Path(__file__).resolve().parent.parent)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Setup failed: {error}\n")
    print(f"Created isolated simulation config: {ini}")
    print(f"Start it with: linuxcnc {shlex.quote(str(ini))}")


if __name__ == "__main__":
    main()
