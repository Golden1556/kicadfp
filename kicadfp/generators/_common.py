"""Общие построители для генераторов посадочных мест (``docs/dev/lab-generators.md`` §1).

Содержимое:

* константы KLC (толщины линий, шрифт, отступы courtyard, зазор шелкографии);
* округление к сетке courtyard 0.01 «наружу» (:func:`floor_grid`, :func:`ceil_grid`);
* создание корпуса (:func:`new_footprint`) с Reference (F.SilkS) и Value (F.Fab) и без
  служебных полей Datasheet/Description (lab-generators.md §1.2 п.4);
* площадки: одиночные (:func:`add_pad`), ряды (:func:`add_pad_row`), монтажные отверстия
  (:func:`add_mounting_hole`);
* графика: ломаные (:func:`add_polyline`), дуги в направлении обхода KiCad
  (:func:`add_arc`), ``${REFERENCE}`` на F.Fab (:func:`add_fab_reference`);
* область размещения по габаритам площадок и F.Fab (:func:`add_courtyard_rect`,
  :func:`courtyard_box`);
* обрезка шелкографии у площадок (:func:`clip_silk`, lab-generators.md §1.5);
* завершение (:func:`finalize`): порядок узлов как у writer'а KiCad 9 и детерминированные
  ``uuid5`` (одни и те же параметры — один и тот же файл).

Все размеры — миллиметры, система координат KiCad (Y вниз).
"""

from __future__ import annotations

import math
import uuid as _uuidlib
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from ..format_rules import DEFAULT_VERSION, drawing_sort_key
from ..geometry import BBox, angle_of, arc_from_three_points, normalize_angle, round_mm
from ..model import Footprint, Pad, Text
from ..sexpr import Node, Str, to_compact

__all__ = [
    "SILK_WIDTH", "FAB_WIDTH", "CRTYD_WIDTH", "TEXT_SIZE", "TEXT_THICKNESS",
    "COURTYARD_OFFSET", "CONNECTOR_COURTYARD_OFFSET", "COURTYARD_GRID", "SILK_PAD_CLEARANCE",
    "SILK_PAD_OFFSET", "SILK_MIN_LENGTH", "TEXT_OFFSET", "UUID_NAMESPACE",
    "Point", "Zone", "floor_grid", "ceil_grid", "num", "pad_pair", "check_positive",
    "new_footprint", "set_texts", "add_fab_reference", "fab_reference_size",
    "add_pad", "add_pad_row", "add_mounting_hole", "add_polyline", "add_lines", "add_arc",
    "courtyard_box", "add_courtyard_rect", "pad_keepouts", "clip_silk", "clip_segment",
    "clip_arc", "clip_circle", "finalize", "min_silk_clearance",
]

Point = tuple[float, float]

#: Толщина линий шелкографии F.SilkS (KLC F5.1).
SILK_WIDTH = 0.12
#: Толщина линий сборочного слоя F.Fab (KLC F5.2).
FAB_WIDTH = 0.1
#: Толщина линий области размещения F.CrtYd (KLC F5.3).
CRTYD_WIDTH = 0.05
#: Размер шрифта Reference / Value / ``${REFERENCE}``.
TEXT_SIZE = 1.0
#: Толщина шрифта Reference / Value / ``${REFERENCE}``.
TEXT_THICKNESS = 0.15
#: Отступ courtyard от корпуса и площадок (KLC F5.3 п.5).
COURTYARD_OFFSET = 0.25
#: Отступ courtyard у разъёмов (KLC F5.3 п.7).
CONNECTOR_COURTYARD_OFFSET = 0.5
#: Сетка courtyard (округление наружу).
COURTYARD_GRID = 0.01
#: Зазор «край линии шелкографии — край меди» (KLC F5.1).
SILK_PAD_CLEARANCE = 0.2
#: Смещение оси линии шелкографии от края меди: 0.2 + 0.12/2.
SILK_PAD_OFFSET = SILK_PAD_CLEARANCE + SILK_WIDTH / 2
#: Минимальная длина куска шелкографии после обрезки.
SILK_MIN_LENGTH = 0.2
#: Отступ центра текста от крайней линии контура.
TEXT_OFFSET = 1.0
#: Пространство имён детерминированных ``uuid5`` генераторов kicadfp.
UUID_NAMESPACE = _uuidlib.uuid5(_uuidlib.NAMESPACE_URL, "kicadfp/generators")

