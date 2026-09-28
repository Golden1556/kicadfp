"""Главное окно MainWindow (pytest-qt, offscreen): сборка окна, открытие файлов и библиотек,
сценарий 8 ТЗ (перемещение площадки мышью и в таблице, отмена, повтор, сохранение),
создание типового корпуса через диалог, закрытие с несохранёнными изменениями, ошибки
открытия, недавние файлы и настройки, панель слоёв, операции меню."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import (QEvent, QMimeData, QPoint, QPointF, QSettings, Qt, QTimer,  # noqa: E402
                            QUrl)
from PySide6.QtGui import QContextMenuEvent, QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QLineEdit,  # noqa: E402
                               QMessageBox, QWidget)

import kicadfp  # noqa: E402
from kicadfp import generators, io, sexpr  # noqa: E402
from kicadfp.gui import main as gui_main  # noqa: E402
from kicadfp.gui.canvas import (HOLES_LAYER, LAYER_ROLE, PAD_NUMBERS_LAYER,  # noqa: E402
                                PreviewCanvas)
from kicadfp.gui.commands import AddItemCommand, SetAttrCommand  # noqa: E402
from kicadfp.gui.dialogs import (AboutDialog, GenerateDialog, ItemPropertiesDialog,  # noqa: E402
                                 PadBatchDialog)
from kicadfp.gui.mainwindow import (MAX_RECENT, PANEL_LAYERS, SETTINGS_ENV,  # noqa: E402
                                    LayersPanel, MainWindow, ParamsDialog, ParamSpec,
                                    default_settings)
from kicadfp.gui.pad_table import COL_DRILL, COL_X, COL_Y, format_mm  # noqa: E402
from kicadfp.model import Circle, Line, Pad, Rect, Text  # noqa: E402
from kicadfp.sexpr import SexprSyntaxError  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

DIP_LIB = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14 = DIP_LIB / "DIP-14_W7.62mm.kicad_mod"
DIP8 = DIP_LIB / "DIP-8_W7.62mm.kicad_mod"
KICAD5_DIP14 = FIXTURES / "kicad5" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
NOMOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


# ---------------------------------------------------------------------------------------------
# Фикстуры и помощники
# ---------------------------------------------------------------------------------------------

class Recorder:
    """Подмена вопросов окна: сообщения об ошибках и показанные диалоги записываются;
    диалог обрабатывает ``handler(диалог) -> bool`` (без него — ошибка теста)."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.dialogs: list[QDialog] = []
        self.handler = None

    def show_error(self, title: str, text: str) -> None:
        self.errors.append((title, text))

    def exec_dialog(self, dlg: QDialog) -> bool:
        self.dialogs.append(dlg)
        if self.handler is None:
            raise AssertionError(f"неожиданный модальный диалог {type(dlg).__name__}")
        return bool(self.handler(dlg))


def _unexpected(*args):
    raise AssertionError(f"неожиданный вопрос пользователю: {args!r}")


def _discard(w: MainWindow) -> None:
    """Перед закрытием окна в конце теста: не спрашивать о несохранённых изменениях."""
    w.document.confirm_discard = True


@pytest.fixture
def settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "kicadfp.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def rec() -> Recorder:
    return Recorder()


@pytest.fixture
def make(qtbot, settings, rec):
    """Фабрика окон: вопросы подменены (:class:`Recorder`), окно показано."""

    def factory(**kw) -> MainWindow:
        kw.setdefault("settings", settings)
        w = MainWindow(**kw)
        qtbot.addWidget(w, before_close_func=_discard)
        w.show_error = rec.show_error
        w.exec_dialog = rec.exec_dialog
        w.ask_open_file = w.ask_save_file = w.ask_directory = w.ask_text = _unexpected
        w.ask_save_changes = _unexpected
        w.exec_menu = _unexpected
        w.library_tree.show_errors = False
        w.resize(1440, 900)  # экран offscreen — 800×800: размер задаётся явно
        w.show()
        assert QTest.qWaitForWindowExposed(w)
        return w

    return factory


@pytest.fixture
def win(make) -> MainWindow:
    return make()


def activate(w: MainWindow) -> None:
    w.activateWindow()
    assert QTest.qWaitForWindowActive(w)


def open_dip(w: MainWindow, path: Path = DIP14) -> None:
    assert w.open_path(path) is True
    w.canvas.fit()


def vp(canvas: PreviewCanvas, x: float, y: float) -> QPoint:
    """Точка окна просмотра канвы для точки сцены (мм)."""
    return canvas.mapFromScene(QPointF(x, y))


def drag(canvas: PreviewCanvas, start: tuple[float, float], end: tuple[float, float],
         steps: int = 5) -> None:
    w = canvas.viewport()
    QTest.mousePress(w, LEFT, NOMOD, vp(canvas, *start))
    for i in range(1, steps + 1):
        t = i / steps
        QTest.mouseMove(w, vp(canvas, start[0] + (end[0] - start[0]) * t,
                              start[1] + (end[1] - start[1]) * t))
    QTest.mouseRelease(w, LEFT, NOMOD, vp(canvas, *end))


def table_xy(w: MainWindow, pad: Pad) -> tuple[str, str]:
    m = w.pad_table.pad_model()
    row = m.row_of(pad)
    assert row >= 0
    return m.data(m.index(row, COL_X)), m.data(m.index(row, COL_Y))


def canvas_xy(w: MainWindow, pad: Pad) -> set[tuple[float, float]]:
    return {(round(it.pos().x(), 6), round(it.pos().y(), 6)) for it in w.canvas.items_for(pad)}


def assert_views_agree(w: MainWindow, pad: Pad, x: float, y: float) -> None:
    """Модель, таблица площадок и канва показывают одно и то же положение площадки."""
    assert (pad.x, pad.y) == (x, y)
    assert table_xy(w, pad) == (format_mm(x), format_mm(y))
    assert canvas_xy(w, pad) == {(x, y)}


def is_within(widget: QWidget | None, ancestor: QWidget) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def copy_library(tmp_path: Path, names: tuple[str, ...] = ("DIP-14_W7.62mm", "DIP-8_W7.62mm"),
                 lib_name: str = "My.pretty") -> Path:
    lib = tmp_path / lib_name
    lib.mkdir()
    for n in names:
        shutil.copy(DIP_LIB / f"{n}.kicad_mod", lib / f"{n}.kicad_mod")
    return lib


# ---------------------------------------------------------------------------------------------
# Сборка окна
# ---------------------------------------------------------------------------------------------

