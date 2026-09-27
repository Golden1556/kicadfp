"""Слои KiCad: канонические имена, групповые обозначения, пресеты площадок, цвета,
порядок отрисовки и старая (legacy) нумерация.

Все данные — константы в коде (источник: ``docs/dev/layers.json`` / ``layers.md``,
сверено с исходниками KiCad 5.1–9.0/master; json во время выполнения не читается).

Главное о слоях посадочных мест:

* Канонические имена — ``LSET::Name`` KiCad (``F.Cu``, ``In1.Cu`` … ``In30.Cu``, ``B.Cu``,
  ``F.SilkS``, …, ``User.1`` … ``User.45``, ``Rescue``). ``User.1..9`` появились в 6.0,
  ``User.10..45`` — в 9.0.
* Групповые обозначения (wildcards) — только для списков ``(layers …)``: ``*.Cu``,
  ``*In.Cu``, ``F&B.Cu``, ``*.Adhes``, ``*.Paste``, ``*.Mask``, ``*.SilkS``, ``*.Fab``,
  ``*.CrtYd`` (парсер 6.0–9.0 одинаков).
* Парсер KiCad (все версии с 6.0) дополнительно понимает в ``(layers …)`` старые имена
  ``Inner1.Cu`` … ``Inner14.Cu`` (обратная нумерация: ``Inner1.Cu`` = ``In14.Cu``), а парсер
  9.0+ — ещё ``In31.Cu`` … ``In62.Cu`` (побочный эффект ``LSET::Name`` для чётных
  идентификаторов 64…126; реальных слоёв за ними нет). kicadfp считает эти «призрачные»
  имена **невалидными** (layers.md §1.3, §2.4): :func:`is_valid_layer`, :func:`is_copper`,
  :func:`expand` не признают их слоями; принять их можно только явно
  (``is_valid_layer(..., parser_names=True)``). Неизвестное имя KiCad молча переносит на
  слой ``Rescue``.
* Порядок слоёв: ``ALL_LAYERS`` — порядок перечисления 6.0–8.0 (числовые ``PCB_LAYER_ID``
  тех версий), расширенный слоями 9.0; KiCad 9 перечисляет слои в другом порядке
  (``LAYER_ID_V9``), см. :func:`sort_layers` и :func:`collapse`.
"""

from __future__ import annotations

import re
from typing import Iterable

__all__ = [
    "MAX_INNER_LAYERS",
    "COPPER_LAYERS",
    "INNER_COPPER_LAYERS",
    "TECH_LAYERS",
    "BOARD_USER_LAYERS",
    "FOOTPRINT_LAYERS",
    "USER_DEFINED_LAYERS",
    "USER_DEFINED_LAYERS_V6",
    "USER_LAYERS",
    "RESCUE_LAYER",
    "ALL_LAYERS",
    "ALL_LAYERS_V5",
    "ALL_LAYERS_V6",
    "LAYER_ID_V5",
    "LAYER_ID_V6",
    "LAYER_ID_V9",
    "WILDCARDS",
    "WILDCARD_WRITE_ORDER",
    "OLD_INNER_NAMES",
    "PARSER_EXTRA_COPPER_V9",
    "FRONT_LAYERS",
    "BACK_LAYERS",
    "FLIP_PAIRS",
    "PAD_LAYER_PRESETS",
    "PAD_LAYER_MASKS",
    "PAD_ALLOWED_NON_COPPER",
    "COLORS",
    "COLOR_ALPHA",
    "DRAW_ORDER",
    "LEGACY_INDEX",
    "LEGACY_NAMES_2011",
    "LEGACY_MASK_BITS",
    "LEGACY_MASKS",
    "LEGACY_PAD_DEFAULT_MASKS",
    "is_valid_layer",
    "is_wildcard",
    "expand",
    "collapse",
    "sort_layers",
    "legacy_layer_to_name",
    "legacy_mask_to_layers",
    "is_copper",
    "is_inner_copper",
    "is_front",
    "is_back",
    "layer_side",
    "flip_layer",
    "flip_layers",
    "describe",
    "display_name",
    "color",
    "rgba",
]

# ---------------------------------------------------------------------------
# Списки слоёв
# ---------------------------------------------------------------------------

#: Число внутренних слоёв меди (``In1.Cu`` … ``In30.Cu``); всего меди — 32.
MAX_INNER_LAYERS: int = 30

#: Внутренние слои меди ``In1.Cu`` … ``In30.Cu``.
INNER_COPPER_LAYERS: list[str] = [f"In{i}.Cu" for i in range(1, MAX_INNER_LAYERS + 1)]

#: Все слои меди сверху вниз: ``F.Cu``, ``In1.Cu`` … ``In30.Cu``, ``B.Cu``.
COPPER_LAYERS: list[str] = ["F.Cu", *INNER_COPPER_LAYERS, "B.Cu"]

#: Технологические слои платы (порядок KiCad 6.0–8.0).
TECH_LAYERS: list[str] = [
    "B.Adhes", "F.Adhes", "B.Paste", "F.Paste",
    "B.SilkS", "F.SilkS", "B.Mask", "F.Mask",
]

#: Чертёжные слои платы: рисунки, комментарии, ECO, контур, поле.
BOARD_USER_LAYERS: list[str] = [
    "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User", "Edge.Cuts", "Margin",
]

#: Слои посадочного места: область размещения и сборочный (fabrication).
FOOTPRINT_LAYERS: list[str] = ["B.CrtYd", "F.CrtYd", "B.Fab", "F.Fab"]

