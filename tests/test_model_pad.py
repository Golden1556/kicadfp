"""Тесты :class:`kicadfp.model.Pad` и :class:`kicadfp.model.Drill`."""

from __future__ import annotations

import math

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import profile_for
from kicadfp.geometry import BBox
from kicadfp.model import Drill, Footprint, Pad, Poly
from kicadfp.sexpr import Node, Str, Sym
from tests.conftest import FIXTURES
from tests.test_model_common import assert_one_token_changed, changed_lines, load_dip

P5 = profile_for(None, "module")
P6 = profile_for(20211014)
P8 = profile_for(20240108)
P9 = profile_for(20241229)


def _pad(text: str, profile=P9) -> Pad:
    return Pad(sexpr.parse(text), profile)


def _approx_bbox(b: BBox, expected: tuple[float, float, float, float]) -> None:
    assert tuple(b) == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_read_dip14_pad1(version):
    p = load_dip(version).pad(1)
    assert p.number == "1" and p.type == "thru_hole"
    assert p.shape == ("roundrect" if version == "kicad9" else "rect")
    assert (p.x, p.y, p.angle, p.position) == (0.0, 0.0, 0.0, (0.0, 0.0))
    assert (p.size_x, p.size_y, p.size) == (1.6, 1.6, (1.6, 1.6))
    d = p.drill
    assert isinstance(d, Drill)
    assert (d.diameter, d.oval, d.width, d.size, d.offset) == (0.8, False, None, (0.8, 0.8), (0.0, 0.0))
    assert p.layers == ["*.Cu", "*.Mask"]
    assert p.is_tht() and not p.is_smd()
    assert p.roundrect_rratio == (0.15625 if version == "kicad9" else None)
    assert p.chamfer == [] and p.chamfer_ratio is None
    assert p.rect_delta is None and p.net is None and p.property is None
    assert p.pinfunction is None and p.pintype is None
    assert p.clearance is None and p.solder_mask_margin is None and p.solder_paste_ratio is None
    assert p.zone_connect is None and p.thermal_bridge_width is None and p.thermal_gap is None
    assert p.locked is False and p.primitives == [] and p.options is None and p.anchor is None
    assert p.remove_unused_layers == (False if version in ("kicad8", "kicad9") else None)
    assert p.keep_end_layers is None
    assert p.uuid == {"kicad5": None, "kicad6": "c59ff4fb-10d1-49fb-80e5-f15385e71fb6",
                      "kicad8": "c59ff4fb-10d1-49fb-80e5-f15385e71fb6", "kicad9": None}[version]
    assert p.bbox() == BBox(-0.8, -0.8, 0.8, 0.8)
    assert repr(p).startswith("Pad('1', thru_hole")


def test_read_custom_pad_with_primitives():
    fp = kicadfp.load(FIXTURES / "kicad9" / "Package_DFN_QFN.pretty"
                      / "QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm.kicad_mod")
    p = fp.pad(1)
    assert p.shape == "custom" and p.is_smd() and p.anchor == "circle"
    assert p.options is not None and p.options.value("clearance") == "outline"
    assert [n.name for n in p.primitives] == ["gr_poly"]
    (g,) = p.primitive_views
    assert isinstance(g, Poly) and g.is_primitive and g.layer is None
    assert g.width == 0.08 and g.fill is True          # без (fill) многоугольник залит (KiCad)
    assert g.points[0] == (-0.335, -0.06) and len(g.points) == 5
    _approx_bbox(p.bbox(), (-1.875, -1.1, -1.125, -0.9))


def test_read_drill_offset_without_size():
    fp = kicadfp.load(FIXTURES / "kicad8" / "Package_DIP.pretty" / "Fairchild_LSOP-8.kicad_mod")
    p = fp.pad(1)
    d = p.drill
    assert p.type == "smd" and d is not None
    assert (d.diameter, d.oval, d.width, d.offset) == (0.0, False, None, (0.0, 0.266))
    _approx_bbox(p.bbox(), (-5.35, -4.17, -3.35, -2.918))


@pytest.mark.parametrize("text,diameter,oval,width,size,offset", [
    ("(drill 0.8)", 0.8, False, None, (0.8, 0.8), (0, 0)),
    ("(drill oval 1.2 0.8)", 1.2, True, 0.8, (1.2, 0.8), (0, 0)),
    ("(drill oval 1)", 1.0, True, 1.0, (1.0, 1.0), (0, 0)),
    ("(drill 0.8 (offset 0 0.1))", 0.8, False, None, (0.8, 0.8), (0, 0.1)),
    ("(drill (offset 0.2 -0.3) oval 2 1)", 2.0, True, 1.0, (2.0, 1.0), (0.2, -0.3)),
    ("(drill)", 0.0, False, None, (0.0, 0.0), (0, 0)),
])
def test_drill_forms(text, diameter, oval, width, size, offset):
    d = Drill(sexpr.parse(text))
    assert (d.diameter, d.oval, d.width, d.size, d.offset) == (diameter, oval, width, size, offset)
    assert (d.offset_x, d.offset_y) == offset


