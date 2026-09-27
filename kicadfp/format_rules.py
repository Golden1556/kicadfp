"""Таблицы правил формата на тип узла и профили версий (требование ТЗ 7.3).

Здесь описано, **в каком порядке** KiCad записывает дочерние токены каждого узла
(чтобы новые токены вставлялись в «правильное» место, а не в конец), какие узлы
образуют группы внутри корпуса (новые элементы добавляются в конец своей группы)
и чем отличаются версии формата (:class:`FormatProfile`). Порядок взят из
исходников writer'а KiCad (``pcb_io_kicad_sexpr.cpp`` 8.0/9.0/10.0, ``pcb_plugin.cpp``
6.0/7.0, ``kicad_plugin.cpp`` 5.1) и дополнен устаревшими и новыми (10.0, master)
токенами в тех позициях, где их пишут соответствующие версии. Расширение на новые
типы файлов — добавлением новых таблиц, без изменения ядра.

Порядок координат в графике (``start``, ``center``, ``mid``, ``end``) для KiCad не
косметика: парсер требует именно такую последовательность (``fp_arc``: start, mid,
end; ``fp_circle``: center, end), иначе файл не читается.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .sexpr import Node, Sym

__all__ = [
    "FormatProfile", "profile_for", "DEFAULT_VERSION", "DEFAULT_GENERATOR",
    "FOOTPRINT_ORDER", "PAD_ORDER", "TEXT_ORDER", "TEXT_ORDER_V6", "GRAPHIC_ORDER",
    "GRAPHIC_ORDER_V8", "GRAPHIC_ORDER_V7", "GRAPHIC_ORDER_V6", "MODEL_ORDER",
    "EFFECTS_ORDER", "FONT_ORDER", "DRILL_ORDER", "STROKE_ORDER", "ATTR_ORDER", "GROUPS",
    "GRAPHIC_NAMES", "TEXT_NAMES", "KNOWN_FOOTPRINT_CHILDREN", "group_of",
    "insert_in_group", "order_for", "DRAWING_GROUPS", "DRAWING_TYPE_RANK",
    "DRAWING_TYPE_RANK_V6", "SHAPE_RANK", "drawing_sort_key", "positional_atoms",
    "flag_slot", "POSITIONAL_ATOMS", "LOCKED_SLOT",
]

# Версия формата для новых корпусов — KiCad 9.0 (SEXPR_BOARD_FILE_VERSION 20241229).
DEFAULT_VERSION = 20241229
DEFAULT_GENERATOR = "kicadfp"

# --- пороги версий (номера из pcb_io_kicad_sexpr.h / pcb_plugin.h) ---------------------
V_LEGACY_ARC = 20210925       # LEGACY_ARC_FORMATTING: версии <= — дуги center/end/angle
V_ARC_MID = V_LEGACY_ARC + 1  # первая версия с дугами start/mid/end (парсер: > 20210925)
V_STROKE = 20211229           # (stroke (width) (type)) вместо (width)
V_NO_TEDIT = 20220225         # tedit удалён
V_KICAD7 = 20221018           # KiCad 7.0: групповые слои площадок в кавычках ("*.Cu")
V_FIELDS = 20230620           # Reference/Value как (property …) с текстовыми атрибутами
V_NORMALIZED = 20231014       # «V8 file format normalization»: uuid, (hide yes), кавычки
V_PASTE_RATIO = 20240225      # solder_paste_margin_ratio у корпуса (вместо solder_paste_ratio)
V_FILL_YESNO = 20241129       # «Normalise … fill properties»: (fill yes|no) вместо solid|none;
                              # с 9.0 же (locked yes) у графики стоит после fill, а не до stroke

# Порядок графики KiCad 5.1/6.0: голый флаг locked сразу после имени узла (парсер 6/7
# принимает его только там), координаты, layer, width, fill, tstamp. Хвостовые
# токены новых версий — в конце, на случай смешанных файлов.
GRAPHIC_ORDER_V6: tuple[str, ...] = (
    "locked", "start", "center", "mid", "end", "pts", "angle", "layer", "width", "fill",
    "tstamp", "uuid", "stroke", "net", "solder_mask_margin",
)
# KiCad 7.0 (20211229 <= v < 20231014): locked (флаг), координаты, stroke, fill, layer, tstamp.
GRAPHIC_ORDER_V7: tuple[str, ...] = (
    "locked", "start", "center", "mid", "end", "pts", "angle", "stroke", "width", "fill",
    "layer", "tstamp", "uuid", "net", "solder_mask_margin",
)
# KiCad 8.0 (20231014 <= v < 20241129): координаты, (locked yes), stroke, fill, layer, net, uuid.
GRAPHIC_ORDER_V8: tuple[str, ...] = (
    "start", "center", "mid", "end", "pts", "angle", "locked", "stroke", "width", "fill",
    "layer", "layers", "net", "uuid", "tstamp", "solder_mask_margin",
)
# KiCad 9.0+: координаты, stroke, fill, (locked yes), layer|layers, solder_mask_margin, net,
# uuid. Токены master (после 10.0): эллипсы (center, major_radius, minor_radius,
# rotation_angle, start_angle, end_angle), radius у fp_rect, start_shape/end_shape,
# custom_property.
GRAPHIC_ORDER: tuple[str, ...] = (
    "start", "center", "major_radius", "minor_radius", "rotation_angle", "start_angle",
    "end_angle", "mid", "end", "radius", "pts", "angle", "stroke", "width", "start_shape",
    "end_shape", "fill", "locked", "layer", "layers", "solder_mask_margin", "net", "uuid",
    "tstamp", "custom_property",
)

# property/fp_text в KiCad 8+: (locked yes) (только fp_text), at, (unlocked yes), layer,
# (hide yes) (только property), uuid, effects, render_cache.
TEXT_ORDER: tuple[str, ...] = (
    "locked", "at", "unlocked", "layer", "knockout", "hide", "uuid", "tstamp", "effects",
    "render_cache",
)
# fp_text в KiCad 5–7: TYPE [locked] "TEXT" (at x y [a] [unlocked]) (layer L [knockout])
# [hide] (effects …) (tstamp …) [render_cache]. Голый locked — позиционный (между типом
# и текстом) и рангом не выражается: его место задаёт flag_slot (см. Node.set_flag).
TEXT_ORDER_V6: tuple[str, ...] = (
    "at", "unlocked", "layer", "knockout", "hide", "effects", "tstamp", "uuid", "render_cache",
)


@dataclass(frozen=True)
class FormatProfile:
    """Особенности записи, зависящие от версии формата файла.

    Поля сверх контракта (architecture.md §4): ``has_tedit``, ``has_generator_version``,
    ``text_order``, ``graphic_order``, ``fill_style``, ``quoted_wildcards``.

    * ``quoted_layers`` — имена слоёв в ``(layer …)``/``(layers …)`` в кавычках: так пишет
      любой writer с корнем ``footprint`` (KiCad 6+ всегда вызывает ``Quotes``); KiCad 5
      (``module``) — без кавычек;
    * ``quoted_wildcards`` — групповые обозначения ``*.Cu``/``F&B.Cu``/``*.Mask`` в
      ``(layers …)`` площадок в кавычках: KiCad 7+ (``Quotew("*.Cu")``); KiCad 6 пишет
      ``(layers *.Cu "F.Mask")``;
    * ``fill_style`` — форма ``(fill …)`` у графики корпуса (``fp_*``): ``"solid"`` —
      ``solid|none`` (KiCad 6–8), ``"yesno"`` — ``yes|no`` (KiCad 9+); у примитивов площадок
      (``gr_*`` внутри ``primitives``) своя форма: ``yes|none`` в 6/7, ``yes|no`` в 8+;
    * ``model_offset_token`` — токен смещения 3D-модели **для записи**: всегда
      ``"offset"`` (мм). ``(at (xyz …))`` KiCad 5 — устаревшая форма в **дюймах**
      (KiCad 5.1 писал её только для нулевого смещения); её надо уметь читать, но не писать;
    * ``arc_mid`` — дуги ``start/mid/end``; парсер KiCad считает старой формой
      (``start`` = центр, ``end``, ``angle``) всё с версией ``<= 20210925``, в том числе
      корпус ``footprint`` без токена ``version`` (версия 0).
    """

    version: int                      # версия формата (0 — KiCad 5 «module» или нет version)
    root: str                         # "footprint" | "module"
    style: str                        # стиль dumps: kicad8 | kicad7 | kicad6 | kicad5
    uuid_token: str                   # "uuid" | "tstamp"
    text_as_property: bool            # Reference/Value — (property …) с at/layer/effects
    stroke: bool                      # графика: stroke вместо width
    bool_style: str                   # "yesno" — (hide yes)/(locked yes); "flag" — голые hide/locked
    quoted_layers: bool               # (layers "F.Cu") vs (layers F.Cu)
    quoted_generator: bool            # (generator "pcbnew") vs (generator pcbnew)
    solder_paste_ratio_token: str     # токен коэффициента пасты у корпуса
    arc_mid: bool                     # дуги start/mid/end (иначе KiCad 5: center/end/angle)
    model_offset_token: str           # токен смещения модели для записи (всегда "offset")
    has_tedit: bool                   # писать ли tedit у новых корпусов
    has_generator_version: bool
    text_order: tuple[str, ...]
    graphic_order: tuple[str, ...]
    fill_style: str                   # "yesno" — (fill yes|no); "solid" — (fill solid|none)
    quoted_wildcards: bool = False    # (layers "*.Cu") vs (layers *.Cu)

    @property
    def is_legacy_module(self) -> bool:
        """Корень ``module`` (формат KiCad 5)."""
        return self.root == "module"


def profile_for(version: int | None, root: str = "footprint") -> FormatProfile:
    """Профиль формата по версии файла.

    ``version=None`` (токена ``version`` нет) трактуется, как в парсере KiCad, версией
    0: для корня ``footprint`` это старая форма дуг, ``tstamp``, голые флаги; раскладка
    ``kicad6``. Корень ``module`` — всегда KiCad 5 (версия 0).
    """
    from .sexpr import style_for_version

    if root == "module" or version is None:
        v = 0
    else:
        v = int(version)
    normalized = v >= V_NORMALIZED
    if v >= V_FILL_YESNO:
        graphic_order = GRAPHIC_ORDER
    elif normalized:
        graphic_order = GRAPHIC_ORDER_V8
    elif v >= V_STROKE:
        graphic_order = GRAPHIC_ORDER_V7
    else:
        graphic_order = GRAPHIC_ORDER_V6
    return FormatProfile(
        version=v,
        root=root,
        style=style_for_version(v if root != "module" and version is not None else None, root),
        uuid_token="uuid" if normalized else "tstamp",
        text_as_property=v >= V_FIELDS,
        stroke=v >= V_STROKE,
        bool_style="yesno" if normalized else "flag",
        quoted_layers=root != "module",
        quoted_generator=normalized,
        solder_paste_ratio_token="solder_paste_margin_ratio" if v >= V_PASTE_RATIO else "solder_paste_ratio",
        arc_mid=v > V_LEGACY_ARC,
        model_offset_token="offset",
        has_tedit=v < V_NO_TEDIT,
        has_generator_version=normalized,
        text_order=TEXT_ORDER if normalized else TEXT_ORDER_V6,
        graphic_order=graphic_order,
        fill_style="yesno" if v >= V_FILL_YESNO else "solid",
        quoted_wildcards=v >= V_KICAD7,
    )


# --- порядок дочерних токенов ------------------------------------------------------

# Корень корпуса. Секция графики в KiCad сортируется по типу элемента (6/7: fp_text,
# fp_text_box, фигуры; 8+: фигуры, image, fp_text, fp_text_box, table, barcode,
# dimension), поэтому внутри секции рисования порядок имён в этой таблице несуществен
# (порядок вставки — по drawing_sort_key, см. insert_in_group). Токены 10.0: units, stackup,
# duplicate_pad_numbers_are_jumpers, jumper_pad_groups, barcode, point, variant; master:
# transform (вместо at), fp_ellipse, fp_ellipse_arc, constraint, custom_property.
FOOTPRINT_ORDER: tuple[str, ...] = (
    "version", "generator", "generator_version", "locked", "placed", "layer", "tedit",
    "uuid", "tstamp", "at", "transform", "descr", "tags", "property", "component_classes",
    "path", "sheetname", "sheetfile", "units", "autoplace_cost90", "autoplace_cost180",
    "solder_mask_margin", "solder_paste_margin", "solder_paste_ratio",
    "solder_paste_margin_ratio", "clearance", "zone_connect", "thermal_width", "thermal_gap",
    "attr", "stackup", "private_layers", "net_tie_pad_groups",
    "duplicate_pad_numbers_are_jumpers", "jumper_pad_groups",
    "fp_text", "fp_text_box", "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly",
    "fp_curve", "fp_ellipse", "fp_ellipse_arc", "image", "table", "barcode", "dimension",
    "point", "pad", "zone", "group", "constraint", "variant", "embedded_fonts",
    "embedded_files", "model", "custom_property",
)

# Площадка (6.0–10.0 + master). locked: в 6/7 — голый флаг после формы (первым в таблице,
# чтобы Node.set_flag ставил его после номера/типа/формы и до (at)); ночные 5.99
# (20210108–20210423) писали узел (locked) после (at) — парсер KiCad 6+ принимает обе формы;
# 8.0+ блокировку площадок не пишет.
PAD_ORDER: tuple[str, ...] = (
    "locked", "at", "size", "rect_delta", "drill", "backdrill", "tertiary_drill",
    "front_post_machining", "back_post_machining", "property", "sim_electrical_type",
    "layers", "remove_unused_layers", "keep_end_layers", "zone_layer_connections",
    "roundrect_rratio", "chamfer_ratio", "chamfer", "net", "pinfunction", "pintype",
    "die_length", "die_delay", "solder_mask_margin", "solder_paste_margin",
    "solder_paste_margin_ratio", "clearance", "zone_connect", "thermal_width",
    "thermal_bridge_width", "thermal_bridge_angle", "thermal_gap", "options", "primitives",
    "teardrops", "tenting", "uuid", "tstamp", "padstack", "custom_property",
)

# 3D-модель: "path" [hide] (6/7 — голый флаг, 8+ — (hide yes)), opacity, offset|at, scale,
# rotate; для «выдавленного» корпуса master — type, overall_height, body_pcb_gap, layer,
# material, color.
MODEL_ORDER: tuple[str, ...] = (
    "type", "hide", "opacity", "overall_height", "body_pcb_gap", "layer", "material",
    "color", "offset", "at", "scale", "rotate",
)
# EDA_TEXT::Format: font, justify, hide (6/7 — голый флаг, 8 — (hide yes)), href.
EFFECTS_ORDER: tuple[str, ...] = ("font", "justify", "hide", "href")
# (font [(face)] (size) [(line_spacing)] [(thickness)] [bold] [italic] [(color)]);
# bold/italic — голые флаги в 6/7 и (bold yes)/(italic yes) в 8+.
FONT_ORDER: tuple[str, ...] = ("face", "size", "line_spacing", "thickness", "bold", "italic", "color")
DRILL_ORDER: tuple[str, ...] = ("offset",)
STROKE_ORDER: tuple[str, ...] = ("width", "type", "color")

# порядок флагов attr (как их пишет KiCad; exclude_from_sim — master; virtual — KiCad 5,
# парсер 6+ читает его как exclude_from_pos_files + exclude_from_bom)
ATTR_ORDER: tuple[str, ...] = (
    "smd", "through_hole", "board_only", "exclude_from_pos_files", "exclude_from_bom",
    "exclude_from_sim", "allow_missing_courtyard", "dnp", "allow_soldermask_bridges", "virtual",
)

GRAPHIC_NAMES: frozenset[str] = frozenset(
    ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve", "fp_ellipse",
     "fp_ellipse_arc"))
TEXT_NAMES: frozenset[str] = frozenset(("fp_text", "property"))

# Группы дочерних узлов корпуса (architecture.md §4): новые элементы добавляются в конец
# своей группы. Отклонения от контракта (по фактам writer'а KiCad):
# * «header» — свойства (property): в 6/7 — пользовательские свойства после tags, в 8+ —
#   все поля, включая Reference/Value; поэтому property не входит в «text» (иначе новое
#   fp_text в файле 8+ без fp_text встало бы после свойств в заголовке);
# * «text» — тексты секции рисования (fp_text, fp_text_box);
# * «graphic» — прочие элементы секции рисования (фигуры, image, table, barcode,
#   dimension, point).
# «text» и «graphic» образуют одну секцию рисования, которую KiCad 6+ сортирует по типу
# (FOOTPRINT::cmp_drawings): в 6/7 тексты идут до фигур, в 8+ — после; порядок вставки
# внутри секции см. insert_in_group.
GROUPS: dict[str, frozenset[str]] = {
    "header": frozenset(("property",)),
    "text": frozenset(("fp_text", "fp_text_box")),
    "graphic": frozenset(("image", "table", "barcode", "dimension", "point")) | GRAPHIC_NAMES,
    "pad": frozenset(("pad",)),
    "zone": frozenset(("zone",)),
    "group": frozenset(("group",)),
    "model": frozenset(("model",)),
}
_GROUP_SEQUENCE = ("header", "text", "graphic", "pad", "zone", "group", "model")
#: Группы, образующие секцию рисования корпуса.
DRAWING_GROUPS: frozenset[str] = frozenset(("text", "graphic"))

KNOWN_FOOTPRINT_CHILDREN: frozenset[str] = frozenset(FOOTPRINT_ORDER)

# --- порядок секции рисования (FOOTPRINT::cmp_drawings) ----------------------------
# Ключ сортировки KiCad 6.0–10.0: тип элемента (KICAD_T), слой (PCB_LAYER_ID), для фигур —
# вид (SHAPE_T), далее координаты/uuid. Ранги типов — порядок перечисления KICAD_T.

#: KiCad 6.0/7.0 (``core/typeinfo.h``): PCB_BITMAP_T < PCB_FP_TEXT_T < PCB_FP_TEXTBOX_T <
#: PCB_FP_SHAPE_T < PCB_FP_DIM_*_T. Тексты — до фигур.
DRAWING_TYPE_RANK_V6: dict[str, int] = {
    "image": 0, "fp_text": 1, "fp_text_box": 2,
    **{n: 3 for n in GRAPHIC_NAMES},
    "dimension": 4, "table": 5, "barcode": 6, "point": 7,
}
#: KiCad 8.0+ (``core/typeinfo.h``): PCB_SHAPE_T < PCB_REFERENCE_IMAGE_T < PCB_TEXT_T <
#: PCB_TEXTBOX_T < PCB_TABLE_T < PCB_BARCODE_T (10.0) < PCB_DIM_*_T; точки (10.0) пишутся
#: отдельным циклом после всей графики. Фигуры — до текстов.
DRAWING_TYPE_RANK: dict[str, int] = {
    **{n: 0 for n in GRAPHIC_NAMES},
    "image": 1, "fp_text": 2, "fp_text_box": 3, "table": 4, "barcode": 5, "dimension": 6,
    "point": 7,
}
#: ``SHAPE_T`` (6.0–10.0): SEGMENT, RECT(ANGLE), ARC, CIRCLE, POLY, BEZIER; эллипсы master —
#: после них.
SHAPE_RANK: dict[str, int] = {
    "fp_line": 0, "fp_rect": 1, "fp_arc": 2, "fp_circle": 3, "fp_poly": 4, "fp_curve": 5,
    "fp_ellipse": 6, "fp_ellipse_arc": 7,
}


def group_of(node: Node) -> str | None:
    """Группа дочернего узла корпуса.

    ``header`` (property), ``text`` (fp_text, fp_text_box), ``graphic`` (фигуры, image,
    table, barcode, dimension, point), ``pad``, ``zone``, ``group``, ``model``; иначе ``None``.
    """
    name = node.name
    for g in _GROUP_SEQUENCE:
        if name in GROUPS[g]:
            return g
    return None


def _is_ref_or_value(node: Node) -> bool:
    kind = node.atom(0) if node.name == "fp_text" else None
    return isinstance(kind, Sym) and kind in ("reference", "value")


def _root_version(root: Node) -> int | None:
    """Версия формата корня (``None`` — корень ``module`` или нет токена version)."""
    if root.name == "module":
        return None
    v = root.find("version")
    a = v.atom(0) if v is not None else None
    try:
        return int(a) if a is not None else None
    except ValueError:
        return None


def drawing_sort_key(node: Node, version: int | None) -> tuple[int, int, int]:
    """Ключ (тип, слой, вид фигуры) элемента секции рисования, как в ``cmp_drawings``.

    ``version`` — версия формата файла: ``<= 20221018`` (KiCad 6/7, в т.ч. ``None``) —
    ранги :data:`DRAWING_TYPE_RANK_V6`, иначе :data:`DRAWING_TYPE_RANK`; номера слоёв —
    ``LAYER_ID_V9`` для версий ``>= 20241129`` (KiCad 9+), иначе ``LAYER_ID_V6``.
    Неизвестный слой или его отсутствие — после всех известных. Координаты и uuid
    (последние критерии KiCad) не учитываются.
    """
    from .layers import LAYER_ID_V6, LAYER_ID_V9

    v = version or 0
    ranks = DRAWING_TYPE_RANK if v > V_KICAD7 else DRAWING_TYPE_RANK_V6
    ids = LAYER_ID_V9 if v >= V_FILL_YESNO else LAYER_ID_V6
    t = ranks.get(node.name, len(ranks))
    layer = node.value("layer")
    lid = ids.get(str(layer), 1 << 10) if layer is not None else 1 << 10
    return (t, lid, SHAPE_RANK.get(node.name, 0))


def insert_in_group(root: Node, child: Node) -> None:
    """Вставить ``child`` в корневой узел корпуса в конец его группы.

    Если элементов группы ещё нет — по общей таблице :data:`FOOTPRINT_ORDER` (после
    последнего узла, стоящего в ней раньше): так новое свойство встаёт после
    ``descr``/``tags``, а не после ``attr``, первая модель — после ``embedded_fonts``,
    первая площадка — после графики. Узлы вне групп — по :data:`FOOTPRINT_ORDER`.

    Секция рисования (группы ``text`` и ``graphic``) упорядочивается так, как её пишет
    KiCad (``FOOTPRINT::cmp_drawings``), чтобы пересохранение в KiCad не двигало новый
    элемент:

    * ``fp_text reference``/``value`` (KiCad 5–7) — после уже имеющихся reference/value,
      иначе в начало секции (writer пишет их первыми, вне сортировки);
    * корень ``module`` (KiCad 5, writer не сортирует) — в конец секции;
    * KiCad 6+: ключ :func:`drawing_sort_key` (тип, слой, вид фигуры). В 6/7 тексты
      (``fp_text``, ``fp_text_box``) стоят до фигур, в 8+ — после фигур. Если имеющаяся
      секция уже упорядочена по полному ключу (файл записан KiCad), элемент встаёт после
      последнего элемента с ключом не больше своего; иначе (файл генератора) — то же
      по одному рангу типа, т.е. в конец элементов своего типа (или перед первым
      элементом более позднего типа).
    """
    g = group_of(child)
    if g is None:
        root.insert(child, order=FOOTPRINT_ORDER)
        return
    if g in DRAWING_GROUPS:
        _insert_drawing(root, child)
        return
    last = None
    for i, x in enumerate(root.items):
        if isinstance(x, Node) and group_of(x) == g:
            last = i
    if last is not None:
        root.items.insert(last + 1, child)
        return
    root.insert(child, order=FOOTPRINT_ORDER)


def _insert_drawing(root: Node, child: Node) -> None:
    """Вставка элемента секции рисования (см. :func:`insert_in_group`)."""
    rv: list[int] = []
    rest: list[int] = []
    for i, x in enumerate(root.items):
        if isinstance(x, Node) and group_of(x) in DRAWING_GROUPS:
            (rv if _is_ref_or_value(x) else rest).append(i)
    if _is_ref_or_value(child):
        if rv:
            root.items.insert(rv[-1] + 1, child)
        elif rest:
            root.items.insert(rest[0], child)
        else:
            root.insert(child, order=FOOTPRINT_ORDER)
        return
    if not rest:
        if rv:
            root.items.insert(rv[-1] + 1, child)
        else:
            root.insert(child, order=FOOTPRINT_ORDER)
        return
    if root.name == "module":
        root.items.insert(rest[-1] + 1, child)
        return
    version = _root_version(root)
    keys = [drawing_sort_key(root.items[i], version) for i in rest]
    mine = drawing_sort_key(child, version)
    if any(a > b for a, b in zip(keys, keys[1:])):
        keys = [k[:1] for k in keys]
        mine = mine[:1]
    pos = None
    for i, k in zip(rest, keys):
        if k <= mine:
            pos = i + 1
    if pos is None:
        pos = next(i for i, k in zip(rest, keys) if k > mine)
    root.items.insert(pos, child)


def order_for(node_name: str, profile: FormatProfile | None = None) -> Sequence[str] | None:
    """Таблица порядка дочерних токенов для узла с именем ``node_name``.

    Для текстов и графики таблица зависит от версии (``profile``); без профиля —
    таблицы текущего формата (KiCad 9).
    """
    if node_name in ("footprint", "module"):
        return FOOTPRINT_ORDER
    if node_name == "pad":
        return PAD_ORDER
    if node_name in TEXT_NAMES:
        return profile.text_order if profile else TEXT_ORDER
    if node_name in GRAPHIC_NAMES:
        return profile.graphic_order if profile else GRAPHIC_ORDER
    if node_name == "model":
        return MODEL_ORDER
    if node_name == "effects":
        return EFFECTS_ORDER
    if node_name == "font":
        return FONT_ORDER
    if node_name == "stroke":
        return STROKE_ORDER
    if node_name == "drill":
        return DRILL_ORDER
    return None


# --- позиционные атомы (значения, а не флаги) ----------------------------------------

#: Сколько ведущих атомов узла — позиционные значения (не флаги): имя корпуса, тип и
#: текст ``fp_text``, ключ и значение ``property``, номер/тип/форма ``pad``, путь
#: ``model``, текст ``gr_text``/``fp_text_box``, имя ``group``, имя слоя ``layer``.
#: KiCad 5 пишет строки без кавычек, если они не нужны, поэтому такой атом может
#: совпасть с именем флага (``(fp_text user hide …)`` — видимый текст «hide»).
POSITIONAL_ATOMS: dict[str, int] = {
    "footprint": 1, "module": 1, "fp_text": 2, "fp_text_box": 1, "property": 2, "pad": 3,
    "model": 1, "gr_text": 1, "gr_text_box": 1, "group": 1, "layer": 1,
}
#: Порядковый номер (среди ведущих атомов) места голого флага ``locked``, стоящего
#: перед текстом: ``(fp_text TYPE locked "TEXT" …)`` (KiCad 6/7), ``(fp_text_box locked
#: "TEXT" …)`` (KiCad 7). Парсер KiCad 6+ считает ``locked`` в этом месте флагом, если за
#: ним идёт ещё один атом (текст).
LOCKED_SLOT: dict[str, int] = {"fp_text": 1, "fp_text_box": 0}


def positional_atoms(node: Node) -> frozenset[int]:
    """Индексы ``node.items`` позиционных атомов (см. :data:`POSITIONAL_ATOMS`).

    Позиционные атомы ищутся только среди атомов до первого подузла. Голый ``locked`` на
    месте :data:`LOCKED_SLOT`, за которым следует ещё атом, — флаг, а не текст (как в
    парсере KiCad 6+: ``(fp_text reference locked "REF**" …)``). Для узлов вне таблицы —
    пустое множество (все атомы могут быть флагами).
    """
    n = POSITIONAL_ATOMS.get(node.name, 0)
    if not n:
        return frozenset()
    slot = LOCKED_SLOT.get(node.name)
    items = node.items
    out: list[int] = []
    for i, x in enumerate(items):
        if isinstance(x, Node) or len(out) >= n:
            break
        if (slot is not None and len(out) == slot and isinstance(x, Sym) and x == "locked"
                and i + 1 < len(items) and not isinstance(items[i + 1], Node)):
            continue
        out.append(i)
    return frozenset(out)


def flag_slot(node: Node, flag: str) -> int | None:
    """Индекс в ``node.items`` для нового голого флага с особой позицией или ``None``.

    Сейчас это только ``locked`` у ``fp_text``/``fp_text_box`` (:data:`LOCKED_SLOT`): флаг
    ставится перед текстом, т.е. сразу после первых ``LOCKED_SLOT[name]`` ведущих атомов.
    ``None`` — особой позиции нет (или у узла нет текста), действует общая логика
    :meth:`Node.set_flag`.
    """
    slot = LOCKED_SLOT.get(node.name) if flag == "locked" else None
    if slot is None:
        return None
    seen = 0
    for i, x in enumerate(node.items):
        if isinstance(x, Node):
            return None
        if seen == slot:
            return i
        seen += 1
    return None
