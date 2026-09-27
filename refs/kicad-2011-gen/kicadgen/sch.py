"""Схема EESchema (.sch): модель, запись и строгий читатель.

Ссылки: eeschema/load_one_schematic_file.cpp, sch_screen.cpp:499-549,
sch_component.cpp:667-1320, sch_field.cpp:316-361, sch_line.cpp:117-180,
sch_bus_entry.cpp:58-119, sch_junction.cpp:53-89, sch_no_connect.cpp:54-84,
sch_text.cpp:407-510/726-790/900-990/1333-1420, sch_sheet.cpp:120-292,
sch_sheet_pin.cpp:233-377.

Координаты — милы, начало (0,0) в левом верхнем углу листа, Y ВНИЗ.
Библиотечные координаты (Y вверх) переводятся матрицей компонента.
"""

from __future__ import annotations

import io
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from . import model as M
from .sscanf import sscanf
from .textio import escaped, read_delimited, encode_sch_name, decode_sch_name, kicad_date

EESCHEMA_VERSION = 2
NULL_STRING = '_NONAME_'
MAX_LAYER = 25

PAGE_SIZES: Dict[str, Tuple[int, int]] = {   # common/common.cpp:26-42
    'A4': (11700, 8267), 'A3': (16535, 11700), 'A2': (23400, 16535),
    'A1': (33070, 23400), 'A0': (46800, 33070), 'A': (11000, 8500),
    'B': (17000, 11000), 'C': (22000, 17000), 'D': (34000, 22000),
    'E': (44000, 34000), 'User': (17000, 11000),
}

SHAPE_NAMES = ['Input', 'Output', 'BiDi', '3State', 'UnSpc']   # sch_text.cpp:28-36
SHAPE_LETTERS = {'Input': 'I', 'Output': 'O', 'BiDi': 'B', '3State': 'T', 'UnSpc': 'U'}


class SchLoadError(Exception):
    pass


# --- Ориентация компонента -------------------------------------------------

Transform = Tuple[int, int, int, int]   # (x1, y1, x2, y2)

_T_BASE: Transform = (1, 0, 0, -1)                    # CMP_ORIENT_0
_T_ROT_CW: Transform = (0, 1, -1, 0)                  # sch_component.cpp:682-687
_T_ROT_CCW: Transform = (0, -1, 1, 0)                 # :689-694
_T_MIRROR_Y: Transform = (-1, 0, 0, 1)                # :696-701
_T_MIRROR_X: Transform = (1, 0, 0, -1)                # :703-708


def _mul(m: Transform, t: Transform) -> Transform:
    """sch_component.cpp:786-789."""
    mx1, my1, mx2, my2 = m
    tx1, ty1, tx2, ty2 = t
    return (mx1 * tx1 + mx2 * ty1,
            my1 * tx1 + my2 * ty1,
            mx1 * tx2 + mx2 * ty2,
            my1 * tx2 + my2 * ty2)


class Orientation:
    """Имена ориентаций: '0', '90', '180', '270', с суффиксом 'MX' или 'MY'
    (например '90MX'). Матрица вычисляется репликой SetOrientation."""

    @staticmethod
    def matrix(name: str) -> Transform:
        name = str(name).upper().replace('°', '')
        rot, mirror = name, ''
        for suf in ('MX', 'MY'):
            if name.endswith(suf):
                rot, mirror = name[:-2], suf
        m = _T_BASE
        if rot in ('', '0'):
            pass
        elif rot == '90':
            m = _mul(m, _T_ROT_CCW)
        elif rot == '180':
            m = _mul(_mul(m, _T_ROT_CCW), _T_ROT_CCW)
        elif rot == '270':
            m = _mul(m, _T_ROT_CW)
        else:
            raise ValueError('bad orientation %r' % name)
        if mirror == 'MX':
            m = _mul(m, _T_MIRROR_X)
        elif mirror == 'MY':
            m = _mul(m, _T_MIRROR_Y)
        return m

    @staticmethod
    def name(m: Transform) -> str:
        """GetOrientation (sch_component.cpp:795-831): первое совпадение в списке."""
        for n in ('0', '90', '180', '270', '0MX', '90MX', '180MX', '270MX',
                  '0MY', '90MY', '180MY', '270MY'):
            if Orientation.matrix(n) == tuple(m):
                return n
        return '?'