def test_drill_view_setters():
    d = Drill(sexpr.parse("(drill 0.8 (offset 0 0.1))"))
    d.diameter = 1.0
    assert sexpr.to_compact(d.node) == "(drill 1(offset 0 0.1))"
    d.width = 0.6                               # второй размер -> овал
    assert sexpr.to_compact(d.node) == "(drill oval 1 0.6(offset 0 0.1))"
    d.width = None
    assert sexpr.to_compact(d.node) == "(drill oval 1(offset 0 0.1))"
    d.oval = False
    assert sexpr.to_compact(d.node) == "(drill 1(offset 0 0.1))"
    d.oval = True
    assert d.oval and d.width == 1.0
    d.offset_x = 0.5
    assert d.offset == (0.5, 0.1)
    d.offset = (0, 0)                           # (0, 0) удаляет (offset)
    assert sexpr.to_compact(d.node) == "(drill oval 1)"
    d.offset_y = -0.2
    assert sexpr.to_compact(d.node) == "(drill oval 1(offset 0 -0.2))"
    e = Drill(sexpr.parse("(drill (offset 0 0.2))"))
    e.diameter = 0.5
    assert sexpr.to_compact(e.node) == "(drill 0.5(offset 0 0.2))"
    assert sexpr.to_compact(Drill.new(0.8).node) == "(drill 0.8)"
    assert sexpr.to_compact(Drill.new(1.2, 0.6).node) == "(drill oval 1.2 0.6)"
    assert sexpr.to_compact(Drill.new(1.0, 1.0).node) == "(drill oval 1)"
    assert sexpr.to_compact(Drill.new(0.8, offset=(0.1, 0)).node) == "(drill 0.8(offset 0.1 0))"


def test_pad_drill_assignment_forms():
    p = _pad('(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 0.8 (offset 0 0.1)) (layers "*.Cu") (uuid "u"))')
    p.drill = 1.0                              # круглое, offset сохраняется
    assert sexpr.to_compact(p.node.find("drill")) == "(drill 1(offset 0 0.1))"
    p.drill = (1.2, 0.8)
    assert sexpr.to_compact(p.node.find("drill")) == "(drill oval 1.2 0.8(offset 0 0.1))"
    p.drill = (1.0, 1.0)
    assert sexpr.to_compact(p.node.find("drill")) == "(drill oval 1(offset 0 0.1))"
    p.drill = Drill.new(0.5)                   # копия узла целиком
    assert sexpr.to_compact(p.node.find("drill")) == "(drill 0.5)"
    p.drill = None
    assert p.drill is None and p.node.find("drill") is None
    p.drill = 0.9                              # новый узел — после size по таблице
    names = [n.name for n in p.node.nodes()]
    assert names[:4] == ["at", "size", "drill", "layers"]
    p.drill = (1.5, 0.5)
    assert p.drill.size == (1.5, 0.5)
    with pytest.raises(TypeError):
        p.drill = "0.8"                        # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Setters: один токен
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
@pytest.mark.parametrize("attr,value", [
    ("number", "15"), ("type", "smd"), ("shape", "oval"), ("x", 1.27), ("y", -2.5),
    ("angle", 90.0), ("size_x", 2.0), ("size_y", 2.2), ("roundrect_rratio", 0.2),
    ("chamfer_ratio", 0.15), ("clearance", 0.1), ("solder_mask_margin", 0.05),
    ("solder_paste_margin", -0.05), ("solder_paste_ratio", -0.1), ("zone_connect", 1),
    ("thermal_gap", 0.3), ("die_length", 1.5), ("pinfunction", "VCC"), ("pintype", "power_in"),
    ("property", "pad_prop_heatsink"), ("thermal_bridge_angle", 45.0),
])
def test_pad_setter_changes_one_token(version, attr, value):
    fp = load_dip(version)
    pad = fp.pad(1)
    if attr == "chamfer_ratio":
        # фаска у rect переводит площадку в roundrect (test_pad_chamfer_converts_rect)
        pad.shape = "roundrect"
    before = fp.node.copy()
    text_before = fp.dumps()
    if (attr == "thermal_bridge_angle" and version in ("kicad5", "kicad6")) or (
            attr in ("pinfunction", "pintype", "property") and version == "kicad5"):
        # токена нет в формате версии файла (thermal_bridge_angle — 20211227, pinfunction —
        # 20191123, pintype — 20210126, property площадки — 20200104): KiCad этой версии
        # файл с ним не прочитал бы
        with pytest.raises(ValueError, match="upgrade"):
            setattr(pad, attr, value)
        assert fp.dumps() == text_before
        return
    setattr(pad, attr, value)
    assert_one_token_changed(before, fp.node)
    assert getattr(pad, attr) == value
    if version in ("kicad8", "kicad9"):
        removed, added = changed_lines(text_before, fp.dumps())
        assert len(removed) <= 1 and len(added) == 1, (removed, added)
    again = kicadfp.loads(fp.dumps())
    assert getattr(again.pads[0], attr) == value


