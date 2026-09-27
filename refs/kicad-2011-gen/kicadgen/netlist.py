"""Список цепей EESchema bzr2986 («формат Pcbnew», файл ``.net``).

Реплика двух вещей:

* ``SCH_EDIT_FRAME::BuildNetListBase`` (eeschema/netlist.cpp:86-310) —
  вычисление связности: объекты NETLIST_OBJECT из выводов, проводов, шин,
  соединений, меток, NoConnect; проходы PointToPointConnect,
  SegmentToPointConnect, ConnectBusLabels, LabelConnect, SheetLabelConnect,
  PropageNetCode; сжатие номеров цепей; SetUnconnectedFlag;
  FindBestNetNameForEachNet.
* ``EXPORT_HELP::WriteNetListPCBNEW`` (eeschema/netform.cpp:1486-1629) —
  текст файла: заголовок, блоки компонентов с путём /<timestamp>, корпусом,
  ссылкой, значением, ``{Lib=…}`` и строками выводов ``( <num> <net> )``,
  секция ``{ Allowed footprints by component:``, секция ``{ Pin List by Nets``.

Перед построением списка EESchema делает ``SchematicCleanUp``
(sch_screen.cpp:450-496, netlist_control.cpp:574-577): склеивает коллинеарные
провода с общим концом. Это повторено в :func:`schematic_cleanup`.

Единицы — милы, координаты листа (Y вниз). Python 3.8, только stdlib.
"""

from __future__ import annotations

import copy
import functools
import io
import math
import os
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from . import model as M
from . import sch as S
from .textio import kicad_date

NETLIST_HEAD_STRING = 'EESchema Netlist Version 1.1'   # netlist.h:44
NETLIST_EXTENSION = 'net'                                # common/common.cpp:58

Point = Tuple[int, int]


class NetlistError(Exception):
    pass


# --- Типы объектов (class_netlist_object.h:15-49) ------------------------------

class NetType(IntEnum):
    UNSPECIFIED = 0
    SEGMENT = 1            # провод
    BUS = 2                # шина
    JUNCTION = 3           # Connection
    LABEL = 4              # локальная метка
    GLOBLABEL = 5          # глобальная метка
    HIERLABEL = 6          # иерархическая метка (внутри листа)
    SHEETLABEL = 7         # вывод иерархического листа (снаружи)
    BUSLABELMEMBER = 8     # член шинной метки NAME[a..b]
    GLOBBUSLABELMEMBER = 9
    HIERBUSLABELMEMBER = 10
    SHEETBUSLABELMEMBER = 11
    PINLABEL = 12          # невидимый вывод «Вход питания» = глобальная метка
    PIN = 13
    NOCONNECT = 14


class Connect(IntEnum):
    """m_FlagOfConnection (class_netlist_object.h:52-58)."""
    UNCONNECTED = 0
    NOCONNECT_SYMBOL_PRESENT = 1
    PAD_CONNECT = 2


# --- Путь листа (sch_sheet_path.cpp) ------------------------------------------

class SheetPath:
    """SCH_SHEET_PATH без корневого листа: ``sheets`` — вложенные S.Sheet,
    ``schematic`` — экран последнего листа (для корня — корневая схема).

    * ``path()``      — ``/`` + ``%8.8lX/`` на каждый вложенный лист (:171-187);
    * ``human()``     — ``/`` + ``<имя листа>/`` … (:190-204);
    * ``cmp()``       — сначала глубина, затем метки времени (:72-100).
    """

    __slots__ = ('sheets', 'schematic')

    def __init__(self, sheets: Tuple[S.Sheet, ...] = (), schematic: Optional[S.Schematic] = None):
        self.sheets = tuple(sheets)
        self.schematic = schematic

    @property
    def key(self) -> Tuple[int, ...]:
        return tuple(int(s.timestamp) & 0xFFFFFFFF for s in self.sheets)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SheetPath) and self.key == other.key

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.key)

    def cmp(self, other: 'SheetPath') -> int:
        a, b = self.key, other.key
        if len(a) != len(b):
            return 1 if len(a) > len(b) else -1
        for x, y in zip(a, b):
            if x != y:
                return 1 if x > y else -1
        return 0

    def path(self) -> str:
        return '/' + ''.join('%8.8X/' % ts for ts in self.key)

    def human(self) -> str:
        return '/' + ''.join(s.name + '/' for s in self.sheets)

    def push(self, sheet: S.Sheet, schematic: S.Schematic) -> 'SheetPath':
        return SheetPath(self.sheets + (sheet,), schematic)

    def __repr__(self) -> str:
        return 'SheetPath(%s)' % self.human()


SheetLoader = Callable[[str], S.Schematic]


def build_sheet_list(root: S.Schematic, loader: Optional[SheetLoader] = None) -> List[SheetPath]:
    """SCH_SHEET_LIST::BuildSheetList (sch_sheet_path.cpp:513-549): обход в
    глубину, родитель перед потомками, потомки — в порядке списка отрисовки.
    Подлисты грузятся ``loader(filename)``; без загрузчика подлисты — ошибка."""
    out: List[SheetPath] = []
    cache: Dict[str, S.Schematic] = {}

    def walk(path: SheetPath, depth: int) -> None:
        if depth > 32:
            raise NetlistError('sheet nesting too deep (recursive hierarchy?)')
        out.append(path)
        for it in path.schematic.items:
            if isinstance(it, S.Sheet):
                if it.filename not in cache:
                    if loader is None:
                        raise NetlistError('hierarchical sheet %r (%s): no sheet loader given'
                                           % (it.name, it.filename))
                    cache[it.filename] = loader(it.filename)
                if not it.timestamp:
                    it.timestamp = S.new_timestamp()
                walk(path.push(it, cache[it.filename]), depth + 1)

    walk(SheetPath((), root), 0)
    return out


