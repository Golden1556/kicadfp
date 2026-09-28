"""Дерево библиотек: :class:`LibraryTree` (``QTreeView`` над ``QStandardItemModel``).

Корни дерева — открытые библиотеки ``.pretty`` (:class:`~kicadfp.library.Library`) и
одиночные файлы корпусов; дети библиотеки — имена её корпусов (:attr:`Library.names
<kicadfp.library.Library.names>`, по алфавиту). Дерево не хранит данных корпусов — только
пути и объекты :class:`~kicadfp.library.Library`; список детей перечитывается из каталога
при :meth:`LibraryTree.refresh` и после каждой операции над файлами.

Двойной щелчок или Enter на корпусе (или одиночном файле) — сигнал
:attr:`LibraryTree.open_requested` с путём к файлу (``Path``); открывает файл главное окно
(``FootprintDocument.open``).

Контекстное меню: «Открыть», «Переименовать…» (``QInputDialog`` → :meth:`Library.rename
<kicadfp.library.Library.rename>`), «Удалить…» (с подтверждением → :meth:`Library.remove
<kicadfp.library.Library.remove>`), «Копировать в библиотеку…» (выбор из открытых
библиотек и новое имя → :meth:`Library.copy_to <kicadfp.library.Library.copy_to>`),
«Обновить», «Закрыть библиотеку/файл». Для тестов и сценариев те же действия доступны без
окон: :meth:`LibraryTree.rename_footprint`, :meth:`LibraryTree.delete_footprint`,
:meth:`LibraryTree.copy_footprint`; вопросы пользователю задают подменяемые функции
:attr:`LibraryTree.ask_text`, :attr:`LibraryTree.ask_confirm`, :attr:`LibraryTree.ask_copy`.

Сигналы: ``open_requested(Path)``; ``libraries_changed()`` — изменился состав дерева
(добавлена/закрыта библиотека или файл) или содержимое библиотеки (переименование,
удаление, копирование, обновление); ``footprint_renamed(Path, Path)`` — файл корпуса
переименован (старый и новый путь: главное окно обновляет путь открытого документа);
``footprint_removed(Path)`` — файл корпуса удалён; ``error(str)`` — ошибка операции
(сообщение по-русски; интерактивные действия дополнительно показывают его в окне).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from os import PathLike
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QKeyEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QInputDialog, QLineEdit, QMenu, QMessageBox,
                               QStyle, QTreeView, QWidget)

from ..library import FOOTPRINT_EXT, Library, sanitize_name

__all__ = [
    "LibraryTree", "CopyFootprintDialog", "KIND_LIBRARY", "KIND_FILE", "KIND_FOOTPRINT",
    "KIND_ROLE", "PATH_ROLE", "NAME_ROLE",
]

#: Роль данных элемента: вид элемента (:data:`KIND_LIBRARY`, :data:`KIND_FILE`,
#: :data:`KIND_FOOTPRINT`).
KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Роль данных элемента: путь (``Path``) — каталог библиотеки или файл корпуса.
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 2
#: Роль данных элемента: имя корпуса в библиотеке (у корпуса) или имя библиотеки.
NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 3

KIND_LIBRARY = "library"
KIND_FILE = "file"
KIND_FOOTPRINT = "footprint"


def _abs(path: str | PathLike[str]) -> Path:
    """Абсолютный путь (``~`` раскрывается, ссылки не разыменовываются)."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a == b or (a.exists() and b.exists() and os.path.samefile(a, b))
    except OSError:
        return a == b


