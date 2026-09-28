"""Тесты kicadfp.render: SVG (stdlib) и PNG (PySide6, если установлен)."""

from __future__ import annotations

import os
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import kicadfp
from kicadfp import layers as L
from kicadfp.model import Footprint, Poly
from kicadfp.render import SVG_NS, render_svg, save_png, save_svg

from .conftest import FIXTURES, fixture_files

NS = {"s": SVG_NS}
Q = f"{{{SVG_NS}}}"


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg.encode("utf-8"))


def _layer_groups(root: ET.Element) -> dict[str, ET.Element]:
    return {g.get("data-layer"): g for g in root.findall("s:g[@class='layer']", NS)}


def _pads(group: ET.Element) -> list[ET.Element]:
    return [g for g in group.findall("s:g", NS) if "pad" in (g.get("class") or "").split()]


def _viewbox(root: ET.Element) -> list[float]:
    return [float(v) for v in root.get("viewBox").split()]


@pytest.fixture
def dip14(dip14_v8: Path) -> Footprint:
    return kicadfp.load(dip14_v8)


@pytest.fixture
def soic8() -> Footprint:
    return kicadfp.load(FIXTURES / "kicad8" / "Package_SO.pretty"
                        / "SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod")


# ---------------------------------------------------------------------------
# Документ
# ---------------------------------------------------------------------------

def test_svg_is_valid_xml(dip14: Footprint) -> None:
    svg = render_svg(dip14)
    assert svg.startswith("<?xml")
    assert svg.endswith("\n")
    root = _parse(svg)
    assert root.tag == Q + "svg"
    assert root.find("s:title", NS).text == "DIP-14_W7.62mm"
    vb = _viewbox(root)
    assert len(vb) == 4 and vb[2] > 0 and vb[3] > 0
    # масштаб по умолчанию — 10 px/мм
    assert float(root.get("width")) == pytest.approx(vb[2] * 10, abs=0.01)
    assert float(root.get("height")) == pytest.approx(vb[3] * 10, abs=0.01)


def test_viewbox_covers_bbox_with_margin(dip14: Footprint) -> None:
    root = _parse(render_svg(dip14, margin=3.0))
    x, y, w, h = _viewbox(root)
    b = dip14.bbox()
    assert x <= b.x1 - 3.0 + 1e-6 and y <= b.y1 - 3.0 + 1e-6
    assert x + w >= b.x2 + 3.0 - 1e-6 and y + h >= b.y2 + 3.0 - 1e-6


def test_scale(dip14: Footprint) -> None:
    r1 = _parse(render_svg(dip14, scale=10))
    r2 = _parse(render_svg(dip14, scale=25))
    assert float(r2.get("width")) == pytest.approx(float(r1.get("width")) * 2.5, abs=0.01)
    assert r1.get("viewBox") == r2.get("viewBox")
    with pytest.raises(ValueError):
        render_svg(dip14, scale=0)
    with pytest.raises(TypeError):
        render_svg("not a footprint")  # type: ignore[arg-type]


def test_background_and_grid_options(dip14: Footprint) -> None:
    root = _parse(render_svg(dip14))
    bg = root.find("s:rect[@class='background']", NS)
    assert bg is not None and bg.get("fill") == L.COLORS["background"]
    assert root.find("s:g[@class='grid']", NS) is not None
    root = _parse(render_svg(dip14, background=False, grid=None))
    assert root.find("s:rect[@class='background']", NS) is None
    assert root.find("s:g[@class='grid']", NS) is None


def test_grid_step_grows_when_too_dense(dip14: Footprint) -> None:
    root = _parse(render_svg(dip14, grid=0.01, scale=10))
    step = float(root.find("s:g[@class='grid']", NS).get("data-step"))
    assert step * 10 >= 4.0


# ---------------------------------------------------------------------------
# Площадки
# ---------------------------------------------------------------------------