def file_sheet_loader(base_dir: str) -> SheetLoader:
    """Загрузчик подлистов из каталога корневой схемы."""
    def load(filename: str) -> S.Schematic:
        p = filename if os.path.isabs(filename) else os.path.join(base_dir, filename)
        sub, _ = S.load_schematic(p)
        return sub
    return load


# --- Очистка схемы перед построением (SchematicCleanUp) -------------------------

def _merge_overlap(a: S.Wire, b: S.Wire) -> bool:
    """SCH_LINE::MergeOverlap (sch_line.cpp:260-321), включая побочные
    перестановки концов, которые остаются даже при результате false."""
    if a is b or a.layer != b.layer:
        return False
    a_s, a_e = (a.x1, a.y1), (a.x2, a.y2)
    b_s, b_e = (b.x1, b.y1), (b.x2, b.y2)
    if a_s == b_s:
        if a_e == b_e:
            return True
        a_s, a_e = a_e, a_s
    elif a_s == b_e:
        a_s, a_e = a_e, a_s
        b_s, b_e = b_e, b_s
    elif a_e == b_e:
        b_s, b_e = b_e, b_s
    elif a_e != b_s:
        return False
    a.x1, a.y1 = a_s
    a.x2, a.y2 = a_e
    b.x1, b.y1 = b_s
    b.x2, b.y2 = b_e
    merged = False
    if a_s[1] == a_e[1]:                       # горизонтальный
        merged = b_s[1] == b_e[1]
    elif a_s[0] == a_e[0]:                     # вертикальный
        merged = b_s[0] == b_e[0]
    else:
        merged = (math.atan2(float(a_s[0] - a_e[0]), float(a_s[1] - a_e[1]))
                  == math.atan2(float(b_s[0] - b_e[0]), float(b_s[1] - b_e[1])))
    if merged:
        a.x2, a.y2 = b_e
    return merged


def schematic_cleanup(items: Sequence[S.SchItem]) -> List[S.SchItem]:
    """SCH_SCREEN::SchematicCleanUp (sch_screen.cpp:450-496) на копии списка:
    для каждой линии ищется следующая линия с общим концом на той же прямой,
    вторая удаляется, поиск начинается с головы списка заново."""
    out: List[S.SchItem] = [copy.copy(it) if isinstance(it, S.Wire) else it for it in items]
    i = 0
    while i < len(out):
        line = out[i]
        if isinstance(line, S.Wire):
            j = i + 1
            while j < len(out):
                tst = out[j]
                if isinstance(tst, S.Wire) and j != i and _merge_overlap(line, tst):
                    del out[j]
                    if j < i:
                        i -= 1
                    j = 0                       # TstDrawList = GetDrawItems()
                else:
                    j += 1
        i += 1
    return out


# --- Объект связности --------------------------------------------------------

@dataclass
class NetObject:
    """NETLIST_OBJECT (class_netlist_object.h:61-130)."""
    type: NetType
    sheet: SheetPath                     # m_SheetList
    start: Point
    end: Point
    label: str = ''                      # m_Label: текст метки / имя вывода
    net: int = 0                         # m_NetCode
    bus_net: int = 0                     # m_BusNetCode
    member: int = 0                      # m_Member
    flag: int = 0                        # m_Flag (дубликаты выводов при записи)
    conn: Connect = Connect.UNCONNECTED  # m_FlagOfConnection
    pin_num: str = ''                    # m_PinNum как строка (<= 4 байт)
    etype: Optional[M.PinType] = None    # m_ElectricalType (для выводов)
    comp: Optional[S.SchComponent] = None   # m_Link для NET_PIN
    pin: Optional[M.Pin] = None          # m_Comp для NET_PIN
    item: object = None                  # m_Comp: элемент схемы
    sheet_include: Optional[SheetPath] = None  # m_SheetListInclude
    name_candidate: Optional['NetObject'] = None  # m_NetNameCandidate

    def clone(self) -> 'NetObject':
        return copy.copy(self)


# --- Вспомогательное --------------------------------------------------------------

def _isdigit(ch: str) -> bool:
    return '0' <= ch <= '9'


def _strtol(s: str) -> int:
    """strtol(s, NULL, 10): пробелы, знак, цифры; 0, если цифр нет."""
    i, n = 0, len(s)
    while i < n and s[i] in ' \t\n\r\x0b\x0c':
        i += 1
    sign = 1
    if i < n and s[i] in '+-':
        sign = -1 if s[i] == '-' else 1
        i += 1
    j = i
    while j < n and _isdigit(s[j]):
        j += 1
    return sign * int(s[i:j]) if j > i else 0


def _cmp(a: str, b: str) -> int:
    """wxString::Cmp — по кодам символов."""
    return (a > b) - (a < b)


def _cmp_nocase(a: str, b: str) -> int:
    """wxString::CmpNoCase."""
    a2, b2 = a.lower(), b.lower()
    return (a2 > b2) - (a2 < b2)


def split_string(s: str) -> Tuple[str, str, str]:
    """SplitString (common/string.cpp:469-522): <начало><последние цифры><хвост>."""
    if not s:
        return '', '', ''
    ii = len(s) - 1
    while ii >= 0 and not _isdigit(s[ii]):
        ii -= 1
    if ii < 0:
        return s, '', ''
    end = s[ii + 1:]
    position = ii + 1
    while ii >= 0 and _isdigit(s[ii]):
        ii -= 1
    if ii < 0:
        return '', s[:position], end
    return s[:ii + 1], s[ii + 1:position], end


