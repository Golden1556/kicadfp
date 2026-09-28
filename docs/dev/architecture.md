# kicadfp — архитектура и контракт API (этап 1: посадочные места)

Документ — обязательный контракт для всех, кто реализует модули пакета. Идентификаторы
кода — английские, строки документации, комментарии, сообщения CLI/GUI/проверок — русские.
Ядро (`kicadfp.*` кроме `kicadfp.gui` и PNG-экспорта) использует **только стандартную
библиотеку Python 3.10+**. Единицы: миллиметры и градусы; система координат KiCad
(ось Y вниз, поворот против часовой стрелки на экране = положительный угол в файле, как в KiCad).

Смежные спецификации (в этом каталоге): `format-writer.md` (порядок токенов writer'а KiCad),
`format-layout.md` (раскладка пробелов/переводов строк по версиям), `format-tokens.md`
(полный перечень токенов + инвентаризация по реальным файлам), `layers.md` (слои, цвета),
`legacy-mod.md` (старый формат .mod), `lab-generators.md` (геометрия генераторов).

## 1. Структура пакета

```
kicadfp/
  __init__.py        публичный API: load, loads, save, dumps, Footprint, Pad, Drill, Line, Rect,
                     Circle, Arc, Poly, Curve, Text, Model, Library, Issue, validate, __version__
  _version.py        __version__ = "0.1.0"
  sexpr.py           дерево S-выражений: Node, Sym, Str, parse(), dumps(), SexprSyntaxError,
                     форматирование чисел/строк, prettify (стиль KiCad 8/9), legacy layout (6/7),
                     equal(), diff()
  format_rules.py    ТАБЛИЦЫ на тип узла: порядок дочерних токенов, кавычки, формы булевых
                     значений по версии формата, FormatProfile
  layers.py          имена слоёв, групповые обозначения, пресеты, цвета, старая нумерация
  model.py           типизированные представления над узлами: Footprint, Pad, Drill, графика,
                     Text, Model (+ базовый класс View)
  geometry.py        вспомогательная геометрия: поворот точки, bbox, дуги (start/mid/end <->
                     центр/радиус/углы), безье — без зависимостей
  io.py              load/loads/save/dumps, атомарная запись, определение формата (sexpr /
                     legacy .mod / module KiCad 5), кодировка UTF-8, LF
  legacy.py          чтение PCBNEW-LibModule-V1 (.mod/.emp) -> список Footprint; convert()
  library.py         Library для каталогов .pretty
  validate.py        Issue, реестр правил, validate(fp, strict=False)
  generators/
    __init__.py      экспорт всех генераторов + реестр по имени для CLI (dip, pin_header, ...)
    _common.py       общие построители: тексты Reference/Value/${REFERENCE}, courtyard,
                     контуры, округление к сетке 0.01
    dip.py, pin_header.py, axial.py (resistor/diode), radial.py (capacitor), transistor.py,
    lab.py           lab_dip14(), lab_mlt(), lab_snp8() — корпуса лабораторной работы
  render.py          SVG (stdlib) + PNG (через PySide6, если доступен)
  cli.py             argparse: info, list, validate, set, pads, gen, fmt, convert, render, gui,
                     --version
  gui/               PySide6 (см. раздел 10)
```

## 2. Ключевой принцип: дерево + представления (round-trip без потерь)

Файл разбирается целиком в дерево `Node`. Все типизированные объекты (`Footprint`, `Pad`,
`Line`, …) — **представления (views)** над узлами дерева: они не хранят копий данных, каждый
getter читает из узла, каждый setter меняет узел (и только его). Поэтому:

* неизвестные узлы, неизвестные атрибуты известных узлов, порядок узлов сохраняются как есть;
* атомы хранят **исходный текст** числа (`"1.6"`, `"-180.000000"`), и он не меняется, пока
  значение не присвоено заново; при присваивании число форматируется по правилам KiCad;
* открытый и не изменённый файл после записи совпадает с исходным по дереву, а для файлов,
  записанных KiCad 8/9/10 (стиль prettify) — **байт в байт** (это проверяется тестами).

## 3. `kicadfp.sexpr`

```python
class Sym(str):   # голый токен: символ или число как записано ("thru_hole", "1.6", "*.Cu")
class Str(str):   # строка в кавычках; значение — уже без экранирования

class Node:
    __slots__ = ("name", "items", "line", "col")
    name: str                      # имя узла (первый токен, всегда символ)
    items: list[Node | Sym | Str]  # остальные элементы в исходном порядке (атомы и подузлы вперемешку)
    line: int; col: int            # позиция открывающей скобки в исходнике (1-based), 0 если создан в памяти

    # навигация
    def nodes(self, name: str | None = None) -> list[Node]          # дочерние узлы (все или по имени)
    def atoms(self) -> list[Sym | Str]                              # дочерние атомы по порядку
    def find(self, name: str) -> Node | None                        # первый дочерний узел с именем
    def find_all(self, name: str) -> list[Node]
    def index(self, child: Node) -> int                             # индекс в items (по идентичности), ValueError
    # атомарные значения
    def atom(self, i: int, default=None) -> Sym | Str | None        # i-й атом (только атомы, не узлы)
    def set_atom(self, i: int, value: Sym | Str) -> None            # заменить/дописать i-й атом
    def value(self, name: str, i: int = 0, default=None)            # атом i дочернего узла name (или default)
    def number(self, name: str, i: int = 0, default=None) -> float | None
    def numbers(self, name: str) -> list[float] | None              # все атомы-числа дочернего узла
    def has(self, name: str) -> bool
    def has_flag(self, flag: str) -> bool                           # есть ли голый Sym среди атомов
    # изменение
    def set(self, name: str, *values, order: list[str] | None = None) -> Node
        # найти дочерний узел name; если есть — заменить его атомы на values (подузлы сохранить);
        # если нет — создать Node(name, values) и вставить по таблице порядка `order`
        # (после последнего существующего дочернего узла, чьё имя стоит раньше в order; если
        # order не задан — в конец). values: float -> Sym(format_number), int -> Sym(str), bool -> Sym('yes'/'no'),
        # str -> Str, Sym/Str как есть.
    def remove(self, name: str) -> bool                             # удалить все дочерние узлы с именем
    def remove_child(self, child: Node) -> None
    def insert(self, child: Node, order: list[str] | None = None) -> None   # вставка по таблице порядка
    def append(self, child: Node) -> None
    def replace_child(self, old: Node, new: Node) -> None
    def set_flag(self, flag: str, on: bool, order: list[str] | None = None) -> None  # голый Sym-флаг
    def copy(self) -> Node                                          # глубокая копия (line/col = 0)
    # вывод
    def __repr__(self)
```

Числа в `values`: `float` округляется до 6 знаков (нанометры KiCad) и форматируется
функцией `format_number`. Значение `-0.0` записывается как `0`.

```python
class SexprSyntaxError(ValueError):
    line: int; col: int; msg: str      # str(e) == f"строка {line}, позиция {col}: {msg}"

def parse(text: str) -> Node            # ровно один корневой узел; ошибки: незакрытая/лишняя скобка,
                                         # незакрытая строка, пустой ввод, мусор после корня. Модель при ошибке не создаётся.
def parse_all(text: str) -> list[Node]  # несколько корневых узлов (на будущее — kicad_pcb, sym-lib-table)
def format_number(value: float) -> str  # правила KiCad: см. format-writer.md §8 (без экспоненты, без хвостовых нулей,
                                         # целые без точки, точность 1e-6, -0 -> 0)
def format_angle(value: float) -> str   # как format_number (KiCad: FormatAngle = %.10g; в отличие от KiCad малые углы
                                         # < 1e-4 пишутся без экспоненты — лексер KiCad принимает оба вида). Угол не нормализуется.
def quote(s: str) -> str                # экранирование по правилам KiCad (см. format-writer.md §9)
def unquote(s: str) -> str
def dumps(node: Node, *, style: str = "auto", version: int | None = None, compact: bool = False) -> str
    # style: "kicad8" — prettify KiCad 8/9/10 (табы), "kicad6" — раскладка KiCad 6/7 (2 пробела),
    # "kicad5" — если отличается от kicad6 (иначе синоним), "auto" — по version (см. format-layout.md §C):
    # version >= 20231014 -> kicad8; корень "module" или version < 20231014 -> kicad6.
    # Возвращает текст с LF и завершающим '\n'.
def to_compact(node: Node) -> str       # одна строка без переводов: вход для prettify
def prettify(compact_text: str, compact_save: bool = False) -> str   # порт KICAD_FORMAT::Prettify 1:1
def equal(a: Node, b: Node, *, numeric_tol: float = 1e-6, ignore_quotes: bool = True) -> bool
def diff(a: Node, b: Node, path: str = "") -> list[str]   # человекочитаемые расхождения (для тестов и fmt --check)
```

Сравнение `equal`: имена равны; элементы попарно; атомы: если оба разбираются как числа —
сравнить с допуском; иначе сравнить строки (при `ignore_quotes=True` `Sym("1") == Str("1")`).

## 4. `kicadfp.format_rules` — таблицы на тип узла

Реализует требование ТЗ 7.3: правила форматирования описываются таблицей на тип узла и
дополняются для новых типов без изменения ядра.

```python
@dataclass(frozen=True)
class FormatProfile:
    version: int                 # версия формата файла (0 для KiCad 5 "module")
    root: str                    # "footprint" | "module"
    style: str                   # "kicad8" | "kicad6"
    uuid_token: str              # "uuid" | "tstamp"
    text_as_property: bool       # Reference/Value как (property ...) — версия >= 20230620? (уточнить по format-tokens.md)
    stroke: bool                 # графика: (stroke (width) (type)) vs (width)
    bool_style: str              # "yesno" ((hide yes), (locked yes)) | "flag" (hide, locked)
    quoted_layers: bool          # (layers "F.Cu" ...) vs (layers F.Cu ...)
    quoted_generator: bool
    solder_paste_ratio_token: str  # "solder_paste_margin_ratio" | "solder_paste_ratio" (для footprint)
    arc_mid: bool                # fp_arc через start/mid/end (True) или center/end/angle (KiCad 5)
    model_offset_token: str      # "offset" | "at"

DEFAULT_VERSION = 20241229          # новые корпуса: KiCad 9
KICAD_FORMAT_VERSIONS = {6: 20211014, 7: 20221018, 8: 20240108, 9: 20241229}  # формат KiCad X.0
def kicad_format_version(target: int | str) -> int   # 8 / "8" / "kicad8" / 20240108 -> 20240108; иначе ValueError
    # KiCad не открывает файл версии новее своей: корпус формата KiCad 9 KiCad 8 не читает,
    # поэтому у генераторов и преобразования .mod формат можно выбрать (см. §8, §11, §13)
def profile_for(version: int | None, root: str = "footprint") -> FormatProfile

# Порядок дочерних токенов (для вставки новых узлов через Node.set/insert):
FOOTPRINT_ORDER: list[str]   # version, generator, generator_version, locked, placed, layer, tedit, uuid, tstamp, at, descr, tags,
                             # property, component_classes, path, sheetname, sheetfile, autoplace_cost90, autoplace_cost180,
                             # solder_mask_margin, solder_paste_margin, solder_paste_ratio, solder_paste_margin_ratio, clearance,
                             # zone_connect, thermal_width, thermal_gap, attr, private_layers, net_tie_pad_groups,
                             # fp_text, fp_text_box, fp_line, fp_rect, fp_circle, fp_arc, fp_poly, fp_curve, dimension, image,
                             # pad, zone, group, embedded_fonts, embedded_files, model
PAD_ORDER, TEXT_ORDER (fp_text/property), GRAPHIC_ORDER, MODEL_ORDER, EFFECTS_ORDER, FONT_ORDER, DRILL_ORDER
# Группы для "новые элементы добавляются в конец соответствующей группы":
GROUPS = {"text": {"fp_text","property"}, "graphic": {"fp_line",...}, "pad": {"pad"}, "zone": {"zone"}, "group": {"group"}, "model": {"model"}}
def insert_in_group(root: Node, child: Node) -> None   # после последнего узла своей группы; если группы нет — по FOOTPRINT_ORDER
KNOWN_FOOTPRINT_CHILDREN: frozenset[str]              # всё из FOOTPRINT_ORDER; остальное -> Footprint.unknown
```

Точные значения таблиц берутся из `format-writer.md`/`format-tokens.md`.

## 5. `kicadfp.layers`

```python
COPPER_LAYERS: list[str]        # F.Cu, In1.Cu..In30.Cu, B.Cu
TECH_LAYERS: list[str]          # B.Adhes, F.Adhes, B.Paste, F.Paste, B.SilkS, F.SilkS, B.Mask, F.Mask
USER_LAYERS: list[str]          # Dwgs.User, Cmts.User, Eco1.User, Eco2.User, Edge.Cuts, Margin, B.CrtYd, F.CrtYd, B.Fab, F.Fab, User.1..User.9 (и далее по layers.md)
ALL_LAYERS: list[str]           # в порядке KiCad
WILDCARDS: dict[str, list[str]] # "*.Cu": [...], "F&B.Cu": [...], "*.Mask": [...], "*.Paste", "*.SilkS", "*.Adhes", "*.CrtYd", "*.Fab"
PAD_LAYER_PRESETS: dict[str, list[str]]  # "thru_hole": ["*.Cu","*.Mask"], "smd": ["F.Cu","F.Paste","F.Mask"], "smd_back": [...],
                                          # "connect": ["F.Cu","F.Mask"], "np_thru_hole": ["*.Cu","*.Mask"]
COLORS: dict[str, str]          # "#RRGGBB" по теме KiCad Default (+ ключи "background", "grid", "pad_th", "hole", "npth", "selection")
DRAW_ORDER: list[str]           # снизу вверх
LEGACY_INDEX: dict[int, str]    # 0 -> "B.Cu", ..., 15 -> "F.Cu", 16.."B.Adhes" ... 28 -> "Edge.Cuts"
def is_valid_layer(name: str) -> bool            # каноническое имя или групповое обозначение
def expand(names: Iterable[str]) -> list[str]     # раскрыть групповые обозначения
def legacy_mask_to_layers(mask: int, pad_type: str) -> list[str]   # см. legacy-mod.md
def is_copper(name), is_front(name), is_back(name), flip_layer(name) -> str   # F.Cu <-> B.Cu и т.д.
```

## 6. `kicadfp.model` — представления

Общее для всех представлений:

```python
class View:
    node: Node                      # узел-носитель
    profile: FormatProfile          # от родительского Footprint (или DEFAULT при создании отдельно)
    def __eq__(self, other): return type(self) is type(other) and self.node is other.node
    def __hash__(self): return id(self.node)
    def copy(self) -> Self          # представление над копией узла
```

Все setters меняют только свой узел; при отсутствии дочернего токена он создаётся по таблице
порядка; присваивание `None` удаляет необязательный токен. Getter несуществующего
необязательного токена возвращает `None` (или значение по умолчанию KiCad там, где оно указано).

### 6.1 Footprint

```python
class Footprint(View):
    @classmethod
    def new(cls, name: str, *, version: int = DEFAULT_VERSION, generator: str = "kicadfp",
            layer: str = "F.Cu", descr: str = "", tags: str = "", attrs: Iterable[str] = ()) -> Footprint
        # создаёт корень (footprint "name" (version V) (generator "kicadfp") (generator_version "0.1") (layer "F.Cu") ...)
        # плюс обязательные тексты Reference "REF**" (F.SilkS, at 0 -? см. generators/_common) и Value name (F.Fab).
    # свойства корпуса
    name: str                       # первый атом корня (в KiCad 5 «module» — Sym, в 6+ — Str)
    version: int | None; generator: str | None; generator_version: str | None
    layer: str                      # "F.Cu" | "B.Cu"
    descr: str; tags: str           # "" если нет узла; присваивание "" удаляет узел
    attrs: set[str]                 # представление-множество: fp.attrs.add("smd"), .discard(), .clear(), in, iter; порядок при записи — как в KiCad (smd, through_hole, board_only, exclude_from_pos_files, exclude_from_bom, allow_missing_courtyard, dnp, allow_soldermask_bridges)
    properties: MutableMapping[str, str]   # все (property "K" "V" ...) — включая Reference/Value в 8+; значение = второй атом;
                                           # присваивание нового ключа создаёт (property "K" "V") (+ текстовые атрибуты, если профиль 8+: hide yes, layer F.Fab, at 0 0 0, effects font 1.27); del удаляет
    clearance: float | None; solder_mask_margin: float | None; solder_paste_margin: float | None
    solder_paste_ratio: float | None   # токен по профилю (solder_paste_margin_ratio / solder_paste_ratio); читать любой из них
    zone_connect: int | None
    uuid: str | None                # (uuid "…") или (tstamp …)
    locked: bool; placed: bool; tedit: str | None; path: str | None
    autoplace_cost90: int | None; autoplace_cost180: int | None
    private_layers: list[str]; net_tie_pad_groups: list[str]
    at: tuple[float, float, float] | None   # (x, y, angle) если есть узел at (в библиотеке обычно нет)
    # коллекции (каждый вызов — новый список представлений над текущими узлами; порядок = порядок в файле)
    pads: list[Pad]; graphics: list[Graphic]; texts: list[Text]; models: list[Model]
    zones: list[Node]; groups: list[Node]; unknown: list[Node]   # узлы, не входящие в KNOWN_FOOTPRINT_CHILDREN
    reference: Text | None; value: Text | None   # обязательные тексты; None, если отсутствуют (validate даёт error)
    # операции
    def pad(self, number: str | int) -> Pad            # первая площадка с таким номером; KeyError
    def pads_by_number(self, number) -> list[Pad]
    def add(self, item: Pad | Graphic | Text | Model | Node) -> item      # вставка в конец своей группы
    def remove(self, item: View | Node) -> None
    def new_pad(self, number, type="thru_hole", shape="circle", x=0.0, y=0.0, size=(1.6, 1.6), drill=None, layers=None, angle=0.0, **kw) -> Pad
    def new_line(self, start, end, layer="F.SilkS", width=0.12) -> Line   # аналогично new_rect/new_circle/new_arc/new_poly/new_text/new_model
    def bbox(self, layers: Iterable[str] | None = None, include_texts: bool = False) -> BBox   # BBox(x1,y1,x2,y2) namedtuple с width/height/center
    def move(self, dx: float, dy: float) -> None      # все элементы
    def rotate(self, angle: float, origin=(0.0, 0.0)) -> None
    def flip(self) -> None                            # зеркально по X (как KiCad «Flip»: y -> -y? см. ниже) + смена слоёв F<->B у всех элементов
    def renumber_pads(self, rule: str | Callable[[int, Pad], str] = "sequential", start: int = 1, order: str = "file") -> None
        # rule: "sequential" (1..n в порядке order: "file" | "xy" | "yx" | "circular"), "prefix:A" , или функция (index, pad) -> str
    def validate(self, strict: bool = False) -> list[Issue]
    def to_sexpr(self) -> Node                         # сам корневой узел (не копия)
    def dumps(self) -> str                             # sexpr.dumps(self.node, version=self.version)
    def upgrade(self, version: int = DEFAULT_VERSION) -> None   # необязательно: fp_text->property, width->stroke, tstamp->uuid, tedit удалить, hide->(hide yes) и т.п.
```

`flip()` — как «Flip» (перенос на другую сторону платы) в редакторе KiCad с направлением
LEFT_RIGHT: `FOOTPRINT::Flip(center, FLIP_DIRECTION::LEFT_RIGHT)` — x → −x относительно (0,0),
слои всех элементов F↔B, `layer` корпуса F.Cu↔B.Cu, углы площадок и текстов → −angle,
текстам ставится/снимается `justify mirror`. Реализация сверяется с `footprint.cpp`/`pad.cpp`
KiCad 9 (скачать при реализации), семантика фиксируется в docstring и тестах.

### 6.2 Pad и Drill

```python
class Drill(View):                 # узел (drill [oval] d1 [d2] [(offset x y)])
    diameter: float                # d1 (для овала — ширина по X)
    oval: bool
    width: float | None            # d2 для овала (высота); None если круглое
    offset_x: float; offset_y: float   # 0.0 если нет offset; присваивание 0/0 удаляет (offset)

PAD_TYPES = ("thru_hole", "smd", "connect", "np_thru_hole")
PAD_SHAPES = ("circle", "rect", "oval", "trapezoid", "roundrect", "custom")

class Pad(View):
    @classmethod
    def new(cls, number, type, shape, x, y, size, *, drill=None, layers=None, angle=0.0, profile=None, uuid=True, **kw) -> Pad
        # size: float или (sx, sy); drill: float | (w, h) | Drill-параметры; layers: None -> пресет по типу
    number: str                    # строка ("1", "A1", "" для монтажных отверстий)
    type: str; shape: str          # из PAD_TYPES / PAD_SHAPES; ValueError при недопустимом значении
    x: float; y: float; angle: float          # (at x y [angle]); угол 0 — токен не пишется (по профилю: в 8+ KiCad пишет угол только если != 0)
    size_x: float; size_y: float
    drill: Drill | None            # setter: None удаляет узел; float -> круглое; (w,h) -> овальное; Drill -> копия узла
    layers: list[str]              # setter заменяет список (кавычки по профилю)
    roundrect_rratio: float | None; chamfer_ratio: float | None; chamfer: list[str]
    rect_delta: tuple[float, float] | None
    net: tuple[int, str] | None; pinfunction: str | None; pintype: str | None
    property: str | None           # pad_prop_bga и т.п.
    clearance, solder_mask_margin, solder_paste_margin, solder_paste_ratio: float | None
    zone_connect: int | None; thermal_bridge_width: float | None; thermal_gap: float | None; die_length: float | None
    remove_unused_layers: bool | None; keep_end_layers: bool | None
    locked: bool; uuid: str | None
    primitives: list[Node]         # содержимое (primitives ...) — узлы gr_*; options: Node | None
    def move(self, dx, dy); def rotate(self, angle, origin=(0,0))  # поворот положения вокруг origin + angle
    def set_layers(self, preset: str) -> None     # ключ PAD_LAYER_PRESETS
    def is_tht(self) -> bool; def is_smd(self) -> bool
    def bbox(self) -> BBox                         # с учётом поворота (для прямоугольника — описанный)
```

### 6.3 Графика

```python
class Graphic(View):               # базовый: fp_line/fp_rect/fp_circle/fp_arc/fp_poly/fp_curve
    kind: str                      # "line" | "rect" | "circle" | "arc" | "poly" | "curve"
    layer: str
    width: float                   # (stroke (width w)) или (width w) по профилю; setter пишет по профилю узла (если в узле уже есть stroke — stroke)
    stroke_type: str | None        # solid/dash/... (None в KiCad 6)
    fill: bool                     # (fill yes|solid) -> True; (fill no|none) / отсутствует -> False; setter пишет по профилю
    locked: bool; uuid: str | None
    def move(self, dx, dy); def rotate(self, angle, origin=(0,0)); def mirror(self, axis: str = "x", origin=0.0)
    def bbox(self) -> BBox; def length(self) -> float     # периметр/длина
    def points(self) -> list[tuple[float, float]]         # характерные точки (для bbox/рендера)

class Line(Graphic):   start: (x,y); end: (x,y)   # свойства start_x/start_y/end_x/end_y тоже
class Rect(Graphic):   start; end
class Circle(Graphic): center; end; radius (вычисляемое; setter меняет end)
class Arc(Graphic):    start; mid; end            # для KiCad 5 (center/end/angle) — getters вычисляют start/mid/end, setters конвертируют узел в форму start/mid/end (только при изменении)
                       center; radius; start_angle; end_angle (вычисляемые, через geometry.arc_from_3points)
class Poly(Graphic):   points: list[(x,y)]        # setter переписывает (pts (xy ..)...); дуги внутри pts (arc ...) сохраняются, если не менять
class Curve(Graphic):  points: list[(x,y)]        # 4 точки Безье
```

### 6.4 Text

Представление над `fp_text` (6/7) **и** над `property` с текстовыми атрибутами (8+).
`Footprint.texts` включает: все `fp_text`, а также все `property`, у которых есть узел `at`
или `layer` или `effects` (в 8+ это Reference, Value, Footprint, Datasheet, Description и
пользовательские).

```python
class Text(View):
    kind: str            # "reference" | "value" | "user"
    name: str | None     # имя property ("Reference", "Value", "Datasheet", …) или None для fp_text
    text: str
    x, y, angle: float   # (at x y [angle] [unlocked])
    layer: str; hide: bool; unlocked: bool | None; knockout: bool
    font_size_x, font_size_y: float (default 1.0); thickness: float | None; bold: bool; italic: bool
    justify: list[str]   # напр. ["left"], ["right","top"], ["mirror"]; mirror: bool (наличие "mirror" в justify)
    uuid: str | None
    def move(dx, dy); def rotate(angle, origin=(0,0))
```

### 6.5 Model

```python
class Model(View):
    path: str; hide: bool; opacity: float | None
    offset: (x,y,z); scale: (x,y,z); rotate: (x,y,z)     # (offset (xyz …)) — мм; старая форма (at (xyz …)) — дюймы:
                                                          # на чтение значения ×25.4 (как парсер KiCad), на запись существующий
                                                          # узел at сохраняется (значение /25.4), новый узел — offset
```

## 7. `kicadfp.io`

```python
def load(path: str | PathLike) -> Footprint
    # UTF-8 (BOM допускается); определяет формат: начинается с "(footprint"/"(module" -> sexpr;
    # заголовок "PCBNEW-LibModule-V1" -> legacy: если в файле один модуль — вернуть его,
    # иначе LegacyLibraryError с подсказкой использовать legacy.read_library / convert.
def loads(text: str) -> Footprint
def save(fp: Footprint, path, *, strict: bool = False, style: str = "auto") -> None
    # strict: validate() -> если есть error -> ValidationError (ничего не пишется).
    # Атомарная запись: временный файл в том же каталоге (tempfile.NamedTemporaryFile(dir=..., delete=False)),
    # write UTF-8 без BOM, newline="\n", flush+fsync, os.replace().
def dumps(fp: Footprint, *, style: str = "auto") -> str
class ValidationError(Exception): issues: list[Issue]
```

## 8. `kicadfp.legacy`

```python
class LegacyFormatError(ValueError): line: int          # ошибка формата с номером строки
def read_library(path, *, compat: str = "kicad9", version=None) -> list[Footprint]   # PCBNEW-LibModule-V1 (.mod/.emp); единицы по заголовку (deci-mils / mm)
def loads_library(text, *, compat: str = "kicad9") -> list[Footprint]
def convert(mod_path, out_dir, *, compat: str = "kicad9", version=None) -> list[Path]   # каждый модуль -> <out_dir>/<name>.kicad_mod (создаёт каталог .pretty)
    # version: None -> DEFAULT_VERSION (KiCad 9); 6/7/8 или версия формата -> результат в формате этой версии
def is_legacy(text_head: str) -> bool
```

Точные правила — `legacy-mod.md`. Результат конвертации — footprint версии `DEFAULT_VERSION`,
generator "kicadfp", с новыми uuid. Параметр `compat`: ``"kicad9"`` — воспроизводить
поведение конвертера KiCad 9 полностью, включая его известные отступления D1–D5 из
`legacy-mod.md` §16.3 (в частности, смещение 3D-модели `Of` в дюймах записывается как мм);
``"fixed"`` — физически корректная конвертация (смещение ×25.4 и прочие исправления).
Отклонения перечисляются в docstring модуля.

## 9. `kicadfp.library`

```python
class Library:
    def __init__(self, path, create: bool = False)  # каталог .pretty; create=True создаёт; иначе FileNotFoundError если нет
    path: Path; name: str (без .pretty)
    @property names -> list[str]                    # отсортированные имена (файлы *.kicad_mod без расширения)
    def list(self) -> list[str]; __iter__, __len__, __contains__
    def get(self, name) -> Footprint                # загружает (кэш по имени); KeyError если нет
    def add(self, fp: Footprint, name: str | None = None, overwrite: bool = False) -> None
        # регистрирует в памяти под именем (fp.name := name); файл пишется в save_all()/save(name); FileExistsError если есть и не overwrite
    def save(self, name) -> Path; def save_all(self) -> list[Path]   # атомарно каждый файл
    def remove(self, name) -> None                  # удаляет файл немедленно (и из кэша)
    def rename(self, old, new) -> None              # переименовывает файл и поле name внутри (перезапись файла)
    def copy_to(self, other: "Library", name: str, new_name: str | None = None) -> Footprint   # копия узла, new_name -> имя; записывается в other сразу; исходный не меняется
    def path_of(self, name) -> Path
    def validate_all(self) -> dict[str, list[Issue]]
```

## 10. `kicadfp.validate`

```python
@dataclass
class Issue:
    level: str        # "error" | "warning"
    code: str         # напр. "PAD_DUP_NUMBER", "PAD_NO_LAYERS", "PAD_THT_NO_DRILL", "PAD_SMD_WITH_DRILL", "PAD_DRILL_GT_SIZE",
                      # "TEXT_MISSING_REFERENCE", "TEXT_MISSING_VALUE", "TEXT_BAD_LAYER", "GRAPHIC_BAD_LAYER", "PAD_BAD_LAYER",
                      # "ENUM_BAD_VALUE", "SIZE_NOT_POSITIVE", "COURTYARD_MISSING", "FOOTPRINT_BAD_LAYER", "SEXPR_..."
    message: str      # по-русски, с подстановкой номера/координат
    element: View | Node | None
    def __str__

RULES: list[Callable[[Footprint], Iterable[Issue]]]
def rule(code: str, level: str)  # декоратор-регистратор
def validate(fp: Footprint, strict: bool = False) -> list[Issue]   # strict не меняет список; используется save()
def has_errors(issues) -> bool
```

Правила по ТЗ 4.1.5 (уровни): дубли номеров — warning; площадка без слоёв — error; thru_hole
без drill — error; smd/connect с drill — error; drill > size (по любой оси, с учётом овала) —
error; нет Reference/Value — error; Reference/Value не на *.SilkS и не на *.Fab — warning;
графика/текст/площадка на несуществующем слое — error; недопустимые значения перечислений
(type, shape, layer корпуса, attr, fill/stroke type) — error; нулевые/отрицательные размеры
(size, drill, width < 0, font size ≤ 0) — error; нет области размещения (*.CrtYd) — warning
(не выдаётся, если у корпуса есть `attr allow_missing_courtyard`). Дополнительно (warning):
`PAD_NPTH_NUMBER` — у np_thru_hole есть номер (KiCad ожидает пустой), `LAYER_RESCUE` — слой
`Rescue` (так KiCad помечает неизвестные слои), `VERSION_TOO_NEW` — версия формата новее
известной программе (`> 20260206`), `PAD_THT_NO_COPPER` — сквозная площадка без медных слоёв.
Пустой номер у np_thru_hole — норма (не замечание); у thru_hole/smd пустой номер — warning
`PAD_EMPTY_NUMBER`.

## 11. `kicadfp.generators`

Сигнатуры и умолчания — `lab-generators.md` (он имеет приоритет над этим разделом). Все
генераторы возвращают `Footprint` (версия `DEFAULT_VERSION`, generator "kicadfp") с Reference
(F.SilkS), Value (F.Fab), контуром F.SilkS, контуром F.Fab, областью F.CrtYd (fp_rect, для
радиальных конденсаторов — fp_circle), `attr through_hole`, `descr`/`tags`. Стандартные
семейства (dip, pin_header, resistor, …) добавляют `${REFERENCE}` на F.Fab по правилам KLC;
лабораторные `lab_dip14`/`lab_mlt`/`lab_snp8` воспроизводят методичку и `${REFERENCE}` не содержат. Формат нового корпуса —
`DEFAULT_VERSION` (KiCad 9) или заданный контекстом `with generators.target_version(8): …` (KiCad 6–9 или версия
формата; `generators.current_version()` — действующая) / `from_json(kind, params, version=8)`: KiCad 8 файл формата
KiCad 9 не открывает. Реестр для CLI: `GENERATORS: dict[str, Callable]` с именами `dip`,
`pin_header`, `resistor`, `capacitor_radial`, `capacitor_axial`, `diode`, `transistor`,
`lab_dip14`, `lab_mlt`, `lab_snp8`; параметры CLI берутся из сигнатуры (inspect) и/или JSON.

## 12. `kicadfp.render`

```python
def render_svg(fp: Footprint, *, layers: Iterable[str] | None = None, scale: float = 10.0, grid: float | None = 1.0,
               background: bool = True, margin: float = 2.0) -> str      # SVG-документ; цвета layers.COLORS; порядок DRAW_ORDER
def save_svg(fp, path, **kw) -> None
def save_png(fp, path, *, width: int = 800, **kw) -> None      # через PySide6 (QSvgRenderer/QImage); ImportError -> RuntimeError с подсказкой
```

## 13. `kicadfp.cli`

`kicadfp <команда> …`, `kicadfp --version`. Команды и опции (все принимают путь к файлу или
каталогу .pretty; файлы не изменяются без `--write`/`-o`):

| команда | аргументы | вывод |
|---|---|---|
| `info PATH` | `--json` | имя, версия, генератор, слой, число площадок (по типам), список слоёв, габариты bbox, число графики/текстов/моделей |
| `list LIB` | `--json` | имена корпусов библиотеки |
| `validate PATH` | `--strict`, `--json` | список замечаний `LEVEL CODE: message`; код возврата 1 при ошибках; с `--strict` — также при предупреждениях |
| `set PATH SELECTOR VALUE` | `--write`, `-o OUT` | селектор: `footprint.descr`, `footprint.name`, `pad[3].size` (=size_x=size_y), `pad[3].size_x`, `pad[*].drill`, `pad[1].shape`, `pad[*].layers` ("F.Cu,F.Mask"), `text[reference].layer`, `graphic[0].width`, `model[0].path`; печатает, что изменено |
| `pads PATH` | `--json` | таблица: №, тип, форма, X, Y, угол, размер X/Y, отверстие, слои |
| `gen KIND [--param value …]` | `-o OUT`, `--params FILE.json`, `--name`, `--list`, `--kicad {6,7,8,9}` | параметры по сигнатуре генератора; без `-o` печатает в stdout; `--kicad 8` — формат KiCad 8 |
| `fmt PATH` | `--write`, `--check`, `--style {auto,kicad8,kicad6}` | канонический формат; `--check` возвращает 1 если файл отличается |
| `convert IN.mod` | `-o OUT.pretty`, `--compat`, `--kicad {6,7,8,9}` | конвертация старой библиотеки |
| `render PATH` | `-o OUT.svg/.png`, `--layers`, `--scale` | изображение |
| `gui [PATH]` | | запуск GUI (ImportError -> сообщение об установке `pip install kicadfp[gui]`) |

Ошибки разбора печатаются как `ошибка: <файл>: строка N, позиция M: …`, код возврата 2.

## 14. `kicadfp.gui` (PySide6)

```
gui/__init__.py     main(argv) -> int
gui/app.py          создание QApplication, стили
gui/document.py     FootprintDocument(QObject): fp: Footprint | None, path, undo_stack: QUndoStack(undoLimit=1000),
                    сигналы changed(), selectionChanged(object), modified(bool); методы open(path), save(), save_as(path),
                    apply(command) — все изменения модели только через QUndoCommand
gui/commands.py     SetValueCommand(doc, target_view, attr, new, old) с mergeable id для перетаскивания;
                    AddItemCommand / RemoveItemCommand (снимок узла + индекс), ReplaceNodeCommand (снимок до/после для сложных операций),
                    BatchCommand (групповые операции над площадками)
gui/mainwindow.py   QMainWindow: меню Файл (Открыть файл/библиотеку, Сохранить, Сохранить как, Экспорт SVG/PNG, Выход), Правка (Отменить, Повторить,
                    Удалить, Групповые операции над площадками…), Корпус (Проверить, Создать типовой корпус…, Свойства), Вид (сетка, слои, масштаб);
                    док-панели: дерево библиотек (LibraryTree), свойства корпуса (PropertiesPanel), таблица площадок (PadTable),
                    таблица графики и текстов (ItemsTable), центр — PreviewCanvas; статусная строка с координатами курсора
gui/libtree.py      QTreeView с моделью: корни = открытые каталоги .pretty (и одиночные файлы), дети = корпуса; двойной щелчок открывает
gui/props_panel.py  форма свойств Footprint (name, layer, descr, tags, attrs чекбоксы, clearance…, uuid readonly)
gui/pad_table.py    QTableView + QAbstractTableModel над fp.pads: столбцы номер, тип (combo), форма (combo), X, Y, поворот, размер X, размер Y, отверстие, слои;
                    редактирование ячеек -> команды; выбор строки -> выделение на канве
gui/items_table.py  графика и тексты: тип, слой, ширина/размер, координаты (сводно), текст; редактирование основных полей
gui/canvas.py       PreviewCanvas(QGraphicsView): сцена в мм (масштаб через transform, Y вниз), слои в цветах KiCad, сетка (1.25/1.0/0.5 мм, настраиваемая),
                    зум колесом, панорамирование средней кнопкой/пробелом, выбор элемента щелчком (подсветка), перетаскивание площадок/графики/текстов
                    мышью (одна команда на перетаскивание), контекстное меню; перерисовка по сигналу changed()
gui/dialogs.py      GenerateDialog (выбор генератора, параметры по сигнатуре), ValidateDialog (список замечаний, двойной щелчок -> выделение),
                    PadBatchDialog (перенумерация, сдвиг, поворот вокруг точки, смена слоёв, общий размер), PropertiesDialog для элемента
```

Требования: отмена/повтор ≥ 100 шагов (QUndoStack без ограничения или 1000); запрос
подтверждения при закрытии несохранённого; все изменения (таблицы, канва, диалоги) идут
через `FootprintDocument.apply()` и отражаются везде по сигналу `changed`. GUI-тесты
запускаются с `QT_QPA_PLATFORM=offscreen`.

## 15. Тесты (`tests/`)

* `conftest.py`: пути к фикстурам (`FIXTURES = tests/fixtures`), параметризация по всем
  `*.kicad_mod` (по каталогам версий), переменная окружения `KICADFP_EXTRA_FIXTURES`
  (дополнительные каталоги для расширенного прогона), `KICAD_CLI` (путь к kicad-cli для
  необязательных тестов), `KICAD8_CLI` (kicad-cli KiCad 8 для проверки открытия в KiCad 8).
* `test_sexpr.py` — токенизация, строки/экранирование, числа, ошибки с позицией, prettify.
* `test_roundtrip.py` — для каждого файла: `equal(parse(t), parse(dumps(parse(t))))`; для
  kicad8/kicad9/kicad10dev — байт-в-байт; для kicad6 — байт-в-байт там, где layout таблица
  это гарантирует (список исключений явно).
* `test_model_*.py` — по одному на тип узла: чтение всех атрибутов, запись каждого атрибута
  меняет только этот токен (diff по дереву ровно один), создание новых.
* `test_validate.py`, `test_generators.py`, `test_library.py`, `test_legacy.py`, `test_cli.py`,
  `test_render.py`, `test_gui_*.py` (offscreen), `test_acceptance.py` (сценарии приложения Г),
  `test_kicad_cli.py` (файлы, записанные kicadfp, открывает KiCad 8 и 9; помощники —
  `kicad_cli_tools.py`). Отчёт приёмки — `scripts/acceptance_report.py` →
  `docs/acceptance_report.md`.
* Покрытие ядра ≥ 80 % (`pytest --cov=kicadfp`).

## 16. Версионирование, упаковка

`pyproject.toml` (setuptools или hatchling — без сторонних зависимостей ядра), `[project.optional-dependencies] gui = ["PySide6>=6.5"]`,
`dev = ["pytest", "pytest-cov", "pytest-qt"]`; `[project.scripts] kicadfp = "kicadfp.cli:main"`,
`kicadfp-gui = "kicadfp.gui:main"`. Версия — `kicadfp/_version.py`, `kicadfp --version`.
Лицензия MIT. Python ≥ 3.10.
