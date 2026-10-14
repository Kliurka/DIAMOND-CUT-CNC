import tempfile
import unittest
from pathlib import Path

from profile import PassSpec, Sample, generate_gcode, load_csv, save_csv, simulated_scan, simulated_scan_range, smooth


class ProfileTests(unittest.TestCase):
    def test_mixed_pass_modes_and_directions_keep_profile_pairs(self):
        from gcode_playback import parse_program
        points = [Sample(0, 2, -100, 'spindle_center'), Sample(20, 3, -80, 'spindle_center')]
        code = generate_gcode(points, passes=3, total_depth=.3, max_depth=.5,
            feed=50, rpm=500, surface_speed=150, max_rpm=1200, safe_z=5,
            pass_specs=[PassSpec(.1, 50, 500, 150, use_css=False, cut_direction='outer_to_center'),
                        PassSpec(.2, .05, 600, 120, use_css=True, cut_direction='center_to_outer'),
                        PassSpec(.3, 40, 700, 100, use_css=False, cut_direction='outer_to_center')])
        passes = code.split('(PASS ')[1:]
        self.assertIn('G0 X-100.0000\nG1 Z0.1000\nG1 X-80.0000 Z1.1000', passes[0])
        self.assertNotIn('G0 X', passes[0][passes[0].index('G1 X-80.0000'):])
        self.assertNotIn('G0 X', passes[1])
        self.assertIn('G96 D1200 S120.000\nG95\nF0.0500\nG1 Z1.2000\nG1 X-100.0000 Z0.2000', passes[1])
        self.assertIn('G97 S700\nG94\nF40.0000', passes[2])
        moves = parse_program(code)
        self.assertTrue(moves.uses_css)
        self.assertTrue(any(m.feed_per_rev for m in moves))

    def test_centered_bidirectional_scan_csv_and_filter(self):
        forward = simulated_scan_range(-250, -240, 2, centered_x=True)
        reverse = simulated_scan_range(-240, -250, 2, centered_x=True)
        self.assertEqual([p.work_x_mm for p in reverse], [-240, -242, -244, -246, -248, -250])
        for a, b in zip(forward, reversed(reverse)):
            self.assertAlmostEqual(a.z_mm, b.z_mm)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'centered.csv'
            save_csv(path, smooth(reverse, 3, 3))
            loaded = load_csv(path)
            self.assertTrue(all(p.x_reference == 'spindle_center' for p in loaded))
            self.assertEqual(loaded[0].work_x_mm, -240)
            self.assertEqual(loaded[-1].work_x_mm, -250)
        with self.assertRaises(ValueError):
            simulated_scan_range(-10, 1, 1, centered_x=True)

    def test_css_negative_center_coordinates_and_separate_cut_direction(self):
        points = [Sample(0, 2, -100, 'spindle_center'), Sample(10, 2.5, -110, 'spindle_center')]
        options = dict(passes=1, total_depth=.1, max_depth=.5, feed=.1, rpm=500,
                       surface_speed=150, max_rpm=1200, safe_z=5, use_css=True)
        code = generate_gcode(points, cut_direction='outer_to_center', **options)
        self.assertIn('G0 X-110.0000', code)
        self.assertIn('G1 X-100.0000 Z0.1000', code)
        self.assertIn('G96 D1200 S150.000', code)
        self.assertIn('G95\nF0.1000', code)
        self.assertLess(code.index('G0 X-110.0000'), code.index('G96'))
        reverse_code = generate_gcode(points, cut_direction='center_to_outer', **options)
        self.assertIn('G0 X-100.0000', reverse_code)
        self.assertIn('G1 X-110.0000 Z0.6000', reverse_code)
        with self.assertRaises(ValueError):
            generate_gcode(points, tool_x_offset=120, **options)

    def test_work_x_clearance_is_above_whole_profile_and_depth_points_down(self):
        points = [Sample(0, 2, 10), Sample(5, -1, 15), Sample(10, 3, 20)]
        code = generate_gcode(points, passes=2, total_depth=.2, max_depth=.5,
                              feed=30, rpm=500, surface_speed=100,
                              max_rpm=1200, safe_z=5)
        self.assertEqual(code.count('G0 Z-8.0000'), 4)
        self.assertIn('G1 Z0.1000', code)
        self.assertIn('G1 X15.0000 Z-2.8000', code)
        self.assertIn('G1 X20.0000 Z1.2000', code)
        # Every rapid X move is preceded by clearance above min(surface Z).
        lines = code.splitlines()
        for index, line in enumerate(lines):
            if line.startswith('G0 X'):
                self.assertEqual(lines[index-1], 'G0 Z-8.0000')

    def test_first_pass_starts_at_work_z_depth_without_sensor_baseline(self):
        points = [Sample(0, 1.0003, 0), Sample(1, 1.0338, 1), Sample(2, .95, 2)]
        options = dict(passes=1, total_depth=.01, max_depth=.5, feed=50,
                       rpm=500, surface_speed=100, max_rpm=1200, safe_z=5)
        code = generate_gcode(points, **options)
        self.assertIn('G1 Z0.0100', code)
        self.assertIn('G1 X1.0000 Z0.0435', code)
        self.assertIn('G1 X2.0000 Z-0.0403', code)
        shifted = [Sample(p.edge_mm, p.z_mm + 50, p.work_x_mm) for p in points]
        self.assertEqual(generate_gcode(shifted, **options), code)
        calibrated = generate_gcode(points, tool_z_offset=.2, sensor_z_offset=.1, **options)
        self.assertIn('G1 Z0.1100', calibrated)

    def test_work_x_survives_smoothing_csv_and_toolpath_offsets(self):
        points = smooth(simulated_scan_range(-12, 22, 2), 3, 3)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "work.csv"
            save_csv(path, points)
            loaded = load_csv(path)
            self.assertEqual(loaded[0].work_x_mm, -12)
            self.assertEqual(loaded[-1].work_x_mm, 22)
            options = dict(passes=1, total_depth=.1, max_depth=.5, feed=30,
                           rpm=500, surface_speed=100, max_rpm=1200, safe_z=5,
                           tool_x_offset=2, sensor_x_offset=1)
            code = generate_gcode(loaded, **options)
            self.assertIn("G0 X-11.0000", code)
            self.assertIn("G1 X23.0000", code)
            with self.assertRaises(ValueError):
                generate_gcode(loaded, use_css=True, **options)

    def test_scan_and_filter_keep_x_positions(self):
        raw = simulated_scan(100, 1)
        filtered = smooth(raw)
        self.assertEqual(len(raw), 101)
        self.assertEqual([p.edge_mm for p in raw], [p.edge_mm for p in filtered])

    def test_scan_range_starts_at_selected_work_x_but_csv_is_relative(self):
        points = simulated_scan_range(12, 22, 2, 20)
        self.assertEqual([p.edge_mm for p in points], [0, 2, 4, 6, 8, 10])
        reverse = simulated_scan_range(22, 12, 2, 20)
        self.assertEqual([p.work_x_mm for p in reverse], [22, 20, 18, 16, 14, 12])
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
