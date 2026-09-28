"""Главное окно редактора посадочных мест: :class:`MainWindow` (``QMainWindow``).

Окно собирает готовые компоненты вокруг одного документа
:class:`~kicadfp.gui.document.FootprintDocument` — единственного владельца модели:

* центр — канва :class:`~kicadfp.gui.canvas.PreviewCanvas`;
* док-панели (``QDockWidget``): «Библиотеки» (:class:`~kicadfp.gui.libtree.LibraryTree`,
  слева), «Слои» (:class:`LayersPanel` — флажки видимости слоёв канвы с цветными
  квадратиками, слева), «Свойства корпуса»
  (:class:`~kicadfp.gui.props_panel.PropertiesPanel`, справа), «Площадки»
  (:class:`~kicadfp.gui.pad_table.PadTable`) и «Графика и тексты»
  (:class:`~kicadfp.gui.items_table.ItemsTable`) — снизу, вкладками;
* меню «Файл», «Правка», «Корпус», «Вид», «Справка» и панель инструментов;
* строка состояния: координаты курсора (мм), шаг сетки, имя файла, признак «изменён».

Модель меняется только командами через :meth:`FootprintDocument.apply
<kicadfp.gui.document.FootprintDocument.apply>`: таблицы, панель свойств, канва и диалоги
делают это сами, окно — для добавления и удаления элементов и операций над корпусом
(сдвиг, поворот, отражение, перенумерация). Все виджеты перерисовываются по сигналу
документа ``changed``; окно и панель слоёв не хранят копий данных модели.

Заголовок окна — «kicadfp — имя [*]» (``setWindowModified`` по признаку несохранённых
изменений). Открытие другого корпуса, создание нового и закрытие окна при несохранённых
изменениях спрашивают :attr:`FootprintDocument.confirm_discard
<kicadfp.gui.document.FootprintDocument.confirm_discard>`; окно подставляет туда вопрос
«Сохранить / Не сохранять / Отмена» (:attr:`MainWindow.ask_save_changes`).

Клавиши: Ctrl+N, Ctrl+O, Ctrl+Shift+O, Ctrl+S, Ctrl+Shift+S, Ctrl+Q; Ctrl+Z — отменить,
Ctrl+Shift+Z (Ctrl+Y) — повторить; Del — удалить; F7 — проверить; Ctrl++/Ctrl+- —
масштаб. Enter (свойства элемента) и F (вписать) действуют, когда фокус на канве, чтобы
не мешать вводу в полях и таблицах; свойства элемента открывает и двойной щелчок по нему
на канве, а в таблицах — Enter на строке (вне редактирования ячейки). Контекстное меню
канвы (правая кнопка, :meth:`MainWindow.canvas_context_menu`): свойства и удаление
элемента под курсором, добавление площадки и фигур в точку щелчка, отмена/повтор, «Вписать».

Вопросы пользователю и модальные диалоги
----------------------------------------
Окно не вызывает модальные окна напрямую, а через подменяемые атрибуты-функции — так
сценарии и тесты работают без блокирующих окон:

* :attr:`MainWindow.exec_dialog` ``(диалог) -> bool`` — показать модальный диалог
  (:class:`~kicadfp.gui.dialogs.GenerateDialog`, :class:`~kicadfp.gui.dialogs.PadBatchDialog`,
  :class:`~kicadfp.gui.dialogs.ItemPropertiesDialog`, :class:`ParamsDialog`,
  :class:`~kicadfp.gui.dialogs.AboutDialog`); результат — принят ли диалог. Тест
  подставляет функцию, которая заполняет диалог его методами ``set_*`` и вызывает
  ``accept()``;
* :attr:`MainWindow.ask_open_file` ``(заголовок, фильтр)``, :attr:`MainWindow.ask_save_file`
  ``(заголовок, фильтр, предлагаемый путь)``, :attr:`MainWindow.ask_directory`
  ``(заголовок)`` — путь или ``None`` (``QFileDialog``);
* :attr:`MainWindow.ask_text` ``(заголовок, подпись, текст)`` — строка или ``None``;
* :attr:`MainWindow.ask_save_changes` ``()`` — ``"save"``, ``"discard"`` или ``"cancel"``;
* :attr:`MainWindow.show_error` ``(заголовок, текст)`` — сообщение об ошибке
  (``QMessageBox``). Ошибка разбора файла показывается с позицией: «строка N, позиция M: …»;
* :attr:`MainWindow.exec_menu` ``(меню, точка)`` — показ контекстного меню канвы.

Программные эквиваленты команд меню: :meth:`MainWindow.open_path`, :meth:`~MainWindow.open_file`,
:meth:`~MainWindow.open_library`, :meth:`~MainWindow.new_footprint`, :meth:`~MainWindow.save`,
:meth:`~MainWindow.save_as`, :meth:`~MainWindow.export_svg`, :meth:`~MainWindow.export_png`,
:meth:`~MainWindow.delete_selected`, :meth:`~MainWindow.edit_properties`,
:meth:`~MainWindow.pad_batch`, :meth:`~MainWindow.add_pad`, :meth:`~MainWindow.add_line`,
:meth:`~MainWindow.add_rect`, :meth:`~MainWindow.add_circle`, :meth:`~MainWindow.add_text`,
:meth:`~MainWindow.validate`, :meth:`~MainWindow.generate`, :meth:`~MainWindow.move_footprint`,
:meth:`~MainWindow.rotate_footprint`, :meth:`~MainWindow.flip_footprint`,
:meth:`~MainWindow.renumber_pads`.

Настройки (``QSettings``)
-------------------------
Геометрия окна и расположение панелей (``window/geometry``, ``window/state``), вид канвы
(``view/grid``, ``view/grid_visible``, ``view/snap``, ``view/show_hidden``,
``view/hidden_layers``), недавние файлы и библиотеки (``recent_files``, до
:data:`MAX_RECENT`), открытые в дереве библиотеки и файлы (``session/libraries``) и
последний каталог диалогов выбора файлов (``dirs/last``). По умолчанию — файл INI из
переменной окружения ``KICADFP_SETTINGS``, иначе ``QSettings("kicadfp", "kicadfp")``;
тесты передают свой объект.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from PySide6.QtCore import (QEvent, QMimeData, QObject, QPoint, QPointF, QRectF, QSettings, QSize,
                            Qt, QTimer)
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QContextMenuEvent,
                           QDragEnterEvent, QDropEvent, QFont, QIcon, QKeyEvent, QKeySequence,
                           QMouseEvent, QPainter, QPalette, QPen, QPixmap, QShowEvent)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QStyle, QTabWidget, QToolBar,
                               QVBoxLayout, QWidget)

from .. import geometry as _geo
from .. import layers as _L
from .. import render as _render
from ..library import FOOTPRINT_EXT, Library, sanitize_name
from ..model import Circle, Footprint, Graphic, Line, Model, Pad, Rect, Text
from ..sexpr import SexprSyntaxError
from .app import APP_NAME, ORGANIZATION_NAME, app_icon
from .canvas import GRID_STEPS, HOLES_LAYER, PAD_NUMBERS_LAYER, PreviewCanvas
from .commands import AddItemCommand, BatchCommand, OperationCommand, RemoveItemCommand
from .dialogs import (RENUMBER_ORDERS, AboutDialog, GenerateDialog, ItemPropertiesDialog,
                      PadBatchDialog, ValidateDialog)
from .document import FootprintDocument
from .items_table import ItemsTable
from .libtree import LibraryTree
from .pad_table import DocumentTableView, PadTable, format_mm
from .props_panel import PropertiesPanel

__all__ = [
    "MainWindow", "LayersPanel", "ParamsDialog", "ParamSpec", "MAX_RECENT", "PNG_EXPORT_WIDTH",
    "OPEN_FILTER", "SAVE_FILTER", "SVG_FILTER", "PNG_FILTER", "PANEL_LAYERS",
    "PSEUDO_LAYER_TITLES", "SETTINGS_ENV", "default_settings",
]

#: Число записей в меню «Недавние файлы».
MAX_RECENT = 10
#: Ширина изображения при экспорте PNG, пикселей.
PNG_EXPORT_WIDTH = 1600
#: Переменная окружения с путём к файлу настроек (INI) вместо стандартного места.
SETTINGS_ENV = "KICADFP_SETTINGS"

#: Фильтр диалога «Открыть файл».
OPEN_FILTER = "Корпуса KiCad (*.kicad_mod *.mod *.emp);;Все файлы (*)"
#: Фильтр диалога «Сохранить как».
SAVE_FILTER = "Корпус KiCad (*.kicad_mod)"
#: Фильтр диалога «Экспорт SVG».
SVG_FILTER = "Изображение SVG (*.svg)"
#: Фильтр диалога «Экспорт PNG».
PNG_FILTER = "Изображение PNG (*.png)"

#: Слои, которые панель «Слои» показывает всегда (как панель «Внешний вид» редактора
#: корпусов KiCad); к ним добавляются слои, использованные в открытом корпусе
#: (внутренняя медь, ``User.N``, ``Rescue``), и псевдослои канвы.
PANEL_LAYERS: tuple[str, ...] = (
    "F.Cu", "B.Cu", "F.Adhes", "B.Adhes", "F.Paste", "B.Paste", "F.SilkS", "B.SilkS",
    "F.Mask", "B.Mask", "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User", "Edge.Cuts",
    "Margin", "F.CrtYd", "B.CrtYd", "F.Fab", "B.Fab",
)

#: Названия псевдослоёв канвы в панели «Слои».
PSEUDO_LAYER_TITLES: dict[str, str] = {HOLES_LAYER: "Отверстия",
                                       PAD_NUMBERS_LAYER: "Номера площадок"}

_PSEUDO_COLOR_KEYS = {HOLES_LAYER: "hole", PAD_NUMBERS_LAYER: "pad_net_names"}
_STATE_VERSION = 1
_STATUS_MS = 5000
_DEFAULT_SIZE = (1440, 900)
_REMOVE_FORBIDDEN = "Reference и Value — обязательные тексты корпуса, их нельзя удалить"


def _panel_rank() -> dict[str, int]:
    order = ["F.Cu", *_L.INNER_COPPER_LAYERS, "B.Cu", *PANEL_LAYERS[2:],
             *_L.USER_DEFINED_LAYERS, _L.RESCUE_LAYER]
    return {name: i for i, name in enumerate(order)}


_PANEL_RANK = _panel_rank()


# ---------------------------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------------------------

def _abs(path: str | PathLike[str]) -> Path:
    """Абсолютный путь (``~`` раскрывается, символические ссылки не разыменовываются)."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _same_path(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return a == b or (a.exists() and b.exists() and os.path.samefile(a, b))
    except OSError:
        return a == b


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


_OS_ERRORS: tuple[tuple[type[OSError], str], ...] = (
    (FileNotFoundError, "файл или каталог не найден"),
    (IsADirectoryError, "это каталог, а не файл"),
    (NotADirectoryError, "это файл, а не каталог"),
    (PermissionError, "нет доступа (недостаточно прав)"),
    (FileExistsError, "файл уже существует"),
)


def _error_text(e: BaseException) -> str:
    """Текст ошибки для пользователя. Ошибка разбора — «строка N, позиция M: …»; ошибки
    операционной системы — по-русски (исключения kicadfp уже содержат русский текст)."""
    if isinstance(e, SexprSyntaxError):
        return str(e)
    if isinstance(e, OSError) and e.errno is not None:
        for cls, text in _OS_ERRORS:
            if isinstance(e, cls):
                return text
        return f"ошибка ввода-вывода: {e.strerror or e}"
    return str(e) or type(e).__name__


def _to_bool(value: Any, default: bool) -> bool:
    """Логическое значение из ``QSettings`` (в INI — строка ``true``/``false``)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return default


def _to_float(value: Any, default: float | None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _to_list(value: Any) -> list[str]:
    """Список строк из ``QSettings`` (в INI список из одного элемента читается строкой, пустой
    список — ``None``)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None and str(v)]
    return []


def _next_pad_number(fp: Footprint) -> str:
    """Следующий свободный числовой номер площадки."""
    used = {p.number for p in fp.pads}
    nums = [int(n) for n in used if n.isdigit()]
    n = max(nums, default=0) + 1
    while str(n) in used:
        n += 1
    return str(n)


