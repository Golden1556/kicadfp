"""Корпуса лабораторной работы: ``dip14`` (микросхема К555ТВ6), ``mlt`` (резистор МЛТ),
``snp8`` (разъём СНП, 8 контактов) — ``docs/dev/lab-generators.md`` §2 (ТЗ прил. Г,
сценарий 5).

Общие решения (lab-generators.md §2.2): сетка 1.25 мм; площадки ``thru_hole`` 1.3 × 1.3,
отверстие 0.8, площадка 1 ``rect``, остальные ``circle``, слои ``*.Cu *.Mask``; шелкография
0.12, F.Fab 0.1, F.CrtYd 0.05; Reference ``REF**`` на F.SilkS, Value = имя на F.Fab (1 × 1,
0.15); контур и тексты — на 1.25 от площадок/контура; начало координат по умолчанию —
центр блока площадок (``origin="center"``, как в ``My_lib.mod``), ``origin="pin1"`` — в
площадке 1 (KLC F7.2). Шелкография по умолчанию обрезается у площадок (``clip=True``,
зазор до меди ≥ 0.2), полный контур задания остаётся на F.Fab.

Отступление от ``architecture.md`` §11 (решение L9 lab-generators.md): текст
``${REFERENCE}`` на F.Fab в лабораторных корпусах **не создаётся** (центр dip14 занят
вертикальным Value по требованию методички).
"""

from __future__ import annotations

from ..model import Footprint
from ._common import (
    CONNECTOR_COURTYARD_OFFSET,
    COURTYARD_OFFSET,
    FAB_WIDTH,
    SILK_WIDTH,
    add_arc,
    add_courtyard_rect,
    add_lines,
    add_mounting_hole,
    add_pad,
    check_positive,
    clip_silk,
    finalize,
    new_footprint,
    pad_pair,
    set_texts,
)

__all__ = ["lab_dip14", "lab_mlt", "lab_snp8", "LAB_GRID"]

#: Сетка методички, мм: контур и тексты отстоят на одну клетку.
LAB_GRID = 1.25

_ORIGINS = ("center", "pin1")


def _check_origin(origin: str) -> None:
    if origin not in _ORIGINS:
        raise ValueError(f"origin: ожидается одно из {_ORIGINS}, получено {origin!r}")


def _to_pin1(fp: Footprint, origin: str) -> None:
    """При ``origin="pin1"`` перенести начало координат в площадку 1."""
    if origin == "pin1":
        p1 = fp.pad("1")
        dx, dy = -p1.x, -p1.y
        if dx or dy:
            fp.move(dx, dy)