def test_window_layout(win):
    assert win.windowTitle() == "kicadfp" and not win.isWindowModified()
    assert win.centralWidget() is win.canvas and isinstance(win.canvas, PreviewCanvas)
    docks = {d.windowTitle(): d for d in win.findChildren(QDockWidget)}
    assert set(docks) == {"Библиотеки", "Свойства корпуса", "Площадки", "Графика и тексты",
                          "Слои"}
    area = win.dockWidgetArea
    assert area(win.dock_libraries) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert area(win.dock_layers) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert area(win.dock_properties) == Qt.DockWidgetArea.RightDockWidgetArea
    assert area(win.dock_pads) == area(win.dock_items) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert win.tabifiedDockWidgets(win.dock_pads) == [win.dock_items]
    assert docks["Библиотеки"].widget() is win.library_tree
    assert docks["Площадки"].widget() is win.pad_table
    assert docks["Графика и тексты"].widget() is win.items_table
    assert docks["Слои"].widget() is win.layers_panel
    assert docks["Свойства корпуса"].widget().widget() is win.props_panel  # в QScrollArea
    assert all(d.objectName() for d in win.docks())  # нужно для saveState

    menus = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert menus == ["Файл", "Правка", "Корпус", "Вид", "Справка"]
    texts = {a.text() for m in (win.menu_file, win.menu_edit, win.menu_footprint,
                                win.menu_view, win.menu_help) for a in m.actions()}
    for t in ("Создать корпус…", "Открыть файл…", "Открыть библиотеку…", "Сохранить",
              "Сохранить как…", "Экспорт SVG…", "Экспорт PNG…", "Недавние файлы", "Выход",
              "Отменить", "Повторить", "Удалить", "Свойства элемента…",
              "Групповые операции над площадками…", "Добавить площадку", "Добавить линию",
              "Добавить прямоугольник", "Добавить окружность", "Добавить текст", "Проверить",
              "Создать типовой корпус…", "Сдвинуть…", "Повернуть…", "Отразить",
              "Перенумеровать площадки…", "Вписать", "Увеличить", "Уменьшить", "Сетка",
              "Привязка к сетке", "Показывать скрытые тексты", "О программе"):
        assert t in texts, t

    def keys(a):
        return [s.toString() for s in a.shortcuts()]

    assert keys(win.act_save) == ["Ctrl+S"] and keys(win.act_undo) == ["Ctrl+Z"]
    assert keys(win.act_redo)[0] == "Ctrl+Shift+Z" and keys(win.act_delete) == ["Del"]
    assert keys(win.act_validate) == ["F7"] and keys(win.act_fit) == ["F"]
    assert keys(win.act_properties)[0] == "Return" and keys(win.act_open) == ["Ctrl+O"]
    # Enter и F — только на канве: не мешают вводу в полях и таблицах
    for a in (win.act_properties, win.act_fit):
        assert a.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        assert a in win.canvas.actions()
    assert [a.text() for a in win.menu_grid.actions() if a.isCheckable()][:5] == \
        ["1.25 мм", "1 мм", "0.5 мм", "0.25 мм", "0.1 мм"]
    assert win.grid_actions[1.0].isChecked()

    tb = win.toolbar.actions()
    for a in (win.act_new, win.act_open, win.act_save, win.act_undo, win.act_redo,
              win.act_add_pad, win.act_delete, win.act_validate, win.act_generate, win.act_fit):
        assert a in tb and not a.icon().isNull()
    # без корпуса команды над ним недоступны
    for a in (win.act_save, win.act_save_as, win.act_export_svg, win.act_add_pad,
              win.act_validate, win.act_delete, win.act_batch, win.act_properties, win.act_move):
        assert not a.isEnabled()
    for a in (win.act_new, win.act_open, win.act_open_library, win.act_generate, win.act_quit):
        assert a.isEnabled()
    assert win.act_undo.text() == "Отменить" and not win.act_undo.isEnabled()
    assert win.document.undo_stack.undoLimit() >= 100
    assert win.coords_label.text().startswith("X") and win.grid_label.text() == "Сетка 1 мм"
    assert win.file_label.text() == "" and win.modified_label.text() == ""


def test_open_dip14_fills_tables_panels_and_canvas(win):
    assert win.open_path(DIP14) is True
    doc = win.document
    fp = doc.fp
    assert doc.path == DIP14 and not doc.is_modified
    assert win.windowTitle() == "kicadfp — DIP-14_W7.62mm [*]" and not win.isWindowModified()
    assert win.file_label.text() == DIP14.name and win.file_label.toolTip() == str(DIP14)
    assert win.modified_label.text() == ""
    pm = win.pad_table.model()
    assert pm.rowCount() == 14 == len(fp.pads)
    assert [pm.data(pm.index(r, 0)) for r in range(14)] == [p.number for p in fp.pads]
    im = win.items_table.model()
    assert im.rowCount() == len(fp.graphics) + len(fp.texts) > 0
    assert win.props_panel.name_edit.text() == "DIP-14_W7.62mm"
    assert win.props_panel.descr_edit.text() == fp.descr
    assert all(win.canvas.items_for(p) for p in fp.pads)
    assert all(win.canvas.items_for(g) for g in fp.graphics)
    # дерево библиотек: библиотека файла открыта, файл выделен
    lib = win.library_tree.library_for(DIP14)
    assert lib is not None and lib.name == "Package_DIP"
    assert win.library_tree.selected_path() == DIP14
    assert win.recent_files()[0] == str(DIP14)
    for a in (win.act_save, win.act_save_as, win.act_validate, win.act_add_pad, win.act_batch,
              win.act_move, win.act_renumber):
        assert a.isEnabled()
    assert not win.act_delete.isEnabled() and not win.act_properties.isEnabled()
    names = win.layers_panel.layer_names()
    assert names[:2] == ["F.Cu", "B.Cu"] and names[-2:] == [HOLES_LAYER, PAD_NUMBERS_LAYER]
    assert all(win.layers_panel.is_checked(n) for n in names)
    # выделение — в таблице и на канве
    doc.select(fp.pad("3"))
    assert win.pad_table.selected_rows() == [2]
    assert win.canvas.highlight_item() is not None
    assert win.act_delete.isEnabled() and win.act_properties.isEnabled()


def test_cursor_coordinates_in_status_bar(win):
    open_dip(win)
    c = win.canvas
    QTest.mouseMove(c.viewport(), vp(c, 2.0, 5.0))
    m = re.fullmatch(r"X (-?\d+\.\d{3})  Y (-?\d+\.\d{3}) мм", win.coords_label.text())
    assert m, win.coords_label.text()
    tol = 2.0 / c.zoom  # пиксель-другой
    assert abs(float(m.group(1)) - 2.0) <= tol and abs(float(m.group(2)) - 5.0) <= tol
    QApplication.sendEvent(c.viewport(), QEvent(QEvent.Type.Leave))  # курсор ушёл с канвы
    assert win.coords_label.text() == "X —  Y —"


def test_title_escapes_placeholder_in_name(win):
    assert win.new_footprint("A[*]B")
    assert win.windowTitle() == "kicadfp — A[*][*]B [*]"  # Qt покажет «A[*]B»
    assert not win.isWindowModified()


# ---------------------------------------------------------------------------------------------
# Сценарий 8 ТЗ
# ---------------------------------------------------------------------------------------------