def test_dip14_has_14_pads_and_holes(dip14: Footprint) -> None:
    groups = _layer_groups(_parse(render_svg(dip14)))
    cu = _pads(groups["F.Cu"])
    assert len(cu) == 14
    assert {g.get("data-number") for g in cu} == {str(i) for i in range(1, 15)}
    # сквозные площадки рисуются на меди один раз — цветом pad_th
    assert "B.Cu" not in groups
    for g in cu:
        (shape,) = list(g)
        assert shape.get("fill") == L.COLORS["pad_th"]
    # площадка 1 — прямоугольная, прочие — овальные (rx)
    p1 = next(g for g in cu if g.get("data-number") == "1")
    assert p1[0].tag == Q + "rect" and p1[0].get("rx") is None
    p2 = next(g for g in cu if g.get("data-number") == "2")
    assert float(p2[0].get("rx")) == pytest.approx(0.8)
    holes = _pads(groups["holes"])
    assert len(holes) == 14
    assert all(h[0].tag == Q + "circle" and float(h[0].get("r")) == pytest.approx(0.4)
               for h in holes)


def test_smd_pads_use_layer_color(soic8: Footprint) -> None:
    groups = _layer_groups(_parse(render_svg(soic8)))
    cu = _pads(groups["F.Cu"])
    assert len(cu) == 8
    assert all(g[0].get("fill") == L.COLORS["F.Cu"] for g in cu)
    assert "holes" not in groups
    # маска и паста — на своих слоях, с прозрачностью слоя
    assert len(_pads(groups["F.Mask"])) == 8
    assert float(groups["F.Mask"].get("opacity")) == pytest.approx(L.COLOR_ALPHA["F.Mask"])
    assert len(_pads(groups["F.Paste"])) == 8


def test_layers_follow_draw_order(soic8: Footprint) -> None:
    root = _parse(render_svg(soic8))
    names = [g.get("data-layer") for g in root.findall("s:g[@class='layer']", NS)]
    known = [n for n in names if n in L.DRAW_ORDER]
    assert known == sorted(known, key=L.DRAW_ORDER.index)
    assert names.index("F.SilkS") < names.index("F.Cu")


def test_layer_filter(dip14: Footprint) -> None:
    groups = _layer_groups(_parse(render_svg(dip14, layers=["F.SilkS"])))
    assert set(groups) == {"F.SilkS"}
    assert _pads(groups["F.SilkS"]) == []
    groups = _layer_groups(_parse(render_svg(dip14, layers=["*.Cu"])))
    assert "F.SilkS" not in groups and "F.Fab" not in groups
    assert len(_pads(groups["F.Cu"])) == 14
    # только нижняя медь: сквозные площадки — на B.Cu
    groups = _layer_groups(_parse(render_svg(dip14, layers="B.Cu")))
    assert len(_pads(groups["B.Cu"])) == 14
    assert len(_pads(groups["holes"])) == 14
    # строка — одно имя; пустой фильтр — пустой рисунок, но корректный документ
    root = _parse(render_svg(dip14, layers=[]))
    assert _layer_groups(root) == {}
    assert _viewbox(root)[2] > 0


def test_viewbox_follows_filter(dip14: Footprint) -> None:
    full = _viewbox(_parse(render_svg(dip14, margin=0)))
    fab = _viewbox(_parse(render_svg(dip14, layers=["F.CrtYd"], margin=0)))
    assert fab[2] <= full[2] and fab[3] <= full[3]
    crt = dip14.bbox(layers=["F.CrtYd"])
    assert fab[0] == pytest.approx(crt.x1 - 0.025, abs=0.01)


def _fp() -> Footprint:
    fp = Footprint.new("TEST")
    return fp