def test_pad_number_quoting_and_validation():
    p5 = load_dip("kicad5").pad(1)
    p5.number = "A1"
    assert isinstance(p5.node.atom(0), Sym)
    p5.number = ""
    assert isinstance(p5.node.atom(0), Str)
    p8 = load_dip("kicad8").pad(1)
    p8.number = 7
    assert p8.node.atom(0) == Str("7") and isinstance(p8.node.atom(0), Str)
    with pytest.raises(TypeError):
        p8.number = True                       # type: ignore[assignment]
    with pytest.raises(ValueError):
        p8.type = "via"
    with pytest.raises(ValueError):
        p8.shape = "star"
    with pytest.raises(TypeError):
        p8.x = "1"                             # type: ignore[assignment]
    with pytest.raises(ValueError):
        p8.x = math.nan


def test_pad_angle_zero_is_not_written():
    p = load_dip("kicad8").pad(8)
    p.angle = 90
    assert p.node.find("at").atoms() == ["7.62", "15.24", "90"]
    p.angle = 0
    assert p.node.find("at").atoms() == ["7.62", "15.24"]
    p.angle = -45.5
    assert p.node.find("at").atoms() == ["7.62", "15.24", "-45.5"]


def test_pad_size_and_position_setters():
    p = load_dip("kicad8").pad(2)
    p.size = 2
    assert p.node.find("size").atoms() == ["2", "2"]
    p.size = (1.5, 2.5)
    assert p.size == (1.5, 2.5)
    p.position = (1, 2)
    assert p.node.find("at").atoms() == ["1", "2"]
    p.x = 3
    assert p.node.find("at").atoms() == ["3", "2"]


@pytest.mark.parametrize("version,expected", [
    ("kicad5", "(layers F.Cu F.Paste F.Mask)"),
    ("kicad6", '(layers "F.Cu" "F.Paste" "F.Mask")'),
    ("kicad8", '(layers "F.Cu" "F.Paste" "F.Mask")'),
])
def test_layers_setter_quoting(version, expected):
    p = load_dip(version).pad(1)
    p.layers = ["F.Cu", "F.Paste", "F.Mask"]
    assert sexpr.to_compact(p.node.find("layers")) == expected
    assert p.layers == ["F.Cu", "F.Paste", "F.Mask"]


def test_layers_wildcards_quoting_by_version():
    p5, p6, p8 = (load_dip(v).pad(1) for v in ("kicad5", "kicad6", "kicad8"))
    for p in (p5, p6, p8):
        p.layers = "*.Cu, *.Mask"
    assert sexpr.to_compact(p5.node.find("layers")) == "(layers *.Cu *.Mask)"
    assert sexpr.to_compact(p6.node.find("layers")) == "(layers *.Cu *.Mask)"
    assert sexpr.to_compact(p8.node.find("layers")) == '(layers "*.Cu" "*.Mask")'


def test_set_layers_presets_writer_order():
    p8 = load_dip("kicad8").pad(1)
    p8.set_layers("smd")
    assert p8.layers == ["F.Cu", "F.Paste", "F.Mask"]       # порядок KiCad 6–8
    p9 = Footprint.new("X").new_pad(1, "smd", "rect", 0, 0, 1)
    assert p9.layers == ["F.Cu", "F.Mask", "F.Paste"]       # порядок KiCad 9
    p9.set_layers("smd_back")
    assert p9.layers == ["B.Cu", "B.Mask", "B.Paste"]
    p9.set_layers("thru_hole")
    assert p9.layers == ["*.Cu", "*.Mask"]
    with pytest.raises(ValueError):
        p9.set_layers("nope")


def test_is_tht_is_smd():
    for t, tht, smd in (("thru_hole", True, False), ("np_thru_hole", True, False),
                        ("smd", False, True), ("connect", False, True)):
        p = Pad.new("1", t, "circle", 0, 0, 1)
        assert (p.is_tht(), p.is_smd()) == (tht, smd)


def test_thermal_bridge_width_token_by_version():
    p6 = load_dip("kicad6").pad(1)
    p6.thermal_bridge_width = 0.5
    assert p6.node.number("thermal_width") == 0.5 and p6.node.find("thermal_bridge_width") is None
    p8 = load_dip("kicad8").pad(1)
    p8.thermal_bridge_width = 0.5
    assert p8.node.number("thermal_bridge_width") == 0.5
    p = _pad('(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (thermal_width 0.3))', P9)
    assert p.thermal_bridge_width == 0.3
    p.thermal_bridge_width = 0.4               # существующий токен сохраняет имя
    assert p.node.number("thermal_width") == 0.4
    p.thermal_bridge_width = None
    assert p.thermal_bridge_width is None