_EPS = 1e-9


# ---------------------------------------------------------------------------------------------
# Числа и параметры
# ---------------------------------------------------------------------------------------------

def floor_grid(value: float, grid: float = COURTYARD_GRID) -> float:
    """Округлить вниз к сетке ``grid`` с защитой от погрешности float (1e-6 шага)."""
    return round_mm(math.floor(value / grid + 1e-6) * grid)


def ceil_grid(value: float, grid: float = COURTYARD_GRID) -> float:
    """Округлить вверх к сетке ``grid`` с защитой от погрешности float (1e-6 шага)."""
    return round_mm(math.ceil(value / grid - 1e-6) * grid)


def num(value: float) -> str:
    """Число для имён и описаний: без хвостовых нулей (``7.5`` → ``"7.5"``, ``10.0`` →
    ``"10"``), не более 6 знаков после точки."""
    s = f"{round(float(value), 6):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pad_pair(size: float | Sequence[float], what: str = "pad_size") -> tuple[float, float]:
    """Размер площадки: число (квадрат/круг) или пара ``(sx, sy)``; оба > 0, иначе
    ``ValueError``."""
    if isinstance(size, bool):
        raise TypeError(f"{what}: ожидается число или пара чисел")
    if isinstance(size, (int, float)):
        sx = sy = float(size)
    else:
        vals = list(size)
        if len(vals) != 2:
            raise ValueError(f"{what}: ожидается число или пара (sx, sy), получено {size!r}")
        sx, sy = float(vals[0]), float(vals[1])
    check_positive(what, sx, sy)
    return sx, sy


def check_positive(what: str, *values: float) -> None:
    """``ValueError``, если какое-либо из значений не является положительным конечным числом."""
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) \
                or v <= 0:
            raise ValueError(f"{what}: ожидается положительное число, получено {v!r}")


def _check_drill(drill: float, size: tuple[float, float]) -> None:
    check_positive("drill", drill)
    if drill > min(size) + 1e-9:
        raise ValueError(f"отверстие {num(drill)} мм больше площадки "
                         f"{num(size[0])}×{num(size[1])} мм")


# ---------------------------------------------------------------------------------------------
# Корпус и тексты
# ---------------------------------------------------------------------------------------------

