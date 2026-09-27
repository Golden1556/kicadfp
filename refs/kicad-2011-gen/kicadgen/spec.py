"""YAML-спецификация проекта -> Library / Schematic / .pro.

Формат спецификации описан в docs/workflow.md. Кратко:

    project: 346_8
    units: mm            # mm | mil  (единицы всех размеров в файле)
    grid: 50             # мил; точки подключения выводов снапятся к сетке
    library:
      components:
        - name: K555TB6      # kind: box | two_pin | table | power | raw
          kind: box
          ...
    schematic:
      page: A4
      place: [...]
      connect: [...]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import model as M
from . import helpers as H
from . import sch as S
from .textio import mm_to_mil
from .writer_lib import save_library, write_library
from .writer_pro import save_project, DEFAULT_EESCHEMA_LIBS

_PIN_TYPES = {
    'input': M.PinType.INPUT, 'in': M.PinType.INPUT, 'вход': M.PinType.INPUT,
    'output': M.PinType.OUTPUT, 'out': M.PinType.OUTPUT, 'выход': M.PinType.OUTPUT,
    'bidi': M.PinType.BIDI, 'bidirectional': M.PinType.BIDI, 'двунаправленный': M.PinType.BIDI,
    'tristate': M.PinType.TRISTATE, '3state': M.PinType.TRISTATE,
    'passive': M.PinType.PASSIVE, 'пассивный': M.PinType.PASSIVE,
    'unspecified': M.PinType.UNSPECIFIED, 'unspc': M.PinType.UNSPECIFIED,
    'power_in': M.PinType.POWER_IN, 'power in': M.PinType.POWER_IN, 'вход питания': M.PinType.POWER_IN,
    'power_out': M.PinType.POWER_OUT, 'power out': M.PinType.POWER_OUT, 'выход питания': M.PinType.POWER_OUT,
    'open_collector': M.PinType.OPEN_COLLECTOR, 'open_emitter': M.PinType.OPEN_EMITTER,
    'nc': M.PinType.NC, 'not_connected': M.PinType.NC,
}
_PIN_SHAPES = {
    'line': M.PinShape.NONE, 'none': M.PinShape.NONE, '': M.PinShape.NONE,
    'inverted': M.PinShape.INVERT, 'invert': M.PinShape.INVERT, 'инверсный': M.PinShape.INVERT,
    'clock': M.PinShape.CLOCK, 'inverted_clock': M.PinShape.INVERT | M.PinShape.CLOCK,
    'input_low': M.PinShape.LOWLEVEL_IN, 'clock_low': M.PinShape.LOWLEVEL_IN | M.PinShape.CLOCK,
    'output_low': M.PinShape.LOWLEVEL_OUT, 'falling_edge': M.PinShape.CLOCK_FALL,
    'nonlogic': M.PinShape.NONLOGIC,
}


class SpecError(ValueError):
    pass


class Units:
    def __init__(self, units: str = 'mm', grid: int = 50):
        if units not in ('mm', 'mil'):
            raise SpecError('units must be mm or mil')
        self.units = units
        self.grid = int(grid)

    def L(self, v: Any, snap: bool = True) -> int:
        """Длина/координата -> милы (со снапом к сетке по умолчанию)."""
        if v is None:
            raise SpecError('missing length')
        if isinstance(v, str):
            s = v.strip().lower()
            if s.endswith('mil'):
                return int(round(float(s[:-3])))
            if s.endswith('mm'):
                v = float(s[:-2]); units = 'mm'
            else:
                v = float(s); units = self.units
        else:
            units = self.units
        mil = mm_to_mil(float(v)) if units == 'mm' else float(v)
        return H.snap(mil, self.grid) if snap else int(round(mil))

    def T(self, v: Any) -> int:
        """Размер текста -> милы без снапа."""
        return self.L(v, snap=False)

    def pt(self, p: Sequence[Any], snap: bool = True) -> Tuple[int, int]:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise SpecError('point must be [x, y], got %r' % (p,))
        return self.L(p[0], snap), self.L(p[1], snap)


# --- библиотека ---------------------------------------------------------------

def _pin_spec(d: Dict[str, Any], u: Units, default_unit: int) -> H.PinSpec:
    t = str(d.get('type', 'input')).strip().lower()
    if t not in _PIN_TYPES:
        raise SpecError('unknown pin type %r' % t)
    sh = str(d.get('shape', 'line')).strip().lower()
    if sh not in _PIN_SHAPES:
        raise SpecError('unknown pin shape %r' % sh)
    unit = d.get('unit', default_unit)
    if isinstance(unit, str):
        unit = 0 if unit.lower() in ('common', 'all', 'общий', '0') else (ord(unit.upper()) - ord('A') + 1 if unit.isalpha() else int(unit))
    return H.PinSpec(
        name=str(d.get('name', '~')), number=str(d['number']),
        side=str(d.get('side', 'left')).lower(), etype=_PIN_TYPES[t], shape=_PIN_SHAPES[sh],
        unit=int(unit), convert=int(d.get('convert', 1)),
        visible=bool(d.get('visible', True)),
        length=u.L(d['length']) if 'length' in d else None,
        at=u.pt(d['at']) if 'at' in d else None,
        row=int(d['row']) if 'row' in d else None,
        name_size=u.T(d['name_size']) if 'name_size' in d else None,
        num_size=u.T(d['number_size']) if 'number_size' in d else None)


def _raw_items(items: Sequence[Dict[str, Any]], u: Units) -> List[M.DrawItem]:
    out: List[M.DrawItem] = []
    for d in items or []:
        unit, conv = int(d.get('unit', 0)), int(d.get('convert', 1))
        width = u.L(d.get('width', 0), snap=False)
        fill = {'none': M.Fill.NONE, 'fg': M.Fill.FOREGROUND, 'bg': M.Fill.BACKGROUND}[str(d.get('fill', 'none'))]
        if 'rect' in d:
            (x1, y1), (x2, y2) = u.pt(d['rect'][0]), u.pt(d['rect'][1])
            out.append(M.Rect(unit, conv, x1, y1, x2, y2, width, fill))
        elif 'line' in d or 'polyline' in d:
            pts = [u.pt(p) for p in d.get('line', d.get('polyline'))]
            out.append(M.Polyline(unit, conv, pts, width, fill))
        elif 'bezier' in d:
            out.append(M.Bezier(unit, conv, [u.pt(p) for p in d['bezier']], width, fill))
        elif 'circle' in d:
            cx, cy = u.pt(d['circle']['at'])
            out.append(M.Circle(unit, conv, cx, cy, u.L(d['circle']['r'], snap=False), width, fill))
        elif 'arc' in d:
            a = d['arc']; cx, cy = u.pt(a['at'])
            out.append(M.Arc(unit, conv, cx, cy, u.L(a['r'], snap=False),
                             int(round(float(a['start']) * 10)), int(round(float(a['end']) * 10)), width, fill))
        elif 'text' in d:
            x, y = u.pt(d.get('at', [0, 0]), snap=False)
            out.append(M.Text(unit, conv, str(d['text']), x, y, u.T(d.get('size', 50 if u.units == 'mil' else 1.27)),
                              bool(d.get('vertical', False)), bool(d.get('hidden', False)),
                              bool(d.get('italic', False)), bool(d.get('bold', False))))
        elif 'pin' in d:
            p = _pin_spec(d['pin'], u, 1)
            if p.at is None:
                raise SpecError('raw pin needs "at"')
            length = p.length if p.length is not None else 300
            out.append(M.Pin(p.unit, p.convert, p.name, p.number, p.at[0], p.at[1], length,
                             H._SIDE_ORIENT[p.side], p.num_size or 50, p.name_size or 50,
                             p.etype, p.shape, p.visible))
        else:
            raise SpecError('unknown draw item %r' % d)
    return out


def build_component(d: Dict[str, Any], u: Units) -> M.Component:
    kind = str(d.get('kind', 'box')).lower()
    name = str(d['name']).upper()   # DEF-имя всё равно приводится к верхнему регистру при загрузке
    ref = str(d.get('reference', 'U'))
    unit_count = int(d.get('units', 1))
    text_size = u.T(d['text_size']) if 'text_size' in d else 50
    field_size = u.T(d['field_size']) if 'field_size' in d else M.DEFAULT_SIZE_TEXT
    value_visible = bool(d.get('value_visible', True))
    line_width = u.L(d.get('line_width', 0), snap=False)
    if kind == 'box':
        pins = [_pin_spec(p, u, 1) for p in d.get('pins', [])]
        extra = _raw_items(d.get('draw', []), u)
        for t in d.get('texts', []):
            x, y = u.pt(t.get('at', [0, 0]), snap=False)
            extra.append(M.Text(0, 1, str(t['text']), x, y, u.T(t.get('size', text_size if u.units == 'mil' else t.get('size', 1.27)))))
        comp = H.box_symbol(
            name, ref, pins, unit_count=unit_count,
            width=u.L(d['width']) if 'width' in d else None,
            height=u.L(d['height']) if 'height' in d else None,
            pin_length=u.L(d.get('pin_length', 300 if u.units == 'mil' else 7.62)),
            pitch=u.L(d.get('pitch', 100 if u.units == 'mil' else 2.54)),
            grid=u.grid, text_size=text_size,
            pin_name_offset=u.T(d['pin_name_offset']) if 'pin_name_offset' in d else 40,
            line_width=line_width, value_visible=value_visible,
            show_pin_numbers=bool(d.get('show_pin_numbers', True)),
            show_pin_names=bool(d.get('show_pin_names', True)),
            power=bool(d.get('power', False)), units_locked=bool(d.get('units_locked', False)),
            field_size=field_size, extra_items=extra,
            body_dividers=[u.L(x) for x in d.get('dividers', [])])
    elif kind == 'two_pin':
        pins = d.get('pins', [{'number': 1}, {'number': 2}])
        ptype = _PIN_TYPES[str(pins[0].get('type', 'passive')).lower()]
        comp = H.two_pin_box(
            name, ref, width=u.L(d.get('width', 10 if u.units == 'mm' else 400)),
            height=u.L(d.get('height', 4 if u.units == 'mm' else 150)),
            pin_length=u.L(d.get('pin_length', 5 if u.units == 'mm' else 200)), etype=ptype,
            names=(str(pins[0].get('name', pins[0]['number'])), str(pins[1].get('name', pins[1]['number']))),
            numbers=(str(pins[0]['number']), str(pins[1]['number'])),
            text_size=text_size, line_width=line_width, value_visible=value_visible,
            show_pin_names=bool(d.get('show_pin_names', False)),
            show_pin_numbers=bool(d.get('show_pin_numbers', True)), field_size=field_size)
    elif kind == 'table':
        rows = [(str(r[0] or ''), str(r[1])) for r in d['rows']]
        ptype = _PIN_TYPES[str(d.get('pin_type', 'bidi')).lower()]
        comp = H.table_connector(
            name, ref, rows, width=u.L(d.get('width', 35)), row_height=u.L(d.get('row_height', 7.5)),
            pin_length=u.L(d.get('pin_length', 5)),
            net_col_width=u.L(d['net_col_width']) if 'net_col_width' in d else None,
            header=tuple(d.get('header', ('Net', 'Pin'))), etype=ptype, text_size=text_size,
            line_width=line_width, value_visible=value_visible, field_size=field_size, grid=u.grid,
            pins_side=str(d.get('pins_side', 'right')))
    elif kind == 'power':
        comp = H.power_symbol(
            name, d.get('net'), str(d.get('style', 'gnd')), reference=ref if ref != 'U' else '#PWR',
            length=u.L(d.get('pin_length', 0)), bar=u.L(d.get('bar', 8)), height=u.L(d.get('height', 5)),
            line_width=line_width, bar_width=u.L(d.get('bar_width', 0), snap=False),
            arm_height=u.L(d['arm_height']) if 'arm_height' in d else None,
            text_size=text_size, value_visible=value_visible, field_size=field_size)
    elif kind == 'raw':
        comp = M.Component(name, ref, int(d.get('pin_name_offset', 40)), bool(d.get('show_pin_numbers', True)),
                           bool(d.get('show_pin_names', True)), unit_count, bool(d.get('units_locked', False)),
                           bool(d.get('power', False)), value_visible)
        comp.items.extend(_raw_items(d.get('draw', []), u))
        for f in d.get('fields', []):
            x, y = u.pt(f.get('at', [0, 0]), snap=False)
            comp.fields.append(M.Field(int(f['id']), str(f.get('text', '')), x, y, u.T(f.get('size', field_size)),
                                       visible=bool(f.get('visible', True)), name=f.get('name')))
        comp.ensure_mandatory_fields()
    else:
        raise SpecError('unknown component kind %r' % kind)
    if d.get('footprint'):
        # поле Footprint (F2) — как после назначения корпуса в Cvpcb; попадает в .sch и в .net
        comp.ensure_mandatory_fields()
        if comp.get_field(M.FOOTPRINT) is None:
            comp.fields.append(M.Field(M.FOOTPRINT, str(d['footprint']), 0, 0, visible=False))
        else:
            comp.get_field(M.FOOTPRINT).text = str(d['footprint'])
    comp.description = str(d.get('description', ''))
    comp.keywords = str(d.get('keywords', ''))
    comp.docfile = str(d.get('docfile', ''))
    comp.aliases = [str(a) for a in d.get('aliases', [])]
    comp.fplist = [str(f) for f in d.get('footprints', [])]
    for f in d.get('fields', []) if kind != 'raw' else []:
        x, y = u.pt(f.get('at', [0, 0]), snap=False)
        comp.fields.append(M.Field(int(f['id']), str(f.get('text', '')), x, y, u.T(f.get('size', field_size)),
                                   visible=bool(f.get('visible', True)), name=f.get('name')))
    if 'reference_at' in d:
        comp.get_field(M.REFERENCE).x, comp.get_field(M.REFERENCE).y = u.pt(d['reference_at'], snap=False)
    if 'value_at' in d:
        comp.get_field(M.VALUE).x, comp.get_field(M.VALUE).y = u.pt(d['value_at'], snap=False)
    return comp


def build_library(spec: Dict[str, Any], u: Units) -> M.Library:
    lib = M.Library()
    for d in spec.get('components', []):
        lib.components.append(build_component(d, u))
    lib.validate()
    return lib


# --- схема ------------------------------------------------------------------------

class _Placed:
    def __init__(self, comp: S.SchComponent, libc: M.Component):
        self.comp = comp
        self.libc = libc

    def pin_by_number(self, number: str) -> Optional[M.Pin]:
        for p in self.libc.pins(self.comp.unit, self.comp.convert):
            if p.number == number:
                return p
        return None


def _seg_contains(w: S.Wire, x: int, y: int) -> bool:
    """Точка строго внутри отрезка (не на концах), коллинеарно — как SegmentIntersect."""
    if (x, y) in ((w.x1, w.y1), (w.x2, w.y2)):
        return False
    if w.x1 == w.x2 == x:
        return min(w.y1, w.y2) < y < max(w.y1, w.y2)
    if w.y1 == w.y2 == y:
        return min(w.x1, w.x2) < x < max(w.x1, w.x2)
    return False


def build_schematic(spec: Dict[str, Any], lib: M.Library, u: Units, libs_for_header: Sequence[str]) -> S.Schematic:
    sch = S.Schematic(libs=list(libs_for_header), page=str(spec.get('page', 'A4')),
                      title=str(spec.get('title', '')), date=str(spec.get('date', '')),
                      rev=str(spec.get('rev', '')), company=str(spec.get('company', '')))
    cm = spec.get('comments', [])
    sch.comments = (list(cm) + [''] * 4)[:4]
    placed: List[_Placed] = []
    power_idx = 0
    for d in spec.get('place', []):
        libname = str(d['lib']).upper()
        libc = lib.find(libname)
        if libc is None:
            raise SpecError('library has no component %r' % libname)
        x, y = u.pt(d['at'])
        ref = str(d.get('ref', ''))
        if not ref:
            if libc.power:
                power_idx += 1
                ref = '#PWR%02d' % power_idx
            else:
                ref = libc.reference + '?'
        comp = S.SchComponent(libname, ref, x, y, int(d.get('unit', 1)), int(d.get('convert', 1)),
                              str(d.get('orientation', '0')), value=d.get('value'))
        # поля: позиции берём из библиотеки (перевод lib->sheet матрицей), видимость тоже
        for lf in libc.fields:
            if lf.id > M.VALUE and lf.text == '':
                continue
            dx, dy = S.transform_point(comp.matrix, lf.x, lf.y)
            text = lf.text
            if lf.id == M.REFERENCE:
                text = ref
            elif lf.id == M.VALUE:
                text = d.get('value', libc.name)
            hidden = not lf.visible
            if lf.id == M.REFERENCE and ref.startswith('#'):
                hidden = True
            sf = S.SchField(lf.id, text, x + dx, y + dy, lf.size, lf.vertical, hidden,
                            lf.hjust, lf.vjust, lf.italic, lf.bold, lf.name)
            comp.fields.append(sf)
        for f in d.get('fields', []):
            fid = int(f['id'])
            existing = comp.field(fid)
            if existing is None:
                existing = S.SchField(fid, '', x, y, name=f.get('name'))
                comp.fields.append(existing)
            if 'text' in f:
                existing.text = str(f['text'])
            if 'at' in f:
                existing.x, existing.y = u.pt(f['at'], snap=False)
            if 'visible' in f:
                existing.hidden = not bool(f['visible'])
            if 'size' in f:
                existing.size = u.T(f['size'])
        sch.items.append(comp)
        placed.append(_Placed(comp, libc))

    def pin_pos(s: str) -> Tuple[int, int]:
        if '.' not in s:
            raise SpecError('endpoint %r must be REF.PIN' % s)
        ref, num = s.rsplit('.', 1)
        cands = [p for p in placed if p.comp.reference == ref]
        if not cands:
            raise SpecError('no placed component with reference %r' % ref)
        for p in cands:
            pin = p.pin_by_number(num)
            if pin is not None:
                return p.comp.pin_position(pin)
        raise SpecError('component %r has no pin %r in placed units' % (ref, num))

    def resolve(ep: Any, prev: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
        """Точка: [x, y] | "REF.PIN" | "x=<v>" / "y=<v>" (остальная координата от prev)
        | {ref: REF.PIN, x: <v>} / {ref: ..., y: <v>} | {x: <v>} / {y: <v>} (от prev)."""
        if isinstance(ep, (list, tuple)):
            return u.pt(ep)
        if isinstance(ep, dict):
            base = pin_pos(str(ep['ref'])) if 'ref' in ep else prev
            if base is None:
                raise SpecError('point %r needs a previous point or ref' % (ep,))
            x = u.L(ep['x']) if 'x' in ep else base[0]
            y = u.L(ep['y']) if 'y' in ep else base[1]
            return x, y
        s = str(ep).strip()
        if s.startswith(('x=', 'y=')):
            if prev is None:
                raise SpecError('%r needs a previous point' % s)
            v = u.L(s[2:])
            return (v, prev[1]) if s[0] == 'x' else (prev[0], v)
        return pin_pos(s)

    def resolve_path(seq) -> List[Tuple[int, int]]:
        pts: List[Tuple[int, int]] = []
        for e in seq:
            pts.append(resolve(e, pts[-1] if pts else None))
        return pts

    wires: List[S.Wire] = []

    def add_path(points: List[Tuple[int, int]], layer: str = 'Wire') -> None:
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if (ax, ay) == (bx, by):
                continue
            if ax != bx and ay != by:
                # L-образно: сначала по горизонтали
                wires.append(S.Wire(ax, ay, bx, ay, layer))
                wires.append(S.Wire(bx, ay, bx, by, layer))
            else:
                wires.append(S.Wire(ax, ay, bx, by, layer))

    for c in spec.get('connect', []):
        if isinstance(c, dict):
            pts = resolve_path(c['path'])
            layer = str(c.get('layer', 'Wire'))
        else:
            pts = resolve_path(c)
            layer = 'Wire'
        add_path(pts, layer)
    for wdef in spec.get('wires', []):
        add_path([u.pt(p) for p in wdef], 'Wire')
    for bdef in spec.get('buses', []):
        add_path([u.pt(p) for p in bdef], 'Bus')
    sch.items.extend(wires)
    for e in spec.get('bus_entries', []):
        if 'from_bus' in e:
            # ввод по концу провода: старт на шине, 45°, длина по горизонтали = расстояние до шины
            bx = u.L(e['from_bus'])
            ex, ey = resolve(e['to'])
            dx = ex - bx
            sy = ey - abs(dx)
            sch.items.append(S.BusEntry(bx, sy, dx, abs(dx), bool(e.get('bus', False))))
        else:
            x, y = resolve(e['at'])
            dx, dy = u.pt(e.get('to', [50, 50] if u.units == 'mil' else [1.27, 1.27]), snap=False)
            sch.items.append(S.BusEntry(x, y, dx, dy, bool(e.get('bus', False))))
    for l in spec.get('labels', []):
        x, y = resolve(l['at'])
        kind = str(l.get('kind', 'local')).lower()
        size = u.T(l.get('size', 60 if u.units == 'mil' else 1.524))
        args = (x, y, str(l['text']), int(l.get('orient', 0)), size, bool(l.get('italic', False)), bool(l.get('bold', False)))
        if kind == 'global':
            sch.items.append(S.GlobalLabel(*args, shape=str(l.get('shape', 'Input'))))
        elif kind in ('hier', 'hierarchical'):
            sch.items.append(S.HierLabel(*args, shape=str(l.get('shape', 'Input'))))
        elif kind in ('note', 'text'):
            sch.items.append(S.Note(*args))
        else:
            sch.items.append(S.Label(*args))
    for nc in spec.get('noconnect', []):
        x, y = resolve(nc)
        sch.items.append(S.NoConnect(x, y))
    for j in spec.get('junctions', []):
        x, y = resolve(j)
        sch.items.append(S.Junction(x, y))
    for sh in spec.get('sheets', []):
        x, y = u.pt(sh['at'])
        w_, h_ = u.pt(sh['size'])
        sheet = S.Sheet(x, y, w_, h_, str(sh['name']), str(sh['file']),
                        name_size=u.T(sh.get('name_size', 60 if u.units == 'mil' else 1.524)),
                        file_size=u.T(sh.get('file_size', 60 if u.units == 'mil' else 1.524)))
        for p in sh.get('pins', []):
            px, py = resolve(p['at'])
            sheet.pins.append(S.SheetPin(str(p['name']), px, py, str(p.get('shape', 'Input')),
                                         str(p.get('side', 'L')), u.T(p.get('size', 60 if u.units == 'mil' else 1.524))))
        sch.items.append(sheet)
    # авто-junction: конец провода или вывод внутри другого провода (IsJunctionNeeded)
    if spec.get('auto_junctions', True):
        existing = {(i.x, i.y) for i in sch.items if isinstance(i, S.Junction)}
        pts = set()
        for w in wires:
            if w.layer == 'Wire':
                pts.add((w.x1, w.y1)); pts.add((w.x2, w.y2))
        for p in placed:
            for pin in p.libc.pins(p.comp.unit, p.comp.convert):
                pts.add(p.comp.pin_position(pin))
        from collections import Counter
        ends = Counter()
        for w in wires:
            if w.layer == 'Wire':
                ends[(w.x1, w.y1)] += 1
                ends[(w.x2, w.y2)] += 1
        for (x, y) in sorted(pts):
            if (x, y) in existing:
                continue
            inside = any(w.layer == 'Wire' and _seg_contains(w, x, y) for w in wires)
            # T-стык из >= 3 концов проводов: электрически связан и без junction
            # (PointToPointConnect), но на чертеже точка нужна — ставим, как делает libedit
            if inside or ends[(x, y)] >= 3:
                sch.items.append(S.Junction(x, y))
                existing.add((x, y))
    sch.validate()
    return sch


# --- проект целиком ------------------------------------------------------------------

def load_spec(path: str) -> Dict[str, Any]:
    import yaml
    with open(path, encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def build_footprints(items: Sequence[Dict[str, Any]]):
    """Секция footprints: [{name, kind: dip|two_pad|pin_rows, ...параметры в мм}]."""
    from . import mod as MOD
    lib = MOD.ModLibrary()
    builders = {'dip': MOD.dip, 'two_pad': MOD.two_pad, 'pin_rows': MOD.pin_rows}
    for d in items:
        d = dict(d)
        kind = str(d.pop('kind', 'dip'))
        if kind not in builders:
            raise SpecError('unknown footprint kind %r' % kind)
        desc = d.pop('description', '')
        kw = d.pop('keywords', '')
        fp = builders[kind](**d)
        if desc:
            fp.doc = str(desc)
        if kw:
            fp.keyword = str(kw)
        lib.add(fp)
    return lib


def generate(spec: Dict[str, Any], out_dir: str, date: Optional[str] = None) -> List[str]:
    """Создаёт <proj>.lib/.dcm/.pro[/.sch, -cache.lib] в out_dir. Возвращает пути."""
    if not isinstance(spec.get('project'), str):
        raise SpecError('project must be a quoted string (YAML reads 346_8 as the number 3468)')
    name = spec['project']
    u = Units(str(spec.get('units', 'mm')), int(spec.get('grid', 50)))
    crlf = bool(spec.get('crlf', True))
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    lib = build_library(spec.get('library', {}), u)
    lib_name = str(spec.get('library', {}).get('name', name))
    written += save_library(lib, os.path.join(out_dir, lib_name + '.lib'), date=date, crlf=crlf)
    extra_libs = [str(l) for l in spec.get('extra_libraries', [])]
    std_libs = spec.get('standard_libraries')
    pcb_libs = None
    pcb_over: Dict[str, str] = {}
    if spec.get('footprints'):
        from . import mod as MOD
        from .writer_pro import DEFAULT_PCBNEW_LIBS
        fplib = build_footprints(spec['footprints'])
        mod_path = os.path.join(out_dir, lib_name + '.mod')
        MOD.save_modlib(fplib, mod_path, date=date, crlf=crlf)
        written.append(mod_path)
        pcb_libs = [lib_name] + list(DEFAULT_PCBNEW_LIBS)
        pads = spec.get('pad_defaults') or {}
        # ТЗ §1.5: площадки по умолчанию 1.3x1.3 мм, сверло 0.8 мм (единицы pcbnew: 1/10000 дюйма)
        pcb_over = {'PadDimH': str(MOD.mm_to_pcb(float(pads.get('size', 1.3)))),
                    'PadDimV': str(MOD.mm_to_pcb(float(pads.get('size', 1.3)))),
                    'PadDrlX': str(MOD.mm_to_pcb(float(pads.get('drill', 0.8)))),
                    'PadForm': '1'}   # PAD_CIRCLE (include/pad_shapes.h:10)
    written.append(save_project(os.path.join(out_dir, name + '.pro'), lib_name, crlf=crlf, date=date,
                                extra_libs=extra_libs,
                                standard_libs=std_libs if std_libs is not None else None,
                                pcb_libs=pcb_libs, pcbnew_overrides=pcb_over))
    if 'schematic' in spec:
        std = list(DEFAULT_EESCHEMA_LIBS if std_libs is None else std_libs)
        header_libs = [l for l in extra_libs + [lib_name] if l not in std] + std + [name + '-cache']
        sch = build_schematic(spec['schematic'], lib, u, header_libs)
        # детерминированные timestamps: при одинаковой дате файлы .sch/.net воспроизводимы байт в байт
        import zlib
        base = (zlib.crc32((date or '').encode('utf-8')) & 0x3FFFFFFF) | 0x40000000
        for i, it in enumerate(x for x in sch.items if isinstance(x, (S.SchComponent, S.Sheet))):
            if not it.timestamp:
                it.timestamp = (base + i) & 0xFFFFFFFF
        sch_path = os.path.join(out_dir, name + '.sch')
        S.save_schematic(sch, sch_path, date=date, crlf=crlf)
        written.append(sch_path)
        # кеш: только использованные компоненты (libarch.cpp)
        used = {c.lib_name.casefold() for c in sch.components()}
        cache = M.Library([c for c in lib.components if c.name.casefold() in used])
        written += save_library(cache, os.path.join(out_dir, name + '-cache.lib'), date=date,
                                crlf=crlf, with_doc=False)
        # список цепей (ЛР 3: «Сформировать список цепей», формат Pcbnew)
        if spec.get('netlist', True):
            from . import netlist as N
            from .textio import kicad_date
            import io as _io
            import sys as _sys
            try:
                net_text = N.write_netlist_pcbnew(sch, lib, date=date or kicad_date(),
                                                  loader=N.file_sheet_loader(out_dir))
            except (N.NetlistError, OSError) as e:
                print('warning: netlist not written: %s' % e, file=_sys.stderr)
            else:
                net_path = os.path.join(out_dir, name + '.net')
                with _io.open(net_path, 'w', encoding='utf-8', newline='') as fh:
                    fh.write(net_text.replace('\n', '\r\n') if crlf else net_text)
                written.append(net_path)
    return written