def transform_point(m: Transform, x: int, y: int) -> Tuple[int, int]:
    """TRANSFORM::TransformCoordinate (transform.cpp:28-32)."""
    return m[0] * x + m[1] * y, m[2] * x + m[3] * y


# --- Элементы схемы -----------------------------------------------------------

_ts_counter = [0]


def new_timestamp() -> int:
    """GetTimeStamp (common/common.cpp): time(NULL) c монотонным сдвигом."""
    t = int(time.time())
    if t <= _ts_counter[0]:
        t = _ts_counter[0] + 1
    _ts_counter[0] = t
    return t & 0xFFFFFFFF


@dataclass
class SchField:
    id: int
    text: str
    x: int = 0
    y: int = 0
    size: int = M.DEFAULT_SIZE_TEXT
    vertical: bool = False
    hidden: bool = False          # attrs 0001
    hjust: M.HJust = M.HJust.CENTER
    vjust: M.VJust = M.VJust.CENTER
    italic: bool = False
    bold: bool = False
    name: Optional[str] = None    # обязателен в файле для id >= 4


@dataclass
class SchComponent:
    lib_name: str
    reference: str                # 'DD1', 'R?' ...
    x: int
    y: int
    unit: int = 1
    convert: int = 1
    orientation: str = '0'        # см. Orientation
    timestamp: int = 0            # 0 -> сгенерировать
    fields: List[SchField] = field(default_factory=list)
    value: Optional[str] = None   # текст F1; None -> lib_name
    ar: List[Tuple[str, str, int]] = field(default_factory=list)   # (path, ref, part)

    @property
    def matrix(self) -> Transform:
        return Orientation.matrix(self.orientation)

    def pin_position(self, pin: M.Pin) -> Tuple[int, int]:
        dx, dy = transform_point(self.matrix, pin.x, pin.y)
        return self.x + dx, self.y + dy

    def field(self, idx: int) -> Optional[SchField]:
        for f in self.fields:
            if f.id == idx:
                return f
        return None

    def ensure_fields(self) -> None:
        if self.field(M.REFERENCE) is None:
            self.fields.insert(0, SchField(M.REFERENCE, self.reference, self.x, self.y,
                                           hidden=self.reference.startswith('#')))
        if self.field(M.VALUE) is None:
            self.fields.insert(1, SchField(M.VALUE, self.value if self.value is not None else self.lib_name,
                                           self.x, self.y))


@dataclass
class Wire:
    x1: int
    y1: int
    x2: int
    y2: int
    layer: str = 'Wire'           # Wire | Bus | Notes


@dataclass
class Bus(Wire):
    layer: str = 'Bus'


@dataclass
class BusEntry:
    x: int
    y: int
    dx: int = 100
    dy: int = 100
    bus: bool = False             # Entry Wire Line | Entry Bus Bus


@dataclass
class Junction:
    x: int
    y: int


@dataclass
class NoConnect:
    x: int
    y: int


@dataclass
class Label:
    x: int
    y: int
    text: str
    orient: int = 0               # 0 вправо, 1 вверх, 2 влево, 3 вниз
    size: int = M.DEFAULT_SIZE_TEXT
    italic: bool = False
    bold: bool = False


@dataclass
class GlobalLabel(Label):
    shape: str = 'Input'          # SHAPE_NAMES


@dataclass
class HierLabel(Label):
    shape: str = 'Input'


@dataclass
class Note(Label):
    """Text Notes: единственный тип, где допускается многострочный текст."""


@dataclass
class SheetPin:
    name: str
    x: int
    y: int
    shape: str = 'Input'          # I O B T U
    side: str = 'L'               # L R T B
    size: int = M.DEFAULT_SIZE_TEXT


@dataclass
class Sheet:
    x: int
    y: int
    w: int
    h: int
    name: str
    filename: str
    timestamp: int = 0
    name_size: int = M.DEFAULT_SIZE_TEXT
    file_size: int = M.DEFAULT_SIZE_TEXT
    pins: List[SheetPin] = field(default_factory=list)


SchItem = Union[SchComponent, Wire, Bus, BusEntry, Junction, NoConnect, Label,
                GlobalLabel, HierLabel, Note, Sheet]