#: Пользовательские слои KiCad 9.0+: ``User.1`` … ``User.45``.
USER_DEFINED_LAYERS: list[str] = [f"User.{i}" for i in range(1, 46)]

#: Пользовательские слои KiCad 6.0–8.0: ``User.1`` … ``User.9``.
USER_DEFINED_LAYERS_V6: list[str] = USER_DEFINED_LAYERS[:9]

#: «Пользовательские» слои в смысле контракта (§5 architecture.md): чертёжные слои платы,
#: слои посадочного места и ``User.1`` … ``User.45``.
USER_LAYERS: list[str] = [*BOARD_USER_LAYERS, *FOOTPRINT_LAYERS, *USER_DEFINED_LAYERS]

#: Служебный слой, на который KiCad переносит объекты с неизвестных слоёв.
RESCUE_LAYER: str = "Rescue"

#: Все канонические имена (KiCad 9.0+) в порядке перечисления 6.0–8.0, дополненном
#: ``User.10`` … ``User.45``; ``Rescue`` — последним.
ALL_LAYERS: list[str] = [*COPPER_LAYERS, *TECH_LAYERS, *USER_LAYERS, RESCUE_LAYER]

#: Канонические имена KiCad 5.1 (без ``User.N``), в порядке их идентификаторов.
ALL_LAYERS_V5: list[str] = [*COPPER_LAYERS, *TECH_LAYERS, *BOARD_USER_LAYERS,
                            *FOOTPRINT_LAYERS, RESCUE_LAYER]

#: Канонические имена KiCad 6.0–8.0 в порядке их идентификаторов.
ALL_LAYERS_V6: list[str] = [*COPPER_LAYERS, *TECH_LAYERS, *BOARD_USER_LAYERS,
                            *FOOTPRINT_LAYERS, *USER_DEFINED_LAYERS_V6, RESCUE_LAYER]

#: Числовые ``PCB_LAYER_ID`` KiCad 5.1.
LAYER_ID_V5: dict[str, int] = {name: i for i, name in enumerate(ALL_LAYERS_V5)}

#: Числовые ``PCB_LAYER_ID`` KiCad 6.0–8.0 (= порядок перечисления writer'а этих версий).
LAYER_ID_V6: dict[str, int] = {name: i for i, name in enumerate(ALL_LAYERS_V6)}


def _build_ids_v9() -> dict[str, int]:
    """Числовые ``PCB_LAYER_ID`` KiCad 9.0+ (include/layer_ids.h 9.0:59-172).

    Медь — чётные идентификаторы (F.Cu=0, B.Cu=2, In1.Cu=4 … In30.Cu=62), остальные —
    нечётные; порядок перечисления writer'а 9.0+ — по возрастанию идентификатора.
    """
    ids: dict[str, int] = {"F.Cu": 0, "B.Cu": 2}
    for i in range(1, MAX_INNER_LAYERS + 1):
        ids[f"In{i}.Cu"] = 2 * i + 2
    odd = ["F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "F.Adhes", "B.Adhes", "F.Paste",
           "B.Paste", "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User", "Edge.Cuts",
           "Margin", "B.CrtYd", "F.CrtYd", "B.Fab", "F.Fab", "Rescue"]
    for k, name in enumerate(odd):
        ids[name] = 2 * k + 1
    for n in range(1, 46):
        ids[f"User.{n}"] = ids["Rescue"] + 2 * n
    return dict(sorted(ids.items(), key=lambda kv: kv[1]))


#: Числовые ``PCB_LAYER_ID`` KiCad 9.0+ (от 0 до 127).
LAYER_ID_V9: dict[str, int] = _build_ids_v9()

# ---------------------------------------------------------------------------
# Групповые обозначения и дополнительные имена парсера
# ---------------------------------------------------------------------------

#: Групповые обозначения, которые понимает парсер KiCad 6.0–9.0 в ``(layers …)``.
#: ``*.Cu`` = ``LSET::AllCuMask()`` (все 32 слоя меди независимо от числа слоёв платы).
WILDCARDS: dict[str, list[str]] = {
    "*.Cu": list(COPPER_LAYERS),
    "*In.Cu": list(INNER_COPPER_LAYERS),
    "F&B.Cu": ["F.Cu", "B.Cu"],
    "*.Adhes": ["B.Adhes", "F.Adhes"],
    "*.Paste": ["B.Paste", "F.Paste"],
    "*.Mask": ["B.Mask", "F.Mask"],
    "*.SilkS": ["B.SilkS", "F.SilkS"],
    "*.Fab": ["B.Fab", "F.Fab"],
    "*.CrtYd": ["B.CrtYd", "F.CrtYd"],
}

#: Порядок, в котором writer KiCad (``formatLayers``) выводит групповые обозначения;
#: ``*.Cu`` и ``F&B.Cu`` взаимоисключающие. ``*In.Cu`` writer не выводит никогда.
WILDCARD_WRITE_ORDER: list[str] = [
    "*.Cu", "F&B.Cu", "*.Adhes", "*.Paste", "*.SilkS", "*.Mask", "*.CrtYd", "*.Fab",
]

#: Имена первых форматов .kicad_pcb/.pretty (только в ``(layers …)``), обратная нумерация.
OLD_INNER_NAMES: dict[str, str] = {f"Inner{i}.Cu": f"In{15 - i}.Cu" for i in range(1, 15)}

