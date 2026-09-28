"""Панель свойств корпуса :class:`PropertiesPanel` (``QWidget`` с ``QFormLayout``).

Поля: имя, слой (сторона ``F.Cu``/``B.Cu``), описание (``descr``), ключевые слова
(``tags``), атрибуты (флажки ``smd``, ``through_hole``, ``board_only``,
``exclude_from_pos_files``, ``exclude_from_bom``, ``allow_missing_courtyard``, ``dnp``),
зазоры ``clearance``/``solder_mask_margin``/``solder_paste_margin``/``solder_paste_ratio``
(пусто — не задано), подключение к зонам (``zone_connect``: наследовать/0/1/2/3), версия
формата и UUID (только чтение).

Изменения применяются командами через ``doc.apply``: текстовые поля — по
``editingFinished``, флажки и списки — сразу. Панель обновляется по ``doc.changed()``
(сигналы виджетов при этом заблокированы — рекурсии нет). Недопустимый ввод
отклоняется: поле возвращается к значению модели, испускается :attr:`PropertiesPanel.error`.
Для программного заполнения (тесты, сценарии) — :meth:`PropertiesPanel.set_field`.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLineEdit, QVBoxLayout,
                               QWidget)

from ..model import Footprint
from .commands import SetAttrCommand
from .pad_table import format_mm, parse_number

__all__ = ["PropertiesPanel", "ATTR_FLAGS", "ATTR_LABELS", "NUMERIC_FIELDS", "ZONE_CONNECT_ITEMS",
           "TEXT_FIELDS"]

#: Флаги ``(attr …)``, показываемые флажками.
ATTR_FLAGS: tuple[str, ...] = ("smd", "through_hole", "board_only", "exclude_from_pos_files",
                               "exclude_from_bom", "allow_missing_courtyard", "dnp")

#: Надписи флажков атрибутов.
ATTR_LABELS: dict[str, str] = {
    "smd": "Поверхностный монтаж (smd)",
    "through_hole": "Выводной монтаж (through_hole)",
    "board_only": "Только на плате, нет в схеме (board_only)",
    "exclude_from_pos_files": "Не включать в файлы позиций (exclude_from_pos_files)",
    "exclude_from_bom": "Не включать в перечень элементов (exclude_from_bom)",
    "allow_missing_courtyard": "Допускается без области размещения (allow_missing_courtyard)",
    "dnp": "Не устанавливать (dnp)",
}

#: Числовые поля: свойство -> (надпись, минимальное значение или ``None``).
NUMERIC_FIELDS: dict[str, tuple[str, float | None]] = {
    "clearance": ("Зазор, мм", 0.0),
    "solder_mask_margin": ("Отступ маски, мм", None),
    "solder_paste_margin": ("Отступ пасты, мм", None),
    "solder_paste_ratio": ("Коэффициент пасты", None),
}

#: Текстовые поля: свойство -> надпись.
TEXT_FIELDS: dict[str, str] = {"name": "Имя", "descr": "Описание", "tags": "Ключевые слова"}

#: Пункты списка «Подключение к зонам»: (надпись, значение ``zone_connect``).
ZONE_CONNECT_ITEMS: tuple[tuple[str, int | None], ...] = (
    ("наследовать", None),
    ("0 — не подключать", 0),
    ("1 — термобарьеры", 1),
    ("2 — сплошное", 2),
    ("3 — термобарьеры только для сквозных", 3),
)

_SIDES = ("F.Cu", "B.Cu")
_DASH = "—"


class PropertiesPanel(QWidget):
    """Форма свойств открытого корпуса (см. модуль).

    Виджеты доступны как атрибуты: :attr:`name_edit`, :attr:`layer_combo`,
    :attr:`descr_edit`, :attr:`tags_edit`, :attr:`attr_checks` (``{флаг: QCheckBox}``),
    :attr:`numeric_edits` (``{свойство: QLineEdit}``), :attr:`zone_combo`,
    :attr:`version_edit`, :attr:`uuid_edit`. Флажки ``smd`` и ``through_hole``
    взаимоисключающие (тип монтажа в KiCad один)."""

    #: Отклонённый ввод или ошибка команды: текст для строки состояния.
    error = Signal(str)

    def __init__(self, doc: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form = form

        self.name_edit = QLineEdit(self)
        self.name_edit.editingFinished.connect(lambda: self.commit_field("name"))
        form.addRow(TEXT_FIELDS["name"], self.name_edit)

        self.layer_combo = QComboBox(self)
        self.layer_combo.addItems(_SIDES)
        self.layer_combo.currentIndexChanged.connect(lambda _i: self.commit_field("layer"))
        form.addRow("Слой", self.layer_combo)

        self.descr_edit = QLineEdit(self)
        self.descr_edit.editingFinished.connect(lambda: self.commit_field("descr"))
        form.addRow(TEXT_FIELDS["descr"], self.descr_edit)

        self.tags_edit = QLineEdit(self)
        self.tags_edit.editingFinished.connect(lambda: self.commit_field("tags"))
        form.addRow(TEXT_FIELDS["tags"], self.tags_edit)

        box = QWidget(self)
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)
        self.attr_checks: dict[str, QCheckBox] = {}
        for flag in ATTR_FLAGS:
            cb = QCheckBox(ATTR_LABELS[flag], box)
            cb.toggled.connect(lambda on, f=flag: self._on_attr_toggled(f, on))
            vbox.addWidget(cb)
            self.attr_checks[flag] = cb
        form.addRow("Атрибуты", box)

        self.numeric_edits: dict[str, QLineEdit] = {}
        for attr, (label, _minimum) in NUMERIC_FIELDS.items():
            ed = QLineEdit(self)
            ed.setPlaceholderText("не задано")
            ed.editingFinished.connect(lambda a=attr: self.commit_field(a))
            form.addRow(label, ed)
            self.numeric_edits[attr] = ed

        self.zone_combo = QComboBox(self)
        for text, value in ZONE_CONNECT_ITEMS:
            self.zone_combo.addItem(text, value)
        self.zone_combo.currentIndexChanged.connect(lambda _i: self.commit_field("zone_connect"))
        form.addRow("Подключение к зонам", self.zone_combo)

        self.version_edit = QLineEdit(self)
        self.version_edit.setReadOnly(True)
        form.addRow("Версия формата", self.version_edit)
        self.uuid_edit = QLineEdit(self)
        self.uuid_edit.setReadOnly(True)
        form.addRow("UUID", self.uuid_edit)

        doc.changed.connect(self.refresh)
        doc.document_changed.connect(self.refresh)
        self.refresh()

    # --- доступ ---------------------------------------------------------------------------------
    @property
    def document(self) -> Any:
        """Документ панели."""
        return self._doc

    def _text_edit(self, field: str) -> QLineEdit | None:
        if field == "name":
            return self.name_edit
        if field == "descr":
            return self.descr_edit
        if field == "tags":
            return self.tags_edit
        return self.numeric_edits.get(field)

    # --- обновление из модели --------------------------------------------------------------
    def _all_inputs(self) -> list[QWidget]:
        return [self.name_edit, self.layer_combo, self.descr_edit, self.tags_edit,
                *self.attr_checks.values(), *self.numeric_edits.values(), self.zone_combo]

    def refresh(self) -> None:
        """Показать значения открытого корпуса (без испускания сигналов виджетов)."""
        fp: Footprint | None = self._doc.fp
        widgets = self._all_inputs()
        was_blocked = [w.blockSignals(True) for w in widgets]
        try:
            self.setEnabled(fp is not None)
            if fp is None:
                for ed in (self.name_edit, self.descr_edit, self.tags_edit,
                           *self.numeric_edits.values(), self.version_edit, self.uuid_edit):
                    ed.clear()
                for cb in self.attr_checks.values():
                    cb.setChecked(False)
                self.layer_combo.setCurrentIndex(0)
                self.zone_combo.setCurrentIndex(0)
                return
            self._set_text(self.name_edit, fp.name)
            self._set_text(self.descr_edit, fp.descr)
            self._set_text(self.tags_edit, fp.tags)
            side = fp.layer
            i = self.layer_combo.findText(side)
            if i < 0:  # недопустимое значение в файле — показать как есть
                self.layer_combo.addItem(side)
                i = self.layer_combo.findText(side)
            self.layer_combo.setCurrentIndex(i)
            attrs = set(fp.attrs)
            for flag, cb in self.attr_checks.items():
                cb.setChecked(flag in attrs)
            for attr, ed in self.numeric_edits.items():
                self._set_text(ed, format_mm(getattr(fp, attr)))
            zi = self.zone_combo.findData(fp.zone_connect)
            self.zone_combo.setCurrentIndex(zi if zi >= 0 else 0)
            v = fp.version
            self.version_edit.setText(_DASH if v is None else str(v))
            self.uuid_edit.setText(fp.uuid or _DASH)
        finally:
            for w, b in zip(widgets, was_blocked, strict=True):
                w.blockSignals(b)

    @staticmethod
    def _set_text(ed: QLineEdit, text: str) -> None:
        if ed.text() != text:
            ed.setText(text)
            ed.setCursorPosition(0)

    # --- запись ---------------------------------------------------------------------------------
    def _apply(self, attr: str, value: Any) -> bool:
        fp = self._doc.fp
        if fp is None:
            return False
        try:
            self._doc.apply(SetAttrCommand(self._doc, fp, attr, value))
        except (ValueError, TypeError, AttributeError) as e:
            return self._reject(str(e))
        return True

    def _reject(self, message: str) -> bool:
        self.refresh()
        self.error.emit(message)
        return False

    def commit_field(self, field: str) -> bool:
        """Применить значение виджета поля ``field`` (``name``, ``layer``, ``descr``,
        ``tags``, ``clearance``, ``solder_mask_margin``, ``solder_paste_margin``,
        ``solder_paste_ratio``, ``zone_connect`` или флаг атрибута) к модели. ``True`` —
        применено или не изменилось; ``False`` — отклонено (поле восстановлено)."""
        fp = self._doc.fp
        if fp is None:
            return False
        if field in ("name", "descr", "tags"):
            ed = self._text_edit(field)
            assert ed is not None
            text = ed.text()
            if field == "name":
                text = text.strip()
                if not text:
                    return self._reject("имя корпуса не может быть пустым")
            if text == getattr(fp, field):
                return True
            return self._apply(field, text)
        if field == "layer":
            side = self.layer_combo.currentText()
            if side == fp.layer:
                return True
            return self._apply("layer", side)
        if field in NUMERIC_FIELDS:
            ed = self.numeric_edits[field]
            label, minimum = NUMERIC_FIELDS[field]
            text = ed.text().strip()
            if text:
                try:
                    value: float | None = parse_number(text, label, minimum=minimum)
                except ValueError as e:
                    return self._reject(str(e))
            else:
                value = None
            if value == getattr(fp, field):
                if text and format_mm(value) != text:
                    self.refresh()  # «0.50» -> «0.5»
                return True
            return self._apply(field, value)
        if field == "zone_connect":
            value = self.zone_combo.currentData()
            if value == fp.zone_connect:
                return True
            return self._apply("zone_connect", value)
        if field in self.attr_checks:
            return self._on_attr_toggled(field, self.attr_checks[field].isChecked())
        raise KeyError(f"неизвестное поле {field!r}")

    def commit_pending(self) -> bool:
        """Применить незавершённый ввод текстовых полей (набранный, но ещё без Enter и
        ухода фокуса) — перед записью файла и вопросом о несохранённых изменениях.
        ``False`` — какое-то значение отклонено (поле восстановлено из модели)."""
        if self._doc.fp is None:
            return True
        fp = self._doc.fp
        ok = True
        for field in ("name", "descr", "tags", *self.numeric_edits):
            ed = self._text_edit(field)
            if ed is None or not ed.isModified():  # пользователь в поле ничего не вводил
                continue
            shown = getattr(fp, field)
            shown = shown if field in ("name", "descr", "tags") else format_mm(shown)
            if ed.text() != shown:  # текст отличается от того, что показал refresh()
                ok = self.commit_field(field) and ok
        return ok

    def _on_attr_toggled(self, flag: str, on: bool) -> bool:
        fp = self._doc.fp
        if fp is None:
            return False
        attrs = set(fp.attrs)
        if (flag in attrs) == on:
            return True
        if on:
            attrs.add(flag)
            # тип монтажа один: smd и through_hole взаимоисключающие
            if flag == "smd":
                attrs.discard("through_hole")
            elif flag == "through_hole":
                attrs.discard("smd")
        else:
            attrs.discard(flag)
        ordered = [a for a in ATTR_FLAGS if a in attrs] + sorted(attrs - set(ATTR_FLAGS))
        return self._apply("attrs", ordered)

    def set_field(self, field: str, value: Any) -> bool:
        """Программно заполнить поле и применить его (как пользователь: ввод и
        ``editingFinished``). ``value``: строка для текстовых и числовых полей (``None`` —
        пусто), ``"F.Cu"``/``"B.Cu"`` для ``layer``, ``None``/0…3 для ``zone_connect``,
        ``bool`` для флагов атрибутов. Возвращает результат :meth:`commit_field`."""
        if field in self.attr_checks:
            cb = self.attr_checks[field]
            with QSignalBlocker(cb):
                cb.setChecked(bool(value))
            return self.commit_field(field)
        if field == "layer":
            i = self.layer_combo.findText(str(value))
            if i < 0:
                return self._reject(f"слой корпуса: недопустимое значение «{value}» "
                                    f"(допустимо: F.Cu, B.Cu)")
            with QSignalBlocker(self.layer_combo):
                self.layer_combo.setCurrentIndex(i)
            return self.commit_field("layer")
        if field == "zone_connect":
            i = self.zone_combo.findData(value)
            if i < 0:
                return self._reject(f"подключение к зонам: недопустимое значение «{value}»")
            with QSignalBlocker(self.zone_combo):
                self.zone_combo.setCurrentIndex(i)
            return self.commit_field("zone_connect")
        ed = self._text_edit(field)
        if ed is None:
            raise KeyError(f"неизвестное поле {field!r}")
        ed.setText("" if value is None else str(value))
        return self.commit_field(field)
