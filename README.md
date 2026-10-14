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

The synthetic scan accepts either direction between selected Work X start/end. Work X0 is the spindle center and +X moves toward it, so the working side uses negative X in G8 radius mode. New CSV files store distance from scan start (`edge_mm`), sensor Z, `work_x_mm`, and `x_reference=spindle_center`; smoothing preserves the reference. The cutting direction can be selected independently. The processing library can read old files, but the screen requires a newly scanned spindle_center CSV for generation in either mode. The coordinate display shows X/Z; Y remains a manual table axis.

Scan step determines the spacing and number of synthetic samples. Scan speed displays an estimated machine travel time (`distance / speed`); the simulator creates samples immediately and does not command real motion.

The median window removes isolated spikes; the optional mean window (1 = off) further smooths nearby samples. Both use centered sample windows and may flatten narrow decorative details, so compare the red raw profile with the blue result before saving.

The screen supports fixed RPM G97/G94 and native CSS G96/G95. CSS requires a calibrated spindle-center Work X reference, an explicit maximum RPM, and verified real spindle speed feedback for Run. Laser scan acquisition is still synthetic. CSS simulation uses commanded RPM and nominal feed per revolution, without hardware feedback or acceleration dynamics.

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

Machine and Work positions come from LinuxCNC status, including work, G92 and tool offsets and XY rotation. **Home All** uses the configured LinuxCNC homing sequence. The uploaded free-motor configuration has no connected home inputs or search/latch velocities, so it establishes the reference without searching for switches. Physical switch homing must be configured in PNCconf/INI/HAL with verified input channels, polarity, search direction, search/latch speeds and home offsets. Home All then invokes that configured procedure; the screen itself does not invent switch wiring or change homing parameters. **Set spindle center at known radius** in Settings sets the current tool-tip position to the negative known radius, establishing G54 X0 at the spindle center. X has no zero button: Work X shows the radius from the calibrated spindle center. **0 beside Work Z** sets surface Z0 through G10 L20. These actions require X/Z homed and motion stopped. The screen does not bypass homing or auto-home. Before homing, clicking Zero Work explains the required Home All step instead of silently disabling the button. After touch-off, the backend waits for the return to Manual mode before refreshing the controls. Y remains a manual table joint. The setup script excludes Y from Home All in diamondcut-control.ini and sets Z then X homing. It adds NO_FORCE_HOMING for MDI with unhomed Y; the screen independently gates work-zero commands on X/Z homing. Rerun the setup script after every PNCconf regeneration. Page Up/Down jog the table while held, except when editing fields. The handler exports table-lock (HAL bit input): TRUE stops and blocks Y jog. It is unconnected by default; the physical part-change-window signal must be wired before that interlock is active. The generated launch INI uses LATHE=1 and GEOMETRY=XZ for the preview. Go to scan start X positions X at the loaded profile reference point after the operator confirms the tool is clear; Z is unchanged. Laser scan remains synthetic. Generated G-code can be simulated graphically or executed with Run G-code. In this mode Mesa I/O offers a password-protected maintenance test; direct bench STEPGEN0 controls are hidden; the screen never writes stepgen pins owned by LinuxCNC.

The user's VirtualBox free-motor test used SERVO_PERIOD = 10000000 ns, watchdog = 90000000 ns, and P = 100 for all three stepgen PID loops. These are bench settings, not validated machine timing. A 320 pulses/mm scale is provisional (1600 pulses/revolution with an assumed 5 mm/revolution); real mechanics require their actual scale. After changing PNCconf settings, test the original AXIS INI and rerun `setup_machine_qtvcp.py` to refresh the separate launch INI. PNCconf may regenerate manual timing/P edits, so keep those settings consistent in its project.

Validation: 21 controller/configuration tests pass. An offscreen Qt smoke test checked continuous press/release, incremental motion, application deactivation, fault blocking and unchanged standalone simulation. Real NML/QtVCP and hardware acceptance are performed on the LinuxCNC desktop.

### Protected output and spindle test

In real-control Mesa I/O, Unlock output test asks for a password. The first use creates and confirms a password (at least six characters); only a salted PBKDF2 hash is stored at ~/.config/diamondcut/output-test-password.json with owner-only permissions. There is no default password. A warning with No as default appears before unlocking and before every output/spindle ON command.

Unlock requires healthy Mesa, machine ON, stopped axes and idle Manual mode. While unlocked, axis jog, homing and touch-off are blocked. OUT0–OUT5 can be switched and the spindle can be started forward at the selected RPM using the LinuxCNC spindle command and current PNCconf wiring. HAL-linked outputs are not force-overridden: HAL reports a write failure if another component owns the pin. The provided configuration has all six physical outputs unassigned.