def test_chamfer_rect_delta_net_property():
    p = load_dip("kicad8").pad(1)
    p.chamfer = ["bottom_right", "top_left"]
    assert sexpr.to_compact(p.node.find("chamfer")) == "(chamfer top_left bottom_right)"
    p.chamfer = []
    assert p.node.find("chamfer") is None
    with pytest.raises(ValueError):
        p.chamfer = ["left"]
    p.rect_delta = (0.2, 0)
    assert p.rect_delta == (0.2, 0.0)
    p.rect_delta = None
    assert p.node.find("rect_delta") is None
    p.net = (1, "GND")
    assert sexpr.to_compact(p.node.find("net")) == '(net 1 "GND")' and p.net == (1, "GND")
    p.net = None
    q = _pad('(pad "1" smd rect (at 0 0) (size 1 1) (net "VCC"))')
    assert q.net == (0, "VCC")
    p.property = "pad_prop_bga"
    assert sexpr.to_compact(p.node.find("property")) == "(property pad_prop_bga)"
    assert p.property == "pad_prop_bga"
    with pytest.raises(ValueError):
        p.property = "two words"
    p.property = None
    assert p.property is None


@pytest.mark.parametrize("version,on,off", [
    ("kicad6", "(remove_unused_layers)", None),
    ("kicad8", "(remove_unused_layers yes)", "(remove_unused_layers no)"),
])
def test_remove_unused_layers_forms(version, on, off):
    p = load_dip(version).pad(1)
    p.remove_unused_layers = True
    assert sexpr.to_compact(p.node.find("remove_unused_layers")) == on
    assert p.remove_unused_layers is True
    p.keep_end_layers = True
    assert p.keep_end_layers is True
    p.remove_unused_layers = False
    n = p.node.find("remove_unused_layers")
    assert (None if n is None else sexpr.to_compact(n)) == off
    p.remove_unused_layers = None
    assert p.node.find("remove_unused_layers") is None and p.remove_unused_layers is None


@pytest.mark.parametrize("version,expected", [
    ("kicad6", '(pad "1" thru_hole rect locked(at 0 0)'),
    ("kicad8", '(pad "1" thru_hole rect(locked yes)(at 0 0)'),
])
def test_pad_locked_forms(version, expected):
    p = load_dip(version).pad(1)
    p.locked = True
    assert sexpr.to_compact(p.node).startswith(expected) and p.locked
    p.locked = False
    assert "locked" not in sexpr.to_compact(p.node)


def test_pad_tokens_rejected_by_old_versions():
    """Регрессия: locked (20210108), pinfunction (20191123), pintype (20210126) и property
    (20200104) площадки не пишутся в файлы версий, которые их не знают, — ни setters, ни
    Footprint.add; уже записанные токены меняются."""
    fp5 = load_dip("kicad5")
    p = fp5.pad(1)
    before = fp5.dumps()
    for attr, val in (("locked", True), ("pinfunction", "A"), ("pintype", "passive"),
                      ("property", "pad_prop_heatsink")):
        with pytest.raises(ValueError, match="upgrade"):
            setattr(p, attr, val)
    p.locked = False
    p.pinfunction = None
    assert fp5.dumps() == before
    # файл 20201116 (корень footprint): pinfunction/property уже можно, locked/pintype — нет
    fp6 = kicadfp.loads(load_dip("kicad6").dumps().replace("(version 20211014)",
                                                           "(version 20201116)"))
    q = fp6.pad(1)
    q.pinfunction = "A"
    q.property = "pad_prop_bga"
    with pytest.raises(ValueError, match="20210108"):
        q.locked = True
    with pytest.raises(ValueError, match="20210126"):
        q.pintype = "passive"
    # имеющийся в файле токен меняется без проверки версии
    fp5b = kicadfp.loads(before.replace("(pad 1 thru_hole rect", "(pad 1 thru_hole rect locked", 1))
    assert fp5b.pad(1).locked
    fp5b.pad(1).locked = True
    # Footprint.add отвергает площадку с такими токенами
    for kw in ({"pinfunction": "A"}, {"pintype": "passive"}, {"property": "pad_prop_bga"},
               {"locked": True}):
        with pytest.raises(ValueError, match="upgrade"):
            load_dip("kicad5").add(Pad.new("9", "smd", "rect", **kw))
    load_dip("kicad5").add(Pad.new("9", "smd", "rect"))


