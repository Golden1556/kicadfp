"""Тесты kicadfp.legacy — чтение библиотек PCBNEW-LibModule-V1 (.mod) как KiCad 9.

Эталон — ``docs/dev/legacy-mod.md`` §17 (фикстура ``tests/fixtures/legacy_mod/My_lib.mod``)
и вывод ``kicad-cli fp upgrade`` 9.0.1 (тесты с маркером ``kicad_cli``).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from kicadfp import geometry, legacy, load, loads, sexpr
from kicadfp.format_rules import DEFAULT_VERSION
from kicadfp.io import LegacyLibraryError
from kicadfp.legacy import LegacyFormatError, LegacyIssue
from kicadfp.model import Arc, Circle, Footprint, Line, Poly

HEADER = "PCBNEW-LibModule-V1  Ср 02.09.26 19:52:23\n# encoding utf-8\n"
_UUID_RE = re.compile(r'\(uuid "[0-9a-f-]+"\)')


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------

def lib(*modules: str, units_mm: bool = False, index: bool = True) -> str:
    """Текст библиотеки из блоков модулей (LF)."""
    head = HEADER + ("Units mm\n" if units_mm else "")
    if index:
        head += "$INDEX\n$EndINDEX\n"
    return head + "".join(modules) + "$EndLIBRARY\n"


def module(name: str, *lines: str, po: str = "Po 0 0 0 15 00000000 00000000 ~~") -> str:
    """Блок ``$MODULE``: строка ``Po`` (если не пустая) и переданные строки."""
    body = ([po] if po else []) + list(lines)
    return f"$MODULE {name}\n" + "".join(x + "\n" for x in body) + f"$EndMODULE {name}\n"


def pad_block(*lines: str) -> tuple[str, ...]:
    return ("$PAD",) + lines + ("$EndPAD",)


def one(text: str, **kw) -> Footprint:
    fps = legacy.loads_library(text, **kw)
    assert len(fps) == 1
    return fps[0]


def norm(text: str) -> str:
    """Текст корпуса без значений uuid и без generator/generator_version."""
    text = _UUID_RE.sub('(uuid "…")', text)
    text = re.sub(r'\(generator "[^"]*"\)', '(generator "G")', text)
    return re.sub(r'\(generator_version "[^"]*"\)', '(generator_version "V")', text)


def nodes(fp: Footprint, name: str) -> list[sexpr.Node]:
    return fp.node.nodes(name)


def compact(node: sexpr.Node) -> str:
    return _UUID_RE.sub("", sexpr.to_compact(node))


def pad_rows(fp: Footprint) -> list[tuple]:
    rows = []
    for p in fp.pads:
        d = p.drill
        rows.append((p.number, p.type, p.shape, sexpr.format_number(p.x),
                     sexpr.format_number(p.y), sexpr.format_number(p.size_x),
                     sexpr.format_number(p.size_y),
                     None if d is None else sexpr.format_number(d.diameter), p.layers))
    return rows


# ---------------------------------------------------------------------------
# Фикстура My_lib.mod (legacy-mod.md §17)
# ---------------------------------------------------------------------------

MLT_EXPECTED = """(footprint "mlt"
	(version 20241229)
	(generator "G")
	(generator_version "V")
	(layer "F.Cu")
	(descr "Корпус резистора МЛТ")
	(tags "mlt resistor")
	(property "Reference" "REF**"
		(at 0 -2.49936 0)
		(layer "F.SilkS")
		(uuid "…")
		(effects
			(font
				(size 1.00076 1.00076)
				(thickness 0.14986)
			)
		)
	)
	(property "Value" "VAL**"
		(at 0 2.49936 0)
		(layer "F.SilkS")
		(uuid "…")
		(effects
			(font
				(size 1.00076 1.00076)
				(thickness 0.14986)
			)
		)
	)
	(property "Datasheet" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "…")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(property "Description" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "…")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
""" + "".join(f"""	(fp_line
		(start {s})
		(end {e})
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
""" for s, e in [("-5.00126 0", "-3.74904 0"), ("-3.74904 -1.24968", "3.74904 -1.24968"),
                 ("-3.74904 1.24968", "-3.74904 -1.24968"), ("3.74904 -1.24968", "3.74904 1.24968"),
                 ("3.74904 0", "5.00126 0"), ("3.74904 1.24968", "-3.74904 1.24968")]) + """	(pad "1" thru_hole rect
		(at -5.00126 0)
		(size 1.30048 1.30048)
		(drill 0.8001)
		(layers "*.Cu" "*.Mask" "F.SilkS")
		(remove_unused_layers no)
		(thermal_bridge_angle 45)
		(uuid "…")
	)
	(pad "2" thru_hole circle
		(at 5.00126 0)
		(size 1.30048 1.30048)
		(drill 0.8001)
		(layers "*.Cu" "*.Mask" "F.SilkS")
		(remove_unused_layers no)
		(uuid "…")
	)
	(embedded_fonts no)
)
"""

TH = ("*.Cu", "*.Mask", "F.SilkS")


@pytest.fixture(scope="module")
def my_lib() -> list[Footprint]:
    return legacy.read_library(Path(__file__).parent / "fixtures" / "legacy_mod" / "My_lib.mod")


def test_fixture_modules(my_lib):
    assert [fp.name for fp in my_lib] == ["dip14", "mlt", "snp8"]
    for fp in my_lib:
        assert fp.version == DEFAULT_VERSION
        assert fp.generator == "kicadfp"
        assert fp.layer == "F.Cu"
        assert fp.node.find("attr") is None
        assert not fp.locked and not fp.placed
        assert fp.node.find("embedded_fonts") is not None
        assert not fp.models


def test_fixture_new_unique_uuids(my_lib):
    ids = [m.group(0) for fp in my_lib for m in _UUID_RE.finditer(fp.dumps())]
    assert len(ids) == 3 * 4 + 26 + 15      # поля, площадки, фигуры
    assert len(set(ids)) == len(ids)
    again = legacy.read_library(Path(__file__).parent / "fixtures" / "legacy_mod" / "My_lib.mod")
    ids2 = {m.group(0) for fp in again for m in _UUID_RE.finditer(fp.dumps())}
    assert not ids2 & set(ids)


def test_fixture_dip14(my_lib):
    fp = my_lib[0]
    assert fp.descr == "Корпус К555ТВ6 DIP14"
    assert fp.tags == "dip14 K555TB6"
    ys = ["-7.50062", "-5.00126", "-2.49936", "0", "2.49936", "5.00126", "7.50062"]
    expected = []
    for k, y in enumerate(ys, start=1):
        expected.append((str(k), "thru_hole", "rect" if k == 1 else "circle", "-3.74904", y,
                         "1.30048", "1.30048", "0.8001", list(TH)))
    for k, y in enumerate(reversed(ys), start=8):
        expected.append((str(k), "thru_hole", "circle", "3.74904", y, "1.30048", "1.30048",
                         "0.8001", list(TH)))
    assert pad_rows(fp) == expected
    # тексты: Reference, Value, Datasheet, Description (legacy-mod.md §17)
    texts = [(t.name, t.text, sexpr.format_number(t.x), sexpr.format_number(t.y), t.angle,
              t.font_size_y, t.font_size_x, t.thickness, t.layer, t.hide) for t in fp.texts]
    assert texts == [
        ("Reference", "REF**", "0", "-9.99998", 0.0, 1.00076, 1.00076, 0.14986, "F.SilkS", False),
        ("Value", "VAL**", "0", "0", 90.0, 1.00076, 1.00076, 0.14986, "F.SilkS", False),
        ("Datasheet", "", "0", "0", 0.0, 1.27, 1.27, 0.15, "F.Fab", True),
        ("Description", "", "0", "0", 0.0, 1.27, 1.27, 0.15, "F.Fab", True),
    ]
    g = fp.graphics
    assert [type(x) for x in g] == [Line, Line, Line, Line, Arc]
    assert [(x.start, x.end) for x in g[:4]] == [
        ((-2.49936, -8.7503), (2.49936, -8.7503)), ((-2.49936, 8.7503), (-2.49936, -8.7503)),
        ((2.49936, -8.7503), (2.49936, 8.7503)), ((2.49936, 8.7503), (-2.49936, 8.7503))]
    arc = g[4]
    # DA 0 -3445 295 -3445 -1800: угол < 0 — начало и конец переставлены
    assert (arc.start, arc.mid, arc.end) == ((-0.7493, -8.7503), (0.0, -9.4996), (0.7493, -8.7503))
    assert all(x.width == 0.14986 and x.layer == "F.SilkS" for x in g)


def test_fixture_mlt_exact_text(my_lib):
    assert norm(my_lib[1].dumps()) == MLT_EXPECTED


def test_fixture_snp8(my_lib):
    fp = my_lib[2]
    assert fp.descr == "Корпус разъёма СНП 8 контактов с двумя монтажными отверстиями 3 мм"
    assert fp.tags == "snp8 connector"
    rows = pad_rows(fp)
    hole = ["*.Mask", "B.Cu", "F.SilkS"]
    assert rows[:2] == [
        ("", "np_thru_hole", "circle", "8.7503", "-9.99998", "2.99974", "2.99974", "2.99974", hole),
        ("", "np_thru_hole", "circle", "8.7503", "9.99998", "2.99974", "2.99974", "2.99974", hole)]
    assert [r[:5] for r in rows[2:]] == [
        ("1", "thru_hole", "rect", "-2.49936", "-3.74904"),
        ("2", "thru_hole", "circle", "-2.49936", "-1.24968"),
        ("3", "thru_hole", "circle", "-2.49936", "1.24968"),
        ("4", "thru_hole", "circle", "-2.49936", "3.74904"),
        ("5", "thru_hole", "circle", "2.49936", "-3.74904"),
        ("6", "thru_hole", "circle", "2.49936", "-1.24968"),
        ("7", "thru_hole", "circle", "2.49936", "1.24968"),
        ("8", "thru_hole", "circle", "2.49936", "3.74904")]
    npth = fp.pads[0]
    assert npth.remove_unused_layers is None
    assert fp.pads[2].remove_unused_layers is False
    ref, val = fp.reference, fp.value
    assert (ref.x, ref.y, val.x, val.y) == (8.7503, -13.74902, 8.7503, 13.74902)
    assert [(x.start, x.end) for x in fp.graphics] == [
        ((2.49936, -12.49934), (15.00124, -12.49934)), ((2.49936, 12.49934), (2.49936, -12.49934)),
        ((15.00124, -12.49934), (15.00124, 12.49934)), ((15.00124, 12.49934), (2.49936, 12.49934))]


def test_fixture_line_counts(my_lib):
    # legacy-mod.md §17 даёт 218/131/173; kicad-cli 9.0.1 пишет ещё
    # (thermal_bridge_angle 45) у прямоугольной площадки 1 — на строку больше
    counts = [len(fp.dumps().splitlines()) for fp in my_lib]
    assert counts == [219, 132, 174]


def test_crlf_equals_lf(legacy_mod):
    data = legacy_mod.read_bytes()
    assert data.count(b"\r\n") == 238
    a = [norm(fp.dumps()) for fp in legacy.loads_library(data)]
    b = [norm(fp.dumps()) for fp in legacy.loads_library(data.replace(b"\r\n", b"\n"))]
    c = [norm(fp.dumps()) for fp in legacy.loads_library(data.decode("utf-8"))]
    assert a == b == c


def test_convert_fixture(legacy_mod, tmp_path):
    out = tmp_path / "My_lib.pretty"
    paths = legacy.convert(legacy_mod, out)
    assert [p.name for p in paths] == ["dip14.kicad_mod", "mlt.kicad_mod", "snp8.kicad_mod"]
    assert sorted(p.name for p in out.iterdir()) == [p.name for p in paths]
    for p in paths:
        text = p.read_text(encoding="utf-8")
        assert text.endswith(")\n") and "\r" not in text and "\t(" in text
        fp = load(p)
        assert fp.name == p.stem
        # round-trip: неизменённый корпус пишется байт в байт, дерево — то же
        assert fp.dumps() == text
        tree = sexpr.parse(text)
        assert sexpr.equal(tree, sexpr.parse(sexpr.dumps(tree)))
    assert norm(paths[1].read_text(encoding="utf-8")) == MLT_EXPECTED


def test_convert_creates_nested_dir_and_overwrites(legacy_mod, tmp_path):
    out = tmp_path / "a" / "b.pretty"
    legacy.convert(legacy_mod, out)
    (out / "mlt.kicad_mod").write_text("garbage", encoding="utf-8")
    legacy.convert(legacy_mod, out)
    assert load(out / "mlt.kicad_mod").name == "mlt"


def test_convert_error_writes_nothing(tmp_path):
    src = tmp_path / "bad.mod"
    src.write_text(lib(module("ok"), "$MODULE broken\nPo 0 0 0 15 0 0 ~~\n"), encoding="utf-8")
    out = tmp_path / "out.pretty"
    with pytest.raises(LegacyFormatError) as ei:
        legacy.convert(src, out)
    assert ei.value.path == str(src)
    assert not out.exists()


# ---------------------------------------------------------------------------
# kicad-cli (эталон — конвертер KiCad 9)
# ---------------------------------------------------------------------------

def _kicad_convert(cli: str, src: Path, out: Path) -> dict[str, str]:
    r = subprocess.run([cli, "fp", "upgrade", str(src), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(out.glob("*.kicad_mod"))}


@pytest.mark.kicad_cli
def test_kicad_cli_reads_converted(kicad_cli, legacy_mod, tmp_path):
    out = tmp_path / "My_lib.pretty"
    legacy.convert(legacy_mod, out)
    again = tmp_path / "again.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", "--force", str(out), "-o", str(again)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "Unable" not in r.stdout + r.stderr
    assert sorted(p.name for p in again.glob("*.kicad_mod")) == \
        ["dip14.kicad_mod", "mlt.kicad_mod", "snp8.kicad_mod"]


@pytest.mark.kicad_cli
def test_kicad_cli_same_as_kicad_converter(kicad_cli, legacy_mod, tmp_path):
    """Вывод kicadfp совпадает с конвертером KiCad 9 (кроме uuid и generator)."""
    ref = _kicad_convert(kicad_cli, legacy_mod, tmp_path / "kicad.pretty")
    mine = {p.name: p.read_text(encoding="utf-8")
            for p in legacy.convert(legacy_mod, tmp_path / "mine.pretty")}
    assert set(ref) == set(mine)
    for name in ref:
        assert norm(mine[name]) == norm(ref[name]), name


SYNTH_FOR_CLI = lib(
    module("TST1",
           "Cd Descr with \\\"quotes\\\" and \\\\ back", "Kw kw1 kw2", "At SMD",
           ".SolderMask 0.1", ".SolderPaste -0.05", ".SolderPasteRatio -0.1",
           ".LocalClearance 0.2", ".ZoneConnection 2",
           'T0 0 -3 1.5 1.2 900 0.2 N V 21 N "REF**"',
           'T1 0 3 1.5 1.5 0 0.2 M I 21 N "%V val"',
           'T2 1 1 1 1 300 0.15 M V 25 I "user ~RST~" R B',
           "DS 0 0 1 1 0.1 21", "DC 0 0 1 0 0.1 24", "DA 0 0 1 0 450 0.1 21",
           "DA 0 0 1 0 -300 0.1 21", "DP 0 0 0 0 4 0.1 21", "Dl 0 0", "Dl 1 0", "Dl 1 0", "Dl 1 1",
           *pad_block('Sh "1" O 1.5 2.5 0 0 450.5', "Dr 0 0.1 -0.2 O 0.8 1.6",
                      "At SMD N 00888000", 'Ne 1 "GND"', "Po 1.27 0", ".SolderMask 0.05",
                      ".SolderPasteRatio -0.2", "Le 1.5"),
           *pad_block('Sh "" C 3 3 0 0 0', "Dr 3 0 0", "At HOLE N 00E0FFFF", "Po 5 5"),
           *pad_block('Sh "A1" T 2 1 0.2 0 900', "Dr 1 0 0 O 1 2", "At CONN N 00E0FFFF",
                      "Po -5 0", ".ThermalWidth 0.3", ".ThermalGap 0.4", ".LocalClearance 0.1",
                      ".ZoneConnection 1"),
           "$SHAPE3D", 'Na "dil/dil_14.wrl"', "Sc 1 1 1", "Of 0 0.075 0", "Ro 0 0 90",
           "$EndSHAPE3D",
           po="Po 1 2 450 15 00000000 00000000 ~F"),
    module("ROT",
           *pad_block('Sh "1" C 600 600 0 0 1200', "Dr 300 0 0", "At STD N 00E0FFFF",
                      "Po 333 777"),
           'T0 111 222 400 400 1200 60 N V 21 N "REF**"', "DS 123 456 789 -321 60 21",
           "DA 10 20 1000 333 123 60 21", "DP 0 0 0 0 3 60 21", "Dl 0 0", "Dl 1000 10", "Dl 17 999",
           po="Po 1000 2000 300 15 00000000 00000000 ~~"),
    module("a/b:c \"q\"", "At VIRTUAL"),
    module("TST1"),
    units_mm=True)


@pytest.mark.kicad_cli
def test_kicad_cli_same_on_synthetic(kicad_cli, tmp_path):
    """Units mm, ориентация 45° и 30° (погрешности ±1 нм), SMD с овальным сверлом и
    смещением, HOLE, CONN-трапеция, 3D-модель, дуги, полигон, выравнивание текста, имена с
    недопустимыми символами, повтор имени — побайтно как kicad-cli (кроме uuid)."""
    src = tmp_path / "synth.mod"
    src.write_text(SYNTH_FOR_CLI, encoding="utf-8")
    ref = _kicad_convert(kicad_cli, src, tmp_path / "kicad.pretty")
    mine = {p.name: p.read_text(encoding="utf-8")
            for p in legacy.convert(src, tmp_path / "mine.pretty")}
    assert set(ref) == set(mine) == {"TST1.kicad_mod", "TST1_v2.kicad_mod", "ROT.kicad_mod",
                                     "a%2fb%3ac %22q%22.kicad_mod"}
    for name in ref:
        assert norm(mine[name]) == norm(ref[name]), name


# ---------------------------------------------------------------------------
# Синтетические входы
# ---------------------------------------------------------------------------

def test_units_mm():
    fp = one(lib(module("M", 'T0 0 -10.16 1.524 1.2 0 0.3048 N V 21 N "L"',
                        "DS -1.5 0 2.54 0 0.2032 21",
                        *pad_block('Sh "1" R 1.905 1.905 0 0 0', "Dr 0.8128 0 0",
                                   "At STD N 00E0FFFF", "Po 2.54 -1.27")), units_mm=True))
    p = fp.pads[0]
    assert (p.x, p.y, p.size_x, p.size_y, p.drill.diameter) == (2.54, -1.27, 1.905, 1.905, 0.8128)
    assert (fp.reference.y, fp.reference.font_size_y, fp.reference.font_size_x,
            fp.reference.thickness) == (-10.16, 1.524, 1.2, 0.3048)
    line = fp.graphics[0]
    assert (line.start, line.end, line.width) == ((-1.5, 0.0), (2.54, 0.0), 0.2032)


def test_units_only_mm_and_only_before_index():
    body = module("M", *pad_block('Sh "1" C 100 100 0 0 0', "At STD N 00E0FFFF"))
    inch = HEADER + "Units inch\n$INDEX\n$EndINDEX\n" + body
    assert one(inch).pads[0].size_x == 0.254          # deci-mils
    late = HEADER + "$INDEX\nUnits mm\n$EndINDEX\n" + body
    assert one(late).pads[0].size_x == 0.254          # после $INDEX не действует


def test_oval_drill():
    fp = one(lib(module("M",
                        *pad_block('Sh "1" O 1000 2000 0 0 0', "Dr 400 0 0 O 400 800",
                                   "At STD N 00E0FFFF"),
                        *pad_block('Sh "2" O 1000 1000 0 0 0', "Dr 400 50 -100 O 600 600",
                                   "At STD N 00E0FFFF", "Po 3000 0"))))
    d1, d2 = fp.pads[0].drill, fp.pads[1].drill
    assert compact(d1.node) == "(drill oval 1.016 2.032)"
    assert (d1.oval, d1.diameter, d1.width) == (True, 1.016, 2.032)
    assert compact(d2.node) == "(drill oval 1.524(offset 0.127 -0.254))"


def test_smd_drill_removed_offset_kept():
    fp = one(lib(module("M",
                        *pad_block('Sh "1" O 1.5 2.5 0 0 0', "Dr 0 0.1 -0.2 O 0.8 1.6",
                                   "At SMD N 00888000"),
                        # строка Dr после At: отверстие убирает копирование площадки KiCad
                        *pad_block('Sh "2" R 1 1 0 0 0', "At SMD N 00888000", "Dr 0.5 0 0",
                                   "Po 3 0")), units_mm=True))
    p1, p2 = fp.pads
    assert compact(p1.drill.node) == "(drill oval(offset 0.1 -0.2))"
    assert p2.drill is None


def test_hole_pad():
    fp = one(lib(module("M", *pad_block('Sh "9" C 1181 1181 0 0 0', "Dr 1181 0 0",
                                        "At HOLE N 00E00001", 'Ne 0 ""', "Po 3445 -3937"))))
    p = fp.pads[0]
    assert (p.number, p.type, p.shape) == ("", "np_thru_hole", "circle")
    assert p.layers == ["*.Mask", "B.Cu", "F.SilkS"]
    assert p.remove_unused_layers is None
    assert compact(p.node) == ('(pad "" np_thru_hole circle(at 8.7503 -9.99998)'
                               '(size 2.99974 2.99974)(drill 2.99974)'
                               '(layers "*.Mask" "B.Cu" "F.SilkS"))')


def test_hole_number_kept_if_sh_after_at():
    # PAD::SetAttribute стирает номер в момент смены типа; номер, заданный позже, остаётся
    fp = one(lib(module("M", *pad_block("At HOLE N 00E0FFFF", 'Sh "5" C 100 100 0 0 0'))))
    assert fp.pads[0].number == "5"


def test_smd_pad_with_mask():
    fp = one(lib(module("M",
                        *pad_block('Sh "1" R 600 400 0 0 900', "Dr 0 0 0", "At SMD N 00888000",
                                   "Po 1000 0", ".SolderMask 20", ".SolderPaste -10",
                                   ".SolderPasteRatio -0.25", ".LocalClearance 40",
                                   ".ZoneConnection 2", ".ThermalWidth 30", ".ThermalGap 50",
                                   "Le 100"),
                        *pad_block('Sh "2" R 600 400 0 0 0', "At SMD N 00E0FFFF", "Po -1000 0"),
                        *pad_block('Sh "3" R 600 400 0 0 0', "At CONN N 00808000", "Po 0 1000"))))
    p1, p2, p3 = fp.pads
    assert (p1.type, p1.angle, p1.layers) == ("smd", 90.0, ["F.Cu", "F.Mask", "F.Paste"])
    assert p1.drill is None
    assert (p1.solder_mask_margin, p1.solder_paste_margin, p1.solder_paste_ratio,
            p1.clearance, p1.zone_connect, p1.thermal_bridge_width, p1.thermal_gap,
            p1.die_length) == (0.0508, -0.0254, -0.25, 0.1016, 2, 0.0762, 0.127, 0.254)
    assert p1.thermal_bridge_angle == 45.0
    # SMD с многослойной медью: остаётся B.Cu (PAD::SetAttribute)
    assert p2.layers == ["*.Mask", "B.Cu", "F.SilkS"]
    assert (p3.type, p3.layers) == ("connect", ["F.Cu", "F.Mask"])
    order = [n.name for n in p1.node.nodes()]
    assert order == ["at", "size", "layers", "die_length", "solder_mask_margin",
                     "solder_paste_margin", "solder_paste_margin_ratio", "clearance",
                     "zone_connect", "thermal_bridge_width", "thermal_bridge_angle",
                     "thermal_gap", "uuid"]


@pytest.mark.parametrize("mask, kind, expected", [
    ("00E0FFFF", "STD", ["*.Cu", "*.Mask", "F.SilkS"]),
    ("00888000", "STD", ["F.Cu", "F.Mask", "F.Paste"]),
    ("0000FFFF", "SMD", ["B.Cu"]),
    ("00008001", "STD", ["F&B.Cu"]),
    ("00008001", "CONN", ["B.Cu"]),
    ("0088FFFF", "HOLE", ["*.Cu", "F.Mask", "F.Paste"]),
    ("00F0FFFF", "SMD", ["*.SilkS", "*.Mask", "B.Cu"]),
    ("00888002", "STD", ["F.Cu", "F.Mask", "F.Paste", "In14.Cu"]),
    ("00888002", "SMD", ["F.Cu", "F.Mask", "F.Paste"]),
    ("00000000", "STD", []),
    ("00E0FFFF", "MECA", ["*.Cu", "*.Mask", "F.SilkS"]),
])
def test_pad_mask_table(mask, kind, expected):
    """Таблица масок legacy-mod.md §6.5 (``F.Cu``+``B.Cu`` KiCad 9.0.1 пишет ``F&B.Cu``)."""
    fp = one(lib(module("M", *pad_block('Sh "1" R 100 100 0 0 0', f"At {kind} N {mask}"))))
    assert fp.pads[0].layers == expected


def test_pad_attribute_changes_twice():
    # SMD урезает медь, повторный At STD снова «добавляет» всю медь (PAD::SetAttribute)
    fp = one(lib(module("M", *pad_block('Sh "1" R 100 100 0 0 0', "At SMD N 00888000",
                                        "At STD N 00888000"))))
    assert (fp.pads[0].type, fp.pads[0].layers) == ("thru_hole", ["*.Cu", "F.Mask", "F.Paste"])


def test_circle_pad_and_zero_and_negative_size():
    issues: list[LegacyIssue] = []
    fp = one(lib(module("M",
                        *pad_block('Sh "1" C 700 1400 0 0 0', "At STD N 00E0FFFF"),
                        *pad_block('Sh "2" R -500 300 0 0 0', "At STD N 00E0FFFF", "Po 2000 0"),
                        *pad_block('Sh "3" C 0 0 0 0 0', "At STD N 00E0FFFF"))), issues=issues)
    assert [(p.number, p.size_x, p.size_y) for p in fp.pads] == [("1", 1.778, 1.778),
                                                                 ("2", 1.27, 0.762)]
    assert [i.code for i in issues] == ["legacy-zero-size-pad"]
    assert issues[0].module == "M" and issues[0].line > 0


def test_pad_defaults_and_trapezoid():
    fp = one(lib(module("M", *pad_block('Sh "7" T 800 400 100 -50 0'))))
    p = fp.pads[0]
    assert (p.type, p.shape, p.x, p.y) == ("thru_hole", "trapezoid", 0.0, 0.0)
    assert p.rect_delta == (0.254, -0.127)
    assert p.drill.diameter == 0.762          # 30 mil по умолчанию
    assert p.layers == ["*.Cu", "*.Mask"]     # PTHMask


def test_unknown_pad_attribute():
    issues: list[LegacyIssue] = []
    fp = one(lib(module("M", *pad_block('Sh "1" C 100 100 0 0 0', "At MECA N 00E0FFFF"))),
             issues=issues)
    assert fp.pads[0].type == "thru_hole"
    assert [i.code for i in issues] == ["legacy-unknown-pad-attr"]


# --- дуги ----------------------------------------------------------------------------------

@pytest.mark.parametrize("angle, start, mid, end", [
    (900, (2.54, 0), (1.796051, 1.796051), (0, 2.54)),
    (-900, (0, -2.54), (1.796051, -1.796051), (2.54, 0)),
    (450, (2.54, 0), (2.346654, 0.972016), (1.796051, 1.796051)),
    (300, (2.54, 0), (2.453452, 0.6574), (2.199705, 1.27)),
    (1800, (2.54, 0), (0, 2.54), (-2.54, 0)),
    (-1800, (-2.54, 0), (0, -2.54), (2.54, 0)),
    (3600, (2.54, 0), (-2.54, 0), (2.54, 0)),
    (5000, (2.54, 0), (0.868731, 2.386819), (-1.945753, 1.632681)),   # 500° -> 140°
])
def test_da_arc(angle, start, mid, end):
    fp = one(lib(module("M", f"DA 0 0 1000 0 {angle} 60 21")))
    arc = fp.graphics[0]
    assert isinstance(arc, Arc)
    assert (arc.start, arc.mid, arc.end) == (start, mid, end)
    assert (arc.width, arc.layer) == (0.1524, "F.SilkS")


@pytest.mark.parametrize("angle", [900, -900, 450, -450, 123, -1237, 1800, 3333, -3001])
def test_da_arc_matches_geometry(angle):
    """Та же дуга, что geometry.arc_three_points с углом ``-A`` (знак geometry —
    противоположный), при ``A < 0`` начало и конец переставлены; отличие — до 1 нм."""
    fp = one(lib(module("M", f"DA 10 20 1000 333 {angle} 60 21")))
    arc = fp.graphics[0]
    c, s = (0.0254, 0.0508), (2.54, 0.84582)
    g_s, g_m, g_e = geometry.arc_three_points(c, s, -angle / 10.0)
    if angle < 0:
        g_s, g_e = g_e, g_s
    for got, exp in zip((arc.start, arc.mid, arc.end), (g_s, g_m, g_e)):
        assert got == pytest.approx(exp, abs=1.5e-6)
    # дуга в KiCad 9 всегда по часовой стрелке на экране от start к end
    assert geometry.arc_from_three_points(arc.start, arc.mid, arc.end).sweep < 0


def test_graphics_layers_and_circle():
    fp = one(lib(module("M", "DC 0 0 300 300 0 -5", "DS 0 0 1 1 10 7", "DS 0 0 2 2 10 3",
                        "DS 0 0 3 3 10 28", "DS 0 0 4 4 10 29", "DS 0 0 5 5 10 15")))
    by_layer = {g.layer: g for g in fp.graphics}
    assert set(by_layer) == {"F.SilkS", "In8.Cu", "In12.Cu", "Edge.Cuts", "F.Cu"}
    circle = by_layer["F.SilkS"]
    assert isinstance(circle, Circle)
    assert (circle.center, circle.end, circle.width, circle.fill) == ((0.0, 0.0), (0.762, 0.762),
                                                                     0.0, False)
    assert fp.graphics[-1].layer == "In12.Cu"  # слой > 28 -> F.SilkS; медь допускается


def test_dp_polygon_kicad9_and_fixed():
    text = lib(module("M", "DP 0 0 0 0 5 20 21", "Dl 0 0", "Dl 100 0", "Dl 100 0", "Dl 100 100",
                      "Dl 0 0", "DP 0 0 0 0 3 20 28", "Dl 0 0", "Dl 10 0", "Dl 10 10",
                      "DP 0 0 0 0 3 20 21", "Dl 0 0", "Dl 0 0", "Dl 5 5"))
    fp = one(text)
    polys = [g for g in fp.graphics if isinstance(g, Poly)]
    assert len(polys) == 2       # полигон из 2 точек (после удаления дублей) не пишется
    silk = [p for p in polys if p.layer == "F.SilkS"][0]
    assert silk.points == [(0.0, 0.0), (0.254, 0.0), (0.254, 0.254), (0.0, 0.0)]
    assert all(not p.fill for p in polys)
    fixed = one(text, compat="fixed")
    fills = {p.layer: p.fill for p in fixed.graphics if isinstance(p, Poly)}
    assert fills == {"F.SilkS": True, "Edge.Cuts": False}
    assert "(fill yes)" in fixed.dumps()


# --- тексты ---------------------------------------------------------------------------------

def test_t2_text_mirror_italic_justify():
    fp = one(lib(module("M", 'T2 100 200 300 250 450 20 M V 25 I "user ~RST~ %R" R B')))
    t = [x for x in fp.texts if x.node.name == "fp_text"][0]
    assert t.kind == "user"
    assert (t.text, t.x, t.y, t.angle, t.layer) == ("user ~{RST} ${REFERENCE}", 0.254, 0.508,
                                                   45.0, "Cmts.User")
    assert (t.font_size_y, t.font_size_x, t.thickness) == (0.762, 0.635, 0.0508)
    assert t.italic and t.mirror and not t.hide
    assert t.justify == ["right", "bottom", "mirror"]
    assert t.node.find("unlocked") is None


def test_t2_hidden_becomes_field():
    issues: list[LegacyIssue] = []
    fp = one(lib(module("M", 'T2 100 200 300 300 0 20 N I 21 N "hidden one"',
                        'T2 0 0 300 300 0 20 N I 21 N "hidden two"',
                        'T0 0 0 300 300 0 20 N I 21 N "REF**"')), issues=issues)
    fields = {t.name: t for t in fp.texts if t.node.name == "property"}
    assert fields["Field5"].text == "hidden one" and fields["Field5"].hide
    assert fields["Field6"].text == "hidden two"
    assert (fields["Field5"].x, fields["Field5"].y, fields["Field5"].layer) == (0.254, 0.508,
                                                                                 "F.SilkS")
    assert fields["Reference"].hide
    assert not [t for t in fp.texts if t.node.name == "fp_text"]
    assert [i.code for i in issues] == ["legacy-hidden-text", "legacy-hidden-text"]
    names = [str(n.atom(0)) for n in nodes(fp, "property")]
    assert names == ["Reference", "Value", "Datasheet", "Description", "Field5", "Field6"]


def test_text_layers_and_defaults():
    fp = one(lib(module("M", 'T0 0 0 300 300 0 0 N V 0 N "a"', 'T1 0 0 300 300 0 -3 N V 5 N "b"',
                        'T2 0 0 300 300 0 10 N V -2 N "c"', 'T2 0 0 300 300 0 10 N V 99 N "d"',
                        'T2 0 0 300 300 0 10 N V 20 N "e"')))
    layers = {t.text: t.layer for t in fp.texts}
    assert layers == {"a": "B.SilkS", "b": "F.SilkS", "c": "B.Cu", "d": "Edge.Cuts",
                      "e": "B.SilkS", "": "F.Fab"}
    assert fp.reference.thickness is None      # толщина 0 не пишется
    no_t = one(lib(module("M")))
    ref, val = no_t.reference, no_t.value
    assert (ref.text, ref.layer, ref.x, ref.y, ref.font_size, ref.thickness) == \
        ("", "F.SilkS", 0.0, 0.0, (1.27, 1.27), 0.15)
    assert (val.text, val.layer) == ("", "F.Fab")


def test_text_missing_fields_like_kicad():
    # поля mirror/hide/layer/italic отсутствуют: strtok берёт начало текста, слой 0 -> B.SilkS
    fp = one(lib(module("M", 'T0 0 0 300 300 0 10 N V "U**"')))
    assert (fp.reference.text, fp.reference.layer) == ("U**", "B.SilkS")
    fp = one(lib(module("M", 'T0 0 0 300 300 0 10 "U**"')))   # нет токена слоя -> 21
    assert (fp.reference.text, fp.reference.layer) == ("U**", "F.SilkS")
    # italic отсутствует: strtok «съедает» пробел после кавычки, выравнивание теряется
    fp = one(lib(module("M", 'T0 0 0 300 300 0 10 N V 21 "U**" L T')))
    assert fp.reference.justify == []
    fp = one(lib(module("M", 'T0 0 0 300 300 0 10 N V 21 N "U**" L T')))
    assert fp.reference.justify == ["left", "top"]


@pytest.mark.parametrize("src, expected", [
    ("~", "~"), ("~RST~", "~{RST}"), ("a~b c", "a~{b} c"), ("~~", "~"), ("x~~y", "x~y"),
    ("~{x}", "~{x}"), ("~~{x}", "~~{x}"), ("~a)b", "~{a})b"), ("~a", "~{a}"), ("", ""),
])
def test_overbar_conversion(src, expected):
    assert legacy._convert_overbar(src) == expected


def test_escaped_quotes_in_cd():
    fp = one(lib(module("M", 'Cd  Descr with \\"quotes\\" and \\\\ back  ', "Kw  a  b ")))
    # Cd/Kw — текст до конца строки как есть (без разэкранирования), пробелы по краям убраны
    assert fp.descr == 'Descr with \\"quotes\\" and \\\\ back'
    assert fp.tags == "a  b"
    assert '(descr "Descr with \\\\\\"quotes\\\\\\" and \\\\\\\\ back")' in fp.dumps()
    assert load_text_roundtrip(fp)


def load_text_roundtrip(fp: Footprint) -> bool:
    text = fp.dumps()
    again = loads(text)
    return again.dumps() == text and again.descr == fp.descr


def test_quoted_pad_number_and_text_escapes():
    fp = one(lib(module("M", 'T2 0 0 300 300 0 10 N V 21 N "a \\"q\\" \\n b"',
                        *pad_block('Sh "A\\"1" R 100 100 0 0 0'))))
    assert fp.pads[0].number == 'A"1'
    assert [t.text for t in fp.texts if t.node.name == "fp_text"] == ['a "q" \\n b']


def test_module_attributes_and_overrides():
    fps = legacy.loads_library(lib(
        module("A", "At SMD", ".SolderMask 0", ".SolderPasteRatio 0.3", ".ZoneConnection 0",
               ".LocalClearance 10", ".ThermalWidth 5", ".ThermalGap 5"),
        module("B", "At VIRTUAL"), module("C", "At "), module("D", ".SolderPasteRatio -0.8",
                                                             ".ZoneConnection -1")))
    a, b, c, d = fps
    assert set(a.attrs) == {"smd"}
    assert (a.solder_mask_margin, a.solder_paste_ratio, a.zone_connect, a.clearance) == \
        (0.0, 0.0, 0, 0.0254)
    assert a.node.find("thermal_gap") is None and a.node.find("thermal_width") is None
    assert list(b.attrs) == ["exclude_from_pos_files", "exclude_from_bom"]
    assert list(c.attrs) == ["through_hole", "exclude_from_pos_files"]
    assert (d.solder_paste_ratio, d.zone_connect) == (-0.5, None)


# --- ориентация и положение корпуса -----------------------------------------------------------

def test_orientation_subtracted_from_pad_and_text_angles():
    fp = one(lib(module("C7812", 'T0 0 -300 400 400 0 60 N V 21 N "R"',
                        'T1 0 300 400 400 1800 60 N V 21 N "V"',
                        *pad_block('Sh "8" R 236 748 0 0 900', "At STD N 00E0FFFF",
                                   "Po -750 1100"),
                        po="Po 5000 7000 900 15 00000000 00000000 ~~")))
    p = fp.pads[0]
    assert (p.x, p.y, p.angle) == (-1.905, 2.794, 0.0)
    assert p.node.find("at").atoms()[2:] == []            # угол 0 не пишется
    assert (fp.reference.angle, fp.value.angle) == (270.0, 90.0)
    assert fp.node.find("at") is None


def test_non_cardinal_orientation_rounding_like_kicad():
    # значения — из kicad-cli 9.0.1: двойной KiROUND даёт ±1 нм
    fp = one(lib(module("ROT", *pad_block('Sh "1" C 600 600 0 0 1200', "Dr 300 0 0",
                                          "At STD N 00E0FFFF", "Po 333 777"),
                        "DA 10 20 1000 333 123 60 21",
                        po="Po 1000 2000 300 15 00000000 00000000 ~~")))
    p = fp.pads[0]
    assert (p.x, p.y, p.angle) == (0.845821, 1.97358, 90.0)
    arc = fp.graphics[0]
    assert (arc.start, arc.mid, arc.end) == ((2.54, 0.845821), (2.440356, 1.110639),
                                             (2.312915, 1.363257))


def test_elements_before_po_keep_angle():
    # площадка до строки Po поворачивается вместе с корпусом: её угол не уменьшается
    fp = one(lib(module("M", *pad_block('Sh "1" R 100 100 0 0 300', "Po 100 0"),
                        "Po 0 0 900 15 00000000 00000000 ~~",
                        *pad_block('Sh "2" R 100 100 0 0 300', "Po 200 0"), po="")))
    angles = {p.number: p.angle for p in fp.pads}
    assert angles == {"1": 30.0, "2": 300.0}
    assert {p.number: p.x for p in fp.pads} == {"1": 0.254, "2": 0.508}


def test_status_flags_kicad9_and_fixed():
    text = lib(module("A", po="Po 0 0 0 15 00000000 00000000 ~F"),
               module("B", po="Po 0 0 0 15 00000000 00000000 F~"),
               module("C", po="Po 0 0 0 15 00000000 00000000 ~FP"))
    issues: list[LegacyIssue] = []
    a, b, c = legacy.loads_library(text, issues=issues)
    assert (a.locked, b.locked, c.locked, c.placed) == (True, False, True, True)
    assert [i.code for i in issues] == ["legacy-locked-lost"]
    a, b, c = legacy.loads_library(text, compat="fixed")
    assert (a.locked, b.locked, c.locked, c.placed) == (False, True, False, False)


def test_back_layer_module_kept():
    issues: list[LegacyIssue] = []
    fp = one(lib(module("BACK", 'T0 0 -300 400 400 0 60 N V 20 N "REF**"',
                        *pad_block('Sh "1" R 500 300 0 0 0', "At SMD N 00440001", "Po 100 200"),
                        po="Po 0 0 0 0 00000000 00000000 ~~")), issues=issues)
    assert fp.layer == "B.Cu"
    assert fp.pads[0].layers == ["B.Cu", "B.Mask", "B.Paste"]
    assert (fp.pads[0].x, fp.pads[0].y) == (0.254, 0.508)
    assert fp.reference.layer == "B.SilkS"
    assert [i.code for i in issues] == ["legacy-back-layer"]


def test_other_module_layer_goes_front():
    issues: list[LegacyIssue] = []
    fp = one(lib(module("X", po="Po 0 0 0 21 00000000 00000000 ~~")), issues=issues)
    assert fp.layer == "F.Cu"
    assert [i.code for i in issues] == ["legacy-module-layer"]


# --- 3D ----------------------------------------------------------------------------------------

def test_shape3d_kicad9_and_fixed():
    text = lib(module("M", "$SHAPE3D", 'Na "discret/cnp.wrl"', "Sc 1 2 3", "Of 0 0.075 -0.1",
                      "Ro 0 0 90", "$EndSHAPE3D", "$SHAPE3D", 'Na ""', "$EndSHAPE3D",
                      "$SHAPE3D", 'Na "b.wrl"', "Sc 2 x 3", "$EndSHAPE3D"))
    issues: list[LegacyIssue] = []
    fp = one(text, issues=issues)
    assert [m.path for m in fp.models] == ["discret/cnp.wrl", "b.wrl"]   # пустое имя не пишется
    m = fp.models[0]
    assert (m.offset, m.scale, m.rotate) == ((0.0, 0.075, -0.1), (1.0, 2.0, 3.0), (0.0, 0.0, 90.0))
    assert fp.models[1].scale == (2.0, 1.0, 1.0)                         # sscanf до ошибки
    assert [i.code for i in issues] == ["legacy-model-offset"]
    fixed = one(text, compat="fixed")
    assert fixed.models[0].offset == pytest.approx((0.0, 1.905, -2.54))
    last = [n.name for n in fp.node.nodes()][-3:]
    assert last == ["embedded_fonts", "model", "model"]


# --- структура библиотеки ---------------------------------------------------------------------------

def test_several_modules_sorted_duplicates_and_names():
    issues: list[LegacyIssue] = []
    fps = legacy.loads_library(lib(module("mlt"), module("Zeta"), module("a/b:c \"q\""),
                                   module("mlt"), module("mlt"), module("Ёж"), module("a b")),
                               issues=issues)
    assert [fp.name for fp in fps] == ["Zeta", "a b", "a%2fb%3ac %22q%22", "mlt", "mlt_v2",
                                       "mlt_v3", "Ёж"]
    codes = sorted(i.code for i in issues)
    assert codes == ["legacy-duplicate-name", "legacy-duplicate-name", "legacy-name-escaped"]


def test_convert_file_names(tmp_path):
    src = tmp_path / "x.mod"
    src.write_text(lib(module("a/b"), module("a b")), encoding="utf-8")
    paths = legacy.convert(src, tmp_path / "x.pretty")
    assert [p.name for p in paths] == ["a b.kicad_mod", "a%2fb.kicad_mod"]


def test_no_index_means_no_modules():
    assert legacy.loads_library(lib(module("M"), index=False)) == []


def test_index_contents_ignored_and_double_index():
    text = HEADER + "$INDEX\nfoo\n$EndINDEX\n$INDEX\nbar\n$EndINDEX\n" + module("M") + \
        "garbage line\n" + module("N")
    assert [fp.name for fp in legacy.loads_library(text)] == ["M", "N"]


def test_keywords_case_insensitive():
    text = "pcbnew-libmodule-v1\n$index\n$endindex\n$module low\npo 0 0 0 15 0 0 ~~\n" \
           "ds 0 0 100 0 10 21\n$pad\nsh \"1\" R 100 100 0 0 0\n$endpad\n$endmodule\n"
    fp = one(text)
    assert fp.name == "low" and len(fp.pads) == 1
    # «ds»: второй символ сравнивается с учётом регистра — строка не графика
    assert fp.graphics == []


def test_bom_and_bytes_and_invalid_utf8():
    data = ("﻿" + lib(module("M", "Cd ok"))).encode("utf-8")
    assert one(data).descr == "ok"
    issues: list[LegacyIssue] = []
    fp = one(lib(module("M")).encode("utf-8").replace(b"$MODULE M", b"$MODULE M\xff"),
             issues=issues)
    assert fp.name == "Mÿ"
    assert [i.code for i in issues] == ["legacy-invalid-utf8"]


def test_is_legacy():
    assert legacy.is_legacy("PCBNEW-LibModule-V1  date\n")
    assert legacy.is_legacy("pcbnew-libmodule-v1")
    assert legacy.is_legacy(b"\xef\xbb\xbfPCBNEW-LibModule-V1\r\n$INDEX")
    assert not legacy.is_legacy("PCBNEW-LibModule-V10")
    assert not legacy.is_legacy("(footprint \"x\")")
    assert not legacy.is_legacy("")


def test_io_load_single_and_multi(tmp_path, legacy_mod):
    single = tmp_path / "one.mod"
    single.write_text(lib(module("M", *pad_block('Sh "1" C 100 100 0 0 0'))), encoding="utf-8")
    fp = load(single)
    assert fp.name == "M" and len(fp.pads) == 1
    assert loads(single.read_text(encoding="utf-8")).name == "M"
    with pytest.raises(LegacyLibraryError):
        load(legacy_mod)


def test_compat_validation():
    with pytest.raises(ValueError):
        legacy.loads_library(lib(module("M")), compat="kicad5")


# --- формат результата (version): KiCad 9 по умолчанию, KiCad 6/7/8 по запросу --------------------

def test_version_default_is_kicad9(legacy_mod):
    assert {fp.version for fp in legacy.read_library(legacy_mod)} == {DEFAULT_VERSION}
    assert [norm(fp.dumps()) for fp in legacy.read_library(legacy_mod, version=9)] == \
        [norm(fp.dumps()) for fp in legacy.read_library(legacy_mod)]


@pytest.mark.parametrize("kicad, version", [(8, 20240108), ("7", 20221018), (20211014, 20211014)])
def test_version_target_same_content(legacy_mod, tmp_path, kicad, version):
    """Регрессия (приёмка, сценарий 10): результат конвертации был только в формате KiCad 9,
    который KiCad 8 не открывает. ``version`` даёт тот же результат в формате другой версии:
    площадки, графика, тексты совпадают (порядок узлов — по writer'у своей версии)."""
    ref = legacy.read_library(legacy_mod)
    fps = legacy.read_library(legacy_mod, version=kicad)
    assert [fp.name for fp in fps] == [fp.name for fp in ref]
    def key(p):
        return (p.number, p.type, p.shape, p.x, p.y, p.size,
                p.drill.size if p.drill else None, tuple(p.layers))

    def gkey(g):
        return (g.kind, g.layer, tuple(g.points), g.width)

    def tkey(t):
        return (t.kind, t.text, t.layer, t.position, t.angle, t.hide)

    for fp, r in zip(fps, ref):
        assert fp.version == version
        assert sorted(map(key, fp.pads)) == sorted(map(key, r.pads))
        assert sorted(map(gkey, fp.graphics)) == sorted(map(gkey, r.graphics))
        # служебные пустые поля — по версии (KiCad 8 пишет ещё поле Footprint)
        assert sorted(tkey(t) for t in fp.texts if t.text) == \
            sorted(tkey(t) for t in r.texts if t.text)
        text = fp.dumps()
        assert loads(text).dumps() == text
    paths = legacy.convert(legacy_mod, tmp_path / "k.pretty", version=kicad)
    assert [load(q).version for q in paths] == [version] * 3


def test_version_kicad6_has_no_thermal_bridge_angle():
    """В формате KiCad 6 (до 20211227) токена thermal_bridge_angle нет — KiCad 9 пишет
    его у некруглых площадок, в KiCad 6 угол спиц задаёт парсер."""
    text = lib(module("M", *pad_block('Sh "1" R 100 100 0 0 0', "At SMD N 00888000",
                                      "Po 0 0")))
    assert "thermal_bridge_angle" in legacy.loads_library(text)[0].dumps()
    assert "thermal_bridge_angle" in legacy.loads_library(text, version=7)[0].dumps()
    k6 = legacy.loads_library(text, version=6)[0].dumps()
    assert "thermal_bridge_angle" not in k6 and "(version 20211014)" in k6


def test_version_validation(legacy_mod, tmp_path):
    for bad in (5, 10, "20240109"):
        with pytest.raises(ValueError, match="версия KiCad"):
            legacy.loads_library(lib(module("M")), version=bad)
        with pytest.raises(ValueError, match="версия KiCad"):
            legacy.convert(legacy_mod, tmp_path / "x.pretty", version=bad)
    assert not (tmp_path / "x.pretty").exists()


# --- ошибки формата -------------------------------------------------------------------------------

@pytest.mark.parametrize("text, line, fragment", [
    ("", 1, "пуст"),
    ("hello\n$INDEX\n", 1, "PCBNEW-LibModule-V1"),
    ("\n" + HEADER, 1, "PCBNEW-LibModule-V1"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nPo 0 0 0 15 0 0 ~~\n", 5, "$EndMODULE"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\n$PAD\nSh \"1\" C 1 1 0 0 0\n", 6, "$EndPAD"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\n$PAD\nSh \"1\" X 1 1 0 0 0\n$EndPAD\n$EndMODULE\n",
     7, "форма площадки"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDS 1 2 x\n$EndMODULE\n", 6, "числа"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDP 0 0 0 0 2 1 21\nDl 0 0\nDS 0 0 1 1 1 21\n"
              "$EndMODULE\n", 8, "Dl"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDP 0 0 0 0 3 1 21\nDl 0 0\n", 8, "конец файла"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\n$SHAPE3D\nNa \"x\"\n", 6, "$EndSHAPE3D"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\n$PAD\nDr 1 0 0 O\n$EndPAD\n$EndMODULE\n", 7, "Dr"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE   \n$EndMODULE\n", 5, "имя"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nT0 1 2 3\n$EndMODULE\n", 6, "числа"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nPo 1e999 0 0 15 0 0 ~~\n$EndMODULE\n", 6, "некоррект"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nSc\n$EndMODULE\n", 6, "Sc"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nPo 0 0\n$EndMODULE\n", 6, "uuid"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDP 0 0 0 0 -4 1 21\n$EndMODULE\n", 6, "отрицательное"),
    (HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDA 0 0 1 0 nan 1 21\n$EndMODULE\n", 6, "угол"),
])
def test_format_errors(text, line, fragment):
    with pytest.raises(LegacyFormatError) as ei:
        legacy.loads_library(text)
    err = ei.value
    assert isinstance(err, ValueError)
    assert err.line == line
    assert fragment in str(err)
    assert str(err).startswith(f"строка {line}")


def test_format_error_position_and_path(tmp_path):
    src = tmp_path / "bad.mod"
    src.write_text(HEADER + "$INDEX\n$EndINDEX\n$MODULE M\nDS 1 2 3 4 zz 21\n$EndMODULE\n",
                   encoding="utf-8")
    with pytest.raises(LegacyFormatError) as ei:
        legacy.read_library(src)
    assert (ei.value.line, ei.value.col, ei.value.path) == (6, 11, str(src))
    assert str(ei.value).startswith("строка 6, позиция 11: ")


def test_issue_str():
    i = LegacyIssue("legacy-zero-size-pad", "площадка удалена", 12, "M")
    assert str(i) == "WARNING legacy-zero-size-pad: площадка удалена (строка 12)"


def test_inf_nan_lengths_like_kiround():
    fp = one(lib(module("M", "DS 1 1 inf -inf 10 21", "DS 0 0 nan 5 10 21")))
    ends = sorted(g.end for g in fp.graphics)
    assert ends == [(0.0, 0.0127), (2147.483646, -2147.483647)]


def test_text_size_clamped():
    fp = one(lib(module("M", 'T0 0 0 400 0 0 10 N V 21 N "R"'), units_mm=True))
    assert fp.reference.font_size == (0.001, 250.0)


def _unclosed_quote_lib() -> str:
    """Строка T0 с незакрытой кавычкой: KiCad читает выравнивание за концом строки — из
    хвоста предыдущей, более длинной строки в буфере LINE_READER."""
    short = 'T0 0 0 300 300 0 10 N V 21 N "x'
    head = 'T2 0 0 300 300 0 10 N V 21 N "'
    fill = len(short) + 2 - len(head) - 2        # закрывающая кавычка и пробел
    long = head + "z" * fill + '" L T'
    assert long[len(short) + 2:] == "L T"
    return lib(module("M", long, short))


def test_unclosed_quote_reads_previous_line_tail():
    fp = one(_unclosed_quote_lib())
    assert fp.reference.text == "x\n"
    # «L T» — хвост строки T2 в буфере; strtok при её разборе уже заменил пробел после «L»
    # на NUL, поэтому второй токен (вертикальное выравнивание) не находится — как в KiCad
    assert fp.reference.justify == ["left"]


@pytest.mark.kicad_cli
def test_kicad_cli_same_on_unclosed_quote(kicad_cli, tmp_path):
    src = tmp_path / "q.mod"
    src.write_text(_unclosed_quote_lib(), encoding="utf-8")
    ref = _kicad_convert(kicad_cli, src, tmp_path / "kicad.pretty")
    mine = {p.name: p.read_text(encoding="utf-8")
            for p in legacy.convert(src, tmp_path / "mine.pretty")}
    assert {n: norm(t) for n, t in mine.items()} == {n: norm(t) for n, t in ref.items()}


def test_int32_wrap_helper():
    assert legacy._i32(2 ** 31) == -2 ** 31
    assert legacy._i32(-2 ** 31 - 1) == 2 ** 31 - 1
    assert legacy._i32(123) == 123