#: Имена ``In31.Cu`` … ``In62.Cu``: парсер 9.0+ их принимает (``LSET::Name`` для чётных
#: идентификаторов 64…126), но реальных слоёв меди за ними нет — kicadfp считает их
#: невалидными (``is_valid_layer(..., parser_names=True)`` — чтобы принять).
PARSER_EXTRA_COPPER_V9: list[str] = [f"In{i}.Cu" for i in range(31, 63)]

# ---------------------------------------------------------------------------
# Стороны и отражение
# ---------------------------------------------------------------------------

#: Слои лицевой стороны.
FRONT_LAYERS: list[str] = ["F.Cu", "F.Adhes", "F.Paste", "F.SilkS", "F.Mask", "F.CrtYd", "F.Fab"]

#: Слои обратной стороны.
BACK_LAYERS: list[str] = ["B.Cu", "B.Adhes", "B.Paste", "B.SilkS", "B.Mask", "B.CrtYd", "B.Fab"]

#: Пары слоёв при отражении на другую сторону (``FlipLayer``), в обе стороны.
FLIP_PAIRS: dict[str, str] = {
    **dict(zip(FRONT_LAYERS, BACK_LAYERS)),
    **dict(zip(BACK_LAYERS, FRONT_LAYERS)),
}

# ---------------------------------------------------------------------------
# Пресеты слоёв площадок
# ---------------------------------------------------------------------------

#: Слои новой площадки по типу — в том виде, в каком они записываются в файл
#: (групповые обозначения, порядок 6.0–8.0). ``np_thru_hole`` — ``"*.Cu" "*.Mask"``, как в
#: текущих библиотеках KiCad и writer'е 9.0.6+; внутренняя маска KiCad — F.Cu+B.Cu
#: (6.0–9.0.5 писали ``"F&B.Cu" "*.Mask"``), см. :data:`PAD_LAYER_MASKS`.
PAD_LAYER_PRESETS: dict[str, list[str]] = {
    "thru_hole": ["*.Cu", "*.Mask"],
    "smd": ["F.Cu", "F.Paste", "F.Mask"],
    "smd_back": ["B.Cu", "B.Paste", "B.Mask"],
    "connect": ["F.Cu", "F.Mask"],
    "connect_back": ["B.Cu", "B.Mask"],
    "np_thru_hole": ["*.Cu", "*.Mask"],
    "aperture": ["F.Paste"],
}

#: Точные наборы слоёв из pcbnew/pad.cpp (``PTHMask``, ``SMDMask``, ``ConnSMDMask``,
#: ``UnplatedHoleMask``, ``ApertureMask``; ``*_back`` — ``FlipStandardLayers``), раскрытые.
PAD_LAYER_MASKS: dict[str, list[str]] = {
    "thru_hole": [*COPPER_LAYERS, "B.Mask", "F.Mask"],
    "smd": ["F.Cu", "F.Paste", "F.Mask"],
    "smd_back": ["B.Cu", "B.Paste", "B.Mask"],
    "connect": ["F.Cu", "F.Mask"],
    "connect_back": ["B.Cu", "B.Mask"],
    "np_thru_hole": ["F.Cu", "B.Cu", "B.Mask", "F.Mask"],
    "aperture": ["F.Paste"],
}

#: Не-медные слои, которые диалог свойств площадки KiCad 9 позволяет выбрать.
PAD_ALLOWED_NON_COPPER: list[str] = [
    "F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.Adhes", "B.Adhes",
    "F.SilkS", "B.SilkS", "Dwgs.User", "Eco1.User", "Eco2.User",
]

# ---------------------------------------------------------------------------
# Цвета (тема KiCad Default 9.0, common/settings/builtin_color_themes.h)
# ---------------------------------------------------------------------------

