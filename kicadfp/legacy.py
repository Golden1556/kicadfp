"""Чтение старых библиотек посадочных мест KiCad ``PCBNEW-LibModule-V1`` (``.mod``/``.emp``).

Модуль реализует ``docs/dev/architecture.md`` §8 по спецификации ``docs/dev/legacy-mod.md``:
точная реплика того, как библиотеку читает и пересохраняет в ``.pretty`` KiCad 9
(``PCB_IO_KICAD_LEGACY`` → ``FootprintSave`` → writer S-выражений; тот же путь у
``kicad-cli fp upgrade LIB.mod``). Результат — корпуса :class:`~kicadfp.model.Footprint`
формата :data:`~kicadfp.format_rules.DEFAULT_VERSION` (KiCad 9), ``generator "kicadfp"``,
с новыми ``uuid``; они строятся через API :mod:`kicadfp.model`
(``Footprint.new`` + ``Pad.new``/``Line.new``/``Text.new``…), а порядок элементов — как у
writer'а KiCad (поля, ``cmp_drawings``, ``cmp_pads``).

Публичные функции: :func:`read_library`, :func:`loads_library`, :func:`convert`,
:func:`is_legacy`; ошибки формата — :class:`LegacyFormatError` (с номером строки);
замечания конвертации — :class:`LegacyIssue` (необязательный список ``issues``).

Как читается файл (всё — как в KiCad 9, ``pcb_io_kicad_legacy.cpp``)
--------------------------------------------------------------------

* Файл разбирается **побайтно по строкам** (строка заканчивается ``\\n``, ``\\r`` остаётся
  разделителем — CRLF и LF дают одинаковый результат), числа — семантикой C ``strtod``/
  ``strtol``/``strtoul``, поля — ``strtok`` с разделителями ``" \\t\\r\\n"`` (включая то,
  что ``strtok`` пишет NUL на место разделителя), ключевые слова — без учёта регистра.
* Единицы: по умолчанию 1 ед. = 0.1 mil = 2540 нм; строка ``Units mm`` в заголовке (до
  ``$INDEX``) — миллиметры. Каждое число — ``KiROUND(v × k)`` нм; углы — десятые доли
  градуса.
* Все вычисления геометрии — в целых нанометрах, как в KiCad: состояние корпуса (позиция и
  ориентация из ``Po``) моделируется буквально — элементы хранятся в абсолютных
  координатах, строка ``Po`` сдвигает и поворачивает уже прочитанные элементы
  (``FOOTPRINT::SetPosition``/``SetOrientation``), а при сохранении ориентация обнуляется
  (поворот всех элементов на ``−orient`` с округлением ``RotatePoint``). Поэтому совпадают и
  погрешности ±1 нм у корпусов с ориентацией, не кратной 90°, и углы элементов,
  записанных до строки ``Po``; координаты — 32-битные ``int`` (за пределами ±2147 мм
  значения ограничиваются ``KiROUND`` и «заворачиваются» при сдвигах/поворотах, как в
  KiCad).
* ``DA`` (дуга): центр ``C``, начальная точка ``S``, угол ``A`` (0.1°; положительный — по
  часовой стрелке на экране, ось Y вниз). Конец — ``S``, повёрнутая вокруг ``C`` на ``A``
  (``EDA_SHAPE::SetArcAngleAndEnd``), при ``A < 0`` начало и конец меняются местами;
  середина — ``GetArcMid`` по округлённым до нанометра концам. Это та же дуга, что даёт
  :func:`kicadfp.geometry.arc_three_points` с углом ``-A`` (соглашение о знаке
  :mod:`kicadfp.geometry` противоположное), но вычисленная в целых нанометрах, как KiCad
  (отличие от расчёта в ``float`` — до 1 нм).
* Слои: номер → имя :func:`kicadfp.layers.legacy_layer_to_name` (``cu_count = 16``), маска
  площадки → набор слоёв (``leg_mask2new``) с последующей коррекцией ``PAD::SetAttribute``
  (SMD/CONN: одна медь и нет отверстия; HOLE: номер стирается; смена типа обратно на STD
  «добавляет» всю медь) — как конечный автомат, т.е. с учётом порядка строк внутри
  ``$PAD``; запись ``(layers …)`` — :func:`kicadfp.layers.collapse` (медь ровно
  ``{F.Cu, B.Cu}`` → ``F&B.Cu``, как пишет KiCad 9.0.1 — ``kicad-cli``, по которому сверен
  модуль; ветка 9.0 начиная с 9.0.6 пишет у площадок ``*.Cu``, оба варианта KiCad читает).
* ``$PAD``: ``Sh`` (номер, форма ``C/R/O/T``, размер, ``rect_delta``, угол), ``Dr`` (круглое
  или ``O`` — овальное, смещение), ``At`` (``STD``/``SMD``/``CONN``/``HOLE``; прочее —
  ``thru_hole``), ``Po``, ``Le``, ``.SolderMask``, ``.SolderPaste``, ``.SolderPasteRatio``,
  ``.LocalClearance``, ``.ZoneConnection``, ``.ThermalWidth``, ``.ThermalGap``; ``Ne``
  отбрасывается. Площадка нулевого размера удаляется. У площадок не круглой формы пишется
  ``(thermal_bridge_angle 45)`` (угол спиц по умолчанию у площадки KiCad — 45°, а writer
  опускает только значение по умолчанию своей формы — 90° для не круглых; так пишет и
  ``kicad-cli`` 9.0.1).
* Тексты ``T0`` → поле Reference, ``T1`` → Value, ``T2+`` → ``fp_text user``; ``%R``/``%V`` →
  ``${REFERENCE}``/``${VALUE}``; старое надчёркивание ``~X~`` → ``~{X}``; размер в файле
  ``высота ширина`` пишется в ``(size …)`` в том же порядке и ограничивается диапазоном
  0.001…250 мм (``EDA_TEXT::SetTextSize``); толщина < 1 нм → 0 (токен не пишется).
* ``$SHAPE3D`` → ``(model …)``; ``Cd``/``Kw`` → ``descr``/``tags`` (текст до конца строки
  без разэкранирования); ``At SMD``/``VIRTUAL``/прочее → ``attr``; ``.SolderMask`` и т.п.
  корпуса; ``Op``, ``Sc``, ``AR``, ``Li``, время правки, цепи — отбрасываются.
* Имя модуля: остаток строки ``$MODULE`` без пробелов по краям; символы ``\\/:"<>|*?`` →
  ``%xx``; повтор имени → ``имя_v2``, ``имя_v3``…; корпуса возвращаются в порядке
  побайтовой сортировки имён (как ``FootprintEnumerate``).
* Любая ошибка формата — :class:`LegacyFormatError` (KiCad в этом случае не конвертирует
  библиотеку целиком; :func:`convert` тоже ничего не пишет). Ошибки — те же, что у KiCad:
  нет заголовка, пустой файл, нет ``$EndMODULE``/``$EndPAD``/``$EndSHAPE3D``, нет числа
  или число вне диапазона ``double`` (ERANGE), неизвестная форма площадки, ``DP`` без
  нужного числа строк ``Dl`` или с отрицательным числом точек (``vector::reserve``),
  ``Sc``/``Po`` модуля без поля uuid (``KIID(nullptr)``); в сообщении — номер строки
  (и позиция для чисел).

Режимы ``compat``
-----------------

``"kicad9"`` (по умолчанию) — результат совпадает с ``kicad-cli fp upgrade`` KiCad 9.0.1
(проверено на фикстурах и синтетических библиотеках: деревья равны с точностью до значений
``uuid`` и ``generator``/``generator_version``), включая известные отступления KiCad из
``legacy-mod.md`` §16.3: смещение 3D-модели ``Of`` (дюймы) записывается как миллиметры без
пересчёта (D1); полигоны ``DP`` — без заливки (D2); флаги locked/placed строки ``Po``
читаются с ошибкой KiCad (``data + 1``: статус ``~F`` даёт ``(locked yes)``, ``F~`` —
нет) (D4); коэффициент пасты корпуса ограничивается ``[-0.5, 0]``.

``"fixed"`` — физически корректная конвертация: смещение модели × 25.4 (D1); ``DP`` вне
``Edge.Cuts`` залиты, как их рисовал KiCad 2011 и как парсер KiCad 9 читает старые
``fp_poly`` без ``fill`` (D2); статус ``Po`` читается правильно: первая буква ``F`` —
``(locked yes)``, ``placed`` в библиотеке не пишется (D4).

Отклонения от KiCad 9 в обоих режимах (KiCad 9.0.1 в этих случаях даёт неверный или
нечитаемый файл, либо падает):

1. **Скрытый текст ``T2+``** (D3). KiCad 9 превращает его в поле ``PCB_FIELD(*text, -1)``, но
   writer 9.0.1 пишет такое поле без заголовка ``(property …)`` и с потерей текста и
   атрибутов — файл потом не читается (проверено ``kicad-cli``); вариант из
   ``legacy-mod.md`` (``(property "" …)``) не годится: два поля с пустым именем роняют
   ``kicad-cli``. kicadfp пишет скрытое поле ``(property "FieldN" "текст" … (hide yes))`` —
   как парсер KiCad 9 читает скрытый ``fp_text`` (``N`` — 5, 6, …); атрибуты текста
   сохраняются. Замечание ``legacy-hidden-text``.
2. **Корпус не на F.Cu** (``Po … слой ≠ 15``, D5). ``FootprintSave`` KiCad 9 вызывает
   ``Flip()`` без платы и ``kicad-cli`` 9.0.1 падает (проверено: Segmentation fault). kicadfp
   сохраняет корпус как есть: слой 0 → ``(layer "B.Cu")`` без зеркалирования элементов
   (замечание ``legacy-back-layer``), прочие слои → ``F.Cu`` (``legacy-module-layer``).
3. BOM UTF-8 в начале файла допускается (KiCad 9 такой файл не читает); некорректный UTF-8
   в строках читается как Latin-1 (замечание ``legacy-invalid-utf8``).
4. Пустое имя модуля (``$MODULE`` без имени) — :class:`LegacyFormatError` (у KiCad —
   файл ``.kicad_mod`` с пустым именем).
5. Где KiCad разыменовывает ``NULL`` и падает (``Dr … O`` без размеров, ``At`` без типа или
   маски): ``Dr … O`` без размеров — :class:`LegacyFormatError`, ``At`` без типа — ``STD``,
   без маски — маска 0. Чтение за концом строки (``Po`` без статуса, незакрытая кавычка
   текста) воспроизводится буквально: буфер строки, как у ``LINE_READER``, хранит хвосты
   прежних более длинных строк. Угол, коэффициент пасты и числа 3D-модели ``inf``/``nan``
   — :class:`LegacyFormatError` (KiCad пишет ``nan``/``inf`` в файл, который потом сам не
   читает); длина ``inf``/``nan`` — как ``KiROUND`` (предел int / 0).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Iterable

from . import layers as _L
from .format_rules import DEFAULT_VERSION
from .model import Arc, Circle, Drill, Footprint, Line, Model, Pad, Poly, Text
from .model import _sort_root_like_kicad
from .sexpr import Node, Sym, format_number

__all__ = [
    "LegacyFormatError", "LegacyIssue", "read_library", "loads_library", "convert",
    "is_legacy", "COMPAT_MODES", "LEGACY_HEADER",
]

#: Заголовок первой строки файла библиотеки (сравнивается без учёта регистра).
LEGACY_HEADER = "PCBNEW-LibModule-V1"
#: Допустимые значения параметра ``compat``.
COMPAT_MODES: tuple[str, ...] = ("kicad9", "fixed")

_BOM = b"\xef\xbb\xbf"
_DELIMS = b" \t\r\n"          # delims[] легаси-плагина
_NM_PER_DECIMIL = 25400.0 / 10  # IU_PER_MILS / 10 = 2540.0
_NM_PER_MM = 1e6              # IU_PER_MM
_INT_MAX = 2 ** 31 - 1
_INT_MIN = -2 ** 31
_MILS60 = 60 * 25400          # размер площадки по умолчанию (60 mil), нм
_MILS30 = 30 * 25400          # сверло по умолчанию (30 mil), нм
_DEG_TO_RAD = math.pi / 180.0  # EDA_ANGLE::DEGREES_TO_RADIANS
_SQRT1_2 = math.sqrt(0.5)     # M_SQRT1_2
_ILLEGAL_NAME_CHARS = '\\/:"<>|*?'
_ZONE_INHERITED = -1          # ZONE_CONNECTION::INHERITED
_OF_INCH_TO_MM = 25.4
_TEXT_MIN = 1000              # TEXT_MIN_SIZE_MM = 0.001 мм, нм
_TEXT_MAX = 250_000_000       # TEXT_MAX_SIZE_MM = 250 мм, нм
_LINE_BUF_SIZE = 5000         # начальный размер буфера LINE_READER

# Номера слоёв легаси-плагина
_LAYER_BACK = 0
_LAYER_FRONT = 15
_SILK_BACK = 20
_SILK_FRONT = 21
_LAST_NON_COPPER = 28

#: Все слои меди (``LSET::AllCuMask()``) и маска новой площадки (``PAD::PTHMask()``).
_ALL_CU: frozenset[str] = frozenset(_L.COPPER_LAYERS)
_PTH_MASK: frozenset[str] = _ALL_CU | {"F.Mask", "B.Mask"}

_PAD_SHAPES = {ord("C"): "circle", ord("R"): "rect", ord("O"): "oval", ord("T"): "trapezoid"}
_PAD_TYPES = {"PTH": "thru_hole", "SMD": "smd", "CONN": "connect", "NPTH": "np_thru_hole"}


# ---------------------------------------------------------------------------
# Ошибки и замечания
# ---------------------------------------------------------------------------

class LegacyFormatError(ValueError):
    """Ошибка формата ``PCBNEW-LibModule-V1``.

    ``line`` — номер строки (с 1), ``col`` — позиция в строке (с 1; 0 — не определена),
    ``msg`` — текст без позиции, ``path`` — путь к файлу (если читался файл). ``str(e)`` —
    ``"строка N[, позиция M]: …"`` (путь не включается — как у
    :class:`~kicadfp.sexpr.SexprSyntaxError`).
    """

    def __init__(self, msg: str, line: int, col: int = 0, path: str | None = None) -> None:
        self.msg = msg
        self.line = int(line)
        self.col = int(col)
        self.path = path
        where = f"строка {self.line}" + (f", позиция {self.col}" if self.col > 0 else "")
        super().__init__(f"{where}: {msg}")


@dataclass
class LegacyIssue:
    """Замечание конвертации (не ошибка): что KiCad теряет или что kicadfp сделал иначе.

    Поля совместимы с :class:`kicadfp.validate.Issue` (``level``, ``code``, ``message``,
    ``element``) и дополнены ``line`` (номер строки файла, 0 — нет) и ``module`` (имя
    корпуса). Коды: ``legacy-zero-size-pad``, ``legacy-duplicate-name``,
    ``legacy-name-escaped``, ``legacy-model-offset``, ``legacy-back-layer``,
    ``legacy-module-layer``, ``legacy-hidden-text``, ``legacy-unknown-pad-attr``,
    ``legacy-invalid-utf8``, ``legacy-locked-lost``.
    """

    code: str
    message: str
    line: int = 0
    module: str = ""
    level: str = "warning"
    element: object | None = None

    def __str__(self) -> str:
        where = f" (строка {self.line})" if self.line else ""
        return f"{self.level.upper()} {self.code}: {self.message}{where}"


# ---------------------------------------------------------------------------
# Примитивы C над строкой-буфером (bytearray с завершающим NUL)
# ---------------------------------------------------------------------------

def _cget(buf: bytearray, i: int) -> int:
    """Байт ``buf[i]``; за концом буфера — 0 (там, где C читал бы за концом строки,
    строка считается закончившейся)."""
    return buf[i] if 0 <= i < len(buf) else 0


def _cstr(buf: bytearray, i: int) -> bytes:
    """C-строка, начинающаяся с ``i`` (до первого NUL)."""
    if i >= len(buf):
        return b""
    end = buf.find(0, i)
    return bytes(buf[i:end if end >= 0 else len(buf)])


_FLOAT_RE = re.compile(
    rb"[ \t\n\v\f\r]*"
    rb"([+-]?(?:0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)(?:[pP][+-]?[0-9]+)?"
    rb"|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    rb"|[iI][nN][fF](?:[iI][nN][iI][tT][yY])?"
    rb"|[nN][aA][nN](?:\([0-9A-Za-z_]*\))?))")
_INT_RE = re.compile(rb"[ \t\n\v\f\r]*([+-]?)([0-9]+)")
_HEX_RE = re.compile(rb"[ \t\n\v\f\r]*([+-]?)(?:0[xX](?=[0-9a-fA-F]))?([0-9a-fA-F]+)")


def _strtod(buf: bytearray, i: int) -> tuple[float | None, int, bool]:
    """``strtod``: ``(значение, позиция после числа, ошибка ERANGE)``; нет числа —
    ``(None, i, False)``. ERANGE — переполнение или потеря значимости (результат 0 или
    денормализованный при ненулевой мантиссе), как у glibc."""
    if i >= len(buf):
        return None, i, False
    m = _FLOAT_RE.match(buf, i)
    if m is None:
        return None, i, False
    text = m.group(1).decode("ascii")
    body = text.lstrip("+-").lower()
    if body.startswith(("inf", "nan")):
        return float(text.split("(")[0]), m.end(), False
    if body.startswith("0x"):
        v = float.fromhex(text)
        mantissa = body[2:].split("p")[0]
    else:
        v = float(text)
        mantissa = body.split("e")[0]
    erange = math.isinf(v) or (
        abs(v) < 2.2250738585072014e-308 and any(c not in "0." for c in mantissa))
    return v, m.end(), erange


def _atof(buf: bytearray, i: int) -> float:
    """``atof``: число или 0.0."""
    v, _, _ = _strtod(buf, i)
    return 0.0 if v is None else v


def _strtol(buf: bytearray, i: int) -> tuple[int, int]:
    """``(int) strtol(…, 10)``: ``(значение, позиция)``; нет числа — ``(0, i)``."""
    if i >= len(buf):
        return 0, i
    m = _INT_RE.match(buf, i)
    if m is None:
        return 0, i
    v = int(m.group(2))
    if m.group(1) == b"-":
        v = -v
    v = max(-2 ** 63, min(2 ** 63 - 1, v))      # long (LP64)
    v &= 0xFFFFFFFF                             # приведение к int
    if v >= 2 ** 31:
        v -= 2 ** 32
    return v, m.end()


def _strtoul16(buf: bytearray, i: int) -> tuple[int, int]:
    """``(uint32_t) strtoul(…, 16)``: ``(значение, позиция)``; нет числа — ``(0, i)``."""
    if i >= len(buf):
        return 0, i
    m = _HEX_RE.match(buf, i)
    if m is None:
        return 0, i
    v = int(m.group(2), 16)
    if v > 2 ** 64 - 1:
        v = 2 ** 64 - 1
    elif m.group(1) == b"-":
        v = (-v) % 2 ** 64
    return v & 0xFFFFFFFF, m.end()


def _strtok(buf: bytearray, i: int | None) -> tuple[int | None, int | None]:
    """``strtok_r`` с разделителями ``" \\t\\r\\n"``: ``(начало токена, saveptr)``.

    Как в glibc, разделитель после токена заменяется NUL, ``saveptr`` указывает за ним
    (или на завершающий NUL). Нет токена — ``(None, позиция NUL)``. ``i=None`` или за
    концом буфера — ``(None, None)``."""
    if i is None or i >= len(buf):
        return None, None
    n = len(buf)
    while i < n and buf[i] != 0 and buf[i] in _DELIMS:
        i += 1
    if i >= n or buf[i] == 0:
        return None, i
    j = i
    while j < n and buf[j] != 0 and buf[j] not in _DELIMS:
        j += 1
    if j >= n or buf[j] == 0:
        return i, j
    buf[j] = 0
    return i, j + 1


def _read_delimited(buf: bytearray, i: int, size: int | None = None) -> tuple[bytes, int]:
    """``ReadDelimitedText``: текст между первой парой кавычек (``\\"`` → ``"``, ``\\\\`` →
    ``\\``, прочие ``\\X`` — как есть) и число прочитанных байт (позиция после закрывающей
    кавычки минус ``i``). ``size`` — размер буфера char-версии (не больше ``size - 1``
    байт результата), ``None`` — версия для ``wxString`` без ограничения."""
    out = bytearray()
    inside = False
    p = i
    limit = None if size is None else size - 1
    while True:
        cc = _cget(buf, p)
        p += 1
        if cc == 0:
            break
        if limit is not None and len(out) >= limit:
            break
        if cc == 0x22:  # "
            if inside:
                break
            inside = True
        elif inside:
            if cc == 0x5C:  # \
                cc = _cget(buf, p)
                p += 1
                if cc == 0:
                    break
                if cc not in (0x22, 0x5C):
                    out.append(0x5C)
                if limit is None or len(out) < limit:
                    out.append(cc)
            else:
                out.append(cc)
    return bytes(out), p - i


def _strpurge(data: bytes) -> bytes:
    """``StrPurge``: убрать пробельные символы C по краям (и всё после NUL)."""
    end = data.find(b"\0")
    if end >= 0:
        data = data[:end]
    return data.strip(b" \t\n\r\f\v")


def _testline(buf: bytearray, key: bytes) -> bool:
    """``TESTLINE``: строка начинается с ``key`` (без учёта регистра), за ним — пробел,
    таб, CR, LF или конец строки (NUL внутри ``key`` не совпадёт — строка короче)."""
    k = len(key)
    if bytes(buf[:k]).lower() != key.lower():
        return False
    return _cget(buf, k) in b" \t\r\n\0"


def _testsubstr(buf: bytearray, key: bytes) -> bool:
    """``TESTSUBSTR``: только префикс без учёта регистра."""
    return bytes(buf[:len(key)]).lower() == key.lower()


def _i32(v: int) -> int:
    """Целое ``int`` C++ (32 бита, переполнение по модулю 2³², как в KiCad на практике):
    координаты за пределами ±2147 мм «заворачиваются» так же, как у KiCad."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _kiround(v: float) -> int:
    """``KiROUND`` (половина от нуля; переполнение int — как KiCad)."""
    if math.isnan(v):
        return 0          # int(long long(nan)) на x86-64 — 0x8000…, после усечения до int — 0
    r = v - 0.5 if v < 0 else v + 0.5
    if r > _INT_MAX:
        return _INT_MAX - 1
    if r < _INT_MIN:
        return _INT_MIN + 1
    return int(r)


