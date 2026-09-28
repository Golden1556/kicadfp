# Состояние работы и инструкция по продолжению (для облачной сессии)

Обновлено: 2026-09-28 (облачная сессия, после волн core и gui). Первая сессия велась локально на
Mac; всё, что нужно для продолжения, лежит в этом репозитории.

## Что это

Реализация ТЗ «Библиотека и редактор файлов KiCad на языке Python» (kicadfp), этап 1 —
посадочные места. ТЗ: `refs/tz/ТЗ_kicadfp_этап1_корпуса.pdf`, извлечённый текст —
`refs/tz/tz_text.txt` (читать ЕГО, PDF-рендер не нужен). Заказчик — кафедра САПР ВС РГРТУ,
исполнитель — студент группы 346 Хорьков К. А. Требование пользователя: «всё должно
получиться в лучшем виде», агентов не жалеть; агентов запускать на модели **Opus** (не Fable).

## Материалы

| Путь | Что |
|---|---|
| `refs/tz/` | ТЗ (PDF + текст) |
| `refs/kicad-2011-gen/` | наработки пользователя: генератор/валидатор файлов KiCad 2011 (старый формат `.mod`, `.lib`, `.sch`), docs/pcbnew-mod-format.md и pcbnew-pad-format.md — точное описание формата `.mod` |
| `refs/bzr2986/` | снапшот исходников KiCad 2011 (bzr2986) + `kicad-требования-и-задания.md` (методичка лабораторных: геометрия корпусов dip14/mlt/snp8) |
| `refs/kicad-src/{6.0,7.0,8.0,9.0,master}/` | скачанные исходники KiCad: writer/parser S-выражений, Prettify, legacy plugin, layer_id, eda_units, richio, dsnlexer (имена файлов = путь в репозитории KiCad с `/`→`_`) |
| `docs/dev/architecture.md` | **контракт API** для всех модулей (обязателен к соблюдению) |
| `docs/dev/format-writer.md`, `format-layout.md`, `format-tokens.md`, `layers.md`, `legacy-mod.md`, `lab-generators.md` | спецификации, написанные исследователями по исходникам KiCad и 12 тыс. реальных файлов (с приложениями — портами алгоритмов на Python) |
| `docs/dev/token-inventory.json`, `layers.json` | инвентаризация токенов реальных файлов; слои/цвета |
| `docs/dev/research/` | скрипты исследования (prettify.py — порт Prettify, layout67.py — раскладка KiCad 5/6/7, legacy_expected.py — эталон конвертации `My_lib.mod`, rt_check.py — проверка round-trip) |
| `tests/fixtures/` | 2300 корпусов стандартных библиотек (kicad5/6/8/9/10dev) + `special/` (221 файл с редкими конструкциями) + `legacy_mod/My_lib.mod` |
| `scripts/workflows/*.js` | скрипты волн для инструмента Workflow (см. ниже) |
| `scripts/fetch_refs.sh` | загрузка полных библиотек kicad-footprints в `.cache/` (для расширенных прогонов) |

## Окружение

* Python ≥ 3.10 (локально был venv `.venv` на 3.12; в облаке — 3.11). Установка:
  `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` (pytest, pytest-cov, pytest-qt,
  PySide6). Ядро без сторонних зависимостей. В облачном контейнере (Ubuntu noble) для
  PySide6 нужны системные библиотеки: `apt-get install libegl1 libgl1 libxkbcommon0
  libdbus-1-3 libfontconfig1 libglib2.0-0 libxcb-cursor0 libopengl0 libxkbcommon-x11-0`.
