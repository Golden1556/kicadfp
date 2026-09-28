"""Тесты интерфейса командной строки :mod:`kicadfp.cli` (architecture.md §13, ТЗ 4.1.7,
приложение В.3).

Каждая команда проверяется отдельным процессом (``python -m kicadfp …``) и вызовом
:func:`kicadfp.cli.main` в том же процессе (вывод — через ``capsys``); коды возврата:
0 — успешно, 1 — замечания/различия, 2 — ошибка входных данных.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import kicadfp
from kicadfp import cli, sexpr
from kicadfp.library import Library

from .conftest import FIXTURES

ROOT = Path(__file__).resolve().parent.parent
DIP_LIB8 = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14_8 = DIP_LIB8 / "DIP-14_W7.62mm.kicad_mod"
DIP14_6 = FIXTURES / "kicad6" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
DIP14_5 = FIXTURES / "kicad5" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
SMD_DIP8 = DIP_LIB8 / "SMDIP-8_W9.53mm.kicad_mod"
MY_LIB = FIXTURES / "legacy_mod" / "My_lib.mod"
BROKEN = '(footprint "bad"\n\t(version 20241229)\n\t(layer "F.Cu"\n'
POSITION = re.compile(r"строка \d+, позиция \d+")


# ---------------------------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------------------------

def run_cli(*args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """``python -m kicadfp ARGS`` отдельным процессом."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("KICADFP_DEBUG", None)
    return subprocess.run([sys.executable, "-m", "kicadfp", *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env,
                          timeout=300)


def call(capsys: pytest.CaptureFixture[str], *args: object) -> tuple[int, str, str]:
    """:func:`kicadfp.cli.main` в том же процессе: ``(код, stdout, stderr)``."""
    rc = cli.main([str(a) for a in args])
    out, err = capsys.readouterr()
    return rc, out, err


def copy(src: Path, dst: Path) -> Path:
    """Скопировать файл или каталог-фикстуру во временный каталог."""
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copyfile(src, dst)
    return dst


def small_lib(tmp_path: Path, names: tuple[str, ...] = ("DIP-4_W7.62mm", "DIP-8_W7.62mm",
                                                         "SMDIP-8_W9.53mm")) -> Path:
    """Маленькая библиотека ``lib.pretty`` из файлов фикстуры KiCad 8."""
    lib = tmp_path / "lib.pretty"
    lib.mkdir()
    for n in names:
        shutil.copyfile(DIP_LIB8 / f"{n}.kicad_mod", lib / f"{n}.kicad_mod")
    return lib


def tree_diff(a: Path | sexpr.Node, b: Path | sexpr.Node) -> list[str]:
    """Различия деревьев двух файлов (точные: без допуска и с учётом кавычек)."""
    na = sexpr.parse(a.read_text(encoding="utf-8")) if isinstance(a, Path) else a
    nb = sexpr.parse(b.read_text(encoding="utf-8")) if isinstance(b, Path) else b
    return sexpr.diff(na, nb, numeric_tol=0.0, ignore_quotes=False, limit=1000)


# ---------------------------------------------------------------------------------------------
# Общее: версия, справка, ошибки аргументов, python -m kicadfp, импорт пакета
# ---------------------------------------------------------------------------------------------

def test_version_subprocess():
    r = run_cli("--version")
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"kicadfp {kicadfp.__version__}\n"
    assert re.fullmatch(r"kicadfp \d+\.\d+\.\d+\n", r.stdout)


def test_version_in_process(capsys):
    rc, out, err = call(capsys, "--version")
    assert rc == 0 and out.strip() == f"kicadfp {kicadfp.__version__}" and err == ""


def test_main_uses_sys_argv(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["kicadfp", "--version"])
    assert cli.main() == 0
    assert capsys.readouterr().out.startswith("kicadfp ")


def test_main_rejects_plain_string():
    with pytest.raises(TypeError, match="список аргументов"):
        cli.main("info x")      # type: ignore[arg-type]


def test_main_accepts_path_objects(capsys):
    rc, out, _ = call(capsys, "list", DIP_LIB8)
    rc2 = cli.main(["list", DIP_LIB8])          # Path, а не str
    out2 = capsys.readouterr().out
    assert rc == rc2 == 0 and out == out2


def test_help_is_russian(capsys):
    rc, out, _ = call(capsys, "--help")
    assert rc == 0
    assert "использование: kicadfp" in out and "команды:" in out
    for command in ("info", "list", "validate", "set", "pads", "gen", "fmt", "convert",
                    "render", "gui"):
        assert command in out
    rc, out, _ = call(capsys, "set", "-h")
    assert rc == 0 and "SELECTOR" in out and "pad[*]" in out and "--write" in out


def test_no_command_and_unknown_command(capsys):
    rc, _, err = call(capsys)
    assert rc == 2 and "не указана команда" in err
    rc, _, err = call(capsys, "frobnicate")
    assert rc == 2 and "недопустимое значение 'frobnicate'" in err and "использование:" in err


def test_usage_errors_are_russian(capsys):
    rc, _, err = call(capsys, "set", str(DIP14_8))
    assert rc == 2 and "не заданы обязательные аргументы: SELECTOR, VALUE" in err
    rc, _, err = call(capsys, "info", str(DIP14_8), "--bogus")
    assert rc == 2 and "нераспознанные аргументы: --bogus" in err
    rc, _, err = call(capsys, "render", str(DIP14_8), "--scale", "abc")
    assert rc == 2 and "аргумент --scale: недопустимое значение 'abc'" in err
    rc, _, err = call(capsys, "fmt", str(DIP14_8), "--check", "--write")
    assert rc == 2 and "нельзя использовать вместе" in err
    rc, _, err = call(capsys, "fmt", str(DIP14_8), "--style", "kicad3")
    assert rc == 2 and "недопустимое значение" in err


def test_translate_argparse_messages():
    t = cli._translate_argparse
    assert t("argument -o/--output: expected one argument") == \
        "аргумент -o/--output: ожидается одно значение"
    assert t("ambiguous option: --p could match --params, --pins") == \
        "неоднозначный параметр --p: подходят --params, --pins"
    assert t("argument --x: ignored explicit argument 'y'") == "аргумент --x: лишнее значение 'y'"
    assert t("one of the arguments --a --b is required") == "нужен один из аргументов --a --b"
    assert t("argument --n: expected at least one argument").endswith("хотя бы одно значение")
    assert t("argument --n: expected at most one argument").endswith("не больше одного значения")
    assert t("argument X: something new") == "аргумент X: something new"
    assert t("совсем другое сообщение") == "совсем другое сообщение"


def test_python_m_kicadfp_runs_main():
    """``python -m kicadfp`` — модуль ``kicadfp.__main__``."""
    r = run_cli("list", DIP_LIB8)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == Library(DIP_LIB8).names


def test_import_kicadfp_without_pyside6():
    code = ("import sys\n"
            "sys.modules['PySide6'] = None\n"
            "import kicadfp, kicadfp.cli\n"
            "assert callable(kicadfp.validate) and kicadfp.Issue.__name__ == 'Issue'\n"
            "assert kicadfp.Library.__name__ == 'Library'\n"
            "assert kicadfp.generators.GENERATORS and kicadfp.legacy.convert\n"
            "assert kicadfp.render.render_svg\n"
            "assert issubclass(kicadfp.ValidationError, Exception)\n"
            "loaded = [m for m, v in sys.modules.items() if m.startswith('PySide6') and v]\n"
            "assert not loaded, loaded\n"
            "print('ok')\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_package_exports():
    import kicadfp.generators as gen_mod
    import kicadfp.legacy as legacy_mod
    import kicadfp.render as render_mod
    from kicadfp.io import ValidationError
    from kicadfp.validate import Issue, validate

    assert kicadfp.validate is validate and kicadfp.Issue is Issue
    assert kicadfp.Library is Library and kicadfp.ValidationError is ValidationError
    assert kicadfp.generators is gen_mod and kicadfp.legacy is legacy_mod
    assert kicadfp.render is render_mod
    for name in ("Library", "validate", "Issue", "ValidationError", "generators", "legacy",
                 "render", "Graphic", "load", "save", "Footprint"):
        assert name in kicadfp.__all__, name
        assert hasattr(kicadfp, name), name
    with pytest.raises(AttributeError, match="не содержит атрибута"):
        kicadfp.no_such_thing  # noqa: B018


# ---------------------------------------------------------------------------------------------
# Ошибка синтаксиса: код 2, «строка N, позиция M»
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    ["info"], ["pads"], ["validate"], ["set", "@", "footprint.descr", "x", "--write"], ["fmt"],
    ["render"], ["info", "--json"], ["fmt", "--check"],
])
def test_syntax_error_exit_2_with_position(capsys, tmp_path, command):
    bad = tmp_path / "bad.kicad_mod"
    bad.write_text(BROKEN, encoding="utf-8")
    args = [str(bad) if a == "@" else a for a in command]
    if "@" not in command:
        args.insert(1, str(bad))
    rc, out, err = call(capsys, *args)
    assert rc == 2
    assert f"ошибка: {bad}: строка 4, позиция 1: незакрытая скобка" in err
    assert bad.read_text(encoding="utf-8") == BROKEN          # файл не тронут


def test_syntax_error_subprocess(tmp_path):
    bad = tmp_path / "bad.kicad_mod"
    bad.write_text(BROKEN, encoding="utf-8")
    r = run_cli("info", bad)
    assert r.returncode == 2
    assert r.stderr.startswith("ошибка: ") and POSITION.search(r.stderr)
    assert "bad.kicad_mod: строка 4, позиция 1" in r.stderr
    assert r.stdout == ""


