"""Тесты kicadfp.layers: полнота против docs/dev/layers.json, групповые обозначения из
инвентаризации реальных библиотек, пресеты, отражение, старые маски слоёв."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import pytest

from kicadfp import layers as L

DOCS = Path(__file__).resolve().parent.parent / "docs" / "dev"
FIXTURES = Path(__file__).parent / "fixtures"
HEX6 = re.compile(r"^#[0-9A-F]{6}$")


@lru_cache(maxsize=None)
def _json(name: str) -> dict:
    path = DOCS / name
    if not path.exists():
        pytest.skip(f"нет {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def spec(*keys: str):
    """Значение из layers.json по пути ключей; skip, если спецификация его не содержит."""
    node = _json("layers.json")
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            pytest.skip(f"в layers.json нет ключа {'/'.join(keys)}")
        node = node[k]
    return node


# ---------------------------------------------------------------------------
# Списки против layers.json
# ---------------------------------------------------------------------------

def test_copper_layers():
    assert L.COPPER_LAYERS == ["F.Cu", *[f"In{i}.Cu" for i in range(1, 31)], "B.Cu"]
    assert L.COPPER_LAYERS == spec("categories", "copper")
    assert L.INNER_COPPER_LAYERS == L.COPPER_LAYERS[1:-1]


def test_tech_and_user_layers():
    assert L.TECH_LAYERS == spec("categories", "board_tech")
    assert L.BOARD_USER_LAYERS == spec("categories", "user")
    assert L.FOOTPRINT_LAYERS == spec("categories", "footprint")
    assert L.USER_DEFINED_LAYERS == spec("categories", "user_defined", "9.0+")
    assert L.USER_DEFINED_LAYERS_V6 == spec("categories", "user_defined", "6.0-8.0")
    # контракт §5: USER_LAYERS = Dwgs.User … F.Fab, User.1..User.9 и далее
    assert L.USER_LAYERS[:10] == ["Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User",
                                  "Edge.Cuts", "Margin", "B.CrtYd", "F.CrtYd", "B.Fab", "F.Fab"]
    assert L.USER_LAYERS[10:] == [f"User.{i}" for i in range(1, 46)]


@pytest.mark.parametrize("version", ["9.0", "master"])
def test_all_layers_complete(version):
    canon = spec("canonical", version)
    assert set(L.ALL_LAYERS) == set(canon)
    assert len(L.ALL_LAYERS) == len(set(L.ALL_LAYERS)) == 96


def test_version_lists_and_ids():
    assert L.ALL_LAYERS_V6 == spec("canonical", "6.0") == spec("canonical", "8.0")
    assert L.ALL_LAYERS_V5 == spec("canonical", "5.1")
    assert L.LAYER_ID_V6 == spec("ids", "6.0-8.0")
    assert L.LAYER_ID_V5 == spec("ids", "5.1")
    assert L.LAYER_ID_V9 == spec("ids", "9.0+")
    # порядок ALL_LAYERS продолжает порядок 6.0–8.0
    sub = [n for n in L.ALL_LAYERS if n in L.LAYER_ID_V6]
    assert sub == L.ALL_LAYERS_V6


def test_wildcards_and_parser_names():
    assert L.WILDCARDS == spec("wildcards")
    assert L.OLD_INNER_NAMES == spec("old_inner_names")
    assert L.PARSER_EXTRA_COPPER_V9 == spec("parser_extra_names_9.0")
    order = spec("wildcards_written_order")
    flat = [w for item in order for w in item.split("|")]
    assert L.WILDCARD_WRITE_ORDER == flat


def test_flip_pairs_and_sides():
    assert L.FLIP_PAIRS == spec("flip")
    assert L.FRONT_LAYERS == spec("categories", "front")
    assert L.BACK_LAYERS == spec("categories", "back")


def test_pad_presets():
    masks = spec("pad_presets")
    assert set(L.PAD_LAYER_MASKS) == set(masks)
    for key, layers in masks.items():
        assert set(L.PAD_LAYER_MASKS[key]) == set(layers), key
    written = spec("pad_presets_as_written")
    for key, forms in written.items():
        preset = L.PAD_LAYER_PRESETS[key]
        # пресет — ровно форма, которую пишет текущий KiCad (9.0.6+/master) …
        current = forms["9.0.6+/master"] if isinstance(forms, dict) else forms
        assert set(preset) == set(current), key
        # … и без np_thru_hole совпадает по смыслу с внутренней маской pad.cpp
        if key != "np_thru_hole":
            assert set(L.expand(preset)) == set(masks[key]), key
    assert L.PAD_ALLOWED_NON_COPPER == spec("pad_allowed_non_copper")


def test_pad_presets_contract():
    p = L.PAD_LAYER_PRESETS
    assert p["thru_hole"] == ["*.Cu", "*.Mask"]
    assert p["smd"] == ["F.Cu", "F.Paste", "F.Mask"]
    assert p["smd_back"] == ["B.Cu", "B.Paste", "B.Mask"]
    assert p["connect"] == ["F.Cu", "F.Mask"]
    assert p["np_thru_hole"] == ["*.Cu", "*.Mask"]
    for key, preset in p.items():
        assert all(L.is_valid_layer(n) for n in preset), key
    assert [L.flip_layer(n) for n in L.expand(p["smd"])] == ["B.Cu", "B.Paste", "B.Mask"]


def test_pad_masks_collapse_like_writer():
    """Внутренние маски pad.cpp, свёрнутые как formatLayers, = pad_presets_as_written."""
    written = spec("pad_presets_as_written")
    columns = {"6.0-8.0": dict(kicad=8), "9.0.0-9.0.5": dict(kicad=9),
               "9.0.6+/master": dict(kicad=10)}
    for key, forms in written.items():
        for column, kw in columns.items():
            assert L.collapse(L.PAD_LAYER_MASKS[key], **kw) == forms[column], (key, column)


# ---------------------------------------------------------------------------
# Цвета и порядок отрисовки
# ---------------------------------------------------------------------------

def test_colors_all_layers():
    colors = spec("colors")
    for name in L.ALL_LAYERS:
        assert HEX6.match(L.COLORS[name]), name
    for name, value in colors.items():
        assert L.COLORS[name] == value[:7].upper(), name
        alpha = round(int(value[7:9], 16) / 255, 2) if len(value) == 9 else 1.0
        assert L.COLOR_ALPHA.get(name, 1.0) == pytest.approx(alpha, abs=0.01), name
    rgba = spec("colors_rgba")
    for name, item in rgba.items():
        if name in L.COLORS:
            value = item["rgba"] if isinstance(item, dict) else item
            assert L.rgba(name) == pytest.approx(tuple(value), abs=0.01), name


def test_colors_service_keys():
    for key in ("background", "grid", "pad_th", "hole", "npth", "selection", "anchor", "cursor"):
        assert HEX6.match(L.COLORS[key]), key
    ui = spec("colors_ui")
    for key, value in ui.items():
        assert L.COLORS[key] == value[:7].upper(), key
        alpha = round(int(value[7:9], 16) / 255, 2) if len(value) == 9 else 1.0
        assert L.COLOR_ALPHA.get(key, 1.0) == pytest.approx(alpha, abs=0.01), key
    assert all(HEX6.match(v) for v in L.COLORS.values())
    assert set(L.COLOR_ALPHA) <= set(L.COLORS)


def test_color_helpers():
    assert L.color("F.Cu") == "#C83434"
    assert L.color("*.Mask") == L.COLORS["F.Mask"]
    assert L.color("F&B.Cu") == L.COLORS["F.Cu"]
    assert L.color("Inner1.Cu") == L.COLORS["In14.Cu"]
    assert L.color("НетТакого", default="#000000") == "#000000"
    assert L.rgba("F.Mask") == (216, 100, 255, 0.4)
    assert L.rgba("*.Paste")[3] == 0.9


def test_draw_order():
    order = spec("draw_order")
    assert [n for n in L.DRAW_ORDER if n != L.RESCUE_LAYER] == order
    assert set(L.DRAW_ORDER) == set(L.ALL_LAYERS)
    assert len(L.DRAW_ORDER) == len(set(L.DRAW_ORDER))
    # снизу вверх: обратная сторона под лицевой, чертёжные сверху
    idx = L.DRAW_ORDER.index
    assert idx("B.Cu") < idx("In1.Cu") < idx("F.Cu") < idx("Edge.Cuts") < idx("Dwgs.User")
    assert idx("F.Cu") > idx("F.Mask") > idx("F.SilkS") > idx("F.Fab")


# ---------------------------------------------------------------------------
# Проверка имён
# ---------------------------------------------------------------------------

def _inventory_layer_names() -> dict[str, set[str]]:
    inv = _json("token-inventory.json")
    out: dict[str, set[str]] = {}
    for group in ("libraries", "fixtures"):
        for data in inv.get(group, {}).values():
            for token, names in data.get("layer_names", {}).items():
                for name in names:
                    out.setdefault(name, set()).add(token)
    if not out:
        pytest.skip("в token-inventory.json нет layer_names")
    return out


def test_inventory_names_valid():
    """Все имена слоёв из реальных библиотек 6.0–master и фикстур допустимы."""
    names = _inventory_layer_names()
    bad = sorted(n for n in names if not L.is_valid_layer(n))
    assert not bad
    # одиночные (layer X) — только канонические имена
    bad_single = sorted(n for n, toks in names.items()
                        if toks - {"layers"} and not L.is_valid_layer(n, single=True))
    assert not bad_single
    # групповые из инвентаризации раскрываются и сворачиваются обратно
    for n in names:
        if L.is_wildcard(n):
            assert L.expand([n]) == [x for x in L.ALL_LAYERS if x in L.WILDCARDS[n]]


def test_inventory_contains_expected_wildcards():
    names = _inventory_layer_names()
    for w in ("*.Cu", "*.Mask", "F&B.Cu"):
        assert w in names


_LAYER_RE = re.compile(r'\((layers?|private_layers)((?:\s+(?:"[^"]*"|[^\s()"]+))+)\s*\)')
_ATOM_RE = re.compile(r'"([^"]*)"|([^\s()"]+)')


def _files() -> list[Path]:
    files = sorted(FIXTURES.rglob("*.kicad_mod"))
    extra = os.environ.get("KICADFP_EXTRA_FIXTURES", "")
    for d in filter(None, extra.split(os.pathsep)):
        files.extend(sorted(Path(d).rglob("*.kicad_mod")))
    return files


def test_fixture_files_layer_names_valid():
    """Прямой просмотр фикстур: каждое значение layer/layers валидно (и KICADFP_EXTRA_FIXTURES)."""
    files = _files()
    if not files:
        pytest.skip("нет фикстур")
    seen: dict[str, set[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _LAYER_RE.finditer(text):
            token = m.group(1)
            for a in _ATOM_RE.finditer(m.group(2)):
                name = a.group(1) if a.group(1) is not None else a.group(2)
                seen.setdefault(name, set()).add(token)
    assert seen
    bad = {n: t for n, t in seen.items()
           if not L.is_valid_layer(n, single=(t == {"layer"}))}
    assert not bad


@pytest.mark.parametrize("name", [*L.ALL_LAYERS, *L.WILDCARDS, "Inner1.Cu", "Inner14.Cu"])
def test_is_valid_layer_positive(name):
    assert L.is_valid_layer(name)


@pytest.mark.parametrize("name", ["", "F.Silks", "f.cu", "F.Cu ", "In0.Cu", "In63.Cu",
                                  "In31.Cu", "In40.Cu", "In62.Cu",
                                  "In01.Cu", "User.0", "User.46", "Inner15.Cu", "*.User",
                                  "B&F.Cu", "*.Edge", "Top", None, 5])
def test_is_valid_layer_negative(name):
    assert not L.is_valid_layer(name)


def test_is_valid_layer_modes():
    # одиночный (layer X): групповые и InnerN.Cu парсер не принимает
    assert not L.is_valid_layer("*.Cu", single=True)
    assert not L.is_valid_layer("Inner1.Cu", single=True)
    assert L.is_valid_layer("F.SilkS", single=True)
    assert L.is_valid_layer("Rescue", single=True)
    # «призрачные» In31..In62 (layers.md §1.3, §2.4) — ошибка в обоих режимах
    assert not L.is_valid_layer("In40.Cu", single=True)
    assert not L.is_valid_layer("In31.Cu", single=True)
    # версии парсера
    assert L.is_valid_layer("User.9", kicad=8)
    assert not L.is_valid_layer("User.10", kicad=8)
    assert L.is_valid_layer("User.45", kicad=9)
    assert not L.is_valid_layer("In31.Cu", kicad=8)
    assert not L.is_valid_layer("User.1", kicad=5)
    assert L.is_valid_layer("F.CrtYd", kicad=5)
    assert L.is_valid_layer("*.Cu", kicad=6)


def test_phantom_inner_layers_rejected():
    """Регрессия: In31.Cu … In62.Cu — не слои (layers.md §1.3), принимаются только явно."""
    for n in L.PARSER_EXTRA_COPPER_V9:
        assert not L.is_valid_layer(n)
        assert not L.is_valid_layer(n, single=True)
        assert not L.is_copper(n) and not L.is_inner_copper(n)
        # что примет парсер KiCad 9+ (без переноса на Rescue) — только по явному флагу
        assert L.is_valid_layer(n, parser_names=True)
        assert L.is_valid_layer(n, single=True, parser_names=True)
        assert not L.is_valid_layer(n, parser_names=True, kicad=8)
    # expand не считает их медью: остаются неизвестными в конце, в порядке появления
    assert L.expand(["In62.Cu", "*.Cu", "In31.Cu"]) == [*L.COPPER_LAYERS, "In62.Cu", "In31.Cu"]
    assert L.describe("In40.Cu") == "медь, внутренний слой 40 (нет в KiCad)"


# ---------------------------------------------------------------------------
# expand / collapse / sort_layers
# ---------------------------------------------------------------------------

def test_expand():
    assert L.expand(["*.Cu", "*.Mask"]) == [*L.COPPER_LAYERS, "B.Mask", "F.Mask"]
    assert L.expand(["F&B.Cu"]) == ["F.Cu", "B.Cu"]
    assert L.expand(["*In.Cu"]) == L.INNER_COPPER_LAYERS
    assert L.expand(["F.Mask", "F.Cu", "F.Paste", "F.Cu"]) == ["F.Cu", "F.Paste", "F.Mask"]
    assert L.expand(["Inner1.Cu", "Inner14.Cu"]) == ["In1.Cu", "In14.Cu"]
    assert L.expand(["In40.Cu", "B.Cu", "Mystery", "F.Cu"]) == ["F.Cu", "B.Cu", "In40.Cu",
                                                                 "Mystery"]
    assert L.expand("*.SilkS") == ["B.SilkS", "F.SilkS"]
    assert L.expand([]) == []
    for w, members in L.WILDCARDS.items():
        assert set(L.expand([w])) == set(members)


def test_sort_layers():
    assert L.sort_layers(["F.Mask", "F.Paste", "F.Cu"], kicad=8) == ["F.Cu", "F.Paste", "F.Mask"]
    assert L.sort_layers(["F.Mask", "F.Paste", "F.Cu"], kicad=9) == ["F.Cu", "F.Mask", "F.Paste"]
    assert L.sort_layers(["User.1", "In18.Cu", "Rescue"], kicad=9) == ["Rescue", "In18.Cu",
                                                                     "User.1"]
    assert L.sort_layers(["User.1", "In18.Cu", "Rescue"], kicad=8) == ["In18.Cu", "User.1",
                                                                     "Rescue"]
    assert L.sort_layers(["*.Cu", "B.Cu", "zzz"], kicad=9) == ["B.Cu", "*.Cu", "zzz"]
    assert L.sort_layers(L.ALL_LAYERS, kicad=9) == list(L.LAYER_ID_V9)


def test_collapse():
    assert L.collapse(L.COPPER_LAYERS + ["F.Mask", "B.Mask"]) == ["*.Cu", "*.Mask"]
    assert L.collapse(["F.Cu", "B.Cu", "F.Mask", "B.Mask"], kicad=8) == ["F&B.Cu", "*.Mask"]
    assert L.collapse(["F.Cu", "B.Cu", "F.Mask", "B.Mask"], kicad=10) == ["*.Cu", "*.Mask"]
    assert L.collapse(["F.Cu", "B.Cu"], kicad=9, fb_wildcard="*.Cu") == ["*.Cu"]
    # 2-слойная плата: F.Cu+B.Cu = вся медь платы
    assert L.collapse(["F.Cu", "B.Cu", "F.Mask"], copper_count=2) == ["*.Cu", "F.Mask"]
    assert L.collapse(["B.Fab", "F.Fab", "F.CrtYd", "B.CrtYd"]) == ["*.CrtYd", "*.Fab"]
    assert L.collapse(["F.Cu", "F.Paste", "F.Mask"], kicad=8) == ["F.Cu", "F.Paste", "F.Mask"]


def test_legacy_mask_examples_from_spec():
    """legacy_mask_examples из layers.json: набор слоёв и запись всеми версиями writer'а."""
    examples = spec("legacy_mask_examples")
    columns = {"6.0-8.0": dict(kicad=8), "9.0.0-9.0.5": dict(kicad=9),
               "9.0.6+/master": dict(kicad=10)}
    for mask, item in examples.items():
        expected = item["layers"] if isinstance(item, dict) else item
        got = L.legacy_mask_to_layers(int(mask, 16), "STD")
        assert set(got) == set(expected), mask
        assert got == [n for n in L.ALL_LAYERS if n in set(expected)], mask
        if isinstance(item, dict):
            assert L.sort_layers(got, kicad=9) == expected, mask
            for column, kw in columns.items():
                if column in item.get("written", {}):
                    assert L.collapse(got, **kw) == item["written"][column], (mask, column)


