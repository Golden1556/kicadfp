"""Строгий читатель .lib/.dcm — реплика загрузчика EESchema bzr2986.

Повторяет логику CMP_LIBRARY::Load (class_library.cpp:400-542),
LIB_COMPONENT::Load (class_libentry.cpp:680-960), LIB_*::Load (lib_*.cpp)
с теми же минимумами sscanf и теми же сообщениями об ошибках. Дополнительно
сообщает о ситуациях, которые в C++ являются UB/крахом (переполнение буферов,
NULL в strtok), — как об ошибках.

Уровни:
- LibLoadError — то, что в C++ роняет загрузку всей библиотеки;
- ошибка компонента — в C++ только warning (компонент пропускается); здесь
  при strict=True поднимается LibLoadError, при strict=False копится в warnings.
"""

from __future__ import annotations

import io
import os
from typing import List, Optional, Tuple

from . import model as M
from .sscanf import sscanf
from .textio import read_delimited, decode_lib_text_quoted, decode_lib_text_bare

LINE_BUFFER_LEN_LARGE = 8000   # general.h:27


class LibLoadError(Exception):
    pass


class _ComponentError(Exception):
    pass


class _Lines:
    """GetLine (common/string.cpp:157-169): пропускает строки, начинающиеся с
    '#', пустые и начинающиеся с \\r/\\n; обрезает \\r\\n."""

    def __init__(self, text: str):
        self.raw = text.split('\n')
        self.pos = 0
        self.lineno = 0
        self.warnings: List[str] = []

    def next(self) -> Optional[str]:
        while self.pos < len(self.raw):
            line = self.raw[self.pos]
            self.pos += 1
            self.lineno += 1
            if len(line) + 1 >= LINE_BUFFER_LEN_LARGE:
                raise LibLoadError('line %d longer than %d bytes: fgets would split it'
                                   % (self.lineno, LINE_BUFFER_LEN_LARGE))
            if line == '' or line[0] in '#\r\n':
                continue
            return line.rstrip('\r\n')
        return None


def _tok(s: str) -> List[str]:
    """strtok(s, " \\t\\n") / " \\t\\r\\n"."""
    return s.replace('\r', ' ').replace('\t', ' ').split()


def _check_buf(tok: str, size: int, what: str) -> None:
    if len(tok.encode('utf-8')) >= size:
        raise _ComponentError('%s %r is %d bytes: overflows the C buffer of %d (undefined behaviour)'
                              % (what, tok, len(tok.encode('utf-8')), size))


# --- поля --------------------------------------------------------------------

def _load_field(line: str) -> M.Field:
    """LIB_FIELD::Load (lib_field.cpp:147-268)."""
    vals, cnt = sscanf(line[1:], '%d')
    if cnt != 1 or vals[0] < 0:
        raise _ComponentError('invalid field header')
    fid = vals[0]
    # первый токен уже "обрезан" strtok'ом — ищем кавычку после него
    first_end = 0
    while first_end < len(line) and not line[first_end].isspace():
        first_end += 1
    q = line.find('"', first_end)
    if q < 0:
        raise _ComponentError('field %d: text must be double-quoted (no " found)' % fid)
    text, pos = read_delimited(line, q)
    if pos >= len(line):
        raise _ComponentError('field %d: nothing after the closing quote' % fid)
    rest = line[pos:]
    vals, cnt = sscanf(rest, ' %d %d %d %c %c %c %s')
    if cnt < 5:
        raise _ComponentError('field %d does not have the correct number of parameters' % fid)
    x, y, size, orient, visible = vals[:5]
    if orient == 'H':
        vertical = False
    elif orient == 'V':
        vertical = True
    else:
        raise _ComponentError('field %d text orientation parameter <%s> is not valid' % (fid, orient))
    if visible == 'V':
        vis = True
    elif visible == 'I':
        vis = False
    else:
        raise _ComponentError('field %d text visible parameter <%s> is not valid' % (fid, visible))
    hj, vj, italic, bold = M.HJust.CENTER, M.VJust.CENTER, False, False
    if cnt >= 6:
        h = vals[5]
        if h == 'C':
            hj = M.HJust.CENTER
        elif h == 'L':
            hj = M.HJust.LEFT
        elif h == 'R':
            hj = M.HJust.RIGHT
        else:
            raise _ComponentError('field %d text horizontal justification parameter <%s> is not valid' % (fid, h))
        vtok = vals[6] if cnt >= 7 else ''   # cnt == 6 -> textVJustify[0] == 0 -> ошибка
        v0 = vtok[0] if vtok else ''
        if v0 == 'C':
            vj = M.VJust.CENTER
        elif v0 == 'B':
            vj = M.VJust.BOTTOM
        elif v0 == 'T':
            vj = M.VJust.TOP
        else:
            raise _ComponentError('field %d text vertical justification parameter <%s> is not valid'
                                  ' (6 tokens after the text is fatal: hjust without vjust)' % (fid, v0))
        italic = len(vtok) > 1 and vtok[1] == 'I'
        bold = len(vtok) > 2 and vtok[2] == 'B'
    name: Optional[str] = None
    if fid >= M.MANDATORY_FIELDS:
        nm, _ = read_delimited(line, pos)
        name = nm if nm else None
    return M.Field(fid, text, x, y, size, vertical, vis, hj, vj, italic, bold, name)


