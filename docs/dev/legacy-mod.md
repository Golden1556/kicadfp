# Преобразование библиотек PCBNEW-LibModule-V1 (`.mod`/`.emp`) в модель footprint

Спецификация модуля `kicadfp.legacy` (см. `architecture.md` §8). Документ описывает, **как
современный KiCad 9.0 читает старый формат** и во что превращает каждую строку, чтобы
конвертер kicadfp давал тот же результат (эталон), и отдельно перечисляет места, где KiCad
теряет или искажает данные, с рекомендациями для kicadfp.

Все утверждения подтверждены ссылками `файл:строка`. Если не сказано иное, строки относятся к
ветке **9.0** репозитория `gitlab.com/kicad/code/kicad`. Сокращения:

| Сокр. | Файл в репозитории KiCad (ветка 9.0, если не указано) |
|---|---|
| `L9` | `pcbnew/pcb_io/kicad_legacy/pcb_io_kicad_legacy.cpp` |
| `L9h` | `pcbnew/pcb_io/kicad_legacy/pcb_io_kicad_legacy.h` |
| `Lm` | то же, ветка `master` (KiCad 10-dev) |
| `S9` | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp` (writer) |
| `S9h` | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.h` |
| `P9` | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp` |
| `MGR` | `pcbnew/pcb_io/pcb_io_mgr.cpp` |
| `FP` | `pcbnew/footprint.cpp`; `FPh` — `pcbnew/footprint.h` |
| `PAD` | `pcbnew/pad.cpp`; `PADh` — `pcbnew/pad.h`; `PSh` — `pcbnew/padstack.h` |
| `BI` | `pcbnew/board_item.cpp` |
| `PT` / `PF` | `pcbnew/pcb_text.cpp` / `pcbnew/pcb_field.cpp` |
| `ES` | `common/eda_shape.cpp`; `ESh` — `include/eda_shape.h` |
| `ET` | `common/eda_text.cpp`; `ETh` — `include/eda_text.h` |
| `SU` | `common/string_utils.cpp`; `SUh` — `include/string_utils.h` |
| `RIO` | `common/richio.cpp` |
| `EU` | `common/eda_units.cpp` |
| `TR` | `libs/kimath/src/trigo.cpp`; `EA` — `libs/kimath/include/geometry/eda_angle.h` |
| `LID` | `common/layer_id.cpp`; `LIDh` — `include/layer_ids.h`; `LS` — `common/lset.cpp` |
| `BU` | `include/base_units.h`; `MU` — `libs/kimath/include/math/util.h` |
| `TF` | `common/template_fieldnames.cpp` |
| `L40` | `pcbnew/legacy_plugin.cpp`, ветка **4.0** (для справки о писателе «Units mm») |
| `bzr/…` | снапшот KiCad 2011 (bzr2986), `…/Telegram Desktop/bzr2986/…` — писатель формата |

Фикстура: `tests/fixtures/legacy_mod/My_lib.mod` (3 модуля `dip14`, `mlt`, `snp8`, deci-mils,
CRLF). Реальный корпус для проверок: 96 файлов `modules/*.mod` из
`github.com/KiCad/kicad-library` на коммите `188a0c5e` (2013 г.), 1518 модулей (§19).

---

## 1. Кратко (ключевые факты)

1. KiCad 9 конвертирует библиотеку так: `PCB_IO_MGR::ConvertLibrary` → `FootprintEnumerate`
   → для каждого имени `FootprintLoad` (копия через `Duplicate()`) → `PCB_IO_KICAD_SEXPR::FootprintSave`
   (`MGR:191-252`). Тот же путь использует `kicad-cli fp upgrade <lib.mod> --output <dir.pretty>`
   (`pcbnew/pcbnew_jobs_handler.cpp:1707-1795`).
2. Единицы: по умолчанию 1 ед. = 1/10000 дюйма = **2540 нм** (`L9:2938`,
   `IU_PER_MILS = 1e6*0.0254 = 25400.0`, `BU:70,83`); строка `Units mm` в заголовке (до `$INDEX`)
   переключает на мм: 1 ед. = 1 000 000 нм (`L9:3056-3062`). Любое число → `KiROUND(v*k)` нм
   (`L9:2876-2881`, `MU:100-103`). Углы всегда в 0.1° (`L9:2885-2917`).
3. `512 → 1300480 нм → "1.30048"`, `315 → "0.8001"`, `984 → "2.49936"` — подтверждено (§5.3).
4. Координаты `Po` модуля, `Po` площадок, `T*`, `D*` в файле — **относительно якоря при
   ориентации модуля 0**; углы площадок (`Sh`) и текстов (`T*`) — **абсолютные** (экранные).
   При сохранении KiCad обнуляет ориентацию модуля, поэтому в результате:
   координаты = значения из файла, угол площадки/текста = (угол из файла − ориентация модуля)
   mod 360 (§8).
5. Маска слоёв площадки `At … N <hex>` → набор слоёв `leg_mask2new` (`L9:367-385`), затем
   `PAD::SetAttribute` может его изменить (SMD/CONN — оставить ≤1 медный слой) (`PAD:923-974`).
   `00E0FFFF` → `"*.Cu" "*.Mask" "F.SilkS"`; `00888000` (SMD) → `"F.Cu" "F.Mask" "F.Paste"`;
   `00808000` → `"F.Cu" "F.Mask"`; `00E00001` (HOLE) → `"*.Mask" "B.Cu" "F.SilkS"` (§6.3).
6. Дуга `DA cx cy sx sy angle w layer`: конец = начало, повёрнутое вокруг центра на `angle`
   **по часовой стрелке на экране** (ось Y вниз); при `angle < 0` начало и конец меняются
   местами; середина считается из (start, end, center) (§10.3).
7. `T0` → `(property "Reference" …)`, `T1` → `(property "Value" …)`, `T2+` → `fp_text user`;
   невидимый `T2+` → `(property "" …)` с **пустым именем** (`L9:1244-1249`). Размер в файле
   записан как `высота ширина` и в `(size …)` попадает **в том же порядке** (§9).
8. Теряется: цепи площадок (`Ne`), `Op` (стоимость автоплэйсмента), `AR`, `Sc`, время правки,
   флаги locked/placed (из-за ошибки разбора `Po`, §7.2), признак заливки полигонов `DP`,
   корректные единицы смещения 3D-модели (`Of` в дюймах записывается как мм, §12).
9. Имя файла результата: имя из `$MODULE` → `StrPurge` → символы `\/:"<>|*?` заменяются на
   `%xx` (`L9:3116-3120`, `SUh:260`, `SU:1267-1294`) → `<имя>.kicad_mod`; дубликаты имён
   получают суффикс `_v2`, `_v3`… (`L9:3145-3183`).
10. Все UUID новые (`FP:2672-2682`); `tedit`/время правки не пишутся; uuid самого footprint
    в библиотечный файл не пишется (`S9h:191`, `CTL_OMIT_UUIDS`).

---

## 2. Конвейер KiCad 9

| Шаг | Что делает | Где |
|---|---|---|
| Определение типа | по расширению файла: `mod`, `emp` (без учёта регистра) | `L9h:77`, `common/io/io_base.cpp:71-86`, `MGR:136-157` |
| `FootprintEnumerate(bestEfforts=false)` | `init()`, `cacheLib()` → `LP_CACHE::Load()`; имена — ключи `boost::ptr_map<std::string>` (порядок — побайтовая сортировка) | `L9:3210-3234`, `L9:2959`, `L9:3026-3041` |
| Ошибка разбора | исключение `IO_ERROR`; при `bestEfforts=false` — ConvertLibrary возвращает `false`, **ни один файл не пишется** | `L9:3228-3233`, `MGR:218-250` |
| `GetEnumeratedFootprint` → `FootprintLoad` | копия из кэша `Duplicate()` (новые KIID всем), `SetParent(nullptr)` | `pcbnew/pcb_io/pcb_io.cpp:127-133`, `L9:3237-3255` |
| `FootprintSave` | `SetOrientation(ANGLE_0)`; если слой ≠ F.Cu — `Flip()`; запись через кэш `.pretty` | `S9:2893-2984` |
| Ошибка сохранения одного footprint | пропускается с предупреждением `Footprint "%s" can't be saved. Skipped` | `MGR:227-240` |
| Форматирование | `format(FOOTPRINT)` + `KICAD_FORMAT::Prettify` (стиль KiCad 9, табы) | `S9:1083-1343` |

Параметры загрузчика для библиотек: `m_loading_format_version = 0`, `m_cu_count = 16`,
`m_board = nullptr` (`L9:2920-2940`, `L9:3296-3306`).

---

## 3. Лексика файла

### 3.1 Строки

* Чтение — `FILE_LINE_READER::ReadLine`: строка заканчивается на `\n` (включительно), `\r`
  остаётся в строке, фильтра комментариев **нет** (`RIO:249-280`, `L9:3026-3031`). CRLF
  допустим: `\r` входит в набор разделителей `" \t\r\n"` (`L9:198`).
* После конца файла текущая строка пуста (`RIO:273-279`).
* Строки `# …` (например `# encoding utf-8`) ничем не распознаются и игнорируются.
* Макрос `TESTLINE(x)`: `strncasecmp(line, x, len(x)) == 0` **и** следующий символ ∈
  `{' ', '\t', '\r', '\n', '\0'}` (`L9:201,231`; `strchr(delims, 0)` находит терминатор,
  поэтому конец строки тоже «пробел»). Сравнение ключевых слов **без учёта регистра**.
* `TESTSUBSTR(x)`: только префикс без учёта регистра (`L9:234`).
* UTF-8 BOM в начале файла не обрабатывается: первая строка не пройдёт
  `TESTLINE("PCBNEW-LibModule-V1")` → ошибка «not a legacy library» (`L9:3052-3053`).

### 3.2 Числа

| Функция | Семантика | Где |
|---|---|---|
| `biuParse` | `strtod` (пропуск ведущих пробелов; допускает `1e-3` и т.п.), `KiROUND(v * diskToBiu)`; нет числа → исключение «Missing floating point number» | `L9:2846-2882` |
| `degParse` | `strtod`, `EDA_ANGLE(v, TENTHS_OF_A_DEGREE_T)` = `v/10` градусов | `L9:2885-2917`, `EA:46-61` |
| `intParse` | `strtol(…, 10)`, нет числа → 0 | `L9:394-398` |
| `hexParse` | `strtoul(…, 16)`, `uint32_t` | `L9:407-410` |
| `KiROUND` | `v<0 ? (int)(v-0.5) : (int)(v+0.5)` — половина от нуля | `MU:100-103` |

### 3.3 Строка в кавычках — `ReadDelimitedText`

`SU:410-452` (wxString-версия, для текстов) и `SU:455-497` (char-буфер, для `Sh`, `Na`, `Ne`):

1. Пропустить всё до первой `"`; копировать до следующей неэкранированной `"`.
2. `\"` → `"`, `\\` → `\`; **любой другой** `\X` копируется как два символа `\X`.
3. Возвращает число прочитанных байт (позиция после закрывающей кавычки).
4. Результат — UTF-8 → wxString (`From_UTF8`; при невалидном UTF-8 — локаль, затем 8-битная
   копия, `SU:1432-1446`).

`Cd`, `Kw`, имя `$MODULE` читаются **без** разбора кавычек: `StrPurge` (обрезка
` \t\n\r\f\v` с обеих сторон, `SU:755-770`) остатка строки после ключевого слова.

### 3.4 Кодировка

Строки считаются UTF-8 (`From_UTF8`). Номера площадок в библиотеках — тоже UTF-8, т.к.
`m_loading_format_version == 0` ≠ 1 (`L9:1434-1449`, `L9:2922`). Для kicadfp: декодировать
UTF-8; при ошибке — `latin-1` (эквивалент `From8BitData`) с предупреждением.

---

## 4. Структура файла библиотеки

```
PCBNEW-LibModule-V1  <дата>        ← заголовок (дата не разбирается)
# encoding utf-8                   ← игнорируется
Units mm                           ← необязательно; только до $INDEX
$INDEX
<имя>                              ← содержимое индекса игнорируется
$EndINDEX
$MODULE <имя>
…
$EndMODULE <имя>                   ← имя после $EndMODULE не проверяется
$MODULE …
…
$EndLIBRARY                        ← не проверяется
```

| Этап | Поведение KiCad 9 | Где |
|---|---|---|
| Заголовок | первая строка: `TESTLINE("PCBNEW-LibModule-V1")`; пустой файл → «File '%s' is empty.»; иначе → «File '%s' is not a legacy library.» | `L9:3043-3053` |
| `ReadAndVerifyHeader` | читает строки до `$INDEX`; `Units`: первый токен после слова; ровно `mm` (регистр важен, `strcmp`) → `diskToBiu = 1e6`; иначе остаётся 2540 | `L9:3055-3069` |
| **Нет `$INDEX`** | заголовочный цикл дочитывает файл до конца → **0 модулей, без ошибки** (проверено эмуляцией, §19) | `L9:3055-3069`, `L9:3103-3125` |
| `SkipIndex` | пропуск до `$EndINDEX`; если сразу после него снова `$INDEX` — пропуск и его (обход старой ошибки) | `L9:3072-3100` |
| `LoadModules` | просматривает **все** оставшиеся строки; каждая `TESTLINE("$MODULE")` → новый footprint; всё остальное (включая `$EndLIBRARY`, мусор между модулями) игнорируется | `L9:3103-3125` |
| Имя модуля | `StrPurge(line + 7)` → пробелы внутри имени сохраняются (`$MODULE a b` → `a b`) | `L9:3116` |
| Недопустимые символы имени | `ReplaceIllegalFileNameChars(&name)` с `aReplaceChar = 0` → каждый символ из `\/:"<>|*?` заменяется на `%` + 2 hex-цифры в нижнем регистре (`/` → `%2f`, `:` → `%3a`, `"` → `%22`) | `L9:3117-3120`, `SU:49`, `SU:1267-1294`, `SUh:260` |
| FPID | `LIB_ID("", name)` — без проверки и исправления символов | `L9:3123`, `common/lib_id.cpp:92-96` |
| Дубликаты имён | второй и последующие получают имя `<имя>_v2`, `_v3`, … (первый свободный) | `L9:3145-3183` |
| Строка `Li` | не обрабатывается (имя берётся только из `$MODULE`) | `L9:1200-1375` (нет ветки `Li`) |
| `.emp` | тот же формат (один модуль), тот же загрузчик | `L9h:77` |

Реальные примеры (корпус §19): 3 имени с пробелами
(`Potentiometer_WirePads_large Pads_RevA_30July2010`), 1 имя со слэшем `SMDHD/VF` →
`SMDHD%2fVF`.

---

## 5. Единицы и числа

### 5.1 Масштаб

| Режим | Признак | 1 ед. файла | Где |
|---|---|---|---|
| deci-mils (по умолчанию) | нет строки `Units` | `IU_PER_MILS/10 = 2540.0` нм = 0.00254 мм | `L9:2938`, `BU:83` |
| мм | `Units mm` до `$INDEX` | `IU_PER_MM = 1e6` нм | `L9:3060-3061` |

`Units mm` писал `LP_CACHE::SaveHeader` плагина LEGACY (`L40:4541-4546`, в 4.0 код уже под
`#if 0`); значения в таком файле — десятичные мм (`%.10g`), углы — по-прежнему в 0.1°
(`L40:3208-3216`). В корпусе §19: 14 из 96 файлов с `Units mm` (датированы 2012–2013).

Все длины (`Po`, размеры, толщины, сверло, смещения, `.SolderMask` и т.п.) проходят `biuParse`.
Исключение: коэффициент `.SolderPasteRatio` (безразмерный, `atof`), углы (`degParse`/`intParse`)
и числа `$SHAPE3D` (§12).

### 5.2 Вывод в мм

Нанометры → строка: `FormatInternalUnits` (`EU:170-200`): `v = nm/1e6`; если `v≠0` и
`|v| ≤ 0.0001` — `"%.10f"` с удалением хвостовых нулей и точки; иначе `"%.10g"`.
Углы: `"%.10g"` от градусов (`EU:162-167`). Безразмерные (`solder_paste_margin_ratio`,
числа `model`): `FormatDouble2Str` — как выше, но `"%.16f"` для малых (`SU:1372-1399`).

### 5.3 Контрольные значения (deci-mils → нм → мм)

| Файл | нм | Вывод | Файл | нм | Вывод |
|---|---|---|---|---|---|
| 512 | 1300480 | `1.30048` | 1969 | 5001260 | `5.00126` |
| 315 | 800100 | `0.8001` | 2953 | 7500620 | `7.50062` |
| 984 | 2499360 | `2.49936` | 3445 | 8750300 | `8.7503` |
| 1476 | 3749040 | `3.74904` | 3937 | 9999980 | `9.99998` |
| 394 | 1000760 | `1.00076` | 4921 | 12499340 | `12.49934` |
| 59 | 149860 | `0.14986` | 5413 | 13749020 | `13.74902` |
| 295 | 749300 | `0.7493` | 5906 | 15001240 | `15.00124` |
| 492 | 1249680 | `1.24968` | 1181 | 2999740 | `2.99974` |

Для целых deci-mils результат всегда точный: `n·2540` нм (2540.0 представимо точно; проверено:
`1e6*0.0254 == 25400.0`).

---

## 6. Слои

### 6.1 Номер слоя → имя (`leg_layer2new`, `L9:311-364`; номера `L9:102-136`)

| Legacy № | Имя KiCad 9 | Legacy № | Имя KiCad 9 |
|---|---|---|---|
| 0 | `B.Cu` | 20 | `B.SilkS` |
| 1…14 | `In(15−n).Cu`: 1→`In14.Cu` … 14→`In1.Cu` | 21 | `F.SilkS` |
| 15 | `F.Cu` | 22 | `B.Mask` |
| 16 | `B.Adhes` | 23 | `F.Mask` |
| 17 | `F.Adhes` | 24 | `Dwgs.User` |
| 18 | `B.Paste` | 25 | `Cmts.User` |
| 19 | `F.Paste` | 26 | `Eco1.User` |
|  |  | 27 | `Eco2.User` |
|  |  | 28 | `Edge.Cuts` |
| 29 и больше (и отрицательные через `unsigned`) | `Cmts.User` | | |

Внутренние: `BoardLayerFromLegacyId(cu_count − 1 − n)` при `cu_count = 16`
(`L9:334-342`, `LID:215-227`: id 1…30 → `In1_Cu + (id−1)·2`).

### 6.2 Маска → набор слоёв (`leg_mask2new`, `L9:367-385`)

```
если (mask & 0x0000FFFF) == 0x0000FFFF:
    набор = все 32 медных слоя (LSET::AllCuMask(), LS:591-596, MAX_CU_LAYERS=32 LIDh:176)
    mask &= ~0x0000FFFF
для i = 0, 1, …, пока mask ≠ 0:  если бит i — добавить leg_layer2new(i)
```

Частичная медь (например `00008001`) даёт только перечисленные слои (`F.Cu`, `B.Cu`, `In*.Cu`).

### 6.3 Коррекция по типу площадки — `PAD::SetAttribute` (`PAD:923-974`)

Вызывается **после** `SetLayerSet` (`L9:1512-1513`). Новая площадка уже имеет тип PTH
(`PAD:93`), поэтому для `STD` (и неизвестных, см. §11.3) коррекции **нет** (ветка
выполняется только при смене типа, `PAD:925`).

| Тип | Эффект |
|---|---|
| `thru_hole` (STD/прочее) | ничего |
| `smd`, `connect` | если медных слоёв > 1: оставить `B.Cu`, если он есть, иначе медный слой с наименьшим id (`F.Cu`=0, `In1.Cu`=4, …; `LS:310-323`); **сверло := (0,0)** (смещение `offset` сохраняется) |
| `np_thru_hole` (HOLE) | номер := `""`; слои не меняются |

### 6.4 Запись `(layers …)` (`S9:1345-1429`, библиотека: `m_board == nullptr`)

1. Если есть все 32 медных → `"*.Cu"`; иначе если медь ровно `{F.Cu, B.Cu}` → `"*.Cu"`.
2. Пары → `"*.Adhes"`, `"*.Paste"`, `"*.SilkS"`, `"*.Mask"`, `"*.CrtYd"`, `"*.Fab"` (в этом порядке).
3. Остальные слои по одному в порядке числового `PCB_LAYER_ID` (`LIDh:64-124`:
   `F.Cu`0 `F.Mask`1 `B.Cu`2 `B.Mask`3 `In1.Cu`4 `F.SilkS`5 `In2.Cu`6 `B.SilkS`7 … `F.Adhes`9
   `B.Adhes`11 `F.Paste`13 `B.Paste`15 `Dwgs.User`17 `Cmts.User`19 `Eco1.User`21 `Eco2.User`23
   `Edge.Cuts`25 …). Все имена — в кавычках.

### 6.5 Таблица масок (результат `(layers …)` после §6.2–6.4)

| Маска | STD → thru_hole | SMD → smd | CONN → connect | HOLE → np_thru_hole |
|---|---|---|---|---|
| `00E0FFFF` | `"*.Cu" "*.Mask" "F.SilkS"` | `"*.Mask" "B.Cu" "F.SilkS"` | как SMD | `"*.Cu" "*.Mask" "F.SilkS"` |
| `00808000` | `"F.Cu" "F.Mask"` | `"F.Cu" "F.Mask"` | `"F.Cu" "F.Mask"` | `"F.Cu" "F.Mask"` |
| `00888000` | `"F.Cu" "F.Mask" "F.Paste"` | `"F.Cu" "F.Mask" "F.Paste"` | то же | то же |
| `00E00001` | `"*.Mask" "B.Cu" "F.SilkS"` | то же | то же | `"*.Mask" "B.Cu" "F.SilkS"` |
| `0000FFFF` | `"*.Cu"` | `"B.Cu"` | `"B.Cu"` | `"*.Cu"` |
| `00008001` | `"*.Cu"` (пара F/B) | `"B.Cu"` | `"B.Cu"` | `"*.Cu"` |
| `0088FFFF` | `"*.Cu" "F.Mask" "F.Paste"` | `"F.Mask" "B.Cu" "F.Paste"` | как SMD | `"*.Cu" "F.Mask" "F.Paste"` |
| `00F0FFFF` | `"*.Cu" "*.SilkS" "*.Mask"` | `"*.SilkS" "*.Mask" "B.Cu"` | как SMD | `"*.Cu" "*.SilkS" "*.Mask"` |
| `00888002` | `"F.Cu" "F.Mask" "F.Paste" "In14.Cu"` | `"F.Cu" "F.Mask" "F.Paste"` | как SMD | как STD |
| `00000000` | `(layers)` пусто | пусто | пусто | пусто |

Примечания. В KiCad 2011 маски по умолчанию: STD `00E0FFFF`, SMD `00808000`(!), CONN
`00888000`, HOLE `00E00001` (`bzr/pcbnew/class_pad.h:15-27`); при этом диалог 2011 выдавал
SMD/CONN маски «наоборот» (см. `kicad-2011-gen/docs/pcbnew-pad-format.md` §3.4). Конвертер
маску **не** «чинит» — берёт биты как есть. Частоты в реальном корпусе — §19.

---

## 7. Блок `$MODULE` построчно (`loadFOOTPRINT`, `L9:1200-1380`)

Порядок проверок важен (первое совпадение выигрывает): `D[SCAP]` → `$PAD` → `T*` → `Po` →
`Sc` → `Op` → `At` → `AR` → `$SHAPE3D` → `Cd` → `Kw` → `.SolderPasteRatio` → `.SolderPaste` →
`.SolderMask` → `.LocalClearance` → `.ZoneConnection` → `.ThermalWidth` → `.ThermalGap` →
`$EndMODULE`. Прочие строки (`Li`, `Dl` вне `DP`, комментарии, неизвестные) игнорируются.
Нет `$EndMODULE` до конца файла → исключение «Missing '$EndMODULE' for MODULE '%s'.»
(`L9:1377-1379`) → конвертация всей библиотеки неуспешна (§2).

| Строка | Формат (2011: `bzr/pcbnew/class_module.cpp:259-357`) | KiCad 9 | Результат в `.kicad_mod` |
|---|---|---|---|
| `Po` | `Po x y orient layer edittime(hex) timestamp(hex) status` | §7.2 | слой → `(layer …)` (см. §8.3); позиция/ориентация — §8 |
| `Li` | `Li <имя>` | игнор | — |
| `Cd` | `Cd <текст до конца строки>` | `SetLibDescription(StrPurge(rest))`, без разэкранирования (`L9:1316-1320`) | `(descr "…")` если не пусто (`S9:1134-1135`) |
| `Kw` | `Kw <текст>` | `SetKeywords(StrPurge(rest))` (`L9:1321-1324`) | `(tags "…")` если не пусто (`S9:1137-1138`) |
| `Sc` | `Sc <hex>` | UUID footprint (затем заменяется, §13) (`L9:1279-1283`) | — |
| `AR` | `AR <путь>` | `SetPath` (`L9:1304-1311`) | не пишется в библиотеку (`CTL_OMIT_PATH`, `S9h:191`) |
| `Op` | `Op <rot90 hex> <rot180 hex> 0` | читается и отбрасывается (`L9:1284-1288`) | — (`autoplace_cost*` KiCad 9 не пишет; парсер 9 их игнорирует `P9:4683-4687`) |
| `At` | `At [SMD] [VIRTUAL]` | §7.3 | `(attr …)` |
| `.SolderMask v` | длина | `SetLocalSolderMaskMargin` (`L9:1346-1350`) | `(solder_mask_margin v)` (`S9:1183-1187`) |
| `.SolderPaste v` | длина | `SetLocalSolderPasteMargin` (`L9:1341-1345`) | `(solder_paste_margin v)` (`S9:1189-1193`) |
| `.SolderPasteRatio r` | число | `atof`, затем ограничение в `[-0.5, 0]` (`L9:1325-1340`) | `(solder_paste_margin_ratio r)` (`FormatDouble2Str`, `S9:1195-1199`) |
| `.LocalClearance v` | длина | `SetLocalClearance` (`L9:1351-1355`) | `(clearance v)` (`S9:1201-1205`) |
| `.ZoneConnection n` | целое | `SetLocalZoneConnection((ZONE_CONNECTION)n)` (`L9:1356-1360`) | `(zone_connect n)` если `n ≠ -1` (INHERITED) (`S9:1207-1211`) |
| `.ThermalWidth v`, `.ThermalGap v` | длина | разбирается и **отбрасывается** (`L9:1361-1370`) | — |
| `T<n> …` | текст | §9 | `property`/`fp_text` |
| `DS/DC/DA/DP …` | графика | §10 | `fp_line/fp_circle/fp_arc/fp_poly` |
| `$PAD … $EndPAD` | площадка | §11 | `pad` |
| `$SHAPE3D … $EndSHAPE3D` | 3D | §12 | `model` |
| `$EndMODULE [имя]` | конец | выход (`L9:1371-1374`) | — |

Строки `.SolderMask` и т.п. пишутся (и в 2011, и в 4.x) только при ненулевом значении
(`bzr/pcbnew/class_module.cpp:299-306`, `L40:3832-3853`), но если строка есть со значением 0,
KiCad 9 всё равно запишет токен со значением `0` (значение становится `optional` с
содержимым).

### 7.1 Замечание про ключевые слова

`.SolderPasteRatio` проверяется раньше `.SolderPaste`, но даже иначе конфликта нет: `TESTLINE`
требует разделитель сразу после ключа.

### 7.2 Строка `Po` модуля (`L9:1251-1278`)

```
x = biuParse, y = biuParse, orient = intParse (0.1°), layer = intParse,
edittime = hexParse (не используется),
uuid   = strtok_r(data, " \t\r\n", &data)             → KIID(uuid)
status = strtok_r(data + 1, " \t\r\n", &data)          ← ВНИМАНИЕ: data+1
locked = status && status[0]=='F';  placed = status && status[1]=='P'
SetPosition(x,y); SetLayer(leg_layer2new(layer)); SetOrientation(orient/10 °)
```

* `orient` читается **целым** (`intParse`): дробная часть в файлах `Units mm` отбрасывается
  (например `450.5` → 45.0°).
* **Ошибка KiCad 9**: после `strtok_r` указатель `data` уже стоит на первом символе статуса,
  а `data + 1` пропускает его. При обычной записи `… 00000000 ~~` (один пробел; формат
  `bzr/pcbnew/class_module.cpp:279-282`, `L40:3807-3813`) токен статуса начинается со
  **второго** символа: `F~` → `~` (locked=false), `FP` → `P` (locked=false, placed=false),
  `~F` → `F` (locked=true). В итоге флаги locked/placed из библиотеки фактически
  **теряются** (проверено эмуляцией, §19; вывод по коду, прогоном KiCad не проверено).
* В корпусе §19: 1 модуль со статусом `F~` (`BUSPCI`).

### 7.3 Атрибуты `At` (`L9:1289-1303`)

| Содержимое строки после `At` (поиск подстроки, регистр важен) | Атрибуты | `(attr …)` |
|---|---|---|
| содержит `SMD` (даже вместе с `VIRTUAL`) | `FP_SMD` | `(attr smd)` |
| иначе содержит `VIRTUAL` | `FP_EXCLUDE_FROM_POS_FILES \| FP_EXCLUDE_FROM_BOM` | `(attr exclude_from_pos_files exclude_from_bom)` |
| иначе (например `At ` пусто) | `FP_THROUGH_HOLE \| FP_EXCLUDE_FROM_POS_FILES` | `(attr through_hole exclude_from_pos_files)` |
| строки `At` нет | 0 (`FP:77`) | токен `attr` **не пишется** (`S9:1214`) |

Порядок слов в `(attr …)`: `smd`, `through_hole`, `board_only`, `exclude_from_pos_files`,
`exclude_from_bom`, … (`S9:1214-1240`). Писатель 2011 не пишет `At` для обычных (сквозных)
модулей (`bzr/pcbnew/class_module.cpp:309-317`) — поэтому у большинства старых модулей
`attr` в результате отсутствует (в корпусе: 1194 без `At`, 308 `smd`, 16 `VIRTUAL`).

---

## 8. Координаты и ориентация модуля

### 8.1 Загрузка (внутреннее представление KiCad — абсолютные координаты)

* `Po` модуля должен идти раньше элементов (так пишут все писатели); элементы используют
  текущие позицию/ориентацию модуля.
* Площадка `Po x y` → `SetFPRelativePosition`: `abs = R(orient)·(x,y) + pos` (`L9:1534-1543`,
  `BI:348-359`).
* Текст `T` `x y` → то же (`L9:1776`).
* Графика: координаты как в файле, затем `Rotate({0,0}, orient)`, `Move(pos)` (`L9:1722-1723`).
* Угол площадки `Sh …` → `SetOrientation(angle)` — **абсолютный** (`L9:1457`, `PAD:1004-1008`);
  угол текста → `SetTextAngle(angle)` — абсолютный (`L9:1779`). Это совпадает с семантикой
  писателя 2011: угол площадки хранится экранным (`bzr/pcbnew/class_module_transform_functions.cpp:352-358`),
  угол текста пишется как `m_Orient + parent->m_Orient` (`bzr/pcbnew/class_text_mod.cpp:73-79`).

`R(a)` — `RotatePoint` KiCad (`TR:229-264`): для 0/90/180/270° точные перестановки
(`90°: (x,y)→(y,−x)`), иначе `x' = KiROUND(y·sin a + x·cos a)`, `y' = KiROUND(y·cos a − x·sin a)`,
где `sin/cos` точные для кратных 45° (`EA:178-227`). Положительный угол поворачивает
**против часовой стрелки на экране** (ось Y вниз).

### 8.2 Сохранение (`FootprintSave`, `S9:2960-2973`)

`footprint->SetOrientation(ANGLE_0)` поворачивает всех детей вокруг позиции модуля на
`−orient` (`FP:2641-2669`), причём **даже при нулевом изменении** вызываются
`PCB_TEXT::Rotate` (нормализует угол текста в `[0, 360)`, `PT:381-390`) и `PAD::Rotate`
(`PAD:1614-1620`; `PADSTACK::SetOrientation` всегда нормализует в `[0,360)`, `PSh:294-298`).
Писатель выводит координаты относительно позиции модуля (`S9:445-455`, `S9:1492-1495`,
`S9:1966-1975`). Позиция модуля в файл не пишется (`CTL_OMIT_AT`, `S9h:191`).

Итог для конвертера (без промежуточных абсолютных координат):

| Величина | Результат |
|---|---|
| координаты площадок, текстов, графики, точек полигона | значения из файла × масштаб (точно для ориентаций, кратных 90°; для прочих — возможна погрешность ±1 нм от двойного `KiROUND`) |
| угол площадки `(at x y a)` | `a = norm360(Sh_angle − orient)`; при `a == 0` угол не пишется (`S9:1492-1495`) |
| угол текста `(at x y a)` | `a = norm360(T_angle − orient)`; пишется всегда, в т.ч. `0` (`S9:1992-1994`) |
| `norm360` | `while a < 0: a += 360; while a >= 360: a -= 360` (`EA:229-238`) |

Пример (корпус, `muonde.mod`, модуль `C7812`, `Po … 900 …`): `Sh "8" R 236 748 0 0 900` →
`(at -1.905 2.794)` без угла; `T0 … 0 …` → угол 270; `T1 … 1800 …` → угол 90.

### 8.3 Слой модуля ≠ F.Cu

`Po … layer=0 …` → `B.Cu`; `FootprintSave` вызывает `Flip(pos, m_FlipDirection)` (`S9:2965-2973`;
умолчание настройки `TOP_BOTTOM`, `pcbnew/pcbnew_settings.cpp:74`). `FOOTPRINT::Flip` вызывает
`GetBoard()->FlipLayer(…)` (`FP:2510`), а у копии из `FootprintLoad` родителя нет
(`L9:3253`) — поведение **не проверено** (по коду похоже на обращение к `nullptr`). В корпусе
§19 таких модулей нет (все 1518 — слой 15). См. «Открытые вопросы».

---

## 9. Тексты `T<n>` (`L9:1218-1250`, `loadMODULE_TEXT` `L9:1728-1808`)

### 9.1 Формат строки

2011 (`bzr/pcbnew/class_text_mod.cpp:83-94`):
```
T<type> <x> <y> <size_y> <size_x> <angle> <thickness> <M|N> <V|I> <layer> <I|N> "<text>"
```
4.x (`L40:3589-3629`) дописывает после текста ` <H> <V>` (`L`/`C`/`R`, `T`/`C`/`B`), только
если выравнивание не по центру. Очень старые файлы — без пробела перед текстом: `… N"74LS245"`
(`L9:1737-1739`).

### 9.2 Разбор (`L9:1739-1806`)

| Поле | Разбор | Результат |
|---|---|---|
| `type` | `intParse(line+1)` | 0 → поле Reference, 1 → поле Value (повторная `T0`/`T1` перезаписывает), иначе новый `PCB_TEXT` (`L9:1223-1238`) |
| `x y` | `biuParse` ×2 | позиция (§8) |
| `size_y size_x` | `biuParse` ×2 — **сначала высота, потом ширина** | `SetTextSize(VECTOR2I(size_x, size_y))`; в файле результата `(size <высота> <ширина>)` (`ET:1063-1065`) = **те же два числа в том же порядке** |
| `angle` | `degParse` (0.1°) | §8.2 |
| `thickness` | `biuParse`; `< 1` → 0 (`L9:1781`) | `(thickness v)` только если ≠ 0 (`ET:1073-1077`) |
| текст | `ReadDelimitedText` от текущей позиции до первой `"` (§3.3); затем `%V` → `${VALUE}`, `%R` → `${REFERENCE}`, затем `ConvertToNewOverbarNotation` (`L9:1753-1757`) | текст поля |
| `mirror` | 1-й токен `strtok` после толщины; `[0]=='M'` | `(justify … mirror)` (`ET:1096-1111`) |
| `hide` | 2-й токен; `[0]=='I'` → невидим | §9.4 |
| `layer` | 3-й токен `intParse`; нет токена → 21 | §9.3 |
| `italic` | 4-й токен; `[0]=='I'` | `(italic yes)` в `font` (`ET:1082-1083`) |
| `hjust`, `vjust` | 1-й и 2-й токены **после закрывающей кавычки**; точные строки `L`/`R`, `T`/`B`, иначе центр (`L9:263-283`) | `(justify left\|right top\|bottom)` |

Токены `mirror/hide/layer/italic` берутся `strtok` от позиции после толщины, т.е. если поле
отсутствует, «токеном» становится начало текста (например `"U**"`): его первый символ `"` не
равен `M/I`, а `intParse("\"…")` = 0 → слой 0 → по §9.3 станет 20 (`B.SilkS`). Это
поведение KiCad; писатели 2011/4.x всегда пишут все поля.

`ConvertToNewOverbarNotation` (`SU:80-147`): строка `"~"` не меняется; `~~` → `~`
(а `~~{` → `~~{}`); `~{` без предшествующего `~` → вернуть исходную строку без изменений;
иначе одиночная `~` открывает/закрывает надчёркивание: `~X~` → `~{X}`; открытое надчёркивание
закрывается перед пробелом, `}` и `)`; в конце строки — принудительно.

### 9.3 Слой текста (`L9:1795-1806`)

| `layer` из файла | Итоговый legacy № |
|---|---|
| `< 0` | 0 (`FIRST_LAYER`) → `B.Cu` (дальнейшие ветки не выполняются) |
| `> 28` | 28 → `Edge.Cuts` |
| `0` | 20 → `B.SilkS` |
| `15` | 21 → `F.SilkS` |
| `1…14` | 21 → `F.SilkS` |
| `16…28` | как есть (§6.1) |

Это цепочка `if / else if` (`L9:1796-1805`): отрицательный номер заменяется на 0 и дальше не
проверяется, поэтому текст попадает на медный слой `B.Cu` — буквальное поведение кода.

### 9.4 Поля и тексты в результате

| Источник | Объект KiCad 9 | Токен результата |
|---|---|---|
| `T0` | `PCB_FIELD` Reference | `(property "Reference" "<текст>" (at x y a) (layer L) [(hide yes)] (uuid …) (effects …))` |
| `T1` | `PCB_FIELD` Value | `(property "Value" …)` — слой из файла (обычно `F.SilkS`), а не `F.Fab` |
| `T2+`, видимый | `PCB_TEXT` | `(fp_text user "<текст>" (at x y a) (layer L) (uuid …) (effects …))` |
| `T2+`, невидимый | удаляется и превращается в `PCB_FIELD(*text, -1)` c **пустым именем** (`L9:1244-1249`, `PF:42-53`) | `(property "" "<текст>" … (hide yes) …)` — имя `GetCanonicalName()` = `m_name` = `""` (`PF:121-129`, `S9:1146-1148`) |
| нет `T0`/`T1` | поля из конструктора | `(property "Reference" "" …)` / `(property "Value" "" …)`: `at` = якорь, угол 0, слой `F.SilkS`/`F.Fab`, размер 1.27×1.27, толщина 0.15, видимые |
| (всегда) | Datasheet, Description из `FOOTPRINT::addMandatoryFields` (`FP:94-111`) | `(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid …) (effects (font (size 1.27 1.27) (thickness 0.15))))`, то же для `"Description"` |

Значения по умолчанию: размер `DEFAULT_SIZE_TEXT` = 50 mil = 1.27 мм (`ETh:70`, `ET:101-102`),
толщина `DEFAULT_TEXT_WIDTH` = 0.15 мм (`PT:63`, `include/board_design_settings.h:54`),
`KeepUpright = true` (`PT:60`) → токен `(unlocked yes)` **не** пишется (`S9:1996-1997`);
`PCB_FIELD(*text,-1)` копирует атрибуты исходного текста, включая `KeepUpright`
(`PF:42-53`). Поле «Footprint» в KiCad 9 отсутствует (`FP:108`, `P9:4629-4636`).
`Description`-поле **не** заполняется из `Cd` (`FPh:260-264`).

`hide` пишется только для полей (`S9:2001-2002`); у `fp_text` невидимость в KiCad 9
невозможна (поэтому и конвертация в поле).

При повторном чтении такого файла парсер KiCad 9 ищет поле по имени (`P9:4637-4640`), поэтому
несколько полей с именем `""` могут слиться (не проверено). Сам парсер для скрытых `fp_text`
использует имя `Field<N>` (`P9:3421-3427`, `TF:40,78-84`).

### 9.5 Порядок в файле

Поля — в порядке `Reference, Value, Datasheet, Description, <пользовательские>` сразу после
`tags` (`S9:1140-1153`). `fp_text` — среди графики, после всех фигур (§14.2).

---

## 10. Графика `DS`/`DC`/`DA`/`DP` (`loadFP_SHAPE`, `L9:1604-1725`)

### 10.1 Форматы (2011: `bzr/pcbnew/class_edge_mod.cpp:310-361`)

| Строка | Поля | Объект |
|---|---|---|
| `DS x0 y0 x1 y1 w layer` | начало, конец, толщина, слой | `SEGMENT` → `fp_line (start x0 y0) (end x1 y1)` |
| `DC cx cy px py w layer` | центр, точка на окружности | `CIRCLE` → `fp_circle (center cx cy) (end px py)` |
| `DA cx cy sx sy angle w layer` | центр, **начальная точка**, угол 0.1° | `ARC` → `fp_arc (start …) (mid …) (end …)` (§10.3) |
| `DP x0 y0 x1 y1 n w layer` + `n` строк `Dl x y` | первые 4 числа не используются | `POLY` → `fp_poly (pts (xy …)…)` |

Выбор по `line[1]` ∈ `SCAP` (регистр важен; `D` — без учёта регистра, `L9:1210`); неизвестный
второй символ до сюда не доходит.

### 10.2 Общие правила

* Слой: `< 0` или `> 28` → 21 (`F.SilkS`); **медные 0…15 допускаются** (СВЧ-модули)
  (`L9:1716-1717`), далее §6.1.
* Толщина → `STROKE_PARAMS(width, SOLID)` (`L9:1719`) → `(stroke (width w) (type solid))`
  (`common/stroke_params.cpp:280-289`). Нулевая толщина остаётся нулевой (KiCad 9 при чтении
  `.kicad_mod` заменил бы её на 0.1 мм для незалитых фигур, `P9:3242-3246` — при конвертации
  этого нет).
* Заливка: `PCB_SHAPE` создаётся с `FILL_T::NO_FILL` (`pcbnew/pcb_shape.cpp:59-64`), загрузчик
  заливку не меняет → `fp_circle` и `fp_poly` получают `(fill no)` (`S9:1004-1009`).
  **Расхождение со старым KiCad**: в 2011 полигоны модуля рисовались залитыми
  (`bzr/pcbnew/class_edge_mod.cpp:266-267`, `GRPoly(…, TRUE, …)`), и парсер `.kicad_mod`
  KiCad 9 для старых файлов без `fill` считает полигоны вне `Edge.Cuts` залитыми
  (`P9:3224-3238`). См. рекомендацию §16.
* `DP`: ровно `n` строк `Dl`; EOF → «S_POLGON point count mismatch.», не `Dl` →
  «Missing Dl point def.» (`L9:1685-1697`). Точки добавляются через `SHAPE_LINE_CHAIN::Append`
  без дублей подряд: точка, равная предыдущей, отбрасывается; совпадение последней с первой
  сохраняется (`ES:1598-1605`, `libs/kimath/include/geometry/shape_line_chain.h:518-529`).
  Полигон с ≤ 2 точками (после удаления дублей) **не пишется** (`ES:1719-1723`, `S9:971-983`).

### 10.3 Дуга `DA`: точная формула (`L9:1632-1647`, `ES:953-965`, `ES:811-838`)

Входные: центр `C`, начальная точка `S` (нм), угол `θ` (градусы = значение/10).

```
θn  = normalize720(θ)          # while θn < -360: +=360; while θn >= 360: -=360   (EA:279-288)
E   = RotatePoint(S, C, -θn)   # §8.1: поворот на θ по ЧАСОВОЙ стрелке на экране (Y вниз)
если θ < 0:  S, E = E, S       # SetArcAngleAndEnd(angle, aCheckNegativeAngle=true)
# середина (writer вызывает GetArcMid, S9:964-968):
a_s = EDA_ANGLE(S − C); a_e = EDA_ANGLE(E − C)     # atan2 в градусах со спец-случаями (EA:72-110)
если a_e == a_s: a_e = a_s + 360                    # полный круг (θ = ±360)
пока a_e < a_s: a_e += 360
M   = RotatePoint(S, C, -(a_e − a_s)/2)             # KiROUND
вывод: (fp_arc (start S) (mid M) (end E))
```

В координатах файла (x вправо, y вниз): `E = C + [[cos θ, −sin θ], [sin θ, cos θ]]·(S − C)`,
т.е. **положительный угол = по часовой стрелке на экране**. Это совпадает с рисованием в 2011:
`StAngle = ArcTangente(dy, dx)` начальной точки, `EndAngle = StAngle + m_Angle`, дуга
рисуется между ними (`bzr/pcbnew/class_edge_mod.cpp:226-235`, `bzr/common/gr_basic.cpp:1161-1199`).
После перестановки при `θ < 0` дуга в KiCad 9 всегда идёт от `start` к `end` по часовой.

Примеры (центр (0,0), `S` = (1000, 0) deci-mils = (2.54, 0) мм):

| `angle` | start | mid | end |
|---|---|---|---|
| 900 | 2.54 0 | 1.796051 1.796051 | 0 2.54 |
| −900 | 0 −2.54 | 1.796051 −1.796051 | 2.54 0 |
| 450 | 2.54 0 | 2.346654 0.972016 | 1.796051 1.796051 |
| 300 | 2.54 0 | 2.453452 0.6574 | 2.199705 1.27 |
| 1800 | 2.54 0 | 0 2.54 | −2.54 0 |
| −1800 | −2.54 0 | 0 −2.54 | 2.54 0 |
| 3600 | 2.54 0 | −2.54 0 | 2.54 0 |

Фикстура `dip14`: `DA 0 -3445 295 -3445 -1800 59 21` → start `-0.7493 -8.7503`,
mid `0 -9.4996`, end `0.7493 -8.7503` (полуокружность **над** верхней стороной корпуса,
y < −8.7503 — так же рисовал KiCad 2011).

---

## 11. Площадки `$PAD … $EndPAD` (`loadPAD`, `L9:1383-1601`)

Новая площадка: тип PTH, форма circle, размер 60×60 mil, сверло 30 mil, слои `PTHMask()` =
все медные + `F.Mask` + `B.Mask`, позиция = якорь (`PAD:75-115`, `PAD:334-337`). Порядок
строк внутри блока произвольный; неизвестные строки игнорируются; нет `$EndPAD` →
исключение «Missing '$EndPAD'» (`L9:1600`).

### 11.1 `Sh "<номер>" <форма> <sx> <sy> <dx> <dy> <угол>`

| Поле | Разбор | Результат |
|---|---|---|
| номер | `ReadDelimitedText` в буфер 50 байт (≤ 49 байт) с позиции `line+3`; затем пропуск 1 символа и пробелов (`L9:1401-1409`) | `(pad "<номер>" …)`; UTF-8 |
| форма | 1 символ: `C`→`circle`, `R`→`rect`, `O`→`oval`, `T`→`trapezoid`; иное → исключение «Unknown padshape» (`L9:1420-1430`) | 3-й атом `pad` |
| `sx sy` | `biuParse` | `(size sx sy)` |
| `dx dy` | `biuParse` | `(rect_delta dx dy)` только если не (0,0) (`S9:1500-1505`) |
| угол | `degParse`, абсолютный | §8.2 |

2011 писал номер как `%.4s` (≤ 4 символов, `bzr/pcbnew/class_pad.cpp:528-530`); KiCad 9 такого
ограничения не имеет.

### 11.2 `Dr <d> <ox> <oy> [O <dx> <dy>]` (`L9:1459-1487`)

`drill = (d, d)`, `offset = (ox, oy)`; если следующий токен начинается с `O` — сверло
`oval`, `drill = (dx, dy)` (первое число игнорируется). Запись (`S9:1507-1539`):

```
если drill.x>0 или drill.y>0 или offset≠(0,0):
    (drill [oval] [drill.x если >0] [drill.y если >0 и ≠ drill.x] [(offset ox oy) если ≠ (0,0)])
```

Для SMD/CONN сверло обнуляется (§6.3), но `oval` и `offset` сохраняются: например
`Dr 0 0.1 -0.2 O 0.8 1.6` у SMD даёт `(drill oval (offset 0.1 -0.2))` (эмуляция, §19).

### 11.3 `At <тип> N <маска hex>` (`L9:1489-1514`)

| Тип (сравнение `strcmp`, регистр важен) | Результат |
|---|---|
| `SMD` | `smd` |
| `CONN` | `connect` |
| `HOLE` | `np_thru_hole` (номер := `""`) |
| `STD` и **всё прочее** (например `MECA` в корпусе) | `thru_hole` |

Второй токен (`N`) пропускается, третий — маска → §6.2, затем `SetAttribute` → §6.3.
Для `thru_hole` всегда пишется `(remove_unused_layers no)` (`S9:1547-1549`).

### 11.4 Прочие строки площадки

| Строка | KiCad 9 | Результат |
|---|---|---|
| `Ne <код> "<цепь>"` | код в `SetNetCode` (без платы — сирота), имя читается и отбрасывается (`L9:1515-1533`) | **не пишется** (`CTL_OMIT_PAD_NETS`, `S9:1610-1624`) |
| `Po x y` | `SetFPRelativePosition` (`L9:1534-1543`) | `(at x y [угол])` |
| `Le v` | `SetPadToDieLength` | `(die_length v)` если ≠ 0 (`S9:1628-1632`) |
| `.SolderMask v` | `SetLocalSolderMaskMargin` | `(solder_mask_margin v)` |
| `.SolderPaste v` | `SetLocalSolderPasteMargin` | `(solder_paste_margin v)` |
| `.SolderPasteRatio r` | `atof`, **без** ограничения (в отличие от модуля) (`L9:1554-1558`) | `(solder_paste_margin_ratio r)` |
| `.LocalClearance v` | `SetLocalClearance` | `(clearance v)` |
| `.ZoneConnection n` | `SetLocalZoneConnection(n)` | `(zone_connect n)` если ≠ −1 |
| `.ThermalWidth v` | `SetLocalThermalSpokeWidthOverride` | `(thermal_bridge_width v)` |
| `.ThermalGap v` | `SetLocalThermalGapOverride` | `(thermal_gap v)` |
| `$EndPAD` | площадка добавляется, только если `size.x > 0 && size.y > 0`; иначе сообщение «Invalid zero-sized pad ignored» и **пропуск** (`L9:1584-1596`) | — |

Порядок токенов площадки в результате (`S9:1487-1819`):
`(pad "n" type shape (at …) (size …) [rect_delta] [drill] (layers …) [remove_unused_layers]
[die_length] [solder_mask_margin] [solder_paste_margin] [solder_paste_margin_ratio] [clearance]
[zone_connect] [thermal_bridge_width] [thermal_gap] (uuid …))`. Угол спиц
`thermal_bridge_angle` не пишется (значение по умолчанию зависит от формы и совпадает,
`S9:1672-1683`, `pcbnew/padstack.cpp:1287-1303`).

---

## 12. 3D-модели `$SHAPE3D … $EndSHAPE3D` (`load3D`, `L9:1811-1848`)

| Строка | Разбор | Результат |
|---|---|---|
| `Na "<файл>"` | `ReadDelimitedText` в буфер 512 байт | `(model "<файл>" …)` — путь **без изменений** (обычно относительный, например `discret/capacitor/cnp_3mm_disc.wrl`) |
| `Sc x y z` | `sscanf("%lf %lf %lf")` | `(scale (xyz x y z))` |
| `Of x y z` | `sscanf` | `(offset (xyz x y z))` — **число без пересчёта** |
| `Ro x y z` | `sscanf` | `(rotate (xyz x y z))` |
| `$EndSHAPE3D` | модель добавляется | — |

Умолчания: масштаб 1, смещение и поворот 0, видима, непрозрачна. Модель с пустым именем не
пишется (`S9:1310`). Запись (`S9:1304-1338`): `(model "f" (offset (xyz …)) (scale (xyz …))
(rotate (xyz …)))`, числа `FormatDouble2Str`; модели идут **после** `(embedded_fonts no)`.

**Единицы смещения.** В старом формате `Of` — в **дюймах** (2011:
`bzr/pcbnew/export_vrml.cpp:1091` «offset is given inch», `UNITS_3D_TO_PCB_UNITS =
PCB_INTERNAL_UNIT`). S-expr формат хранит мм начиная с `20171114` («Save 3D model offset in mm,
instead of inches», `S9h:75`), а парсер `.kicad_mod` для старого токена `(at (xyz …))` умножает
на 25.4 (`P9:722-736`). Загрузчик `.mod` **не умножает** (`L9:1830-1834`; так же в 5.1/6.0/master)
— после конвертации KiCad 9 смещение уменьшается в 25.4 раза. В корпусе §19: 27 из 510
моделей с ненулевым смещением (например `Of 0 0 -0.033`, `Of 0 0.075 0`).

`master` отличается только строгостью разбора `Sc/Of/Ro` (ошибка при нечисловых данных,
`Lm:1796-1856`).

---

## 13. UUID, время правки, прочее

| Данные | Судьба | Где |
|---|---|---|
| uuid footprint (`Po` 6-е поле, `Sc`) | присваивается при загрузке, затем `Duplicate()` даёт новый; в библиотечный файл uuid footprint не пишется | `L9:1277,1282`, `FP:2672-2682`, `S9:1122-1123`, `S9h:191` |
| uuid детей | все новые случайные (`RunOnDescendants → KIID()`) | `FP:2676-2679` |
| время правки (`Po` 5-е поле) | читается и игнорируется (`[[maybe_unused]]`) | `L9:1260` |
| `tedit` | не пишется (удалён в `20220225`) | `S9h:133` |
| `(version …) (generator "pcbnew") (generator_version "9.0")` | пишутся | `S9:1107-1112`, `S9h:175` (`20241229`) |
| `(locked yes)`, `(placed yes)` | пишутся, если флаги установлены (но см. §7.2) | `S9:1114-1118` |
| `(embedded_fonts no)` | всегда | `S9:1298-1299` |

---

## 14. Выходной файл

### 14.1 Имя

`fpName = ReplaceIllegalFileNameChars(имя, '_')` + `.kicad_mod` (`S9:2927-2931`). Так как имя
после загрузки уже не содержит недопустимых символов (§4), замена на `_` на практике не
срабатывает: `SMDHD/VF` → footprint `"SMDHD%2fVF"`, файл `SMDHD%2fVF.kicad_mod`. Каталог —
выходной путь; `ConvertLibrary` при пути с расширением создаёт подкаталог (`MGR:203-214`).
Существующий файл с тем же именем перезаписывается (`S9:2950-2957`).

### 14.2 Порядок элементов (`S9:1268-1297`)

1. Заголовок, `layer`, `descr`, `tags`, поля (§9.5), локальные параметры, `attr`.
2. Графика и тексты отсортированы `FOOTPRINT::cmp_drawings` (`FP:3774-3848`): тип
   (`PCB_SHAPE_T` < `PCB_TEXT_T`, `include/core_typeinfo.h:88-92`) → id слоя (§6.4) → вид фигуры
   (`SEGMENT`0 < `RECTANGLE`1 < `ARC`2 < `CIRCLE`3 < `POLY`4, `ESh:42-51`) → `start.x`, `start.y`,
   `end.x`, `end.y` (не для полигонов) → центр дуги / вершины полигона → толщина → uuid.
   Т.е. **порядок строк файла не сохраняется**; при полном равенстве решает случайный uuid.
3. Площадки: `FOOTPRINT::cmp_pads` (`FP:3851-3894`): `StrNumCmp(номер)` (натуральное
   сравнение, регистр важен, пустой номер раньше любого, `SU:804-890`) → относительный x → y →
   размеры/форма → набор слоёв → uuid. Поэтому NPTH с номером `""` оказываются **первыми**.
4. `(embedded_fonts no)`, затем модели.

Затем `Prettify` (порт в kicadfp — `sexpr.prettify`, стиль KiCad 8/9, см. `format-layout.md`).

### 14.3 Для kicadfp

Результат строится как footprint версии `DEFAULT_VERSION = 20241229` в структуре §14.2;
отличия от KiCad 9 допустимы только в `(generator "kicadfp")`, `generator_version` и значениях
uuid (архитектура §8). Эталонные файлы §17 сравнивать с нормализацией uuid.

---

## 15. Потери и места, требующие внимания

| Что | Поведение KiCad 9 | Критичность |
|---|---|---|
| `Ne` (цепи площадок) | отбрасываются | норма для библиотеки |
| `Op` | отбрасывается | норма (автоплэйсмент удалён) |
| `AR`, `Sc`, время правки, `Li` | отбрасываются | норма |
| `.ThermalWidth/.ThermalGap` модуля | отбрасываются | низкая |
| locked/placed (`Po` статус) | почти всегда теряются из-за `data+1` (§7.2) | низкая |
| `Of` 3D-модели | дюймы записываются как мм (§12) | **высокая** — смещение модели в 25.4 раза меньше |
| заливка `DP` | `(fill no)` вместо залитого полигона (§10.2) | средняя — меняется вид/плоттинг |
| скрытые `T2+` | `(property "" …)` с пустым именем (§9.4) | средняя (возможна коллизия имён) |
| слой модуля ≠ 15 | `Flip` без платы (§8.3) | не проверено |
| NPTH (`HOLE`) | слои из маски как есть, напр. `"*.Mask" "B.Cu" "F.SilkS"` вместо привычных `"*.Cu" "*.Mask"` | низкая (KiCad допускает) |
| SMD/CONN с многослойной медью | остаётся **B.Cu** (§6.3) | средняя (редко: 6 площадок `0088FFFF` в корпусе) |
| `STD` с неполной медью (`00200001`, `00808000`) | не «дополняется» до всех слоёв | низкая |
| неизвестный тип (`MECA`) | `thru_hole` | низкая |
| ориентация `Po` дробная (`Units mm`) | усекается до целых 0.1° | низкая |
| `.SolderPasteRatio` модуля вне `[-0.5,0]` | зажимается (в т.ч. мусор `3.5468e-315` → `0`) | низкая |
| площадка нулевого размера | удаляется | низкая |
| ошибка разбора любого модуля | вся библиотека не конвертируется | высокая для UX |
| текстовые размеры/толщины | без ограничений (2011 зажимал размер ≥ 50 и толщину ≤ size/4 при чтении, `bzr/pcbnew/class_text_mod.cpp:170-178`) | низкая |
| Datasheet/Description | добавляются пустые скрытые поля | норма |

---

## 16. Рекомендации для реализации `kicadfp.legacy`

### 16.1 API (уточнение `architecture.md` §8)

```python
def is_legacy(text_head: str) -> bool
    # первая строка (без BOM? — см. ниже) начинается с "PCBNEW-LibModule-V1" без учёта регистра
    # и за ним пробел/таб/CR/LF/конец строки
def loads_library(text: str | bytes) -> list[Footprint]      # порядок: сортировка имён по UTF-8 байтам
def read_library(path) -> list[Footprint]
def convert(mod_path, out_dir) -> list[Path]                 # файл на каждый footprint (§14.1)
def legacy_mask_to_layers(mask: int, pad_type: str) -> list[str]
    # §6.2 + §6.3 + §6.4: сразу готовый список для (layers …), с wildcard и в порядке KiCad;
    # pad_type ∈ {"thru_hole","smd","connect","np_thru_hole"}
```

`is_legacy`: KiCad 9 BOM не пропускает; kicadfp может пропускать BOM (`﻿`) — это
расширение, не влияющее на совместимость.

### 16.2 Алгоритм (эквивалент KiCad 9)

```
k = 2540 (нм/ед.)
строки = split по "\n" (оставить "\r" — он разделитель)
проверить заголовок (§4); до "$INDEX": "Units mm" → k = 1e6
пропустить индекс (§4); далее для каждой строки TESTLINE("$MODULE"):
    name = escape_illegal(strip(line[7:]))           # §4, %xx
    fp = новый footprint: pos=(0,0), orient=0, layer=F.Cu, attrs=[],
         поля [Reference(F.SilkS), Value(F.Fab), Datasheet(hidden,F.Fab), Description(hidden,F.Fab)]
    читать до $EndMODULE по таблице §7:
        Po: pos, orient (целое/10), layer; флаги статуса — §7.2 (эмулировать data+1 или не читать)
        T*: §9 (координаты — как в файле; угол = norm360(angle − orient) при сохранении)
        D*: §10 (координаты как в файле; дуга — §10.3)
        $PAD: §11 (угол = norm360(angle − orient))
        $SHAPE3D: §12
    дубликат имени → name + "_vN"
результат каждой fp: версия 20241229, uuid новые, порядок §14.2
```

Поскольку при сохранении ориентация обнуляется, конвертеру **не нужно** вращать координаты:
достаточно вычесть `orient` из углов площадок и текстов. Для полной эквивалентности при
ориентациях, не кратных 90°, KiCad дважды округляет (`KiROUND` при повороте и обратном
повороте) — отличие ≤ 1 нм; kicadfp может этим пренебречь (в корпусе §19 все 7 повёрнутых
модулей кратны 90°).

### 16.3 Где kicadfp может (по решению архитектора) отступить от KiCad 9

| № | Случай | KiCad 9 | Предложение (с предупреждением `Issue`) |
|---|---|---|---|
| D1 | `Of` 3D-модели | копирует число | умножить на 25.4 (единицы — дюймы, §12); код `legacy-model-offset` |
| D2 | `DP` | `(fill no)` | `(fill yes)`, кроме `Edge.Cuts` (как делает парсер KiCad 9 для старых файлов, `P9:3224-3238`) |
| D3 | скрытый `T2+` | `(property "" …)` | имя `Field<N>` как в парсере (`P9:3424`), N = число полей (включая пустой слот Footprint, т.е. 5 для первого) |
| D4 | статус `Po` | почти всегда теряется | читать корректно: `status[0]=='F'` → `(locked yes)`; `placed` в библиотеке не нужен |
| D5 | слой модуля B.Cu | `Flip` (не проверено) | предупреждение `legacy-back-layer`; см. «Открытые вопросы» |

По умолчанию рекомендуется режим **совместимости с KiCad 9** (эталон §17 — именно он); отступления
D1–D5 — опции конвертера. Решение за архитектором (см. «Открытые вопросы»).

### 16.4 Предупреждения (`Issue`)

`legacy-zero-size-pad` (удалена площадка), `legacy-duplicate-name` (переименование `_vN`),
`legacy-name-escaped` (в имени были `\/:"<>|*?`), `legacy-model-offset` (есть ненулевой `Of`),
`legacy-back-layer`, `legacy-hidden-text` (скрытый `T2+`), `legacy-unknown-pad-attr`
(не `STD/SMD/CONN/HOLE`), `legacy-invalid-utf8`.

---

## 17. Эталон: `tests/fixtures/legacy_mod/My_lib.mod`

Файл: 238 строк, все с CRLF (включая последнюю `$EndLIBRARY`), 3798 байт, 1 комментарий `# encoding utf-8`, `$INDEX` (dip14, mlt, snp8),
deci-mils, у всех модулей `Po 0 0 0 15 00000000 00000000 ~~`, `AR `, `Op 0 0 0`, нет `At`,
нет `$SHAPE3D`, нет `T2`. Итог: 3 файла `dip14.kicad_mod` (218 строк), `mlt.kicad_mod` (131),
`snp8.kicad_mod` (173) в стиле KiCad 9. Таблицы — в порядке записи в файл (§14.2).
Во всех трёх: `(layer "F.Cu")`, **нет** `attr`, поля Datasheet/Description как в §9.4.

#### dip14 — `(descr "Корпус К555ТВ6 DIP14") (tags "dip14 K555TB6")`

| # | pad | тип | форма | at (мм) | size | drill | layers |
|---|---|---|---|---|---|---|---|
| 1 | "1" | thru_hole | rect | -3.74904 -7.50062 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 2 | "2" | thru_hole | circle | -3.74904 -5.00126 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 3 | "3" | thru_hole | circle | -3.74904 -2.49936 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 4 | "4" | thru_hole | circle | -3.74904 0 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 5 | "5" | thru_hole | circle | -3.74904 2.49936 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 6 | "6" | thru_hole | circle | -3.74904 5.00126 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 7 | "7" | thru_hole | circle | -3.74904 7.50062 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 8 | "8" | thru_hole | circle | 3.74904 7.50062 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 9 | "9" | thru_hole | circle | 3.74904 5.00126 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 10 | "10" | thru_hole | circle | 3.74904 2.49936 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 11 | "11" | thru_hole | circle | 3.74904 0 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 12 | "12" | thru_hole | circle | 3.74904 -2.49936 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 13 | "13" | thru_hole | circle | 3.74904 -5.00126 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 14 | "14" | thru_hole | circle | 3.74904 -7.50062 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |

| поле | текст | at (мм, угол) | size (h w) | thickness | layer | hide |
|---|---|---|---|---|---|---|
| Reference | "REF**" | 0 -9.99998 0 | 1.00076 1.00076 | 0.14986 | F.SilkS | — |
| Value | "VAL**" | 0 0 90 | 1.00076 1.00076 | 0.14986 | F.SilkS | — |
| Datasheet | "" | 0 0 0 | 1.27 1.27 | 0.15 | F.Fab | yes |
| Description | "" | 0 0 0 | 1.27 1.27 | 0.15 | F.Fab | yes |

| # | элемент | геометрия (мм) | width | layer |
|---|---|---|---|---|
| 1 | fp_line | start -2.49936 -8.7503; end 2.49936 -8.7503 | 0.14986 | F.SilkS |
| 2 | fp_line | start -2.49936 8.7503; end -2.49936 -8.7503 | 0.14986 | F.SilkS |
| 3 | fp_line | start 2.49936 -8.7503; end 2.49936 8.7503 | 0.14986 | F.SilkS |
| 4 | fp_line | start 2.49936 8.7503; end -2.49936 8.7503 | 0.14986 | F.SilkS |
| 5 | fp_arc | start -0.7493 -8.7503; mid 0 -9.4996; end 0.7493 -8.7503 | 0.14986 | F.SilkS |

(Файл: `DS` 1-4 в порядке 1, 4, 2, 3 из-за сортировки §14.2; `DA` с углом −1800 — начало и конец
переставлены, §10.3.)

#### mlt — `(descr "Корпус резистора МЛТ") (tags "mlt resistor")`

| # | pad | тип | форма | at | size | drill | layers |
|---|---|---|---|---|---|---|---|
| 1 | "1" | thru_hole | rect | -5.00126 0 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 2 | "2" | thru_hole | circle | 5.00126 0 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |

| поле | текст | at | size | thickness | layer |
|---|---|---|---|---|---|
| Reference | "REF**" | 0 -2.49936 0 | 1.00076 1.00076 | 0.14986 | F.SilkS |
| Value | "VAL**" | 0 2.49936 0 | 1.00076 1.00076 | 0.14986 | F.SilkS |

| # | элемент | геометрия | width | layer |
|---|---|---|---|---|
| 1 | fp_line | -5.00126 0 → -3.74904 0 | 0.14986 | F.SilkS |
| 2 | fp_line | -3.74904 -1.24968 → 3.74904 -1.24968 | 0.14986 | F.SilkS |
| 3 | fp_line | -3.74904 1.24968 → -3.74904 -1.24968 | 0.14986 | F.SilkS |
| 4 | fp_line | 3.74904 -1.24968 → 3.74904 1.24968 | 0.14986 | F.SilkS |
| 5 | fp_line | 3.74904 0 → 5.00126 0 | 0.14986 | F.SilkS |
| 6 | fp_line | 3.74904 1.24968 → -3.74904 1.24968 | 0.14986 | F.SilkS |

#### snp8 — `(descr "Корпус разъёма СНП 8 контактов с двумя монтажными отверстиями 3 мм") (tags "snp8 connector")`

| # | pad | тип | форма | at | size | drill | layers |
|---|---|---|---|---|---|---|---|
| 1 | "" | np_thru_hole | circle | 8.7503 -9.99998 | 2.99974 2.99974 | 2.99974 | "*.Mask" "B.Cu" "F.SilkS" |
| 2 | "" | np_thru_hole | circle | 8.7503 9.99998 | 2.99974 2.99974 | 2.99974 | "*.Mask" "B.Cu" "F.SilkS" |
| 3 | "1" | thru_hole | rect | -2.49936 -3.74904 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 4 | "2" | thru_hole | circle | -2.49936 -1.24968 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 5 | "3" | thru_hole | circle | -2.49936 1.24968 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 6 | "4" | thru_hole | circle | -2.49936 3.74904 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 7 | "5" | thru_hole | circle | 2.49936 -3.74904 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 8 | "6" | thru_hole | circle | 2.49936 -1.24968 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 9 | "7" | thru_hole | circle | 2.49936 1.24968 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |
| 10 | "8" | thru_hole | circle | 2.49936 3.74904 | 1.30048 1.30048 | 0.8001 | "*.Cu" "*.Mask" "F.SilkS" |

NPTH-площадки (`At HOLE N 00E00001`, `Sh ""`) — первыми (пустой номер), без
`remove_unused_layers`.

| поле | текст | at | size | thickness | layer |
|---|---|---|---|---|---|
| Reference | "REF**" | 8.7503 -13.74902 0 | 1.00076 1.00076 | 0.14986 | F.SilkS |
| Value | "VAL**" | 8.7503 13.74902 0 | 1.00076 1.00076 | 0.14986 | F.SilkS |

| # | элемент | геометрия | width | layer |
|---|---|---|---|---|
| 1 | fp_line | 2.49936 -12.49934 → 15.00124 -12.49934 | 0.14986 | F.SilkS |
| 2 | fp_line | 2.49936 12.49934 → 2.49936 -12.49934 | 0.14986 | F.SilkS |
| 3 | fp_line | 15.00124 -12.49934 → 15.00124 12.49934 | 0.14986 | F.SilkS |
| 4 | fp_line | 15.00124 12.49934 → 2.49936 12.49934 | 0.14986 | F.SilkS |

#### Полный текст `mlt.kicad_mod` (реконструкция вывода KiCad 9; uuid заменены на `…`)

```
(footprint "mlt"
	(version 20241229)
	(generator "pcbnew")
	(generator_version "9.0")
	(layer "F.Cu")
	(descr "Корпус резистора МЛТ")
	(tags "mlt resistor")
	(property "Reference" "REF**"
		(at 0 -2.49936 0)
		(layer "F.SilkS")
		(uuid "…")
		(effects
			(font
				(size 1.00076 1.00076)
				(thickness 0.14986)
			)
		)
	)
	(property "Value" "VAL**"
		(at 0 2.49936 0)
		(layer "F.SilkS")
		(uuid "…")
		(effects
			(font
				(size 1.00076 1.00076)
				(thickness 0.14986)
			)
		)
	)
	(property "Datasheet" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "…")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(property "Description" ""
		(at 0 0 0)
		(layer "F.Fab")
		(hide yes)
		(uuid "…")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(fp_line
		(start -5.00126 0)
		(end -3.74904 0)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(fp_line
		(start -3.74904 -1.24968)
		(end 3.74904 -1.24968)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(fp_line
		(start -3.74904 1.24968)
		(end -3.74904 -1.24968)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(fp_line
		(start 3.74904 -1.24968)
		(end 3.74904 1.24968)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(fp_line
		(start 3.74904 0)
		(end 5.00126 0)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(fp_line
		(start 3.74904 1.24968)
		(end -3.74904 1.24968)
		(stroke
			(width 0.14986)
			(type solid)
		)
		(layer "F.SilkS")
		(uuid "…")
	)
	(pad "1" thru_hole rect
		(at -5.00126 0)
		(size 1.30048 1.30048)
		(drill 0.8001)
		(layers "*.Cu" "*.Mask" "F.SilkS")
		(remove_unused_layers no)
		(uuid "…")
	)
	(pad "2" thru_hole circle
		(at 5.00126 0)
		(size 1.30048 1.30048)
		(drill 0.8001)
		(layers "*.Cu" "*.Mask" "F.SilkS")
		(remove_unused_layers no)
		(uuid "…")
	)
	(embedded_fonts no)
)
```

Файл заканчивается `)\n`, отступы — табы, переводы строк — LF. Для kicadfp в заголовке
ожидается `(generator "kicadfp")` и своя `generator_version`.

Рекомендуемые тесты (`test_legacy.py`): число модулей 3 и их имена; для каждого модуля —
таблицы выше (сравнение чисел как строк после форматирования §5.2); число строк файлов
218/131/173 при генераторе `pcbnew` (для `kicadfp` — сравнение деревьев с нормализацией uuid
и `generator*`); CRLF и LF версии фикстуры дают одинаковый результат.

---

## 18. Справка: как писали старые версии (для генерации тестовых входов)

| Строка | 2011 (bzr2986), deci-mils | 4.x LEGACY_PLUGIN, `Units mm` |
|---|---|---|
| заголовок | `PCBNEW-LibModule-V1  <дата>` + `# encoding utf-8` | + `Units mm` (`L40:4541-4546`) |
| `$MODULE` / конец | `$MODULE %s` / `$EndMODULE  %s` (2 пробела) | `$EndMODULE %s` (1 пробел) |
| `Po` | `Po %d %d %d %d %8.8lX %8.8lX %s` | `Po %s %s %d %08lX %08lX %s` (координаты `%.10g` мм, угол `%.10g`) |
| `Sc` | `Sc %8.8lX` | `Sc %lX` |
| `At` | `At ` + `SMD ` + `VIRTUAL ` | `At` + ` SMD` + ` VIRTUAL` |
| `T` | `T%d %d %d %d %d %d %d %c %c %d %c %s` | то же с мм + ` L\|C\|R T\|C\|B` при нецентрированном тексте |
| `Sh` | `Sh "%.4s" %c %d %d %d %d %d` | `Sh %s %c …` (`EscapedUTF8`, любая длина) |
| `Dr` | `Dr %d %d %d[ O %d %d]` | то же в мм |
| `At` площадки | `At %s N %8.8X` | `At %s N %08X` |
| `$SHAPE3D` | `Sc/Of/Ro %lf %lf %lf` | `%.10g` |

Источники: `bzr/pcbnew/class_module.cpp:259-398`, `bzr/pcbnew/class_pad.cpp:499-581`,
`bzr/pcbnew/class_text_mod.cpp:71-94`, `bzr/pcbnew/class_edge_mod.cpp:310-361`,
`L40:3113-3160, 3589-3860`. Примеры реальных строк `Units mm` из корпуса:
`Sh "1" R 1.905 1.905 0 0 0`, `Dr 0.8128 0 0`, `DA 5.08 0 9.525 0 900 0.2032 21`,
`T0 0 -10.16 1.524 1.524 0 0.3048 N V 21 N "L"`.

---

## 19. Проверено

Скрипты — в scratchpad сессии (`…/scratchpad/research/`), вне репозитория:
`legacy9.py` (эмуляция конвейера KiCad 9: загрузчик `L9` + `FootprintSave` + writer `S9` +
порт `Prettify`), `edge_cases.py`, `corpus_stats.py`, `dump_tables.py`,
`legacy_expected.py` (независимая более ранняя реализация таблиц).

1. **Фикстура `My_lib.mod`**: 3 модуля, 26 площадок (14 + 2 + 10), 6 текстов (все `T0/T1`),
   15 фигур (5 + 6 + 4, из них 1 дуга); 238 строк, все с CRLF. Таблицы §17 выданы
   `legacy9.py` и совпадают с независимым `legacy_expected.py` (все координаты, размеры, слои).
2. **16 контрольных пересчётов** deci-mils → мм (§5.3) — все совпали, в т.ч. подсказки
   512 → 1.30048, 315 → 0.8001, 984 → 2.49936.
3. **Маски**: `00E0FFFF`, `00808000`, `00888000`, `00E00001`, `0000FFFF`, `00008001`, `00C08000`
   и 10 масок из корпуса × 4 типа — таблица §6.5 получена расчётом по `L9:367-385` + `PAD:923-974` + `S9:1345-1429`.
4. **Дуги**: 7 случаев таблицы §10.3; направление сверено с кодом рисования 2011
   (`ArcTangente` + `GRArc` + `wxDC::DrawArc`) — для ±180° совпадает сторона выпуклости.
5. **Граничные случаи** (`edge_cases.py`, 14/14 OK): CRLF ≡ LF (3 файла идентичны);
   нет `$INDEX` → 0 модулей без ошибки; содержимое `$INDEX` игнорируется; `$module`/`$endmodule`
   в нижнем регистре; дубликат → `mlt_v2`; имя `a/b:c "q"` → `a%2fb%3ac %22q%22`; скрытый `T2` →
   `(property "" "hidden" …)`; `%R ~RST~` → `${REFERENCE} ~{RST}`; площадка нулевого размера
   удаляется; нет `$EndMODULE` → ошибка; `Units mm` (текст с `R B`, овальное сверло с
   offset у SMD → `(drill oval (offset 0.1 -0.2))`, угол 450.5 → 45.05, 3D-модель); статус
   `FP` → locked=false/placed=false, `~F` → locked=true.
6. **Реальный корпус** (`github.com/KiCad/kicad-library`, `modules/` на коммите
   `188a0c5eaccd1d27e8ab5ef2993b3f01505b70be`): 96 файлов (48 с CRLF, 14 с `Units mm`),
   **1518 модулей, 0 ошибок разбора**, все 1518 сохранены и повторно разобраны токенизатором.
   Состав: 20 947 площадок (circle 13 212, rect 5 751, oval 1 938, trapezoid 46; 1 988 с
   ненулевым углом, 21 с овальным сверлом, 66 со смещением, 44 с `rect_delta`);
   28 331 фигура (SEGMENT 27 555, CIRCLE 649, ARC 127 — все с положительным углом, 43 не кратны
   90°; POLY 0); слои графики: F.SilkS 23 414, F.Cu 3 669, Cmts.User 643, B.Cu 280,
   Edge.Cuts 200, F.Adhes 125; 510 моделей (27 с ненулевым `Of`, 21 с поворотом, 227 с
   масштабом ≠ 1); `attr`: нет 1 194, smd 308, virtual 16; 858 скрытых Reference/Value;
   1 239 пользовательских текстов (все видимые); модулей с ориентацией ≠ 0 — 7 (180°/90°/270°),
   со слоем ≠ 15 — 0; имён с пробелом — 3, с `/` — 1; статус ≠ `~~` — 1.
   Частоты масок: `SMD 00888000` 10 450, `STD 00E0FFFF` 9 407, `CONN 00400001` 258,
   `CONN 00808000` 246, `STD 00F0FFFF` 114, `STD 00A88001` 80, `STD 00808000` 72,
   `SMD 00A88000` 45, `HOLE 00E0FFFF` 43, `STD 00A8FFFF` 33, `STD 0000FFFF` 31, …,
   `MECA 00E0FFFF` 3, `MECA 00C0FFFF` 2.
7. **Порт `Prettify`** (`prettify.py`, режим 9.0): все **1860** файлов kicad-footprints v9.0.0
   с `(generator "pcbnew") (generator_version "9.0")` воспроизводятся байт-в-байт;
   структура эмулированного вывода (поля, `remove_unused_layers`, `embedded_fonts`, порядок)
   сверена с такими файлами (например `MountingHole_2.7mm_M2.5_ISO7380.kicad_mod`).
8. Сверено с `master`: загрузчик библиотек отличается только типом поля для скрытого текста
   (`FIELD_T::USER`, `Lm:1224`), `SetUuidDirect` и строгим разбором `$SHAPE3D`
   (`Lm:1796-1856`); `ReplaceIllegalFileNameChars` в `LoadModules` вызывается так же (`Lm:3161`).

Не проверено запуском настоящего KiCad (нет установленного KiCad/kicad-cli): всё выше —
по исходникам и эмуляции.

---

## 20. Открытые вопросы

1. **Отступления D1–D5 (§16.3)** — включать ли по умолчанию. Особенно D1 (смещение 3D в
   дюймах): KiCad 9 даёт физически неверный результат, но эталон «как KiCad» проще тестировать.
2. **Модуль на B.Cu** (`Po … 0 …`): что реально делает `FootprintSave` → `Flip()` без платы
   (`FP:2510` `GetBoard()->FlipLayer`) — не проверено; в корпусе таких модулей нет. Для kicadfp
   нужен выбор: оставить `(layer "B.Cu")` как есть или зеркалить (TOP_BOTTOM: y → −y, слои
   F↔B, углы → −угол, `PAD::Flip`/`PCB_TEXT::Flip`/`EDA_SHAPE::flip`) — правила зеркалирования
   в этом документе не расписаны.
3. **Относительные пути 3D-моделей** (`dil/dil_14.wrl`): как их разрешает KiCad 9
   (каталог проекта, `${KICAD9_3DMODEL_DIR}`, таблица псевдонимов) и нужен ли префикс — не
   проверено. Также не проверено, в каких единицах KiCad 9 интерпретирует старые `.wrl`
   (0.1 дюйма на единицу?) и остаётся ли `Sc 1 1 1` корректным.
4. **Несколько полей `""`** (скрытые `T2+`): сливаются ли они при повторном чтении KiCad 9
   (`P9:4637-4640`) — не проверено.
5. **Невалидный UTF-8**: KiCad использует локаль (`wxConvCurrent`), затем 8-бит; точное
   поведение на macOS/Windows не проверено; kicadfp предлагает `latin-1` + предупреждение.
6. **Очень старые файлы** (до bzr2986) без поля `italic`/без пробела перед текстом: разбор
   §9.2 описан по коду, реальных примеров в корпусе не найдено (слой в таком случае — см. §9.2).
7. Где именно в KiCad 9 GUI доступна конвертация `.mod` (диалог таблицы библиотек «Migrate»)
   и совпадает ли её путь с `ConvertLibrary` — не проверялось; `kicad-cli fp upgrade` — да
   (по коду).