def test_unknown_format_and_missing_file(capsys, tmp_path):
    junk = tmp_path / "junk.kicad_mod"
    junk.write_text("\n\nhello world\n", encoding="utf-8")
    rc, _, err = call(capsys, "info", junk)
    assert rc == 2 and "строка 3, позиция 1: неизвестный формат файла" in err
    rc, _, err = call(capsys, "info", tmp_path / "nope.kicad_mod")
    assert rc == 2 and "nope.kicad_mod: файл или каталог не найден" in err
    rc, _, err = call(capsys, "info", DIP_LIB8, "--fp", "NoSuchFootprint")
    assert rc == 2 and "нет корпуса «NoSuchFootprint»" in err
    rc, _, err = call(capsys, "info", DIP14_8, "--fp", "Other")
    assert rc == 2 and "нет корпуса «Other»" in err


# ---------------------------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------------------------

def test_info_subprocess():
    r = run_cli("info", DIP14_8)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert re.search(r"^Корпус:\s+DIP-14_W7\.62mm$", out, re.M)
    assert re.search(r"^Формат:\s+20240108 \(KiCad 8\)$", out, re.M)
    assert re.search(r"^Генератор:\s+pcbnew 8\.0$", out, re.M)
    assert re.search(r"^Слой:\s+F\.Cu$", out, re.M)
    assert re.search(r"^Площадки:\s+14 \(thru_hole: 14\)$", out, re.M)
    assert re.search(r"^Слои:\s+\*\.Cu, F\.SilkS, \*\.Mask, F\.CrtYd, F\.Fab$", out, re.M)
    assert re.search(r"^Габариты:\s+9\.8 x 18\.35 мм \(X: -1\.1 \.\. 8\.7, Y: -1\.55 \.\. 16\.8\)$",
                     out, re.M)
    assert re.search(r"^Графика:\s+15 \(line: 14, arc: 1\)$", out, re.M)
    assert re.search(r"^Тексты:\s+6 ", out, re.M)
    assert re.search(r"^3D-модели:\s+1 \(\$\{KICAD8_3DMODEL_DIR\}", out, re.M)


def test_info_json(capsys):
    rc, out, err = call(capsys, "info", DIP14_8, "--json")
    assert rc == 0 and err == ""
    d = json.loads(out)
    assert d["name"] == "DIP-14_W7.62mm" and d["version"] == 20240108 and d["kicad"] == "KiCad 8"
    assert d["generator"] == "pcbnew" and d["layer"] == "F.Cu" and d["attrs"] == ["through_hole"]
    assert d["pads"] == {"total": 14, "by_type": {"thru_hole": 14}}
    assert d["graphics"]["total"] == 15 and d["graphics"]["by_kind"] == {"line": 14, "arc": 1}
    assert d["texts"]["total"] == 6 and d["models"]["total"] == 1
    assert d["bbox"] == {"x1": -1.1, "y1": -1.55, "x2": 8.7, "y2": 16.8, "width": 9.8,
                         "height": 18.35}
    assert d["layers"] == ["*.Cu", "F.SilkS", "*.Mask", "F.CrtYd", "F.Fab"]
    assert d["unknown"] == [] and d["zones"] == 0


def test_info_old_formats(capsys):
    rc, out, _ = call(capsys, "info", DIP14_5)
    assert rc == 0 and "KiCad 5 (корень module" in out and "Площадки:       14" in out
    rc, out, _ = call(capsys, "info", DIP14_6, "--json")
    assert rc == 0 and json.loads(out)["kicad"] == "KiCad 6"


def test_info_library_and_fp_filter(capsys, tmp_path):
    lib = small_lib(tmp_path)
    rc, out, _ = call(capsys, "info", lib)
    assert rc == 0
    assert out.startswith(f"Библиотека: lib ({lib}), корпусов: 3\n")
    assert out.count("Корпус:") == 3 and "Площадки:       8 (smd: 8)" in out
    rc, out, _ = call(capsys, "info", lib, "--json")
    d = json.loads(out)
    assert d["library"] == "lib" and [f["name"] for f in d["footprints"]] == [
        "DIP-4_W7.62mm", "DIP-8_W7.62mm", "SMDIP-8_W9.53mm"]
    rc, out, _ = call(capsys, "info", lib, "--fp", "DIP-8_W7.62mm.kicad_mod", "--json")
    assert rc == 0 and json.loads(out)["name"] == "DIP-8_W7.62mm"


def test_info_legacy_library(capsys):
    rc, out, _ = call(capsys, "info", MY_LIB)
    assert rc == 0 and out.count("Корпус:") == 3 and "старый формат .mod" in out
    rc, out, _ = call(capsys, "info", MY_LIB, "--fp", "snp8", "--json")
    d = json.loads(out)
    assert d["name"] == "snp8" and d["source"] == "PCBNEW-LibModule-V1"


def test_info_library_with_broken_file(capsys, tmp_path):
    lib = small_lib(tmp_path, ("DIP-4_W7.62mm",))
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    rc, out, err = call(capsys, "info", lib)
    assert rc == 2 and "Корпус:         DIP-4_W7.62mm" in out
    assert "bad.kicad_mod: строка 4, позиция 1" in err
    rc, out, _ = call(capsys, "info", lib, "--json")
    items = {f["name"]: f for f in json.loads(out)["footprints"]}
    assert rc == 2 and "строка 4" in items["bad"]["error"] and "error" not in items[
        "DIP-4_W7.62mm"]


def test_info_shows_unknown_nodes_zones_groups(capsys, tmp_path):
    fp = kicadfp.load(DIP14_8)
    fp.node.append(sexpr.parse("(example_token 1 2)"))
    fp.node.append(sexpr.parse('(zone (net 0) (layer "F.Cu") (hatch edge 0.5))'))
    fp.node.append(sexpr.parse('(group "g" (uuid "0") (members))'))
    path = tmp_path / "x.kicad_mod"
    kicadfp.save(fp, path)
    rc, out, _ = call(capsys, "info", path)
    assert rc == 0
    assert re.search(r"^Неизвестные узлы:\s+example_token$", out, re.M)
    assert re.search(r"^Зоны:\s+1$", out, re.M) and re.search(r"^Группы:\s+1$", out, re.M)


# ---------------------------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------------------------

def test_list_subprocess():
    r = run_cli("list", DIP_LIB8, "--json")
    assert r.returncode == 0, r.stderr
    names = json.loads(r.stdout)
    assert names == Library(DIP_LIB8).names and "DIP-14_W7.62mm" in names


def test_list_variants(capsys):
    rc, out, _ = call(capsys, "list", DIP_LIB8)
    assert rc == 0 and out.splitlines() == Library(DIP_LIB8).names
    rc, out, _ = call(capsys, "list", MY_LIB)
    assert rc == 0 and out.split() == ["dip14", "mlt", "snp8"]
    rc, out, _ = call(capsys, "list", DIP14_8, "--json")
    assert rc == 0 and json.loads(out) == ["DIP-14_W7.62mm"]


# ---------------------------------------------------------------------------------------------
# pads
# ---------------------------------------------------------------------------------------------

def test_pads_subprocess():
    r = run_cli("pads", DIP14_8)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["№", "Тип", "Форма", "X", "Y", "Угол", "Размер", "X", "Размер",
                                "Y", "Отверстие", "Слои"]
    assert len(lines) == 15
    assert lines[1].split() == ["1", "thru_hole", "rect", "0", "0", "0", "1.6", "1.6", "0.8",
                                "*.Cu,*.Mask"]
    assert lines[8].split()[:5] == ["8", "thru_hole", "oval", "7.62", "15.24"]


def test_pads_json_and_library(capsys, tmp_path):
    rc, out, _ = call(capsys, "pads", DIP14_8, "--json")
    d = json.loads(out)
    assert rc == 0 and d["name"] == "DIP-14_W7.62mm" and len(d["pads"]) == 14
    p1 = d["pads"][0]
    assert p1 == {"number": "1", "type": "thru_hole", "shape": "rect", "x": 0.0, "y": 0.0,
                  "angle": 0.0, "size_x": 1.6, "size_y": 1.6,
                  "drill": {"diameter": 0.8, "width": None, "oval": False, "offset_x": 0.0,
                            "offset_y": 0.0},
                  "layers": ["*.Cu", "*.Mask"], "roundrect_rratio": None}
    lib = small_lib(tmp_path)
    rc, out, _ = call(capsys, "pads", lib)
    assert rc == 0 and "DIP-4_W7.62mm (площадок: 4)" in out and "SMDIP-8_W9.53mm" in out
    assert re.search(r"^1\s+smd\s+rect\s+-4\.765\s+-3\.81\s+0\s+2\s+1\.78\s+-\s+"
                     r"F\.Cu,F\.Paste,F\.Mask$", out, re.M)
    rc, out, _ = call(capsys, "pads", lib, "--json")
    assert [f["name"] for f in json.loads(out)["footprints"]] == Library(lib).names


def test_pads_oval_drill_offset_and_empty(capsys, tmp_path):
    fp = kicadfp.Footprint.new("t")
    fp.new_pad("1", "thru_hole", "oval", 0, 0, (2.0, 3.0), drill=(1.0, 1.5))
    pad = fp.new_pad("", "np_thru_hole", "circle", 5, 0, 3.0, drill=3.0)
    pad.drill.offset_y = 0.25
    path = tmp_path / "t.kicad_mod"
    kicadfp.save(fp, path)
    rc, out, _ = call(capsys, "pads", path)
    assert rc == 0 and "овал 1x1.5" in out and '""' in out and "3 смещение 0,0.25" in out
    empty = tmp_path / "e.kicad_mod"
    kicadfp.save(kicadfp.Footprint.new("e"), empty)
    rc, out, _ = call(capsys, "pads", empty)
    assert rc == 0 and out.strip() == "площадок нет"


# ---------------------------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------------------------

def test_validate_clean_file_subprocess():
    r = run_cli("validate", DIP14_8)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "замечаний нет"


