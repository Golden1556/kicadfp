"""Дерево библиотек :class:`LibraryTree` и :class:`CopyFootprintDialog`: редкие ветви
(ошибки операций, отмена вопросов, клавиши, контекстное меню, закрытие корней)."""

from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QModelIndex, QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox  # noqa: E402

from kicadfp.gui import libtree as libtree_mod  # noqa: E402
from kicadfp.gui.libtree import (KIND_FILE, KIND_LIBRARY, CopyFootprintDialog,  # noqa: E402
                                 LibraryTree)
from kicadfp.library import Library  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

DIP_LIB = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14 = DIP_LIB / "DIP-14_W7.62mm.kicad_mod"
DIP8 = DIP_LIB / "DIP-8_W7.62mm.kicad_mod"


@pytest.fixture
def tree(qtbot) -> LibraryTree:
    t = LibraryTree()
    t.show_errors = False
    qtbot.addWidget(t)
    return t


@pytest.fixture
def libs(tmp_path):
    """Две временные библиотеки: A (DIP-14, DIP-8) и пустая B."""
    a = tmp_path / "A.pretty"
    a.mkdir()
    shutil.copy(DIP14, a)
    shutil.copy(DIP8, a)
    b = tmp_path / "B.pretty"
    b.mkdir()
    return a, b


def _errors(tree: LibraryTree) -> list[str]:
    out: list[str] = []
    tree.error.connect(out.append)
    return out


# --- CopyFootprintDialog ---------------------------------------------------------------------

def test_copy_dialog_default_target_and_set_target(qtbot, libs):
    a, b = Library(libs[0]), Library(libs[1])
    dlg = CopyFootprintDialog([a, b], "DIP-8_W7.62mm", source=a)
    qtbot.addWidget(dlg)
    assert dlg.target is b  # по умолчанию — другая библиотека
    assert dlg.new_name == "DIP-8_W7.62mm"
    dlg.set_target(0)
    assert dlg.target is a
    dlg.set_target("B")  # по имени
    assert dlg.target is b
    dlg.set_target(a)  # объект
    assert dlg.target is a
    dlg.set_target(libs[1])  # путь к каталогу
    assert dlg.target is b
    with pytest.raises(KeyError, match="не открыта"):
        dlg.set_target("Нет")
    dlg.set_new_name("  Новое  ")
    assert dlg.new_name == "Новое"


def test_copy_dialog_without_libraries(qtbot):
    dlg = CopyFootprintDialog([], "X")
    qtbot.addWidget(dlg)
    assert dlg.target is None


# --- добавление, закрытие, обновление ------------------------------------------------------

def test_add_library_object_and_errors(tree, libs, tmp_path):
    a = Library(libs[0])
    assert tree.add_library(a) is a
    assert tree.add_library(a) is a and tree.root_count() == 1  # тот же объект — не дубль
    assert tree.add_library(str(libs[0])) is a  # тот же каталог
    with pytest.raises(FileNotFoundError):
        tree.add_library(tmp_path / "missing.pretty")
    with pytest.raises(IsADirectoryError):
        tree.add_file(libs[0])
    with pytest.raises(KeyError, match="не открыта"):
        tree.children_names("Нет")
    # библиотека по имени и по пути (строкой с .pretty)
    assert tree.children_names("A") == ["DIP-14_W7.62mm", "DIP-8_W7.62mm"]
    assert tree.children_names(str(libs[0])) == tree.children_names(a)


def test_add_path_file_twice_and_paths(tree, libs, tmp_path):
    f = tmp_path / "single.kicad_mod"
    shutil.copy(DIP14, f)
    assert isinstance(tree.add_path(libs[0]), Library)
    p = tree.add_path(f)
    assert p == f.resolve()
    assert tree.add_file(str(f)) == p and tree.root_count() == 2  # не дублируется
    assert list(tree.paths()) == [libs[0].resolve(), f.resolve()]
    assert tree.item_info(tree.root_item(1).index())[0] == KIND_FILE
    assert tree.item_info(QModelIndex()) == ("", None, None, "")


