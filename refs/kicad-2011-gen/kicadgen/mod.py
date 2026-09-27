"""Формат библиотеки посадочных мест Pcbnew bzr2986: *.mod / *.emp, байт-в-байт
по fprintf-форматам исходников. Источники (в ~/Desktop/Университет/bzr2986):

- MODULE::Save / ReadDescr        pcbnew/class_module.cpp:259-357 / :473-620
- TEXTE_MODULE::Save / ReadDescr  pcbnew/class_text_mod.cpp:71-94 / :103-180
- EDGE_MODULE::ReadDescr          pcbnew/class_edge_mod.cpp:360-470
- D_PAD::Save / ReadDescr         pcbnew/class_pad.cpp:499-581 / :359-496
- заголовок/$INDEX                pcbnew/librairi.cpp:94, :200-209, :258
- сообщение "не валидная библиотека" pcbnew/loadcmp.cpp:256

Подробные разборы форматов (со ссылками файл:строка на каждое поле) — см.
docs/pcbnew-mod-format.md и docs/pcbnew-pad-format.md в этом репозитории;
этот модуль реализует именно то, что там описано.

Стиль (dataclass-модель, EscapedUTF8/ReadDelimitedText, CRLF-запись) —
как в writer_lib.py / reader_lib.py / model.py этого пакета.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Union

from .sscanf import sscanf
from .textio import escaped, read_delimited, kicad_date

# --------------------------------------------------------------------------
# Константы формата
# --------------------------------------------------------------------------

PCB_INTERNAL_UNIT = 10000
"""Внутренняя единица PCBNEW = 1/10000 дюйма (= 2,54 мкм).
include/fctsys.h:32: `#define PCB_INTERNAL_UNIT 10000 // PCBNEW internal unit
= 1/10000 inch` (то же значение продублировано в include/wxBasePcbFrame.h:18
и include/wxPcbStruct.h:16 — везде синхронно)."""

ENTETE_LIBRAIRIE = 'PCBNEW-LibModule-V1'    # include/pcbstruct.h:14
L_ENTETE_LIB = 18                            # include/pcbstruct.h:15 (strnicmp на 18 байт)

LAYER_N_BACK = 0            # include/layers_id_colors_and_visibility.h
LAYER_N_FRONT = 15
SILKSCREEN_N_BACK = 20
SILKSCREEN_N_FRONT = 21
LAST_NO_COPPER_LAYER = 28    # он же EDGE_N

MOD_DEFAULT = 0
MOD_CMS = 1
MOD_VIRTUAL = 2

TEXT_is_REFERENCE = 0
TEXT_is_VALUE = 1
TEXT_is_DIVERS = 2

TEXTS_MIN_SIZE = 50          # class_text_mod.cpp / drawtxt.cpp
MAX_EDGE_WIDTH = 10000        # class_edge_mod.cpp:19 (#define MAX_WIDTH 10000)

# Маски слоёв по умолчанию для атрибутов площадки (docs/pcbnew-pad-format.md §3.4)
PAD_STANDARD_DEFAULT_LAYERS = 0x00E0FFFF   # STD
PAD_SMD_DEFAULT_LAYERS = 0x00808000         # SMD
PAD_CONN_DEFAULT_LAYERS = 0x00888000        # CONN
PAD_HOLE_DEFAULT_LAYERS = 0x00E00001        # HOLE (монтажное отверстие)


class ModLoadError(Exception):
    """Ошибка строгого чтения .mod — с текстом реальных C++ сообщений там,
    где они существуют (см. docstring-и мест, где возбуждается)."""


def mm_to_pcb(mm: float) -> int:
    """мм -> внутренние единицы PCBNEW (1/10000"): iu = wxRound(mm * 10000 / 25.4).
    wxRound (common округление KiCad) — к ближайшему целому, половина — от нуля:
    include/fctsys.h:32 задаёт PCB_INTERNAL_UNIT = 10000.

    ВАЖНО: округление применяется к каждому итоговому мм-значению отдельно, а
    не к «шагу», умноженному на количество — mm_to_pcb(2.5)=984, но
    mm_to_pcb(2*2.5) = mm_to_pcb(5.0) = 1969, а не 2*984 = 1968
    (docs/pcbnew-pad-format.md §5)."""
    v = mm * PCB_INTERNAL_UNIT / 25.4
    return int(v + 0.5) if v >= 0 else int(v - 0.5)


def pcb_to_mm(iu: int) -> float:
    """Внутренние единицы -> мм (обратное к mm_to_pcb, без округления)."""
    return iu * 25.4 / PCB_INTERNAL_UNIT


def _wx_round(x: float) -> int:
    return int(x + 0.5) if x >= 0 else int(x - 0.5)


def _hex8(v: int) -> str:
    return '%08X' % (v & 0xFFFFFFFF)


_ATOI_CHARS = '0123456789+-'


def _atoi(s: str) -> int:
    """Аналог C atoi(): ведущие пробелы, необязательный знак, цифры; иначе 0."""
    s = s.strip()
    i = 0
    if i < len(s) and s[i] in '+-':
        i += 1
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    if j == i:
        return 0
    return int(s[:j])


def _atof(s: str) -> float:
    """Аналог C atof(): ведущие пробелы, знак, цифры, необязательные '.'/'e'; иначе 0.0."""
    s = s.strip()
    i = 0
    n = len(s)
    if i < n and s[i] in '+-':
        i += 1
    start_digits = i
    while i < n and s[i].isdigit():
        i += 1
    if i < n and s[i] == '.':
        i += 1
        while i < n and s[i].isdigit():
            i += 1
    if i == start_digits or (i == start_digits + 1 and s[start_digits] == '.'):
        return 0.0
    if i < n and s[i] in 'eE':
        k = i + 1
        if k < n and s[k] in '+-':
            k += 1
        d0 = k
        while k < n and s[k].isdigit():
            k += 1
        if k > d0:
            i = k
    try:
        return float(s[:i])
    except ValueError:
        return 0.0


def _g(vals, i, default=0):
    return vals[i] if i < len(vals) else default


# --------------------------------------------------------------------------
# Модель данных
# --------------------------------------------------------------------------


@dataclass
class Pad:
    """$PAD .. $EndPAD (class_pad.cpp:499-581 Save, :359-496 ReadDescr).

    x/y — это m_Pos0 (координаты площадки относительно якоря модуля при его
    ориентации 0); D_PAD::Save всегда пишет именно m_Pos0, а не абсолютную
    m_Pos, поэтому вращение модуля здесь не нужно."""

    number: str = ''
    shape: str = 'C'            # 'C' круг, 'R' прямоугольник, 'O' овал, 'T' трапеция
    x: int = 0
    y: int = 0
    size_x: int = 500            # D_PAD ctor: m_Size.x = m_Size.y = 500 (class_pad.cpp:18-50)
    size_y: int = 500
    delta_x: int = 0             # для трапеции
    delta_y: int = 0
    orient: int = 0
    drill: int = 315
    drill_y: Optional[int] = None   # не None => овальное сверло (drill x drill_y)
    offset_x: int = 0
    offset_y: int = 0
    attribute: str = 'STD'       # STD / SMD / CONN / HOLE
    layer_mask: int = PAD_STANDARD_DEFAULT_LAYERS
    net_code: int = 0
    net_name: str = ''
    solder_mask_margin: int = 0
    solder_paste_margin: int = 0
    solder_paste_ratio: float = 0.0
    local_clearance: int = 0


@dataclass
class EdgeLine:
    """DS start.x start.y end.x end.y width layer (class_edge_mod.cpp)."""

    start_x: int
    start_y: int
    end_x: int
    end_y: int
    width: int = 120             # EDGE_MODULE ctor: m_Width = 120 (class_edge_mod.cpp:15-32)
    layer: int = SILKSCREEN_N_FRONT


@dataclass
class EdgeCircle:
    """DC center.x center.y point.x point.y width layer."""

    center_x: int
    center_y: int
    point_x: int
    point_y: int
    width: int = 120
    layer: int = SILKSCREEN_N_FRONT


@dataclass
class EdgeArc:
    """DA center.x center.y start.x start.y angle(0.1°) width layer."""

    center_x: int
    center_y: int
    start_x: int
    start_y: int
    angle: int
    width: int = 120
    layer: int = SILKSCREEN_N_FRONT


@dataclass
class ModText:
    """T<kind> ... (class_text_mod.cpp:71-94 Save, :103-180 ReadDescr).

    x/y — m_Pos0 (якорь модуля, ориентация 0). size_x/size_y — m_Size.x/y,
    но в файле пишутся в порядке Size.y затем Size.x (см. format_text)."""

    kind: int = TEXT_is_DIVERS
    x: int = 0
    y: int = 0
    text: str = ''
    size_x: int = 400            # TEXTE_MODULE ctor: m_Size.x=m_Size.y=400 (class_text_mod.cpp:31)
    size_y: int = 400
    thickness: int = 120          # ctor: m_Thickness = 120 (class_text_mod.cpp:32)
    orient: int = 0
    mirror: bool = False
    hidden: bool = False
    layer: int = SILKSCREEN_N_FRONT
    italic: bool = False


DrawItem = Union[EdgeLine, EdgeCircle, EdgeArc, ModText]


@dataclass
class Footprint:
    """$MODULE .. $EndMODULE (class_module.cpp:259-357 Save, :473-620 ReadDescr)."""

    name: str
    x: int = 0
    y: int = 0
    orient: int = 0
    layer: int = LAYER_N_FRONT
    locked: bool = False
    placed: bool = False
    last_edit_time: int = 0
    timestamp: int = 0
    doc: str = ''
    keyword: str = ''
    path: str = ''
    cnt_rot90: int = 0
    cnt_rot180: int = 0
    solder_mask_margin: int = 0
    solder_paste_margin: int = 0
    solder_paste_ratio: float = 0.0
    local_clearance: int = 0
    attributes: int = MOD_DEFAULT
    reference: ModText = field(default_factory=lambda: ModText(kind=TEXT_is_REFERENCE))
    value: ModText = field(default_factory=lambda: ModText(kind=TEXT_is_VALUE))
    drawings: List[DrawItem] = field(default_factory=list)
    pads: List[Pad] = field(default_factory=list)


@dataclass
class ModLibrary:
    footprints: List[Footprint] = field(default_factory=list)

    def add(self, fp: Footprint) -> Footprint:
        self.footprints.append(fp)
        return fp

    def get(self, name: str) -> Optional[Footprint]:
        for fp in self.footprints:
            if fp.name.casefold() == name.casefold():
                return fp
        return None


# --------------------------------------------------------------------------
# Запись
# --------------------------------------------------------------------------


def format_pad(p: Pad) -> List[str]:
    """D_PAD::Save, class_pad.cpp:499-581."""
    lines = ['$PAD']
    lines.append('Sh "%s" %s %d %d %d %d %d' % (
        p.number[:4], p.shape, p.size_x, p.size_y, p.delta_x, p.delta_y, p.orient))
    dr = 'Dr %d %d %d' % (p.drill, p.offset_x, p.offset_y)
    if p.drill_y is not None:
        dr += ' O %d %d' % (p.drill, p.drill_y)
    lines.append(dr)
    lines.append('At %s N %s' % (p.attribute, _hex8(p.layer_mask)))
    lines.append('Ne %d %s' % (p.net_code, escaped(p.net_name)))
    lines.append('Po %d %d' % (p.x, p.y))
    if p.solder_mask_margin:
        lines.append('.SolderMask %d' % p.solder_mask_margin)
    if p.solder_paste_margin:
        lines.append('.SolderPaste %d' % p.solder_paste_margin)
    if p.solder_paste_ratio:
        lines.append('.SolderPasteRatio %g' % p.solder_paste_ratio)
    if p.local_clearance:
        lines.append('.LocalClearance %d' % p.local_clearance)
    lines.append('$EndPAD')
    return lines


def format_text(t: ModText, parent_orient: int = 0) -> str:
    """TEXTE_MODULE::Save, class_text_mod.cpp:71-94 — порядок полей Size.y
    затем Size.x (не x потом y!). Угол в файле = угол текста + угол модуля
    (class_text_mod.cpp:72-79); при чтении угол модуля вычитается (:133)."""
    return 'T%d %d %d %d %d %d %d %c %c %d %c %s' % (
        t.kind, t.x, t.y, t.size_y, t.size_x, (t.orient + parent_orient) % 3600, t.thickness,
        'M' if t.mirror else 'N',
        'I' if t.hidden else 'V',
        t.layer,
        'I' if t.italic else 'N',
        escaped(t.text))


def format_edge(e: DrawItem) -> str:
    if isinstance(e, EdgeLine):
        return 'DS %d %d %d %d %d %d' % (e.start_x, e.start_y, e.end_x, e.end_y, e.width, e.layer)
    if isinstance(e, EdgeCircle):
        return 'DC %d %d %d %d %d %d' % (e.center_x, e.center_y, e.point_x, e.point_y, e.width, e.layer)
    if isinstance(e, EdgeArc):
        return 'DA %d %d %d %d %d %d %d' % (
            e.center_x, e.center_y, e.start_x, e.start_y, e.angle, e.width, e.layer)
    raise TypeError('unknown drawing item %r' % (e,))


def format_footprint(m: Footprint) -> List[str]:
    """MODULE::Save, class_module.cpp:259-357 — точный порядок полей."""
    lines = ['$MODULE %s' % m.name]
    status = ('F' if m.locked else '~') + ('P' if m.placed else '~')
    lines.append('Po %d %d %d %d %s %s %s' % (
        m.x, m.y, m.orient, m.layer, _hex8(m.last_edit_time), _hex8(m.timestamp), status))
    lines.append('Li %s' % m.name)
    if m.doc:
        lines.append('Cd %s' % m.doc)
    if m.keyword:
        lines.append('Kw %s' % m.keyword)
    lines.append('Sc %s' % _hex8(m.timestamp))
    lines.append('AR %s' % m.path)
    lines.append('Op %X %X 0' % (m.cnt_rot90, m.cnt_rot180))
    if m.solder_mask_margin:
        lines.append('.SolderMask %d' % m.solder_mask_margin)
    if m.solder_paste_margin:
        lines.append('.SolderPaste %d' % m.solder_paste_margin)
    if m.solder_paste_ratio:
        lines.append('.SolderPasteRatio %g' % m.solder_paste_ratio)
    if m.local_clearance:
        lines.append('.LocalClearance %d' % m.local_clearance)
    if m.attributes != MOD_DEFAULT:
        s = 'At '
        if m.attributes & MOD_CMS:
            s += 'SMD '
        if m.attributes & MOD_VIRTUAL:
            s += 'VIRTUAL '
        lines.append(s)
    lines.append(format_text(m.reference, m.orient))
    lines.append(format_text(m.value, m.orient))
    for item in m.drawings:
        if isinstance(item, ModText):
            lines.append(format_text(item, m.orient))
        else:
            lines.append(format_edge(item))
    for p in m.pads:
        lines.extend(format_pad(p))
    lines.append('$EndMODULE  %s' % m.name)
    return lines


def write_modlib(lib: ModLibrary, date: Optional[str] = None) -> str:
    """Полный текст .mod (с '\\n'; CRLF — при сохранении файла).

    Заголовок и $INDEX: librairi.cpp:200 (`"%s  %s\\n"`, ENTETE_LIBRAIRIE,
    дата — два пробела перед датой) и :204-209 (построчный список имён модулей
    между $INDEX/$EndINDEX, в порядке библиотеки). Модули пишутся в этом же
    порядке (см. format_footprint), завершается '$EndLIBRARY'."""
    date = date or kicad_date()
    out = ['%s  %s' % (ENTETE_LIBRAIRIE, date), '# encoding utf-8', '$INDEX']
    for m in lib.footprints:
        out.append(m.name)
    out.append('$EndINDEX')
    for m in lib.footprints:
        out.extend(format_footprint(m))
    out.append('$EndLIBRARY')
    return '\n'.join(out) + '\n'


def _write_text(path: str, text: str, crlf: bool) -> None:
    data = text.replace('\n', '\r\n') if crlf else text
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(data)


def save_modlib(lib: ModLibrary, path: str, date: Optional[str] = None, crlf: bool = True) -> str:
    """Пишет .mod в path (CRLF по умолчанию — как в файлах, созданных KiCad
    на Windows; см. writer_lib.py::save_library / _write_text)."""
    _write_text(path, write_modlib(lib, date=date), crlf)
    return path


# --------------------------------------------------------------------------
# Чтение (строгое)
# --------------------------------------------------------------------------


class _Cursor:
    """FILE_LINE_READER + FILTER_READER (common/filter_reader.cpp): строки,
    начинающиеся с '#' или '\\r', и пустые строки пропускаются; хвостовой
    '\\r' срезается (у нас входной текст уже без него после split('\\n'), но
    срез оставлен на случай смешанных окончаний строк)."""

    def __init__(self, text: str, start: int = 0):
        self._lines = text.split('\n')
        self._pos = start

    def read_line(self) -> Optional[str]:
        while self._pos < len(self._lines):
            raw = self._lines[self._pos]
            self._pos += 1
            line = raw[:-1] if raw.endswith('\r') else raw
            if line == '' or line[0] in ('#', '\r'):
                continue
            return line
        return None


def read_modlib(text: str) -> ModLibrary:
    """Строгий разбор .mod. Верхнеуровневая логика — как в
    FOOTPRINT_LIST::ReadFootprintFiles (common/footprint_info.cpp:82-104):
    ищем блоки $MODULE напрямую, $INDEX не обязателен и не используется для
    поиска (в отличие от Get_Librairie_Module в loadcmp.cpp, который требует
    $INDEX — но это для функции "найти модуль по имени", не для чтения всей
    библиотеки, что и делает read_modlib)."""
    raw = text.split('\n', 1)
    header = raw[0][:-1] if raw and raw[0].endswith('\r') else (raw[0] if raw else '')
    if header[:L_ENTETE_LIB].casefold() != ENTETE_LIBRAIRIE[:L_ENTETE_LIB].casefold():
        # loadcmp.cpp:256: msg.Printf(_("<%s> is not a valid Kicad PCB footprint
        # library file."), ...) — без имени файла: read_modlib(text) его не получает.
        raise ModLoadError('is not a valid Kicad PCB footprint library file.')

    cur = _Cursor(text, start=1)
    lib = ModLibrary()
    line = cur.read_line()
    while line is not None:
        if line[:7] == '$MODULE':
            name = line[7:].strip()
            lib.footprints.append(_read_module(cur, name))
        line = cur.read_line()
    return lib


def load_modlib(path: str) -> ModLibrary:
    """Читает .mod с диска. UTF-8 с запасным cp1251 — как reader_lib._read_text."""
    with open(path, 'rb') as fh:
        data = fh.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('cp1251')
    return read_modlib(text)


def _read_module(cur: _Cursor, name: str) -> Footprint:
    fp = Footprint(name=name)
    while True:
        line = cur.read_line()
        if line is None:
            # Реальный ReadDescr не считает это ошибкой (просто выходит из
            # цикла по EOF ReadLine()==0) — мы намеренно строже: непарный
            # $MODULE без $EndMODULE делает файл невалидным для генератора.
            raise ModLoadError(
                '$MODULE %s: $EndMODULE not found before end of file' % name)
        if line[0] == '$':
            tag = line[1] if len(line) > 1 else ''
            if tag == 'E':      # $EndMODULE (имя после него не проверяем — как реальный код)
                return fp
            if tag == 'P':      # $PAD
                fp.pads.append(_read_pad(cur))
                continue
            if tag == 'S':      # $SHAPE3D — вне области задачи, просто пропускаем блок
                _skip_shape3d(cur)
                continue
            continue
        if len(line) < 3:
            # strlen(Line) < 4 в реальном коде (буфер C ещё содержит '\n');
            # для уже очищенной python-строки эквивалент — len(line) < 3.
            continue
        tag = line[0]
        ptline = line[3:]
        if tag == 'P':
            _parse_module_po(fp, ptline)
        elif tag == 'L':
            vals, cnt = sscanf(ptline, ' %s')
            if cnt:
                fp.name = vals[0]
        elif tag == 'S':
            vals, cnt = sscanf(ptline, ' %lX')
            if cnt:
                fp.timestamp = vals[0]
        elif tag == 'O':
            vals, cnt = sscanf(ptline, ' %X %X')
            _parse_module_op(fp, vals, cnt)
        elif tag == 'A':
            second = line[1] if len(line) > 1 else ''
            if second == 't':
                if 'SMD' in ptline:
                    fp.attributes |= MOD_CMS
                if 'VIRTUAL' in ptline:
                    fp.attributes |= MOD_VIRTUAL
            elif second == 'R':
                # Реальный код переиспользует общий буфер BufLine между веток
                # switch: если "AR "-строка пуста, там остаётся имя модуля из
                # предыдущей ветки 'L' ("AR"-баг). Мы этот баг НЕ повторяем —
                # пустая "AR " всегда даёт path='' (иначе запись->чтение не
                # были бы идемпотентны).
                vals, cnt = sscanf(ptline, ' %s')
                fp.path = vals[0] if cnt else ''
        elif tag == 'T':
            _read_text_line(fp, line)
        elif tag == 'D':
            _read_edge_line(fp, line)
        elif tag == 'C':
            fp.doc = ptline.strip()
        elif tag == 'K':
            fp.keyword = ptline.strip()
        elif tag == '.':
            _parse_dot_field(line, fp)
        # прочие теги первого уровня — молча игнорируются (как реальный switch
        # без default-обработчика для нераспознанных однобуквенных кодов)


def _parse_module_po(fp: Footprint, ptline: str) -> None:
    vals, cnt = sscanf(ptline, '%d %d %d %d %lX %lX %s')
    if cnt >= 1:
        fp.x = vals[0]
    if cnt >= 2:
        fp.y = vals[1]
    if cnt >= 3:
        fp.orient = vals[2]
    if cnt >= 4:
        fp.layer = vals[3]
    if cnt >= 5:
        fp.last_edit_time = vals[4]
    if cnt >= 6:
        fp.timestamp = vals[5]
    fp.locked = False
    fp.placed = False
    if cnt >= 7:
        status = vals[6]
        if len(status) >= 1 and status[0] == 'F':
            fp.locked = True
        if len(status) >= 2 and status[1] == 'P':
            fp.placed = True


def _parse_module_op(fp: Footprint, vals, cnt) -> None:
    itmp1 = vals[0] if cnt >= 1 else 0
    itmp2 = vals[1] if cnt >= 2 else 0
    cnt180 = itmp2 & 0x0F
    if cnt180 > 10:
        cnt180 = 10
    cnt90 = itmp1 & 0x0F
    if cnt90 > 10:
        cnt90 = 0
    hi = (itmp1 >> 4) & 0x0F
    if hi > 10:
        hi = 0
    cnt90 |= hi << 4
    fp.cnt_rot180 = cnt180
    fp.cnt_rot90 = cnt90


def _parse_dot_field(line: str, target) -> None:
    if line.startswith('.SolderMask '):
        target.solder_mask_margin = _atoi(line[12:])
    elif line.startswith('.SolderPaste '):
        target.solder_paste_margin = _atoi(line[13:])
    elif line.startswith('.SolderPasteRatio '):
        target.solder_paste_ratio = _atof(line[18:])
    elif line.startswith('.LocalClearance '):
        target.local_clearance = _atoi(line[16:])


def _read_text_line(fp: Footprint, line: str) -> None:
    """TEXTE_MODULE::ReadDescr, class_text_mod.cpp:103-180.

    ПРИМЕЧАНИЕ: в реальном коде `success` инициализируется в `true` ДО
    проверки sscanf(...) >= 10, а в теле if нет ветки else — то есть
    возвращаемое значение ВСЕГДА успешно, порог >= 10 фактически ни на что
    не влияет (мёртвая проверка/баг). Мы намеренно применяем этот порог как
    настоящую валидацию — по заданию: "те же минимумы sscanf", но строже."""
    vals, cnt = sscanf(line[1:], '%d %d %d %d %d %d %d %s %s %d %s')
    if cnt < 10:
        raise ModLoadError(
            'module %r: text line has only %d of the required 10 fields: %r'
            % (fp.name, cnt, line))
    ttype = vals[0]
    t = ModText(kind=ttype if ttype in (TEXT_is_REFERENCE, TEXT_is_VALUE) else TEXT_is_DIVERS,
                x=vals[1], y=vals[2], size_y=vals[3], size_x=vals[4],
                orient=vals[5], thickness=vals[6])
    bufcar1 = _g(vals, 7, '')
    bufcar2 = _g(vals, 8, '')
    layer = _g(vals, 9, SILKSCREEN_N_FRONT)
    t.mirror = bool(bufcar1) and bufcar1[0] == 'M'
    t.hidden = bool(bufcar2) and bufcar2[0] == 'I'
    if layer < 0:
        layer = 0
    if layer > LAST_NO_COPPER_LAYER:
        layer = LAST_NO_COPPER_LAYER
    if layer == LAYER_N_BACK:
        layer = SILKSCREEN_N_BACK
    elif layer == LAYER_N_FRONT:
        layer = SILKSCREEN_N_FRONT
    t.layer = layer
    bufcar3 = vals[10] if cnt >= 11 else ''
    t.italic = bool(bufcar3) and bufcar3[0] == 'I'
    t.text, _pos = read_delimited(line, 0)
    t.orient = (t.orient - fp.orient) % 3600      # class_text_mod.cpp:133: m_Orient -= parent->m_Orient
    if t.size_x < TEXTS_MIN_SIZE:
        t.size_x = TEXTS_MIN_SIZE
    if t.size_y < TEXTS_MIN_SIZE:
        t.size_y = TEXTS_MIN_SIZE
    if t.thickness < 1:
        t.thickness = 1
    max_pen = _wx_round(min(t.size_x, t.size_y) / 4.0)   # Clamp_Text_PenSize, common/drawtxt.cpp:44-72
    if t.thickness > max_pen:
        t.thickness = max_pen
    if ttype == TEXT_is_REFERENCE:
        fp.reference = t
    elif ttype == TEXT_is_VALUE:
        fp.value = t
    else:
        fp.drawings.append(t)


def _read_edge_line(fp: Footprint, line: str) -> None:
    """EDGE_MODULE::ReadDescr, class_edge_mod.cpp:360-470."""
    kind = line[1] if len(line) > 1 else ''
    ptline = line[3:]
    if kind == 'S':
        vals, cnt = sscanf(ptline, '%d %d %d %d %d %d')
        e: DrawItem = EdgeLine(start_x=_g(vals, 0), start_y=_g(vals, 1),
                                end_x=_g(vals, 2), end_y=_g(vals, 3),
                                width=_g(vals, 4, 120), layer=_g(vals, 5, SILKSCREEN_N_FRONT))
    elif kind == 'C':
        vals, cnt = sscanf(ptline, '%d %d %d %d %d %d')
        e = EdgeCircle(center_x=_g(vals, 0), center_y=_g(vals, 1),
                        point_x=_g(vals, 2), point_y=_g(vals, 3),
                        width=_g(vals, 4, 120), layer=_g(vals, 5, SILKSCREEN_N_FRONT))
    elif kind == 'A':
        vals, cnt = sscanf(ptline, '%d %d %d %d %d %d %d')
        angle = _g(vals, 4)
        while angle < -3600:
            angle += 3600
        while angle > 3600:
            angle -= 3600
        e = EdgeArc(center_x=_g(vals, 0), center_y=_g(vals, 1),
                    start_x=_g(vals, 2), start_y=_g(vals, 3), angle=angle,
                    width=_g(vals, 5, 120), layer=_g(vals, 6, SILKSCREEN_N_FRONT))
    elif kind == 'P':
        # DP — контур-полигон; вне области задачи (не входит в список
        # требуемых dataclass-ов), поэтому явная ошибка вместо тихой потери данных.
        raise ModLoadError('DP polygon edges are not supported by this generator: %r' % line)
    else:
        # class_edge_mod.cpp: DisplayError(NULL, "Unknown Edge Type") — в
        # библиотечном контексте (без GUI) превращаем в исключение.
        raise ModLoadError('Unknown EDGE_MODULE type: %r' % line)
    if e.width <= 1:
        e.width = 1
    if e.width > MAX_EDGE_WIDTH:
        e.width = MAX_EDGE_WIDTH
    if e.layer < 0 or e.layer > LAST_NO_COPPER_LAYER:
        e.layer = SILKSCREEN_N_FRONT
    fp.drawings.append(e)


def _skip_shape3d(cur: _Cursor) -> None:
    """Read_3D_Descr, class_module.cpp:404-465 — 3D-модели вне области
    задачи; при чтении просто пропускаем блок $SHAPE3D..$EndSHAPE3D."""
    while True:
        line = cur.read_line()
        if line is None or line[0] == '$':
            return


def _read_pad(cur: _Cursor) -> Pad:
    """D_PAD::ReadDescr, class_pad.cpp:359-496."""
    p = Pad()
    while True:
        line = cur.read_line()
        if line is None:
            raise ModLoadError('$PAD: unexpected end of file inside pad block')
        if line[0] == '$':
            return p
        tag = line[0]
        ptline = line[3:]
        if tag == 'S':
            _parse_pad_sh(p, ptline)
        elif tag == 'D':
            _parse_pad_dr(p, ptline)
        elif tag == 'A':
            _parse_pad_at(p, ptline)
        elif tag == 'N':
            _parse_pad_ne(p, ptline)
        elif tag == 'P':
            vals, cnt = sscanf(ptline, '%d %d')
            if cnt >= 1:
                p.x = vals[0]
            if cnt >= 2:
                p.y = vals[1]
        elif tag == '.':
            _parse_dot_field(line, p)
        else:
            # class_pad.cpp: DisplayError(NULL, "Err Pad: Id inconnu")
            raise ModLoadError('Err Pad: Id inconnu: %r' % line)


def _parse_pad_sh(p: Pad, ptline: str) -> None:
    qi = ptline.find('"')
    if qi < 0:
        # Реальный код продолжает молча (PtLine доходит до '\0' и цикл
        # останавливается сам) — read_modlib здесь намеренно строже: линия
        # Sh без кавычки для имени площадки считается структурно некорректной.
        raise ModLoadError('pad Sh line: no quoted pad name found: %r' % ptline)
    i = qi + 1
    chars: List[str] = []
    while i < len(ptline) and ptline[i] != '"':
        ch = ptline[i]
        if len(chars) < 4 and ch > ' ':
            chars.append(ch)
        i += 1
    if i < len(ptline) and ptline[i] == '"':
        i += 1
    vals, cnt = sscanf(ptline[i:], ' %s %d %d %d %d %d')
    if cnt < 6:
        raise ModLoadError(
            'pad Sh line: expected shape + 5 numeric fields after the name, got %d: %r'
            % (cnt, ptline))
    p.number = ''.join(chars)
    letter = vals[0][0] if vals[0] else 'C'
    p.shape = letter if letter in ('C', 'R', 'O', 'T') else 'C'
    p.size_x, p.size_y, p.delta_x, p.delta_y, p.orient = vals[1], vals[2], vals[3], vals[4], vals[5]


def _parse_pad_dr(p: Pad, ptline: str) -> None:
    vals, cnt = sscanf(ptline, '%d %d %d %s %d %d')
    if cnt >= 1:
        p.drill = vals[0]
    if cnt >= 2:
        p.offset_x = vals[1]
    if cnt >= 3:
        p.offset_y = vals[2]
    p.drill_y = None
    if cnt >= 6 and vals[3] and vals[3][0] == 'O':
        p.drill = vals[4]
        p.drill_y = vals[5]


def _parse_pad_at(p: Pad, ptline: str) -> None:
    vals, cnt = sscanf(ptline, '%s %s %X')
    tok = vals[0] if cnt >= 1 else ''
    attr = 'STD'
    if tok[:3] == 'SMD':
        attr = 'SMD'
    if tok[:4] == 'CONN':
        attr = 'CONN'
    if tok[:4] == 'HOLE':
        attr = 'HOLE'
    p.attribute = attr
    if cnt >= 3:
        p.layer_mask = vals[2]


def _parse_pad_ne(p: Pad, ptline: str) -> None:
    vals, cnt = sscanf(ptline, '%d')
    if cnt >= 1:
        p.net_code = vals[0]
    text, _pos = read_delimited(ptline, 0)
    p.net_name = text


# --------------------------------------------------------------------------
# Помощники геометрии (ТЗ §3.2) — размеры на входе в мм
# --------------------------------------------------------------------------

SILK_CLEARANCE_MM = 1.25
"""Отступ шёлкографии (площадка/текст -> контур). В ТЗ §3.2.1 явно задан
только для dip14 ("площадки отстоят от контура на 1,25 мм... верхний/нижний
отступ 1,25 мм"); переиспользуется как разумное значение по умолчанию для
mlt и snp8 (там численно не задан) — совпадает с шагом сетки лабораторной
работы ("Сетка 1,25 мм", ТЗ §3.2)."""

DEFAULT_PAD_SIZE_MM = 1.3      # ТЗ §3.2: "площадки по умолчанию 1,3x1,3 мм круглые"
DEFAULT_DRILL_MM = 0.8         # ТЗ §3.2: "отверстие 0,8 мм"
DEFAULT_EDGE_WIDTH_MM = 0.15    # линия контура — не задана в ТЗ, разумный дефолт
DEFAULT_TEXT_SIZE_MM = 1.0      # размер Ref/Val — не задан в ТЗ, разумный дефолт
DEFAULT_TEXT_THICKNESS_MM = 0.15
DIP_NOTCH_RADIUS_MM = 0.75      # радиус ключевой выемки dip14 — не задан в ТЗ численно


def _round_pad(number, x_mm: float, y_mm: float, pad_mm: float, drill_mm: float,
               square: bool = False) -> Pad:
    return Pad(number=str(number), shape='R' if square else 'C',
               x=mm_to_pcb(x_mm), y=mm_to_pcb(y_mm),
               size_x=mm_to_pcb(pad_mm), size_y=mm_to_pcb(pad_mm),
               drill=mm_to_pcb(drill_mm))


def _mounting_hole(x_mm: float, y_mm: float, hole_mm: float) -> Pad:
    """Механическое (не электрическое) монтажное отверстие: площадка без
    номера, атрибут HOLE, маска слоёв PAD_HOLE_DEFAULT_LAYERS
    (docs/pcbnew-pad-format.md §3.4/§6)."""
    return Pad(number='', shape='C', x=mm_to_pcb(x_mm), y=mm_to_pcb(y_mm),
               size_x=mm_to_pcb(hole_mm), size_y=mm_to_pcb(hole_mm),
               drill=mm_to_pcb(hole_mm), attribute='HOLE',
               layer_mask=PAD_HOLE_DEFAULT_LAYERS)


def _ref_text(x_mm: float, y_mm: float, orient: int = 0) -> ModText:
    s = mm_to_pcb(DEFAULT_TEXT_SIZE_MM)
    return ModText(kind=TEXT_is_REFERENCE, x=mm_to_pcb(x_mm), y=mm_to_pcb(y_mm),
                    text='REF**', size_x=s, size_y=s,
                    thickness=mm_to_pcb(DEFAULT_TEXT_THICKNESS_MM), orient=orient)


def _val_text(x_mm: float, y_mm: float, orient: int = 0) -> ModText:
    s = mm_to_pcb(DEFAULT_TEXT_SIZE_MM)
    return ModText(kind=TEXT_is_VALUE, x=mm_to_pcb(x_mm), y=mm_to_pcb(y_mm),
                    text='VAL**', size_x=s, size_y=s,
                    thickness=mm_to_pcb(DEFAULT_TEXT_THICKNESS_MM), orient=orient)


def _rect_outline(half_w_mm: float, half_h_mm: float,
                   width_mm: float = DEFAULT_EDGE_WIDTH_MM) -> List[EdgeLine]:
    w = mm_to_pcb(width_mm)
    x0, x1 = mm_to_pcb(-half_w_mm), mm_to_pcb(half_w_mm)
    y0, y1 = mm_to_pcb(-half_h_mm), mm_to_pcb(half_h_mm)
    return [
        EdgeLine(x0, y0, x1, y0, width=w),
        EdgeLine(x1, y0, x1, y1, width=w),
        EdgeLine(x1, y1, x0, y1, width=w),
        EdgeLine(x0, y1, x0, y0, width=w),
    ]


def dip(name: str = 'dip14', pins: int = 14, pitch: float = 2.5, rows: float = 7.5,
        pad: float = DEFAULT_PAD_SIZE_MM, drill: float = DEFAULT_DRILL_MM,
        body_w: float = 5.0) -> Footprint:
    """DIP-корпус (ТЗ §3.2.1, dip14 = К555ТВ6): `pins` сквозных площадок в
    два ряда по pins/2, шаг в ряду `pitch`, расстояние между рядами `rows`.
    Нумерация буквой "U": 1 слева вверху, вниз до pins/2, затем pins/2+1
    справа внизу, вверх до pins (справа вверху). Площадка 1 — квадратная,
    остальные круглые. Контур — прямоугольник шириной body_w между рядами
    с ключевой полукруглой выемкой сверху (DA-дуга); зазор контур<->площадки
    и контур<->текст = SILK_CLEARANCE_MM. Ref сверху, Val** внутри вертикально."""
    half = pins // 2
    y0 = (half - 1) * pitch / 2.0
    pads: List[Pad] = []
    for k in range(half):
        num = k + 1
        pads.append(_round_pad(num, -rows / 2.0, -y0 + k * pitch, pad, drill, square=(num == 1)))
    for j in range(half):
        num = half + 1 + j
        pads.append(_round_pad(num, rows / 2.0, y0 - j * pitch, pad, drill, square=(num == 1)))

    body_x = body_w / 2.0
    body_y = y0 + SILK_CLEARANCE_MM
    drawings: List[DrawItem] = list(_rect_outline(body_x, body_y))
    r = DIP_NOTCH_RADIUS_MM
    drawings.append(EdgeArc(
        center_x=0, center_y=mm_to_pcb(-body_y),
        start_x=mm_to_pcb(r), start_y=mm_to_pcb(-body_y),
        angle=-1800, width=mm_to_pcb(DEFAULT_EDGE_WIDTH_MM)))

    return Footprint(name=name,
                      reference=_ref_text(0, -(body_y + SILK_CLEARANCE_MM)),
                      value=_val_text(0, 0, orient=900),
                      drawings=drawings, pads=pads)


def two_pad(name: str = 'mlt', spacing: float = 10.0, body_w: float = 7.5,
            body_h: float = 2.5, pad: float = DEFAULT_PAD_SIZE_MM,
            drill: float = DEFAULT_DRILL_MM) -> Footprint:
    """Двухвыводной корпус (ТЗ §3.2.2, mlt = резистор): 2 сквозные площадки
    на расстоянии `spacing`, площадка 1 квадратная. Контур — прямоугольник
    body_w x body_h по центру между площадками, с выводными линиями
    (площадка -> контур). Ref сверху, Val** снизу."""
    pads = [
        _round_pad(1, -spacing / 2.0, 0.0, pad, drill, square=True),
        _round_pad(2, spacing / 2.0, 0.0, pad, drill, square=False),
    ]
    bx, by = body_w / 2.0, body_h / 2.0
    drawings: List[DrawItem] = list(_rect_outline(bx, by))
    w = mm_to_pcb(DEFAULT_EDGE_WIDTH_MM)
    drawings.append(EdgeLine(mm_to_pcb(-spacing / 2.0), 0, mm_to_pcb(-bx), 0, width=w))
    drawings.append(EdgeLine(mm_to_pcb(bx), 0, mm_to_pcb(spacing / 2.0), 0, width=w))

    return Footprint(name=name,
                      reference=_ref_text(0, -(by + SILK_CLEARANCE_MM)),
                      value=_val_text(0, by + SILK_CLEARANCE_MM),
                      drawings=drawings, pads=pads)


def pin_rows(name: str = 'snp8', rows: int = 2, per_row: int = 4, pitch: float = 2.5,
             row_gap: float = 5.0, body_w: float = 12.5, body_h: float = 25.0,
             hole: float = 3.0, pad: float = DEFAULT_PAD_SIZE_MM,
             drill: float = DEFAULT_DRILL_MM) -> Footprint:
    """Корпус разъёма (ТЗ §3.2.3, snp8): `rows` столбцов по `per_row`
    сигнальных площадок, шаг в столбце `pitch`, расстояние между столбцами
    `row_gap`. Нумерация по столбцам сверху вниз (1..per_row в левом,
    per_row+1..per_row*rows в следующем и т.д. — порядок явно не задан на
    рисунке ТЗ, взят предложенный по умолчанию вариант, см. §3.2.3).
    Площадка 1 — квадратная (слева вверху). Контур body_w x body_h — справа
    от последнего столбца площадок, его левый край совпадает с этим
    столбцом. Два монтажных (не электрических) отверстия диаметром `hole`
    на вертикальной оси контура, по 2,5 мм от верхнего/нижнего края.
    Ref сверху, Val** снизу."""
    y0 = (per_row - 1) * pitch / 2.0
    x_span = (rows - 1) * row_gap
    pads: List[Pad] = []
    num = 1
    for col in range(rows):
        x_mm = -x_span / 2.0 + col * row_gap
        for k in range(per_row):
            y_mm = -y0 + k * pitch
            pads.append(_round_pad(num, x_mm, y_mm, pad, drill, square=(num == 1)))
            num += 1

    left_edge_x = x_span / 2.0
    right_edge_x = left_edge_x + body_w
    body_cx = (left_edge_x + right_edge_x) / 2.0
    by = body_h / 2.0
    w = mm_to_pcb(DEFAULT_EDGE_WIDTH_MM)
    x0, x1 = mm_to_pcb(left_edge_x), mm_to_pcb(right_edge_x)
    y0i, y1i = mm_to_pcb(-by), mm_to_pcb(by)
    drawings: List[DrawItem] = [
        EdgeLine(x0, y0i, x1, y0i, width=w),
        EdgeLine(x1, y0i, x1, y1i, width=w),
        EdgeLine(x1, y1i, x0, y1i, width=w),
        EdgeLine(x0, y1i, x0, y0i, width=w),
    ]

    holes = [
        _mounting_hole(body_cx, -(by - 2.5), hole),
        _mounting_hole(body_cx, by - 2.5, hole),
    ]

    return Footprint(name=name,
                      reference=_ref_text(body_cx, -(by + SILK_CLEARANCE_MM)),
                      value=_val_text(body_cx, by + SILK_CLEARANCE_MM),
                      drawings=drawings, pads=pads + holes)
