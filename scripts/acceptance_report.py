#!/usr/bin/env python3
"""Приёмочные испытания kicadfp по сценариям приложения Г ТЗ с отчётом в Markdown.

Скрипт запускает автоматические тесты сценариев Г.1–Г.10 (``tests/test_acceptance.py``),
проверки совместимости с KiCad (``tests/test_kicad_cli.py``), GUI-сценарий Г.8
(``tests/test_gui_mainwindow.py``) и тесты решений из критики спецификаций; собирает
фактические числа (``record_property`` в тестах), исходы, время и версии окружения и пишет
отчёт ``docs/acceptance_report.md``.

Запуск (из любого каталога)::

    python scripts/acceptance_report.py            # выборка файлов (каждый 5-й), ~2–3 мин
    python scripts/acceptance_report.py --full     # все файлы фикстур + 20 библиотек
                                                   # kicad-footprints 8.0.0 (.cache/kfp/v8.0.0)

Параметры: ``--kicad-cli PATH`` — kicad-cli KiCad 9+ (по умолчанию ``KICAD_CLI`` или
``kicad-cli`` из PATH); ``--kicad8-cli PATH`` — KiCad 8 (``KICAD8_CLI`` или ``kicad-cli8``);
``--kicad8-library DIR`` — каталог библиотек KiCad 8 для расширенного Г.1 (при ``--full`` по
умолчанию ``.cache/kfp/v8.0.0``, если он есть); ``--output FILE`` (по умолчанию
``docs/acceptance_report.md``); ``--print`` — напечатать отчёт и в stdout; ``--full-suite`` —
дополнительно весь набор тестов (``pytest``) и его итог в отчёте. Без kicad-cli проверки «открыть в KiCad» пропускаются
(ТЗ 4.5.4) и отмечаются в отчёте.

Код возврата: 0 — все запущенные тесты пройдены (пропуски допустимы), 1 — есть непройденные,
2 — ошибка запуска.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "docs" / "acceptance_report.md"
KICAD8_CACHE = REPO / ".cache" / "kfp" / "v8.0.0"

#: Тесты, из которых собирается отчёт.
TARGETS = [
    "tests/test_acceptance.py",
    "tests/test_kicad_cli.py",
    "tests/test_gui_mainwindow.py::test_scenario_8_drag_and_table_undo_redo_save",
    # решения из критики спецификаций (модульные проверки)
    "tests/test_validate.py::test_npth_number_and_empty_number",
    "tests/test_validate.py::test_rescue_layer",
    "tests/test_validate.py::test_version_too_new",
    "tests/test_validate.py::test_tht_no_outer_copper",
    "tests/test_validate.py::test_courtyard_missing",
    "tests/test_validate.py::test_all_fixtures_no_errors",
    "tests/test_legacy.py::test_shape3d_kicad9_and_fixed",
    "tests/test_legacy.py::test_format_error_position_and_path",
    "tests/test_legacy.py::test_compat_validation",
    "tests/test_legacy.py::test_kicad_cli_same_as_kicad_converter",
    "tests/test_model_model3d.py::test_legacy_at_is_inches_times_float_25_4",
    "tests/test_layers.py::test_wildcards_and_parser_names",
    "tests/test_model_graphics.py::test_fill_read_forms",
    "tests/test_model_graphics.py::test_fill_write_by_profile",
    "tests/test_model_graphics.py::test_fill_write_primitives",
    "tests/test_model_compat.py::test_hidden_user_text_becomes_hidden_field_in_kicad9",
    "tests/test_sexpr.py::test_number_formats_match_kicad_c_reference",
    "tests/test_model_footprint.py::test_views_read_every_special_fixture",
    # исправления, сделанные при приёмке (регрессионные тесты)
    "tests/test_generators.py::test_target_version_every_generator",
    "tests/test_generators.py::test_target_version_forms_of_kicad8_and_kicad6",
    "tests/test_generators.py::test_from_json_version",
    "tests/test_legacy.py::test_version_target_same_content",
    "tests/test_legacy.py::test_version_kicad6_has_no_thermal_bridge_angle",
    "tests/test_cli.py::test_gen_and_convert_kicad_target",
    "tests/test_gui_dialogs.py::test_generate_dialog_kicad_format",
    "tests/test_format_rules.py::test_kicad_format_versions",
    "tests/test_sexpr.py::test_unclosed_paren_in_the_middle_points_to_the_node",
    "tests/test_sexpr.py::test_unclosed_paren_without_indent_hint_reports_end",
]


# ---------------------------------------------------------------------------------------------
# Сбор результатов pytest
# ---------------------------------------------------------------------------------------------

@dataclass
class Result:
    """Итог одного теста (все фазы)."""

    nodeid: str
    outcome: str = "passed"
    duration: float = 0.0
    props: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    @property
    def name(self) -> str:
        return self.nodeid.split("::")[-1]

    @property
    def params(self) -> list[str]:
        m = re.search(r"\[(.*)\]$", self.nodeid)
        return m.group(1).split("-") if m else []


class Collector:
    """Плагин pytest: исходы, длительности и ``user_properties`` каждого теста."""

    def __init__(self) -> None:
        self.results: dict[str, Result] = {}
        self.errors: list[str] = []

    def pytest_runtest_logreport(self, report: Any) -> None:
        r = self.results.setdefault(report.nodeid, Result(report.nodeid))
        r.duration += report.duration
        r.props.update(dict(report.user_properties))
        if report.failed:
            r.outcome = "failed"
            r.message = _first_lines(getattr(report, "longreprtext", ""), 8)
        elif report.skipped and r.outcome != "failed":
            r.outcome = "skipped"
            lr = report.longrepr
            reason = lr[2] if isinstance(lr, tuple) and len(lr) == 3 else str(lr)
            r.message = str(reason).removeprefix("Skipped: ")

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.errors.append(f"{report.nodeid}: {_first_lines(report.longreprtext, 5)}")


def _first_lines(text: str, n: int) -> str:
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    return " / ".join(lines[-n:])[:1500]


def run_pytest(targets: list[str]) -> tuple[int, Collector, float]:
    import pytest

    col = Collector()
    t0 = time.perf_counter()
    rc = pytest.main(["-p", "no:cacheprovider", "-rN", *targets], plugins=[col])
    return int(rc), col, time.perf_counter() - t0


# ---------------------------------------------------------------------------------------------
# Окружение
# ---------------------------------------------------------------------------------------------

def _run_text(argv: list[str], timeout: int = 120) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=REPO)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip()


def cli_version(cli: str | None) -> str:
    if not cli:
        return ""
    m = re.search(r"\d+\.\d+(?:\.\d+)?", _run_text([cli, "version"]))
    return m.group(0) if m else ""


def find_cli(explicit: str | None, env: str, name: str) -> str | None:
    cli = explicit or os.environ.get(env) or shutil.which(name)
    return cli if cli and Path(cli).exists() else None


def environment(kicad9: str | None, kicad8: str | None,
                kicad8_lib: Path | None) -> list[tuple[str, str]]:
    import kicadfp

    try:
        import PySide6
        from PySide6 import QtCore
        qt = f"PySide6 {PySide6.__version__}, Qt {QtCore.qVersion()} (QT_QPA_PLATFORM=" \
             f"{os.environ.get('QT_QPA_PLATFORM', '')})"
    except ImportError:
        qt = "PySide6 не установлен (GUI-тесты пропускаются)"
    import pytest

    rev = _run_text(["git", "rev-parse", "--short", "HEAD"])
    dirty = _run_text(["git", "status", "--porcelain"])
    git = f"{rev}{' + незафиксированные изменения' if dirty else ''}" if rev else "—"
    from tests.conftest import FIXTURES, fixture_files

    counts = {d: len(fixture_files(d)) for d in ("kicad5", "kicad6", "kicad8", "kicad9",
                                                 "kicad10dev")}
    counts["special"] = len(list((FIXTURES / "special").rglob("*.kicad_mod")))
    fixtures = ", ".join(f"{k} — {v}" for k, v in counts.items())
    fixtures += f"; всего {sum(counts.values())}; legacy_mod/My_lib.mod (3 модуля)"
    rows = [
        ("kicadfp", f"{kicadfp.__version__}; git {git}"),
        ("Python", f"{platform.python_version()} ({sys.executable})"),
        ("ОС, процессор", f"{platform.platform()}, {os.cpu_count()} CPU"),
        ("Графический интерфейс", qt),
        ("pytest", pytest.__version__),
        ("KiCad 9", f"kicad-cli {cli_version(kicad9)} ({kicad9})" if kicad9 else
         "kicad-cli не найден — проверки в KiCad 9 пропущены"),
        ("KiCad 8", f"kicad-cli {cli_version(kicad8)} ({kicad8})" if kicad8 else
         "kicad-cli 8 не найден — проверки в KiCad 8 пропущены"),
        ("Фикстуры (tests/fixtures)", fixtures),
    ]
    if kicad8_lib is not None:
        n = len(list(kicad8_lib.rglob("*.kicad_mod")))
        libs = len([p for p in kicad8_lib.rglob("*.pretty") if p.is_dir()])
        rows.append(("Библиотеки KiCad 8 (расширенный Г.1)",
                     f"{_rel(kicad8_lib)}: {libs} библиотек, {n} файлов"))
    return rows


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------------------------
# Доступ к результатам
# ---------------------------------------------------------------------------------------------

class Results:
    def __init__(self, col: Collector) -> None:
        self.all = list(col.results.values())

    def find(self, name: str, *params: str) -> list[Result]:
        """Тесты с именем ``name`` (без параметров или с параметрами, среди которых все
        ``params``)."""
        out = []
        for r in self.all:
            base = r.name.split("[", 1)[0]
            if base == name and all(p in r.params for p in params):
                out.append(r)
        return out

    def one(self, name: str, *params: str) -> Result | None:
        found = self.find(name, *params)
        return found[0] if found else None

    def prefix(self, prefix: str) -> list[Result]:
        return [r for r in self.all if r.name.startswith(prefix)]


def plural(n: int, one: str, few: str, many: str) -> str:
    """``3 корпуса``, ``5 корпусов``, ``21 корпус``."""
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


def _outcome_ru(r: Result | None) -> str:
    if r is None:
        return "не запускался"
    return {"passed": "пройден", "failed": "НЕ ПРОЙДЕН", "skipped": "пропущен"}[r.outcome]


def _k(r: Result | None, key: str, default: Any = "?") -> Any:
    if r is None or r.outcome != "passed":
        return default
    return r.props.get(key, default)


def _cli_note(r: Result | None, what: str) -> str:
    """Итог проверки «открыть в KiCad»: ``KiCad 9.0.1: 1377/1377`` или причина пропуска."""
    if r is None:
        return f"{what}: не запускалось"
    if r.outcome == "skipped":
        return f"{what}: не проверялось ({r.message})"
    if r.outcome == "failed":
        return f"{what}: ОШИБКА"
    ver = r.props.get("kicad_cli", "")
    files = r.props.get("files")
    eq = r.props.get("compared_equal")
    count = f" {eq}/{files}" if files is not None and eq is not None else ""
    return f"KiCad {ver}:{count} без ошибок" if ver else f"{what}: без ошибок"


# ---------------------------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------------------------

@dataclass
class Scenario:
    number: int
    title: str
    expected: str
    steps: str
    facts: Callable[[Results], list[str]]
    notes: list[str] = field(default_factory=list)
    extra_tests: tuple[str, ...] = ()
    kicad_note: str = ""
    #: Номера фактов (из ``facts``) для строки сводной таблицы.
    summary: tuple[int, ...] = (0,)


def _n(n: Any, one: str, few: str, many: str) -> str:
    return plural(n, one, few, many) if isinstance(n, int) else f"{n} {many}"


def _g1(R: Results) -> list[str]:
    r = R.one("test_scenario_1_roundtrip_kicad8_libraries")
    out = []
    if r is not None and r.outcome == "passed":
        p = r.props
        files = _n(p["files"], "корпус", "корпуса", "корпусов")
        out.append(f"Открыто и сохранено {files} стандартных библиотек KiCad 8 "
                   f"({p['libraries']}): деревья S-выражений совпали у {p['tree_equal']} из "
                   f"{p['files']} (строгое сравнение: числа и кавычки как в исходнике); байт в "
                   f"байт — {p['byte_equal']} из {p['kicad_written']} файлов, записанных KiCad; "
                   f"{p['seconds']} с.")
    notes = [_cli_note(R.one(f"test_scenario_1_saved_files_open_in_kicad{v}"), f"KiCad {v}")
             for v in (9, 8)]
    out.append("Сохранённые файлы в KiCad: " + "; ".join(notes)
               + " (содержимое после чтения KiCad совпадает).")
    f = R.one("test_scenario_1_full_kicad8_library")
    if f is not None and f.outcome == "passed":
        p = f.props
        kc = [f"KiCad {p[key + '_cli']} открыл {p[key + '_opened']}/{p['files']} (содержимое "
              f"совпало у {p[key + '_compared_equal']} из {p[key + '_compared']} проверенных)"
              for key in ("kicad9", "kicad8") if f"{key}_cli" in p]
        libs = _n(p["libraries"], "библиотека", "библиотеки", "библиотек")
        files = _n(p["files"], "файл", "файла", "файлов")
        text = (f"Расширенный прогон: {libs} kicad-footprints 8.0.0, {files} — деревья "
                f"{p['tree_equal']}/{p['files']}, байт в байт {p['byte_equal']}/"
                f"{p['kicad_written']}")
        if kc:
            text += f"; без ошибок: {'; '.join(kc)}"
        out.append(f"{text}; {p['seconds']} с.")
    elif f is not None:
        reason = f" ({f.message})" if f.message else ""
        out.append(f"Расширенный прогон по 20 библиотекам KiCad 8: {_outcome_ru(f)}{reason}.")
    return out


def _g2(R: Results) -> list[str]:
    r9 = R.one("test_scenario_2_kicad6_footprint_opens_in_kicad9")
    r8 = R.one("test_scenario_2_kicad6_footprint_opens_in_kicad8")
    base = r9 if r9 is not None and r9.outcome == "passed" else r8
    out = []
    if base is not None and base.outcome == "passed":
        p = base.props
        pads = _n(p["pads"], "площадка", "площадки", "площадок")
        graphics = _n(p["graphics"], "графический элемент", "графических элемента",
                      "графических элементов")
        texts = _n(p["texts"], "текст", "текста", "текстов")
        out.append(f"DIP-14_W7.62mm формата KiCad 6 (version 20211014, width, fp_text): {pads}, "
                   f"{graphics}, {texts}; сохранён без изменений (байт в байт) и с правкой "
                   f"(новая линия width 0.15 и текст fp_text — в форме KiCad 6).")
    for r, v in ((r9, 9), (r8, 8)):
        if r is not None and r.outcome == "passed":
            out.append(f"KiCad {r.props['kicad_cli']} открыл оба файла без ошибок: площадки, "
                       f"графика (с толщинами) и тексты на месте.")
        else:
            out.append(_cli_note(r, f"KiCad {v}") + ".")
    alls = [R.one("test_scenario_2_all_kicad6_fixtures_open_in_kicad", w)
            for w in ("kicad9", "kicad8")]
    notes = [_cli_note(a, w) for a, w in zip(alls, ("KiCad 9", "KiCad 8"))]
    out.append("Все корпуса формата KiCad 6 (фикстура kicad6): " + "; ".join(notes) + ".")
    return out


def _g3(R: Results) -> list[str]:
    r = R.one("test_scenario_3_unknown_node_kept_only_pad1_changed")
    out = []
    if r is not None and r.outcome == "passed":
        out.append(f"Узел (example_token 1 2) сохранён без изменений (та же строка, то же "
                   f"место); изменилась одна строка файла — (size 1.6 1.6) → (size 2 2) "
                   f"площадки 1 (расхождения дерева: {r.props['diff']}).")
    c = R.one("test_scenario_3_cli_set_keeps_unknown_node")
    out.append(f"То же командой kicadfp set … \"pad[1].size\" 2: {_outcome_ru(c)}.")
    k = R.one("test_scenario_3_kicad_reads_the_edit_without_unknown_node")
    if k is not None and k.outcome == "passed":
        reads = k.props.get("kicad_reads_file_with_unknown_token")
        msg = k.props.get("kicad_message_for_unknown_token", "")
        why = f" («{msg}»)" if msg and msg != "-" and not reads else ""
        out.append(f"KiCad {k.props['kicad_cli']} читает то же изменение без неизвестного узла "
                   f"(площадка 1 — 2 × 2, остальное без изменений). Файл с неизвестным узлом "
                   f"KiCad {'открывает' if reads else 'не открывает'}{why}.")
    else:
        out.append(_cli_note(k, "Проверка в KiCad") + ".")
    return out


def _g4(R: Results) -> list[str]:
    parts = []
    for v in ("kicad8", "kicad6", "kicad5"):
        r = R.one("test_scenario_4_all_pads_to_smd_roundrect", v)
        if r is not None and r.outcome == "passed":
            warn = r.props["warnings"]
            pads = _n(r.props["pads"], "площадка", "площадки", "площадок")
            parts.append(f"{v}: {pads}, ошибок {r.props['errors']}, предупреждений "
                         f"{'нет' if warn == '-' else warn}")
        else:
            parts.append(f"{v}: {_outcome_ru(r)}")
    out = ["DIP-14 → SMD (roundrect 0.25, F.Cu F.Mask F.Paste, smd, без отверстий, attr smd) "
           "в форматах KiCad 8, 6 и 5: " + "; ".join(parts) + "; запись в строгом режиме "
           "выполнена, изменены только площадки и атрибут."]
    c = R.one("test_scenario_4_same_result_with_cli_set")
    out.append(f"Групповое изменение командами kicadfp set \"pad[*]…\": {_outcome_ru(c)} "
               f"(тот же файл, что и через API).")
    k = R.one("test_scenario_4_kicad_shows_smd_footprint")
    if k is not None and k.outcome == "passed":
        files = _n(k.props["files"], "файл прочитан", "файла прочитаны", "файлов прочитаны")
        out.append(f"KiCad {k.props['kicad_cli']}: {files} без ошибок, все площадки SMD "
                   f"roundrect 0.25, attr smd; SVG слоёв F.Cu+F.Paste построен "
                   f"({k.props['svg_bytes']} байт).")
    else:
        out.append(_cli_note(k, "Проверка в KiCad") + ".")
    return out


def _g5(R: Results) -> list[str]:
    out = []
    for name in ("dip14", "mlt", "snp8"):
        r = R.one("test_scenario_5_lab_footprint_matches_assignment", name)
        h = R.one("test_scenario_5_matches_hand_made_footprint", name)
        if r is not None and r.outcome == "passed":
            p = r.props
            dev = _k(h, "max_deviation_mm")
            signal = _n({"dip14": 14, "mlt": 2, "snp8": 8}[name], "площадка", "площадки",
                        "площадок")
            if p["pitch"] == "-":
                geometry = f"расстояние между площадками {p['rows']:g}"
            else:
                geometry = f"шаг {p['pitch']:g}, расстояние между рядами {p['rows']:g}"
            holes = " + 2 монтажных отверстия Ø3" if name == "snp8" else ""
            out.append(f"{name}: {signal}{holes}; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, "
                       f"остальные — circle; {geometry}; контур {p['body']} мм; отличие от "
                       f"корпуса, созданного вручную (My_lib.mod), — не более {dev} мм.")
        else:
            out.append(f"{name}: {_outcome_ru(r)}.")
    c = R.one("test_scenario_5_cli_gen_same_as_api")
    out.append(f"kicadfp gen dip14/mlt/snp8 -o …: {_outcome_ru(c)} (те же файлы, что и API).")
    for w, label in (("kicad9", "KiCad 9 (формат 20241229)"),
                     ("kicad8", "KiCad 8 (формат 20240108)")):
        k = R.one("test_scenario_5_lab_footprints_open_in_kicad", w)
        if k is not None and k.outcome == "passed":
            files = _n(k.props["files"], "корпус", "корпуса", "корпусов")
            out.append(f"{label}: kicad-cli {k.props['kicad_cli']} открыл {files} без ошибок, "
                       f"после чтения — те же площадки и контур.")
        else:
            out.append(_cli_note(k, label) + ".")
    return out


def _g6(R: Results) -> list[str]:
    out = []
    for src in ("lab_dip14", "kicad8"):
        r = R.one("test_scenario_6_drill_bigger_than_pad_is_error", src)
        if r is not None and r.outcome == "passed":
            out.append(f"{src}: «{r.props['error']}».")
        else:
            out.append(f"{src}: {_outcome_ru(r)}.")
    cli = _outcome_ru(R.one("test_scenario_6_cli_validate_reports_error"))
    out.append("Запись в строгом режиме отклоняется (ValidationError), по умолчанию — "
               f"выполняется; kicadfp validate — код 1: {cli}.")
    return out


def _g7(R: Results) -> list[str]:
    out = []
    for where, label in (("middle", "Не закрыта скобка (at …) площадки 5"),
                         ("end", "Нет последней скобки файла")):
        r = R.one("test_scenario_7_syntax_error_line_and_position", where)
        if r is not None and r.outcome == "passed":
            out.append(f"{label}: «{r.props['message']}»; модель не создана.")
        else:
            out.append(f"{label}: {_outcome_ru(r)}.")
    cli = _outcome_ru(R.one("test_scenario_7_cli_exit_code_2"))
    gui = _outcome_ru(R.one("test_scenario_7_gui_document_not_created"))
    out.append(f"Командная строка (info, validate, pads, set) — код 2 и то же сообщение: {cli}; "
               f"документ GUI не открывается: {gui}.")
    return out


def _g8(R: Results) -> list[str]:
    g = R.one("test_scenario_8_drag_and_table_undo_redo_save")
    d = R.one("test_scenario_8_document_move_undo_redo_save")
    out = [f"Главное окно (tests/test_gui_mainwindow.py): перетаскивание площадки 1 мышью "
           f"(0; 0) → (−2; −3), ввод X = 5.08 в таблице, Ctrl+Z / меню «Отменить», "
           f"Ctrl+Shift+Z / «Повторить», «Сохранить как», Ctrl+S — {_outcome_ru(g)}; значения "
           f"модели, таблицы и поля просмотра совпадают на каждом шаге."]
    if d is not None and d.outcome == "passed":
        out.append(f"Без окна (FootprintDocument + модель таблицы + команда канвы): итоговые "
                   f"координаты в файле ({d.props['final_xy']}), изменён только узел (at …) "
                   f"площадки 1; после отмены всех шагов файл совпадает с исходным байт в байт.")
    else:
        out.append(f"Без окна: {_outcome_ru(d)}.")
    return out


def _g9(R: Results) -> list[str]:
    r = R.one("test_scenario_9_copy_with_rename")
    out = []
    if r is not None and r.outcome == "passed":
        files = _n(r.props["source_files"], "файл", "файла", "файлов")
        out.append(f"Library.copy_to(…, \"dip14_copy\"): в целевой библиотеке один файл "
                   f"dip14_copy.kicad_mod с полем name «dip14_copy»; исходная библиотека "
                   f"({files}) не изменена (SHA-256 совпадают); отличие копии от исходного "
                   f"корпуса — только имя: {r.props['diff']}.")
    else:
        out.append(f"Копирование: {_outcome_ru(r)}.")
    k = R.one("test_scenario_9_copied_footprint_opens_in_kicad")
    if k is not None and k.outcome == "passed":
        out.append(f"KiCad {k.props['kicad_cli']} читает целевую библиотеку, корпус "
                   f"«dip14_copy».")
    else:
        out.append(_cli_note(k, "KiCad") + ".")
    return out


def _g10(R: Results) -> list[str]:
    r = R.one("test_scenario_10_convert_legacy_library")
    out = []
    if r is not None and r.outcome == "passed":
        mods = _n(r.props["modules"], "модуль", "модуля", "модулей")
        out.append(f"My_lib.mod → My_lib.pretty: {mods} — по файлу на модуль "
                   f"({r.props['files']}); {r.props['values_checked']} значений (координаты, "
                   f"размеры, отверстия площадок, отрезки, тексты) равны децимилам × 0.00254 мм "
                   f"(например, 512 → 1.30048).")
    else:
        out.append(f"Преобразование: {_outcome_ru(r)}.")
    out.append(f"kicadfp convert … -o …: {_outcome_ru(R.one('test_scenario_10_cli_convert'))}.")
    for w, label in (("kicad9", "KiCad 9"), ("kicad8", "KiCad 8")):
        k = R.one("test_scenario_10_converted_library_opens_in_kicad", w)
        if k is not None and k.outcome == "passed":
            same = k.props["same_as_kicad_converter"]
            out.append(f"{label} (формат {k.props['format_version']}): kicad-cli "
                       f"{k.props['kicad_cli']} открыл результат без ошибок; содержимое "
                       f"совпадает с собственным конвертером KiCad ({same} из 3).")
        else:
            out.append(_cli_note(k, label) + ".")
    return out


SCENARIOS = [
    Scenario(1, "Открыть ≥ 200 корпусов стандартных библиотек KiCad 8, сохранить без изменений, "
                "сравнить деревья S-выражений",
             "Совпадение деревьев для всех файлов",
             "kicadfp.load → kicadfp.save → разбор исходного и записанного файла, сравнение "
             "деревьев (sexpr.equal/diff) и байтов; записанные файлы — kicad-cli fp upgrade "
             "(KiCad 9 и 8).", _g1, summary=(0, 2)),
    Scenario(2, "Открыть корпус KiCad 6 (width, fp_text), сохранить, открыть в KiCad 8 и 9",
             "Файл открывается без ошибок, графика и тексты на месте",
             "DIP-14_W7.62mm (version 20211014) — сохранить без изменений и с правкой; "
             "kicad-cli 9.0.1 и 8.0.6 читают и пересохраняют; сравнение площадок, графики, "
             "текстов; то же для всех 224 корпусов формата KiCad 6.", _g2),
    Scenario(3, "В корпус DIP-14 добавить неизвестный узел (example_token 1 2), изменить размер "
                "площадки 1, сохранить",
             "Неизвестный узел сохранён без изменений, изменена только площадка 1",
             "В файл DIP-14 (KiCad 8) вставлена строка (example_token 1 2); kicadfp.load, "
             "pad(\"1\").size = (2, 2), kicadfp.save; сравнение текста и деревьев до/после.",
             _g3, notes=[
                 "KiCad отвергает файл с неизвестным ему узлом (парсер parseFOOTPRINT → "
                 "«Expecting …», kicad-cli: «Unable to load library»), поэтому требование "
                 "сценария — сохранение узла — проверяется самой Программой, а проверка в KiCad "
                 "выполняется на том же изменении файла без неизвестного узла. Это ограничение "
                 "KiCad, а не Программы."],
             kicad_note=" (то же изменение без неизвестного узла: KiCad отвергает неизвестные "
                        "токены)"),
    Scenario(4, "У всех площадок: форма roundrect с rratio 0.25, слои F.Cu F.Mask F.Paste, тип "
                "smd, удалить отверстия",
             "Проверка не выдаёт ошибок, KiCad показывает SMD-корпус",
             "API: pad.shape/roundrect_rratio/layers/type/drill, attrs = {smd}; то же командами "
             "kicadfp set \"pad[*]…\"; validate; kicad-cli fp upgrade и fp export svg.", _g4),
    Scenario(5, "Сгенерировать dip14, mlt, snp8 по параметрам лабораторной работы, открыть в KiCad",
             "Площадки 1,3 мм, отверстия 0,8 мм, первая площадка квадратная, шаг и контур "
             "соответствуют заданию",
             "generators.lab_dip14/lab_mlt/lab_snp8 (и kicadfp gen dip14/mlt/snp8); сравнение с "
             "заданием (lab-generators.md §2) и с корпусами, созданными вручную (My_lib.mod); "
             "kicad-cli 9 (формат KiCad 9) и 8 (формат KiCad 8).", _g5, summary=(0, 1, 2)),
    Scenario(6, "Задать площадке отверстие 1,5 мм при размере 1,3 мм, выполнить проверку",
             "Сообщение об ошибке «отверстие больше площадки»",
             "pad.size = 1.3, pad.drill = 1.5; validate(); save(strict=True); kicadfp validate.",
             _g6),
    Scenario(7, "Открыть файл с синтаксической ошибкой (незакрытая скобка)",
             "Сообщение с номером строки и позиции, модель не создаётся",
             "DIP-14 без «)» у (at …) площадки 5 и без последней «)»; kicadfp.load (конструктор "
             "Footprint подменён счётчиком), kicadfp info/validate/pads/set, "
             "FootprintDocument.open.", _g7),
    Scenario(8, "В графическом интерфейсе переместить площадку мышью и в таблице, отменить, "
                "повторить, сохранить",
             "Значения в таблице и на поле просмотра совпадают, файл содержит итоговые координаты",
             "pytest-qt, QT_QPA_PLATFORM=offscreen: главное окно (мышь, таблица, клавиши, меню) и "
             "документ без окна.", _g8,
             extra_tests=("test_scenario_8_drag_and_table_undo_redo_save",)),
    Scenario(9, "Скопировать корпус из одной библиотеки .pretty в другую с переименованием",
             "В целевой библиотеке появился файл с новым именем и полем name, исходный не изменён",
             "Library(src).copy_to(Library(dst, create=True), \"DIP-14_W7.62mm\", \"dip14_copy\"); "
             "SHA-256 файлов источника до/после; kicad-cli.", _g9),
    Scenario(10, "Преобразовать библиотеку старого формата .mod (PCBnew-LibModule-V1) в .pretty",
             "Каждый модуль сохранён отдельным файлом .kicad_mod, единицы переведены из децимил "
             "в миллиметры, открывается в KiCad",
             "legacy.convert(My_lib.mod) и kicadfp convert; независимый разбор чисел .mod; "
             "kicad-cli 9 и 8; сравнение с собственным конвертером KiCad (kicad-cli fp upgrade "
             "My_lib.mod).", _g10),
]


# ---------------------------------------------------------------------------------------------
# Решения из критики спецификаций
# ---------------------------------------------------------------------------------------------

GAPS: list[tuple[str, str, list[str]]] = [
    ("Неизвестные токены: KiCad их отвергает",
     "Программа сохраняет неизвестный узел без изменений (Г.3); проверка в KiCad — на файле без "
     "неизвестного узла; ограничение отмечено в отчёте и тестах.",
     ["test_scenario_3_unknown_node_kept_only_pad1_changed",
      "test_scenario_3_kicad_reads_the_edit_without_unknown_node"]),
    ("validate: PAD_NPTH_NUMBER, PAD_EMPTY_NUMBER, LAYER_RESCUE, VERSION_TOO_NEW, "
     "PAD_THT_NO_COPPER; COURTYARD_MISSING не выдаётся при allow_missing_courtyard; нет ложных "
     "error на реальных библиотеках",
     "Реализовано (kicadfp/validate.py); все 2533 фикстуры (kicad5–10dev, special) — без "
     "ошибок.",
     ["test_npth_number_and_empty_number", "test_rescue_layer", "test_version_too_new",
      "test_tht_no_outer_copper", "test_courtyard_missing", "test_all_fixtures_no_errors"]),
    ("legacy: compat=\"kicad9\"|\"fixed\", LegacyFormatError с номером строки",
     "Реализовано; результат compat=\"kicad9\" совпадает с kicad-cli 9.0.1 (кроме uuid).",
     ["test_shape3d_kicad9_and_fixed", "test_format_error_position_and_path",
      "test_compat_validation", "test_kicad_cli_same_as_kicad_converter"]),
    ("Model: старая форма (at (xyz)) — дюймы ×25.4",
     "Реализовано (×25.4f, как парсер KiCad); KiCad пишет offset в мм — значения совпадают.",
     ["test_legacy_at_is_inches_times_float_25_4", "test_model_old_at_form_is_inches"]),
    ("F&B.Cu (6.0–9.0.5) и *.Cu (9.0.6+)",
     "Исходная форма сохраняется, layers.expand понимает обе, KiCad читает обе.",
     ["test_wildcards_and_parser_names", "test_fb_cu_and_star_cu_read_alike"]),
    ("fill: solid/none (6.0–8.0), yes/no (9.0+); примитивы custom — yes/none (6/7), yes/no (8+)",
     "Чтение всех форм, запись по профилю версии; KiCad читает то же значение.",
     ["test_fill_read_forms", "test_fill_write_by_profile", "test_fill_write_primitives",
      "test_fill_forms_by_version_read_by_kicad"]),
    ("hide у fp_text user в 9.0+",
     "Text.hide = True пишет (hide yes): в формате KiCad 8+ текст становится скрытым полем "
     "FieldN (как делает парсер KiCad 9). Проверено: kicad-cli 9.0.1 такое поле сохраняет, а "
     "(fp_text user … (hide yes)) при чтении теряет — поэтому запись полем надёжнее.",
     ["test_hidden_user_text_becomes_hidden_field_in_kicad9",
      "test_hidden_user_text_survives_kicad"]),
    ("Числа: углы < 1e-4 KiCad пишет с экспонентой",
     "kicadfp пишет без экспоненты, исходная запись сохраняется; лексеры обоих читают обе.",
     ["test_number_formats_match_kicad_c_reference", "test_small_angle_with_exponent"]),
    ("Фикстуры special/* (221 файл редких конструкций): round-trip и model-тесты",
     "Round-trip проходит; все представления читаются без исключений на каждом файле; "
     "записанные kicadfp файлы читает KiCad (выборка special в test_kicad_cli).",
     ["test_views_read_every_special_fixture", "test_fixtures_written_by_kicadfp_open_in_kicad9"]),
]

FIXES = [
    ("Новые корпуса открывались только в KiCad 9",
     "Генераторы, преобразование .mod и GUI «Создать типовой корпус» писали только формат "
     "KiCad 9 (version 20241229), а KiCad 8 такой файл не открывает («Unable to load library» — "
     "версия новее его собственной), что противоречит ТЗ 4.5.3 («открываться в KiCad 8 и 9») "
     "для сценариев Г.5 и Г.10.",
     "формат нового корпуса выбирается (по умолчанию — прежний, KiCad 9): "
     "format_rules.KICAD_FORMAT_VERSIONS/kicad_format_version; generators.target_version(8) "
     "(контекст) и from_json(…, version=8); legacy.convert/read_library/loads_library(…, "
     "version=8) (в формате KiCad 6 без thermal_bridge_angle — токена там нет); CLI "
     "kicadfp gen/convert --kicad {6,7,8,9}; GUI — поле «Формат файла» в диалоге «Создать "
     "типовой корпус». Корпуса генераторов и результат преобразования в форматах KiCad 6–8 "
     "проверены kicad-cli 8.0.6 и 9.0.1.",
     ["test_target_version_every_generator", "test_target_version_forms_of_kicad8_and_kicad6",
      "test_from_json_version", "test_version_target_same_content",
      "test_version_kicad6_has_no_thermal_bridge_angle", "test_gen_and_convert_kicad_target",
      "test_generate_dialog_kicad_format", "test_kicad_format_versions",
      "test_all_generators_open_in_kicad8", "test_convert_result_opens_in_kicad8",
      "test_kicad8_needs_kicad8_format"]),
    ("Позиция ошибки «незакрытая скобка» указывала на конец файла",
     "Пропущенная «)» в середине файла сдвигает все следующие закрывающие скобки, и к концу "
     "файла открытым остаётся корень: сообщение называло строку конца файла и корень "
     "footprint, а не место ошибки (сценарий Г.7).",
     "при незакрытой скобке sexpr.parse находит по отступам (KiCad пишет файлы с отступами по "
     "вложенности) узел, который должен был закрыться раньше, и сообщает его строку и позицию "
     "(«строка 262, позиция 3: незакрытая скобка: не закрыт узел «at» …»); если подсказки нет "
     "(файл в одну строку, не хватает последней скобки) — прежнее сообщение. Разбор "
     "корректных файлов не изменился (подсказка вычисляется только при ошибке).",
     ["test_unclosed_paren_in_the_middle_points_to_the_node",
      "test_unclosed_paren_without_indent_hint_reports_end",
      "test_scenario_7_syntax_error_line_and_position"]),
]


# ---------------------------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------------------------

def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _status(results: list[Result]) -> tuple[str, int, int, int, int]:
    passed = sum(r.outcome == "passed" for r in results)
    failed = sum(r.outcome == "failed" for r in results)
    skipped = sum(r.outcome == "skipped" for r in results)
    if not results:
        return "не проверялся", 0, 0, 0, 0
    if failed:
        return "не выполнен", passed, failed, skipped, len(results)
    if skipped:
        return "выполнен (часть проверок пропущена)", passed, failed, skipped, len(results)
    return "выполнен", passed, failed, skipped, len(results)


def _kicad_summary(rs: list[Result], note: str = "") -> str:
    """« Открыто в KiCad 9.0.1 и 8.0.6 без ошибок.» по тестам сценария с kicad-cli."""
    kicad = [r for r in rs if "kicad" in r.name and ("open" in r.name or "reads" in r.name
                                                     or "shows" in r.name)]
    if not kicad:
        return ""
    if any(r.outcome == "failed" for r in kicad):
        return " Проверка в KiCad: ОШИБКА."
    versions = sorted({str(r.props["kicad_cli"]) for r in kicad
                       if r.outcome == "passed" and r.props.get("kicad_cli")}, reverse=True)
    skipped = any(r.outcome == "skipped" for r in kicad)
    if not versions:
        return " Проверка в KiCad пропущена (нет kicad-cli)."
    return (f" KiCad {' и '.join(versions)}: открыто без ошибок, содержимое совпадает{note}"
            + (" (часть проверок пропущена)." if skipped else "."))


def _tests_status(R: Results, names: Iterable[str]) -> tuple[str, list[Result]]:
    rs = [r for n in names for r in R.find(n)]
    if not rs:
        return "не запускалось", rs
    if any(r.outcome == "failed" for r in rs):
        return "НЕ ПРОЙДЕНО", rs
    if all(r.outcome == "skipped" for r in rs):
        return "пропущено", rs
    passed = sum(r.outcome == "passed" for r in rs)
    return f"пройдено {passed} из {len(rs)}" + (
        f", пропущено {len(rs) - passed}" if passed < len(rs) else ""), rs


def _kicad_cli_section(R: Results, lines: list[str]) -> None:
    lines += ["## 4. Совместимость с KiCad (tests/test_kicad_cli.py)", "",
              "Корпуса записываются kicadfp в каталог .pretty, `kicad-cli fp upgrade --force` "
              "читает и пересохраняет каждый; KiCad не выдаёт сообщений, прочитанное KiCad "
              "(площадки, графика, тексты, 3D-модели) совпадает с прочитанным kicadfp. Режимы: "
              "`save` — открыть и сохранить без изменений; `upgrade` — Footprint.upgrade() в "
              "формат KiCad 9 (для KiCad 8 — 20240108); `edit` — сдвиг, поворот, размеры "
              "площадок, новая линия и текст, описание. В ячейках — «совпало/файлов»; KiCad 8 "
              "проверяет файлы форматов до 20240108 включительно.", ""]
    step = None
    rows = []
    for group in ("kicad5", "kicad6", "kicad8", "kicad9", "special"):
        for mode in ("save", "upgrade", "edit"):
            cells = []
            for cli in ("9", "8"):
                r = R.one(f"test_fixtures_written_by_kicadfp_open_in_kicad{cli}", group, mode)
                if r is None:
                    cells.append("—")
                elif r.outcome == "passed":
                    step = r.props.get("step", step)
                    cells.append(f"{r.props.get('compared_equal')}/{r.props.get('files')}")
                elif r.outcome == "skipped":
                    cells.append("пропуск")
                else:
                    cells.append("**ОШИБКА**")
            rows.append(f"| {group} | {mode} | {cells[0]} | {cells[1]} |")
    if step is not None:
        lines.append(f"Выборка: каждый {step}-й файл (у режимов разный сдвиг)"
                     if str(step) != "1" else "Проверены все файлы фикстур.")
        lines.append("")
    lines += ["| Фикстуры | Режим | KiCad 9 | KiCad 8 |", "|---|---|---|---|", *rows, ""]
    totals = []
    for cli in ("9", "8"):
        rs = [r for r in R.find(f"test_fixtures_written_by_kicadfp_open_in_kicad{cli}")
              if r.outcome == "passed"]
        if rs:
            files = sum(int(r.props.get("files", 0)) for r in rs)
            equal = sum(int(r.props.get("compared_equal", 0)) for r in rs)
            totals.append(f"KiCad {rs[0].props.get('kicad_cli')} — "
                          f"{plural(files, 'файл', 'файла', 'файлов')} (содержимое совпало у "
                          f"{equal})")
    if totals:
        lines += ["Всего записано kicadfp и открыто без ошибок: " + "; ".join(totals) + ".", ""]
    gen_rows = []
    for k in ("6", "7", "8", "9"):
        c9 = R.one("test_all_generators_open_in_kicad9", k)
        c8 = R.one("test_all_generators_open_in_kicad8", k)
        sources = ("My_lib", "synthetic")
        conv9 = [R.one("test_convert_result_opens_in_kicad9", s, k) for s in sources]
        conv8 = [R.one("test_convert_result_opens_in_kicad8", s, k) for s in sources]

        def cell(r: Result | None) -> str:
            if r is None:
                return "—"
            if r.outcome == "passed":
                return f"{r.props.get('compared_equal')}/{r.props.get('files')}"
            return "пропуск" if r.outcome == "skipped" else "**ОШИБКА**"

        def cells(rs: list[Result | None]) -> str:
            if all(r is None for r in rs):
                return "—"
            return " + ".join(cell(r) for r in rs)

        gen_rows.append(f"| KiCad {k} ({_fmt_version(k)}) | {cell(c9)} | {cell(c8)} | "
                        f"{cells(conv9)} | {cells(conv8)} |")
    lines += ["Новые корпуса (все варианты генераторов из tests/test_generators.py) и результат "
              "преобразования .mod (My_lib.mod + синтетическая библиотека) в каждом формате:", "",
              "| Формат | Генераторы: KiCad 9 | Генераторы: KiCad 8 | .mod: KiCad 9 "
              "| .mod: KiCad 8 |",
              "|---|---|---|---|---|", *gen_rows, ""]
    k8 = R.one("test_kicad8_needs_kicad8_format")
    if k8 is not None and k8.outcome == "passed":
        lines += [f"KiCad {k8.props.get('kicad_cli')} файл формата KiCad 9 (20241229) не открывает "
                  f"(«{k8.props.get('kicad8_message')}»), тот же корпус в формате KiCad 8 — "
                  f"открывает; отсюда параметр формата у генераторов и преобразования (раздел 6).",
                  ""]
    cli = [R.one("test_cli_gen_and_convert_open_in_kicad", p) for p in ("None", "8")]
    lines += [f"Команды `kicadfp gen` (dip14/mlt/snp8, пример ТЗ В.3) и `kicadfp convert`: формат "
              f"KiCad 9 — {_outcome_ru(cli[0])}, `--kicad 8` — {_outcome_ru(cli[1])}.", ""]


def _fmt_version(k: str) -> str:
    from kicadfp.format_rules import KICAD_FORMAT_VERSIONS
    return str(KICAD_FORMAT_VERSIONS[int(k)])


def build_report(R: Results, env: list[tuple[str, str]], args: argparse.Namespace,
                 total: float, collect_errors: list[str], suite: str | None) -> str:
    now = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    cmd = "python scripts/acceptance_report.py" + (" --full" if args.full else "") + \
        (" --full-suite" if args.full_suite else "")
    all_rs = R.all
    n_pass = sum(r.outcome == "passed" for r in all_rs)
    n_fail = sum(r.outcome == "failed" for r in all_rs)
    n_skip = sum(r.outcome == "skipped" for r in all_rs)
    lines = [
        "# Отчёт о приёмочных испытаниях kicadfp",
        "",
        f"Сформирован автоматически: {now}; команда `{cmd}` (скрипт "
        f"`scripts/acceptance_report.py`). Сценарии — ТЗ, приложение Г (таблица Г.1) и п. 8.2; "
        f"тесты — `tests/test_acceptance.py` (сценарии), `tests/test_kicad_cli.py` "
        f"(совместимость с KiCad), `tests/test_gui_mainwindow.py` (Г.8 в окне) и модульные тесты "
        f"решений из критики спецификаций. Проверка «открыть в KiCad» выполняется командной "
        f"строкой KiCad (`kicad-cli fp upgrade --force`, ТЗ 4.5.4): KiCad читает и пересохраняет "
        f"корпус без сообщений, а прочитанное KiCad совпадает с прочитанным kicadfp.",
        "",
        f"Итог: запущено тестов — {len(all_rs)}, пройдено — {n_pass}, не пройдено — {n_fail}, "
        f"пропущено — {n_skip}; время — {total:.0f} с.",
        "",
        "## 1. Условия испытаний",
        "",
        "| Параметр | Значение |",
        "|---|---|",
        *[f"| {a} | {_md_escape(b)} |" for a, b in env],
        "",
        "## 2. Сводная таблица",
        "",
        "| № | Сценарий | Ожидаемый результат | Фактический результат | Тесты | Время, с | Итог |",
        "|---|---|---|---|---|---|---|",
    ]
    details: list[str] = []
    for sc in SCENARIOS:
        rs = R.prefix(f"test_scenario_{sc.number}_")
        status, passed, failed, skipped, n = _status(rs)
        facts = sc.facts(R)
        dur = sum(r.duration for r in rs)
        picked = [facts[i] for i in sc.summary if i < len(facts)
                  and not facts[i].startswith("Расширенный прогон по 20")]
        short = (" ".join(picked) if picked else "—") + _kicad_summary(rs, sc.kicad_note)
        lines.append(f"| Г.{sc.number} | {_md_escape(sc.title)} | {_md_escape(sc.expected)} | "
                     f"{_md_escape(short)} | {passed}/{n}"
                     + (f" ({skipped} проп.)" if skipped else "") + f" | {dur:.1f} | {status} |")
        details += [f"### Г.{sc.number}. {sc.title}", "",
                    f"**Ожидаемый результат (ТЗ):** {sc.expected}.", "",
                    f"**Как проверяется:** {sc.steps}", "",
                    "**Фактический результат:**", ""]
        details += [f"- {f}" for f in facts]
        details.append("")
        for note in sc.notes:
            details += [f"**Примечание.** {note}", ""]
        details += ["**Тесты:**", ""]
        for r in sorted(rs, key=lambda r: r.nodeid):
            extra = f" — {r.message}" if r.outcome != "passed" and r.message else ""
            details.append(f"- `{r.nodeid}` — {_outcome_ru(r)} ({r.duration:.2f} с){extra}")
        details += ["", f"**Итог:** {status}.", ""]
    lines += ["", "## 3. Сценарии", "", *details]
    _kicad_cli_section(R, lines)
    lines += ["## 5. Решения из критики спецификаций", "",
              "| Пункт | Решение и факт | Проверка |", "|---|---|---|"]
    for title, decision, tests in GAPS:
        st, _ = _tests_status(R, tests)
        lines.append(f"| {_md_escape(title)} | {_md_escape(decision)} | {st}: "
                     f"{', '.join(f'`{t}`' for t in tests)} |")
    lines += ["", "## 6. Дефекты, найденные при приёмке, и исправления", ""]
    for i, (title, problem, fix, tests) in enumerate(FIXES, 1):
        st, _ = _tests_status(R, tests)
        lines += [f"{i}. **{title}.** {problem}", "",
                  f"   Исправление: {fix}", "",
                  f"   Регрессионные тесты — {st}: {', '.join(f'`{t}`' for t in tests)}.", ""]
    lines += ["## 7. Замечания", "",
              "- kicad-cli 9.0.1 читает старые библиотеки `.mod` (`kicad-cli fp upgrade "
              "My_lib.mod -o …`): это использовано в Г.10 для сравнения с собственным "
              "конвертером KiCad; kicad-cli 8.0.6 — тоже.",
              "- KiCad 8 для проверок установлен из бинарного кэша Nix (канал nixos-24.11, "
              "`kicad-small` 8.0.6) в отдельный профиль: `nix-env -p "
              "/nix/var/nix/profiles/kicad8 -f https://channels.nixos.org/nixos-24.11/"
              "nixexprs.tar.xz -iA kicad-small`, ссылка `/usr/local/bin/kicad-cli8`; тесты "
              "находят его по `KICAD8_CLI` или `kicad-cli8` в PATH.",
              "- Файлы KiCad 10-dev (`version 20260206`, фикстуры kicad10dev) kicad-cli 9 и 8 не "
              "читают — это ожидаемо (формат новее), они проверяются round-trip-тестами.",
              "- Открытые и сохранённые корпуса сохраняют свой формат: файлы форматов KiCad 5–8 "
              "после записи Программой открывают и KiCad 8, и KiCad 9, файл формата KiCad 9 — "
              "KiCad 9 (как и исходный). Новые корпуса по умолчанию создаются в формате KiCad 9; "
              "для KiCad 8 — формат KiCad 8: "
              "`kicadfp gen … --kicad 8`, `kicadfp convert … --kicad 8`, "
              "`generators.target_version(8)`, `Footprint.new(name, version=20240108)`, поле "
              "«Формат файла» в диалоге «Создать типовой корпус». Пустой корпус из меню "
              "«Создать корпус…» создаётся в формате KiCad 9 (выбора формата там нет).",
              "- При пересохранении KiCad нормализует файл сам (это не расхождение kicadfp): "
              "стирает номер у неметаллизированных отверстий и апертур, добавляет пустые "
              "служебные поля, пишет `%R`/`%V` как `${REFERENCE}`/`${VALUE}`, упорядочивает "
              "элементы; сравнение это учитывает (`tests/kicad_cli_tools.py`).",
              ""]
    if collect_errors:
        lines += ["**Ошибки сбора тестов:**", "", *[f"- {e}" for e in collect_errors], ""]
    if suite:
        lines += ["## 8. Полный набор автоматических тестов", "", suite, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def run_full_suite(env: dict[str, str]) -> str:
    t0 = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider"],
                           capture_output=True, text=True, cwd=REPO, env=env, timeout=3600)
    except subprocess.TimeoutExpired:
        return "Полный набор не завершился за 60 мин."
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:] or ["?"]
    return (f"`python -m pytest` (все тесты, KICAD_CLI/KICAD8_CLI заданы): {tail[0]} — код "
            f"возврата {r.returncode}, {time.perf_counter() - t0:.0f} с.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Приёмочные испытания kicadfp и отчёт в Markdown")
    ap.add_argument("--full", action="store_true",
                    help="все файлы фикстур (KICADFP_CLI_STEP=1) и библиотеки KiCad 8 из "
                         ".cache/kfp/v8.0.0")
    ap.add_argument("--kicad-cli", help="kicad-cli KiCad 9+ (по умолчанию KICAD_CLI / PATH)")
    ap.add_argument("--kicad8-cli", help="kicad-cli KiCad 8 (по умолчанию KICAD8_CLI / kicad-cli8)")
    ap.add_argument("--kicad8-library", help="каталог библиотек KiCad 8 для расширенного Г.1")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="файл отчёта")
    ap.add_argument("--full-suite", action="store_true",
                    help="дополнительно запустить весь набор тестов и добавить итог в отчёт")
    ap.add_argument("--print", action="store_true", dest="print_report",
                    help="напечатать отчёт в stdout (кроме записи в файл)")
    args = ap.parse_args(argv)

    os.chdir(REPO)
    sys.path.insert(0, str(REPO))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    kicad9 = find_cli(args.kicad_cli, "KICAD_CLI", "kicad-cli")
    kicad8 = find_cli(args.kicad8_cli, "KICAD8_CLI", "kicad-cli8")
    for key, value in (("KICAD_CLI", kicad9), ("KICAD8_CLI", kicad8)):
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    lib8: Path | None = None
    if args.kicad8_library:
        lib8 = Path(args.kicad8_library).resolve()
    elif args.full and KICAD8_CACHE.is_dir():
        lib8 = KICAD8_CACHE
    if lib8 is not None:
        os.environ["KICADFP_KICAD8_LIBRARY"] = str(lib8)
    if args.full:
        os.environ["KICADFP_CLI_STEP"] = "1"

    rc, col, total = run_pytest(TARGETS)
    if not col.results:
        print("не запущено ни одного теста", file=sys.stderr)
        return 2
    R = Results(col)
    env = environment(kicad9, kicad8, lib8)
    suite = run_full_suite(dict(os.environ)) if args.full_suite else None
    text = build_report(R, env, args, total, col.errors, suite)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    if args.print_report:
        print(text)
    failed = [r.nodeid for r in R.all if r.outcome == "failed"]
    print(f"\nотчёт: {_rel(out)}; тестов {len(R.all)}, не пройдено {len(failed)}, "
          f"пропущено {sum(r.outcome == 'skipped' for r in R.all)}; {total:.0f} с")
    for f in failed:
        print(f"  НЕ ПРОЙДЕН: {f}")
    return 1 if failed or rc not in (0, 5) else 0


if __name__ == "__main__":
    sys.exit(main())
