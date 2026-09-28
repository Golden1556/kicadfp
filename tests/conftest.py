"""Общие фикстуры pytest для kicadfp.

Каталоги фикстур (tests/fixtures/<версия>/<библиотека>.pretty/*.kicad_mod):
  kicad5     — формат KiCad 5 (корень ``module``), из kicad-footprints 6.0.0
  kicad6     — формат KiCad 6 (version 20211014), из kicad-footprints 7.0.0
  kicad8     — формат KiCad 8 (version 20240108), пять библиотек из ТЗ целиком
  kicad9     — формат KiCad 9 (version 20240108/20241229), из kicad-footprints 9.0.0
  kicad10dev — формат KiCad 10-dev (version 20260206), из kicad-footprints master
  legacy_mod — старый формат PCBNEW-LibModule-V1

Переменные окружения:
  KICADFP_EXTRA_FIXTURES — список каталогов через ``os.pathsep`` с дополнительными
      .pretty (полные клоны библиотек) для расширенного прогона round-trip;
  KICAD_CLI — путь к kicad-cli; при отсутствии тесты с маркером ``kicad_cli`` пропускаются
      (фикстура ``kicad_cli`` требует kicad-cli >= 9, ``kicad_cli_any`` — любую версию);
  KICAD8_CLI — путь к kicad-cli KiCad 8.x (по умолчанию ``kicad-cli8`` из PATH) для проверки,
      что файлы открываются и в KiCad 8 (фикстура ``kicad8_cli``; без него — skip).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
# special/<версия> — файлы с редкими конструкциями (zone, group, custom pads, chamfer, …)
VERSION_DIRS = ("kicad5", "kicad6", "kicad8", "kicad9", "kicad10dev",
                "special/kicad5", "special/kicad6", "special/kicad8", "special/kicad9",
                "special/kicad10dev")
PRETTIFY_DIRS = ("kicad8", "kicad9", "kicad10dev", "special/kicad8", "special/kicad9",
                 "special/kicad10dev")  # файлы, записанные Prettify -> байт в байт
LEGACY_LAYOUT_DIRS = ("kicad5", "kicad6", "special/kicad5", "special/kicad6")


def fixture_files(*dirs: str) -> list[Path]:
    """Все ``*.kicad_mod`` в указанных каталогах версий (отсортированно)."""
    out: list[Path] = []
    for d in dirs or VERSION_DIRS:
        out.extend(sorted((FIXTURES / d).rglob("*.kicad_mod")))
    return out


def extra_fixture_files() -> list[Path]:
    extra = os.environ.get("KICADFP_EXTRA_FIXTURES", "")
    out: list[Path] = []
    for d in filter(None, extra.split(os.pathsep)):
        out.extend(sorted(Path(d).rglob("*.kicad_mod")))
    return out


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(FIXTURES)) if FIXTURES in p.parents else str(p) for p in paths]


ALL_FILES = fixture_files()
PRETTIFY_FILES = fixture_files(*PRETTIFY_DIRS)


@pytest.fixture(params=ALL_FILES, ids=_ids(ALL_FILES))
def any_fixture(request) -> Path:
    """Каждый файл-фикстура всех версий."""
    return request.param


@pytest.fixture(params=PRETTIFY_FILES, ids=_ids(PRETTIFY_FILES))
def prettify_fixture(request) -> Path:
    """Файлы, записанные KiCad 8+ (стиль Prettify) — ожидается совпадение байт в байт."""
    return request.param


@pytest.fixture
def dip14_v8() -> Path:
    return FIXTURES / "kicad8" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"


@pytest.fixture
def dip14_v6() -> Path:
    return FIXTURES / "kicad6" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"


@pytest.fixture
def dip14_v5() -> Path:
    return FIXTURES / "kicad5" / "Package_DIP.pretty" / "DIP-14_W7.62mm.kicad_mod"


@pytest.fixture
def legacy_mod() -> Path:
    return FIXTURES / "legacy_mod" / "My_lib.mod"


def _find_kicad_cli() -> str | None:
    cli = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    if not cli or not Path(cli).exists():
        return None
    return cli


def kicad_cli_version(cli: str) -> tuple[int, ...]:
    """Версия kicad-cli как кортеж чисел (``kicad-cli version`` -> ``7.0.11`` -> (7, 0, 11)).

    При ошибке запуска возвращает пустой кортеж.
    """
    import re
    import subprocess

    try:
        out = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(x) for x in m.groups() if x is not None) if m else ()


# Минимальная версия KiCad, читающая файлы, которые пишет Программа по умолчанию
# (DEFAULT_VERSION = 20241229, формат KiCad 9). KiCad 7 такие файлы отвергает
# («Unable to load library»), поэтому для них нужен kicad-cli >= 9.
KICAD_CLI_MIN_MAJOR = 9


@pytest.fixture
def kicad_cli() -> str:
    """Путь к kicad-cli версии >= 9 (читает файлы формата KiCad 9) или skip.

    Для проверки файлов старых форматов (KiCad 5/6/7, version <= 20221018) любой
    версией kicad-cli используйте фикстуру ``kicad_cli_any``.
    """
    cli = _find_kicad_cli()
    if not cli:
        pytest.skip("kicad-cli не найден (задайте KICAD_CLI)")
    ver = kicad_cli_version(cli)
    if ver and ver[0] < KICAD_CLI_MIN_MAJOR:
        pytest.skip(f"kicad-cli {'.'.join(map(str, ver))} не читает файлы формата KiCad "
                    f"{KICAD_CLI_MIN_MAJOR}+ (нужен kicad-cli >= {KICAD_CLI_MIN_MAJOR})")
    return cli


@pytest.fixture
def kicad_cli_any() -> str:
    """Путь к kicad-cli любой версии (для файлов форматов KiCad 5/6/7) или skip."""
    cli = _find_kicad_cli()
    if not cli:
        pytest.skip("kicad-cli не найден (задайте KICAD_CLI)")
    return cli


def find_kicad8_cli() -> str | None:
    """kicad-cli KiCad 8.x: ``KICAD8_CLI`` или ``kicad-cli8`` из PATH; ``None`` — нет
    (или это не 8.x)."""
    cli = os.environ.get("KICAD8_CLI") or shutil.which("kicad-cli8")
    if not cli or not Path(cli).exists():
        return None
    ver = kicad_cli_version(cli)
    return cli if ver and ver[0] == 8 else None


@pytest.fixture
def kicad8_cli() -> str:
    """Путь к kicad-cli KiCad 8.x (``KICAD8_CLI``/``kicad-cli8``) или skip: KiCad 8 читает
    форматы до 20240108 включительно и не открывает файлы формата KiCad 9."""
    cli = find_kicad8_cli()
    if not cli:
        pytest.skip("kicad-cli KiCad 8 не найден (задайте KICAD8_CLI)")
    return cli


@pytest.fixture
def tmp_lib(tmp_path: Path) -> Path:
    """Пустой каталог временной библиотеки ``tmp.pretty``."""
    d = tmp_path / "tmp.pretty"
    d.mkdir()
    return d
