"""Точка входа GUI ``kicadfp.gui.main`` и открытие путей из командной строки
(:func:`kicadfp.gui._open_in_window`): протокол главного окна и сообщения об ошибках."""

from __future__ import annotations

import builtins
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import kicadfp.gui as gui  # noqa: E402

from .conftest import FIXTURES  # noqa: E402

DIP_LIB = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14 = DIP_LIB / "DIP-14_W7.62mm.kicad_mod"


class _Doc:
    def __init__(self, result=True):
        self.opened = []
        self.result = result

    def open(self, path):
        self.opened.append(path)
        return self.result


def test_open_in_window_prefers_open_path():
    calls = []

    class W:
        def open_path(self, p):
            calls.append(("open_path", p))

        def open_file(self, p):  # pragma: no cover — не должен вызываться
            calls.append(("open_file", p))
    assert gui._open_in_window(W(), str(DIP14)) is True  # None -> «успешно»
    assert calls == [("open_path", DIP14)]


def test_open_in_window_library_and_file_fallbacks():
    calls = []

    class W:
        def open_library(self, p):
            calls.append(("lib", p))
            return False

        def open_file(self, p):
            calls.append(("file", p))
    w = W()
    assert gui._open_in_window(w, str(DIP_LIB)) is False  # opener вернул False
    assert gui._open_in_window(w, str(DIP14)) is True
    assert calls == [("lib", DIP_LIB), ("file", DIP14)]


def test_open_in_window_document_attribute_and_method():
    """Нет open_path/open_file: файл открывается через ``document`` (атрибут или метод)."""
    doc = _Doc()

    class WithAttr:
        document = doc
    assert gui._open_in_window(WithAttr(), str(DIP14)) is True
    assert doc.opened == [DIP14]

    doc2 = _Doc(result=False)

    class WithMethod:
        def doc(self):
            return doc2
    assert gui._open_in_window(WithMethod(), str(DIP14)) is False
    assert doc2.opened == [DIP14]


def test_open_in_window_errors(capsys, tmp_path):
    class Empty:
        pass
    assert gui._open_in_window(Empty(), str(tmp_path / "нет.kicad_mod")) is False
    assert "файл или каталог не найден" in capsys.readouterr().err
    assert gui._open_in_window(Empty(), str(DIP_LIB)) is False
    assert "не умеет открывать каталоги" in capsys.readouterr().err
    assert gui._open_in_window(Empty(), str(DIP14)) is False
    assert "не умеет открывать файлы" in capsys.readouterr().err

    class Broken:
        def open_path(self, p):
            raise ValueError("строка 3, позиция 7: лишняя скобка")
    assert gui._open_in_window(Broken(), str(DIP14)) is False
    err = capsys.readouterr().err
    assert err.startswith("ошибка: ") and "строка 3, позиция 7: лишняя скобка" in err


def test_lazy_attribute_unknown():
    with pytest.raises(AttributeError, match="не содержит атрибута"):
        gui.NoSuchThing  # noqa: B018


def test_main_help_does_not_need_qt(capsys):
    assert gui.main(["--help"]) == 0
    assert capsys.readouterr().out.startswith("использование: kicadfp-gui")


def _fail_import(monkeypatch, predicate, exc):
    real = builtins.__import__

    def fake(name, globals=None, locals=None, fromlist=(), level=0):
        if predicate(name, globals, fromlist, level):
            raise exc
        return real(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, "__import__", fake)


def test_main_without_pyside6(monkeypatch, capsys):
    _fail_import(monkeypatch, lambda n, g, f, lv: n == "PySide6.QtWidgets",
                 ImportError("No module named 'PySide6'", name="PySide6"))
    assert gui.main([]) == 2
    err = capsys.readouterr().err
    assert "нужен PySide6" in err and gui.INSTALL_HINT in err


def _is_mainwindow(name, globals_, fromlist, level):
    return level == 1 and name == "mainwindow" and (globals_ or {}).get("__name__") == \
        "kicadfp.gui"


@pytest.mark.parametrize("missing, expected", [
    ("kicadfp.gui.mainwindow", "модуль kicadfp.gui.mainwindow"),
    ("PySide6.QtSvg", "не хватает модуля PySide6"),
    ("shiboken6.Shiboken", "не хватает модуля PySide6"),
    ("numpy", "не удалось загрузить главное окно: "),
])
def test_main_mainwindow_import_errors(monkeypatch, capsys, missing, expected):
    pytest.importorskip("PySide6")
    _fail_import(monkeypatch, _is_mainwindow,
                 ImportError(f"No module named {missing!r}", name=missing))
    assert gui.main([]) == 2
    assert expected in capsys.readouterr().err


def test_main_opens_paths_in_existing_app(monkeypatch, qtbot):
    """С уже созданным QApplication все аргументы — пути; окно показывается до открытия."""
    pytest.importorskip("pytestqt")
    from PySide6.QtWidgets import QApplication

    import kicadfp.gui.mainwindow as mw
    events = []

    class FakeWindow:
        def show(self):
            events.append("show")

        def open_path(self, p):
            events.append(p.name)
    monkeypatch.setattr(mw, "MainWindow", FakeWindow)
    monkeypatch.setattr(QApplication, "exec", staticmethod(lambda: 0))
    assert QApplication.instance() is not None
    monkeypatch.setattr(sys, "argv", ["kicadfp-gui"])
    assert gui.main([str(DIP14), DIP_LIB]) == 0
    assert events == ["show", DIP14.name, DIP_LIB.name]