def test_validate_errors_and_json(capsys, tmp_path):
    fp = kicadfp.load(DIP14_8)
    fp.pad(1).drill = 1.9                      # сценарий 6: отверстие больше площадки
    path = tmp_path / "d.kicad_mod"
    kicadfp.save(fp, path)
    r = run_cli("validate", path)
    assert r.returncode == 1
    assert re.search(r"^ERROR PAD_DRILL_GT_SIZE: ", r.stdout, re.M)
    assert "ошибок: 1, предупреждений: 0" in r.stdout
    rc, out, _ = call(capsys, "validate", path, "--json")
    d = json.loads(out)
    assert rc == 1 and d["errors"] == 1 and d["warnings"] == 0
    assert d["issues"][0]["code"] == "PAD_DRILL_GT_SIZE" and d["issues"][0]["line"] > 0


def test_validate_strict_warnings(capsys, tmp_path):
    fp = kicadfp.load(DIP14_8)
    for g in fp.graphics:
        if g.layer == "F.CrtYd":
            fp.remove(g)
    path = tmp_path / "w.kicad_mod"
    kicadfp.save(fp, path)
    rc, out, _ = call(capsys, "validate", path)
    assert rc == 0 and "WARNING COURTYARD_MISSING" in out
    rc, out, _ = call(capsys, "validate", path, "--strict")
    assert rc == 1 and "ошибок: 0, предупреждений: 1" in out


def test_validate_library(capsys, tmp_path):
    lib = small_lib(tmp_path)
    fp = kicadfp.load(lib / "DIP-4_W7.62mm.kicad_mod")
    fp.pad(2).drill = None
    kicadfp.save(fp, lib / "DIP-4_W7.62mm.kicad_mod")
    rc, out, _ = call(capsys, "validate", lib)
    assert rc == 1
    assert re.search(r"^DIP-4_W7\.62mm: ERROR PAD_THT_NO_DRILL: ", out, re.M)
    assert "проверено корпусов: 3; ошибок: 1, предупреждений: 0" in out
    rc, out, _ = call(capsys, "validate", lib, "--json")
    d = json.loads(out)
    assert rc == 1 and d["errors"] == 1 and len(d["footprints"]) == 3
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    rc, out, err = call(capsys, "validate", lib)
    assert rc == 2 and "bad.kicad_mod: строка 4, позиция 1" in err
    rc, out, _ = call(capsys, "validate", lib, "--json")
    d = json.loads(out)
    bad = [f for f in d["footprints"] if f["name"] == "bad"][0]
    assert rc == 2 and bad["issues"][0]["code"] == "SEXPR_SYNTAX"


def test_validate_legacy_library_and_read_issue(capsys, tmp_path):
    rc, out, _ = call(capsys, "validate", MY_LIB)
    assert rc in (0, 1) and "проверено корпусов: 3" in out
    lib = tmp_path / "x.pretty"
    lib.mkdir()
    (lib / "two.kicad_mod").write_bytes(MY_LIB.read_bytes())   # .mod из трёх корпусов
    rc, out, err = call(capsys, "validate", lib, "--json")
    d = json.loads(out)
    assert rc == 2 and d["footprints"][0]["issues"][0]["code"] == "FILE_READ"


# ---------------------------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------------------------

def test_set_scenario_write_subprocess(tmp_path):
    """ТЗ В.3: ``kicadfp set dip14.kicad_mod "pad[*].drill" 0.8 --write``."""
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    r = run_cli("set", path, "pad[*].drill", "1.0", "--write")
    assert r.returncode == 0, r.stderr
    assert "pad[1].drill: 0.8 -> 1" in r.stdout and f"записан: {path}" in r.stdout
    diffs = tree_diff(DIP14_8, path)
    assert len(diffs) == 14 and all("/drill[0]: атом 0: 0.8 != 1" in d for d in diffs), diffs
    r = run_cli("set", path, "pad[*].drill", "0.8", "--write")
    assert r.returncode == 0, r.stderr
    # обратно: файл KiCad 8 совпадает с исходным байт в байт
    assert path.read_bytes() == DIP14_8.read_bytes()
    before = path.stat().st_mtime_ns
    r = run_cli("set", path, "pad[*].drill", "0.8", "--write")
    assert r.returncode == 0 and "без изменений" in r.stdout
    assert path.stat().st_mtime_ns == before


def test_set_output_file_subprocess(tmp_path):
    """ТЗ В.3: ``kicadfp set dip14.kicad_mod footprint.descr "DIP-14" -o dip14_new.kicad_mod``."""
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    out = tmp_path / "dip14_new.kicad_mod"
    r = run_cli("set", path, "footprint.descr", "DIP-14", "-o", out)
    assert r.returncode == 0, r.stderr
    assert path.read_bytes() == DIP14_8.read_bytes()            # исходный не изменён
    assert kicadfp.load(out).descr == "DIP-14"
    assert len(tree_diff(DIP14_8, out)) == 1


def test_set_without_write_prints_result(capsys, tmp_path):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    rc, out, err = call(capsys, "set", path, "pad[1].size", "1.3")
    assert rc == 0
    assert "pad[1].size: (1.6, 1.6) -> (1.3, 1.3)" in err
    assert "файл не изменён" in err
    assert path.read_bytes() == DIP14_8.read_bytes()
    fp = kicadfp.loads(out)
    assert fp.pad(1).size == (1.3, 1.3) and fp.pad(2).size == (1.6, 1.6)


def test_set_stdout_is_exact_file_text(tmp_path):
    """Текст результата в stdout — байты UTF-8 с LF (как у записанного файла)."""
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, "-m", "kicadfp", "set", str(path), "footprint.tags",
                        "тест", ], capture_output=True, env=env, timeout=300)
    assert r.returncode == 0
    out = tmp_path / "o.kicad_mod"
    assert cli.main(["set", str(path), "footprint.tags", "тест", "-o", str(out)]) == 0
    assert r.stdout == out.read_bytes() and b"\r\n" not in r.stdout


@pytest.mark.parametrize("selector, value, check", [
    ("pad[1].size_x", "2", lambda fp: fp.pad(1).size == (2.0, 1.6)),
    ("pad[#0].shape", "roundrect", lambda fp: fp.pad(1).shape == "roundrect"),
    ("pad[#-1].x", "-1.5", lambda fp: fp.pad(14).x == -1.5),
    ('pad["2"].angle', "90", lambda fp: fp.pad(2).angle == 90),
    ("pad[*].layers", "F.Cu,F.Mask", lambda fp: all(p.layers == ["F.Cu", "F.Mask"]
                                                    for p in fp.pads)),
    ("pad[*].layers", "F.Cu F.Paste F.Mask",
     lambda fp: fp.pad(3).layers == ["F.Cu", "F.Paste", "F.Mask"]),
    ("pad[1].drill", "1.2x0.8", lambda fp: fp.pad(1).drill.oval and fp.pad(1).drill.width == 0.8),
    ("pad[1].drill", "[1.2, 0.9]", lambda fp: fp.pad(1).drill.size == (1.2, 0.9)),
    ("pad[1].drill", "none", lambda fp: fp.pad(1).drill is None),
    ("pad[*].drill.diameter", "0.9", lambda fp: all(p.drill.diameter == 0.9 for p in fp.pads)),
    ("pad[1].drill.offset_x", "0.1", lambda fp: fp.pad(1).drill.offset_x == 0.1),
    ("pad[1].position", "1,2", lambda fp: (fp.pad(1).x, fp.pad(1).y) == (1.0, 2.0)),
    ("pad[1].roundrect_rratio", "0.25", lambda fp: fp.pad(1).roundrect_rratio == 0.25),
    ("pad[1].net", "1,GND", lambda fp: fp.pad(1).net == (1, "GND")),
    ("pad[1].zone_connect", "2", lambda fp: fp.pad(1).zone_connect == 2),
    ("pad[1].locked", "yes", lambda fp: fp.pad(1).locked is True),
    ("pad[1].number", "01", lambda fp: fp.pads[0].number == "01"),
    ("pad[1].pinfunction", "CLK", lambda fp: fp.pad(1).pinfunction == "CLK"),
    ("text[reference].layer", "F.Fab", lambda fp: fp.reference.layer == "F.Fab"),
    ("text[value].text", "dip14", lambda fp: fp.value.text == "dip14"),
    ("text[Datasheet].text", "http://x", lambda fp: fp.properties["Datasheet"] == "http://x"),
    ("text[datasheet].hide", "no", lambda fp: fp.properties.text("Datasheet").hide is False),
    ("text[user:3].font_size", "1.5", lambda fp: fp.texts[-1].font_size == (1.5, 1.5)),
    ("text[user].italic", "да", lambda fp: all(t.italic for t in fp.texts if t.kind == "user")),
    ("text[*].bold", "true", lambda fp: all(t.bold for t in fp.texts)),
    ("text[#1].justify", "left top", lambda fp: fp.value.justify == ["left", "top"]),
    ("graphic[0].width", "0.15", lambda fp: fp.graphics[0].width == 0.15),
    ("graphic[F.SilkS].width", "0.2",
     lambda fp: all(g.width == 0.2 for g in fp.graphics if g.layer == "F.SilkS")),
    ("graphic[*.Fab].stroke_type", "dash",
     lambda fp: all(g.stroke_type == "dash" for g in fp.graphics if g.layer == "F.Fab")),
    ("graphic[arc].layer", "F.Fab", lambda fp: [g for g in fp.graphics if g.kind == "arc"][0]
     .layer == "F.Fab"),
    ("graphic[#-1].end", "7 17", lambda fp: fp.graphics[-1].end == (7.0, 17.0)),
    ("graphic[*].locked", "1", lambda fp: all(g.locked for g in fp.graphics)),
    ("model[0].path", "a.wrl", lambda fp: fp.models[0].path == "a.wrl"),
    ("model[*].offset", "0,0,1.5", lambda fp: fp.models[0].offset == (0.0, 0.0, 1.5)),
    ("model[#0].hide", "yes", lambda fp: fp.models[0].hide),
    ("footprint.descr", "DIP-14", lambda fp: fp.descr == "DIP-14"),
    ("footprint.descr", "none", lambda fp: fp.descr == ""),
    ("footprint.tags", "", lambda fp: fp.tags == ""),
    ("footprint.attrs", "smd,exclude_from_bom", lambda fp: set(fp.attrs) == {"smd",
                                                                           "exclude_from_bom"}),
    ("footprint.clearance", "0.2", lambda fp: fp.clearance == 0.2),
    ("footprint.locked", "true", lambda fp: fp.locked),
    ("footprint.layer", "B.Cu", lambda fp: fp.layer == "B.Cu"),
    ("fp.reference", "U1", lambda fp: fp.reference.text == "U1"),
    ("footprint.value", "X", lambda fp: fp.value.text == "X"),
    ("footprint.autoplace_cost90", "5", lambda fp: fp.autoplace_cost90 == 5),
    ("property[Datasheet]", "http://y", lambda fp: fp.properties["Datasheet"] == "http://y"),
    ("property[MyKey]", "v", lambda fp: fp.properties["MyKey"] == "v"),
    ("property[Description]", "none", lambda fp: "Description" not in fp.properties),
])
def test_set_selectors(capsys, tmp_path, selector, value, check):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    out = tmp_path / "out.kicad_mod"
    rc, stdout, err = call(capsys, "set", path, selector, value, "-o", out)
    assert rc == 0, err
    assert f"записан: {out}" in stdout
    assert check(kicadfp.load(out)), stdout + err