* Тесты: `KICAD_CLI=$(which kicad-cli) QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
  (после волны core ~8100 тестов, все зелёные; ~10 мин). Расширенный round-trip:
  `scripts/fetch_refs.sh` (в облаке `.cache/kfp` уже скачан — 22 718 файлов), затем
  `KICADFP_EXTRA_FIXTURES=.cache/kfp/v8.0.0:.cache/kfp/v9.0.0:.cache/kfp/master:.cache/kfp/v7.0.0:.cache/kfp/v6.0.0 pytest tests/test_roundtrip.py -m slow`.
* kicad-cli: локально на Mac — из DMG KiCad 10.0.6. В облаке PPA KiCad недоступен, а apt даёт
  только KiCad 7 (не читает файлы формата KiCad 8/9). Рабочий путь — Nix из бинарного кэша:
  `sh <(curl -L https://releases.nixos.org/nix/nix-2.24.10/install) --no-daemon` (как root
  упадёт на группе nixbld; тогда `printf 'build-users-group =\nsandbox = false\n' >
  /etc/nix/nix.conf` и повторить установку профиля), `nix-channel --add
  https://channels.nixos.org/nixos-25.05 nixpkgs && nix-channel --update && nix-env -iA
  nixpkgs.kicad-small` → `/root/.nix-profile/bin/kicad-cli` 9.0.1 (симлинк в
  `/usr/local/bin/kicad-cli`). Он читает форматы KiCad 5–9 (version ≤ 20241229) и НЕ читает
  KiCad 10-dev (фикстуры kicad10dev, `.cache/kfp/master`) — это ожидаемо. Фикстура `kicad_cli`
  в conftest требует версию ≥ 9, `kicad_cli_any` — любую; без kicad-cli тесты с маркером
  `kicad_cli` пропускаются (допустимо по ТЗ 4.5.4).
* Тесты производительности разбора (`test_roundtrip.py`) пропускаются под coverage.

## Сделано (проверено тестами)

1. `kicadfp/sexpr.py` — дерево S-выражений: парсер с позициями ошибок (правила DSNLEXER
   KiCad), Prettify KiCad 8/9/10 (порт 1:1), табличная раскладка writer'ов KiCad 5.1/6.0/7.0,
   форматирование чисел как KiCad (KiROUND, `%.10g`), `equal`/`diff`. Round-trip на 12 191
   файле: 100 % равенство деревьев, байт-в-байт для всех файлов, записанных самим KiCad.
   Прошёл adversarial-ревью (17 + 6 дефектов найдено и исправлено).
2. `kicadfp/format_rules.py` — профили версий (`profile_for`), таблицы порядка токенов,
   группы, `insert_in_group` с сортировкой как у KiCad (`drawing_sort_key`).
3. `kicadfp/layers.py` — слои, групповые обозначения, пресеты, цвета, старая нумерация/маски.
4. `kicadfp/geometry.py` — поворот, дуги (3 точки ↔ центр/угол), bbox, Безье.
5. `kicadfp/model.py` (~6300 строк) и `kicadfp/io.py` — представления над деревом по
   контракту §6–7, конверсия узлов между версиями, `upgrade()` (сверен с `kicad-cli fp
   upgrade` 9.0.1 на 15 894 файлах библиотек v6–v9: расхождения только по keepout-зонам,
   которые KiCad переписывает целиком, и по неизвестным слоям → Rescue). Прошёл два раунда
   adversarial-ревью (10 + 5 замечаний исправлены). Отклонения от контракта описаны в
   docstring модуля `model.py`.
6. `kicadfp/legacy.py` — конвертер `.mod` (сверен с kicad-cli на 96 реальных библиотеках
   kicad-library, 1518 модулей), `validate.py` (правила ТЗ 4.1.5 + дополнительные, коды в
   docstring), `generators/` (dip, pin_header, axial, radial, transistor, lab_*), `library.py`,
   `render.py` (SVG на stdlib, PNG через PySide6), `cli.py` + `__main__.py` (все команды §13,
   русские сообщения, коды возврата 0/1/2). Ревью ядра: два раунда (4 + 5 замечаний
   исправлены). Покрытие ядра без gui ≈ 96 %.
7. Тесты: `test_sexpr.py`, `test_roundtrip.py`, `test_format_rules.py`, `test_layers.py`,
   `test_geometry.py`, `test_model_*.py`, `test_io.py`, `test_legacy.py`, `test_validate.py`,
   `test_generators.py`, `test_library.py`, `test_render.py`, `test_cli.py`.

