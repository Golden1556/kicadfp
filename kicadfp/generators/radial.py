"""Генератор радиальных конденсаторов (``lab-generators.md`` §3.5–3.6): неполярный дисковый
(``C_Disc_D5.0mm_W2.5mm_P5.00mm``) и полярный электролитический
(``CP_Radial_D5.0mm_P2.50mm``) — геометрия ``makeResistorRadial``
(``footprint_scripts_resistorlike.py``) библиотеки KiCad v8/v9."""

from __future__ import annotations

import math

from ..geometry import round_mm
from ..model import Footprint
from ._common import (
    COURTYARD_OFFSET,
    CRTYD_WIDTH,
    FAB_WIDTH,
    SILK_WIDTH,
    TEXT_OFFSET,
    add_courtyard_rect,
    add_fab_reference,
    add_lines,
    add_pad,
    ceil_grid,
    check_positive,
    clip_silk,
    fab_reference_size,
    finalize,
    new_footprint,
    num,
    set_texts,
)

__all__ = ["capacitor_radial", "hatch_segments"]

_COS30 = math.cos(math.radians(30))
_SIN30 = 0.5


def _round_away(v: float, step: float = 0.001) -> float:
    """Округление к шагу ``step`` «от нуля» (как у KiCad при штриховке: 2.57725 → 2.578)."""
    q = abs(v) / step
    r = math.ceil(q) * step
    return round_mm(math.copysign(r, v)) if r else 0.0


