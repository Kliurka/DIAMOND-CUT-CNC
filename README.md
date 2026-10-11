# DIAMOND-CUT-CNC

English-language prototype for a LinuxCNC wheel rim scanning and decorative turning workflow. Standalone and preview configurations simulate the axis controls and laser scanning. The PNCconf integration below provides real LinuxCNC manual axis control. A separate Mesa bench configuration offers real I/O and direct STEPGEN0 testing. Laser acquisition and machining program execution through this screen are not implemented. Do not run generated G-code on a machine without configuring, inspecting and dry-running it.

## Run

On a Linux desktop with Python 3 and PyQt5:

```bash
sudo apt install python3-pyqt5
python3 sim_app.py
```

Alternatively, install PyQt5 into a Python virtual environment. The profile and G-code engine uses the Python standard library.

## Workflow

- Left: simulated machine/work X and Z positions, E-stop reset, simulated homing, work zero, cross-shaped X/Z jog controls, step sizes and simulated work-home motion.
- Scan tab: X start and X end share a row (each can capture current Work X); scan step and X scan feedrate share the next row. Choose independent odd-sized median and moving-average windows, generate a synthetic rim profile, compare raw and smoothed curves, and save both CSV files.
- Toolpath & Turning tab: load the saved smoothed CSV, edit each pass's enable flag, target cut depth, feed, RPM and surface speed in a table; generate and save a G-code preview.
- Settings tab: sensor/tool X and Z offsets, safe Z clearance and maximum total cut depth. Scan limits and step are on the Scan tab.

The simulated scan moves from the selected X start to X end (increasing work X, toward the center). CSV files store relative `edge_mm`, measured `z_mm` and absolute `work_x_mm`. Smoothing preserves both X values. Turning previews use saved work X plus tool/sensor offsets, so changing the scan fields after saving does not relocate a loaded profile. There is no separate rim-radius setting. Older two-column CSV files can still be read by the processing library, but the screen requires a newly saved work-X profile for toolpath generation. The coordinate display shows only X/Z. Table Up/Down controls jog the existing Y joint continuously while held and stop on release, independently of the X/Z Continuous checkbox. The underlying PNCconf XYZ joint configuration is preserved.

Scan step determines the spacing and number of synthetic samples. Scan speed displays an estimated machine travel time (`distance / speed`); the simulator creates samples immediately and does not command real motion.

The median window removes isolated spikes; the optional mean window (1 = off) further smooths nearby samples. Both use centered sample windows and may flatten narrow decorative details, so compare the red raw profile with the blue result before saving.

The screen uses G97/G94 for work-X profiles. G96/G95 is disabled because CSS needs a verified spindle-center reference; removing the rim-radius conversion means work X cannot be assumed to be radius. The processing library retains the legacy radius-based generator for older callers. G95 requires actual spindle speed feedback in LinuxCNC. All generated moves are tagged as unverified, and the generator rejects passes deeper than the configured limit. Real spindle feedback, sensor acquisition, machine homing and safe travel are future hardware steps.

The Turning tab has G-code text on the left and LinuxCNC's **actual QtVCP GCodeGraphics** on the right when the `diamondcut` QtVCP screen is launched by LinuxCNC. Standalone `python3 sim_app.py` deliberately shows an explanatory placeholder. The QtVCP handler dynamically registers the native widget with QtVCP, then loads the generated G-code into it. The native preview has been verified on LinuxCNC 2.9.10. The left control panel remains simulated in preview and Mesa bench configurations. The explicit PNCconf real-control launch INI enables LinuxCNC manual controls instead.

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

Generate the preview from the Turning tab. The native widget should occupy the right half of the preview area. If the QtVCP screen fails to start, collect the terminal output and LinuxCNC version. Real HAL bench I/O and STEPGEN0 controls are available only in the Mesa configuration below; laser acquisition and coordinated axis motion are not implemented.

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

Tab **4. Mesa I/O** polls HAL every 100 ms and shows INPUT0–INPUT10, output command states, packet-error count and watchdog status. Faulted or missing data is shown as UNKNOWN. Output states are commands, not physical feedback. OUT0–OUT5 checkboxes directly send HAL commands; an All outputs OFF button attempts all six OFF commands. Checkboxes follow external HAL changes without writing during refresh. ON commands are blocked while current communication/watchdog faults are active; failures are reported in the panel. In the original simulation preview the monitor reports Mesa unavailable. The left motion controls and scan acquisition remain simulated in preview and Mesa bench configurations. The PNCconf integration enables real manual axes, while scan acquisition stays synthetic.

Input bench test: with power off, wire the 5 V supply ground to TB3-12 (INPUT COMMON), and +5 V through a switch to TB3-1 (INPUT0). With the screen running, the physical input indicator and the INPUT0 row should change together. VirtualBox is for bench communication/I/O checks; its timing is not validated for real machine motion. Real Mesa writes, OUT0 indication and INPUT0 reads have been verified manually on the user's board; the GUI input/output controls have also been checked on that board. STEPGEN0 pulses and a DM542 motor running both directions have been verified with manual HAL commands; the new GUI motor controls still need hardware acceptance testing.

## STEPGEN0 motor controls in the Mesa tab

