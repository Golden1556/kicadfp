"""Библиотека посадочных мест — каталог ``.pretty`` (architecture.md §9).

Каталог ``<имя>.pretty`` содержит по файлу ``<имя корпуса>.kicad_mod`` на корпус; имя
корпуса в библиотеке — имя файла без расширения (так KiCad строит ``LIB_ID``: при чтении
библиотеки имя берётся из имени файла, при записи файл называется по имени корпуса, и
поле ``name`` корня совпадает с ним).

Модель работы :class:`Library`:

* перечисление (:attr:`Library.names`, :meth:`Library.list`, ``iter``, ``len``, ``in``) —
  файлы ``*.kicad_mod`` каталога плюс корпуса, добавленные :meth:`Library.add` и ещё не
  записанные;
* :meth:`Library.get` читает файл один раз и кэширует корпус; изменения этого объекта
  записываются :meth:`Library.save` / :meth:`Library.save_all`;
* :meth:`Library.add` регистрирует корпус в памяти (файл пишется при сохранении);
  :meth:`Library.remove`, :meth:`Library.rename`, :meth:`Library.copy_to` меняют файлы
  сразу;
* запись — только через :func:`kicadfp.io.save` (атомарно: временный файл + ``os.replace``).

Имена корпусов: при :meth:`~Library.add`, :meth:`~Library.rename` и
:meth:`~Library.copy_to` новое имя нормализуется :func:`sanitize_name`, и поле ``name``
внутри корпуса приводится к нему.
"""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path
from typing import Any, Iterator

from . import io as _io
from .model import Footprint
from .sexpr import Node, SexprSyntaxError, equal

__all__ = ["Library", "sanitize_name", "FOOTPRINT_EXT", "ILLEGAL_NAME_CHARS"]

#: Расширение файла корпуса (как ``FILEEXT::KiCadFootprintFileExtension`` KiCad).
FOOTPRINT_EXT = ".kicad_mod"

#: Печатные символы, заменяемые на ``_`` в имени корпуса (кроме них заменяются все
#: управляющие символы с кодом < 0x20). ``: \\ < > "`` — недопустимые символы
#: ``LIB_ID::isLegalChar`` KiCad; ``/ * ? |`` — недопустимые в именах файлов Windows/POSIX.
ILLEGAL_NAME_CHARS = frozenset('/\\:*?"<>|')

_LIBRARY_EXT = ".pretty"


def _is_legal_char(ch: str) -> bool:
    """Допустим ли символ в имени корпуса (см. :func:`sanitize_name`)."""
    return ch >= " " and ch not in ILLEGAL_NAME_CHARS


def sanitize_name(name: str) -> str:
    """Имя корпуса, пригодное для имени файла: каждый недопустимый символ заменён на ``_``.

    Поведение — как ``LIB_ID::FixIllegalChars(name, false)`` KiCad (посимвольная замена на
    ``'_'``, длина в символах Unicode не меняется, пробелы допустимы, обрезки нет).
    Недопустимые символы: все управляющие (код < 0x20, в том числе табуляция и переводы
    строк) и ``/ \\ : * ? " < > |``.

    Отличие от KiCad: ``LIB_ID::isLegalChar`` не считает недопустимыми ``/ * ? |`` (KiCad
    заменяет только ``: \\ < > "`` и управляющие), но в имени файла они недопустимы
    (``/`` — разделитель каталогов, ``* ? |`` запрещены в Windows), поэтому здесь они
    тоже заменяются. Символы ``%`` и ``$``, которые запрещает диалог свойств корпуса KiCad
    (``FOOTPRINT::StringLibNameInvalidChars``), не заменяются: KiCad читает и пишет файлы с
    ними.

    ``ValueError`` — пустое имя; ``TypeError`` — не строка.
    """
    if not isinstance(name, str):
        raise TypeError(f"имя корпуса должно быть строкой, а не {type(name).__name__}")
    if not name:
        raise ValueError("имя корпуса не может быть пустым")
    return "".join(ch if _is_legal_char(ch) else "_" for ch in name)