8. **GUI** (`kicadfp/gui/`, PySide6): `document.py` (FootprintDocument, undo/redo по снимкам
   узлов, отмена возвращает файл байт в байт), `commands.py`, `app.py`, `canvas.py`
   (PreviewCanvas: все элементы по DRAW_ORDER/COLORS, зум, панорамирование, выбор,
   перетаскивание с привязкой), `pad_table.py`/`items_table.py`/`props_panel.py`,
   `libtree.py`, `dialogs.py` (GenerateDialog, ValidateDialog, PadBatchDialog,
   ItemPropertiesDialog, AboutDialog, CopyFootprintDialog), `mainwindow.py` (все меню,
   док-панели, QSettings; модальные окна подменяются функциями для тестов). Тесты
   `tests/test_gui_*.py` (≈400, offscreen), `tests/gui_screenshots.py` → `docs/img/gui_main.png`.
   Ревью GUI: 6 замечаний (незавершённый ввод при Ctrl+S/закрытии, повторное открытие
   файла с «Сохранить», no-op смены слоёв и др.) исправлены, регрессии в
   `tests/test_gui_regressions.py`.

## Не сделано (по порядку)

1. **Приёмка** (сценарии Г.1–Г.10, kicad-cli, покрытие ≥ 80 %, охота на дефекты до исчерпания)
   — `scripts/workflows/qa.js`.
2. **Документация** по ТЗ п.5 (описание программы, руководство пользователя, руководство
   программиста, ПМИ) + README + DOCX — `scripts/workflows/docs.js`.

Волна **core** (`scripts/workflows/core.js`) выполнена в облаке 2026-09-28 (19 агентов Opus,
~10,5 ч при 4 CPU → 2 агента одновременно); фазы Sexpr/Review-Sexpr пропускались через
`args.skip_sexpr: true`. Волна **gui** выполнена 2026-09-28 (8 агентов; дважды
возобновлялась через `resumeFromRunId` после перезапуска контейнера и прерывания пользователем —
кэш завершённых агентов сработал; `gui.js` принимает `args.main_note` для дополнения промпта
главного окна).

Скрипты рассчитаны на инструмент Workflow: запускать `Workflow({scriptPath, args: {repo:
"<абсолютный путь к репозиторию>", kicad_cli: "<путь к kicad-cli>", kicad_note: "<описание
доступного kicad-cli для промптов>"}})`; в скриптах `REPO` берётся из `args.repo`, `PY` =
`REPO/.venv/bin/python`, справочники — `REPO/refs/...`, кэш — `REPO/.cache/...`;
`core.js` дополнительно принимает `skip_sexpr: true`. Все агенты с `model: 'opus'`. Промпты
агентов содержат полный контекст задач; при необходимости их можно править. Число
одновременно работающих агентов = min(16, CPU − 2).

## Важные решения и находки (не терять)

* Представления над деревом: setter меняет только свой токен; новые токены — по таблицам
  порядка; неизвестные узлы сохраняются. Числа хранят исходный текст.
* Стиль записи = по версии файла: ≥ 20231014 — Prettify (табы); 20221018–20231013 — раскладка
  7.0; < 20221018 — 6.0; корень `module` — 5.1. Новые корпуса: version 20241229, generator
  "kicadfp", стиль KiCad 9.
* KiCad **не читает** файлы с неизвестными токенами (parser → Expecting). Сценарий Г.3
  (сохранение `example_token`) проверяется самой Программой; в документации это отметить.
* `fill`: 6.0–8.0 пишут `solid/none`, 9.0+ `yes/no`; `hide`: голый в 6/7, `(hide yes)` в 8+;
  `F&B.Cu` KiCad 9.0.6+ пишет как `*.Cu`; `solder_paste_ratio` (footprint) до 9.0, потом
  `solder_paste_margin_ratio`; 3D-`offset` в мм, старая форма `(at (xyz))` — дюймы.
* Конвертер `.mod`: параметр `compat="kicad9"|"fixed"` (KiCad 9 пишет смещение 3D `Of` в
  дюймах как мм — известная ошибка). Эталон конвертации `My_lib.mod` — в legacy-mod.md.
* Генераторы: лабораторные `lab_dip14/lab_mlt/lab_snp8` строго по методичке (площадки 1.3,
  отверстия 0.8, шаг 2.5, первая квадратная, монтажные отверстия 3 мм); семейства по KLC.
* Файлы библиотек, записанные не KiCad (kicad-footprint-generator), отличаются по
  раскладке (по одной точке `xy` в строке, нет `\n` в конце у 8.0.0) — в тестах это учтено.
