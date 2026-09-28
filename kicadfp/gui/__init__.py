"""Графический интерфейс kicadfp на PySide6 (architecture.md §14).

Модули:

* :mod:`kicadfp.gui.app` — создание и настройка ``QApplication`` (:func:`create_app`);
* :mod:`kicadfp.gui.document` — :class:`FootprintDocument`: открытый корпус, путь, стек
  отмены, выделение, сигналы ``changed``/``selection_changed``/``modified_changed``/
  ``document_changed``;
* :mod:`kicadfp.gui.commands` — команды отмены/повтора (все изменения модели в GUI идут
  через ``FootprintDocument.apply(команда)``);
* :mod:`kicadfp.gui.canvas` — канва корпуса ``PreviewCanvas``;
* :mod:`kicadfp.gui.pad_table`, :mod:`kicadfp.gui.items_table` — таблицы площадок и
  графики/текстов; :mod:`kicadfp.gui.props_panel` — панель свойств корпуса;
  :mod:`kicadfp.gui.libtree` — дерево библиотек; :mod:`kicadfp.gui.dialogs` — диалоги;
* :mod:`kicadfp.gui.mainwindow` — главное окно :class:`MainWindow`, собирающее всё это
  (меню, панель инструментов, док-панели, строка состояния, настройки ``QSettings``).

Импорт пакета не загружает PySide6: :func:`main` и имена :data:`__all__` импортируют его
при первом обращении, поэтому ``kicadfp gui`` без PySide6 выдаёт понятное сообщение.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "main", "create_app", "MainWindow", "FootprintDocument", "DocumentCommand",
    "SetAttrCommand", "SetAttrsCommand", "AddItemCommand", "RemoveItemCommand",
    "ReplaceNodeCommand", "OperationCommand", "BatchCommand",
]

INSTALL_HINT = "pip install kicadfp[gui]"

_USAGE = """\
использование: kicadfp-gui [ПУТЬ …]

Графический редактор посадочных мест KiCad (kicadfp).

  ПУТЬ   файл корпуса (.kicad_mod, .mod с одним корпусом) или каталог библиотеки .pretty

Ключи Qt (например, -platform offscreen, -style fusion) передаются Qt.
Тема оформления: переменная окружения KICADFP_THEME=light|dark|auto.
Файл настроек окна (INI) вместо стандартного места: переменная KICADFP_SETTINGS=ПУТЬ.
"""

# Имена, загружаемые лениво: имя -> (подмодуль, атрибут).
_LAZY: dict[str, tuple[str, str]] = {
    "create_app": ("app", "create_app"),
    "MainWindow": ("mainwindow", "MainWindow"),
    "FootprintDocument": ("document", "FootprintDocument"),
    "DocumentCommand": ("commands", "DocumentCommand"),
    "SetAttrCommand": ("commands", "SetAttrCommand"),
    "SetAttrsCommand": ("commands", "SetAttrsCommand"),
    "AddItemCommand": ("commands", "AddItemCommand"),
    "RemoveItemCommand": ("commands", "RemoveItemCommand"),
    "ReplaceNodeCommand": ("commands", "ReplaceNodeCommand"),
    "OperationCommand": ("commands", "OperationCommand"),
    "BatchCommand": ("commands", "BatchCommand"),
}


def __getattr__(name: str) -> Any:
    """Ленивый импорт классов GUI (PySide6 загружается при первом обращении)."""
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"модуль 'kicadfp.gui' не содержит атрибута {name!r}")
    module = importlib.import_module(f"{__name__}.{target[0]}")
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def _err(message: str) -> None:
    print(f"ошибка: {message}", file=sys.stderr)


def _open_in_window(window: Any, path: str) -> bool:
    """Открыть путь из командной строки в главном окне.

    Протокол главного окна: ``open_path(path)`` (файл или каталог ``.pretty``); если его
    нет — ``open_library(path)`` для каталога, ``open_file(path)`` или ``document.open(path)``
    (``doc.open(path)``) для файла. Ошибки печатаются и не мешают запуску окна."""
    p = Path(path)
    if not p.exists():
        _err(f"{p}: файл или каталог не найден")
        return False
    try:
        names = ("open_path", "open_library") if p.is_dir() else ("open_path", "open_file")
        for name in names:
            opener = getattr(window, name, None)
            if callable(opener):
                return opener(p) is not False
        if not p.is_dir():
            for name in ("document", "doc"):
                doc = getattr(window, name, None)
                if callable(doc) and not hasattr(doc, "open"):
                    doc = doc()
                if doc is not None and callable(getattr(doc, "open", None)):
                    return bool(doc.open(p))
        _err(f"{p}: главное окно не умеет открывать {'каталоги' if p.is_dir() else 'файлы'}")
        return False
    except Exception as e:  # noqa: BLE001 — ошибка чтения не должна мешать запуску окна
        _err(f"{p}: {e}")  # SexprSyntaxError: «строка N, позиция M: …»
        return False


def main(argv: Sequence[str] | None = None) -> int:
    """Запустить графический интерфейс: ``kicadfp-gui [ПУТЬ …]`` или ``kicadfp gui [ПУТЬ]``.

    ``argv`` — аргументы без имени программы (по умолчанию ``sys.argv[1:]``): пути к
    файлам корпусов или каталогам ``.pretty`` (открываются в главном окне) и ключи Qt.
    Создаёт ``QApplication`` при необходимости (:func:`kicadfp.gui.app.create_app`),
    показывает главное окно :class:`~kicadfp.gui.mainwindow.MainWindow`, открывает в нём
    пути (каталог — библиотекой в дереве, файл — в редакторе; ошибка чтения показывается в
    окне и не мешает запуску) и входит в цикл событий. Возвращает код завершения:
    результат цикла событий (0), 2 — нет PySide6 или главного окна.
    """
    args = [os.fspath(a) for a in (sys.argv[1:] if argv is None else argv)]
    if any(a in ("-h", "--help") for a in args):
        print(_USAGE, end="")
        return 0
    try:
        from PySide6.QtWidgets import QApplication

        from .app import create_app
    except ImportError as e:
        _err(f"для графического интерфейса нужен PySide6: установите его командой "
             f"{INSTALL_HINT} ({e})")
        return 2
    try:
        from .mainwindow import MainWindow
    except ImportError as e:
        if e.name == f"{__name__}.mainwindow":
            _err("не удалось загрузить главное окно (модуль kicadfp.gui.mainwindow "
                 "недоступен); переустановите kicadfp")
        elif (e.name or "").split(".")[0] in ("PySide6", "shiboken6"):
            _err(f"не хватает модуля PySide6 ({e}): переустановите его командой {INSTALL_HINT}")
        else:
            _err(f"не удалось загрузить главное окно: {e}")
        return 2
    created = QApplication.instance() is None
    prog = sys.argv[0] if sys.argv and sys.argv[0] else "kicadfp-gui"
    app = create_app([prog, *args])
    if created:
        # Qt убрал из списка свои ключи (-platform, -style …): остальное — пути
        remaining = list(app.arguments()[1:])
        paths = []
        for a in args:
            if a in remaining:
                remaining.remove(a)
                paths.append(a)
    else:
        paths = args
    window = MainWindow()
    window.show()  # сначала окно: сообщения об ошибках открытия появляются поверх него
    for path in paths:
        _open_in_window(window, path)
    return int(app.exec() or 0)