@dataclass
class Schematic:
    libs: List[str] = field(default_factory=list)   # строки LIBS: (информационные)
    page: str = 'A4'
    page_size: Optional[Tuple[int, int]] = None      # только для 'User'
    sheet_number: int = 1
    sheet_count: int = 1
    title: str = ''
    date: str = ''
    rev: str = ''
    company: str = ''
    comments: List[str] = field(default_factory=lambda: ['', '', '', ''])
    items: List[SchItem] = field(default_factory=list)

    def components(self) -> List[SchComponent]:
        return [i for i in self.items if isinstance(i, SchComponent)]

    def validate(self) -> None:
        if self.page not in PAGE_SIZES:
            raise M.ValidationError('unknown page %r' % self.page)
        for it in self.items:
            if isinstance(it, SchComponent):
                for s, what in ((it.lib_name, 'lib name'), (it.reference, 'reference')):
                    if s == '':
                        raise M.ValidationError('component %s must not be empty' % what)
                    if '~' in s:
                        raise M.ValidationError('component %s %r: ~ is the space marker' % (what, s))
                if it.unit < 1:
                    raise M.ValidationError('component unit must be >= 1')
                Orientation.matrix(it.orientation)
                for f in it.fields:
                    if f.id >= M.MANDATORY_FIELDS and not (f.name or '').strip():
                        raise M.ValidationError('user field %d needs a name' % f.id)
            elif isinstance(it, (Label, GlobalLabel, HierLabel, Note)):
                if it.text == '':
                    raise M.ValidationError('label/text must not be empty (empty payload line is fatal)')
                if not isinstance(it, Note) and ('\n' in it.text or '\r' in it.text):
                    raise M.ValidationError('only Text Notes may contain newlines')
                if it.orient not in (0, 1, 2, 3):
                    raise M.ValidationError('text orient must be 0..3')
                if isinstance(it, (GlobalLabel, HierLabel)) and it.shape not in SHAPE_NAMES:
                    raise M.ValidationError('label shape must be one of %s' % SHAPE_NAMES)
            elif isinstance(it, Sheet):
                if not it.name or not it.filename:
                    raise M.ValidationError('sheet needs name and filename')
                for p in it.pins:
                    if p.shape not in SHAPE_LETTERS:
                        raise M.ValidationError('sheet pin shape %r' % p.shape)
                    if p.side not in 'LRTB':
                        raise M.ValidationError('sheet pin side %r' % p.side)
                    if p.name == '':
                        raise M.ValidationError('sheet pin name empty (KiCad would not write it)')
            elif isinstance(it, Wire):
                if it.layer not in ('Wire', 'Bus', 'Notes'):
                    raise M.ValidationError('wire layer %r' % it.layer)


# --- Запись ------------------------------------------------------------------

def _fmt4(*vals: int) -> str:
    return '\t' + ' '.join('%-4d' % v for v in vals)


def format_sch_field(f: SchField) -> str:
    """SCH_FIELD::Save (sch_field.cpp:332-355)."""
    s = 'F %d %s %c %-3d %-3d %-3d %4.4X %c %c%c%c' % (
        f.id, escaped(f.text), 'V' if f.vertical else 'H', f.x, f.y, f.size,
        1 if f.hidden else 0, f.hjust.value, f.vjust.value,
        'I' if f.italic else 'N', 'B' if f.bold else 'N')
    if f.id >= M.MANDATORY_FIELDS:
        s += ' ' + escaped(f.name or M.default_field_name(f.id))
    return s


