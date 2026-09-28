"""Тесты :mod:`kicadfp.io`: load/loads/save/dumps, определение формата, атомарная запись,
strict-проверка, сценарий 3 ТЗ (неизвестный узел сохраняется)."""

from __future__ import annotations

import os
import stat
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

import kicadfp
from kicadfp import io as kio
from kicadfp import sexpr
from kicadfp.io import LegacyLibraryError, ValidationError, detect_format
from kicadfp.model import Footprint
from kicadfp.sexpr import SexprSyntaxError
from tests.conftest import FIXTURES
from tests.test_model_common import DIP14, changed_lines, tree_changes

CP_ELEC9 = FIXTURES / "kicad9" / "Capacitor_SMD.pretty" / "CP_Elec_10x10.5.kicad_mod"


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_load_and_loads_all_versions(version):
    fp = kicadfp.load(DIP14[version])
    assert isinstance(fp, Footprint) and fp.name == "DIP-14_W7.62mm"
    text = DIP14[version].read_text(encoding="utf-8")
    fp2 = kicadfp.loads(text)
    assert sexpr.equal(fp.node, fp2.node, ignore_quotes=False)
    assert kicadfp.loads(text.encode("utf-8")).name == fp.name
    assert kio.load(str(DIP14[version])).name == fp.name


def test_bom_and_crlf_are_accepted(tmp_path):
    text = DIP14["kicad8"].read_text(encoding="utf-8")
    crlf = "﻿" + text.replace("\n", "\r\n")
    fp = kicadfp.loads(crlf)
    assert sexpr.equal(fp.node, kicadfp.loads(text).node, ignore_quotes=False)
    p = tmp_path / "bom.kicad_mod"
    p.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    fp2 = kicadfp.load(p)
    assert fp2.pad(14).position == (7.62, 0)
    out = tmp_path / "out.kicad_mod"
    kicadfp.save(fp2, out)
    data = out.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data   # UTF-8 без BOM, LF


def test_syntax_error_has_line_and_position(tmp_path):
    with pytest.raises(SexprSyntaxError) as ei:
        kicadfp.loads('(footprint "x"\n  (layer "F.Cu")\n  (descr "open')
    e = ei.value
    assert (e.line, e.col) == (3, 10) and str(e).startswith("строка 3, позиция 10:")
    bad = tmp_path / "bad.kicad_mod"
    bad.write_text('(footprint "x"\n  (layer "F.Cu"))\n)\n', encoding="utf-8")
    with pytest.raises(SexprSyntaxError) as ei:
        kicadfp.load(bad)
    assert ei.value.line == 3 and ei.value.path == str(bad)      # type: ignore[attr-defined]
    with pytest.raises(SexprSyntaxError) as ei:
        kicadfp.loads('(footprint "x" (layer "F.Cu")')
    assert "незакрытая скобка" in str(ei.value)


@pytest.mark.parametrize("text,line,col,fragment", [
    ("", 1, 1, "пустой ввод"),
    ("   \n\t\n", 1, 1, "пустой ввод"),
    ("hello world", 1, 1, "неизвестный формат"),
    ("\n\n  junk", 3, 3, "неизвестный формат"),
    ("# comment\n{}", 2, 1, "неизвестный формат"),
    ("(kicad_pcb (version 20241229))", 1, 1, "kicad_pcb"),
])
def test_unknown_format_errors(text, line, col, fragment):
    with pytest.raises(SexprSyntaxError) as ei:
        kicadfp.loads(text)
    assert (ei.value.line, ei.value.col) == (line, col) and fragment in str(ei.value)


