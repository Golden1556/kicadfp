"""Простой SVG-рендер библиотечных символов и схем — для визуальной проверки
без KiCad. Повторяет геометрию отрисовки EESchema (lib_pin.cpp:844-1055,
DrawPinTexts :1067-1267, матрицу компонента), без претензий на пиксельную
точность шрифтов.
"""

from __future__ import annotations

import html
import math
from typing import List, Optional, Tuple

from . import model as M
from . import sch as S

INVERT_PIN_RADIUS = 35
CLOCK_PIN_DIM = 40
IEEE_SYMBOL_PIN_DIM = 40
NONLOGIC_PIN_DIM = 30
TARGET_PIN_DIAM = 12
TXTMARGE = 10


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


class _Canvas:
    def __init__(self):
        self.parts: List[str] = []
        self.minx = self.miny = 10 ** 9
        self.maxx = self.maxy = -10 ** 9

    def _bb(self, *pts):
        for x, y in pts:
            self.minx, self.maxx = min(self.minx, x), max(self.maxx, x)
            self.miny, self.maxy = min(self.miny, y), max(self.maxy, y)

    def line(self, x1, y1, x2, y2, color='#800000', width=6):
        self._bb((x1, y1), (x2, y2))
        self.parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="%d" stroke-linecap="round"/>'
                          % (x1, y1, x2, y2, color, width))

    def poly(self, pts, color='#800000', width=6, fill='none', close=False):
        self._bb(*pts)
        d = ' '.join('%d,%d' % p for p in pts)
        tag = 'polygon' if close else 'polyline'
        self.parts.append('<%s points="%s" stroke="%s" stroke-width="%d" fill="%s" stroke-linejoin="round"/>'
                          % (tag, d, color, width, fill))

    def rect(self, x1, y1, x2, y2, color='#800000', width=6, fill='none'):
        self._bb((x1, y1), (x2, y2))
        self.parts.append('<rect x="%d" y="%d" width="%d" height="%d" stroke="%s" stroke-width="%d" fill="%s"/>'
                          % (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1), color, width, fill))

    def circle(self, cx, cy, r, color='#800000', width=6, fill='none'):
        self._bb((cx - r, cy - r), (cx + r, cy + r))
        self.parts.append('<circle cx="%d" cy="%d" r="%d" stroke="%s" stroke-width="%d" fill="%s"/>'
                          % (cx, cy, r, color, width, fill))

    def arc(self, cx, cy, r, a1, a2, color='#800000', width=6):
        # a1,a2 в десятых градуса, экранные (Y вниз), против часовой в математическом смысле
        x1 = cx + r * math.cos(math.radians(a1 / 10)); y1 = cy - r * math.sin(math.radians(a1 / 10))
        x2 = cx + r * math.cos(math.radians(a2 / 10)); y2 = cy - r * math.sin(math.radians(a2 / 10))
        delta = (a2 - a1) % 3600
        large = 1 if delta > 1800 else 0
        self._bb((cx - r, cy - r), (cx + r, cy + r))
        self.parts.append('<path d="M %.1f %.1f A %d %d 0 %d 0 %.1f %.1f" stroke="%s" stroke-width="%d" fill="none"/>'
                          % (x1, y1, r, r, large, x2, y2, color, width))

    def text(self, x, y, s, size, color='#008080', hj='C', vj='C', vertical=False, italic=False, bold=False):
        anchor = {'L': 'start', 'C': 'middle', 'R': 'end'}[hj]
        base = {'T': 'hanging', 'C': 'central', 'B': 'alphabetic'}[vj]
        tr = ' transform="rotate(-90 %d %d)"' % (x, y) if vertical else ''
        style = ('font-style:italic;' if italic else '') + ('font-weight:bold;' if bold else '')
        # надчёркивание: ~фрагмент~
        parts = s.split('~')
        inner = ''
        for i, p in enumerate(parts):
            if p == '':
                continue
            if i % 2 == 1:
                inner += '<tspan text-decoration="overline">%s</tspan>' % _esc(p)
            else:
                inner += _esc(p)
        self._bb((x - size * len(s) * 0.4, y - size / 2), (x + size * len(s) * 0.4, y + size / 2))
        self.parts.append('<text x="%d" y="%d" font-size="%d" font-family="monospace" fill="%s" text-anchor="%s" '
                          'dominant-baseline="%s" style="%s"%s>%s</text>' % (x, y, size * 1.2, color, anchor, base, style, tr, inner))

    def svg(self, margin=200, scale=0.25) -> str:
        if self.minx > self.maxx:
            self.minx = self.miny = 0; self.maxx = self.maxy = 100
        w = self.maxx - self.minx + 2 * margin
        h = self.maxy - self.miny + 2 * margin
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="%d %d %d %d">'
                '<rect x="%d" y="%d" width="%d" height="%d" fill="white"/>%s</svg>'
                % (w * scale, h * scale, self.minx - margin, self.miny - margin, w, h,
                   self.minx - margin, self.miny - margin, w, h, ''.join(self.parts)))


