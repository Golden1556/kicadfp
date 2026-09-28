"""Интерфейс командной строки ``kicadfp`` (architecture.md §13; ТЗ 4.1.7, приложение В.3).

Запуск: ``kicadfp <команда> …`` (точка входа ``kicadfp.cli:main``) или
``python -m kicadfp <команда> …``; ``kicadfp --version`` печатает ``kicadfp X.Y.Z``.
:func:`main` принимает аргументы без имени программы и возвращает код возврата;
``SystemExit`` наружу не выходит (функцию можно вызывать из Python и тестов).

Команды
-------

=============================  =============================================================
``info PATH``                  сводка: имя, формат, генератор, слой, площадки по типам, слои,
                               габариты, число графики/текстов/моделей (``--json``)
``list LIB``                   имена корпусов библиотеки (``--json``)
``validate PATH``              замечания ``LEVEL CODE: message`` (``--strict``, ``--json``)
``set PATH SELECTOR VALUE``    изменить свойство (``--write`` | ``-o OUT``; ``--strict``)
``pads PATH``                  таблица площадок (``--json``)
``gen KIND [--ПАРАМЕТР …]``    типовой корпус (``-o``, ``--params``, ``--name``, ``--list``)
``fmt PATH``                   каноническое форматирование KiCad (``--check`` | ``--write`` |
                               ``-o``; ``--style``)
``convert IN.mod``             старая библиотека ``.mod`` -> каталог ``.pretty`` (``-o``)
``render PATH``                изображение SVG/PNG (``-o``, ``--layers``, ``--scale`` …)
``gui [PATH]``                 графический интерфейс (нужен PySide6)
=============================  =============================================================

PATH — файл ``.kicad_mod`` (KiCad 5–10), каталог ``.pretty`` (команда применяется ко всем
корпусам библиотеки, ``--fp ИМЯ`` — только к одному) или библиотека старого формата
``.mod`` (только чтение: ``info``, ``list``, ``validate``, ``pads``, ``render``; корпуса
показываются такими, какими их делает :func:`kicadfp.legacy.read_library`).

Коды возврата
-------------

* ``0`` — успешно (``validate``: нет ошибок, с ``--strict`` — и предупреждений;
  ``fmt --check``: все файлы уже в каноническом виде);
* ``1`` — замечания или различия: ``validate`` нашла ошибки (с ``--strict`` — и
  предупреждения); ``fmt --check`` нашла файлы, требующие форматирования; ``set``/``gen``
  с ``--strict`` не записали результат, потому что проверка нашла ошибки;
* ``2`` — ошибка входных данных: синтаксическая ошибка файла (``ошибка: <файл>: строка N,
  позиция M: …``), файл не найден, неверные аргументы или значение, селектор не нашёл
  элементов, нет PySide6 для PNG/GUI. Непредвиденная (внутренняя) ошибка тоже даёт 2 и
  одну строку сообщения; трассировка — с переменной окружения ``KICADFP_DEBUG=1``.

Вывод: результат — в stdout, сообщения и предупреждения — в stderr. Текст файла (``set``,
``fmt``, ``gen`` без записи, ``render`` без ``-o``) выводится байтами UTF-8 с переводами
строк LF — перенаправление ``kicadfp gen dip > dip.kicad_mod`` даёт тот же файл, что ``-o``.
Файлы не изменяются без ``--write`` или ``-o`` (ТЗ 4.1.7); запись атомарная
(:func:`kicadfp.io.save`).

Селекторы команды ``set``
-------------------------

===========================  ==================================================================
``footprint.ATTR``           свойство корпуса: ``footprint.descr``, ``footprint.name``,
                             ``footprint.tags``, ``footprint.layer``, ``footprint.attrs``
                             (``"smd,exclude_from_bom"``), ``footprint.clearance`` …
``pad[N].ATTR``              площадки с номером ``N`` (номер — строка: ``pad[1]``, ``pad[A1]``,
                             ``pad[]`` — пустой номер); если таких площадок несколько, меняются
                             все (в KiCad это один вывод)
``pad[*].ATTR``              все площадки
``pad[#i].ATTR``             площадка с индексом ``i`` в порядке файла (с 0; ``#-1`` —
                             последняя)
``text[reference].ATTR``     текст Reference; ``text[value]`` — Value; ``text[user]`` — все
                             пользовательские тексты; ``text[user:N]`` — ``N``-й из них (с 0);
                             ``text[ИМЯ]`` — поле KiCad 8+ по имени (``text[Datasheet]``);
                             ``text[*]``, ``text[#i]``
``graphic[i].ATTR``          графика с индексом ``i`` (с 0) в порядке файла; ``graphic[*]`` —
                             вся; ``graphic[СЛОЙ]`` — на слое (``graphic[F.SilkS]``,
                             ``graphic[*.Fab]``); ``graphic[ВИД]`` — вида ``line``, ``rect``,
                             ``circle``, ``arc``, ``poly``, ``curve``
``model[i].ATTR``            3D-модель с индексом ``i``; ``model[*]`` — все
``property[КЛЮЧ]``           свойство корпуса ``(property "КЛЮЧ" …)``; ``none`` удаляет его
===========================  ==================================================================

``ATTR`` — имя атрибута представления (architecture.md §6), в том числе вложенное:
``pad[*].drill.diameter``, ``pad[1].drill.offset_x``. Значение приводится к типу атрибута
(по аннотации свойства модели): число (десятичный разделитель — точка), целое, логическое
(``yes/no``, ``true/false``, ``1/0``, ``да/нет``), строка (как есть), список — через запятую
или пробел (``"F.Cu,F.Mask"``), пара/тройка чисел — ``"1.2,0.8"``, ``"1.2 0.8"`` или
``"1.2x0.8"``, список точек — ``"0,0;1,0;1,1"``; JSON-массив (``[…]``) — для любых списков;
``none``/``null`` удаляет необязательный токен. ``pad[N].size`` с одним числом задаёт обе
стороны, ``drill`` с одним числом — круглое отверстие, с парой — овальное. Значение,
начинающееся с ``-`` и не являющееся числом, передаётся после ``--``.

``set`` сравнивает замечания проверки до и после изменения и печатает новые (в stderr).
Для каталога ``.pretty``: корпуса, где селектор ничего не нашёл, пропускаются; если хоть
один файл не прочитан или изменение не удалось — не записывается ничего (код 2).

Решения, не оговорённые контрактом (architecture.md §13)
--------------------------------------------------------

* ``--fp ИМЯ`` у ``info``/``validate``/``set``/``pads``/``fmt``/``render`` — один корпус
  библиотеки; ``list``/``info``/``validate``/``pads``/``render`` читают и старые
  библиотеки ``.mod``.
* ``set`` без ``--write``/``-o``: для одного файла текст результата — в stdout, список
  изменений — в stderr; для каталога — список изменений в stdout (пробный прогон).
  ``set … -o КАТАЛОГ`` для библиотеки пишет в КАТАЛОГ все её корпуса (неизменённые —
  копией файла). ``--strict`` у ``set``/``gen`` — не записывать при ошибках проверки (код 1).
* ``gen``: параметры генератора — ``--имя-параметра ЗНАЧЕНИЕ`` (``_`` -> ``-``, логические
  можно без значения: ``--first-square``), значения приводит
  :func:`kicadfp.generators.coerce_param`; ``--params FILE.json`` задаёт параметры из файла
  (командная строка важнее); ``-o`` — файл ``.kicad_mod`` или каталог (существующий, с
  ``/`` в конце или с расширением ``.pretty``: файл ``<имя>.kicad_mod``, каталог
  создаётся); без ``--name`` при ``-o ФАЙЛ`` имя корпуса — имя файла (KiCad отождествляет
  их); ``gen --list`` — генераторы, ``gen KIND --list`` — параметры генератора.
* ``fmt``: без ключей для файла — текст в stdout, для каталога — список файлов, которые
  изменились бы; ``--style`` также принимает ``kicad7`` и ``kicad5``; перед записью
  проверяется, что дерево S-выражений не изменилось.
* ``convert`` без ``-o`` ничего не пишет, а только перечисляет корпуса библиотеки;
  ``--compat {kicad9,fixed}`` — режим :func:`kicadfp.legacy.convert`.
* ``render``: без ``-o`` — SVG в stdout; для библиотеки ``-o`` — каталог, файлы
  ``<имя>.svg``/``.png`` (``--format``); ``--width`` — ширина PNG.
* ``gui [PATH]`` вызывает ``kicadfp.gui.main([PATH])``; без PySide6 — сообщение
  ``pip install kicadfp[gui]`` и код 2.
"""

from __future__ import annotations

import argparse
import errno
import importlib
import importlib.util
import inspect
import json
import math
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, Sequence

from . import generators as _gen
from . import io as _io
from . import layers as _L
from . import legacy as _legacy
from . import render as _render
from . import sexpr as _sexpr
from ._version import __version__
from .library import FOOTPRINT_EXT, Library, sanitize_name
from .model import PAD_TYPES, AttrSet, Drill, Footprint, Graphic, Model, Pad, Text, View
from .sexpr import SexprSyntaxError
from .validate import Issue, syntax_issue

__all__ = ["main", "build_parser", "EXIT_OK", "EXIT_ISSUES", "EXIT_ERROR"]

#: Код возврата: успешно.
EXIT_OK = 0
#: Код возврата: есть замечания проверки или различия (``validate``, ``fmt --check``, ``--strict``).
EXIT_ISSUES = 1
#: Код возврата: ошибка входных данных (разбор файла, аргументы, значения).
EXIT_ERROR = 2

_NONE_WORDS = frozenset(("none", "null"))
_TRUE_WORDS = frozenset(("1", "true", "yes", "y", "on", "да"))
_FALSE_WORDS = frozenset(("0", "false", "no", "n", "off", "нет"))
_GRAPHIC_KINDS = ("line", "rect", "circle", "arc", "poly", "curve")
_FMT_STYLES = ("auto", "kicad8", "kicad7", "kicad6", "kicad5")
_IMAGE_FORMATS = ("svg", "png")
_INSTALL_GUI = "pip install kicadfp[gui]"
_MAX_ERRORS = 10        # сколько ошибок ``set`` по библиотеке показывать


# ---------------------------------------------------------------------------------------------
# Ошибки и вывод
# ---------------------------------------------------------------------------------------------

class _CliError(Exception):
    """Ошибка входных данных команды (сообщение по-русски; код возврата 2)."""