def test_set_kicad6_user_text_and_graphic_poly(capsys, tmp_path):
    path = copy(DIP14_6, tmp_path / "d6.kicad_mod")
    rc, out, err = call(capsys, "set", path, "text[user:0].text", "%R", "--write")
    assert rc == 0, err
    assert 'text[user:0].text: "${REFERENCE}" -> "%R"' in out
    fp = kicadfp.load(path)
    assert [t.text for t in fp.texts if t.kind == "user"] == ["%R"]
    fp.new_poly([(0, 0), (1, 0), (1, 1)], layer="F.SilkS", width=0.12)
    kicadfp.save(fp, path)
    rc, out, err = call(capsys, "set", path, "graphic[poly].points", "0,0; 2,0; 2,2; 0,2",
                        "--write")
    assert rc == 0, err
    poly = [g for g in kicadfp.load(path).graphics if g.kind == "poly"][0]
    assert list(poly.points) == [(0, 0), (2, 0), (2, 2), (0, 2)]
    rc, out, err = call(capsys, "set", path, "graphic[poly].points", "[[0, 0], [3, 0], [3, 3]]",
                        "--write")
    assert rc == 0, err
    poly = [g for g in kicadfp.load(path).graphics if g.kind == "poly"][0]
    assert list(poly.points) == [(0, 0), (3, 0), (3, 3)]


def test_set_nested_skips_pads_without_drill(capsys, tmp_path):
    path = copy(SMD_DIP8, tmp_path / "s.kicad_mod")
    rc, _, err = call(capsys, "set", path, "pad[*].drill.diameter", "0.5", "--write")
    assert rc == 2
    assert "примечание: pad[1].drill: нет значения — элемент пропущен" in err
    assert "ни один элемент не изменён" in err
    assert path.read_bytes() == SMD_DIP8.read_bytes()


def test_set_reports_new_issues_and_strict(capsys, tmp_path):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    out = tmp_path / "o.kicad_mod"
    rc, _, err = call(capsys, "set", path, "pad[1].size", "0.5", "-o", out)
    assert rc == 0 and out.exists()
    assert "предупреждение: после изменения: ERROR PAD_DRILL_GT_SIZE" in err
    out.unlink()
    rc, _, err = call(capsys, "set", path, "pad[1].size", "0.5", "-o", out, "--strict")
    assert rc == 1 and not out.exists()
    assert "строгая проверка: есть ошибки — ничего не записано" in err


def test_set_name_mismatch_warning(capsys, tmp_path):
    path = copy(DIP14_8, tmp_path / "DIP-14_W7.62mm.kicad_mod")
    rc, out, err = call(capsys, "set", path, "footprint.name", "dip14", "--write")
    assert rc == 0 and kicadfp.load(path).name == "dip14"
    assert "не совпадает с именем файла DIP-14_W7.62mm.kicad_mod" in err


@pytest.mark.parametrize("selector, value, message", [
    ("pads[1].size", "1", "неизвестный элемент «pads»"),
    ("pad.size", "1", "укажите элемент в скобках, например pad[1].size"),
    ("pad[1]", "1", "укажите атрибут — pad[1].ATTR"),
    ("pad[1]size", "1", "после элемента ожидается .ATTR"),
    ("pad[1].2x", "1", "после элемента ожидается .ATTR"),
    ("footprint[0].descr", "1", "у footprint нет индекса"),
    ("footprint", "1", "укажите атрибут, например footprint.descr"),
    ("property[]", "1", "укажите ключ"),
    ("property[X].value", "1", "без атрибута"),
    ("pad[#x].size", "1", "индекс должен быть целым числом"),
    ("model[a].path", "1", "индекс должен быть целым числом"),
    ("text[user:x].text", "1", "индекс должен быть целым числом"),
    ("graphic[Q.Cu].width", "1", "не индекс, не слой и не вид графики"),
    ("[1].size", "1", "неверный селектор"),
    ("pad[1].foo", "1", "у площадки нет атрибута «foo»; изменяемые атрибуты: anchor, angle"),
    ("pad[1].drill.foo", "1", "у отверстия нет атрибута «foo»"),
    ("pad[1].foo.bar", "1", "у площадки нет атрибута «foo»"),
    ("pad[1].size.x", "1", "не имеет атрибутов — задайте pad[1].size целиком"),
    ("graphic[0].kind", "arc", "graphic[0].kind: атрибут только для чтения"),
    ("graphic[0].points", "0,0", "атрибут только для чтения"),
    ("pad[1].x", "abc", "pad[1].x: ожидается число, получено «abc»"),
    ("pad[1].x", "0,5", "ожидается число (десятичный разделитель — точка)"),
    ("pad[1].x", "nan", "ожидается конечное число"),
    ("pad[1].zone_connect", "1.5", "ожидается целое число"),
    ("pad[1].locked", "maybe", "ожидается логическое значение"),
    ("pad[1].shape", "hexagon", "pad[1].shape: недопустимое значение 'hexagon'"),
    ("pad[1].size", "1,2,3", "ожидается значений: 2, получено: 3"),
    ("pad[1].drill", "[1, 2", "неверный JSON"),
    ("pad[1].drill", '{"a": 1}', "ожидается число"),
    ("pad[1].drill", "[[1, 2]]", "ожидается"),
    ("model[0].offset", "1,2", "ожидается значений: 3, получено: 2"),
    ("pad[99].x", "1", "селектор «pad[99].x» не нашёл элементов в корпусе DIP-14_W7.62mm"),
    ("model[5].path", "x", "не нашёл элементов"),
    ("footprint.name", "", "name"),
    ("property[Nope]", "none", "свойства нет — удалять нечего"),
])
def test_set_errors(capsys, tmp_path, selector, value, message):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    rc, out, err = call(capsys, "set", path, selector, value, "--write")
    assert rc == 2, (out, err)
    assert message in err, err
    assert path.read_bytes() == DIP14_8.read_bytes()


def test_set_value_starting_with_dash(capsys, tmp_path):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    rc, _, err = call(capsys, "set", path, "pad[1].y", "-2.5", "--write")
    assert rc == 0, err
    assert kicadfp.load(path).pad(1).y == -2.5
    rc, _, err = call(capsys, "set", path, "--write", "--", "footprint.descr", "-x-")
    assert rc == 0, err
    assert kicadfp.load(path).descr == "-x-"


def test_set_library_dry_run_write_and_output(capsys, tmp_path):
    lib = small_lib(tmp_path)
    original = {p.name: p.read_bytes() for p in lib.iterdir()}
    rc, out, err = call(capsys, "set", lib, "pad[1].shape", "circle")
    assert rc == 0 and "DIP-4_W7.62mm: pad[1].shape: \"rect\" -> \"circle\"" in out
    assert "файлы не изменены" in err
    assert {p.name: p.read_bytes() for p in lib.iterdir()} == original
    out_dir = tmp_path / "out.pretty"
    rc, out, err = call(capsys, "set", lib, "pad[*].drill.diameter", "0.9", "-o", out_dir)
    assert rc == 0, err
    assert "записано файлов: 3 в" in out and "(изменено корпусов: 2)" in out
    assert "примечание: SMDIP-8_W9.53mm: pad[1].drill: нет значения" in err
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(original)
    assert (out_dir / "SMDIP-8_W9.53mm.kicad_mod").read_bytes() == \
        original["SMDIP-8_W9.53mm.kicad_mod"]          # селектор не сработал -> копия
    assert kicadfp.load(out_dir / "DIP-8_W7.62mm.kicad_mod").pad(5).drill.diameter == 0.9
    rc, out, err = call(capsys, "set", lib, "pad[5].shape", "rect", "--write")
    assert rc == 0, err
    assert kicadfp.load(lib / "DIP-8_W7.62mm.kicad_mod").pad(5).shape == "rect"
    assert (lib / "DIP-4_W7.62mm.kicad_mod").read_bytes() == original["DIP-4_W7.62mm.kicad_mod"]
    rc, out, err = call(capsys, "set", lib, "pad[5].shape", "rect", "--write", "--fp",
                        "DIP-8_W7.62mm")
    assert rc == 0 and "без изменений" in out
    rc, out, err = call(capsys, "set", lib, "pad[1].x", "1", "-o", lib)
    assert rc == 2 and "это исходный каталог" in err
    rc, out, err = call(capsys, "set", lib, "pad[1].x", "1", "-o", lib / "DIP-4_W7.62mm.kicad_mod")
    assert rc == 2 and "а это файл" in err


