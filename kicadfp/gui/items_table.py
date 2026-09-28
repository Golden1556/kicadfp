"""Таблица графики и текстов корпуса: :class:`ItemsTableModel` и :class:`ItemsTable`.

Строки — ``doc.fp.graphics`` (в порядке файла), затем ``doc.fp.texts``. Столбцы:

* «Тип» — ``line``/``rect``/``circle``/``arc``/``poly``/``curve`` или ``text:reference``,
  ``text:value``, ``text:user`` (имя поля KiCad 8+ — в подсказке);
* «Слой» — выпадающий список :data:`kicadfp.layers.ALL_LAYERS`;
* «Ширина/Размер» — ширина линии графики или размер шрифта текста (``1`` или
  ``1.2 x 1``);
* «X1/X», «Y1/Y», «X2», «Y2» — сводные координаты: линия и прямоугольник — начало и
  конец; окружность — центр (правка сдвигает окружность целиком) и радиус в «X2»; дуга —
  начало и конец (середина сохраняется); многоугольник — первая точка и число точек, кривая
  Безье — первая и последняя точки (только чтение); текст — положение;
* «Текст» — текст (редактируется у текстов);
* «Скрыт» — флажок видимости текста.

Правка ячейки — команда через ``doc.apply`` (см. :mod:`kicadfp.gui.pad_table`: общая
модель, синхронизация выделения, сигнал ``error`` при отклонённом вводе).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import QMenu, QWidget

from .. import layers as _layers
from ..model import Arc, Circle, Curve, Graphic, Line, Poly, Rect, Text
from .commands import BatchCommand, RemoveItemCommand, SetAttrCommand, SetAttrsCommand
from .pad_table import (ComboBoxDelegate, DocumentTableModel, DocumentTableView, format_mm,
                        format_pair, parse_number, parse_pair)

__all__ = [
    "ItemsTableModel", "ItemsTable", "ITEM_COLUMNS", "COL_KIND", "COL_LAYER", "COL_WIDTH",
    "COL_X1", "COL_Y1", "COL_X2", "COL_Y2", "COL_TEXT", "COL_HIDDEN", "item_kind",
]

COL_KIND, COL_LAYER, COL_WIDTH, COL_X1, COL_Y1, COL_X2, COL_Y2, COL_TEXT, COL_HIDDEN = range(9)

#: Заголовки столбцов таблицы графики и текстов.
ITEM_COLUMNS: tuple[str, ...] = ("Тип", "Слой", "Ширина/Размер", "X1/X", "Y1/Y", "X2", "Y2",
                                 "Текст", "Скрыт")

_COORD_COLS = (COL_X1, COL_Y1, COL_X2, COL_Y2)

_HEADER_TIPS: dict[int, str] = {
    COL_KIND: "Вид элемента",
    COL_LAYER: "Слой",
    COL_WIDTH: "Ширина линии (графика) или размер шрифта (текст), мм",
    COL_X1: "Линия/прямоугольник/дуга: X начала; окружность: X центра; текст: X",
    COL_Y1: "Линия/прямоугольник/дуга: Y начала; окружность: Y центра; текст: Y",
    COL_X2: "Линия/прямоугольник/дуга: X конца; окружность: радиус; многоугольник: число точек",
    COL_Y2: "Линия/прямоугольник/дуга: Y конца",
    COL_TEXT: "Текст",
    COL_HIDDEN: "Текст скрыт",
}

_COORD_WHAT = {COL_X1: "X1", COL_Y1: "Y1", COL_X2: "X2", COL_Y2: "Y2"}


def item_kind(item: Any) -> str:
    """Вид элемента для столбца «Тип»: ``line`` … ``curve``, ``text:reference`` …"""
    if isinstance(item, Text):
        return f"text:{item.kind}"
    if isinstance(item, Graphic):
        return item.kind
    return getattr(getattr(item, "node", None), "name", "?")


def _coords(item: Any) -> list[tuple[float | int | None, bool]]:
    """Значения столбцов X1, Y1, X2, Y2 и признак «редактируется» для каждого."""
    if isinstance(item, (Line, Rect)):
        (sx, sy), (ex, ey) = item.start, item.end
        return [(sx, True), (sy, True), (ex, True), (ey, True)]
    if isinstance(item, Circle):
        cx, cy = item.center
        return [(cx, True), (cy, True), (item.radius, True), (None, False)]
    if isinstance(item, Arc):
        (sx, sy), (ex, ey) = item.start, item.end
        return [(sx, True), (sy, True), (ex, True), (ey, True)]
    if isinstance(item, Poly):
        pts = list(item.points)
        x, y = pts[0] if pts else (None, None)
        return [(x, False), (y, False), (len(pts), False), (None, False)]
    if isinstance(item, Curve):
        pts = list(item.points)
        if not pts:
            return [(None, False)] * 4
        return [(pts[0][0], False), (pts[0][1], False), (pts[-1][0], False),
                (pts[-1][1], False)]
    if isinstance(item, Text):
        return [(item.x, True), (item.y, True), (None, False), (None, False)]
    return [(None, False)] * 4


def _is_checked(value: Any) -> bool:
    """Значение роли ``CheckStateRole`` (перечисление Qt, целое или bool) — «отмечено»?"""
    if isinstance(value, Qt.CheckState):
        return value == Qt.CheckState.Checked
    if isinstance(value, bool):
        return value
    try:
        return int(value) == Qt.CheckState.Checked.value
    except (TypeError, ValueError):
        return bool(value)


class ItemsTableModel(DocumentTableModel):
    """Модель таблицы графики и текстов (см. модуль). ``UserRole`` — представление
    элемента; ``setData`` принимает строку ввода (для «Скрыт» — ``CheckStateRole``) и
    возвращает ``False`` при недопустимом вводе."""

    HEADERS = ITEM_COLUMNS

    def _collect(self) -> list[Any]:
        fp = self._doc.fp
        return [] if fp is None else [*fp.graphics, *fp.texts]

    # --- чтение ---------------------------------------------------------------------------------
    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            return _HEADER_TIPS.get(section)
        return super().headerData(section, orientation, role)

    def text(self, item: Any, column: int) -> str:
        """Текст ячейки элемента ``item`` в столбце ``column``."""
        if column == COL_KIND:
            return item_kind(item)
        if column == COL_LAYER:
            return item.layer or ""
        if column == COL_WIDTH:
            if isinstance(item, Text):
                return format_pair(item.font_size_x, item.font_size_y)
            return format_mm(item.width)
        if column in _COORD_COLS:
            v, _ = _coords(item)[column - COL_X1]
            if v is None:
                return ""
            return str(v) if isinstance(v, int) else format_mm(v)
        if column == COL_TEXT:
            return item.text if isinstance(item, Text) else ""
        return ""

    def _editable(self, item: Any, column: int) -> bool:
        if column in (COL_LAYER, COL_WIDTH):
            return True
        if column in _COORD_COLS:
            return _coords(item)[column - COL_X1][1]
        return column == COL_TEXT and isinstance(item, Text)

    def data(self, index: QModelIndex | QPersistentModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        item = self.item_at(index)
        if item is None:
            return None
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            try:
                return self.text(item, col)
            except Exception:  # noqa: BLE001 — узел необычной формы не должен ронять таблицу
                return "?"
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_HIDDEN \
                and isinstance(item, Text):
            return Qt.CheckState.Checked if item.hide else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_KIND and isinstance(item, Text) and item.name:
                return f"Поле «{item.name}»"
            if col == COL_X2 and isinstance(item, Poly):
                return "Число точек многоугольника"
            return _HEADER_TIPS.get(col)
        if role == Qt.ItemDataRole.TextAlignmentRole and (col in _COORD_COLS or col == COL_WIDTH):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        item = self.item_at(index)
        if item is None:
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        col = index.column()
        if col == COL_HIDDEN:
            if isinstance(item, Text):
                f |= Qt.ItemFlag.ItemIsUserCheckable
            return f
        try:
            if self._editable(item, col):
                f |= Qt.ItemFlag.ItemIsEditable
        except Exception:  # noqa: BLE001
            pass
        return f

    # --- запись ---------------------------------------------------------------------------------
    def setData(self, index: QModelIndex | QPersistentModelIndex, value: Any,  # noqa: N802
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        item = self.item_at(index)
        if item is None or self._doc.fp is None:
            return False
        col = index.column()
        if col == COL_HIDDEN:
            if role != Qt.ItemDataRole.CheckStateRole or not isinstance(item, Text):
                return False
            hide = _is_checked(value)
            if hide == item.hide:
                return True
            return self._apply(SetAttrCommand(self._doc, item, "hide", hide))
        if role != Qt.ItemDataRole.EditRole:
            return False
        try:
            if not self._editable(item, col):
                raise ValueError("ячейка только для чтения")
            change = self._change_for(item, col, value)
        except (ValueError, TypeError) as e:
            return self._reject(str(e))
        if change is None:
            return True
        values, text = change
        if len(values) == 1:
            (attr, v), = values.items()
            return self._apply(SetAttrCommand(self._doc, item, attr, v, text))
        return self._apply(SetAttrsCommand(self._doc, item, values, text))

    def _change_for(self, item: Any, col: int,
                    value: Any) -> tuple[dict[str, Any], str | None] | None:
        if col == COL_LAYER:
            name = str(value).strip()
            if not _layers.is_valid_layer(name, single=True):
                raise ValueError(f"слой: неизвестный слой «{name}»")
            return None if name == item.layer else ({"layer": name}, None)
        if col == COL_WIDTH:
            if isinstance(item, Text):
                size = parse_pair(value, "размер шрифта")
                pair = (size, size) if isinstance(size, float) else size
                if pair == (item.font_size_x, item.font_size_y):
                    return None
                return {"font_size": size}, None
            w = parse_number(value, "ширина", minimum=0.0)
            return None if w == item.width else ({"width": w}, None)
        if col in _COORD_COLS:
            return self._coord_change(item, col, parse_number(value, _COORD_WHAT[col]))
        if col == COL_TEXT and isinstance(item, Text):
            s = "" if value is None else str(value)
            return None if s == item.text else ({"text": s}, None)
        raise ValueError("ячейка только для чтения")

    def _coord_change(self, item: Any, col: int,
                      v: float) -> tuple[dict[str, Any], str | None] | None:
        cur = _coords(item)[col - COL_X1][0]
        if cur == v:
            return None
        if isinstance(item, (Line, Rect)):
            attr = {COL_X1: "start_x", COL_Y1: "start_y", COL_X2: "end_x", COL_Y2: "end_y"}[col]
            return {attr: v}, None
        if isinstance(item, Circle):
            if col == COL_X2:
                if v <= 0:
                    raise ValueError("радиус: значение должно быть больше 0")
                return {"radius": v}, None
            (cx, cy), (ex, ey) = item.center, item.end
            dx, dy = (v - cx, 0.0) if col == COL_X1 else (0.0, v - cy)
            return ({"center": (cx + dx, cy + dy), "end": (ex + dx, ey + dy)},
                    "перемещение окружности")
        if isinstance(item, Arc):
            if col in (COL_X1, COL_Y1):
                x, y = item.start
                return {"start": (v, y) if col == COL_X1 else (x, v)}, None
            x, y = item.end
            return {"end": (v, y) if col == COL_X2 else (x, v)}, None
        if isinstance(item, Text):
            return {"x" if col == COL_X1 else "y": v}, None
        raise ValueError("ячейка только для чтения")


class ItemsTable(DocumentTableView):
    """Таблица графики и текстов (``QTableView`` над :class:`ItemsTableModel`): сортировка
    выключена, выбор строки — ``doc.select``, «Слой» — выпадающий список. Контекстное меню:
    «Удалить» (:meth:`remove_selected`; Reference и Value не удаляются)."""

    def __init__(self, doc: Any, parent: QWidget | None = None) -> None:
        super().__init__(doc, ItemsTableModel(doc), parent)
        self.model().setParent(self)
        self.setItemDelegateForColumn(COL_LAYER, ComboBoxDelegate(_layers.ALL_LAYERS, self))
        self.act_remove = QAction("Удалить", self)
        self.act_remove.triggered.connect(self.remove_selected)
        for col, w in ((COL_KIND, 110), (COL_LAYER, 90), (COL_WIDTH, 90), (COL_TEXT, 140),
                       (COL_HIDDEN, 50)):
            self.setColumnWidth(col, w)
        for col in _COORD_COLS:
            self.setColumnWidth(col, 70)

    def items_model(self) -> ItemsTableModel:
        """Модель графики и текстов."""
        m = self.model()
        assert isinstance(m, ItemsTableModel)
        return m

    @staticmethod
    def _removable(item: Any) -> bool:
        return not (isinstance(item, Text) and item.kind in ("reference", "value"))

    def context_menu(self) -> QMenu:
        """Контекстное меню таблицы."""
        self.act_remove.setEnabled(any(self._removable(i) for i in self.selected_items()))
        menu = QMenu(self)
        menu.addAction(self.act_remove)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = self.context_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    def remove_selected(self) -> int:
        """Удалить выделенные элементы (кроме Reference/Value) одним шагом отмены; возвращает
        их число."""
        items = [i for i in self.selected_items() if self._removable(i)]
        if not items or self._doc.fp is None:
            return 0
        cmds = [RemoveItemCommand(self._doc, i) for i in items]
        cmd: Any = cmds[0] if len(cmds) == 1 else BatchCommand(
            self._doc, cmds, f"удаление элементов ({len(cmds)})")
        return len(items) if self.items_model()._apply(cmd) else 0
