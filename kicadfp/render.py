"""Изображение посадочного места: SVG (только стандартная библиотека) и PNG (через PySide6).

Основная функция — :func:`render_svg`: строит SVG-документ по :class:`~kicadfp.model.Footprint`
(архитектура, §12). Координаты внутри документа — миллиметры KiCad (ось Y вниз, как в SVG),
масштаб задаётся атрибутами ``width``/``height`` корневого ``<svg>`` (``scale`` пикселей на
миллиметр) и ``viewBox`` (габариты нарисованного плюс поле ``margin``).

Состав изображения (снизу вверх):

* фон (``layers.COLORS["background"]``), если ``background=True``;
* сетка с шагом ``grid`` мм (цвет ``grid``) и оси через начало координат (``grid_axes``),
  если ``grid`` не ``None``; при слишком мелком шаге (меньше 4 пикселей или больше 400
  линий) шаг удваивается — решение kicadfp, чтобы документ не разрастался;
* слои в порядке :data:`kicadfp.layers.DRAW_ORDER` (неизвестные имена слоёв — самыми
  нижними), каждый — группа ``<g class="layer" data-layer="ИМЯ">`` цвета слоя
  (:func:`kicadfp.layers.color`; прозрачность :data:`~kicadfp.layers.COLOR_ALPHA` — атрибутом
  ``opacity`` группы). Внутри слоя — графика, затем площадки, затем тексты (в порядке файла);
* группа отверстий ``data-layer="holes"`` — сразу над ``F.Cu`` (над всей медью);
* номера площадок (``pad_numbers=True``) — группа ``data-layer="pad_numbers"`` наверху.

Правила отрисовки:

* **графика** (``fp_line``/``fp_rect``/``fp_circle``/``fp_arc``/``fp_poly``/``fp_curve``) —
  ``<line>``, ``<rect>``, ``<circle>``, ``<path>`` (дуги — командой ``A`` SVG, кривые Безье —
  ``C``, дуги внутри ``pts`` многоугольника — тоже ``A``); ширина линии — ``stroke-width``,
  концы и стыки скруглены (как в KiCad); заливка — по :attr:`Graphic.fill`; линии нулевой
  ширины рисуются волосяной линией в 1 пиксель; типы линий ``dash``/``dot``/``dash_dot``/
  ``dash_dot_dot`` — ``stroke-dasharray`` с отношениями KiCad (штрих 12·w, пробел 3·w,
  точка 0.2·w). Фигура на наборе слоёв ``(layers …)`` рисуется на каждом из них;
* **площадки** — группа ``<g class="pad" data-number=… data-type=…>`` с
  ``transform="translate(x y) rotate(-угол)"`` (положительный угол KiCad — против часовой
  стрелки на экране, в SVG — наоборот); форма смещается на ``(drill (offset …))``. Формы:
  ``circle``, ``rect``, ``oval`` (``rect`` с ``rx`` = половине меньшей стороны),
  ``roundrect`` (``rx`` = ``roundrect_rratio``·меньшая сторона, по умолчанию 0.25),
  прямоугольник с фасками (``chamfer``/``chamfer_ratio``, по умолчанию 0.2; скругление
  остальных углов сохраняется) — ``<path>``, ``trapezoid`` — многоугольник по
  ``rect_delta`` (как ``PAD::BuildEffectiveShapes``), ``custom`` — якорь (``circle``/
  ``rect``) плюс примитивы ``gr_*`` (``gr_bbox``/``gr_vector`` — служебные, не рисуются).
  Медь: ``thru_hole`` и ``np_thru_hole`` (у последней — только если площадка больше
  отверстия) рисуются один раз, на самом верхнем из своих медных слоёв, прошедших фильтр,
  цветом ``pad_th``; ``smd``/``connect`` — на каждом своём медном слое цветом слоя. На
  немедных слоях (маска, паста, …) площадка рисуется цветом слоя без учёта зазоров
  маски/пасты. Отверстие (круглое или овальное) — ``<circle>``/``<rect class="hole">`` в
  группе ``holes``: металлизированное — цветом фона с каймой цвета ``hole``, неметаллизированное —
  цветом ``npth``;
* **тексты** (Reference, Value, пользовательские, поля KiCad 8+) — простой ``<text>`` с
  ``font-size`` = ``font_size_y``, ``text-anchor`` по горизонтальному выравниванию,
  вертикальное выравнивание — сдвигом базовой линии (приближённо: высота прописных
  ≈ 0.7 кегля), поворот — ``rotate(-угол)`` с правилом KiCad «держать читаемым» (если
  текст не ``unlocked``, угол приводится к (-90°, 90°]), зеркальный текст —
  отражение ``scale(-1 1)``; внутри группы текста координаты и кегль увеличены в 100 раз
  с обратным ``scale`` (обход округления кегля в QSvgRenderer); ``bold``/``italic`` — ``font-weight``/``font-style``; многострочный текст —
  по элементу ``<text>`` на строку с шагом 1.62·высоты. Скрытые тексты не рисуются
  (``show_hidden=True`` — рисуются). ``${REFERENCE}``/``%R`` и ``${VALUE}``/``%V``
  подставляются текстами Reference/Value;
* 3D-модели, зоны, ``fp_text_box``, размеры, изображения и прочие элементы без собственного
  представления не рисуются.

``viewBox`` — объединение габаритов всего нарисованного (площадки — :meth:`Pad.bbox`,
графика — с половиной ширины линии, тексты — приближённо) плюс ``margin`` мм с каждой
стороны; если не нарисовано ничего — габариты корпуса :meth:`Footprint.bbox`, у пустого
корпуса — квадрат 2×2 мм вокруг начала координат.

:func:`save_png` рендерит тот же SVG через ``QtSvg.QSvgRenderer`` в ``QImage`` заданной ширины
(масштаб подбирается так, чтобы ширина изображения была ``width`` пикселей). PySide6 —
необязательная зависимость (``pip install kicadfp[png]``); без неё — :class:`RuntimeError`.
"""