def _supports_rect(profile: Any) -> bool:
    """Есть ли ``fp_rect`` в формате профиля (в KiCad 5 ``module`` и версиях до 20200614
    прямоугольник рисуется четырьмя ``fp_line``). Проверяется самой моделью: пробный
    :meth:`Rect.new <kicadfp.model.Rect.new>` в этом профиле."""
    try:
        Rect.new((0.0, 0.0), (1.0, 1.0), "F.SilkS", 0.12, profile=profile, uuid=False)
    except ValueError:
        return False
    return True


def _is_within(widget: QWidget | None, ancestor: QWidget) -> bool:
    """Является ли ``widget`` самим ``ancestor`` или его потомком."""
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def default_settings() -> QSettings:
    """Настройки по умолчанию: файл INI из ``KICADFP_SETTINGS`` или
    ``QSettings("kicadfp", "kicadfp")``."""
    path = os.environ.get(SETTINGS_ENV, "").strip()
    if path:
        return QSettings(os.path.expanduser(path), QSettings.Format.IniFormat)
    return QSettings(ORGANIZATION_NAME, APP_NAME)


# ---------------------------------------------------------------------------------------------
# Значки
# ---------------------------------------------------------------------------------------------

def _paint_icon(p: QPainter, kind: str, fg: QColor) -> None:
    """Нарисовать значок ``kind`` в системе координат 32×32."""
    accent = QColor("#2f65ca")

    def pen(color: QColor | str, width: float) -> QPen:
        q = QPen(QColor(color))
        q.setWidthF(width)
        q.setCapStyle(Qt.PenCapStyle.RoundCap)
        q.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return q

    no_brush = Qt.BrushStyle.NoBrush
    if kind == "pad":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d9a93a"))
        p.drawRoundedRect(QRectF(5, 5, 22, 22), 4, 4)
        p.setBrush(QColor("#1e1e1e"))
        p.drawEllipse(QPointF(16, 16), 5, 5)
    elif kind == "line":
        p.setPen(pen(fg, 2.6))
        p.drawLine(QPointF(7, 25), QPointF(25, 7))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(QPointF(7, 25), 3, 3)
        p.drawEllipse(QPointF(25, 7), 3, 3)
    elif kind == "rect":
        p.setPen(pen(fg, 2.6))
        p.setBrush(no_brush)
        p.drawRect(QRectF(5, 8, 22, 16))
    elif kind == "circle":
        p.setPen(pen(fg, 2.6))
        p.setBrush(no_brush)
        p.drawEllipse(QPointF(16, 16), 10.5, 10.5)
    elif kind == "text":
        font = QFont()
        font.setBold(True)
        font.setPixelSize(26)
        p.setFont(font)
        p.setPen(fg)
        p.drawText(QRectF(0, 0, 32, 32), int(Qt.AlignmentFlag.AlignCenter), "T")
    elif kind == "fit":
        p.setPen(pen(fg, 2.6))
        for x, y, dx, dy in ((4, 4, 1, 1), (28, 4, -1, 1), (4, 28, 1, -1), (28, 28, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 7 * dx, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + 7 * dy))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRect(QRectF(11, 11, 10, 10))
    elif kind in ("zoom_in", "zoom_out"):
        p.setPen(pen(fg, 2.6))
        p.setBrush(no_brush)
        p.drawEllipse(QPointF(13, 13), 8.5, 8.5)
        p.setPen(pen(fg, 4.0))
        p.drawLine(QPointF(20, 20), QPointF(27, 27))
        p.setPen(pen(accent, 2.6))
        p.drawLine(QPointF(9, 13), QPointF(17, 13))
        if kind == "zoom_in":
            p.drawLine(QPointF(13, 9), QPointF(13, 17))
    elif kind == "validate":
        p.setPen(pen("#2e7d32", 4.0))
        p.setBrush(no_brush)
        p.drawPolyline([QPointF(6, 17), QPointF(13, 24), QPointF(26, 8)])
    elif kind == "generate":
        p.setPen(pen(fg, 2.0))
        p.setBrush(QColor("#3a3a3a"))
        p.drawRoundedRect(QRectF(10, 4, 12, 24), 1.5, 1.5)
        p.setPen(pen("#d9a93a", 2.6))
        for y in (8.5, 14, 19.5, 25):
            p.drawLine(QPointF(4, y), QPointF(8.5, y))
            p.drawLine(QPointF(23.5, y), QPointF(28, y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f2f2f2"))
        p.drawEllipse(QPointF(14, 8), 1.6, 1.6)
    elif kind == "delete":
        p.setPen(pen("#c62828", 3.6))
        p.drawLine(QPointF(9, 9), QPointF(23, 23))
        p.drawLine(QPointF(23, 9), QPointF(9, 23))


def _tool_icon(kind: str, fg: QColor) -> QIcon:
    """Значок панели инструментов (рисуется программно в нескольких размерах)."""
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.scale(size / 32.0, size / 32.0)
            _paint_icon(p, kind, fg)
        finally:
            p.end()
        icon.addPixmap(pm)
    return icon


def _themed(name: str, fallback: QIcon) -> QIcon:
    """Значок темы оформления системы (если есть), иначе ``fallback``."""
    try:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name, fallback)
    except (AttributeError, RuntimeError):  # pragma: no cover — старые PySide6
        pass
    return fallback


def _layer_icon(name: str) -> QIcon:
    """Цветной квадратик слоя (цвет :data:`kicadfp.layers.COLORS`)."""
    key = _PSEUDO_COLOR_KEYS.get(name, name)
    color = QColor(_L.color(key))
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setPen(QPen(QColor("#5f5f5f")))
        p.setBrush(color)
        p.drawRect(1, 1, 13, 13)
    finally:
        p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------------------------
# Панель слоёв
# ---------------------------------------------------------------------------------------------

class LayersPanel(QWidget):
    """Панель «Слои»: флажки видимости слоёв канвы с цветными квадратиками.

    Строки — :data:`PANEL_LAYERS`, слои, использованные в открытом корпусе (внутренняя медь,
    ``User.N``, ``Rescue``; групповые обозначения вроде ``*.Cu`` не добавляют строк),
    скрытые на канве слои и псевдослои «Отверстия» и «Номера площадок»
    (:data:`PSEUDO_LAYER_TITLES`). Состояние флажков — видимость слоёв канвы
    (:meth:`PreviewCanvas.is_layer_visible <kicadfp.gui.canvas.PreviewCanvas.is_layer_visible>`):
    панель не хранит его сама, а перечитывает по сигналу канвы ``layers_changed``;
    щелчок по флажку — :meth:`PreviewCanvas.set_layer_visible
    <kicadfp.gui.canvas.PreviewCanvas.set_layer_visible>`. Состав строк обновляется по
    сигналам документа ``changed``/``document_changed``.

    Программно: :meth:`layer_names`, :meth:`is_checked`, :meth:`set_checked`,
    :meth:`show_all`, :meth:`hide_all`.
    """

    def __init__(self, canvas: PreviewCanvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._names: list[str] = []
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        #: Список слоёв (``QListWidget``; у строки ``data(UserRole)`` — имя слоя).
        self.list_widget = QListWidget(self)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_widget, 1)
        row = QHBoxLayout()
        self.show_all_button = QPushButton("Показать все", self)
        self.show_all_button.clicked.connect(self.show_all)
        self.hide_all_button = QPushButton("Скрыть все", self)
        self.hide_all_button.clicked.connect(self.hide_all)
        row.addWidget(self.show_all_button)
        row.addWidget(self.hide_all_button)
        layout.addLayout(row)
        canvas.layers_changed.connect(self.refresh)
        doc = canvas.document
        doc.changed.connect(self.refresh)
        doc.document_changed.connect(self.refresh)
        self.refresh()

    # --- доступ ---------------------------------------------------------------------------------
    @property
    def canvas(self) -> PreviewCanvas:
        """Канва, видимостью слоёв которой управляет панель."""
        return self._canvas

    def layer_names(self) -> list[str]:
        """Имена слоёв в порядке строк (псевдослои — в конце)."""
        return list(self._names)

    def item_for(self, name: str) -> QListWidgetItem | None:
        """Строка слоя ``name`` (``None`` — нет в панели)."""
        lw = self.list_widget
        for i in range(lw.count()):
            it = lw.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == name:
                return it
        return None

    def is_checked(self, name: str) -> bool:
        """Отмечен ли флажок слоя (``KeyError`` — слоя нет в панели)."""
        it = self.item_for(name)
        if it is None:
            raise KeyError(f"слоя {name!r} нет в панели «Слои»")
        return it.checkState() == Qt.CheckState.Checked

    def set_checked(self, name: str, checked: bool) -> None:
        """Отметить или снять флажок слоя (как щелчком): видимость меняется на канве."""
        it = self.item_for(name)
        if it is None:
            raise KeyError(f"слоя {name!r} нет в панели «Слои»")
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def show_all(self) -> None:
        """Показать все слои."""
        self._canvas.show_all_layers()

    def hide_all(self) -> None:
        """Скрыть все слои панели (и псевдослои)."""
        self._canvas.set_hidden_layers(self._names)

    # --- состав ---------------------------------------------------------------------------------
    def _used_layers(self) -> set[str]:
        fp = self._canvas.document.fp
        out: set[str] = set()
        if fp is None:
            return out
        try:
            for pad in fp.pads:
                out.update(pad.layers)
            for g in fp.graphics:
                out.update(g.layers)
            for t in fp.texts:
                if t.layer:
                    out.add(t.layer)
            for z in fp.zones:
                ls = z.find("layers")
                if ls is not None:
                    out.update(str(a) for a in ls.atoms())
                elif z.value("layer") is not None:
                    out.add(str(z.value("layer")))
        except Exception:  # noqa: BLE001 — узел необычной формы не мешает панели
            pass
        return out

    def _collect(self) -> list[str]:
        names = set(PANEL_LAYERS)
        names.update(n for n in self._used_layers() if n in _PANEL_RANK)
        names.update(n for n in self._canvas.hidden_layers if n in _PANEL_RANK)
        return [*sorted(names, key=_PANEL_RANK.__getitem__), *PSEUDO_LAYER_TITLES]

    def refresh(self) -> None:
        """Обновить состав строк (если изменился) и флажки по видимости слоёв канвы."""
        names = self._collect()
        if names != self._names:
            self._rebuild(names)
        else:
            self._sync_checks()

    def _check_state(self, name: str) -> Qt.CheckState:
        try:
            visible = self._canvas.is_layer_visible(name)
        except ValueError:
            visible = True
        return Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked

    def _rebuild(self, names: list[str]) -> None:
        lw = self.list_widget
        current = lw.currentItem()
        current_name = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._syncing = True
        try:
            lw.clear()
            flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                     | Qt.ItemFlag.ItemIsSelectable)
            for name in names:
                title = PSEUDO_LAYER_TITLES.get(name) or _L.display_name(name)
                it = QListWidgetItem(_layer_icon(name), title)
                it.setData(Qt.ItemDataRole.UserRole, name)
                it.setFlags(flags)
                it.setCheckState(self._check_state(name))
                it.setToolTip(f"{title}: флажок — показать/скрыть на канве")
                lw.addItem(it)
                if name == current_name:
                    lw.setCurrentItem(it)
            self._names = list(names)
        finally:
            self._syncing = False

    def _sync_checks(self) -> None:
        lw = self.list_widget
        self._syncing = True
        try:
            for i in range(lw.count()):
                it = lw.item(i)
                want = self._check_state(it.data(Qt.ItemDataRole.UserRole))
                if it.checkState() != want:
                    it.setCheckState(want)
        finally:
            self._syncing = False

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._syncing:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        try:
            self._canvas.set_layer_visible(name, item.checkState() == Qt.CheckState.Checked)
        except ValueError:
            pass