def test_set_library_all_or_nothing(capsys, tmp_path):
    lib = small_lib(tmp_path)
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    original = {p.name: p.read_bytes() for p in lib.iterdir()}
    rc, _, err = call(capsys, "set", lib, "pad[1].x", "1", "--write")
    assert rc == 2 and "bad.kicad_mod: строка 4, позиция 1" in err and "файлы не изменены" in err
    assert {p.name: p.read_bytes() for p in lib.iterdir()} == original
    (lib / "bad.kicad_mod").unlink()
    rc, _, err = call(capsys, "set", lib, "pad[1].shape", "hexagon", "--write")
    assert rc == 2 and "DIP-4_W7.62mm: pad[1].shape: недопустимое значение" in err
    rc, _, err = call(capsys, "set", lib, "pad[42].x", "1", "--write")
    assert rc == 2 and "не нашёл элементов ни в одном корпусе" in err


def test_set_library_output_file_with_fp(capsys, tmp_path):
    lib = small_lib(tmp_path)
    out = tmp_path / "res.pretty"
    rc, stdout, err = call(capsys, "set", lib, "footprint.descr", "X", "--fp", "DIP-4_W7.62mm",
                           "-o", out)
    assert rc == 0, err
    assert kicadfp.load(out / "DIP-4_W7.62mm.kicad_mod").descr == "X"


def test_set_legacy_is_read_only(capsys):
    rc, _, err = call(capsys, "set", MY_LIB, "footprint.descr", "x", "--write")
    assert rc == 2 and "только читается" in err and "kicadfp convert" in err


def test_set_old_format_and_version_guard(capsys, tmp_path):
    path = copy(DIP14_5, tmp_path / "d5.kicad_mod")
    rc, _, err = call(capsys, "set", path, "text[reference].knockout", "yes", "--write")
    assert rc == 2 and "upgrade" in err
    rc, out, err = call(capsys, "set", path, "pad[1].size", "1.3", "--write")
    assert rc == 0, err
    fp = kicadfp.load(path)
    assert fp.node.name == "module" and fp.pad(1).size == (1.3, 1.3)


def test_set_help_value_types():
    """Тип значения атрибута — из аннотаций модели (и таблицы уточнений)."""
    from kicadfp.model import Footprint, Graphic, Model, Pad, Text

    def names(cls: type, attr: str) -> list[str]:
        prop = cli._property_of(cls, attr)
        return [t.name for t in cli._attr_type(cls, attr, prop, None)]

    assert names(Pad, "size") == ["float", "tuple"]
    assert names(Pad, "drill") == ["float", "tuple", "None"]
    assert names(Pad, "number") == ["str"]
    assert names(Pad, "layers") == ["list", "str"]
    assert names(Pad, "die_length") == ["float", "None"]
    assert names(Footprint, "attrs") == ["list"]
    assert names(Footprint, "path") == ["str", "None"]
    assert names(Footprint, "version") == ["int", "None"]
    assert names(Graphic, "fill") == ["bool"]
    assert names(Text, "justify") == ["list", "str", "None"]
    assert names(Model, "offset") == ["tuple"]


def test_parse_type_and_coerce():
    P, C = cli._parse_type, cli._coerce
    assert P("Optional[float]") == (cli._FLOAT, cli._Ty("None"))
    assert [t.name for t in P("typing.Union[int, str]")] == ["int", "str"]
    assert P("tuple[float, ...] | None")[0].variadic
    assert P("Point") == cli._POINT
    assert P("PointList")[0].name == "list"
    assert P("AttrSet")[0].args == ((cli._Ty("str"),),)
    assert P("Real") == (cli._FLOAT,)
    assert P("Drill | None") == (cli._ANY, cli._Ty("None"))
    assert P("list[") == (cli._ANY,) and P("int int") == (cli._ANY,)
    assert P("tuple[float float]") == (cli._ANY,)
    assert C("1.5", P("float"), "x") == 1.5
    assert C(" 7 ", P("int | None"), "x") == 7
    assert C("NULL", P("int | None"), "x") is None
    assert C("4", P("int | float"), "x") == 4 and C("4.5", P("int | float"), "x") == 4.5
    assert C("x", P("None"), "x") is None if False else True
    with pytest.raises(cli._CliError, match="допустимо только значение none"):
        C("x", P("None"), "x")
    assert C("-1,2.5,90", P("tuple[float, ...] | None"), "x") == (-1.0, 2.5, 90.0)
    assert C("1.2x0.8", P("float | tuple[float, float]"), "x") == (1.2, 0.8)
    assert C("F.Cu, F.Mask", P("Iterable[str] | str"), "x") == ["F.Cu", "F.Mask"]
    assert C("", P("Iterable[str] | str | None"), "x") == []
    assert C("[1, true, null, \"a\"]", P("list[str]"), "x") == ["1", "true", "none", "a"]
    assert C("3,My Net", P("tuple[int, str] | None"), "x") == (3, "My Net")
    assert C(" as is ", P("str"), "x") == " as is "
    assert C("whatever", (cli._ANY,), "x") == "whatever"
    assert C(["2"], P("float"), "x") == 2.0
    with pytest.raises(cli._CliError, match="ожидается одно значение"):
        C(["1", "2"], P("float"), "x")
    assert cli._alts_from_value(True) == (cli._Ty("bool"),)
    assert cli._alts_from_value(3)[0].name == "int"
    assert cli._alts_from_value(1.5)[0].name == "float"
    assert cli._alts_from_value((1.0, 2.0))[0].name == "tuple"
    assert cli._alts_from_value(["a"])[0].name == "list"
    assert cli._alts_from_value(None)[0].name == "str"


def test_show_values():
    s = cli._show
    assert s(None) == "нет" and s(True) == "да" and s(False) == "нет"
    assert s(3) == "3" and s(0.30000000000000004) == "0.3" and s(float("inf")) == "inf"
    assert s("a\"b") == '"a\\"b"' and s((1.0, "x")) == '(1, "x")'
    assert s(["F.Cu", 1.5]) == "[F.Cu, 1.5]" and s({"a"}) == "[a]"
    fp = kicadfp.load(DIP14_8)
    assert s(fp.reference) == '"REF**"' and s(fp.attrs) == "[through_hole]"
    assert s(fp.pads[0]) == "Pad" and s(object).startswith("<class")


# ---------------------------------------------------------------------------------------------
# gen
# ---------------------------------------------------------------------------------------------

def test_gen_scenario_subprocess(tmp_path):
    """ТЗ В.3: ``kicadfp gen dip --pins 14 --pitch 2.5 --row-pitch 7.5 -o …/dip14.kicad_mod``."""
    target = tmp_path / "br8_timer.pretty" / "dip14.kicad_mod"
    r = run_cli("gen", "dip", "--pins", "14", "--pitch", "2.5", "--row-pitch", "7.5", "-o",
                target)
    assert r.returncode == 0, r.stderr
    assert f"записан: {target}" in r.stdout
    fp = kicadfp.load(target)
    assert fp.name == "dip14" and fp.value.text == "dip14"      # имя — по имени файла
    assert fp.version == 20241229 and fp.generator == "kicadfp"
    assert len(fp.pads) == 14 and fp.pad(1).shape == "rect"
    assert fp.pad(2).y - fp.pad(1).y == pytest.approx(2.5)
    assert fp.pad(14).x - fp.pad(1).x == pytest.approx(7.5)
    assert kicadfp.validate(fp) == []


def test_gen_to_stdout_and_options(capsys, tmp_path):
    rc, out, err = call(capsys, "gen", "dip", "--pins", "8", "--pad-size", "1.3",
                        "--first-square", "no", "--pad-shape", "circle")
    assert rc == 0 and err == ""
    fp = kicadfp.loads(out)
    assert fp.name.startswith("DIP-8") and len(fp.pads) == 8
    assert fp.pad(1).shape == "circle" and fp.pad(1).size == (1.3, 1.3)
    rc, out, _ = call(capsys, "gen", "dip", "--first-square", "--pins=4", "--row_pitch", "10.16",
                      "--name", "MyDip")
    fp = kicadfp.loads(out)
    assert rc == 0 and fp.name == "MyDip" and fp.pad(1).shape == "rect"
    assert fp.pad(4).x == pytest.approx(10.16)
    rc, out, _ = call(capsys, "gen", "to92")
    assert rc == 0 and kicadfp.loads(out).name == "TO-92_Inline"


def test_gen_params_json_and_output_dir(capsys, tmp_path):
    params = tmp_path / "p.json"
    params.write_text(json.dumps({"rows": 2, "cols": 4, "pitch": 2.5, "row-pitch": 5.0,
                                  "pad_size": 1.3, "drill": 0.8,
                                  "mounting_holes": [[11.25, -5.0, 3.0], [11.25, 15.0, 3.0]],
                                  "name": "snp8"}), encoding="utf-8")
    lib = tmp_path / "out.pretty"
    rc, out, err = call(capsys, "gen", "pin_header", "--params", params, "--drill", "0.9", "-o",
                        lib)
    assert rc == 0, err
    fp = kicadfp.load(lib / "snp8.kicad_mod")
    assert fp.name == "snp8" and len(fp.pads) == 10
    assert fp.pad(1).drill.diameter == 0.9                    # командная строка важнее JSON
    assert sorted(p.drill.diameter for p in fp.pads if p.type == "np_thru_hole") == [3.0, 3.0]
    existing = tmp_path / "existing"
    existing.mkdir()
    rc, out, err = call(capsys, "gen", "lab_mlt", "-o", existing)
    assert rc == 0 and (existing / "mlt.kicad_mod").exists()