def new_footprint(name: str, *, descr: str = "", tags: str = "",
                  attrs: Iterable[str] = ("through_hole",)) -> Footprint:
    """Новый корпус формата ``DEFAULT_VERSION`` (KiCad 9) с генератором ``kicadfp``.

    Создаются Reference ``"REF**"`` на F.SilkS и Value = имя на F.Fab (шрифт 1 × 1, толщина
    0.15; положения задаёт :func:`set_texts`), ``attr``, ``descr``/``tags``. Служебные поля
    Datasheet/Description, которые :meth:`Footprint.new` добавляет по образцу KiCad 9,
    удаляются: генераторы их не создают (как kicad-footprint-generator, lab-generators.md
    §1.2 п.4); KiCad добавит их сам при открытии.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("имя корпуса не может быть пустым")
    fp = Footprint.new(name, version=DEFAULT_VERSION, descr=descr, tags=tags, attrs=attrs)
    props = fp.properties
    for key in ("Footprint", "Datasheet", "Description"):
        if key in props:
            del props[key]
    return fp


def set_texts(fp: Footprint, reference: tuple[float, ...], value: tuple[float, ...]) -> None:
    """Положения Reference и Value: кортежи ``(x, y)`` или ``(x, y, угол)``."""
    for text, pos in ((fp.reference, reference), (fp.value, value)):
        if text is None:  # pragma: no cover - new_footprint всегда создаёт оба текста
            continue
        text.x = round_mm(pos[0])
        text.y = round_mm(pos[1])
        text.angle = float(pos[2]) if len(pos) > 2 else 0.0


def fab_reference_size(length: float, diameter: float) -> tuple[float, float]:
    """Размер и толщина шрифта ``${REFERENCE}`` выводных/радиальных корпусов
    (lab-generators.md §3.4, ``footprint_scripts_resistorlike.py:121-128``): 1/0.15, но при
    длине ≤ 5 или диаметре ≤ 1 — ``s = min(0.8·D, L/5)``, ``t = 0.15·s``; затем
    ``s ≥ 0.25``, ``t ≥ 0.0375``."""
    s, t = TEXT_SIZE, TEXT_THICKNESS
    if length <= 5 or diameter <= 1:
        s = min(0.8 * diameter, length / 5)
        t = 0.15 * s
    s = max(0.25, s)
    t = max(0.0375, t)
    return round_mm(s), round_mm(t)


def add_fab_reference(fp: Footprint, x: float, y: float, angle: float = 0.0, *,
                      size: float = TEXT_SIZE, thickness: float = TEXT_THICKNESS) -> Text:
    """Текст ``${REFERENCE}`` на F.Fab (KLC F5.2) в точке ``(x, y)``."""
    return fp.new_text("${REFERENCE}", "user", round_mm(x), round_mm(y), "F.Fab",
                       angle=float(angle), size=size, thickness=thickness)


# ---------------------------------------------------------------------------------------------
# Площадки
# ---------------------------------------------------------------------------------------------

def add_pad(fp: Footprint, number: str | int, x: float, y: float,
            size: float | Sequence[float], drill: float, shape: str = "circle") -> Pad:
    """Сигнальная сквозная площадка ``thru_hole`` (слои ``*.Cu *.Mask``) в ``(x, y)``."""
    sz = pad_pair(size)
    _check_drill(drill, sz)
    return fp.new_pad(str(number), "thru_hole", shape, round_mm(x), round_mm(y), sz,
                      drill=float(drill))


def add_pad_row(fp: Footprint, numbers: Iterable[str | int], start: Point, step: Point,
                size: float | Sequence[float], drill: float, *, shape: str = "circle",
                first_shape: str | None = None) -> list[Pad]:
    """Ряд площадок: ``i``-я площадка (с нуля) — в ``start + i·step``.

    ``numbers`` — номера по порядку; ``first_shape`` — форма первой площадки ряда (обычно
    ``"rect"`` для площадки 1), остальные — ``shape``.
    """
    out: list[Pad] = []
    for i, n in enumerate(numbers):
        sh = first_shape if (i == 0 and first_shape) else shape
        out.append(add_pad(fp, n, start[0] + i * step[0], start[1] + i * step[1], size, drill,
                           sh))
    return out


def add_mounting_hole(fp: Footprint, x: float, y: float, diameter: float) -> Pad:
    """Монтажное (неметаллизированное) отверстие: ``(pad "" np_thru_hole circle … (size D D)
    (drill D) (layers "*.Cu" "*.Mask"))`` (lab-generators.md §1.3)."""
    check_positive("диаметр монтажного отверстия", diameter)
    d = float(diameter)
    return fp.new_pad("", "np_thru_hole", "circle", round_mm(x), round_mm(y), (d, d), drill=d)


# ---------------------------------------------------------------------------------------------
# Графика
# ---------------------------------------------------------------------------------------------

def _pt(p: Point) -> Point:
    return (round_mm(p[0]), round_mm(p[1]))


def add_lines(fp: Footprint, segments: Iterable[tuple[Point, Point]], layer: str,
              width: float) -> None:
    """Отрезки ``fp_line`` (пары точек) на слое ``layer``."""
    for a, b in segments:
        fp.new_line(_pt(a), _pt(b), layer, width)


def add_polyline(fp: Footprint, points: Sequence[Point], layer: str, width: float, *,
                 closed: bool = False) -> None:
    """Ломаная из отрезков ``fp_line`` по точкам ``points`` (``closed`` — замкнуть)."""
    pts = list(points)
    if closed and pts:
        pts.append(pts[0])
    add_lines(fp, zip(pts, pts[1:]), layer, width)


def add_arc(fp: Footprint, start: Point, mid: Point, end: Point, layer: str,
            width: float) -> None:
    """Дуга ``fp_arc`` по трём точкам в направлении обхода KiCad (по часовой стрелке на
    экране, как ``EDA_SHAPE::SetArcGeometry``): при обратном направлении начало и конец
    меняются местами."""
    s, m, e = _pt(start), _pt(mid), _pt(end)
    g = arc_from_three_points(s, m, e)
    if g is not None and g.sweep > 0:
        s, e = e, s
    fp.new_arc(s, m, e, layer, width)


# ---------------------------------------------------------------------------------------------
# Courtyard
# ---------------------------------------------------------------------------------------------

def courtyard_box(fp: Footprint, offset: float = COURTYARD_OFFSET,
                  extra: Iterable[BBox] = ()) -> BBox:
    """Прямоугольник области размещения (lab-generators.md §1.4): объединение габаритов всех
    площадок (включая монтажные отверстия), контура F.Fab и ``extra``, расширенное на
    ``offset`` и округлённое к сетке 0.01 наружу."""
    b = fp.bbox(layers=["F.Fab"], include_pads=True)
    for e in extra:
        b = b.union(e)
    return BBox(floor_grid(b.x1 - offset), floor_grid(b.y1 - offset),
                ceil_grid(b.x2 + offset), ceil_grid(b.y2 + offset))


def add_courtyard_rect(fp: Footprint, offset: float = COURTYARD_OFFSET,
                       extra: Iterable[BBox] = ()) -> BBox:
    """Добавить ``fp_rect`` на F.CrtYd по :func:`courtyard_box`; возвращает прямоугольник."""
    b = courtyard_box(fp, offset, extra)
    fp.new_rect((b.x1, b.y1), (b.x2, b.y2), "F.CrtYd", CRTYD_WIDTH)
    return b


# ---------------------------------------------------------------------------------------------
# Обрезка шелкографии у площадок (lab-generators.md §1.5)
# ---------------------------------------------------------------------------------------------

class Zone(NamedTuple):
    """Зона запрета шелкографии: круг (``kind="circle"``: центр ``(a, b)``, радиус ``c``)
    или прямоугольник (``kind="rect"``: ``(a, b)`` — ``(c, d)``)."""

    kind: str
    a: float
    b: float
    c: float
    d: float = 0.0

    def inside(self, p: Point) -> bool:
        """Точка строго внутри зоны (граница допускается)."""
        if self.kind == "circle":
            return math.hypot(p[0] - self.a, p[1] - self.b) < self.c - 1e-7
        return (self.a + 1e-7 < p[0] < self.c - 1e-7) and (self.b + 1e-7 < p[1] < self.d - 1e-7)


def pad_keepouts(fp: Footprint, offset: float = SILK_PAD_OFFSET) -> list[Zone]:
    """Зоны запрета вокруг всех площадок (включая ``np_thru_hole``): ``circle`` — круг
    радиуса ``max(sx, sy)/2 + offset``, любая другая форма — прямоугольник площадки,
    расширенный на ``offset`` (площадки генераторов не повёрнуты; у повёрнутой берётся
    описанный прямоугольник)."""
    zones: list[Zone] = []
    for p in fp.pads:
        if p.shape == "circle":
            zones.append(Zone("circle", p.x, p.y, max(p.size_x, p.size_y) / 2 + offset))
        else:
            b = p.bbox()
            zones.append(Zone("rect", b.x1 - offset, b.y1 - offset, b.x2 + offset,
                              b.y2 + offset))
    return zones


def _kept_intervals(ts: list[float], inside) -> list[tuple[float, float]]:
    """Интервалы параметра [0, 1] между критическими точками ``ts``, середина которых не
    лежит в зонах; соседние интервалы сливаются."""
    pts = sorted({0.0, 1.0, *[t for t in ts if _EPS < t < 1 - _EPS]})
    kept: list[tuple[float, float]] = []
    for t0, t1 in zip(pts, pts[1:]):
        if t1 - t0 <= _EPS:
            continue
        if inside((t0 + t1) / 2):
            continue
        if kept and abs(kept[-1][1] - t0) <= _EPS:
            kept[-1] = (kept[-1][0], t1)
        else:
            kept.append((t0, t1))
    return kept


def clip_segment(a: Point, b: Point, zones: Sequence[Zone],
                 min_length: float = SILK_MIN_LENGTH) -> list[tuple[Point, Point]]:
    """Вырезать из отрезка ``a–b`` части, лежащие строго внутри зон. Нетронутый отрезок
    возвращается как есть; куски короче ``min_length`` отбрасываются. Направление кусков —
    как у исходного отрезка."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    ts: list[float] = []
    for z in zones:
        if z.kind == "circle":
            fx, fy = ax - z.a, ay - z.b
            qa = dx * dx + dy * dy
            qb = 2 * (fx * dx + fy * dy)
            qc = fx * fx + fy * fy - z.c * z.c
            disc = qb * qb - 4 * qa * qc
            if qa > 0 and disc > 0:
                r = math.sqrt(disc)
                ts += [(-qb - r) / (2 * qa), (-qb + r) / (2 * qa)]
        else:
            if dx:
                ts += [(z.a - ax) / dx, (z.c - ax) / dx]
            if dy:
                ts += [(z.b - ay) / dy, (z.d - ay) / dy]

    def inside(t: float) -> bool:
        p = (ax + dx * t, ay + dy * t)
        return any(z.inside(p) for z in zones)

    kept = _kept_intervals(ts, inside)
    if kept == [(0.0, 1.0)]:
        return [(a, b)]
    length = math.hypot(dx, dy)
    out = []
    for t0, t1 in kept:
        if (t1 - t0) * length < min_length - 1e-9:
            continue
        out.append(((round_mm(ax + dx * t0), round_mm(ay + dy * t0)),
                    (round_mm(ax + dx * t1), round_mm(ay + dy * t1))))
    return out


