"""Общие помощники тестов модели и тесты базового класса ``View``, ``view_for``, профилей.

Помощники (``load_dip``, ``tree_changes``, ``changed_lines``) импортируются остальными
``tests/test_model_*.py`` и ``tests/test_io.py``.
"""

from __future__ import annotations

import difflib
import re
import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.format_rules import DEFAULT_VERSION, profile_for
from kicadfp.model import (
    Arc,
    Circle,
    Curve,
    Drill,
    Footprint,
    Line,
    Model,
    Pad,
    PointList,
    Poly,
    Rect,
    Text,
    View,
    view_for,
)
from kicadfp.sexpr import Node, Str, Sym
from tests.conftest import FIXTURES

VERSIONS = ("kicad5", "kicad6", "kicad8", "kicad9")
DIP14 = {v: FIXTURES / v / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod" for v in VERSIONS}


def load_dip(version: str) -> Footprint:
    """DIP-14_W7.62mm из фикстур версии ``version`` (kicad5/kicad6/kicad8/kicad9)."""
    return kicadfp.load(DIP14[version])


def _key(x: Node | Sym | Str) -> str:
    if isinstance(x, Node):
        return sexpr.to_compact(x)
    return ("S:" if isinstance(x, Str) else "Y:") + str(x)


def tree_changes(a: Node, b: Node, path: str = "") -> list[str]:
    """Минимальные различия деревьев: список изменённых элементов (``путь: старое -> новое``,
    ``путь: + вставка``, ``путь: - удаление``). Одноимённые узлы на одном месте сравниваются
    рекурсивно, поэтому изменение одного атома даёт одну запись, вставка узла — одну."""
    path = path or a.name
    out: list[str] = []
    same_shape = len(a.items) == len(b.items) and all(
        isinstance(x, Node) == isinstance(y, Node) and (not isinstance(x, Node) or x.name == y.name)
        for x, y in zip(a.items, b.items))
    if same_shape:
        # та же структура: атомы сравниваются по позициям, узлы — рекурсивно
        for x, y in zip(a.items, b.items):
            if isinstance(x, Node):
                out.extend(tree_changes(x, y, f"{path}/{x.name}"))  # type: ignore[arg-type]
            elif _key(x) != _key(y):
                out.append(f"{path}: {_key(x)} -> {_key(y)}")
        return out
    ka = [_key(x) for x in a.items]
    kb = [_key(x) for x in b.items]
    sm = difflib.SequenceMatcher(a=ka, b=kb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            for x, y in zip(a.items[i1:i2], b.items[j1:j2]):
                if isinstance(x, Node) and isinstance(y, Node) and x.name == y.name:
                    out.extend(tree_changes(x, y, f"{path}/{x.name}"))
                else:
                    out.append(f"{path}: {_key(x)} -> {_key(y)}")
            continue
        out.extend(f"{path}: - {_key(x)}" for x in a.items[i1:i2])
        out.extend(f"{path}: + {_key(y)}" for y in b.items[j1:j2])
    return out


def assert_one_token_changed(before: Node, after: Node) -> str:
    """Проверить, что изменился ровно один токен (атомы одного узла или один вставленный/
    удалённый узел), и вернуть описание изменения. Для замены значений дополнительно
    сверяется :func:`kicadfp.sexpr.diff`: те же атомы того же узла."""
    ch = tree_changes(before, after)
    paths = {c.split(":", 1)[0] for c in ch}
    assert ch and len(paths) == 1, ch
    if all("->" in c for c in ch):
        d = sexpr.diff(before, after)
        assert len(d) == len(ch), d
        assert {re.sub(r"\[\d+\]", "", x.split(":", 1)[0]) for x in d} == paths, (d, ch)
    else:
        assert len(ch) == 1, ch
    return ch[0]


def changed_nodes(a: Node, b: Node) -> set[str]:
    """Пути узлов, в которых есть изменения (без номера элемента)."""
    return {c.split(":", 1)[0] for c in tree_changes(a, b)}


def changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    """Строки текста, удалённые и добавленные между ``before`` и ``after``."""
    a, b = before.splitlines(), after.splitlines()
    removed: list[str] = []
    added: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            removed.extend(a[i1:i2])
            added.extend(b[j1:j2])
    return removed, added


# ---------------------------------------------------------------------------
# Тесты помощников (чтобы на них можно было полагаться)
# ---------------------------------------------------------------------------

def test_tree_changes_helper():
    a = sexpr.parse('(a (b 1 2) (c "x") (d))')
    b = sexpr.parse('(a (b 1 3) (c "x") (e 5) (d))')
    assert tree_changes(a, b) == ["a/b: Y:2 -> Y:3", "a: + (e 5)"]
    assert tree_changes(a, a.copy()) == []
    assert changed_lines("a\nb\nc\n", "a\nB\nc\n") == (["b"], ["B"])


# ---------------------------------------------------------------------------
# View, view_for, профили
# ---------------------------------------------------------------------------

def test_view_equality_and_hash_by_node_identity():
    fp = load_dip("kicad8")
    p1, p1b = fp.pads[0], fp.pad("1")
    assert p1 is not p1b
    assert p1 == p1b and hash(p1) == hash(p1b)
    assert p1 != fp.pads[1]
    assert len({p1, p1b, fp.pads[1]}) == 2
    # другой класс над тем же узлом — не равен
    assert Pad(p1.node) != Drill(p1.node)
    assert isinstance(p1, View)


def test_view_requires_node():
    with pytest.raises(TypeError):
        Pad("pad")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Footprint(Node("kicad_pcb"))


def test_view_copy_is_detached_deep_copy():
    fp = load_dip("kicad8")
    pad = fp.pad(1)
    cp = pad.copy()
    assert type(cp) is Pad and cp.node is not pad.node
    assert sexpr.equal(cp.node, pad.node)
    assert cp.parent is None and cp.profile == fp.profile
    cp.x = 5.0
    assert pad.x == 0.0 and cp.x == 5.0
    fcp = fp.copy()
    assert isinstance(fcp, Footprint) and fcp.node is not fp.node
    fcp.pad(1).x = 1.0
    assert fp.pad(1).x == 0.0


def test_view_for_maps_node_names():
    fp = load_dip("kicad8")
    assert isinstance(view_for(fp.node), Footprint)
    kinds = {n.name: type(view_for(n)) for n in fp.node.nodes()
             if n.name in ("pad", "fp_line", "fp_arc", "fp_text", "property", "model")}
    assert kinds == {"pad": Pad, "fp_line": Line, "fp_arc": Arc, "fp_text": Text, "property": Text,
                     "model": Model}
    mapping = {"fp_rect": Rect, "fp_circle": Circle, "fp_poly": Poly, "fp_curve": Curve,
               "gr_poly": Poly, "gr_line": Line, "gr_arc": Arc, "drill": Drill}
    for name, cls in mapping.items():
        assert type(view_for(Node(name))) is cls
    with pytest.raises(ValueError):
        view_for(Node("example_token"))


def test_views_follow_footprint_profile():
    fp = load_dip("kicad6")
    line = fp.graphics[0]
    assert line.profile.version == 20211014 and line.parent is fp
    fp.upgrade(DEFAULT_VERSION)           # профиль представлений — вслед за корпусом
    assert line.profile.version == DEFAULT_VERSION
    assert fp.profile.uuid_token == "uuid"
    # отдельно созданное представление — профиль KiCad 9 по умолчанию
    assert Line.new((0, 0), (1, 1)).profile == profile_for(DEFAULT_VERSION)
    assert Line.new((0, 0), (1, 1), profile=profile_for(20211014)).profile.version == 20211014


def test_module_profile_is_version_zero():
    fp = load_dip("kicad5")
    assert fp.version is None
    assert fp.profile.root == "module" and fp.profile.version == 0
    assert fp.profile.quoted_layers is False and fp.profile.arc_mid is False


def test_point_list_is_callable():
    line = Line.new((0, 0), (3, 4))
    assert isinstance(line.points, PointList)
    assert line.points == [(0.0, 0.0), (3.0, 4.0)]
    assert line.points() == line.points
