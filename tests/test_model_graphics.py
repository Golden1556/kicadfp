"""Тесты графики :mod:`kicadfp.model`: Line, Rect, Circle, Arc, Poly, Curve."""

from __future__ import annotations

import math

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import profile_for
from kicadfp.geometry import BBox
from kicadfp.model import Arc, Circle, Curve, Graphic, Line, Poly, Rect, view_for
from tests.conftest import FIXTURES
from tests.test_model_common import assert_one_token_changed, changed_lines, load_dip, tree_changes

P5 = profile_for(None, "module")
P6 = profile_for(20211014)
P7 = profile_for(20221018)
P8 = profile_for(20240108)
P9 = profile_for(20241229)


def _g(text: str, profile=P9) -> Graphic:
    return view_for(sexpr.parse(text), profile)  # type: ignore[return-value]


def _c(view) -> str:
    return sexpr.to_compact(view.node)


# ---------------------------------------------------------------------------
# Чтение из фикстур
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_read_dip14_arc_all_versions(version):
    fp = load_dip(version)
    (arc,) = [g for g in fp.graphics if g.kind == "arc"]
    assert isinstance(arc, Arc)
    assert (arc.start, arc.mid, arc.end) == ((4.81, -1.33), (3.81, -0.33), (2.81, -1.33))
    assert arc.center == (3.81, -1.33) and arc.radius == 1.0
    assert arc.sweep == pytest.approx(-180.0)
    assert arc.start_angle == pytest.approx(0.0) and arc.end_angle == pytest.approx(180.0)
    assert arc.is_legacy == (version == "kicad5")
    assert (arc.layer, arc.width, arc.fill) == ("F.SilkS", 0.12, False)
    assert arc.stroke_type == (None if version in ("kicad5", "kicad6") else "solid")
    assert arc.bbox() == BBox(2.81, -1.33, 4.81, -0.33)
    assert arc.length() == pytest.approx(math.pi)
    assert arc.points == [(4.81, -1.33), (3.81, -0.33), (2.81, -1.33)]


def test_read_dip14_lines():
    fp = load_dip("kicad8")
    line = fp.graphics[0]
    assert isinstance(line, Line) and line.kind == "line" and not line.is_primitive
    assert (line.start, line.end) == ((1.16, -1.33), (1.16, 16.57))
    assert (line.start_x, line.start_y, line.end_x, line.end_y) == (1.16, -1.33, 1.16, 16.57)
    assert line.length() == pytest.approx(17.9)
    assert (line.layer, line.layers, line.width, line.stroke_type) == ("F.SilkS", ["F.SilkS"], 0.12, "solid")
    assert line.uuid == "27ea462e-c99b-4ceb-9ed7-3dc77d037ea8" and line.locked is False
    assert line.bbox() == BBox(1.16, -1.33, 1.16, 16.57)
    assert line.bbox(with_width=True) == BBox(1.1, -1.39, 1.22, 16.63)
    assert repr(line).startswith("Line(layer='F.SilkS'")
    l5 = load_dip("kicad5").graphics[1]
    assert (l5.start, l5.end, l5.width, l5.uuid) == ((1.635, -1.27), (6.985, -1.27), 0.1, None)


def test_read_circle_and_poly_fixtures():
    fp = kicadfp.load(FIXTURES / "kicad8" / "Capacitor_THT.pretty" / "CP_Radial_D10.0mm_P2.50mm.kicad_mod")
    circles = [g for g in fp.graphics if g.kind == "circle"]
    silk = [c for c in circles if c.layer == "F.SilkS"][0]
    assert isinstance(silk, Circle)
    assert (silk.center, silk.end, silk.radius, silk.fill) == ((1.25, 0.0), (6.37, 0.0), 5.12, False)
    assert silk.bbox() == BBox(-3.87, -5.12, 6.37, 5.12)
    assert silk.length() == pytest.approx(2 * math.pi * 5.12)
    fp5 = kicadfp.load(FIXTURES / "kicad5" / "Capacitor_THT.pretty" / "CP_Radial_D10.0mm_P2.50mm_P5.00mm.kicad_mod")
    c5 = [g for g in fp5.graphics if g.kind == "circle"][0]
    assert c5.node.find("fill") is None and c5.fill is False     # ширина > 0 -> не залита
    fps = kicadfp.load(FIXTURES / "kicad8" / "Package_SO.pretty" / "Diodes_PSOP-8.kicad_mod")
    poly = [g for g in fps.graphics if g.kind == "poly"][0]
    assert isinstance(poly, Poly) and poly.fill is True
    assert poly.points == [(-2.7, -2.5), (-2.94, -2.83), (-2.46, -2.83), (-2.7, -2.5)]
    assert poly.bbox() == BBox(-2.94, -2.83, -2.46, -2.5)


