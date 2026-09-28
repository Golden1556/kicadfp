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

Отклонения от буквы контракта и решения, принятые по фактам формата KiCad (подробности — в
docstring соответствующих членов):

1. ``Text.font_size_x``/``font_size_y`` без токена ``(size …)`` возвращают 1.524 мм — умолчание
   парсера KiCad (``parseEDA_TEXT``), а не 1.0; новые тексты создаются размером 1.0 × 1.0.
2. ``Graphic.fill`` при отсутствии токена ``(fill …)`` следует правилам парсера KiCad
   (``parsePCB_SHAPE``): многоугольник не на ``Edge.Cuts`` и прямоугольник/окружность с
   нулевой шириной линии — залиты (так читаются файлы KiCad 5 и примитивы площадок), остальное
   — нет. Запись ``fill`` — по версии файла: ``solid|none`` для KiCad 6–8 (writer 8.0 тоже пишет
   ``solid|none``, format-writer.md §3.6), ``yes|no`` для KiCad 9+ (20241129+); у примитивов
   площадок — ``yes|none`` (6/7) и ``yes|no`` (8+).
3. Дуги: форму (``start/mid/end`` или старую ``center/end/angle``) KiCad выбирает **по версии
   файла** (``<= 20210925`` — старая; дуга ``start/mid/end`` в файле без версии — ошибка
   чтения «Unable to load library», проверено ``kicad-cli``), поэтому setters :class:`Arc` в
   файле KiCad 5 оставляют узел в старой форме (меняются центр, начало и угол), а в файле
   новой версии перестраивают старый узел в ``start/mid/end`` (единственный случай
   перестройки узла при присваивании одного значения). Старая форма читается ровно так, как
   KiCad 6+ (``EDA_SHAPE::SetArcAngleAndEnd`` в целых нанометрах с перестановкой концов при
   отрицательном угле), а не через :func:`kicadfp.geometry.arc_three_points`: результат тот
   же геометрически, но совпадает с KiCad и по порядку концов.
4. ``Graphic.width``/``Graphic.layer`` возвращают ``None``, если токена нет (примитивы площадок
   без слоя, фигуры без ширины); ``Graphic.bbox()`` — геометрические габариты без ширины линии
   (``with_width=True`` — с половиной ширины), ``None`` у узла без координат.
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
   смещение отверстия, срезанные углы, примитивы) отражаются по X, текстам на слоях одной
   стороны переключается ``justify mirror``.
9. Старая форма смещения модели ``(at (xyz …))`` (дюймы) пересчитывается множителем
   ``25.4f`` парсера KiCad (25.399999618530273), а не точным 25.4 — так значения совпадают с
   тем, что KiCad читает и пишет при пересохранении.
10. :meth:`Footprint.new` создаёт корпус в том виде, в каком его пишет KiCad версии формата:
    для KiCad 9 кроме Reference/Value — служебные поля Datasheet/Description и
    ``(embedded_fonts no)``; Reference (0, -0.5) на F.SilkS и Value (0, 1) на F.Fab — как
    новый корпус редактора KiCad. ``version=None`` — корень ``module`` (KiCad 5).
11. :attr:`Footprint.attrs` отражает токен как есть: у корпуса KiCad 5 без ``(attr …)``
    множество пусто, хотя KiCad считает такой корпус ``through_hole``
    (:meth:`Footprint.upgrade` дописывает ``(attr through_hole)``, как KiCad).
12. :attr:`Text.unlocked` — ``None``, если токена нет; :meth:`Pad.is_smd` истинно и для
    ``connect``; присваивание числа или пары ``Pad.drill`` при существующем узле меняет только
    размеры (``offset`` сохраняется).
13. :meth:`Footprint.add` приводит к профилю корпуса только представления; «голый» узел
    ``Node`` добавляется как есть.
14. :meth:`Footprint.upgrade` воспроизводит пересохранение KiCad 9 (сверено с
    ``kicad-cli fp upgrade`` 9.0.1 на 15 894 файлах официальных библиотек v6.0.0–v9.0.0 и
    2 287 файлах ``tests/fixtures`` в форматах KiCad 5–9: совпадение деревьев,
    кроме значений новых uuid и ``generator``, во всех случаях, кроме трёх видов,
    которые kicadfp намеренно не повторяет: зоны (keepout) сохраняются как есть, а KiCad
    нормализует их целиком; неизвестное имя слоя не заменяется на ``Rescue``; порядок
    текстов одного слоя без uuid в KiCad случаен); кроме того, скрытый ``fp_text user``
    kicadfp переводит в скрытое поле (п. 17), а kicad-cli 9.0.1 его теряет. По умолчанию
    ``generator`` становится ``"kicadfp"`` (файл записан kicadfp; ``generator=None`` — оставить прежний).
15. Версия файла — обещание, что KiCad этой версии его прочитает, поэтому setters, фабрики
    и :meth:`Footprint.add` не пишут конструкций, которых версия файла не знает, а дают
    ``ValueError`` с предложением выполнить :meth:`Footprint.upgrade`: флаги ``attr`` по
    версиям (KiCad 5 ``module`` — только ``smd``/``virtual``; ``allow_*`` — KiCad 7,
    ``dnp`` — 20230410, ``exclude_from_sim`` — 20260828), ``knockout`` (20220308),
    ``face`` (20211232), ``thermal_bridge_angle`` (20211227), ``private_layers``
    (20211231), ``net_tie_pad_groups`` (20220818), ``remove_unused_layers``/
    ``keep_end_layers`` (20200809), ``fp_rect`` (20200614) и заливка, отличная от
    умолчания парсера, в KiCad 5 (20201114); у площадки ``pinfunction`` (20191123),
    ``property`` (20200104), ``locked`` (20210108), ``pintype`` (20210126); ``locked`` у
    текста (20210925) и у фигуры (нет в KiCad 5); у 3D-модели ``hide`` (нет в KiCad 5) и
    ``opacity`` (20210824); свойство корпуса (20200808); ``sheetname``/``sheetfile``
    (KiCad 8, парсер 7.0 их не знает). Уже записанные в файле токены не
    проверяются (файл читается и пишется как есть; присваивание имеющемуся токену
    разрешено). Смена :attr:`Footprint.version` — только без изменения формы и смысла
    содержимого (см. там), иначе — :meth:`Footprint.upgrade`.
16. Правило nullable KiCad: в файле версии <= 20240201 ноль у ``clearance``/
    ``solder_mask_margin``/``solder_paste_margin``/``solder_paste_*ratio`` корпуса и
    площадки означает «не задано»: getter — ``None``, присваивание 0 удаляет токен (а при
    отсутствии переопределения ничего не меняет), :meth:`Footprint.upgrade` такие токены
    удаляет. В 9+ ноль — явное значение.
17. Скрытый пользовательский текст в формате KiCad 8+ (версия >= 20230620) — скрытое поле
    ``(property "FieldN" …)``, а не ``(fp_text user … (hide yes))``: KiCad 9 скрытых
    ``fp_text`` не поддерживает (kicad-cli 9.0.1 их теряет); см. :attr:`Text.hide`.
18. :meth:`Footprint.add`/:meth:`Pad.add_primitive` не копируют узел и отвергают
    представление, узел которого ещё входит в другой корпус (``item.copy()``).
19. Присваивание дуге точки, совпадающей с текущей (до 1 нм), узел не меняет (в том числе
    старую форму KiCad 5 не перекодирует); при перекодировании старой формы неизменные
    центр/начало сохраняются, угол считается по записанным центру и началу.
20. Дуга ``start/mid/end`` записывается с истинной серединой в ``mid`` (как writer KiCad):
    KiCad 6+ читает ``mid`` лишь как подсказку стороны и дугу с ``mid`` вдали от середины
    читает как дополнительную (см. :class:`Arc`).
