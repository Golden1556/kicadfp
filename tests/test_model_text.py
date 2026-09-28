"""Тесты :class:`kicadfp.model.Text` (``fp_text`` всех версий и поля ``property`` KiCad 8+)."""

from __future__ import annotations

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import profile_for
from kicadfp.geometry import BBox
from kicadfp.model import DEFAULT_TEXT_SIZE, Footprint, Text
from kicadfp.sexpr import Str, Sym
from tests.test_model_common import assert_one_token_changed, changed_lines, load_dip

P5 = profile_for(None, "module")
P6 = profile_for(20211014)
P8 = profile_for(20240108)
P9 = profile_for(20241229)


def _t(text: str, profile=P9) -> Text:
    return Text(sexpr.parse(text), profile)


def _c(view) -> str:
    return sexpr.to_compact(view.node)


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_read_reference_all_versions(version):
    ref = load_dip(version).reference
    assert ref.kind == "reference" and ref.text == "REF**"
    assert ref.name == (None if version in ("kicad5", "kicad6") else "Reference")
    assert ref.is_property == (version in ("kicad8", "kicad9"))
    assert (ref.x, ref.y, ref.angle, ref.position) == (3.81, -2.33, 0.0, (3.81, -2.33))
    assert (ref.layer, ref.hide, ref.visible, ref.unlocked, ref.knockout) == ("F.SilkS", False, True, None, False)
    assert (ref.font_size_x, ref.font_size_y, ref.font_size, ref.thickness) == (1.0, 1.0, (1.0, 1.0), 0.15)
    assert (ref.bold, ref.italic, ref.justify, ref.mirror, ref.locked) == (False, False, [], False, False)
    assert ref.face is None
    assert ref.uuid == {"kicad5": None, "kicad6": "ab1aeba6-0260-4b2b-a55c-e0a5f11f3d49",
                        "kicad8": "ab1aeba6-0260-4b2b-a55c-e0a5f11f3d49", "kicad9": None}[version]
    assert repr(ref).startswith("Text(")


def test_read_hidden_fields_kicad8():
    fp = load_dip("kicad8")
    ds = fp.properties.text("Datasheet")
    assert ds.kind == "user" and ds.name == "Datasheet" and ds.text == ""
    assert (ds.hide, ds.unlocked, ds.layer, ds.position, ds.angle) == (True, True, "F.Fab", (0, 0), 0.0)
    assert ds.font_size == (1.27, 1.27) and ds.thickness is None


def test_read_kicad5_user_text_and_kicad9_angle():
    user5 = load_dip("kicad5").texts[2]
    assert user5.kind == "user" and user5.text == "%R" and isinstance(user5.node.atom(1), Sym)
    user9 = load_dip("kicad9").texts[-1]
    assert user9.text == "${REFERENCE}" and user9.angle == 90.0 and user9.uuid is None


def test_read_flag_forms():
    t = _t('(fp_text user "hide" (at 1 2 90 unlocked) (layer "F.SilkS" knockout) hide '
           '(effects (font (size 1.5 1.2) (thickness 0.2) bold italic) (justify left mirror)))', P6)
    assert t.text == "hide"                           # текст «hide» — не флаг
    assert (t.hide, t.unlocked, t.knockout, t.bold, t.italic) == (True, True, True, True, True)
    assert (t.font_size_x, t.font_size_y) == (1.2, 1.5)  # (size ВЫСОТА ШИРИНА)
    assert t.justify == ["left", "mirror"] and t.mirror
    t8 = _t('(fp_text user "x" (at 0 0 0) (unlocked no) (layer "F.SilkS") '
            '(effects (font (size 1 1) (bold yes) (italic no)) hide))', P8)
    assert (t8.unlocked, t8.bold, t8.italic, t8.hide) == (False, True, False, True)
    locked6 = _t('(fp_text reference locked "REF**" (at 0 0) (layer "F.SilkS") (effects))', P6)
    assert locked6.locked and locked6.text == "REF**"
    nosize = _t('(fp_text user "x" (at 0 0) (layer "F.SilkS") (effects (font (thickness 0.1))))')
    assert nosize.font_size == (DEFAULT_TEXT_SIZE, DEFAULT_TEXT_SIZE) == (1.524, 1.524)