def refdes_compare(a: str, b: str) -> int:
    """RefDesStringCompare (common/string.cpp:414-466): начала без регистра,
    числа по значению, хвосты без регистра."""
    ab, am, ae = split_string(a)
    bb, bm, be = split_string(b)
    r = _cmp_nocase(ab, bb)
    if r:
        return r
    na, nb = _strtol(am), _strtol(bm)
    if na != nb:
        return 1 if na > nb else -1
    return _cmp_nocase(ae, be)


def is_bus_label(text: str) -> Tuple[int, int, int, int]:
    """IsBusLabel (netlist.cpp:785-846): (число членов, первый, последний,
    длина корневого имени); 0 членов — не шинная метка."""
    ii = text.find('[')
    if ii < 0:
        return 0, 0, 0, 0
    root_len = ii
    num = ii + 1
    buf = ''
    while num < len(text) and text[num] != '.':
        buf += text[num]
        num += 1
    first = _strtol(buf)
    while num < len(text) and text[num] == '.':
        num += 1
    buf = ''
    while num < len(text) and text[num] != ']':
        buf += text[num]
        num += 1
    last = _strtol(buf)
    first = max(first, 0)
    last = max(last, 0)
    if first > last:
        first, last = last, first
    return last - first + 1, first, last, root_len


def _convert_bus_to_members(buf: List[NetObject], obj: NetObject, first: int, last: int,
                            root_len: int) -> int:
    """ConvertBusToMembers (netlist.cpp:852-895)."""
    if obj.type == NetType.HIERLABEL:
        obj.type = NetType.HIERBUSLABELMEMBER
    elif obj.type == NetType.GLOBLABEL:
        obj.type = NetType.GLOBBUSLABELMEMBER
    elif obj.type == NetType.SHEETLABEL:
        obj.type = NetType.SHEETBUSLABELMEMBER
    else:
        obj.type = NetType.BUSLABELMEMBER
    root = obj.label[:root_len]
    obj.label = root + str(first)
    obj.member = first
    n = 1
    for m in range(first + 1, last + 1):
        new = obj.clone()
        new.label = root + str(m)
        new.member = m
        buf.append(new)
        n += 1
    return n


def _segment_intersect(seg_start: Point, seg_end: Point, p: Point) -> bool:
    """SegmentIntersect (dangling_ends.cpp:19-33): точка на отрезке (включая
    концы)."""
    vx, vy = seg_end[0] - seg_start[0], seg_end[1] - seg_start[1]
    px, py = p[0] - seg_start[0], p[1] - seg_start[1]
    if vx * py - vy * px:
        return False
    if vx * px + vy * py < px * px + py * py:
        return False
    return True


# --- Доступ к компоненту (sch_component.cpp) -------------------------------------

Libraries = Union[M.Library, Sequence[M.Library]]


def _libs(library: Libraries) -> List[M.Library]:
    if isinstance(library, M.Library):
        return [library]
    return list(library)


def find_lib_component(library: Libraries, name: str) -> Optional[M.Component]:
    """CMP_LIBRARY::FindLibraryComponent: первая библиотека, где есть имя или
    алиас (без учёта регистра)."""
    for lib in _libs(library):
        c = lib.find(name)
        if c is not None:
            return c
    return None


def component_path(comp: S.SchComponent, sheet: SheetPath) -> str:
    """SCH_COMPONENT::GetPath (sch_component.cpp:329-335): <путь листа><%8.8lX ts>."""
    if not comp.timestamp:
        comp.timestamp = S.new_timestamp()
    return sheet.path() + '%8.8X' % (int(comp.timestamp) & 0xFFFFFFFF)


def component_ref(comp: S.SchComponent, sheet: SheetPath) -> str:
    """SCH_COMPONENT::GetRef (sch_component.cpp:338-370): запись AR для этого пути, иначе поле F0, иначе
    префикс."""
    path = component_path(comp, sheet)
    for p, r, _part in comp.ar:
        if p == path:
            return r
    f0 = comp.field(M.REFERENCE)
    if f0 is not None and f0.text:
        return f0.text
    return comp.reference


def component_unit(comp: S.SchComponent, sheet: SheetPath) -> int:
    """SCH_COMPONENT::GetUnitSelection (sch_component.cpp:447-470): запись AR для этого пути, иначе m_unit."""
    path = component_path(comp, sheet)
    for p, _r, part in comp.ar:
        if p == path:
            return part
    return comp.unit


def component_value(comp: S.SchComponent) -> str:
    f1 = comp.field(M.VALUE)
    if f1 is not None:
        return f1.text
    return comp.value if comp.value is not None else comp.lib_name


def component_footprint(comp: S.SchComponent) -> str:
    """Поле F2; IsVoid (sch_field.h:71-76): пусто или ``~`` -> ``$noname``."""
    f2 = comp.field(M.FOOTPRINT)
    text = f2.text if f2 is not None else ''
    if text == '' or text == '~':
        return '$noname'
    return text.replace(' ', '_')


def lib_pins_sorted(entry: M.Component) -> List[M.Pin]:
    """Порядок выводов как в LIB_COMPONENT::drawings после ``drawings.sort()``
    при загрузке (class_libentry.cpp:805; LIB_ITEM::operator<)."""
    return [it for it in sorted(entry.items, key=M.item_sort_key) if isinstance(it, M.Pin)]


def pin_position(comp: S.SchComponent, pin: M.Pin) -> Point:
    return comp.pin_position(pin)


# --- Построение объектов (AddConnectedObjects, netlist.cpp:506-735) --------------