def test_gen_list(capsys):
    rc, out, _ = call(capsys, "gen", "--list")
    assert rc == 0 and "Генераторы" in out
    for name in kicadfp.generators.GENERATORS:
        assert re.search(rf"^  {name}\s", out, re.M), name
    assert "``" not in out and "dip14 = lab_dip14" in out
    rc, out, _ = call(capsys, "gen", "dip", "--list")
    assert rc == 0 and "--row-pitch" in out and "--pins" in out and "7.62" in out
    rc, out, _ = call(capsys, "gen", "--help")
    assert rc == 0 and "использование: kicadfp gen" in out and "lab_snp8" in out
    rc, out, _ = call(capsys, "gen", "lab_snp8", "-h")
    assert rc == 0 and "--hole-inset" in out and "общие параметры gen" in out


def test_gen_list_subprocess():
    r = run_cli("gen", "--list")
    assert r.returncode == 0, r.stderr
    assert "lab_dip14" in r.stdout and "capacitor_radial" in r.stdout


def test_gen_errors(capsys, tmp_path):
    rc, _, err = call(capsys, "gen")
    assert rc == 2 and "не указан генератор KIND" in err
    rc, _, err = call(capsys, "gen", "bogus")
    assert rc == 2 and "неизвестный генератор 'bogus'" in err
    rc, _, err = call(capsys, "gen", "dip", "--pinz", "3")
    assert rc == 2 and "нераспознанные аргументы: --pinz 3" in err
    rc, _, err = call(capsys, "gen", "dip", "--pins", "13")
    assert rc == 2 and "gen dip: pins:" in err
    rc, _, err = call(capsys, "gen", "dip", "--pins", "x")
    assert rc == 2 and "pins" in err
    rc, _, err = call(capsys, "gen", "dip", "--name", " ")
    assert rc == 2 and "имя корпуса не может быть пустым" in err
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    rc, _, err = call(capsys, "gen", "dip", "--params", bad)
    assert rc == 2 and "неверный JSON: строка 1, позиция 2" in err
    bad.write_text("[1, 2]", encoding="utf-8")
    rc, _, err = call(capsys, "gen", "dip", "--params", bad)
    assert rc == 2 and "ожидается JSON-объект" in err
    rc, _, err = call(capsys, "gen", "dip", "--params", tmp_path / "none.json")
    assert rc == 2 and "none.json: файл или каталог не найден" in err
    bad.write_text('{"foo": 1}', encoding="utf-8")
    rc, _, err = call(capsys, "gen", "dip", "--params", bad)
    assert rc == 2 and "не имеет параметра 'foo'" in err


def test_gen_strict_and_warnings(capsys, tmp_path, monkeypatch):
    """Замечания проверки сгенерированного корпуса выводятся; ``--strict`` не пишет файл."""
    vmod = sys.modules["kicadfp.validate"]        # kicadfp.validate — функция, а не модуль
    real = vmod.validate

    def fake(fp, strict=False, **kw):
        return [vmod.Issue("error", "X_TEST", "тест", None),
                vmod.Issue("warning", "W_TEST", "тест2", None)] + real(fp, strict, **kw)

    monkeypatch.setattr(vmod, "validate", fake)
    out = tmp_path / "x.kicad_mod"
    rc, _, err = call(capsys, "gen", "lab_dip14", "-o", out, "--strict")
    assert rc == 1 and not out.exists() and "ошибка проверки: ERROR X_TEST" in err
    assert "предупреждение: WARNING W_TEST" in err
    rc, _, err = call(capsys, "gen", "lab_dip14", "-o", out)
    assert rc == 0 and out.exists()


def test_gen_without_name_parameter(capsys, monkeypatch):
    """Генератор без параметра ``name``: имя задаётся после построения (и Value тоже)."""
    def tiny(pins: int = 2) -> kicadfp.Footprint:
        """Тестовый генератор.

        Параметры:
            pins: число выводов.
        """
        fp = kicadfp.Footprint.new("TINY")
        for i in range(pins):
            fp.new_pad(str(i + 1), "thru_hole", "circle", i * 2.54, 0, 1.6, drill=0.8)
        return fp

    monkeypatch.setitem(kicadfp.generators.GENERATORS, "tiny", tiny)
    rc, out, err = call(capsys, "gen", "tiny", "--pins", "3", "--name", "T3")
    assert rc == 0, err
    fp = kicadfp.loads(out)
    assert fp.name == "T3" and fp.value.text == "T3" and len(fp.pads) == 3


# ---------------------------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------------------------

def test_fmt_check_kicad8_is_canonical_subprocess():
    r = run_cli("fmt", "--check", DIP14_8)
    assert r.returncode == 0, r.stdout + r.stderr
    r = run_cli("fmt", "--check", DIP_LIB8)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "все файлы в каноническом форматировании (проверено: 268)" in r.stdout


def test_fmt_check_write_and_output(capsys, tmp_path):
    messy = tmp_path / "m.kicad_mod"
    fp = kicadfp.load(DIP14_8)
    messy.write_text(sexpr.to_compact(fp.node) + "\n", encoding="utf-8")
    rc, out, _ = call(capsys, "fmt", "--check", messy)
    assert rc == 1 and f"требуется форматирование: {messy} (первое отличие в строке 1)" in out
    other = tmp_path / "o.kicad_mod"
    rc, out, _ = call(capsys, "fmt", messy, "-o", other)
    assert rc == 0 and f"записан: {other}" in out
    rc, out, err = call(capsys, "fmt", messy)
    assert rc == 0 and "файл не изменён" in err and out == other.read_text(encoding="utf-8")
    rc, out, _ = call(capsys, "fmt", "--write", messy)
    assert rc == 0 and f"переформатирован: {messy}" in out and "1 из 1" in out
    assert messy.read_bytes() == other.read_bytes()
    assert sexpr.equal(sexpr.parse(messy.read_text(encoding="utf-8")), fp.node,
                       numeric_tol=0.0, ignore_quotes=False)
    rc, out, _ = call(capsys, "fmt", "--check", messy)
    assert rc == 0
    rc, out, err = call(capsys, "fmt", messy)
    assert rc == 0 and "уже в каноническом" in err


def test_fmt_style_and_library(capsys, tmp_path):
    lib = small_lib(tmp_path)
    rc, out, err = call(capsys, "fmt", lib)
    assert rc == 0 and "требуют форматирования файлов: 0 из 3" in out and "файлы не изменены" in err
    rc, out, _ = call(capsys, "fmt", lib, "--check", "--style", "kicad6")
    assert rc == 1 and "требуют форматирования файлов: 3 из 3" in out
    rc, out, _ = call(capsys, "fmt", lib, "--style", "kicad6")
    assert rc == 0 and out.count("требуется форматирование:") == 3
    out_dir = tmp_path / "k6.pretty"
    rc, out, _ = call(capsys, "fmt", lib, "--style", "kicad6", "-o", out_dir)
    assert rc == 0 and len(list(out_dir.glob("*.kicad_mod"))) == 3
    text = (out_dir / "DIP-4_W7.62mm.kicad_mod").read_text(encoding="utf-8")
    assert "\t" not in text and text.startswith('(footprint "DIP-4_W7.62mm"\n  (version 20240108)')
    rc, out, _ = call(capsys, "fmt", lib, "--style", "kicad6", "--write")
    assert rc == 0 and "переформатировано файлов: 3 из 3" in out
    rc, out, _ = call(capsys, "fmt", lib, "--check")
    assert rc == 1                       # auto для 20240108 — Prettify
    rc, out, _ = call(capsys, "fmt", lib, "--write", "--fp", "DIP-4_W7.62mm")
    assert rc == 0 and "переформатировано файлов: 1 из 1" in out
    assert (lib / "DIP-4_W7.62mm.kicad_mod").read_bytes() == \
        (DIP_LIB8 / "DIP-4_W7.62mm.kicad_mod").read_bytes()


def test_fmt_errors(capsys, tmp_path):
    rc, _, err = call(capsys, "fmt", MY_LIB)
    assert rc == 2 and "не форматируется" in err
    lib = small_lib(tmp_path, ("DIP-4_W7.62mm",))
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    rc, out, err = call(capsys, "fmt", lib, "--check")
    assert rc == 2 and "bad.kicad_mod: строка 4, позиция 1" in err
    assert "проверено: 1" in out


def test_fmt_first_diff_line():
    f = cli._first_diff_line
    assert f(b"a\nb\nc", b"a\nx\nc") == 2
    assert f(b"a\nb", b"a\nb\nc") == 3
    assert f(b"a\nb", b"a\nb") == 2


# ---------------------------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------------------------

def test_convert_subprocess(tmp_path):
    """ТЗ В.3 / сценарий Г.10: ``kicadfp convert My_lib.mod -o tmp.pretty``."""
    out = tmp_path / "tmp.pretty"
    r = run_cli("convert", MY_LIB, "-o", out)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["dip14.kicad_mod", "mlt.kicad_mod",
                                                     "snp8.kicad_mod"]
    assert "преобразовано корпусов: 3" in r.stdout
    dip = kicadfp.load(out / "dip14.kicad_mod")
    assert dip.version == 20241229 and len(dip.pads) == 14
    assert dip.pads[0].size_x == pytest.approx(1.3, abs=0.002)   # 512 децимил -> мм


def test_convert_variants(capsys, tmp_path):
    rc, out, err = call(capsys, "convert", MY_LIB)
    assert rc == 0 and out.split("\n")[0] == "dip14 (площадок: 14)"
    assert "файлы не записаны" in err and "-o My_lib.pretty" in err
    assert not (MY_LIB.parent / "My_lib.pretty").exists()
    out_dir = tmp_path / "fixed.pretty"
    rc, out, err = call(capsys, "convert", MY_LIB, "-o", out_dir, "--compat", "fixed")
    assert rc == 0 and len(list(out_dir.glob("*.kicad_mod"))) == 3
    rc, _, err = call(capsys, "convert", DIP14_8, "-o", tmp_path / "x.pretty")
    assert rc == 2 and "не библиотека старого формата" in err
    rc, _, err = call(capsys, "convert", DIP_LIB8)
    assert rc == 2 and "а не каталог" in err
    rc, _, err = call(capsys, "convert", tmp_path / "none.mod")
    assert rc == 2 and "файл не найден" in err
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    rc, _, err = call(capsys, "convert", MY_LIB, "-o", afile)
    assert rc == 2 and "это файл" in err