"""

from __future__ import annotations

import builtins
import functools
import importlib
import math
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
    DRAWING_GROUPS,
    DRILL_ORDER,
    EFFECTS_ORDER,
    FONT_ORDER,
    FOOTPRINT_ORDER,
    KNOWN_FOOTPRINT_CHILDREN,
    MODEL_ORDER,
    PAD_ORDER,
    STROKE_ORDER,
    V_ARC_MID,
    V_FIELDS,
    V_FILL_YESNO,
    V_KICAD7,
    V_NORMALIZED,
    V_STROKE,
    FormatProfile,
    drawing_sort_key,
    group_of,
    insert_in_group,
    positional_atoms,
    profile_for,
)
from .geometry import BBox
from .sexpr import (Node, Str, Sym, format_angle, format_double, format_number, is_number,
                    to_compact)

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

# Множитель парсера KiCad для старой формы (model (at (xyz …))) в дюймах: константа float
# 25.4f, приведённая к double (``parseDouble() * 25.4f``, pcb_io_kicad_sexpr_parser.cpp).
_INCH_KICAD = 25.399999618530273
_V_ATTR_FLAGS = 20200826     # до этой версии корпус без флагов attr считается through_hole
_V_THERMAL_BRIDGE = 20211014  # по эту версию (KiCad 6) ширина спицы — thermal_width
_V_KNOCKOUT = 20220308       # knockout у текстов
_V_EMBEDDED = 20240706       # embedded_fonts / embedded_files
_V_NULLABLE = 20240201       # до этой версии включительно 0 у зазоров/масок = «наследовать»
_V_GROUP_UUID = 20231231     # (uuid …) вместо (id …) у групп
_V_JUMPERS = 20250324        # duplicate_pad_numbers_are_jumpers (KiCad 10)
_V_LEGACY_NET_TIES = 20220815  # LEGACY_NET_TIES: по эту версию net tie задавался через tags
# Первые версии формата, в которых появилась конструкция (история SEXPR_BOARD_FILE_VERSION в
# pcb_io_kicad_sexpr.h, format-tokens.md §3.1, §13). Файл объявляет версию, и KiCad этой
# версии обязан его прочитать, поэтому setters не пишут то, чего версия файла не знает
# (ValueError с предложением выполнить Footprint.upgrade()). У корня module версия — 0.
_V_PINFUNCTION = 20191123     # pinfunction у площадок
_V_PAD_PROPERTY = 20200104    # (property pad_prop_…) у площадок
_V_FP_RECT = 20200614         # fp_rect
_V_FP_PROPERTY = 20200808     # (property "ключ" "значение") у корпуса
_V_REMOVE_UNUSED = 20200809   # remove_unused_layers / keep_end_layers у площадок
_V_FILL = 20201114            # явная заливка фигур (fill …)
# module -> footprint (20201115). Флаги, которых нет у KiCad 5.1 (writer/parser 5.1.12), но
# точная версия появления в истории SEXPR_BOARD_FILE_VERSION не указана (hide у 3D-модели,
# locked у фигур): их нет только в корне module.
_V_FOOTPRINT_ROOT = 20201115
_V_PAD_LOCKED = 20210108      # locked у площадок («Pad locking moved from footprint to pads»)
_V_PINTYPE = 20210126         # pintype у площадок
_V_OPACITY = 20210824         # opacity у 3D-модели
_V_TEXT_LOCKED = 20210925     # locked у fp_text («Locked flag for fp_text»)
_V_THERMAL_ANGLE = 20211227   # thermal_bridge_angle у площадок
_V_MISSING_COURTYARD = 20211226  # attr allow_missing_courtyard (разработка 7.0; в 6.0 нет)
_V_SOLDERMASK_BRIDGES = 20211228  # attr allow_soldermask_bridges
_V_PRIVATE_LAYERS = 20211231  # private_layers
_V_FONTS = 20211232           # (font (face "…")) — шрифты TrueType
_V_NET_TIE_GROUPS = 20220818  # net_tie_pad_groups
_V_DNP = 20230410             # attr dnp
# sheetname/sheetfile корпуса: парсер 7.0 (20221018) их не знает (нет T_sheetname), 8.0 —
# знает; точная версия разработки 8.0 не указана, берётся первая после 7.0.
_V_SHEET = 20221019
# Скрытый fp_text user пишется скрытым полем с версии полей (20230620, KiCad 8): KiCad 9
# скрытых fp_text не поддерживает (парсер превращает их в поле, а 9.0.1 — теряет, в том
# числе в файлах формата KiCad 8), а скрытое поле читают и KiCad 8, и KiCad 9.
_V_HIDDEN_FIELD = V_FIELDS
_V_EXCLUDE_FROM_SIM = 20260828  # attr exclude_from_sim (master)

#: Минимальная версия формата для флагов ``(attr …)``; ``smd`` и ``virtual`` понимает и
#: KiCad 5 (``module``), остальные флаги появились в 20200826 и позже.
_ATTR_MIN_VERSION: dict[str, int] = {
    "smd": 0, "virtual": 0,
    "through_hole": _V_ATTR_FLAGS, "board_only": _V_ATTR_FLAGS,
    "exclude_from_pos_files": _V_ATTR_FLAGS, "exclude_from_bom": _V_ATTR_FLAGS,
    "allow_missing_courtyard": _V_MISSING_COURTYARD,
    "allow_soldermask_bridges": _V_SOLDERMASK_BRIDGES,
    "dnp": _V_DNP, "exclude_from_sim": _V_EXCLUDE_FROM_SIM,
}

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


def _kicad_release(version: int) -> str:
    """Выпуск KiCad, который первым пишет формат версии ``version`` (для сообщений)."""
    for limit, name in ((20211014, "6.0"), (20221018, "7.0"), (20240108, "8.0"),
                        (20241229, "9.0")):
        if version <= limit:
            return name
    return "10 (master)"


def _require_version(profile: FormatProfile, need: int, what: str) -> None:
    """``ValueError``, если формат профиля старше ``need`` (конструкции ``what`` в нём нет:
    KiCad версии файла не смог бы его прочитать)."""
    if profile.version >= need:
        return
    have = ("KiCad 5 (module)" if profile.root == "module" or profile.version == 0
            else f"версии {profile.version}")
    raise ValueError(f"{what}: нет в формате {have}; нужна версия не ниже {need} "
                     f"(KiCad {_kicad_release(need)}) — выполните Footprint.upgrade()")


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


# Ключевые слова, которые парсер KiCad 6+ (``parsePCB_TEXT``) проверяет на месте текста
# ``fp_text`` перед чтением значения: голый ``locked`` там — устаревший флаг блокировки, после
# которого текст считается отсутствующим («Expecting text value» → «Unable to load library»).
_TEXT_VALUE_KEYWORDS = frozenset({"locked"})


def _text_value_atom(s: str, profile: FormatProfile) -> Atom:
    """Текст ``fp_text`` по профилю: как :func:`_str_atom`, но в KiCad 5 (``module``) строка,
    совпадающая с ключевым словом, которое парсер KiCad проверяет на этом месте (``locked``),
    всегда пишется в кавычках — KiCad 5 читает оба вида, а KiCad 6–9 голый ``locked``
    принимает за флаг и файл не читает."""
    if profile.root == "module" and s in _TEXT_VALUE_KEYWORDS:
        return Str(s)
    return _str_atom(s, profile)


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
    """Записать координаты в первые два атома узла (остальные атомы сохраняются).

    Атом, значение которого не меняется (с точностью до нанометра), остаётся прежним —
    с исходным текстом числа (``1.0`` в файле KiCad 5 не превращается в ``1``)."""
    for i in (0, 1):
        new = _len(p[i])
        old = _num(node.atom(i))
        if old is not None and format_number(old) == new:
            continue
        node.set_atom(i, new)


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


def _insert_node(parent: Node, child: Node, order: Sequence[str]) -> None:
    """``Node.insert`` по таблице порядка с учётом голых флагов: :meth:`Node.insert`
    сравнивает только подузлы, поэтому новый узел мог бы встать перед флагом с меньшим
    рангом (``(layer …) (effects …) hide`` вместо ``(layer …) hide (effects …)``); здесь узел
    переносится за такие флаги."""
    parent.insert(child, order=order)
    rank = {n: i for i, n in enumerate(order)}
    my = rank.get(child.name)
    if my is None:
        return
    i = parent.index(child)
    pos_atoms = positional_atoms(parent)
    j = i + 1
    while j < len(parent.items):
        x = parent.items[j]
        if isinstance(x, Sym) and j not in pos_atoms and rank.get(str(x), my) < my:
            j += 1
            continue
        break
    if j > i + 1:
        del parent.items[i]
        parent.items.insert(j - 1, child)


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


# --- стек площадки (padstack, KiCad 9+) при переносе на другую сторону --------------------------
# Свойства меди одного слоя в записи (layer "…" …) стека (порядок writer'а KiCad 9,
# PCB_IO_KICAD_SEXPR::format(PAD) → formatPadLayer).
_PS_ENTRY_ORDER: tuple[str, ...] = (
    "shape", "size", "rect_delta", "offset", "roundrect_rratio", "chamfer_ratio", "chamfer",
    "options", "primitives", "thermal_bridge_angle", "thermal_gap", "thermal_bridge_width",
    "clearance", "zone_connect",
)
# не наследуются от передней стороны: парсер сбрасывает их в 0 у каждой записи слоя
_PS_RESET = frozenset(("offset", "rect_delta"))
# не переставляются: угол спиц термобарьера из записи слоя парсер KiCad 9 относит к передней
# стороне (SetThermalSpokeAngle без слоя), и по-слойного смысла у токена при чтении нет —
# узлы остаются на своих местах (так двойной перенос возвращает исходное дерево)
_PS_FIXED = frozenset(("thermal_bridge_angle",))
_CHAMFER_MIRROR_X = {"top_left": "top_right", "top_right": "top_left",
                     "bottom_left": "bottom_right", "bottom_right": "bottom_left"}


_PS_CORNER = ("roundrect_rratio", "chamfer_ratio", "chamfer")


def _ps_is_zero(n: Node) -> bool:
    """Нулевые ``(offset 0 0)``/``(rect_delta 0 0)`` — то же, что отсутствие токена."""
    return all(is_number(str(a)) and float(str(a)) == 0 for a in n.atoms())


def _ps_front_props(pad: Node) -> dict[str, Node]:
    """Свойства меди передней стороны (верхний уровень площадки) в форме записи стека."""
    out: dict[str, Node] = {}
    shape = pad.atom(2)
    if shape is not None:
        out["shape"] = Node("shape", [Sym(str(shape))])
    drill = pad.find("drill")
    off = None if drill is None else drill.find("offset")
    if off is not None and not _ps_is_zero(off):
        out["offset"] = off.copy()
    for name in _PS_ENTRY_ORDER:
        if name in ("shape", "offset") or name in _PS_FIXED:
            continue
        n = pad.find(name)
        if n is None and name == "thermal_bridge_width":
            n = pad.find("thermal_width")
        if name == "options":
            # по слоям хранится только якорь; (clearance outline|convexhull) — у площадки
            anchor = None if n is None else n.find("anchor")
            n = None if anchor is None else Node("options", [anchor.copy()])
        if n is not None and not (name in _PS_RESET and _ps_is_zero(n)):
            c = n.copy()
            c.name = name
            out[name] = c
    return out


def _ps_effective(front: dict[str, Node], entry: Node | None) -> dict[str, Node]:
    """Действующие свойства слоя стека так, как их собирает парсер KiCad 9 (``parsePadstack``).

    ``SetMode`` копирует в слои свойства передней стороны целиком (слой без записи — её
    полная копия); запись ``(layer …)`` сбрасывает ``offset``/``rect_delta`` и заменяет
    перечисленные в ней свойства. Скругление/фаска: форма записи задаёт вид заново
    (``(shape roundrect)`` без токенов фаски — не фаска, даже если у передней стороны
    фаска есть), значения ``roundrect_rratio``, ``chamfer_ratio`` и углы фаски, не
    указанные в записи, наследуются от передней стороны (умолчания KiCad — 0.25, 0.2, нет
    углов)."""
    if entry is None:
        return {k: v.copy() for k, v in front.items()}
    own = {n.name: n for n in entry.nodes()
           if n.name in _PS_ENTRY_ORDER and n.name not in _PS_FIXED}
    if "options" in own:
        anchor = own["options"].find("anchor")
        if anchor is None:
            del own["options"]
        else:
            own["options"] = Node("options", [anchor.copy()])
    out = {k: v.copy() for k, v in front.items() if k not in _PS_RESET and k not in _PS_CORNER}
    for name, n in own.items():
        if name in _PS_CORNER or (name in _PS_RESET and _ps_is_zero(n)):
            continue
        out[name] = n.copy()
    if "shape" not in own:
        corners = {k: front[k] for k in _PS_CORNER if k in front}
        corners.update({k: own[k] for k in _PS_CORNER if k in own})
    else:
        corners = {}
        rr = own.get("roundrect_rratio") or front.get("roundrect_rratio")
        if rr is not None:
            corners["roundrect_rratio"] = rr
        if "chamfer_ratio" in own or "chamfer" in own:
            corners["chamfer_ratio"] = (own.get("chamfer_ratio") or front.get("chamfer_ratio")
                                        or Node("chamfer_ratio", [_dbl(0.2)]))
            corners["chamfer"] = (own.get("chamfer") or front.get("chamfer")
                                  or Node("chamfer", []))
    out.update({k: v.copy() for k, v in corners.items()})
    return out


def _ps_mirror_x(props: dict[str, Node], profile: FormatProfile) -> None:
    """Отразить свойства слоя по X (как ``PAD::Flip`` для каждого слоя стека): смещение
    формы и дельта трапеции по X, фаски слева <-> справа, примитивы."""
    for name in ("offset", "rect_delta"):
        n = props.get(name)
        if n is None:
            continue
        a = n.atom(0)
        if a is not None and is_number(str(a)) and float(str(a)) != 0:
            n.set_atom(0, _len(-float(str(a))))
    ch = props.get("chamfer")
    if ch is not None:
        corners = [str(a) for a in ch.atoms()]
        new = sorted({_CHAMFER_MIRROR_X.get(c, c) for c in corners},
                     key=lambda c: CHAMFER_CORNERS.index(c) if c in CHAMFER_CORNERS else 99)
        if new != corners:
            ch.items = [Sym(c) for c in new]  # type: ignore[assignment]
    prims = props.get("primitives")
    if prims is not None:
        for g in prims.nodes():
            cls = _GRAPHIC_CLASSES.get(g.name)
            if cls is not None:
                cls(g, profile).mirror("x", 0.0)


def _ps_same(a: Node | None, b: Node | None) -> bool:
    """Совпадают ли два необязательных узла (по компактной записи)."""
    if a is None or b is None:
        return a is b
    return to_compact(a) == to_compact(b)


def _ps_shape_name(props: dict[str, Node]) -> str:
    n = props.get("shape")
    a = None if n is None else n.atom(0)
    return "" if a is None else str(a)


def _ps_set_front(pad: Node, props: dict[str, Node]) -> None:
    """Записать свойства передней стороны на верхний уровень площадки. Токены скругления и
    фаски — только у формы ``roundrect`` (у прочих форм KiCad их не пишет, а
    ``chamfer_ratio`` > 0 при чтении превратил бы площадку в прямоугольник с фаской)."""
    shape = _ps_shape_name(props)
    if shape:
        pad.set_atom(2, Sym(shape))
    for name in _PS_ENTRY_ORDER:
        if name in ("shape", "offset") or name in _PS_FIXED:
            continue
        new = props.get(name)
        if name in _PS_CORNER and shape != "roundrect":
            new = None
        if name == "primitives" and shape != "custom":
            new = None
        if name == "options":
            _ps_set_anchor(pad, new)
            continue
        cur = pad.find(name)
        if name == "thermal_bridge_width" and cur is None:
            cur = pad.find("thermal_width")
        if cur is None and new is None:
            continue
        if cur is not None and new is not None and \
                to_compact(Node(new.name, cur.items)) == to_compact(new):
            continue
        if cur is not None:
            pad.remove_child(cur)
        if new is not None:
            pad.insert(new.copy(), order=PAD_ORDER)
    # смещение формы хранится в (drill … (offset x y))
    new_off = props.get("offset")
    drill = pad.find("drill")
    cur_off = None if drill is None else drill.find("offset")
    if _ps_same(cur_off, new_off):
        return
    if drill is not None and cur_off is not None:
        drill.remove_child(cur_off)
    if new_off is not None:
        if drill is None:
            drill = Node("drill", [])
            pad.insert(drill, order=PAD_ORDER)
        drill.append(new_off.copy())
    elif drill is not None and not drill.items:
        pad.remove_child(drill)


def _ps_set_anchor(pad: Node, options: Node | None) -> None:
    """Якорь custom-площадки ``(options … (anchor …))`` верхнего уровня; прочие узлы
    ``options`` (``clearance``) относятся ко всей площадке и не меняются."""
    new = None if options is None else options.find("anchor")
    opts = pad.find("options")
    cur = None if opts is None else opts.find("anchor")
    if _ps_same(cur, new):
        return
    if opts is not None and cur is not None:
        if new is None:
            opts.remove_child(cur)
        else:
            opts.replace_child(cur, new.copy())
    elif new is not None:
        if opts is None:
            pad.insert(Node("options", [new.copy()]), order=PAD_ORDER)
        else:
            opts.append(new.copy())


def _ps_write_entry(entry: Node, props: dict[str, Node], front: dict[str, Node]) -> None:
    """Переписать известные свойства записи слоя стека: форма и размер — всегда (как
    writer KiCad), смещение и дельта — если есть (и явным нулём, если они есть только у
    передней стороны), скругление и фаска — у формы ``roundrect`` всегда (вид фаски не
    наследуется), якорь и примитивы — у ``custom`` всегда (как writer KiCad), прочие — если отличаются от передней стороны (иначе парсер унаследует их
    от неё). Неизвестные узлы записи остаются."""
    known = [x for x in entry.items if isinstance(x, Node) and x.name in _PS_ENTRY_ORDER
             and x.name not in _PS_FIXED]
    for x in known:
        entry.remove_child(x)
    shape = _ps_shape_name(props)
    for name in _PS_ENTRY_ORDER:
        if name in _PS_FIXED:
            continue
        n = props.get(name)
        if n is None:
            if name in _PS_RESET and front.get(name) is not None:
                # явный ноль: kicad-cli 9.0.1 не сбрасывает offset/rect_delta записи слоя
                # и унаследовал бы их от передней стороны (сброс появился позже в 9.0.x)
                entry.insert(Node(name, [_len(0.0), _len(0.0)]), order=_PS_ENTRY_ORDER)
            continue
        if name in _PS_CORNER:
            if shape == "roundrect":
                entry.insert(n.copy(), order=_PS_ENTRY_ORDER)
            continue
        if name in ("options", "primitives"):
            # как writer KiCad: только у custom (у прочих форм они не действуют)
            if shape == "custom":
                entry.insert(n.copy(), order=_PS_ENTRY_ORDER)
            continue
        if name in ("shape", "size") or name in _PS_RESET or not _ps_same(n, front.get(name)):
            entry.insert(n.copy(), order=_PS_ENTRY_ORDER)


def _ps_layer_names(mode: str) -> list[str]:
    """Слои записей стека в порядке writer'а: ``Inner``, ``B.Cu`` (front_inner_back) или
    ``In1.Cu`` … ``In30.Cu``, ``B.Cu`` (custom, библиотека — 32 медных слоя)."""
    if mode == "front_inner_back":
        return ["Inner", "B.Cu"]
    return [f"In{k}.Cu" for k in range(1, 31)] + ["B.Cu"]


def _flip_padstack(pad: Node, profile: FormatProfile) -> None:
    """Перенос стека площадки на другую сторону (``PADSTACK::FlipLayers`` + зеркалирование
    слоёв в ``PAD::Flip`` KiCad 9).

    ``front_inner_back``: свойства меди передней стороны (верхний уровень площадки) и
    записи ``(layer "B.Cu" …)`` меняются местами; ``custom``: ещё и внутренние слои
    ``In(k)`` <-> ``In(31-k)`` — сопряжение по 32 медным слоям, как у KiCad вне платы
    (``BOARD_ITEM::BoardCopperLayerCount()`` без платы — 32; в библиотеке файл хранит все
    30 внутренних слоёв). На каждом слое отражаются смещение формы и дельта трапеции по
    X, фаски и примитивы. Сторона маски (``tenting``) меняется в :meth:`Pad._flip_x`.
    Узлы ``thermal_bridge_angle`` остаются на месте (см. ``_PS_FIXED``). Действующие
    свойства записи слоя — как у парсера KiCad 9.0.x после исправления (``offset`` и
    ``rect_delta``, не указанные в записи, равны 0; kicad-cli 9.0.1 наследовал их от
    передней стороны), поэтому нулевое смещение там, где у передней стороны оно есть,
    пишется явно ``(offset 0 0)`` — файл читается одинаково обеими версиями.
    Свойство, которое есть у новой задней стороны, но не у новой передней, в файле не
    выразить (запись слоя без токена наследует его от передней стороны) — так же
    поступает и writer KiCad."""
    ps = pad.find("padstack")
    if ps is None:
        return
    mode = str(ps.value("mode") or "")
    if mode not in ("front_inner_back", "custom"):
        return
    front = _ps_front_props(pad)
    names = _ps_layer_names(mode)
    entries: dict[str, Node] = {}
    for n in ps.nodes("layer"):
        a = n.atom(0)
        if a is not None and str(a) in names and str(a) not in entries:
            entries[str(a)] = n
    eff = {name: _ps_effective(front, entries.get(name)) for name in names}
    eff["F.Cu"] = {k: v.copy() for k, v in front.items()}
    perm = {"F.Cu": "B.Cu", "B.Cu": "F.Cu"}
    if mode == "custom":
        for k in range(1, 31):
            perm[f"In{k}.Cu"] = f"In{31 - k}.Cu"
    new = {name: eff[perm.get(name, name)] for name in eff}
    for props in new.values():
        _ps_mirror_x(props, profile)
    new_front = new["F.Cu"]
    _ps_set_front(pad, new_front)
    for name in names:
        entry = entries.get(name)
        props = new[name]
        if entry is None:
            # запись отсутствовала: слой был полной копией передней стороны
            if all(_ps_same(props.get(k), new_front.get(k)) for k in _PS_ENTRY_ORDER
                   if k not in _PS_FIXED):
                continue
            entry = Node("layer", [Str(name)])
            later = [n for n in ps.nodes("layer") if n.atom(0) is not None
                     and str(n.atom(0)) in names
                     and names.index(str(n.atom(0))) > names.index(name)]
            if later:
                ps.items.insert(ps.index(later[0]), entry)
            else:
                ps.append(entry)
        _ps_write_entry(entry, props, new_front)


def _flip_tenting(pad: Node) -> None:
    """``(tenting front|back …)`` — сторона маски меняется (``std::swap(m_frontMaskProps,
    m_backMaskProps)`` в ``PADSTACK::FlipLayers``); ``none`` и ``front back`` не меняются."""
    t = pad.find("tenting")
    if t is None:
        return
    atoms = [str(a) for a in t.atoms()]
    swapped = {"front": "back", "back": "front"}
    new = [swapped.get(a, a) for a in atoms]
    side = [a for a in ("front", "back") if a in new]
    rest = [a for a in new if a not in ("front", "back")]
    new = side + rest
    if new != atoms:
        t.items = [Sym(a) for a in new] + [x for x in t.items if isinstance(x, Node)]  # type: ignore[assignment]


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


def _same_point_nm(a: Point, b: Point, tol_nm: int = 1) -> bool:
    """Совпадают ли точки с точностью ``tol_nm`` нанометров (в целых нм, как KiCad)."""
    (ax, ay), (bx, by) = _to_nm(a), _to_nm(b)
    return abs(ax - bx) <= tol_nm and abs(ay - by) <= tol_nm


def _true_arc_mid(s: Point, m: Point, e: Point) -> Point:
    """Истинная середина дуги, проходящей через ``s``, ``m``, ``e`` (от ``s`` к ``e`` через
    ``m``), — то, что пишет writer KiCad (``EDA_SHAPE::GetArcMid``).

    KiCad 6+ читает ``(mid …)`` лишь как подсказку стороны: ``EDA_SHAPE::SetArcGeometry``
    вычисляет центр по трём точкам, затем свою середину дуги от начала к концу и, если она
    дальше от ``mid``, чем от центра, меняет начало и конец местами (common/eda_shape.cpp).
    Поэтому ``mid``, заметно отстоящая от середины большой дуги (например, в 20° от начала
    дуги в 300°), читается KiCad как дополнительная дуга (60°). Середина, совпадающая с
    ``m`` до 1 нм, и вырожденная (коллинеарная) дуга — ``m`` без изменений."""
    g = _geo.arc_from_three_points(s, m, e)
    if g is None:
        return m
    t = _geo.point_at_angle(g.center, g.radius, g.start_angle + g.sweep / 2.0)
    return m if _same_point_nm(m, t) else t


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
    """Записать дугу в старой форме KiCad 5: ``(start ЦЕНТР) (end НАЧАЛО) (angle A)``.

    Дуга с углом ``sweep < 0`` (так KiCad хранит все дуги) кодируется двумя равноценными
    способами: ``(ЦЕНТР, start, -sweep)`` и ``(ЦЕНТР, end, sweep)``; выбирается тот, у
    которого знак угла совпадает с имеющимся в узле, — тогда при неизменной геометрии
    токены не меняются."""
    an = node.find("angle")
    old_a = _num(an.atom(0)) if an is not None else None
    g = _geo.arc_from_three_points(s, m, e)
    if g is not None and old_a is not None and old_a < 0 and g.sweep < 0:
        c, sp, a = g.center, e, g.sweep
    else:
        c, sp, a = _three_to_legacy(s, m, e)
    radius = g.radius if g is not None else _geo.distance(s, e) / 2.0
    node.remove("mid")
    st = node.find("start")
    if st is None:
        node.items.insert(0, Node("start", [_len(c[0]), _len(c[1])]))
        st = node.find("start")
    else:
        old_c = _xy_of(st)
        # центр, совпадающий с прежним до нанометра, не переписывается (иначе округление
        # пересчёта сдвигает его на 1 нм без изменения геометрии)
        if old_c is None or not _same_point_nm(old_c, c):
            _set_xy(st, c)
    en = node.find("end")
    if en is None:
        en = Node("end", [_len(sp[0]), _len(sp[1])])
        node.items.insert(node.index(st) + 1, en)
    else:
        old_sp = _xy_of(en)
        if old_sp is None or not _same_point_nm(old_sp, sp):
            _set_xy(en, sp)
    # угол — по фактически записанным центру и началу (центр мог остаться прежним, числа
    # округлены до нм): конец дуги попадает в заданную точку, а не в точку окружности,
    # проведённой через округлённую середину
    ep = s if sp is e else e
    cw, spw = _xy_of(st), _xy_of(en)
    if cw is not None and spw is not None and g is not None:
        phi = (_eda_angle_of(ep[0] - cw[0], ep[1] - cw[1])
               - _eda_angle_of(spw[0] - cw[0], spw[1] - cw[1]))
        d = (phi - a + 180.0) % 360.0 - 180.0
        if abs(d) < 1.0:
            a += d
    an = node.find("angle")
    if an is None:
        node.items.insert(node.index(en) + 1, Node("angle", [_ang(a)]))
    else:
        old = _num(an.atom(0))
        # угол, отличающийся так мало, что конец дуги смещается не больше чем на 1 нм,
        # сохраняется с исходным текстом (135 не превращается в 134.999978)
        if old is None or (format_angle(old) != format_angle(a)
                           and abs(math.radians(old - a)) * radius > 1e-6):
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


def _is_null_override(value: float, kind: str) -> bool:
    """Значение, которое парсер KiCad для файлов версии <= 20240201 считает «не задано»:
    ноль после чтения (длина — в целых нанометрах, ``parseBoardUnits``; коэффициент —
    точно, ``parseDouble``)."""
    if kind == "len":
        return _kiround(value * 1e6) == 0
    return value == 0


def _nullable(view: View) -> bool:
    """Действует ли для версии файла правило «0 у зазоров/масок — наследовать»
    (``m_requiredVersion <= 20240201`` в парсере KiCad 9; KiCad 5–8 хранили эти значения
    целыми, 0 = не задано)."""
    return view.profile.version <= _V_NULLABLE


def _get_override(view: View, tokens: Sequence[str], kind: str) -> float | None:
    """Значение локального переопределения (первый найденный из ``tokens``) с учётом
    правила nullable: в файле версии <= 20240201 ноль — ``None``."""
    for token in tokens:
        v = view.node.number(token)
        if v is not None:
            if _nullable(view) and _is_null_override(v, kind):
                return None
            return v
    return None


def _set_override(view: View, tokens: Sequence[str], value: Any, kind: str,
                  new_token: str, what: str) -> None:
    """Записать локальное переопределение (``clearance``/``solder_*``).

    Существующий токен (любой из ``tokens``) сохраняет имя, новый — ``new_token``;
    ``None`` удаляет. В файле версии <= 20240201 значение 0 означает для KiCad «не задано»
    (writer KiCad 5–8 ноль не пишет, парсер KiCad 9 читает его как отсутствие), поэтому
    присваивание 0 удаляет токен, а если переопределения и так нет (токена нет или он
    равен 0) — ``None``/0 ничего не меняют (узел остаётся как был)."""
    fmt = _len if kind == "len" else _dbl
    v = None if value is None else _check_real(value, what)
    if _nullable(view) and (v is None or _is_null_override(v, kind)):
        if _get_override(view, tokens, kind) is None:
            return
        for token in tokens:
            view.node.remove(token)
        return
    if v is None:
        for token in tokens:
            view.node.remove(token)
        return
    for token in tokens:
        if view.node.find(token) is not None:
            if view.node.number(token) != v:     # то же значение — исходный текст числа цел
                view.node.set(token, fmt(v), order=view._order())
            return
    view.node.set(new_token, fmt(v), order=view._order())


_FP_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("solder_mask_margin", "len"), ("solder_paste_margin", "len"),
    ("solder_paste_ratio", "dbl"), ("solder_paste_margin_ratio", "dbl"), ("clearance", "len"),
)
_PAD_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("solder_mask_margin", "len"), ("solder_paste_margin", "len"),
    ("solder_paste_margin_ratio", "dbl"), ("clearance", "len"),
)


def _drop_null_overrides(node: Node, tokens: Sequence[tuple[str, str]]) -> None:
    """Удалить нулевые переопределения (для файла версии <= 20240201 они значат «не
    задано»; так их отбрасывает KiCad при пересохранении)."""
    for token, kind in tokens:
        for child in node.nodes(token):
            v = _num(child.atom(0))
            if v is not None and _is_null_override(v, kind):
                node.remove_child(child)


def _override_prop(token: str, kind: str, doc: str) -> builtins.property:
    """Свойство локального переопределения ``(token v)`` площадки/корпуса с правилом
    nullable (:func:`_set_override`): в файле версии <= 20240201 ноль — ``None``."""

    def fget(self: View) -> float | None:
        return _get_override(self, (token,), kind)

    def fset(self: View, value: Any) -> None:
        _set_override(self, (token,), value, kind, token, token)

    return builtins.property(fget, fset, doc=doc)


_NULLABLE_DOC = (" В файле версии <= 20240201 (KiCad 5–8) ноль означает «не задано» "
                 "(наследовать): getter возвращает ``None``, присваивание 0 удаляет токен.")


def _str_prop(token: str, doc: str, need: int = 0) -> builtins.property:
    """Свойство для необязательного строкового токена ``(token "v")`` (всегда в кавычках).

    ``need`` — первая версия формата с этим токеном: запись **нового** токена в файл более
    старой версии — ``ValueError`` (:func:`_require_version`); уже имеющийся меняется."""

    def fget(self: View) -> str | None:
        v = self.node.value(token)
        return None if v is None else str(v)

    def fset(self: View, value: Any) -> None:
        if need and value is not None and self.node.find(token) is None:
            _check_str(value, token)
            _require_version(self.profile, need, token)
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


# ---------------------------------------------------------------------------
# Pad
# ---------------------------------------------------------------------------

def _check_enum(value: Any, allowed: Sequence[str], what: str) -> str:
    """Проверить значение перечисления (строка из ``allowed``)."""
    if not isinstance(value, str):
        raise TypeError(f"{what}: ожидается строка, получено {type(value).__name__}")
    if value not in allowed:
        raise ValueError(f"{what}: недопустимое значение {value!r} (допустимо: {', '.join(allowed)})")
    return value


def _writer_layer_order(names: Sequence[str], profile: FormatProfile) -> list[str]:
    """Слои в порядке, в котором их перечисляет writer KiCad версии профиля: групповые
    обозначения первыми (в заданном порядке), затем отдельные слои по возрастанию
    ``PCB_LAYER_ID`` своей версии (KiCad 9+: ``F.Cu F.Mask F.Paste``, раньше —
    ``F.Cu F.Paste F.Mask``)."""
    wild = [n for n in names if _L.is_wildcard(n)]
    single = [n for n in names if not _L.is_wildcard(n)]
    kicad = 9 if profile.version >= V_FILL_YESNO else 8
    return wild + _L.sort_layers(single, kicad=kicad)


def _round_bbox(b: BBox) -> BBox:
    """Габариты, округлённые до нанометров (убирает «шум» тригонометрии)."""
    return BBox(_geo.round_mm(b.x1), _geo.round_mm(b.y1), _geo.round_mm(b.x2), _geo.round_mm(b.y2))


def _bbox_union(boxes: Iterable[BBox | None]) -> BBox | None:
    """Объединение габаритов (``None`` пропускаются); ``None``, если нечего объединять."""
    out: BBox | None = None
    for b in boxes:
        if b is None:
            continue
        out = b if out is None else out.union(b)
    return out


def _set_coord_atom(parent: Node, name: str, index: int, value: float,
                    order: Sequence[str] | None, default: Sequence[float] = (0.0, 0.0)) -> None:
    """Заменить один координатный атом ``index`` дочернего узла ``(name x y …)``; если узла
    нет — создать его со значениями ``default`` (с подстановкой нового значения)."""
    child = parent.find(name)
    if child is None:
        vals = list(default)
        vals[index] = value
        parent.set(name, *[_len(v) for v in vals], order=order)
    else:
        child.set_atom(index, _len(value))


class Pad(View):
    """Площадка: узел ``(pad НОМЕР ТИП ФОРМА [locked] (at …) (size …) …)``.

    Номер — строка (``"1"``, ``"A1"``, ``""`` у монтажных отверстий): в KiCad 6+ пишется в
    кавычках, в KiCad 5 (``module``) — голым символом, если кавычки не нужны. Тип и форма —
    голые символы из :data:`PAD_TYPES` / :data:`PAD_SHAPES`.

    Положение ``(at x y [угол])`` — относительно начала координат корпуса; нулевой угол KiCad
    не пишет (во всех версиях), поэтому присваивание ``angle = 0`` удаляет атом угла.
    Отверстие — :class:`Drill`; ``drill`` принимает ``None`` (удалить), число (круглое),
    пару ``(w, h)`` (овальное) или :class:`Drill` (копия узла).
    """

    __slots__ = ()

    def _order(self) -> Sequence[str]:
        return PAD_ORDER

    # --- создание ------------------------------------------------------------------
    @classmethod
    def new(cls, number: str | int = "", type: str = "thru_hole", shape: str = "circle",
            x: float = 0.0, y: float = 0.0, size: float | tuple[float, float] = (1.6, 1.6), *,
            drill: float | tuple[float, float] | Drill | None = None,
            layers: Iterable[str] | str | None = None, angle: float = 0.0,
            profile: FormatProfile | None = None, uuid: bool | str | None = True,
            **kw: Any) -> Pad:
        """Новая площадка в форме профиля (по умолчанию — KiCad 9).

        ``size`` — число (квадрат/круг) или ``(sx, sy)``; ``drill`` — см. :attr:`drill`
        (``None`` — без отверстия, в том числе у ``thru_hole``: проверку делает
        ``validate``); ``layers=None`` — пресет по типу (:data:`kicadfp.layers.PAD_LAYER_PRESETS`)
        в порядке writer'а версии профиля. Как и writer KiCad 8+, у ``thru_hole`` пишется
        ``(remove_unused_layers no)``; у ``roundrect`` без явного ``roundrect_rratio`` —
        ``0.25`` (умолчание KiCad). ``uuid``: ``True`` — новый ``uuid4``, строка — это значение,
        ``False``/``None`` — без идентификатора. Прочие ключевые аргументы — имена
        записываемых свойств (``roundrect_rratio=0.2``, ``chamfer=["top_left"]``,
        ``solder_mask_margin=0.05``, ``property="pad_prop_heatsink"``, ``anchor="circle"`` …).
        """
        prof = profile or _default_profile()
        t = _check_enum(type, PAD_TYPES, "type")
        s = _check_enum(shape, PAD_SHAPES, "shape")
        if isinstance(number, bool) or not isinstance(number, (str, int)):
            raise TypeError("number: ожидается строка или целое число")
        num = str(number)
        node = Node("pad", [_str_atom(num, prof), Sym(t), Sym(s)])
        view = cls(node, prof)
        px, py = _check_real(x, "x"), _check_real(y, "y")
        a = _check_real(angle, "angle")
        node.append(Node("at", [_len(px), _len(py)] + ([_ang(a)] if a != 0 else [])))
        sx, sy = _as_pair(size, "size")
        node.append(Node("size", [_len(sx), _len(sy)]))
        if drill is not None:
            view.drill = drill
        if layers is None:
            preset = t if t in _L.PAD_LAYER_PRESETS else "thru_hole"
            view.layers = _writer_layer_order(_L.PAD_LAYER_PRESETS[preset], prof)
        else:
            view.layers = layers
        if t == "thru_hole" and prof.bool_style == "yesno":
            node.set("remove_unused_layers", Sym("no"), order=PAD_ORDER)
        if s == "roundrect" and "roundrect_rratio" not in kw:
            view.roundrect_rratio = 0.25
        for key, val in kw.items():
            if key.startswith("_") or not isinstance(getattr(cls, key, None), builtins.property) \
                    or getattr(cls, key).fset is None:
                raise TypeError(f"Pad.new: неизвестный параметр {key!r}")
            setattr(view, key, val)
        _add_new_id(node, prof, PAD_ORDER, uuid)
        return view

    # --- заголовок -----------------------------------------------------------------
    @property
    def number(self) -> str:
        """Номер площадки (строка; ``""`` — без номера)."""
        a = self.node.atom(0)
        return "" if a is None else str(a)

    @number.setter
    def number(self, value: str | int) -> None:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise TypeError("number: ожидается строка или целое число")
        self.node.set_atom(0, _str_atom(str(value), self.profile))

    @property
    def type(self) -> str:
        """Тип: ``thru_hole`` | ``smd`` | ``connect`` | ``np_thru_hole``."""
        a = self.node.atom(1)
        return "" if a is None else str(a)

    @type.setter
    def type(self, value: str) -> None:
        self.node.set_atom(1, Sym(_check_enum(value, PAD_TYPES, "type")))

    @property
    def shape(self) -> str:
        """Форма: ``circle`` | ``rect`` | ``oval`` | ``trapezoid`` | ``roundrect`` | ``custom``.

        Присваивание меняет только атом формы (параметры вроде ``roundrect_rratio`` не
        добавляются: при их отсутствии KiCad берёт умолчания)."""
        a = self.node.atom(2)
        return "" if a is None else str(a)

    @shape.setter
    def shape(self, value: str) -> None:
        self.node.set_atom(2, Sym(_check_enum(value, PAD_SHAPES, "shape")))

    # --- положение и размер --------------------------------------------------------------
    @property
    def x(self) -> float:
        """X центра (отверстия) площадки, мм."""
        p = _xy_of(self.node.find("at"))
        return 0.0 if p is None else p[0]

    @x.setter
    def x(self, value: float) -> None:
        _set_coord_atom(self.node, "at", 0, _check_real(value, "x"), PAD_ORDER)

    @property
    def y(self) -> float:
        """Y центра площадки, мм (ось Y вниз)."""
        p = _xy_of(self.node.find("at"))
        return 0.0 if p is None else p[1]

    @y.setter
    def y(self, value: float) -> None:
        _set_coord_atom(self.node, "at", 1, _check_real(value, "y"), PAD_ORDER)

    @property
    def position(self) -> Point:
        """Положение ``(x, y)``."""
        return (self.x, self.y)

    @position.setter
    def position(self, value: Point) -> None:
        x, y = _as_point(value, "position")
        at = self.node.find("at")
        if at is None:
            self.node.set("at", _len(x), _len(y), order=PAD_ORDER)
        else:
            _set_xy(at, (x, y))

    @property
    def angle(self) -> float:
        """Угол поворота, градусы (0, если атома нет)."""
        return _at_angle(self.node.find("at"))

    @angle.setter
    def angle(self, value: float) -> None:
        a = _check_real(value, "angle")
        at = self.node.find("at")
        if at is None:
            if a == 0:
                return
            at = self.node.set("at", _len(0.0), _len(0.0), order=PAD_ORDER)
        _set_at_angle(at, a, always=False)

    @property
    def size_x(self) -> float:
        """Размер по X (ширина), мм."""
        return self.node.number("size", 0, 0.0)  # type: ignore[return-value]

    @size_x.setter
    def size_x(self, value: float) -> None:
        v = _check_real(value, "size_x")
        _set_coord_atom(self.node, "size", 0, v, PAD_ORDER, default=(v, v))

    @property
    def size_y(self) -> float:
        """Размер по Y (высота), мм."""
        return self.node.number("size", 1, 0.0)  # type: ignore[return-value]

    @size_y.setter
    def size_y(self, value: float) -> None:
        v = _check_real(value, "size_y")
        _set_coord_atom(self.node, "size", 1, v, PAD_ORDER, default=(v, v))

    @property
    def size(self) -> tuple[float, float]:
        """Размер ``(sx, sy)``; присваивание принимает число (``sx = sy``) или пару."""
        return (self.size_x, self.size_y)

    @size.setter
    def size(self, value: float | tuple[float, float]) -> None:
        sx, sy = _as_pair(value, "size")
        node = self.node.find("size")
        if node is None:
            self.node.set("size", _len(sx), _len(sy), order=PAD_ORDER)
        else:
            _set_xy(node, (sx, sy))

    # --- отверстие ---------------------------------------------------------------------
    @property
    def drill(self) -> Drill | None:
        """Отверстие (:class:`Drill`) или ``None``.

        Присваивание: ``None`` — удалить узел; число ``d`` — круглое (у существующего узла
        меняются только размеры, смещение ``offset`` сохраняется); пара ``(w, h)`` —
        овальное (``(drill oval w h)``; при ``w == h`` KiCad пишет ``(drill oval w)``);
        :class:`Drill` — копия его узла (узел площадки заменяется целиком).
        """
        n = self.node.find("drill")
        return None if n is None else Drill(n, self._profile, self._parent)

    @drill.setter
    def drill(self, value: Any) -> None:
        if value is None:
            self.node.remove("drill")
            return
        existing = self.node.find("drill")
        if isinstance(value, Drill):
            new = value.node.copy()
            if existing is None:
                self.node.insert(new, order=PAD_ORDER)
            else:
                self.node.replace_child(existing, new)
            return
        if isinstance(value, Real) and not isinstance(value, bool):
            d = _check_real(value, "drill")
            if existing is None:
                self.node.set("drill", _len(d), order=PAD_ORDER)
                return
            view = Drill(existing, self._profile, self._parent)
            view.oval = False
            view.diameter = d
            return
        w, h = _as_point(value, "drill")
        if existing is None:
            self.node.insert(Drill.new(w, h).node, order=PAD_ORDER)
            return
        view = Drill(existing, self._profile, self._parent)
        view.oval = True
        view.diameter = w
        if h == w:
            view.width = None
        else:
            view.width = h

    # --- слои ----------------------------------------------------------------------------
    @property
    def layers(self) -> list[str]:
        """Слои площадки (как записаны: с групповыми обозначениями ``*.Cu``, ``*.Mask`` …)."""
        n = self.node.find("layers")
        return [] if n is None else [str(a) for a in n.atoms()]

    @layers.setter
    def layers(self, value: Iterable[str] | str) -> None:
        names = _layer_list(value)
        prof = self.profile
        self.node.set("layers", *[_layer_atom(n, prof, in_list=True) for n in names],
                      order=PAD_ORDER)

    def set_layers(self, preset: str) -> None:
        """Слои по пресету :data:`kicadfp.layers.PAD_LAYER_PRESETS` (``"thru_hole"``,
        ``"smd"``, ``"smd_back"``, ``"connect"``, ``"connect_back"``, ``"np_thru_hole"``,
        ``"aperture"``) в порядке writer'а KiCad версии файла."""
        if preset not in _L.PAD_LAYER_PRESETS:
            raise ValueError(f"неизвестный пресет слоёв {preset!r} "
                             f"(допустимо: {', '.join(_L.PAD_LAYER_PRESETS)})")
        self.layers = _writer_layer_order(_L.PAD_LAYER_PRESETS[preset], self.profile)

    def is_tht(self) -> bool:
        """Сквозная площадка (``thru_hole`` или ``np_thru_hole``)."""
        return self.type in ("thru_hole", "np_thru_hole")

    def is_smd(self) -> bool:
        """Планарная площадка (``smd`` или ``connect`` — без отверстия)."""
        return self.type in ("smd", "connect")

    # --- параметры формы -------------------------------------------------------------------
    roundrect_rratio = _num_prop("roundrect_rratio", "dbl",
                                 "Радиус скругления ``roundrect`` как доля меньшей стороны "
                                 "(``None`` — токена нет; KiCad по умолчанию 0.25).")
    def _activate_chamfer(self) -> None:
        """Подготовить форму к фаске так, как её понимает KiCad.

        Парсер KiCad (``parsePAD``, все версии 5–9) делает площадку ``CHAMFERED_RECT``, если
        в узле есть ``(chamfer <углы>)`` или ``(chamfer_ratio > 0)``, **независимо от
        формы**, а writer пишет такую площадку как ``roundrect`` с ``(roundrect_rratio …)``.
        Поэтому ``rect`` переводится в ``roundrect`` с ``(roundrect_rratio 0)`` (без токена
        KiCad взял бы скругление 0.25); ``roundrect`` не меняется. Фаска у ``circle``,
        ``oval``, ``trapezoid``, ``custom`` KiCad превратила бы площадку в прямоугольник с
        фаской — ``ValueError``."""
        shape = self.shape
        if shape == "roundrect":
            return
        if shape != "rect":
            raise ValueError(f"фаска возможна только у площадки rect/roundrect, а не {shape!r}: "
                             "KiCad прочитал бы её как прямоугольник с фаской")
        self.node.set_atom(2, Sym("roundrect"))
        self.node.set("roundrect_rratio", _dbl(0.0), order=PAD_ORDER)

    @property
    def chamfer_ratio(self) -> float | None:
        """Размер фаски как доля меньшей стороны (``None`` — нет).

        Присваивание значения > 0 площадке ``rect`` переводит её в ``roundrect`` с
        ``(roundrect_rratio 0)`` — так KiCad хранит прямоугольник с фаской (парсер делает
        площадку с фаской ``CHAMFERED_RECT`` при любой форме); у ``circle``/``oval``/
        ``trapezoid``/``custom`` — ``ValueError``."""
        return self.node.number("chamfer_ratio")

    @chamfer_ratio.setter
    def chamfer_ratio(self, value: float | None) -> None:
        if value is not None and _check_real(value, "chamfer_ratio") > 0:
            self._activate_chamfer()
        self._set_opt("chamfer_ratio", value, _dbl)

    @property
    def chamfer(self) -> list[str]:
        """Углы с фаской: подмножество ``top_left``, ``top_right``, ``bottom_left``,
        ``bottom_right``; присваивание пишет их в порядке KiCad, пустой список удаляет
        ``(chamfer …)``. Непустой список у площадки ``rect`` переводит её в ``roundrect`` с
        ``(roundrect_rratio 0)``, у ``circle``/``oval``/``trapezoid``/``custom`` —
        ``ValueError`` (см. :attr:`chamfer_ratio`)."""
        n = self.node.find("chamfer")
        return [] if n is None else [str(a) for a in n.atoms()]

    @chamfer.setter
    def chamfer(self, value: Iterable[str] | str | None) -> None:
        if value is None:
            self.node.remove("chamfer")
            return
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        corners = set()
        for c in value:
            corners.add(_check_enum(c, CHAMFER_CORNERS, "chamfer"))
        if not corners:
            self.node.remove("chamfer")
            return
        self._activate_chamfer()
        self.node.set("chamfer", *[Sym(c) for c in CHAMFER_CORNERS if c in corners],
                      order=PAD_ORDER)

    @property
    def rect_delta(self) -> tuple[float, float] | None:
        """Дельта трапеции ``(dx, dy)`` или ``None``."""
        return _point_of(self.node, "rect_delta")

    @rect_delta.setter
    def rect_delta(self, value: tuple[float, float] | None) -> None:
        if value is None:
            self.node.remove("rect_delta")
            return
        dx, dy = _as_point(value, "rect_delta")
        _set_point(self.node, "rect_delta", (dx, dy), PAD_ORDER)

    # --- цепь и функция вывода ----------------------------------------------------------------
    @property
    def net(self) -> tuple[int, str] | None:
        """Цепь ``(номер, имя)`` или ``None`` (в библиотеках цепей нет). Форма KiCad 10
        ``(net "имя")`` без номера читается как ``(0, имя)``."""
        n = self.node.find("net")
        if n is None:
            return None
        a0, a1 = n.atom(0), n.atom(1)
        if a0 is not None and isinstance(a0, Sym) and is_number(a0):
            return (int(float(a0)), "" if a1 is None else str(a1))
        return (0, "" if a0 is None else str(a0))

    @net.setter
    def net(self, value: tuple[int, str] | None) -> None:
        if value is None:
            self.node.remove("net")
            return
        try:
            code, name = value
        except (TypeError, ValueError):
            raise TypeError("net: ожидается пара (номер, имя)") from None
        self.node.set("net", Sym(str(_check_int(code, "net"))), Str(_check_str(name, "net")),
                      order=PAD_ORDER)

    pinfunction = _str_prop("pinfunction", "Функция вывода (``None`` — нет токена; новый "
                            "токен — с версии 20191123, в KiCad 5 ``module`` — ``ValueError``).",
                            _V_PINFUNCTION)
    pintype = _str_prop("pintype", "Электрический тип вывода (``None`` — нет токена; новый "
                        "токен — с версии 20210126).", _V_PINTYPE)

    def _get_pad_property(self) -> str | None:
        v = self.node.value("property")
        return None if v is None else str(v)

    def _set_pad_property(self, value: str | None) -> None:
        if value is None:
            self.node.remove("property")
            return
        s = _check_str(value, "property", allow_empty=False)
        if not _bare_symbol_ok(s):
            raise ValueError(f"property: {s!r} не может быть голым символом")
        if self.node.find("property") is None:
            _require_version(self.profile, _V_PAD_PROPERTY, "property площадки")
        self.node.set("property", Sym(s), order=PAD_ORDER)

    # --- зазоры и термобарьеры -----------------------------------------------------------------
    clearance = _override_prop("clearance", "len", "Локальный зазор, мм (``None`` — нет "
                               "токена)." + _NULLABLE_DOC)
    solder_mask_margin = _override_prop("solder_mask_margin", "len",
                                        "Отступ маски, мм (``None`` — нет токена)." + _NULLABLE_DOC)
    solder_paste_margin = _override_prop("solder_paste_margin", "len",
                                         "Отступ пасты, мм (``None`` — нет токена)." + _NULLABLE_DOC)
    solder_paste_ratio = _override_prop("solder_paste_margin_ratio", "dbl",
                                        "Коэффициент пасты ``(solder_paste_margin_ratio …)`` "
                                        "(у площадки — во всех версиях этот токен)."
                                        + _NULLABLE_DOC)
    zone_connect = _num_prop("zone_connect", "int",
                             "Подключение к зонам: 0 нет, 1 термо, 2 сплошное, 3 термо только THT.")
    thermal_gap = _num_prop("thermal_gap", "len", "Зазор термобарьера, мм.")
    @property
    def thermal_bridge_angle(self) -> float | None:
        """Угол спиц термобарьера (``None`` — нет токена). Токен есть с формата 20211227
        (KiCad 7); в файле KiCad 5/6 присваивание числа — ``ValueError``."""
        return self.node.number("thermal_bridge_angle")

    @thermal_bridge_angle.setter
    def thermal_bridge_angle(self, value: float | None) -> None:
        if value is not None and self.node.find("thermal_bridge_angle") is None:
            _require_version(self.profile, _V_THERMAL_ANGLE, "thermal_bridge_angle")
        self._set_opt("thermal_bridge_angle", value, _ang)
    die_length = _num_prop("die_length", "len", "Длина проводника в корпусе, мм.")

    @property
    def thermal_bridge_width(self) -> float | None:
        """Ширина спиц термобарьера: ``(thermal_bridge_width …)`` (KiCad 7+) или устаревшее
        ``(thermal_width …)`` (KiCad 5/6). Существующий токен сохраняет своё имя; новый
        создаётся с именем версии файла."""
        v = self.node.number("thermal_bridge_width")
        return self.node.number("thermal_width") if v is None else v

    @thermal_bridge_width.setter
    def thermal_bridge_width(self, value: float | None) -> None:
        if value is None:
            self.node.remove("thermal_bridge_width")
            self.node.remove("thermal_width")
            return
        v = _len(_check_real(value, "thermal_bridge_width"))
        for token in ("thermal_bridge_width", "thermal_width"):
            if self.node.find(token) is not None:
                self.node.set(token, v, order=PAD_ORDER)
                return
        token = "thermal_width" if self.profile.version <= _V_THERMAL_BRIDGE else "thermal_bridge_width"
        self.node.set(token, v, order=PAD_ORDER)

    def _get_opt_bool(self, name: str) -> bool | None:
        return _bool_token(self.node, name)

    def _set_opt_bool(self, name: str, value: bool | None) -> None:
        """``(name)`` (KiCad 6/7: присутствие = да) или ``(name yes|no)`` (KiCad 8+); в
        формате старше 20200809 (KiCad 5) токенов нет — ``True`` даёт ``ValueError``."""
        if value and _bool_token(self.node, name) is None:
            _require_version(self.profile, _V_REMOVE_UNUSED, name)
        self.node.set_flag(name, False)
        if value is None:
            self.node.remove(name)
            return
        if self.profile.bool_style == "yesno":
            self.node.set(name, Sym("yes" if value else "no"), order=PAD_ORDER)
        elif value:
            self.node.set(name, order=PAD_ORDER)
        else:
            self.node.remove(name)

    @property
    def remove_unused_layers(self) -> bool | None:
        """Удалять неиспользуемые слои меди: ``None`` — токена нет; ``(remove_unused_layers)``
        (KiCad 6/7) и ``(… yes)`` — ``True``; ``(… no)`` — ``False``."""
        return self._get_opt_bool("remove_unused_layers")

    @remove_unused_layers.setter
    def remove_unused_layers(self, value: bool | None) -> None:
        self._set_opt_bool("remove_unused_layers", None if value is None else bool(value))

    @property
    def keep_end_layers(self) -> bool | None:
        """Сохранять крайние слои (при ``remove_unused_layers``); формы — как у него."""
        return self._get_opt_bool("keep_end_layers")

    @keep_end_layers.setter
    def keep_end_layers(self, value: bool | None) -> None:
        self._set_opt_bool("keep_end_layers", None if value is None else bool(value))

    @property
    def locked(self) -> bool:
        """Блокировка: голый ``locked`` после формы (KiCad 6/7) или ``(locked yes)``.
        KiCad 8+ блокировку площадок в файл не пишет и при чтении игнорирует."""
        return bool(_bool_token(self.node, "locked"))

    @locked.setter
    def locked(self, value: bool) -> None:
        if value and _bool_token(self.node, "locked") is None:
            _require_version(self.profile, _V_PAD_LOCKED, "locked у площадки")
        _write_bool(self.node, "locked", bool(value), self.profile, PAD_ORDER)

    @property
    def uuid(self) -> str | None:
        """Идентификатор ``(uuid "…")`` / ``(tstamp …)`` или ``None``."""
        return _get_id(self.node)

    @uuid.setter
    def uuid(self, value: str | None) -> None:
        _set_id(self.node, value, self.profile, PAD_ORDER)

    # --- custom-площадки ---------------------------------------------------------------------
    @property
    def options(self) -> Node | None:
        """Узел ``(options (clearance …) (anchor …))`` custom-площадки или ``None``."""
        return self.node.find("options")

    @property
    def anchor(self) -> str | None:
        """Форма якоря custom-площадки (``rect`` | ``circle``) или ``None``."""
        opts = self.options
        v = None if opts is None else opts.value("anchor")
        return None if v is None else str(v)

    @anchor.setter
    def anchor(self, value: str | None) -> None:
        opts = self.options
        if value is None:
            if opts is not None:
                opts.remove("anchor")
            return
        v = _check_enum(value, ("rect", "circle"), "anchor")
        if opts is None:
            opts = Node("options", [Node("clearance", [Sym("outline")])])
            self.node.insert(opts, order=PAD_ORDER)
        opts.set("anchor", Sym(v), order=("clearance", "anchor"))

    @property
    def primitives(self) -> list[Node]:
        """Узлы-примитивы ``gr_*`` из ``(primitives …)`` (пусто, если их нет)."""
        n = self.node.find("primitives")
        return [] if n is None else n.nodes()

    @property
    def primitive_views(self) -> list[Graphic]:
        """Примитивы custom-площадки как представления :class:`Graphic` (координаты — в
        системе площадки: относительно её центра, без учёта угла)."""
        out: list[Graphic] = []
        for n in self.primitives:
            cls = _GRAPHIC_CLASSES.get(n.name)
            if cls is not None:
                out.append(cls(n, self._profile, self._parent))
        return out

    def add_primitive(self, item: Graphic | Node) -> Graphic | Node:
        """Добавить примитив (узел ``gr_*`` или представление над ним) в ``(primitives …)``;
        узел ``primitives`` создаётся при необходимости. Узел не копируется: примитив,
        уже входящий в эту или другую площадку корпуса (представление из
        :attr:`primitive_views`), — ``ValueError`` (добавьте ``item.copy()``)."""
        node = item.node if isinstance(item, View) else item
        if not isinstance(node, Node) or node.name not in _PRIM_GRAPHIC_KIND:
            raise ValueError("примитив площадки — узел gr_line/gr_rect/gr_circle/gr_arc/"
                             "gr_poly/gr_curve")
        if _contains(self.node, node):
            raise ValueError("примитив уже входит в эту площадку")
        owner = item._parent if isinstance(item, View) else None
        if owner is not None and _contains(owner.node, node):
            raise ValueError("примитив входит в другую площадку: добавьте его копию "
                             "(item.copy()) или сначала удалите его оттуда")
        prims = self.node.find("primitives")
        if prims is None:
            prims = Node("primitives")
            self.node.insert(prims, order=PAD_ORDER)
        prims.append(node)
        if isinstance(item, View):
            item._parent = self._parent
            item._profile = self._profile
        return item

    # --- преобразования ------------------------------------------------------------------------
    def move(self, dx: float, dy: float) -> None:
        """Сдвинуть площадку на ``(dx, dy)``."""
        dx, dy = _check_real(dx, "dx"), _check_real(dy, "dy")
        if dx == 0 and dy == 0:
            return
        x, y = self.position
        self.position = (x + dx, y + dy)

    def rotate(self, angle: float, origin: Point = (0.0, 0.0)) -> None:
        """Повернуть на ``angle`` градусов вокруг ``origin``: и положение, и собственный угол
        площадки (как ``PAD::Rotate``; угол нормализуется в [0, 360))."""
        a = _check_real(angle, "angle")
        o = _as_point(origin, "origin")
        if a == 0:
            return
        new_pos = _geo.rotate_point(self.position, a, o)
        if new_pos != self.position:
            self.position = new_pos
        self.angle = _norm360(self.angle + a)

    def _flip_x(self) -> None:
        """Перенос на другую сторону (часть :meth:`Footprint.flip`): ``x -> -x``, угол
        ``-a``, отражение смещения отверстия, дельты трапеции, фасок и примитивов по X,
        смена сторон слоёв (как ``PAD::Flip`` с LEFT_RIGHT при нулевой ориентации корпуса).

        Стек площадки KiCad 9+ (``(padstack (mode front_inner_back|custom) (layer …))``):
        имена слоёв его записей — ключи свойств меди, а не слои площадки; они не
        переименовываются, а свойства передней и задней сторон (и сопряжённых внутренних
        слоёв в режиме ``custom``) меняются местами с отражением каждого слоя
        (:func:`_flip_padstack`), и вместе с ними — сторона ``(tenting …)``, как в
        ``PADSTACK::FlipLayers``. У площадки без стека (режим ``normal``) KiCad 9 стороны
        маски не меняет — ``tenting`` остаётся как был."""
        x = self.x
        if x != 0:
            self.x = -x
        a = self.angle
        if a != 0:
            self.angle = _norm360(-a)
        ps = self.node.find("padstack")
        mode = None if ps is None else str(ps.value("mode") or "")
        if mode in ("front_inner_back", "custom"):
            _flip_padstack(self.node, self.profile)
            _flip_tenting(self.node)
        else:
            d = self.drill
            if d is not None and d.offset_x != 0:
                d.offset_x = -d.offset_x
            rd = self.rect_delta
            if rd is not None and rd[0] != 0:
                self.node.find("rect_delta").set_atom(0, _len(-rd[0]))  # type: ignore[union-attr]
            ch = self.chamfer
            if ch:
                new = sorted({_CHAMFER_MIRROR_X.get(c, c) for c in ch},
                             key=lambda c: CHAMFER_CORNERS.index(c) if c in CHAMFER_CORNERS
                             else 99)
                if new != ch:
                    self.node.set("chamfer", *[Sym(c) for c in new], order=PAD_ORDER)
            for g in self.primitive_views:
                g.mirror("x", 0.0)
        if ps is not None:
            # записи стека не трогаем: их «слои» — ключи свойств (см. выше)
            i = self.node.index(ps)
            del self.node.items[i]
            try:
                _flip_layer_nodes(self.node, self.profile)
            finally:
                self.node.items.insert(i, ps)
        else:
            _flip_layer_nodes(self.node, self.profile)

    def bbox(self) -> BBox:
        """Габариты площадки с учётом формы и поворота (описанный прямоугольник).

        ``circle`` — окружность диаметра ``size_x``; ``rect`` — повёрнутый прямоугольник;
        ``oval`` — «капсула»; ``roundrect`` — прямоугольник со скруглениями (с фасками —
        как прямоугольник); ``trapezoid`` — четыре угла с ``rect_delta`` (как
        ``PAD::BuildEffectiveShapes``); ``custom`` — якорь (``size``) и примитивы
        (приближённо: габариты каждого примитива с половиной ширины линии, повёрнутые
        вместе с площадкой). Смещение формы ``(drill (offset …))`` учитывается; отверстие
        тоже входит в габариты.
        """
        cx, cy = self.position
        a = self.angle
        d = self.drill
        off = (0.0, 0.0) if d is None else d.offset
        if off != (0.0, 0.0):
            ox, oy = _geo.rotate_point(off, a)
            sc = (cx + ox, cy + oy)
        else:
            sc = (cx, cy)
        sx, sy = self.size
        shape = self.shape
        boxes: list[BBox | None] = []
        if shape == "circle":
            r = sx / 2.0
            boxes.append(BBox(sc[0] - r, sc[1] - r, sc[0] + r, sc[1] + r))
        elif shape == "oval":
            boxes.append(_capsule_bbox(sc, sx, sy, a))
        elif shape == "roundrect" and not self.chamfer:
            ratio = self.roundrect_rratio
            r = min(sx, sy) * (0.25 if ratio is None else max(0.0, min(ratio, 0.5)))
            inner = _geo.rotated_rect_bbox(sc, max(sx - 2 * r, 0.0), max(sy - 2 * r, 0.0), a)
            boxes.append(inner.inflated(r))
        elif shape == "trapezoid":
            dx, dy = self.rect_delta or (0.0, 0.0)
            hx, hy, tx, ty = sx / 2.0, sy / 2.0, dx / 2.0, dy / 2.0
            corners = [(-hx - ty, hy + tx), (hx + ty, hy - tx), (hx - ty, -hy + tx),
                       (-hx + ty, -hy - tx)]
            pts = [_geo.rotate_point(p, a) for p in corners]
            boxes.append(BBox.of_points([(sc[0] + p[0], sc[1] + p[1]) for p in pts]))
        elif shape == "custom":
            if self.anchor == "circle":
                r = sx / 2.0
                boxes.append(BBox(sc[0] - r, sc[1] - r, sc[0] + r, sc[1] + r))
            else:
                boxes.append(_geo.rotated_rect_bbox(sc, sx, sy, a))
            for g in self.primitive_views:
                gb = g.bbox(with_width=True)
                if gb is None:
                    continue
                corners = [(gb.x1, gb.y1), (gb.x2, gb.y1), (gb.x2, gb.y2), (gb.x1, gb.y2)]
                pts = [_geo.rotate_point(p, a) for p in corners]
                boxes.append(BBox.of_points([(sc[0] + p[0], sc[1] + p[1]) for p in pts]))
        else:
            boxes.append(_geo.rotated_rect_bbox(sc, sx, sy, a))
        if d is not None:
            dw, dh = d.size
            if dw > 0 or dh > 0:
                boxes.append(_capsule_bbox((cx, cy), dw, dh, a))
        out = _bbox_union(boxes) or BBox(cx, cy, cx, cy)
        return _round_bbox(out)

    def __repr__(self) -> str:
        return (f"Pad({self.number!r}, {self.type}, {self.shape}, at=({self.x:g}, {self.y:g}"
                f"{', ' + format(self.angle, 'g') if self.angle else ''}), "
                f"size=({self.size_x:g}, {self.size_y:g}))")

    # Свойство ``property`` определяется последним: имя совпадает со встроенным декоратором.
    property = builtins.property(  # noqa: A003
        _get_pad_property, _set_pad_property,
        doc="Технологическое свойство площадки (``pad_prop_bga``, ``pad_prop_heatsink``, "
            "``pad_prop_castellated`` …) или ``None``; пишется голым символом.")


