"""Диалоги редактора: создание типового корпуса, проверка, групповые операции над
площадками, свойства элемента, «О программе».

* :class:`GenerateDialog` — выбор генератора из :data:`kicadfp.generators.GENERATORS`
  (русские названия — :data:`GENERATOR_TITLES`), форма параметров по
  :func:`kicadfp.generators.describe`, поле имени, предпросмотр; :meth:`GenerateDialog.build`
  возвращает :class:`~kicadfp.model.Footprint` (ошибки параметров — в строке ошибки, без
  исключений).
* :class:`ValidateDialog` — немодальный список замечаний :func:`kicadfp.validate.validate`
  для открытого корпуса; двойной щелчок выделяет элемент (``doc.select``).
* :class:`PadBatchDialog` — групповые операции над выбранными или всеми площадками
  (перенумерация, тип/форма, размер, отверстие, слои, поворот вокруг точки, сдвиг) одной
  командой :class:`~kicadfp.gui.commands.ReplaceNodeCommand` — один шаг отмены.
* :class:`ItemPropertiesDialog` — свойства площадки, фигуры, текста или 3D-модели в форме;
  изменённые свойства присваиваются одной командой
  :class:`~kicadfp.gui.commands.SetAttrsCommand`.
* :class:`AboutDialog` — версия программы.

Все диалоги можно заполнять программно (методы ``set_*``) и применять без показа окна —
так их проверяют тесты; модель меняется только через :meth:`FootprintDocument.apply
<kicadfp.gui.document.FootprintDocument.apply>`.
"""

from __future__ import annotations

import json
import math
import platform
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6 import __version__ as _pyside_version
from PySide6.QtCore import QByteArray, QModelIndex, Qt, QTimer, qVersion
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import generators as _gen
from .. import layers as _layers
from .._version import __version__
from ..format_rules import KICAD_FORMAT_VERSIONS, kicad_format_version
from ..model import (JUSTIFY_VALUES, PAD_SHAPES, PAD_TYPES, STROKE_TYPES, Arc, Circle, Curve,
                     Footprint, Graphic, Line, Model, Pad, Poly, Rect, Text, View)
from ..validate import Issue, validate
from .commands import ReplaceNodeCommand, SetAttrsCommand, describe_item
from .pad_table import LAYER_PRESET_TEXTS, format_mm, parse_layers, parse_number, parse_pair

try:  # предпросмотр в GenerateDialog (модуль QtSvgWidgets может отсутствовать в сборке)
    from PySide6.QtSvgWidgets import QSvgWidget
except ImportError:  # pragma: no cover — зависит от сборки PySide6
    QSvgWidget = None  # type: ignore[assignment,misc]

__all__ = [
    "GenerateDialog", "ValidateDialog", "PadBatchDialog", "ItemPropertiesDialog",
    "PropertiesDialog", "AboutDialog", "GENERATOR_TITLES", "RENUMBER_ORDERS", "LEVEL_TITLES",
    "LEVEL_COLORS",
]

_ERROR_STYLE = "color: #c62828;"


def _set_error_label(label: QLabel, message: str) -> None:
    label.setText(message)
    label.setVisible(bool(message))


