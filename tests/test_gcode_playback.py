import unittest
from gcode_playback import Move, Playback, parse_program
from profile import Sample, generate_gcode


class PlaybackTests(unittest.TestCase):
    def test_generated_multiple_passes_include_clearance_and_return(self):
        code = generate_gcode([Sample(0, 1, 0), Sample(10, 1.2, 10)],
                              passes=2, total_depth=.02, max_depth=.1, feed=60, rpm=1000,
                              surface_speed=100, max_rpm=2000, safe_z=2)
        moves = parse_program(code)
        cuts = [m for m in moves if m.x == 0 and m.z > 0]
        self.assertEqual([m.z for m in cuts], [.01, .02])
        self.assertEqual(moves[-1].x, 0)
        self.assertLess(moves[-1].z, 0)
        playback = Playback(moves, (0, 0))
        playback.advance(100000)
        self.assertTrue(playback.done)
        self.assertEqual(playback.position, (moves[-1].x, moves[-1].z))

    def test_feed_time_and_zero_length_segments(self):
        playback = Playback([Move(0, 0, 60, 1), Move(3, 4, 60, 2),
                             Move(3, 6, 120, 3)], (0, 0))
        x, z = playback.advance(1)
        self.assertAlmostEqual(x, .6)
        self.assertAlmostEqual(z, .8)
        self.assertEqual(playback.advance(5), (3, 6))
        self.assertTrue(playback.done)

    def test_reject_unsupported_modal_and_table_commands(self):
        for code in ['G0 Y1', 'G91\nG0 X1', 'G96 S100\nG0 X1',
                     'G1 X1', 'F0\nG1 X1', 'M4\nG0 X1', 'G0 X1 bad']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                parse_program(code)

    def test_rapid_speed_is_axis_specific(self):
        moves = parse_program('G0 X3\nG0 Z4', rapid={'X': 60, 'Z': 120})
        self.assertEqual([m.speed for m in moves], [60, 120])
        playback = Playback(moves, (0, 0))
        self.assertEqual(playback.advance(3), (3, 0))
        self.assertEqual(playback.advance(2), (3, 4))
        self.assertTrue(playback.done)

    def test_comments_and_partial_axis_moves(self):
        moves = parse_program('(comment)\nF60\nG0 Z-1 ; rapid\nG1 X2', start=(1, 3))
        self.assertEqual([(m.x, m.z) for m in moves], [(1, -1), (2, -1)])