from __future__ import annotations

import math
import os
import sys
import xml.etree.ElementTree as ET
from os import PathLike
from pathlib import Path
from typing import Any, Iterable

from . import geometry as _geo
from . import layers as _L
from .geometry import BBox, Point
from .model import Arc, Circle, Curve, Footprint, Graphic, Line, Pad, Poly, Rect, Text

__all__ = ["SVG_NS", "render_svg", "save_svg", "save_png"]

#: Пространство имён SVG.
SVG_NS = "http://www.w3.org/2000/svg"

#: Имя псевдослоя группы отверстий.
HOLES_LAYER = "holes"
#: Имя псевдослоя группы номеров площадок.
PAD_NUMBERS_LAYER = "pad_numbers"

# Отношения длины штриха/пробела/точки к ширине линии (RENDER_SETTINGS KiCad).
_DASH_RATIO = 12.0
_GAP_RATIO = 3.0
_DOT_RATIO = 0.2

# Шаг строк многострочного текста (доля высоты символа) и доля высоты прописных в кегле.
_LINE_PITCH = 1.62
_CAP_HEIGHT = 0.7
# Средняя ширина символа в долях font_size_x (для габаритов текста).
_CHAR_WIDTH = 0.85

_MIN_GRID_PX = 4.0
_MAX_GRID_LINES = 400

_FONT_FAMILY = "DejaVu Sans, Arial, Helvetica, sans-serif"

# Тексты пишутся в системе, увеличенной в _TEXT_K раз (``scale(1/_TEXT_K)`` у группы):
# QSvgRenderer округляет кегль до целых единиц пользователя, и текст высотой меньше
# 0.5 мм иначе пропадает (``QFont::setPixelSize: Pixel size <= 0``).
_TEXT_K = 100.0

# Приложение Qt, созданное save_png (держим ссылку, чтобы его не собрал сборщик мусора).
_QT_APP: Any = None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _f(v: float) -> str:
    """Число для атрибута SVG: до 4 знаков после точки, без хвостовых нулей и ``-0``."""
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        return "0"
    return s


def _pt(p: Point) -> str:
    return f"{_f(p[0])} {_f(p[1])}"


def _sub(parent: ET.Element, tag: str, **attrs: Any) -> ET.Element:
    """Дочерний элемент с атрибутами (``class_`` -> ``class``, ``_`` в имени -> ``-``)."""
    clean: dict[str, str] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        name = "class" if k == "class_" else k.replace("_", "-")
        clean[name] = v if isinstance(v, str) else _f(v)
    return ET.SubElement(parent, tag, clean)


