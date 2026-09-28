"""Round-trip без потерь на реальных библиотеках KiCad (ТЗ 4.1.4, сценарий Г.1).

Для каждого файла-фикстуры: разбор → запись → разбор даёт равное дерево.
Для файлов, записанных KiCad 8+ (Prettify), текст воспроизводится байт в байт;
для файлов KiCad 5/6 — тоже, за счёт табличной раскладки. Исключения — файлы,
записанные не самим KiCad, а сторонними генераторами: для Prettify-файлов признак —
токен ``generator`` в заголовке, отличный от ``pcbnew``; для раскладки 5/6 — ещё
«по одной точке (xy) в строке» и таб в первой строке.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kicadfp import io as kio
from kicadfp import sexpr
from tests.conftest import FIXTURES, LEGACY_LAYOUT_DIRS, extra_fixture_files, fixture_files

_XY_PER_LINE = re.compile(r"\n\t+\(xy ")
_GENERATOR = re.compile(r'\(generator\s+(?:"([^"]*)"|([^\s()"]+))')


def _generator_name(text: str) -> str | None:
    """Значение ``(generator …)`` из заголовка файла (первые 1000 символов) или ``None``."""
    m = _GENERATOR.search(text[:1000])
    if m is None:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def _roundtrip(path: Path) -> tuple[str, str, sexpr.Node, sexpr.Node]:
    text = path.read_text(encoding="utf-8")
    tree = sexpr.parse(text)
    out = sexpr.dumps(tree)
    tree2 = sexpr.parse(out)
    return text, out, tree, tree2


def test_tree_roundtrip_every_fixture(any_fixture: Path):
    text, out, tree, tree2 = _roundtrip(any_fixture)
    assert sexpr.equal(tree, tree2), sexpr.diff(tree, tree2)[:5]
    # повторная запись стабильна (идемпотентность)
    assert sexpr.dumps(tree2) == out


def _io_roundtrip(path: Path) -> tuple[str, str]:
    """Текст файла и результат ``io.dumps(io.load(path))`` (со стилем конца файла, который
    корпус запоминает при чтении: файлы KiCad 8.0.0/8.0.1 — без ``\n``)."""
    return path.read_text(encoding="utf-8"), kio.dumps(kio.load(path))


def test_bytes_roundtrip_prettify_files(prettify_fixture: Path):
    text, out = _io_roundtrip(prettify_fixture)
    if out == text:
        return
    # Пропуск — только для файлов сторонних генераторов. Признак «по одной точке xy в
    # строке» не годится: так же выглядит обычный вывод Prettify «(pts\n\t\t\t(xy …»,
    # и регрессия раскладки полигонов в файлах pcbnew превращалась бы в skip.
    generator = _generator_name(text)
    if generator is not None and generator != "pcbnew":
        pytest.skip(f"файл записан генератором {generator!r}, а не KiCad")
    assert out == text


def test_prettify_polygon_files_are_byte_checked():
    """Регрессия: файлы pcbnew с полигонами (xy на отдельной строке) проверяются байт в байт,
    а не пропускаются как «файлы генератора»."""
    from tests.conftest import PRETTIFY_FILES

    pcbnew_polys = 0
    for p in PRETTIFY_FILES:
        text = p.read_text(encoding="utf-8")
        if _XY_PER_LINE.search(text) and _generator_name(text) == "pcbnew":
            pcbnew_polys += 1
            assert kio.dumps(kio.loads(text)) == text, p
    assert pcbnew_polys >= 100
    assert _generator_name('(footprint "X"\n\t(version 1)\n\t(generator pcbnew)') == "pcbnew"
    assert _generator_name('(footprint "X" (generator "kicad-footprint-generator"))') == \
        "kicad-footprint-generator"
    assert _generator_name("(module X (layer F.Cu))") is None


def _one_line_header_at_6_0(text: str) -> bool:
    """Ночные сборки между сменой версии на 20211014 и коммитом 80c5b1ef (2021-11-13)
    писали «(layer …)» в первой строке; по версии их не отличить (format-layout.md §3.3).
    Файлы ночных 5.99 с версией < 20211014 раскладка воспроизводит."""
    first_line = text.split("\n", 1)[0]
    m = re.search(r"\(version (\d+)\)", first_line)
    return ("(layer" in first_line and "(footprint" in first_line
            and m is not None and int(m.group(1)) >= 20211014)


_LEGACY_STYLE_EXCEPTIONS = {
    # (файлы ночных 5.99 с версией < 20211014 — заголовок в одну строку — воспроизводятся:
    # kicad5/Capacitor_THT.pretty/DX_5R5VxxxxU_D11.5mm_P5.00mm.kicad_mod и др.)
    # ранняя сборка KiCad 5.0: (roundrect_rratio …) без пробела перед скобкой
    "special/kicad5/Package_TO_SOT_THT.pretty__TO-92_HandSolder.kicad_mod",
    "special/kicad5/Package_TO_SOT_THT.pretty__TO-92L_HandSolder.kicad_mod",
}


@pytest.mark.parametrize("path", fixture_files(*LEGACY_LAYOUT_DIRS),
                         ids=[str(p.relative_to(FIXTURES)) for p in fixture_files(*LEGACY_LAYOUT_DIRS)])
def test_bytes_roundtrip_legacy_layout(path: Path):
    text, out = _io_roundtrip(path)
    rel = str(path.relative_to(FIXTURES))
    if rel in _LEGACY_STYLE_EXCEPTIONS or path.name in {Path(x).name for x in _LEGACY_STYLE_EXCEPTIONS}:
        pytest.xfail("известное исключение раскладки")
    first_line = text.split("\n", 1)[0]
    if _XY_PER_LINE.search(text) or "\t" in first_line:
        pytest.skip("файл записан не самим KiCad (сторонний генератор)")
    if "(generator pcbnew)" not in first_line and "(module " not in first_line:
        pytest.skip("файл записан сторонним генератором (не pcbnew)")
    if _one_line_header_at_6_0(text):
        pytest.skip("заголовок в одну строку при version 20211014: ночная сборка 2021-10-15…11-13")
    if "allowed )" in text:
        pytest.skip("keepout-зона writer'а KiCad 6.0.0–6.0.6 с лишним пробелом (по дереву не восстановить)")
    assert out == text


def test_roundtrip_statistics_summary():
    """Сводная проверка: ≥ 200 корпусов стандартных библиотек KiCad 8 совпадают на 100 %."""
    files = fixture_files("kicad8")
    assert len(files) >= 200
    ok = 0
    for p in files:
        text, out, tree, tree2 = _roundtrip(p)
        if sexpr.equal(tree, tree2) and kio.dumps(kio.loads(text)) == text:
            ok += 1
    assert ok == len(files)


def _is_kicad_written(text: str) -> bool:
    """Записан ли файл самим KiCad (pcbnew / KiCad 5), а не генератором библиотек.

    Для корня ``footprint`` признак — ``generator pcbnew``; файлы ``module`` без признака
    генератора принимаются все (среди них есть и файлы KicadModTree, см. допуск ниже).
    """
    head = text[:400]
    if "(generator pcbnew)" in head or '(generator "pcbnew")' in head:
        return True
    return text.startswith("(module ")


@pytest.mark.slow
def test_bytes_roundtrip_extra_fixtures():
    """Расширенный прогон, байт в байт: файлы, записанные самим KiCad (5.1…10), кроме
    вариантов раскладки, которые по дереву не восстановить (format-layout.md §5.2):
    keepout 6.0.0–6.0.6 «(pads … )», заголовок в одну строку при version 20211014,
    вторая строка заголовка с одним пробелом (ручная правка)."""
    files = extra_fixture_files()
    if not files:
        pytest.skip("KICADFP_EXTRA_FIXTURES не задана")
    bad: list[str] = []
    checked = 0
    for p in files:
        text = p.read_text(encoding="utf-8")
        if not _is_kicad_written(text) or "allowed )" in text or _one_line_header_at_6_0(text):
            continue
        if text.split("\n", 2)[1:2] and text.split("\n", 2)[1].startswith(" (layer"):
            continue
        checked += 1
        if kio.dumps(kio.loads(text)) != text:
            bad.append(str(p))
    # файлы KiCad 5 из генератора KicadModTree тоже начинаются с «(module» — их раскладка
    # отличается (gr_poly по 4 точки, model в одну строку и т. п.): допускается до 5 %
    assert checked, "нет файлов, записанных KiCad"
    modules_bad = [b for b in bad if Path(b).read_text(encoding="utf-8").startswith("(module ")]
    others_bad = [b for b in bad if b not in modules_bad]
    assert not others_bad, others_bad[:20]
    assert len(modules_bad) <= 0.05 * checked, modules_bad[:20]


@pytest.mark.slow
def test_roundtrip_extra_fixtures():
    files = extra_fixture_files()
    if not files:
        pytest.skip("KICADFP_EXTRA_FIXTURES не задана")
    bad: list[str] = []
    for p in files:
        try:
            text, out, tree, tree2 = _roundtrip(p)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p}: {e}")
            continue
        if not sexpr.equal(tree, tree2):
            bad.append(f"{p}: дерево не совпало")
    assert not bad, bad[:20]


def test_unknown_node_preserved_verbatim(dip14_v8: Path):
    """Сценарий Г.3 на уровне дерева: неизвестный узел сохраняется без изменений."""
    text = dip14_v8.read_text(encoding="utf-8")
    text2 = text.replace('\t(attr through_hole)\n', '\t(attr through_hole)\n\t(example_token 1 2)\n', 1)
    assert text2 != text
    tree = sexpr.parse(text2)
    assert tree.find("example_token") is not None
    out = sexpr.dumps(tree)
    assert "\t(example_token 1 2)\n" in out
    assert out.rstrip("\n") == text2.rstrip("\n")


def test_dumps_uses_lf_and_trailing_newline(dip14_v8: Path):
    out = sexpr.dumps(sexpr.parse(dip14_v8.read_text(encoding="utf-8")))
    assert "\r" not in out and out.endswith(")\n")


def _skip_if_tracing() -> None:
    """Пропуск тестов на скорость под coverage/отладчиком: трассировка замедляет код в разы,
    и пороги времени теряют смысл."""
    import sys

    if sys.gettrace() is not None or "coverage" in sys.modules:
        pytest.skip("тест производительности не выполняется под трассировкой (coverage)")


def test_parse_speed_kicad8_fixtures():
    """Цель ревью: разбор < 4 мс на файл (в среднем по библиотекам KiCad 8)."""
    import time

    _skip_if_tracing()
    texts = [p.read_text(encoding="utf-8") for p in fixture_files("kicad8")]
    t0 = time.perf_counter()
    for t in texts:
        sexpr.parse(t)
    dt = (time.perf_counter() - t0) / len(texts)
    assert dt < 0.004, f"разбор {dt * 1000:.2f} мс на файл"


def test_performance_parse_and_dump(dip14_v8: Path):
    import time

    _skip_if_tracing()
    text = dip14_v8.read_text(encoding="utf-8")
    t0 = time.perf_counter()
    for _ in range(20):
        sexpr.dumps(sexpr.parse(text))
    dt = (time.perf_counter() - t0) / 20
    assert dt < 0.05, f"слишком медленно: {dt * 1000:.1f} мс на файл"