class _UsageError(Exception):
    """Ошибка аргументов командной строки: печатается строка использования ``parser``."""

    def __init__(self, parser: argparse.ArgumentParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser


def _out(text: str = "") -> None:
    """Строка результата — в stdout (поток берётся в момент вызова: его подменяют тесты)."""
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    """Сообщение — в stderr."""
    sys.stderr.write(text + "\n")


def _emit_file_text(text: str) -> None:
    """Текст файла (корпус, SVG) в stdout байтами UTF-8, без преобразования переводов строк
    (в Windows текстовый stdout заменил бы LF на CRLF)."""
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        return
    stream.flush()
    buffer.write(text.encode("utf-8", "surrogateescape"))
    buffer.flush()


def _print_json(obj: Any) -> None:
    """JSON в stdout (UTF-8, отступ 2)."""
    _out(json.dumps(obj, ensure_ascii=False, indent=2))


_ERRNO_TEXT = {
    errno.ENOENT: "файл или каталог не найден",
    errno.EACCES: "нет доступа",
    errno.EPERM: "операция не разрешена",
    errno.EISDIR: "это каталог, а не файл",
    errno.ENOTDIR: "это не каталог",
    errno.EEXIST: "уже существует",
    errno.ENOSPC: "нет места на устройстве",
    errno.EROFS: "файловая система только для чтения",
}


def _os_error_text(e: OSError) -> str:
    """Сообщение об ошибке ввода-вывода по-русски (с именем файла)."""
    what = _ERRNO_TEXT.get(e.errno) if e.errno is not None else None
    if what is None:
        what = e.strerror or str(e)
    name = e.filename
    return f"{name}: {what}" if name else what


def _exc_text(e: BaseException) -> str:
    """Текст исключения без кавычек ``KeyError``."""
    if isinstance(e, KeyError) and e.args:
        return str(e.args[0])
    return str(e)


def _error_text(e: BaseException, path: Path | str | None = None) -> str:
    """Сообщение об ошибке чтения файла: ``<файл>: строка N, позиция M: …`` для
    синтаксических ошибок, текст ошибки ввода-вывода — для прочих."""
    if isinstance(e, OSError):
        return _os_error_text(e)
    where = getattr(e, "path", None) or path
    msg = _exc_text(e)
    if where and not msg.startswith(str(where)):
        return f"{where}: {msg}"
    return msg


# ---------------------------------------------------------------------------------------------
# Разбор аргументов: русские заголовки и сообщения argparse
# ---------------------------------------------------------------------------------------------

_ARGPARSE_MESSAGES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.S), r) for p, r in (
        (r"^the following arguments are required: (.*)$", r"не заданы обязательные аргументы: \1"),
        (r"^unrecognized arguments: (.*)$", r"нераспознанные аргументы: \1"),
        (r"^argument (.+?): invalid choice: (.+?) \(choose from (.*)\)$",
         r"аргумент \1: недопустимое значение \2 (допустимы: \3)"),
        (r"^argument (.+?): expected one argument$", r"аргумент \1: ожидается одно значение"),
        (r"^argument (.+?): expected at most one argument$",
         r"аргумент \1: ожидается не больше одного значения"),
        (r"^argument (.+?): expected at least one argument$",
         r"аргумент \1: ожидается хотя бы одно значение"),
        (r"^argument (.+?): invalid (\w+) value: (.*)$",
         r"аргумент \1: недопустимое значение \3 (ожидается \2)"),
        (r"^argument (.+?): not allowed with argument (.*)$",
         r"аргумент \1 нельзя использовать вместе с \2"),
        (r"^argument (.+?): ignored explicit argument (.*)$", r"аргумент \1: лишнее значение \2"),
        (r"^ambiguous option: (.+?) could match (.*)$", r"неоднозначный параметр \1: подходят \2"),
        (r"^one of the arguments (.*) is required$", r"нужен один из аргументов \1"),
        (r"^argument (.+?): (.*)$", r"аргумент \1: \2"),
    ))


def _translate_argparse(message: str) -> str:
    """Перевести стандартное сообщение argparse (известные шаблоны; прочее — как есть)."""
    for pattern, repl in _ARGPARSE_MESSAGES:
        if pattern.match(message):
            return pattern.sub(repl, message)
    return message


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Справка с русским заголовком строки использования."""

    def add_usage(self, usage: Any, actions: Any, groups: Any, prefix: str | None = None) -> None:
        """Строка использования с префиксом «использование: »."""
        super().add_usage(usage, actions, groups,
                          "использование: " if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    """``ArgumentParser`` с русскими заголовками, без сокращений длинных параметров;
    ошибки аргументов — исключение :class:`_UsageError` вместо выхода из процесса."""

    def __init__(self, *args: Any, add_help: bool = True, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", _HelpFormatter)
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "аргументы"
        self._optionals.title = "параметры"
        if add_help:
            self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                              help="показать эту справку и выйти")

    def error(self, message: str) -> Any:  # noqa: D401 - переопределение argparse
        """Ошибка аргументов: исключение :class:`_UsageError` (обрабатывает :func:`main`)."""
        raise _UsageError(self, _translate_argparse(message))


_DESCRIPTION = """\
kicadfp — чтение, проверка, изменение и создание посадочных мест KiCad
(.kicad_mod, каталоги .pretty, старые библиотеки .mod).

PATH — файл .kicad_mod, каталог .pretty (команда применяется ко всем корпусам) или
библиотека старого формата .mod (только чтение). Файлы не изменяются без --write или -o.
Коды возврата: 0 — успешно, 1 — есть замечания или различия, 2 — ошибка входных данных."""

_EPILOG = """\
примеры:
  kicadfp info dip14.kicad_mod
  kicadfp pads dip14.kicad_mod
  kicadfp set dip14.kicad_mod "pad[*].drill" 0.8 --write
  kicadfp set dip14.kicad_mod footprint.descr "DIP-14" -o dip14_new.kicad_mod
  kicadfp validate br8_timer.pretty --strict
  kicadfp gen dip --pins 14 --pitch 2.5 --row-pitch 7.5 -o br8_timer.pretty/dip14.kicad_mod
  kicadfp fmt br8_timer.pretty --check
  kicadfp convert old_lib.mod -o old_lib.pretty
  kicadfp render dip14.kicad_mod -o dip14.svg

справка по команде: kicadfp КОМАНДА -h"""

_SET_DESCRIPTION = """\
Изменить свойство корпуса или его элементов.

