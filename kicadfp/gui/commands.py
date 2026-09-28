"""Команды отмены/повтора (``QUndoCommand``) для изменения модели в графическом интерфейсе.

Все изменения модели в GUI выполняются только командами через
:meth:`FootprintDocument.apply() <kicadfp.gui.document.FootprintDocument.apply>`::

    doc.apply(SetAttrCommand(doc, pad, "x", 2.54))                    # одно свойство
    doc.apply(SetAttrsCommand(doc, pad, {"x": 1.0, "y": 2.0}))        # несколько свойств
    doc.apply(AddItemCommand(doc, Pad.new("15", "smd", "rect", 0, 0, (1, 2))))
    doc.apply(RemoveItemCommand(doc, fp.pads[3]))
    doc.apply(OperationCommand(doc, lambda fp: fp.rotate(90), "поворот корпуса"))
    doc.apply(OperationCommand(doc, lambda g: g.move(1, 0), item=line))  # один элемент
    doc.apply(ReplaceNodeCommand(doc, before_copy, after_copy, "перенумерация"))
    doc.apply(BatchCommand([cmd1, cmd2, cmd3], "групповая операция"))

Точная отмена
-------------
Команда при первом выполнении снимает состояние дерева корпуса (для каждого узла — имя,
позиция в исходнике, список элементов с *идентичностью* подузлов, комментарии), выполняет
операцию над «живой» моделью — setter представления, :meth:`Footprint.add
<kicadfp.model.Footprint.add>`, ``move``/``rotate``/``flip``/``renumber_pads`` … — и снимает
состояние ещё раз. Хранятся только различающиеся узлы (обычно один-два), поэтому шаг
отмены занимает мало памяти. Отмена восстанавливает узлы из первого снимка, повтор — из
второго, поэтому:

* текст файла после отмены совпадает с исходным **байт в байт** — даже там, где обратное
  присваивание через setter записало бы число иначе (``-180.000000`` → ``-180``) или
  где операция переставила узлы (скрытие ``fp_text`` в KiCad 8+ превращает его в поле
  ``property`` и переносит за последнее поле);
* идентичность узлов (объектов :class:`~kicadfp.sexpr.Node`) сохраняется: представления
  (``Pad``, ``Line``, …), которые держат таблицы, канва и выделение, остаются
  действительными после отмены и повтора, а команды, записанные в стек позже, находят
  свои узлы.

Область снимка зависит от команды: изменение элемента (свойства представления,
добавление, удаление, операция над одним элементом) снимает только сам элемент с
поддеревом и списки элементов корня и родителя — по контракту модели setter меняет только
свой узел (architecture.md §6), а переставить может лишь его место в родителе; операции
над всем корпусом, замена корня и группы команд снимают всё дерево. Поэтому правка ячейки
таблицы не зависит от размера корпуса.

Команды, выполненные через :meth:`FootprintDocument.apply`, при ошибке (``ValueError`` от
setter'а и т. п.) возвращают модель в исходное состояние, в стек не попадают, а исключение
получает вызывающий. Команда, ничего не изменившая в модели, в стек не кладётся.
После каждого ``redo()``/``undo()`` команда вызывает ``doc._emit_changed()`` — документ
испускает ``changed()``.

Слияние (перетаскивание)
------------------------
:class:`SetAttrCommand`/:class:`SetAttrsCommand` с одинаковым ``merge_id`` над тем же
представлением (тот же узел) и тем же набором свойств сливаются в один шаг отмены: хранится
первое старое значение и последнее новое. ``merge_id`` — целое число или любое хешируемое
значение (например, строка ``"drag"``); для отдельной «сессии» перетаскивания удобно брать
новый номер :func:`next_merge_id`. Если после слияния модель вернулась к исходному
состоянию, шаг удаляется из стека. ``QUndoStack`` не сливает команду с командой, после
которой документ был сохранён.

Классы
------
* :class:`DocumentCommand` — базовый класс (снимки, ``redo``/``undo``); наследники
  определяют :meth:`DocumentCommand._perform` (и при необходимости ``_prepare``);
* :class:`SetAttrCommand`, :class:`SetAttrsCommand` — присваивание свойств представления;
* :class:`AddItemCommand`, :class:`RemoveItemCommand` — добавление/удаление элемента с
  восстановлением точной позиции в файле;
* :class:`ReplaceNodeCommand` — применение готового состояния (копии узла) к корню или
  элементу с сохранением идентичности корневого узла и, где возможно, подузлов;
* :class:`OperationCommand` — выполнение произвольной операции модели одним шагом;
* :class:`BatchCommand` — несколько команд одним шагом отмены.
"""

from __future__ import annotations

import difflib
import itertools
import types
from collections.abc import Callable, Hashable, Iterable, Mapping
from contextlib import nullcontext
from typing import Any

from PySide6.QtGui import QUndoCommand

from ..model import (Arc, Circle, Curve, Drill, Footprint, Graphic, Line, Model, Pad, Poly,
                     Rect, Text, View, view_for)
from ..sexpr import Node

__all__ = [
    "DocumentCommand", "SetAttrCommand", "SetAttrsCommand", "AddItemCommand",
    "RemoveItemCommand", "ReplaceNodeCommand", "OperationCommand", "BatchCommand",
    "next_merge_id", "describe_item",
]

