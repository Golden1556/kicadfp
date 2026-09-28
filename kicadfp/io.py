"""Чтение и запись файлов посадочных мест KiCad (architecture.md §7).

* :func:`load` / :func:`loads` — прочитать корпус; формат определяется по началу текста
  (после BOM, пробелов и строк-комментариев ``#``): ``(footprint``/``(module`` — S-выражение
  (KiCad 5–10), заголовок ``PCBNEW-LibModule-V1`` — старая библиотека ``.mod`` (читается
  модулем :mod:`kicadfp.legacy`; из библиотеки с несколькими корпусами один корпус не
  выбирается — :class:`LegacyLibraryError`); иначе — :class:`~kicadfp.sexpr.SexprSyntaxError`
  с номером строки и позицией.
* :func:`save` — атомарная запись (временный файл в том же каталоге, ``fsync``,
  ``os.replace``), UTF-8 без BOM, переводы строк LF; ``strict=True`` — сначала проверка
  (:mod:`kicadfp.validate`), при ошибках файл не пишется (:class:`ValidationError`).
* :func:`dumps` — текст корпуса в стиле KiCad (``style="auto"`` — по версии файла).

Кодировка: файлы KiCad — UTF-8. Байты, не являющиеся корректным UTF-8, читаются без
потерь (``surrogateescape``) и при записи возвращаются теми же байтами.
"""

from __future__ import annotations

import errno
import importlib
import os
import stat
import tempfile
from os import PathLike
from pathlib import Path
from typing import Any, Iterable

from . import sexpr as _sexpr
from .model import Footprint
from .sexpr import SexprSyntaxError

__all__ = [
    "load", "loads", "save", "dumps", "detect_format", "ValidationError", "LegacyLibraryError",
]

_LEGACY_HEADER = "PCBNEW-LIBMODULE-V1"


class ValidationError(Exception):
    """Корпус не прошёл проверку при ``save(..., strict=True)``; файл не записан.

    ``issues`` — полный список замечаний (:class:`kicadfp.validate.Issue`), ``errors`` —
    только ошибки.
    """

    def __init__(self, issues: Iterable[Any], path: str | None = None) -> None:
        self.issues = list(issues)
        self.path = path
        self.errors = [i for i in self.issues if getattr(i, "level", "error") == "error"]
        head = f"{path}: " if path else ""
        shown = "; ".join(str(i) for i in self.errors[:3])
        more = " …" if len(self.errors) > 3 else ""
        super().__init__(f"{head}корпус не прошёл проверку (ошибок: {len(self.errors)})"
                         + (f": {shown}{more}" if shown else ""))


class LegacyLibraryError(ValueError):
    """Файл старого формата ``PCBNEW-LibModule-V1`` нельзя прочитать как один корпус:
    в библиотеке несколько корпусов (или ни одного), либо модуль :mod:`kicadfp.legacy`
    недоступен. ``count`` — число корпусов (``None``, если файл не читался)."""

    def __init__(self, message: str, count: int | None = None) -> None:
        self.count = count
        super().__init__(message)


# ---------------------------------------------------------------------------
# Определение формата
# ---------------------------------------------------------------------------

def _first_significant(text: str) -> tuple[str, int, int]:
    """Начало первой значимой строки: ``(остаток строки, номер строки, позиция)`` (с 1);
    пропускаются BOM, пустые строки и строки-комментарии (``#`` первым непробельным
    символом, как у лексера KiCad). Пустой текст — ``("", 1, 1)``."""
    if text.startswith("﻿"):
        text = text[1:]
    for n, line in enumerate(text.split("\n"), start=1):
        stripped = line.lstrip(" \t\r\0\f\v")
        if not stripped or stripped.startswith("#"):
            continue
        return stripped, n, len(line) - len(stripped) + 1
    return "", 1, 1


def detect_format(text: str) -> str | None:
    """Формат текста: ``"sexpr"`` (начинается с ``(``), ``"legacy"`` (заголовок
    ``PCBNEW-LibModule-V1``, без учёта регистра, как в KiCad) или ``None``."""
    head, _, _ = _first_significant(text)
    if head.startswith("("):
        return "sexpr"
    if head.upper().startswith(_LEGACY_HEADER):
        return "legacy"
    return None