def test_scenario_8_drag_and_table_undo_redo_save(win, qtbot, tmp_path):
    """Переместить площадку мышью и в таблице, отменить, повторить, сохранить: значения в
    таблице и на поле просмотра совпадают, файл содержит итоговые координаты."""
    activate(win)
    open_dip(win)
    doc = win.document
    pad = doc.fp.pad("1")
    assert_views_agree(win, pad, 0.0, 0.0)

    # 1. мышью: площадка 1 из (0, 0) в (-2, -3), привязка к сетке 1 мм
    assert win.canvas.snap and win.canvas.grid == 1.0
    drag(win.canvas, (0.0, 0.0), (-2.0, -3.0))
    assert doc.selected == pad
    assert_views_agree(win, pad, -2.0, -3.0)
    assert doc.undo_stack.count() == 1 and win.isWindowModified()
    assert win.modified_label.text() == "изменён"
    assert win.act_undo.text() == "Отменить перемещение площадки 1"

    # 2. в таблице: X = 5.08 — ввод в редакторе ячейки и Enter
    table = win.pad_table
    idx = table.model().index(table.pad_model().row_of(pad), COL_X)
    table.setFocus()
    table.setCurrentIndex(idx)
    table.edit(idx)
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit) and is_within(editor, table)
    editor.selectAll()
    QTest.keyClicks(editor, "5.08")
    QTest.keyClick(editor, Qt.Key.Key_Return)  # Enter окна (свойства) не перехватывает
    qtbot.waitUntil(lambda: pad.x == 5.08)
    assert_views_agree(win, pad, 5.08, -3.0)
    assert doc.undo_stack.count() == 2

    # 3. отменить и повторить: клавишами на канве и пунктами меню
    win.canvas.setFocus()
    QTest.keyClick(win.canvas, Qt.Key.Key_Z, CTRL)
    assert_views_agree(win, pad, -2.0, -3.0)
    win.act_undo.trigger()
    assert_views_agree(win, pad, 0.0, 0.0)
    assert not doc.is_modified and not win.isWindowModified()
    assert win.modified_label.text() == ""
    QTest.keyClick(win.canvas, Qt.Key.Key_Z, CTRL | SHIFT)
    assert_views_agree(win, pad, -2.0, -3.0)
    win.act_redo.trigger()
    assert_views_agree(win, pad, 5.08, -3.0)
    assert win.isWindowModified()

    # 4. сохранить в новый файл
    out = tmp_path / "DIP-14_W7.62mm.kicad_mod"
    assert win.save_as(out) is True
    assert doc.path == out and not doc.is_modified and not win.isWindowModified()
    assert win.file_label.text() == out.name
    saved = kicadfp.load(out)
    assert (saved.pad("1").x, saved.pad("1").y) == (5.08, -3.0)
    original = kicadfp.load(DIP14)
    diffs = sexpr.diff(original.node, saved.node)
    assert diffs and all(d.startswith("footprint/pad[0]/at") for d in diffs), diffs
    assert win.recent_files()[0] == str(out)

    # 5. ещё одно изменение и Ctrl+S — в тот же файл
    table.pad_model().setData(table.model().index(0, COL_Y), "-2.54")
    assert_views_agree(win, pad, 5.08, -2.54)
    QTest.keyClick(win.canvas, Qt.Key.Key_S, CTRL)
    assert not doc.is_modified
    again = kicadfp.load(out)
    assert (again.pad("1").x, again.pad("1").y) == (5.08, -2.54)


# ---------------------------------------------------------------------------------------------
# Создание корпусов
# ---------------------------------------------------------------------------------------------

def test_generate_dip_via_dialog_opens_new_document(win, rec):
    def fill(dlg):
        assert isinstance(dlg, GenerateDialog)
        dlg.set_generator("dip")
        assert dlg.set_param("pins", 14) is True
        dlg.accept()
        return dlg.result() == QDialog.DialogCode.Accepted

    rec.handler = fill
    win.act_generate.trigger()
    assert len(rec.dialogs) == 1
    doc = win.document
    assert doc.fp is not None and len(doc.fp.pads) == 14
    assert win.pad_table.model().rowCount() == 14
    assert io.dumps(doc.fp).count("(pad ") == 14
    assert doc.path is None and doc.is_modified and win.isWindowModified()
    assert win.windowTitle() == "kicadfp — DIP-14_W7.62mm [*]"
    assert win.file_label.text() == "не сохранён" and win.modified_label.text() == "изменён"
    assert doc.undo_stack.count() == 0

    # отмена диалога — ничего не меняется
    rec.handler = lambda dlg: False
    assert win.generate() is False and len(doc.fp.pads) == 14

    # несохранённый корпус: вопрос; «Отмена» — остаётся прежний
    asked = []
    win.ask_save_changes = lambda: asked.append(1) or "cancel"
    rec.handler = fill
    assert win.generate("lab_snp8") is False
    assert asked == [1] and doc.fp.name == "DIP-14_W7.62mm"
    # «Не сохранять» — открывается новый
    win.ask_save_changes = lambda: "discard"

    def snp8(dlg):
        assert dlg.generator == "lab_snp8"
        dlg.accept()
        return True

    rec.handler = snp8
    assert win.generate("lab_snp8") is True
    assert doc.fp.name == "snp8" and len(doc.fp.pads) == len(generators.lab_snp8().pads)


def test_generate_dialog_error_is_reported(win, rec):
    def bad(dlg):
        dlg.set_generator("dip")
        dlg.set_param("pins", 13)  # нечётное — генератор отвергает
        dlg.accept()  # не закрывается при ошибке
        return True

    rec.handler = bad
    assert win.generate() is False
    assert rec.errors and win.document.fp is None


def test_new_footprint_and_save_as_interactive(win, tmp_path):
    asked = []
    win.ask_text = lambda title, label, text: asked.append(text) or "MyPart"
    win.act_new.trigger()
    doc = win.document
    assert asked == ["NewFootprint"] and doc.fp.name == "MyPart" and doc.fp.pads == []
    assert win.windowTitle() == "kicadfp — MyPart [*]" and not win.isWindowModified()
    assert win.add_pad() is not None
    assert doc.fp.pads[0].number == "1" and win.isWindowModified()
    suggested = []

    def ask_save(title, flt, path):
        suggested.append(path)
        return str(tmp_path / "MyPart")  # без расширения — добавится .kicad_mod

    win.ask_save_file = ask_save
    win.act_save.trigger()  # нет файла — «Сохранить как…»
    out = tmp_path / "MyPart.kicad_mod"
    assert suggested and suggested[0].endswith("MyPart.kicad_mod")
    assert doc.path == out and out.is_file() and not win.isWindowModified()
    assert len(kicadfp.load(out).pads) == 1
    # отказ от выбора файла
    win.ask_save_file = lambda *a: None
    assert win.save_as_interactive() is False
    # пустое имя
    win.ask_text = lambda *a: "  "
    assert win.new_footprint_interactive() is False


# ---------------------------------------------------------------------------------------------
# Закрытие и несохранённые изменения
# ---------------------------------------------------------------------------------------------

def test_close_with_unsaved_changes_calls_confirm(win):
    open_dip(win)
    calls: list[int] = []

    def refuse():
        calls.append(1)
        return False

    win.document.confirm_discard = refuse
    assert win.move_footprint(1.0, 0.0) is True and win.document.is_modified
    assert win.close() is False
    assert calls == [1] and win.isVisible()

    def allow():
        calls.append(2)
        return True

    win.document.confirm_discard = allow
    assert win.close() is True
    assert calls == [1, 2] and not win.isVisible()


