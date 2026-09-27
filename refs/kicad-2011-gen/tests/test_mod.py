"""Тесты kicadgen.mod (unittest, без внешних зависимостей).

Запуск: python3 -m unittest tests.test_mod -v   (из корня kicad-2011-gen)
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kicadgen.mod import (                                          # noqa: E402
    ModLibrary, Footprint, Pad, EdgeLine, EdgeArc, ModText,
    ModLoadError, write_modlib, read_modlib, pcb_to_mm, mm_to_pcb,
    dip, two_pad, pin_rows,
)
from kicadgen.gen_footprints import build_lab2_library                # noqa: E402

FIXED_DATE = 'Ср 02.09.26 19:52:23'


def _replace_line(text: str, startswith: str, new_line: str) -> str:
    """Заменяет первую строку, начинающуюся с ``startswith``, на ``new_line``."""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line.startswith(startswith):
            lines[i] = new_line
            return '\n'.join(lines)
    raise AssertionError('line %r not found in fixture text' % startswith)


def _drop_lines(text: str, *prefixes: str) -> str:
    lines = [l for l in text.split('\n') if not any(l.startswith(p) for p in prefixes)]
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------

class TestRoundTrip(unittest.TestCase):
    def test_lab2_library_roundtrip_identity(self):
        lib = build_lab2_library()
        text = write_modlib(lib, date=FIXED_DATE)
        reread = read_modlib(text)
        self.assertEqual([f.name for f in reread.footprints], ['dip14', 'mlt', 'snp8'])
        for orig, rt in zip(lib.footprints, reread.footprints):
            self.assertEqual(orig, rt, 'round-trip mismatch for %s' % orig.name)
        self.assertEqual(lib, reread)

    def test_write_read_write_is_stable(self):
        # Повторная запись перечитанной библиотеки даёт байт-в-байт тот же текст
        # (кроме даты) — подтверждает отсутствие скрытой мутации при чтении.
        lib = build_lab2_library()
        text1 = write_modlib(lib, date=FIXED_DATE)
        reread = read_modlib(text1)
        text2 = write_modlib(reread, date=FIXED_DATE)
        self.assertEqual(text1, text2)

    def test_header_and_index_and_terminator(self):
        lib = ModLibrary()
        lib.add(two_pad(name='mlt'))
        text = write_modlib(lib, date=FIXED_DATE)
        lines = text.split('\n')
        self.assertEqual(lines[0], 'PCBNEW-LibModule-V1  %s' % FIXED_DATE)
        self.assertIn('$INDEX', lines)
        self.assertIn('mlt', lines)
        self.assertIn('$EndINDEX', lines)
        self.assertTrue(text.rstrip('\n').endswith('$EndLIBRARY'))
        self.assertIn('$MODULE mlt', lines)
        self.assertIn('$EndMODULE  mlt', lines)   # два пробела — class_module.cpp:353

    def test_save_load_crlf(self):
        import tempfile
        lib = ModLibrary()
        lib.add(two_pad(name='mlt'))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'x.mod')
            from kicadgen.mod import save_modlib, load_modlib
            save_modlib(lib, path, date=FIXED_DATE, crlf=True)
            with open(path, 'rb') as fh:
                raw = fh.read()
            self.assertIn(b'\r\n', raw)
            self.assertEqual(raw.count(b'\n'), raw.count(b'\r\n'))   # каждый \n внутри \r\n
            reread = load_modlib(path)
            self.assertEqual(reread.footprints[0], lib.footprints[0])


# --------------------------------------------------------------------------
# Отказы строгого загрузчика
# --------------------------------------------------------------------------

class TestLoaderRejections(unittest.TestCase):
    def setUp(self):
        lib = ModLibrary()
        lib.add(two_pad(name='mlt'))
        self.valid_text = write_modlib(lib, date=FIXED_DATE)

    def test_bad_header_rejected(self):
        bad = 'NOT-A-KICAD-LIB\n' + '\n'.join(self.valid_text.split('\n')[1:])
        with self.assertRaises(ModLoadError) as ctx:
            read_modlib(bad)
        self.assertIn('not a valid Kicad PCB footprint library file', str(ctx.exception))

    def test_missing_endmodule_rejected(self):
        truncated = _drop_lines(self.valid_text, '$EndMODULE', '$EndLIBRARY')
        with self.assertRaises(ModLoadError) as ctx:
            read_modlib(truncated)
        self.assertIn('EndMODULE', str(ctx.exception))

    def test_malformed_pad_sh_line_rejected(self):
        # Sh-строка без кавычек вокруг имени площадки — структурно некорректна.
        broken = _replace_line(self.valid_text, 'Sh "1"', 'Sh 1 R 512 512 0 0 0')
        with self.assertRaises(ModLoadError) as ctx:
            read_modlib(broken)
        self.assertIn('quoted pad name', str(ctx.exception))

    def test_pad_sh_line_too_few_fields_rejected(self):
        broken = _replace_line(self.valid_text, 'Sh "1"', 'Sh "1" R 512 512')
        with self.assertRaises(ModLoadError):
            read_modlib(broken)

    def test_text_line_below_sscanf_minimum_rejected(self):
        # Т-строка (Ref/Val) обязана дать >= 10 успешных преобразований sscanf
        # (class_text_mod.cpp:116-124); у настоящего KiCad эта проверка ни на
        # что не влияет (мёртвый код — success инициализирован в true и не
        # сбрасывается в else), но по заданию мы применяем тот же порог как
        # настоящую валидацию.
        broken = _replace_line(self.valid_text, 'T0 ', 'T0 0 0 100 100')
        with self.assertRaises(ModLoadError) as ctx:
            read_modlib(broken)
        self.assertIn('10', str(ctx.exception))

    def test_unterminated_pad_block_rejected(self):
        lines = self.valid_text.split('\n')
        i = next(k for k, l in enumerate(lines) if l == '$EndPAD')
        del lines[i:]
        with self.assertRaises(ModLoadError):
            read_modlib('\n'.join(lines))

    def test_dp_polygon_edge_rejected(self):
        with_dp = _replace_line(self.valid_text, 'DS ', 'DP 0 0 0 0 4 120 21')
        with self.assertRaises(ModLoadError):
            read_modlib(with_dp)


# --------------------------------------------------------------------------
# Геометрия трёх посадочных мест (ТЗ §3.2)
# --------------------------------------------------------------------------

MM = 0.005   # допуск сравнения в мм (округление wxRound даёт ошибку << 1/10000")


class TestDip14Geometry(unittest.TestCase):
    def setUp(self):
        self.fp = dip(name='dip14')

    def test_pin_count_and_numbers(self):
        self.assertEqual(len(self.fp.pads), 14)
        self.assertEqual(sorted(p.number for p in self.fp.pads),
                          sorted(str(n) for n in range(1, 15)))

    def test_u_numbering_order(self):
        by_num = {p.number: p for p in self.fp.pads}
        left_x = pcb_to_mm(by_num['1'].x)
        right_x = pcb_to_mm(by_num['8'].x)
        self.assertLess(left_x, 0)
        self.assertGreater(right_x, 0)
        # 1..7 слева, сверху вниз
        ys_left = [pcb_to_mm(by_num[str(n)].y) for n in range(1, 8)]
        self.assertEqual(ys_left, sorted(ys_left))
        for n in range(1, 8):
            self.assertAlmostEqual(pcb_to_mm(by_num[str(n)].x), left_x, delta=MM)
        # 8..14 справа, снизу вверх (8 внизу, 14 вверху)
        ys_right = [pcb_to_mm(by_num[str(n)].y) for n in range(8, 15)]
        self.assertEqual(ys_right, sorted(ys_right, reverse=True))
        for n in range(8, 15):
            self.assertAlmostEqual(pcb_to_mm(by_num[str(n)].x), right_x, delta=MM)
        # 7 (низ левого ряда) и 8 (низ правого ряда) на одной высоте
        self.assertAlmostEqual(pcb_to_mm(by_num['7'].y), pcb_to_mm(by_num['8'].y), delta=MM)
        # 1 (верх левого) и 14 (верх правого) на одной высоте
        self.assertAlmostEqual(pcb_to_mm(by_num['1'].y), pcb_to_mm(by_num['14'].y), delta=MM)

    def test_pad1_is_square_rest_round(self):
        by_num = {p.number: p for p in self.fp.pads}
        self.assertEqual(by_num['1'].shape, 'R')
        for n in range(2, 15):
            self.assertEqual(by_num[str(n)].shape, 'C')

    def test_pitch_and_row_spacing_mm(self):
        by_num = {p.number: p for p in self.fp.pads}
        pitch = pcb_to_mm(by_num['2'].y) - pcb_to_mm(by_num['1'].y)
        self.assertAlmostEqual(pitch, 2.5, delta=MM)
        row_gap = pcb_to_mm(by_num['8'].x) - pcb_to_mm(by_num['1'].x)
        self.assertAlmostEqual(row_gap, 7.5, delta=MM)

    def test_all_pads_standard_through_hole(self):
        for p in self.fp.pads:
            self.assertEqual(p.attribute, 'STD')
            self.assertAlmostEqual(pcb_to_mm(p.drill), 0.8, delta=MM)
            self.assertAlmostEqual(pcb_to_mm(p.size_x), 1.3, delta=MM)

    def test_notch_arc_present(self):
        arcs = [d for d in self.fp.drawings if isinstance(d, EdgeArc)]
        self.assertEqual(len(arcs), 1)
        lines = [d for d in self.fp.drawings if isinstance(d, EdgeLine)]
        self.assertEqual(len(lines), 4)   # прямоугольник контура

    def test_reference_above_value_inside_vertical(self):
        self.assertEqual(self.fp.reference.kind, 0)
        self.assertEqual(self.fp.value.kind, 1)
        self.assertLess(pcb_to_mm(self.fp.reference.y), pcb_to_mm(self.fp.value.y))
        self.assertEqual(self.fp.value.orient, 900)   # вертикально


class TestMltGeometry(unittest.TestCase):
    def setUp(self):
        self.fp = two_pad(name='mlt')

    def test_two_pads_spacing_and_shapes(self):
        self.assertEqual(len(self.fp.pads), 2)
        by_num = {p.number: p for p in self.fp.pads}
        self.assertEqual(by_num['1'].shape, 'R')
        self.assertEqual(by_num['2'].shape, 'C')
        spacing = pcb_to_mm(by_num['2'].x) - pcb_to_mm(by_num['1'].x)
        self.assertAlmostEqual(spacing, 10.0, delta=MM)

    def test_ref_above_value_below(self):
        self.assertLess(pcb_to_mm(self.fp.reference.y), 0)
        self.assertGreater(pcb_to_mm(self.fp.value.y), 0)

    def test_lead_lines_present(self):
        lines = [d for d in self.fp.drawings if isinstance(d, EdgeLine)]
        # 4 стороны прямоугольника + 2 выводные линии
        self.assertEqual(len(lines), 6)


class TestSnp8Geometry(unittest.TestCase):
    def setUp(self):
        self.fp = pin_rows(name='snp8')

    def test_eight_signal_pads_plus_two_holes(self):
        signal = [p for p in self.fp.pads if p.number != '']
        holes = [p for p in self.fp.pads if p.number == '']
        self.assertEqual(len(signal), 8)
        self.assertEqual(len(holes), 2)

    def test_column_numbering_and_pitch(self):
        by_num = {p.number: p for p in self.fp.pads if p.number}
        left_x = pcb_to_mm(by_num['1'].x)
        right_x = pcb_to_mm(by_num['5'].x)
        self.assertLess(left_x, right_x)
        for n in range(1, 5):
            self.assertAlmostEqual(pcb_to_mm(by_num[str(n)].x), left_x, delta=MM)
        for n in range(5, 9):
            self.assertAlmostEqual(pcb_to_mm(by_num[str(n)].x), right_x, delta=MM)
        ys_left = [pcb_to_mm(by_num[str(n)].y) for n in range(1, 5)]
        self.assertEqual(ys_left, sorted(ys_left))
        pitch = ys_left[1] - ys_left[0]
        self.assertAlmostEqual(pitch, 2.5, delta=MM)
        row_gap = right_x - left_x
        self.assertAlmostEqual(row_gap, 5.0, delta=MM)

    def test_pad1_square(self):
        by_num = {p.number: p for p in self.fp.pads if p.number}
        self.assertEqual(by_num['1'].shape, 'R')
        for n in range(2, 9):
            self.assertEqual(by_num[str(n)].shape, 'C')

    def test_mounting_holes_non_electrical(self):
        holes = [p for p in self.fp.pads if p.number == '']
        self.assertEqual(len(holes), 2)
        for h in holes:
            self.assertEqual(h.attribute, 'HOLE')
            self.assertAlmostEqual(pcb_to_mm(h.size_x), 3.0, delta=MM)
            self.assertAlmostEqual(pcb_to_mm(h.drill), 3.0, delta=MM)
        ys = sorted(pcb_to_mm(h.y) for h in holes)
        body_h = 25.0
        self.assertAlmostEqual(ys[0], -(body_h / 2 - 2.5), delta=MM)
        self.assertAlmostEqual(ys[1], body_h / 2 - 2.5, delta=MM)
        # обе дырки на одной вертикальной оси
        xs = [pcb_to_mm(h.x) for h in holes]
        self.assertAlmostEqual(xs[0], xs[1], delta=MM)

    def test_ref_above_value_below(self):
        self.assertLess(pcb_to_mm(self.fp.reference.y), 0)
        self.assertGreater(pcb_to_mm(self.fp.value.y), 0)


# --------------------------------------------------------------------------
# mm_to_pcb — корректность округления (не накопительное умножение)
# --------------------------------------------------------------------------

class TestMmToPcb(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(mm_to_pcb(0.8), 315)
        self.assertEqual(mm_to_pcb(1.3), 512)
        self.assertEqual(mm_to_pcb(2.5), 984)
        self.assertEqual(mm_to_pcb(5.0), 1969)
        self.assertEqual(mm_to_pcb(7.5), 2953)
        self.assertEqual(mm_to_pcb(10.0), 3937)

    def test_rounding_is_per_value_not_cumulative(self):
        # mm_to_pcb(2*2.5) != 2*mm_to_pcb(2.5) — см. docstring mm_to_pcb.
        self.assertNotEqual(mm_to_pcb(5.0), 2 * mm_to_pcb(2.5))

    def test_negative_symmetry(self):
        self.assertEqual(mm_to_pcb(-2.5), -mm_to_pcb(2.5))


if __name__ == '__main__':
    unittest.main()