def test_pad_shapes() -> None:
    fp = _fp()
    fp.new_pad("1", "smd", "roundrect", 0, 0, (2.0, 1.0), angle=90)
    fp.pad("1").roundrect_rratio = 0.25
    fp.new_pad("2", "smd", "trapezoid", 3, 0, (1.0, 1.0))
    fp.pad("2").rect_delta = (0.4, 0.0)
    fp.new_pad("3", "smd", "roundrect", 6, 0, (1.0, 1.0))
    p3 = fp.pad("3")
    p3.chamfer_ratio = 0.25
    p3.chamfer = ["top_left", "bottom_right"]
    p4 = fp.new_pad("4", "smd", "custom", 9, 0, (0.5, 0.5))
    p4.anchor = "circle"
    p4.add_primitive(Poly.new([(0, 0), (1, 0), (1, 1)], width=0, fill=True, primitive=True,
                              uuid=False))
    fp.new_pad("5", "thru_hole", "oval", 12, 0, (1.2, 2.0), drill=(0.6, 1.2))
    fp.new_pad("", "np_thru_hole", "circle", 15, 0, 1.0, drill=1.0)
    groups = _layer_groups(_parse(render_svg(fp)))
    cu = {g.get("data-number"): g for g in _pads(groups["F.Cu"])}
    # поворот: rotate(-угол)
    assert "rotate(-90)" in cu["1"].get("transform")
    assert float(cu["1"][0].get("rx")) == pytest.approx(0.25)
    assert cu["2"][0].tag == Q + "polygon"
    assert len(cu["2"][0].get("points").split()) == 8
    assert cu["3"][0].tag == Q + "path"
    d = cu["3"][0].get("d")
    assert d.startswith("M ") and d.endswith("Z")
    kinds = [c.tag for c in cu["4"].iter()]
    assert Q + "circle" in kinds and Q + "path" in kinds
    assert cu["5"][0].get("fill") == L.COLORS["pad_th"]
    # у NPTH размером с отверстие меди нет, но отверстие есть
    assert "" not in cu
    holes = {g.get("data-number"): g for g in _pads(groups["holes"])}
    assert set(holes) == {"5", ""}
    assert holes[""][0].get("fill") == L.COLORS["npth"]
    assert holes["5"][0].tag == Q + "rect"          # овальное отверстие


def test_chamfer_path_geometry() -> None:
    fp = _fp()
    p = fp.new_pad("1", "smd", "rect", 0, 0, (2.0, 2.0))
    p.chamfer_ratio = 0.25
    p.chamfer = ["top_left"]
    groups = _layer_groups(_parse(render_svg(fp, grid=None)))
    d = _pads(groups["F.Cu"])[0][0].get("d")
    # фаска 0.5 в левом верхнем углу (верх — меньшее Y), обход по часовой на экране
    assert d == "M -1 -0.5 L -0.5 -1 L 1 -1 L 1 1 L -1 1 Z"


def test_drill_offset_moves_shape() -> None:
    fp = _fp()
    p = fp.new_pad("1", "thru_hole", "circle", 0, 0, 2.0, drill=1.0)
    p.drill.offset_x = 0.5
    groups = _layer_groups(_parse(render_svg(fp)))
    shape = _pads(groups["F.Cu"])[0][0]
    assert float(shape.get("cx")) == pytest.approx(0.5)
    hole = _pads(groups["holes"])[0][0]
    assert float(hole.get("cx")) == pytest.approx(0.0)


def test_pad_numbers_option(dip14: Footprint) -> None:
    root = _parse(render_svg(dip14))
    assert "pad_numbers" not in _layer_groups(root)
    root = _parse(render_svg(dip14, pad_numbers=True))
    nums = _layer_groups(root)["pad_numbers"]
    texts = [t.text for t in nums.iter(Q + "text")]
    assert sorted(texts, key=int) == [str(i) for i in range(1, 15)]


# ---------------------------------------------------------------------------
# Графика
# ---------------------------------------------------------------------------

def test_graphics_elements() -> None:
    fp = _fp()
    fp.new_line((0, 0), (5, 0), "F.SilkS", 0.12)
    fp.new_rect((0, 0), (2, 1), "F.Fab", 0.1)
    fp.new_rect((3, 0), (4, 1), "F.Fab", 0.1, fill=True)
    fp.new_circle((0, 5), 1.0, "F.CrtYd", 0.05)
    fp.new_arc((1, 0), (0, -1), (-1, 0), "Dwgs.User", 0.2)
    fp.new_poly([(0, 0), (1, 0), (1, 1)], "Cmts.User", 0.0, fill=True)
    fp.new_curve([(0, 0), (1, 1), (2, 1), (3, 0)], "Eco1.User", 0.1)
    fp.new_line((0, 0), (0, 3), "Eco2.User", 0.0)
    groups = _layer_groups(_parse(render_svg(fp, scale=20)))
    line = groups["F.SilkS"].find("s:line", NS)
    assert line.get("stroke") == L.COLORS["F.SilkS"]
    assert float(line.get("stroke-width")) == pytest.approx(0.12)
    rects = groups["F.Fab"].findall("s:rect", NS)
    assert [r.get("fill") for r in rects] == ["none", L.COLORS["F.Fab"]]
    circle = groups["F.CrtYd"].find("s:circle", NS)
    assert float(circle.get("r")) == pytest.approx(1.0)
    # дуга против часовой стрелки на экране (через верх) -> sweep-flag 0
    arc = groups["Dwgs.User"].find("s:path", NS)
    assert arc.get("d") == "M 1 0 A 1 1 0 0 0 -1 0"
    poly = groups["Cmts.User"].find("s:path", NS)
    assert poly.get("d").endswith("Z")
    assert poly.get("fill") == L.COLORS["Cmts.User"] and poly.get("stroke") == "none"
    curve = groups["Eco1.User"].find("s:path", NS)
    assert curve.get("d").startswith("M 0 0 C ")
    # нулевая ширина без заливки — волосяная линия в 1 пиксель
    hair = groups["Eco2.User"].find("s:line", NS)
    assert float(hair.get("stroke-width")) == pytest.approx(1 / 20)