# --- графика -------------------------------------------------------------------

def _fill_from(tok: Optional[str], warnings: List[str], what: str) -> M.Fill:
    if tok is None:
        warnings.append('%s: fill token missing — C++ reads an uninitialised buffer; write it explicitly' % what)
        return M.Fill.NONE
    if tok[0] == 'F':
        return M.Fill.FOREGROUND
    if tok[0] == 'f':
        return M.Fill.BACKGROUND
    return M.Fill.NONE


def _norm_pos(t: int) -> int:
    """NORMALIZE_ANGLE_POS (include/macros.h:84-87)."""
    while t < 0:
        t += 3600
    while t >= 3600:
        t -= 3600
    return t


def _load_arc(line: str, w: List[str]) -> M.Arc:
    vals, cnt = sscanf(line[2:], '%d %d %d %d %d %d %d %d %s %d %d %d %d')
    if cnt < 8:
        raise _ComponentError('arc only had %d parameters of the required 8' % cnt)
    cx, cy, r, t1, t2, unit, conv, width = vals[:8]
    fill = _fill_from(vals[8] if cnt >= 9 else None, w, 'arc')
    arc = M.Arc(unit, conv, cx, cy, r, _norm_pos(t1), _norm_pos(t2), width, fill)
    if cnt >= 13:
        arc.x1, arc.y1, arc.x2, arc.y2 = vals[9:13]
    else:
        arc.x1, arc.y1, arc.x2, arc.y2 = arc.endpoints()
    return arc


def _load_circle(line: str, w: List[str]) -> M.Circle:
    vals, cnt = sscanf(line[2:], '%d %d %d %d %d %d %s')
    if cnt < 6:
        raise _ComponentError('circle only had %d parameters of the required 6' % cnt)
    cx, cy, r, unit, conv, width = vals[:6]
    return M.Circle(unit, conv, cx, cy, r, width, _fill_from(vals[6] if cnt >= 7 else None, w, 'circle'))


def _load_rect(line: str, w: List[str]) -> M.Rect:
    vals, cnt = sscanf(line[2:], '%d %d %d %d %d %d %d %s')
    if cnt < 7:
        raise _ComponentError('rectangle only had %d parameters of the required 7' % cnt)
    x1, y1, x2, y2, unit, conv, width = vals[:7]
    return M.Rect(unit, conv, x1, y1, x2, y2, width, _fill_from(vals[7] if cnt >= 8 else None, w, 'rectangle'))


def _load_poly(line: str, w: List[str], bezier: bool):
    name = 'Bezier' if bezier else 'polyline'
    vals, cnt = sscanf(line[2:], '%d %d %d %d')
    if (cnt != 4) if bezier else (cnt < 4):
        raise _ComponentError('%s only had %d parameters of the required 4' % (name, cnt))
    ccount, unit, conv, width = vals
    if ccount <= 0:
        raise _ComponentError('%s count parameter %d is invalid' % (name, ccount))
    toks = _tok(line[2:])[4:]
    pts = []
    for i in range(ccount):
        if 2 * i >= len(toks):
            if bezier:
                raise _ComponentError('Bezier point %d missing: C++ passes NULL to sscanf (crash)' % i)
            raise _ComponentError('polyline point %d X position not defined' % i)
        xv, xc = sscanf(toks[2 * i], '%d')
        if xc != 1:
            raise _ComponentError('%s point %d X position not defined' % (name, i))
        if 2 * i + 1 >= len(toks):
            if bezier:
                raise _ComponentError('Bezier point %d missing: C++ passes NULL to sscanf (crash)' % i)
            raise _ComponentError('polyline point %d Y position not defined' % i)
        yv, yc = sscanf(toks[2 * i + 1], '%d')
        if yc != 1:
            raise _ComponentError('%s point %d Y position not defined' % (name, i))
        pts.append((xv[0], yv[0]))
    fill = M.Fill.NONE
    rest = toks[2 * ccount:]
    if rest:
        if rest[0][0] == 'F':
            fill = M.Fill.FOREGROUND
        elif rest[0][0] == 'f':
            fill = M.Fill.BACKGROUND
    cls = M.Bezier if bezier else M.Polyline
    return cls(unit, conv, pts, width, fill)


