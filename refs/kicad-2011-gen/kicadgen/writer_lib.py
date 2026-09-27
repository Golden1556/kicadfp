"""Запись .lib и .dcm байт-в-байт по fprintf-форматам EESchema bzr2986.

Ссылки: class_library.cpp:789-810 (заголовок), :666-727 (Save),
class_libentry.cpp:536-677 (LIB_COMPONENT::Save), lib_*.cpp (::Save).
"""

from __future__ import annotations

import io
from typing import Iterable, List, Optional

from . import model as M
from .textio import escaped, encode_lib_text, kicad_date

LIB_IDENT = 'EESchema-LIBRARY Version'
LIB_VERSION = '2.3'
DOC_IDENT = 'EESchema-DOCLIB  Version 2.0'   # два пробела — так в class_library.h:41


def _fill(f: M.Fill) -> str:
    return f.value


def _norm_angle_for_save(t: int) -> int:
    """lib_arc.cpp:90-98: сначала KiCad хранит угол в [0,3600), при записи
    переводит > 1800 в отрицательные."""
    t = t % 3600
    if t > 1800:
        t -= 3600
    return t


def format_field(f: M.Field) -> str:
    """LIB_FIELD::Save (lib_field.cpp:94-144)."""
    text = f.text if f.text != '' else '~'
    line = 'F%d %s %d %d %d %c %c %c %c%c%c' % (
        f.id, escaped(text), f.x, f.y, f.size,
        'V' if f.vertical else 'H',
        'V' if f.visible else 'I',
        f.hjust.value, f.vjust.value,
        'I' if f.italic else 'N',
        'B' if f.bold else 'N')
    if f.id >= M.MANDATORY_FIELDS and f.name and f.name != M.default_field_name(f.id):
        line += ' ' + escaped(f.name)
    return line


def format_item(it: M.DrawItem) -> str:
    if isinstance(it, M.Arc):
        x1, y1, x2, y2 = it.endpoints()
        return 'A %d %d %d %d %d %d %d %d %c %d %d %d %d' % (
            it.cx, it.cy, it.radius,
            _norm_angle_for_save(it.t1), _norm_angle_for_save(it.t2),
            it.unit, it.convert, it.width, _fill(it.fill), x1, y1, x2, y2)
    if isinstance(it, M.Circle):
        return 'C %d %d %d %d %d %d %c' % (
            it.cx, it.cy, it.radius, it.unit, it.convert, it.width, _fill(it.fill))
    if isinstance(it, M.Rect):
        return 'S %d %d %d %d %d %d %d %c' % (
            it.x1, it.y1, it.x2, it.y2, it.unit, it.convert, it.width, _fill(it.fill))
    if isinstance(it, (M.Polyline, M.Bezier)):
        letter = 'P' if isinstance(it, M.Polyline) else 'B'
        s = '%s %d %d %d %d' % (letter, len(it.points), it.unit, it.convert, it.width)
        for (x, y) in it.points:
            s += '  %d %d' % (x, y)          # два пробела — lib_polyline.cpp:49
        return s + ' %c' % _fill(it.fill)
    if isinstance(it, M.Text):
        # lib_text.cpp:55-74: "T ... %s " + " %s %d" + " %c %c" -> два пробела перед Italic/Normal
        s = 'T %d %d %d %d %d %d %d %s ' % (
            900 if it.vertical else 0, it.x, it.y, it.size, 1 if it.hidden else 0,
            it.unit, it.convert, encode_lib_text(it.text))
        s += ' %s %d' % ('Italic' if it.italic else 'Normal', 1 if it.bold else 0)
        s += ' %c %c' % (it.hjust.value, it.vjust.value)
        return s
    if isinstance(it, M.Pin):
        name = it.name if it.name else '~'
        num = it.number if it.number else '~'
        s = 'X %s %s %d %d %d %c %d %d %d %d %c' % (
            name, num, it.x, it.y, it.length, it.orient.value,
            it.num_size, it.name_size, it.unit, it.convert, it.etype.value)
        attrs = ''
        if not it.visible:
            attrs += 'N'
        for flag, letter in M._SHAPE_LETTERS:
            if it.shape & flag:
                attrs += letter
        if attrs:
            s += ' ' + attrs
        return s
    raise TypeError('unknown draw item %r' % (it,))