_ROOT_NAMES = ("footprint", "module")
_ID_TOKENS = ("uuid", "tstamp", "id")


# ---------------------------------------------------------------------------------------------
# Снимки состояния дерева
# ---------------------------------------------------------------------------------------------
#
# Состояние узла — кортеж (узел, имя, строка, позиция, элементы, комментарии), где элементы —
# кортеж атомов (неизменяемые строки Sym/Str) и самих объектов-подузлов. Восстановление
# состояния присваивает узлу эти поля; подузлы восстанавливаются своими состояниями.

_State = tuple  # (Node, str, int, int, tuple, tuple)


def _node_state(node: Node) -> _State:
    return (node, node.name, node.line, node.col, tuple(node.items),
            tuple(getattr(node, "comments", ()) or ()))


def _capture(root: Node) -> dict[int, _State]:
    """Состояния всех узлов дерева ``root`` (включая корень): ``{id(узел): состояние}``."""
    states: dict[int, _State] = {}
    stack = [root]
    while stack:
        n = stack.pop()
        key = id(n)
        if key in states:
            continue
        states[key] = _node_state(n)
        stack.extend(x for x in n.items if isinstance(x, Node))
    return states


def _capture_scope(scope: Iterable[tuple[Node, bool]]) -> dict[int, _State]:
    """Состояния узлов области снимка: ``(узел, True)`` — узел со всем поддеревом,
    ``(узел, False)`` — только сам узел (его имя и список элементов)."""
    states: dict[int, _State] = {}
    for node, deep in scope:
        if deep:
            for k, st in _capture(node).items():
                states.setdefault(k, st)
        else:
            states.setdefault(id(node), _node_state(node))
    return states