def test_dashed_stroke() -> None:
    fp = _fp()
    ln = fp.new_line((0, 0), (5, 0), "F.Fab", 0.1)
    ln.stroke_type = "dash"
    el = _layer_groups(_parse(render_svg(fp)))["F.Fab"].find("s:line", NS)
    assert el.get("stroke-dasharray") == "1.2 0.3"


def test_full_circle_arc_and_poly_arc() -> None:
    from kicadfp.render import _arc_command, _poly_path
    cmd = _arc_command((1, 0), (-1, 0), (1, 0))      # начало = конец: окружность
    assert cmd == "A 1 1 0 0 0 -1 0 A 1 1 0 0 0 1 0"
    assert _arc_command((0, 0), (1, 0), (2, 0)) == "L 2 0"
    d = _poly_path([("xy", (0, 0)), ("arc", ((1, 0), (1.5, 0.5), (1, 1)))])
    assert d.startswith("M 0 0 L 1 0 A ") and d.endswith("Z")


# ---------------------------------------------------------------------------
# Тексты
# ---------------------------------------------------------------------------

def _text_groups(group: ET.Element) -> list[ET.Element]:
    return [g for g in group.findall("s:g", NS) if (g.get("class") or "").startswith("text")]


def test_texts(dip14: Footprint) -> None:
    groups = _layer_groups(_parse(render_svg(dip14)))
    silk = _text_groups(groups["F.SilkS"])
    assert [t.find("s:text", NS).text for t in silk] == ["REF**"]
    fab = [t.find("s:text", NS).text for t in _text_groups(groups["F.Fab"])]
    # Value и ${REFERENCE} (подставлено); скрытые поля не рисуются
    assert "DIP-14_W7.62mm" in fab and "REF**" in fab
    assert all("${" not in s for s in fab)
    el = silk[0].find("s:text", NS)
    assert el.get("text-anchor") == "middle"
    assert el.get("fill") == L.COLORS["F.SilkS"]
    ref = dip14.reference
    # кегль = font_size_y (в увеличенной в 100 раз системе группы)
    assert float(el.get("font-size")) / 100 == pytest.approx(ref.font_size_y)
    assert "scale(0.01 0.01)" in silk[0].get("transform")


def test_hidden_texts_option(dip14: Footprint) -> None:
    def count(**kw) -> int:
        root = _parse(render_svg(dip14, **kw))
        return sum(len(_text_groups(g)) for g in _layer_groups(root).values())

    visible = count()
    hidden = sum(1 for t in dip14.texts if t.hide)
    assert hidden > 0
    assert count(show_hidden=True) == visible + hidden