# ---------------------------------------------------------------------------
# Углы и повороты — как EDA_ANGLE / RotatePoint KiCad
# ---------------------------------------------------------------------------

def _normalize(a: float) -> float:
    """``EDA_ANGLE::Normalize``: [0, 360)."""
    while a < -0.0:
        a += 360.0
    while a >= 360.0:
        a -= 360.0
    return a


def _normalize180(a: float) -> float:
    """``EDA_ANGLE::Normalize180``: (-180, 180]."""
    while a <= -180.0:
        a += 360.0
    while a > 180.0:
        a -= 360.0
    return a


def _normalize720(a: float) -> float:
    """``EDA_ANGLE::Normalize720``: [-360, 360)."""
    while a < -360.0:
        a += 360.0
    while a >= 360.0:
        a -= 360.0
    return a


def _sin_cos(a: float) -> tuple[float, float]:
    """``EDA_ANGLE::Sin``/``Cos`` (точные значения на кратных 45°)."""
    t = _normalize(a)
    if t in (0.0, 180.0):
        s = 0.0
    elif t in (45.0, 135.0):
        s = _SQRT1_2
    elif t in (225.0, 315.0):
        s = -_SQRT1_2
    elif t == 90.0:
        s = 1.0
    elif t == 270.0:
        s = -1.0
    else:
        s = math.sin(t * _DEG_TO_RAD)
    if t == 0.0:
        c = 1.0
    elif t == 180.0:
        c = -1.0
    elif t in (90.0, 270.0):
        c = 0.0
    elif t in (45.0, 315.0):
        c = _SQRT1_2
    elif t in (135.0, 225.0):
        c = -_SQRT1_2
    else:
        c = math.cos(t * _DEG_TO_RAD)
    return s, c


