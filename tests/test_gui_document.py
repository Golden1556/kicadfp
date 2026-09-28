"""Основа GUI: FootprintDocument, команды отмены/повтора, create_app, main (pytest-qt, offscreen).

Проверяется главное свойство команд: отмена возвращает текст файла байт в байт, повтор —
точно состояние после команды, а объекты-узлы (и представления над ними) остаются теми же.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QLocale  # noqa: E402
from PySide6.QtGui import QPalette, QUndoCommand  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

import kicadfp  # noqa: E402
from kicadfp import generators  # noqa: E402
from kicadfp.gui import app as gui_app  # noqa: E402
from kicadfp.gui import main as gui_main  # noqa: E402
from kicadfp.gui.commands import (AddItemCommand, BatchCommand, DocumentCommand,  # noqa: E402
                                  OperationCommand, RemoveItemCommand, ReplaceNodeCommand,
                                  SetAttrCommand, SetAttrsCommand, describe_item,
                                  next_merge_id)
from kicadfp.gui.document import UNDO_LIMIT, FootprintDocument  # noqa: E402
from kicadfp.io import LegacyLibraryError, ValidationError  # noqa: E402
from kicadfp.model import Line, Pad, Poly, Rect, Text  # noqa: E402
from kicadfp.sexpr import SexprSyntaxError  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

pytestmark = pytest.mark.gui

ROOT = Path(__file__).resolve().parents[1]
DIP14 = FIXTURES / "kicad8" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
POWERPAK = FIXTURES / "kicad8" / "Package_SO.pretty" / "PowerPAK_SO-8L_Single.kicad_mod"


def text_of(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def changed_lines(a: str, b: str) -> list[tuple[str, str]]:
    la, lb = a.split("\n"), b.split("\n")
    assert len(la) == len(lb), "число строк изменилось"
    return [(x, y) for x, y in zip(la, lb, strict=True) if x != y]


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


# ---------------------------------------------------------------------------------------------
# Открытие
# ---------------------------------------------------------------------------------------------

def test_open_dip14(doc, qtbot):
    with qtbot.waitSignals([doc.document_changed, doc.changed, doc.path_changed]):
        assert doc.open(DIP14) is True
    fp = doc.fp
    assert fp.name == "DIP-14_W7.62mm" and len(fp.pads) == 14
    assert doc.path == DIP14 and doc.display_name == "DIP-14_W7.62mm"
    assert doc.library is not None and doc.library.name == "Package_DIP"
    assert not doc.is_modified and doc.selected is None
    assert doc.undo_stack.count() == 0
    assert doc.undo_stack.undoLimit() == UNDO_LIMIT >= 100
    # открытый без изменений файл записывается байт в байт (у KiCad 8.0 нет '\n' в конце)
    assert doc.fp.dumps().encode("utf-8") == DIP14.read_bytes()


def test_open_errors_keep_current_document(dip, tmp_path):
    bad = tmp_path / "bad.kicad_mod"
    bad.write_text('(footprint "x"\n\t(layer "F.Cu")\n', encoding="utf-8")
    with pytest.raises(SexprSyntaxError) as ei:
        dip.open(bad)
    assert "строка" in str(ei.value)
    with pytest.raises(LegacyLibraryError):
        dip.open(FIXTURES / "legacy_mod" / "My_lib.mod")  # три корпуса в одном .mod
    with pytest.raises(IsADirectoryError):
        dip.open(DIP14.parent)
    with pytest.raises(FileNotFoundError):
        dip.open(tmp_path / "нет.kicad_mod")
    assert dip.fp.name == "DIP-14_W7.62mm" and dip.path == DIP14


def test_open_legacy_single_module(doc, tmp_path):
    lines = text_of(FIXTURES / "legacy_mod" / "My_lib.mod").split("\n")
    end = next(i for i, s in enumerate(lines) if s.startswith("$EndMODULE"))
    start = next(i for i, s in enumerate(lines) if s.startswith("$MODULE"))
    one = lines[:2] + ["$INDEX", "dip14", "$EndINDEX"] + lines[start:end + 1] + ["$EndLIBRARY"]
    mod = tmp_path / "one.mod"
    mod.write_text("\n".join(one) + "\n", encoding="utf-8")
    assert doc.open(mod)
    # старый формат: корпус как новый несохранённый — записывать только «Сохранить как»
    assert doc.fp.name == "dip14" and doc.path is None and doc.library is None
    assert doc.is_modified and doc.save() is False
    out = tmp_path / "dip14.kicad_mod"
    assert doc.save_as(out) and not doc.is_modified
    assert kicadfp.load(out).name == "dip14"


# ---------------------------------------------------------------------------------------------
# SetAttrCommand: один токен, точная отмена, повтор
# ---------------------------------------------------------------------------------------------

def test_set_attr_changes_one_token_and_undo_is_exact(dip, qtbot):
    orig = text_of(DIP14)
    pad = dip.fp.pad("3")
    cmd = SetAttrCommand(dip, pad, "x", 1.5)
    with qtbot.waitSignal(dip.changed):
        assert dip.apply(cmd) is True
    new = dip.fp.dumps()
    assert changed_lines(orig, new) == [("\t\t(at 0 5.08)", "\t\t(at 1.5 5.08)")]
    assert (cmd.attr, cmd.old_value, cmd.new_value) == ("x", 0, 1.5)
    assert dip.undo_stack.count() == 1 and dip.is_modified
    assert dip.undo_stack.undoText() == "изменение X площадки 3"
    assert dip.undo_stack.command(0).text() == "Изменение X площадки 3"
    with qtbot.waitSignal(dip.changed):
        dip.undo_stack.undo()
    assert dip.fp.dumps().encode("utf-8") == DIP14.read_bytes()
    assert not dip.is_modified
    with qtbot.waitSignal(dip.changed):
        dip.undo_stack.redo()
    assert dip.fp.dumps() == new and pad.x == 1.5
    assert dip.contains(pad)


def test_undo_restores_original_number_text(doc, tmp_path):
    """Отмена возвращает исходную запись числа («0.000»), которую setter записал бы иначе."""
    src = text_of(DIP14).replace("\t\t(at 0 5.08)", "\t\t(at 0.000 5.080)", 1)
    path = tmp_path / "odd.kicad_mod"
    path.write_bytes(src.encode("utf-8"))
    assert doc.open(path)
    pad = doc.fp.pad("3")
    doc.apply(SetAttrCommand(doc, pad, "x", 2.0))
    doc.apply(SetAttrCommand(doc, pad, "x", 0.0))
    assert "(at 0 5.080)" in doc.fp.dumps()        # setter пишет «0», а не «0.000»
    doc.undo()
    doc.undo()
    assert doc.fp.dumps() == src


def test_150_commands_and_150_undo(dip):
    orig = dip.fp.dumps()
    states = [orig]
    for i in range(150):
        pad = dip.fp.pads[i % 14]
        assert dip.apply(SetAttrCommand(dip, pad, "size_x", round(1.0 + (i + 1) * 0.01, 2)))
        states.append(dip.fp.dumps())
    assert dip.undo_stack.count() == 150
    for i in range(150):
        dip.undo_stack.undo()
        assert dip.fp.dumps() == states[149 - i]
    assert not dip.undo_stack.canUndo() and dip.fp.dumps() == orig and not dip.is_modified
    for _ in range(150):
        dip.undo_stack.redo()
    assert dip.fp.dumps() == states[-1]


def test_set_attr_on_detached_view_binds_to_document(dip):
    """Представление без родителя над узлом корпуса пишет по профилю корпуса."""
    loose = Pad(dip.fp.pad("2").node)
    assert loose.parent is None
    cmd = SetAttrCommand(dip, loose, "y", 3.0)
    dip.apply(cmd)
    assert cmd.view.parent is dip.fp and dip.fp.pad("2").y == 3.0


def test_invalid_value_leaves_model_and_stack(dip):
    orig = dip.fp.dumps()
    pad = dip.fp.pad("1")
    dip.apply(SetAttrCommand(dip, pad, "x", 1.0))
    dip.undo_stack.undo()
    with pytest.raises(ValueError):
        dip.apply(SetAttrCommand(dip, pad, "shape", "hexagon"))
    with pytest.raises(ValueError):
        dip.apply(SetAttrsCommand(dip, pad, {"x": 5.0, "type": "bogus"}))  # x уже присвоен
    assert dip.fp.dumps() == orig
    assert dip.undo_stack.count() == 1 and dip.undo_stack.canRedo()  # история не потеряна
    with pytest.raises(AttributeError):
        SetAttrCommand(dip, pad, "sise_x", 1.0)  # опечатка в имени свойства
    with pytest.raises(AttributeError):
        SetAttrCommand(dip, pad, "is_tht", True)  # метод, а не свойство
    with pytest.raises(ValueError):
        SetAttrCommand(dip, pad, "_parent", None)


def test_noop_command_is_not_pushed(dip):
    assert dip.apply(SetAttrCommand(dip, dip.fp.pad("1"), "x", 0.0)) is False
    assert dip.undo_stack.count() == 0 and not dip.is_modified


def test_text_hide_moves_node_and_undo_restores_it(dip):
    """Скрытие fp_text в KiCad 8+ превращает его в поле и переставляет узел — отмена точна."""
    orig = dip.fp.dumps()
    t = next(t for t in dip.fp.texts if t.node.name == "fp_text")
    node = t.node
    index = dip.fp.node.index(node)
    dip.apply(SetAttrCommand(dip, t, "hide", True))
    assert node.name == "property" and dip.fp.node.index(node) != index
    dip.undo()
    assert dip.fp.dumps() == orig and node.name == "fp_text"
    assert dip.fp.node.index(node) == index


# ---------------------------------------------------------------------------------------------
# Слияние (перетаскивание)
# ---------------------------------------------------------------------------------------------

def test_merge_drag_into_one_undo_step(dip):
    orig = dip.fp.dumps()
    pad = dip.fp.pad("1")
    mid = next_merge_id()
    for i in range(10):
        dip.apply(SetAttrsCommand(dip, pad, {"x": 0.25 * (i + 1), "y": -0.5 * (i + 1)},
                                  merge_id=mid))
    assert dip.undo_stack.count() == 1
    cmd = dip.undo_stack.command(0)
    assert cmd.old_values == {"x": 0, "y": 0}
    assert cmd.values == {"x": 2.5, "y": -5.0}
    assert dip.undo_stack.undoText() == "перемещение площадки 1"
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig
    dip.undo_stack.redo()
    assert (pad.x, pad.y) == (2.5, -5.0)


def test_merge_set_attr_with_named_id(dip):
    orig = dip.fp.dumps()
    pad = dip.fp.pad("4")
    for i in range(10):
        dip.apply(SetAttrCommand(dip, pad, "angle", 10.0 * (i + 1), merge_id="rotate-drag"))
    assert dip.undo_stack.count() == 1
    assert dip.undo_stack.command(0).old_value == 0 and pad.angle == 100
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig


def test_merge_only_same_view_attr_and_id(dip):
    p1, p2 = dip.fp.pad("1"), dip.fp.pad("2")
    mid = next_merge_id()
    dip.apply(SetAttrCommand(dip, p1, "x", 1.0, merge_id=mid))
    dip.apply(SetAttrCommand(dip, p2, "x", 1.0, merge_id=mid))      # другой элемент
    dip.apply(SetAttrCommand(dip, p2, "y", 9.0, merge_id=mid))      # другое свойство
    dip.apply(SetAttrCommand(dip, p2, "y", 8.0))                    # без merge_id
    dip.apply(SetAttrCommand(dip, p2, "y", 7.0))
    dip.apply(SetAttrCommand(dip, p2, "y", 6.0, merge_id=next_merge_id()))
    assert dip.undo_stack.count() == 6


def test_merge_back_to_start_removes_step(dip):
    orig = dip.fp.dumps()
    pad = dip.fp.pad("1")
    dip.apply(SetAttrCommand(dip, dip.fp.pad("2"), "x", 1.0))
    mid = next_merge_id()
    dip.apply(SetAttrCommand(dip, pad, "x", 3.0, merge_id=mid))
    dip.apply(SetAttrCommand(dip, pad, "x", 0.0, merge_id=mid))  # вернули на место
    assert dip.undo_stack.count() == 1
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig and not dip.is_modified


# ---------------------------------------------------------------------------------------------
# Добавление и удаление
# ---------------------------------------------------------------------------------------------

def test_remove_pad_and_undo_restores_position(dip):
    orig = dip.fp.dumps()
    root = dip.fp.node
    pad5 = dip.fp.pad("5")
    index = root.index(pad5.node)
    cmd = RemoveItemCommand(dip, pad5)
    assert dip.apply(cmd)
    assert [p.number for p in dip.fp.pads] == [str(i) for i in range(1, 15) if i != 5]
    removed = dip.fp.dumps()
    assert dip.undo_stack.undoText() == "удаление площадки 5"
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig
    assert root.items[index] is pad5.node and dip.contains(pad5)
    dip.undo_stack.redo()
    assert dip.fp.dumps() == removed and not dip.contains(pad5)


def test_add_pad_and_undo_redo_same_position(dip):
    orig = dip.fp.dumps()
    new = Pad.new("15", "smd", "rect", 3.81, 20.0, (1.0, 2.0))
    cmd = AddItemCommand(dip, new)
    assert dip.apply(cmd)
    assert cmd.item is new and new.parent is dip.fp
    root = dip.fp.node
    index = root.index(new.node)
    assert index == root.index(dip.fp.pad("14").node) + 1   # в конце группы площадок
    assert dip.fp.pads[-1] == new and dip.undo_stack.undoText() == "добавление площадки 15"
    added = dip.fp.dumps()
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig and not dip.contains(new)
    dip.undo_stack.redo()
    assert dip.fp.dumps() == added and root.items[index] is new.node


def test_add_copy_of_pad_gets_new_uuid_and_removes_cleanly(dip):
    orig = dip.fp.dumps()
    src = dip.fp.pad("1")
    dup = src.copy()
    dip.apply(AddItemCommand(dip, dup))
    assert dup.uuid != src.uuid and len(dip.fp.pads_by_number("1")) == 2
    dip.apply(RemoveItemCommand(dip, dup.node))       # удаление по узлу
    assert dip.fp.dumps() == orig
    with pytest.raises(ValueError):
        dip.apply(RemoveItemCommand(dip, dup))        # уже удалена
    with pytest.raises(ValueError):
        dip.apply(AddItemCommand(dip, src))           # уже в корпусе
    with pytest.raises(ValueError):
        RemoveItemCommand(dip, dip.fp)


def test_remove_nested_node(doc):
    """Удаление узла не из корня (примитив площадки) и точная отмена."""
    path = next(p for p in sorted((FIXTURES / "special").rglob("*.kicad_mod"))
                if "(primitives" in p.read_text(encoding="utf-8")
                and "(footprint" in p.read_text(encoding="utf-8")[:20])
    assert doc.open(path)
    orig = doc.fp.dumps()
    pad = next(p for p in doc.fp.pads if p.primitives)
    prim = pad.primitives[0]
    doc.apply(RemoveItemCommand(doc, prim))
    assert all(x is not prim for x in pad.primitives)
    doc.undo()
    assert doc.fp.dumps() == orig


# ---------------------------------------------------------------------------------------------
# ReplaceNodeCommand, OperationCommand, BatchCommand
# ---------------------------------------------------------------------------------------------

def test_replace_node_command_with_move(dip):
    orig = dip.fp.dumps()
    root = dip.fp.node
    pad1 = dip.fp.pad("1")
    before = dip.fp.node.copy()
    work = dip.fp.copy()
    work.move(1.27, -2.54)
    cmd = ReplaceNodeCommand(dip, before, work.node, "сдвиг корпуса")
    assert dip.apply(cmd)
    assert dip.fp.node is root                              # идентичность корня
    assert dip.fp.dumps() == work.dumps()
    assert dip.contains(pad1) and (pad1.x, pad1.y) == (1.27, -2.54)  # узлы переиспользованы
    assert dip.undo_stack.undoText() == "сдвиг корпуса"
    dip.undo_stack.undo()
    assert dip.fp.dumps() == orig and dip.contains(pad1) and pad1.x == 0
    dip.undo_stack.redo()
    assert dip.fp.dumps() == work.dumps()


def test_replace_node_after_direct_change(dip):
    """Живое дерево уже изменено вызывающим: отмена всё равно даёт состояние «до»."""
    orig = dip.fp.dumps()
    before = dip.fp.node.copy()
    dip.fp.rotate(90)
    after = dip.fp.node.copy()
    dip.apply(ReplaceNodeCommand(dip, before, after))
    rotated = dip.fp.dumps()
    dip.undo()
    assert dip.fp.dumps() == orig
    dip.redo()
    assert dip.fp.dumps() == rotated


def test_replace_whole_footprint_with_generated(dip):
    """Замена корпуса результатом генератора (другая структура) и перенос final_newline."""
    orig_bytes = DIP14.read_bytes()
    assert not dip.fp.final_newline
    gen = generators.dip(pins=8)
    dip.apply(ReplaceNodeCommand(dip, dip.fp.copy(), gen, "замена корпуса"))
    assert dip.fp.dumps() == gen.dumps() and dip.fp.final_newline
    assert len(dip.fp.pads) == 8 and dip.fp.name == "DIP-8_W7.62mm"
    dip.undo()
    assert dip.fp.dumps().encode("utf-8") == orig_bytes and not dip.fp.final_newline
    dip.redo()
    assert dip.fp.dumps() == gen.dumps()
    with pytest.raises(ValueError):
        dip.apply(ReplaceNodeCommand(dip, dip.fp.copy(), dip.fp.pad("1").copy()))


def test_replace_node_of_element(dip):
    orig = dip.fp.dumps()
    line = dip.fp.graphics[0]
    moved = line.copy()
    moved.move(0.5, 0.5)
    dip.apply(ReplaceNodeCommand(dip, line.node.copy(), moved.node, target=line))
    assert line.start == moved.start and dip.contains(line)
    assert dip.undo_stack.undoText() == "изменение линии"
    dip.undo()
    assert dip.fp.dumps() == orig


def test_operation_command_whole_footprint(dip):
    orig = dip.fp.dumps()
    for op, text in ((lambda fp: fp.flip(), "отражение"), (lambda fp: fp.rotate(45), "поворот"),
                     (lambda fp: fp.renumber_pads(order="circular", rule="prefix:P"),
                      "перенумерация")):
        cmd = OperationCommand(dip, op, text)
        assert dip.apply(cmd)
        after = dip.fp.dumps()
        dip.undo()
        assert dip.fp.dumps() == orig
        dip.redo()
        assert dip.fp.dumps() == after
        dip.undo()
    assert dip.fp.pad("1").number == "1"


def test_operation_error_rolls_back(dip):
    orig = dip.fp.dumps()

    def half_done(fp):
        fp.move(1, 1)
        raise RuntimeError("сбой посередине операции")

    with pytest.raises(RuntimeError):
        dip.apply(OperationCommand(dip, half_done))
    assert dip.fp.dumps() == orig and dip.undo_stack.count() == 0


def test_rect_rotation_changes_selected_view_kind(doc, qtbot):
    assert doc.open(POWERPAK)
    orig = doc.fp.dumps()
    rect = next(g for g in doc.fp.graphics if isinstance(g, Rect))
    node = rect.node
    doc.select(rect)
    doc.apply(OperationCommand(doc, lambda g: g.rotate(30), "поворот", item=rect))
    assert node.name == "fp_poly" and isinstance(doc.selected, Poly)
    with qtbot.waitSignal(doc.selection_changed) as blocker:
        doc.undo()
    assert node.name == "fp_rect" and isinstance(blocker.args[0], Rect)
    assert doc.selected.node is node and doc.fp.dumps() == orig


def test_batch_command_is_one_step(dip, qtbot):
    orig = dip.fp.dumps()
    emitted = []
    dip.changed.connect(lambda: emitted.append(1))
    kids = [SetAttrCommand(dip, p, "size", (2.0, 2.0)) for p in dip.fp.pads]
    kids.append(RemoveItemCommand(dip, dip.fp.pad("14")))
    kids.append(AddItemCommand(dip, Line.new((0, 0), (1, 1), "F.Fab", 0.1)))
    assert dip.apply(BatchCommand(kids, "групповая операция"))
    assert emitted == [1] and dip.undo_stack.count() == 1
    assert dip.undo_stack.undoText() == "групповая операция"
    after = dip.fp.dumps()
    assert len(dip.fp.pads) == 13 and all(p.size == (2, 2) for p in dip.fp.pads)
    dip.undo()
    assert dip.fp.dumps() == orig
    dip.redo()
    assert dip.fp.dumps() == after
    with pytest.raises(RuntimeError):
        dip.apply(kids[0])  # дочерние команды уже выполнены в группе


def test_batch_command_doc_first_and_rollback(dip):
    orig = dip.fp.dumps()
    kids = [SetAttrCommand(dip, dip.fp.pad("1"), "x", 5.0),
            SetAttrCommand(dip, dip.fp.pad("2"), "type", "bogus")]
    with pytest.raises(ValueError):
        dip.apply(BatchCommand(dip, kids, "ошибка"))
    assert dip.fp.dumps() == orig and dip.undo_stack.count() == 0
    one = BatchCommand(dip, [SetAttrCommand(dip, dip.fp.pad("1"), "x", 5.0)])
    assert one.actionText() == "изменение X площадки 1"
    with pytest.raises(TypeError):
        BatchCommand([])


def test_foreign_qundocommand(dip, qtbot):
    pad = dip.fp.pad("1")

    class Plain(QUndoCommand):
        def redo(self):
            pad.x = 7.0

        def undo(self):
            pad.x = 0.0

    with qtbot.waitSignal(dip.changed):
        assert dip.apply(Plain("простая команда"))
    assert pad.x == 7.0 and dip.undo_stack.count() == 1
    dip.undo()
    assert pad.x == 0


# ---------------------------------------------------------------------------------------------
# Сигналы, выделение, защита от вложенных команд
# ---------------------------------------------------------------------------------------------

def test_modified_signals(dip, qtbot):
    pad = dip.fp.pad("1")
    with qtbot.waitSignal(dip.modified_changed) as blocker:
        dip.apply(SetAttrCommand(dip, pad, "x", 1.0))
    assert blocker.args == [True] and dip.is_modified
    with qtbot.assertNotEmitted(dip.modified_changed):
        dip.apply(SetAttrCommand(dip, pad, "x", 2.0))
    dip.undo()
    with qtbot.waitSignal(dip.modified_changed) as blocker:
        dip.undo()
    assert blocker.args == [False] and not dip.is_modified
    with qtbot.waitSignals([dip.changed, dip.modified_changed]):
        dip.redo()


def test_selection(dip, qtbot):
    pad = dip.fp.pad("2")
    with qtbot.waitSignal(dip.selection_changed) as blocker:
        dip.select(pad)
    assert blocker.args[0] == pad and dip.selected == pad
    with qtbot.assertNotEmitted(dip.selection_changed):
        dip.select(dip.fp.pad("2"))      # то же самое (другое представление над тем же узлом)
    with qtbot.waitSignal(dip.selection_changed) as blocker:
        dip.apply(RemoveItemCommand(dip, pad))
    assert blocker.args == [None] and dip.selected is None
    with pytest.raises(ValueError):
        dip.select(pad)                  # элемента больше нет в корпусе
    with pytest.raises(ValueError):
        dip.select(Pad.new("99"))
    dip.undo()
    dip.select(dip.fp.pad("3").node)     # узел -> представление
    assert isinstance(dip.selected, Pad) and dip.selected.parent is dip.fp
    dip.select(dip.fp)
    assert dip.selected is dip.fp
    with qtbot.waitSignal(dip.selection_changed) as blocker:
        dip.select(None)
    assert blocker.args == [None]


def test_selection_cleared_on_open(dip, qtbot):
    dip.select(dip.fp.pad("1"))
    with qtbot.waitSignal(dip.selection_changed) as blocker:
        dip.open(POWERPAK)
    assert blocker.args == [None] and dip.selected is None


def test_nested_apply_from_changed_slot_is_refused(dip, qtbot):
    def slot():
        dip.apply(SetAttrCommand(dip, dip.fp.pad("2"), "x", 9.0))

    dip.changed.connect(slot)
    try:
        with qtbot.capture_exceptions() as exceptions:
            dip.apply(SetAttrCommand(dip, dip.fp.pad("1"), "x", 1.0))
    finally:
        dip.changed.disconnect(slot)
    assert exceptions and isinstance(exceptions[0][1], RuntimeError)
    assert dip.undo_stack.count() == 1 and dip.fp.pad("2").x == 0


def test_apply_guards(doc):
    with pytest.raises(RuntimeError):
        doc.apply(QUndoCommand("x"))                 # нет открытого корпуса
    doc.open(DIP14)
    other = FootprintDocument()
    other.open(DIP14)
    with pytest.raises(ValueError):
        doc.apply(SetAttrCommand(other, other.fp.pad("1"), "x", 1.0))
    with pytest.raises(ValueError):
        doc.apply(SetAttrCommand(doc, other.fp.pad("1"), "x", 1.0))   # чужой узел
    with pytest.raises(TypeError):
        doc.apply("не команда")                      # type: ignore[arg-type]
    with pytest.raises(TypeError):
        SetAttrCommand(object(), doc.fp.pad("1"), "x", 1.0)
    assert doc.undo_stack.count() == 0


# ---------------------------------------------------------------------------------------------
# Запись, создание, закрытие
# ---------------------------------------------------------------------------------------------

def test_save_and_save_as(doc, qtbot, tmp_path):
    lib = tmp_path / "t.pretty"
    lib.mkdir()
    dst = lib / DIP14.name
    shutil.copy(DIP14, dst)
    assert doc.open(dst) and doc.library is not None and doc.library.name == "t"
    cached = doc.library.get("DIP-14_W7.62mm")
    doc.apply(SetAttrCommand(doc, doc.fp.pad("1"), "x", 0.5))
    with qtbot.waitSignals([doc.saved, doc.modified_changed]):
        assert doc.save() is True
    assert not doc.is_modified
    assert dst.read_bytes() == doc.fp.dumps().encode("utf-8")
    assert kicadfp.load(dst).pad("1").x == 0.5
    assert doc.library.get("DIP-14_W7.62mm") is not cached   # кэш библиотеки сброшен
    # после сохранения команда не сливается с предыдущей (граница «чистого» состояния)
    mid = next_merge_id()
    doc.apply(SetAttrCommand(doc, doc.fp.pad("2"), "x", 1.0, merge_id=mid))
    doc.save()
    doc.apply(SetAttrCommand(doc, doc.fp.pad("2"), "x", 2.0, merge_id=mid))
    assert doc.undo_stack.count() == 3
    doc.undo()
    assert not doc.is_modified
    doc.undo()
    assert doc.is_modified                                  # раньше сохранённого состояния
    other = tmp_path / "other.kicad_mod"
    with qtbot.waitSignal(doc.path_changed) as blocker:
        assert doc.save_as(other)
    assert blocker.args == [other] and doc.path == other and doc.library is None
    assert not doc.is_modified and other.read_bytes() == doc.fp.dumps().encode("utf-8")
    lib2 = tmp_path / "l2.pretty"
    lib2.mkdir()
    doc.save_as(lib2 / "x.kicad_mod")
    assert doc.library is not None and doc.library.name == "l2"
    with pytest.raises(IsADirectoryError):
        doc.save_as(lib2)


def test_save_strict_refuses_invalid(dip, tmp_path):
    path = tmp_path / "bad.kicad_mod"
    assert dip.save_as(path)
    before = path.read_bytes()
    dip.apply(SetAttrCommand(dip, dip.fp.pad("1"), "drill", 3.0))  # отверстие больше площадки
    with pytest.raises(ValidationError):
        dip.save(strict=True)
    assert path.read_bytes() == before and dip.is_modified
    assert dip.save()                                               # без проверки — пишется
    assert not dip.is_modified


def test_new_and_generated_footprints(doc, qtbot):
    with qtbot.waitSignals([doc.document_changed, doc.changed]):
        assert doc.new_footprint("test_fp")
    assert doc.fp.name == "test_fp" and doc.fp.version == 20241229
    assert doc.path is None and doc.library is None and not doc.is_modified
    assert doc.save() is False                   # нет пути — нужен save_as
    gen = generators.lab_dip14()
    with qtbot.waitSignal(doc.modified_changed) as blocker:
        assert doc.open_footprint(gen)           # корпус из памяти — несохранённый
    assert blocker.args == [True] and doc.fp is gen and len(doc.fp.pads) == 14
    doc.confirm_discard = False
    assert doc.new_footprint("x") is False and doc.fp is gen
    with pytest.raises(TypeError):
        doc.open_footprint("не корпус")          # type: ignore[arg-type]


def test_close_asks_confirmation(dip, qtbot):
    asked: list[int] = []
    assert dip.close() is True and dip.fp is None     # без изменений — не спрашивает
    dip.open(DIP14)
    dip.apply(SetAttrCommand(dip, dip.fp.pad("1"), "x", 1.0))
    dip.confirm_discard = lambda: asked.append(1) or False
    assert dip.close() is False and asked == [1]
    assert dip.fp is not None and dip.is_modified
    assert dip.open(POWERPAK) is False and dip.fp.name == "DIP-14_W7.62mm"
    dip.confirm_discard = False
    assert dip.close() is False
    dip.confirm_discard = True
    with qtbot.waitSignals([dip.document_changed, dip.modified_changed, dip.changed]):
        assert dip.close() is True
    assert dip.fp is None and dip.path is None and not dip.is_modified
    assert dip.undo_stack.count() == 0
    with pytest.raises(TypeError):
        dip.confirm_discard = "да"                    # type: ignore[assignment]


def test_set_path(dip, qtbot, tmp_path):
    new = tmp_path / "renamed.kicad_mod"
    with qtbot.waitSignal(dip.path_changed):
        dip.set_path(new)
    assert dip.path == new and dip.library is None and not dip.is_modified


# ---------------------------------------------------------------------------------------------
# Точная отмена на файлах всех версий
# ---------------------------------------------------------------------------------------------

EDIT_FILES = [
    FIXTURES / "kicad5" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod",
    FIXTURES / "kicad6" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod",
    DIP14,
    POWERPAK,
    FIXTURES / "kicad9" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod",
    FIXTURES / "kicad10dev" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod",
]


def _edits(doc: FootprintDocument) -> list:
    """Команды-правки разных видов (каждая строится по текущему состоянию)."""
    fp = doc.fp

    def first(seq):
        return seq[0] if seq else None

    out = [
        lambda: SetAttrsCommand(doc, fp.pads[0], {"x": fp.pads[0].x + 0.5,
                                                 "y": fp.pads[0].y - 0.25}),
        lambda: SetAttrCommand(doc, fp.pads[-1], "size_x", fp.pads[-1].size_x + 0.1),
        lambda: SetAttrCommand(doc, fp.pads[1], "shape",
                               "rect" if fp.pads[1].shape != "rect" else "oval"),
        lambda: SetAttrCommand(doc, fp.reference, "y", fp.reference.y + 1),
        lambda: SetAttrCommand(doc, fp.value, "hide", True),
        lambda: SetAttrCommand(doc, first([g for g in fp.graphics if g.width]), "width", 0.2),
        lambda: SetAttrCommand(doc, fp, "descr", "описание — правка"),
        lambda: RemoveItemCommand(doc, fp.graphics[-1]),
        lambda: AddItemCommand(doc, Line.new((-1, -1), (1, 1), "F.SilkS", 0.12)),
        lambda: AddItemCommand(doc, Text.new("метка", "user", 1.0, 2.0, "F.Fab")),
        lambda: OperationCommand(doc, lambda f: f.move(0.1, 0.2), "сдвиг"),
        lambda: OperationCommand(doc, lambda f: f.rotate(90), "поворот"),
        lambda: OperationCommand(doc, lambda f: f.flip(), "отражение"),
        lambda: OperationCommand(doc, lambda g: g.move(0.3, 0), item=fp.graphics[0]),
        lambda: BatchCommand([SetAttrCommand(doc, p, "angle", 45.0) for p in fp.pads]),
        lambda: RemoveItemCommand(doc, fp.pads[2]),
    ]
    return out


@pytest.mark.parametrize("path", EDIT_FILES, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_edit_sequence_undo_redo_exact(doc, path):
    assert doc.open(path)
    states = [doc.fp.dumps()]
    applied = 0
    for make in _edits(doc):
        try:
            cmd = make()
            ok = doc.apply(cmd)
        except ValueError:
            assert doc.fp.dumps() == states[-1]      # отказ не меняет модель
            continue
        if ok:
            applied += 1
            states.append(doc.fp.dumps())
    assert applied >= 12
    assert doc.undo_stack.count() == applied
    for i in range(applied):
        doc.undo()
        assert doc.fp.dumps() == states[-2 - i]
    assert doc.fp.dumps().encode("utf-8") == path.read_bytes()
    for i in range(applied):
        doc.redo()
        assert doc.fp.dumps() == states[i + 1]


# ---------------------------------------------------------------------------------------------
# Тексты команд
# ---------------------------------------------------------------------------------------------

def test_command_texts(dip):
    fp = dip.fp
    assert describe_item(fp.pad("1")) == "площадки 1"
    assert describe_item(fp.graphics[0]) == "линии"
    assert describe_item(fp.reference) == "текста «REF**»"
    assert describe_item(fp) == "корпуса DIP-14_W7.62mm"
    cmd = SetAttrsCommand(dip, fp.pad("1"), {"size_x": 2, "size_y": 2})
    assert cmd.actionText() == "изменение размера X и размера Y площадки 1"
    assert SetAttrCommand(dip, fp, "descr", "x").actionText() == \
        "изменение описания корпуса DIP-14_W7.62mm"
    assert SetAttrCommand(dip, fp.pad("1"), "x", 1, text="Сдвиг площадки").actionText() == \
        "сдвиг площадки"
    assert RemoveItemCommand(dip, fp.graphics[0]).text() == "Удаление линии"
    assert isinstance(cmd, DocumentCommand) and not cmd.executed


def test_undo_action_text_is_russian(dip, qapp):
    gui_app.create_app()
    undo_action = dip.undo_stack.createUndoAction(None)
    dip.apply(SetAttrCommand(dip, dip.fp.pad("1"), "x", 1.0))
    assert undo_action.text() == "Отменить изменение X площадки 1"


# ---------------------------------------------------------------------------------------------
# Приложение и main()
# ---------------------------------------------------------------------------------------------

def test_create_app_settings(qapp):
    app = gui_app.create_app()
    assert app is QApplication.instance() and gui_app.create_app() is app
    assert app.applicationName() == "kicadfp" and app.organizationName() == "kicadfp"
    assert app.applicationVersion() == kicadfp.__version__
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Отмена"
    assert QCoreApplication.translate("QPlatformTheme", "Discard") == "Не сохранять"
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                           | QDialogButtonBox.StandardButton.Discard
                           | QDialogButtonBox.StandardButton.Cancel)
    assert {b.text() for b in box.buttons()} == {"Сохранить", "Не сохранять", "Отмена"}
    assert QLocale().decimalPoint() == "." and QLocale().toString(1234.5, "f", 1) == "1234.5"
    assert not app.windowIcon().isNull()
    assert app.style().name().lower() == "fusion"


def test_palette_and_theme(qapp, monkeypatch):
    dark = gui_app.make_palette("dark")
    light = gui_app.make_palette("light")
    assert dark.color(QPalette.ColorRole.Window).lightness() < 80
    assert light.color(QPalette.ColorRole.Window).lightness() > 180
    assert gui_app.resolve_theme("dark") == "dark"
    monkeypatch.setenv("KICADFP_THEME", "light")
    assert gui_app.resolve_theme() == "light"
    with pytest.raises(ValueError):
        gui_app.resolve_theme("pink")
    assert gui_app.resolve_theme("auto") in ("light", "dark")


def _fake_mainwindow(monkeypatch, cls) -> None:
    fake = types.ModuleType("kicadfp.gui.mainwindow")
    fake.MainWindow = cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kicadfp.gui.mainwindow", fake)
    monkeypatch.setattr(QApplication, "exec", lambda *a, **k: 0)


def test_main_opens_paths_in_window(qapp, monkeypatch, capsys, tmp_path):
    windows: list = []

    class FakeWindow:
        def __init__(self):
            self.opened: list[Path] = []
            self.shown = False
            windows.append(self)

        def open_path(self, path):
            self.opened.append(Path(path))

        def show(self):
            self.shown = True

    _fake_mainwindow(monkeypatch, FakeWindow)
    missing = tmp_path / "нет.kicad_mod"
    assert gui_main([str(DIP14), str(missing), str(DIP14.parent)]) == 0
    (w,) = windows
    assert w.shown and w.opened == [DIP14, DIP14.parent]
    assert "не найден" in capsys.readouterr().err


def test_main_falls_back_to_window_document(qapp, monkeypatch, capsys):
    docs: list[FootprintDocument] = []

    class DocWindow:
        def __init__(self):
            self.document = FootprintDocument()
            docs.append(self.document)

        def show(self):
            pass

    _fake_mainwindow(monkeypatch, DocWindow)
    bad = FIXTURES / "legacy_mod" / "My_lib.mod"
    assert gui_main([str(DIP14), str(bad)]) == 0
    assert docs[0].path == DIP14                   # второй путь не открылся, окно работает
    assert "My_lib.mod" in capsys.readouterr().err


def test_main_without_mainwindow(qapp, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "kicadfp.gui.mainwindow", None)
    assert gui_main([]) == 2
    assert "главное окно" in capsys.readouterr().err


def test_main_help(capsys):
    assert gui_main(["--help"]) == 0
    assert "kicadfp-gui" in capsys.readouterr().out


def test_gui_package_import_does_not_load_pyside6():
    code = ("import sys\n"
            "import kicadfp.gui as g\n"
            "assert 'PySide6' not in sys.modules, 'PySide6 загружен при импорте'\n"
            "sys.modules['PySide6'] = None\n"
            "sys.exit(g.main([]))\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 2, r.stderr
    assert "pip install kicadfp[gui]" in r.stderr


def test_lazy_exports():
    import kicadfp.gui as g

    assert g.FootprintDocument is FootprintDocument and g.SetAttrCommand is SetAttrCommand
    with pytest.raises(AttributeError):
        g.NoSuchThing  # noqa: B018