def _same_items(a: tuple, b: tuple) -> bool:
    """Совпадают ли списки элементов: подузлы — по идентичности, атомы — по типу и тексту
    (``Sym("1")`` и ``Str("1")`` различаются: кавычки — часть формата)."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        if x is y:
            continue
        if isinstance(x, Node) or isinstance(y, Node) or type(x) is not type(y) or x != y:
            return False
    return True


def _same_state(a: _State, b: _State) -> bool:
    return (a[1] == b[1] and a[2] == b[2] and a[3] == b[3] and a[5] == b[5]
            and _same_items(a[4], b[4]))


def _diff(before: dict[int, _State],
          after: dict[int, _State]) -> tuple[dict[int, _State], dict[int, _State]]:
    """Состояния для отмены (узлы, изменённые или исключённые из дерева) и для повтора
    (узлы, изменённые или появившиеся)."""
    undo = {k: s for k, s in before.items() if k not in after or not _same_state(s, after[k])}
    redo = {k: s for k, s in after.items() if k not in before or not _same_state(s, before[k])}
    return undo, redo


def _restore(states: Iterable[_State]) -> None:
    """Вернуть узлам записанные состояния (порядок не важен: каждое задаёт только свой узел)."""
    for node, name, line, col, items, comments in states:
        node.name = name
        node.line = line
        node.col = col
        node.items = list(items)
        node.comments = list(comments)


def _net_noop(undo: dict[int, _State], redo: dict[int, _State]) -> bool:
    """Нет ли суммарного изменения: каждый узел исходного дерева, менявшийся по ходу, имеет
    в конце то же состояние, что и в начале (узлы, которые есть только в ``redo``, созданы
    по ходу и в итоговое дерево не входят)."""
    for k, s in undo.items():
        r = redo.get(k)
        if r is None or not _same_state(s, r):
            return False
    return True


# ---------------------------------------------------------------------------------------------
# Поиск и синхронизация узлов
# ---------------------------------------------------------------------------------------------

def _in_tree(root: Node, node: Node) -> bool:
    """Входит ли ``node`` (по идентичности) в дерево ``root`` (сам корень — входит)."""
    if node is root:
        return True
    stack = [root]
    while stack:
        n = stack.pop()
        for x in n.items:
            if isinstance(x, Node):
                if x is node:
                    return True
                stack.append(x)
    return False


def _find_parent(root: Node, node: Node) -> Node | None:
    """Узел, в ``items`` которого непосредственно стоит ``node`` (``None`` — не найден)."""
    stack = [root]
    while stack:
        n = stack.pop()
        for x in n.items:
            if isinstance(x, Node):
                if x is node:
                    return n
                stack.append(x)
    return None


def _ident(node: Node) -> str | None:
    """Идентификатор элемента (``uuid``/``tstamp``/``id``) для сопоставления узлов."""
    for x in node.items:
        if isinstance(x, Node) and x.name in _ID_TOKENS:
            a = x.atom(0)
            return None if a is None else str(a)
    return None


def _match_children(old: list[Node], new: list[Node]) -> list[Node | None]:
    """Сопоставить подузлы ``new`` (снимок) подузлам ``old`` (живое дерево): для каждого
    узла снимка — узел, который следует переиспользовать (``None`` — создать копию).

    Одинаковая последовательность имён — сопоставление по позиции (``move``/``rotate``/
    ``flip``/``renumber_pads`` структуру не меняют); иначе — выравнивание по (имя,
    идентификатор) как в ``diff``: общие начало и конец, затем ``difflib.SequenceMatcher``;
    в заменённых участках переиспользуются узлы с тем же именем в той же позиции.
    """
    n_old, n_new = len(old), len(new)
    if n_old == n_new and all(a.name == b.name for a, b in zip(old, new, strict=True)):
        return list(old)
    ko = [(n.name, _ident(n)) for n in old]
    kn = [(n.name, _ident(n)) for n in new]
    result: list[Node | None] = [None] * n_new
    p = 0
    while p < n_old and p < n_new and ko[p] == kn[p]:
        result[p] = old[p]
        p += 1
    s = 0
    while s < n_old - p and s < n_new - p and ko[n_old - 1 - s] == kn[n_new - 1 - s]:
        result[n_new - 1 - s] = old[n_old - 1 - s]
        s += 1
    mo, mn = ko[p:n_old - s], kn[p:n_new - s]
    if mo and mn:
        sm = difflib.SequenceMatcher(None, mo, mn, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    result[p + j1 + k] = old[p + i1 + k]
            elif tag == "replace":
                for k in range(min(i2 - i1, j2 - j1)):
                    if old[p + i1 + k].name == new[p + j1 + k].name:
                        result[p + j1 + k] = old[p + i1 + k]
    return result


def _sync(dst: Node, src: Node) -> None:
    """Сделать содержимое живого узла ``dst`` равным снимку ``src``, сохраняя идентичность
    ``dst`` и, где возможно, его подузлов (см. :func:`_match_children`). Узлы снимка в
    дерево не попадают: новые подузлы — копии; ``line``/``col`` переиспользованных узлов не
    меняются."""
    dst.name = src.name
    dst.comments = list(getattr(src, "comments", ()) or ())
    src_nodes = [x for x in src.items if isinstance(x, Node)]
    reuse = iter(_match_children([x for x in dst.items if isinstance(x, Node)], src_nodes))
    items: list[Any] = []
    for x in src.items:
        if isinstance(x, Node):
            r = next(reuse)
            if r is None:
                items.append(x.copy())
            else:
                _sync(r, x)
                items.append(r)
        else:
            items.append(x)
    dst.items = items


# ---------------------------------------------------------------------------------------------
# Тексты команд
# ---------------------------------------------------------------------------------------------

# Родительный падеж названий свойств: «изменение <свойства> <элемента>».
_ATTR_GENITIVE: dict[str, str] = {
    "x": "X", "y": "Y", "position": "положения", "at": "положения", "angle": "поворота",
    "number": "номера", "type": "типа", "shape": "формы", "size": "размера",
    "size_x": "размера X", "size_y": "размера Y", "drill": "отверстия", "layers": "слоёв",
    "layer": "слоя", "width": "ширины", "stroke_type": "типа линии", "fill": "заливки",
    "text": "текста", "hide": "видимости", "font_size": "размера шрифта",
    "font_size_x": "ширины шрифта", "font_size_y": "высоты шрифта", "thickness": "толщины",
    "bold": "полужирности", "italic": "курсива", "justify": "выравнивания",
    "mirror": "зеркальности", "knockout": "инверсии", "unlocked": "привязки поворота",
    "face": "шрифта", "locked": "блокировки", "start": "начала", "end": "конца",
    "mid": "середины", "center": "центра", "radius": "радиуса", "points": "точек",
    "start_x": "начала X", "start_y": "начала Y", "end_x": "конца X", "end_y": "конца Y",
    "name": "имени", "descr": "описания", "tags": "ключевых слов", "attrs": "атрибутов",
    "clearance": "зазора", "solder_mask_margin": "зазора маски",
    "solder_paste_margin": "зазора пасты", "solder_paste_ratio": "коэффициента пасты",
    "zone_connect": "подключения к зонам", "reference": "позиционного обозначения",
    "value": "номинала", "path": "пути", "offset": "смещения", "scale": "масштаба",
    "rotate": "поворота", "opacity": "прозрачности", "diameter": "диаметра",
    "oval": "формы отверстия", "offset_x": "смещения X", "offset_y": "смещения Y",
    "roundrect_rratio": "скругления", "chamfer_ratio": "размера фаски", "chamfer": "фасок",
    "rect_delta": "скоса трапеции", "net": "цепи", "pinfunction": "функции вывода",
    "pintype": "типа вывода", "die_length": "длины вывода в корпусе",
    "thermal_bridge_width": "ширины термомоста", "thermal_bridge_angle": "угла термомоста",
    "thermal_gap": "зазора термомоста", "remove_unused_layers": "удаления неиспользуемых слоёв",
    "keep_end_layers": "сохранения крайних слоёв", "kind": "вида", "version": "версии формата",
    "generator": "генератора", "generator_version": "версии генератора", "uuid": "UUID",
    "private_layers": "собственных слоёв", "net_tie_pad_groups": "групп соединённых площадок",
    "placed": "признака размещения", "tedit": "метки времени", "anchor": "якоря",
    "property": "свойства площадки", "final_newline": "перевода строки в конце файла",
}

# Наборы свойств, присваивание которых — перемещение элемента.
_MOVE_SETS = (frozenset(("x", "y")), frozenset(("position",)), frozenset(("at",)))

# Родительный падеж названий элементов (подклассы раньше базовых).
_ITEM_GENITIVE: tuple[tuple[type, str], ...] = (
    (Footprint, "корпуса"), (Pad, "площадки"), (Drill, "отверстия"), (Line, "линии"),
    (Rect, "прямоугольника"), (Circle, "окружности"), (Arc, "дуги"),
    (Poly, "многоугольника"), (Curve, "кривой Безье"), (Graphic, "фигуры"),
    (Text, "текста"), (Model, "3D-модели"),
)
_NODE_GENITIVE = {"zone": "зоны", "group": "группы", "fp_text_box": "текстового блока",
                  "dimension": "размерной линии", "image": "изображения"}


def _short(s: str, n: int = 24) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def describe_item(item: Any) -> str:
    """Название элемента модели в родительном падеже для текстов команд: «площадки 1»,
    «линии», «текста «REF**»», «корпуса» …"""
    try:
        if isinstance(item, Pad):
            num = item.number
            return f"площадки {num}" if num else "площадки без номера"
        if isinstance(item, Text):
            return f"текста «{_short(item.text)}»"
        if isinstance(item, Footprint):
            return f"корпуса {item.name}"
        for cls, word in _ITEM_GENITIVE:
            if isinstance(item, cls):
                return word
        if isinstance(item, Node):
            return _NODE_GENITIVE.get(item.name, f"элемента {item.name}")
    except Exception:  # noqa: BLE001 — узел необычной формы: общее название
        pass
    return "элемента"


def _attrs_text(view: Any, attrs: list[str]) -> str:
    what = describe_item(view)
    if frozenset(attrs) in _MOVE_SETS:
        return f"перемещение {what}"
    names = [_ATTR_GENITIVE.get(a, f"«{a}»") for a in attrs]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " и " + names[-1]
    return f"изменение {joined} {what}"


def _action_form(text: str) -> str:
    """Текст для пунктов «Отменить …»/«Повторить …»: первая буква строчная (кроме
    аббревиатур)."""
    if len(text) >= 2 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _view_form(text: str) -> str:
    """Текст для списка истории (QUndoView): с прописной буквы."""
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------------------------
# Идентификаторы слияния
# ---------------------------------------------------------------------------------------------

_INT32_MAX = 2**31 - 1
_merge_counter = itertools.count(1 << 24)
_merge_registry: dict[Hashable, int] = {}


def next_merge_id() -> int:
    """Новый уникальный ``merge_id`` (например, на каждую «сессию» перетаскивания, чтобы
    два отдельных перетаскивания одного элемента не слились в один шаг отмены)."""
    return next(_merge_counter)


def _merge_int(merge_id: Hashable | None) -> int:
    """``QUndoCommand.id()`` для ``merge_id``: ``None`` → -1 (без слияния); целое 0…2³¹−1 —
    как есть; прочее хешируемое — постоянный номер из реестра."""
    if merge_id is None:
        return -1
    if isinstance(merge_id, int) and not isinstance(merge_id, bool):
        if merge_id == -1:
            return -1
        if 0 <= merge_id <= _INT32_MAX:
            return merge_id
    try:
        return _merge_registry[merge_id]
    except KeyError:
        value = next(_merge_counter)
        _merge_registry[merge_id] = value
        return value
    except TypeError:
        raise TypeError(f"merge_id должен быть хешируемым, а не {type(merge_id).__name__}") \
            from None


# ---------------------------------------------------------------------------------------------
# Базовая команда
# ---------------------------------------------------------------------------------------------

def _node_of(item: Any) -> Node:
    if isinstance(item, View):
        return item.node
    if isinstance(item, Node):
        return item
    raise TypeError(f"ожидается элемент модели (представление или Node), "
                    f"а не {type(item).__name__}")


class DocumentCommand(QUndoCommand):
    """Базовая команда над моделью :class:`~kicadfp.gui.document.FootprintDocument`.

    Наследник реализует :meth:`_perform` — изменение «живой» модели (``self._fp`` —
    открытый корпус). Первое выполнение (:meth:`execute`; его делает
    :meth:`FootprintDocument.apply`) снимает состояние дерева до и после операции и
    запоминает различия; ``undo()``/``redo()`` восстанавливают снимки (см. модуль).
    :meth:`_prepare` вызывается перед первым снимком (например,
    :class:`ReplaceNodeCommand` приводит дерево к состоянию «до»).

    ``text`` — описание для истории и пунктов меню: в ``QUndoView`` показывается с
    прописной буквы, в «Отменить …»/«Повторить …» — со строчной.
    """

    def __init__(self, doc: Any, text: str | None = None) -> None:
        super().__init__()
        if doc is None or not hasattr(doc, "_emit_changed"):
            raise TypeError("команде нужен документ FootprintDocument")
        self._doc = doc
        self._fp: Footprint | None = None
        self._executed = False
        self._in_batch = False
        self._skip_redo = False
        self._undo_states: dict[int, _State] = {}
        self._redo_states: dict[int, _State] = {}
        self._nl: tuple[bool, bool] | None = None
        self.set_description(text or "изменение корпуса")

    # --- описание ---------------------------------------------------------------------------
    def set_description(self, text: str) -> None:
        """Задать описание команды (см. класс)."""
        text = str(text).strip() or "изменение корпуса"
        self.setText(f"{_view_form(text)}\n{_action_form(text)}")

    @property
    def document(self) -> Any:
        """Документ, для которого создана команда."""
        return self._doc

    @property
    def executed(self) -> bool:
        """Выполнена ли команда (первое выполнение уже было)."""
        return self._executed

    @property
    def has_changes(self) -> bool:
        """Изменила ли команда модель (после :meth:`execute`)."""
        return bool(self._undo_states or self._redo_states) or (
            self._nl is not None and self._nl[0] != self._nl[1])

    # --- переопределяемое ---------------------------------------------------------------------
    def _prepare(self) -> None:
        """Подготовка перед снимком «до»: привязка элементов, проверки (по умолчанию ничего)."""

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        """Область снимка (см. :func:`_capture_scope`): по умолчанию — всё дерево корпуса.
        Всё, что меняет :meth:`_perform`, должно входить в область."""
        return [(fp.node, True)]

    def _perform(self) -> None:
        """Изменить модель (выполняется один раз; повтор — по снимку)."""
        raise NotImplementedError

    # --- выполнение ---------------------------------------------------------------------------
    def _begin(self) -> Footprint:
        if self._executed or self._in_batch:
            raise RuntimeError(f"команда «{self.actionText()}» уже выполнена")
        fp = self._doc.fp
        if fp is None:
            raise RuntimeError("в документе нет открытого корпуса")
        self._fp = fp
        return fp

    def execute(self) -> bool:
        """Первое выполнение: снимок, операция, снимок. Возвращает, изменилась ли модель.

        При исключении в операции модель возвращается в состояние до неё, исключение
        передаётся вызывающему, команда остаётся невыполненной. Обычно вызывается из
        :meth:`FootprintDocument.apply`, а не напрямую."""
        fp = self._begin()
        suspend = getattr(self._doc, "_suspend_changed", None)
        with suspend() if suspend is not None else nullcontext():
            self._prepare()
            scope = self._scope_nodes(fp)
            before = _capture_scope(scope)
            nl_before = fp.final_newline
            try:
                self._perform()
            except BaseException:
                _restore(before.values())
                fp.final_newline = nl_before
                raise
            after = _capture_scope(scope)
        self._undo_states, self._redo_states = _diff(before, after)
        self._nl = (nl_before, fp.final_newline)
        self._executed = True
        return self.has_changes

    def _execute_in_batch(self, fp: Footprint) -> None:
        """Выполнить операцию внутри :class:`BatchCommand` (снимки делает группа)."""
        if self._executed or self._in_batch:
            raise RuntimeError(f"команда «{self.actionText()}» уже выполнена")
        self._fp = fp
        self._prepare()
        self._perform()
        self._in_batch = True

    def _scope(self) -> Any:
        scope = getattr(self._doc, "_command_scope", None)
        return scope() if scope is not None else nullcontext()

    def redo(self) -> None:  # noqa: D401 — переопределение Qt
        """Выполнить (первый раз — операцию, далее — восстановить снимок «после»)."""
        with self._scope():
            if self._skip_redo:
                self._skip_redo = False  # уже выполнена в FootprintDocument.apply()
            elif not self._executed:
                if self._in_batch:
                    return
                self.execute()
            else:
                _restore(self._redo_states.values())
                if self._fp is not None and self._nl is not None:
                    self._fp.final_newline = self._nl[1]
            self._doc._emit_changed()

    def undo(self) -> None:  # noqa: D401 — переопределение Qt
        """Отменить: восстановить снимок «до»."""
        if not self._executed:
            return
        with self._scope():
            _restore(self._undo_states.values())
            if self._fp is not None and self._nl is not None:
                self._fp.final_newline = self._nl[0]
            self._doc._emit_changed()

    def _merge_states(self, other: DocumentCommand) -> None:
        """Присоединить результат ``other`` (выполненной после этой команды) к этой."""
        redo = dict(self._redo_states)
        redo.update(other._redo_states)
        undo = dict(other._undo_states)
        undo.update(self._undo_states)
        self._redo_states, self._undo_states = redo, undo
        if self._nl is not None and other._nl is not None:
            self._nl = (self._nl[0], other._nl[1])
        if _net_noop(undo, redo) and (self._nl is None or self._nl[0] == self._nl[1]):
            self.setObsolete(True)  # вернулись к исходному состоянию — шаг не нужен


# ---------------------------------------------------------------------------------------------
# Свойства представления
# ---------------------------------------------------------------------------------------------

def _element_scope(fp: Footprint, node: Node) -> list[tuple[Node, bool]]:
    """Область снимка изменения одного элемента: списки элементов корня и родителя и
    поддерево элемента (корень — всё дерево)."""
    if node is fp.node:
        return [(fp.node, True)]
    scope = [(fp.node, False)]
    parent = _find_parent(fp.node, node)
    if parent is not None and parent is not fp.node:
        scope.append((parent, False))
    scope.append((node, True))
    return scope


def _check_attr(view: Any, attr: Any) -> str:
    """Проверить, что ``attr`` — записываемое свойство класса представления."""
    if not isinstance(attr, str) or not attr.isidentifier():
        raise ValueError(f"недопустимое имя свойства {attr!r}")
    if attr.startswith("_") or attr == "node":
        raise ValueError(f"свойство {attr!r} нельзя менять командой")
    desc = getattr(type(view), attr, None)
    if isinstance(desc, property):
        if desc.fset is None:
            raise AttributeError(f"свойство {type(view).__name__}.{attr} только для чтения")
        return attr
    if isinstance(desc, types.MemberDescriptorType):
        return attr
    raise AttributeError(f"у {type(view).__name__} нет записываемого свойства {attr!r}")


def _safe_get(view: Any, attr: str) -> Any:
    try:
        return getattr(view, attr)
    except Exception:  # noqa: BLE001 — старое значение нужно только для сведения
        return None


class SetAttrsCommand(DocumentCommand):
    """Присвоить несколько свойств одного представления одним шагом (например, ``x`` и ``y``
    площадки при перетаскивании): ``SetAttrsCommand(doc, pad, {"x": 1.0, "y": 2.0})``.

    Свойства присваиваются в порядке ``values`` через setters модели (все проверки значений
    — модели: недопустимое значение даёт ``ValueError`` из :meth:`FootprintDocument.apply`,
    модель не меняется). ``view`` — представление элемента открытого корпуса (или сам
    корпус); представление без родителя привязывается к корпусу документа (его профиль).
    ``merge_id`` — см. модуль; сливаются команды над тем же узлом с тем же набором
    свойств. После выполнения: :attr:`old_values` — значения до первого выполнения,
    :attr:`values` — присвоенные (последние при слиянии).
    """

    def __init__(self, doc: Any, view: View, values: Mapping[str, Any] | Iterable[tuple[str, Any]],
                 text: str | None = None, merge_id: Hashable | None = None) -> None:
        if not isinstance(view, View):
            raise TypeError(f"ожидается представление модели, а не {type(view).__name__}")
        vals = dict(values)
        if not vals:
            raise ValueError("не заданы свойства")
        for a in vals:
            _check_attr(view, a)
        super().__init__(doc, text or _attrs_text(view, list(vals)))
        self._view = view
        self._values = vals
        self._merge = _merge_int(merge_id)
        self.old_values: dict[str, Any] = {}

    @property
    def view(self) -> View:
        """Представление, над которым работает команда (после выполнения — привязанное к
        корпусу документа)."""
        return self._view

    @property
    def values(self) -> dict[str, Any]:
        """Присваиваемые значения ``{свойство: значение}``."""
        return dict(self._values)

    def id(self) -> int:  # noqa: A003 — переопределение Qt
        return self._merge

    def _prepare(self) -> None:
        view = self._doc.bind(self._view)
        if not isinstance(view, View):
            raise ValueError("элемент не является представлением модели")
        for a in self._values:
            _check_attr(view, a)
        self._view = view

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        return _element_scope(fp, self._view.node)

    def _perform(self) -> None:
        view = self._view
        self.old_values = {a: _safe_get(view, a) for a in self._values}
        for a, v in self._values.items():
            setattr(view, a, v)

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 — переопределение Qt
        """Слить с последующей командой (см. модуль)."""
        if (self._merge == -1 or not isinstance(other, SetAttrsCommand)
                or other._merge != self._merge or not self._executed or not other._executed
                or other._fp is not self._fp or other._view.node is not self._view.node
                or type(other._view) is not type(self._view)
                or set(other._values) != set(self._values)):
            return False
        self._values = dict(other._values)
        self._merge_states(other)
        return True


class SetAttrCommand(SetAttrsCommand):
    """Присвоить одно свойство представления: ``SetAttrCommand(doc, pad, "x", 2.54)``.

    ``text`` — описание (по умолчанию «изменение X площадки 1»); ``merge_id`` — слияние
    последовательных изменений того же свойства того же элемента в один шаг (хранится
    первое старое значение). :attr:`attr`, :attr:`new_value`, :attr:`old_value` — для
    сведения."""

    def __init__(self, doc: Any, view: View, attr: str, new_value: Any, text: str | None = None,
                 merge_id: Hashable | None = None) -> None:
        super().__init__(doc, view, {attr: new_value}, text, merge_id)
        self._attr = attr

    @property
    def attr(self) -> str:
        """Имя свойства."""
        return self._attr

    @property
    def new_value(self) -> Any:
        """Присваиваемое (при слиянии — последнее) значение."""
        return self._values[self._attr]

    @property
    def old_value(self) -> Any:
        """Значение до первого выполнения (``None`` до выполнения)."""
        return self.old_values.get(self._attr)


# ---------------------------------------------------------------------------------------------
# Добавление и удаление
# ---------------------------------------------------------------------------------------------

class AddItemCommand(DocumentCommand):
    """Добавить элемент в корпус: ``AddItemCommand(doc, Pad.new(...))`` или узел ``Node``.

    Элемент вставляется :meth:`Footprint.add <kicadfp.model.Footprint.add>` — в конец своей
    группы, с приведением к профилю корпуса и заменой совпадающего ``uuid``; отмена убирает
    его, повтор возвращает тот же узел на то же место. :attr:`item` — добавленный элемент
    (представление, привязанное к корпусу, или узел без представления)."""

    def __init__(self, doc: Any, item: View | Node, text: str | None = None) -> None:
        _node_of(item)
        if isinstance(item, Footprint):
            raise TypeError("корпус нельзя добавить в корпус")
        super().__init__(doc, text or f"добавление {describe_item(item)}")
        self._item: Any = item

    @property
    def item(self) -> Any:
        """Добавляемый (после выполнения — добавленный) элемент."""
        return self._item

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        return [(fp.node, False), (_node_of(self._item), True)]

    def _perform(self) -> None:
        fp = self._fp
        assert fp is not None
        added = fp.add(self._item)
        if isinstance(added, Node):
            try:
                added = view_for(added, None, fp)
            except ValueError:
                pass
        self._item = added


class RemoveItemCommand(DocumentCommand):
    """Удалить элемент (представление или узел) из корпуса; отмена возвращает тот же узел
    точно на прежнее место в файле. Удаляется узел на любой глубине (например, примитив
    площадки), кроме самого корпуса. :attr:`item` — удаляемый элемент."""

    def __init__(self, doc: Any, item: View | Node, text: str | None = None) -> None:
        _node_of(item)
        if isinstance(item, Footprint) or (isinstance(item, Node) and item.name in _ROOT_NAMES):
            raise ValueError("корпус нельзя удалить командой удаления элемента")
        super().__init__(doc, text or f"удаление {describe_item(item)}")
        self._item: Any = item
        self._parent_node: Node = Node("_")

    @property
    def item(self) -> Any:
        """Удаляемый элемент."""
        return self._item

    def _prepare(self) -> None:
        fp = self._fp
        assert fp is not None
        node = _node_of(self._item)
        if node is fp.node:
            raise ValueError("корпус нельзя удалить командой удаления элемента")
        parent = _find_parent(fp.node, node)
        if parent is None:
            raise ValueError("элемент не входит в открытый корпус")
        self._parent_node = parent

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        return [(self._parent_node, False), (_node_of(self._item), True)]

    def _perform(self) -> None:
        self._parent_node.remove_child(_node_of(self._item))


# ---------------------------------------------------------------------------------------------
# Сложные операции
# ---------------------------------------------------------------------------------------------

def _snapshot_arg(value: Any, what: str) -> tuple[Node, bool | None]:
    if isinstance(value, Footprint):
        return value.node, value.final_newline
    if isinstance(value, View):
        return value.node, None
    if isinstance(value, Node):
        return value, None
    raise TypeError(f"{what}: ожидается Node, представление или Footprint, "
                    f"а не {type(value).__name__}")


class ReplaceNodeCommand(DocumentCommand):
    """Применить готовое состояние узла — для сложных операций, выполненных над копией
    (сдвиг, поворот, отражение, перенумерация, результат генератора)::

        before = doc.fp.node.copy()
        work = doc.fp.copy()
        work.renumber_pads(order="circular")
        doc.apply(ReplaceNodeCommand(doc, before, work.node, "перенумерация площадок"))

    ``before_copy``/``after_copy`` — снимки (``Node``, представление или ``Footprint``):
    копии, не входящие в дерево документа; их узлы в дерево не попадают (вставляются
    копии), менять снимки до выполнения команды нельзя. ``target`` —
    живой узел (или представление), содержимое которого заменяется; по умолчанию — корень
    корпуса. Идентичность целевого узла сохраняется (``root.items = копия``, корневой
    ``Node`` остаётся тем же объектом), подузлы переиспользуются, где структура совпадает
    (площадки после сдвига — те же объекты, выделение и представления остаются
    действительными); в дерево попадают только копии снимков. Отмена даёт в точности
    ``before_copy``, повтор — ``after_copy``.

    Если живое дерево уже изменено вызывающим (сначала операция над живой моделью, потом
    команда), первое выполнение сначала приводит его к ``before_copy`` — отмена всё равно
    вернёт состояние «до». Если снимки — :class:`~kicadfp.model.Footprint`, при замене
    корня переносится и признак ``final_newline``.

    Для операций над живой моделью без копий удобнее :class:`OperationCommand`.
    """

    def __init__(self, doc: Any, before_copy: Any, after_copy: Any, text: str | None = None, *,
                 target: View | Node | None = None) -> None:
        b_node, b_nl = _snapshot_arg(before_copy, "before_copy")
        a_node, a_nl = _snapshot_arg(after_copy, "after_copy")
        if target is not None:
            _node_of(target)
        default = "изменение корпуса" if target is None or isinstance(target, Footprint) \
            else f"изменение {describe_item(target)}"
        super().__init__(doc, text or default)
        self._before: Node | None = b_node
        self._after: Node | None = a_node
        self._before_nl = b_nl
        self._after_nl = a_nl
        self._target = target
        self._target_node: Node | None = None

    def _resolve_target(self) -> Node:
        fp = self._fp
        assert fp is not None
        node = fp.node if self._target is None else _node_of(self._target)
        if node is fp.node:
            for snap in (self._before, self._after):
                if snap.name not in _ROOT_NAMES:
                    raise ValueError(f"корень корпуса можно заменить только узлом footprint/"
                                     f"module, а не {snap.name!r}")
        elif not _in_tree(fp.node, node):
            raise ValueError("заменяемый узел не входит в открытый корпус")
        return node

    def _apply_snapshot(self, snap: Node, final_newline: bool | None) -> None:
        fp = self._fp
        assert fp is not None and self._target_node is not None
        _sync(self._target_node, snap)
        if self._target_node is fp.node and final_newline is not None:
            fp.final_newline = final_newline

    def _prepare(self) -> None:
        if self._before is None or self._after is None:
            raise RuntimeError("снимки команды уже использованы")
        self._target_node = self._resolve_target()
        self._apply_snapshot(self._before, self._before_nl)

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        assert self._target_node is not None
        return [(self._target_node, True)]

    def _perform(self) -> None:
        assert self._after is not None
        self._apply_snapshot(self._after, self._after_nl)
        # снимки нужны только для первого выполнения (далее — состояния узлов)
        self._before = self._after = None


class OperationCommand(DocumentCommand):
    """Выполнить операцию модели одним шагом отмены: ``operation(цель)``, где цель —
    открытый корпус (``doc.fp``) или элемент ``item`` (представление, привязанное к
    корпусу)::

        OperationCommand(doc, lambda fp: fp.move(1.27, 0), "сдвиг корпуса")
        OperationCommand(doc, lambda fp: fp.renumber_pads(order="circular"), "перенумерация")
        OperationCommand(doc, lambda g: g.move(dx, dy), "перемещение линии", item=line)

    Операция выполняется над живой моделью один раз; отмена и повтор — по снимкам (точно,
    с сохранением идентичности узлов). Исключение в операции откатывает её частичные
    изменения. :attr:`result` — значение, которое вернула операция.

    Без ``item`` снимается всё дерево корпуса (операция может менять что угодно). С
    ``item`` — только поддерево элемента и списки элементов корня и родителя: операция
    должна менять лишь сам элемент (как методы представлений ``move``/``rotate``/
    ``mirror`` и setters); для изменений нескольких элементов — ``item=None``.
    """

    def __init__(self, doc: Any, operation: Callable[[Any], Any], text: str | None = None, *,
                 item: View | Node | None = None) -> None:
        if not callable(operation):
            raise TypeError("operation должна быть вызываемой: operation(корпус или элемент)")
        if item is not None:
            _node_of(item)
        default = "изменение корпуса" if item is None or isinstance(item, Footprint) \
            else f"изменение {describe_item(item)}"
        super().__init__(doc, text or default)
        self._operation = operation
        self._item = item
        self._target: Any = None
        self.result: Any = None

    def _prepare(self) -> None:
        self._target = self._fp if self._item is None else self._doc.bind(self._item)

    def _scope_nodes(self, fp: Footprint) -> list[tuple[Node, bool]]:
        if self._item is None or isinstance(self._target, Footprint):
            return [(fp.node, True)]
        return _element_scope(fp, _node_of(self._target))

    def _perform(self) -> None:
        self.result = self._operation(self._target)


class BatchCommand(DocumentCommand):
    """Несколько команд одним шагом отмены (групповые операции над площадками и т. п.).

    ``BatchCommand(children, text=None, *, doc=None)`` или ``BatchCommand(doc, children,
    text=None)``. ``children`` — команды :class:`DocumentCommand` (ещё не выполненные) и/или
    любые ``QUndoCommand`` (у них вызывается ``redo()``); документ берётся из ``doc`` или из
    дочерних команд. Дочерние команды выполняются по порядку при первом выполнении группы;
    отмена и повтор группы — по её снимкам (сразу всё, один сигнал ``changed``). Ошибка в
    любой дочерней команде откатывает всю группу. Дочерние команды нельзя затем применять
    отдельно.
    """

    def __init__(self, *args: Any, text: str | None = None, doc: Any = None) -> None:
        args_list = list(args)
        if args_list and hasattr(args_list[0], "_emit_changed") \
                and not isinstance(args_list[0], QUndoCommand):
            if doc is not None and doc is not args_list[0]:
                raise ValueError("документ указан дважды")
            doc = args_list.pop(0)
        if not args_list:
            raise TypeError("BatchCommand: не заданы дочерние команды")
        if len(args_list) > 2:
            raise TypeError("BatchCommand(children, text=None, *, doc=None)")
        children = args_list[0]
        if len(args_list) == 2:
            if text is not None:
                raise TypeError("BatchCommand: text указан дважды")
            text = args_list[1]
        if isinstance(children, QUndoCommand):
            children = [children]
        kids = list(children)
        for c in kids:
            if not isinstance(c, QUndoCommand):
                raise TypeError(f"дочерняя команда должна быть QUndoCommand, "
                                f"а не {type(c).__name__}")
        docs = {id(c.document): c.document for c in kids if isinstance(c, DocumentCommand)}
        if doc is None:
            if len(docs) != 1:
                raise TypeError("BatchCommand: укажите doc (его нельзя определить по дочерним "
                                "командам)")
            doc = next(iter(docs.values()))
        elif any(d is not doc for d in docs.values()):
            raise ValueError("дочерние команды относятся к другому документу")
        if text is None:
            text = kids[0].actionText() if len(kids) == 1 else "групповая операция"
        super().__init__(doc, text)
        self._children = kids

    @property
    def children(self) -> list[QUndoCommand]:
        """Дочерние команды."""
        return list(self._children)

    def _perform(self) -> None:
        fp = self._fp
        assert fp is not None
        for c in self._children:
            if isinstance(c, DocumentCommand):
                c._execute_in_batch(fp)
            else:
                c.redo()
