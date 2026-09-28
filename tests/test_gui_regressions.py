"""Регрессионные тесты по замечаниям ревью GUI: незавершённый ввод перед записью и
закрытием, повторное открытие того же файла с ответом «Сохранить», переименование
открытого корпуса в дереве библиотек, «пустые» правки слоёв в таблице и диалога
свойств элемента."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kicadfp import io  # noqa: E402
from kicadfp.gui.commands import SetAttrCommand  # noqa: E402
from kicadfp.gui.dialogs import ItemPropertiesDialog  # noqa: E402
from kicadfp.gui.document import FootprintDocument  # noqa: E402
from kicadfp.gui.mainwindow import MainWindow  # noqa: E402
from kicadfp.gui.pad_table import COL_LAYERS, COL_X, PadTable  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

DIP8 = FIXTURES / "kicad8" / "Package_DIP.pretty" / "DIP-8_W7.62mm.kicad_mod"
TSOP = FIXTURES / "kicad6" / "Package_SO.pretty" / "TSOP-I-24_16.4x6mm_P0.5mm.kicad_mod"
QFN9 = FIXTURES / "special" / "kicad9" / \
    "Package_DFN_QFN.pretty__Analog_QFN-28-36-2EP_5x6mm_P0.5mm.kicad_mod"
FUSE5 = FIXTURES / "special" / "kicad5" / "Fuse.pretty__Fuse_Blade_Mini_directSolder.kicad_mod"
CTRL = Qt.KeyboardModifier.ControlModifier


def _unexpected(*args):
    raise AssertionError(f"неожиданный вопрос пользователю: {args!r}")


@pytest.fixture
def win(qtbot, tmp_path):
    w = MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                   restore_settings=False)
    qtbot.addWidget(w, before_close_func=lambda w: setattr(w.document, "confirm_discard", True))
    w.show_error = _unexpected
    w.ask_save_changes = _unexpected
    w.library_tree.show_errors = False
    w.resize(1400, 900)
    w.show()
    assert QTest.qWaitForWindowExposed(w)
    w.activateWindow()
    QTest.qWaitForWindowActive(w)
    return w


def _lib_copy(tmp_path: Path, src: Path = DIP8, name: str | None = None) -> Path:
    lib = tmp_path / "My.pretty"
    lib.mkdir(exist_ok=True)
    p = lib / (name or src.name)
    shutil.copyfile(src, p)
    return p


def _type_into(widget, text: str) -> None:
    widget.setFocus()
    QApplication.processEvents()
    widget.selectAll()
    QTest.keyClicks(widget, text)


def _open_cell_editor(win: MainWindow, row: int, col: int):
    t = win.pad_table
    win.dock_pads.show()
    win.dock_pads.raise_()
    idx = t.pad_model().index(row, col)
    t.setFocus()
    t.setCurrentIndex(idx)
    t.edit(idx)
    QApplication.processEvents()
    ed = t.open_editor()
    assert ed is not None
    return ed


# --- незавершённый ввод -----------------------------------------------------------------------

def test_ctrl_s_commits_typed_props_field(win, tmp_path):
    p = _lib_copy(tmp_path)
    assert win.open_path(p)
    win.dock_properties.show()
    ed = win.props_panel.descr_edit
    _type_into(ed, "New descr")
    QTest.keyClick(ed, Qt.Key.Key_S, CTRL)  # Ctrl+S, фокус остаётся в поле
    QApplication.processEvents()
    assert io.load(p).descr == "New descr"
    assert win.document.fp.descr == "New descr" and not win.document.is_modified
    assert win.document.undo_stack.count() == 1  # правка — отдельный шаг отмены


def test_close_asks_when_props_field_has_typed_text(win, tmp_path):
    p = _lib_copy(tmp_path)
    assert win.open_path(p)
    _type_into(win.props_panel.descr_edit, "Lost text")
    asked = []
    win.ask_save_changes = lambda: asked.append(1) or "cancel"
    assert win.close() is False
    assert asked and win.isVisible()
    assert win.document.fp.descr == "Lost text" and win.document.is_modified


def test_ctrl_s_commits_open_table_cell_editor(win, tmp_path):
    p = _lib_copy(tmp_path)
    assert win.open_path(p)
    ed = _open_cell_editor(win, 0, COL_X)
    ed.selectAll()
    QTest.keyClicks(ed, "5")
    QTest.keyClick(ed, Qt.Key.Key_S, CTRL)
    QApplication.processEvents()
    assert win.document.fp.pads[0].x == 5.0
    assert io.load(p).pads[0].x == 5.0 and not win.document.is_modified
    assert win.pad_table.open_editor() is None


def test_close_asks_when_table_cell_editor_is_open(win, tmp_path):
    p = _lib_copy(tmp_path)
    assert win.open_path(p)
    ed = _open_cell_editor(win, 0, COL_X)
    ed.selectAll()
    QTest.keyClicks(ed, "9.99")
    asked = []
    win.ask_save_changes = lambda: asked.append(1) or "save"
    assert win.close() is True
    assert asked and io.load(p).pads[0].x == 9.99


def test_open_other_file_commits_typed_text_before_question(win, tmp_path):
    p = _lib_copy(tmp_path)
    other = _lib_copy(tmp_path, FIXTURES / "kicad8" / "Package_DIP.pretty" /
                      "DIP-14_W7.62mm.kicad_mod")
    assert win.open_path(p)
    _type_into(win.props_panel.tags_edit, "typed tags")
    win.ask_save_changes = lambda: "save"
    assert win.open_file(other)
    assert io.load(p).tags == "typed tags"


def test_commit_pending_does_not_touch_rounded_numeric_fields(qtbot):
    """Поле панели с округлённым показом (больше 6 знаков) без ввода не переписывается."""
    from kicadfp.gui.props_panel import PropertiesPanel
    doc = FootprintDocument()
    doc.open(DIP8)
    doc.apply(SetAttrCommand(doc, doc.fp, "solder_paste_ratio", -0.1234567891))
    ratio = doc.fp.solder_paste_ratio
    panel = PropertiesPanel(doc)
    qtbot.addWidget(panel)
    n = doc.undo_stack.count()
    assert panel.commit_pending()
    assert doc.undo_stack.count() == n and doc.fp.solder_paste_ratio == ratio


# --- повторное открытие того же файла с «Сохранить» -----------------------------------------

def test_reopen_same_file_with_save_keeps_edit(win, tmp_path):
    p = _lib_copy(tmp_path)
    assert win.open_file(p)
    doc = win.document
    doc.apply(SetAttrCommand(doc, doc.fp.pads[0], "x", 7.5))
    win.ask_save_changes = lambda: "save"
    assert win.open_file(p)
    assert doc.fp.pads[0].x == 7.5 and not doc.is_modified
    assert io.load(p).pads[0].x == 7.5
    # следующая правка и запись не теряют сохранённое значение
    doc.apply(SetAttrCommand(doc, doc.fp.pads[1], "y", 1.0))
    assert win.save()
    loaded = io.load(p)
    assert loaded.pads[0].x == 7.5 and loaded.pads[1].y == 1.0


def test_document_open_rereads_after_confirmation(tmp_path):
    p = _lib_copy(tmp_path)
    doc = FootprintDocument()
    doc.open(p)
    doc.apply(SetAttrCommand(doc, doc.fp, "descr", "saved on confirm"))
    doc.confirm_discard = lambda: doc.save()
    assert doc.open(p)
    assert doc.fp.descr == "saved on confirm" and not doc.is_modified


# --- переименование открытого корпуса -----------------------------------------------------------

def test_rename_open_footprint_updates_value_like_library(win, tmp_path):
    p = _lib_copy(tmp_path)
    lib = win.open_library(p.parent)
    assert lib is not None
    assert win.open_file(p)
    doc = win.document
    assert doc.fp.value.text == "DIP-8_W7.62mm"
    new = win.library_tree.rename_footprint(p, "MyDIP8")
    assert doc.path == new and doc.fp.name == "MyDIP8" and doc.fp.value.text == "MyDIP8"
    assert not doc.is_modified
    before = new.read_text(encoding="utf-8")
    assert win.save()
    assert new.read_text(encoding="utf-8") == before  # запись не возвращает старый Value
    doc.undo()  # отмена переименования — одним шагом, имя и Value вместе
    assert doc.fp.name == "DIP-8_W7.62mm" and doc.fp.value.text == "DIP-8_W7.62mm"


# --- таблица площадок: повторный ввод слоёв ------------------------------------------------------

def test_layers_cell_same_set_is_noop(qtbot, tmp_path):
    p = tmp_path / TSOP.name
    shutil.copyfile(TSOP, p)
    doc = FootprintDocument()
    doc.open(p)
    t = PadTable(doc)
    qtbot.addWidget(t)
    m = t.pad_model()
    idx = m.index(0, COL_LAYERS)
    text = m.data(idx)
    assert text == "F.Cu, F.Mask, F.Paste"  # порядок файла отличается от пресета
    assert m.setData(idx, text)
    assert m.setData(idx, "F.Paste F.Cu F.Mask")  # тот же набор в другом порядке
    assert doc.undo_stack.count() == 0 and not doc.is_modified
    # реальное изменение набора по-прежнему применяется (в порядке пресета)
    assert m.setData(idx, "F.Cu, F.Mask")
    assert set(doc.fp.pads[0].layers) == {"F.Cu", "F.Mask"} and doc.undo_stack.count() == 1


# --- диалог свойств элемента: нетронутые округлённые поля ---------------------------------------

@pytest.mark.parametrize("path", [QFN9, FUSE5], ids=["qfn-rratio", "fuse-model-inch"])
def test_item_dialog_untouched_fields_are_not_changes(qtbot, tmp_path, path):
    p = tmp_path / path.name
    shutil.copyfile(path, p)
    doc = FootprintDocument()
    doc.open(p)
    orig = p.read_text(encoding="utf-8")
    fp = doc.fp
    for it in fp.pads + fp.graphics + fp.texts + fp.models:
        dlg = ItemPropertiesDialog(doc, it)
        qtbot.addWidget(dlg)
        assert dlg.changes() == {}, it
        dlg.accept()
    assert doc.undo_stack.count() == 0 and not doc.is_modified
    doc.save()
    assert p.read_text(encoding="utf-8") == orig


def test_item_dialog_edit_one_field_keeps_precise_ratio(qtbot, tmp_path):
    p = tmp_path / QFN9.name
    shutil.copyfile(QFN9, p)
    doc = FootprintDocument()
    doc.open(p)
    pad = next(q for q in doc.fp.pads
               if q.roundrect_rratio is not None
               and round(q.roundrect_rratio, 6) != q.roundrect_rratio)
    ratio = pad.roundrect_rratio
    dlg = ItemPropertiesDialog(doc, pad)
    qtbot.addWidget(dlg)
    dlg.set_field("number", "99")
    assert dlg.changes() == {"number": "99"}
    dlg.accept()
    assert pad.number == "99" and pad.roundrect_rratio == ratio
    # правка самого поля по-прежнему применяется
    dlg2 = ItemPropertiesDialog(doc, pad)
    qtbot.addWidget(dlg2)
    dlg2.set_field("roundrect_rratio", "0.2")
    assert dlg2.changes() == {"roundrect_rratio": 0.2}