def _check_file_name(name: str) -> str:
    """Проверить, что ``name`` — имя корпуса, из которого получается имя файла в каталоге
    библиотеки (без разделителей каталогов и нулевого символа); вернуть его же."""
    if not isinstance(name, str):
        raise TypeError(f"имя корпуса должно быть строкой, а не {type(name).__name__}")
    if not name:
        raise ValueError("имя корпуса не может быть пустым")
    bad = {"/", "\0", os.sep} | ({os.altsep} if os.altsep else set())
    if any(ch in bad for ch in name):
        raise ValueError(f"имя корпуса {name!r} содержит разделитель каталогов или нулевой "
                         f"символ (используйте sanitize_name)")
    return name


class Library:
    """Библиотека посадочных мест — каталог ``.pretty`` (architecture.md §9).

    ``Library(path)`` открывает существующий каталог (``FileNotFoundError``, если его нет;
    ``NotADirectoryError``, если это файл); ``create=True`` создаёт каталог (с
    родительскими). Атрибуты: :attr:`path` — путь к каталогу, :attr:`name` — имя
    библиотеки (имя каталога без ``.pretty``).

    Кэш: :meth:`get` читает файл при первом обращении и далее возвращает тот же объект
    :class:`~kicadfp.model.Footprint`; его изменения попадают в файл при :meth:`save` /
    :meth:`save_all`. Для прочитанных корпусов запоминается снимок дерева, и
    :meth:`save_all` перезаписывает только изменённые (неизменённые файлы не трогаются —
    ни байты, ни время изменения). Изменения каталога другими программами после чтения
    не отслеживаются (см. :meth:`refresh`).
    """

    def __init__(self, path: str | PathLike[str], create: bool = False) -> None:
        p = Path(path)
        if create:
            p.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            raise FileNotFoundError(f"библиотека не найдена: {p}")
        if not p.is_dir():
            raise NotADirectoryError(f"библиотека должна быть каталогом (.pretty): {p}")
        #: Путь к каталогу библиотеки.
        self.path: Path = p
        #: Имя библиотеки: имя каталога без расширения ``.pretty``.
        self.name: str = p.name[:-len(_LIBRARY_EXT)] if (
            p.name.endswith(_LIBRARY_EXT) and len(p.name) > len(_LIBRARY_EXT)) else p.name
        # Корпуса в памяти: прочитанные get() и добавленные add().
        self._cache: dict[str, Footprint] = {}
        # Снимки прочитанных/записанных корпусов: (копия дерева, final_newline).
        self._snapshots: dict[str, tuple[Node, bool]] = {}
        # Имена, добавленные add() и ещё не записанные (файл пишется при сохранении).
        self._pending: set[str] = set()

    # --- перечисление ---------------------------------------------------------------------
    def _disk_names(self) -> set[str]:
        """Имена файлов ``*.kicad_mod`` каталога (без расширения; только обычные файлы)."""
        out: set[str] = set()
        try:
            entries = list(os.scandir(self.path))
        except FileNotFoundError:
            return out
        for e in entries:
            fn = e.name
            if not fn.endswith(FOOTPRINT_EXT) or len(fn) == len(FOOTPRINT_EXT):
                continue
            try:
                if not e.is_file():
                    continue
            except OSError:
                continue
            out.add(fn[:-len(FOOTPRINT_EXT)])
        return out

    @property
    def names(self) -> list[str]:
        """Отсортированные имена корпусов: файлы ``*.kicad_mod`` без расширения плюс
        добавленные :meth:`add` и ещё не записанные."""
        return sorted(self._disk_names() | self._pending)

    def list(self) -> list[str]:
        """То же, что :attr:`names`."""
        return self.names

    def __iter__(self) -> Iterator[str]:
        """Имена корпусов (в порядке :attr:`names`)."""
        return iter(self.names)

    def __len__(self) -> int:
        return len(self._disk_names() | self._pending)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str) or not name:
            return False
        if name in self._pending:
            return True
        try:
            return self.path_of(name).is_file()
        except ValueError:
            return False

    def __repr__(self) -> str:
        return f"Library({str(self.path)!r})"

    # --- пути -----------------------------------------------------------------------------
    def path_of(self, name: str) -> Path:
        """Путь к файлу корпуса ``name``: ``<path>/<name>.kicad_mod`` (файла может ещё не
        быть). Имя не нормализуется; ``ValueError`` — пустое имя или имя с разделителем
        каталогов (такого файла в каталоге быть не может)."""
        return self.path / (_check_file_name(name) + FOOTPRINT_EXT)

    def _exists(self, name: str) -> bool:
        """Есть ли корпус (файл или добавленный в памяти)."""
        return name in self._pending or self.path_of(name).is_file()

    def _require(self, name: str) -> None:
        """``KeyError``, если корпуса ``name`` нет в библиотеке."""
        try:
            ok = self._exists(name)
        except ValueError:
            ok = False
        if not ok:
            raise KeyError(f"в библиотеке {self.name} нет корпуса {name!r}")

    # --- чтение ---------------------------------------------------------------------------
    def get(self, name: str) -> Footprint:
        """Корпус ``name`` (из кэша или прочитанный из файла и закэшированный).

        ``KeyError`` — корпуса нет; ошибки разбора файла
        (:class:`~kicadfp.sexpr.SexprSyntaxError` с позицией) передаются как есть, в кэш
        ничего не попадает.
        """
        fp = self._cache.get(name)
        if fp is not None:
            return fp
        self._require(name)
        fp = _io.load(self.path_of(name))
        self._cache[name] = fp
        self._snapshots[name] = (fp.node.copy(), fp.final_newline)
        return fp

    def is_modified(self, name: str) -> bool:
        """Есть ли у корпуса ``name`` незаписанные изменения: добавлен :meth:`add` и не
        записан, либо прочитанный объект изменён после чтения/записи. Не прочитанный
        корпус не изменён; ``KeyError`` — корпуса нет."""
        if name in self._pending:
            return True
        fp = self._cache.get(name)
        if fp is None:
            self._require(name)
            return False
        snap = self._snapshots.get(name)
        if snap is None:
            return True
        node, final_newline = snap
        return (fp.final_newline != final_newline
                or not equal(node, fp.node, numeric_tol=0.0, ignore_quotes=False))

    @property
    def unsaved(self) -> list[str]:
        """Отсортированные имена корпусов с незаписанными изменениями (:meth:`is_modified`)."""
        return sorted(n for n in set(self._cache) | self._pending if self.is_modified(n))

    def refresh(self) -> None:
        """Забыть прочитанные и не изменённые корпуса (следующий :meth:`get` перечитает
        файл). Добавленные и изменённые корпуса остаются в памяти."""
        for n in [n for n in self._cache if not self.is_modified(n)]:
            del self._cache[n]
            self._snapshots.pop(n, None)

    # --- изменение ------------------------------------------------------------------------
    @staticmethod
    def _assign_name(fp: Footprint, new: str) -> None:
        """Привести поле ``name`` корпуса к ``new``; если текст Value совпадал со старым
        именем (так у корпусов стандартных библиотек KiCad), он тоже заменяется на ``new``."""
        old = fp.name
        if old == new:
            return
        fp.name = new
        value = fp.value
        if value is not None and value.text == old:
            value.text = new

    def add(self, fp: Footprint, name: str | None = None, overwrite: bool = False) -> None:
        """Зарегистрировать корпус в памяти под именем ``name`` (по умолчанию ``fp.name``).

        Имя нормализуется :func:`sanitize_name`, и поле ``name`` корпуса приводится к нему
        (текст Value, равный старому имени, тоже меняется — см. :meth:`rename`).
        Регистрируется сам объект ``fp`` (не копия): его дальнейшие изменения попадут в
        файл. Файл пишется при :meth:`save`/:meth:`save_all`. ``FileExistsError`` — корпус
        с таким именем уже есть (файл или добавленный) и ``overwrite`` ложно; при
        ``overwrite=True`` он заменяется в памяти (файл перезаписывается при сохранении).
        """
        if not isinstance(fp, Footprint):
            raise TypeError("Library.add: ожидается Footprint")
        target = sanitize_name(fp.name if name is None else name)
        if not overwrite and self._exists(target):
            raise FileExistsError(f"в библиотеке {self.name} уже есть корпус {target!r}: "
                                  f"{self.path_of(target)}")
        self._assign_name(fp, target)
        self._cache[target] = fp
        self._snapshots.pop(target, None)
        self._pending.add(target)

    def save(self, name: str, *, strict: bool = False, style: str = "auto") -> Path:
        """Записать корпус ``name`` в ``<path>/<name>.kicad_mod`` атомарно
        (:func:`kicadfp.io.save`) и вернуть путь.

        Записывается объект из памяти (добавленный или прочитанный :meth:`get`), даже если
        он не изменён; поле ``name`` перед записью приводится к имени в библиотеке (как у
        KiCad: имя файла и ``name`` совпадают). Если корпус не читался — файл не трогается.
        ``strict``/``style`` — как у :func:`kicadfp.io.save` (``ValidationError`` —
        ничего не записано). ``KeyError`` — корпуса нет.
        """
        fp = self._cache.get(name)
        if fp is None:
            self._require(name)
            return self.path_of(name)
        return self._write(name, fp, strict=strict, style=style)

    def _write(self, name: str, fp: Footprint, *, strict: bool, style: str) -> Path:
        path = self.path_of(name)
        if strict:
            issues = list(fp.validate(strict=True))
            if any(getattr(i, "level", None) == "error" for i in issues):
                raise _io.ValidationError(issues, str(path))
        self._assign_name(fp, name)
        _io.save(fp, path, style=style)
        self._pending.discard(name)
        self._snapshots[name] = (fp.node.copy(), fp.final_newline)
        return path

    def save_all(self, *, strict: bool = False, style: str = "auto") -> list[Path]:
        """Записать все корпуса с незаписанными изменениями (:attr:`unsaved`), каждый файл
        атомарно; вернуть пути записанных файлов (в порядке имён).

        ``strict=True``: сначала проверяются все корпуса; если хоть у одного есть ошибки —
        :class:`~kicadfp.io.ValidationError` (первого такого корпуса) и не пишется ничего.
        """
        todo = self.unsaved
        if strict:
            for n in todo:
                issues = list(self._cache[n].validate(strict=True))
                if any(getattr(i, "level", None) == "error" for i in issues):
                    raise _io.ValidationError(issues, str(self.path_of(n)))
        return [self._write(n, self._cache[n], strict=False, style=style) for n in todo]

    def remove(self, name: str) -> None:
        """Удалить корпус: файл удаляется немедленно, корпус — из кэша. ``KeyError`` —
        корпуса нет."""
        self._require(name)
        path = self.path_of(name)
        try:
            path.unlink()
        except FileNotFoundError:
            pass  # корпус был только в памяти
        self._forget(name)

    def _forget(self, name: str) -> None:
        self._cache.pop(name, None)
        self._snapshots.pop(name, None)
        self._pending.discard(name)

    def rename(self, old: str, new: str, *, overwrite: bool = False) -> None:
        """Переименовать корпус ``old`` в ``new``: записать файл ``<new>.kicad_mod`` с
        полем ``name`` = ``new`` и удалить ``<old>.kicad_mod``.

        ``new`` нормализуется :func:`sanitize_name`. Если текст Value совпадал со старым
        именем (так у корпусов стандартных библиотек), он тоже меняется на новое. Корпус,
        добавленный :meth:`add` и ещё не записанный, переименовывается только в памяти.
        Записывается текущее состояние объекта из кэша (с его незаписанными изменениями).
        ``KeyError`` — нет ``old``; ``FileExistsError`` — ``new`` уже есть и ``overwrite``
        ложно.
        """
        self._require(old)
        target = sanitize_name(new)
        if target == old:
            return
        old_path = self.path_of(old)
        new_path = self.path_of(target)
        same_file = _same_file(old_path, new_path)  # смена регистра на нечувствительной ФС
        if not overwrite and not same_file and self._exists(target):
            raise FileExistsError(f"в библиотеке {self.name} уже есть корпус {target!r}: "
                                  f"{new_path}")
        fp = self.get(old)
        on_disk = old_path.is_file()
        if target in self._cache or target in self._pending:
            self._forget(target)
        self._assign_name(fp, target)
        if on_disk:
            _io.save(fp, new_path)
            if not same_file:
                old_path.unlink()
            self._forget(old)
            self._cache[target] = fp
            self._snapshots[target] = (fp.node.copy(), fp.final_newline)
        else:
            self._forget(old)
            self._cache[target] = fp
            self._pending.add(target)

    def copy_to(self, other: Library, name: str, new_name: str | None = None, *,
                overwrite: bool = False) -> Footprint:
        """Скопировать корпус ``name`` в библиотеку ``other`` (можно в эту же) под именем
        ``new_name`` (по умолчанию — прежнее) и сразу записать файл; вернуть копию
        (зарегистрированную в ``other``).

        Копируется дерево корпуса из памяти (глубокая копия); исходный объект и исходный
        файл не меняются. Новое имя нормализуется :func:`sanitize_name`, поле ``name``
        копии и текст Value, равный старому имени, приводятся к нему.
        ``FileExistsError`` — в ``other`` уже есть такой корпус и ``overwrite`` ложно
        (в этом случае ничего не записывается); ``KeyError`` — нет ``name``.
        """
        if not isinstance(other, Library):
            raise TypeError("Library.copy_to: ожидается Library")
        src = self.get(name)
        target = sanitize_name(name if new_name is None else new_name)
        if other is self and target == name:
            raise FileExistsError(f"корпус {name!r} нельзя скопировать сам в себя")
        dup = src.copy()
        previous = other._cache.get(target), other._snapshots.get(target), \
            target in other._pending
        other.add(dup, target, overwrite=overwrite)
        try:
            other.save(target)
        except BaseException:
            # запись не удалась — вернуть состояние other как было
            other._forget(target)
            fp_prev, snap_prev, pending_prev = previous
            if fp_prev is not None:
                other._cache[target] = fp_prev
            if snap_prev is not None:
                other._snapshots[target] = snap_prev
            if pending_prev:
                other._pending.add(target)
            raise
        return dup

    # --- проверка -------------------------------------------------------------------------
    def validate_all(self) -> dict[str, list[Any]]:
        """Проверить все корпуса: ``{имя: список Issue}`` в порядке :attr:`names`.

        Используются корпуса из памяти (с незаписанными изменениями), остальные читаются
        из файлов без помещения в кэш. Файл, который не удалось прочитать, даёт одно
        замечание уровня ``error``: ``SEXPR_SYNTAX`` (синтаксис, с позицией) или
        ``FILE_READ`` (ошибка ввода-вывода, старая библиотека ``.mod`` и т. п.).
        """
        from .validate import Issue, syntax_issue

        out: dict[str, list[Any]] = {}
        for n in self.names:
            fp = self._cache.get(n)
            if fp is None:
                path = self.path_of(n)
                try:
                    fp = _io.load(path)
                except SexprSyntaxError as e:
                    out[n] = [syntax_issue(e, str(path))]
                    continue
                except (OSError, ValueError) as e:
                    out[n] = [Issue("error", "FILE_READ",
                                    f"{path}: не удалось прочитать файл: {e}", None)]
                    continue
            out[n] = list(fp.validate())
        return out


def _same_file(a: Path, b: Path) -> bool:
    """Указывают ли пути на один существующий файл (``False``, если какого-то нет)."""
    try:
        return a != b and os.path.samefile(a, b)
    except OSError:
        return False