# ---------------------------------------------------------------------------------------------
# Диалог параметров операции
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:
    """Поле :class:`ParamsDialog`: ``kind`` — ``"float"`` (``QDoubleSpinBox``), ``"int"``
    (``QSpinBox``), ``"choice"`` (``QComboBox`` с парами ``choices`` (значение, надпись)),
    ``"text"`` (``QLineEdit``) или ``"bool"`` (``QCheckBox``)."""

    name: str
    label: str
    kind: str = "float"
    default: Any = 0.0
    minimum: float = -10_000.0
    maximum: float = 10_000.0
    decimals: int = 4
    step: float = 0.1
    choices: tuple[tuple[Any, str], ...] = ()
    tip: str = ""


class ParamsDialog(QDialog):
    """Небольшой диалог параметров операции над корпусом («Сдвинуть…», «Повернуть…»,
    «Перенумеровать площадки…»).

    Поля задаются списком :class:`ParamSpec`. Программное заполнение (тесты, сценарии):
    :meth:`set_value` (значение вне диапазона или не из списка — ``ValueError``),
    :meth:`value`, :meth:`values`; дополнительные кнопки — :meth:`add_button`, их список —
    :attr:`buttons`. Диалог только собирает значения, операцию выполняет окно.
    """

    def __init__(self, title: str, specs: Sequence[ParamSpec], parent: QWidget | None = None, *,
                 note: str = "", ok_text: str = "Применить") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._specs: dict[str, ParamSpec] = {}
        self._widgets: dict[str, QWidget] = {}
        #: Дополнительные кнопки (:meth:`add_button`).
        self.buttons: dict[str, QPushButton] = {}
        outer = QVBoxLayout(self)
        if note:
            label = QLabel(note, self)
            label.setWordWrap(True)
            outer.addWidget(label)
        form = QFormLayout()
        outer.addLayout(form)
        for spec in specs:
            if spec.name in self._specs:
                raise ValueError(f"поле {spec.name!r} задано дважды")
            w = self._make(spec)
            if spec.tip:
                w.setToolTip(spec.tip)
            self._specs[spec.name] = spec
            self._widgets[spec.name] = w
            form.addRow(spec.label, w)
            self.set_value(spec.name, spec.default)
        self._extra = QHBoxLayout()
        outer.addLayout(self._extra)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel, self)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        outer.addWidget(box)

    def _make(self, spec: ParamSpec) -> QWidget:
        w: Any
        if spec.kind == "float":
            w = QDoubleSpinBox(self)
            w.setDecimals(spec.decimals)
            w.setRange(spec.minimum, spec.maximum)
            w.setSingleStep(spec.step)
        elif spec.kind == "int":
            w = QSpinBox(self)
            w.setRange(int(spec.minimum), int(spec.maximum))
        elif spec.kind == "choice":
            w = QComboBox(self)
            for value, title in spec.choices:
                w.addItem(title, value)
        elif spec.kind == "text":
            w = QLineEdit(self)
        elif spec.kind == "bool":
            w = QCheckBox(self)
        else:
            raise ValueError(f"неизвестный вид поля {spec.kind!r}")
        return w

    def names(self) -> list[str]:
        """Имена полей по порядку."""
        return list(self._specs)

    def widget(self, name: str) -> QWidget:
        """Виджет поля ``name`` (``KeyError`` — нет такого поля)."""
        return self._widgets[name]

    def set_value(self, name: str, value: Any) -> None:
        """Записать значение в поле ``name``."""
        spec = self._specs[name]
        w: Any = self._widgets[name]
        what = spec.label.rstrip(": ")
        if spec.kind in ("float", "int"):
            v = float(value)
            if not math.isfinite(v) or not spec.minimum <= v <= spec.maximum:
                raise ValueError(f"{what}: значение вне диапазона "
                                 f"{format_mm(spec.minimum)} … {format_mm(spec.maximum)}")
            if spec.kind == "int":
                if not v.is_integer():
                    raise ValueError(f"{what}: ожидается целое число")
                w.setValue(int(v))
            else:
                w.setValue(v)
        elif spec.kind == "choice":
            i = w.findData(value)
            if i < 0:
                raise ValueError(f"{what}: недопустимое значение {value!r}")
            w.setCurrentIndex(i)
        elif spec.kind == "text":
            w.setText("" if value is None else str(value))
        else:
            w.setChecked(bool(value))

    def value(self, name: str) -> Any:
        """Значение поля ``name`` (число, ключ выбранного пункта, строка или ``bool``)."""
        spec = self._specs[name]
        w: Any = self._widgets[name]
        if spec.kind == "float":
            return float(w.value())
        if spec.kind == "int":
            return int(w.value())
        if spec.kind == "choice":
            return w.currentData()
        if spec.kind == "text":
            return w.text().strip()
        return bool(w.isChecked())

    def values(self) -> dict[str, Any]:
        """Все значения ``{поле: значение}``."""
        return {n: self.value(n) for n in self._specs}

    def add_button(self, text: str, callback: Callable[[], Any]) -> QPushButton:
        """Добавить кнопку над кнопками «Применить»/«Отмена» (например, «Центр площадок»)."""
        b = QPushButton(text, self)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _checked=False: callback())
        self._extra.addWidget(b)
        self.buttons[text] = b
        return b