def _circle_crossings(center: Point, radius: float, z: Zone) -> list[float]:
    """Углы (градусы, соглашение :func:`kicadfp.geometry.angle_of`) точек пересечения
    окружности с границей зоны (для прямоугольника — с прямыми его сторон)."""
    cx, cy = center
    out: list[float] = []
    if z.kind == "circle":
        d = math.hypot(z.a - cx, z.b - cy)
        if d <= _EPS or d >= radius + z.c or d <= abs(radius - z.c):
            return out
        base = angle_of(center, (z.a, z.b))
        cos_t = (radius * radius + d * d - z.c * z.c) / (2 * radius * d)
        t = math.degrees(math.acos(max(-1.0, min(1.0, cos_t))))
        return [base - t, base + t]
    for xv in (z.a, z.c):
        c = (xv - cx) / radius
        if -1 < c < 1:
            t = math.degrees(math.acos(c))
            out += [t, -t]
    for yv in (z.b, z.d):
        s = -(yv - cy) / radius  # экранный Y вниз: угол отсчитывается вверх
        if -1 < s < 1:
            t = math.degrees(math.asin(s))
            out += [t, 180 - t]
    return out


def _point_on(center: Point, radius: float, angle: float) -> Point:
    a = math.radians(angle)
    return (round_mm(center[0] + radius * math.cos(a)), round_mm(center[1] - radius * math.sin(a)))