def test_close_without_changes_does_not_ask(win):
    open_dip(win)
    win.document.confirm_discard = _unexpected
    assert win.close() is True


def test_default_confirm_asks_save_discard_cancel(win, tmp_path):
    src = tmp_path / "a.kicad_mod"
    shutil.copy(DIP14, src)
    assert win.open_path(src)
    doc = win.document
    win.move_footprint(0.0, 1.0)
    answers = ["cancel"]
    win.ask_save_changes = lambda: answers.pop(0)
    assert win.open_path(DIP8) is False  # «Отмена»: остаётся изменённый корпус
    assert doc.path == src and doc.is_modified
    answers.append("save")
    assert win.open_path(DIP8) is True  # «Сохранить»: записан, открыт новый
    assert doc.path == DIP8 and not doc.is_modified
    assert kicadfp.load(src).pad("1").y == 1.0
    win.move_footprint(0.0, 1.0)
    answers.append("discard")
    assert win.close() is True  # «Не сохранять»
    assert kicadfp.load(DIP8).pad("1").y == 0.0  # файл библиотеки не тронут


def test_save_for_unsaved_document_asks_path_and_cancel_keeps_open(win, rec):
    rec.handler = lambda dlg: (dlg.set_generator("lab_mlt"), dlg.accept(), True)[-1]
    assert win.generate() is True
    win.ask_save_changes = lambda: "save"
    win.ask_save_file = lambda *a: None  # отказ от выбора файла
    assert win.close() is False and win.isVisible()


# ---------------------------------------------------------------------------------------------
# Ошибки открытия
# ---------------------------------------------------------------------------------------------

def test_open_syntax_error_shows_line_and_position(win, rec, tmp_path):
    bad = tmp_path / "bad.kicad_mod"
    bad.write_text('(footprint "bad"\n\t(layer "F.Cu")\n\t(pad "1" smd rect (at 0 0) '
                   '(size 1 1)\n', encoding="utf-8")
    with pytest.raises(SexprSyntaxError) as ei:
        io.load(bad)
    assert win.open_path(bad) is False
    (title, text), = rec.errors
    assert str(ei.value) in text and re.search(r"строка \d+, позиция \d+", text)
    assert str(bad) in text
    assert win.document.fp is None and win.windowTitle() == "kicadfp"
    assert str(bad) not in win.recent_files()
    # открытый корпус остаётся открытым
    open_dip(win)
    assert win.open_path(bad) is False
    assert win.document.path == DIP14 and len(rec.errors) == 2


def test_open_missing_file_and_legacy(win, rec, tmp_path):
    assert win.open_file(tmp_path / "нет.kicad_mod") is False
    assert "не найден" in rec.errors[-1][1]
    # .mod из нескольких корпусов — сообщение, корпус не открыт
    legacy_lib = FIXTURES / "legacy_mod" / "My_lib.mod"
    assert win.open_path(legacy_lib) is False
    assert len(rec.errors) == 2 and win.document.fp is None
    # .mod с одним корпусом — открывается как новый несохранённый (путь документа пуст)
    lines = legacy_lib.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    start = next(i for i, s in enumerate(lines) if s.startswith("$MODULE"))
    end = next(i for i, s in enumerate(lines) if s.startswith("$EndMODULE"))
    one = lines[:2] + ["$INDEX", "dip14", "$EndINDEX"] + lines[start:end + 1] + ["$EndLIBRARY"]
    mod = tmp_path / "one.mod"
    mod.write_text("\n".join(one) + "\n", encoding="utf-8")
    assert win.open_path(mod) is True
    doc = win.document
    assert doc.fp.name == "dip14" and doc.path is None and doc.is_modified
    assert win.windowTitle() == "kicadfp — dip14 [*]" and win.isWindowModified()
    assert win.file_label.text() == "не сохранён"
    assert "старый формат" in win.statusBar().currentMessage()
    assert mod in win.library_tree.files and win.recent_files()[0] == str(mod)


# ---------------------------------------------------------------------------------------------
# Правка
# ---------------------------------------------------------------------------------------------

def test_add_items_at_view_center(win):
    open_dip(win)
    doc = win.document
    c = win.canvas
    c.center_on(3.0, 7.0)
    x, y = win.placement_point()
    center = c.view_center()
    assert abs(x - center.x()) <= c.grid / 2 + 1e-9 and abs(y - center.y()) <= c.grid / 2 + 1e-9
    assert x == round(x / c.grid) * c.grid  # привязка к сетке
    d = win.placement_span()
    assert d >= c.grid

    win.act_add_pad.trigger()
    pad = doc.selected
    assert isinstance(pad, Pad) and pad.number == "15" and (pad.x, pad.y) == (x, y)
    assert pad.type == "thru_hole" and pad.shape == "oval"  # по образцу последней площадки
    assert win.pad_table.model().rowCount() == 15 and win.canvas.items_for(pad)
    win.act_add_line.trigger()
    line = doc.selected
    assert isinstance(line, Line) and line.layer == "F.SilkS" and line.width == 0.12
    assert line.start == (x - d, y) and line.end == (x + d, y)
    win.act_add_rect.trigger()
    rect = doc.selected
    assert isinstance(rect, Rect) and rect.start == (x - d, y - d) and rect.end == (x + d, y + d)
    win.act_add_circle.trigger()
    circle = doc.selected
    assert isinstance(circle, Circle) and circle.center == (x, y) and circle.radius == d
    win.act_add_text.trigger()
    text = doc.selected
    assert isinstance(text, Text) and text.kind == "user" and text.text == "Текст"
    assert (text.x, text.y) == (x, y) and text.layer == "F.SilkS"
    assert doc.undo_stack.count() == 5
    fp = doc.fp
    assert win.items_table.model().rowCount() == len(fp.graphics) + len(fp.texts)
    for _ in range(5):
        win.act_undo.trigger()
    assert len(fp.pads) == 14 and not doc.is_modified and doc.selected is None


def test_add_pad_uses_selected_pad_and_empty_footprint_default(win):
    open_dip(win)
    doc = win.document
    doc.select(doc.fp.pad("1"))  # прямоугольная площадка 1 — образец
    pad = win.add_pad()
    assert pad.shape == "rect" and pad.number == "15" and pad.drill.diameter == 0.8
    win.ask_save_changes = lambda: "discard"  # корпус изменён — вопрос перед новым
    assert win.new_footprint("Empty")
    pad = win.add_pad()
    assert pad.number == "1" and pad.type == "thru_hole" and pad.shape == "circle"
    assert (pad.size_x, pad.size_y) == (1.6, 1.6) and pad.drill.diameter == 0.8