def test_detect_format_and_comments():
    assert detect_format('(footprint "x")') == "sexpr"
    assert detect_format("﻿  \n(module x)") == "sexpr"
    assert detect_format("PCBNEW-LibModule-V1  01/01/2011\n") == "legacy"
    assert detect_format("pcbnew-libmodule-v1\n") == "legacy"          # без учёта регистра
    assert detect_format("# c\n(footprint x)") == "sexpr"
    assert detect_format("junk") is None
    fp = kicadfp.loads('# header comment\n(footprint "X" (version 20241229) (generator "g") '
                       '(layer "F.Cu"))')
    assert fp.node.comments == ["# header comment"]
    assert kicadfp.dumps(fp).startswith("# header comment\n(footprint \"X\"")


def test_legacy_library_is_not_a_single_footprint():
    path = FIXTURES / "legacy_mod" / "My_lib.mod"
    with pytest.raises(LegacyLibraryError) as ei:
        kicadfp.load(path)
    assert isinstance(ei.value, ValueError)
    # модуль kicadfp.legacy может ещё отсутствовать; если он есть — в библиотеке 3 корпуса
    assert ei.value.count in (None, 3)


def test_legacy_single_module_via_legacy_module(monkeypatch):
    one = Footprint.new("ONE")
    fake = types.ModuleType("kicadfp.legacy")
    fake.loads_library = lambda text, **kw: [one]                   # type: ignore[attr-defined]
    fake.read_library = lambda path, **kw: [one, Footprint.new("TWO")]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kicadfp.legacy", fake)
    assert kicadfp.loads("PCBNEW-LibModule-V1 x\n$INDEX\n") is one
    with pytest.raises(LegacyLibraryError) as ei:
        kicadfp.load(FIXTURES / "legacy_mod" / "My_lib.mod")
    assert ei.value.count == 2 and "read_library" in str(ei.value)
    fake.loads_library = lambda text, **kw: []                      # type: ignore[attr-defined]
    with pytest.raises(LegacyLibraryError) as ei:
        kicadfp.loads("PCBNEW-LibModule-V1 x\n")
    assert ei.value.count == 0


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

def test_save_atomic_and_reads_back_equal(tmp_path):
    fp = kicadfp.load(CP_ELEC9)
    out = tmp_path / "lib.pretty" / "CP.kicad_mod"
    out.parent.mkdir()
    kicadfp.save(fp, out)
    assert out.read_bytes() == CP_ELEC9.read_bytes()       # файл KiCad 9 — байт в байт
    again = kicadfp.load(out)
    assert sexpr.equal(again.node, fp.node, ignore_quotes=False)
    assert sorted(p.name for p in out.parent.iterdir()) == ["CP.kicad_mod"]   # нет временных
    fp.descr = "changed"
    kicadfp.save(fp, str(out))                            # перезапись существующего
    assert kicadfp.load(out).descr == "changed"
    assert sorted(p.name for p in out.parent.iterdir()) == ["CP.kicad_mod"]


@pytest.mark.skipif(os.name != "posix", reason="права доступа POSIX")
def test_save_preserves_permissions(tmp_path):
    fp = kicadfp.load(DIP14["kicad8"])
    out = tmp_path / "a.kicad_mod"
    kicadfp.save(fp, out)
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE(out.stat().st_mode) == 0o666 & ~mask
    os.chmod(out, 0o640)
    kicadfp.save(fp, out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o640


def test_save_failure_keeps_original(tmp_path, monkeypatch):
    fp = kicadfp.load(DIP14["kicad8"])
    out = tmp_path / "a.kicad_mod"
    out.write_text("original", encoding="utf-8")

    def boom(src, dst):
        raise OSError("диск переполнен")

    monkeypatch.setattr(kio.os, "replace", boom)
    with pytest.raises(OSError):
        kicadfp.save(fp, out)
    assert out.read_text(encoding="utf-8") == "original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.kicad_mod"]


@pytest.mark.skipif(os.name != "posix", reason="символические ссылки POSIX")
def test_save_through_symlink_writes_target(tmp_path):
    target = tmp_path / "real.kicad_mod"
    link = tmp_path / "link.kicad_mod"
    fp = kicadfp.load(DIP14["kicad8"])
    kicadfp.save(fp, target)
    link.symlink_to(target)
    fp.descr = "via link"
    kicadfp.save(fp, link)
    assert link.is_symlink() and kicadfp.load(target).descr == "via link"