@pytest.mark.parametrize("text,expected", [
    ('(fp_rect (start 0 0) (end 1 1) (fill yes) (layer "F.SilkS"))', True),
    ('(fp_rect (start 0 0) (end 1 1) (fill solid) (layer "F.SilkS"))', True),
    ('(fp_rect (start 0 0) (end 1 1) (fill no) (layer "F.SilkS"))', False),
    ('(fp_rect (start 0 0) (end 1 1) (fill none) (layer "F.SilkS"))', False),
    ('(fp_rect (start 0 0) (end 1 1) (fill) (layer "F.SilkS"))', False),
    ('(fp_rect (start 0 0) (end 1 1) (fill none solid) (layer "F.SilkS"))', True),
    ('(fp_rect (start 0 0) (end 1 1) (fill hatch) (layer "F.SilkS"))', True),
    # без (fill): правило парсера KiCad
    ('(fp_rect (start 0 0) (end 1 1) (layer "F.SilkS") (width 0))', True),
    ('(fp_rect (start 0 0) (end 1 1) (layer "F.SilkS") (width 0.1))', False),
    ('(fp_circle (center 0 0) (end 1 0) (layer "F.SilkS"))', True),
    ('(fp_circle (center 0 0) (end 1 0) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))', False),
    ('(fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (layer "F.SilkS") (width 0.1))', True),
    ('(fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (layer "Edge.Cuts") (width 0.1))', False),
    ('(fp_line (start 0 0) (end 1 1) (layer "F.SilkS"))', False),
    ('(gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (width 0))', True),
])
def test_fill_read_forms(text, expected):
    assert _g(text).fill is expected


# ---------------------------------------------------------------------------
# Запись: форма по версии, ровно один токен
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile,true_word,false_word", [
    (P6, "solid", "none"), (P7, "solid", "none"), (P8, "solid", "none"), (P9, "yes", "no"),
])
def test_fill_write_by_profile(profile, true_word, false_word):
    r = Rect.new((0, 0), (1, 1), profile=profile, uuid=False)
    assert r.node.value("fill") == false_word
    r.fill = True
    assert r.node.value("fill") == true_word and r.fill
    r.fill = False
    assert r.node.value("fill") == false_word


@pytest.mark.parametrize("profile,false_word", [(P6, "none"), (P8, "no"), (P9, "no")])
def test_fill_write_primitives(profile, false_word):
    p = Poly.new([(0, 0), (1, 0), (1, 1)], width=0, fill=True, profile=profile, primitive=True)
    assert p.node.value("fill") == "yes"
    p.fill = False
    assert p.node.value("fill") == false_word


def test_fill_on_line_arc_curve():
    line = Line.new((0, 0), (1, 1))
    with pytest.raises(ValueError):
        line.fill = True
    line.fill = False                              # нет заливки — ничего не меняется
    assert line.node.find("fill") is None


@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
@pytest.mark.parametrize("attr,value", [
    ("width", 0.2), ("layer", "B.Fab"), ("start", (1.2, -1.4)), ("end", (6.0, 16.0)),
    ("start_x", 1.0), ("end_y", 16.0), ("locked", True),
])
def test_line_setter_changes_one_token(version, attr, value):
    fp = load_dip(version)
    line = [g for g in fp.graphics if g.kind == "line"][0]
    before = fp.node.copy()
    text_before = fp.dumps()
    if attr == "locked" and version == "kicad5":
        # блокировки фигур в KiCad 5 (module) нет
        with pytest.raises(ValueError, match="upgrade"):
            setattr(line, attr, value)
        assert fp.dumps() == text_before
        return
    setattr(line, attr, value)
    assert_one_token_changed(before, fp.node)
    assert getattr(line, attr) == value
    if version in ("kicad8", "kicad9"):
        removed, added = changed_lines(text_before, fp.dumps())
        assert len(removed) <= 1 and len(added) == 1, (removed, added)