def clip_arc(start: Point, mid: Point, end: Point, zones: Sequence[Zone],
             min_length: float = SILK_MIN_LENGTH) -> list[tuple[Point, Point, Point]]:
    """Обрезать дугу по зонам (по углу); нетронутая дуга возвращается как есть, куски
    короче ``min_length`` (по длине дуги) отбрасываются."""
    g = arc_from_three_points(start, mid, end)
    if g is None:
        return [(start, mid, end)]
    sa, sw = g.start_angle, g.sweep
    ts: list[float] = []
    for z in zones:
        for ang in _circle_crossings(g.center, g.radius, z):
            rel = normalize_angle(ang - sa) if sw > 0 else normalize_angle(sa - ang)
            ts.append(rel / abs(sw))

    def inside(t: float) -> bool:
        p = _point_on(g.center, g.radius, sa + sw * t)
        return any(z.inside(p) for z in zones)

    kept = _kept_intervals(ts, inside)
    if kept == [(0.0, 1.0)]:
        return [(start, mid, end)]
    out = []
    for t0, t1 in kept:
        if math.radians(abs(sw) * (t1 - t0)) * g.radius < min_length - 1e-9:
            continue
        out.append((_point_on(g.center, g.radius, sa + sw * t0),
                    _point_on(g.center, g.radius, sa + sw * (t0 + t1) / 2),
                    _point_on(g.center, g.radius, sa + sw * t1)))
    return out