def _add_connected_objects(sheet: SheetPath, items: Sequence[S.SchItem], library: Libraries,
                           buf: List[NetObject], warnings: List[str]) -> None:
    for it in items:
        if isinstance(it, S.Wire):
            if it.layer == 'Bus':
                t = NetType.BUS
            elif it.layer == 'Wire':
                t = NetType.SEGMENT
            else:
                continue
            buf.append(NetObject(t, sheet, (it.x1, it.y1), (it.x2, it.y2), item=it,
                                 sheet_include=sheet))
        elif isinstance(it, S.Junction):
            buf.append(NetObject(NetType.JUNCTION, sheet, (it.x, it.y), (it.x, it.y), item=it,
                                 sheet_include=sheet))
        elif isinstance(it, S.NoConnect):
            buf.append(NetObject(NetType.NOCONNECT, sheet, (it.x, it.y), (it.x, it.y), item=it,
                                 sheet_include=sheet))
        elif isinstance(it, S.Note):
            continue
        elif isinstance(it, S.Label):
            if isinstance(it, S.GlobalLabel):
                t = NetType.GLOBLABEL
            elif isinstance(it, S.HierLabel):
                t = NetType.HIERLABEL
            else:
                t = NetType.LABEL
            n, first, last, root_len = is_bus_label(it.text)
            obj = NetObject(t, sheet, (it.x, it.y), (it.x, it.y), label=it.text, item=it,
                            sheet_include=sheet)
            buf.append(obj)
            if n:
                _convert_bus_to_members(buf, obj, first, last, root_len)
        elif isinstance(it, S.SchComponent):
            entry = find_lib_component(library, it.lib_name)
            if entry is None:
                warnings.append('component %s: library part %r not found, pins ignored'
                                % (it.reference, it.lib_name))
                continue
            unit = component_unit(it, sheet)
            for pin in lib_pins_sorted(entry):
                if pin.unit and pin.unit != unit:
                    continue
                if pin.convert and pin.convert != it.convert:
                    continue
                pos = pin_position(it, pin)
                buf.append(NetObject(NetType.PIN, sheet, pos, pos, label=pin.name,
                                     pin_num=pin.number, etype=pin.etype, comp=it, pin=pin,
                                     item=pin, sheet_include=sheet))
                if pin.etype is M.PinType.POWER_IN and not pin.visible:
                    buf.append(NetObject(NetType.PINLABEL, sheet, pos, pos, label=pin.name,
                                         sheet_include=sheet))
        elif isinstance(it, S.Sheet):
            inner = sheet.push(it, sheet.schematic)   # m_SheetListInclude = list + sheet
            for sp in it.pins:
                n, first, last, root_len = is_bus_label(sp.name)
                obj = NetObject(NetType.SHEETLABEL, sheet, (sp.x, sp.y), (sp.x, sp.y),
                                label=sp.name, item=sp, comp=None, sheet_include=inner)
                buf.append(obj)
                if n:
                    _convert_bus_to_members(buf, obj, first, last, root_len)
        else:
            # BusEntry, Poly (уже развёрнут в Wire), маркеры — не участвуют
            continue


# --- Проходы связности (netlist.cpp) ---------------------------------------------

