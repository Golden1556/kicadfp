"""Вспомогательная геометрия для kicadfp (без сторонних зависимостей).

Система координат — как в KiCad: ось X вправо, ось Y **вниз**, единицы — миллиметры,
углы — градусы. Положительный угол поворота в файле KiCad соответствует повороту
против часовой стрелки на экране (т.е. по часовой стрелке в математической системе с
осью Y вверх); формулы ниже воспроизводят ``RotatePoint`` KiCad: точка ``(x, y)``
поворачивается на угол ``a`` вокруг начала координат как

    x' =  x·cos a + y·sin a
    y' = -x·sin a + y·cos a

Дуги описываются тремя точками ``start``/``mid``/``end`` (формат KiCad 6+). Функции
преобразования между тремя точками и представлением «центр/радиус/угол» нужны для
чтения формата KiCad 5 (``(fp_arc (start cx cy) (end sx sy) (angle a))``), старого
формата ``.mod`` (``DA``), для отрисовки и для расчёта габаритов.
"""

from __future__ import annotations

import math
from typing import Iterable, NamedTuple, Sequence

Point = tuple[float, float]

EPS = 1e-9


class BBox(NamedTuple):
    """Прямоугольная область (x1, y1) — (x2, y2), x1 <= x2, y1 <= y2."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> Point:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def union(self, other: "BBox | None") -> "BBox":
        if other is None:
            return self
        return BBox(min(self.x1, other.x1), min(self.y1, other.y1),
                    max(self.x2, other.x2), max(self.y2, other.y2))

    def inflated(self, d: float) -> "BBox":
        return BBox(self.x1 - d, self.y1 - d, self.x2 + d, self.y2 + d)

    def contains(self, p: Point) -> bool:
        return self.x1 - EPS <= p[0] <= self.x2 + EPS and self.y1 - EPS <= p[1] <= self.y2 + EPS

    @staticmethod
    def of_points(points: Iterable[Point]) -> "BBox | None":
        pts = list(points)
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return BBox(min(xs), min(ys), max(xs), max(ys))


def round_mm(value: float, ndigits: int = 6) -> float:
    """Округление до нанометров (точность внутренних единиц KiCad); ``-0.0`` -> ``0.0``."""
    r = round(float(value), ndigits)
    return 0.0 if r == 0 else r


def normalize_angle(angle: float) -> float:
    """Привести угол к диапазону [0, 360)."""
    a = math.fmod(float(angle), 360.0)
    if a < 0:
        a += 360.0
    if abs(a - 360.0) < EPS:
        a = 0.0
    return a


def normalize_angle_180(angle: float) -> float:
    """Привести угол к диапазону (-180, 180]."""
    a = normalize_angle(angle)
    if a > 180.0:
        a -= 360.0
    return a


def rotate_point(p: Point, angle: float, origin: Point = (0.0, 0.0)) -> Point:
    """Повернуть точку на ``angle`` градусов вокруг ``origin`` (соглашение KiCad, ось Y вниз).

    Положительный угол — против часовой стрелки на экране KiCad.
    """
    if angle == 0:
        return (float(p[0]), float(p[1]))
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    x = dx * c + dy * s
    y = -dx * s + dy * c
    return (round_mm(x + origin[0]), round_mm(y + origin[1]))


def mirror_point(p: Point, axis: str = "x", origin: float = 0.0) -> Point:
    """Зеркальное отражение точки.

    ``axis="x"`` — отражение относительно вертикальной оси ``x = origin`` (меняется X),
    ``axis="y"`` — относительно горизонтальной оси ``y = origin`` (меняется Y).
    """
    if axis == "x":
        return (round_mm(2 * origin - p[0]), float(p[1]))
    if axis == "y":
        return (float(p[0]), round_mm(2 * origin - p[1]))
    raise ValueError(f"неизвестная ось отражения: {axis!r} (ожидается 'x' или 'y')")


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def angle_of(center: Point, p: Point) -> float:
    """Угол (градусы, [0, 360)) направления из ``center`` в ``p`` в экранных координатах KiCad.

    Ось Y направлена вниз, поэтому угол отсчитывается против часовой стрелки на экране:
    точка справа от центра — 0°, сверху (меньшее Y) — 90°.
    """
    return normalize_angle(math.degrees(math.atan2(-(p[1] - center[1]), p[0] - center[0])))


def point_at_angle(center: Point, radius: float, angle: float) -> Point:
    """Точка на окружности под углом ``angle`` (соглашение как в :func:`angle_of`)."""
    a = math.radians(angle)
    return (round_mm(center[0] + radius * math.cos(a)), round_mm(center[1] - radius * math.sin(a)))


class ArcGeometry(NamedTuple):
    """Дуга в представлении центр/радиус/углы.

    ``start_angle`` и ``end_angle`` — в градусах (см. :func:`angle_of`); ``sweep`` —
    угол дуги со знаком: положительный — против часовой стрелки на экране (от
    ``start_angle`` в сторону увеличения угла), отрицательный — по часовой.
    """

    center: Point
    radius: float
    start_angle: float
    end_angle: float
    sweep: float


def _same_nm(a: Point, b: Point) -> bool:
    """Совпадают ли точки после округления до нанометра (внутренняя единица KiCad)."""
    return (round(a[0] * 1e6) == round(b[0] * 1e6)
            and round(a[1] * 1e6) == round(b[1] * 1e6))


def arc_from_three_points(start: Point, mid: Point, end: Point) -> ArcGeometry | None:
    """Центр, радиус и углы дуги, проходящей через ``start``, ``mid``, ``end``.

    Возвращает ``None`` для вырожденной (коллинеарной) дуги.

    Полная окружность (дуга на 360°): ``start`` совпадает с ``end`` с точностью до
    нанометра, а ``mid`` отличается от них. Такие дуги пишет и читает KiCad (есть в
    стандартных библиотеках всех версий); как ``CalcArcCenter`` KiCad (trigo.cpp), центр —
    середина отрезка ``start``–``mid``, радиус — половина его длины. Направление — как у
    KiCad (``EDA_SHAPE::CalcArcAngles``: конечный угол = начальный + 360° в системе KiCad,
    т.е. по часовой стрелке на экране): ``sweep = -360``, ``end_angle == start_angle``.
    """
    ax, ay = start
    bx, by = mid
    cx, cy = end
    if _same_nm(start, end):
        if _same_nm(start, mid):
            return None
        center = ((ax + bx) / 2.0, (ay + by) / 2.0)
        sa = angle_of(center, start)
        return ArcGeometry(center, distance(start, mid) / 2.0, sa, sa, -360.0)
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    center = (ux, uy)
    radius = distance(center, start)
    sa = angle_of(center, start)
    ma = angle_of(center, mid)
    ea = angle_of(center, end)
    # Направление обхода: от start к end через mid.
    ccw_to_mid = normalize_angle(ma - sa)
    ccw_to_end = normalize_angle(ea - sa)
    if ccw_to_mid <= ccw_to_end:
        sweep = ccw_to_end if ccw_to_end > 0 else 360.0
    else:
        sweep = -(360.0 - ccw_to_end) if ccw_to_end > 0 else -360.0
    return ArcGeometry(center, radius, sa, ea, sweep)


def arc_three_points(center: Point, start: Point, sweep: float) -> tuple[Point, Point, Point]:
    """Три точки (start, mid, end) дуги по центру, начальной точке и углу ``sweep``.

    Соглашение о знаке ``sweep`` — как в :class:`ArcGeometry` (положительный — против
    часовой стрелки на экране). Формат KiCad 5 ``(fp_arc (start C) (end S) (angle A))``
    и старый ``DA`` используют противоположный знак (положительный угол = по часовой на
    экране, см. ``EDA_SHAPE::SetArcAngleAndEnd``): вызывающая сторона передаёт ``-A``.
    """
    radius = distance(center, start)
    sa = angle_of(center, start)
    mid = point_at_angle(center, radius, sa + sweep / 2.0)
    end = point_at_angle(center, radius, sa + sweep)
    return ((round_mm(start[0]), round_mm(start[1])), mid, end)


def arc_bbox(start: Point, mid: Point, end: Point) -> BBox:
    """Габариты дуги (с учётом крайних точек окружности, попадающих в дугу)."""
    g = arc_from_three_points(start, mid, end)
    pts = [start, mid, end]
    if g is not None:
        cx, cy = g.center
        r = g.radius
        for quad, (px, py) in ((0.0, (cx + r, cy)), (90.0, (cx, cy - r)),
                               (180.0, (cx - r, cy)), (270.0, (cx, cy + r))):
            if angle_in_arc(quad, g.start_angle, g.sweep):
                pts.append((px, py))
    return BBox.of_points(pts)  # type: ignore[return-value]


def angle_in_arc(angle: float, start_angle: float, sweep: float) -> bool:
    """Лежит ли направление ``angle`` внутри дуги от ``start_angle`` на ``sweep`` градусов."""
    if sweep >= 0:
        return normalize_angle(angle - start_angle) <= sweep + EPS
    return normalize_angle(start_angle - angle) <= -sweep + EPS


def arc_points(start: Point, mid: Point, end: Point, segments: int | None = None) -> list[Point]:
    """Аппроксимация дуги ломаной (для отрисовки и SVG-экспорта)."""
    g = arc_from_three_points(start, mid, end)
    if g is None:
        return [start, end]
    if segments is None:
        segments = max(8, int(abs(g.sweep) / 5.0) + 1)
    out: list[Point] = []
    for i in range(segments + 1):
        a = g.start_angle + g.sweep * i / segments
        out.append(point_at_angle(g.center, g.radius, a))
    out[0] = start
    out[-1] = end
    return out


def bezier_points(p0: Point, p1: Point, p2: Point, p3: Point, segments: int = 24) -> list[Point]:
    """Точки кубической кривой Безье."""
    out: list[Point] = []
    for i in range(segments + 1):
        t = i / segments
        mt = 1.0 - t
        x = mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]
        out.append((x, y))
    return out


def polyline_length(points: Sequence[Point], closed: bool = False) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += distance(a, b)
    if closed and len(points) > 2:
        total += distance(points[-1], points[0])
    return total


def rect_corners(start: Point, end: Point) -> list[Point]:
    """Четыре угла прямоугольника по двум противоположным углам."""
    return [(start[0], start[1]), (end[0], start[1]), (end[0], end[1]), (start[0], end[1])]


def rotated_rect_bbox(center: Point, size_x: float, size_y: float, angle: float) -> BBox:
    """Габариты прямоугольника ``size_x × size_y`` с центром ``center``, повёрнутого на ``angle``."""
    hx, hy = size_x / 2.0, size_y / 2.0
    corners = [(center[0] - hx, center[1] - hy), (center[0] + hx, center[1] - hy),
               (center[0] + hx, center[1] + hy), (center[0] - hx, center[1] + hy)]
    if angle:
        corners = [rotate_point(c, angle, center) for c in corners]
    return BBox.of_points(corners)  # type: ignore[return-value]


def snap(value: float, grid: float) -> float:
    """Округлить к ближайшему узлу сетки ``grid``."""
    if grid <= 0:
        return value
    return round_mm(round(value / grid) * grid)