селекторы:
  footprint.ATTR          свойство корпуса (descr, name, tags, layer, attrs, clearance …)
  pad[N].ATTR             площадки с номером N (pad[1], pad[A1]); pad[*] — все;
                          pad[#i] — по индексу в файле (с 0)
  text[reference].ATTR    Reference; text[value] — Value; text[user] — все пользовательские;
                          text[user:N] — N-й пользовательский (с 0); text[ИМЯ] — поле KiCad 8+
  graphic[i].ATTR         графика по индексу (с 0); graphic[*]; graphic[F.SilkS] — на слое;
                          graphic[line] — по виду (line, rect, circle, arc, poly, curve)
  model[i].ATTR           3D-модель по индексу; model[*]
  property[КЛЮЧ]          свойство корпуса (значение none удаляет его)

ATTR может быть вложенным: pad[*].drill.diameter. Значение приводится к типу атрибута:
числа — с точкой, списки — через запятую ("F.Cu,F.Mask"), пары — "1.2,0.8" или "1.2x0.8",
логические — yes/no, none — удалить необязательный токен.
pad[N].size с одним числом задаёт обе стороны; drill 0.8 — круглое, drill 1.2x0.8 — овальное.

Без --write/-o результат выводится в stdout, файл не изменяется."""


def build_parser() -> argparse.ArgumentParser:
    """Разборщик аргументов ``kicadfp`` со всеми подкомандами (architecture.md §13)."""
    parser = _Parser(prog="kicadfp", description=_DESCRIPTION, epilog=_EPILOG)
    parser.add_argument("--version", action="version", version=f"kicadfp {__version__}",
                        help="показать версию программы и выйти")
    sub = parser.add_subparsers(title="команды", dest="command", metavar="КОМАНДА")

    def command(name: str, func: Callable[..., int], help_text: str,
                description: str | None = None, **kw: Any) -> argparse.ArgumentParser:
        """Подкоманда ``name`` с обработчиком ``func``."""
        sp = sub.add_parser(name, help=help_text, description=description or help_text, **kw)
        sp.set_defaults(func=func, cmd_parser=sp)
        return sp

    def path_args(sp: argparse.ArgumentParser) -> None:
        """Аргумент PATH и параметр ``--fp``."""
        sp.add_argument("path", metavar="PATH",
                        help="файл .kicad_mod, каталог .pretty или библиотека .mod")
        sp.add_argument("--fp", metavar="ИМЯ", help="только корпус ИМЯ библиотеки")

    def json_arg(sp: argparse.ArgumentParser) -> None:
        """Параметр ``--json``."""
        sp.add_argument("--json", action="store_true", help="вывод в формате JSON")

    sp = command("info", _cmd_info, "сводка по корпусу или библиотеке")
    path_args(sp)
    json_arg(sp)

    sp = command("list", _cmd_list, "имена корпусов библиотеки")
    sp.add_argument("path", metavar="LIB",
                    help="каталог .pretty, библиотека .mod или файл .kicad_mod")
    json_arg(sp)

    sp = command("validate", _cmd_validate, "проверка корпуса или библиотеки",
                 "Проверка корпусов: вывод LEVEL CODE: message; код возврата 1 при ошибках "
                 "(с --strict — и при предупреждениях).")
    path_args(sp)
    sp.add_argument("--strict", action="store_true",
                    help="код возврата 1 и при предупреждениях")
    json_arg(sp)

    sp = command("set", _cmd_set, "изменить свойство корпуса или его элементов",
                 _SET_DESCRIPTION)
    path_args(sp)
    sp.add_argument("selector", metavar="SELECTOR",
                    help="что менять: footprint.descr, pad[1].size, pad[*].drill, "
                         "text[reference].layer, graphic[0].width, model[0].path …")
    sp.add_argument("value", metavar="VALUE",
                    help="новое значение (none — удалить необязательный токен)")
    group = sp.add_mutually_exclusive_group()
    group.add_argument("-w", "--write", action="store_true",
                       help="записать изменения в исходные файлы")
    group.add_argument("-o", "--output", metavar="OUT",
                       help="записать результат в OUT (файл; для библиотеки — каталог)")
    sp.add_argument("--strict", action="store_true",
                    help="не записывать, если после изменения проверка находит ошибки (код 1)")

    sp = command("pads", _cmd_pads, "таблица площадок")
    path_args(sp)
    json_arg(sp)

    sp = command("gen", _cmd_gen, "создать типовой корпус генератором",
                 "Создать типовой корпус. Параметры генератора задаются как "
                 "--имя-параметра ЗНАЧЕНИЕ (список: kicadfp gen KIND --list); без -o "
                 "текст корпуса выводится в stdout.", add_help=False)
    sp.add_argument("-h", "--help", action="store_true",
                    help="показать справку (с KIND — вместе с параметрами генератора)")
    sp.add_argument("kind", metavar="KIND", nargs="?",
                    help="генератор: " + ", ".join(_gen.GENERATORS))
    sp.add_argument("-o", "--output", metavar="OUT",
                    help="файл .kicad_mod или каталог .pretty (без -o — вывод в stdout)")
    sp.add_argument("--params", metavar="FILE.json",
                    help="параметры генератора из JSON-файла (командная строка важнее)")
    sp.add_argument("--name", metavar="ИМЯ",
                    help="имя корпуса (по умолчанию — имя файла -o или имя генератора)")
    sp.add_argument("--list", action="store_true",
                    help="список генераторов (с KIND — список его параметров)")
    sp.add_argument("--strict", action="store_true",
                    help="не записывать, если проверка находит ошибки (код 1)")

    sp = command("fmt", _cmd_fmt, "каноническое форматирование KiCad (без изменения содержания)",
                 "Переписать файлы в каноническом форматировании KiCad (стиль — по версии "
                 "файла) без изменения содержания. Без ключей: для файла — текст в stdout, для "
                 "каталога — список файлов, которые изменились бы.")
    path_args(sp)
    group = sp.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="только проверить: код 1, если файлы отличаются от канонического вида")
    group.add_argument("-w", "--write", action="store_true", help="переписать файлы на месте")
    group.add_argument("-o", "--output", metavar="OUT",
                       help="записать в OUT (файл; для библиотеки — каталог)")
    sp.add_argument("--style", choices=_FMT_STYLES, default="auto",
                    help="auto — по версии файла; kicad8 — Prettify KiCad 8/9/10; "
                         "kicad7/kicad6/kicad5 — раскладка writer'а KiCad 7/6/5")

    sp = command("convert", _cmd_convert,
                 "преобразовать старую библиотеку .mod в каталог .pretty")
    sp.add_argument("path", metavar="IN.mod",
                    help="библиотека старого формата PCBNEW-LibModule-V1 (.mod, .emp)")
    sp.add_argument("-o", "--output", metavar="OUT.pretty",
                    help="каталог результата (без -o файлы не пишутся, выводится список "
                         "корпусов)")
    sp.add_argument("--compat", choices=_legacy.COMPAT_MODES, default="kicad9",
                    help="kicad9 — как конвертер KiCad 9 (по умолчанию); fixed — физически "
                         "корректная конвертация (смещение 3D-модели в мм и др.)")

    sp = command("render", _cmd_render, "изображение корпуса SVG или PNG")
    path_args(sp)
    sp.add_argument("-o", "--output", metavar="OUT",
                    help="файл .svg или .png (для библиотеки — каталог); без -o — SVG в stdout")
    sp.add_argument("--layers", metavar="СЛОИ",
                    help="только эти слои через запятую (F.Cu,F.SilkS,*.Fab)")
    sp.add_argument("--scale", type=float, default=10.0, metavar="PX",
                    help="масштаб SVG, пикселей на мм (по умолчанию 10)")
    sp.add_argument("--width", type=int, default=800, metavar="PX",
                    help="ширина PNG в пикселях (по умолчанию 800)")
    sp.add_argument("--grid", type=float, default=1.0, metavar="ММ",
                    help="шаг сетки, мм (по умолчанию 1)")
    sp.add_argument("--no-grid", action="store_true", help="без сетки")
    sp.add_argument("--no-background", action="store_true", help="прозрачный фон")
    sp.add_argument("--margin", type=float, default=2.0, metavar="ММ",
                    help="поле вокруг корпуса, мм (по умолчанию 2)")
    sp.add_argument("--pad-numbers", action="store_true", help="подписать номера площадок")
    sp.add_argument("--show-hidden", action="store_true", help="рисовать скрытые тексты")
    sp.add_argument("--format", choices=_IMAGE_FORMATS,
                    help="формат файлов при выводе в каталог (по умолчанию svg)")

    sp = command("gui", _cmd_gui, "запустить графический интерфейс (нужен PySide6)")
    sp.add_argument("path", metavar="PATH", nargs="?",
                    help="файл .kicad_mod или каталог .pretty, который открыть")
    return parser


# ---------------------------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    """Выполнить команду ``kicadfp`` и вернуть код возврата.

    ``argv`` — аргументы без имени программы (``None`` — ``sys.argv[1:]``); элементы могут
    быть путями (``os.PathLike``). Коды: :data:`EXIT_OK` (0), :data:`EXIT_ISSUES` (1 —
    замечания/различия), :data:`EXIT_ERROR` (2 — ошибка входных данных). ``SystemExit``
    (``--help``, ``--version``) не выпускается: возвращается его код.
    """
    raw = sys.argv[1:] if argv is None else argv
    if isinstance(raw, (str, bytes)):
        raise TypeError("main: ожидается список аргументов, а не строка")
    args = [os.fspath(a) if isinstance(a, os.PathLike) else str(a) for a in raw]
    parser = build_parser()
    try:
        return _run(parser, args)
    except _UsageError as e:
        e.parser.print_usage(sys.stderr)
        _err(f"ошибка: {e}")
        return EXIT_ERROR
    except _CliError as e:
        _err(f"ошибка: {e}")
        return EXIT_ERROR
    except BrokenPipeError:
        # вывод оборвал читатель (например, «| head»): молча завершиться
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return EXIT_ERROR
    except (ValueError, OSError) as e:   # SexprSyntaxError, LegacyFormatError, ошибки ФС …
        _err(f"ошибка: {_error_text(e)}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("прервано")
        return 130
    except Exception as e:  # noqa: BLE001 - одна строка вместо трассировки
        if os.environ.get("KICADFP_DEBUG"):
            raise
        _err(f"ошибка: внутренняя ошибка kicadfp: {type(e).__name__}: {e} "
             f"(трассировка — с переменной окружения KICADFP_DEBUG=1)")
        return EXIT_ERROR


def _run(parser: argparse.ArgumentParser, args: list[str]) -> int:
    """Разобрать аргументы и выполнить команду."""
    try:
        ns, extras = parser.parse_known_args(args)
    except SystemExit as e:   # --help, --version
        code = e.code
        return code if isinstance(code, int) else (EXIT_OK if code is None else EXIT_ERROR)
    if getattr(ns, "command", None) is None:
        parser.print_usage(sys.stderr)
        _err("ошибка: не указана команда (список команд: kicadfp --help)")
        return EXIT_ERROR
    if extras and ns.command != "gen":
        raise _UsageError(ns.cmd_parser, "нераспознанные аргументы: " + " ".join(extras))
    return int(ns.func(ns, extras))


# ---------------------------------------------------------------------------------------------
# Входные корпуса: файл, каталог .pretty, библиотека .mod
# ---------------------------------------------------------------------------------------------

@dataclass
class _Entry:
    """Корпус из входного пути: имя (для каталога — имя файла без расширения), файл,
    прочитанный корпус или ошибка чтения."""

    name: str
    path: Path
    fp: Footprint | None = None
    error: Exception | None = None


def _read_head(path: Path, size: int = 65536) -> str:
    """Начало файла текстом (для определения формата)."""
    with open(path, "rb") as f:
        data = f.read(size)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "surrogateescape")


class _Source:
    """Корпуса по пути из командной строки.

    ``kind``: ``"file"`` — файл ``.kicad_mod`` (ошибка чтения — исключение сразу),
    ``"library"`` — каталог (файлы читаются по одному в :meth:`entries`, ошибка чтения
    файла — в :attr:`_Entry.error`), ``"legacy"`` — библиотека ``.mod`` (только чтение).
    ``only`` — имя единственного нужного корпуса (``--fp``).
    """

    def __init__(self, path: str | Path, only: str | None = None) -> None:
        p = Path(path)
        if not p.exists():
            raise _CliError(f"{p}: файл или каталог не найден")
        self.path = p
        self.only = only
        self.library: Library | None = None
        self._fps: list[Footprint] = []
        if p.is_dir():
            self.kind = "library"
            self.library = Library(p)
            names = self.library.names
            if only is not None:
                key = only[:-len(FOOTPRINT_EXT)] if only.endswith(FOOTPRINT_EXT) else only
                if key not in names:
                    raise _CliError(f"{p}: в библиотеке нет корпуса «{only}»")
                names = [key]
            self.names: list[str] = names
            self.title = self.library.name
            return
        if _io.detect_format(_read_head(p)) == "legacy":
            self.kind = "legacy"
            fps = _legacy.read_library(p)
        else:
            self.kind = "file"
            fps = [_io.load(p)]
        if only is not None:
            fps = [fp for fp in fps if fp.name == only]
            if not fps:
                raise _CliError(f"{p}: нет корпуса «{only}»")
        self._fps = fps
        self.names = [fp.name for fp in fps]
        self.title = p.stem

    @property
    def single(self) -> bool:
        """Один корпус (файл, ``--fp`` или библиотека ``.mod`` из одного корпуса): вывод
        без имён корпусов, JSON — объект, а не список."""
        if self.only is not None:
            return True
        return self.kind != "library" and len(self._fps) == 1

    def entries(self) -> Iterator[_Entry]:
        """Корпуса по одному (файлы каталога читаются лениво)."""
        if self.library is None:
            for fp in self._fps:
                yield _Entry(fp.name, self.path, fp)
            return
        for name in self.names:
            path = self.library.path_of(name)
            try:
                fp = _io.load(path)
            except (ValueError, OSError) as e:   # синтаксис, старый формат, ввод-вывод
                yield _Entry(name, path, error=e)
            else:
                yield _Entry(name, path, fp)

    def library_json(self, footprints: list[Any], **extra: Any) -> dict[str, Any]:
        """JSON-объект библиотеки: имя, путь, формат, список по корпусам (+ ``extra``)."""
        obj: dict[str, Any] = {"library": self.title, "path": str(self.path)}
        if self.kind == "legacy":
            obj["format"] = "PCBNEW-LibModule-V1"
        obj["footprints"] = footprints
        obj.update(extra)
        return obj


def _prefix(src: _Source, entry: _Entry) -> str:
    """Префикс строк вывода для корпуса библиотеки (для одного корпуса — пусто)."""
    return "" if src.single else f"{entry.name}: "


def _is_dir_target(out: str, pretty: bool = True) -> bool:
    """``-o`` указывает на каталог: существующий каталог, путь с разделителем в конце или
    (при ``pretty``) ещё не существующий путь с расширением ``.pretty``."""
    p = Path(out)
    if p.is_dir() or out.endswith(("/", os.sep)):
        return True
    return pretty and p.suffix.lower() == ".pretty" and not p.exists()


def _output_path(out: str, default_name: str) -> Path:
    """Путь выходного файла по ``-o``: каталог (см. :func:`_is_dir_target`) — файл
    ``default_name`` в нём (каталог создаётся); иначе — сам путь (родительские каталоги
    создаются)."""
    p = Path(out)
    if _is_dir_target(out):
        p.mkdir(parents=True, exist_ok=True)
        return p / default_name
    if p.parent != Path(""):
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


_FILE_SUFFIXES = frozenset((FOOTPRINT_EXT, ".mod", ".svg", ".png"))


def _output_dir(out: str, source: Path | None = None) -> Path:
    """Каталог результата ``-o`` для библиотеки (создаётся); ``_CliError``, если это файл
    (или ещё не существующий путь с расширением файла: ``.kicad_mod``, ``.svg`` …) или сам
    исходный каталог (для записи на место есть ``--write``)."""
    p = Path(out)
    if p.exists() and not p.is_dir():
        raise _CliError(f"{p}: для библиотеки -o должен указывать каталог, а это файл")
    if not p.exists() and p.suffix.lower() in _FILE_SUFFIXES:
        raise _CliError(f"{p}: для библиотеки -o должен указывать каталог, а не файл "
                        f"{p.suffix}")
    if source is not None and p.exists() and p.resolve() == source.resolve():
        raise _CliError(f"{p}: это исходный каталог — для записи на место используйте --write")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file_name(name: str) -> str:
    """Имя файла корпуса: ``<имя>.kicad_mod`` (недопустимые символы — ``_``)."""
    return sanitize_name(name) + FOOTPRINT_EXT


# ---------------------------------------------------------------------------------------------
# Форматирование значений
# ---------------------------------------------------------------------------------------------

def _num(v: float | int | None) -> str:
    """Число для вывода — как в файлах KiCad (без хвостовых нулей, до 1e-6)."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, int):
        return str(v)
    try:
        return _sexpr.format_number(float(v))
    except (ValueError, OverflowError):
        return str(v)


def _jnum(v: float | None) -> float | None:
    """Число для JSON (округление до нанометра, без ``-0``)."""
    if v is None:
        return None
    r = round(float(v), 6)
    return 0.0 if r == 0 else r


def _drill_text(d: Drill | None) -> str:
    """Отверстие для таблиц: ``0.8``, ``овал 1.2x0.8``, со смещением формы."""
    if d is None:
        return "-"
    if d.oval:
        h = d.width if d.width is not None else d.diameter
        s = f"овал {_num(d.diameter)}x{_num(h)}"
    else:
        s = _num(d.diameter)
    if d.offset_x or d.offset_y:
        s += f" смещение {_num(d.offset_x)},{_num(d.offset_y)}"
    return s


def _drill_json(d: Drill | None) -> dict[str, Any] | None:
    """Отверстие для JSON."""
    if d is None:
        return None
    return {"diameter": _jnum(d.diameter), "width": _jnum(d.width), "oval": d.oval,
            "offset_x": _jnum(d.offset_x), "offset_y": _jnum(d.offset_y)}


def _show(v: Any) -> str:
    """Значение атрибута для сообщений ``set`` (``старое -> новое``)."""
    if v is None:
        return "нет"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, (int, float)):
        return _num(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, Drill):
        return _drill_text(v)
    if isinstance(v, Text):
        return json.dumps(v.text, ensure_ascii=False)
    if isinstance(v, tuple):
        return "(" + ", ".join(_show(x) for x in v) + ")"
    if isinstance(v, (list, set, frozenset, AttrSet)):
        return "[" + ", ".join(x if isinstance(x, str) else _show(x) for x in v) + "]"
    if isinstance(v, View):
        return type(v).__name__
    return str(v)


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Таблица с выравниванием столбцов по ширине (строки без хвостовых пробелов)."""
    all_rows = [list(headers), *[list(r) for r in rows]]
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in all_rows]


# ---------------------------------------------------------------------------------------------
# info, list, pads
# ---------------------------------------------------------------------------------------------

def _kicad_label(fp: Footprint) -> str:
    """Выпуск KiCad, который пишет формат корпуса (для сводки)."""
    if fp.node.name == "module":
        return "KiCad 5"
    v = fp.version
    if v is None:
        return "KiCad 6 (без версии)"
    for limit, label in ((20211014, "KiCad 6"), (20221018, "KiCad 7"), (20240108, "KiCad 8"),
                         (20241229, "KiCad 9")):
        if v <= limit:
            return label
    return "KiCad 10"


def _layer_key(name: str) -> tuple[int, int, str]:
    """Порядок слоёв в сводке: по первому слою группы в порядке KiCad, группа — раньше."""
    expanded = _L.expand([name])
    first = expanded[0] if expanded else name
    try:
        idx = _L.ALL_LAYERS.index(first)
    except ValueError:
        idx = len(_L.ALL_LAYERS)
    return (idx, 0 if _L.is_wildcard(name) else 1, name)


def _used_layers(fp: Footprint) -> list[str]:
    """Слои, на которых есть элементы корпуса (как записаны, с групповыми обозначениями)."""
    names: set[str] = set()
    for p in fp.pads:
        names.update(p.layers)
    for g in fp.graphics:
        names.update(g.layers)
    for t in fp.texts:
        if t.layer:
            names.add(t.layer)
    for z in fp.zones:
        lay = z.value("layer")
        if lay is not None:
            names.add(str(lay))
        lays = z.find("layers")
        if lays is not None:
            names.update(str(a) for a in lays.atoms())
    return sorted(names, key=_layer_key)


def _ordered_counts(values: Sequence[str], order: Sequence[str]) -> dict[str, int]:
    """Подсчёт значений: сначала в порядке ``order``, затем прочие по алфавиту."""
    counts = Counter(values)
    out = {k: counts[k] for k in order if counts.get(k)}
    out.update({k: counts[k] for k in sorted(counts) if k not in out})
    return out


def _info_dict(entry: _Entry, src: _Source) -> dict[str, Any]:
    """Сводка по корпусу (для ``info`` и ``info --json``)."""
    fp = entry.fp
    assert fp is not None
    pads = fp.pads
    graphics = fp.graphics
    texts = fp.texts
    models = fp.models
    bb = fp.bbox()
    d: dict[str, Any] = {
        "name": fp.name,
        "path": str(entry.path),
        "root": fp.node.name,
        "version": fp.version,
        "kicad": _kicad_label(fp),
        "generator": fp.generator,
        "generator_version": fp.generator_version,
        "layer": fp.layer,
        "descr": fp.descr,
        "tags": fp.tags,
        "attrs": list(fp.attrs),
        "pads": {"total": len(pads),
                 "by_type": _ordered_counts([p.type for p in pads], PAD_TYPES)},
        "layers": _used_layers(fp),
        "bbox": {"x1": _jnum(bb.x1), "y1": _jnum(bb.y1), "x2": _jnum(bb.x2), "y2": _jnum(bb.y2),
                 "width": _jnum(bb.width), "height": _jnum(bb.height)},
        "graphics": {"total": len(graphics),
                     "by_kind": _ordered_counts([g.kind for g in graphics], _GRAPHIC_KINDS)},
        "texts": {"total": len(texts),
                  "by_kind": _ordered_counts([t.kind for t in texts],
                                             ("reference", "value", "user"))},
        "models": {"total": len(models), "paths": [m.path for m in models]},
        "zones": len(fp.zones),
        "groups": len(fp.groups),
        "unknown": [n.name for n in fp.unknown],
    }
    if src.kind == "legacy":
        d["source"] = "PCBNEW-LibModule-V1"
    return d


def _counts_text(total: int, counts: dict[str, int]) -> str:
    """``14 (thru_hole: 14)``."""
    if not total:
        return "0"
    return f"{total} (" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + ")"


def _info_lines(d: dict[str, Any]) -> list[str]:
    """Сводка ``info`` текстом (строки «Поле: значение»)."""
    if d.get("source"):
        fmt = f"старый формат .mod (показан после преобразования в {d['version']})"
    elif d["root"] == "module":
        fmt = "KiCad 5 (корень module, без версии)"
    else:
        fmt = f"{d['version']} ({d['kicad']})"
    gen = d["generator"] or "-"
    if d["generator_version"]:
        gen += f" {d['generator_version']}"
    bb = d["bbox"]
    bbox = (f"{_num(bb['width'])} x {_num(bb['height'])} мм "
            f"(X: {_num(bb['x1'])} .. {_num(bb['x2'])}, Y: {_num(bb['y1'])} .. {_num(bb['y2'])})")
    models = d["models"]
    model_text = str(models["total"])
    if models["paths"]:
        model_text += " (" + "; ".join(models["paths"]) + ")"
    rows = [
        ("Корпус", d["name"]),
        ("Файл", d["path"]),
        ("Формат", fmt),
        ("Генератор", gen),
        ("Слой", d["layer"]),
        ("Описание", d["descr"] or "-"),
        ("Ключевые слова", d["tags"] or "-"),
        ("Атрибуты", ", ".join(d["attrs"]) or "-"),
        ("Площадки", _counts_text(d["pads"]["total"], d["pads"]["by_type"])),
        ("Слои", ", ".join(d["layers"]) or "-"),
        ("Габариты", bbox),
        ("Графика", _counts_text(d["graphics"]["total"], d["graphics"]["by_kind"])),
        ("Тексты", _counts_text(d["texts"]["total"], d["texts"]["by_kind"])),
        ("3D-модели", model_text),
    ]
    if d["zones"]:
        rows.append(("Зоны", str(d["zones"])))
    if d["groups"]:
        rows.append(("Группы", str(d["groups"])))
    if d["unknown"]:
        rows.append(("Неизвестные узлы", ", ".join(d["unknown"])))
    width = max(len(k) for k, _ in rows) + 1
    return [f"{k + ':':<{width}} {v}" for k, v in rows]


def _report_read_error(entry: _Entry) -> None:
    """Сообщение о файле библиотеки, который не удалось прочитать."""
    assert entry.error is not None
    _err(f"ошибка: {_error_text(entry.error, entry.path)}")


def _cmd_info(ns: argparse.Namespace, extras: list[str]) -> int:
    """``info PATH``: сводка по корпусу (для библиотеки — по каждому корпусу)."""
    src = _Source(ns.path, ns.fp)
    status = EXIT_OK
    items: list[dict[str, Any]] = []
    if not ns.json and not src.single:
        _out(f"Библиотека: {src.title} ({src.path}), корпусов: {len(src.names)}")
    for entry in src.entries():
        if entry.error is not None:
            _report_read_error(entry)
            status = EXIT_ERROR
            items.append({"name": entry.name, "path": str(entry.path),
                          "error": _error_text(entry.error)})
            continue
        d = _info_dict(entry, src)
        items.append(d)
        if not ns.json:
            if not src.single:
                _out()
            for line in _info_lines(d):
                _out(line)
    if ns.json:
        _print_json(items[0] if src.single and items else src.library_json(items))
    return status


def _cmd_list(ns: argparse.Namespace, extras: list[str]) -> int:
    """``list LIB``: имена корпусов (каталог — по именам файлов, ``.mod`` — модули)."""
    src = _Source(ns.path)
    if ns.json:
        _print_json(src.names)
    else:
        for name in src.names:
            _out(name)
    return EXIT_OK


_PAD_HEADERS = ("№", "Тип", "Форма", "X", "Y", "Угол", "Размер X", "Размер Y", "Отверстие",
                "Слои")


def _pad_row(p: Pad) -> list[str]:
    """Строка таблицы ``pads``."""
    return [p.number if p.number else '""', p.type, p.shape, _num(p.x), _num(p.y),
            _num(p.angle), _num(p.size_x), _num(p.size_y), _drill_text(p.drill),
            ",".join(p.layers) or "-"]


def _pad_json(p: Pad) -> dict[str, Any]:
    """Площадка для ``pads --json``."""
    return {"number": p.number, "type": p.type, "shape": p.shape, "x": _jnum(p.x),
            "y": _jnum(p.y), "angle": _jnum(p.angle), "size_x": _jnum(p.size_x),
            "size_y": _jnum(p.size_y), "drill": _drill_json(p.drill), "layers": p.layers,
            "roundrect_rratio": _jnum(p.roundrect_rratio)}


def _cmd_pads(ns: argparse.Namespace, extras: list[str]) -> int:
    """``pads PATH``: таблица площадок (№, тип, форма, X, Y, угол, размеры, отверстие, слои)."""
    src = _Source(ns.path, ns.fp)
    status = EXIT_OK
    items: list[dict[str, Any]] = []
    first = True
    for entry in src.entries():
        if entry.error is not None:
            _report_read_error(entry)
            status = EXIT_ERROR
            items.append({"name": entry.name, "path": str(entry.path),
                          "error": _error_text(entry.error)})
            continue
        fp = entry.fp
        assert fp is not None
        pads = fp.pads
        items.append({"name": fp.name, "path": str(entry.path),
                      "pads": [_pad_json(p) for p in pads]})
        if ns.json:
            continue
        if not src.single:
            if not first:
                _out()
            _out(f"{entry.name} (площадок: {len(pads)})")
        first = False
        if not pads:
            _out("площадок нет")
            continue
        for line in _table(_PAD_HEADERS, [_pad_row(p) for p in pads]):
            _out(line)
    if ns.json:
        _print_json(items[0] if src.single and items else src.library_json(items))
    return status


# ---------------------------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------------------------

def _read_issue(entry: _Entry) -> Issue:
    """Замечание об ошибке чтения файла (``SEXPR_SYNTAX`` или ``FILE_READ``)."""
    e = entry.error
    if isinstance(e, SexprSyntaxError):
        return syntax_issue(e, str(entry.path))
    return Issue("error", "FILE_READ", _error_text(e or Exception("?"), entry.path), None)


def _issues_json(entry: _Entry, issues: list[Issue], error: str | None = None) -> dict[str, Any]:
    """Отчёт проверки корпуса для JSON."""
    n_err = sum(1 for i in issues if i.level == "error")
    obj: dict[str, Any] = {"name": entry.fp.name if entry.fp is not None else entry.name,
                           "path": str(entry.path)}
    if error is not None:
        obj["error"] = error
    obj.update({"issues": [i.to_dict() for i in issues], "errors": n_err,
                "warnings": len(issues) - n_err})
    return obj


def _cmd_validate(ns: argparse.Namespace, extras: list[str]) -> int:
    """``validate PATH``: замечания ``LEVEL CODE: message``; код 1 при ошибках (с
    ``--strict`` — и при предупреждениях), 2 — если файл не прочитан."""
    src = _Source(ns.path, ns.fp)
    reports: list[dict[str, Any]] = []
    n_err = n_warn = checked = 0
    read_errors = False
    for entry in src.entries():
        if entry.error is not None:
            read_errors = True
            msg = _error_text(entry.error, entry.path)
            if not ns.json:
                _err(f"ошибка: {msg}")
            reports.append(_issues_json(entry, [_read_issue(entry)], error=msg))
            n_err += 1
            continue
        assert entry.fp is not None
        checked += 1
        issues = list(entry.fp.validate())
        e = sum(1 for i in issues if i.level == "error")
        n_err += e
        n_warn += len(issues) - e
        reports.append(_issues_json(entry, issues))
        if not ns.json:
            prefix = _prefix(src, entry)
            for issue in issues:
                _out(f"{prefix}{issue}")
    if ns.json:
        _print_json(reports[0] if src.single and reports
                    else src.library_json(reports, errors=n_err, warnings=n_warn))
    elif src.single:
        _out("замечаний нет" if not (n_err or n_warn)
             else f"ошибок: {n_err}, предупреждений: {n_warn}")
    else:
        _out(f"проверено корпусов: {checked}; ошибок: {n_err}, предупреждений: {n_warn}")
    if read_errors:
        return EXIT_ERROR
    if n_err or (ns.strict and n_warn):
        return EXIT_ISSUES
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# set: селекторы
# ---------------------------------------------------------------------------------------------

class _Selector(NamedTuple):
    """Разобранный селектор ``set``: вид элемента, индекс в скобках, цепочка атрибутов."""

    text: str
    kind: str
    index: str | None
    attrs: tuple[str, ...]


_SELECTOR_KINDS = ("footprint", "pad", "text", "graphic", "model", "property")
_SELECTOR_RE = re.compile(r"^(?P<kind>[A-Za-z_]+)(?:\[(?P<index>[^\]]*)\])?(?P<rest>.*)$", re.S)
_ATTR_RE = re.compile(r"^[A-Za-z_]\w*$")
_SELECTOR_EXAMPLES = {"pad": "pad[1].size", "text": "text[reference].layer",
                      "graphic": "graphic[0].width", "model": "model[0].path"}


def _to_index(s: str, what: str) -> int:
    """Целый индекс из селектора (``_CliError`` — не число)."""
    try:
        return int(s.strip())
    except ValueError:
        raise _CliError(f"{what}: индекс должен быть целым числом, получено «{s}»") from None


def _parse_selector(text: str) -> _Selector:
    """Разобрать селектор ``set`` (синтаксис — в описании модуля); ``_CliError`` при ошибке."""
    s = text.strip()
    hint = ("ожидается footprint.ATTR, pad[N].ATTR, text[reference].ATTR, graphic[i].ATTR, "
            "model[i].ATTR или property[КЛЮЧ]")
    m = _SELECTOR_RE.match(s)
    if m is None:
        raise _CliError(f"неверный селектор «{text}»: {hint}")
    kind = m.group("kind").lower()
    if kind == "fp":
        kind = "footprint"
    if kind not in _SELECTOR_KINDS:
        raise _CliError(f"неверный селектор «{text}»: неизвестный элемент «{kind}»; {hint}")
    index = m.group("index")
    rest = m.group("rest")
    attrs: tuple[str, ...] = ()
    if rest:
        parts = rest[1:].split(".") if rest.startswith(".") else []
        if not parts or not all(_ATTR_RE.match(p) for p in parts):
            raise _CliError(f"неверный селектор «{text}»: после элемента ожидается .ATTR; {hint}")
        attrs = tuple(parts)
    if kind == "footprint":
        if index is not None:
            raise _CliError(f"неверный селектор «{text}»: у footprint нет индекса "
                            f"(footprint.ATTR)")
        if not attrs:
            raise _CliError(f"неверный селектор «{text}»: укажите атрибут, например "
                            f"footprint.descr")
    elif kind == "property":
        if index is None or not index.strip():
            raise _CliError(f"неверный селектор «{text}»: укажите ключ — property[КЛЮЧ]")
        if attrs:
            raise _CliError(f"неверный селектор «{text}»: значение присваивается самому "
                            f"свойству — property[КЛЮЧ] без атрибута")
    else:
        if index is None:
            raise _CliError(f"неверный селектор «{text}»: укажите элемент в скобках, например "
                            f"{_SELECTOR_EXAMPLES[kind]}")
        if not attrs:
            raise _CliError(f"неверный селектор «{text}»: укажите атрибут — "
                            f"{kind}[{index}].ATTR")
        idx = index.strip()
        if idx.startswith("#"):
            _to_index(idx[1:], text)
        elif kind == "text" and idx.lower().startswith("user:"):
            _to_index(idx[5:], text)
        elif kind == "model" and idx != "*":
            _to_index(idx, text)
        elif kind == "graphic" and idx != "*" and not re.fullmatch(r"[-+]?\d+", idx):
            if idx.lower() not in _GRAPHIC_KINDS and not _L.is_valid_layer(idx):
                raise _CliError(f"неверный селектор «{text}»: «{idx}» — не индекс, не слой и "
                                f"не вид графики ({', '.join(_GRAPHIC_KINDS)})")
    return _Selector(text, kind, index, attrs)


def _pick(items: list[Any], i: int) -> list[tuple[int, Any]]:
    """Элемент по индексу (отрицательный — с конца) или пусто, если индекс вне диапазона."""
    if -len(items) <= i < len(items):
        j = i % len(items)
        return [(j, items[j])]
    return []


def _unquote(s: str) -> str:
    """Снять кавычки вокруг номера/имени в селекторе (``pad["A1"]``)."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _resolve(sel: _Selector, fp: Footprint) -> list[tuple[str, View]]:
    """Элементы корпуса, выбранные селектором: пары ``(метка, представление)``."""
    idx = (sel.index or "").strip()
    if sel.kind == "footprint":
        return [("footprint", fp)]
    if sel.kind == "pad":
        pads = fp.pads
        counts = Counter(p.number for p in pads)
        if idx == "*":
            chosen = list(enumerate(pads))
        elif idx.startswith("#"):
            chosen = _pick(pads, _to_index(idx[1:], sel.text))
        else:
            number = _unquote(idx)
            chosen = [(i, p) for i, p in enumerate(pads) if p.number == number]
        return [(f"pad[{p.number}]" if p.number and counts[p.number] == 1 else f"pad[#{i}]", p)
                for i, p in chosen]
    if sel.kind == "text":
        texts = fp.texts
        users = [t for t in texts if t.kind == "user"]
        user_index = {id(t.node): k for k, t in enumerate(users)}

        def label(t: Text) -> str:
            if t.kind in ("reference", "value"):
                return f"text[{t.kind}]"
            if t.name:
                return f"text[{t.name}]"
            return f"text[user:{user_index[id(t.node)]}]"

        low = idx.lower()
        if idx == "*":
            chosen_t = texts
        elif idx.startswith("#"):
            chosen_t = [t for _, t in _pick(texts, _to_index(idx[1:], sel.text))]
        elif low in ("reference", "value"):
            t = fp.reference if low == "reference" else fp.value
            chosen_t = [] if t is None else [t]
        elif low == "user":
            chosen_t = users
        elif low.startswith("user:"):
            chosen_t = [t for _, t in _pick(users, _to_index(idx[5:], sel.text))]
        else:
            name = _unquote(idx)
            chosen_t = [t for t in texts if t.name == name]
            if not chosen_t:
                chosen_t = [t for t in texts if t.name and t.name.lower() == name.lower()]
        return [(label(t), t) for t in chosen_t]
    if sel.kind == "graphic":
        graphics = fp.graphics
        if idx == "*":
            chosen_g = list(enumerate(graphics))
        elif idx.startswith("#"):
            chosen_g = _pick(graphics, _to_index(idx[1:], sel.text))
        elif re.fullmatch(r"[-+]?\d+", idx):
            chosen_g = _pick(graphics, int(idx))
        elif idx.lower() in _GRAPHIC_KINDS:
            chosen_g = [(i, g) for i, g in enumerate(graphics) if g.kind == idx.lower()]
        else:
            wanted = set(_L.expand([idx]))
            chosen_g = [(i, g) for i, g in enumerate(graphics)
                        if any(ly in wanted for ly in _L.expand(g.layers))]
        return [(f"graphic[{i}]", g) for i, g in chosen_g]
    models = fp.models
    if idx == "*":
        chosen_m = list(enumerate(models))
    else:
        chosen_m = _pick(models, _to_index(idx[1:] if idx.startswith("#") else idx, sel.text))
    return [(f"model[{i}]", m) for i, m in chosen_m]


