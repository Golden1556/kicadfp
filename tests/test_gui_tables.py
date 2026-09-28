"""Таблицы площадок, графики/текстов и панель свойств корпуса (pytest-qt, offscreen)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtWidgets import QComboBox  # noqa: E402

from kicadfp import generators  # noqa: E402
from kicadfp.gui.document import FootprintDocument  # noqa: E402
from kicadfp.gui.items_table import (COL_HIDDEN, COL_KIND, COL_LAYER, COL_TEXT,  # noqa: E402
                                     COL_WIDTH, COL_X1, COL_X2, COL_Y1, COL_Y2, ITEM_COLUMNS,
                                     ItemsTable, ItemsTableModel)
from kicadfp.gui.pad_table import (COL_ANGLE, COL_DRILL, COL_LAYERS, COL_NUMBER,  # noqa: E402
                                   COL_SHAPE, COL_SIZE_X, COL_SIZE_Y, COL_TYPE, COL_X, COL_Y,
                                   LAYER_PRESET_TEXTS, PAD_COLUMNS, ComboBoxDelegate, PadTable,
                                   PadTableModel, parse_layers, parse_number, parse_pair)
from kicadfp.gui.props_panel import PropertiesPanel  # noqa: E402
from kicadfp.model import Arc, Circle, Line, Pad, Poly  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

DIP14 = FIXTURES / "kicad8" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
ED = Qt.ItemDataRole.EditRole
DISP = Qt.ItemDataRole.DisplayRole
CHECK = Qt.ItemDataRole.CheckStateRole


@pytest.fixture
def doc(qtbot) -> FootprintDocument:
    d = FootprintDocument()
    yield d
    d.confirm_discard = True
    d.close()


@pytest.fixture
def dip(doc) -> FootprintDocument:
    assert doc.open(DIP14) is True
    return doc


@pytest.fixture
def pads(dip, qtbot) -> PadTable:
    t = PadTable(dip)
    qtbot.addWidget(t)
    return t


@pytest.fixture
def items(dip, qtbot) -> ItemsTable:
    t = ItemsTable(dip)
    qtbot.addWidget(t)
    return t


def cell(model, row: int, col: int, role=DISP):
    return model.data(model.index(row, col), role)


# ---------------------------------------------------------------------------------------------
# Разбор ввода
# ---------------------------------------------------------------------------------------------

def test_parse_helpers():
    assert parse_number("1,27") == 1.27 and parse_number(" -2.5 ") == -2.5
    assert parse_number("−1") == -1.0 and parse_number(3) == 3.0
    for bad in ("", "abc", "nan", "inf", "1..2", True):
        with pytest.raises(ValueError):
            parse_number(bad)
    with pytest.raises(ValueError):
        parse_number("0", minimum=0.0, strict_minimum=True)
    assert parse_pair("0.8", "d") == 0.8
    assert parse_pair("1.2 x 0.8", "d") == (1.2, 0.8)
    assert parse_pair("1.2х0.8", "d") == (1.2, 0.8)  # кириллическая «х»
    assert parse_pair("1.2*0,8", "d") == (1.2, 0.8)
    for bad in ("1 x 2 x 3", "0", "-1", "a x 1"):
        with pytest.raises(ValueError):
            parse_pair(bad, "d")
    assert parse_layers("*.Cu, *.Mask") == ["*.Cu", "*.Mask"]
    assert parse_layers("F.Cu F.Mask;F.Cu") == ["F.Cu", "F.Mask"]
    for bad in ("", "F.Cu, X.Bad"):
        with pytest.raises(ValueError):
            parse_layers(bad)


# ---------------------------------------------------------------------------------------------
# Таблица площадок
# ---------------------------------------------------------------------------------------------

def test_pad_model_shape_and_headers(pads):
    m = pads.pad_model()
    assert m.rowCount() == 14 and m.columnCount() == 10 == len(PAD_COLUMNS)
    assert [m.headerData(c, Qt.Orientation.Horizontal) for c in range(10)] == [
        "№", "Тип", "Форма", "X", "Y", "Поворот", "Размер X", "Размер Y", "Отверстие", "Слои"]
    assert not pads.isSortingEnabled()


def test_pad_model_data_pad1(pads):
    m = pads.pad_model()
    row = [cell(m, 0, c) for c in range(10)]
    assert row == ["1", "thru_hole", "rect", "0", "0", "0", "1.6", "1.6", "0.8", "*.Cu, *.Mask"]
    assert cell(m, 1, COL_Y) == "2.54" and cell(m, 1, COL_SHAPE) == "oval"
    assert cell(m, 0, COL_X, ED) == "0"
    assert isinstance(cell(m, 0, 0, Qt.ItemDataRole.UserRole), Pad)
    assert m.flags(m.index(0, COL_X)) & Qt.ItemFlag.ItemIsEditable


def test_pad_set_x_and_undo(dip, pads, qtbot):
    m = pads.pad_model()
    pad = dip.fp.pad("3")
    row = m.row_of(pad)
    assert row == 2
    orig = dip.fp.dumps()
    with qtbot.waitSignal(dip.changed):
        assert m.setData(m.index(row, COL_X), "1.5", ED) is True
    assert pad.x == 1.5 and cell(m, row, COL_X) == "1.5"
    assert dip.undo_stack.count() == 1 and dip.is_modified
    assert dip.undo_stack.undoText() == "изменение X площадки 3"
    dip.undo()
    assert pad.x == 0 and cell(m, row, COL_X) == "0"
    assert dip.fp.dumps() == orig
    dip.redo()
    assert cell(m, row, COL_X) == "1.5"


def test_pad_invalid_input_rejected(dip, pads, qtbot):
    m = pads.pad_model()
    orig = dip.fp.dumps()
    errors: list[str] = []
    m.error.connect(errors.append)
    for col, bad in ((COL_X, "abc"), (COL_Y, ""), (COL_ANGLE, "nan"), (COL_SIZE_X, "0"),
                     (COL_SIZE_Y, "-1"), (COL_DRILL, "1 x"), (COL_DRILL, "x"),
                     (COL_LAYERS, "F.Cu, Нет.Слоя"), (COL_LAYERS, ""),
                     (COL_TYPE, "bogus"), (COL_SHAPE, "hexagon")):
        assert m.setData(m.index(0, col), bad, ED) is False, (col, bad)
    assert len(errors) == 11 and all(errors)
    assert dip.fp.dumps() == orig and dip.undo_stack.count() == 0
    # то же значение — не ошибка и не шаг отмены (исходная запись числа сохраняется)
    assert m.setData(m.index(0, COL_X), "0", ED) is True
    assert m.setData(m.index(0, COL_DRILL), "0.80", ED) is True
    assert dip.undo_stack.count() == 0


def test_pad_other_numeric_columns(dip, pads):
    m = pads.pad_model()
    pad = dip.fp.pad("1")
    assert m.setData(m.index(0, COL_Y), "-1,27", ED)
    assert m.setData(m.index(0, COL_ANGLE), 90, ED)
    assert m.setData(m.index(0, COL_SIZE_X), "2", ED)
    assert m.setData(m.index(0, COL_SIZE_Y), "1.8", ED)
    assert (pad.y, pad.angle, pad.size_x, pad.size_y) == (-1.27, 90, 2, 1.8)
    assert m.setData(m.index(0, COL_NUMBER), "A1", ED)
    assert pad.number == "A1" and cell(m, 0, COL_NUMBER) == "A1"
    assert dip.undo_stack.count() == 5
    for _ in range(5):
        dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_pad_drill_column(dip, pads):
    m = pads.pad_model()
    pad = dip.fp.pad("1")
    assert m.setData(m.index(0, COL_DRILL), "1.2 x 0.9", ED)
    assert pad.drill.oval and pad.drill.size == (1.2, 0.9)
    assert cell(m, 0, COL_DRILL) == "1.2 x 0.9"
    assert m.setData(m.index(0, COL_DRILL), "1", ED)
    assert not pad.drill.oval and pad.drill.diameter == 1
    assert m.setData(m.index(0, COL_DRILL), "", ED)
    assert pad.drill is None and cell(m, 0, COL_DRILL) == ""
    dip.undo()
    assert pad.drill.diameter == 1


def test_pad_type_and_shape_change(dip, pads):
    m = pads.pad_model()
    pad = dip.fp.pad("2")
    assert m.setData(m.index(1, COL_SHAPE), "roundrect", ED)
    assert pad.shape == "roundrect" and cell(m, 1, COL_SHAPE) == "roundrect"
    assert m.setData(m.index(1, COL_TYPE), "smd", ED)
    assert pad.type == "smd" and pad.drill is None
    assert set(pad.layers) == {"F.Cu", "F.Paste", "F.Mask"}  # пресет нового типа
    assert dip.undo_stack.count() == 2
    assert dip.undo_stack.undoText() == "изменение типа площадки 2"
    assert m.setData(m.index(1, COL_TYPE), "thru_hole", ED)
    assert pad.type == "thru_hole" and pad.drill.diameter == 0.8
    assert pad.layers == ["*.Cu", "*.Mask"]
    for _ in range(3):
        dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_pad_layers_column(dip, pads):
    m = pads.pad_model()
    pad = dip.fp.pad("1")
    assert m.setData(m.index(0, COL_LAYERS), "F.Cu, F.Mask, B.SilkS", ED)
    assert pad.layers == ["F.Cu", "F.Mask", "B.SilkS"]
    assert cell(m, 0, COL_LAYERS) == "F.Cu, F.Mask, B.SilkS"
    # пресет: порядок как у writer'а KiCad
    assert m.setData(m.index(0, COL_LAYERS), "F.Mask, F.Paste, F.Cu", ED)
    assert set(pad.layers) == {"F.Cu", "F.Paste", "F.Mask"} and pad.layers[0] == "F.Cu"
    assert "*.Cu, *.Mask" in LAYER_PRESET_TEXTS


def test_combo_delegate_commits_through_model(dip, pads, qtbot):
    m = pads.pad_model()
    delegate = pads.itemDelegateForColumn(COL_SHAPE)
    assert isinstance(delegate, ComboBoxDelegate)
    idx = m.index(0, COL_SHAPE)
    editor = delegate.createEditor(pads.viewport(), None, idx)
    assert isinstance(editor, QComboBox) and not editor.isEditable()
    delegate.setEditorData(editor, idx)
    assert editor.currentText() == "rect"
    editor.setCurrentText("circle")
    delegate.setModelData(editor, m, idx)
    assert dip.fp.pad("1").shape == "circle"
    layers_delegate = pads.itemDelegateForColumn(COL_LAYERS)
    ed2 = layers_delegate.createEditor(pads.viewport(), None, m.index(0, COL_LAYERS))
    assert ed2.isEditable() and ed2.count() == len(LAYER_PRESET_TEXTS)
    types = pads.itemDelegateForColumn(COL_TYPE).items()
    assert types == ["thru_hole", "smd", "connect", "np_thru_hole"]
    editor.deleteLater()
    ed2.deleteLater()


def test_pad_selection_sync(dip, pads, qtbot):
    m = pads.pad_model()
    with qtbot.waitSignal(dip.selection_changed):
        pads.selectRow(4)
    assert dip.selected == dip.fp.pad("5")
    dip.select(dip.fp.pad("9"))
    assert pads.selected_rows() == [8]
    dip.select(dip.fp.graphics[0])  # не площадка — выделение в таблице снимается
    assert pads.selected_rows() == []
    dip.select(dip.fp.pad("2"))
    assert pads.selected_rows() == [1]
    pads.clearSelection()
    assert dip.selected is None
    # после сброса модели (удаление площадки) выделение восстанавливается по документу
    from kicadfp.gui.commands import RemoveItemCommand
    dip.select(dip.fp.pad("14"))
    assert pads.selected_rows() == [13]
    dip.apply(RemoveItemCommand(dip, dip.fp.pad("1")))
    assert m.rowCount() == 13 and pads.selected_rows() == [12]
    assert dip.selected == dip.fp.pad("14")
    dip.undo()
    assert m.rowCount() == 14 and pads.selected_rows() == [13]
    pads.selectionModel().select(m.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                                 | QItemSelectionModel.SelectionFlag.Rows)
    assert dip.selected == dip.fp.pad("1")


def test_pad_table_refreshes_on_changes(dip, pads):
    m = pads.pad_model()
    from kicadfp.gui.commands import SetAttrCommand
    dip.apply(SetAttrCommand(dip, dip.fp.pad("7"), "y", 20.0))
    assert cell(m, 6, COL_Y) == "20"
    dip.undo()
    assert cell(m, 6, COL_Y) == "15.24"
    dip.new_footprint("empty")
    assert m.rowCount() == 0
    assert dip.open(DIP14) and m.rowCount() == 14


def test_pad_context_actions(dip, pads, qtbot):
    m = pads.pad_model()
    menu = pads.context_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Добавить площадку", "Дублировать", "Удалить", "Групповые операции…"]
    assert not pads.act_remove.isEnabled()  # ничего не выделено
    pads.selectRow(13)
    new = pads.add_pad()
    assert m.rowCount() == 15 and new.number == "15"
    assert (new.x, new.y) == (7.62, 0 + 2.54) and dip.selected == new
    assert pads.selected_rows() == [14]
    dip.undo()
    assert m.rowCount() == 14
    pads.selectRow(0)
    pads.selectionModel().select(m.index(1, 0), QItemSelectionModel.SelectionFlag.Select
                                 | QItemSelectionModel.SelectionFlag.Rows)
    assert [p.number for p in pads.selected_pads()] == ["1", "2"]
    with qtbot.waitSignal(pads.batch_requested) as blocker:
        pads.act_batch.trigger()
    assert [p.number for p in blocker.args[0]] == ["1", "2"]
    added = pads.duplicate_selected()
    assert [p.number for p in added] == ["15", "16"] and m.rowCount() == 16
    assert added[0].x == 2.54 and added[0].y == 0
    assert dip.undo_stack.undoText() == "дублирование площадок (2)"
    dip.undo()
    pads.selectRow(0)
    pads.selectionModel().select(m.index(1, 0), QItemSelectionModel.SelectionFlag.Select
                                 | QItemSelectionModel.SelectionFlag.Rows)
    assert pads.remove_selected() == 2 and m.rowCount() == 12
    dip.undo()
    assert m.rowCount() == 14
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_add_pad_in_empty_footprint(doc, qtbot):
    doc.new_footprint("X")
    t = PadTable(doc)
    qtbot.addWidget(t)
    pad = t.add_pad()
    assert pad.number == "1" and pad.type == "thru_hole" and pad.drill.diameter == 0.8
    assert t.pad_model().rowCount() == 1


def test_undo_depth_via_table(dip, pads):
    m = pads.pad_model()
    for i in range(120):
        assert m.setData(m.index(0, COL_X), str(0.01 * (i + 1)), ED)
    assert dip.undo_stack.count() == 120
    for _ in range(120):
        dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


# ---------------------------------------------------------------------------------------------
# Таблица графики и текстов
# ---------------------------------------------------------------------------------------------

def test_items_model_rows(dip, items):
    m = items.items_model()
    fp = dip.fp
    assert m.rowCount() == len(fp.graphics) + len(fp.texts) == 21
    assert m.columnCount() == len(ITEM_COLUMNS) == 9
    kinds = [cell(m, r, COL_KIND) for r in range(m.rowCount())]
    assert kinds[0] == "line" and "arc" in kinds
    assert kinds[15:] == ["text:reference", "text:value", "text:user", "text:user",
                          "text:user", "text:user"]
    line = fp.graphics[0]
    assert isinstance(line, Line)
    r = [cell(m, 0, c) for c in (COL_LAYER, COL_WIDTH, COL_X1, COL_Y1, COL_X2, COL_Y2)]
    from kicadfp.gui.pad_table import format_mm
    assert r == [line.layer, format_mm(line.width), format_mm(line.start[0]),
                 format_mm(line.start[1]), format_mm(line.end[0]), format_mm(line.end[1])]
    ref = m.row_of(fp.reference)
    assert ref == 15
    assert cell(m, ref, COL_TEXT) == "REF**" and cell(m, ref, COL_LAYER) == "F.SilkS"
    assert cell(m, ref, COL_WIDTH) == "1" and cell(m, ref, COL_X1) == "3.81"
    assert cell(m, ref, COL_HIDDEN, CHECK) == Qt.CheckState.Unchecked
    assert cell(m, 17, COL_HIDDEN, CHECK) == Qt.CheckState.Checked  # поле Footprint
    assert cell(m, 0, COL_HIDDEN, CHECK) is None
    assert not m.flags(m.index(0, COL_TEXT)) & Qt.ItemFlag.ItemIsEditable
    assert m.flags(m.index(ref, COL_TEXT)) & Qt.ItemFlag.ItemIsEditable
    assert m.flags(m.index(ref, COL_HIDDEN)) & Qt.ItemFlag.ItemIsUserCheckable


def test_items_change_graphic_layer(dip, items):
    m = items.items_model()
    line = dip.fp.graphics[0]
    old = line.layer
    assert m.setData(m.index(0, COL_LAYER), "B.SilkS", ED)
    assert line.layer == "B.SilkS" and cell(m, 0, COL_LAYER) == "B.SilkS"
    assert m.setData(m.index(0, COL_LAYER), "Нет.Слоя", ED) is False
    assert m.setData(m.index(0, COL_LAYER), "*.Cu", ED) is False  # групповое — не для графики
    dip.undo()
    assert line.layer == old
    assert isinstance(items.itemDelegateForColumn(COL_LAYER), ComboBoxDelegate)


def test_items_change_text_layer_text_and_hide(dip, items):
    m = items.items_model()
    ref = dip.fp.reference
    row = m.row_of(ref)
    assert m.setData(m.index(row, COL_LAYER), "F.Fab", ED)
    assert ref.layer == "F.Fab" and cell(m, row, COL_LAYER) == "F.Fab"
    assert m.setData(m.index(row, COL_TEXT), "U**", ED)
    assert ref.text == "U**"
    assert m.setData(m.index(row, COL_HIDDEN), Qt.CheckState.Checked, CHECK)
    assert ref.hide and cell(m, row, COL_HIDDEN, CHECK) == Qt.CheckState.Checked
    assert m.setData(m.index(row, COL_HIDDEN), Qt.CheckState.Unchecked.value, CHECK)
    assert not ref.hide
    assert m.setData(m.index(row, COL_WIDTH), "1.2 x 1", ED)
    assert (ref.font_size_x, ref.font_size_y) == (1.2, 1.0)
    assert cell(m, row, COL_WIDTH) == "1.2 x 1"
    assert m.setData(m.index(row, COL_WIDTH), "0", ED) is False
    assert m.setData(m.index(row, COL_X1), "1", ED) and m.setData(m.index(row, COL_Y1), "2", ED)
    assert (ref.x, ref.y) == (1, 2)
    assert m.setData(m.index(row, COL_X2), "1", ED) is False  # у текста X2 нет
    assert dip.undo_stack.count() == 7
    for _ in range(7):
        dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_items_hide_user_text_reorders(dip, items):
    """Скрытие fp_text в формате KiCad 8 превращает его в поле: строки перестраиваются."""
    m = items.items_model()
    user = next(t for t in dip.fp.texts if t.name is None)
    row = m.row_of(user)
    assert row == 20
    assert m.setData(m.index(row, COL_HIDDEN), Qt.CheckState.Checked, CHECK)
    assert m.rowCount() == 21 and m.row_of(user) >= 0
    assert cell(m, m.row_of(user), COL_HIDDEN, CHECK) == Qt.CheckState.Checked
    dip.undo()
    assert m.row_of(user) == 20
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_items_graphic_geometry_columns(doc, qtbot):
    fp = generators.GENERATORS["dip"](pins=8) if "dip" in generators.GENERATORS else None
    assert fp is not None
    doc.open_footprint(fp)
    line = doc.fp.new_line((0, 0), (1, 0), "F.SilkS", 0.12)
    circ = doc.fp.new_circle((5, 5), 1.0, "F.Fab", 0.1)
    arc = doc.fp.new_arc((0, 1), (1, 2), (2, 1), "F.Fab", 0.1)
    poly = doc.fp.new_poly([(0, 0), (1, 0), (1, 1)], "F.Fab", 0.1)
    doc.undo_stack.clear()
    t = ItemsTable(doc)
    qtbot.addWidget(t)
    m = t.items_model()
    m._on_document_changed()  # элементы добавлены в обход команд (подготовка теста)
    r_line, r_circ, r_arc, r_poly = (m.row_of(x) for x in (line, circ, arc, poly))
    assert min(r_line, r_circ, r_arc, r_poly) >= 0
    assert isinstance(m.item_at(r_circ), Circle) and isinstance(m.item_at(r_arc), Arc)
    assert m.setData(m.index(r_line, COL_X2), "3", ED) and line.end == (3, 0)
    assert m.setData(m.index(r_line, COL_WIDTH), "0.2", ED) and line.width == 0.2
    assert m.setData(m.index(r_line, COL_WIDTH), "-1", ED) is False
    # окружность: центр сдвигает окружность целиком, X2 — радиус
    assert [cell(m, r_circ, c) for c in (COL_X1, COL_Y1, COL_X2, COL_Y2)] == ["5", "5", "1", ""]
    assert m.setData(m.index(r_circ, COL_X1), "6", ED)
    assert circ.center == (6, 5) and circ.radius == pytest.approx(1.0)
    assert m.setData(m.index(r_circ, COL_X2), "2", ED) and circ.radius == pytest.approx(2.0)
    assert m.setData(m.index(r_circ, COL_X2), "0", ED) is False
    assert not m.flags(m.index(r_circ, COL_Y2)) & Qt.ItemFlag.ItemIsEditable
    # дуга: начало и конец
    assert m.setData(m.index(r_arc, COL_Y2), "1.5", ED) and arc.end == (2, 1.5)
    # многоугольник: первая точка и число точек — только чтение
    assert isinstance(m.item_at(r_poly), Poly)
    assert [cell(m, r_poly, c) for c in (COL_X1, COL_Y1, COL_X2)] == ["0", "0", "3"]
    for c in (COL_X1, COL_Y1, COL_X2, COL_Y2):
        assert not m.flags(m.index(r_poly, c)) & Qt.ItemFlag.ItemIsEditable
    assert m.setData(m.index(r_poly, COL_X1), "5", ED) is False
    assert doc.undo_stack.count() == 5


def test_items_selection_and_remove(dip, items, qtbot):
    m = items.items_model()
    items.selectRow(3)
    assert dip.selected == dip.fp.graphics[3]
    dip.select(dip.fp.value)
    assert items.selected_rows() == [16]
    assert items.context_menu().actions()[0].isEnabled() is False  # Value не удаляется
    items.selectRow(0)
    assert items.remove_selected() == 1 and m.rowCount() == 20
    assert dip.selected is None
    dip.undo()
    assert m.rowCount() == 21


# ---------------------------------------------------------------------------------------------
# Панель свойств
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def panel(dip, qtbot) -> PropertiesPanel:
    p = PropertiesPanel(dip)
    qtbot.addWidget(p)
    return p


def test_panel_shows_values(dip, panel):
    assert panel.isEnabled()
    assert panel.name_edit.text() == "DIP-14_W7.62mm"
    assert panel.layer_combo.currentText() == "F.Cu"
    assert panel.descr_edit.text().startswith("14-lead")
    assert panel.tags_edit.text().startswith("THT DIP")
    assert panel.attr_checks["through_hole"].isChecked()
    assert not panel.attr_checks["smd"].isChecked()
    assert panel.numeric_edits["clearance"].text() == ""
    assert panel.zone_combo.currentData() is None
    assert panel.version_edit.text() == "20240108" and panel.version_edit.isReadOnly()
    assert panel.uuid_edit.isReadOnly()


def test_panel_descr_via_editing_finished(dip, panel, qtbot):
    panel.descr_edit.setText("новое описание")
    with qtbot.waitSignal(dip.changed):
        panel.descr_edit.editingFinished.emit()
    assert dip.fp.descr == "новое описание"
    assert dip.undo_stack.undoText() == "изменение описания корпуса DIP-14_W7.62mm"
    dip.undo()
    assert panel.descr_edit.text().startswith("14-lead")
    # повторный editingFinished без изменений — не шаг отмены
    panel.descr_edit.editingFinished.emit()
    assert dip.undo_stack.count() == 1 and dip.undo_stack.index() == 0


def test_panel_set_field_and_attrs(dip, panel):
    assert panel.set_field("tags", "a b c") and dip.fp.tags == "a b c"
    assert panel.set_field("name", "NEW") and dip.fp.name == "NEW"
    assert panel.set_field("name", "  ") is False and dip.fp.name == "NEW"
    assert panel.name_edit.text() == "NEW"
    panel.attr_checks["exclude_from_bom"].setChecked(True)  # как щелчок пользователя
    assert "exclude_from_bom" in dip.fp.attrs
    assert panel.set_field("smd", True)
    assert set(dip.fp.attrs) == {"smd", "exclude_from_bom"}  # smd исключает through_hole
    assert not panel.attr_checks["through_hole"].isChecked()
    assert panel.set_field("exclude_from_bom", False)
    assert set(dip.fp.attrs) == {"smd"}
    assert panel.set_field("layer", "B.Cu") and dip.fp.layer == "B.Cu"
    assert panel.set_field("layer", "X.Cu") is False
    assert panel.set_field("zone_connect", 2) and dip.fp.zone_connect == 2
    assert panel.zone_combo.currentData() == 2
    assert panel.set_field("zone_connect", None) and dip.fp.zone_connect is None
    n = dip.undo_stack.count()
    for _ in range(n):
        dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()
    assert panel.attr_checks["through_hole"].isChecked()


def test_panel_numeric_fields(dip, panel):
    errors: list[str] = []
    panel.error.connect(errors.append)
    assert panel.set_field("clearance", "0,25") and dip.fp.clearance == 0.25
    assert panel.numeric_edits["clearance"].text() == "0.25"
    assert panel.set_field("clearance", "abc") is False and dip.fp.clearance == 0.25
    assert panel.numeric_edits["clearance"].text() == "0.25"  # восстановлено
    assert panel.set_field("clearance", "-1") is False
    assert panel.set_field("solder_mask_margin", "-0.05") and dip.fp.solder_mask_margin == -0.05
    assert panel.set_field("solder_paste_ratio", "-0.1") and dip.fp.solder_paste_ratio == -0.1
    assert panel.set_field("clearance", "") and dip.fp.clearance is None
    assert len(errors) == 2
    assert dip.undo_stack.count() == 4


def test_panel_follows_document(doc, qtbot):
    p = PropertiesPanel(doc)
    qtbot.addWidget(p)
    assert not p.isEnabled() and p.name_edit.text() == ""
    doc.open(DIP14)
    assert p.isEnabled() and p.name_edit.text() == "DIP-14_W7.62mm"
    from kicadfp.gui.commands import SetAttrCommand
    doc.apply(SetAttrCommand(doc, doc.fp, "descr", "из команды"))
    assert p.descr_edit.text() == "из команды"
    doc.close()
    assert not p.isEnabled() and p.descr_edit.text() == ""


def test_widgets_without_document(doc, qtbot):
    pt, it = PadTable(doc), ItemsTable(doc)
    qtbot.addWidget(pt)
    qtbot.addWidget(it)
    assert pt.pad_model().rowCount() == 0 and it.items_model().rowCount() == 0
    assert pt.add_pad() is None and pt.remove_selected() == 0
    model = PadTableModel(doc)
    assert model.rowCount() == 0 and ItemsTableModel(doc).columnCount() == 9


# ---------------------------------------------------------------------------------------------
# Таблица графики: редкие ветви (кривые, неизменённые значения, недопустимые роли)
# ---------------------------------------------------------------------------------------------

def test_items_helpers_unknown_item_and_check_values():
    """Вспомогательные функции: вид и координаты «чужого» элемента, разбор CheckStateRole."""
    from kicadfp.gui.items_table import _coords, _is_checked, item_kind

    fp = generators.GENERATORS["dip"](pins=8)
    pad = fp.pads[0]
    assert item_kind(pad) == "pad"  # не графика и не текст — имя узла
    assert item_kind(object()) == "?"
    assert _coords(pad) == [(None, False)] * 4
    assert _is_checked(True) is True and _is_checked(False) is False
    assert _is_checked(Qt.CheckState.Checked.value) is True
    assert _is_checked(0) is False
    assert _is_checked("да") is True and _is_checked("") is False  # не число -> bool()


def test_items_curve_rows_read_only(doc, qtbot):
    fp = generators.GENERATORS["dip"](pins=8)
    doc.open_footprint(fp)
    curve = doc.fp.new_curve([(0, 0), (1, 1), (2, 1), (3, -1)], "F.Fab", 0.1)
    empty = doc.fp.new_curve([(0, 0), (1, 1), (2, 1), (3, 0)], "F.Fab", 0.1)
    empty.node.items.remove(empty.node.find("pts"))  # кривая без точек (повреждённый файл)
    doc.undo_stack.clear()
    t = ItemsTable(doc)
    qtbot.addWidget(t)
    m = t.items_model()
    m._on_document_changed()
    r, r_empty = m.row_of(curve), m.row_of(empty)
    # X1/Y1 — первая точка, X2/Y2 — последняя; всё только для чтения
    assert [cell(m, r, c) for c in (COL_X1, COL_Y1, COL_X2, COL_Y2)] == ["0", "0", "3", "-1"]
    assert [cell(m, r_empty, c) for c in (COL_X1, COL_Y1, COL_X2, COL_Y2)] == [""] * 4
    for c in (COL_X1, COL_Y1, COL_X2, COL_Y2):
        assert not m.flags(m.index(r, c)) & Qt.ItemFlag.ItemIsEditable
    errors: list[str] = []
    m.error.connect(errors.append)
    assert m.setData(m.index(r, COL_X1), "5", ED) is False
    assert errors and "только для чтения" in errors[-1]
    assert m.setData(m.index(r, COL_TEXT), "x", ED) is False  # у графики нет текста
    assert cell(m, r, COL_TEXT) == "" and cell(m, r, COL_HIDDEN) == ""
    assert doc.undo_stack.count() == 0


def test_items_tooltips_alignment_and_user_role(dip, items):
    m = items.items_model()
    tip = Qt.ItemDataRole.ToolTipRole
    assert "Ширина" in m.headerData(COL_WIDTH, Qt.Orientation.Horizontal, tip)
    assert m.headerData(COL_KIND, Qt.Orientation.Horizontal, DISP) == "Тип"
    ref_row = m.row_of(dip.fp.reference)
    assert cell(m, ref_row, COL_KIND, tip) == "Поле «Reference»"
    assert cell(m, 0, COL_KIND, tip) == "Вид элемента"  # графика — подсказка столбца
    align = cell(m, 0, COL_X1, Qt.ItemDataRole.TextAlignmentRole)
    assert align & int(Qt.AlignmentFlag.AlignRight)
    assert cell(m, 0, COL_KIND, Qt.ItemDataRole.TextAlignmentRole) is None
    assert cell(m, 0, COL_KIND, Qt.ItemDataRole.UserRole).node is dip.fp.graphics[0].node
    assert cell(m, 0, COL_KIND, Qt.ItemDataRole.DecorationRole) is None
    # строки за пределами таблицы
    bad = m.index(999, 0)
    assert m.data(bad) is None and m.flags(bad) == Qt.ItemFlag.NoItemFlags
    assert m.setData(bad, "1", ED) is False


def test_items_poly_tooltip(doc, qtbot):
    doc.open_footprint(generators.GENERATORS["dip"](pins=8))
    poly = doc.fp.new_poly([(0, 0), (1, 0), (1, 1)], "F.Fab", 0.1)
    t = ItemsTable(doc)
    qtbot.addWidget(t)
    m = t.items_model()
    m._on_document_changed()
    r = m.row_of(poly)
    assert cell(m, r, COL_X2, Qt.ItemDataRole.ToolTipRole) == "Число точек многоугольника"


def test_items_unchanged_values_make_no_undo_step(dip, items):
    """Ввод текущего значения принимается, но шага отмены не создаёт."""
    m = items.items_model()
    fp = dip.fp
    line = fp.graphics[0]
    ref = fp.reference
    rr = m.row_of(ref)
    from kicadfp.gui.pad_table import format_mm
    assert m.setData(m.index(0, COL_LAYER), line.layer, ED)
    assert m.setData(m.index(0, COL_WIDTH), format_mm(line.width), ED)
    assert m.setData(m.index(0, COL_X1), format_mm(line.start[0]), ED)
    assert m.setData(m.index(rr, COL_TEXT), ref.text, ED)
    assert m.setData(m.index(rr, COL_WIDTH), f"{ref.font_size_x} x {ref.font_size_y}", ED)
    state = Qt.CheckState.Checked if ref.hide else Qt.CheckState.Unchecked
    assert m.setData(m.index(rr, COL_HIDDEN), state, CHECK)
    assert dip.undo_stack.count() == 0
    # «Скрыт» — только через CheckStateRole и только у текста; прочие ячейки — только EditRole
    assert m.setData(m.index(rr, COL_HIDDEN), True, ED) is False
    assert m.setData(m.index(0, COL_HIDDEN), Qt.CheckState.Checked, CHECK) is False
    assert m.setData(m.index(0, COL_WIDTH), "0.3", CHECK) is False
    assert m.setData(m.index(rr, COL_TEXT), None, ED) and ref.text == ""
    assert dip.undo_stack.count() == 1
    dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_items_text_single_font_size_and_arc_start(doc, qtbot):
    doc.open_footprint(generators.GENERATORS["dip"](pins=8))
    arc = doc.fp.new_arc((0, 1), (1, 2), (2, 1), "F.Fab", 0.1)
    doc.undo_stack.clear()
    t = ItemsTable(doc)
    qtbot.addWidget(t)
    m = t.items_model()
    m._on_document_changed()
    r = m.row_of(arc)
    assert m.setData(m.index(r, COL_X1), "-0.5", ED) and arc.start == (-0.5, 1)
    assert m.setData(m.index(r, COL_Y1), "0.5", ED) and arc.start == (-0.5, 0.5)
    assert m.setData(m.index(r, COL_X2), "2.5", ED) and arc.end == (2.5, 1)
    ref = doc.fp.reference
    rr = m.row_of(ref)
    assert m.setData(m.index(rr, COL_WIDTH), "0.8", ED)  # одно число -> квадратный шрифт
    assert (ref.font_size_x, ref.font_size_y) == (0.8, 0.8)
    assert doc.undo_stack.count() == 4


def test_items_remove_nothing_removable(dip, items):
    """Выделены только Reference и Value — удалять нечего, документ не меняется."""
    m = items.items_model()
    items.select_item(dip.fp.reference)
    assert items.remove_selected() == 0
    items.clearSelection()
    assert items.remove_selected() == 0
    assert m.rowCount() == 21 and dip.undo_stack.count() == 0


def test_items_remove_several_in_one_undo_step(dip, items):
    m = items.items_model()
    sel = items.selectionModel()
    for r in (0, 1, 2):
        sel.select(m.index(r, 0), QItemSelectionModel.SelectionFlag.Select
                   | QItemSelectionModel.SelectionFlag.Rows)
    assert items.remove_selected() == 3
    assert m.rowCount() == 18 and dip.undo_stack.count() == 1
    dip.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()
