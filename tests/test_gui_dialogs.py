"""Дерево библиотек и диалоги GUI (pytest-qt, offscreen)."""

from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLineEdit, QSpinBox  # noqa: E402

from kicadfp import generators, io  # noqa: E402
from kicadfp.gui.dialogs import (GENERATOR_TITLES, AboutDialog, GenerateDialog,  # noqa: E402
                                 ItemPropertiesDialog, PadBatchDialog, ValidateDialog)
from kicadfp.gui.document import FootprintDocument  # noqa: E402
from kicadfp.gui.libtree import KIND_FOOTPRINT, LibraryTree  # noqa: E402
from kicadfp.library import Library  # noqa: E402
from kicadfp.model import Circle, Line, Pad  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

DIP_LIB = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14 = DIP_LIB / "DIP-14_W7.62mm.kicad_mod"


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


def _text(doc: FootprintDocument) -> str:
    return io.dumps(doc.fp)


# =============================================================================================
# GenerateDialog
# =============================================================================================

def test_generate_dialog_lists_all_generators(qtbot):
    dlg = GenerateDialog(preview=False)
    qtbot.addWidget(dlg)
    combo = dlg._combo
    keys = [combo.itemData(i) for i in range(combo.count())]
    assert keys == list(generators.GENERATORS)
    assert combo.itemText(keys.index("dip")) == GENERATOR_TITLES["dip"]
    assert dlg.generator == "dip"


def test_generate_dialog_form_widgets_by_type(qtbot):
    dlg = GenerateDialog(generator="dip", preview=False)
    qtbot.addWidget(dlg)
    assert "name" not in dlg.param_names()
    assert isinstance(dlg.param_widget("pins"), QSpinBox)
    pitch = dlg.param_widget("pitch")
    assert isinstance(pitch, QDoubleSpinBox) and pitch.decimals() == 3
    assert isinstance(dlg.param_widget("first_square"), QCheckBox)
    assert isinstance(dlg.param_widget("pad_shape"), QLineEdit)
    assert isinstance(dlg.param_widget("pad_size"), QLineEdit)
    assert dlg.param_widget("pad_size").text() == "[1.6, 1.6]"
    assert dlg.param("body_width") is None  # «авто»
    dlg.set_generator("pin_header")
    holes = dlg.param_widget("mounting_holes")
    assert isinstance(holes, QLineEdit) and holes.text() == ""


def test_generate_dip_14_pins(qtbot):
    dlg = GenerateDialog(preview=False)
    qtbot.addWidget(dlg)
    dlg.set_generator("dip")
    dlg.set_param("pins", 16)
    assert dlg.set_param("pins", 14) is True
    fp = dlg.build()
    assert fp is not None and dlg.error_text == ""
    assert len(fp.pads) == 14
    assert fp.name == "DIP-14_W7.62mm"
    assert dlg.footprint is fp


def test_generate_lab_snp8_defaults(qtbot):
    dlg = GenerateDialog(preview=True)
    qtbot.addWidget(dlg)
    dlg.set_generator("lab_snp8")
    fp = dlg.build()
    assert fp is not None
    ref = generators.lab_snp8()
    assert io.dumps(fp) == io.dumps(ref)
    assert fp.name == "snp8"


def test_generate_alias_name_and_json_params(qtbot):
    dlg = GenerateDialog(preview=False)
    qtbot.addWidget(dlg)
    dlg.set_generator("snp8")  # синоним
    assert dlg.generator == "lab_snp8"
    dlg.set_generator("pin_header")
    dlg.set_param("rows", 2)
    dlg.set_param("cols", 3)
    dlg.set_param("mounting_holes", "[[-3, 2.54, 3.2]]")
    dlg.set_param("name", "MyHeader")
    fp = dlg.build()
    assert fp is not None, dlg.error_text
    assert fp.name == "MyHeader"
    assert len(fp.pads) == 7  # 6 выводов + монтажное отверстие
    dlg.set_param("pad_size", (1.7, 2.0))
    assert dlg.param("pad_size") == (1.7, 2.0)


def test_generate_errors_go_to_label(qtbot):
    dlg = GenerateDialog(preview=False)
    qtbot.addWidget(dlg)
    dlg.set_generator("dip")
    dlg.set_param("pins", 13)  # нечётное — генератор отвергает
    assert dlg.build() is None
    assert dlg.error_text and not dlg.error_label.isHidden()
    dlg.set_param("pins", 8)
    assert dlg.build() is not None and dlg.error_text == ""
    dlg.set_param("pad_size", "[1, 2, 3]")  # неверный JSON-кортеж
    assert dlg.build() is None and "pad_size" in dlg.error_text
    assert dlg.set_param("first_square", "может быть") is False
    with pytest.raises(KeyError):
        dlg.set_param("no_such_param", 1)


