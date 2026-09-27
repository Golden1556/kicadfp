# Токены формата footprint (`.kicad_mod`): что принимает парсер KiCad и что встречается в реальных файлах

Статус: спецификация для реализации `kicadfp.sexpr` / `kicadfp.model` / `kicadfp.io`. Смежные документы:
`architecture.md` (контракт API), `format-writer.md` (порядок и условия записи токенов writer'ом),
`format-layout.md` (пробелы/переводы строк), `layers.md` + `layers.json` (имена слоёв),
`legacy-mod.md` (старый формат `.mod`). Машиночитаемая эмпирика — `token-inventory.json` (этот каталог).

Документ отвечает на два вопроса:

1. **Часть 1.** Какие токены, в каких формах и в каком контексте *принимает* парсер KiCad 9.0
   (со сверкой с 8.0, master = 10-dev и, где это важно для совместимости, с 6.0/7.0); что он делает
   с неизвестными токенами; какие устаревшие формы он всё ещё понимает.
2. **Часть 2.** Что *реально встречается* в стандартных библиотеках KiCad (≈12 200 файлов пяти выпусков)
   и в кураторских фикстурах репозитория — с привязкой конструкций к конкретным файлам для тестов.

Всё, что не подтверждено кодом или скриптом, помечено «не проверено».

---

## 0. Источники и обозначения

### 0.1. Исходники KiCad

Файлы лежат в `scratchpad/kicad-src/<ветка>/` (имя файла = путь в репозитории с `/` → `_`).
В тексте используются сокращения; номер после двоеточия — строка файла.

| Сокр. | Файл (путь в репозитории KiCad) | Ветка |
|---|---|---|
| **P9** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp` | 9.0 |
| **P8** | то же | 8.0 |
| **PM** | то же | master (10-dev, `SEXPR_BOARD_FILE_VERSION` 20260901) |
| **P7** | `pcbnew/plugins/kicad/pcb_parser.cpp` | 7.0 |
| **P6** | то же | 6.0 |
| **H9** / **HM** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.h` (история версий формата) | 9.0 / master |
| **PH9** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.h` | 9.0 |
| **IO9** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp` (загрузка библиотеки) | 9.0 |
| **L9** | `common/dsnlexer.cpp` (лексер) | 9.0 |
| **LH9** | `include/dsnlexer.h` | 9.0 |
| **S9** | `common/stroke_params.cpp` (парсер `stroke`) | 9.0 (идентичен 7.0/8.0/master по набору токенов) |
| **E9** | `common/embedded_files.cpp` (парсер `embedded_files`) | 9.0 |
| **K9** | `common/kiid.cpp` | 9.0 |
| **ID9** | `common/lib_id.cpp` | 9.0 |
| **X9** | `common/exceptions.cpp` | 9.0 |
| **Z9** | `pcbnew/zones.h` | 9.0 |

Начальные строки функций (для навигации): P9 `parseFOOTPRINT_unchecked` 4417, `parsePAD` 5015,
`parsePCB_SHAPE` 2828, `parsePCB_TEXT` 3357, `parsePCB_TEXT_effects` 3438, `parseEDA_TEXT` 505,
`parse3DModel` 703, `parsePAD_option` 5579, `parsePadstack` 5652, `parseGROUP` 6019,
`parseTEARDROP_PARAMETERS` 437, `parseOutlinePoints` 316, `parseTenting` 6585, `parseZONE` 6703.
P8: `parseFOOTPRINT_unchecked` 3936, `parsePAD` 4438, `parsePCB_SHAPE` 2654, `parsePCB_TEXT_effects` 3220,
`parseEDA_TEXT` 485, `parse3DModel` 685. PM: `parseFOOTPRINT_unchecked` 6062, `parsePAD` 7105,
`parsePCB_SHAPE` 3790, `parsePCB_TEXT_effects` 4495, `parseEDA_TEXT` 770, `parse3DModel` 949.
P7: `parseFOOTPRINT_unchecked` 3575, `parseFP_TEXT` 3964, `parseFP_SHAPE` 4197, `parsePAD` 4562,
`parseEDA_TEXT` 385. P6: `parseFOOTPRINT_unchecked` 3223, `parseFP_TEXT` 3546, `parseFP_SHAPE` 3655,
`parsePAD` 4007, `parseEDA_TEXT` 403.

Сравнение наборов `case T_*` по функциям всех пяти версий делает скрипт
`scratchpad/research/parser_funcs.py` (вывод цитируется в §3 и §13).

### 0.2. Обозначения форм аргументов

| Обозн. | Что лексер должен выдать | Пример |
|---|---|---|
| `N` | число (`DSN_NUMBER`, §1.2); без кавычек | `1.27`, `-0.5`, `90` |
| `I` | целое `N` (читается `strtol`) | `2` |
| `S` | «символ или строка»: строка в кавычках **или** символ без кавычек, **но не число** (`NeedSYMBOL`, L9:409) | `"F.SilkS"`, `F.SilkS` |
| `SN` | строка, символ **или** число (`NeedSYMBOLorNUMBER`, L9:420) | `"1"`, `1`, `A1` |
| `Q` | только строка в кавычках (`T_STRING`/`DSN_STRING`) | `""` в `(group "" ...)` |
| `K` | ключевое слово **без кавычек** (сравнение по id токена; строка в кавычках — всегда `DSN_STRING`, не ключевое слово, §1.3) | `smd`, `yes`, `solid` |
| `B` | `K` из `yes`/`no` (`parseBool`, P9:223) | `(embedded_fonts no)` |
| `MB` | «может отсутствовать» bool (`parseMaybeAbsentBool`, P9:241): голый токен = значение по умолчанию; `(tok)` = по умолчанию; `(tok yes|no|true|false)` | `hide`, `(hide yes)` |
| `T` | «любой токен»: берётся текст текущего токена (`CurStr`/`curText`) | uuid, имя слоя |
| `(…)` | подузел | |

«Обязательно» в таблицах означает: без него парсер бросает ошибку. «Позиционно» — токен проверяется
на фиксированном месте (не в цикле по дочерним узлам), порядок важен.

---

## 1. Лексика (DSNLEXER, общий для всех версий)

### 1.1. Разделители, скобки, комментарии

* Пробельные символы: `' '`, `\t`, `\n`, `\r`, `\0` (L9:452–470). Разделители символов: пробельные, `(`, `)`
  и — только если включено `m_knowsBar` — `|` (L9:480–483).
* `m_knowsBar` включается для файлов с `version >= 20240706` (P9:4477 — при чтении `(version)` footprint'а,
  P9:1423 — для платы). В таком файле **голый** символ, содержащий `|`, разрезается на несколько токенов
  (и парсер почти наверняка упадёт). Writer обязан заключать в кавычки любую строку с `|` (для записи
  в формат ≥ 20240706; см. `format-writer.md`). Внутри `embedded_files` `|` включается принудительно (E9:332).
* **Комментарий** — строка, у которой *первый непробельный символ* `#` (L9:575–598). `#` в середине строки
  комментарием не является (это часть символа). Комментарии в начале файла (до `(footprint`) читаются
  `ReadCommentLines()` (L9:836) и сохраняются в footprint как «initial comments» (P9:845, 4430);
  комментарии в других местах молча пропускаются. В реальных библиотеках файлов с комментариями — **0**
  (§14, `files_with_leading_comments`).
* Чтение построчное: строка в кавычках **не может** содержать сырой перевод строки — лексер дойдёт до конца
  физической строки и бросит `Un-terminated delimited string` (L9:640–732). Переводы строк внутри значений
  пишутся только как `\n`.

### 1.2. Числа

`isNumber()` (L9:495–541): `[-+]? цифры* ( . цифры* )? ( [eE] [-+]? цифры+ )?`, причём хотя бы одна цифра
в мантиссе и весь токен целиком. Значит, числами считаются `5.`, `.5`, `+5`, `-0`, `1e3` и **`5E888720`**.

* Значение читается `std::from_chars` (L9:858–915; на старых компиляторах — `strtod`). `from_chars`
  **не принимает ведущий `+`** → токен `+5` лексер считает числом, но `parseDouble` бросает
  `Invalid floating point number`. Никогда не писать `+`.
* Целые (`parseInt`, PH9:354–363) читаются `strtol(…,10)` — дробная часть отбрасывается молча.
* Все размеры переводятся в нм: `KiROUND(clamp(x * 1e6, ±(INT_MAX-10)))` (P9:195–220).
* Числа в кавычках (`"1.27"`) — это `DSN_STRING`, а не число: там, где ожидается `N`, будет ошибка
  `Expecting '<описание>'` (`NeedNUMBER`).
* **Ловушка `tedit`:** значение `(tedit 5E888720)` — «число» с точки зрения лексера; KiCad читает его
  `strtol(…,16)` (PH9:365–369) как текст. Наша модель обязана хранить **сырой текст** атомов, иначе
  `5E888720` превратится в `inf` (такой файл есть в v6.0.0/v7.0.0: `Package_SO.pretty/SO-16_3.9x9.9mm_P1.27mm.kicad_mod`).

### 1.3. Строки и символы; ключевые слова

* Строка в `"…"` — всегда `DSN_STRING` (L9:640–719), **никогда не ключевое слово**. Поэтому
  `(pad "1" "smd" rect …)` или `(fill "solid")` — ошибка; ключевые слова (`K`) пишутся только без кавычек.
* Символ без кавычек: если совпадает с ключевым словом из `pcb.keywords` — id ключевого слова, иначе
  `DSN_SYMBOL` (L9:824). `IsSymbol()` истинно для `DSN_SYMBOL`, `DSN_STRING` **и любого ключевого слова**
  (L9:327–333), поэтому там, где ожидается `S`, годится и `smd`, и `"smd"`.
* Экранирование внутри кавычек (L9:650–716): `\"`, `\\`, `\a \b \f \n \r \t \v`, `\xHH` (1–2 hex-цифры),
  `\ooo` (1–3 восьмеричные). Неизвестная последовательность `\q` (не цифра 0–7) остаётся как есть:
  в значение попадает `\`, а `q` читается дальше как обычный символ (ветка `default`, L9:688–705).
  В реальных файлах встречаются только `\"` и `\\` (§14.4).
* Имя символа/строки после лексера — UTF-8 (`FromUTF8`); не-ASCII встречается в `descr` (3 файла v9/master).

### 1.4. Ошибки лексера/парсера и как они всплывают

* `Expecting( T_x )` → текст `Expecting <tok>`; `Expecting( "a, b" )` → `Expecting 'a, b'`;
  `Unexpected(...)` аналогично (L9:342–379). Все бросают `PARSE_ERROR`; сообщение пользователю:
  `"<проблема> in '<файл>', line <N>, offset <M>."` (X9:71–98).
* Если разбор упал **и** `version` файла больше поддерживаемой, `PARSE_ERROR` заменяется на
  `FUTURE_FORMAT_ERROR` («created with a more recent version…», X9:101–123; P9:4401–4414, IO9:345–351).
* С 8.0 при чтении `(generator_version …)` сразу вызывается `checkVersion()` (P9:4451–4459, 4489–4499;
  P8 аналогично; в P7 нет): если `version > SEXPR_BOARD_FILE_VERSION`, файл отвергается **даже если он
  разобрался бы**. Без `generator_version` слишком новый файл отвергается только при первой ошибке разбора.
* Библиотека (`FP_CACHE::Load`, IO9:149–209): каждый `.kicad_mod` разбирается отдельно; упавший файл
  **не загружается**, его ошибка копится в общее сообщение `Unable to read file '<путь>'` + текст ошибки,
  остальные footprint'ы библиотеки загружаются, затем бросается общее `IO_ERROR`. Имя footprint'а
  берётся **из имени файла** (IO9:185–190), а не из `(footprint "имя")`.

---

## 2. Поведение с неизвестными токенами (критично для «без потерь»)

**Вывод: KiCad не сохраняет и в подавляющем большинстве мест не прощает неизвестные токены.**
Почти каждый цикл разбора заканчивается веткой `default: Expecting( "<список>" )`, т.е. неизвестный узел
= `PARSE_ERROR` = footprint не загружается (библиотека — см. §1.4).

| Контекст | Неизвестный токен | Ссылка |
|---|---|---|
| верхний уровень файла (не `footprint`/`module`/`kicad_pcb`) | ошибка `Unknown token '<x>'` | P9:856–876 |
| дочерний узел `footprint` (список или голый символ, кроме `locked`/`placed`) | ошибка `Expecting 'at, descr, locked, placed, tedit, …'` | P9:4968–4974; P8, PM:6994–7000, P7, P6 — так же |
| `pad` | ошибка `Expecting 'at, locked, drill, …'` | P9:5518–5523 |
| `fp_line`/`fp_rect`/`fp_circle`/`fp_arc`/`fp_poly`/`fp_curve` | ошибка `Expecting 'layer, width, fill, …'` | P9:3218–3220 |
| `fp_text`/`property` | ошибка `Expecting 'layer, hide, effects, locked, render_cache or tstamp'` | P9:3547–3551 |
| `effects`, `font`, `justify` | ошибка | P9:586, 621, 638 |
| `model` | ошибка `Expecting 'at, hide, opacity, offset, scale, or rotate'` | P9:805 |
| `stroke` | ошибка `Expecting 'width, type, or color'` | S9:353–355 |
| `drill`, `chamfer`, `attr`, `fill`, `teardrops`, `group` | ошибка | P9:5192, 5379, 4814, 3192, 498, 6069 |
| значение в `pad (property …)` | **молча игнорируется** (ветка `#if 0`) — 6.0…master | P9:5406–5413; PM:7643–7648 |
| подузел `pad (options (<x> …))` | **молча пропускается** до `)` — 6.0…9.0; в master — ошибка `Expecting 'anchor or clearance'` | P9:5637–5644; PM:7885–7887 |
| `(options (anchor <x>))` / `(options (clearance <x>))` с неизвестным значением | молча игнорируется в ≤9.0; ошибка в master | P9:5607–5611, 5629–5633; PM:7860, 7878 |
| подузел слоя в `pad (padstack (layer …))` | «не строгий разбор»: `continue` (9.0) — поведение с вложенными скобками не проверено | P9:5987–5989; PM:8183–8184 |
| `units`/`unit` (только master) | пропуск `skipCurrent()` | PM:6410–6425 |
| `embedded_files` с ошибкой | ошибка логируется (9.0 `wxLogError`, master — предупреждение), разбор продолжается | P9:4925–4940; PM:6933–6958 |
| **имя слоя** в `(layer X)`/`(layers X …)` | **не ошибка**: неизвестное имя → слой `Rescue` (для `layer` ещё и запоминается в `m_undefinedLayers`, который используется только при разборе платы, P9:1138–1230) | P9:2095–2150 |
| имя слоя в `(private_layers …)` | ошибка `Expecting 'layer name'` | P9:4689–4701 |
| имя слоя в `(zone_layer_connections …)` | не-медный слой (в т.ч. `Rescue`) → ошибка `Expecting 'copper layer name'` | P9:5485–5500 |
| значение `(generator X)` | игнорируется (любой `S`) | P9:4482–4487 |
| `tedit`, `autoplace_cost90/180`, footprint-уровня `thermal_width`/`thermal_gap`, `angle` и `status` в графике | читаются и **отбрасываются** (устаревшие) | P9:4521, 4683, 4765, 3128, 3198 |

### 2.1. Риск для сценария приёмки 3 («неизвестный узел `example_token`»)

Если сценарий требует, чтобы файл с неизвестным узлом, например
`(footprint "X" … (example_token 1 2) …)`, после сохранения Программой **открывался в KiCad**, — это
невыполнимо: KiCad 6.0–10-dev (все проверенные версии) на таком файле выдаёт
`Expecting 'at, descr, locked, placed, tedit, tstamp, uuid, autoplace_cost90, …' in '<файл>', line N, offset M.`
и не загружает footprint (§1.4, §2). Это свойство KiCad, а не Программы.

Предлагаемая формулировка критерия:

> «Узлы и атрибуты, неизвестные Программе, сохраняются при чтении и записываются обратно без изменений
> (порядок, значения, кавычки). Проверка: файл-фикстура с синтетическим узлом `(example_token 1 "a")` на
> уровне footprint и внутри `pad` проходит цикл load → save байт-в-байт (для файлов KiCad 8+) / с
> сохранением дерева (для 6/7). Совместимость с KiCad проверяется на файлах, **не содержащих** синтетических
> узлов; для демонстрации «неизвестного, но принимаемого KiCad» использовать `(property pad_prop_future)`
> внутри `pad` (значение молча игнорируется KiCad 6.0…master) или узел из более новой версии формата
> при чтении/записи файла этой же версии.»

Дополнительно Программе полезно предупреждать (в `validate`), что файл содержит узлы, которых нет в
таблицах §5–§12 для целевой версии, — такой файл KiCad этой версии не откроет.

---

## 3. Версии формата

### 3.1. Даты, важные для footprint'ов

Полная история — H9:67–175, HM:180–222. Максимальная версия, которую пишет/понимает выпуск:

| Выпуск KiCad | `SEXPR_BOARD_FILE_VERSION` | Источник |
|---|---|---|
| 6.0 | 20211014 | `pcbnew/plugins/kicad/pcb_plugin.h`@6.0:105 |
| 7.0 | 20221018 | `pcbnew/plugins/kicad/pcb_plugin.h`@7.0:136 |
| 8.0 | 20240108 | `pcb_io_kicad_sexpr.h`@8.0:152 |
| 9.0 | 20241229 | H9:175 |
| master (10-dev), на момент скачивания | 20260901 | HM:222 (стандартная библиотека master записана как 20260206) |

Ключевые изменения синтаксиса footprint'ов (из комментариев H9/HM, проверено по коду парсера):

| Версия | Изменение | Влияние на парсер (9.0) |
|---|---|---|
| (нет `version`) | формат KiCad 5, корень `module` | `m_requiredVersion = 0` (P9:99) — все ветки «legacy» активны |
| 20171130 | 3D offset: `(offset (xyz))` в мм вместо `(at (xyz))` в дюймах | `at` в `model` читается ×25.4 (P9:721–740) |
| 20200614 | `fp_rect` | — |
| 20200826 (в коде) | `attr` с новыми флагами; отсутствие `attr` раньше = through_hole | P9:4985–4986 |
| 20201115 | `module` → `footprint`; синтаксис `fill` | — |
| 20201116 | `version` и `generator` пишутся в footprint | — |
| 20210108 | `locked` у pad | принимается и игнорируется (P9:5103–5107, 5506–5509) |
| 20210424 | `locked` без скобок | голые `locked` принимаются (§5, §7, §9) |
| 20210606 | надчёркивание `~...~` → `~{...}` | для `version < 20210606` тексты конвертируются (P9:519–520) |
| 20210623 | `(arc …)` внутри `pts` | P9:335–393 |
| 20210925 = `LEGACY_ARC_FORMATTING` | последняя версия со старой формой дуги | `fp_arc` при `version <= 20210925` читается как `(start центр)(end начало)(angle a)` (P9:2860–2889) |
| 20211014 | дуга `(start)(mid)(end)` | P9:2891–2918 |
| 20211227 | `thermal_bridge_angle` у pad | — |
| 20211229 | `(stroke …)` вместо `(width)` | `width` остаётся как устаревший (P9:3147) |
| 20211231 | `private_layers` | — |
| 20220131 | `fp_text_box` | — |
| 20220225 | удалён `tedit` | принимается и игнорируется |
| 20220308 | `knockout`, `(locked)` у графического текста | — |
| 20220427 | Edge.Cuts/Margin исключены из `private_layers` | для `version < 20220427` снимаются (P9:4703–4707) |
| 20220815 = `LEGACY_NET_TIES` | net tie через `tags "net tie"` | для `version <= 20220815` строится группа из всех pad (P9:4988–5004) |
| 20220818 | `net_tie_pad_groups` | — |
| 20230620 | PCB fields: `(property "Reference" …)` с эффектами | для `version < 20230620` см. §6.2 |
| 20231014 | нормализация 8.0 (`(hide yes)`, `uuid`, bool-формы) | — |
| 20240108 | 8.0 финальная; teardrop bool | — |
| 20240201 | nullable overrides | для `version <= 20240201` значение `0` у `clearance`/`solder_*_margin*` = «наследовать» (P9:4724…4757, 5270…5302) |
| 20240609 | `tenting` | — |
| 20240706 | embedded files; `|` — разделитель | P9:4477 |
| 20240929 | `padstack` | — |
| 20241010 | `layers`/`solder_mask_margin` у графики | — |
| 20241229 | 9.0 финальная | — |
| 20250324 | jumper pads (`duplicate_pad_numbers_are_jumpers`, `jumper_pad_groups`) | только PM |
| 20250901 | `(point …)` | только PM |
| 20250909 | `units` в footprint | только PM |
| 20251028 | net без номера | только PM (§9.4) |
| 20260616 = `FIRST_FP_AFFINE_TRANSFORM` | `(transform …)` в footprint | только PM |

**Важно для writer'а:** `version` действует с момента прочтения (P9:4468–4480), поэтому `(version …)` должна
идти раньше любой графики/текста (иначе `fp_arc` до неё будет прочитана по «legacy» правилам, а `|` —
не распознан). Реальные файлы всегда пишут её вторым токеном.

### 3.2. Фактические версии в библиотеках

| Набор | Файлов | `version` | `generator` | `generator_version` |
|---|---|---|---|---|
| v6.0.0 | 1303 | нет — 1300; `20210722` — 3 | нет — 1300; `pcbnew` (без кавычек) — 3 | — |
| v7.0.0 | 1332 | `20211014` — 1306; нет — 26 | `pcbnew` — 1306 | — |
| v8.0.0 | 1377 | `20240108` — 1377 | `"pcbnew"` — 1377 | `"8.0"` — 1377 |
| v9.0.0 | 3297 | `20241229` — 1860; `20240108` — 1437 | `"pcbnew"` — 1860; `"kicad-footprint-generator"` — 1437 | `"9.0"` — 1860 |
| master | 4882 | `20260206` — 4882 | `"kicad-footprint-generator"` — 4239; `"pcbnew"` — 643 | `"10.0"` — 643 (по `token-inventory.json`) |

(`token-inventory.json` → `libraries.<набор>.versions / generators / generator_versions`.)

---

## 4. Корень файла

`Parse()` (P9:834–890):

1. Читает начальные комментарии (§1.1).
2. Ожидает `(`; иначе `Expecting (`. Пустой файл → `Unexpected EOF`.
3. Первый токен: `module` (устаревший) или `footprint` → `parseFOOTPRINT`; `kicad_pcb` → плата; иное →
   `Unknown token`. После разбора footprint'у принудительно `SetLocked(false)` (P9:869) — «locked» вне
   платы не имеет смысла.
4. Что идёт после закрывающей `)` корня, парсер footprint'а не проверяет — **не проверено**, игнорируется
   ли хвост (код `FP_CACHE::Load` не читает дальше, IO9:181–191).

Имя footprint'а (P9:4437–4449): следующий токен `S` или `N` (`symbol|number`), иначе ошибка.
Проверка `LIB_ID::Parse(name, aFix=true)`: недопустимые символы имени **исправляются** на `_`
(ID9:191–205); ошибка `Invalid footprint ID` возможна только если в имени есть `:` и часть до него
(nickname) содержит `\` или управляющие символы (ID9:51–89, 244–266). В библиотеке имя всё равно
заменяется именем файла (§1.4). В v6.0.0 имена — символы без кавычек (1299 файлов), с 7.0 — строки.

---

## 5. `footprint` (`module`) — дочерние узлы

Цикл P9:4461–4975: перед `switch` открывающая `(` просто пропускается (`if( token == T_LEFT ) token = NextTok()`),
поэтому **голые** символы на этом уровне попадают в тот же `switch`: работают только `locked` и `placed`
(`MB`), любой другой голый символ — ошибка. Порядок дочерних узлов для парсера **не важен**
(кроме `version`, §3.1), повторы допустимы (последний выигрывает, для `pad`/графики — добавляются).

| Токен | Форма | Появился | Примечание / устаревшие формы | Ссылка P9 |
|---|---|---|---|---|
| `version` | `(version I)` | 20201116 | `I` без кавычек (`NeedNUMBER`); берётся max с текущим | 4468 |
| `generator` | `(generator S)` | 20201116 | значение игнорируется; 6/7 писали без кавычек, 8+ в кавычках | 4482 |
| `generator_version` | `(generator_version S)` | 8.0 | `S` — **не число**: `"9.0"` в кавычках обязательно (`9.0` без кавычек = `N` → ошибка `Expecting symbol`); запускает `checkVersion` | 4489 |
| `locked` | `locked` \| `(locked)` \| `(locked yes/no)` | — | `MB`; итог сбрасывается в false (§4). 6/7 писали голый `locked` после `(generator …)` (writer 7.0 `pcbnew/plugins/kicad/pcb_plugin.cpp`:1167) | 4502 |
| `placed` | как `locked` | — | `MB` | 4506 |
| `layer` | `(layer S)` | — | любой слой кроме `B.Cu` превращается в `F.Cu` | 4510 |
| `tedit` | `(tedit T)` | — | устарел (20220225); `strtol(…,16)`, отбрасывается | 4521 |
| `tstamp`, `uuid` | `(uuid T)` | tstamp≤7, uuid 8+ | KIID из текста; 8 hex-цифр = старый timestamp; нераспознанная строка → **случайный** UUID без ошибки (K9:111–160) | 4526 |
| `at` | `(at N N [N])` | — | позиция и угол footprint'а; в библиотеках не пишется | 4533 |
| `descr` | `(descr SN)` | — | | 4551 |
| `tags` | `(tags SN)` | — | | 4557 |
| `property` | `(property S S <дети §6>)` | 20200808 (без детей), 20230620 (с детьми) | имя и значение — `S`: **число без кавычек недопустимо** (`NeedSYMBOL`) | 4563–4663, §6.2 |
| `path` | `(path SN)` | — | только в платах | 4665 |
| `sheetname`, `sheetfile` | `(sheetname S)` | 8.0 | | 4671, 4677 |
| `autoplace_cost90`, `autoplace_cost180` | `(… I)` | — | устарели; отбрасываются | 4683 |
| `private_layers` | `(private_layers S…)` | 7.0 | имена должны быть известны, иначе ошибка | 4689 |
| `net_tie_pad_groups` | `(net_tie_pad_groups T…)` | 7.0 (20220818) | каждая группа — строка `"1, 2"` | 4713 |
| `solder_mask_margin` | `(… N)` | — | | 4719 |
| `solder_paste_margin` | `(… N)` | — | | 4729 |
| `solder_paste_margin_ratio` | `(… N)` | **9.0** | P6/P7/P8 знают на уровне footprint только `solder_paste_ratio` | 4740 |
| `solder_paste_ratio` | `(… N)` | — | устаревшее имя того же; пишется 6/7/8 (writer 8.0 `pcb_io_kicad_sexpr.cpp`:1217), читается и 9/master | 4739 |
| `clearance` | `(clearance N)` | — | | 4750 |
| `zone_connect` | `(zone_connect I)` | — | `-1` наследовать, `0` нет, `1` термо, `2` сплошное, `3` термо только THT (Z9:46–53) | 4760 |
| `thermal_width`, `thermal_gap` | `(… N)` | — | на уровне footprint отбрасываются | 4765 |
| `attr` | `(attr K…)` | — | см. ниже; пустой `(attr)` допустим | 4772–4819 |
| `fp_text` | §6.1 | — | | 4821 |
| `fp_text_box` | §12.3 | 7.0 | | 4852 |
| `table` | §12.3 | 9.0 | | 4859 |
| `fp_line` `fp_rect` `fp_circle` `fp_arc` `fp_poly` `fp_curve` | §7 | — | | 4866–4876 |
| `image` | §12.3 | 7.0 | | 4878 |
| `dimension` | §12.3 | 7.0 | | 4885 |
| `pad` | §9 | — | | 4892 |
| `model` | §10 | — | может повторяться | 4899 |
| `zone` | §12.2 | — | | 4907 |
| `group` | §12.1 | 20201002 | | 4914 |
| `embedded_fonts` | `(embedded_fonts B)` | 9.0 | | 4918 |
| `embedded_files` | §12.4 | 9.0 | | 4925 |
| `component_classes` | `(component_classes (class SN)…)` | 9.0 | | 4943 |

`attr` (P9:4772–4819): `through_hole`, `smd`, `board_only`, `exclude_from_pos_files`, `exclude_from_bom`,
`allow_missing_courtyard` (7.0+), `dnp` (8.0+), `allow_soldermask_bridges` (7.0+), устаревший `virtual`
(= exclude_from_pos_files + exclude_from_bom). Порядок флагов произвольный. Если файл `version < 20200826`
и флагов нет (в т.ч. нет самого `attr`) — footprint считается `through_hole` (P9:4985–4986);
в v6.0.0 нет `attr` у 767 из 1303 файлов.

### 5.1. Только master (10-dev), отвергаются 9.0

PM:6109–7000. Добавлены: `stackup` (`(stackup (layer S)…)`, чётное непрерывное число медных слоёв,
PM:7041–7102), `transform` (`(transform (translate N N) (rotate N) (scale N N))`, PM:6194–6243),
`units` (`(units (unit (name SN) (pins Q|N …))…)`, PM:6370–6430), `duplicate_pad_numbers_are_jumpers`
(`B`, PM:6468), `jumper_pad_groups` (`((Q Q…)…)`, PM:6473–6511), `attr exclude_from_sim` (PM:6595),
`fp_ellipse`, `fp_ellipse_arc` (PM:6675–6676), `barcode` (PM:6690), `model (type extruded)`
(PM:6711–6881), `constraint` (PM:6915), `point` (PM:6919, `parsePCB_POINT` PM:10196),
`variant` (PM:6986), `custom_property` (`(custom_property S S)`, PM:6990, 511–519).
В master `allow_missing_courtyard`/`allow_soldermask_bridges` стали отдельными свойствами, но синтаксис
тот же. Проверено скриптом (§14.3): **все** 4882 файла библиотеки master содержат
`duplicate_pad_numbers_are_jumpers`, 369 узлов `point` в 326 файлах → KiCad 9 их не откроет даже без
учёта `checkVersion`.

---

## 6. Тексты: `fp_text`, `property`, `effects`

### 6.1. `fp_text`

`(fp_text <тип> [locked] <текст> <дети>)`, тип — `K` из `reference` | `value` | `user` (иначе
`THROW_IO_ERROR "Cannot handle footprint text type"`, P9:3374–3392). Устаревший голый `locked` — сразу
после типа (P9:3400–3405; writer 7.0 писал `(fp_text reference locked "R1" (at …))`). Текст — `S` или `N`
(P9:3407–3408); `%V` → `${VALUE}`, `%R` → `${REFERENCE}` (P9:3411–3412; `%R` встречается в v6.0.0 в 1296
файлах). В 8.0+ `fp_text reference/value` по-прежнему читаются (становятся полями Reference/Value,
P9:4821–4849), но пишутся как `property`.

Дочерние элементы (общий `parsePCB_TEXT_effects`, P9:3438–3576; порядок произвольный, `(` перед
токеном необязательна — голые `hide`/`unlocked` тоже ловятся):

| Токен | Форма | Примечание | Ссылка |
|---|---|---|---|
| `at` | `(at N N [N] [unlocked])` | угол — абсолютный (на экране); голый `unlocked` внутри `at` = устаревшее «не держать вертикально» (6/7) | 3456–3484 |
| `layer` | `(layer S [knockout])` | `knockout` — голый `K` после имени слоя (7.0+). **Другие** голые токены после имени слоя (в т.ч. `locked`) → ошибка `Expecting )` | 3486–3500 |
| `tstamp`, `uuid` | `(uuid T)` | | 3502–3507 |
| `hide` | `hide` \| `(hide)` \| `(hide yes/no/true/false)` | `MB`; только в footprint | 3509–3521 |
| `locked` | `(locked B)` | в списке — строго `yes`/`no` (`(locked)` → ошибка) | 3523–3527 |
| `unlocked` | `(unlocked B)` | 8.0+; в footprint | 3530–3537 |
| `effects` | §6.3 | | 3539 |
| `render_cache` | `(render_cache SN N (polygon (pts …)…)…)` | 7.0+; кэш глифов | 3543, 653–700 |

Нет `at` — позиция = позиция footprint'а (P9:3569–3574). Скрытый `fp_text user` в 9.0 превращается при
чтении в **скрытое поле** с автоименем (P9:3421–3426) — при пересохранении KiCad это уже `property`.

**6/7 строже** (P7:3964–4084): после текста обязательно `(at …)` сразу (`Expecting at`), затем
`unlocked` голым внутри `at`; в цикле только `layer`, голый `hide` (без аргумента! `(hide yes)` → ошибка
на `yes`), `effects`, `render_cache`, `tstamp` (без `uuid`).

### 6.2. `property` (уровень footprint)

`(property S S <дети как у fp_text>)` (P9:4563–4663). Особенности:

* Имя/значение — `S` (**не число**; `(property "Value" 100)` → ошибка).
* Для `version < 20230620` (P9:4574–4607): `ki_keywords`, `ki_locked` пропускаются;
  `ki_description` → поле Description; `Sheetfile`/`Sheet file`, `Sheetname`/`Sheet name` → свойства
  footprint'а. Такие свойства и все прочие получают `visible=false` (P9:4656–4659). Для `>= 20230620`
  поле по умолчанию видимое, скрывается только `(hide yes)`.
* `ki_fp_filters` (любая версия) — фильтры; дочерние элементы разбираются и отбрасываются (P9:4611–4625).
* `Footprint` (писался только 8.0) — разбирается во временное поле и **выбрасывается** (P9:4629–4636).
* Новое имя → новое поле на слое `F.Fab`/`B.Fab` (P9:4643–4652).
* 6/7: `parseProperty` = строго `(property S S)` без детей (P7:370–382, 3693) — файл 8.0+ им не читается.

Имена свойств в библиотеках (`token-inventory.json` → `property_names`): v8 — `Reference`, `Value`,
`Footprint`, `Datasheet`, `Description` (по 1377); v9 — `Reference`, `Value` (3297), `Datasheet`,
`Description` (1860); master — `Reference`, `Value` (4882), `KiLib_Generator` (4239), `Datasheet`,
`Description` (643). Свойства без дочерних элементов в библиотеках 8+ не встречаются.

### 6.3. `effects`, `font`, `justify`

`parseEDA_TEXT` (P9:505–650). Перед разбором: выравнивание center/center, mirror=false. Порядок
элементов произвольный; `(`-обёртка необязательна (голые `hide`, `bold`, `italic` допустимы).

| Токен | Форма | Примечание | Ссылка |
|---|---|---|---|
| `font` | `(font <дети>)` | | 535 |
| `font/face` | `(face S)` | 7.0+ | 543 |
| `font/size` | `(size N N)` | **первое число — высота, второе — ширина** | 549–559 |
| `font/line_spacing` | `(line_spacing N)` | 7.0+ | 561 |
| `font/thickness` | `(thickness N)` | | 566 |
| `font/bold`, `font/italic` | `bold` \| `(bold)` \| `(bold yes/no/true/false)` | `MB`; 6/7 — **только голые** (`(bold yes)` → ошибка на `yes`, P7:449–455) | 571–584 |
| `justify` | `(justify K…)`: `left` `right` `top` `bottom` `mirror` | любое сочетание | 592–624 |
| `hide` | `MB` | 6/7 — только голый (P7:506) | 628–634 |

Если `size` не задан — 1.524 мм (P9:643–648). Проверено: в библиотеках `face`, `line_spacing`, `bold`,
`italic`, `mirror`, `render_cache`, `knockout` не встречаются; `justify` — 1 раз (master,
`(justify left bottom)`).

---

## 7. Графика footprint'а: `fp_line`, `fp_rect`, `fp_circle`, `fp_arc`, `fp_poly`, `fp_curve`

`parsePCB_SHAPE` (P9:2828–3256). Структура: `(<тип> [locked] <геометрия позиционно> <атрибуты в любом порядке>)`.
Голый `locked` допустим **только сразу после имени** (P9:2847–2851 и аналоги); после геометрии каждый
элемент обязан начинаться с `(` (P9:3121–3122).

### 7.1. Геометрия (позиционно, строго в этом порядке)

| Тип | Геометрия | Ссылка |
|---|---|---|
| `fp_line` | `(start N N) (end N N)` | 3039–3073 |
| `fp_rect` | `(start N N) (end N N)` (в footprint без нормализации) | 2992–3037 |
| `fp_circle` | `(center N N) (end N N)` — `end` = точка на окружности | 2924–2958 |
| `fp_arc`, `version > 20210925` | `(start N N) (mid N N) (end N N)` | 2891–2918 |
| `fp_arc`, `version <= 20210925` (в т.ч. без version) | `(start Cx Cy) (end Sx Sy) (angle A)` — `start`=центр, `end`=начало, угол в градусах | 2860–2889 |
| `fp_poly` | `(pts <точки §8>)` | 3075–3102 |
| `fp_curve` | `(pts (xy)(xy)(xy)(xy))` — ровно 4 точки: начало, C1, C2, конец | 2960–2990 |

Внимание: форма дуги выбирается **по версии файла**, а не по наличию `mid`. Файл с `(version 20211014)`
и дугой `(start)(end)(angle)` → ошибка `Expecting mid`; файл без версии с `(mid)` → ошибка `Expecting angle`.

### 7.2. Атрибуты (P9:3120–3221)

| Токен | Форма | Появился | Примечание |
|---|---|---|---|
| `layer` | `(layer S)` | — | неизвестное имя → `Rescue` |
| `layers` | `(layers S…)` | 9.0 (20241010) | |
| `solder_mask_margin` | `(… N)` | 9.0 | |
| `width` | `(width N)` | — | устарел с 20211229 (7.0 писал `stroke`), = ширина линии |
| `stroke` | §7.3 | 7.0 | |
| `tstamp`, `uuid` | `(uuid T)` | uuid — 8.0 | |
| `fill` | `(fill K)` | 20201115 | см. §7.4 |
| `status` | `(status T)` | — | устарел, hex, отбрасывается |
| `locked` | `locked` (только после имени) \| `(locked)` \| `(locked yes/no)` | — | `MB` в списке; 7.0 — только `(locked)` без аргумента (P7:4523–4526) |
| `net` | `(net I)` | 8.0 | номер сети; в библиотеках нет |
| `angle` | `(angle N)` | — | в цикле атрибутов — устаревший, **игнорируется** |

После разбора (P9:3224–3246): если `fill` не было — `fp_rect`/`fp_circle` с шириной 0 считаются залитыми,
`fp_poly` не на `Edge.Cuts` — залитым; незалитая фигура с шириной ≤ 0 получает ширину по умолчанию
(`DEFAULT_LINE_WIDTH`). Для точного round-trip эти умолчания **не применять** к модели, а хранить исходные
токены (иначе поменяется смысл при записи в 8+).

### 7.3. `stroke`

`(stroke (width N) (type K) [(color I I I N)])`, элементы в любом порядке (S9:303–357). `type`:
`solid`, `dash`, `dot`, `dash_dot`, `dash_dot_dot`, `default`. Одинаково в 7.0/8.0/9.0/master.
В библиотеках: `solid` (подавляющее большинство), `default` (1/28/46 файлов в v8/v9/master).

### 7.4. `fill` — формы по версиям

| Значение | Смысл | P6/P7 | P8 | P9 | PM | Реально пишут |
|---|---|---|---|---|---|---|
| `yes` | залито | да | да | да | да | 9.0+ (с 20241129), примитивы pad всех версий |
| `solid` | залито | да | да | да | да | 7.0–8.0 |
| `none` | не залито | да | да | да | да | 7.0–8.0 |
| `no` | не залито | **нет** (P7:4510 `Expecting 'yes, none, solid'`) | да | да | да | 9.0+ |
| `hatch`, `reverse_hatch`, `cross_hatch` | штриховка | нет | нет | нет | да (PM:4169–4171) | — |

Внутри `(fill …)` цикл до `)` — несколько значений подряд допустимы (последнее выигрывает); пустой
`(fill)` = «fill найден, не залито». v9.0.0 содержит смесь: `none` 403 файла, `no` 473, `solid` 925, `yes` 393.

---

## 8. Точки: `pts`, `xy`, `arc`

`parseOutlinePoints` (P9:316–398): каждый элемент `pts` — либо `(xy N N)`, либо
`(arc (start N N) (mid N N) (end N N))` (20210623+). Внутри `arc` порядок `start/mid/end` произвольный,
все три обязательны (`Expecting 'start'` и т.д.). Иное → `Expecting 'xy or arc'`. `fp_curve` использует
строгий `parseXY` — только `xy` (P9:296–313). В библиотеках `arc` внутри `pts` не встречается ни разу.

---

## 9. `pad`

### 9.1. Заголовок (позиционно)

`(pad <номер SN> <тип K> <форма K> [locked] <дети>)` (P9:5015–5098).

| Позиция | Значения | Примечание |
|---|---|---|
| номер | `SN` | пустая строка `""` допустима (NPTH, paste-apertures); с 7.0 пишется в кавычках, в v6.0.0 — голые числа |
| тип | `thru_hole` \| `smd` \| `connect` \| `np_thru_hole` | иначе `Expecting 'thru_hole, smd, connect, or np_thru_hole'` |
| форма | `circle` \| `rect` \| `oval` \| `trapezoid` \| `roundrect` \| `custom` | `roundrect` + chamfer → chamfered rect (формы `chamfered_rect` в файле нет) |

Голый `locked` допускается **между любыми дочерними списками** (проверка в начале каждой итерации,
P9:5103–5110) и игнорируется (блокировка pad — настройка сеанса). Writer 7.0 ставил его сразу после формы.

### 9.2. Дочерние элементы `pad` (P9:5101–5524)

| Токен | Форма | Появился | Примечание |
|---|---|---|---|
| `size` | `(size N N)` | — | ширина, высота; ≤0 → 1 мкм + предупреждение (P9:5565–5573) |
| `at` | `(at N N [N])` | — | угол — абсолютный; иной токен → `Expecting ') or angle value'` |
| `rect_delta` | `(rect_delta N N)` | — | трапеция |
| `drill` | §9.3 | — | |
| `layers` | `(layers S…)` | — | §11; пустой список допустим |
| `net` | `(net I SN)` | — | **имя обязательно** в ≤9.0 (`NeedSYMBOLorNUMBER`, P9:5225); в master `(net [I] S)` (PM:7397–7459). В библиотеках не встречается (CTL_OMIT_PAD_NETS, H9:191) |
| `pinfunction`, `pintype` | `(… SN)` | 20191123 / 20210126 | |
| `die_length` | `(die_length N)` | — | в master ещё `die_delay` |
| `solder_mask_margin` | `(… N)` | — | для `version <= 20240201` `0` = наследовать |
| `solder_paste_margin` | `(… N)` | — | то же |
| `solder_paste_margin_ratio` | `(… N)` | — | то же. **`solder_paste_ratio` у pad не принимается** ни в одной версии |
| `clearance` | `(clearance N)` | — | то же |
| `teardrops` | §9.6 | 8.0 | |
| `zone_connect` | `(zone_connect I)` | — | значения как у footprint (§5) |
| `thermal_width` | `(… N)` | — | устаревшее имя `thermal_bridge_width` |
| `thermal_bridge_width` | `(… N)` | 7.0 | |
| `thermal_bridge_angle` | `(… N)` | 7.0 (20211227) | градусы; без него: 45° для круглых, 90° для прочих (для custom с круглым якорем и `version <= 20211014` — 90°), P9:5533–5556 |
| `thermal_gap` | `(… N)` | — | |
| `roundrect_rratio` | `(… N)` | — | |
| `chamfer_ratio` | `(… N)` | — | `> 0` → форма chamfered rect |
| `chamfer` | `(chamfer K…)`: `top_left` `top_right` `bottom_left` `bottom_right` | 20190331 | пустой `(chamfer)` допустим; текст ошибки ошибочно говорит `chamfer_top_left…` |
| `property` | `(property K…)` | 20200104 | §9.5 |
| `options` | §9.7 | — | |
| `padstack` | §9.8 | 9.0 | |
| `primitives` | §9.7 | — | |
| `remove_unused_layers` | `MB` | 20200809 | 7.0 писал `(remove_unused_layers)`, 8+ — `(remove_unused_layers no)` |
| `keep_end_layers` | `MB` | — | |
| `tenting` | §9.8 | 9.0 | |
| `zone_layer_connections` | `(zone_layer_connections S…)` | 7.0 | только медные слои |
| `locked` | голый \| `(locked)` \| `(locked yes/no)` | — | игнорируется |
| `tstamp`, `uuid` | `(uuid T)` | uuid — 8.0 | |

Постобработка: pad без `net` получает net 0 (P9:5527–5531); у pad, которые не могут иметь номер,
номер **стирается** (P9:5558–5563): `PAD::CanHaveNumber()` = false для апертурных pad и **для всех
`np_thru_hole`** (`pcbnew/pad.cpp`@9.0:281–292). Т.е. `(pad "5" np_thru_hole …)` KiCad прочитает как
pad без номера — Программе номер NPTH хранить сырым, но `validate` может предупреждать.

**Только master:** `backdrill`, `tertiary_drill` (`(… (size N) (layers S S))`), `front_post_machining`,
`back_post_machining` (`(… K (size N) (depth N) (angle N))`, PM:7893–7937), `sim_electrical_type`
(`source`/`sink`), `die_delay`, `custom_property`, значение `pad_prop_pressfit`.

### 9.3. `drill`

Цикл P9:5152–5205 — элементы в любом порядке, `(`-обёртка у чисел необязательна:
`(drill [oval] [W [H]] [(offset X Y)])`.

* `oval` — `K`, овальное отверстие; одно число → `W = H`.
* `offset` — смещение площадки относительно отверстия.
* Пустой `(drill)` и `(drill (offset X Y))` без размера допустимы. У `smd`/`connect` размер отверстия
  принудительно 0, но `offset` сохраняется (реальный пример — SMD pad с `(drill (offset 0 0.266))`,
  `Package_DIP.pretty/Fairchild_LSOP-8.kicad_mod` во всех выпусках).
* У `thru_hole` без `drill` размер = 1 нм (P9:5034–5040).
* Иной элемент → `Expecting 'oval, size, or offset'`.

### 9.4. `net` у pad

≤9.0: `(net I SN)` — номер обязателен и должен быть числом, имя обязательно (при чтении платы сверяется,
несовпадение → сеть «осиротевшая» + сообщение). master: номер необязателен (PM:7397–7459; версия 20251028).
Библиотечные footprint'ы сети не содержат (проверено: 0 pad с `net` во всех пяти библиотеках).

### 9.5. `pad (property …)`

Значения (`K`): `pad_prop_bga`, `pad_prop_fiducial_glob`, `pad_prop_fiducial_loc`, `pad_prop_testpoint`,
`pad_prop_castellated`, `pad_prop_heatsink`, `pad_prop_mechanical` (9.0+), `pad_prop_pressfit` (master),
`none`. Неизвестное значение **молча игнорируется** во всех версиях (§2). Встречаются:
`pad_prop_heatsink` (v8 82 файла … master 797), `pad_prop_bga` (v9 2, master 236), `pad_prop_fiducial_loc`
(master 1).

### 9.6. `teardrops`

`parseTEARDROP_PARAMETERS` (P9:437–502): `enabled` (`MB`), `allow_two_segments` (`MB`),
`prefer_zone_connections` (`MB`), `best_length_ratio N`, `max_length N`, `best_width_ratio N`,
`max_width N`, `curve_points I` (устаревший, 8.0), `curved_edges` (`MB`, 9.0+; **P8 не знает** —
ошибка), `filter_ratio N`. В библиотеках не встречается.

### 9.7. `options` и `primitives` (custom pad)

* `(options (clearance outline|convexhull) (anchor rect|circle))` (P9:5579–5649). Порядок произвольный.
  Неизвестные подузлы/значения игнорируются в ≤9.0, ошибка в master.
* `(primitives <gr_*>…)` (P9:5426–5464): `gr_line`, `gr_arc`, `gr_circle`, `gr_rect`, `gr_poly`,
  `gr_curve`, а также `gr_bbox` (7.0+, рамка номера) и `gr_vector` (8.0+, шаблон спицы). Каждый
  разбирается тем же `parsePCB_SHAPE` (§7, без родителя-footprint'а), т.е. атрибуты `width`/`stroke`/
  `fill`/`layer`/… Реальная форма во всех версиях (writer не перешёл на `stroke`):
  `(gr_poly (pts (xy …)…) (width 0.2) (fill yes))`, `(gr_circle (center …) (end …) (width …) (fill yes))`,
  `(gr_arc (start …) (mid …) (end …) (width …))`. В v6.0.0 (KiCad 5) у `gr_poly` нет `fill`.
  Форма дуги в primitives тоже зависит от версии файла (§7.1).

### 9.8. `padstack` и `tenting` (9.0+)

* `(padstack (mode front_inner_back|custom) (layer "F.Cu"|"Inner"|… <дети>)…)` (P9:5652–6001).
  `"Inner"` допустим только в режиме `front_inner_back`; не-медный слой → `IO_ERROR "Invalid padstack
  layer"`. Дети слоя: `shape`, `size`, `offset`, `rect_delta`, `roundrect_rratio`, `chamfer_ratio`,
  `chamfer`, `thermal_bridge_width`, `thermal_gap`, `thermal_bridge_angle`, `zone_connect`, `clearance`,
  `tenting`, `options`, `primitives`; прочее — `continue` (§2).
* `tenting` в 9.0 (P9:6585–6603): `(tenting K…)`, где `K` ∈ `front`, `back`, `none` (устанавливает
  «есть маска» спереди/сзади). В master (PM:9216–9275) — новая форма `(tenting (front B|none) (back B|none))`
  плюс старая голая. **Новую форму 9.0 не читает** (ошибка `Expecting 'front, back, or none'`).
* В библиотеках `padstack`, `tenting`, `teardrops`, `zone_layer_connections`, `keep_end_layers`,
  `die_length`, `pinfunction`, `pintype`, `rect_delta` не встречаются ни разу.

---

## 10. `model`

`parse3DModel` (P9:703–811): `(model <путь SN> <дети>)`, дети в любом порядке, `(`-обёртка у `hide`
необязательна.

| Токен | Форма | Примечание |
|---|---|---|
| `at` | `(at (xyz N N N))` | **устаревший**: смещение в дюймах, умножается на 25.4 (P9:721–740). Писал KiCad 5 |
| `offset` | `(offset (xyz N N N))` | мм (с 20171130) |
| `scale` | `(scale (xyz N N N))` | |
| `rotate` | `(rotate (xyz N N N))` | градусы |
| `hide` | `MB` | 6/7 — только голый (P7:615) |
| `opacity` | `(opacity N)` | 20210824 |

Внутри `at/offset/scale/rotate` обязателен `(xyz …)` (`Expecting xyz`). Путь в v6.0.0 — символ без
кавычек (`${KICAD6_3DMODEL_DIR}/…wrl`, 1300 файлов), далее — строка. master дополнительно принимает
`(model (type extruded) …)` (§5.1). Если `at` и `offset` оба заданы — выигрывает последний (оба пишут одно поле).

---

## 11. Слои: `layer`, `layers`, подстановки

* Таблица имён строится из `LSET::Name()` для всех `PCB_LAYER_ID` (англ., непереводимые) — P9:104–113;
  полный список по версиям — `layers.json` (`canonical`, `parser_extra_names_9.0`). Имена чувствительны
  к регистру; кавычки не важны (сравнивается текст токена).
* Маски-подстановки только для `layers` (P9:115–123): `*.Cu` (все медные), `*In.Cu` (внутренние),
  `F&B.Cu`, `*.Adhes`, `*.Paste`, `*.Mask`, `*.SilkS`, `*.Fab`, `*.CrtYd`. В `(layer …)` подстановка не
  работает → `Rescue`.
* Старые имена `Inner1.Cu…Inner14.Cu` → `In(15-2i)`… (только в масках `layers`, P9:125–136;
  `layers.json` → `old_inner_names`).
* Неизвестное имя → слой `Rescue` без ошибки (P9:2095–2122). **`"Rescue"` встречается в реальном файле**:
  `kfp/v9.0.0/MountingHole.pretty/MountingHole_6.4mm_M6_DIN965_Pad_TopBottom.kicad_mod`
  (`(layers "B.Mask" "Rescue")`) — модель должна его сохранять.
* Кавычки в реальных файлах: v6.0.0 — всё без кавычек; v7.0.0 — `layer` в кавычках, в `layers` имена
  в кавычках, а подстановки `*.Cu *.Mask` без кавычек (21 441 без / 37 038 в кавычках); 8+ — всё в кавычках.
  Точные правила — `format-writer.md`.

---

## 12. Структуры, которые Программа хранит «как есть»

### 12.1. `group`

`(group <имя Q> [locked] (uuid T) [(locked B)] (members T…))` (P9:6019–6072). Имя — **только строка в
кавычках** (`T_STRING`; голый символ → `Expecting 'group name or locked'`), обычно `""`. `id` — синоним
`uuid` для файлов [20200811, 20231215). Порядок дочерних свободный в 8+, **строгий** в 6/7:
`(group "name" [locked] (id …) (members …))` (P7:5144–5190) — `uuid` там не принимается.
UUID участников, которых нет в footprint'е, молча пропускаются (P9:1258–1397). В библиотеках: 4 файла
v9/master (в просмотренном примере — после pad, перед `embedded_fonts`).

### 12.2. `zone` (в footprint — keepout / rule area)

`parseZONE` (P9:6703–7420): голый `locked` в начале, далее элементы в любом порядке: `net I`,
`net_name SN`, `layer S` | `layers S…`, `uuid`, `hatch K N` (`none|edge|full`), `priority I`,
`connect_pads [K] (clearance N)`, `min_thickness N`, `filled_areas_thickness B`, `fill …`,
`placement (enabled B) (sheetname S) | (component_class S)`, `keepout (tracks|vias|pads|copperpour|footprints allowed|not_allowed)`,
`polygon (pts …)`, `filled_polygon`, `fill_segments`, `name S`, `attr (teardrop (type K))`, `locked B`.
Неизвестное → ошибка. Пример: `kfp/v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod`
(2 файла v9, 7 master; в фикстурах **нет**).

### 12.3. `fp_text_box`, `table`, `dimension`, `image`

Только структура — Программа их не интерпретирует. Ни одного вхождения в пяти библиотеках.

* `fp_text_box` (P9:3579, `parseTextBoxContent` 3605–3766): `[locked] <текст> (start)(end) | (pts)`,
  `angle`, `stroke`, `border B`, `margins N N N N`, `layer`, `uuid`, `effects`, `render_cache`, `locked`;
  master + `knockout`, `custom_property`.
* `table` (P9:3769–3930): `column_count`, `locked`, `angle` (устар.), `layer`, `column_widths N…`,
  `row_heights N…`, `cells (table_cell …)…`, `border (external B)(header B)(stroke …)`,
  `separators (rows B)(cols B)(stroke …)`.
* `dimension` (P9:3933–4398): `[locked] (type aligned|orthogonal|leader|center|radial)` или старое
  `(width N)`; `layer`, `uuid`, `gr_text`, `pts`, `height`, `leader_length`, `orientation`,
  `format (…)`, `style (…)`, `feature1/2`, `crossbar`, `arrow1a/1b/2a/2b`, `locked`.
* `image` (P9:3259–3354): `at N N`, `layer`, `scale N`, `data <base64 символы…>`, `(locked B)`, `uuid`.

### 12.4. `embedded_files` (9.0+)

`(embedded_files (file (name SN) (type datasheet|font|model|worksheet|other) (checksum SN) (data | base64… |))…)`
(E9:329–470). Данные — символы между `|`…`|`. Ошибка разбора логируется, footprint загружается (§2).
`embedded_fonts` — отдельный узел footprint'а (`B`). В библиотеках: `(embedded_fonts no)` во всех
файлах 9.0 (1860) и master (4882); `embedded_files` — 0.

---

## 13. Совместимость форм между версиями KiCad

Что сломает загрузку в более старом KiCad (проверено по коду; «≥X» — первая версия, которая принимает).
Нужна writer'у при записи «в формат версии X» и `validate`.

| Конструкция | Принимает | Старшие отвергают с | Ссылка |
|---|---|---|---|
| `(uuid …)` вместо `(tstamp …)` у элементов | ≥ 8.0 | P7: `Expecting 'layer, hide, effects, render_cache or tstamp'` и т.п. | P7:4080, 4529 |
| `(stroke …)` у графики | ≥ 7.0 | P6 | P6 `parseFP_SHAPE` |
| `(fill no)` | ≥ 8.0 | P7 `Expecting 'yes, none, solid'` | P7:4510 |
| `(hide yes)` в `effects`/`fp_text`/`model`, `(bold yes)`, `(italic yes)` | ≥ 8.0 | P7 (голые — да, со значением — ошибка) | P7:449–455, 506, 615, 4062 |
| `(locked yes)` у графики | ≥ 8.0 | P7 (только `(locked)`) | P7:4523 |
| `(property … <дети>)` | ≥ 8.0 | P6/P7 (`NeedRIGHT` после значения) | P7:370–382 |
| `(unlocked yes)` у текста | ≥ 8.0 | P7 (только `unlocked` внутри `at`) | P7:4027–4031 |
| `generator_version` | ≥ 8.0 | P6/P7 | parser_funcs |
| `thermal_bridge_angle`, `thermal_bridge_width`, `zone_layer_connections`, `gr_bbox`, `private_layers`, `net_tie_pad_groups`, `fp_text_box`, `dimension`, `image`, `attr allow_soldermask_bridges/allow_missing_courtyard` | ≥ 7.0 | P6 | parser_funcs |
| `teardrops`, `gr_vector`, `attr dnp`, `sheetname`/`sheetfile` | ≥ 8.0 | P7 | parser_funcs |
| footprint `solder_paste_margin_ratio`, `embedded_fonts`, `embedded_files`, `table`, `component_classes`, `padstack`, `tenting` (старая форма), `layers`/`solder_mask_margin` у графики, `teardrops … curved_edges` | ≥ 9.0 | P8 | parser_funcs |
| `duplicate_pad_numbers_are_jumpers`, `jumper_pad_groups`, `point`, `units`, `stackup`, `transform`, `fp_ellipse*`, `barcode`, `(tenting (front …))`, `(net "имя")` без номера, `fill hatch` | master | P9 | §5.1, §9.2 |
| footprint `solder_paste_ratio` | 6.0 … master | — (9+ читают как устаревший) | P9:4739 |
| pad `solder_paste_ratio` | нигде | все | — |
| `(fp_text reference/value …)` | 6.0 … master | — | P9:3374 |
| `fp_arc (start)(end)(angle)` | при `version <= 20210925` в любой версии KiCad | — | P9:2860 |

Скрипт `accept_check.py` (§14.3) подтверждает на реальных файлах: библиотеку v8.0.0 не принимают P6/P7
(`generator_version`, `uuid`, `property` с детьми, `stroke`), v9.0.0 — P8 (`embedded_fonts` 1860 файлов,
`solder_paste_margin_ratio` 1), master — P9 (`duplicate_pad_numbers_are_jumpers` 4882, `point` 369).
Проверка только по именам узлов, формы значений (`(hide yes)` и т.п.) она не ловит.

---

## 14. Часть 2: эмпирическая инвентаризация

### 14.1. Метод

Скрипт `scratchpad/research/inventory.py` — минимальный S-expr парсер без зависимостей (атом = вид
`n` число / `y` символ без кавычек / `s` строка в кавычках + **сырой** текст; `#` — комментарий только как
первый непробельный символ строки, как в L9). Для каждого ключа «родитель/узел» собирает число вхождений и
файлов, арность (позиционные атомы до первого подузла), виды и значения атомов по позициям, голые символы
(в т.ч. после подузлов — ловит голые `hide`/`locked`), дочерние узлы, 3 сырых примера с разными
сигнатурами, а также имена слоёв и кавычки, версии/генераторы, имена `property`, последовательности
дочерних узлов footprint'а, формы чисел и строк, ~150 флагов конструкций. Запуск:

```
.venv/bin/python scratchpad/research/inventory.py inventory_kfp.json v6.0.0=kfp/v6.0.0 v7.0.0=… v8.0.0=… v9.0.0=… master=…
.venv/bin/python scratchpad/research/inventory.py inventory_fixtures.json kicad5=tests/fixtures/kicad5 …
.venv/bin/python scratchpad/research/build_token_json.py      # → docs/dev/token-inventory.json
```

Структура `token-inventory.json`: `_meta` (источники, описание схемы), `libraries.<набор>`,
`fixtures.<набор>`; в каждом наборе — `files`, `parse_errors`, `files_with_leading_comments`, `roots`,
`versions`, `generators`, `generator_versions`, `layer_names`, `layer_quoting`, `paths`, `nodes`, `flags`,
`property_names`, `footprint_child_sequences`, `numbers`, `strings` (подробно — `_meta.schema`).
Пути в примерах — относительно каталога набора.

Дополнительные скрипты: `constructs.py` (файлы с конкретными конструкциями → `constructs.json`,
таблица §15), `accept_check.py` (какие узлы реальных файлов отвергает парсер каждой версии),
`parser_funcs.py` (наборы `case T_*` по функциям парсеров 6.0…master), `fixture_stats.py`
(regex-подсчёты), `longnum.py` (числа с > 6 знаками после точки).

### 14.2. Сводка по наборам

| Набор | Файлов | Ошибок разбора | Ключей «родитель/узел» | Корни |
|---|---|---|---|---|
| v6.0.0 | 1303 | 0 | 77 | `module` 1300, `footprint` 3 |
| v7.0.0 | 1332 | 0 | 76 | `footprint` 1306, `module` 26 |
| v8.0.0 | 1377 | 0 | 90 | `footprint` 1377 |
| v9.0.0 | 3297 | 0 | 137 | `footprint` 3297 |
| master | 4882 | 0 | 146 | `footprint` 4882 |
| фикстуры kicad5 / kicad6 / kicad8 / kicad9 / kicad10dev | 166 / 224 / 1377 / 337 / 208 | 0 | 69 / 63 / 90 / 96 / 96 | см. `token-inventory.json` |

(kicad8 в фикстурах совпадает с полной библиотекой v8.0.0 — 1377 файлов.)

Дочерние узлы footprint'а (число **узлов**; `token-inventory.json` → `nodes["<root>/footprint"].children`):

| Узел | v6.0.0 | v7.0.0 | v8.0.0 | v9.0.0 | master |
|---|---|---|---|---|---|
| `fp_line` | 67 024 | 67 432 | 67 995 | 97 123 | 150 333 |
| `pad` | 22 267 | 23 329 | 24 443 | 69 912 | 157 075 |
| `fp_text` | 3 909 | 3 996 | 1 377 | 3 482 | 5 094 |
| `property` | 0 | 0 | 6 885 | 10 314 | 15 289 |
| `fp_arc` / `fp_circle` | 261 / 257 | 261 / 257 | 293 / 257 | 908 / 1 166 | 1 285 / 1 570 |
| `fp_poly` / `fp_rect` | 0 / 0 | 0 / 0 | 349 / 6 | 1 328 / 505 | 2 840 / 5 824 |
| `model` | 1 303 | 1 332 | 1 377 | 3 130 | 4 715 |
| `attr` | 536 | 1 332 | 1 377 | 3 297 | 4 882 |
| `tedit` | 1 303 | 1 332 | 0 | 0 | 0 |
| `generator_version` | 0 | 0 | 1 377 | 1 860 | 643 |
| `embedded_fonts` | 0 | 0 | 0 | 1 860 | 4 882 |
| `duplicate_pad_numbers_are_jumpers` | 0 | 0 | 0 | 0 | 4 882 |
| `point` | 0 | 0 | 0 | 0 | 369 |
| `solder_mask_margin` | 1 | 1 | 1 | 10 | 152 |
| `solder_paste_margin` | 0 | 0 | 0 | 6 | 55 |
| `clearance` | 0 | 0 | 17 | 14 | 13 |
| `solder_paste_margin_ratio` / `solder_paste_ratio` | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 0 | 1 / 2 |
| `net_tie_pad_groups` | 0 | 0 | 0 | 3 | 3 |
| `group` | 0 | 0 | 0 | 4 | 4 |
| `zone` | 0 | 0 | 0 | 2 | 11 |

(для v6.0.0/v7.0.0 объединены `module` и `footprint`.)

**Ни разу не встречаются ни в одной библиотеке:** `fp_curve`, `fp_text_box`, `table`, `dimension`,
`image`, `embedded_files`, `private_layers`, `placed`, `locked` (любой формы), `path`, `sheetfile`,
`component_classes`, `jumper_pad_groups`, `units`, `transform`, `stackup`; у pad — `net`, `teardrops`,
`padstack`, `tenting`, `pinfunction`, `pintype`, `die_length`, `rect_delta`, `keep_end_layers`,
`zone_layer_connections`, `thermal_width`, `thermal_gap` (кроме zone), форма `trapezoid`; у текста —
`face`, `bold`, `italic`, `line_spacing`, `mirror`, `knockout`, `render_cache`, `locked`, голый `hide`;
`(arc …)` в `pts`; комментарии в начале файла. Их поддержку можно проверять только синтетическими
фикстурами.

### 14.3. Голые символы и значения

| Где | Значения (частота узлов; v6/v7/v8/v9/master) |
|---|---|
| тип pad | `smd`, `thru_hole` (все); `connect` (v9 108, master 108 узлов), `np_thru_hole` (v9 102, master 261) |
| форма pad | `rect`, `oval`, `circle`, `roundrect`, `custom` (все); `trapezoid` — 0 |
| `attr` | `smd`, `through_hole`; с v9: `exclude_from_pos_files exclude_from_bom` (167 файлов, без smd/th, MountingHole); одиночный `exclude_from_pos_files` — 1 |
| `fill` | см. §7.4 |
| `stroke/type` | `solid`, `default` |
| `pad/property` | `pad_prop_heatsink`, `pad_prop_bga`, `pad_prop_fiducial_loc` |
| `options/anchor` / `clearance` | `rect`, `circle` / `outline` |
| `remove_unused_layers` | только `no` (8+) |
| `hide`, `unlocked` (в property/fp_text) | только `yes` в списке (8+); голых нет |
| `zone/hatch` | `edge N`, `full N` |
| `layer` у текста | без модификаторов (`knockout` — 0) |
| `drill` | `oval` (6/6/6/21/52 узлов) |

### 14.4. Числа и строки

`token-inventory.json` → `numbers`, `strings`:

* Знаков после точки у чисел: подавляющее большинство 0–6; 10 знаков — только `roundrect_rratio`
  (например `0.1666666667`, v8 8 узлов, v9 148, master 155) и `offset/xyz` модели (`0.3249999954`, v9 3);
  в v6.0.0 — `fp_arc/angle` `-316.9297483` (7 знаков). Координаты в мм — не более 6 знаков.
* Экспонента: только `tedit 5E888720` (v6.0.0, v7.0.0 по 1 файлу) — §1.2.
* `-0`: v6.0.0 31 атом (`at`), master 6 (`xyz`). Хвостовые нули в дроби (`1.0`): v6.0.0 5144 атома
  (KiCad 5 писал `(drill 1.0)` и т.п.), в 7.0+ — 0. Ведущий `+`, ведущая/хвостовая точка — 0.
* Строки: пустые `""` (номера pad, `net_name`, `group`); экранирование `\"` (1–3 файла `descr` в каждом
  наборе, например `Package_SO.pretty/QSOP-16_3.9x4.9mm_P0.635mm.kicad_mod`), `\\` (v9: `\\xe2\\x88\\x92`
  в `descr` `Package_DFN_QFN.pretty/DFN-22-1EP_5x6mm_P0.5mm_EP3.14x4.3mm.kicad_mod`); не-ASCII в `descr`
  (`º`, `²`, `−`); сырых переводов строк в строках — 0.
* Символы без кавычек, начинающиеся с цифры: `tedit` и `tstamp` в v6/v7 (UUID без кавычек в KiCad 6:
  `(tstamp 7079fecf-8ee7-…)`), имена pad в v6.0.0.

### 14.5. Типичные последовательности дочерних узлов footprint'а

(`footprint_child_sequences`, подряд идущие одинаковые схлопнуты; верхние строки)

* v6.0.0: `layer tedit descr tags fp_text fp_line pad fp_text model` (533), с `attr` после `tags` (297).
* v7.0.0: `version generator layer tedit descr tags attr fp_text fp_line pad model` (973).
* v8.0.0: `version generator generator_version layer descr tags property attr fp_line fp_text pad model` (665).
* v9.0.0: `version generator generator_version layer descr tags property attr fp_line fp_text pad embedded_fonts model` (940);
  файлы генератора (20240108): `version generator layer descr tags property attr fp_line fp_poly fp_line fp_text pad model` (922).
* master: `version generator layer descr tags property attr duplicate_pad_numbers_are_jumpers fp_line fp_poly fp_line fp_poly fp_text pad embedded_fonts model` (1030).

Порядок, который пишет сам KiCad, — предмет `format-writer.md`.

---

## 15. Привязка конструкций к фикстурам репозитория

Сгенерировано `constructs.py` + `fixture_table.py` (снимок фикстур на 2026-09-27 16:30; фикстуры
пополняются параллельно — при изменениях перезапустить). Числа — количество **файлов**. «k8» = полная
библиотека v8.0.0. Пути «в библиотеке» — относительно `scratchpad/` (`kfp/<тег>/…`), для конструкций,
которых нет в фикстурах; такие фикстуры стоит добавить (строки с **нет**).

| конструкция | библиотеки v6/v7/v8/v9/master | фикстуры k5/k6/k8/k9/k10 | пример в tests/fixtures | пример в библиотеке |
|---|---|---|---|---|
| корень `(module ...)` (KiCad 5, без version) | 1300/26/0/0/0 | 165/7/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod`<br>`tests/fixtures/kicad6/Package_SO.pretty/HSOP-32-1EP_7.5x11mm_P0.65mm_EP4.7x4.7mm.kicad_mod` | `kfp/v7.0.0/Package_SO.pretty/HSOP-32-1EP_7.5x11mm_P0.65mm_EP4.7x4.7mm.kicad_mod` |
| `(version 20210722)` в наборе KiCad 5 | 3/0/0/0/0 | 1/0/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/DX_5R5VxxxxU_D11.5mm_P5.00mm.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/DX_5R5HxxxxU_D11.5mm_P10.00mm.kicad_mod` |
| `(version 20211014)` (KiCad 6) | 0/1306/0/0/0 | 0/217/0/0/0 | `tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `(version 20240108)` (KiCad 8 / генератор в v9) | 0/0/1377/1437/0 | 0/0/1377/143/0 | `tests/fixtures/kicad8/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod`<br>`tests/fixtures/kicad9/LED_THT.pretty/LED_D1.8mm_W3.3mm_H2.4mm.kicad_mod` | `kfp/v9.0.0/Capacitor_SMD.pretty/C_1808_4520Metric.kicad_mod` |
| `(version 20241229)` (KiCad 9) | 0/0/0/1860/0 | 0/0/0/194/0 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/v9.0.0/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(version 20260206)` (10-dev) | 0/0/0/0/4882 | 0/0/0/0/208 | `tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(generator pcbnew)` без кавычек | 3/1306/0/0/0 | 1/217/0/0/0 | `tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `(generator "kicad-footprint-generator")` без `generator_version` | 0/0/0/1437/4239 | 0/0/0/143/177 | `tests/fixtures/kicad9/LED_THT.pretty/LED_D1.8mm_W3.3mm_H2.4mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(tedit HEX)` | 1303/1332/0/0/0 | 166/224/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v6.0.0/Package_SO.pretty/SO-16_3.9x9.9mm_P1.27mm.kicad_mod` (`5E888720`) |
| `(tstamp …)` у элементов | 3/1306/0/0/0 | 1/217/0/0/0 | `tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `(uuid "…")` у элементов | 0/0/1377/1860/643 | 0/0/1377/194/31 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod`<br>`tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_3x5.3.kicad_mod` |
| нет `(attr)` (KiCad 5 ⇒ through_hole) | 767/0/0/0/0 | 88/0/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `(attr exclude_from_pos_files exclude_from_bom)` | 0/0/0/167/167 | 0/0/0/17/7 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.1mm.kicad_mod`<br>`tests/fixtures/kicad10dev/MountingHole.pretty/MountingHole_2.1mm.kicad_mod` | `kfp/master/MountingHole.pretty/MountingHole_2.1mm.kicad_mod` |
| `fp_text reference/value` (KiCad 5/6) | 1303/1332/0/0/0 | 166/224/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod`<br>`tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `fp_text user %R` (голый `%R`) | 1296/0/0/0/0 | 164/0/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `fp_text … (at x y angle)` | 284/284/1377/3297/4882 | 35/47/1377/337/208 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `fp_text user … (unlocked yes)` | 0/0/0/8/21 | 0/0/0/2/2 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod`<br>`tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` |
| `(property "Reference" …)` с эффектами | 0/0/1377/3297/4882 | 0/0/1377/337/208 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(property "Footprint" …)` (только 8.0) | 0/0/1377/0/0 | 0/0/1377/0/0 | `tests/fixtures/kicad8/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v8.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| пользовательское свойство `"KiLib_Generator"` | 0/0/0/0/4239 | 0/0/0/0/177 | `tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(property … (hide yes))` | 0/0/1377/1860/4882 | 0/0/1377/194/208 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(property … (unlocked yes))` | 0/0/1377/1858/636 | 0/0/1377/194/31 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_3x5.3.kicad_mod` |
| графика с `(width w)` (6/7) | 1303/1332/0/0/0 | 166/224/0/0/0 | `tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| графика с `(stroke (width) (type))` | 0/0/1377/3297/4882 | 0/0/1377/337/208 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(stroke … (type default))` | 0/0/1/28/46 | 0/0/1/3/1 | `tests/fixtures/kicad8/Package_SO.pretty/PowerPAK_SO-8L_Single.kicad_mod`<br>`tests/fixtures/kicad9/Package_DFN_QFN.pretty/Texas_REF0038A_WQFN-38-2EP_6x4mm_P0.4.kicad_mod` | `kfp/master/Crystal.pretty/Resonator_SMD_Murata_CSTCR_4.5x2x1.15mm.kicad_mod` |
| `fp_arc` старого вида `(start ц)(end нач)(angle a)` | 247/0/0/0/0 | 32/0/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Radial_Tantal_D5.5mm_P5.00mm.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod` |
| `fp_arc (start)(mid)(end)` | 0/247/279/495/593 | 0/43/279/50/25 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Capacitor_THT.pretty/CP_Radial_Tantal_D4.5mm_P5.00mm.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod` |
| `fp_circle` без `(fill)` | 95/0/0/0/0 | 12/0/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Radial_D10.0mm_P2.50mm_P5.00mm.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/CP_Radial_D10.0mm_P2.50mm.kicad_mod` |
| `(fill none)` | 1/96/99/403/0 | 0/16/99/41/0 | `tests/fixtures/kicad8/Capacitor_THT.pretty/CP_Radial_D10.0mm_P2.50mm.kicad_mod`<br>`tests/fixtures/kicad9/LED_THT.pretty/LED_D1.8mm_W3.3mm_H2.4mm.kicad_mod` | `kfp/v9.0.0/LED_THT.pretty/LED_D1.8mm_W3.3mm_H2.4mm.kicad_mod` |
| `(fill solid)` | 0/0/347/925/0 | 0/0/347/92/0 | `tests/fixtures/kicad8/Package_SO.pretty/Diodes_PSOP-8.kicad_mod`<br>`tests/fixtures/kicad9/Package_DFN_QFN.pretty/DFN-10-1EP_3x3mm_P0.5mm_EP1.7x2.5mm.kicad_mod` | `kfp/v9.0.0/Package_DFN_QFN.pretty/AO_AOZ666xDI_DFN-8-1EP_3x3mm_P0.65mm_EP1.25x2.7mm.kicad_mod` |
| `(fill yes)` | 0/0/0/393/1763 | 0/0/0/42/75 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/AMS_QFN-4-1EP_2x2mm_P0.95mm_EP0.7x1.6mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Connector_PinHeader_2.54mm.pretty/PinHeader_1x01_P2.54mm_Horizontal.kicad_mod` | `kfp/master/Connector_PinHeader_2.54mm.pretty/PinHeader_1x01_P2.54mm_Horizontal.kicad_mod` |
| `(fill no)` | 0/0/0/473/3919 | 0/0/0/49/163 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `fp_rect` | 0/0/1/266/2404 | 0/0/1/29/104 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` |
| `fp_poly` | 0/0/349/1314/1746 | 0/0/349/134/75 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` |
| pad `thru_hole circle` | 466/468/488/1285/2311 | 60/80/488/125/92 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| pad `thru_hole oval` | 464/464/480/694/517 | 49/89/480/69/21 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/master/Capacitor_THT.pretty/DX_5R5HxxxxU_D11.5mm_P10.00mm.kicad_mod` |
| pad `thru_hole rect` | 415/415/447/662/669 | 46/80/447/70/27 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/master/Capacitor_THT.pretty/DX_5R5HxxxxU_D11.5mm_P10.00mm.kicad_mod` |
| pad `thru_hole roundrect` | 0/0/0/153/703 | 0/0/0/16/27 | `tests/fixtures/kicad9/Package_DIP.pretty/CERDIP-14_W7.62mm_SideBrazed.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| pad `thru_hole custom` | 0/0/0/0/29 | 0/0/0/0/2 | `tests/fixtures/kicad10dev/Connector_JST.pretty/JST_ZE_B03B-ZESK-1D_1x03_P1.50mm_Vertical.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_ZE_B02B-ZESK-1D_1x02_P1.50mm_Vertical.kicad_mod` |
| pad `smd roundrect` | 182/214/229/1305/1782 | 23/37/229/127/70 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| pad `smd custom` + `options` + `primitives` | 5/5/5/149/93 | 2/0/5/16/2 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_DFN_QFN.pretty/Texas_RHB0032M_VQFN-32-1EP_5x5mm_P0.5mm_EP2.1x2.1mm_ThermalVias.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/IDT_QFN-12-1EP_2x2mm_P0.5mm_EP1.1x1.1mm.kicad_mod` |
| pad `smd circle` | 0/0/0/6/241 | 0/0/0/1/10 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Nordic_AQFN-94-1EP_7x7mm_P0.4mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` | `kfp/master/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` |
| pad `connect` | 0/0/0/72/72 | 0/0/0/7/3 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.5mm_Pad_TopBottom.kicad_mod`<br>`tests/fixtures/kicad10dev/MountingHole.pretty/MountingHole_3.2mm_M3_DIN965_Pad_TopOnly.kicad_mod` | `kfp/master/MountingHole.pretty/MountingHole_2.2mm_M2_DIN965_Pad_TopBottom.kicad_mod` |
| pad `np_thru_hole circle` | 0/0/0/97/196 | 0/0/0/8/9 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.1mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Connector_JST.pretty/JST_JWPF_B02B-JWPF-SK-R_1x02_P2.00mm_Vertical.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_JWPF_B02B-JWPF-SK-R_1x02_P2.00mm_Vertical.kicad_mod` |
| pad `np_thru_hole oval` | 0/0/0/5/18 | 0/0/0/0/1 | `tests/fixtures/kicad10dev/Connector_JST.pretty/JST_XA_S07B-XASK-1_1x07_P2.50mm_Horizontal.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_XA_S02B-XASK-1_1x02_P2.50mm_Horizontal.kicad_mod` |
| pad с номером `""` | 100/107/116/941/1194 | 14/18/116/99/50 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.1mm.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/C_01005_0402Metric.kicad_mod` |
| pad с нецифровым номером (`A1`, `MP`, …) | 0/0/0/10/467 | 0/0/0/2/19 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Microchip_DRQFN-44-1EP_5x5mm_P0.7mm_EP2.65x2.65mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Connector_JST.pretty/JST_ACH_BM01B-ACHSS-A-GAN-ETF_1x01-1MP_P1.20mm_Vertical.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_ACH_BM01B-ACHSS-A-GAN-ETF_1x01-1MP_P1.20mm_Vertical.kicad_mod` |
| повторяющиеся номера pad | 74/75/80/527/785 | 10/17/80/43/29 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Radial_D10.0mm_P5.00mm_P7.50mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Capacitor_THT.pretty/CP_Radial_D24.0mm_P10.00mm_3pin_SnapIn.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Radial_D10.0mm_P2.50mm_P5.00mm.kicad_mod` |
| pad `(at x y angle)` | 13/13/12/137/156 | 2/4/12/22/6 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod` |
| `(drill oval w h)` | 3/3/3/8/30 | 1/0/3/0/1 | `tests/fixtures/kicad8/Capacitor_THT.pretty/DX_5R5HxxxxU_D11.5mm_P10.00mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Connector_JST.pretty/JST_XA_S07B-XASK-1_1x07_P2.50mm_Horizontal.kicad_mod` | `kfp/master/Capacitor_THT.pretty/DX_5R5HxxxxU_D11.5mm_P10.00mm.kicad_mod` |
| `(drill (offset x y))` у SMD, без размера | 1/1/1/1/1 | 0/0/1/0/0 | `tests/fixtures/kicad8/Package_DIP.pretty/Fairchild_LSOP-8.kicad_mod` | `kfp/master/Package_DIP.pretty/Fairchild_LSOP-8.kicad_mod` |
| `(roundrect_rratio r)` | 182/214/229/1458/2485 | 23/37/229/143/97 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(chamfer_ratio r) (chamfer top_left)` | 0/0/0/2/2 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/Package_DFN_QFN.pretty/Analog_QFN-28-36-2EP_5x6mm_P0.5mm.kicad_mod` |
| `(remove_unused_layers no)` | 0/0/858/1792/2745 | 0/0/858/175/110 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| pad `(zone_connect N)` | 5/5/87/731/941 | 2/0/87/75/36 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.7mm_M2.5_Pad_Via.kicad_mod` | `kfp/master/MountingHole.pretty/MountingHole_2.2mm_M2_DIN965_Pad.kicad_mod` |
| pad `(thermal_bridge_angle a)` | 0/0/5/51/57 | 0/0/5/8/2 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Texas_REF0038A_WQFN-38-2EP_6x4mm_P0.4.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/Infineon_MLPQ-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm.kicad_mod` |
| pad `(solder_paste_margin_ratio r)` | 7/7/7/14/14 | 1/3/7/0/2 | `tests/fixtures/kicad8/Package_SO.pretty/Diodes_PSOP-8.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_DFN_QFN.pretty/DFN-S-8-1EP_6x5mm_P1.27mm.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm.kicad_mod` |
| pad `(solder_paste_margin m)` | 1/1/1/12/12 | 0/0/1/1/1 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/AMS_QFN-4-1EP_2x2mm_P0.95mm_EP0.7x1.6mm.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/AMS_QFN-4-1EP_2x2mm_P0.95mm_EP0.7x1.6mm.kicad_mod` |
| pad `(solder_mask_margin m)` | 0/0/0/5/7 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod` |
| pad `(property pad_prop_heatsink)` | 0/0/82/671/797 | 0/0/82/66/30 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/DFN-10-1EP_3x3mm_P0.5mm_EP1.7x2.5mm.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/AO_AOZ666xDI_DFN-8-1EP_3x3mm_P0.65mm_EP1.25x2.7mm.kicad_mod` |
| pad `(property pad_prop_bga)` | 0/0/0/2/236 | 0/0/0/1/10 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Nordic_AQFN-94-1EP_7x7mm_P0.4mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` | `kfp/master/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` |
| pad `(property pad_prop_fiducial_loc)` | 0/0/0/0/1 | 0/0/0/0/0 | **нет** | `kfp/master/Package_DFN_QFN.pretty/Texas_RDX0007A_QFN-FCMOD-7-3.3x4mm-P0.5mm_4EP.kicad_mod` |
| `(options (clearance outline) (anchor rect))` | 5/5/5/41/47 | 2/0/5/6/1 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Texas_RGY_R-PVQFN-N24_EP2.05x3.1mm_ThermalVias.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_DFN_QFN.pretty/UDFN-4-1EP_1x1mm_P0.65mm_EP0.48x0.48mm.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/Infineon_MLPQ-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm.kicad_mod` |
| `(options … (anchor circle))` | 0/0/0/110/81 | 0/0/0/11/3 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Connector_JST.pretty/JST_ZE_B03B-ZESK-1D_1x03_P1.50mm_Vertical.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_ZE_B02B-ZESK-1D_1x02_P1.50mm_Vertical.kicad_mod` |
| primitives `gr_poly` | 5/5/5/145/118 | 2/0/5/15/4 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm.kicad_mod` | `kfp/master/Connector_JST.pretty/JST_ZE_B02B-ZESK-1D_1x02_P1.50mm_Vertical.kicad_mod` |
| primitives `gr_poly` без `fill` (KiCad 5: `(gr_poly (pts …) (width 0))`) | 5/0/0/0/0 | 2/0/0/0/0 | `tests/fixtures/kicad5/Package_SO.pretty/Infineon_PG-DSO-20-85.kicad_mod`<br>`tests/fixtures/kicad5/Package_SO.pretty/Vishay_PowerPAK_1212-8_Dual.kicad_mod` | `kfp/v6.0.0/Package_SO.pretty/Infineon_PG-DSO-20-85.kicad_mod` |
| primitives `gr_circle` | 0/0/0/5/5 | 0/0/0/1/0 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Texas_RGY_R-PVQFN-N24_EP2.05x3.1mm_ThermalVias.kicad_mod` | `kfp/master/Package_DFN_QFN.pretty/Linear_DE14MA.kicad_mod` |
| primitives `gr_arc` | 0/0/0/1/1 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/Package_DFN_QFN.pretty/Texas_QFN-41_10x16mm.kicad_mod` |
| `(layers *.Cu *.Mask)` | 820/822/858/1836/2793 | 97/151/858/177/112 | `tests/fixtures/kicad9/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/master/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| имена слоёв без кавычек | 1303/846/0/0/0 | 166/156/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod`<br>`tests/fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v7.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `F&B.Cu` | 0/0/0/1/0 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod` |
| слой `"Rescue"` | 0/0/0/1/0 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/MountingHole.pretty/MountingHole_6.4mm_M6_DIN965_Pad_TopBottom.kicad_mod` |
| footprint `(clearance m)` | 0/0/17/14/13 | 0/0/17/1/0 | `tests/fixtures/kicad8/Package_SO.pretty/HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm.kicad_mod`<br>`tests/fixtures/kicad9/Package_SO.pretty/HTSSOP-32-1EP_6.1x11mm_P0.65mm_EP5.2x11mm_Mask4.11x4.36mm.kicad_mod` | `kfp/master/Package_SO.pretty/HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm.kicad_mod` |
| footprint `(solder_mask_margin m)` | 1/1/1/10/152 | 0/0/1/1/7 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Panasonic_HQFN-16-1EP_4x4mm_P0.65mm_EP2.9x2.9mm.kicad_mod`<br>`tests/fixtures/kicad10dev/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` | `kfp/master/Package_BGA.pretty/Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm.kicad_mod` |
| footprint `(solder_paste_margin m)` | 0/0/0/6/55 | 0/0/0/0/3 | `tests/fixtures/kicad10dev/Package_BGA.pretty/Micron_FBGA-96_8x14mm_Layout9x16_P0.8mm.kicad_mod` | `kfp/master/Package_BGA.pretty/Analog_BGA-49_6.25x6.25mm_Layout7x7_P0.8mm.kicad_mod` |
| footprint `(solder_paste_margin_ratio r)` (9+) | 0/0/0/1/1 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/Package_DFN_QFN.pretty/Qorvo_DFN-8-1EP_2x2mm_P0.5mm.kicad_mod` |
| footprint `(solder_paste_ratio r)` | 0/0/0/0/2 | 0/0/0/0/0 | **нет** | `kfp/master/Package_BGA.pretty/ST_TFBGA-225_13x13mm_Layout15x15_P0.8mm.kicad_mod` |
| `(net_tie_pad_groups "…")` | 0/0/0/3/3 | 0/0/0/1/0 | `tests/fixtures/kicad9/Package_DFN_QFN.pretty/Vishay_PowerPAK_MLP44-24L.kicad_mod` | `kfp/v9.0.0/Package_DFN_QFN.pretty/EPC_QFN-13-3EP_3.5x5mm_P0.5mm.kicad_mod` |
| `(group "" (uuid) (members …))` | 0/0/0/4/4 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/Package_DIP.pretty/DIP-24_18.0mmx34.29mm_W15.24mm.kicad_mod` |
| `(zone …)` (keepout) в footprint | 0/0/0/2/7 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod` |
| `(embedded_fonts no)` | 0/0/0/1860/4882 | 0/0/0/194/208 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(duplicate_pad_numbers_are_jumpers no)` | 0/0/0/0/4882 | 0/0/0/0/208 | `tests/fixtures/kicad10dev/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(point (at) (size) (layer))` | 0/0/0/0/326 | 0/0/0/0/13 | `tests/fixtures/kicad10dev/LED_THT.pretty/LED_D3.0mm_Horizontal_O1.27mm_Z6.0mm.kicad_mod` | `kfp/master/LED_THT.pretty/LED_D1.8mm_W1.8mm_H2.4mm_Horizontal_O1.27mm_Z1.6mm.kicad_mod` |
| путь `model` без кавычек | 1300/26/0/0/0 | 165/7/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod`<br>`tests/fixtures/kicad6/Package_SO.pretty/HSOP-32-1EP_7.5x11mm_P0.65mm_EP4.7x4.7mm.kicad_mod` | `kfp/v7.0.0/Package_SO.pretty/HSOP-32-1EP_7.5x11mm_P0.65mm_EP4.7x4.7mm.kicad_mod` |
| `(model … (at (xyz …)))` (дюймы) | 1300/26/0/0/0 | 165/7/0/0/0 | `tests/fixtures/kicad5/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` | `kfp/v6.0.0/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod` |
| `(model … (offset (xyz …)))` | 3/1306/1377/3130/4715 | 1/217/1377/320/201 | `tests/fixtures/kicad9/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` | `kfp/master/Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod` |
| `(model … (hide yes))` | 0/0/0/1/2 | 0/0/0/0/0 | **нет** | `kfp/v9.0.0/Package_SO.pretty/Texas_S-PDSO-G8_3x3mm_P0.65mm.kicad_mod` |
| нет `(model)` | 0/0/0/167/167 | 0/0/0/17/7 | `tests/fixtures/kicad9/MountingHole.pretty/MountingHole_2.1mm.kicad_mod` | `kfp/master/MountingHole.pretty/MountingHole_2.1mm.kicad_mod` |
| `(justify left bottom)` | 0/0/0/0/1 | 0/0/0/0/0 | **нет** | `kfp/master/Package_DFN_QFN.pretty/Texas_RDX0007A_QFN-FCMOD-7-3.3x4mm-P0.5mm_4EP.kicad_mod` |

Рекомендуемые дополнения фикстур (не делал — вне задачи): `chamfer`, `group`, `zone`, `F&B.Cu`,
`Rescue`, `model (hide yes)`, `primitives gr_arc`, footprint `solder_paste_margin_ratio`/`solder_paste_ratio`,
pad `solder_mask_margin`, `pad_prop_fiducial_loc`, `justify` — все из перечисленных файлов библиотек.
Синтетические (в библиотеках нет): `fp_curve`, `arc` в `pts`, `fp_text_box`, `teardrops`, `padstack`,
`tenting`, `net` у pad, `bold`/`italic`/`face`, голые `hide`/`locked`, `(locked yes)`, `private_layers`,
`knockout`, неизвестный узел `example_token` (§2.1).

---

## 16. Проверено

Все скрипты — `scratchpad/research/`, интерпретатор `kicadfp/.venv/bin/python` (3.12).

1. **Инвентаризация** (`inventory.py`) — полный проход: v6.0.0 1303 файла, v7.0.0 1332, v8.0.0 1377,
   v9.0.0 3297, master 4882 (всего 12 191); фикстуры kicad5 166, kicad6 224, kicad8 1377, kicad9 337,
   kicad10dev 208. Ошибок разбора мини-парсером — 0 во всех наборах. Результат → `docs/dev/token-inventory.json`.
   Первая версия скрипта (от прерванного прогона) перезапущена и дала JSON, **идентичный** ранее
   сохранённому (`==` по обоим разделам); затем скрипт исправлен (флаг `fp_bare_*` ошибочно включал имя
   footprint'а — 1496 мусорных флагов; комментарий `#` только в начале строки) и дополнен статистикой
   чисел/строк/имён свойств/последовательностей, JSON пересобран (`build_token_json.py`).
2. **Файлы с начальными комментариями:** 0 во всех библиотеках и фикстурах.
3. **Пригодность реальных файлов для парсеров разных версий** (`accept_check.py`, проверка по именам
   дочерних узлов footprint/pad/графики/текста/property/effects/model/stroke против `case T_*`
   соответствующих функций): v6.0.0 и v7.0.0 принимаются всеми парсерами 6.0…master; v8.0.0 — 8.0+
   (P6/P7 отвергают `generator_version` 1377, `uuid` у pad 24 443, `property` с детьми 6885, …);
   v9.0.0 — 9.0+ (P8 отвергает `embedded_fonts` 1860, `solder_paste_margin_ratio` 1); master — только PM
   (P9 отвергает `duplicate_pad_numbers_are_jumpers` 4882, `point` 369).
4. **Отсутствие сетей у pad в библиотеках:** 0 pad с `net` во всех пяти наборах (флаг `pad_with_net` пуст).
5. **Формы `fill`** по наборам (файлов): `none` 1/96/99/403/0, `solid` 0/0/347/925/0, `yes` 0/5/5/393/1792
   (с примитивами pad), `no` 0/0/0/473/3919 (`fixture_stats.py`).
6. **Кавычки у слоёв:** v6.0.0 — 72 677 `layer` и 55 404 `layers` без кавычек, 77 в кавычках (3 файла
   KiCad 6-nightly); v7.0.0 — `layer` 72 831 в кавычках / 447 без; `layers` 37 038 / 21 441; v8+ — 100 %
   в кавычках. Найдено имя `Rescue` (1 файл v9) и `F&B.Cu` (1 файл v9).
7. **Длинные дроби** (`longnum.py`): > 6 знаков только у `roundrect_rratio` (8/148/155 атомов в
   v8/v9/master), `offset/xyz` (3 в v9) и `fp_arc/angle` (2 в v6.0.0).
8. **Экспонента в числе** — только `tedit 5E888720` (по 1 файлу в v6.0.0/v7.0.0).
9. **Сравнение наборов `case T_*`** по функциям P6/P7/P8/P9/PM (`parser_funcs.py`) — таблица «появился» в
   §5, §9, §13 выведена из него и вычитана по коду.
10. Все утверждения §1–§13 о поведении парсера сверены с исходным кодом по указанным строкам (чтение кода,
    не запуск KiCad).

## 17. Открытые вопросы

1. **Реальная загрузка в KiCad не выполнялась** — выводы о принятии/отказе сделаны по коду парсера.
   Желательно подтвердить сценарий 3 (§2.1) запуском `kicad-cli fp upgrade`/открытием библиотеки
   в KiCad 8/9, если он доступен.
2. Что KiCad делает с данными **после** закрывающей скобки корня (второй корневой список, мусор) — не
   проверено (§4).
3. Поведение «нестрогого» разбора `padstack (layer … (<неизвестное> …))` в 9.0 (`continue` без пропуска
   вложенных скобок, P9:5987–5989) — не проверено; вероятно, ломает разбор при вложенных списках.
4. Точные правила `ConvertToNewOverbarNotation` для `version < 20210606` (какие `~` считаются
   надчёркиванием) — не изучены; для round-trip текст хранится сырым, для отображения нужно отдельно.
5. `m_undefinedLayers` для footprint'а, открытого в редакторе footprint'ов (а не в библиотечном кэше), —
   не проверено, показывает ли KiCad предупреждение о слое `Rescue`.
6. master — движущаяся цель: снимок парсера скачан 2026-09-27 (`SEXPR_BOARD_FILE_VERSION` 20260901);
   библиотека master записана версией 20260206. Список §5.1 может устареть.
7. Парсеры 6.0/7.0 изучены выборочно (то, что нужно для совместимости §13); полная таблица их форм —
   не составлялась.