class _Builder:
    def __init__(self) -> None:
        self.objs: List[NetObject] = []
        self.last_net = 1
        self.last_bus = 1

    # PropageNetCode (:901-930)
    def propagate(self, old: int, new: int, is_bus: bool) -> None:
        if old == new:
            return
        if not is_bus:
            for o in self.objs:
                if o.net == old:
                    o.net = new
        else:
            for o in self.objs:
                if o.bus_net == old:
                    o.bus_net = new

    _P2P_WIRE = frozenset([NetType.SEGMENT, NetType.PIN, NetType.LABEL, NetType.HIERLABEL,
                           NetType.GLOBLABEL, NetType.SHEETLABEL, NetType.PINLABEL,
                           NetType.JUNCTION, NetType.NOCONNECT])
    _P2P_BUS = frozenset([NetType.BUS, NetType.BUSLABELMEMBER, NetType.SHEETBUSLABELMEMBER,
                          NetType.HIERBUSLABELMEMBER, NetType.GLOBBUSLABELMEMBER,
                          NetType.JUNCTION])

    # PointToPointConnect (:950-1038)
    def point_to_point(self, ref: NetObject, is_bus: bool, start: int) -> None:
        objs = self.objs
        if not is_bus:
            code = ref.net
            for i in range(start, len(objs)):
                item = objs[i]
                if item.sheet != ref.sheet:
                    continue
                if item.type not in self._P2P_WIRE:
                    continue
                if (ref.start == item.start or ref.start == item.end
                        or ref.end == item.start or ref.end == item.end):
                    if item.net == 0:
                        item.net = code
                    else:
                        self.propagate(item.net, code, False)
        else:
            code = ref.bus_net
            for i in range(start, len(objs)):
                item = objs[i]
                if item.sheet != ref.sheet:
                    continue
                if item.type not in self._P2P_BUS:
                    continue
                if (ref.start == item.start or ref.start == item.end
                        or ref.end == item.start or ref.end == item.end):
                    if item.bus_net == 0:
                        item.bus_net = code
                    else:
                        self.propagate(item.bus_net, code, True)

    # SegmentToPointConnect (:1048-1091)
    def segment_to_point(self, junction: NetObject, is_bus: bool, start: int) -> None:
        want = NetType.BUS if is_bus else NetType.SEGMENT
        for i in range(start, len(self.objs)):
            seg = self.objs[i]
            if seg.sheet != junction.sheet or seg.type != want:
                continue
            if _segment_intersect(seg.start, seg.end, junction.start):
                if not is_bus:
                    if seg.net:
                        self.propagate(seg.net, junction.net, False)
                    else:
                        seg.net = junction.net
                else:
                    if seg.bus_net:
                        self.propagate(seg.bus_net, junction.bus_net, True)
                    else:
                        seg.bus_net = junction.bus_net

    # Основной цикл BuildNetListBase (:120-222)
    def connect_sheet_local(self) -> None:
        objs = self.objs
        if not objs:
            return
        sheet = objs[0].sheet
        istart = 0
        for ii, item in enumerate(objs):
            if item.sheet != sheet:
                sheet = item.sheet
                istart = ii
            t = item.type
            if t in (NetType.PIN, NetType.PINLABEL, NetType.SHEETLABEL, NetType.NOCONNECT):
                if item.net != 0:
                    continue
                t = NetType.SEGMENT                      # fallthrough
            if t == NetType.SEGMENT:
                if item.net == 0:
                    item.net = self.last_net
                    self.last_net += 1
                self.point_to_point(item, False, istart)
            elif t == NetType.JUNCTION:
                if item.net == 0:
                    item.net = self.last_net
                    self.last_net += 1
                self.segment_to_point(item, False, istart)
                if item.bus_net == 0:
                    item.bus_net = self.last_bus
                    self.last_bus += 1
                self.segment_to_point(item, True, istart)
            elif t in (NetType.LABEL, NetType.HIERLABEL, NetType.GLOBLABEL):
                if item.net == 0:
                    item.net = self.last_net
                    self.last_net += 1
                self.segment_to_point(item, False, istart)
            elif t in (NetType.SHEETBUSLABELMEMBER, NetType.BUS):
                if t == NetType.SHEETBUSLABELMEMBER and item.bus_net != 0:
                    continue
                if item.bus_net == 0:
                    item.bus_net = self.last_bus
                    self.last_bus += 1
                self.point_to_point(item, True, istart)
            elif t in (NetType.BUSLABELMEMBER, NetType.HIERBUSLABELMEMBER,
                       NetType.GLOBBUSLABELMEMBER):
                if item.net == 0:                        # sic: проверяется NetCode (:207)
                    item.bus_net = self.last_bus
                    self.last_bus += 1
                self.segment_to_point(item, True, istart)

    _BUS_MEMBERS = frozenset([NetType.SHEETBUSLABELMEMBER, NetType.BUSLABELMEMBER,
                              NetType.HIERBUSLABELMEMBER])

    # ConnectBusLabels (:740-780)
    def connect_bus_labels(self) -> None:
        objs = self.objs
        for ii, label in enumerate(objs):
            if label.type not in self._BUS_MEMBERS:
                continue
            if label.net == 0:
                label.net = self.last_net
                self.last_net += 1
            for jj in range(ii + 1, len(objs)):
                tst = objs[jj]
                if tst.type not in self._BUS_MEMBERS:
                    continue
                if tst.bus_net != label.bus_net or tst.member != label.member:
                    continue
                if tst.net == 0:
                    tst.net = label.net
                else:
                    self.propagate(tst.net, label.net, False)

    _LABELISH = frozenset([NetType.LABEL, NetType.GLOBLABEL, NetType.HIERLABEL,
                           NetType.BUSLABELMEMBER, NetType.GLOBBUSLABELMEMBER,
                           NetType.HIERBUSLABELMEMBER, NetType.PINLABEL])

    # LabelConnect (:1097-1142)
    def label_connect(self, ref: NetObject) -> None:
        if ref.net == 0:
            return
        for o in self.objs:
            if o.net == ref.net:
                continue
            if o.sheet != ref.sheet:
                if o.type not in (NetType.PINLABEL, NetType.GLOBLABEL, NetType.GLOBBUSLABELMEMBER):
                    continue
                if (o.type in (NetType.GLOBLABEL, NetType.GLOBBUSLABELMEMBER)
                        and o.type != ref.type):
                    continue      # глобальные метки соединяют только глобальные
            if o.type in self._LABELISH:
                if _cmp_nocase(o.label, ref.label) != 0:
                    continue
                if o.net:
                    self.propagate(o.net, ref.net, False)
                else:
                    o.net = ref.net

    # SheetLabelConnect (:463-500)
    def sheet_label_connect(self, sheet_label: NetObject) -> None:
        if sheet_label.net == 0:
            return
        for o in self.objs:
            if o.sheet != sheet_label.sheet_include:
                continue
            if o.type not in (NetType.HIERLABEL, NetType.HIERBUSLABELMEMBER):
                continue
            if o.net == sheet_label.net:
                continue
            if _cmp_nocase(o.label, sheet_label.label) != 0:
                continue
            if o.net:
                self.propagate(o.net, sheet_label.net, False)
            else:
                o.net = sheet_label.net

    # SetUnconnectedFlag (:1168-1251)
    def set_unconnected_flags(self) -> None:
        objs = self.objs
        n = len(objs)
        net_start = 0
        state = Connect.UNCONNECTED
        for ii in range(n):
            ref = objs[ii]
            if ref.type == NetType.NOCONNECT and state != Connect.PAD_CONNECT:
                state = Connect.NOCONNECT_SYMBOL_PRESENT
            idx = ii + 1
            if idx >= n or ref.net != objs[idx].net:
                for kk in range(net_start, idx):
                    objs[kk].conn = state
                if idx >= n:
                    return
                state = Connect.UNCONNECTED
                net_start = idx
                continue
            while idx < n and ref.net == objs[idx].net:
                t = objs[idx].type
                if t == NetType.PIN:
                    if ref.type == NetType.PIN:
                        state = Connect.PAD_CONNECT
                elif t == NetType.NOCONNECT:
                    if state != Connect.PAD_CONNECT:
                        state = Connect.NOCONNECT_SYMBOL_PRESENT
                idx += 1

    # FindBestNetName (:380-458)
    @staticmethod
    def best_net_name(cands: List[NetObject]) -> Optional[NetObject]:
        if not cands:
            return None
        prio_order = [NetType.UNSPECIFIED, NetType.LABEL, NetType.HIERLABEL,
                      NetType.PINLABEL, NetType.GLOBLABEL]
        prio_max = 4

        def prio(o: NetObject) -> int:
            for i, t in enumerate(prio_order):
                if o.type == t:
                    return i
            return 0

        item = cands[0]
        item_prio = prio(item)
        for cand in cands[1:]:
            cp = prio(cand)
            if cp > item_prio:
                item, item_prio = cand, cp
            elif cp == item_prio:
                if item_prio >= prio_max - 1:                  # глобальная / pin label
                    if _cmp(cand.label, item.label) < 0:
                        item = cand
                else:
                    lc, li = len(cand.sheet.path()), len(item.sheet.path())
                    if lc < li:
                        item = cand
                    elif lc == li and _cmp(cand.label, item.label) < 0:
                        item = cand
        return item

    # FindBestNetNameForEachNet (:322-368)
    def find_best_net_names(self) -> None:
        objs = self.objs
        if not objs:
            return
        cands: List[NetObject] = []
        netcode = 0
        idxstart = 0
        for ii in range(len(objs) + 1):
            item = objs[ii] if ii < len(objs) else None
            code = -2 if item is None else item.net
            if netcode != code:
                if cands:
                    best = self.best_net_name(cands)
                    for jj in range(idxstart, ii):
                        objs[jj].name_candidate = best
                if item is None:
                    break
                netcode = code
                cands = []
                idxstart = ii
            if item.type in (NetType.HIERLABEL, NetType.LABEL, NetType.PINLABEL, NetType.GLOBLABEL):
                cands.append(item)