def format_component(c: M.Component, sort_items: bool = True) -> List[str]:
    """LIB_COMPONENT::Save (class_libentry.cpp:536-677) -> список строк без \\n."""
    c.ensure_mandatory_fields()
    value = c.get_field(M.VALUE)
    ref = c.get_field(M.REFERENCE)
    assert value is not None and ref is not None
    # DEF использует текст поля Value как имя (class_libentry.cpp:549-558)
    name_text = value.text
    lines = ['#', '# %s' % name_text, '#']
    lines.append('DEF %s%s %s %d %d %c %c %d %c %c' % (
        '' if value.visible else '~', name_text,
        ref.text if ref.text else '~',
        0, c.pin_name_offset,
        'Y' if c.show_pin_numbers else 'N',
        'Y' if c.show_pin_names else 'N',
        c.unit_count,
        'L' if c.units_locked else 'F',
        'P' if c.power else 'N'))
    # Строка Ti НЕ пишется: загрузчик этой версии её не умеет читать (см. docs).
    mandatory = [c.get_field(i) for i in range(M.MANDATORY_FIELDS)]
    for f in mandatory:
        if f is not None and f.text != '':
            lines.append(format_field(f))
    user = sorted((f for f in c.fields if f.id >= M.MANDATORY_FIELDS), key=lambda f: f.id)
    next_id = M.MANDATORY_FIELDS
    for f in user:
        if f.text == '':
            continue
        f2 = M.Field(**{**f.__dict__, 'id': next_id})
        next_id += 1
        lines.append(format_field(f2))
    if c.aliases:
        lines.append('ALIAS ' + ' '.join(c.aliases))
    if c.fplist:
        lines.append('$FPLIST')
        for fp in c.fplist:
            lines.append(' ' + fp)             # ведущий пробел — class_libentry.cpp:642
        lines.append('$ENDFPLIST')
    if c.items:
        items = sorted(c.items, key=M.item_sort_key) if sort_items else list(c.items)
        lines.append('DRAW')
        for it in items:
            lines.append(format_item(it))
        lines.append('ENDDRAW')
    lines.append('ENDDEF')
    return lines


def write_library(lib: M.Library, date: Optional[str] = None, sort_items: bool = True,
                  validate: bool = True) -> str:
    """Полный текст .lib (с '\\n'; конвертация в CRLF — при сохранении)."""
    if validate:
        lib.validate()
    date = date or kicad_date()
    out = ['%s %s  Date: %s' % (LIB_IDENT, LIB_VERSION, date), '#encoding utf-8']
    # KiCad пишет компоненты в порядке map (без учёта регистра); повторяем.
    comps = sorted(lib.components, key=lambda c: c.name.casefold())
    for c in comps:
        out.extend(format_component(c, sort_items=sort_items))
    out.append('#')
    out.append('#End Library')
    return '\n'.join(out) + '\n'


def write_doclib(lib: M.Library, date: Optional[str] = None) -> str:
    """CMP_LIBRARY::SaveDocFile (class_library.cpp:730-786) + LIB_ALIAS::SaveDoc
    (class_libentry.cpp:104-128). Пишется по всем алиасам в порядке map."""
    date = date or kicad_date()
    out = ['%s  Date: %s' % (DOC_IDENT, date)]
    entries = []
    for c in lib.components:
        entries.append((c.name, c.description, c.keywords, c.docfile))
        for a in c.aliases:
            d = c.alias_docs.get(a) if hasattr(c, 'alias_docs') else None
            if d:
                entries.append((a, d[0], d[1], d[2]))
    for name, desc, kw, doc in sorted(entries, key=lambda e: e[0].casefold()):
        if not (desc or kw or doc):
            continue
        out.append('#')
        out.append('$CMP %s' % name)
        if desc:
            out.append('D %s' % desc)
        if kw:
            out.append('K %s' % kw)
        if doc:
            out.append('F %s' % doc)
        out.append('$ENDCMP')
    out.append('#')
    out.append('#End Doc Library')
    return '\n'.join(out) + '\n'


def _write_text(path: str, text: str, crlf: bool) -> None:
    data = text.replace('\n', '\r\n') if crlf else text
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(data)


def save_library(lib: M.Library, path: str, date: Optional[str] = None,
                 crlf: bool = True, with_doc: bool = True, sort_items: bool = True) -> List[str]:
    """Сохраняет <path>.lib и (по умолчанию) <path>.dcm рядом. Возвращает список
    записанных файлов. CRLF по умолчанию — как в файлах, созданных KiCad на Windows."""
    import os
    date = date or kicad_date()
    base, ext = os.path.splitext(path)
    if ext.lower() != '.lib':
        base = path
    lib_path = base + '.lib'
    _write_text(lib_path, write_library(lib, date=date, sort_items=sort_items), crlf)
    written = [lib_path]
    if with_doc:
        dcm_path = base + '.dcm'
        _write_text(dcm_path, write_doclib(lib, date=date), crlf)
        written.append(dcm_path)
    return written