# ---------------------------------------------------------------------------
# Старый формат
# ---------------------------------------------------------------------------

ALL_CU = L.COPPER_LAYERS


@pytest.mark.parametrize("mask, pad_type, expected", [
    # ожидания legacy-mod.md / layers.md (маски площадок KiCad 2011)
    ("00E0FFFF", "STD", [*ALL_CU, "F.SilkS", "B.Mask", "F.Mask"]),
    ("00808000", "SMD", ["F.Cu", "F.Mask"]),
    ("00888000", "CONN", ["F.Cu", "F.Paste", "F.Mask"]),
    ("00888000", "SMD", ["F.Cu", "F.Paste", "F.Mask"]),
    ("00E00001", "HOLE", ["B.Cu", "F.SilkS", "B.Mask", "F.Mask"]),
    (0x00E0FFFF, "thru_hole", [*ALL_CU, "F.SilkS", "B.Mask", "F.Mask"]),
    (0x00E00001, "np_thru_hole", ["B.Cu", "F.SilkS", "B.Mask", "F.Mask"]),
    # SMD/CONN с несколькими слоями меди: KiCad 8+ оставляет B.Cu или первый слой
    ("00E0FFFF", "SMD", ["B.Cu", "F.SilkS", "B.Mask", "F.Mask"]),
    ("00808001", "CONN", ["B.Cu", "F.Mask"]),
    ("00808002", "smd", ["F.Cu", "F.Mask"]),
    ("00000006", "SMD", ["In13.Cu"]),
    # биты 29..31 -> Cmts.User; «лишние» старшие биты отбрасываются (uint32)
    ("E0000000", "STD", ["Cmts.User"]),
    (0x1_0000_8000, "STD", ["F.Cu"]),
    ("1FFF0000", "STD", [*L.TECH_LAYERS, "Dwgs.User", "Cmts.User", "Eco1.User",
                         "Eco2.User", "Edge.Cuts"]),
    ("00000000", "STD", []),
])
def test_legacy_mask_to_layers(mask, pad_type, expected):
    assert L.legacy_mask_to_layers(mask, pad_type) == expected