#: Цвета ``#RRGGBB`` для всех слоёв и служебные ключи (``background``, ``grid``,
#: ``pad_th``, ``hole``, ``npth``, ``selection``, ``anchor``, ``cursor`` и др.).
#: Прозрачность — отдельно в :data:`COLOR_ALPHA` (восьмизначный hex не используется:
#: Qt трактует его как ``#AARRGGBB``, а SVG/CSS — как ``#RRGGBBAA``).
COLORS: dict[str, str] = {
    "F.Cu": "#C83434", "In1.Cu": "#7FC87F", "In2.Cu": "#CE7D2C", "In3.Cu": "#4FCBCB",
    "In4.Cu": "#DB628B", "In5.Cu": "#A7A5C6", "In6.Cu": "#28CCD9", "In7.Cu": "#E8B2A7",
    "In8.Cu": "#F2EDA1", "In9.Cu": "#8DCB81", "In10.Cu": "#ED7C33", "In11.Cu": "#5BC3EB",
    "In12.Cu": "#F76F8E", "In13.Cu": "#A7A5C6", "In14.Cu": "#28CCD9", "In15.Cu": "#E8B2A7",
    "In16.Cu": "#F2EDA1", "In17.Cu": "#ED7C33", "In18.Cu": "#5BC3EB", "In19.Cu": "#F76F8E",
    "In20.Cu": "#A7A5C6", "In21.Cu": "#28CCD9", "In22.Cu": "#E8B2A7", "In23.Cu": "#F2EDA1",
    "In24.Cu": "#ED7C33", "In25.Cu": "#5BC3EB", "In26.Cu": "#F76F8E", "In27.Cu": "#A7A5C6",
    "In28.Cu": "#28CCD9", "In29.Cu": "#E8B2A7", "In30.Cu": "#F2EDA1", "B.Cu": "#4D7FC4",
    "B.Adhes": "#000084", "F.Adhes": "#840084", "B.Paste": "#00C2C2", "F.Paste": "#B4A09A",
    "B.SilkS": "#E8B2A7", "F.SilkS": "#F2EDA1", "B.Mask": "#02FFEE", "F.Mask": "#D864FF",
    "Dwgs.User": "#C2C2C2", "Cmts.User": "#5994DC", "Eco1.User": "#B4DBD2",
    "Eco2.User": "#D8C852", "Edge.Cuts": "#D0D2CD", "Margin": "#FF26E2",
    "B.CrtYd": "#26E9FF", "F.CrtYd": "#FF26E2", "B.Fab": "#585D84", "F.Fab": "#AFAFAF",
    "User.1": "#C2C2C2", "User.2": "#5994DC", "User.3": "#B4DBD2", "User.4": "#D8C852",
    "User.5": "#C2C2C2", "User.6": "#5994DC", "User.7": "#B4DBD2", "User.8": "#D8C852",
    "User.9": "#E8B2A7", "User.10": "#5994DC", "User.11": "#B4DBD2", "User.12": "#D8C852",
    "User.13": "#C2C2C2", "User.14": "#5994DC", "User.15": "#B4DBD2", "User.16": "#D8C852",
    "User.17": "#C2C2C2", "User.18": "#5994DC", "User.19": "#B4DBD2", "User.20": "#D8C852",
    "User.21": "#C2C2C2", "User.22": "#5994DC", "User.23": "#B4DBD2", "User.24": "#D8C852",
    "User.25": "#C2C2C2", "User.26": "#5994DC", "User.27": "#B4DBD2", "User.28": "#D8C852",
    "User.29": "#C2C2C2", "User.30": "#5994DC", "User.31": "#B4DBD2", "User.32": "#D8C852",
    "User.33": "#C2C2C2", "User.34": "#5994DC", "User.35": "#B4DBD2", "User.36": "#D8C852",
    "User.37": "#C2C2C2", "User.38": "#5994DC", "User.39": "#B4DBD2", "User.40": "#D8C852",
    "User.41": "#C2C2C2", "User.42": "#5994DC", "User.43": "#B4DBD2", "User.44": "#D8C852",
    "User.45": "#C2C2C2",
    # В теме KiCad цвета для Rescue нет — выбран нейтральный серый (решение kicadfp).
    "Rescue": "#848484",
    # Служебные ключи (GAL-слои темы Default).
    "background": "#001023",     # LAYER_PCB_BACKGROUND
    "grid": "#848484",           # LAYER_GRID
    "grid_axes": "#C2C2C2",      # LAYER_GRID_AXES
    "pad_th": "#E3B72E",         # LAYER_PADS_TH (тема 8.0; в 9.0 площадки — цветом меди)
    "hole": "#C2C200",           # LAYER_PAD_PLATEDHOLES
    "npth": "#1AC4D2",           # LAYER_NON_PLATEDHOLES
    "via_holes": "#E3B72E",      # LAYER_VIA_HOLES
    "selection": "#04FF43",      # LAYER_SELECT_OVERLAY
    "anchor": "#FF26E2",         # LAYER_ANCHOR
    "cursor": "#FFFFFF",         # LAYER_CURSOR
    "aux_items": "#FFFFFF",      # LAYER_AUX_ITEMS
    "locked_shadow": "#FF26E2",  # LAYER_LOCKED_ITEM_SHADOW
    "conflicts_shadow": "#FF0005",  # LAYER_CONFLICTS_SHADOW
    "drc_error": "#D75B6B",      # LAYER_DRC_ERROR
    "drc_warning": "#FFD042",    # LAYER_DRC_WARNING
    "ratsnest": "#00F8FF",       # LAYER_RATSNEST
    "drawingsheet": "#C872AB",   # LAYER_DRAWINGSHEET
    "page_limits": "#848484",    # LAYER_PAGE_LIMITS
    "pad_net_names": "#FFFFFF",  # LAYER_PAD_NETNAMES
}

#: Непрозрачность (0…1) для ключей :data:`COLORS`, у которых она меньше 1 (остальные — 1.0).
COLOR_ALPHA: dict[str, float] = {
    "F.Mask": 0.4, "B.Mask": 0.4,
    "F.Paste": 0.9, "B.Paste": 0.9,
    "locked_shadow": 0.5, "conflicts_shadow": 0.5,
    "drc_error": 0.8, "drc_warning": 0.8,
    "ratsnest": 0.35, "pad_net_names": 0.9,
}

# ---------------------------------------------------------------------------
# Порядок отрисовки
# ---------------------------------------------------------------------------

#: Порядок отрисовки слоёв платы снизу вверх (KiCad 9.0 GAL_LAYER_ORDER, обращённый;
#: pcbnew/pcb_draw_panel_gal.cpp): обратная сторона, внутренняя медь от In30 к In1,
#: лицевая сторона, пользовательские и чертёжные слои сверху. ``Rescue`` в порядке KiCad
#: нет; здесь он — самый нижний (решение kicadfp).
DRAW_ORDER: list[str] = [
    RESCUE_LAYER,
    "B.Fab", "B.CrtYd", "B.Adhes", "B.Paste", "B.SilkS", "B.Mask", "B.Cu",
    *reversed(INNER_COPPER_LAYERS),
    "F.Fab", "F.CrtYd", "F.Adhes", "F.Paste", "F.SilkS", "F.Mask", "F.Cu",
    *reversed(USER_DEFINED_LAYERS),
    "Margin", "Edge.Cuts", "Eco2.User", "Eco1.User", "Cmts.User", "Dwgs.User",
]

