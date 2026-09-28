"""Дерево S-выражений KiCad: разбор, представление, запись.

Модуль не привязан к типу файла (footprint, board, symbol …) и является основой
для всех представлений модели. Основные сущности:

* :class:`Sym` — голый токен (символ, число, ключевое слово) — хранится как записан;
* :class:`Str` — строка в кавычках, хранится уже без экранирования;
* :class:`Node` — список ``(name элемент …)``; элементы — атомы и подузлы в исходном
  порядке.

Функция :func:`parse` разбирает текст целиком и при синтаксической ошибке
выбрасывает :class:`SexprSyntaxError` с номером строки и позицией (модель не
создаётся). Функция :func:`dumps` записывает дерево в одном из стилей KiCad:

* ``"kicad8"`` — точный порт алгоритма ``KICAD_FORMAT::Prettify`` (KiCad 8, 9, 10):
  табуляция, каждый подсписок на новой строке, особые случаи для ``(xy …)``;
* ``"kicad6"`` / ``"kicad7"`` / ``"kicad5"`` — табличная раскладка writer'ов KiCad 5.1, 6.0
  и 7.0 (два пробела на уровень, часть узлов в одну строку);
* ``"auto"`` — выбор по версии формата файла (см. :func:`style_for_version`).

Числа записываются по правилам KiCad: длины — :func:`format_number`
(``FormatInternalUnits`` после ``KiROUND`` до нанометров), углы — :func:`format_angle`
(``FormatAngle``), коэффициенты и 3D-параметры — :func:`format_double`
(``FormatDouble2Str``). Строки экранируются как ``OUTPUTFORMATTER::Quotes``
(:func:`quote`), разбор (включая экранирование и комментарии) — как ``DSNLEXER``.
Раскладка KiCad 5/6/7 проверяется обратным разбором: узел, который табличные
правила исказили бы (нестандартный порядок/состав), пишется одной строкой без потерь.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Iterable, Iterator, Sequence, Union

__all__ = [
    "Sym", "Str", "Node", "Atom", "SexprSyntaxError",
    "parse", "parse_all", "dumps", "to_compact", "prettify",
    "format_number", "format_angle", "format_double", "quote", "unquote", "atom_text",
    "equal", "diff", "style_for_version", "is_number",
]


# ---------------------------------------------------------------------------
# Атомы и узлы
# ---------------------------------------------------------------------------

class Sym(str):
    """Голый токен S-выражения: символ (``thru_hole``), число (``1.6``) или ключевое слово.

    Хранится ровно так, как записан в файле (числа — исходным текстом), поэтому
    неизменённые значения воспроизводятся байт в байт.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"Sym({str.__repr__(self)})"


