"""Pure profile processing and preview G-code generation; no machine I/O."""
from __future__ import annotations

import csv
from bisect import bisect_right
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class Sample:
    edge_mm: float
    z_mm: float
    work_x_mm: float | None = None
    x_reference: str = "work"


@dataclass(frozen=True)
class PassSpec:
    depth_mm: float
    feed: float
    rpm: int
    surface_speed: float
    enabled: bool = True
    use_css: bool | None = None
    cut_direction: str | None = None


def simulated_scan(radius_mm: float, step_mm: float) -> list[Sample]:
    if radius_mm <= 0 or step_mm <= 0:
        raise ValueError("Radius and step must be positive")
    result = []
    count = math.ceil(radius_mm / step_mm)
    for i in range(count + 1):
        edge = min(i * step_mm, radius_mm)
        radius = radius_mm - edge
        progress = edge / radius_mm
        # About 20 mm downward (+Z) over the scan, with level ends.
        shape = 1.0 + 20.0 * progress ** 2 * (3.0 - 2.0 * progress)
        shape += 0.7 * math.exp(-((radius - 0.72 * radius_mm) / (0.10 * radius_mm)) ** 2)
        shape += 0.32 * math.exp(-((radius - 0.36 * radius_mm) / (0.16 * radius_mm)) ** 2)
        noise = 0.07 * math.sin(i * 2.34) + 0.04 * math.sin(i * 0.43)
        result.append(Sample(edge, shape + noise))
    return result


def simulated_scan_range(start_x: float, end_x: float, step_mm: float,
                         radius_at_start: float | None = None, *, centered_x: bool = False) -> list[Sample]:
    """Travel distance rises from scan start, with either sign of work-X travel."""
    span = abs(end_x - start_x)
    direction = 1 if end_x > start_x else -1
    if not all(math.isfinite(v) for v in (start_x, end_x, step_mm)):
        raise ValueError("Scan positions must be finite")
    if span <= 0:
        raise ValueError("Scan start and end must differ")
    if radius_at_start is not None and (not math.isfinite(radius_at_start) or span > radius_at_start):
        raise ValueError("Scan distance exceeds legacy rim radius")
    if centered_x and (start_x > 0 or end_x > 0):
        raise ValueError("Centered-X scan coordinates must be <= 0; +X moves toward the center")
    raw = simulated_scan(span, step_mm)
    edges = [p.edge_mm for p in raw]
    def z_at(edge):
        index = min(max(bisect_right(edges, edge) - 1, 0), len(raw) - 2)
        left, right = raw[index:index + 2]
        return left.z_mm + (right.z_mm - left.z_mm) * (edge - left.edge_mm) / (right.edge_mm - left.edge_mm)
    return [Sample(s.edge_mm, z_at(s.edge_mm if direction > 0 else span - s.edge_mm),
                   start_x + direction * s.edge_mm, "spindle_center" if centered_x else "work") for s in raw]


def smooth(samples: list[Sample], window: int = 5, average_window: int = 1) -> list[Sample]:
    if window < 1 or window % 2 != 1 or average_window < 1 or average_window % 2 != 1:
        raise ValueError("Smoothing windows must be positive odd numbers")
    if not samples:
        raise ValueError("No scan samples")
    half = window // 2
    filtered = [
        Sample(s.edge_mm, median(p.z_mm for p in samples[max(0, i-half):min(len(samples), i+half+1)]), s.work_x_mm, s.x_reference)
        for i, s in enumerate(samples)
    ]
    if average_window == 1:
        return filtered
    half = average_window // 2
    return [
        Sample(s.edge_mm, sum(p.z_mm for p in filtered[max(0, i-half):min(len(filtered), i+half+1)])
               / len(filtered[max(0, i-half):min(len(filtered), i+half+1)]), s.work_x_mm, s.x_reference)
        for i, s in enumerate(filtered)
    ]