# ---------------------------------------------------------------------------
# Старая нумерация (PCBNEW-LibModule-V1, .brd/.mod)
# ---------------------------------------------------------------------------

#: Номер слоя старого формата -> имя при ``cu_count = 16`` (значение, с которым legacy
#: plugin читает библиотеки .mod: pcb_io_kicad_legacy.cpp 9.0:2923). 0 — низ (B.Cu),
#: 15 — верх (F.Cu), 1…14 — внутренние в обратном порядке, 29…31 -> Cmts.User.
LEGACY_INDEX: dict[int, str] = {
    0: "B.Cu",
    **{i: f"In{15 - i}.Cu" for i in range(1, 15)},
    15: "F.Cu",
    16: "B.Adhes", 17: "F.Adhes", 18: "B.Paste", 19: "F.Paste",
    20: "B.SilkS", 21: "F.SilkS", 22: "B.Mask", 23: "F.Mask",
    24: "Dwgs.User", 25: "Cmts.User", 26: "Eco1.User", 27: "Eco2.User", 28: "Edge.Cuts",
    29: "Cmts.User", 30: "Cmts.User", 31: "Cmts.User",
}

#: Имена слоёв KiCad 2011 (для сообщений и отображения старых файлов).
LEGACY_NAMES_2011: dict[int, str] = {
    0: "Back",
    **{i: f"Inner{i + 1}" for i in range(1, 15)},
    15: "Front",
    16: "Adhes_Back", 17: "Adhes_Front", 18: "SoldP_Back", 19: "SoldP_Front",
    20: "SilkS_Back", 21: "SilkS_Front", 22: "Mask_Back", 23: "Mask_Front",
    24: "Drawings", 25: "Comments", 26: "Eco1", 27: "Eco2", 28: "PCB_Edges",
}

#: Бит маски старого формата (``1 << n``) -> имя слоя при ``cu_count = 16``.
LEGACY_MASK_BITS: dict[int, str] = {1 << n: name for n, name in LEGACY_INDEX.items()}

#: Именованные маски legacy plugin (pcb_io_kicad_legacy.cpp 9.0:102-174).
LEGACY_MASKS: dict[str, int] = {
    "LAYER_BACK": 0x00000001,
    "LAYER_FRONT": 0x00008000,
    "ADHESIVE_LAYER_BACK": 0x00010000,
    "ADHESIVE_LAYER_FRONT": 0x00020000,
    "SOLDERPASTE_LAYER_BACK": 0x00040000,
    "SOLDERPASTE_LAYER_FRONT": 0x00080000,
    "SILKSCREEN_LAYER_BACK": 0x00100000,
    "SILKSCREEN_LAYER_FRONT": 0x00200000,
    "SOLDERMASK_LAYER_BACK": 0x00400000,
    "SOLDERMASK_LAYER_FRONT": 0x00800000,
    "DRAW_LAYER": 0x01000000,
    "COMMENT_LAYER": 0x02000000,
    "ECO1_LAYER": 0x04000000,
    "ECO2_LAYER": 0x08000000,
    "EDGE_LAYER": 0x10000000,
    "ALL_CU_LAYERS": 0x0000FFFF,
    "ALL_NO_CU_LAYERS": 0x1FFF0000,
    "FRONT_TECH_LAYERS": 0x00AA0000,
    "BACK_TECH_LAYERS": 0x00550000,
    "ALL_TECH_LAYERS": 0x00FF0000,
    "BACK_LAYERS": 0x00550001,
}

#: Маски площадок по умолчанию в KiCad 2011 (class_pad.h), по типу ``At``.
LEGACY_PAD_DEFAULT_MASKS: dict[str, int] = {
    "STD": 0x00E0FFFF,
    "SMD": 0x00808000,
    "CONN": 0x00888000,
    "HOLE": 0x00E00001,
}

# ---------------------------------------------------------------------------
# Внутренние таблицы
# ---------------------------------------------------------------------------

_ALL_SET: frozenset[str] = frozenset(ALL_LAYERS)
_V5_SET: frozenset[str] = frozenset(ALL_LAYERS_V5)
_V6_SET: frozenset[str] = frozenset(ALL_LAYERS_V6)
_EXTRA_V9_SET: frozenset[str] = frozenset(PARSER_EXTRA_COPPER_V9)
_ORDER: dict[str, int] = {name: i for i, name in enumerate(ALL_LAYERS)}
_INNER_RE = re.compile(r"^In(\d+)\.Cu$")
_USER_RE = re.compile(r"^User\.(\d+)$")
_COPPER_WILDCARDS = frozenset({"*.Cu", "*In.Cu", "F&B.Cu"})
_TECH_PAIRS: list[tuple[str, frozenset[str]]] = [
    (w, frozenset(WILDCARDS[w]))
    for w in ("*.Adhes", "*.Paste", "*.SilkS", "*.Mask", "*.CrtYd", "*.Fab")
]


def _order_key(name: str) -> tuple[int, int]:
    """Ключ сортировки: канонический порядок, затем In31+.Cu, затем прочие (0)."""
    if name in _ORDER:
        return (0, _ORDER[name])
    m = _INNER_RE.match(name)
    if m:
        return (1, int(m.group(1)))
    return (2, 0)


# ---------------------------------------------------------------------------
# Проверка и раскрытие имён
# ---------------------------------------------------------------------------