def _capsule_bbox(center: Point, sx: float, sy: float, angle: float) -> BBox:
    """Габариты овала («капсулы») ``sx × sy`` с центром ``center``, повёрнутого на ``angle``."""
    if sx >= sy:
        r = sy / 2.0
        half = (sx - sy) / 2.0
        ends = [(-half, 0.0), (half, 0.0)]
    else:
        r = sx / 2.0
        half = (sy - sx) / 2.0
        ends = [(0.0, -half), (0.0, half)]
    pts = [_geo.rotate_point(p, angle) for p in ends]
    b = BBox.of_points([(center[0] + p[0], center[1] + p[1]) for p in pts])
    return b.inflated(r)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Графика: fp_line / fp_rect / fp_circle / fp_arc / fp_poly / fp_curve (и gr_* примитивов)
# ---------------------------------------------------------------------------

_FILL_WORDS_TRUE = frozenset(("yes", "solid", "hatch", "reverse_hatch", "cross_hatch"))
_FILL_WORDS_FALSE = frozenset(("no", "none"))


def _fill_word(value: bool, profile: FormatProfile, primitive: bool) -> str:
    """Слово ``(fill …)`` в форме версии: фигуры корпуса — ``solid|none`` (KiCad 6–8) или
    ``yes|no`` (KiCad 9+); примитивы площадки — ``yes|none`` (6/7) или ``yes|no`` (8+)."""
    if primitive:
        if value:
            return "yes"
        return "no" if profile.bool_style == "yesno" else "none"
    if profile.fill_style == "yesno":
        return "yes" if value else "no"
    return "solid" if value else "none"


def _parser_default_fill(kind: str, width: float | None, layer: str | None) -> bool:
    """Заливка при отсутствии токена ``(fill …)`` — правило парсера KiCad
    (``parsePCB_SHAPE``): прямоугольник/окружность с нулевой шириной линии и многоугольник
    не на ``Edge.Cuts`` считаются залитыми."""
    if kind in ("rect", "circle"):
        return (width or 0.0) == 0.0
    if kind == "poly":
        return layer != "Edge.Cuts"
    return False


class Graphic(View):
    """Базовое представление графики корпуса (``fp_*``) и примитивов площадки (``gr_*``).

    Ширина линии — ``(stroke (width w) (type t))`` (KiCad 7+) или ``(width w)`` (KiCad 5/6,
    а также примитивы площадок во всех версиях). Заливка читается во всех формах
    (``yes``/``solid`` — да, ``no``/``none`` — нет; при отсутствии токена — правило парсера
    KiCad, см. :attr:`fill`) и пишется в форме версии файла.

    Преобразования (:meth:`move`, :meth:`rotate`, :meth:`mirror`) меняют только
    координатные узлы (``start``/``mid``/``end``/``center``/``xy``); габариты
    (:meth:`bbox`) — геометрические, без ширины линии (``with_width=True`` — с половиной
    ширины).
    """

    __slots__ = ()

    def _order(self) -> Sequence[str]:
        if self.is_primitive:
            return _PRIMITIVE_ORDER
        return self.profile.graphic_order

    @property
    def kind(self) -> str:
        """Вид фигуры: ``line`` | ``rect`` | ``circle`` | ``arc`` | ``poly`` | ``curve``."""
        return _GRAPHIC_KIND.get(self.node.name, self.node.name)

    @property
    def is_primitive(self) -> bool:
        """Примитив custom-площадки (узел ``gr_*``), а не графика корпуса."""
        return self.node.name.startswith("gr_")

    # --- слой ------------------------------------------------------------------------------
    @property
    def layer(self) -> str | None:
        """Слой ``(layer …)``; при форме ``(layers …)`` (KiCad 9, медь с маской) — первый из
        слоёв; ``None`` — слоя нет (примитивы площадки)."""
        v = self.node.value("layer")
        if v is not None:
            return str(v)
        ls = self.node.find("layers")
        a = None if ls is None else ls.atom(0)
        return None if a is None else str(a)

    @layer.setter
    def layer(self, value: str) -> None:
        name = _check_layer(value)
        atom = _layer_atom(name, self.profile)
        ln = self.node.find("layer")
        if ln is not None:
            ln.set_atom(0, atom)
            return
        lsn = self.node.find("layers")
        if lsn is not None:
            # (layers A B) -> (layer X): одиночный слой заменяет набор (на его месте)
            self.node.replace_child(lsn, Node("layer", [atom]))
            return
        self.node.set("layer", atom, order=self._order())

    @property
    def layers(self) -> list[str]:
        """Все слои фигуры: атомы ``(layers …)`` или ``[layer]`` (пусто — слоя нет)."""
        ls = self.node.find("layers")
        if ls is not None:
            return [str(a) for a in ls.atoms()]
        v = self.node.value("layer")
        return [] if v is None else [str(v)]

    # --- линия и заливка -------------------------------------------------------------------
    @property
    def width(self) -> float | None:
        """Ширина линии, мм: ``(stroke (width …))`` или ``(width …)``; ``None`` — нет токена.

        Присваивание меняет существующий токен (``stroke`` — если он есть в узле, иначе
        ``width``); если нет ни того ни другого, создаётся форма версии файла:
        ``(stroke (width w) (type solid))`` (KiCad 7+) или ``(width w)`` (KiCad 5/6 и
        примитивы площадок). ``None`` удаляет ширину.
        """
        st = self.node.find("stroke")
        if st is not None:
            w = st.number("width")
            if w is not None:
                return w
        return self.node.number("width")

    @width.setter
    def width(self, value: float | None) -> None:
        st = self.node.find("stroke")
        if value is None:
            self.node.remove("width")
            if st is not None:
                st.remove("width")
            return
        w = _len(_check_real(value, "width"))
        if st is not None:
            st.set("width", w, order=STROKE_ORDER)
            return
        if self.node.find("width") is not None or self.is_primitive or not self.profile.stroke:
            self.node.set("width", w, order=self._order())
            return
        self.node.insert(Node("stroke", [Node("width", [w]), Node("type", [Sym("solid")])]),
                         order=self._order())

    @property
    def stroke_type(self) -> str | None:
        """Тип линии ``(stroke (type …))``: ``solid``, ``dash``, ``dot``, ``dash_dot``,
        ``dash_dot_dot``, ``default``; ``None`` — нет ``stroke`` (KiCad 5/6) или типа.

        Присваивание в узле с ``(width …)`` (форма KiCad 6) при профиле с ``stroke``
        заменяет ``(width w)`` на ``(stroke (width w) (type …))``; в формате без
        ``stroke`` (KiCad 5/6, примитивы) — ``ValueError``.
        """
        st = self.node.find("stroke")
        v = None if st is None else st.value("type")
        return None if v is None else str(v)

    @stroke_type.setter
    def stroke_type(self, value: str | None) -> None:
        st = self.node.find("stroke")
        if value is None:
            if st is not None:
                st.remove("type")
            return
        v = _check_enum(value, STROKE_TYPES, "stroke_type")
        if st is not None:
            st.set("type", Sym(v), order=STROKE_ORDER)
            return
        if self.is_primitive or not self.profile.stroke:
            raise ValueError("в этом формате (KiCad 5/6 или примитив площадки) у линии нет типа "
                             "(stroke); доступна только ширина")
        w = self.node.number("width")
        self.node.remove("width")
        self.node.insert(Node("stroke", [Node("width", [_len(w or 0.0)]), Node("type", [Sym(v)])]),
                         order=self._order())

    @property
    def fill(self) -> bool:
        """Заливка: ``(fill yes|solid)`` — ``True``, ``(fill no|none)`` и пустой ``(fill)`` —
        ``False`` (несколько значений — побеждает последнее, как в KiCad). Если токена нет,
        действует правило парсера KiCad (``parsePCB_SHAPE``): залиты прямоугольник и
        окружность с нулевой шириной линии и многоугольник не на ``Edge.Cuts`` (так
        читаются файлы KiCad 5); у линий, дуг и кривых заливки нет.

        Присваивание пишет ``(fill …)`` в форме версии: ``solid|none`` (KiCad 6–8),
        ``yes|no`` (KiCad 9+); у примитивов площадки — ``yes|none`` (6/7) / ``yes|no`` (8+).
        Для линии/дуги/кривой ``True`` — ``ValueError``. В формате KiCad 5 (``module``,
        версия < 20201114) токена ``fill`` нет: допустимо только значение по умолчанию
        парсера (токен не пишется), иное — ``ValueError`` (нужен :meth:`Footprint.upgrade`).
        """
        f = self.node.find("fill")
        if f is not None:
            filled = False
            for a in f.atoms():
                w = str(a)
                if w in _FILL_WORDS_TRUE:
                    filled = True
                elif w in _FILL_WORDS_FALSE:
                    filled = False
            return filled
        return _parser_default_fill(self.kind, self.width, self.layer)

    @fill.setter
    def fill(self, value: bool) -> None:
        v = bool(value)
        if self.kind not in _FILL_KINDS:
            if v:
                raise ValueError(f"у фигуры вида {self.kind!r} нет заливки")
            self.node.remove("fill")
            return
        if self.profile.version < _V_FILL:
            # формат KiCad 5: токена fill нет, заливка — только умолчание парсера
            if v == self.fill:
                return
            if v == _parser_default_fill(self.kind, self.width, self.layer):
                self.node.remove("fill")
                return
            _require_version(self.profile, _V_FILL, "fill")
        self.node.set("fill", Sym(_fill_word(v, self.profile, self.is_primitive)),
                      order=self._order())

    @property
    def locked(self) -> bool:
        """Блокировка: голый ``locked`` сразу после имени узла (KiCad 6/7) или
        ``(locked yes)`` (KiCad 8+). В KiCad 5 (``module``) блокировки фигур нет —
        установка — ``ValueError``."""
        return bool(_bool_token(self.node, "locked"))

    @locked.setter
    def locked(self, value: bool) -> None:
        if value and _bool_token(self.node, "locked") is None:
            _require_version(self.profile, _V_FOOTPRINT_ROOT, "locked у фигуры")
        _write_bool(self.node, "locked", bool(value), self.profile, self._order())

    @property
    def uuid(self) -> str | None:
        """Идентификатор ``(uuid "…")`` / ``(tstamp …)`` или ``None``."""
        return _get_id(self.node)

    @uuid.setter
    def uuid(self, value: str | None) -> None:
        _set_id(self.node, value, self.profile, self._order())

    # --- геометрия --------------------------------------------------------------------------
    def _coord_nodes(self) -> list[Node]:
        """Координатные узлы фигуры: start/mid/end/center и точки ``pts`` (включая дуги)."""
        out = [c for c in self.node.nodes() if c.name in ("start", "mid", "end", "center")]
        pts = self.node.find("pts")
        if pts is not None:
            for c in pts.nodes():
                if c.name == "xy":
                    out.append(c)
                elif c.name == "arc":
                    out.extend(x for x in c.nodes() if x.name in ("start", "mid", "end"))
        return out

    @property
    def points(self) -> PointList:
        """Характерные точки фигуры (для габаритов и отрисовки); можно и вызвать:
        ``g.points()``."""
        return PointList(self._points())

    def _points(self) -> list[Point]:
        return [p for p in (_xy_of(n) for n in self._coord_nodes()) if p is not None]

    def move(self, dx: float, dy: float) -> None:
        """Сдвинуть фигуру на ``(dx, dy)``."""
        dx, dy = _check_real(dx, "dx"), _check_real(dy, "dy")
        if dx == 0 and dy == 0:
            return
        for n in self._coord_nodes():
            _shift_node(n, dx, dy)

    def rotate(self, angle: float, origin: Point = (0.0, 0.0)) -> None:
        """Повернуть фигуру на ``angle`` градусов вокруг ``origin`` (соглашение KiCad)."""
        a = _check_real(angle, "angle")
        o = _as_point(origin, "origin")
        if a == 0:
            return
        for n in self._coord_nodes():
            _rotate_node(n, a, o)

    def mirror(self, axis: str = "x", origin: float = 0.0) -> None:
        """Отразить фигуру: ``axis="x"`` — относительно вертикали ``x = origin`` (меняется X),
        ``axis="y"`` — относительно горизонтали ``y = origin``."""
        if axis not in ("x", "y"):
            raise ValueError(f"неизвестная ось отражения: {axis!r} (ожидается 'x' или 'y')")
        o = _check_real(origin, "origin")
        for n in self._coord_nodes():
            _mirror_node(n, axis, o)

    def _geom_bbox(self) -> BBox | None:
        return BBox.of_points(self._points())

    def bbox(self, with_width: bool = False) -> BBox | None:
        """Габариты фигуры (геометрические; ``with_width=True`` — с половиной ширины линии).
        ``None`` — у узла нет координат."""
        b = self._geom_bbox()
        if b is None:
            return None
        if with_width:
            w = self.width or 0.0
            if w > 0:
                b = b.inflated(w / 2.0)
        return _round_bbox(b)

    def length(self) -> float:
        """Длина линии / периметр фигуры, мм."""
        return _geo.polyline_length(self._points())

    def __repr__(self) -> str:
        return f"{type(self).__name__}(layer={self.layer!r}, points={list(self._points())!r})"


def _new_graphic(cls: type, fp_name: str, coords: list[Node], layer: str, width: float, *,
                 profile: FormatProfile | None, uuid: bool | str | None, stroke_type: str,
                 locked: bool, fill: bool | None, primitive: bool) -> Graphic:
    """Собрать узел графики в форме профиля и вернуть представление ``cls`` над ним."""
    prof = profile or _default_profile()
    w = _len(_check_real(width, "width"))
    kind = _FP_GRAPHIC_KIND[fp_name]
    if primitive:
        node = Node("gr_" + fp_name[3:], coords + [Node("width", [w])])
        if kind in _FILL_KINDS and (fill is not None or prof.version >= _V_FILL):
            if prof.version >= _V_FILL:
                node.append(Node("fill", [Sym(_fill_word(bool(fill), prof, True))]))
            elif bool(fill) != _parser_default_fill(kind, float(w), None):
                _require_version(prof, _V_FILL, "fill")
        return cls(node, prof)
    # fill=None у rect/circle/poly — «не задано»: в KiCad 6+ пишется (fill none|no), как у
    # KiCad, в KiCad 5 — ничего (действует умолчание парсера)
    if fp_name == "fp_rect":
        _require_version(prof, _V_FP_RECT, "fp_rect (прямоугольник; в KiCad 5 — четыре "
                                           "отрезка или fp_poly)")
    name = _check_layer(layer)
    node = Node(fp_name, coords)
    order = prof.graphic_order
    if prof.stroke:
        node.insert(Node("stroke", [Node("width", [w]),
                                    Node("type", [Sym(_check_enum(stroke_type, STROKE_TYPES,
                                                                  "stroke_type"))])]),
                    order=order)
    else:
        node.insert(Node("width", [w]), order=order)
    if kind in _FILL_KINDS and (fill is not None or prof.version >= _V_FILL):
        f = bool(fill)
        if prof.version >= _V_FILL:
            node.insert(Node("fill", [Sym(_fill_word(f, prof, False))]), order=order)
        elif f != _parser_default_fill(kind, float(w), name):
            # KiCad 5 (module) токена fill не знал: заливка там — только умолчание парсера
            # (fp_poly залит, окружность с ненулевой линией — нет)
            _require_version(prof, _V_FILL, "fill")
    node.insert(Node("layer", [_layer_atom(name, prof)]), order=order)
    if locked:
        _write_bool(node, "locked", True, prof, order)
    _add_new_id(node, prof, order, uuid)
    return cls(node, prof)


def _pt_node(name: str, p: Any, what: str) -> Node:
    x, y = _as_point(p, what)
    return Node(name, [_len(x), _len(y)])


def _pts_node(points: Iterable[Any], what: str = "points") -> Node:
    return Node("pts", [_pt_node("xy", p, what) for p in points])


class _StartEnd(Graphic):
    """Общая часть фигур, заданных узлами ``(start x y)`` и ``(end x y)``."""

    __slots__ = ()

    @property
    def start(self) -> Point:
        """Начало ``(x, y)``."""
        return _point_of(self.node, "start") or (0.0, 0.0)

    @start.setter
    def start(self, value: Point) -> None:
        _set_point(self.node, "start", _as_point(value, "start"), self._order())

    @property
    def end(self) -> Point:
        """Конец ``(x, y)``."""
        return _point_of(self.node, "end") or (0.0, 0.0)

    @end.setter
    def end(self, value: Point) -> None:
        _set_point(self.node, "end", _as_point(value, "end"), self._order())

    @property
    def start_x(self) -> float:
        """X начала."""
        return self.start[0]

    @start_x.setter
    def start_x(self, value: float) -> None:
        _set_coord_atom(self.node, "start", 0, _check_real(value, "start_x"), self._order())

    @property
    def start_y(self) -> float:
        """Y начала."""
        return self.start[1]

    @start_y.setter
    def start_y(self, value: float) -> None:
        _set_coord_atom(self.node, "start", 1, _check_real(value, "start_y"), self._order())

    @property
    def end_x(self) -> float:
        """X конца."""
        return self.end[0]

    @end_x.setter
    def end_x(self, value: float) -> None:
        _set_coord_atom(self.node, "end", 0, _check_real(value, "end_x"), self._order())

    @property
    def end_y(self) -> float:
        """Y конца."""
        return self.end[1]

    @end_y.setter
    def end_y(self, value: float) -> None:
        _set_coord_atom(self.node, "end", 1, _check_real(value, "end_y"), self._order())



