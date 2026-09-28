# Отчёт о приёмочных испытаниях kicadfp

Сформирован автоматически: 2026-09-28 13:27 UTC; команда `python scripts/acceptance_report.py --full` (скрипт `scripts/acceptance_report.py`). Сценарии — ТЗ, приложение Г (таблица Г.1) и п. 8.2; тесты — `tests/test_acceptance.py` (сценарии), `tests/test_kicad_cli.py` (совместимость с KiCad), `tests/test_gui_mainwindow.py` (Г.8 в окне) и модульные тесты решений из критики спецификаций. Проверка «открыть в KiCad» выполняется командной строкой KiCad (`kicad-cli fp upgrade --force`, ТЗ 4.5.4): KiCad читает и пересохраняет корпус без сообщений, а прочитанное KiCad совпадает с прочитанным kicadfp.

Итог: запущено тестов — 546, пройдено — 546, не пройдено — 0, пропущено — 0; время — 467 с.

## 1. Условия испытаний

| Параметр | Значение |
|---|---|
| kicadfp | 0.1.0; git ccaf508 + незафиксированные изменения |
| Python | 3.11.15 (/home/user/kicadfp/.venv/bin/python) |
| ОС, процессор | Linux-6.18.44-fc-v37-x86_64-with-glibc2.39, 4 CPU |
| Графический интерфейс | PySide6 6.11.2, Qt 6.11.2 (QT_QPA_PLATFORM=offscreen) |
| pytest | 9.1.1 |
| KiCad 9 | kicad-cli 9.0.1 (/usr/local/bin/kicad-cli) |
| KiCad 8 | kicad-cli 8.0.6 (/usr/local/bin/kicad-cli8) |
| Фикстуры (tests/fixtures) | kicad5 — 166, kicad6 — 224, kicad8 — 1377, kicad9 — 337, kicad10dev — 208, special — 221; всего 2533; legacy_mod/My_lib.mod (3 модуля) |
| Библиотеки KiCad 8 (расширенный Г.1) | .cache/kfp/v8.0.0: 20 библиотек, 4517 файлов |

## 2. Сводная таблица

