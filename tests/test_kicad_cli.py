"""Совместимость с KiCad: файлы, записанные kicadfp, открывает KiCad (ТЗ 4.5.3, 4.5.4).

Необязательные тесты (маркер ``kicad_cli``): выполняются, если есть kicad-cli (``KICAD_CLI``,
версия >= 9; для KiCad 8 — ``KICAD8_CLI`` или ``kicad-cli8`` в PATH), иначе пропускаются.
Метод (``tests/kicad_cli_tools.py``): корпуса записываются kicadfp в каталог ``.pretty``,
``kicad-cli fp upgrade --force`` читает и пересохраняет каждый; KiCad не должен выдать ни
одного сообщения, а прочитанное KiCad (площадки, графика, тексты, 3D-модели) должно совпасть
с прочитанным kicadfp. Если KiCad отверг библиотеку, нечитаемые файлы находятся делением
пополам и перечисляются в сообщении теста.

Что проверяется:

* фикстуры всех версий (``kicad5``, ``kicad6``, ``kicad8``, ``kicad9``, ``special``) в трёх
  режимах: ``save`` — открыть и сохранить без изменений, ``upgrade`` — перевести
  :meth:`Footprint.upgrade` в формат KiCad 9 (для KiCad 8 — в 20240108), ``edit`` —
  сдвиг, поворот, размеры площадок, новая линия и текст, описание. Выборка — каждый 5-й файл
  (у каждого режима свой сдвиг, так что вместе режимы охватывают 3/5 файлов);
  ``KICADFP_CLI_STEP=1`` — все файлы (≈ 2 мин на KiCad 9);
* все генераторы (варианты из ``test_generators.VARIANTS``) в форматах KiCad 6–9;
* результат преобразования ``.mod`` (``My_lib.mod`` и синтетическая библиотека) —
  :func:`kicadfp.legacy.convert` и ``kicadfp convert`` — в форматах KiCad 6–9;
* решения из критики спецификаций, которые зависят от поведения KiCad: скрытый
  пользовательский текст (поле ``FieldN``), формы ``fill``, ``F&B.Cu``/``*.Cu``, малые углы с
  экспонентой, смещение 3D-модели в старой форме ``(at (xyz))`` (дюймы).

KiCad 8 не открывает файлы формата KiCad 9 (``version 20241229``): новые корпуса для KiCad 8
строятся с ``target_version(8)`` / ``--kicad 8`` (:func:`test_kicad8_needs_kicad8_format`).
"""

from __future__ import annotations

import pytest

import kicadfp
from kicadfp import cli as kcli
from kicadfp import generators, legacy
from kicadfp.format_rules import KICAD_FORMAT_VERSIONS
from kicadfp.model import Footprint

from . import kicad_cli_tools as T
from .conftest import FIXTURES, fixture_files
from .test_generators import VARIANTS
from .test_legacy import SYNTH_FOR_CLI

pytestmark = pytest.mark.kicad_cli

GROUPS: dict[str, tuple[str, ...]] = {
    "kicad5": ("kicad5",),
    "kicad6": ("kicad6",),
    "kicad8": ("kicad8",),
    "kicad9": ("kicad9",),
    "special": ("special/kicad5", "special/kicad6", "special/kicad8", "special/kicad9"),
}
MODES = ("save", "upgrade", "edit")
STEP = T.sample_step(5)
KICAD8_MAX_VERSION = KICAD_FORMAT_VERSIONS[8]   # 20240108 — новейший формат, читаемый KiCad 8
MY_LIB = FIXTURES / "legacy_mod" / "My_lib.mod"


def edit(fp: Footprint) -> None:
    """Типичные правки: сдвиг и поворот корпуса, размеры площадок, новая линия и текст,
    описание (всё — через API модели, в форме версии файла)."""
    fp.move(1.25, -2.5)
    fp.rotate(90)
    for p in fp.pads:
        if p.shape != "custom":
            p.size = (round(p.size_x * 1.1, 4), round(p.size_y * 1.1, 4))
    fp.new_line((0.0, 0.0), (1.0, 1.0), "F.SilkS", 0.12)
    fp.new_text("ACCEPT", "user", 0.5, 0.5, layer="F.Fab")
    fp.descr = "edited by kicadfp"