class Line(_StartEnd):
    """Отрезок ``(fp_line (start x y) (end x y) …)`` (примитив — ``gr_line``)."""

    __slots__ = ()

    @classmethod
    def new(cls, start: Point, end: Point, layer: str = "F.SilkS", width: float = 0.12, *,
            profile: FormatProfile | None = None, uuid: bool | str | None = True,
            stroke_type: str = "solid", locked: bool = False, primitive: bool = False) -> Line:
        """Новый отрезок в форме профиля (``primitive=True`` — ``gr_line`` для площадки)."""
        return _new_graphic(cls, "fp_line", [_pt_node("start", start, "start"),
                                             _pt_node("end", end, "end")],
                            layer, width, profile=profile, uuid=uuid, stroke_type=stroke_type,
                            locked=locked, fill=None, primitive=primitive)  # type: ignore[return-value]

    def _points(self) -> list[Point]:
        return [self.start, self.end]

    def length(self) -> float:
        """Длина отрезка, мм."""
        return _geo.distance(self.start, self.end)


class Rect(_StartEnd):
    """Прямоугольник ``(fp_rect (start x y) (end x y) …)`` по двум противоположным углам.

    Поворот на угол, не кратный 90°, превращает его в многоугольник ``fp_poly`` (как
    ``EDA_SHAPE::rotate`` KiCad): узел переименовывается, ``start``/``end`` заменяются на
    ``(pts …)``, а представление становится :class:`Poly`.
    """

    __slots__ = ()

    @classmethod
    def new(cls, start: Point, end: Point, layer: str = "F.SilkS",
            width: float = 0.12, *, fill: bool | None = None, profile: FormatProfile | None = None,
            uuid: bool | str | None = True, stroke_type: str = "solid", locked: bool = False,
            primitive: bool = False) -> Rect:
        """Новый прямоугольник в форме профиля (``fill`` пишется всегда, как в KiCad 6+;
        ``None`` — без заливки). В формате KiCad 5 (``module``, версия < 20200614) ``fp_rect``
        нет — ``ValueError``."""
        return _new_graphic(cls, "fp_rect", [_pt_node("start", start, "start"),
                                             _pt_node("end", end, "end")],
                            layer, width, profile=profile, uuid=uuid, stroke_type=stroke_type,
                            locked=locked, fill=fill, primitive=primitive)  # type: ignore[return-value]

    def _points(self) -> list[Point]:
        return _geo.rect_corners(self.start, self.end)

    def length(self) -> float:
        """Периметр, мм."""
        (x1, y1), (x2, y2) = self.start, self.end
        return 2.0 * (abs(x2 - x1) + abs(y2 - y1))

    def rotate(self, angle: float, origin: Point = (0.0, 0.0)) -> None:
        """Поворот; на угол, не кратный 90°, — с превращением в ``fp_poly`` (см. класс)."""
        a = _check_real(angle, "angle")
        o = _as_point(origin, "origin")
        if a == 0:
            return
        if _is_cardinal(a):
            super().rotate(a, o)
            return
        corners = [_geo.rotate_point(p, a, o) for p in _geo.rect_corners(self.start, self.end)]
        node = self.node
        st = node.find("start")
        pos = node.index(st) if st is not None else 0
        node.remove("start")
        node.remove("end")
        node.remove("radius")
        node.items.insert(min(pos, len(node.items)), _pts_node(corners))
        node.name = "gr_poly" if node.name.startswith("gr_") else "fp_poly"
        self.__class__ = Poly  # type: ignore[assignment]


class Circle(Graphic):
    """Окружность ``(fp_circle (center x y) (end x y) …)``; ``end`` — точка на окружности."""

    __slots__ = ()

    @classmethod
    def new(cls, center: Point, radius: float | None = None, layer: str = "F.SilkS",
            width: float = 0.12, *, end: Point | None = None, fill: bool | None = None,
            profile: FormatProfile | None = None, uuid: bool | str | None = True,
            stroke_type: str = "solid", locked: bool = False, primitive: bool = False) -> Circle:
        """Новая окружность: центр и радиус (точка ``end`` — справа от центра) или явная
        точка ``end`` на окружности."""
        cx, cy = _as_point(center, "center")
        if end is None:
            if radius is None:
                raise TypeError("Circle.new: нужен radius или end")
            r = _check_real(radius, "radius")
            end = (cx + r, cy)
        return _new_graphic(cls, "fp_circle", [_pt_node("center", (cx, cy), "center"),
                                               _pt_node("end", end, "end")],
                            layer, width, profile=profile, uuid=uuid, stroke_type=stroke_type,
                            locked=locked, fill=fill, primitive=primitive)  # type: ignore[return-value]

    @property
    def center(self) -> Point:
        """Центр ``(x, y)``."""
        return _point_of(self.node, "center") or (0.0, 0.0)

    @center.setter
    def center(self, value: Point) -> None:
        _set_point(self.node, "center", _as_point(value, "center"), self._order())

    @property
    def end(self) -> Point:
        """Точка на окружности ``(x, y)``."""
        return _point_of(self.node, "end") or (0.0, 0.0)

    @end.setter
    def end(self, value: Point) -> None:
        _set_point(self.node, "end", _as_point(value, "end"), self._order())

    @property
    def radius(self) -> float:
        """Радиус (вычисляемый); присваивание сдвигает ``end`` вдоль прежнего направления
        (или вправо от центра, если окружность вырождена)."""
        return _geo.distance(self.center, self.end)

    @radius.setter
    def radius(self, value: float) -> None:
        r = _check_real(value, "radius")
        (cx, cy), (ex, ey) = self.center, self.end
        d = math.hypot(ex - cx, ey - cy)
        if d == 0:
            self.end = (cx + r, cy)
        else:
            self.end = (cx + (ex - cx) * r / d, cy + (ey - cy) * r / d)

    def _points(self) -> list[Point]:
        return [self.center, self.end]

    def _geom_bbox(self) -> BBox | None:
        (cx, cy), r = self.center, self.radius
        return BBox(cx - r, cy - r, cx + r, cy + r)

    def length(self) -> float:
        """Длина окружности, мм."""
        return 2.0 * math.pi * self.radius


class Arc(Graphic):
    """Дуга: ``(fp_arc (start x y) (mid x y) (end x y) …)`` (KiCad 6+) или старая форма
    KiCad 5 ``(fp_arc (start ЦЕНТР) (end НАЧАЛО) (angle A) …)``.

    Getters всегда дают ``start``/``mid``/``end`` (для старой формы — вычисленные так же,
    как их вычисляет KiCad 6+ при чтении, в целых нанометрах). Форму записи KiCad выбирает
    **по версии файла** (``<= 20210925`` — старая, иначе ``start/mid/end``; в файле
    «не своей» формы KiCad выдаёт ошибку), поэтому setters пишут форму версии файла: в
    файле KiCad 6+ старый узел перестраивается в ``start/mid/end`` (единственный случай
    перестройки узла при присваивании одного значения), в файле KiCad 5 узел остаётся в
    старой форме (меняются центр, начало и угол). ``center``, ``radius``,
    ``start_angle``, ``end_angle``, ``sweep`` — вычисляемые
    (:func:`kicadfp.geometry.arc_from_three_points`).

    В форме ``start/mid/end`` любая запись точек (:attr:`start`, :attr:`mid`, :attr:`end`,
    :meth:`set_points`, :meth:`new`) сохраняет в ``(mid …)`` **истинную середину** дуги,
    проходящей через три заданные точки, как writer KiCad: KiCad 6+ считает ``mid`` лишь
    подсказкой стороны (``EDA_SHAPE::SetArcGeometry``) и дугу, у которой ``mid`` далеко от
    середины (дальше, чем центр), читает как дополнительную. Поэтому после присваивания
    :attr:`mid` возвращает середину дуги, а не присвоенную точку (если они различаются
    больше чем на 1 нм).
    """

    __slots__ = ()

    @classmethod
    def new(cls, start: Point, mid: Point, end: Point, layer: str = "F.SilkS",
            width: float = 0.12, *, profile: FormatProfile | None = None,
            uuid: bool | str | None = True, stroke_type: str = "solid", locked: bool = False,
            primitive: bool = False) -> Arc:
        """Новая дуга по трём точкам в форме профиля (для KiCad 5 — центр/начало/угол)."""
        prof = profile or _default_profile()
        s = _as_point(start, "start")
        m = _as_point(mid, "mid")
        e = _as_point(end, "end")
        if prof.arc_mid:
            m = _true_arc_mid(s, m, e)
            coords = [_pt_node("start", s, "start"), _pt_node("mid", m, "mid"),
                      _pt_node("end", e, "end")]
        else:
            c, sp, a = _three_to_legacy(s, m, e)
            coords = [_pt_node("start", c, "center"), _pt_node("end", sp, "start"),
                      Node("angle", [_ang(a)])]
        return _new_graphic(cls, "fp_arc", coords, layer, width, profile=prof, uuid=uuid,
                            stroke_type=stroke_type, locked=locked, fill=None,
                            primitive=primitive)  # type: ignore[return-value]

    @classmethod
    def from_center(cls, center: Point, start: Point, sweep: float, layer: str = "F.SilkS",
                    width: float = 0.12, **kw: Any) -> Arc:
        """Дуга по центру, начальной точке и углу ``sweep`` (градусы; положительный — против
        часовой стрелки на экране, как в :mod:`kicadfp.geometry`)."""
        s, m, e = _geo.arc_three_points(_as_point(center, "center"), _as_point(start, "start"),
                                        _check_real(sweep, "sweep"))
        return cls.new(s, m, e, layer, width, **kw)

    @property
    def is_legacy(self) -> bool:
        """Узел в старой форме KiCad 5 (``angle`` без ``mid``)."""
        return _arc_is_legacy(self.node)

    def _three(self) -> tuple[Point, Point, Point]:
        t = _arc_three(self.node)
        return t if t is not None else ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0))

    def _write_three(self, s: Point, m: Point, e: Point) -> None:
        if self.profile.arc_mid:
            _arc_write_modern(self.node, s, _true_arc_mid(s, m, e), e)
        else:
            _arc_write_legacy(self.node, s, m, e)

    def _set_one(self, index: int, name: str, value: Point) -> None:
        p = _as_point(value, name)
        pts = list(self._three())
        if _same_point_nm(pts[index], p):
            # точка не меняется (с точностью до 1 нм): узел не трогаем (старую форму не
            # перекодируем — пересчёт центра и угла дал бы дрейф 135 -> 134.999978)
            return
        pts[index] = p
        if self.profile.arc_mid and not self.is_legacy:
            # меняется только своя точка и (mid …): KiCad читает mid лишь как подсказку
            # стороны, поэтому пишется истинная середина новой дуги (_true_arc_mid)
            if index != 1:
                _set_point(self.node, name, p, self._order())
            new_mid = _true_arc_mid(*pts)
            cur_mid = _point_of(self.node, "mid")
            if cur_mid is None or not _same_point_nm(cur_mid, new_mid):
                _set_point(self.node, "mid", new_mid, self._order())
            return
        self._write_three(*pts)

    @property
    def start(self) -> Point:
        """Начало дуги."""
        return self._three()[0]

    @start.setter
    def start(self, value: Point) -> None:
        self._set_one(0, "start", value)

    @property
    def mid(self) -> Point:
        """Промежуточная точка дуги."""
        return self._three()[1]

    @mid.setter
    def mid(self, value: Point) -> None:
        self._set_one(1, "mid", value)

    @property
    def end(self) -> Point:
        """Конец дуги."""
        return self._three()[2]

    @end.setter
    def end(self, value: Point) -> None:
        self._set_one(2, "end", value)

    def set_points(self, start: Point, mid: Point, end: Point) -> None:
        """Задать все три точки сразу (в форме версии файла; если ни одна не меняется с
        точностью до 1 нм — узел не трогается)."""
        new = (_as_point(start, "start"), _as_point(mid, "mid"), _as_point(end, "end"))
        if all(_same_point_nm(a, b) for a, b in zip(self._three(), new)):
            return
        self._write_three(*new)

    def _geometry(self) -> _geo.ArcGeometry | None:
        return _geo.arc_from_three_points(*self._three())

    @property
    def center(self) -> Point:
        """Центр окружности дуги (для вырожденной дуги — середина хорды)."""
        g = self._geometry()
        if g is None:
            s, _, e = self._three()
            return ((s[0] + e[0]) / 2.0, (s[1] + e[1]) / 2.0)
        return (_geo.round_mm(g.center[0]), _geo.round_mm(g.center[1]))

    @property
    def radius(self) -> float:
        """Радиус (0 для вырожденной дуги), с точностью до нанометра."""
        g = self._geometry()
        return 0.0 if g is None else _geo.round_mm(g.radius)

    @property
    def start_angle(self) -> float:
        """Угол направления на начало, градусы [0, 360) (против часовой на экране)."""
        g = self._geometry()
        return 0.0 if g is None else g.start_angle

    @property
    def end_angle(self) -> float:
        """Угол направления на конец, градусы [0, 360)."""
        g = self._geometry()
        return 0.0 if g is None else g.end_angle

    @property
    def sweep(self) -> float:
        """Угол дуги со знаком (положительный — против часовой стрелки на экране)."""
        g = self._geometry()
        return 0.0 if g is None else g.sweep

    def _points(self) -> list[Point]:
        return list(self._three())

    def _geom_bbox(self) -> BBox | None:
        return _geo.arc_bbox(*self._three())

    def length(self) -> float:
        """Длина дуги, мм."""
        g = self._geometry()
        if g is None:
            s, _, e = self._three()
            return _geo.distance(s, e)
        return g.radius * math.radians(abs(g.sweep))

    def mirror(self, axis: str = "x", origin: float = 0.0) -> None:
        """Отражение (у старой формы — ещё и смена знака угла)."""
        super().mirror(axis, origin)
        if self.is_legacy:
            an = self.node.find("angle")
            a = _num(an.atom(0)) if an is not None else None
            if an is not None and a is not None:
                an.set_atom(0, _ang(-a))


class Poly(Graphic):
    """Многоугольник ``(fp_poly (pts (xy x y) … [(arc (start)(mid)(end))]) …)``.

    :attr:`points` — вершины по порядку (у дуги внутри ``pts`` — её три точки);
    присваивание переписывает ``pts`` точками ``(xy …)`` (дуги при этом теряются, пока
    ``pts`` не присваивается, они сохраняются как есть, в том числе при
    :meth:`move`/:meth:`rotate`/:meth:`mirror`).
    """

    __slots__ = ()

    @classmethod
    def new(cls, points: Iterable[Point], layer: str = "F.SilkS", width: float = 0.12, *,
            fill: bool | None = None, profile: FormatProfile | None = None,
            uuid: bool | str | None = True, stroke_type: str = "solid", locked: bool = False,
            primitive: bool = False) -> Poly:
        """Новый многоугольник в форме профиля (``fill`` — как у :meth:`Rect.new`)."""
        return _new_graphic(cls, "fp_poly", [_pts_node(points)], layer, width, profile=profile,
                            uuid=uuid, stroke_type=stroke_type, locked=locked, fill=fill,
                            primitive=primitive)  # type: ignore[return-value]

    @property
    def points(self) -> PointList:
        """Вершины ``[(x, y), …]`` (можно и вызвать: ``poly.points()``)."""
        return PointList(self._points())

    @points.setter
    def points(self, value: Iterable[Point]) -> None:
        pts = _pts_node(value)
        old = self.node.find("pts")
        if old is None:
            self.node.items.insert(0, pts)
        else:
            old.items = pts.items

    def _segments(self) -> list[tuple[str, Any]]:
        """Элементы контура: ``("xy", точка)`` или ``("arc", (s, m, e))``."""
        out: list[tuple[str, Any]] = []
        pts = self.node.find("pts")
        if pts is None:
            return out
        for c in pts.nodes():
            if c.name == "xy":
                p = _xy_of(c)
                if p is not None:
                    out.append(("xy", p))
            elif c.name == "arc":
                s, m, e = (_point_of(c, "start"), _point_of(c, "mid"), _point_of(c, "end"))
                if s is not None and m is not None and e is not None:
                    out.append(("arc", (s, m, e)))
        return out

    def _geom_bbox(self) -> BBox | None:
        boxes: list[BBox | None] = []
        for kind, v in self._segments():
            if kind == "xy":
                boxes.append(BBox(v[0], v[1], v[0], v[1]))
            else:
                boxes.append(_geo.arc_bbox(*v))
        return _bbox_union(boxes)

    def length(self) -> float:
        """Периметр замкнутого контура (дуги внутри ``pts`` — по длине дуги), мм."""
        total = 0.0
        first: Point | None = None
        prev: Point | None = None
        for kind, v in self._segments():
            if kind == "xy":
                start = end = v
                arc_len = 0.0
            else:
                start, mid, end = v
                g = _geo.arc_from_three_points(start, mid, end)
                arc_len = _geo.distance(start, end) if g is None else \
                    g.radius * math.radians(abs(g.sweep))
            if prev is None:
                first = start
            else:
                total += _geo.distance(prev, start)
            total += arc_len
            prev = end
        if prev is not None and first is not None:
            total += _geo.distance(prev, first)
        return total


class Curve(Graphic):
    """Кубическая кривая Безье ``(fp_curve (pts (xy P0) (xy C1) (xy C2) (xy P3)) …)``."""

    __slots__ = ()

    @classmethod
    def new(cls, points: Sequence[Point], layer: str = "F.SilkS", width: float = 0.12, *,
            profile: FormatProfile | None = None, uuid: bool | str | None = True,
            stroke_type: str = "solid", locked: bool = False, primitive: bool = False) -> Curve:
        """Новая кривая по четырём точкам (начало, C1, C2, конец)."""
        pts = list(points)
        if len(pts) != 4:
            raise ValueError("кривая Безье задаётся ровно четырьмя точками")
        return _new_graphic(cls, "fp_curve", [_pts_node(pts)], layer, width, profile=profile,
                            uuid=uuid, stroke_type=stroke_type, locked=locked, fill=None,
                            primitive=primitive)  # type: ignore[return-value]

    @property
    def points(self) -> PointList:
        """Четыре точки ``[P0, C1, C2, P3]`` (можно и вызвать)."""
        return PointList(self._points())

    @points.setter
    def points(self, value: Sequence[Point]) -> None:
        pts = list(value)
        if len(pts) != 4:
            raise ValueError("кривая Безье задаётся ровно четырьмя точками")
        node = _pts_node(pts)
        old = self.node.find("pts")
        if old is None:
            self.node.items.insert(0, node)
        else:
            old.items = node.items

    def _curve_points(self, segments: int = 64) -> list[Point]:
        pts = self._points()
        if len(pts) != 4:
            return pts
        return _geo.bezier_points(pts[0], pts[1], pts[2], pts[3], segments)

    def _geom_bbox(self) -> BBox | None:
        return BBox.of_points(self._curve_points())

    def length(self) -> float:
        """Длина кривой (по ломаной из 64 отрезков), мм."""
        return _geo.polyline_length(self._curve_points())


_GRAPHIC_CLASSES: dict[str, type[Graphic]] = {
    "fp_line": Line, "gr_line": Line, "gr_vector": Line,
    "fp_rect": Rect, "gr_rect": Rect, "gr_bbox": Rect,
    "fp_circle": Circle, "gr_circle": Circle,
    "fp_arc": Arc, "gr_arc": Arc,
    "fp_poly": Poly, "gr_poly": Poly,
    "fp_curve": Curve, "gr_curve": Curve,
}


# ---------------------------------------------------------------------------
# Text: fp_text (все версии) и property с текстовыми атрибутами (KiCad 8+)
# ---------------------------------------------------------------------------

def _is_text_property(node: Node) -> bool:
    """``property`` с текстовыми атрибутами (``at``/``layer``/``effects``) — поле KiCad 8+."""
    return node.name == "property" and any(node.find(n) is not None for n in _TEXT_ATTRS)


def _field_slot(node: Node) -> str | None:
    """Имя поля корпуса, которое занимает узел: ``fp_text reference``/``value`` и
    ``property "Reference"``/``"Value"`` — ``"Reference"``/``"Value"``, прочий ``property``
    — его имя; ``fp_text user`` и прочие узлы — ``None``.

    У корпуса KiCad каждое поле одно (``FOOTPRINT::Reference()``/``Value()``,
    ``GetFieldByName``): второй узел того же поля парсер KiCad не добавляет, а переписывает
    им первое (``fp_text`` — целиком, ``property`` — текст и заданные атрибуты), так что
    действует последний из них."""
    if node.name == "fp_text":
        a = node.atom(0)
        return None if a is None else _FIELD_NAMES.get(str(a))
    if node.name == "property":
        a = node.atom(0)
        return None if a is None else str(a)
    return None


def _slot_nodes(root: Node, slot: str) -> list[Node]:
    """Все узлы корня, занимающие поле ``slot`` (см. :func:`_field_slot`), в порядке файла."""
    return [n for n in root.nodes() if n.name in ("fp_text", "property")
            and _field_slot(n) == slot]


def _check_free_slot(root: Node | None, slot: str | None, node: Node) -> None:
    """``ValueError``, если поле ``slot`` в корне ``root`` уже занято другим узлом."""
    if root is None or slot is None:
        return
    if any(n is not node for n in _slot_nodes(root, slot)):
        raise ValueError(f"поле {slot} у корпуса уже есть: KiCad хранит одно такое поле и "
                         f"второе молча отбрасывает — измените имеющееся (или удалите его)")