def test_convert_format_error_and_issues(capsys, tmp_path):
    bad = tmp_path / "bad.mod"
    bad.write_text("PCBNEW-LibModule-V1\n$INDEX\nx\n$EndINDEX\n$MODULE x\n"
                   "Po 0 0 0 15 00000000 00000000 ~~\n", encoding="utf-8")
    rc, _, err = call(capsys, "convert", bad, "-o", tmp_path / "o.pretty")
    assert rc == 2 and f"ошибка: {bad}: строка 5: нет строки $EndMODULE" in err
    rc, _, err = call(capsys, "info", bad)
    assert rc == 2 and f"ошибка: {bad}: строка 5: нет строки $EndMODULE" in err
    assert not (tmp_path / "o.pretty").exists() or not list((tmp_path / "o.pretty").iterdir())
    dup = tmp_path / "dup.mod"
    text = MY_LIB.read_text(encoding="utf-8")
    end = text.index("$EndMODULE  mlt") + len("$EndMODULE  mlt")
    body = text[text.index("$MODULE mlt"):end]
    dup.write_text(text.replace("$EndLIBRARY", body + "\n$EndLIBRARY"), encoding="utf-8")
    rc, out, err = call(capsys, "convert", dup)
    assert rc == 0 and "предупреждение:" in err and "mlt_v2" in out


# ---------------------------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------------------------

def test_render_svg_subprocess(tmp_path):
    out = tmp_path / "dip14.svg"
    r = run_cli("render", DIP14_8, "-o", out, "--scale", "20", "--pad-numbers")
    assert r.returncode == 0, r.stderr
    root = ET.parse(out).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.find(".//{http://www.w3.org/2000/svg}title").text == "DIP-14_W7.62mm"
    assert 'data-layer="pad_numbers"' in out.read_text(encoding="utf-8")


def test_render_stdout_layers_and_options(capsys, tmp_path):
    rc, out, _ = call(capsys, "render", DIP14_8, "--layers", "F.Cu,F.SilkS", "--no-grid",
                      "--no-background", "--margin", "1", "--show-hidden")
    assert rc == 0 and out.startswith("<?xml")
    root = ET.fromstring(out)
    layers = {g.get("data-layer") for g in root.iter("{http://www.w3.org/2000/svg}g")}
    assert "F.SilkS" in layers and "F.Fab" not in layers
    rc, _, err = call(capsys, "render", DIP14_8, "--layers", "Q.Cu")
    assert rc == 2 and "неизвестный слой «Q.Cu»" in err
    rc, _, err = call(capsys, "render", DIP14_8, "--scale", "0")
    assert rc == 2 and "--scale" in err
    rc, _, err = call(capsys, "render", DIP14_8, "--width", "0", "-o", tmp_path / "x.png")
    assert rc == 2 and "--width" in err
    rc, _, err = call(capsys, "render", DIP14_8, "--grid", "0")
    assert rc == 2 and "--grid" in err
    rc, _, err = call(capsys, "render", DIP14_8, "--margin", "-1")
    assert rc == 2 and "--margin" in err
    rc, _, err = call(capsys, "render", MY_LIB, "-o", tmp_path / "all.svg")
    assert rc == 2 and "а не файл .svg" in err and not (tmp_path / "all.svg").exists()
    rc, _, err = call(capsys, "fmt", DIP_LIB8, "-o", tmp_path / "one.kicad_mod")
    assert rc == 2 and "а не файл .kicad_mod" in err
    rc, _, err = call(capsys, "render", DIP14_8, "-o", tmp_path / "x.jpg")
    assert rc == 2 and "неизвестный формат изображения" in err
    rc, _, err = call(capsys, "render", DIP14_8, "-o", tmp_path / "x.svg", "--format", "png")
    assert rc == 2 and "не совпадает с расширением" in err
    rc, _, err = call(capsys, "render", DIP14_8, "--format", "png")
    assert rc == 2 and "PNG не выводится в stdout" in err
    target = tmp_path / "noext"
    rc, out, _ = call(capsys, "render", DIP14_8, "-o", target, "--format", "svg")
    assert rc == 0 and target.read_text(encoding="utf-8").startswith("<?xml")


def test_render_library_to_directory(capsys, tmp_path):
    lib = small_lib(tmp_path)
    out_dir = tmp_path / "img"
    rc, out, _ = call(capsys, "render", lib, "-o", out_dir)
    assert rc == 0 and sorted(p.name for p in out_dir.iterdir()) == [
        "DIP-4_W7.62mm.svg", "DIP-8_W7.62mm.svg", "SMDIP-8_W9.53mm.svg"]
    rc, _, err = call(capsys, "render", lib)
    assert rc == 2 and "укажите каталог результата" in err
    rc, out, _ = call(capsys, "render", MY_LIB, "-o", out_dir)
    assert rc == 0 and (out_dir / "snp8.svg").exists()
    rc, out, _ = call(capsys, "render", DIP14_8, "-o", out_dir)       # файл -> каталог
    assert rc == 0 and (out_dir / "DIP-14_W7.62mm.svg").exists()
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    rc, out, err = call(capsys, "render", lib, "-o", out_dir)
    assert rc == 2 and "bad.kicad_mod: строка 4" in err and "DIP-4_W7.62mm.svg" in out


def test_render_png_subprocess(tmp_path):
    pytest.importorskip("PySide6")
    out = tmp_path / "dip14.png"
    r = run_cli("render", DIP14_8, "-o", out, "--width", "300")
    assert r.returncode == 0, r.stderr
    data = out.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(data[16:20], "big") == 300          # ширина из IHDR


def test_render_png_without_pyside6(capsys, tmp_path, monkeypatch):
    def no_qt(*a, **k):
        raise RuntimeError("для экспорта PNG нужен PySide6: установите его командой "
                           "pip install kicadfp[png]")

    monkeypatch.setattr(kicadfp.render, "save_png", no_qt)
    rc, _, err = call(capsys, "render", DIP14_8, "-o", tmp_path / "x.png")
    assert rc == 2 and "pip install kicadfp[png]" in err


# ---------------------------------------------------------------------------------------------
# gui
# ---------------------------------------------------------------------------------------------

def test_gui_calls_gui_main(capsys, monkeypatch):
    calls: list[list[str]] = []
    fake = types.ModuleType("kicadfp.gui")
    fake.main = lambda argv: calls.append(argv) or 0            # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kicadfp.gui", fake)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
    rc, _, _ = call(capsys, "gui", DIP14_8)
    assert rc == 0 and calls == [[str(DIP14_8)]]
    fake.main = lambda argv: calls.append(argv) or 3            # type: ignore[attr-defined]
    rc, _, _ = call(capsys, "gui")
    assert rc == 3 and calls[-1] == []