def lab_dip14(name: str = "dip14", pins: int = 14, pitch: float = 2.5, row_pitch: float = 7.5,
              body_width: float = 5.0, pad_size: float = 1.3, drill: float = 0.8,
              notch_radius: float = 0.75, clip: bool = True,
              origin: str = "center") -> Footprint:
    """Корпус dip14 лабораторной работы (микросхема К555ТВ6, lab-generators.md §2.3).

    14 площадок в два ряда по 7, нумерация «U» (1 слева вверху вниз до 7, 8 справа внизу
    вверх до 14), шаг 2.5, ряды 7.5; контур — прямоугольник шириной 5 между рядами, на 1.25
    выше/ниже крайних площадок, ключ — полукруглая выемка сверху (радиус 0.75); Reference
    над контуром, Value в центре вертикально (90°).

    Параметры:
        name: имя корпуса.
        pins: число выводов (чётное).
        pitch: шаг выводов в ряду, мм.
        row_pitch: расстояние между рядами, мм.
        body_width: ширина контура корпуса, мм.
        pad_size: диаметр (сторона) площадок, мм.
        drill: диаметр отверстий, мм.
        notch_radius: радиус выемки-ключа, мм.
        clip: обрезать шелкографию у площадок (зазор до меди не меньше 0.2 мм).
        origin: начало координат: center — центр блока площадок, pin1 — площадка 1.
    """
    if isinstance(pins, bool) or not isinstance(pins, int) or pins < 2 or pins % 2:
        raise ValueError(f"pins: ожидается чётное число не меньше 2, получено {pins!r}")
    for what, v in (("pitch", pitch), ("row_pitch", row_pitch), ("body_width", body_width),
                    ("notch_radius", notch_radius)):
        check_positive(what, v)
    _check_origin(origin)
    size = pad_pair(pad_size)
    n = pins // 2
    y0 = (n - 1) * pitch / 2
    bx, by, r = body_width / 2, y0 + LAB_GRID, float(notch_radius)
    if r >= bx:
        raise ValueError("notch_radius: выемка шире корпуса")
    if pins == 14:
        descr, tags = "Корпус К555ТВ6 DIP14", f"{name} K555TB6"
    else:
        descr, tags = f"Корпус DIP{pins} (лабораторная работа)", f"{name} DIP{pins}"
    fp = new_footprint(name, descr=descr, tags=tags)

    for i in range(n):
        add_pad(fp, i + 1, -row_pitch / 2, -y0 + i * pitch, size, drill,
                "rect" if i == 0 else "circle")
    for j in range(n):
        add_pad(fp, n + j + 1, row_pitch / 2, y0 - j * pitch, size, drill, "circle")

    add_lines(fp, [((-bx, -by), (-r, -by)), ((r, -by), (bx, -by)), ((bx, -by), (bx, by)),
                   ((bx, by), (-bx, by)), ((-bx, by), (-bx, -by))], "F.SilkS", SILK_WIDTH)
    add_arc(fp, (r, -by), (0.0, -by + r), (-r, -by), "F.SilkS", SILK_WIDTH)
    fp.new_rect((-bx, -by), (bx, by), "F.Fab", FAB_WIDTH)
    if clip:
        clip_silk(fp)
    set_texts(fp, (0.0, -(by + LAB_GRID)), (0.0, 0.0, 90.0))
    _to_pin1(fp, origin)
    add_courtyard_rect(fp, COURTYARD_OFFSET)
    return finalize(fp)


def lab_mlt(name: str = "mlt", pitch: float = 10.0, body_length: float = 7.5,
            body_width: float = 2.5, pad_size: float = 1.3, drill: float = 0.8,
            clip: bool = True, origin: str = "center") -> Footprint:
    """Корпус резистора МЛТ лабораторной работы (lab-generators.md §2.4).

    Две площадки на расстоянии 10, контур 7.5 × 2.5 по центру и выводные линии от
    площадок к контуру (на F.SilkS — обрезанные у площадок), Reference над контуром,
    Value под ним.

    Параметры:
        name: имя корпуса.
        pitch: расстояние между площадками, мм.
        body_length: длина контура корпуса, мм.
        body_width: ширина контура корпуса, мм.
        pad_size: диаметр (сторона) площадок, мм.
        drill: диаметр отверстий, мм.
        clip: обрезать шелкографию у площадок (зазор до меди не меньше 0.2 мм).
        origin: начало координат: center — середина между площадками, pin1 — площадка 1.
    """
    for what, v in (("pitch", pitch), ("body_length", body_length),
                    ("body_width", body_width)):
        check_positive(what, v)
    _check_origin(origin)
    size = pad_pair(pad_size)
    x, bx, by = pitch / 2, body_length / 2, body_width / 2
    if bx >= x:
        raise ValueError("body_length: корпус длиннее расстояния между площадками")
    fp = new_footprint(name, descr="Корпус резистора МЛТ", tags=f"{name} resistor")
    add_pad(fp, 1, -x, 0.0, size, drill, "rect")
    add_pad(fp, 2, x, 0.0, size, drill, "circle")

    add_lines(fp, [((-bx, -by), (bx, -by)), ((bx, -by), (bx, by)), ((bx, by), (-bx, by)),
                   ((-bx, by), (-bx, -by)), ((-x, 0.0), (-bx, 0.0)), ((bx, 0.0), (x, 0.0))],
              "F.SilkS", SILK_WIDTH)
    fp.new_rect((-bx, -by), (bx, by), "F.Fab", FAB_WIDTH)
    add_lines(fp, [((-x, 0.0), (-bx, 0.0)), ((bx, 0.0), (x, 0.0))], "F.Fab", FAB_WIDTH)
    if clip:
        clip_silk(fp)
    set_texts(fp, (0.0, -(by + LAB_GRID)), (0.0, by + LAB_GRID))
    _to_pin1(fp, origin)
    add_courtyard_rect(fp, COURTYARD_OFFSET)
    return finalize(fp)