class Text(View):
    """Текст корпуса: узел ``(fp_text ВИД [locked] "ТЕКСТ" …)`` или поле
    ``(property "ИМЯ" "ЗНАЧЕНИЕ" (at …) (layer …) … (effects …))`` (KiCad 8+).

    ``kind`` — ``reference`` | ``value`` | ``user`` (у ``fp_text`` — первый атом; у поля — по
    имени: ``Reference``, ``Value``, прочие — ``user``); ``name`` — имя поля или ``None``
    у ``fp_text``; ``text`` — текст (у поля — значение, второй атом).

    Формы токенов по версиям: угол в ``(at x y угол)`` KiCad 8+ пишет всегда (в т.ч. 0),
    KiCad 5–7 — только ненулевой; ``hide`` — голый флаг после ``(layer …)`` (5–7) или
    ``(hide yes)`` (8+); «не держать вертикально» — голый ``unlocked`` внутри ``(at …)`` (5–7)
    или ``(unlocked yes)`` (8+); ``bold``/``italic`` — голые флаги в ``font`` (5–7) или
    ``(bold yes)`` (8+); ``knockout`` — голый флаг в ``(layer … knockout)``.

    Размер шрифта: ``(font (size ВЫСОТА ШИРИНА))`` — :attr:`font_size_y` — первое число,
    :attr:`font_size_x` — второе. Без ``(size …)`` KiCad подставляет 1.524 мм
    (:data:`DEFAULT_TEXT_SIZE`), так же поступает и getter.
    """

    __slots__ = ()

    def _order(self) -> Sequence[str]:
        return self.profile.text_order

    # --- создание ------------------------------------------------------------------------
    @classmethod
    def new(cls, text: str = "", kind: str = "user", x: float = 0.0, y: float = 0.0,
            layer: str = "F.SilkS", *, angle: float = 0.0,
            size: float | tuple[float, float] = 1.0, thickness: float | None = 0.15,
            hide: bool = False, name: str | None = None, justify: Iterable[str] | None = None,
            profile: FormatProfile | None = None, uuid: bool | str | None = True) -> Text:
        """Новый текст в форме профиля.

        В KiCad 8+ (``profile.text_as_property``) ``reference``/``value`` создаются полями
        ``(property "Reference"|"Value" …)``, ``user`` — ``(fp_text user …)``; ``name`` —
        поле с произвольным именем (только KiCad 8+). В KiCad 5–7 — ``fp_text``.
        ``size`` — число или ``(ширина, высота)``; ``thickness=None`` — без толщины.
        Скрытый (``hide=True``) пользовательский текст в формате KiCad 8+ (версия
        >= 20230620) создаётся скрытым полем ``(property "FieldN" …)`` — KiCad 9 скрытых
        ``fp_text`` не поддерживает (см. :attr:`hide`); при добавлении в корпус имя
        ``FieldN`` уточняется, чтобы не совпасть с имеющимися полями.
        """
        prof = profile or _default_profile()
        k = _check_enum(kind, TEXT_KINDS, "kind")
        s = _check_str(text, "text")
        if name is not None or (prof.text_as_property and k in _FIELD_NAMES):
            if not prof.text_as_property:
                raise ValueError("поле (property) с текстовыми атрибутами есть только в "
                                 "формате KiCad 8+; для KiCad 5–7 используйте fp_text")
            fname = _check_str(name, "name", allow_empty=False) if name is not None \
                else _FIELD_NAMES[k]
            node = Node("property", [Str(fname), Str(s)])
        else:
            node = Node("fp_text", [Sym(k), _text_value_atom(s, prof)])
        order = prof.text_order
        px, py = _check_real(x, "x"), _check_real(y, "y")
        a = _check_real(angle, "angle")
        at_items: list[Any] = [_len(px), _len(py)]
        if a != 0 or prof.bool_style == "yesno":
            at_items.append(_ang(a))
        node.insert(Node("at", at_items), order=order)
        node.insert(Node("layer", [_layer_atom(_check_layer(layer), prof)]), order=order)
        sx, sy = _as_pair(size, "size")
        font = Node("font", [Node("size", [_len(sy), _len(sx)])])
        if thickness is not None:
            font.append(Node("thickness", [_len(_check_real(thickness, "thickness"))]))
        effects = Node("effects", [font])
        node.insert(effects, order=order)
        view = cls(node, prof)
        if justify:
            view.justify = justify
        _add_new_id(node, prof, order, uuid)
        # флаг — после вставки всех узлов: Node.insert не учитывает голые флаги
        if hide:
            _write_bool(node, "hide", True, prof, order)
            # KiCad 8+: скрытый пользовательский текст — скрытое поле «FieldN»
            _hidden_text_to_field(node, prof, None)
        return view

    # --- вид, имя, текст -----------------------------------------------------------------------
    @property
    def is_property(self) -> bool:
        """Узел — поле ``property`` (KiCad 8+), а не ``fp_text``."""
        return self.node.name == "property"

    @property
    def kind(self) -> str:
        """``reference`` | ``value`` | ``user``. Присваивание: у ``fp_text`` меняет первый
        атом; у поля ``reference``/``value`` переименовывают его в ``Reference``/``Value``."""
        if self.is_property:
            return {"Reference": "reference", "Value": "value"}.get(self.name or "", "user")
        a = self.node.atom(0)
        return "user" if a is None else str(a)

    @kind.setter
    def kind(self, value: str) -> None:
        k = _check_enum(value, TEXT_KINDS, "kind")
        if self.is_property:
            if k == "user":
                raise ValueError("вид поля задаётся его именем: присвойте name")
            self.name = _FIELD_NAMES[k]
            return
        if k != self.kind and self._parent is not None:
            # второй Reference/Value KiCad не хранит (см. _field_slot)
            _check_free_slot(self._parent.node, _FIELD_NAMES.get(k), self.node)
        self.node.set_atom(0, Sym(k))

    @property
    def name(self) -> str | None:
        """Имя поля (``"Reference"``, ``"Value"``, ``"Datasheet"`` …) или ``None`` у ``fp_text``."""
        if not self.is_property:
            return None
        a = self.node.atom(0)
        return None if a is None else str(a)

    @name.setter
    def name(self, value: str) -> None:
        if not self.is_property:
            raise ValueError("у fp_text нет имени (имя есть только у полей property)")
        v = _check_str(value, "name", allow_empty=False)
        if v != self.name and self._parent is not None:
            _check_free_slot(self._parent.node, v, self.node)
        self.node.set_atom(0, Str(v))

    def _text_index(self) -> int | None:
        pos = sorted(positional_atoms(self.node))
        return pos[1] if len(pos) > 1 else None

    @property
    def text(self) -> str:
        """Текст (у поля — значение). ``%R``/``%V`` KiCad 5 возвращаются как записаны."""
        i = self._text_index()
        return "" if i is None else str(self.node.items[i])

    @text.setter
    def text(self, value: str) -> None:
        s = _check_str(value, "text")
        atom: Atom = Str(s) if self.is_property else _text_value_atom(s, self.profile)
        i = self._text_index()
        if i is None:
            self.node.set_atom(1, atom)
        else:
            self.node.items[i] = atom

    # --- положение ------------------------------------------------------------------------------
    def _ensure_at(self) -> Node:
        at = self.node.find("at")
        if at is None:
            items: list[Any] = [_len(0.0), _len(0.0)]
            if self.profile.bool_style == "yesno":
                items.append(_ang(0.0))
            at = Node("at", items)
            self.node.insert(at, order=self._order())
        return at

    @property
    def x(self) -> float:
        """X, мм (0.0, если нет ``at``)."""
        p = _xy_of(self.node.find("at"))
        return 0.0 if p is None else p[0]

    @x.setter
    def x(self, value: float) -> None:
        v = _check_real(value, "x")
        at = self._ensure_at()
        _set_xy(at, (v, self.y))

    @property
    def y(self) -> float:
        """Y, мм (ось Y вниз)."""
        p = _xy_of(self.node.find("at"))
        return 0.0 if p is None else p[1]

    @y.setter
    def y(self, value: float) -> None:
        v = _check_real(value, "y")
        at = self._ensure_at()
        _set_xy(at, (self.x, v))

    @property
    def position(self) -> Point:
        """Положение ``(x, y)``."""
        return (self.x, self.y)

    @position.setter
    def position(self, value: Point) -> None:
        p = _as_point(value, "position")
        _set_xy(self._ensure_at(), p)

    @property
    def angle(self) -> float:
        """Угол текста, градусы (0, если атома нет)."""
        return _at_angle(self.node.find("at"))

    @angle.setter
    def angle(self, value: float) -> None:
        a = _check_real(value, "angle")
        at = self.node.find("at")
        always = self.profile.bool_style == "yesno"
        if at is None:
            if a == 0 and not always:
                return
            at = self._ensure_at()
        _set_at_angle(at, a, always=always)

    # --- слой и видимость ------------------------------------------------------------------------
    @property
    def layer(self) -> str | None:
        """Слой ``(layer …)`` или ``None``."""
        v = self.node.value("layer")
        return None if v is None else str(v)

    @layer.setter
    def layer(self, value: str) -> None:
        atom = _layer_atom(_check_layer(value), self.profile)
        ln = self.node.find("layer")
        if ln is None:
            self.node.set("layer", atom, order=self._order())
        else:
            ln.set_atom(0, atom)

    @property
    def hide(self) -> bool:
        """Скрыт ли текст: голый ``hide``/``(hide yes)`` у текста или в ``effects``.

        Скрывать пользовательский ``fp_text`` в формате с полями (версия >= 20230620,
        KiCad 8+) kicadfp не стал: KiCad 9 пишет ``hide`` только у полей и при чтении
        превращает скрытый ``fp_text`` в поле, а kicad-cli 9.0.1 такой текст вовсе теряет
        (в том числе в файле формата KiCad 8). Поэтому ``hide = True`` у такого текста, как
        и KiCad 9, превращает узел в скрытое поле ``(property "FieldN" "текст" … (hide
        yes))`` (``FieldN`` — свободное имя; узел переставляется за последнее поле корпуса,
        представление остаётся над ним, :attr:`kind` — ``user``, :attr:`name` —
        ``FieldN``); скрытое поле читают без потерь и KiCad 8, и KiCad 9. В KiCad 5–7
        полей с текстовыми атрибутами нет — скрытый ``fp_text`` пишется как есть."""
        v = _bool_token(self.node, "hide")
        if v is None:
            eff = self.node.find("effects")
            v = _bool_token(eff, "hide") if eff is not None else None
        return bool(v)

    @hide.setter
    def hide(self, value: bool) -> None:
        v = bool(value)
        eff = self.node.find("effects")
        in_effects = eff is not None and _bool_token(eff, "hide") is not None
        in_node = _bool_token(self.node, "hide") is not None
        if in_effects and not in_node:
            _write_bool(eff, "hide", v, self.profile, EFFECTS_ORDER)  # type: ignore[arg-type]
        else:
            if in_effects:
                _drop_bool(eff, "hide")  # type: ignore[arg-type]
            _write_bool(self.node, "hide", v, self.profile, self._order())
        if v:
            root = self._parent.node if self._parent is not None else None
            _hidden_text_to_field(self.node, self.profile, root)

    @property
    def visible(self) -> bool:
        """``not hide``."""
        return not self.hide

    @property
    def unlocked(self) -> bool | None:
        """«Не держать вертикально» (KiCad: ``!KeepUpright``): голый ``unlocked`` в ``(at …)``
        (KiCad 5–7) или ``(unlocked yes|no)`` (8+); ``None`` — токена нет (текст держится
        вертикально). Присваивание ``False``/``None`` удаляет токен."""
        at = self.node.find("at")
        if at is not None and at.has_flag("unlocked"):
            return True
        return _bool_token(self.node, "unlocked")

    @unlocked.setter
    def unlocked(self, value: bool | None) -> None:
        v = bool(value)
        at = self.node.find("at")
        if v and self.unlocked is True:
            return
        if at is not None:
            at.set_flag("unlocked", False)
        self.node.set_flag("unlocked", False)
        self.node.remove("unlocked")
        if not v:
            return
        if self.profile.bool_style == "yesno":
            self.node.set("unlocked", Sym("yes"), order=self._order())
        else:
            self._ensure_at().set_flag("unlocked", True)

    @property
    def knockout(self) -> bool:
        """Инверсный текст: голый ``knockout`` в ``(layer … knockout)`` (KiCad 7+, формат
        20220308; в более старом формате включение — ``ValueError``)."""
        ln = self.node.find("layer")
        return ln is not None and ln.has_flag("knockout")

    @knockout.setter
    def knockout(self, value: bool) -> None:
        ln = self.node.find("layer")
        if ln is None:
            if not value:
                return
            raise ValueError("knockout задаётся в (layer …), а слоя у текста нет")
        if value and not ln.has_flag("knockout"):
            _require_version(self.profile, _V_KNOCKOUT, "knockout")
        ln.set_flag("knockout", bool(value))

    @property
    def locked(self) -> bool:
        """Блокировка ``fp_text``: голый ``locked`` между видом и текстом (KiCad 6/7) или
        ``(locked yes)`` (8+). У полей KiCad её не хранит. Флаг появился в версии 20210925
        («Locked flag for fp_text»): установка в файле более старой версии (в том числе
        KiCad 5 ``module``) — ``ValueError``."""
        return bool(_bool_token(self.node, "locked"))

    @locked.setter
    def locked(self, value: bool) -> None:
        if value and _bool_token(self.node, "locked") is None:
            _require_version(self.profile, _V_TEXT_LOCKED, "locked у текста")
        _write_bool(self.node, "locked", bool(value), self.profile, self._order())

    @property
    def uuid(self) -> str | None:
        """Идентификатор ``(uuid "…")`` / ``(tstamp …)`` или ``None``."""
        return _get_id(self.node)

    @uuid.setter
    def uuid(self, value: str | None) -> None:
        _set_id(self.node, value, self.profile, self._order())

    # --- шрифт ------------------------------------------------------------------------------------
    def _effects(self, create: bool = False) -> Node | None:
        eff = self.node.find("effects")
        if eff is None and create:
            eff = Node("effects")
            _insert_node(self.node, eff, self._order())
        return eff

    def _font(self, create: bool = False) -> Node | None:
        eff = self._effects(create)
        if eff is None:
            return None
        font = eff.find("font")
        if font is None and create:
            font = Node("font")
            eff.insert(font, order=EFFECTS_ORDER)
        return font

    def _font_size(self, i: int) -> float:
        font = self._font()
        v = None if font is None else font.number("size", i)
        return DEFAULT_TEXT_SIZE if v is None else v

    def _set_font_size(self, i: int, value: float) -> None:
        v = _check_real(value, "font_size")
        font = self._font(create=True)
        size = font.find("size")  # type: ignore[union-attr]
        if size is None:
            vals = [DEFAULT_TEXT_SIZE, DEFAULT_TEXT_SIZE]
            vals[i] = v
            font.set("size", _len(vals[0]), _len(vals[1]), order=FONT_ORDER)  # type: ignore[union-attr]
        else:
            size.set_atom(i, _len(v))

    @property
    def font_size_x(self) -> float:
        """Ширина символа, мм (второе число ``(size H W)``; без токена — 1.524)."""
        return self._font_size(1)

    @font_size_x.setter
    def font_size_x(self, value: float) -> None:
        self._set_font_size(1, value)

    @property
    def font_size_y(self) -> float:
        """Высота символа, мм (первое число ``(size H W)``; без токена — 1.524)."""
        return self._font_size(0)

    @font_size_y.setter
    def font_size_y(self, value: float) -> None:
        self._set_font_size(0, value)

    @property
    def font_size(self) -> tuple[float, float]:
        """Размер шрифта ``(ширина, высота)``; присваивание — число или пара."""
        return (self.font_size_x, self.font_size_y)

    @font_size.setter
    def font_size(self, value: float | tuple[float, float]) -> None:
        w, h = _as_pair(value, "font_size")
        font = self._font(create=True)
        size = font.find("size")  # type: ignore[union-attr]
        if size is None:
            font.set("size", _len(h), _len(w), order=FONT_ORDER)  # type: ignore[union-attr]
        else:
            _set_xy(size, (h, w))

    @property
    def thickness(self) -> float | None:
        """Толщина линий шрифта, мм, или ``None`` (нет токена — KiCad считает сам)."""
        font = self._font()
        return None if font is None else font.number("thickness")

    @thickness.setter
    def thickness(self, value: float | None) -> None:
        if value is None:
            font = self._font()
            if font is not None:
                font.remove("thickness")
            return
        v = _len(_check_real(value, "thickness"))
        self._font(create=True).set("thickness", v, order=FONT_ORDER)  # type: ignore[union-attr]

    @property
    def face(self) -> str | None:
        """Имя шрифта ``(face "…")`` (KiCad 7+, формат 20211232; в более старом формате
        присваивание — ``ValueError``) или ``None`` (штриховой шрифт KiCad)."""
        font = self._font()
        v = None if font is None else font.value("face")
        return None if v is None else str(v)

    @face.setter
    def face(self, value: str | None) -> None:
        if value is None:
            font = self._font()
            if font is not None:
                font.remove("face")
            return
        if self.face is None:
            _require_version(self.profile, _V_FONTS, "font face")
        self._font(create=True).set("face", Str(_check_str(value, "face")),  # type: ignore[union-attr]
                                    order=FONT_ORDER)

    @property
    def bold(self) -> bool:
        """Полужирный: голый ``bold`` (KiCad 5–7) или ``(bold yes)`` (8+)."""
        font = self._font()
        return bool(font is not None and _bool_token(font, "bold"))

    @bold.setter
    def bold(self, value: bool) -> None:
        font = self._font(create=bool(value))
        if font is not None:
            _write_bool(font, "bold", bool(value), self.profile, FONT_ORDER)

    @property
    def italic(self) -> bool:
        """Курсив: голый ``italic`` (KiCad 5–7) или ``(italic yes)`` (8+)."""
        font = self._font()
        return bool(font is not None and _bool_token(font, "italic"))

    @italic.setter
    def italic(self, value: bool) -> None:
        font = self._font(create=bool(value))
        if font is not None:
            _write_bool(font, "italic", bool(value), self.profile, FONT_ORDER)

    @property
    def justify(self) -> list[str]:
        """Выравнивание ``(justify …)``: подмножество ``left``/``right``, ``top``/``bottom``,
        ``mirror`` (пусто — по центру, без зеркала). Присваивание пишет значения в порядке
        KiCad; пустой список удаляет ``(justify …)``."""
        eff = self._effects()
        j = None if eff is None else eff.find("justify")
        return [] if j is None else [str(a) for a in j.atoms()]

    @justify.setter
    def justify(self, value: Iterable[str] | str | None) -> None:
        if value is None:
            vals: set[str] = set()
        else:
            if isinstance(value, str):
                value = value.replace(",", " ").split()
            vals = {_check_enum(v, JUSTIFY_VALUES, "justify") for v in value}
        if {"left", "right"} <= vals or {"top", "bottom"} <= vals:
            raise ValueError("justify: взаимоисключающие значения (left/right или top/bottom)")
        if not vals:
            eff = self._effects()
            if eff is not None:
                eff.remove("justify")
            return
        eff = self._effects(create=True)
        eff.set("justify", *[Sym(v) for v in JUSTIFY_VALUES if v in vals],  # type: ignore[union-attr]
                order=EFFECTS_ORDER)

    @property
    def mirror(self) -> bool:
        """Зеркальный текст (``mirror`` в ``justify``)."""
        return "mirror" in self.justify

    @mirror.setter
    def mirror(self, value: bool) -> None:
        cur = self.justify
        if bool(value) == ("mirror" in cur):
            return
        self.justify = (cur + ["mirror"]) if value else [v for v in cur if v != "mirror"]

    # --- преобразования ----------------------------------------------------------------------------
    def move(self, dx: float, dy: float) -> None:
        """Сдвинуть текст на ``(dx, dy)``."""
        dx, dy = _check_real(dx, "dx"), _check_real(dy, "dy")
        if dx == 0 and dy == 0:
            return
        x, y = self.position
        self.position = (x + dx, y + dy)

    def rotate(self, angle: float, origin: Point = (0.0, 0.0)) -> None:
        """Повернуть на ``angle`` вокруг ``origin``: положение и угол текста (как
        ``PCB_TEXT::Rotate``; угол нормализуется в [0, 360))."""
        a = _check_real(angle, "angle")
        o = _as_point(origin, "origin")
        if a == 0:
            return
        new_pos = _geo.rotate_point(self.position, a, o)
        if new_pos != self.position:
            self.position = new_pos
        self.angle = _norm360(self.angle + a)

    def _flip_x(self) -> None:
        """Часть :meth:`Footprint.flip` (``PCB_TEXT::Flip`` LEFT_RIGHT): ``x -> -x``, угол
        ``-a``, слой на другую сторону, у текста на слое одной стороны переключается
        ``mirror``."""
        if self.node.find("at") is not None:
            if self.x != 0:
                self.x = -self.x
            if self.angle != 0:
                self.angle = _norm360(-self.angle)
        layer = self.layer
        if layer is not None:
            flipped = _L.flip_layer(layer)
            if flipped != layer:
                self.layer = flipped
        if _is_side_specific(layer):
            self.mirror = not self.mirror

    def __repr__(self) -> str:
        who = self.name if self.is_property else self.kind
        return f"Text({who!r}, {self.text!r}, at=({self.x:g}, {self.y:g}), layer={self.layer!r})"


# ---------------------------------------------------------------------------
# Model (3D-модель)
# ---------------------------------------------------------------------------

class Model(View):
    """3D-модель: ``(model "путь" [hide] [(opacity …)] (offset (xyz …)) (scale (xyz …))
    (rotate (xyz …)))``.

    ``offset`` — смещение, мм (ось Y — вверх, как в 3D-окне KiCad). Старая форма KiCad 5
    ``(at (xyz …))`` хранит смещение в **дюймах**: getter умножает на 25.4 ровно как парсер
    KiCad — на константу ``float`` 25.4f (25.399999618530273), поэтому ``(at (xyz 0.16 0 0))``
    читается как 4.063999939 мм, как в KiCad; setter сохраняет узел ``at`` и пишет значение,
    делённое на тот же множитель; новый узел создаётся как ``offset``. Числа пишутся как
    ``FormatDouble2Str`` (``format_double``), ``opacity`` — ``%0.4f``, как KiCad.
    Имя ``rotate`` занято поворотом модели (по контракту), поэтому метода поворота у модели
    нет — см. :meth:`Footprint.rotate`.
    """

    __slots__ = ()

    def _order(self) -> Sequence[str]:
        return MODEL_ORDER

    @classmethod
    def new(cls, path: str, *, offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
            scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
            rotate: tuple[float, float, float] = (0.0, 0.0, 0.0), hide: bool = False,
            opacity: float | None = None, profile: FormatProfile | None = None) -> Model:
        """Новая модель (``offset``/``scale``/``rotate`` пишутся всегда, как в KiCad)."""
        prof = profile or _default_profile()
        node = Node("model", [_str_atom(_check_str(path, "path", allow_empty=False), prof)])
        view = cls(node, prof)
        if hide:
            view.hide = True
        if opacity is not None:
            view.opacity = opacity
        for name, vals in (("offset", offset), ("scale", scale), ("rotate", rotate)):
            xyz = _as_xyz(vals, name)
            node.insert(Node(name, [Node("xyz", [_dbl(v) for v in xyz])]), order=MODEL_ORDER)
        return view

    @property
    def path(self) -> str:
        """Путь к файлу модели (с переменными вида ``${KICAD9_3DMODEL_DIR}``)."""
        a = self.node.atom(0)
        return "" if a is None else str(a)

    @path.setter
    def path(self, value: str) -> None:
        self.node.set_atom(0, _str_atom(_check_str(value, "path", allow_empty=False),
                                        self.profile))

    @property
    def hide(self) -> bool:
        """Скрыта ли модель: голый ``hide`` после пути (KiCad 6/7) или ``(hide yes)`` (8+).
        В KiCad 5 (``module``) флага нет — установка — ``ValueError``."""
        return bool(_bool_token(self.node, "hide"))

    @hide.setter
    def hide(self, value: bool) -> None:
        if value and _bool_token(self.node, "hide") is None:
            _require_version(self.profile, _V_FOOTPRINT_ROOT, "hide у 3D-модели")
        _write_bool(self.node, "hide", bool(value), self.profile, MODEL_ORDER)

    @property
    def opacity(self) -> float | None:
        """Непрозрачность 0..1 или ``None`` (нет токена = 1). Новый токен — с версии
        20210824; в файле более старой версии — ``ValueError``."""
        return self.node.number("opacity")

    @opacity.setter
    def opacity(self, value: float | None) -> None:
        if value is None:
            self.node.remove("opacity")
            return
        v = _check_real(value, "opacity")
        if not 0.0 <= v <= 1.0:
            raise ValueError("opacity: ожидается число от 0 до 1")
        if self.node.find("opacity") is None:
            _require_version(self.profile, _V_OPACITY, "opacity")
        self.node.set("opacity", Sym("%.4f" % v), order=MODEL_ORDER)

    def _xyz(self, name: str) -> tuple[float, float, float] | None:
        n = self.node.find(name)
        xyz = None if n is None else n.find("xyz")
        if xyz is None:
            return None
        vals = [_num(xyz.atom(i)) for i in range(3)]
        return tuple(0.0 if v is None else v for v in vals)  # type: ignore[return-value]

    def _set_xyz(self, name: str, vals: tuple[float, float, float]) -> None:
        n = self.node.find(name)
        if n is None:
            self.node.insert(Node(name, [Node("xyz", [_dbl(v) for v in vals])]), order=MODEL_ORDER)
            return
        xyz = n.find("xyz")
        if xyz is None:
            n.append(Node("xyz", [_dbl(v) for v in vals]))
            return
        for i, v in enumerate(vals):
            old = _num(xyz.atom(i))
            if old is not None and old == v:
                continue
            xyz.set_atom(i, _dbl(v))

    @property
    def uses_inch_offset(self) -> bool:
        """Смещение задано старой формой ``(at (xyz …))`` в дюймах (KiCad 5)."""
        return self.node.find("offset") is None and self.node.find("at") is not None

    @property
    def offset(self) -> tuple[float, float, float]:
        """Смещение ``(x, y, z)``, мм (из ``(at …)`` — пересчитанное из дюймов)."""
        v = self._xyz("offset")
        if v is not None:
            return v
        v = self._xyz("at")
        if v is not None:
            return tuple(c * _INCH_KICAD for c in v)  # type: ignore[return-value]
        return (0.0, 0.0, 0.0)

    @offset.setter
    def offset(self, value: tuple[float, float, float]) -> None:
        vals = _as_xyz(value, "offset")
        if self.uses_inch_offset:
            old = self._xyz("at") or (0.0, 0.0, 0.0)
            # неизменные координаты не трогаем (деление/умножение на 25.4f не обратимо точно)
            cur = tuple(c * _INCH_KICAD for c in old)
            new = tuple(o if abs(n - c) < 1e-12 else n / _INCH_KICAD
                        for o, n, c in zip(old, vals, cur))
            self._set_xyz("at", new)  # type: ignore[arg-type]
        else:
            self._set_xyz("offset", vals)

    @property
    def scale(self) -> tuple[float, float, float]:
        """Масштаб ``(x, y, z)`` (по умолчанию ``(1, 1, 1)``)."""
        return self._xyz("scale") or (1.0, 1.0, 1.0)

    @scale.setter
    def scale(self, value: tuple[float, float, float]) -> None:
        self._set_xyz("scale", _as_xyz(value, "scale"))

    @property
    def rotate(self) -> tuple[float, float, float]:
        """Поворот ``(x, y, z)``, градусы (по умолчанию нули)."""
        return self._xyz("rotate") or (0.0, 0.0, 0.0)

    @rotate.setter
    def rotate(self, value: tuple[float, float, float]) -> None:
        self._set_xyz("rotate", _as_xyz(value, "rotate"))

    def __repr__(self) -> str:
        return f"Model({self.path!r}, offset={self.offset}, scale={self.scale}, rotate={self.rotate})"


# ---------------------------------------------------------------------------
# Приведение узлов к профилю (Footprint.add, Footprint.upgrade)
# ---------------------------------------------------------------------------

#: Элементы корпуса, у которых KiCad 6+ хранит идентификатор (uuid/tstamp).
_ID_ELEMENTS = frozenset((
    "pad", "fp_text", "fp_text_box", "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly",
    "fp_curve", "image", "dimension", "table", "zone", "point", "barcode",
))
_HEX8 = frozenset("0123456789abcdefABCDEF")


def _uuid_from_text(value: str) -> str:
    """Текст идентификатора для ``(uuid …)``: 8 hex-цифр (метка времени KiCad 5) KiCad
    превращает в ``00000000-0000-0000-0000-0000XXXXXXXX`` (``KIID`` из legacy timestamp)."""
    if len(value) == 8 and all(c in _HEX8 for c in value):
        return "00000000-0000-0000-0000-0000" + value.lower()
    return value


def _convert_id(node: Node, dst: FormatProfile, order: Sequence[str] | None, *,
                required: bool) -> None:
    """Идентификатор элемента в форме ``dst``: ``(uuid "…")`` (8+) / ``(tstamp …)`` (6/7);
    в KiCad 5 (``module``) у элементов библиотеки идентификаторов нет — удаляется.
    ``required`` — добавить новый ``uuid4``, если идентификатора не было."""
    idn = _id_node(node)
    if dst.root == "module":
        if idn is not None:
            node.remove("uuid")
            node.remove("tstamp")
        return
    if idn is None:
        if required:
            _add_new_id(node, dst, order, True)
        return
    a = idn.atom(0)
    value = "" if a is None else str(a)
    if not value:
        value = _new_uuid()
    token = dst.uuid_token
    if token == "uuid":
        value = _uuid_from_text(value)
    if idn.name != token:
        idn.name = token
    new = _id_atom(token, value)
    if a is None or type(a) is not type(new) or str(a) != value:
        idn.items = [new]


def _requote_layers(node: Node, dst: FormatProfile) -> None:
    """Имена слоёв во всех ``(layer …)``/``(layers …)`` узла (на любой глубине) — в форме
    ``dst``: KiCad 5 — голые, KiCad 6 — в кавычках, но групповые обозначения в ``layers``
    голые, KiCad 7+ — всё в кавычках. В ``(layer …)`` меняется только имя (``knockout``
    остаётся)."""
    for ln in _deep_layer_nodes(node):
        if ln.name == "layer":
            for i, x in enumerate(ln.items):
                if not isinstance(x, Node):
                    new = _layer_atom(str(x), dst)
                    if type(new) is not type(x):
                        ln.items[i] = new
                    break
        else:
            for i, x in enumerate(ln.items):
                if not isinstance(x, Node):
                    new = _layer_atom(str(x), dst, in_list=True)
                    if type(new) is not type(x):
                        ln.items[i] = new


def _move_bool(node: Node, name: str, dst: FormatProfile, order: Sequence[str] | None) -> bool | None:
    """Прочитать булев токен в любой форме, удалить его и записать заново в форме ``dst``
    (только истинное значение — как пишет KiCad). Возвращает прочитанное значение."""
    v = _bool_token(node, name)
    if v is None:
        return None
    _drop_bool(node, name)
    if v:
        _write_bool(node, name, True, dst, order)
    return v


def _convert_font(node: Node, dst: FormatProfile) -> None:
    """``bold``/``italic`` в ``(effects (font …))`` — в форме ``dst``. Для KiCad 9+ текст без
    ``(thickness …)`` получает ``(thickness 0.15)``: KiCad 9 создаёт тексты с толщиной
    ``DEFAULT_TEXT_WIDTH`` (0.15 мм), и при чтении без токена она остаётся, а при записи
    ненулевая толщина пишется всегда."""
    eff = node.find("effects")
    font = None if eff is None else eff.find("font")
    if font is None:
        return
    for flag in ("bold", "italic"):
        _move_bool(font, flag, dst, FONT_ORDER)
    if dst.version >= V_FILL_YESNO and font.find("thickness") is None:
        font.insert(Node("thickness", [_len(0.15)]), order=FONT_ORDER)


_KICAD_FIELD_NAMES = frozenset(("Reference", "Value", "Footprint", "Datasheet", "Description"))


def _is_auto_field_name(name: str) -> bool:
    """Имя вида ``FieldN`` — так KiCad (``GetUserFieldName``) называет поля без имени."""
    return name.startswith("Field") and name[5:].isdigit()


def _free_field_name(root: Node | None, exclude: Node | None = None) -> str:
    """Имя нового пользовательского поля, как у KiCad 9 (``GetUserFieldName(
    GetFields().size())``: пять обязательных полей в памяти плюс прочие поля корпуса), с
    гарантией уникальности среди полей ``root``."""
    names: set[str] = set()
    user = 0
    for n in [] if root is None else root.nodes("property"):
        if n is exclude:
            continue
        name = str(n.atom(0) or "")
        names.add(name)
        if name not in _KICAD_FIELD_NAMES:
            user += 1
    i = len(_KICAD_FIELD_NAMES) + user
    while f"Field{i}" in names:
        i += 1
    return f"Field{i}"


def _move_after_fields(root: Node, node: Node) -> None:
    """Переставить ``node`` (поле) сразу за последним полем ``property`` корпуса."""
    try:
        root.items.remove(node)
    except ValueError:
        return
    last = -1
    for i, x in enumerate(root.items):
        if isinstance(x, Node) and x.name == "property":
            last = i
    if last < 0:
        insert_in_group(root, node)
    else:
        root.items.insert(last + 1, node)


def _hidden_text_to_field(node: Node, prof: FormatProfile, root: Node | None) -> bool:
    """Скрытый пользовательский ``fp_text`` в формате с полями (версия >= 20230620, KiCad
    8+) — в скрытое поле ``(property "FieldN" "текст" … (hide yes) …)``, как это делает
    парсер KiCad 9 (``parsePCB_TEXT``: «Convert hidden footprint text (which is no longer
    supported) into a hidden field»): writer KiCad 9 пишет ``hide`` только у полей, а
    kicad-cli 9.0.1 скрытый ``fp_text`` при чтении теряет — и в файлах формата KiCad 8;
    скрытое поле читают без потерь и KiCad 8, и KiCad 9. Имя поля — свободное ``FieldN``
    среди полей ``root``; блокировку поле не хранит. Узел меняется на месте; если он входит
    в ``root``, он переставляется за последнее поле. Возвращает, было ли преобразование."""
    if node.name != "fp_text" or prof.version < _V_HIDDEN_FIELD:
        return False
    if str(node.atom(0) or "") != "user":
        return False
    hidden = bool(_bool_token(node, "hide"))
    eff = node.find("effects")
    if eff is not None and _bool_token(eff, "hide"):
        hidden = True
        _drop_bool(eff, "hide")
    if not hidden:
        return False
    text = Text(node, prof).text
    _drop_bool(node, "locked")
    _drop_bool(node, "hide")
    name = _free_field_name(root, exclude=node)
    node.name = "property"
    node.items = [Str(name), Str(text)] + node.nodes()  # type: ignore[list-item]
    order = prof.text_order
    _write_bool(node, "hide", True, prof, order)
    _reorder(node, order)
    if root is not None and any(x is node for x in root.items):
        _move_after_fields(root, node)
    return True


def _convert_text_node(node: Node, dst: FormatProfile) -> None:
    """``fp_text``/``property`` — в форму ``dst`` (см. :meth:`Footprint.upgrade`).

    ``fp_text reference/value`` в KiCad 8+ становится полем ``(property "Reference"|"Value"
    …)``, поле KiCad 8+ в KiCad 6/7 — ``fp_text`` (Reference/Value) или «голым» свойством
    ``(property "имя" "значение")`` без текстовых атрибутов (их KiCad 6/7 не хранит).
    Флаги ``locked``/``hide``/``unlocked``/``bold``/``italic``, угол в ``(at …)``,
    идентификатор, кавычки слоя и ``%R``/``%V`` (→ ``${REFERENCE}``/``${VALUE}``, как их
    переводит парсер KiCad 6+) приводятся к ``dst``; порядок дочерних токенов — по
    таблице ``dst.text_order``."""
    order = dst.text_order
    view = Text(node, dst)
    kind = view.kind
    text = view.text
    locked = _bool_token(node, "locked")
    if locked is not None:
        _drop_bool(node, "locked")
    hide = _bool_token(node, "hide")
    if hide is not None:
        _drop_bool(node, "hide")
    eff = node.find("effects")
    if eff is not None:
        eh = _bool_token(eff, "hide")
        if eh is not None:
            _drop_bool(eff, "hide")
            hide = bool(hide) or eh
    at = node.find("at")
    unlocked: bool | None = None
    if at is not None and at.has_flag("unlocked"):
        unlocked = True
        at.set_flag("unlocked", False)
    un = _bool_token(node, "unlocked")
    if un is not None:
        _drop_bool(node, "unlocked")
        unlocked = bool(unlocked) or un
    if dst.root != "module" and ("%R" in text or "%V" in text):
        text = text.replace("%V", "${VALUE}").replace("%R", "${REFERENCE}")
    subnodes = node.nodes()
    if node.name == "fp_text" and dst.text_as_property and kind in _FIELD_NAMES:
        node.name = "property"
        node.items = [Str(_FIELD_NAMES[kind]), Str(text)] + subnodes  # type: ignore[list-item]
        locked = None  # у полей KiCad блокировку не хранит
    elif node.name == "property" and not dst.text_as_property:
        name = view.name or ""
        if name in ("Reference", "Value"):
            node.name = "fp_text"
            node.items = [Sym(kind), _text_value_atom(text, dst)] + subnodes  # type: ignore[list-item]
        else:
            node.items = [Str(name), Str(text)]
            return
    elif node.name == "fp_text":
        i = view._text_index()
        if i is not None:
            node.items[i] = _text_value_atom(text, dst)
    else:
        i = view._text_index()
        if i is not None and str(node.items[i]) != text:
            node.items[i] = Str(text)
    at = node.find("at")
    if at is not None:
        a = _at_angle(at)
        if dst.version >= V_FILL_YESNO:
            # KiCad 9 при чтении поворачивает текст на ориентацию корпуса (PCB_TEXT::Rotate),
            # что нормализует угол в [0, 360): -90 записывается как 270
            a = _norm360(a)
        _set_at_angle(at, a, always=dst.bool_style == "yesno")
    _requote_layers(node, dst)
    _convert_font(node, dst)
    if locked and node.name == "fp_text":
        _write_bool(node, "locked", True, dst, order)
    if hide:
        _write_bool(node, "hide", True, dst, order)
    if unlocked:
        if dst.bool_style == "yesno":
            node.set("unlocked", Sym("yes"), order=order)
        elif at is not None:
            at.set_flag("unlocked", True)
    _convert_id(node, dst, order, required=True)
    _reorder(node, order)


