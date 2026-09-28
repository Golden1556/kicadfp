"""Помощники тестов с kicad-cli: пересохранение библиотеки KiCad, поиск файлов, которые KiCad
не читает, и сравнение корпуса «как его видит KiCad» до и после пересохранения.

Используются ``tests/test_kicad_cli.py``, ``tests/test_acceptance.py`` и
``scripts/acceptance_report.py``.

Как проверяется, что KiCad читает файл. ``kicad-cli fp upgrade --force LIB.pretty -o OUT``
загружает каждый корпус библиотеки и записывает его заново; если хоть один файл не читается,
KiCad отвергает всю библиотеку («Unable to load library», код 2) — тогда виновные файлы
находятся делением библиотеки пополам (:func:`unreadable`). Затем прочитанное KiCad
сравнивается с прочитанным kicadfp (:func:`signature`, :func:`compare`): площадки, графика,
тексты и 3D-модели должны совпасть. Сравнение учитывает то, что KiCad при чтении
нормализует сам: стирает номер у неметаллизированных отверстий и апертур
(``PAD::CanHaveNumber``), пишет ``%R``/``%V`` как ``${REFERENCE}``/``${VALUE}``, добавляет
пустые служебные поля (Datasheet, Description …), приводит углы текстов к [0, 360) и
переупорядочивает элементы; числа сравниваются с допуском 10 нм.
"""

from __future__ import annotations

import functools
import itertools
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import kicadfp
from kicadfp import layers as L
from kicadfp.model import Footprint, Pad

__all__ = [
    "TIMEOUT", "CliRun", "LibraryCheck", "run", "upgrade", "export_svg", "unreadable",
    "check_library", "write_library", "signature", "compare", "cli_version", "sample",
    "sample_step",
]

#: Предельное время одного запуска kicad-cli, с.
TIMEOUT = 600
#: Допуск сравнения чисел, мм/градусы (KiCad хранит целые нанометры).
TOL = 1e-5
#: Сообщения kicad-cli о ходе работы (KiCad 8 печатает их всегда) — не ошибки.
_PROGRESS = ("Loading footprint library", "Saving footprint library", "Plotting footprint")


# ---------------------------------------------------------------------------------------------
# Запуск kicad-cli
# ---------------------------------------------------------------------------------------------