@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_pad_chamfer_converts_rect(version):
    """Регрессия: фаска у rect — это roundrect с (roundrect_rratio 0), как пишет KiCad
    (иначе парсер KiCad сделает CHAMFERED_RECT со скруглением 0.25 по умолчанию)."""
    fp = load_dip(version)
    p = fp.new_pad("80", "smd", "rect", 6, 5, (1, 2), chamfer_ratio=0.2, chamfer=["top_left"])
    assert p.shape == "roundrect" and p.roundrect_rratio == 0.0
    assert p.chamfer_ratio == 0.2 and p.chamfer == ["top_left"]
    q = fp.pad(1)                          # имеющаяся площадка rect (в KiCad 9 — roundrect)
    was, rr = q.shape, q.roundrect_rratio
    q.chamfer = ["bottom_right"]
    assert q.shape == "roundrect"
    assert q.roundrect_rratio == (0.0 if was == "rect" else rr)
    r = fp.new_pad("81", "smd", "roundrect", 0, 0, (1, 2), roundrect_rratio=0.1)
    r.chamfer_ratio = 0.3                  # roundrect не меняется
    assert r.shape == "roundrect" and r.roundrect_rratio == 0.1
    o = fp.new_pad("82", "smd", "oval", 0, 0, (1, 2))
    text = fp.dumps()
    with pytest.raises(ValueError, match="rect"):
        o.chamfer = ["top_left"]
    with pytest.raises(ValueError, match="rect"):
        o.chamfer_ratio = 0.2
    o.chamfer_ratio = 0                    # без фаски — форма не важна
    o.chamfer_ratio = None
    o.chamfer = []
    assert fp.dumps() == text
    with pytest.raises(ValueError):
        Pad.new("1", "smd", "circle", chamfer=["top_left"])


def test_pad_uuid_forms():
    p6, p8 = load_dip("kicad6").pad(1), load_dip("kicad8").pad(1)
    p6.uuid = "11111111-2222-3333-4444-555555555555"
    p8.uuid = "11111111-2222-3333-4444-555555555555"
    assert sexpr.to_compact(p6.node.find("tstamp")) == "(tstamp 11111111-2222-3333-4444-555555555555)"
    assert sexpr.to_compact(p8.node.find("uuid")) == '(uuid "11111111-2222-3333-4444-555555555555")'
    p9 = load_dip("kicad9").pad(1)
    p9.uuid = "11111111-2222-3333-4444-555555555555"
    assert p9.node.nodes()[-1].name == "uuid"            # в конец по таблице
    p9.uuid = None
    assert p9.uuid is None


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------

def test_pad_new_forms_by_profile():
    p9 = Pad.new(1, "thru_hole", "rect", 0, 0, 1.6, drill=0.8, uuid="u-1")
    assert sexpr.to_compact(p9.node) == (
        '(pad "1" thru_hole rect(at 0 0)(size 1.6 1.6)(drill 0.8)(layers "*.Cu" "*.Mask")'
        '(remove_unused_layers no)(uuid "u-1"))')
    p8 = Pad.new(1, "smd", "roundrect", 1, 2, (1, 0.5), angle=180, profile=P8, uuid="u-2")
    assert sexpr.to_compact(p8.node) == (
        '(pad "1" smd roundrect(at 1 2 180)(size 1 0.5)(layers "F.Cu" "F.Paste" "F.Mask")'
        '(roundrect_rratio 0.25)(uuid "u-2"))')
    p6 = Pad.new(2, "thru_hole", "oval", 0, 0, (1.6, 2), drill=(0.8, 1.2), profile=P6, uuid="u-3")
    assert sexpr.to_compact(p6.node) == (
        '(pad "2" thru_hole oval(at 0 0)(size 1.6 2)(drill oval 0.8 1.2)(layers *.Cu *.Mask)'
        '(tstamp u-3))')
    p5 = Pad.new(3, "smd", "rect", 0, 0, 1, profile=P5)
    assert sexpr.to_compact(p5.node) == "(pad 3 smd rect(at 0 0)(size 1 1)(layers F.Cu F.Paste F.Mask))"
    npth = Pad.new("", "np_thru_hole", "circle", 0, 0, 3, drill=3, uuid=False)
    assert sexpr.to_compact(npth.node) == (
        '(pad "" np_thru_hole circle(at 0 0)(size 3 3)(drill 3)(layers "*.Cu" "*.Mask"))')