@pytest.mark.parametrize("version,prefix", [
    ("kicad5", "(fp_line(start 1.635 -1.27)(end 6.985 -1.27)(layer F.Fab)(width 0.2))"),
    ("kicad6", '(fp_line(start 1.16 -1.33)(end 1.16 16.57)(layer "F.SilkS")(width 0.2)'),
    ("kicad8", '(fp_line(start 1.16 -1.33)(end 1.16 16.57)(stroke(width 0.2)(type solid))'),
])
def test_width_setter_uses_existing_token(version, prefix):
    line = [g for g in load_dip(version).graphics if g.kind == "line"][0]
    line.width = 0.2
    assert _c(line).startswith(prefix)


def test_width_created_by_profile_when_missing():
    g9 = _g('(fp_line (start 0 0) (end 1 1) (layer "F.SilkS"))', P9)
    g9.width = 0.15
    assert _c(g9) == '(fp_line(start 0 0)(end 1 1)(stroke(width 0.15)(type solid))(layer "F.SilkS"))'
    g6 = _g('(fp_line (start 0 0) (end 1 1) (layer "F.SilkS"))', P6)
    g6.width = 0.15
    assert _c(g6) == '(fp_line(start 0 0)(end 1 1)(layer "F.SilkS")(width 0.15))'
    prim = _g("(gr_line (start 0 0) (end 1 1))", P9)
    prim.width = 0.2
    assert _c(prim) == "(gr_line(start 0 0)(end 1 1)(width 0.2))"
    g9.width = None
    assert g9.width is None


def test_stroke_type():
    line = load_dip("kicad8").graphics[0]
    line.stroke_type = "dash"
    assert line.node.find("stroke").value("type") == "dash" and line.stroke_type == "dash"
    with pytest.raises(ValueError):
        line.stroke_type = "wavy"
    line.stroke_type = None
    assert line.node.find("stroke").find("type") is None
    l6 = load_dip("kicad6").graphics[0]
    with pytest.raises(ValueError):
        l6.stroke_type = "dash"                    # в KiCad 6 у графики нет stroke
    mixed = _g('(fp_line (start 0 0) (end 1 1) (layer "F.SilkS") (width 0.1))', P9)
    mixed.stroke_type = "dot"                      # (width) -> (stroke …) в файле 7+
    assert _c(mixed) == '(fp_line(start 0 0)(end 1 1)(stroke(width 0.1)(type dot))(layer "F.SilkS"))'


@pytest.mark.parametrize("profile,expected", [
    (P6, '(fp_line locked(start 0 0)(end 1 1)'),
    (P7, '(fp_line locked(start 0 0)(end 1 1)'),
    (P8, '(fp_line(start 0 0)(end 1 1)(locked yes)(stroke'),
    (P9, '(fp_line(start 0 0)(end 1 1)(stroke(width 0.12)(type solid))(locked yes)(layer'),
])
def test_locked_forms(profile, expected):
    line = Line.new((0, 0), (1, 1), profile=profile, locked=True, uuid=False)
    assert _c(line).startswith(expected) and line.locked
    line.locked = False
    assert "locked" not in _c(line)


def test_layer_setter_quoting_and_layers_form():
    l5 = load_dip("kicad5").graphics[1]
    l5.layer = "B.Fab"
    assert l5.node.find("layer").atoms() == ["B.Fab"] and _c(l5).count('"') == 0
    g = _g('(fp_rect (start 0 0) (end 1 1) (stroke (width 0.1) (type solid)) (fill yes) '
           '(layers "F.Cu" "F.Mask") (uuid "u"))')
    assert g.layer == "F.Cu" and g.layers == ["F.Cu", "F.Mask"]
    g.layer = "F.Cu"
    assert g.node.find("layers") is None and g.layers == ["F.Cu"]
    names = [n.name for n in g.node.nodes()]
    assert names.index("layer") == names.index("fill") + 1


# ---------------------------------------------------------------------------
# Дуги
# ---------------------------------------------------------------------------

def test_arc_modern_setter_changes_only_its_point():
    fp = load_dip("kicad8")
    arc = [g for g in fp.graphics if g.kind == "arc"][0]
    before = fp.node.copy()
    arc.mid = (3.81, -2.33)
    assert tree_changes(before, fp.node) == ["footprint/fp_arc/mid: Y:-0.33 -> Y:-2.33"]
    assert arc.sweep == pytest.approx(180.0)