def clip_circle(center: Point, radius: float, zones: Sequence[Zone],
                min_length: float = SILK_MIN_LENGTH) -> list[tuple[Point, Point, Point]] | None:
    """Обрезать окружность по зонам. ``None`` — окружность не задета (оставить как есть);
    иначе список дуг ``(start, mid, end)``: обход начинается с первого угла внутри зоны
    (lab-generators.md §1.5); пустой список — окружность целиком внутри зон."""
    angles = sorted({round(normalize_angle(a), 9) for z in zones
                     for a in _circle_crossings(center, radius, z)})

    def inside_at(a: float) -> bool:
        p = _point_on(center, radius, a)
        return any(z.inside(p) for z in zones)

    if not angles:
        return [] if inside_at(0.0) else None
    k = len(angles)
    ivals = [(angles[i], angles[i + 1] if i + 1 < k else angles[0] + 360.0) for i in range(k)]
    flags = [inside_at((a0 + a1) / 2) for a0, a1 in ivals]
    if not any(flags):
        return None
    j = flags.index(True)
    order = ivals[j:] + [(a0 + 360.0, a1 + 360.0) for a0, a1 in ivals[:j]]
    oflags = flags[j:] + flags[:j]
    arcs: list[tuple[float, float]] = []
    for (a0, a1), ins in zip(order, oflags):
        if ins:
            continue
        if arcs and abs(arcs[-1][1] - a0) <= 1e-9:
            arcs[-1] = (arcs[-1][0], a1)
        else:
            arcs.append((a0, a1))
    out = []
    for a0, a1 in arcs:
        if math.radians(a1 - a0) * radius < min_length - 1e-9:
            continue
        # по часовой стрелке на экране (как KiCad): от большего угла к меньшему
        out.append((_point_on(center, radius, a1), _point_on(center, radius, (a0 + a1) / 2),
                    _point_on(center, radius, a0)))
    return out


def clip_silk(fp: Footprint, zones: Sequence[Zone] | None = None, *,
              layer: str = "F.SilkS") -> None:
    """Обрезать графику шелкографии ``layer`` (``fp_line``, ``fp_arc``, ``fp_circle``) по
    зонам запрета (по умолчанию — :func:`pad_keepouts`). Изменённые элементы заменяются
    новыми с той же толщиной; нетронутые остаются как были."""
    if zones is None:
        zones = pad_keepouts(fp)
    if not zones:
        return
    for g in fp.graphics:
        if g.layer != layer or g.kind not in ("line", "arc", "circle"):
            continue
        width = g.width if g.width is not None else SILK_WIDTH
        if g.kind == "line":
            a, b = g.start, g.end  # type: ignore[attr-defined]
            pieces = clip_segment(a, b, zones)
            if pieces == [(a, b)]:
                continue
            fp.remove(g)
            for p0, p1 in pieces:
                fp.new_line(p0, p1, layer, width)
        elif g.kind == "arc":
            s, m, e = g.start, g.mid, g.end  # type: ignore[attr-defined]
            arcs = clip_arc(s, m, e, zones)
            if arcs == [(s, m, e)]:
                continue
            fp.remove(g)
            for a0, a1, a2 in arcs:
                add_arc(fp, a0, a1, a2, layer, width)
        else:
            arcs3 = clip_circle(g.center, g.radius, zones)  # type: ignore[attr-defined]
            if arcs3 is None:
                continue
            fp.remove(g)
            for a0, a1, a2 in arcs3:
                add_arc(fp, a0, a1, a2, layer, width)