@dataclass
class _Issue:
    level: str
    code: str
    message: str = ""

    def __str__(self) -> str:
        return f"{self.level} {self.code}: {self.message}"


def _fake_validate(monkeypatch, issues):
    mod = types.ModuleType("kicadfp.validate")
    mod.validate = lambda fp, strict=False: list(issues)            # type: ignore[attr-defined]
    mod.has_errors = lambda iss: any(i.level == "error" for i in iss)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kicadfp.validate", mod)


def test_save_strict_raises_on_errors(tmp_path, monkeypatch):
    fp = kicadfp.load(DIP14["kicad8"])
    out = tmp_path / "a.kicad_mod"
    _fake_validate(monkeypatch, [_Issue("error", "PAD_THT_NO_DRILL", "площадка 1 без отверстия"),
                                 _Issue("warning", "COURTYARD_MISSING")])
    with pytest.raises(ValidationError) as ei:
        kicadfp.save(fp, out, strict=True)
    assert not out.exists()
    assert len(ei.value.issues) == 2 and len(ei.value.errors) == 1
    assert "PAD_THT_NO_DRILL" in str(ei.value)
    kicadfp.save(fp, out)                                # без strict — пишется
    assert out.exists()


def test_save_strict_with_warnings_only_writes(tmp_path, monkeypatch):
    fp = kicadfp.load(DIP14["kicad8"])
    out = tmp_path / "a.kicad_mod"
    _fake_validate(monkeypatch, [_Issue("warning", "COURTYARD_MISSING")])
    kicadfp.save(fp, out, strict=True)
    assert kicadfp.load(out).name == fp.name


def test_save_strict_real_validate(tmp_path):
    fp = kicadfp.load(DIP14["kicad8"])
    out = tmp_path / "a.kicad_mod"
    kicadfp.save(fp, out, strict=True)                   # корпус из библиотеки KiCad корректен
    assert out.exists()


def test_dumps_styles_and_type_errors(tmp_path):
    fp = kicadfp.load(DIP14["kicad6"])
    assert kicadfp.dumps(fp) == DIP14["kicad6"].read_text(encoding="utf-8")
    assert kicadfp.dumps(fp, style="kicad8").startswith('(footprint "DIP-14_W7.62mm"\n\t(version')
    with pytest.raises(ValueError):
        kicadfp.dumps(fp, style="kicad99")
    with pytest.raises(TypeError):
        kicadfp.dumps("x")                               # type: ignore[arg-type]
    with pytest.raises(TypeError):
        kicadfp.save(fp.node, tmp_path / "x.kicad_mod")  # type: ignore[arg-type]


def test_invalid_utf8_bytes_roundtrip(tmp_path):
    raw = DIP14["kicad8"].read_bytes().replace(b"14-lead", b"14-lead \xff\xfe", 1)
    src = tmp_path / "raw.kicad_mod"
    src.write_bytes(raw)
    fp = kicadfp.load(src)
    out = tmp_path / "out.kicad_mod"
    kicadfp.save(fp, out)
    assert out.read_bytes() == raw


@pytest.mark.parametrize("path", [
    CP_ELEC9,
    FIXTURES / "kicad9" / "Package_DFN_QFN.pretty" / "Texas_RGY_R-PVQFN-N24_EP2.05x3.1mm_ThermalVias.kicad_mod",
    FIXTURES / "kicad10dev" / "Capacitor_SMD.pretty" / "CP_Elec_10x10.5.kicad_mod",
    FIXTURES / "kicad8" / "Capacitor_THT.pretty" / "CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod",  # KiCad 8.0.0: без \n в конце
    DIP14["kicad8"], DIP14["kicad6"], DIP14["kicad5"],
])
def test_load_save_roundtrip_bytes(tmp_path, path):
    out = tmp_path / path.name
    kicadfp.save(kicadfp.load(path), out)
    assert out.read_bytes() == path.read_bytes()


