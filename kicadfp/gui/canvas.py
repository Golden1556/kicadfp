"""Канва предпросмотра и редактирования корпуса: :class:`PreviewCanvas` (``QGraphicsView``).

Система координат
-----------------
Сцена — в миллиметрах KiCad: 1 единица сцены = 1 мм, ось Y направлена вниз (как в
KiCad); масштаб (пикселей на миллиметр) задаётся преобразованием вида
(``QTransform.fromScale(k, k)``), см. :attr:`PreviewCanvas.zoom`. Положительный угол KiCad —
поворот против часовой стрелки на экране, поэтому элементы поворачиваются на ``-угол``
(``QGraphicsItem.setRotation``); дуги строятся ``QPainterPath.arcTo`` по
:func:`kicadfp.geometry.arc_from_three_points` (соглашение об углах совпадает с Qt).

Отрисовка
---------
Фон и сетка рисуются в :meth:`PreviewCanvas.drawBackground` (цвета ``background``,
``grid``; оси через начало координат — ``grid_axes``); шаг сетки — :attr:`grid` (список
для меню — :data:`GRID_STEPS`), при слишком мелком шаге на экране он удваивается.

Элементы корпуса — элементы сцены (``QGraphicsPathItem``), по одному на каждый слой
элемента; у каждого ``data(ELEMENT_ROLE)`` (``data(0)``) — представление модели
(:class:`~kicadfp.model.Pad`, :class:`~kicadfp.model.Graphic`, :class:`~kicadfp.model.Text`)
или узел зоны, ``data(LAYER_ROLE)`` — имя слоя. Порядок по оси Z — по
:data:`kicadfp.layers.DRAW_ORDER` (неизвестные слои — ниже всех; внутри слоя графика,
затем площадки, затем тексты), псевдослой отверстий :data:`HOLES_LAYER` — сразу над
``F.Cu``, номера площадок :data:`PAD_NUMBERS_LAYER` — наверху. Цвета —
:data:`kicadfp.layers.COLORS`, прозрачность немедных слоёв — :data:`~kicadfp.layers.COLOR_ALPHA`,
меди — :data:`COPPER_ALPHA`.

* Площадки: ``thru_hole`` — медь цветом ``pad_th`` (один раз, на верхнем видимом медном
  слое) и отверстие (цвет фона с каймой ``hole``); ``smd``/``connect`` — цветом каждого
  своего медного слоя; ``np_thru_hole`` — только отверстие (цвет ``npth``) и контур
  площадки; на немедных слоях (маска, паста) — цветом слоя без учёта зазоров. Формы:
  ``circle``, ``rect``, ``oval``, ``roundrect``, фаски (``chamfer``), ``trapezoid``,
  ``custom`` (якорь + примитивы, упрощённо: линии — контуром ширины линии). Номер площадки —
  текстом внутри неё (без поворота).
* Графика: линия, прямоугольник, окружность, дуга, многоугольник (с дугами внутри ``pts``),
  кривая Безье; ширина пера = ``width`` (0 — волосяная линия в 1 пиксель), концы
  скруглены, заливка — по ``fill``, штриховые типы линий — узором пера.
* Тексты: контуры глифов шрифта без засечек (не штриховой шрифт KiCad): высота прописных
  = ``font_size_y``, ширина — пропорционально ``font_size_x``; выравнивание ``justify``,
  зеркальность, угол по правилу KiCad «держать читаемым», ``bold``/``italic``;
  подстановка ``${REFERENCE}``/``${VALUE}``; скрытые тексты не рисуются, пока не включено
  :attr:`show_hidden`.
* Зоны корпуса — контуром с полупрозрачной заливкой; 3D-модели не рисуются.

Канва не хранит копий данных модели: сцена целиком перестраивается по сигналу
``FootprintDocument.changed`` (с сохранением выделения, масштаба и положения вида);
элементы сцены сгруппированы по ключу ``id(view.node)``.

Мышь и клавиатура
-----------------
* колесо — масштаб относительно точки под курсором; :meth:`fit` — «вписать» (клавиша
  ``Home``), ``+``/``-`` — масштаб относительно центра;
* средняя кнопка или левая кнопка с зажатым пробелом — панорамирование;
* щелчок левой кнопкой — выбор элемента (:meth:`element_at`, затем
  ``FootprintDocument.select``), подсветка цветом ``selection``; щелчок по пустому месту
  снимает выделение;
* перетаскивание выбранной площадки, графики или текста левой кнопкой: во время
  перетаскивания элементы сцены смещаются временно, при отпускании применяется одна
  команда — :class:`~kicadfp.gui.commands.SetAttrsCommand` (``x``/``y``) для площадок и
  текстов, :class:`~kicadfp.gui.commands.ReplaceNodeCommand` (``move(dx, dy)`` копии узла)
  для графики; ``Esc`` отменяет перетаскивание. При :attr:`snap` к сетке привязывается
  опорная точка элемента (центр площадки, точка привязки текста, первая точка фигуры);
* :attr:`cursor_moved` ``(x, y)`` — координаты курсора в мм (для статусной строки).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QKeyEvent, QMouseEvent,
                           QPainter, QPainterPath, QPainterPathStroker, QPen, QResizeEvent,
                           QShowEvent, QTransform, QWheelEvent)
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsView, QWidget)

from .. import geometry as _geo
from .. import layers as _L
from ..model import Arc, Circle, Curve, Footprint, Graphic, Line, Pad, Poly, Rect, Text, View
from ..render import _readable_angle, _substitute
from ..sexpr import Node
from .commands import ReplaceNodeCommand, SetAttrsCommand, describe_item

__all__ = [
    "PreviewCanvas", "GRID_STEPS", "HOLES_LAYER", "PAD_NUMBERS_LAYER", "ELEMENT_ROLE",
    "LAYER_ROLE", "COPPER_ALPHA", "ZOOM_MIN", "ZOOM_MAX",
]

#: Шаги сетки для меню «Вид → Сетка», мм.
GRID_STEPS: tuple[float, ...] = (1.25, 1.0, 0.5, 0.25, 0.1)
#: Псевдослой отверстий площадок (рисуется сразу над ``F.Cu``).
HOLES_LAYER = "holes"
#: Псевдослой номеров площадок (рисуется поверх всех слоёв).
PAD_NUMBERS_LAYER = "pad_numbers"
#: Ключ ``QGraphicsItem.data``: элемент модели (представление или узел зоны).
ELEMENT_ROLE = 0
#: Ключ ``QGraphicsItem.data``: имя слоя элемента сцены.
LAYER_ROLE = 1
#: Непрозрачность меди (площадки и графика на медных слоях).
COPPER_ALPHA = 0.8
#: Пределы масштаба, пикселей на миллиметр.
ZOOM_MIN = 0.5
ZOOM_MAX = 5000.0
#: Шаг масштаба на одно деление колеса (120 единиц ``angleDelta``).
ZOOM_STEP = 1.25

_PSEUDO_LAYERS = (HOLES_LAYER, PAD_NUMBERS_LAYER)
# Половина стороны сцены, мм: сцена фиксированного размера, чтобы перестроение не сдвигало вид.
_SCENE_EXTENT = 1000.0
# Допуск попадания щелчка, пикселей.
_PICK_PX = 4.0
# Минимальный шаг сетки на экране, пикселей (мельче — шаг удваивается).
_MIN_GRID_PX = 6.0
# Поле при «вписать», доля размера и минимум в мм.
_FIT_MARGIN = 0.08
_FIT_MARGIN_MM = 0.5
_HIGHLIGHT_Z = 1.0e6
# Размер шрифта, из которого строятся контуры текстов (потом масштабируются).
_TEXT_PX = 100
_FONT_FAMILIES = ["DejaVu Sans", "Liberation Sans", "Arial", "Helvetica", "Sans Serif"]
_LINE_PITCH = 1.62
_DASH_PATTERNS = {
    "dash": [12.0, 3.0], "dot": [0.2, 3.0], "dash_dot": [12.0, 3.0, 0.2, 3.0],
    "dash_dot_dot": [12.0, 3.0, 0.2, 3.0, 0.2, 3.0],
}


# ---------------------------------------------------------------------------------------------
# Порядок слоёв и цвета
# ---------------------------------------------------------------------------------------------

def _build_rank() -> dict[str, int]:
    order: list[str] = []
    for name in _L.DRAW_ORDER:
        order.append(name)
        if name == "F.Cu":
            order.append(HOLES_LAYER)
    order.append(PAD_NUMBERS_LAYER)
    return {name: i for i, name in enumerate(order)}


_RANK = _build_rank()


def _z(layer: str, sub: int = 0) -> float:
    """Значение Z элемента слоя ``layer`` (``sub``: 0 — графика, 1 — площадки, 2 — тексты)."""
    return (_RANK.get(layer, -1) + 1) * 4.0 + sub


def _qcolor(key: str, alpha: float | None = None) -> QColor:
    """Цвет слоя или служебного ключа :data:`~kicadfp.layers.COLORS` с прозрачностью."""
    r, g, b, a = _L.rgba(key)
    if alpha is None:
        alpha = COPPER_ALPHA if key not in _PSEUDO_LAYERS and _is_copper(key) else a
    c = QColor(r, g, b)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _is_copper(name: str) -> bool:
    try:
        return _L.is_copper(name)
    except Exception:  # noqa: BLE001 — необычное имя слоя
        return False


def _is_inner(name: str) -> bool:
    try:
        return _L.is_inner_copper(name)
    except Exception:  # noqa: BLE001
        return False


def _draw_layers(names: Iterable[str]) -> list[str]:
    """Слои, на которых рисуется элемент: групповые обозначения раскрываются, но
    внутренние медные слои из них (``*.Cu``) не берутся — у корпуса в библиотеке их нет,
    медь сквозной площадки рисуется на ``F.Cu``/``B.Cu``; явно названные — рисуются."""
    names = list(names)
    explicit = set(names)
    return [n for n in _expand(names) if n in explicit or not _is_inner(n)]


def _expand(names: Iterable[str]) -> list[str]:
    """Раскрыть групповые обозначения слоёв (неизвестные имена — как есть)."""
    out: list[str] = []
    for n in names:
        try:
            got = _L.expand([n])
        except Exception:  # noqa: BLE001 — неизвестное имя рисуется на «своём» слое
            got = [n]
        for g in got or [n]:
            if g not in out:
                out.append(g)
    return out


# ---------------------------------------------------------------------------------------------
# Построение контуров
# ---------------------------------------------------------------------------------------------

def _pt(p: tuple[float, float]) -> QPointF:
    return QPointF(float(p[0]), float(p[1]))


def _arc_to(path: QPainterPath, s: tuple[float, float], m: tuple[float, float],
            e: tuple[float, float]) -> None:
    """Добавить к пути дугу от ``s`` (текущая точка) через ``m`` до ``e``."""
    if _geo.distance(s, e) < 1e-9 and _geo.distance(s, m) > 1e-9:
        # начало совпадает с концом: окружность с диаметром start–mid (как у KiCad)
        c = ((s[0] + m[0]) / 2.0, (s[1] + m[1]) / 2.0)
        r = _geo.distance(s, m) / 2.0
        path.arcTo(QRectF(c[0] - r, c[1] - r, 2 * r, 2 * r), _geo.angle_of(c, s), -360.0)
        return
    g = _geo.arc_from_three_points(s, m, e)
    if g is None or g.radius <= 0:
        path.lineTo(_pt(e))
        return
    cx, cy = g.center
    r = g.radius
    path.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), g.start_angle, g.sweep)


def _graphic_path(g: Graphic) -> tuple[QPainterPath, bool]:
    """Контур фигуры в её координатах и признак «фигура замкнута» (можно залить)."""
    path = QPainterPath()
    closed = False
    if isinstance(g, Line):
        path.moveTo(_pt(g.start))
        path.lineTo(_pt(g.end))
    elif isinstance(g, Rect):
        (x1, y1), (x2, y2) = g.start, g.end
        path.addRect(QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized())
        closed = True
    elif isinstance(g, Circle):
        r = g.radius
        path.addEllipse(_pt(g.center), r, r)
        closed = True
    elif isinstance(g, Arc):
        s, m, e = g.start, g.mid, g.end
        path.moveTo(_pt(s))
        _arc_to(path, s, m, e)
    elif isinstance(g, Poly):
        first = True
        for kind, v in g._segments():  # noqa: SLF001 — контур с дугами (модель)
            if kind == "xy":
                if first:
                    path.moveTo(_pt(v))
                else:
                    path.lineTo(_pt(v))
            else:
                s, m, e = v
                if first:
                    path.moveTo(_pt(s))
                else:
                    path.lineTo(_pt(s))
                _arc_to(path, s, m, e)
            first = False
        if not first:
            path.closeSubpath()
            closed = True
    elif isinstance(g, Curve):
        pts = list(g.points)
        if len(pts) == 4:
            path.moveTo(_pt(pts[0]))
            path.cubicTo(_pt(pts[1]), _pt(pts[2]), _pt(pts[3]))
        elif pts:
            path.moveTo(_pt(pts[0]))
            for p in pts[1:]:
                path.lineTo(_pt(p))
    return path, closed


def _safe_fill(g: Graphic) -> bool:
    try:
        return bool(g.fill)
    except Exception:  # noqa: BLE001 — повреждённый узел fill не мешает отрисовке
        return False


def _stroke_outline(path: QPainterPath, width: float) -> QPainterPath:
    """Контур линии ширины ``width`` вдоль ``path`` (скруглённые концы и стыки)."""
    st = QPainterPathStroker()
    st.setWidth(max(width, 1e-4))
    st.setCapStyle(Qt.PenCapStyle.RoundCap)
    st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return st.createStroke(path)


def _rect_path(ox: float, oy: float, sx: float, sy: float, r: float, c: float,
               corners: list[str]) -> QPainterPath:
    """Прямоугольник ``sx × sy`` с центром ``(ox, oy)``, скруглением ``r`` и фасками ``c``
    на углах ``corners`` (``top_left`` … — «верх» — меньшее Y)."""
    hx, hy = sx / 2.0, sy / 2.0
    path = QPainterPath()
    if not corners:
        rect = QRectF(ox - hx, oy - hy, sx, sy)
        if r > 0:
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
        return path
    # обход по часовой стрелке на экране: угол, направление входящей и выходящей сторон,
    # начальный угол дуги скругления (Qt: против часовой стрелки на экране)
    spec = [("top_left", (-hx, -hy), (0.0, -1.0), (1.0, 0.0), 180.0),
            ("top_right", (hx, -hy), (1.0, 0.0), (0.0, 1.0), 90.0),
            ("bottom_right", (hx, hy), (0.0, 1.0), (-1.0, 0.0), 0.0),
            ("bottom_left", (-hx, hy), (-1.0, 0.0), (0.0, -1.0), 270.0)]
    first = True
    for name, (px, py), din, dout, start in spec:
        chamfer = name in corners
        a = c if chamfer else r
        p_in = QPointF(ox + px - din[0] * a, oy + py - din[1] * a)
        p_out = QPointF(ox + px + dout[0] * a, oy + py + dout[1] * a)
        if first:
            path.moveTo(p_in)
            first = False
        else:
            path.lineTo(p_in)
        if a > 0:
            if chamfer:
                path.lineTo(p_out)
            else:
                cx, cy = ox + px + (dout[0] - din[0]) * a, oy + py + (dout[1] - din[1]) * a
                path.arcTo(QRectF(cx - a, cy - a, 2 * a, 2 * a), start, -90.0)
    path.closeSubpath()
    return path


def _pad_path(pad: Pad) -> QPainterPath:
    """Форма площадки в её локальной системе (центр отверстия — начало, без поворота)."""
    d = pad.drill
    ox, oy = (0.0, 0.0) if d is None else d.offset
    sx, sy = (max(0.0, float(v)) for v in pad.size)
    shape = pad.shape
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    if shape == "circle":
        path.addEllipse(QPointF(ox, oy), sx / 2.0, sx / 2.0)
    elif shape == "oval":
        r = min(sx, sy) / 2.0
        path.addRoundedRect(QRectF(ox - sx / 2.0, oy - sy / 2.0, sx, sy), r, r)
    elif shape in ("rect", "roundrect"):
        chamfer = list(pad.chamfer)
        ratio = pad.roundrect_rratio
        if shape == "roundrect":
            ratio = 0.25 if ratio is None else ratio
        else:
            ratio = ratio if (chamfer and ratio is not None) else 0.0
        r = min(sx, sy) * max(0.0, min(ratio, 0.5))
        c = 0.0
        if chamfer:
            cr = pad.chamfer_ratio
            c = min(sx, sy) * max(0.0, min(0.2 if cr is None else cr, 0.5))
        path.addPath(_rect_path(ox, oy, sx, sy, r, c, chamfer))
    elif shape == "trapezoid":
        dx, dy = pad.rect_delta or (0.0, 0.0)
        hx, hy, tx, ty = sx / 2.0, sy / 2.0, dx / 2.0, dy / 2.0
        corners = [(-hx - ty, hy + tx), (hx + ty, hy - tx), (hx - ty, -hy + tx),
                   (-hx + ty, -hy - tx)]
        path.moveTo(ox + corners[0][0], oy + corners[0][1])
        for x, y in corners[1:]:
            path.lineTo(ox + x, oy + y)
        path.closeSubpath()
    elif shape == "custom":
        if pad.anchor == "circle":
            path.addEllipse(QPointF(ox, oy), sx / 2.0, sx / 2.0)
        else:
            path.addRect(QRectF(ox - sx / 2.0, oy - sy / 2.0, sx, sy))
        shift = QTransform.fromTranslate(ox, oy)
        for g in pad.primitive_views:
            if g.node.name in ("gr_bbox", "gr_vector"):
                continue
            try:
                p, closed = _graphic_path(g)
                width = max(0.0, g.width or 0.0)
                if closed and _safe_fill(g):
                    path.addPath(shift.map(p))
                    if width > 0:
                        path.addPath(shift.map(_stroke_outline(p, width)))
                else:
                    path.addPath(shift.map(_stroke_outline(p, width)))
            except Exception:  # noqa: BLE001 — примитив необычной формы пропускается
                continue
    else:
        path.addRect(QRectF(ox - sx / 2.0, oy - sy / 2.0, sx, sy))
    return path


def _hole_path(dw: float, dh: float) -> QPainterPath:
    """Отверстие (круглое или овальное) с центром в начале координат."""
    path = QPainterPath()
    dh = dh or dw
    if abs(dw - dh) < 1e-9:
        path.addEllipse(QPointF(0.0, 0.0), dw / 2.0, dw / 2.0)
    else:
        r = min(dw, dh) / 2.0
        path.addRoundedRect(QRectF(-dw / 2.0, -dh / 2.0, dw, dh), r, r)
    return path


def _text_font(bold: bool = False, italic: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(_FONT_FAMILIES)
    font.setPixelSize(_TEXT_PX)
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    return font


def _text_path(text: str, height: float, width: float, justify: Iterable[str] = (),
               bold: bool = False, italic: bool = False) -> QPainterPath:
    """Контур текста в системе точки привязки: высота прописных ``height``, ширина
    символов пропорциональна ``width``; ``justify`` — ``left``/``right``/``top``/``bottom``
    (по умолчанию — по центру)."""
    font = _text_font(bold, italic)
    fm = QFontMetricsF(font)
    cap = fm.capHeight()
    if cap <= 0:
        cap = fm.ascent() * 0.7 or float(_TEXT_PX) * 0.7
    h = height if height > 0 else 1.0
    w = width if width > 0 else h
    sy = h / cap
    sx = sy * (w / h)
    just = set(justify)
    lines = text.split("\n")
    pitch = h * _LINE_PITCH
    block = h + pitch * (len(lines) - 1)
    if "top" in just:
        top = 0.0
    elif "bottom" in just:
        top = -block
    else:
        top = -block / 2.0
    out = QPainterPath()
    out.setFillRule(Qt.FillRule.WindingFill)
    for i, line in enumerate(lines):
        if not line:
            continue
        adv = fm.horizontalAdvance(line) * sx
        if "left" in just:
            x0 = 0.0
        elif "right" in just:
            x0 = -adv
        else:
            x0 = -adv / 2.0
        base = top + i * pitch + h
        glyphs = QPainterPath()
        glyphs.addText(0.0, 0.0, font, line)
        out.addPath(QTransform(sx, 0.0, 0.0, sy, x0, base).map(glyphs))
    return out


def _node_xy_list(pts: Node | None) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    if pts is None:
        return out
    for c in pts.nodes("xy"):
        a = c.atoms()
        if len(a) >= 2:
            try:
                out.append((float(a[0]), float(a[1])))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------------------------
# Элементы сцены
# ---------------------------------------------------------------------------------------------

class _ShapeItem(QGraphicsPathItem):
    """Элемент сцены с контуром ``path``; форма попадания (``shape``): ``"fill"`` — сам
    контур (залитые фигуры, площадки), ``"stroke"`` — только линия (незалитые фигуры: щелчок
    внутри контура их не выбирает), ``"bbox"`` — описанный прямоугольник (тексты)."""

    def __init__(self, path: QPainterPath, pen: QPen, brush: QBrush, pick: str = "fill",
                 stroke_width: float = 0.0) -> None:
        super().__init__(path)
        self.setPen(pen)
        self.setBrush(brush)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._pick = pick
        self._stroke_width = stroke_width
        self._shape_cache: QPainterPath | None = None

    def shape(self) -> QPainterPath:  # noqa: D401 — переопределение Qt
        if self._shape_cache is None:
            if self._pick == "stroke":
                self._shape_cache = _stroke_outline(self.path(), self._stroke_width)
            elif self._pick == "bbox":
                p = QPainterPath()
                p.addRect(self.path().boundingRect())
                self._shape_cache = p
            else:
                self._shape_cache = super().shape()
        return self._shape_cache


@dataclass
class _Drag:
    """Состояние перетаскивания элемента левой кнопкой."""

    element: Any
    press_scene: QPointF
    press_view: QPointF
    anchor: tuple[float, float]
    items: list[tuple[QGraphicsItem, QPointF]] = field(default_factory=list)
    started: bool = False
    delta: tuple[float, float] = (0.0, 0.0)


# ---------------------------------------------------------------------------------------------
# Канва
# ---------------------------------------------------------------------------------------------

class PreviewCanvas(QGraphicsView):
    """Канва корпуса документа :class:`~kicadfp.gui.document.FootprintDocument`.

    Свойства вида: :attr:`zoom` (пикселей на мм), :attr:`grid` (шаг сетки, мм),
    :attr:`grid_visible`, :attr:`snap` (привязка к сетке при перетаскивании),
    :attr:`show_hidden` (рисовать скрытые тексты), видимость слоёв
    (:meth:`set_layer_visible`, :meth:`is_layer_visible`, :attr:`hidden_layers`; кроме
    слоёв KiCad — псевдослои :data:`HOLES_LAYER` и :data:`PAD_NUMBERS_LAYER`).

    Доступ к сцене (для тестов и других виджетов): :meth:`elements` — нарисованные
    элементы модели, :meth:`items_for` — элементы сцены элемента модели,
    :meth:`element_at` — элемент модели под точкой сцены, :meth:`highlight_item` —
    подсветка выделения, :meth:`scene_layers` — слои, на которых что-то нарисовано.

    Сигналы: ``cursor_moved(float, float)`` — координаты курсора в мм;
    ``zoom_changed(float)``; ``grid_changed(float)``; ``layers_changed()`` — изменилась
    видимость слоёв; ``rebuilt()`` — сцена перестроена.
    """

    cursor_moved = Signal(float, float)
    zoom_changed = Signal(float)
    grid_changed = Signal(float)
    layers_changed = Signal()
    rebuilt = Signal()

    def __init__(self, document: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = document
        self._grid = 1.0
        self._grid_visible = True
        self._snap = True
        self._show_hidden = False
        self._hidden: set[str] = set()
        self._items: dict[int, list[QGraphicsItem]] = {}
        self._elements: dict[int, Any] = {}
        self._highlight: QGraphicsPathItem | None = None
        self._drag: _Drag | None = None
        self._pan_last: QPointF | None = None
        self._pan_button = Qt.MouseButton.NoButton
        self._space_down = False
        self._fit_pending = True
        self._auto_fit = False

        scene = QGraphicsScene(self)
        e = _SCENE_EXTENT
        scene.setSceneRect(-e, -e, 2 * e, 2 * e)
        self.setScene(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setBackgroundBrush(QBrush(_qcolor("background", 1.0)))
        self.setTransform(QTransform.fromScale(10.0, 10.0))
        self.centerOn(0.0, 0.0)

        document.changed.connect(self._on_changed)
        document.selection_changed.connect(self._on_selection_changed)
        document.document_changed.connect(self._on_document_changed)
        self.rebuild()

    # --- свойства -------------------------------------------------------------------------------
    @property
    def document(self) -> Any:
        """Документ, корпус которого показывает канва."""
        return self._doc

    @property
    def zoom(self) -> float:
        """Масштаб, пикселей на миллиметр."""
        return float(self.transform().m11())

    @zoom.setter
    def zoom(self, value: float) -> None:
        self.set_zoom(value)

    @property
    def grid(self) -> float:
        """Шаг сетки, мм (положительное число; для меню — :data:`GRID_STEPS`)."""
        return self._grid

    @grid.setter
    def grid(self, value: float) -> None:
        v = float(value)
        if not v > 0 or math.isinf(v):
            raise ValueError(f"шаг сетки должен быть положительным: {value!r}")
        if v != self._grid:
            self._grid = v
            self.viewport().update()
            self.grid_changed.emit(v)

    @property
    def grid_visible(self) -> bool:
        """Показывать ли сетку (оси через начало координат рисуются вместе с ней)."""
        return self._grid_visible

    @grid_visible.setter
    def grid_visible(self, value: bool) -> None:
        self._grid_visible = bool(value)
        self.viewport().update()

    @property
    def snap(self) -> bool:
        """Привязка к сетке при перетаскивании."""
        return self._snap

    @snap.setter
    def snap(self, value: bool) -> None:
        self._snap = bool(value)

    @property
    def show_hidden(self) -> bool:
        """Рисовать ли скрытые тексты (``hide``)."""
        return self._show_hidden

    @show_hidden.setter
    def show_hidden(self, value: bool) -> None:
        v = bool(value)
        if v != self._show_hidden:
            self._show_hidden = v
            self.rebuild()

    @property
    def hidden_layers(self) -> frozenset[str]:
        """Скрытые слои (канонические имена и псевдослои)."""
        return frozenset(self._hidden)

    @property
    def is_dragging(self) -> bool:
        """Идёт ли перетаскивание элемента."""
        return self._drag is not None and self._drag.started

    # --- видимость слоёв ------------------------------------------------------------------------
    def _layer_names(self, layer: str) -> list[str]:
        if layer in _PSEUDO_LAYERS:
            return [layer]
        if not isinstance(layer, str) or not _L.is_valid_layer(layer):
            raise ValueError(f"неизвестный слой: {layer!r}")
        return _expand([layer])

    def is_layer_visible(self, layer: str) -> bool:
        """Виден ли слой (для группового обозначения — виден ли хотя бы один его слой)."""
        names = self._layer_names(layer)
        return any(n not in self._hidden for n in names)

    def set_layer_visible(self, layer: str, visible: bool = True) -> None:
        """Показать или скрыть слой (имя KiCad, групповое обозначение ``*.Cu`` … или
        псевдослой :data:`HOLES_LAYER`/:data:`PAD_NUMBERS_LAYER`); сцена перестраивается.
        Видимость слоёв сохраняется при изменениях модели и открытии других корпусов.
        ``ValueError`` — неизвестное имя слоя."""
        names = self._layer_names(layer)
        before = set(self._hidden)
        if visible:
            self._hidden.difference_update(names)
        else:
            self._hidden.update(names)
        if self._hidden != before:
            self.rebuild()
            self.layers_changed.emit()

    def set_hidden_layers(self, layers: Iterable[str]) -> None:
        """Задать набор скрытых слоёв целиком (остальные — видимы)."""
        new: set[str] = set()
        for name in layers:
            new.update(self._layer_names(name))
        if new != self._hidden:
            self._hidden = new
            self.rebuild()
            self.layers_changed.emit()

    def show_all_layers(self) -> None:
        """Сделать видимыми все слои."""
        self.set_hidden_layers(())

    def _visible(self, layer: str) -> bool:
        return layer not in self._hidden

    # --- доступ к сцене -------------------------------------------------------------------------
    def elements(self) -> list[Any]:
        """Элементы модели, нарисованные на сцене (в порядке построения: графика,
        площадки, тексты, зоны)."""
        return list(self._elements.values())

    def items_for(self, element: Any) -> list[QGraphicsItem]:
        """Элементы сцены элемента модели (представления или узла); пусто — не нарисован."""
        node = element.node if isinstance(element, View) else element
        return list(self._items.get(id(node), ()))

    def scene_layers(self) -> list[str]:
        """Слои (и псевдослои), на которых нарисованы элементы, в порядке отрисовки."""
        found = {it.data(LAYER_ROLE) for its in self._items.values() for it in its}
        found.discard(None)
        return sorted(found, key=lambda n: (_RANK.get(n, -1), n))

    def highlight_item(self) -> QGraphicsPathItem | None:
        """Элемент сцены подсветки выделения (``None`` — ничего не выделено или выделенный
        элемент не нарисован)."""
        return self._highlight

    def map_to_scene(self, pos: QPointF) -> QPointF:
        """Точка окна просмотра (пиксели, дробные) -> точка сцены (мм)."""
        inv, _ok = self.viewportTransform().inverted()
        return inv.map(QPointF(pos))

    def map_from_scene(self, pos: QPointF) -> QPointF:
        """Точка сцены (мм) -> точка окна просмотра (пиксели, дробные)."""
        return self.viewportTransform().map(QPointF(pos))

    def element_at(self, pos: QPointF) -> Any:
        """Элемент модели под точкой сцены ``pos`` (верхний по порядку отрисовки) или
        ``None``. Сначала — точное попадание, затем — с допуском в несколько пикселей."""
        scene = self.scene()
        order = Qt.SortOrder.DescendingOrder
        mode = Qt.ItemSelectionMode.IntersectsItemShape
        candidates = scene.items(QPointF(pos), mode, order)
        tol = _PICK_PX / max(self.zoom, 1e-9)
        rect = QRectF(pos.x() - tol, pos.y() - tol, 2 * tol, 2 * tol)
        for group in (candidates, None):
            items = group if group is not None else scene.items(rect, mode, order)
            for it in items:
                if it is self._highlight or not it.isVisible():
                    continue
                el = it.data(ELEMENT_ROLE)
                if el is not None:
                    return el
        return None

    # --- построение сцены -----------------------------------------------------------------------
    def rebuild(self) -> None:
        """Перестроить сцену по модели документа (выделение, масштаб и положение вида
        сохраняются; идущее перетаскивание отменяется)."""
        self._drag = None
        scene = self.scene()
        self._highlight = None
        scene.clear()
        self._items = {}
        self._elements = {}
        fp = self._doc.fp
        if fp is not None:
            self._build(fp)
        self._update_highlight()
        if self._fit_pending and fp is not None:
            self._try_fit()
        self.viewport().update()
        self.rebuilt.emit()

    def _register(self, element: Any, item: QGraphicsItem, layer: str) -> None:
        node = element.node if isinstance(element, View) else element
        item.setData(ELEMENT_ROLE, element)
        item.setData(LAYER_ROLE, layer)
        self.scene().addItem(item)
        key = id(node)
        self._items.setdefault(key, []).append(item)
        self._elements.setdefault(key, element)

    def _build(self, fp: Footprint) -> None:
        for g in fp.graphics:
            self._safe(self._add_graphic, g)
        for pad in fp.pads:
            self._safe(self._add_pad, pad)
        for t in fp.texts:
            self._safe(self._add_text, t, fp)
        for z in fp.zones:
            self._safe(self._add_zone, z)

    @staticmethod
    def _safe(func: Any, *args: Any) -> None:
        """Элемент необычной (повреждённой) формы не мешает отрисовке остальных."""
        try:
            func(*args)
        except Exception:  # noqa: BLE001
            pass

    # графика
    def _graphic_pen(self, color: QColor, width: float, stroke_type: str | None) -> QPen:
        pen = QPen(color)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if width > 0:
            pen.setWidthF(width)
        else:
            pen.setWidth(0)
            pen.setCosmetic(True)
        pattern = _DASH_PATTERNS.get(stroke_type or "")
        if pattern:
            pen.setDashPattern(pattern)
        return pen

    def _add_graphic(self, g: Graphic) -> None:
        path, closed = _graphic_path(g)
        if path.isEmpty():
            return
        width = max(0.0, g.width or 0.0)
        filled = closed and _safe_fill(g)
        try:
            stroke_type = g.stroke_type
        except Exception:  # noqa: BLE001
            stroke_type = None
        for layer in _draw_layers(g.layers):
            if not self._visible(layer):
                continue
            color = _qcolor(layer)
            if filled and width <= 0:
                pen = QPen(Qt.PenStyle.NoPen)
            else:
                pen = self._graphic_pen(color, width, stroke_type)
            brush = QBrush(color) if filled else QBrush(Qt.BrushStyle.NoBrush)
            item = _ShapeItem(path, pen, brush, "fill" if filled else "stroke", width)
            item.setZValue(_z(layer, 0))
            self._register(g, item, layer)

    # площадки
    def _pad_item(self, pad: Pad, path: QPainterPath, pen: QPen, brush: QBrush,
                  pick: str = "fill") -> _ShapeItem:
        item = _ShapeItem(path, pen, brush, pick)
        x, y = pad.position
        item.setPos(x, y)
        a = pad.angle
        if a:
            item.setRotation(-a)
        return item

    def _add_pad(self, pad: Pad) -> None:
        ptype = pad.type
        names = [n for n in _draw_layers(pad.layers) if self._visible(n)]
        copper = [n for n in names if _is_copper(n)]
        other = [n for n in names if not _is_copper(n)]
        if not names:
            return
        path = _pad_path(pad)
        no_pen = QPen(Qt.PenStyle.NoPen)
        d = pad.drill
        dw, dh = d.size if d is not None else (0.0, 0.0)
        if ptype == "np_thru_hole":
            # только отверстие и контур площадки
            outline = QPen(_qcolor("npth", 1.0))
            outline.setWidth(0)
            outline.setCosmetic(True)
            layer = max(copper, key=lambda n: _RANK.get(n, -1)) if copper else HOLES_LAYER
            item = self._pad_item(pad, path, outline, QBrush(Qt.BrushStyle.NoBrush), "stroke")
            item.setZValue(_z(HOLES_LAYER, 1) if layer == HOLES_LAYER else _z(layer, 1))
            self._register(pad, item, layer)
            if (dw > 0 or dh > 0) and self._visible(HOLES_LAYER):
                hole = self._pad_item(pad, _hole_path(dw, dh), no_pen,
                                      QBrush(_qcolor("npth", 1.0)))
                hole.setZValue(_z(HOLES_LAYER, 2))
                self._register(pad, hole, HOLES_LAYER)
            return
        for layer in other:
            item = self._pad_item(pad, path, no_pen, QBrush(_qcolor(layer)))
            item.setZValue(_z(layer, 1))
            self._register(pad, item, layer)
        if copper:
            if ptype == "thru_hole":
                top = max(copper, key=lambda n: _RANK.get(n, -1))
                item = self._pad_item(pad, path, no_pen,
                                      QBrush(_qcolor("pad_th", COPPER_ALPHA)))
                item.setZValue(_z(top, 1))
                self._register(pad, item, top)
            else:
                for layer in copper:
                    item = self._pad_item(pad, path, no_pen, QBrush(_qcolor(layer)))
                    item.setZValue(_z(layer, 1))
                    self._register(pad, item, layer)
        if ptype == "thru_hole" and (dw > 0 or dh > 0) and self._visible(HOLES_LAYER):
            pen = QPen(_qcolor("hole", 1.0))
            pen.setWidthF(min(dw, dh or dw) * 0.08)
            hole = self._pad_item(pad, _hole_path(dw, dh), pen,
                                  QBrush(_qcolor("background", 1.0)))
            hole.setZValue(_z(HOLES_LAYER, 1))
            self._register(pad, hole, HOLES_LAYER)
        number = pad.number
        if number and self._visible(PAD_NUMBERS_LAYER):
            m = min(pad.size_x, pad.size_y)
            if m > 0:
                size = max(0.05, min(m * 0.4, 1.2 * m / max(len(number), 1)))
                tpath = _text_path(number, size, size)
                item = _ShapeItem(tpath, no_pen, QBrush(_qcolor("pad_net_names")), "bbox")
                x, y = pad.position
                item.setPos(x, y)
                item.setZValue(_z(PAD_NUMBERS_LAYER, 0))
                self._register(pad, item, PAD_NUMBERS_LAYER)

    # тексты
    def _add_text(self, t: Text, fp: Footprint) -> None:
        layer = t.layer
        if not layer or not self._visible(layer):
            return
        if t.hide and not self._show_hidden:
            return
        if t.node.find("at") is None:
            return
        content = _substitute(t.text, fp)
        path = _text_path(content, t.font_size_y, t.font_size_x, t.justify, t.bold, t.italic)
        item = _ShapeItem(path, QPen(Qt.PenStyle.NoPen), QBrush(_qcolor(layer)), "bbox")
        x, y = t.position
        item.setPos(x, y)
        angle = _readable_angle(t.angle, bool(t.unlocked))
        rot = QTransform()
        rot.rotate(-angle)
        mirror = QTransform.fromScale(-1.0 if t.mirror else 1.0, 1.0)
        item.setTransform(mirror * rot)
        item.setZValue(_z(layer, 2))
        self._register(t, item, layer)

    # зоны
    def _add_zone(self, zone: Node) -> None:
        names: list[str] = []
        ls = zone.find("layers")
        if ls is not None:
            names = [str(a) for a in ls.atoms()]
        else:
            v = zone.value("layer")
            if v is not None:
                names = [str(v)]
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for poly in zone.nodes("polygon"):
            pts = _node_xy_list(poly.find("pts"))
            if len(pts) >= 2:
                path.moveTo(_pt(pts[0]))
                for p in pts[1:]:
                    path.lineTo(_pt(p))
                path.closeSubpath()
        if path.isEmpty():
            return
        for layer in _draw_layers(names):
            if not self._visible(layer):
                continue
            pen = QPen(_qcolor(layer, 1.0))
            pen.setWidth(0)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            item = _ShapeItem(path, pen, QBrush(_qcolor(layer, 0.2)), "stroke")
            item.setZValue(_z(layer, 0))
            self._register(zone, item, layer)

    # --- выделение ------------------------------------------------------------------------------
    def _update_highlight(self) -> None:
        if self._highlight is not None:
            self.scene().removeItem(self._highlight)
            self._highlight = None
        sel = self._doc.selected
        if sel is None or isinstance(sel, Footprint):
            return
        items = self.items_for(sel)
        if not items:
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for it in items:
            path.addPath(it.sceneTransform().map(it.shape()))
        color = _qcolor("selection", 1.0)
        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCosmetic(True)
        fill = QColor(color)
        fill.setAlphaF(0.3)
        h = QGraphicsPathItem(path)
        h.setPen(pen)
        h.setBrush(QBrush(fill))
        h.setZValue(_HIGHLIGHT_Z)
        h.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.scene().addItem(h)
        self._highlight = h
        if self._drag is not None and self._drag.started:
            dx, dy = self._drag.delta
            h.setPos(dx, dy)

    # --- сигналы документа ----------------------------------------------------------------------
    def _on_changed(self) -> None:
        self.rebuild()

    def _on_selection_changed(self, _item: Any) -> None:
        self._update_highlight()
        self.viewport().update()

    def _on_document_changed(self) -> None:
        self._drag = None
        self._fit_pending = True

    # --- масштаб и вид --------------------------------------------------------------------------
    def set_zoom(self, value: float, anchor: QPointF | None = None) -> None:
        """Установить масштаб (пикселей на мм, в пределах :data:`ZOOM_MIN`…:data:`ZOOM_MAX`),
        сохранив на месте точку окна просмотра ``anchor`` (по умолчанию — центр)."""
        v = float(value)
        if not v > 0 or math.isinf(v):
            raise ValueError(f"масштаб должен быть положительным: {value!r}")
        v = max(ZOOM_MIN, min(ZOOM_MAX, v))
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        anchor = QPointF(anchor)
        target = self.map_to_scene(anchor)
        old = self.zoom
        self.setTransform(QTransform.fromScale(v, v))
        now = self.map_from_scene(target)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setValue(hb.value() + round(now.x() - anchor.x()))
        vb.setValue(vb.value() + round(now.y() - anchor.y()))
        self._fit_pending = False
        self._auto_fit = False
        if abs(v - old) > 1e-12:
            self.zoom_changed.emit(v)

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        """Изменить масштаб в ``factor`` раз относительно точки ``anchor`` окна просмотра."""
        self.set_zoom(self.zoom * float(factor), anchor)

    def zoom_in(self) -> None:
        """Увеличить (относительно центра)."""
        self.zoom_by(ZOOM_STEP)

    def zoom_out(self) -> None:
        """Уменьшить (относительно центра)."""
        self.zoom_by(1.0 / ZOOM_STEP)

    def content_rect(self) -> QRectF:
        """Габариты нарисованного (мм); у пустого корпуса — квадрат вокруг начала координат."""
        rect = QRectF()
        for items in self._items.values():
            for it in items:
                rect = rect.united(it.sceneBoundingRect())
        if rect.isNull() or rect.isEmpty():
            fp = self._doc.fp
            b = None
            if fp is not None:
                try:
                    b = fp.bbox()
                except Exception:  # noqa: BLE001
                    b = None
            if b is not None and (b.width > 0 or b.height > 0):
                rect = QRectF(b.x1, b.y1, b.width, b.height)
            else:
                rect = QRectF(-5.0, -5.0, 10.0, 10.0)
        return rect

    def fit(self) -> None:
        """«Вписать»: масштаб и положение, при которых весь корпус виден целиком."""
        vw, vh = self.viewport().width(), self.viewport().height()
        if vw < 4 or vh < 4:
            self._fit_pending = True
            return
        rect = self.content_rect()
        m = max(rect.width(), rect.height()) * _FIT_MARGIN + _FIT_MARGIN_MM
        rect = rect.adjusted(-m, -m, m, m)
        k = min(vw / max(rect.width(), 1e-6), vh / max(rect.height(), 1e-6))
        k = max(ZOOM_MIN, min(ZOOM_MAX, k))
        old = self.zoom
        self.setTransform(QTransform.fromScale(k, k))
        self.centerOn(rect.center())
        self._fit_pending = False
        self._auto_fit = False
        if abs(k - old) > 1e-12:
            self.zoom_changed.emit(k)

    def _try_fit(self) -> None:
        """Отложенное «вписать» (новый корпус): до первого действия пользователя с видом
        повторяется при изменении размера окна."""
        if self.viewport().width() >= 4 and self.viewport().height() >= 4 and self.isVisible():
            self.fit()
            self._auto_fit = True

    def center_on(self, x: float, y: float) -> None:
        """Поместить точку сцены ``(x, y)`` мм в центр окна просмотра."""
        self.centerOn(QPointF(x, y))

    def view_center(self) -> QPointF:
        """Точка сцены (мм) в центре окна просмотра."""
        return self.map_to_scene(QPointF(self.viewport().rect().center()))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — переопределение Qt
        super().showEvent(event)
        if self._fit_pending and self._doc.fp is not None:
            self._try_fit()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — переопределение Qt
        super().resizeEvent(event)
        if (self._fit_pending or self._auto_fit) and self._doc.fp is not None:
            self._try_fit()

    # --- фон и сетка ----------------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.fillRect(rect, _qcolor("background", 1.0))
            if not self._grid_visible:
                return
            k = max(self.zoom, 1e-9)
            step = self._grid
            while step * k < _MIN_GRID_PX:
                step *= 2.0
            color = _qcolor("grid", 0.35)
            pen = QPen(color)
            pen.setWidth(0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            lines: list[QLineF] = []
            x = math.ceil(rect.left() / step) * step
            while x <= rect.right():
                lines.append(QLineF(x, rect.top(), x, rect.bottom()))
                x += step
            y = math.ceil(rect.top() / step) * step
            while y <= rect.bottom():
                lines.append(QLineF(rect.left(), y, rect.right(), y))
                y += step
            if lines:
                painter.drawLines(lines)
            axes = QPen(_qcolor("grid_axes", 0.7))
            axes.setWidth(0)
            axes.setCosmetic(True)
            painter.setPen(axes)
            if rect.left() <= 0.0 <= rect.right():
                painter.drawLine(QLineF(0.0, rect.top(), 0.0, rect.bottom()))
            if rect.top() <= 0.0 <= rect.bottom():
                painter.drawLine(QLineF(rect.left(), 0.0, rect.right(), 0.0))
        finally:
            painter.restore()

    # --- перетаскивание -------------------------------------------------------------------------
    @staticmethod
    def _anchor_of(element: Any) -> tuple[float, float] | None:
        """Опорная точка перетаскиваемого элемента (``None`` — элемент не перетаскивается)."""
        if isinstance(element, (Pad, Text)):
            x, y = element.position
            return (float(x), float(y))
        if isinstance(element, Graphic):
            pts = list(element.points)
            if not pts:
                return None
            return (float(pts[0][0]), float(pts[0][1]))
        return None

    def _drag_delta(self, scene_pos: QPointF) -> tuple[float, float]:
        d = self._drag
        assert d is not None
        rx = scene_pos.x() - d.press_scene.x()
        ry = scene_pos.y() - d.press_scene.y()
        ax, ay = d.anchor
        if self._snap and self._grid > 0:
            nx = _geo.snap(ax + rx, self._grid)
            ny = _geo.snap(ay + ry, self._grid)
            return (_geo.round_mm(nx - ax), _geo.round_mm(ny - ay))
        return (_geo.round_mm(rx, 4), _geo.round_mm(ry, 4))

    def _apply_drag_offset(self, dx: float, dy: float) -> None:
        d = self._drag
        if d is None:
            return
        d.delta = (dx, dy)
        for it, orig in d.items:
            it.setPos(orig.x() + dx, orig.y() + dy)
        if self._highlight is not None:
            self._highlight.setPos(dx, dy)

    def cancel_drag(self) -> None:
        """Отменить идущее перетаскивание (элементы возвращаются на место)."""
        if self._drag is None:
            return
        self._apply_drag_offset(0.0, 0.0)
        self._drag = None

    def _commit_drag(self, drag: _Drag) -> bool:
        """Применить результат перетаскивания одной командой."""
        dx, dy = drag.delta
        el = drag.element
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return False
        text = f"перемещение {describe_item(el)}"
        if isinstance(el, (Pad, Text)):
            x0, y0 = drag.anchor
            cmd: Any = SetAttrsCommand(self._doc, el, {"x": _geo.round_mm(x0 + dx),
                                                       "y": _geo.round_mm(y0 + dy)}, text)
        else:
            moved = el.copy()
            moved.move(dx, dy)
            cmd = ReplaceNodeCommand(self._doc, el.node.copy(), moved.node, text, target=el)
        return bool(self._doc.apply(cmd))

    # --- мышь -----------------------------------------------------------------------------------
    def _start_pan(self, pos: QPointF, button: Qt.MouseButton) -> None:
        self._pan_last = QPointF(pos)
        self._pan_button = button
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def _pan_to(self, pos: QPointF) -> None:
        assert self._pan_last is not None
        self._auto_fit = False
        delta = pos - self._pan_last
        self._pan_last = QPointF(pos)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setValue(hb.value() - round(delta.x()))
        vb.setValue(vb.value() - round(delta.y()))

    def _end_pan(self) -> None:
        self._pan_last = None
        self._pan_button = Qt.MouseButton.NoButton
        if self._space_down:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — переопределение Qt
        pos = event.position()
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (
                button == Qt.MouseButton.LeftButton and self._space_down):
            self.cancel_drag()
            self._start_pan(pos, button)
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            self.cancel_drag()
            sp = self.map_to_scene(pos)
            el = self.element_at(sp)
            if self._doc.fp is not None:
                try:
                    self._doc.select(el)
                except (ValueError, RuntimeError):
                    el = None
            sel = self._doc.selected if el is not None else None
            anchor = self._anchor_of(sel) if sel is not None else None
            if anchor is not None:
                items = self.items_for(sel)
                self._drag = _Drag(sel, sp, QPointF(pos), anchor,
                                   [(it, it.pos()) for it in items])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — переопределение Qt
        pos = event.position()
        sp = self.map_to_scene(pos)
        self.cursor_moved.emit(_geo.round_mm(sp.x(), 4), _geo.round_mm(sp.y(), 4))
        if self._pan_last is not None:
            self._pan_to(pos)
            event.accept()
            return
        d = self._drag
        if d is not None:
            if not d.started:
                moved = pos - d.press_view
                if moved.manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                d.started = True
            self._apply_drag_offset(*self._drag_delta(sp))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — переопределение Qt
        button = event.button()
        if self._pan_last is not None and button == self._pan_button:
            self._end_pan()
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton and self._drag is not None:
            d = self._drag
            if d.started:
                self._apply_drag_offset(*self._drag_delta(self.map_to_scene(event.position())))
            delta = d.delta
            self._apply_drag_offset(0.0, 0.0)  # временное положение снимается
            self._drag = None
            if d.started:
                d.delta = delta
                self._commit_drag(d)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 — переопределение Qt
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            event.ignore()
            return
        self.zoom_by(ZOOM_STEP ** (delta / 120.0), event.position())
        event.accept()

    # --- клавиатура -----------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — переопределение Qt
        key = event.key()
        if key == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space_down = True
                if self._pan_last is None:
                    self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if key == Qt.Key.Key_Escape and self._drag is not None:
            self.cancel_drag()
            event.accept()
            return
        if key == Qt.Key.Key_Home:
            self.fit()
            event.accept()
            return
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            event.accept()
            return
        if key == Qt.Key.Key_Minus:
            self.zoom_out()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — переопределение Qt
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space_down = False
                if self._pan_last is not None and self._pan_button == Qt.MouseButton.LeftButton:
                    self._end_pan()
                elif self._pan_last is None:
                    self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)