# ---------------------------------------------------------------------------------------------
# set: типы атрибутов и приведение значений
# ---------------------------------------------------------------------------------------------

class _Ty(NamedTuple):
    """Тип значения атрибута: имя (``str``, ``int``, ``float``, ``bool``, ``None``, ``list``,
    ``tuple``, ``any``), параметры (каждый — кортеж альтернатив), ``tuple[X, ...]``."""

    name: str
    args: tuple[tuple["_Ty", ...], ...] = ()
    variadic: bool = False


_ANY = _Ty("any")
_FLOAT = _Ty("float")
_POINT = (_Ty("tuple", ((_FLOAT,), (_FLOAT,))),)
_LIST_NAMES = frozenset(("list", "List", "Iterable", "Sequence", "MutableSequence",
                         "Collection", "set", "Set", "frozenset", "FrozenSet", "MutableSet"))

#: Типы атрибутов, аннотации которых не описывают принимаемые значения (``Any``,
#: представление вместо значения, ``str | int`` у номера площадки).
_TYPE_OVERRIDES: dict[str, str] = {
    "drill": "float | tuple[float, float] | None",
    "attrs": "list[str]",
    "reference": "str",
    "value": "str",
    "number": "str",
    "zone_connect": "int | None",
    "autoplace_cost90": "int | None",
    "autoplace_cost180": "int | None",
    "thermal_gap": "float | None",
    "thermal_width": "float | None",
    "die_length": "float | None",
    "roundrect_rratio": "float | None",
}