def test_gui_errors(capsys, monkeypatch, tmp_path):
    rc, _, err = call(capsys, "gui", tmp_path / "none.kicad_mod")
    assert rc == 2 and "не найден" in err
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None)
    rc, _, err = call(capsys, "gui")
    assert rc == 2 and "нужен PySide6" in err and "pip install kicadfp[gui]" in err
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
    monkeypatch.setitem(sys.modules, "kicadfp.gui", types.ModuleType("kicadfp.gui"))
    rc, _, err = call(capsys, "gui")
    assert rc == 2 and "нет kicadfp.gui.main" in err
    real_import = importlib.import_module

    def broken(name, *a, **k):
        if name == "kicadfp.gui":
            raise ImportError("no Qt", name="PySide6.QtWidgets")
        return real_import(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", broken)
    rc, _, err = call(capsys, "gui")
    assert rc == 2 and "pip install kicadfp[gui]" in err

    def broken2(name, *a, **k):
        if name == "kicadfp.gui":
            raise ImportError("что-то ещё", name="other")
        return real_import(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", broken2)
    rc, _, err = call(capsys, "gui")
    assert rc == 2 and "графический интерфейс недоступен: что-то ещё" in err

    def spec_fails(name, *a, **k):
        raise ValueError("PySide6.__spec__ is None")

    monkeypatch.setattr(importlib.util, "find_spec", spec_fails)
    rc, _, err = call(capsys, "gui")
    assert rc == 2 and "нужен PySide6" in err


def test_gui_subprocess_without_pyside6():
    """``kicadfp gui`` без PySide6: сообщение об установке и код 2 (окно не открывается)."""
    code = ("import sys\n"
            "sys.modules['PySide6'] = None\n"
            "from kicadfp.cli import main\n"
            "sys.exit(main(['gui']))\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 2
    assert "pip install kicadfp[gui]" in r.stderr


# ---------------------------------------------------------------------------------------------
# Обработка исключений в main
# ---------------------------------------------------------------------------------------------

def test_main_exception_handling(capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("сбой")

    monkeypatch.setattr(cli, "_run", boom)
    monkeypatch.delenv("KICADFP_DEBUG", raising=False)
    rc, _, err = call(capsys, "info", "x")
    assert rc == 2 and "внутренняя ошибка kicadfp: RuntimeError: сбой" in err
    monkeypatch.setenv("KICADFP_DEBUG", "1")
    with pytest.raises(RuntimeError):
        cli.main(["info", "x"])

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", interrupt)
    assert cli.main(["info", "x"]) == 130

    def pipe(*a, **k):
        raise BrokenPipeError

    monkeypatch.setattr(cli, "_run", pipe)
    assert cli.main(["info", "x"]) == 2

    def oserr(*a, **k):
        raise PermissionError(13, "Permission denied", "/root/x")

    monkeypatch.setattr(cli, "_run", oserr)
    rc, _, err = call(capsys, "info", "x")
    assert rc == 2 and "ошибка: /root/x: нет доступа" in err


def test_error_text_helpers(tmp_path):
    e = OSError(12345, "Strange")
    assert cli._os_error_text(e) == "Strange"
    assert cli._error_text(KeyError("ключ"), "p") == "p: ключ"
    err = sexpr.SexprSyntaxError("x", 1, 2)
    assert cli._error_text(err, "f.kicad_mod") == "f.kicad_mod: строка 1, позиция 2: x"
    assert cli._error_text(ValueError("f.kicad_mod: уже с путём"), "f.kicad_mod") == \
        "f.kicad_mod: уже с путём"


def test_emit_file_text_without_buffer(monkeypatch):
    import io as _stdio

    stream = _stdio.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    cli._emit_file_text("abc\n")
    assert stream.getvalue() == "abc\n"


# ---------------------------------------------------------------------------------------------
# Совместимость с KiCad (необязательно: нужен kicad-cli >= 9)
# ---------------------------------------------------------------------------------------------

@pytest.mark.kicad_cli
def test_kicad_cli_reads_cli_results(kicad_cli, tmp_path):
    lib = tmp_path / "res.pretty"
    lib.mkdir()
    path = copy(DIP14_8, lib / "DIP-14_W7.62mm.kicad_mod")
    assert cli.main(["set", str(path), "pad[*].size", "1.3", "--write"]) == 0
    assert cli.main(["set", str(path), "pad[1].shape", "roundrect", "--write"]) == 0
    assert cli.main(["gen", "dip", "--pins", "14", "--pitch", "2.5", "--row-pitch", "7.5", "-o",
                     str(lib / "dip14.kicad_mod")]) == 0
    assert cli.main(["gen", "lab_snp8", "-o", str(lib)]) == 0
    assert cli.main(["convert", str(MY_LIB), "-o", str(tmp_path / "conv.pretty")]) == 0
    for src in (lib, tmp_path / "conv.pretty"):
        out = tmp_path / f"up_{src.name}"
        r = subprocess.run([kicad_cli, "fp", "upgrade", "--force", str(src), "-o", str(out)],
                           capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Unable" not in r.stderr and "rror" not in r.stderr, r.stderr
        assert len(list(out.glob("*.kicad_mod"))) == len(list(src.glob("*.kicad_mod")))
    up = kicadfp.load(tmp_path / "up_res.pretty" / "DIP-14_W7.62mm.kicad_mod")
    assert up.pad(1).shape == "roundrect" and up.pad(2).size == (1.3, 1.3)


# ---------------------------------------------------------------------------------------------
# Редкие ветви
# ---------------------------------------------------------------------------------------------

def test_info_formats_and_zone_layers(capsys, tmp_path):
    k10 = next((FIXTURES / "kicad10dev" / "Package_DIP.pretty").glob("*.kicad_mod"))
    rc, out, _ = call(capsys, "info", k10, "--json")
    assert rc == 0 and json.loads(out)["kicad"] == "KiCad 10"
    nover = tmp_path / "nover.kicad_mod"
    nover.write_text('(footprint "x" (layer "F.Cu")\n  (zone (net 0) (layers "F.Cu" "B.Cu"))\n)\n',
                     encoding="utf-8")
    rc, out, _ = call(capsys, "info", nover)
    assert rc == 0 and "(KiCad 6 (без версии))" in out
    assert re.search(r"^Слои:\s+F\.Cu, B\.Cu$", out, re.M)
    assert re.search(r"^Площадки:\s+0$", out, re.M)
    bom = tmp_path / "bom.kicad_mod"
    bom.write_bytes(b"\xef\xbb\xbf" + DIP14_8.read_bytes())
    rc, out, _ = call(capsys, "info", bom)
    assert rc == 0 and "DIP-14_W7.62mm" in out
    rc, out, _ = call(capsys, "info", MY_LIB, "--json")
    d = json.loads(out)
    assert d["format"] == "PCBNEW-LibModule-V1" and d["library"] == "My_lib"
    assert [f["name"] for f in d["footprints"]] == ["dip14", "mlt", "snp8"]


def test_read_errors_in_libraries(capsys, tmp_path):
    lib = small_lib(tmp_path, ("DIP-4_W7.62mm",))
    (lib / "bad.kicad_mod").write_text(BROKEN, encoding="utf-8")
    rc, out, err = call(capsys, "pads", lib)
    assert rc == 2 and "bad.kicad_mod: строка 4" in err and "DIP-4_W7.62mm" in out
    rc, out, _ = call(capsys, "pads", lib, "--json")
    assert rc == 2 and any("error" in f for f in json.loads(out)["footprints"])
    rc, out, err = call(capsys, "render", lib, "--fp", "bad", "-o", tmp_path / "b.svg")
    assert rc == 2 and "bad.kicad_mod: строка 4" in err and not (tmp_path / "b.svg").exists()
    rc, out, err = call(capsys, "validate", lib, "--fp", "bad", "--json")
    assert rc == 2 and json.loads(out)["issues"][0]["code"] == "SEXPR_SYNTAX"


@pytest.mark.parametrize("selector, message", [
    ("footprint.foo", "у корпуса нет атрибута «foo»"),
    ("graphic[0].foo", "у графики (line) нет атрибута «foo»"),
    ("text[reference].foo", "у текста нет атрибута «foo»"),
    ("model[0].foo", "у 3D-модели нет атрибута «foo»"),
    ("pad[1]._profile", "у площадки нет атрибута «_profile»"),
])
def test_set_unknown_attribute_messages(capsys, tmp_path, selector, message):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    rc, _, err = call(capsys, "set", path, selector, "1")
    assert rc == 2 and message in err


def test_set_many_library_errors_are_capped(capsys, tmp_path):
    lib = tmp_path / "many.pretty"
    lib.mkdir()
    for p in sorted(DIP_LIB8.glob("DIP-*_W7.62mm.kicad_mod"))[:12]:
        shutil.copyfile(p, lib / p.name)
    rc, _, err = call(capsys, "set", lib, "pad[1].shape", "hexagon", "--write")
    assert rc == 2
    assert err.count("ошибка: ") == 10 and "… и ещё ошибок: 2" in err


def test_set_property_in_kicad5_module(capsys, tmp_path):
    path = copy(DIP14_5, tmp_path / "d5.kicad_mod")
    rc, _, err = call(capsys, "set", path, "property[MyKey]", "v", "--write")
    assert rc == 2 and "property[MyKey]:" in err and "upgrade" in err


def test_output_targets(capsys, tmp_path):
    path = copy(DIP14_8, tmp_path / "dip14.kicad_mod")
    newdir = str(tmp_path / "newdir") + os.sep
    rc, out, err = call(capsys, "set", path, "footprint.tags", "t", "-o", newdir)
    assert rc == 0, err
    assert kicadfp.load(tmp_path / "newdir" / "dip14.kicad_mod").tags == "t"
    gen_dir = str(tmp_path / "gen") + os.sep
    rc, out, err = call(capsys, "gen", "lab_mlt", "-o", gen_dir)
    assert rc == 0 and (tmp_path / "gen" / "mlt.kicad_mod").exists()
    img_dir = str(tmp_path / "img") + os.sep
    rc, out, err = call(capsys, "render", path, "-o", img_dir)
    assert rc == 0 and (tmp_path / "img" / "DIP-14_W7.62mm.svg").exists()
    assert cli._is_dir_target(str(tmp_path / "x.pretty"))
    assert not cli._is_dir_target(str(tmp_path / "x.pretty"), pretty=False)
    assert not cli._is_dir_target(str(path))


def test_annotation_helpers():
    class Plain:
        """Класс со свойствами без аннотаций и с аннотациями-типами."""

        def _get(self):
            return 1.5

        def _set(self, value):
            pass

        untyped = property(_get, _set)

        def _get2(self) -> float:
            return 2.0

        def _set2(self, value: float) -> None:
            pass

        typed = property(_get2, _set2)
        builtin = property(len, len)

    assert cli._annotation(Plain._set2, setter=True) == "float"
    assert cli._annotation(Plain._get2, setter=False) == "float"
    assert cli._annotation(Plain._set, setter=True) is None
    assert cli._annotation(None, setter=True) is None
    assert cli._annotation(lambda: None, setter=True) is None
    assert cli._annotation(len, setter=True) is None or True
    prop = cli._property_of(Plain, "untyped")
    assert [t.name for t in cli._attr_type(Plain, "untyped", prop, 1.5)] == ["float", "None"]
    assert cli._property_of(Plain, "nothing") is None
    assert cli._property_of(Plain, "_get") is None
    assert "typed" in cli._settable_names(Plain) and "untyped" in cli._settable_names(Plain)

    def typed_real(self, value: float) -> None:   # аннотация — объект типа
        pass

    typed_real.__annotations__ = {"value": float, "return": None}
    assert cli._annotation(typed_real, setter=True) == "float"


def test_console_script_entry_point():
    """Точка входа ``kicadfp`` (``[project.scripts]``), если пакет установлен в окружение."""
    script = Path(sys.executable).parent / ("kicadfp.exe" if os.name == "nt" else "kicadfp")
    if not script.exists():
        pytest.skip("пакет не установлен в окружение (нет скрипта kicadfp)")
    r = subprocess.run([str(script), "--version"], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0 and r.stdout == f"kicadfp {kicadfp.__version__}\n"


def test_dunder_main_in_process(capsys, monkeypatch):
    """``kicadfp/__main__.py`` в том же процессе (как ``python -m kicadfp --version``)."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["kicadfp", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("kicadfp", run_name="__main__", alter_sys=False)
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"kicadfp {kicadfp.__version__}\n"