def test_legacy_mask_pad_type_variants():
    for t in ("SMD", "smd", " SMD "):
        assert L.legacy_mask_to_layers("00E0FFFF", t)[0] == "B.Cu"
    # неизвестный тип и None — PTH (ветка else плагина), без урезания
    assert len(L.legacy_mask_to_layers("0000FFFF", "XYZ")) == 32
    assert len(L.legacy_mask_to_layers("0000FFFF", None)) == 32
    # KiCad 6/7 медь не урезали
    assert len(L.legacy_mask_to_layers("0000FFFF", "SMD", kicad=7)) == 32
    assert L.legacy_mask_to_layers("00008001", "SMD", kicad=7) == ["F.Cu", "B.Cu"]


def test_legacy_mask_partial_copper_cu_count():
    # не все 16 бит меди: каждый бит отдельно; при cu_count=16 бит 1 = In14.Cu
    assert L.legacy_mask_to_layers("0000C003", "STD") == ["F.Cu", "In1.Cu", "In14.Cu", "B.Cu"]
    # 4-слойная плата: 1 -> In2, 2 -> In1, 3.. -> F.Cu
    assert L.legacy_mask_to_layers("0000000E", "STD", cu_count=4) == ["F.Cu", "In1.Cu",
                                                                      "In2.Cu"]