def _draw_pin(cv: _Canvas, pin: M.Pin, m: S.Transform, ox: int, oy: int, comp: M.Component, show_hidden=True):
    if not pin.visible and not show_hidden:
        return
    color = '#800000' if pin.visible else '#c0c0c0'
    px, py = S.transform_point(m, pin.x, pin.y)
    px += ox; py += oy
    # ориентация после трансформации (ReturnPinDrawOrient)
    ex, ey = {M.PinOrient.UP: (0, 1), M.PinOrient.DOWN: (0, -1), M.PinOrient.LEFT: (-1, 0), M.PinOrient.RIGHT: (1, 0)}[pin.orient]
    tx, ty = S.transform_point(m, ex, ey)
    if tx == 0:
        orient = 'D' if ty > 0 else 'U'
    else:
        orient = 'R' if tx > 0 else 'L'
    ln = pin.length
    mapx = mapy = 0
    x1, y1 = px, py
    if orient == 'U':
        y1 = py - ln; mapy = 1
    elif orient == 'D':
        y1 = py + ln; mapy = -1
    elif orient == 'L':
        x1 = px - ln; mapx = 1
    else:
        x1 = px + ln; mapx = -1
    if pin.shape & M.PinShape.INVERT:
        cv.circle(mapx * INVERT_PIN_RADIUS + x1, mapy * INVERT_PIN_RADIUS + y1, INVERT_PIN_RADIUS, color)
        cv.line(mapx * INVERT_PIN_RADIUS * 2 + x1, mapy * INVERT_PIN_RADIUS * 2 + y1, px, py, color)
    else:
        cv.line(x1, y1, px, py, color)
    if pin.shape & M.PinShape.CLOCK:
        if mapy == 0:
            cv.poly([(x1, y1 + CLOCK_PIN_DIM), (x1 - mapx * CLOCK_PIN_DIM, y1), (x1, y1 - CLOCK_PIN_DIM)], color)
        else:
            cv.poly([(x1 + CLOCK_PIN_DIM, y1), (x1, y1 - mapy * CLOCK_PIN_DIM), (x1 - CLOCK_PIN_DIM, y1)], color)
    if pin.etype is M.PinType.NC:
        d = TARGET_PIN_DIAM
        cv.line(px - d, py - d, px + d, py + d, color); cv.line(px + d, py - d, px - d, py + d, color)
    else:
        cv.circle(px, py, TARGET_PIN_DIAM, color, 2)
    # тексты (DrawPinTexts)
    inside = comp.pin_name_offset
    name = pin.name if pin.name and pin.name != '~' else ''
    num = pin.number if pin.number != '~' else ''
    ns, zs = pin.name_size, pin.num_size
    if inside:
        if orient in 'LR':
            if name and comp.show_pin_names:
                if orient == 'R':
                    cv.text(x1 + inside, y1, name, ns, hj='L')
                else:
                    cv.text(x1 - inside, y1, name, ns, hj='R')
            if num and comp.show_pin_numbers:
                cv.text((x1 + px) // 2, y1 - TXTMARGE, num, zs, color='#808000', vj='B')
        else:
            if orient == 'D':
                if name and comp.show_pin_names:
                    cv.text(x1, y1 + inside, name, ns, hj='R', vertical=True)
            else:
                if name and comp.show_pin_names:
                    cv.text(x1, y1 - inside, name, ns, hj='L', vertical=True)
            if num and comp.show_pin_numbers:
                cv.text(x1 - TXTMARGE, (y1 + py) // 2, num, zs, color='#808000', vj='B', vertical=True)
    else:
        if orient in 'LR':
            if name and comp.show_pin_names:
                cv.text((x1 + px) // 2, y1 - TXTMARGE, name, ns, vj='B')
            if num and comp.show_pin_numbers:
                cv.text((x1 + px) // 2, y1 + TXTMARGE, num, zs, color='#808000', vj='T')
        else:
            if name and comp.show_pin_names:
                cv.text(x1 - TXTMARGE, (y1 + py) // 2, name, ns, vj='B', vertical=True)
            if num and comp.show_pin_numbers:
                cv.text(x1 + TXTMARGE, (y1 + py) // 2, num, zs, color='#808000', vj='T', vertical=True)


def draw_component(cv: _Canvas, comp: M.Component, unit: int = 1, convert: int = 1,
                   m: S.Transform = (1, 0, 0, -1), ox: int = 0, oy: int = 0,
                   fields: bool = True, show_hidden_pins: bool = True):
    def tp(x, y):
        a, b = S.transform_point(m, x, y)
        return a + ox, b + oy
    for it in comp.items:
        if unit and it.unit and it.unit != unit:
            continue
        if convert and it.convert and it.convert != convert:
            continue
        w = it.width if getattr(it, 'width', 0) else 6
        if isinstance(it, M.Rect):
            (x1, y1), (x2, y2) = tp(it.x1, it.y1), tp(it.x2, it.y2)
            cv.rect(x1, y1, x2, y2, width=w, fill='#ffffc0' if it.fill is M.Fill.BACKGROUND else 'none')
        elif isinstance(it, (M.Polyline, M.Bezier)):
            cv.poly([tp(*p) for p in it.points], width=w)
        elif isinstance(it, M.Circle):
            cx, cy = tp(it.cx, it.cy)
            cv.circle(cx, cy, it.radius, width=w)
        elif isinstance(it, M.Arc):
            cx, cy = tp(it.cx, it.cy)
            # приближённо: только для единичной матрицы без поворота
            cv.arc(cx, cy, it.radius, it.t1, it.t2, width=w)
        elif isinstance(it, M.Text):
            if it.hidden:
                continue
            x, y = tp(it.x, it.y)
            cv.text(x, y, it.text, it.size, color='#800080', hj=it.hjust.value, vj=it.vjust.value,
                    vertical=it.vertical, italic=it.italic, bold=it.bold)
        elif isinstance(it, M.Pin):
            _draw_pin(cv, it, m, ox, oy, comp, show_hidden_pins)
    if fields:
        for f in comp.fields:
            if not f.visible or not f.text:
                continue
            x, y = tp(f.x, f.y)
            text = f.text
            if f.id == M.REFERENCE and comp.unit_count > 1:
                text += chr(ord('A') + unit - 1)
            cv.text(x, y, text, f.size, color='#008080', hj=f.hjust.value, vj=f.vjust.value, vertical=f.vertical)


def render_component(comp: M.Component, unit: int = 1, convert: int = 1) -> str:
    cv = _Canvas()
    draw_component(cv, comp, unit, convert)
    cv.line(-30, 0, 30, 0, '#0000ff', 2); cv.line(0, -30, 0, 30, '#0000ff', 2)   # якорь
    return cv.svg()


def render_library(lib: M.Library) -> str:
    """Все компоненты (каждая секция) в одну картинку."""
    cv = _Canvas()
    x = 0
    for c in lib.components:
        for u in range(1, c.unit_count + 1):
            sub = _Canvas()
            draw_component(sub, c, u, 1)
            w = sub.maxx - sub.minx + 600
            ox = x - sub.minx + 300
            draw_component(cv, c, u, 1, ox=ox, oy=-sub.miny)
            cv.text(ox + (sub.maxx + sub.minx) / 2, -sub.miny + sub.maxy + 200, '%s%s' % (c.name, ('' if c.unit_count == 1 else ' unit %d' % u)), 60, color='#000000')
            x += w
    return cv.svg()


def render_schematic(sch: S.Schematic, lib: M.Library) -> str:
    cv = _Canvas()
    w_, h_ = S.PAGE_SIZES.get(sch.page, (11700, 8267))
    cv.rect(0, 0, w_, h_, '#c0c0c0', 4)
    for it in sch.items:
        if isinstance(it, S.Wire):
            color = '#008000' if it.layer == 'Wire' else '#0000ff' if it.layer == 'Bus' else '#0000a0'
            cv.line(it.x1, it.y1, it.x2, it.y2, color, 6 if it.layer != 'Bus' else 12)
        elif isinstance(it, S.BusEntry):
            cv.line(it.x, it.y, it.x + it.dx, it.y + it.dy, '#0000ff' if it.bus else '#008000', 6)
        elif isinstance(it, S.Junction):
            cv.circle(it.x, it.y, 20, '#008000', 2, fill='#008000')
        elif isinstance(it, S.NoConnect):
            cv.line(it.x - 20, it.y - 20, it.x + 20, it.y + 20, '#0000ff', 6)
            cv.line(it.x + 20, it.y - 20, it.x - 20, it.y + 20, '#0000ff', 6)
        elif isinstance(it, S.Note):
            for i, ln in enumerate(it.text.split('\n')):
                cv.text(it.x, it.y + i * it.size * 1.3, ln, it.size, '#0000a0', hj='L', vj='B')
        elif isinstance(it, S.Label):
            hj = 'L' if it.orient in (0, 1) else 'R'
            cv.text(it.x, it.y - TXTMARGE, it.text, it.size, '#000000', hj=hj, vj='B', vertical=it.orient in (1, 3))
            cv.circle(it.x, it.y, 8, '#000000', 2)
        elif isinstance(it, S.SchComponent):
            comp = lib.find(it.lib_name)
            if comp is None:
                cv.rect(it.x - 200, it.y - 200, it.x + 200, it.y + 200, '#ff0000')
                cv.text(it.x, it.y, '??', 100, '#ff0000')
                continue
            draw_component(cv, comp, it.unit, it.convert, it.matrix, it.x, it.y, fields=False, show_hidden_pins=False)
            for f in it.fields:
                if f.hidden or not f.text:
                    continue
                text = f.text
                if f.id == M.REFERENCE and comp.unit_count > 1:
                    text += chr(ord('A') + it.unit - 1)
                cv.text(f.x, f.y, text, f.size, '#008080', hj=f.hjust.value, vj=f.vjust.value, vertical=f.vertical)
        elif isinstance(it, S.Sheet):
            cv.rect(it.x, it.y, it.x + it.w, it.y + it.h, '#a000a0')
            cv.text(it.x, it.y - 20, it.name, it.name_size, '#00a0a0', hj='L', vj='B')
            cv.text(it.x, it.y + it.h + 20, it.filename, it.file_size, '#a0a000', hj='L', vj='T')
            for p in it.pins:
                cv.text(p.x, p.y, p.name, p.size, '#a000a0', hj='L' if p.side == 'L' else 'R')
    return cv.svg(margin=100, scale=0.15)


# --- посадочные места (.mod) ---------------------------------------------------

def render_modlib(lib, scale_mm: float = 12.0) -> str:
    """Все корпуса библиотеки в одну картинку. Координаты pcbnew: 1/10000 дюйма,
    Y вниз; масштаб — пикселей на мм."""
    from . import mod as MOD
    import math as _m
    k = scale_mm / (10000.0 / 25.4)          # пикселей на внутреннюю единицу
    parts = []
    x_off = 0.0
    width_total = 0.0
    height_max = 0.0
    for fp in lib.footprints:
        xs, ys = [0.0], [0.0]
        for p in fp.pads:
            xs += [p.x - p.size_x / 2, p.x + p.size_x / 2]; ys += [p.y - p.size_y / 2, p.y + p.size_y / 2]
        for e in fp.drawings:
            if isinstance(e, MOD.EdgeLine):
                xs += [e.start_x, e.end_x]; ys += [e.start_y, e.end_y]
            elif isinstance(e, MOD.EdgeCircle):
                r = _m.hypot(e.point_x - e.center_x, e.point_y - e.center_y)
                xs += [e.center_x - r, e.center_x + r]; ys += [e.center_y - r, e.center_y + r]
            elif isinstance(e, MOD.EdgeArc):
                r = _m.hypot(e.start_x - e.center_x, e.start_y - e.center_y)
                xs += [e.center_x - r, e.center_x + r]; ys += [e.center_y - r, e.center_y + r]
        for t in (fp.reference, fp.value):
            xs += [t.x - 2000, t.x + 2000]; ys += [t.y - 600, t.y + 600]
        minx, maxx, miny, maxy = min(xs) - 2000, max(xs) + 2000, min(ys) - 2000, max(ys) + 2000
        w = (maxx - minx) * k
        h = (maxy - miny) * k
        ox = x_off - minx * k
        oy = -miny * k
        g = ['<g transform="translate(%.1f,%.1f)">' % (ox, oy)]
        for e in fp.drawings:
            if isinstance(e, MOD.EdgeLine):
                g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c0c000" stroke-width="%.1f" stroke-linecap="round"/>'
                         % (e.start_x * k, e.start_y * k, e.end_x * k, e.end_y * k, max(1, e.width * k)))
            elif isinstance(e, MOD.EdgeCircle):
                r = _m.hypot(e.point_x - e.center_x, e.point_y - e.center_y)
                g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" stroke="#c0c000" fill="none" stroke-width="%.1f"/>'
                         % (e.center_x * k, e.center_y * k, r * k, max(1, e.width * k)))
            elif isinstance(e, MOD.EdgeArc):
                r = _m.hypot(e.start_x - e.center_x, e.start_y - e.center_y)
                a0 = _m.atan2(e.start_y - e.center_y, e.start_x - e.center_x)
                a1 = a0 + _m.radians(e.angle / 10.0)     # pcbnew: положительный угол — по часовой на экране (Y вниз)
                ex, ey = e.center_x + r * _m.cos(a1), e.center_y + r * _m.sin(a1)
                large = 1 if abs(e.angle) > 1800 else 0
                sweep = 1 if e.angle > 0 else 0
                g.append('<path d="M %.1f %.1f A %.1f %.1f 0 %d %d %.1f %.1f" stroke="#c0c000" fill="none" stroke-width="%.1f"/>'
                         % (e.start_x * k, e.start_y * k, r * k, r * k, large, sweep, ex * k, ey * k, max(1, e.width * k)))
        for p in fp.pads:
            fill = '#c08040' if p.attribute != 'HOLE' else 'none'
            if p.shape == 'R':
                g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#804000"/>'
                         % ((p.x - p.size_x / 2) * k, (p.y - p.size_y / 2) * k, p.size_x * k, p.size_y * k, fill))
            else:
                g.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="%s" stroke="#804000"/>'
                         % (p.x * k, p.y * k, p.size_x / 2 * k, p.size_y / 2 * k, fill))
            if p.drill:
                g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="white" stroke="#404040"/>' % (p.x * k, p.y * k, p.drill / 2 * k))
            if p.number:
                g.append('<text x="%.1f" y="%.1f" font-size="%.1f" font-family="monospace" text-anchor="middle" dominant-baseline="central" fill="#000">%s</text>'
                         % (p.x * k, p.y * k, max(6, p.size_x * k * 0.6), _esc(p.number)))
        for t in (fp.reference, fp.value):
            if t.hidden:
                continue
            tr = ' transform="rotate(%.0f %.1f %.1f)"' % (-t.orient / 10.0, t.x * k, t.y * k) if t.orient else ''
            g.append('<text x="%.1f" y="%.1f" font-size="%.1f" font-family="monospace" text-anchor="middle" dominant-baseline="central" fill="#008080"%s>%s</text>'
                     % (t.x * k, t.y * k, max(6, t.size_y * k), tr, _esc(t.text)))
        g.append('<text x="%.1f" y="%.1f" font-size="12" font-family="monospace" text-anchor="middle" fill="#000">%s</text>'
                 % (((minx + maxx) / 2) * k, maxy * k - 4, _esc(fp.name)))
        # сетка 1.25 мм (ТЗ §1.3б)
        step = MOD.mm_to_pcb(1.25) * k
        gx = minx * k
        while gx < maxx * k:
            gy = miny * k
            while gy < maxy * k:
                g.append('<circle cx="%.1f" cy="%.1f" r="0.6" fill="#b0b0b0"/>' % (gx, gy))
                gy += step
            gx += step
        g.append('</g>')
        parts.append(''.join(g))
        x_off += w + 20
        width_total = x_off
        height_max = max(height_max, h)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d"><rect width="100%%" height="100%%" fill="white"/>%s</svg>'
            % (width_total + 20, height_max + 20, ''.join(parts)))
