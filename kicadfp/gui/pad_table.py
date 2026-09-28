"""Таблица площадок корпуса: :class:`PadTableModel` (``QAbstractTableModel``) и
:class:`PadTable` (``QTableView``).

Модель — представление над ``doc.fp.pads``: строки — площадки в порядке файла, данные
читаются из модели kicadfp при каждом обращении (``data()``), копий значений таблица не
хранит — только список представлений :class:`~kicadfp.model.Pad`, пересобираемый по
сигналу ``doc.changed()``. Правка ячейки (``setData``) превращается в команду
:class:`~kicadfp.gui.commands.SetAttrCommand`/:class:`~kicadfp.gui.commands.SetAttrsCommand`
и выполняется через :meth:`FootprintDocument.apply
<kicadfp.gui.document.FootprintDocument.apply>`; недопустимый ввод отклоняется
(``setData`` возвращает ``False``, модель не меняется, испускается сигнал ``error``).

Столбцы: «№», «Тип», «Форма», «X», «Y», «Поворот», «Размер X», «Размер Y», «Отверстие»,
«Слои». Отверстие: пусто — нет отверстия, ``0.8`` — круглое, ``1.2 x 0.8`` — овальное
(разделитель ``x``, ``х``, ``×`` или ``*``). Слои — через запятую (``*.Cu, *.Mask``).

Здесь же — общие части таблиц документа (используются и
:mod:`kicadfp.gui.items_table`): :class:`DocumentTableModel`, :class:`DocumentTableView`,
делегат :class:`ComboBoxDelegate`, разбор чисел :func:`parse_number` и вывод
:func:`format_mm`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from PySide6.QtCore import (QAbstractTableModel, QItemSelectionModel,
                            QModelIndex, QObject, QPersistentModelIndex, Qt, Signal)
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QApplication,
                               QComboBox, QHeaderView, QMenu,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableView, QWidget)

from .. import layers as _layers
from ..model import PAD_SHAPES, PAD_TYPES, Pad, View
from ..sexpr import format_number
from .commands import (AddItemCommand, BatchCommand, RemoveItemCommand, SetAttrCommand,
                       SetAttrsCommand, describe_item)

__all__ = [
    "PadTableModel", "PadTable", "PAD_COLUMNS", "LAYER_PRESET_TEXTS",
    "COL_NUMBER", "COL_TYPE", "COL_SHAPE", "COL_X", "COL_Y", "COL_ANGLE", "COL_SIZE_X",
    "COL_SIZE_Y", "COL_DRILL", "COL_LAYERS",
    "DocumentTableModel", "DocumentTableView", "ComboBoxDelegate",
    "parse_number", "format_mm", "format_pair", "parse_pair", "parse_layers",
]

# ---------------------------------------------------------------------------------------------
# Разбор и вывод значений
# ---------------------------------------------------------------------------------------------

_PAIR_SPLIT = re.compile(r"\s*[xXхХ×*]\s*")
_LAYER_SPLIT = re.compile(r"[,;\s]+")


def format_mm(value: float | None) -> str:
    """Число в записи KiCad (``1.27``, ``0``, без экспоненты); ``None`` — пустая строка."""
    if value is None:
        return ""
    return format_number(float(value))


def format_pair(a: float, b: float) -> str:
    """Пара размеров: ``"1.2 x 0.8"`` (при равенстве — одно число)."""
    return format_mm(a) if a == b else f"{format_mm(a)} x {format_mm(b)}"


def parse_number(value: Any, what: str = "значение", *, minimum: float | None = None,
                 strict_minimum: bool = False) -> float:
    """Разобрать ввод пользователя как конечное число (``float``).

    Принимает число или строку (десятичная точка или запятая, ``−`` как минус). Пустая
    строка, не-число, ``nan``/``inf``, значение меньше ``minimum`` (``strict_minimum`` —
    меньше или равное) — ``ValueError`` с русским сообщением."""
    if isinstance(value, bool):
        raise ValueError(f"{what}: ожидается число")
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value).strip().replace(",", ".").replace("−", "-")
        if not s:
            raise ValueError(f"{what}: введите число")
        try:
            v = float(s)
        except ValueError:
            raise ValueError(f"{what}: «{value}» — не число") from None
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{what}: число должно быть конечным")
    if minimum is not None:
        if strict_minimum and v <= minimum:
            raise ValueError(f"{what}: значение должно быть больше {format_mm(minimum)}")
        if not strict_minimum and v < minimum:
            raise ValueError(f"{what}: значение должно быть не меньше {format_mm(minimum)}")
    return v


def parse_pair(value: Any, what: str, *, positive: bool = True) -> float | tuple[float, float]:
    """Разобрать ``"a"`` (число) или ``"a x b"`` (пара). Значения должны быть положительны
    (``positive``)."""
    if isinstance(value, (tuple, list)):
        parts: list[Any] = list(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parts = [value]
    else:
        s = str(value).strip()
        parts = [p for p in _PAIR_SPLIT.split(s)] if s else [""]
    if len(parts) not in (1, 2):
        raise ValueError(f"{what}: ожидается «число» или «ширина x высота»")
    nums = [parse_number(p, what, minimum=0.0 if positive else None, strict_minimum=positive)
            for p in parts]
    return nums[0] if len(nums) == 1 else (nums[0], nums[1])


def parse_layers(value: Any, what: str = "слои") -> list[str]:
    """Список слоёв из строки через запятую (или пробел/точку с запятой) либо из списка.
    Неизвестный слой или пустой список — ``ValueError``; повторы убираются."""
    if isinstance(value, str):
        names = [n for n in _LAYER_SPLIT.split(value.strip()) if n]
    elif isinstance(value, Iterable):
        names = [str(n).strip() for n in value if str(n).strip()]
    else:
        raise ValueError(f"{what}: ожидается список слоёв через запятую")
    out: list[str] = []
    for n in names:
        if not _layers.is_valid_layer(n):
            raise ValueError(f"{what}: неизвестный слой «{n}»")
        if n not in out:
            out.append(n)
    if not out:
        raise ValueError(f"{what}: укажите хотя бы один слой")
    return out


# ---------------------------------------------------------------------------------------------
# Делегат-список
# ---------------------------------------------------------------------------------------------

class ComboBoxDelegate(QStyledItemDelegate):
    """Делегат с выпадающим списком ``items`` (последовательность строк или функция без
    аргументов, возвращающая её). ``editable=True`` — список пресетов плюс свободный ввод.
    Значение передаётся в модель строкой (``setData(index, текст, EditRole)``)."""

    def __init__(self, items: Sequence[str] | Callable[[], Sequence[str]],
                 parent: QObject | None = None, *, editable: bool = False) -> None:
        super().__init__(parent)
        self._items = items
        self._editable = editable

    def items(self) -> list[str]:
        """Текущие пункты списка."""
        src = self._items() if callable(self._items) else self._items
        return [str(s) for s in src]

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem,  # noqa: N802
                     index: QModelIndex | QPersistentModelIndex) -> QWidget:
        combo = QComboBox(parent)
        combo.setEditable(self._editable)
        combo.addItems(self.items())
        if self._editable:
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        else:
            # выбор из списка сразу применяется (без лишнего щелчка вне редактора)
            def commit(_: int, c: QComboBox = combo) -> None:
                self.commitData.emit(c)
                self.closeEditor.emit(c, QStyledItemDelegate.EndEditHint.NoHint)
            combo.activated.connect(commit)
        return combo

    def setEditorData(self, editor: QWidget,  # noqa: N802
                      index: QModelIndex | QPersistentModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            super().setEditorData(editor, index)
            return
        text = index.data(Qt.ItemDataRole.EditRole)
        text = "" if text is None else str(text)
        i = editor.findText(text)
        if i >= 0:
            editor.setCurrentIndex(i)
        elif editor.isEditable():
            editor.setEditText(text)

    def setModelData(self, editor: QWidget, model: Any,  # noqa: N802
                     index: QModelIndex | QPersistentModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            super().setModelData(editor, model, index)
            return
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


# ---------------------------------------------------------------------------------------------
# Общая модель и таблица документа
# ---------------------------------------------------------------------------------------------

def _node_key(item: Any) -> int:
    return id(item.node if isinstance(item, View) else item)


class DocumentTableModel(QAbstractTableModel):
    """Базовая табличная модель над списком элементов открытого корпуса.

    Наследник задаёт :attr:`HEADERS` и :meth:`_collect` (список представлений в порядке
    строк). Список пересобирается по ``doc.changed()``: если набор узлов и их порядок не
    изменились — испускается ``dataChanged`` по всей таблице (выделение и текущая ячейка
    сохраняются), иначе модель сбрасывается (``modelReset``). ``doc.document_changed()`` —
    всегда сброс. Сигнал :attr:`error` — сообщение об отклонённом вводе."""

    HEADERS: tuple[str, ...] = ()
    #: Отклонённый ввод или ошибка команды: текст для строки состояния.
    error = Signal(str)

    def __init__(self, doc: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._rows: list[Any] = self._collect()
        doc.changed.connect(self._on_changed)
        doc.document_changed.connect(self._on_document_changed)

    # --- переопределяемое --------------------------------------------------------------------
    def _collect(self) -> list[Any]:
        raise NotImplementedError

    # --- доступ --------------------------------------------------------------------------------
    @property
    def document(self) -> Any:
        """Документ :class:`~kicadfp.gui.document.FootprintDocument`."""
        return self._doc

    def items(self) -> list[Any]:
        """Элементы в порядке строк (представления над узлами корпуса)."""
        return list(self._rows)

    def item_at(self, row: int | QModelIndex | QPersistentModelIndex) -> Any:
        """Элемент строки (``None`` — строки нет)."""
        if not isinstance(row, int):
            if not row.isValid():
                return None
            row = row.row()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def row_of(self, item: Any) -> int:
        """Строка элемента (по идентичности узла); -1 — нет в таблице."""
        if item is None:
            return -1
        try:
            key = _node_key(item)
        except AttributeError:
            return -1
        for i, v in enumerate(self._rows):
            if id(v.node) == key:
                return i
        return -1

    # --- обновление ---------------------------------------------------------------------------
    def _on_changed(self) -> None:
        new = self._collect()
        if [id(v.node) for v in new] == [id(v.node) for v in self._rows]:
            self._rows = new  # представления могли сменить класс (fp_rect -> fp_poly)
            if new:
                self.dataChanged.emit(self.index(0, 0),
                                      self.index(len(new) - 1, self.columnCount() - 1))
            return
        self.beginResetModel()
        self._rows = new
        self.endResetModel()

    def _on_document_changed(self) -> None:
        self.beginResetModel()
        self._rows = self._collect()
        self.endResetModel()

    # --- QAbstractTableModel ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
            return str(section + 1)
        return None

    # --- команды ------------------------------------------------------------------------------
    def _apply(self, cmd: Any) -> bool:
        """Выполнить команду; ошибка модели — ``False`` и сигнал :attr:`error`."""
        try:
            self._doc.apply(cmd)
        except (ValueError, TypeError, AttributeError) as e:
            self.error.emit(str(e))
            return False
        return True

    def _reject(self, message: str) -> bool:
        self.error.emit(message)
        return False


class DocumentTableView(QTableView):
    """Базовая таблица элементов документа: сортировка выключена, выделение строками;
    выбор строки — :meth:`doc.select() <kicadfp.gui.document.FootprintDocument.select>`,
    ``doc.selection_changed`` — выделение строки элемента (или снятие выделения)."""

    def __init__(self, doc: Any, model: DocumentTableModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._syncing = False
        self.setModel(model)
        self.setSortingEnabled(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 8)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.selectionModel().selectionChanged.connect(self._on_view_selection)
        self.selectionModel().currentRowChanged.connect(self._on_current_row)
        model.modelReset.connect(self._after_reset)
        doc.selection_changed.connect(self._on_doc_selection)

    @property
    def document(self) -> Any:
        """Документ таблицы."""
        return self._doc

    def table_model(self) -> DocumentTableModel:
        """Модель таблицы."""
        m = self.model()
        assert isinstance(m, DocumentTableModel)
        return m

    def selected_rows(self) -> list[int]:
        """Выделенные строки по возрастанию."""
        return sorted({i.row() for i in self.selectionModel().selectedRows()})

    def selected_items(self) -> list[Any]:
        """Выделенные элементы в порядке строк."""
        m = self.table_model()
        return [m.item_at(r) for r in self.selected_rows() if m.item_at(r) is not None]

    def select_item(self, item: Any) -> bool:
        """Выделить строку элемента в таблице (и в документе). ``False`` — элемента нет."""
        row = self.table_model().row_of(item)
        if row < 0:
            return False
        self.selectRow(row)
        return True

    # --- синхронизация выделения ---------------------------------------------------------------
    def _push_selection(self) -> None:
        if self._syncing or self._doc.fp is None:
            return
        m = self.table_model()
        rows = self.selected_rows()
        cur = self.currentIndex()
        item = None
        if cur.isValid() and cur.row() in rows:
            item = m.item_at(cur.row())
        elif rows:
            item = m.item_at(rows[0])
        if item is None:
            if m.row_of(self._doc.selected) >= 0:
                self._doc.select(None)  # снято выделение элемента этой таблицы
            return
        try:
            self._doc.select(item)
        except ValueError:
            pass

    def _on_view_selection(self, *_: Any) -> None:
        self._push_selection()

    def _on_current_row(self, *_: Any) -> None:
        self._push_selection()

    def _on_doc_selection(self, item: Any) -> None:
        if self._syncing:
            return
        m = self.table_model()
        row = m.row_of(item)
        sm = self.selectionModel()
        self._syncing = True
        try:
            if row < 0:
                if sm.hasSelection():
                    sm.clearSelection()
                return
            if row in self.selected_rows():
                return  # уже выделена (возможно, вместе с другими строками)
            idx = m.index(row, max(0, self.currentIndex().column()))
            flags = (QItemSelectionModel.SelectionFlag.ClearAndSelect
                     | QItemSelectionModel.SelectionFlag.Rows)
            sm.setCurrentIndex(idx, flags)
            self.scrollTo(idx)
        finally:
            self._syncing = False

    def _after_reset(self) -> None:
        self._on_doc_selection(self._doc.selected)

    # --- незавершённый ввод ---------------------------------------------------------------------
    def open_editor(self) -> QWidget | None:
        """Открытый редактор ячейки (``None`` — ячейка не редактируется)."""
        if self.state() != QAbstractItemView.State.EditingState:
            return None
        editor = self.indexWidget(self.currentIndex())
        if editor is not None:
            return editor
        focus = QApplication.focusWidget()
        vp = self.viewport()
        while focus is not None:
            if focus.parentWidget() is vp:
                return focus
            focus = focus.parentWidget()
        return None

    def commit_pending_edit(self) -> bool:
        """Применить значение открытого редактора ячейки (как Enter) и закрыть его.
        ``True`` — редактор был открыт."""
        editor = self.open_editor()
        if editor is None:
            return False
        self.commitData(editor)
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        return True


# ---------------------------------------------------------------------------------------------
# Площадки
# ---------------------------------------------------------------------------------------------

COL_NUMBER, COL_TYPE, COL_SHAPE, COL_X, COL_Y, COL_ANGLE, COL_SIZE_X, COL_SIZE_Y, \
    COL_DRILL, COL_LAYERS = range(10)

#: Заголовки столбцов таблицы площадок.
PAD_COLUMNS: tuple[str, ...] = ("№", "Тип", "Форма", "X", "Y", "Поворот", "Размер X",
                                "Размер Y", "Отверстие", "Слои")

_TOOLTIPS: dict[int, str] = {
    COL_NUMBER: "Номер площадки (пусто — монтажное отверстие)",
    COL_TYPE: "Тип: thru_hole, smd, connect, np_thru_hole",
    COL_SHAPE: "Форма площадки",
    COL_X: "X центра, мм", COL_Y: "Y центра, мм (ось Y вниз)",
    COL_ANGLE: "Поворот, градусы",
    COL_SIZE_X: "Размер по X, мм", COL_SIZE_Y: "Размер по Y, мм",
    COL_DRILL: "Отверстие, мм: пусто — нет, «0.8» — круглое, «1.2 x 0.8» — овальное",
    COL_LAYERS: "Слои через запятую (например, «*.Cu, *.Mask»)",
}

_NUMERIC_ATTRS: dict[int, tuple[str, str]] = {
    COL_X: ("x", "X"), COL_Y: ("y", "Y"), COL_ANGLE: ("angle", "поворот"),
    COL_SIZE_X: ("size_x", "размер X"), COL_SIZE_Y: ("size_y", "размер Y"),
}


def _preset_texts() -> list[str]:
    out: list[str] = []
    for names in _layers.PAD_LAYER_PRESETS.values():
        s = ", ".join(names)
        if s not in out:
            out.append(s)
    return out


#: Пункты списка пресетов слоёв (свободный ввод тоже допускается).
LAYER_PRESET_TEXTS: list[str] = _preset_texts()

#: Отверстие по умолчанию при смене типа на сквозной (доля меньшего размера площадки).
_DEFAULT_DRILL_RATIO = 0.5


def _preset_key(layer_names: Iterable[str]) -> str | None:
    """Ключ пресета :data:`kicadfp.layers.PAD_LAYER_PRESETS` с тем же набором слоёв."""
    s = set(layer_names)
    for key, names in _layers.PAD_LAYER_PRESETS.items():
        if set(names) == s:
            return key
    return None


def _drill_text(pad: Pad) -> str:
    d = pad.drill
    if d is None:
        return ""
    if d.oval:
        w, h = d.size
        return f"{format_mm(w)} x {format_mm(h)}"
    return "" if d.diameter == 0 else format_mm(d.diameter)


def _drill_value(pad: Pad) -> float | tuple[float, float] | None:
    d = pad.drill
    if d is None:
        return None
    if d.oval:
        return d.size
    return None if d.diameter == 0 else d.diameter


class PadTableModel(DocumentTableModel):
    """Модель таблицы площадок над ``doc.fp.pads`` (см. модуль).

    Роли: ``DisplayRole``/``EditRole`` — текст ячейки, ``ToolTipRole`` — подсказка,
    ``UserRole`` — само представление :class:`~kicadfp.model.Pad`. ``setData(index, значение)``
    принимает строку (как ввёл пользователь) или число/список; возвращает ``False`` при
    недопустимом вводе (модель не меняется)."""

    HEADERS = PAD_COLUMNS

    def _collect(self) -> list[Pad]:
        fp = self._doc.fp
        return [] if fp is None else fp.pads

    def pad_at(self, row: int) -> Pad | None:
        """Площадка строки (``None`` — нет строки)."""
        return self.item_at(row)

    # --- чтение ---------------------------------------------------------------------------------
    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            return _TOOLTIPS.get(section)
        return super().headerData(section, orientation, role)

    def text(self, pad: Pad, column: int) -> str:
        """Текст ячейки площадки ``pad`` в столбце ``column``."""
        if column == COL_NUMBER:
            return pad.number
        if column == COL_TYPE:
            return pad.type
        if column == COL_SHAPE:
            return pad.shape
        if column in _NUMERIC_ATTRS:
            return format_mm(getattr(pad, _NUMERIC_ATTRS[column][0]))
        if column == COL_DRILL:
            return _drill_text(pad)
        if column == COL_LAYERS:
            return ", ".join(pad.layers)
        return ""

    def data(self, index: QModelIndex | QPersistentModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        pad = self.item_at(index)
        if pad is None:
            return None
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            try:
                return self.text(pad, col)
            except Exception:  # noqa: BLE001 — узел необычной формы не должен ронять таблицу
                return "?"
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{describe_item(pad)}: {_TOOLTIPS.get(col, '')}"
        if role == Qt.ItemDataRole.TextAlignmentRole and (col in _NUMERIC_ATTRS
                                                          or col == COL_DRILL):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return pad
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsEditable)

    # --- запись ---------------------------------------------------------------------------------
    def setData(self, index: QModelIndex | QPersistentModelIndex, value: Any,  # noqa: N802
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole:
            return False
        pad = self.item_at(index)
        if pad is None or self._doc.fp is None:
            return False
        try:
            change = self._change_for(pad, index.column(), value)
        except (ValueError, TypeError) as e:
            return self._reject(str(e))
        if change is None:
            return True  # значение не изменилось
        values, text = change
        if len(values) == 1:
            (attr, v), = values.items()
            cmd: Any = SetAttrCommand(self._doc, pad, attr, v, text)
        else:
            cmd = SetAttrsCommand(self._doc, pad, values, text)
        return self._apply(cmd)

    def _change_for(self, pad: Pad, col: int,
                    value: Any) -> tuple[dict[str, Any], str | None] | None:
        """Свойства для присваивания по вводу ``value`` в столбце ``col`` (``None`` — нечего
        менять); ``ValueError`` — недопустимый ввод."""
        if col == COL_NUMBER:
            s = "" if value is None else str(value).strip()
            return None if s == pad.number else ({"number": s}, None)
        if col == COL_TYPE:
            return self._type_change(pad, str(value).strip())
        if col == COL_SHAPE:
            s = str(value).strip()
            if s not in PAD_SHAPES:
                raise ValueError(f"форма: недопустимое значение «{s}» "
                                 f"(допустимо: {', '.join(PAD_SHAPES)})")
            return None if s == pad.shape else ({"shape": s}, None)
        if col in _NUMERIC_ATTRS:
            attr, what = _NUMERIC_ATTRS[col]
            size = attr.startswith("size")
            v = parse_number(value, what, minimum=0.0 if size else None, strict_minimum=size)
            return None if v == getattr(pad, attr) else ({attr: v}, None)
        if col == COL_DRILL:
            if isinstance(value, (tuple, list, int, float)) and not isinstance(value, bool):
                new: Any = parse_pair(value, "отверстие")
            else:
                s = "" if value is None else str(value).strip()
                new = None if not s else parse_pair(s, "отверстие")
            if new == _drill_value(pad) or (new is None and pad.drill is None):
                return None
            return {"drill": new}, None
        if col == COL_LAYERS:
            names = parse_layers(value)
            if set(names) == set(pad.layers):
                return None  # тот же набор слоёв: порядок записи в файле не трогаем
            key = _preset_key(names)
            if key is not None:
                names = self._preset_layers(pad, key)
            return None if names == pad.layers else ({"layers": names}, None)
        raise ValueError("столбец не редактируется")

    def _preset_layers(self, pad: Pad, key: str) -> list[str]:
        """Слои пресета ``key`` в порядке записи KiCad версии файла (как ``set_layers``)."""
        tmp = Pad(pad.node.copy(), None, self._doc.fp)
        tmp.set_layers(key)
        return tmp.layers

    def _type_change(self, pad: Pad, new_type: str) -> tuple[dict[str, Any], str] | None:
        """Смена типа площадки как в диалоге KiCad: слои — пресет нового типа (если текущие
        слои совпадали с каким-либо пресетом; сторона сохраняется), у ``smd``/``connect``
        отверстие удаляется, у сквозной площадки без отверстия оно создаётся (половина
        меньшего размера)."""
        if new_type not in PAD_TYPES:
            raise ValueError(f"тип: недопустимое значение «{new_type}» "
                             f"(допустимо: {', '.join(PAD_TYPES)})")
        if new_type == pad.type:
            return None
        values: dict[str, Any] = {"type": new_type}
        cur_layers = pad.layers
        old_key = _preset_key(cur_layers) if cur_layers else pad.type
        if old_key is not None:
            back = old_key.endswith("_back")
            key = f"{new_type}_back" if back and f"{new_type}_back" in _layers.PAD_LAYER_PRESETS \
                else new_type
            if key in _layers.PAD_LAYER_PRESETS:
                names = self._preset_layers(pad, key)
                if names != cur_layers:
                    values["layers"] = names
        if new_type in ("smd", "connect"):
            if pad.drill is not None:
                values["drill"] = None
        elif pad.drill is None or _drill_value(pad) is None:
            d = round(min(pad.size_x, pad.size_y) * _DEFAULT_DRILL_RATIO, 2)
            values["drill"] = d if d > 0 else 0.8
        return values, f"изменение типа {describe_item(pad)}"


class PadTable(DocumentTableView):
    """Таблица площадок (``QTableView`` над :class:`PadTableModel`).

    Сортировка выключена (порядок строк — порядок в файле). Выбор строки выделяет
    площадку в документе; выделение в документе (канва, проверка) выделяет строку.
    Контекстное меню (:meth:`context_menu`): «Добавить площадку» (:meth:`add_pad`),
    «Дублировать» (:meth:`duplicate_selected`), «Удалить» (:meth:`remove_selected`),
    «Групповые операции…» — сигнал :attr:`batch_requested` со списком выделенных площадок
    (пустой список — все площадки; диалог открывает главное окно)."""

    #: Запрошены групповые операции над площадками (список :class:`~kicadfp.model.Pad`).
    batch_requested = Signal(list)

    #: Сдвиг новой площадки относительно исходной при добавлении и дублировании, мм.
    ADD_OFFSET = (0.0, 2.54)
    DUPLICATE_OFFSET = (2.54, 0.0)

    def __init__(self, doc: Any, parent: QWidget | None = None) -> None:
        super().__init__(doc, PadTableModel(doc), parent)
        self.model().setParent(self)
        self.setItemDelegateForColumn(COL_TYPE, ComboBoxDelegate(PAD_TYPES, self))
        self.setItemDelegateForColumn(COL_SHAPE, ComboBoxDelegate(PAD_SHAPES, self))
        self.setItemDelegateForColumn(COL_LAYERS,
                                      ComboBoxDelegate(LAYER_PRESET_TEXTS, self, editable=True))
        self.act_add = QAction("Добавить площадку", self)
        self.act_add.triggered.connect(self.add_pad)
        self.act_duplicate = QAction("Дублировать", self)
        self.act_duplicate.triggered.connect(self.duplicate_selected)
        self.act_remove = QAction("Удалить", self)
        self.act_remove.triggered.connect(self.remove_selected)
        self.act_batch = QAction("Групповые операции…", self)
        self.act_batch.triggered.connect(self.request_batch)
        for col, w in ((COL_NUMBER, 50), (COL_TYPE, 100), (COL_SHAPE, 90), (COL_DRILL, 90)):
            self.setColumnWidth(col, w)
        for col in (COL_X, COL_Y, COL_ANGLE, COL_SIZE_X, COL_SIZE_Y):
            self.setColumnWidth(col, 70)

    def pad_model(self) -> PadTableModel:
        """Модель площадок."""
        m = self.model()
        assert isinstance(m, PadTableModel)
        return m

    def selected_pads(self) -> list[Pad]:
        """Выделенные площадки в порядке строк."""
        return self.selected_items()

    # --- контекстное меню -----------------------------------------------------------------
    def update_actions(self) -> None:
        """Доступность пунктов меню по наличию корпуса и выделения."""
        has_fp = self._doc.fp is not None
        has_sel = bool(self.selected_rows())
        self.act_add.setEnabled(has_fp)
        self.act_duplicate.setEnabled(has_fp and has_sel)
        self.act_remove.setEnabled(has_fp and has_sel)
        self.act_batch.setEnabled(has_fp and self.pad_model().rowCount() > 0)

    def context_menu(self) -> QMenu:
        """Контекстное меню таблицы (пункты — :attr:`act_add` и др.)."""
        self.update_actions()
        menu = QMenu(self)
        menu.addAction(self.act_add)
        menu.addAction(self.act_duplicate)
        menu.addAction(self.act_remove)
        menu.addSeparator()
        menu.addAction(self.act_batch)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = self.context_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    # --- операции -------------------------------------------------------------------------
    def _next_numbers(self, count: int) -> list[str]:
        fp = self._doc.fp
        used = {p.number for p in fp.pads} if fp is not None else set()
        nums = [int(n) for n in used if n.isdigit()]
        n = max(nums, default=0) + 1
        out: list[str] = []
        while len(out) < count:
            if str(n) not in used:
                out.append(str(n))
            n += 1
        return out

    def _reference_pad(self) -> Pad | None:
        m = self.pad_model()
        cur = self.currentIndex()
        if cur.isValid() and cur.row() in self.selected_rows():
            return m.pad_at(cur.row())
        sel = self.selected_pads()
        if sel:
            return sel[-1]
        return m.pad_at(m.rowCount() - 1)

    def add_pad(self) -> Pad | None:
        """Добавить площадку: копию выделенной (или последней) со следующим номером и
        сдвигом :attr:`ADD_OFFSET`; в пустом корпусе — сквозную круглую 1.6 мм с
        отверстием 0.8 мм в (0, 0). Новая площадка выделяется. Возвращает её (``None`` —
        корпус не открыт)."""
        fp = self._doc.fp
        if fp is None:
            return None
        number = self._next_numbers(1)[0]
        ref = self._reference_pad()
        if ref is None:
            new = Pad.new(number, "thru_hole", "circle", 0.0, 0.0, (1.6, 1.6), drill=0.8,
                          profile=fp.profile)
        else:
            new = ref.copy()
            new.number = number
            new.position = (ref.x + self.ADD_OFFSET[0], ref.y + self.ADD_OFFSET[1])
        cmd = AddItemCommand(self._doc, new, f"добавление площадки {number}")
        if not self.pad_model()._apply(cmd):
            return None
        self._doc.select(cmd.item)
        return cmd.item

    def duplicate_selected(self) -> list[Pad]:
        """Дублировать выделенные площадки (следующие свободные номера, сдвиг
        :attr:`DUPLICATE_OFFSET`) одним шагом отмены; выделяется последняя копия."""
        pads = self.selected_pads()
        if not pads or self._doc.fp is None:
            return []
        numbers = self._next_numbers(len(pads))
        cmds = []
        for pad, num in zip(pads, numbers, strict=True):
            new = pad.copy()
            new.number = num
            new.position = (pad.x + self.DUPLICATE_OFFSET[0], pad.y + self.DUPLICATE_OFFSET[1])
            cmds.append(AddItemCommand(self._doc, new, f"дублирование {describe_item(pad)}"))
        cmd: Any = cmds[0] if len(cmds) == 1 else BatchCommand(
            self._doc, cmds, f"дублирование площадок ({len(cmds)})")
        if not self.pad_model()._apply(cmd):
            return []
        added = [c.item for c in cmds]
        self._doc.select(added[-1])
        return added

    def remove_selected(self) -> int:
        """Удалить выделенные площадки одним шагом отмены; возвращает их число."""
        pads = self.selected_pads()
        if not pads or self._doc.fp is None:
            return 0
        cmds = [RemoveItemCommand(self._doc, p) for p in pads]
        cmd: Any = cmds[0] if len(cmds) == 1 else BatchCommand(
            self._doc, cmds, f"удаление площадок ({len(cmds)})")
        return len(pads) if self.pad_model()._apply(cmd) else 0

    def request_batch(self) -> list[Pad]:
        """Испустить :attr:`batch_requested` с выделенными площадками (пусто — все)."""
        pads = self.selected_pads()
        self.batch_requested.emit(pads)
        return pads