| № | Сценарий | Ожидаемый результат | Фактический результат | Тесты | Время, с | Итог |
|---|---|---|---|---|---|---|
| Г.1 | Открыть ≥ 200 корпусов стандартных библиотек KiCad 8, сохранить без изменений, сравнить деревья S-выражений | Совпадение деревьев для всех файлов | Открыто и сохранено 1377 корпусов стандартных библиотек KiCad 8 (Capacitor_THT, Connector_PinHeader_2.54mm, Package_DIP, Package_SO, Resistor_THT): деревья S-выражений совпали у 1377 из 1377 (строгое сравнение: числа и кавычки как в исходнике); байт в байт — 1377 из 1377 файлов, записанных KiCad; 20.08 с. Расширенный прогон: 20 библиотек kicad-footprints 8.0.0, 4517 файлов — деревья 4517/4517, байт в байт 4517/4517; без ошибок: KiCad 9.0.1 открыл 4517/4517 (содержимое совпало у 904 из 904 проверенных); KiCad 8.0.6 открыл 4517/4517 (содержимое совпало у 904 из 904 проверенных); 64.73 с. KiCad 9.0.1 и 8.0.6: открыто без ошибок, содержимое совпадает. | 4/4 | 142.2 | выполнен |
| Г.2 | Открыть корпус KiCad 6 (width, fp_text), сохранить, открыть в KiCad 8 и 9 | Файл открывается без ошибок, графика и тексты на месте | DIP-14_W7.62mm формата KiCad 6 (version 20211014, width, fp_text): 14 площадок, 15 графических элементов, 3 текста; сохранён без изменений (байт в байт) и с правкой (новая линия width 0.15 и текст fp_text — в форме KiCad 6). KiCad 9.0.1 и 8.0.6: открыто без ошибок, содержимое совпадает. | 4/4 | 11.4 | выполнен |
| Г.3 | В корпус DIP-14 добавить неизвестный узел (example_token 1 2), изменить размер площадки 1, сохранить | Неизвестный узел сохранён без изменений, изменена только площадка 1 | Узел (example_token 1 2) сохранён без изменений (та же строка, то же место); изменилась одна строка файла — (size 1.6 1.6) → (size 2 2) площадки 1 (расхождения дерева: footprint/pad[0]/size[0]: атом 0: 1.6 != 2; footprint/pad[0]/size[0]: атом 1: 1.6 != 2). KiCad 9.0.1: открыто без ошибок, содержимое совпадает (то же изменение без неизвестного узла: KiCad отвергает неизвестные токены). | 3/3 | 1.2 | выполнен |
| Г.4 | У всех площадок: форма roundrect с rratio 0.25, слои F.Cu F.Mask F.Paste, тип smd, удалить отверстия | Проверка не выдаёт ошибок, KiCad показывает SMD-корпус | DIP-14 → SMD (roundrect 0.25, F.Cu F.Mask F.Paste, smd, без отверстий, attr smd) в форматах KiCad 8, 6 и 5: kicad8: 14 площадок, ошибок 0, предупреждений нет; kicad6: 14 площадок, ошибок 0, предупреждений нет; kicad5: 14 площадок, ошибок 0, предупреждений нет; запись в строгом режиме выполнена, изменены только площадки и атрибут. KiCad 9.0.1: открыто без ошибок, содержимое совпадает. | 5/5 | 1.4 | выполнен |
| Г.5 | Сгенерировать dip14, mlt, snp8 по параметрам лабораторной работы, открыть в KiCad | Площадки 1,3 мм, отверстия 0,8 мм, первая площадка квадратная, шаг и контур соответствуют заданию | dip14: 14 площадок; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; шаг 2.5, расстояние между рядами 7.5; контур 5×17.5 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00126 мм. mlt: 2 площадки; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; расстояние между площадками 10; контур 7.5×2.5 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00126 мм. snp8: 8 площадок + 2 монтажных отверстия Ø3; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; шаг 2.5, расстояние между рядами 5; контур 12.5×25 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00098 мм. KiCad 9.0.1 и 8.0.6: открыто без ошибок, содержимое совпадает. | 9/9 | 1.3 | выполнен |
| Г.6 | Задать площадке отверстие 1,5 мм при размере 1,3 мм, выполнить проверку | Сообщение об ошибке «отверстие больше площадки» | lab_dip14: «ERROR PAD_DRILL_GT_SIZE: площадка «1» (-3.75; -7.5): отверстие больше площадки по оси X и Y: отверстие 1.5 мм, площадка rect 1.3×1.3 мм». | 3/3 | 0.1 | выполнен |
| Г.7 | Открыть файл с синтаксической ошибкой (незакрытая скобка) | Сообщение с номером строки и позиции, модель не создаётся | Не закрыта скобка (at …) площадки 5: «строка 262, позиция 3: незакрытая скобка: не закрыт узел «at» (строка 263 начинается на том же уровне отступа, что и строка узла); в конце файла (строка 352) остался незакрытым узел «footprint» (открыт в строке 1, позиция 1)»; модель не создана. | 4/4 | 0.0 | выполнен |
| Г.8 | В графическом интерфейсе переместить площадку мышью и в таблице, отменить, повторить, сохранить | Значения в таблице и на поле просмотра совпадают, файл содержит итоговые координаты | Главное окно (tests/test_gui_mainwindow.py): перетаскивание площадки 1 мышью (0; 0) → (−2; −3), ввод X = 5.08 в таблице, Ctrl+Z / меню «Отменить», Ctrl+Shift+Z / «Повторить», «Сохранить как», Ctrl+S — пройден; значения модели, таблицы и поля просмотра совпадают на каждом шаге. | 3/3 | 0.3 | выполнен |
| Г.9 | Скопировать корпус из одной библиотеки .pretty в другую с переименованием | В целевой библиотеке появился файл с новым именем и полем name, исходный не изменён | Library.copy_to(…, "dip14_copy"): в целевой библиотеке один файл dip14_copy.kicad_mod с полем name «dip14_copy»; исходная библиотека (268 файлов) не изменена (SHA-256 совпадают); отличие копии от исходного корпуса — только имя: footprint: атом 0: "DIP-14_W7.62mm" != "dip14_copy"; footprint/property[1]: атом 1: "DIP-14_W7.62mm" != "dip14_copy". KiCad 9.0.1: открыто без ошибок, содержимое совпадает. | 2/2 | 0.8 | выполнен |
| Г.10 | Преобразовать библиотеку старого формата .mod (PCBnew-LibModule-V1) в .pretty | Каждый модуль сохранён отдельным файлом .kicad_mod, единицы переведены из децимил в миллиметры, открывается в KiCad | My_lib.mod → My_lib.pretty: 3 модуля — по файлу на модуль (dip14.kicad_mod, mlt.kicad_mod, snp8.kicad_mod); 46 значений (координаты, размеры, отверстия площадок, отрезки, тексты) равны децимилам × 0.00254 мм (например, 512 → 1.30048). KiCad 9.0.1 и 8.0.6: открыто без ошибок, содержимое совпадает. | 4/4 | 2.4 | выполнен |

## 3. Сценарии

### Г.1. Открыть ≥ 200 корпусов стандартных библиотек KiCad 8, сохранить без изменений, сравнить деревья S-выражений