def _rotate(p: tuple[int, int], c: tuple[int, int], angle: float) -> tuple[int, int]:
    """``RotatePoint(p, c, angle)`` в целых нанометрах (положительный угол — против часовой
    стрелки на экране; 0/90/180/270° — точные перестановки, иначе ``KiROUND``)."""
    ox, oy = _i32(p[0] - c[0]), _i32(p[1] - c[1])
    a = _normalize(angle)
    if a == 0.0:
        rx, ry = ox, oy
    elif a == 90.0:
        rx, ry = oy, _i32(-ox)
    elif a == 180.0:
        rx, ry = _i32(-ox), _i32(-oy)
    elif a == 270.0:
        rx, ry = _i32(-oy), ox
    else:
        s, co = _sin_cos(a)
        rx = _kiround(oy * s + ox * co)
        ry = _kiround(oy * co - ox * s)
    return (_i32(rx + c[0]), _i32(ry + c[1]))


def _vector_angle(dx: float, dy: float) -> float:
    """``EDA_ANGLE(VECTOR2D)`` — угол вектора в градусах со спецслучаями осей и диагоналей."""
    if dx == 0.0 and dy == 0.0:
        return 0.0
    if dy == 0.0:
        return 0.0 if dx >= 0 else -180.0
    if dx == 0.0:
        return 90.0 if dy >= 0.0 else -90.0
    if dx == dy:
        return 45.0 if dx >= 0.0 else -180.0 + 45.0
    if dx == -dy:
        return -45.0 if dx >= 0.0 else 180.0 - 45.0
    return math.atan2(dy, dx) / _DEG_TO_RAD


