"""Типизированные представления (views) над деревом S-выражений посадочного места KiCad.

Модуль реализует контракт ``docs/dev/architecture.md`` §6: :class:`Footprint`, :class:`Pad`,
:class:`Drill`, графика (:class:`Line`, :class:`Rect`, :class:`Circle`, :class:`Arc`,
:class:`Poly`, :class:`Curve` с общим базовым :class:`Graphic`), :class:`Text`,
:class:`Model` и базовый класс :class:`View`.

Принципы
--------

* Представление не хранит копий данных: каждый getter читает узел, каждый setter меняет
  **только свой токен** (атом или дочерний узел) и не пересоздаёт узел целиком. Неизвестные
  узлы и атрибуты, порядок токенов и исходный текст чисел остальных токенов сохраняются.
* Отсутствующий токен создаётся в той форме, которую пишет KiCad версии файла (профиль
  :class:`~kicadfp.format_rules.FormatProfile`), и вставляется по таблице порядка
  (``format_rules.*_ORDER``); присваивание ``None`` удаляет необязательный токен.
* Профиль корпуса вычисляется по корню (токен ``version`` и имя корня ``footprint``/``module``);
  представления, полученные из корпуса, пользуются его профилем. Отдельно созданные
  представления (``Pad.new`` и т.п.) имеют собственный профиль (по умолчанию — KiCad 9,
  ``DEFAULT_VERSION``); :meth:`Footprint.add` приводит их узел к профилю корпуса.
* Числа записываются как в KiCad: координаты и длины — :func:`~kicadfp.sexpr.format_number`
  (нанометры), углы — :func:`~kicadfp.sexpr.format_angle`, коэффициенты и 3D-параметры —
  :func:`~kicadfp.sexpr.format_double`.

Отклонения от буквы контракта (решения по фактам формата KiCad; подробности — в docstring
соответствующих членов):

1. ``Text.font_size_x``/``font_size_y`` без токена ``(size …)`` возвращают 1.524 мм — умолчание
   парсера KiCad (``parseEDA_TEXT``), а не 1.0; новые тексты создаются размером 1.0 × 1.0.
2. ``Graphic.fill`` при отсутствии токена ``(fill …)`` следует правилам парсера KiCad:
   многоугольник не на ``Edge.Cuts`` и прямоугольник/окружность с нулевой шириной линии —
   залиты (так читаются файлы KiCad 5), остальное — нет.
3. Дуги: форму (``start/mid/end`` или старую ``center/end/angle``) KiCad выбирает **по версии
   файла** (``<= 20210925`` — старая), поэтому setters :class:`Arc` в файле старой версии
   оставляют узел в старой форме, а в файле новой версии перестраивают старый узел в
   ``start/mid/end`` (единственный случай перестройки узла при присваивании).
4. ``Graphic.width``/``Graphic.layer`` возвращают ``None``, если токена нет (примитивы площадок
   без слоя, фигуры без ширины).
5. ``Rect.rotate`` на угол, не кратный 90°, превращает ``fp_rect`` в ``fp_poly`` (как KiCad,
   ``EDA_SHAPE::rotate``); представление при этом становится :class:`Poly`.
6. ``points`` — свойство, возвращающее список, который можно и вызвать: ``g.points`` и
   ``g.points()`` равнозначны (контракт описывает и метод ``Graphic.points()``, и свойство
   ``Poly.points`` с setter).
7. :meth:`Footprint.move`/:meth:`Footprint.rotate` сдвигают/поворачивают и смещение 3D-моделей
   (как ``FOOTPRINT::MoveAnchorPosition`` KiCad), отключается ``models=False``.
8. :meth:`Footprint.flip` выражает результат KiCad (``FOOTPRINT::Flip`` LEFT_RIGHT даёт
   ориентацию 180° и зеркало TOP_BOTTOM) при нулевой ориентации корпуса: ``x -> -x``, угол
   ``a -> -a`` (нормализуется в [0, 360)), несимметричные детали площадок (``rect_delta``,
   смещение отверстия, срезанные углы, примитивы) отражаются по X.
"""

from __future__ import annotations

import builtins
import functools
import importlib
import math
import sys
import time
import uuid as _uuidlib
from collections.abc import Iterable, Iterator, MutableMapping, MutableSet, Sequence
from numbers import Real
from typing import Any, Callable, Union

from . import geometry as _geo
from . import layers as _L
from . import sexpr as _sexpr
from ._version import __version__
from .format_rules import (
    ATTR_ORDER,
    DEFAULT_GENERATOR,
    DEFAULT_VERSION,
    DRILL_ORDER,
    EFFECTS_ORDER,
    FONT_ORDER,
    FOOTPRINT_ORDER,
    GRAPHIC_ORDER,
    KNOWN_FOOTPRINT_CHILDREN,
    MODEL_ORDER,
    PAD_ORDER,
    STROKE_ORDER,
    TEXT_ORDER,
    TEXT_ORDER_V6,
    V_FIELDS,
    V_FILL_YESNO,
    V_LEGACY_ARC,
    V_NORMALIZED,
    V_PASTE_RATIO,
    FormatProfile,
    insert_in_group,
    positional_atoms,
    profile_for,
)
from .geometry import BBox
from .sexpr import Node, Str, Sym, format_angle, format_double, format_number, is_number