def _load_text(line: str, w: List[str]) -> M.Text:
    vals, cnt = sscanf(line[2:], '%d %d %d %d %d %d %d "%[^"]" %s %d %c %c')
    if cnt >= 8:
        text = decode_lib_text_quoted(vals[7])
    else:
        vals, cnt = sscanf(line[2:], '%d %d %d %d %d %d %d %s %s %d %c %c')
        if cnt < 8:
            raise _ComponentError('text only had %d parameters of the required 8' % cnt)
        text = decode_lib_text_bare(vals[7])
    orient, x, y, size, attr, unit, conv = vals[:7]
    tmp = vals[8] if cnt >= 9 else ''
    thickness = vals[9] if cnt >= 10 else 0
    hj = vals[10] if cnt >= 11 else 'C'
    vj = vals[11] if cnt >= 12 else 'C'
    t = M.Text(unit, conv, text, x, y, size, orient != 0, bool(attr & 1),
               tmp[:6].lower() == 'italic', thickness > 0)
    if orient not in (0, 900):
        w.append('text orientation %d is neither 0 nor 900' % orient)
    t.hjust = {'L': M.HJust.LEFT, 'C': M.HJust.CENTER, 'R': M.HJust.RIGHT}.get(hj, M.HJust.CENTER)
    t.vjust = {'T': M.VJust.TOP, 'C': M.VJust.CENTER, 'B': M.VJust.BOTTOM}.get(vj, M.VJust.CENTER)
    return t


def _load_pin(line: str, w: List[str]) -> M.Pin:
    vals, cnt = sscanf(line[2:], '%s %s %d %d %d %s %d %d %d %d %s %s')
    if cnt < 11:
        raise _ComponentError('pin only had %d parameters of the required 11 or 12' % cnt)
    name, num, x, y, length, orient, nsz, nmsz, unit, conv, ptype = vals[:11]
    _check_buf(name, 256, 'pin name')
    _check_buf(num, 64, 'pin number')
    _check_buf(orient, 64, 'pin orientation')
    _check_buf(ptype, 64, 'pin type')
    if len(num.encode('utf-8')) > 4:
        w.append('pin number %r truncated to 4 bytes by strncpy' % num)
        num = num.encode('utf-8')[:4].decode('utf-8', 'ignore')
    o = orient[0]
    try:
        orientation = M.PinOrient(o)
    except ValueError:
        w.append('pin orientation %r is not R/L/U/D (C++ stores it verbatim, draws a degenerate pin)' % o)
        orientation = M.PinOrient.RIGHT
    try:
        etype = M.PinType.from_letter(ptype[0])
    except M.ValidationError as e:
        raise _ComponentError(str(e))
    pin = M.Pin(unit, conv, name, num, x, y, length, orientation, nsz, nmsz, etype)
    if cnt == 12:
        attrs = vals[11]
        _check_buf(attrs, 64, 'pin attributes')
        for ch in reversed(attrs):
            if ch == '~':
                continue
            if ch == 'N':
                pin.visible = False
            elif ch == 'I':
                pin.shape |= M.PinShape.INVERT
            elif ch == 'C':
                pin.shape |= M.PinShape.CLOCK
            elif ch == 'L':
                pin.shape |= M.PinShape.LOWLEVEL_IN
            elif ch == 'V':
                pin.shape |= M.PinShape.LOWLEVEL_OUT
            elif ch == 'F':
                pin.shape |= M.PinShape.CLOCK_FALL
            elif ch == 'X':
                pin.shape |= M.PinShape.NONLOGIC
            else:
                raise _ComponentError('unknown pin attribute [%s]' % ch)
    return pin