def _error_label(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setStyleSheet(_ERROR_STYLE)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setVisible(False)
    return label


def _close(a: Any, b: Any, tol: float = 1e-9) -> bool:
    """Равны ли значения свойств (числа — с допуском, списки/кортежи — поэлементно)."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or (isinstance(a, bool) and isinstance(b, bool) and a == b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tol
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


# =============================================================================================
# Создание типового корпуса
# =============================================================================================

#: Русские названия генераторов (для выпадающего списка).
GENERATOR_TITLES: dict[str, str] = {
    "dip": "DIP — микросхема в двухрядном корпусе",
    "pin_header": "Штыревой разъём (PinHeader)",
    "resistor": "Резистор выводной (горизонтальный)",
    "capacitor_radial": "Конденсатор радиальный",
    "capacitor_axial": "Конденсатор осевой (горизонтальный)",
    "diode": "Диод выводной (горизонтальный)",
    "transistor": "Транзистор TO-92",
    "lab_dip14": "Лабораторная: микросхема dip14 (К555ТВ6)",
    "lab_mlt": "Лабораторная: резистор МЛТ",
    "lab_snp8": "Лабораторная: разъём СНП (8 контактов)",
}

_INT_RANGE = (-1_000_000, 1_000_000)
_FLOAT_RANGE = (-100_000.0, 100_000.0)
_AUTO_TEXT = "авто"


@dataclass
class _ParamWidget:
    info: Any          # generators.ParamInfo
    kind: str          # int | float | optfloat | bool | str | optstr | json
    optional: bool
    widget: QWidget


def _param_kind(type_text: str) -> tuple[str, bool]:
    """Вид поля по аннотации параметра: ``(вид, необязательный)``."""
    parts = [p for p in type_text.replace(" ", "").split("|") if p]
    optional = "None" in parts
    base = [p for p in parts if p != "None"]
    if base == ["int"]:
        return ("int" if not optional else "json"), optional
    if base == ["float"]:
        return ("optfloat" if optional else "float"), optional
    if base == ["bool"]:
        return "bool", optional
    if base == ["str"]:
        return ("optstr" if optional else "str"), optional
    return "json", optional


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


class GenerateDialog(QDialog):
    """Создание типового корпуса генератором.

    Выпадающий список — генераторы :data:`kicadfp.generators.GENERATORS` с русскими
    названиями; форма параметров строится по :func:`kicadfp.generators.describe`:
    ``float`` — ``QDoubleSpinBox`` (3 знака; у необязательных ``float | None`` наименьшее
    значение показывается как «авто» и означает ``None``), ``int`` — ``QSpinBox``,
    ``bool`` — ``QCheckBox``, ``str`` — ``QLineEdit``, списки и кортежи (``pad_size``,
    ``mounting_holes``) — ``QLineEdit`` с текстом JSON (пусто — ``None``). Параметр
    ``name`` вынесен в отдельное поле «Имя» (пусто — имя по умолчанию генератора).
    «Формат файла» — версия KiCad, для которой строится корпус (KiCad 9 по умолчанию; KiCad 8
    не открывает файлы формата KiCad 9, для него — «KiCad 8», см.
    :func:`kicadfp.generators.target_version`).

    Программный API: :meth:`set_generator`, :meth:`set_param`, :meth:`set_name`,
    :meth:`set_kicad_version` / :attr:`kicad_version`,
    :meth:`params`, :meth:`build` (→ ``Footprint`` или ``None``; ошибка — в
    :attr:`error_text`), :attr:`footprint` — последний построенный корпус,
    :meth:`open_in` — открыть результат в документе. «ОК» строит корпус и закрывает диалог
    только при успехе.
    """

    def __init__(self, parent: QWidget | None = None, generator: str | None = None, *,
                 preview: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать типовой корпус")
        self._params: dict[str, _ParamWidget] = {}
        self._name_default: Any = None
        self._footprint: Footprint | None = None
        self._generator = ""
        self._loading = False

        outer = QVBoxLayout(self)
        top = QFormLayout()
        self._combo = QComboBox(self)
        for key in _gen.GENERATORS:
            self._combo.addItem(GENERATOR_TITLES.get(key, key), key)
        top.addRow("Тип корпуса:", self._combo)
        self._name_edit = QLineEdit(self)
        top.addRow("Имя:", self._name_edit)
        self._format = QComboBox(self)
        for major in sorted(KICAD_FORMAT_VERSIONS, reverse=True):
            self._format.addItem(f"KiCad {major} ({KICAD_FORMAT_VERSIONS[major]})", major)
        self._format.setToolTip("Версия формата файла нового корпуса. KiCad открывает файлы "
                                "своей и более старых версий: для KiCad 8 выберите «KiCad 8».")
        top.addRow("Формат файла:", self._format)
        outer.addLayout(top)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        body = QHBoxLayout()
        self._form_host = QWidget(self)
        self._form = QFormLayout(self._form_host)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_host)
        scroll.setMinimumWidth(360)
        body.addWidget(scroll, 1)
        self._preview: Any = None
        if preview and QSvgWidget is not None:
            self._preview = QSvgWidget(self)
            self._preview.setMinimumSize(260, 260)
            try:
                self._preview.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            except AttributeError:  # pragma: no cover — Qt < 6.7
                pass
            body.addWidget(self._preview, 1)
        outer.addLayout(body, 1)

        self._info = QLabel(self)
        self._info.setWordWrap(True)
        outer.addWidget(self._info)
        self._error = _error_label(self)
        outer.addWidget(self._error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults, self)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(
            "По умолчанию")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self.reset_params)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.update_preview)

        self._combo.currentIndexChanged.connect(self._on_combo)
        self._name_edit.textChanged.connect(self._schedule_preview)
        self._format.currentIndexChanged.connect(self._schedule_preview)
        self.set_generator(generator or next(iter(_gen.GENERATORS)))

    # --- свойства -------------------------------------------------------------------------------
    @property
    def generator(self) -> str:
        """Имя выбранного генератора (ключ :data:`kicadfp.generators.GENERATORS`)."""
        return self._generator

    @property
    def footprint(self) -> Footprint | None:
        """Корпус, построенный последним вызовом :meth:`build` (``None`` — ошибка)."""
        return self._footprint

    @property
    def error_text(self) -> str:
        """Текст строки ошибки (пусто — ошибок нет)."""
        return self._error.text()

    @property
    def error_label(self) -> QLabel:
        """Строка ошибки."""
        return self._error

    @property
    def kicad_version(self) -> int:
        """Версия KiCad (6–9), в формате которой строится корпус (поле «Формат файла»)."""
        return int(self._format.currentData())

    def set_kicad_version(self, kicad: int | str) -> None:
        """Выбрать формат файла: номер KiCad (6–9) или версия формата (``20240108``);
        ``ValueError`` — неизвестная версия."""
        version = kicad_format_version(kicad)
        major = next(k for k, v in KICAD_FORMAT_VERSIONS.items() if v == version)
        self._format.setCurrentIndex(self._format.findData(major))

    def param_names(self) -> list[str]:
        """Параметры формы (без ``name`` — он в поле «Имя»)."""
        return list(self._params)

    def param_widget(self, name: str) -> QWidget:
        """Виджет параметра ``name`` (``KeyError`` — нет такого параметра)."""
        if name == "name":
            return self._name_edit
        return self._params[name].widget

    # --- выбор генератора -----------------------------------------------------------------------
    def set_generator(self, name: str) -> None:
        """Выбрать генератор (имя или синоним из :data:`kicadfp.generators.ALIASES`) и
        построить форму с его параметрами по умолчанию. ``KeyError`` — нет такого."""
        func = _gen.get(name)
        key = next(k for k, f in _gen.GENERATORS.items() if f is func)
        idx = self._combo.findData(key)
        if self._combo.currentIndex() != idx:
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(idx)
            self._combo.blockSignals(False)
        self._rebuild_form(key)

    def _on_combo(self, index: int) -> None:
        key = self._combo.itemData(index)
        if key and key != self._generator:
            self._rebuild_form(key)

    def _rebuild_form(self, key: str) -> None:
        self._loading = True
        try:
            self._generator = key
            while self._form.rowCount():
                self._form.removeRow(0)
            self._params.clear()
            self._name_default = None
            self._name_edit.clear()
            try:
                self._summary.setText(_gen.summary(key))
            except Exception:  # noqa: BLE001 — описание вторично
                self._summary.setText("")
            for info in _gen.describe(key):
                if info.name == "name":
                    self._name_default = info.default
                    self._name_edit.setPlaceholderText(
                        f"по умолчанию: {info.default}" if info.default
                        else "по умолчанию — по параметрам")
                    continue
                kind, optional = _param_kind(info.type)
                widget = self._make_widget(kind, info)
                self._params[info.name] = _ParamWidget(info, kind, optional, widget)
                label = QLabel(f"{info.name}:", self._form_host)
                tip = f"{info.description}\nТип: {info.type}" if info.description \
                    else f"Тип: {info.type}"
                label.setToolTip(tip)
                widget.setToolTip(tip)
                self._form.addRow(label, widget)
            self._set_defaults()
        finally:
            self._loading = False
        self._footprint = None
        _set_error_label(self._error, "")
        self._schedule_preview()

    def _make_widget(self, kind: str, info: Any) -> QWidget:
        parent = self._form_host
        if kind == "int":
            w: Any = QSpinBox(parent)
            w.setRange(*_INT_RANGE)
            w.valueChanged.connect(self._schedule_preview)
        elif kind in ("float", "optfloat"):
            w = QDoubleSpinBox(parent)
            w.setDecimals(3)
            w.setSingleStep(0.1)
            if kind == "optfloat":
                w.setRange(0.0, _FLOAT_RANGE[1])
                w.setSpecialValueText(_AUTO_TEXT)
            else:
                w.setRange(*_FLOAT_RANGE)
            w.valueChanged.connect(self._schedule_preview)
        elif kind == "bool":
            w = QCheckBox(parent)
            w.toggled.connect(self._schedule_preview)
        else:
            w = QLineEdit(parent)
            if kind == "json":
                w.setPlaceholderText(_AUTO_TEXT if "None" in info.type else "JSON")
            elif kind == "optstr":
                w.setPlaceholderText(_AUTO_TEXT)
            w.textChanged.connect(self._schedule_preview)
        return w

    def _set_widget(self, pw: _ParamWidget, value: Any) -> None:
        w: Any = pw.widget
        if pw.kind == "int":
            v = int(value)
            if not _INT_RANGE[0] <= v <= _INT_RANGE[1]:
                raise ValueError(f"{pw.info.name}: значение вне диапазона")
            w.setValue(v)
        elif pw.kind == "float":
            v = float(value)
            if not _FLOAT_RANGE[0] <= v <= _FLOAT_RANGE[1]:
                raise ValueError(f"{pw.info.name}: значение вне диапазона")
            w.setValue(v)
        elif pw.kind == "optfloat":
            if value is None:
                w.setValue(w.minimum())
            else:
                v = float(value)
                if not 0.0 < v <= _FLOAT_RANGE[1]:
                    raise ValueError(f"{pw.info.name}: ожидается положительное число "
                                     f"(или авто)")
                w.setValue(v)
        elif pw.kind == "bool":
            w.setChecked(bool(value))
        elif pw.kind in ("str", "optstr"):
            w.setText("" if value is None else str(value))
        else:
            w.setText(_json_text(value))

    def _set_defaults(self) -> None:
        for pw in self._params.values():
            try:
                self._set_widget(pw, pw.info.default)
            except (TypeError, ValueError):
                pass

    def reset_params(self) -> None:
        """Вернуть параметрам значения по умолчанию (имя очищается)."""
        self._loading = True
        try:
            self._set_defaults()
            self._name_edit.clear()
        finally:
            self._loading = False
        self._schedule_preview()

    # --- программное заполнение -----------------------------------------------------------------
    def set_param(self, name: str, value: Any) -> bool:
        """Задать параметр ``name`` (``name="name"`` — поле «Имя»). Значение приводится к
        типу параметра (:func:`kicadfp.generators.coerce_param`; для полей JSON строка
        записывается как есть и проверяется при :meth:`build`). ``KeyError`` — у
        генератора нет такого параметра; недопустимое значение — ``False`` и сообщение в
        строке ошибки."""
        key = name.replace("-", "_")
        if key == "name":
            self.set_name("" if value is None else str(value))
            return True
        pw = self._params.get(key)
        if pw is None:
            raise KeyError(f"у генератора {self._generator!r} нет параметра {name!r}; "
                           f"параметры: {', '.join(self._params)}")
        try:
            if pw.kind == "json" and isinstance(value, str):
                pw.widget.setText(value)  # type: ignore[attr-defined]
            else:
                v = value if (value is None and pw.optional) else \
                    _gen.coerce_param(self._generator, key, value)
                self._set_widget(pw, v)
        except (TypeError, ValueError) as e:
            _set_error_label(self._error, str(e))
            return False
        return True

    def set_params(self, values: dict[str, Any]) -> bool:
        """Задать несколько параметров (:meth:`set_param`); ``False`` — хотя бы один не
        принят."""
        ok = True
        for k, v in values.items():
            ok = self.set_param(k, v) and ok
        return ok

    def set_name(self, name: str) -> None:
        """Имя корпуса (пусто — по умолчанию генератора)."""
        self._name_edit.setText(name)

    def param(self, name: str) -> Any:
        """Значение параметра из формы (приведённое к типу); ``ValueError`` — неверный ввод."""
        key = name.replace("-", "_")
        if key == "name":
            text = self._name_edit.text().strip()
            return text or self._name_default
        pw = self._params[key]
        w: Any = pw.widget
        if pw.kind == "int":
            return int(w.value())
        if pw.kind == "float":
            return float(w.value())
        if pw.kind == "optfloat":
            v = float(w.value())
            return None if v <= w.minimum() else v
        if pw.kind == "bool":
            return bool(w.isChecked())
        if pw.kind == "str":
            return w.text()
        text = w.text().strip()
        if pw.kind == "optstr":
            return text or None
        if not text:
            if pw.optional:
                return None
            raise ValueError(f"{key}: значение обязательно")
        return _gen.coerce_param(self._generator, key, text)

    def params(self) -> dict[str, Any]:
        """Все параметры формы для вызова генератора (включая ``name``, если задано);
        ``ValueError`` — неверный ввод."""
        out = {k: self.param(k) for k in self._params}
        text = self._name_edit.text().strip()
        if text:
            out["name"] = text
        return out

    # --- построение -----------------------------------------------------------------------------
    def build(self) -> Footprint | None:
        """Построить корпус выбранным генератором с параметрами формы. При ошибке
        (неверный параметр, генератор отверг значения) сообщение показывается в строке
        ошибки и возвращается ``None`` — исключение не выбрасывается."""
        self._timer.stop()
        try:
            kwargs = self.params()
            with _gen.target_version(self.kicad_version):
                fp = _gen.get(self._generator)(**kwargs)
            if not isinstance(fp, Footprint):
                raise TypeError("генератор вернул не корпус")
        except Exception as e:  # noqa: BLE001 — любые ошибки параметров показываются в форме
            self._footprint = None
            msg = str(e) or type(e).__name__
            _set_error_label(self._error, f"Ошибка параметров: {msg}")
            self._info.setText("")
            if self._preview is not None:
                self._preview.load(QByteArray())
            return None
        self._footprint = fp
        _set_error_label(self._error, "")
        self._show_info(fp)
        return fp

    def _show_info(self, fp: Footprint) -> None:
        try:
            bb = fp.bbox()
            size = f", габариты {format_mm(round(bb.width, 3))} × " \
                   f"{format_mm(round(bb.height, 3))} мм"
        except Exception:  # noqa: BLE001
            size = ""
        self._info.setText(f"{fp.name}: площадок {len(fp.pads)}{size}")
        if self._preview is not None:
            try:
                from ..render import render_svg
                svg = render_svg(fp, grid=None, pad_numbers=True)
                self._preview.load(QByteArray(svg.encode("utf-8")))
            except Exception:  # noqa: BLE001 — предпросмотр вторичен
                self._preview.load(QByteArray())

    def _schedule_preview(self, *_: Any) -> None:
        if not self._loading:
            self._timer.start()

    def update_preview(self) -> None:
        """Перестроить корпус и обновить предпросмотр (вызывается с задержкой после
        изменения параметров)."""
        self.build()

    def open_in(self, doc: Any) -> bool:
        """Построить корпус и открыть его в документе (``doc.open_footprint``) как новый
        несохранённый; ``False`` — ошибка параметров или пользователь отказался отбросить
        изменения текущего корпуса."""
        fp = self.build()
        if fp is None:
            return False
        return bool(doc.open_footprint(fp))

    def accept(self) -> None:  # noqa: D401 — переопределение Qt
        """«ОК»: построить корпус; диалог закрывается только при успехе."""
        if self.build() is not None:
            super().accept()


# =============================================================================================
# Проверка корпуса
# =============================================================================================

#: Названия уровней замечаний.
LEVEL_TITLES = {"error": "Ошибка", "warning": "Предупреждение"}
#: Цвета уровней: (текст, фон).
LEVEL_COLORS = {"error": ("#b71c1c", "#fde0e0"), "warning": ("#8a5a00", "#fff1c9")}


class ValidateDialog(QDialog):
    """Немодальное окно проверки открытого корпуса (:func:`kicadfp.validate.validate`).

    Таблица: «Уровень» (цветом), «Код», «Сообщение»; ошибки — первыми. Двойной щелчок по
    строке выделяет элемент замечания (``doc.select``). Кнопка «Проверить снова» —
    :meth:`run`. Пока окно видно и включено :attr:`auto_update`, проверка повторяется
    после каждого изменения корпуса (сигнал ``doc.changed``).
    """

    COLUMNS = ("Уровень", "Код", "Сообщение")

    def __init__(self, doc: Any, parent: QWidget | None = None, *,
                 auto_update: bool = True) -> None:
        super().__init__(parent)
        self._doc = doc
        self._issues: list[Issue] = []
        #: Повторять проверку по ``doc.changed``, пока окно видно.
        self.auto_update = auto_update
        self.setWindowTitle("Проверка корпуса")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        layout = QVBoxLayout(self)
        self._summary = QLabel(self)
        layout.addWidget(self._summary)
        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._table.setWordWrap(True)
        self._table.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._table, 1)
        buttons = QDialogButtonBox(self)
        self._rerun = buttons.addButton("Проверить снова",
                                        QDialogButtonBox.ButtonRole.ActionRole)
        self._rerun.clicked.connect(self.run)
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.resize(640, 360)
        doc.changed.connect(self._on_changed)

    @property
    def issues(self) -> list[Issue]:
        """Замечания последней проверки (в порядке строк таблицы)."""
        return list(self._issues)

    @property
    def table(self) -> QTableWidget:
        """Таблица замечаний."""
        return self._table

    @property
    def summary_text(self) -> str:
        """Итоговая строка («Ошибок: 1, предупреждений: 0» …)."""
        return self._summary.text()

    def run(self) -> list[Issue]:
        """Проверить открытый корпус и заполнить таблицу; вернуть замечания."""
        fp = self._doc.fp
        if fp is None:
            issues: list[Issue] = []
        else:
            try:
                issues = list(validate(fp))
            except Exception as e:  # noqa: BLE001 — сбой правила не должен ронять окно
                issues = [Issue("error", "VALIDATE_FAILED", f"сбой проверки: {e}", None)]
        issues.sort(key=lambda i: 0 if i.level == "error" else 1)  # устойчивая сортировка
        self._issues = issues
        self._fill()
        if fp is None:
            self._summary.setText("Корпус не открыт")
        else:
            n_err = sum(1 for i in issues if i.level == "error")
            n_warn = len(issues) - n_err
            self._summary.setText("Замечаний нет" if not issues
                                  else f"Ошибок: {n_err}, предупреждений: {n_warn}")
        return self.issues

    def _fill(self) -> None:
        t = self._table
        t.setRowCount(0)
        t.setRowCount(len(self._issues))
        for row, issue in enumerate(self._issues):
            level = QTableWidgetItem(LEVEL_TITLES.get(issue.level, issue.level))
            fg, bg = LEVEL_COLORS.get(issue.level, ("#000000", "#ffffff"))
            level.setForeground(QBrush(QColor(fg)))
            level.setBackground(QBrush(QColor(bg)))
            font = QFont(level.font())
            font.setBold(issue.level == "error")
            level.setFont(font)
            code = QTableWidgetItem(issue.code)
            msg = QTableWidgetItem(issue.message)
            msg.setToolTip(issue.message)
            for col, item in enumerate((level, code, msg)):
                item.setData(Qt.ItemDataRole.UserRole, row)
                t.setItem(row, col, item)
        t.resizeRowsToContents()

    def select_issue(self, row: int) -> bool:
        """Выделить в документе элемент замечания строки ``row``; ``False`` — у замечания
        нет элемента или его уже нет в корпусе."""
        if not 0 <= row < len(self._issues):
            return False
        element = self._issues[row].element
        if element is None or not self._doc.contains(element):
            return False
        try:
            self._doc.select(element)
        except (ValueError, RuntimeError, TypeError):
            return False
        return True

    def _on_double_clicked(self, index: QModelIndex) -> None:
        self.select_issue(index.row())

    def _on_changed(self) -> None:
        if self.auto_update and self.isVisible():
            self.run()

    def showEvent(self, event: Any) -> None:  # noqa: N802 — переопределение Qt
        super().showEvent(event)
        self.run()


# =============================================================================================
# Групповые операции над площадками
# =============================================================================================

#: Правила порядка перенумерации: (ключ, название).
RENUMBER_ORDERS: tuple[tuple[str, str], ...] = (
    ("file", "по порядку в файле"),
    ("xy", "по X, затем по Y"),
    ("yx", "по Y, затем по X"),
    ("circular", "по кругу (против часовой стрелки)"),
)

_KEEP = "(не менять)"
_DEFAULT_DRILL_RATIO = 0.5


def _preset_key(names: Iterable[str]) -> str | None:
    s = set(names)
    for key, preset in _layers.PAD_LAYER_PRESETS.items():
        if set(preset) == s:
            return key
    return None


def _dspin(parent: QWidget, lo: float, hi: float, decimals: int = 4,
           value: float = 0.0, step: float = 0.1) -> QDoubleSpinBox:
    w = QDoubleSpinBox(parent)
    w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setValue(value)
    return w


class PadBatchDialog(QDialog):
    """Групповые операции над площадками (выбранными или всеми) одним шагом отмены.

    Операции (включаются флажками групп; выполняются в этом порядке):

    1. перенумерация — с номера N, порядок :data:`RENUMBER_ORDERS` (в файле, по X, по Y,
       по кругу), префикс (``A`` → ``A1, A2, …``); для всех площадок — как
       :meth:`Footprint.renumber_pads <kicadfp.model.Footprint.renumber_pads>` (площадки
       ``np_thru_hole`` и без номера/меди не нумеруются, площадки одного вывода получают
       общий номер), для части — нумеруются только они;
    2. тип и форма (при смене типа слои-пресет меняются на пресет нового типа, у
       ``smd``/``connect`` отверстие удаляется, у сквозной без отверстия — создаётся);
    3. общий размер (X, Y); 4. общее отверстие (``0.8`` или ``1.2 x 0.8``; пусто —
       удалить); 5. слои (пресет или строка через запятую);
    6. поворот на угол вокруг точки (положение и угол площадки); 7. сдвиг dx, dy.

    :meth:`apply_to` выполняет всё над копией корпуса и применяет одной
    :class:`~kicadfp.gui.commands.ReplaceNodeCommand` (один шаг отмены); ошибки — в строке
    ошибки, модель не меняется. Программное заполнение: :meth:`set_scope`,
    :meth:`set_renumber`, :meth:`set_type`, :meth:`set_size`, :meth:`set_drill`,
    :meth:`set_layers`, :meth:`set_rotate`, :meth:`set_move`, :meth:`clear_operations`.
    """

    def __init__(self, doc: Any, pads: Sequence[Pad] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        if pads is None:
            sel = getattr(doc, "selected", None)
            pads = [sel] if isinstance(sel, Pad) else []
        self._pads: list[Pad] = [p for p in pads if isinstance(p, Pad)]
        self.setWindowTitle("Групповые операции над площадками")
        outer = QVBoxLayout(self)

        scope = QGroupBox("Площадки", self)
        sl = QHBoxLayout(scope)
        self._rb_selected = QRadioButton(scope)
        self._rb_all = QRadioButton(scope)
        sl.addWidget(self._rb_selected)
        sl.addWidget(self._rb_all)
        outer.addWidget(scope)

        grid = QGridLayout()
        outer.addLayout(grid)

        # перенумерация
        self._g_renumber = self._group("Перенумерация")
        f = QFormLayout(self._g_renumber)
        self._start = QSpinBox(self._g_renumber)
        self._start.setRange(0, 1_000_000)
        self._start.setValue(1)
        self._order = QComboBox(self._g_renumber)
        for key, title in RENUMBER_ORDERS:
            self._order.addItem(title, key)
        self._prefix = QLineEdit(self._g_renumber)
        self._prefix.setPlaceholderText("без префикса")
        f.addRow("Начать с:", self._start)
        f.addRow("Порядок:", self._order)
        f.addRow("Префикс:", self._prefix)
        grid.addWidget(self._g_renumber, 0, 0)

        # тип и форма
        self._g_type = self._group("Тип и форма")
        f = QFormLayout(self._g_type)
        self._type = QComboBox(self._g_type)
        self._type.addItems([_KEEP, *PAD_TYPES])
        self._shape = QComboBox(self._g_type)
        self._shape.addItems([_KEEP, *PAD_SHAPES])
        f.addRow("Тип:", self._type)
        f.addRow("Форма:", self._shape)
        grid.addWidget(self._g_type, 0, 1)

        # размер
        self._g_size = self._group("Размер площадки")
        f = QFormLayout(self._g_size)
        self._size_x = _dspin(self._g_size, 0.0001, 1000.0, value=1.6)
        self._size_y = _dspin(self._g_size, 0.0001, 1000.0, value=1.6)
        f.addRow("Размер X, мм:", self._size_x)
        f.addRow("Размер Y, мм:", self._size_y)
        grid.addWidget(self._g_size, 1, 0)

        # отверстие
        self._g_drill = self._group("Отверстие")
        f = QFormLayout(self._g_drill)
        self._drill = QLineEdit("0.8", self._g_drill)
        self._drill.setPlaceholderText("пусто — без отверстия")
        self._drill.setToolTip("Диаметр (0.8) или овал «ширина x высота» (1.2 x 0.8), мм")
        f.addRow("Отверстие, мм:", self._drill)
        grid.addWidget(self._g_drill, 1, 1)

        # слои
        self._g_layers = self._group("Слои")
        f = QFormLayout(self._g_layers)
        self._layers = QComboBox(self._g_layers)
        self._layers.setEditable(True)
        self._layers.addItems(LAYER_PRESET_TEXTS)
        self._layers.setToolTip("Пресет или список слоёв через запятую (F.Cu, F.Mask)")
        f.addRow("Слои:", self._layers)
        grid.addWidget(self._g_layers, 2, 0)

        # поворот
        self._g_rotate = self._group("Поворот")
        f = QFormLayout(self._g_rotate)
        self._angle = _dspin(self._g_rotate, -360.0, 360.0, decimals=3, value=90.0, step=15.0)
        self._cx = _dspin(self._g_rotate, -10000.0, 10000.0)
        self._cy = _dspin(self._g_rotate, -10000.0, 10000.0)
        center_btn = QPushButton("Центр площадок", self._g_rotate)
        center_btn.clicked.connect(self.use_pads_center)
        f.addRow("Угол, °:", self._angle)
        f.addRow("Центр X, мм:", self._cx)
        f.addRow("Центр Y, мм:", self._cy)
        f.addRow("", center_btn)
        grid.addWidget(self._g_rotate, 2, 1)

        # сдвиг
        self._g_move = self._group("Сдвиг")
        f = QFormLayout(self._g_move)
        self._dx = _dspin(self._g_move, -10000.0, 10000.0)
        self._dy = _dspin(self._g_move, -10000.0, 10000.0)
        f.addRow("dX, мм:", self._dx)
        f.addRow("dY, мм:", self._dy)
        grid.addWidget(self._g_move, 3, 0)

        self._error = _error_label(self)
        outer.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._update_scope_texts()
        self.set_scope("selected" if self._pads else "all")

    def _group(self, title: str) -> QGroupBox:
        g = QGroupBox(title, self)
        g.setCheckable(True)
        g.setChecked(False)
        return g

    # --- область -------------------------------------------------------------------------------
    def _update_scope_texts(self) -> None:
        fp = self._doc.fp
        total = 0 if fp is None else len(fp.pads)
        self._rb_selected.setText(f"Выбранные ({len(self._live_selected())})")
        self._rb_all.setText(f"Все ({total})")
        self._rb_selected.setEnabled(bool(self._pads))

    def _live_selected(self) -> list[Pad]:
        return [p for p in self._pads if self._doc.contains(p)]

    def set_pads(self, pads: Sequence[Pad]) -> None:
        """Задать выбранные площадки (представления площадок открытого корпуса)."""
        self._pads = [p for p in pads if isinstance(p, Pad)]
        self._update_scope_texts()
        if not self._pads:
            self.set_scope("all")

    def set_scope(self, scope: str) -> None:
        """Область операций: ``"selected"`` — выбранные площадки, ``"all"`` — все."""
        if scope not in ("selected", "all"):
            raise ValueError("область: selected или all")
        (self._rb_selected if scope == "selected" else self._rb_all).setChecked(True)

    @property
    def scope(self) -> str:
        """Текущая область: ``"selected"`` или ``"all"``."""
        return "selected" if self._rb_selected.isChecked() else "all"

    def target_pads(self, doc: Any = None) -> list[Pad]:
        """Площадки, к которым будут применены операции (в порядке файла)."""
        doc = doc or self._doc
        fp = doc.fp
        if fp is None:
            return []
        if self.scope == "all" or doc is not self._doc:
            return fp.pads if self.scope == "all" else []
        keys = {id(p.node) for p in self._live_selected()}
        return [p for p in fp.pads if id(p.node) in keys]

    # --- программное заполнение ----------------------------------------------------------------
    def clear_operations(self) -> None:
        """Выключить все операции."""
        for g in (self._g_renumber, self._g_type, self._g_size, self._g_drill, self._g_layers,
                  self._g_rotate, self._g_move):
            g.setChecked(False)

    def set_renumber(self, start: int = 1, order: str = "file", prefix: str = "",
                     enabled: bool = True) -> None:
        """Перенумерация: с номера ``start``, порядок ``order`` (ключ
        :data:`RENUMBER_ORDERS`), префикс ``prefix``."""
        idx = self._order.findData(order)
        if idx < 0:
            raise ValueError(f"порядок перенумерации: {', '.join(k for k, _ in RENUMBER_ORDERS)}")
        self._start.setValue(int(start))
        self._order.setCurrentIndex(idx)
        self._prefix.setText(prefix)
        self._g_renumber.setChecked(enabled)

    def set_type(self, pad_type: str | None = None, shape: str | None = None,
                 enabled: bool = True) -> None:
        """Тип (:data:`~kicadfp.model.PAD_TYPES`) и/или форма
        (:data:`~kicadfp.model.PAD_SHAPES`); ``None`` — не менять."""
        for combo, value, allowed, what in ((self._type, pad_type, PAD_TYPES, "тип"),
                                            (self._shape, shape, PAD_SHAPES, "форма")):
            if value is None:
                combo.setCurrentIndex(0)
            elif value not in allowed:
                raise ValueError(f"{what}: недопустимое значение {value!r}")
            else:
                combo.setCurrentText(value)
        self._g_type.setChecked(enabled)

    def set_size(self, size_x: float, size_y: float | None = None, enabled: bool = True) -> None:
        """Общий размер площадок (``size_y`` по умолчанию равен ``size_x``)."""
        self._size_x.setValue(float(size_x))
        self._size_y.setValue(float(size_x if size_y is None else size_y))
        self._g_size.setChecked(enabled)

    def set_drill(self, value: float | tuple[float, float] | str | None,
                  enabled: bool = True) -> None:
        """Общее отверстие: число, пара (овал), строка или ``None`` (удалить отверстие)."""
        if value is None:
            text = ""
        elif isinstance(value, (tuple, list)):
            text = f"{format_mm(float(value[0]))} x {format_mm(float(value[1]))}"
        elif isinstance(value, str):
            text = value
        else:
            text = format_mm(float(value))
        self._drill.setText(text)
        self._g_drill.setChecked(enabled)

    def set_layers(self, value: str | Iterable[str], enabled: bool = True) -> None:
        """Слои: ключ пресета (``thru_hole``, ``smd`` …), строка через запятую или список."""
        text = value if isinstance(value, str) else ", ".join(value)
        self._layers.setCurrentText(text)
        self._g_layers.setChecked(enabled)

    def set_rotate(self, angle: float, origin: tuple[float, float] = (0.0, 0.0),
                   enabled: bool = True) -> None:
        """Поворот на ``angle`` градусов вокруг точки ``origin``."""
        self._angle.setValue(float(angle))
        self._cx.setValue(float(origin[0]))
        self._cy.setValue(float(origin[1]))
        self._g_rotate.setChecked(enabled)

    def set_move(self, dx: float, dy: float, enabled: bool = True) -> None:
        """Сдвиг на ``(dx, dy)`` мм."""
        self._dx.setValue(float(dx))
        self._dy.setValue(float(dy))
        self._g_move.setChecked(enabled)

    def use_pads_center(self) -> None:
        """Подставить центр поворота — середину габарита целевых площадок."""
        pads = self.target_pads()
        if not pads:
            return
        xs = [p.x for p in pads]
        ys = [p.y for p in pads]
        self._cx.setValue((min(xs) + max(xs)) / 2)
        self._cy.setValue((min(ys) + max(ys)) / 2)

    # --- чтение формы --------------------------------------------------------------------------
    @property
    def error_text(self) -> str:
        """Текст строки ошибки (пусто — ошибок нет)."""
        return self._error.text()

    def operations(self) -> dict[str, Any]:
        """Включённые операции с проверенными параметрами: ``{"renumber": (start, order,
        prefix), "type": (тип|None, форма|None), "size": (x, y), "drill": значение|None,
        "layers": список|ключ пресета, "rotate": (угол, (x, y)), "move": (dx, dy)}``;
        ``ValueError`` — неверный ввод."""
        ops: dict[str, Any] = {}
        if self._g_renumber.isChecked():
            ops["renumber"] = (int(self._start.value()), self._order.currentData(),
                               self._prefix.text().strip())
        if self._g_type.isChecked():
            t = self._type.currentText()
            s = self._shape.currentText()
            t_val = None if t == _KEEP else t
            s_val = None if s == _KEEP else s
            if t_val is not None or s_val is not None:
                ops["type"] = (t_val, s_val)
        if self._g_size.isChecked():
            ops["size"] = (float(self._size_x.value()), float(self._size_y.value()))
        if self._g_drill.isChecked():
            text = self._drill.text().strip()
            ops["drill"] = None if not text else parse_pair(text, "отверстие")
        if self._g_layers.isChecked():
            text = self._layers.currentText().strip()
            if text in _layers.PAD_LAYER_PRESETS:
                ops["layers"] = text
            else:
                names = parse_layers(text)
                ops["layers"] = _preset_key(names) or names
        if self._g_rotate.isChecked():
            ops["rotate"] = (float(self._angle.value()),
                             (float(self._cx.value()), float(self._cy.value())))
        if self._g_move.isChecked():
            ops["move"] = (float(self._dx.value()), float(self._dy.value()))
        return ops

    # --- выполнение ----------------------------------------------------------------------------
    @staticmethod
    def _renumber_subset(pads: list[Pad], start: int, order: str, prefix: str) -> None:
        """Перенумеровать только площадки ``pads`` (без ``np_thru_hole``); площадки с
        одинаковым непустым номером получают общий новый номер."""
        groups: dict[Any, list[Pad]] = {}
        for i, p in enumerate(pads):
            if p.type == "np_thru_hole":
                continue
            key = ("num", p.number) if p.number else ("pad", i)
            groups.setdefault(key, []).append(p)
        keys = list(groups)

        def pos(k: Any) -> tuple[float, float]:
            ps = groups[k]
            return (sum(q.x for q in ps) / len(ps), sum(q.y for q in ps) / len(ps))

        if order == "xy":
            keys.sort(key=lambda k: (round(pos(k)[0], 6), round(pos(k)[1], 6)))
        elif order == "yx":
            keys.sort(key=lambda k: (round(pos(k)[1], 6), round(pos(k)[0], 6)))
        elif order == "circular" and keys:
            pts = {k: pos(k) for k in keys}
            cx = sum(x for x, _ in pts.values()) / len(pts)
            cy = sum(y for _, y in pts.values()) / len(pts)

            def ang(k: Any) -> float:
                x, y = pts[k]
                return math.atan2(-(y - cy), x - cx)  # ось Y вниз: против часовой на экране

            a0 = ang(keys[0])
            keys.sort(key=lambda k: round((ang(k) - a0) % (2 * math.pi), 9))
        for i, k in enumerate(keys):
            for p in groups[k]:
                p.number = f"{prefix}{start + i}"

    @staticmethod
    def _change_type(pad: Pad, new_type: str, keep_layers: bool) -> None:
        old_key = _preset_key(pad.layers) if pad.layers else pad.type
        pad.type = new_type
        if not keep_layers and old_key is not None:
            back = old_key.endswith("_back")
            key = f"{new_type}_back" if back and f"{new_type}_back" in \
                _layers.PAD_LAYER_PRESETS else new_type
            if key in _layers.PAD_LAYER_PRESETS:
                pad.set_layers(key)
        if new_type in ("smd", "connect"):
            if pad.drill is not None:
                pad.drill = None
        elif pad.drill is None:
            d = round(min(pad.size_x, pad.size_y) * _DEFAULT_DRILL_RATIO, 2)
            pad.drill = d if d > 0 else 0.8

    def _perform(self, work: Footprint, pads: list[Pad], all_pads: bool,
                 ops: dict[str, Any]) -> None:
        if "renumber" in ops:
            start, order, prefix = ops["renumber"]
            if all_pads:
                rule = f"prefix:{prefix}" if prefix else "sequential"
                work.renumber_pads(rule, start=start, order=order)
            else:
                self._renumber_subset(pads, start, order, prefix)
        if "type" in ops:
            new_type, new_shape = ops["type"]
            for p in pads:
                if new_type is not None and new_type != p.type:
                    self._change_type(p, new_type, keep_layers="layers" in ops)
                if new_shape is not None and new_shape != p.shape:
                    p.shape = new_shape
        if "size" in ops:
            for p in pads:
                p.size = ops["size"]
        if "drill" in ops:
            for p in pads:
                p.drill = ops["drill"]
        if "layers" in ops:
            layers = ops["layers"]
            for p in pads:
                if isinstance(layers, str):
                    p.set_layers(layers)
                else:
                    p.layers = layers
        if "rotate" in ops:
            angle, origin = ops["rotate"]
            if angle:
                for p in pads:
                    p.rotate(angle, origin)
        if "move" in ops:
            dx, dy = ops["move"]
            if dx or dy:
                for p in pads:
                    p.move(dx, dy)

    _OP_TITLES = {"renumber": "перенумерация", "type": "смена типа/формы", "size": "размер",
                  "drill": "отверстие", "layers": "слои", "rotate": "поворот", "move": "сдвиг"}

    def apply_to(self, doc: Any = None, pads: Sequence[Pad] | None = None) -> bool:
        """Выполнить включённые операции над площадками ``pads`` (по умолчанию — по
        области диалога) документа ``doc`` (по умолчанию — документ диалога) одной
        командой (один шаг отмены). ``True`` — модель изменена; при ошибке сообщение — в
        строке ошибки, модель не меняется, результат ``False``."""
        doc = doc or self._doc
        _set_error_label(self._error, "")
        fp = doc.fp
        if fp is None:
            _set_error_label(self._error, "Корпус не открыт")
            return False
        targets = list(pads) if pads is not None else self.target_pads(doc)
        live = fp.pads
        index = {id(p.node): i for i, p in enumerate(live)}
        idx = sorted({index[id(p.node)] for p in targets if id(p.node) in index})
        if not idx:
            _set_error_label(self._error, "Нет площадок для операции")
            return False
        try:
            ops = self.operations()
        except ValueError as e:
            _set_error_label(self._error, str(e))
            return False
        if not ops:
            _set_error_label(self._error, "Не выбрано ни одной операции")
            return False
        before = fp.copy()
        work = fp.copy()
        wpads = work.pads
        sel = [wpads[i] for i in idx]
        try:
            self._perform(work, sel, len(idx) == len(live), ops)
        except (ValueError, TypeError, KeyError) as e:
            _set_error_label(self._error, f"Операция не выполнена: {e}")
            return False
        titles = ", ".join(self._OP_TITLES[k] for k in ops)
        cmd = ReplaceNodeCommand(doc, before, work,
                                 f"групповая операция над площадками ({titles})")
        try:
            return bool(doc.apply(cmd))
        except (ValueError, RuntimeError, TypeError) as e:
            _set_error_label(self._error, f"Операция не выполнена: {e}")
            return False

    def accept(self) -> None:  # noqa: D401 — переопределение Qt
        """«Применить»: выполнить операции; при ошибке диалог остаётся открытым."""
        if self.apply_to() or (not self.error_text):
            super().accept()


# =============================================================================================
# Свойства элемента
# =============================================================================================

_NUM_SPLIT = re.compile(r"[\s,;]+")


@dataclass
class _Field:
    attr: str
    label: str
    kind: str                       # см. ItemPropertiesDialog._make
    options: Sequence[str] = ()
    widget: Any = None
    shown: Any = None               # состояние виджета после последнего reload()


def _parse_point(text_x: str, text_y: str, what: str) -> tuple[float, float]:
    return (parse_number(text_x, f"{what} X"), parse_number(text_y, f"{what} Y"))


class ItemPropertiesDialog(QDialog):
    """Свойства элемента корпуса в форме: площадка (:class:`~kicadfp.model.Pad`), фигура
    (:class:`~kicadfp.model.Graphic`), текст (:class:`~kicadfp.model.Text`) или 3D-модель
    (:class:`~kicadfp.model.Model`).

    Поля — все редактируемые свойства представления, виджет — по типу: числа —
    ``QLineEdit`` (точное значение, десятичная точка или запятая; у необязательных пусто —
    «не задано»), перечисления — ``QComboBox``, флаги — ``QCheckBox`` (трёхпозиционный для
    ``bool | None``), точки — пара полей X/Y, списки — строка через пробел/запятую.
    :meth:`apply` присваивает **только изменённые** свойства одной командой
    :class:`~kicadfp.gui.commands.SetAttrsCommand` (один шаг отмены); ошибка — в строке
    ошибки, модель не меняется. Программно: :meth:`set_field`, :meth:`field_value`,
    :meth:`changes`, :meth:`apply`; :meth:`reload` — перечитать значения из модели.
    """

    def __init__(self, doc: Any, item: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        item = doc.selected if item is None else item
        if item is None:
            raise ValueError("не выбран элемент")
        if isinstance(item, Footprint):
            raise TypeError("свойства корпуса редактируются на панели свойств корпуса")
        item = doc.bind(item)
        if not isinstance(item, (Pad, Graphic, Text, Model)):
            raise TypeError(f"свойства элемента {type(item).__name__} не редактируются")
        self._item: View = item
        self._fields: dict[str, _Field] = {}
        self.setWindowTitle(f"Свойства {describe_item(item)}")
        outer = QVBoxLayout(self)
        host = QWidget(self)
        self._form = QFormLayout(host)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)
        self._host = host
        for f in self._field_specs(item):
            self._add(f)
        self._error = _error_label(self)
        outer.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.Apply, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        outer.addWidget(buttons)
        self.resize(420, 560)
        self.reload()
        doc.changed.connect(self._on_changed)

    # --- описание полей --------------------------------------------------------------------------
    @staticmethod
    def _field_specs(item: Any) -> list[_Field]:
        F = _Field
        if isinstance(item, Pad):
            return [
                F("number", "Номер", "text"),
                F("type", "Тип", "enum", PAD_TYPES),
                F("shape", "Форма", "enum", PAD_SHAPES),
                F("position", "Положение, мм", "point"),
                F("angle", "Поворот, °", "num"),
                F("size_x", "Размер X, мм", "pos"),
                F("size_y", "Размер Y, мм", "pos"),
                F("drill", "Отверстие, мм", "drill"),
                F("layers", "Слои", "layers"),
                F("roundrect_rratio", "Скругление (доля)", "optnum"),
                F("chamfer_ratio", "Фаска (доля)", "optnum"),
                F("chamfer", "Срезанные углы", "list"),
                F("rect_delta", "Скос трапеции, мм", "optpoint"),
                F("pinfunction", "Функция вывода", "opttext"),
                F("pintype", "Тип вывода", "opttext"),
                F("property", "Свойство площадки", "opttext"),
                F("clearance", "Зазор, мм", "optnum"),
                F("solder_mask_margin", "Зазор маски, мм", "optnum"),
                F("solder_paste_margin", "Зазор пасты, мм", "optnum"),
                F("solder_paste_ratio", "Коэффициент пасты", "optnum"),
                F("zone_connect", "Подключение к зонам", "optint"),
                F("thermal_bridge_width", "Ширина термомоста, мм", "optnum"),
                F("thermal_bridge_angle", "Угол термомоста, °", "optnum"),
                F("thermal_gap", "Зазор термомоста, мм", "optnum"),
                F("die_length", "Длина вывода в корпусе, мм", "optnum"),
                F("remove_unused_layers", "Удалять неиспользуемые слои", "tribool"),
                F("keep_end_layers", "Сохранять крайние слои", "tribool"),
                F("locked", "Заблокирована", "bool"),
                F("uuid", "UUID", "readonly"),
            ]
        if isinstance(item, Graphic):
            specs = [F("layer", "Слой", "layer"),
                     F("width", "Ширина линии, мм", "optnum"),
                     F("stroke_type", "Тип линии", "optenum", STROKE_TYPES)]
            if item.kind in ("rect", "circle", "poly"):
                specs.append(F("fill", "Заливка", "bool"))
            if isinstance(item, (Line, Rect)):
                specs += [F("start", "Начало, мм", "point"), F("end", "Конец, мм", "point")]
            elif isinstance(item, Circle):
                specs += [F("center", "Центр, мм", "point"), F("radius", "Радиус, мм", "pos")]
            elif isinstance(item, Arc):
                specs += [F("start", "Начало, мм", "point"), F("mid", "Середина, мм", "point"),
                          F("end", "Конец, мм", "point")]
            elif isinstance(item, (Poly, Curve)):
                specs.append(F("points", "Точки (x y по строкам), мм", "points"))
            specs += [F("locked", "Заблокирована", "bool"), F("uuid", "UUID", "readonly")]
            return specs
        if isinstance(item, Text):
            specs = [F("kind", "Вид", "readonly")]
            if item.name is not None:
                specs.append(F("name", "Поле", "readonly"))
            specs += [
                F("text", "Текст", "text"),
                F("position", "Положение, мм", "point"),
                F("angle", "Поворот, °", "num"),
                F("layer", "Слой", "layer"),
                F("hide", "Скрыт", "bool"),
                F("font_size_x", "Ширина шрифта, мм", "pos"),
                F("font_size_y", "Высота шрифта, мм", "pos"),
                F("thickness", "Толщина линий, мм", "optnum"),
                F("bold", "Полужирный", "bool"),
                F("italic", "Курсив", "bool"),
                F("justify", f"Выравнивание ({' '.join(JUSTIFY_VALUES)})", "list"),
                F("knockout", "Инверсия (knockout)", "bool"),
                F("unlocked", "Не поворачивать с корпусом", "tribool"),
                F("face", "Шрифт", "opttext"),
                F("locked", "Заблокирован", "bool"),
                F("uuid", "UUID", "readonly"),
            ]
            return specs
        return [
            F("path", "Файл модели", "text"),
            F("hide", "Скрыта", "bool"),
            F("opacity", "Непрозрачность", "optnum"),
            F("offset", "Смещение X Y Z, мм", "xyz"),
            F("scale", "Масштаб X Y Z", "xyz"),
            F("rotate", "Поворот X Y Z, °", "xyz"),
        ]

    def _add(self, f: _Field) -> None:
        host = self._host
        if f.kind in ("enum", "optenum"):
            w: Any = QComboBox(host)
            if f.kind == "optenum":
                w.addItem("")
            w.addItems(list(f.options))
        elif f.kind in ("layer", "layers"):
            w = QComboBox(host)
            w.setEditable(True)
            w.addItems(list(_layers.ALL_LAYERS) if f.kind == "layer" else LAYER_PRESET_TEXTS)
        elif f.kind == "bool":
            w = QCheckBox(host)
        elif f.kind == "tribool":
            w = QCheckBox(host)
            w.setTristate(True)
            w.setToolTip("Серый — не задано")
        elif f.kind in ("point", "optpoint"):
            w = QWidget(host)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            w.ex = QLineEdit(w)
            w.ey = QLineEdit(w)
            w.ex.setPlaceholderText("X")
            w.ey.setPlaceholderText("Y")
            lay.addWidget(w.ex)
            lay.addWidget(w.ey)
        elif f.kind == "points":
            w = QPlainTextEdit(host)
            w.setMinimumHeight(90)
        else:
            w = QLineEdit(host)
            if f.kind == "readonly":
                w.setReadOnly(True)
            elif f.kind.startswith("opt"):
                w.setPlaceholderText("не задано")
        f.widget = w
        self._fields[f.attr] = f
        self._form.addRow(f"{f.label}:", w)

    # --- доступ ---------------------------------------------------------------------------------
    @property
    def item(self) -> View:
        """Редактируемый элемент."""
        return self._item

    @property
    def error_text(self) -> str:
        """Текст строки ошибки (пусто — ошибок нет)."""
        return self._error.text()

    def field_names(self) -> list[str]:
        """Свойства в форме (в порядке присваивания)."""
        return list(self._fields)

    def field_widget(self, attr: str) -> QWidget:
        """Виджет поля ``attr``."""
        return self._fields[attr].widget

    # --- значения полей -------------------------------------------------------------------------
    def _write(self, f: _Field, value: Any) -> None:
        w = f.widget
        k = f.kind
        if k in ("enum", "optenum"):
            text = "" if value is None else str(value)
            i = w.findText(text)
            if i < 0:
                w.addItem(text)
                i = w.findText(text)
            w.setCurrentIndex(i)
        elif k == "layer":
            w.setCurrentText("" if value is None else str(value))
        elif k == "layers":
            w.setCurrentText(value if isinstance(value, str) else ", ".join(value or ()))
        elif k == "bool":
            w.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        elif k == "tribool":
            w.setCheckState(Qt.CheckState.PartiallyChecked if value is None else
                            Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        elif k in ("point", "optpoint"):
            if value is None:
                w.ex.setText("")
                w.ey.setText("")
            else:
                w.ex.setText(format_mm(value[0]))
                w.ey.setText(format_mm(value[1]))
        elif k == "points":
            w.setPlainText("\n".join(f"{format_mm(x)} {format_mm(y)}" for x, y in value or ()))
        elif k == "drill":
            if value is None:
                w.setText("")
            elif isinstance(value, (tuple, list)):
                w.setText(f"{format_mm(value[0])} x {format_mm(value[1])}")
            elif hasattr(value, "oval"):
                if value.oval:
                    sx, sy = value.size
                    w.setText(f"{format_mm(sx)} x {format_mm(sy)}")
                else:
                    w.setText("" if not value.diameter else format_mm(value.diameter))
            else:
                w.setText(format_mm(float(value)))
        elif k == "list":
            w.setText("" if value is None else
                      value if isinstance(value, str) else " ".join(str(v) for v in value))
        elif k == "xyz":
            w.setText(" ".join(format_mm(v) for v in value))
        elif k in ("num", "pos", "optnum"):
            w.setText("" if value is None else format_mm(float(value)))
        elif k == "optint":
            w.setText("" if value is None else str(int(value)))
        else:
            w.setText("" if value is None else str(value))

    def _read(self, f: _Field) -> Any:
        w = f.widget
        k = f.kind
        what = f.label.split(",")[0]
        if k == "enum":
            return w.currentText()
        if k == "optenum":
            return w.currentText() or None
        if k == "layer":
            name = w.currentText().strip()
            if not _layers.is_valid_layer(name):
                raise ValueError(f"{what}: неизвестный слой «{name}»")
            return name
        if k == "layers":
            text = w.currentText().strip()
            if text in _layers.PAD_LAYER_PRESETS:
                return list(_layers.PAD_LAYER_PRESETS[text])
            return parse_layers(text)
        if k == "bool":
            return w.checkState() == Qt.CheckState.Checked
        if k == "tribool":
            st = w.checkState()
            return None if st == Qt.CheckState.PartiallyChecked else st == Qt.CheckState.Checked
        if k in ("point", "optpoint"):
            tx, ty = w.ex.text().strip(), w.ey.text().strip()
            if k == "optpoint" and not tx and not ty:
                return None
            return _parse_point(tx, ty, what)
        if k == "points":
            pts = []
            for n, line in enumerate(w.toPlainText().splitlines(), 1):
                parts = [p for p in _NUM_SPLIT.split(line.strip()) if p]
                if not parts:
                    continue
                if len(parts) != 2:
                    raise ValueError(f"{what}: строка {n}: ожидается «x y»")
                pts.append((parse_number(parts[0], what), parse_number(parts[1], what)))
            return pts
        if k == "drill":
            text = w.text().strip()
            return None if not text else parse_pair(text, what)
        if k == "list":
            return [p for p in _NUM_SPLIT.split(w.text().strip()) if p]
        if k == "xyz":
            parts = [p for p in _NUM_SPLIT.split(w.text().strip()) if p]
            if len(parts) != 3:
                raise ValueError(f"{what}: ожидается три числа X Y Z")
            return tuple(parse_number(p, what) for p in parts)
        if k == "num":
            return parse_number(w.text(), what)
        if k == "pos":
            return parse_number(w.text(), what, minimum=0.0, strict_minimum=True)
        if k == "optnum":
            text = w.text().strip()
            return None if not text else parse_number(text, what)
        if k == "optint":
            text = w.text().strip()
            if not text:
                return None
            v = parse_number(text, what)
            if not v.is_integer():
                raise ValueError(f"{what}: ожидается целое число")
            return int(v)
        if k == "opttext":
            return w.text() or None
        return w.text()

    def _current(self, f: _Field) -> Any:
        value = getattr(self._item, f.attr)
        if f.kind == "drill" and value is not None:
            if value.oval:
                return tuple(value.size)
            return None if not value.diameter else value.diameter
        if f.kind == "points":
            return [tuple(p) for p in value]
        return value

    @staticmethod
    def _widget_state(f: _Field) -> Any:
        """Содержимое виджета поля (текст, выбранный пункт, состояние флажка) — для
        сравнения с показанным при :meth:`reload`."""
        w = f.widget
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QCheckBox):
            return w.checkState()
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText()
        if isinstance(w, QLineEdit):
            return w.text()
        if hasattr(w, "ex"):
            return (w.ex.text(), w.ey.text())
        return None

    def reload(self) -> None:
        """Перечитать значения полей из модели (несохранённый ввод теряется)."""
        for f in self._fields.values():
            try:
                self._write(f, self._current(f))
            except Exception:  # noqa: BLE001 — узел необычной формы: поле пустое
                if f.kind not in ("xyz", "points"):
                    self._write(f, None)
            f.shown = self._widget_state(f)
        _set_error_label(self._error, "")

    def set_field(self, attr: str, value: Any) -> None:
        """Записать в поле ``attr`` значение (в том виде, в каком его возвращает свойство
        модели, или строкой как ввёл бы пользователь). ``KeyError`` — нет такого поля."""
        f = self._fields[attr]
        if f.kind == "readonly":
            raise ValueError(f"поле {attr!r} только для чтения")
        if isinstance(value, str) and f.kind not in ("enum", "optenum", "layer", "layers",
                                                     "text", "opttext", "list"):
            w = f.widget
            if f.kind in ("point", "optpoint"):
                parts = [p for p in _NUM_SPLIT.split(value.strip()) if p]
                w.ex.setText(parts[0] if parts else "")
                w.ey.setText(parts[1] if len(parts) > 1 else "")
            elif f.kind == "points":
                w.setPlainText(value)
            elif f.kind in ("bool", "tribool"):
                self._write(f, value.strip().lower() in ("1", "true", "yes", "да"))
            else:
                w.setText(value)
            return
        self._write(f, value)

    def field_value(self, attr: str) -> Any:
        """Значение поля ``attr`` (разобранное); ``ValueError`` — неверный ввод."""
        return self._read(self._fields[attr])

    def changes(self) -> dict[str, Any]:
        """Изменённые свойства ``{свойство: новое значение}`` в порядке полей;
        ``ValueError`` — неверный ввод.

        Поле, содержимое которого не менялось после :meth:`reload`, изменённым не
        считается, даже если показанный текст округлён (значение с более чем 6 знаками
        после точки, пересчёт из дюймов): нетронутое свойство не переписывается."""
        out: dict[str, Any] = {}
        item = self._item
        for f in self._fields.values():
            if f.kind == "readonly":
                continue
            if f.shown is not None and self._widget_state(f) == f.shown:
                continue
            new = self._read(f)
            old = self._current(f)
            if f.kind == "layers" and old is not None and set(new) == set(old):
                continue
            if f.kind == "list" and old is not None and set(new) == set(old):
                continue
            if not _close(new, old):
                out[f.attr] = new
        if isinstance(item, Circle) and ("center" in out or "radius" in out):
            # окружность: смена центра сдвигает её целиком, радиус — вдоль прежнего
            # направления (центр и точку на окружности присваиваем явно)
            (cx, cy), (ex, ey) = item.center, item.end
            ncx, ncy = out.pop("center", (cx, cy))
            r = out.pop("radius", item.radius)
            d = math.hypot(ex - cx, ey - cy)
            ux, uy = ((ex - cx) / d, (ey - cy) / d) if d else (1.0, 0.0)
            if not _close((ncx, ncy), (cx, cy)):
                out["center"] = (ncx, ncy)
            end = (ncx + ux * r, ncy + uy * r)
            if not _close(end, (ex, ey)):
                out["end"] = end
        return out

    def apply(self) -> bool:
        """Присвоить изменённые свойства одной командой. ``True`` — успешно (в том числе
        если менять нечего); ошибка — сообщение в строке ошибки, ``False``."""
        _set_error_label(self._error, "")
        if not self._doc.contains(self._item):
            _set_error_label(self._error, "Элемента больше нет в корпусе")
            return False
        try:
            values = self.changes()
        except ValueError as e:
            _set_error_label(self._error, str(e))
            return False
        if not values:
            return True
        cmd = SetAttrsCommand(self._doc, self._item, values,
                              f"изменение свойств {describe_item(self._item)}")
        try:
            self._doc.apply(cmd)
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            _set_error_label(self._error, str(e))
            return False
        if isinstance(cmd.view, View) and type(cmd.view) is not type(self._item):
            self._item = cmd.view
        return True

    def _on_changed(self) -> None:
        if self._doc.contains(self._item):
            try:
                self._item = self._doc.bind(self._item)
            except (ValueError, RuntimeError):
                return
            self.reload()
        else:
            _set_error_label(self._error, "Элемента больше нет в корпусе")

    def accept(self) -> None:  # noqa: D401 — переопределение Qt
        """«ОК»: применить изменения; при ошибке диалог остаётся открытым."""
        if self.apply():
            super().accept()

    def done(self, result: int) -> None:  # noqa: D401 — переопределение Qt
        try:
            self._doc.changed.disconnect(self._on_changed)
        except (RuntimeError, TypeError):
            pass
        super().done(result)


#: Синоним (название из architecture.md §14).
PropertiesDialog = ItemPropertiesDialog


# =============================================================================================
# О программе
# =============================================================================================

class AboutDialog(QDialog):
    """«О программе»: название, версия kicadfp, версии Python, PySide6 и Qt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("О программе kicadfp")
        layout = QVBoxLayout(self)
        #: Версия kicadfp.
        self.version = __version__
        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setText(
            f"<h3>kicadfp {__version__}</h3>"
            "<p>Библиотека и редактор файлов посадочных мест KiCad (форматы KiCad 5–10, "
            "старый формат .mod).</p>"
            f"<p>Python {platform.python_version()}, PySide6 {_pyside_version}, "
            f"Qt {qVersion()}</p>"
            "<p>Лицензия MIT.</p>")
        layout.addWidget(self._label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def text(self) -> str:
        """Текст окна (HTML)."""
        return self._label.text()
