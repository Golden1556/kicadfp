"""Генераторы выводных (осевых) корпусов для горизонтального монтажа
(``lab-generators.md`` §3.4): резисторы, конденсаторы, диоды. Геометрия —
``makeResistorAxialHorizontal`` (``footprint_scripts_resistorlike.py``) библиотеки KiCad v8/v9."""

from __future__ import annotations

from ..model import Footprint
from ._common import (
    COURTYARD_OFFSET,
    FAB_WIDTH,
    SILK_WIDTH,
    TEXT_OFFSET,
    TEXT_SIZE,
    TEXT_THICKNESS,
    add_courtyard_rect,
    add_fab_reference,
    add_lines,
    add_pad,
    check_positive,
    fab_reference_size,
    finalize,
    new_footprint,
    num,
    set_texts,
)

__all__ = ["resistor", "capacitor_axial", "diode"]

#: Смещение контура шелкографии от F.Fab у выводных корпусов KiCad.
_SILK_OFFSET = 0.12


def _axial(prefix: str, kind: str, pitch: float, body_length: float, body_diameter: float,
           drill: float, pad_size: float | None, first_shape: str, series: str,
           name: str | None, diode_band: bool) -> Footprint:
    """Общий построитель резистора/конденсатора/диода (lab-generators.md §3.4)."""
    check_positive("pitch", pitch)
    check_positive("body_length", body_length)
    check_positive("body_diameter", body_diameter)
    check_positive("drill", drill)
    rm, bl, bd = float(pitch), float(body_length), float(body_diameter)
    pd = 2 * float(drill) if pad_size is None else float(pad_size)
    check_positive("pad_size", pd)
    if not series:
        raise ValueError("series: ожидается непустая строка")

    if name is None:
        if prefix == "D":
            name = f"D_{series}_P{rm:.2f}mm_Horizontal"
        else:
            name = f"{prefix}_{series}_L{bl:.1f}mm_D{bd:.1f}mm_P{rm:.2f}mm_Horizontal"
    descr = (f"{kind}, {series}, Horizontal, pin pitch={num(rm)}mm, "
             f"length*diameter={num(bl)}*{num(bd)}mm^2")
    tags = (f"{kind} {series} Horizontal pin pitch {num(rm)}mm length {num(bl)}mm "
            f"diameter {num(bd)}mm")
    fp = new_footprint(name, descr=descr, tags=tags)

    add_pad(fp, 1, 0.0, 0.0, pd, drill, first_shape)
    add_pad(fp, 2, rm, 0.0, pd, drill, "oval")

    # F.Fab: корпус и выводы
    lf = (rm - bl) / 2
    fp.new_rect((lf, -bd / 2), (lf + bl, bd / 2), "F.Fab", FAB_WIDTH)
    if lf > 1e-9:
        add_lines(fp, [((0.0, 0.0), (lf, 0.0)), ((rm, 0.0), (lf + bl, 0.0))], "F.Fab", FAB_WIDTH)

    # F.SilkS: прямоугольник на 0.12 снаружи F.Fab, скобки или две горизонтали у площадок
    so = _SILK_OFFSET
    hs, ws = bd + 2 * so, bl + 2 * so
    ls, ts = lf - so, -hs / 2
    lim = pd / 2 + 0.24
    if ls >= lim:
        fp.new_rect((round(ls, 6), round(ts, 6)), (round(ls + ws, 6), round(ts + hs, 6)),
                    "F.SilkS", SILK_WIDTH)
    elif ts < -lim:
        y0 = lim
        add_lines(fp, [((ls, -y0), (ls, ts)), ((ls, ts), (ls + ws, ts)),
                       ((ls + ws, ts), (ls + ws, -y0)),
                       ((ls, y0), (ls, -ts)), ((ls, -ts), (ls + ws, -ts)),
                       ((ls + ws, -ts), (ls + ws, y0))], "F.SilkS", SILK_WIDTH)
    else:
        add_lines(fp, [((ls, ts), (ls + ws, ts)), ((ls, ts + hs), (ls + ws, ts + hs))],
                  "F.SilkS", SILK_WIDTH)
    if lim < ls:
        add_lines(fp, [((lim, 0.0), (ls, 0.0)), ((rm - lim, 0.0), (ls + ws, 0.0))],
                  "F.SilkS", SILK_WIDTH)

    ref_x = rm / 2
    if diode_band:
        # полоса катода: три линии на F.Fab и на F.SilkS, «K» у площадки 1
        xb = lf + 0.15 * bl
        add_lines(fp, [((xb + dx, -bd / 2), (xb + dx, bd / 2)) for dx in (-0.1, 0.0, 0.1)],
                  "F.Fab", FAB_WIDTH)
        add_lines(fp, [((xb + dx, ts), (xb + dx, ts + hs)) for dx in (-0.12, 0.0, 0.12)],
                  "F.SilkS", SILK_WIDTH)
        for layer in ("F.SilkS", "F.Fab"):
            fp.new_text("K", "user", 0.0, round(-pd / 2 - 1, 6), layer, size=TEXT_SIZE,
                        thickness=TEXT_THICKNESS)
    if prefix == "D":
        ref_x = rm / 2 + 0.075 * bl

    add_courtyard_rect(fp, COURTYARD_OFFSET)
    set_texts(fp, (rm / 2, ts - TEXT_OFFSET), (rm / 2, hs / 2 + TEXT_OFFSET))
    s, t = fab_reference_size(bl, bd)
    add_fab_reference(fp, ref_x, 0.0, size=s, thickness=t)
    return finalize(fp)