class CopyFootprintDialog(QDialog):
    """Диалог «Копировать в библиотеку»: выбор библиотеки из открытых и новое имя.

    Программное заполнение: :meth:`set_target` (индекс, имя или путь библиотеки),
    :meth:`set_new_name`; результат — :attr:`target` (``Library``) и :attr:`new_name`.
    """

    def __init__(self, libraries: list[Library], name: str, source: Library | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Копировать корпус в библиотеку")
        self._libraries = list(libraries)
        form = QFormLayout(self)
        self._combo = QComboBox(self)
        for lib in self._libraries:
            self._combo.addItem(f"{lib.name}  ({lib.path})", str(lib.path))
        if source is not None:
            # по умолчанию — другая библиотека (если есть)
            for i, lib in enumerate(self._libraries):
                if lib is not source:
                    self._combo.setCurrentIndex(i)
                    break
        self._name = QLineEdit(name, self)
        form.addRow("Библиотека:", self._combo)
        form.addRow("Новое имя:", self._name)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def set_target(self, target: int | str | Library | PathLike[str]) -> None:
        """Выбрать библиотеку: индекс, объект ``Library``, имя или путь к каталогу."""
        if isinstance(target, int):
            self._combo.setCurrentIndex(target)
            return
        for i, lib in enumerate(self._libraries):
            if target is lib or (isinstance(target, str) and target == lib.name) or (
                    not isinstance(target, Library) and _same_path(_abs(target), _abs(lib.path))):
                self._combo.setCurrentIndex(i)
                return
        raise KeyError(f"библиотека {target!r} не открыта")

    def set_new_name(self, name: str) -> None:
        """Задать новое имя корпуса."""
        self._name.setText(name)

    @property
    def target(self) -> Library | None:
        """Выбранная библиотека (``None`` — открытых библиотек нет)."""
        i = self._combo.currentIndex()
        return self._libraries[i] if 0 <= i < len(self._libraries) else None

    @property
    def new_name(self) -> str:
        """Введённое имя (без пробелов по краям)."""
        return self._name.text().strip()


class LibraryTree(QTreeView):
    """Дерево открытых библиотек ``.pretty`` и одиночных файлов (см. модуль).

    Методы: :meth:`add_library`, :meth:`add_file`, :meth:`remove_selected`,
    :meth:`refresh`; операции над корпусами — :meth:`rename_footprint`,
    :meth:`delete_footprint`, :meth:`copy_footprint`; доступ — :attr:`libraries`,
    :attr:`files`, :meth:`library_for`, :meth:`selected_path`, :meth:`select_path`,
    :meth:`index_for_path`.
    """

    open_requested = Signal(object)
    libraries_changed = Signal()
    footprint_renamed = Signal(object, object)
    footprint_removed = Signal(object)
    error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["Библиотеки"])
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(True)
        self._libraries: list[Library] = []
        self._files: list[Path] = []
        style = self.style()
        self._icon_lib = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._icon_file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        #: Запрос строки: ``ask_text(заголовок, подпись, текст) -> str | None``
        #: (``None`` — отмена). По умолчанию — ``QInputDialog.getText``.
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text_dialog
        #: Подтверждение: ``ask_confirm(заголовок, вопрос) -> bool``. По умолчанию —
        #: ``QMessageBox.question``.
        self.ask_confirm: Callable[[str, str], bool] = self._ask_confirm_dialog
        #: Выбор библиотеки и имени для копирования: ``ask_copy(библиотеки, имя, исходная)
        #: -> (Library, новое имя) | None``. По умолчанию — :class:`CopyFootprintDialog`.
        self.ask_copy: Callable[[list[Library], str, Library],
                                tuple[Library, str] | None] = self._ask_copy_dialog
        #: Показывать ли ошибки интерактивных действий в окне сообщения (в тестах —
        #: ``False``; сигнал :attr:`error` испускается всегда).
        self.show_errors = True
        self.doubleClicked.connect(self._on_double_clicked)

    # --- доступ ---------------------------------------------------------------------------------
    @property
    def item_model(self) -> QStandardItemModel:
        """Модель дерева (``QStandardItemModel``)."""
        return self._model

    @property
    def libraries(self) -> list[Library]:
        """Открытые библиотеки в порядке корней дерева."""
        return list(self._libraries)

    @property
    def files(self) -> list[Path]:
        """Открытые одиночные файлы."""
        return list(self._files)

    def library_for(self, path: str | PathLike[str]) -> Library | None:
        """Открытая библиотека по пути каталога или файла корпуса внутри неё (``None`` —
        не открыта)."""
        p = _abs(path)
        for lib in self._libraries:
            lp = _abs(lib.path)
            if _same_path(p, lp) or (p.suffix == FOOTPRINT_EXT and _same_path(p.parent, lp)):
                return lib
        return None

    def root_count(self) -> int:
        """Число корней дерева."""
        return self._model.rowCount()

    def root_item(self, row: int) -> QStandardItem | None:
        """Корневой элемент строки ``row``."""
        return self._model.item(row)

    def children_names(self, library: Library | str | PathLike[str]) -> list[str]:
        """Имена детей корня библиотеки (как показаны в дереве)."""
        item = self._library_item(library)
        if item is None:
            raise KeyError(f"библиотека {library!r} не открыта")
        return [item.child(r).data(NAME_ROLE) for r in range(item.rowCount())]

    # --- элементы -------------------------------------------------------------------------------
    def _library_item(self, library: Library | str | PathLike[str]) -> QStandardItem | None:
        lib = library if isinstance(library, Library) else None
        if lib is None:
            if isinstance(library, str) and os.sep not in library and not library.endswith(
                    ".pretty"):
                lib = next((x for x in self._libraries if x.name == library), None)
            if lib is None:
                lib = self.library_for(library)
        if lib is None:
            return None
        for r in range(self._model.rowCount()):
            it = self._model.item(r)
            if it.data(KIND_ROLE) == KIND_LIBRARY and it.data(Qt.ItemDataRole.UserRole) is lib:
                return it
        return None

    def _make_footprint_item(self, lib: Library, name: str) -> QStandardItem:
        it = QStandardItem(name)
        it.setEditable(False)
        it.setData(KIND_FOOTPRINT, KIND_ROLE)
        it.setData(name, NAME_ROLE)
        try:
            path = lib.path_of(name)
        except ValueError:
            path = None
        it.setData(path, PATH_ROLE)
        it.setToolTip(str(path) if path is not None else name)
        return it

    def _fill_library(self, item: QStandardItem, lib: Library) -> None:
        item.removeRows(0, item.rowCount())
        try:
            names = lib.names
        except OSError as e:
            self._report(f"{lib.path}: не удалось прочитать каталог: {e}", interactive=False)
            names = []
        item.appendRows([self._make_footprint_item(lib, n) for n in names])
        item.setText(f"{lib.name} ({len(names)})")

    # --- добавление и удаление корней -----------------------------------------------------------
    def add_library(self, path: str | PathLike[str] | Library) -> Library:
        """Открыть библиотеку ``.pretty`` (путь к каталогу или объект ``Library``) и добавить
        её корнем дерева. Уже открытая библиотека не дублируется — она перечитывается и
        возвращается. ``FileNotFoundError``/``NotADirectoryError`` — нет такого каталога."""
        if isinstance(path, Library):
            lib = path
            existing = next((x for x in self._libraries if x is lib), None) or \
                self.library_for(lib.path)
        else:
            existing = self.library_for(path)
            lib = existing if existing is not None else Library(_abs(path))
        if existing is not None:
            self.refresh(existing)
            return existing
        item = QStandardItem(lib.name)
        item.setEditable(False)
        item.setIcon(self._icon_lib)
        item.setData(KIND_LIBRARY, KIND_ROLE)
        item.setData(_abs(lib.path), PATH_ROLE)
        item.setData(lib.name, NAME_ROLE)
        item.setData(lib, Qt.ItemDataRole.UserRole)
        item.setToolTip(str(lib.path))
        self._fill_library(item, lib)
        self._libraries.append(lib)
        self._model.appendRow(item)
        self.libraries_changed.emit()
        return lib

    def add_file(self, path: str | PathLike[str]) -> Path:
        """Добавить одиночный файл корпуса корнем дерева (повторно не добавляется).
        ``FileNotFoundError`` — файла нет; ``IsADirectoryError`` — это каталог (для
        ``.pretty`` — :meth:`add_library`)."""
        p = _abs(path)
        if p.is_dir():
            raise IsADirectoryError(f"{p}: это каталог; библиотеку .pretty откройте как "
                                    f"библиотеку")
        if not p.is_file():
            raise FileNotFoundError(f"файл не найден: {p}")
        for f in self._files:
            if _same_path(f, p):
                return f
        item = QStandardItem(p.name)
        item.setEditable(False)
        item.setIcon(self._icon_file)
        item.setData(KIND_FILE, KIND_ROLE)
        item.setData(p, PATH_ROLE)
        item.setData(p.stem, NAME_ROLE)
        item.setToolTip(str(p))
        self._files.append(p)
        self._model.appendRow(item)
        self.libraries_changed.emit()
        return p

    def add_path(self, path: str | PathLike[str]) -> Library | Path:
        """Каталог — :meth:`add_library`, файл — :meth:`add_file`."""
        return self.add_library(path) if _abs(path).is_dir() else self.add_file(path)

    def remove_root(self, row: int) -> None:
        """Закрыть корень строки ``row`` (библиотеку или файл); файлы на диске не
        трогаются."""
        item = self._model.item(row)
        if item is None:
            raise IndexError(row)
        kind = item.data(KIND_ROLE)
        if kind == KIND_LIBRARY:
            lib = item.data(Qt.ItemDataRole.UserRole)
            self._libraries = [x for x in self._libraries if x is not lib]
        elif kind == KIND_FILE:
            p = item.data(PATH_ROLE)
            self._files = [f for f in self._files if f != p]
        self._model.removeRow(row)
        self.libraries_changed.emit()

    def remove_selected(self) -> int:
        """Закрыть выделенные корни дерева (библиотеки и одиночные файлы; файлы на диске не
        удаляются). Выделенный корпус внутри библиотеки закрывает не библиотеку, а
        игнорируется — корпус удаляет :meth:`delete_footprint`. Возвращает число закрытых
        корней."""
        rows = sorted({ix.row() for ix in self.selectionModel().selectedRows()
                       if not ix.parent().isValid()}, reverse=True)
        if not rows:
            return 0
        for r in rows:
            item = self._model.item(r)
            kind = item.data(KIND_ROLE)
            if kind == KIND_LIBRARY:
                lib = item.data(Qt.ItemDataRole.UserRole)
                self._libraries = [x for x in self._libraries if x is not lib]
            elif kind == KIND_FILE:
                p = item.data(PATH_ROLE)
                self._files = [f for f in self._files if f != p]
            self._model.removeRow(r)
        self.libraries_changed.emit()
        return len(rows)

    def clear_all(self) -> None:
        """Закрыть все библиотеки и файлы."""
        if not self._model.rowCount():
            return
        self._model.removeRows(0, self._model.rowCount())
        self._libraries.clear()
        self._files.clear()
        self.libraries_changed.emit()

    # --- обновление -----------------------------------------------------------------------------
    def refresh(self, library: Library | str | PathLike[str] | None = None) -> None:
        """Перечитать каталоги библиотек (все или одну) и обновить детей; исчезнувшие
        одиночные файлы убираются. Раскрытие корней и текущий элемент сохраняются, если
        элементы остались."""
        current = self.selected_path()
        expanded = {r for r in range(self._model.rowCount())
                    if self.isExpanded(self._model.index(r, 0))}
        targets: list[Library]
        if library is None:
            targets = list(self._libraries)
        else:
            item = self._library_item(library)
            if item is None:
                raise KeyError(f"библиотека {library!r} не открыта")
            targets = [item.data(Qt.ItemDataRole.UserRole)]
        for lib in targets:
            item = self._library_item(lib)
            if item is None:
                continue
            try:
                lib.refresh()
            except Exception:  # noqa: BLE001 — кэш библиотеки вторичен
                pass
            self._fill_library(item, lib)
        if library is None:
            for r in range(self._model.rowCount() - 1, -1, -1):
                it = self._model.item(r)
                if it.data(KIND_ROLE) == KIND_FILE and not Path(it.data(PATH_ROLE)).is_file():
                    self._files = [f for f in self._files if f != it.data(PATH_ROLE)]
                    self._model.removeRow(r)
                    expanded = {x - 1 if x > r else x for x in expanded if x != r}
        for r in expanded:
            if r < self._model.rowCount():
                self.setExpanded(self._model.index(r, 0), True)
        if current is not None:
            self.select_path(current)
        self.libraries_changed.emit()

    # --- выделение ------------------------------------------------------------------------------
    def index_for_path(self, path: str | PathLike[str]) -> QModelIndex:
        """Индекс элемента с путём ``path`` (корпус, файл или каталог библиотеки);
        недействительный индекс — не найден."""
        p = _abs(path)
        for r in range(self._model.rowCount()):
            it = self._model.item(r)
            ip = it.data(PATH_ROLE)
            if ip is not None and _same_path(Path(ip), p):
                return it.index()
            if it.data(KIND_ROLE) == KIND_LIBRARY and _same_path(p.parent, Path(ip)):
                for c in range(it.rowCount()):
                    ch = it.child(c)
                    cp = ch.data(PATH_ROLE)
                    if cp is not None and Path(cp).name == p.name:
                        return ch.index()
        return QModelIndex()

    def select_path(self, path: str | PathLike[str]) -> bool:
        """Сделать элемент с путём ``path`` текущим (родитель раскрывается). ``False`` —
        не найден."""
        ix = self.index_for_path(path)
        if not ix.isValid():
            return False
        if ix.parent().isValid():
            self.expand(ix.parent())
        self.setCurrentIndex(ix)
        self.scrollTo(ix)
        return True

    def item_info(self, index: QModelIndex) -> tuple[str, Path | None, Library | None, str]:
        """``(вид, путь, библиотека, имя)`` элемента ``index`` (вид — :data:`KIND_LIBRARY`,
        :data:`KIND_FILE`, :data:`KIND_FOOTPRINT` или ``""`` для пустого индекса)."""
        if not index.isValid():
            return "", None, None, ""
        item = self._model.itemFromIndex(index.siblingAtColumn(0))
        kind = item.data(KIND_ROLE) or ""
        path = item.data(PATH_ROLE)
        name = item.data(NAME_ROLE) or ""
        lib: Library | None = None
        if kind == KIND_LIBRARY:
            lib = item.data(Qt.ItemDataRole.UserRole)
        elif kind == KIND_FOOTPRINT and item.parent() is not None:
            lib = item.parent().data(Qt.ItemDataRole.UserRole)
        return kind, (Path(path) if path is not None else None), lib, name

    def selected_path(self) -> Path | None:
        """Путь текущего элемента (файл корпуса, одиночный файл или каталог библиотеки)."""
        return self.item_info(self.currentIndex())[1]

    # --- открытие -------------------------------------------------------------------------------
    def open_index(self, index: QModelIndex) -> bool:
        """Испустить :attr:`open_requested` для корпуса или одиночного файла ``index``;
        ``False`` — это не файл (например, корень библиотеки)."""
        kind, path, _lib, _name = self.item_info(index)
        if kind in (KIND_FOOTPRINT, KIND_FILE) and path is not None:
            self.open_requested.emit(path)
            return True
        return False

    def _on_double_clicked(self, index: QModelIndex) -> None:
        self.open_index(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — переопределение Qt
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != \
                QAbstractItemView.State.EditingState:
            ix = self.currentIndex()
            if self.open_index(ix):
                event.accept()
                return
            if ix.isValid():
                self.setExpanded(ix, not self.isExpanded(ix))
                event.accept()
                return
        if event.key() == Qt.Key.Key_Delete:
            kind = self.item_info(self.currentIndex())[0]
            if kind == KIND_FOOTPRINT:
                self.delete_selected_interactive()
                event.accept()
                return
        super().keyPressEvent(event)

    # --- операции над корпусами (без окон) -------------------------------------------------------
    def _resolve(self, target: Any) -> tuple[Library, str]:
        """Библиотека и имя корпуса по пути файла, индексу или паре ``(библиотека, имя)``."""
        if isinstance(target, QModelIndex):
            kind, _path, lib, name = self.item_info(target)
            if kind != KIND_FOOTPRINT or lib is None:
                raise ValueError("выбран не корпус библиотеки")
            return lib, name
        if isinstance(target, tuple) and len(target) == 2:
            lib, name = target
            if not isinstance(lib, Library):
                found = self._library_item(lib)
                if found is None:
                    raise KeyError(f"библиотека {lib!r} не открыта")
                lib = found.data(Qt.ItemDataRole.UserRole)
            return lib, str(name)
        p = _abs(target)
        lib = self.library_for(p)
        if lib is None or p.suffix != FOOTPRINT_EXT:
            raise ValueError(f"{p}: корпус не из открытой библиотеки .pretty")
        return lib, p.name[:-len(FOOTPRINT_EXT)]

    def rename_footprint(self, target: Any, new_name: str) -> Path:
        """Переименовать корпус (:meth:`Library.rename <kicadfp.library.Library.rename>`):
        ``target`` — путь к файлу, индекс дерева или ``(библиотека, имя)``. Возвращает
        новый путь; испускает :attr:`footprint_renamed` и :attr:`libraries_changed`.
        Ошибки (``FileExistsError``, ``KeyError``, ``ValueError``, ``OSError``) передаются
        вызывающему."""
        lib, old = self._resolve(target)
        new = sanitize_name(str(new_name).strip())
        old_path = _abs(lib.path_of(old))
        lib.rename(old, new)
        new_path = _abs(lib.path_of(new))
        self.refresh(lib)
        self.select_path(new_path)
        if new_path != old_path:
            self.footprint_renamed.emit(old_path, new_path)
        return new_path

    def delete_footprint(self, target: Any) -> Path:
        """Удалить файл корпуса (:meth:`Library.remove <kicadfp.library.Library.remove>`)
        без вопросов; вернуть путь удалённого файла; испускает :attr:`footprint_removed` и
        :attr:`libraries_changed`."""
        lib, name = self._resolve(target)
        path = _abs(lib.path_of(name))
        lib.remove(name)
        self.refresh(lib)
        self.footprint_removed.emit(path)
        return path

    def copy_footprint(self, target: Any, library: Library | str | PathLike[str],
                       new_name: str | None = None, *, overwrite: bool = False) -> Path:
        """Скопировать корпус в открытую библиотеку ``library`` (объект, имя или путь) под
        именем ``new_name`` (:meth:`Library.copy_to <kicadfp.library.Library.copy_to>`);
        вернуть путь нового файла. ``FileExistsError`` — такой корпус уже есть."""
        src, name = self._resolve(target)
        if isinstance(library, Library):
            dst = library
        else:
            item = self._library_item(library)
            if item is None:
                raise KeyError(f"библиотека {library!r} не открыта")
            dst = item.data(Qt.ItemDataRole.UserRole)
        name_new = name if not new_name or not str(new_name).strip() else str(new_name).strip()
        dup = src.copy_to(dst, name, name_new, overwrite=overwrite)
        path = _abs(dst.path_of(dup.name))
        if self._library_item(dst) is not None:
            self.refresh(dst)
        else:
            self.libraries_changed.emit()
        return path

    # --- интерактивные действия (с окнами) ------------------------------------------------------
    def _ask_text_dialog(self, title: str, label: str, text: str) -> str | None:
        value, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, text)
        return value if ok else None

    def _ask_confirm_dialog(self, title: str, question: str) -> bool:
        answer = QMessageBox.question(self, title, question,
                                      QMessageBox.StandardButton.Yes
                                      | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _ask_copy_dialog(self, libraries: list[Library], name: str,
                         source: Library) -> tuple[Library, str] | None:
        dlg = CopyFootprintDialog(libraries, name, source, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.target is None:
            return None
        return dlg.target, dlg.new_name

    def _report(self, message: str, *, interactive: bool = True) -> None:
        self.error.emit(message)
        if interactive and self.show_errors:
            QMessageBox.warning(self, "Библиотеки", message)

    def _current_footprint(self) -> tuple[Library, str] | None:
        kind, _path, lib, name = self.item_info(self.currentIndex())
        if kind != KIND_FOOTPRINT or lib is None:
            return None
        return lib, name

    def open_selected(self) -> bool:
        """Открыть текущий элемент (сигнал :attr:`open_requested`)."""
        return self.open_index(self.currentIndex())

    def rename_selected_interactive(self) -> Path | None:
        """«Переименовать…»: спросить новое имя (:attr:`ask_text`) и переименовать текущий
        корпус; ошибки показываются пользователю. ``None`` — отмена или ошибка."""
        cur = self._current_footprint()
        if cur is None:
            return None
        lib, name = cur
        new = self.ask_text("Переименовать корпус", "Новое имя корпуса:", name)
        if new is None or not new.strip() or new.strip() == name:
            return None
        try:
            return self.rename_footprint((lib, name), new)
        except FileExistsError:
            self._report(f"В библиотеке {lib.name} уже есть корпус «{sanitize_name(new)}»")
        except (KeyError, ValueError, OSError) as e:
            self._report(f"Не удалось переименовать «{name}»: {e}")
        return None

    def delete_selected_interactive(self) -> Path | None:
        """«Удалить…»: подтвердить (:attr:`ask_confirm`) и удалить файл текущего корпуса."""
        cur = self._current_footprint()
        if cur is None:
            return None
        lib, name = cur
        if not self.ask_confirm("Удалить корпус",
                                f"Удалить корпус «{name}» из библиотеки {lib.name}?\n"
                                f"Файл {lib.path_of(name)} будет удалён безвозвратно."):
            return None
        try:
            return self.delete_footprint((lib, name))
        except (KeyError, ValueError, OSError) as e:
            self._report(f"Не удалось удалить «{name}»: {e}")
        return None

    def copy_selected_interactive(self) -> Path | None:
        """«Копировать в библиотеку…»: выбрать библиотеку и имя (:attr:`ask_copy`) и
        скопировать текущий корпус."""
        cur = self._current_footprint()
        if cur is None:
            return None
        lib, name = cur
        if not self._libraries:
            return None
        answer = self.ask_copy(list(self._libraries), name, lib)
        if answer is None:
            return None
        target, new_name = answer
        try:
            return self.copy_footprint((lib, name), target, new_name or name)
        except FileExistsError:
            self._report(f"В библиотеке {target.name} уже есть корпус "
                         f"«{sanitize_name(new_name or name)}»")
        except (KeyError, ValueError, OSError) as e:
            self._report(f"Не удалось скопировать «{name}»: {e}")
        return None

    # --- контекстное меню -----------------------------------------------------------------------
    def context_menu_for(self, index: QModelIndex) -> QMenu:
        """Контекстное меню элемента ``index`` (для показа и для тестов: пункты —
        ``menu.actions()`` с понятными текстами)."""
        menu = QMenu(self)
        kind, _path, _lib, _name = self.item_info(index)

        def add(text: str, slot: Callable[[], Any], enabled: bool = True) -> QAction:
            act = QAction(text, menu)
            act.setEnabled(enabled)
            act.triggered.connect(lambda _checked=False: slot())
            menu.addAction(act)
            return act

        is_fp = kind == KIND_FOOTPRINT
        add("Открыть", self.open_selected, kind in (KIND_FOOTPRINT, KIND_FILE))
        if is_fp:
            add("Переименовать…", self.rename_selected_interactive)
            add("Копировать в библиотеку…", self.copy_selected_interactive,
                bool(self._libraries))
            add("Удалить…", self.delete_selected_interactive)
        menu.addSeparator()
        add("Обновить", self.refresh)
        if kind in (KIND_LIBRARY, KIND_FILE):
            add("Закрыть библиотеку" if kind == KIND_LIBRARY else "Закрыть файл",
                self.remove_selected)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        if index.isValid():
            self.setCurrentIndex(index)
        menu = self.context_menu_for(index)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def show_context_menu(self, pos: QPoint) -> None:
        """Показать контекстное меню в точке ``pos`` (координаты viewport)."""
        index = self.indexAt(pos)
        menu = self.context_menu_for(index)
        menu.exec(self.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # --- прочее ---------------------------------------------------------------------------------
    def expand_library(self, library: Library | str | PathLike[str],
                       expanded: bool = True) -> None:
        """Раскрыть (свернуть) корень библиотеки."""
        item = self._library_item(library)
        if item is not None:
            self.setExpanded(item.index(), expanded)

    def paths(self) -> Iterable[Path]:
        """Пути всех корней (каталоги библиотек и одиночные файлы) — для сохранения сеанса."""
        for r in range(self._model.rowCount()):
            p = self._model.item(r).data(PATH_ROLE)
            if p is not None:
                yield Path(p)