def _parse_type(text: str) -> tuple[_Ty, ...]:
    """Разобрать аннотацию (``"float | tuple[float, float] | None"``) в альтернативы
    :class:`_Ty`; непонятное — ``any``."""
    tokens = re.findall(r"\.\.\.|[A-Za-z_][\w.]*|[\[\],|]", text)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def union() -> tuple[_Ty, ...]:
        alts = list(single())
        while peek() == "|":
            take()
            alts.extend(single())
        return tuple(alts)

    def single() -> tuple[_Ty, ...]:
        name = take().rsplit(".", 1)[-1]
        args: list[tuple[_Ty, ...]] = []
        variadic = False
        if peek() == "[":
            take()
            while True:
                if peek() == "...":
                    take()
                    variadic = True
                else:
                    args.append(union())
                tok = take()
                if tok == "]":
                    break
                if tok != ",":
                    raise ValueError(text)
        if name in ("None", "NoneType"):
            return (_Ty("None"),)
        if name in ("str", "int", "float", "bool"):
            return (_Ty(name),)
        if name == "Real":
            return (_FLOAT,)
        if name == "Optional":
            return (*args[0], _Ty("None")) if args else (_ANY,)
        if name == "Union":
            return tuple(a for alt in args for a in alt)
        if name == "Point":
            return _POINT
        if name == "PointList":
            return (_Ty("list", (_POINT,)),)
        if name == "AttrSet":
            return (_Ty("list", ((_Ty("str"),),)),)
        if name in _LIST_NAMES:
            return (_Ty("list", (args[0] if args else (_ANY,),)),)
        if name in ("tuple", "Tuple"):
            return (_Ty("tuple", tuple(args), variadic),)
        return (_ANY,)

    try:
        result = union()
    except (IndexError, ValueError):
        return (_ANY,)
    return result if pos == len(tokens) else (_ANY,)


