"""Регрессионные тесты совместимости модели с версиями формата KiCad (замечания ревью):

* флаги ``attr`` и прочие токены, которых нет в версии файла, не пишутся (``ValueError``);
* ``Footprint.add``/``Pad.add_primitive`` не делят узел между двумя деревьями;
* правило nullable (версии <= 20240201: ноль у зазоров/масок — «не задано»);
* скрытый пользовательский текст в формате KiCad 8+ — скрытое поле;
* присваивание неизменной точки старой дуге KiCad 5 не меняет узел.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import profile_for
from kicadfp.model import Arc, Footprint, Poly, Rect, Text
from tests.conftest import FIXTURES
from tests.test_model_common import DIP14, load_dip

K9_FILE = FIXTURES / "kicad9" / "Resistor_THT.pretty" / "R_Array_SIP9.kicad_mod"   # 20241229


def _k9() -> Footprint:
    fp = kicadfp.load(K9_FILE)
    assert fp.version == 20241229
    return fp


def _snapshot(fp: Footprint) -> str:
    return sexpr.to_compact(fp.node)


def _cli_upgrade(cli: str, fps: dict[str, Footprint], tmp_path: Path) -> Path:
    lib = tmp_path / "in.pretty"
    lib.mkdir(exist_ok=True)
    for name, fp in fps.items():
        kicadfp.save(fp, lib / f"{name}.kicad_mod")
    out = tmp_path / "out.pretty"
    r = subprocess.run([cli, "fp", "upgrade", str(lib), "-o", str(out), "--force"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "Unable" not in r.stderr and "rror" not in r.stderr, r.stderr
    return out


# ---------------------------------------------------------------------------
# attr: флаги по версии формата
# ---------------------------------------------------------------------------

def test_exclude_from_sim_rejected_in_kicad9_file():
    fp = _k9()
    before = _snapshot(fp)
    with pytest.raises(ValueError, match="exclude_from_sim.*20260828.*upgrade"):
        fp.attrs.add("exclude_from_sim")
    with pytest.raises(ValueError, match="exclude_from_sim"):
        fp.attrs = ["through_hole", "exclude_from_sim"]
    assert _snapshot(fp) == before
    with pytest.raises(ValueError, match="exclude_from_sim"):
        Footprint.new("X", attrs=["exclude_from_sim"])
    # KiCad 10 (20260828+) — можно
    fp10 = Footprint.new("X", version=20260901, attrs=["smd", "exclude_from_sim"])
    assert list(fp10.attrs) == ["smd", "exclude_from_sim"]


@pytest.mark.parametrize("flag,ok_version", [
    ("allow_missing_courtyard", 20221018), ("allow_soldermask_bridges", 20221018),
    ("dnp", 20240108), ("board_only", 20211014), ("exclude_from_bom", 20211014),
])
def test_attr_flags_by_version(flag, ok_version):
    fp6 = load_dip("kicad6")                                  # 20211014
    if ok_version > fp6.version:
        with pytest.raises(ValueError, match=f"attr {flag}"):
            fp6.attrs.add(flag)
        assert flag not in fp6.attrs
    else:
        fp6.attrs.add(flag)
        assert flag in fp6.attrs
    fp = Footprint.new("X", version=ok_version)
    fp.attrs.add(flag)
    assert flag in fp.attrs


def test_attr_flags_in_kicad5_module():
    fp5 = load_dip("kicad5")
    assert fp5.node.name == "module" and len(fp5.attrs) == 0
    # KiCad 5.1 знает только smd и virtual; сквозной монтаж — отсутствие attr
    with pytest.raises(ValueError, match="through_hole"):
        fp5.attrs.add("through_hole")
    with pytest.raises(ValueError, match="through_hole"):
        Footprint.new("X", version=None, attrs=["through_hole"])
    fp5.attrs.add("virtual")
    assert list(fp5.attrs) == ["virtual"]


def test_attrs_setter_keeps_existing_flag_of_newer_version():
    """Флаг, уже записанный в файле, повторное присваивание множества не отвергает."""
    fp = Footprint.new("X", version=20211014, attrs=["through_hole"])
    fp.node.find("attr").items.append(sexpr.Sym("dnp"))       # как в чужом файле
    fp.attrs = ["through_hole", "dnp"]
    assert set(fp.attrs) == {"through_hole", "dnp"}


# ---------------------------------------------------------------------------
# Прочие токены по версии формата
# ---------------------------------------------------------------------------

def test_newer_tokens_rejected_in_kicad6_file():
    fp = load_dip("kicad6")
    before = _snapshot(fp)
    cases = [
        (lambda: setattr(fp.value, "knockout", True), "knockout"),
        (lambda: setattr(fp.value, "face", "Arial"), "face"),
        (lambda: setattr(fp.pads[0], "thermal_bridge_angle", 45), "thermal_bridge_angle"),
        (lambda: setattr(fp, "private_layers", ["Eco1.User"]), "private_layers"),
        (lambda: setattr(fp, "net_tie_pad_groups", ["1, 2"]), "net_tie_pad_groups"),
        (lambda: fp.attrs.add("allow_missing_courtyard"), "allow_missing_courtyard"),
        (lambda: fp.attrs.add("dnp"), "dnp"),
        (lambda: fp.new_pad("99", thermal_bridge_angle=45), "thermal_bridge_angle"),
    ]
    for fn, what in cases:
        with pytest.raises(ValueError, match=what):
            fn()
    assert _snapshot(fp) == before
    # «выключение» и удаление допустимы и ничего не меняют
    fp.value.knockout = False
    fp.value.face = None
    fp.pads[0].thermal_bridge_angle = None
    fp.private_layers = []
    assert _snapshot(fp) == before
    # после upgrade() — можно
    fp.upgrade()
    fp.value.knockout = True
    fp.value.face = "Arial"
    fp.pads[0].thermal_bridge_angle = 45
    fp.private_layers = ["Eco1.User"]
    fp.attrs.add("dnp")
    assert fp.value.knockout and fp.value.face == "Arial" and "dnp" in fp.attrs


def test_kicad5_module_rect_and_fill():
    fp5 = load_dip("kicad5")
    before = _snapshot(fp5)
    with pytest.raises(ValueError, match="fp_rect"):
        fp5.new_rect((0, 0), (1, 1), "F.CrtYd", 0.05)
    with pytest.raises(ValueError, match="fill"):
        fp5.new_circle((0, 0), 1, fill=True)
    with pytest.raises(ValueError, match="remove_unused_layers"):
        fp5.pads[0].remove_unused_layers = True
    assert _snapshot(fp5) == before
    # умолчание парсера (fp_poly залит, окружность нет) — без токена fill
    poly = fp5.new_poly([(0, 0), (1, 0), (1, 1)], "F.SilkS", 0.12)
    circ = fp5.new_circle((0, 0), 1)
    assert poly.fill and poly.node.find("fill") is None
    assert not circ.fill and circ.node.find("fill") is None
    poly.fill = True                                         # уже так — без изменений
    assert poly.node.find("fill") is None
    with pytest.raises(ValueError, match="fill"):
        poly.fill = False
    with pytest.raises(ValueError, match="fill"):
        circ.fill = True
    assert "fill" not in kicadfp.dumps(fp5) and "fp_rect" not in kicadfp.dumps(fp5)


def test_add_view_with_unsupported_construct_is_rejected():
    fp6 = load_dip("kicad6")
    before = _snapshot(fp6)
    t = Text.new("x", "user", layer="F.SilkS")               # профиль KiCad 9
    t.knockout = True
    with pytest.raises(ValueError, match="knockout"):
        fp6.add(t)
    fp5 = load_dip("kicad5")
    with pytest.raises(ValueError, match="fp_rect"):
        fp5.add(Rect.new((0, 0), (1, 1)))
    with pytest.raises(ValueError, match="fill"):
        fp5.add(Poly.new([(0, 0), (1, 0), (1, 1)], fill=False))
    assert _snapshot(fp6) == before
    # совместимое — приводится к форме KiCad 5, fill по умолчанию парсера исчезает
    p = fp5.add(Poly.new([(0, 0), (1, 0), (1, 1)], fill=True))
    assert p.node.find("fill") is None and p.fill


@pytest.mark.kicad_cli
def test_version_limited_edits_are_readable_by_kicad_cli(kicad_cli, tmp_path):
    fp9 = _k9()
    for flag in ("board_only", "exclude_from_pos_files", "exclude_from_bom",
                 "allow_missing_courtyard", "dnp", "allow_soldermask_bridges"):
        fp9.attrs.add(flag)
    fp6 = load_dip("kicad6")
    fp6.attrs.add("board_only")
    fp6.new_poly([(0, 0), (1, 0), (1, 1)], "F.SilkS", 0.12)
    fp5 = load_dip("kicad5")
    fp5.attrs.add("smd")
    fp5.new_poly([(0, 0), (1, 0), (1, 1)], "F.SilkS", 0.12)
    out = _cli_upgrade(kicad_cli, {"a9": fp9, "a6": fp6, "a5": fp5}, tmp_path)
    assert "dnp" in kicadfp.load(out / "a9.kicad_mod").attrs


# ---------------------------------------------------------------------------
# add(): узел другого корпуса
# ---------------------------------------------------------------------------

def test_add_view_of_another_footprint_is_rejected():
    a = load_dip("kicad5")
    b = _k9()
    a_before, b_before = _snapshot(a), _snapshot(b)
    pad = a.pads[0]
    with pytest.raises(ValueError, match="другой корпус.*copy"):
        b.add(pad)
    assert _snapshot(a) == a_before and _snapshot(b) == b_before
    # копия — независимый узел, исходный корпус не меняется
    new = b.add(pad.copy())
    assert new.node is not pad.node and new.parent is b
    new.x = 99
    assert _snapshot(a) == a_before and pad.x == 0.0
    # после remove() элемент можно перенести
    a.remove(pad)
    b.add(pad)
    assert pad.parent is b and not any(n is pad.node for n in a.node.items)
    # тот же корпус — «уже входит»
    with pytest.raises(ValueError, match="уже входит"):
        b.add(b.pads[0])


def test_add_primitive_of_another_pad_is_rejected():
    fp = kicadfp.load(FIXTURES / "kicad9" / "Package_DFN_QFN.pretty"
                      / "QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm.kicad_mod")
    src, dst = fp.pad(1), fp.pad(2)
    (prim,) = src.primitive_views
    before = _snapshot(fp)
    with pytest.raises(ValueError, match="другую площадку"):
        dst.add_primitive(prim)
    with pytest.raises(ValueError, match="уже входит"):
        src.add_primitive(prim.node)
    assert _snapshot(fp) == before
    dst.add_primitive(prim.copy())
    assert len(dst.primitives) == len(src.primitives) == 1
    assert dst.primitives[0] is not src.primitives[0]


# ---------------------------------------------------------------------------
# nullable overrides: версии <= 20240201
# ---------------------------------------------------------------------------

_ZERO_TOKENS = ("(clearance 0)", "(solder_mask_margin 0)", "(solder_paste_margin 0)",
                "(solder_paste_margin_ratio 0)")


@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8"])
def test_zero_override_means_inherit_in_old_versions(version):
    fp = load_dip(version)
    pad = fp.pads[0]
    before = _snapshot(fp)
    for attr in ("clearance", "solder_mask_margin", "solder_paste_margin", "solder_paste_ratio"):
        setattr(pad, attr, 0)
        setattr(fp, attr, 0)
        assert getattr(pad, attr) is None and getattr(fp, attr) is None
    assert _snapshot(fp) == before                           # 0 — «не задано»: токенов нет
    pad.clearance = 0.1
    fp.solder_paste_ratio = -0.1
    assert pad.clearance == 0.1 and fp.solder_paste_ratio == -0.1
    pad.clearance = 0                                        # 0 удаляет токен
    fp.solder_paste_ratio = 0
    assert _snapshot(fp) == before


def test_zero_override_read_from_old_file_is_none_and_noop():
    text = DIP14["kicad8"].read_text(encoding="utf-8")            # 20240108
    text = text.replace("\t\t(drill 0.8)\n", "\t\t(drill 0.8)\n\t\t(solder_mask_margin 0)\n"
                        "\t\t(clearance 0.0)\n", 1)
    text = text.replace("\t(attr through_hole)\n",
                        "\t(solder_paste_ratio 0)\n\t(clearance 0)\n\t(attr through_hole)\n", 1)
    fp = kicadfp.loads(text)
    pad = fp.pads[0]
    assert (pad.solder_mask_margin, pad.clearance, fp.clearance, fp.solder_paste_ratio) == \
        (None, None, None, None)
    before = _snapshot(fp)
    for obj, attr in ((pad, "solder_mask_margin"), (pad, "clearance"), (fp, "clearance"),
                      (fp, "solder_paste_ratio")):
        setattr(obj, attr, getattr(obj, attr))                # x = x — без изменений
        setattr(obj, attr, 0)
    assert _snapshot(fp) == before
    assert kicadfp.dumps(fp) == text
    # upgrade(): нулевые токены из файла <= 20240201 исчезают (как у KiCad), не становятся 0
    fp.upgrade()
    dumped = kicadfp.dumps(fp)
    assert not any(t in dumped for t in _ZERO_TOKENS + ("(solder_paste_ratio 0)",))
    assert fp.clearance is None and fp.pads[0].clearance is None


def test_zero_override_is_explicit_in_kicad9():
    fp = _k9()
    pad = fp.pads[0]
    pad.clearance = 0
    pad.solder_mask_margin = 0
    fp.solder_paste_ratio = 0
    assert (pad.clearance, pad.solder_mask_margin, fp.solder_paste_ratio) == (0.0, 0.0, 0.0)
    dumped = kicadfp.dumps(fp)
    assert "(clearance 0)" in dumped and "(solder_paste_margin_ratio 0)" in dumped
    again = kicadfp.loads(dumped)
    again.upgrade()                                          # 20241229 -> 20241229: остаются
    assert again.pads[0].clearance == 0.0
    pad.clearance = None
    assert pad.clearance is None and pad.node.find("clearance") is None


@pytest.mark.kicad_cli
def test_nullable_semantics_match_kicad_cli(kicad_cli, tmp_path):
    old = kicadfp.loads(DIP14["kicad8"].read_text(encoding="utf-8").replace(
        "\t\t(drill 0.8)\n", "\t\t(drill 0.8)\n\t\t(clearance 0)\n", 1))
    new = _k9()
    new.pads[0].clearance = 0
    out = _cli_upgrade(kicad_cli, {"old": old, "new": new}, tmp_path)
    k_old = kicadfp.load(out / "old.kicad_mod")
    k_new = kicadfp.load(out / "new.kicad_mod")
    assert k_old.pads[0].clearance is None and old.pads[0].clearance is None
    assert k_new.pad(new.pads[0].number).clearance == 0.0 == new.pads[0].clearance
    old.upgrade()
    assert "(clearance" not in kicadfp.dumps(old)


# ---------------------------------------------------------------------------
# Скрытый пользовательский текст в формате KiCad 8+
# ---------------------------------------------------------------------------

def test_hidden_user_text_becomes_hidden_field_in_kicad9():
    fp = _k9()
    t = fp.new_text("hello world", "user", 1, 2, "F.Fab", hide=True)
    assert t.node.name == "property" and t.hide and t.kind == "user"
    assert t.name == "Field5" and t.text == "hello world" and t.parent is fp
    assert fp.properties["Field5"] == "hello world"
    t2 = fp.new_text("second", "user", hide=True)
    assert t2.name == "Field6"
    # поля идут подряд (за последним полем), fp_text после них
    names = [n.name for n in fp.node.nodes() if n.name in ("property", "fp_text")]
    assert names == sorted(names, key=lambda n: n != "property")
    # скрыть имеющийся fp_text user
    u = [x for x in fp.texts if x.node.name == "fp_text"][0]
    txt = u.text
    u.hide = True
    assert u.node.name == "property" and u.name == "Field7" and u.text == txt and u.hide
    assert "(hide yes)" in sexpr.to_compact(u.node)
    u.hide = False                                           # остаётся видимым полем
    assert u.node.name == "property" and not u.hide
    assert "(fp_text user" not in "".join(
        sexpr.to_compact(n) for n in fp.node.nodes("fp_text") if "(hide" in sexpr.to_compact(n))


def test_hidden_user_text_standalone_and_add():
    t = Text.new("n", "user", hide=True)                     # профиль KiCad 9
    assert t.node.name == "property" and t.name == "Field5"
    fp = _k9()
    fp.add(Text.new("a", "user", hide=True))
    fp.add(t)                                                # имя FieldN уточняется
    assert [x.name for x in fp.fields][-2:] == ["Field5", "Field6"]
    # fp_text user из KiCad 6 со скрытием -> поле при добавлении в корпус KiCad 9
    t6 = Text.new("old", "user", hide=True, profile=profile_for(20211014))
    assert t6.node.name == "fp_text"
    fp.add(t6)
    assert t6.node.name == "property" and t6.name == "Field7" and t6.hide


def test_hidden_user_text_kept_in_kicad6_and_converted_by_upgrade():
    fp = load_dip("kicad6")
    t = fp.new_text("note", "user", hide=True)
    assert t.node.name == "fp_text" and t.hide               # KiCad 6/7: так и пишется
    fp.upgrade()
    fields = {f.name: f for f in fp.fields}
    assert "Field5" in fields and fields["Field5"].text == "note" and fields["Field5"].hide
    assert not any(n.find("hide") is not None for n in fp.node.nodes("fp_text"))


@pytest.mark.kicad_cli
def test_hidden_user_text_survives_kicad_cli(kicad_cli, tmp_path):
    fps = {}
    for key, fp in (("k9", _k9()), ("k8", load_dip("kicad8")), ("new", Footprint.new("H"))):
        fp.new_text("note", "user", 1, 1, "F.Fab", hide=True)
        fp.new_text("${REFERENCE}", "user", 0, 0, "F.Fab", hide=True)
        fps[key] = fp
    k6 = load_dip("kicad6")
    k6.new_text("note", "user", 1, 1, "F.Fab", hide=True)
    k6.upgrade()
    fps["k6up"] = k6
    out = _cli_upgrade(kicad_cli, fps, tmp_path)
    for name in fps:
        res = kicadfp.load(out / f"{name}.kicad_mod")
        values = {t.text: t for t in res.texts}
        assert "note" in values and values["note"].hide, name


# ---------------------------------------------------------------------------
# Дуги KiCad 5: присваивание неизменной точки
# ---------------------------------------------------------------------------

def test_legacy_arc_noop_assignment_keeps_node():
    fp = kicadfp.loads("(module X (layer F.Cu) (fp_arc (start 1.27 0) (end 1.27 -2.48) "
                       "(angle 135) (layer F.Fab) (width 0.1)))")
    g = fp.graphics[0]
    before = _snapshot(fp)
    for _ in range(3):
        g.start = g.start
        g.mid = g.mid
        g.end = g.end
        g.set_points(g.start, g.mid, g.end)
    assert _snapshot(fp) == before
    assert "(angle 135)" in kicadfp.dumps(fp)


def test_legacy_arc_noop_on_all_kicad5_fixture_arcs():
    files = sorted((FIXTURES / "kicad5").rglob("*.kicad_mod")) + \
        sorted((FIXTURES / "special" / "kicad5").rglob("*.kicad_mod"))
    count = 0
    for path in files:
        fp = kicadfp.load(path)
        for g in fp.graphics:
            if not isinstance(g, Arc) or not g.is_legacy:
                continue
            count += 1
            before = sexpr.to_compact(g.node)
            g.start = g.start
            g.mid = g.mid
            g.end = g.end
            assert sexpr.to_compact(g.node) == before, path
    assert count > 20


def test_legacy_arc_change_keeps_unmoved_center_and_exact_angle():
    """Перенос точки на нанометр ничего не меняет; перенос конца по той же окружности
    меняет только угол — ровно (без дрейфа из-за округлённой середины)."""
    fp = kicadfp.loads("(module X (layer F.Cu) (fp_arc (start 0 0) (end 1 0) (angle 90) "
                       "(layer F.Fab) (width 0.1)))")
    g = fp.graphics[0]
    s, m, e = g.start, g.mid, g.end
    assert (s, e) == ((1.0, 0.0), (0.0, 1.0))
    g.start = (s[0] + 1e-7, s[1])
    assert "(fp_arc(start 0 0)(end 1 0)(angle 90)" in _snapshot(fp)
    g.end = (-1.0, 0.0)
    assert "(fp_arc(start 0 0)(end 1 0)(angle 180)" in _snapshot(fp)
    g.set_points(g.start, g.mid, (0.0, -1.0))
    assert "(fp_arc(start 0 0)(end 1 0)(angle 270)" in _snapshot(fp)
    assert g.is_legacy and g.center == (0.0, 0.0) and g.radius == 1.0 and g.end == (0.0, -1.0)
