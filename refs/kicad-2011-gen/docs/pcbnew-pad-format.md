# Формат блока `$PAD` (pcbnew bzr2986): площадки в `.mod` / `.brd`

Восстановлено из исходников `~/Desktop/Университет/bzr2986`. Ссылки `файл:строка` — относительно
корня снапшота. Запись: `D_PAD::Save` (`pcbnew/class_pad.cpp:499-581`), чтение: `D_PAD::ReadDescr`
(`pcbnew/class_pad.cpp:359-496`). Блок одинаков для библиотеки `.mod` и платы `.brd`.

Содержание:
1. [Общие сведения](#1-общие-сведения)
2. [Блок `$PAD` построчно](#2-блок-pad-построчно)
3. [Коды форм, атрибутов, маски слоёв](#3-коды-форм-атрибутов-маски-слоёв)
4. [Монтажное отверстие без металлизации](#4-монтажное-отверстие-без-металлизации)
5. [Единицы и пересчёт мм → внутренние](#5-единицы-и-пересчёт-мм--внутренние)
6. [Готовые блоки для ТЗ](#6-готовые-блоки-для-тз)

---

## 1. Общие сведения

| Параметр | Значение | Где в коде |
|---|---|---|
| Единица длины | 1/10000 дюйма (`PCB_INTERNAL_UNIT 10000`) | `include/fctsys.h:32`, `include/wxPcbStruct.h:16`, `include/wxBasePcbFrame.h:18`, `pcbnew/basepcbframe.cpp:65` |
| Угол | 1/10 градуса (`m_Orient`) | `pcbnew/class_pad.h:99` |
| Имя площадки | `char m_Padname[4]` (union с `unsigned long m_NumPadName`), **не более 4 байт**, без завершающего NUL при 4 символах | `pcbnew/class_pad.h:60-64`, `class_pad.cpp:167-178` |
| Буферы чтения | `BufLine[1024]`, `BufCar[256]`; `%s` в них без ограничения длины | `pcbnew/class_pad.cpp:362,403,433,449` |
| Макс. длина строки файла | `LINE_READER_LINE_DEFAULT_MAX 100000` | `include/richio.h:187` |
| Кто вызывает | `MODULE::Save` пишет все площадки после графики (`m_Drawings`) и перед `$SHAPE3D` | `pcbnew/class_module.cpp:346-350` |
| Кто читает | `MODULE::ReadDescr`: строка `$P…` → `new D_PAD`, `pad->ReadDescr()`; **код возврата игнорируется**; затем `m_Pos` поворачивается на ориентацию модуля и сдвигается на `m_Pos` модуля | `pcbnew/class_module.cpp:482-495` |
| Разбор строки | по **первому символу** (`Line[0]`), данные с `Line + 3` | `pcbnew/class_pad.cpp:372,376` |
| Конец блока | **любая** строка, начинающаяся с `$` → `return 0` (`$EndPAD` не проверяется) | `pcbnew/class_pad.cpp:369-370` |

## 2. Блок `$PAD` построчно

Порядок записи фиксирован (`Save`), порядок чтения — произвольный (switch по первой букве).

| # | Строка (формат `fprintf`) | Поля | Чтение (`sscanf` / прочее) | Строки кода |
|---|---|---|---|---|
| 1 | `$PAD\n` | — | `Line[0]=='$'` завершает *предыдущий* блок; сам `$PAD` съедает `MODULE::ReadDescr` | Save `:505-506`; Read `class_module.cpp:486` |
| 2 | `Sh "%.4s" %c %d %d %d %d %d\n` | имя (≤4), буква формы, `m_Size.x`, `m_Size.y`, `m_DeltaSize.x`, `m_DeltaSize.y`, `m_Orient` (0,1°) | имя: пропуск до первой `"`, копируются только символы `> ' '`, максимум 4 (`nn < sizeof(m_Padname)`), лишние молча отбрасываются; далее `sscanf(" %s %d %d %d %d %d")` → 6 полей, `nn` не проверяется; форма — по **первому символу** `BufCar[0]`, неизвестная → `PAD_CIRCLE` | Save `:528-530`; Read `:378-428` (имя `:381-400`, sscanf `:403-406`, форма `:408-426`) |
| 3 | `Dr %d %d %d` [+ ` O %d %d`] `\n` | `m_Drill.x`, `m_Offset.x`, `m_Offset.y`; для овального сверла добавляется ` O m_Drill.x m_Drill.y` | `sscanf("%d %d %d %s %d %d")`; `m_Drill.y = m_Drill.x`, `m_DrillShape = PAD_CIRCLE`; если `nn >= 6` **и** `BufCar[0]=='O'` → `m_Drill=(dx,dy)`, `PAD_OVAL` | Save `:532-537`; Read `:431-446` |
| 4 | `At %s N %8.8X\n` | атрибут `STD`/`SMD`/`CONN`/`HOLE`, литерал `N`, маска слоёв — 8 hex-цифр, верхний регистр, с ведущими нулями | `sscanf("%s %s %X", BufLine, BufCar, &m_Masque_Layer)`; `BufCar` («N») не используется; `m_Attribut = PAD_STANDARD`, затем `strncmp` на `SMD`(3)/`CONN`(4)/`HOLE`(4) | Save `:539-559`; Read `:448-461` |
| 5 | `Ne %d %s\n` | `GetNet()`, имя цепи через `EscapedUTF8` — **всегда в кавычках**, `"`→`\"`, `\`→`\\`; пустая цепь → `Ne 0 ""` | `sscanf("%d", &netcode)` → `SetNet`; `ReadDelimitedText(BufLine, PtLine, 1024)` берёт текст между первой парой `"`, `StrPurge`, `FROM_UTF8` → `SetNetname` | Save `:561`; Read `:463-471`; `common/string.cpp:53-97,99-131` |
| 6 | `Po %d %d\n` | `m_Pos0` — позиция относительно якоря модуля при ориентации модуля 0 | `sscanf("%d %d", &m_Pos0.x, &m_Pos0.y)`; `m_Pos = m_Pos0` | Save `:563`; Read `:473-476`; `class_pad.h:95` |
| 7 | `.SolderMask %d\n` | `m_LocalSolderMaskMargin`, **только если ≠ 0** | `strnicmp(Line, ".SolderMask ", 12)` → `atoi(Line+12)` | Save `:565-566`; Read `:479-480` |
| 8 | `.SolderPaste %d\n` | `m_LocalSolderPasteMargin`, только если ≠ 0 | `atoi(Line+13)` | Save `:568-569`; Read `:481-482` |
| 9 | `.SolderPasteRatio %g\n` | `m_LocalSolderPasteMarginRatio` (double, доля, напр. `-0.1`), только если ≠ 0 | `atoi(Line+18)` — **дробная часть теряется** (баг версии) | Save `:571-572`; Read `:483-484` |
| 10 | `.LocalClearance %d\n` | `m_LocalClearance`, только если ≠ 0 | `atoi(Line+16)` | Save `:574-575`; Read `:485-486` |
| 11 | `$EndPAD\n` | — | любая строка с `$` → `return 0` | Save `:577-578`; Read `:369-370` |

Обработка ошибок:

| Ситуация | Поведение | Где |
|---|---|---|
| `fprintf("$PAD\n")` / `fprintf("$EndPAD\n")` вернул не 5 / 8 байт | `Save` → `false` (остальные `fprintf` не проверяются) | `class_pad.cpp:505-506,577-578` |
| Неизвестная первая буква строки | `DisplayError("Err Pad: Id inconnu")`, `return 1` | `class_pad.cpp:488-491` |
| EOF без `$…` | `return 2` | `class_pad.cpp:495` |
| Любой код возврата `ReadDescr` | игнорируется `MODULE::ReadDescr`, площадка всё равно добавляется | `class_module.cpp:489-494` |
| Неизвестная форма/атрибут при записи | `DisplayError`, пишется `C` / `STD` | `class_pad.cpp:522-525,553-556` |
| Пустое `Sh ""` | `m_Padname` = `{0,0,0,0}` (`memset` перед чтением) | `class_pad.cpp:387` |

## 3. Коды форм, атрибутов, маски слоёв

### 3.1 Форма (`m_PadShape`, `include/pad_shapes.h:9-17`)

| Буква в файле | Макрос | Значение | Примечание |
|---|---|---|---|
| `C` | `PAD_CIRCLE` (`PAD_ROUND`) | 1 | `m_Size.y = m_Size.x` (диалог `dialog_pad_properties.cpp:695-696`, `move-drag_pads.cpp:160-161`) |
| `R` | `PAD_RECT` | 2 | |
| `O` | `PAD_OVAL` | 3 | |
| `T` | `PAD_TRAPEZOID` | 4 | один из `m_DeltaSize.x/y` должен быть 0 (`dialog_pad_properties.cpp:699-700`) |
| — | `PAD_RRECT`/`PAD_OCTAGON`/`PAD_SQUARE` | 5/6/7 | объявлены, но `Save` не пишет (→ `C` + ошибка), `ReadDescr` не читает |

Форма сверла (`m_DrillShape`, `class_pad.h:73`): `PAD_CIRCLE` (по умолчанию) или `PAD_OVAL` (суффикс ` O dx dy` в `Dr`).

### 3.2 Атрибут (`m_Attribut`, `include/pad_shapes.h:20-26`)

| Строка в файле | Макрос | Значение | Комментарий в исходнике |
|---|---|---|---|
| `STD` | `PAD_STANDARD` | 0 | «Usual pad» — сквозная с отверстием |
| `SMD` | `PAD_SMD` | 1 | «appears on the layer paste»; сверло и offset обнуляются (`dialog_pad_properties.cpp:770-774`, `move-drag_pads.cpp:165-172`) |
| `CONN` | `PAD_CONN` | 2 | «does not appear on the layer paste»; сверло обнуляется (там же) |
| `HOLE` | `PAD_HOLE_NOT_PLATED` | 3 | «reserved, but not yet really used … like PAD_STANDARD, but not plated» (`pad_shapes.h:25-26`) |

### 3.3 Биты маски слоёв (`include/layers_id_colors_and_visibility.h`)

| Слой | Номер (`*_N_*`) | Бит-маска | Строки |
|---|---|---|---|
| Copper (back) | `LAYER_N_BACK` = 0 | `LAYER_BACK` = `0x00000001` | `:10,52` |
| Внутренние медные | 1…14 | `LAYER_2`…`LAYER_15` | `:53-66` |
| Component (front) | `LAYER_N_FRONT` = 15 | `LAYER_FRONT` = `0x00008000` | `:25,67` |
| Все медные | — | `ALL_CU_LAYERS` = `0x0000FFFF` | `:90` |
| Adhesive back/front | 16 / 17 | `0x00010000` / `0x00020000` | `:30-31,68-69` |
| SolderPaste back/front | 18 / 19 | `0x00040000` / `0x00080000` | `:32-33,70-71` |
| SilkScreen back/front | 20 / 21 | `0x00100000` / `0x00200000` | `:34-35,72-73` |
| SolderMask back/front | 22 / 23 | `0x00400000` / `0x00800000` | `:36-37,74-75` |
| Все слои pcbnew | — | `ALL_LAYERS` = `0x1FFFFFFF` (29 слоёв) | `:87` |

### 3.4 Маски по умолчанию для каждого атрибута (`pcbnew/class_pad.h:15-27`)

| Атрибут | Макрос | Состав | **Hex в файле (`At … N`)** |
|---|---|---|---|
| `STD` | `PAD_STANDARD_DEFAULT_LAYERS` | `ALL_CU_LAYERS \| SILKSCREEN_LAYER_FRONT \| SOLDERMASK_LAYER_BACK \| SOLDERMASK_LAYER_FRONT` | **`00E0FFFF`** |
| `SMD` | `PAD_SMD_DEFAULT_LAYERS` | `LAYER_FRONT \| SOLDERMASK_LAYER_FRONT` | `00808000` |
| `CONN` | `PAD_CONN_DEFAULT_LAYERS` | `LAYER_FRONT \| SOLDERPASTE_LAYER_FRONT \| SOLDERMASK_LAYER_FRONT` | `00888000` |
| `HOLE` | `PAD_HOLE_NOT_PLATED_DEFAULT_LAYERS` | `LAYER_BACK \| SILKSCREEN_LAYER_FRONT \| SOLDERMASK_LAYER_BACK \| SOLDERMASK_LAYER_FRONT` | **`00E00001`** |

Откуда берётся маска в реальном файле:

| Путь | Что пишется | Где |
|---|---|---|
| Конструктор `D_PAD` | `m_Masque_Layer = PAD_STANDARD_DEFAULT_LAYERS`, `m_Size = 500×500`, `m_PadShape = PAD_CIRCLE`, `m_Attribut = PAD_STANDARD`, `m_DrillShape = PAD_CIRCLE`, `m_Orient = 0` | `pcbnew/class_pad.cpp:20-48` |
| Новая площадка в редакторе модулей | копия `g_Pad_Master` (`m_Masque_Layer`, `m_Attribut`, размеры, сверло), `SetNetname("")` | `pcbnew/move-drag_pads.cpp:143-152,200` |
| `g_Pad_Master` из `.pro` | `PadDrlX` = 320, `PadDimH` = `PadDimV` = 550 (внутр. ед., т.е. 0,8128 / 1,397 мм) | `pcbnew/pcbnew_config.cpp:198-203` |
| Смена типа в диалоге | `Std_Pad_Layers[тип]` → чекбоксы слоёв | `pcbnew/dialogs/dialog_pad_properties.cpp:29-42,493-498` |
| OK в диалоге | маска собирается из чекбоксов: оба медных → `ALL_CU_LAYERS` | `dialog_pad_properties.cpp:784-812` |

Замечание: в `Std_Pad_Layers` индекс 1 = `PAD_CONN_DEFAULT_LAYERS`, индекс 2 = `PAD_SMD_DEFAULT_LAYERS`,
тогда как `CodeType[1] = PAD_SMD`, `CodeType[2] = PAD_CONN` (`dialog_pad_properties.cpp:23-42`) —
в диалоге SMD/CONN получают маски «наоборот». Для STD/HOLE (индексы 0/3) расхождения нет.

## 4. Монтажное отверстие без металлизации

Как это выглядит в bzr2986 (ТЗ: «площадка без номера / тип "монтажное отверстие"»,
`kicad-требования-и-задания.md:180`):

| Признак | Поведение / доказательство | Где |
|---|---|---|
| Атрибут `HOLE` | пишется/читается (`PAD_HOLE_NOT_PLATED` = 3); в диалоге 4-й пункт списка типов; при OK сверло **не** обнуляется (в отличие от SMD/CONN) | `class_pad.cpp:550-551,459-460`; `dialog_pad_properties.cpp:23-26,765-780` |
| Больше нигде не используется | `grep PAD_HOLE_NOT_PLATED pcbnew/` → только `class_pad.cpp`, `dialog_pad_properties.cpp`, `pad_shapes.h`; плоттер, DRC, сверловка атрибут не смотрят | (grep по снапшоту) |
| Сверловка | в список отверстий попадает **любая** площадка с `m_Drill.x != 0`; понятия plated/non-plated нет (в `gendrill*.cpp` слово «plated» отсутствует) | `pcbnew/gen_holes_and_tools_lists_for_drill.cpp:104-118` |
| Маска по умолчанию для `HOLE` | `00E00001`: только **back copper** (бит 0) + маска пайки обеих сторон + шелкография front; т.е. медное кольцо рисуется/плоттится только на Copper, front-медь пуста | `class_pad.h:25-27` |
| Пустой номер | `Sh ""` → `m_Padname = {0,0,0,0}`; netlist сопоставляет выводы `strnicmp(TextPinName, m_Padname, 4)` — пустое имя никогда не совпадёт; цепь пустая → `SetNet(0)`; ratsnest пропускает `GetNet()==0` | `class_pad.cpp:387-400`; `pcbnew/netlist.cpp:613`; `pcbnew/class_netinfolist.cpp:112-114`; `pcbnew/ratsnest.cpp:805` |
| Имя в диалоге | `m_PadNumCtrl->GetValue().Left(4)` → `SetPadName` | `dialog_pad_properties.cpp:740-741` |
| DRC | у площадки, отсутствующей на проверяемом медном слое, проверяется само **отверстие** как псевдо-площадка размера `m_Drill` (зазор дорожка–отверстие) | `pcbnew/drc_clearance_test_functions.cpp:290-303` |
| Селектор/визуализация | всё, что не SMD/CONN, считается «with hole, on multiple layers» | `pcbnew/collectors.cpp:218-223` |

Итого: «непокрытое» отверстие в этой версии = площадка `At HOLE N 00E00001` с `Sh ""` (без номера) и
`Ne 0 ""`, `Dr` = диаметр отверстия. Альтернатива, дающая тот же результат на плёнках — `STD` с
`m_Size == m_Drill` (кольцо нулевой ширины): для сверловки и DRC разницы нет (см. выше).
Имя может быть пустым или, например, `"H"` — на сверловку и DRC не влияет, влияет только на
сопоставление с netlist (`netlist.cpp:613`).

## 5. Единицы и пересчёт мм → внутренние

| Шаг | Код | Где |
|---|---|---|
| Константа | `#define PCB_INTERNAL_UNIT 10000 // PCBNEW internal unit = 1/10000 inch` | `include/fctsys.h:32` |
| Фрейм | `m_InternalUnits = PCB_INTERNAL_UNIT` | `pcbnew/basepcbframe.cpp:65`, `pcbnew/pcbframe.cpp:305` |
| Диалог площадки | все размеры через `ReturnValueFromTextCtrl(ctrl, internalUnits)` | `dialog_pad_properties.cpp:659-664,677-694` |
| → строка | `ReturnValueFromString(g_UserUnit, msg, Internal_Unit)`: числовая часть до первого не-цифрового символа; суффикс `mm`/`in`/`"`/`mi`/`th` переопределяет единицу | `common/common.cpp:327-333,387-437` |
| → число | `From_User_Unit(MILLIMETRES, val, iu)`: `value = val * internal_unit_value / 25.4; return wxRound(value)` | `common/common.cpp:501-520` |
| Округление | `wxRound` (wxWidgets `wx/math.h`, вне снапшота): `int(x < 0 ? x - 0.5 : x + 0.5)` — к ближайшему, половина от нуля; для положительных = `int(v + 0.5)` | — |
| Обратно | `To_User_Unit(MILLIMETRES, val, iu) = val * 25.4 / iu` | `common/common.cpp:482-495` |

Формула: `iu = round(mm * 10000 / 25.4)`, `mm = iu * 25.4 / 10000`.

| мм | `mm·10000/25.4` | **iu (в файл)** | Обратно, мм | Для чего (ТЗ) |
|---|---|---|---|---|
| 0,5 | 196,8504 | **197** | 0,50038 | сверло переходного отв. (`ТЗ:233`) |
| 0,8 | 314,9606 | **315** | 0,80010 | сверло площадки (`ТЗ:79,165`) |
| 0,9 | 354,3307 | **354** | 0,89916 | площадка переходного отв. (`ТЗ:233`) |
| 1,25 | 492,1260 | **492** | 1,24968 | сетка (`ТЗ:165`) |
| 1,3 | 511,8110 | **512** | 1,30048 | площадка 1,3×1,3 (`ТЗ:165`) |
| 2,5 | 984,2520 | **984** | 2,49936 | шаг выводов / отступ отверстия (`ТЗ:180`) |
| 2,54 | 1000,0000 | **1000** | 2,54000 | 100 mil |
| 3,0 | 1181,1024 | **1181** | 2,99974 | монтажное отверстие (`ТЗ:180`) |
| 5,0 | 1968,5039 | **1969** | 5,00126 | |
| 7,5 | 2952,7559 | **2953** | 7,50062 | |
| 10,0 | 3937,0079 | **3937** | 9,99998 | |

Кратные шаги: `n × 2,5 мм` считать как `round(n·25000/25.4)`, а не `n × 984` (984·2 = 1968, а
`round(5,0 мм)` = 1969) — иначе накопится ошибка на 1 iu.

## 6. Готовые блоки для ТЗ

Площадка 1 (квадрат 1,3 мм, сверло 0,8 мм, в якоре модуля):

```
$PAD
Sh "1" R 512 512 0 0 0
Dr 315 0 0
At STD N 00E0FFFF
Ne 0 ""
Po 0 0
$EndPAD
```

Площадка 2 (круг 1,3 мм, шаг 2,5 мм вправо):

```
$PAD
Sh "2" C 512 512 0 0 0
Dr 315 0 0
At STD N 00E0FFFF
Ne 0 ""
Po 984 0
$EndPAD
```

Монтажное отверстие 3 мм без номера (сверло = размер площадки → без медного кольца):

```
$PAD
Sh "" C 1181 1181 0 0 0
Dr 1181 0 0
At HOLE N 00E00001
Ne 0 ""
Po 0 -984
$EndPAD
```

Овальное сверло (для справки): `Dr 315 0 0 O 315 512`.