def lab_snp8(name: str = "snp8", rows: int = 2, per_row: int = 4, pitch: float = 2.5,
             row_pitch: float = 5.0, body_width: float = 12.5, body_height: float = 25.0,
             hole: float = 3.0, hole_inset: float = 2.5, pads_offset_y: float = 0.0,
             numbering: str = "by_row", pad_size: float = 1.3, drill: float = 0.8,
             clip: bool = True, origin: str = "center") -> Footprint:
    """Корпус разъёма СНП, 8 контактов, лабораторной работы (lab-generators.md §2.5).

    Два ряда по 4 площадки (шаг 2.5, ряды 5), площадка 1 квадратная слева вверху; контур
    12.5 × 25 справа от площадок, левая сторона — по правому ряду; два неметаллизированных
    монтажных отверстия Ø3 на вертикальной оси контура, в 2.5 от верхнего и нижнего краёв;
    Reference над контуром, Value под ним; courtyard с отступом 0.5 (разъём).

    Параметры:
        name: имя корпуса.
        rows: число рядов площадок.
        per_row: число площадок в ряду.
        pitch: шаг площадок в ряду, мм.
        row_pitch: расстояние между рядами, мм.
        body_width: ширина контура корпуса, мм.
        body_height: высота контура корпуса, мм.
        hole: диаметр монтажных отверстий, мм.
        hole_inset: расстояние от центра монтажного отверстия до края контура, мм.
        pads_offset_y: смещение блока площадок по вертикали относительно центра контура, мм
            (−1.25 — вариант примера ТЗ прил. В.2).
        numbering: нумерация: by_row (синоним row) — 1…4 левый ряд, 5…8 правый; zigzag
            (синоним column) — поперёк рядов, как PinHeader_2x04 KiCad.
        pad_size: диаметр (сторона) площадок, мм.
        drill: диаметр отверстий площадок, мм.
        clip: обрезать шелкографию у площадок (зазор до меди не меньше 0.2 мм).
        origin: начало координат: center — центр блока площадок, pin1 — площадка 1.
    """
    from .pin_header import pin_number

    for what, v in (("rows", rows), ("per_row", per_row)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"{what}: ожидается целое число не меньше 1, получено {v!r}")
    for what, v in (("pitch", pitch), ("row_pitch", row_pitch), ("body_width", body_width),
                    ("body_height", body_height), ("hole", hole), ("hole_inset", hole_inset)):
        check_positive(what, v)
    _check_origin(origin)
    pin_number(numbering, 0, 0, rows, per_row)  # проверка значения numbering
    size = pad_pair(pad_size)
    y0 = (per_row - 1) * pitch / 2
    xs = (rows - 1) * row_pitch
    left = xs / 2
    right = left + body_width
    cx = (left + right) / 2
    by = body_height / 2
    dy = float(pads_offset_y)
    fp = new_footprint(
        name, descr="Корпус разъёма СНП 8 контактов с двумя монтажными отверстиями 3 мм"
        if (rows * per_row == 8 and abs(hole - 3.0) < 1e-9) else
        f"Корпус разъёма СНП {rows * per_row} контактов с двумя монтажными отверстиями "
        f"{hole:g} мм", tags=f"{name} connector")

    for c in range(rows):
        for k in range(per_row):
            number = pin_number(numbering, c, k, rows, per_row)
            add_pad(fp, number, -xs / 2 + c * row_pitch, -y0 + k * pitch + dy, size, drill,
                    "rect" if number == 1 else "circle")
    for hy in (-(by - hole_inset), by - hole_inset):
        add_mounting_hole(fp, cx, hy, hole)

    add_lines(fp, [((left, -by), (right, -by)), ((right, -by), (right, by)),
                   ((right, by), (left, by)), ((left, by), (left, -by))], "F.SilkS", SILK_WIDTH)
    fp.new_rect((left, -by), (right, by), "F.Fab", FAB_WIDTH)
    if clip:
        clip_silk(fp)
    set_texts(fp, (cx, -(by + LAB_GRID)), (cx, by + LAB_GRID))
    _to_pin1(fp, origin)
    add_courtyard_rect(fp, CONNECTOR_COURTYARD_OFFSET)
    return finalize(fp)
