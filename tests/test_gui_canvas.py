"""Канва корпуса PreviewCanvas (pytest-qt, offscreen): построение сцены, цвета и слои,
выбор щелчком, перетаскивание одной командой отмены, видимость слоёв, масштаб и
панорамирование, снимок виджета."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from kicadfp import generators  # noqa: E402
from kicadfp import layers as L  # noqa: E402
from kicadfp.gui.canvas import (COPPER_ALPHA, ELEMENT_ROLE, GRID_STEPS,  # noqa: E402
                                HOLES_LAYER, LAYER_ROLE, PAD_NUMBERS_LAYER, ZOOM_MAX,
                                PreviewCanvas, _graphic_path, _pad_path)
from kicadfp.gui.commands import (ReplaceNodeCommand, SetAttrCommand,  # noqa: E402
                                  SetAttrsCommand)
from kicadfp.gui.document import FootprintDocument  # noqa: E402
from kicadfp.model import Arc, Graphic, Line, Pad, Rect, Text  # noqa: E402

from .conftest import FIXTURES, fixture_files  # noqa: E402

pytestmark = pytest.mark.gui

DIP14 = FIXTURES / "kicad8" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
POWERPAD = (FIXTURES / "special" / "kicad8"
            / "Package_SO.pretty__TI_SO-PowerPAD-8_ThermalVias.kicad_mod")


# ---------------------------------------------------------------------------------------------
# Фикстуры и помощники
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def doc(qtbot) -> FootprintDocument:
    d = FootprintDocument()
    assert d.open(DIP14)
    yield d
    d.confirm_discard = True
    d.close()


@pytest.fixture
def canvas(qtbot, doc) -> PreviewCanvas:
    c = PreviewCanvas(doc)
    qtbot.addWidget(c)
    c.resize(800, 600)
    c.show()
    qtbot.waitExposed(c)
    return c


def vp(canvas: PreviewCanvas, x: float, y: float) -> QPoint:
    """Точка окна просмотра (целые пиксели) для точки сцены (мм)."""
    return canvas.mapFromScene(QPointF(x, y))


def click(canvas: PreviewCanvas, x: float, y: float) -> None:
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     vp(canvas, x, y))


def drag(canvas: PreviewCanvas, start: tuple[float, float], end: tuple[float, float],
         button: Qt.MouseButton = Qt.MouseButton.LeftButton, steps: int = 4) -> None:
    w = canvas.viewport()
    QTest.mousePress(w, button, Qt.KeyboardModifier.NoModifier, vp(canvas, *start))
    for i in range(1, steps + 1):
        t = i / steps
        QTest.mouseMove(w, vp(canvas, start[0] + (end[0] - start[0]) * t,
                              start[1] + (end[1] - start[1]) * t))
    QTest.mouseRelease(w, button, Qt.KeyboardModifier.NoModifier, vp(canvas, *end))


def drag_px(canvas: PreviewCanvas, start: QPoint, end: QPoint, button: Qt.MouseButton,
            steps: int = 4) -> None:
    w = canvas.viewport()
    QTest.mousePress(w, button, Qt.KeyboardModifier.NoModifier, start)
    for i in range(1, steps + 1):
        QTest.mouseMove(w, start + (end - start) * (i / steps))
    QTest.mouseRelease(w, button, Qt.KeyboardModifier.NoModifier, end)


def silk_line(fp) -> Line:
    return next(g for g in fp.graphics if isinstance(g, Line) and g.layer == "F.SilkS")


def layer_items(canvas: PreviewCanvas, layer: str) -> list:
    return [it for it in canvas.scene().items() if it.data(LAYER_ROLE) == layer]


# ---------------------------------------------------------------------------------------------
# Построение сцены
# ---------------------------------------------------------------------------------------------

def test_dip14_elements(canvas, doc):
    fp = doc.fp
    els = canvas.elements()
    pads = [e for e in els if isinstance(e, Pad)]
    graphics = [e for e in els if isinstance(e, Graphic)]
    texts = [e for e in els if isinstance(e, Text)]
    assert len(pads) == 14
    assert sorted(p.number for p in pads) == sorted(str(i) for i in range(1, 15))
    assert len(graphics) == len(fp.graphics) > 0
    assert set(graphics) == set(fp.graphics)
    # скрытые поля (Footprint, Datasheet, Description) не рисуются
    assert sorted(t.text for t in texts) == sorted(["REF**", "DIP-14_W7.62mm", "${REFERENCE}"])
    # у каждого элемента сцены data(0) — представление модели, data(1) — слой
    for it in canvas.scene().items():
        if it is canvas.highlight_item():
            continue
        assert it.data(ELEMENT_ROLE) in els
        assert isinstance(it.data(LAYER_ROLE), str)
    # элементы сцены площадки: медь, маски F/B, отверстие, номер
    layers = sorted(it.data(LAYER_ROLE) for it in canvas.items_for(fp.pads[0]))
    assert layers == sorted(["F.Cu", "F.Mask", "B.Mask", HOLES_LAYER, PAD_NUMBERS_LAYER])
    assert canvas.scene_layers()[-1] == PAD_NUMBERS_LAYER


def test_show_hidden_texts(canvas, doc):
    n = len([e for e in canvas.elements() if isinstance(e, Text)])
    canvas.show_hidden = True
    texts = [e for e in canvas.elements() if isinstance(e, Text)]
    assert len(texts) == len(doc.fp.texts) > n
    canvas.show_hidden = False
    assert len([e for e in canvas.elements() if isinstance(e, Text)]) == n


def test_colors_and_draw_order(canvas, doc):
    fp = doc.fp
    pad = fp.pads[0]
    by_layer = {it.data(LAYER_ROLE): it for it in canvas.items_for(pad)}
    # сквозная площадка: медь цветом pad_th с прозрачностью, отверстие — фон с каймой hole
    cu = by_layer["F.Cu"].brush().color()
    assert cu.name().upper() == L.COLORS["pad_th"].upper()
    assert cu.alphaF() == pytest.approx(COPPER_ALPHA, abs=0.01)
    hole = by_layer[HOLES_LAYER]
    assert hole.brush().color().name().upper() == L.COLORS["background"].upper()
    assert hole.pen().color().name().upper() == L.COLORS["hole"].upper()
    mask = by_layer["F.Mask"].brush().color()
    assert mask.name().upper() == L.COLORS["F.Mask"].upper()
    assert mask.alphaF() == pytest.approx(L.COLOR_ALPHA["F.Mask"], abs=0.01)
    # порядок по DRAW_ORDER: маска < медь < отверстия < номера
    z = {name: it.zValue() for name, it in by_layer.items()}
    assert z["B.Mask"] < z["F.Mask"] < z["F.Cu"] < z[HOLES_LAYER] < z[PAD_NUMBERS_LAYER]
    # графика: цвет пера — цвет слоя, ширина — width
    line = silk_line(fp)
    (item,) = canvas.items_for(line)
    assert item.data(LAYER_ROLE) == "F.SilkS"
    assert item.pen().color().name().upper() == L.COLORS["F.SilkS"].upper()
    assert item.pen().widthF() == pytest.approx(line.width)
    fab = next(g for g in fp.graphics if g.layer == "F.Fab")
    assert canvas.items_for(fab)[0].zValue() < item.zValue()   # F.Fab ниже F.SilkS
    # площадки поверх графики своего слоя не прячутся под ней, тексты — над площадками
    ref = fp.reference
    (ref_item,) = canvas.items_for(ref)
    assert ref_item.brush().color().name().upper() == L.COLORS["F.SilkS"].upper()
    assert ref_item.zValue() > item.zValue()
    # модели не рисуются
    for m in fp.models:
        assert canvas.items_for(m) == []


def test_smd_and_npth_pads(qtbot):
    doc = FootprintDocument()
    fp = generators.GENERATORS["dip"]()
    smd = fp.new_pad("S", "smd", "roundrect", x=20, y=0, size=(1.0, 2.0))
    npth = fp.new_pad("", "np_thru_hole", "circle", x=25, y=0, size=(2.0, 2.0), drill=2.0)
    trap = fp.new_pad("T", "smd", "trapezoid", x=30, y=0, size=(1.0, 2.0))
    trap.rect_delta = (0.0, 0.4)
    assert doc.open_footprint(fp)
    c = PreviewCanvas(doc)
    qtbot.addWidget(c)
    items = {it.data(LAYER_ROLE): it for it in c.items_for(smd)}
    assert set(items) == {"F.Cu", "F.Paste", "F.Mask", PAD_NUMBERS_LAYER}
    assert items["F.Cu"].brush().color().name().upper() == L.COLORS["F.Cu"].upper()
    # np_thru_hole: только отверстие цвета npth и контур без заливки
    kinds = c.items_for(npth)
    holes = [it for it in kinds if it.data(LAYER_ROLE) == HOLES_LAYER
             and it.brush().style() != Qt.BrushStyle.NoBrush]
    assert len(holes) == 1
    assert holes[0].brush().color().name().upper() == L.COLORS["npth"].upper()
    outline = [it for it in kinds if it.brush().style() == Qt.BrushStyle.NoBrush]
    assert len(outline) == 1
    assert all(it.data(LAYER_ROLE) != PAD_NUMBERS_LAYER for it in kinds)
    # трапеция: четыре угла, верх уже низа на rect_delta
    path = _pad_path(trap)
    r = path.boundingRect()
    assert r.width() == pytest.approx(1.4) and r.height() == pytest.approx(2.0)


def test_pad_rotation_and_shapes(qtbot, doc):
    fp = doc.fp
    pad = fp.pads[1]
    c = PreviewCanvas(doc)
    qtbot.addWidget(c)
    doc.apply(SetAttrsCommand(doc, pad, {"shape": "oval", "size_x": 1.0, "size_y": 3.0,
                                         "angle": 90.0}))
    cu = next(it for it in c.items_for(pad) if it.data(LAYER_ROLE) == "F.Cu")
    rect = cu.sceneBoundingRect()
    # после поворота на 90° вытянута по X
    assert rect.width() == pytest.approx(3.0, abs=0.05)
    assert rect.height() == pytest.approx(1.0, abs=0.05)
    assert rect.center().x() == pytest.approx(pad.x) and rect.center().y() == pytest.approx(pad.y)


def test_arc_path_follows_geometry():
    # дуга от (1, 0) через (0, -1) до (-1, 0): верхняя половина (Y вниз)
    arc = Arc.new((1.0, 0.0), (0.0, -1.0), (-1.0, 0.0), layer="F.SilkS", width=0.1)
    path, closed = _graphic_path(arc)
    assert not closed
    r = path.boundingRect()
    assert r.top() == pytest.approx(-1.0, abs=1e-3) and r.bottom() == pytest.approx(0.0, abs=1e-3)
    assert r.left() == pytest.approx(-1.0, abs=1e-3) and r.right() == pytest.approx(1.0, abs=1e-3)
    # в обратную сторону — нижняя половина
    path2, _ = _graphic_path(Arc.new((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)))
    assert path2.boundingRect().bottom() == pytest.approx(1.0, abs=1e-3)
    assert path2.boundingRect().top() == pytest.approx(0.0, abs=1e-3)
    rect, closed = _graphic_path(Rect.new((0, 0), (2, 1), fill=True))
    assert closed and rect.boundingRect().width() == pytest.approx(2.0)


@pytest.mark.parametrize("path", fixture_files("special/kicad5", "special/kicad6",
                                               "special/kicad8", "special/kicad9",
                                               "special/kicad10dev"),
                         ids=lambda p: p.name)
def test_all_elements_drawn(qtbot, path):
    """Каждая площадка со слоями, вся графика и видимые тексты попадают на сцену (ошибка
    отрисовки элемента не проглатывается молча)."""
    doc = FootprintDocument()
    assert doc.open(path)
    c = PreviewCanvas(doc)
    qtbot.addWidget(c)
    drawn = set(map(id, (e.node for e in c.elements() if hasattr(e, "node"))))
    fp = doc.fp
    for pad in fp.pads:
        if pad.layers:
            assert id(pad.node) in drawn, pad
    for g in fp.graphics:
        if g.layers:
            assert id(g.node) in drawn, g
    for t in fp.texts:
        if not t.hide and t.layer and t.node.find("at") is not None:
            assert id(t.node) in drawn, t


# ---------------------------------------------------------------------------------------------
# Выбор щелчком
# ---------------------------------------------------------------------------------------------

def test_click_selects_pad_and_highlights(canvas, doc, qtbot):
    pad3 = doc.fp.pad(3)
    with qtbot.waitSignal(doc.selection_changed):
        click(canvas, pad3.x + 0.3, pad3.y + 0.3)
    assert doc.selected == pad3
    h = canvas.highlight_item()
    assert h is not None
    assert h.pen().color().name().upper() == L.COLORS["selection"].upper()
    assert h.sceneBoundingRect().contains(QPointF(pad3.x, pad3.y))
    # элемент под точкой — то же представление
    assert canvas.element_at(QPointF(pad3.x, pad3.y)) == pad3
    # щелчок по пустому месту снимает выделение
    click(canvas, 30.0, 30.0)
    assert doc.selected is None and canvas.highlight_item() is None


def test_click_selects_graphic_and_text(canvas, doc):
    fp = doc.fp
    line = silk_line(fp)
    (x1, y1), (x2, y2) = line.start, line.end
    click(canvas, (x1 + x2) / 2, (y1 + y2) / 2)
    assert doc.selected == line
    ref = fp.reference
    click(canvas, ref.x, ref.y)
    assert doc.selected == ref


def test_unfilled_shape_not_hit_inside(canvas, doc):
    """Щелчок внутри незалитого прямоугольника его не выбирает, по контуру — выбирает;
    залитый выбирается и внутри."""
    from kicadfp.gui.commands import AddItemCommand
    cmd = AddItemCommand(doc, Rect.new((12.0, 0.0), (20.0, 8.0), "F.CrtYd", 0.05, fill=False))
    doc.apply(cmd)
    rect = cmd.item
    assert canvas.element_at(QPointF(16.0, 4.0)) is None
    assert canvas.element_at(QPointF(12.0, 4.0)) == rect
    click(canvas, 20.0, 4.0)
    assert doc.selected == rect
    doc.apply(SetAttrCommand(doc, rect, "fill", True))
    assert canvas.element_at(QPointF(16.0, 4.0)) == rect


def test_selection_from_document_is_highlighted(canvas, doc):
    pad = doc.fp.pad(7)
    doc.select(pad)
    h = canvas.highlight_item()
    assert h is not None and h.sceneBoundingRect().contains(QPointF(pad.x, pad.y))
    doc.select(doc.fp)            # корпус целиком — без подсветки
    assert canvas.highlight_item() is None


# ---------------------------------------------------------------------------------------------
# Перетаскивание
# ---------------------------------------------------------------------------------------------

def test_drag_pad_is_one_command(canvas, doc):
    canvas.grid = 1.0
    canvas.snap = True
    pad = doc.fp.pad(1)
    assert pad.position == (0.0, 0.0)
    before = doc.fp.dumps()
    drag(canvas, (0.0, 0.0), (3.0, 2.0), steps=6)
    assert pad.position == (3.0, 2.0)
    assert doc.selected == pad
    stack = doc.undo_stack
    assert stack.count() == 1
    assert isinstance(stack.command(0), SetAttrsCommand)
    assert "площадки 1" in stack.text(0)
    # сцена перестроена: медь площадки на новом месте, подсветка — тоже
    cu = next(it for it in canvas.items_for(pad) if it.data(LAYER_ROLE) == "F.Cu")
    assert cu.sceneBoundingRect().center().x() == pytest.approx(3.0)
    assert canvas.highlight_item().sceneBoundingRect().contains(QPointF(3.0, 2.0))
    doc.undo()
    assert pad.position == (0.0, 0.0)
    assert doc.fp.dumps() == before
    cu = next(it for it in canvas.items_for(pad) if it.data(LAYER_ROLE) == "F.Cu")
    assert cu.sceneBoundingRect().center().x() == pytest.approx(0.0)


def test_drag_temporary_position_and_escape(canvas, doc):
    canvas.grid = 0.5
    pad = doc.fp.pad(2)
    w = canvas.viewport()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     vp(canvas, pad.x, pad.y))
    QTest.mouseMove(w, vp(canvas, pad.x + 1.0, pad.y))
    QTest.mouseMove(w, vp(canvas, pad.x + 2.0, pad.y + 1.0))
    assert canvas.is_dragging
    cu = next(it for it in canvas.items_for(pad) if it.data(LAYER_ROLE) == "F.Cu")
    # во время перетаскивания меняется только временная позиция элемента сцены
    assert cu.sceneBoundingRect().center().x() == pytest.approx(pad.x + 2.0)
    assert pad.position == (0.0, 2.54) and doc.undo_stack.count() == 0
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.is_dragging
    assert cu.sceneBoundingRect().center().x() == pytest.approx(pad.x)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       vp(canvas, pad.x + 2.0, pad.y + 1.0))
    assert pad.position == (0.0, 2.54) and doc.undo_stack.count() == 0


def test_drag_without_snap(canvas, doc):
    canvas.snap = False
    pad = doc.fp.pad(14)
    x0, y0 = pad.position
    drag(canvas, (x0, y0), (x0 + 1.3, y0 - 0.7))
    tol = 2.0 / canvas.zoom   # округление до целых пикселей
    assert pad.x == pytest.approx(x0 + 1.3, abs=tol)
    assert pad.y == pytest.approx(y0 - 0.7, abs=tol)
    assert doc.undo_stack.count() == 1


def test_small_click_does_not_move(canvas, doc):
    pad = doc.fp.pad(5)
    before = pad.position
    click(canvas, pad.x + 0.1, pad.y)
    assert pad.position == before and doc.undo_stack.count() == 0
    assert doc.selected == pad


def test_drag_graphic_is_replace_node_command(canvas, doc):
    canvas.grid = 1.0
    line = silk_line(doc.fp)
    (x1, y1), (x2, y2) = line.start, line.end
    before = doc.fp.dumps()
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    drag(canvas, (mx, my), (mx - 2.0, my + 1.0))
    # опорная точка (начало линии) привязана к сетке
    nx, ny = line.start
    assert nx == pytest.approx(round(x1 - 2.0)) and ny == pytest.approx(round(y1 + 1.0))
    dx, dy = nx - x1, ny - y1
    assert line.end == (pytest.approx(x2 + dx), pytest.approx(y2 + dy))
    assert doc.undo_stack.count() == 1
    assert isinstance(doc.undo_stack.command(0), ReplaceNodeCommand)
    assert doc.selected == line                       # узел тот же — выделение сохранилось
    doc.undo()
    assert doc.fp.dumps() == before
    doc.redo()
    assert line.start == (nx, ny)


def test_drag_text(canvas, doc):
    canvas.grid = 0.5
    ref = doc.fp.reference
    x0, y0 = ref.position
    drag(canvas, (x0, y0), (x0 + 3.0, y0 - 1.0))
    assert ref.position == (pytest.approx(round((x0 + 3.0) * 2) / 2),
                            pytest.approx(round((y0 - 1.0) * 2) / 2))
    assert doc.undo_stack.count() == 1
    doc.undo()
    assert ref.position == (x0, y0)


def test_undo_depth_after_many_drags(canvas, doc):
    pad = doc.fp.pad(8)
    x0, y0 = pad.position
    for i in range(3):
        drag(canvas, (pad.x, pad.y), (pad.x + 1.0, pad.y))
    assert pad.x > x0 + 2.0 and pad.y == pytest.approx(round(y0))
    assert doc.undo_stack.count() == 3
    for _ in range(3):
        doc.undo()
    assert pad.position == (x0, y0)


# ---------------------------------------------------------------------------------------------
# Видимость слоёв, перестроение
# ---------------------------------------------------------------------------------------------

def test_layer_visibility_persists(canvas, doc, qtbot):
    assert layer_items(canvas, "F.SilkS")
    with qtbot.waitSignal(canvas.layers_changed):
        canvas.set_layer_visible("F.SilkS", False)
    assert not canvas.is_layer_visible("F.SilkS")
    assert "F.SilkS" in canvas.hidden_layers
    assert layer_items(canvas, "F.SilkS") == []
    assert doc.fp.reference not in canvas.elements()   # Reference на F.SilkS
    # щелчок по месту скрытой линии её не выбирает
    line = silk_line(doc.fp)
    assert canvas.element_at(QPointF(*line.start)) != line
    # изменение модели (команда) и отмена не возвращают скрытый слой
    doc.apply(SetAttrCommand(doc, doc.fp.pad(1), "x", 0.5))
    assert layer_items(canvas, "F.SilkS") == []
    doc.undo()
    assert layer_items(canvas, "F.SilkS") == []
    # открытие другого корпуса — тоже
    assert doc.open(POWERPAD)
    assert layer_items(canvas, "F.SilkS") == [] and layer_items(canvas, "F.Cu")
    # групповое обозначение и псевдослои
    canvas.set_layer_visible("*.Cu", False)
    assert layer_items(canvas, "F.Cu") == [] and not canvas.is_layer_visible("B.Cu")
    canvas.set_layer_visible(HOLES_LAYER, False)
    assert layer_items(canvas, HOLES_LAYER) == []
    canvas.show_all_layers()
    assert canvas.hidden_layers == frozenset()
    assert layer_items(canvas, "F.SilkS") and layer_items(canvas, "F.Cu")
    with pytest.raises(ValueError):
        canvas.set_layer_visible("Нет.Такого", False)


def test_tht_copper_on_top_visible_layer(canvas, doc):
    pad = doc.fp.pad(1)
    canvas.set_layer_visible("F.Cu", False)
    layers = {it.data(LAYER_ROLE) for it in canvas.items_for(pad)}
    assert "F.Cu" not in layers and "B.Cu" in layers and HOLES_LAYER in layers


def test_rebuild_keeps_selection_and_view(canvas, doc, qtbot):
    pad = doc.fp.pad(4)
    doc.select(pad)
    canvas.set_zoom(40.0)
    canvas.center_on(2.0, 5.0)
    zoom = canvas.zoom
    center = canvas.view_center()
    with qtbot.waitSignal(canvas.rebuilt):
        doc.apply(SetAttrCommand(doc, doc.fp.pad(10), "size_x", 2.0))
    assert canvas.zoom == pytest.approx(zoom)
    assert canvas.view_center().x() == pytest.approx(center.x(), abs=0.1)
    assert canvas.view_center().y() == pytest.approx(center.y(), abs=0.1)
    assert doc.selected == pad and canvas.highlight_item() is not None


def test_removed_element_disappears(canvas, doc):
    from kicadfp.gui.commands import RemoveItemCommand
    line = silk_line(doc.fp)
    doc.select(line)
    doc.apply(RemoveItemCommand(doc, line))
    assert canvas.items_for(line) == [] and canvas.highlight_item() is None
    doc.undo()
    assert canvas.items_for(line)


# ---------------------------------------------------------------------------------------------
# Масштаб, панорамирование, сетка, курсор
# ---------------------------------------------------------------------------------------------

def test_fit_shows_whole_footprint(canvas, doc):
    canvas.set_zoom(ZOOM_MAX)
    canvas.fit()
    rect = canvas.mapToScene(canvas.viewport().rect()).boundingRect()
    b = doc.fp.bbox()
    assert rect.contains(QPointF(b.x1, b.y1)) and rect.contains(QPointF(b.x2, b.y2))
    assert canvas.zoom > 5.0


def test_wheel_zoom_keeps_point_under_cursor(canvas, qtbot):
    pos = vp(canvas, 7.62, 15.24)
    z0 = canvas.zoom
    with qtbot.waitSignal(canvas.zoom_changed):
        QTest.mouseMove(canvas.viewport(), pos)
        # колесо: angleDelta 120 = одно деление
        from PySide6.QtGui import QWheelEvent
        ev = QWheelEvent(QPointF(pos), QPointF(canvas.viewport().mapToGlobal(pos)), QPoint(0, 0),
                         QPoint(0, 240), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        canvas.wheelEvent(ev)
    assert canvas.zoom > z0
    sp = canvas.map_to_scene(QPointF(pos))
    assert sp.x() == pytest.approx(7.62, abs=2.0 / canvas.zoom)
    assert sp.y() == pytest.approx(15.24, abs=2.0 / canvas.zoom)
    canvas.zoom_out()
    canvas.zoom_in()


def test_pan_middle_button_and_space(canvas, doc):
    c0 = canvas.view_center()
    drag_px(canvas, QPoint(400, 300), QPoint(300, 250), Qt.MouseButton.MiddleButton)
    c1 = canvas.view_center()
    k = canvas.zoom
    assert c1.x() - c0.x() == pytest.approx(100 / k, abs=2 / k)
    assert c1.y() - c0.y() == pytest.approx(50 / k, abs=2 / k)
    assert doc.undo_stack.count() == 0
    # пробел + левая кнопка — тоже панорамирование, а не перетаскивание площадки
    pad = doc.fp.pad(1)
    QTest.keyPress(canvas, Qt.Key.Key_Space)
    start = vp(canvas, pad.x, pad.y)
    drag_px(canvas, start, start + QPoint(-80, 0), Qt.MouseButton.LeftButton)
    QTest.keyRelease(canvas, Qt.Key.Key_Space)
    c2 = canvas.view_center()
    assert c2.x() - c1.x() == pytest.approx(80 / k, abs=2 / k)
    assert pad.position == (0.0, 0.0) and doc.undo_stack.count() == 0


def test_grid_property(canvas, qtbot):
    assert GRID_STEPS == (1.25, 1.0, 0.5, 0.25, 0.1)
    with qtbot.waitSignal(canvas.grid_changed):
        canvas.grid = 0.25
    assert canvas.grid == 0.25
    for bad in (0, -1.0, float("inf")):
        with pytest.raises(ValueError):
            canvas.grid = bad
    canvas.grid_visible = False
    assert canvas.grab().toImage().width() > 0
    canvas.grid_visible = True


def test_cursor_moved_signal(canvas, qtbot):
    with qtbot.waitSignal(canvas.cursor_moved) as blocker:
        QTest.mouseMove(canvas.viewport(), vp(canvas, 2.54, 5.08))
    x, y = blocker.args
    assert x == pytest.approx(2.54, abs=2 / canvas.zoom)
    assert y == pytest.approx(5.08, abs=2 / canvas.zoom)


# ---------------------------------------------------------------------------------------------
# Снимок виджета
# ---------------------------------------------------------------------------------------------

def _count_colored(img: QImage, color: str, tol: int = 40) -> int:
    target = QColor(color)
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if (abs(c.red() - target.red()) < tol and abs(c.green() - target.green()) < tol
                    and abs(c.blue() - target.blue()) < tol):
                n += 1
    return n


def test_grab_has_content(canvas, doc):
    canvas.fit()
    img = canvas.grab().toImage()
    assert not img.isNull() and img.width() > 0
    bg = QColor(L.COLORS["background"])
    non_bg = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            if (c.red(), c.green(), c.blue()) != (bg.red(), bg.green(), bg.blue()):
                non_bg += 1
    assert non_bg > 100
    # медь сквозных площадок (pad_th поверх фона) видна на снимке
    assert _count_colored(img, L.COLORS["pad_th"], tol=60) > 20


def test_empty_and_closed_document(qtbot):
    doc = FootprintDocument()
    c = PreviewCanvas(doc)
    qtbot.addWidget(c)
    c.resize(300, 200)
    c.show()
    qtbot.waitExposed(c)
    assert c.elements() == []
    assert not c.grab().toImage().isNull()
    click(c, 0.0, 0.0)            # без корпуса щелчок ничего не ломает
    assert doc.new_footprint("Пустой")
    assert {type(e) for e in c.elements()} <= {Text}
    c.fit()
    doc.close()
    assert c.elements() == []