def test_pad_new_keyword_properties():
    p = Pad.new(1, "smd", "roundrect", 0, 0, (1, 2), roundrect_rratio=0.1, chamfer_ratio=0.2,
                chamfer=["top_left"], solder_mask_margin=0.05, property="pad_prop_heatsink",
                uuid=False)
    assert p.roundrect_rratio == 0.1 and p.chamfer == ["top_left"] and p.chamfer_ratio == 0.2
    names = [n.name for n in p.node.nodes()]
    assert names == ["at", "size", "property", "layers", "roundrect_rratio", "chamfer_ratio",
                     "chamfer", "solder_mask_margin"]
    c = Pad.new(1, "smd", "custom", 0, 0, 0.5, anchor="circle", uuid=False)
    assert c.anchor == "circle"
    assert sexpr.to_compact(c.options) == "(options(clearance outline)(anchor circle))"
    c.add_primitive(Poly.new([(0, 0), (1, 0), (1, 1)], width=0, fill=True, primitive=True))
    assert sexpr.to_compact(c.node.find("primitives")) == \
        "(primitives(gr_poly(pts(xy 0 0)(xy 1 0)(xy 1 1))(width 0)(fill yes)))"
    with pytest.raises(ValueError):
        c.add_primitive(Node("fp_line"))
    with pytest.raises(TypeError):
        Pad.new(1, "smd", "rect", 0, 0, 1, bogus=1)
    with pytest.raises(ValueError):
        Pad.new(1, "via", "rect", 0, 0, 1)


# ---------------------------------------------------------------------------
# Преобразования и габариты
# ---------------------------------------------------------------------------

def test_pad_move_rotate():
    p = Pad.new(1, "smd", "rect", 1, 0, (2, 1), uuid=False)
    p.move(0.5, -0.5)
    assert p.position == (1.5, -0.5)
    p.move(-0.5, 0.5)
    p.rotate(90)
    assert p.position == (0.0, -1.0) and p.angle == 90
    p.rotate(90, (0, -1))
    assert p.position == (0.0, -1.0) and p.angle == 180
    p.rotate(180)
    assert p.position == (0.0, 1.0) and p.angle == 0
    assert p.node.find("at").atoms() == ["0", "1"]
    p.rotate(-90)
    assert p.angle == 270                      # нормализация в [0, 360)


@pytest.mark.parametrize("pad_text,expected", [
    ('(pad "1" smd circle (at 1 1) (size 1.6 1.6))', (0.2, 0.2, 1.8, 1.8)),
    ('(pad "1" smd rect (at 0 0 45) (size 2 1))', (-1.06066, -1.06066, 1.06066, 1.06066)),
    ('(pad "1" smd rect (at 0 0 90) (size 2 1))', (-0.5, -1, 0.5, 1)),
    ('(pad "1" smd oval (at 0 0) (size 2 1))', (-1, -0.5, 1, 0.5)),
    ('(pad "1" smd oval (at 0 0 45) (size 2 1))', (-0.853553, -0.853553, 0.853553, 0.853553)),
    ('(pad "1" smd roundrect (at 0 0 45) (size 2 1) (roundrect_rratio 0.25))',
     (-0.957107, -0.957107, 0.957107, 0.957107)),
    ('(pad "1" smd trapezoid (at 0 0) (size 2 1) (rect_delta 0.4 0))', (-1, -0.7, 1, 0.7)),
    ('(pad "1" smd rect (at 0 0) (size 2 2) (drill 1 (offset 1 0)))', (-0.5, -1, 2, 1)),
    ('(pad "1" thru_hole circle (at 0 0) (size 1 1) (drill oval 2 0.5))', (-1, -0.5, 1, 0.5)),
    ('(pad "1" smd custom (at 0 0) (size 1 1) (options (anchor circle)) '
     '(primitives (gr_poly (pts (xy 0 0) (xy 2 0) (xy 2 1)) (width 0))))', (-0.5, -0.5, 2, 1)),
    ('(pad "1" smd custom (at 1 0 90) (size 1 1) (options (anchor rect)) '
     '(primitives (gr_poly (pts (xy 0 0) (xy 2 0) (xy 2 1)) (width 0))))', (0.5, -2, 2, 0.5)),
])
def test_pad_bbox_shapes(pad_text, expected):
    _approx_bbox(_pad(pad_text).bbox(), expected)


def test_pad_flip_x_in_footprint():
    fp = load_dip("kicad6")
    p = fp.pad(8)
    p.angle = 90
    p.drill = Drill.new(0.8, offset=(0.1, 0.2))
    fp.flip()
    assert p.position == (-7.62, 15.24) and p.angle == 270
    assert p.drill.offset == (-0.1, 0.2)
    assert p.layers == ["*.Cu", "*.Mask"]


# ---------------------------------------------------------------------------
# Перенос на другую сторону: стек площадки (padstack) и tenting, KiCad 9+
# ---------------------------------------------------------------------------

_PS_HEAD = '''(footprint "ps"
	(version 20241229)
	(generator "pcbnew")
	(generator_version "9.0")
	(layer "F.Cu")
	(property "Reference" "REF**"
		(at 0 -3 0)
		(layer "F.SilkS")
		(uuid "11111111-1111-1111-1111-111111111111")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(property "Value" "ps"
		(at 0 3 0)
		(layer "F.Fab")
		(uuid "11111111-1111-1111-1111-111111111112")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(attr through_hole)
'''