class Str(str):
    """Строка в кавычках; значение хранится без экранирования."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"Str({str.__repr__(self)})"


Atom = Union[Sym, Str]


class Node:
    """Узел S-выражения ``(name items…)``.

    ``items`` — список атомов (:class:`Sym`/:class:`Str`) и подузлов в исходном
    порядке. ``line``/``col`` — позиция открывающей скобки в исходном тексте
    (нумерация с 1; 0 — узел создан в памяти). ``comments`` — строки комментариев
    (начинающиеся с ``#``), стоявшие перед корневым узлом файла (KiCad сохраняет их).
    """

    __slots__ = ("name", "items", "line", "col", "comments")

    def __init__(self, name: str, items: Iterable[Node | Atom | str | int | float | bool] = (),
                 line: int = 0, col: int = 0) -> None:
        self.name = str(name)
        self.items: list[Node | Atom] = [_coerce(v) for v in items]
        self.line = line
        self.col = col
        self.comments: list[str] = []

    # -- навигация ---------------------------------------------------------
    def nodes(self, name: str | None = None) -> list[Node]:
        """Дочерние узлы (все или только с именем ``name``)."""
        if name is None:
            return [x for x in self.items if isinstance(x, Node)]
        return [x for x in self.items if isinstance(x, Node) and x.name == name]

    def atoms(self) -> list[Atom]:
        """Дочерние атомы по порядку (без подузлов)."""
        return [x for x in self.items if not isinstance(x, Node)]

    def find(self, name: str) -> Node | None:
        """Первый дочерний узел с именем ``name`` или ``None``."""
        for x in self.items:
            if isinstance(x, Node) and x.name == name:
                return x
        return None

    def find_all(self, name: str) -> list[Node]:
        """Все дочерние узлы с именем ``name`` (синоним :meth:`nodes` с именем)."""
        return self.nodes(name)

    def index(self, child: Node | Atom) -> int:
        """Индекс элемента в ``items`` по идентичности объекта."""
        for i, x in enumerate(self.items):
            if x is child:
                return i
        raise ValueError("элемент не принадлежит узлу")

    def has(self, name: str) -> bool:
        """Есть ли дочерний узел с именем ``name``."""
        return self.find(name) is not None

    def has_flag(self, flag: str, *, skip: int | None = None) -> bool:
        """Есть ли среди атомов голый символ-флаг ``flag`` (например ``locked``, ``hide``).

        Позиционные атомы (значения, а не флаги) не учитываются: текст ``fp_text``
        KiCad 5 может быть голым символом ``hide``/``locked``, номер площадки — ``locked``
        и т.п. ``skip=None`` — позиционные атомы по таблице
        :func:`kicadfp.format_rules.positional_atoms` (по имени узла: тип и текст
        ``fp_text``, номер/тип/форма ``pad``, путь ``model``, имя корпуса …); целое
        ``skip`` — первые ``skip`` атомов позиционные (``0`` — все атомы считаются флагами).
        """
        pos = self._positional(skip)
        return any(isinstance(x, Sym) and x == flag and i not in pos
                   for i, x in enumerate(self.items))

    def _positional(self, skip: int | None) -> frozenset[int]:
        """Индексы ``items`` позиционных атомов (см. :meth:`has_flag`)."""
        if skip is None:
            from .format_rules import positional_atoms
            return positional_atoms(self)
        out: list[int] = []
        for i, x in enumerate(self.items):
            if len(out) >= skip:
                break
            if not isinstance(x, Node):
                out.append(i)
        return frozenset(out)

    # -- атомарные значения --------------------------------------------------
    def atom(self, i: int, default: Atom | None = None) -> Atom | None:
        """``i``-й атом (считаются только атомы) или ``default``."""
        n = 0
        for x in self.items:
            if not isinstance(x, Node):
                if n == i:
                    return x
                n += 1
        return default

    def set_atom(self, i: int, value: Atom | str | int | float | bool) -> None:
        """Заменить ``i``-й атом; если атомов меньше — дописать в конец списка атомов."""
        v = _coerce(value)
        n = 0
        for k, x in enumerate(self.items):
            if not isinstance(x, Node):
                if n == i:
                    self.items[k] = v
                    return
                n += 1
        # дописать после последнего атома (перед первым подузлом, если атомов нет — в начало)
        pos = len(self.items)
        for k in range(len(self.items) - 1, -1, -1):
            if not isinstance(self.items[k], Node):
                pos = k + 1
                break
        else:
            pos = 0
        self.items.insert(pos, v)

    def value(self, name: str, i: int = 0, default=None):
        """Атом ``i`` дочернего узла ``name`` (или ``default``)."""
        child = self.find(name)
        if child is None:
            return default
        a = child.atom(i)
        return default if a is None else a

    def number(self, name: str, i: int = 0, default: float | None = None) -> float | None:
        """Числовое значение атома ``i`` дочернего узла ``name``.

        Числом считается только то, что лексер KiCad распознаёт как число
        (:func:`is_number`): ``"1_0"``, ``"inf"``, ``"nan"`` дают ``default``,
        а не значение по правилам ``float()`` Python.
        """
        a = self.value(name, i)
        if a is None or not is_number(a):
            return default
        return float(a)

    def numbers(self, name: str) -> list[float] | None:
        """Все атомы-числа дочернего узла ``name`` (``None`` если узла нет); см. :func:`is_number`."""
        child = self.find(name)
        if child is None:
            return None
        return [float(a) for a in child.items if not isinstance(a, Node) and is_number(a)]

    # -- изменение ----------------------------------------------------------
    def set(self, name: str, *values, order: Sequence[str] | None = None) -> Node:
        """Установить дочерний узел ``(name values…)``.

        Если узел уже есть — его атомы заменяются на ``values`` (подузлы сохраняются);
        иначе создаётся новый узел и вставляется по таблице порядка ``order``
        (после последнего существующего дочернего узла, чьё имя стоит в ``order``
        раньше ``name``; без ``order`` — в конец). Возвращает узел.
        Преобразование значений: ``float`` → :func:`format_number`, ``int`` → ``str``,
        ``bool`` → ``yes``/``no``, ``str`` → :class:`Str`, :class:`Sym`/:class:`Str` как есть.
        """
        child = self.find(name)
        if child is not None:
            subnodes = [x for x in child.items if isinstance(x, Node)]
            child.items = [_coerce(v) for v in values] + subnodes
            return child
        child = Node(name, values)
        self.insert(child, order=order)
        return child

    def remove(self, name: str) -> bool:
        """Удалить все дочерние узлы с именем ``name``. Возвращает, было ли что удалять."""
        before = len(self.items)
        self.items = [x for x in self.items if not (isinstance(x, Node) and x.name == name)]
        return len(self.items) != before

    def remove_child(self, child: Node | Atom) -> None:
        """Удалить элемент по идентичности объекта."""
        del self.items[self.index(child)]

    def insert(self, child: Node | Atom, order: Sequence[str] | None = None) -> None:
        """Вставить подузел по таблице порядка (см. :meth:`set`); без ``order`` — в конец."""
        if order is None or not isinstance(child, Node) or child.name not in order:
            self.items.append(_coerce(child) if not isinstance(child, Node) else child)
            return
        rank = {n: i for i, n in enumerate(order)}
        my_rank = rank[child.name]
        pos = None
        last_atom = -1
        for i, x in enumerate(self.items):
            if isinstance(x, Node):
                r = rank.get(x.name)
                if r is not None and r <= my_rank:
                    pos = i + 1
            else:
                last_atom = i
        if pos is None:
            # ни одного предшественника: после атомов и перед первым узлом, стоящим позже
            pos = last_atom + 1
            for i, x in enumerate(self.items):
                if isinstance(x, Node):
                    r = rank.get(x.name)
                    if r is not None and r > my_rank:
                        pos = i
                        break
                    if r is None:
                        # неизвестный узел: вставляем перед ним только если ещё не прошли атомы
                        continue
            else:
                if pos <= last_atom:
                    pos = last_atom + 1
        self.items.insert(pos, child)

    def append(self, child: Node | Atom | str | int | float | bool) -> None:
        """Добавить элемент в конец (значения приводятся как в :meth:`set`)."""
        self.items.append(child if isinstance(child, Node) else _coerce(child))

    def replace_child(self, old: Node | Atom, new: Node | Atom) -> None:
        """Заменить элемент ``old`` (по идентичности) на ``new``."""
        self.items[self.index(old)] = new if isinstance(new, Node) else _coerce(new)

    def set_flag(self, flag: str, on: bool, order: Sequence[str] | None = None, *,
                 skip: int | None = None) -> None:
        """Добавить/убрать голый символ-флаг среди атомов (``locked``, ``hide``, ``unlocked``).

        Позиционные атомы (``skip``, как в :meth:`has_flag`) флагами не считаются: они не
        удаляются при ``on=False`` и не мешают добавить настоящий флаг (текст ``hide``
        у ``fp_text`` KiCad 5 остаётся текстом). ``on=False`` удаляет все
        непозиционные вхождения флага.

        Без ``order`` (или если ``flag`` в нём нет) новый флаг ставится после последнего
        атома. С ``order`` — после последнего элемента, стоящего в таблице не позже
        ``flag`` (подузлы сравниваются по имени, флаги-символы — по значению);
        позиционные атомы и атомы, не входящие в таблицу (``reference``, ``"REF**"`` …),
        предшествуют флагу, только если стоят раньше первого элемента-«последователя»
        (элемента таблицы с большим рангом): «хвостовой» неизвестный атом после
        ``(effects …)`` не утаскивает флаг в конец. Неизвестные подузлы нейтральны.

        Особая позиция, которая рангом не выражается, при ``skip=None`` берётся из
        :func:`kicadfp.format_rules.flag_slot`: голый ``locked`` у ``fp_text`` KiCad 6/7
        стоит между типом и текстом (``(fp_text reference locked "REF**" …)``), у
        ``fp_text_box`` 7.0 — перед текстом; такой слот имеет приоритет над ``order``.
        """
        pos_atoms = self._positional(skip)
        if on:
            if self.has_flag(flag, skip=skip):
                return
            if skip is None:
                from .format_rules import flag_slot
                slot = flag_slot(self, flag)
                if slot is not None:
                    self.items.insert(slot, Sym(flag))
                    return
            pos = 0
            for i, x in enumerate(self.items):
                if not isinstance(x, Node):
                    pos = i + 1
            if order is not None and flag in order:
                rank = {n: i for i, n in enumerate(order)}
                my = rank[flag]
                pos = 0
                seen_successor = False
                for i, x in enumerate(self.items):
                    if isinstance(x, Node):
                        r = rank.get(x.name)
                        if r is None:
                            continue
                    else:
                        r = (rank.get(str(x)) if isinstance(x, Sym) and i not in pos_atoms
                             else None)
                        if r is None:
                            if not seen_successor:
                                pos = i + 1
                            continue
                    if r <= my:
                        pos = i + 1
                    else:
                        seen_successor = True
            self.items.insert(pos, Sym(flag))
        else:
            self.items = [x for i, x in enumerate(self.items)
                          if not (isinstance(x, Sym) and x == flag and i not in pos_atoms)]

    def copy(self) -> Node:
        """Глубокая копия (позиции ``line``/``col`` обнуляются)."""
        n = Node(self.name)
        n.items = [x.copy() if isinstance(x, Node) else x for x in self.items]
        n.comments = list(self.comments)
        return n

    # -- служебное ----------------------------------------------------------
    def __iter__(self) -> Iterator[Node | Atom]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __repr__(self) -> str:
        s = to_compact(self)
        if len(s) > 120:
            s = s[:117] + "..."
        return f"Node<{s}>"


def _coerce(v) -> Node | Atom:
    """Привести python-значение к атому дерева (см. :meth:`Node.set`)."""
    if isinstance(v, (Node, Sym, Str)):
        return v
    if isinstance(v, bool):
        return Sym("yes" if v else "no")
    if isinstance(v, int):
        return Sym(str(v))
    if isinstance(v, float):
        return Sym(format_number(v))
    if isinstance(v, str):
        return Str(v)
    raise TypeError(f"недопустимый тип значения для S-выражения: {type(v).__name__}")


# ---------------------------------------------------------------------------
# Числа и строки
# ---------------------------------------------------------------------------

# Число по правилам DSNLEXER::isNumber: [-+]? цифры [. цифры] [e[-+]цифры], хотя бы одна
# цифра в мантиссе; «1.», «.5», «1e5» — числа; «1_0», «inf», «nan», «0x10», «1e» — нет.
_NUMBER_RE = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")


def is_number(atom) -> bool:
    """Является ли атом числом по правилам лексера KiCad (``DSNLEXER::isNumber``).

    Используется при сравнении деревьев и в :meth:`Node.number`. В отличие от
    ``float()`` Python не принимает ``1_000``, ``inf``, ``nan``, пробелы по краям.
    Как и в KiCad, шестнадцатеричная метка вида ``5E888720`` формально — число.
    """
    if isinstance(atom, Node):
        return False
    return _NUMBER_RE.match(atom) is not None


def _kiround(x: float) -> int:
    """``KiROUND``: округление половины от нуля (``x ± 0.5`` с отбрасыванием дробной части)."""
    return int(x - 0.5) if x < 0 else int(x + 0.5)


def _strip_fraction_zeros(s: str) -> str:
    """Убрать хвостовые нули дробной части и, если она пуста, точку (как KiCad)."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _no_exponent(s: str) -> str:
    """Запись ``%g`` с экспонентой -> десятичная без экспоненты (те же значащие цифры)."""
    return _strip_fraction_zeros(format(Decimal(s), "f"))


def _check_finite(value: float) -> float:
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        raise ValueError("число должно быть конечным")
    return v


def format_number(value: float) -> str:
    """Длина/координата в формате KiCad: без экспоненты, без хвостовых нулей, целые без точки.

    Воспроизводит путь значения в KiCad: мм → внутренние единицы
    ``KiROUND(v * 1e6)`` (нанометры; половина округляется **от нуля**, как в
    ``parseBoardUnits``: ``0.0000005`` → ``0.000001``, ``210.1910385`` → ``210.191039``)
    → ``EDA_UNIT_UTILS::FormatInternalUnits``: ``%.10g``, а для ``|v| <= 1e-4`` —
    ``%.10f`` с обрезкой нулей. ``-0`` записывается как ``0``. Для значений вне
    диапазона KiCad (``|v| >= 1e10`` мм) экспонента заменяется десятичной записью
    (KiCad такие числа ограничивает ±2147 мм).
    """
    v = _check_finite(value)
    if abs(v) >= 1e15:  # далеко за пределами int32 нм KiCad; v * 1e6 может переполниться
        return _strip_fraction_zeros("%.6f" % v)
    iu = _kiround(v * 1e6)
    if iu == 0:
        return "0"
    eng = iu / 1e6
    if abs(eng) <= 0.0001:
        return _strip_fraction_zeros("%.10f" % eng)
    s = "%.10g" % eng
    if "e" in s:
        s = _strip_fraction_zeros("%.6f" % eng)
    return s


def format_angle(value: float) -> str:
    """Угол в градусах как ``EDA_UNIT_UTILS::FormatAngle``: ``%.10g`` без округления до 1e-6.

    Угол не нормализуется и не округляется до нанометров (в KiCad это ``double``):
    ``12.3456789`` → ``12.3456789``, ``360/7`` → ``51.42857143``. Отличия от KiCad,
    принятые по контракту: ``-0`` → ``0``; экспонента, которую ``%.10g`` дала бы для
    ``|v| < 1e-4`` или ``|v| >= 1e10`` (``1e-05``), заменяется десятичной записью
    (``0.00001``) — KiCad читает обе формы.
    """
    v = _check_finite(value)
    if v == 0:
        return "0"
    s = "%.10g" % v
    if "e" in s:
        s = _no_exponent(s)
    return s


def format_double(value: float) -> str:
    """Безразмерное число как ``FormatDouble2Str`` KiCad (string_utils.cpp).

    Так KiCad пишет коэффициенты и 3D-параметры: ``roundrect_rratio``,
    ``chamfer_ratio``, ``solder_paste_margin_ratio``/``solder_paste_ratio``,
    ``line_spacing``, ``(xyz …)`` в ``offset``/``scale``/``rotate`` модели:
    ``%.10g`` без округления до нанометров (``0.2083333333``), а для
    ``0 < |v| <= 1e-4`` — ``%.16f`` с обрезкой нулей. Отличия от KiCad: ``-0`` → ``0``
    (KiCad пишет ``-0``), экспонента для ``|v| >= 1e10`` заменяется десятичной записью.
    """
    v = _check_finite(value)
    if v == 0:
        return "0"
    if abs(v) <= 0.0001:
        s = _strip_fraction_zeros("%.16f" % v)
        return "0" if s in ("0", "-0") else s
    s = "%.10g" % v
    if "e" in s:
        s = _no_exponent(s)
    return s


def quote(s: str) -> str:
    """Строка в кавычках с экранированием как ``OUTPUTFORMATTER::Quotes`` KiCad.

    Экранируются только ``\\``, ``"``, перевод строки и возврат каретки.
    """
    if "\\" in s:
        s = s.replace("\\", "\\\\")
    if '"' in s:
        s = s.replace('"', '\\"')
    if "\n" in s:
        s = s.replace("\n", "\\n")
    if "\r" in s:
        s = s.replace("\r", "\\r")
    return '"' + s + '"'


_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "a": "\x07", "b": "\x08", "f": "\x0c",
                   "n": "\n", "r": "\r", "t": "\t", "v": "\x0b"}
