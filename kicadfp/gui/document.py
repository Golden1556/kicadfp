"""Документ графического интерфейса: открытый корпус, путь, стек отмены, выделение.

:class:`FootprintDocument` — единственный владелец модели в GUI. Таблицы, панели и канва
получают документ в конструкторе, читают модель через :attr:`FootprintDocument.fp` и
перерисовываются по сигналу :attr:`~FootprintDocument.changed`, не храня копий данных
модели (элемент идентифицируется представлением или ``id(view.node)``; представления равны,
если это представления одного класса над одним узлом). Любое изменение модели —
только командой (:mod:`kicadfp.gui.commands`) через :meth:`FootprintDocument.apply`.

Сигналы
-------
``changed()``
    после каждой команды, отмены, повтора, а также открытия/закрытия корпуса;
``selection_changed(object)``
    выделенный элемент модели (представление, узел без представления или ``None``);
``modified_changed(bool)``
    изменился признак «есть несохранённые изменения» (:attr:`is_modified`);
``document_changed()``
    открыт другой корпус (или документ закрыт) — виджеты сбрасывают своё состояние;
``path_changed(object)``
    изменился путь файла (``Path`` или ``None``), например после «Сохранить как»;
``saved(object)``
    корпус записан в файл (``Path``).

Порядок при открытии: ``document_changed``, ``path_changed`` (если путь другой),
``selection_changed(None)`` (если было выделение), ``changed``, ``modified_changed`` (если
признак изменился).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from .. import io as _io
from ..library import Library
from ..model import Footprint, View, view_for
from ..sexpr import Node
from .commands import DocumentCommand, _in_tree

__all__ = ["FootprintDocument", "UNDO_LIMIT"]

#: Глубина отмены (ТЗ: не менее 100 шагов).
UNDO_LIMIT = 1000

_LIBRARY_SUFFIX = ".pretty"


def _always_true() -> bool:
    return True


def _abs_path(path: str | PathLike[str]) -> Path:
    """Абсолютный путь (``~`` раскрывается, символические ссылки не разыменовываются)."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _library_for(path: Path) -> Library | None:
    """Библиотека ``.pretty``, в каталоге которой лежит файл, или ``None``."""
    parent = path.parent
    if not parent.name.lower().endswith(_LIBRARY_SUFFIX) or not parent.is_dir():
        return None
    try:
        return Library(parent)
    except OSError:
        return None


def _is_legacy_file(path: Path) -> bool:
    """Файл старого формата ``PCBNEW-LibModule-V1`` (``.mod``)?"""
    try:
        text = path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return False
    return _io.detect_format(text) == "legacy"


def _node_of(item: Any) -> Node:
    if isinstance(item, View):
        return item.node
    if isinstance(item, Node):
        return item
    raise TypeError(f"ожидается элемент модели (представление или Node), "
                    f"а не {type(item).__name__}")