def build_net_objects(schematic: S.Schematic, library: Libraries,
                      loader: Optional[SheetLoader] = None,
                      warnings: Optional[List[str]] = None
                      ) -> Tuple[List[NetObject], List[SheetPath], Dict[SheetPath, List[S.SchItem]]]:
    """BuildNetListBase (netlist.cpp:86-310) поверх SchematicCleanUp.

    Возвращает (объекты, отсортированные по коду цепи; список путей листов;
    очищенные списки элементов по листам — в них порядок компонентов для
    записи файла)."""
    w = warnings if warnings is not None else []
    sheets = build_sheet_list(schematic, loader)
    cleaned: Dict[SheetPath, List[S.SchItem]] = {}
    b = _Builder()
    for sp in sheets:
        items = schematic_cleanup(sp.schematic.items)
        cleaned[sp] = items
        _add_connected_objects(sp, items, library, b.objs, w)
    if not b.objs:
        return [], sheets, cleaned
    # sort( SortItemsBySheet ) — стабильная сортировка (см. docs/netlist-format.md)
    b.objs.sort(key=functools.cmp_to_key(lambda x, y: x.sheet.cmp(y.sheet)))
    b.connect_sheet_local()
    b.connect_bus_labels()
    for o in list(b.objs):
        if o.type in (NetType.LABEL, NetType.GLOBLABEL, NetType.PINLABEL,
                      NetType.BUSLABELMEMBER, NetType.GLOBBUSLABELMEMBER):
            b.label_connect(o)
    for o in list(b.objs):
        if o.type in (NetType.SHEETLABEL, NetType.SHEETBUSLABELMEMBER):
            b.sheet_label_connect(o)
    b.objs.sort(key=lambda o: o.net)             # sort( SortItemsbyNetcode ), стабильно
    last = 0
    code = 0
    for o in b.objs:                              # сжатие кодов (:291-300)
        if o.net != last:
            code += 1
            last = o.net
        o.net = code
    b.set_unconnected_flags()
    b.find_best_net_names()
    return b.objs, sheets, cleaned


# --- Имена цепей (netform.cpp:463-500) --------------------------------------------

def pin_net_name(pin: NetObject, fmt: str = 'N-%.6d') -> str:
    """sprintPinNetName: '' если вывод не подключён (нет второго вывода в цепи),
    ``<метка>`` для глобальных, ``<путь листа><метка>`` для локальных, иначе
    ``N-%06d``."""
    if pin.net == 0 or pin.conn != Connect.PAD_CONNECT:
        return ''
    ref = pin.name_candidate
    result = ref.label if ref is not None else ''
    if result:
        if ref.type not in (NetType.PINLABEL, NetType.GLOBLABEL):
            prefix = ref.sheet.human()
            if len(prefix) > 32:
                prefix = ref.sheet.path()
            result = prefix + result
        return result
    return fmt % pin.net


# --- Список компонентов и их выводов (netform.cpp:550-637, 1632-1765) -------------

