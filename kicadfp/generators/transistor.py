"""Генератор транзисторов TO-92 с выводами в линию (``lab-generators.md`` §3.7): эталоны
``TO-92_Inline`` (шаг 1.27) и ``TO-92_Inline_Wide`` (шаг 2.54) библиотеки KiCad."""

from __future__ import annotations

import math

from ..model import Footprint
from ._common import (
    COURTYARD_OFFSET,
    FAB_WIDTH,
    SILK_WIDTH,
    add_arc,
    add_courtyard_rect,
    add_fab_reference,
    add_lines,
    add_pad,
    check_positive,
    clip_silk,
    finalize,
    new_footprint,
    num,
    pad_pair,
    set_texts,
)

__all__ = ["transistor", "transistor_inline"]

_C45 = math.cos(math.radians(45))


def _body(fp: Footprint, cx: float, r: float, layer: str, width: float) -> None:
    """Контур TO-92 (окружность радиуса ``r`` с центром ``(cx, 0)``, срезанная хордой снизу
    на ``y = r·sin45°``): две дуги (левая и правая половины, по часовой стрелке) и хорда."""
    def pt(angle: float) -> tuple[float, float]:
        a = math.radians(angle)
        return (cx + r * math.cos(a), -r * math.sin(a))

    left, top, right = pt(225.0), (cx, -r), pt(-45.0)
    add_arc(fp, left, pt(157.5), top, layer, width)
    add_arc(fp, top, pt(22.5), right, layer, width)
    add_lines(fp, [(left, right)], layer, width)


def transistor(pitch: float = 1.27, pad_size: float | tuple[float, float] | None = None,
               drill: float | None = None, body_radius: float = 2.48, pins: int = 3,
               name: str | None = None) -> Footprint:
    """Транзистор в корпусе TO-92 с выводами в линию (вид сверху: плоская сторона внизу).

    Шаг 1.27 (``TO-92_Inline``): площадки 1.05 × 1.5, отверстие 0.75, №1 ``rect``,
    остальные ``oval``. Шаг от 2 мм (``TO-92_Inline_Wide`` при 2.54): площадки 1.5 × 1.5,
    отверстие 0.8, №1 ``rect``, остальные ``circle``. Контур F.Fab/F.SilkS — дуги
    окружности корпуса и хорда плоской стороны (замкнутый контур; у KiCad хорды не
    замкнуты), шелкография обрезается у площадок; courtyard с отступом 0.25.

    Параметры:
        pitch: шаг выводов, мм (1.27 — узкий, 2.54 — широкий вариант).
        pad_size: размер площадки, мм: число или пара (по умолчанию 1.05 × 1.5 при шаге
            меньше 2 мм, иначе 1.5 × 1.5).
        drill: диаметр отверстия, мм (по умолчанию 0.75 при шаге меньше 2 мм, иначе 0.8).
        body_radius: радиус корпуса, мм.
        pins: число выводов (2 или больше).
        name: имя корпуса (по умолчанию TO-92_Inline, TO-92_Inline_Wide или
            TO-92_Inline_P{pitch}mm; при pins ≠ 3 — TO-92-{pins}_…).
    """
    check_positive("pitch", pitch)
    check_positive("body_radius", body_radius)
    if isinstance(pins, bool) or not isinstance(pins, int) or pins < 2:
        raise ValueError(f"pins: ожидается целое число не меньше 2, получено {pins!r}")
    p, r = float(pitch), float(body_radius)
    narrow = p < 2.0
    size = pad_pair(pad_size if pad_size is not None else ((1.05, 1.5) if narrow else 1.5))
    dr = float(drill) if drill is not None else (0.75 if narrow else 0.8)
    other = "oval" if narrow else "circle"

    if name is None:
        base = "TO-92" if pins == 3 else f"TO-92-{pins}"
        if abs(p - 1.27) < 1e-9:
            name = f"{base}_Inline"
        elif abs(p - 2.54) < 1e-9:
            name = f"{base}_Inline_Wide"
        else:
            name = f"{base}_Inline_P{p:.2f}mm"
    descr = (f"TO-92 leads in-line, {'narrow, oval pads' if narrow else 'wide'}, "
             f"drill {num(dr)}mm (see NXP sot054_po.pdf)")
    if pins != 3:
        descr = f"{pins} pins, " + descr
    tags = "to-92 sc-43 sc-43a sot54 PA33 transistor"
    fp = new_footprint(name, descr=descr, tags=tags)

    for i in range(pins):
        add_pad(fp, i + 1, i * p, 0.0, size, dr, "rect" if i == 0 else other)
    cx = (pins - 1) * p / 2
    _body(fp, cx, r, "F.Fab", FAB_WIDTH)
    _body(fp, cx, r + 0.12, "F.SilkS", SILK_WIDTH)
    clip_silk(fp)

    crt = add_courtyard_rect(fp, COURTYARD_OFFSET)
    set_texts(fp, (cx, crt.y1 - 0.83), (cx, crt.y2 + 0.78))
    add_fab_reference(fp, cx, 0.0)
    return finalize(fp)


#: Синоним :func:`transistor` (TO-92, выводы в линию).
transistor_inline = transistor