def _load_draw_entries(lines: _Lines, c: M.Component, w: List[str]) -> None:
    """LIB_COMPONENT::LoadDrawEntries (class_libentry.cpp:811-890)."""
    while True:
        line = lines.next()
        if line is None:
            raise _ComponentError('file ended prematurely loading component draw element')
        if line.startswith('ENDDRAW'):
            return
        if not line.strip():
            raise _ComponentError('whitespace-only line inside DRAW at %d: aLine[0] is a space -> "undefined DRAW command"' % lines.lineno)
        ch = line[0]
        try:
            if ch == 'A':
                item = _load_arc(line, w)
            elif ch == 'C':
                item = _load_circle(line, w)
            elif ch == 'T':
                item = _load_text(line, w)
            elif ch == 'S':
                item = _load_rect(line, w)
            elif ch == 'X':
                item = _load_pin(line, w)
            elif ch == 'P':
                item = _load_poly(line, w, False)
            elif ch == 'B':
                item = _load_poly(line, w, True)
            else:
                raise _ComponentError('undefined DRAW command %s' % ch)
        except _ComponentError as e:
            raise _ComponentError('error <%s> in DRAW command %s (line %d)' % (e, ch, lines.lineno))
        c.items.append(item)


def _load_component(lines: _Lines, first: str, w: List[str]) -> M.Component:
    """LIB_COMPONENT::Load (class_libentry.cpp:680-808)."""
    toks = _tok(first)
    if toks[0] != 'DEF':
        raise _ComponentError('DEF command expected in line %d, aborted.' % lines.lineno)
    try:
        name, prefix, unused, offset, drawnum, drawname, unitcount = toks[1:8]
        vals, cnt = sscanf(unused, '%d')
        assert cnt == 1
        vals, cnt = sscanf(offset, '%d')
        assert cnt == 1
        pin_name_offset = vals[0]
        vals, cnt = sscanf(unitcount, '%d')
        assert cnt == 1
        unit_count = vals[0]
    except (ValueError, AssertionError):
        raise _ComponentError('Wrong DEF format in line %d, skipped.' % lines.lineno)
    if unit_count < 1:
        w.append('DEF unit count %d < 1 coerced to 1' % unit_count)
        unit_count = 1
    show_num = drawnum[0] != 'N'
    show_name = drawname[0] != 'N'
    value_visible = not name.startswith('~')
    if not value_visible:
        name = name[1:]
    ref = '' if prefix == '~' else prefix
    locked = len(toks) > 8 and toks[8][0] == 'L'
    power = len(toks) > 9 and toks[9][0] == 'P'
    if name != name.upper():
        w.append('DEF name %r is uppercased on load (strupper); the F1 value keeps its case' % name)
    c = M.Component(name.upper(), ref, pin_name_offset, show_num, show_name, unit_count,
                    locked, power, value_visible)
    c.fields.append(M.Field(M.REFERENCE, ref, visible=bool(ref)))
    c.fields.append(M.Field(M.VALUE, name.upper(), visible=value_visible))
    saw_enddef = False
    while True:
        line = lines.next()
        if line is None:
            break
        if not line.strip():
            raise _ComponentError('whitespace-only line inside DEF at %d: strtok returns NULL -> strcmp(NULL) crash' % lines.lineno)
        toks = _tok(line)
        p = toks[0]
        if line[0] == 'T' and len(line) > 1 and line[1] == 'i':
            raise _ComponentError('"Ti" (date) line at %d: LoadDateAndTime always fails in this version '
                                  '(sscanf on the strtok-truncated buffer) -> component rejected' % lines.lineno)
        if line[0] == 'F':
            f = _load_field(line)
            if f.id < M.MANDATORY_FIELDS:
                for i, old in enumerate(c.fields):
                    if old.id == f.id:
                        c.fields[i] = f
                        break
                else:
                    c.fields.append(f)
                if f.id == M.VALUE:
                    c.name = f.text
                    c.value_visible = f.visible
                if f.id == M.REFERENCE:
                    c.reference = f.text
            else:
                c.fields.append(f)
            continue
        if p == 'ENDDEF':
            saw_enddef = True
            break
        if p == 'DRAW':
            _load_draw_entries(lines, c, w)
            continue
        if p.startswith('ALIAS'):
            c.aliases.extend(toks[1:])
            continue
        if p.startswith('$FPLI'):
            while True:
                line = lines.next()
                if line is None:
                    raise _ComponentError('file ended prematurely while loading footprints')
                if line.lower() == '$endfplist':
                    break
                c.fplist.append(line[1:])
            continue
        w.append('line %d ignored inside DEF: %r' % (lines.lineno, line))
    if not saw_enddef:
        w.append('component %s: ENDDEF missing at end of file (accepted by C++)' % c.name)
    return c