def test_arc_legacy_node_in_module_stays_legacy():
    fp = load_dip("kicad5")
    arc = [g for g in fp.graphics if g.kind == "arc"][0]
    before = fp.node.copy()
    arc.start = (4.81, -1.33)                      # то же значение — токены не меняются
    assert tree_changes(before, fp.node) == []
    arc.end = (3.81, -2.33)            # прежняя mid (внизу) -> дуга на 270° по часовой
    assert arc.is_legacy and fp.node.find("fp_arc").find("mid") is None
    assert arc.end == (3.81, -2.33) and arc.center == (3.81, -1.33)
    assert (arc.start, arc.mid) == ((4.81, -1.33), pytest.approx((3.102893, -0.622893), abs=1e-6))
    assert arc.sweep == pytest.approx(-270.0)
    # кодировка (ЦЕНТР, КОНЕЦ, sweep) сохраняет знак угла узла: меняются только end и angle
    assert tree_changes(before, fp.node) == ["module/fp_arc/end: Y:2.81 -> Y:3.81",
                                             "module/fp_arc/end: Y:-1.33 -> Y:-2.33",
                                             "module/fp_arc/angle: Y:-180.000000 -> Y:-270"]


def test_arc_legacy_node_in_modern_file_is_converted():
    arc = _g('(fp_arc (start 3.81 -1.33) (end 2.81 -1.33) (angle -180) (layer "F.SilkS") (width 0.12))', P9)
    assert arc.is_legacy and arc.start == (4.81, -1.33)
    before = _c(arc)
    arc.end = arc.end                  # без изменения точки узел не перестраивается
    assert arc.is_legacy and _c(arc) == before
    arc.set_points(arc.start, arc.mid, arc.end)
    assert arc.is_legacy and _c(arc) == before
    arc.end = (2.81, -1.34)
    assert not arc.is_legacy
    # mid — истинная середина новой дуги (как пишет KiCad), а не прежняя точка
    assert _c(arc) == ('(fp_arc(start 4.81 -1.33)(mid 3.804975 -0.330012)(end 2.81 -1.34)'
                       '(layer "F.SilkS")'
                       '(width 0.12))')


def test_arc_new_forms_and_from_center():
    a9 = Arc.new((1, 0), (0, -1), (-1, 0), uuid=False)
    assert _c(a9) == ('(fp_arc(start 1 0)(mid 0 -1)(end -1 0)(stroke(width 0.12)(type solid))'
                      '(layer "F.SilkS"))')
    a5 = Arc.new((1, 0), (0, 1), (-1, 0), profile=P5)
    assert _c(a5) == "(fp_arc(start 0 0)(end 1 0)(angle 180)(layer F.SilkS)(width 0.12))"
    assert (a5.start, a5.mid, a5.end) == ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0))
    fc = Arc.from_center((0, 0), (1, 0), 90, uuid=False)
    assert (fc.start, fc.end) == ((1.0, 0.0), (0.0, -1.0)) and fc.sweep == pytest.approx(90)
    assert fc.mid == pytest.approx((0.707107, -0.707107), abs=1e-6)
    fc.set_points((1, 0), (0, 1), (-1, 0))
    assert fc.sweep == pytest.approx(-180)


def test_arc_mirror_legacy_negates_angle():
    arc = _g('(fp_arc (start 0 0) (end 1 0) (angle 90) (layer F.SilkS) (width 0.1))', P5)
    s, m, e = arc.start, arc.mid, arc.end
    arc.mirror("x", 0.0)
    assert arc.node.find("angle").atoms() == ["-90"]
    # KiCad хранит дуги в одном направлении обхода: после отражения концы меняются местами
    assert {arc.start, arc.end} == {(-s[0], s[1]), (-e[0], e[1])}
    assert arc.mid == pytest.approx((-m[0], m[1]), abs=1e-6)


# ---------------------------------------------------------------------------
# Прямоугольник, окружность, многоугольник, кривая
# ---------------------------------------------------------------------------