def test_text_justify_mirror_angle() -> None:
    fp = _fp()
    fp.new_text("L", x=1, y=2, layer="F.SilkS", justify=["left", "top"])
    fp.new_text("M", x=0, y=0, layer="B.SilkS", justify=["mirror"])
    fp.new_text("A", x=0, y=0, layer="Cmts.User", angle=180)
    t_un = fp.new_text("U", x=0, y=0, layer="Eco1.User", angle=180)
    t_un.unlocked = True
    fp.new_text("two\nlines", x=0, y=0, layer="Eco2.User")
    groups = _layer_groups(_parse(render_svg(fp)))
    g = next(t for t in _text_groups(groups["F.SilkS"]) if t.find("s:text", NS).text == "L")
    assert g.get("transform").startswith("translate(1 2)")
    assert g.find("s:text", NS).get("text-anchor") == "start"
    assert float(g.find("s:text", NS).get("y")) > 0      # верхнее выравнивание: ниже якоря
    m = _text_groups(groups["B.SilkS"])[0]
    assert "scale(-0.01 0.01)" in m.get("transform")
    # «держать читаемым»: 180° рисуется как 0°, а с unlocked — повёрнутым
    a = _text_groups(groups["Cmts.User"])[0]
    assert "rotate" not in a.get("transform")
    u = _text_groups(groups["Eco1.User"])[0]
    assert "rotate(-180)" in u.get("transform")
    two = _text_groups(groups["Eco2.User"])[0]
    assert [t.text for t in two.findall("s:text", NS)] == ["two", "lines"]


def test_text_escaping() -> None:
    fp = _fp()
    fp.new_text("<&\"'>", layer="F.SilkS")
    svg = render_svg(fp)
    root = _parse(svg)
    texts = [t.text for t in root.iter(Q + "text")]
    assert "<&\"'>" in texts


# ---------------------------------------------------------------------------
# Файлы
# ---------------------------------------------------------------------------

def test_save_svg(dip14: Footprint, tmp_path: Path) -> None:
    out = tmp_path / "dip.svg"
    save_svg(dip14, out, layers=["F.Cu"], scale=5)
    text = out.read_bytes()
    assert b"\r\n" not in text
    root = ET.fromstring(text)
    assert set(_layer_groups(root)) <= {"F.Cu", "holes"}