def test_add_rect_in_kicad5_file_uses_four_lines(win, rec):
    """В формате KiCad 5 (``module``) нет ``fp_rect``: «Добавить прямоугольник» рисует его
    четырьмя ``fp_line`` одним шагом отмены (как библиотеки KiCad 5), а не падает."""
    open_dip(win, KICAD5_DIP14)
    doc = win.document
    fp = doc.fp
    assert fp.node.name == "module"
    text0 = io.dumps(fp)
    n_graphics = len(fp.graphics)
    (x, y), d = win.placement_point(), win.placement_span()
    first = win.add_rect()
    assert isinstance(first, Line) and doc.selected == first
    new = fp.graphics[n_graphics:]
    assert len(new) == 4 and all(isinstance(g, Line) for g in new)
    assert all(g.node.name == "fp_line" and g.layer == "F.SilkS" and g.width == 0.12 for g in new)
    corners = [(x - d, y - d), (x + d, y - d), (x + d, y + d), (x - d, y + d)]
    assert [(g.start, g.end) for g in new] == [(corners[i], corners[(i + 1) % 4])
                                               for i in range(4)]
    assert "fp_rect" not in io.dumps(fp)
    assert doc.undo_stack.count() == 1 and not rec.errors
    assert win.items_table.model().rowCount() == len(fp.graphics) + len(fp.texts)
    win.act_undo.trigger()
    assert io.dumps(fp) == text0 and not doc.is_modified
    # в формате KiCad 6+ — обычный fp_rect
    open_dip(win)
    assert isinstance(win.add_rect(), Rect)


def test_canvas_context_menu(win):
    open_dip(win)
    doc = win.document
    menu = win.canvas_context_menu(QPointF(0.0, 0.0))  # под курсором площадка 1
    assert doc.selected == doc.fp.pad("1")
    actions = {a.text(): a for a in menu.actions() if a.text()}
    assert actions["Свойства элемента…"] is win.act_properties and win.act_properties.isEnabled()
    assert actions["Удалить"] is win.act_delete and win.act_delete.isEnabled()
    for t in ("Добавить площадку", "Добавить линию", "Добавить прямоугольник",
              "Добавить окружность", "Добавить текст", "Отменить", "Вписать"):
        assert t in actions, t
    menu.deleteLater()
    # пустое место: выделение снимается, добавление — в точку щелчка (по сетке)
    menu = win.canvas_context_menu(QPointF(20.2, -4.9))
    assert doc.selected is None and not win.act_delete.isEnabled()
    actions = {a.text(): a for a in menu.actions() if a.text()}
    actions["Добавить площадку"].trigger()
    pad = doc.selected
    assert isinstance(pad, Pad) and (pad.x, pad.y) == (20.0, -5.0)
    actions["Добавить окружность"].trigger()
    assert isinstance(doc.selected, Circle) and doc.selected.center == (20.0, -5.0)
    actions["Добавить текст"].trigger()
    assert isinstance(doc.selected, Text) and (doc.selected.x, doc.selected.y) == (20.0, -5.0)
    menu.deleteLater()


def test_canvas_context_menu_event(win):
    open_dip(win)
    shown: list[list[str]] = []
    win.exec_menu = lambda menu, pos: shown.append(
        [x.text() for x in menu.actions() if x.text()])
    c = win.canvas
    pad2 = win.document.fp.pad("2")
    pos = vp(c, pad2.x, pad2.y)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, c.viewport().mapToGlobal(pos))
    QApplication.sendEvent(c.viewport(), event)
    assert len(shown) == 1 and shown[0][:2] == ["Свойства элемента…", "Удалить"]
    assert win.document.selected == pad2


def test_delete_selected(win):
    activate(win)
    open_dip(win)
    doc = win.document
    doc.select(doc.fp.pad("3"))
    win.canvas.setFocus()
    win.act_delete.trigger()
    assert [p.number for p in doc.fp.pads].count("3") == 0 and len(doc.fp.pads) == 13
    assert win.pad_table.model().rowCount() == 13 and doc.selected is None
    assert not win.act_delete.isEnabled()
    win.act_undo.trigger()
    assert len(doc.fp.pads) == 14
    # Del на канве
    doc.select(doc.fp.pad("5"))
    win.canvas.setFocus()
    QTest.keyClick(win.canvas, Qt.Key.Key_Delete)
    assert len(doc.fp.pads) == 13
    # Reference и Value не удаляются
    doc.select(doc.fp.reference)
    assert not win.act_delete.isEnabled()
    assert win.remove_item(doc.fp.reference) is False and doc.fp.reference is not None
    # несколько строк таблицы площадок — одним шагом отмены
    count = doc.undo_stack.count()
    table = win.pad_table
    table.setFocus()
    table.selectRow(0)
    table.selectionModel().select(
        table.model().index(1, 0),
        table.selectionModel().SelectionFlag.Select | table.selectionModel().SelectionFlag.Rows)
    assert table.selected_rows() == [0, 1]
    assert win.delete_selected() == 2
    assert len(doc.fp.pads) == 11 and doc.undo_stack.count() == count + 1


def test_delete_key_in_tables_and_fields(win):
    """Клавиша Del: в таблице площадок и в таблице графики удаляет выделенные строки, в поле
    ввода — символ (не элемент корпуса)."""
    activate(win)
    open_dip(win)
    doc = win.document
    table = win.pad_table
    table.setFocus()
    table.selectRow(2)
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert [p.number for p in doc.fp.pads].count("3") == 0 and doc.undo_stack.count() == 1
    items = win.items_table
    win.dock_items.raise_()
    items.setFocus()
    items.selectRow(0)
    removed = items.items_model().item_at(0)
    n = len(doc.fp.graphics)
    QTest.keyClick(items, Qt.Key.Key_Delete)
    assert len(doc.fp.graphics) == n - 1 and removed not in doc.fp.graphics
    edit = win.props_panel.name_edit
    edit.setFocus()
    edit.setCursorPosition(0)
    doc.select(doc.fp.pad("1"))
    count = doc.undo_stack.count()
    QTest.keyClick(edit, Qt.Key.Key_Delete)
    assert edit.text() == "IP-14_W7.62mm" and doc.fp.pad("1") is not None
    assert doc.undo_stack.count() == count and doc.fp.name == "DIP-14_W7.62mm"


def test_edit_properties_via_dialog_enter_and_double_click(win, rec, qtbot):
    activate(win)
    open_dip(win)
    doc = win.document
    pad1 = doc.fp.pad("1")

    def set_size(dlg):
        assert isinstance(dlg, ItemPropertiesDialog) and dlg.item == doc.selected
        dlg.set_field("size_x", "2.2")
        dlg.accept()
        return dlg.result() == QDialog.DialogCode.Accepted

    rec.handler = set_size
    doc.select(pad1)
    assert win.act_properties.isEnabled()
    win.act_properties.trigger()
    assert pad1.size_x == 2.2 and doc.undo_stack.count() == 1
    assert win.pad_table.model().data(win.pad_table.model().index(0, 6)) == "2.2"

    # Enter на канве
    seen: list = []
    rec.handler = lambda dlg: seen.append(dlg.item) or False
    win.canvas.setFocus()
    QTest.keyClick(win.canvas, Qt.Key.Key_Return)
    assert seen == [pad1]
    # двойной щелчок по площадке 2 на канве — выделение и свойства
    pad2 = doc.fp.pad("2")
    QTest.mouseDClick(win.canvas.viewport(), LEFT, NOMOD, vp(win.canvas, pad2.x, pad2.y))
    qtbot.waitUntil(lambda: len(seen) == 2)
    assert seen[1] == pad2 and doc.selected == pad2
    # Enter на строке таблицы (вне редактирования)
    table = win.pad_table
    table.setFocus()
    table.setCurrentIndex(table.model().index(3, 0))
    QTest.keyClick(table, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(seen) == 3)
    assert seen[2] == doc.fp.pad("4")
    # свойства корпуса — панель
    assert win.edit_properties(doc.fp) is True and win.dock_properties.isVisible()
    assert doc.undo_stack.count() == 1