def _file_name(path) -> str:
    """Уникальное имя файла для библиотеки проверки: версия, библиотека, корпус."""
    rel = path.relative_to(FIXTURES)
    return "__".join(part.replace(".pretty", "") for part in rel.with_suffix("").parts)


def _record(record_property, cli: str, res: T.LibraryCheck, **extra) -> None:
    """Факты для отчёта scripts/acceptance_report.py."""
    record_property("kicad_cli", T.cli_version(cli))
    record_property("files", res.files)
    record_property("compared_equal", res.compared - len(res.mismatches))
    record_property("unreadable", len(res.unreadable))
    for k, v in extra.items():
        record_property(k, v)


def _write_fixtures(group: str, mode: str, lib, *, max_version: int | None = None,
                    upgrade_to: int | None = None) -> int:
    files = T.sample(fixture_files(*GROUPS[group]), STEP, MODES.index(mode))
    fps = {}
    for p in files:
        fp = kicadfp.load(p)
        if max_version is not None and (fp.version or 0) > max_version:
            continue
        if mode == "upgrade":
            fp.upgrade(upgrade_to or KICAD_FORMAT_VERSIONS[9])
        elif mode == "edit":
            edit(fp)
        fps[_file_name(p)] = fp
    T.write_library(fps, lib)
    return len(fps)


# ---------------------------------------------------------------------------------------------
# Фикстуры всех версий
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("group", GROUPS)
def test_fixtures_written_by_kicadfp_open_in_kicad9(kicad_cli, tmp_path, group, mode,
                                                    record_property):
    lib = tmp_path / f"{group}_{mode}.pretty"
    n = _write_fixtures(group, mode, lib)
    assert n > 0
    res = T.check_library(kicad_cli, lib, tmp_path)
    _record(record_property, kicad_cli, res, step=STEP)
    assert res.ok, res.report()
    assert res.compared == n


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("group", GROUPS)
def test_fixtures_written_by_kicadfp_open_in_kicad8(kicad8_cli, tmp_path, group, mode,
                                                    record_property):
    """Файлы форматов до KiCad 8 включительно (version <= 20240108) после записи kicadfp
    открывает и KiCad 8; ``upgrade`` — в формат KiCad 8."""
    lib = tmp_path / f"{group}_{mode}.pretty"
    n = _write_fixtures(group, mode, lib, max_version=KICAD8_MAX_VERSION,
                        upgrade_to=KICAD8_MAX_VERSION)
    if n == 0:
        pytest.skip("в выборке нет файлов форматов KiCad <= 8")
    res = T.check_library(kicad8_cli, lib, tmp_path)
    _record(record_property, kicad8_cli, res, step=STEP)
    assert res.ok, res.report()
    assert res.compared == n


# ---------------------------------------------------------------------------------------------
# Генераторы и преобразование .mod
# ---------------------------------------------------------------------------------------------

def _generated(kicad: int) -> dict[str, Footprint]:
    out = {}
    with generators.target_version(kicad):
        for i, (name, params) in enumerate(VARIANTS):
            fp = generators.GENERATORS[name](**params)
            out[f"{i:02d}_{fp.name}"] = fp
    return out