def _annotation(fn: Callable[..., Any] | None, setter: bool) -> str | None:
    """Аннотация значения свойства: параметра setter'а или результата getter'а (строкой)."""
    if fn is None:
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    if setter:
        params = list(sig.parameters.values())
        if len(params) < 2:
            return None
        ann = params[1].annotation
    else:
        ann = sig.return_annotation
    if ann is inspect.Parameter.empty or ann is inspect.Signature.empty:
        return None
    if isinstance(ann, str):
        return ann
    return getattr(ann, "__name__", None) or str(ann)


def _alts_from_value(v: Any) -> tuple[_Ty, ...]:
    """Тип по текущему значению атрибута (когда аннотации нет)."""
    if isinstance(v, bool):
        return (_Ty("bool"),)
    if isinstance(v, int):
        return (_Ty("int"), _Ty("None"))
    if isinstance(v, float):
        return (_FLOAT, _Ty("None"))
    if isinstance(v, tuple):
        return (_Ty("tuple", tuple((_FLOAT,) for _ in v)), _Ty("None"))
    if isinstance(v, (list, set, frozenset)):
        return (_Ty("list", ((_Ty("str"),),)), _Ty("None"))
    return (_Ty("str"), _Ty("None"))


def _property_of(cls: type, name: str) -> property | None:
    """Публичное свойство ``name`` класса (по MRO) или ``None``."""
    if name.startswith("_"):
        return None
    for klass in cls.__mro__:
        if name in klass.__dict__:
            attr = klass.__dict__[name]
            return attr if isinstance(attr, property) else None
    return None


def _settable_names(cls: type) -> list[str]:
    """Имена изменяемых публичных свойств класса (для подсказок)."""
    names: set[str] = set()
    for klass in cls.__mro__:
        for name, attr in klass.__dict__.items():
            if not name.startswith("_") and isinstance(attr, property) and attr.fset is not None:
                if _property_of(cls, name) is attr:
                    names.add(name)
    return sorted(names)


def _attr_type(cls: type, name: str, prop: property, current: Any) -> tuple[_Ty, ...]:
    """Тип значения атрибута: таблица уточнений, аннотация setter'а, аннотация getter'а,
    тип текущего значения."""
    text = _TYPE_OVERRIDES.get(name)
    if text is None:
        text = _annotation(prop.fset, setter=True)
        if text is None or text.strip() == "Any":
            text = _annotation(prop.fget, setter=False)
    alts = _parse_type(text) if text else (_ANY,)
    if all(a.name == "any" for a in alts):
        alts = _alts_from_value(current)
    return alts


def _to_float(s: str, what: str) -> float:
    """Число с точкой (``_CliError`` — не число или не конечное)."""
    try:
        v = float(s)
    except ValueError:
        hint = " (десятичный разделитель — точка)" if "," in s else ""
        raise _CliError(f"{what}: ожидается число{hint}, получено «{s}»") from None
    if not math.isfinite(v):
        raise _CliError(f"{what}: ожидается конечное число, получено «{s}»")
    return v


def _to_int(s: str, what: str) -> int:
    """Целое число (``_CliError`` — не целое)."""
    try:
        return int(s)
    except ValueError:
        raise _CliError(f"{what}: ожидается целое число, получено «{s}»") from None


def _to_bool(s: str, what: str) -> bool:
    """Логическое значение: yes/no, true/false, 1/0, on/off, да/нет."""
    low = s.lower()
    if low in _TRUE_WORDS:
        return True
    if low in _FALSE_WORDS:
        return False
    raise _CliError(f"{what}: ожидается логическое значение (yes/no, true/false, 1/0), "
                    f"получено «{s}»")


def _stringify(value: Any) -> Any:
    """Значения JSON -> строки (списки остаются списками) для единого приведения типов."""
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return str(value)


def _is_numeric_seq(alt: _Ty) -> bool:
    """Последовательность из чисел (для разделителя ``x`` в ``1.2x0.8``)."""
    return all(a.name in ("int", "float") for arg in alt.args for a in arg)


def _has_nested(alt: _Ty) -> bool:
    """Элементы последовательности — сами последовательности (список точек)."""
    return any(a.name in ("list", "tuple") for arg in alt.args for a in arg)


def _split_flat(s: str, numeric: bool) -> list[str]:
    """Разбить список: запятые, точки с запятой, пробелы (для чисел ещё ``x``: ``1.2x0.8``)."""
    if numeric:
        s = re.sub(r"(?<=[\d.])[xX×*](?=[-+.\d])", ",", s)
    return [p for p in re.split(r"[,;\s]+", s.strip()) if p]


def _split_value(s: str, seqs: tuple[_Ty, ...], what: str) -> list[Any]:
    """Разбить строку значения на элементы (JSON-массив, список точек ``x,y;x,y`` или
    плоский список)."""
    if s.startswith("["):
        try:
            data = json.loads(s)
        except json.JSONDecodeError as e:
            raise _CliError(f"{what}: неверный JSON: {e.msg} (позиция {e.pos + 1})") from None
        return _stringify(data)     # текст на «[» — всегда массив
    if any(_has_nested(a) for a in seqs):
        return [_split_flat(part, True) for part in s.split(";") if part.strip()]
    if any(a.name == "tuple" and not _is_numeric_seq(a) and not a.variadic for a in seqs):
        return [p.strip() for p in s.split(",")] if s.strip() else []
    return _split_flat(s, all(_is_numeric_seq(a) for a in seqs))


def _coerce_seq(items: list[Any], seqs: tuple[_Ty, ...], what: str) -> Any:
    """Привести разобранный список к одной из альтернатив-последовательностей."""
    error: _CliError | None = None
    for alt in seqs:
        try:
            if alt.name == "list" or alt.variadic:
                elem = alt.args[0] if alt.args else (_ANY,)
                vals = [_coerce(it, elem, what) for it in items]
                return vals if alt.name == "list" else tuple(vals)
            if len(items) != len(alt.args):
                raise _CliError(f"{what}: ожидается значений: {len(alt.args)}, получено: "
                                f"{len(items)}")
            return tuple(_coerce(it, t, what) for it, t in zip(items, alt.args))
        except _CliError as e:
            error = e
    assert error is not None
    raise error


def _coerce(raw: Any, alts: tuple[_Ty, ...], what: str) -> Any:
    """Привести значение из командной строки (строку или разобранный список) к типу с
    альтернативами ``alts``; ``_CliError`` — если это невозможно."""
    kinds = {a.name for a in alts}
    seqs = tuple(a for a in alts if a.name in ("list", "tuple"))
    if isinstance(raw, list):
        if seqs:
            return _coerce_seq(raw, seqs, what)
        if len(raw) == 1:
            return _coerce(raw[0], alts, what)
        raise _CliError(f"{what}: ожидается одно значение, а не список")
    s = raw.strip()
    if "None" in kinds and s.lower() in _NONE_WORDS:
        return None
    scalars = tuple(a for a in alts if a.name not in ("list", "tuple", "None"))
    if not scalars and not seqs:
        raise _CliError(f"{what}: допустимо только значение none")
    if seqs:
        items = _split_value(s, seqs, what)
        numeric_scalar = any(a.name in ("int", "float", "bool") for a in scalars)
        if (numeric_scalar and len(items) == 1 and isinstance(items[0], str)
                and not s.startswith("[")):
            return _coerce(items[0], scalars, what)
        return _coerce_seq(items, seqs, what)
    names = {a.name for a in scalars}
    if "str" in names or "any" in names:
        return raw
    if "bool" in names:
        return _to_bool(s, what)
    if "int" in names:
        if "float" in names:
            try:
                return int(s)
            except ValueError:
                return _to_float(s, what)
        return _to_int(s, what)
    return _to_float(s, what)


# ---------------------------------------------------------------------------------------------
# set: применение
# ---------------------------------------------------------------------------------------------

class _Change(NamedTuple):
    """Изменение одного атрибута: где, старое и новое значение (текстом)."""

    where: str
    old: str
    new: str


def _what(obj: Any) -> str:
    """Название элемента в родительном падеже (для сообщений)."""
    if isinstance(obj, Footprint):
        return "корпуса"
    if isinstance(obj, Pad):
        return "площадки"
    if isinstance(obj, Drill):
        return "отверстия"
    if isinstance(obj, Graphic):
        return f"графики ({obj.kind})"
    if isinstance(obj, Text):
        return "текста"
    if isinstance(obj, Model):
        return "3D-модели"
    return type(obj).__name__


def _no_attr(obj: Any, attr: str, where: str) -> _CliError:
    """Ошибка «нет такого атрибута» со списком изменяемых атрибутов."""
    return _CliError(f"{where}: у {_what(obj)} нет атрибута «{attr}»; изменяемые атрибуты: "
                     f"{', '.join(_settable_names(type(obj)))}")


def _apply_property(fp: Footprint, key: str, raw: str) -> tuple[list[_Change], list[str]]:
    """``property[КЛЮЧ] VALUE``: присвоить или удалить (``none``) свойство корпуса."""
    props = fp.properties
    where = f"property[{key}]"
    old = _show(props.get(key))
    if raw.strip().lower() in _NONE_WORDS:
        if key not in props:
            return [], [f"{where}: свойства нет — удалять нечего"]
        del props[key]
    else:
        try:
            props[key] = raw
        except (ValueError, TypeError) as e:
            raise _CliError(f"{where}: {_exc_text(e)}") from None
    return [_Change(where, old, _show(props.get(key)))], []


def _apply_set(fp: Footprint, sel: _Selector, raw: str) -> tuple[list[_Change], list[str]]:
    """Применить ``set`` к корпусу: список изменений и примечаний о пропущенных элементах
    (промежуточный атрибут отсутствует, например ``drill`` у SMD-площадки).
    ``_CliError`` — неизвестный/неизменяемый атрибут или недопустимое значение."""
    if sel.kind == "property":
        return _apply_property(fp, _unquote(sel.index or ""), raw)
    changes: list[_Change] = []
    skipped: list[str] = []
    for label, view in _resolve(sel, fp):
        obj: Any = view
        where = label
        missing = False
        for part in sel.attrs[:-1]:
            if _property_of(type(obj), part) is None:
                raise _no_attr(obj, part, where)
            nxt = getattr(obj, part)
            where = f"{where}.{part}"
            if nxt is None:
                skipped.append(f"{where}: нет значения — элемент пропущен")
                missing = True
                break
            if not isinstance(nxt, View):
                raise _CliError(f"{where}: значение {_show(nxt)} не имеет атрибутов — "
                                f"задайте {where} целиком")
            obj = nxt
        if missing:
            continue
        attr = sel.attrs[-1]
        prop = _property_of(type(obj), attr)
        if prop is None:
            raise _no_attr(obj, attr, where)
        full = f"{where}.{attr}"
        if prop.fset is None:
            raise _CliError(f"{full}: атрибут только для чтения")
        current = getattr(obj, attr)
        old = _show(current)
        value = _coerce(raw, _attr_type(type(obj), attr, prop, current), full)
        try:
            setattr(obj, attr, value)
        except (ValueError, TypeError, KeyError) as e:
            msg = _exc_text(e)
            if msg.startswith(f"{attr}:"):      # модель уже назвала атрибут
                msg = msg[len(attr) + 1:].lstrip()
            raise _CliError(f"{full}: {msg}") from None
        changes.append(_Change(full, old, _show(getattr(obj, attr))))
    return changes, skipped