def test_generate_dialog_kicad_format(qtbot):
    """Регрессия (приёмка): «Формат файла» — корпус в формате KiCad 8 (его открывает и
    KiCad 8; формат KiCad 9 по умолчанию KiCad 8 не читает)."""
    dlg = GenerateDialog(generator="lab_dip14", preview=False)
    qtbot.addWidget(dlg)
    assert dlg.kicad_version == 9
    assert dlg.build().version == 20241229
    dlg.set_kicad_version(8)
    fp = dlg.build()
    assert dlg.kicad_version == 8 and fp.version == 20240108
    assert io.dumps(fp) == io.dumps(generators.from_json("lab_dip14", {}, version=8))
    dlg.set_kicad_version(20211014)
    assert dlg.kicad_version == 6 and dlg.build().version == 20211014
    with pytest.raises(ValueError):
        dlg.set_kicad_version(5)
    assert dlg.kicad_version == 6
    assert generators.current_version() == 20241229   # контекст не «протекает»


def test_generate_open_in_document(qtbot, doc):
    dlg = GenerateDialog(generator="lab_dip14", preview=False)
    qtbot.addWidget(dlg)
    assert dlg.open_in(doc) is True
    assert doc.fp is not None and len(doc.fp.pads) == 14
    assert doc.path is None and doc.is_modified


# =============================================================================================
# ValidateDialog
# =============================================================================================

def test_validate_dialog_drill_gt_size(qtbot, dip):
    pad = dip.fp.pads[0]
    from kicadfp.gui.commands import SetAttrCommand
    dip.apply(SetAttrCommand(dip, pad, "drill", 3.0))  # отверстие больше площадки 1.6
    dlg = ValidateDialog(dip)
    qtbot.addWidget(dlg)
    assert not dlg.isModal()
    issues = dlg.run()
    codes = [i.code for i in issues]
    assert "PAD_DRILL_GT_SIZE" in codes
    row = codes.index("PAD_DRILL_GT_SIZE")
    assert issues[row].level == "error"
    t = dlg.table
    assert t.rowCount() == len(issues)
    assert t.item(row, 0).text() == "Ошибка"
    assert t.item(row, 1).text() == "PAD_DRILL_GT_SIZE"
    assert t.item(row, 0).background().color().name() != "#000000"
    assert "Ошибок: 1" in dlg.summary_text
    # двойной щелчок -> выделение элемента
    with qtbot.waitSignal(dip.selection_changed):
        assert dlg.select_issue(row) is True
    assert dip.selected == pad
    # после исправления «Проверить снова» — ошибки нет
    dip.undo()
    assert "PAD_DRILL_GT_SIZE" not in [i.code for i in dlg.run()]


def test_validate_dialog_clean_and_empty(qtbot, doc):
    dlg = ValidateDialog(doc)
    qtbot.addWidget(dlg)
    assert dlg.run() == [] and dlg.summary_text == "Корпус не открыт"
    doc.open_footprint(generators.dip(pins=8))
    assert all(i.level != "error" for i in dlg.run())
    dlg.show()
    qtbot.waitExposed(dlg)
    # окно видно — проверка повторяется после изменений
    from kicadfp.gui.commands import SetAttrCommand
    doc.apply(SetAttrCommand(doc, doc.fp.pads[1], "drill", 5.0))
    assert "PAD_DRILL_GT_SIZE" in [i.code for i in dlg.issues]
    dlg.close()


# =============================================================================================
# PadBatchDialog
# =============================================================================================

def test_pad_batch_renumber_move_layers_single_undo(qtbot, dip):
    original = _text(dip)
    stack = dip.undo_stack
    count0 = stack.count()
    pads_before = dip.fp.pads
    xs = [p.x for p in pads_before]
    dlg = PadBatchDialog(dip)
    qtbot.addWidget(dlg)
    assert dlg.scope == "all"
    dlg.set_renumber(start=101, order="file", prefix="P")
    dlg.set_move(1.27, -2.54)
    dlg.set_layers("F.Cu, F.Mask")
    assert dlg.apply_to(dip) is True, dlg.error_text
    assert stack.count() == count0 + 1  # один шаг отмены
    pads = dip.fp.pads
    assert [p.number for p in pads] == [f"P{101 + i}" for i in range(14)]
    assert [p.x for p in pads] == pytest.approx([x + 1.27 for x in xs])
    assert all(p.layers == ["F.Cu", "F.Mask"] for p in pads)
    # идентичность площадок сохраняется (представления таблиц остаются действительными)
    assert [p.node for p in pads] == [p.node for p in pads_before]
    dip.undo()
    assert _text(dip) == original
    dip.redo()
    assert dip.fp.pads[0].number == "P101"