**Ожидаемый результат (ТЗ):** Совпадение деревьев для всех файлов.

**Как проверяется:** kicadfp.load → kicadfp.save → разбор исходного и записанного файла, сравнение деревьев (sexpr.equal/diff) и байтов; записанные файлы — kicad-cli fp upgrade (KiCad 9 и 8).

**Фактический результат:**

- Открыто и сохранено 1377 корпусов стандартных библиотек KiCad 8 (Capacitor_THT, Connector_PinHeader_2.54mm, Package_DIP, Package_SO, Resistor_THT): деревья S-выражений совпали у 1377 из 1377 (строгое сравнение: числа и кавычки как в исходнике); байт в байт — 1377 из 1377 файлов, записанных KiCad; 20.08 с.
- Сохранённые файлы в KiCad: KiCad 9.0.1: 1377/1377 без ошибок; KiCad 8.0.6: 1377/1377 без ошибок (содержимое после чтения KiCad совпадает).
- Расширенный прогон: 20 библиотек kicad-footprints 8.0.0, 4517 файлов — деревья 4517/4517, байт в байт 4517/4517; без ошибок: KiCad 9.0.1 открыл 4517/4517 (содержимое совпало у 904 из 904 проверенных); KiCad 8.0.6 открыл 4517/4517 (содержимое совпало у 904 из 904 проверенных); 64.73 с.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_1_full_kicad8_library` — пройден (93.69 с)
- `tests/test_acceptance.py::test_scenario_1_roundtrip_kicad8_libraries` — пройден (20.10 с)
- `tests/test_acceptance.py::test_scenario_1_saved_files_open_in_kicad8` — пройден (13.13 с)
- `tests/test_acceptance.py::test_scenario_1_saved_files_open_in_kicad9` — пройден (15.30 с)

**Итог:** выполнен.

### Г.2. Открыть корпус KiCad 6 (width, fp_text), сохранить, открыть в KiCad 8 и 9

**Ожидаемый результат (ТЗ):** Файл открывается без ошибок, графика и тексты на месте.

**Как проверяется:** DIP-14_W7.62mm (version 20211014) — сохранить без изменений и с правкой; kicad-cli 9.0.1 и 8.0.6 читают и пересохраняют; сравнение площадок, графики, текстов; то же для всех 224 корпусов формата KiCad 6.

**Фактический результат:**

- DIP-14_W7.62mm формата KiCad 6 (version 20211014, width, fp_text): 14 площадок, 15 графических элементов, 3 текста; сохранён без изменений (байт в байт) и с правкой (новая линия width 0.15 и текст fp_text — в форме KiCad 6).
- KiCad 9.0.1 открыл оба файла без ошибок: площадки, графика (с толщинами) и тексты на месте.
- KiCad 8.0.6 открыл оба файла без ошибок: площадки, графика (с толщинами) и тексты на месте.
- Все корпуса формата KiCad 6 (фикстура kicad6): KiCad 9.0.1: 224/224 без ошибок; KiCad 8.0.6: 224/224 без ошибок.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_2_all_kicad6_fixtures_open_in_kicad[kicad8]` — пройден (4.84 с)
- `tests/test_acceptance.py::test_scenario_2_all_kicad6_fixtures_open_in_kicad[kicad9]` — пройден (5.45 с)
- `tests/test_acceptance.py::test_scenario_2_kicad6_footprint_opens_in_kicad8` — пройден (0.46 с)
- `tests/test_acceptance.py::test_scenario_2_kicad6_footprint_opens_in_kicad9` — пройден (0.65 с)

**Итог:** выполнен.

### Г.3. В корпус DIP-14 добавить неизвестный узел (example_token 1 2), изменить размер площадки 1, сохранить

**Ожидаемый результат (ТЗ):** Неизвестный узел сохранён без изменений, изменена только площадка 1.

**Как проверяется:** В файл DIP-14 (KiCad 8) вставлена строка (example_token 1 2); kicadfp.load, pad("1").size = (2, 2), kicadfp.save; сравнение текста и деревьев до/после.

**Фактический результат:**

- Узел (example_token 1 2) сохранён без изменений (та же строка, то же место); изменилась одна строка файла — (size 1.6 1.6) → (size 2 2) площадки 1 (расхождения дерева: footprint/pad[0]/size[0]: атом 0: 1.6 != 2; footprint/pad[0]/size[0]: атом 1: 1.6 != 2).
- То же командой kicadfp set … "pad[1].size" 2: пройден.
- KiCad 9.0.1 читает то же изменение без неизвестного узла (площадка 1 — 2 × 2, остальное без изменений). Файл с неизвестным узлом KiCad не открывает («Unable to load library»).