For an existing `diamondcut-mesa-io` setup, close LinuxCNC, run `git pull` in this repository, and launch the same INI again. No configuration regeneration is needed.

Tab **4. Mesa I/O** now includes a pulse-rate field (1–2000 pulses/s, default 500), **Forward (hold)**, **Reverse (hold)** and **STOP motor**. Hold a direction button to generate pulses; releasing it stops and disables STEPGEN0. The interface configures velocity mode, scale 1 pulse/unit, 5 µs step length/space, 10 µs direction setup/hold, maximum velocity 2000 and acceleration 10000. At the tested DM542 setting of 1600 pulses/revolution, 500 pulses/s is about 18.75 RPM.

Changing tabs, application deactivation, closing the screen or a detected communication fault requests motor stop. Recovery never automatically restarts it. Stopping STEPGEN0 disables pulse generation; it does not remove DM542 holding current when ENA is unwired. **All outputs OFF** addresses only OUT0–OUT5; use **STOP motor** for STEPGEN0. The left axis jog and E-stop controls still affect the simulator and do not control this bench motor. This panel is for a free motor on the bench with the existing VirtualBox test setup, not coordinated machine movement.

The controller command sequence, reverse direction, fault rejection and cleanup paths have eight standard-library regression tests. Qt event behavior and the integrated controls must be verified on the LinuxCNC desktop.

## Real manual controls with a PNCconf configuration

First verify the generated AXIS configuration with a free motor. Close LinuxCNC, then run:

```bash
git pull
python3 tools/setup_machine_qtvcp.py --source ~/linuxcnc/configs/diamondcut-machine_001/diamondcut-machine_001.ini
linuxcnc ~/linuxcnc/configs/diamondcut-machine_001/diamondcut-control.ini
```

The script creates a separate `diamondcut-control.ini` beside the original INI, preserves the source INI and all HAL files, and links the QtVCP screen to this repository. Both launch INIs share PNCconf-managed HAL, tool and variable files. The real-control backend currently supports millimeter machines with exactly three trivkins joints in XYZ order. Mesa channel order may differ: the tested setup is joint 0 X/STEPGEN0, joint 1 Y/STEPGEN2, joint 2 Z/STEPGEN1.

The left panel displays **LINUXCNC — REAL AXES**. **Reset / E-stop** resets or asserts LinuxCNC E-stop; reset does not turn the machine on. **Machine ON/OFF** toggles machine power state. **STOP** stops this screen's jog and aborts current LinuxCNC activity. Continuous jog runs while holding a button and stops on release or application deactivation. With Continuous unchecked, pressing a button requests the selected increment; release does not cancel that increment, but STOP or application deactivation does. Speed is entered in mm/min and clamped to the axis velocity limit. Before homing it jogs the corresponding joint; in teleop mode it jogs the Cartesian axis. Communication faults disable jog controls, request stop and never restart motion on recovery.

Machine and Work positions come from LinuxCNC status, including work, G92 and tool offsets and XY rotation. **Home All** uses the configured LinuxCNC homing sequence. The uploaded free-motor configuration has no connected home inputs or search/latch velocities, so it establishes the reference without searching for switches. Physical switch homing must be configured in PNCconf/INI/HAL with verified input channels, polarity, search direction, search/latch speeds and home offsets. Home All then invokes that configured procedure; the screen itself does not invent switch wiring or change homing parameters. **Zero Work X/Z** uses G10 L20 in the active work coordinate system and requires X and Z homed and motion stopped. The screen does not bypass homing or auto-home. Before homing, clicking Zero Work explains the required Home All step instead of silently disabling the button. After touch-off, the backend waits for the return to Manual mode before refreshing the controls. Y remains a manual table joint. The setup script excludes Y from Home All in diamondcut-control.ini and sets Z then X homing. It adds NO_FORCE_HOMING for MDI with unhomed Y; the screen independently gates work-zero commands on X/Z homing. Rerun the setup script after every PNCconf regeneration. Page Up/Down jog the table while held, except when editing fields. The handler exports table-lock (HAL bit input): TRUE stops and blocks Y jog. It is unconnected by default; the physical part-change-window signal must be wired before that interlock is active. The generated launch INI uses LATHE=1 and GEOMETRY=XZ for the preview. Work-home movement remains disabled until clearance and geometry are verified. Laser scan remains synthetic and generated G-code remains preview-only. In this mode Mesa I/O is read-only and the direct bench STEPGEN0 controls are hidden; the screen never writes stepgen pins owned by LinuxCNC.

The user's VirtualBox free-motor test used SERVO_PERIOD = 10000000 ns, watchdog = 90000000 ns, and P = 100 for all three stepgen PID loops. These are bench settings, not validated machine timing. A 320 pulses/mm scale is provisional (1600 pulses/revolution with an assumed 5 mm/revolution); real mechanics require their actual scale. After changing PNCconf settings, test the original AXIS INI and rerun `setup_machine_qtvcp.py` to refresh the separate launch INI. PNCconf may regenerate manual timing/P edits, so keep those settings consistent in its project.

Validation: 21 controller/configuration tests pass. An offscreen Qt smoke test checked continuous press/release, incremental motion, application deactivation, fault blocking and unchanged standalone simulation. Real NML/QtVCP and hardware acceptance are performed on the LinuxCNC desktop.