def test_pad_batch_selected_subset_and_rotate(qtbot, dip):
    original = _text(dip)
    sel = dip.fp.pads[:2]
    dlg = PadBatchDialog(dip, sel)
    qtbot.addWidget(dlg)
    assert dlg.scope == "selected"
    assert len(dlg.target_pads()) == 2
    dlg.set_renumber(start=20)
    dlg.set_rotate(90, (0.0, 0.0))
    dlg.set_size(2.0, 1.5)
    dlg.set_drill((1.2, 0.8))
    assert dlg.apply_to() is True, dlg.error_text
    p0, p1 = dip.fp.pads[:2]
    assert (p0.number, p1.number) == ("20", "21")
    assert [p.number for p in dip.fp.pads[2:]] == [str(i) for i in range(3, 15)]
    # (0, 2.54) повёрнута на 90° против часовой (ось Y вниз) -> (2.54, 0)
    assert (p1.x, p1.y) == pytest.approx((2.54, 0.0), abs=1e-6)
    assert p1.angle == pytest.approx(90)
    assert (p0.size_x, p0.size_y) == (2.0, 1.5)
    assert p0.drill.oval and p0.drill.size == (1.2, 0.8)
    dip.undo()
    assert _text(dip) == original


def test_pad_batch_type_shape_and_errors(qtbot, dip):
    dlg = PadBatchDialog(dip)
    qtbot.addWidget(dlg)
    assert dlg.apply_to() is False and "операции" in dlg.error_text
    dlg.set_type("smd", "roundrect")
    assert dlg.apply_to() is True
    pads = dip.fp.pads
    assert all(p.type == "smd" and p.shape == "roundrect" and p.drill is None for p in pads)
    assert set(pads[0].layers) == {"F.Cu", "F.Paste", "F.Mask"}
    dlg.clear_operations()
    dlg.set_layers("F.Cu, Nonexistent.Layer")
    count = dip.undo_stack.count()
    assert dlg.apply_to() is False and "Nonexistent.Layer" in dlg.error_text
    assert dip.undo_stack.count() == count
    dip.undo()
    assert all(p.type == "thru_hole" for p in dip.fp.pads)


def test_pad_batch_circular_all(qtbot, dip):
    dlg = PadBatchDialog(dip)
    qtbot.addWidget(dlg)
    dlg.set_renumber(start=1, order="circular")
    # DIP уже пронумерован по кругу — изменений нет, шаг не добавляется
    assert dlg.apply_to() is False and dlg.error_text == ""
    dlg.set_renumber(start=1, order="xy")
    assert dlg.apply_to() is True
    # по X, затем по Y: левый ряд 1…7 сверху вниз, правый — 8…14 сверху вниз
    nums = {(round(p.x, 2), round(p.y, 2)): p.number for p in dip.fp.pads}
    assert nums[(0.0, 0.0)] == "1" and nums[(7.62, 0.0)] == "8"
    assert nums[(7.62, 15.24)] == "14"


# =============================================================================================
# ItemPropertiesDialog и AboutDialog
# =============================================================================================

def test_item_properties_pad(qtbot, dip):
    original = _text(dip)
    pad = dip.fp.pads[2]
    dlg = ItemPropertiesDialog(dip, pad)
    qtbot.addWidget(dlg)
    assert dlg.field_value("number") == "3"
    assert dlg.changes() == {}  # без правок ничего не меняется
    dlg.set_field("number", "A3")
    dlg.set_field("position", (1.0, 2.0))
    dlg.set_field("size_x", "2,2")
    dlg.set_field("drill", "1.1 x 0.9")
    dlg.set_field("layers", "smd")
    dlg.set_field("type", "smd")
    count = dip.undo_stack.count()
    dlg.set_field("drill", "")  # у smd отверстия нет
    assert dlg.apply() is True, dlg.error_text
    assert dip.undo_stack.count() == count + 1
    p = dip.fp.pads[2]
    assert (p.number, p.x, p.y, p.size_x, p.type, p.drill) == ("A3", 1.0, 2.0, 2.2, "smd", None)
    assert set(p.layers) == {"F.Cu", "F.Paste", "F.Mask"}
    dip.undo()
    assert _text(dip) == original


