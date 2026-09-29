"""Pure profile processing and preview G-code generation; no machine I/O."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class Sample:
    edge_mm: float
    z_mm: float


@dataclass(frozen=True)
class PassSpec:
    depth_mm: float
    feed: float
    rpm: int
    surface_speed: float
    enabled: bool = True


def simulated_scan(radius_mm: float, step_mm: float) -> list[Sample]:
    if radius_mm <= 0 or step_mm <= 0:
        raise ValueError("Radius and step must be positive")
    result = []
    count = math.ceil(radius_mm / step_mm)
    for i in range(count + 1):
        edge = min(i * step_mm, radius_mm)
        radius = radius_mm - edge
        shape = 1.0 + 0.7 * math.exp(-((radius - 0.72 * radius_mm) / (0.10 * radius_mm)) ** 2)
        shape += 0.32 * math.exp(-((radius - 0.36 * radius_mm) / (0.16 * radius_mm)) ** 2)
        noise = 0.07 * math.sin(i * 2.34) + 0.04 * math.sin(i * 0.43)
        result.append(Sample(edge, shape + noise))
    return result


def smooth(samples: list[Sample], window: int = 5) -> list[Sample]:
    if window < 1 or window % 2 != 1:
        raise ValueError("Median window must be a positive odd number")
    if not samples:
        raise ValueError("No scan samples")
    half = window // 2
    return [
        Sample(s.edge_mm, median(p.z_mm for p in samples[max(0, i-half):min(len(samples), i+half+1)]))
        for i, s in enumerate(samples)
    ]


def save_csv(path: str | Path, samples: list[Sample]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["edge_mm", "z_mm"])
        writer.writerows((f"{s.edge_mm:.4f}", f"{s.z_mm:.4f}") for s in samples)


def load_csv(path: str | Path) -> list[Sample]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["edge_mm", "z_mm"]:
            raise ValueError("Expected CSV columns: edge_mm,z_mm")
        samples = [Sample(float(row["edge_mm"]), float(row["z_mm"])) for row in reader]
    if len(samples) < 2 or not all(math.isfinite(s.edge_mm) and math.isfinite(s.z_mm) for s in samples):
        raise ValueError("Profile needs at least two finite samples")
    if samples[0].edge_mm < 0 or any(a.edge_mm >= b.edge_mm for a, b in zip(samples, samples[1:])):
        raise ValueError("edge_mm must rise strictly from the rim edge")
    return samples


def generate_gcode(
    samples: list[Sample], *, rim_radius: float, passes: int,
    total_depth: float, max_depth: float, feed: float, rpm: int,
    surface_speed: float, max_rpm: int, safe_z: float,
    sensor_x_offset: float = 0.0, sensor_z_offset: float = 0.0,
    tool_x_offset: float = 0.0, tool_z_offset: float = 0.0,
    use_css: bool = False,
    pass_specs: list[PassSpec] | None = None,
) -> str:
    if not samples or passes < 1 or rim_radius <= 0 or feed <= 0 or rpm <= 0 or max_rpm <= 0:
        raise ValueError("Missing profile or invalid machining parameter")
    if max_depth <= 0 or (pass_specs is None and (total_depth <= 0 or total_depth > max_depth)):
        raise ValueError("Cut depth exceeds configured maximum")
    if pass_specs is None:
        pass_specs = [PassSpec(total_depth * i / passes, feed, rpm, surface_speed)
                      for i in range(1, passes + 1)]
    active = [p for p in pass_specs if p.enabled]
    if not active or any(not math.isfinite(p.depth_mm) or p.depth_mm <= 0 or p.depth_mm > max_depth or
                         not math.isfinite(p.feed) or p.feed <= 0 or p.rpm <= 0 or
                         (use_css and (not math.isfinite(p.surface_speed) or p.surface_speed <= 0))
                         for p in active):
        raise ValueError("Invalid per-pass setting or maximum cut depth exceeded")
    if any(a.depth_mm >= b.depth_mm for a, b in zip(active, active[1:])):
        raise ValueError("Enabled pass depths must increase")
    if safe_z <= 0 or (use_css and surface_speed <= 0):
        raise ValueError("Invalid clearance or surface speed")
    xs = [rim_radius - s.edge_mm + tool_x_offset - sensor_x_offset for s in samples]
    if any(x < 0 for x in xs) or any(xs[i] <= xs[i+1] for i in range(len(xs)-1)):
        raise ValueError("X values must descend toward, but not beyond, spindle center")
    zprofile = [s.z_mm + tool_z_offset - sensor_z_offset for s in samples]
    # Positive Z points away from the face in this provisional geometry.
    if any(z + safe_z <= z for z in zprofile):
        raise ValueError("Invalid safe Z")
    lines = [
        "(SIMULATION PREVIEW - VERIFY COORDINATES AND CLEARANCES BEFORE MACHINE USE)",
        "G21 G90 G40 G49 G54",
        "G8",  # Radius X mode. Center is X0.
        "G95" if use_css else "G94",
        f"G96 D{max_rpm} S{active[0].surface_speed:.3f}" if use_css else f"G97 S{active[0].rpm}",
        "M3",
    ]
    for number, setting in enumerate(active, 1):
        depth = setting.depth_mm
        lines.append(f"(PASS {number}/{len(active)}; depth {depth:.4f} mm)")
        lines.append(f"G96 D{max_rpm} S{setting.surface_speed:.3f}" if use_css else f"G97 S{setting.rpm}")
        lines.append(f"F{setting.feed:.4f}")
        lines.append(f"G0 Z{zprofile[0] + safe_z:.4f}")
        lines.append(f"G0 X{xs[0]:.4f}")
        lines.append(f"G1 Z{zprofile[0] - depth:.4f}")
        for x, z in zip(xs[1:], zprofile[1:]):
            lines.append(f"G1 X{x:.4f} Z{z - depth:.4f}")
        lines.append(f"G0 Z{zprofile[-1] - depth + safe_z:.4f}")
        # Retract above the outer edge before the next entry.
        lines.append(f"G0 Z{max(zprofile) + safe_z:.4f}")
        lines.append(f"G0 X{xs[0]:.4f}")
    lines += ["M5", "G97 G94", "M2"]
    return "\n".join(lines) + "\n"