def test_remove_root_and_clear_all(tree, libs, tmp_path, qtbot):
    f = tmp_path / "single.kicad_mod"
    shutil.copy(DIP14, f)
    tree.add_library(libs[0])
    tree.add_file(f)
    with qtbot.waitSignal(tree.libraries_changed):
        tree.remove_root(1)  # файл
    assert tree.files == [] and tree.root_count() == 1
    tree.remove_root(0)  # библиотека
    assert tree.libraries == [] and tree.root_count() == 0
    with pytest.raises(IndexError):
        tree.remove_root(0)
    # clear_all: пустое дерево — без сигнала; непустое — всё закрыто
    with qtbot.assertNotEmitted(tree.libraries_changed):
        tree.clear_all()
    tree.add_library(libs[0])
    tree.add_file(f)
    tree.clear_all()
    assert tree.root_count() == 0 and tree.libraries == [] and tree.files == []


def test_remove_selected_file_and_nothing(tree, libs, tmp_path):
    f = tmp_path / "single.kicad_mod"
    shutil.copy(DIP14, f)
    tree.add_library(libs[0])
    tree.add_file(f)
    tree.clearSelection()
    assert tree.remove_selected() == 0
    # выделенный корпус внутри библиотеки библиотеку не закрывает
    tree.select_path(libs[0] / DIP14.name)
    assert tree.remove_selected() == 0 and tree.root_count() == 2
    tree.setCurrentIndex(tree.root_item(1).index())
    assert tree.remove_selected() == 1
    assert tree.files == [] and tree.root_count() == 1


def test_refresh_errors_and_vanished_file(tree, libs, tmp_path):
    f = tmp_path / "single.kicad_mod"
    shutil.copy(DIP14, f)
    a = tree.add_library(libs[0])
    tree.add_file(f)
    tree.expand_library(a)
    assert tree.isExpanded(tree.root_item(0).index())
    with pytest.raises(KeyError, match="не открыта"):
        tree.refresh("Нет")
    f.unlink()  # одиночный файл удалён другой программой
    tree.refresh()
    assert tree.files == [] and tree.root_count() == 1
    assert tree.isExpanded(tree.root_item(0).index())  # раскрытие сохранено
    tree.expand_library(a, False)
    assert not tree.isExpanded(tree.root_item(0).index())
    assert tree.select_path(tmp_path / "nothing.kicad_mod") is False


def test_refresh_unreadable_library_reports_error(tree, libs, monkeypatch):
    a = tree.add_library(libs[0])
    errors = _errors(tree)

    def boom(self):
        raise PermissionError("нет доступа")
    monkeypatch.setattr(Library, "_disk_names", boom)
    tree.refresh(a)
    assert errors and "не удалось прочитать каталог" in errors[0]
    assert tree.children_names(a) == [] and tree.root_item(0).text() == "A (0)"


# --- операции над корпусами: ошибки ---------------------------------------------------------

def test_resolve_errors(tree, libs, tmp_path):
    tree.add_library(libs[0])
    with pytest.raises(ValueError, match="не корпус"):
        tree.rename_footprint(tree.root_item(0).index(), "X")
    with pytest.raises(KeyError, match="не открыта"):
        tree.rename_footprint(("Нет", "DIP-8_W7.62mm"), "X")
    with pytest.raises(ValueError, match="не из открытой библиотеки"):
        tree.delete_footprint(tmp_path / "other.kicad_mod")
    # пара (имя библиотеки, имя корпуса) — корпус находится
    p = tree.rename_footprint(("A", "DIP-8_W7.62mm"), "D8")
    assert p.name == "D8.kicad_mod" and p.is_file()
    # индекс дерева
    ix = tree.index_for_path(p)
    removed = tree.delete_footprint(ix)
    assert removed == p and not p.exists()


def test_copy_footprint_by_name_and_outside_tree(tree, libs, tmp_path, qtbot):
    a = tree.add_library(libs[0])
    tree.add_library(libs[1])
    p = tree.copy_footprint((a, "DIP-8_W7.62mm"), "B")  # библиотека по имени, имя прежнее
    assert p == (libs[1] / "DIP-8_W7.62mm.kicad_mod").resolve() and p.is_file()
    assert tree.children_names("B") == ["DIP-8_W7.62mm"]
    with pytest.raises(KeyError, match="не открыта"):
        tree.copy_footprint((a, "DIP-8_W7.62mm"), "Нет")
    # библиотека, не открытая в дереве: копия пишется, дерево лишь оповещает
    c = Library(tmp_path / "C.pretty", create=True)
    with qtbot.waitSignal(tree.libraries_changed):
        q = tree.copy_footprint((a, "DIP-8_W7.62mm"), c, "   ")
    assert q.name == "DIP-8_W7.62mm.kicad_mod" and q.is_file()
    assert tree.root_count() == 2