def hatch_segments(cx: float, rs: float, pad_xs: list[float], pad_size: float,
                   step: float = 0.04) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Штриховка отрицательной половины электролитического конденсатора (F.SilkS,
    ``footprint_scripts_resistorlike.py:1625-1634``): вертикальные отрезки от центра
    ``cx`` вправо с шагом ``step`` (накопительно), длиной ``2·(sqrt(rs² − x²) − 0.04)``;
    из них вырезаются квадраты со стороной ``pad_size + 0.48`` вокруг площадок; локальные
    координаты округляются на 0.001 «от нуля»."""
    half = pad_size / 2 + 0.24
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    x = 0.0
    while x < rs:
        hc = math.sqrt(max(rs * rs - x * x, 0.0)) - 0.04
        if hc > 0:
            lx = _round_away(x)
            xs = round_mm(cx + lx)
            ys = _round_away(hc)
            cut = any(abs(cx + x - px) < half for px in pad_xs)
            if not cut:
                out.append(((xs, -ys), (xs, ys)))
            elif ys > half:
                hy = _round_away(half)
                out.append(((xs, -ys), (xs, -hy)))
                out.append(((xs, hy), (xs, ys)))
        x += step
    return out


def capacitor_radial(pitch: float = 5.0, diameter: float = 5.0, width: float = 2.5,
                     drill: float = 0.8, pad_size: float | None = None,
                     polarized: bool = False, hatch: bool = True,
                     name: str | None = None) -> Footprint:
    """Радиальный конденсатор (выводы в одну сторону).

    ``polarized=False`` — неполярный дисковый (``C_Disc_D…_W…_P…``): обе площадки
    ``circle``, корпус — прямоугольник ``diameter × width``; шелкография на 0.12 снаружи
    F.Fab, обрезанная у площадок. ``polarized=True`` — электролитический (``CP_Radial_D…_P…``):
    площадка 1 (+) ``rect``, корпус — окружность ``diameter``, знаки «+» на F.Fab и F.SilkS,
    штриховка отрицательной половины (``hatch``), область размещения — окружность.

    Параметры:
        pitch: расстояние между выводами, мм.
        diameter: диаметр корпуса (у дискового — длина диска), мм.
        width: толщина дискового корпуса, мм (для полярного не используется).
        drill: диаметр отверстия, мм.
        pad_size: диаметр площадки, мм (по умолчанию 2 × drill).
        polarized: полярный (электролитический) конденсатор.
        hatch: штриховка отрицательной половины (только для полярного).
        name: имя корпуса (по умолчанию C_Disc_D{d}mm_W{w}mm_P{pitch}mm или
            CP_Radial_D{d}mm_P{pitch}mm).
    """
    check_positive("pitch", pitch)
    check_positive("diameter", diameter)
    check_positive("drill", drill)
    rm, dd = float(pitch), float(diameter)
    pd = 2 * float(drill) if pad_size is None else float(pad_size)
    check_positive("pad_size", pd)
    cx = rm / 2
    if not polarized:
        check_positive("width", width)
        hh = float(width)
        if name is None:
            name = f"C_Disc_D{dd:.1f}mm_W{hh:.1f}mm_P{rm:.2f}mm"
        descr = (f"C, Disc series, Radial, pin pitch={rm:.2f}mm, diameter*width="
                 f"{num(dd)}*{num(hh)}mm^2, Capacitor")
        tags = (f"C Disc series Radial pin pitch {rm:.2f}mm diameter {num(dd)}mm width "
                f"{num(hh)}mm Capacitor")
        fp = new_footprint(name, descr=descr, tags=tags)
        add_pad(fp, 1, 0.0, 0.0, pd, drill, "circle")
        add_pad(fp, 2, rm, 0.0, pd, drill, "circle")
        fp.new_rect((round_mm(cx - dd / 2), -hh / 2), (round_mm(cx + dd / 2), hh / 2), "F.Fab",
                    FAB_WIDTH)
        so = 0.12
        x1, x2, y1, y2 = cx - dd / 2 - so, cx + dd / 2 + so, -hh / 2 - so, hh / 2 + so
        add_lines(fp, [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)),
                       ((x1, y2), (x1, y1))], "F.SilkS", SILK_WIDTH)
        clip_silk(fp)
        crt = add_courtyard_rect(fp, COURTYARD_OFFSET)
        set_texts(fp, (cx, crt.y1 - TEXT_OFFSET), (cx, crt.y2 + TEXT_OFFSET))
        s, t = fab_reference_size(dd, hh)
        add_fab_reference(fp, cx, 0.0, size=s, thickness=t)
        return finalize(fp)

    if name is None:
        name = f"CP_Radial_D{dd:.1f}mm_P{rm:.2f}mm"
    descr = (f"CP, Radial series, Radial, pin pitch={rm:.2f}mm, diameter={num(dd)}mm, "
             f"Electrolytic Capacitor")
    tags = (f"CP Radial series Radial pin pitch {rm:.2f}mm diameter {num(dd)}mm "
            f"Electrolytic Capacitor")
    fp = new_footprint(name, descr=descr, tags=tags)
    add_pad(fp, 1, 0.0, 0.0, pd, drill, "rect")
    add_pad(fp, 2, rm, 0.0, pd, drill, "circle")
    fp.new_circle((cx, 0.0), dd / 2, "F.Fab", FAB_WIDTH)
    rs = (dd + 0.24) / 2
    fp.new_circle((cx, 0.0), round_mm(rs), "F.SilkS", SILK_WIDTH)
    clip_silk(fp)

    # знаки «+» у площадки 1
    ps = dd / 10
    for layer, width_, k in (("F.Fab", FAB_WIDTH, (dd - 0.05 - ps) / 2 - ps / 10),
                             ("F.SilkS", SILK_WIDTH, (2 * rs + 0.06 + ps) / 2 + ps / 10)):
        px, py = cx - k * _COS30, -k * _SIN30
        add_lines(fp, [((px - ps / 2, py), (px + ps / 2, py)),
                       ((px, py - ps / 2), (px, py + ps / 2))], layer, width_)
    if hatch:
        add_lines(fp, hatch_segments(cx, rs, [0.0, rm], pd), "F.SilkS", SILK_WIDTH)

    r_crt = max(dd / 2 + COURTYARD_OFFSET,
                math.hypot(rm / 2 + pd / 2 + 0.06, pd / 2 + 0.06) + COURTYARD_OFFSET)
    r_crt = ceil_grid(r_crt)
    fp.new_circle((cx, 0.0), r_crt, "F.CrtYd", CRTYD_WIDTH)
    ty = (max(dd, pd) + 0.5) / 2 + TEXT_OFFSET
    set_texts(fp, (cx, -ty), (cx, ty))
    s, t = fab_reference_size(dd, dd)
    add_fab_reference(fp, cx, 0.0, size=s, thickness=t)
    return finalize(fp)