# ---------------------------------------------------------------------------
# Setters: ровно один токен, форма по версии
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
@pytest.mark.parametrize("attr,value", [
    ("text", "U1"), ("x", 1.5), ("y", -3.0), ("angle", 90.0), ("layer", "F.Fab"),
    ("hide", True), ("unlocked", True), ("knockout", True), ("font_size_x", 1.2),
    ("font_size_y", 0.8), ("thickness", 0.12), ("bold", True), ("italic", True),
    ("justify", ["left"]), ("mirror", True),
])
def test_text_setter_changes_one_token(version, attr, value):
    fp = load_dip(version)
    ref = fp.reference
    before = fp.node.copy()
    text_before = fp.dumps()
    if attr == "knockout" and version in ("kicad5", "kicad6"):
        # knockout появился в формате 20220308 (KiCad 7)
        with pytest.raises(ValueError, match="upgrade"):
            setattr(ref, attr, value)
        assert fp.dumps() == text_before
        return
    setattr(ref, attr, value)
    assert_one_token_changed(before, fp.node)
    assert getattr(ref, attr) == value
    if version in ("kicad8", "kicad9"):
        removed, added = changed_lines(text_before, fp.dumps())
        assert len(removed) <= 1 and len(added) == 1, (removed, added)
    again = kicadfp.loads(fp.dumps())
    assert getattr(again.reference, attr) == value


@pytest.mark.parametrize("version,hide,unlocked,bold", [
    ("kicad5", '(layer F.SilkS) hide(effects', "(at 3.81 -2.33 unlocked)", "(thickness 0.15) bold)"),
    ("kicad6", '(layer "F.SilkS") hide(effects', "(at 3.81 -2.33 unlocked)", "(thickness 0.15) bold)"),
    ("kicad8", '(layer "F.SilkS")(hide yes)(uuid', "(at 3.81 -2.33 0)(unlocked yes)(layer",
     "(thickness 0.15)(bold yes))"),
])
def test_flag_forms_by_version(version, hide, unlocked, bold):
    ref = load_dip(version).reference
    ref.hide = True
    ref.unlocked = True
    ref.bold = True
    c = _c(ref)
    assert hide in c and unlocked in c and bold in c, c
    ref.hide = False
    ref.unlocked = None
    ref.bold = False
    assert sexpr.equal(ref.node, load_dip(version).reference.node, ignore_quotes=False)


def test_angle_zero_rules():
    r6 = load_dip("kicad6").reference
    r6.angle = 90
    assert r6.node.find("at").atoms() == ["3.81", "-2.33", "90"]
    r6.angle = 0                                     # KiCad 6: нулевой угол не пишется
    assert r6.node.find("at").atoms() == ["3.81", "-2.33"]
    r8 = load_dip("kicad8").reference
    r8.angle = 0                                     # KiCad 8+: угол пишется всегда
    assert r8.node.find("at").atoms() == ["3.81", "-2.33", "0"]
    r6.unlocked = True
    r6.angle = 45                                    # угол — перед флагом unlocked
    assert r6.node.find("at").atoms() == ["3.81", "-2.33", "45", "unlocked"]


def test_locked_text_forms():
    r6 = load_dip("kicad6").reference
    r6.locked = True
    assert _c(r6).startswith('(fp_text reference locked "REF**"(at 3.81 -2.33)')
    assert r6.text == "REF**"
    r6.text = "U1"
    assert _c(r6).startswith('(fp_text reference locked "U1"')
    u8 = load_dip("kicad8").texts[-1]
    u8.locked = True
    assert _c(u8).startswith('(fp_text user "${REFERENCE}"(locked yes)(at 3.81 7.62 0)')