def test_kicad8_fixtures_without_final_newline_are_byte_identical():
    """Регрессия: файлы KiCad 8.0.0/8.0.1 (все фикстуры kicad8) не оканчиваются ``\n``, и
    load + dumps без изменений воспроизводит их байт в байт (раньше дописывался ``\n``)."""
    files = sorted((FIXTURES / "kicad8").rglob("*.kicad_mod"))
    assert len(files) > 1000
    for path in files:
        raw = path.read_bytes()
        assert not raw.endswith(b"\n"), path
        fp = kicadfp.load(path)
        assert fp.final_newline is False
        assert kio.dumps(fp).encode("utf-8") == raw, path


def test_final_newline_is_remembered_and_overridable(tmp_path):
    text = DIP14["kicad8"].read_text(encoding="utf-8")
    assert not text.endswith("\n")
    fp = kicadfp.loads(text)
    assert fp.final_newline is False and fp.dumps() == text == kicadfp.dumps(fp)
    # изменённый корпус сохраняет стиль конца файла (без лишнего diff)
    fp.descr = "x"
    assert not kicadfp.dumps(fp).endswith("\n")
    assert kicadfp.dumps(fp, final_newline=True).endswith(")\n")
    assert fp.copy().final_newline is False
    with_nl = kicadfp.loads(text + "\n")
    assert with_nl.final_newline is True and kicadfp.dumps(with_nl) == text + "\n"
    assert kicadfp.dumps(with_nl, final_newline=False) == text
    out = tmp_path / "x.kicad_mod"
    kicadfp.save(fp, out, final_newline=True)
    assert out.read_bytes().endswith(b")\n")
    # новый корпус и upgrade() — как KiCad 8.0.2+/9: с переводом строки
    assert Footprint.new("N").final_newline and kicadfp.dumps(Footprint.new("N")).endswith(")\n")
    fp.upgrade()
    assert fp.final_newline is True and kicadfp.dumps(fp).endswith(")\n")


# ---------------------------------------------------------------------------
# Сценарий 3 ТЗ: неизвестный узел сохраняется
# ---------------------------------------------------------------------------

def test_scenario3_unknown_node_is_preserved(tmp_path):
    text = DIP14["kicad8"].read_text(encoding="utf-8")
    text = text.replace("\t(attr through_hole)\n", "\t(attr through_hole)\n\t(example_token 1 2)\n", 1)
    text = text.replace('\t\t(uuid "c59ff4fb-10d1-49fb-80e5-f15385e71fb6")\n',
                        '\t\t(uuid "c59ff4fb-10d1-49fb-80e5-f15385e71fb6")\n'
                        '\t\t(example_token "a" (nested 3))\n', 1)
    text = sexpr.dumps(sexpr.parse(text))      # раскладка KiCad 8 для вставленных узлов
    src = tmp_path / "DIP-14_W7.62mm.kicad_mod"
    src.write_text(text, encoding="utf-8")
    fp = kicadfp.load(src)
    original = fp.node.copy()
    assert [n.name for n in fp.unknown] == ["example_token"]
    fp.pad(1).size = (1.7, 1.7)
    kicadfp.save(fp, src)
    saved_text = src.read_text(encoding="utf-8")
    saved = sexpr.parse(saved_text)
    # узел на месте и без изменений
    assert sexpr.to_compact(saved.find("example_token")) == "(example_token 1 2)"
    names = [n.name for n in saved.nodes()]
    assert names[names.index("attr") + 1] == "example_token"
    pad1 = saved.find("pad")
    assert sexpr.to_compact(pad1.find("example_token")) == '(example_token "a"(nested 3))'
    # различия деревьев — только размер площадки 1
    assert tree_changes(original, saved) == ["footprint/pad/size: Y:1.6 -> Y:1.7",
                                             "footprint/pad/size: Y:1.6 -> Y:1.7"]
    removed, added = changed_lines(text, saved_text)
    assert removed == ["\t\t(size 1.6 1.6)"] and added == ["\t\t(size 1.7 1.7)"]


