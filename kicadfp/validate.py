"""Проверка посадочного места (architecture.md §10, ТЗ 4.1.5).

Модуль содержит класс замечания :class:`Issue`, реестр правил :data:`RULES` с
декоратором-регистратором :func:`rule` и функцию :func:`validate`.

Каждое правило — функция ``(fp: Footprint) -> Iterable``, зарегистрированная
декоратором ``@rule(code, level)``. Правило выдаёт (``yield``) либо готовые
:class:`Issue`, либо пары ``(сообщение, элемент)``, либо просто строку-сообщение —
код и уровень подставляются из декоратора. Правила независимы: исключение внутри одного
правила не прерывает проверку, а превращается в замечание уровня ``error`` с кодом
``RULE_CRASH`` (замечания, выданные правилом до исключения, сохраняются).

Коды замечаний
--------------

========================  =======  ==============================================================
код                       уровень  смысл
========================  =======  ==============================================================
``PAD_DUP_NUMBER``        warning  несколько площадок с одним номером (в KiCad — один вывод)
``PAD_NO_LAYERS``         error    у площадки нет слоёв
``PAD_THT_NO_DRILL``      error    у сквозной площадки (thru_hole/np_thru_hole) нет отверстия
``PAD_SMD_WITH_DRILL``    error    у планарной площадки (smd/connect) есть отверстие
``PAD_DRILL_GT_SIZE``     error    отверстие больше площадки по одной из осей (с учётом овала и
                                   смещения формы ``offset``)
``TEXT_MISSING_REFERENCE``error    нет текста/поля Reference
``TEXT_MISSING_VALUE``    error    нет текста/поля Value
``TEXT_DUP_FIELD``        error    поле корпуса (Reference, Value, Datasheet …) задано
                                   несколькими узлами: KiCad оставляет одно (последний узел
                                   переписывает прежние), остальные теряются
``TEXT_REF_VALUE_LAYER``  warning  Reference/Value не на ``*.SilkS`` и не на ``*.Fab``
``TEXT_BAD_LAYER``        error    текст на несуществующем слое
``GRAPHIC_BAD_LAYER``     error    графика на несуществующем слое
``PAD_BAD_LAYER``         error    площадка на несуществующем слое
``FOOTPRINT_BAD_LAYER``   error    слой корпуса не ``F.Cu``/``B.Cu``
``ENUM_BAD_VALUE``        error    недопустимое значение перечисления (тип и форма площадки,
                                   флаги ``attr``, ``fill``, тип линии ``stroke``, вид ``fp_text``)
``SIZE_NOT_POSITIVE``     error    нулевой/отрицательный размер площадки, отрицательный диаметр
                                   отверстия, отрицательная ширина линии, размер шрифта ≤ 0,
                                   отрицательная толщина шрифта
``COURTYARD_MISSING``     warning  нет области размещения (``*.CrtYd``); не выдаётся при
                                   ``attr allow_missing_courtyard``
``PAD_NPTH_NUMBER``       warning  у неметаллизированного отверстия есть номер
``PAD_EMPTY_NUMBER``      warning  у thru_hole/smd/connect с медью пустой номер
``PAD_THT_NO_COPPER``     warning  у металлизированной площадки нет меди на внешних слоях
``LAYER_RESCUE``          warning  элемент на слое ``Rescue`` (так KiCad помечает неизвестные слои)
``VERSION_TOO_NEW``       warning  версия формата новее известной программе
``RULE_CRASH``            error    правило завершилось исключением (ошибка программы или
                                   сильно повреждённый файл)
========================  =======  ==============================================================

Решения, принятые там, где контракт неполон (сверено с ``PAD::CheckPad`` KiCad 9,
``pcbnew/pad.cpp``, и с официальными библиотеками):

* ``PAD_THT_NO_DRILL`` проверяется и у ``np_thru_hole`` (у KiCad — та же ошибка
  ``DRCE_PAD_TH_WITH_NO_HOLE``); отверстием считается диаметр > 0 (у овала — обе стороны).
* ``PAD_SMD_WITH_DRILL`` — только при ненулевом размере отверстия: узел
  ``(drill (offset x y))`` без размера у SMD-площадки — законный способ сместить форму
  (KiCad проверяет ``drill_size.x > 0 || drill_size.y > 0``).
* ``PAD_DRILL_GT_SIZE`` — у ``thru_hole`` и ``np_thru_hole`` (буква контракта; KiCad
  у NPTH проверяет лишь попадание центра отверстия в форму, но в 22 718 файлах
  официальных библиотек v6–master и фикстурах нет ни одной NPTH-площадки меньше
  отверстия, у 1255 размер равен отверстию). Сравнение по каждой оси в системе
  площадки (поворот одинаково действует на форму и отверстие): отверстие ``[-dx/2, dx/2]`` должно лежать внутри формы
  ``[ox - sx/2, ox + sx/2]``; ``circle`` — диаметр ``size_x`` по обеим осям; ``trapezoid``
  — с учётом ``rect_delta``; ``custom`` — описанный прямоугольник якоря и примитивов.
  Равенство размеров (медь без пояска) замечанием не считается. Допуск — 1 нм.
* ``PAD_THT_NO_COPPER`` — как в KiCad: у ``thru_hole`` нет ни ``F.Cu``, ни ``B.Cu``
  (с учётом групповых обозначений); это покрывает и «нет медных слоёв вообще».
* ``PAD_EMPTY_NUMBER`` не выдаётся для площадок без меди (апертуры пасты/маски,
  номер им не нужен).
* ``PAD_DUP_NUMBER`` не выдаётся, если у корпуса ``(duplicate_pad_numbers_are_jumpers
  yes)`` (KiCad 10: одинаковые номера — намеренные перемычки); пустые номера не
  сравниваются. Замечание выдаётся для каждой повторной площадки (элемент — она).
* Имена слоёв проверяет :func:`kicadfp.layers.is_valid_layer`: у площадки допустимы
  групповые обозначения (``*.Cu``, ``F&B.Cu`` …), у графики и текстов — только
  канонические имена (``single=True``, как парсер KiCad для ``(layer X)``). Отсутствие
  слоя у текста/графики не проверяется (так бывает у полей без ``layer``).
* ``fill``: допустимы ``yes``, ``no``, ``solid``, ``none`` и штриховки KiCad 10
  (``hatch``, ``reverse_hatch``, ``cross_hatch``); пустой ``(fill)`` допустим.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Union

from . import layers as _L
from .format_rules import ATTR_ORDER
from .model import (
    PAD_SHAPES,
    PAD_TYPES,
    STROKE_TYPES,
    TEXT_KINDS,
    Footprint,
    Graphic,
    Pad,
    Text,
    View,
)
from .sexpr import Node, SexprSyntaxError, format_number, is_number

__all__ = [
    "Issue", "RULES", "rule", "validate", "has_errors",
    "syntax_issue", "LEVELS", "MAX_KNOWN_VERSION", "FILL_VALUES",
]

#: Допустимые уровни замечаний.
LEVELS: tuple[str, ...] = ("error", "warning")

#: Наибольшая версия формата, известная программе (KiCad 10-dev, 20260206);
#: файл с большей версией — предупреждение ``VERSION_TOO_NEW``.
MAX_KNOWN_VERSION: int = 20260206

#: Допустимые значения ``(fill …)`` у графики (все версии, включая штриховки KiCad 10).
FILL_VALUES: frozenset[str] = frozenset(
    ("yes", "no", "solid", "none", "hatch", "reverse_hatch", "cross_hatch"))

#: Допуск сравнения размеров, мм (1 нм — разрешение KiCad).
EPS: float = 1e-6

_COURTYARD_LAYERS = frozenset(("F.CrtYd", "B.CrtYd"))
_REF_VALUE_LAYERS = frozenset(("F.SilkS", "B.SilkS", "F.Fab", "B.Fab"))
_OUTER_COPPER = frozenset(("F.Cu", "B.Cu"))

_GRAPHIC_KIND_RU = {
    "line": "линия", "rect": "прямоугольник", "circle": "окружность", "arc": "дуга",
    "poly": "многоугольник", "curve": "кривая Безье",
}


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """Замечание проверки.

    ``level`` — ``"error"`` | ``"warning"``; ``code`` — машинный код (``PAD_DUP_NUMBER`` …,
    см. docstring модуля); ``message`` — сообщение по-русски с идентификатором элемента
    (номер площадки, вид графики и слой, координаты); ``element`` — представление
    (:class:`~kicadfp.model.Pad`, :class:`~kicadfp.model.Graphic`,
    :class:`~kicadfp.model.Text`, :class:`~kicadfp.model.Footprint`), узел или ``None``.

    ``str(issue)`` — ``"ERROR PAD_DRILL_GT_SIZE: сообщение"`` (формат вывода CLI
    ``LEVEL CODE: message``).
    """

    level: str
    code: str
    message: str
    element: Union[View, Node, None] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"уровень замечания — error или warning, а не {self.level!r}")

    @property
    def is_error(self) -> bool:
        """Замечание уровня ``error``."""
        return self.level == "error"

    @property
    def node(self) -> Node | None:
        """Узел элемента (у представления — его ``node``), ``None`` если элемента нет."""
        el = self.element
        if isinstance(el, View):
            return el.node
        return el if isinstance(el, Node) else None

    @property
    def line(self) -> int:
        """Строка элемента в исходном файле (1-based) или 0 (неизвестно/создан в памяти)."""
        n = self.node
        return 0 if n is None else n.line

    def to_dict(self) -> dict[str, Any]:
        """Словарь для JSON (``level``, ``code``, ``message``, ``line``)."""
        return {"level": self.level, "code": self.code, "message": self.message,
                "line": self.line}

    def __str__(self) -> str:
        return f"{self.level.upper()} {self.code}: {self.message}"


# ---------------------------------------------------------------------------
# Реестр правил
# ---------------------------------------------------------------------------

RuleFunc = Callable[[Footprint], Iterable[Issue]]

#: Зарегистрированные правила в порядке регистрации. Каждое — генератор
#: ``(fp) -> Iterable[Issue]`` с атрибутами ``code``, ``level`` и ``check`` (исходная функция).
RULES: list[RuleFunc] = []


def rule(code: str, level: str) -> Callable[[Callable[[Footprint], Iterable[Any]]], RuleFunc]:
    """Декоратор-регистратор правила проверки.

    Декорируемая функция принимает :class:`~kicadfp.model.Footprint` и выдаёт замечания:
    :class:`Issue` (как есть — можно переопределить код/уровень), пару
    ``(сообщение, элемент)`` или строку (элемент — ``None``); код и уровень берутся из
    аргументов декоратора. Результат — обёртка-генератор, добавленная в :data:`RULES`
    (правило с тем же ``code`` и тем же именем функции заменяется — повторный импорт или
    переопределение не дублируют проверку).
    """
    if level not in LEVELS:
        raise ValueError(f"уровень правила — error или warning, а не {level!r}")
    if not code or not isinstance(code, str):
        raise ValueError("код правила — непустая строка")

    def decorate(fn: Callable[[Footprint], Iterable[Any]]) -> RuleFunc:
        @functools.wraps(fn)
        def wrapper(fp: Footprint) -> Iterator[Issue]:
            result = fn(fp)
            if result is None:
                return
            for item in result:
                if isinstance(item, Issue):
                    yield item
                elif isinstance(item, tuple):
                    msg, element = item
                    yield Issue(level, code, str(msg), element)
                else:
                    yield Issue(level, code, str(item), None)

        wrapper.code = code  # type: ignore[attr-defined]
        wrapper.level = level  # type: ignore[attr-defined]
        wrapper.check = fn  # type: ignore[attr-defined]
        for i, r in enumerate(RULES):
            if getattr(r, "code", None) == code and r.__name__ == wrapper.__name__:
                RULES[i] = wrapper
                break
        else:
            RULES.append(wrapper)
        return wrapper

    return decorate


def validate(fp: Footprint, strict: bool = False, *,
             rules: Iterable[RuleFunc] | None = None) -> list[Issue]:
    """Проверить корпус всеми правилами (или ``rules``) и вернуть список замечаний.

    Порядок — порядок правил, внутри правила — порядок элементов в файле. ``strict`` не
    меняет список (его использует :func:`kicadfp.io.save`: при ``strict=True`` и наличии
    ошибок файл не записывается). Исключение в правиле даёт замечание ``RULE_CRASH``
    (уровень ``error``), остальные правила выполняются.
    """
    if not isinstance(fp, Footprint):
        if isinstance(fp, Node):
            fp = Footprint(fp)
        else:
            raise TypeError("validate: ожидается Footprint")
    out: list[Issue] = []
    for r in (RULES if rules is None else list(rules)):
        try:
            for issue in r(fp):
                out.append(issue)
        except Exception as e:  # noqa: BLE001 — правила независимы (ТЗ 4.1.5)
            code = getattr(r, "code", getattr(r, "__name__", "?"))
            out.append(Issue("error", "RULE_CRASH",
                             f"правило {code} завершилось с ошибкой: "
                             f"{type(e).__name__}: {e}", None))
    return out


def has_errors(issues: Iterable[Issue]) -> bool:
    """Есть ли среди замечаний хотя бы одно уровня ``error``."""
    return any(getattr(i, "level", None) == "error" for i in issues)


def errors(issues: Iterable[Issue]) -> list[Issue]:
    """Только замечания уровня ``error``."""
    return [i for i in issues if i.level == "error"]


def warnings(issues: Iterable[Issue]) -> list[Issue]:
    """Только замечания уровня ``warning``."""
    return [i for i in issues if i.level == "warning"]


def syntax_issue(exc: SexprSyntaxError, path: str | None = None) -> Issue:
    """Замечание ``SEXPR_SYNTAX`` (error) для ошибки разбора файла — для вызывающих,
    которые проверяют файлы (CLI, :meth:`Library.validate_all`) и хотят единый список."""
    head = f"{path}: " if path else ""
    return Issue("error", "SEXPR_SYNTAX", f"{head}ошибка разбора: {exc}", None)


# ---------------------------------------------------------------------------
# Описание элементов для сообщений
# ---------------------------------------------------------------------------

def _n(v: float | None) -> str:
    """Число для сообщения (как в файле KiCad: без хвостовых нулей)."""
    if v is None:
        return "?"
    return format_number(v)


def _xy(x: float, y: float) -> str:
    return f"({_n(x)}; {_n(y)})"


def _pad_id(p: Pad) -> str:
    """«площадка «1» (x; y)» / «площадка без номера (x; y)»."""
    num = p.number
    head = f"площадка «{num}»" if num else "площадка без номера"
    return f"{head} {_xy(p.x, p.y)}"


def _graphic_id(g: Graphic) -> str:
    """«линия fp_line на слое F.SilkS от (x; y)»."""
    kind = _GRAPHIC_KIND_RU.get(g.kind, g.kind)
    layers = g.layers
    where = f" на слое {', '.join(layers)}" if layers else ""
    pts = g._points()
    at = f" в точке {_xy(*pts[0])}" if pts else ""
    return f"{kind} {g.node.name}{where}{at}"


def _text_id(t: Text) -> str:
    """«текст reference «REF**» (x; y)» / «поле «Datasheet» (x; y)»."""
    if t.is_property:
        head = f"поле «{t.name}»"
    else:
        head = f"текст {t.kind}"
    txt = t.text
    shown = txt if len(txt) <= 40 else txt[:37] + "…"
    return f"{head} «{shown}» {_xy(t.x, t.y)}"


def _expanded(names: Iterable[str]) -> set[str]:
    return set(_L.expand([n for n in names if _L.is_valid_layer(n)]))


def _has_copper(p: Pad) -> bool:
    return any(_L.is_copper(n) for n in _expanded(p.layers))


def _drill_size(p: Pad) -> tuple[float, float] | None:
    """Размер отверстия ``(dx, dy)`` или ``None`` (нет узла drill)."""
    d = p.drill
    return None if d is None else d.size


# ---------------------------------------------------------------------------
# Правила: площадки
# ---------------------------------------------------------------------------

@rule("PAD_DUP_NUMBER", "warning")
def check_pad_duplicate_numbers(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Повторяющиеся номера площадок (пустые номера не сравниваются)."""
    jumpers = fp.node.find("duplicate_pad_numbers_are_jumpers")
    if jumpers is not None and str(jumpers.atom(0, "")) in ("yes", "true"):
        return
    first: dict[str, Pad] = {}
    count: dict[str, int] = {}
    pads = fp.pads
    for p in pads:
        if p.number:
            count[p.number] = count.get(p.number, 0) + 1
    for p in pads:
        num = p.number
        if not num:
            continue
        if num not in first:
            first[num] = p
            continue
        f = first[num]
        yield (f"{_pad_id(p)}: номер «{num}» уже есть у площадки {_xy(f.x, f.y)} "
               f"(всего площадок с этим номером: {count[num]}); в KiCad площадки с "
               f"одинаковым номером — один вывод (электрически соединены)", p)