def test_item_properties_errors_and_graphic(qtbot, dip):
    line = next(g for g in dip.fp.graphics if isinstance(g, Line))
    dlg = ItemPropertiesDialog(dip, line)
    qtbot.addWidget(dlg)
    dlg.set_field("width", "abc")
    count = dip.undo_stack.count()
    assert dlg.apply() is False and dlg.error_text
    assert dip.undo_stack.count() == count
    dlg.reload()
    dlg.set_field("layer", "B.SilkS")
    dlg.set_field("end", (5.0, 6.0))
    assert dlg.apply() is True
    assert line.layer == "B.SilkS" and line.end == (5.0, 6.0)
    dip.undo()
    assert line.layer == "F.SilkS"


def test_item_properties_circle_and_text(qtbot, doc):
    fp = generators.capacitor_radial(polarized=True)
    doc.open_footprint(fp)
    circle = next(g for g in doc.fp.graphics if isinstance(g, Circle))
    r = circle.radius
    dlg = ItemPropertiesDialog(doc, circle)
    qtbot.addWidget(dlg)
    dlg.set_field("center", (10.0, 5.0))
    assert dlg.apply() is True
    assert circle.center == (10.0, 5.0)
    assert circle.radius == pytest.approx(r)
    ref = doc.fp.reference
    tdlg = ItemPropertiesDialog(doc, ref)
    qtbot.addWidget(tdlg)
    tdlg.set_field("text", "U1")
    tdlg.set_field("justify", "left mirror")
    tdlg.set_field("hide", True)
    assert tdlg.apply() is True, tdlg.error_text
    assert ref.text == "U1" and ref.mirror and "left" in ref.justify and ref.hide


def test_about_dialog(qtbot):
    from kicadfp import __version__
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert dlg.version == __version__ and __version__ in dlg.text


# =============================================================================================
# LibraryTree
# =============================================================================================

@pytest.fixture
def tree(qtbot) -> LibraryTree:
    t = LibraryTree()
    t.show_errors = False
    qtbot.addWidget(t)
    return t


def test_library_tree_add_library(tree, qtbot):
    with qtbot.waitSignal(tree.libraries_changed):
        lib = tree.add_library(DIP_LIB)
    n_files = len(list(DIP_LIB.glob("*.kicad_mod")))
    assert n_files == 268  # kicad-footprints 8.0.0 (281 — в ветке master)
    root = tree.root_item(0)
    assert root.rowCount() == n_files == len(lib)
    assert tree.children_names(lib) == lib.names
    assert tree.root_count() == 1
    tree.add_library(DIP_LIB)  # повторно не добавляется
    assert tree.root_count() == 1


def test_library_tree_open_requested(tree, qtbot):
    tree.add_library(DIP_LIB)
    ix = tree.index_for_path(DIP14)
    assert ix.isValid() and tree.item_info(ix)[0] == KIND_FOOTPRINT
    with qtbot.waitSignal(tree.open_requested) as blocker:
        tree.doubleClicked.emit(ix)
    assert blocker.args[0] == DIP14.resolve()
    tree.setCurrentIndex(ix)
    with qtbot.waitSignal(tree.open_requested) as blocker:
        qtbot.keyClick(tree, Qt.Key.Key_Return)
    assert blocker.args[0].name == DIP14.name
    # корень библиотеки не открывается
    assert tree.open_index(tree.root_item(0).index()) is False


def test_library_tree_file_and_remove(tree, qtbot, tmp_path):
    f = tmp_path / "one.kicad_mod"
    shutil.copy(DIP14, f)
    tree.add_library(DIP_LIB)
    tree.add_file(f)
    assert tree.files == [f.resolve()] and tree.root_count() == 2
    with qtbot.waitSignal(tree.open_requested) as blocker:
        tree.open_index(tree.root_item(1).index())
    assert blocker.args[0] == f.resolve()
    tree.setCurrentIndex(tree.root_item(0).index())
    assert tree.remove_selected() == 1
    assert tree.libraries == [] and tree.root_count() == 1
    with pytest.raises(FileNotFoundError):
        tree.add_file(tmp_path / "missing.kicad_mod")


