"""Создание и общая настройка ``QApplication`` графического интерфейса kicadfp.

* :func:`create_app` — вернуть существующий ``QApplication`` или создать новый и настроить
  его (:func:`setup_app`): имя/организация (для ``QSettings``), версия, стиль Fusion
  (одинаковый вид на всех платформах), палитра (светлая, тёмная или по системе),
  значок окна, русский перевод стандартных надписей Qt.
* Перевод: ``qtbase_ru`` из поставки Qt (кнопки ``QDialogButtonBox``/``QMessageBox``,
  «Отменить %1»/«Повторить %1» стека отмены, контекстные меню полей ввода …), загружаемый
  через ``QLocale`` русского языка, плюс собственный переводчик kicadfp: уточнения
  («Discard» — «Не сохранять») и запасной перевод стандартных кнопок, если файлов перевода
  Qt нет.
* Числа: локаль по умолчанию (``QLocale.setDefault``) — «C» с десятичной **точкой** и без
  разделителя групп, как в файлах KiCad, поэтому ``QDoubleSpinBox``/``QDoubleValidator``
  показывают и принимают ``1.27``, а не ``1,27``. Язык надписей от этого не зависит.
* Тема: параметр ``theme`` или переменная окружения ``KICADFP_THEME`` — ``light``,
  ``dark`` или ``auto`` (по цветовой схеме системы, Qt ≥ 6.5; по умолчанию).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QPointF, QRectF, Qt, QTranslator
from PySide6.QtGui import (QColor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QStyleFactory

from .._version import __version__

__all__ = [
    "APP_NAME", "ORGANIZATION_NAME", "create_app", "setup_app", "install_translations",
    "ui_locale", "number_locale", "make_palette", "resolve_theme", "app_icon",
]

#: Имя приложения (``QSettings``, заголовки окон).
APP_NAME = "kicadfp"
#: Организация для ``QSettings``.
ORGANIZATION_NAME = "kicadfp"

_THEME_ENV = "KICADFP_THEME"
_CONFIGURED_PROPERTY = "kicadfp_configured"
# Переводчики должны жить, пока установлены: храним ссылки на уровне модуля.
_TRANSLATORS: list[QTranslator] = []


def ui_locale() -> QLocale:
    """Локаль надписей интерфейса — русский язык (Россия)."""
    return QLocale(QLocale.Language.Russian, QLocale.Country.Russia)


def number_locale() -> QLocale:
    """Локаль чисел — «C»: десятичная точка, без разделителя групп (как в файлах KiCad)."""
    loc = QLocale.c()
    loc.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator
                         | QLocale.NumberOption.RejectGroupSeparator)
    return loc


# ---------------------------------------------------------------------------------------------
# Перевод
# ---------------------------------------------------------------------------------------------

# Уточнения перевода Qt (действуют всегда): формулировки диалога «Сохранить изменения?».
_OVERRIDES: dict[tuple[str, str], str] = {
    ("QPlatformTheme", "Discard"): "Не сохранять",
    ("QPlatformTheme", "Don't Save"): "Не сохранять",
    ("QPlatformTheme", "Close without Saving"): "Закрыть без сохранения",
}

# Запасной перевод (если qtbase_ru не найден): стандартные кнопки и действия стека отмены.
_FALLBACK: dict[tuple[str, str], str] = {
    ("QPlatformTheme", "OK"): "OK",
    ("QPlatformTheme", "Save"): "Сохранить",
    ("QPlatformTheme", "Save All"): "Сохранить все",
    ("QPlatformTheme", "Open"): "Открыть",
    ("QPlatformTheme", "&Yes"): "&Да",
    ("QPlatformTheme", "Yes to &All"): "Да для &всех",
    ("QPlatformTheme", "&No"): "&Нет",
    ("QPlatformTheme", "N&o to All"): "Н&ет для всех",
    ("QPlatformTheme", "Abort"): "Прервать",
    ("QPlatformTheme", "Retry"): "Повторить",
    ("QPlatformTheme", "Ignore"): "Пропустить",
    ("QPlatformTheme", "Close"): "Закрыть",
    ("QPlatformTheme", "Cancel"): "Отмена",
    ("QPlatformTheme", "Help"): "Справка",
    ("QPlatformTheme", "Apply"): "Применить",
    ("QPlatformTheme", "Reset"): "Сбросить",
    ("QPlatformTheme", "Restore Defaults"): "Восстановить значения по умолчанию",
    ("QUndoStack", "Undo %1"): "Отменить %1",
    ("QUndoStack", "Redo %1"): "Повторить %1",
    ("QUndoStack", "Undo"): "Отменить действие",
    ("QUndoStack", "Redo"): "Повторить действие",
    ("QUndoModel", "<empty>"): "<пусто>",
    ("QMessageBox", "Show Details..."): "Показать подробности...",
    ("QMessageBox", "Hide Details..."): "Скрыть подробности...",
}


class _KicadfpTranslator(QTranslator):
    """Перевод из словаря ``{(контекст, исходный текст): перевод}`` (без файлов .qm)."""

    def __init__(self, table: dict[tuple[str, str], str], parent: QCoreApplication | None = None
                 ) -> None:
        super().__init__(parent)
        self._table = dict(table)

    def translate(self, context: str, source_text: str, disambiguation: str | None = None,
                  n: int = -1) -> str | None:  # noqa: D401 — переопределение Qt
        # None -> «нулевая» QString: Qt ищет перевод дальше (пустая строка "" была бы
        # переводом в пустой текст)
        return self._table.get((context, source_text))

    def isEmpty(self) -> bool:  # noqa: N802 — переопределение Qt
        return not self._table


def install_translations(app: QCoreApplication | None = None) -> bool:
    """Установить русский перевод стандартных надписей Qt в приложение (однократно).

    Возвращает, найден ли перевод Qt (``qtbase_ru.qm``); без него действует запасной
    перевод kicadfp."""
    app = app if app is not None else QCoreApplication.instance()
    if app is None:
        raise RuntimeError("install_translations: приложение Qt ещё не создано")
    if app.property("kicadfp_translations"):
        return bool(app.property("kicadfp_qt_translation"))
    qt_tr = QTranslator(app)
    found = False
    tr_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for base in ("qtbase", "qt"):
        if qt_tr.load(ui_locale(), base, "_", tr_dir):
            found = True
            break
    if found:
        app.installTranslator(qt_tr)
        _TRANSLATORS.append(qt_tr)
    table = dict(_OVERRIDES) if found else {**_FALLBACK, **_OVERRIDES}
    own = _KicadfpTranslator(table, app)
    app.installTranslator(own)  # установлен последним — просматривается первым
    _TRANSLATORS.append(own)
    app.setProperty("kicadfp_translations", True)
    app.setProperty("kicadfp_qt_translation", found)
    return found


# ---------------------------------------------------------------------------------------------
# Палитра и значок
# ---------------------------------------------------------------------------------------------

def resolve_theme(theme: str | None = None) -> str:
    """``"light"`` или ``"dark"``: из ``theme``, иначе из ``KICADFP_THEME``, иначе по
    цветовой схеме системы (``auto``)."""
    value = (theme or os.environ.get(_THEME_ENV) or "auto").strip().lower()
    if value in ("light", "dark"):
        return value
    if value != "auto":
        raise ValueError(f"неизвестная тема {value!r} (light, dark или auto)")
    try:
        hints = QGuiApplication.styleHints()
        if hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
    except (AttributeError, RuntimeError):  # Qt < 6.5 или нет приложения
        pass
    return "light"


def make_palette(theme: str = "light") -> QPalette:
    """Палитра интерфейса: ``"light"`` — стандартная палитра Fusion с синим выделением,
    ``"dark"`` — тёмная (для работы рядом с тёмной канвой)."""
    style = QStyleFactory.create("Fusion")
    pal = QPalette(style.standardPalette()) if style is not None else QPalette()
    highlight = QColor("#2f65ca")
    if theme == "dark":
        window, base, alt, text = (QColor("#2d2d30"), QColor("#1e1e1e"), QColor("#262628"),
                                   QColor("#e3e3e3"))
        disabled = QColor("#7c7c7c")
        roles = {
            QPalette.ColorRole.Window: window, QPalette.ColorRole.WindowText: text,
            QPalette.ColorRole.Base: base, QPalette.ColorRole.AlternateBase: alt,
            QPalette.ColorRole.ToolTipBase: QColor("#3c3c3f"),
            QPalette.ColorRole.ToolTipText: text, QPalette.ColorRole.Text: text,
            QPalette.ColorRole.Button: QColor("#3a3a3d"), QPalette.ColorRole.ButtonText: text,
            QPalette.ColorRole.BrightText: QColor("#ff6b6b"),
            QPalette.ColorRole.Link: QColor("#5ea3ff"),
            QPalette.ColorRole.Highlight: highlight,
            QPalette.ColorRole.HighlightedText: QColor("#ffffff"),
            QPalette.ColorRole.PlaceholderText: QColor("#8c8c8c"),
            QPalette.ColorRole.Light: QColor("#505053"),
            QPalette.ColorRole.Midlight: QColor("#454548"),
            QPalette.ColorRole.Mid: QColor("#303033"), QPalette.ColorRole.Dark: QColor("#1b1b1d"),
            QPalette.ColorRole.Shadow: QColor("#000000"),
        }
        for role, color in roles.items():
            pal.setColor(role, color)
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.WindowText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#44484f"))
    else:
        pal.setColor(QPalette.ColorRole.Highlight, highlight)
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Link, QColor("#1f5fbf"))
    return pal


def _draw_icon(size: int) -> QPixmap:
    """Значок: плата с корпусом DIP (контур шелкографии и два ряда площадок)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = size / 64.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1d4a2e"))
        p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 10 * s, 10 * s)
        pen = QPen(QColor("#f2f2f2"))
        pen.setWidthF(max(1.0, 2.2 * s))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(20 * s, 10 * s, 24 * s, 44 * s))
        p.drawArc(QRectF(28 * s, 6 * s, 8 * s, 8 * s), 180 * 16, 180 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d9a93a"))
        for i in range(4):
            y = (15 + i * 10) * s
            for x in (11 * s, 45 * s):
                if i == 0 and x < 20 * s:
                    p.drawRect(QRectF(x, y, 8 * s, 6 * s))
                else:
                    p.drawEllipse(QPointF(x + 4 * s, y + 3 * s), 4 * s, 3 * s)
    finally:
        p.end()
    return pm


def app_icon() -> QIcon:
    """Значок приложения (рисуется программно, в нескольких размерах)."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw_icon(size))
    return icon


# ---------------------------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------------------------

def setup_app(app: QApplication, *, style: str | None = "Fusion", theme: str | None = None
              ) -> QApplication:
    """Общие настройки приложения (см. модуль). Повторный вызов безопасен: перевод
    устанавливается один раз, стиль и палитра переустанавливаются."""
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    install_translations(app)
    QLocale.setDefault(number_locale())
    if style:
        st = QStyleFactory.create(style)
        if st is not None:
            app.setStyle(st)
    app.setPalette(make_palette(resolve_theme(theme)))
    if app.windowIcon().isNull() or not app.property(_CONFIGURED_PROPERTY):
        app.setWindowIcon(app_icon())
    app.setProperty(_CONFIGURED_PROPERTY, True)
    return app


def create_app(argv: Sequence[str] | None = None, *, style: str | None = "Fusion",
               theme: str | None = None) -> QApplication:
    """Существующий ``QApplication`` (например, созданный pytest-qt) или новый, настроенный
    :func:`setup_app`. ``argv`` — аргументы командной строки с именем программы первым
    элементом (Qt забирает из них свои ключи вроде ``-platform``/``-style``); по
    умолчанию — только имя программы. ``RuntimeError`` — уже создано приложение Qt без
    виджетов (``QCoreApplication``/``QGuiApplication``)."""
    app = QCoreApplication.instance()
    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        args = list(argv) if argv is not None else [sys.argv[0] if sys.argv and sys.argv[0]
                                                    else APP_NAME]
        app = QApplication(args or [APP_NAME])
    elif not isinstance(app, QApplication):
        raise RuntimeError("уже создано приложение Qt без поддержки виджетов "
                           f"({type(app).__name__}); графическому интерфейсу нужен QApplication")
    return setup_app(app, style=style, theme=theme)