def _ps_fp(pad: str) -> Footprint:
    return kicadfp.loads(_PS_HEAD + pad + "\t(embedded_fonts no)\n)\n")


_PS_FIB = '''	(pad "1" thru_hole rect
		(at 2 0)
		(size 3 1.5)
		(drill 0.8)
		(layers "*.Cu" "*.Mask")
		(remove_unused_layers no)
		(tenting front)
		(uuid "11111111-1111-1111-1111-111111111113")
		(padstack
			(mode front_inner_back)
			(layer "Inner"
				(shape circle)
				(size 1.2 1.2)
			)
			(layer "B.Cu"
				(shape roundrect)
				(size 1.6 2.5)
				(offset 0.3 0.2)
				(roundrect_rratio 0.1)
				(chamfer_ratio 0.2)
				(chamfer top_left bottom_left)
			)
		)
	)
'''


def _entry(p: Pad, name: str) -> Node | None:
    ps = p.node.find("padstack")
    return next((n for n in ps.nodes("layer") if str(n.atom(0)) == name), None)


def test_pad_flip_padstack_front_inner_back():
    """Регрессия: flip() переименовывал (layer "B.Cu") стека в "F.Cu" вместо обмена
    свойств передней и задней сторон (PADSTACK::FlipLayers) и не отражал их по X."""
    fp = _ps_fp(_PS_FIB)
    fp.flip()
    p = fp.pads[0]
    # передняя сторона — бывшая задняя, отражённая по X
    assert (p.shape, p.size, p.x) == ("roundrect", (1.6, 2.5), -2.0)
    assert p.drill.offset == (-0.3, 0.2)
    assert p.roundrect_rratio == 0.1 and p.chamfer_ratio == 0.2
    assert p.chamfer == ["top_right", "bottom_right"]
    # задняя — бывшая передняя; смещения у неё нет, а у передней есть — явный ноль
    back = _entry(p, "B.Cu")
    assert back is not None and _entry(p, "F.Cu") is None
    assert sexpr.to_compact(back) == '(layer "B.Cu"(shape rect)(size 3 1.5)(offset 0 0))'
    inner = _entry(p, "Inner")
    assert sexpr.to_compact(inner) == '(layer "Inner"(shape circle)(size 1.2 1.2)(offset 0 0))'
    assert p.node.find("tenting").atoms() == ["back"]
    assert p.layers == ["*.Cu", "*.Mask"]
    # двойной перенос возвращает исходное дерево
    fp.flip()
    assert sexpr.diff(_ps_fp(_PS_FIB).node, fp.node) == []


def test_pad_flip_padstack_custom_inner_conjugates():
    """custom: F.Cu <-> B.Cu и In(k) <-> In(31-k) (32 медных слоя, как KiCad вне платы);
    слой без записи — копия передней стороны."""
    pad = '''	(pad "1" thru_hole rect
		(at 0 0)
		(size 3 1.5)
		(drill 0.8
			(offset 0.2 0.1)
		)
		(layers "*.Cu" "*.Mask")
		(uuid "11111111-1111-1111-1111-111111111113")
		(padstack
			(mode custom)
			(layer "In1.Cu"
				(shape circle)
				(size 1.2 1.2)
				(offset 0 0)
			)
			(layer "In30.Cu"
				(shape oval)
				(size 1.4 1.1)
				(offset 0.1 0)
			)
			(layer "B.Cu"
				(shape oval)
				(size 1.6 2.5)
				(offset 0.3 0.2)
			)
		)
	)
'''
    fp = _ps_fp(pad)
    fp.flip()
    p = fp.pads[0]
    assert (p.shape, p.size, p.drill.offset) == ("oval", (1.6, 2.5), (-0.3, 0.2))
    c = {name: sexpr.to_compact(_entry(p, name)) for name in ("In1.Cu", "In30.Cu", "B.Cu")}
    assert c["In1.Cu"] == '(layer "In1.Cu"(shape oval)(size 1.4 1.1)(offset -0.1 0))'
    assert c["In30.Cu"] == '(layer "In30.Cu"(shape circle)(size 1.2 1.2)(offset 0 0))'
    assert c["B.Cu"] == '(layer "B.Cu"(shape rect)(size 3 1.5)(offset -0.2 0.1))'
    # In2 (не было записи = копия передней) теперь отличается от новой передней
    assert sexpr.to_compact(_entry(p, "In2.Cu")) == \
        '(layer "In2.Cu"(shape rect)(size 3 1.5)(offset -0.2 0.1))'
    names = [str(n.atom(0)) for n in p.node.find("padstack").nodes("layer")]
    assert names[0] == "In1.Cu" and names[-1] == "B.Cu" and len(names) == 31