def _arc_end(center: tuple[int, int], start: tuple[int, int],
             angle: float) -> tuple[tuple[int, int], tuple[int, int]]:
    """``EDA_SHAPE::SetArcAngleAndEnd(angle, true)``: ``(start, end)`` дуги ``DA``."""
    end = _rotate(start, center, -_normalize720(angle))
    if angle < 0.0:
        return end, start
    return start, end


def _arc_mid(start: tuple[int, int], end: tuple[int, int],
             center: tuple[int, int]) -> tuple[int, int]:
    """``EDA_SHAPE::GetArcMid`` (через ``CalcArcAngles``)."""
    sa = _vector_angle(float(_i32(start[0] - center[0])), float(_i32(start[1] - center[1])))
    ea = _vector_angle(float(_i32(end[0] - center[0])), float(_i32(end[1] - center[1])))
    if ea == sa:
        ea = sa + 360.0
    while ea < sa:
        ea += 360.0
    return _rotate(start, center, -(ea - sa) / 2.0)


# ---------------------------------------------------------------------------
# Промежуточные объекты (как объекты KiCad в памяти, координаты — абсолютные нм)
# ---------------------------------------------------------------------------

Pt = tuple[int, int]


@dataclass
class _Text:
    kind: str                         # reference | value | user (или имя служебного поля)
    pos: Pt = (0, 0)
    text: str = ""
    size: Pt = (1270000, 1270000)     # (ширина, высота), DEFAULT_SIZE_TEXT
    thickness: int = 150000           # DEFAULT_TEXT_WIDTH
    angle: float = 0.0
    layer: str = "F.SilkS"
    mirror: bool = False
    visible: bool = True
    italic: bool = False
    hjust: str | None = None
    vjust: str | None = None
    line: int = 0

    def move(self, d: Pt) -> None:
        self.pos = (_i32(self.pos[0] + d[0]), _i32(self.pos[1] + d[1]))

    def rotate(self, c: Pt, a: float) -> None:
        self.pos = _rotate(self.pos, c, a)
        self.angle = _normalize(self.angle + a)


@dataclass
class _Shape:
    kind: str                         # line | circle | arc | poly
    start: Pt = (0, 0)
    end: Pt = (0, 0)
    center: Pt = (0, 0)
    pts: list[Pt] = field(default_factory=list)
    width: int = 0
    layer: str = "F.SilkS"

    def move(self, d: Pt) -> None:
        def mv(p: Pt) -> Pt:
            return (_i32(p[0] + d[0]), _i32(p[1] + d[1]))
        self.start, self.end, self.center = mv(self.start), mv(self.end), mv(self.center)
        self.pts = [mv(p) for p in self.pts]

    def rotate(self, c: Pt, a: float) -> None:
        self.start = _rotate(self.start, c, a)
        self.end = _rotate(self.end, c, a)
        self.center = _rotate(self.center, c, a)
        self.pts = [_rotate(p, c, a) for p in self.pts]


@dataclass
class _Pad:
    pos: Pt
    number: str = ""
    shape: str = "circle"
    size: Pt = (_MILS60, _MILS60)
    delta: Pt = (0, 0)
    angle: float = 0.0
    drill: Pt = (_MILS30, _MILS30)
    oblong: bool = False
    offset: Pt = (0, 0)
    layers: frozenset[str] = _PTH_MASK
    attrib: str = "PTH"
    die_length: int = 0
    mask_margin: int | None = None
    paste_margin: int | None = None
    paste_ratio: float | None = None
    clearance: int | None = None
    zone_connect: int = _ZONE_INHERITED
    thermal_width: int | None = None
    thermal_gap: int | None = None
    line: int = 0

    def move(self, d: Pt) -> None:
        self.pos = (_i32(self.pos[0] + d[0]), _i32(self.pos[1] + d[1]))

    def rotate(self, c: Pt, a: float) -> None:
        self.pos = _rotate(self.pos, c, a)
        self.angle = _normalize(self.angle + a)

    def set_attribute(self, attrib: str) -> None:
        """``PAD::SetAttribute`` (только при смене типа)."""
        if attrib == self.attrib:
            return
        self.attrib = attrib
        if attrib == "PTH":
            self.layers = self.layers | _ALL_CU
        elif attrib in ("SMD", "CONN"):
            copper = [n for n in _L.COPPER_LAYERS if n in self.layers]
            if len(copper) > 1:
                keep = "B.Cu" if "B.Cu" in copper else copper[0]
                self.layers = (self.layers - _ALL_CU) | {keep}
            self.drill = (0, 0)
        elif attrib == "NPTH":
            self.number = ""


@dataclass
class _Model3D:
    path: str = ""
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    line: int = 0


@dataclass
class _Module:
    name: str
    line: int
    pos: Pt = (0, 0)
    orient: float = 0.0
    layer_num: int = _LAYER_FRONT
    locked: bool = False
    placed: bool = False
    status_locked: bool = False       # правильно прочитанный статус (режим fixed)
    descr: str = ""
    tags: str = ""
    attrs: list[str] = field(default_factory=list)
    mask_margin: int | None = None
    paste_margin: int | None = None
    paste_ratio: float | None = None
    clearance: int | None = None
    zone_connect: int = _ZONE_INHERITED
    reference: _Text = field(default_factory=lambda: _Text("reference", layer="F.SilkS"))
    value: _Text = field(default_factory=lambda: _Text("value", layer="F.Fab"))
    # служебные поля Datasheet/Description: всегда в якоре, но их угол поворачивается вместе
    # с корпусом (при нескольких строках Po остаётся «шум» вида 5.3e-15, как у KiCad)
    service: list[_Text] = field(default_factory=lambda: [
        _Text("Datasheet", layer="F.Fab", visible=False),
        _Text("Description", layer="F.Fab", visible=False)])
    fields: list[_Text] = field(default_factory=list)       # скрытые T2+ (поля)
    drawings: list[_Shape | _Text] = field(default_factory=list)
    pads: list[_Pad] = field(default_factory=list)
    models: list[_Model3D] = field(default_factory=list)

    def children(self) -> Iterable[_Text | _Shape | _Pad]:
        yield self.reference
        yield self.value
        yield from self.service
        yield from self.fields
        yield from self.pads
        yield from self.drawings

    def set_position(self, pos: Pt) -> None:
        """``FOOTPRINT::SetPosition``: сдвинуть все элементы."""
        d = (_i32(pos[0] - self.pos[0]), _i32(pos[1] - self.pos[1]))
        self.pos = pos
        for c in self.children():
            c.move(d)

    def set_orientation(self, angle: float) -> None:
        """``FOOTPRINT::SetOrientation``: повернуть все элементы на изменение угла."""
        change = angle - self.orient
        self.orient = _normalize180(angle)
        for c in self.children():
            c.rotate(self.pos, change)

    def rel(self, p: Pt) -> Pt:
        """Координаты относительно якоря (как writer при нулевой ориентации)."""
        return (_i32(p[0] - self.pos[0]), _i32(p[1] - self.pos[1]))


# ---------------------------------------------------------------------------
# Разбор
# ---------------------------------------------------------------------------