def min_silk_clearance(fp: Footprint, layer: str = "F.SilkS") -> float:
    """Наименьшее расстояние от края линии шелкографии до края меди (приближённо: линии и
    дуги разбиваются на точки с шагом ≤ 0.01 мм; площадки ``circle`` — круги, остальные —
    прямоугольники). Отрицательное — линия заходит на медь. Для самопроверки и тестов."""
    from ..geometry import arc_points

    best = math.inf
    pads = fp.pads
    for g in fp.graphics:
        if g.layer != layer:
            continue
        w = (g.width or 0.0) / 2
        if g.kind == "line":
            a, b = g.start, g.end  # type: ignore[attr-defined]
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.01))
            pts = [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                   for i in range(n + 1)]
        elif g.kind == "arc":
            pts = arc_points(g.start, g.mid, g.end, 720)  # type: ignore[attr-defined]
        elif g.kind == "circle":
            c, r = g.center, g.radius  # type: ignore[attr-defined]
            pts = [_point_on(c, r, i / 2) for i in range(720)]
        elif g.kind == "rect":
            (x1, y1), (x2, y2) = g.start, g.end  # type: ignore[attr-defined]
            pts = []
            for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)),
                         ((x1, y2), (x1, y1))):
                n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.01))
                pts += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                        for i in range(n + 1)]
        else:
            continue
        for p in pads:
            for q in pts:
                if p.shape == "circle":
                    d = math.hypot(q[0] - p.x, q[1] - p.y) - max(p.size_x, p.size_y) / 2
                else:
                    bb = p.bbox()
                    ddx = max(bb.x1 - q[0], 0.0, q[0] - bb.x2)
                    ddy = max(bb.y1 - q[1], 0.0, q[1] - bb.y2)
                    inside = bb.x1 <= q[0] <= bb.x2 and bb.y1 <= q[1] <= bb.y2
                    d = -min(q[0] - bb.x1, bb.x2 - q[0], q[1] - bb.y1, bb.y2 - q[1]) \
                        if inside else math.hypot(ddx, ddy)
                best = min(best, d - w)
    return best


# ---------------------------------------------------------------------------------------------
# Завершение: порядок узлов и uuid
# ---------------------------------------------------------------------------------------------

def _strnum_key(s: str) -> tuple:
    """Ключ натуральной сортировки номеров площадок (группы цифр — как числа; пустой номер
    первым), приближение ``StrNumCmp`` KiCad."""
    import re

    parts = re.split(r"(\d+)", s.upper())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p != "")


def _fallback_sort(root: Node) -> None:
    """Упорядочить секцию рисования и площадки без закрытых помощников модели:
    фигуры/тексты по :func:`kicadfp.format_rules.drawing_sort_key` и координатам,
    площадки по номеру и положению."""
    from ..model import view_for

    def dkey(n: Node) -> tuple:
        v = view_for(n)
        pts = []
        try:
            pts = list(v.points())  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - тексты
            pass
        return drawing_sort_key(n, DEFAULT_VERSION) + tuple(
            round(c * 1e6) for p in pts for c in p)

    items = root.items
    draw = [i for i, x in enumerate(items) if isinstance(x, Node)
            and x.name in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_text")]
    nodes = sorted((items[i] for i in draw), key=dkey)
    for i, n in zip(draw, nodes):
        items[i] = n
    pads = [i for i, x in enumerate(items) if isinstance(x, Node) and x.name == "pad"]
    pn = sorted((items[i] for i in pads),
                key=lambda n: (_strnum_key(str(n.atom(0) or "")), Pad(n).x, Pad(n).y))
    for i, n in zip(pads, pn):
        items[i] = n


def finalize(fp: Footprint) -> Footprint:
    """Завершить корпус: порядок узлов — как у writer'а KiCad 9 (поля, ``cmp_drawings``,
    ``cmp_pads``: пустой номер монтажного отверстия первым) и детерминированные ``uuid5``
    всем элементам (от имени корпуса и содержимого узла; у одинаковых узлов — ещё номер
    повтора), чтобы повторная генерация с теми же параметрами давала тот же файл
    (lab-generators.md §1.2, «Решение (рекомендация)»). Возвращает ``fp``."""
    from .. import model as _model

    root = fp.node
    # сначала uuid (от содержимого, не от места): KiCad упорядочивает одинаковые по слою
    # тексты по uuid, поэтому сортировка — после их назначения
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for n in root.nodes():
        if n.find("uuid") is None:
            continue
        probe = n.copy()
        probe.remove("uuid")
        body = to_compact(probe)
        k = counts[body] = counts.get(body, 0) + 1
        seed = f"{fp.name}\n{k}\n{body}"
        value = str(_uuidlib.uuid5(UUID_NAMESPACE, seed))
        while value in seen:  # pragma: no cover - практически невозможно
            value = str(_uuidlib.uuid5(UUID_NAMESPACE, seed + value))
        seen.add(value)
        n.set("uuid", Str(value))
    sorter = getattr(_model, "_sort_root_like_kicad", None)
    if sorter is not None:
        sorter(root, fp.version or DEFAULT_VERSION)
    else:  # pragma: no cover - запасной путь, если модель изменится
        _fallback_sort(root)
    return fp
