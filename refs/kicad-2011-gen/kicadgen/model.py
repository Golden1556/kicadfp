"""Модель данных компонентной библиотеки EESchema (.lib + .dcm).

Все координаты — в милах (1/1000 дюйма), ось Y направлена ВВЕРХ
(eeschema/general.h:87-92: при отрисовке применяется матрица (1,0,0,-1)).
Точка (0,0) — якорь символа.

Каждый класс знает ограничения загрузчика C++ (см. validate()).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


class ValidationError(ValueError):
    pass


# --- Перечисления (буквы — ровно те, что пишет/читает lib_pin.cpp) ----------

class PinType(enum.Enum):
    """ElectricPinType (lib_pin.h:36-49) -> буква в файле (lib_pin.cpp:546-592)."""
    INPUT = 'I'
    OUTPUT = 'O'
    BIDI = 'B'
    TRISTATE = 'T'
    PASSIVE = 'P'
    UNSPECIFIED = 'U'
    POWER_IN = 'W'      # заглавная W
    POWER_OUT = 'w'     # строчная w — регистр важен!
    OPEN_COLLECTOR = 'C'
    OPEN_EMITTER = 'E'
    NC = 'N'

    @classmethod
    def from_letter(cls, ch: str) -> 'PinType':
        for t in cls:
            if t.value == ch:
                return t
        raise ValidationError('unknown pin type [%s]' % ch)


class PinOrient(enum.Enum):
    """DrawPinOrient (lib_pin.h:75-80). Буква задаёт направление линии вывода
    ОТ точки подключения (x,y) К корпусу: R -> +X, L -> -X, U -> +Y, D -> -Y."""
    RIGHT = 'R'
    LEFT = 'L'
    UP = 'U'
    DOWN = 'D'


class PinShape(enum.IntFlag):
    """DrawPinShape (lib_pin.h:61-69) — битовая маска."""
    NONE = 0
    INVERT = 1
    CLOCK = 2
    LOWLEVEL_IN = 4
    LOWLEVEL_OUT = 8
    CLOCK_FALL = 0x10
    NONLOGIC = 0x20


# Порядок букв при записи (lib_pin.cpp:624-641): I C L V F X.
_SHAPE_LETTERS: List[Tuple[PinShape, str]] = [
    (PinShape.INVERT, 'I'),
    (PinShape.CLOCK, 'C'),
    (PinShape.LOWLEVEL_IN, 'L'),
    (PinShape.LOWLEVEL_OUT, 'V'),
    (PinShape.CLOCK_FALL, 'F'),
    (PinShape.NONLOGIC, 'X'),
]


class Fill(enum.Enum):
    """FILL_T -> fill_tab (lib_draw_item.cpp:14)."""
    NONE = 'N'
    FOREGROUND = 'F'   # FILLED_SHAPE
    BACKGROUND = 'f'   # FILLED_WITH_BG_BODYCOLOR


class HJust(enum.Enum):
    LEFT = 'L'
    CENTER = 'C'
    RIGHT = 'R'


class VJust(enum.Enum):
    TOP = 'T'
    CENTER = 'C'
    BOTTOM = 'B'


# Имена обязательных полей (template_fieldnames.cpp:10-31)
FIELD_NAMES = ['Reference', 'Value', 'Footprint', 'Datasheet']
REFERENCE, VALUE, FOOTPRINT, DATASHEET = 0, 1, 2, 3
MANDATORY_FIELDS = 4

DEFAULT_SIZE_TEXT = 60      # include/base_struct.h:681
DEFAULT_PIN_LENGTH = 300    # lib_pin.cpp:167
DEFAULT_PIN_TEXT_SIZE = 50  # lib_pin.cpp:173-174
DEFAULT_PIN_NAME_OFFSET = 40  # class_libentry.cpp:167


def default_field_name(idx: int) -> str:
    if 0 <= idx < MANDATORY_FIELDS:
        return FIELD_NAMES[idx]
    return 'Field%d' % idx


def _no_ws(name: str, what: str) -> None:
    if name == '':
        raise ValidationError('%s must not be empty' % what)
    if any(ch.isspace() for ch in name):
        raise ValidationError('%s must not contain whitespace: %r' % (what, name))


# --- Поля -------------------------------------------------------------------

@dataclass
class Field:
    """Строка F<id> (lib_field.cpp:94-268)."""
    id: int
    text: str
    x: int = 0
    y: int = 0
    size: int = DEFAULT_SIZE_TEXT
    vertical: bool = False           # 'H' | 'V'
    visible: bool = True             # 'V' | 'I'
    hjust: HJust = HJust.CENTER
    vjust: VJust = VJust.CENTER
    italic: bool = False
    bold: bool = False
    name: Optional[str] = None       # только для id >= 4; None = имя по умолчанию

    def validate(self) -> None:
        if self.id < 0:
            raise ValidationError('field id must be >= 0')
        if self.size < 0:
            raise ValidationError('field size must be >= 0')
        if self.id < MANDATORY_FIELDS and self.name not in (None, default_field_name(self.id)):
            raise ValidationError('mandatory field %d cannot be renamed' % self.id)

    @property
    def effective_name(self) -> str:
        return self.name if self.name else default_field_name(self.id)


# --- Графические примитивы ----------------------------------------------------

@dataclass
class _Item:
    unit: int = 0        # 0 = общий для всех секций
    convert: int = 0     # 0 = общий для обоих стилей, 1 = обычный, 2 = DeMorgan

    def _validate_common(self) -> None:
        if self.unit < 0:
            raise ValidationError('unit must be >= 0')
        if self.convert < 0:
            raise ValidationError('convert must be >= 0')


@dataclass
class Arc(_Item):
    """A cx cy r t1 t2 unit convert width fill x1 y1 x2 y2 (lib_arc.cpp:88-157).
    Углы t1/t2 в десятых долях градуса. Концы x1,y1,x2,y2 можно не задавать —
    будут вычислены (как это делает KiCad для старых библиотек)."""
    cx: int = 0
    cy: int = 0
    radius: int = 0
    t1: int = 0
    t2: int = 0
    width: int = 0
    fill: Fill = Fill.NONE
    x1: Optional[int] = None
    y1: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None

    def endpoints(self) -> Tuple[int, int, int, int]:
        import math
        if None not in (self.x1, self.y1, self.x2, self.y2):
            return self.x1, self.y1, self.x2, self.y2  # type: ignore
        # lib_arc.cpp:140-153: RotatePoint(radius,0,-t) + centre
        def rot(t):
            a = math.radians(t / 10.0)
            return (self.cx + int(round(self.radius * math.cos(a))),
                    self.cy + int(round(self.radius * math.sin(a))))
        sx, sy = rot(self.t1)
        ex, ey = rot(self.t2)
        return sx, sy, ex, ey

    def validate(self) -> None:
        self._validate_common()
        if self.radius < 0:
            raise ValidationError('arc radius must be >= 0')


@dataclass
class Circle(_Item):
    """C cx cy r unit convert width fill (lib_circle.cpp:41-70)."""
    cx: int = 0
    cy: int = 0
    radius: int = 0
    width: int = 0
    fill: Fill = Fill.NONE

    def validate(self) -> None:
        self._validate_common()
        if self.radius < 0:
            raise ValidationError('circle radius must be >= 0')


@dataclass
class Rect(_Item):
    """S x1 y1 x2 y2 unit convert width fill (lib_rectangle.cpp:43-73)."""
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
    width: int = 0
    fill: Fill = Fill.NONE

    def validate(self) -> None:
        self._validate_common()


@dataclass
class Polyline(_Item):
    """P n unit convert width x1 y1 ... fill (lib_polyline.cpp:40-113)."""
    points: List[Tuple[int, int]] = field(default_factory=list)
    width: int = 0
    fill: Fill = Fill.NONE

    def validate(self) -> None:
        self._validate_common()
        if len(self.points) < 1:
            raise ValidationError('polyline needs at least one point (C++: count <= 0 is invalid)')


@dataclass
class Bezier(_Item):
    """B n unit convert width x1 y1 ... fill (lib_bezier.cpp:40-113)."""
    points: List[Tuple[int, int]] = field(default_factory=list)
    width: int = 0
    fill: Fill = Fill.NONE

    def validate(self) -> None:
        self._validate_common()
        if len(self.points) < 1:
            raise ValidationError('bezier needs at least one point')


@dataclass
class Text(_Item):
    """T orient x y size attr unit convert text Italic|Normal bold hjust vjust
    (lib_text.cpp:38-161)."""
    text: str = ''
    x: int = 0
    y: int = 0
    size: int = 50
    vertical: bool = False           # orient 0 | 900
    hidden: bool = False             # attr bit 0 (TEXT_NO_VISIBLE)
    italic: bool = False
    bold: bool = False
    hjust: HJust = HJust.CENTER
    vjust: VJust = VJust.CENTER

    def validate(self) -> None:
        self._validate_common()
        if self.text == '':
            raise ValidationError('text must not be empty (an empty %s token cannot be read back)')
        if '\n' in self.text or '\r' in self.text:
            raise ValidationError('text must be single-line')
        if '~' not in self.text and '"' not in self.text:
            # без кавычек: пробелы кодируются ~, табы и прочие пробельные — нет
            if any(ch.isspace() and ch != ' ' for ch in self.text):
                raise ValidationError('unquoted text may contain only plain spaces')
        else:
            if any(ch.isspace() and ch != ' ' for ch in self.text):
                raise ValidationError('quoted text may contain only plain spaces')


@dataclass
class Pin(_Item):
    """X name number x y length orient numSize nameSize unit convert etype [attrs]
    (lib_pin.cpp:541-773). (x,y) — точка подключения."""
    name: str = '~'
    number: str = '~'
    x: int = 0
    y: int = 0
    length: int = DEFAULT_PIN_LENGTH
    orient: PinOrient = PinOrient.RIGHT
    num_size: int = DEFAULT_PIN_TEXT_SIZE
    name_size: int = DEFAULT_PIN_TEXT_SIZE
    etype: PinType = PinType.INPUT
    shape: PinShape = PinShape.NONE
    visible: bool = True             # атрибут PINNOTDRAW -> буква N

    def validate(self) -> None:
        self._validate_common()
        _no_ws(self.name, 'pin name')
        _no_ws(self.number, 'pin number')
        if len(self.number.encode('utf-8')) > 4:
            raise ValidationError('pin number %r longer than 4 bytes (stored in a C long)' % self.number)
        if self.length < 0:
            raise ValidationError('pin length must be >= 0')
        if self.num_size < 0 or self.name_size < 0:
            raise ValidationError('pin text sizes must be >= 0')

    def body_end(self) -> Tuple[int, int]:
        """Конец линии вывода у корпуса (lib_pin.cpp:1466-1490)."""
        if self.orient is PinOrient.RIGHT:
            return self.x + self.length, self.y
        if self.orient is PinOrient.LEFT:
            return self.x - self.length, self.y
        if self.orient is PinOrient.UP:
            return self.x, self.y + self.length
        return self.x, self.y - self.length


DrawItem = Union[Arc, Circle, Rect, Polyline, Bezier, Text, Pin]

# Порядок типов при сортировке DRAW (include/base_struct.h:81-87)
_TYPE_ORDER = {Arc: 0, Circle: 1, Text: 2, Rect: 3, Polyline: 4, Bezier: 5, Pin: 6}
_LINE_LETTER = {Arc: 'A', Circle: 'C', Text: 'T', Rect: 'S', Polyline: 'P', Bezier: 'B', Pin: 'X'}


def packed_pin_number(number: str) -> int:
    """m_number: 4 байта номера, упакованные в long (little-endian, знаковый).
    Используется только для повторения порядка сортировки KiCad."""
    raw = number.encode('utf-8')[:4].ljust(4, b'\0')
    return int.from_bytes(raw, 'little', signed=True)


def _cmp_nocase(a: str, b: str) -> int:
    a2, b2 = a.casefold(), b.casefold()
    return (a2 > b2) - (a2 < b2)


def item_sort_key(item: DrawItem):
    """LIB_ITEM::operator< (lib_draw_item.cpp:90-108) + DoCompare каждого типа."""
    base = (item.convert, item.unit, _TYPE_ORDER[type(item)])
    if isinstance(item, Pin):
        return base + (packed_pin_number(item.number), item.name.casefold(), item.x, item.y)
    if isinstance(item, Arc):
        return base + (item.cx, item.cy, item.t1, item.t2)
    if isinstance(item, Circle):
        return base + (item.cx, item.cy, item.radius)
    if isinstance(item, Rect):
        return base + (item.x1, item.y1, item.x2, item.y2)
    if isinstance(item, (Polyline, Bezier)):
        return base + (len(item.points), tuple(item.points))
    if isinstance(item, Text):
        return base + (item.text.casefold(), item.x, item.y, item.size)
    return base


# --- Компонент и библиотека --------------------------------------------------

@dataclass
class Component:
    """Блок DEF ... ENDDEF (class_libentry.cpp:536-808)."""
    name: str
    reference: str = 'U'                     # префикс; '' -> пишется как ~ (невидимый)
    pin_name_offset: int = DEFAULT_PIN_NAME_OFFSET  # 0 = имена выводов снаружи
    show_pin_numbers: bool = True
    show_pin_names: bool = True
    unit_count: int = 1
    units_locked: bool = False               # 'L' | 'F'
    power: bool = False                      # 'P' | 'N'
    value_visible: bool = True               # префикс ~ у имени в DEF
    fields: List[Field] = field(default_factory=list)   # F0..Fn; F0/F1 генерируются при отсутствии
    aliases: List[str] = field(default_factory=list)
    fplist: List[str] = field(default_factory=list)
    items: List[DrawItem] = field(default_factory=list)
    # документация (.dcm)
    description: str = ''
    keywords: str = ''
    docfile: str = ''
    # документация алиасов: {alias: (description, keywords, docfile)}
    alias_docs: dict = field(default_factory=dict)

    # -- поля --
    def get_field(self, idx: int) -> Optional[Field]:
        for f in self.fields:
            if f.id == idx:
                return f
        return None

    def ensure_mandatory_fields(self) -> None:
        """Как конструктор LIB_COMPONENT: F0 (Reference) и F1 (Value) всегда есть."""
        if self.get_field(REFERENCE) is None:
            self.fields.insert(0, Field(REFERENCE, self.reference, visible=bool(self.reference)))
        if self.get_field(VALUE) is None:
            self.fields.insert(1, Field(VALUE, self.name, visible=self.value_visible))

    def pins(self, unit: int = 0, convert: int = 0) -> List[Pin]:
        """Фильтр как в LIB_COMPONENT::GetPins (class_libentry.cpp:489-513)."""
        out = []
        for it in self.items:
            if not isinstance(it, Pin):
                continue
            if unit and it.unit and it.unit != unit:
                continue
            if convert and it.convert and it.convert != convert:
                continue
            out.append(it)
        return out

    def validate(self) -> None:
        _no_ws(self.name, 'component name')
        if self.name.startswith('~'):
            raise ValidationError('component name must not start with ~ (it is the "value invisible" marker)')
        if self.reference:
            _no_ws(self.reference, 'reference prefix')
            if self.reference == '~':
                raise ValidationError("reference '~' means empty; use ''")
        if self.unit_count < 1:
            raise ValidationError('unit_count must be >= 1')
        if self.pin_name_offset < 0:
            raise ValidationError('pin_name_offset must be >= 0')
        for a in self.aliases:
            _no_ws(a, 'alias')
            if a.casefold() == self.name.casefold():
                raise ValidationError('alias %r duplicates component name' % a)
        ids = set()
        for f in self.fields:
            f.validate()
            if f.id in ids:
                raise ValidationError('duplicate field id %d' % f.id)
            ids.add(f.id)
        for it in self.items:
            it.validate()
            if it.unit > self.unit_count:
                raise ValidationError('%s: unit %d > unit_count %d' % (type(it).__name__, it.unit, self.unit_count))
            if it.convert > 2:
                raise ValidationError('%s: convert %d > 2' % (type(it).__name__, it.convert))
        for fp in self.fplist:
            if fp == '':
                raise ValidationError('empty footprint filter')
            if '\n' in fp or '\r' in fp:
                raise ValidationError('footprint filter must be single-line')
        for s, what in ((self.description, 'description'), (self.keywords, 'keywords'), (self.docfile, 'docfile')):
            if '\n' in s or '\r' in s:
                raise ValidationError('%s must be single-line' % what)
        # семантические проверки, которые KiCad не делает, но без которых символ бесполезен
        seen = {}
        for p in self.pins():
            key = (p.number, p.unit, p.convert)
            if key in seen:
                raise ValidationError('duplicate pin number %r in unit %d convert %d' % key)
            seen[key] = p

    def has_conversion(self) -> bool:
        return any(it.convert > 1 for it in self.items)


@dataclass
class Library:
    components: List[Component] = field(default_factory=list)

    def find(self, name: str) -> Optional[Component]:
        """Поиск без учёта регистра, как LIB_ALIAS_MAP (class_libentry.h:24-33)."""
        key = name.casefold()
        for c in self.components:
            if c.name.casefold() == key or any(a.casefold() == key for a in c.aliases):
                return c
        return None

    def validate(self) -> None:
        names = set()
        for c in self.components:
            c.validate()
            for n in [c.name] + list(c.aliases):
                k = n.casefold()
                if k in names:
                    raise ValidationError('duplicate component/alias name %r (case-insensitive)' % n)
                names.add(k)
