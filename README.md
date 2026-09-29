# DIAMOND-CUT-CNC

English-language prototype for a LinuxCNC wheel rim scanning and decorative turning workflow. **This first version is a desktop simulator only. It does not connect to LinuxCNC, the laser, spindle or motors. Do not run its generated G-code on a machine without configuring, inspecting and dry-running it.**

## Run

On a Linux desktop with Python 3 and PyQt5:

```bash
sudo apt install python3-pyqt5
python3 sim_app.py
```

Alternatively, install PyQt5 into a Python virtual environment. The profile and G-code engine uses the Python standard library.

## Workflow

- Left: simulated machine/work X and Z positions, E-stop reset, simulated homing, work zero, jog controls, step sizes and simulated work-home motion.
- Scan tab: generate a repeatable synthetic rim profile, display it and save raw CSV.
- Toolpath & Turning tab: median filter the profile, compare raw and smoothed curves, set passes/cut depth/feed/rpm, generate and save a G-code preview.
- Settings tab: rim radius, scan step, sensor/tool X and Z offsets, safe Z clearance, maximum total cut depth and a fixed Y table position.

The simulated scan moves from the outer edge toward the center. Its stored `edge_mm` starts at zero at the edge. The generated turning code converts it to a **radius-coordinate X with X0 at the spindle center**, so LinuxCNC G96 has the correct reference. This is only a provisional geometry model; actual directions and offsets require verification at the machine.

The G-code generator currently offers G97/G94 or G96/G95. G95 requires actual spindle speed feedback in LinuxCNC. All generated moves are tagged as unverified, and the generator rejects a requested depth greater than the configured limit. Real spindle feedback, sensor acquisition, machine homing, safe travel and QtVCP integration are future hardware steps.

## Tests

```bash
python3 -m unittest discover -s tests
```