def save_csv(path: str | Path, samples: list[Sample]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        with_work = bool(samples) and all(s.work_x_mm is not None for s in samples)
        with_reference = with_work and any(s.x_reference != "work" for s in samples)
        writer.writerow((["edge_mm", "z_mm", "work_x_mm"] + (["x_reference"] if with_reference else []))
                        if with_work else ["edge_mm", "z_mm"])
        for s in samples:
            row = [f"{s.edge_mm:.4f}", f"{s.z_mm:.4f}"]
            if with_work:
                row.append(f"{s.work_x_mm:.4f}")
            if with_reference:
                row.append(s.x_reference)
            writer.writerow(row)


def load_csv(path: str | Path) -> list[Sample]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames not in (["edge_mm", "z_mm"], ["edge_mm", "z_mm", "work_x_mm"],
                                     ["edge_mm", "z_mm", "work_x_mm", "x_reference"]):
            raise ValueError("Expected CSV columns: edge_mm,z_mm[,work_x_mm]")
        samples = [Sample(float(row["edge_mm"]), float(row["z_mm"]),
                          float(row["work_x_mm"]) if "work_x_mm" in row else None,
                          row.get("x_reference", "work")) for row in reader]
    if len(samples) < 2 or not all(math.isfinite(s.edge_mm) and math.isfinite(s.z_mm) for s in samples):
        raise ValueError("Profile needs at least two finite samples")
    if samples[0].edge_mm < 0 or any(a.edge_mm >= b.edge_mm for a, b in zip(samples, samples[1:])):
        raise ValueError("edge_mm must rise strictly from the rim edge")
    if samples[0].work_x_mm is not None:
        if any(s.work_x_mm is None or not math.isfinite(s.work_x_mm) for s in samples):
            raise ValueError("Invalid work X coordinates")
        direction = 1 if samples[-1].work_x_mm > samples[0].work_x_mm else -1
        start = samples[0].work_x_mm - direction * samples[0].edge_mm
        if any(not math.isclose(s.work_x_mm - direction * s.edge_mm, start, abs_tol=0.0002) for s in samples):
            raise ValueError("Work X coordinates must match scan travel")
        if len({s.x_reference for s in samples}) != 1 or samples[0].x_reference not in ('work', 'spindle_center'):
            raise ValueError("Invalid X reference in CSV")
        if samples[0].x_reference == 'spindle_center' and any(s.work_x_mm > 0 for s in samples):
            raise ValueError("Centered X coordinates must be <= 0")
    return samples


def generate_gcode(
    samples: list[Sample], *, rim_radius: float | None = None, passes: int,
    total_depth: float, max_depth: float, feed: float, rpm: int,
    surface_speed: float, max_rpm: int, safe_z: float,
    sensor_x_offset: float = 0.0, sensor_z_offset: float = 0.0,
    tool_x_offset: float = 0.0, tool_z_offset: float = 0.0,
    use_css: bool = False,
    pass_specs: list[PassSpec] | None = None,
    cut_direction: str = "scan",
) -> str:
    if not samples or passes < 1 or feed <= 0 or rpm <= 0 or max_rpm <= 0:
        raise ValueError("Missing profile or invalid machining parameter")
    if max_depth <= 0 or (pass_specs is None and (total_depth <= 0 or total_depth > max_depth)):
        raise ValueError("Cut depth exceeds configured maximum")
    if pass_specs is None:
        pass_specs = [PassSpec(total_depth * i / passes, feed, rpm, surface_speed)
                      for i in range(1, passes + 1)]
    active = [p for p in pass_specs if p.enabled]
    def css_mode(p):
        return use_css if p.use_css is None else p.use_css
    any_css = any(css_mode(p) for p in active)
    if not active or any(not math.isfinite(p.depth_mm) or p.depth_mm <= 0 or p.depth_mm > max_depth or
                         not math.isfinite(p.feed) or p.feed <= 0 or p.rpm <= 0 or
                         (css_mode(p) and (not math.isfinite(p.surface_speed) or p.surface_speed <= 0))
                         for p in active):
        raise ValueError("Invalid per-pass setting or maximum cut depth exceeded")
    if any(a.depth_mm >= b.depth_mm for a, b in zip(active, active[1:])):
        raise ValueError("Enabled pass depths must increase")
    if safe_z <= 0:
        raise ValueError("Invalid clearance or surface speed")
    if rim_radius is None:
        if any(s.work_x_mm is None or not math.isfinite(s.work_x_mm) for s in samples):
            raise ValueError("Profile needs saved work X coordinates")
        if any_css and any(s.x_reference != 'spindle_center' for s in samples):
            raise ValueError("CSS needs a new CSV marked spindle_center; old edge-zero files must be rescanned")
        xs = [s.work_x_mm + tool_x_offset - sensor_x_offset for s in samples]
        diffs = [b - a for a, b in zip(xs, xs[1:])]
        if not diffs or not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
            raise ValueError("Work X must be strictly monotonic")
        if (any_css or all(s.x_reference == "spindle_center" for s in samples)) and any(x > 0 for x in xs):
            raise ValueError("CSS tool path cannot cross the spindle center")
    else:
        if not math.isfinite(rim_radius) or rim_radius <= 0:
            raise ValueError("Invalid legacy rim radius")
        xs = [rim_radius - s.edge_mm + tool_x_offset - sensor_x_offset for s in samples]
        if any(x < 0 for x in xs) or any(xs[i] <= xs[i+1] for i in range(len(xs)-1)):
            raise ValueError("X values must descend toward, but not beyond, spindle center")
    # Work Z0 is touched off at the first profile point. Sensor readings carry
    # an arbitrary absolute baseline; retain their differences, not that bias.
    z_reference = samples[0].z_mm if rim_radius is None else 0.0
    zprofile = [s.z_mm - z_reference + tool_z_offset - sensor_z_offset for s in samples]
    # Current machine: -Z is up/clearance, +Z is down/into the face.
    z_sign = 1 if rim_radius is None else -1
    clearance = min(zprofile) - safe_z if z_sign == 1 else max(zprofile) + safe_z
    if not all(math.isfinite(z) for z in zprofile) or not math.isfinite(clearance):
        raise ValueError("Invalid safe Z")
    if cut_direction not in ('scan', 'outer_to_center', 'center_to_outer'):
        raise ValueError("Invalid cutting direction")
    def pass_points(setting):
        direction = setting.cut_direction or cut_direction
        if direction not in ('scan', 'outer_to_center', 'center_to_outer'):
            raise ValueError('Invalid per-pass cutting direction')
        points = list(zip(xs, zprofile))
        if direction != 'scan':
            points.sort(key=lambda p: abs(p[0]), reverse=direction == 'outer_to_center')
        return points
    def start_rpm(setting):
        if not css_mode(setting):
            return setting.rpm
        radius = abs(pass_points(setting)[0][0])
        return min(max_rpm, setting.surface_speed * 1000 / (2 * math.pi * radius)) if radius else max_rpm
    lines = [
        "(PROFILE TOOLPATH - VERIFY COORDINATES AND CLEARANCES)",
        "(X_REFERENCE spindle_center)" if samples[0].x_reference == 'spindle_center' else "(X_REFERENCE legacy)",
        "G21 G90 G40 G49 G54",
        "G8",
        "G94",
        f"G97 S{start_rpm(active[0]):.3f}" if css_mode(active[0]) else f"G97 S{active[0].rpm}",
        "M3",
    ]
    for number, setting in enumerate(active, 1):
        pass_xs, pass_zs = map(list, zip(*pass_points(setting)))
        css = css_mode(setting)
        depth = setting.depth_mm
        lines.append(f"(PASS {number}/{len(active)}; depth {depth:.4f} mm)")
        lines.append(f"G97 S{start_rpm(setting):.3f}" if css else f"G97 S{setting.rpm}")
        lines.append("G94")
        if not css:
            lines.append(f"F{setting.feed:.4f}")
        lines.append(f"G0 Z{clearance:.4f}")
        lines.append(f"G0 X{pass_xs[0]:.4f}")
        if css:
            lines += [f"G96 D{max_rpm} S{setting.surface_speed:.3f}", "G95", f"F{setting.feed:.4f}"]
        lines.append(f"G1 Z{pass_zs[0] + z_sign * depth:.4f}")
        for x, z in zip(pass_xs[1:], pass_zs[1:]):
            lines.append(f"G1 X{x:.4f} Z{z + z_sign * depth:.4f}")
        if css:
            lines += [f"G97 S{start_rpm(setting):.3f}", "G94"]
        lines.append(f"G0 Z{clearance:.4f}")
        lines.append(f"G0 X{pass_xs[0]:.4f}")
    lines += ["M5", "G97 G94", "M2"]
    return "\n".join(lines) + "\n"