class _Reader:
    """Построчный разбор библиотеки (``LP_CACHE`` + ``loadFOOTPRINT`` KiCad 9)."""

    def __init__(self, data: bytes, compat: str, issues: list[LegacyIssue] | None,
                 path: str | None) -> None:
        if data.startswith(_BOM):
            data = data[len(_BOM):]
        parts = data.split(b"\n")
        #: строки файла с завершающим \n (последняя — без него, если его нет в файле)
        self.lines: list[bytes] = [p + b"\n" for p in parts[:-1]]
        if parts[-1]:
            self.lines.append(parts[-1])
        self.idx = -1                 # индекс текущей строки
        #: буфер строки LINE_READER: новая строка пишется в начало и завершается NUL,
        #: за ним остаются байты прежних (более длинных) строк — их KiCad читает, когда
        #: разбор выходит за конец строки (незакрытая кавычка, Po без статуса)
        self.buf = bytearray(_LINE_BUF_SIZE)
        self.compat = compat
        self.issues = issues
        self.path = path
        self.scale = _NM_PER_DECIMIL
        self.module: _Module | None = None

    # --- служебное -----------------------------------------------------------------------------
    @property
    def lineno(self) -> int:
        return self.idx + 1

    def readline(self) -> bytearray | None:
        """Следующая строка (``FILE_LINE_READER::ReadLine``) или ``None`` в конце файла."""
        self.idx += 1
        if self.idx >= len(self.lines):
            self.idx = len(self.lines)
            self.buf[0] = 0
            return None
        raw = self.lines[self.idx]
        n = len(raw)
        if n + 1 > len(self.buf):
            self.buf.extend(bytes(n + 1 - len(self.buf)))
        self.buf[:n] = raw
        self.buf[n] = 0
        return self.buf

    def error(self, msg: str, col: int = 0, line: int | None = None) -> LegacyFormatError:
        return LegacyFormatError(msg, self.lineno if line is None else line, col, self.path)

    def warn(self, code: str, message: str, line: int = 0) -> None:
        if self.issues is not None:
            name = self.module.name if self.module is not None else ""
            self.issues.append(LegacyIssue(code, message, line or self.lineno, name))

    def decode(self, raw: bytes, what: str) -> str:
        """UTF-8 (``From_UTF8``); некорректные байты — Latin-1 и замечание."""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            self.warn("legacy-invalid-utf8",
                      f"{what}: некорректная последовательность UTF-8, прочитано как Latin-1")
            return raw.decode("latin-1")

    # --- числа -----------------------------------------------------------------------------------
    def _float(self, buf: bytearray, i: int) -> tuple[float, int]:
        """``strtod`` с проверками ``biuParse``/``degParse``: нет числа или ERANGE —
        ошибка; литералы ``inf``/``nan`` (ERANGE не дают) пропускаются."""
        v, end, erange = _strtod(buf, i)
        if v is None:
            raise self.error("нет числа с плавающей точкой", col=i + 1)
        if erange:
            raise self.error("некорректное число с плавающей точкой (вне диапазона)",
                             col=i + 1)
        return v, end

    def biu(self, buf: bytearray, i: int) -> tuple[int, int]:
        """``biuParse``: длина в нанометрах (``KiROUND``: ±inf — предел int, nan — 0)."""
        v, end = self._float(buf, i)
        return _kiround(v * self.scale), end

    def deg(self, buf: bytearray, i: int) -> tuple[float, int]:
        """``degParse``: угол в градусах (в файле — десятые доли). Бесконечный угол или
        nan — ошибка (KiCad записал бы файл с ``nan``, который сам не читает)."""
        v, end = self._float(buf, i)
        if not math.isfinite(v):
            raise self.error("некорректный угол (inf/nan)", col=i + 1)
        return v / 10.0, end

    # --- файл --------------------------------------------------------------------------------------
    def load(self) -> list[tuple[str, _Module]]:
        """``LP_CACHE::Load``: заголовок, индекс, модули. Возвращает пары (имя, модуль) в
        порядке файла (имена уже уникальны)."""
        line = self.readline()
        if line is None:
            raise self.error("файл пуст", line=1)
        if not _testline(line, LEGACY_HEADER.encode()):
            raise self.error(f"не библиотека старого формата: первая строка должна "
                             f"начинаться с «{LEGACY_HEADER}»", line=1)
        # ReadAndVerifyHeader
        while (line := self.readline()) is not None:
            if _testline(line, b"Units"):
                tok, _ = _strtok(line, 5)
                if tok is not None and _cstr(line, tok) == b"mm":
                    self.scale = _NM_PER_MM
            elif _testline(line, b"$INDEX"):
                break
        # SkipIndex
        exit_ = False
        line = self.buf
        while True:
            if _testline(line, b"$INDEX"):
                exit_ = False
                while (line := self.readline()) is not None:
                    if _testline(line, b"$EndINDEX"):
                        exit_ = True
                        break
            elif exit_:
                break
            line = self.readline()
            if line is None:
                break
        # LoadModules
        result: dict[str, _Module] = {}
        order: list[str] = []
        line = self.buf
        while line is not None:
            if _testline(line, b"$MODULE"):
                raw = _strpurge(_cstr(line, 7))
                start = self.lineno
                name = self.decode(raw, "имя модуля")
                escaped = "".join(f"%{ord(ch):02x}" if ch in _ILLEGAL_NAME_CHARS else ch
                                  for ch in name)
                if not escaped:
                    raise self.error("пустое имя модуля в строке $MODULE")
                mod = _Module(escaped, start)
                self.module = mod
                if escaped != name:
                    self.warn("legacy-name-escaped",
                              f"имя «{name}» содержит недопустимые символы, заменено на "
                              f"«{escaped}»", start)
                self.load_module(mod)
                final = escaped
                if final in result:
                    version = 2
                    while f"{escaped}_v{version}" in result:
                        version += 1
                    final = f"{escaped}_v{version}"
                    mod.name = final
                    self.warn("legacy-duplicate-name",
                              f"повтор имени «{escaped}»: корпус переименован в «{final}»",
                              start)
                result[final] = mod
                order.append(final)
                self.module = None
            line = self.readline()
        return [(n, result[n]) for n in order]

    # --- модуль ------------------------------------------------------------------------------------
    def load_module(self, mod: _Module) -> None:
        """``loadFOOTPRINT``."""
        while (line := self.readline()) is not None:
            c1 = _cget(line, 1)
            if _testsubstr(line, b"D") and (c1 == 0 or c1 in b"SCAP"):
                self.load_shape(mod, line)
            elif _testline(line, b"$PAD"):
                self.load_pad(mod)
            elif _testsubstr(line, b"T"):
                self.load_text(mod, line)
            elif _testline(line, b"Po"):
                self.load_module_po(mod, line)
            elif _testline(line, b"Sc"):
                # uuid корпуса отбрасывается, но KIID(nullptr) без токена — исключение KiCad
                if _strtok(line, 2)[0] is None:
                    raise self.error("Sc: нет идентификатора (uuid) модуля")
            elif _testline(line, b"Op"):
                pass  # стоимость автоплэйсмента — отбрасывается
            elif _testline(line, b"At"):
                rest = _cstr(line, 2)
                if b"SMD" in rest:
                    mod.attrs = ["smd"]
                elif b"VIRTUAL" in rest:
                    mod.attrs = ["exclude_from_pos_files", "exclude_from_bom"]
                else:
                    mod.attrs = ["through_hole", "exclude_from_pos_files"]
            elif _testline(line, b"AR"):
                pass  # путь на схеме — в библиотеку не пишется
            elif _testline(line, b"$SHAPE3D"):
                self.load_3d(mod)
            elif _testline(line, b"Cd"):
                mod.descr = self.decode(_strpurge(_cstr(line, 2)), "описание (Cd)")
            elif _testline(line, b"Kw"):
                mod.tags = self.decode(_strpurge(_cstr(line, 2)), "ключевые слова (Kw)")
            elif _testline(line, b".SolderPasteRatio"):
                r = _atof(line, 17)
                if math.isnan(r):
                    raise self.error(".SolderPasteRatio: коэффициент nan")
                mod.paste_ratio = min(0.0, max(-0.5, r))   # ±inf -> 0 / -0.5, как в KiCad
            elif _testline(line, b".SolderPaste"):
                mod.paste_margin = self.biu(line, 12)[0]
            elif _testline(line, b".SolderMask"):
                mod.mask_margin = self.biu(line, 11)[0]
            elif _testline(line, b".LocalClearance"):
                mod.clearance = self.biu(line, 15)[0]
            elif _testline(line, b".ZoneConnection"):
                mod.zone_connect = _strtol(line, 15)[0]
            elif _testline(line, b".ThermalWidth") or _testline(line, b".ThermalGap"):
                k = 13 if _testline(line, b".ThermalWidth") else 11
                self.biu(line, k)  # разбирается и отбрасывается
            elif _testline(line, b"$EndMODULE"):
                return
        raise self.error(f"нет строки $EndMODULE для модуля «{mod.name}»", line=mod.line)

    def load_module_po(self, mod: _Module, line: bytearray) -> None:
        """``Po x y orient layer edittime uuid status`` модуля."""
        x, i = self.biu(line, 2)
        y, i = self.biu(line, i)
        orient, i = _strtol(line, i)
        layer_num, i = _strtol(line, i)
        _, i = _strtoul16(line, i)
        # правильное чтение статуса (режим fixed): токен после uuid
        probe = bytearray(line)
        _, save = _strtok(probe, i)
        tok, _ = _strtok(probe, save)
        status_ok = _cstr(probe, tok) if tok is not None else b""
        # KiCad 9: strtok_r(data + 1, …) — первый символ статуса теряется
        uid, save = _strtok(line, i)
        if uid is None:
            # KIID(nullptr) в KiCad — исключение (библиотека не читается)
            raise self.error("Po: нет полей «время правки» и «uuid» модуля")
        tok, _ = _strtok(line, None if save is None else save + 1)
        status = _cstr(line, tok) if tok is not None else b""
        # флаги только устанавливаются (SetLocked(true)/SetIsPlaced(true)), не сбрасываются
        mod.locked = mod.locked or status[:1] == b"F"
        mod.placed = mod.placed or status[1:2] == b"P"
        mod.status_locked = mod.status_locked or status_ok[:1] == b"F"
        mod.layer_num = layer_num
        mod.set_position((x, y))
        mod.set_orientation(orient / 10.0)
        if self.compat == "kicad9" and mod.status_locked and not mod.locked:
            self.warn("legacy-locked-lost",
                      "признак блокировки (статус «F…») теряется, как в KiCad 9 "
                      "(compat=\"fixed\" его сохраняет)")

    # --- графика -------------------------------------------------------------------------------------
    def load_shape(self, mod: _Module, line: bytearray) -> None:
        """``loadFP_SHAPE``: ``DS``/``DC``/``DA``/``DP``."""
        c1 = _cget(line, 1)
        if c1 == 0:
            raise self.error("неизвестный тип графики (строка «D» без второго символа)")
        kind = {ord("S"): "line", ord("C"): "circle", ord("A"): "arc", ord("P"): "poly"}[c1]
        shape = _Shape(kind)
        if kind == "arc":
            cx, i = self.biu(line, 2)
            cy, i = self.biu(line, i)
            sx, i = self.biu(line, i)
            sy, i = self.biu(line, i)
            angle, i = self.deg(line, i)
            width, i = self.biu(line, i)
            layer, _ = _strtol(line, i)
            shape.center = (cx, cy)
            shape.start, shape.end = _arc_end((cx, cy), (sx, sy), angle)
        elif kind in ("line", "circle"):
            x0, i = self.biu(line, 2)
            y0, i = self.biu(line, i)
            x1, i = self.biu(line, i)
            y1, i = self.biu(line, i)
            width, i = self.biu(line, i)
            layer, _ = _strtol(line, i)
            shape.start, shape.end = (x0, y0), (x1, y1)
        else:
            _, i = self.biu(line, 2)
            _, i = self.biu(line, i)
            _, i = self.biu(line, i)
            _, i = self.biu(line, i)
            count, i = _strtol(line, i)
            width, i = self.biu(line, i)
            layer, _ = _strtol(line, i)
            if count < 0:
                # std::vector::reserve(отрицательное) в KiCad — исключение length_error
                raise self.error(f"DP: отрицательное число точек полигона ({count})")
            for _k in range(count):
                pl = self.readline()
                if pl is None:
                    raise self.error("DP: число точек полигона не совпадает (конец файла)")
                if not _testline(pl, b"Dl"):
                    raise self.error("DP: ожидалась строка точки полигона «Dl x y»")
                px, j = self.biu(pl, 2)
                py, _ = self.biu(pl, j)
                pt = (px, py)
                if not shape.pts or shape.pts[-1] != pt:   # SHAPE_LINE_CHAIN::Append
                    shape.pts.append(pt)
        if layer < 0 or layer > _LAST_NON_COPPER:
            layer = _SILK_FRONT
        shape.width = width
        shape.layer = _L.legacy_layer_to_name(layer)
        shape.rotate((0, 0), mod.orient)
        shape.move(mod.pos)
        mod.drawings.append(shape)

    # --- тексты --------------------------------------------------------------------------------------
    def load_text(self, mod: _Module, line: bytearray) -> None:
        """Строка ``T<n> …`` (``loadMODULE_TEXT``)."""
        tnum, _ = _strtol(line, 1)
        if tnum == 0:
            t = mod.reference
        elif tnum == 1:
            t = mod.value
        else:
            t = _Text("user", pos=mod.pos)
            mod.drawings.append(t)
        _, i = _strtol(line, 1)
        x, i = self.biu(line, i)
        y, i = self.biu(line, i)
        size_y, i = self.biu(line, i)
        size_x, i = self.biu(line, i)
        orient, i = self.deg(line, i)
        thick, i = self.biu(line, i)
        raw, n = _read_delimited(line, i)
        txt_end = i + n
        text = self.decode(raw, "текст").replace("%V", "${VALUE}").replace("%R", "${REFERENCE}")
        t.text = _convert_overbar(text)
        tok_m, save = _strtok(line, i)
        tok_h, save = _strtok(line, save)
        tok_l, save = _strtok(line, save)
        layer_num = _strtol(line, tok_l)[0] if tok_l is not None else _SILK_FRONT
        tok_i, save = _strtok(line, save)
        tok_hj, save = _strtok(line, txt_end if txt_end < len(line) else None)
        tok_vj, _ = _strtok(line, save)
        t.line = self.lineno
        # SetFPRelativePosition
        rp = _rotate((x, y), (0, 0), mod.orient)
        t.pos = (_i32(rp[0] + mod.pos[0]), _i32(rp[1] + mod.pos[1]))
        # EDA_TEXT::SetTextSize ограничивает размер [TEXT_MIN_SIZE_MM, TEXT_MAX_SIZE_MM]
        t.size = (min(max(size_x, _TEXT_MIN), _TEXT_MAX), min(max(size_y, _TEXT_MIN), _TEXT_MAX))
        t.angle = orient
        t.thickness = 0 if thick < 1 else thick
        t.mirror = tok_m is not None and _cget(line, tok_m) == ord("M")
        t.visible = not (tok_h is not None and _cget(line, tok_h) == ord("I"))
        t.italic = tok_i is not None and _cget(line, tok_i) == ord("I")
        if tok_hj is not None:
            hj = _cstr(line, tok_hj)
            t.hjust = "left" if hj == b"L" else "right" if hj == b"R" else None
        if tok_vj is not None:
            vj = _cstr(line, tok_vj)
            t.vjust = "top" if vj == b"T" else "bottom" if vj == b"B" else None
        if layer_num < 0:
            layer_num = 0
        elif layer_num > _LAST_NON_COPPER:
            layer_num = _LAST_NON_COPPER
        elif layer_num == _LAYER_BACK:
            layer_num = _SILK_BACK
        elif layer_num == _LAYER_FRONT:
            layer_num = _SILK_FRONT
        elif layer_num < _LAYER_FRONT:
            layer_num = _SILK_FRONT
        t.layer = _L.legacy_layer_to_name(layer_num)
        if t.kind == "user" and not t.visible:
            # KiCad 9: скрытый текст T2+ — поле (см. отклонение 1 в описании модуля)
            mod.drawings.remove(t)
            mod.fields.append(t)
            self.warn("legacy-hidden-text",
                      f"скрытый текст «{t.text}» записан скрытым полем (property "
                      f"\"FieldN\"): у KiCad 9 скрытых fp_text нет")

    # --- площадки ------------------------------------------------------------------------------------
    def load_pad(self, mod: _Module) -> None:
        """Блок ``$PAD … $EndPAD`` (``loadPAD``)."""
        pad = _Pad(pos=mod.pos, line=self.lineno)
        while (line := self.readline()) is not None:
            if _testline(line, b"Sh"):
                raw, n = _read_delimited(line, 3, 50)
                i = 3 + n + 1
                while i < len(line) and line[i] in b" \t\r\n\0":   # isSpace(0) истинно
                    i += 1
                ch = _cget(line, i)
                i += 1
                if ch not in _PAD_SHAPES:
                    shown = chr(ch) if 32 <= ch < 127 else "?"
                    raise self.error(f"неизвестная форма площадки «{shown}» (0x{ch:02x}) "
                                     f"в модуле «{mod.name}»", col=i)
                sx, i = self.biu(line, i)
                sy, i = self.biu(line, i)
                dx, i = self.biu(line, i)
                dy, i = self.biu(line, i)
                angle, _ = self.deg(line, i)
                pad.number = self.decode(raw, "номер площадки")
                pad.shape = _PAD_SHAPES[ch]
                pad.size = (abs(sx), abs(sy))     # PADSTACK::SetSize берёт модуль
                pad.delta = (dx, dy)
                pad.angle = _normalize(angle)
            elif _testline(line, b"Dr"):
                d, i = self.biu(line, 2)
                ox, i = self.biu(line, i)
                oy, i = self.biu(line, i)
                dx = dy = d
                oblong = False
                tok, save = _strtok(line, i)
                if tok is not None and _cget(line, tok) == ord("O"):
                    oblong = True
                    tok, save = _strtok(line, save)
                    if tok is None:
                        raise self.error("Dr: нет размеров овального отверстия")
                    dx = self.biu(line, tok)[0]
                    tok, save = _strtok(line, save)
                    if tok is None:
                        raise self.error("Dr: нет второго размера овального отверстия")
                    dy = self.biu(line, tok)[0]
                pad.oblong = oblong
                pad.offset = (ox, oy)
                pad.drill = (dx, dy)
            elif _testline(line, b"At"):
                tok, save = _strtok(line, 2)
                word = _cstr(line, tok) if tok is not None else b""
                attrib = {b"SMD": "SMD", b"CONN": "CONN", b"HOLE": "NPTH"}.get(word, "PTH")
                if attrib == "PTH" and word != b"STD":
                    self.warn("legacy-unknown-pad-attr",
                              f"неизвестный тип площадки «{word.decode('latin-1')}» — "
                              f"thru_hole, как в KiCad")
                _, save = _strtok(line, save)
                tok, save = _strtok(line, save)
                mask = _strtoul16(line, tok)[0] if tok is not None else 0
                pad.layers = frozenset(_mask_to_layers(mask))
                pad.set_attribute(attrib)
            elif _testline(line, b"Ne"):
                pass  # цепь — в библиотеку не пишется
            elif _testline(line, b"Po"):
                x, i = self.biu(line, 2)
                y, _ = self.biu(line, i)
                rp = _rotate((x, y), (0, 0), mod.orient)
                pad.pos = (_i32(rp[0] + mod.pos[0]), _i32(rp[1] + mod.pos[1]))
            elif _testline(line, b"Le"):
                pad.die_length = self.biu(line, 2)[0]
            elif _testline(line, b".SolderMask"):
                pad.mask_margin = self.biu(line, 11)[0]
            elif _testline(line, b".SolderPasteRatio"):
                pad.paste_ratio = _atof(line, 17)
                if not math.isfinite(pad.paste_ratio):
                    raise self.error(".SolderPasteRatio: коэффициент inf/nan")
            elif _testline(line, b".SolderPaste"):
                pad.paste_margin = self.biu(line, 12)[0]
            elif _testline(line, b".LocalClearance"):
                pad.clearance = self.biu(line, 15)[0]
            elif _testline(line, b".ZoneConnection"):
                pad.zone_connect = _strtol(line, 15)[0]
            elif _testline(line, b".ThermalWidth"):
                pad.thermal_width = self.biu(line, 13)[0]
            elif _testline(line, b".ThermalGap"):
                pad.thermal_gap = self.biu(line, 11)[0]
            elif _testline(line, b"$EndPAD"):
                if pad.size[0] > 0 and pad.size[1] > 0:
                    mod.pads.append(pad)
                else:
                    self.warn("legacy-zero-size-pad",
                              f"площадка «{pad.number}» нулевого размера удалена (как в KiCad)",
                              pad.line)
                return
        raise self.error("нет строки $EndPAD", line=pad.line)

    # --- 3D ------------------------------------------------------------------------------------------
    def load_3d(self, mod: _Module) -> None:
        """Блок ``$SHAPE3D … $EndSHAPE3D`` (``load3D``)."""
        m = _Model3D(line=self.lineno)
        while (line := self.readline()) is not None:
            if _testline(line, b"Na"):
                raw, _ = _read_delimited(line, 2, 512)
                m.path = self.decode(raw, "имя файла 3D-модели")
            elif _testline(line, b"Sc"):
                m.scale = _scan3(line, 2, m.scale)
            elif _testline(line, b"Of"):
                m.offset = _scan3(line, 2, m.offset)
            elif _testline(line, b"Ro"):
                m.rotation = _scan3(line, 2, m.rotation)
            elif _testline(line, b"$EndSHAPE3D"):
                if not all(math.isfinite(v) for v in m.scale + m.offset + m.rotation):
                    raise self.error("3D-модель: значение inf/nan", line=m.line)
                mod.models.append(m)
                return
        raise self.error("нет строки $EndSHAPE3D", line=m.line)