Spindle OFF and All outputs OFF require no password. Closing/hiding the Mesa tab, application deactivation, STOP, machine OFF/E-stop, a communication fault or shutdown locks the session and attempts all six OFF commands plus spindle OFF. An OFF failure is displayed and keeps axis controls inhibited until a successful All outputs OFF clears it. Hardware feedback is not inferred from a command. Test mode never writes LinuxCNC-owned stepgen pins.

### QtVCP X/Z preview orientation

The native preview starts in an orthographic X/Z view: X home at the left,
Z home at the top, positive X right and positive Z down. The tip-position
yellow cone silhouette stays aligned with Z, including when a tool-table entry is loaded.
It uses actual position minus tool offset, with a dark gray background.
Markers are drawn in the same OpenGL framebuffer as the paths, with a full
clear on every frame. There is no transparent child widget over the native GL
surface. Live tool Work X/Z coordinates were originally shown in a label below the
graph. Markers are added after native paintGL, even if it returns early.
The cyan `Work 0` cross/circle follows the active G5x and G92 offsets, including
when both offsets are zero. Reset X/Z view fits the program, machine origin
work origin and actual tool tip and restores this orientation after panning or rotation.
Y is not drawn as a cutting axis. These are renderer settings only; the
PNCconf-generated kinematics, homing and motion configuration are unchanged.

For work-X profiles on this machine, -Z retracts up and +Z cuts down.
The first scan point is anchored at Work Z0; later points retain their Z
differences from that point. Pass depth is added to this relative surface Z,
so a 0.01 mm pass starts at Z0.0100 when sensor/tool Z offsets match. Configured
tool Z minus sensor Z calibration is still applied. Each rapid X move occurs at
min(surface Z) minus safe clearance, above the entire profile. Regenerate the
preview after updating; previously saved G-code retains its old Z signs.
The legacy rim-radius API retains its historical +Z clearance convention.

The preview hides the live tool-motion backplot (yellow jog trail); the yellow
tool tip marker remains. After successful Zero Work X/Z, it polls the updated
status, reloads the same displayed G-code to rebuild its offset-dependent
geometry and restores the X/Z view. G-code values and the saved scan are not
rewritten by touch-off. A rejected/failed zero command does not trigger reload.

### G-code simulation and execution

Set the **Passes** count in **Settings**. In **Toolpath & Turning**, load the
smoothed CSV and configure the enabled pass rows. Changing Passes or Total depth
rebuilds the table automatically; changing the default feed/RPM/surface speed
updates that column. Individual cells remain editable. **Simulate G-code** regenerates the program and animates the yellow tool
marker from the current Work X/Z position. It sends no motion or spindle commands.
The speed multiplier affects only this graphical playback; rapid moves use the X/Z rates from Settings, capped by the active machine
velocity limits; feed moves use their programmed F values. Acceleration
and spindle dynamics are not simulated. **Stop simulation** restores the actual
tool marker. Simulation requires the native LinuxCNC QtVCP graph.

**Run G-code** regenerates and saves a separate program snapshot, then opens it
in LinuxCNC AUTO and starts from line 0, including all enabled passes and M3/M5
spindle commands. It requires healthy Mesa communication, machine ON, idle Manual
mode, stopped axes, homed X/Z, active G54 without XY rotation, and no maintenance
output test or simulation. Y is not commanded and does not require homing.
Every generated X/Z endpoint is checked against the current INI soft limits after
applying G54/G92 offsets. The generated header cancels tool-length compensation
with G49. CSS programs require the calibrated center reference and verified real RPM feedback; old edge-zero profiles are not converted automatically.

During execution, manual jog/home/work-zero controls are blocked and the screen
shows the current program line. **STOP** aborts the program and switches the
spindle off. Completion returns to Manual mode. Native LinuxCNC remains responsible
for trajectory execution, limits and spindle control; the screen sends NML
commands and never writes stepgen pins. Hardware execution still needs acceptance
testing on the machine.

### Machine coordinate limits in Settings

Settings shows X/Z and the manual Y table Min/Max travel in machine mm, independent
of Work 0. Values initially come from the active INI. Turn Machine OFF, edit the
limits and click **Save machine limits**, then restart LinuxCNC. Saving updates
both AXIS and corresponding XYZ JOINT sections in the active launch INI and keeps
a `.ini.limits-backup`. It sends no runtime limit commands; Run is blocked until
restart so it cannot use limits that have not yet become active.