**Примечание.** KiCad отвергает файл с неизвестным ему узлом (парсер parseFOOTPRINT → «Expecting …», kicad-cli: «Unable to load library»), поэтому требование сценария — сохранение узла — проверяется самой Программой, а проверка в KiCad выполняется на том же изменении файла без неизвестного узла. Это ограничение KiCad, а не Программы.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_3_cli_set_keeps_unknown_node` — пройден (0.02 с)
- `tests/test_acceptance.py::test_scenario_3_kicad_reads_the_edit_without_unknown_node` — пройден (1.16 с)
- `tests/test_acceptance.py::test_scenario_3_unknown_node_kept_only_pad1_changed` — пройден (0.01 с)

**Итог:** выполнен.

### Г.4. У всех площадок: форма roundrect с rratio 0.25, слои F.Cu F.Mask F.Paste, тип smd, удалить отверстия

**Ожидаемый результат (ТЗ):** Проверка не выдаёт ошибок, KiCad показывает SMD-корпус.

**Как проверяется:** API: pad.shape/roundrect_rratio/layers/type/drill, attrs = {smd}; то же командами kicadfp set "pad[*]…"; validate; kicad-cli fp upgrade и fp export svg.

**Фактический результат:**

- DIP-14 → SMD (roundrect 0.25, F.Cu F.Mask F.Paste, smd, без отверстий, attr smd) в форматах KiCad 8, 6 и 5: kicad8: 14 площадок, ошибок 0, предупреждений нет; kicad6: 14 площадок, ошибок 0, предупреждений нет; kicad5: 14 площадок, ошибок 0, предупреждений нет; запись в строгом режиме выполнена, изменены только площадки и атрибут.
- Групповое изменение командами kicadfp set "pad[*]…": пройден (тот же файл, что и через API).
- KiCad 9.0.1: 3 файла прочитаны без ошибок, все площадки SMD roundrect 0.25, attr smd; SVG слоёв F.Cu+F.Paste построен (13285 байт).

**Тесты:**

- `tests/test_acceptance.py::test_scenario_4_all_pads_to_smd_roundrect[kicad5]` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_4_all_pads_to_smd_roundrect[kicad6]` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_4_all_pads_to_smd_roundrect[kicad8]` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_4_kicad_shows_smd_footprint` — пройден (1.30 с)
- `tests/test_acceptance.py::test_scenario_4_same_result_with_cli_set` — пройден (0.05 с)

**Итог:** выполнен.

### Г.5. Сгенерировать dip14, mlt, snp8 по параметрам лабораторной работы, открыть в KiCad

**Ожидаемый результат (ТЗ):** Площадки 1,3 мм, отверстия 0,8 мм, первая площадка квадратная, шаг и контур соответствуют заданию.

**Как проверяется:** generators.lab_dip14/lab_mlt/lab_snp8 (и kicadfp gen dip14/mlt/snp8); сравнение с заданием (lab-generators.md §2) и с корпусами, созданными вручную (My_lib.mod); kicad-cli 9 (формат KiCad 9) и 8 (формат KiCad 8).

**Фактический результат:**

- dip14: 14 площадок; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; шаг 2.5, расстояние между рядами 7.5; контур 5×17.5 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00126 мм.
- mlt: 2 площадки; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; расстояние между площадками 10; контур 7.5×2.5 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00126 мм.
- snp8: 8 площадок + 2 монтажных отверстия Ø3; 1.3 × 1.3, отверстия 0.8, площадка 1 — rect, остальные — circle; шаг 2.5, расстояние между рядами 5; контур 12.5×25 мм; отличие от корпуса, созданного вручную (My_lib.mod), — не более 0.00098 мм.
- kicadfp gen dip14/mlt/snp8 -o …: пройден (те же файлы, что и API).
- KiCad 9 (формат 20241229): kicad-cli 9.0.1 открыл 3 корпуса без ошибок, после чтения — те же площадки и контур.
- KiCad 8 (формат 20240108): kicad-cli 8.0.6 открыл 3 корпуса без ошибок, после чтения — те же площадки и контур.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_5_cli_gen_same_as_api` — пройден (0.04 с)
- `tests/test_acceptance.py::test_scenario_5_lab_footprint_matches_assignment[dip14]` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_5_lab_footprint_matches_assignment[mlt]` — пройден (0.00 с)
- `tests/test_acceptance.py::test_scenario_5_lab_footprint_matches_assignment[snp8]` — пройден (0.00 с)
- `tests/test_acceptance.py::test_scenario_5_lab_footprints_open_in_kicad[kicad8]` — пройден (0.60 с)
- `tests/test_acceptance.py::test_scenario_5_lab_footprints_open_in_kicad[kicad9]` — пройден (0.66 с)
- `tests/test_acceptance.py::test_scenario_5_matches_hand_made_footprint[dip14]` — пройден (0.00 с)
- `tests/test_acceptance.py::test_scenario_5_matches_hand_made_footprint[mlt]` — пройден (0.00 с)
- `tests/test_acceptance.py::test_scenario_5_matches_hand_made_footprint[snp8]` — пройден (0.00 с)