# --- интерактивные действия ----------------------------------------------------------------

def test_interactive_actions_without_footprint_selected(tree, libs):
    tree.add_library(libs[0])
    tree.setCurrentIndex(tree.root_item(0).index())  # корень библиотеки, не корпус
    called = []
    tree.ask_text = lambda *a: called.append("text") or "X"
    tree.ask_confirm = lambda *a: called.append("confirm") or True
    tree.ask_copy = lambda *a: called.append("copy") or None
    assert tree.rename_selected_interactive() is None
    assert tree.delete_selected_interactive() is None
    assert tree.copy_selected_interactive() is None
    assert called == []  # вопросы не задавались
    assert tree.open_selected() is False


def test_rename_interactive_cancel_same_and_error(tree, libs, monkeypatch):
    a = tree.add_library(libs[0])
    tree.select_path(libs[0] / DIP8.name)
    errors = _errors(tree)
    for answer in (None, "   ", "DIP-8_W7.62mm"):  # отмена, пусто, то же имя
        tree.ask_text = lambda *args, _a=answer: _a
        assert tree.rename_selected_interactive() is None
    assert errors == [] and (libs[0] / DIP8.name).exists()

    def fail(self, old, new, **kw):
        raise OSError("диск только для чтения")
    monkeypatch.setattr(Library, "rename", fail)
    tree.ask_text = lambda *args: "New"
    assert tree.rename_selected_interactive() is None
    assert errors == ["Не удалось переименовать «DIP-8_W7.62mm»: диск только для чтения"]
    assert tree.children_names(a) == ["DIP-14_W7.62mm", "DIP-8_W7.62mm"]


def test_delete_interactive_error(tree, libs, monkeypatch):
    tree.add_library(libs[0])
    tree.select_path(libs[0] / DIP8.name)
    tree.ask_confirm = lambda *a: True
    errors = _errors(tree)

    def fail(self, name):
        raise OSError("занят")
    monkeypatch.setattr(Library, "remove", fail)
    assert tree.delete_selected_interactive() is None
    assert errors and "Не удалось удалить «DIP-8_W7.62mm»" in errors[0]
    assert (libs[0] / DIP8.name).exists()


def test_copy_interactive_cancel_exists_and_error(tree, libs, monkeypatch):
    a = tree.add_library(libs[0])
    b = tree.add_library(libs[1])
    tree.select_path(libs[0] / DIP8.name)
    errors = _errors(tree)
    seen = []
    tree.ask_copy = lambda libraries, name, source: seen.append((libraries, name, source))
    assert tree.copy_selected_interactive() is None  # отмена
    assert seen == [([a, b], "DIP-8_W7.62mm", a)]
    shutil.copy(DIP8, libs[1])
    tree.refresh()
    tree.select_path(libs[0] / DIP8.name)
    tree.ask_copy = lambda *args: (b, "")  # пустое имя -> прежнее, а оно уже есть
    assert tree.copy_selected_interactive() is None
    assert errors[-1] == "В библиотеке B уже есть корпус «DIP-8_W7.62mm»"

    def fail(self, other, name, new_name=None, **kw):
        raise OSError("нет места")
    monkeypatch.setattr(Library, "copy_to", fail)
    tree.ask_copy = lambda *args: (b, "Other")
    assert tree.copy_selected_interactive() is None
    assert errors[-1] == "Не удалось скопировать «DIP-8_W7.62mm»: нет места"


def test_copy_interactive_without_libraries(tree, libs):
    a = tree.add_library(libs[0])
    tree.select_path(libs[0] / DIP8.name)
    tree._libraries = []  # состояние «библиотек нет» (защита от гонки при закрытии)
    tree.ask_copy = lambda *args: pytest.fail("вопрос не должен задаваться")
    assert tree.copy_selected_interactive() is None
    tree._libraries = [a]