def _convert_graphic_node(node: Node, src: FormatProfile, dst: FormatProfile) -> None:
    """Фигура ``fp_*`` или примитив ``gr_*`` — в форму ``dst``: дуги (центр/угол ↔
    start/mid/end), ``(width)`` ↔ ``(stroke (width) (type solid))`` (примитивы всегда
    ``width``), слова ``fill`` (и явная заливка вместо умолчания парсера — KiCad 6+ пишет
    ``fill`` у rect/circle/poly всегда), ``locked``, кавычки слоя, идентификатор, порядок
    токенов."""
    cls = _GRAPHIC_CLASSES.get(node.name)
    if cls is None:
        return
    view = cls(node, src)
    kind = view.kind
    primitive = view.is_primitive
    eff_fill = view.fill if kind in _FILL_KINDS else None
    had_fill = node.find("fill") is not None
    # формат KiCad 5 (< 20201114) токена fill не знает: заливку по умолчанию парсера
    # выражает его отсутствие
    drop_fill = (dst.version < _V_FILL and eff_fill is not None
                 and eff_fill == _parser_default_fill(kind, view.width, view.layer))
    if kind == "arc":
        three = _arc_three(node)
        if three is not None:
            if dst.arc_mid and _arc_is_legacy(node):
                _arc_write_modern(node, *three)
            elif not dst.arc_mid and not _arc_is_legacy(node):
                _arc_write_legacy(node, *three)
    if primitive:
        if drop_fill:
            node.remove("fill")
        elif eff_fill is not None and (had_fill or dst.root != "module"):
            node.set("fill", Sym(_fill_word(eff_fill, dst, True)), order=_PRIMITIVE_ORDER)
        return
    order = dst.graphic_order
    locked = _bool_token(node, "locked")
    if locked is not None:
        _drop_bool(node, "locked")
    st = node.find("stroke")
    wn = node.find("width")
    if dst.stroke and st is None and wn is not None:
        w = wn.atom(0)
        node.remove("width")
        node.insert(Node("stroke", [Node("width", [w if w is not None else _len(0.0)]),
                                    Node("type", [Sym("solid")])]), order=order)
    elif not dst.stroke and st is not None:
        w = st.value("width")
        node.remove("stroke")
        if w is not None and wn is None:
            node.insert(Node("width", [w]), order=order)
    if drop_fill:
        node.remove("fill")
    elif eff_fill is not None and (had_fill or dst.root != "module"):
        node.set("fill", Sym(_fill_word(eff_fill, dst, False)), order=order)
    _requote_layers(node, dst)
    if locked:
        _write_bool(node, "locked", True, dst, order)
    _convert_id(node, dst, order, required=True)
    _reorder(node, order)


def _convert_pad_node(node: Node, src: FormatProfile, dst: FormatProfile) -> None:
    """Площадка — в форму ``dst``: номер (кавычки), ``locked`` (голый в 6/7; KiCad 8+ его
    не хранит — удаляется), ``remove_unused_layers``/``keep_end_layers`` (``(x)`` в 6/7,
    ``(x yes|no)`` в 8+, у ``thru_hole`` KiCad 8+ пишет всегда), ``thermal_width`` ↔
    ``thermal_bridge_width``, кавычки слоёв, примитивы, идентификатор."""
    a0 = node.atom(0)
    if a0 is not None:
        new = _str_atom(str(a0), dst)
        if type(new) is not type(a0):
            node.set_atom(0, new)
    locked = _bool_token(node, "locked")
    if locked is not None:
        _drop_bool(node, "locked")
        if locked and dst.bool_style == "flag":
            node.set_flag("locked", True, order=PAD_ORDER)
    rul = _bool_token(node, "remove_unused_layers")
    kel = _bool_token(node, "keep_end_layers")
    for name in ("remove_unused_layers", "keep_end_layers"):
        _drop_bool(node, name)
    pad_type = str(node.atom(1) or "")
    if dst.bool_style == "yesno":
        if pad_type == "thru_hole":
            node.set("remove_unused_layers", Sym("yes" if rul else "no"), order=PAD_ORDER)
            if rul:
                node.set("keep_end_layers", Sym("yes" if kel else "no"), order=PAD_ORDER)
    elif rul:
        node.set("remove_unused_layers", order=PAD_ORDER)
        if kel:
            node.set("keep_end_layers", order=PAD_ORDER)
    new_style = dst.root != "module" and dst.version > _V_THERMAL_BRIDGE
    old_name, new_name = ("thermal_width", "thermal_bridge_width") if new_style else \
        ("thermal_bridge_width", "thermal_width")
    tn = node.find(old_name)
    if tn is not None and node.find(new_name) is None:
        tn.name = new_name
    _requote_layers(node, dst)
    prims = node.find("primitives")
    if prims is not None:
        for g in prims.nodes():
            _convert_graphic_node(g, src, dst)
    _convert_id(node, dst, PAD_ORDER, required=True)


def _upgrade_pad_semantics(node: Node, src_version: int, dst: FormatProfile) -> None:
    """Правки площадки, которые делает парсер KiCad 9 при чтении (``parsePAD``) и которые
    поэтому появляются при пересохранении: номер у ``np_thru_hole`` и у площадок без
    слоёв меди (апертур) стирается (``PAD::CanHaveNumber``); у custom-площадки с круглым
    якорем из файла KiCad 5/6 без ``thermal_bridge_angle`` угол спиц — 90° (умолчание
    записи для неё — 45°, поэтому KiCad 7+ пишет ``(thermal_bridge_angle 90)``)."""
    view = Pad(node, dst)
    if view.number and (view.type == "np_thru_hole"
                        or not any(_L.is_copper(x) for x in _L.expand(view.layers))):
        view.number = ""
    if (src_version <= 20211014 < dst.version and view.shape == "custom"
            and view.anchor == "circle" and node.find("thermal_bridge_angle") is None):
        node.set("thermal_bridge_angle", _ang(90.0), order=PAD_ORDER)


def _convert_model_node(node: Node, dst: FormatProfile) -> None:
    """3D-модель — в форму ``dst``: путь (кавычки), ``hide``, ``(at (xyz …))`` в дюймах →
    ``(offset (xyz …))`` в мм (KiCad 6+ пишет только ``offset``)."""
    a0 = node.atom(0)
    if a0 is not None:
        new = _str_atom(str(a0), dst)
        if type(new) is not type(a0):
            node.set_atom(0, new)
    _move_bool(node, "hide", dst, MODEL_ORDER)
    if dst.root != "module" and node.find("offset") is None:
        at = node.find("at")
        xyz = None if at is None else at.find("xyz")
        if at is not None and xyz is not None:
            vals = [_num(xyz.atom(i)) or 0.0 for i in range(3)]
            at.name = "offset"
            xyz.items = [_dbl(v * _INCH_KICAD) for v in vals]


def _convert_group_node(node: Node, dst: FormatProfile) -> None:
    """Группа: ``(group "имя" [locked] (id UUID) (members UUID …))`` (KiCad 6/7) ↔
    ``(group "имя" (uuid "UUID") [(locked yes)] (members "UUID" …))`` (8+)."""
    use_uuid = dst.root != "module" and dst.version >= _V_GROUP_UUID
    idn = node.find("uuid")
    if idn is None:
        idn = node.find("id")
    if idn is not None:
        val = str(idn.atom(0) or _new_uuid())
        idn.name = "uuid" if use_uuid else "id"
        idn.items = [Str(val) if use_uuid else Sym(val)]
    members = node.find("members")
    if members is not None:
        members.items = [(Str(str(a)) if use_uuid else Sym(str(a))) if not isinstance(a, Node)
                         else a for a in members.items]
    locked = _bool_token(node, "locked")
    if locked is not None:
        _drop_bool(node, "locked")
        if locked:
            if dst.bool_style == "yesno":
                node.set("locked", Sym("yes"), order=("uuid", "id", "locked", "members"))
            else:
                node.set_flag("locked", True, order=("locked", "uuid", "id", "members"), skip=1)


def _contains(root: Node, node: Node) -> bool:
    """Входит ли ``node`` (по идентичности) в дерево ``root`` на любой глубине."""
    stack = [root]
    while stack:
        n = stack.pop()
        for x in n.items:
            if isinstance(x, Node):
                if x is node:
                    return True
                stack.append(x)
    return False


def _unsupported_constructs(node: Node, src: FormatProfile, dst: FormatProfile) -> list[str]:
    """Конструкции элемента ``node`` (в форме ``src``), которых нет в формате ``dst`` и
    которые приведение формы (:func:`_convert_element`) не переводит: ``fp_rect`` и
    заливка, отличная от умолчания парсера, в KiCad 5; ``knockout`` (< 20220308); ``face``
    (< 20211232); ``thermal_bridge_angle`` (< 20211227); у площадки ``locked``
    (< 20210108), ``pinfunction`` (< 20191123), ``pintype`` (< 20210126), ``property``
    (< 20200104); ``locked`` у фигуры (KiCad 5) и у текста (< 20210925); ``hide`` (KiCad 5)
    и ``opacity`` (< 20210824) у 3D-модели; свойство корпуса ``(property "к" "з")``
    (< 20200808)."""
    v = dst.version
    out: list[str] = []
    stack = [node]
    while stack:
        n = stack.pop()
        name = n.name
        if name == "pad":
            if v < _V_PAD_LOCKED and _bool_token(n, "locked"):
                out.append("locked у площадки")
            if v < _V_PINFUNCTION and n.find("pinfunction") is not None:
                out.append("pinfunction")
            if v < _V_PINTYPE and n.find("pintype") is not None:
                out.append("pintype")
            if v < _V_PAD_PROPERTY and n.find("property") is not None:
                out.append("property площадки")
        elif name in _FP_GRAPHIC_KIND:
            if v < _V_FOOTPRINT_ROOT and _bool_token(n, "locked"):
                out.append("locked у фигуры")
        elif name in ("fp_text", "property") and n is node:
            if v < _V_TEXT_LOCKED and _bool_token(n, "locked"):
                out.append("locked у текста")
            if name == "property" and not _is_text_property(n) and v < _V_FP_PROPERTY:
                out.append("property корпуса")
        elif name == "model":
            if v < _V_FOOTPRINT_ROOT and _bool_token(n, "hide"):
                out.append("hide у 3D-модели")
            if v < _V_OPACITY and n.find("opacity") is not None:
                out.append("opacity")
        if name == "fp_rect" and v < _V_FP_RECT:
            out.append("fp_rect")
        elif name == "layer" and v < _V_KNOCKOUT and n.has_flag("knockout"):
            out.append("knockout")
        elif name == "face" and v < _V_FONTS:
            out.append("font face")
        elif name == "thermal_bridge_angle" and v < _V_THERMAL_ANGLE:
            out.append("thermal_bridge_angle")
        if v < _V_FILL and name in _GRAPHIC_CLASSES and n.find("fill") is not None:
            g = _GRAPHIC_CLASSES[name](n, src)
            if g.kind in _FILL_KINDS and g.fill != _parser_default_fill(g.kind, g.width, g.layer):
                out.append("fill")
        stack.extend(n.nodes())
    return sorted(set(out))


def _convert_element(node: Node, src: FormatProfile, dst: FormatProfile) -> None:
    """Привести дочерний элемент корпуса к профилю ``dst`` (на месте)."""
    name = node.name
    if name == "pad":
        _convert_pad_node(node, src, dst)
    elif name in ("fp_text", "property"):
        if name == "fp_text" or _is_text_property(node) or dst.text_as_property:
            _convert_text_node(node, dst)
    elif name in _GRAPHIC_CLASSES:
        _convert_graphic_node(node, src, dst)
    elif name == "model":
        _convert_model_node(node, dst)
    elif name == "group":
        _convert_group_node(node, dst)
    elif name == "zone":
        _requote_layers(node, dst)
        _move_bool(node, "locked", dst, _ZONE_ORDER)
        _convert_id(node, dst, _ZONE_ORDER, required=True)
    elif name in _ID_ELEMENTS or name in _GENERIC_GEOMETRY:
        _requote_layers(node, dst)
        _convert_id(node, dst, None, required=False)


def _normalize_arc_winding(node: Node) -> None:
    """Направление обхода дуги ``start/mid/end`` как у KiCad: ``EDA_SHAPE::SetArcGeometry``
    меняет местами начало и конец, если средняя точка лежит «не с той стороны» — все дуги
    KiCad обходит по часовой стрелке на экране (``sweep < 0`` в соглашении
    :mod:`kicadfp.geometry`); ``mid`` остаётся прежней."""
    if node.name not in ("fp_arc", "gr_arc") or _arc_is_legacy(node):
        return
    st, mid, en = node.find("start"), node.find("mid"), node.find("end")
    if st is None or mid is None or en is None:
        return
    s, m, e = _xy_of(st), _xy_of(mid), _xy_of(en)
    if s is None or m is None or e is None:
        return
    g = _geo.arc_from_three_points(s, m, e)
    if g is not None and g.sweep > 0:
        st.items, en.items = en.items, st.items


# --- нормализация чисел как у writer'а KiCad (Footprint.upgrade) ------------------------

#: Токены, числа в которых — длины (``FormatInternalUnits``: округление до нанометра).
_LEN_TOKENS = frozenset((
    "start", "mid", "end", "center", "xy", "size", "rect_delta", "drill", "offset", "width",
    "thickness", "solder_mask_margin", "solder_paste_margin", "clearance", "thermal_gap",
    "thermal_width", "thermal_bridge_width", "die_length", "radius", "margins",
    "min_thickness", "hatch", "island_area_min", "max_length", "max_width",
    "hatch_thickness", "hatch_gap",
))
#: Токены-углы (``FormatAngle``).
_ANG_TOKENS = frozenset(("thermal_bridge_angle", "angle", "render_cache"))
#: Безразмерные числа (``FormatDouble2Str``).
_DBL_TOKENS = frozenset((
    "roundrect_rratio", "chamfer_ratio", "solder_paste_margin_ratio", "solder_paste_ratio",
    "line_spacing", "xyz", "best_length_ratio", "best_width_ratio", "filter_ratio",
    "hatch_orientation", "hatch_smoothing_value", "hatch_min_hole_area",
))


def _normalize_numbers(node: Node) -> None:
    """Переписать числа известных токенов так, как их пишет KiCad при сохранении: длины —
    с округлением до нанометра (``0.1666666667`` -> ``0.166667``, ``1.0`` -> ``1``, ``-0`` ->
    ``0``), углы и коэффициенты — ``%.10g``, ``opacity`` — ``%0.4f``. Узлы с неизвестными
    именами не трогаются (их дочерние узлы с известными именами — да)."""
    stack = [node]
    while stack:
        n = stack.pop()
        name = n.name
        fmt: Callable[[float], str] | None = None
        if name in _LEN_TOKENS:
            fmt = format_number
        elif name in _ANG_TOKENS:
            fmt = format_angle
        elif name in _DBL_TOKENS:
            fmt = format_double
        k = 0
        for i, x in enumerate(n.items):
            if isinstance(x, Node):
                stack.append(x)
                continue
            if not isinstance(x, Sym) or not is_number(x):
                continue
            if name == "at":
                f = format_angle if k == 2 else format_number
            elif name == "opacity":
                f = lambda v: "%.4f" % v  # noqa: E731
            else:
                f = fmt  # type: ignore[assignment]
            k += 1
            if f is None:
                continue
            text = f(float(x))
            if text != x:
                n.items[i] = Sym(text)


# --- сортировка как у writer'а KiCad (Footprint.upgrade) ------------------------------

def _nm(v: float) -> int:
    """Миллиметры -> целые нанометры (``KiROUND``, как парсер KiCad)."""
    return _kiround(float(v) * 1e6)


def _nm_pt(p: Point) -> tuple[int, int]:
    return (_nm(p[0]), _nm(p[1]))


def _strnumcmp(a: str, b: str) -> int:
    """``StrNumCmp`` KiCad (string_utils.cpp): сравнение с учётом чисел внутри строк."""
    i = j = 0
    while i < len(a) and j < len(b):
        c1, c2 = a[i], b[j]
        if c1.isdigit() and c2.isdigit():
            n1 = 0
            while True:
                n1 = n1 * 10 + ord(a[i]) - 48
                i += 1
                if not (i < len(a) and a[i].isdigit()):
                    break
            n2 = 0
            while True:
                n2 = n2 * 10 + ord(b[j]) - 48
                j += 1
                if not (j < len(b) and b[j].isdigit()):
                    break
            if n1 != n2:
                return -1 if n1 < n2 else 1
            c1 = a[i] if i < len(a) else "\0"
            c2 = b[j] if j < len(b) else "\0"
        if c1 != c2:
            return -1 if c1 < c2 else 1
        if i < len(a):
            i += 1
        if j < len(b):
            j += 1
    if i >= len(a) and j < len(b):
        return -1
    if i < len(a) and j >= len(b):
        return 1
    return 0


_PAD_SHAPE_RANK = {"circle": 0, "rect": 1, "oval": 2, "trapezoid": 3, "roundrect": 4,
                   "custom": 6}


def _pad_cmp_key(node: Node, version: int) -> tuple:
    """Ключ ``FOOTPRINT::cmp_pads`` без номера (номер сравнивается ``StrNumCmp`` отдельно):
    KiCad 7+ — положение, размер, форма; 6.0 — только uuid."""
    view = Pad(node, None)
    uid = (_get_id(node) or "").lower()
    if version <= 20211014:
        return (uid,)
    shape = view.shape
    rank = 5 if shape == "roundrect" and (view.chamfer_ratio or 0) > 0 and view.chamfer else \
        _PAD_SHAPE_RANK.get(shape, 7)
    ids = _L.LAYER_ID_V9 if version >= V_FILL_YESNO else _L.LAYER_ID_V6
    seq = tuple(sorted(ids.get(n, 1 << 10) for n in _L.expand(view.layers)))
    return (_nm(view.x), _nm(view.y), _nm(view.size_x), _nm(view.size_y), rank, seq, uid)


def _drawing_cmp_key(node: Node, version: int) -> tuple:
    """Полный ключ ``FOOTPRINT::cmp_drawings`` (KiCad 7+: тип, слой, вид фигуры, координаты
    в нанометрах, ширина линии, uuid; 6.0 — без координат)."""
    base = drawing_sort_key(node, version)
    uid = (_get_id(node) or "").lower()
    cls = _GRAPHIC_CLASSES.get(node.name)
    if cls is None or version <= 20211014:
        return base + ((), uid)
    g = cls(node, None)
    kind = g.kind
    coords: tuple = ()
    if kind == "poly":
        pts = g._points()
        coords = (len(pts),) + tuple(c for p in pts for c in _nm_pt(p))
    else:
        if kind == "circle":
            s, e = g.center, g.end  # type: ignore[attr-defined]
        elif kind == "arc":
            s, _, e = g._three()  # type: ignore[attr-defined]
        elif kind == "curve":
            pts = g._points()
            s, e = (pts[0], pts[-1]) if pts else ((0.0, 0.0), (0.0, 0.0))
        else:
            s, e = g.start, g.end  # type: ignore[attr-defined]
        coords = _nm_pt(s) + _nm_pt(e)
        if kind == "arc":
            coords += _nm_pt(g.center)  # type: ignore[attr-defined]
        elif kind == "curve":
            pts = g._points()
            if len(pts) == 4:
                coords += _nm_pt(pts[1]) + _nm_pt(pts[2])
    coords += (_nm(g.width or 0.0),)
    return base + (coords, uid)


def _is_ref_or_value_text(node: Node) -> bool:
    a = node.atom(0) if node.name == "fp_text" else None
    return a is not None and str(a) in ("reference", "value")


def _field_rank(node: Node, version: int) -> int:
    """Порядок полей как ``GetFields()``: обязательные в порядке KiCad, затем прочие."""
    name = str(node.atom(0) or "")
    fields = _mandatory_fields(version) or ["Reference", "Value"]
    return fields.index(name) if name in fields else len(fields)


def _sort_root_like_kicad(root: Node, version: int) -> None:
    """Упорядочить дочерние узлы корпуса так, как их пишет writer KiCad версии ``version``:
    секции по :data:`FOOTPRINT_ORDER` (секция рисования — одним блоком), поля — в порядке
    ``GetFields()``, секция рисования — по ``cmp_drawings`` (в 6/7 ``fp_text reference/value``
    первыми), площадки — по ``cmp_pads`` (``StrNumCmp`` номера, положение, размер, форма).
    Зоны, группы, модели — в исходном порядке; неизвестные узлы остаются после своего
    предшественника."""
    items = root.items
    k = 0
    while k < len(items) and not isinstance(items[k], Node):
        k += 1
    head, rest = items[:k], items[k:]
    rank = {n: i for i, n in enumerate(FOOTPRINT_ORDER)}
    drawing_rank = rank["fp_text"]
    last = -1
    keyed: list[tuple[int, int, Any]] = []
    for idx, x in enumerate(rest):
        name = x.name if isinstance(x, Node) else str(x)
        if isinstance(x, Node) and group_of(x) in DRAWING_GROUPS:
            r = drawing_rank
        else:
            r = rank.get(name, -1)
            if r < 0:
                r = last
        last = r
        keyed.append((r, idx, x))
    keyed.sort(key=lambda t: (t[0], t[1]))
    ordered = [x for _, _, x in keyed]
    # поля в порядке GetFields()
    props = [i for i, x in enumerate(ordered) if isinstance(x, Node) and x.name == "property"
             and _is_text_property(x)]
    if props:
        nodes = sorted((ordered[i] for i in props), key=lambda n: _field_rank(n, version))
        for i, n in zip(props, nodes):
            ordered[i] = n
    # секция рисования
    draw = [i for i, x in enumerate(ordered) if isinstance(x, Node) and group_of(x) in DRAWING_GROUPS]
    if draw:
        nodes = [ordered[i] for i in draw]
        refval = [n for n in nodes if _is_ref_or_value_text(n)]
        others = [n for n in nodes if not _is_ref_or_value_text(n)]
        refval.sort(key=lambda n: 0 if str(n.atom(0)) == "reference" else 1)
        others.sort(key=lambda n: _drawing_cmp_key(n, version))
        for i, n in zip(draw, refval + others):
            ordered[i] = n
    # площадки
    pads = [i for i, x in enumerate(ordered) if isinstance(x, Node) and x.name == "pad"]
    if pads:
        def cmp(a: Node, b: Node) -> int:
            na, nb = str(a.atom(0) or ""), str(b.atom(0) or "")
            if na != nb:
                c = _strnumcmp(na, nb)
                if c:
                    return c
            ka, kb = _pad_cmp_key(a, version), _pad_cmp_key(b, version)
            return (ka > kb) - (ka < kb)
        nodes = sorted((ordered[i] for i in pads), key=functools.cmp_to_key(cmp))
        for i, n in zip(pads, nodes):
            ordered[i] = n
    root.items = head + ordered


# ---------------------------------------------------------------------------
# Поля корпуса (KiCad 8+) и прочие помощники корпуса
# ---------------------------------------------------------------------------

def _mandatory_fields(version: int | None) -> list[str]:
    """Поля, которые KiCad версии формата ``version`` пишет всегда (``GetFields()``):
    9.0+ — Reference, Value, Datasheet, Description; 8.0 — ещё Footprint; до 8.0 полей нет
    (Reference/Value — ``fp_text``)."""
    v = version or 0
    if v >= V_FILL_YESNO:
        return ["Reference", "Value", "Datasheet", "Description"]
    if v >= V_FIELDS:
        return ["Reference", "Value", "Footprint", "Datasheet", "Description"]
    return []


def _field_node(name: str, value: str, profile: FormatProfile, *, x: float = 0.0, y: float = 0.0,
                layer: str = "F.Fab", hide: bool = True, uuid: bool | str | None = True) -> Node:
    """Узел поля KiCad 8+ ``(property "имя" "значение" (at …) … (effects …))`` в том виде,
    в каком KiCad создаёт служебные поля: 9.0+ — ``(at 0 0 0) (layer "F.Fab") (hide yes)
    (uuid …) (effects (font (size 1.27 1.27) (thickness 0.15)))``; 8.0 — с
    ``(unlocked yes)`` и без толщины."""
    order = profile.text_order
    node = Node("property", [Str(name), Str(value)])
    node.append(Node("at", [_len(x), _len(y), _ang(0.0)]))
    nine = profile.version >= V_FILL_YESNO
    if not nine:
        node.append(Node("unlocked", [Sym("yes")]))
    node.append(Node("layer", [_layer_atom(layer, profile)]))
    if hide:
        node.append(Node("hide", [Sym("yes")]))
    font = Node("font", [Node("size", [_len(1.27), _len(1.27)])])
    if nine:
        font.append(Node("thickness", [_len(0.15)]))
    node.append(Node("effects", [font]))
    _add_new_id(node, profile, order, uuid)
    return node


def _new_property_node(name: str, value: str, profile: FormatProfile) -> Node:
    """Новое свойство корпуса: поле со скрытым текстом на F.Fab (KiCad 8+) или
    ``(property "имя" "значение")`` (KiCad 6/7)."""
    if profile.text_as_property:
        return _field_node(name, value, profile)
    return Node("property", [Str(name), Str(value)])


def _version_major_minor() -> str:
    """``__version__`` без номера исправления (``"0.1.0"`` -> ``"0.1"``)."""
    return ".".join(__version__.split(".")[:2])


#: Версия KiCad, соответствующая версии формата (для ``generator_version`` у ``pcbnew``).
_KICAD_FOR_FORMAT: tuple[tuple[int, str], ...] = (
    (20260206, "10.0"), (20241229, "9.0"), (20231014, "8.0"),
)


def _generator_version_for(generator: str | None, version: int) -> str | None:
    """Значение ``generator_version``: у ``kicadfp`` — версия пакета (major.minor), у
    ``pcbnew`` — версия KiCad для формата (``"9.0"`` для 20241229); иначе ``None``."""
    if generator == DEFAULT_GENERATOR:
        return _version_major_minor()
    if generator == "pcbnew":
        for v, name in _KICAD_FOR_FORMAT:
            if version >= v:
                return name
    return None


def _generator_atom(value: str, profile: FormatProfile) -> Atom:
    """``generator`` в кавычках (KiCad 8+) или голым (6/7, если возможно)."""
    if profile.quoted_generator or not _bare_symbol_ok(value):
        return Str(value)
    return Sym(value)


def _text_bbox(t: Text) -> BBox:
    """Приближённые габариты текста: ширина ≈ 0.85 × ширина символа × длина строки (плюс
    толщина), высота — высота символа; учитываются выравнивание и угол."""
    s = t.text
    w = max(len(s), 1) * t.font_size_x * 0.85
    h = t.font_size_y
    th = t.thickness or 0.0
    w += th
    h += th
    j = t.justify
    x0 = 0.0 if "left" in j else (-w if "right" in j else -w / 2.0)
    y0 = -h if "bottom" in j else (0.0 if "top" in j else -h / 2.0)
    if "mirror" in j:
        x0 = -x0 - w
    corners = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    a = t.angle
    pts = [_geo.rotate_point(p, a) for p in corners] if a else corners
    cx, cy = t.position
    return BBox.of_points([(cx + p[0], cy + p[1]) for p in pts])  # type: ignore[return-value]


def _deep_move(node: Node, dx: float, dy: float) -> None:
    for n in _deep_coord_nodes(node):
        _shift_node(n, dx, dy)


def _deep_rotate(node: Node, angle: float, origin: Point) -> None:
    for n in _deep_coord_nodes(node):
        _rotate_node(n, angle, origin)


def _deep_mirror_x(node: Node) -> None:
    for n in _deep_coord_nodes(node):
        _mirror_node(n, "x", 0.0)


# ---------------------------------------------------------------------------
# Коллекции корпуса: AttrSet, PropertyMap
# ---------------------------------------------------------------------------

def _check_attr_version(flag: str, profile: FormatProfile) -> None:
    """``ValueError``, если флага ``(attr …)`` нет в версии формата профиля."""
    _require_version(profile, _ATTR_MIN_VERSION.get(flag, 0), f"attr {flag}")


class AttrSet(MutableSet):
    """Множество флагов ``(attr …)`` корпуса (представление над узлом).

    ``add``/``discard``/``clear``/``in``/итерация/``len``; новые флаги вставляются на место
    по порядку KiCad (:data:`kicadfp.format_rules.ATTR_ORDER`: ``smd``, ``through_hole``,
    ``board_only``, ``exclude_from_pos_files``, ``exclude_from_bom``,
    ``allow_missing_courtyard``, ``dnp``, ``allow_soldermask_bridges``), имеющиеся не
    переставляются. Пустое множество — узел ``attr`` удаляется (KiCad пишет его только при
    ненулевых атрибутах). Значения читаются как записаны: у корпусов KiCad 5 без
    ``(attr …)`` множество пусто, хотя KiCad считает их ``through_hole``.
    """

    __slots__ = ("_fp",)

    def __init__(self, fp: Footprint) -> None:
        self._fp = fp

    def _node(self) -> Node | None:
        return self._fp.node.find("attr")

    def __contains__(self, value: object) -> bool:
        n = self._node()
        return n is not None and any(str(a) == value for a in n.atoms())

    def __iter__(self) -> Iterator[str]:
        n = self._node()
        if n is None:
            return iter(())
        seen: list[str] = []
        for a in n.atoms():
            if str(a) not in seen:
                seen.append(str(a))
        return iter(seen)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def add(self, value: str) -> None:
        """Добавить флаг (``ValueError`` для неизвестного и для флага, которого нет в версии
        формата корпуса: ``through_hole``, ``board_only``, ``exclude_from_*`` — с 20200826
        (в KiCad 5 ``module`` — только ``smd`` и ``virtual``; сквозной монтаж там — отсутствие
        ``attr``), ``allow_missing_courtyard``/``allow_soldermask_bridges`` — KiCad 7,
        ``dnp`` — KiCad 8 (20230410), ``exclude_from_sim`` — KiCad 10 (20260828))."""
        v = _check_enum(value, ATTR_ORDER, "attr")
        if v in self:
            return
        _check_attr_version(v, self._fp.profile)
        n = self._node()
        if n is None:
            self._fp.node.insert(Node("attr", [Sym(v)]), order=FOOTPRINT_ORDER)
            return
        rank = {a: i for i, a in enumerate(ATTR_ORDER)}
        my = rank[v]
        pos = 0
        for i, x in enumerate(n.items):
            if isinstance(x, Node):
                continue
            if rank.get(str(x), len(ATTR_ORDER)) <= my:
                pos = i + 1
        n.items.insert(pos, Sym(v))

    def discard(self, value: str) -> None:
        """Убрать флаг (если он есть)."""
        n = self._node()
        if n is None:
            return
        n.items = [x for x in n.items if isinstance(x, Node) or str(x) != value]
        if not n.items:
            self._fp.node.remove_child(n)

    def clear(self) -> None:
        """Убрать все флаги (узел ``attr`` удаляется)."""
        self._fp.node.remove("attr")

    def __repr__(self) -> str:
        return f"AttrSet({list(self)!r})"