def _arc_command(s: Point, m: Point, e: Point) -> str:
    """Команда пути SVG от ``s`` до ``e`` по дуге через ``m`` (без начального ``M``).

    Положительный ``sweep`` (против часовой стрелки на экране) — ``sweep-flag`` 0 (в SVG
    с осью Y вниз флаг 1 — по часовой стрелке на экране). Вырожденная дуга — отрезок,
    полная окружность — две полуокружности."""
    if _geo.distance(s, e) < 1e-9 and _geo.distance(s, m) > 1e-9:
        # начало совпадает с концом: окружность с диаметром start–mid (как у KiCad)
        r = _f(_geo.distance(s, m) / 2.0)
        return f"A {r} {r} 0 0 0 {_pt(m)} A {r} {r} 0 0 0 {_pt(e)}"
    g = _geo.arc_from_three_points(s, m, e)
    if g is None or g.radius <= 0:
        return f"L {_pt(e)}"
    r = _f(g.radius)
    flag = 0 if g.sweep > 0 else 1
    if abs(g.sweep) >= 360.0 - 1e-6 or _geo.distance(s, e) < 1e-9:
        opp = (2 * g.center[0] - s[0], 2 * g.center[1] - s[1])
        return f"A {r} {r} 0 0 {flag} {_pt(opp)} A {r} {r} 0 0 {flag} {_pt(e)}"
    large = 1 if abs(g.sweep) > 180.0 else 0
    return f"A {r} {r} 0 {large} {flag} {_pt(e)}"


def _poly_path(segments: list[tuple[str, Any]]) -> str:
    """Путь SVG многоугольника по элементам ``("xy", p)`` / ``("arc", (s, m, e))``."""
    parts: list[str] = []
    for kind, v in segments:
        if kind == "xy":
            parts.append(("M " if not parts else "L ") + _pt(v))
        else:
            s, m, e = v
            parts.append(("M " if not parts else "L ") + _pt(s))
            parts.append(_arc_command(s, m, e))
    if parts:
        parts.append("Z")
    return " ".join(parts)


def _poly_segments(g: Graphic) -> list[tuple[str, Any]]:
    """Элементы контура многоугольника (через представление :class:`Poly`, если доступно)."""
    seg = getattr(g, "_segments", None)
    if callable(seg):
        return list(seg())
    return [("xy", p) for p in g.points]


def _substitute(text: str, fp: Footprint) -> str:
    """Подстановка переменных текста так, как их показывает редактор корпусов KiCad."""
    if "${" not in text and "%" not in text:
        return text
    ref = fp.reference
    val = fp.value
    ref_s = ref.text if ref is not None else "REF**"
    val_s = val.text if val is not None else fp.name
    out = text.replace("${REFERENCE}", ref_s).replace("${VALUE}", val_s)
    out = out.replace("${FOOTPRINT_NAME}", fp.name)
    if out.strip() in ("%R", "%V"):
        out = out.replace("%R", ref_s).replace("%V", val_s)
    return out


def _readable_angle(angle: float, unlocked: bool) -> float:
    """Угол отрисовки текста: правило KiCad «держать читаемым» (``keep upright``)."""
    a = _geo.normalize_angle_180(angle)
    if unlocked:
        return a
    if a > 90.0 + 1e-9:
        a -= 180.0
    elif a <= -90.0 + 1e-9:
        a += 180.0
    return a


# ---------------------------------------------------------------------------
# Построитель документа
# ---------------------------------------------------------------------------

