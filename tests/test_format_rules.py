"""Тесты kicadfp.format_rules: профили версий, таблицы порядка, группы.

Таблицы сверяются тремя способами: с последовательностями токенов, переписанными из
writer'ов KiCad (pcb_io_kicad_sexpr.cpp 8.0/9.0/10.0, pcb_plugin.cpp 6.0/7.0), с
реальными файлами-фикстурами (порядок дочерних узлов, формы токенов по версии) и с
инвентаризацией docs/dev/token-inventory.json (полнота имён).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kicadfp import format_rules as fr
from kicadfp.sexpr import Node, Str, Sym, dumps, parse, to_compact
from tests.conftest import FIXTURES, fixture_files

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs" / "dev" / "token-inventory.json"


# ---------------------------------------------------------------------------
# Профили: пороги версий
# ---------------------------------------------------------------------------


def test_profile_thresholds():
    p = fr.profile_for
    # fill: solid|none до 9.0 (8.0 = 20240108 пишет (fill solid)), yes|no с 20241129
    assert p(20211014).fill_style == "solid"
    assert p(20240108).fill_style == "solid"
    assert p(20241128).fill_style == "solid"
    assert p(20241129).fill_style == "yesno"
    assert p(20241229).fill_style == "yesno"
    # имена слоёв в кавычках у любого writer'а с корнем footprint; у KiCad 5 — нет
    assert p(20211014).quoted_layers and p(20221018).quoted_layers and p(20241229).quoted_layers
    assert not p(None, "module").quoted_layers
    # групповые слои площадок: 6.0 — голые, 7.0+ — Quotew("*.Cu")
    assert not p(20211014).quoted_wildcards
    assert p(20221018).quoted_wildcards and p(20240108).quoted_wildcards
    # дуги: парсер считает старой формой версии <= 20210925 (LEGACY_ARC_FORMATTING)
    assert not p(20210925).arc_mid and p(20210926).arc_mid and p(20211014).arc_mid
    assert not p(None).arc_mid and not p(None, "module").arc_mid
    # (at (xyz …)) KiCad 5 — дюймы: записывать всегда offset
    assert {p(v).model_offset_token for v in (None, 20211014, 20241229)} == {"offset"}
    assert p(None, "module").model_offset_token == "offset"
    # прочее
    assert p(20211014).uuid_token == "tstamp" and p(20240108).uuid_token == "uuid"
    assert p(20211014).bool_style == "flag" and p(20240108).bool_style == "yesno"
    assert not p(20211014).quoted_generator and p(20240108).quoted_generator
    assert p(20211014).has_tedit and not p(20221018).has_tedit and p(None, "module").has_tedit
    assert p(None).has_tedit  # footprint без version — версия 0, как в парсере KiCad
    assert not p(20221018).text_as_property and p(20230620).text_as_property
    assert not p(20211014).stroke and p(20211229).stroke
    assert p(20240108).solder_paste_ratio_token == "solder_paste_ratio"
    assert p(20240225).solder_paste_ratio_token == "solder_paste_margin_ratio"
    assert p(None).version == 0 and p(None, "module").is_legacy_module
    assert (p(None, "module").style, p(None).style, p(20211014).style, p(20221018).style,
            p(20240108).style) == ("kicad5", "kicad6", "kicad6", "kicad7", "kicad8")
    # таблицы графики по версиям
    assert p(20211014).graphic_order is fr.GRAPHIC_ORDER_V6
    assert p(20221018).graphic_order is fr.GRAPHIC_ORDER_V7
    assert p(20240108).graphic_order is fr.GRAPHIC_ORDER_V8
    assert p(20241229).graphic_order is fr.GRAPHIC_ORDER
    assert p(20211014).text_order is fr.TEXT_ORDER_V6 and p(20240108).text_order is fr.TEXT_ORDER


# ---------------------------------------------------------------------------
# Порядок: последовательности, переписанные из writer'ов KiCad
# ---------------------------------------------------------------------------

# (таблица, последовательность токенов в порядке записи writer'а, источник)
_WRITER_SEQUENCES = [
    (fr.PAD_ORDER, ["at", "size", "rect_delta", "drill", "property", "layers", "remove_unused_layers",
                    "keep_end_layers", "zone_layer_connections", "roundrect_rratio", "chamfer_ratio",
                    "chamfer", "net", "pinfunction", "pintype", "die_length", "solder_mask_margin",
                    "solder_paste_margin", "solder_paste_margin_ratio", "clearance", "zone_connect",
                    "thermal_bridge_width", "thermal_bridge_angle", "thermal_gap", "options",
                    "primitives", "teardrops", "tenting", "uuid", "padstack"], "W9 pad"),
    (fr.PAD_ORDER, ["at", "size", "rect_delta", "drill", "backdrill", "tertiary_drill",
                    "front_post_machining", "back_post_machining", "property", "layers",
                    "remove_unused_layers", "keep_end_layers", "zone_layer_connections",
                    "roundrect_rratio", "chamfer_ratio", "chamfer", "net", "pinfunction", "pintype",
                    "die_length", "die_delay", "solder_mask_margin", "solder_paste_margin",
                    "solder_paste_margin_ratio", "clearance", "zone_connect", "thermal_bridge_width",
                    "thermal_bridge_angle", "thermal_gap", "options", "primitives", "teardrops",
                    "tenting", "uuid", "padstack"], "W10 pad"),
    (fr.PAD_ORDER, ["at", "size", "rect_delta", "drill", "property", "layers", "remove_unused_layers",
                    "keep_end_layers", "roundrect_rratio", "chamfer_ratio", "chamfer", "net",
                    "pinfunction", "pintype", "die_length", "solder_mask_margin", "solder_paste_margin",
                    "solder_paste_margin_ratio", "clearance", "zone_connect", "thermal_width",
                    "thermal_gap", "options", "primitives", "tstamp"], "W6 pad"),
    (fr.GRAPHIC_ORDER, ["start", "mid", "end", "stroke", "fill", "locked", "layer",
                        "solder_mask_margin", "net", "uuid"], "W9 fp_arc"),
    (fr.GRAPHIC_ORDER, ["center", "end", "stroke", "fill", "locked", "layers", "uuid"], "W9 fp_circle"),
    (fr.GRAPHIC_ORDER, ["pts", "stroke", "fill", "locked", "layer", "net", "uuid"], "W9 fp_poly"),
    (fr.GRAPHIC_ORDER, ["center", "major_radius", "minor_radius", "rotation_angle", "start_angle",
                        "end_angle", "stroke", "start_shape", "end_shape", "fill", "layer", "uuid",
                        "custom_property"], "Wmaster fp_ellipse_arc"),
    (fr.GRAPHIC_ORDER_V8, ["start", "mid", "end", "locked", "stroke", "fill", "layer", "net", "uuid"],
     "W8 fp_arc"),
    (fr.GRAPHIC_ORDER_V7, ["locked", "start", "mid", "end", "stroke", "fill", "layer", "tstamp"],
     "W7 fp_arc"),
    (fr.GRAPHIC_ORDER_V6, ["locked", "center", "end", "layer", "width", "fill", "tstamp"], "W6 fp_circle"),
    (fr.GRAPHIC_ORDER_V6, ["start", "end", "angle", "layer", "width"], "W5 fp_arc"),
    (fr.TEXT_ORDER, ["locked", "at", "unlocked", "layer", "uuid", "effects", "render_cache"], "W9 fp_text"),
    (fr.TEXT_ORDER, ["at", "unlocked", "layer", "hide", "uuid", "effects"], "W8/9 property"),
    (fr.TEXT_ORDER_V6, ["at", "layer", "hide", "effects", "tstamp", "render_cache"], "W7 fp_text"),
    (fr.EFFECTS_ORDER, ["font", "justify", "hide", "href"], "T6/7/8 effects"),
    (fr.FONT_ORDER, ["face", "size", "line_spacing", "thickness", "bold", "italic", "color"], "T7-10 font"),
    (fr.STROKE_ORDER, ["width", "type", "color"], "SP9 stroke"),
    (fr.MODEL_ORDER, ["hide", "opacity", "offset", "scale", "rotate"], "W6-10 model"),
    (fr.MODEL_ORDER, ["type", "hide", "overall_height", "body_pcb_gap", "layer", "material", "color",
                      "offset", "scale", "rotate"], "Wmaster extruded model"),
    (fr.FOOTPRINT_ORDER, ["version", "generator", "generator_version", "locked", "placed", "layer",
                          "uuid", "at", "descr", "tags", "property", "component_classes",
                          "path", "sheetname", "sheetfile", "solder_mask_margin", "solder_paste_margin",
                          "solder_paste_margin_ratio", "clearance", "zone_connect", "attr",
                          "private_layers", "net_tie_pad_groups", "fp_line", "pad", "zone", "group",
                          "embedded_fonts", "embedded_files", "model"], "W9 footprint"),
    (fr.FOOTPRINT_ORDER, ["version", "generator", "generator_version", "locked", "placed", "layer",
                          "uuid", "at", "descr", "tags", "property", "component_classes", "path",
                          "sheetname", "sheetfile", "units", "solder_mask_margin", "clearance",
                          "zone_connect", "attr", "stackup", "private_layers", "net_tie_pad_groups",
                          "duplicate_pad_numbers_are_jumpers", "jumper_pad_groups", "fp_line", "barcode",
                          "point", "pad", "zone", "group", "variant", "embedded_fonts", "embedded_files",
                          "model"], "W10 footprint"),
    (fr.FOOTPRINT_ORDER, ["version", "generator", "layer", "tedit", "tstamp", "at", "descr", "tags",
                          "property", "path", "autoplace_cost90", "autoplace_cost180",
                          "solder_mask_margin", "solder_paste_margin", "solder_paste_ratio", "clearance",
                          "zone_connect", "thermal_width", "thermal_gap", "attr", "fp_text", "fp_line",
                          "pad", "zone", "group", "model"], "W6 footprint"),
    (fr.FOOTPRINT_ORDER, ["uuid", "transform", "descr", "model", "custom_property"], "Wmaster footprint"),
]


@pytest.mark.parametrize("table, seq, source", _WRITER_SEQUENCES, ids=[s for _, _, s in _WRITER_SEQUENCES])
def test_tables_follow_writer_sequences(table, seq, source):
    rank = {n: i for i, n in enumerate(table)}
    missing = [t for t in seq if t not in rank]
    assert not missing, f"{source}: нет в таблице {missing}"
    ranks = [rank[t] for t in seq]
    assert ranks == sorted(ranks), f"{source}: порядок нарушен {seq}"


def test_arc_coordinates_order_is_parser_order():
    # парсер KiCad требует (start) (mid) (end) у fp_arc и (center) (end) у fp_circle
    for table in (fr.GRAPHIC_ORDER, fr.GRAPHIC_ORDER_V8, fr.GRAPHIC_ORDER_V7, fr.GRAPHIC_ORDER_V6):
        r = {n: i for i, n in enumerate(table)}
        assert r["start"] < r["mid"] < r["end"] and r["center"] < r["end"]
    arc = parse('(fp_arc (start 0 0) (end 1 1) (stroke (width 0.1) (type solid)) (layer "F.SilkS"))')
    arc.set("mid", 0.5, 0.2, order=fr.GRAPHIC_ORDER)
    assert [c.name for c in arc.nodes()] == ["start", "mid", "end", "stroke", "layer"]


def test_set_with_tables_places_tokens_like_kicad():
    font = parse("(font (size 1 1) (thickness 0.15) (bold yes))")
    font.set("line_spacing", 1.5, order=fr.FONT_ORDER)
    assert [c.name for c in font.nodes()] == ["size", "line_spacing", "thickness", "bold"]
    eff = parse('(effects (font (size 1 1)) (href "x"))')
    eff.set("hide", True, order=fr.EFFECTS_ORDER)
    assert [c.name for c in eff.nodes()] == ["font", "hide", "href"]
    txt = parse('(fp_text user "x" (at 0 0 0) (layer "F.SilkS") (uuid "u") (effects))')
    txt.set("locked", True, order=fr.TEXT_ORDER)
    assert to_compact(txt).startswith('(fp_text user "x"(locked yes)(at')
    line9 = parse('(fp_line (start 0 0) (end 1 0) (stroke (width 0.1) (type solid)) (layer "F.Cu") (uuid "u"))')
    for name, vals in (("net", (1,)), ("solder_mask_margin", (0.1,)), ("locked", (True,))):
        line9.set(name, *vals, order=fr.GRAPHIC_ORDER)
    assert [c.name for c in line9.nodes()] == ["start", "end", "stroke", "locked", "layer",
                                              "solder_mask_margin", "net", "uuid"]
    line8 = parse('(fp_line (start 0 0) (end 1 0) (stroke (width 0.1) (type solid)) (layer "F.Cu") (uuid "u"))')
    line8.set("locked", True, order=fr.GRAPHIC_ORDER_V8)
    assert [c.name for c in line8.nodes()] == ["start", "end", "locked", "stroke", "layer", "uuid"]
    line6 = parse('(fp_line (start 0 0) (end 1 0) (layer "F.SilkS") (width 0.12) (tstamp t))')
    line6.set_flag("locked", True, order=fr.GRAPHIC_ORDER_V6)
    assert to_compact(line6).startswith("(fp_line locked(start")
    model6 = parse('(model "a.wrl" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')
    model6.set_flag("hide", True, order=fr.MODEL_ORDER)
    assert to_compact(model6).startswith('(model "a.wrl" hide(offset')
    fp6 = parse('(footprint "X" (version 20211014) (generator pcbnew) (layer "F.Cu") (tedit 0))')
    fp6.set_flag("locked", True, order=fr.FOOTPRINT_ORDER)
    assert [str(x) if not isinstance(x, Node) else x.name for x in fp6.items] == \
        ["X", "version", "generator", "locked", "layer", "tedit"]


# ---------------------------------------------------------------------------
# Сверка с реальными файлами
# ---------------------------------------------------------------------------


def _generator(root: Node) -> str | None:
    g = root.value("generator")
    return None if g is None else str(g)


def _pcbnew_files() -> list[tuple[Path, Node]]:
    """Файлы, записанные самим KiCad (pcbnew) в релизном формате (версия >= 20211014).

    Ночные 5.99 (20210108–20211013) пропускаются: там, например, узел ``(locked)`` у
    площадок после ``(at)`` — форма, которую KiCad 6+ только читает.
    """
    out = []
    for path in fixture_files():
        root = parse(path.read_text(encoding="utf-8"))
        if (root.name == "footprint" and _generator(root) == "pcbnew"
                and int(root.value("version")) >= 20211014):
            out.append((path, root))
    return out


_PCBNEW = _pcbnew_files()


def _walk(node: Node):
    yield node
    for k in node.nodes():
        yield from _walk(k)


def _graphic_rank_table(profile: fr.FormatProfile) -> dict[str, int]:
    """Ранги корня; вся секция рисования — один ранг (её порядок зависит от версии)."""
    rank = {n: i for i, n in enumerate(fr.FOOTPRINT_ORDER)}
    g = rank["fp_text"]
    for name in fr.GROUPS["graphic"] | fr.GROUPS["text"]:
        rank[name] = g
    return rank


def _check_order(node: Node, rank: dict[str, int], where: str, flags: bool = True) -> None:
    seq = []
    for x in node.items:
        if isinstance(x, Node):
            assert x.name in rank, f"{where}: токен {x.name!r} отсутствует в таблице"
            seq.append((rank[x.name], x.name))
        elif flags and isinstance(x, Sym) and str(x) in rank:
            seq.append((rank[str(x)], str(x)))
    ranks = [r for r, _ in seq]
    assert ranks == sorted(ranks), f"{where}: порядок {[n for _, n in seq]}"


def test_fixture_orders_follow_tables():
    assert len(_PCBNEW) > 100
    for path, root in _PCBNEW:
        prof = fr.profile_for(int(root.value("version")), root.name)
        where = path.name
        _check_order(root, _graphic_rank_table(prof), where, flags=False)
        tables = {
            "pad": fr.PAD_ORDER, "model": fr.MODEL_ORDER, "effects": fr.EFFECTS_ORDER,
            "font": fr.FONT_ORDER, "stroke": fr.STROKE_ORDER, "drill": fr.DRILL_ORDER,
        }
        for name in fr.TEXT_NAMES:
            tables[name] = prof.text_order
        for name in fr.GRAPHIC_NAMES:
            tables[name] = prof.graphic_order
        for child in root.nodes():
            for node in _walk(child):
                table = tables.get(node.name)
                if table is not None and not (node.name == "property" and node is not child):
                    _check_order(node, {n: i for i, n in enumerate(table)}, f"{where}/{node.name}")


def test_fixture_token_forms_match_profile():
    for path, root in _PCBNEW:
        prof = fr.profile_for(int(root.value("version")), root.name)
        where = path.name
        gen = root.find("generator").atom(0)
        assert isinstance(gen, Str) == prof.quoted_generator, where
        assert root.has("generator_version") == prof.has_generator_version, where
        assert root.has("tedit") == prof.has_tedit, where
        names = {n.name for n in _walk(root)}
        assert ("uuid" in names or "tstamp" in names), where
        assert prof.uuid_token in names and ({"uuid", "tstamp"} - {prof.uuid_token}).isdisjoint(names), where
        has_ref_property = any(p.atom(0) == "Reference" for p in root.nodes("property"))
        assert has_ref_property == prof.text_as_property, where
        for node in _walk(root):
            if node.name == "layer" and node.atoms():
                assert isinstance(node.atom(0), Str) == prof.quoted_layers, where
            elif node.name == "layers":
                for a in node.atoms():
                    wildcard = str(a).startswith(("*", "F&B"))
                    expected = prof.quoted_wildcards if wildcard else prof.quoted_layers
                    assert isinstance(a, Str) == expected, (where, str(a))
            elif node.name in fr.GRAPHIC_NAMES:
                assert node.has("stroke") == prof.stroke and node.has("width") != prof.stroke, where
                if node.name == "fp_arc":
                    assert node.has("mid") == prof.arc_mid, where
                fill = node.value("fill")
                if fill is not None:
                    allowed = ("yes", "no") if prof.fill_style == "yesno" else ("solid", "none")
                    assert fill in allowed, (where, fill)
            elif node.name == "model":
                assert not node.has("at") and node.has(prof.model_offset_token), where
            elif node.name == "hide" and prof.bool_style == "yesno":
                assert node.atoms() == ["yes"], where
        if prof.bool_style == "flag":
            assert not any(n.name in ("hide", "locked", "bold", "italic") for n in _walk(root)), where


def test_module_fixtures_profile():
    for path in fixture_files("kicad5"):
        root = parse(path.read_text(encoding="utf-8"))
        if root.name != "module":  # в каталоге есть и файлы ночных 5.99 (корень footprint)
            continue
        prof = fr.profile_for(None, root.name)
        assert prof.style == "kicad5" and not prof.arc_mid and not prof.quoted_layers
        for node in _walk(root):
            if node.name == "fp_arc":
                assert node.has("angle") and not node.has("mid")


def test_inventory_child_names_are_known():
    if not INVENTORY.exists():
        pytest.skip("нет docs/dev/token-inventory.json")
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    by_parent = {
        "footprint": fr.KNOWN_FOOTPRINT_CHILDREN, "module": fr.KNOWN_FOOTPRINT_CHILDREN,
        "pad": set(fr.PAD_ORDER), "model": set(fr.MODEL_ORDER), "effects": set(fr.EFFECTS_ORDER),
        "font": set(fr.FONT_ORDER), "stroke": set(fr.STROKE_ORDER), "drill": set(fr.DRILL_ORDER),
        "fp_text": set(fr.TEXT_ORDER) | set(fr.TEXT_ORDER_V6),
        "property": set(fr.TEXT_ORDER) | set(fr.TEXT_ORDER_V6),
    }
    graphic = set(fr.GRAPHIC_ORDER) | set(fr.GRAPHIC_ORDER_V8) | set(fr.GRAPHIC_ORDER_V7) | \
        set(fr.GRAPHIC_ORDER_V6)
    for name in fr.GRAPHIC_NAMES:
        by_parent[name] = graphic
    unknown = set()
    for section in ("libraries", "fixtures"):
        for set_name, data in inv[section].items():
            for key in data["nodes"]:
                parent, _, child = key.rpartition("/")
                parent = parent.rpartition("/")[2]
                known = by_parent.get(parent)
                if known is not None and child not in known:
                    unknown.add(f"{set_name}: {parent}/{child}")
    assert not unknown, sorted(unknown)


# ---------------------------------------------------------------------------
# Группы и insert_in_group
# ---------------------------------------------------------------------------

_V6 = ('(footprint "X" (version 20211014) (generator pcbnew) (layer "F.Cu") (tedit 0) (descr "d")'
       ' (tags "t") (attr smd) (fp_text reference "R" (at 0 0) (layer "F.SilkS") (effects))'
       ' (fp_text value "V" (at 0 1) (layer "F.Fab") (effects)) (fp_line (start 0 0) (end 1 0)'
       ' (layer "F.SilkS") (width 0.12)) (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))'
       ' (model "a.wrl" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0))))')
_V9 = ('(footprint "X" (version 20241229) (generator "pcbnew") (generator_version "9.0") (layer "F.Cu")'
       ' (descr "d") (tags "t") (property "Reference" "R") (property "Value" "V") (attr smd)'
       ' (fp_line (start 0 0) (end 1 0)) (fp_text user "x") (pad "1" smd rect) (embedded_fonts no))')


def _root_names(root: Node) -> list[str]:
    out = []
    for x in root.nodes():
        if x.name == "fp_text" or x.name == "property":
            out.append(f"{x.name}:{x.atom(0)}")
        else:
            out.append(x.name)
    return out


def test_groups_contract_and_group_of():
    # «text» — тексты секции рисования; property — заголовок (отклонение от контракта:
    # в 8+ все поля — property в заголовке, см. format_rules.GROUPS)
    assert fr.GROUPS["text"] == {"fp_text", "fp_text_box"}
    assert fr.group_of(parse('(fp_text reference "R")')) == "text"
    assert fr.group_of(parse('(fp_text user "x")')) == "text"
    assert fr.group_of(parse('(fp_text_box "x")')) == "text"
    assert fr.group_of(parse('(property "Reference" "R")')) == "header"
    assert fr.group_of(parse("(fp_line)")) == "graphic"
    assert fr.group_of(parse("(fp_ellipse)")) == "graphic"
    assert fr.group_of(parse("(barcode)")) == "graphic"
    assert fr.group_of(parse("(attr smd)")) is None
    assert fr.KNOWN_FOOTPRINT_CHILDREN == frozenset(fr.FOOTPRINT_ORDER)
    assert fr.DRAWING_GROUPS == {"text", "graphic"}


def test_insert_in_group_positions():
    # первое свойство KiCad 6/7 — после tags, до attr (раньше попадало после fp_text)
    root = parse(_V6)
    fr.insert_in_group(root, Node("property", [Str("Sheetfile"), Str("a.kicad_sch")]))
    assert _root_names(root)[:7] == ["version", "generator", "layer", "tedit", "descr", "tags",
                                     "property:Sheetfile"]
    # новое свойство 8+ — после последнего свойства
    root = parse(_V9)
    fr.insert_in_group(root, Node("property", [Str("Datasheet"), Str("")]))
    assert _root_names(root)[6:9] == ["property:Reference", "property:Value", "property:Datasheet"]
    # фигура в 8+ — после фигур, до текстов (KiCad 8+ пишет фигуры раньше текстов)
    root = parse(_V9)
    fr.insert_in_group(root, Node("fp_circle"))
    assert _root_names(root)[-5:] == ["fp_line", "fp_circle", "fp_text:user", "pad",
                                      "embedded_fonts"]
    # текст в 8+ — после текстов
    root = parse(_V9)
    fr.insert_in_group(root, parse('(fp_text user "y")'))
    assert _root_names(root)[-5:] == ["fp_line", "fp_text:user", "fp_text:user", "pad",
                                      "embedded_fonts"]
    # fp_text reference/value (6/7) — после имеющихся reference/value, иначе в начало графики
    root = parse(_V6)
    ref = root.nodes("fp_text")[0]
    root.remove_child(ref)
    fr.insert_in_group(root, ref)
    assert _root_names(root)[7:10] == ["fp_text:value", "fp_text:reference", "fp_line"]
    root = parse(_V6)
    for t in root.nodes("fp_text"):
        root.remove_child(t)
    fr.insert_in_group(root, parse('(fp_text value "V")'))
    assert _root_names(root)[7:9] == ["fp_text:value", "fp_line"]
    # первая модель 9.0 — после embedded_fonts (раньше вставлялась перед ним)
    root = parse(_V9)
    fr.insert_in_group(root, Node("model", [Str("b.wrl")]))
    assert _root_names(root)[-2:] == ["embedded_fonts", "model"]
    # первая площадка — после графики; узлы вне групп — по FOOTPRINT_ORDER
    root = parse(_V6)
    root.remove_child(root.find("pad"))
    fr.insert_in_group(root, Node("pad", [Str("2")]))
    assert _root_names(root)[-2:] == ["pad", "model"]
    root = parse(_V9)
    fr.insert_in_group(root, Node("clearance", [0.2]))
    assert _root_names(root)[8:10] == ["clearance", "attr"]
    root = parse(_V9)
    fr.insert_in_group(root, Node("zone"))
    assert _root_names(root)[-3:] == ["pad", "zone", "embedded_fonts"]


def _drawing_seq(root: Node) -> list[str]:
    out = []
    for x in root.nodes():
        if fr.group_of(x) in fr.DRAWING_GROUPS:
            tag = f"{x.name}:{x.atom(0)}" if x.name == "fp_text" else x.name
            out.append(f"{tag}@{x.value('layer')}")
    return out


def test_insert_drawing_kicad6_texts_before_shapes(dip14_v6):
    """Регрессия: KiCad 6/7 пишет fp_text до фигур — новый текст не уходит в конец секции."""
    root = parse(dip14_v6.read_text(encoding="utf-8"))
    before = _drawing_seq(root)
    assert before[:3] == ["fp_text:reference@F.SilkS", "fp_text:value@F.Fab", "fp_text:user@F.Fab"]
    fr.insert_in_group(root, parse('(fp_text user "NEW" (at 0 0) (layer "F.Fab") (effects))'))
    assert _drawing_seq(root)[:5] == ["fp_text:reference@F.SilkS", "fp_text:value@F.Fab",
                                      "fp_text:user@F.Fab", "fp_text:user@F.Fab", "fp_line@F.SilkS"]
    # фигура 6/7 — среди фигур своего слоя (сортировка KiCad: тип, слой, вид фигуры)
    root = parse(dip14_v6.read_text(encoding="utf-8"))
    new = parse('(fp_line (start 0 0) (end 1 1) (layer "F.CrtYd") (width 0.05))')
    fr.insert_in_group(root, new)
    seq = _drawing_seq(root)
    i = [x for x in root.nodes() if fr.group_of(x) in fr.DRAWING_GROUPS].index(new)
    assert seq[i - 1] == "fp_line@F.CrtYd" and seq[i + 1] != "fp_line@F.CrtYd"
    keys = [fr.drawing_sort_key(x, 20211014) for x in root.nodes()
            if fr.group_of(x) in fr.DRAWING_GROUPS and not fr._is_ref_or_value(x)]
    assert keys == sorted(keys)


def test_insert_drawing_kicad8_shapes_before_texts(dip14_v8):
    """Регрессия: KiCad 8+ пишет фигуры до текстов — новая фигура встаёт перед fp_text."""
    root = parse(dip14_v8.read_text(encoding="utf-8"))
    assert _drawing_seq(root)[-1] == "fp_text:user@F.Fab"
    new = parse('(fp_line (start 0 0) (end 1 1) (stroke (width 0.12) (type solid))'
                ' (layer "F.SilkS"))')
    fr.insert_in_group(root, new)
    seq = _drawing_seq(root)
    assert seq[-1] == "fp_text:user@F.Fab"
    nodes = [x for x in root.nodes() if fr.group_of(x) in fr.DRAWING_GROUPS]
    i = nodes.index(new)
    # после линий F.SilkS, до дуги F.SilkS (вид фигуры: SEGMENT < ARC)
    assert seq[i - 1] == "fp_line@F.SilkS" and seq[i + 1] == "fp_arc@F.SilkS"
    keys = [fr.drawing_sort_key(x, 20240108) for x in nodes]
    assert keys == sorted(keys)


def test_drawing_sort_key_matches_kicad_files():
    """Все файлы pcbnew из фикстур 6+ упорядочены по drawing_sort_key (как cmp_drawings)."""
    checked = 0
    for path in fixture_files("kicad6", "kicad8", "kicad9", "kicad10dev"):
        root = parse(path.read_text(encoding="utf-8"))
        if root.name == "module":   # KiCad 5: writer не сортирует
            continue
        v = fr._root_version(root)
        keys = [fr.drawing_sort_key(x, v) for x in root.nodes()
                if fr.group_of(x) in fr.DRAWING_GROUPS and not fr._is_ref_or_value(x)]
        assert keys == sorted(keys), path
        checked += 1
    assert checked > 100


def test_insert_drawing_unsorted_and_module():
    # секция не упорядочена по слоям (генератор) — только по рангу типа: в конец своего типа
    root = parse('(footprint "X" (version 20241229) (fp_line (layer "F.Fab")) (fp_line (layer'
                 ' "F.SilkS")) (fp_text user "t" (layer "F.Fab")) (pad "1"))')
    fr.insert_in_group(root, parse('(fp_arc (layer "Edge.Cuts"))'))
    assert [x.name for x in root.nodes()] == ["version", "fp_line", "fp_line", "fp_arc",
                                              "fp_text", "pad"]
    # текст, когда в 8+ текстов нет, — после фигур; фигура, когда нет фигур, — перед текстами
    root = parse('(footprint "X" (version 20241229) (fp_line (layer "F.Fab")) (pad "1"))')
    fr.insert_in_group(root, parse('(fp_text user "t" (layer "F.SilkS"))'))
    assert [x.name for x in root.nodes()] == ["version", "fp_line", "fp_text", "pad"]
    root = parse('(footprint "X" (version 20241229) (fp_text user "t") (pad "1"))')
    fr.insert_in_group(root, parse('(fp_rect (layer "F.Fab"))'))
    assert [x.name for x in root.nodes()] == ["version", "fp_rect", "fp_text", "pad"]
    # KiCad 5 (module, writer не сортирует) — в конец секции
    root = parse('(module X (fp_text reference R) (fp_line (layer F.Fab)) (fp_text user t)'
                 ' (pad 1))')
    fr.insert_in_group(root, parse('(fp_circle (layer F.SilkS))'))
    assert [x.name for x in root.nodes()] == ["fp_text", "fp_line", "fp_text", "fp_circle", "pad"]


@pytest.mark.kicad_cli
def test_kicad_cli_insert_order_survives_resave(kicad_cli, tmp_path):
    """Новые элементы в файле KiCad 9 стоят там же, куда их ставит пересохранение KiCad."""
    src = FIXTURES / "kicad9" / "Capacitor_SMD.pretty" / \
        "C_0603_1608Metric_Pad1.08x0.95mm_HandSolder.kicad_mod"
    root = parse(src.read_text(encoding="utf-8"))

    def uid(n: int) -> str:
        return f'"{str(n) * 8}-1111-1111-1111-111111111111"'

    new = [
        f'(fp_line (start 50 50) (end 51 51) (stroke (width 0.12) (type solid)) (layer "F.SilkS")'
        f' (uuid {uid(1)}))',
        f'(fp_text user "NEW" (at 0 0 0) (layer "Cmts.User") (uuid {uid(2)})'
        ' (effects (font (size 1 1) (thickness 0.15))))',
        f'(fp_circle (center 0 0) (end 1 0) (stroke (width 0.05) (type solid)) (fill no)'
        f' (layer "F.CrtYd") (uuid {uid(3)}))',
        f'(fp_line (start -50 -50) (end 51 51) (stroke (width 0.12) (type solid)) (layer "B.Fab")'
        f' (uuid {uid(4)}))',
        f'(fp_text user "NEW2" (at 0 0 0) (layer "B.SilkS") (uuid {uid(5)})'
        ' (effects (font (size 1 1) (thickness 0.15))))',
    ]
    for text in new:
        fr.insert_in_group(root, parse(text))
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    (lib / "T.kicad_mod").write_text(dumps(root), encoding="utf-8")
    out = tmp_path / "out.pretty"
    subprocess.run([kicad_cli, "fp", "upgrade", "--force", "-o", str(out), str(lib)],
                   capture_output=True, text=True, timeout=120)
    saved = parse((out / "T.kicad_mod").read_text(encoding="utf-8"))

    def seq(r: Node) -> list[tuple[str, str]]:
        return [(x.name, str(x.value("uuid"))) for x in r.nodes()
                if fr.group_of(x) in fr.DRAWING_GROUPS]

    assert seq(saved) == seq(root)


def test_order_for():
    p6, p9 = fr.profile_for(20211014), fr.profile_for(20241229)
    assert fr.order_for("fp_line", p6) is fr.GRAPHIC_ORDER_V6
    assert fr.order_for("fp_arc", p9) is fr.GRAPHIC_ORDER
    assert fr.order_for("property") is fr.TEXT_ORDER
    assert fr.order_for("fp_text", p6) is fr.TEXT_ORDER_V6
    assert fr.order_for("module") is fr.FOOTPRINT_ORDER
    assert fr.order_for("zone") is None


# ---------------------------------------------------------------------------
# Версии формата новых корпусов по версии KiCad
# ---------------------------------------------------------------------------

def test_kicad_format_versions():
    assert fr.KICAD_FORMAT_VERSIONS == {6: 20211014, 7: 20221018, 8: 20240108, 9: 20241229}
    assert fr.KICAD_FORMAT_VERSIONS[9] == fr.DEFAULT_VERSION
    for target, version in ((8, 20240108), ("9", 20241229), ("kicad7", 20221018),
                            ("KiCad 6", 20211014), (20240108, 20240108), ("20221018", 20221018)):
        assert fr.kicad_format_version(target) == version, target
    # профиль каждой версии пишет свою форму: 6 — width и fp_text, 8 — поля, 9 — fill yes|no
    assert not fr.profile_for(20211014).stroke and fr.profile_for(20221018).stroke
    assert fr.profile_for(20240108).text_as_property and fr.profile_for(20240108).fill_style \
        == "solid"
    assert fr.profile_for(20241229).fill_style == "yesno"
    for bad in (5, 10, 20240109, "20260206", "kicad", "", None, True, 8.0):
        with pytest.raises(ValueError, match="версия KiCad"):
            fr.kicad_format_version(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# KiCad читает то, что получается по таблицам (необязательный тест с kicad-cli)
# ---------------------------------------------------------------------------


@pytest.mark.kicad_cli
def test_kicad_cli_loads_table_ordered_arc(kicad_cli, tmp_path):
    base = ('(footprint "A" (version 20241229) (generator "pcbnew") (generator_version "9.0")'
            ' (layer "F.Cu") (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS")'
            ' (uuid "11111111-1111-1111-1111-111111111111") (effects (font (size 1 1))))'
            ' (fp_arc (start 0 0) (end 1 1) (stroke (width 0.1) (type solid)) (layer "F.SilkS")'
            ' (uuid "22222222-2222-2222-2222-222222222222")) (embedded_fonts no))')
    good = parse(base)
    good.find("fp_arc").set("mid", 0.5, 0.2, order=fr.GRAPHIC_ORDER)
    bad = parse(base)
    bad.find("fp_arc").append(Node("mid", [0.5, 0.2]))  # старый порядок таблицы: после end
    results = {}
    for name, tree in (("good", good), ("bad", bad)):
        lib = tmp_path / f"{name}.pretty"
        lib.mkdir()
        (lib / "A.kicad_mod").write_text(dumps(tree), encoding="utf-8")
        out = tmp_path / f"out_{name}.pretty"
        subprocess.run([kicad_cli, "fp", "upgrade", "--force", "-o", str(out), str(lib)],
                       capture_output=True, text=True, timeout=120)
        results[name] = (out / "A.kicad_mod").exists()
    assert results == {"good": True, "bad": False}