def test_package_exports():
    for name in ("load", "loads", "save", "dumps", "Footprint", "Pad", "Drill", "Line", "Rect",
                 "Circle", "Arc", "Poly", "Curve", "Text", "Model", "BBox", "SexprSyntaxError",
                 "__version__"):
        assert hasattr(kicadfp, name), name
    assert kicadfp.__version__.count(".") == 2
    with pytest.raises(AttributeError):
        kicadfp.no_such_name  # noqa: B018


def test_package_picks_up_optional_modules(tmp_path):
    """Когда появятся kicadfp/validate.py и kicadfp/library.py, ``kicadfp.validate`` — функция
    (а не подмодуль), ``kicadfp.Issue``/``kicadfp.Library`` доступны; проверка — на копии
    пакета с модулями-заглушками."""
    import shutil
    import subprocess
    import textwrap

    pkg = tmp_path / "kicadfp"
    shutil.copytree(Path(kicadfp.__file__).parent, pkg,
                    ignore=shutil.ignore_patterns("__pycache__", "validate.py", "library.py"))
    (pkg / "validate.py").write_text(textwrap.dedent('''
        from dataclasses import dataclass
        from .model import Footprint

        @dataclass
        class Issue:
            level: str
            code: str

        def validate(fp: Footprint, strict: bool = False):
            return [Issue("warning", "STUB")]

        def has_errors(issues):
            return any(i.level == "error" for i in issues)
    '''), encoding="utf-8")
    (pkg / "library.py").write_text("class Library:\n    pass\n", encoding="utf-8")
    code = textwrap.dedent(f'''
        import kicadfp
        fp = kicadfp.load({str(DIP14["kicad8"])!r})
        assert [i.code for i in fp.validate()] == ["STUB"]
        import sys
        vmod = sys.modules["kicadfp.validate"]   # «import kicadfp.validate as m» дал бы функцию
        assert callable(kicadfp.validate) and kicadfp.validate is vmod.validate
        assert kicadfp.validate(fp)[0].code == "STUB"
        assert kicadfp.Issue is vmod.Issue and kicadfp.Library.__name__ == "Library"
        assert "validate" in kicadfp.__all__
        print("ok")
    ''')
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       cwd=str(tmp_path), timeout=120)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="нужен os.mkfifo (POSIX)")
def test_save_into_fifo_keeps_fifo(tmp_path):
    """Регрессия: запись в существующий FIFO (как в /dev/null, /dev/stdout) идёт прямо в
    него; FIFO не заменяется обычным файлом."""
    import threading

    target = tmp_path / "out.kicad_mod"
    os.mkfifo(target)
    got: list[bytes] = []

    def reader() -> None:
        with open(target, "rb") as f:
            got.append(f.read())

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    fp = Footprint.new("X")
    kicadfp.save(fp, target)
    t.join(10)
    assert not t.is_alive()
    assert stat.S_ISFIFO(os.stat(target).st_mode)
    assert got == [fp.dumps().encode("utf-8")]
    assert [p.name for p in tmp_path.iterdir()] == ["out.kicad_mod"]   # без временных файлов


def test_save_into_char_device_and_directory(tmp_path):
    """Символьное устройство пишется напрямую (узел не заменяется); каталог — ошибка."""
    null = Path(os.devnull)
    if os.name == "posix" and null.exists() and stat.S_ISCHR(os.stat(null).st_mode) \
            and os.access(null, os.W_OK):
        kicadfp.save(Footprint.new("X"), null)
        assert stat.S_ISCHR(os.stat(null).st_mode)
    d = tmp_path / "dir.kicad_mod"
    d.mkdir()
    with pytest.raises(IsADirectoryError):
        kicadfp.save(Footprint.new("X"), d)
    assert d.is_dir() and list(d.iterdir()) == []
