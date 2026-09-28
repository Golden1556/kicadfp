"""Генератор корпусов DIP (``lab-generators.md`` §3.2): геометрия ``DIP-N_W*mm`` библиотеки
KiCad v8 (kicad-footprint-generator, ``footprint_scripts_DIP.py``)."""

from __future__ import annotations

from ..model import Footprint
from ._common import (
    COURTYARD_OFFSET,
    FAB_WIDTH,
    SILK_WIDTH,
    TEXT_OFFSET,
    add_arc,
    add_courtyard_rect,
    add_fab_reference,
    add_pad_row,
    add_polyline,
    check_positive,
    finalize,
    new_footprint,
    num,
    pad_pair,
    set_texts,
)

__all__ = ["dip", "dip_body_width"]

#: Ширина корпуса по расстоянию между рядами (``klt …/DIP/legacy/footprint.py:44-121``).
_BODY_WIDTH = {7.62: 6.35, 10.16: 6.35, 15.24: 14.73, 22.86: 22.35, 25.4: 24.89}


def dip_body_width(row_pitch: float, pins: int) -> float:
    """Ширина корпуса DIP по таблице KiCad: 7.62 → 6.35; 10.16 → 6.35 (22 и 24 вывода —
    9.14); 15.24 → 14.73; 22.86 → 22.35; 25.4 → 24.89; иначе (решение kicadfp)
    ``row_pitch − 1.27``."""
    for w, bw in _BODY_WIDTH.items():
        if abs(row_pitch - w) < 1e-6:
            if w == 10.16 and pins in (22, 24):
                return 9.14
            return bw
    return round(row_pitch - 1.27, 6)


def dip(pins: int = 14, pitch: float = 2.54, row_pitch: float = 7.62,
        pad_size: float | tuple[float, float] = (1.6, 1.6), drill: float = 0.8,
        body_width: float | None = None, first_square: bool = True, pad_shape: str = "oval",
        name: str | None = None, body_length: float | None = None) -> Footprint:
    """Корпус DIP: два ряда выводов, нумерация «U» (1 слева вверху вниз, далее справа снизу
    вверх), начало координат — площадка 1 (KLC F7.2).

    Геометрия — как у ``DIP-N_W7.62mm`` KiCad v8: площадки 1.6 × 1.6 (№1 ``rect``, остальные
    ``oval``), F.Fab со скосом у вывода 1, F.SilkS с выемкой-ключом (дуга внутрь), F.CrtYd с
    отступом 0.25 на сетке 0.01, Reference над корпусом, Value под ним, ``${REFERENCE}`` в
    центре (повёрнут на 90°, если корпус выше, чем шире). ``dip()`` = ``DIP-14_W7.62mm``.

    Параметры:
        pins: число выводов (чётное, не меньше 2).
        pitch: шаг выводов в ряду, мм.
        row_pitch: расстояние между рядами (по центрам площадок), мм.
        pad_size: размер площадки, мм: число или пара (ширина, высота).
        drill: диаметр отверстия, мм.
        body_width: ширина корпуса, мм (по умолчанию — по таблице KiCad, иначе
            row_pitch − 1.27).
        first_square: площадка 1 прямоугольная (rect).
        pad_shape: форма остальных площадок (oval, circle, rect).
        name: имя корпуса (по умолчанию DIP-{pins}_W{row_pitch}mm[_P{pitch}mm]).
        body_length: длина корпуса, мм (по умолчанию — (pins/2 − 1)·pitch + pitch, т.е.
            выступ pitch/2 за крайние выводы).
    """
    if isinstance(pins, bool) or not isinstance(pins, int) or pins < 2 or pins % 2:
        raise ValueError(f"pins: ожидается чётное число не меньше 2, получено {pins!r}")
    check_positive("pitch", pitch)
    check_positive("row_pitch", row_pitch)
    if pad_shape not in ("oval", "circle", "rect", "roundrect"):
        raise ValueError(f"pad_shape: недопустимая форма {pad_shape!r}")
    px, py = pad_pair(pad_size)
    n = pins // 2
    p, w = float(pitch), float(row_pitch)
    bw = dip_body_width(w, pins) if body_width is None else float(body_width)
    check_positive("body_width", bw)
    if body_length is None:
        over = p / 2
        h = (n - 1) * p + 2 * over
    else:
        check_positive("body_length", body_length)
        h = float(body_length)
        over = (h - (n - 1) * p) / 2
    if name is None:
        name = f"DIP-{pins}_W{round(w, 2)}mm"
        if abs(p - 2.54) > 1e-9:
            name += f"_P{round(p, 2)}mm"
    mils = int(round(w / 2.54 * 100, 6))
    descr = f"{pins}-lead though-hole mounted DIP package, row spacing {num(w)}mm ({mils} mils)"
    if abs(p - 2.54) > 1e-9:
        descr += f", pin pitch {num(p)}mm"
    tags = f"THT DIP DIL PDIP {num(p)}mm {num(w)}mm {mils}mil"
    fp = new_footprint(name, descr=descr, tags=tags)

    # площадки: 1..n вниз в x = 0, n+1..2n вверх в x = W
    first = "rect" if first_square else pad_shape
    add_pad_row(fp, range(1, n + 1), (0.0, 0.0), (0.0, p), (px, py), drill, shape=pad_shape,
                first_shape=first)
    add_pad_row(fp, range(n + 1, pins + 1), (w, (n - 1) * p), (0.0, -p), (px, py), drill,
                shape=pad_shape)

    # F.Fab: контур со скосом у вывода 1
    left, top = (w - bw) / 2, -over
    b = min(1.0, 0.25 * min(bw, h))
    add_polyline(fp, [(left + b, top), (left + bw, top), (left + bw, top + h), (left, top + h),
                      (left, top + b), (left + b, top)], "F.Fab", FAB_WIDTH)

    # F.SilkS: прямоугольник на 0.06 снаружи F.Fab (не ближе 0.36 к площадкам) с выемкой
    so = 0.06
    hs = h + 2 * so
    ws = min(bw + 2 * so, w - px - 0.72)
    ls = (w - ws) / 2
    ts = top - so
    cx = w / 2
    add_polyline(fp, [(cx - 1, ts), (ls, ts), (ls, ts + hs), (ls + ws, ts + hs), (ls + ws, ts),
                      (cx + 1, ts)], "F.SilkS", SILK_WIDTH)
    add_arc(fp, (cx + 1, ts), (cx, ts + 1), (cx - 1, ts), "F.SilkS", SILK_WIDTH)

    add_courtyard_rect(fp, COURTYARD_OFFSET)
    set_texts(fp, (cx, ts - TEXT_OFFSET), (cx, ts + hs + TEXT_OFFSET))
    add_fab_reference(fp, cx, top + h / 2, 0.0 if bw > h else 90.0)
    return finalize(fp)