def test_text_quoting_by_version():
    r5 = load_dip("kicad5").reference
    r5.text = "U1"
    assert isinstance(r5.node.atom(1), Sym)
    r5.text = "two words"
    assert isinstance(r5.node.atom(1), Str)
    r5.text = ""
    assert isinstance(r5.node.atom(1), Str) and r5.text == ""
    r6 = load_dip("kicad6").reference
    r6.text = "U1"
    assert isinstance(r6.node.atom(1), Str)
    with pytest.raises(TypeError):
        r6.text = 5                                  # type: ignore[assignment]


def test_hide_inside_effects_is_changed_in_place():
    t = _t('(fp_text user "x" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)) hide))', P6)
    assert t.hide
    t.hide = False
    assert _c(t) == '(fp_text user "x"(at 0 0)(layer "F.SilkS")(effects(font(size 1 1))))'
    t.hide = True
    assert _c(t) == '(fp_text user "x"(at 0 0)(layer "F.SilkS") hide(effects(font(size 1 1))))'


def test_font_and_justify_setters():
    ref = load_dip("kicad8").reference
    ref.font_size = (1.2, 0.9)
    assert ref.node.find("effects").find("font").find("size").atoms() == ["0.9", "1.2"]
    ref.font_size = 1.1
    assert ref.font_size == (1.1, 1.1)
    ref.thickness = None
    assert ref.thickness is None
    ref.face = "KiCad Font"
    assert ref.node.find("effects").find("font").value("face") == "KiCad Font"
    ref.face = None
    ref.justify = "right top"
    assert ref.justify == ["right", "top"]
    ref.mirror = True
    assert ref.justify == ["right", "top", "mirror"]
    ref.justify = ["mirror", "left"]                # порядок KiCad
    assert ref.node.find("effects").find("justify").atoms() == ["left", "mirror"]
    with pytest.raises(ValueError):
        ref.justify = ["left", "right"]
    with pytest.raises(ValueError):
        ref.justify = ["center"]
    ref.justify = []
    assert ref.node.find("effects").find("justify") is None and not ref.mirror
    t = _t('(fp_text user "x" (at 0 0) (layer "F.SilkS"))')
    t.font_size_y = 2.0                              # нет effects — создаётся
    assert _c(t) == '(fp_text user "x"(at 0 0)(layer "F.SilkS")(effects(font(size 2 1.524))))'


def test_knockout_and_layer():
    ref = load_dip("kicad8").reference
    ref.knockout = True
    assert sexpr.to_compact(ref.node.find("layer")) == '(layer "F.SilkS" knockout)'
    ref.layer = "B.SilkS"                            # knockout сохраняется
    assert sexpr.to_compact(ref.node.find("layer")) == '(layer "B.SilkS" knockout)'
    ref.knockout = False
    assert sexpr.to_compact(ref.node.find("layer")) == '(layer "B.SilkS")'
    r5 = load_dip("kicad5").reference
    r5.layer = "B.SilkS"
    assert sexpr.to_compact(r5.node.find("layer")) == "(layer B.SilkS)"


def test_kind_and_name_setters():
    fp8 = load_dip("kicad8")
    ref = fp8.reference
    with pytest.raises(ValueError):
        ref.kind = "user"
    with pytest.raises(ValueError, match="Value"):
        ref.kind = "value"          # второе поле Value KiCad отбросил бы
    fp8.remove(fp8.value)
    ref.kind = "value"
    assert ref.name == "Value" and ref.kind == "value"
    ref.name = "MPN"
    assert ref.kind == "user"
    r6 = load_dip("kicad6").reference
    r6.kind = "user"
    assert r6.node.atom(0) == "user" and r6.text == "REF**"
    with pytest.raises(ValueError):
        r6.name = "X"
    with pytest.raises(ValueError):
        r6.kind = "label"


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------

