"""Тесты kicadfp.validate: реестр правил, каждое правило на синтетических корпусах,
реальные библиотеки (kicad8 и все фикстуры — без ошибок), strict-сохранение."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import kicadfp
from kicadfp import load, loads, save
from kicadfp.io import ValidationError
from kicadfp.model import Footprint
from kicadfp.sexpr import Node, SexprSyntaxError, Str, Sym, parse
from tests.conftest import ALL_FILES, FIXTURES, fixture_files

# ``import kicadfp.validate as V`` дал бы функцию validate (атрибут пакета), а не модуль
V = sys.modules["kicadfp.validate"]

KICAD8_FILES = fixture_files("kicad8")


# ---------------------------------------------------------------------------
# вспомогательные
# ---------------------------------------------------------------------------

def base_fp(version: int | None = 20241229) -> Footprint:
    """Корректный корпус: Reference/Value, область размещения, без площадок."""
    fp = Footprint.new("TEST", version=version, attrs=["through_hole"] if version else ())
    fp.new_line((-2, -2), (2, -2), layer="F.CrtYd", width=0.05)
    return fp


def codes(fp: Footprint) -> list[str]:
    return [i.code for i in V.validate(fp)]


def issues_of(fp: Footprint, code: str) -> list[V.Issue]:
    return [i for i in V.validate(fp) if i.code == code]


def test_base_fp_is_clean():
    for ver in (20241229, 20240108, 20211014, None):
        assert V.validate(base_fp(ver)) == [], ver


def test_fp_without_pads_ok():
    assert not V.has_errors(V.validate(base_fp()))


# ---------------------------------------------------------------------------
# Issue, реестр, validate
# ---------------------------------------------------------------------------

def test_issue_basics():
    i = V.Issue("error", "X_CODE", "сообщение")
    assert str(i) == "ERROR X_CODE: сообщение"
    assert i.is_error and i.element is None and i.line == 0
    assert i.to_dict() == {"level": "error", "code": "X_CODE", "message": "сообщение", "line": 0}
    w = V.Issue("warning", "W", "м")
    assert not w.is_error
    with pytest.raises(ValueError):
        V.Issue("info", "X", "м")


def test_issue_element_line(dip14_v8):
    fp = load(dip14_v8)
    pad = fp.pads[0]
    i = V.Issue("warning", "X", "м", pad)
    assert i.node is pad.node and i.line == pad.node.line > 0


def test_has_errors():
    assert not V.has_errors([])
    assert not V.has_errors([V.Issue("warning", "A", "")])
    assert V.has_errors([V.Issue("warning", "A", ""), V.Issue("error", "B", "")])


def test_public_api():
    assert kicadfp.validate is V.validate
    assert kicadfp.Issue is V.Issue
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", size=1.3, drill=1.5)
    assert fp.validate() == V.validate(fp)
    assert fp.validate(strict=True) == V.validate(fp)      # strict не меняет список


def test_registry_contains_all_codes():
    got = {r.code: r.level for r in V.RULES}
    expected = {
        "PAD_DUP_NUMBER": "warning", "PAD_NO_LAYERS": "error", "PAD_THT_NO_DRILL": "error",
        "PAD_SMD_WITH_DRILL": "error", "PAD_DRILL_GT_SIZE": "error",
        "TEXT_MISSING_REFERENCE": "error", "TEXT_MISSING_VALUE": "error", "TEXT_DUP_FIELD": "error",
        "TEXT_REF_VALUE_LAYER": "warning", "TEXT_BAD_LAYER": "error",
        "GRAPHIC_BAD_LAYER": "error", "PAD_BAD_LAYER": "error", "ENUM_BAD_VALUE": "error",
        "SIZE_NOT_POSITIVE": "error", "COURTYARD_MISSING": "warning",
        "FOOTPRINT_BAD_LAYER": "error", "PAD_NPTH_NUMBER": "warning",
        "LAYER_RESCUE": "warning", "VERSION_TOO_NEW": "warning",
        "PAD_THT_NO_COPPER": "warning", "PAD_EMPTY_NUMBER": "warning",
    }
    assert got == expected
    for r in V.RULES:
        assert r.__doc__, r.__name__


def test_rule_decorator_registers_and_converts():
    n_before = len(V.RULES)
    try:
        @V.rule("TEST_CUSTOM", "warning")
        def my_rule(fp):
            """Тестовое правило."""
            yield "строка"
            yield ("пара", fp)
            yield V.Issue("error", "OVERRIDE", "готовое")

        assert len(V.RULES) == n_before + 1 and V.RULES[-1] is my_rule
        assert my_rule.code == "TEST_CUSTOM" and my_rule.level == "warning"
        fp = base_fp()
        out = [i for i in V.validate(fp) if i.code in ("TEST_CUSTOM", "OVERRIDE")]
        assert [(i.level, i.code, i.message) for i in out] == [
            ("warning", "TEST_CUSTOM", "строка"), ("warning", "TEST_CUSTOM", "пара"),
            ("error", "OVERRIDE", "готовое")]
        assert out[1].element is fp

        # повторная регистрация того же правила заменяет его, а не дублирует
        @V.rule("TEST_CUSTOM", "warning")
        def my_rule(fp):  # noqa: F811
            """Тестовое правило (замена)."""
            return None

        assert len(V.RULES) == n_before + 1
        assert [i for i in V.validate(fp) if i.code == "TEST_CUSTOM"] == []
    finally:
        V.RULES[:] = [r for r in V.RULES if r.code != "TEST_CUSTOM"]
    assert len(V.RULES) == n_before


def test_rule_bad_level():
    with pytest.raises(ValueError):
        V.rule("X", "fatal")
    with pytest.raises(ValueError):
        V.rule("", "error")


def test_rule_crash_is_isolated():
    n_before = len(V.RULES)
    try:
        @V.rule("TEST_CRASH", "warning")
        def crashing(fp):
            """Падает после первого замечания."""
            yield "до падения"
            raise ZeroDivisionError("деление на ноль")

        fp = base_fp()
        fp.new_pad("1", "thru_hole", "circle", size=1.3, drill=1.5)
        issues = V.validate(fp)
        cs = [i.code for i in issues]
        assert "TEST_CRASH" in cs                         # выданное до падения сохранено
        crash = [i for i in issues if i.code == "RULE_CRASH"]
        assert len(crash) == 1 and crash[0].level == "error"
        assert "TEST_CRASH" in crash[0].message and "ZeroDivisionError" in crash[0].message
        assert "PAD_DRILL_GT_SIZE" in cs                  # остальные правила выполнены
    finally:
        V.RULES[:] = [r for r in V.RULES if r.code != "TEST_CRASH"]
    assert len(V.RULES) == n_before


def test_crash_on_broken_node_does_not_stop_other_rules():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", size=1.3, drill=1.5)
    pad = fp.pads[0]

    class Boom:
        def __str__(self):
            raise RuntimeError("сломанный атом")

    fp.node.find("attr").items.append(Boom())  # type: ignore[union-attr]
    issues = V.validate(fp)
    assert any(i.code == "RULE_CRASH" and "ENUM_BAD_VALUE" in i.message for i in issues)
    assert any(i.code == "PAD_DRILL_GT_SIZE" and i.element == pad for i in issues)


def test_validate_rules_subset_and_types():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", size=1.3, drill=1.5)
    only = [r for r in V.RULES if r.code == "PAD_DUP_NUMBER"]
    assert V.validate(fp, rules=only) == []
    assert [i.code for i in V.validate(fp.node)] == codes(fp)   # голый узел оборачивается
    with pytest.raises(TypeError):
        V.validate("не корпус")  # type: ignore[arg-type]


def test_syntax_issue():
    with pytest.raises(SexprSyntaxError) as ei:
        parse("(footprint \"x\"")
    i = V.syntax_issue(ei.value, "a.kicad_mod")
    assert i.level == "error" and i.code == "SEXPR_SYNTAX"
    assert i.message.startswith("a.kicad_mod: ошибка разбора: строка 1")


# ---------------------------------------------------------------------------
# площадки
# ---------------------------------------------------------------------------

def test_scenario6_drill_greater_than_pad():
    """Сценарий 6 ТЗ: drill 1.5 при size 1.3 -> ошибка «отверстие больше площадки»."""
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", 1.27, -2.54, size=1.3, drill=1.5)
    iss = issues_of(fp, "PAD_DRILL_GT_SIZE")
    assert len(iss) == 1
    i = iss[0]
    assert i.level == "error" and i.element == fp.pads[0]
    assert "отверстие больше площадки" in i.message
    assert "«1»" in i.message and "(1.27; -2.54)" in i.message
    assert "1.5" in i.message and "1.3" in i.message
    assert V.has_errors(V.validate(fp))


def test_drill_equal_or_smaller_ok():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", size=1.6, drill=0.8)
    fp.new_pad("2", "thru_hole", "rect", 2.54, 0, size=1.6, drill=1.6)   # равенство — не ошибка
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") == []


@pytest.mark.parametrize("shape,size,drill,angle,axes", [
    ("oval", (1.6, 3.0), (1.0, 2.0), 0, None),              # овальное сверло влезает
    ("oval", (1.6, 3.0), (2.0, 1.0), 0, "X"),               # овал поперёк: по X больше
    ("oval", (1.6, 3.0), (1.0, 3.2), 0, "Y"),
    ("rect", (2.0, 1.0), 1.2, 0, "Y"),                      # круглое сверло шире узкой стороны
    ("rect", (2.0, 1.0), 1.2, 90, "Y"),                     # поворот одинаков для формы и сверла
    ("circle", (1.3, 5.0), 1.5, 0, "X и Y"),                # круг: size_y не учитывается
    ("roundrect", (2.0, 2.0), (2.1, 1.0), 0, "X"),
])
def test_drill_per_axis(shape, size, drill, angle, axes):
    fp = base_fp()
    fp.new_pad("1", "thru_hole", shape, size=size, drill=drill, angle=angle)
    iss = issues_of(fp, "PAD_DRILL_GT_SIZE")
    if axes is None:
        assert iss == []
    else:
        assert len(iss) == 1 and f"по оси {axes}:" in iss[0].message


def test_drill_offset_moves_shape_off_hole():
    fp = base_fp()
    p = fp.new_pad("1", "thru_hole", "rect", size=(3.0, 1.6), drill=1.0)
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") == []
    p.drill.offset_x = 0.8                     # край формы: -1.5+0.8 = -0.7 > -0.5 -> ок
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") == []
    p.drill.offset_x = 1.2                     # -1.5+1.2 = -0.3 > -0.5 -> отверстие торчит
    iss = issues_of(fp, "PAD_DRILL_GT_SIZE")
    assert len(iss) == 1 and "по оси X" in iss[0].message and "смещение формы" in iss[0].message


def test_drill_trapezoid_and_custom():
    fp = base_fp()
    # rect_delta (dx, dy): dy расширяет форму по X, dx — по Y (углы как PAD::BuildEffectiveShapes);
    # сравнивается наибольший размер трапеции по оси
    fp.new_pad("1", "thru_hole", "trapezoid", size=(1.0, 1.0), drill=1.2, rect_delta=(0, 0.6))
    iss = issues_of(fp, "PAD_DRILL_GT_SIZE")
    assert len(iss) == 1 and "по оси Y:" in iss[0].message    # по X 1.0 + 0.6 >= 1.2
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "trapezoid", size=(1.0, 1.0), drill=1.2, rect_delta=(0.6, 0.6))
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") == []
    # custom: якорь маленький, примитив покрывает отверстие
    fp = base_fp()
    p = fp.new_pad("1", "thru_hole", "custom", size=0.5, drill=1.0)
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") != []
    p.add_primitive(Node("gr_circle", [Node("center", [Sym("0"), Sym("0")]),
                                       Node("end", [Sym("0.8"), Sym("0")]),
                                       Node("width", [Sym("0")]), Node("fill", [Sym("yes")])]))
    assert issues_of(fp, "PAD_DRILL_GT_SIZE") == []


def test_drill_npth_greater():
    fp = base_fp()
    fp.new_pad("", "np_thru_hole", "circle", size=3.0, drill=3.2)
    assert [i.code for i in V.validate(fp) if i.level == "error"] == ["PAD_DRILL_GT_SIZE"]


def test_tht_without_drill():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", 1, 2, size=1.6)
    fp.new_pad("", "np_thru_hole", "circle", size=1.6)
    p3 = fp.new_pad("3", "thru_hole", "circle", size=1.6, drill=0.8)
    p3.drill.diameter = 0
    iss = issues_of(fp, "PAD_THT_NO_DRILL")
    assert [i.element for i in iss] == fp.pads
    assert all(i.level == "error" for i in iss)
    assert "«1» (1; 2)" in iss[0].message and "нет отверстия" in iss[0].message
    assert "площадка без номера" in iss[1].message
    assert "нулевое отверстие" in iss[2].message


def test_smd_with_drill():
    fp = base_fp()
    fp.new_pad("1", "smd", "rect", size=(1, 1.5), drill=0.3)
    fp.new_pad("2", "connect", "rect", 2, 0, size=(1, 1.5), drill=0.3)
    p3 = fp.new_pad("3", "smd", "rect", 4, 0, size=(1, 1.5))
    # (drill (offset …)) без размера — законное смещение формы SMD-площадки
    p3.node.append(Node("drill", [Node("offset", [Sym("0.2"), Sym("0")])]))
    assert p3.drill is not None and p3.drill.size == (0.0, 0.0)
    iss = issues_of(fp, "PAD_SMD_WITH_DRILL")
    assert [i.element.number for i in iss] == ["1", "2"]
    assert "smd" in iss[0].message and "connect" in iss[1].message


def test_pad_no_layers():
    fp = base_fp()
    p = fp.new_pad("1", "smd", "rect", size=1)
    p.node.remove("layers")
    iss = issues_of(fp, "PAD_NO_LAYERS")
    assert len(iss) == 1 and iss[0].level == "error" and "«1»" in iss[0].message


def test_pad_duplicates():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", 0, 0, size=1.6, drill=0.8)
    fp.new_pad("1", "thru_hole", "circle", 2.54, 0, size=1.6, drill=0.8)
    fp.new_pad("1", "thru_hole", "circle", 5.08, 0, size=1.6, drill=0.8)
    fp.new_pad("2", "thru_hole", "circle", 7.62, 0, size=1.6, drill=0.8)
    fp.new_pad("", "np_thru_hole", "circle", 10, 0, size=1, drill=1)
    fp.new_pad("", "np_thru_hole", "circle", 12, 0, size=1, drill=1)   # пустые не сравниваются
    iss = issues_of(fp, "PAD_DUP_NUMBER")
    assert len(iss) == 2 and all(i.level == "warning" for i in iss)
    assert [i.element for i in iss] == fp.pads[1:3]
    msg = iss[0].message
    assert "«1»" in msg and "(2.54; 0)" in msg and "(0; 0)" in msg
    assert "один вывод" in msg and "всего площадок с этим номером: 3" in msg
    assert not V.has_errors(V.validate(fp))


def test_pad_duplicates_jumpers_flag():
    fp = base_fp(20260206)
    fp.new_pad("1", "smd", "rect", size=1)
    fp.new_pad("1", "smd", "rect", 2, 0, size=1)
    assert issues_of(fp, "PAD_DUP_NUMBER") != []
    fp.node.find("duplicate_pad_numbers_are_jumpers").set_atom(0, Sym("yes"))
    assert issues_of(fp, "PAD_DUP_NUMBER") == []


def test_npth_number_and_empty_number():
    fp = base_fp()
    fp.new_pad("5", "np_thru_hole", "circle", size=1, drill=1)
    fp.new_pad("", "np_thru_hole", "circle", 3, 0, size=1, drill=1)
    fp.new_pad("", "thru_hole", "circle", 6, 0, size=1.6, drill=0.8)
    fp.new_pad("", "smd", "rect", 9, 0, size=1)
    fp.new_pad("", "smd", "rect", 12, 0, size=1, layers=["F.Paste"])   # апертура — без номера норма
    iss = issues_of(fp, "PAD_NPTH_NUMBER")
    assert len(iss) == 1 and iss[0].element == fp.pads[0] and "«5»" in iss[0].message
    iss = issues_of(fp, "PAD_EMPTY_NUMBER")
    assert [i.element for i in iss] == fp.pads[2:4]
    assert all(i.level == "warning" for i in iss)
    assert not V.has_errors(V.validate(fp))


def test_tht_no_outer_copper():
    fp = base_fp()
    fp.new_pad("1", "thru_hole", "circle", size=1.6, drill=0.8, layers=["F.Mask", "B.Mask"])
    fp.new_pad("2", "thru_hole", "circle", 3, 0, size=1.6, drill=0.8, layers=["In1.Cu", "F.Mask"])
    fp.new_pad("3", "thru_hole", "circle", 6, 0, size=1.6, drill=0.8, layers=["F&B.Cu"])
    fp.new_pad("4", "thru_hole", "circle", 9, 0, size=1.6, drill=0.8, layers=["B.Cu"])
    iss = issues_of(fp, "PAD_THT_NO_COPPER")
    assert [i.element.number for i in iss] == ["1", "2"]
    assert all(i.level == "warning" for i in iss)


def test_pad_bad_layer_and_wildcards_ok():
    fp = base_fp()
    p = fp.new_pad("1", "thru_hole", "circle", size=1.6, drill=0.8)
    fp.new_pad("2", "thru_hole", "circle", 3, 0, size=1.6, drill=0.8,
               layers=["*.Cu", "*.Mask", "*.Paste", "*.SilkS"])
    assert issues_of(fp, "PAD_BAD_LAYER") == []
    p.node.find("layers").items = [Str("*.Cu"), Str("R.Cu"), Str("In31.Cu")]
    iss = issues_of(fp, "PAD_BAD_LAYER")
    assert len(iss) == 1 and iss[0].level == "error"
    assert "R.Cu" in iss[0].message and "In31.Cu" in iss[0].message and "«1»" in iss[0].message


def test_pad_enum_values():
    fp = base_fp()
    p = fp.new_pad("7", "thru_hole", "circle", size=1.6, drill=0.8)
    p.node.items[1] = Sym("through")
    p.node.items[2] = Sym("hexagon")
    iss = issues_of(fp, "ENUM_BAD_VALUE")
    assert len(iss) == 2 and all(i.level == "error" and i.element == p for i in iss)
    assert "«through»" in iss[0].message and "«hexagon»" in iss[1].message
    assert "«7»" in iss[0].message


def test_pad_sizes():
    fp = base_fp()
    fp.new_pad("1", "smd", "rect", size=(0, 1))
    fp.new_pad("2", "smd", "rect", 2, 0, size=(1, -1))
    fp.new_pad("3", "thru_hole", "circle", 4, 0, size=(1.6, 0), drill=0.8)   # у круга size_y не важен
    p4 = fp.new_pad("4", "thru_hole", "circle", 6, 0, size=1.6, drill=0.8)
    p4.drill.diameter = -0.8
    fp.new_pad("5", "smd", "custom", 8, 0, size=0.01)
    iss = issues_of(fp, "SIZE_NOT_POSITIVE")
    assert [i.element.number for i in iss] == ["1", "2", "4"]
    assert "размер площадки" in iss[0].message and "отверстия" in iss[2].message


# ---------------------------------------------------------------------------
# тексты
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", [20241229, 20211014, None])
def test_missing_reference_value(version):
    fp = base_fp(version)
    fp.remove(fp.reference)
    iss = issues_of(fp, "TEXT_MISSING_REFERENCE")
    assert len(iss) == 1 and iss[0].level == "error" and "Reference" in iss[0].message
    assert issues_of(fp, "TEXT_MISSING_VALUE") == []
    fp.remove(fp.value)
    iss = issues_of(fp, "TEXT_MISSING_VALUE")
    assert len(iss) == 1 and iss[0].level == "error" and "Value" in iss[0].message
    assert "«TEST»" in iss[0].message


def test_reference_value_layer():
    fp = base_fp()
    fp.reference.layer = "B.SilkS"
    fp.value.layer = "B.Fab"
    assert issues_of(fp, "TEXT_REF_VALUE_LAYER") == []
    fp.reference.layer = "F.Cu"
    fp.value.layer = "Dwgs.User"
    iss = issues_of(fp, "TEXT_REF_VALUE_LAYER")
    assert len(iss) == 2 and all(i.level == "warning" for i in iss)
    assert "Reference" in iss[0].message and "F.Cu" in iss[0].message
    assert "Value" in iss[1].message and "Dwgs.User" in iss[1].message
    assert not V.has_errors(V.validate(fp))


def test_text_bad_layer():
    fp = base_fp()
    t = fp.new_text("${REFERENCE}", "user", 1, 2, "F.Fab")
    t.node.find("layer").set_atom(0, Str("F.Fabb"))
    fp.reference.node.find("layer").set_atom(0, Str("*.SilkS"))   # группа в (layer) недопустима
    iss = issues_of(fp, "TEXT_BAD_LAYER")
    assert len(iss) == 2 and all(i.level == "error" for i in iss)
    assert {i.element for i in iss} == {t, fp.reference}
    msg = next(i.message for i in iss if i.element == t)
    assert "F.Fabb" in msg and "(1; 2)" in msg and "${REFERENCE}" in msg
    # на несуществующем слое Reference не даёт ещё и предупреждение о слое
    assert issues_of(fp, "TEXT_REF_VALUE_LAYER") == []


def test_text_kind_enum_and_font_sizes():
    fp = base_fp(20211014)
    t = fp.new_text("x", "user", 0, 0, "F.SilkS")
    t.node.items[0] = Sym("title")
    iss = issues_of(fp, "ENUM_BAD_VALUE")
    assert len(iss) == 1 and "«title»" in iss[0].message
    fp = base_fp()
    t = fp.new_text("abc", "user", 0, 0, "F.SilkS", size=1.0)
    t.font_size_x = 0
    fp.value.thickness = -0.1
    iss = issues_of(fp, "SIZE_NOT_POSITIVE")
    assert [i.element for i in iss] == [fp.value, t] or [i.element for i in iss] == [t, fp.value]
    assert any("размер шрифта" in i.message and "«abc»" in i.message for i in iss)
    assert any("толщина шрифта" in i.message for i in iss)


# ---------------------------------------------------------------------------
# графика
# ---------------------------------------------------------------------------

def test_graphic_bad_layer():
    fp = base_fp()
    ln = fp.new_line((1, 2), (3, 4), "F.SilkS", 0.12)
    ln.node.find("layer").set_atom(0, Str("F.Silk"))
    c = fp.new_circle((0, 0), 1, "F.Fab")
    c.node.find("layer").set_atom(0, Str("*.Fab"))
    iss = issues_of(fp, "GRAPHIC_BAD_LAYER")
    assert [i.element for i in iss] == [ln, c]
    assert iss[0].level == "error"
    assert "линия fp_line" in iss[0].message and "F.Silk" in iss[0].message
    assert "(1; 2)" in iss[0].message
    assert "окружность fp_circle" in iss[1].message


def test_graphic_width_fill_stroke():
    fp = base_fp()
    ln = fp.new_line((0, 0), (1, 0), "F.SilkS", 0.12)
    ln.width = -0.1
    r = fp.new_rect((0, 0), (1, 1), "F.Fab", 0.1, fill=False)
    r.node.find("fill").set_atom(0, Sym("maybe"))
    ln.node.find("stroke").find("type").set_atom(0, Sym("wavy"))
    z = fp.new_poly([(0, 0), (1, 0), (1, 1)], "F.SilkS", 0, fill=True)
    assert issues_of(fp, "SIZE_NOT_POSITIVE")[0].element == ln
    assert "отрицательная ширина" in issues_of(fp, "SIZE_NOT_POSITIVE")[0].message
    iss = issues_of(fp, "ENUM_BAD_VALUE")
    assert {i.element for i in iss} == {ln, r}
    assert any("«maybe»" in i.message and "прямоугольник" in i.message for i in iss)
    assert any("«wavy»" in i.message for i in iss)
    assert z not in {i.element for i in V.validate(fp)}


@pytest.mark.parametrize("word", ["yes", "no", "solid", "none", "hatch", "cross_hatch"])
def test_fill_values_accepted(word):
    fp = base_fp()
    r = fp.new_rect((0, 0), (1, 1), "F.Fab", 0.1, fill=False)
    r.node.find("fill").set_atom(0, Sym(word))
    assert V.validate(fp) == []


def test_courtyard_missing():
    fp = Footprint.new("NOCRT", attrs=["smd"])
    iss = issues_of(fp, "COURTYARD_MISSING")
    assert len(iss) == 1 and iss[0].level == "warning" and "«NOCRT»" in iss[0].message
    fp.attrs.add("allow_missing_courtyard")
    assert issues_of(fp, "COURTYARD_MISSING") == []
    fp = Footprint.new("BCRT")
    fp.new_line((0, 0), (1, 0), "B.CrtYd", 0.05)
    assert issues_of(fp, "COURTYARD_MISSING") == []
    fp = Footprint.new("SILK")
    fp.new_line((0, 0), (1, 0), "F.SilkS", 0.12)
    fp.new_text("x", "user", 0, 0, "F.CrtYd")            # текст — не область размещения
    assert len(issues_of(fp, "COURTYARD_MISSING")) == 1


# ---------------------------------------------------------------------------
# корпус, слои, версия
# ---------------------------------------------------------------------------

def test_footprint_layer():
    fp = base_fp()
    fp.layer = "B.Cu"
    assert issues_of(fp, "FOOTPRINT_BAD_LAYER") == []
    fp.node.find("layer").set_atom(0, Str("F.SilkS"))
    iss = issues_of(fp, "FOOTPRINT_BAD_LAYER")
    assert len(iss) == 1 and iss[0].level == "error" and iss[0].element == fp
    assert "F.SilkS" in iss[0].message


def test_attr_enum():
    fp = base_fp()
    fp.node.find("attr").items.append(Sym("smt"))
    iss = issues_of(fp, "ENUM_BAD_VALUE")
    assert len(iss) == 1 and "«smt»" in iss[0].message and "attr" in iss[0].message


def test_rescue_layer():
    fp = base_fp()
    p = fp.new_pad("1", "connect", "circle", size=2, layers=["B.Mask"])
    p.node.find("layers").items.append(Str("Rescue"))
    g = fp.new_line((0, 0), (1, 1), "F.SilkS")
    g.node.find("layer").set_atom(0, Str("Rescue"))
    iss = issues_of(fp, "LAYER_RESCUE")
    assert [i.element for i in iss] == [p, g]
    assert all(i.level == "warning" for i in iss)
    assert not any(i.code in ("PAD_BAD_LAYER", "GRAPHIC_BAD_LAYER") for i in V.validate(fp))


def test_version_too_new():
    fp = base_fp(20260206)
    assert issues_of(fp, "VERSION_TOO_NEW") == []
    fp.node.find("version").set_atom(0, Sym("20270101"))
    iss = issues_of(fp, "VERSION_TOO_NEW")
    assert len(iss) == 1 and iss[0].level == "warning" and "20270101" in iss[0].message


# ---------------------------------------------------------------------------
# реальные библиотеки
# ---------------------------------------------------------------------------

def test_kicad8_fixtures_exist():
    assert len(KICAD8_FILES) > 100


@pytest.mark.parametrize("path", KICAD8_FILES,
                         ids=[str(p.relative_to(FIXTURES)) for p in KICAD8_FILES])
def test_kicad8_no_errors(path: Path):
    issues = V.validate(load(path))
    assert not V.has_errors(issues), [str(i) for i in issues if i.is_error]
    assert all(i.code != "RULE_CRASH" for i in issues)


def test_all_fixtures_no_errors():
    """Все фикстуры (KiCad 5–10) — без ошибок; единственное известное «настоящее»
    замечание — слой Rescue в библиотеке KiCad 9 (предупреждение)."""
    bad: list[str] = []
    for path in ALL_FILES:
        for i in V.validate(load(path)):
            if i.is_error:
                bad.append(f"{path}: {i}")
    assert bad == []


def test_dip14_warnings_only(dip14_v8, dip14_v6, dip14_v5):
    for p in (dip14_v8, dip14_v6, dip14_v5):
        assert V.validate(load(p)) == [], p


# ---------------------------------------------------------------------------
# strict-сохранение
# ---------------------------------------------------------------------------

def test_save_strict_raises(tmp_path, dip14_v8):
    fp = load(dip14_v8)
    fp.pad(1).size = 1.3
    fp.pad(1).drill = 1.5
    out = tmp_path / "bad.kicad_mod"
    with pytest.raises(ValidationError) as ei:
        save(fp, out, strict=True)
    assert not out.exists()
    errs = ei.value.errors
    assert [i.code for i in errs] == ["PAD_DRILL_GT_SIZE"]
    assert "отверстие больше площадки" in str(ei.value)
    save(fp, out)                                   # без strict — пишется
    assert out.exists()
    assert issues_of(loads(out.read_text()), "PAD_DRILL_GT_SIZE")


def test_save_strict_warnings_only_writes(tmp_path):
    fp = Footprint.new("W", attrs=["smd"])          # нет CrtYd — только предупреждение
    fp.new_pad("1", "smd", "rect", size=1)
    fp.new_pad("1", "smd", "rect", 2, 0, size=1)
    assert V.validate(fp) and not V.has_errors(V.validate(fp))
    out = tmp_path / "w.kicad_mod"
    save(fp, out, strict=True)
    assert out.exists()


def test_save_strict_ok(tmp_path, dip14_v8):
    out = tmp_path / "ok.kicad_mod"
    save(load(dip14_v8), out, strict=True)
    assert out.read_bytes() == dip14_v8.read_bytes()


# ---------------------------------------------------------------------------
# TEXT_DUP_FIELD
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", [None, 20211014, 20241229])
def test_text_dup_field(version):
    fp = base_fp(version)
    assert "TEXT_DUP_FIELD" not in codes(fp)
    fp.node.items.append(fp.reference.node.copy())     # мимо add(): как в испорченном файле
    got = issues_of(fp, "TEXT_DUP_FIELD")
    assert len(got) == 1 and got[0].level == "error" and "Reference" in got[0].message


def test_text_dup_field_named_property():
    fp = base_fp()
    fp.node.items.append(parse('(property "Datasheet" "x")'))
    got = issues_of(fp, "TEXT_DUP_FIELD")
    assert len(got) == 1 and "Datasheet" in got[0].message