def resistor(pitch: float = 10.16, body_length: float = 6.3, body_diameter: float = 2.5,
             drill: float = 0.8, pad_size: float | None = None, first_square: bool = False,
             series: str = "Axial", name: str | None = None) -> Footprint:
    """Выводной резистор, горизонтальный монтаж.

    Геометрия — как у ``R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal`` KiCad v8
    (``series="Axial_DIN0207"``). Площадка 1 ``circle`` (``rect`` при ``first_square``),
    площадка 2 ``oval``, размер площадки по умолчанию — 2 × отверстие.

    Параметры:
        pitch: расстояние между выводами, мм.
        body_length: длина корпуса, мм.
        body_diameter: диаметр корпуса, мм.
        drill: диаметр отверстия, мм.
        pad_size: диаметр площадки, мм (по умолчанию 2 × drill).
        first_square: площадка 1 прямоугольная (rect).
        series: серия корпуса в имени (Axial, Axial_DIN0207, …).
        name: имя корпуса (по умолчанию R_{series}_L{L}mm_D{D}mm_P{pitch}mm_Horizontal).
    """
    return _axial("R", "Resistor", pitch, body_length, body_diameter, drill, pad_size,
                  "rect" if first_square else "circle", series, name, False)


def capacitor_axial(pitch: float = 7.5, body_length: float = 3.8, body_diameter: float = 2.6,
                    drill: float = 0.8, pad_size: float | None = None,
                    first_square: bool = False, series: str = "Axial",
                    name: str | None = None) -> Footprint:
    """Выводной (осевой) конденсатор, горизонтальный монтаж.

    Геометрия — как у ``C_Axial_L3.8mm_D2.6mm_P7.50mm_Horizontal`` KiCad v8.

    Параметры:
        pitch: расстояние между выводами, мм.
        body_length: длина корпуса, мм.
        body_diameter: диаметр корпуса, мм.
        drill: диаметр отверстия, мм.
        pad_size: диаметр площадки, мм (по умолчанию 2 × drill).
        first_square: площадка 1 прямоугольная (rect).
        series: серия корпуса в имени.
        name: имя корпуса (по умолчанию C_{series}_L{L}mm_D{D}mm_P{pitch}mm_Horizontal).
    """
    return _axial("C", "Capacitor", pitch, body_length, body_diameter, drill, pad_size,
                  "rect" if first_square else "circle", series, name, False)


def diode(pitch: float = 7.62, body_length: float = 4.0, body_diameter: float = 2.0,
          drill: float = 0.8, pad_size: float | None = None, series: str = "DO-35_SOD27",
          cathode_band: bool = True, name: str | None = None) -> Footprint:
    """Выводной диод, горизонтальный монтаж.

    Геометрия — как у ``D_DO-35_SOD27_P7.62mm_Horizontal`` KiCad. Площадка 1 — катод, ``rect``; полоса катода на F.Fab и F.SilkS (три линии) и
    надпись «K» у площадки 1 на обоих слоях; ``${REFERENCE}`` смещён от полосы.

    Параметры:
        pitch: расстояние между выводами, мм.
        body_length: длина корпуса, мм.
        body_diameter: диаметр корпуса, мм.
        drill: диаметр отверстия, мм.
        pad_size: размер площадки, мм (по умолчанию 2 × drill).
        series: серия корпуса в имени (DO-35_SOD27, DO-41_SOD81, …).
        cathode_band: рисовать полосу катода и надписи «K».
        name: имя корпуса (по умолчанию D_{series}_P{pitch}mm_Horizontal).
    """
    return _axial("D", "Diode", pitch, body_length, body_diameter, drill, pad_size, "rect",
                  series, name, bool(cathode_band))