def _decode(data: bytes) -> str:
    """UTF-8 (BOM допускается и отбрасывается); некорректные байты сохраняются как
    суррогаты (``surrogateescape``) и при записи возвращаются без изменений."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "surrogateescape")


def _legacy_module() -> Any:
    """Модуль :mod:`kicadfp.legacy` или :class:`LegacyLibraryError`, если его нет."""
    try:
        return importlib.import_module("kicadfp.legacy")
    except ModuleNotFoundError as e:
        if e.name in ("kicadfp.legacy", "kicadfp"):
            raise LegacyLibraryError(
                "файл старого формата PCBNEW-LibModule-V1 (.mod): модуль чтения "
                "kicadfp.legacy недоступен") from None
        raise


def _single_legacy(fps: list[Footprint], source: str) -> Footprint:
    """Единственный корпус старой библиотеки или :class:`LegacyLibraryError`."""
    if len(fps) == 1:
        return fps[0]
    if not fps:
        raise LegacyLibraryError(f"{source}: в старой библиотеке .mod нет ни одного корпуса",
                                 count=0)
    raise LegacyLibraryError(
        f"{source}: старая библиотека .mod содержит {len(fps)} корпусов — прочитайте её "
        f"kicadfp.legacy.read_library() или преобразуйте в каталог .pretty "
        f"kicadfp.legacy.convert()", count=len(fps))


def _parse_footprint(text: str) -> Footprint:
    """Разобрать S-выражение и проверить, что корень — ``footprint``/``module``.

    Запоминается, оканчивался ли текст переводом строки (:attr:`Footprint.final_newline`):
    файлы KiCad 8.0.0/8.0.1 и генератора библиотек KiCad 5 его не имеют, и неизменённый
    корпус должен записаться байт в байт."""
    root = _sexpr.parse(text)
    if root.name not in ("footprint", "module"):
        raise SexprSyntaxError(
            f"ожидался корневой узел footprint или module, найден «{root.name}»",
            root.line or 1, root.col or 1)
    return Footprint(root, final_newline=text.endswith("\n"))


def _unknown_format(text: str) -> SexprSyntaxError:
    head, line, col = _first_significant(text)
    if not head:
        return SexprSyntaxError("пустой ввод: нет ни одного S-выражения", 1, 1)
    return SexprSyntaxError(
        "неизвестный формат файла: ожидалось «(footprint …)», «(module …)» или заголовок "
        "PCBNEW-LibModule-V1", line, col)


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

def loads(text: str | bytes) -> Footprint:
    """Прочитать корпус из текста (формат определяется автоматически, см. модуль).

    Ошибки: :class:`~kicadfp.sexpr.SexprSyntaxError` (``строка N, позиция M: …``) —
    синтаксис или неизвестный формат; :class:`LegacyLibraryError` — старая библиотека
    ``.mod`` не из одного корпуса.
    """
    if isinstance(text, (bytes, bytearray)):
        text = _decode(bytes(text))
    kind = detect_format(text)
    if kind == "sexpr":
        return _parse_footprint(text)
    if kind == "legacy":
        mod = _legacy_module()
        return _single_legacy(list(mod.loads_library(text)), "текст")
    raise _unknown_format(text)


def load(path: str | PathLike[str]) -> Footprint:
    """Прочитать корпус из файла ``.kicad_mod`` (KiCad 5–10) или ``.mod`` с одним корпусом.

    Ошибка синтаксиса — :class:`~kicadfp.sexpr.SexprSyntaxError` с позицией (атрибут
    ``path`` — путь к файлу); прочие — как у :func:`loads`.
    """
    p = Path(path)
    data = p.read_bytes()
    text = _decode(data)
    kind = detect_format(text)
    try:
        if kind == "sexpr":
            return _parse_footprint(text)
        if kind == "legacy":
            mod = _legacy_module()
            fps = mod.read_library(p) if hasattr(mod, "read_library") else mod.loads_library(text)
            return _single_legacy(list(fps), str(p))
        raise _unknown_format(text)
    except SexprSyntaxError as e:
        e.path = str(p)  # type: ignore[attr-defined]
        raise


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

def dumps(fp: Footprint, *, style: str = "auto", final_newline: bool | None = None) -> str:
    """Текст корпуса в стиле KiCad: ``auto`` — по версии файла (KiCad 8+ — Prettify, 6/7 —
    раскладка writer'а 6.0/7.0, ``module`` — 5.1), либо явно ``kicad8``/``kicad7``/
    ``kicad6``/``kicad5``. Переводы строк — LF.

    Завершающий перевод строки — как в прочитанном файле (:attr:`Footprint.final_newline`;
    у новых корпусов он есть): файлы KiCad 8.0.0/8.0.1 оканчиваются на ``)`` без ``\n``,
    и открытый без изменений файл записывается байт в байт. ``final_newline=True``/``False``
    задаёт его явно."""
    if not isinstance(fp, Footprint):
        raise TypeError("dumps: ожидается Footprint")
    return fp.dumps(style=style, final_newline=final_newline)


def _has_errors(issues: list[Any]) -> bool:
    try:
        mod = importlib.import_module("kicadfp.validate")
        fn = getattr(mod, "has_errors", None)
        if callable(fn):
            return bool(fn(issues))
    except ModuleNotFoundError:
        pass
    return any(getattr(i, "level", None) == "error" for i in issues)


def _default_mode() -> int:
    """Права нового файла: ``0o666`` с учётом umask процесса (как у ``open()``)."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def _fsync_dir(directory: Path) -> None:
    """``fsync`` каталога после ``os.replace`` (POSIX; ошибки игнорируются)."""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Записать ``data`` в ``path`` атомарно: временный файл в том же каталоге, запись,
    ``flush`` + ``fsync``, права как у заменяемого файла (или ``0o666 & ~umask``),
    ``os.replace``. При ошибке временный файл удаляется, исходный файл не меняется.
    Символическая ссылка не заменяется файлом: пишется файл, на который она указывает.

    Существующий не обычный файл (FIFO, символьное устройство вроде ``/dev/null`` или
    ``/dev/stdout``) не заменяется обычным файлом: данные пишутся в него напрямую
    (``open(path, "wb")``, как перенаправление ``>`` в оболочке), без временного файла и
    ``os.replace`` — атомарность для таких целей не имеет смысла. Каталог —
    :class:`IsADirectoryError`, цель не меняется."""
    if path.is_symlink():
        path = Path(os.path.realpath(path))
    directory = path.parent
    try:
        st = os.stat(path)
    except FileNotFoundError:
        mode = _default_mode()
    else:
        if stat.S_ISDIR(st.st_mode):
            raise IsADirectoryError(errno.EISDIR, "путь — каталог, а не файл", str(path))
        if not stat.S_ISREG(st.st_mode):
            with open(path, "wb") as f:
                f.write(data)
            return
        mode = stat.S_IMODE(st.st_mode)
    tmp = tempfile.NamedTemporaryFile(dir=directory, prefix="." + path.name + ".",
                                      suffix=".tmp", delete=False)
    tmp_name = tmp.name
    try:
        with tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _fsync_dir(directory)


def save(fp: Footprint, path: str | PathLike[str], *, strict: bool = False,
         style: str = "auto", final_newline: bool | None = None) -> None:
    """Записать корпус в файл атомарно (UTF-8 без BOM, LF).

    ``strict=True`` — сначала ``fp.validate(strict=True)``; если есть замечания уровня
    ``error`` — :class:`ValidationError`, файл не пишется (пока модуля
    :mod:`kicadfp.validate` нет, проверка пропускается). ``style`` и ``final_newline`` —
    как у :func:`dumps` (по умолчанию завершающий перевод строки — как в прочитанном файле).
    """
    if not isinstance(fp, Footprint):
        raise TypeError("save: ожидается Footprint")
    p = Path(path)
    if strict:
        issues = list(fp.validate(strict=True))
        if _has_errors(issues):
            raise ValidationError(issues, str(p))
    text = dumps(fp, style=style, final_newline=final_newline)
    _atomic_write(p, text.encode("utf-8", "surrogateescape"))
