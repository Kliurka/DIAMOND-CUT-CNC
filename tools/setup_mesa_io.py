#!/usr/bin/env python3
"""Create an isolated simulation plus real Mesa I/O monitor configuration."""
import argparse
import ipaddress
from pathlib import Path
import re
import shlex
from setup_qtvcp_preview import setup, SECTION, SETTING

HAL = """# Bench I/O test only: no motor enables or motion connections.
loadrt hostmot2
loadrt hm2_eth board_ip="[MESA_IO]BOARD_IP"
loadrt threads name1=mesa-test period1=10000000
setp hm2_7i96s.0.watchdog.timeout_ns 100000000
addf hm2_7i96s.0.read mesa-test
addf hm2_7i96s.0.write mesa-test
"""


def mesa_ini(contents, board_ip):
    board_ip = str(ipaddress.IPv4Address(board_ip))
    result = []
    section = ""
    found_hal = False
    for line in contents.splitlines(keepends=True):
        heading = SECTION.match(line)
        if heading:
            if section == "HAL":
                result.append("HALFILE = mesa_io.hal\n")
            section = heading.group(1).upper()
            found_hal |= section == "HAL"
        setting = SETTING.match(line)
        if setting:
            key = setting.group(1).upper()
            # AXIS's old PyVCP spindle panel has no pins in the QtVCP screen.
            if section == "HAL" and key == "POSTGUI_HALFILE":
                result.append("# Mesa monitor disables source post-GUI HAL: " + line)
                continue
            if section == "DISPLAY" and key in ("PYVCP", "PYVCP_POSITION"):
                result.append("# " + line)
                continue
        result.append(line if line.endswith("\n") else line + "\n")
    if section == "HAL":
        result.append("HALFILE = mesa_io.hal\n")
    if not found_hal:
        raise ValueError("Source INI needs a [HAL] section")
    if re.search(r"^\s*\[MESA_IO\]", contents, re.MULTILINE | re.IGNORECASE):
        raise ValueError("Source INI already has a [MESA_IO] section")
    result.append(f"\n[MESA_IO]\nBOARD_IP = {board_ip}\n")
    return "".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Original working SIMULATION INI, not a machine configuration")
    parser.add_argument("--dest", type=Path, default=Path("~/linuxcnc/configs/diamondcut-mesa-io"))
    parser.add_argument("--ip", default="10.10.10.10")
    args = parser.parse_args()
    try:
        ipaddress.IPv4Address(args.ip)
        # Validate before creating anything; setup refuses existing destinations.
        mesa_ini(args.source.expanduser().read_text(encoding="utf-8"), args.ip)
        ini = setup(args.source, args.dest, Path(__file__).resolve().parent.parent)
        ini.write_text(mesa_ini(ini.read_text(encoding="utf-8"), args.ip), encoding="utf-8")
        (ini.parent / "mesa_io.hal").write_text(HAL, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Setup failed: {exc}\n")
    print(f"Created Mesa I/O bench config: {ini}")
    print("Mesa cycle: 10 ms; watchdog: 100 ms. Motion remains simulated.")
    print(f"Start: linuxcnc {shlex.quote(str(ini))}")


if __name__ == "__main__":
    main()
