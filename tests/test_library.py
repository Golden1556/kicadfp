"""Тесты :mod:`kicadfp.library`: открытие/создание каталога .pretty, перечисление, кэш get,
add/save/save_all, remove, rename, copy_to (сценарий 9 ТЗ), sanitize_name, validate_all."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import kicadfp
from kicadfp import sexpr
from kicadfp.io import ValidationError
from kicadfp.library import Library, sanitize_name
from kicadfp.model import Footprint
from tests.conftest import FIXTURES

DIP8 = FIXTURES / "kicad8" / "Package_DIP.pretty"
DIP14_NAME = "DIP-14_W7.62mm"


def _copy_lib(src: Path, dst: Path, names: list[str]) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy2(src / f"{n}.kicad_mod", dst / f"{n}.kicad_mod")
    return dst


@pytest.fixture
def src_lib(tmp_path: Path) -> Path:
    """Копия трёх корпусов kicad8/Package_DIP.pretty во временном каталоге."""
    return _copy_lib(DIP8, tmp_path / "src.pretty",
                     [DIP14_NAME, "DIP-8_W7.62mm", "DIP-16_W7.62mm"])


def _snapshot(d: Path) -> dict[str, tuple[bytes, int]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(d.iterdir())}


# ---------------------------------------------------------------------------
# sanitize_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, fixed", [
    ("DIP-14_W7.62mm", "DIP-14_W7.62mm"),
    ("a/b\\c:d*e?f\"g<h>i|j", "a_b_c_d_e_f_g_h_i_j"),
    ("tab\there\nnl\rcr\x01", "tab_here_nl_cr_"),
    ("with space", "with space"),                 # пробел допустим (как в KiCad)
    ("корпус%$", "корпус%$"),                     # Unicode, % и $ не заменяются
    ("..", ".."),
    ("///", "___"),
])
def test_sanitize_name(raw, fixed):
    assert sanitize_name(raw) == fixed
    assert len(sanitize_name(raw)) == len(raw)


def test_sanitize_name_errors():
    with pytest.raises(ValueError):
        sanitize_name("")
    with pytest.raises(TypeError):
        sanitize_name(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Открытие, перечисление
# ---------------------------------------------------------------------------

def test_open_missing_and_create(tmp_path):
    missing = tmp_path / "nope.pretty"
    with pytest.raises(FileNotFoundError):
        Library(missing)
    lib = Library(missing, create=True)
    assert missing.is_dir() and lib.path == missing and lib.name == "nope"
    assert lib.names == [] and len(lib) == 0 and list(lib) == []
    Library(missing, create=True)                  # повторное создание — не ошибка
    nested = Library(tmp_path / "a" / "b" / "deep.pretty", create=True)
    assert nested.path.is_dir() and nested.name == "deep"
    f = tmp_path / "file.pretty"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        Library(f)
    assert Library(tmp_lib_dir := tmp_path / "plain", create=True).name == "plain"
    assert tmp_lib_dir.is_dir()


def test_list_kicad8_package_dip():
    lib = Library(DIP8)
    files = sorted(p.stem for p in DIP8.glob("*.kicad_mod"))
    # в kicad-footprints 8.0.0 Package_DIP.pretty — 268 файлов (281 — в ветке master)
    assert len(files) == 268
    assert lib.names == files == lib.list() == list(lib)
    assert len(lib) == 268
    assert DIP14_NAME in lib and "nope" not in lib and "a/b" not in lib and 5 not in lib
    assert lib.name == "Package_DIP"
    assert lib.path_of(DIP14_NAME) == DIP8 / f"{DIP14_NAME}.kicad_mod"


def test_names_ignore_other_entries(tmp_lib):
    (tmp_lib / "readme.txt").write_text("x")
    (tmp_lib / "sub.kicad_mod").mkdir()           # каталог с «расширением» — не корпус
    (tmp_lib / ".kicad_mod").write_text("x")      # пустое имя — не корпус
    shutil.copy2(DIP8 / f"{DIP14_NAME}.kicad_mod", tmp_lib / "A.kicad_mod")
    shutil.copy2(DIP8 / f"{DIP14_NAME}.kicad_mod", tmp_lib / "b.kicad_mod")
    assert Library(tmp_lib).names == ["A", "b"]


def test_path_of_rejects_separators(tmp_lib):
    lib = Library(tmp_lib)
    with pytest.raises(ValueError):
        lib.path_of("../evil")
    with pytest.raises(ValueError):
        lib.path_of("")
    with pytest.raises(KeyError):
        lib.get("../evil")


# ---------------------------------------------------------------------------
# get: кэш
# ---------------------------------------------------------------------------

def test_get_cache(src_lib):
    lib = Library(src_lib)
    fp = lib.get(DIP14_NAME)
    assert isinstance(fp, Footprint) and fp.name == DIP14_NAME
    assert lib.get(DIP14_NAME) is fp               # тот же объект из кэша
    assert not lib.is_modified(DIP14_NAME) and lib.unsaved == []
    with pytest.raises(KeyError):
        lib.get("missing")
    with pytest.raises(KeyError):
        lib.is_modified("missing")
    # изменение объекта из кэша видно в is_modified и записывается save_all
    fp.pad(1).shape = "rect" if fp.pad(1).shape != "rect" else "oval"
    assert lib.is_modified(DIP14_NAME) and lib.unsaved == [DIP14_NAME]
    written = lib.save_all()
    assert written == [src_lib / f"{DIP14_NAME}.kicad_mod"]
    assert not lib.is_modified(DIP14_NAME)
    again = kicadfp.load(written[0])
    assert again.pad(1).shape == fp.pad(1).shape
    # refresh забывает неизменённые — следующий get читает файл заново
    lib.refresh()
    fp2 = lib.get(DIP14_NAME)
    assert fp2 is not fp and sexpr.equal(fp2.node, fp.node)


def test_get_syntax_error_not_cached(tmp_lib):
    (tmp_lib / "bad.kicad_mod").write_text('(footprint "bad"\n  (layer "F.Cu")\n')
    lib = Library(tmp_lib)
    with pytest.raises(kicadfp.SexprSyntaxError):
        lib.get("bad")
    assert lib.unsaved == []
    with pytest.raises(kicadfp.SexprSyntaxError):
        lib.get("bad")


def test_save_all_does_not_touch_unmodified(src_lib):
    lib = Library(src_lib)
    before = _snapshot(src_lib)
    for n in lib:
        lib.get(n)
    assert lib.save_all() == []
    assert _snapshot(src_lib) == before


# ---------------------------------------------------------------------------
# add / save / overwrite
# ---------------------------------------------------------------------------

def test_add_and_save_all(tmp_lib):
    lib = Library(tmp_lib)
    fp = Footprint.new("dip14")
    lib.add(fp)
    assert "dip14" in lib and lib.names == ["dip14"] and len(lib) == 1
    assert not (tmp_lib / "dip14.kicad_mod").exists()   # файл пишется только при сохранении
    assert lib.get("dip14") is fp and lib.unsaved == ["dip14"]
    paths = lib.save_all()
    assert paths == [tmp_lib / "dip14.kicad_mod"]
    assert kicadfp.load(paths[0]).name == "dip14"
    assert lib.unsaved == [] and lib.save_all() == []
    assert Library(tmp_lib).names == ["dip14"]
    # save(name) не читавшегося корпуса файл не трогает
    lib2 = Library(tmp_lib)
    before = _snapshot(tmp_lib)
    assert lib2.save("dip14") == tmp_lib / "dip14.kicad_mod"
    assert _snapshot(tmp_lib) == before
    with pytest.raises(KeyError):
        lib2.save("missing")


def test_add_with_name_syncs_name_field_and_value(tmp_lib):
    lib = Library(tmp_lib)
    fp = Footprint.new("orig")
    assert fp.value.text == "orig"
    lib.add(fp, "new:name/1")
    assert lib.names == ["new_name_1"]
    assert fp.name == "new_name_1" and fp.value.text == "new_name_1"
    path = lib.save("new_name_1")
    assert path.name == "new_name_1.kicad_mod"
    back = kicadfp.load(path)
    assert back.name == "new_name_1" and back.value.text == "new_name_1"
    # Value, отличный от имени, не трогается
    fp2 = Footprint.new("x", value="custom value")
    lib.add(fp2, "y")
    assert fp2.name == "y" and fp2.value.text == "custom value"


def test_add_overwrite_and_file_exists(src_lib):
    lib = Library(src_lib)
    original = (src_lib / f"{DIP14_NAME}.kicad_mod").read_bytes()
    fp = Footprint.new(DIP14_NAME)
    with pytest.raises(FileExistsError):
        lib.add(fp)                                  # файл есть на диске
    lib.add(Footprint.new("pending"))
    with pytest.raises(FileExistsError):
        lib.add(Footprint.new("pending"))            # добавлен, но не записан
    assert (src_lib / f"{DIP14_NAME}.kicad_mod").read_bytes() == original
    lib.get(DIP14_NAME)                              # в кэше — старый корпус
    lib.add(fp, overwrite=True)
    assert lib.get(DIP14_NAME) is fp
    assert (src_lib / f"{DIP14_NAME}.kicad_mod").read_bytes() == original
    written = lib.save_all()
    assert sorted(p.name for p in written) == sorted([f"{DIP14_NAME}.kicad_mod",
                                                      "pending.kicad_mod"])
    back = kicadfp.load(src_lib / f"{DIP14_NAME}.kicad_mod")
    assert back.pads == [] and back.name == DIP14_NAME


def test_add_type_and_empty_name(tmp_lib):
    lib = Library(tmp_lib)
    with pytest.raises(TypeError):
        lib.add("not a footprint")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        lib.add(Footprint.new("x"), "")
    assert lib.names == []


def test_save_syncs_name_with_file_name(tmp_lib):
    lib = Library(tmp_lib)
    fp = Footprint.new("a")
    lib.add(fp)
    fp.name = "something_else"                       # пользователь поменял поле name
    path = lib.save("a")
    assert kicadfp.load(path).name == "a" and fp.name == "a"


def test_save_strict(tmp_lib):
    lib = Library(tmp_lib)
    good = Footprint.new("good")
    bad = Footprint.new("bad")
    bad.new_pad(1, type="thru_hole", size=(1.3, 1.3), drill=1.5)   # отверстие больше площадки
    lib.add(good)
    lib.add(bad)
    with pytest.raises(ValidationError):
        lib.save("bad", strict=True)
    with pytest.raises(ValidationError):
        lib.save_all(strict=True)
    assert list(tmp_lib.iterdir()) == []             # ничего не записано
    assert lib.unsaved == ["bad", "good"]
    assert len(lib.save_all()) == 2                  # без strict — пишется


def test_scenario_v1_api_example(tmp_path):
    """Пример В.1 ТЗ: изменить корпус, переименовать, сохранить в другую библиотеку."""
    fp = kicadfp.load(DIP8 / f"{DIP14_NAME}.kicad_mod")
    for pad in fp.pads:
        pad.size_x = pad.size_y = 1.3
        pad.drill.diameter = 0.8
    fp.pad("1").shape = "rect"
    fp.name = "dip14"
    lib = Library(tmp_path / "br8_timer.pretty", create=True)
    lib.add(fp)
    assert lib.save_all() == [tmp_path / "br8_timer.pretty" / "dip14.kicad_mod"]
    back = Library(tmp_path / "br8_timer.pretty").get("dip14")
    assert back.name == "dip14" and back.pad("1").shape == "rect"
    assert all(p.drill.diameter == 0.8 for p in back.pads)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def test_remove(src_lib):
    lib = Library(src_lib)
    lib.get(DIP14_NAME)
    lib.remove(DIP14_NAME)
    assert not (src_lib / f"{DIP14_NAME}.kicad_mod").exists()
    assert DIP14_NAME not in lib and DIP14_NAME not in lib.names
    with pytest.raises(KeyError):
        lib.get(DIP14_NAME)
    with pytest.raises(KeyError):
        lib.remove(DIP14_NAME)
    # удаление добавленного, но не записанного корпуса
    lib.add(Footprint.new("tmp"))
    lib.remove("tmp")
    assert "tmp" not in lib and lib.save_all() == []
    assert sorted(p.name for p in src_lib.iterdir()) == ["DIP-16_W7.62mm.kicad_mod",
                                                         "DIP-8_W7.62mm.kicad_mod"]


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------

def test_rename(src_lib):
    lib = Library(src_lib)
    other_before = (src_lib / "DIP-8_W7.62mm.kicad_mod").read_bytes()
    lib.rename(DIP14_NAME, "dip14")
    assert not (src_lib / f"{DIP14_NAME}.kicad_mod").exists()
    new_path = src_lib / "dip14.kicad_mod"
    assert new_path.is_file()
    fp = kicadfp.load(new_path)
    assert fp.name == "dip14" and fp.value.text == "dip14"
    assert lib.names == ["DIP-16_W7.62mm", "DIP-8_W7.62mm", "dip14"]
    assert lib.get("dip14").name == "dip14" and not lib.is_modified("dip14")
    # остальное содержимое не изменилось: отличие деревьев — только имя и Value
    orig = kicadfp.load(DIP8 / f"{DIP14_NAME}.kicad_mod")
    orig.name = "dip14"
    orig.value.text = "dip14"
    assert sexpr.equal(orig.node, fp.node, ignore_quotes=False)
    assert (src_lib / "DIP-8_W7.62mm.kicad_mod").read_bytes() == other_before
    with pytest.raises(KeyError):
        lib.rename(DIP14_NAME, "x")
    with pytest.raises(FileExistsError):
        lib.rename("dip14", "DIP-8_W7.62mm")
    assert (src_lib / "DIP-8_W7.62mm.kicad_mod").read_bytes() == other_before
    lib.rename("dip14", "dip14")                     # то же имя — ничего не делается
    lib.rename("dip14", "a/b")                       # имя нормализуется
    assert (src_lib / "a_b.kicad_mod").is_file() and kicadfp.load(
        src_lib / "a_b.kicad_mod").name == "a_b"


def test_rename_keeps_unsaved_changes_and_overwrite(src_lib):
    lib = Library(src_lib)
    fp = lib.get(DIP14_NAME)
    fp.descr = "изменено"
    lib.rename(DIP14_NAME, "DIP-8_W7.62mm", overwrite=True)
    assert sorted(lib.names) == ["DIP-16_W7.62mm", "DIP-8_W7.62mm"]
    back = kicadfp.load(src_lib / "DIP-8_W7.62mm.kicad_mod")
    assert back.descr == "изменено" and back.name == "DIP-8_W7.62mm"
    assert len(back.pads) == 14
    assert lib.get("DIP-8_W7.62mm") is fp


def test_rename_pending_only_in_memory(tmp_lib):
    lib = Library(tmp_lib)
    fp = Footprint.new("a")
    lib.add(fp)
    lib.rename("a", "b")
    assert list(tmp_lib.iterdir()) == []
    assert lib.names == ["b"] and fp.name == "b" and lib.unsaved == ["b"]
    assert lib.save_all() == [tmp_lib / "b.kicad_mod"]


def test_rename_value_not_equal_to_name_is_kept(tmp_lib):
    lib = Library(tmp_lib)
    lib.add(Footprint.new("a", value="VAL"))
    lib.save_all()
    lib.rename("a", "b")
    fp = kicadfp.load(tmp_lib / "b.kicad_mod")
    assert fp.name == "b" and fp.value.text == "VAL"


# ---------------------------------------------------------------------------
# copy_to — сценарий 9 ТЗ
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["kicad5", "kicad6", "kicad8", "kicad9"])
def test_scenario9_copy_to_with_rename(tmp_path, version):
    """Сценарий 9: скопировать корпус из одной библиотеки .pretty в другую с
    переименованием — в целевой появился файл с новым именем и полем name, исходный
    не изменён (байт в байт)."""
    src_dir = _copy_lib(FIXTURES / version / "Package_DIP.pretty", tmp_path / "src.pretty",
                        [DIP14_NAME])
    before = _snapshot(src_dir)
    src = Library(src_dir)
    dst = Library(tmp_path / "dst.pretty", create=True)
    copy = src.copy_to(dst, DIP14_NAME, "dip14_copy")
    target = dst.path / "dip14_copy.kicad_mod"
    assert target.is_file() and dst.names == ["dip14_copy"]
    fp = kicadfp.load(target)
    assert fp.name == "dip14_copy" and copy.name == "dip14_copy"
    assert fp.value.text == "dip14_copy"
    assert dst.get("dip14_copy") is copy and not dst.is_modified("dip14_copy")
    # исходный файл и объект не изменены
    assert _snapshot(src_dir) == before
    assert src.get(DIP14_NAME).name == DIP14_NAME and not src.is_modified(DIP14_NAME)
    assert src.names == [DIP14_NAME]
    # копия — независимое дерево
    copy.descr = "copy only"
    assert src.get(DIP14_NAME).descr != "copy only"
    # остальное содержимое совпадает с исходным (кроме имени и Value)
    orig = kicadfp.load(src_dir / f"{DIP14_NAME}.kicad_mod")
    orig.name = "dip14_copy"
    orig.value.text = "dip14_copy"
    assert sexpr.equal(orig.node, fp.node, ignore_quotes=False)


def test_copy_to_default_name_and_errors(src_lib, tmp_path):
    src = Library(src_lib)
    dst = Library(tmp_path / "dst.pretty", create=True)
    before = _snapshot(src_lib)
    fp = src.copy_to(dst, DIP14_NAME)
    assert fp.name == DIP14_NAME and dst.names == [DIP14_NAME]
    # файл без изменений дерева -> для файла KiCad 8 байт в байт
    assert (dst.path / f"{DIP14_NAME}.kicad_mod").read_bytes() == before[
        f"{DIP14_NAME}.kicad_mod"][0]
    dst_before = _snapshot(dst.path)
    with pytest.raises(FileExistsError):
        src.copy_to(dst, DIP14_NAME)
    assert _snapshot(dst.path) == dst_before
    with pytest.raises(KeyError):
        src.copy_to(dst, "missing")
    with pytest.raises(TypeError):
        src.copy_to(str(dst.path), DIP14_NAME)  # type: ignore[arg-type]
    fp2 = src.copy_to(dst, "DIP-8_W7.62mm", DIP14_NAME, overwrite=True)
    assert len(kicadfp.load(dst.path / f"{DIP14_NAME}.kicad_mod").pads) == 8
    assert fp2.name == DIP14_NAME and dst.get(DIP14_NAME) is fp2
    # копия внутри одной библиотеки; копия «в себя» — ошибка
    src.copy_to(src, "DIP-8_W7.62mm", "dip8 copy")
    assert "dip8 copy" in src and (src_lib / "dip8 copy.kicad_mod").is_file()
    with pytest.raises(FileExistsError):
        src.copy_to(src, "DIP-8_W7.62mm")
    assert _snapshot(src_lib).items() >= before.items()


def test_copy_to_sanitizes_new_name(src_lib, tmp_lib):
    src = Library(src_lib)
    dst = Library(tmp_lib)
    fp = src.copy_to(dst, DIP14_NAME, 'bad<name>:"x"')
    assert fp.name == "bad_name___x_"
    assert (tmp_lib / "bad_name___x_.kicad_mod").is_file()


def test_copy_to_unsaved_source_changes(src_lib, tmp_lib):
    """Копируется состояние в памяти (с незаписанными изменениями); исходный файл цел."""
    src = Library(src_lib)
    before = _snapshot(src_lib)
    src.get(DIP14_NAME).descr = "в памяти"
    fp = src.copy_to(Library(tmp_lib), DIP14_NAME, "c")
    assert kicadfp.load(tmp_lib / "c.kicad_mod").descr == "в памяти" == fp.descr
    assert _snapshot(src_lib) == before


def test_copy_to_opens_in_kicad(src_lib, tmp_lib, kicad_cli, tmp_path):
    """Копия с переименованием читается KiCad (kicad-cli fp upgrade)."""
    Library(src_lib).copy_to(Library(tmp_lib), DIP14_NAME, "dip14_copy")
    out = tmp_path / "out.pretty"
    r = subprocess.run([kicad_cli, "fp", "upgrade", str(tmp_lib), "-o", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "dip14_copy.kicad_mod").is_file()
    assert kicadfp.load(out / "dip14_copy.kicad_mod").name == "dip14_copy"


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------

def test_validate_all(src_lib):
    (src_lib / "broken.kicad_mod").write_text('(footprint "broken"\n  (layer "F.Cu"\n')
    lib = Library(src_lib)
    bad = Footprint.new("bad")
    bad.new_pad(1, type="thru_hole", size=(1.3, 1.3), drill=1.5)
    lib.add(bad)
    res = lib.validate_all()
    assert list(res) == lib.names
    assert [i.code for i in res["broken"]] == ["SEXPR_SYNTAX"]
    assert res["broken"][0].level == "error"
    assert "PAD_DRILL_GT_SIZE" in {i.code for i in res["bad"]}
    for n in (DIP14_NAME, "DIP-8_W7.62mm", "DIP-16_W7.62mm"):
        assert not [i for i in res[n] if i.level == "error"], res[n]
    # validate_all не кэширует прочитанные файлы
    assert lib.unsaved == ["bad"]


def test_validate_all_kicad8_package_dip():
    res = Library(DIP8).validate_all()
    assert len(res) == 268
    assert all(not [i for i in issues if i.level == "error"] for issues in res.values())


def test_validate_all_read_error(tmp_lib):
    (tmp_lib / "legacy.kicad_mod").write_text("PCBNEW-LibModule-V1\n$INDEX\n$EndINDEX\n"
                                              "$EndLIBRARY\n")
    res = Library(tmp_lib).validate_all()
    assert [i.code for i in res["legacy"]] == ["FILE_READ"]


def test_package_exports_library():
    assert kicadfp.Library is Library


def test_copy_to_write_failure_rolls_back(src_lib, tmp_lib, monkeypatch):
    """Ошибка записи в copy_to: в целевой библиотеке не остаётся ни файла, ни корпуса
    в памяти (а прежний корпус при overwrite возвращается)."""
    from kicadfp import io as kio

    src = Library(src_lib)
    dst = Library(tmp_lib)
    src.copy_to(dst, "DIP-8_W7.62mm", "x")
    prev = dst.get("x")

    def boom(*a, **kw):
        raise OSError("диск заполнен")

    monkeypatch.setattr(kio, "save", boom)
    with pytest.raises(OSError):
        src.copy_to(dst, DIP14_NAME, "y")
    assert "y" not in dst and dst.unsaved == []
    with pytest.raises(OSError):
        src.copy_to(dst, DIP14_NAME, "x", overwrite=True)
    assert dst.get("x") is prev and not dst.is_modified("x")
    assert sorted(p.name for p in tmp_lib.iterdir()) == ["x.kicad_mod"]
