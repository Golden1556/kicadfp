"""Построители типовых символов (в милах, Y вверх). Используются
spec.py и напрямую из Python.

Соглашения (см. docs/conventions.md):
- точки подключения выводов лежат на сетке ``grid`` (50 мил по умолчанию);
- вывод слева от корпуса имеет ориентацию R, справа — L, сверху — D, снизу — U
  (буква = направление линии ОТ точки подключения К корпусу);
- Reference над корпусом, Value под корпусом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import model as M


def snap(v: float, grid: int = 50) -> int:
    if not grid:
        return int(round(v))
    return int(round(v / grid)) * grid


@dataclass
class PinSpec:
    name: str
    number: str
    side: str = 'left'                       # left | right | top | bottom
    etype: M.PinType = M.PinType.INPUT
    shape: M.PinShape = M.PinShape.NONE
    unit: int = 1
    convert: int = 1
    visible: bool = True
    length: Optional[int] = None
    at: Optional[Tuple[int, int]] = None     # точка подключения; None = авто
    row: Optional[int] = None                # номер строки/столбца на стороне (0 = первый), None = по порядку
    name_size: Optional[int] = None
    num_size: Optional[int] = None


_SIDE_ORIENT = {'left': M.PinOrient.RIGHT, 'right': M.PinOrient.LEFT,
                'top': M.PinOrient.DOWN, 'bottom': M.PinOrient.UP}


def box_symbol(name: str, reference: str, pins: Sequence[PinSpec], *,
               unit_count: int = 1, width: Optional[int] = None, height: Optional[int] = None,
               pin_length: int = 200, pitch: int = 100, grid: int = 50,
               text_size: int = 50, pin_name_offset: int = 40, line_width: int = 0,
               fill: M.Fill = M.Fill.NONE, value_visible: bool = True,
               show_pin_numbers: bool = True, show_pin_names: bool = True,
               power: bool = False, units_locked: bool = False,
               field_size: int = M.DEFAULT_SIZE_TEXT, extra_items: Sequence[M.DrawItem] = (),
               body_dividers: Sequence[int] = (), pin_gap: Optional[int] = None) -> M.Component:
    """Прямоугольный корпус с выводами по сторонам.

    Выводы каждой стороны раскладываются в порядке перечисления с шагом
    ``pitch`` (для секций — одинаковая раскладка для каждой секции, общие
    выводы unit=0 участвуют в каждой). Если ``width``/``height`` не заданы —
    подбираются под число выводов. ``body_dividers`` — X-координаты
    вертикальных линий-разделителей внутри корпуса (как у К555ТВ6).
    """
    def side_pins(side: str, unit: int) -> List[PinSpec]:
        return [p for p in pins if p.side == side and p.at is None and (p.unit in (0, unit))]

    n_left = max((len(side_pins('left', u)) for u in range(1, unit_count + 1)), default=0)
    n_right = max((len(side_pins('right', u)) for u in range(1, unit_count + 1)), default=0)
    n_top = max((len(side_pins('top', u)) for u in range(1, unit_count + 1)), default=0)
    n_bottom = max((len(side_pins('bottom', u)) for u in range(1, unit_count + 1)), default=0)
    gap = pin_gap if pin_gap is not None else pitch
    if height is None:
        rows = max(n_left, n_right)
        height = snap(max(rows + 1, 2) * pitch, grid)
    if width is None:
        cols = max(n_top, n_bottom)
        width = snap(max(cols + 1, 2) * pitch, grid)
        width = max(width, snap(4 * pitch, grid))
    hw, hh = snap(width / 2, grid), snap(height / 2, grid)
    comp = M.Component(name, reference, pin_name_offset, show_pin_numbers, show_pin_names,
                       unit_count, units_locked, power, value_visible)
    comp.fields.append(M.Field(M.REFERENCE, reference, 0, hh + field_size + 20, field_size,
                               visible=bool(reference)))
    comp.fields.append(M.Field(M.VALUE, name, 0, -hh - field_size - 20, field_size,
                               visible=value_visible))
    comp.items.append(M.Rect(0, 1, -hw, hh, hw, -hh, line_width, fill))
    for xd in body_dividers:
        comp.items.append(M.Polyline(0, 1, [(xd, hh), (xd, -hh)], line_width))
    comp.items.extend(extra_items)

    def place(p: PinSpec, x: int, y: int) -> None:
        length = p.length if p.length is not None else pin_length
        comp.items.append(M.Pin(p.unit, p.convert, p.name, str(p.number), x, y, length,
                                _SIDE_ORIENT[p.side],
                                p.num_size if p.num_size is not None else text_size,
                                p.name_size if p.name_size is not None else text_size,
                                p.etype, p.shape, p.visible))

    placed = set()
    for unit in range(1, unit_count + 1):
        for side, count in (('left', n_left), ('right', n_right)):
            sp = side_pins(side, unit)
            rows_here = max(count, n_left, n_right)
            y0 = snap(hh - (height - (rows_here - 1) * pitch) / 2, grid) if count else 0
            for i, p in enumerate(sp):
                if id(p) in placed:
                    continue
                placed.add(id(p))
                length = p.length if p.length is not None else pin_length
                x = -hw - length if side == 'left' else hw + length
                place(p, x, y0 - (p.row if p.row is not None else i) * pitch)
        for side, count in (('top', n_top), ('bottom', n_bottom)):
            sp = side_pins(side, unit)
            x0 = snap(-hw + (width - (count - 1) * pitch) / 2, grid) if count else 0
            for i, p in enumerate(sp):
                if id(p) in placed:
                    continue
                placed.add(id(p))
                length = p.length if p.length is not None else pin_length
                y = hh + length if side == 'top' else -hh - length
                place(p, x0 + (p.row if p.row is not None else i) * pitch, y)
    for p in pins:
        if p.at is not None:
            place(p, p.at[0], p.at[1])
    return comp


def power_symbol(name: str, net: Optional[str] = None, style: str = 'gnd', *,
                 reference: str = '#PWR', length: int = 0, bar: int = 300, height: int = 200,
                 line_width: int = 0, bar_width: int = 0, arm_height: Optional[int] = None,
                 text_size: int = 50, value_visible: bool = False,
                 field_size: int = M.DEFAULT_SIZE_TEXT) -> M.Component:
    """Символ питания: один невидимый вывод типа W (Power In) с именем цепи.

    style 'gnd' — черта длиной ``bar`` на высоте -height от точки подключения
    (вывод идёт вниз); 'vcc' — стрелка-галка: ножка вниз на ``height``, от вершины
    плечи шириной ``bar`` возвращаются вверх на ``arm_height`` (по умолчанию =
    height, т.е. к уровню точки подключения) — как рис. 13 методички;
    'bar_up' — черта сверху (вывод идёт вверх).
    """
    net = net or name
    comp = M.Component(name, reference, 0, False, False, 1, False, True, value_visible)
    below = style in ('gnd', 'vcc')
    comp.fields.append(M.Field(M.REFERENCE, reference, 0, -height - 100 if below else height + 100,
                               field_size, visible=False))
    comp.fields.append(M.Field(M.VALUE, name, 0, -height - 200 if below else height + 200,
                               field_size, visible=value_visible))
    half = bar // 2
    if style == 'gnd':
        comp.items.append(M.Polyline(0, 1, [(0, 0), (0, -height)], line_width))
        comp.items.append(M.Polyline(0, 1, [(-half, -height), (half, -height)], bar_width or line_width))
        # вывод невидимый (иначе не создаётся глобальная метка), линия к черте — от точки подключения вниз
        comp.items.append(M.Pin(0, 1, net, '1', 0, 0, length, M.PinOrient.DOWN, text_size, text_size,
                                M.PinType.POWER_IN, M.PinShape.NONE, False))
    elif style == 'vcc':
        # рис. 13 методички: точка подключения вверху, ножка вниз к вершине галки,
        # плечи возвращаются вверх к уровню точки подключения; общая высота = height
        arm = arm_height if arm_height is not None else height
        comp.items.append(M.Polyline(0, 1, [(0, 0), (0, -height)], line_width))
        comp.items.append(M.Polyline(0, 1, [(-half, -height + arm), (0, -height), (half, -height + arm)],
                                     bar_width or line_width))
        comp.items.append(M.Pin(0, 1, net, '1', 0, 0, length, M.PinOrient.DOWN, text_size, text_size,
                                M.PinType.POWER_IN, M.PinShape.NONE, False))
    elif style == 'bar_up':
        comp.items.append(M.Polyline(0, 1, [(0, 0), (0, height)], line_width))
        comp.items.append(M.Polyline(0, 1, [(-half, height), (half, height)], bar_width or line_width))
        comp.items.append(M.Pin(0, 1, net, '1', 0, 0, length, M.PinOrient.UP, text_size, text_size,
                                M.PinType.POWER_IN, M.PinShape.NONE, False))
    else:
        raise ValueError('unknown power style %r' % style)
    return comp


def two_pin_box(name: str, reference: str, *, width: int = 800, height: int = 150,
                pin_length: int = 200, etype: M.PinType = M.PinType.PASSIVE,
                names: Tuple[str, str] = ('1', '2'), numbers: Tuple[str, str] = ('1', '2'),
                text_size: int = 50, line_width: int = 0, value_visible: bool = True,
                show_pin_names: bool = False, show_pin_numbers: bool = True,
                field_size: int = M.DEFAULT_SIZE_TEXT) -> M.Component:
    """Горизонтальный двухвыводной элемент (резистор по ГОСТ — прямоугольник)."""
    hw, hh = width // 2, height // 2
    comp = M.Component(name, reference, 0, show_pin_numbers, show_pin_names, 1, False, False, value_visible)
    comp.fields.append(M.Field(M.REFERENCE, reference, 0, hh + field_size, field_size))
    comp.fields.append(M.Field(M.VALUE, name, 0, -hh - field_size, field_size, visible=value_visible))
    comp.items.append(M.Rect(0, 1, -hw, hh, hw, -hh, line_width))
    comp.items.append(M.Pin(1, 1, names[0], numbers[0], -hw - pin_length, 0, pin_length,
                            M.PinOrient.RIGHT, text_size, text_size, etype))
    comp.items.append(M.Pin(1, 1, names[1], numbers[1], hw + pin_length, 0, pin_length,
                            M.PinOrient.LEFT, text_size, text_size, etype))
    return comp


def table_connector(name: str, reference: str, rows: Sequence[Tuple[str, str]], *,
                    width: int = 1000, row_height: int = 200, pin_length: int = 200,
                    net_col_width: Optional[int] = None, header: Tuple[str, str] = ('Net', 'Pin'),
                    etype: M.PinType = M.PinType.BIDI, text_size: int = 50, line_width: int = 0,
                    value_visible: bool = False, field_size: int = M.DEFAULT_SIZE_TEXT,
                    grid: int = 50, pins_side: str = 'right') -> M.Component:
    """Разъём-«таблица» (рис. 11а методички): столбцы Net | Pin, по строке на
    контакт; выводы справа (или слева). ``rows`` — [(имя цепи, номер), ...];
    имя цепи может быть пустым."""
    n = len(rows)
    total_h = row_height * (n + 1)
    hw = snap(width / 2, grid)
    top = snap(total_h / 2, grid)
    bottom = top - total_h
    ncw = net_col_width if net_col_width is not None else snap(width * 0.65, grid)
    xdiv = -hw + ncw
    comp = M.Component(name, reference, 0, True, False, 1, False, False, value_visible)
    comp.fields.append(M.Field(M.REFERENCE, 0, 0, top + field_size + 20, field_size))
    comp.fields[-1].text = reference
    comp.fields.append(M.Field(M.VALUE, name, 0, bottom - field_size - 20, field_size, visible=value_visible))
    comp.items.append(M.Rect(0, 1, -hw, top, hw, bottom, line_width))
    comp.items.append(M.Polyline(0, 1, [(xdiv, top), (xdiv, bottom)], line_width))
    for i in range(n + 1):
        y = top - row_height * (i + 1)
        if i < n:
            comp.items.append(M.Polyline(0, 1, [(-hw, y), (hw, y)], line_width))
    yh = top - row_height // 2
    comp.items.append(M.Text(0, 1, header[0], (-hw + xdiv) // 2, yh, text_size))
    comp.items.append(M.Text(0, 1, header[1], (xdiv + hw) // 2, yh, text_size))
    for i, (net, num) in enumerate(rows):
        yc = top - row_height * (i + 1) - row_height // 2
        if net:
            comp.items.append(M.Text(0, 1, net, (-hw + xdiv) // 2, yc, text_size))
        comp.items.append(M.Text(0, 1, str(num), (xdiv + hw) // 2, yc, text_size))
        yp = snap(yc, grid)
        if pins_side == 'right':
            comp.items.append(M.Pin(1, 1, str(num), str(num), hw + pin_length, yp, pin_length,
                                    M.PinOrient.LEFT, text_size, text_size, etype))
        else:
            comp.items.append(M.Pin(1, 1, str(num), str(num), -hw - pin_length, yp, pin_length,
                                    M.PinOrient.RIGHT, text_size, text_size, etype))
    comp.show_pin_numbers = False   # номера уже нарисованы текстом в таблице
    return comp