__all__ = [
    "View", "Footprint", "Pad", "Drill", "Graphic", "Line", "Rect", "Circle", "Arc", "Poly",
    "Curve", "Text", "Model", "AttrSet", "PropertyMap", "PointList", "BBox", "view_for",
    "PAD_TYPES", "PAD_SHAPES", "TEXT_KINDS", "STROKE_TYPES", "JUSTIFY_VALUES",
    "CHAMFER_CORNERS", "DEFAULT_TEXT_SIZE",
]

Point = tuple[float, float]
Atom = Union[Sym, Str]

#: Типы площадок (``(pad N ТИП …)``).
PAD_TYPES: tuple[str, ...] = ("thru_hole", "smd", "connect", "np_thru_hole")
#: Формы площадок (``(pad N тип ФОРМА …)``).
PAD_SHAPES: tuple[str, ...] = ("circle", "rect", "oval", "trapezoid", "roundrect", "custom")
#: Виды текстов (:attr:`Text.kind`).
TEXT_KINDS: tuple[str, ...] = ("reference", "value", "user")
#: Типы линий ``(stroke (type …))``.
STROKE_TYPES: tuple[str, ...] = ("solid", "dash", "dot", "dash_dot", "dash_dot_dot", "default")
#: Значения ``(justify …)`` в порядке записи KiCad (``EDA_TEXT::Format``).
JUSTIFY_VALUES: tuple[str, ...] = ("left", "right", "top", "bottom", "mirror")
#: Углы ``(chamfer …)`` в порядке записи KiCad.
CHAMFER_CORNERS: tuple[str, ...] = ("top_left", "top_right", "bottom_left", "bottom_right")
#: Размер шрифта, который KiCad подставляет при отсутствии ``(size …)`` (60 mil).
DEFAULT_TEXT_SIZE = 1.524

_INCH = 25.4                 # мм в дюйме: старая форма (model (at (xyz …))) — дюймы
_V_ATTR_FLAGS = 20200826     # до этой версии корпус без флагов attr считается through_hole
_V_THERMAL_BRIDGE = 20211014  # по эту версию (KiCad 6) ширина спицы — thermal_width
_V_KNOCKOUT = 20220308       # knockout у текстов
_V_EMBEDDED = 20240706       # embedded_fonts / embedded_files
_V_NULLABLE = 20240201       # до этой версии включительно 0 у зазоров/масок = «наследовать»
_V_GROUP_UUID = 20231231     # (uuid …) вместо (id …) у групп
_V_JUMPERS = 20250324        # duplicate_pad_numbers_are_jumpers (KiCad 10)

# Порядок дочерних токенов примитивов площадки (gr_* внутри primitives): writer KiCad
# пишет координаты, (width), (fill); прочее — на случай нестандартных файлов.
_PRIMITIVE_ORDER: tuple[str, ...] = (
    "locked", "start", "center", "mid", "end", "pts", "angle", "width", "stroke", "fill",
    "layer", "layers", "net", "uuid", "tstamp",
)
# Порядок токенов зоны (только для вставки новых токенов, зоны не переупорядочиваются).
_ZONE_ORDER: tuple[str, ...] = (
    "net", "net_name", "locked", "layer", "layers", "uuid", "tstamp", "name", "hatch",
)

_FP_GRAPHIC_KIND: dict[str, str] = {
    "fp_line": "line", "fp_rect": "rect", "fp_circle": "circle", "fp_arc": "arc",
    "fp_poly": "poly", "fp_curve": "curve",
}
_PRIM_GRAPHIC_KIND: dict[str, str] = {
    "gr_line": "line", "gr_rect": "rect", "gr_circle": "circle", "gr_arc": "arc",
    "gr_poly": "poly", "gr_curve": "curve", "gr_bbox": "rect", "gr_vector": "line",
}
_GRAPHIC_KIND: dict[str, str] = {**_FP_GRAPHIC_KIND, **_PRIM_GRAPHIC_KIND}
_FILL_KINDS = frozenset(("rect", "circle", "poly"))
_TEXT_ATTRS = ("at", "layer", "effects")
_FIELD_NAMES = {"reference": "Reference", "value": "Value"}
# прочие элементы секции рисования с координатами: переносятся/поворачиваются/отражаются
# обобщённо (все узлы at/start/end/center/mid/xy на любой глубине)
_GENERIC_GEOMETRY = frozenset((
    "fp_text_box", "image", "dimension", "point", "table", "barcode", "fp_ellipse",
    "fp_ellipse_arc",
))
_COORD_NODES = frozenset(("at", "start", "end", "center", "mid", "xy"))


# ---------------------------------------------------------------------------
# Вспомогательные функции: профили, числа, атомы
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _profile(version: int | None, root: str) -> FormatProfile:
    """Кэшированный :func:`~kicadfp.format_rules.profile_for` (профили неизменяемы)."""
    return profile_for(version, root)


def _default_profile() -> FormatProfile:
    """Профиль новых элементов по умолчанию — KiCad 9 (``DEFAULT_VERSION``)."""
    return _profile(DEFAULT_VERSION, "footprint")


def _num(atom: Any) -> float | None:
    """Числовое значение атома или ``None`` (не число по правилам лексера KiCad)."""
    if atom is None or isinstance(atom, Node) or not is_number(atom):
        return None
    return float(atom)