def test_legacy_index_and_bits():
    assert {str(k): v for k, v in L.LEGACY_INDEX.items()} == spec("legacy_index")
    bits = spec("legacy_mask_bits")
    for key, item in bits.items():
        layer = item.get("layer") or item.get("layer_lib16")
        assert L.LEGACY_MASK_BITS[int(key, 16)] == layer, key
    assert L.LEGACY_INDEX[0] == "B.Cu" and L.LEGACY_INDEX[15] == "F.Cu"
    assert L.LEGACY_INDEX[16] == "B.Adhes" and L.LEGACY_INDEX[28] == "Edge.Cuts"
    defaults = spec("legacy_pad_default_masks_2011")
    assert {k: f"{v:08X}" for k, v in L.LEGACY_PAD_DEFAULT_MASKS.items()} == defaults
    assert L.LEGACY_MASKS["ALL_CU_LAYERS"] == 0xFFFF
    assert L.LEGACY_MASKS["ALL_TECH_LAYERS"] == (L.LEGACY_MASKS["FRONT_TECH_LAYERS"]
                                                 | L.LEGACY_MASKS["BACK_TECH_LAYERS"])


def test_legacy_layer_to_name_by_cu_count():
    table = spec("legacy_inner_by_cu_count")
    for cu_count, mapping in table.items():
        for number, name in mapping.items():
            assert L.legacy_layer_to_name(int(number), int(cu_count)) == name, (cu_count, number)
    for n in range(32):
        assert L.legacy_layer_to_name(n) == L.LEGACY_INDEX[n]
    assert L.legacy_layer_to_name(40) == "Cmts.User"


