import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lathe_tools import LatheTool, LatheToolTable
from gcode_playback import parse_program
from profile import Sample, generate_gcode
from test_linuxcnc_control import make_backend


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tool.tbl'

    def table(self):
        table = LatheToolTable(self.path)
        table.tools[1].values.update(X=4., Z=-3., D=.8, I=105., J=165., Q=1.)
        table.save(list(table.tools.values()))
        return table

    def code(self, tool):
        return generate_gcode([Sample(0, 1, -20, 'spindle_center'), Sample(10, 1.2, -10, 'spindle_center')],
                              passes=1, total_depth=.01, max_depth=.1, feed=30, rpm=100,
                              surface_speed=100, max_rpm=200, safe_z=2, tool=tool)

    def test_roundtrip_and_other_tools_preserved_with_backup(self):
        original = '; keep\nT8 P8 X3 Z4 ;other tool\nT2 P2 X2 Z0 Q2 ;second\n'
        self.path.write_text(original)
        table = self.table()
        self.assertIn('T8 P8 X3 Z4 ;other tool', self.path.read_text())
        self.assertEqual(self.path.with_suffix('.tbl.bak').read_text(), original)
        self.assertEqual(table.tools[1].value('D'), .8)
        self.assertEqual(table.tools[2].comment, 'second')
        self.assertEqual(len(table.tools), 5)

    def test_conflict_and_invalid_data(self):
        table = self.table()
        self.path.write_text(self.path.read_text() + ';external\n')
        with self.assertRaisesRegex(ValueError, 'externally'):
            table.save(list(table.tools.values()))
        for values in [dict(X=float('nan')), dict(Q=1.5), dict(Q=10), dict(D=-1), dict(Y=1)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                LatheTool(1, values).validate()

    def test_offsets_not_baked_into_profile_and_parser_shifts_start(self):
        tool = self.table().tools[1]
        code = self.code(tool)
        self.assertIn('G43 H1', code)
        self.assertIn('G0 X-20.0000', code)
        moves = parse_program(code, start=(-20, 0), tools={1: tool}, require_preamble=True)
        self.assertEqual((moves[0].start_x, moves[0].start_z), (-24, 3))
        self.assertEqual((moves[0].tool_x, moves[0].tool_z), (4, -3))
        self.assertEqual(moves.tool_numbers, {1})
        with self.assertRaises(ValueError):
            parse_program(code, require_preamble=True)
        with self.assertRaises(ValueError):
            parse_program(code.replace('M5', 'G49\nM5'), tools={1: tool}, require_preamble=True)

    def backend(self):
        b, s, c = make_backend()
        b.ini_path = Path(self.temp.name) / 'machine.ini'
        b.ini.data['EMCIO', 'TOOL_TABLE'] = 'tool.tbl'
        s.homed = (1, 0, 1)
        s.tool_offset = (4, 0, -3)
        s.tool_in_spindle = 1
        b.x_center_reference = b.center_signature()
        return b, s, c

    def test_manual_selection_no_motion_and_busy_interlock(self):
        self.table()
        b, s, c = self.backend()
        b.select_tool(1)
        self.assertIn(('mdi', ('G21 G8 M61 Q1',)), c.calls)
        self.assertIn(('mdi', ('G43 H1',)), c.calls)
        self.assertFalse(any(n in ('auto', 'jog', 'home') for n, _ in c.calls))
        b.output_test_active = True
        before = list(c.calls)
        with self.assertRaises(RuntimeError):
            b.select_tool(2)
        self.assertEqual(before, c.calls)

    def test_run_checks_record_and_mounted_tool_and_compensated_limits(self):
        table = self.table()
        path = Path(self.temp.name) / 'test.ngc'
        path.write_text(self.code(table.tools[1]))
        b, s, c = self.backend()
        b.run_program(path)
        self.assertIn(('auto', (0, 0)), c.calls)
        self.assertIn(('load_tool_table', ()), c.calls)
        b.program_running = False
        c.calls.clear()
        s.tool_in_spindle = 2
        with self.assertRaisesRegex(RuntimeError, 'Mount and select'):
            b.run_program(path)
        self.assertEqual(c.calls, [])
        s.tool_in_spindle = 1
        table.tools[1].values['X'] = 150
        table.save(list(table.tools.values()))
        with self.assertRaisesRegex(RuntimeError, 'regenerate'):
            b.run_program(path)
        path.write_text(self.code(table.tools[1]))
        with self.assertRaisesRegex(RuntimeError, 'exceeds machine limits'):
            b.run_program(path)
        self.assertEqual(c.calls, [])

    def test_ui_save_selection_and_native_generation(self):
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from lathe_tools_ui import ToolsPanel
        app = QApplication.instance() or QApplication([])
        self.table()
        b, s, c = self.backend()
        selected = []
        panel = ToolsPanel(b, selected.append)
        self.addCleanup(panel.close)
        self.assertEqual(panel.table.rowCount(), 5)
        self.assertEqual(panel.table.item(0, 4).text(), '0.4')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            panel.use()
        self.assertEqual(panel.program_tool().number, 1)
        self.assertEqual(panel.shape.tool.value('Q'), 1)
        panel.table.item(0, 2).setText('5')
        with self.assertRaisesRegex(ValueError, 'changed'):
            panel.program_tool()
        panel.save()
        with self.assertRaisesRegex(ValueError, 'Select the mounted tool'):
            panel.program_tool()
        self.assertEqual(LatheToolTable(self.path).tools[1].value('X'), 5)
        panel.show()
        app.processEvents()

    def test_scan_start_limit_uses_active_tool_offset(self):
        self.table()
        b, s, c = self.backend()
        s.g5x_offset = (100, 0, 0)
        s.g92_offset = (0, 0, 0)
        b.x_center_reference = b.center_signature()
        b.move_to_scan_x(-20)
        self.assertEqual(b.positioning_target, 84)
        self.assertIn(('mdi', ('G21 G90 G54 G0 X-20.000000',)), c.calls)
        b.positioning = False
        c.calls.clear()
        with self.assertRaisesRegex(ValueError, 'outside machine limits'):
            b.move_to_scan_x(0)
        self.assertEqual(c.calls, [])

    def test_parser_requires_explicit_h_and_generator_rejects_double_offsets(self):
        tool = self.table().tools[1]
        with self.assertRaisesRegex(ValueError, 'explicit saved tool'):
            parse_program('G43\nG0 X1', tools={1: tool})
        with self.assertRaisesRegex(ValueError, 'legacy tool'):
            generate_gcode([Sample(0, 1, -20, 'spindle_center'), Sample(10, 1, -10, 'spindle_center')], passes=1, total_depth=.01,
                max_depth=.1, feed=30, rpm=100, surface_speed=100, max_rpm=200,
                safe_z=2, tool=tool, tool_x_offset=4)