The configuration directory also stores `diamondcut-limits.json`. After PNCconf
regeneration, rerun `setup_machine_qtvcp.py`; it reapplies these saved limits to
`diamondcut-control.ini` while preserving the original PNCconf INI. These screen
overrides take precedence over PNCconf travel limits for the Diamond Cut launch
configuration. Set travel values for the real mechanics; increasing a limit does
not increase physical travel. Y remains manual.

### Linked G-code selection and execution line

Click a trajectory segment in the native QtVCP graph to scroll the text to its
one-based G-code line and highlight it in yellow. Selecting a text line also
highlights the corresponding graph segment; comments and non-motion lines have
no trajectory segment. A label above the text shows the selected line number.
During **Run G-code**, the screen follows LinuxCNC `motion_line`, highlights the
executing text line in green and scrolls it into view. It updates only when the
line changes. After STOP/completion the last line remains selected in yellow.
Line selection is a display action; Run continues to start the entire program
from line 0.

### Rapid jog, table speed and G-code line numbers

**Settings** has independent **X rapid / G0 speed**, **Z rapid / G0 speed** and
**Y table speed**, all in mm/min. Save X/Z rapid speeds with Machine OFF and restart
LinuxCNC. This updates the corresponding AXIS/JOINT maximum velocities, preserves
the stepgen velocity margin, and updates the trajectory velocity ceiling. These
axis limits also cap cutting feeds. `diamondcut-rapids.json` preserves the values
when the setup script is rerun after PNCconf regeneration. Run is blocked until
restart after saving. Jog commands continue to respect the active machine limits.

Hold **Ctrl** with an X/Z jog button to use that axis's rapid rate. For continuous
jog, pressing/releasing Ctrl while holding the mouse button switches between
rapid and the normal Jog speed. Incremental jog keeps its selected distance.
Release still stops continuous jogging. The Y buttons and Page Up/Down always
use the dedicated Settings Y speed, independent of normal Jog speed and Ctrl.
The configured Y machine maximum velocity remains an upper bound.

**Show G-code line numbers** toggles a separate margin beside the text. Numbers
remain aligned while scrolling and do not alter saved or executed G-code. Y speed
and the number-margin preference are remembered automatically on this computer.

### Turning page layout

Work X/Z zero buttons sit beside the corresponding Work DROs. In the turning tab,
machining controls and the pass table occupy the upper left, with G-code text in
the upper right. The native X/Z graph spans the full width underneath. Drag the
horizontal/vertical splitters to adjust text/control widths and graph height.
Line selection and execution following work across this layout as before.

### Open an existing G-code file

**Open G-code** beside Save G-code loads `.ngc`, `.nc` or `.tap` text into the
linked text/graph view. Simulate and Run use the opened code without regenerating
it from the CSV; Generate preview explicitly replaces it with a new profile
program. Loading a smoothed CSV switches back to profile generation.

The native graph can preview files supported by LinuxCNC. Screen simulation and
Run accept straight X/Z programs with explicit G21 G90 G40 G49 G54 G8, feed and spindle modes before motion, a spindle S setting before M3, M5 before M2, and an M2 ending. G96 requires an explicit D maximum RPM; a new F is required after changing G94/G95. Unsupported/ambiguous programs are blocked before AUTO start. All
existing homing, machine-state and machine-coordinate limit checks remain active.

Run is light blue. Reset X/Z view is beside the simulation speed. The explanatory
text beneath the graph is removed; execution and simulation status appear in the
window status bar.

### Spindle-centered X and native CSS / feed per revolution

Physical Home locations and PNCconf homing settings are unchanged. Work X0 is the
spindle axis. With the existing +X direction toward the center, a tool tip at a
250 mm radius reads X−250 in G8 mode.

1. Home X/Z. Position the tool tip at a measured radius; enter that radius in
   Settings (**Known tool-tip radius**), then press **Set spindle center at known radius**
   in Settings. This executes a stationary G10 L20 touch-off to X−radius and cancels
   active tool compensation with G49. It does not drive any axis to the center.
2. Set Work Z0 at the surface reference corresponding to the first scan sample.
3. In Scan choose negative X start/end, e.g. −250 to −50. Reverse endpoints for
   an outward scan. Smooth and save a new CSV with spindle_center metadata.
