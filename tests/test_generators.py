"""Тесты генераторов посадочных мест (kicadfp.generators; lab-generators.md, architecture.md §11)."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import pytest

import kicadfp
from kicadfp import generators as G
from kicadfp import load, loads, sexpr
from kicadfp.format_rules import DEFAULT_VERSION
from kicadfp.generators import _common as C
from kicadfp.generators import (
    GENERATORS,
    capacitor_axial,
    capacitor_radial,
    describe,
    diode,
    dip,
    from_json,
    lab_dip14,
    lab_mlt,
    lab_snp8,
    pin_header,
    resistor,
    transistor,
    transistor_inline,
)
from kicadfp.validate import validate

from .conftest import FIXTURES

TOL = 1e-9

# Пример ТЗ прил. В.2 — буквально
B2 = dict(rows=2, cols=4, pitch=2.5, row_pitch=5.0, pad_size=1.3, drill=0.8, first_square=True,
          mounting_holes=[(11.25, -5.0, 3.0), (11.25, 15.0, 3.0)], name="snp8")


def _all_variants():
    """Генераторы с умолчаниями и характерные варианты параметров."""
    out = [(name, {}) for name in GENERATORS]
    out += [
        ("dip", {"pins": 8}),
        ("dip", {"pins": 28, "row_pitch": 15.24}),
        ("dip", {"pins": 14, "pitch": 2.5, "row_pitch": 7.5}),
        ("dip", {"pins": 16, "pad_size": (2.4, 1.6), "pad_shape": "circle"}),
        ("pin_header", {"rows": 1, "cols": 1}),
        ("pin_header", {"rows": 2, "cols": 20}),
        ("pin_header", {"rows": 3, "cols": 5, "numbering": "by_row"}),
        ("pin_header", B2),
        ("resistor", {"series": "Axial_DIN0207"}),
        ("resistor", {"pitch": 5.08, "body_length": 3.6, "body_diameter": 1.6}),
        ("resistor", {"pitch": 7.62, "body_length": 6.3, "body_diameter": 2.5}),
        ("resistor", {"pitch": 5.0, "body_length": 5.0, "body_diameter": 4.0}),
        ("capacitor_axial", {"pitch": 10.0}),
        ("diode", {"pitch": 12.7}),
        ("diode", {"cathode_band": False}),
        ("capacitor_radial", {"polarized": True, "pitch": 2.5}),
        ("capacitor_radial", {"polarized": True, "pitch": 7.5, "diameter": 10.0, "drill": 1.0}),
        ("capacitor_radial", {"polarized": True, "hatch": False}),
        ("capacitor_radial", {"pitch": 2.5, "diameter": 3.0, "width": 1.6}),
        ("transistor", {"pitch": 2.54}),
        ("transistor", {"pins": 2, "pitch": 2.54}),
        ("lab_dip14", {"origin": "pin1"}),
        ("lab_mlt", {"origin": "pin1", "clip": False}),
        ("lab_snp8", {"numbering": "zigzag"}),
        ("lab_snp8", {"origin": "pin1", "pads_offset_y": -1.25}),
    ]
    return out


VARIANTS = _all_variants()
VARIANT_IDS = [f"{n}-{i}" for i, (n, _) in enumerate(VARIANTS)]

_ELEMENTS = ("property", "fp_text", "fp_line", "fp_rect", "fp_circle", "fp_arc", "pad")
_WIDTH = {"F.SilkS": 0.12, "F.Fab": 0.1, "F.CrtYd": 0.05}


def _gen(name: str, params: dict) -> kicadfp.Footprint:
    return GENERATORS[name](**params)


def _seg_set(fp, layers, nd=3):
    """Графика слоёв как множество нормализованных элементов: отрезки и стороны
    прямоугольников — неупорядоченные пары точек; дуги — (начало/конец неупорядоченно, mid);
    окружности — (центр, радиус)."""
    out = set()

    def pt(p):
        return (round(p[0], nd) + 0.0, round(p[1], nd) + 0.0)

    for g in fp.graphics:
        if g.layer not in layers:
            continue
        if g.kind == "line":
            out.add((g.layer, "seg", frozenset((pt(g.start), pt(g.end)))))
        elif g.kind == "rect":
            (x1, y1), (x2, y2) = g.start, g.end
            for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)),
                         ((x1, y2), (x1, y1))):
                out.add((g.layer, "seg", frozenset((pt(a), pt(b)))))
        elif g.kind == "arc":
            out.add((g.layer, "arc", frozenset((pt(g.start), pt(g.end))), pt(g.mid)))
        elif g.kind == "circle":
            out.add((g.layer, "circle", pt(g.center), round(g.radius, nd)))
        else:  # pragma: no cover
            out.add((g.layer, g.kind))
    return out


def _pads(fp):
    return [(p.number, p.type, p.shape, round(p.x, 6), round(p.y, 6), round(p.size_x, 6),
             round(p.size_y, 6), round(p.drill.diameter, 6) if p.drill else None,
             tuple(p.layers)) for p in fp.pads]


def _texts(fp):
    return {(t.text, round(t.x, 4), round(t.y, 4), round(t.angle, 4) % 360, t.layer,
             round(t.font_size_x, 4), round(t.thickness or 0, 4))
            for t in fp.texts if not t.hide}


def _courtyard(fp):
    crt = [g for g in fp.graphics if g.layer == "F.CrtYd"]
    assert len(crt) == 1
    return crt[0]


# ---------------------------------------------------------------------------------------------
# Общие требования ко всем генераторам
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,params", VARIANTS, ids=VARIANT_IDS)
def test_generator_common_requirements(name, params):
    fp = _gen(name, params)
    assert fp.version == DEFAULT_VERSION
    assert fp.generator == "kicadfp"
    assert fp.layer == "F.Cu"
    assert set(fp.attrs) == {"through_hole"}
    assert fp.descr and fp.tags
    issues = validate(fp)
    assert not [i for i in issues if i.level == "error"], issues
    assert not [i for i in issues if i.code == "COURTYARD_MISSING"]
    # Reference над корпусом на F.SilkS, Value под ним на F.Fab
    ref, val = fp.reference, fp.value
    assert ref is not None and ref.text == "REF**" and ref.layer == "F.SilkS"
    assert val is not None and val.text == fp.name and val.layer == "F.Fab"
    for t in (ref, val):
        assert (t.font_size_x, t.font_size_y, t.thickness) == (1.0, 1.0, 0.15)
        assert not t.hide
    # над/под контуром F.Fab (у dip14 Value — в центре по методичке)
    fab_ys = [y for g in fp.graphics if g.layer == "F.Fab" for y in (g.bbox().y1, g.bbox().y2)]
    assert ref.y < min(fab_ys)
    if name != "lab_dip14":
        assert val.y > max(fab_ys)
    # служебных полей нет
    assert set(fp.properties) == {"Reference", "Value"}
    # ${REFERENCE}: у семейств — на F.Fab, у лабораторных — нет
    fab_refs = [t for t in fp.texts if t.text == "${REFERENCE}"]
    if name.startswith("lab_"):
        assert fab_refs == []
    else:
        assert len(fab_refs) == 1 and fab_refs[0].layer == "F.Fab"
    # контуры: F.SilkS 0.12, F.Fab 0.1, F.CrtYd 0.05
    layers = {g.layer for g in fp.graphics}
    assert {"F.SilkS", "F.Fab", "F.CrtYd"} <= layers
    for g in fp.graphics:
        assert g.width == pytest.approx(_WIDTH[g.layer]), g
        assert g.stroke_type == "solid"
    # courtyard: одна фигура, на сетке 0.01, содержит площадки и F.Fab
    crt = _courtyard(fp)
    cb = crt.bbox()
    inner = fp.bbox(layers=["F.Fab"])
    assert cb.x1 <= inner.x1 + 1e-9 and cb.y1 <= inner.y1 + 1e-9
    assert cb.x2 >= inner.x2 - 1e-9 and cb.y2 >= inner.y2 - 1e-9
    if crt.kind == "rect":
        for v in (*crt.start, *crt.end):
            assert abs(v * 100 - round(v * 100)) < 1e-6, v
    else:
        assert crt.kind == "circle" and name == "capacitor_radial"
    # uuid у всех элементов, все разные
    ids = [n.value("uuid") for n in fp.node.nodes() if n.name in _ELEMENTS]
    assert all(ids) and len(set(ids)) == len(ids)
    # площадки: сквозные, *.Cu *.Mask, площадка 1 одна
    assert all(p.type in ("thru_hole", "np_thru_hole") for p in fp.pads)
    assert all(p.layers == ["*.Cu", "*.Mask"] for p in fp.pads)
    assert len(fp.pads_by_number("1")) == 1
    for p in fp.pads:
        if p.type == "np_thru_hole":
            assert p.number == "" and p.size_x == p.drill.diameter
        assert p.angle == 0


@pytest.mark.parametrize("name,params", VARIANTS, ids=VARIANT_IDS)
def test_generator_dumps_parse_equal(name, params):
    fp = _gen(name, params)
    text = fp.dumps()
    assert text.startswith("(footprint ") and text.endswith(")\n") and "\t" in text
    tree = sexpr.parse(text)
    assert sexpr.equal(tree, fp.node), sexpr.diff(tree, fp.node)
    again = loads(text)
    assert again.dumps() == text
    assert _pads(again) == _pads(fp)


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_generator_is_deterministic(name):
    assert GENERATORS[name]().dumps() == GENERATORS[name]().dumps()


def test_different_params_give_different_uuids():
    a, b = dip(pins=8), dip(pins=10)
    ua = {n.value("uuid") for n in a.node.nodes("pad")}
    ub = {n.value("uuid") for n in b.node.nodes("pad")}
    assert ua != ub


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_generator_save_load(name, tmp_path):
    fp = GENERATORS[name]()
    path = tmp_path / f"{fp.name}.kicad_mod"
    kicadfp.save(fp, path, strict=True)
    back = load(path)
    assert sexpr.equal(back.node, fp.node)


def test_node_order_like_kicad():
    """Порядок записи: поля, attr, фигуры (F.SilkS < F.CrtYd < F.Fab), тексты, площадки
    (монтажные отверстия первыми), embedded_fonts (lab-generators.md §1.2)."""
    fp = pin_header(**B2)
    names = [n.name for n in fp.node.nodes()]
    assert names[:5] == ["version", "generator", "generator_version", "layer", "descr"]
    assert names.index("attr") < names.index("fp_line") < names.index("fp_text") \
        < names.index("pad") < names.index("embedded_fonts")
    assert names[-1] == "embedded_fonts"
    assert [p.number for p in fp.pads][:3] == ["", "", "1"]
    layers = [n.value("layer") for n in fp.node.nodes() if n.name.startswith("fp_")
              and n.name != "fp_text"]
    order = {"F.SilkS": 0, "F.CrtYd": 1, "F.Fab": 2}
    assert layers == sorted(layers, key=order.__getitem__)


# ---------------------------------------------------------------------------------------------
# Лабораторные корпуса (lab-generators.md §2)
# ---------------------------------------------------------------------------------------------

L = ("*.Cu", "*.Mask")


def _tht(n, shape, x, y):
    return (str(n), "thru_hole", shape, x, y, 1.3, 1.3, 0.8, L)


LAB_DIP14_PADS = [_tht(i, "rect" if i == 1 else "circle", -3.75, -7.5 + (i - 1) * 2.5)
                  for i in range(1, 8)] + \
                 [_tht(i, "circle", 3.75, 7.5 - (i - 8) * 2.5) for i in range(8, 15)]

LAB_DIP14_GRAPHICS = {
    ("F.SilkS", "seg", frozenset(((-2.5, -8.75), (-0.75, -8.75)))),
    ("F.SilkS", "seg", frozenset(((0.75, -8.75), (2.5, -8.75)))),
    ("F.SilkS", "seg", frozenset(((2.5, -8.75), (2.5, 8.75)))),
    ("F.SilkS", "seg", frozenset(((2.5, 8.75), (-2.5, 8.75)))),
    ("F.SilkS", "seg", frozenset(((-2.5, 8.75), (-2.5, -8.75)))),
    ("F.SilkS", "arc", frozenset(((0.75, -8.75), (-0.75, -8.75))), (0.0, -8.0)),
}


def test_lab_dip14_exact():
    fp = lab_dip14()
    assert fp.name == "dip14"
    assert _pads(fp) == LAB_DIP14_PADS
    assert _seg_set(fp, {"F.SilkS"}) == LAB_DIP14_GRAPHICS
    fab = [g for g in fp.graphics if g.layer == "F.Fab"]
    assert len(fab) == 1 and fab[0].kind == "rect"
    assert (fab[0].start, fab[0].end) == ((-2.5, -8.75), (2.5, 8.75))
    crt = _courtyard(fp)
    assert crt.kind == "rect" and (crt.start, crt.end) == ((-4.65, -9.0), (4.65, 9.0))
    assert _texts(fp) == {("REF**", 0.0, -10.0, 0.0, "F.SilkS", 1.0, 0.15),
                          ("dip14", 0.0, 0.0, 90.0, "F.Fab", 1.0, 0.15)}
    assert fp.descr == "Корпус К555ТВ6 DIP14" and fp.tags == "dip14 K555TB6"
    # выемка — дуга внутрь корпуса, по часовой стрелке (как KiCad)
    arc = next(g for g in fp.graphics if g.kind == "arc")
    assert arc.mid == (0.0, -8.0) and arc.sweep < 0
    assert C.min_silk_clearance(fp) == pytest.approx(0.54, abs=1e-6)


LAB_MLT_SILK = {
    ("F.SilkS", "seg", frozenset(((-3.75, -1.25), (3.75, -1.25)))),
    ("F.SilkS", "seg", frozenset(((3.75, -1.25), (3.75, 1.25)))),
    ("F.SilkS", "seg", frozenset(((3.75, 1.25), (-3.75, 1.25)))),
    ("F.SilkS", "seg", frozenset(((-3.75, 1.25), (-3.75, -1.25)))),
    ("F.SilkS", "seg", frozenset(((-4.09, 0.0), (-3.75, 0.0)))),
    ("F.SilkS", "seg", frozenset(((3.75, 0.0), (4.09, 0.0)))),
}


def test_lab_mlt_exact():
    fp = lab_mlt()
    assert _pads(fp) == [_tht(1, "rect", -5.0, 0.0), _tht(2, "circle", 5.0, 0.0)]
    assert _seg_set(fp, {"F.SilkS"}) == LAB_MLT_SILK
    assert _seg_set(fp, {"F.Fab"}) == _seg_set(fp, {"F.Fab"}) & _seg_set(fp, {"F.Fab"})
    fab = sorted(((g.kind, g.start, g.end) for g in fp.graphics if g.layer == "F.Fab"))
    assert fab == [("line", (-5.0, 0.0), (-3.75, 0.0)), ("line", (3.75, 0.0), (5.0, 0.0)),
                   ("rect", (-3.75, -1.25), (3.75, 1.25))]
    crt = _courtyard(fp)
    assert (crt.start, crt.end) == ((-5.9, -1.5), (5.9, 1.5))
    assert _texts(fp) == {("REF**", 0.0, -2.5, 0.0, "F.SilkS", 1.0, 0.15),
                          ("mlt", 0.0, 2.5, 0.0, "F.Fab", 1.0, 0.15)}
    assert fp.descr == "Корпус резистора МЛТ" and fp.tags == "mlt resistor"
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6


def test_lab_mlt_full_text_matches_spec():
    """Полный текст lab_mlt() из lab-generators.md §2.4 (без uuid; writer KiCad 9 добавляет
    у сквозных площадок ``(remove_unused_layers no)``)."""
    text = lab_mlt().dumps()
    text = re.sub(r"\n\t+\(uuid \"[0-9a-f-]+\"\)", "", text)
    text = text.replace("\n\t\t(remove_unused_layers no)", "")
    spec = (Path(__file__).parents[1] / "docs" / "dev" / "lab-generators.md").read_text("utf-8")
    m = re.search(r"```\n(\(footprint \"mlt\"\n.*?\n\))\n```", spec, re.S)
    assert m, "в lab-generators.md нет полного текста lab_mlt"
    assert text == m.group(1) + "\n"


def test_lab_mlt_no_clip_is_like_my_lib():
    fp = lab_mlt(clip=False)
    silk = _seg_set(fp, {"F.SilkS"})
    assert ("F.SilkS", "seg", frozenset(((-5.0, 0.0), (-3.75, 0.0)))) in silk
    assert ("F.SilkS", "seg", frozenset(((3.75, 0.0), (5.0, 0.0)))) in silk


LAB_SNP8_PADS = [
    ("", "np_thru_hole", "circle", 8.75, -10.0, 3.0, 3.0, 3.0, L),
    ("", "np_thru_hole", "circle", 8.75, 10.0, 3.0, 3.0, 3.0, L),
    _tht(1, "rect", -2.5, -3.75), _tht(2, "circle", -2.5, -1.25),
    _tht(3, "circle", -2.5, 1.25), _tht(4, "circle", -2.5, 3.75),
    _tht(5, "circle", 2.5, -3.75), _tht(6, "circle", 2.5, -1.25),
    _tht(7, "circle", 2.5, 1.25), _tht(8, "circle", 2.5, 3.75),
]

LAB_SNP8_SILK = {("F.SilkS", "seg", frozenset(s)) for s in (
    ((2.5, -12.5), (15.0, -12.5)), ((15.0, -12.5), (15.0, 12.5)),
    ((15.0, 12.5), (2.5, 12.5)), ((2.5, 12.5), (2.5, 4.66)), ((2.5, 2.84), (2.5, 2.16)),
    ((2.5, 0.34), (2.5, -0.34)), ((2.5, -2.16), (2.5, -2.84)), ((2.5, -4.66), (2.5, -12.5)))}


def test_lab_snp8_exact():
    fp = lab_snp8()
    assert _pads(fp) == LAB_SNP8_PADS
    assert _seg_set(fp, {"F.SilkS"}) == LAB_SNP8_SILK
    fab = [g for g in fp.graphics if g.layer == "F.Fab"]
    assert len(fab) == 1 and (fab[0].start, fab[0].end) == ((2.5, -12.5), (15.0, 12.5))
    crt = _courtyard(fp)
    assert (crt.start, crt.end) == ((-3.65, -13.0), (15.5, 13.0))
    assert _texts(fp) == {("REF**", 8.75, -13.75, 0.0, "F.SilkS", 1.0, 0.15),
                          ("snp8", 8.75, 13.75, 0.0, "F.Fab", 1.0, 0.15)}
    assert fp.descr == "Корпус разъёма СНП 8 контактов с двумя монтажными отверстиями 3 мм"
    assert fp.tags == "snp8 connector"
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6
    # без обрезки левая сторона контура проходит через площадки 5–8
    assert C.min_silk_clearance(lab_snp8(clip=False)) < 0


def test_lab_snp8_numbering_zigzag():
    fp = lab_snp8(numbering="zigzag")
    pos = {p.number: (p.x, p.y) for p in fp.pads if p.number}
    assert pos["1"] == (-2.5, -3.75) and pos["2"] == (2.5, -3.75)
    assert pos["3"] == (-2.5, -1.25) and pos["4"] == (2.5, -1.25)
    assert fp.pad("1").shape == "rect"
    assert lab_snp8(numbering="column").dumps() == fp.dumps()


@pytest.mark.parametrize("gen", [lab_dip14, lab_mlt, lab_snp8])
@pytest.mark.parametrize("origin", ["center", "pin1"])
def test_lab_pads_on_grid_and_first_square(gen, origin):
    fp = gen(origin=origin)
    for p in fp.pads:
        for v in (p.x, p.y):
            assert abs(v / 1.25 - round(v / 1.25)) < 1e-9, (p.number, v)
        if p.type == "thru_hole":
            assert (p.size_x, p.size_y, p.drill.diameter) == (1.3, 1.3, 0.8)
            assert p.shape == ("rect" if p.number == "1" else "circle")
    if origin == "pin1":
        assert (fp.pad("1").x, fp.pad("1").y) == (0.0, 0.0)
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6


def test_lab_pitches():
    d = lab_dip14()
    left = sorted((p for p in d.pads if p.x < 0), key=lambda p: p.y)
    assert all(abs(b.y - a.y - 2.5) < TOL for a, b in zip(left, left[1:]))
    assert d.pad("14").x - d.pad("1").x == pytest.approx(7.5)
    s = lab_snp8()
    assert s.pad("5").x - s.pad("1").x == pytest.approx(5.0)
    m = lab_mlt()
    assert m.pad("2").x - m.pad("1").x == pytest.approx(10.0)


def test_lab_pin1_shift_keeps_geometry():
    a, b = lab_dip14(), lab_dip14(origin="pin1")
    dx, dy = -a.pad("1").x, -a.pad("1").y
    for pa, pb in zip(a.pads, b.pads):
        assert (pb.x, pb.y) == pytest.approx((pa.x + dx, pa.y + dy))
    assert b.reference.y == pytest.approx(a.reference.y + dy)
    assert _courtyard(b).start == pytest.approx((_courtyard(a).start[0] + dx,
                                                 _courtyard(a).start[1] + dy))


def test_lab_snp8_pin1_offset_matches_b2():
    """lab_snp8(origin="pin1", pads_offset_y=-1.25) даёт те же площадки и отверстия, что
    пример В.2 (с точностью до нумерации: у В.2 — zigzag)."""
    lab = lab_snp8(origin="pin1", pads_offset_y=-1.25, numbering="zigzag")
    b2 = pin_header(**B2)
    key = lambda p: (p.number, p.type, round(p.x, 6), round(p.y, 6), p.drill.diameter)  # noqa: E731
    assert sorted(map(key, lab.pads)) == sorted(map(key, b2.pads))
    fab = next(g for g in lab.graphics if g.layer == "F.Fab")
    assert (fab.start, fab.end) == ((5.0, -7.5), (17.5, 17.5))
    holes = [(p.x, p.y) for p in lab_snp8(origin="pin1").pads if p.number == ""]
    assert holes == [(11.25, -6.25), (11.25, 13.75)]


def _parse_my_lib(path: Path) -> dict[str, dict]:
    """Мини-разбор My_lib.mod (деци-милы): площадки и тексты T0/T1 по модулям."""
    mods: dict[str, dict] = {}
    cur = pad = None
    k = 0.00254
    for line in path.read_text("latin-1").splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == "$MODULE":
            cur = mods.setdefault(w[1], {"pads": [], "texts": {}})
        elif cur is None:
            continue
        elif w[0] in ("T0", "T1"):
            cur["texts"][w[0]] = (int(w[1]) * k, int(w[2]) * k, int(w[5]) / 10)
        elif w[0] == "$PAD":
            pad = {}
        elif w[0] == "Sh" and pad is not None:
            pad.update(num=w[1].strip('"'), shape={"R": "rect", "C": "circle"}[w[2]],
                       sx=int(w[3]) * k, sy=int(w[4]) * k)
        elif w[0] == "Dr" and pad is not None:
            pad["drill"] = int(w[1]) * k
        elif w[0] == "At" and pad is not None:
            pad["type"] = {"STD": "thru_hole", "HOLE": "np_thru_hole"}[w[1]]
        elif w[0] == "Po" and pad is not None:
            pad["x"], pad["y"] = int(w[1]) * k, int(w[2]) * k
        elif w[0] == "$EndPAD" and pad is not None:
            cur["pads"].append(pad)
            pad = None
        elif w[0] == "$EndMODULE":
            cur = None
    return mods


@pytest.mark.parametrize("gen", [lab_dip14, lab_mlt, lab_snp8])
def test_lab_matches_my_lib_mod(gen, legacy_mod):
    """Сравнение с корпусами «созданными вручную» (My_lib.mod, ТЗ 8.2): номера, типы,
    формы, координаты, размеры и отверстия площадок, положения Reference/Value — с
    допуском 0.00127 мм (округление до деци-мил)."""
    fp = gen()
    ref = _parse_my_lib(legacy_mod)[fp.name]
    tol = 0.00127 + 1e-9
    mine = sorted(fp.pads, key=lambda p: (p.number, p.x, p.y))
    theirs = sorted(ref["pads"], key=lambda p: (p["num"], p["x"], p["y"]))
    assert len(mine) == len(theirs)
    for p, q in zip(mine, theirs):
        # у отверстий HOLE в .mod номер не пустой — kicadfp пишет "" (KiCad 9 стирает номер)
        assert p.number == ("" if q["type"] == "np_thru_hole" else q["num"])
        assert (p.type, p.shape) == (q["type"], q["shape"])
        for a, b in ((p.x, q["x"]), (p.y, q["y"]), (p.size_x, q["sx"]), (p.size_y, q["sy"]),
                     (p.drill.diameter, q["drill"])):
            assert abs(a - b) <= tol, (p.number, a, b)
    for t, key in ((fp.reference, "T0"), (fp.value, "T1")):
        x, y, ang = ref["texts"][key]
        assert abs(t.x - x) <= tol and abs(t.y - y) <= tol and t.angle == ang


# ---------------------------------------------------------------------------------------------
# Семейства против библиотеки KiCad
# ---------------------------------------------------------------------------------------------

def _pad_xy(fp):
    return sorted((p.number, round(p.x, 6), round(p.y, 6)) for p in fp.pads)


def test_dip14_matches_kicad8(dip14_v8):
    ref = load(dip14_v8)
    fp = dip(14)
    assert fp.name == ref.name == "DIP-14_W7.62mm"
    assert len(fp.pads) == 14
    assert _pad_xy(fp) == _pad_xy(ref)
    assert _pads(fp) == _pads(ref)  # формы rect/oval, 1.6 × 1.6, drill 0.8
    assert _seg_set(fp, {"F.SilkS", "F.Fab"}) == _seg_set(ref, {"F.SilkS", "F.Fab"})
    assert fp.tags == ref.tags
    for kind in ("reference", "value"):
        a, b = getattr(fp, kind), getattr(ref, kind)
        assert (a.x, a.y, a.layer) == (b.x, b.y, b.layer)
    # courtyard — сетка 0.01 (у v8 — 0.05): расхождение не больше 0.05
    rb = ref.bbox(layers=["F.CrtYd"])
    cb = _courtyard(fp).bbox()
    for a, b in zip(cb, rb):
        assert abs(a - b) <= 0.05 + 1e-9
    assert (cb.x1, cb.y1, cb.x2, cb.y2) == (-1.05, -1.52, 8.67, 16.76)
    fab_ref = next(t for t in fp.texts if t.text == "${REFERENCE}")
    assert (fab_ref.x, fab_ref.y, fab_ref.angle) == (3.81, 7.62, 90.0)


def test_dip_b3_example():
    """ТЗ прил. В.3: kicadfp gen dip --pins 14 --pitch 2.5 --row-pitch 7.5."""
    fp = dip(pins=14, pitch=2.5, row_pitch=7.5)
    assert fp.name == "DIP-14_W7.5mm_P2.5mm"
    cb = _courtyard(fp).bbox()
    assert (cb.x1, cb.y1, cb.x2, cb.y2) == (-1.05, -1.5, 8.55, 16.5)
    arc = next(g for g in fp.graphics if g.kind == "arc")
    assert {arc.start, arc.end} == {(4.75, -1.31), (2.75, -1.31)} and arc.mid == (3.75, -0.31)
    assert (fp.reference.x, fp.reference.y) == (3.75, -2.31)
    assert (fp.value.x, fp.value.y) == (3.75, 17.31)
    silk = fp.bbox(layers=["F.SilkS"])
    fab = [g for g in fp.graphics if g.layer == "F.Fab"]
    assert min(min(g.start[0], g.end[0]) for g in fab) == pytest.approx(0.635)
    assert max(max(g.start[0], g.end[0]) for g in fab) == pytest.approx(6.865)
    xs = [x for g in fp.graphics if g.layer == "F.SilkS" and g.kind == "line"
          for x in (g.start[0], g.end[0])]
    assert (min(xs), max(xs)) == (1.16, 6.34)
    assert silk is not None


@pytest.mark.parametrize("rows", [1, 2])
def test_pin_header_matches_kicad8(rows):
    ref = load(FIXTURES / "kicad8" / "Connector_PinHeader_2.54mm.pretty" /
               f"PinHeader_{rows}x04_P2.54mm_Vertical.kicad_mod")
    fp = pin_header(rows, 4)
    assert fp.name == ref.name
    assert fp.descr == ref.descr and fp.tags == ref.tags
    assert _pad_xy(fp) == _pad_xy(ref)
    assert _pads(fp) == _pads(ref)
    assert _seg_set(fp, {"F.SilkS", "F.Fab"}) == _seg_set(ref, {"F.SilkS", "F.Fab"})
    assert _texts(fp) - {t for t in _texts(fp) if t[0] == fp.name} == \
        _texts(ref) - {t for t in _texts(ref) if t[0] == ref.name}
    rb, cb = ref.bbox(layers=["F.CrtYd"]), _courtyard(fp).bbox()
    for a, b in zip(cb, rb):
        assert abs(a - b) <= 0.05 + 1e-9


def test_pin_header_b2_example():
    """Пример ТЗ прил. В.2 — буквально (lab-generators.md §2.5, таблица)."""
    fp = pin_header(rows=2, cols=4, pitch=2.5, row_pitch=5.0, pad_size=1.3, drill=0.8,
                    first_square=True, mounting_holes=[(11.25, -5.0, 3.0), (11.25, 15.0, 3.0)],
                    name="snp8")
    assert fp.name == "snp8"
    got = [(p.number, p.type, p.shape, p.x, p.y) for p in fp.pads]
    assert got == [("", "np_thru_hole", "circle", 11.25, -5.0),
                   ("", "np_thru_hole", "circle", 11.25, 15.0),
                   ("1", "thru_hole", "rect", 0.0, 0.0), ("2", "thru_hole", "oval", 5.0, 0.0),
                   ("3", "thru_hole", "oval", 0.0, 2.5), ("4", "thru_hole", "oval", 5.0, 2.5),
                   ("5", "thru_hole", "oval", 0.0, 5.0), ("6", "thru_hole", "oval", 5.0, 5.0),
                   ("7", "thru_hole", "oval", 0.0, 7.5), ("8", "thru_hole", "oval", 5.0, 7.5)]
    for p in fp.pads:
        if p.number:
            assert (p.size_x, p.size_y, p.drill.diameter) == (1.3, 1.3, 0.8)
        else:
            assert (p.size_x, p.size_y, p.drill.diameter) == (3.0, 3.0, 3.0)
    fab = {("F.Fab", "seg", frozenset(s)) for s in (
        ((0.625, -1.25), (6.25, -1.25)), ((6.25, -1.25), (6.25, 8.75)),
        ((6.25, 8.75), (-1.25, 8.75)), ((-1.25, 8.75), (-1.25, 0.625)),
        ((-1.25, 0.625), (0.625, -1.25)))}
    assert _seg_set(fp, {"F.Fab"}) == fab
    silk = {("F.SilkS", "seg", frozenset(s)) for s in (
        ((-1.31, -1.31), (0, -1.31)), ((-1.31, 0), (-1.31, -1.31)),
        ((-1.31, 1.25), (-1.31, 8.81)), ((-1.31, 1.25), (2.5, 1.25)),
        ((-1.31, 8.81), (6.31, 8.81)), ((2.5, -1.31), (6.31, -1.31)),
        ((2.5, 1.25), (2.5, -1.31)), ((6.31, -1.31), (6.31, 8.81)))}
    assert _seg_set(fp, {"F.SilkS"}) == {(a, b, frozenset((x + 0.0, y + 0.0) for x, y in s))
                                         for a, b, s in silk}
    crt = _courtyard(fp)
    assert (crt.start, crt.end) == ((-1.75, -7.0), (13.25, 17.0))
    assert _texts(fp) == {("REF**", 2.5, -2.31, 0.0, "F.SilkS", 1.0, 0.15),
                          ("snp8", 2.5, 9.81, 0.0, "F.Fab", 1.0, 0.15),
                          ("${REFERENCE}", 2.5, 3.75, 90.0, "F.Fab", 1.0, 0.15)}
    assert C.min_silk_clearance(fp) == pytest.approx(0.54, abs=1e-6)
    # без имени — имя по правилу KiCad с суффиксом ширины
    b2 = dict(B2)
    del b2["name"]
    assert pin_header(**b2).name == "PinHeader_2x04_P2.50mm_Vertical_W5.0mm"


def test_pin_header_numbering():
    zig = {p.number: (p.x, p.y) for p in pin_header(2, 3).pads}
    assert zig == {"1": (0, 0), "2": (2.54, 0), "3": (0, 2.54), "4": (2.54, 2.54),
                   "5": (0, 5.08), "6": (2.54, 5.08)}
    row = {p.number: (p.x, p.y) for p in pin_header(2, 3, numbering="by_row").pads}
    assert row == {"1": (0, 0), "2": (0, 2.54), "3": (0, 5.08), "4": (2.54, 0),
                   "5": (2.54, 2.54), "6": (2.54, 5.08)}
    assert pin_header(2, 3, numbering="row").dumps() == pin_header(2, 3, numbering="by_row").dumps()
    assert pin_header(2, 3, numbering="column").dumps() == pin_header(2, 3).dumps()
    with pytest.raises(ValueError, match="numbering"):
        pin_header(2, 3, numbering="spiral")


def test_pin_header_mounting_hole_clips_silk():
    fp = pin_header(1, 4, mounting_holes=[(0.0, -3.0, 3.0)])
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6
    assert fp.pads[0].number == "" and fp.pads[0].type == "np_thru_hole"
    cb = _courtyard(fp).bbox()
    assert cb.y1 <= -4.5 - 0.5 + 1e-9


def _fixture(*parts):
    return load(FIXTURES.joinpath(*parts))


def test_resistor_matches_kicad8():
    ref = _fixture("kicad8", "Resistor_THT.pretty",
                   "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal.kicad_mod")
    fp = resistor(series="Axial_DIN0207")
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    assert _seg_set(fp, {"F.SilkS", "F.Fab"}) == _seg_set(ref, {"F.SilkS", "F.Fab"})
    assert _texts(fp) == _texts(ref) | set() or \
        {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}
    assert _courtyard(fp).bbox() == ref.bbox(layers=["F.CrtYd"])
    assert resistor().name == "R_Axial_L6.3mm_D2.5mm_P10.16mm_Horizontal"


def test_capacitor_axial_matches_kicad8():
    ref = _fixture("kicad8", "Capacitor_THT.pretty",
                   "C_Axial_L3.8mm_D2.6mm_P7.50mm_Horizontal.kicad_mod")
    fp = capacitor_axial()
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    assert _seg_set(fp, {"F.SilkS", "F.Fab"}) == _seg_set(ref, {"F.SilkS", "F.Fab"})
    assert {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}  # ${REFERENCE} 0.76/0.114


def test_diode_matches_kicad9():
    ref = _fixture("kicad9", "Diode_THT.pretty", "D_DO-35_SOD27_P12.70mm_Horizontal.kicad_mod")
    fp = diode(pitch=12.7)
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    assert _seg_set(fp, {"F.SilkS", "F.Fab"}) == _seg_set(ref, {"F.SilkS", "F.Fab"})
    assert {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}
    assert {t[0] for t in _texts(fp)} >= {"K", "${REFERENCE}", "REF**"}
    no_band = diode(cathode_band=False)
    assert not [t for t in no_band.texts if t.text == "K"]


def test_capacitor_disc_matches_kicad8():
    ref = _fixture("kicad8", "Capacitor_THT.pretty", "C_Disc_D5.0mm_W2.5mm_P5.00mm.kicad_mod")
    fp = capacitor_radial()
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    assert _seg_set(fp, {"F.Fab"}) == _seg_set(ref, {"F.Fab"})
    assert fp.bbox(layers=["F.SilkS"]).width == pytest.approx(ref.bbox(layers=["F.SilkS"]).width)
    assert {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}
    assert _courtyard(fp).bbox() == ref.bbox(layers=["F.CrtYd"])
    # разрывы у площадок: KiCad ±1.055, kicadfp — точное пересечение с зоной (±1.0532)
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6


def test_capacitor_polarized_matches_kicad8():
    ref = _fixture("kicad8", "Capacitor_THT.pretty", "CP_Radial_D5.0mm_P2.50mm.kicad_mod")
    fp = capacitor_radial(pitch=2.5, polarized=True)
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    layers = {"F.SilkS", "F.Fab", "F.CrtYd"}
    assert _seg_set(fp, layers) == _seg_set(ref, layers)  # включая штриховку (88 отрезков)
    assert {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}
    assert _courtyard(fp).kind == "circle"


def test_transistor_matches_kicad9_wide():
    ref = _fixture("kicad9", "Package_TO_SOT_THT.pretty", "TO-92_Inline_Wide.kicad_mod")
    fp = transistor(pitch=2.54)
    assert fp.name == ref.name
    assert _pads(fp) == _pads(ref)
    arcs = lambda f: {x for x in _seg_set(f, {"F.Fab"}) if x[1] == "arc"}  # noqa: E731
    assert arcs(fp) == arcs(ref)
    assert {t[1:] for t in _texts(fp)} == {t[1:] for t in _texts(ref)}
    rb, cb = ref.bbox(layers=["F.CrtYd"]), _courtyard(fp).bbox()
    for a, b in zip(cb, rb):
        assert abs(a - b) <= 0.05 + 1e-9
    assert C.min_silk_clearance(fp) >= 0.2 - 1e-6


def test_transistor_inline_narrow():
    fp = transistor_inline()
    assert fp.name == "TO-92_Inline"
    assert [(p.number, p.shape, p.x, p.size_x, p.size_y, p.drill.diameter) for p in fp.pads] == [
        ("1", "rect", 0.0, 1.05, 1.5, 0.75), ("2", "oval", 1.27, 1.05, 1.5, 0.75),
        ("3", "oval", 2.54, 1.05, 1.5, 0.75)]
    silk_arcs = {x for x in _seg_set(fp, {"F.SilkS"}, nd=6) if x[1] == "arc"}
    assert ("F.SilkS", "arc", frozenset(((-0.568478, 1.838478), (1.27, -2.6))),
            (-1.132087, -0.994977)) in silk_arcs
    cb = _courtyard(fp).bbox()
    assert (cb.x1, cb.y1, cb.x2, cb.y2) == (-1.46, -2.73, 4.0, 2.01)
    assert (fp.reference.y, fp.value.y) == (-3.56, 2.79)


# ---------------------------------------------------------------------------------------------
# Ошибки параметров
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda: dip(pins=7),
    lambda: dip(pins=0),
    lambda: dip(pitch=-1),
    lambda: dip(pad_size=0.5, drill=0.8),
    lambda: dip(pad_shape="hexagon"),
    lambda: pin_header(rows=0),
    lambda: pin_header(mounting_holes=[(1, 2)]),
    lambda: resistor(drill=0),
    lambda: capacitor_radial(diameter=-5),
    lambda: transistor(pins=1),
    lambda: lab_dip14(origin="corner"),
    lambda: lab_mlt(body_length=12),
    lambda: lab_snp8(numbering="spiral"),
])
def test_bad_parameters(call):
    with pytest.raises(ValueError):
        call()


# ---------------------------------------------------------------------------------------------
# Реестр, describe, from_json
# ---------------------------------------------------------------------------------------------

def test_registry_names():
    assert set(GENERATORS) == {"dip", "pin_header", "resistor", "capacitor_radial",
                               "capacitor_axial", "diode", "transistor", "lab_dip14",
                               "lab_mlt", "lab_snp8"}
    assert G.get("transistor_inline") is transistor
    assert G.get("Pin-Header") is pin_header
    with pytest.raises(KeyError, match="неизвестный генератор"):
        G.get("qfn")


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_describe(name):
    params = describe(name)
    assert params
    for p in params:
        assert isinstance(p, G.ParamInfo)
        assert p.description, (name, p.name)
        assert p.type
    names = [p.name for p in params]
    assert "name" in names
    assert G.summary(name)


def test_describe_values():
    d = {p.name: p for p in describe("dip")}
    assert d["pins"].type == "int" and d["pins"].default == 14
    assert d["pad_size"].default == (1.6, 1.6)
    assert "float" in d["pad_size"].type and "tuple" in d["pad_size"].type
    assert d["body_width"].default is None
    assert "чётное" in d["pins"].description
    ph = {p.name: p for p in describe("pin_header")}
    assert ph["numbering"].default == "zigzag"
    assert "list" in ph["mounting_holes"].type


def test_from_json_b2():
    params = json.loads(json.dumps(B2))  # кортежи -> списки, как из файла JSON
    fp = from_json("pin_header", params)
    assert fp.dumps() == pin_header(**B2).dumps()
    assert from_json("pin_header", json.dumps(params)).dumps() == fp.dumps()


def test_from_json_variants():
    assert from_json("dip").dumps() == dip().dumps()
    assert from_json("dip", {}).dumps() == dip().dumps()
    fp = from_json("dip", {"pins": "8", "row-pitch": "7,62", "pad_size": [2.4, 1.6],
                           "first_square": "false"})
    assert fp.dumps() == dip(pins=8, pad_size=(2.4, 1.6), first_square=False).dumps()
    assert from_json("transistor_inline", {"pitch": 2.54}).name == "TO-92_Inline_Wide"
    assert from_json("lab_snp8", {"pads_offset_y": -1.25}).pad("1").y == -5.0
    with pytest.raises(KeyError):
        from_json("nope", {})
    with pytest.raises(ValueError, match="не имеет параметра"):
        from_json("dip", {"legs": 4})
    with pytest.raises(ValueError):
        from_json("dip", {"pins": "много"})
    with pytest.raises(ValueError):
        from_json("dip", {"pins": 14.5})
    with pytest.raises(ValueError, match="JSON"):
        from_json("dip", "{pins: 14")
    with pytest.raises(ValueError, match="объект"):
        from_json("dip", "[1, 2]")


def test_coerce_param():
    cp = G.coerce_param
    assert cp("dip", "pad_size", "1.6x2.4") == (1.6, 2.4)
    assert cp("dip", "pad-size", "1.6,2.4") == (1.6, 2.4)
    assert cp("dip", "pad_size", "[1.6, 2.4]") == (1.6, 2.4)
    assert cp("dip", "pad_size", "1.8") == 1.8
    assert cp("dip", "pad_size", [1.8]) == 1.8
    assert cp("dip", "first_square", "no") is False
    assert cp("dip", "first_square", "Да") is True
    assert cp("dip", "body_width", "none") is None
    assert cp("dip", "pins", 14.0) == 14 and isinstance(cp("dip", "pins", 14.0), int)
    assert cp("dip", "name", "X") == "X"
    assert cp("pin_header", "mounting_holes", "[[1, 2, 3]]") == [(1.0, 2.0, 3.0)]
    assert cp("pin_header", "mounting_holes", [[1, 2, 3], "4,5,6"]) == [(1.0, 2.0, 3.0),
                                                                        (4.0, 5.0, 6.0)]
    with pytest.raises(ValueError):
        cp("dip", "pins", None)
    with pytest.raises(ValueError):
        cp("dip", "first_square", "maybe")
    with pytest.raises(ValueError):
        cp("pin_header", "mounting_holes", [[1, 2]])
    with pytest.raises(ValueError):
        cp("dip", "pad_size", [1, 2, 3])


# ---------------------------------------------------------------------------------------------
# Вспомогательная геометрия _common
# ---------------------------------------------------------------------------------------------

def test_grid_rounding():
    assert C.floor_grid(-1.05) == -1.05 and C.ceil_grid(16.76) == 16.76
    assert C.floor_grid(-1.0500000001) == -1.05
    assert C.ceil_grid(2.0036) == 2.01 and C.floor_grid(-2.0036) == -2.01
    assert C.num(7.5) == "7.5" and C.num(10.0) == "10" and C.num(-0.0) == "0"


def test_clip_segment():
    zones = [C.Zone("circle", 0.0, 0.0, 1.0)]
    assert C.clip_segment((-3, 0), (3, 0), zones) == [((-3, 0), (-1.0, 0.0)), ((1.0, 0.0), (3, 0))]
    assert C.clip_segment((-3, 2), (3, 2), zones) == [((-3, 2), (3, 2))]
    # касание границы — не обрезка
    assert C.clip_segment((-3, 1), (3, 1), zones) == [((-3, 1), (3, 1))]
    # короткий остаток отбрасывается
    assert C.clip_segment((-1.1, 0), (0, 0), zones) == []
    rz = [C.Zone("rect", -1, -1, 1, 1)]
    assert C.clip_segment((0, -3), (0, 3), rz) == [((0, -3), (0.0, -1.0)), ((0.0, 1.0), (0, 3))]
    assert C.clip_segment((1, -3), (1, 3), rz) == [((1, -3), (1, 3))]


def test_clip_circle_and_arc():
    zones = [C.Zone("circle", 2.0, 0.0, 0.5)]
    assert C.clip_circle((0, 0), 1.0, zones) is None
    arcs = C.clip_circle((0, 0), 2.0, zones)
    assert len(arcs) == 1
    s, m, e = arcs[0]
    assert m == pytest.approx((-2.0, 0.0), abs=1e-6)
    for p in (s, e):
        assert math.hypot(p[0] - 2, p[1]) == pytest.approx(0.5, abs=1e-6)
    assert C.clip_circle((0, 0), 0.2, [C.Zone("circle", 0, 0, 1)]) == []
    # дуга (полуокружность снизу), разрезанная в середине
    pieces = C.clip_arc((-2, 0), (0, 2), (2, 0), [C.Zone("rect", -0.5, 1.5, 0.5, 2.5)])
    assert len(pieces) == 2
    ends = sorted(p for piece in pieces for p in (piece[0], piece[2]))
    assert ends[0] == pytest.approx((-2, 0)) and ends[-1] == pytest.approx((2, 0))


def test_fab_reference_size():
    assert C.fab_reference_size(6.3, 2.5) == (1.0, 0.15)
    assert C.fab_reference_size(4.0, 2.0) == (0.8, 0.12)
    assert C.fab_reference_size(3.8, 2.6) == (0.76, 0.114)
    assert C.fab_reference_size(1.0, 0.2) == (0.25, 0.0375)


# ---------------------------------------------------------------------------------------------
# KiCad читает результат
# ---------------------------------------------------------------------------------------------

@pytest.mark.kicad_cli
def test_kicad_cli_reads_generated(kicad_cli, tmp_path):
    lib = tmp_path / "gen.pretty"
    lib.mkdir()
    made = {}
    for i, (name, params) in enumerate(VARIANTS):
        fp = _gen(name, params)
        fname = f"{i:02d}_{fp.name}"
        kicadfp.save(fp, lib / f"{fname}.kicad_mod")
        made[fname] = fp
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", "--force", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    assert "Unable" not in r.stderr and "rror" not in r.stderr, r.stderr
    for fname, fp in made.items():
        back = load(out / f"{fname}.kicad_mod")
        # KiCad добавляет служебные поля и меняет генератор; остальное — без изменений
        for k in ("Datasheet", "Description"):
            if k in back.properties:
                del back.properties[k]
        back.generator = "kicadfp"
        back.generator_version = fp.generator_version
        back.name = fp.name
        assert sexpr.equal(back.node, fp.node), (fname, sexpr.diff(back.node, fp.node)[:5])


@pytest.mark.kicad_cli
def test_kicad_cli_exports_svg(kicad_cli, tmp_path):
    lib = tmp_path / "lab.pretty"
    lib.mkdir()
    for gen in (lab_dip14, lab_mlt, lab_snp8):
        fp = gen()
        kicadfp.save(fp, lib / f"{fp.name}.kicad_mod")
    for name in ("dip14", "mlt", "snp8"):
        out = tmp_path / f"svg_{name}"
        r = subprocess.run([kicad_cli, "fp", "export", "svg", str(lib), "--fp", name, "-o",
                            str(out)], capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr
        assert list(out.glob("*.svg")), r.stdout + r.stderr


def test_fallback_sort_orders_pads_and_layers():
    """Запасной порядок (без закрытого помощника модели): площадки по номеру (пустой —
    первым), фигуры по слою и виду."""
    fp = pin_header(**B2)
    items = fp.node.items
    idx = [i for i, x in enumerate(items) if isinstance(x, sexpr.Node)
           and (x.name == "pad" or x.name.startswith("fp_"))]
    nodes = [items[i] for i in idx][::-1]
    for i, n in zip(idx, nodes):
        items[i] = n
    C._fallback_sort(fp.node)
    assert [p.number for p in fp.pads] == ["", "", "1", "2", "3", "4", "5", "6", "7", "8"]
    order = {"F.SilkS": 0, "F.CrtYd": 1, "F.Fab": 2}
    layers = [n.value("layer") for n in fp.node.nodes() if n.name.startswith("fp_")
              and n.name != "fp_text"]
    assert layers == sorted(layers, key=order.__getitem__)
    assert C._strnum_key("10") > C._strnum_key("9") > C._strnum_key("")