**Итог:** выполнен.

### Г.6. Задать площадке отверстие 1,5 мм при размере 1,3 мм, выполнить проверку

**Ожидаемый результат (ТЗ):** Сообщение об ошибке «отверстие больше площадки».

**Как проверяется:** pad.size = 1.3, pad.drill = 1.5; validate(); save(strict=True); kicadfp validate.

**Фактический результат:**

- lab_dip14: «ERROR PAD_DRILL_GT_SIZE: площадка «1» (-3.75; -7.5): отверстие больше площадки по оси X и Y: отверстие 1.5 мм, площадка rect 1.3×1.3 мм».
- kicad8: «ERROR PAD_DRILL_GT_SIZE: площадка «1» (0; 0): отверстие больше площадки по оси X и Y: отверстие 1.5 мм, площадка rect 1.3×1.3 мм».
- Запись в строгом режиме отклоняется (ValidationError), по умолчанию — выполняется; kicadfp validate — код 1: пройден.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_6_cli_validate_reports_error` — пройден (0.03 с)
- `tests/test_acceptance.py::test_scenario_6_drill_bigger_than_pad_is_error[kicad8]` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_6_drill_bigger_than_pad_is_error[lab_dip14]` — пройден (0.01 с)

**Итог:** выполнен.

### Г.7. Открыть файл с синтаксической ошибкой (незакрытая скобка)

**Ожидаемый результат (ТЗ):** Сообщение с номером строки и позиции, модель не создаётся.

**Как проверяется:** DIP-14 без «)» у (at …) площадки 5 и без последней «)»; kicadfp.load (конструктор Footprint подменён счётчиком), kicadfp info/validate/pads/set, FootprintDocument.open.

**Фактический результат:**