#: Пороги версий, после которых KiCad читает те же токены иначе (или пишет их в другой
#: форме, не отражённой в FormatProfile): ``(первая версия нового поведения, что меняется)``.
_VERSION_SEMANTIC_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (20171130, "смещение 3D-модели (at) в дюймах"),
    (_V_ATTR_FLAGS, "корпус без attr (through_hole)"),
    (20210606, "синтаксис надчёркивания ~…~"),
    (V_ARC_MID, "форма дуг (center/end/angle -> start/mid/end)"),
    (V_STROKE, "stroke/width"),
    (20220427, "Edge.Cuts/Margin в private_layers"),
    (_V_LEGACY_NET_TIES + 1, "net tie через tags"),
    (V_FIELDS, "поля Reference/Value (property)"),
    (V_NORMALIZED, "формы флагов и uuid"),
    (_V_GROUP_UUID, "id/uuid групп"),
    (_V_NULLABLE + 1, "ноль у зазоров и масок («не задано»)"),
    (_V_EMBEDDED, "разделитель | в путях встроенных файлов"),
)


def _check_version_change(root: str, cur: int | None, new: int | None) -> None:
    """``ValueError``, если смена токена ``version`` с ``cur`` на ``new`` (без перевода
    содержимого) изменила бы форму записи или смысл уже записанных токенов (см.
    :attr:`Footprint.version`)."""
    hint = " — используйте Footprint.upgrade(), он переводит и содержимое корпуса"
    if root == "module" or cur is None:
        raise ValueError("version: версию корпуса KiCad 5 (module или без version) задаёт "
                         "только Footprint.upgrade(): он переводит и содержимое корпуса")
    if new is None:
        raise ValueError("version: удалить версию нельзя — без неё KiCad читает файл как "
                         "формат KiCad 5 (старая форма дуг и т.п.)")
    if new < cur:
        raise ValueError(f"version: понижение версии ({cur} -> {new}) не поддерживается: "
                         "KiCad старой версии может не прочитать уже записанные конструкции")
    crossed = [what for limit, what in _VERSION_SEMANTIC_THRESHOLDS if cur < limit <= new]
    a, b = _profile(cur, root), _profile(new, root)
    differ = [f for f in a.__dataclass_fields__ if f not in ("version", "style")
              and getattr(a, f) != getattr(b, f)]
    if crossed or differ:
        what = ", ".join(crossed + differ)
        raise ValueError(f"version: при переходе {cur} -> {new} меняется форма или смысл "
                         f"токенов ({what}){hint}")


def _merge_legacy_ref_value(root: Node, src: FormatProfile, dst: FormatProfile) -> None:
    """Дубли Reference/Value файла KiCad 5–7 — так, как их сводит парсер KiCad 8+ при чтении
    (для :meth:`Footprint.upgrade`), чтобы после перевода осталось одно поле.

    Каждый ``fp_text reference``/``value`` заменяет поле целиком (``FOOTPRINT::Reference() =
    PCB_FIELD(*text)``) — остаётся последний. Голое ``(property "Reference"|"Value" "v")``
    версии < 20230620 лишь меняет текст уже созданного поля и скрывает его
    (``SetVisible(false)``): стоящее перед ``fp_text`` (так пишут KiCad 6/7) переписывается
    им и исчезает, стоящее после — даёт полю свой текст и признак «скрыто»; без ``fp_text``
    оно становится скрытым полем (Reference — на F.SilkS, Value — на F.Fab)."""
    for kind, fname in _FIELD_NAMES.items():
        slot = _slot_nodes(root, fname)
        texts = [n for n in slot if n.name == "fp_text"]
        for n in texts[:-1]:
            root.remove_child(n)
        last_text = texts[-1] if texts else None
        for n in slot:
            if n.name != "property" or _is_text_property(n):
                continue
            pval = str(n.atom(1) or "")
            if last_text is None:
                layer = "F.SilkS" if kind == "reference" else "F.Fab"
                n.items = _field_node(fname, pval, dst, layer=layer, hide=True).items
                continue
            if root.index(n) > root.index(last_text):
                t = Text(last_text, src)
                t.text = pval
                _write_bool(last_text, "hide", True, src, src.text_order)
            root.remove_child(n)


class PropertyMap(MutableMapping):
    """Свойства корпуса ``(property "ключ" "значение" …)`` как словарь ``str -> str``.

    Включает все узлы ``property`` (в KiCad 8+ — и поля Reference/Value/Datasheet …);
    значение — второй атом. Присваивание существующему ключу меняет только значение;
    новый ключ создаёт свойство в форме версии файла: KiCad 8+ — скрытое поле на F.Fab
    (``(at 0 0 0) (layer "F.Fab") (hide yes) (uuid …) (effects (font (size 1.27 1.27) …))``),
    KiCad 6/7 — ``(property "ключ" "значение")``; вставка — после последнего свойства.
    Свойства корпуса появились в версии 20200808: новый ключ в файле более старой версии
    (KiCad 5 ``module``) — ``ValueError``. ``del`` удаляет все свойства с этим ключом.
    В KiCad 5–7 (профиль без полей) присваивание ключам ``Reference``/``Value`` —
    ``ValueError``: там это тексты ``fp_text reference/value`` (:attr:`Footprint.reference`),
    а одноимённое свойство KiCad 6/7 к тексту не относят, KiCad 8+ его отбрасывает.
    """

    __slots__ = ("_fp",)

    def __init__(self, fp: Footprint) -> None:
        self._fp = fp

    def _nodes(self) -> list[Node]:
        return self._fp.node.nodes("property")

    def node(self, key: str) -> Node | None:
        """Узел свойства ``key`` (первый) или ``None``."""
        for n in self._nodes():
            a = n.atom(0)
            if a is not None and str(a) == key:
                return n
        return None

    def text(self, key: str) -> Text | None:
        """Свойство ``key`` как :class:`Text` (для полей KiCad 8+) или ``None``."""
        n = self.node(key)
        return None if n is None else Text(n, parent=self._fp)

    def __getitem__(self, key: str) -> str:
        n = self.node(key)
        if n is None:
            raise KeyError(key)
        v = n.atom(1)
        return "" if v is None else str(v)

    def __setitem__(self, key: str, value: str) -> None:
        k = _check_str(key, "key", allow_empty=False)
        v = _check_str(value, "value")
        if k in _FIELD_NAMES.values() and not self._fp.profile.text_as_property:
            # KiCad 5–7: Reference/Value — это fp_text; свойство с таким ключом KiCad 6/7
            # хранят отдельно от текста, а KiCad 8+ при чтении отбрасывает (fp_text его
            # переписывает) — значение потерялось бы
            raise ValueError(f"в формате KiCad 5–7 {k} — это текст fp_text, а не свойство: "
                             f"присвойте fp.{k.lower()}.text (или fp.{k.lower()} = …)")
        n = self.node(k)
        if n is not None:
            old = n.atom(1)
            if old is None or str(old) != v or not isinstance(old, Str):
                n.set_atom(1, Str(v))
            return
        _require_version(self._fp.profile, _V_FP_PROPERTY, "property корпуса")
        insert_in_group(self._fp.node, _new_property_node(k, v, self._fp.profile))

    def __delitem__(self, key: str) -> None:
        nodes = [n for n in self._nodes() if n.atom(0) is not None and str(n.atom(0)) == key]
        if not nodes:
            raise KeyError(key)
        for n in nodes:
            self._fp.node.remove_child(n)

    def __iter__(self) -> Iterator[str]:
        seen: list[str] = []
        for n in self._nodes():
            a = n.atom(0)
            if a is not None and str(a) not in seen:
                seen.append(str(a))
        return iter(seen)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __repr__(self) -> str:
        return f"PropertyMap({dict(self)!r})"


# ---------------------------------------------------------------------------
# Footprint
# ---------------------------------------------------------------------------

_ROOT_NAMES = ("footprint", "module")