def test_library_tree_rename_copy_delete(tree, qtbot, tmp_path):
    src_dir = tmp_path / "A.pretty"
    src_dir.mkdir()
    for name in ("DIP-14_W7.62mm", "DIP-8_W7.62mm"):
        shutil.copy(DIP_LIB / f"{name}.kicad_mod", src_dir)
    dst = Library(tmp_path / "B.pretty", create=True)
    a = tree.add_library(src_dir)
    tree.add_library(dst.path)
    b = tree.library_for(dst.path)

    # переименование через Library.rename
    with qtbot.waitSignal(tree.footprint_renamed) as blocker:
        new = tree.rename_footprint(src_dir / "DIP-8_W7.62mm.kicad_mod", "MyDIP8")
    assert new == (src_dir / "MyDIP8.kicad_mod").resolve()
    assert blocker.args[1] == new
    assert new.is_file() and not (src_dir / "DIP-8_W7.62mm.kicad_mod").exists()
    assert io.load(new).name == "MyDIP8"
    assert tree.children_names(a) == ["DIP-14_W7.62mm", "MyDIP8"]

    # копирование в другую библиотеку через Library.copy_to
    copied = tree.copy_footprint((a, "MyDIP8"), b, "Copy8")
    assert copied.is_file() and copied.parent == dst.path.resolve()
    assert tree.children_names(b) == ["Copy8"]
    assert io.load(copied).name == "Copy8"
    with pytest.raises(FileExistsError):
        tree.copy_footprint((a, "MyDIP8"), b, "Copy8")

    # интерактивные действия с подменёнными вопросами
    tree.select_path(src_dir / "DIP-14_W7.62mm.kicad_mod")
    tree.ask_text = lambda title, label, text: "DIP14x"
    assert tree.rename_selected_interactive() is not None
    assert "DIP14x" in tree.children_names(a)
    tree.select_path(src_dir / "DIP14x.kicad_mod")
    tree.ask_copy = lambda libs, name, source: (b, "Copy14")
    assert tree.copy_selected_interactive() is not None
    assert tree.children_names(b) == ["Copy14", "Copy8"]

    # удаление — с подтверждением
    tree.select_path(src_dir / "DIP14x.kicad_mod")
    tree.ask_confirm = lambda title, question: False
    assert tree.delete_selected_interactive() is None
    assert (src_dir / "DIP14x.kicad_mod").exists()
    tree.ask_confirm = lambda title, question: True
    with qtbot.waitSignal(tree.footprint_removed):
        assert tree.delete_selected_interactive() is not None
    assert not (src_dir / "DIP14x.kicad_mod").exists()
    assert tree.children_names(a) == ["MyDIP8"]

    # ошибка интерактивного переименования -> сигнал error, без исключения
    tree.select_path(src_dir / "MyDIP8.kicad_mod")
    shutil.copy(DIP14, src_dir / "Taken.kicad_mod")
    tree.refresh()
    tree.select_path(src_dir / "MyDIP8.kicad_mod")
    tree.ask_text = lambda *a: "Taken"
    with qtbot.waitSignal(tree.error):
        assert tree.rename_selected_interactive() is None


def test_library_tree_context_menu_and_refresh(tree, tmp_path):
    lib_dir = tmp_path / "C.pretty"
    lib_dir.mkdir()
    shutil.copy(DIP14, lib_dir)
    lib = tree.add_library(lib_dir)
    ix = tree.index_for_path(lib_dir / DIP14.name)
    texts = [a.text() for a in tree.context_menu_for(ix).actions() if a.text()]
    assert texts[:4] == ["Открыть", "Переименовать…", "Копировать в библиотеку…", "Удалить…"]
    assert "Обновить" in texts
    root_texts = [a.text() for a in tree.context_menu_for(tree.root_item(0).index()).actions()]
    assert "Закрыть библиотеку" in root_texts
    # файл, добавленный другой программой, появляется после обновления
    shutil.copy(DIP_LIB / "DIP-8_W7.62mm.kicad_mod", lib_dir)
    tree.refresh()
    assert tree.children_names(lib) == ["DIP-14_W7.62mm", "DIP-8_W7.62mm"]


def test_pad_batch_default_uses_document_selection(qtbot, dip):
    pad = dip.fp.pads[5]
    dip.select(pad)
    dlg = PadBatchDialog(dip)
    qtbot.addWidget(dlg)
    assert dlg.scope == "selected"
    assert dlg.target_pads() == [pad]
    assert isinstance(dlg.target_pads()[0], Pad)