def test_default_question_dialogs(tree, libs, monkeypatch):
    """Вопросы по умолчанию — стандартные окна Qt (подменены, чтобы не блокировать)."""
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a: ("Имя", True)))
    assert tree._ask_text_dialog("t", "l", "x") == "Имя"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a: ("Имя", False)))
    assert tree._ask_text_dialog("t", "l", "x") is None
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    assert tree._ask_confirm_dialog("t", "q") is True
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a: QMessageBox.StandardButton.No))
    assert tree._ask_confirm_dialog("t", "q") is False

    a = tree.add_library(libs[0])
    b = tree.add_library(libs[1])

    def accept(self):
        self.set_new_name("Copy")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CopyFootprintDialog, "exec", accept)
    assert tree._ask_copy_dialog([a, b], "DIP-8_W7.62mm", a) == (b, "Copy")
    monkeypatch.setattr(CopyFootprintDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert tree._ask_copy_dialog([a, b], "DIP-8_W7.62mm", a) is None


def test_report_shows_warning_only_when_enabled(tree, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: shown.append(a[2])))
    errors = _errors(tree)
    tree._report("ошибка 1")
    assert shown == [] and errors == ["ошибка 1"]  # show_errors=False — только сигнал
    tree.show_errors = True
    tree._report("ошибка 2")
    tree._report("ошибка 3", interactive=False)
    assert shown == ["ошибка 2"] and errors == ["ошибка 1", "ошибка 2", "ошибка 3"]


# --- клавиши и контекстное меню ------------------------------------------------------------

def test_enter_on_library_toggles_expand(tree, libs, qtbot):
    tree.add_library(libs[0])
    root = tree.root_item(0).index()
    tree.setCurrentIndex(root)
    assert not tree.isExpanded(root)
    qtbot.keyClick(tree, Qt.Key.Key_Return)
    assert tree.isExpanded(root)
    qtbot.keyClick(tree, Qt.Key.Key_Enter)
    assert not tree.isExpanded(root)


def test_delete_key_asks_and_removes_footprint(tree, libs, qtbot):
    a = tree.add_library(libs[0])
    tree.select_path(libs[0] / DIP8.name)
    questions = []
    tree.ask_confirm = lambda title, q: questions.append(q) or True
    with qtbot.waitSignal(tree.footprint_removed):
        qtbot.keyClick(tree, Qt.Key.Key_Delete)
    assert len(questions) == 1 and "DIP-8_W7.62mm" in questions[0]
    assert tree.children_names(a) == ["DIP-14_W7.62mm"]
    # Delete на корне библиотеки ничего не удаляет
    tree.setCurrentIndex(tree.root_item(0).index())
    qtbot.keyClick(tree, Qt.Key.Key_Delete)
    assert len(questions) == 1 and tree.root_count() == 1


def test_context_menu_file_root_and_empty_place(tree, libs, tmp_path):
    f = tmp_path / "single.kicad_mod"
    shutil.copy(DIP14, f)
    tree.add_file(f)
    texts = [a.text() for a in tree.context_menu_for(tree.root_item(0).index()).actions()]
    assert "Закрыть файл" in texts and "Переименовать…" not in texts
    menu = tree.context_menu_for(QModelIndex())
    acts = {a.text(): a for a in menu.actions() if a.text()}
    assert set(acts) == {"Открыть", "Обновить"} and not acts["Открыть"].isEnabled()
    # «Закрыть файл» из меню закрывает корень
    tree.setCurrentIndex(tree.root_item(0).index())
    close = next(a for a in tree.context_menu_for(tree.root_item(0).index()).actions()
                 if a.text() == "Закрыть файл")
    close.trigger()
    assert tree.root_count() == 0


def test_context_menu_events_show_menu(tree, libs, monkeypatch):
    from PySide6.QtGui import QContextMenuEvent
    tree.add_library(libs[0])
    tree.expand_library("A")
    tree.resize(300, 300)
    shown: list[list[str]] = []
    make_menu = tree.context_menu_for

    def fake_menu(index):  # меню не показывается (exec модален) — запоминаем пункты
        menu = make_menu(index)
        menu.exec = lambda *a: shown.append([x.text() for x in menu.actions()])
        return menu
    monkeypatch.setattr(tree, "context_menu_for", fake_menu)
    pos = tree.visualRect(tree.index_for_path(libs[0] / DIP8.name)).center()
    ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, tree.viewport().mapToGlobal(pos))
    tree.contextMenuEvent(ev)
    assert tree.selected_path() == (libs[0] / DIP8.name).resolve()  # щелчок выделяет
    assert "Удалить…" in shown[-1]
    tree.show_context_menu(QPoint(5, 290))  # пустое место под элементами
    assert "Удалить…" not in shown[-1] and "Обновить" in shown[-1]
    assert libtree_mod.KIND_LIBRARY == KIND_LIBRARY
