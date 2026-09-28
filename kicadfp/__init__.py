"""kicadfp — библиотека и редактор файлов посадочных мест KiCad (``.kicad_mod``, ``.pretty``).

Публичный API (architecture.md §1, ТЗ 4.1.6):

* чтение/запись: :func:`load`, :func:`loads`, :func:`save`, :func:`dumps`,
  :class:`ValidationError`, :class:`SexprSyntaxError`;
* модель: :class:`Footprint`, :class:`Pad`, :class:`Drill`, графика (:class:`Graphic` и
  :class:`Line`, :class:`Rect`, :class:`Circle`, :class:`Arc`, :class:`Poly`,
  :class:`Curve`), :class:`Text`, :class:`Model`, :class:`BBox`;
* библиотека ``.pretty``: :class:`Library`;
* проверка: :func:`validate` (функция), :class:`Issue`;
* модули: :mod:`kicadfp.generators` (типовые корпуса), :mod:`kicadfp.legacy` (старый формат
  ``.mod``), :mod:`kicadfp.render` (SVG/PNG);
* :data:`__version__`.

Пакет импортируется без сторонних зависимостей: PySide6 нужен только графическому
интерфейсу (:mod:`kicadfp.gui`) и экспорту PNG (:func:`kicadfp.render.save_png`) и
загружается ими при вызове. Интерфейс командной строки — :mod:`kicadfp.cli`
(``kicadfp …`` или ``python -m kicadfp …``); он не импортируется вместе с пакетом.

Имя ``kicadfp.validate`` — функция проверки, а не подмодуль: модуль проверок доступен как
``sys.modules["kicadfp.validate"]`` или через ``from kicadfp.validate import Issue, RULES``
(``import kicadfp.validate as m`` дал бы функцию — атрибут пакета).
"""

from __future__ import annotations

from typing import Any

from . import generators, legacy, render
from ._version import __version__
from .geometry import BBox
from .io import ValidationError, dumps, load, loads, save
from .library import Library
from .model import (
    Arc,
    Circle,
    Curve,
    Drill,
    Footprint,
    Graphic,
    Line,
    Model,
    Pad,
    Poly,
    Rect,
    Text,
)
from .sexpr import SexprSyntaxError
from .validate import Issue

# Импорт подмодуля kicadfp.validate (строкой выше) записал в пакет атрибут validate = модуль;
# функция с тем же именем должна перезаписать его — это следующая строка.
from .validate import validate  # noqa: E402  (порядок важен)

__all__ = [
    "load", "loads", "save", "dumps", "Footprint", "Pad", "Drill", "Graphic", "Line", "Rect",
    "Circle", "Arc", "Poly", "Curve", "Text", "Model", "BBox", "Library", "Issue", "validate",
    "SexprSyntaxError", "ValidationError", "generators", "legacy", "render", "__version__",
]


def __getattr__(name: str) -> Any:
    """Сообщение по-русски для отсутствующих имён пакета."""
    raise AttributeError(f"модуль 'kicadfp' не содержит атрибута {name!r}")