@pytest.mark.parametrize("kicad", sorted(KICAD_FORMAT_VERSIONS))
def test_all_generators_open_in_kicad9(kicad_cli, tmp_path, kicad, record_property):
    fps = _generated(kicad)
    assert {fp.version for fp in fps.values()} == {KICAD_FORMAT_VERSIONS[kicad]}
    lib = T.write_library(fps, tmp_path / f"gen{kicad}.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    _record(record_property, kicad_cli, res, format_version=KICAD_FORMAT_VERSIONS[kicad])
    assert res.ok, res.report()
    assert res.compared == len(VARIANTS)


@pytest.mark.parametrize("kicad", [6, 7, 8])
def test_all_generators_open_in_kicad8(kicad8_cli, tmp_path, kicad, record_property):
    lib = T.write_library(_generated(kicad), tmp_path / f"gen{kicad}.pretty")
    res = T.check_library(kicad8_cli, lib, tmp_path)
    _record(record_property, kicad8_cli, res, format_version=KICAD_FORMAT_VERSIONS[kicad])
    assert res.ok, res.report()
    assert res.compared == len(VARIANTS)


def test_kicad8_needs_kicad8_format(kicad8_cli, tmp_path, record_property):
    """Корпус формата KiCad 9 (по умолчанию) KiCad 8 не открывает — поэтому есть
    ``target_version(8)`` / ``--kicad 8``; тот же корпус в формате KiCad 8 он открывает."""
    k9 = T.write_library({"dip14": generators.lab_dip14()}, tmp_path / "k9.pretty")
    r = T.upgrade(kicad8_cli, k9, tmp_path / "k9_out")
    record_property("kicad_cli", T.cli_version(kicad8_cli))
    record_property("kicad8_reads_kicad9_format", r.ok)
    record_property("kicad8_message", "; ".join(r.messages) or "-")
    assert not r.ok and r.returncode != 0
    with generators.target_version(8):
        k8 = T.write_library({"dip14": generators.lab_dip14()}, tmp_path / "k8.pretty")
    res = T.check_library(kicad8_cli, k8, tmp_path)
    assert res.ok, res.report()


def _synthetic_mod(tmp_path):
    src = tmp_path / "synth.mod"
    src.write_text(SYNTH_FOR_CLI, encoding="utf-8")
    return src


@pytest.mark.parametrize("kicad", sorted(KICAD_FORMAT_VERSIONS))
@pytest.mark.parametrize("source", ["My_lib", "synthetic"])
def test_convert_result_opens_in_kicad9(kicad_cli, tmp_path, source, kicad, record_property):
    src = MY_LIB if source == "My_lib" else _synthetic_mod(tmp_path)
    out = tmp_path / f"{source}_{kicad}.pretty"
    paths = legacy.convert(src, out, version=kicad)
    assert paths and {kicadfp.load(p).version for p in paths} == {KICAD_FORMAT_VERSIONS[kicad]}
    res = T.check_library(kicad_cli, out, tmp_path)
    _record(record_property, kicad_cli, res, format_version=KICAD_FORMAT_VERSIONS[kicad])
    assert res.ok, res.report()
    assert res.compared == len(paths)


@pytest.mark.parametrize("kicad", [6, 7, 8])
@pytest.mark.parametrize("source", ["My_lib", "synthetic"])
def test_convert_result_opens_in_kicad8(kicad8_cli, tmp_path, source, kicad, record_property):
    src = MY_LIB if source == "My_lib" else _synthetic_mod(tmp_path)
    out = tmp_path / f"{source}_{kicad}.pretty"
    paths = legacy.convert(src, out, version=kicad)
    res = T.check_library(kicad8_cli, out, tmp_path)
    _record(record_property, kicad8_cli, res, format_version=KICAD_FORMAT_VERSIONS[kicad])
    assert res.ok, res.report()
    assert res.compared == len(paths)


@pytest.mark.parametrize("kicad", [None, "8"])
def test_cli_gen_and_convert_open_in_kicad(kicad_cli, tmp_path, capsys, kicad):
    """Команды ``kicadfp gen``/``kicadfp convert`` (ТЗ прил. В.3) пишут файлы, которые
    KiCad читает (с ``--kicad 8`` — формат KiCad 8)."""
    lib = tmp_path / "br8_timer.pretty"
    extra = [] if kicad is None else ["--kicad", kicad]
    for args in (["gen", "dip", "--pins", "14", "--pitch", "2.5", "--row-pitch", "7.5", "-o",
                  lib / "dip14.kicad_mod"],
                 ["gen", "lab_mlt", "-o", lib / "mlt.kicad_mod"],
                 ["gen", "lab_snp8", "-o", lib / "snp8.kicad_mod"],
                 ["convert", MY_LIB, "-o", tmp_path / "old_lib.pretty"]):
        assert kcli.main([str(a) for a in args + extra]) == 0, capsys.readouterr().err
    for d in (lib, tmp_path / "old_lib.pretty"):
        res = T.check_library(kicad_cli, d, tmp_path)
        assert res.ok, res.report()
        assert res.compared == 3


# ---------------------------------------------------------------------------------------------
# Решения из критики спецификаций, зависящие от поведения KiCad
# ---------------------------------------------------------------------------------------------

_HIDDEN_BASE = """(footprint "H"
\t(version {version})
\t(generator "pcbnew")
\t(generator_version "{gv}")
\t(layer "F.Cu")
\t(property "Reference" "REF**"
\t\t(at 0 -1 0)
\t\t(layer "F.SilkS")
\t\t(uuid "a0000000-0000-0000-0000-000000000001")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1 1)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t)
\t)
\t(property "Value" "H"
\t\t(at 0 1 0)
\t\t(layer "F.Fab")
\t\t(uuid "a0000000-0000-0000-0000-000000000002")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1 1)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t)
\t)
\t(fp_text user "HIDDEN_TEXT"
\t\t(at 0.5 0.25 0)
\t\t(layer "F.Fab")
\t\t(uuid "a0000000-0000-0000-0000-000000000003")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1 1)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t)
\t)
)
"""


@pytest.mark.parametrize("version, gv", [(20241229, "9.0"), (20240108, "8.0")])
def test_hidden_user_text_survives_kicad(kicad_cli, tmp_path, version, gv, record_property):
    """``Text.hide = True`` у ``fp_text user`` в формате KiCad 8+ превращает текст в скрытое
    поле ``FieldN`` (как парсер KiCad 9): kicad-cli 9.0.1 такое поле сохраняет, а
    ``(fp_text user … (hide yes))`` теряет — поэтому kicadfp пишет поле, а не fp_text."""
    fp = kicadfp.loads(_HIDDEN_BASE.format(version=version, gv=gv))
    t = next(t for t in fp.texts if t.text == "HIDDEN_TEXT")
    raw = t.node.copy()
    t.hide = True
    assert t.hide and t.is_property and t.name.startswith("Field")
    lib = T.write_library({"H": fp}, tmp_path / "h.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "h_kicad.pretty" / "H.kicad_mod")
    hidden = [x for x in back.texts if x.text == "HIDDEN_TEXT"]
    assert len(hidden) == 1 and hidden[0].hide and (hidden[0].x, hidden[0].y) == (0.5, 0.25)
    # для сравнения: скрытый fp_text в той же версии kicad-cli 9.0.1 теряет
    from kicadfp.sexpr import Node, Sym
    raw.append(Node("hide", [Sym("yes")]))
    fp2 = kicadfp.loads(_HIDDEN_BASE.format(version=version, gv=gv))
    old = next(x for x in fp2.texts if x.text == "HIDDEN_TEXT").node
    fp2.node.replace_child(old, raw)
    lib2 = T.write_library({"H": fp2}, tmp_path / "raw.pretty")
    r = T.upgrade(kicad_cli, lib2, tmp_path / "raw_out")
    assert r.ok
    lost = "HIDDEN_TEXT" not in (tmp_path / "raw_out" / "H.kicad_mod").read_text(encoding="utf-8")
    record_property("kicad_cli", T.cli_version(kicad_cli))
    record_property("field_kept_by_kicad", True)
    record_property("raw_hidden_fp_text_lost_by_kicad", lost)
    if T.cli_version(kicad_cli) == "9.0.1":  # проверено на 9.0.1; другие версии — без проверки
        assert lost, "kicad-cli 9.0.1 сохранил скрытый fp_text (поведение изменилось)"


@pytest.mark.parametrize("kicad", [6, 7, 8, 9])
def test_fill_forms_by_version_read_by_kicad(kicad_cli, tmp_path, kicad):
    """``fill``: 6.0–8.0 — ``solid|none``, 9.0+ — ``yes|no``; примитивы custom-площадки —
    ``yes|none`` (6/7), ``yes|no`` (8+). Запись setter'ом — в форме версии; KiCad читает то же
    значение заливки."""
    version = KICAD_FORMAT_VERSIONS[kicad]
    fp = Footprint.new("F", version=version)
    shapes = [fp.new_rect((0, 0), (1, 1), "F.SilkS", 0.12),
              fp.new_circle((3, 3), 1.0, "F.SilkS", 0.12),
              fp.new_poly([(5, 5), (6, 5), (6, 6)], "F.SilkS", 0.12)]
    for i, g in enumerate(shapes):
        g.fill = bool(i % 2)
    text = fp.dumps()
    words = ("solid", "none") if kicad < 9 else ("yes", "no")
    assert f"(fill {words[0]})" in text and f"(fill {words[1]})" in text
    pad = fp.new_pad("1", "smd", "custom", 0, 0, (0.5, 0.5), layers=["F.Cu", "F.Mask"])
    pad.node.append(kicadfp.sexpr.parse(
        "(primitives (gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (width 0) (fill yes)))"))
    prim = pad.primitive_views[0]
    prim.fill = False
    assert prim.fill is False
    assert str(prim.node.find("fill").atom(0)) == ("none" if kicad < 8 else "no")
    prim.fill = True
    assert str(prim.node.find("fill").atom(0)) == "yes"
    lib = T.write_library({"F": fp}, tmp_path / "f.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "f_kicad.pretty" / "F.kicad_mod")
    assert [g.fill for g in back.graphics] == [g.fill for g in fp.graphics] == [False, True, False]
    assert back.pad("1").primitive_views[0].fill is True


def test_fb_cu_and_star_cu_read_alike(kicad_cli, tmp_path):
    """``F&B.Cu`` (KiCad 6–9.0.5) и ``*.Cu`` (9.0.6+ у площадок): kicadfp сохраняет исходную
    форму, :func:`kicadfp.layers.expand` раскрывает обе, KiCad читает обе."""
    fp = Footprint.new("L")
    a = fp.new_pad("1", "thru_hole", "circle", 0, 0, 1.6, drill=0.8, layers=["F&B.Cu", "*.Mask"])
    b = fp.new_pad("2", "thru_hole", "circle", 2.54, 0, 1.6, drill=0.8, layers=["*.Cu", "*.Mask"])
    assert a.layers == ["F&B.Cu", "*.Mask"] and b.layers == ["*.Cu", "*.Mask"]
    assert '"F&B.Cu"' in fp.dumps() and '"*.Cu"' in fp.dumps()
    lib = T.write_library({"L": fp}, tmp_path / "l.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "l_kicad.pretty" / "L.kicad_mod")
    assert {"F.Cu", "B.Cu"} <= set(kicadfp.layers.expand(back.pad("1").layers))
    assert "In1.Cu" in kicadfp.layers.expand(back.pad("2").layers)


def test_small_angle_with_exponent(kicad_cli, tmp_path):
    """KiCad пишет углы < 1e-4 с экспонентой (``1e-05``), kicadfp — без неё
    (``0.00001``); лексеры обоих читают обе записи."""
    text = _HIDDEN_BASE.format(version=20241229, gv="9.0").replace(
        '(at 0.5 0.25 0)', '(at 0.5 0.25 1e-05)')
    fp = kicadfp.loads(text)
    t = next(t for t in fp.texts if t.text == "HIDDEN_TEXT")
    assert t.angle == pytest.approx(1e-05)
    assert "1e-05" in fp.dumps()             # исходная запись сохраняется
    t.angle = 2e-05
    assert "(at 0.5 0.25 0.00002)" in fp.dumps()
    lib = T.write_library({"A": fp}, tmp_path / "a.pretty")
    res = T.check_library(kicad_cli, lib, tmp_path)
    assert res.ok, res.report()


def test_model_old_at_form_is_inches(kicad_cli_any, tmp_path):
    """Смещение 3D-модели в старой форме ``(at (xyz …))`` — дюймы: kicadfp читает его ×25.4
    (как парсер KiCad), KiCad пишет ``(offset (xyz …))`` в мм — значения совпадают."""
    text = ("(module M (layer F.Cu) (tedit 5A02E8D8)\n"
            "  (fp_text reference REF** (at 0 0) (layer F.SilkS)\n"
            "    (effects (font (size 1 1) (thickness 0.15))))\n"
            "  (fp_text value M (at 0 1) (layer F.Fab)\n"
            "    (effects (font (size 1 1) (thickness 0.15))))\n"
            "  (model m.wrl\n    (at (xyz 0.1 -0.05 0.02))\n    (scale (xyz 1 1 1))\n"
            "    (rotate (xyz 0 0 90))\n  )\n)\n")
    fp = kicadfp.loads(text)
    assert fp.models[0].offset == pytest.approx((2.54, -1.27, 0.508), abs=1e-6)
    lib = T.write_library({"M": fp}, tmp_path / "m.pretty")
    res = T.check_library(kicad_cli_any, lib, tmp_path)
    assert res.ok, res.report()
    back = kicadfp.load(tmp_path / "m_kicad.pretty" / "M.kicad_mod")
    assert back.models[0].offset == pytest.approx((2.54, -1.27, 0.508), abs=1e-5)
    assert back.node.find("model").find("offset") is not None
