import unittest

from profile import Sample, generate_gcode, simulated_scan, smooth


class ProfileTests(unittest.TestCase):
    def test_scan_and_filter_keep_x_positions(self):
        raw = simulated_scan(100, 1)
        filtered = smooth(raw)
        self.assertEqual(len(raw), 101)
        self.assertEqual([p.edge_mm for p in raw], [p.edge_mm for p in filtered])

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


if __name__ == "__main__":
    unittest.main()