def _scan3(buf: bytearray, i: int, cur: tuple[float, float, float]) -> tuple[float, float, float]:
    """``sscanf("%lf %lf %lf")``: разобранные числа заменяют значения по порядку."""
    vals = list(cur)
    for k in range(3):
        v, end, _ = _strtod(buf, i)
        if v is None:
            break
        vals[k] = v
        i = end
    return (vals[0], vals[1], vals[2])


def _mask_to_layers(mask: int) -> set[str]:
    """``leg_mask2new`` (``cu_count = 16``): маска слоёв → набор имён."""
    out: set[str] = set()
    mask &= 0xFFFFFFFF
    if mask & 0x0000FFFF == 0x0000FFFF:
        out |= _ALL_CU
        mask &= ~0x0000FFFF
    n = 0
    while mask:
        if mask & 1:
            out.add(_L.legacy_layer_to_name(n))
        mask >>= 1
        n += 1
    return out


def _convert_overbar(s: str) -> str:
    """``ConvertToNewOverbarNotation`` KiCad (буквально, включая выход с исходной строкой
    при ``~{`` и ``~~{``)."""
    if s == "~":
        return s
    out: list[str] = []
    over = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "~":
            la = i + 1
            if la < n and s[la] == "~":
                la += 1
                if la < n and s[la] == "{":
                    out.append("~~{}")
                    i += 1
                    continue
                out.append("~")
                i += 2
                continue
            if la < n and s[la] == "{":
                return s
            out.append("}" if over else "~{")
            over = not over
            i += 1
            continue
        if ch in " })" and over:
            out.append("}")
            over = False
        out.append(ch)
        i += 1
    if over:
        out.append("}")
    return "".join(out)