def read_library(text: str, strict: bool = True) -> Tuple[M.Library, List[str]]:
    """Разбирает текст .lib. Возвращает (Library, warnings)."""
    lines = _Lines(text)
    w = lines.warnings
    header = lines.next()
    if header is None:
        raise LibLoadError('The file is empty!')
    toks = header.split()
    if not toks or not toks[0].upper().startswith('EESCHEMA-LIB'):
        raise LibLoadError('The file is NOT an EESCHEMA library!')
    if len(toks) < 2:
        raise LibLoadError('The file header is missing version and time stamp information.')
    if toks[1] != 'Version' or len(toks) < 3:
        raise LibLoadError('The file header version information is invalid.')
    ver = toks[2].split('.')
    try:
        major, minor = int(ver[0]), int(ver[1])
        if major < 1 or minor < 0 or minor > 99:
            raise ValueError
    except (ValueError, IndexError):
        w.append('header version %r malformed: versionMajor/Minor stay uninitialised in C++' % toks[2])
        major, minor = 2, 3
    if (major, minor) != (2, 3):
        w.append('library version %d.%d (this KiCad writes 2.3)' % (major, minor))
    lib = M.Library()
    while True:
        line = lines.next()
        if line is None:
            break
        if line[:7].upper() == '$HEADER':
            while True:
                line = lines.next()
                if line is None:
                    raise LibLoadError('An error occurred attempting to read the header.')
                if _tok(line) and _tok(line)[0].lower() == '$endheader':
                    break
            continue
        if line[:3].upper() == 'DEF':
            start = lines.lineno
            try:
                c = _load_component(lines, line, w)
            except _ComponentError as e:
                msg = 'component starting at line %d rejected: %s' % (start, e)
                if strict:
                    raise LibLoadError(msg)
                w.append(msg)
                # C++: только для "Wrong DEF format" перематывает до ENDDEF; для прочих ошибок
                # чтение продолжается со следующей строки — повторяем.
                continue
            if lib.find(c.name) is not None:
                w.append('duplicate component name %r' % c.name)
            for a in c.aliases:
                if lib.find(a) is not None:
                    w.append('duplicate alias name %r' % a)
            lib.components.append(c)
        else:
            w.append('top-level line %d ignored: %r' % (lines.lineno, line))
    return lib, w


def read_doclib(text: str, lib: M.Library) -> List[str]:
    """CMP_LIBRARY::LoadDocs (class_library.cpp:583-663). Заполняет описания в lib.
    Ошибки формата поднимают LibLoadError (в C++ результат игнорируется, но файл
    перестаёт читаться с этого места)."""
    lines = _Lines(text)
    w = lines.warnings
    header = lines.next()
    if header is None:
        raise LibLoadError('Component document library file is empty.')
    if header[:10].lower() != 'eeschema-d':
        raise LibLoadError('File is not a valid component library document file.')
    while True:
        line = lines.next()
        if line is None:
            break
        if not line.startswith('$CMP'):
            raise LibLoadError('$CMP command expected in line %d, aborted.' % lines.lineno)
        if len(line) < 5:
            raise LibLoadError('line %d: "$CMP" without a name (C++ reads past the terminator)' % lines.lineno)
        name = line[5:]
        comp = lib.find(name)
        if comp is None:
            w.append('doc entry %r has no matching component/alias (silently ignored by C++)' % name)
        while True:
            line = lines.next()
            if line is None:
                w.append('$ENDCMP missing at EOF')
                break
            if line.startswith('$ENDCMP'):
                break
            value = line[2:]
            if comp is not None:
                target = comp
                if comp.name.casefold() != name.casefold():
                    docs = getattr(comp, 'alias_docs', None)
                    if docs is None:
                        comp.alias_docs = docs = {}
                    d = list(docs.get(name, ('', '', '')))
                    idx = {'D': 0, 'K': 1, 'F': 2}.get(line[0])
                    if idx is not None:
                        d[idx] = value
                        docs[name] = tuple(d)
                    continue
                if line[0] == 'D':
                    target.description = value
                elif line[0] == 'K':
                    target.keywords = value
                elif line[0] == 'F':
                    target.docfile = value
                else:
                    w.append('line %d ignored inside $CMP: %r' % (lines.lineno, line))
    return w


def _read_text(path: str) -> str:
    with io.open(path, 'rb') as fh:
        data = fh.read()
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1251')


def load_library(path: str, strict: bool = True, with_doc: bool = True) -> Tuple[M.Library, List[str]]:
    """Читает <path>.lib (+ <path>.dcm, если есть)."""
    lib, w = read_library(_read_text(path), strict=strict)
    base, ext = os.path.splitext(path)
    dcm = base + '.dcm'
    if with_doc and os.path.exists(dcm):
        w.extend(read_doclib(_read_text(dcm), lib))
    return lib, w
