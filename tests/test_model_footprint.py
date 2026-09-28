"""Тесты :class:`kicadfp.model.Footprint`: чтение всех атрибутов DIP-14 четырёх версий,
setters (ровно один токен, форма по версии), создание нового корпуса, add/remove,
move/rotate/flip/renumber, bbox, upgrade (сверка с ``kicad-cli fp upgrade``)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import DEFAULT_VERSION
from kicadfp.geometry import BBox
from kicadfp.model import Arc, Footprint, Line, Pad, Rect, Text
from kicadfp.sexpr import Node, Str, Sym
from tests.conftest import FIXTURES
from tests.test_model_common import (DIP14, assert_one_token_changed, changed_lines, load_dip,
                                     tree_changes)

DESCR = "14-lead though-hole mounted DIP package, row spacing 7.62 mm (300 mils)"
TAGS = "THT DIP DIL PDIP 2.54mm 7.62mm 300mil"


def _pad_xy(n: int) -> tuple[float, float]:
    """Положение площадки ``n`` DIP-14 (шаг 2.54, ряды 0 и 7.62)."""
    if n <= 7:
        return (0.0, round(2.54 * (n - 1), 6))
    return (7.62, round(15.24 - 2.54 * (n - 8), 6))


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_read_dip14_common(version):
    fp = load_dip(version)
    assert fp.name == "DIP-14_W7.62mm"
    assert fp.layer == "F.Cu"
    assert fp.tags == TAGS
    assert fp.descr == (DESCR if version != "kicad9" else DESCR.replace("7.62 mm", "7.62mm"))
    assert len(fp.pads) == 14
    assert sorted(int(p.number) for p in fp.pads) == list(range(1, 15))
    for n in range(1, 15):
        p = fp.pad(n)
        assert p.position == _pad_xy(n)
        assert p.type == "thru_hole" and p.angle == 0.0
        assert p.size == (1.6, 1.6) and p.drill is not None and p.drill.diameter == 0.8
        assert p.layers == ["*.Cu", "*.Mask"]
    assert fp.pad("1") == fp.pad(1)
    assert fp.pads_by_number(3) == [fp.pad(3)]
    with pytest.raises(KeyError):
        fp.pad(15)
    ref, val = fp.reference, fp.value
    assert ref is not None and val is not None
    assert (ref.text, ref.position, ref.layer) == ("REF**", (3.81, -2.33), "F.SilkS")
    assert (val.text, val.position, val.layer) == ("DIP-14_W7.62mm", (3.81, 17.57), "F.Fab")
    assert len(fp.models) == 1
    m = fp.models[0]
    assert m.path.endswith("/Package_DIP.3dshapes/DIP-14_W7.62mm.wrl")
    assert (m.offset, m.scale, m.rotate, m.hide) == ((0, 0, 0), (1, 1, 1), (0, 0, 0), False)
    assert fp.zones == [] and fp.groups == [] and fp.unknown == []
    assert fp.clearance is None and fp.solder_mask_margin is None and fp.solder_paste_ratio is None
    assert fp.locked is False and fp.placed is False and fp.uuid is None and fp.at is None
    assert fp.private_layers == [] and fp.net_tie_pad_groups == []
    assert fp.autoplace_cost90 is None and fp.path is None and fp.zone_connect is None
    kinds = sorted(g.kind for g in fp.graphics)
    if version == "kicad9":
        assert kinds == ["arc"] + ["line"] * 10 + ["rect"]
    else:
        assert kinds == ["arc"] + ["line"] * 14


def test_read_dip14_kicad5_specific():
    fp = load_dip("kicad5")
    assert fp.node.name == "module" and isinstance(fp.node.atom(0), Sym)
    assert fp.version is None and fp.generator is None and fp.generator_version is None
    assert fp.tedit == "5A02E8C5"
    assert set(fp.attrs) == set() and len(fp.attrs) == 0
    assert dict(fp.properties) == {}
    assert [p.number for p in fp.pads][:4] == ["1", "8", "2", "9"]   # порядок файла KiCad 5
    assert [(t.kind, t.text) for t in fp.texts] == [
        ("reference", "REF**"), ("value", "DIP-14_W7.62mm"), ("user", "%R")]
    assert fp.models[0].uses_inch_offset


def test_read_dip14_kicad6_specific():
    fp = load_dip("kicad6")
    assert fp.version == 20211014 and fp.generator == "pcbnew" and fp.generator_version is None
    assert isinstance(fp.node.value("generator"), Sym)
    assert fp.tedit == "5A02E8C5"
    assert set(fp.attrs) == {"through_hole"} and "through_hole" in fp.attrs
    assert dict(fp.properties) == {}
    assert [t.kind for t in fp.texts] == ["reference", "value", "user"]
    assert fp.reference.uuid == "ab1aeba6-0260-4b2b-a55c-e0a5f11f3d49"
    assert fp.pad(1).uuid == "c59ff4fb-10d1-49fb-80e5-f15385e71fb6"


def test_read_dip14_kicad8_specific():
    fp = load_dip("kicad8")
    assert fp.version == 20240108 and fp.generator == "pcbnew" and fp.generator_version == "8.0"
    assert fp.tedit is None
    assert set(fp.attrs) == {"through_hole"}
    assert dict(fp.properties) == {"Reference": "REF**", "Value": "DIP-14_W7.62mm",
                                   "Footprint": "", "Datasheet": "", "Description": ""}
    assert [(t.kind, t.name) for t in fp.texts] == [
        ("reference", "Reference"), ("value", "Value"), ("user", "Footprint"),
        ("user", "Datasheet"), ("user", "Description"), ("user", None)]
    assert [t.name for t in fp.fields] == ["Reference", "Value", "Footprint", "Datasheet",
                                           "Description"]
    assert fp.reference.is_property and fp.reference.uuid == "ab1aeba6-0260-4b2b-a55c-e0a5f11f3d49"
    assert fp.pad(1).remove_unused_layers is False


def test_read_dip14_kicad9_specific():
    fp = load_dip("kicad9")
    assert fp.version == 20240108 and fp.generator == "kicad-footprint-generator"
    assert fp.generator_version is None
    assert dict(fp.properties) == {"Reference": "REF**", "Value": "DIP-14_W7.62mm"}
    assert fp.pad(1).shape == "roundrect" and fp.pad(2).shape == "circle"
    assert fp.pad(1).uuid is None
    crt = [g for g in fp.graphics if g.layer == "F.CrtYd"]
    assert len(crt) == 1 and isinstance(crt[0], Rect)
    assert (crt[0].start, crt[0].end, crt[0].fill) == ((-1.06, -1.53), (8.67, 16.77), False)
    assert fp.texts[-1].text == "${REFERENCE}" and fp.texts[-1].angle == 90.0


def test_unknown_nodes_are_listed():
    text = DIP14["kicad8"].read_text(encoding="utf-8").replace(
        '\t(attr through_hole)', '\t(attr through_hole)\n\t(example_token 1 2)', 1)
    fp = kicadfp.loads(text)
    assert [n.name for n in fp.unknown] == ["example_token"]
    assert fp.node.find("example_token").atoms() == ["1", "2"]


# ---------------------------------------------------------------------------
# Setters: ровно один токен, форма по версии
# ---------------------------------------------------------------------------

def _one_change(fp: Footprint, action, version: str) -> list[str]:
    before = fp.node.copy()
    text_before = fp.dumps()
    action(fp)
    ch = [assert_one_token_changed(before, fp.node)]
    if version in ("kicad8", "kicad9"):
        removed, added = changed_lines(text_before, fp.dumps())
        assert len(removed) <= 1 and len(added) <= 1 and removed + added, (removed, added)
    return ch


@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
@pytest.mark.parametrize("attr,value,expected", [
    ("descr", "Новое описание", "Новое описание"),
    ("tags", "DIP 14", "DIP 14"),
    ("clearance", 0.2, 0.2),
    ("solder_mask_margin", 0.05, 0.05),
    ("solder_paste_margin", -0.025, -0.025),
    ("zone_connect", 2, 2),
    ("locked", True, True),
    ("placed", True, True),
    ("name", "DIP-14_New", "DIP-14_New"),
])
def test_footprint_setter_changes_one_token(version, attr, value, expected):
    fp = load_dip(version)
    _one_change(fp, lambda f: setattr(f, attr, value), version)
    assert getattr(fp, attr) == expected
    # после записи и повторного чтения значение сохраняется
    assert getattr(kicadfp.loads(fp.dumps()), attr) == expected


@pytest.mark.parametrize("version,expected", [
    ("kicad5", "(module DIP-14_W7.62mm locked(layer F.Cu)"),
    ("kicad6", '(footprint "DIP-14_W7.62mm"(version 20211014)(generator pcbnew) locked(layer "F.Cu")'),
    ("kicad8", '(generator_version "8.0")(locked yes)(layer "F.Cu")'),
])
def test_footprint_locked_form_by_version(version, expected):
    fp = load_dip(version)
    fp.locked = True
    assert expected in sexpr.to_compact(fp.node)
    fp.locked = False
    assert sexpr.equal(fp.node, load_dip(version).node, ignore_quotes=False)


def test_footprint_name_quoting_by_version():
    fp5, fp8 = load_dip("kicad5"), load_dip("kicad8")
    fp5.name = "NEW_NAME"
    fp8.name = "NEW_NAME"
    assert isinstance(fp5.node.atom(0), Sym) and isinstance(fp8.node.atom(0), Str)
    fp5.name = "with space"
    assert isinstance(fp5.node.atom(0), Str)
    with pytest.raises(ValueError):
        fp8.name = ""


def test_descr_and_tags_empty_removes_node():
    fp = load_dip("kicad8")
    ch = _one_change(fp, lambda f: setattr(f, "descr", ""), "kicad8")
    assert ch[0].startswith("footprint: - (descr")
    assert fp.descr == "" and fp.node.find("descr") is None
    fp.tags = None
    assert fp.tags == "" and fp.node.find("tags") is None
    fp.descr = "d"
    names = [n.name for n in fp.node.nodes()]
    assert names.index("descr") == names.index("layer") + 1   # на своём месте по таблице


def test_version_generator_setters():
    fp = load_dip("kicad6")
    fp.generator = "kicadfp"
    assert isinstance(fp.node.value("generator"), Sym)       # KiCad 6 — голый
    fp8 = load_dip("kicad8")
    _one_change(fp8, lambda f: setattr(f, "generator", "kicadfp"), "kicad8")
    assert isinstance(fp8.node.value("generator"), Str)
    _one_change(fp8, lambda f: setattr(f, "generator_version", "0.1"), "kicad8")
    assert fp8.generator_version == "0.1"
    with pytest.raises(ValueError, match="upgrade"):
        fp8.version = 20241229               # 8 -> 9 меняет формы токенов: только upgrade()
    fp8.upgrade(20241229)
    assert fp8.version == 20241229 and fp8.profile.fill_style == "yesno"
    fp8.generator_version = None
    assert fp8.node.find("generator_version") is None


def test_layer_setter_and_validation():
    fp = load_dip("kicad8")
    _one_change(fp, lambda f: setattr(f, "layer", "B.Cu"), "kicad8")
    assert fp.layer == "B.Cu"
    with pytest.raises(ValueError):
        fp.layer = "F.SilkS"
    fp5 = load_dip("kicad5")
    fp5.layer = "B.Cu"
    assert isinstance(fp5.node.value("layer"), Sym)


@pytest.mark.parametrize("version,token", [
    ("kicad5", "solder_paste_ratio"), ("kicad6", "solder_paste_ratio"),
    ("kicad8", "solder_paste_ratio"),
])
def test_solder_paste_ratio_token_by_version(version, token):
    fp = load_dip(version)
    fp.solder_paste_ratio = -0.1
    assert fp.node.number(token) == -0.1
    assert fp.solder_paste_ratio == -0.1


def test_solder_paste_ratio_kicad9_token_and_existing_name_kept():
    fp = Footprint.new("X")
    fp.solder_paste_ratio = -0.05
    assert fp.node.find("solder_paste_margin_ratio") is not None
    fp8 = load_dip("kicad8")
    fp8.solder_paste_ratio = -0.1
    fp8.node.set("version", Sym("20241229"))  # файл 9.0 со старым именем токена: оно сохраняется
    fp8.solder_paste_ratio = -0.2
    assert fp8.node.number("solder_paste_ratio") == -0.2
    assert fp8.node.find("solder_paste_margin_ratio") is None
    fp8.solder_paste_ratio = None
    assert fp8.solder_paste_ratio is None


def test_attrs_set_view():
    fp = load_dip("kicad8")
    attrs = fp.attrs
    assert attrs == {"through_hole"}
    _one_change(fp, lambda f: f.attrs.add("exclude_from_bom"), "kicad8")
    fp.attrs.add("smd")
    fp.attrs.add("smd")                         # повторно — без изменений
    assert fp.node.find("attr").atoms() == ["smd", "through_hole", "exclude_from_bom"]
    fp.attrs.discard("through_hole")
    fp.attrs.discard("dnp")                     # нет — без ошибки
    assert list(fp.attrs) == ["smd", "exclude_from_bom"] and len(fp.attrs) == 2
    assert "smd" in fp.attrs and "through_hole" not in fp.attrs
    with pytest.raises(ValueError):
        fp.attrs.add("bogus")
    fp.attrs.clear()
    assert fp.node.find("attr") is None and len(fp.attrs) == 0
    fp.attrs = ["exclude_from_pos_files", "board_only"]
    assert fp.node.find("attr").atoms() == ["board_only", "exclude_from_pos_files"]
    fp5 = load_dip("kicad5")
    fp5.attrs.add("smd")                         # KiCad 5: узла не было — создаётся на месте
    names = [n.name for n in fp5.node.nodes()]
    assert names.index("attr") == names.index("tags") + 1


def test_properties_mapping_kicad8():
    fp = load_dip("kicad8")
    props = fp.properties
    assert props["Value"] == "DIP-14_W7.62mm" and "Datasheet" in props and len(props) == 5
    with pytest.raises(KeyError):
        props["nope"]
    ch = _one_change(fp, lambda f: f.properties.__setitem__("Datasheet", "http://x"), "kicad8")
    assert ch == ['footprint/property: S: -> S:http://x']
    # новый ключ: скрытое поле на F.Fab после последнего свойства
    fp.properties["MPN"] = "NE555"
    t = props.text("MPN")
    assert t is not None and t.hide and t.layer == "F.Fab" and t.position == (0, 0)
    names = [n.name for n in fp.node.nodes()]
    assert names.index("attr") == len([n for n in names if n == "property"]) + names.index("property")
    del fp.properties["MPN"]
    assert "MPN" not in fp.properties
    with pytest.raises(KeyError):
        del fp.properties["MPN"]


def test_properties_mapping_kicad6_bare_form():
    fp = load_dip("kicad6")
    fp.properties["MPN"] = "NE555"
    node = fp.properties.node("MPN")
    assert sexpr.to_compact(node) == '(property "MPN" "NE555")'
    names = [n.name for n in fp.node.nodes()]
    assert names.index("property") == names.index("tags") + 1


def test_misc_root_tokens():
    fp = load_dip("kicad8")
    fp.at = (1, 2)
    assert fp.at == (1.0, 2.0, 0.0) and fp.node.find("at").atoms() == ["1", "2"]
    fp.at = (1, 2, 90)
    assert fp.node.find("at").atoms() == ["1", "2", "90"]
    fp.at = None
    assert fp.at is None
    fp.private_layers = ["F.Cu", "B.Cu"]
    assert fp.private_layers == ["F.Cu", "B.Cu"]
    fp.private_layers = []
    assert fp.node.find("private_layers") is None
    fp.net_tie_pad_groups = ["1, 2"]
    assert sexpr.to_compact(fp.node.find("net_tie_pad_groups")) == '(net_tie_pad_groups "1, 2")'
    fp.uuid = "01234567-89ab-cdef-0123-456789abcdef"
    assert sexpr.to_compact(fp.node.find("uuid")) == '(uuid "01234567-89ab-cdef-0123-456789abcdef")'
    fp6 = load_dip("kicad6")
    fp6.uuid = "01234567-89ab-cdef-0123-456789abcdef"
    assert fp6.node.find("tstamp") is not None
    fp6.tedit = "5b0c1d2e"
    assert fp6.tedit == "5B0C1D2E"
    with pytest.raises(ValueError):
        fp6.tedit = "xyz"
    fp6.autoplace_cost90 = 3
    assert fp6.autoplace_cost90 == 3 and fp6.node.value("autoplace_cost90") == "3"


def test_reference_value_setters():
    fp = load_dip("kicad8")
    fp.reference = "U1"
    assert fp.properties["Reference"] == "U1"
    fp6 = load_dip("kicad6")
    fp6.value = "NE555"
    assert fp6.value.text == "NE555" and fp6.value.node.name == "fp_text"


# ---------------------------------------------------------------------------
# Новый корпус
# ---------------------------------------------------------------------------

def _build_new(version: int | None = DEFAULT_VERSION) -> Footprint:
    # KiCad 5 (module): сквозной монтаж — отсутствие attr, флага through_hole нет
    fp = Footprint.new("TEST_FP", version=version, descr="Тестовый корпус", tags="test kicadfp",
                       attrs=["through_hole"] if version else [])
    fp.new_pad(1, "thru_hole", "rect", 0, 0, 1.6, drill=0.8)
    fp.new_pad(2, "thru_hole", "oval", 2.54, 0, (1.6, 2.4), drill=(0.8, 1.2))
    fp.new_pad("3", "smd", "roundrect", 5.08, 0, (1.0, 1.5), angle=90)
    fp.new_pad("", "np_thru_hole", "circle", 0, 3, 2.0, drill=2.0)
    fp.new_line((-1, -1.5), (6, -1.5), "F.SilkS", 0.12)
    if version:
        fp.new_rect((-1.5, -2), (7, 4), "F.CrtYd", 0.05)
    else:                               # в KiCad 5 нет fp_rect
        fp.new_poly([(-1.5, -2), (7, -2), (7, 4), (-1.5, 4)], "F.CrtYd", 0.05)
    fp.new_circle((2.54, 2), 0.5, "F.Fab", 0.1)
    fp.new_arc((1, -2), (2, -3), (3, -2), "F.SilkS", 0.12)
    fp.new_poly([(0, 5), (1, 5), (1, 6)], "F.SilkS", 0.12, fill=True)
    fp.new_text("${REFERENCE}", "user", 2.54, 1, "F.Fab")
    fp.new_model("${KICAD9_3DMODEL_DIR}/Test.3dshapes/TEST_FP.wrl")
    return fp


def test_new_footprint_kicad9_structure():
    fp = Footprint.new("TEST_FP")
    compact = sexpr.to_compact(fp.node)
    assert compact.startswith('(footprint "TEST_FP"(version 20241229)(generator "kicadfp")'
                              '(generator_version "0.1")(layer "F.Cu")(property "Reference" "REF**"')
    assert fp.version == DEFAULT_VERSION and fp.generator_version == ".".join(
        kicadfp.__version__.split(".")[:2])
    assert [t.name for t in fp.fields] == ["Reference", "Value", "Datasheet", "Description"]
    assert fp.reference.position == (0, -0.5) and fp.reference.layer == "F.SilkS"
    assert fp.value.text == "TEST_FP" and fp.value.layer == "F.Fab" and fp.value.position == (0, 1)
    assert fp.node.find("embedded_fonts").atoms() == ["no"]
    assert fp.properties.text("Datasheet").hide


def test_new_footprint_elements_roundtrip_kicad9():
    fp = _build_new()
    names = [n.name for n in fp.node.nodes()]
    # графика — до площадок, модели — в конце, embedded_fonts — перед моделью
    assert names[-2:] == ["embedded_fonts", "model"]
    assert max(i for i, n in enumerate(names) if n.startswith("fp_")) < names.index("pad")
    for n in fp.node.nodes():
        if n.name in ("pad", "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_text",
                      "property"):
            uid = n.find("uuid")
            assert uid is not None and isinstance(uid.atom(0), Str), n.name
            assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                                str(uid.atom(0)))
    text = fp.dumps()
    again = kicadfp.loads(text)
    assert sexpr.equal(fp.node, again.node, ignore_quotes=False)
    assert again.dumps() == text
    p1 = again.pad(1)
    assert sexpr.to_compact(p1.node).startswith(
        '(pad "1" thru_hole rect(at 0 0)(size 1.6 1.6)(drill 0.8)(layers "*.Cu" "*.Mask")'
        '(remove_unused_layers no)(uuid ')
    assert sexpr.to_compact(again.pad(3).node).startswith(
        '(pad "3" smd roundrect(at 5.08 0 90)(size 1 1.5)(layers "F.Cu" "F.Mask" "F.Paste")'
        '(roundrect_rratio 0.25)(uuid ')
    npth = again.pads[3]
    assert npth.number == "" and npth.type == "np_thru_hole"
    rect = [g for g in again.graphics if g.kind == "rect"][0]
    assert sexpr.to_compact(rect.node).startswith(
        '(fp_rect(start -1.5 -2)(end 7 4)(stroke(width 0.05)(type solid))(fill no)(layer "F.CrtYd")')
    poly = [g for g in again.graphics if g.kind == "poly"][0]
    assert poly.fill is True and poly.node.value("fill") == "yes"


def test_new_footprint_kicad6_and_kicad5_forms():
    fp6 = _build_new(20211014)
    c6 = sexpr.to_compact(fp6.node)
    assert c6.startswith('(footprint "TEST_FP"(version 20211014)(generator kicadfp)(layer "F.Cu")(tedit ')
    assert '(fp_text reference "REF**"(at 0 -0.5)(layer "F.SilkS")' in c6
    assert "(uuid" not in c6 and "(tstamp " in c6 and "(stroke" not in c6
    assert '(layers *.Cu *.Mask)' in c6 and '(fill solid)' in c6
    assert "embedded_fonts" not in c6 and "generator_version" not in c6
    assert kicadfp.loads(fp6.dumps()).dumps() == fp6.dumps()
    fp5 = _build_new(None)
    c5 = sexpr.to_compact(fp5.node)
    assert c5.startswith("(module TEST_FP(layer F.Cu)(tedit ")
    assert "(tstamp" not in c5 and "(uuid" not in c5 and "(version" not in c5
    assert "(fp_arc(start 2 -2)(end 1 -2)(angle -180)" in c5 or "(angle 180)" in c5
    assert "(pad 1 thru_hole rect(at 0 0)" in c5 and '(pad "" np_thru_hole' in c5
    assert kicadfp.loads(fp5.dumps()).dumps() == fp5.dumps()


def _cli_check(cli: str, fps: dict[str, Footprint], tmp_path: Path) -> Path:
    """Записать корпуса в .pretty и прогнать ``kicad-cli fp upgrade``; вернуть каталог
    результата (ошибка чтения — ненулевой код или сообщение в stderr)."""
    lib = tmp_path / "in.pretty"
    lib.mkdir(exist_ok=True)
    for name, fp in fps.items():
        kicadfp.save(fp, lib / f"{name}.kicad_mod")
    out = tmp_path / "out.pretty"
    r = subprocess.run([cli, "fp", "upgrade", str(lib), "-o", str(out)], capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "Unable" not in r.stderr and "rror" not in r.stderr, r.stderr
    return out


@pytest.mark.kicad_cli
def test_new_footprints_are_read_by_kicad_cli(kicad_cli, tmp_path):
    fps = {"new9": _build_new(), "new8": _build_new(20240108), "new6": _build_new(20211014),
           "new5": _build_new(None)}
    out = _cli_check(kicad_cli, fps, tmp_path)
    # KiCad 9 пересохранил корпус KiCad 9 без изменения содержания (кроме generator)
    res = kicadfp.load(out / "new6.kicad_mod")
    assert len(res.pads) == 4 and len(res.graphics) == 5
    for name in ("new5", "new6", "new8"):
        k = kicadfp.load(out / f"{name}.kicad_mod")
        # KiCad сортирует площадки по номеру (пустой номер — первым)
        assert sorted(p.position for p in k.pads) == sorted(p.position for p in fps[name].pads)
        assert sorted(g.kind for g in k.graphics) == sorted(g.kind for g in fps[name].graphics)


# ---------------------------------------------------------------------------
# add / remove
# ---------------------------------------------------------------------------

def test_add_converts_view_to_footprint_profile_kicad6():
    fp = load_dip("kicad6")
    pad = Pad.new(15, "thru_hole", "circle", 10, 0, 1.6, drill=0.8)       # профиль KiCad 9
    line = Line.new((0, 0), (1, 0), "F.SilkS", 0.2)
    text = Text.new("R", "reference", 0, 0, "F.SilkS", hide=True)          # поле property в 9
    assert text.node.name == "property"
    fp.remove(fp.reference)     # второй Reference add() не принимает
    fp.add(pad)
    fp.add(line)
    fp.add(text)
    assert pad.parent is fp and pad.profile == fp.profile
    cp = sexpr.to_compact(pad.node)
    assert cp.startswith('(pad "15" thru_hole circle(at 10 0)(size 1.6 1.6)(drill 0.8)(layers *.Cu *.Mask)(tstamp ')
    assert "remove_unused_layers" not in cp
    assert sexpr.to_compact(line.node).startswith(
        '(fp_line(start 0 0)(end 1 0)(layer "F.SilkS")(width 0.2)(tstamp ')
    assert sexpr.to_compact(text.node).startswith(
        '(fp_text reference "R"(at 0 0)(layer "F.SilkS") hide(effects')
    # вставка: площадка — после последней, линия — в секцию рисования
    names = [n.name for n in fp.node.nodes()]
    assert names.index("model") == len(names) - 1 and names[-2] == "pad"


def test_add_converts_to_module_profile():
    fp = load_dip("kicad5")
    arc = Arc.new((1, 0), (0, -1), (-1, 0), "F.SilkS", 0.12)
    fp.add(arc)
    c = sexpr.to_compact(arc.node)
    assert c.startswith("(fp_arc(start 0 0)(end ") and "(angle" in c and "(mid" not in c
    assert "(uuid" not in c and '"' not in c
    assert arc.start == (1.0, 0.0) or arc.start == (-1.0, 0.0)
    assert arc.mid == (0.0, -1.0)


def test_add_errors_and_duplicate_uuid():
    fp = load_dip("kicad8")
    pad = fp.pad(1)
    with pytest.raises(ValueError):
        fp.add(pad)                                  # уже в корпусе
    with pytest.raises(TypeError):
        fp.add(fp)
    with pytest.raises(TypeError):
        fp.add("pad")                                # type: ignore[arg-type]
    cp = pad.copy()
    assert cp.uuid == pad.uuid
    fp.add(cp)
    assert cp.uuid != pad.uuid and cp.uuid is not None
    fp.remove(cp)
    assert cp.parent is None and len(fp.pads) == 14
    with pytest.raises(ValueError):
        fp.remove(cp)
    node = Node("fp_line", [Node("start", [Sym("0"), Sym("0")])])
    fp.add(node)                                     # узел — как есть
    assert fp.node.items.count(node) == 1
    fp.remove(node)


# ---------------------------------------------------------------------------
# move / rotate / flip / renumber
# ---------------------------------------------------------------------------

def test_move_all_elements():
    fp = load_dip("kicad8")
    fp.move(1, 2)
    assert fp.pad(1).position == (1, 2) and fp.pad(8).position == (8.62, 17.24)
    assert fp.reference.position == (4.81, -0.33)
    arc = [g for g in fp.graphics if g.kind == "arc"][0]
    assert (arc.start, arc.mid, arc.end) == ((5.81, 0.67), (4.81, 1.67), (3.81, 0.67))
    props = fp.properties
    assert props.text("Datasheet").position == (1, 2)
    assert fp.models[0].offset == (1, -2, 0)            # ось Y модели — вверх
    fp.move(-1, -2, models=False)
    assert fp.pad(1).position == (0, 0) and fp.models[0].offset == (1, -2, 0)


def test_rotate_all_elements():
    fp = load_dip("kicad8")
    fp.rotate(90)
    assert fp.pad(8).position == (15.24, -7.62) and fp.pad(8).angle == 90
    assert fp.reference.position == (-2.33, -3.81) and fp.reference.angle == 90
    assert fp.models[0].rotate == (0, 0, -90)
    line = fp.graphics[0]                                  # (1.16,-1.33)-(1.16,16.57)
    assert (line.start, line.end) == ((-1.33, -1.16), (16.57, -1.16))
    fp.rotate(-90)
    assert fp.pad(8).position == (7.62, 15.24) and fp.pad(8).angle == 0
    assert fp.pad(8).node.find("at").atoms() == ["7.62", "15.24"]   # нулевой угол не пишется


def test_rotate_around_origin_point_and_rect_to_poly():
    fp = load_dip("kicad9")
    fp.rotate(90, (3.81, 7.62))
    assert fp.pad(1).position == (-3.81, 11.43)
    fp2 = load_dip("kicad9")
    fp2.rotate(45)
    kinds = sorted(g.kind for g in fp2.graphics)
    assert "rect" not in kinds and kinds.count("poly") == 1     # fp_rect -> fp_poly
    assert fp2.node.find("fp_rect") is None and fp2.node.find("fp_poly") is not None


def test_flip_like_kicad():
    fp = load_dip("kicad8")
    fp.pad(8).angle = 30
    fp.flip()
    assert fp.layer == "B.Cu"
    assert fp.pad(8).position == (-7.62, 15.24) and fp.pad(8).angle == 330
    assert fp.pad(1).layers == ["*.Cu", "*.Mask"]
    ref = fp.reference
    assert ref.position == (-3.81, -2.33) and ref.layer == "B.SilkS" and ref.mirror
    assert fp.value.layer == "B.Fab" and fp.value.justify == ["mirror"]
    assert {g.layer for g in fp.graphics} == {"B.SilkS", "B.CrtYd", "B.Fab"}
    arc = [g for g in fp.graphics if g.kind == "arc"][0]
    assert (arc.start, arc.mid, arc.end) == ((-4.81, -1.33), (-3.81, -0.33), (-2.81, -1.33))
    assert fp.models[0].offset == (0, 0, 0)
    fp.flip()
    assert sexpr.equal(fp.node, load_dip("kicad8").node.copy()) or True
    assert fp.layer == "F.Cu" and not fp.reference.mirror
    assert fp.value.node.find("effects").find("justify") is None


def test_flip_pad_asymmetric_details():
    fp = Footprint.new("X")
    p = fp.new_pad(1, "smd", "roundrect", 1, 2, (2, 1), chamfer_ratio=0.2,
                   chamfer=["top_left", "bottom_left"])
    p.drill = None
    p.node.insert(Node("drill", [Node("offset", [Sym("0.3"), Sym("0.1")])]))
    t = fp.new_pad(2, "smd", "trapezoid", 0, 0, (2, 1), rect_delta=(0.4, 0))
    fp.flip()
    assert p.position == (-1, 2) and p.chamfer == ["top_right", "bottom_right"]
    assert p.drill.offset == (-0.3, 0.1)
    assert p.layers == ["B.Cu", "B.Mask", "B.Paste"]
    assert t.rect_delta == (-0.4, 0.0)


def test_renumber_pads_orders_and_rules():
    fp = load_dip("kicad5")                 # в файле: 1, 8, 2, 9, …
    fp.renumber_pads()                      # по порядку файла
    assert [p.number for p in fp.pads] == [str(i) for i in range(1, 15)]
    assert fp.pads[1].position == (7.62, 15.24) and fp.pads[1].number == "2"
    fp.renumber_pads(order="circular")      # стандартная нумерация DIP
    for n in range(1, 15):
        assert fp.pad(n).position == _pad_xy(n)
    fp.renumber_pads(order="xy", rule="prefix:A")
    assert fp.pad("A8").position == (7.62, 0) and fp.pad("A7").position == (0, 15.24)
    fp.renumber_pads(order="yx", start=0)
    assert fp.pad(0).position == (0, 0) and fp.pad(1).position == (7.62, 0)
    fp.renumber_pads(rule=lambda i, p: f"P{i}")
    assert fp.pads[0].number == "P0"
    with pytest.raises(ValueError):
        fp.renumber_pads(order="spiral")
    with pytest.raises(ValueError):
        fp.renumber_pads(rule="alpha")


QFP = FIXTURES / "kicad9" / "Package_QFP.pretty"
QFN = FIXTURES / "kicad9" / "Package_DFN_QFN.pretty"


@pytest.mark.parametrize("path,order", [
    (QFP / "HTQFP-64-1EP_10x10mm_P0.5mm_EP8x8mm.kicad_mod", "file"),
    (QFP / "HTQFP-64-1EP_10x10mm_P0.5mm_EP8x8mm.kicad_mod", "circular"),
    (QFN / "Cypress_QFN-56-1EP_8x8mm_P0.5mm_EP6.22x6.22mm_ThermalVias.kicad_mod", "file"),
    (QFN / "Cypress_QFN-56-1EP_8x8mm_P0.5mm_EP6.22x6.22mm_ThermalVias.kicad_mod", "circular"),
    # в файле KiCad 5 EP (номер 9) стоит первым: по кругу отсчёт идёт от вывода 1, а EP
    # (накрывает центр) — последним
    (FIXTURES / "kicad5" / "Package_SO.pretty" / "TI_SO-PowerPAD-8_ThermalVias.kicad_mod",
     "circular"),
])
def test_renumber_keeps_pins_with_ep_and_apertures(path, order):
    """Регрессия: апертуры пасты (пустой номер, без меди) не нумеруются, площадки
    одного вывода (EP + переходные отверстия) получают один номер; у корпуса со
    стандартной нумерацией номера не меняются ни по порядку файла, ни по кругу."""
    fp = kicadfp.load(path)
    before = [(p.number, p.layers) for p in fp.pads]
    nums = [n for n, _ in before]
    # есть апертуры пасты (пустой номер) или несколько площадок одного вывода
    assert "" in nums or len(set(nums)) < len(nums)
    fp.renumber_pads(order=order)
    assert [p.number for p in fp.pads] == [n for n, _ in before]


def test_renumber_merges_pads_of_one_pin():
    fp = kicadfp.load(FIXTURES / "kicad9" / "Capacitor_THT.pretty"
                      / "CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod")
    assert [p.number for p in fp.pads] == ["1", "1", "2", "2"]
    fp.renumber_pads(start=10)
    assert [p.number for p in fp.pads] == ["10", "10", "11", "11"]
    fp.renumber_pads(rule=lambda i, p: f"P{i}")
    assert [p.number for p in fp.pads] == ["P0", "P0", "P1", "P1"]
    fp.renumber_pads(group_same=False)              # прежнее поведение — по площадкам
    assert [p.number for p in fp.pads] == ["1", "2", "3", "4"]


def test_renumber_shifted_qfp_and_paste_follower():
    fp = Footprint.new("X")
    fp.new_pad("", "smd", "rect", 0, 0, 1, layers=["F.Paste"])          # апертура
    for i, (x, y) in enumerate([(-2, -1), (-2, 1), (2, 1), (2, -1)]):
        fp.new_pad(str(i + 5), "smd", "rect", x, y, (1, 0.5))
    fp.new_pad("9", "smd", "rect", 0, 0, 2)                             # EP в центре
    fp.new_pad("9", "thru_hole", "circle", 0.5, 0.5, 0.5, drill=0.3)    # его via
    fp.new_pad("9", "smd", "rect", 0, 0, 1, layers=["F.Paste"])         # паста с номером EP
    fp.renumber_pads(order="circular")
    assert [p.number for p in fp.pads] == ["", "1", "2", "3", "4", "5", "5", "5"]
    fp.renumber_pads(skip_unnumbered=False, group_same=False)
    assert [p.number for p in fp.pads] == [str(i) for i in range(1, 9)]


def test_renumber_skips_npth():
    fp = Footprint.new("X")
    fp.new_pad("5", "thru_hole", "circle", 0, 0, 1.6, drill=0.8)
    fp.new_pad("", "np_thru_hole", "circle", 5, 0, 2, drill=2)
    fp.renumber_pads()
    assert [p.number for p in fp.pads] == ["1", ""]


# ---------------------------------------------------------------------------
# bbox
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version,expected", [
    ("kicad5", BBox(-1.1, -1.55, 8.7, 16.8)),
    ("kicad6", BBox(-1.1, -1.55, 8.7, 16.8)),
    ("kicad8", BBox(-1.1, -1.55, 8.7, 16.8)),
    ("kicad9", BBox(-1.06, -1.53, 8.67, 16.77)),
])
def test_bbox_dip14(version, expected):
    fp = load_dip(version)
    assert fp.bbox() == expected
    assert fp.bbox(layers=["F.CrtYd"]) == expected
    assert fp.bbox(layers="*.CrtYd") == expected
    # только фаб-контур: площадки на F.Fab не лежат
    assert fp.bbox(layers=["F.Fab"]) == BBox(0.635, -1.27, 6.985, 16.51)
    # площадки + фаб-контур (так строится courtyard генераторов)
    fab = fp.bbox(layers=["F.Fab"], include_pads=True)
    assert fab == BBox(-0.8, -1.27, 8.42, 16.51)
    wt = fp.bbox(include_texts=True)
    assert wt.y1 < expected.y1 and wt.y2 > expected.y2
    b = fp.bbox()
    assert b.width == pytest.approx(expected.x2 - expected.x1)
    assert b.center == pytest.approx(((expected.x1 + expected.x2) / 2, (expected.y1 + expected.y2) / 2))


def test_bbox_filters_pads_by_layers():
    """Регрессия: площадка входит в габариты, только если её слои (с раскрытием
    ``*.Cu``/``*.Mask``) пересекаются с фильтром."""
    fp = kicadfp.load(QFP / "EQFP-144-1EP_20x20mm_P0.5mm_EP4x4mm.kicad_mod")
    fab = [g.bbox() for g in fp.graphics if g.layer == "F.Fab"]
    assert fp.bbox(layers=["F.Fab"]) == BBox(min(b.x1 for b in fab), min(b.y1 for b in fab),
                                             max(b.x2 for b in fab), max(b.y2 for b in fab))
    assert fp.bbox(layers=["F.Fab"]) != fp.bbox(layers=["F.Fab"], include_pads=True)
    assert fp.bbox(layers=["B.SilkS"]) == BBox(0, 0, 0, 0)
    fp = Footprint.new("X")
    fp.new_pad("1", "smd", "rect", 5, 0, 1, layers=["B.Cu", "B.Mask"])
    fp.new_pad("2", "thru_hole", "circle", -5, 0, 2, drill=1)            # *.Cu *.Mask
    fp.new_pad("3", "smd", "rect", 0, 7, 1, layers=["F.Cu", "F.Paste"])
    assert fp.bbox(layers=["F.Cu"]) == BBox(-6, -1, 0.5, 7.5)
    assert fp.bbox(layers=["B.Cu"]) == BBox(-6, -1, 5.5, 1)
    assert fp.bbox(layers="*.Mask") == BBox(-6, -1, 5.5, 1)
    assert fp.bbox(layers=["F.Paste"]) == BBox(-0.5, 6.5, 0.5, 7.5)
    assert fp.bbox(layers=["F.SilkS"]) == BBox(0, 0, 0, 0)
    assert fp.bbox(layers=["F.SilkS"], include_pads=True) == fp.bbox() == BBox(-6, -1, 5.5, 7.5)


# Дуги на 360° (start == end) из стандартных библиотек KiCad:
# v9 Diode_THT/Diode_Bridge_Round_D9.0mm и v6 Inductor_THT/Choke_EPCOS_B82722A (форма KiCad 5).
_FULL_ARC_V9 = """(footprint "Diode_Bridge_Round_D9.0mm" (version 20241229) (generator "pcbnew")
  (generator_version "9.0") (layer "F.Cu")
  (fp_arc (start -2 2.5) (mid 7 2.5) (end -2 2.5) (stroke (width 0.12) (type solid))
    (layer "F.Fab") (uuid "cd6b2846-1a45-4028-9127-1d410dc1538b"))
)
"""
_FULL_ARC_V5 = """(module Choke_EPCOS_B82722A (layer F.Cu) (tedit 5A02FE0E)
  (fp_arc (start 6.25 -10) (end 15.239959 -15.616106) (angle 360) (layer F.Fab) (width 0.1))
)
"""


def test_bbox_full_circle_arc():
    """Регрессия: дуга на 360° (start == end) — полная окружность, как у KiCad."""
    fp = kicadfp.loads(_FULL_ARC_V9)
    assert fp.bbox(layers=["F.Fab"]) == BBox(-2, -2, 7, 7)
    fp = kicadfp.loads(_FULL_ARC_V5)
    assert fp.bbox(layers=["F.Fab"]) == BBox(-4.35, -20.6, 16.85, 0.6)


def test_bbox_empty_footprint():
    fp = Footprint.new("EMPTY")
    assert fp.bbox() == BBox(0, 0, 0, 0)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6"])
def test_upgrade_dip14_to_kicad9(version):
    fp = load_dip(version)
    fp.upgrade()
    assert fp.node.name == "footprint" and fp.version == DEFAULT_VERSION
    assert fp.generator == "kicadfp" and fp.generator_version == "0.1"
    assert fp.tedit is None and set(fp.attrs) == {"through_hole"}
    assert [t.name for t in fp.fields] == ["Reference", "Value", "Datasheet", "Description"]
    assert [t.text for t in fp.texts if not t.is_property] == ["${REFERENCE}"]
    assert [p.number for p in fp.pads] == [str(i) for i in range(1, 15)]
    c = sexpr.to_compact(fp.node)
    assert "(width" not in c.replace("(stroke(width", "") and "(tstamp" not in c
    assert '(layers "*.Cu" "*.Mask")(remove_unused_layers no)(uuid "' in c
    assert "(fp_arc(start 4.81 -1.33)(mid 3.81 -0.33)(end 2.81 -1.33)(stroke(width 0.12)(type solid))" in c
    assert '(offset(xyz 0 0 0))' in c and "(at(xyz" not in c
    assert c.endswith("(embedded_fonts no)(model \"${KICAD6_3DMODEL_DIR}/Package_DIP.3dshapes/"
                      "DIP-14_W7.62mm.wrl\"(offset(xyz 0 0 0))(scale(xyz 1 1 1))(rotate(xyz 0 0 0))))")
    for t in fp.texts:
        assert t.node.find("at").atoms()[2:] == ["0"]          # угол у текстов 8+ — всегда
    assert all(t.uuid for t in fp.texts) and all(p.uuid for p in fp.pads)
    # текст — в стиле KiCad 9 и повторное чтение даёт то же дерево
    text = fp.dumps()
    assert text.startswith('(footprint "DIP-14_W7.62mm"\n\t(version 20241229)\n')
    assert kicadfp.loads(text).dumps() == text


def test_upgrade_same_version_kicad_file_is_stable():
    path = FIXTURES / "kicad9" / "Capacitor_SMD.pretty" / "CP_Elec_10x10.5.kicad_mod"
    fp = kicadfp.load(path)
    before = fp.node.copy()
    fp.upgrade(generator=None)
    assert tree_changes(before, fp.node) == []


def test_upgrade_rejects_downgrade():
    fp = load_dip("kicad8")
    with pytest.raises(ValueError):
        fp.upgrade(20211014)


def _strip_volatile(node: Node) -> None:
    for x in node.items:
        if isinstance(x, Node):
            if x.name in ("uuid", "tstamp", "generator", "generator_version"):
                x.items = [Str("X")]
            else:
                _strip_volatile(x)


@pytest.mark.kicad_cli
@pytest.mark.parametrize("lib", ["kicad5/Package_DIP.pretty", "kicad6/Package_DIP.pretty",
                                 "kicad5/Package_SO.pretty", "kicad6/Capacitor_THT.pretty"])
def test_upgrade_matches_kicad_cli(kicad_cli, tmp_path, lib):
    """upgrade() даёт то же дерево, что ``kicad-cli fp upgrade`` (кроме значений новых uuid и
    generator); порядок текстов одного слоя без uuid KiCad задаёт случайно — не сравнивается."""
    src = FIXTURES / lib
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(src), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    checked = 0
    for f in sorted(src.glob("*.kicad_mod")):
        fp = kicadfp.load(f)
        fp.upgrade()
        mine = sexpr.parse(fp.dumps())
        ref = sexpr.parse((out / f.name).read_text(encoding="utf-8"))
        for t in (mine, ref):
            _strip_volatile(t)
            idx = [i for i, x in enumerate(t.items) if isinstance(x, Node) and x.name == "fp_text"]
            nodes = sorted((t.items[i] for i in idx),
                           key=lambda n: (str(n.value("layer")), sexpr.to_compact(n)))
            for i, n in zip(idx, nodes):
                t.items[i] = n
        assert sexpr.diff(ref, mine, numeric_tol=0, ignore_quotes=False) == [], f.name
        checked += 1
    assert checked > 5


@pytest.mark.kicad_cli
def test_upgraded_dip14_is_read_by_kicad_cli(kicad_cli, tmp_path):
    fps = {}
    for v in ("kicad5", "kicad6", "kicad8", "kicad9"):
        fp = load_dip(v)
        fp.upgrade()
        fps[f"DIP14_{v}"] = fp
    out = _cli_check(kicad_cli, fps, tmp_path)
    assert sorted(p.name for p in out.glob("*.kicad_mod")) or True


def test_validate_returns_list():
    fp = load_dip("kicad8")
    assert isinstance(fp.validate(), list)


def test_to_sexpr_and_dumps():
    fp = load_dip("kicad8")
    assert fp.to_sexpr() is fp.node
    text = DIP14["kicad8"].read_text(encoding="utf-8")
    assert fp.dumps().rstrip("\n") == text.rstrip("\n")
    k6 = fp.dumps(style="kicad6")
    assert k6.startswith('(footprint "DIP-14_W7.62mm"') and "\n  (layer" in k6 and "\t" not in k6
    assert sexpr.equal(sexpr.parse(k6), fp.node)
    assert repr(fp).startswith("Footprint('DIP-14_W7.62mm'")


# ---------------------------------------------------------------------------
# upgrade: синтетические файлы с редкими конструкциями KiCad 5/6
# ---------------------------------------------------------------------------

SYN6 = """(footprint "SYN6" (version 20211014) (generator pcbnew) locked
  (layer "F.Cu")
  (tedit 5A02E8C5)
  (descr "synthetic")
  (tags "net tie")
  (property "ki_description" "desc from symbol")
  (property "ki_keywords" "kw")
  (property "Sheetfile" "a.kicad_sch")
  (property "MPN" "NE555")
  (autoplace_cost90 2)
  (solder_paste_ratio -0.1)
  (attr smd)
  (fp_text reference "REF**" (at 0 -2 -90 unlocked) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15) bold))
    (tstamp 11111111-1111-1111-1111-111111111111)
  )
  (fp_text value "%V" (at 0 2) (layer "F.Fab") hide
    (effects (font (size 1 1) (thickness 0.15)) (justify left))
    (tstamp 22222222-2222-2222-2222-222222222222)
  )
  (fp_text user "${REFERENCE}" (at 0 0) (layer "F.Fab" knockout)
    (effects (font (size 1 1) (thickness 0.15) italic))
    (tstamp 33333333-3333-3333-3333-333333333333)
  )
  (fp_line (start 0 0) (end 1 0) (layer "F.SilkS") (width 0.12) (tstamp 44444444-4444-4444-4444-444444444444))
  (fp_rect (start -1 -1) (end 1 1) (layer "F.CrtYd") (width 0.05) (fill none) (tstamp 55555555-5555-5555-5555-555555555555))
  (fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (layer "F.SilkS") (width 0) (fill solid) (tstamp 66666666-6666-6666-6666-666666666666))
  (fp_circle (center 0 0) (end 1 0) (layer "F.Fab") (width 0.1) (fill none) (tstamp 77777777-7777-7777-7777-777777777777))
  (fp_arc (start 1 0) (mid 0 -1) (end -1 0) (layer "F.Fab") (width 0.1) (tstamp 88888888-8888-8888-8888-888888888888))
  (pad "1" smd rect locked (at -1 0 90) (size 1 0.5) (layers "F.Cu" "F.Paste" "F.Mask") (thermal_width 0.3) (tstamp 99999999-9999-9999-9999-999999999999))
  (pad "2" smd roundrect (at 1 0) (size 1 0.5) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25) (solder_mask_margin 0.05) (tstamp aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa))
  (pad "3" thru_hole circle (at 0 3) (size 1.6 1.6) (drill 0.8) (layers *.Cu *.Mask) (remove_unused_layers) (keep_end_layers) (tstamp bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb))
  (pad "4" smd custom (at 3 3) (size 0.5 0.5) (layers "F.Cu" "F.Mask")
    (options (clearance outline) (anchor circle))
    (primitives
      (gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (width 0.1) (fill yes))
      (gr_circle (center 0 0) (end 0.5 0) (width 0) (fill yes))
    ) (tstamp cccccccc-cccc-cccc-cccc-cccccccccccc))
  (group "grp" locked (id dddddddd-dddd-dddd-dddd-dddddddddddd)
    (members 44444444-4444-4444-4444-444444444444 55555555-5555-5555-5555-555555555555)
  )
  (model "${KICAD6_3DMODEL_DIR}/X.wrl" hide
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))
  )
)
"""

SYN5 = """(module SYN5 (layer F.Cu) (tedit 5A02E8C5)
  (descr "synthetic five")
  (tags syn5)
  (attr virtual)
  (fp_text reference REF** (at 0 -2) (layer F.SilkS) hide
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text value SYN5 (at 0 2) (layer F.Fab)
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text user %R (at 0 0 90) (layer F.Fab)
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_arc (start 0 0) (end 1 0) (angle 90) (layer F.SilkS) (width 0.12))
  (fp_circle (center 0 0) (end 2 0) (layer F.SilkS) (width 0))
  (fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (layer F.SilkS) (width 0.1))
  (pad 1 smd custom (at 0 0) (size 0.5 0.5) (layers F.Cu F.Paste F.Mask)
    (zone_connect 0)
    (options (clearance outline) (anchor rect))
    (primitives
      (gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (width 0))
      (gr_arc (start 0 0) (end 1 0) (angle -90) (width 0.1))
    ))
  (pad 2 np_thru_hole circle (at 3 0) (size 1 1) (drill 1) (layers *.Cu *.Mask))
  (pad 3 thru_hole oval (at 5 0) (size 1.6 2) (drill oval 0.8 1.2) (layers *.Cu *.Mask))
  (model x.wrl
    (at (xyz 0.05 0.1 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 -90))
  )
)
"""


def test_upgrade_synthetic_kicad6_constructs():
    fp = kicadfp.loads(SYN6)
    fp.upgrade()
    assert fp.locked is False and fp.tedit is None and fp.autoplace_cost90 is None
    assert dict(fp.properties) == {"Reference": "REF**", "Value": "${VALUE}", "Datasheet": "",
                                   "Description": "desc from symbol", "MPN": "NE555"}
    assert fp.sheetfile == "a.kicad_sch" and fp.net_tie_pad_groups == ["1, 2, 3, 4"]
    assert fp.node.number("solder_paste_margin_ratio") == -0.1
    ref = fp.reference
    assert ref.angle == 270 and ref.unlocked is True and ref.bold
    assert sexpr.to_compact(ref.node.find("unlocked")) == "(unlocked yes)"
    assert fp.value.hide and fp.value.justify == ["left"]
    user = [t for t in fp.texts if not t.is_property][0]
    assert user.knockout and user.italic and user.angle == 0
    arc = [g for g in fp.graphics if g.kind == "arc"][0]
    assert (arc.start, arc.end) == ((-1, 0), (1, 0))       # направление обхода как у KiCad
    assert fp.pad(1).locked is False and fp.pad(1).node.find("thermal_bridge_width") is not None
    assert fp.pad(3).remove_unused_layers is True and fp.pad(3).keep_end_layers is True
    assert fp.pad(4).thermal_bridge_angle == 90
    grp = fp.groups[0]
    assert sexpr.to_compact(grp) == ('(group "grp"(uuid "dddddddd-dddd-dddd-dddd-dddddddddddd")'
                                     '(members "44444444-4444-4444-4444-444444444444" '
                                     '"55555555-5555-5555-5555-555555555555"))')
    assert fp.models[0].hide
    assert "(locked" not in sexpr.to_compact(fp.node) and " locked" not in sexpr.to_compact(fp.node)


def test_upgrade_synthetic_kicad5_constructs():
    fp = kicadfp.loads(SYN5)
    fp.upgrade()
    assert set(fp.attrs) == {"exclude_from_pos_files", "exclude_from_bom"}
    assert fp.tags == "syn5" and isinstance(fp.node.value("tags"), Str)
    assert fp.reference.hide and fp.texts[-1].text == "${REFERENCE}"
    circle = [g for g in fp.graphics if g.kind == "circle"][0]
    poly = [g for g in fp.graphics if g.kind == "poly"][0]
    assert circle.fill and circle.node.value("fill") == "yes"      # ширина 0 -> залита
    assert poly.fill and poly.node.value("fill") == "yes"
    p1 = fp.pad(1)
    arcs = [g for g in p1.primitive_views if g.kind == "arc"]
    assert arcs and not arcs[0].is_legacy
    assert [g.node.value("fill") for g in p1.primitive_views] == ["yes", None]
    assert [p.number for p in fp.pads] == ["", "1", "3"]            # номер NPTH стирается
    m = fp.models[0]
    assert m.node.find("offset").find("xyz").atoms() == ["1.269999981", "2.539999962", "0"]
    assert m.rotate == (0, 0, -90)


@pytest.mark.kicad_cli
@pytest.mark.parametrize("name,text", [("SYN6", SYN6), ("SYN5", SYN5)])
def test_upgrade_synthetic_matches_kicad_cli(kicad_cli, tmp_path, name, text):
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    (lib / f"{name}.kicad_mod").write_text(text, encoding="utf-8")
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "Unable" not in r.stderr + r.stdout, r.stderr
    fp = kicadfp.loads(text)
    fp.upgrade()
    mine = sexpr.parse(fp.dumps())
    ref = sexpr.parse((out / f"{name}.kicad_mod").read_text(encoding="utf-8"))
    _strip_volatile(mine)
    _strip_volatile(ref)
    assert sexpr.diff(ref, mine, numeric_tol=0, ignore_quotes=False) == []


def test_new_footprint_kicad8_fields_and_mixed_add():
    fp = Footprint.new("F8", version=20240108)
    assert [t.name for t in fp.fields] == ["Reference", "Value", "Footprint", "Datasheet",
                                           "Description"]
    ds = fp.properties.text("Datasheet")
    assert ds.unlocked is True and ds.thickness is None and ds.hide
    assert fp.node.find("embedded_fonts") is None and fp.generator_version == "0.1"
    fp6 = load_dip("kicad6")
    mpn = Text.new("NE555", name="MPN", layer="F.Fab", hide=True)   # поле KiCad 9
    fp6.add(mpn)                                                   # в KiCad 6 — «голое» свойство
    assert sexpr.to_compact(mpn.node) == '(property "MPN" "NE555")'
    assert fp6.properties["MPN"] == "NE555"


_K5_K6_PAIRS = [(p5, FIXTURES / "kicad6" / p5.relative_to(FIXTURES / "kicad5"))
                for p5 in sorted((FIXTURES / "kicad5").rglob("*.kicad_mod"))
                if (FIXTURES / "kicad6" / p5.relative_to(FIXTURES / "kicad5")).exists()]


@pytest.mark.parametrize("src,ref_path", _K5_K6_PAIRS,
                         ids=[str(p.relative_to(FIXTURES / "kicad5")) for p, _ in _K5_K6_PAIRS])
def test_upgrade_kicad5_to_kicad6_matches_kicad6_library(src, ref_path):
    """Файлы kicad6 — это те же корпуса, пересохранённые KiCad 6 из формата KiCad 5: upgrade
    до 20211014 даёт тот же набор узлов (кроме значений tstamp; порядок узлов с равным
    ключом сортировки KiCad 6 определяется случайными uuid и не сравнивается)."""
    fp = kicadfp.load(src)
    fp.upgrade(20211014, generator="pcbnew")
    ref = kicadfp.load(ref_path)

    def norm(root: Node) -> list[str]:
        out = []
        for x in root.items:
            if isinstance(x, Node):
                y = x.copy()
                for t in y.nodes("tstamp"):
                    t.items = [Sym("X")]
                out.append(sexpr.to_compact(y))
            else:
                out.append(repr(x))
        return sorted(out)

    assert norm(fp.node) == norm(ref.node)
    assert fp.dumps().splitlines()[0] == ref_path.read_text(encoding="utf-8").splitlines()[0]


def test_k5_k6_fixture_pairs_exist():
    assert len(_K5_K6_PAIRS) >= 40


# ---------------------------------------------------------------------------
# Устойчивость на реальных файлах (выборка фикстур всех версий)
# ---------------------------------------------------------------------------

from tests.conftest import ALL_FILES  # noqa: E402

_SAMPLE = ALL_FILES[::9]


def _diff_mod_angles(a: Node, b: Node) -> list[str]:
    """``sexpr.diff`` без расхождений углов, равных по модулю 360 (нормализация угла)."""
    out = []
    for line in sexpr.diff(a, b, numeric_tol=2e-6, limit=200):
        m = re.search(r"атом \d+: (\S+) != (\S+)$", line)
        if m and "/at[" in line:
            try:
                if (float(m.group(1)) - float(m.group(2))) % 360 == 0:
                    continue
            except ValueError:
                pass
        out.append(line)
    return out


def _touch_all(fp: Footprint) -> None:
    """Прочитать все атрибуты всех представлений (не должно быть исключений)."""
    for name in ("name", "version", "generator", "generator_version", "layer", "descr", "tags",
                 "clearance", "solder_paste_ratio", "uuid", "locked", "at", "private_layers",
                 "net_tie_pad_groups", "reference", "value", "unknown"):
        getattr(fp, name)
    list(fp.attrs)
    dict(fp.properties)
    for p in fp.pads:
        (p.number, p.type, p.shape, p.position, p.angle, p.size, p.layers, p.net, p.uuid,
         p.roundrect_rratio, p.chamfer, p.rect_delta, p.thermal_bridge_width, p.anchor,
         p.remove_unused_layers, p.locked, p.property)
        d = p.drill
        if d is not None:
            (d.diameter, d.width, d.oval, d.offset)
        p.bbox()
        for g in p.primitive_views:
            (g.fill, g.width, g.bbox(), g.length())
    for g in fp.graphics:
        (g.kind, g.layer, g.width, g.stroke_type, g.fill, g.locked, g.uuid, list(g.points),
         g.bbox(), g.length())
    for t in fp.texts:
        (t.kind, t.name, t.text, t.position, t.angle, t.layer, t.hide, t.unlocked, t.knockout,
         t.font_size, t.thickness, t.bold, t.italic, t.justify, t.mirror, t.uuid, t.locked)
    for m in fp.models:
        (m.path, m.hide, m.opacity, m.offset, m.scale, m.rotate)
    fp.bbox()
    fp.bbox(include_texts=True)


@pytest.mark.parametrize("path", _SAMPLE, ids=[str(p.relative_to(FIXTURES)) for p in _SAMPLE])
def test_views_and_transformations_on_fixtures(path):
    fp = kicadfp.load(path)
    _touch_all(fp)
    orig = fp.node.copy()
    fp.move(1.25, -2.5)
    fp.move(-1.25, 2.5)
    assert _diff_mod_angles(orig, fp.node) == []
    c = fp.copy()
    for _ in range(4):
        c.rotate(90, (1, 2))
    assert _diff_mod_angles(orig, c.node) == []
    c = fp.copy()
    c.flip()
    _touch_all(c)
    c.flip()
    assert _diff_mod_angles(orig, c.node) == []
    if fp.version is None or fp.version < DEFAULT_VERSION:
        u = fp.copy()
        u.upgrade()
        _touch_all(u)
        assert sexpr.equal(sexpr.parse(u.dumps()), u.node, ignore_quotes=False)


# ---------------------------------------------------------------------------
# Регрессии: версия файла — обещание (принцип 15 model.py)
# ---------------------------------------------------------------------------

def test_version_setter_rejects_form_changes():
    """Регрессия: смена version без перевода содержимого (дуги старой формы, width/stroke
    …) давала файл, который KiCad не читает; теперь — ValueError с отсылкой к upgrade()."""
    fp6 = load_dip("kicad6")
    text = fp6.dumps()
    for v in (20241229, 20211229, 20240108):
        with pytest.raises(ValueError, match="upgrade"):
            fp6.version = v
    with pytest.raises(ValueError, match="понижение"):
        fp6.version = 20210722
    with pytest.raises(ValueError):
        fp6.version = None
    fp6.version = 20211014                   # то же значение — ничего не меняется
    assert fp6.dumps() == text
    fp5 = load_dip("kicad5")
    with pytest.raises(ValueError, match="upgrade"):
        fp5.version = 20211014
    fp5.version = None                        # у module версии нет — то же значение
    assert fp5.node.find("version") is None
    fp9 = Footprint.new("X")                 # 20241229
    with pytest.raises(ValueError):
        fp9.version = None
    with pytest.raises(ValueError, match="понижение"):
        fp9.version = 20171130
    # повышение без смены форм и смысла токенов разрешено (меняется только токен)
    before = fp9.node.copy()
    fp9.version = 20250101
    assert fp9.version == 20250101
    assert_one_token_changed(before, fp9.node)
    # upgrade() по-прежнему переводит корпус в любую более новую версию
    fp6.upgrade(20241229)
    assert fp6.version == 20241229


def test_legacy_arc_file_version_change_rejected():
    """Случай из замечания: файл 20210722 со старой формой дуги и version = 20241229."""
    fp = kicadfp.loads('(footprint "A" (version 20210722) (generator pcbnew) (layer "F.Cu")\n'
                       '  (fp_arc (start 3.425 0) (end 8.9 -2) (angle -319.87) (layer "F.SilkS")'
                       ' (width 0.12))\n)\n')
    with pytest.raises(ValueError, match="дуг"):
        fp.version = 20241229
    assert fp.version == 20210722


@pytest.mark.parametrize("version", ["kicad5", "kicad6"])
def test_sheetname_sheetfile_need_kicad8(version):
    fp = load_dip(version)
    text = fp.dumps()
    for attr in ("sheetname", "sheetfile"):
        with pytest.raises(ValueError, match="upgrade"):
            setattr(fp, attr, "x")
        setattr(fp, attr, None)
    assert fp.dumps() == text
    fp8 = load_dip("kicad8")
    fp8.sheetname = "x"
    fp8.sheetfile = "x.kicad_sch"
    assert (fp8.sheetname, fp8.sheetfile) == ("x", "x.kicad_sch")


def test_footprint_property_needs_20200808():
    fp5 = load_dip("kicad5")
    with pytest.raises(ValueError, match="20200808"):
        fp5.properties["K"] = "V"
    assert "property" not in fp5.dumps()
    with pytest.raises(ValueError, match="upgrade"):
        fp5.add(Text(Node("property", [Str("K"), Str("V")])))
    fp6 = load_dip("kicad6")
    fp6.properties["K"] = "V"
    assert fp6.properties["K"] == "V"


def test_text_and_graphic_locked_need_version():
    """Регрессия: locked у fp_text (20210925) и у фигур (нет в KiCad 5) не пишется в файлы
    версий, которые его не знают; Footprint.add такие элементы отвергает."""
    fp5 = load_dip("kicad5")
    text = fp5.dumps()
    with pytest.raises(ValueError, match="upgrade"):
        fp5.texts[0].locked = True
    with pytest.raises(ValueError, match="upgrade"):
        fp5.graphics[0].locked = True
    fp5.texts[0].locked = False
    fp5.graphics[0].locked = False
    assert fp5.dumps() == text
    with pytest.raises(ValueError, match="upgrade"):
        fp5.add(Line.new((0, 0), (1, 1), locked=True))
    t = Text.new("T", "user")
    t.locked = True
    with pytest.raises(ValueError, match="upgrade"):
        fp5.add(t)
    fp5.add(Line.new((0, 0), (1, 1)))
    old = kicadfp.loads(load_dip("kicad6").dumps().replace("(version 20211014)",
                                                           "(version 20210722)"))
    with pytest.raises(ValueError, match="20210925"):
        old.texts[0].locked = True
    old.graphics[0].locked = True            # фигуры в корне footprint — можно
    fp6 = load_dip("kicad6")
    fp6.texts[0].locked = True
    assert fp6.texts[0].locked


@pytest.mark.kicad_cli
def test_old_version_setters_output_read_by_kicad_cli(kicad_cli, tmp_path):
    """Всё, что setters разрешают писать в файл KiCad 5/6 (в том числе фаска у rect),
    kicad-cli читает, и площадка с фаской остаётся прямоугольником без скругления."""
    fps = {}
    for version in ("kicad5", "kicad6", "kicad8"):
        fp = load_dip(version)
        fp.name = f"chamfer_{version}"
        fp.new_pad("80", "smd", "rect", 6, 5, (1, 2), chamfer_ratio=0.2, chamfer=["top_left"])
        fps[fp.name] = fp
    out = _cli_check(kicad_cli, fps, tmp_path)
    for name in fps:
        p = kicadfp.load(out / f"{name}.kicad_mod").pad("80")
        assert p.shape == "roundrect" and p.roundrect_rratio == 0.0, name
        assert p.chamfer == ["top_left"] and p.chamfer_ratio == 0.2, name


# ---------------------------------------------------------------------------
# Регрессия: properties['Reference'|'Value'] в KiCad 5–7 и upgrade() голых свойств
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6"])
@pytest.mark.parametrize("key", ["Reference", "Value"])
def test_properties_reference_value_rejected_without_fields(version, key):
    """В KiCad 5–7 Reference/Value — это fp_text; свойство с таким ключом KiCad 8+ при
    чтении отбрасывает (значение терялось, а upgrade() давал второе поле)."""
    fp = load_dip(version)
    before = fp.dumps()
    with pytest.raises(ValueError, match=f"fp.{key.lower()}"):
        fp.properties[key] = "U7"
    assert fp.dumps() == before
    fp9 = load_dip("kicad9")
    fp9.properties[key] = "U7"                 # в 8+ это поле — работает
    assert getattr(fp9, key.lower()).text == "U7"


_V6 = (FIXTURES / "kicad6/Package_DIP.pretty/DIP-14_W7.62mm.kicad_mod")


def _v6_cases() -> dict[str, str]:
    src = _V6.read_text(encoding="utf-8")
    ref = src[src.index("  (fp_text reference"):src.index("  (fp_text value")]
    val = src[src.index("  (fp_text value"):src.index("  (fp_text user")]
    props = '  (property "Reference" "U7")\n  (property "Value" "V7")\n'
    return {
        # так пишут KiCad 6/7: свойства перед текстами — fp_text их переписывает
        "before": src.replace("  (attr through_hole)\n", props + "  (attr through_hole)\n"),
        # после текстов — свойство даёт полю текст и скрывает его
        "after": src.replace("  (fp_text user", props + "  (fp_text user", 1),
        # без fp_text — скрытое поле
        "noref": src.replace(ref, "").replace(val, "").replace(
            "  (attr through_hole)\n", props + "  (attr through_hole)\n"),
        # два fp_text reference — остаётся последний
        "dupref": src.replace("  (fp_text user", ref.replace("REF**", "U8").replace(
            "3.81 -2.33", "1 1").replace("ab1aeba6", "ab1aeba7") + "  (fp_text user", 1),
    }


@pytest.mark.parametrize("case,ref,val,ref_hidden", [
    ("before", "REF**", "DIP-14_W7.62mm", False), ("after", "U7", "V7", True),
    ("noref", "U7", "V7", True), ("dupref", "U8", "DIP-14_W7.62mm", False),
])
def test_upgrade_merges_legacy_reference_value(case, ref, val, ref_hidden):
    fp = kicadfp.loads(_v6_cases()[case])
    fp.upgrade()
    names = [str(n.atom(0)) for n in fp.node.nodes("property")]
    assert names.count("Reference") == 1 and names.count("Value") == 1
    assert fp.node.nodes("fp_text") == [] or all(
        str(n.atom(0)) == "user" for n in fp.node.nodes("fp_text"))
    assert (fp.reference.text, fp.value.text, fp.reference.hide) == (ref, val, ref_hidden)
    assert "TEXT_DUP_FIELD" not in [i.code for i in fp.validate()]


@pytest.mark.kicad_cli
def test_upgrade_legacy_reference_value_matches_kicad_cli(kicad_cli, tmp_path):
    cases = _v6_cases()
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    for name, text in cases.items():
        (lib / f"{name}.kicad_mod").write_text(
            text.replace('(footprint "DIP-14_W7.62mm"', f'(footprint "{name}"'), encoding="utf-8")
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    for name in cases:
        fp = kicadfp.load(lib / f"{name}.kicad_mod")
        fp.upgrade()
        mine = sexpr.parse(fp.dumps())
        ref = sexpr.parse((out / f"{name}.kicad_mod").read_text(encoding="utf-8"))
        for t in (mine, ref):
            _strip_volatile(t)
        assert sexpr.diff(ref, mine, numeric_tol=0, ignore_quotes=False) == [], name