# ---------------------------------------------------------------------------
# Построение Footprint
# ---------------------------------------------------------------------------

def _mm(v: int) -> float:
    return v / 1e6


def _mmpt(p: Pt) -> tuple[float, float]:
    return (p[0] / 1e6, p[1] / 1e6)


def _build(mod: _Module, compat: str, reader: _Reader) -> Footprint:
    """Модуль → :class:`Footprint` (``FootprintSave``: ориентация обнуляется, запись
    относительно якоря, порядок элементов — как у writer'а KiCad 9)."""
    mod.set_orientation(0.0)
    layer_name = _L.legacy_layer_to_name(mod.layer_num)
    reader.module = mod
    if layer_name == "B.Cu":
        fp_layer = "B.Cu"
        reader.warn("legacy-back-layer",
                    "корпус на обратной стороне (слой 0): сохранён как есть с (layer "
                    "\"B.Cu\"), без переноса на F.Cu (KiCad 9 на таком корпусе падает)",
                    mod.line)
    elif layer_name != "F.Cu":
        fp_layer = "F.Cu"
        reader.warn("legacy-module-layer",
                    f"слой корпуса {mod.layer_num} ({layer_name}) — записан F.Cu", mod.line)
    else:
        fp_layer = "F.Cu"
    fp = Footprint.new(mod.name, version=DEFAULT_VERSION, layer=fp_layer)
    prof = fp.profile
    for t in (fp.reference, fp.value):
        if t is not None:
            fp.remove(t)
    for st in mod.service:
        view = fp.properties.text(st.kind)
        if view is not None and st.angle != 0.0:
            view.angle = st.angle
    if compat == "fixed":
        fp.locked = mod.status_locked
    else:
        fp.locked = mod.locked
        fp.placed = mod.placed
    if mod.descr:
        fp.descr = mod.descr
    if mod.tags:
        fp.tags = mod.tags
    if mod.mask_margin is not None:
        fp.solder_mask_margin = _mm(mod.mask_margin)
    if mod.paste_margin is not None:
        fp.solder_paste_margin = _mm(mod.paste_margin)
    if mod.paste_ratio is not None:
        fp.solder_paste_ratio = mod.paste_ratio
    if mod.clearance is not None:
        fp.clearance = _mm(mod.clearance)
    if mod.zone_connect != _ZONE_INHERITED:
        fp.zone_connect = mod.zone_connect
    if mod.attrs:
        fp.attrs = mod.attrs
    for t in [mod.reference, mod.value] + mod.fields:
        fp.add(_make_text(t, mod, prof))
    for d in mod.drawings:
        if isinstance(d, _Text):
            fp.add(_make_text(d, mod, prof))
            continue
        g = _make_shape(d, mod, compat, prof)
        if g is not None:
            fp.add(g)
    for p in mod.pads:
        fp.add(_make_pad(p, mod, prof))
    for m in mod.models:
        if not m.path:
            continue
        offset = m.offset
        if any(offset):
            if compat == "fixed":
                offset = (offset[0] * _OF_INCH_TO_MM, offset[1] * _OF_INCH_TO_MM,
                          offset[2] * _OF_INCH_TO_MM)
                reader.warn("legacy-model-offset",
                            f"смещение 3D-модели «{m.path}» в дюймах пересчитано в мм (×25.4)",
                            m.line)
            else:
                reader.warn("legacy-model-offset",
                            f"смещение 3D-модели «{m.path}» (дюймы) записано без пересчёта в "
                            f"мм, как в KiCad 9 (compat=\"fixed\" умножает на 25.4)", m.line)
        fp.add(Model.new(m.path, offset=offset, scale=m.scale, rotate=m.rotation, profile=prof))
    _sort_root_like_kicad(fp.node, DEFAULT_VERSION)
    reader.module = None
    return fp


