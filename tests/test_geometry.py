"""Тесты вспомогательной геометрии (kicadfp.geometry)."""

import math

import pytest

from kicadfp.geometry import (
    BBox,
    angle_of,
    arc_bbox,
    arc_from_three_points,
    arc_points,
    arc_three_points,
    bezier_points,
    mirror_point,
    normalize_angle,
    normalize_angle_180,
    point_at_angle,
    polyline_length,
    rotate_point,
    rotated_rect_bbox,
    round_mm,
    snap,
)


def test_rotate_point_kicad_convention():
    # Положительный угол — против часовой стрелки на экране (ось Y вниз): (1,0) -> (0,-1)
    assert rotate_point((1, 0), 90) == (0.0, -1.0)
    assert rotate_point((1, 0), 180) == (-1.0, 0.0)
    assert rotate_point((1, 0), -90) == (0.0, 1.0)
    assert rotate_point((2, 1), 90, (1, 1)) == (1.0, 0.0)
    assert rotate_point((3.5, -2.25), 0) == (3.5, -2.25)


def test_mirror_point():
    assert mirror_point((2, 3), "x") == (-2.0, 3.0)
    assert mirror_point((2, 3), "y") == (2.0, -3.0)
    assert mirror_point((2, 3), "x", origin=1.0) == (0.0, 3.0)
    with pytest.raises(ValueError):
        mirror_point((0, 0), "z")


def test_angles():
    assert normalize_angle(370) == 10
    assert normalize_angle(-90) == 270
    assert normalize_angle(360) == 0
    assert normalize_angle_180(270) == -90
    assert normalize_angle_180(180) == 180
    assert angle_of((0, 0), (1, 0)) == 0
    assert angle_of((0, 0), (0, -1)) == 90  # вверх на экране
    assert angle_of((0, 0), (-1, 0)) == 180
    assert angle_of((0, 0), (0, 1)) == 270
    assert point_at_angle((0, 0), 2, 90) == (0.0, -2.0)


def test_arc_dip14_key_notch():
    # Выемка ключа DIP-14 из стандартной библиотеки (KiCad 6+): три точки
    g = arc_from_three_points((4.81, -1.33), (3.81, -0.33), (2.81, -1.33))
    assert g is not None
    assert g.center[0] == pytest.approx(3.81)
    assert g.center[1] == pytest.approx(-1.33)
    assert g.radius == pytest.approx(1.0)
    assert g.sweep == pytest.approx(-180.0)
    # обратное преобразование
    s, m, e = arc_three_points((3.81, -1.33), (4.81, -1.33), -180)
    assert m == pytest.approx((3.81, -0.33))
    assert e == pytest.approx((2.81, -1.33))
    # форма KiCad 5: (start C) (end S) (angle -180) -> sweep = +180 от точки S
    s5, m5, e5 = arc_three_points((3.81, -1.33), (2.81, -1.33), 180)
    assert m5 == pytest.approx((3.81, -0.33))
    assert e5 == pytest.approx((4.81, -1.33))


def test_arc_degenerate():
    assert arc_from_three_points((0, 0), (1, 0), (2, 0)) is None
    assert arc_points((0, 0), (1, 0), (2, 0)) == [(0, 0), (2, 0)]


def test_arc_bbox_includes_extreme():
    # четверть окружности от (1,0) через 45° до (0,-1) — bbox x:[0,1], y:[-1,0]
    b = arc_bbox((1, 0), (math.sqrt(0.5), -math.sqrt(0.5)), (0, -1))
    assert b.x1 == pytest.approx(0)
    assert b.y1 == pytest.approx(-1)
    assert b.x2 == pytest.approx(1)
    assert b.y2 == pytest.approx(0)
    # полуокружность снизу: включает нижнюю точку (0,1)
    b = arc_bbox((1, 0), (0, 1), (-1, 0))
    assert b.y2 == pytest.approx(1)
    assert b.y1 == pytest.approx(0)


def test_arc_points_endpoints():
    pts = arc_points((4.81, -1.33), (3.81, -0.33), (2.81, -1.33), segments=10)
    assert pts[0] == (4.81, -1.33)
    assert pts[-1] == (2.81, -1.33)
    assert len(pts) == 11
    assert pts[5] == pytest.approx((3.81, -0.33))


def test_bezier_and_length():
    pts = bezier_points((0, 0), (0, 1), (1, 1), (1, 0), segments=4)
    assert pts[0] == (0, 0) and pts[-1] == pytest.approx((1, 0))
    assert polyline_length([(0, 0), (3, 4)]) == 5
    assert polyline_length([(0, 0), (1, 0), (1, 1)], closed=True) == pytest.approx(2 + math.sqrt(2))


def test_bbox_helpers():
    b = BBox.of_points([(1, 2), (-1, 5)])
    assert b == BBox(-1, 2, 1, 5)
    assert b.width == 2 and b.height == 3 and b.center == (0, 3.5)
    assert b.union(BBox(0, 0, 0, 0)) == BBox(-1, 0, 1, 5)
    assert b.inflated(1) == BBox(-2, 1, 2, 6)
    assert b.contains((0, 3)) and not b.contains((2, 3))
    assert BBox.of_points([]) is None
    assert rotated_rect_bbox((0, 0), 2, 1, 90) == pytest.approx(BBox(-0.5, -1, 0.5, 1))


def test_round_and_snap():
    assert round_mm(-0.0000001) == 0.0
    assert str(round_mm(-0.0)) == "0.0"
    assert round_mm(1.23456789) == 1.234568
    assert snap(1.2499, 1.25) == 1.25
    assert snap(1.0, 0) == 1.0