# ---------------------------------------------------------------------------
# Классификация, стороны, отражение, имена для GUI
# ---------------------------------------------------------------------------

def test_is_copper():
    for n in L.COPPER_LAYERS:
        assert L.is_copper(n)
    for n in ("*.Cu", "*In.Cu", "F&B.Cu", "Inner3.Cu"):
        assert L.is_copper(n)
    for n in (*L.TECH_LAYERS, *L.USER_LAYERS, "Rescue", "*.Mask", "In0.Cu", "In63.Cu",
              "In31.Cu", "In40.Cu", "In62.Cu"):
        assert not L.is_copper(n), n
    assert L.is_inner_copper("In30.Cu") and not L.is_inner_copper("F.Cu")


def test_sides():
    assert L.is_front("F.SilkS") and not L.is_back("F.SilkS")
    assert L.is_back("B.CrtYd") and not L.is_front("B.CrtYd")
    for n in ("In1.Cu", "Dwgs.User", "Edge.Cuts", "User.1", "*.Cu", "Rescue"):
        assert not L.is_front(n) and not L.is_back(n)
        assert L.layer_side(n) is None
    assert L.layer_side("F.Cu") == "F"
    assert L.layer_side("B.Fab") == "B"
    for f, b in zip(L.FRONT_LAYERS, L.BACK_LAYERS):
        assert L.layer_side(f) == "F" and L.layer_side(b) == "B"