def test_pad_batch_dialog_single_undo_step(win, rec):
    open_dip(win)
    doc = win.document
    table = win.pad_table
    table.selectRow(0)
    for r in (1, 2):
        table.selectionModel().select(
            table.model().index(r, 0),
            table.selectionModel().SelectionFlag.Select
            | table.selectionModel().SelectionFlag.Rows)

    def fill(dlg):
        assert isinstance(dlg, PadBatchDialog)
        assert dlg.scope == "selected" and len(dlg.target_pads()) == 3
        dlg.set_size(2.0)
        dlg.accept()
        return dlg.result() == QDialog.DialogCode.Accepted

    rec.handler = fill
    win.act_batch.trigger()
    sizes = [(p.number, p.size_x) for p in doc.fp.pads]
    assert sizes[:3] == [("1", 2.0), ("2", 2.0), ("3", 2.0)]
    assert all(s == 1.6 for _, s in sizes[3:]) and doc.undo_stack.count() == 1
    # из контекстного меню таблицы (сигнал batch_requested): все площадки
    table.clearSelection()

    def drill_all(dlg):
        assert dlg.scope == "all"
        dlg.set_drill(1.0)
        dlg.accept()
        return True

    rec.handler = drill_all
    doc.select(None)
    table.request_batch()
    assert all(p.drill.diameter == 1.0 for p in doc.fp.pads) and doc.undo_stack.count() == 2


# ---------------------------------------------------------------------------------------------
# Операции над корпусом
# ---------------------------------------------------------------------------------------------

def test_move_rotate_flip_renumber(win, rec):
    open_dip(win)
    doc = win.document
    before = [(p.number, p.x, p.y) for p in doc.fp.pads]

    def move(dlg):
        assert isinstance(dlg, ParamsDialog) and dlg.names() == ["dx", "dy"]
        dlg.set_value("dx", 1.27)
        dlg.set_value("dy", -2.54)
        dlg.accept()
        return True

    rec.handler = move
    win.act_move.trigger()
    after = [(p.number, p.x, p.y) for p in doc.fp.pads]
    assert after == [(n, round(x + 1.27, 6), round(y - 2.54, 6)) for n, x, y in before]
    assert doc.undo_stack.count() == 1
    pad1 = doc.fp.pad("1")
    assert canvas_xy(win, pad1) == {(1.27, -2.54)}

    # кнопка «Площадка 1 в (0, 0)» подставляет сдвиг
    def to_origin(dlg):
        dlg.buttons["Площадка 1 в (0, 0)"].click()
        assert (dlg.value("dx"), dlg.value("dy")) == (-1.27, 2.54)
        dlg.accept()
        return True

    rec.handler = to_origin
    win.act_move.trigger()
    assert [(p.number, p.x, p.y) for p in doc.fp.pads] == before

    expected = kicadfp.load(DIP14)
    expected.rotate(90.0, (3.81, 7.62))

    def rotate(dlg):
        assert dlg.value("angle") == 90.0
        dlg.buttons["Центр площадок"].click()
        assert (dlg.value("x"), dlg.value("y")) == (3.81, 7.62)
        dlg.accept()
        return True

    rec.handler = rotate
    win.act_rotate.trigger()
    assert [(p.number, p.x, p.y, p.angle) for p in doc.fp.pads] == \
        [(p.number, p.x, p.y, p.angle) for p in expected.pads]
    win.act_undo.trigger()

    assert win.flip_footprint() is True
    assert doc.fp.layer == "B.Cu" and doc.fp.pad("8").x == -7.62
    win.act_undo.trigger()
    assert doc.fp.layer == "F.Cu"

    def renumber(dlg):
        assert dlg.names() == ["start", "order", "prefix"]
        dlg.set_value("order", "circular")
        dlg.set_value("prefix", "A")
        with pytest.raises(ValueError):
            dlg.set_value("order", "zigzag")
        dlg.accept()
        return True

    rec.handler = renumber
    win.act_renumber.trigger()
    assert [p.number for p in doc.fp.pads] == [f"A{i}" for i in range(1, 15)]
    with pytest.raises(ValueError):
        win.renumber_pads(order="zigzag")
    # отмена диалога — без изменений
    count = doc.undo_stack.count()
    rec.handler = lambda dlg: False
    assert win.move_interactive() is False and doc.undo_stack.count() == count


def test_validate_opens_nonmodal_dialog(win, qtbot):
    activate(win)
    open_dip(win)
    doc = win.document
    pm = win.pad_table.pad_model()
    assert pm.setData(pm.index(0, COL_DRILL), "3") is True  # отверстие больше площадки
    win.act_validate.trigger()
    dlg = win.validate_dialog()
    assert dlg.isVisible() and not dlg.isModal()
    assert any(i.code == "PAD_DRILL_GT_SIZE" for i in dlg.issues)
    assert "ошибок" in win.statusBar().currentMessage()
    # повторная проверка (F7) при открытом окне — то же окно, проверка заново
    win.statusBar().clearMessage()
    win.canvas.setFocus()
    QTest.keyClick(win.canvas, Qt.Key.Key_F7)
    assert win.validate_dialog() is dlg and dlg.isVisible()
    assert "ошибок" in win.statusBar().currentMessage()
    # окно обновляется после изменений, двойной щелчок — выделение
    win.act_undo.trigger()
    assert not any(i.code == "PAD_DRILL_GT_SIZE" for i in dlg.issues)
    assert doc.fp is not None
    dlg.close()


# ---------------------------------------------------------------------------------------------
# Вид и слои
# ---------------------------------------------------------------------------------------------

def test_view_actions(win):
    open_dip(win)
    c = win.canvas
    win.grid_actions[0.5].trigger()
    assert c.grid == 0.5 and win.grid_label.text() == "Сетка 0.5 мм"
    c.grid = 0.25  # изменение с канвы отражается в меню
    assert win.grid_actions[0.25].isChecked() and not win.grid_actions[0.5].isChecked()
    c.grid = 0.3
    assert not any(a.isChecked() for a in win.grid_actions.values())
    win.act_grid_visible.trigger()
    assert not c.grid_visible and "скрыта" in win.grid_label.text()
    assert c.snap
    win.act_snap.trigger()
    assert not c.snap and not win.act_snap.isChecked()
    ref_hidden = [t for t in win.document.fp.texts if t.hide]
    assert ref_hidden and not c.items_for(ref_hidden[0])
    win.act_show_hidden.trigger()
    assert c.show_hidden and c.items_for(ref_hidden[0])
    zoom = c.zoom
    win.act_zoom_in.trigger()
    assert c.zoom > zoom
    win.act_zoom_out.trigger()
    win.act_zoom_out.trigger()
    assert c.zoom < zoom
    win.act_fit.trigger()
    assert abs(c.zoom - zoom) < 1e-6