_HEX_ESCAPE_RE = re.compile(r"[0-9a-fA-F]{1,2}")
_OCT_ESCAPE_RE = re.compile(r"[0-7]{1,3}")


def unquote(s: str) -> str:
    """Снять кавычки и экранирование по правилам ``DSNLEXER`` KiCad.

    Поддерживаются ``\\"``, ``\\\\``, ``\\a \\b \\f \\n \\r \\t \\v``, ``\\xHH`` (1–2 hex-цифры)
    и восьмеричные ``\\ooo`` (1–3 цифры); «испорченные» последовательности
    интерпретируются как в KiCad (``\\x`` без цифр → ``x``, ``\\`` перед прочим символом → ``\\``).
    Как и в KiCad, ``\\xHH``/``\\ooo`` задают **байты** UTF-8, а не кодовые точки:
    ``"\\xC3\\xA9"`` → ``"é"`` (см. :func:`_unescape`).
    """
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return _unescape(s)


def _unescape(body: str) -> str:
    """Разобрать escape-последовательности тела строки (без кавычек) как ``DSNLEXER::NextTok``.

    KiCad собирает строку как ``std::string`` байтов (``\\xHH`` и ``\\ooo`` дают по одному
    байту, восьмеричное значение усекается до 8 бит) и затем декодирует её как UTF-8
    (``wxString::FromUTF8``). Здесь то же самое. Отличия, принятые намеренно: байтовая
    последовательность, не являющаяся корректным UTF-8, не превращается в пустую строку
    (как у ``FromUTF8``), а декодируется побайтно как latin-1; байт ``0`` не обрезает
    строку (в KiCad ``FromUTF8(c_str())`` отбросил бы всё после него).
    """
    if "\\" not in body:
        return body
    parts: list[str | int] = []   # str — готовый текст, int — байт из \x/\ooo
    high = False                  # был ли байт >= 0x80 (тогда нужна сборка UTF-8)
    i, n = 0, len(body)
    while i < n:
        j = body.find("\\", i)
        if j < 0:
            parts.append(body[i:])
            break
        if j > i:
            parts.append(body[i:j])
        i = j + 1
        if i >= n:  # одиночная «\» в самом конце (в файле невозможна: экранирует кавычку)
            parts.append("\\")
            break
        e = body[i]
        simple = _SIMPLE_ESCAPES.get(e)
        if simple is not None:
            parts.append(simple)
            i += 1
        elif e == "x":
            m = _HEX_ESCAPE_RE.match(body, i + 1)
            if m:
                b = int(m.group(), 16)
                parts.append(b)
                high = high or b >= 0x80
                i = m.end()
            else:  # «испорченная» hex-последовательность — буква x
                parts.append("x")
                i += 1
        else:
            m = _OCT_ESCAPE_RE.match(body, i)
            if m:
                b = int(m.group(), 8) & 0xFF
                parts.append(b)
                high = high or b >= 0x80
                i = m.end()
            else:  # «испорченная» восьмеричная — сама «\», символ после неё обычный
                parts.append("\\")
    if not high:
        return "".join(chr(p) if isinstance(p, int) else p for p in parts)
    try:
        data = b"".join(bytes((p,)) if isinstance(p, int) else p.encode("utf-8", "surrogateescape")
                        for p in parts)
    except UnicodeEncodeError:  # одиночные суррогаты в тексте — без сборки байтов
        return "".join(chr(p) if isinstance(p, int) else p for p in parts)
    return _decode_utf8_lenient(data)


def _decode_utf8_lenient(data: bytes) -> str:
    """UTF-8 -> str; некорректные байты (KiCad дал бы пустую строку) — как latin-1."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        s = data.decode("utf-8", "surrogateescape")
        return "".join(chr(ord(c) - 0xDC00) if "\udc80" <= c <= "\udcff" else c for c in s)


def atom_text(atom: Atom) -> str:
    """Текст атома для записи: :class:`Str` — в кавычках с экранированием, :class:`Sym` — как есть."""
    if isinstance(atom, Str):
        return quote(atom)
    return str(atom)


# ---------------------------------------------------------------------------
# Разбор
# ---------------------------------------------------------------------------

class SexprSyntaxError(ValueError):
    """Синтаксическая ошибка S-выражения с позицией (строка и позиция — с 1)."""

    def __init__(self, msg: str, line: int, col: int) -> None:
        self.msg = msg
        self.line = line
        self.col = col
        super().__init__(f"строка {line}, позиция {col}: {msg}")


# Лексика DSNLEXER (common/dsnlexer.cpp, режим KiCad, не specctra):
# * пробельные символы (isSpace) — только « », \t, \n, \r и \0; \v, \f и прочие символы —
#   часть голого токена;
# * голый токен — всё до пробельного символа или скобки; кавычка внутри него — обычный
#   символ (``ab"c`` — один символ), а в начале токена открывает строку;
# * строка в кавычках не может содержать перевод строки, в том числе после «\»
#   (``"a\`` + перевод строки — «Un-terminated delimited string»);
# * строка, первым непробельным символом которой является «#», — комментарий (целиком),
#   где бы она ни стояла; комментарий после других токенов той же строки невозможен.
# Символ «|» (DSN_BAR, известен лексеру для файлов версии >= 20240706 — данные
# embedded_files) здесь не выделяется в отдельный токен: он остаётся частью голого
# символа, поэтому исходный текст таких данных воспроизводится без изменений.
_TOKEN_RE = re.compile(
    r'(\n)'                                       # 1: перевод строки
    r'|(\()'                                      # 2: открывающая скобка
    r'|(\))'                                      # 3: закрывающая скобка
    r'|("[^"\\\n]*(?:\\[^\n][^"\\\n]*)*")'        # 4: строка в кавычках
    r'|([^ \t\r\n\0()"][^ \t\r\n\0()]*)'          # 5: голый символ (включая числа)
    r'|(")'                                       # 6: незакрытая строка
)
_COMMENT_LINE_RE = re.compile(r'^[ \t\r\0]*#[^\n]*', re.M)


def _blank_comments(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Заменить строки-комментарии пробелами той же длины (позиции не сдвигаются).

    Возвращает новый текст и список ``(смещение, строка комментария)``; строка
    хранится целиком, с начальными пробелами, без завершающих CR/LF — как
    ``DSNLEXER::ReadCommentLines``.
    """
    found = [(m.start(), m.group()) for m in _COMMENT_LINE_RE.finditer(text)]
    if not found:
        return text, []
    pieces: list[str] = []
    pos = 0
    for start, body in found:
        pieces.append(text[pos:start])
        pieces.append(" " * len(body))
        pos = start + len(body)
    pieces.append(text[pos:])
    return "".join(pieces), [(start, body.rstrip("\r\n")) for start, body in found]