def test_flip_layer():
    pairs = [("F.Cu", "B.Cu"), ("F.SilkS", "B.SilkS"), ("F.Mask", "B.Mask"),
             ("F.Paste", "B.Paste"), ("F.Adhes", "B.Adhes"), ("F.CrtYd", "B.CrtYd"),
             ("F.Fab", "B.Fab")]
    for f, b in pairs:
        assert L.flip_layer(f) == b and L.flip_layer(b) == f
    for n in L.ALL_LAYERS:
        assert L.flip_layer(L.flip_layer(n)) == n
    # 2-слойная плата (по умолчанию): внутренние остаются
    for n in L.INNER_COPPER_LAYERS:
        assert L.flip_layer(n) == n
    for n in ("Dwgs.User", "Edge.Cuts", "User.3", "Rescue", "*.Cu", "*.Mask", "F&B.Cu"):
        assert L.flip_layer(n) == n
    # 4 и 6 слоёв: зеркально внутри стека
    assert L.flip_layer("In1.Cu", 4) == "In2.Cu"
    assert L.flip_layer("In2.Cu", 4) == "In1.Cu"
    assert L.flip_layer("In1.Cu", 6) == "In4.Cu"
    assert L.flip_layer("In3.Cu", 6) == "In2.Cu"
    assert L.flip_layer("In5.Cu", 4) == "F.Cu"          # вне стека: ограничение, как KiCad
    assert L.flip_layers(["F.Cu", "In1.Cu", "F.Mask"]) == ["B.Cu", "In1.Cu", "B.Mask"]