def test_layers_panel_controls_canvas_visibility(win):
    open_dip(win)
    panel: LayersPanel = win.layers_panel
    c = win.canvas
    assert set(PANEL_LAYERS) <= set(panel.layer_names())
    assert not panel.item_for("F.SilkS").icon().isNull()
    assert "шелкография" in panel.item_for("F.SilkS").text()

    def drawn(layer):
        return any(it.data(LAYER_ROLE) == layer for it in c.scene().items())

    assert drawn("F.SilkS")
    panel.set_checked("F.SilkS", False)
    assert not c.is_layer_visible("F.SilkS") and not drawn("F.SilkS")
    c.set_layer_visible("F.SilkS", True)  # изменение с канвы — флажок следует
    assert panel.is_checked("F.SilkS") and drawn("F.SilkS")
    panel.set_checked(PAD_NUMBERS_LAYER, False)
    assert not drawn(PAD_NUMBERS_LAYER)
    panel.hide_all()
    assert not c.scene_layers()
    assert not any(panel.is_checked(n) for n in panel.layer_names())
    panel.show_all()
    assert all(panel.is_checked(n) for n in panel.layer_names())
    # слой, использованный в корпусе, появляется в списке
    assert "User.3" not in panel.layer_names()
    doc = win.document
    doc.apply(AddItemCommand(doc, Line.new((0, 0), (1, 1), "User.3", 0.1,
                                           profile=doc.fp.profile)))
    assert "User.3" in panel.layer_names() and panel.is_checked("User.3")
    names = panel.layer_names()
    assert names.index("B.Fab") < names.index("User.3") < names.index(HOLES_LAYER)
    win.act_undo.trigger()
    assert "User.3" not in panel.layer_names()
    with pytest.raises(KeyError):
        panel.is_checked("In5.Cu")


def test_export_svg_and_png(win, tmp_path):
    open_dip(win)
    win.layers_panel.set_checked("F.SilkS", False)
    assert win.render_options()["layers"] is not None
    svg = tmp_path / "dip"
    assert win.export_svg(svg) is True  # расширение добавляется
    text = (tmp_path / "dip.svg").read_text(encoding="utf-8")
    assert text.startswith("<") and "<svg" in text
    assert 'data-layer="F.Fab"' in text and 'data-layer="F.SilkS"' not in text
    png = tmp_path / "dip.png"
    assert win.export_png(png, width=320) is True
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    win.ask_save_file = lambda title, flt, path: str(tmp_path / "x.svg") \
        if path.endswith("DIP-14_W7.62mm.svg") else None
    assert win.export_svg_interactive() is True and (tmp_path / "x.svg").is_file()


# ---------------------------------------------------------------------------------------------
# Библиотеки, недавние файлы, настройки
# ---------------------------------------------------------------------------------------------

def test_open_library_and_open_from_tree(win, tmp_path):
    lib_dir = copy_library(tmp_path)
    win.ask_directory = lambda title: str(lib_dir)
    lib = win.open_library_interactive()
    tree = win.library_tree
    assert lib is not None and lib.name == "My" and tree.children_names(lib) == \
        ["DIP-14_W7.62mm", "DIP-8_W7.62mm"]
    assert win.dock_libraries.isVisible() and win.recent_files()[0] == str(lib_dir)
    ix = tree.index_for_path(lib_dir / "DIP-8_W7.62mm.kicad_mod")
    assert tree.open_index(ix) is True  # двойной щелчок/Enter в дереве
    doc = win.document
    assert doc.path == lib_dir / "DIP-8_W7.62mm.kicad_mod" and doc.library is lib
    # переименование открытого корпуса в дереве: путь и имя документа следуют
    new_path = tree.rename_footprint(doc.path, "DIP-8_Renamed")
    assert doc.path == new_path and doc.fp.name == "DIP-8_Renamed"
    assert not doc.is_modified and win.windowTitle() == "kicadfp — DIP-8_Renamed [*]"
    assert kicadfp.load(new_path).name == "DIP-8_Renamed"
    # ошибка открытия библиотеки
    assert win.open_library(tmp_path / "нет.pretty") is None


def test_recent_files_menu_and_settings(win, settings, rec, tmp_path):
    open_dip(win, DIP8)
    open_dip(win, DIP14)
    assert win.recent_files()[:2] == [str(DIP14), str(DIP8)]
    actions = win.recent_actions()
    assert [a.data() for a in actions][:2] == [str(DIP14), str(DIP8)]
    assert actions[0].text().startswith("&1 ") and "DIP-14_W7.62mm.kicad_mod" in actions[0].text()
    assert settings.value("recent_files")[:2] == [str(DIP14), str(DIP8)]
    actions[1].trigger()
    assert win.document.path == DIP8 and win.recent_files()[0] == str(DIP8)
    # исчезнувший файл убирается из списка с сообщением
    gone = tmp_path / "gone.kicad_mod"
    shutil.copy(DIP14, gone)
    assert win.open_path(gone)
    gone.unlink()
    assert win.open_recent(str(gone)) is False
    assert str(gone) not in win.recent_files() and rec.errors
    for i in range(MAX_RECENT + 3):
        win.add_recent_file(tmp_path / f"f{i}.kicad_mod")
    assert len(win.recent_files()) == MAX_RECENT
    assert win.recent_files()[0] == str(tmp_path / f"f{MAX_RECENT + 2}.kicad_mod")
    win.act_clear_recent.trigger()
    assert win.recent_files() == [] and win.recent_actions() == []
    assert not win.act_clear_recent.isEnabled()


def test_settings_saved_on_close_and_restored(make, settings, tmp_path):
    lib_dir = copy_library(tmp_path)
    w1 = make()
    w1.grid_actions[0.5].trigger()
    w1.act_snap.trigger()
    w1.act_show_hidden.trigger()
    w1.layers_panel.set_checked("F.SilkS", False)
    w1.open_library(lib_dir)
    w1.open_path(DIP14)
    assert w1.close() is True
    assert Path(settings.fileName()).is_file()

    w2 = make()
    c = w2.canvas
    assert c.grid == 0.5 and w2.grid_actions[0.5].isChecked()
    assert not c.snap and not w2.act_snap.isChecked()
    assert c.show_hidden and w2.act_show_hidden.isChecked()
    assert not c.is_layer_visible("F.SilkS") and not w2.layers_panel.is_checked("F.SilkS")
    assert w2.library_tree.library_for(lib_dir) is not None
    assert w2.library_tree.library_for(DIP14) is not None
    assert w2.recent_files()[:2] == [str(DIP14), str(lib_dir)]
    assert w2.document.fp is None  # корпус не открывается автоматически
    w2.close()

    w3 = make(restore_settings=False)
    assert w3.canvas.grid == 1.0 and w3.canvas.snap and w3.recent_files() == []
    assert w3.library_tree.root_count() == 0