def is_wildcard(name: str) -> bool:
    """Истина для группового обозначения из :data:`WILDCARDS` (``*.Cu``, ``F&B.Cu``, …)."""
    return name in WILDCARDS


def is_valid_layer(name: str, *, single: bool = False, kicad: int | None = None,
                   parser_names: bool = False) -> bool:
    """Допустимо ли имя слоя.

    По умолчанию — канонические имена (включая ``Rescue``), групповые обозначения
    (:data:`WILDCARDS`) и старые ``Inner1.Cu`` … ``Inner14.Cu`` (их парсер KiCad принимает в
    ``(layers …)``).

    ``In31.Cu`` … ``In62.Cu`` недопустимы (layers.md §1.3, §2.4: реальных слоёв за ними нет,
    KiCad их не создаёт и не пишет) — ни в ``(layers …)``, ни в ``(layer …)``.
    ``parser_names=True`` — проверка «примет ли парсер KiCad 9+ имя без переноса на
    ``Rescue``»: тогда эти имена допустимы (при ``kicad`` ``None`` или ``>= 9``).

    ``single=True`` — проверка значения одиночного ``(layer X)``: там парсер ищет имя только
    среди канонических (``m_layerIndices``), поэтому групповые обозначения и ``InnerN.Cu``
    недопустимы.

    ``kicad`` — мажорная версия парсера: 5 — без ``User.N``; 6/7/8 — ``User.1..9``;
    ``None``/9/10 — как 9.0 (``User.1..45``).
    """
    if not isinstance(name, str):
        return False
    if kicad is not None and kicad <= 5:
        canon, extra = _V5_SET, frozenset()
    elif kicad is not None and kicad < 9:
        canon, extra = _V6_SET, frozenset()
    else:
        canon, extra = _ALL_SET, (_EXTRA_V9_SET if parser_names else frozenset())
    if name in canon or name in extra:
        return True
    if single:
        return False
    return name in WILDCARDS or name in OLD_INNER_NAMES


def expand(names: Iterable[str]) -> list[str]:
    """Раскрыть групповые обозначения и старые имена ``InnerN.Cu`` в канонические имена.

    Результат без повторов, в порядке :data:`ALL_LAYERS`; неизвестные имена (в том числе
    «призрачные» ``In31.Cu`` … ``In62.Cu``, см. :func:`is_valid_layer`) сохраняются как есть
    в конце (в порядке появления) — решение, что с ними делать, остаётся за вызывающим
    (KiCad переносит их на ``Rescue``). Строка вместо итерируемого считается одним именем.
    """
    if isinstance(names, str):
        names = [names]
    seen: set[str] = set()
    known: list[str] = []
    unknown: list[str] = []
    for name in names:
        members = WILDCARDS.get(name)
        if members is None:
            members = [OLD_INNER_NAMES.get(name, name)]
        for m in members:
            if m in seen:
                continue
            seen.add(m)
            if m in _ALL_SET:
                known.append(m)
            else:
                unknown.append(m)
    known.sort(key=_order_key)
    return known + unknown


def sort_layers(names: Iterable[str], *, kicad: int = 9) -> list[str]:
    """Упорядочить имена так, как writer KiCad перечисляет отдельные слои.

    ``kicad < 9`` — по идентификаторам 6.0–8.0 (:data:`LAYER_ID_V6`), иначе — по
    идентификаторам 9.0+ (:data:`LAYER_ID_V9`: F.Cu, F.Mask, B.Cu, B.Mask, In1.Cu, F.SilkS…).
    Имена без идентификатора (групповые, неизвестные) — в конце в исходном порядке.
    Повторы сохраняются.
    """
    ids = LAYER_ID_V6 if kicad < 9 else LAYER_ID_V9
    items = list(names)
    big = 1 << 20

    def key(pair: tuple[int, str]) -> tuple[int, int]:
        idx, name = pair
        if name in ids:
            return (0, ids[name])
        m = _INNER_RE.match(name)
        if m and kicad >= 9 and name in _EXTRA_V9_SET:
            return (0, 2 * int(m.group(1)) + 2)   # In31.Cu -> 64 … In62.Cu -> 126
        return (1, big + idx)

    return [n for _, n in sorted(enumerate(items), key=key)]


def collapse(names: Iterable[str], *, kicad: int = 9, fb_wildcard: str | None = None,
             copper_count: int = 32) -> list[str]:
    """Свернуть набор слоёв в групповые обозначения, как writer KiCad (``formatLayers``).

    Алгоритм (6.0–10.0): если присутствуют все слои меди платы (``copper_count``: F.Cu,
    In1..In(n-2), B.Cu) — ``*.Cu`` и вся медь снимается; иначе если медь платы ровно
    F.Cu+B.Cu — ``fb_wildcard``; затем пары ``*.Adhes``, ``*.Paste``, ``*.SilkS``, ``*.Mask``,
    ``*.CrtYd``, ``*.Fab``; затем оставшиеся отдельные слои в порядке :func:`sort_layers`.

    ``fb_wildcard`` по умолчанию — ``"F&B.Cu"`` для ``kicad <= 9`` (6.0–9.0.5) и ``"*.Cu"``
    для ``kicad >= 10`` (так пишет и 9.0.6+ для не-зон — передайте явно).
    Неизвестные имена сохраняются в конце.
    """
    if fb_wildcard is None:
        fb_wildcard = "F&B.Cu" if kicad <= 9 else "*.Cu"
    layers = expand(names)
    present = set(layers)
    n_inner = max(0, min(MAX_INNER_LAYERS, copper_count - 2))
    board_cu = {"F.Cu", "B.Cu", *INNER_COPPER_LAYERS[:n_inner]}
    all_cu = set(COPPER_LAYERS)   # как ``~cu_all``: фантомные In31+ не снимаются
    out: list[str] = []
    cu_present = present & board_cu
    if cu_present == board_cu:
        out.append("*.Cu")
        present -= all_cu
    elif cu_present == {"F.Cu", "B.Cu"}:
        out.append(fb_wildcard)
        present -= {"F.Cu", "B.Cu"}
    for wildcard, members in _TECH_PAIRS:
        if members <= present:
            out.append(wildcard)
            present -= members
    out.extend(sort_layers([n for n in layers if n in present], kicad=kicad))
    return out