def _check_real(value: Any, what: str) -> float:
    """Проверить, что ``value`` — конечное число (не bool), и вернуть ``float``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{what}: ожидается число, получено {type(value).__name__}")
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{what}: число должно быть конечным")
    return v


def _check_int(value: Any, what: str) -> int:
    """Проверить, что ``value`` — целое число (не bool)."""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise TypeError(f"{what}: ожидается целое число, получено {type(value).__name__}")
    return int(value)


def _check_str(value: Any, what: str, *, allow_empty: bool = True) -> str:
    """Проверить, что ``value`` — строка."""
    if not isinstance(value, str):
        raise TypeError(f"{what}: ожидается строка, получено {type(value).__name__}")
    if not allow_empty and not value:
        raise ValueError(f"{what}: строка не может быть пустой")
    return value


def _as_point(value: Any, what: str) -> Point:
    """Точка ``(x, y)`` из последовательности двух чисел."""
    try:
        x, y = value
    except (TypeError, ValueError):
        raise TypeError(f"{what}: ожидается точка (x, y)") from None
    return (_check_real(x, what), _check_real(y, what))


def _as_pair(value: Any, what: str) -> tuple[float, float]:
    """Пара чисел: одно число ``v`` -> ``(v, v)``, последовательность -> ``(a, b)``."""
    if isinstance(value, Real) and not isinstance(value, bool):
        v = _check_real(value, what)
        return (v, v)
    return _as_point(value, what)


def _as_xyz(value: Any, what: str) -> tuple[float, float, float]:
    """Тройка чисел ``(x, y, z)``."""
    try:
        x, y, z = value
    except (TypeError, ValueError):
        raise TypeError(f"{what}: ожидается тройка чисел (x, y, z)") from None
    return (_check_real(x, what), _check_real(y, what), _check_real(z, what))


def _len(v: float) -> Sym:
    """Длина/координата как атом (``FormatInternalUnits``)."""
    return Sym(format_number(v))


def _ang(v: float) -> Sym:
    """Угол как атом (``FormatAngle``)."""
    return Sym(format_angle(v))


def _dbl(v: float) -> Sym:
    """Безразмерное число как атом (``FormatDouble2Str``)."""
    return Sym(format_double(v))


def _norm360(a: float) -> float:
    """Угол в диапазоне [0, 360) (``EDA_ANGLE::Normalize``); почти 360 -> 0."""
    a = math.fmod(float(a), 360.0)
    if a < 0:
        a += 360.0
    if a >= 360.0 - 1e-9 or abs(a) < 1e-9:
        return 0.0
    return a


def _is_cardinal(angle: float) -> bool:
    """Кратен ли угол 90° (``EDA_ANGLE::IsCardinal``)."""
    r = math.fmod(abs(float(angle)), 90.0)
    return r < 1e-9 or 90.0 - r < 1e-9


_K5_SPECIAL = frozenset(" \t()\n\r")


def _k5_atom(s: str) -> Atom:
    """Строка в форме KiCad 5.1 (``OUTPUTFORMATTER::Quotew`` 5.1): кавычки, только если строка
    пустая, начинается с ``#`` или ``"`` либо содержит пробел, табуляцию, скобку или перевод
    строки."""
    if not s or s[0] in '#"' or any(c in _K5_SPECIAL for c in s):
        return Str(s)
    return Sym(s)


def _str_atom(s: str, profile: FormatProfile) -> Atom:
    """Строковое значение по профилю: в корне ``module`` (KiCad 5) — кавычки по необходимости,
    иначе — всегда в кавычках."""
    return _k5_atom(s) if profile.root == "module" else Str(s)


def _bare_symbol_ok(s: str) -> bool:
    """Можно ли записать строку голым символом (не число, без разделителей и кавычек)."""
    return bool(s) and not is_number(s) and not any(c in s for c in ' \t\r\n()"\\#')


def _layer_atom(name: str, profile: FormatProfile, *, in_list: bool = False) -> Atom:
    """Имя слоя в форме профиля: KiCad 5 — голое; KiCad 6 — в кавычках, но групповые
    обозначения (``*.Cu``) в ``(layers …)`` голые; KiCad 7+ — всё в кавычках."""
    if not profile.quoted_layers:
        return _k5_atom(name)
    if in_list and _L.is_wildcard(name) and not profile.quoted_wildcards:
        return Sym(name)
    return Str(name)


def _check_layer(name: Any, what: str = "layer") -> str:
    """Проверить имя слоя (непустая строка; существование слоя не проверяется)."""
    return _check_str(name, what, allow_empty=False)


def _layer_list(names: Any, what: str = "layers") -> list[str]:
    """Список имён слоёв: итерируемое строк или строка через запятую (``"F.Cu,F.Mask"``)."""
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    out = []
    for n in names:
        out.append(_check_layer(n, what))
    return out


def _is_side_specific(layer: str | None) -> bool:
    """Слой «одной стороны» (``BOARD_ITEM::IsSideSpecific``): медь, F./B. технологические,
    CrtYd, Fab."""
    if not layer:
        return False
    return layer in _L.FRONT_LAYERS or layer in _L.BACK_LAYERS or _L.is_copper(layer)


# --- булевы токены --------------------------------------------------------------

_TRUE_WORDS = frozenset(("yes", "true"))


def _bool_token(node: Node | None, name: str) -> bool | None:
    """Булев токен в любой форме (``parseMaybeAbsentBool``): голый флаг ``name``, ``(name)``,
    ``(name yes|true)`` -> ``True``; ``(name no|false)`` -> ``False``; нет токена -> ``None``.
    Позиционные атомы (текст, номер и т.п.) флагами не считаются."""
    if node is None:
        return None
    if node.has_flag(name):
        return True
    child = node.find(name)
    if child is None:
        return None
    a = child.atom(0)
    if a is None:
        return True
    return str(a) in _TRUE_WORDS


def _drop_bool(node: Node, name: str) -> None:
    """Удалить токен-флаг во всех формах (голый символ и узел ``(name …)``)."""
    node.set_flag(name, False)
    node.remove(name)


def _write_bool(node: Node, name: str, value: bool, profile: FormatProfile,
                order: Sequence[str] | None, *, write_false: bool = False) -> None:
    """Записать булев токен в форме профиля.

    ``bool_style == "yesno"`` (KiCad 8+) — ``(name yes)``; ``False`` удаляет токен (или пишет
    ``(name no)`` при ``write_false``). ``"flag"`` (KiCad 5–7) — голый символ ``name`` на месте
    по таблице ``order``; ``False`` удаляет его.
    """
    if profile.bool_style == "yesno":
        node.set_flag(name, False)
        if value or write_false:
            node.set(name, Sym("yes" if value else "no"), order=order)
        else:
            node.remove(name)
    else:
        node.remove(name)
        node.set_flag(name, bool(value), order=order)


# --- uuid / tstamp -----------------------------------------------------------------

def _id_node(node: Node) -> Node | None:
    """Дочерний узел ``(uuid …)`` или ``(tstamp …)``."""
    for x in node.items:
        if isinstance(x, Node) and x.name in ("uuid", "tstamp"):
            return x
    return None


def _get_id(node: Node) -> str | None:
    """Значение ``(uuid …)``/``(tstamp …)`` или ``None``."""
    n = _id_node(node)
    if n is None:
        return None
    a = n.atom(0)
    return None if a is None else str(a)


def _id_atom(token: str, value: str) -> Atom:
    """``uuid`` — в кавычках (8+), ``tstamp`` — голый (6/7)."""
    return Str(value) if token == "uuid" else Sym(value)


def _new_uuid() -> str:
    """Новый идентификатор (``uuid4``)."""
    return str(_uuidlib.uuid4())


def _set_id(node: Node, value: str | None, profile: FormatProfile,
            order: Sequence[str] | None) -> None:
    """Записать идентификатор: существующий токен (``uuid`` или ``tstamp``) сохраняет свою
    форму; новый создаётся по профилю; ``None`` удаляет."""
    existing = _id_node(node)
    if value is None:
        node.remove("uuid")
        node.remove("tstamp")
        return
    value = _check_str(value, "uuid", allow_empty=False)
    if existing is not None:
        existing.items = [_id_atom(existing.name, value)] + existing.nodes()
        return
    token = profile.uuid_token
    node.set(token, _id_atom(token, value), order=order)


def _add_new_id(node: Node, profile: FormatProfile, order: Sequence[str] | None,
                value: str | bool | None = True) -> None:
    """Добавить идентификатор новому элементу: ``True`` — ``uuid4``, строка — это значение,
    ``False``/``None`` — не добавлять. В KiCad 5 (``module``) у элементов идентификаторов нет."""
    if value is None or value is False or profile.root == "module":
        return
    _set_id(node, _new_uuid() if value is True else str(value), profile, order)


# --- координатные узлы ---------------------------------------------------------------

def _xy_of(node: Node | None) -> Point | None:
    """Первые два атома узла как точка или ``None``."""
    if node is None:
        return None
    x, y = _num(node.atom(0)), _num(node.atom(1))
    if x is None or y is None:
        return None
    return (x, y)


def _set_xy(node: Node, p: Point) -> None:
    """Заменить первые два атома узла координатами (остальные атомы сохраняются)."""
    node.set_atom(0, _len(p[0]))
    node.set_atom(1, _len(p[1]))


def _point_of(parent: Node, name: str) -> Point | None:
    """Точка из дочернего узла ``(name x y)``."""
    return _xy_of(parent.find(name))


def _set_point(parent: Node, name: str, p: Point, order: Sequence[str] | None) -> None:
    """Установить ``(name x y)``: существующий узел меняет только координаты, новый
    вставляется по таблице порядка."""
    child = parent.find(name)
    if child is None:
        parent.set(name, _len(p[0]), _len(p[1]), order=order)
    else:
        _set_xy(child, p)


def _at_angle_index(at: Node) -> int | None:
    """Индекс атома угла в ``(at x y [угол] [unlocked])`` или ``None``."""
    n = 0
    for i, x in enumerate(at.items):
        if isinstance(x, Node):
            continue
        if n == 2:
            return i if is_number(x) else None
        n += 1
    return None


def _at_angle(at: Node | None) -> float:
    """Угол из ``(at x y [угол])``; нет угла — 0."""
    if at is None:
        return 0.0
    i = _at_angle_index(at)
    return 0.0 if i is None else float(at.items[i])


def _set_at_angle(at: Node, angle: float, *, always: bool) -> None:
    """Записать угол в ``(at x y …)``: ``always`` — всегда (тексты KiCad 8+), иначе нулевой
    угол не пишется (площадки, корпус, тексты KiCad 5–7). Флаги (``unlocked``) остаются
    после угла."""
    i = _at_angle_index(at)
    if angle == 0 and not always:
        if i is not None:
            del at.items[i]
        return
    atom = _ang(angle)
    if i is not None:
        at.items[i] = atom
        return
    # вставить третьим атомом (после x и y), перед флагами
    n = 0
    pos = len(at.items)
    for k, x in enumerate(at.items):
        if isinstance(x, Node):
            continue
        n += 1
        if n == 2:
            pos = k + 1
            break
    at.items.insert(pos, atom)


def _shift_node(node: Node, dx: float, dy: float) -> None:
    """Сдвинуть координаты ``(name x y …)``."""
    p = _xy_of(node)
    if p is not None:
        _set_xy(node, (p[0] + dx, p[1] + dy))


def _rotate_node(node: Node, angle: float, origin: Point) -> None:
    """Повернуть координаты ``(name x y …)`` вокруг ``origin``."""
    p = _xy_of(node)
    if p is not None:
        _set_xy(node, _geo.rotate_point(p, angle, origin))


def _mirror_node(node: Node, axis: str, origin: float) -> None:
    """Отразить координаты ``(name x y …)``."""
    p = _xy_of(node)
    if p is not None:
        _set_xy(node, _geo.mirror_point(p, axis, origin))


def _deep_coord_nodes(node: Node) -> list[Node]:
    """Все координатные узлы (at/start/end/center/mid/xy) на любой глубине."""
    out: list[Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        for x in n.items:
            if isinstance(x, Node):
                if x.name in _COORD_NODES:
                    out.append(x)
                else:
                    stack.append(x)
    return out


def _deep_layer_nodes(node: Node) -> list[Node]:
    """Все узлы ``layer``/``layers`` на любой глубине (включая сам ``node``)."""
    out: list[Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.name in ("layer", "layers"):
            out.append(n)
        stack.extend(x for x in n.items if isinstance(x, Node))
    return out


def _flip_layer_nodes(node: Node, profile: FormatProfile) -> None:
    """Сменить сторону всех слоёв в узлах ``layer``/``layers`` (F.* <-> B.*)."""
    for ln in _deep_layer_nodes(node):
        if ln.name == "layer":
            a = ln.atom(0)
            if a is not None:
                flipped = _L.flip_layer(str(a))
                if flipped != str(a):
                    ln.set_atom(0, _layer_atom(flipped, profile))
        else:
            for i, x in enumerate(ln.items):
                if not isinstance(x, Node):
                    flipped = _L.flip_layer(str(x))
                    if flipped != str(x):
                        ln.items[i] = _layer_atom(flipped, profile, in_list=True)


def _reorder(node: Node, order: Sequence[str]) -> None:
    """Упорядочить элементы узла по таблице ``order`` (для приведения формы при add/upgrade).

    Ведущие атомы (до первого подузла) остаются на месте; дальнейшие подузлы и голые
    флаги сортируются устойчиво по рангу имени в ``order``; элемент, которого нет в
    таблице, остаётся сразу после своего предшественника.
    """
    rank = {n: i for i, n in enumerate(order)}
    items = node.items
    k = 0
    while k < len(items) and not isinstance(items[k], Node):
        k += 1
    head, rest = items[:k], items[k:]
    keyed: list[tuple[int, int, Any]] = []
    last = -1
    for idx, x in enumerate(rest):
        name = x.name if isinstance(x, Node) else str(x)
        r = rank.get(name)
        if r is None:
            r = last
        else:
            last = r
        keyed.append((r, idx, x))
    keyed.sort(key=lambda t: (t[0], t[1]))
    node.items = head + [x for _, _, x in keyed]


class PointList(list):
    """Список точек ``[(x, y), …]``, который можно и вызвать.

    ``g.points`` и ``g.points()`` дают одно и то же: контракт описывает метод
    ``Graphic.points()`` (характерные точки) и свойство ``Poly.points`` с setter; объединённая
    форма поддерживает оба способа обращения.
    """

    __slots__ = ()

    def __call__(self) -> PointList:
        """Вернуть сам список (совместимость с вызовом ``points()``)."""
        return self


# ---------------------------------------------------------------------------
# Дуги: старая форма KiCad 5 (center/end/angle) <-> start/mid/end
# ---------------------------------------------------------------------------

def _kiround(x: float) -> int:
    """``KiROUND``: округление половины от нуля."""
    return int(x - 0.5) if x < 0 else int(x + 0.5)


def _to_nm(p: Point) -> tuple[int, int]:
    """Точка в целых нанометрах (как ``parseBoardUnits``)."""
    return (_kiround(p[0] * 1e6), _kiround(p[1] * 1e6))


def _eda_angle_of(dx: float, dy: float) -> float:
    """Угол вектора в градусах, как конструктор ``EDA_ANGLE(VECTOR2D)`` KiCad (со спецслучаями
    осей и диагоналей; ось Y вниз)."""
    if dx == 0 and dy == 0:
        return 0.0
    if dy == 0:
        return 0.0 if dx >= 0 else -180.0
    if dx == 0:
        return 90.0 if dy >= 0 else -90.0
    if dx == dy:
        return 45.0 if dx >= 0 else -135.0
    if dx == -dy:
        return -45.0 if dx >= 0 else 135.0
    return math.degrees(math.atan2(dy, dx))


def _normalize_eda(a: float) -> float:
    """``EDA_ANGLE::Normalize``: циклы ``+= 360`` / ``-= 360`` до [0, 360)."""
    while a < -0.0:
        a += 360.0
    while a >= 360.0:
        a -= 360.0
    return a


def _sin_cos_eda(a: float) -> tuple[float, float]:
    """``EDA_ANGLE::Sin/Cos`` для нормализованного угла (точные значения на кратных 45°)."""
    h = math.sqrt(0.5)
    exact = {0.0: (0.0, 1.0), 45.0: (h, h), 90.0: (1.0, 0.0), 135.0: (h, -h),
             180.0: (0.0, -1.0), 225.0: (-h, -h), 270.0: (-1.0, 0.0), 315.0: (-h, h)}
    if a in exact:
        return exact[a]
    r = a * (math.pi / 180.0)
    return (math.sin(r), math.cos(r))


def _rotate_nm(x: int, y: int, cx: int, cy: int, angle: float) -> tuple[int, int]:
    """``RotatePoint`` KiCad для целых нанометров (положительный угол — против часовой
    стрелки на экране)."""
    ox, oy = x - cx, y - cy
    a = _normalize_eda(float(angle))
    if a == 0.0:
        px, py = ox, oy
    elif a == 90.0:
        px, py = oy, -ox
    elif a == 180.0:
        px, py = -ox, -oy
    elif a == 270.0:
        px, py = -oy, ox
    else:
        s, c = _sin_cos_eda(a)
        px = _kiround(oy * s + ox * c)
        py = _kiround(oy * c - ox * s)
    return (px + cx, py + cy)


def _legacy_arc_three(center: Point, start: Point, angle: float) -> tuple[Point, Point, Point]:
    """Дуга KiCad 5 ``(start ЦЕНТР) (end НАЧАЛО) (angle A)`` -> ``(start, mid, end)`` ровно так,
    как это делает KiCad 6+ при чтении (``EDA_SHAPE::SetArcAngleAndEnd`` с перестановкой концов
    при ``A < 0``, затем ``GetArcMid``), в целых нанометрах."""
    cx, cy = _to_nm(center)
    sx, sy = _to_nm(start)
    a = float(angle)
    a720 = a
    while a720 < -360.0:
        a720 += 360.0
    while a720 >= 360.0:
        a720 -= 360.0
    ex, ey = _rotate_nm(sx, sy, cx, cy, -a720)
    if a < 0:
        (sx, sy), (ex, ey) = (ex, ey), (sx, sy)
    sa = _eda_angle_of(sx - cx, sy - cy)
    ea = _eda_angle_of(ex - cx, ey - cy)
    if ea == sa:
        ea = sa + 360.0
    while ea < sa:
        ea += 360.0
    mx, my = _rotate_nm(sx, sy, cx, cy, -(ea - sa) / 2.0)
    return ((sx / 1e6, sy / 1e6), (mx / 1e6, my / 1e6), (ex / 1e6, ey / 1e6))


def _three_to_legacy(s: Point, m: Point, e: Point) -> tuple[Point, Point, float]:
    """``start/mid/end`` -> ``(центр, начало, угол KiCad 5)``; угол KiCad 5 положителен по
    часовой стрелке на экране, т.е. ``-sweep`` (см. :func:`kicadfp.geometry.arc_three_points`).
    Вырожденная (коллинеарная) дуга: центр — середина хорды, угол 180°."""
    g = _geo.arc_from_three_points(s, m, e)
    if g is None:
        c = ((s[0] + e[0]) / 2.0, (s[1] + e[1]) / 2.0)
        return (c, s, -180.0)
    return (g.center, s, -g.sweep)


def _arc_is_legacy(node: Node) -> bool:
    """Узел дуги в старой форме: есть ``(angle …)`` и нет ``(mid …)``."""
    return node.find("mid") is None and node.find("angle") is not None


def _arc_three(node: Node) -> tuple[Point, Point, Point] | None:
    """Три точки дуги из узла любой формы (``None`` — узел неполный)."""
    if _arc_is_legacy(node):
        c = _point_of(node, "start")
        sp = _point_of(node, "end")
        a = _num(node.value("angle"))
        if c is None or sp is None or a is None:
            return None
        return _legacy_arc_three(c, sp, a)
    s = _point_of(node, "start")
    e = _point_of(node, "end")
    if s is None or e is None:
        return None
    m = _point_of(node, "mid")
    if m is None:
        m = ((s[0] + e[0]) / 2.0, (s[1] + e[1]) / 2.0)
    return (s, m, e)


def _arc_write_modern(node: Node, s: Point, m: Point, e: Point) -> None:
    """Записать дугу в форме ``start/mid/end`` (старая форма перестраивается: ``start``
    становится началом, добавляется ``mid`` после него, ``angle`` удаляется)."""
    node.remove("angle")
    st = node.find("start")
    if st is None:
        node.items.insert(0, Node("start", [_len(s[0]), _len(s[1])]))
        st = node.find("start")
    else:
        _set_xy(st, s)
    mid = node.find("mid")
    if mid is None:
        node.items.insert(node.index(st) + 1, Node("mid", [_len(m[0]), _len(m[1])]))
    else:
        _set_xy(mid, m)
    en = node.find("end")
    if en is None:
        mid = node.find("mid")
        node.items.insert(node.index(mid) + 1, Node("end", [_len(e[0]), _len(e[1])]))
    else:
        _set_xy(en, e)


def _arc_write_legacy(node: Node, s: Point, m: Point, e: Point) -> None:
    """Записать дугу в старой форме KiCad 5: ``(start ЦЕНТР) (end НАЧАЛО) (angle A)``."""
    c, sp, a = _three_to_legacy(s, m, e)
    node.remove("mid")
    st = node.find("start")
    if st is None:
        node.items.insert(0, Node("start", [_len(c[0]), _len(c[1])]))
        st = node.find("start")
    else:
        _set_xy(st, c)
    en = node.find("end")
    if en is None:
        en = Node("end", [_len(sp[0]), _len(sp[1])])
        node.items.insert(node.index(st) + 1, en)
    else:
        _set_xy(en, sp)
    an = node.find("angle")
    if an is None:
        node.items.insert(node.index(en) + 1, Node("angle", [_ang(a)]))
    else:
        an.items = [_ang(a)]


# ---------------------------------------------------------------------------
# Базовое представление
# ---------------------------------------------------------------------------

class View:
    """Базовый класс представления над узлом дерева S-выражений.

    ``node`` — узел-носитель; ``profile`` — профиль формата: у представления, полученного из
    корпуса, — профиль корпуса (вычисляется при каждом обращении), у отдельно созданного —
    переданный при создании или профиль KiCad 9 (``DEFAULT_VERSION``). Представления равны,
    если это представления одного класса над одним и тем же узлом (по идентичности).
    """

    __slots__ = ("node", "_profile", "_parent")

    def __init__(self, node: Node, profile: FormatProfile | None = None,
                 parent: Footprint | None = None) -> None:
        if not isinstance(node, Node):
            raise TypeError("представление создаётся над узлом sexpr.Node")
        self.node = node
        self._profile = profile
        self._parent = parent

    @property
    def profile(self) -> FormatProfile:
        """Профиль формата, по которому пишутся новые токены."""
        if self._parent is not None:
            return self._parent.profile
        if self._profile is not None:
            return self._profile
        return _default_profile()

    @property
    def parent(self) -> Footprint | None:
        """Корпус, из которого получено представление (``None`` — отдельный элемент)."""
        return self._parent

    def _order(self) -> Sequence[str] | None:
        """Таблица порядка дочерних токенов узла (для вставки новых)."""
        return None

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.node is getattr(other, "node", None)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(self.node)

    def copy(self) -> View:
        """Представление над глубокой копией узла (не входит ни в какой корпус; профиль —
        текущий профиль исходного представления)."""
        return type(self)(self.node.copy(), self.profile)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.node!r})"

    # --- общие помощники для числовых токенов ---------------------------------------
    def _get_num(self, name: str, i: int = 0) -> float | None:
        return self.node.number(name, i)

    def _set_opt(self, name: str, value: Any, fmt: Callable[[float], Sym],
                 what: str | None = None) -> None:
        """Необязательный числовой токен ``(name v)``: ``None`` удаляет."""
        if value is None:
            self.node.remove(name)
            return
        v = _check_real(value, what or name)
        self.node.set(name, fmt(v), order=self._order())

    def _set_opt_int(self, name: str, value: Any) -> None:
        if value is None:
            self.node.remove(name)
            return
        self.node.set(name, Sym(str(_check_int(value, name))), order=self._order())

    def _set_opt_str(self, name: str, value: Any, *, quoted: bool = True) -> None:
        if value is None:
            self.node.remove(name)
            return
        s = _check_str(value, name)
        atom: Atom = Str(s) if quoted else _str_atom(s, self.profile)
        self.node.set(name, atom, order=self._order())


def _num_prop(token: str, kind: str, doc: str) -> builtins.property:
    """Свойство для необязательного числового токена ``(token v)``.

    ``kind``: ``"len"`` (длина, мм), ``"ang"`` (угол), ``"dbl"`` (коэффициент), ``"int"``.
    Getter — значение или ``None``; setter — запись по таблице порядка узла, ``None`` удаляет.
    """
    fmt = {"len": _len, "ang": _ang, "dbl": _dbl}.get(kind)

    def fget(self: View) -> Any:
        v = self.node.number(token)
        if v is None:
            return None
        return int(v) if kind == "int" else v

    def fset(self: View, value: Any) -> None:
        if kind == "int":
            self._set_opt_int(token, value)
        else:
            self._set_opt(token, value, fmt)  # type: ignore[arg-type]

    return builtins.property(fget, fset, doc=doc)


def _str_prop(token: str, doc: str) -> builtins.property:
    """Свойство для необязательного строкового токена ``(token "v")`` (всегда в кавычках)."""

    def fget(self: View) -> str | None:
        v = self.node.value(token)
        return None if v is None else str(v)

    def fset(self: View, value: Any) -> None:
        self._set_opt_str(token, value)

    return builtins.property(fget, fset, doc=doc)


# ---------------------------------------------------------------------------
# Drill
# ---------------------------------------------------------------------------

class Drill(View):
    """Отверстие площадки: узел ``(drill [oval] d1 [d2] [(offset x y)])``.

    Все формы KiCad: ``(drill 0.8)``, ``(drill oval 1.2 0.8)``, ``(drill oval 1)`` (овал с
    равными сторонами), ``(drill 0.8 (offset 0 0.1))``, ``(drill (offset x y))`` без размера
    (SMD-площадка со смещённой формой), пустой ``(drill)``. Порядок элементов для KiCad
    произволен; представление меняет только нужный атом.
    """

    __slots__ = ()

    def _order(self) -> Sequence[str]:
        return DRILL_ORDER

    @classmethod
    def new(cls, diameter: float = 0.0, width: float | None = None, *, oval: bool | None = None,
            offset: Point = (0.0, 0.0), profile: FormatProfile | None = None) -> Drill:
        """Новое отверстие: ``Drill.new(0.8)`` — круглое, ``Drill.new(1.2, 0.8)`` — овальное
        (``oval`` по умолчанию истинно, если задан ``width``), ``offset`` — смещение формы
        площадки относительно отверстия."""
        d = _check_real(diameter, "diameter")
        is_oval = (width is not None) if oval is None else bool(oval)
        atoms: list[Any] = [Sym("oval")] if is_oval else []
        atoms.append(_len(d))
        if width is not None:
            w = _check_real(width, "width")
            if not is_oval or w != d:
                atoms.append(_len(w))
        node = Node("drill", atoms)
        ox, oy = _as_point(offset, "offset")
        if ox or oy:
            node.append(Node("offset", [_len(ox), _len(oy)]))
        return cls(node, profile)

    def _numeric_indices(self) -> list[int]:
        return [i for i, x in enumerate(self.node.items)
                if not isinstance(x, Node) and is_number(x)]

    @property
    def oval(self) -> bool:
        """Овальное отверстие (голый символ ``oval``)."""
        return self.node.has_flag("oval")

    @oval.setter
    def oval(self, value: bool) -> None:
        v = bool(value)
        if v == self.oval:
            return
        if v:
            self.node.items.insert(0, Sym("oval"))
        else:
            self.node.set_flag("oval", False)
            nums = self._numeric_indices()
            if len(nums) > 1:
                del self.node.items[nums[1]]

    @property
    def diameter(self) -> float:
        """Первый размер ``d1`` (для овала — размер по X); 0.0, если размера нет."""
        nums = self._numeric_indices()
        return float(self.node.items[nums[0]]) if nums else 0.0

    @diameter.setter
    def diameter(self, value: float) -> None:
        v = _len(_check_real(value, "diameter"))
        nums = self._numeric_indices()
        if nums:
            self.node.items[nums[0]] = v
            return
        pos = 1 if self.node.items and self.node.items[0] == "oval" \
            and not isinstance(self.node.items[0], Node) else 0
        self.node.items.insert(pos, v)

    @property
    def width(self) -> float | None:
        """Второй размер овального отверстия ``d2`` (по Y); для ``(drill oval w)`` — ``w``;
        ``None`` у круглого отверстия."""
        if not self.oval:
            return None
        nums = self._numeric_indices()
        if len(nums) > 1:
            return float(self.node.items[nums[1]])
        return float(self.node.items[nums[0]]) if nums else None

    @width.setter
    def width(self, value: float | None) -> None:
        nums = self._numeric_indices()
        if value is None:
            if len(nums) > 1:
                del self.node.items[nums[1]]
            return
        v = _len(_check_real(value, "width"))
        if not self.oval:
            # второй размер имеет смысл только у овала (KiCad пишет d2 только для oval)
            self.node.items.insert(0, Sym("oval"))
            nums = self._numeric_indices()
        if len(nums) > 1:
            self.node.items[nums[1]] = v
        elif nums:
            self.node.items.insert(nums[0] + 1, v)
        else:
            self.node.items.insert(1, _len(0.0))
            self.node.items.insert(2, v)

    @property
    def size(self) -> tuple[float, float]:
        """Размеры ``(по X, по Y)``: для круглого — ``(d, d)``."""
        d = self.diameter
        w = self.width
        return (d, d if w is None else w)

    def _offset_node(self) -> Node | None:
        return self.node.find("offset")

    @property
    def offset_x(self) -> float:
        """Смещение формы площадки относительно отверстия по X (0.0, если нет ``offset``)."""
        p = _xy_of(self._offset_node())
        return 0.0 if p is None else p[0]

    @offset_x.setter
    def offset_x(self, value: float) -> None:
        self._set_offset(_check_real(value, "offset_x"), self.offset_y)

    @property
    def offset_y(self) -> float:
        """Смещение по Y (0.0, если нет ``offset``)."""
        p = _xy_of(self._offset_node())
        return 0.0 if p is None else p[1]

    @offset_y.setter
    def offset_y(self, value: float) -> None:
        self._set_offset(self.offset_x, _check_real(value, "offset_y"))

    @property
    def offset(self) -> Point:
        """Смещение ``(x, y)``; присваивание ``(0, 0)`` удаляет ``(offset …)``."""
        return (self.offset_x, self.offset_y)

    @offset.setter
    def offset(self, value: Point) -> None:
        self._set_offset(*_as_point(value, "offset"))

    def _set_offset(self, x: float, y: float) -> None:
        if x == 0 and y == 0:
            self.node.remove("offset")
            return
        _set_point(self.node, "offset", (x, y), DRILL_ORDER)