- Не закрыта скобка (at …) площадки 5: «строка 262, позиция 3: незакрытая скобка: не закрыт узел «at» (строка 263 начинается на том же уровне отступа, что и строка узла); в конце файла (строка 352) остался незакрытым узел «footprint» (открыт в строке 1, позиция 1)»; модель не создана.
- Нет последней скобки файла: «строка 352, позиция 1: незакрытая скобка: узел «footprint» (открыт в строке 1, позиция 1)»; модель не создана.
- Командная строка (info, validate, pads, set) — код 2 и то же сообщение: пройден; документ GUI не открывается: пройден.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_7_cli_exit_code_2` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_7_gui_document_not_created` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_7_syntax_error_line_and_position[end]` — пройден (0.00 с)
- `tests/test_acceptance.py::test_scenario_7_syntax_error_line_and_position[middle]` — пройден (0.00 с)

**Итог:** выполнен.

### Г.8. В графическом интерфейсе переместить площадку мышью и в таблице, отменить, повторить, сохранить

**Ожидаемый результат (ТЗ):** Значения в таблице и на поле просмотра совпадают, файл содержит итоговые координаты.

**Как проверяется:** pytest-qt, QT_QPA_PLATFORM=offscreen: главное окно (мышь, таблица, клавиши, меню) и документ без окна.

**Фактический результат:**

- Главное окно (tests/test_gui_mainwindow.py): перетаскивание площадки 1 мышью (0; 0) → (−2; −3), ввод X = 5.08 в таблице, Ctrl+Z / меню «Отменить», Ctrl+Shift+Z / «Повторить», «Сохранить как», Ctrl+S — пройден; значения модели, таблицы и поля просмотра совпадают на каждом шаге.
- Без окна (FootprintDocument + модель таблицы + команда канвы): итоговые координаты в файле (5.08; -3), изменён только узел (at …) площадки 1; после отмены всех шагов файл совпадает с исходным байт в байт.

**Тесты:**

- `tests/test_acceptance.py::test_scenario_8_document_move_undo_redo_save` — пройден (0.01 с)
- `tests/test_acceptance.py::test_scenario_8_gui_test_is_present` — пройден (0.00 с)
- `tests/test_gui_mainwindow.py::test_scenario_8_drag_and_table_undo_redo_save` — пройден (0.29 с)

**Итог:** выполнен.

### Г.9. Скопировать корпус из одной библиотеки .pretty в другую с переименованием

**Ожидаемый результат (ТЗ):** В целевой библиотеке появился файл с новым именем и полем name, исходный не изменён.

**Как проверяется:** Library(src).copy_to(Library(dst, create=True), "DIP-14_W7.62mm", "dip14_copy"); SHA-256 файлов источника до/после; kicad-cli.

**Фактический результат:**

- Library.copy_to(…, "dip14_copy"): в целевой библиотеке один файл dip14_copy.kicad_mod с полем name «dip14_copy»; исходная библиотека (268 файлов) не изменена (SHA-256 совпадают); отличие копии от исходного корпуса — только имя: footprint: атом 0: "DIP-14_W7.62mm" != "dip14_copy"; footprint/property[1]: атом 1: "DIP-14_W7.62mm" != "dip14_copy".
- KiCad 9.0.1 читает целевую библиотеку, корпус «dip14_copy».

**Тесты:**

- `tests/test_acceptance.py::test_scenario_9_copied_footprint_opens_in_kicad` — пройден (0.73 с)
- `tests/test_acceptance.py::test_scenario_9_copy_with_rename` — пройден (0.07 с)

**Итог:** выполнен.

### Г.10. Преобразовать библиотеку старого формата .mod (PCBnew-LibModule-V1) в .pretty

**Ожидаемый результат (ТЗ):** Каждый модуль сохранён отдельным файлом .kicad_mod, единицы переведены из децимил в миллиметры, открывается в KiCad.

**Как проверяется:** legacy.convert(My_lib.mod) и kicadfp convert; независимый разбор чисел .mod; kicad-cli 9 и 8; сравнение с собственным конвертером KiCad (kicad-cli fp upgrade My_lib.mod).

**Фактический результат:**

- My_lib.mod → My_lib.pretty: 3 модуля — по файлу на модуль (dip14.kicad_mod, mlt.kicad_mod, snp8.kicad_mod); 46 значений (координаты, размеры, отверстия площадок, отрезки, тексты) равны децимилам × 0.00254 мм (например, 512 → 1.30048).
- kicadfp convert … -o …: пройден.
- KiCad 9 (формат 20241229): kicad-cli 9.0.1 открыл результат без ошибок; содержимое совпадает с собственным конвертером KiCad (3 из 3).
- KiCad 8 (формат 20240108): kicad-cli 8.0.6 открыл результат без ошибок; содержимое совпадает с собственным конвертером KiCad (3 из 3).

**Тесты:**

- `tests/test_acceptance.py::test_scenario_10_cli_convert` — пройден (0.03 с)
- `tests/test_acceptance.py::test_scenario_10_convert_legacy_library` — пройден (0.02 с)
- `tests/test_acceptance.py::test_scenario_10_converted_library_opens_in_kicad[kicad8]` — пройден (1.23 с)
- `tests/test_acceptance.py::test_scenario_10_converted_library_opens_in_kicad[kicad9]` — пройден (1.12 с)

**Итог:** выполнен.

## 4. Совместимость с KiCad (tests/test_kicad_cli.py)

Корпуса записываются kicadfp в каталог .pretty, `kicad-cli fp upgrade --force` читает и пересохраняет каждый; KiCad не выдаёт сообщений, прочитанное KiCad (площадки, графика, тексты, 3D-модели) совпадает с прочитанным kicadfp. Режимы: `save` — открыть и сохранить без изменений; `upgrade` — Footprint.upgrade() в формат KiCad 9 (для KiCad 8 — 20240108); `edit` — сдвиг, поворот, размеры площадок, новая линия и текст, описание. В ячейках — «совпало/файлов»; KiCad 8 проверяет файлы форматов до 20240108 включительно.

Проверены все файлы фикстур.

| Фикстуры | Режим | KiCad 9 | KiCad 8 |
|---|---|---|---|
| kicad5 | save | 166/166 | 166/166 |
| kicad5 | upgrade | 166/166 | 166/166 |
| kicad5 | edit | 166/166 | 166/166 |
| kicad6 | save | 224/224 | 224/224 |
| kicad6 | upgrade | 224/224 | 224/224 |
| kicad6 | edit | 224/224 | 224/224 |
| kicad8 | save | 1377/1377 | 1377/1377 |
| kicad8 | upgrade | 1377/1377 | 1377/1377 |
| kicad8 | edit | 1377/1377 | 1377/1377 |
| kicad9 | save | 337/337 | 143/143 |
| kicad9 | upgrade | 337/337 | 143/143 |
| kicad9 | edit | 337/337 | 143/143 |
| special | save | 183/183 | 157/157 |
| special | upgrade | 183/183 | 157/157 |
| special | edit | 183/183 | 157/157 |

Всего записано kicadfp и открыто без ошибок: KiCad 9.0.1 — 6861 файл (содержимое совпало у 6861); KiCad 8.0.6 — 6201 файл (содержимое совпало у 6201).

Новые корпуса (все варианты генераторов из tests/test_generators.py) и результат преобразования .mod (My_lib.mod + синтетическая библиотека) в каждом формате:

| Формат | Генераторы: KiCad 9 | Генераторы: KiCad 8 | .mod: KiCad 9 | .mod: KiCad 8 |
|---|---|---|---|---|
| KiCad 6 (20211014) | 35/35 | 35/35 | 3/3 + 4/4 | 3/3 + 4/4 |
| KiCad 7 (20221018) | 35/35 | 35/35 | 3/3 + 4/4 | 3/3 + 4/4 |
| KiCad 8 (20240108) | 35/35 | 35/35 | 3/3 + 4/4 | 3/3 + 4/4 |
| KiCad 9 (20241229) | 35/35 | — | 3/3 + 4/4 | — |

KiCad 8.0.6 файл формата KiCad 9 (20241229) не открывает («Unable to load library»), тот же корпус в формате KiCad 8 — открывает; отсюда параметр формата у генераторов и преобразования (раздел 6).

Команды `kicadfp gen` (dip14/mlt/snp8, пример ТЗ В.3) и `kicadfp convert`: формат KiCad 9 — пройден, `--kicad 8` — пройден.

## 5. Решения из критики спецификаций

| Пункт | Решение и факт | Проверка |
|---|---|---|
| Неизвестные токены: KiCad их отвергает | Программа сохраняет неизвестный узел без изменений (Г.3); проверка в KiCad — на файле без неизвестного узла; ограничение отмечено в отчёте и тестах. | пройдено 2 из 2: `test_scenario_3_unknown_node_kept_only_pad1_changed`, `test_scenario_3_kicad_reads_the_edit_without_unknown_node` |
| validate: PAD_NPTH_NUMBER, PAD_EMPTY_NUMBER, LAYER_RESCUE, VERSION_TOO_NEW, PAD_THT_NO_COPPER; COURTYARD_MISSING не выдаётся при allow_missing_courtyard; нет ложных error на реальных библиотеках | Реализовано (kicadfp/validate.py); все 2533 фикстуры (kicad5–10dev, special) — без ошибок. | пройдено 6 из 6: `test_npth_number_and_empty_number`, `test_rescue_layer`, `test_version_too_new`, `test_tht_no_outer_copper`, `test_courtyard_missing`, `test_all_fixtures_no_errors` |
| legacy: compat="kicad9"\|"fixed", LegacyFormatError с номером строки | Реализовано; результат compat="kicad9" совпадает с kicad-cli 9.0.1 (кроме uuid). | пройдено 4 из 4: `test_shape3d_kicad9_and_fixed`, `test_format_error_position_and_path`, `test_compat_validation`, `test_kicad_cli_same_as_kicad_converter` |
| Model: старая форма (at (xyz)) — дюймы ×25.4 | Реализовано (×25.4f, как парсер KiCad); KiCad пишет offset в мм — значения совпадают. | пройдено 2 из 2: `test_legacy_at_is_inches_times_float_25_4`, `test_model_old_at_form_is_inches` |
| F&B.Cu (6.0–9.0.5) и *.Cu (9.0.6+) | Исходная форма сохраняется, layers.expand понимает обе, KiCad читает обе. | пройдено 2 из 2: `test_wildcards_and_parser_names`, `test_fb_cu_and_star_cu_read_alike` |
| fill: solid/none (6.0–8.0), yes/no (9.0+); примитивы custom — yes/none (6/7), yes/no (8+) | Чтение всех форм, запись по профилю версии; KiCad читает то же значение. | пройдено 26 из 26: `test_fill_read_forms`, `test_fill_write_by_profile`, `test_fill_write_primitives`, `test_fill_forms_by_version_read_by_kicad` |
| hide у fp_text user в 9.0+ | Text.hide = True пишет (hide yes): в формате KiCad 8+ текст становится скрытым полем FieldN (как делает парсер KiCad 9). Проверено: kicad-cli 9.0.1 такое поле сохраняет, а (fp_text user … (hide yes)) при чтении теряет — поэтому запись полем надёжнее. | пройдено 3 из 3: `test_hidden_user_text_becomes_hidden_field_in_kicad9`, `test_hidden_user_text_survives_kicad` |
| Числа: углы < 1e-4 KiCad пишет с экспонентой | kicadfp пишет без экспоненты, исходная запись сохраняется; лексеры обоих читают обе. | пройдено 35 из 35: `test_number_formats_match_kicad_c_reference`, `test_small_angle_with_exponent` |
| Фикстуры special/* (221 файл редких конструкций): round-trip и model-тесты | Round-trip проходит; все представления читаются без исключений на каждом файле; записанные kicadfp файлы читает KiCad (выборка special в test_kicad_cli). | пройдено 236 из 236: `test_views_read_every_special_fixture`, `test_fixtures_written_by_kicadfp_open_in_kicad9` |

## 6. Дефекты, найденные при приёмке, и исправления

1. **Новые корпуса открывались только в KiCad 9.** Генераторы, преобразование .mod и GUI «Создать типовой корпус» писали только формат KiCad 9 (version 20241229), а KiCad 8 такой файл не открывает («Unable to load library» — версия новее его собственной), что противоречит ТЗ 4.5.3 («открываться в KiCad 8 и 9») для сценариев Г.5 и Г.10.

   Исправление: формат нового корпуса выбирается (по умолчанию — прежний, KiCad 9): format_rules.KICAD_FORMAT_VERSIONS/kicad_format_version; generators.target_version(8) (контекст) и from_json(…, version=8); legacy.convert/read_library/loads_library(…, version=8) (в формате KiCad 6 без thermal_bridge_angle — токена там нет); CLI kicadfp gen/convert --kicad {6,7,8,9}; GUI — поле «Формат файла» в диалоге «Создать типовой корпус». Корпуса генераторов и результат преобразования в форматах KiCad 6–8 проверены kicad-cli 8.0.6 и 9.0.1.

   Регрессионные тесты — пройдено 159 из 159: `test_target_version_every_generator`, `test_target_version_forms_of_kicad8_and_kicad6`, `test_from_json_version`, `test_version_target_same_content`, `test_version_kicad6_has_no_thermal_bridge_angle`, `test_gen_and_convert_kicad_target`, `test_generate_dialog_kicad_format`, `test_kicad_format_versions`, `test_all_generators_open_in_kicad8`, `test_convert_result_opens_in_kicad8`, `test_kicad8_needs_kicad8_format`.

2. **Позиция ошибки «незакрытая скобка» указывала на конец файла.** Пропущенная «)» в середине файла сдвигает все следующие закрывающие скобки, и к концу файла открытым остаётся корень: сообщение называло строку конца файла и корень footprint, а не место ошибки (сценарий Г.7).

   Исправление: при незакрытой скобке sexpr.parse находит по отступам (KiCad пишет файлы с отступами по вложенности) узел, который должен был закрыться раньше, и сообщает его строку и позицию («строка 262, позиция 3: незакрытая скобка: не закрыт узел «at» …»); если подсказки нет (файл в одну строку, не хватает последней скобки) — прежнее сообщение. Разбор корректных файлов не изменился (подсказка вычисляется только при ошибке).

   Регрессионные тесты — пройдено 4 из 4: `test_unclosed_paren_in_the_middle_points_to_the_node`, `test_unclosed_paren_without_indent_hint_reports_end`, `test_scenario_7_syntax_error_line_and_position`.

## 7. Замечания

- kicad-cli 9.0.1 читает старые библиотеки `.mod` (`kicad-cli fp upgrade My_lib.mod -o …`): это использовано в Г.10 для сравнения с собственным конвертером KiCad; kicad-cli 8.0.6 — тоже.
- KiCad 8 для проверок установлен из бинарного кэша Nix (канал nixos-24.11, `kicad-small` 8.0.6) в отдельный профиль: `nix-env -p /nix/var/nix/profiles/kicad8 -f https://channels.nixos.org/nixos-24.11/nixexprs.tar.xz -iA kicad-small`, ссылка `/usr/local/bin/kicad-cli8`; тесты находят его по `KICAD8_CLI` или `kicad-cli8` в PATH.
- Файлы KiCad 10-dev (`version 20260206`, фикстуры kicad10dev) kicad-cli 9 и 8 не читают — это ожидаемо (формат новее), они проверяются round-trip-тестами.
- Открытые и сохранённые корпуса сохраняют свой формат: файлы форматов KiCad 5–8 после записи Программой открывают и KiCad 8, и KiCad 9, файл формата KiCad 9 — KiCad 9 (как и исходный). Новые корпуса по умолчанию создаются в формате KiCad 9; для KiCad 8 — формат KiCad 8: `kicadfp gen … --kicad 8`, `kicadfp convert … --kicad 8`, `generators.target_version(8)`, `Footprint.new(name, version=20240108)`, поле «Формат файла» в диалоге «Создать типовой корпус». Пустой корпус из меню «Создать корпус…» создаётся в формате KiCad 9 (выбора формата там нет).
- При пересохранении KiCad нормализует файл сам (это не расхождение kicadfp): стирает номер у неметаллизированных отверстий и апертур, добавляет пустые служебные поля, пишет `%R`/`%V` как `${REFERENCE}`/`${VALUE}`, упорядочивает элементы; сравнение это учитывает (`tests/kicad_cli_tools.py`).