def test_text_new_by_profile():
    r9 = Text.new("REF**", "reference", 0, -2, "F.SilkS", uuid="u")
    assert _c(r9) == ('(property "Reference" "REF**"(at 0 -2 0)(layer "F.SilkS")(uuid "u")'
                      '(effects(font(size 1 1)(thickness 0.15))))')
    u9 = Text.new("${REFERENCE}", "user", 0, 0, "F.Fab", uuid="u")
    assert _c(u9) == ('(fp_text user "${REFERENCE}"(at 0 0 0)(layer "F.Fab")(uuid "u")'
                      '(effects(font(size 1 1)(thickness 0.15))))')
    h9 = Text.new("x", name="MPN", layer="F.Fab", hide=True, size=(1.27, 1.27), thickness=None, uuid=False)
    assert _c(h9) == '(property "MPN" "x"(at 0 0 0)(layer "F.Fab")(hide yes)(effects(font(size 1.27 1.27))))'
    r6 = Text.new("REF**", "reference", 0, -2, profile=P6, uuid="u", angle=90, hide=True)
    assert _c(r6) == ('(fp_text reference "REF**"(at 0 -2 90)(layer "F.SilkS") hide'
                      '(effects(font(size 1 1)(thickness 0.15)))(tstamp u))')
    v5 = Text.new("DIP-8", "value", 0, 2, "F.Fab", profile=P5, justify=["left"])
    assert _c(v5) == ('(fp_text value DIP-8(at 0 2)(layer F.Fab)'
                      '(effects(font(size 1 1)(thickness 0.15))(justify left)))')
    wide = Text.new("W", size=(2.0, 1.0), uuid=False)
    assert wide.font_size == (2.0, 1.0)
    with pytest.raises(ValueError):
        Text.new("x", name="MPN", profile=P6)
    with pytest.raises(ValueError):
        Text.new("x", "label")


def test_text_move_rotate():
    t = Text.new("A", "user", 1, 0, uuid=False)
    t.move(1, 1)
    assert t.position == (2, 1)
    t.move(-1, -1)
    t.rotate(90)
    assert t.position == (0, -1) and t.angle == 90
    t.rotate(-180)
    assert t.position == (0, 1) and t.angle == 270          # нормализация [0, 360)
    t.rotate(90, (0, 1))
    assert t.position == (0, 1) and t.angle == 0
    assert t.node.find("at").atoms() == ["0", "1", "0"]


def test_text_bbox_in_footprint():
    fp = Footprint.new("X")
    for t in list(fp.texts):
        fp.remove(t)
    fp.new_text("AB", "user", 0, 0, "F.SilkS")
    assert fp.bbox() == BBox(0, 0, 0, 0)
    assert fp.bbox(include_texts=True) == BBox(-0.925, -0.575, 0.925, 0.575)
    t = fp.texts[0]
    t.justify = ["left"]
    assert fp.bbox(include_texts=True) == BBox(0, -0.575, 1.85, 0.575)
    t.hide = True
    assert fp.bbox(include_texts=True) == BBox(0, 0, 0, 0)


def test_effects_created_after_bare_hide_flag():
    t = _t('(fp_text user "x" (at 0 0) (layer "F.SilkS") hide (tstamp u))', P6)
    t.font_size = 1.0
    assert _c(t) == '(fp_text user "x"(at 0 0)(layer "F.SilkS") hide(effects(font(size 1 1)))(tstamp u))'
    t.bold = True
    assert _c(t).endswith("(effects(font(size 1 1) bold))(tstamp u))")
    t.bold = False
    t.italic = False                                   # нет — ничего не создаётся
    assert "italic" not in _c(t) and "bold" not in _c(t)


# ---------------------------------------------------------------------------
# Регрессии: «locked» в тексте KiCad 5, единственность полей Reference/Value
# ---------------------------------------------------------------------------

def _k5_text_atom(t: Text):
    return t.node.items[t._text_index()]