4. Select cutting direction independently in Turning; default is outside →
   center. Select **G96 / G95**, set surface speed in m/min, feed in mm/rev, and
   maximum RPM. In CSS the per-pass RPM column is hidden; RPM is calculated from
   surface speed and radius. For example F0.1 specifies 0.1 mm of path per spindle
   revolution, not 0.1 mm/min.

Generated CSS programs position at clearance in G97/G94, enable G96/G95 after
reaching the pass start radius, and restore G97/G94 before rapid return. G96 is
handled by LinuxCNC's motion controller, not the GUI timer. D caps RPM near the
center; constant surface speed cannot be maintained once this cap is reached.

Simulation works without a connected sensor, estimating segment timing using
commanded CSS RPM at each segment's midpoint and the RPM cap. Run of a generated
centered-X program requires center calibration in Settings in the current session and unchanged X
work offsets. CSS/G95 additionally requires a writer connected to
`spindle.0.speed-in` and **Real spindle RPM sensor connected and checked** in
Settings. Verify the displayed real RPM against actual rotation
before checking it; this checkbox does not configure sensor wiring or scaling.
No commanded-RPM loopback is created. Feedback wiring/scaling remains in the
PNCconf/HAL configuration and must be tested for the actual sensor/pulses per rev.
The displayed RPM is signed: M3 feedback must have the correct positive direction.

Run checks G95 path-feed capacity against active X/Z velocity limits at the
maximum commanded RPM for each segment. Reduce feed/rev or surface speed / maximum
RPM if the selected pitch would exceed a limit. Loss of the feedback connection
while executing G95 aborts the program. Existing soft limits and other interlocks
remain enforced. An external X work-offset change invalidates the CSS center calibration.
Recalibrate the center in Settings after changing tools or offsets. X has no operator zero.

### Touch input and independent pass modes

Touching a numeric field or editable pass-table value opens an on-screen keypad;
mouse clicks keep ordinary editing. OK applies the value; Cancel leaves it alone.
Decimal commas are accepted. Text fields use a keyboard with Shift. The Linux
touchscreen driver must deliver real touch events to Qt; a mouse-only emulation
device cannot be distinguished reliably from a mouse. Verify on the actual panel.

Each pass row has its own RPM/CSS mode and Outside → center / Center → outside
direction. Feed is mm/min for RPM rows and mm/rev for CSS rows (also shown in the
mode label and feed-cell tooltip). Switching a row's mode resets its feed to 50
mm/min or 0.1 mm/rev; check the value before generating. RPM and surface-speed
cells remain visible, with the unused value greyed out. The controls above the
table apply defaults to all rows; the common feed control changes only rows of
the selected mode. Changing pass count or total depth retains surviving rows'
speed, mode and direction settings. Maximum RPM remains a shared CSS limit.

The generator preserves X/Z profile pairs when reversing direction, retracts to
clearance between passes, and explicitly selects G97/G94 for positioning before
G96/G95 cutting. A program containing any CSS/G95 pass needs the same real spindle
feedback checks as a program using CSS throughout. Simulation supports mixed modes.

### Fixed X radius, scan reference positioning and Z touch-off

X has no reset or operator offset. Work X and scan endpoints show a positive radius
from the calibrated spindle center. The machine +X direction runs toward the center,
so the G54 X coordinate and CSV/G-code remain negative (G8 radius mode). For example,
with the center at Machine X250, Machine X70 reads Work radius180 and commands G54
X-180. The separate G-code X label shows this signed coordinate. This display mapping
does not change homing, physical motor direction, file coordinates or G96.

1. Home X/Z and calibrate the spindle center at the measured radius in Settings.
2. Load the saved smoothed spindle-center CSV. Its first sample defines Z surface
   reference, independent of each pass's cutting direction. Tool minus sensor X
   offset is applied exactly as in generation.
3. Raise the tool clear of the rim, then press **Go to scan start X** and confirm.
   This makes an X-only G1 move at the selected jog speed, capped to the X limit.
   Z stays where it is. The desktop remains responsive, STOP aborts the move, and
   limits, homing, center calibration and controller health are checked.
4. Lower the tool to touch the rim and press **0 beside Z**. With a profile loaded,
   Z touch-off is blocked until X is within 0.01 mm of the profile reference X.
   The generator subtracts the first scan sample's Z baseline, preserving its shape.

Do not recalibrate X to a new arbitrary point between scanning and turning. There
is no X reset action. The red vertical preview line and cyan X0Z0 mark the real
spindle-center X reference and surface Z0. Actual feed beside X/Z comes from each
joint velocity in mm/min, excluding table Y. Spindle actual remains measured RPM.