@pytest.mark.parametrize("before,after", [
    ("front", ["back"]), ("back", ["front"]), ("front back", ["front", "back"]),
    ("none", ["none"]),
])
def test_pad_flip_tenting_with_padstack(before, after):
    """Регрессия: flip() не менял сторону (tenting …) (std::swap масок в FlipLayers)."""
    fp = _ps_fp(_PS_FIB.replace("(tenting front)", f"(tenting {before})"))
    fp.flip()
    assert [str(a) for a in fp.pads[0].node.find("tenting").atoms()] == after


def test_pad_flip_tenting_normal_mode_like_kicad9():
    """Без стека (режим normal) PADSTACK::FlipLayers KiCad 9 маски не меняет."""
    fp = _ps_fp('''	(pad "1" smd rect
		(at 1 0)
		(size 1 1)
		(layers "F.Cu" "F.Mask" "F.Paste")
		(tenting front)
	)
''')
    fp.flip()
    p = fp.pads[0]
    assert p.layers == ["B.Cu", "B.Mask", "B.Paste"]
    assert [str(a) for a in p.node.find("tenting").atoms()] == ["front"]


def _cli_resave(cli: str, fps: dict[str, Footprint], tmp_path) -> dict[str, Footprint]:
    import subprocess
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    for name, fp in fps.items():
        kicadfp.save(fp, lib / f"{name}.kicad_mod")
    out = tmp_path / "out.pretty"
    r = subprocess.run([cli, "fp", "upgrade", "--force", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "Unable" not in r.stderr, r.stderr
    return {name: kicadfp.load(out / f"{name}.kicad_mod") for name in fps}


@pytest.mark.kicad_cli
def test_pad_flip_padstack_read_by_kicad_cli(kicad_cli, tmp_path):
    """KiCad читает перенесённый стек так, как его показывает kicadfp: передняя сторона —
    бывшая задняя с отражённым смещением, задняя — бывшая передняя, tenting — back."""
    fp = _ps_fp(_PS_FIB)
    fp.flip()
    twice = _ps_fp(_PS_FIB)
    twice.flip()
    twice.flip()
    got = _cli_resave(kicad_cli, {"orig": _ps_fp(_PS_FIB), "flip": fp, "twice": twice},
                      tmp_path)
    k = got["flip"].pads[0]
    assert (k.shape, k.size, k.x, k.drill.offset) == ("roundrect", (1.6, 2.5), -2.0, (-0.3, 0.2))
    assert k.chamfer == ["top_right", "bottom_right"]
    back = _entry(k, "B.Cu")
    assert back.value("shape") == "rect" and back.numbers("size") == [3.0, 1.5]
    assert back.find("offset") is None and _entry(k, "Inner").find("offset") is None
    assert [str(a) for a in k.node.find("tenting").atoms()] == ["back"]
    # двойной перенос KiCad читает так же, как исходный корпус
    a, b = got["orig"].pads[0].node, got["twice"].pads[0].node
    assert sexpr.diff(a, b) == []


def test_pad_flip_padstack_custom_primitives_and_anchor():
    """Якорь и примитивы custom-площадки переставляются по слоям и отражаются;
    (clearance outline) остаётся у площадки; у не-custom слоя их нет."""
    pad = '''	(pad "1" smd custom
		(at 2 0)
		(size 1 1)
		(layers "F.Cu" "F.Mask")
		(options (clearance outline) (anchor circle))
		(primitives
			(gr_poly (pts (xy 0 0) (xy 2 0) (xy 2 1)) (width 0) (fill yes))
		)
		(padstack
			(mode front_inner_back)
			(layer "Inner" (shape circle) (size 1 1))
			(layer "B.Cu" (shape custom) (size 1 1) (options (anchor rect))
				(primitives (gr_line (start 0 0) (end 3 0) (width 0.2)))
			)
		)
	)
'''
    fp = _ps_fp(pad)
    fp.flip()
    p = fp.pads[0]
    assert p.layers == ["B.Cu", "B.Mask"]
    assert sexpr.to_compact(p.node.find("options")) == "(options(clearance outline)(anchor rect))"
    assert [sexpr.to_compact(n) for n in p.primitives] == [
        "(gr_line(start 0 0)(end -3 0)(width 0.2))"]
    assert sexpr.to_compact(_entry(p, "Inner")) == '(layer "Inner"(shape circle)(size 1 1))'
    assert sexpr.to_compact(_entry(p, "B.Cu")) == (
        '(layer "B.Cu"(shape custom)(size 1 1)(options(anchor circle))'
        '(primitives(gr_poly(pts(xy 0 0)(xy -2 0)(xy -2 1))(width 0)(fill yes))))')
    fp.flip()
    assert sexpr.diff(_ps_fp(pad).node, fp.node) == []
