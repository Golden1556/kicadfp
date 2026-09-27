"""Низкоуровневые текстовые утилиты, повторяющие функции KiCad из common/string.cpp.

- EscapedUTF8 / ReadDelimitedText — кавычки с экранированием \\" и \\\\
  (common/string.cpp:11-125). Используются для полей F<n> в .lib и .sch,
  для строк $Descr и для имён/файлов листов.
- Кодирование текста T-строк .lib (lib_text.cpp:38-119) — ДРУГАЯ схема:
  либо кавычки с заменой " на '' , либо без кавычек с заменой пробела на ~.
- Дата в формате, который пишет wxDateTime::Format(%c) в русской локали
  Windows: "Ср 02.09.26 19:52:23" (так выглядят реальные файлы пользователя).
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Optional, Tuple

# --- EscapedUTF8 / ReadDelimitedText -------------------------------------


def escaped(text: str) -> str:
    """EscapedUTF8 (common/string.cpp:99-127): оборачивает в кавычки,
    экранирует " -> \\" и \\ -> \\\\."""
    out = ['"']
    for ch in text:
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def read_delimited(src: str, start: int = 0) -> Tuple[str, int]:
    """ReadDelimitedText (common/string.cpp:11-50).

    Ищет первую кавычку начиная с ``start``, копирует до второй
    неэкранированной кавычки. ``\\"`` -> ``"``, ``\\\\`` -> ``\\``, любой другой
    ``\\x`` сохраняется как два символа. Возвращает (текст, позиция после
    закрывающей кавычки). Если кавычка не найдена — ("", len(src)).
    """
    out = []
    inside = False
    i = start
    n = len(src)
    while i < n:
        cc = src[i]
        i += 1
        if cc == '"':
            if inside:
                break
            inside = True
        elif inside:
            if cc == '\\':
                if i >= n:
                    break
                cc = src[i]
                i += 1
                if cc != '"' and cc != '\\':
                    out.append('\\')
                out.append(cc)
            else:
                out.append(cc)
    return ''.join(out), i


# --- Текст T-строк в .lib ----------------------------------------------------


def encode_lib_text(text: str) -> str:
    """LIB_TEXT::Save (lib_text.cpp:40-53)."""
    if '~' in text or '"' in text:
        return '"' + text.replace('"', "''") + '"'
    return text.replace(' ', '~')


def decode_lib_text_quoted(buf: str) -> str:
    """LIB_TEXT::Load, ветка с кавычками (lib_text.cpp:97-102)."""
    return buf.replace("''", '"')


def decode_lib_text_bare(buf: str) -> str:
    """LIB_TEXT::Load, ветка без кавычек (lib_text.cpp:116-118)."""
    return buf.replace('~', ' ')


# --- Имена в строке L блока $Comp (.sch) --------------------------------------


def encode_sch_name(text: str) -> str:
    """SCH_COMPONENT::Save (sch_component.cpp:896-920): каждый байт <= ' ' -> '~'."""
    return ''.join('~' if ord(ch) <= 0x20 else ch for ch in text)


def decode_sch_name(text: str) -> str:
    """SCH_COMPONENT::Load (sch_component.cpp:1045-1047): '~' -> ' '."""
    return text.replace('~', ' ')


# --- sscanf-подобные помощники ---------------------------------------------

_INT_RE = re.compile(r'^[+-]?\d+$')
_HEX_RE = re.compile(r'^(0[xX])?[0-9a-fA-F]+$')


def is_int(tok: str) -> bool:
    return bool(_INT_RE.match(tok))


def scan_ints(tokens, count: int):
    """Эмуляция последовательности %d в sscanf: возвращает список успешно
    прочитанных целых (останавливается на первом нечисловом токене)."""
    out = []
    for tok in tokens[:count]:
        if not is_int(tok):
            break
        out.append(int(tok))
    return out


def parse_hex(tok: str) -> Optional[int]:
    """%lX / %X: шестнадцатеричное число, регистр не важен."""
    if not _HEX_RE.match(tok):
        return None
    return int(tok, 16)


# --- Дата ------------------------------------------------------------------

_RU_WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


def kicad_date(when: Optional[_dt.datetime] = None) -> str:
    """Строка даты в стиле реальных файлов пользователя (русская локаль,
    wxDefaultDateTimeFormat = "%c"): 'Ср 02.09.26 19:52:23'.
    Парсером никогда не разбирается — чисто информационное поле."""
    when = when or _dt.datetime.now()
    return '%s %s' % (_RU_WEEKDAYS[when.weekday()], when.strftime('%d.%m.%y %H:%M:%S'))


# --- Единицы -----------------------------------------------------------------

MIL_PER_MM = 1000.0 / 25.4


def mm_to_mil(mm: float, grid: int = 0) -> int:
    """Миллиметры -> милы. При ``grid`` > 0 округляет к кратному сетки
    (методички: «5 мм ~ 5,08 мм = 4 клетки» при сетке 50 мил)."""
    mil = mm * MIL_PER_MM
    if grid:
        return int(round(mil / grid)) * grid
    return int(round(mil))


def mil_to_mm(mil: int) -> float:
    return mil / MIL_PER_MM