def test_default_settings_env(monkeypatch, tmp_path):
    path = tmp_path / "env.ini"
    monkeypatch.setenv(SETTINGS_ENV, str(path))
    s = default_settings()
    assert s.format() == QSettings.Format.IniFormat and Path(s.fileName()) == path
    monkeypatch.delenv(SETTINGS_ENV)
    s = default_settings()
    assert s.organizationName() == "kicadfp" and s.applicationName() == "kicadfp"


def test_open_paths_like_drop(win, tmp_path):
    lib_dir = copy_library(tmp_path)
    other = tmp_path / "other.kicad_mod"
    shutil.copy(DIP8, other)
    assert win.open_paths([lib_dir, DIP14, other]) is True
    assert win.document.path == DIP14
    assert win.library_tree.library_for(lib_dir) is not None
    assert other in win.library_tree.files


def test_drag_and_drop_files(win, qtbot, tmp_path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(DIP8))])
    copy = Qt.DropAction.CopyAction
    enter = QDragEnterEvent(QPoint(50, 50), copy, mime, LEFT, NOMOD)
    QApplication.sendEvent(win, enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(50, 50), copy, mime, LEFT, NOMOD)
    QApplication.sendEvent(win, drop)
    qtbot.waitUntil(lambda: win.document.path == DIP8)
    # не файлы (текст) — не принимаются
    text = QMimeData()
    text.setText("abc")
    enter = QDragEnterEvent(QPoint(50, 50), copy, text, LEFT, NOMOD)
    enter.ignore()
    QApplication.sendEvent(win, enter)
    assert not enter.isAccepted()


# ---------------------------------------------------------------------------------------------
# Прочее
# ---------------------------------------------------------------------------------------------

def test_about_dialog(win, rec):
    rec.handler = lambda dlg: isinstance(dlg, AboutDialog) and kicadfp.__version__ in dlg.text
    win.act_about.trigger()
    assert len(rec.dialogs) == 1


def test_params_dialog(qtbot):
    dlg = ParamsDialog("Проба", [
        ParamSpec("a", "A, мм:", default=1.5, minimum=0, maximum=10),
        ParamSpec("n", "N:", kind="int", default=3, minimum=1, maximum=9),
        ParamSpec("c", "C:", kind="choice", default="y", choices=(("x", "Икс"), ("y", "Игрек"))),
        ParamSpec("t", "T:", kind="text", default="abc"),
        ParamSpec("b", "B:", kind="bool", default=True),
    ], note="Пояснение")
    qtbot.addWidget(dlg)
    assert dlg.values() == {"a": 1.5, "n": 3, "c": "y", "t": "abc", "b": True}
    for name, bad in (("a", 11), ("a", float("nan")), ("n", 2.5), ("n", 0), ("c", "z")):
        with pytest.raises(ValueError):
            dlg.set_value(name, bad)
    dlg.set_value("t", "  xyz ")
    assert dlg.value("t") == "xyz"
    with pytest.raises(KeyError):
        dlg.value("нет")
    with pytest.raises(ValueError):
        ParamsDialog("x", [ParamSpec("a", "A"), ParamSpec("a", "B")])
    with pytest.raises(ValueError):
        ParamsDialog("x", [ParamSpec("a", "A", kind="date")])


def test_window_with_external_document(qtbot, settings):
    from kicadfp.gui.document import FootprintDocument

    doc = FootprintDocument()
    assert doc.open(DIP14)
    w = MainWindow(doc, settings=settings, restore_settings=False)
    qtbot.addWidget(w, before_close_func=_discard)
    assert w.document is doc and w.pad_table.model().rowCount() == 14
    assert w.windowTitle() == "kicadfp — DIP-14_W7.62mm [*]"
    # вопрос о сохранении подставлен окном
    doc.apply(SetAttrCommand(doc, doc.fp.pad("1"), "x", 1.0))
    w.ask_save_changes = lambda: "cancel"
    assert doc.close() is False and doc.fp is not None


def test_main_shows_window_and_opens_path(qapp, monkeypatch, tmp_path):
    from kicadfp.gui import mainwindow as mw

    created: list[MainWindow] = []

    class RecordingWindow(MainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)  # ссылка не даёт удалить окно после выхода из main()

    monkeypatch.setattr(mw, "MainWindow", RecordingWindow)
    monkeypatch.setenv(SETTINGS_ENV, str(tmp_path / "main.ini"))
    monkeypatch.setattr(QApplication, "exec", lambda *a, **k: 0)
    assert gui_main([str(DIP14), str(DIP_LIB)]) == 0
    assert len(created) == 1
    w = created[0]
    try:
        assert w.isVisible() and w.document.path == DIP14
        assert w.library_tree.library_for(DIP_LIB) is not None
        assert w.settings.fileName() == str(tmp_path / "main.ini")
    finally:
        _discard(w)
        w.close()
        w.deleteLater()


def test_screenshot_script(tmp_path):
    from . import gui_screenshots

    out = gui_screenshots.take_main_window_screenshot(tmp_path / "shot.png", (1000, 700))
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 10_000


def _answer_modal(choose, attempts: int = 200) -> None:
    """Ответить на ближайший модальный диалог (``choose(диалог)`` нажимает кнопку); если
    он не появился за ``attempts`` попыток — закрыть все видимые модальные окна."""

    def tick(left: int = attempts) -> None:
        box = QApplication.activeModalWidget()
        if box is not None:
            choose(box)
        elif left > 0:
            QTimer.singleShot(10, lambda: tick(left - 1))
        else:
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QDialog) and w.isVisible():
                    w.reject()

    QTimer.singleShot(0, tick)


def test_default_question_boxes(qtbot, settings):
    w = MainWindow(settings=settings, restore_settings=False)
    qtbot.addWidget(w, before_close_func=_discard)
    w.resize(1440, 900)
    w.show()
    assert w.open_path(DIP14)
    buttons: list[list[str]] = []

    def press(which):
        def choose(box):
            assert isinstance(box, QMessageBox)
            buttons.append(sorted(b.text() for b in box.buttons()))
            box.button(which).click()
        return choose

    sb = QMessageBox.StandardButton
    for which, answer in ((sb.Discard, "discard"), (sb.Cancel, "cancel"), (sb.Save, "save")):
        _answer_modal(press(which))
        assert w.ask_save_changes() == answer
    assert buttons[0] == sorted(["Сохранить", "Не сохранять", "Отмена"])
    # сообщение об ошибке и модальный диалог по умолчанию
    _answer_modal(lambda box: box.accept())
    w.show_error("Ошибка", "строка 1, позиция 2: проба")
    _answer_modal(lambda box: box.reject())
    assert w.exec_dialog(AboutDialog(w)) is False
    _answer_modal(lambda box: box.accept())
    assert w.exec_dialog(AboutDialog(w)) is True
