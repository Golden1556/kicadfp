"""Тесты :class:`kicadfp.model.Model` (3D-модели корпуса)."""

from __future__ import annotations

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import profile_for
from kicadfp.model import Footprint, Model
from kicadfp.sexpr import Str, Sym
from tests.test_model_common import assert_one_token_changed, changed_lines, load_dip

P5 = profile_for(None, "module")
P6 = profile_for(20211014)
P8 = profile_for(20240108)
INCH_F = 25.399999618530273     # 25.4f парсера KiCad


def _m(text: str, profile=P8) -> Model:
    return Model(sexpr.parse(text), profile)


def _c(view) -> str:
    return sexpr.to_compact(view.node)


@pytest.mark.parametrize("version,prefix,quoted", [
    ("kicad5", "${KICAD6_3DMODEL_DIR}", False), ("kicad6", "${KICAD6_3DMODEL_DIR}", True),
    ("kicad8", "${KICAD8_3DMODEL_DIR}", True), ("kicad9", "${KICAD9_3DMODEL_DIR}", True),
])
def test_read_dip14_model(version, prefix, quoted):
    (m,) = load_dip(version).models
    assert m.path == prefix + "/Package_DIP.3dshapes/DIP-14_W7.62mm.wrl"
    assert isinstance(m.node.atom(0), Str) == quoted
    assert (m.offset, m.scale, m.rotate) == ((0, 0, 0), (1, 1, 1), (0, 0, 0))
    assert m.hide is False and m.opacity is None
    assert m.uses_inch_offset == (version == "kicad5")
    assert repr(m).startswith("Model(")


def test_legacy_at_is_inches_times_float_25_4():
    m = _m("(model a.wrl (at (xyz 0.1 0 -0.05)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 90)))", P5)
    assert m.uses_inch_offset
    assert m.offset == (0.1 * INCH_F, 0.0, -0.05 * INCH_F)
    assert m.offset[0] == pytest.approx(2.54, abs=1e-6)
    assert m.rotate == (0, 0, 90)
    m.offset = (2.54, 0.0, m.offset[2])          # узел at сохраняется, значения — в дюймах
    at = m.node.find("at")
    assert at is not None and m.node.find("offset") is None
    assert at.find("xyz").atoms()[1:] == ["0", "-0.05"]      # неизменённые атомы не трогаются
    assert float(at.find("xyz").atoms()[0]) * INCH_F == pytest.approx(2.54, abs=1e-9)


def test_model_setters_one_token_kicad8():
    fp = load_dip("kicad8")
    m = fp.models[0]
    for attr, value in (("offset", (0, 0, 1.5)), ("scale", (2, 1, 1)), ("rotate", (0, 0, -90)),
                        ("hide", True), ("opacity", 0.5), ("path", "${KIPRJMOD}/x.step")):
        before = fp.node.copy()
        text_before = fp.dumps()
        setattr(m, attr, value)
        assert_one_token_changed(before, fp.node)
        assert getattr(m, attr) == value
        removed, added = changed_lines(text_before, fp.dumps())
        assert len(removed) <= 1 and len(added) == 1, (attr, removed, added)
    assert sexpr.to_compact(m.node.find("opacity")) == "(opacity 0.5000)"
    assert sexpr.to_compact(m.node.find("hide")) == "(hide yes)"
    assert m.node.find("offset").find("xyz").atoms() == ["0", "0", "1.5"]


@pytest.mark.parametrize("version,expected", [
    ("kicad6", '(model "${KICAD6_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-14_W7.62mm.wrl" hide(offset'),
    ("kicad8", '(model "${KICAD8_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-14_W7.62mm.wrl"(hide yes)(offset'),
])
def test_model_hide_forms(version, expected):
    m = load_dip(version).models[0]
    m.hide = True
    assert _c(m).startswith(expected) and m.hide
    m.hide = False
    assert "hide" not in _c(m)


def test_model_hide_opacity_rejected_by_old_versions():
    """Регрессия: hide (нет в KiCad 5.1) и opacity (20210824) не пишутся в файлы версий,
    которые их не знают (принцип 15 model.py)."""
    fp = load_dip("kicad5")
    m = fp.models[0]
    before = fp.dumps()
    with pytest.raises(ValueError, match="upgrade"):
        m.hide = True
    with pytest.raises(ValueError, match="upgrade"):
        m.opacity = 0.5
    m.hide = False                        # снятие флага и удаление токена разрешены
    m.opacity = None
    assert fp.dumps() == before
    fp6 = kicadfp.loads(before.replace("(module DIP-14_W7.62mm", "(footprint \"X\" (version 20210722)", 1))
    with pytest.raises(ValueError, match="20210824"):
        fp6.models[0].opacity = 0.3
    fp6.models[0].hide = True             # hide в корне footprint допустим
    assert fp6.models[0].hide
    fp9 = load_dip("kicad9")
    fp9.models[0].opacity = 0.3
    assert fp9.models[0].opacity == 0.3
    # Footprint.add отвергает модель с этими токенами для KiCad 5
    for attr, val in (("hide", True), ("opacity", 0.5)):
        mm = Model.new("a.wrl")
        setattr(mm, attr, val)
        with pytest.raises(ValueError, match="upgrade"):
            load_dip("kicad5").add(mm)