class _ComponentPins:
    """findNextComponentAndCreatePinList + addPinToComponentPinList +
    eraseDuplicatePins."""

    def __init__(self, objs: List[NetObject], sheets: List[SheetPath],
                 cleaned: Dict[SheetPath, List[S.SchItem]], library: Libraries):
        self.objs = objs
        self.sheets = sheets
        self.cleaned = cleaned
        self.library = library
        self.refs_found: set = set()          # m_ReferencesAlreadyFound (с учётом регистра)

    def add_pin(self, out: List[Optional[NetObject]], comp: S.SchComponent, sheet: SheetPath,
                pin: M.Pin) -> bool:
        for o in self.objs:
            if o.type != NetType.PIN or o.comp is not comp:
                continue
            if o.pin_num != pin.number:
                continue
            if o.sheet != sheet:
                continue
            out.append(o)
            return True
        return False

    def all_instances(self, out: List[Optional[NetObject]], comp: S.SchComponent,
                      entry: M.Component, sheet: SheetPath) -> None:
        ref = component_ref(comp, sheet)
        for sp in self.sheets:
            for it in self.cleaned[sp]:
                if not isinstance(it, S.SchComponent):
                    continue
                if _cmp_nocase(component_ref(it, sp), ref) != 0:
                    continue
                unit2 = component_unit(it, sp)
                for pin in lib_pins_sorted(entry):
                    if pin.unit and pin.unit != unit2:
                        continue
                    if pin.convert and pin.convert != it.convert:
                        continue
                    self.add_pin(out, it, sp, pin)

    @staticmethod
    def erase_duplicates(pins: List[Optional[NetObject]]) -> None:
        n = len(pins)
        for ii in range(n):
            if pins[ii] is None:
                continue
            idxref = ii
            for jj in range(ii + 1, n):
                if pins[jj] is None:
                    continue
                if pins[idxref].pin_num != pins[jj].pin_num:
                    break
                if pins[idxref].conn == Connect.PAD_CONNECT:
                    pins[jj].flag = 1
                    pins[jj] = None
                elif pins[jj].conn == Connect.PAD_CONNECT:
                    pins[idxref].flag = 1
                    pins[idxref] = None
                    idxref = jj
                else:
                    pins[jj].flag = 1
                    pins[jj] = None

    def components(self):
        """Генератор (компонент, лист, entry, [выводы|None]) в порядке файла;
        символы питания (#…) и неизвестные компоненты пропускаются."""
        for sp in self.sheets:
            for it in self.cleaned[sp]:
                if not isinstance(it, S.SchComponent):
                    continue
                ref = component_ref(it, sp)
                if ref[:1] == '#':
                    continue
                entry = find_lib_component(self.library, it.lib_name)
                if entry is None:
                    continue
                pins: List[Optional[NetObject]] = []
                if entry.unit_count > 1:
                    if ref in self.refs_found:
                        continue
                    self.refs_found.add(ref)
                    self.all_instances(pins, it, entry, sp)
                else:
                    unit = component_unit(it, sp)
                    for pin in lib_pins_sorted(entry):
                        if unit and pin.unit and pin.unit != unit:
                            continue
                        if it.convert and pin.convert and pin.convert != it.convert:
                            continue
                        self.add_pin(pins, it, sp, pin)
                pins.sort(key=functools.cmp_to_key(
                    lambda a, c: refdes_compare(a.pin_num, c.pin_num)))
                self.erase_duplicates(pins)
                yield it, sp, entry, pins


# --- Итог для пользователя ----------------------------------------------------------

@dataclass
class Net:
    code: int
    name: str                          # имя для строк выводов ('' = нет)
    label: str                         # «короткое» имя (метка) или ''
    pins: List[Tuple[str, str]] = field(default_factory=list)   # (ссылка, номер вывода)
    connected: bool = False            # PAD_CONNECT
    objects: List[NetObject] = field(default_factory=list)

    def pin_names(self) -> List[str]:
        return ['%s.%s' % (r, p) for r, p in self.pins]


def build_nets(schematic: S.Schematic, library: Libraries, loader: Optional[SheetLoader] = None,
               include_power: bool = False) -> List[Net]:
    """Цепи схемы в порядке кодов. ``name`` — как в строках выводов файла
    (``GND``, ``/1``, ``N-000004``; для неподключённых цепей ``''``)."""
    objs, _sheets, _cleaned = build_net_objects(schematic, library, loader)
    nets: Dict[int, Net] = {}
    for o in objs:
        if o.net == 0:
            continue          # код 0 остаётся у шин: у них только BusNetCode
        net = nets.get(o.net)
        if net is None:
            cand = o.name_candidate
            label = cand.label if cand is not None else ''
            name = ''
            if o.conn == Connect.PAD_CONNECT:
                if label:
                    if cand.type in (NetType.PINLABEL, NetType.GLOBLABEL):
                        name = label
                    else:
                        prefix = cand.sheet.human()
                        if len(prefix) > 32:
                            prefix = cand.sheet.path()
                        name = prefix + label
                else:
                    name = 'N-%.6d' % o.net
            net = Net(o.net, name, label, connected=(o.conn == Connect.PAD_CONNECT))
            nets[o.net] = net
        net.objects.append(o)
        if o.type == NetType.PIN and o.comp is not None:
            ref = component_ref(o.comp, o.sheet)
            if (include_power or ref[:1] != '#') and (ref, o.pin_num) not in net.pins:
                net.pins.append((ref, o.pin_num))
    return [nets[k] for k in sorted(nets)]


def format_nets(nets: Sequence[Net]) -> str:
    lines = []
    for n in nets:
        lines.append('%3d %-12s %s' % (n.code, n.name or '?', ' '.join(n.pin_names())))
    return '\n'.join(lines)


# --- Запись файла (WriteNetListPCBNEW, netform.cpp:1486-1629) ---------------------

def check_annotation(schematic: S.Schematic, library: Libraries,
                     loader: Optional[SheetLoader] = None) -> List[str]:
    """Упрощённый CheckAnnotation (component_references_lister.cpp:460-560):
    ссылки, оканчивающиеся на ``?`` или не на цифру, и дубликаты (та же ссылка,
    та же секция). Символы с ``#`` не проверяются."""
    errors: List[str] = []
    seen: Dict[Tuple[str, int], S.SchComponent] = {}
    for sp in build_sheet_list(schematic, loader):
        for it in sp.schematic.items:
            if not isinstance(it, S.SchComponent):
                continue
            ref = component_ref(it, sp)
            if ref[:1] == '#':
                continue
            if not ref or ref.endswith('?') or not _isdigit(ref[-1]):
                errors.append('Item not annotated: %s' % ref)
                continue
            entry = find_lib_component(library, it.lib_name)
            unit = component_unit(it, sp)
            if entry is not None and entry.unit_count > 1 and not (1 <= unit <= entry.unit_count):
                errors.append('Error item %s unit %d and no more than %d parts'
                              % (ref, unit, entry.unit_count))
            key = (ref, unit)
            if key in seen:
                errors.append('Multiple item %s%s' % (ref, ('' if entry is None or entry.unit_count <= 1
                                                              else chr(ord('A') + unit - 1))))
            seen[key] = it
    return errors


