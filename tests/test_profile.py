import tempfile
import unittest
from pathlib import Path

from profile import PassSpec, Sample, generate_gcode, load_csv, save_csv, simulated_scan, simulated_scan_range, smooth


class ProfileTests(unittest.TestCase):
    def test_scan_and_filter_keep_x_positions(self):
        raw = simulated_scan(100, 1)
        filtered = smooth(raw)
        self.assertEqual(len(raw), 101)
        self.assertEqual([p.edge_mm for p in raw], [p.edge_mm for p in filtered])

    def test_scan_range_starts_at_selected_work_x_but_csv_is_relative(self):
        points = simulated_scan_range(12, 22, 2, 20)
        self.assertEqual([p.edge_mm for p in points], [0, 2, 4, 6, 8, 10])
        with self.assertRaises(ValueError):
            simulated_scan_range(22, 12, 2, 20)
        with self.assertRaises(ValueError):
            simulated_scan_range(12, 42, 2, 20)

    def test_independent_median_and_mean_smoothing(self):
        points = [Sample(i, z) for i, z in enumerate((0, 0, 9, 0, 0))]
        self.assertEqual([s.z_mm for s in smooth(points, 3, 1)], [0, 0, 0, 0, 0])
        gradual = [Sample(i, z) for i, z in enumerate((0, 0, 3, 0, 0))]
        self.assertEqual(smooth(gradual, 1, 3)[2].z_mm, 1)
        with self.assertRaises(ValueError):
            smooth(points, 3, 2)

    def test_preview_uses_center_as_x_zero_and_safe_pass_depths(self):
        points = [Sample(0, 2), Sample(50, 2.5), Sample(100, 2)]
        code = generate_gcode(
            points, rim_radius=100, passes=2, total_depth=0.2,
            max_depth=0.5, feed=0.1, rpm=500, surface_speed=150,
            max_rpm=1200, safe_z=5, use_css=True,
        )
        self.assertIn("G8", code)
        self.assertIn("G96 D1200 S150.000", code)
        self.assertIn("G95", code)
        self.assertIn("G1 X0.0000 Z1.8000", code)
        self.assertEqual(code.count("(PASS"), 2)

    def test_depth_guard_and_center_guard(self):
        points = [Sample(0, 1), Sample(10, 1)]
        options = dict(
            rim_radius=10, passes=1, total_depth=1, max_depth=0.5,
            feed=0.1, rpm=500, surface_speed=100, max_rpm=1200, safe_z=5,
        )
        with self.assertRaises(ValueError):
            generate_gcode(points, **options)
        options["total_depth"] = 0.1
        options["tool_x_offset"] = -1
        with self.assertRaises(ValueError):
            generate_gcode(points, **options)

    def test_saved_smoothed_profile_and_independent_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "smoothed.csv"
            points = [Sample(0, 2), Sample(5, 2.5), Sample(10, 2)]
            save_csv(path, points)
            self.assertEqual(load_csv(path), points)
            code = generate_gcode(
                load_csv(path), rim_radius=10, passes=1, total_depth=3,
                max_depth=0.5, feed=50, rpm=500, surface_speed=150,
                max_rpm=1200, safe_z=5,
                pass_specs=[PassSpec(0.1, 30, 400, 100),
                            PassSpec(0.2, 20, 450, 120, False),
                            PassSpec(0.3, 15, 600, 130)],
            )
            self.assertEqual(code.count("(PASS"), 2)
            self.assertIn("G97 S600", code)
            self.assertIn("F15.0000", code)
            self.assertNotIn("G97 S450", code)


if __name__ == "__main__":
    unittest.main()
