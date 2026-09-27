# Формат библиотеки посадочных мест Pcbnew bzr2986: `.mod` / `.emp` — уровень LIBRARY и MODULE

Часть A спецификации. Восстановлено из исходников `~/Desktop/Университет/bzr2986`;
все ссылки `файл:строка` — относительно корня снапшота. Строки `$PAD … $EndPAD`
(`D_PAD::Save/ReadDescr`) — часть B, здесь упоминаются только как непрозрачный блок.

Содержание:
1. [Общие сведения и константы](#1-общие-сведения-и-константы)
2. [Файл библиотеки: заголовок, `$INDEX`, `$EndLIBRARY`](#2-файл-библиотеки)
3. [Как KiCad читает библиотеку](#3-как-kicad-читает-библиотеку)
4. [Как KiCad пишет библиотеку](#4-как-kicad-пишет-библиотеку)
5. [Блок `$MODULE … $EndMODULE`](#5-блок-module--endmodule)
6. [Строка текста `T<n>`](#6-строка-текста-tn)
7. [Графика `DS` / `DC` / `DA` / `DP`](#7-графика-ds--dc--da--dp)
8. [Блок `$SHAPE3D`](#8-блок-shape3d)
9. [Что роняет или искажает загрузку](#9-что-роняет-или-искажает-загрузку)

---

## 1. Общие сведения и константы

| Параметр | Значение | Где в коде |
|---|---|---|
| Внутренняя единица Pcbnew | `#define PCB_INTERNAL_UNIT 10000 // PCBNEW internal unit = 1/10000 inch` → 1 ед. = 0.1 mil = 2.54 мкм; все координаты, размеры, толщины в `.mod` — целые в этих единицах | `include/fctsys.h:32` (дубли: `include/wxBasePcbFrame.h:18`, `include/wxPcbStruct.h:16`) |
| Оси | экранные: X вправо, Y **вниз** (координаты элементов складываются с `Module->m_Pos` без инверсии) | `class_text_mod.cpp:211-225`, `class_edge_mod.cpp:124-138` |
| Углы | целые, в 0.1° (`m_Orient` модуля, `m_Angle` дуги, ориентация текста) | `pcbnew/class_module.h:51`, `pcbnew/class_edge_mod.h:21` |
| Расширение | библиотека `mod`; экспорт одного модуля `emp` (тот же формат, один модуль); резервная копия `bak`; временный `$$$` | `common/pcbcommon.cpp:79`, `pcbnew/librairi.cpp:28-32` |
| Заголовок | `#define ENTETE_LIBRAIRIE "PCBNEW-LibModule-V1"`, `#define L_ENTETE_LIB 18` — сравниваются только первые 18 байт (`PCBNEW-LibModule-V`) без учёта регистра | `include/pcbstruct.h:14-15` |
| Кодировка | UTF-8 (`TO_UTF8` / `FROM_UTF8`) | `include/macros.h:16-23` |
| Дата в заголовке | `DateAndTime()` = `wxDateTime::Now().Format(wxDefaultDateTimeFormat)`, свободный текст, никогда не парсится | `common/string.cpp:175-199` |
| Чтение строк при загрузке | `FILE_LINE_READER` + `FILTER_READER`: строки, начинающиеся с `#`, `\n`, `\r`, **пропускаются**; `\n` в конце строки **сохраняется** в буфере; лимит строки 100000 байт | `common/filter_reader.cpp:30-41`, `common/richio.cpp:105-120`, `include/richio.h:187` |
| Чтение строк при перезаписи библиотеки | `GetLine`: пропускает `#`, пустые, `\r`/`\n`; обрезает `\n\r` | `common/string.cpp:157-169` |
| Экранирование текста | `EscapedUTF8`: `"…"`, внутри `"`→`\"`, `\`→`\\`; `ReadDelimitedText` ищет первую `"` в строке | `common/string.cpp:11-125` |

### 1.1 Слои (`include/layers_id_colors_and_visibility.h:9-49`, имена `pcbnew/class_board.cpp:237-265`)

| № | Макрос | Имя по умолчанию | Примечание |
|---|---|---|---|
| 0 | `LAYER_N_BACK` | `Back` | медь, низ (`FIRST_COPPER_LAYER`) |
| 1…14 | `LAYER_N_2` … `LAYER_N_15` | `Inner2` … `Inner15` | внутренняя медь |
| 15 | `LAYER_N_FRONT` | `Front` | медь, верх (`LAST_COPPER_LAYER`); слой модуля по умолчанию (`class_module.cpp:32`) |
| 16 | `ADHESIVE_N_BACK` | `Adhes_Back` | `FIRST_NO_COPPER_LAYER` |
| 17 | `ADHESIVE_N_FRONT` | `Adhes_Front` | |
| 18 | `SOLDERPASTE_N_BACK` | `Paste_Back` | |
| 19 | `SOLDERPASTE_N_FRONT` | `Paste_Front` | |
| 20 | `SILKSCREEN_N_BACK` | `SilkS_Back` | |
| 21 | `SILKSCREEN_N_FRONT` | `SilkS_Front` | слой текста/графики модуля по умолчанию (`class_text_mod.cpp:37`, `class_edge_mod.cpp:481`) |
| 22 | `SOLDERMASK_N_BACK` | `Mask_Back` | |
| 23 | `SOLDERMASK_N_FRONT` | `Mask_Front` | |
| 24 | `DRAW_N` | `Drawings` | |
| 25 | `COMMENT_N` | `Comments` | |
| 26 | `ECO1_N` | `Eco1` | |
| 27 | `ECO2_N` | `Eco2` | |
| 28 | `EDGE_N` | `PCB_Edges` | `LAST_NO_COPPER_LAYER` = `LAST_NON_COPPER_LAYER` (`:43,83`) |
| 29–31 | `UNUSED_LAYER_29..31` | — | `LAYER_COUNT 32` (`:49`) |

Маски: `ALL_CU_LAYERS 0x0000FFFF`, `ALL_NO_CU_LAYERS 0x1FFF0000`, `ALL_LAYERS 0x1FFFFFFF` (`:87-90`).

### 1.2 Атрибуты и флаги модуля (`pcbnew/class_module.h:17-29`)

| Макрос | Значение | В файле |
|---|---|---|
| `MOD_DEFAULT` | 0 | строка `At` **не пишется** |
| `MOD_CMS` | 1 | `At SMD` (сквозные/обычные — без `At`) |
| `MOD_VIRTUAL` | 2 | `At VIRTUAL` (может сочетаться: `At SMD VIRTUAL `) |
| `MODULE_is_LOCKED` | 0x01 | первый символ статуса в `Po`: `F` / `~` |
| `MODULE_is_PLACED` | 0x02 | второй символ статуса в `Po`: `P` / `~` |

Типы текста (`pcbnew/class_text_mod.h:11-13`): `TEXT_is_REFERENCE 0`, `TEXT_is_VALUE 1`, `TEXT_is_DIVERS 2`.

Пределы (`pcbnew/pcbnew.h:33-35`): `TEXTS_MIN_SIZE 50`, `TEXTS_MAX_SIZE 10000`, `TEXTS_MAX_WIDTH 5000`; `MAX_WIDTH 10000` для графики (`pcbnew/class_edge_mod.cpp:19`).

Умолчания редактора модулей для нового посадочного места (`pcbnew/pcbnew_config.cpp:213-218`, ключи проекта `TxtModV/TxtModH/TxtModW`): размер текста 500×500, толщина 100. `Create_1_Module` (`librairi.cpp:725-777`): ссылка = имя модуля, значение `VAL**`, позиция модуля (0,0).

---

## 2. Файл библиотеки

Комментарий-схема в коде (`pcbnew/librairi.cpp:19-27`):

```
PCBNEW-LibModule-V1  <дата>          ← ENTETE_LIBRAIRIE, два пробела, DateAndTime
# encoding utf-8                     ← комментарий; FILTER_READER/GetLine его пропускают
$INDEX
<имя модуля>                         ← по одному в строке, в порядке следования $MODULE
...
$EndINDEX
$MODULE <имя>
...
$EndMODULE  <имя>
...                                  ← остальные модули
$EndLIBRARY
```

Пример (сгенерированный `Export_Module`, один модуль `dip14`, без `Cd/Kw/At`):

```
PCBNEW-LibModule-V1  Wed 02 Sep 2026 19:52:23
# encoding utf-8
$INDEX
dip14
$EndINDEX
$MODULE dip14
Po 0 0 0 15 00000000 00000000 ~~
Li dip14
Sc 00000000
AR 
Op 0 0 0
T0 0 -1500 500 500 0 100 N V 21 N "dip14"
T1 0 1500 500 500 0 100 N V 21 N "VAL**"
DS -3500 -1500 3500 -1500 120 21
$PAD
...
$EndPAD
$EndMODULE  dip14
$EndLIBRARY
```

Имя модуля читается через `%s` / `StrPurge(Line+8)` — **без пробелов**. Сравнение имён везде `CmpNoCase` (регистронезависимо): `loadcmp.cpp:281,306`, `librairi.cpp:272,352,573,663`.

---

## 3. Как KiCad читает библиотеку

### 3.1 Загрузка модуля по имени — `PCB_BASE_FRAME::Get_Librairie_Module` (`pcbnew/loadcmp.cpp:196-330`)

Вызывается из Pcbnew/ModEdit при «Load module from library» (`loadcmp.cpp:135,150`).

| Шаг | Код | Поведение |
|---|---|---|
| Открытие | `:216-246` | если имя библиотеки пустое — перебирает все `g_LibName_List` с расширением `mod` через `FindLibraryPath`; иначе один файл. `FILE_LINE_READER` + `FILTER_READER` |
| Заголовок | `:250-263` | первая (нефильтрованная) строка, `StrPurge`, `strnicmp(Line, ENTETE_LIBRAIRIE, 18) != 0` → диалог `<%s> is not a valid Kicad PCB footprint library file.` и `return NULL` |
| Поиск в индексе | `:266-285` | читает строки до `$MODULE` (`strnicmp 6`, т.е. `$MODUL`) или `$INDEX` (`strnicmp 6`). Внутри `$INDEX`: до `$EndINDEX` (`strnicmp 9`), каждая строка `StrPurge` → `CmpNoCase(aModuleName)` → `Found=1` |
| Поиск блока | `:288-318` | только если `Found`: строки `$MODULE` (`Line[0]=='$'`, `Line[1]=='M'`, `strnicmp 7`), имя = `StrPurge(Line+8)`; при совпадении `new MODULE`, `SetLocaleTo_C_standard`, `ReadDescr(&reader)` (`:313`), `board->Add(NewModule, ADD_APPEND)`, `return` |
| Не найден | `:325-329` | `Module <%s> not found` (только при `aDisplayMessageError`), `return NULL` |

Следствия: **`$INDEX` обязателен**, и имя должно быть в нём, иначе `Found=0` и блоки `$MODULE` не сканируются. Если `$MODULE` встретится раньше `$INDEX` — поиск прекращается с `Found=0`. `$EndLIBRARY` этой функцией не проверяется.

### 3.2 Список модулей для выбора / CvPcb — `FOOTPRINT_LIST::ReadFootprintFiles` (`common/footprint_info.cpp:60-128`)

| Шаг | Код | Поведение |
|---|---|---|
| Заголовок | `:73-86` | `strnicmp(…, 18)` → файл помечается invalid: `<%s> is not a valid Kicad PCB footprint library.` |
| Цикл | `:89-97` | до `$EndLIBRARY` (`strnicmp 11`) или EOF |
| Модуль | `:98-104` | `$MODULE` (`strnicmp 7`) → имя = `StrPurge(line+7)`; **`$INDEX` не используется** |
| Внутри | `:106-124` | до `$EndMODULE` (`strnicmp 10`); по первым двум байтам: `Kw` → `m_KeyWord = StrPurge(line+3)`, `Cd` → `m_Doc = StrPurge(line+3)` |

### 3.3 Импорт `.emp` — `WinEDA_ModuleEditFrame::Import_Module` (`pcbnew/librairi.cpp:41-130`)

Заголовок `:92-102` (иначе `Element` → формат gPCB, иначе `Not a module file`); пропуск до первого `$MODULE` (`strnicmp 7`, `:105-111`); `ReadDescr` (`:123`). Индекс не читается.

### 3.4 Плата `.brd` (`pcbnew/ioascii.cpp:965-982`)

`TESTLINE("MODULE")` = `strncmp(Line, "$MODULE", 7)` → `new MODULE`, `board->Add(…, ADD_APPEND)`, `Module->ReadDescr(aReader)` — тот же парсер блока, что и для библиотеки.

---

## 4. Как KiCad пишет библиотеку

### 4.1 Новая библиотека из одного модуля / экспорт `.emp` — `Export_Module` (`pcbnew/librairi.cpp:152-217`)

Формат-строки дословно (`:200-209`):

```c
fprintf( file, "%s  %s\n", ENTETE_LIBRAIRIE, DateAndTime( Line ) );   // :200  два пробела
fprintf( file, "# encoding utf-8\n");                                  // :201
fputs( "$INDEX\n", file );                                             // :202
fprintf( file, "%s\n", TO_UTF8( aModule->m_LibRef ) );                 // :204
fputs( "$EndINDEX\n", file );                                          // :205
GetBoard()->m_Modules->Save( file );                                   // :207  один MODULE::Save
fputs( "$EndLIBRARY\n", file );                                        // :209
```

Перед записью `m_LibRef = m_Reference->m_Text` (`:163`); локаль `C` (`:198,213`). `aCreateSysLib=true` → расширение `mod`, иначе `emp` (`:165`).

### 4.2 Архив всех модулей платы — `Archive_Modules` (`:398-480`)

Если библиотека новая или `NewModulesOnly=false` — создаётся **пустая** библиотека (`:453-457`):

```c
fprintf( lib_module, "%s  %s\n", ENTETE_LIBRAIRIE, DateAndTime( Line ) );
fprintf( lib_module, "# encoding utf-8\n");
fputs( "$INDEX\n", lib_module );
fputs( "$EndINDEX\n", lib_module );
fputs( "$EndLIBRARY\n", lib_module );
```

затем для каждого модуля платы `Save_Module_In_Library(fileName, Module, overwrite=!NewModulesOnly, dialog=false)` (`:470-475`).

### 4.3 Сохранение одного модуля в существующую библиотеку — `Save_Module_In_Library` (`:495-706`)

Единственный путь записи «целой библиотеки» из ModEdit («Save module in current library»). Библиотека **перезаписывается целиком** через временный файл:

| Шаг | Код | Поведение |
|---|---|---|
| Проверки | `:515-520`, `:544-550` | файл должен существовать; заголовок `strnicmp 18`, иначе `File %s is not a eeschema library` (sic) |
| Есть ли модуль | `:553-590` | ищет имя в `$INDEX` (только там); найден и `!aOverwrite` → `return 1` без записи |
| Новый заголовок | `:621-624` | `fprintf(dest, ENTETE_LIBRAIRIE); fprintf(dest, "  %s\n", DateAndTime(Line)); fprintf(dest, "# encoding utf-8\n"); fprintf(dest, "$INDEX\n");` |
| Индекс | `:626-646` | копирует старые имена из `$INDEX` (после `StrPurge`), новое имя дописывает в конец (`:642-643`, если `newmodule`); строка `:644` `strnicmp(Line,"$EndINDEX",0)==0` всегда истинна → выход после первого `$INDEX` |
| | `:648` | `fprintf( dest, "$EndINDEX\n" );` |
| Тело | `:651-672` | копирует остальные строки построчно (`StrPurge` — хвостовые пробелы срезаются); `$EndLIBRARY` **пропускается** (`:654`); блок старого одноимённого модуля пропускается до `$EndMODULE` (`:657-670`) |
| Новый модуль | `:675-677` | `m_TimeStamp` временно = 0 → `aModule->Save( dest )` → `fprintf( dest, "$EndLIBRARY\n" )` |
| Замена | `:684-706` | старый файл → `.bak`, временный `.$$$` → `.mod` |

Итог: в библиотеке, записанной KiCad, у модулей `Po … 00000000 00000000` и `Sc 00000000` (кроме `m_LastEdit_Time`, который остаётся).

### 4.4 Удаление модуля — `Delete_Module_In_Library` (`:224-392`)

Тот же перезаписывающий алгоритм. Заголовок (`:310-313`) содержит опечатку кода: `fprintf( dest, "  %s\n$", … ); fprintf( dest, "# encoding utf-8\n");` → вторая строка `$# encoding utf-8` (не `#…`, поэтому `FILTER_READER` её **не** пропускает; безвредна — не совпадает ни с `$INDEX`, ни с `$MODULE`).

### 4.5 Создание пустой библиотеки — `Create_Librairie` (`:798-834`)

`fprintf( lib_module, ENTETE_LIBRAIRIE ); fprintf( lib_module, "  %s\n", DateAndTime( cbuf ) ); fputs( "$INDEX\n" ); fputs( "$EndINDEX\n" );` (`:820-830`) — **без** `# encoding` и без `$EndLIBRARY`; `$EndLIBRARY` появится при первом `Save_Module_In_Library`.

---

## 5. Блок `$MODULE … $EndMODULE`

### 5.1 Запись — `MODULE::Save` (`pcbnew/class_module.cpp:259-357`)

Порядок строго такой (`goto out` при ошибке любого вложенного `Save`):

| # | Формат (дословно) | Аргументы | Условие | Строка |
|---|---|---|---|---|
| 1 | `"$MODULE %s\n"` | `m_LibRef` | всегда | `:266` |
| 2 | `"Po %d %d %d %d %8.8lX %8.8lX %s\n"` | `m_Pos.x, m_Pos.y, m_Orient, m_Layer, m_LastEdit_Time, m_TimeStamp, statusTxt` | всегда | `:279-282` |
| 3 | `"Li %s\n"` | `m_LibRef` | всегда | `:284` |
| 4 | `"Cd %s\n"` | `m_Doc` | `!m_Doc.IsEmpty()` | `:286-289` |
| 5 | `"Kw %s\n"` | `m_KeyWord` | `!m_KeyWord.IsEmpty()` | `:291-294` |
| 6 | `"Sc %8.8lX\n"` | `m_TimeStamp` | всегда | `:296` |
| 7 | `"AR %s\n"` | `m_Path` | всегда (в библиотеке пусто → `AR ` с пробелом) | `:297` |
| 8 | `"Op %X %X 0\n"` | `m_CntRot90, m_CntRot180` | всегда | `:298` |
| 9 | `".SolderMask %d\n"` | `m_LocalSolderMaskMargin` | `!= 0` | `:299-300` |
| 10 | `".SolderPaste %d\n"` | `m_LocalSolderPasteMargin` | `!= 0` | `:301-302` |
| 11 | `".SolderPasteRatio %g\n"` | `m_LocalSolderPasteMarginRatio` | `!= 0` | `:303-304` |
| 12 | `".LocalClearance %d\n"` | `m_LocalClearance` | `!= 0` | `:305-306` |
| 13 | `"At "` + `"SMD "` + `"VIRTUAL "` + `"\n"` | флаги `MOD_CMS`, `MOD_VIRTUAL` | `m_Attributs != MOD_DEFAULT` | `:309-317` |
| 14 | `T0 …` | `m_Reference->Save` | всегда | `:320` |
| 15 | `T1 …` | `m_Value->Save` | всегда | `:324` |
| 16 | `T2 …` / `DS|DC|DA|DP …` | `m_Drawings` по порядку, только `TYPE_TEXTE_MODULE` и `TYPE_EDGE_MODULE` | по списку | `:328-343` |
| 17 | `$PAD … $EndPAD` | `m_Pads` по порядку (`D_PAD::Save`, часть B) | по списку | `:346-349` |
| 18 | `$SHAPE3D … $EndSHAPE3D` | `Write_3D_Descr` (см. §8) | имя формы непустое | `:351` |
| 19 | `"$EndMODULE  %s\n"` (два пробела) | `m_LibRef` | всегда | `:353` |

`statusTxt` (`:268-277`): `[0]` = `F` если `IsLocked()` иначе `~`; `[1]` = `P` если `MODULE_is_PLACED` иначе `~`; итого `~~`, `F~`, `~P`, `FP`.

`%8.8lX` — 8 hex-цифр в верхнем регистре с ведущими нулями (`00000000`). `m_LastEdit_Time` по умолчанию `time(NULL)` (`:40`), `m_TimeStamp` при сохранении в библиотеку = 0 (§4.3).

Умолчания конструктора (`:31-52`): `m_Attributs=MOD_DEFAULT`, `m_Layer=LAYER_N_FRONT`(15), `m_Orient=0`, `m_ModuleStatus=0`, `m_CntRot90=m_CntRot180=0`, все локальные зазоры 0; создаются `m_Reference` (тип 0) и `m_Value` (тип 1); один пустой `S3D_MASTER`.

### 5.2 Чтение — `MODULE::ReadDescr` (`pcbnew/class_module.cpp:473-620`)

Строка `$MODULE` уже прочитана вызывающим. Цикл `while( aReader->ReadLine() )` (`:479`), возвращает **всегда 0** (`:619`); EOF без `$EndMODULE` — не ошибка.

Диспетчер по `Line[0]` (после проверки `$`):

| Префикс | Код | Разбор | Примечания |
|---|---|---|---|
| `$E…` | `:484-485` | `break` — конец модуля | любая строка `$E*` (`$EndMODULE`) |
| `$P…` | `:486-495` | `new D_PAD(this)`; `pad->ReadDescr(aReader)`; `RotatePoint(&pad->m_Pos, m_Orient)`; `pad->m_Pos += m_Pos`; `m_Pads.PushBack` | координаты пада в файле относительны модуля при ориентации 0; `Po` должна идти **раньше** падов |
| `$S…` | `:496-497` | `Read_3D_Descr(aReader)` (§8) | затем строка `$EndSHAPE3D` попадает в `switch` и игнорируется |
| любая, `strlen(Line) < 4` | `:500-501` | пропуск | длина **с** `\n`; `AR\n` (3) пропускается, `AR \n` (4) — нет |
| `P` (`Po`) | `:510-522` | `sscanf( PtLine, "%d %d %d %d %lX %lX %s", &m_Pos.x, &m_Pos.y, &m_Orient, &m_Layer, &m_LastEdit_Time, &m_TimeStamp, BufCar1 )`; `m_ModuleStatus=0`; `BufCar1[0]=='F'` → `SetLocked(true)`; `BufCar1[1]=='P'` → `MODULE_is_PLACED` | результат `sscanf` не проверяется; недостающие поля остаются как были; `PtLine = Line+3` (`:503`) |
| `L` (`Li`) | `:525-528` | `sscanf( PtLine, " %s", BufLine )` → `m_LibRef` | имя без пробелов |
| `S` (`Sc`) | `:531-532` | `sscanf( PtLine, " %lX", &m_TimeStamp )` | |
| `O` (`Op`) | `:536-549` | `sscanf( PtLine, " %X %X", &itmp1, &itmp2 )`; `m_CntRot180 = itmp2 & 0x0F` (>10 → 10); `m_CntRot90 = itmp1 & 0x0F` (>10 → 0) `| ((itmp1>>4)&0x0F, >10 → 0) << 4` | третье число `0` не читается |
| `At` | `:552-559` | `strstr(PtLine,"SMD")` → `\|= MOD_CMS`; `strstr(PtLine,"VIRTUAL")` → `\|= MOD_VIRTUAL` | только установка битов |
| `AR` | `:561-566` | `sscanf( PtLine, " %s", BufLine )` → `m_Path` | при пустом `AR ` `sscanf` ничего не пишет, `BufLine` хранит имя из `Li` → `m_Path` = имя модуля (в библиотеке не важно) |
| `T` | `:570-583` | `sscanf( Line + 1, "%d", &itmp1 )`: `0` → `m_Reference`, `1` → `m_Value`, иначе `new TEXTE_MODULE(this)` в `m_Drawings`; `textm->ReadDescr(aReader)` (§6) | второй `T0`/`T1` перезапишет ссылку/значение |
| `D` | `:586-591` | `new EDGE_MODULE(this)` в `m_Drawings`; `edge->ReadDescr(aReader)` (§7); `edge->SetDrawCoord()` | любая строка `D*` (кроме `Dl` внутри `DP`) |
| `C` (`Cd`) | `:594-595` | `m_Doc = FROM_UTF8( StrPurge( PtLine ) )` | до конца строки, пробелы допустимы |
| `K` (`Kw`) | `:598-599` | `m_KeyWord = FROM_UTF8( StrPurge( PtLine ) )` | |
| `.` | `:602-611` | `.SolderMask ` (12) → `atoi(Line+12)`; `.SolderPaste ` (13) → `atoi(Line+13)`; `.SolderPasteRatio ` (18) → `atof(Line+18)`; `.LocalClearance ` (16) → `atoi(Line+16)` | `strnicmp` с пробелом в образце |
| прочее | `:614-615` | игнорируется | в т.ч. `$EndSHAPE3D`, `$EndPAD` не встречаются здесь |

Финал: `Set_Rectangle_Encadrement()` (`:618`).

Обязательные строки: формально — ни одной (все поля имеют умолчания). Практически: `Po` (иначе слой 15 / позиция 0 из конструктора), `Li` (иначе `m_LibRef` пуст → в `.brd` не найдётся при перезагрузке), `T0`/`T1` (иначе ссылка/значение — пустой текст на слое 21 размером 400, толщиной 120, `class_text_mod.cpp:33-35`).

---

## 6. Строка текста `T<n>`

### 6.1 Запись — `TEXTE_MODULE::Save` (`pcbnew/class_text_mod.cpp:71-94`)

```c
fprintf( aFile, "T%d %d %d %d %d %d %d %c %c %d %c %s\n",
         m_Type,                      // 0 ref, 1 value, 2 прочий
         m_Pos0.x, m_Pos0.y,          // относительно центра модуля при ориентации 0
         m_Size.y, m_Size.x,          // ВНИМАНИЕ: сначала Y (высота), потом X (ширина)
         orient,                      // m_Orient + parent->m_Orient, 0.1°  (:73-79)
         m_Thickness,
         m_Mirror ? 'M' : 'N',
         m_NoShow ? 'I' : 'V',        // I = invisible, V = visible
         GetLayer(),
         m_Italic ? 'I' : 'N',
         EscapedUTF8( m_Text ).c_str() );   // "текст", " → \"
```

Возврат `ret > 20` (`:93`). Пример: `T0 0 -1500 500 500 0 100 N V 21 N "dip14"`.

### 6.2 Чтение — `TEXTE_MODULE::ReadDescr` (`:103-180`)

| Шаг | Код | Поведение |
|---|---|---|
| Разбор | `:116-123` | `sscanf( line + 1, "%d %d %d %d %d %d %d %s %s %d %s", &type, &m_Pos0.x, &m_Pos0.y, &m_Size.y, &m_Size.x, &m_Orient, &m_Thickness, BufCar1, BufCar2, &layer, BufCar3 )`; `>= 10` → success (но `success` уже `true` в `:105` → функция **всегда** возвращает 1) |
| Тип | `:126-129` | не 0 и не 1 → `TEXT_is_DIVERS` (2) |
| Ориентация | `:133` | `m_Orient -= parent->m_Orient` (в файле — абсолютная) |
| Флаги | `:135-148` | `BufCar1[0]=='M'` → зеркало; `BufCar2[0]=='I'` → невидим; `BufCar3[0]=='I'` → курсив; любой другой символ → false. `BufCar3` необязателен (10 полей достаточно) |
| Слой | `:151-158` | `<0` → 0; `>28` → 28; `0` (`LAYER_N_BACK`) → 20 (`SILKSCREEN_N_BACK`); `15` (`LAYER_N_FRONT`) → 21 (`SILKSCREEN_N_FRONT`); умолчание при отсутствии — 21 (`:109`) |
| Координаты | `:163`, `:211-225` | `m_Pos = RotatePoint(m_Pos0, module.m_Orient) + module.m_Pos` |
| Текст | `:167` | `ReadDelimitedText( &m_Text, line )` — первая `"` во всей строке (`common/string.cpp:11-60`) |
| Размер | `:170-173` | `m_Size.x/y < TEXTS_MIN_SIZE(50)` → 50 |
| Толщина | `:176-178` | `< 1` → 1; `Clamp_Text_PenSize(m_Thickness, m_Size)` = не больше `min(size.x, size.y) / 4` (`common/drawtxt.cpp:55-72`, `aBold=true` по умолчанию `include/drawtxt.h:28`) |

Умолчания конструктора (`:23-57`): размер 400×400, толщина 120, слой 21; если слой модуля 0 (`Back`) → слой 20 и `m_Mirror=true`.

---

## 7. Графика `DS` / `DC` / `DA` / `DP`

Координаты `m_Start0/m_End0` — относительно начала модуля при ориентации 0 (`pcbnew/class_edge_mod.h:18-19`); при чтении `SetDrawCoord` поворачивает на `m_Orient` модуля и прибавляет `m_Pos` (`class_edge_mod.cpp:124-138`). Умолчания: `S_SEGMENT`, `m_Angle=0`, `m_Width=120` (`:29-32`).

### 7.1 Запись — `EDGE_MODULE::Save` (`pcbnew/class_edge_mod.cpp:310-361`)

| `m_Shape` | Формат (дословно) | Аргументы | Строка |
|---|---|---|---|
| `S_SEGMENT` (0) | `"DS %d %d %d %d %d %d\n"` | `m_Start0.x, m_Start0.y, m_End0.x, m_End0.y, m_Width, m_Layer` | `:317-321` |
| `S_CIRCLE` (3) | `"DC %d %d %d %d %d %d\n"` | центр `m_Start0`, точка на окружности `m_End0`, `m_Width, m_Layer` | `:324-328` |
| `S_ARC` (2) | `"DA %d %d %d %d %d %d %d\n"` | центр `m_Start0`, начало дуги `m_End0`, `m_Angle` (0.1°), `m_Width, m_Layer` | `:331-336` |
| `S_POLYGON` (4) | `"DP %d %d %d %d %d %d %d\n"` + N × `"Dl %d %d\n"` | `m_Start0, m_End0` (не используются), `m_PolyPoints.size(), m_Width, m_Layer`; затем каждая точка | `:339-348` |
| прочее (`S_RECT`, `S_CURVE`) | ничего не пишется, `ret=-1` | | `:351-357` |

Значения enum: `include/class_board_item.h:14-19`. Возврат `ret > 5` (`:361`).

### 7.2 Чтение — `EDGE_MODULE::ReadDescr` (`:375-484`)

| Шаг | Код | Поведение |
|---|---|---|
| Тип по `Line[1]` | `:384-405` | `S` → сегмент, `C` → круг, `A` → дуга, `P` → полигон; иначе диалог `Unknown EDGE_MODULE type <…>`, `error=1`, разбор как 6 полей (`:463-467`) |
| Дуга | `:409-414` | `sscanf( Line + 3, "%d %d %d %d %d %d %d", &m_Start0.x, &m_Start0.y, &m_End0.x, &m_End0.y, &m_Angle, &m_Width, &m_Layer )`; `NORMALIZE_ANGLE_360` (`include/macros.h:78-81`: `while <-3600 += 3600; while > 3600 -= 3600`) |
| Сегмент / круг | `:416-421` | `sscanf( Line + 3, "%d %d %d %d %d %d", &m_Start0.x, &m_Start0.y, &m_End0.x, &m_End0.y, &m_Width, &m_Layer )` |
| Полигон | `:423-458` | 7 полей как у дуги, но 5-е — `pointCount`; затем ровно `pointCount` строк, каждая должна начинаться с `Dl` (`strncmp 2`), `sscanf( Buf + 3, "%d %d\n", &x, &y )`; иная строка или EOF → `error=1`, `break` |
| Толщина | `:472-475` | `<= 1` → 1; `> MAX_WIDTH(10000)` → 10000 |
| Слой | `:480-481` | `< 0` или `> 28` → `SILKSCREEN_N_FRONT` (21); медные слои допускаются (СВЧ-модули) |
| Возврат | `:482` | `error` — вызывающий `MODULE::ReadDescr` его **игнорирует** (`class_module.cpp:589`) |

Результат `sscanf` нигде не проверяется; недостающие поля остаются из конструктора.

---

## 8. Блок `$SHAPE3D`

Запись `MODULE::Write_3D_Descr` (`pcbnew/class_module.cpp:362-398`), для каждого `S3D_MASTER` с непустым `m_Shape3DName`:

```
$SHAPE3D                       ← :371
Na "<EscapedUTF8 имя файла>"   ← :373
Sc %lf %lf %lf                 ← :375-379  масштаб;  to_point() заменяет ',' на '.'
Of %lf %lf %lf                 ← :381-385  смещение
Ro %lf %lf %lf                 ← :387-391  поворот
$EndSHAPE3D                    ← :393
```

Чтение `Read_3D_Descr` (`:404-465`): если у текущего `S3D_MASTER` имя уже есть — создаётся новый (`:409-416`); по `Line[0]`: `$` + `E` → return 0, другой `$` → return 1; `N` → `ReadDelimitedText(buf, Line+3, 512)`; `S`/`O`/`R` → `sscanf( text, "%lf %lf %lf\n", …)`. В библиотеке без 3D-моделей блок отсутствует.

---

## 9. Что роняет или искажает загрузку

| Ситуация | Эффект | Код |
|---|---|---|
| Первые 18 байт первой непустой/не-`#` строки ≠ `PCBNEW-LibModule-V` | библиотека отвергнута (диалог, `NULL`) | `loadcmp.cpp:254-263`, `footprint_info.cpp:79-86` |
| Нет `$INDEX` или имени в нём | `Get_Librairie_Module` не находит модуль, хотя `$MODULE` есть; в списке CvPcb модуль виден | `loadcmp.cpp:266-285` vs `footprint_info.cpp:98-104` |
| `$MODULE` раньше `$INDEX` | поиск индекса прерывается, модуль не найден | `loadcmp.cpp:268-269` |
| Имя модуля с пробелом | в `$MODULE` берётся `StrPurge(Line+8)` (весь хвост), в `Li` — `%s` (до пробела), в `Save_Module_In_Library` — `%s` (`:661`) → рассинхрон имён | `loadcmp.cpp:303-304`, `class_module.cpp:527`, `librairi.cpp:661` |
| Строка длиной < 4 байт (с `\n`) внутри модуля | молча пропускается | `class_module.cpp:500-501` |
| `Po` после `$PAD` | пады сдвинуты/повёрнуты по старым `m_Pos/m_Orient` (0,0 / 0) | `class_module.cpp:489-491` |
| `T<n>` без `"` | `ReadDelimitedText` не находит кавычку → текст пуст | `common/string.cpp:11-60` |
| Текст размером < 50 или толщиной > size/4 | молча приводится к границе | `class_text_mod.cpp:170-178` |
| Слой текста 0 / 15 | заменяется на 20 / 21 | `class_text_mod.cpp:155-158` |
| Слой графики вне 0..28 | → 21 | `class_edge_mod.cpp:480-481` |
| `DP` с меньшим числом `Dl` | `error=1`, но модуль загружается, полигон усечён | `class_edge_mod.cpp:437-457`, `class_module.cpp:589` |
| Неизвестный `D?` | модальный диалог `Unknown EDGE_MODULE type`, элемент всё равно создан | `class_edge_mod.cpp:399-404` |
| Нет `$EndMODULE` | чтение до EOF без ошибки; следующий модуль «съедается» | `class_module.cpp:479-485` |
| Строка длиннее 100000 байт | `IO_ERROR "Line length exceeded"` | `common/richio.cpp:115-116` |
| Числа с `,` как десятичным разделителем | `%g`/`%lf` пишутся/читаются в локали `C` (`SetLocaleTo_C_standard`), только `.` | `librairi.cpp:198`, `loadcmp.cpp:312` |