def test_rect_geometry_and_rotation():
    r = Rect.new((0, 0), (2, 1), "F.CrtYd", 0.05, uuid=False)
    assert r.points == [(0, 0), (2, 0), (2, 1), (0, 1)] and r.length() == 6
    r.rotate(90)
    assert isinstance(r, Rect) and (r.start, r.end) == ((0, 0), (1, -2))
    r.rotate(45)
    assert isinstance(r, Poly) and r.node.name == "fp_poly"
    assert len(r.points) == 4 and r.fill is False
    assert _c(r).startswith("(fp_poly(pts(xy 0 0)(xy 0.707107 -0.707107)")


def test_circle_radius_setter_and_new():
    c = Circle.new((1, 1), 2, "F.Fab", 0.1, uuid=False)
    assert _c(c) == '(fp_circle(center 1 1)(end 3 1)(stroke(width 0.1)(type solid))(fill no)(layer "F.Fab"))'
    c.end = (1, 4)
    assert c.radius == 3
    c.radius = 1.5                                 # направление сохраняется
    assert c.end == (1, 2.5)
    c.move(-1, -1)
    assert (c.center, c.end) == ((0, 0), (0, 1.5))
    assert c.bbox() == BBox(-1.5, -1.5, 1.5, 1.5)
    c.center = (1, 0)                              # end не меняется
    assert c.radius == pytest.approx(math.hypot(1, 1.5))
    c6 = Circle.new((0, 0), end=(1, 0), profile=P6, uuid=False, fill=True)
    assert _c(c6) == '(fp_circle(center 0 0)(end 1 0)(layer "F.SilkS")(width 0.12)(fill solid))'
    with pytest.raises(TypeError):
        Circle.new((0, 0))


def test_poly_points_setter_and_arcs_in_pts():
    p = _g('(fp_poly (pts (xy 0 0) (arc (start 1 0) (mid 2 1) (end 1 2)) (xy 0 2)) '
           '(stroke (width 0.1) (type solid)) (fill no) (layer "F.SilkS") (uuid "u"))')
    assert p.points == [(0, 0), (1, 0), (2, 1), (1, 2), (0, 2)]
    assert p.bbox() == BBox(0, 0, 2, 2)
    assert p.length() == pytest.approx(1 + math.pi + 1 + 2)
    p.move(1, 1)                                   # дуга внутри pts сохраняется
    assert "(arc(start 2 1)(mid 3 2)(end 2 3))" in _c(p)
    p.points = [(0, 0), (3, 0), (3, 3)]
    assert sexpr.to_compact(p.node.find("pts")) == "(pts(xy 0 0)(xy 3 0)(xy 3 3))"
    assert p.points() == [(0, 0), (3, 0), (3, 3)]


def test_curve():
    c = Curve.new([(0, 0), (0, 1), (1, 1), (1, 0)], uuid=False)
    assert _c(c).startswith("(fp_curve(pts(xy 0 0)(xy 0 1)(xy 1 1)(xy 1 0))(stroke")
    assert c.points == [(0, 0), (0, 1), (1, 1), (1, 0)]
    b = c.bbox()
    assert (b.x1, b.x2, b.y1) == (0, 1, 0) and b.y2 == pytest.approx(0.75, abs=1e-3)
    assert c.length() == pytest.approx(2.0, abs=0.01)
    c.points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert c.length() == pytest.approx(3.0)
    with pytest.raises(ValueError):
        c.points = [(0, 0), (1, 1)]
    with pytest.raises(ValueError):
        Curve.new([(0, 0)])


