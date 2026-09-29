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

- Left: simulated machine/work X, Z and Y positions, E-stop reset, simulated homing, work zero, cross-shaped X/Z jog controls, separate Y table up/down buttons, step sizes and simulated work-home motion.
- Scan tab: set X start and X end in work coordinates by typing or capturing the current Work X; set scan step and X scan speed in mm/min; generate a repeatable synthetic rim profile, compare raw and median-smoothed curves, and save both CSV files.
- Toolpath & Turning tab: load the saved smoothed CSV, edit each pass's enable flag, target cut depth, feed, RPM and surface speed in a table; generate and save a G-code preview.
- Settings tab: rim radius, scan step, sensor/tool X and Z offsets, safe Z clearance, maximum total cut depth and a fixed Y table position.

The simulated scan moves from the selected X start to X end (increasing work X, toward the center). Its stored `edge_mm` starts at zero at the selected start and increases over the travel. Set the **rim radius at scan start** in Settings; the scan distance must not exceed this radius. The generated turning code converts `edge_mm` to a **radius-coordinate X with X0 at the spindle center**, so LinuxCNC G96 has the correct reference. This is only a provisional geometry model; actual directions and offsets require verification at the machine. Y+ means table up in the simulator; the physical direction remains to be mapped.

Scan step determines the spacing and number of synthetic samples. Scan speed displays an estimated machine travel time (`distance / speed`); the simulator creates samples immediately and does not command real motion.

The G-code generator currently offers G97/G94 or G96/G95. G95 requires actual spindle speed feedback in LinuxCNC. All generated moves are tagged as unverified, and the generator rejects passes deeper than the configured limit. Real spindle feedback, sensor acquisition, machine homing and safe travel are future hardware steps.

The Turning tab has G-code text on the left and a space for LinuxCNC's **actual QtVCP GCodeGraphics** on the right. In a standalone Python simulation there is no LinuxCNC interpreter or INI context, so the right side reports that the native preview is unavailable. If launched in a LinuxCNC context with `INI_FILE_NAME` and QtVCP importable, the application attempts to construct the real widget and load the generated preview. That integration has **not yet been verified in a LinuxCNC runtime**. No custom 3D rendering is substituted for it.

## Tests

```bash
python3 -m unittest discover -s tests
```
