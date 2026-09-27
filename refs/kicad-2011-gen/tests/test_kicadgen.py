"""Тесты kicadgen (unittest, без внешних зависимостей).

Запуск:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kicadgen import model as M                     # noqa: E402
from kicadgen import reader_lib, writer_lib          # noqa: E402
from kicadgen import reader_pro, writer_pro          # noqa: E402
from kicadgen import sch as S                        # noqa: E402
from kicadgen.sscanf import sscanf                   # noqa: E402
from kicadgen.textio import escaped, read_delimited, encode_lib_text, mm_to_mil  # noqa: E402

TESTING_DATA = os.path.join(os.path.dirname(ROOT), 'testing_data')


def _read(path: str) -> str:
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def _date_of(text: str) -> str:
    return text.splitlines()[0].split('Date: ', 1)[1].rstrip('\r')


# --- sscanf ---------------------------------------------------------------------

class TestSscanf(unittest.TestCase):
    def test_ints_and_strings(self):
        self.assertEqual(sscanf('1 2 abc', '%d %d %s'), ([1, 2, 'abc'], 3))
        self.assertEqual(sscanf('1 x', '%d %d'), ([1], 1))

    def test_c_does_not_skip_whitespace_without_format_space(self):
        self.assertEqual(sscanf('HV', '%c%c'), (['H', 'V'], 2))
        self.assertEqual(sscanf(' H V', ' %c %c'), (['H', 'V'], 2))

    def test_scanset(self):
        self.assertEqual(sscanf('1 "a b" x', '%d "%[^"]" %s'), ([1, 'a b', 'x'], 3))
        self.assertEqual(sscanf('1 ab x', '%d "%[^"]" %s')[1], 1)

    def test_hex(self):
        self.assertEqual(sscanf('1 1 4DBA0001', '%d %d %lX'), ([1, 1, 0x4DBA0001], 3))


# --- экранирование ----------------------------------------------------------------

class TestTextIO(unittest.TestCase):
    def test_escaped_roundtrip(self):
        for s in ['', 'abc', 'a b', 'q"q', 'back\\slash', 'x\\"y', 'юникод']:
            enc = escaped(s)
            dec, pos = read_delimited(enc)
            self.assertEqual(dec, s)
            self.assertEqual(pos, len(enc))

    def test_read_delimited_keeps_unknown_escapes(self):
        self.assertEqual(read_delimited('"a\\nb"')[0], 'a\\nb')

    def test_lib_text_encoding(self):
        self.assertEqual(encode_lib_text('Hello World'), 'Hello~World')
        self.assertEqual(encode_lib_text('say "hi"'), '"say \'\'hi\'\'"')
        self.assertEqual(encode_lib_text('a~b'), '"a~b"')

    def test_mm(self):
        self.assertEqual(mm_to_mil(5), 197)
        self.assertEqual(mm_to_mil(5, grid=50), 200)
        self.assertEqual(mm_to_mil(2), 79)


# --- round-trip на реальных файлах пользователя ------------------------------------

@unittest.skipUnless(os.path.isdir(TESTING_DATA), 'testing_data not available')
class TestRealFiles(unittest.TestCase):
    def test_lib_roundtrip_identical(self):
        src = _read(os.path.join(TESTING_DATA, '346_8.lib'))
        lib, w = reader_lib.read_library(src, strict=True)
        self.assertEqual(w, [])
        self.assertEqual([c.name for c in lib.components], ['K555TB6'])
        out = writer_lib.write_library(lib, date=_date_of(src))
        self.assertEqual(out, src.replace('\r\n', '\n'))

    def test_dcm_roundtrip_identical(self):
        src = _read(os.path.join(TESTING_DATA, '346_8.lib'))
        lib, _ = reader_lib.read_library(src)
        dsrc = _read(os.path.join(TESTING_DATA, '346_8.dcm'))
        reader_lib.read_doclib(dsrc, lib)
        self.assertEqual(writer_lib.write_doclib(lib, date=_date_of(dsrc)), dsrc.replace('\r\n', '\n'))

    def test_pro_roundtrip_identical(self):
        path = os.path.join(TESTING_DATA, '346_8.pro')
        cfg = reader_pro.read_project(path)
        ok, notes = reader_pro.check_project(cfg)
        self.assertTrue(ok, notes)
        # у студента проектная библиотека последней (диалог «Добавить»); наш генератор ставит её первой
        mine = writer_pro.write_project('346_8', date=cfg['']['update'], project_first=False)
        self.assertEqual(mine, _read(path).replace('\r\n', '\n'))


# --- модель / писатель / читатель библиотек ---------------------------------------

def _sample_component() -> M.Component:
    c = M.Component('DEMO', 'U', unit_count=2)
    c.fields.append(M.Field(M.REFERENCE, 'U', 0, 400))
    c.fields.append(M.Field(M.VALUE, 'DEMO', 0, -400, visible=False))
    c.fields.append(M.Field(M.FOOTPRINT, 'DIP8', 0, -500, visible=False))
    c.fields.append(M.Field(4, 'custom value', 0, -600, name='MyField', italic=True, bold=True,
                            hjust=M.HJust.LEFT, vjust=M.VJust.TOP))
    c.aliases = ['DEMO2', 'demo3']
    c.fplist = ['DIP*', 'SO8']
    c.description = 'Демо компонент'
    c.keywords = 'demo test'
    c.docfile = 'demo.pdf'
    c.items += [
        M.Rect(0, 1, -300, 300, 300, -300, 0, M.Fill.BACKGROUND),
        M.Circle(0, 1, 0, 0, 100, 10, M.Fill.NONE),
        M.Arc(0, 1, 0, 0, 200, 0, 900, 0, M.Fill.NONE),
        M.Arc(0, 2, 0, 0, 200, 2700, 900, 0, M.Fill.FOREGROUND),
        M.Polyline(0, 1, [(-100, -100), (100, 100), (100, -100)], 0, M.Fill.NONE),
        M.Bezier(0, 1, [(0, 0), (50, 100), (100, 0)], 0, M.Fill.NONE),
        M.Text(0, 1, 'Hello World', 0, 200, 60),
        M.Text(0, 1, 'quoted "x" ~y', 0, -200, 60, italic=True, bold=True),
        M.Pin(1, 1, 'IN', '1', -500, 100, 200, M.PinOrient.RIGHT, 50, 50, M.PinType.INPUT),
        M.Pin(1, 1, '~CLK', '2', -500, -100, 200, M.PinOrient.RIGHT, 50, 50, M.PinType.INPUT,
              M.PinShape.CLOCK | M.PinShape.INVERT),
        M.Pin(1, 1, 'OUT', '3', 500, 0, 200, M.PinOrient.LEFT, 50, 50, M.PinType.OUTPUT, M.PinShape.LOWLEVEL_OUT),
        M.Pin(2, 1, 'IN', '4', -500, 100, 200, M.PinOrient.RIGHT, 50, 50, M.PinType.INPUT),
        M.Pin(2, 1, 'OUT', '5', 500, 0, 200, M.PinOrient.LEFT, 50, 50, M.PinType.OUTPUT),
        M.Pin(0, 1, 'VCC', '8', 0, 500, 200, M.PinOrient.DOWN, 50, 50, M.PinType.POWER_IN, visible=False),
        M.Pin(0, 1, 'GND', '7', 0, -500, 200, M.PinOrient.UP, 50, 50, M.PinType.POWER_IN, visible=False),
        M.Pin(1, 2, 'NC', '6', 500, 200, 200, M.PinOrient.LEFT, 50, 50, M.PinType.NC, M.PinShape.NONLOGIC),
    ]
    return c


class TestLibraryRoundTrip(unittest.TestCase):
    def test_roundtrip(self):
        lib = M.Library([_sample_component()])
        text = writer_lib.write_library(lib, date='D')
        lib2, w = reader_lib.read_library(text, strict=True)
        self.assertEqual(w, [])
        text2 = writer_lib.write_library(lib2, date='D')
        self.assertEqual(text, text2)
        c = lib2.components[0]
        self.assertEqual(c.aliases, ['DEMO2', 'demo3'])
        self.assertEqual(c.fplist, ['DIP*', 'SO8'])
        self.assertFalse(c.value_visible)
        pins = {p.number: p for p in c.pins()}
        self.assertEqual(pins['2'].shape, M.PinShape.CLOCK | M.PinShape.INVERT)
        self.assertFalse(pins['8'].visible)
        self.assertIs(pins['8'].etype, M.PinType.POWER_IN)
        texts = [t.text for t in c.items if isinstance(t, M.Text)]
        self.assertIn('Hello World', texts)
        self.assertIn('quoted "x" ~y', texts)
        f4 = c.get_field(4)
        self.assertEqual((f4.name, f4.italic, f4.bold, f4.hjust, f4.vjust),
                         ('MyField', True, True, M.HJust.LEFT, M.VJust.TOP))

    def test_doc_roundtrip(self):
        lib = M.Library([_sample_component()])
        lib.components[0].alias_docs['DEMO2'] = ('alias desc', 'kw', '')
        text = writer_lib.write_doclib(lib, date='D')
        lib2, _ = reader_lib.read_library(writer_lib.write_library(lib, date='D'))
        reader_lib.read_doclib(text, lib2)
        c = lib2.components[0]
        self.assertEqual((c.description, c.keywords, c.docfile), ('Демо компонент', 'demo test', 'demo.pdf'))
        self.assertEqual(c.alias_docs['DEMO2'], ('alias desc', 'kw', ''))
        self.assertEqual(writer_lib.write_doclib(lib2, date='D'), text)

    def test_sort_order_matches_kicad(self):
        # порядок выводов из файла студента: unit 0 первым, потом по упакованному номеру
        nums = ['13', '1', '14', '2', '12', '7']
        c = M.Component('X', 'U')
        for n in nums:
            c.items.append(M.Pin(1, 1, 'p', n, 0, 0, 100, M.PinOrient.RIGHT, 50, 50, M.PinType.INPUT))
        text = writer_lib.write_library(M.Library([c]), date='D')
        order = [l.split()[2] for l in text.splitlines() if l.startswith('X ')]
        self.assertEqual(order, ['1', '2', '7', '12', '13', '14'])

    def test_arc_angle_normalisation(self):
        a = M.Arc(0, 1, 0, 0, 100, 2700, 900)
        line = writer_lib.format_item(a)
        self.assertTrue(line.startswith('A 0 0 100 -900 900 '), line)


class TestValidation(unittest.TestCase):
    def test_pin_number_too_long(self):
        p = M.Pin(1, 1, 'A', '12345', 0, 0)
        self.assertRaises(M.ValidationError, p.validate)

    def test_spaces_forbidden(self):
        self.assertRaises(M.ValidationError, M.Pin(1, 1, 'A B', '1', 0, 0).validate)
        self.assertRaises(M.ValidationError, M.Component('A B', 'U').validate)

    def test_duplicate_pin(self):
        c = M.Component('X', 'U')
        c.items += [M.Pin(1, 1, 'a', '1', 0, 0), M.Pin(1, 1, 'b', '1', 0, 100)]
        self.assertRaises(M.ValidationError, c.validate)

    def test_unit_out_of_range(self):
        c = M.Component('X', 'U', unit_count=1)
        c.items.append(M.Pin(2, 1, 'a', '1', 0, 0))
        self.assertRaises(M.ValidationError, c.validate)


class TestReaderRejectsLikeKiCad(unittest.TestCase):
    HEAD = 'EESchema-LIBRARY Version 2.3  Date: x\n'

    def _comp(self, body: str) -> str:
        return self.HEAD + 'DEF X U 0 40 Y Y 1 F N\nF0 "U" 0 0 60 H V C CNN\nF1 "X" 0 0 60 H V C CNN\n' + body + 'ENDDEF\n'

    def test_bad_header(self):
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library, 'nonsense\nDEF X U 0 40 Y Y 1 F N\n')
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library, 'EESchema-LIBRARY version 2.3\n')

    def test_ti_line_is_fatal(self):
        text = self.HEAD + 'DEF X U 0 40 Y Y 1 F N\nTi 2011/4/29 1:2:3\nENDDEF\n'
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library, text)
        lib, w = reader_lib.read_library(text, strict=False)
        self.assertEqual(lib.components, [])
        self.assertTrue(any('Ti' in x for x in w))

    def test_field_six_tokens_fatal(self):
        text = self.HEAD + 'DEF X U 0 40 Y Y 1 F N\nF0 "U" 0 0 60 H V C\nENDDEF\n'
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library, text)

    def test_field_five_tokens_ok(self):
        text = self.HEAD + 'DEF X U 0 40 Y Y 1 F N\nF0 "U" 0 0 60 H V\nENDDEF\n'
        lib, _ = reader_lib.read_library(text)
        self.assertEqual(lib.components[0].get_field(0).hjust, M.HJust.CENTER)

    def test_unknown_pin_type(self):
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library,
                          self._comp('DRAW\nX A 1 0 0 100 R 50 50 1 1 Z\nENDDRAW\n'))

    def test_pin_with_11_tokens_ok(self):
        lib, _ = reader_lib.read_library(self._comp('DRAW\nX A 1 0 0 100 R 50 50 1 1 I\nENDDRAW\n'))
        self.assertEqual(len(lib.components[0].pins()), 1)

    def test_undefined_draw_command(self):
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library,
                          self._comp('DRAW\nF0 "x" 0 0 60 H V C CNN\nENDDRAW\n'))

    def test_missing_fill_warns(self):
        lib, w = reader_lib.read_library(self._comp('DRAW\nC 0 0 100 0 1 0\nENDDRAW\n'))
        self.assertTrue(any('uninitialised' in x for x in w))

    def test_bezier_missing_points(self):
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_library,
                          self._comp('DRAW\nB 3 0 1 0 0 0 10 10\nENDDRAW\n'))

    def test_def_name_uppercased_and_case_insensitive_lookup(self):
        lib, w = reader_lib.read_library(self.HEAD + 'DEF abc U 0 40 Y Y 1 F N\nENDDEF\n')
        self.assertEqual(lib.components[0].name, 'ABC')
        self.assertIsNotNone(lib.find('Abc'))

    def test_missing_enddef_at_eof_accepted(self):
        lib, w = reader_lib.read_library(self.HEAD + 'DEF X U 0 40 Y Y 1 F N\n')
        self.assertEqual(len(lib.components), 1)

    def test_comments_anywhere(self):
        lib, _ = reader_lib.read_library(self._comp('# c\nDRAW\n# c\nX A 1 0 0 100 R 50 50 1 1 I\n# c\nENDDRAW\n'))
        self.assertEqual(len(lib.components[0].pins()), 1)

    def test_dcm_requires_cmp(self):
        lib = M.Library([M.Component('X', 'U')])
        self.assertRaises(reader_lib.LibLoadError, reader_lib.read_doclib,
                          'EESchema-DOCLIB  Version 2.0\nD oops\n', lib)


# --- .pro ------------------------------------------------------------------------------

class TestProject(unittest.TestCase):
    def test_version_required(self):
        cfg = reader_pro.parse_project('[eeschema]\nLibDir=\n[eeschema/libraries]\nLibName1=a\n')
        ok, notes = reader_pro.check_project(cfg)
        self.assertFalse(ok)

    def test_gap_in_libnames(self):
        cfg = reader_pro.parse_project('[eeschema]\nversion=1\n[eeschema/libraries]\nLibName1=a\nLibName3=c\n')
        self.assertEqual(reader_pro.eeschema_libraries(cfg), ['a'])

    def test_generated_project_valid(self):
        cfg = reader_pro.parse_project(writer_pro.write_project('proj', extra_libs=['mylib'], date='D'))
        ok, notes = reader_pro.check_project(cfg)
        self.assertTrue(ok, notes)
        libs = reader_pro.eeschema_libraries(cfg)
        self.assertEqual(libs[:3], ['mylib', 'proj', 'power'])   # проектные библиотеки первыми (см. writer_pro)
        self.assertEqual(cfg['general']['version'], '1')


# --- .sch ---------------------------------------------------------------------------------

class TestOrientation(unittest.TestCase):
    def test_matrices(self):
        O = S.Orientation
        self.assertEqual(O.matrix('0'), (1, 0, 0, -1))
        self.assertEqual(O.matrix('90'), (0, 1, 1, 0))
        self.assertEqual(O.matrix('180'), (-1, 0, 0, 1))
        self.assertEqual(O.matrix('270'), (0, -1, -1, 0))
        self.assertEqual(O.matrix('0MX'), (1, 0, 0, 1))
        self.assertEqual(O.matrix('0MY'), (-1, 0, 0, -1))
        # GetOrientation возвращает первое совпадение: 180+MY == 0+MX
        self.assertEqual(O.name(O.matrix('180MY')), '0MX')

    def test_pin_position(self):
        pin = M.Pin(1, 1, 'a', '1', -300, 100, 200, M.PinOrient.RIGHT)
        c = S.SchComponent('X', 'U1', 1000, 2000, orientation='0')
        self.assertEqual(c.pin_position(pin), (700, 1900))
        c.orientation = '90'
        self.assertEqual(c.pin_position(pin), (1100, 1700))


def _sample_schematic() -> S.Schematic:
    sch = S.Schematic(libs=['power', 'demo'], title='Тест "кавычки"', date='2011')
    comp = S.SchComponent('DEMO', 'U1', 1000, 1000, unit=2, orientation='90MX', timestamp=0x4DBA0001)
    comp.fields = [S.SchField(0, 'U1', 1000, 900), S.SchField(1, 'DEMO', 1000, 1100, hidden=True),
                   S.SchField(4, 'x y', 1000, 1200, name='Note', italic=True, bold=True,
                              hjust=M.HJust.LEFT, vjust=M.VJust.BOTTOM)]
    pwr = S.SchComponent('GND', '#PWR01', 500, 500, timestamp=0x4DBA0002)
    sheet = S.Sheet(3000, 3000, 1000, 800, 'sub', 'sub.sch', 0x4DBA0003,
                    pins=[S.SheetPin('IN', 3000, 3100, 'Input', 'L'), S.SheetPin('OUT', 4000, 3200, 'Output', 'R')])
    sch.items += [comp, pwr,
                  S.Wire(0, 0, 100, 0), S.Bus(200, 0, 200, 500), S.Wire(0, 100, 100, 100, 'Notes'),
                  S.BusEntry(200, 100, 100, 100), S.BusEntry(200, 200, 100, 100, bus=True),
                  S.Junction(100, 0), S.NoConnect(300, 300),
                  S.Label(100, 0, 'NET1', 0), S.GlobalLabel(100, 100, 'VCC', 2, shape='BiDi', italic=True, bold=True),
                  S.HierLabel(100, 200, 'H1', 1, shape='3State'),
                  S.Note(500, 500, 'line one\nline two', 0, 60),
                  sheet]
    return sch


class TestSchematicRoundTrip(unittest.TestCase):
    def test_roundtrip(self):
        sch = _sample_schematic()
        text = S.write_schematic(sch, date='D')
        sch2, w = S.read_schematic(text)
        self.assertEqual(w, [])
        text2 = S.write_schematic(sch2, date='D')
        self.assertEqual(text, text2)
        comp = sch2.components()[0]
        self.assertEqual((comp.reference, comp.unit, comp.orientation, comp.timestamp), ('U1', 2, '90MX', 0x4DBA0001))
        f4 = comp.field(4)
        self.assertEqual((f4.name, f4.text, f4.italic, f4.bold, f4.hjust), ('Note', 'x y', True, True, M.HJust.LEFT))
        self.assertTrue(sch2.components()[1].field(0).hidden)   # #PWR -> невидимая ссылка
        notes = [i for i in sch2.items if isinstance(i, S.Note)]
        self.assertEqual(notes[0].text, 'line one\nline two')
        sheets = [i for i in sch2.items if isinstance(i, S.Sheet)]
        self.assertEqual([p.name for p in sheets[0].pins], ['IN', 'OUT'])
        self.assertEqual(sch2.title, 'Тест "кавычки"')

    def test_rejections(self):
        base = S.write_schematic(_sample_schematic(), date='D')
        self.assertRaises(S.SchLoadError, S.read_schematic, base.replace('LIBS:power', 'LIB:power', 1))
        self.assertRaises(S.SchLoadError, S.read_schematic, base.replace('$EndDescr\n', '$EndDescr\n\n', 1))
        self.assertRaises(S.SchLoadError, S.read_schematic, base.replace('EELAYER END\n', '', 1))
        self.assertRaises(S.SchLoadError, S.read_schematic, base.replace('$EndComp', '$Foo', 1).replace('$Foo', 'Foo'))

    def test_empty_label_forbidden(self):
        sch = S.Schematic(items=[S.Label(0, 0, '')])
        self.assertRaises(M.ValidationError, S.write_schematic, sch)


# --- spec -> файлы ------------------------------------------------------------------------------

class TestSpecExample(unittest.TestCase):
    def test_346_8_generates_and_validates(self):
        import tempfile
        from kicadgen.spec import load_spec, generate
        spec = load_spec(os.path.join(ROOT, 'examples', '346_8.yaml'))
        with tempfile.TemporaryDirectory() as tmp:
            files = generate(spec, tmp, date='D')
            names = sorted(os.path.basename(f) for f in files)
            self.assertEqual(names, ['346_8-cache.lib', '346_8.net', '346_8.pro', '346_8.sch', 'My_lib.dcm', 'My_lib.lib', 'My_lib.mod'])
            lib, w = reader_lib.load_library(os.path.join(tmp, 'My_lib.lib'))
            self.assertEqual(w, [])
            k = lib.find('K555TB6')
            self.assertEqual(k.unit_count, 2)
            self.assertFalse(k.value_visible)
            nums = sorted(p.number for p in k.pins(2, 1))
            self.assertEqual(nums, ['10', '11', '14', '5', '6', '7', '8', '9'])
            pwr = [p for p in k.pins() if p.unit == 0]
            self.assertTrue(all(p.etype is M.PinType.POWER_IN and not p.visible for p in pwr))
            sch, w = S.load_schematic(os.path.join(tmp, '346_8.sch'))
            self.assertEqual(w, [])
            self.assertEqual(len(sch.components()), 7)
            with io.open(os.path.join(tmp, 'My_lib.lib'), 'rb') as fh:
                self.assertIn(b'\r\n', fh.read())


if __name__ == '__main__':
    unittest.main()
