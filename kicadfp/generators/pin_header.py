"""Генератор штыревых разъёмов (``lab-generators.md`` §3.3): геометрия
``PinHeader_{rows}x{cols}_P2.54mm_Vertical`` библиотеки KiCad v8/v9
(``def_makePinHeadStraight.py``) и пример ТЗ прил. В.2."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..model import Footprint
from ._common import (
    CONNECTOR_COURTYARD_OFFSET,
    FAB_WIDTH,
    SILK_WIDTH,
    TEXT_OFFSET,
    add_courtyard_rect,
    add_fab_reference,
    add_lines,
    add_mounting_hole,
    add_pad,
    add_polyline,
    check_positive,
    clip_silk,
    finalize,
    new_footprint,
    num,
    pad_pair,
    set_texts,
)

__all__ = ["pin_header", "NUMBERING", "pin_number"]

#: Допустимые схемы нумерации и их синонимы: ``zigzag`` (= ``column``) — по «столбцам»
#: поперёк рядов, как ``PinHeader_2xNN`` KiCad (1 и 2 — первая пара); ``by_row``
#: (= ``row``) — вдоль каждого ряда (1…cols в первом ряду, далее следующий ряд).
NUMBERING = {"zigzag": "zigzag", "column": "zigzag", "by_column": "zigzag",
             "by_row": "by_row", "row": "by_row"}


def pin_number(numbering: str, r: int, k: int, rows: int, cols: int) -> int:
    """Номер площадки ряда ``r`` (с нуля) и позиции ``k`` в ряду (с нуля):
    ``zigzag`` — ``k·rows + r + 1``, ``by_row`` — ``r·cols + k + 1``."""
    mode = NUMBERING.get(numbering)
    if mode is None:
        raise ValueError(f"numbering: ожидается одно из {sorted(NUMBERING)}, "
                         f"получено {numbering!r}")
    return k * rows + r + 1 if mode == "zigzag" else r * cols + k + 1


def _holes(mounting_holes: Iterable[Sequence[float]] | None) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for h in mounting_holes or ():
        vals = list(h)
        if len(vals) != 3:
            raise ValueError(f"mounting_holes: ожидаются тройки (x, y, диаметр), получено {h!r}")
        x, y, d = (float(v) for v in vals)
        check_positive("диаметр монтажного отверстия", d)
        out.append((x, y, d))
    return out


def pin_header(rows: int = 1, cols: int = 4, pitch: float = 2.54,
               row_pitch: float | None = None, pad_size: float | tuple[float, float] = 1.7,
               drill: float = 1.0, first_square: bool = True, pad_shape: str = "oval",
               numbering: str = "zigzag",
               mounting_holes: list[tuple[float, float, float]] | None = None,
               name: str | None = None) -> Footprint:
    """Прямой штыревой разъём: ``rows`` рядов вдоль X через ``row_pitch``, в каждом ряду
    ``cols`` площадок вдоль Y (вниз) через ``pitch``; начало координат — площадка 1.

    Геометрия — как у ``PinHeader_1x04``/``2x04_P2.54mm_Vertical`` KiCad: площадки 1.7 × 1.7
    (№1 ``rect``, остальные ``oval``), F.Fab со скосом у вывода 1, F.SilkS на 0.06 снаружи
    F.Fab с угловым маркером у вывода 1, F.CrtYd с отступом 0.5 (разъём), Reference над
    разъёмом, Value под ним, ``${REFERENCE}`` по центру (90°). Монтажные отверстия
    (``np_thru_hole``) входят в courtyard; шелкография обрезается вокруг площадок и
    отверстий (lab-generators.md §1.5).

    Пример ТЗ прил. В.2: ``pin_header(rows=2, cols=4, pitch=2.5, row_pitch=5.0,
    pad_size=1.3, drill=0.8, first_square=True, mounting_holes=[(11.25, -5.0, 3.0),
    (11.25, 15.0, 3.0)], name="snp8")``.

    Параметры:
        rows: число рядов (вдоль оси X).
        cols: число площадок в ряду (вдоль оси Y).
        pitch: шаг площадок в ряду, мм.
        row_pitch: расстояние между рядами, мм (по умолчанию равно pitch).
        pad_size: размер площадки, мм: число или пара (ширина, высота).
        drill: диаметр отверстия, мм.
        first_square: площадка 1 прямоугольная (rect).
        pad_shape: форма остальных площадок (oval, circle, rect).
        numbering: нумерация: zigzag (синоним column) — поперёк рядов, как PinHeader_2xNN
            KiCad; by_row (синоним row) — вдоль каждого ряда.
        mounting_holes: монтажные отверстия [(x, y, диаметр), …] в координатах корпуса
            (от площадки 1); только через JSON/Python.
        name: имя корпуса (по умолчанию PinHeader_{rows}x{cols}_P{pitch}mm_Vertical
            [_W{row_pitch}mm]).
    """
    for what, v in (("rows", rows), ("cols", cols)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"{what}: ожидается целое число не меньше 1, получено {v!r}")
    check_positive("pitch", pitch)
    p = float(pitch)
    rp = p if row_pitch is None else float(row_pitch)
    check_positive("row_pitch", rp)
    if pad_shape not in ("oval", "circle", "rect", "roundrect"):
        raise ValueError(f"pad_shape: недопустимая форма {pad_shape!r}")
    size = pad_pair(pad_size)
    holes = _holes(mounting_holes)
    pin_number(numbering, 0, 0, rows, cols)  # проверка значения numbering

    if name is None:
        name = f"PinHeader_{rows}x{cols:02d}_P{p:.2f}mm_Vertical"
        if abs(rp - p) > 1e-9:
            name += f"_W{round(rp, 2)}mm"
    if rows == 1:
        kind, kind_t = "single row", "single row"
    elif rows == 2:
        kind, kind_t = "double rows", "double row"
    else:
        kind, kind_t = f"{rows} rows", f"{rows} row"
    descr = f"Through hole straight pin header, {rows}x{cols:02d}, {p:.2f}mm pitch, {kind}"
    tags = f"Through hole pin header THT {rows}x{cols:02d} {p:.2f}mm {kind_t}"
    if abs(rp - p) > 1e-9:
        descr += f", row spacing {num(rp)}mm"
    if holes:
        descr += f", {len(holes)} mounting hole{'s' if len(holes) > 1 else ''}"
    fp = new_footprint(name, descr=descr, tags=tags)

    for x, y, d in holes:
        add_mounting_hole(fp, x, y, d)
    for r in range(rows):
        for k in range(cols):
            number = pin_number(numbering, r, k, rows, cols)
            shape = "rect" if (number == 1 and first_square) else pad_shape
            add_pad(fp, number, r * rp, k * p, size, drill, shape)

    # F.Fab: прямоугольник со скосом у площадки 1
    bw = (rows - 1) * rp + p
    left = (rows - 1) * rp / 2 - bw / 2
    top = -p / 2
    right = left + bw
    bottom = (cols - 1) * p + p / 2
    ch = bw / 4
    add_polyline(fp, [(left + ch, top), (right, top), (right, bottom), (left, bottom),
                      (left, top + ch), (left + ch, top)], "F.Fab", FAB_WIDTH)

    # F.SilkS: угол-маркер у площадки 1 и контур, начинающийся ниже/правее неё
    so = 0.06
    sl, st, sr, sb = left - so, top - so, right + so, bottom + so
    segs = [((sl, st), (0.0, st)), ((sl, 0.0), (sl, st)), ((sl, p / 2), (sl, sb))]
    if rows == 1:
        segs += [((sl, p / 2), (sr, p / 2)), ((sl, sb), (sr, sb)), ((sr, p / 2), (sr, sb))]
    else:
        segs += [((sl, p / 2), (rp / 2, p / 2)), ((sl, sb), (sr, sb)),
                 ((rp / 2, st), (sr, st)), ((rp / 2, p / 2), (rp / 2, st)),
                 ((sr, st), (sr, sb))]
    add_lines(fp, segs, "F.SilkS", SILK_WIDTH)
    clip_silk(fp)

    add_courtyard_rect(fp, CONNECTOR_COURTYARD_OFFSET)
    xc = (rows - 1) * rp / 2
    set_texts(fp, (xc, st - TEXT_OFFSET), (xc, sb + TEXT_OFFSET))
    add_fab_reference(fp, xc, (cols - 1) * p / 2, 90.0)
    return finalize(fp)