def _same_item(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return type(a) is type(b) and _node_of(a) is _node_of(b)


class FootprintDocument(QObject):
    """Открытый в редакторе корпус с путём, библиотекой, стеком отмены и выделением.

    Свойства: :attr:`fp` (:class:`~kicadfp.model.Footprint` или ``None``), :attr:`path`
    (``Path`` или ``None`` — ещё не записан), :attr:`library`
    (:class:`~kicadfp.library.Library`, если файл лежит в каталоге ``.pretty``),
    :attr:`undo_stack` (``QUndoStack``, глубина :data:`UNDO_LIMIT`), :attr:`is_modified`,
    :attr:`selected`, :attr:`confirm_discard`.

    Открытие другого корпуса (:meth:`open`, :meth:`open_footprint`, :meth:`new_footprint`)
    и :meth:`close` при несохранённых изменениях спрашивают разрешения у
    :attr:`confirm_discard` — функции без аргументов, возвращающей ``True`` («можно
    отбросить изменения / продолжить») или ``False`` («отмена»); по умолчанию всегда
    ``True``. Главное окно подставляет свой диалог (например, «Сохранить / Не сохранять /
    Отмена», где «Сохранить» вызывает :meth:`save` и возвращает ``True`` при успехе).

    Изменение модели — только :meth:`apply` (см. :mod:`kicadfp.gui.commands`); применять
    команды из обработчиков сигналов документа, испущенных во время выполнения команды,
    нельзя (``RuntimeError``) — это испортило бы стек отмены.
    """

    changed = Signal()
    selection_changed = Signal(object)
    modified_changed = Signal(bool)
    document_changed = Signal()
    path_changed = Signal(object)
    saved = Signal(object)

    def __init__(self, parent: QObject | None = None, *,
                 confirm_discard: Callable[[], bool] | bool | None = None) -> None:
        super().__init__(parent)
        self._fp: Footprint | None = None
        self._path: Path | None = None
        self._library: Library | None = None
        self._selected: Any = None
        self._force_modified = False
        self._last_modified = False
        self._switching = False
        self._suspend = 0
        self._busy = 0
        self._confirm: Callable[[], bool] = _always_true
        self.confirm_discard = confirm_discard  # type: ignore[assignment]
        #: Функция без аргументов, применяющая незавершённый ввод виджетов (поле панели
        #: свойств, открытый редактор ячейки таблицы) командами :meth:`apply`; вызывается
        #: :meth:`commit_pending_edits` перед записью и вопросом о несохранённых изменениях.
        self.pending_edits_hook: Callable[[], Any] | None = None
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(UNDO_LIMIT)
        self._undo_stack.cleanChanged.connect(self._update_modified)

    # --- свойства -------------------------------------------------------------------------------
    @property
    def fp(self) -> Footprint | None:
        """Открытый корпус (``None`` — документ пуст)."""
        return self._fp

    @property
    def path(self) -> Path | None:
        """Путь к файлу корпуса (``None`` — корпус ещё не записан в файл)."""
        return self._path

    @property
    def library(self) -> Library | None:
        """Библиотека ``.pretty``, из которой открыт корпус (``None`` — одиночный файл)."""
        return self._library

    @property
    def undo_stack(self) -> QUndoStack:
        """Стек отмены (``createUndoAction``/``createRedoAction`` — для меню «Правка»)."""
        return self._undo_stack

    @property
    def is_modified(self) -> bool:
        """Есть ли несохранённые изменения (стек отмены не в «чистом» состоянии или корпус
        создан в памяти и ещё не записан, см. :meth:`open_footprint`)."""
        return self._fp is not None and (self._force_modified or not self._undo_stack.isClean())

    @property
    def display_name(self) -> str:
        """Имя для заголовка окна: имя файла без расширения или имя корпуса."""
        if self._path is not None:
            return self._path.stem
        return self._fp.name if self._fp is not None else ""

    @property
    def selected(self) -> Any:
        """Выделенный элемент (представление, привязанное к корпусу, узел без представления,
        сам корпус) или ``None``."""
        return self._selected

    @property
    def confirm_discard(self) -> Callable[[], bool]:
        """Функция подтверждения потери несохранённых изменений (см. класс). Можно
        присвоить ``True``/``False`` (постоянный ответ) или ``None`` (по умолчанию)."""
        return self._confirm

    @confirm_discard.setter
    def confirm_discard(self, func: Callable[[], bool] | bool | None) -> None:
        if func is None:
            func = _always_true
        elif isinstance(func, bool):
            answer = func
            func = lambda: answer  # noqa: E731
        elif not callable(func):
            raise TypeError("confirm_discard: ожидается функция без аргументов -> bool")
        self._confirm = func

    # --- служебное -------------------------------------------------------------------------------
    def _require_fp(self) -> Footprint:
        if self._fp is None:
            raise RuntimeError("в документе нет открытого корпуса")
        return self._fp

    def _check_idle(self, what: str) -> None:
        if self._busy:
            raise RuntimeError(f"{what}: нельзя во время выполнения команды (из обработчика "
                               f"сигнала документа)")

    @contextmanager
    def _command_scope(self) -> Iterator[None]:
        """Команда выполняется, отменяется или повторяется (защита от вложенных команд)."""
        self._busy += 1
        try:
            yield
        finally:
            self._busy -= 1

    @contextmanager
    def _suspend_changed(self) -> Iterator[None]:
        """Не испускать ``changed`` внутри блока (первое выполнение команды: сигнал испустит
        сама команда после выполнения)."""
        self._suspend += 1
        try:
            yield
        finally:
            self._suspend -= 1

    def _emit_changed(self) -> None:
        """Сообщить об изменении модели: проверить выделение, испустить ``changed`` (и
        ``selection_changed``, если выделенный элемент исчез или сменил вид). Вызывается
        командами после ``redo``/``undo``."""
        if self._suspend:
            return
        sel_changed = self._revalidate_selection()
        self.changed.emit()
        if sel_changed:
            self.selection_changed.emit(self._selected)

    def _update_modified(self, *_: Any) -> None:
        if self._switching:
            return
        m = self.is_modified
        if m != self._last_modified:
            self._last_modified = m
            self.modified_changed.emit(m)

    def _revalidate_selection(self) -> bool:
        """Сбросить выделение элемента, которого больше нет в корпусе, и заменить
        представление, если узел сменил вид (``fp_rect`` → ``fp_poly`` при повороте).
        Возвращает, изменилось ли выделение."""
        sel = self._selected
        if sel is None:
            return False
        fp = self._fp
        node = _node_of(sel)
        if fp is None or not _in_tree(fp.node, node):
            self._selected = None
            return True
        if isinstance(sel, View) and not isinstance(sel, Footprint):
            fresh = self._natural_view(node)
            if fresh is not None and type(fresh) is not type(sel):
                self._selected = fresh
                return True
        return False

    def _natural_view(self, node: Node) -> View | None:
        try:
            return view_for(node, None, self._fp)
        except ValueError:
            return None

    def _set_document(self, fp: Footprint | None, path: Path | None, library: Library | None, *,
                      modified: bool) -> None:
        """Заменить содержимое документа (стек отмены очищается)."""
        old_path = self._path
        had_selection = self._selected is not None
        self._switching = True
        try:
            self._undo_stack.clear()
            self._fp = fp
            self._path = path
            self._library = library
            self._force_modified = bool(modified) and fp is not None
            self._selected = None
        finally:
            self._switching = False
        self.document_changed.emit()
        if path != old_path:
            self.path_changed.emit(path)
        if had_selection:
            self.selection_changed.emit(None)
        self._emit_changed()
        self._update_modified()

    def commit_pending_edits(self) -> None:
        """Применить незавершённый ввод виджетов (:attr:`pending_edits_hook`), чтобы
        набранное, но ещё не подтверждённое значение попало в модель до записи файла или
        проверки :attr:`is_modified`."""
        hook = self.pending_edits_hook
        if hook is not None and self._fp is not None and not self._busy:
            hook()

    def _confirm_discard_changes(self) -> bool:
        self.commit_pending_edits()
        if not self.is_modified:
            return True
        return bool(self._confirm())

    # --- привязка элементов --------------------------------------------------------------------
    def contains(self, item: Any) -> bool:
        """Входит ли элемент (представление или узел) в открытый корпус."""
        if self._fp is None or item is None:
            return False
        try:
            node = _node_of(item)
        except TypeError:
            return False
        return _in_tree(self._fp.node, node)

    def bind(self, item: Any) -> Any:
        """Элемент, привязанный к открытому корпусу: представление подходящего класса с
        родителем :attr:`fp` (пишет по профилю корпуса), сам :attr:`fp` для корпуса или
        узел — для узлов без представления (зоны, группы, неизвестные).
        ``ValueError`` — элемента нет в открытом корпусе; ``RuntimeError`` — корпус не
        открыт."""
        fp = self._require_fp()
        node = _node_of(item)
        if node is fp.node:
            return fp
        if isinstance(item, Footprint) or not _in_tree(fp.node, node):
            raise ValueError("элемент не входит в открытый корпус")
        natural = self._natural_view(node)
        if isinstance(item, View):
            if natural is None:
                return item if item.parent is fp else type(item)(node, None, fp)
            if type(natural) is type(item) and item.parent is fp:
                return item
            return natural
        return natural if natural is not None else node

    # --- выделение ------------------------------------------------------------------------------
    def select(self, item: Any) -> None:
        """Выделить элемент модели (представление или узел открытого корпуса, сам корпус)
        или снять выделение (``None``); испускает ``selection_changed``, если выделение
        изменилось. ``ValueError`` — элемента нет в открытом корпусе."""
        new = None if item is None else self.bind(item)
        if _same_item(new, self._selected):
            return
        self._selected = new
        self.selection_changed.emit(new)

    # --- команды --------------------------------------------------------------------------------
    def apply(self, cmd: QUndoCommand) -> bool:
        """Выполнить команду и записать её в стек отмены; испускается ``changed()``.

        Для :class:`~kicadfp.gui.commands.DocumentCommand` команда сначала выполняется
        (ошибка — модель не меняется, исключение передаётся вызывающему, стек отмены не
        трогается), затем кладётся в стек (или сливается с предыдущей). Команда, не
        изменившая модель, в стек не кладётся — результат ``False``; иначе ``True``.
        Прочие ``QUndoCommand`` просто кладутся в стек (``redo`` вызывает Qt), после чего
        испускается ``changed``.
        """
        if not isinstance(cmd, QUndoCommand):
            raise TypeError(f"apply: ожидается QUndoCommand, а не {type(cmd).__name__}")
        self._check_idle("применить команду")
        self._require_fp()
        if isinstance(cmd, DocumentCommand):
            if cmd.document is not self:
                raise ValueError("команда создана для другого документа")
            with self._command_scope():
                changed = cmd.execute()
            if not changed:
                return False
            cmd._skip_redo = True
            self._undo_stack.push(cmd)
            return True
        with self._command_scope():
            self._undo_stack.push(cmd)
        self._emit_changed()
        return True

    def undo(self) -> None:
        """Отменить последнюю команду (как ``undo_stack.undo()``)."""
        self._check_idle("отменить")
        self._undo_stack.undo()

    def redo(self) -> None:
        """Повторить отменённую команду (как ``undo_stack.redo()``)."""
        self._check_idle("повторить")
        self._undo_stack.redo()

    # --- открытие -------------------------------------------------------------------------------
    def open(self, path: str | PathLike[str], *, library: Library | None = None) -> bool:
        """Открыть файл корпуса (``.kicad_mod`` KiCad 5–10 или ``.mod`` с одним корпусом).

        Файл читается до вопроса о несохранённых изменениях: ошибка чтения
        (:class:`~kicadfp.sexpr.SexprSyntaxError` со строкой и позицией, ``OSError``,
        :class:`~kicadfp.io.LegacyLibraryError` для ``.mod`` из нескольких корпусов)
        передаётся вызывающему, открытый документ не меняется. Если вопрос задавался, файл
        после ответа читается ещё раз (ответ «Сохранить» мог записать этот же файл). ``False`` — пользователь
        отказался отбросить изменения (:attr:`confirm_discard`). ``library`` — библиотека,
        из которой открыт файл (по умолчанию определяется по каталогу ``.pretty``). Корпус
        старого формата ``.mod`` открывается как новый несохранённый (путь ``None``:
        записывать его надо через :meth:`save_as` в ``.kicad_mod``).
        """
        self._check_idle("открыть корпус")
        p = _abs_path(path)
        if p.is_dir():
            raise IsADirectoryError(f"{p}: это каталог, а не файл корпуса (библиотеку .pretty "
                                    f"открывает дерево библиотек)")
        fp = _io.load(p)
        legacy = _is_legacy_file(p)
        self.commit_pending_edits()
        asked = self.is_modified
        if not self._confirm_discard_changes():
            return False
        if asked:
            # ответ «Сохранить» мог записать файл (в том числе этот же): прочитать заново,
            # чтобы открыть содержимое после записи, а не прочитанное до вопроса
            fp = _io.load(p)
        if legacy:
            self._set_document(fp, None, None, modified=True)
        else:
            lib = library if library is not None else _library_for(p)
            self._set_document(fp, p, lib, modified=False)
        return True

    def open_footprint(self, fp: Footprint, path: str | PathLike[str] | None = None, *,
                       library: Library | None = None, modified: bool | None = None) -> bool:
        """Открыть корпус из памяти (например, результат генератора).

        ``path`` — файл, в который будет записывать :meth:`save` (``None`` — только
        :meth:`save_as`); ``modified`` — считать ли корпус несохранённым (по умолчанию —
        если нет пути). Объект ``fp`` не копируется. ``False`` — пользователь отказался
        отбросить изменения текущего корпуса."""
        self._check_idle("открыть корпус")
        if not isinstance(fp, Footprint):
            raise TypeError(f"open_footprint: ожидается Footprint, а не {type(fp).__name__}")
        p = None if path is None else _abs_path(path)
        if not self._confirm_discard_changes():
            return False
        lib = library if library is not None else (None if p is None else _library_for(p))
        self._set_document(fp, p, lib, modified=(p is None) if modified is None else modified)
        return True

    def new_footprint(self, name: str, **kwargs: Any) -> bool:
        """Создать пустой корпус :meth:`Footprint.new(name, **kwargs)
        <kicadfp.model.Footprint.new>` (по умолчанию формат KiCad 9) и открыть его (без
        пути, не изменён). ``False`` — пользователь отказался отбросить изменения."""
        self._check_idle("создать корпус")
        fp = Footprint.new(name, **kwargs)
        return self.open_footprint(fp, None, modified=False)

    def close(self) -> bool:
        """Закрыть корпус. При несохранённых изменениях спрашивает :attr:`confirm_discard`;
        ``False`` — пользователь отказался (документ остаётся открытым)."""
        self._check_idle("закрыть корпус")
        if self._fp is None:
            return True
        if not self._confirm_discard_changes():
            return False
        self._set_document(None, None, None, modified=False)
        return True

    # --- запись ---------------------------------------------------------------------------------
    def _write(self, path: Path, strict: bool) -> None:
        fp = self._require_fp()
        _io.save(fp, path, strict=strict)
        self._force_modified = False
        self._undo_stack.setClean()
        self._update_modified()

    def _refresh_library(self) -> None:
        """Сбросить в библиотеке прочитанные ранее и не изменённые копии корпусов, чтобы
        следующий ``Library.get`` прочитал записанный файл."""
        if self._library is None:
            return
        try:
            self._library.refresh()
        except Exception:  # noqa: BLE001 — кэш библиотеки вторичен, запись уже выполнена
            pass

    def save(self, strict: bool = False) -> bool:
        """Записать корпус в :attr:`path` (атомарно, :func:`kicadfp.io.save`).

        ``False`` — пути нет (нужен :meth:`save_as`). ``strict=True`` — при ошибках проверки
        ничего не пишется, :class:`~kicadfp.io.ValidationError`; ошибки записи —
        ``OSError``. После записи документ не изменён (стек отмены помечается чистым)."""
        self._check_idle("сохранить")
        self._require_fp()
        if self._path is None:
            return False
        self.commit_pending_edits()
        path = self._path
        self._write(path, strict)
        self._refresh_library()
        self.saved.emit(path)
        return True

    def save_as(self, path: str | PathLike[str], strict: bool = False) -> bool:
        """Записать корпус в новый файл и сделать его путём документа (библиотека —
        по каталогу ``.pretty``); испускается ``path_changed``. Ошибки — как у
        :meth:`save`, при ошибке путь документа не меняется. Имя корпуса внутри файла не
        меняется (KiCad берёт имя корпуса библиотеки из имени файла)."""
        self._check_idle("сохранить")
        self._require_fp()
        p = _abs_path(path)
        if p.is_dir():
            raise IsADirectoryError(f"{p}: это каталог, укажите файл .kicad_mod")
        self.commit_pending_edits()
        self._write(p, strict)
        old = self._path
        self._path = p
        lib = self._library
        if lib is None or _abs_path(lib.path) != p.parent:
            self._library = _library_for(p)
        self._refresh_library()
        if p != old:
            self.path_changed.emit(p)
        self.saved.emit(p)
        return True

    def set_path(self, path: str | PathLike[str] | None, *,
                 library: Library | None = None) -> None:
        """Сменить путь документа без записи (файл переименован или перемещён другим
        способом, например в дереве библиотек). Признак изменений не меняется."""
        self._require_fp()
        p = None if path is None else _abs_path(path)
        old = self._path
        self._path = p
        self._library = library if library is not None else (
            None if p is None else _library_for(p))
        if p != old:
            self.path_changed.emit(p)