def test_display_name():
    assert L.display_name("F.SilkS") == "F.SilkS (шелкография, верх)"
    assert L.display_name("B.Cu") == "B.Cu (медь, низ)"
    assert L.display_name("In7.Cu") == "In7.Cu (медь, внутренний слой 7)"
    assert L.display_name("*.Mask") == "*.Mask (паяльная маска, обе стороны)"
    assert L.display_name("Edge.Cuts") == "Edge.Cuts (контур платы)"
    assert L.display_name("User.12") == "User.12 (пользовательский слой 12)"
    assert L.display_name("Unknown.Layer") == "Unknown.Layer"
    for n in (*L.ALL_LAYERS, *L.WILDCARDS, *L.OLD_INNER_NAMES):
        d = L.describe(n)
        assert d and re.search("[а-яА-ЯE]", d), n
        assert L.display_name(n).startswith(n + " (")
    names = [L.display_name(n) for n in L.ALL_LAYERS]
    assert len(set(names)) == len(names)


def test_public_names_documented():
    for name in L.__all__:
        obj = getattr(L, name)
        if callable(obj):
            assert obj.__doc__, name


def test_legacy_masks_match_kicad_cli(kicad_cli, legacy_mod, tmp_path):
    """kicad-cli fp upgrade (.mod -> .pretty) даёт те же слои площадок, что и
    legacy_mask_to_layers + collapse (writer 9.0.6+/10)."""
    import subprocess
    from collections import Counter

    out = tmp_path / "out.pretty"
    subprocess.run([kicad_cli, "fp", "upgrade", str(legacy_mod), "-o", str(out)],
                   check=True, capture_output=True, timeout=120)
    got: Counter = Counter()
    for path in out.glob("*.kicad_mod"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\(pad\s.*?\(layers((?:\s+\"[^\"]*\")+)\)", text, re.S):
            got[tuple(re.findall(r'"([^"]*)"', m.group(1)))] += 1
    expected: Counter = Counter()
    for line in legacy_mod.read_text(encoding="latin-1").splitlines():
        if line.startswith("At "):
            parts = line.split()
            expected[tuple(L.collapse(L.legacy_mask_to_layers(parts[3], parts[1]),
                                      kicad=10))] += 1
    assert expected and got == expected