def _issue_key(i: Issue) -> tuple[str, str, str]:
    """Ключ замечания для сравнения «до/после» изменения."""
    return (i.level, i.code, i.message)


@dataclass
class _SetResult:
    """Результат ``set`` для одного корпуса."""

    entry: _Entry
    changes: list[_Change]
    modified: bool
    issues: list[Issue] = field(default_factory=list)
    new_issues: list[Issue] = field(default_factory=list)


def _warn_name_mismatch(sel: _Selector, fp: Footprint, target: Path) -> None:
    """Предупредить, что новое имя корпуса не совпадает с именем файла."""
    if sel.kind == "footprint" and sel.attrs == ("name",) and target.stem != fp.name:
        _err(f"предупреждение: имя корпуса «{fp.name}» не совпадает с именем файла "
             f"{target.name} (KiCad показывает корпус под именем файла)")


def _cmd_set(ns: argparse.Namespace, extras: list[str]) -> int:
    """``set PATH SELECTOR VALUE``: изменить свойство; без ``--write``/``-o`` файлы не
    меняются (см. описание модуля)."""
    sel = _parse_selector(ns.selector)
    src = _Source(ns.path, ns.fp)
    if src.kind == "legacy":
        raise _CliError(f"{src.path}: библиотека старого формата .mod только читается — "
                        f"преобразуйте её: kicadfp convert {src.path} -o КАТАЛОГ.pretty")
    results: list[_SetResult] = []
    errors: list[str] = []
    notes: list[str] = []
    for entry in src.entries():
        if entry.error is not None:
            errors.append(_error_text(entry.error, entry.path))
            continue
        fp = entry.fp
        assert fp is not None
        prefix = _prefix(src, entry)
        before_node = fp.node.copy()
        before = {_issue_key(i) for i in fp.validate()}
        try:
            changes, skipped = _apply_set(fp, sel, ns.value)
        except _CliError as e:
            errors.append(f"{prefix}{e}")
            continue
        notes.extend(prefix + s for s in skipped)
        if not changes:
            if src.single:
                what = "ни один элемент не изменён" if skipped else "не нашёл элементов"
                errors.append(f"селектор «{sel.text}» {what} в корпусе {entry.name}")
            continue
        after = list(fp.validate())
        modified = not _sexpr.equal(before_node, fp.node, numeric_tol=0.0, ignore_quotes=False)
        results.append(_SetResult(entry, changes, modified, after,
                                  [i for i in after if _issue_key(i) not in before]))
    for note in notes:
        _err(f"примечание: {note}")
    if errors:
        for msg in errors[:_MAX_ERRORS]:
            _err(f"ошибка: {msg}")
        if len(errors) > _MAX_ERRORS:
            _err(f"… и ещё ошибок: {len(errors) - _MAX_ERRORS}")
        if not src.single:
            _err("файлы не изменены")
        return EXIT_ERROR
    if not results:
        raise _CliError(f"селектор «{sel.text}» не нашёл элементов ни в одном корпусе "
                        f"библиотеки {src.path}")

    write = bool(ns.write or ns.output)
    report = _out if (write or not src.single) else _err
    for r in results:
        prefix = _prefix(src, r.entry)
        for c in r.changes:
            if c.old == c.new:
                report(f"{prefix}{c.where}: {c.new} (без изменений)")
            else:
                report(f"{prefix}{c.where}: {c.old} -> {c.new}")
        for issue in r.new_issues:
            _err(f"предупреждение: {prefix}после изменения: {issue}")
    if ns.strict:
        bad = [r for r in results if any(i.level == "error" for i in r.issues)]
        if bad:
            for r in bad:
                for issue in r.issues:
                    if issue.level == "error":
                        _err(f"{_prefix(src, r.entry)}{issue}")
            _err("строгая проверка: есть ошибки — ничего не записано")
            return EXIT_ISSUES
    if not write:
        if src.single:
            fp = results[0].entry.fp
            assert fp is not None
            _emit_file_text(_io.dumps(fp))
            _err("файл не изменён (для записи используйте --write или -o ФАЙЛ)")
        else:
            _err("файлы не изменены (для записи используйте --write или -o КАТАЛОГ)")
        return EXIT_OK
    if ns.write:
        for r in results:
            fp = r.entry.fp
            assert fp is not None
            if r.modified:
                _io.save(fp, r.entry.path)
                _out(f"записан: {r.entry.path}")
                _warn_name_mismatch(sel, fp, r.entry.path)
            else:
                _out(f"без изменений (значения уже такие): {r.entry.path}")
        return EXIT_OK
    if src.single:
        r = results[0]
        fp = r.entry.fp
        assert fp is not None
        target = _output_path(ns.output, r.entry.path.name if src.kind == "file"
                              else _file_name(r.entry.name))
        _io.save(fp, target)
        _out(f"записан: {target}")
        _warn_name_mismatch(sel, fp, target)
        return EXIT_OK
    assert src.library is not None
    out_dir = _output_dir(ns.output, src.path)
    by_name = {r.entry.name: r for r in results}
    for name in src.names:
        target = out_dir / (name + FOOTPRINT_EXT)
        r = by_name.get(name)
        if r is not None and r.modified:
            assert r.entry.fp is not None
            _io.save(r.entry.fp, target)
        else:
            shutil.copyfile(src.library.path_of(name), target)
    changed = sum(1 for r in results if r.modified)
    _out(f"записано файлов: {len(src.names)} в {out_dir} (изменено корпусов: {changed})")
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# gen
# ---------------------------------------------------------------------------------------------

_GEN_COMMON = frozenset(("help", "output", "params", "name", "list", "strict", "o", "h"))


def _gen_metavar(type_text: str) -> str:
    """Подсказка значения параметра генератора в справке."""
    t = type_text.replace(" ", "")
    if "list[" in t:
        return "JSON"
    if "tuple" in t:
        return "X[,Y]"
    if t.startswith("bool"):
        return "yes|no"
    if t.startswith("int"):
        return "N"
    if t.startswith("float"):
        return "ЧИСЛО"
    return "ТЕКСТ"


def _gen_default(v: Any) -> str:
    """Умолчание параметра генератора текстом."""
    if v is None:
        return "вычисляется"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return _num(v)
    if isinstance(v, tuple):
        return ",".join(_num(x) for x in v)
    return str(v)


def _gen_param_parser(kind: str, base: argparse.ArgumentParser) -> _Parser:
    """Разборщик параметров генератора ``kind`` (``--имя-параметра ЗНАЧЕНИЕ``); общие
    параметры ``gen`` показываются в справке отдельной группой."""
    pp = _Parser(prog=f"{base.prog} {kind}", add_help=False,
                 description=f"{_plain(_gen.summary(kind))}\n\nПараметры генератора задаются как "
                             f"--имя-параметра ЗНАЧЕНИЕ; значения строк, чисел, пар (1.6,1.6), "
                             f"логические (yes/no); списки — JSON.")
    common = pp.add_argument_group("общие параметры gen")
    common.add_argument("-h", "--help", action="store_true", dest="_help",
                        help="показать эту справку")
    common.add_argument("-o", "--output", metavar="OUT", dest="_output",
                        help="файл .kicad_mod или каталог .pretty (без -o — вывод в stdout)")
    common.add_argument("--params", metavar="FILE.json", dest="_params",
                        help="параметры из JSON-файла (командная строка важнее)")
    common.add_argument("--name", metavar="ИМЯ", dest="_name", help="имя корпуса")
    common.add_argument("--list", action="store_true", dest="_list",
                        help="список параметров генератора")
    common.add_argument("--strict", action="store_true", dest="_strict",
                        help="не записывать при ошибках проверки")
    own = pp.add_argument_group(f"параметры генератора {kind}")
    for info in _gen.describe(kind):
        if info.name in _GEN_COMMON:
            continue
        flag = "--" + info.name.replace("_", "-")
        flags = [flag] if "_" not in info.name else [flag, "--" + info.name]
        help_text = (f"{_plain(info.description)} [{info.type}; по умолчанию: "
                     f"{_gen_default(info.default)}]").replace("%", "%%")
        kw: dict[str, Any] = {"dest": info.name, "default": None,
                              "metavar": _gen_metavar(info.type), "help": help_text}
        if info.type.replace(" ", "") in ("bool", "bool|None"):
            kw.update(nargs="?", const="true")
        own.add_argument(*flags, **kw)
    return pp


def _plain(text: str) -> str:
    """Текст docstring без разметки reStructuredText (````x```` -> ``x``)."""
    return text.replace("``", "")


def _print_generators() -> None:
    """``gen --list``: генераторы и синонимы."""
    _out("Генераторы (параметры: kicadfp gen KIND --list):")
    width = max(len(n) for n in _gen.GENERATORS) + 2
    for name in _gen.GENERATORS:
        _out(f"  {name:<{width}}{_plain(_gen.summary(name))}")
    if _gen.ALIASES:
        _out("Синонимы: " + ", ".join(f"{a} = {t}" for a, t in _gen.ALIASES.items()))


def _print_gen_params(kind: str) -> None:
    """``gen KIND --list``: параметры генератора."""
    _out(f"Параметры генератора {kind} (kicadfp gen {kind} --ПАРАМЕТР ЗНАЧЕНИЕ):")
    rows = [["--" + p.name.replace("_", "-"), p.type, _gen_default(p.default),
             _plain(p.description)] for p in _gen.describe(kind)]
    for line in _table(("параметр", "тип", "по умолчанию", "описание"), rows):
        _out("  " + line)