def _make_text(t: _Text, mod: _Module, prof: object) -> Text:
    """Текст/поле KiCad 9 (``PCB_TEXT``/``PCB_FIELD``) из промежуточного объекта."""
    justify = [j for j in (t.hjust, t.vjust) if j] + (["mirror"] if t.mirror else [])
    x, y = _mmpt(mod.rel(t.pos))
    view = Text.new(t.text, t.kind, x, y, t.layer, angle=t.angle,
                    size=(_mm(t.size[0]), _mm(t.size[1])),
                    thickness=_mm(t.thickness) if t.thickness else None,
                    hide=not t.visible, justify=justify or None, profile=prof)  # type: ignore[arg-type]
    if t.italic:
        view.italic = True
    return view


def _make_shape(s: _Shape, mod: _Module, compat: str, prof: object) -> object | None:
    """Графика KiCad 9 из промежуточного объекта (``None`` — KiCad её не пишет)."""
    w = _mm(s.width)
    if s.kind == "line":
        return Line.new(_mmpt(mod.rel(s.start)), _mmpt(mod.rel(s.end)), s.layer, w,
                        profile=prof)  # type: ignore[arg-type]
    if s.kind == "circle":
        return Circle.new(_mmpt(mod.rel(s.start)), None, s.layer, w,
                          end=_mmpt(mod.rel(s.end)), fill=False, profile=prof)  # type: ignore[arg-type]
    if s.kind == "arc":
        mid = _mmpt(mod.rel(_arc_mid(s.start, s.end, s.center)))
        arc = Arc.new(_mmpt(mod.rel(s.start)), mid, _mmpt(mod.rel(s.end)),
                      s.layer, w, profile=prof)  # type: ignore[arg-type]
        # середина — ровно GetArcMid KiCad (от округлённого до нм конца); Arc.new заменяет
        # её «истинной» серединой окружности через три точки, которая может отличаться на
        # 2 нм — возвращаем значение KiCad
        mid_node = arc.node.find("mid")
        if mid_node is not None:
            mid_node.items = [Sym(format_number(mid[0])), Sym(format_number(mid[1]))]
        return arc
    if len(s.pts) <= 2:
        return None
    fill = compat == "fixed" and s.layer != "Edge.Cuts"
    return Poly.new([_mmpt(mod.rel(p)) for p in s.pts], s.layer, w, fill=fill,
                    profile=prof)  # type: ignore[arg-type]


def _make_pad(p: _Pad, mod: _Module, prof: object) -> Pad:
    """Площадка KiCad 9 из промежуточного объекта (writer ``format(PAD)``)."""
    x, y = _mmpt(mod.rel(p.pos))
    ptype = _PAD_TYPES[p.attrib]
    # копирование площадки (Duplicate при FootprintLoad, Clone при FootprintSave) идёт через
    # PAD::ImportSettingsFrom: у круглой площадки размер по Y := размер по X, у SMD/CONN
    # отверстие обнуляется (даже если строка Dr шла после At)
    size = (p.size[0], p.size[0]) if p.shape == "circle" else p.size
    drill = (0, 0) if p.attrib in ("SMD", "CONN") else p.drill
    layers = _L.collapse(p.layers, kicad=9)
    kw: dict[str, object] = {}
    if p.delta != (0, 0):
        kw["rect_delta"] = _mmpt(p.delta)
    if p.die_length:
        kw["die_length"] = _mm(p.die_length)
    if p.mask_margin is not None:
        kw["solder_mask_margin"] = _mm(p.mask_margin)
    if p.paste_margin is not None:
        kw["solder_paste_margin"] = _mm(p.paste_margin)
    if p.paste_ratio is not None:
        kw["solder_paste_ratio"] = p.paste_ratio
    if p.clearance is not None:
        kw["clearance"] = _mm(p.clearance)
    if p.zone_connect != _ZONE_INHERITED:
        kw["zone_connect"] = p.zone_connect
    if p.thermal_width is not None:
        kw["thermal_bridge_width"] = _mm(p.thermal_width)
    if p.shape != "circle":
        # угол спиц площадки по умолчанию — 45°; writer опускает только умолчание формы
        kw["thermal_bridge_angle"] = 45.0
    if p.thermal_gap is not None:
        kw["thermal_gap"] = _mm(p.thermal_gap)
    pad = Pad.new(p.number, ptype, p.shape, x, y, _mmpt(size), layers=layers,
                  angle=p.angle, profile=prof, **kw)  # type: ignore[arg-type]
    dx, dy = drill
    if dx > 0 or dy > 0 or p.offset != (0, 0):
        atoms: list[object] = [Sym("oval")] if p.oblong else []
        if dx > 0:
            atoms.append(Sym(format_number(_mm(dx))))
        if dy > 0 and dx != dy:
            atoms.append(Sym(format_number(_mm(dy))))
        if p.offset != (0, 0):
            atoms.append(Node("offset", [Sym(format_number(_mm(p.offset[0]))),
                                         Sym(format_number(_mm(p.offset[1])))]))
        pad.drill = Drill(Node("drill", atoms))  # type: ignore[arg-type]
    return pad


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def _check_compat(compat: str) -> str:
    if compat not in COMPAT_MODES:
        raise ValueError(f"compat: ожидается одно из {', '.join(COMPAT_MODES)}, "
                         f"получено {compat!r}")
    return compat


def _to_bytes(text: str | bytes | bytearray) -> bytes:
    if isinstance(text, (bytes, bytearray)):
        return bytes(text)
    if isinstance(text, str):
        # суррогаты (io.loads читает некорректный UTF-8 как surrogateescape) — исходные байты
        return text.encode("utf-8", "surrogateescape")
    raise TypeError("ожидается str или bytes")


def _load(data: bytes, compat: str, issues: list[LegacyIssue] | None,
          path: str | None) -> list[Footprint]:
    reader = _Reader(data, _check_compat(compat), issues, path)
    modules = reader.load()
    # FootprintEnumerate: имена — ключи std::map (побайтовая сортировка UTF-8)
    modules.sort(key=lambda nm: nm[0].encode("utf-8", "surrogatepass"))
    return [_build(mod, compat, reader) for _, mod in modules]


def loads_library(text: str | bytes, *, compat: str = "kicad9",
                  issues: list[LegacyIssue] | None = None) -> list[Footprint]:
    """Прочитать библиотеку ``PCBNEW-LibModule-V1`` из текста (``str`` или ``bytes``).

    Возвращает корпуса формата KiCad 9 в порядке побайтовой сортировки имён (как
    ``FootprintEnumerate`` KiCad). ``compat`` — ``"kicad9"`` (как KiCad 9, по умолчанию) или
    ``"fixed"`` (физически корректная конвертация, см. описание модуля). В ``issues``
    (если передан список) добавляются замечания :class:`LegacyIssue`. Ошибка формата —
    :class:`LegacyFormatError` с номером строки.
    """
    return _load(_to_bytes(text), compat, issues, None)


def read_library(path: str | PathLike[str], *, compat: str = "kicad9",
                 issues: list[LegacyIssue] | None = None) -> list[Footprint]:
    """Прочитать файл библиотеки ``.mod``/``.emp`` (см. :func:`loads_library`); у
    :class:`LegacyFormatError` заполняется ``path``."""
    p = Path(path)
    return _load(p.read_bytes(), compat, issues, str(p))


def _file_name(name: str) -> str:
    """Имя файла корпуса: ``ReplaceIllegalFileNameChars(имя, '_')`` + ``.kicad_mod``."""
    return "".join("_" if ch in _ILLEGAL_NAME_CHARS else ch for ch in name) + ".kicad_mod"


def convert(mod_path: str | PathLike[str], out_dir: str | PathLike[str], *,
            compat: str = "kicad9", issues: list[LegacyIssue] | None = None) -> list[Path]:
    """Преобразовать библиотеку ``.mod`` в каталог ``.pretty``: каждый модуль →
    ``<out_dir>/<имя>.kicad_mod`` (каталог создаётся; файлы с теми же именами
    перезаписываются атомарно). Сначала читается вся библиотека: при ошибке формата
    (:class:`LegacyFormatError`) не пишется ни один файл — как у KiCad. Возвращает пути
    записанных файлов в порядке имён.
    """
    from .io import save  # локальный импорт: io импортирует legacy лениво

    fps = read_library(mod_path, compat=compat, issues=issues)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for fp in fps:
        target = out / _file_name(fp.name)
        save(fp, target)
        paths.append(target)
    return paths


def is_legacy(text_head: str | bytes) -> bool:
    """Начинается ли текст с заголовка ``PCBNEW-LibModule-V1`` (без учёта регистра, за ним —
    пробел, таб, CR, LF или конец строки; BOM UTF-8 пропускается)."""
    data = _to_bytes(text_head)
    if data.startswith(_BOM):
        data = data[len(_BOM):]
    first = data.split(b"\n", 1)[0]
    return _testline(bytearray(first + b"\0"), LEGACY_HEADER.encode())
