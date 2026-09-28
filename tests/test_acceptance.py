"""Приёмочные испытания: сценарии приложения Г ТЗ (Г.1–Г.10) и п. 8.2.

Каждый сценарий — один или несколько тестов ``test_scenario_N_*``. Тесты с kicad-cli
(«открыть в KiCad») выполняются при наличии kicad-cli (``KICAD_CLI``, версия >= 9; KiCad 8 —
``KICAD8_CLI`` или ``kicad-cli8`` в PATH), иначе пропускаются (ТЗ 4.5.4). «Открыть в KiCad»
проверяется так (``tests/kicad_cli_tools.py``): ``kicad-cli fp upgrade --force`` читает и
пересохраняет каждый корпус без сообщений, а прочитанное KiCad (площадки, графика, тексты,
3D-модели) совпадает с прочитанным kicadfp.

Фактические числа тестов записываются через ``record_property`` — их собирает
``scripts/acceptance_report.py`` в отчёт ``docs/acceptance_report.md``.

Примечание к сценарию Г.3. KiCad отвергает файл с неизвестным ему узлом (парсер
``parseFOOTPRINT`` → «Expecting …», kicad-cli: «Unable to load library»), поэтому файл
сценария с ``(example_token 1 2)`` проверяется самой Программой (узел сохраняется без
изменений, изменена только площадка 1), а проверка в KiCad выполняется на том же изменении
файла **без** неизвестного узла.

Сценарий Г.8 (графический интерфейс) целиком — ``tests/test_gui_mainwindow.py::
test_scenario_8_drag_and_table_undo_redo_save`` (мышь на поле просмотра, таблица, клавиши и
меню); здесь — та же последовательность через документ :class:`FootprintDocument`, модель
таблицы площадок и команду перетаскивания канвы (без окна, ``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import kicadfp
from kicadfp import cli as kcli
from kicadfp import generators, legacy, sexpr
from kicadfp.format_rules import KICAD_FORMAT_VERSIONS
from kicadfp.io import ValidationError
from kicadfp.library import Library
from kicadfp.sexpr import Node, SexprSyntaxError

from . import kicad_cli_tools as T
from .conftest import FIXTURES, extra_fixture_files, fixture_files

DIP_LIB8 = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14_8 = DIP_LIB8 / "DIP-14_W7.62mm.kicad_mod"
DIP14_6 = FIXTURES / "kicad6" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
DIP14_5 = FIXTURES / "kicad5" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"
MY_LIB = FIXTURES / "legacy_mod" / "My_lib.mod"
#: Библиотеки KiCad 8, названные в ТЗ 4.2.3 (фикстура tests/fixtures/kicad8 — они целиком).
TZ_LIBRARIES = ("Package_DIP", "Resistor_THT", "Capacitor_THT", "Connector_PinHeader_2.54mm",
                "Package_SO")
_GENERATOR = re.compile(r'\(generator\s+"?([^")\s]+)')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kicad_written(text: str) -> bool:
    """Файл записан самим KiCad (``generator pcbnew`` или ``module`` KiCad 5)."""
    m = _GENERATOR.search(text[:1000])
    return (m is not None and m.group(1) == "pcbnew") or text.startswith("(module ")


# =============================================================================================
# Г.1. Открыть ≥ 200 корпусов стандартных библиотек KiCad 8, сохранить без изменений,
#      сравнить деревья S-выражений — совпадение для всех файлов
# =============================================================================================

@dataclass
class RoundTrip:
    """Итог «открыть — сохранить без изменений — сравнить» по набору файлов."""

    files: list[Path]
    saved: Path                                   # каталог .pretty с записанными файлами
    tree_equal: int = 0
    byte_equal: int = 0
    kicad_written: int = 0
    tree_bad: list[str] = field(default_factory=list)
    byte_bad: list[str] = field(default_factory=list)
    seconds: float = 0.0


def _flat_name(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.parent.name) / path.name
    return "__".join(p.replace(".pretty", "") for p in rel.with_suffix("").parts)


def roundtrip_files(files: list[Path], saved: Path, root: Path = FIXTURES) -> RoundTrip:
    """Каждый файл: :func:`kicadfp.load` → :func:`kicadfp.save` в ``saved`` → сравнить
    разобранные деревья (строго: числа и кавычки как в исходнике) и байты (для файлов,
    записанных KiCad, ожидается совпадение байт в байт)."""
    saved.mkdir(parents=True, exist_ok=True)
    res = RoundTrip(files, saved)
    t0 = time.perf_counter()
    for p in files:
        src = p.read_bytes()
        dst = saved / f"{_flat_name(p, root)}.kicad_mod"
        kicadfp.save(kicadfp.load(p), dst)
        out = dst.read_bytes()
        a = sexpr.parse(src.decode("utf-8"))
        b = sexpr.parse(out.decode("utf-8"))
        if sexpr.equal(a, b, numeric_tol=0.0, ignore_quotes=False) and not sexpr.diff(a, b):
            res.tree_equal += 1
        else:
            res.tree_bad.append(str(p))
        if _kicad_written(src.decode("utf-8")):
            res.kicad_written += 1
            if out == src:
                res.byte_equal += 1
            else:
                res.byte_bad.append(str(p))
    res.seconds = time.perf_counter() - t0
    return res


@pytest.fixture(scope="module")
def kicad8_roundtrip(tmp_path_factory) -> RoundTrip:
    return roundtrip_files(fixture_files("kicad8"), tmp_path_factory.mktemp("g1") / "kicad8.pretty")


def test_scenario_1_roundtrip_kicad8_libraries(kicad8_roundtrip, record_property):
    rt = kicad8_roundtrip
    libs = sorted({p.parent.name.removesuffix(".pretty") for p in rt.files})
    record_property("files", len(rt.files))
    record_property("libraries", ", ".join(libs))
    record_property("tree_equal", rt.tree_equal)
    record_property("kicad_written", rt.kicad_written)
    record_property("byte_equal", rt.byte_equal)
    record_property("seconds", round(rt.seconds, 2))
    assert len(rt.files) >= 200
    assert set(TZ_LIBRARIES) <= set(libs)
    assert rt.tree_equal == len(rt.files), rt.tree_bad[:10]
    assert rt.byte_equal == rt.kicad_written == len(rt.files), rt.byte_bad[:10]


def test_scenario_1_saved_files_open_in_kicad9(kicad_cli, kicad8_roundtrip, tmp_path,
                                                record_property):
    """ТЗ 8.2: сохранённые без изменений корпуса открываются в KiCad 9 без сообщений об
    ошибках, содержимое после чтения KiCad совпадает."""
    res = T.check_library(kicad_cli, kicad8_roundtrip.saved, tmp_path)
    record_property("kicad_cli", T.cli_version(kicad_cli))
    record_property("files", res.files)
    record_property("compared_equal", res.compared - len(res.mismatches))
    record_property("seconds", round(res.run.seconds, 2))
    assert res.ok, res.report()
    assert res.compared == len(kicad8_roundtrip.files)


def test_scenario_1_saved_files_open_in_kicad8(kicad8_cli, kicad8_roundtrip, tmp_path,
                                                record_property):
    res = T.check_library(kicad8_cli, kicad8_roundtrip.saved, tmp_path)
    record_property("kicad_cli", T.cli_version(kicad8_cli))
    record_property("files", res.files)
    record_property("compared_equal", res.compared - len(res.mismatches))
    assert res.ok, res.report()
    assert res.compared == len(kicad8_roundtrip.files)


@pytest.mark.slow
def test_scenario_1_full_kicad8_library(tmp_path, record_property):
    """Расширенный прогон по библиотекам KiCad 8 (``KICADFP_KICAD8_LIBRARY`` — каталог клона
    kicad-footprints 8.x, например ``.cache/kfp/v8.0.0``); без переменной — skip. При наличии
    kicad-cli сохранённые файлы открываются в KiCad (все — без ошибок; содержимое после чтения
    KiCad сравнивается у каждого 5-го — у фикстуры kicad8 оно сравнивается у всех)."""
    root = os.environ.get("KICADFP_KICAD8_LIBRARY")
    if not root or not Path(root).is_dir():
        pytest.skip("KICADFP_KICAD8_LIBRARY не задана (полная библиотека KiCad 8)")
    files = sorted(Path(root).rglob("*.kicad_mod"))
    rt = roundtrip_files(files, tmp_path / "full.pretty", root=Path(root))
    record_property("files", len(files))
    record_property("libraries", len({p.parent for p in files}))
    record_property("tree_equal", rt.tree_equal)
    record_property("kicad_written", rt.kicad_written)
    record_property("byte_equal", rt.byte_equal)
    record_property("seconds", round(rt.seconds, 2))
    assert len(files) >= 200
    assert rt.tree_equal == len(files), rt.tree_bad[:10]
    assert rt.byte_equal == rt.kicad_written, rt.byte_bad[:10]
    from .conftest import _find_kicad_cli, find_kicad8_cli, kicad_cli_version
    for key, cli in (("kicad9", _find_kicad_cli()), ("kicad8", find_kicad8_cli())):
        if not cli or (key == "kicad9" and kicad_cli_version(cli)[:1] < (9,)):
            continue
        res = T.check_library(cli, rt.saved, tmp_path, compare_step=5)
        record_property(f"{key}_cli", T.cli_version(cli))
        record_property(f"{key}_opened", res.files - len(res.missing) if res.run.ok else 0)
        record_property(f"{key}_compared", res.compared)
        record_property(f"{key}_compared_equal", res.compared - len(res.mismatches))
        assert res.ok, res.report()


# =============================================================================================
# Г.2. Открыть корпус KiCad 6 (толщина линий токеном width, тексты fp_text), сохранить,
#      открыть в KiCad 8 и 9 — файл открывается без ошибок, графика и тексты на месте
# =============================================================================================

def _scenario_2(cli: str, tmp_path: Path, kicad_version: int) -> dict[str, int]:
    text = DIP14_6.read_text(encoding="utf-8")
    assert "(version 20211014)" in text and "(width 0.12)" in text
    assert '(fp_text reference "REF**"' in text and "(stroke" not in text
    fp = kicadfp.load(DIP14_6)
    assert fp.version == 20211014 and not fp.profile.stroke and not fp.profile.text_as_property
    lib = tmp_path / "k6.pretty"
    lib.mkdir()
    kicadfp.save(fp, lib / DIP14_6.name)                       # сохранить без изменений
    assert (lib / DIP14_6.name).read_bytes() == DIP14_6.read_bytes()
    edited = kicadfp.load(DIP14_6)                              # и с правкой в форме KiCad 6
    edited.new_line((-1.0, -2.0), (8.62, -2.0), "F.SilkS", 0.15)
    edited.new_text("ПРИЁМКА Г.2", "user", 3.81, 18.5, layer="F.Fab")
    kicadfp.save(edited, lib / "DIP-14_edited.kicad_mod")
    etext = (lib / "DIP-14_edited.kicad_mod").read_text(encoding="utf-8")
    assert "(width 0.15)" in etext and "(stroke" not in etext
    assert '(fp_text user "ПРИЁМКА Г.2"' in etext and "(version 20211014)" in etext
    res = T.check_library(cli, lib, tmp_path)
    assert res.ok, res.report()
    for name, ours in ((DIP14_6.name, fp), ("DIP-14_edited.kicad_mod", edited)):
        back = kicadfp.load(tmp_path / "k6_kicad.pretty" / name)
        assert back.version == KICAD_FORMAT_VERSIONS[kicad_version]
        assert len(back.pads) == len(ours.pads) == 14
        assert len(back.graphics) == len(ours.graphics)
        assert sorted(g.width for g in back.graphics) == sorted(g.width for g in ours.graphics)
        texts = {(t.text, t.layer) for t in back.texts if t.text}
        assert {(t.text, t.layer) for t in ours.texts if t.text} <= texts
        assert back.reference.text == "REF**" and back.value.text == "DIP-14_W7.62mm"
    return {"graphics": len(fp.graphics), "texts": len(fp.texts), "pads": len(fp.pads)}


def test_scenario_2_kicad6_footprint_opens_in_kicad9(kicad_cli, tmp_path, record_property):
    n = _scenario_2(kicad_cli, tmp_path, 9)
    record_property("kicad_cli", T.cli_version(kicad_cli))
    for k, v in n.items():
        record_property(k, v)


def test_scenario_2_kicad6_footprint_opens_in_kicad8(kicad8_cli, tmp_path, record_property):
    n = _scenario_2(kicad8_cli, tmp_path, 8)
    record_property("kicad_cli", T.cli_version(kicad8_cli))
    for k, v in n.items():
        record_property(k, v)


@pytest.mark.parametrize("which", ["kicad9", "kicad8"])
def test_scenario_2_all_kicad6_fixtures_open_in_kicad(which, request, tmp_path, record_property):
    """Все корпуса формата KiCad 6 (фикстура kicad6) после сохранения kicadfp открываются в
    KiCad, графика и тексты — те же."""
    cli = request.getfixturevalue("kicad_cli" if which == "kicad9" else "kicad8_cli")
    rt = roundtrip_files(fixture_files("kicad6"), tmp_path / "k6all.pretty")
    assert rt.tree_equal == len(rt.files)
    res = T.check_library(cli, rt.saved, tmp_path)
    record_property("kicad_cli", T.cli_version(cli))
    record_property("files", res.files)
    record_property("compared_equal", res.compared - len(res.mismatches))
    assert res.ok, res.report()
    assert res.compared == len(rt.files) >= 200


# =============================================================================================
# Г.3. В корпус DIP-14 добавить неизвестный узел (example_token 1 2), изменить размер
#      площадки 1, сохранить — узел сохранён без изменений, изменена только площадка 1
# =============================================================================================

_TOKEN_LINE = "\t(example_token 1 2)\n"


def _dip14_with_token(tmp_path: Path) -> Path:
    text = DIP14_8.read_text(encoding="utf-8")
    anchor = "\t(attr through_hole)\n"
    assert text.count(anchor) == 1
    src = tmp_path / "DIP-14_W7.62mm.kicad_mod"
    src.write_text(text.replace(anchor, anchor + _TOKEN_LINE), encoding="utf-8")
    return src


def test_scenario_3_unknown_node_kept_only_pad1_changed(tmp_path, record_property):
    src = _dip14_with_token(tmp_path)
    before_text = src.read_text(encoding="utf-8")
    fp = kicadfp.load(src)
    assert [n.name for n in fp.unknown] == ["example_token"]
    pad1 = fp.pad("1")
    assert pad1.size == (1.6, 1.6)
    pad1.size = (2.0, 2.0)
    out = tmp_path / "out" / src.name
    out.parent.mkdir()
    kicadfp.save(fp, out)
    after_text = out.read_text(encoding="utf-8")
    # неизвестный узел — на месте и без изменений (та же строка файла)
    assert after_text.count(_TOKEN_LINE) == 1
    assert after_text.index(_TOKEN_LINE) == before_text.index(_TOKEN_LINE)
    before, after = sexpr.parse(before_text), sexpr.parse(after_text)
    tok_b, tok_a = before.find("example_token"), after.find("example_token")
    assert sexpr.equal(tok_a, tok_b, numeric_tol=0.0, ignore_quotes=False)
    assert before.index(tok_b) == after.index(tok_a)
    # изменена только площадка 1: по дереву — один токен size, по тексту — одна строка
    diffs = sexpr.diff(before, after)
    assert diffs and all(d.startswith("footprint/pad[0]/size") for d in diffs), diffs
    changed = [(a, b) for a, b in zip(before_text.split("\n"), after_text.split("\n")) if a != b]
    assert len(before_text.split("\n")) == len(after_text.split("\n"))
    assert changed == [("\t\t(size 1.6 1.6)", "\t\t(size 2 2)")]
    # относительно исходного файла библиотеки: добавленная строка узла + размер площадки 1
    orig = DIP14_8.read_text(encoding="utf-8").split("\n")
    assert [ln for ln in after_text.split("\n") if ln not in orig] == \
        ["\t(example_token 1 2)", "\t\t(size 2 2)"]
    record_property("unknown_node_kept", True)
    record_property("tree_diffs", len(diffs))
    record_property("changed_lines", len(changed))
    record_property("diff", "; ".join(diffs))


def test_scenario_3_cli_set_keeps_unknown_node(tmp_path, capsys):
    """То же командой ``kicadfp set FILE "pad[1].size" 2 -o OUT``."""
    src = _dip14_with_token(tmp_path)
    out = tmp_path / "cli.kicad_mod"
    assert kcli.main(["set", str(src), "pad[1].size", "2", "-o", str(out)]) == 0, \
        capsys.readouterr().err
    a, b = src.read_text(encoding="utf-8"), out.read_text(encoding="utf-8")
    changed = [(x, y) for x, y in zip(a.split("\n"), b.split("\n")) if x != y]
    assert changed == [("\t\t(size 1.6 1.6)", "\t\t(size 2 2)")] and _TOKEN_LINE in b


def test_scenario_3_kicad_reads_the_edit_without_unknown_node(kicad_cli, tmp_path,
                                                               record_property):
    """Проверка в KiCad — на том же изменении файла без неизвестного узла (KiCad отвергает
    неизвестные токены): KiCad читает файл, у площадки 1 размер 2 × 2, остальные площадки,
    графика и тексты — как в исходном корпусе."""
    fp = kicadfp.load(DIP14_8)
    fp.pad("1").size = (2.0, 2.0)
    lib = T.write_library({"DIP-14_W7.62mm": fp}, tmp_path / "g3.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "g3_kicad.pretty" / "DIP-14_W7.62mm.kicad_mod")
    orig = kicadfp.load(DIP14_8)
    assert back.pad("1").size == (2.0, 2.0)
    assert [(p.number, p.size) for p in back.pads[1:]] == [(p.number, p.size)
                                                            for p in orig.pads[1:]]
    # файл с неизвестным узлом KiCad не открывает — фиксируется для отчёта (не проверка)
    with_token = tmp_path / "token.pretty"
    with_token.mkdir()
    kicadfp.save(kicadfp.load(_dip14_with_token(tmp_path)), with_token / "DIP-14_W7.62mm.kicad_mod")
    r = T.upgrade(kicad_cli, with_token, tmp_path / "token_out")
    record_property("kicad_cli", T.cli_version(kicad_cli))
    record_property("kicad_reads_edit_without_token", res.ok)
    record_property("kicad_reads_file_with_unknown_token", r.ok)
    record_property("kicad_message_for_unknown_token", "; ".join(r.messages) or "-")


# =============================================================================================
# Г.4. У всех площадок: форма roundrect с rratio 0.25, слои F.Cu F.Mask F.Paste, тип smd,
#      удалить отверстия — проверка без ошибок, KiCad показывает SMD-корпус
# =============================================================================================

_SMD_LAYERS = ["F.Cu", "F.Mask", "F.Paste"]


def _to_smd(fp: kicadfp.Footprint) -> None:
    for pad in fp.pads:
        pad.shape = "roundrect"
        pad.roundrect_rratio = 0.25
        pad.layers = _SMD_LAYERS
        pad.type = "smd"
        pad.drill = None
    fp.attrs.discard("through_hole")   # тип корпуса — SMD (в KiCad — «Surface mount»)
    fp.attrs.add("smd")


def _assert_smd(fp: kicadfp.Footprint) -> None:
    assert fp.pads and all(
        p.type == "smd" and p.shape == "roundrect" and p.roundrect_rratio == 0.25
        and set(p.layers) == set(_SMD_LAYERS) and p.drill is None for p in fp.pads)
    assert set(fp.attrs) == {"smd"}


@pytest.mark.parametrize("src", [DIP14_8, DIP14_6, DIP14_5], ids=["kicad8", "kicad6", "kicad5"])
def test_scenario_4_all_pads_to_smd_roundrect(src, tmp_path, record_property):
    fp = kicadfp.load(src)
    orig = fp.node.copy()
    _to_smd(fp)
    issues = fp.validate()
    errors = [str(i) for i in issues if i.level == "error"]
    assert errors == []
    out = tmp_path / src.name
    kicadfp.save(fp, out, strict=True)          # строгая запись: ошибок нет
    back = kicadfp.load(out)
    _assert_smd(back)
    assert back.version == fp.version            # формат файла сохраняется
    # изменены только площадки и атрибут корпуса: без них деревья совпадают
    def rest(root: Node) -> Node:
        return Node(root.name, [x for x in root.items
                                if not (isinstance(x, Node) and x.name in ("pad", "attr"))])

    assert not sexpr.equal(orig, back.node)
    assert sexpr.equal(rest(orig), rest(back.node), numeric_tol=0.0, ignore_quotes=False)
    record_property("pads", len(back.pads))
    record_property("errors", len(errors))
    record_property("warnings", "; ".join(f"{i.code}" for i in issues) or "-")


def test_scenario_4_same_result_with_cli_set(tmp_path, capsys):
    """Групповое изменение командами ``kicadfp set … "pad[*]…" --write`` (ТЗ 6.1) даёт тот же
    файл, что и API."""
    f = tmp_path / DIP14_8.name
    shutil.copyfile(DIP14_8, f)
    for sel, value in (("pad[*].shape", "roundrect"), ("pad[*].roundrect_rratio", "0.25"),
                       ("pad[*].layers", "F.Cu,F.Mask,F.Paste"), ("pad[*].type", "smd"),
                       ("pad[*].drill", "none"), ("footprint.attrs", "smd")):
        assert kcli.main(["set", str(f), sel, value, "--write"]) == 0, capsys.readouterr().err
    assert kcli.main(["validate", str(f)]) == 0
    capsys.readouterr()
    api = kicadfp.load(DIP14_8)
    _to_smd(api)
    assert f.read_text(encoding="utf-8") == kicadfp.dumps(api)


def test_scenario_4_kicad_shows_smd_footprint(kicad_cli, tmp_path, record_property):
    fps = {}
    for key, src in (("kicad8", DIP14_8), ("kicad6", DIP14_6), ("kicad5", DIP14_5)):
        fp = kicadfp.load(src)
        _to_smd(fp)
        fps[f"DIP-14_SMD_{key}"] = fp
    lib = T.write_library(fps, tmp_path / "g4.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()
    for name in fps:
        back = kicadfp.load(tmp_path / "g4_kicad.pretty" / f"{name}.kicad_mod")
        _assert_smd(back)
    # KiCad рисует корпус: SVG слоёв F.Cu и F.Paste (у сквозных площадок пасты нет)
    svg = T.export_svg(kicad_cli, lib, "DIP-14_SMD_kicad8", tmp_path / "svg", ["F.Cu", "F.Paste"])
    assert svg.returncode == 0, str(svg)
    files = list((tmp_path / "svg").glob("*.svg"))
    assert len(files) == 1 and files[0].stat().st_size > 1000
    record_property("kicad_cli", T.cli_version(kicad_cli))
    record_property("files", len(fps))
    record_property("svg_bytes", files[0].stat().st_size)


# =============================================================================================
# Г.5. Сгенерировать dip14, mlt, snp8 по параметрам лабораторной работы, открыть в KiCad —
#      площадки 1,3 мм, отверстия 0,8 мм, первая площадка квадратная, шаг и контур по заданию
# =============================================================================================

#: Задание (методичка, lab-generators.md §2): число сигнальных площадок, шаг в ряду,
#: расстояние между рядами, контур F.Fab (x1, y1, x2, y2).
LAB = {
    "dip14": dict(gen=generators.lab_dip14, pads=14, pitch=2.5, rows=7.5,
                  body=(-2.5, -8.75, 2.5, 8.75)),
    "mlt": dict(gen=generators.lab_mlt, pads=2, pitch=None, rows=10.0,
                body=(-3.75, -1.25, 3.75, 1.25)),
    "snp8": dict(gen=generators.lab_snp8, pads=8, pitch=2.5, rows=5.0,
                 body=(2.5, -12.5, 15.0, 12.5)),
}


def _check_lab(name: str, fp: kicadfp.Footprint) -> dict[str, object]:
    spec = LAB[name]
    signal = [p for p in fp.pads if p.number]
    assert fp.name == name and len(signal) == spec["pads"]
    for p in signal:
        assert p.type == "thru_hole" and p.size == (1.3, 1.3), p.number
        assert p.drill is not None and p.drill.size == (0.8, 0.8) and not p.drill.oval
        assert p.shape == ("rect" if p.number == "1" else "circle"), p.number
    xs = sorted({p.x for p in signal})
    if spec["rows"] is not None:
        assert len(xs) == 2 and xs[1] - xs[0] == pytest.approx(spec["rows"])
    if spec["pitch"] is not None:
        for x in xs:
            ys = sorted(p.y for p in signal if p.x == x)
            assert all(b - a == pytest.approx(spec["pitch"]) for a, b in zip(ys, ys[1:]))
    for p in fp.pads:     # сетка методички 1.25 мм
        assert (p.x / 1.25) == pytest.approx(round(p.x / 1.25)) and \
            (p.y / 1.25) == pytest.approx(round(p.y / 1.25))
    fab = [g for g in fp.graphics if g.layer == "F.Fab" and g.kind == "rect"]
    assert len(fab) == 1
    (x1, y1), (x2, y2) = fab[0].start, fab[0].end
    assert (x1, y1, x2, y2) == pytest.approx(spec["body"])
    silk = [g for g in fp.graphics if g.layer == "F.SilkS"]
    crtyd = [g for g in fp.graphics if g.layer == "F.CrtYd"]
    assert silk and len(crtyd) == 1
    if name == "snp8":
        holes = sorted((p.x, p.y, p.size_x, p.drill.diameter) for p in fp.pads if not p.number)
        assert holes == [(8.75, -10.0, 3.0, 3.0), (8.75, 10.0, 3.0, 3.0)]
        assert {p.type for p in fp.pads if not p.number} == {"np_thru_hole"}
    errors = [str(i) for i in fp.validate() if i.level == "error"]
    assert errors == []
    return {"pads": len(fp.pads), "pitch": spec["pitch"] or "-", "rows": spec["rows"],
            "body": "×".join(f"{v:g}" for v in (x2 - x1, y2 - y1))}


@pytest.mark.parametrize("name", list(LAB))
def test_scenario_5_lab_footprint_matches_assignment(name, record_property):
    facts = _check_lab(name, LAB[name]["gen"]())
    for k, v in facts.items():
        record_property(k, v)


@pytest.mark.parametrize("name", list(LAB))
def test_scenario_5_matches_hand_made_footprint(name, legacy_mod, record_property):
    """ТЗ 8.2: сравнение с корпусами, созданными вручную (``My_lib.mod``, деци-милы):
    номера, типы, формы, координаты, размеры, отверстия площадок и положения
    Reference/Value совпадают с допуском 0.00127 мм (округление до деци-мила)."""
    from .test_generators import _parse_my_lib

    fp = LAB[name]["gen"]()
    ref = _parse_my_lib(legacy_mod)[name]
    tol = 0.00127 + 1e-9
    mine = sorted(fp.pads, key=lambda p: (p.number, p.x, p.y))
    theirs = sorted(ref["pads"], key=lambda q: ("" if q["type"] == "np_thru_hole" else q["num"],
                                                 q["x"], q["y"]))
    assert len(mine) == len(theirs)
    worst = 0.0
    for p, q in zip(mine, theirs):
        assert p.number == ("" if q["type"] == "np_thru_hole" else q["num"])
        assert (p.type, p.shape) == (q["type"], q["shape"])
        for a, b in ((p.x, q["x"]), (p.y, q["y"]), (p.size_x, q["sx"]), (p.size_y, q["sy"]),
                     (p.drill.diameter, q["drill"])):
            worst = max(worst, abs(a - b))
    for t, key in ((fp.reference, "T0"), (fp.value, "T1")):
        x, y, ang = ref["texts"][key]
        worst = max(worst, abs(t.x - x), abs(t.y - y))
        assert t.angle == ang
    assert worst <= tol
    record_property("pads", len(mine))
    record_property("max_deviation_mm", round(worst, 6))


def test_scenario_5_cli_gen_same_as_api(tmp_path, capsys):
    lib = tmp_path / "br8_timer.pretty"
    for kind, name in (("dip14", "dip14"), ("mlt", "mlt"), ("snp8", "snp8")):
        assert kcli.main(["gen", kind, "-o", str(lib / f"{name}.kicad_mod")]) == 0
        assert (lib / f"{name}.kicad_mod").read_text(encoding="utf-8") == \
            kicadfp.dumps(LAB[name]["gen"]())
    capsys.readouterr()


@pytest.mark.parametrize("which", ["kicad9", "kicad8"])
def test_scenario_5_lab_footprints_open_in_kicad(which, request, tmp_path, record_property):
    """Корпуса открываются в KiCad 9 (формат по умолчанию) и в KiCad 8 (формат KiCad 8:
    ``target_version(8)`` / ``kicadfp gen … --kicad 8`` — KiCad 8 не читает формат KiCad 9);
    после чтения KiCad — те же площадки 1.3/0.8 и контур."""
    cli = request.getfixturevalue("kicad_cli" if which == "kicad9" else "kicad8_cli")
    kicad = 9 if which == "kicad9" else 8
    with generators.target_version(kicad):
        fps = {name: spec["gen"]() for name, spec in LAB.items()}
    lib = T.write_library(fps, tmp_path / "lab.pretty")
    res = T.check_library(cli, lib, tmp_path)
    assert res.ok, res.report()
    for name in LAB:
        back = kicadfp.load(tmp_path / "lab_kicad.pretty" / f"{name}.kicad_mod")
        _check_lab(name, back)
    record_property("kicad_cli", T.cli_version(cli))
    record_property("format_version", KICAD_FORMAT_VERSIONS[kicad])
    record_property("files", res.files)


# =============================================================================================
# Г.6. Задать площадке отверстие 1,5 мм при размере 1,3 мм, выполнить проверку —
#      сообщение об ошибке «отверстие больше площадки»
# =============================================================================================

@pytest.mark.parametrize("source", ["lab_dip14", "kicad8"])
def test_scenario_6_drill_bigger_than_pad_is_error(source, tmp_path, record_property):
    fp = generators.lab_dip14() if source == "lab_dip14" else kicadfp.load(DIP14_8)
    pad = fp.pad("1")
    pad.size = (1.3, 1.3)
    pad.drill = 1.5
    issues = fp.validate()
    errors = [i for i in issues if i.level == "error"]
    assert [i.code for i in errors] == ["PAD_DRILL_GT_SIZE"]
    err = errors[0]
    assert "отверстие больше площадки" in err.message and "«1»" in err.message
    assert err.element == pad and err.node is pad.node
    # по умолчанию ошибки не блокируют запись, в строгом режиме — блокируют (ТЗ 4.1.5)
    out = tmp_path / "g6.kicad_mod"
    with pytest.raises(ValidationError) as ei:
        kicadfp.save(fp, out, strict=True)
    assert not out.exists() and ei.value.errors == errors
    kicadfp.save(fp, out)
    assert kicadfp.load(out).pad("1").drill.diameter == 1.5
    record_property("error", str(err))


def test_scenario_6_cli_validate_reports_error(tmp_path, capsys):
    f = tmp_path / "dip14.kicad_mod"
    kicadfp.save(generators.lab_dip14(), f)
    rc = kcli.main(["set", str(f), "pad[1].drill", "1.5", "--strict", "--write"])
    out, err = capsys.readouterr()
    assert rc == 1 and "отверстие больше площадки" in err     # строгий режим: не записано
    assert kicadfp.load(f).pad("1").drill.diameter == 0.8
    assert kcli.main(["set", str(f), "pad[1].drill", "1.5", "--write"]) == 0
    capsys.readouterr()
    rc = kcli.main(["validate", str(f)])
    out, err = capsys.readouterr()
    assert rc == 1
    assert "ERROR PAD_DRILL_GT_SIZE: площадка «1» (-3.75; -7.5): отверстие больше площадки" in out


# =============================================================================================
# Г.7. Открыть файл с синтаксической ошибкой (незакрытая скобка) — сообщение с номером
#      строки и позиции, модель не создаётся
# =============================================================================================

def _broken_dip14(tmp_path: Path, where: str) -> tuple[Path, int, int]:
    """DIP-14 с незакрытой скобкой: ``middle`` — у ``(at …)`` площадки 5, ``end`` — нет
    последней скобки корня. Возвращает путь и ожидаемые строку и позицию ошибки."""
    text = DIP14_8.read_text(encoding="utf-8")
    if where == "middle":
        lines = text.split("\n")
        i = next(k for k, ln in enumerate(lines) if ln.startswith('\t(pad "5"')) + 1
        assert lines[i] == "\t\t(at 0 10.16)"
        lines[i] = "\t\t(at 0 10.16"
        bad_text, line, col = "\n".join(lines), i + 1, 3
    else:
        body = text.rstrip("\n")
        assert body.endswith("\n)")
        bad_text = body[:-1]                    # без последней «)», оканчивается на «\n»
        line, col = bad_text.count("\n") + 1, 1
    bad = tmp_path / f"broken_{where}.kicad_mod"
    bad.write_text(bad_text, encoding="utf-8")
    return bad, line, col


@pytest.mark.parametrize("where", ["middle", "end"])
def test_scenario_7_syntax_error_line_and_position(where, tmp_path, monkeypatch,
                                                    record_property):
    bad, line, col = _broken_dip14(tmp_path, where)
    created: list[object] = []

    class Spy(kicadfp.Footprint):
        def __init__(self, *a, **kw):  # pragma: no cover - не должен вызываться
            created.append(a)
            super().__init__(*a, **kw)

    import kicadfp.io as kio
    monkeypatch.setattr(kio, "Footprint", Spy)
    with pytest.raises(SexprSyntaxError) as ei:
        kicadfp.load(bad)
    e = ei.value
    assert (e.line, e.col) == (line, col), str(e)
    assert str(e).startswith(f"строка {line}, позиция {col}: незакрытая скобка")
    assert e.path == str(bad)                           # type: ignore[attr-defined]
    assert created == []                                # модель не создана
    record_property("message", str(e))


def test_scenario_7_cli_exit_code_2(tmp_path, capsys):
    bad, line, col = _broken_dip14(tmp_path, "middle")
    before = bad.read_bytes()
    for cmd in (["info", str(bad)], ["validate", str(bad)], ["pads", str(bad)],
                ["set", str(bad), "pad[1].size", "2", "--write"]):
        assert kcli.main(cmd) == 2
        _, err = capsys.readouterr()
        assert f"ошибка: {bad}: строка {line}, позиция {col}: незакрытая скобка" in err
    assert bad.read_bytes() == before                    # файл не изменён


def test_scenario_7_gui_document_not_created(qtbot, tmp_path):
    pytest.importorskip("PySide6")
    from kicadfp.gui.document import FootprintDocument

    bad, line, col = _broken_dip14(tmp_path, "middle")
    doc = FootprintDocument()
    with pytest.raises(SexprSyntaxError) as ei:
        doc.open(bad)
    assert (ei.value.line, ei.value.col) == (line, col)
    assert doc.fp is None and doc.path is None and not doc.is_modified


# =============================================================================================
# Г.8. В графическом интерфейсе переместить площадку мышью и в таблице, отменить, повторить,
#      сохранить — значения в таблице и на поле просмотра совпадают, файл содержит итоговые
#      координаты
# =============================================================================================

def test_scenario_8_gui_test_is_present():
    """Полный сценарий с окном — tests/test_gui_mainwindow.py (ссылка проверяется)."""
    text = (Path(__file__).parent / "test_gui_mainwindow.py").read_text(encoding="utf-8")
    assert "def test_scenario_8_drag_and_table_undo_redo_save(" in text
    body = text.split("def test_scenario_8_drag_and_table_undo_redo_save(", 1)[1]
    body = body.split("\ndef ", 1)[0]
    for step in ("drag(win.canvas", "table.edit(idx)", "Key_Z, CTRL", "act_undo.trigger",
                 "act_redo.trigger", "win.save_as(out)", "kicadfp.load(out)"):
        assert step in body, step


def test_scenario_8_document_move_undo_redo_save(qtbot, tmp_path, record_property):
    pytest.importorskip("PySide6")
    from kicadfp.gui.commands import SetAttrsCommand, next_merge_id
    from kicadfp.gui.document import FootprintDocument
    from kicadfp.gui.pad_table import COL_X, COL_Y, PadTableModel, format_mm

    lib = tmp_path / "My.pretty"
    lib.mkdir()
    path = lib / DIP14_8.name
    shutil.copyfile(DIP14_8, path)
    doc = FootprintDocument()
    assert doc.open(path)
    table = PadTableModel(doc)
    pad = doc.fp.pad("1")
    row = table.row_of(pad)

    def agree(x: float, y: float) -> None:
        """Модель и таблица показывают одно и то же положение площадки."""
        assert (pad.x, pad.y) == (x, y)
        assert table.data(table.index(row, COL_X)) == format_mm(x)
        assert table.data(table.index(row, COL_Y)) == format_mm(y)

    agree(0.0, 0.0)
    # 1. мышью: канва при перетаскивании применяет одну команду (промежуточные положения —
    #    слияние по merge_id, как при движении мыши с привязкой к сетке 1 мм)
    mid = next_merge_id()
    for x, y in ((-1.0, -1.0), (-2.0, -2.0), (-2.0, -3.0)):
        doc.apply(SetAttrsCommand(doc, pad, {"x": x, "y": y}, "перемещение площадки 1",
                                  merge_id=mid))
    assert doc.undo_stack.count() == 1
    agree(-2.0, -3.0)
    # 2. в таблице: X = 5.08
    assert table.setData(table.index(row, COL_X), "5.08")
    assert doc.undo_stack.count() == 2
    agree(5.08, -3.0)
    # 3. отменить (дважды) и повторить (дважды)
    doc.undo()
    agree(-2.0, -3.0)
    doc.undo()
    agree(0.0, 0.0)
    assert not doc.is_modified
    doc.redo()
    agree(-2.0, -3.0)
    doc.redo()
    agree(5.08, -3.0)
    assert doc.is_modified
    # 4. сохранить: файл содержит итоговые координаты; изменено только (at …) площадки 1
    assert doc.save()
    assert not doc.is_modified
    saved = kicadfp.load(path)
    assert (saved.pad("1").x, saved.pad("1").y) == (5.08, -3.0)
    diffs = sexpr.diff(kicadfp.load(DIP14_8).node, saved.node)
    assert diffs and all(d.startswith("footprint/pad[0]/at") for d in diffs), diffs
    # отмена всего и запись возвращают файл байт в байт
    doc.undo()
    doc.undo()
    assert doc.save()
    assert path.read_bytes() == DIP14_8.read_bytes()
    record_property("undo_steps", 2)
    record_property("final_xy", "5.08; -3")
    doc.confirm_discard = True
    doc.close()


# =============================================================================================
# Г.9. Скопировать корпус из одной библиотеки .pretty в другую с переименованием — в целевой
#      библиотеке файл с новым именем и полем name, исходный не изменён
# =============================================================================================

def _copy_scenario(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    src_dir = tmp_path / "Package_DIP.pretty"
    shutil.copytree(DIP_LIB8, src_dir)
    hashes = {p.name: _sha(p) for p in src_dir.iterdir()}
    src = Library(src_dir)
    dst = Library(tmp_path / "br8_timer.pretty", create=True)
    copy = src.copy_to(dst, "DIP-14_W7.62mm", "dip14_copy")
    assert copy.name == "dip14_copy"
    return src_dir, dst.path, hashes


def test_scenario_9_copy_with_rename(tmp_path, record_property):
    src_dir, dst_dir, hashes = _copy_scenario(tmp_path)
    assert sorted(p.name for p in dst_dir.iterdir()) == ["dip14_copy.kicad_mod"]
    new = kicadfp.load(dst_dir / "dip14_copy.kicad_mod")
    assert new.name == "dip14_copy"
    assert Library(dst_dir).names == ["dip14_copy"]
    # исходная библиотека не изменена: те же файлы, те же байты
    assert {p.name: _sha(p) for p in src_dir.iterdir()} == hashes
    old = kicadfp.load(src_dir / "DIP-14_W7.62mm.kicad_mod")
    assert old.name == "DIP-14_W7.62mm"
    # копия отличается от исходного корпуса только именем (и текстом Value, равным имени)
    diffs = sexpr.diff(old.node, new.node)
    assert diffs == ['footprint: атом 0: "DIP-14_W7.62mm" != "dip14_copy"',
                     'footprint/property[1]: атом 1: "DIP-14_W7.62mm" != "dip14_copy"'], diffs
    record_property("source_files", len(hashes))
    record_property("source_unchanged", True)
    record_property("diff", "; ".join(diffs))


def test_scenario_9_copied_footprint_opens_in_kicad(kicad_cli, tmp_path, record_property):
    _, dst_dir, _ = _copy_scenario(tmp_path)
    res = T.check_library(kicad_cli, dst_dir, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "br8_timer_kicad.pretty" / "dip14_copy.kicad_mod")
    assert back.name == "dip14_copy" and len(back.pads) == 14
    record_property("kicad_cli", T.cli_version(kicad_cli))


# =============================================================================================
# Г.10. Преобразовать библиотеку старого формата .mod (PCBnew-LibModule-V1) в .pretty —
#       каждый модуль отдельным файлом, единицы переведены из децимил в мм, открывается в KiCad
# =============================================================================================

_DECIMIL = 0.00254   # мм в 1/10000 дюйма


def _raw_modules(path: Path) -> dict[str, dict[str, list]]:
    """Независимый мини-разбор .mod: сырые числа (деци-милы) площадок (Sh/Dr/Po), отрезков
    DS и текстов T0/T1 по модулям."""
    mods: dict[str, dict[str, list]] = {}
    cur = pad = None
    for line in path.read_text("latin-1").splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == "$MODULE":
            cur = mods.setdefault(w[1], {"pads": [], "lines": [], "texts": []})
        elif cur is None:
            continue
        elif w[0] == "$PAD":
            pad = {}
        elif w[0] == "Sh" and pad is not None:
            pad["size"] = (int(w[3]), int(w[4]))
        elif w[0] == "Dr" and pad is not None:
            pad["drill"] = int(w[1])
        elif w[0] == "Po" and pad is not None:
            pad["pos"] = (int(w[1]), int(w[2]))
        elif w[0] == "$EndPAD" and pad is not None:
            cur["pads"].append(pad)
            pad = None
        elif w[0] == "DS":
            cur["lines"].append(tuple(int(v) for v in w[1:6]))
        elif w[0] in ("T0", "T1"):
            cur["texts"].append((int(w[1]), int(w[2]), int(w[3]), int(w[4]), int(w[6])))
        elif w[0] == "$EndMODULE":
            cur = None
    return mods


def test_scenario_10_convert_legacy_library(tmp_path, record_property):
    out = tmp_path / "My_lib.pretty"
    paths = legacy.convert(MY_LIB, out)
    raw = _raw_modules(MY_LIB)
    index = MY_LIB.read_text("latin-1").split("$INDEX", 1)[1].split("$EndINDEX", 1)[0].split()
    # каждый модуль — отдельный файл .kicad_mod с именем модуля
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{n}.kicad_mod" for n in index)
    assert sorted(raw) == sorted(index) == ["dip14", "mlt", "snp8"]
    checked = 0
    for p in paths:
        fp = kicadfp.load(p)
        assert fp.name == p.stem and fp.version == KICAD_FORMAT_VERSIONS[9]
        mod = raw[fp.name]
        # единицы: деци-милы × 0.00254 = мм (точно до нанометра)
        mine = sorted((round(q.x, 6), round(q.y, 6), round(q.size_x, 6), round(q.size_y, 6),
                       round(q.drill.diameter, 6)) for q in fp.pads)
        theirs = sorted((round(r["pos"][0] * _DECIMIL, 6), round(r["pos"][1] * _DECIMIL, 6),
                         round(r["size"][0] * _DECIMIL, 6), round(r["size"][1] * _DECIMIL, 6),
                         round(r["drill"] * _DECIMIL, 6)) for r in mod["pads"])
        assert mine == theirs
        lines = sorted((round(g.start[0], 6), round(g.start[1], 6), round(g.end[0], 6),
                        round(g.end[1], 6), round(g.width, 6))
                       for g in fp.graphics if g.kind == "line")
        assert lines == sorted(tuple(round(v * _DECIMIL, 6) for v in ln) for ln in mod["lines"])
        texts = sorted((round(t.x, 6), round(t.y, 6), round(t.font_size_y, 6),
                        round(t.font_size_x, 6), round(t.thickness, 6))
                       for t in (fp.reference, fp.value))
        assert texts == sorted(tuple(round(v * _DECIMIL, 6) for v in t) for t in mod["texts"])
        checked += len(mine) + len(lines) + len(texts)
        assert fp.pads[0].size_x in (1.30048, 2.99974)       # 512 или 1181 деци-мил
    record_property("modules", len(paths))
    record_property("values_checked", checked)
    record_property("files", ", ".join(p.name for p in paths))


def test_scenario_10_cli_convert(tmp_path, capsys):
    out = tmp_path / "old_lib.pretty"
    assert kcli.main(["convert", str(MY_LIB), "-o", str(out)]) == 0
    stdout, _ = capsys.readouterr()
    assert "преобразовано корпусов: 3" in stdout

    def text(p: Path) -> str:   # новые uuid у каждого преобразования свои
        return re.sub(r'\(uuid "[0-9a-f-]+"\)', '(uuid "…")', p.read_text(encoding="utf-8"))

    assert {p.name: text(p) for p in out.iterdir()} == \
        {p.name: text(p) for p in legacy.convert(MY_LIB, tmp_path / "api.pretty")}


@pytest.mark.parametrize("which", ["kicad9", "kicad8"])
def test_scenario_10_converted_library_opens_in_kicad(which, request, tmp_path,
                                                       record_property):
    """Результат открывается в KiCad 9 (формат по умолчанию) и KiCad 8 (``version=8`` /
    ``kicadfp convert --kicad 8``); содержимое — как у собственного конвертера KiCad
    (``kicad-cli fp upgrade My_lib.mod``)."""
    cli = request.getfixturevalue("kicad_cli" if which == "kicad9" else "kicad8_cli")
    kicad = 9 if which == "kicad9" else 8
    out = tmp_path / "My_lib.pretty"
    paths = legacy.convert(MY_LIB, out, version=kicad)
    res = T.check_library(cli, out, tmp_path)
    assert res.ok, res.report()
    assert res.compared == len(paths) == 3
    ref = T.upgrade(cli, MY_LIB, tmp_path / "kicad_converted.pretty")
    assert ref.ok, str(ref)
    same = 0
    for p in paths:
        theirs = kicadfp.load(tmp_path / "kicad_converted.pretty" / p.name)
        assert T.compare(T.signature(kicadfp.load(p)), T.signature(theirs)) == []
        same += 1
    record_property("kicad_cli", T.cli_version(cli))
    record_property("format_version", KICAD_FORMAT_VERSIONS[kicad])
    record_property("same_as_kicad_converter", same)


# =============================================================================================
# Сводка: объём проверок (для отчёта)
# =============================================================================================

def test_acceptance_fixture_inventory(record_property):
    counts = {d: len(fixture_files(d)) for d in ("kicad5", "kicad6", "kicad8", "kicad9",
                                                  "kicad10dev")}
    counts["special"] = len(sorted((FIXTURES / "special").rglob("*.kicad_mod")))
    for k, v in counts.items():
        record_property(k, v)
    record_property("extra_fixtures", len(extra_fixture_files()))
    assert counts["kicad8"] >= 200 and counts["special"] >= 200