def _read_params_json(path: str) -> dict[str, Any]:
    """Параметры генератора из JSON-файла (объект ``{имя: значение}``)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise _CliError(_os_error_text(e)) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise _CliError(f"{p}: неверный JSON: строка {e.lineno}, позиция {e.colno}: "
                        f"{e.msg}") from None
    if not isinstance(data, dict):
        raise _CliError(f"{p}: ожидается JSON-объект {{\"параметр\": значение, …}}")
    return {str(k).replace("-", "_"): v for k, v in data.items()}


def _rename(fp: Footprint, name: str) -> None:
    """Задать имя корпуса; текст Value, равный прежнему имени, тоже меняется."""
    old = fp.name
    if old == name:
        return
    fp.name = name
    value = fp.value
    if value is not None and value.text == old:
        value.text = name


def _cmd_gen(ns: argparse.Namespace, extras: list[str]) -> int:
    """``gen KIND [--параметр значение …]``: создать корпус генератором."""
    if ns.kind is None:
        if ns.help:
            ns.cmd_parser.print_help(sys.stdout)
            _out()
            _print_generators()
            return EXIT_OK
        if ns.list:
            _print_generators()
            return EXIT_OK
        raise _UsageError(ns.cmd_parser, "не указан генератор KIND (список: kicadfp gen --list)")
    try:
        func = _gen.get(ns.kind)
    except KeyError as e:
        raise _CliError(_exc_text(e)) from None
    kind = next(k for k, f in _gen.GENERATORS.items() if f is func)
    pp = _gen_param_parser(kind, ns.cmd_parser)
    if ns.help:
        pp.print_help(sys.stdout)
        return EXIT_OK
    if ns.list:
        _print_gen_params(kind)
        return EXIT_OK
    pns = pp.parse_args(extras)
    params: dict[str, Any] = _read_params_json(ns.params) if ns.params else {}
    params.update({k: v for k, v in vars(pns).items() if v is not None and not k.startswith("_")})
    accepted = {p.name for p in _gen.describe(kind)}
    name = ns.name
    if name is None and "name" not in params and ns.output and not _is_dir_target(ns.output):
        name = Path(ns.output).stem       # KiCad отождествляет имя корпуса с именем файла
    if name is not None:
        if not name.strip():
            raise _CliError("имя корпуса не может быть пустым")
        if "name" in accepted:
            params["name"] = name
    try:
        fp = _gen.from_json(kind, params)
    except (KeyError, ValueError, TypeError) as e:
        raise _CliError(f"gen {kind}: {_exc_text(e)}") from None
    if name is not None and "name" not in accepted:
        _rename(fp, name)
    issues = list(fp.validate())
    for issue in issues:
        label = "предупреждение" if issue.level == "warning" else "ошибка проверки"
        _err(f"{label}: {issue}")
    if ns.strict and any(i.level == "error" for i in issues):
        _err("строгая проверка: есть ошибки — корпус не записан")
        return EXIT_ISSUES
    if not ns.output:
        _emit_file_text(_io.dumps(fp))
        return EXIT_OK
    target = _output_path(ns.output, _file_name(fp.name))
    _io.save(fp, target)
    _out(f"записан: {target} (корпус {fp.name}, площадок: {len(fp.pads)})")
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------------------------

def _canonical_text(fp: Footprint, style: str) -> str:
    """Текст корпуса в каноническом форматировании с проверкой, что дерево не изменилось."""
    text = _io.dumps(fp, style=style)
    try:
        again = _sexpr.parse(text)
    except SexprSyntaxError as e:   # pragma: no cover - защита от ошибки writer'а
        raise _CliError(f"внутренняя ошибка форматирования: {e}") from None
    if not _sexpr.equal(again, fp.node, numeric_tol=0.0, ignore_quotes=False):
        raise _CliError("форматирование изменило бы содержание файла — файл не записан "
                        "(внутренняя ошибка kicadfp)")    # pragma: no cover
    return text


def _first_diff_line(a: bytes, b: bytes) -> int:
    """Номер первой различающейся строки (с 1)."""
    la, lb = a.split(b"\n"), b.split(b"\n")
    for n, (x, y) in enumerate(zip(la, lb), start=1):
        if x != y:
            return n
    return min(len(la), len(lb)) + 1 if len(la) != len(lb) else len(la)


def _cmd_fmt(ns: argparse.Namespace, extras: list[str]) -> int:
    """``fmt PATH``: каноническое форматирование (``--check``/``--write``/``-o``)."""
    src = _Source(ns.path, ns.fp)
    if src.kind == "legacy":
        raise _CliError(f"{src.path}: файл старого формата .mod не форматируется — "
                        f"преобразуйте его: kicadfp convert {src.path} -o КАТАЛОГ.pretty")
    out_dir = _output_dir(ns.output, src.path) if ns.output and not src.single else None
    status = EXIT_OK
    total = differ = written = 0
    for entry in src.entries():
        if entry.error is not None:
            _report_read_error(entry)
            status = EXIT_ERROR
            continue
        fp = entry.fp
        assert fp is not None
        total += 1
        text = _canonical_text(fp, ns.style)
        data = text.encode("utf-8", "surrogateescape")
        original = entry.path.read_bytes()
        same = data == original
        if not same:
            differ += 1
        if ns.check:
            if not same:
                _out(f"требуется форматирование: {entry.path} (первое отличие в строке "
                     f"{_first_diff_line(original, data)})")
        elif ns.write:
            if not same:
                _io.save(fp, entry.path, style=ns.style)
                written += 1
                _out(f"переформатирован: {entry.path}")
        elif ns.output:
            target = (out_dir / entry.path.name if out_dir is not None
                      else _output_path(ns.output, entry.path.name))
            _io.save(fp, target, style=ns.style)
            written += 1
            _out(f"записан: {target}")
        elif src.single:
            _emit_file_text(text)
            _err("файл уже в каноническом форматировании" if same else
                 "файл не изменён (для записи используйте --write или -o ФАЙЛ)")
        elif not same:
            _out(f"требуется форматирование: {entry.path}")
    if ns.check:
        if differ:
            _out(f"требуют форматирования файлов: {differ} из {total}")
        elif not src.single or total:
            _out(f"все файлы в каноническом форматировании (проверено: {total})")
    elif ns.write:
        _out(f"переформатировано файлов: {written} из {total}")
    elif not ns.output and not src.single:
        _out(f"требуют форматирования файлов: {differ} из {total}")
        _err("файлы не изменены (для записи используйте --write или -o КАТАЛОГ)")
    if status != EXIT_OK:
        return status
    return EXIT_ISSUES if ns.check and differ else EXIT_OK


# ---------------------------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------------------------

def _print_legacy_issues(issues: list[Any]) -> None:
    """Замечания конвертации старой библиотеки — в stderr."""
    for issue in issues:
        module = getattr(issue, "module", "")
        where = f" (строка {issue.line})" if getattr(issue, "line", 0) else ""
        _err(f"предупреждение: {module + ': ' if module else ''}{issue.message}{where}")


def _cmd_convert(ns: argparse.Namespace, extras: list[str]) -> int:
    """``convert IN.mod -o OUT.pretty``: старую библиотеку — в каталог ``.pretty``."""
    p = Path(ns.path)
    if not p.exists():
        raise _CliError(f"{p}: файл не найден")
    if p.is_dir():
        raise _CliError(f"{p}: ожидается файл библиотеки .mod, а не каталог")
    if _io.detect_format(_read_head(p)) != "legacy":
        raise _CliError(f"{p}: не библиотека старого формата PCBNEW-LibModule-V1 (.mod)")
    issues: list[Any] = []
    if not ns.output:
        fps = _legacy.read_library(p, compat=ns.compat, issues=issues)
        _print_legacy_issues(issues)
        for fp in fps:
            _out(f"{fp.name} (площадок: {len(fp.pads)})")
        _err(f"файлы не записаны: укажите каталог результата, например "
             f"kicadfp convert {p} -o {p.with_suffix('.pretty').name}")
        return EXIT_OK
    out = Path(ns.output)
    if out.exists() and not out.is_dir():
        raise _CliError(f"{out}: это файл — укажите каталог .pretty")
    paths = _legacy.convert(p, out, compat=ns.compat, issues=issues)
    _print_legacy_issues(issues)
    for q in paths:
        _out(f"записан: {q}")
    _out(f"преобразовано корпусов: {len(paths)} -> {out}")
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------------------------

def _parse_layers(text: str | None) -> list[str] | None:
    """Список слоёв ``--layers`` (``_CliError`` — неизвестное имя)."""
    if text is None:
        return None
    names = [n for n in re.split(r"[,\s]+", text.strip()) if n]
    for name in names:
        if not _L.is_valid_layer(name):
            raise _CliError(f"--layers: неизвестный слой «{name}»")
    return names


def _image_format(target: Path, fmt: str | None) -> str:
    """Формат изображения по расширению файла (или ``--format``)."""
    ext = target.suffix.lower().lstrip(".")
    if ext in _IMAGE_FORMATS:
        if fmt is not None and fmt != ext:
            raise _CliError(f"--format {fmt} не совпадает с расширением файла {target.name}")
        return ext
    if fmt is not None:
        return fmt
    raise _CliError(f"{target}: неизвестный формат изображения — используйте расширение .svg "
                    f"или .png (или --format)")


def _render_to(fp: Footprint, target: Path, fmt: str, ns: argparse.Namespace,
               kw: dict[str, Any]) -> None:
    """Записать изображение корпуса в файл."""
    if target.parent != Path(""):
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if fmt == "png":
            _render.save_png(fp, target, width=ns.width, **kw)
        else:
            _render.save_svg(fp, target, scale=ns.scale, **kw)
    except RuntimeError as e:
        raise _CliError(str(e)) from None


def _cmd_render(ns: argparse.Namespace, extras: list[str]) -> int:
    """``render PATH [-o OUT.svg|OUT.png|КАТАЛОГ]``: изображение корпуса."""
    if not ns.scale > 0 or math.isinf(ns.scale):
        raise _CliError(f"--scale: ожидается положительное число, получено {ns.scale}")
    if ns.width <= 0:
        raise _CliError(f"--width: ожидается положительное число, получено {ns.width}")
    if not ns.no_grid and not ns.grid > 0:
        raise _CliError(f"--grid: ожидается положительный шаг, получено {ns.grid}")
    if not ns.margin >= 0 or math.isinf(ns.margin):
        raise _CliError(f"--margin: ожидается неотрицательное число, получено {ns.margin}")
    kw: dict[str, Any] = {"layers": _parse_layers(ns.layers),
                          "grid": None if ns.no_grid else ns.grid,
                          "background": not ns.no_background, "margin": ns.margin,
                          "show_hidden": ns.show_hidden, "pad_numbers": ns.pad_numbers}
    src = _Source(ns.path, ns.fp)
    to_dir = ns.output is not None and _is_dir_target(ns.output, pretty=False)
    if src.single and not to_dir:
        entry = next(src.entries())
        if entry.error is not None:
            _report_read_error(entry)
            return EXIT_ERROR
        assert entry.fp is not None
        if ns.output is None:
            if ns.format == "png":
                raise _CliError("PNG не выводится в stdout — укажите -o ФАЙЛ.png")
            _emit_file_text(_render.render_svg(entry.fp, scale=ns.scale, **kw))
            return EXIT_OK
        target = Path(ns.output)
        _render_to(entry.fp, target, _image_format(target, ns.format), ns, kw)
        _out(f"записан: {target}")
        return EXIT_OK
    if ns.output is None:
        raise _CliError("для библиотеки укажите каталог результата: -o КАТАЛОГ")
    out_dir = _output_dir(ns.output)
    fmt = ns.format or "svg"
    status = EXIT_OK
    for entry in src.entries():
        if entry.error is not None:
            _report_read_error(entry)
            status = EXIT_ERROR
            continue
        assert entry.fp is not None
        target = out_dir / (sanitize_name(entry.name) + "." + fmt)
        _render_to(entry.fp, target, fmt, ns, kw)
        _out(f"записан: {target}")
    return status


# ---------------------------------------------------------------------------------------------
# gui
# ---------------------------------------------------------------------------------------------

def _load_gui_main() -> Callable[..., Any]:
    """``kicadfp.gui.main`` (ленивый импорт); ``_CliError`` — нет PySide6 или GUI."""
    install = f"для графического интерфейса нужен PySide6: установите его командой {_INSTALL_GUI}"
    try:
        spec = importlib.util.find_spec("PySide6")
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        raise _CliError(install)
    try:
        module = importlib.import_module("kicadfp.gui")
    except ImportError as e:
        if (e.name or "").split(".")[0] in ("PySide6", "shiboken6"):
            raise _CliError(install) from None
        raise _CliError(f"графический интерфейс недоступен: {e}") from None
    func = getattr(module, "main", None)
    if not callable(func):
        raise _CliError("графический интерфейс недоступен: в этой версии kicadfp нет "
                        "kicadfp.gui.main")
    return func


def _cmd_gui(ns: argparse.Namespace, extras: list[str]) -> int:
    """``gui [PATH]``: запустить графический интерфейс (``kicadfp.gui.main([PATH])``)."""
    if ns.path is not None and not Path(ns.path).exists():
        raise _CliError(f"{ns.path}: файл или каталог не найден")
    func = _load_gui_main()
    result = func([ns.path] if ns.path is not None else [])
    return int(result or 0)