class _Renderer:
    """Сборка SVG: группы слоёв, накопление габаритов, завершение (фон, сетка, размеры)."""

    def __init__(self, fp: Footprint, *, layers: Iterable[str] | None, grid: float | None,
                 background: bool, margin: float, show_hidden: bool, pad_numbers: bool) -> None:
        self.fp = fp
        if isinstance(layers, str):
            layers = [layers]
        self.wanted: set[str] | None = None if layers is None else set(_L.expand(layers))
        self.grid = grid
        self.background = background
        self.margin = max(0.0, float(margin))
        self.show_hidden = show_hidden
        self.pad_numbers = pad_numbers
        self.groups: dict[str, ET.Element] = {}
        self.bbox: BBox | None = None
        self.hairlines: list[ET.Element] = []
        self.order = self._layer_order()

    # --- слои --------------------------------------------------------------------------
    def _layer_order(self) -> dict[str, int]:
        order: list[str] = []
        for name in _L.DRAW_ORDER:
            order.append(name)
            if name == "F.Cu":
                order.append(HOLES_LAYER)
        order.append(PAD_NUMBERS_LAYER)
        return {name: i for i, name in enumerate(order)}

    def rank(self, layer: str) -> int:
        """Позиция слоя в порядке отрисовки (неизвестные — ниже всех)."""
        return self.order.get(layer, -1)

    def allowed(self, layer: str | None) -> bool:
        """Проходит ли слой фильтр ``layers``."""
        if not layer:
            return False
        return self.wanted is None or layer in self.wanted

    def group(self, layer: str) -> ET.Element:
        """Группа слоя (создаётся при первом обращении)."""
        g = self.groups.get(layer)
        if g is None:
            attrs = {"class": "layer", "data-layer": layer}
            if layer not in (HOLES_LAYER, PAD_NUMBERS_LAYER):
                alpha = _L.rgba(layer)[3]
                if alpha < 1.0:
                    attrs["opacity"] = _f(alpha)
            g = ET.Element("g", attrs)
            self.groups[layer] = g
        return g

    def grow(self, b: BBox | None) -> None:
        """Расширить габариты нарисованного."""
        if b is not None:
            self.bbox = b.union(self.bbox) if self.bbox is not None else b

    # --- линии -------------------------------------------------------------------------
    def stroke_attrs(self, el: ET.Element, color: str, width: float, stroke_type: str | None,
                     filled: bool) -> None:
        """Атрибуты обводки и заливки фигуры."""
        el.set("fill", color if filled else "none")
        if width > 0:
            el.set("stroke", color)
            el.set("stroke-width", _f(width))
        elif filled:
            el.set("stroke", "none")
            return
        else:
            el.set("stroke", color)
            self.hairlines.append(el)
            width = 0.0
        if stroke_type in ("dash", "dot", "dash_dot", "dash_dot_dot"):
            w = width if width > 0 else 0.1
            dash, gap, dot = _DASH_RATIO * w, _GAP_RATIO * w, _DOT_RATIO * w
            pattern = {"dash": [dash, gap], "dot": [dot, gap],
                       "dash_dot": [dash, gap, dot, gap],
                       "dash_dot_dot": [dash, gap, dot, gap, dot, gap]}[stroke_type]
            el.set("stroke-dasharray", " ".join(_f(x) for x in pattern))

    # --- графика -----------------------------------------------------------------------
    def shape(self, parent: ET.Element, g: Graphic, color: str) -> ET.Element | None:
        """Элемент SVG фигуры ``g`` (координаты — как в узле) или ``None`` (нечего рисовать)."""
        kind = g.kind
        width = g.width or 0.0
        if width < 0:
            width = 0.0
        try:
            filled = bool(g.fill)
        except Exception:  # noqa: BLE001 — повреждённый узел fill не мешает отрисовке
            filled = False
        el: ET.Element | None
        if isinstance(g, Line) or kind == "line":
            (x1, y1), (x2, y2) = g.start, g.end  # type: ignore[attr-defined]
            el = _sub(parent, "line", x1=x1, y1=y1, x2=x2, y2=y2)
            filled = False
        elif isinstance(g, Rect):
            (x1, y1), (x2, y2) = g.start, g.end
            el = _sub(parent, "rect", x=min(x1, x2), y=min(y1, y2), width=abs(x2 - x1),
                      height=abs(y2 - y1))
        elif isinstance(g, Circle):
            (cx, cy), r = g.center, g.radius
            el = _sub(parent, "circle", cx=cx, cy=cy, r=r)
        elif isinstance(g, Arc):
            s, m, e = g.start, g.mid, g.end
            el = _sub(parent, "path", d=f"M {_pt(s)} {_arc_command(s, m, e)}")
            filled = False
        elif isinstance(g, Poly):
            d = _poly_path(_poly_segments(g))
            if not d:
                return None
            el = _sub(parent, "path", d=d)
        elif isinstance(g, Curve):
            pts = list(g.points)
            if len(pts) == 4:
                d = f"M {_pt(pts[0])} C {_pt(pts[1])} {_pt(pts[2])} {_pt(pts[3])}"
            elif pts:
                d = "M " + " L ".join(_pt(p) for p in pts)
            else:
                return None
            el = _sub(parent, "path", d=d)
            filled = False
        else:
            return None
        self.stroke_attrs(el, color, width, g.stroke_type, filled)
        return el

    def draw_graphics(self) -> None:
        """Графика корпуса на своих слоях."""
        for g in self.fp.graphics:
            names = _L.expand(g.layers) if g.layers else []
            for layer in names:
                if not self.allowed(layer):
                    continue
                el = self.shape(self.group(layer), g, _L.color(layer))
                if el is not None:
                    el.set("class", f"graphic {g.kind}")
                    self.grow(g.bbox(with_width=True))

    # --- площадки ----------------------------------------------------------------------
    def _pad_shape(self, parent: ET.Element, pad: Pad, color: str) -> None:
        """Форма площадки в её локальной системе (центр отверстия — начало, без поворота)."""
        d = pad.drill
        ox, oy = (0.0, 0.0) if d is None else d.offset
        sx, sy = (max(0.0, v) for v in pad.size)
        shape = pad.shape
        chamfer = [c for c in pad.chamfer] if shape in ("rect", "roundrect") else []
        if shape == "circle":
            _sub(parent, "circle", cx=ox, cy=oy, r=sx / 2.0, fill=color)
        elif shape == "oval":
            r = min(sx, sy) / 2.0
            _sub(parent, "rect", x=ox - sx / 2.0, y=oy - sy / 2.0, width=sx, height=sy,
                 rx=r, ry=r, fill=color)
        elif shape in ("rect", "roundrect"):
            ratio = pad.roundrect_rratio
            if shape == "roundrect":
                ratio = 0.25 if ratio is None else ratio
            else:
                ratio = ratio if (chamfer and ratio is not None) else 0.0
            r = min(sx, sy) * max(0.0, min(ratio, 0.5))
            if chamfer:
                cr = pad.chamfer_ratio
                c = min(sx, sy) * max(0.0, min(0.2 if cr is None else cr, 0.5))
                _sub(parent, "path", d=_chamfered_rect_path(ox, oy, sx, sy, r, c, chamfer),
                     fill=color)
            else:
                _sub(parent, "rect", x=ox - sx / 2.0, y=oy - sy / 2.0, width=sx, height=sy,
                     rx=r if r > 0 else None, ry=r if r > 0 else None, fill=color)
        elif shape == "trapezoid":
            dx, dy = pad.rect_delta or (0.0, 0.0)
            hx, hy, tx, ty = sx / 2.0, sy / 2.0, dx / 2.0, dy / 2.0
            corners = [(-hx - ty, hy + tx), (hx + ty, hy - tx), (hx - ty, -hy + tx),
                       (-hx + ty, -hy - tx)]
            pts = " ".join(_pt((ox + x, oy + y)) for x, y in corners)
            _sub(parent, "polygon", points=pts, fill=color)
        elif shape == "custom":
            if pad.anchor == "circle":
                _sub(parent, "circle", cx=ox, cy=oy, r=sx / 2.0, fill=color)
            else:
                _sub(parent, "rect", x=ox - sx / 2.0, y=oy - sy / 2.0, width=sx, height=sy,
                     fill=color)
            prims = [g for g in pad.primitive_views
                     if g.node.name not in ("gr_bbox", "gr_vector")]
            if prims:
                holder = _sub(parent, "g", transform=f"translate({_f(ox)} {_f(oy)})"
                              if (ox, oy) != (0.0, 0.0) else None)
                for g in prims:
                    self.shape(holder, g, color)
        else:
            # неизвестная форма — описанный прямоугольник
            _sub(parent, "rect", x=ox - sx / 2.0, y=oy - sy / 2.0, width=sx, height=sy,
                 fill=color)

    def _pad_group(self, layer: str, pad: Pad, extra_class: str = "") -> ET.Element:
        x, y = pad.position
        a = pad.angle
        tr = f"translate({_f(x)} {_f(y)})"
        if a:
            tr += f" rotate({_f(-a)})"
        cls = "pad" + (f" {extra_class}" if extra_class else "")
        return _sub(self.group(layer), "g", class_=cls, data_number=pad.number,
                    data_type=pad.type, transform=tr)

    def draw_pads(self) -> None:
        """Площадки: медь, немедные слои, отверстия, номера."""
        for pad in self.fp.pads:
            ptype = pad.type
            names = [n for n in _L.expand(pad.layers) if self.allowed(n)]
            copper = [n for n in names if _L.is_copper(n)]
            other = [n for n in names if not _L.is_copper(n)]
            drawn = False
            d = pad.drill
            dw, dh = d.size if d is not None else (0.0, 0.0)
            through = ptype in ("thru_hole", "np_thru_hole")
            for layer in other:
                self._pad_shape(self._pad_group(layer, pad), pad, _L.color(layer))
                drawn = True
            if copper:
                if through:
                    has_copper = ptype == "thru_hole" or (
                        pad.size_x > dw + 1e-9 or pad.size_y > (dh or dw) + 1e-9)
                    if has_copper:
                        top = max(copper, key=self.rank)
                        self._pad_shape(self._pad_group(top, pad), pad, _L.COLORS["pad_th"])
                    drawn = True
                else:
                    for layer in copper:
                        self._pad_shape(self._pad_group(layer, pad), pad, _L.color(layer))
                    drawn = True
            if not drawn:
                continue
            self.grow(pad.bbox())
            if through and (dw > 0 or dh > 0):
                self._hole(pad, dw, dh)
            if self.pad_numbers and pad.number:
                self._pad_number(pad)

    def _hole(self, pad: Pad, dw: float, dh: float) -> None:
        g = self._pad_group(HOLES_LAYER, pad, "hole")
        if pad.type == "np_thru_hole":
            fill, stroke = _L.COLORS["npth"], None
        else:
            fill, stroke = _L.COLORS["background"], _L.COLORS["hole"]
        dh = dh or dw
        if abs(dw - dh) < 1e-9:
            el = _sub(g, "circle", cx=0.0, cy=0.0, r=dw / 2.0, fill=fill)
        else:
            r = min(dw, dh) / 2.0
            el = _sub(g, "rect", x=-dw / 2.0, y=-dh / 2.0, width=dw, height=dh, rx=r, ry=r,
                      fill=fill)
        if stroke:
            el.set("stroke", stroke)
            el.set("stroke-width", _f(min(dw, dh) * 0.08))

    def _pad_number(self, pad: Pad) -> None:
        x, y = pad.position
        m = min(pad.size_x, pad.size_y)
        size = max(0.05, min(m * 0.5, 1.4 * m / max(len(pad.number), 1)))
        g = _sub(self.group(PAD_NUMBERS_LAYER), "g", class_="pad-number",
                 transform=f"translate({_f(x)} {_f(y)}) scale({_f(1.0 / _TEXT_K)})")
        k = _TEXT_K
        t = _sub(g, "text", x=0.0, y=size * _CAP_HEIGHT / 2.0 * k, font_size=size * k,
                 font_family=_FONT_FAMILY, text_anchor="middle",
                 fill=_L.COLORS["pad_net_names"])
        t.text = pad.number

    # --- тексты ------------------------------------------------------------------------
    def draw_texts(self) -> None:
        """Тексты и поля на своих слоях."""
        for t in self.fp.texts:
            layer = t.layer
            if not self.allowed(layer):
                continue
            if t.hide and not self.show_hidden:
                continue
            if t.node.find("at") is None:
                continue
            self._text(t, layer)  # type: ignore[arg-type]

    def _text(self, t: Text, layer: str) -> None:
        content = _substitute(t.text, self.fp)
        lines = content.split("\n")
        h = t.font_size_y if t.font_size_y > 0 else 1.0
        wch = t.font_size_x if t.font_size_x > 0 else h
        just = t.justify
        anchor = "start" if "left" in just else ("end" if "right" in just else "middle")
        pitch = h * _LINE_PITCH
        n = len(lines)
        block = h + pitch * (n - 1)
        if "top" in just:
            top = 0.0
        elif "bottom" in just:
            top = -block
        else:
            top = -block / 2.0
        angle = _readable_angle(t.angle, bool(t.unlocked))
        x, y = t.position
        tr = f"translate({_f(x)} {_f(y)})"
        if angle:
            tr += f" rotate({_f(-angle)})"
        k = _TEXT_K
        tr += f" scale({_f(-1.0 / k) if t.mirror else _f(1.0 / k)} {_f(1.0 / k)})"
        color = _L.color(layer)
        g = _sub(self.group(layer), "g", class_=f"text {t.kind}", transform=tr)
        for i, line in enumerate(lines):
            # базовая линия строки i: верх строки + высота символа
            base = top + i * pitch + h
            el = _sub(g, "text", x=0.0, y=(base - h * (1.0 - _CAP_HEIGHT) / 2.0) * k,
                      font_size=h * k, font_family=_FONT_FAMILY, text_anchor=anchor, fill=color,
                      font_weight="bold" if t.bold else None,
                      font_style="italic" if t.italic else None)
            el.text = line
        # приближённые габариты
        w = max((len(s) for s in lines), default=1) * wch * _CHAR_WIDTH
        x0 = 0.0 if anchor == "start" else (-w if anchor == "end" else -w / 2.0)
        if t.mirror:
            x0 = -x0 - w
        corners = [(x0, top), (x0 + w, top), (x0 + w, top + block), (x0, top + block)]
        pts = [_geo.rotate_point(p, angle) for p in corners]
        self.grow(BBox.of_points([(x + px, y + py) for px, py in pts]))

    # --- завершение --------------------------------------------------------------------
    def view_box(self) -> BBox:
        """Область документа: габариты нарисованного плюс поле."""
        b = self.bbox
        if b is None:
            try:
                b = self.fp.bbox()
            except Exception:  # noqa: BLE001 — габариты повреждённого корпуса
                b = None
        if b is None:
            b = BBox(0.0, 0.0, 0.0, 0.0)
        if b.width <= 0 and b.height <= 0 and self.margin <= 0:
            b = b.inflated(1.0)
        b = b.inflated(self.margin)
        if b.width <= 0:
            b = BBox(b.x1 - 0.5, b.y1, b.x2 + 0.5, b.y2)
        if b.height <= 0:
            b = BBox(b.x1, b.y1 - 0.5, b.x2, b.y2 + 0.5)
        return b

    def finish(self, scale: float) -> str:
        """Собрать документ с масштабом ``scale`` пикселей на миллиметр."""
        vb = self.view_box()
        px = 1.0 / scale
        root = ET.Element("svg", {
            "xmlns": SVG_NS, "version": "1.1",
            "width": _f(vb.width * scale), "height": _f(vb.height * scale),
            "viewBox": f"{_f(vb.x1)} {_f(vb.y1)} {_f(vb.width)} {_f(vb.height)}",
            "stroke-linecap": "round", "stroke-linejoin": "round",
        })
        title = ET.SubElement(root, "title")
        title.text = self.fp.name
        if self.background:
            _sub(root, "rect", class_="background", x=vb.x1, y=vb.y1, width=vb.width,
                 height=vb.height, fill=_L.COLORS["background"])
        if self.grid is not None and self.grid > 0:
            self._grid(root, vb, scale)
        for layer in sorted(self.groups, key=self.rank):
            root.append(self.groups[layer])
        for el in self.hairlines:
            el.set("stroke-width", _f(px))
        ET.indent(root, space=" ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, "unicode") + "\n"

    def _grid(self, root: ET.Element, vb: BBox, scale: float) -> None:
        step = float(self.grid)  # type: ignore[arg-type]
        while (step * scale < _MIN_GRID_PX
               or (vb.width + vb.height) / step > _MAX_GRID_LINES):
            step *= 2.0
        g = _sub(root, "g", class_="grid", data_step=step)
        parts: list[str] = []
        i = math.ceil(vb.x1 / step)
        while i * step <= vb.x2 + 1e-9:
            x = i * step
            parts.append(f"M {_f(x)} {_f(vb.y1)} V {_f(vb.y2)}")
            i += 1
        j = math.ceil(vb.y1 / step)
        while j * step <= vb.y2 + 1e-9:
            y = j * step
            parts.append(f"M {_f(vb.x1)} {_f(y)} H {_f(vb.x2)}")
            j += 1
        if parts:
            _sub(g, "path", d=" ".join(parts), fill="none", stroke=_L.COLORS["grid"],
                 stroke_width=0.5 / scale, stroke_opacity=0.5)
        axes: list[str] = []
        if vb.x1 <= 0.0 <= vb.x2:
            axes.append(f"M 0 {_f(vb.y1)} V {_f(vb.y2)}")
        if vb.y1 <= 0.0 <= vb.y2:
            axes.append(f"M {_f(vb.x1)} 0 H {_f(vb.x2)}")
        if axes:
            _sub(g, "path", class_="axes", d=" ".join(axes), fill="none",
                 stroke=_L.COLORS["grid_axes"], stroke_width=1.0 / scale, stroke_opacity=0.6)


def _chamfered_rect_path(ox: float, oy: float, sx: float, sy: float, r: float, c: float,
                         corners: list[str]) -> str:
    """Путь прямоугольника ``sx × sy`` (центр ``(ox, oy)``) со скруглением ``r`` и фасками
    ``c`` на углах ``corners`` (``top_left`` … — «верх» — меньшее Y), обход по часовой
    стрелке на экране."""
    hx, hy = sx / 2.0, sy / 2.0
    # углы по часовой стрелке на экране: (имя, точка угла, направление входа, выхода)
    spec = [("top_left", (-hx, -hy)), ("top_right", (hx, -hy)),
            ("bottom_right", (hx, hy)), ("bottom_left", (-hx, hy))]
    cut = {name: (c if name in corners else r) for name, _ in spec}
    kinds = {name: ("chamfer" if name in corners else ("round" if r > 0 else "sharp"))
             for name, _ in spec}
    # направления сторон при обходе: верх -> +x, правая -> +y, низ -> -x, левая -> -y
    dirs = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
    parts: list[str] = []
    for i, (name, (px, py)) in enumerate(spec):
        a = cut[name] if kinds[name] != "sharp" else 0.0
        din = dirs[(i - 1) % 4]   # направление стороны, входящей в угол
        dout = dirs[i]            # направление стороны, выходящей из угла
        p_in = (ox + px - din[0] * a, oy + py - din[1] * a)
        p_out = (ox + px + dout[0] * a, oy + py + dout[1] * a)
        parts.append(("M " if not parts else "L ") + _pt(p_in))
        if a > 0:
            if kinds[name] == "round":
                parts.append(f"A {_f(a)} {_f(a)} 0 0 1 {_pt(p_out)}")
            else:
                parts.append(f"L {_pt(p_out)}")
    parts.append("Z")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def _prepare(fp: Footprint, *, layers: Iterable[str] | None, grid: float | None,
             background: bool, margin: float, show_hidden: bool,
             pad_numbers: bool) -> _Renderer:
    if not isinstance(fp, Footprint):
        raise TypeError(f"ожидается Footprint, получено {type(fp).__name__}")
    r = _Renderer(fp, layers=layers, grid=grid, background=background, margin=margin,
                  show_hidden=show_hidden, pad_numbers=pad_numbers)
    r.draw_graphics()
    r.draw_pads()
    r.draw_texts()
    return r


def render_svg(fp: Footprint, *, layers: Iterable[str] | None = None, scale: float = 10.0,
               grid: float | None = 1.0, background: bool = True, margin: float = 2.0,
               show_hidden: bool = False, pad_numbers: bool = False) -> str:
    """SVG-документ посадочного места (строка; UTF-8, завершающий перевод строки).

    ``layers`` — фильтр слоёв (имена и групповые обозначения ``*.Cu``, ``*.SilkS``, …;
    ``None`` — все слои); ``scale`` — пикселей на миллиметр (размер документа
    ``width``/``height``); ``grid`` — шаг сетки в мм (``None`` — без сетки); ``background`` —
    закрасить фон цветом ``COLORS["background"]``; ``margin`` — поле вокруг габаритов, мм.
    Дополнительно (расширение контракта): ``show_hidden`` — рисовать скрытые тексты,
    ``pad_numbers`` — подписывать номера площадок. Правила отрисовки — в описании модуля.
    """
    scale = float(scale)
    if not scale > 0 or math.isinf(scale):
        raise ValueError(f"масштаб должен быть положительным: {scale!r}")
    r = _prepare(fp, layers=layers, grid=grid, background=background, margin=margin,
                 show_hidden=show_hidden, pad_numbers=pad_numbers)
    return r.finish(scale)


def save_svg(fp: Footprint, path: str | PathLike[str], **kw: Any) -> None:
    """Записать :func:`render_svg` (``kw`` — её параметры) в файл ``path`` (UTF-8, LF)."""
    text = render_svg(fp, **kw)
    with open(os.fspath(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _ensure_qt_app() -> None:
    """Создать приложение Qt, если его ещё нет (нужно для шрифтов при рендере текста).

    Создаётся ``QApplication`` (а не ``QGuiApplication``), чтобы тот же процесс мог
    потом открыть виджеты GUI. На Linux без дисплея выбирается платформа ``offscreen``."""
    global _QT_APP
    from PySide6.QtCore import QCoreApplication
    if QCoreApplication.instance() is not None:
        return
    if (sys.platform.startswith("linux") and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    _QT_APP = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "kicadfp"])


def save_png(fp: Footprint, path: str | PathLike[str], *, width: int = 800, **kw: Any) -> None:
    """Записать изображение PNG шириной ``width`` пикселей (высота — по пропорциям).

    Рисунок — тот же SVG, что :func:`render_svg` (``kw`` — её параметры, кроме ``scale``:
    он подбирается по ``width``), отрисованный ``QtSvg.QSvgRenderer`` в ``QImage``; при
    ``background=False`` фон прозрачный. Нужен PySide6 (``pip install kicadfp[png]``);
    без него — :class:`RuntimeError`. Ошибка записи файла — :class:`OSError`.
    """
    try:
        from PySide6.QtCore import QByteArray, QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError as exc:
        raise RuntimeError("для экспорта PNG нужен PySide6: установите его командой "
                           "pip install kicadfp[png]") from exc
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValueError(f"ширина изображения должна быть целым положительным числом: {width!r}")
    kw.pop("scale", None)
    r = _prepare(fp, layers=kw.pop("layers", None), grid=kw.pop("grid", 1.0),
                 background=kw.pop("background", True), margin=kw.pop("margin", 2.0),
                 show_hidden=kw.pop("show_hidden", False),
                 pad_numbers=kw.pop("pad_numbers", False))
    if kw:
        raise TypeError(f"неизвестные параметры: {', '.join(sorted(kw))}")
    vb = r.view_box()
    scale = width / vb.width
    height = max(1, round(vb.height * scale))
    svg = r.finish(scale)
    _ensure_qt_app()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("QSvgRenderer не смог разобрать сформированный SVG")
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        renderer.render(painter, QRectF(0, 0, width, height))
    finally:
        painter.end()
    out = Path(os.fspath(path))
    if not image.save(str(out), "PNG"):
        raise OSError(f"не удалось записать PNG: {out}")