# ---------------------------------------------------------------------------------------------
# Главное окно
# ---------------------------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Главное окно редактора (см. модуль).

    ``document`` — документ (по умолчанию новый :class:`FootprintDocument
    <kicadfp.gui.document.FootprintDocument>`); его ``confirm_discard`` заменяется вопросом
    окна о сохранении. ``settings`` — ``QSettings`` (по умолчанию :func:`default_settings`);
    ``restore_settings=False`` — не читать сохранённые настройки (окно «с нуля»; при
    закрытии они всё равно записываются).

    Виджеты: :attr:`canvas`, :attr:`library_tree`, :attr:`props_panel`, :attr:`pad_table`,
    :attr:`items_table`, :attr:`layers_panel`; док-панели :attr:`dock_libraries`,
    :attr:`dock_layers`, :attr:`dock_properties`, :attr:`dock_pads`, :attr:`dock_items`;
    панель инструментов :attr:`toolbar`; действия ``act_*`` (пункты меню и кнопки);
    подменяемые функции вопросов — см. модуль.
    """

    def __init__(self, document: FootprintDocument | None = None,
                 parent: QWidget | None = None, *, settings: QSettings | None = None,
                 restore_settings: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("kicadfp_main_window")
        self._doc = document if document is not None else FootprintDocument(self)
        self._settings = settings if settings is not None else default_settings()
        self._recent: list[str] = []
        self._last_dir = ""
        self._validate_dialog: ValidateDialog | None = None
        self._properties_pending = False
        self._first_show = True
        self._state_restored = False

        #: Показ модального диалога: ``exec_dialog(диалог) -> bool`` (принят ли).
        self.exec_dialog: Callable[[QDialog], bool] = self._exec_dialog
        #: Показ контекстного меню: ``exec_menu(меню, глобальная точка)``.
        self.exec_menu: Callable[[QMenu, QPoint], Any] = self._exec_menu
        #: Выбор файла для открытия: ``ask_open_file(заголовок, фильтр) -> путь | None``.
        self.ask_open_file: Callable[[str, str], str | None] = self._ask_open_file
        #: Выбор файла для записи: ``ask_save_file(заголовок, фильтр, путь) -> путь | None``.
        self.ask_save_file: Callable[[str, str, str], str | None] = self._ask_save_file
        #: Выбор каталога: ``ask_directory(заголовок) -> путь | None``.
        self.ask_directory: Callable[[str], str | None] = self._ask_directory
        #: Ввод строки: ``ask_text(заголовок, подпись, текст) -> строка | None``.
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text
        #: Вопрос о несохранённых изменениях: ``"save"``, ``"discard"`` или ``"cancel"``.
        self.ask_save_changes: Callable[[], str] = self._ask_save_changes
        #: Сообщение об ошибке: ``show_error(заголовок, текст)``.
        self.show_error: Callable[[str, str], None] = self._show_error

        self._doc.confirm_discard = self._confirm_discard
        self._doc.pending_edits_hook = self.commit_pending_edits
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.setDockNestingEnabled(True)

        self._create_widgets()
        self._create_docks()
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._connect_signals()
        self.resize(*self._default_size())
        if restore_settings:
            self.restore_settings()
        self._rebuild_recent_menu()
        self._sync_view_actions()
        self._update_title()
        self._update_actions()
        self.canvas.setFocus()

    # --- свойства -------------------------------------------------------------------------------
    @property
    def document(self) -> FootprintDocument:
        """Документ окна."""
        return self._doc

    @property
    def settings(self) -> QSettings:
        """Объект настроек окна."""
        return self._settings

    def _default_size(self) -> tuple[int, int]:
        """Размер окна по умолчанию: 1440×900, но не больше 90 % доступной области экрана
        (ТЗ: мониторы от 1280×720)."""
        w, h = _DEFAULT_SIZE
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            if area.width() > 0 and area.height() > 0:
                w = min(w, int(area.width() * 0.9))
                h = min(h, int(area.height() * 0.9))
        return (max(w, 640), max(h, 480))

    def docks(self) -> list[QDockWidget]:
        """Док-панели окна."""
        return [self.dock_libraries, self.dock_layers, self.dock_properties, self.dock_pads,
                self.dock_items]

    # --- построение -----------------------------------------------------------------------------
    def _create_widgets(self) -> None:
        doc = self._doc
        #: Канва корпуса (центральный виджет).
        self.canvas = PreviewCanvas(doc, self)
        self.setCentralWidget(self.canvas)
        #: Дерево библиотек.
        self.library_tree = LibraryTree(self)
        #: Панель свойств корпуса.
        self.props_panel = PropertiesPanel(doc, self)
        #: Таблица площадок.
        self.pad_table = PadTable(doc, self)
        #: Таблица графики и текстов.
        self.items_table = ItemsTable(doc, self)
        #: Панель видимости слоёв.
        self.layers_panel = LayersPanel(self.canvas, self)

    def _make_dock(self, title: str, name: str, widget: QWidget,
                   area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _create_docks(self) -> None:
        left = Qt.DockWidgetArea.LeftDockWidgetArea
        right = Qt.DockWidgetArea.RightDockWidgetArea
        bottom = Qt.DockWidgetArea.BottomDockWidgetArea
        # левая и правая панели — во всю высоту, таблицы — под канвой
        self.setCorner(Qt.Corner.BottomLeftCorner, left)
        self.setCorner(Qt.Corner.BottomRightCorner, right)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.dock_libraries = self._make_dock("Библиотеки", "dock_libraries",
                                              self.library_tree, left)
        self.dock_layers = self._make_dock("Слои", "dock_layers", self.layers_panel, left)
        # длинные строки формы (флажки атрибутов) переносятся под подпись, если панель узкая
        form = self.props_panel.layout()
        if isinstance(form, QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.props_panel)
        self.dock_properties = self._make_dock("Свойства корпуса", "dock_properties", scroll,
                                               right)
        self.dock_pads = self._make_dock("Площадки", "dock_pads", self.pad_table, bottom)
        self.dock_items = self._make_dock("Графика и тексты", "dock_items", self.items_table,
                                          bottom)
        self.tabifyDockWidget(self.dock_pads, self.dock_items)
        self.dock_pads.raise_()

    def _apply_default_dock_sizes(self) -> None:
        """Начальные размеры панелей (пропорционально окну; при 1440×900 — слева 265,
        справа 475, снизу 270 пикселей)."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        self.resizeDocks([self.dock_libraries, self.dock_properties],
                         [min(265, int(w * 0.19)), min(475, int(w * 0.33))],
                         Qt.Orientation.Horizontal)
        left = max(h - 100, 200)
        self.resizeDocks([self.dock_libraries, self.dock_layers],
                         [int(left * 0.45), int(left * 0.55)], Qt.Orientation.Vertical)
        self.resizeDocks([self.dock_pads], [min(270, int(h * 0.3))], Qt.Orientation.Vertical)

    def _act(self, text: str, slot: Callable[..., Any], *, shortcut: Any = None, tip: str = "",
             icon: QIcon | None = None, checkable: bool = False,
             context: Qt.ShortcutContext | None = None) -> QAction:
        """Создать действие окна (пункт меню/кнопку)."""
        act = QAction(text, self)
        seqs: list[QKeySequence] = []
        if shortcut is not None:
            items = shortcut if isinstance(shortcut, (list, tuple)) else [shortcut]
            seqs = [s if isinstance(s, QKeySequence) else QKeySequence(s) for s in items]
            act.setShortcuts(seqs)
        if context is not None:
            act.setShortcutContext(context)
        if icon is not None:
            act.setIcon(icon)
        plain = text.rstrip("…").replace("&", "")
        if tip:
            act.setStatusTip(tip)
        keys = seqs[0].toString(QKeySequence.SequenceFormat.NativeText) if seqs else ""
        act.setToolTip(f"{tip or plain} ({keys})" if keys else (tip or plain))
        if checkable:
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, f=slot: f(bool(checked)))
        else:
            act.triggered.connect(lambda _checked=False, f=slot: f())
        return act

    def _create_actions(self) -> None:
        style = self.style()
        fg = self.palette().color(QPalette.ColorRole.WindowText)
        sp = QStyle.StandardPixmap
        canvas_only = Qt.ShortcutContext.WidgetWithChildrenShortcut

        # Файл
        self.act_new = self._act(
            "Создать корпус…", self.new_footprint_interactive, shortcut="Ctrl+N",
            tip="Создать пустой корпус",
            icon=_themed("document-new", style.standardIcon(sp.SP_FileIcon)))
        self.act_open = self._act(
            "Открыть файл…", self.open_file_interactive, shortcut="Ctrl+O",
            tip="Открыть файл корпуса (.kicad_mod или .mod)",
            icon=_themed("document-open", style.standardIcon(sp.SP_DialogOpenButton)))
        self.act_open_library = self._act(
            "Открыть библиотеку…", self.open_library_interactive, shortcut="Ctrl+Shift+O",
            tip="Открыть каталог библиотеки .pretty в дереве библиотек",
            icon=_themed("folder-open", style.standardIcon(sp.SP_DirOpenIcon)))
        self.act_save = self._act(
            "Сохранить", self.save, shortcut="Ctrl+S", tip="Записать корпус в файл",
            icon=_themed("document-save", style.standardIcon(sp.SP_DialogSaveButton)))
        self.act_save_as = self._act(
            "Сохранить как…", self.save_as_interactive, shortcut="Ctrl+Shift+S",
            tip="Записать корпус в другой файл")
        self.act_export_svg = self._act(
            "Экспорт SVG…", self.export_svg_interactive,
            tip="Записать изображение корпуса в формате SVG (видимые слои)")
        self.act_export_png = self._act(
            "Экспорт PNG…", self.export_png_interactive,
            tip="Записать изображение корпуса в формате PNG (видимые слои)")
        self.act_clear_recent = self._act("Очистить список", self.clear_recent_files,
                                          tip="Очистить список недавних файлов")
        self.act_quit = self._act("Выход", self.close, shortcut="Ctrl+Q",
                                  tip="Закрыть программу")
        self.act_quit.setMenuRole(QAction.MenuRole.QuitRole)

        # Правка
        stack = self._doc.undo_stack
        self.act_undo = stack.createUndoAction(self, "Отменить")
        self.act_undo.setShortcuts([QKeySequence("Ctrl+Z")])
        self.act_undo.setIcon(_themed("edit-undo", style.standardIcon(sp.SP_ArrowBack)))
        self.act_undo.setStatusTip("Отменить последнее изменение")
        self.act_redo = stack.createRedoAction(self, "Повторить")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        self.act_redo.setIcon(_themed("edit-redo", style.standardIcon(sp.SP_ArrowForward)))
        self.act_redo.setStatusTip("Повторить отменённое изменение")
        self.act_delete = self._act(
            "Удалить", self.delete_selected, shortcut="Del",
            tip="Удалить выделенный элемент (в таблице — выделенные строки)",
            icon=_themed("edit-delete", _tool_icon("delete", fg)))
        self.act_properties = self._act(
            "Свойства элемента…", self.edit_properties, shortcut=["Return", "Enter"],
            tip="Свойства выделенного элемента (Enter на канве или двойной щелчок)",
            context=canvas_only)
        self.canvas.addAction(self.act_properties)
        self.act_batch = self._act(
            "Групповые операции над площадками…", self.pad_batch,
            tip="Перенумерация, тип, форма, размер, отверстие, слои, поворот и сдвиг площадок")
        self.act_add_pad = self._act("Добавить площадку", self.add_pad,
                                     tip="Добавить площадку в центр вида",
                                     icon=_tool_icon("pad", fg))
        self.act_add_line = self._act("Добавить линию", self.add_line,
                                      tip="Добавить линию на F.SilkS в центр вида",
                                      icon=_tool_icon("line", fg))
        self.act_add_rect = self._act("Добавить прямоугольник", self.add_rect,
                                      tip="Добавить прямоугольник на F.SilkS в центр вида",
                                      icon=_tool_icon("rect", fg))
        self.act_add_circle = self._act("Добавить окружность", self.add_circle,
                                        tip="Добавить окружность на F.SilkS в центр вида",
                                        icon=_tool_icon("circle", fg))
        self.act_add_text = self._act("Добавить текст", self.add_text,
                                      tip="Добавить текст на F.SilkS в центр вида",
                                      icon=_tool_icon("text", fg))

        # Корпус
        self.act_validate = self._act("Проверить", self.validate, shortcut="F7",
                                      tip="Проверить корпус и показать замечания",
                                      icon=_tool_icon("validate", fg))
        self.act_generate = self._act(
            "Создать типовой корпус…", self.generate, shortcut="Ctrl+G",
            tip="Создать корпус генератором (DIP, штыревой разъём, резистор, …)",
            icon=_tool_icon("generate", fg))
        self.act_move = self._act("Сдвинуть…", self.move_interactive,
                                  tip="Сдвинуть все элементы корпуса")
        self.act_rotate = self._act("Повернуть…", self.rotate_interactive,
                                    tip="Повернуть все элементы корпуса вокруг точки")
        self.act_flip = self._act(
            "Отразить", self.flip_footprint,
            tip="Перенести корпус на другую сторону платы (зеркально по X, слои F ↔ B)")
        self.act_renumber = self._act("Перенумеровать площадки…", self.renumber_interactive,
                                      tip="Перенумеровать выводы корпуса")
        self.act_footprint_properties = self._act(
            "Свойства корпуса", self.show_footprint_properties,
            tip="Показать панель свойств корпуса")

        # Вид
        self.act_fit = self._act(
            "Вписать", self.canvas.fit, shortcut="F",
            tip="Показать корпус целиком (F или Home на канве)",
            icon=_themed("zoom-fit-best", _tool_icon("fit", fg)), context=canvas_only)
        self.canvas.addAction(self.act_fit)
        self.act_zoom_in = self._act("Увеличить", self.canvas.zoom_in,
                                     shortcut=["Ctrl++", "Ctrl+="],
                                     icon=_themed("zoom-in", _tool_icon("zoom_in", fg)))
        self.act_zoom_out = self._act("Уменьшить", self.canvas.zoom_out, shortcut="Ctrl+-",
                                      icon=_themed("zoom-out", _tool_icon("zoom_out", fg)))
        self.grid_group = QActionGroup(self)
        self.grid_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.Exclusive)
        #: Действия шагов сетки ``{шаг: действие}``.
        self.grid_actions: dict[float, QAction] = {}
        for step in GRID_STEPS:
            a = QAction(f"{format_mm(step)} мм", self)
            a.setCheckable(True)
            a.setData(step)
            a.setStatusTip(f"Шаг сетки {format_mm(step)} мм")
            a.triggered.connect(lambda _checked=False, s=step: self.set_grid(s))
            self.grid_group.addAction(a)
            self.grid_actions[step] = a
        self.act_grid_visible = self._act("Показывать сетку", self._set_grid_visible,
                                          checkable=True, tip="Показывать сетку на канве")
        self.act_snap = self._act("Привязка к сетке", self._set_snap, checkable=True,
                                  tip="Привязывать перетаскиваемые элементы к узлам сетки")
        self.act_show_hidden = self._act("Показывать скрытые тексты", self._set_show_hidden,
                                         checkable=True,
                                         tip="Рисовать на канве скрытые тексты и поля")
        self.act_show_all_layers = self._act("Показать все слои", self.canvas.show_all_layers,
                                             tip="Сделать видимыми все слои")

        # Справка
        self.act_about = self._act("О программе", self.about,
                                   tip="Версия kicadfp, Python, PySide6 и Qt")
        self.act_about.setMenuRole(QAction.MenuRole.AboutRole)
        self.act_about_qt = self._act("О Qt", QApplication.aboutQt, tip="Сведения о Qt")
        self.act_about_qt.setMenuRole(QAction.MenuRole.AboutQtRole)

    def _create_menus(self) -> None:
        mb = self.menuBar()
        m = self.menu_file = mb.addMenu("&Файл")
        m.addActions([self.act_new, self.act_open, self.act_open_library])
        self.menu_recent = m.addMenu("Недавние файлы")
        self.menu_recent.setToolTipsVisible(True)
        m.addSeparator()
        m.addActions([self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_export_svg, self.act_export_png])
        m.addSeparator()
        m.addAction(self.act_quit)

        m = self.menu_edit = mb.addMenu("&Правка")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_delete, self.act_properties, self.act_batch])
        m.addSeparator()
        m.addActions([self.act_add_pad, self.act_add_line, self.act_add_rect,
                      self.act_add_circle, self.act_add_text])

        m = self.menu_footprint = mb.addMenu("&Корпус")
        m.addActions([self.act_validate, self.act_generate])
        m.addSeparator()
        m.addActions([self.act_move, self.act_rotate, self.act_flip, self.act_renumber])
        m.addSeparator()
        m.addAction(self.act_footprint_properties)

        m = self.menu_view = mb.addMenu("&Вид")
        m.addActions([self.act_fit, self.act_zoom_in, self.act_zoom_out])
        m.addSeparator()
        self.menu_grid = m.addMenu("Сетка")
        self.menu_grid.addActions(self.grid_group.actions())
        self.menu_grid.addSeparator()
        self.menu_grid.addAction(self.act_grid_visible)
        m.addActions([self.act_snap, self.act_show_hidden, self.act_show_all_layers])
        m.addSeparator()
        self.menu_panels = m.addMenu("Панели")
        for dock in self.docks():
            self.menu_panels.addAction(dock.toggleViewAction())

        m = self.menu_help = mb.addMenu("&Справка")
        m.addActions([self.act_about, self.act_about_qt])

    def _create_toolbar(self) -> None:
        tb = self.toolbar = QToolBar("Панель инструментов", self)
        tb.setObjectName("toolbar_main")
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        groups = (
            (self.act_new, self.act_open, self.act_save),
            (self.act_undo, self.act_redo),
            (self.act_add_pad, self.act_add_line, self.act_add_rect, self.act_add_circle,
             self.act_add_text, self.act_delete),
            (self.act_validate, self.act_generate),
            (self.act_fit, self.act_zoom_in, self.act_zoom_out),
        )
        for i, group in enumerate(groups):
            if i:
                tb.addSeparator()
            tb.addActions(list(group))
        self.menu_panels.addSeparator()
        self.menu_panels.addAction(tb.toggleViewAction())

    def _create_status_bar(self) -> None:
        sb = self.statusBar()
        #: Координаты курсора на канве, мм.
        self.coords_label = QLabel(self)
        self.coords_label.setMinimumWidth(200)
        self.coords_label.setToolTip("Координаты курсора, мм (ось Y направлена вниз)")
        #: Шаг сетки.
        self.grid_label = QLabel(self)
        #: Имя файла документа.
        self.file_label = QLabel(self)
        #: Признак несохранённых изменений («изменён»).
        self.modified_label = QLabel(self)
        font = QFont(self.modified_label.font())
        font.setBold(True)
        self.modified_label.setFont(font)
        for w in (self.coords_label, self.grid_label, self.file_label, self.modified_label):
            sb.addPermanentWidget(w)
        self._set_coords(None, None)

    def _connect_signals(self) -> None:
        doc = self._doc
        doc.changed.connect(self._on_changed)
        doc.selection_changed.connect(self._on_selection_changed)
        doc.modified_changed.connect(self._on_modified_changed)
        doc.document_changed.connect(self._on_document_changed)
        doc.path_changed.connect(self._on_path_changed)
        doc.saved.connect(self._on_saved)
        c = self.canvas
        c.cursor_moved.connect(self._set_coords)
        c.grid_changed.connect(self._on_grid_changed)
        c.viewport().installEventFilter(self)
        self.pad_table.installEventFilter(self)
        self.items_table.installEventFilter(self)
        self.pad_table.batch_requested.connect(self.pad_batch)
        for source in (self.pad_table.pad_model(), self.items_table.items_model(),
                       self.props_panel, self.library_tree):
            source.error.connect(self._status)
        t = self.library_tree
        t.open_requested.connect(self._on_open_requested)
        t.footprint_renamed.connect(self._on_footprint_renamed)
        t.footprint_removed.connect(self._on_footprint_removed)

    # --- подменяемые вопросы (реализация по умолчанию) ----------------------------------------
    def _exec_dialog(self, dialog: QDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _exec_menu(self, menu: QMenu, pos: QPoint) -> Any:
        return menu.exec(pos)

    def _start_dir(self) -> str:
        if self._doc.path is not None:
            return str(self._doc.path.parent)
        if self._last_dir and Path(self._last_dir).is_dir():
            return self._last_dir
        return str(Path.home())

    def _ask_open_file(self, title: str, file_filter: str) -> str | None:
        path, _selected = QFileDialog.getOpenFileName(self, title, self._start_dir(), file_filter)
        return path or None

    def _ask_save_file(self, title: str, file_filter: str, suggested: str) -> str | None:
        path, _selected = QFileDialog.getSaveFileName(self, title, suggested, file_filter)
        return path or None

    def _ask_directory(self, title: str) -> str | None:
        path = QFileDialog.getExistingDirectory(self, title, self._start_dir())
        return path or None

    def _ask_text(self, title: str, label: str, text: str) -> str | None:
        value, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, text)
        return value if ok else None

    def _ask_save_changes(self) -> str:
        name = self._doc.display_name or "без имени"
        buttons = QMessageBox.StandardButton
        box = QMessageBox(QMessageBox.Icon.Warning, "Несохранённые изменения",
                          f"Корпус «{name}» изменён. Сохранить изменения?",
                          buttons.Save | buttons.Discard | buttons.Cancel, self)
        box.setInformativeText("Если не сохранить, изменения будут потеряны.")
        box.setDefaultButton(buttons.Save)
        box.setEscapeButton(buttons.Cancel)
        for b, text in ((buttons.Save, "Сохранить"), (buttons.Discard, "Не сохранять"),
                        (buttons.Cancel, "Отмена")):
            box.button(b).setText(text)
        box.exec()
        clicked = box.standardButton(box.clickedButton())
        box.deleteLater()
        if clicked == buttons.Save:
            return "save"
        if clicked == buttons.Discard:
            return "discard"
        return "cancel"

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _confirm_discard(self) -> bool:
        """``confirm_discard`` документа: спросить (:attr:`ask_save_changes`); «Сохранить»
        записывает корпус и разрешает продолжить только при успешной записи."""
        answer = self.ask_save_changes()
        if answer == "save":
            return self.save()
        return answer == "discard"

    def commit_pending_edits(self) -> None:
        """Применить незавершённый ввод: набранное в поле панели свойств корпуса и в
        открытом редакторе ячейки таблицы площадок/графики (как Enter). Вызывается
        документом перед записью и вопросом о несохранённых изменениях
        (:attr:`FootprintDocument.pending_edits_hook
        <kicadfp.gui.document.FootprintDocument.pending_edits_hook>`) и перед закрытием
        окна."""
        for name in ("pad_table", "items_table", "props_panel"):
            widget = getattr(self, name, None)  # None — окно ещё строится
            if widget is None:
                continue
            try:
                if isinstance(widget, DocumentTableView):
                    widget.commit_pending_edit()
                else:
                    widget.commit_pending()
            except RuntimeError:  # виджет уже удалён (закрытие окна)
                pass

    def confirm_close(self) -> bool:
        """Можно ли закрыть открытый корпус: без несохранённых изменений (с учётом
        незавершённого ввода, :meth:`commit_pending_edits`) — да, иначе решает
        ``document.confirm_discard()``."""
        doc = self._doc
        doc.commit_pending_edits()
        if doc.fp is None or not doc.is_modified:
            return True
        return bool(doc.confirm_discard())

    # --- строка состояния, заголовок, доступность действий -----------------------------------
    def _status(self, message: str, timeout: int = _STATUS_MS) -> None:
        self.statusBar().showMessage(str(message), timeout)

    def _set_coords(self, x: float | None, y: float | None) -> None:
        if x is None or y is None:
            self.coords_label.setText("X —  Y —")
            return
        x = 0.0 if abs(x) < 5e-4 else x
        y = 0.0 if abs(y) < 5e-4 else y
        self.coords_label.setText(f"X {x:.3f}  Y {y:.3f} мм")

    def _update_grid_label(self) -> None:
        c = self.canvas
        text = f"Сетка {format_mm(c.grid)} мм"
        if not c.grid_visible:
            text += " (скрыта)"
        self.grid_label.setText(text)

    def _update_title(self) -> None:
        doc = self._doc
        if doc.fp is None:
            self.setWindowTitle(APP_NAME)
            self.setWindowModified(False)
            self.file_label.setText("")
            self.file_label.setToolTip("")
        else:
            # «[*]» в имени — не метка изменений (Qt: «[*][*]» выводится как «[*]»)
            name = doc.display_name.replace("[*]", "[*][*]")
            self.setWindowTitle(f"{APP_NAME} — {name} [*]")
            self.setWindowModified(doc.is_modified)
            if doc.path is None:
                self.file_label.setText("не сохранён")
                self.file_label.setToolTip("Корпус ещё не записан в файл")
            else:
                self.file_label.setText(doc.path.name)
                self.file_label.setToolTip(str(doc.path))
        self.modified_label.setText("изменён" if doc.is_modified else "")

    @staticmethod
    def _removable(item: Any) -> bool:
        if item is None or isinstance(item, Footprint):
            return False
        return not (isinstance(item, Text) and item.kind in ("reference", "value"))

    def _update_actions(self) -> None:
        doc = self._doc
        fp = doc.fp
        has = fp is not None
        for a in (self.act_save, self.act_save_as, self.act_export_svg, self.act_export_png,
                  self.act_add_pad, self.act_add_line, self.act_add_rect, self.act_add_circle,
                  self.act_add_text, self.act_validate, self.act_move, self.act_rotate,
                  self.act_flip, self.act_footprint_properties):
            a.setEnabled(has)
        try:
            has_pads = fp is not None and bool(fp.pads)
        except Exception:  # noqa: BLE001
            has_pads = False
        self.act_batch.setEnabled(has_pads)
        self.act_renumber.setEnabled(has_pads)
        sel = doc.selected
        self.act_delete.setEnabled(has and self._removable(sel))
        self.act_properties.setEnabled(has and isinstance(sel, (Pad, Graphic, Text, Model)))

    # --- сигналы документа ----------------------------------------------------------------------
    def _on_changed(self) -> None:
        self._update_title()
        self._update_actions()

    def _on_selection_changed(self, _item: Any) -> None:
        self._update_actions()

    def _on_modified_changed(self, _modified: bool) -> None:
        self._update_title()

    def _on_document_changed(self) -> None:
        self._update_title()
        self._update_actions()

    def _on_path_changed(self, _path: Any) -> None:
        self._update_title()

    def _on_saved(self, path: Any) -> None:
        p = _abs(path)
        self.add_recent_file(p)
        self._track_in_tree(p)
        self._status(f"Сохранено: {p}")

    # --- дерево библиотек -----------------------------------------------------------------------
    def _on_open_requested(self, path: Any) -> None:
        self.open_file(path)

    def _on_footprint_renamed(self, old: Any, new: Any) -> None:
        old_p, new_p = _abs(old), _abs(new)
        self._recent = [str(new_p) if _same_path(Path(r), old_p) or r == str(old_p) else r
                        for r in self._recent]
        self._store_recent()
        doc = self._doc
        if doc.fp is None or doc.path is None or doc.path != old_p:
            return
        was_modified = doc.is_modified
        doc.set_path(new_p, library=self.library_tree.library_for(new_p))
        # Library.rename записал новое имя и в файл: то же имя — открытому корпусу
        new_name = new_p.name[:-len(FOOTPRINT_EXT)] if new_p.name.endswith(FOOTPRINT_EXT) \
            else new_p.stem
        old_name = doc.fp.name
        if old_name != new_name:

            def rename(fp: Footprint) -> None:
                # правило Library.rename: Value, равный старому имени, тоже меняется
                fp.name = new_name
                value = fp.value
                if value is not None and value.text == old_name:
                    value.text = new_name

            try:
                doc.apply(OperationCommand(doc, rename, "переименование корпуса"))
                if not was_modified:
                    doc.undo_stack.setClean()  # содержимое совпадает с файлом
            except (ValueError, TypeError, RuntimeError) as e:
                self._status(f"Не удалось переименовать открытый корпус: {e}")
        self._status(f"Корпус переименован: {new_p.name}")

    def _on_footprint_removed(self, path: Any) -> None:
        doc = self._doc
        if doc.path is not None and doc.path == _abs(path):
            self._status("Файл открытого корпуса удалён; «Сохранить» запишет его снова",
                         10000)

    def _track_in_tree(self, path: Path) -> None:
        """Показать файл в дереве библиотек: библиотеку ``.pretty``, в которой он лежит
        (открыть её, если она не открыта), или сам файл отдельным корнем."""
        tree = self.library_tree
        try:
            parent = path.parent
            if path.suffix == FOOTPRINT_EXT and parent.name.lower().endswith(".pretty") \
                    and parent.is_dir():
                lib = tree.library_for(path)
                if lib is None:
                    own = self._doc.library
                    tree.add_library(own if own is not None and _abs(own.path) == _abs(parent)
                                     else parent)
                elif not tree.index_for_path(path).isValid():
                    tree.refresh(lib)
            elif path.is_file():
                tree.add_file(path)
            tree.select_path(path)
        except (OSError, ValueError, KeyError) as e:
            self._status(f"Дерево библиотек: {_error_text(e)}")

    # --- открытие -------------------------------------------------------------------------------
    def open_path(self, path: str | PathLike[str]) -> bool:
        """Открыть путь: каталог — как библиотеку (:meth:`open_library`), файл — как
        корпус (:meth:`open_file`). ``False`` — ошибка (показана) или отмена."""
        p = _abs(path)
        if p.is_dir():
            return self.open_library(p) is not None
        return self.open_file(p)

    def open_file(self, path: str | PathLike[str], *, library: Library | None = None) -> bool:
        """Открыть файл корпуса в документе (при несохранённых изменениях — вопрос).

        Ошибка чтения (синтаксис — «строка N, позиция M: …», нет файла, несколько корпусов
        в ``.mod``) показывается :attr:`show_error`; открытый корпус при этом не меняется.
        Файл добавляется в недавние и в дерево библиотек. ``False`` — ошибка или отмена."""
        p = _abs(path)
        if library is None and p.suffix == FOOTPRINT_EXT:
            library = self.library_tree.library_for(p)
        try:
            ok = self._doc.open(p, library=library)
        except Exception as e:  # noqa: BLE001 — любая ошибка чтения показывается пользователю
            text = _error_text(e)
            self.show_error("Ошибка открытия файла", f"Не удалось открыть файл\n{p}\n\n{text}")
            self._status(f"Не удалось открыть {p.name}: {text}")
            return False
        if not ok:
            self._status("Открытие отменено")
            return False
        self._remember_dir(p.parent)
        self.add_recent_file(p)
        self._track_in_tree(p)
        self.canvas.setFocus()
        if self._doc.path is None:
            self._status(f"Корпус прочитан из {p.name} (старый формат): сохраните его как "
                         f".kicad_mod", 10000)
        else:
            self._status(f"Открыт {p}")
        return True

    def open_file_interactive(self) -> bool:
        """«Открыть файл…»: выбрать файл (:attr:`ask_open_file`) и открыть его."""
        path = self.ask_open_file("Открыть корпус", OPEN_FILTER)
        return bool(path) and self.open_path(path)

    def open_library(self, path: str | PathLike[str]) -> Library | None:
        """Открыть каталог библиотеки ``.pretty`` в дереве библиотек (раскрыть и показать
        панель). ``None`` — ошибка (показана)."""
        p = _abs(path)
        try:
            lib = self.library_tree.add_library(p)
        except Exception as e:  # noqa: BLE001
            self.show_error("Ошибка открытия библиотеки",
                            f"Не удалось открыть библиотеку\n{p}\n\n{_error_text(e)}")
            return None
        self.library_tree.expand_library(lib)
        self.dock_libraries.show()
        self.dock_libraries.raise_()
        self._remember_dir(p)
        self.add_recent_file(p)
        try:
            count = len(self.library_tree.children_names(lib))
        except KeyError:
            count = 0
        self._status(f"Открыта библиотека {lib.name}: корпусов {count}")
        return lib

    def open_library_interactive(self) -> Library | None:
        """«Открыть библиотеку…»: выбрать каталог (:attr:`ask_directory`) и открыть его."""
        path = self.ask_directory("Открыть библиотеку .pretty")
        return self.open_library(path) if path else None

    def new_footprint(self, name: str) -> bool:
        """Создать пустой корпус ``name`` (формат KiCad 9). ``False`` — пустое имя, ошибка
        или отказ отбросить изменения текущего корпуса."""
        name = str(name).strip()
        if not name:
            self.show_error("Создать корпус", "Имя корпуса не может быть пустым")
            return False
        try:
            ok = self._doc.new_footprint(name)
        except (ValueError, TypeError) as e:
            self.show_error("Создать корпус", f"Не удалось создать корпус: {e}")
            return False
        if ok:
            self.canvas.setFocus()
            self._status(f"Создан корпус {name}")
        return ok

    def new_footprint_interactive(self) -> bool:
        """«Создать корпус…»: спросить имя (:attr:`ask_text`) и создать корпус."""
        name = self.ask_text("Создать корпус", "Имя нового корпуса:", "NewFootprint")
        if name is None:
            return False
        return self.new_footprint(name)

    # --- недавние файлы -------------------------------------------------------------------------
    def recent_files(self) -> list[str]:
        """Недавние файлы и библиотеки (новые — первыми)."""
        return list(self._recent)

    def _store_recent(self) -> None:
        self._settings.setValue("recent_files", list(self._recent))
        self._rebuild_recent_menu()

    def add_recent_file(self, path: str | PathLike[str]) -> None:
        """Добавить путь в начало списка недавних (не более :data:`MAX_RECENT`)."""
        s = str(_abs(path))
        self._recent = [s, *(r for r in self._recent if r != s)][:MAX_RECENT]
        self._store_recent()

    def clear_recent_files(self) -> None:
        """Очистить список недавних файлов."""
        self._recent = []
        self._store_recent()

    def open_recent(self, path: str) -> bool:
        """Открыть недавний файл или библиотеку; исчезнувший путь убирается из списка."""
        p = _abs(path)
        if not p.exists():
            self._recent = [r for r in self._recent if r != str(p)]
            self._store_recent()
            self.show_error("Недавние файлы",
                            f"Файл или каталог не найден:\n{p}\n\nОн убран из списка недавних.")
            return False
        return self.open_path(p)

    def _rebuild_recent_menu(self) -> None:
        menu = self.menu_recent
        menu.clear()
        for i, s in enumerate(self._recent, 1):
            name = Path(s).name.replace("&", "&&")  # «&» в имени — не мнемоника
            act = menu.addAction(f"&{i} {name}" if i < 10 else f"{i} {name}")
            act.setData(s)
            act.setToolTip(s)
            act.setStatusTip(s)
            act.triggered.connect(lambda _checked=False, path=s: self.open_recent(path))
        if self._recent:
            menu.addSeparator()
        menu.addAction(self.act_clear_recent)
        self.act_clear_recent.setEnabled(bool(self._recent))

    def recent_actions(self) -> list[QAction]:
        """Пункты недавних файлов в меню (без «Очистить список»)."""
        return [a for a in self.menu_recent.actions() if a.data()]

    def _remember_dir(self, directory: Path) -> None:
        self._last_dir = str(directory)
        self._settings.setValue("dirs/last", self._last_dir)

    # --- запись и экспорт -----------------------------------------------------------------------
    def save(self) -> bool:
        """«Сохранить»: записать корпус в его файл; корпус без файла — «Сохранить как…».
        Ошибка записи показывается; ``True`` — записано."""
        doc = self._doc
        if doc.fp is None:
            return False
        if doc.path is None:
            return self.save_as_interactive()
        try:
            doc.save()
        except Exception as e:  # noqa: BLE001 — ошибка записи показывается пользователю
            self.show_error("Ошибка записи",
                            f"Не удалось записать файл\n{doc.path}\n\n{_error_text(e)}")
            return False
        return True

    def save_as(self, path: str | PathLike[str]) -> bool:
        """Записать корпус в файл ``path`` и сделать его файлом документа (расширение
        ``.kicad_mod`` добавляется, если его нет). ``True`` — записано."""
        doc = self._doc
        if doc.fp is None:
            return False
        p = _abs(path)
        if not p.name.lower().endswith(FOOTPRINT_EXT):
            p = p.with_name(p.name + FOOTPRINT_EXT)
        try:
            doc.save_as(p)
        except Exception as e:  # noqa: BLE001
            self.show_error("Ошибка записи", f"Не удалось записать файл\n{p}\n\n{_error_text(e)}")
            return False
        self._remember_dir(p.parent)
        return True

    def _suggested_path(self, suffix: str) -> str:
        doc = self._doc
        if doc.path is not None:
            stem = doc.path.name[:-len(FOOTPRINT_EXT)] if doc.path.name.endswith(FOOTPRINT_EXT) \
                else doc.path.stem
            return str(doc.path.parent / f"{stem}{suffix}")
        try:
            name = sanitize_name(doc.fp.name) if doc.fp is not None else "footprint"
        except (ValueError, TypeError):
            name = "footprint"
        return str(Path(self._start_dir()) / f"{name or 'footprint'}{suffix}")

    def save_as_interactive(self) -> bool:
        """«Сохранить как…»: выбрать файл (:attr:`ask_save_file`) и записать корпус."""
        if self._doc.fp is None:
            return False
        path = self.ask_save_file("Сохранить корпус как", SAVE_FILTER,
                                  self._suggested_path(FOOTPRINT_EXT))
        return bool(path) and self.save_as(path)

    def render_options(self) -> dict[str, Any]:
        """Параметры :func:`kicadfp.render.render_svg` по виду канвы: видимые слои, сетка,
        скрытые тексты, номера площадок."""
        c = self.canvas
        hidden = {n for n in c.hidden_layers if n not in PSEUDO_LAYER_TITLES}
        layers = None if not hidden else [n for n in _L.ALL_LAYERS if n not in hidden]
        return {"layers": layers, "grid": c.grid if c.grid_visible else None,
                "show_hidden": c.show_hidden,
                "pad_numbers": c.is_layer_visible(PAD_NUMBERS_LAYER)}

    def _export(self, path: str | PathLike[str], suffix: str,
                writer: Callable[[Footprint, Path, dict[str, Any]], None]) -> bool:
        fp = self._doc.fp
        if fp is None:
            return False
        p = _abs(path)
        if p.suffix.lower() != suffix:
            p = p.with_name(p.name + suffix)
        try:
            writer(fp, p, self.render_options())
        except Exception as e:  # noqa: BLE001
            self.show_error("Ошибка экспорта",
                            f"Не удалось записать изображение\n{p}\n\n{_error_text(e)}")
            return False
        self._remember_dir(p.parent)
        self._status(f"Изображение записано: {p}")
        return True

    def export_svg(self, path: str | PathLike[str]) -> bool:
        """Записать изображение корпуса в SVG (видимые на канве слои)."""
        return self._export(path, ".svg", lambda fp, p, kw: _render.save_svg(fp, p, **kw))

    def export_png(self, path: str | PathLike[str], width: int = PNG_EXPORT_WIDTH) -> bool:
        """Записать изображение корпуса в PNG шириной ``width`` пикселей."""
        return self._export(path, ".png",
                            lambda fp, p, kw: _render.save_png(fp, p, width=width, **kw))

    def export_svg_interactive(self) -> bool:
        """«Экспорт SVG…»."""
        if self._doc.fp is None:
            return False
        path = self.ask_save_file("Экспорт SVG", SVG_FILTER, self._suggested_path(".svg"))
        return bool(path) and self.export_svg(path)

    def export_png_interactive(self) -> bool:
        """«Экспорт PNG…»."""
        if self._doc.fp is None:
            return False
        path = self.ask_save_file("Экспорт PNG", PNG_FILTER, self._suggested_path(".png"))
        return bool(path) and self.export_png(path)

    # --- правка ---------------------------------------------------------------------------------
    def delete_selected(self) -> int:
        """«Удалить»: в таблице с фокусом — выделенные строки (одним шагом отмены), в дереве
        библиотек — файл корпуса (с подтверждением), иначе — выделенный элемент. Reference
        и Value не удаляются. Возвращает число удалённых элементов."""
        focus = QApplication.focusWidget()
        if _is_within(focus, self.pad_table) and self.pad_table.selected_rows():
            return self.pad_table.remove_selected()
        if _is_within(focus, self.items_table) and self.items_table.selected_rows():
            n = self.items_table.remove_selected()
            if not n:
                self._status(_REMOVE_FORBIDDEN)
            return n
        if _is_within(focus, self.library_tree):
            return 1 if self.library_tree.delete_selected_interactive() is not None else 0
        return 1 if self.remove_item(self._doc.selected) else 0

    def remove_item(self, item: Any) -> bool:
        """Удалить элемент корпуса командой (Reference/Value — нельзя)."""
        doc = self._doc
        if doc.fp is None or item is None or isinstance(item, Footprint):
            return False
        if not self._removable(item):
            self._status(_REMOVE_FORBIDDEN)
            return False
        try:
            return bool(doc.apply(RemoveItemCommand(doc, item)))
        except (ValueError, TypeError, RuntimeError) as e:
            self._status(f"Не удалось удалить: {e}")
            return False

    def edit_properties(self, item: Any = None) -> bool:
        """«Свойства элемента…»: диалог :class:`~kicadfp.gui.dialogs.ItemPropertiesDialog`
        для ``item`` (по умолчанию — выделенного); у корпуса — панель свойств корпуса.
        ``True`` — диалог принят (изменения применены одной командой)."""
        doc = self._doc
        if doc.fp is None:
            return False
        item = doc.selected if item is None else item
        if item is None:
            self._status("Выделите элемент на канве или в таблице")
            return False
        if isinstance(item, Footprint):
            self.show_footprint_properties()
            return True
        if not isinstance(item, (Pad, Graphic, Text, Model)):
            self._status("Свойства этого элемента не редактируются")
            return False
        try:
            dlg = ItemPropertiesDialog(doc, item, self)
        except (ValueError, TypeError) as e:
            self._status(str(e))
            return False
        try:
            return bool(self.exec_dialog(dlg))
        finally:
            dlg.deleteLater()

    def _schedule_properties(self) -> None:
        """Открыть свойства выделенного элемента после обработки текущего события."""
        if not self._properties_pending:
            self._properties_pending = True
            QTimer.singleShot(0, self._run_scheduled_properties)

    def _run_scheduled_properties(self) -> None:
        self._properties_pending = False
        try:
            self.edit_properties()
        except RuntimeError:  # окно уже удалено
            pass

    def pad_batch(self, pads: Sequence[Pad] | None = None) -> bool:
        """«Групповые операции над площадками…»: диалог
        :class:`~kicadfp.gui.dialogs.PadBatchDialog` для ``pads`` (по умолчанию — выделенных
        в таблице площадок или выделенной площадки; пусто — все). ``True`` — применено."""
        doc = self._doc
        fp = doc.fp
        if fp is None or not fp.pads:
            return False
        if pads is None:
            pads = self.pad_table.selected_pads()
            if not pads and isinstance(doc.selected, Pad):
                pads = [doc.selected]
        dlg = PadBatchDialog(doc, list(pads), self)
        try:
            return bool(self.exec_dialog(dlg))
        finally:
            dlg.deleteLater()

    # --- добавление элементов -------------------------------------------------------------------
    def placement_point(self, at: tuple[float, float] | None = None) -> tuple[float, float]:
        """Точка вставки новых элементов: ``at`` (мм) или центр вида канвы — по сетке, если
        включена привязка."""
        c = self.canvas
        if at is None:
            center = c.view_center()
            x, y = float(center.x()), float(center.y())
        else:
            x, y = float(at[0]), float(at[1])
        if c.snap and c.grid > 0:
            return (_geo.snap(x, c.grid), _geo.snap(y, c.grid))
        return (_geo.round_mm(x, 3), _geo.round_mm(y, 3))

    def placement_span(self) -> float:
        """Характерный размер новой фигуры, мм: около восьмой части видимой области,
        кратный шагу сетки (не меньше шага)."""
        c = self.canvas
        vp = c.viewport()
        visible = min(vp.width(), vp.height()) / max(c.zoom, 1e-9)
        g = c.grid if c.grid > 0 else 1.0
        return _geo.round_mm(max(g, round(visible / 8.0 / g) * g))

    def _add_new(self, factory: Callable[[], Any], text: str) -> Any:
        """Добавить элемент, созданный ``factory()``, командой и выделить его. Если
        ``factory`` вернула список элементов, они добавляются одним шагом отмены
        (:class:`~kicadfp.gui.commands.BatchCommand`), выделяется и возвращается первый."""
        doc = self._doc
        if doc.fp is None:
            return None
        try:
            made = factory()
            items = list(made) if isinstance(made, (list, tuple)) else [made]
            cmds = [AddItemCommand(doc, item, text) for item in items]
            cmd: Any = cmds[0] if len(cmds) == 1 else BatchCommand(doc, cmds, text)
            if not doc.apply(cmd):
                return None
        except (ValueError, TypeError, RuntimeError) as e:
            self.show_error("Добавление элемента", f"Не удалось выполнить {text}: {e}")
            return None
        added = cmds[0].item
        try:
            doc.select(added)
        except (ValueError, RuntimeError):
            pass
        self._status(_capitalize(text))
        return added

    def add_pad(self, at: tuple[float, float] | None = None) -> Pad | None:
        """Добавить площадку в точку ``at`` (по умолчанию — в центр вида): копию выделенной
        (иначе последней) площадки со следующим номером, в пустом корпусе — сквозную
        круглую 1.6 мм с отверстием 0.8 мм. Новая площадка выделяется; возвращается она
        (``None`` — корпус не открыт или ошибка)."""
        doc = self._doc
        fp = doc.fp
        if fp is None:
            return None
        x, y = self.placement_point(at)
        number = _next_pad_number(fp)
        template = doc.selected if isinstance(doc.selected, Pad) else None
        if template is None or template.type == "np_thru_hole":
            pads = [p for p in fp.pads if p.type != "np_thru_hole"]
            template = pads[-1] if pads else None

        def make() -> Pad:
            if template is not None:
                new = template.copy()
                new.number = number
                new.position = (x, y)
                return new
            return Pad.new(number, "thru_hole", "circle", x, y, (1.6, 1.6), drill=0.8,
                           profile=fp.profile)

        return self._add_new(make, f"добавление площадки {number}")

    def add_line(self, at: tuple[float, float] | None = None) -> Line | None:
        """Добавить горизонтальную линию на F.SilkS (ширина 0.12 мм) с серединой в точке
        ``at`` (по умолчанию — в центре вида); длина — :meth:`placement_span` × 2."""
        fp = self._doc.fp
        if fp is None:
            return None
        (x, y), d = self.placement_point(at), self.placement_span()
        return self._add_new(lambda: Line.new((x - d, y), (x + d, y), "F.SilkS", 0.12,
                                              profile=fp.profile), "добавление линии")

    def add_rect(self, at: tuple[float, float] | None = None) -> Rect | Line | None:
        """Добавить квадрат-прямоугольник на F.SilkS (ширина 0.12 мм) с центром в точке
        ``at`` (по умолчанию — в центре вида).

        В формате без ``fp_rect`` (KiCad 5 ``module`` и версии до 20200614) прямоугольник
        добавляется, как в библиотеках KiCad 5, четырьмя отрезками ``fp_line`` одним шагом
        отмены; тогда выделяется и возвращается первый отрезок (верхняя сторона)."""
        fp = self._doc.fp
        if fp is None:
            return None
        (x, y), d = self.placement_point(at), self.placement_span()
        profile = fp.profile
        start, end = (x - d, y - d), (x + d, y + d)

        def make() -> Rect | list[Line]:
            if _supports_rect(profile):
                return Rect.new(start, end, "F.SilkS", 0.12, profile=profile)
            corners = [start, (end[0], start[1]), end, (start[0], end[1])]
            return [Line.new(corners[i], corners[(i + 1) % 4], "F.SilkS", 0.12, profile=profile)
                    for i in range(4)]

        return self._add_new(make, "добавление прямоугольника")

    def add_circle(self, at: tuple[float, float] | None = None) -> Circle | None:
        """Добавить окружность на F.SilkS (ширина 0.12 мм) с центром в точке ``at`` (по
        умолчанию — в центре вида)."""
        fp = self._doc.fp
        if fp is None:
            return None
        (x, y), d = self.placement_point(at), self.placement_span()
        return self._add_new(lambda: Circle.new((x, y), d, "F.SilkS", 0.12, profile=fp.profile),
                             "добавление окружности")

    def add_text(self, text: str = "Текст", at: tuple[float, float] | None = None) -> Text | None:
        """Добавить пользовательский текст на F.SilkS (шрифт 1 мм) в точку ``at`` (по
        умолчанию — в центр вида)."""
        fp = self._doc.fp
        if fp is None:
            return None
        x, y = self.placement_point(at)
        return self._add_new(lambda: Text.new(text, "user", x, y, "F.SilkS", size=1.0,
                                              thickness=0.15, profile=fp.profile),
                             "добавление текста")

    # --- корпус ---------------------------------------------------------------------------------
    def validate_dialog(self) -> ValidateDialog:
        """Немодальное окно проверки (создаётся при первом обращении)."""
        if self._validate_dialog is None:
            self._validate_dialog = ValidateDialog(self._doc, self)
        return self._validate_dialog

    def validate(self) -> list[Any]:
        """«Проверить»: показать окно проверки и вернуть замечания."""
        if self._doc.fp is None:
            return []
        dlg = self.validate_dialog()
        if dlg.isVisible():  # уже открыто (возможно, за главным окном) — вывести наверх
            dlg.raise_()
            dlg.activateWindow()
        else:
            dlg.show()
        issues = dlg.run()
        n_err = sum(1 for i in issues if i.level == "error")
        self._status(f"Проверка: ошибок {n_err}, предупреждений {len(issues) - n_err}"
                     if issues else "Проверка: замечаний нет")
        return issues

    def generate(self, generator: str | None = None) -> bool:
        """«Создать типовой корпус…»: диалог :class:`~kicadfp.gui.dialogs.GenerateDialog`;
        построенный корпус открывается как новый несохранённый документ (при
        несохранённых изменениях текущего — вопрос). ``True`` — корпус открыт."""
        try:
            dlg = GenerateDialog(self, generator)
        except KeyError as e:
            self.show_error("Создать типовой корпус", f"Нет такого генератора: {e}")
            return False
        try:
            if not self.exec_dialog(dlg):
                return False
            fp = dlg.footprint if dlg.result() == QDialog.DialogCode.Accepted else None
            if fp is None:
                fp = dlg.build()
            if fp is None:
                self.show_error("Создать типовой корпус",
                                dlg.error_text or "Корпус не построен")
                return False
            ok = self._doc.open_footprint(fp)
        finally:
            dlg.deleteLater()
        if ok:
            self.canvas.setFocus()
            self._status(f"Создан корпус {fp.name}: площадок {len(fp.pads)} (не сохранён)")
        return ok

    def _apply_operation(self, operation: Callable[[Footprint], Any], text: str) -> bool:
        doc = self._doc
        if doc.fp is None:
            return False
        try:
            changed = doc.apply(OperationCommand(doc, operation, text))
        except (ValueError, TypeError, KeyError, RuntimeError) as e:
            self.show_error("Операция не выполнена", f"{_capitalize(text)}: {e}")
            return False
        if changed:
            self._status(_capitalize(text))
        return bool(changed)

    def move_footprint(self, dx: float, dy: float) -> bool:
        """Сдвинуть все элементы корпуса на ``(dx, dy)`` мм одним шагом отмены."""
        dx, dy = float(dx), float(dy)
        return self._apply_operation(lambda fp: fp.move(dx, dy),
                                     f"сдвиг корпуса на ({format_mm(dx)}; {format_mm(dy)}) мм")

    def rotate_footprint(self, angle: float, origin: tuple[float, float] = (0.0, 0.0)) -> bool:
        """Повернуть корпус на ``angle`` градусов (против часовой стрелки на экране) вокруг
        точки ``origin``."""
        a = float(angle)
        o = (float(origin[0]), float(origin[1]))
        return self._apply_operation(lambda fp: fp.rotate(a, o),
                                     f"поворот корпуса на {format_mm(a)}°")

    def flip_footprint(self) -> bool:
        """«Отразить»: перенести корпус на другую сторону платы (:meth:`Footprint.flip
        <kicadfp.model.Footprint.flip>`)."""
        return self._apply_operation(lambda fp: fp.flip(), "отражение корпуса на другую сторону")

    def renumber_pads(self, start: int = 1, order: str = "file", prefix: str = "") -> bool:
        """Перенумеровать выводы (:meth:`Footprint.renumber_pads
        <kicadfp.model.Footprint.renumber_pads>`): с номера ``start``, порядок ``order``
        (ключ :data:`~kicadfp.gui.dialogs.RENUMBER_ORDERS`), префикс ``prefix``."""
        if order not in dict(RENUMBER_ORDERS):
            raise ValueError(f"порядок перенумерации: "
                             f"{', '.join(k for k, _ in RENUMBER_ORDERS)}")
        rule = f"prefix:{prefix}" if prefix else "sequential"
        first = int(start)
        return self._apply_operation(
            lambda fp: fp.renumber_pads(rule, start=first, order=order), "перенумерация площадок")

    def _pads_center(self) -> tuple[float, float] | None:
        fp = self._doc.fp
        pads = [] if fp is None else fp.pads
        if not pads:
            return None
        xs = [p.x for p in pads]
        ys = [p.y for p in pads]
        return (_geo.round_mm((min(xs) + max(xs)) / 2), _geo.round_mm((min(ys) + max(ys)) / 2))

    def _run_params(self, dlg: ParamsDialog) -> dict[str, Any] | None:
        try:
            if not self.exec_dialog(dlg):
                return None
            return dlg.values()
        finally:
            dlg.deleteLater()

    def move_dialog(self) -> ParamsDialog:
        """Диалог «Сдвинуть корпус» (поля ``dx``, ``dy``; кнопки «Площадка 1 в (0, 0)» и
        «Центр площадок в (0, 0)»)."""
        dlg = ParamsDialog(
            "Сдвинуть корпус",
            [ParamSpec("dx", "Сдвиг по X, мм:"), ParamSpec("dy", "Сдвиг по Y, мм:")], self,
            note="Все элементы корпуса (площадки, графика, тексты, зоны, смещение 3D-моделей) "
                 "сдвигаются на заданное расстояние. Ось Y направлена вниз.")

        def pad1_to_origin() -> None:
            fp = self._doc.fp
            pads = [] if fp is None else fp.pads_by_number("1")
            if pads:
                dlg.set_value("dx", _geo.round_mm(-pads[0].x))
                dlg.set_value("dy", _geo.round_mm(-pads[0].y))

        def center_to_origin() -> None:
            c = self._pads_center()
            if c is not None:
                dlg.set_value("dx", _geo.round_mm(-c[0]))
                dlg.set_value("dy", _geo.round_mm(-c[1]))

        dlg.add_button("Площадка 1 в (0, 0)", pad1_to_origin)
        dlg.add_button("Центр площадок в (0, 0)", center_to_origin)
        return dlg

    def move_interactive(self) -> bool:
        """«Сдвинуть…»."""
        if self._doc.fp is None:
            return False
        values = self._run_params(self.move_dialog())
        if values is None:
            return False
        return self.move_footprint(values["dx"], values["dy"])

    def rotate_dialog(self) -> ParamsDialog:
        """Диалог «Повернуть корпус» (поля ``angle``, ``x``, ``y``; кнопка «Центр
        площадок»)."""
        dlg = ParamsDialog(
            "Повернуть корпус",
            [ParamSpec("angle", "Угол, °:", default=90.0, minimum=-360.0, maximum=360.0,
                       decimals=3, step=15.0,
                       tip="Положительный угол — против часовой стрелки на экране"),
             ParamSpec("x", "Центр поворота X, мм:"), ParamSpec("y", "Центр поворота Y, мм:")],
            self, note="Все элементы корпуса поворачиваются вокруг заданной точки.")

        def center() -> None:
            c = self._pads_center()
            if c is not None:
                dlg.set_value("x", c[0])
                dlg.set_value("y", c[1])

        dlg.add_button("Центр площадок", center)
        return dlg

    def rotate_interactive(self) -> bool:
        """«Повернуть…»."""
        if self._doc.fp is None:
            return False
        values = self._run_params(self.rotate_dialog())
        if values is None:
            return False
        return self.rotate_footprint(values["angle"], (values["x"], values["y"]))

    def renumber_dialog(self) -> ParamsDialog:
        """Диалог «Перенумеровать площадки» (поля ``start``, ``order``, ``prefix``)."""
        return ParamsDialog(
            "Перенумеровать площадки",
            [ParamSpec("start", "Начать с:", kind="int", default=1, minimum=0,
                       maximum=1_000_000),
             ParamSpec("order", "Порядок:", kind="choice", default="file",
                       choices=tuple(RENUMBER_ORDERS)),
             ParamSpec("prefix", "Префикс:", kind="text", default="",
                       tip="Например, A: A1, A2, …")],
            self, note="Площадки без номера, без меди и np_thru_hole не нумеруются; площадки "
                       "одного вывода получают общий номер.")

    def renumber_interactive(self) -> bool:
        """«Перенумеровать площадки…»."""
        fp = self._doc.fp
        if fp is None or not fp.pads:
            return False
        values = self._run_params(self.renumber_dialog())
        if values is None:
            return False
        return self.renumber_pads(values["start"], values["order"], values["prefix"])

    def show_footprint_properties(self) -> None:
        """Показать панель «Свойства корпуса» и перевести фокус на имя."""
        self.dock_properties.show()
        self.dock_properties.raise_()
        self.props_panel.name_edit.setFocus()

    def about(self) -> None:
        """«О программе»."""
        dlg = AboutDialog(self)
        try:
            self.exec_dialog(dlg)
        finally:
            dlg.deleteLater()

    # --- вид ------------------------------------------------------------------------------------
    def set_grid(self, step: float) -> None:
        """Шаг сетки канвы, мм."""
        self.canvas.grid = float(step)
        self._sync_grid_actions()
        self._update_grid_label()

    def _on_grid_changed(self, _step: float) -> None:
        self._sync_grid_actions()
        self._update_grid_label()

    def _set_grid_visible(self, on: bool) -> None:
        self.canvas.grid_visible = on
        self._update_grid_label()

    def _set_snap(self, on: bool) -> None:
        self.canvas.snap = on

    def _set_show_hidden(self, on: bool) -> None:
        self.canvas.show_hidden = on

    def _sync_grid_actions(self) -> None:
        g = self.canvas.grid
        match = next((a for s, a in self.grid_actions.items() if abs(s - g) < 1e-9), None)
        if match is not None:
            if not match.isChecked():
                match.setChecked(True)
            return
        group = self.grid_group
        group.setExclusionPolicy(QActionGroup.ExclusionPolicy.None_)
        for a in self.grid_actions.values():
            a.setChecked(False)
        group.setExclusionPolicy(QActionGroup.ExclusionPolicy.Exclusive)

    def _sync_view_actions(self) -> None:
        c = self.canvas
        for act, value in ((self.act_grid_visible, c.grid_visible), (self.act_snap, c.snap),
                           (self.act_show_hidden, c.show_hidden)):
            if act.isChecked() != value:
                act.setChecked(value)
        self._sync_grid_actions()
        self._update_grid_label()

    # --- настройки ------------------------------------------------------------------------------
    def save_settings(self) -> None:
        """Записать настройки окна (см. модуль)."""
        s = self._settings
        c = self.canvas
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState(_STATE_VERSION))
        s.setValue("view/grid", c.grid)
        s.setValue("view/grid_visible", c.grid_visible)
        s.setValue("view/snap", c.snap)
        s.setValue("view/show_hidden", c.show_hidden)
        s.setValue("view/hidden_layers", sorted(c.hidden_layers))
        s.setValue("session/libraries", [str(p) for p in self.library_tree.paths()])
        s.setValue("recent_files", list(self._recent))
        s.setValue("dirs/last", self._last_dir)
        s.sync()

    def restore_settings(self) -> None:
        """Прочитать настройки окна (см. модуль); недопустимые значения пропускаются."""
        s = self._settings
        c = self.canvas
        geometry = s.value("window/geometry")
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except TypeError:
                pass
        state = s.value("window/state")
        if state:
            try:
                self._state_restored = bool(self.restoreState(state, _STATE_VERSION))
            except TypeError:
                self._state_restored = False
        grid = _to_float(s.value("view/grid"), None)
        if grid is not None and grid > 0:
            c.grid = grid
        c.grid_visible = _to_bool(s.value("view/grid_visible"), c.grid_visible)
        c.snap = _to_bool(s.value("view/snap"), c.snap)
        c.show_hidden = _to_bool(s.value("view/show_hidden"), c.show_hidden)
        hidden = [n for n in _to_list(s.value("view/hidden_layers"))
                  if n in PSEUDO_LAYER_TITLES or n in _PANEL_RANK]
        if hidden:
            try:
                c.set_hidden_layers(hidden)
            except ValueError:
                pass
        self._recent = [r for r in _to_list(s.value("recent_files"))][:MAX_RECENT]
        self._last_dir = str(s.value("dirs/last") or "")
        for entry in _to_list(s.value("session/libraries")):
            p = Path(entry)
            try:
                if p.is_dir():
                    self.library_tree.add_library(p)
                elif p.is_file():
                    self.library_tree.add_file(p)
            except (OSError, ValueError):
                pass

    # --- события окна ---------------------------------------------------------------------------
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — переопределение Qt
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            if not self._state_restored:
                self._apply_default_dock_sizes()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — переопределение Qt
        """Закрытие окна: при несохранённых изменениях — вопрос (``confirm_discard``
        документа); настройки записываются."""
        if not self.confirm_close():
            event.ignore()
            return
        self.save_settings()
        if self._validate_dialog is not None:
            self._validate_dialog.close()
        event.accept()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 — переопределение Qt
        try:
            et = event.type()
            if et == QEvent.Type.MouseButtonDblClick and obj is self.canvas.viewport():
                if isinstance(event, QMouseEvent) and self._canvas_double_click(event):
                    return True
            elif et == QEvent.Type.ContextMenu and obj is self.canvas.viewport():
                if isinstance(event, QContextMenuEvent):
                    self._show_canvas_menu(event)
                    return True
            elif et == QEvent.Type.Leave and obj is self.canvas.viewport():
                self._set_coords(None, None)  # курсор ушёл с канвы
            elif et == QEvent.Type.KeyPress and (obj is self.pad_table or obj is self.items_table):
                if isinstance(event, QKeyEvent) and self._table_enter(obj, event):
                    return True
        except RuntimeError:  # виджеты уже удалены (закрытие окна)
            return False
        return super().eventFilter(obj, event)

    def canvas_context_menu(self, scene_pos: QPointF | None = None) -> QMenu:
        """Контекстное меню канвы для точки сцены ``scene_pos`` (мм): элемент под курсором
        выделяется; пункты — «Свойства элемента…», «Удалить», добавление площадки и фигур
        в точку щелчка, «Отменить»/«Повторить», «Вписать», «Показать все слои». Меню
        возвращается (его показывает вызывающий; тесты вызывают пункты напрямую)."""
        doc = self._doc
        point: tuple[float, float] | None = None
        if scene_pos is not None:
            point = (float(scene_pos.x()), float(scene_pos.y()))
            if doc.fp is not None:
                element = self.canvas.element_at(QPointF(scene_pos))
                try:
                    doc.select(element)
                except (ValueError, RuntimeError):
                    pass
        menu = QMenu(self)
        menu.addActions([self.act_properties, self.act_delete])
        menu.addSeparator()
        has_fp = doc.fp is not None
        for text, adder in (("Добавить площадку", self.add_pad), ("Добавить линию", self.add_line),
                            ("Добавить прямоугольник", self.add_rect),
                            ("Добавить окружность", self.add_circle)):
            act = menu.addAction(text)
            act.setEnabled(has_fp)
            act.setStatusTip(f"{text} в точку щелчка")
            act.triggered.connect(lambda _checked=False, f=adder: f(at=point))
        act = menu.addAction("Добавить текст")
        act.setEnabled(has_fp)
        act.triggered.connect(lambda _checked=False: self.add_text(at=point))
        menu.addSeparator()
        menu.addActions([self.act_undo, self.act_redo])
        menu.addSeparator()
        menu.addActions([self.act_fit, self.act_show_all_layers])
        return menu

    def _show_canvas_menu(self, event: QContextMenuEvent) -> None:
        menu = self.canvas_context_menu(self.canvas.map_to_scene(QPointF(event.pos())))
        try:
            self.exec_menu(menu, event.globalPos())
        finally:
            menu.deleteLater()

    def _canvas_double_click(self, event: QMouseEvent) -> bool:
        """Двойной щелчок по элементу на канве — его свойства."""
        if event.button() != Qt.MouseButton.LeftButton or self._doc.fp is None:
            return False
        c = self.canvas
        element = c.element_at(c.map_to_scene(event.position()))
        if element is None:
            return False
        try:
            self._doc.select(element)
        except (ValueError, RuntimeError):
            return False
        self._schedule_properties()
        return True

    def _table_enter(self, view: Any, event: QKeyEvent) -> bool:
        """Enter на строке таблицы (вне редактирования ячейки) — свойства элемента."""
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if event.modifiers() not in (Qt.KeyboardModifier.NoModifier,
                                     Qt.KeyboardModifier.KeypadModifier):
            return False
        if not isinstance(view, DocumentTableView) \
                or view.state() == QAbstractItemView.State.EditingState:
            return False
        item = view.table_model().item_at(view.currentIndex())
        if item is None:
            return False
        try:
            self._doc.select(item)
        except (ValueError, RuntimeError):
            return False
        self._schedule_properties()
        return True

    @staticmethod
    def _dropped_paths(mime: QMimeData | None) -> list[Path]:
        if mime is None or not mime.hasUrls():
            return []
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                p = _abs(url.toLocalFile())
                if p.exists():
                    out.append(p)
        return out

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — переопределение Qt
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — переопределение Qt
        """Перетаскивание файлов в окно: каталоги открываются как библиотеки, первый файл —
        в редакторе, остальные файлы добавляются в дерево библиотек."""
        paths = self._dropped_paths(event.mimeData())
        if not paths:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        # открыть после завершения перетаскивания: вопросы и сообщения об ошибках модальны,
        # а источник перетаскивания ждёт окончания обработки события
        QTimer.singleShot(0, lambda: self.open_paths(paths))

    def open_paths(self, paths: Iterable[str | PathLike[str]]) -> bool:
        """Открыть несколько путей (как перетаскивание в окно): каталоги — библиотеками,
        первый файл — в редакторе, остальные — в дерево библиотек. ``True`` — всё открыто."""
        ok = True
        opened_file = False
        for raw in paths:
            p = _abs(raw)
            if p.is_dir():
                ok = self.open_library(p) is not None and ok
            elif not opened_file:
                opened_file = True
                ok = self.open_file(p) and ok
            else:
                try:
                    self.library_tree.add_file(p)
                except (OSError, ValueError) as e:
                    self._status(f"{p.name}: {_error_text(e)}")
                    ok = False
        return ok