def test_model_opacity_and_validation():
    m = _m('(model "a.wrl" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')
    m.opacity = 0.25
    assert _c(m) == ('(model "a.wrl"(opacity 0.2500)(offset(xyz 0 0 0))(scale(xyz 1 1 1))'
                     '(rotate(xyz 0 0 0)))')
    assert m.opacity == 0.25
    m.opacity = None
    assert m.node.find("opacity") is None
    with pytest.raises(ValueError):
        m.opacity = 1.5
    with pytest.raises(TypeError):
        m.offset = (1, 2)                                  # type: ignore[assignment]
    with pytest.raises(ValueError):
        m.path = ""
    empty = _m('(model "b.wrl")')
    assert (empty.offset, empty.scale, empty.rotate) == ((0, 0, 0), (1, 1, 1), (0, 0, 0))
    empty.rotate = (0, 0, 45)                              # узел создаётся по таблице
    assert _c(empty) == '(model "b.wrl"(rotate(xyz 0 0 45)))'
    empty.offset = (1, 0, 0)
    assert _c(empty) == '(model "b.wrl"(offset(xyz 1 0 0))(rotate(xyz 0 0 45)))'


def test_model_new_by_profile():
    m9 = Model.new("${KICAD9_3DMODEL_DIR}/X.wrl", hide=True, opacity=0.8)
    assert _c(m9) == ('(model "${KICAD9_3DMODEL_DIR}/X.wrl"(hide yes)(opacity 0.8000)'
                      '(offset(xyz 0 0 0))(scale(xyz 1 1 1))(rotate(xyz 0 0 0)))')
    m6 = Model.new("a b.wrl", offset=(0.5, 0, 0.1), hide=True, profile=P6)
    assert _c(m6) == '(model "a b.wrl" hide(offset(xyz 0.5 0 0.1))(scale(xyz 1 1 1))(rotate(xyz 0 0 0)))'
    m5 = Model.new("x.wrl", rotate=(-90, 0, 0), profile=P5)
    assert _c(m5) == "(model x.wrl(offset(xyz 0 0 0))(scale(xyz 1 1 1))(rotate(xyz -90 0 0)))"
    assert isinstance(m5.node.atom(0), Sym)
    fp = Footprint.new("X")
    m = fp.new_model("${KICAD9_3DMODEL_DIR}/Y.wrl", scale=(1, 1, 2))
    assert fp.models == [m] and fp.node.nodes()[-1] is m.node and m.scale == (1, 1, 2)


def test_footprint_move_rotate_models():
    fp = load_dip("kicad8")
    m = fp.models[0]
    m.offset = (1, 1, 0)
    fp.move(2, 3)
    assert m.offset == (3, -2, 0)                 # ось Y модели направлена вверх
    fp.move(1, 1, models=False)
    assert m.offset == (3, -2, 0)
    fp2 = load_dip("kicad8")
    m2 = fp2.models[0]
    m2.offset = (1, 0, 0)
    fp2.rotate(90)
    assert m2.offset == pytest.approx((0, 1, 0), abs=1e-9) and m2.rotate == (0, 0, -90)
    fp2.rotate(90, models=False)
    assert m2.rotate == (0, 0, -90)
    fp2.rotate(-90)
    assert m2.rotate == (0, 0, 0) and m2.offset == pytest.approx((1, 0, 0), abs=1e-9)


def test_upgrade_converts_inch_offset_like_kicad():
    fp = kicadfp.loads("(module X (layer F.Cu) (tedit 0) (model x.wrl (at (xyz 0.16 0 -0.1)) "
                       "(scale (xyz 1 1 1)) (rotate (xyz 0 0 0))))")
    fp.upgrade()
    xyz = fp.models[0].node.find("offset").find("xyz")
    assert xyz.atoms() == ["4.063999939", "0", "-2.539999962"]     # как KiCad 9 (25.4f)
    assert fp.models[0].node.find("at") is None
    assert isinstance(fp.models[0].node.atom(0), Str)