def test_new_graphics_by_profile():
    assert _c(Line.new((0, 0), (1, 1), profile=P5)) == "(fp_line(start 0 0)(end 1 1)(layer F.SilkS)(width 0.12))"
    l6 = Line.new((0, 0), (1, 1), profile=P6, uuid="abc")
    assert _c(l6) == '(fp_line(start 0 0)(end 1 1)(layer "F.SilkS")(width 0.12)(tstamp abc))'
    l7 = Line.new((0, 0), (1, 1), profile=P7, uuid="abc")
    assert _c(l7) == '(fp_line(start 0 0)(end 1 1)(stroke(width 0.12)(type solid))(layer "F.SilkS")(tstamp abc))'
    l9 = Line.new((0, 0), (1, 1), "F.Fab", 0.1, stroke_type="dash", uuid="abc")
    assert _c(l9) == '(fp_line(start 0 0)(end 1 1)(stroke(width 0.1)(type dash))(layer "F.Fab")(uuid "abc"))'
    # KiCad 5 (module): fp_rect нет, заливка — только умолчание парсера (fp_poly залит)
    with pytest.raises(ValueError, match="fp_rect"):
        Rect.new((0, 0), (1, 1), profile=P5)
    assert _c(Poly.new([(0, 0), (1, 0), (1, 1)], profile=P5)) == \
        "(fp_poly(pts(xy 0 0)(xy 1 0)(xy 1 1))(layer F.SilkS)(width 0.12))"
    assert _c(Poly.new([(0, 0), (1, 0), (1, 1)], profile=P5, fill=True)) == \
        "(fp_poly(pts(xy 0 0)(xy 1 0)(xy 1 1))(layer F.SilkS)(width 0.12))"
    with pytest.raises(ValueError, match="fill"):
        Poly.new([(0, 0), (1, 0), (1, 1)], profile=P5, fill=False)
    with pytest.raises(ValueError, match="fill"):
        Circle.new((0, 0), 1, profile=P5, fill=True)
    assert _c(Poly.new([(0, 0), (1, 0), (1, 1)], profile=P6, uuid=False)) == \
        '(fp_poly(pts(xy 0 0)(xy 1 0)(xy 1 1))(layer "F.SilkS")(width 0.12)(fill none))'
    assert _c(Line.new((0, 0), (1, 1), primitive=True, width=0.2)) == "(gr_line(start 0 0)(end 1 1)(width 0.2))"
    with pytest.raises(TypeError):
        Line.new((0, 0), 1)                       # type: ignore[arg-type]


def test_move_rotate_mirror_all_kinds():
    shapes = [
        Line.new((0, 0), (1, 0), uuid=False),
        Circle.new((1, 1), 1, uuid=False),
        Arc.new((1, 0), (0, -1), (-1, 0), uuid=False),
        Poly.new([(0, 0), (1, 0), (1, 1)], uuid=False),
        Curve.new([(0, 0), (0, 1), (1, 1), (1, 0)], uuid=False),
    ]
    for g in shapes:
        pts = list(g.points)
        g.move(1, 2)
        assert list(g.points) == [(x + 1, y + 2) for x, y in pts]
        g.move(-1, -2)
        g.rotate(90)
        assert list(g.points) == pytest.approx([(y, -x) for x, y in pts], abs=1e-6)
        g.rotate(-90)
        g.mirror("x", 1.0)
        assert list(g.points) == pytest.approx([(2 - x, y) for x, y in pts], abs=1e-6)
        g.mirror("y", 0.0)
        assert list(g.points) == pytest.approx([(2 - x, -y) for x, y in pts], abs=1e-6)
    with pytest.raises(ValueError):
        shapes[0].mirror("z")


def test_line_move_keeps_unchanged_atom_text():
    fp = kicadfp.loads("(module X (layer F.Cu) (fp_line (start 1.0 2.0) (end 3.0 4.0) "
                       "(layer F.SilkS) (width 0.1)))")
    line = fp.graphics[0]
    line.move(0, 1)
    assert sexpr.to_compact(line.node.find("start")) == "(start 1.0 3)"


# ---------------------------------------------------------------------------
# Регрессия: mid дуги — истинная середина (KiCad читает mid лишь как подсказку стороны)
# ---------------------------------------------------------------------------

def _P(deg: float, r: float = 2.0) -> tuple[float, float]:
    a = math.radians(deg)
    return (round(r * math.cos(a), 6), round(r * math.sin(a), 6))