# ---------------------------------------------------------------------------
# Старый формат
# ---------------------------------------------------------------------------

def legacy_layer_to_name(number: int, cu_count: int = 16) -> str:
    """Номер слоя старого формата -> каноническое имя (точная реплика ``leg_layer2new``).

    0 -> ``B.Cu``, 15 -> ``F.Cu``, 1…14 -> ``In(cu_count-1-n).Cu`` (номер ≤ 0 -> ``F.Cu``, как
    ``BoardLayerFromLegacyId`` для отрицательных), 16…28 — технологические/чертёжные,
    любой другой не-медный номер -> ``Cmts.User``.
    """
    old = number & 0xFFFFFFFF
    if old <= 15:
        if old == 15:
            return "F.Cu"
        if old == 0:
            return "B.Cu"
        legacy_id = cu_count - 1 - old
        if legacy_id <= 0:
            return "F.Cu"
        if legacy_id >= 31:
            return "B.Cu"
        return f"In{legacy_id}.Cu"
    if 16 <= old <= 28:
        return LEGACY_INDEX[old]
    return "Cmts.User"


_LEGACY_PAD_ATTRIB: dict[str, str] = {
    "STD": "PTH", "SMD": "SMD", "CONN": "CONN", "HOLE": "NPTH",
    "thru_hole": "PTH", "smd": "SMD", "connect": "CONN", "np_thru_hole": "NPTH",
}


def legacy_mask_to_layers(mask: int | str, pad_type: str | None = "STD", *,
                          cu_count: int = 16, kicad: int = 9) -> list[str]:
    """Маска слоёв площадки старого формата (строка ``At TYPE N MASK``) -> имена слоёв.

    Точная реплика legacy plugin KiCad:

    1. ``leg_mask2new``: если в маске все 16 бит меди (``0x0000FFFF``) — ``LSET::AllCuMask()``
       (все 32 слоя меди), биты меди снимаются; каждый оставшийся бит ``n`` ->
       :func:`legacy_layer_to_name` (``cu_count`` = 16 для библиотек .mod).
    2. ``pad->SetAttribute(attribute)`` после ``SetLayerSet``: новая площадка создаётся как
       PTH, поэтому для ``STD``/``HOLE`` слои не меняются, а для ``SMD``/``CONN`` в KiCad
       8.0+ медь урезается до одного слоя: ``B.Cu``, если он есть, иначе первый по порядку
       (``F.Cu``, затем In1…). KiCad 6.0/7.0 (``kicad < 8``) не урезают.

    ``mask`` — число или hex-строка (``"00E0FFFF"``), усечённые до 32 бит (``hexParse`` в
    ``uint32``). ``pad_type`` — ``STD``/``SMD``/``CONN``/``HOLE`` (регистр не важен) или тип
    площадки .kicad_mod (``thru_hole``/``smd``/``connect``/``np_thru_hole``); иное (и
    ``None``) — PTH, как ветка ``else`` плагина. Результат — в порядке :data:`ALL_LAYERS`;
    для записи в файл используйте :func:`collapse`.
    """
    if isinstance(mask, str):
        mask = int(mask.strip(), 16)
    mask &= 0xFFFFFFFF
    result: set[str] = set()
    if mask & 0x0000FFFF == 0x0000FFFF:
        result.update(COPPER_LAYERS)
        mask &= ~0x0000FFFF
    n = 0
    while mask:
        if mask & 1:
            result.add(legacy_layer_to_name(n, cu_count))
        mask >>= 1
        n += 1

    key = (pad_type or "STD").strip()
    attrib = _LEGACY_PAD_ATTRIB.get(key) or _LEGACY_PAD_ATTRIB.get(key.upper(), "PTH")
    if attrib in ("SMD", "CONN") and kicad >= 8:
        copper = [name for name in COPPER_LAYERS if name in result]
        if len(copper) > 1:
            result.difference_update(copper)
            result.add("B.Cu" if "B.Cu" in copper else copper[0])
    return sorted(result, key=_order_key)


# ---------------------------------------------------------------------------
# Классификация, стороны, отражение
# ---------------------------------------------------------------------------

def is_copper(name: str) -> bool:
    """Слой меди: ``F.Cu``, ``B.Cu``, ``In1.Cu`` … ``In30.Cu``, ``InnerN.Cu`` или медное
    групповое обозначение (``*.Cu``, ``*In.Cu``, ``F&B.Cu``). «Призрачные» ``In31.Cu`` …
    ``In62.Cu`` (невалидные, см. :func:`is_valid_layer`) медью не считаются."""
    return (name in ("F.Cu", "B.Cu") or name in _COPPER_WILDCARDS
            or name in OLD_INNER_NAMES or is_inner_copper(name))