def test_save_png(dip14: Footprint, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("PySide6.QtSvg")
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    out = tmp_path / "dip.png"
    save_png(dip14, out, width=320)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    assert w == 320
    vb = _viewbox(_parse(render_svg(dip14)))
    assert h == pytest.approx(320 * vb[3] / vb[2], abs=1)
    with pytest.raises(ValueError):
        save_png(dip14, tmp_path / "x.png", width=0)
    with pytest.raises(TypeError):
        save_png(dip14, tmp_path / "x.png", bogus=1)


def test_save_png_transparent(dip14: Footprint, tmp_path: Path) -> None:
    pytest.importorskip("PySide6.QtSvg")
    from PySide6.QtGui import QImage
    out = tmp_path / "t.png"
    save_png(dip14, out, width=100, background=False, grid=None)
    img = QImage(str(out))
    assert img.width() == 100
    assert img.pixelColor(0, 0).alpha() == 0


def test_save_png_without_pyside(dip14: Footprint, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtSvg"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(RuntimeError, match=r"pip install kicadfp\[png\]"):
        save_png(dip14, tmp_path / "x.png")
    assert not (tmp_path / "x.png").exists()


# ---------------------------------------------------------------------------
# Массовая проверка
# ---------------------------------------------------------------------------

def test_empty_footprint() -> None:
    fp = Footprint.new("EMPTY")
    for t in list(fp.texts):
        fp.remove(t)
    root = _parse(render_svg(fp))
    x, y, w, h = _viewbox(root)
    assert w > 0 and h > 0


def test_generators_render() -> None:
    gens = pytest.importorskip("kicadfp.generators")
    for name, func in gens.GENERATORS.items():
        fp = func()
        root = _parse(render_svg(fp))
        assert _layer_groups(root), name


def test_render_all_kicad8_and_special_fixtures() -> None:
    files = fixture_files("kicad8", "special/kicad5", "special/kicad6", "special/kicad8",
                          "special/kicad9", "special/kicad10dev")
    assert len(files) > 1000
    failures: list[str] = []
    for path in files:
        try:
            fp = kicadfp.load(path)
            root = _parse(render_svg(fp, pad_numbers=True, show_hidden=True))
            groups = _layer_groups(root)
            n_pads = sum(len(_pads(g)) for name, g in groups.items()
                         if name in L.COPPER_LAYERS)
            # у NPTH размером с отверстие меди нет — такие площадки не учитываются
            if any(p.type != "np_thru_hole" and any(L.is_copper(x) for x in p.layers)
                   for p in fp.pads) and n_pads == 0:
                failures.append(f"{path}: площадки не нарисованы")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures[:20])


# ---------------------------------------------------------------------------
# Редкие формы токенов и вырожденные случаи
# ---------------------------------------------------------------------------

_RARE = '''(footprint "RARE" (version 20240108) (generator "pcbnew") (layer "F.Cu")
  (pad "1" smd hexagon (at 1 2) (size 2 1) (layers "F.Cu"))
  (fp_curve (pts (xy 0 0) (xy 1 1)) (stroke (width 0.1) (type solid)) (layer "F.SilkS"))
  (fp_poly (pts) (stroke (width 0.1) (type solid)) (fill none) (layer "F.Fab"))
  (fp_text user "NOAT" (layer "Cmts.User") (effects (font (size 1 1) (thickness 0.15))))
  (fp_text user "R270" (at 0 5 270) (layer "Eco1.User")
    (effects (font (size 1 1) (thickness 0.15))))
)'''


def test_unknown_pad_shape_drawn_as_bounding_rect() -> None:
    """Неизвестная (будущая) форма площадки рисуется описанным прямоугольником size."""
    fp = kicadfp.loads(_RARE)
    groups = _layer_groups(_parse(render_svg(fp, grid=None)))
    pad = {g.get("data-number"): g for g in _pads(groups["F.Cu"])}["1"]
    assert pad.get("transform") == "translate(1 2)"
    rect = pad[0]
    assert rect.tag == Q + "rect"
    assert [float(rect.get(k)) for k in ("x", "y", "width", "height")] == [-1, -0.5, 2, 1]
    assert rect.get("rx") is None


def test_curve_without_four_points_and_empty_poly() -> None:
    """Безье не из 4 точек — ломаная; многоугольник без точек не рисуется."""
    fp = kicadfp.loads(_RARE)
    groups = _layer_groups(_parse(render_svg(fp, grid=None)))
    paths = groups["F.SilkS"].findall("s:path", NS)
    assert [p.get("d") for p in paths] == ["M 0 0 L 1 1"]
    assert paths[0].get("fill") == "none"
    assert list(groups.get("F.Fab", [])) == []


def test_text_without_at_skipped_and_270_kept_readable() -> None:
    """Текст без (at) пропускается; 270° («держать читаемым») рисуется как 90°."""
    fp = kicadfp.loads(_RARE)
    groups = _layer_groups(_parse(render_svg(fp, grid=None)))
    assert "Cmts.User" not in groups or not _text_groups(groups["Cmts.User"])
    t = _text_groups(groups["Eco1.User"])[0]
    assert t.get("transform").startswith("translate(0 5) rotate(-90)")
    from kicadfp.render import _readable_angle
    assert _readable_angle(-135.0, False) == pytest.approx(45.0)
    assert _readable_angle(-135.0, True) == pytest.approx(-135.0)


def test_zero_width_bbox_is_widened_without_margin() -> None:
    """Вертикальный отрезок при margin=0: документ расширяется до ширины 1 мм."""
    fp = kicadfp.loads('''(footprint "Y" (version 20240108) (generator "pcbnew")
      (layer "F.Cu")
      (fp_line (start 0 0) (end 0 3) (stroke (width 0) (type solid)) (layer "F.SilkS")))''')
    root = _parse(render_svg(fp, grid=None, margin=0))
    assert _viewbox(root) == pytest.approx([-0.5, 0, 1, 3])
    assert root.get("width") == "10" and root.get("height") == "30"


def test_render_rejects_non_footprint_and_bad_scale(dip14: Footprint) -> None:
    with pytest.raises(TypeError, match="Footprint"):
        render_svg("not a footprint")  # type: ignore[arg-type]
    for bad in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="масштаб"):
            render_svg(dip14, scale=bad)


def test_save_png_unwritable_path_raises(dip14: Footprint, tmp_path: Path) -> None:
    """Ошибка записи PNG (нет каталога) — OSError с путём, файл не создаётся."""
    pytest.importorskip("PySide6.QtSvg")
    out = tmp_path / "no_such_dir" / "x.png"
    with pytest.raises(OSError, match="PNG"):
        save_png(dip14, out, width=50)
    assert not out.exists()