def test_k5_text_locked_is_quoted():
    """Регрессия: голый ``locked`` на месте текста fp_text парсер KiCad 6+ принимает за
    флаг блокировки («Unable to load library»)."""
    fp = Footprint.new("locked", version=None)
    assert '(fp_text value "locked"' in fp.dumps()
    assert isinstance(_k5_text_atom(fp.value), Str)
    fp.reference.text = "locked"
    assert isinstance(_k5_text_atom(fp.reference), Str) and fp.reference.text == "locked"
    t = fp.new_text("locked", x=1, y=1, layer="F.Fab")
    assert isinstance(_k5_text_atom(t), Str)
    # прочие строки KiCad 5 — по-прежнему без кавычек, если они не нужны
    fp.reference.text = "U1"
    assert isinstance(_k5_text_atom(fp.reference), Sym)
    fp.reference.text = "Locked"
    assert isinstance(_k5_text_atom(fp.reference), Sym)
    # имя корпуса и номер площадки KiCad читает и голыми — их не трогаем
    assert fp.dumps().startswith("(module locked ")


@pytest.mark.kicad_cli
def test_k5_text_locked_read_by_kicad_cli(kicad_cli, tmp_path):
    import subprocess
    fp = Footprint.new("locked", version=None)
    fp.reference.text = "locked"
    fp.new_text("locked", x=1, y=1, layer="F.Fab")
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    kicadfp.save(fp, lib / "locked.kicad_mod")
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "Unable" not in r.stderr, r.stderr
    k = kicadfp.load(out / "locked.kicad_mod")
    assert (k.reference.text, k.value.text) == ("locked", "locked")
    assert [t.text for t in k.texts if t.kind == "user" and t.name is None] == ["locked"]


@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_no_second_reference_or_value(version):
    """Регрессия: второй Reference/Value KiCad молча отбрасывает (берёт последний), а
    kicadfp показывал первый — теперь его создать нельзя."""
    fp = load_dip(version)
    before = sexpr.to_compact(fp.node)
    with pytest.raises(ValueError, match="Reference"):
        fp.new_text("U9", kind="reference", x=5, y=5)
    with pytest.raises(ValueError, match="Value"):
        fp.add(Text.new("V", "value", 0, 0, "F.Fab"))
    assert sexpr.to_compact(fp.node) == before
    user = next(t for t in fp.texts if t.kind == "user")
    with pytest.raises(ValueError, match="Value"):
        user.kind = "value"
    assert user.kind == "user"
    # после удаления — можно
    fp.remove(fp.reference)
    fp.new_text("U9", kind="reference", x=5, y=5)
    assert fp.reference.text == "U9"
    assert "TEXT_DUP_FIELD" not in [i.code for i in fp.validate()]


def test_field_name_setter_rejects_duplicate():
    fp = Footprint.new("X")        # KiCad 9: служебные поля Datasheet, Description
    ds = fp.properties.text("Datasheet")
    with pytest.raises(ValueError, match="Description"):
        ds.name = "Description"
    ds.name = "Datasheet"           # то же имя — не дубль
    ds.name = "MPN"
    assert "MPN" in fp.properties and "Datasheet" not in fp.properties
    with pytest.raises(ValueError, match="Description"):
        fp.add(Text.new("x", "user", 0, 0, "F.Fab", name="Description"))


@pytest.mark.parametrize("version", ["kicad6", "kicad9"])
def test_reference_getter_takes_last_like_kicad(version):
    """При дублях в файле (validate: TEXT_DUP_FIELD) getter показывает то поле, которое
    берёт KiCad, — последнее."""
    fp = load_dip(version)
    dup = fp.reference.node.copy()
    t = Text(dup, fp.profile)
    t.text = "U2"
    fp.node.items.append(dup)          # мимо add(): как в испорченном файле
    assert fp.reference.text == "U2"
    assert "TEXT_DUP_FIELD" in [i.code for i in fp.validate()]


@pytest.mark.kicad_cli
def test_reference_getter_matches_kicad_cli_on_duplicates(kicad_cli, tmp_path):
    import subprocess
    fp = load_dip("kicad9")
    dup = fp.reference.node.copy()
    Text(dup, fp.profile).text = "U2"
    fp.node.items.insert(fp.node.index(fp.value.node) + 1, dup)
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    kicadfp.save(fp, lib / "dup.kicad_mod")
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(lib), "-o", str(tmp_path / "o.pretty")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    k = kicadfp.load(tmp_path / "o.pretty" / "dup.kicad_mod")
    assert k.reference.text == fp.reference.text == "U2"