def _label_header(kind: str, it: Label) -> str:
    shape_tok = ''
    if isinstance(it, (GlobalLabel, HierLabel)):
        shape_tok = '%s ' % it.shape
    thickness = 0
    if it.bold:
        # GetPenSizeForBold(size) = size / 5 (common/drawtxt.cpp)
        thickness = max(1, it.size // 5)
    return 'Text %s %-4d %-4d %-4d %-4d %s%s %d' % (
        kind, it.x, it.y, it.orient, it.size, shape_tok, 'Italic' if it.italic else '~', thickness)


def format_item(it: SchItem) -> List[str]:
    if isinstance(it, SchComponent):
        it.ensure_fields()
        ts = it.timestamp or new_timestamp()
        it.timestamp = ts
        lines = ['$Comp',
                 'L %s %s' % (encode_sch_name(it.lib_name) if it.lib_name else NULL_STRING,
                              encode_sch_name(it.reference)),
                 'U %d %d %8.8X' % (it.unit, it.convert, ts),
                 'P %d %d' % (it.x, it.y)]
        if len(it.ar) > 1:
            for path, ref, part in it.ar:
                lines.append('AR Path="%s" Ref="%s"  Part="%s" ' % (path, ref, part))
        fields = sorted(it.fields, key=lambda f: f.id)
        nid = M.MANDATORY_FIELDS
        for f in fields:
            if f.id < M.MANDATORY_FIELDS:
                if f.text != '':
                    lines.append(format_sch_field(f))
            else:
                f2 = SchField(**{**f.__dict__, 'id': nid})
                nid += 1
                lines.append(format_sch_field(f2))
        m = it.matrix
        lines.append(_fmt4(it.unit, it.x, it.y))
        lines.append(_fmt4(*m))
        lines.append('$EndComp')
        return lines
    if isinstance(it, Wire):
        return ['Wire %s Line' % it.layer, _fmt4(it.x1, it.y1, it.x2, it.y2)]
    if isinstance(it, BusEntry):
        head = 'Entry Bus Bus' if it.bus else 'Entry Wire Line'
        return [head, _fmt4(it.x, it.y, it.x + it.dx, it.y + it.dy)]
    if isinstance(it, Junction):
        return ['Connection ~ %-4d %-4d' % (it.x, it.y)]
    if isinstance(it, NoConnect):
        return ['NoConn ~ %-4d %-4d' % (it.x, it.y)]
    if isinstance(it, Note):
        return [_label_header('Notes', it), it.text.replace('\n', '\\n')]
    if isinstance(it, GlobalLabel):
        return [_label_header('GLabel', it), it.text]
    if isinstance(it, HierLabel):
        return [_label_header('HLabel', it), it.text]
    if isinstance(it, Label):
        return [_label_header('Label', it), it.text]
    if isinstance(it, Sheet):
        ts = it.timestamp or new_timestamp()
        it.timestamp = ts
        lines = ['$Sheet', 'S %-4d %-4d %-4d %-4d' % (it.x, it.y, it.w, it.h), 'U %8.8X' % ts]
        if it.name:
            lines.append('F0 %s %d' % (escaped(it.name), it.name_size))
        if it.filename:
            lines.append('F1 %s %d' % (escaped(it.filename), it.file_size))
        n = 2
        for p in it.pins:
            if p.name == '':
                continue
            lines.append('F%d %s %c %c %-3d %-3d %-3d' % (
                n, escaped(p.name), SHAPE_LETTERS[p.shape], p.side, p.x, p.y, p.size))
            n += 1
        lines.append('$EndSheet')
        return lines
    raise TypeError('unknown schematic item %r' % (it,))


def write_schematic(sch: Schematic, date: Optional[str] = None, validate: bool = True) -> str:
    """SCH_SCREEN::Save (sch_screen.cpp:499-549)."""
    if validate:
        sch.validate()
    date = date or kicad_date()
    out = ['EESchema Schematic File Version %d  date %s' % (EESCHEMA_VERSION, date)]
    libs = sch.libs or ['']
    for l in libs:
        out.append('LIBS:%s' % l)
    out.append('EELAYER %2d %2d' % (MAX_LAYER, 0))
    out.append('EELAYER END')
    w, h = sch.page_size if (sch.page == 'User' and sch.page_size) else PAGE_SIZES[sch.page]
    out.append('$Descr %s %d %d' % (sch.page, w, h))
    out.append('encoding utf-8')
    out.append('Sheet %d %d' % (sch.sheet_number, sch.sheet_count))
    out.append('Title %s' % escaped(sch.title))
    out.append('Date %s' % escaped(sch.date))
    out.append('Rev %s' % escaped(sch.rev))
    out.append('Comp %s' % escaped(sch.company))
    cm = list(sch.comments) + [''] * 4
    for i in range(4):
        out.append('Comment%d %s' % (i + 1, escaped(cm[i])))
    out.append('$EndDescr')
    for it in sch.items:
        out.extend(format_item(it))
    out.append('$EndSCHEMATC')
    return '\n'.join(out) + '\n'


def save_schematic(sch: Schematic, path: str, date: Optional[str] = None, crlf: bool = True) -> str:
    text = write_schematic(sch, date=date)
    data = text.replace('\n', '\r\n') if crlf else text
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(data)
    return path


# --- Чтение (реплика LoadOneEEFile) ---------------------------------------------

class _Reader:
    """FILE_LINE_READER: строки с сохранением '\\n'; здесь храним без него."""

    def __init__(self, text: str):
        self.lines = text.split('\n')
        if self.lines and self.lines[-1] == '':
            self.lines.pop()
        self.pos = 0
        self.lineno = 0

    def read(self) -> Optional[str]:
        if self.pos >= len(self.lines):
            return None
        line = self.lines[self.pos]
        self.pos += 1
        self.lineno += 1
        return line.rstrip('\r')


def _load_field_line(line: str, rd: _Reader) -> SchField:
    q = line.find('"')
    if q < 0:
        raise SchLoadError('EESchema file lib field F at line %d, aborted' % rd.lineno)
    text, pos = read_delimited(line, q)
    if pos >= len(line):
        raise SchLoadError('Component field F at line %d, aborted' % rd.lineno)
    vals, _ = sscanf(line[2:], '%d')
    fid = vals[0] if vals else 0
    name, _ = read_delimited(line, pos)
    rest = line[pos:]
    vals, cnt = sscanf(rest, '%s %d %d %d %X %s %s')
    f = SchField(fid, text)
    if cnt < 4:
        raise SchLoadError('Component Field error line %d (only %d of 4+ tokens; C++ keeps garbage)' % (rd.lineno, cnt))
    orient, f.x, f.y, f.size = vals[:4]
    if cnt >= 5:
        f.hidden = bool(vals[4] & 1)
    if f.size == 0 or cnt == 4:
        f.size = M.DEFAULT_SIZE_TEXT
    f.vertical = orient[0] == 'V'
    if cnt >= 7:
        h, v = vals[5], vals[6]
        f.hjust = {'L': M.HJust.LEFT, 'R': M.HJust.RIGHT}.get(h[0], M.HJust.CENTER)
        f.vjust = {'B': M.VJust.BOTTOM, 'T': M.VJust.TOP}.get(v[0], M.VJust.CENTER)
        f.italic = len(v) > 1 and v[1] == 'I'
        f.bold = len(v) > 2 and v[2] == 'B'
    if fid >= M.MANDATORY_FIELDS:
        f.name = name or M.default_field_name(fid)
    if fid == M.REFERENCE and text.startswith('#'):
        f.hidden = True
    return f


def _load_component(rd: _Reader, first: str, w: List[str]) -> SchComponent:
    newfmt = first.startswith('$')
    line = first
    if newfmt:
        line = rd.read()
        if line is None:
            raise SchLoadError('EOF after $Comp')
    vals, cnt = sscanf(line[1:], '%s %s')
    if cnt != 2:
        raise SchLoadError('EESchema Component descr error at line %d, aborted' % rd.lineno)
    name1, name2 = vals
    lib_name = '' if name1 == NULL_STRING else decode_sch_name(name1)
    ref = '' if name2 == NULL_STRING else decode_sch_name(name2)
    comp = SchComponent(lib_name, ref, 0, 0)
    ts = 0
    while True:
        line = rd.read()
        if line is None:
            raise SchLoadError('EOF inside $Comp')
        if line.startswith('U'):
            vals, cnt = sscanf(line[1:], '%d %d %lX')
            if cnt >= 1:
                comp.unit = vals[0]
            if cnt >= 2:
                comp.convert = vals[1]
            if cnt >= 3:
                ts = vals[2]
            if cnt < 3:
                w.append('line %d: U line has only %d of 3 values (not checked by C++)' % (rd.lineno, cnt))
        elif line.startswith('P'):
            vals, cnt = sscanf(line[1:], '%d %d')
            if cnt == 2:
                comp.x, comp.y = vals
            else:
                w.append('line %d: P line malformed (not checked by C++)' % rd.lineno)
        elif line.startswith('AR'):
            p, pos = read_delimited(line, 2)
            r, pos = read_delimited(line, pos)
            part_s, _ = read_delimited(line, pos)
            part = int(part_s) if part_s.strip().lstrip('-').isdigit() else comp.unit
            if part < 0 or part > 25:
                part = 1
            comp.ar.append((p, r, part))
            comp.reference = r
        elif line.startswith('F'):
            comp.fields.append(_load_field_line(line, rd))
        else:
            break
    vals, cnt = sscanf(line, '%d %d %d')
    if cnt != 3:
        raise SchLoadError('Component unit & pos error at line %d, aborted' % rd.lineno)
    comp.unit, comp.x, comp.y = vals
    line = rd.read()
    if line is None:
        raise SchLoadError('Component orient error at line %d, aborted' % rd.lineno)
    vals, cnt = sscanf(line, '%d %d %d %d')
    if cnt != 4:
        raise SchLoadError('Component orient error at line %d, aborted' % rd.lineno)
    m = tuple(vals)
    comp.orientation = Orientation.name(m)
    if comp.orientation == '?':
        w.append('line %d: transform %s is not one of the 8 KiCad matrices' % (rd.lineno, m))
    comp.timestamp = ts
    if newfmt:
        line = rd.read()
        if line is None or line[:4].lower() != '$end':
            raise SchLoadError('Component End expected at line %d, aborted' % rd.lineno)
    ref_f = comp.field(M.REFERENCE)
    if ref_f is not None and not comp.ar:
        comp.reference = ref_f.text
    val_f = comp.field(M.VALUE)
    if val_f is not None:
        comp.value = val_f.text
    return comp


def _load_two_point(rd: _Reader, first: str, w: List[str]):
    sline = first[first.find(' '):] if ' ' in first else ''
    vals, cnt = sscanf(sline, '%s %s')
    if cnt != 2:
        raise SchLoadError('EESchema file %s load error at line %d' % (first.split()[0], rd.lineno))
    n1 = vals[0]
    line = rd.read()
    if line is None:
        raise SchLoadError('EOF after %s' % first)
    vals, cnt = sscanf(line, '%d %d %d %d')
    if cnt != 4:
        raise SchLoadError('EESchema file Segment struct error at line %d, aborted' % rd.lineno)
    x1, y1, x2, y2 = vals
    if first.startswith('Wire'):
        layer = 'Wire' if n1[0] == 'W' else 'Bus' if n1[0] == 'B' else 'Notes'
        return Wire(x1, y1, x2, y2, layer) if layer != 'Bus' else Bus(x1, y1, x2, y2)
    return BusEntry(x1, y1, x2 - x1, y2 - y1, bus=(n1[0] == 'B'))


def _load_text(rd: _Reader, first: str, version: int, w: List[str]):
    sline = first[first.find(' '):] if ' ' in first else ''
    vals, cnt = sscanf(sline, '%s %d %d %d %d %s %s %d')
    if cnt < 4:
        raise SchLoadError('EESchema file text load error at line %d' % rd.lineno)
    kind = vals[0]
    x, y, orient = vals[1:4]
    size = vals[4] if cnt >= 5 else 0
    n2 = vals[5] if cnt >= 6 else ''
    n3 = vals[6] if cnt >= 7 else ''
    thick = vals[7] if cnt >= 8 else 0
    if size == 0:
        size = M.DEFAULT_SIZE_TEXT
    text = rd.read()
    if text is None:
        raise SchLoadError('EOF after text header at line %d' % rd.lineno)
    if text == '':
        raise SchLoadError('empty text line at %d: strtok returns NULL -> fatal' % rd.lineno)
    if orient not in (0, 1, 2, 3):
        w.append('line %d: text orient %d treated as 0' % (rd.lineno, orient))
        orient = 0
    k = kind[0]
    if k == 'L':
        return Label(x, y, text, orient, size, n2.lower() == 'italic', n3.lstrip('-').isdigit() and int(n3) != 0)
    if k == 'G' and version > 1 or k == 'H':
        shape = next((s for s in SHAPE_NAMES if s.lower() == n2.lower()), 'Input')
        cls = GlobalLabel if k == 'G' else HierLabel
        return cls(x, y, text, orient, size, n3.lower() == 'italic', thick != 0, shape)
    if k == 'G':   # version 1: GLabel == hierarchical
        shape = next((s for s in SHAPE_NAMES if s.lower() == n2.lower()), 'Input')
        return HierLabel(x, y, text, orient, size, n3.lower() == 'italic', thick != 0, shape)
    return Note(x, y, text.replace('\\n', '\n'), orient, size, n2[:6].lower() == 'italic',
                n3.lstrip('-').isdigit() and int(n3) != 0)


def _load_sheet(rd: _Reader, w: List[str]) -> Sheet:
    line = rd.read()
    if line is None or line[0] != 'S':
        raise SchLoadError(' ** EESchema file sheet struct error at line %d, aborted' % rd.lineno)
    vals, cnt = sscanf(line[1:], '%d %d %d %d')
    if cnt != 4:
        raise SchLoadError(' ** EESchema file sheet struct error at line %d, aborted' % rd.lineno)
    sh = Sheet(vals[0], vals[1], vals[2], vals[3], '', '')
    while True:
        line = rd.read()
        if line is None:
            raise SchLoadError('EOF inside $Sheet')
        if line.startswith('U'):
            vals, cnt = sscanf(line[1:], '%lX')
            ts = vals[0] if cnt else 0
            if ts == 0:
                w.append('line %d: sheet timestamp 0 rejected, KiCad regenerates it' % rd.lineno)
                ts = new_timestamp()
            sh.timestamp = ts
            continue
        if line[0] != 'F':
            break
        vals, cnt = sscanf(line[1:], '%d')
        idx = vals[0] if cnt else 0
        q = line.find('"')
        if q < 0:
            raise SchLoadError('EESchema file sheet label error at line %d, aborted' % rd.lineno)
        text, pos = read_delimited(line, q)
        if pos >= len(line):
            raise SchLoadError('EESchema file sheet field error at line %d, aborted' % rd.lineno)
        if idx in (0, 1):
            vals, cnt = sscanf(line[pos:], '%d')
            size = vals[0] if cnt == 1 else M.DEFAULT_SIZE_TEXT
            if cnt != 1:
                w.append('line %d: sheet field size missing' % rd.lineno)
            if size == 0:
                size = M.DEFAULT_SIZE_TEXT
            if idx == 0:
                sh.name, sh.name_size = text, size
            else:
                sh.filename, sh.file_size = text, size
        else:
            # SCH_SHEET_PIN::Load (sch_sheet_pin.cpp:289-377): строго один пробел после F<n> и после стороны
            toks = line.split(' ')
            head = toks[0]
            if len(line) <= len(head) or line[len(head)] != ' ':
                raise SchLoadError('sheet pin line %d: exactly one space required after %s' % (rd.lineno, head))
            after = line[pos:].lstrip(' \t')
            parts = after.split()
            if len(parts) < 2:
                raise SchLoadError('sheet hierarchical label error at line %d' % rd.lineno)
            ctype, side = parts[0], parts[1]
            side_end = after.find(side) + len(side)
            if side_end >= len(after) or after[side_end] != ' ':
                raise SchLoadError('sheet pin line %d: exactly one space required after side letter' % rd.lineno)
            vals, cnt = sscanf(after[side_end + 1:], '%d %d %d')
            if cnt != 3:
                raise SchLoadError('sheet hierarchical label error at line %d' % rd.lineno)
            shape = {v: k for k, v in SHAPE_LETTERS.items()}.get(ctype[0], 'Input')
            sd = side[0] if side[0] in 'LRTB' else 'L'
            size = vals[2] or M.DEFAULT_SIZE_TEXT
            sh.pins.append(SheetPin(text, vals[0], vals[1], shape, sd, size))
    if line[:4].lower() != '$end':
        raise SchLoadError('**** EESchema file sheet error at line %d, aborted' % rd.lineno)
    return sh


def read_schematic(text: str) -> Tuple[Schematic, List[str]]:
    """Реплика SCH_EDIT_FRAME::LoadOneEEFile (load_one_schematic_file.cpp:34-235)."""
    w: List[str] = []
    rd = _Reader(text)
    line = rd.read()
    if line is None or line[9:31] != 'Schematic File Version':
        raise SchLoadError('is NOT an EESchema file! (bytes 9..30 must be "Schematic File Version")')
    ver_s = line[32:].lstrip(''.join(chr(c) for c in range(0x30)))
    vals, cnt = sscanf(ver_s, '%d')
    version = vals[0] if cnt else 0
    if version > EESCHEMA_VERSION:
        w.append('file version %d > %d: KiCad warns but loads' % (version, EESCHEMA_VERSION))
    line = rd.read()
    if line is None or not line.startswith('LIBS:'):
        raise SchLoadError('is NOT an EESchema file! (second line must start with LIBS:)')
    sch = Schematic()
    sch.libs.append(line[5:])
    # LoadLayers: следующая строка — EELAYER (или что угодно), потом пропуск до EELAYER END
    line = rd.read()
    if line is None:
        raise SchLoadError('EOF before EELAYER')
    if not line.startswith('EELAYER'):
        if line.startswith('LIBS:'):
            sch.libs.append(line[5:])
        else:
            w.append('line %d: expected EELAYER, got %r (tolerated: NumberOfLayers=MAX_LAYER)' % (rd.lineno, line))
    while True:
        line = rd.read()
        if line is None:
            raise SchLoadError('EELAYER END missing: the skip loop eats the whole file (empty schematic)')
        if line[:11].lower() == 'eelayer end':
            break
        if line.startswith('LIBS:'):
            sch.libs.append(line[5:])
    seen_descr = False
    item_loaded = False
    while True:
        line = rd.read()
        if line is None:
            break
        if line == '':
            raise SchLoadError('EESchema file undefined object at line %d, aborted (blank line)' % rd.lineno)
        c0 = line[0]
        item = None
        if c0 == '$':
            if line[1:2] == 'C':
                item = _load_component(rd, line, w)
            elif line[1:2] == 'S':
                item = _load_sheet(rd, w)
            elif line[1:2] == 'D':
                _read_descr(rd, line, sch, w)
                seen_descr = True
                item_loaded = True
                continue
            else:
                # $EndSCHEMATC и прочее: item == NULL, itemLoaded не меняется
                if not item_loaded:
                    raise SchLoadError('line %d: %r before any loaded item -> stale itemLoaded==false aborts' % (rd.lineno, line))
                continue
        elif c0 == 'L':
            item = _load_component(rd, line, w)
        elif c0 in 'WE':
            item = _load_two_point(rd, line, w)
        elif c0 == 'P':
            sline = line[line.find(' '):] if ' ' in line else ''
            vals, cnt = sscanf(sline, '%s %s %d')
            if cnt != 3:
                raise SchLoadError('EESchema file polyline struct error at line %d, aborted' % rd.lineno)
            n2, npts = vals[1], vals[2]
            layer = 'Wire' if n2[0] == 'W' else 'Bus' if n2[0] == 'B' else 'Notes'
            pts = []
            for _ in range(npts):
                pl = rd.read()
                if pl is None:
                    raise SchLoadError('EOF in polyline')
                vals, cnt = sscanf(pl, '%d %d')
                if cnt != 2:
                    raise SchLoadError('EESchema file polyline struct error at line %d, aborted' % rd.lineno)
                pts.append(tuple(vals))
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                sch.items.append(Wire(ax, ay, bx, by, layer))
            item_loaded = True
            continue
        elif c0 == 'C':
            vals, cnt = sscanf(line[line.find(' '):] if ' ' in line else '', '%s %d %d')
            if cnt != 3:
                raise SchLoadError('EESchema file connection load error at line %d' % rd.lineno)
            item = Junction(vals[1], vals[2])
        elif c0 == 'K':
            if not item_loaded:
                raise SchLoadError('line %d: K (marker) before any item -> stale itemLoaded==false aborts' % rd.lineno)
            continue
        elif c0 == 'N':
            vals, cnt = sscanf(line[line.find(' '):] if ' ' in line else '', '%s %d %d')
            if cnt != 3:
                raise SchLoadError('EESchema file No Connect load error at line %d' % rd.lineno)
            item = NoConnect(vals[1], vals[2])
        elif c0 == 'T':
            item = _load_text(rd, line, version, w)
        else:
            raise SchLoadError('EESchema file undefined object at line %d, aborted: %r' % (rd.lineno, line))
        sch.items.append(item)
        item_loaded = True
    if not seen_descr:
        w.append('no $Descr block')
    return sch, w


def _read_descr(rd: _Reader, line: str, sch: Schematic, w: List[str]) -> None:
    vals, cnt = sscanf(line, '%s %s %d %d')
    page = vals[1] if cnt >= 2 else ''
    match = next((k for k in PAGE_SIZES if k.lower() == page.lower()), None)
    if match is None:
        w.append('line %d: unknown page %r -> falls back to User' % (rd.lineno, page))
        match = 'User'
    sch.page = match
    if match == 'User' and cnt >= 4:
        sch.page_size = (vals[2], vals[3])
    while True:
        line = rd.read()
        if line is None:
            w.append('$EndDescr missing: everything after is lost')
            return
        if line[:4].lower() == '$end':
            return
        low = line.lower()
        if low.startswith('sh'):
            vals, cnt = sscanf(line[5:], ' %d %d')
            if cnt == 2:
                sch.sheet_number, sch.sheet_count = vals
        elif low.startswith('ti'):
            sch.title = read_delimited(line)[0]
        elif low.startswith('da'):
            sch.date = read_delimited(line)[0]
        elif low.startswith('re'):
            sch.rev = read_delimited(line)[0]
        elif low.startswith('comp'):
            sch.company = read_delimited(line)[0]
        elif low.startswith('comment') and len(line) > 7 and line[7] in '1234':
            sch.comments[int(line[7]) - 1] = read_delimited(line)[0]


def load_schematic(path: str) -> Tuple[Schematic, List[str]]:
    with io.open(path, 'rb') as fh:
        data = fh.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('cp1251')
    return read_schematic(text)
