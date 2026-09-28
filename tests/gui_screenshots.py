"""Снимок главного окна для документации (скрипт, не тест pytest).

Открывает DIP-14 (формат KiCad 8, ``tests/fixtures/kicad8/Package_DIP.pretty``) в главном
окне :class:`kicadfp.gui.mainwindow.MainWindow`, выделяет площадку 1 и сохраняет снимок
окна (``QWidget.grab``) в ``docs/img/gui_main.png``. Работает без дисплея: платформа Qt
``offscreen`` задаётся автоматически, если не указана другая. Настройки пользователя не
читаются и не меняются (временный файл INI).

Запуск из корня репозитория::

    python tests/gui_screenshots.py [--out docs/img/gui_main.png] [--size 1440x900]
                                    [--theme light|dark]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIP14 = ROOT / "tests" / "fixtures" / "kicad8" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
DEFAULT_OUT = ROOT / "docs" / "img" / "gui_main.png"
DEFAULT_SIZE = (1440, 900)


def _process_events(app, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def take_main_window_screenshot(out: Path = DEFAULT_OUT, size: tuple[int, int] = DEFAULT_SIZE,
                                *, theme: str = "light") -> Path:
    """Открыть DIP-14 в главном окне размера ``size`` и записать снимок окна в ``out``
    (PNG); вернуть путь. Ошибки открытия и записи — исключения."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QPointF, QSettings
    from PySide6.QtTest import QTest

    from kicadfp.gui.app import create_app
    from kicadfp.gui.mainwindow import MainWindow

    app = create_app([sys.argv[0] if sys.argv and sys.argv[0] else "gui_screenshots"],
                     theme=theme)
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        settings = QSettings(str(Path(tmp) / "kicadfp.ini"), QSettings.Format.IniFormat)
        win = MainWindow(settings=settings, restore_settings=False)
        doc = win.document
        try:
            # вопросы и сообщения не должны блокировать скрипт
            win.show_error = lambda title, text: print(f"{title}: {text}", file=sys.stderr)
            win.resize(*size)
            win.show()
            _process_events(app)
            if not win.open_path(DIP14):
                raise RuntimeError(f"не удалось открыть {DIP14}")
            doc.select(doc.fp.pad("1"))
            _process_events(app)
            canvas = win.canvas
            canvas.fit()
            # курсор над корпусом: координаты в строке состояния
            QTest.mouseMove(canvas.viewport(), canvas.mapFromScene(QPointF(3.81, 7.62)))
            win.statusBar().clearMessage()
            _process_events(app)
            out.parent.mkdir(parents=True, exist_ok=True)
            if not win.grab().save(str(out), "PNG"):
                raise OSError(f"не удалось записать {out}")
        finally:
            doc.confirm_discard = True
            win.close()
            win.deleteLater()
            _process_events(app)
    return out


def _parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().replace("×", "x").split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"размер окна: ожидается ШxВ, а не {text!r}") from None
    if w < 200 or h < 200:
        raise argparse.ArgumentTypeError("размер окна: не меньше 200x200")
    return w, h


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа скрипта; возвращает код завершения."""
    parser = argparse.ArgumentParser(description="Снимок главного окна kicadfp для документации")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"файл PNG (по умолчанию {DEFAULT_OUT.relative_to(ROOT)})")
    parser.add_argument("--size", type=_parse_size, default=DEFAULT_SIZE,
                        help="размер окна ШxВ (по умолчанию 1440x900)")
    parser.add_argument("--theme", choices=("light", "dark"), default="light",
                        help="тема оформления (по умолчанию light)")
    ns = parser.parse_args(argv)
    path = take_main_window_screenshot(ns.out, ns.size, theme=ns.theme)
    print(f"записан: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