def write_netlist_pcbnew(schematic: S.Schematic, library: Libraries, date: Optional[str] = None,
                         with_pcbnew: bool = True, loader: Optional[SheetLoader] = None,
                         check: bool = True) -> str:
    """Текст ``.net`` (LF; для файла KiCad на Windows — CRLF, см. save_netlist).

    ``with_pcbnew=False`` — вариант ORCADPCB2 (без ``{Lib=…}`` и секций)."""
    if check:
        errs = check_annotation(schematic, library, loader)
        if errs:
            raise NetlistError('schematic is not annotated: ' + '; '.join(errs))
    objs, sheets, cleaned = build_net_objects(schematic, library, loader)
    date = date or kicad_date()
    out: List[str] = []
    if with_pcbnew:
        out.append('# %s created  %s\n(\n' % (NETLIST_HEAD_STRING, date))
    else:
        out.append('( { %s created  %s }\n' % (NETLIST_HEAD_STRING, date))
    for o in objs:
        o.flag = 0
    cmp_list: List[Tuple[S.SchComponent, M.Component, SheetPath]] = []
    helper = _ComponentPins(objs, sheets, cleaned, library)
    for comp, sp, entry, pins in helper.components():
        if entry.fplist:
            cmp_list.append((comp, entry, sp))
        out.append(' ( %s %s' % (component_path(comp, sp), component_footprint(comp)))
        out.append('  %s' % component_ref(comp, sp))
        out.append(' %s' % component_value(comp).replace(' ', '_'))
        if with_pcbnew:
            out.append(' {Lib=%s}' % comp.lib_name.replace(' ', '_'))
        out.append('\n')
        for pin in pins:
            if pin is None:
                continue
            name = pin_net_name(pin) or '?'
            name = name.replace(' ', '_')
            out.append('  ( %4.4s %s )\n' % (pin.pin_num, name))
        out.append(' )\n')
    out.append(')\n*\n')
    if with_pcbnew and cmp_list:
        out.append('{ Allowed footprints by component:\n')
        for comp, entry, sp in cmp_list:
            out.append('$component %s\n' % component_ref(comp, sp).replace(' ', '_'))
            for fp in entry.fplist:
                out.append(' %s\n' % fp)
            out.append('$endlist\n')
        out.append('$endfootprintlist\n}\n')
    if with_pcbnew:
        out.append('{ Pin List by Nets\n')
        out.append(_generic_list_of_nets(objs))
        out.append('}\n')
        out.append('#End\n')
    return ''.join(out)


def _generic_list_of_nets(objs: List[NetObject]) -> str:
    """writeGENERICListOfNets (netform.cpp:1768-1855): цепи с двумя и более
    выводами (без символов питания и без дубликатов)."""
    out: List[str] = []
    last = -1
    same = 0
    netcode_name = ''
    first_line = ''
    for o in objs:
        if o.net != last:
            same = 0
            cand = o.name_candidate
            net_name = cand.label if cand is not None else ''
            netcode_name = 'Net %d "' % o.net
            if net_name:
                if cand.type not in (NetType.PINLABEL, NetType.GLOBLABEL):
                    netcode_name += cand.sheet.human()
                netcode_name += net_name
            netcode_name += '"'
            netcode_name += ' "' + net_name + '"'
            last = o.net
        if o.type != NetType.PIN or o.flag != 0 or o.comp is None:
            continue
        ref = component_ref(o.comp, o.sheet)
        if ref[:1] == '#':
            continue
        same += 1
        if same == 1:
            first_line = ' %s %.4s\n' % (ref, o.pin_num)
        if same == 2:
            out.append(netcode_name + '\n')
            out.append(first_line)
        if same >= 2:
            out.append(' %s %.4s\n' % (ref, o.pin_num))
    return ''.join(out)


def save_netlist(text: str, path: str, crlf: bool = True) -> str:
    data = text.replace('\n', '\r\n') if crlf else text
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(data)
    return path


def netlist_path_for(schematic_path: str) -> str:
    """GenNetlist (netlist_control.cpp:464-530, :493): <имя схемы>.net."""
    return os.path.splitext(schematic_path)[0] + '.' + NETLIST_EXTENSION


# --- CLI ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys
    from .reader_lib import load_library

    p = argparse.ArgumentParser(prog='kicadgen.netlist',
                                description='EESchema bzr2986 netlist (Pcbnew format) from .sch + .lib')
    p.add_argument('sch')
    p.add_argument('libs', nargs='*', help='.lib files (default: <sch>-cache.lib or <sch>.lib)')
    p.add_argument('-o', '--out', help='output .net (default: <sch>.net)')
    p.add_argument('--date')
    p.add_argument('--lf', action='store_true', help='LF line endings instead of CRLF')
    p.add_argument('--print-nets', action='store_true')
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    sch, _w = S.load_schematic(args.sch)
    libs: List[M.Library] = []
    lib_files = list(args.libs)
    base = os.path.splitext(args.sch)[0]
    if not lib_files:
        for cand in (base + '-cache.lib', base + '.lib'):
            if os.path.exists(cand):
                lib_files.append(cand)
                break
    for f in lib_files:
        lib, _ = load_library(f)
        libs.append(lib)
    loader = file_sheet_loader(os.path.dirname(os.path.abspath(args.sch)))
    if args.print_nets:
        print(format_nets(build_nets(sch, libs, loader)))
    text = write_netlist_pcbnew(sch, libs, date=args.date, loader=loader)
    out = args.out or netlist_path_for(args.sch)
    save_netlist(text, out, crlf=not args.lf)
    print('wrote', out)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
