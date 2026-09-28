"""Генераторы типовых посадочных мест (``architecture.md`` §11, ``docs/dev/lab-generators.md``).

Каждый генератор — функция с именованными параметрами (все со значениями по умолчанию),
возвращающая новый :class:`~kicadfp.model.Footprint` формата KiCad 9 (``version 20241229``,
``generator "kicadfp"``): Reference ``REF**`` на F.SilkS над корпусом, Value (имя) на F.Fab
под корпусом, контуры F.SilkS (0.12) и F.Fab (0.1), область размещения F.CrtYd (0.05,
отступ 0.25 / 0.5 у разъёмов, сетка 0.01), ``(attr through_hole)``, осмысленные
``descr``/``tags``, ``uuid`` у всех элементов (детерминированные ``uuid5``).

Семейства (геометрия библиотеки KiCad v8, KLC): :func:`dip`, :func:`pin_header`,
:func:`resistor`, :func:`capacitor_axial`, :func:`diode`, :func:`capacitor_radial`,
:func:`transistor` (TO-92, синоним :func:`transistor_inline`) — с ``${REFERENCE}`` на F.Fab.
Лабораторные корпуса (методичка, ТЗ прил. Г сценарий 5): :func:`lab_dip14`, :func:`lab_mlt`,
:func:`lab_snp8` — без ``${REFERENCE}`` (решение L9 lab-generators.md).

Для CLI и GUI:

* :data:`GENERATORS` — реестр ``{имя: функция}``; :data:`ALIASES` — синонимы имён;
* :func:`describe` — параметры генератора (имя, тип, умолчание, описание из docstring);
* :func:`from_json` — вызов генератора по имени со словарём параметров (или текстом JSON);
* :func:`coerce_param` — приведение значения параметра (в том числе строки из командной
  строки) к типу из сигнатуры.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from ..model import Footprint
from .axial import capacitor_axial, diode, resistor
from .dip import dip
from .lab import lab_dip14, lab_mlt, lab_snp8
from .pin_header import pin_header
from .radial import capacitor_radial
from .transistor import transistor, transistor_inline

__all__ = [
    "dip", "pin_header", "resistor", "capacitor_axial", "diode", "capacitor_radial",
    "transistor", "transistor_inline", "lab_dip14", "lab_mlt", "lab_snp8",
    "GENERATORS", "ALIASES", "ParamInfo", "describe", "summary", "get", "from_json",
    "coerce_param",
]

#: Реестр генераторов для CLI/GUI: имя → функция (architecture.md §11).
GENERATORS: dict[str, Callable[..., Footprint]] = {
    "dip": dip,
    "pin_header": pin_header,
    "resistor": resistor,
    "capacitor_radial": capacitor_radial,
    "capacitor_axial": capacitor_axial,
    "diode": diode,
    "transistor": transistor,
    "lab_dip14": lab_dip14,
    "lab_mlt": lab_mlt,
    "lab_snp8": lab_snp8,
}

#: Синонимы имён генераторов (принимаются :func:`get`, :func:`describe`, :func:`from_json`).
ALIASES: dict[str, str] = {
    "transistor_inline": "transistor",
    "to92": "transistor",
    "dip14": "lab_dip14",
    "mlt": "lab_mlt",
    "snp8": "lab_snp8",
}


class ParamInfo(NamedTuple):
    """Описание параметра генератора (:func:`describe`)."""

    #: Имя параметра (как в сигнатуре; в CLI — с ``-`` вместо ``_``).
    name: str
    #: Тип — аннотация из сигнатуры строкой (``"int"``, ``"float | tuple[float, float]"`` …).
    type: str
    #: Значение по умолчанию (``None`` — «вычисляется генератором»).
    default: Any
    #: Описание из раздела «Параметры:» docstring генератора.
    description: str


def get(kind: str) -> Callable[..., Footprint]:
    """Функция генератора по имени (или синониму, регистр и ``-`` не важны); ``KeyError`` с
    перечнем доступных имён, если такого нет."""
    key = str(kind).strip().lower().replace("-", "_")
    key = ALIASES.get(key, key)
    try:
        return GENERATORS[key]
    except KeyError:
        raise KeyError(f"неизвестный генератор {kind!r}; доступны: "
                       f"{', '.join(sorted(GENERATORS))}") from None


def _param_docs(func: Callable[..., Any]) -> dict[str, str]:
    """Описания параметров из раздела «Параметры:» docstring (строки ``имя: описание``,
    продолжение — с большим отступом)."""
    doc = inspect.getdoc(func) or ""
    out: dict[str, str] = {}
    lines = doc.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Параметры:")
    except StopIteration:
        return out
    base: int | None = None
    current: str | None = None
    for ln in lines[start + 1:]:
        if not ln.strip():
            if out:
                break
            continue
        indent = len(ln) - len(ln.lstrip())
        if base is None:
            base = indent
        if indent < base:
            break
        m = re.match(r"\s*(\w+):\s*(.*)$", ln)
        if indent == base and m:
            current = m.group(1)
            out[current] = m.group(2).strip()
        elif current is not None:
            out[current] = (out[current] + " " + ln.strip()).strip()
    return out


def describe(name: str) -> list[ParamInfo]:
    """Параметры генератора ``name`` в порядке сигнатуры: имя, тип (аннотация строкой),
    умолчание и описание из docstring (для CLI ``gen --list`` и диалога GUI)."""
    func = get(name)
    docs = _param_docs(func)
    out: list[ParamInfo] = []
    for p in inspect.signature(func).parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        if ann is inspect.Parameter.empty:
            ann_s = type(p.default).__name__ if p.default is not p.empty else "Any"
        else:
            ann_s = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
        default = None if p.default is inspect.Parameter.empty else p.default
        out.append(ParamInfo(p.name, ann_s, default, docs.get(p.name, "")))
    return out


def summary(name: str) -> str:
    """Первый абзац docstring генератора (краткое описание для списков CLI/GUI)."""
    doc = inspect.getdoc(get(name)) or ""
    return doc.split("\n\n", 1)[0].replace("\n", " ").strip()


# ---------------------------------------------------------------------------------------------
# Приведение значений параметров
# ---------------------------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on", "да", "y"}
_FALSE = {"0", "false", "no", "off", "нет", "n"}
_NONE = {"none", "null", ""}


def _to_float(value: Any, what: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{what}: ожидается число, получено {value!r}")
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: ожидается число, получено {value!r}") from None


def _to_int(value: Any, what: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{what}: ожидается целое число, получено {value!r}")
    if isinstance(value, int):
        return value
    f = _to_float(value, what)
    if not f.is_integer():
        raise ValueError(f"{what}: ожидается целое число, получено {value!r}")
    return int(f)


def _to_bool(value: Any, what: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    raise ValueError(f"{what}: ожидается логическое значение (true/false), получено {value!r}")


def _split_numbers(text: str) -> list[str]:
    """``"1.6,1.6"``, ``"1.6x1.6"``, ``"1.6 1.6"``, ``"[1.6, 1.6]"`` → список строк-чисел."""
    s = text.strip().strip("[]()")
    parts = re.split(r"[\s;x×*]+|,(?=\s*[-+.\d])", s) if s else []
    return [p for p in (x.strip() for x in parts) if p]


def coerce_param(kind: str, name: str, value: Any) -> Any:
    """Привести значение параметра ``name`` генератора ``kind`` к типу из сигнатуры.

    Принимаются значения из JSON (числа, списки, логические, ``null``) и строки командной
    строки: числа (десятичная запятая допустима), логические ``true/false/yes/no/1/0``,
    ``none``/``null``; пары — ``"1.6,1.6"``, ``"1.6x1.6"`` или JSON ``[1.6, 1.6]``; список
    монтажных отверстий — JSON ``[[x, y, d], …]``. Имя параметра — с ``_`` или ``-``.
    ``ValueError`` — для неизвестного параметра или неприводимого значения.
    """
    info = {p.name: p for p in describe(kind)}
    key = name.replace("-", "_")
    if key not in info:
        raise ValueError(f"генератор {kind!r} не имеет параметра {name!r}; параметры: "
                         f"{', '.join(info)}")
    ann = info[key].type.replace(" ", "")
    optional = "None" in ann.split("|")
    if value is None or (isinstance(value, str) and value.strip().lower() in _NONE):
        if optional:
            return None
        raise ValueError(f"{key}: значение обязательно")
    base = [a for a in ann.split("|") if a != "None"]
    if isinstance(value, str) and any(b.startswith(("list", "tuple")) for b in base):
        s = value.strip()
        if s.startswith("["):
            try:
                value = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"{key}: неверный JSON: {e}") from None
    if base == ["bool"]:
        return _to_bool(value, key)
    if base == ["int"]:
        return _to_int(value, key)
    if base == ["str"]:
        if not isinstance(value, str):
            raise ValueError(f"{key}: ожидается строка, получено {value!r}")
        return value
    if any(b.startswith("list[tuple") for b in base):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{key}: ожидается список троек [[x, y, d], …], получено {value!r}")
        out = []
        for item in value:
            if isinstance(item, str):
                item = _split_numbers(item)
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                raise ValueError(f"{key}: ожидается тройка (x, y, d), получено {item!r}")
            out.append(tuple(_to_float(v, key) for v in item))
        return out
    if "float" in base and any(b.startswith("tuple") for b in base):
        if isinstance(value, str):
            nums = _split_numbers(value)
            value = nums[0] if len(nums) == 1 else nums
        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                return _to_float(value[0], key)
            if len(value) != 2:
                raise ValueError(f"{key}: ожидается число или пара чисел, получено {value!r}")
            return (_to_float(value[0], key), _to_float(value[1], key))
        return _to_float(value, key)
    if base == ["float"]:
        return _to_float(value, key)
    return value


def from_json(kind: str, params: Mapping[str, Any] | str | None = None) -> Footprint:
    """Создать корпус генератором ``kind`` с параметрами ``params`` — словарём (например,
    из JSON-файла CLI ``--params``) или текстом JSON-объекта. Значения приводятся
    :func:`coerce_param` (списки → кортежи, строки → числа …); ключи — с ``_`` или ``-``.
    ``KeyError`` — неизвестный генератор; ``ValueError`` — неизвестный параметр или
    неверное значение."""
    func = get(kind)
    if params is None:
        data: Mapping[str, Any] = {}
    elif isinstance(params, str):
        try:
            data = json.loads(params) if params.strip() else {}
        except json.JSONDecodeError as e:
            raise ValueError(f"неверный JSON параметров: {e}") from None
    else:
        data = params
    if not isinstance(data, Mapping):
        raise ValueError("параметры генератора: ожидается объект JSON {имя: значение}")
    kwargs = {str(k).replace("-", "_"): coerce_param(kind, str(k), v) for k, v in data.items()}
    return func(**kwargs)