def parse(text: str) -> Node:
    """Разобрать текст с ровно одним корневым узлом.

    Допускаются BOM в начале текста (намеренное послабление: KiCad 10 такой файл не
    открывает, :func:`dumps` BOM не пишет), CRLF, строки-комментарии (``#`` первым
    непробельным символом строки; комментарии перед корнем сохраняются в
    ``Node.comments``). Ошибки:
    пустой ввод, незакрытая/лишняя скобка, незакрытая строка (строка в кавычках не
    может переноситься на другую строку — как в KiCad), данные после корневого узла.
    Лексика — как у ``DSNLEXER`` KiCad (см. комментарий к ``_TOKEN_RE``).
    """
    roots = parse_all(text)
    if not roots:
        raise SexprSyntaxError("пустой ввод: нет ни одного S-выражения", 1, 1)
    if len(roots) > 1:
        raise SexprSyntaxError("лишние данные после корневого узла", roots[1].line, roots[1].col)
    return roots[0]


def _new_node(name: str, line: int, col: int) -> Node:
    """Быстрое создание пустого узла при разборе (без приведения элементов)."""
    node = Node.__new__(Node)
    node.name = name
    node.items = []
    node.line = line
    node.col = col
    node.comments = []
    return node


def parse_all(text: str) -> list[Node]:
    """Разобрать текст с произвольным числом корневых узлов (атомы вне скобок — ошибка).

    Имя узла — первый токен после «(», он может стоять и на следующей строке
    (между ними допустимы пробелы, переводы строк и строки-комментарии), но не может
    быть строкой в кавычках или скобкой. Комментарии, стоящие до первого токена,
    сохраняются в ``comments`` первого корня.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    comments: list[tuple[int, str]] = []
    if "#" in text:
        text, comments = _blank_comments(text)
    roots: list[Node] = []
    stack: list[Node] = []
    line, line_start = 1, 0
    pending: tuple[int, int, int] | None = None  # (строка, позиция, смещение) «(» без имени
    for m in _TOKEN_RE.finditer(text):
        k = m.lastindex
        if k == 5:  # голый символ — самый частый токен
            if pending is not None:
                node = _new_node(m.group(5), pending[0], pending[1])
                if stack:
                    stack[-1].items.append(node)
                elif comments and not roots:
                    # начальные комментарии: строки до первого токена файла (ReadCommentLines)
                    node.comments = [c for pos, c in comments if pos < pending[2]]
                pending = None
                stack.append(node)
            elif stack:
                stack[-1].items.append(Sym(m.group(5)))
            else:
                raise SexprSyntaxError("данные вне корневого узла", line, m.start() - line_start + 1)
        elif k == 2:
            start = m.start()
            if pending is not None:
                raise SexprSyntaxError("ожидалось имя узла после «(»", line, start - line_start + 1)
            pending = (line, start - line_start + 1, start)
        elif k == 3:
            if pending is not None or not stack:
                raise SexprSyntaxError("ожидалось имя узла после «(»" if pending is not None
                                       else "лишняя закрывающая скобка", line, m.start() - line_start + 1)
            node = stack.pop()
            if not stack:
                roots.append(node)
        elif k == 1:
            line += 1
            line_start = m.end()
        elif k == 4:
            if pending is not None or not stack:
                raise SexprSyntaxError("имя узла не может быть строкой в кавычках" if pending is not None
                                       else "данные вне корневого узла", line, m.start() - line_start + 1)
            body = m.group(4)[1:-1]
            stack[-1].items.append(Str(_unescape(body) if "\\" in body else body))
        else:  # k == 6: кавычка без пары на той же строке
            raise SexprSyntaxError("незакрытая строка в кавычках", line, m.start() - line_start + 1)
    end_col = max(1, len(text) - line_start + 1)
    if pending is not None:
        raise SexprSyntaxError("ожидалось имя узла после «(»", line, end_col)
    if stack:
        top = stack[-1]
        at_end = f"узел «{top.name}» (открыт в строке {top.line}, позиция {top.col})"
        hint = _unclosed_hint(text)
        if hint is not None and (hint[1], hint[2]) != (top.line, top.col):
            name, h_line, h_col, next_line = hint
            raise SexprSyntaxError(
                f"незакрытая скобка: не закрыт узел «{name}» (строка {next_line} начинается на "
                f"том же уровне отступа, что и строка узла); в конце файла (строка {line}) "
                f"остался незакрытым {at_end}", h_line, h_col)
        raise SexprSyntaxError(f"незакрытая скобка: {at_end}", line, end_col)
    return roots


def _unclosed_hint(text: str) -> tuple[str, int, int, int] | None:
    """Где, судя по отступам, пропущена закрывающая скобка (для сообщения об ошибке).

    Лишняя незакрытая скобка «сдвигает» все следующие закрывающие, и к концу файла открытым
    остаётся корень — место ошибки по одной скобочной структуре не найти. KiCad пишет файлы
    с отступами по вложенности, поэтому первая строка, которая начинается с «(» на отступе
    не больше отступа строки, где открыт ещё не закрытый узел, указывает на этот узел.
    Возвращает ``(имя, строка, позиция, строка-признак)`` самого вложенного такого узла или
    ``None`` (файл в одну строку, отступы не согласуются). Вызывается только при ошибке."""
    stack: list[tuple[str, int, int, int]] = []   # имя, строка, позиция, отступ строки
    line, line_start = 1, 0
    first = True       # следующий токен — первый в строке
    indent = 0         # отступ текущей строки
    pending: tuple[int, int] | None = None
    for m in _TOKEN_RE.finditer(text):
        k = m.lastindex
        if k == 1:
            line += 1
            line_start = m.end()
            first = True
            continue
        if first:
            first = False
            indent = m.start() - line_start
            if k == 2:
                late = [e for e in stack if e[1] < line and e[3] >= indent]
                if late:
                    name, n_line, n_col, _ = late[-1]
                    return name, n_line, n_col, line
        if k == 2:
            pending = (line, m.start() - line_start + 1)
        elif k == 5 and pending is not None:
            stack.append((m.group(5), pending[0], pending[1], indent))
            pending = None
        elif k == 3:
            pending = None
            if stack:
                stack.pop()
    return None


# ---------------------------------------------------------------------------
# Запись: компактная форма и Prettify (KiCad 8/9/10)
# ---------------------------------------------------------------------------

def to_compact(node: Node) -> str:
    """Узел в одну строку без переводов: ``(name a b(sub c)(sub2 d))``.

    Именно так печатает writer KiCad перед вызовом ``Prettify`` (вызовы ``Print``
    просто конкатенируются); все пробелы затем нормализует :func:`prettify`.
    """
    parts: list[str] = []
    _compact_into(node, parts)
    return "".join(parts)


def _compact_into(node: Node, parts: list[str], mask: tuple[str, str] | None = None) -> bool:
    """Компактная запись в ``parts``; возвращает, есть ли в голых символах «"» или «\\».

    С ``mask=(q, b)`` эти символы в голых токенах (и именах узлов) заменяются на
    однобайтовые заменители ``q``/``b`` — см. :func:`_prettify_tree`.
    """
    tricky = False
    name = node.name
    if '"' in name or "\\" in name:
        tricky = True
        if mask is not None:
            name = name.replace('"', mask[0]).replace("\\", mask[1])
    parts.append("(" + name)
    for x in node.items:
        if isinstance(x, Node):
            tricky = _compact_into(x, parts, mask) or tricky
        elif isinstance(x, Str):
            parts.append(" " + quote(x))
        elif '"' in x or "\\" in x:
            tricky = True
            parts.append(" " + (x if mask is None else x.replace('"', mask[0]).replace("\\", mask[1])))
        else:
            parts.append(" " + x)
    parts.append(")")
    return tricky


_MASK_CANDIDATES = ("\x01\x02", "\x03\x04", "\x05\x06", "\x0e\x0f", "\x10\x11", "\x12\x13",
                    "\x14\x15", "\x16\x17", "\x18\x19", "\x1a\x1b", "\x1c\x1d", "\x1e\x1f")


def _prettify_tree(node: Node, compact_save: bool = False) -> str:
    """``prettify(to_compact(node))`` без искажения дерева.

    Prettify отслеживает строки по кавычкам и «\\» в тексте. Голые символы с «"» или
    «\\» внутри (``q"r``, ``x\\`` — DSNLEXER читает их как символы; KiCad сам такие не
    пишет, но в файле они возможны) сбивали это отслеживание, и пробелы внутри
    следующих строк в кавычках схлопывались или заменялись переводом строки. Такие
    символы на время Prettify заменяются однобайтовыми заменителями (колонки не
    сдвигаются), которых нет в тексте, и возвращаются после.
    """
    parts: list[str] = []
    if not _compact_into(node, parts):
        return prettify("".join(parts), compact_save=compact_save)
    plain = "".join(parts)
    for cand in _MASK_CANDIDATES:
        q, b = cand
        if q not in plain and b not in plain:
            break
    else:  # pragma: no cover - в тексте все управляющие символы-кандидаты
        return prettify(plain, compact_save=compact_save)
    masked: list[str] = []
    _compact_into(node, masked, (q, b))
    out = prettify("".join(masked), compact_save=compact_save)
    return out.replace(q, '"').replace(b, "\\")


_SHORT_FORM_9 = frozenset(("font", "stroke", "fill", "offset", "rotate", "scale"))
_SHORT_FORM_10 = frozenset(("font", "stroke", "fill", "teardrop", "offset", "rotate", "scale"))


def prettify(source: str, compact_save: bool = False, mode: str = "9.0") -> str:
    """Порт ``KICAD_FORMAT::Prettify`` (common/io/kicad/kicad_io_utils.cpp) 1:1.

    ``source`` — вывод writer'а (например :func:`to_compact`). Алгоритм работает с
    байтами (колонки считаются в байтах UTF-8), поэтому текст перекодируется через
    latin-1. ``compact_save`` — ``ADVANCED_CFG::m_CompactSave`` (по умолчанию выключен
    в KiCad); ``mode`` — ``"8.0"``, ``"9.0"`` или ``"10"``: в 8.0 нет коротких форм,
    а первая «(» печатается без перевода строки при ``listDepth == 0`` (в 9.0/10 — только
    в самом начале вывода); в 10 к коротким формам добавлен ``teardrop``.
    """
    src = source.encode("utf-8", "surrogatepass").decode("latin-1")
    out = _prettify_bytes_as_str(src, compact_save, mode)
    return out.encode("latin-1").decode("utf-8", "surrogatepass")


# Серии символов, которые Prettify копирует без изменения состояния (кроме колонки):
# вне кавычек — всё, кроме пробельных символов, скобок, кавычки и «\»; внутри кавычек —
# всё, кроме кавычки и «\». Пробельные символы вне кавычек обрабатываются серией целиком:
# после первого из них остальные ничего не меняют (hasInsertedSpace либо условие
# вставки не зависит от них).
_PRETTIFY_PLAIN = re.compile(r'[^ \t\n\r()"\\]+')
_PRETTIFY_QUOTED = re.compile(r'[^"\\]+')
_PRETTIFY_WS = re.compile(r"[ \t\n\r]+")


def _prettify_bytes_as_str(source: str, compact_save: bool, mode: str) -> str:
    indent_char = "\t"
    xy_limit = 99
    wrap_threshold = 72
    if mode == "8.0":
        short_forms: frozenset[str] = frozenset()
    elif mode == "9.0":
        short_forms = _SHORT_FORM_9 if compact_save else frozenset()
    else:
        short_forms = _SHORT_FORM_10 if compact_save else frozenset()
    first_paren_by_depth = mode == "8.0"  # 8.0: if( listDepth == 0 ); 9.0+: formatted.empty()

    formatted: list[str] = []
    n = len(source)
    list_depth = 0
    last_non_ws = "\0"
    in_quote = False
    has_inserted_space = False
    in_multi_line_list = False
    in_xy = False
    in_short_form = False
    short_form_depth = 0
    column = 0
    backslash_count = 0
    plain_match = _PRETTIFY_PLAIN.match
    quoted_match = _PRETTIFY_QUOTED.match
    ws_match = _PRETTIFY_WS.match

    i = 0
    while i < n:
        c = source[i]
        if in_quote:
            m = quoted_match(source, i)
        elif c in " \t\n\r":
            j = ws_match(source, i).end()
            nxt = source[j] if j < n else "\0"
            if (not has_inserted_space and list_depth > 0 and last_non_ws != "("
                    and nxt != ")" and nxt != "("):
                if in_xy or column < wrap_threshold:
                    formatted.append(" ")
                    column += 1
                elif in_short_form:
                    formatted.append(" ")
                else:
                    formatted.append("\n" + indent_char * list_depth)
                    column = list_depth
                    in_multi_line_list = True
                has_inserted_space = True
            i = j
            continue
        else:
            m = plain_match(source, i)
        if m is not None:  # серия обычных символов
            run = m.group()
            formatted.append(run)
            column += len(run)
            last_non_ws = run[-1]
            backslash_count = 0
            has_inserted_space = False
            i = m.end()
            continue
        # одиночный особый символ: «(» / «)» вне кавычек, «"», «\»
        has_inserted_space = False
        if c == "(" and not in_quote:
            current_is_xy = source.startswith("xy ", i + 1)
            current_is_short = False
            if short_forms:
                j = i + 1
                while j < n and source[j].isascii() and source[j].isalpha():
                    j += 1
                current_is_short = source[i + 1:j] in short_forms
            if (list_depth == 0) if first_paren_by_depth else (not formatted):
                formatted.append("(")
                column += 1
            elif in_xy and current_is_xy and column < xy_limit:
                formatted.append(" (")
                column += 2
            elif in_short_form:
                formatted.append(" (")
                column += 2
            else:
                formatted.append("\n" + indent_char * list_depth + "(")
                column = list_depth + 1
            in_xy = current_is_xy
            if current_is_short:
                in_short_form = True
                short_form_depth = list_depth
            list_depth += 1
        elif c == ")" and not in_quote:
            if list_depth > 0:
                list_depth -= 1
            if in_short_form:
                formatted.append(")")
                column += 1
            elif last_non_ws == ")" or in_multi_line_list:
                formatted.append("\n" + indent_char * list_depth + ")")
                column = list_depth + 1
                in_multi_line_list = False
            else:
                formatted.append(")")
                column += 1
            if short_form_depth == list_depth:
                in_short_form = False
                short_form_depth = 0
        else:  # «"» или «\» — учёт экранирования кавычки (как в KiCad: \\" закрывает строку)
            if c == "\\":
                backslash_count += 1
            else:
                if (backslash_count & 1) == 0:
                    in_quote = not in_quote
                backslash_count = 0
            formatted.append(c)
            column += 1
        last_non_ws = c
        i += 1
    formatted.append("\n")
    return "".join(formatted)


# ---------------------------------------------------------------------------
# Запись: раскладка writer'ов KiCad 5.1 / 6.0 / 7.0 (табличная)
# ---------------------------------------------------------------------------

_IND = "  "  # OUTPUTFORMATTER::Print: NESTWIDTH = 2 пробела на уровень
# Ночные сборки 5.99 (например, версия 20210722 в kicad-footprints 6.0.0) печатали
# «(layer …)» в первой строке заголовка; writer 6.0.0 (20211014) — со второй строки.
# Точная версия изменения неизвестна: порог выбран по последней наблюдаемой версии.
_V6_HEADER_NEWLINE = 20211014

# дочерние узлы pad, которые writer 6.0/7.0 выносит на вторую строку
_PAD_SECOND_LINE = frozenset((
    "net", "pinfunction", "pintype", "die_length", "solder_mask_margin", "solder_paste_margin",
    "solder_paste_margin_ratio", "clearance", "zone_connect", "thermal_width", "thermal_gap",
    "thermal_bridge_width", "thermal_bridge_angle",
))
_PAD_CHAMFER_LINE = frozenset(("chamfer_ratio", "chamfer"))
_ONE_LINE_SHAPES = frozenset(("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_curve",
                              "gr_line", "gr_rect", "gr_circle", "gr_arc", "gr_curve"))


def _inline(node: Node | Atom, writer: str) -> str:
    """Узел в одну строку с одиночными пробелами (формат-строки ``Print`` writer'ов 5–7)."""
    if not isinstance(node, Node):
        return atom_text(node)
    parts = [node.name] + [_inline(x, writer) for x in node.items]
    s = "(" + " ".join(parts) + ")"
    if writer == "5.1" and node.name == "rect_delta":
        s = s[:-1] + " )"  # особенность writer'а 5.1: " (rect_delta %s )"
    return s


def _same_tree(a: Node, b: Node) -> bool:
    """Точное совпадение деревьев: имена, порядок, типы (Sym/Str) и тексты атомов."""
    if a.name != b.name or len(a.items) != len(b.items):
        return False
    for x, y in zip(a.items, b.items):
        if isinstance(x, Node):
            if not isinstance(y, Node) or not _same_tree(x, y):
                return False
        elif isinstance(y, Node) or type(x) is not type(y) or x != y:
            return False
    return True


def _fragment_matches(text: str, node: Node) -> bool:
    """Разбирается ли ``text`` ровно в ``node`` (проверка раскладки без потерь)."""
    try:
        roots = parse_all(text)
    except SexprSyntaxError:
        return False
    return len(roots) == 1 and _same_tree(roots[0], node)


class _LegacyLayout:
    """Эмуляция раскладки writer'ов KiCad 5.1 / 6.0 / 7.0 для файлов посадочных мест.

    Табличные правила рассчитаны на деревья в каноническом порядке KiCad. Чтобы
    изменённое или стороннее дерево не теряло и не переставляло элементы, каждый
    дочерний узел корня после раскладки разбирается обратно и сравнивается с исходным;
    при расхождении он пишется одной строкой (``_inline`` — без потерь). Заголовок
    корпуса (version/generator/флаги/layer/tedit/tstamp) выносится в первые строки,
    только если эти элементы и так стоят в дереве в таком порядке, иначе корень
    пишется в общем виде с сохранением порядка всех элементов.
    """

    def __init__(self, writer: str) -> None:
        self.w = writer
        self.out: list[str] = []

    def p(self, nest: int, s: str) -> None:
        self.out.append(_IND * nest + s)

    def root(self, node: Node) -> None:
        if node.name in ("footprint", "module"):
            self.footprint(node, 0)
        else:  # прочие корни (на будущее): общая раскладка «каждый дочерний на строке»
            self.generic(node, 0)

    def generic(self, node: Node, nest: int) -> None:
        """Общая раскладка с сохранением порядка: атомы до первого подузла — в строке
        заголовка, далее каждый элемент на своей строке (подузлы — раскладкой своего типа)."""
        items = node.items
        i = 0
        head = "(" + node.name
        while i < len(items) and not isinstance(items[i], Node):
            head += " " + atom_text(items[i])
            i += 1
        self.p(nest, head + "\n")
        for x in items[i:]:
            if isinstance(x, Node):
                self.child(x, nest + 1)
            else:
                self.p(nest + 1, atom_text(x) + "\n")
        self.p(nest, ")\n")

    def footprint(self, node: Node, nest: int) -> None:
        w = self.w
        kids = node.items
        if not kids or isinstance(kids[0], Node):
            self.generic(node, nest)
            return
        by: dict[str, list[Node]] = {}
        for k in kids:
            if isinstance(k, Node):
                by.setdefault(k.name, []).append(k)
        atoms = [a for a in kids[1:] if not isinstance(a, Node)]  # флаги locked/placed и прочие
        flags = [atom_text(a) for a in atoms]
        # элементы, которые раскладка выводит в заголовке, — в порядке вывода
        if w == "5.1":
            header = ["", "layer", "tedit", "tstamp"]              # "" — место флагов
        elif w == "6.0":
            header = ["version", "generator", "", "layer", "tedit", "tstamp"]
        else:
            header = ["version", "generator", "", "layer", "tstamp"]
        rendered: list = [kids[0]]
        for name in header:
            rendered.extend(atoms if name == "" else by.get(name, []))
        consumed = {name for name in header if name}
        rendered.extend(k for k in kids if isinstance(k, Node) and k.name not in consumed)
        if len(rendered) != len(kids) or any(a is not b for a, b in zip(rendered, kids)):
            self.generic(node, nest)
            return
        line = "(" + node.name + " " + atom_text(kids[0])
        if w == "5.1":
            for f in flags:
                line += " " + f
            for name in ("layer", "tedit", "tstamp"):
                for t in by.get(name, []):
                    line += " " + _inline(t, w)
            self.p(nest, line + "\n")
        else:
            for name in ("version", "generator"):
                for t in by.get(name, []):
                    line += " " + _inline(t, w)
            version = _root_version(node)
            if not (w == "6.0" and version is not None and version < _V6_HEADER_NEWLINE):
                line += "\n "
            for f in flags:
                line += " " + f
            for t in by.get("layer", []):
                line += " " + _inline(t, w)
            self.p(nest, line + "\n")
            if w == "6.0":
                line = " ".join(_inline(t, w) for t in by.get("tedit", []) + by.get("tstamp", []))
                if line:
                    self.p(nest + 1, line + "\n")
            else:
                for t in by.get("tstamp", []):
                    self.p(nest + 1, _inline(t, w) + "\n")
        for k in kids:
            if isinstance(k, Node) and k.name not in consumed:
                self.child(k, nest + 1)
        self.p(nest, ")\n")

    def child(self, node: Node, nest: int) -> None:
        """Дочерний узел по правилам своего типа; если результат не разбирается обратно
        в тот же узел (нестандартный порядок/состав), — одной строкой."""
        start = len(self.out)
        self._render(node, nest)
        if not _fragment_matches("".join(self.out[start:]), node):
            del self.out[start:]
            self.p(nest, _inline(node, self.w) + "\n")

    def _render(self, node: Node, nest: int) -> None:
        n = node.name
        if n == "fp_text":
            self.fp_text(node, nest)
        elif n == "fp_poly":
            self.fp_poly(node, nest)
        elif n in _ONE_LINE_SHAPES:
            self.shape(node, nest)
        elif n == "pad":
            self.pad(node, nest)
        elif n == "model":
            self.model(node, nest)
        elif n == "group":
            self.group(node, nest)
        elif n == "zone":
            self.zone(node, nest)
        elif n == "fp_text_box":
            self.fp_text_box(node, nest)
        else:
            self.p(nest, _inline(node, self.w) + "\n")

    def fp_text(self, node: Node, nest: int) -> None:
        # 5.1/6.0: EDA_TEXT::Format(aNestLevel) -> (effects на N+1; 7.0: Format(aNestLevel + 1)
        # -> (effects на N+2, а tstamp и render_cache — на N+1
        effects_nest = nest + 2 if self.w == "7.0" else nest + 1
        head, rest = [], []
        for k in node.items:
            if isinstance(k, Node) and k.name in ("effects", "tstamp", "render_cache"):
                rest.append(k)
            else:
                head.append(k)
        self.p(nest, "(fp_text " + " ".join(_inline(k, self.w) for k in head) + "\n")
        for k in rest:
            if k.name == "render_cache":
                self.render_cache(k, nest + 1)
            elif k.name == "effects":
                self.p(effects_nest, _inline(k, self.w) + "\n")
            else:
                self.p(nest + 1, _inline(k, self.w) + "\n")
        self.p(nest, ")\n")

    def fp_text_box(self, node: Node, nest: int) -> None:
        # 7.0 (pcb_plugin.cpp:2006-2051): заголовок; (start)(end) на уровне N или pts
        # (formatPolyPts(N, compact)); затем " (angle) (layer) (tstamp)"; effects на N+2;
        # stroke на N+1 без перевода строки; render_cache на N+1; ")" на N
        head = [atom_text(a) for a in node.atoms()]
        self.p(nest, "(fp_text_box " + " ".join(head) + "\n")
        line = ""
        has_pts = False
        for k in node.nodes():
            if k.name == "pts":
                self.poly_pts(k, nest, compact=True)
                has_pts = True
            elif k.name in ("start", "end", "angle", "layer", "tstamp"):
                line += (" " if line else "") + _inline(k, self.w)
        if has_pts:
            self.out.append(" " + line + "\n")
        else:
            self.p(nest, line + "\n")
        for k in node.nodes("effects"):
            self.p(nest + 2, _inline(k, self.w) + "\n")
        for k in node.nodes("stroke"):
            self.p(nest + 1, _inline(k, self.w))
        for k in node.nodes("render_cache"):
            self.render_cache(k, nest + 1)
        self.p(nest, ")\n")

    def render_cache(self, node: Node, nest: int) -> None:
        atoms = node.atoms()
        self.p(nest, "(render_cache " + " ".join(atom_text(a) for a in atoms[:2]) + "\n")
        for poly in node.nodes():
            self.p(nest + 1, "(polygon\n")
            for i, pts in enumerate(poly.nodes()):
                self.poly_pts(pts, nest + 1 if i == 0 else nest + 2, compact=True)
            self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    def shape(self, node: Node, nest: int) -> None:
        w = self.w
        if w in ("5.1", "6.0"):
            self.p(nest, _inline(node, w) + "\n")
            return
        head, tail = [], []
        for k in node.items:
            if isinstance(k, Node) and k.name in ("stroke", "fill", "layer", "tstamp"):
                tail.append(k)
            else:
                head.append(k)
        self.p(nest, "(" + node.name + " " + " ".join(_inline(k, w) for k in head) + "\n")
        self.p(nest + 1, " ".join(_inline(k, w) for k in tail) + ")\n")

    def poly_pts(self, pts: Node, nest: int, compact: bool = False) -> None:
        self.p(nest + 1, "(pts\n")
        need_nl = False
        for i, pt in enumerate(pts.items, 1):
            self.p(nest + 2, _inline(pt, self.w))
            need_nl = True
            if (i % 4 == 0) or not compact:
                self.out.append("\n")
                need_nl = False
        if need_nl:
            self.out.append("\n")
        self.p(nest + 1, ")\n")

    def fp_poly(self, node: Node, nest: int) -> None:
        w = self.w
        flags = [atom_text(a) for a in node.atoms()]
        pts = node.find("pts")
        if pts is None:
            self.p(nest, _inline(node, w) + "\n")
            return
        tail = [k for k in node.nodes() if k.name != "pts"]
        head = "(fp_poly" + "".join(" " + f for f in flags)
        if w == "5.1":
            self.out.append(_IND * nest + head + " (pts")
            for i, pt in enumerate(pts.items):
                if i and i % 4 == 0:
                    self.out.append("\n" + _IND * (nest + 1) + _inline(pt, w))
                else:
                    self.out.append(" " + _inline(pt, w))
            self.out.append(")")
            self.out.append(" " + " ".join(_inline(k, w) for k in tail) + ")\n")
        elif w == "6.0":
            self.out.append(_IND * nest + head + " (pts")
            for pt in pts.items:
                self.out.append("\n" + _IND * (nest + 2) + _inline(pt, w))
            self.out.append("\n" + _IND * (nest + 1) + ")")
            self.out.append(" " + " ".join(_inline(k, w) for k in tail) + ")\n")
        else:
            self.p(nest, head + "\n")
            self.poly_pts(pts, nest, compact=False)
            self.out.append("\n")
            self.p(nest + 1, " ".join(_inline(k, w) for k in tail) + ")\n")

    def pad(self, node: Node, nest: int) -> None:
        w = self.w
        first: list = []
        chamfer: list[Node] = []
        second: list[Node] = []
        options: Node | None = None
        prims: Node | None = None
        tstamp: list[Node] = []
        for k in node.items:
            nm = k.name if isinstance(k, Node) else ""
            if nm in _PAD_SECOND_LINE:
                second.append(k)
            elif nm in _PAD_CHAMFER_LINE:
                chamfer.append(k)
            elif nm == "options":
                options = k
            elif nm == "primitives":
                prims = k
            elif nm == "tstamp":
                tstamp.append(k)
            else:
                first.append(k)
        # Примечание: ранние сборки KiCad 5.0 печатали (roundrect_rratio …) без пробела
        # перед скобкой; 5.1 — с пробелом. По дереву это не восстановить, принят вариант 5.1.
        self.out.append(_IND * nest + "(pad " + " ".join(_inline(k, w) for k in first))
        if chamfer:
            self.out.append("\n" + _IND * (nest + 1) + " ".join(_inline(k, w) for k in chamfer))
        if second:
            self.out.append("\n" + _IND * (nest + 1) + " ".join(_inline(k, w) for k in second))
        if options is not None:
            self.out.append("\n" + _IND * (nest + 1) + _inline(options, w))
        if prims is not None:
            self.primitives(prims, nest)
        for t in tstamp:
            self.out.append(" " + _inline(t, w))
        self.out.append(")\n")

    def primitives(self, prims: Node, nest: int) -> None:
        w = self.w
        self.out.append("\n" + _IND * (nest + 1) + "(primitives")
        nested = nest + 2
        for prim in prims.nodes():
            self.out.append("\n")
            pn = prim.name
            if w == "5.1":
                if pn == "gr_poly" and prim.find("pts") is not None:
                    pts = prim.find("pts")
                    tail = [k for k in prim.nodes() if k.name != "pts"]
                    self.out.append(_IND * nested + "(gr_poly (pts\n")
                    new_line = 0
                    for pt in pts.items:  # type: ignore[union-attr]
                        if new_line == 0:
                            self.out.append(_IND * (nested + 1) + " " + _inline(pt, w))
                        else:
                            self.out.append(" " + _inline(pt, w))
                        new_line += 1
                        if new_line > 4:
                            new_line = 0
                            self.out.append("\n")
                    self.out.append(") " + " ".join(_inline(k, w) for k in tail) + ")")
                else:
                    self.out.append(_IND * nested + _inline(prim, w))
                continue
            head = [k for k in prim.items if not (isinstance(k, Node) and k.name in ("width", "fill", "pts"))]
            tail = [k for k in prim.nodes() if k.name in ("width", "fill")]
            pts = prim.find("pts")
            if pn == "gr_poly" and pts is not None:
                if w == "6.0":
                    self.out.append(_IND * nested + "(gr_poly (pts")
                    for pt in pts.items:
                        nested = nest + 4  # особенность (ошибка) writer'а 6.0
                        self.out.append("\n" + _IND * nested + _inline(pt, w))
                    self.out.append("\n" + _IND * (nest + 3) + ")")
                else:
                    self.out.append(_IND * nested + "(gr_poly\n")
                    self.poly_pts(pts, nested, compact=False)
                    self.out.append(_IND * nested + " ")
            elif pn == "gr_curve" and pts is not None:
                self.out.append(_IND * nested + "(gr_curve " + _inline(pts, w))
            elif pn == "gr_arc" and w == "6.0":
                self.out.append(_IND * nest + "(" + pn + " " + " ".join(_inline(k, w) for k in head))
            else:
                self.out.append(_IND * nested + "(" + pn + " " + " ".join(_inline(k, w) for k in head))
            for k in tail:
                self.out.append(" " + _inline(k, w))
            self.out.append(")")
        self.out.append("\n" + _IND * (nest + 1) + ")")

    def model(self, node: Node, nest: int) -> None:
        w = self.w
        head = [atom_text(a) for a in node.atoms()]
        self.p(nest, "(model " + " ".join(head) + "\n")
        for k in node.nodes():
            if k.name == "opacity":
                self.p(nest + 1, _inline(k, w))  # writer не ставит перевод строки
            else:
                self.p(nest + 1, _inline(k, w) + "\n")
        self.p(nest, ")\n")

    def group(self, node: Node, nest: int) -> None:
        head = [atom_text(a) for a in node.atoms()] + [_inline(k, self.w) for k in node.nodes("id")]
        self.p(nest, "(group " + " ".join(head) + "\n")
        for k in node.nodes("members"):
            self.p(nest + 1, "(members\n")
            for m in k.items:
                self.p(nest + 2, _inline(m, self.w) + "\n")
            self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    def zone(self, node: Node, nest: int) -> None:
        w = self.w
        line1: list = []
        rest: list[Node] = []
        for k in node.items:
            nm = k.name if isinstance(k, Node) else ""
            if not isinstance(k, Node) or nm in ("net", "net_name", "layer", "layers", "tstamp", "name", "hatch"):
                line1.append(k)
            else:
                rest.append(k)
        self.p(nest, "(zone " + " ".join(_inline(k, w) for k in line1) + "\n")
        after_min_thickness = False  # предыдущий выведенный элемент — (min_thickness …)
        for k in rest:
            nm = k.name
            if nm == "filled_areas_thickness" and after_min_thickness:
                # writer 6/7: «(min_thickness X) (filled_areas_thickness no)» в одной строке;
                # заменяется только перевод строки, добавленный после min_thickness
                self.out[-1] = " " + _inline(k, w) + "\n"
                after_min_thickness = False
                continue
            after_min_thickness = nm == "min_thickness"
            if nm == "fill":
                self.zone_fill(k, nest + 1)
            elif nm == "min_thickness":
                self.p(nest + 1, _inline(k, w))
                self.out.append("\n")
            elif nm in ("polygon", "filled_polygon"):
                self.p(nest + 1, "(" + nm + "\n")
                for sub in k.nodes():
                    if sub.name == "pts":
                        if w == "6.0":
                            self.out.append(_IND * (nest + 2) + "(pts")
                            for pt in sub.items:
                                self.out.append("\n" + _IND * (nest + 3) + _inline(pt, w))
                            self.out.append("\n" + _IND * (nest + 2) + ")\n")
                        else:
                            self.poly_pts(sub, nest + 1, compact=False)
                    else:
                        self.p(nest + 2, _inline(sub, w) + "\n")
                self.p(nest + 1, ")\n")
            else:
                self.p(nest + 1, _inline(k, w) + "\n")
        self.p(nest, ")\n")

    def zone_fill(self, node: Node, nest: int) -> None:
        w = self.w
        line = "(fill"
        extra: list[Node] = []
        for k in node.items:
            if isinstance(k, Node) and k.name.startswith("hatch_"):
                extra.append(k)
            else:
                line += " " + _inline(k, w)
        self.out.append(_IND * nest + line)
        if extra:
            groups: list[list[Node]] = [[], [], []]
            for k in extra:
                gi = 0 if k.name in ("hatch_thickness", "hatch_gap", "hatch_orientation") else \
                    1 if k.name.startswith("hatch_smoothing") else 2
                groups[gi].append(k)
            for g in groups:
                if g:
                    self.out.append("\n" + _IND * (nest + 1) + " ".join(_inline(k, w) for k in g))
        self.out.append(")\n")


# ---------------------------------------------------------------------------
# dumps
# ---------------------------------------------------------------------------

STYLE_KICAD8 = "kicad8"
STYLE_KICAD7 = "kicad7"
STYLE_KICAD6 = "kicad6"
STYLE_KICAD5 = "kicad5"
PRETTIFY_MIN_VERSION = 20231014  # «V8 file format normalization»


def style_for_version(version: int | None, root: str = "footprint") -> str:
    """Стиль форматирования по версии формата файла (см. format-layout.md §4.1).

    * корень ``module`` → ``kicad5`` (writer 5.1);
    * корень ``footprint`` без версии или с версией < 20221018 → ``kicad6`` (writer 6.0;
      для ночных 5.99 с версией < 20211014 — заголовок в одну строку);
    * < 20231014 → ``kicad7`` (writer 7.0);
    * иначе (и для прочих корней без версии) → ``kicad8`` (Prettify KiCad 8/9/10).
    """
    if root == "module":
        return STYLE_KICAD5
    if version is None:
        return STYLE_KICAD8 if root != "footprint" else STYLE_KICAD6
    if version >= PRETTIFY_MIN_VERSION:
        return STYLE_KICAD8
    if version >= 20221018:
        return STYLE_KICAD7
    return STYLE_KICAD6


def _root_version(node: Node) -> int | None:
    v = node.value("version")
    if v is None:
        return None
    try:
        return int(str(v))
    except ValueError:
        return None


_HASH_AT_LINE_START = re.compile(r"\n[ \t]*(?=#)")


def dumps(node: Node, *, style: str = "auto", version: int | None = None,
          compact: bool = False) -> str:
    """Записать дерево в текст в стиле KiCad.

    ``style``: ``"auto"`` — по версии (``version`` или токен ``version`` в узле);
    ``"kicad8"`` — Prettify; ``"kicad7"``/``"kicad6"``/``"kicad5"`` — раскладка
    соответствующего writer'а. ``compact`` — ``compact_save`` для Prettify.
    Результат оканчивается переводом строки; переводы строк — LF.
    Комментарии ``Node.comments`` выводятся перед корнем.
    """
    if style == "auto":
        style = style_for_version(version if version is not None else _root_version(node), node.name)
    if style == STYLE_KICAD8:
        body = _prettify_tree(node, compact_save=compact)
    elif style in (STYLE_KICAD7, STYLE_KICAD6, STYLE_KICAD5):
        writer = {STYLE_KICAD7: "7.0", STYLE_KICAD6: "6.0", STYLE_KICAD5: "5.1"}[style]
        lay = _LegacyLayout(writer)
        lay.root(node)
        body = "".join(lay.out)
    elif style == "compact":
        body = to_compact(node) + "\n"
    else:
        raise ValueError(f"неизвестный стиль форматирования: {style!r}")
    if "#" in body:
        # голый символ на «#» в начале строки (перенос Prettify по колонке 72 или атом на
        # своей строке) при чтении стал бы комментарием (DSNLEXER) и потерялся бы; KiCad
        # такие символы сам не пишет (всегда в кавычках), но из файла они возможны —
        # присоединяем их к предыдущей строке (строки в кавычках не бывают многострочными)
        body = _HASH_AT_LINE_START.sub(" ", body)
    if node.comments:
        body = "".join(c + "\n" for c in node.comments) + body
    return body


# ---------------------------------------------------------------------------
# Сравнение деревьев
# ---------------------------------------------------------------------------

def _atoms_equal(a: Atom, b: Atom, tol: float, ignore_quotes: bool) -> bool:
    """Сравнение атомов (см. :func:`equal`)."""
    a_quoted = isinstance(a, Str)
    b_quoted = isinstance(b, Str)
    if a_quoted != b_quoted and not ignore_quotes:
        return False
    if str(a) == str(b):
        return True
    # Строка в кавычках для лексера KiCad — всегда DSN_STRING, а не число: номера площадок
    # "01" и "1", тексты "1e3" и "1000" различны. Допуск — только для двух голых чисел.
    if not a_quoted and not b_quoted and is_number(a) and is_number(b):
        return abs(float(a) - float(b)) <= tol
    return False


def equal(a: Node, b: Node, *, numeric_tol: float = 1e-6, ignore_quotes: bool = True) -> bool:
    """Равны ли деревья по содержанию (числа — с допуском, форма записи не учитывается).

    Имена узлов равны, элементы попарно равны. Атомы: два голых символа (:class:`Sym`),
    оба числа по правилам лексера KiCad, сравниваются с допуском ``numeric_tol``;
    во всех остальных случаях — точное совпадение текста. Строка в кавычках
    (:class:`Str`) числом не считается никогда (в KiCad это всегда ``DSN_STRING``):
    ``(pad "01")`` и ``(pad "1")``, ``"1e3"`` и ``"1000"`` различны. Отклонение от буквы
    контракта (architecture.md §3: «если оба разбираются как числа — с допуском»): там
    не оговорены строки в кавычках, а допуск для них скрывал бы перенумерацию площадок
    и порчу текстов. ``ignore_quotes=True`` — ``Sym("1") == Str("1")`` (сравнивается
    только текст, без допуска); ``False`` — ещё и форма записи (в кавычках или нет).
    """
    if a.name != b.name or len(a.items) != len(b.items):
        return False
    for x, y in zip(a.items, b.items):
        if isinstance(x, Node) or isinstance(y, Node):
            if not (isinstance(x, Node) and isinstance(y, Node)):
                return False
            if not equal(x, y, numeric_tol=numeric_tol, ignore_quotes=ignore_quotes):
                return False
        elif not _atoms_equal(x, y, numeric_tol, ignore_quotes):
            return False
    return True


def diff(a: Node, b: Node, path: str = "", *, numeric_tol: float = 1e-6,
         ignore_quotes: bool = True, limit: int = 50) -> list[str]:
    """Список человекочитаемых расхождений между деревьями (пусто — деревья равны).

    Путь элемента записывается как ``footprint/pad[3]/size``; индекс — порядковый номер
    среди одноимённых дочерних узлов.
    """
    out: list[str] = []
    _diff_into(a, b, path or a.name, out, numeric_tol, ignore_quotes, limit)
    return out


def _diff_into(a: Node, b: Node, path: str, out: list[str], tol: float, iq: bool, limit: int) -> None:
    if len(out) >= limit:
        return
    if a.name != b.name:
        out.append(f"{path}: имя узла {a.name!r} != {b.name!r}")
        return
    if len(a.items) != len(b.items):
        out.append(f"{path}: число элементов {len(a.items)} != {len(b.items)}")
    counters: dict[str, int] = {}
    for i, (x, y) in enumerate(zip(a.items, b.items)):
        if len(out) >= limit:
            return
        if isinstance(x, Node) and isinstance(y, Node):
            k = counters.get(x.name, 0)
            counters[x.name] = k + 1
            _diff_into(x, y, f"{path}/{x.name}[{k}]", out, tol, iq, limit)
        elif isinstance(x, Node) or isinstance(y, Node):
            out.append(f"{path}: элемент {i}: {x!r} != {y!r}")
        elif not _atoms_equal(x, y, tol, iq):
            out.append(f"{path}: атом {i}: {atom_text(x)} != {atom_text(y)}")
