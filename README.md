# DIAMOND-CUT-CNC

English-language prototype for a LinuxCNC wheel rim scanning and decorative turning workflow. Motion and laser scanning are simulated. The QtVCP screen can monitor real Mesa 7i96S I/O using the bench configuration below. It does not enable motors or command a real spindle. Do not run generated G-code on a machine without configuring, inspecting and dry-running it.

## Run

On a Linux desktop with Python 3 and PyQt5:

```bash
sudo apt install python3-pyqt5
python3 sim_app.py
```

Alternatively, install PyQt5 into a Python virtual environment. The profile and G-code engine uses the Python standard library.

## Workflow

- Left: simulated machine/work X, Z and Y positions, E-stop reset, simulated homing, work zero, cross-shaped X/Z jog controls, separate Y table up/down buttons, step sizes and simulated work-home motion.
- Scan tab: X start and X end share a row (each can capture current Work X); scan step and X scan feedrate share the next row. Choose independent odd-sized median and moving-average windows, generate a synthetic rim profile, compare raw and smoothed curves, and save both CSV files.
- Toolpath & Turning tab: load the saved smoothed CSV, edit each pass's enable flag, target cut depth, feed, RPM and surface speed in a table; generate and save a G-code preview.
- Settings tab: rim radius, scan step, sensor/tool X and Z offsets, safe Z clearance, maximum total cut depth and a fixed Y table position.

The simulated scan moves from the selected X start to X end (increasing work X, toward the center). Its stored `edge_mm` starts at zero at the selected start and increases over the travel. Set the **rim radius at scan start** in Settings; the scan distance must not exceed this radius. The generated turning code converts `edge_mm` to a **radius-coordinate X with X0 at the spindle center**, so LinuxCNC G96 has the correct reference. This is only a provisional geometry model; actual directions and offsets require verification at the machine. Y+ means table up in the simulator; the physical direction remains to be mapped.

Scan step determines the spacing and number of synthetic samples. Scan speed displays an estimated machine travel time (`distance / speed`); the simulator creates samples immediately and does not command real motion.

The median window removes isolated spikes; the optional mean window (1 = off) further smooths nearby samples. Both use centered sample windows and may flatten narrow decorative details, so compare the red raw profile with the blue result before saving.

The G-code generator currently offers G97/G94 or G96/G95. G95 requires actual spindle speed feedback in LinuxCNC. All generated moves are tagged as unverified, and the generator rejects passes deeper than the configured limit. Real spindle feedback, sensor acquisition, machine homing and safe travel are future hardware steps.

The Turning tab has G-code text on the left and LinuxCNC's **actual QtVCP GCodeGraphics** on the right when the `diamondcut` QtVCP screen is launched by LinuxCNC. Standalone `python3 sim_app.py` deliberately shows an explanatory placeholder. The QtVCP handler dynamically registers the native widget with QtVCP, then loads the generated G-code into it. The native preview has been verified on LinuxCNC 2.9.10. The left control panel remains simulated even when launched as a QtVCP screen.

## Native QtVCP preview in a LinuxCNC simulation

First locate an existing, working LinuxCNC **simulation** INI on your computer:

```bash
find ~/linuxcnc/configs -name '*.ini'
```

From this repository directory, substitute the path to a simulation INI you have already run successfully:

```bash
python3 tools/setup_qtvcp_preview.py --source ~/linuxcnc/configs/your-simulation/your-simulation.ini
```

The script creates `~/linuxcnc/configs/diamondcut-preview`, copies the source simulation configuration and its related files, links this repository's QtVCP files, and changes `DISPLAY`, `LATHE`, and `GEOMETRY` in the **copy**. It prints the exact `linuxcnc` launch command. If you have no simulation INI yet, first create and run one with LinuxCNC's configuration selector; do not use your real machine INI. The destination must not already exist.

Generate the preview from the Turning tab. The native widget should occupy the right half of the preview area. If the QtVCP screen fails to start, collect the terminal output and LinuxCNC version. The project has no real HAL motor or laser wiring yet.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Mesa 7i96S I/O bench monitor

Close LinuxCNC and exit any halrun session before starting. Use the original working lathe simulation, not an existing preview directory or a real machine configuration:

```bash
python3 tools/setup_mesa_io.py --source ~/linuxcnc/configs/sim.axis/lathe.ini --ip 10.10.10.10
linuxcnc ~/linuxcnc/configs/diamondcut-mesa-io/lathe.ini
```

The new destination must not exist. The source and existing diamondcut-preview configuration are preserved. Old source post-GUI HAL and PyVCP configuration are disabled in the copy. Mesa runs on a separate 10 ms bench thread with a 100 ms watchdog; these values are not a production motion configuration.

Tab **4. Mesa I/O** polls HAL every 100 ms and shows INPUT0–INPUT10, output command states, packet-error count and watchdog status. Faulted or missing data is shown as UNKNOWN. Output states are commands, not physical feedback. OUT0–OUT5 checkboxes directly send HAL commands; an All outputs OFF button attempts all six OFF commands. Checkboxes follow external HAL changes without writing during refresh. ON commands are blocked while current communication/watchdog faults are active; failures are reported in the panel. In the original simulation preview the monitor reports Mesa unavailable. The left motion controls and scan acquisition remain simulated in all configurations.

Input bench test: with power off, wire the 5 V supply ground to TB3-12 (INPUT COMMON), and +5 V through a switch to TB3-1 (INPUT0). With the screen running, the physical input indicator and the INPUT0 row should change together. VirtualBox is for bench communication/I/O checks; its timing is not validated for real machine motion. Real Mesa writes, OUT0 indication and INPUT0 reads have been verified manually on the user's board; the new GUI monitor still needs that hardware acceptance check.