@rule("PAD_NO_LAYERS", "error")
def check_pad_layers_present(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Площадка без слоёв."""
    for p in fp.pads:
        if not p.layers:
            yield (f"{_pad_id(p)}: у площадки нет слоёв (layers)", p)


@rule("PAD_THT_NO_DRILL", "error")
def check_pad_tht_drill(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Сквозная площадка без отверстия (или с нулевым отверстием)."""
    for p in fp.pads:
        if p.type not in ("thru_hole", "np_thru_hole"):
            continue
        d = p.drill
        if d is None:
            yield (f"{_pad_id(p)}: у сквозной площадки ({p.type}) нет отверстия (drill)", p)
            continue
        dx, dy = d.size
        if dx <= 0 or (d.oval and dy <= 0):
            yield (f"{_pad_id(p)}: у сквозной площадки ({p.type}) нулевое отверстие "
                   f"(drill {_n(dx)}×{_n(dy)} мм)", p)


@rule("PAD_SMD_WITH_DRILL", "error")
def check_pad_smd_drill(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Планарная площадка (smd/connect) с отверстием ненулевого размера."""
    for p in fp.pads:
        if p.type not in ("smd", "connect"):
            continue
        size = _drill_size(p)
        if size is not None and (size[0] > 0 or size[1] > 0):
            yield (f"{_pad_id(p)}: у планарной площадки ({p.type}) есть отверстие "
                   f"{_n(size[0])}×{_n(size[1])} мм", p)


def _pad_extent(p: Pad) -> tuple[float, float, float, float]:
    """Габариты формы площадки в её системе (центр отверстия — начало, без поворота):
    ``(x1, y1, x2, y2)`` с учётом смещения ``offset``."""
    d = p.drill
    ox, oy = (0.0, 0.0) if d is None else d.offset
    sx, sy = p.size
    shape = p.shape
    if shape == "circle":
        sy = sx
    hx, hy = sx / 2.0, sy / 2.0
    if shape == "trapezoid":
        dx, dy = p.rect_delta or (0.0, 0.0)
        hx, hy = hx + abs(dy) / 2.0, hy + abs(dx) / 2.0
    x1, y1, x2, y2 = ox - hx, oy - hy, ox + hx, oy + hy
    if shape == "custom":
        if p.anchor == "circle":
            x1, y1, x2, y2 = ox - hx, oy - hx, ox + hx, oy + hx
        for g in p.primitive_views:
            b = g.bbox(with_width=True)
            if b is None:
                continue
            x1, y1 = min(x1, ox + b.x1), min(y1, oy + b.y1)
            x2, y2 = max(x2, ox + b.x2), max(y2, oy + b.y2)
    return x1, y1, x2, y2


@rule("PAD_DRILL_GT_SIZE", "error")
def check_pad_drill_size(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Отверстие больше площадки (по каждой оси, с учётом овала и смещения формы)."""
    for p in fp.pads:
        if p.type not in ("thru_hole", "np_thru_hole"):
            continue
        size = _drill_size(p)
        if size is None:
            continue
        dx, dy = size
        if dx <= 0:
            continue
        x1, y1, x2, y2 = _pad_extent(p)
        bad: list[str] = []
        if -dx / 2.0 < x1 - EPS or dx / 2.0 > x2 + EPS:
            bad.append("X")
        if -dy / 2.0 < y1 - EPS or dy / 2.0 > y2 + EPS:
            bad.append("Y")
        if not bad:
            continue
        d = p.drill
        hole = f"{_n(dx)}" if not (d is not None and d.oval) else f"{_n(dx)}×{_n(dy)}"
        off = ""
        if d is not None and d.offset != (0.0, 0.0):
            off = f", смещение формы {_xy(*d.offset)}"
        shape_sy = p.size_x if p.shape == "circle" else p.size_y
        yield (f"{_pad_id(p)}: отверстие больше площадки по оси {' и '.join(bad)}: "
               f"отверстие {hole} мм, площадка {p.shape} {_n(p.size_x)}×{_n(shape_sy)} мм"
               f"{off}", p)


@rule("PAD_NPTH_NUMBER", "warning")
def check_npth_number(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """У неметаллизированного отверстия есть номер (KiCad ожидает пустой)."""
    for p in fp.pads:
        if p.type == "np_thru_hole" and p.number:
            yield (f"{_pad_id(p)}: у неметаллизированного отверстия (np_thru_hole) есть "
                   f"номер «{p.number}»; KiCad ожидает пустой номер", p)


@rule("PAD_EMPTY_NUMBER", "warning")
def check_pad_empty_number(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Пустой номер у thru_hole/smd/connect с медью (у np_thru_hole пустой номер — норма)."""
    for p in fp.pads:
        if p.type in ("thru_hole", "smd", "connect") and not p.number and _has_copper(p):
            yield (f"{_pad_id(p)}: у площадки {p.type} нет номера — она не будет связана "
                   f"с выводом символа", p)


@rule("PAD_THT_NO_COPPER", "warning")
def check_pad_tht_copper(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Металлизированная площадка без меди на внешних слоях (как ``PAD::CheckPad``)."""
    for p in fp.pads:
        if p.type != "thru_hole" or not p.layers:
            continue
        if not (_expanded(p.layers) & _OUTER_COPPER):
            yield (f"{_pad_id(p)}: у металлизированного отверстия нет меди на внешних "
                   f"слоях (F.Cu/B.Cu); слои: {' '.join(p.layers)}", p)


@rule("PAD_BAD_LAYER", "error")
def check_pad_bad_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Площадка на несуществующем слое."""
    for p in fp.pads:
        bad = [n for n in p.layers if not _L.is_valid_layer(n)]
        if bad:
            yield (f"{_pad_id(p)}: несуществующий слой {', '.join(bad)}", p)


# ---------------------------------------------------------------------------
# Правила: тексты
# ---------------------------------------------------------------------------

@rule("TEXT_MISSING_REFERENCE", "error")
def check_reference_present(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Нет текста/поля Reference."""
    if fp.reference is None:
        yield (f"корпус «{fp.name}»: нет текста Reference (позиционного обозначения)", fp)


@rule("TEXT_MISSING_VALUE", "error")
def check_value_present(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Нет текста/поля Value."""
    if fp.value is None:
        yield (f"корпус «{fp.name}»: нет текста Value (номинала)", fp)


@rule("TEXT_DUP_FIELD", "error")
def check_dup_field(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Поле корпуса задано несколькими узлами (``fp_text reference``/``value`` и
    ``property`` с одним именем): парсер KiCad не заводит второго поля, а переписывает первое
    последним узлом, поэтому остальные молча теряются. Сообщение — на каждый лишний узел
    (кроме последнего, который KiCad и берёт)."""
    slots: dict[str, list[Node]] = {}
    for n in fp.node.nodes():
        if n.name == "fp_text":
            a = n.atom(0)
            name = {"reference": "Reference", "value": "Value"}.get(str(a)) if a is not None \
                else None
        elif n.name == "property":
            a = n.atom(0)
            name = None if a is None else str(a)
        else:
            continue
        if name is not None:
            slots.setdefault(name, []).append(n)
    for name, nodes in slots.items():
        for n in nodes[:-1]:
            yield (f"корпус «{fp.name}»: поле {name} задано {len(nodes)} раз(а) — KiCad "
                   f"оставит только последнее (строка {n.line or '?'} будет потеряна)",
                   Text(n, parent=fp) if n.name == "fp_text" or any(
                       n.find(t) is not None for t in ("at", "layer", "effects")) else n)


@rule("TEXT_REF_VALUE_LAYER", "warning")
def check_ref_value_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Reference/Value не на ``*.SilkS`` и не на ``*.Fab``."""
    for t in (fp.reference, fp.value):
        if t is None:
            continue
        layer = t.layer
        if layer is None or layer in _REF_VALUE_LAYERS or not _L.is_valid_layer(layer, single=True):
            continue
        yield (f"{_text_id(t)}: текст {'Reference' if t.kind == 'reference' else 'Value'} "
               f"на слое {layer}, обычно — F.SilkS/B.SilkS или F.Fab/B.Fab", t)


@rule("TEXT_BAD_LAYER", "error")
def check_text_bad_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Текст на несуществующем слое."""
    for t in fp.texts:
        layer = t.layer
        if layer is not None and not _L.is_valid_layer(layer, single=True):
            yield (f"{_text_id(t)}: несуществующий слой {layer}", t)


# ---------------------------------------------------------------------------
# Правила: графика
# ---------------------------------------------------------------------------

@rule("GRAPHIC_BAD_LAYER", "error")
def check_graphic_bad_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Графика на несуществующем слое."""
    for g in fp.graphics:
        bad = [n for n in g.layers if not _L.is_valid_layer(n, single=True)]
        if bad:
            yield (f"{_graphic_id(g)}: несуществующий слой {', '.join(bad)}", g)


@rule("COURTYARD_MISSING", "warning")
def check_courtyard(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Нет области размещения ``F.CrtYd``/``B.CrtYd`` (кроме ``allow_missing_courtyard``)."""
    if "allow_missing_courtyard" in fp.attrs:
        return
    for g in fp.graphics:
        if _COURTYARD_LAYERS.intersection(g.layers):
            return
    for z in fp.zones:
        names = [str(a) for n in z.nodes() if n.name in ("layer", "layers") for a in n.atoms()]
        if _COURTYARD_LAYERS.intersection(names):
            return
    yield (f"корпус «{fp.name}»: нет области размещения (графики на F.CrtYd/B.CrtYd)", fp)


# ---------------------------------------------------------------------------
# Правила: корпус, перечисления, размеры, слои
# ---------------------------------------------------------------------------

@rule("FOOTPRINT_BAD_LAYER", "error")
def check_footprint_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Слой корпуса — только ``F.Cu`` или ``B.Cu``."""
    layer = fp.layer
    if layer not in _OUTER_COPPER:
        yield (f"корпус «{fp.name}»: недопустимый слой корпуса {layer} "
               f"(допустимо: F.Cu, B.Cu)", fp)


@rule("ENUM_BAD_VALUE", "error")
def check_enums(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Недопустимые значения перечислений: тип/форма площадки, ``attr``, ``fill``, тип
    линии, вид ``fp_text``."""
    for p in fp.pads:
        if p.type not in PAD_TYPES:
            yield (f"{_pad_id(p)}: недопустимый тип площадки «{p.type}» "
                   f"(допустимо: {', '.join(PAD_TYPES)})", p)
        if p.shape not in PAD_SHAPES:
            yield (f"{_pad_id(p)}: недопустимая форма площадки «{p.shape}» "
                   f"(допустимо: {', '.join(PAD_SHAPES)})", p)
    attr = fp.node.find("attr")
    if attr is not None:
        for a in attr.atoms():
            if str(a) not in ATTR_ORDER:
                yield (f"корпус «{fp.name}»: недопустимый флаг attr «{a}» "
                       f"(допустимо: {', '.join(ATTR_ORDER)})", fp)
    graphics: list[Graphic] = list(fp.graphics)
    for p in fp.pads:
        graphics.extend(p.primitive_views)
    for g in graphics:
        f = g.node.find("fill")
        if f is not None:
            for a in f.atoms():
                if str(a) not in FILL_VALUES:
                    yield (f"{_graphic_id(g)}: недопустимое значение заливки fill «{a}» "
                           f"(допустимо: {', '.join(sorted(FILL_VALUES))})", g)
        st = g.node.find("stroke")
        if st is not None:
            for tn in st.nodes("type"):
                v = tn.atom(0)
                if v is None or str(v) not in STROKE_TYPES:
                    yield (f"{_graphic_id(g)}: недопустимый тип линии stroke «{v}» "
                           f"(допустимо: {', '.join(STROKE_TYPES)})", g)
    for t in fp.texts:
        if not t.is_property and t.kind not in TEXT_KINDS:
            yield (f"{_text_id(t)}: недопустимый вид текста fp_text «{t.kind}» "
                   f"(допустимо: {', '.join(TEXT_KINDS)})", t)


@rule("SIZE_NOT_POSITIVE", "error")
def check_sizes(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Нулевые/отрицательные размеры: площадка (size ≤ 0), отверстие (< 0), ширина
    линии (< 0), размер шрифта (≤ 0), толщина шрифта (< 0)."""
    for p in fp.pads:
        shape = p.shape
        if shape != "custom":
            sx, sy = p.size
            if sx <= 0 or (sy <= 0 and shape != "circle"):
                yield (f"{_pad_id(p)}: размер площадки должен быть положительным "
                       f"(size {_n(sx)}×{_n(sy)} мм)", p)
        size = _drill_size(p)
        if size is not None and (size[0] < 0 or size[1] < 0):
            yield (f"{_pad_id(p)}: отрицательный размер отверстия "
                   f"(drill {_n(size[0])}×{_n(size[1])} мм)", p)
        for g in p.primitive_views:
            w = g.width
            if w is not None and w < 0:
                yield (f"{_pad_id(p)}: примитив {_graphic_id(g)}: отрицательная ширина "
                       f"линии {_n(w)} мм", p)
    for g in fp.graphics:
        w = g.width
        if w is not None and w < 0:
            yield (f"{_graphic_id(g)}: отрицательная ширина линии {_n(w)} мм", g)
    for t in fp.texts:
        font = t._font()
        size_node = None if font is None else font.find("size")
        if size_node is not None:
            vals = [float(a) for a in size_node.atoms() if is_number(a)]
            if any(v <= 0 for v in vals[:2]):
                yield (f"{_text_id(t)}: размер шрифта должен быть положительным "
                       f"(size {' '.join(_n(v) for v in vals[:2])} мм)", t)
        th = t.thickness
        if th is not None and th < 0:
            yield (f"{_text_id(t)}: отрицательная толщина шрифта {_n(th)} мм", t)


def _layer_holders(fp: Footprint) -> Iterator[tuple[str, list[str], Any]]:
    """Все элементы со слоями: ``(описание, слои, элемент)``."""
    yield (f"корпус «{fp.name}»", [fp.layer], fp)
    for p in fp.pads:
        yield (_pad_id(p), p.layers, p)
    for g in fp.graphics:
        yield (_graphic_id(g), g.layers, g)
    for t in fp.texts:
        yield (_text_id(t), [] if t.layer is None else [t.layer], t)
    for z in fp.zones:
        names = [str(a) for n in z.nodes() if n.name in ("layer", "layers") for a in n.atoms()]
        yield (f"зона (строка {z.line})" if z.line else "зона", names, z)


@rule("LAYER_RESCUE", "warning")
def check_rescue_layer(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Элемент на слое ``Rescue`` (так KiCad помечает объекты с неизвестных слоёв)."""
    for what, names, el in _layer_holders(fp):
        if _L.RESCUE_LAYER in names:
            yield (f"{what}: слой Rescue — KiCad переносит сюда объекты с неизвестных "
                   f"слоёв; назначьте настоящий слой", el)


@rule("VERSION_TOO_NEW", "warning")
def check_version(fp: Footprint) -> Iterator[tuple[str, Any]]:
    """Версия формата новее известной программе (:data:`MAX_KNOWN_VERSION`)."""
    v = fp.version
    if v is not None and v > MAX_KNOWN_VERSION:
        yield (f"корпус «{fp.name}»: версия формата {v} новее известной программе "
               f"({MAX_KNOWN_VERSION}); незнакомые конструкции сохраняются как есть, но "
               f"проверка может быть неполной", fp)