def test_arc_mid_written_as_true_midpoint():
    s, m, e = _P(0), _P(20), _P(300)          # дуга 300°, mid в 20° от начала
    a = Arc.new(s, m, e, uuid=False)
    assert a.sweep == pytest.approx(-300, abs=1e-4)
    g = _geo_mid(s, m, e)
    assert a.mid == pytest.approx(g, abs=1e-6)
    # середина дальше от прежней mid, чем центр: без пересчёта KiCad взял бы дугу 60°
    assert math.dist(a.mid, m) > a.radius
    # присваивание точки меняет только её токен и mid
    a2 = Arc.new(_P(0), _P(45), _P(90), uuid=False)
    a2.end = _P(300)
    assert a2.sweep == pytest.approx(-300, abs=1e-4)
    assert a2.mid == pytest.approx(_geo_mid(_P(0), _P(45), _P(300)), abs=1e-6)
    before = a2.mid
    a2.mid = _P(10)                          # та же дуга (через 10°) — mid прежняя (до нм)
    assert a2.mid == pytest.approx(before, abs=1e-5) and a2.mid != _P(10)
    assert (a2.start, a2.end) == (_P(0), _P(300))
    a3 = Arc.new(_P(0), _P(45), _P(90), uuid=False)
    a3.set_points(_P(0), _P(10), _P(300))
    assert a3.mid == pytest.approx(_geo_mid(_P(0), _P(10), _P(300)), abs=1e-6)
    # истинная середина сохраняется как есть; вырожденная дуга — mid без изменений
    a4 = Arc.new(_P(0), _P(45), _P(90), uuid=False)
    assert a4.mid == _P(45)
    a5 = Arc.new((0, 0), (1, 0), (2, 0), uuid=False)
    assert a5.mid == (1.0, 0.0)


def _geo_mid(s, m, e):
    from kicadfp import geometry as G
    g = G.arc_from_three_points(s, m, e)
    return G.point_at_angle(g.center, g.radius, g.start_angle + g.sweep / 2)


@pytest.mark.kicad_cli
def test_arc_mid_read_by_kicad_cli(kicad_cli, tmp_path):
    """kicad-cli читает ту же дугу (> 180°, mid не в середине), что и kicadfp: Arc.new в
    форматах 6 и 9 и присваивание конца дуге реального файла KiCad 6."""
    import subprocess
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    expect = {}
    for v in (20241229, 20211014, None):
        fp = kicadfp.Footprint.new(f"arc_{v}", version=v)
        fp.new_arc(_P(0), _P(20), _P(300), "F.SilkS", 0.1)
        kicadfp.save(fp, lib / f"arc_{v}.kicad_mod")
        expect[f"arc_{v}"] = 300.0
    fp6 = load_dip("kicad6")
    fp6.name = "dip6"
    a = [g for g in fp6.graphics if g.kind == "arc"][0]
    a.end = (4.009, -3.868)
    expect["dip6"] = abs(a.sweep)
    kicadfp.save(fp6, lib / "dip6.kicad_mod")
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    for name, sweep in expect.items():
        got = kicadfp.load(out / f"{name}.kicad_mod")
        arcs = [g for g in got.graphics if g.kind == "arc"]
        assert any(abs(abs(g.sweep) - sweep) < 0.01 for g in arcs), (name, sweep,
                                                                      [g.sweep for g in arcs])


def test_full_circle_arc_geometry():
    """Регрессия: дуга с start == end (её пишет и читает KiCad) — окружность с диаметром
    start–mid (``CalcArcCenter``), направление KiCad (sweep −360), длина 2πr; запись
    не меняется."""
    text = """(footprint "Diode_Bridge_Round_D9.0mm" (version 20241229) (generator "pcbnew")
  (generator_version "9.0") (layer "F.Cu")
  (fp_arc (start -2 2.5) (mid 7 2.5) (end -2 2.5) (stroke (width 0.12) (type solid))
    (layer "F.Fab") (uuid "cd6b2846-1a45-4028-9127-1d410dc1538b"))
)
"""
    fp = kicadfp.loads(text)
    (a,) = fp.graphics
    assert isinstance(a, Arc)
    assert a.center == (2.5, 2.5) and a.radius == 4.5
    assert a.sweep == -360.0
    assert a.length() == pytest.approx(2 * math.pi * 4.5)
    assert a.bbox() == BBox(-2, -2, 7, 7)
    assert fp.dumps() == kicadfp.loads(fp.dumps()).dumps()
    a.move(1, 0)
    assert a.start == (-1, 2.5) and a.end == (-1, 2.5) and a.center == (3.5, 2.5)
    # старая форма KiCad 5: (angle 360) вокруг центра
    fp5 = kicadfp.loads("(module X (layer F.Cu)\n  (fp_arc (start 6.25 -10) "
                        "(end 15.239959 -15.616106) (angle 360) (layer F.Fab) (width 0.1))\n)\n")
    (a5,) = fp5.graphics
    assert a5.center == (6.25, -10) and a5.radius == pytest.approx(10.6, abs=1e-6)
    assert abs(a5.sweep) == 360.0