@dataclass
class CliRun:
    """Результат запуска kicad-cli."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def messages(self) -> list[str]:
        """Сообщения KiCad, кроме строк о ходе работы (ошибки, предупреждения)."""
        lines = (self.stdout + "\n" + self.stderr).splitlines()
        return [s for s in (ln.strip() for ln in lines) if s and not s.startswith(_PROGRESS)]

    @property
    def ok(self) -> bool:
        """Код возврата 0 и ни одного сообщения об ошибке или предупреждения."""
        return self.returncode == 0 and not self.messages

    def __str__(self) -> str:
        cmd = " ".join(Path(self.args[0]).name if i == 0 else a for i, a in enumerate(self.args))
        return f"{cmd} -> код {self.returncode}: {'; '.join(self.messages) or 'без сообщений'}"


def run(cli: str, *args: object, timeout: int = TIMEOUT) -> CliRun:
    """Запустить ``cli ARGS`` (без оболочки) и вернуть :class:`CliRun`."""
    argv = [str(cli), *map(str, args)]
    t0 = time.perf_counter()
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return CliRun(argv, r.returncode, r.stdout, r.stderr, time.perf_counter() - t0)


def upgrade(cli: str, lib: Path, out: Path) -> CliRun:
    """``kicad-cli fp upgrade --force LIB -o OUT``: KiCad читает и пересохраняет каждый корпус
    (``--force`` — даже если версия формата уже текущая)."""
    return run(cli, "fp", "upgrade", "--force", lib, "-o", out)


def export_svg(cli: str, lib: Path, name: str, out: Path,
               layers: Iterable[str] | None = None) -> CliRun:
    """``kicad-cli fp export svg LIB --fp NAME -o OUT [--layers …]``."""
    extra: list[object] = ["--layers", ",".join(layers)] if layers else []
    return run(cli, "fp", "export", "svg", lib, "--fp", name, "-o", out, *extra)


@functools.lru_cache(maxsize=None)
def cli_version(cli: str) -> str:
    """Версия kicad-cli строкой (``"9.0.1"``) или ``""`` (запоминается для каждого пути)."""
    try:
        out = run(cli, "version", timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\d+\.\d+(?:\.\d+)?", out)
    return m.group(0) if m else ""


def unreadable(cli: str, lib: Path, work: Path) -> list[str]:
    """Имена файлов ``lib``, которые KiCad не читает (деление пополам: KiCad отвергает всю
    библиотеку, если не читается хоть один файл)."""
    names = sorted(p.name for p in lib.glob("*.kicad_mod"))
    counter = itertools.count()

    def readable(subset: list[str]) -> bool:
        probe = work / f"probe{next(counter)}.pretty"
        probe.mkdir(parents=True)
        for n in subset:
            shutil.copyfile(lib / n, probe / n)
        out = probe.with_name(probe.stem + "_out")
        try:
            return upgrade(cli, probe, out).ok
        finally:
            shutil.rmtree(probe, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)

    def search(subset: list[str]) -> list[str]:
        if not subset or readable(subset):
            return []
        if len(subset) == 1:
            return subset
        mid = len(subset) // 2
        return search(subset[:mid]) + search(subset[mid:])

    return search(names)


# ---------------------------------------------------------------------------------------------
# Библиотеки
# ---------------------------------------------------------------------------------------------

def write_library(fps: Mapping[str, Footprint], lib: Path) -> Path:
    """Записать корпуса в каталог ``lib`` (создаётся): ``{имя файла: корпус}`` →
    ``<lib>/<имя>.kicad_mod`` через :func:`kicadfp.save`."""
    lib.mkdir(parents=True, exist_ok=True)
    for name, fp in fps.items():
        kicadfp.save(fp, lib / f"{name}.kicad_mod")
    return lib


@dataclass
class LibraryCheck:
    """Итог проверки библиотеки kicad-cli (:func:`check_library`)."""

    cli: str
    files: int
    run: CliRun
    unreadable: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    mismatches: dict[str, list[str]] = field(default_factory=dict)
    compared: int = 0

    @property
    def ok(self) -> bool:
        """KiCad прочитал все файлы без сообщений, и содержимое совпало."""
        return self.run.ok and not (self.unreadable or self.missing or self.mismatches)

    def report(self, limit: int = 10) -> str:
        """Текст для сообщения об ошибке теста."""
        lines = [f"{self.run} (файлов: {self.files})"]
        if self.unreadable:
            lines.append(f"KiCad не читает ({len(self.unreadable)}): "
                         f"{', '.join(self.unreadable[:limit])}")
        if self.missing:
            lines.append(f"нет в выводе KiCad ({len(self.missing)}): "
                         f"{', '.join(self.missing[:limit])}")
        for name, diffs in list(self.mismatches.items())[:limit]:
            lines.append(f"{name}: " + " | ".join(diffs[:3]))
        return "\n".join(lines)


def check_library(cli: str, lib: Path, work: Path, *, compare_content: bool = True,
                  compare_step: int = 1) -> LibraryCheck:
    """Пересохранить библиотеку ``lib`` в KiCad (``work/<lib>_kicad``) и сравнить корпуса с
    прочитанным kicadfp (каждый или, при ``compare_step`` > 1, каждый ``compare_step``-й;
    прочитаться без ошибок должны все). Если KiCad отверг библиотеку — найти нечитаемые
    файлы."""
    files = sorted(lib.glob("*.kicad_mod"))
    out = work / f"{lib.stem}_kicad.pretty"
    if out.exists():
        shutil.rmtree(out)
    r = upgrade(cli, lib, out)
    res = LibraryCheck(str(cli), len(files), r)
    if not r.ok:
        res.unreadable = unreadable(cli, lib, work / f"{lib.stem}_bisect")
        return res
    res.missing = [p.name for p in files if not (out / p.name).is_file()]
    if compare_content:
        for p in files[::max(1, compare_step)]:
            q = out / p.name
            if not q.is_file():
                continue
            diffs = compare(signature(kicadfp.load(p)), signature(kicadfp.load(q)))
            res.compared += 1
            if diffs:
                res.mismatches[p.name] = diffs
    return res


# ---------------------------------------------------------------------------------------------
# Содержимое корпуса «как его видит KiCad»
# ---------------------------------------------------------------------------------------------

def _expanded(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(L.expand([n for n in names if L.is_valid_layer(n)]))
                        | {n for n in names if not L.is_valid_layer(n)}))


def _pad_number(p: Pad) -> str:
    """Номер площадки после чтения KiCad: у NPTH и апертур (SMD/CONN без меди) он стирается
    (``PAD::CanHaveNumber``)."""
    if p.type == "np_thru_hole":
        return ""
    if p.type in ("smd", "connect") and not any(L.is_copper(n) for n in _expanded(p.layers)):
        return ""
    return p.number


def _text(s: str) -> str:
    return s.replace("%R", "${REFERENCE}").replace("%V", "${VALUE}")


def _f(v: Any) -> float:
    return 0.0 if v is None else float(v)


def _angle(v: Any) -> float:
    """Угол в [0, 360) (KiCad 9 нормализует углы текстов; 359.9999999 → 0)."""
    a = _f(v) % 360.0
    return 0.0 if abs(a - 360.0) < TOL else a


def signature(fp: Footprint) -> dict[str, Any]:
    """Содержимое корпуса для сравнения kicadfp ↔ KiCad (порядок элементов не важен).

    * ``pads`` — номер (после нормализации KiCad), тип, форма, x, y, угол (mod 360), размер,
      отверстие (размер и смещение), раскрытый набор слоёв, скругление;
    * ``graphics`` — вид, слой, характерные точки, ширина линии, заливка;
    * ``texts`` — непустые тексты: текст (``%R``/``%V`` → ``${…}``), слой, скрыт ли, x, y,
      угол (mod 360), размер шрифта;
    * ``models`` — путь, смещение (мм), масштаб, поворот, скрыта ли;
    * ``footprint`` — слой корпуса, описание, ключевые слова; ``zones`` — число зон.
    """
    pads = []
    for p in fp.pads:
        d = p.drill
        drill = None if d is None else (_f(d.size[0]), _f(d.size[1]), _f(d.offset[0]),
                                        _f(d.offset[1]))
        pads.append((_pad_number(p), p.type, p.shape, _f(p.x), _f(p.y), _angle(p.angle),
                     _f(p.size_x), _f(p.size_y), drill, _expanded(p.layers),
                     _f(p.roundrect_rratio) if p.shape == "roundrect" else 0.0))
    graphics = []
    for g in fp.graphics:
        pts = tuple((_f(x), _f(y)) for x, y in g.points)
        graphics.append((g.kind, g.layer or "", pts, _f(g.width), bool(g.fill)))
    texts = []
    for t in fp.texts:
        if not t.text:
            continue
        fx, fy = t.font_size
        texts.append((_text(t.text), t.layer or "", bool(t.hide), _f(t.x), _f(t.y),
                      _angle(t.angle), _f(fx), _f(fy)))
    models = [(m.path, tuple(map(_f, m.offset)), tuple(map(_f, m.scale)),
               tuple(map(_f, m.rotate)), bool(m.hide)) for m in fp.models]
    return {
        "footprint": (fp.layer, fp.descr, fp.tags),
        "pads": pads,
        "graphics": graphics,
        "texts": texts,
        "models": models,
        "zones": len(fp.zones),
    }


def _close(a: Any, b: Any, tol: float = TOL) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                and not isinstance(a, bool) and not isinstance(b, bool):
            return math.isclose(a, b, abs_tol=tol)
        return False
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


def _coarse(item: Any) -> Any:
    """Ключ сортировки: числа округлены до 0.01 (близкие элементы — рядом)."""
    if isinstance(item, float):
        return round(item, 2) + 0.0
    if isinstance(item, tuple):
        return tuple(_coarse(x) for x in item)
    if item is None:
        return ()
    return item


def _match(a: list[Any], b: list[Any], tol: float = TOL) -> tuple[list[Any], list[Any]]:
    """Сопоставить мультимножества с допуском: ``(только в a, только в b)``."""
    rest = sorted(b, key=lambda x: repr(_coarse(x)))
    only_a: list[Any] = []
    for x in sorted(a, key=lambda x: repr(_coarse(x))):
        for i, y in enumerate(rest):
            if _close(x, y, tol):
                del rest[i]
                break
        else:
            only_a.append(x)
    return only_a, rest


def compare(ours: Mapping[str, Any], kicad: Mapping[str, Any], tol: float = TOL) -> list[str]:
    """Расхождения сигнатур (:func:`signature`) kicadfp и KiCad — пустой список, если нет."""
    out: list[str] = []
    for key, a in ours.items():
        b = kicad.get(key)
        if isinstance(a, list) and isinstance(b, list):
            only_a, only_b = _match(a, b, tol)
            if only_a or only_b:
                out.append(f"{key}: только у kicadfp {only_a[:2]}; только у KiCad {only_b[:2]}")
        elif not _close(a, b, tol):
            out.append(f"{key}: kicadfp {a!r} != KiCad {b!r}")
    return out


def sample(files: list[Path], step: int, offset: int = 0) -> list[Path]:
    """Каждый ``step``-й файл начиная с ``offset % step`` (``step <= 1`` — все)."""
    if step <= 1:
        return list(files)
    return files[offset % step::step]


def sample_step(default: int = 5) -> int:
    """Шаг выборки файлов из ``KICADFP_CLI_STEP`` (1 — все файлы)."""
    try:
        return max(1, int(os.environ.get("KICADFP_CLI_STEP", default)))
    except ValueError:
        return default