def is_inner_copper(name: str) -> bool:
    """Внутренний слой меди ``In1.Cu`` … ``In30.Cu`` (``In31.Cu``+ — не слои, см.
    :func:`is_valid_layer`)."""
    m = _INNER_RE.match(name)
    return bool(m) and 1 <= int(m.group(1)) <= MAX_INNER_LAYERS and not m.group(1).startswith("0")


def is_front(name: str) -> bool:
    """Слой лицевой стороны (``F.*``)."""
    return name in FRONT_LAYERS


def is_back(name: str) -> bool:
    """Слой обратной стороны (``B.*``)."""
    return name in BACK_LAYERS


def layer_side(name: str) -> str | None:
    """Сторона слоя: ``"F"``, ``"B"`` или ``None`` (внутренняя медь, чертёжные, групповые)."""
    if name in FRONT_LAYERS:
        return "F"
    if name in BACK_LAYERS:
        return "B"
    return None


def flip_layer(name: str, copper_count: int = 2) -> str:
    """Слой после переноса посадочного места на другую сторону (``FlipLayer`` KiCad).

    F.* <-> B.* (медь, клей, паста, шелкография, маска, CrtYd, Fab). Внутренняя медь при
    ``copper_count < 4`` (по умолчанию — 2-слойная плата) остаётся на месте; при ``>= 4``
    ``InN.Cu`` -> ``In(copper_count-1-N).Cu`` с ограничением F.Cu/B.Cu, как в KiCad 8.0
    (в 9.0 та же формула записана по новым идентификаторам — здесь реализован её смысл).
    Групповые обозначения симметричны; прочие слои не меняются.
    """
    pair = FLIP_PAIRS.get(name)
    if pair is not None:
        return pair
    if copper_count >= 4:
        m = _INNER_RE.match(name)
        if m and name in _ORDER:
            n = copper_count - 1 - int(m.group(1))
            if n <= 0:
                return "F.Cu"
            if n >= 31:
                return "B.Cu"
            return f"In{n}.Cu"
    return name


def flip_layers(names: Iterable[str], copper_count: int = 2) -> list[str]:
    """:func:`flip_layer` для каждого имени (порядок и повторы сохраняются)."""
    return [flip_layer(n, copper_count) for n in names]


# ---------------------------------------------------------------------------
# Человекочитаемые имена и цвета
# ---------------------------------------------------------------------------

_SIDE = {"F": "верх", "B": "низ"}
_KIND: dict[str, str] = {
    "Cu": "медь",
    "Adhes": "клей",
    "Paste": "паяльная паста",
    "SilkS": "шелкография",
    "Mask": "паяльная маска",
    "CrtYd": "область размещения",
    "Fab": "сборочный",
}
_FIXED: dict[str, str] = {
    "Dwgs.User": "чертёж",
    "Cmts.User": "комментарии",
    "Eco1.User": "ECO 1",
    "Eco2.User": "ECO 2",
    "Edge.Cuts": "контур платы",
    "Margin": "поле (отступ от края)",
    "Rescue": "спасённые объекты с неизвестных слоёв",
    "*.Cu": "вся медь",
    "*In.Cu": "вся внутренняя медь",
    "F&B.Cu": "медь, верх и низ",
}


def describe(name: str) -> str | None:
    """Русское описание слоя (без имени) или ``None`` для неизвестного имени.

    Пример: ``describe("F.SilkS") == "шелкография, верх"``.
    """
    if name in _FIXED:
        return _FIXED[name]
    side, _, kind = name.partition(".")
    if side in _SIDE and kind in _KIND and "." not in kind:
        return f"{_KIND[kind]}, {_SIDE[side]}"
    if side == "*" and kind in _KIND:
        return f"{_KIND[kind]}, обе стороны"
    if name in OLD_INNER_NAMES:
        return f"устаревшее имя {OLD_INNER_NAMES[name]}"
    m = _INNER_RE.match(name)
    if m and (is_inner_copper(name) or name in _EXTRA_V9_SET):
        n = int(m.group(1))
        if n > MAX_INNER_LAYERS:
            return f"медь, внутренний слой {n} (нет в KiCad)"
        return f"медь, внутренний слой {n}"
    m = _USER_RE.match(name)
    if m and name in _ORDER:
        return f"пользовательский слой {m.group(1)}"
    return None


def display_name(name: str) -> str:
    """Имя слоя для GUI: ``"F.SilkS (шелкография, верх)"``; неизвестное — как есть."""
    text = describe(name)
    return f"{name} ({text})" if text else name


def _color_key(name: str) -> str | None:
    """Ключ :data:`COLORS` для имени: само имя, лицевой слой группы или новое имя InnerN."""
    if name in COLORS:
        return name
    members = WILDCARDS.get(name)
    if members:
        front = [m for m in members if m in FRONT_LAYERS]
        return (front or members)[0]
    if name in OLD_INNER_NAMES:
        return OLD_INNER_NAMES[name]
    return None


def color(name: str, default: str = "#848484") -> str:
    """Цвет ``#RRGGBB`` слоя или служебного ключа; групповое обозначение — цвет его
    лицевого (или первого) слоя; ``In31+.Cu`` и неизвестные имена — ``default``."""
    key = _color_key(name)
    return COLORS[key] if key is not None else default


def rgba(name: str) -> tuple[int, int, int, float]:
    """Цвет слоя/служебного ключа как ``(r, g, b, alpha)``; alpha из :data:`COLOR_ALPHA`."""
    h = color(name)
    key = _color_key(name)
    alpha = COLOR_ALPHA.get(key, 1.0) if key is not None else 1.0
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), alpha)