class Footprint(View):
    """Посадочное место: корневой узел ``(footprint "имя" …)`` (KiCad 6+) или
    ``(module имя …)`` (KiCad 5).

    Профиль формата вычисляется по корню при каждом обращении (``version`` и имя корня;
    у ``module`` — версия 0). Все представления, полученные из корпуса (``pads``,
    ``graphics``, ``texts`` …), пишут новые токены в форме этого профиля.

    Коллекции (``pads``, ``graphics``, ``texts``, ``models``, ``zones``, ``groups``,
    ``unknown``) при каждом обращении строятся заново — это списки новых представлений над
    текущими узлами в порядке файла.
    """

    __slots__ = ("final_newline",)

    def __init__(self, node: Node, *, final_newline: bool = True) -> None:
        if not isinstance(node, Node):
            raise TypeError("Footprint создаётся над узлом sexpr.Node")
        if node.name not in _ROOT_NAMES:
            raise ValueError(f"корневой узел посадочного места — footprint или module, "
                             f"а не {node.name!r}")
        super().__init__(node, None, None)
        #: Завершать ли текст файла переводом строки (:meth:`dumps`). :func:`kicadfp.io.load`
        #: запоминает, был ли он в исходном файле: KiCad 8.0.0/8.0.1 и генератор
        #: библиотек KiCad 5 писали файлы без ``\n`` в конце (format-layout.md §4.1), и
        #: открытый без изменений файл должен сохраниться байт в байт (architecture.md §2).
        #: Новые корпуса и :meth:`upgrade` — ``True`` (так пишет KiCad 8.0.2+).
        self.final_newline = bool(final_newline)

    @property
    def profile(self) -> FormatProfile:
        """Профиль формата по корню (версия файла; ``module`` — KiCad 5)."""
        return _profile(self.version, self.node.name)

    def _order(self) -> Sequence[str]:
        return FOOTPRINT_ORDER

    # --- создание ---------------------------------------------------------------------------
    @classmethod
    def new(cls, name: str, *, version: int | None = DEFAULT_VERSION,
            generator: str | None = DEFAULT_GENERATOR, layer: str = "F.Cu", descr: str = "",
            tags: str = "", attrs: Iterable[str] = (), reference: str = "REF**",
            value: str | None = None) -> Footprint:
        """Новый корпус в стиле KiCad версии ``version`` (по умолчанию KiCad 9, 20241229).

        Создаются: ``version``, ``generator`` (``"kicadfp"``), ``generator_version``
        (версия пакета major.minor; для KiCad 8+), ``layer``, ``tedit`` (KiCad 5/6),
        ``descr``/``tags`` (если заданы), тексты Reference (``reference``, F.SilkS,
        (0, -0.5)) и Value (``value`` или имя корпуса, F.Fab, (0, 1)) — положения и
        размер 1 мм как у нового корпуса в редакторе KiCad; в KiCad 8+ это поля
        ``property``, к которым добавляются служебные поля, которые KiCad пишет всегда
        (9.0+: Datasheet, Description; 8.0: ещё Footprint), ``attr``, ``(embedded_fonts
        no)`` (KiCad 9+) и ``(duplicate_pad_numbers_are_jumpers no)`` (KiCad 10).
        ``version=None`` (или 0) — корень ``module`` формата KiCad 5.
        """
        module = not version
        v = None if module else _check_int(version, "version")
        root = Node("module" if module else "footprint")
        prof = _profile(v, root.name)
        root.items.append(_str_atom(_check_str(name, "name", allow_empty=False), prof))
        fp = cls(root)
        if v is not None:
            root.append(Node("version", [Sym(str(v))]))
            if generator:
                root.append(Node("generator", [_generator_atom(generator, prof)]))
                gv = _generator_version_for(generator, v) if prof.has_generator_version else None
                if gv:
                    root.append(Node("generator_version", [Str(gv)]))
        fp.layer = layer
        if prof.has_tedit:
            root.set("tedit", Sym("%X" % int(time.time())), order=FOOTPRINT_ORDER)
        if descr:
            fp.descr = descr
        if tags:
            fp.tags = tags
        fp.add(Text.new(reference, "reference", 0.0, -0.5, "F.SilkS", profile=prof))
        fp.add(Text.new(name if value is None else value, "value", 0.0, 1.0, "F.Fab",
                        profile=prof))
        for fname in _mandatory_fields(v)[2:]:
            insert_in_group(root, _field_node(fname, "", prof))
        for a in attrs:
            fp.attrs.add(a)
        if v is not None and v >= _V_EMBEDDED:
            root.insert(Node("embedded_fonts", [Sym("no")]), order=FOOTPRINT_ORDER)
        if v is not None and v >= _V_JUMPERS:
            root.insert(Node("duplicate_pad_numbers_are_jumpers", [Sym("no")]),
                        order=FOOTPRINT_ORDER)
        return fp

    # --- свойства корпуса ---------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Имя (первый атом корня; в KiCad 6+ — строка в кавычках, в KiCad 5 — голое)."""
        a = self.node.atom(0)
        return "" if a is None else str(a)

    @name.setter
    def name(self, value: str) -> None:
        self.node.set_atom(0, _str_atom(_check_str(value, "name", allow_empty=False),
                                        self.profile))

    @property
    def version(self) -> int | None:
        """Версия формата ``(version N)`` или ``None`` (нет токена, KiCad 5).

        Присваивание меняет только токен ``version`` и поэтому разрешено лишь тогда, когда
        содержимое корпуса в новой версии записывается и читается KiCad так же, как в
        прежней: повышение версии, при котором не меняется ни одна форма записи профиля
        (:class:`~kicadfp.format_rules.FormatProfile`, кроме раскладки пробелов) и не
        пересекается ни один порог, после которого KiCad читает те же токены иначе (форма
        дуг 20210925, надчёркивание 20210606, ``attr`` 20200826, net tie 20220815,
        ``private_layers`` 20220427, поля 20230620, nullable 20240201 …). Иначе —
        ``ValueError`` с предложением :meth:`upgrade` (он переводит и содержимое): KiCad
        выбирает форму дуг и смысл токенов по версии, и файл с «чужой» формой не читается
        («Unable to load library»). Понижение версии, удаление токена (``None``), установка
        версии корню ``module`` и корню без версии также запрещены. Присваивание текущего
        значения ничего не меняет.
        """
        a = self.node.value("version")
        if a is None or not is_number(a):
            return None
        return int(float(a))

    @version.setter
    def version(self, value: int | None) -> None:
        cur = self.version
        new = None if value is None else _check_int(value, "version")
        if new == cur and (new is None) == (self.node.find("version") is None):
            return
        _check_version_change(self.node.name, cur, new)
        self.node.set("version", Sym(str(new)), order=FOOTPRINT_ORDER)

    @property
    def generator(self) -> str | None:
        """Программа, записавшая файл (``pcbnew``, ``kicadfp`` …) или ``None``."""
        v = self.node.value("generator")
        return None if v is None else str(v)

    @generator.setter
    def generator(self, value: str | None) -> None:
        if value is None:
            self.node.remove("generator")
            return
        self.node.set("generator",
                      _generator_atom(_check_str(value, "generator", allow_empty=False), self.profile),
                      order=FOOTPRINT_ORDER)

    @property
    def generator_version(self) -> str | None:
        """Версия программы ``(generator_version "9.0")`` (KiCad 8+) или ``None``."""
        v = self.node.value("generator_version")
        return None if v is None else str(v)

    @generator_version.setter
    def generator_version(self, value: str | None) -> None:
        self._set_opt_str("generator_version", value)

    @property
    def layer(self) -> str:
        """Сторона ``F.Cu`` | ``B.Cu`` (``F.Cu``, если токена нет)."""
        v = self.node.value("layer")
        return "F.Cu" if v is None else str(v)

    @layer.setter
    def layer(self, value: str) -> None:
        v = _check_enum(value, ("F.Cu", "B.Cu"), "layer")
        ln = self.node.find("layer")
        atom = _layer_atom(v, self.profile)
        if ln is None:
            self.node.set("layer", atom, order=FOOTPRINT_ORDER)
        else:
            ln.set_atom(0, atom)

    def _get_text_token(self, token: str) -> str:
        v = self.node.value(token)
        return "" if v is None else str(v)

    def _set_text_token(self, token: str, value: str | None) -> None:
        if value is None or value == "":
            self.node.remove(token)
            return
        s = _check_str(value, token)
        atom: Atom = Str(s)
        n = self.node.find(token)
        if n is not None:
            old = n.atom(0)
            if old is not None and str(old) == s:
                return
            n.set_atom(0, atom)
            return
        self.node.set(token, atom, order=FOOTPRINT_ORDER)

    @property
    def descr(self) -> str:
        """Описание ``(descr "…")`` (``""``, если нет; присваивание ``""`` удаляет узел)."""
        return self._get_text_token("descr")

    @descr.setter
    def descr(self, value: str | None) -> None:
        self._set_text_token("descr", value)

    @property
    def tags(self) -> str:
        """Ключевые слова ``(tags "…")`` (``""``, если нет; ``""`` удаляет узел)."""
        return self._get_text_token("tags")

    @tags.setter
    def tags(self, value: str | None) -> None:
        self._set_text_token("tags", value)

    @property
    def attrs(self) -> AttrSet:
        """Флаги ``(attr …)`` как множество (:class:`AttrSet`); присваивание итерируемого
        заменяет содержимое (порядок — как в KiCad). Новый флаг, которого нет в версии
        формата корпуса (см. :meth:`AttrSet.add`), — ``ValueError``."""
        return AttrSet(self)

    @attrs.setter
    def attrs(self, value: Iterable[str]) -> None:
        if isinstance(value, str):
            value = value.replace(",", " ").split()
        vals = [_check_enum(v, ATTR_ORDER, "attr") for v in value]
        cur = set(self.attrs)
        if set(vals) == cur:
            return
        for v in vals:
            if v not in cur:
                _check_attr_version(v, self.profile)
        n = self.node.find("attr")
        atoms = [Sym(a) for a in ATTR_ORDER if a in vals]
        if not atoms:
            self.node.remove("attr")
        elif n is None:
            self.node.insert(Node("attr", atoms), order=FOOTPRINT_ORDER)
        else:
            n.items = atoms  # type: ignore[assignment]

    @property
    def properties(self) -> PropertyMap:
        """Все свойства ``(property …)`` как словарь (:class:`PropertyMap`)."""
        return PropertyMap(self)

    clearance = _override_prop("clearance", "len", "Локальный зазор корпуса, мм (``None`` — "
                               "нет)." + _NULLABLE_DOC)
    solder_mask_margin = _override_prop("solder_mask_margin", "len",
                                        "Отступ маски, мм." + _NULLABLE_DOC)
    solder_paste_margin = _override_prop("solder_paste_margin", "len",
                                         "Отступ пасты, мм." + _NULLABLE_DOC)
    zone_connect = _num_prop("zone_connect", "int", "Подключение к зонам (0..3) или ``None``.")
    thermal_width = _num_prop("thermal_width", "len",
                              "Ширина спиц термобарьера корпуса (KiCad 5/6; KiCad 7+ не читает).")
    thermal_gap = _num_prop("thermal_gap", "len",
                            "Зазор термобарьера корпуса (KiCad 5/6; KiCad 7+ не читает).")
    autoplace_cost90 = _num_prop("autoplace_cost90", "int", "Устаревший параметр авторазмещения.")
    autoplace_cost180 = _num_prop("autoplace_cost180", "int", "Устаревший параметр авторазмещения.")
    path = _str_prop("path", "Путь в иерархии схемы (только в платах).")
    sheetname = _str_prop("sheetname", "Имя листа схемы (KiCad 8+, только в платах; в "
                          "файле KiCad 5–7 новый токен — ``ValueError``).", _V_SHEET)
    sheetfile = _str_prop("sheetfile", "Файл листа схемы (KiCad 8+, только в платах; в "
                          "файле KiCad 5–7 новый токен — ``ValueError``).", _V_SHEET)

    @property
    def solder_paste_ratio(self) -> float | None:
        """Коэффициент пасты: ``(solder_paste_margin_ratio …)`` (KiCad 9+) или
        ``(solder_paste_ratio …)`` (KiCad 5–8); читается любой. Существующий токен
        сохраняет имя, новый — по версии файла. В файле версии <= 20240201 (KiCad 5–8) ноль
        означает «не задано» (наследовать): getter возвращает ``None``, присваивание 0
        удаляет токен."""
        return _get_override(self, ("solder_paste_margin_ratio", "solder_paste_ratio"), "dbl")

    @solder_paste_ratio.setter
    def solder_paste_ratio(self, value: float | None) -> None:
        _set_override(self, ("solder_paste_margin_ratio", "solder_paste_ratio"), value, "dbl",
                      self.profile.solder_paste_ratio_token, "solder_paste_ratio")

    @property
    def uuid(self) -> str | None:
        """Идентификатор корпуса (только в платах; в библиотеке KiCad его не пишет)."""
        return _get_id(self.node)

    @uuid.setter
    def uuid(self, value: str | None) -> None:
        _set_id(self.node, value, self.profile, FOOTPRINT_ORDER)

    @property
    def locked(self) -> bool:
        """Блокировка корпуса: голый ``locked`` (KiCad 5–7) или ``(locked yes)`` (8+)."""
        return bool(_bool_token(self.node, "locked"))

    @locked.setter
    def locked(self, value: bool) -> None:
        _write_bool(self.node, "locked", bool(value), self.profile, FOOTPRINT_ORDER)

    @property
    def placed(self) -> bool:
        """Признак «размещён»: голый ``placed`` (KiCad 5–7) или ``(placed yes)`` (8+)."""
        return bool(_bool_token(self.node, "placed"))

    @placed.setter
    def placed(self, value: bool) -> None:
        _write_bool(self.node, "placed", bool(value), self.profile, FOOTPRINT_ORDER)

    @property
    def tedit(self) -> str | None:
        """Метка времени правки ``(tedit HEX)`` (KiCad 5/6) или ``None``."""
        v = self.node.value("tedit")
        return None if v is None else str(v)

    @tedit.setter
    def tedit(self, value: str | None) -> None:
        if value is None:
            self.node.remove("tedit")
            return
        s = _check_str(value, "tedit", allow_empty=False)
        if not all(c in _HEX8 for c in s):
            raise ValueError("tedit: ожидается шестнадцатеричное число")
        self.node.set("tedit", Sym(s.upper()), order=FOOTPRINT_ORDER)

    @property
    def private_layers(self) -> list[str]:
        """Приватные слои ``(private_layers …)`` (пусто, если нет). Токен есть с формата
        20211231 (KiCad 7); в более старом формате новый список — ``ValueError``."""
        n = self.node.find("private_layers")
        return [] if n is None else [str(a) for a in n.atoms()]

    @private_layers.setter
    def private_layers(self, value: Iterable[str] | str | None) -> None:
        names = [] if value is None else _layer_list(value)
        if not names:
            self.node.remove("private_layers")
            return
        prof = self.profile
        if self.node.find("private_layers") is None:
            _require_version(prof, _V_PRIVATE_LAYERS, "private_layers")
        self.node.set("private_layers", *[_layer_atom(n, prof) for n in names],
                      order=FOOTPRINT_ORDER)

    @property
    def net_tie_pad_groups(self) -> list[str]:
        """Группы площадок net tie (``"1, 2"`` …) или пусто. Токен есть с формата 20220818
        (KiCad 7; раньше net tie задавался словом «net tie» в ``tags``); в более старом
        формате новый список — ``ValueError``."""
        n = self.node.find("net_tie_pad_groups")
        return [] if n is None else [str(a) for a in n.atoms()]

    @net_tie_pad_groups.setter
    def net_tie_pad_groups(self, value: Iterable[str] | None) -> None:
        groups = [] if value is None else [_check_str(g, "net_tie_pad_groups") for g in value]
        if not groups:
            self.node.remove("net_tie_pad_groups")
            return
        if self.node.find("net_tie_pad_groups") is None:
            _require_version(self.profile, _V_NET_TIE_GROUPS, "net_tie_pad_groups")
        self.node.set("net_tie_pad_groups", *[Str(g) for g in groups], order=FOOTPRINT_ORDER)

    @property
    def at(self) -> tuple[float, float, float] | None:
        """Положение корпуса ``(x, y, угол)`` из ``(at …)`` (в библиотеке обычно нет) или
        ``None``; присваивание пары или тройки (угол 0 не пишется), ``None`` удаляет."""
        n = self.node.find("at")
        p = _xy_of(n)
        if p is None:
            return None
        return (p[0], p[1], _at_angle(n))

    @at.setter
    def at(self, value: tuple[float, ...] | None) -> None:
        if value is None:
            self.node.remove("at")
            return
        vals = list(value)
        if len(vals) not in (2, 3):
            raise TypeError("at: ожидается (x, y) или (x, y, угол)")
        x, y = _check_real(vals[0], "x"), _check_real(vals[1], "y")
        a = _check_real(vals[2], "angle") if len(vals) == 3 else 0.0
        n = self.node.find("at")
        if n is None:
            n = self.node.set("at", _len(x), _len(y), order=FOOTPRINT_ORDER)
        else:
            _set_xy(n, (x, y))
        _set_at_angle(n, a, always=False)

    # --- коллекции -----------------------------------------------------------------------------
    @property
    def pads(self) -> list[Pad]:
        """Площадки в порядке файла."""
        return [Pad(n, parent=self) for n in self.node.nodes("pad")]

    @property
    def graphics(self) -> list[Graphic]:
        """Графика (``fp_line``/``fp_rect``/``fp_circle``/``fp_arc``/``fp_poly``/``fp_curve``)
        в порядке файла."""
        out: list[Graphic] = []
        for n in self.node.nodes():
            cls = _GRAPHIC_CLASSES.get(n.name)
            if cls is not None and n.name.startswith("fp_"):
                out.append(cls(n, parent=self))
        return out

    @property
    def texts(self) -> list[Text]:
        """Тексты: все ``fp_text`` и поля ``property`` с текстовыми атрибутами (``at``,
        ``layer`` или ``effects``) — в KiCad 8+ это Reference, Value, Datasheet,
        Description и пользовательские поля."""
        return [Text(n, parent=self) for n in self.node.nodes()
                if n.name == "fp_text" or _is_text_property(n)]

    @property
    def fields(self) -> list[Text]:
        """Поля KiCad 8+ (``property`` с текстовыми атрибутами)."""
        return [Text(n, parent=self) for n in self.node.nodes("property") if _is_text_property(n)]

    @property
    def models(self) -> list[Model]:
        """3D-модели в порядке файла."""
        return [Model(n, parent=self) for n in self.node.nodes("model")]

    @property
    def zones(self) -> list[Node]:
        """Узлы ``zone`` (хранятся как есть)."""
        return self.node.nodes("zone")

    @property
    def groups(self) -> list[Node]:
        """Узлы ``group`` (хранятся как есть)."""
        return self.node.nodes("group")

    @property
    def unknown(self) -> list[Node]:
        """Дочерние узлы, неизвестные kicadfp (не из ``KNOWN_FOOTPRINT_CHILDREN``)."""
        return [n for n in self.node.nodes() if n.name not in KNOWN_FOOTPRINT_CHILDREN]

    def _ref_or_value(self, kind: str) -> Text | None:
        """Узел, текст которого KiCad берёт для поля Reference/Value.

        Парсер KiCad не создаёт второго поля: каждый следующий ``fp_text reference`` или
        ``property "Reference"`` переписывает первое, поэтому при дублях (validate:
        ``TEXT_DUP_FIELD``) возвращается последний узел. В KiCad 5–7 (без полей) голое
        ``(property "Reference" …)`` — просто свойство (KiCad 6/7 на текст его не
        переносят), поэтому там берётся последний ``fp_text``, а свойство — лишь если
        ``fp_text`` нет."""
        fname = _FIELD_NAMES[kind]
        nodes = _slot_nodes(self.node, fname)
        if not self.profile.text_as_property:
            fpt = [n for n in nodes if n.name == "fp_text"]
            nodes = fpt or nodes
        return Text(nodes[-1], parent=self) if nodes else None

    def _set_ref_or_value(self, kind: str, value: str) -> None:
        s = _check_str(value, kind)
        t = self._ref_or_value(kind)
        if t is not None:
            if t.text != s:
                t.text = s
            return
        layer = "F.SilkS" if kind == "reference" else "F.Fab"
        self.add(Text.new(s, kind, 0.0, -0.5 if kind == "reference" else 1.0, layer,
                          profile=self.profile))

    @property
    def reference(self) -> Text | None:
        """Текст/поле Reference (``None``, если его нет). Присваивание строки меняет текст
        (или создаёт поле/``fp_text`` в форме версии файла)."""
        return self._ref_or_value("reference")

    @reference.setter
    def reference(self, value: str) -> None:
        self._set_ref_or_value("reference", value)

    @property
    def value(self) -> Text | None:
        """Текст/поле Value (``None``, если его нет); присваивание строки — как у
        :attr:`reference`."""
        return self._ref_or_value("value")

    @value.setter
    def value(self, value: str) -> None:
        self._set_ref_or_value("value", value)

    def pad(self, number: str | int) -> Pad:
        """Первая площадка с номером ``number`` (``KeyError``, если нет)."""
        key = str(number)
        for n in self.node.nodes("pad"):
            a = n.atom(0)
            if a is not None and str(a) == key:
                return Pad(n, parent=self)
        raise KeyError(f"нет площадки с номером {key!r}")

    def pads_by_number(self, number: str | int) -> list[Pad]:
        """Все площадки с номером ``number`` (в KiCad они образуют один вывод)."""
        key = str(number)
        return [p for p in self.pads if p.number == key]

    # --- добавление и удаление ------------------------------------------------------------------
    def _ids(self) -> set[str]:
        out: set[str] = set()
        for n in self.node.nodes():
            v = _get_id(n)
            if v:
                out.add(v)
        return out

    def add(self, item: Any) -> Any:
        """Добавить элемент (:class:`Pad`, :class:`Graphic`, :class:`Text`, :class:`Model`
        или узел) в конец его группы (:func:`kicadfp.format_rules.insert_in_group`).

        Если профиль представления отличается от профиля корпуса, узел приводится к форме
        корпуса (идентификатор ``uuid``/``tstamp``, ``stroke``/``width``, ``fill``, кавычки
        слоёв, формы ``hide``/``locked``/``unlocked``, ``fp_text`` ↔ ``property``, форма
        дуги, ``(at)``/``(offset)`` модели …). «Голый» узел добавляется как есть.
        Совпадающий с уже имеющимся идентификатор заменяется новым ``uuid4``. После
        добавления представление пишет по профилю корпуса. Возвращает ``item``.

        Узел не копируется: представление, всё ещё входящее в другой корпус (его
        ``parent`` содержит узел), — ``ValueError`` (добавьте ``item.copy()`` или сначала
        ``remove()``), иначе один узел оказался бы в двух деревьях, а приведение к профилю
        испортило бы исходный корпус. «Голый» узел ``Node`` из чужого дерева так не
        распознаётся — его копирует вызывающий. Представление с конструкциями, которых нет
        в версии формата корпуса (``fp_rect`` и заливка в KiCad 5, ``knockout``,
        ``face``, ``thermal_bridge_angle`` в KiCad 6 …), — ``ValueError`` (нужен
        :meth:`upgrade`). Скрытый пользовательский ``fp_text`` в корпусе KiCad 8+
        становится скрытым полем ``FieldN`` (см. :attr:`Text.hide`); автоматическое имя
        ``FieldN``, совпавшее с именем имеющегося поля, заменяется свободным.
        """
        if isinstance(item, Footprint):
            raise TypeError("корпус нельзя добавить в корпус")
        if isinstance(item, View):
            node = item.node
            src: FormatProfile | None = item.profile
        elif isinstance(item, Node):
            node = item
            src = None
        else:
            raise TypeError(f"нельзя добавить {type(item).__name__} в корпус")
        if node.name in _ROOT_NAMES:
            raise TypeError("корпус нельзя добавить в корпус")
        if any(x is node for x in self.node.items):
            raise ValueError("элемент уже входит в этот корпус")
        owner = item._parent if isinstance(item, View) else None
        if owner is not None and _contains(owner.node, node):
            if owner is self:
                raise ValueError("элемент уже входит в этот корпус")
            raise ValueError("элемент входит в другой корпус: добавьте его копию "
                             "(item.copy()) или сначала удалите его из исходного корпуса "
                             "(remove())")
        dst = self.profile
        if src is not None:
            bad = _unsupported_constructs(node, src, dst)
            if bad:
                raise ValueError(f"элемент содержит то, чего нет в формате корпуса (версия "
                                 f"{dst.version or 'KiCad 5'}): {', '.join(bad)} — выполните "
                                 f"Footprint.upgrade()")
        if src is not None and src != dst:
            _convert_element(node, src, dst)
        if node.name == "fp_text":
            _hidden_text_to_field(node, dst, self.node)
        elif node.name == "property":
            name = str(node.atom(0) or "")
            if _is_auto_field_name(name) and any(
                    str(n.atom(0) or "") == name for n in self.node.nodes("property")):
                node.set_atom(0, Str(_free_field_name(self.node)))
        _check_free_slot(self.node, _field_slot(node), node)
        ident = _get_id(node)
        if ident and ident in self._ids():
            _set_id(node, _new_uuid(), dst, None)
        insert_in_group(self.node, node)
        if isinstance(item, View):
            item._parent = self
            item._profile = None
        return item

    def remove(self, item: View | Node) -> None:
        """Удалить элемент (по идентичности узла); ``ValueError``, если его нет в корпусе.
        Представление остаётся над (уже отдельным) узлом с профилем корпуса."""
        node = item.node if isinstance(item, View) else item
        for i, x in enumerate(self.node.items):
            if x is node:
                del self.node.items[i]
                break
        else:
            raise ValueError("элемент не входит в этот корпус")
        if isinstance(item, View):
            item._profile = self.profile
            item._parent = None

    def new_pad(self, number: str | int, type: str = "thru_hole", shape: str = "circle",
                x: float = 0.0, y: float = 0.0, size: float | tuple[float, float] = (1.6, 1.6),
                drill: Any = None, layers: Iterable[str] | str | None = None,
                angle: float = 0.0, **kw: Any) -> Pad:
        """Создать площадку (:meth:`Pad.new` в профиле корпуса) и добавить её."""
        return self.add(Pad.new(number, type, shape, x, y, size, drill=drill, layers=layers,
                                angle=angle, profile=self.profile, **kw))

    def new_line(self, start: Point, end: Point, layer: str = "F.SilkS", width: float = 0.12,
                 **kw: Any) -> Line:
        """Создать и добавить отрезок."""
        return self.add(Line.new(start, end, layer, width, profile=self.profile, **kw))

    def new_rect(self, start: Point, end: Point, layer: str = "F.SilkS", width: float = 0.12,
                 fill: bool | None = None, **kw: Any) -> Rect:
        """Создать и добавить прямоугольник."""
        return self.add(Rect.new(start, end, layer, width, fill=fill, profile=self.profile, **kw))

    def new_circle(self, center: Point, radius: float | None = None, layer: str = "F.SilkS",
                   width: float = 0.12, fill: bool | None = None, **kw: Any) -> Circle:
        """Создать и добавить окружность (центр и радиус или ``end=``)."""
        return self.add(Circle.new(center, radius, layer, width, fill=fill,
                                   profile=self.profile, **kw))

    def new_arc(self, start: Point, mid: Point, end: Point, layer: str = "F.SilkS",
                width: float = 0.12, **kw: Any) -> Arc:
        """Создать и добавить дугу по трём точкам."""
        return self.add(Arc.new(start, mid, end, layer, width, profile=self.profile, **kw))

    def new_poly(self, points: Iterable[Point], layer: str = "F.SilkS", width: float = 0.12,
                 fill: bool | None = None, **kw: Any) -> Poly:
        """Создать и добавить многоугольник."""
        return self.add(Poly.new(points, layer, width, fill=fill, profile=self.profile, **kw))

    def new_curve(self, points: Sequence[Point], layer: str = "F.SilkS", width: float = 0.12,
                  **kw: Any) -> Curve:
        """Создать и добавить кривую Безье (4 точки)."""
        return self.add(Curve.new(points, layer, width, profile=self.profile, **kw))

    def new_text(self, text: str, kind: str = "user", x: float = 0.0, y: float = 0.0,
                 layer: str = "F.SilkS", **kw: Any) -> Text:
        """Создать и добавить текст (:meth:`Text.new` в профиле корпуса)."""
        return self.add(Text.new(text, kind, x, y, layer, profile=self.profile, **kw))

    def new_model(self, path: str, **kw: Any) -> Model:
        """Создать и добавить 3D-модель."""
        return self.add(Model.new(path, profile=self.profile, **kw))

    # --- геометрия ---------------------------------------------------------------------------------
    def bbox(self, layers: Iterable[str] | str | None = None, include_texts: bool = False,
             *, include_pads: bool = False) -> BBox:
        """Габариты: объединение габаритов площадок и графики на слоях ``layers``
        (``None`` — на всех; групповые обозначения ``*.CrtYd``, ``*.Cu`` раскрываются и в
        фильтре, и в слоях площадок); с ``include_texts=True`` — ещё видимых текстов
        (приближённо, см. :func:`_text_bbox`). Площадка учитывается, если её слои
        пересекаются с ``layers`` (площадка ``*.Cu`` попадает в ``bbox(layers=["B.Cu"])``,
        площадка только на B.Cu в ``bbox(layers=["F.Cu"])`` — нет).

        ``include_pads=True`` — все площадки учитываются независимо от фильтра ``layers``
        (так генераторы строят область размещения: площадки плюс контур F.Fab).
        Графика — геометрически, без ширины линий. Пустой корпус (или ничего на
        выбранных слоях) — ``BBox(0, 0, 0, 0)``."""
        wanted: set[str] | None = None
        if layers is not None:
            wanted = set(_L.expand(_layer_list(layers)))
        boxes: list[BBox | None] = []
        for p in self.pads:
            if (wanted is None or include_pads
                    or any(ly in wanted for ly in _L.expand(p.layers))):
                boxes.append(p.bbox())
        for g in self.graphics:
            if wanted is None or any(ly in wanted for ly in g.layers):
                boxes.append(g.bbox())
        if include_texts:
            for t in self.texts:
                if t.hide or t.node.find("at") is None:
                    continue
                if wanted is None or t.layer in wanted:
                    boxes.append(_text_bbox(t))
        out = _bbox_union(boxes)
        return _round_bbox(out) if out is not None else BBox(0.0, 0.0, 0.0, 0.0)

    def _other_drawings(self) -> list[Node]:
        """Элементы секции рисования без собственного представления (fp_text_box, image,
        dimension, table, barcode, point, эллипсы) и зоны."""
        return [n for n in self.node.nodes()
                if n.name in _GENERIC_GEOMETRY or n.name == "zone"]

    def move(self, dx: float, dy: float, *, models: bool = True) -> None:
        """Сдвинуть все элементы (площадки, графику, тексты и поля, зоны, прочие элементы
        рисования) на ``(dx, dy)``. ``models=True`` — сдвинуть и смещение 3D-моделей
        (``offset.x += dx``, ``offset.y -= dy``: ось Y модели направлена вверх), как
        ``FOOTPRINT::MoveAnchorPosition`` KiCad, чтобы модель осталась на своём месте
        относительно площадок. Положение корпуса ``(at …)`` не меняется."""
        dx, dy = _check_real(dx, "dx"), _check_real(dy, "dy")
        if dx == 0 and dy == 0:
            return
        for p in self.pads:
            p.move(dx, dy)
        for g in self.graphics:
            g.move(dx, dy)
        for t in self.texts:
            if t.node.find("at") is not None:
                t.move(dx, dy)
        for n in self._other_drawings():
            _deep_move(n, dx, dy)
        if models:
            for m in self.models:
                ox, oy, oz = m.offset
                m.offset = (ox + dx, oy - dy, oz)

    def rotate(self, angle: float, origin: Point = (0.0, 0.0), *, models: bool = True) -> None:
        """Повернуть все элементы на ``angle`` градусов вокруг ``origin`` (площадки и тексты —
        и собственный угол; прямоугольники на угол, не кратный 90°, становятся
        многоугольниками, как в KiCad). ``models=True`` — повернуть и 3D-модели: смещение
        поворачивается вместе с элементами, ``rotate.z`` уменьшается на ``angle``
        (KiCad применяет поворот модели со знаком минус, см. ``render_3d_opengl.cpp``)."""
        a = _check_real(angle, "angle")
        o = _as_point(origin, "origin")
        if a == 0:
            return
        for p in self.pads:
            p.rotate(a, o)
        for g in self.graphics:
            g.rotate(a, o)
        for t in self.texts:
            if t.node.find("at") is not None:
                t.rotate(a, o)
        for n in self._other_drawings():
            _deep_rotate(n, a, o)
        if models:
            for m in self.models:
                ox, oy, oz = m.offset
                px, py = _geo.rotate_point((ox, -oy), a, o)
                m.offset = (px, -py, oz)
                rx, ry, rz = m.rotate
                m.rotate = (rx, ry, _geo.normalize_angle_180(rz - a))

    def flip(self) -> None:
        """Перенести корпус на другую сторону платы, как «Flip» редактора KiCad
        (``FOOTPRINT::Flip`` с ``FLIP_DIRECTION::LEFT_RIGHT``).

        KiCad 9 выполняет зеркалирование TOP_BOTTOM с последующим поворотом корпуса на
        180°; для файла библиотеки (ориентация корпуса 0) тот же результат выражается без
        ориентации: ``x -> -x`` относительно (0, 0) у всех элементов; слои всех элементов
        и корпуса F.* ↔ B.*; углы площадок и текстов ``a -> -a`` (нормализуются в
        [0, 360)); у площадок отражаются по X смещение отверстия, дельта трапеции, фаски
        и примитивы (``PAD::Flip``); текстам на слоях одной стороны переключается
        ``justify mirror`` (``PCB_TEXT::Flip``). «Удержание вертикально» (KeepUpright)
        не применяется; 3D-модели и приватные слои не меняются (сторону модели KiCad
        определяет по слою корпуса)."""
        prof = self.profile
        layer = self.layer
        flipped = _L.flip_layer(layer)
        if flipped != layer:
            self.layer = flipped
        for p in self.pads:
            p._flip_x()
        for g in self.graphics:
            g.mirror("x", 0.0)
            _flip_layer_nodes(g.node, prof)
        for t in self.texts:
            t._flip_x()
        for n in self._other_drawings():
            _deep_mirror_x(n)
            _flip_layer_nodes(n, prof)

    def renumber_pads(self, rule: str | Callable[[int, Pad], str] = "sequential", start: int = 1,
                      order: str = "file", *, skip_npth: bool = True,
                      skip_unnumbered: bool = True, group_same: bool = True) -> None:
        """Перенумеровать выводы (площадки).

        Нумеруются *выводы*, а не отдельные площадки:

        * ``skip_unnumbered=True`` (по умолчанию) — площадки с пустым номером (апертуры
          пасты, монтажные отверстия) и площадки без медных слоёв (у KiCad это не выводы)
          в нумерацию не входят и первыми не считаются;
        * ``group_same=True`` (по умолчанию) — площадки с одинаковым номером (несколько
          площадок одного вывода, EP с переходными отверстиями) — один вывод и получают
          один общий новый номер (отображение «старый номер -> новый»); площадки без меди с
          тем же непустым номером (например, апертура пасты с номером EP) получают новый
          номер своего вывода, чтобы связь не рвалась; ``group_same=False`` — каждая
          площадка отдельно (с пустым номером — всегда отдельно);
        * ``skip_npth`` — площадки ``np_thru_hole`` не трогаются вовсе.

        ``order``: ``"file"`` — порядок первого появления вывода в файле; ``"xy"`` — по X,
        затем по Y; ``"yx"`` — по Y, затем по X; ``"circular"`` — против часовой стрелки на
        экране вокруг центра выводов, начиная с первого нумеруемого вывода файла, не
        стоящего в центре (для DIP и QFP это стандартная нумерация); выводы в центре (EP:
        одна из площадок накрывает центр) — последними, в порядке удаления от центра.
        Положение вывода из нескольких площадок — среднее их положений.
        ``rule``: ``"sequential"`` — ``start, start+1, …``; ``"prefix:A"`` — ``A1, A2, …``
        (с ``start``); функция ``(индекс, площадка) -> номер`` (индекс с 0 в порядке
        ``order``, площадка — первая площадка вывода в файле).
        """
        def has_copper(p: Pad) -> bool:
            return any(_L.is_copper(ly) for ly in p.layers)

        all_pads = [p for p in self.pads if not (skip_npth and p.type == "np_thru_hole")]
        groups: dict[Any, list[Pad]] = {}
        for idx, p in enumerate(all_pads):
            num = p.number
            if skip_unnumbered and (num == "" or not has_copper(p)):
                continue
            key: Any = ("num", num) if group_same and num != "" else ("pad", idx)
            groups.setdefault(key, []).append(p)
        keys = list(groups)

        def pos(k: Any) -> Point:
            ps = groups[k]
            return (sum(q.x for q in ps) / len(ps), sum(q.y for q in ps) / len(ps))

        if order == "file":
            seq = keys
        elif order == "xy":
            seq = sorted(keys, key=lambda k: (_nm(pos(k)[0]), _nm(pos(k)[1])))
        elif order == "yx":
            seq = sorted(keys, key=lambda k: (_nm(pos(k)[1]), _nm(pos(k)[0])))
        elif order == "circular":
            if keys:
                pts = {k: pos(k) for k in keys}
                cx = sum(x for x, _ in pts.values()) / len(pts)
                cy = sum(y for _, y in pts.values()) / len(pts)
                c = (cx, cy)

                def at_center(k: Any) -> bool:
                    # вывод в центре (EP): одна из его площадок накрывает центр
                    if _geo.distance(c, pts[k]) < 1e-6:
                        return True
                    for q in groups[k]:
                        b = q.bbox()
                        if b.x1 < cx < b.x2 and b.y1 < cy < b.y2:
                            return True
                    return False

                first = next((k for k in keys if not at_center(k)), keys[0])
                a0 = _geo.angle_of(c, pts[first])
                seq = sorted(keys, key=lambda k: (
                    at_center(k),
                    0.0 if at_center(k) else
                    round(_geo.normalize_angle(_geo.angle_of(c, pts[k]) - a0), 9),
                    _geo.distance(c, pts[k])))
            else:
                seq = []
        else:
            raise ValueError(f"неизвестный порядок {order!r} (file, xy, yx, circular)")
        start = _check_int(start, "start")
        if callable(rule):
            names = [str(rule(i, groups[k][0])) for i, k in enumerate(seq)]
        elif rule == "sequential":
            names = [str(start + i) for i in range(len(seq))]
        elif isinstance(rule, str) and rule.startswith("prefix:"):
            prefix = rule[len("prefix:"):]
            names = [f"{prefix}{start + i}" for i in range(len(seq))]
        else:
            raise ValueError(f"неизвестное правило нумерации {rule!r} "
                             f"(sequential, prefix:X или функция)")
        mapping: dict[str, str] = {}
        assigned: set[int] = set()
        for k, name in zip(seq, names):
            for p in groups[k]:
                assigned.add(id(p.node))
                if k[0] == "num":
                    mapping[p.number] = name
                if p.number != name:
                    p.number = name
        if group_same:
            # площадки без меди с номером вывода (апертуры пасты EP и т.п.) идут за выводом
            for p in all_pads:
                if id(p.node) not in assigned and p.number != "" and p.number in mapping:
                    new_name = mapping[p.number]
                    if p.number != new_name:
                        p.number = new_name

    # --- проверка, запись, копирование ------------------------------------------------------------
    def validate(self, strict: bool = False) -> list[Any]:
        """Проверка (:func:`kicadfp.validate.validate`); пока модуля проверок нет — ``[]``."""
        try:
            mod = importlib.import_module("kicadfp.validate")
        except ModuleNotFoundError as e:
            if e.name in ("kicadfp.validate", "kicadfp"):
                return []
            raise
        return list(mod.validate(self, strict=strict))

    def to_sexpr(self) -> Node:
        """Корневой узел (не копия)."""
        return self.node

    def dumps(self, style: str = "auto", *, final_newline: bool | None = None) -> str:
        """Текст файла в стиле KiCad (``auto`` — по версии файла, см. :func:`kicadfp.sexpr.dumps`).

        ``final_newline``: ``None`` — как в исходном файле (:attr:`final_newline`),
        ``True``/``False`` — с завершающим ``\n`` или без него."""
        text = _sexpr.dumps(self.node, style=style, version=self.version)
        nl = self.final_newline if final_newline is None else bool(final_newline)
        if not nl and text.endswith("\n"):
            text = text[:-1]
        return text

    def copy(self) -> Footprint:
        """Корпус над глубокой копией дерева (с тем же :attr:`final_newline`)."""
        return Footprint(self.node.copy(), final_newline=self.final_newline)

    def upgrade(self, version: int = DEFAULT_VERSION, *,
                generator: str | None = DEFAULT_GENERATOR) -> None:
        """Перевести корпус в формат версии ``version`` (не ниже текущей) так, как это делает
        KiCad при пересохранении (``kicad-cli fp upgrade``).

        Корень ``module`` → ``footprint``; ``(version …)``; ``generator`` (``generator=None`` —
        сохранить прежний) в кавычках (8+) и ``generator_version``; ``tedit`` удаляется
        (с 20220225); ``tstamp`` → ``(uuid "…")`` (8+), новые ``uuid4`` элементам без
        идентификатора (KiCad 5); ``fp_text reference/value`` → поля ``property``, свойства
        KiCad 6/7 → скрытые поля на F.Fab (``ki_description`` → Description,
        ``Sheetfile``/``Sheetname`` → токены, ``ki_keywords``/``ki_locked`` удаляются) и
        служебные поля KiCad (Datasheet, Description …); ``(width)`` → ``(stroke (width)
        (type solid))``; ``fill`` в форме версии (и явный ``fill`` у rect/circle/poly);
        голые ``hide``/``unlocked``/``bold``/``italic`` → ``(… yes)``; ``locked`` корпуса и
        элементов удаляется (вне платы KiCad блокировку не хранит); кавычки строк и слоёв;
        дуги ``(angle)`` → ``mid`` и единое направление обхода (как
        ``EDA_SHAPE::SetArcGeometry``); модель ``(at (xyz))`` (дюймы, ×25.4f) → ``(offset
        (xyz))`` (мм); ``%R``/``%V`` → ``${REFERENCE}``/``${VALUE}``; углы текстов KiCad 9
        нормализует в [0, 360); текстам без толщины — 0.15 мм (KiCad 9); ``(attr virtual)`` →
        ``exclude_from_pos_files exclude_from_bom``, корпус KiCad 5 без атрибутов →
        ``(attr through_hole)``; ``solder_paste_ratio`` → ``solder_paste_margin_ratio``
        (9+); устаревшие ``autoplace_cost*``/``thermal_*`` корпуса удаляются (7+); номера
        ``np_thru_hole`` и апертур стираются, custom-площадке с круглым якорем из KiCad 5/6 —
        ``(thermal_bridge_angle 90)``; старый net tie (``tags "net tie…"``) →
        ``net_tie_pad_groups``; ``(embedded_fonts no)`` (9+); нулевые ``clearance``/
        ``solder_*_margin``/``solder_paste_*ratio`` корпуса и площадок из файла версии
        <= 20240201 удаляются (там 0 — «наследовать»); скрытый ``fp_text user`` в 8+
        становится скрытым полем ``FieldN`` (как делает парсер KiCad 9; kicad-cli 9.0.1
        такой текст теряет — здесь kicadfp намеренно от него отличается);
        ``(duplicate_pad_numbers_are_jumpers no)`` (10); числа — как их пишет KiCad (длины с
        округлением до нанометра); порядок узлов — как у writer'а KiCad (поля,
        ``cmp_drawings``, ``cmp_pads``).

        Проверено сравнением с ``kicad-cli fp upgrade`` (KiCad 9.0.1) на 15 894 файлах
        официальных библиотек v6.0.0–v9.0.0 (форматы KiCad 5–9): деревья совпадают (кроме
        значений новых ``uuid`` и ``generator``) везде, кроме зон (keepout в 8 файлах: KiCad
        переписывает зону целиком, kicadfp сохраняет её как есть) и неизвестного имени слоя
        (1 файл: KiCad пишет ``Rescue``, kicadfp сохраняет исходное имя).
        """
        v = _check_int(version, "version")
        src = self.profile
        cur = self.version if self.node.name != "module" else None
        if cur is not None and v < cur:
            raise ValueError(f"понижение версии формата ({cur} -> {v}) не поддерживается")
        # файл, пересохранённый KiCad 8.0.2+, всегда оканчивается переводом строки
        self.final_newline = True
        root = self.node
        dst = _profile(v, "footprint")
        old_attrs_default_th = src.version < _V_ATTR_FLAGS
        root.name = "footprint"
        a0 = root.atom(0)
        if a0 is not None and not isinstance(a0, Str):
            root.set_atom(0, Str(str(a0)))
        root.set("version", Sym(str(v)), order=FOOTPRINT_ORDER)
        gen = generator if generator is not None else (self.generator or DEFAULT_GENERATOR)
        root.set("generator", _generator_atom(gen, dst), order=FOOTPRINT_ORDER)
        if dst.has_generator_version:
            gv = _generator_version_for(gen, v)
            if gv is None and generator is None:
                gv = self.generator_version
            if gv:
                root.set("generator_version", Str(gv), order=FOOTPRINT_ORDER)
            else:
                root.remove("generator_version")
        else:
            root.remove("generator_version")
        _move_bool(root, "placed", dst, FOOTPRINT_ORDER)
        ln = root.find("layer")
        if ln is None:
            root.set("layer", _layer_atom("F.Cu", dst), order=FOOTPRINT_ORDER)
        else:
            _requote_layers(Node("_", [ln]), dst)
        if not dst.has_tedit:
            root.remove("tedit")
        _convert_id(root, dst, FOOTPRINT_ORDER, required=False)
        # строки корня KiCad 6+ пишет в кавычках (KiCad 5 — только при необходимости)
        for token in ("descr", "tags", "path", "sheetname", "sheetfile"):
            n = root.find(token)
            a = None if n is None else n.atom(0)
            if a is not None and not isinstance(a, Str):
                n.set_atom(0, Str(str(a)))  # type: ignore[union-attr]
        # коэффициент пасты корпуса
        want = dst.solder_paste_ratio_token
        other = ("solder_paste_ratio" if want == "solder_paste_margin_ratio"
                 else "solder_paste_margin_ratio")
        on = root.find(other)
        if on is not None and root.find(want) is None:
            on.name = want
        if v >= V_KICAD7:
            for token in ("autoplace_cost90", "autoplace_cost180", "thermal_width", "thermal_gap"):
                root.remove(token)
        pl = root.find("private_layers")
        if pl is not None:
            pl.items = [_layer_atom(str(a), dst) if not isinstance(a, Node) else a for a in pl.items]
        # атрибуты
        an = root.find("attr")
        flags = [str(a) for a in an.atoms()] if an is not None else []
        if "virtual" in flags:
            flags = [f for f in flags if f != "virtual"] + ["exclude_from_pos_files", "exclude_from_bom"]
        if not flags and old_attrs_default_th:
            flags = ["through_hole"]
        if flags:
            atoms = [Sym(a) for a in ATTR_ORDER if a in flags and a != "virtual"]
            atoms += [Sym(f) for f in flags if f not in ATTR_ORDER]
            if an is None:
                root.insert(Node("attr", atoms), order=FOOTPRINT_ORDER)
            else:
                an.items = atoms  # type: ignore[assignment]
        # свойства KiCad 6/7 -> поля KiCad 8+
        if dst.text_as_property and src.version < V_FIELDS:
            _merge_legacy_ref_value(root, src, dst)
            for n in list(root.nodes("property")):
                if _is_text_property(n):
                    continue
                pname = str(n.atom(0) or "")
                pval = str(n.atom(1) or "")
                if pname in ("ki_keywords", "ki_locked"):
                    root.remove_child(n)
                elif pname == "ki_description":
                    root.remove_child(n)
                    root.append(_field_node("Description", pval, dst))
                elif pname in ("Sheetfile", "Sheet file", "Sheetname", "Sheet name"):
                    root.remove_child(n)
                    token = "sheetfile" if pname.startswith("Sheetf") or pname == "Sheet file" \
                        else "sheetname"
                    if pval:
                        root.set(token, Str(pval), order=FOOTPRINT_ORDER)
                elif pname == "ki_fp_filters":
                    continue
                else:
                    field = _field_node(pname, pval, dst)
                    n.items = field.items
        # элементы
        for n in list(root.nodes()):
            if n.name == "property" and not _is_text_property(n):
                continue
            _convert_element(n, src, dst)
        # KiCad 8+: скрытый fp_text user -> скрытое поле (как парсер KiCad 9)
        for n in list(root.nodes("fp_text")):
            _hidden_text_to_field(n, dst, root)
        # nullable overrides: в файлах <= 20240201 ноль у зазоров/масок — «не задано»;
        # KiCad его не пишет (5–8) или читает как отсутствие (9+) — токен исчезает
        if src.version <= _V_NULLABLE:
            _drop_null_overrides(root, _FP_OVERRIDES)
            for n in root.nodes("pad"):
                _drop_null_overrides(n, _PAD_OVERRIDES)
        # блокировка вне платы смысла не имеет: KiCad сбрасывает её у корпуса при чтении
        # (FOOTPRINT::SetLocked(false)), а у элементов библиотечного корпуса
        # BOARD_ITEM::IsLocked() ложно — при записи locked не появляется нигде
        for n in [root] + [x for x in root.nodes() if x.name in KNOWN_FOOTPRINT_CHILDREN]:
            if _bool_token(n, "locked") is not None:
                _drop_bool(n, "locked")
        # служебные поля KiCad 8+
        fields = _mandatory_fields(v)
        if fields:
            names = [str(n.atom(0) or "") for n in root.nodes("property")]
            if v >= V_FILL_YESNO and "Footprint" in names:
                for n in list(root.nodes("property")):
                    if str(n.atom(0) or "") == "Footprint":
                        root.remove_child(n)
            for fname in fields:
                if fname not in names:
                    if fname in ("Reference", "Value"):
                        layer = "F.SilkS" if fname == "Reference" else "F.Fab"
                        value = "REF**" if fname == "Reference" else self.name
                        root.append(_field_node(fname, value, dst, layer=layer, hide=False))
                    else:
                        root.append(_field_node(fname, "", dst))
        if v >= _V_EMBEDDED:
            if root.find("embedded_fonts") is None:
                root.insert(Node("embedded_fonts", [Sym("no")]), order=FOOTPRINT_ORDER)
        else:
            root.remove("embedded_fonts")
        if v >= _V_JUMPERS and root.find("duplicate_pad_numbers_are_jumpers") is None:
            root.insert(Node("duplicate_pad_numbers_are_jumpers", [Sym("no")]),
                        order=FOOTPRINT_ORDER)
        # площадки: семантика парсера KiCad при чтении старых версий и порядок слоёв writer'а
        for n in root.nodes("pad"):
            _upgrade_pad_semantics(n, src.version, dst)
            ls = n.find("layers")
            if ls is not None:
                names = [str(a) for a in ls.atoms()]
                ordered = _writer_layer_order(names, dst)
                if ordered != names:
                    ls.items = [_layer_atom(x, dst, in_list=True) for x in ordered]
        # старые net tie (до 20220815): ключевое слово «net tie» в tags -> группа из всех площадок
        if src.version <= _V_LEGACY_NET_TIES < v and root.find("net_tie_pad_groups") is None \
                and self.tags.startswith("net tie"):
            group = ", ".join(str(n.atom(0) or "") for n in root.nodes("pad"))
            if group:
                root.insert(Node("net_tie_pad_groups", [Str(group)]), order=FOOTPRINT_ORDER)
        for n in root.nodes():
            if n.name in KNOWN_FOOTPRINT_CHILDREN:
                _normalize_numbers(n)
            if n.name == "fp_arc":
                _normalize_arc_winding(n)
            elif n.name == "pad":
                prims = n.find("primitives")
                for g in [] if prims is None else prims.nodes("gr_arc"):
                    _normalize_arc_winding(g)
        _sort_root_like_kicad(root, v)

    def __repr__(self) -> str:
        return (f"Footprint({self.name!r}, version={self.version}, pads={len(self.node.nodes('pad'))}, "
                f"graphics={len(self.graphics)})")


def view_for(node: Node, profile: FormatProfile | None = None,
             parent: Footprint | None = None) -> View:
    """Представление подходящего класса над узлом (``pad`` → :class:`Pad`, ``fp_line`` →
    :class:`Line`, ``fp_text``/``property`` → :class:`Text`, ``model`` → :class:`Model`,
    ``drill`` → :class:`Drill`, ``footprint``/``module`` → :class:`Footprint` …);
    ``ValueError`` для неизвестного узла."""
    if node.name in _ROOT_NAMES:
        return Footprint(node)
    cls: type[View] | None = _GRAPHIC_CLASSES.get(node.name)
    if cls is None:
        cls = {"pad": Pad, "drill": Drill, "fp_text": Text, "property": Text,
               "model": Model}.get(node.name)
    if cls is None:
        raise ValueError(f"нет представления для узла {node.name!r}")
    return cls(node, profile, parent)
