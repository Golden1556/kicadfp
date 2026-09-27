# Раскладка пробелов и переводов строк в файлах `.kicad_mod` по версиям KiCad

Статус: спецификация для реализации форматтера kicadfp. Цель: для **неизменённого** дерева
форматтер выдаёт **байт-в-байт** то же, что записал бы KiCad соответствующей версии.

Обозначения:

* `@n` — отступ уровня n. В KiCad 5/6/7 это `n × 2` пробела, в KiCad 8+ это `n` табуляций.
* `→` в примерах означает табуляцию, `¶` — конец строки (`\n`).
* Ссылки вида `9.0/kicad_io_utils.cpp:89` указывают на файлы в
  `scratchpad/kicad-src/<ветка>/` (имя = путь в репозитории, в котором `/` заменён на `_`;
  здесь для краткости путь сокращён до последнего компонента). Ссылки `tags/X-file` — это
  файлы, скачанные с тегов gitlab (`scratchpad/kicad-src/tags/`).
* «Корпус» — реальные файлы библиотек kicad-footprints (см. раздел «Проверено»).

Содержание:

1. [Кратко: какой стиль у какой версии файла](#1-кратко)
2. [KiCad 8 / 9 / 10: `KICAD_FORMAT::Prettify`](#2-kicad-8--9--10-kicad_formatprettify)
3. [KiCad 6.0 и 7.0 (и 5.1, и ночные 5.99): отступы, зашитые в writer](#3-kicad-60-и-70-и-51-и-599)
4. [Итоговая таблица и рекомендации](#4-итог-и-рекомендации)
5. [Проверено](#5-проверено)
6. [Открытые вопросы](#6-открытые-вопросы)
7. [Приложение A. `prettify.py` — порт Prettify (полный код)](#приложение-a-prettifypy)
8. [Приложение B. `layout67.py` — табличная раскладка 5.1/5.99/6.0/7.0 (полный код)](#приложение-b-layout67py)

---

## 1. Кратко

| Признак файла | Кто пишет | Стиль |
|---|---|---|
| корень `(module ...)`, нет `(version)` | KiCad 5.x (`pcbnew/kicad_plugin.cpp`) | «5.1»: 2 пробела на уровень, раскладка зашита в `Print()` (§3) |
| `(footprint ...)`, `version` 20200000…20211013 | ночные сборки 5.99 | «5.99» = «6.0», но весь заголовок, включая `(layer)`, в первой строке (§3.3) |
| `version 20211014` | KiCad 6.0.x | «6.0» (§3); 6.0.0–6.0.6 пишут `(pads X )` в `keepout` (§3.9) |
| `version 20221018` | KiCad 7.0.x | «7.0» (§3) |
| `version 20240108` | KiCad 8.0.x | `Prettify` (§2); 8.0.0/8.0.1 — **без** `\n` в конце файла, 8.0.2+ — с `\n` |
| `version 20241229` | KiCad 9.0.x | `Prettify` (§2) |
| `version ≥ 20250000` (корпус: 20260206; `master` сейчас 20260901) | KiCad 10-dev | `Prettify` (§2) с `FORMAT_MODE::NORMAL` |
| `(generator "kicad-footprint-generator")` + version 20240108/20260206 | внешний генератор | как `Prettify`, но **каждая** `(xy …)` на своей строке (§2.7) |

В режиме по умолчанию (`m_CompactSave = false`, §2.5) Prettify версий 8.0, 9.0 и master для
файла с одним корневым списком выдаёт **одинаковый** результат (проверено перекрёстно на всём
корпусе, §5), так что для KiCad 8/9/10 достаточно одной реализации.

---

## 2. KiCad 8 / 9 / 10: `KICAD_FORMAT::Prettify`

### 2.1. Как устроена запись

1. Writer (`PCB_IO_KICAD_SEXPR::format(...)`) печатает дерево в буфер через
   `OUTPUTFORMATTER::Print`. Для `.kicad_mod` используется `PRETTIFIED_FILE_OUTPUTFORMATTER`:
   `8.0/pcb_io_kicad_sexpr.cpp:127`, `9.0/pcb_io_kicad_sexpr.cpp:131`,
   `master/pcb_io_kicad_sexpr.cpp:129` (в `FP_CACHE::Save`).
2. `PRETTIFIED_FILE_OUTPUTFORMATTER::write()` ничего не пишет на диск, а только дописывает
   байты в `std::string m_buf` (`9.0/richio.cpp:649-652`, `master/richio.cpp:733`).
3. `Finish()` (вызывается явно или из деструктора) делает `KICAD_FORMAT::Prettify(m_buf, …)`
   и записывает результат в файл одним `fwrite`:
   * 8.0: `Prettify( m_buf )` (`8.0/richio.cpp:614`), сигнатура
     `Prettify( std::string&, char aQuoteChar = '"' )` (`8.0/kicad_io_utils.h:44`);
   * 9.0: `Prettify( m_buf, ADVANCED_CFG::GetCfg().m_CompactSave )` (`9.0/richio.cpp:637`);
   * master: `Prettify( m_buf, m_mode )` (`master/richio.cpp:714`), где `m_mode` — аргумент
     конструктора (по умолчанию `FORMAT_MODE::NORMAL`, `master/richio.h:525-527`), который
     конструктор заменяет на `COMPACT_TEXT_PROPERTIES`, если `m_CompactSave` включён и режим
     был `NORMAL` (`master/richio.cpp:702-703`). Writer `.kicad_mod` передаёт только имя
     файла (`master/pcb_io_kicad_sexpr.cpp:129`), т. е. режим `NORMAL`.
4. Файл открывается в режиме `"wt"` (`9.0/richio.h:518`, `master/richio.h:527`).
   На POSIX это просто `\n`. Что происходит на Windows (текстовый режим CRT → `\r\n`?) —
   **не проверено** (§6).

`Prettify` появился в коммите `f1f8981395aa` «Automatic whitespace and indentation
prettification for sexpr formats» от 2023-11-29 (история `common/io/kicad/kicad_io_utils.cpp`
через gitlab API). Судя по датам коммитов, файлы с `version ≥ 20231212` уже записаны
с Prettify; для ночных версий 20231014…20231211 — **не проверено**.

### 2.2. Что приходит на вход Prettify

**9.0 и master.** Writer печатает без переводов строк и без отступов:
`OUTPUTFORMATTER::Print( const char* fmt, ... )` — это просто `vsnprintf` + `write`
(`9.0/richio.cpp:492-506`; вариант с `nestLevel`, `9.0/richio.cpp:463-489`, writer 9.0 для
`.kicad_mod` не использует). Вызовы выглядят так:

```cpp
m_out->Print( "(footprint %s", m_out->Quotes( aFootprint->GetFPID().Format() ).c_str() );   // 9.0/pcb_io_kicad_sexpr.cpp:1097-1105
m_out->Print( "(version %d) (generator \"pcbnew\") (generator_version %s)", ... );           // :1109
m_out->Print( "(layer %s %s)", m_out->Quotew( LSET::Name( aLayer ) ).c_str(),
              aIsKnockout ? "knockout" : "" );                                               // :458-463
m_out->Print( "(at %s %s)", formatInternalUnits( pos ).c_str(),
              angle.IsZero() ? "" : FormatAngle( angle ).c_str() );                          // :1127, :1492
```

Поэтому сырой буфер содержит, например:

```
(footprint "R_0603"(version 20241229) (generator "pcbnew") (generator_version "9.0")(layer "F.Cu" )(pad "1" smd roundrect(at -0.775 0 )(size 0.9 0.95)...
```

Обратите внимание на `(layer "F.Cu" )` и `(at -0.775 0 )` — лишний пробел перед `)` от
пустого `%s`, и отсутствие пробела между `"R_0603"` и `(version`. Prettify удаляет пробел
перед `)` (правило `next != ')'`), а перед `(` всегда вставляет перевод строки или `" ("`
независимо от наличия пробела во входе (правило `next != '('`). Итог: `→(layer "F.Cu")`,
`→→(at -0.775 0)`.

Единственный многострочный фрагмент в сыром выводе 9.0 — данные встроенных файлов:
`aOut.Print( "\n%1s%.*s%s\n", first ? "" : "|", length, view.data(), remaining == length ? "|" : "" )`
(`9.0/embedded_files.cpp:201`); Prettify превращает эти `\n` в пробелы/переносы по общим
правилам (§2.4, пример в §2.8).

**8.0.** Writer ещё печатает «по-старому» — с `Print( aNestLevel, ... )` и явными `\n`
(`8.0/pcb_io_kicad_sexpr.cpp:1116-1127`:
`m_out->Print( 0, " (version %d) (generator \"pcbnew\") (generator_version \"%s\")\n ", ...)`),
но Prettify выбрасывает все пробелы/табуляции/переводы строк вне кавычек и расставляет свои,
так что результат от этого не зависит.

**Следствие для реализации.** Выход Prettify зависит от входа только через:

* последовательность байтов токенов (атомы, кавычки, скобки);
* **наличие** хотя бы одного пробельного символа между двумя соседними атомами и между `)` и
  следующим атомом (если пробела нет — атомы «склеятся»); количество и вид пробелов не важны;
* буквально три байта `x`,`y`,` ` сразу после `(` (`isXY`, §2.4) — т. е. после `xy` должен
  быть именно пробел, а не табуляция/перевод строки;
* алфавитный токен сразу после `(` (для компактных режимов, `isShortForm`/`isLib`).

Поэтому форматтер kicadfp может сериализовать дерево в одну строку по правилу
**«`(` + голова; каждому атому, кроме первого в списке, предшествует ровно один пробел;
вложенному списку не предшествует ничего; `)`»** (`serialize_oneline` в приложении A) и
прогнать через порт Prettify. В корпусе KiCad 8+ ни в одном списке атом не идёт после
вложенного списка (проверено скриптом `atom_after_list.py`: 0 случаев в 1377 + 3297 + 4882
файлах), так что вопрос о пробеле между `)` и атомом там на практике не возникает.

### 2.3. Состояние алгоритма (9.0, `9.0/kicad_io_utils.cpp:89-303`)

Константы (`:91-103`):

| Имя | Значение | Смысл |
|---|---|---|
| `quoteChar` | `'"'` | кавычка (в 8.0 это параметр `aQuoteChar`, по умолчанию `'"'`) |
| `indentChar` | `'\t'` | символ отступа |
| `indentSize` | `1` | символов отступа на уровень |
| `xySpecialCaseColumnLimit` | `99` | «список точек»: следующая `(xy` остаётся на той же строке, пока `column < 99` |
| `consecutiveTokenWrapThreshold` | `72` | пробел между атомами при `column ≥ 72` превращается в перевод строки |

Переменные (`:111-120`):

| Имя | Нач. знач. | Смысл |
|---|---|---|
| `listDepth` | 0 | текущая глубина вложенности (уже открытых `(`) |
| `lastNonWhitespace` | `0` | последний обработанный символ, прошедший через ветку «не пробел» (внутри кавычек это может быть и пробел!) |
| `inQuote` | false | внутри строки в кавычках |
| `hasInsertedSpace` | false | после последнего непробельного символа уже выведен разделитель |
| `inMultiLineList` | false | **один глобальный флаг** (не стек!): был перенос по порогу 72 |
| `inXY` | false | последний открытый список начинался с `xy ` |
| `inShortForm` | false | 9.0: внутри «короткой формы» (только при `aCompactSave`) |
| `shortFormDepth` | 0 | глубина, на которой открыта короткая форма |
| `column` | 0 | текущая колонка в **байтах**; табуляция считается за 1 |
| `backslashCount` | 0 | число подряд идущих `\` |

Вспомогательные функции (`:122-169`):

* `isWhitespace(c)`: `c ∈ {' ', '\t', '\n', '\r'}`.
* `nextNonWhitespace(it)`: первый символ с позиции `it` (включительно), не являющийся
  пробельным; `0`, если до конца только пробелы. **Кавычки не учитывает.**
* `isXY(it)` (где `*it == '('`): следующие три байта ровно `x`, `y`, `' '`.
* `isShortForm(it)`: собрать подряд идущие `isalpha()` символы после `(`; истина, если это
  `font`, `stroke`, `fill`, `offset`, `rotate`, `scale` (master: ещё `teardrop`,
  `master/kicad_io_utils.cpp:185-196`).
* master: `isLib(it)` — тот же токен равен `lib` (`master/kicad_io_utils.cpp:198-208`).

### 2.4. Основной цикл (построчно; `9.0/kicad_io_utils.cpp:171-302`)

Для каждого байта `c` входа (курсор `i`):

```
next = nextNonWhitespace(i)

ЕСЛИ isWhitespace(c) И НЕ inQuote:                                   # :175
    ЕСЛИ НЕ hasInsertedSpace И listDepth > 0 И lastNonWhitespace != '('
         И next != ')' И next != '(':                                  # :177-181
        ЕСЛИ inXY ИЛИ column < 72:            вывести ' ';  column += 1  # :183-189
        ИНАЧЕ ЕСЛИ inShortForm:               вывести ' '   (column НЕ увеличивается!)  # :190-193
        ИНАЧЕ: вывести '\n' + '\t'*listDepth; column = listDepth; inMultiLineList = true  # :194-200
        hasInsertedSpace = true                                         # :202
    (иначе пробел просто выбрасывается)
ИНАЧЕ:
    hasInsertedSpace = false                                            # :207
    ЕСЛИ c == '(' И НЕ inQuote:                                         # :209
        currentIsXY = isXY(i)
        currentIsShortForm = aCompactSave И isShortForm(i)
        ЕСЛИ вывод пуст:                      вывести '(';  column += 1   # :214-218  (8.0: ЕСЛИ listDepth == 0)
        ИНАЧЕ ЕСЛИ inXY И currentIsXY И column < 99:
                                              вывести ' ('; column += 2   # :219-224
        ИНАЧЕ ЕСЛИ inShortForm:               вывести ' ('; column += 2   # :225-229
        ИНАЧЕ: вывести '\n' + '\t'*listDepth + '('; column = listDepth + 1  # :230-235
        inXY = currentIsXY                                              # :237
        ЕСЛИ currentIsShortForm: inShortForm = true; shortFormDepth = listDepth   # :239-243
        listDepth += 1                                                  # :245
    ИНАЧЕ ЕСЛИ c == ')' И НЕ inQuote:                                   # :247
        ЕСЛИ listDepth > 0: listDepth -= 1
        ЕСЛИ inShortForm:                     вывести ')';  column += 1   # :252-256
        ИНАЧЕ ЕСЛИ lastNonWhitespace == ')' ИЛИ inMultiLineList:
            вывести '\n' + '\t'*listDepth + ')'; column = listDepth + 1; inMultiLineList = false  # :257-263
        ИНАЧЕ:                                вывести ')';  column += 1   # :264-268
        ЕСЛИ shortFormDepth == listDepth: inShortForm = false; shortFormDepth = 0   # :270-274
    ИНАЧЕ:                                                              # :276-291
        ЕСЛИ c == '\\': backslashCount += 1
        ИНАЧЕ ЕСЛИ c == '"' И (backslashCount чётно): inQuote = НЕ inQuote
        ЕСЛИ c != '\\': backslashCount = 0
        вывести c; column += 1
    lastNonWhitespace = c                                               # :293
В конце: вывести '\n'                                                   # :299-300 (нет в 8.0.0/8.0.1)
```

Разбор правил на словах:

* **Открывающая скобка.** Каждый вложенный список начинается с новой строки с отступом
  `listDepth` табуляций, где `listDepth` — глубина *родителя* (корень → 0 табуляций,
  его дети → 1 и т. д.). Исключения: самая первая `(` файла (без перевода строки);
  «список точек» — `(xy` после `(xy …)`, пока колонка < 99; внутри короткой формы.
* **Закрывающая скобка.** На отдельной строке (с отступом глубины этого списка), если
  предыдущий значащий символ был `)` (т. е. в списке были вложенные списки) или был перенос
  по порогу 72; иначе `)` приклеивается к последнему атому.
* **Пробелы.** Любая последовательность пробельных символов вне кавычек даёт максимум один
  разделитель; он выбрасывается сразу после `(`, перед `)`, перед `(` и на глубине 0.
  Разделитель — `' '`, пока `column < 72` (или внутри `xy`); иначе перевод строки с отступом
  `listDepth` (т. е. продолжение на уровень глубже, чем `(` самого списка).
* **Кавычки.** Пробелы внутри `"…"` копируются как есть и учитываются в `column`.
  `\"` не закрывает строку; `\\"` — закрывает (подсчёт чётности `\`, исправление
  `a5ffcd0a5580` от 2024-01-28, есть уже в 8.0.0 — `tags/8.0.0-kicad_io_utils.cpp`).
* **Колонки считаются в байтах** (`std::string`): многобайтный UTF-8 символ — несколько колонок.

Особенности («так в коде», сохранять при портировании):

1. `inMultiLineList` — один флаг на весь документ. После переноса по порогу 72 **первая же**
   следующая `)` (на любой глубине) уйдёт на свою строку. Пример (результат порта; реальных
   файлов с такой ситуацией в корпусе нет — **поведение KiCad выведено только из кода**):

   ```
   (a
   →(members "0123456789012345678901234567890" "0123456789012345678901234567890"
   →→"01234567890"
   →→(x 1
   →→)
   →)
   →(b 2)
   )
   ```
2. В ветке `inShortForm` пробел выводится без `column++` (`:190-193`).
3. `lastNonWhitespace` обновляется и для пробелов внутри кавычек.
4. Условие `inXY || column < 72` означает, что внутри `(xy …)` перенос по порогу 72 никогда
   не происходит (коммит `b13e244dc551` «Avoid space-wrapping while inside xy special case»).
5. `isXY` проверяет *сырой вход*: `(xy` без последующего пробела (например, `(xy\t1 2)`)
   не считается точкой. Наш сериализатор всегда ставит пробел после головы.

### 2.5. `aCompactSave` / `FORMAT_MODE` и значения по умолчанию

* `ADVANCED_CFG::m_CompactSave` по умолчанию `false`: `8.0/advanced_config.cpp:234`,
  `9.0/advanced_config.cpp:262`, `master/advanced_config.cpp:284`; документация
  `9.0/advanced_config.h:246-256` («Default value: 0»). Включается строкой `CompactSave=1`
  в файле `kicad_advanced` в каталоге конфигурации KiCad (`9.0/advanced_config.cpp:59, 214`,
  ключ `:77`, регистрация `:415-416`).
* 9.0: при `aCompactSave = true` списки `font`, `stroke`, `fill`, `offset`, `rotate`,
  `scale` и всё внутри них пишутся в одну строку (`" ("` вместо перевода строки).
* master: `FORMAT_MODE { NORMAL, COMPACT_TEXT_PROPERTIES, LIBRARY_TABLE }`
  (`master/kicad_io_utils.h:77-82`). `COMPACT_TEXT_PROPERTIES` = компактный режим 9.0 плюс
  токен `teardrop`. `LIBRARY_TABLE` — строки `(lib …)` таблиц библиотек в одну строку
  (`master/kicad_io_utils.cpp:198-208, 265-269, 284-288, 302-306`); для `.kicad_mod` не
  используется. Особенность: в ветке закрытия `lib` (`:302-306`) `column` не увеличивается.
* 8.0: компактного режима в Prettify нет; `m_CompactSave` влияет только на writer
  (`formatPolyPts(..., m_CompactSave)`, `8.0/pcb_io_kicad_sexpr.cpp:987`), но Prettify всё
  равно пересобирает раскладку, поэтому на результат это не влияет.

Пример одного и того же дерева (вывод порта):

```
NORMAL (9.0/master по умолчанию)          9.0 aCompactSave / master COMPACT_TEXT_PROPERTIES
→(property "Reference" "REF**"            →(property "Reference" "REF**"
→→(at 0 -1.43 0)                           →→(at 0 -1.43 0)
→→(layer "F.SilkS")                        →→(layer "F.SilkS")
→→(uuid "a1")                              →→(uuid "a1")
→→(effects                                 →→(effects
→→→(font                                   →→→(font (size 1 1) (thickness 0.15))
→→→→(size 1 1)                             →→)
→→→→(thickness 0.15)                       →)
→→→)
→→)
→)
```

Файлов в компактном режиме в корпусе нет — компактный режим **на реальных файлах не проверен**.

### 2.6. Отличия 8.0 / 9.0 / master

| | 8.0 (`8.0/kicad_io_utils.cpp:65-236`) | 9.0 (`9.0/…:89-303`) | master (`master/…:111-353`) |
|---|---|---|---|
| Сигнатура | `Prettify(std::string&, char aQuoteChar='"')` | `Prettify(std::string&, bool aCompactSave)` | `Prettify(std::string&, FORMAT_MODE aMode=NORMAL)` |
| Первая `(` | `if( listDepth == 0 )` (`:169`) | `if( formatted.empty() )` (`:214`) | `if( formatted.empty() )` (`:254`) |
| Короткие формы | нет | `font stroke fill offset rotate scale` | + `teardrop` |
| `lib`-строки | нет | нет | `LIBRARY_TABLE` |
| `\n` в конце | 8.0.0, 8.0.1: **нет**; 8.0.2…8.0.9: есть (`tags/8.0.X-kicad_io_utils.cpp`) | есть (9.0.0 = ветка 9.0) | есть |

Для файла с одним корневым списком `listDepth == 0` и `formatted.empty()` эквивалентны (до
первой `(` вывод пуст, а после неё `listDepth ≥ 1` до закрытия корня). В 8.0 в ветке `xy` есть
лишнее `inXY = true` (`:179`), перезаписываемое на `:188`, — на результат не влияет.

### 2.7. Стиль kicad-footprint-generator

Файлы с `(generator "kicad-footprint-generator")` (в 9.0 и master это 1437 и 4239 файлов
корпуса) пишет не KiCad. Их раскладка совпадает с Prettify байт-в-байт **за одним
исключением**: каждая `(xy …)` стоит на своей строке (как Prettify с `xySpecialCaseColumnLimit = 0`):

```
→(fp_poly                          ← Package_DFN_QFN.pretty/AO_AOZ666xDI_DFN-8-1EP_3x3mm_P0.65mm_EP1.25x2.7mm.kicad_mod (v9.0.0)
→→(pts
→→→(xy -2.04 -1.29)
→→→(xy -2.52 -1.29)
→→→(xy -2.04 -1.77)
→→→(xy -2.04 -1.29)
→→)
```

KiCad при пересохранении такого файла сведёт точки в строки до колонки 99. Для
побайтового round-trip неизменённого файла стиль нужно распознавать (§4).

### 2.8. Примеры из реальных файлов

Перенос списка точек по колонке 99 (`v9.0.0/Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod:150-151`):

```
→→→(xy 10.75 7.25) (xy -10.85 7.25) (xy -10.85 5) (xy -16.25 5) (xy -16.25 -5) (xy -10.75 -5) (xy -10.75 -7.25)
→→→(xy 10.75 -7.25)
```

`(xy -10.75 -7.25)` начинается в колонке 93 (< 99) — остаётся на строке; следующая `(xy`
была бы в колонке 111 (≥ 99) — новая строка. Проверка идёт по колонке *начала* `(xy`,
поэтому строки бывают длиннее 99 байт (в корпусе 9.0 — до 120).

Перенос по порогу 72 (`v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod:91-96`):

```
→→(layers "F.Cu" "B.Cu" "In1.Cu" "In2.Cu" "In3.Cu" "In4.Cu" "In5.Cu" "In6.Cu"
→→→"In7.Cu" "In8.Cu" "In9.Cu" "In10.Cu" "In11.Cu" "In12.Cu" "In13.Cu" "In14.Cu"
→→→"In15.Cu" "In16.Cu" "In17.Cu" "In18.Cu" "In19.Cu" "In20.Cu" "In21.Cu"
→→→"In22.Cu" "In23.Cu" "In24.Cu" "In25.Cu" "In26.Cu" "In27.Cu" "In28.Cu"
→→→"In29.Cu" "In30.Cu"
→→)
```

и `(members …)` группы (`v9.0.0/Package_DIP.pretty/DIP-24_18.0mmx34.29mm_W15.24mm_Socket.kicad_mod:384-388`).
Закрывающая `)` списка с переносом — на своей строке (флаг `inMultiLineList`).

Встроенные данные (`(embedded_files (file … (data …)))`) в корпусе не встречаются. По коду
(`9.0/embedded_files.cpp:190-206` + Prettify) ожидается `(data |XXXX…` (первая порция base64
на строке `(data`, т. к. колонка < 72), далее каждая порция по 76 символов на своей строке с
отступом `listDepth`, последняя оканчивается на `|`, и `)` на отдельной строке. **Не проверено
на реальных файлах.**

---

## 3. KiCad 6.0 и 7.0 (и 5.1, и 5.99)

### 3.1. Механизм

Для библиотеки footprint'ов 5.1/6.0/7.0 используют обычный `FILE_OUTPUTFORMATTER`
(`5.1/kicad_plugin.cpp:218`, `6.0/pcb_plugin.cpp:201`, `7.0/pcb_plugin.cpp:123`), который
пишет байты сразу в файл; Prettify нет. Вся раскладка — в строках формата:

* `OUTPUTFORMATTER::Print( int nestLevel, const char* fmt, … )` сначала печатает
  `nestLevel` раз `sprint( "%*c", NESTWIDTH, ' ' )`, т. е. **2 пробела на уровень**
  (`#define NESTWIDTH 2`: `5.1/richio.cpp:406,418`, `6.0/richio.cpp:428,440`,
  `7.0/richio.cpp:459,471`), затем `fmt`.
* Отступ ставится **только** в начале каждого вызова `Print` с `nestLevel > 0`, и только
  «как есть»: если предыдущий вызов не закончился `\n`, отступ окажется посреди строки
  (источник нескольких странностей, §3.9).
* `\n` ставятся явно в `fmt`. Файл всегда заканчивается `")\n"` корня
  (`6.0/pcb_plugin.cpp:1286`: `m_out->Print( aNestLevel, ")\n" )`; 5.1: `5.1/kicad_plugin.cpp:1149`).
* Корень пишется с `aNestLevel = 0`, его дети — с 1.

Табличная реализация — приложение B (`layout67.py`, словарь `HANDLER`/`LAYOUT_RULES` +
методы `Formatter`). Ниже — правила по типам узлов. `N` — уровень узла (для детей
footprint N = 1, т. е. 2 пробела).

### 3.2. Общее правило «однострочного» узла

Узел целиком в одну строку: `(`, голова, элементы через один пробел, `)` без пробела перед
ней (кроме ошибок, §3.9), затем `\n`. Так пишутся: `at`, `descr`, `tags`, `property`, `path`,
`autoplace_cost90/180`, `solder_mask_margin`, `solder_paste_margin`, `solder_paste_ratio`,
`clearance`, `zone_connect`, `thermal_width`, `thermal_gap`, `attr`, `private_layers`,
`net_tie_pad_groups` (`6.0/pcb_plugin.cpp:1131-1216`, `7.0/pcb_plugin.cpp:1180-1301`).
Пример: `  (descr "…")¶`, `  (attr smd)¶`.

### 3.3. `footprint` / `module` (заголовок)

| Writer | Раскладка | Источник |
|---|---|---|
| 5.1 | `(module NAME[ locked][ placed] (layer L) (tedit T)[ (tstamp X)]¶` | `5.1/kicad_plugin.cpp:1000-1019` |
| 5.99 (ночные, до 2021-11-13) | `(footprint "NAME" (version V) (generator pcbnew)[ locked][ placed] (layer "L")¶` + `  (tedit T)[ (tstamp U)]¶` | `tags/5.99-ee5f9034-kicad_plugin.cpp:1109-1125` |
| 6.0 | `(footprint "NAME" (version V) (generator pcbnew)¶` + `  [locked ][placed ](layer "L")¶` + `  (tedit T)[ (tstamp U)]¶` | `6.0/pcb_plugin.cpp:1106-1127` |
| 7.0 | как 6.0, но без `tedit`; `  (tstamp U)¶` отдельной строкой (если не `CTL_OMIT_TSTAMPS`; в библиотечном корпусе его нет) | `7.0/pcb_plugin.cpp:1155-1178` |

Вторая строка 6.0/7.0 начинается с **двух пробелов**, но это не отступ `Print`: `fmt` первой
строки оканчивается на `"\n "` (`6.0/pcb_plugin.cpp:1113`), а `formatLayer` печатает
`" (layer %s)"` с ведущим пробелом (`6.0/pcb_plugin.cpp:466-471`); `locked`/`placed` —
`" locked"`. Перевод `"\n "` появился в коммите `80c5b1efb1e3` (2021-11-13, «File formatting
improvements and fixes»); до него (ночные 5.99) всё было в первой строке.

Далее дети с отступом 2: `at`, `descr`, `tags`, `property`…, `attr`, затем
`fp_text reference`, `fp_text value`, графика, pads, zones, groups, models; `)¶` корня
(`6.0/pcb_plugin.cpp:1220-1286`, `7.0/pcb_plugin.cpp:1303-1369`). Порядок детей — тема другого документа; здесь он берётся из
дерева.

Реальный пример 6.0 (`kfp/v7.0.0/Resistor_THT.pretty/R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal.kicad_mod:1-5`):

```
(footprint "R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal" (version 20211014) (generator pcbnew)¶
  (layer "F.Cu")¶
  (tedit 5AE5139B)¶
  (descr "Resistor, Axial_DIN0204 series, …")¶
  (tags "Resistor Axial_DIN0204 series …")¶
```

Заголовок ночной сборки 5.99 (и 14 файлов с `version 20211014` из kicad-footprints 7.0.0,
записанных ночными сборками между 2021-10-15 и 2021-11-13), например
`kfpfull/v7/Inductor_SMD_Wurth.pretty/L_Wurth_WE-LQSH-2010.kicad_mod:1-2`:

```
(footprint "L_Wurth_WE-LQSH-2010" (version 20211014) (generator pcbnew) (layer "F.Cu")¶
  (tedit 6369AD97)¶
```

### 3.4. `fp_text`

5.1 / 6.0 (`5.1/kicad_plugin.cpp:1489-1546`, `6.0/pcb_plugin.cpp:1806-1868`):

```
@N (fp_text TYPE[ locked] TEXT (at X Y[ ANGLE][ unlocked]) (layer L)[ hide]¶      ← 5.1: без " locked"
@N+1 (effects (font (size H W) (thickness T)[ bold][ italic]) [(justify …)])¶      ← EDA_TEXT::Format(aNestLevel) печатает на +1
@N+1 (tstamp U)¶                                                               ← только 6.0
@N )¶
```

`effects` пишется `EDA_TEXT::Format( m_out, aNestLevel, … )` и внутри
`Print( aNestLevel + 1, "(effects" )` (`6.0/eda_text.cpp:539-545`) — одна строка.

7.0 (`7.0/pcb_plugin.cpp:1938-2003`): вызов стал `EDA_TEXT::Format( m_out, aNestLevel + 1, … )`
(`:1995`), а внутри по-прежнему `Print( aNestLevel + 1, "(effects" )`
(`7.0/eda_text.cpp:811-813`) ⇒ **`effects` на уровне N+2 (6 пробелов)**, `tstamp` на N+1
(`:1997`), затем при outline-шрифте `render_cache` на N+1 (`:1999-2000`), `)` на N.
Реальный пример (`kfpfull/v7/Sensor_Motion.pretty/Analog_LGA-16_3.25x3mm_P0.5mm_LayoutBorder3x5y.kicad_mod:6-9`):

```
  (fp_text reference "REF**" (at 0 -2.5) (layer "F.SilkS")¶
      (effects (font (size 1 1) (thickness 0.15)))¶
    (tstamp 17bab7e4-a5c5-4974-832d-5bcbbde0d6bb)¶
  )¶
```

`fp_text_box` (7.0, `7.0/pcb_plugin.cpp:2006-2051`): `@N (fp_text_box[ locked] TEXT¶`, затем
**на уровне N** (не N+1, `:2016`) `(start …) (end …)` или `formatPolyPts(…, N, true)`,
далее `[ (angle A)] (layer L) (tstamp U)¶`, `@N+2 (effects …)¶`, `@N+1 (stroke …)` **без**
`\n` (`:2045`), `[render_cache]`, `@N )¶` ⇒ строка вида `    (stroke …)  )`. На реальных
файлах **не проверено** (в корпусе нет `fp_text_box`).

### 3.5. Графика `fp_line`, `fp_rect`, `fp_circle`, `fp_arc`, `fp_curve`

* 5.1 (`5.1/kicad_plugin.cpp:890-963`) и 6.0 (`6.0/pcb_plugin.cpp:939-1069`) — одна строка:
  `@N (fp_line[ locked] (start X Y) (end X Y) (layer L) (width W)[ (fill solid|none)] (tstamp U))¶`
  (`fill` — только rect/circle/poly; `tstamp` и `locked` — только 6.0).
* 7.0 (`7.0/pcb_plugin.cpp:1032-1117`) — две строки: геометрия, затем `Print( 0, "\n" )`
  (`:1097`) и `STROKE_PARAMS::Format( m_out, …, aNestLevel + 1 )` (`:1099`,
  `7.0/stroke_params.cpp:227-248`):

```
  (fp_line (start -1.41 -2.64) (end 7.21 -2.64)¶
    (stroke (width 0.12) (type solid)) (layer "F.SilkS") (tstamp 534f3e7f-…))¶
```

  (`kfpfull/v7/Connector_Phoenix_SPT.pretty/PhoenixContact_SPT_1.5_2-H-3.5_1x02_P3.5mm_Horizontal.kicad_mod`).
  Вторая строка: `@N+1 (stroke …)[ (fill …)] (layer …) (tstamp …))¶`.

### 3.6. `fp_poly` и списки точек

**5.1** (`5.1/kicad_plugin.cpp:913-936`): `@N (fp_poly (pts` и точки через пробел; перед
каждой точкой с индексом `ii > 0`, `ii % 4 == 0` — `\n` и отступ N+1 (без ведущего пробела);
т. е. 4 точки на строку. Затем `)` (закрывает `pts`) и `" (layer L) (width W))¶"`.

**6.0** (`6.0/pcb_plugin.cpp:974-1034`, при `m_CompactSave = false`): `@N (fp_poly[ locked] (pts`,
**каждая** точка: `\n` + `@N+2 (xy X Y)` (дуги в контуре: `(arc (start) (mid) (end))` так же);
затем `\n`, `@N+1 )`, затем `" (layer L) (width W) (fill …) (tstamp U))¶"`:

```
  (fp_poly (pts¶
      (xy -2.45 -2.51)¶
      (xy -4.45 -2.51)¶
      …¶
    ) (layer "F.Cu") (width 0) (fill solid) (tstamp …))¶
```

(`kfpfull/v7/RF_Antenna.pretty/Texas_SWRA117D_2.4GHz_Left.kicad_mod:19-`).
При `m_CompactSave = true`: точки с индексом `ii % 4 == 0` начинают новую строку на N+2,
остальные дописываются через `" "` (`:985-1004`); индекс считает **сырые точки** контура,
включая точки, «поглощённые» дугой, — по дереву восстановить нельзя (§6).

**7.0** (`formatPolyPts`, `7.0/pcb_plugin.cpp:429-479`): `@N+1 (pts¶`, каждая фигура
(`xy` или `arc`) — `Print( aNestLevel + 2, … )`, после каждой `\n` (compact: после каждой
4-й; при этом отступ печатается перед **каждой** точкой, т. е. внутри строки будут пробелы
отступа), затем `@N+1 )¶`. Для `fp_poly` (`:1066-1075, 1097-1116`):

```
@N (fp_poly[ locked]¶
@N+1 (pts¶
@N+2 (xy …)¶   (по одной)
@N+1 )¶
¶                                    ← пустая строка: Print( 0, "\n" ) после ")\n"
@N+1 (stroke …) (fill …) (layer …) (tstamp …))¶
```

На реальных файлах 7.0 **не проверено** (в корпусе 7.0 нет `fp_poly`).

`fp_curve` во всех версиях — однострочный (в 7.0 — по схеме §3.5):
`(fp_curve (pts (xy …) (xy …) (xy …) (xy …)) …`.

### 3.7. `pad`

Общая схема 6.0/7.0 (`6.0/pcb_plugin.cpp:1376-1751`, `7.0/pcb_plugin.cpp:1459-1826`),
5.1 (`5.1/kicad_plugin.cpp:1245-1462`):

```
@N (pad NUM TYPE SHAPE[ locked] (at X Y[ A]) (size W H)[ (rect_delta …)][ (drill …)][ (property …)] (layers …)[ (remove_unused_layers)][ (keep_end_layers)][ (zone_layer_connections …)][ (roundrect_rratio R)]
   [ "\n" @N+1 (chamfer_ratio R) (chamfer …) ]                         ← только CHAMFERED_RECT (6.0:1495-1512)
   [ "\n" @N+1 (net …) (pinfunction …) (pintype …) (die_length …) (solder_mask_margin …)
               (solder_paste_margin …) (solder_paste_margin_ratio …) (clearance …) (zone_connect …)
               (thermal_width …)|(thermal_bridge_width …) [(thermal_bridge_angle …)] (thermal_gap …) ]   ← 6.0:1516-1595
   [ custom: "\n" @N+1 (options (clearance …) (anchor …))
             "\n" @N+1 (primitives
                 для каждого примитива: "\n" + примитив (см. ниже)
             "\n" @N+1 ) ]
   [ " (tstamp U)" ]                                                    ← 6.0/7.0, 6.0:1748
   ")\n"
```

* Первая строка — всё до `roundrect_rratio` включительно; `layers` —
  `formatLayers( …, 0 )` с ведущим пробелом.
* «Вторая строка» собирается в `std::string output` через `StrPrintf( &output, " (…)" )` и
  печатается `Print( aNestLevel+1, "%s", output.c_str()+1 )` (`6.0:1594`) — первый пробел
  отрезан.
* Если нет ни chamfer, ни второй строки, ни custom — pad целиком в одну строку.
* 5.1: нет `locked`, `property`, `remove_unused_layers`, `chamfer`, `pinfunction`,
  `pintype`, `tstamp`.

Примитивы custom pad (`nested_level = aNestLevel+2`):

| | 5.1 (`5.1:1392-1455`) | 6.0 (`6.0:1623-1745`) | 7.0 (`7.0:1734-1820`) |
|---|---|---|---|
| `gr_line`/`gr_rect`/`gr_circle`/`gr_curve` | `@N+2 (gr_x … (width W))` | `@N+2 (gr_x …) (width W)[ (fill yes\|none)])` | как 6.0; + `gr_bbox` |
| `gr_arc` | `@N+2 (gr_arc (start) (end) (angle) (width))` | **`@N (gr_arc …`** — ошибка: `Print( aNestLevel, …)` (`6.0:1645`) | `@N+2` |
| `gr_poly` | `@N+2 (gr_poly (pts¶` + точки: в начале строки отступ `@N+3` и `" (xy …)"`, остальные `" (xy …)"`; `\n` после каждой 5-й (`if( ++newLine > 4 )`, `5.1:1441`); затем `") (width W))"` | `@N+2 (gr_poly (pts` + каждая точка `\n @N+4 (xy …)`, затем `\n @N+3 )` и `" (width W) (fill …))"` | `@N+2 (gr_poly¶` + `formatPolyPts(…, N+2)` (`pts` на N+3, точки на N+4) + `Print( nested_level, " " )` ⇒ `@N+2` и ещё пробел, затем `" (width W) (fill …))"` — т. е. **два пробела** перед `(width` |

Ошибка 6.0 с `gr_poly`: переменная `nested_level` переиспользуется в цикле точек
(`nested_level = aNestLevel + 4`, `6.0:1684`), поэтому **все следующие примитивы этого pad**
печатаются с отступом N+4 вместо N+2. Реальный пример (`kfpfull/v7/Module.pretty/Carambola2.kicad_mod:47-58`):

```
    (primitives¶
      (gr_poly (pts¶
          (xy 1.27 0.45)¶
          …¶
        ) (width 0) (fill yes))¶
          (gr_poly (pts¶                ← второй примитив: 10 пробелов вместо 6
```

Ошибка 6.0 с `gr_arc` (отступ N вместо N+2), реальный пример
(`kfpfull/v7/Package_DFN_QFN.pretty/Texas_QFN-41_10x16mm.kicad_mod:47-48`):

```
  (gr_arc (start -0.585 -0.285) (mid -0.443579 -0.226421) (end -0.385 -0.085) (width 0.2))¶
    ) (tstamp 00fb3294-…))¶
```

(Если перед `gr_arc` был `gr_poly`, то его отступ всё равно N — вызов берёт `aNestLevel`.)
При `m_CompactSave = true` в 6.0 `nested_level` может стать 0 — **не проверено**.

### 3.8. `model`

Все версии (`5.1:1098-1147`, `6.0:1248-1284`, `7.0:1331-1367`):

```
@N (model PATH[ hide]¶                      ← 5.1: без hide
[@N+1 (opacity 0.XXXX)]                     ← 6.0/7.0, если opacity != 1: БЕЗ "\n" (6.0:1263)
@N+1 (offset (xyz X Y Z))¶                  ← 5.1: (at (xyz …)) если смещение нулевое
@N+1 (scale (xyz X Y Z))¶
@N+1 (rotate (xyz X Y Z))¶
@N )¶
```

Из-за отсутствия `\n` после `opacity` получается `    (opacity 0.5000)    (offset (xyz 0 0 0))¶`
(отступ `offset` посреди строки). В корпусе `opacity` нет — **по коду**.

### 3.9. `zone` (6.0/7.0)

`6.0/pcb_plugin.cpp:1971-2277`, `7.0/pcb_plugin.cpp:2172-2387`:

```
@N (zone[ locked] (net K) (net_name "…") (layer L)|(layers …) (tstamp U)[ (name "…")] (hatch STYLE PITCH)¶
[@N+1 (priority P)¶]
[@N+1 (attr (teardrop (type …)))¶]                                   ← 7.0
@N+1 (connect_pads[ yes|no|thru_hole_only] (clearance C))¶
@N+1 (min_thickness T)[ (filled_areas_thickness no)]¶
[@N+1 (keepout (tracks …) (vias …) (pads …) (copperpour …) (footprints …))¶]
@N+1 (fill[ yes][ (mode hatch)] (thermal_gap G) (thermal_bridge_width W)[ (smoothing …)[ (radius R)]][ (island_removal_mode M) (island_area_min A)]
     [hatch: "\n" @N+2 (hatch_thickness) (hatch_gap) (hatch_orientation)
             ["\n" @N+2 (hatch_smoothing_level) (hatch_smoothing_value)]
             "\n" @N+2 (hatch_border_algorithm) (hatch_min_hole_area)]
     )¶
для каждого контура:
  6.0: @N+1 (polygon¶ @N+2 (pts ; каждая точка "\n" @N+3 (xy …) ; "\n" ; @N+2 )¶ @N+1 )¶
  7.0: @N+1 (polygon¶ formatPolyPts(N+1): @N+2 (pts¶ @N+3 (xy …)¶ … @N+2 )¶ @N+1 )¶
filled_polygon: @N+1 (filled_polygon¶ @N+2 (layer "L")¶ [@N+2 (island)¶] + pts как выше ; @N+1 )¶
@N )¶
```

**KiCad 6.0.0–6.0.6** печатают `"(keepout (tracks %s) (vias %s) (pads %s ) (copperpour %s) "`
— с пробелом перед `)` у `pads` (`tags/6.0.0-pcb_plugin.cpp:2041`, `tags/6.0.6-pcb_plugin.cpp`);
исправлено в 6.0.7 (`tags/6.0.7-pcb_plugin.cpp`, 6.0.11 = ветка 6.0: `6.0/pcb_plugin.cpp:2052`).
В корпусе 67 файлов с `(pads not_allowed )`/`(pads allowed )` и 10 без пробела. Это
**нельзя восстановить из дерева** — нужна опция writer'а (в `layout67.py` —
`keepout_pads_space`) или сохранение исходного стиля.

### 3.10. `group` (6.0/7.0)

`6.0/pcb_plugin.cpp:1778-1803`, `7.0/pcb_plugin.cpp:1910-1935` (пустые группы не пишутся):

```
@N (group "NAME"[ locked] (id U)¶
@N+1 (members¶
@N+2 UUID¶        ← по одному, отсортированы (memberIds.Sort())
@N+1 )¶
@N )¶
```

В корпусе групп в формате 6/7 нет — **по коду, не проверено**.

### 3.11. Где отступ, где `)` на своей строке, где пробел перед `)`

* Отступ всегда кратен 2 пробелам и ставится только в начале вызова `Print(n, …)`; нигде нет
  табуляций.
* `)` на отдельной строке (с отступом уровня узла): корень, `fp_text`, `model`, `group` и
  `members`, `zone`, `polygon`/`filled_polygon`, `pts` в 7.0-`formatPolyPts`; «висячая» `)`
  с отступом N+1 у `pts` в 6.0-`fp_poly` (`    ) (layer …`) и у `primitives` pad
  (`    ) (tstamp …))`); у 6.0 `gr_poly` — N+3.
* Пробел перед `)` бывает только из-за ошибок: 5.1 `(rect_delta %s )` (`5.1:1287`, есть и
  в 5.0.0 — `tags/5.0.0-kicad_plugin.cpp:1323`), 6.0.0–6.0.6 `(pads %s )`, 7.0 `gr_poly`
  «`  (width`», 7.0 `fp_text_box` «`(stroke …)  )`».
* Пустая строка — только 7.0 `fp_poly` (между `pts` и `stroke`).

### 3.12. KiCad 5.x (файлы с корнем `module`)

Проверено: раскладка writer'а 5.1 (`5.1/kicad_plugin.cpp` = тег 5.1.12;
`gr_poly` «5 точек на строку» и `rect_delta` одинаковы в 5.0.0, 5.0.2, 5.1.0, 5.1.12 —
`tags/`) совпадает с 6.0 по общему механизму (2 пробела, `Print(n, …)`), но отличается
деталями, перечисленными выше (заголовок, 4 точки на строку в `fp_poly`, 5 в `gr_poly`,
`fp_text` без `tstamp`, pad без `tstamp`, `(at (xyz))` в `model` при нулевом смещении).
Большинство файлов библиотеки KiCad 5 записаны не KiCad, а генератором (KicadModTree), и
**не оканчиваются `\n`** (8314 из 12085 файлов тега 6.0.0 — §5); writer 5.1 всегда пишет
`)\n`. Кроме того, 265 файлов отличаются от раскладки 5.1 по другим причинам (§5).

---

## 4. Итог и рекомендации

### 4.1. Таблица «версия файла → стиль»

| `version` в файле | Стиль записи | Отступ | Конец файла | Особые варианты |
|---|---|---|---|---|
| нет (`module`) | «5.1» (§3) | 2 пробела | `)\n` | файлы генератора: без `\n` в конце; `gr_poly` по 4 точки |
| 20200000…20211013 | «5.99» (§3.3) | 2 пробела | `)\n` | — |
| 20211014 | «6.0» (§3) | 2 пробела | `)\n` | `keepout_pads_space` (6.0.0–6.0.6); заголовок «5.99» у файлов ночных сборок 2021-10-15…11-13 |
| 20221018 | «7.0» (§3) | 2 пробела | `)\n` | — |
| 20221019…20231211 (ночные 7.99) | **не проверено** | — | — | — |
| 20231212…20240108 | Prettify | 1 таб | `\n` (8.0.2+) | 8.0.0/8.0.1 — без `\n` |
| 20241229 | Prettify | 1 таб | `\n` | `compact` (если `CompactSave=1`) |
| ≥ 20250000 | Prettify (master `NORMAL`) | 1 таб | `\n` | `COMPACT_TEXT_PROPERTIES` |
| любая Prettify-версия + `generator "kicad-footprint-generator"` | Prettify с `xy_limit = 0` | 1 таб | `\n` | — |

### 4.2. Рекомендации для kicadfp

1. **Одна реализация Prettify** (приложение A, `mode="9.0"`, `compact_save=False`) покрывает
   запись файлов версий 20240108, 20241229 и 2025xxxx+ (выход совпадает у 8.0/9.0/master).
   Параметры: `final_newline` (по умолчанию `True`), `xy_per_line` (`xy_limit=0`),
   `compact` (9.0 `aCompactSave` / master `COMPACT_TEXT_PROPERTIES`, по умолчанию выкл.).
2. **Новые файлы**: `version 20241229`, `generator "…"` по политике проекта, стиль Prettify
   9.0 по умолчанию: табы, без compact, `\n` в конце.
3. **Пересохранение существующего файла без изменений** должно давать исходные байты.
   Надёжный способ: при чтении определить стиль, перебирая кандидатов и сравнивая результат
   с исходными байтами (как делают чекеры в приложениях):
   * Prettify-версии: {`final_newline` ∈ {True, False}} × {`xy_limit` ∈ {99, 0}};
   * 6.0-версии: {6.0, 6.0+`keepout_pads_space`, 5.99-заголовок} (+ наличие `\n` в конце);
   * 5.x: 5.1 ± `\n` в конце.
   Если ни один кандидат не совпал — файл записан сторонним инструментом/отредактирован
   руками; тогда при неизменённом дереве лучше вернуть исходные байты, а при изменённом —
   писать канонический стиль версии.
4. **Изменённое дерево**: писать стилем, определённым в п. 3 (сохраняя `final_newline` и
   `xy_per_line`, чтобы не порождать лишний diff), либо каноническим стилем KiCad версии
   файла — решение за политикой проекта. Для версий 20211014 и 20221018 использовать
   табличные правила §3 (приложение B), помня о непроверенных узлах (§6).
5. Столбцы считать в **байтах UTF-8**, табуляцию — за 1 колонку.
6. Если kicadfp когда-либо будет писать формат 6/7 для фрагментов, у которых нет примеров
   (fp_poly/zone/group в 7.0, `opacity`, `fp_text_box`, compact), — это только по коду.

---

## 5. Проверено

Все скрипты — в `scratchpad/research/`, запуск через `.venv/bin/python`.

Корпуса:

* `kfp/v8.0.0`, `kfp/v9.0.0`, `kfp/master` — sparse-клоны kicad-footprints (из задания);
* `kfp/v7.0.0`, `kfp/v6.0.0` — sparse-клоны (5 библиотек);
* `research/kfpfull/v7` и `research/kfpfull/v6` — **полные** shallow-клоны kicad-footprints
  тегов `7.0.0` (12814 файлов) и `6.0.0` (12085 файлов), сделаны мной для этой проверки
  (в sparse-клоне v7.0.0 нет `fp_poly`, зон, custom pad-примитивов с `gr_poly` и т. п.);
* фикстуры репозитория `tests/fixtures/{kicad5,kicad6,kicad8,kicad9,kicad10dev}` (на момент
  прогона).

### 5.1. Prettify (`prettify.py`): parse → `serialize_oneline` → prettify → сравнение байтов

Для каждого файла дополнительно проверялось, что «грязная» сериализация
(`serialize_spaced`: лишние пробелы/табы/переводы строк) даёт тот же результат (assert).

| Корпус | mode | Файлов | Совпало байт-в-байт | Совпало без `\n` в конце | Генератор: xy по строке | Прочее |
|---|---|---|---|---|---|---|
| kfp/v8.0.0 | 8.0 | 1377 | 0 | **1377** (все pcbnew 8.0) | 0 | 0 |
| kfp/v9.0.0 | 9.0 | 3297 | **2372** (1860 pcbnew + 512 generator) | 0 | 925 | 0 |
| kfp/master | master | 4882 | **3525** (643 pcbnew + 2882 generator) | 0 | 1357 | 0 |
| fixtures/kicad8 | 8.0 | 1377 | 0 | 1377 | 0 | 0 |
| fixtures/kicad9 | 9.0 | 337 | 245 (194 pcbnew + 51 generator) | 0 | 92 | 0 |
| fixtures/kicad10dev | master | 208 | 151 (31 pcbnew + 120 generator) | 0 | 57 | 0 |

* Итого: **100 %** файлов, записанных pcbnew (1377 + 1860 + 643), воспроизводятся портом
  (8.0 — с учётом отсутствия `\n` в конце, что объясняется 8.0.0/8.0.1: библиотека v8.0.0
  датирована 2024-02-20). **100 %** файлов kicad-footprint-generator воспроизводятся с
  `xy_limit = 99` (если в них нет подряд идущих точек) или `xy_limit = 0`.
* Перекрёстно: `mode=8.0` на kfp/master и `mode=master` на kfp/v9.0.0 и kfp/v8.0.0 дают те же
  классы и числа (3525/1357, 2372/925, 1377) — NORMAL-выход 8.0/9.0/master идентичен.
* Специальные случаи задействованы на реальных данных: строки с несколькими `(xy)` — 349
  (v8), 390 (v9), 423 (master) pcbnew-файлов; перенос `xy` по колонке 99 — 3 / 17 / 24
  файла; перенос атомов по порогу 72 — 0 / 5 / 5 файлов (`layers` зоны, `members` групп).
* Не встречались в корпусе (проверено только по коду): compact-режимы, `(data …)`
  встроенных файлов, перенос по 72 с последующим вложенным списком (§2.4, особенность 1),
  многобайтные символы при переносе.

### 5.2. Раскладка 5.1 / 5.99 / 6.0 / 7.0 (`layout67.py`): parse → формат по таблице → сравнение

Writer определяется автоматически: `module` → 5.1; `version < 20211014` → 5.99;
`< 20221018` → 6.0; иначе 7.0. Для 6.0 перебираются варианты `keepout_pads_space` и
заголовок 5.99.

| Корпус | Файлов | Результат |
|---|---|---|
| kfpfull/v7 (тег 7.0.0, полный) | 12814 | 6.0: **12213** точно + **67** точно с `keepout_pads_space` (6.0.0–6.0.6) + **14** точно с заголовком 5.99 + 11 отличаются только заголовком; 7.0: **75** точно; 5.1: **350** точно + 50 без `\n` в конце + 6 прочих; 28 файлов стороннего writer'а (`(generator KicadMod)`, `version 20210108`, строки без кавычек) |
| kfpfull/v6 (тег 6.0.0, полный) | 12085 | 5.1: **3477** точно + 8314 без `\n` в конце + 265 прочих; 5.99: **29** точно (version 20210108…20210824) |
| kfp/v7.0.0 (sparse) | 1332 | 6.0: 1306 точно; 5.1: 10 точно + 16 без `\n` |
| kfp/v6.0.0 (sparse) | 1303 | 5.1: 164 точно + 1134 без `\n` + 2 прочих; 5.99: 3 точно |
| fixtures/kicad6 | 224 | 6.0: 217 точно; 5.1: 3 точно + 4 без `\n` |
| fixtures/kicad5 | 166 | 5.1: 21 точно + 144 без `\n`; 5.99: 1 точно |

Покрытие узлов, совпавших байт-в-байт (скрипт `l67feat.py`, kfpfull/v6+v7):

* 6.0: `fp_text` 12280, `fp_line` 11730, `fp_rect` 61, `fp_circle` 2386, `fp_arc` 1572,
  `fp_poly` 146, `pad` 12116, `primitives` 366 (`gr_poly` 197, `gr_line` 163,
  `gr_arc` 164 — с ошибкой отступа, `gr_circle` 174), `chamfer` 4, `model` 11846,
  `zone` 173 (из них `keepout` 77), `property` 6, `solder_mask_margin` 118,
  `zone_connect` 97, `rect_delta` 4, `locked` 1, `hide` 114, `remove_unused_layers` 1 файл.
* 7.0: `fp_text` 75, `fp_line` 75, `fp_arc` 22, `pad` 75, `model` 75, `solder_mask_margin` 2.
* 5.1: `fp_text`/`fp_line`/`pad`/`model` ≈ 3400–3800, `fp_poly` 137, `zone` 90,
  `gr_poly` 68, `rect_delta` 4.

Причины несовпадений (все — не KiCad writer):

* 11 файлов 6.0 «только заголовок»: вторая строка `" (layer "F.Cu")"` с **одним** пробелом
  (напр. `kfpfull/v7/Button_Switch_THT.pretty/SW_Push_2P1T_Toggle_CK_PVA1xxH1xxxxxxV2.kicad_mod`);
  ни одна найденная версия writer'а так не пишет (§6).
* 5.1, 265 файлов в kfpfull/v6: 118 — `gr_poly` по 4 точки на строку (KiCad 5 пишет по 5;
  так пишет генератор), 97 — `model` со всеми дочерними в одной строке, 31 — пустые строки в
  конце, 7 — нет пробела перед `(roundrect_rratio`, 5 — два пробела после имени `module`,
  2 — `effects` в строке `fp_text`, 5 — прочие ручные правки. 6 прочих в kfpfull/v7 —
  `gr_poly` по 4 точки.
* 28 файлов `(generator KicadMod)` — собственный writer KicadModTree.

Проверки по исходникам (скачаны мной в `kicad-src/tags/`):

* `kicad_io_utils.cpp` тегов 8.0.0, 8.0.1 (нет `\n`), 8.0.2…8.0.9 (есть), 9.0.0 (= ветка 9.0).
* `pcb_plugin.cpp` тегов 6.0.0, 6.0.5, 6.0.6 (`(pads %s )`), 6.0.7…6.0.11 (без пробела);
  разница 6.0.0 ↔ 6.0.11 в `Print`-строках — только `keepout` и `(fill none)` у примитивов.
* `pcb_plugin.cpp` 7.0.0 и 7.0.11 — строки заголовка идентичны; ветка 7.0 = 7.0.11.
* `kicad_plugin.cpp` 5.0.0, 5.0.2, 5.1.0, 5.1.12 (= ветка 5.1).
* ночной `kicad_plugin.cpp` коммита `ee5f9034` (2021-08-26) — заголовок в одну строку;
  коммит `80c5b1efb1e3` (2021-11-13) добавил `"\n "`.

---

## 6. Открытые вопросы

1. Windows: `PRETTIFIED_FILE_OUTPUTFORMATTER`/`FILE_OUTPUTFORMATTER` открывают файл в режиме
   `"wt"`; пишет ли KiCad на Windows `\r\n` — не проверено. Парсер kicadfp в любом случае
   должен принимать `\r\n` (Prettify считает `\r` пробелом).
2. Ночные 7.99 (version 20221019…20231211): где writer был «старым», где уже Prettify
   (коммит 2023-11-29), и как менялась раскладка «старого» writer'а между 7.0 и Prettify, —
   не проверено (нет файлов).
3. 11 файлов 6.0 с `" (layer …)"` (один пробел) — источник неизвестен (не воспроизводится ни
   тегами 6.0.x, ни ночным кодом до/после `80c5b1ef`); вероятно, скриптовая правка.
4. Узлы 7.0 без примеров в корпусе: `fp_poly` (пустая строка!), custom-pad примитивы
   (`gr_poly` с двумя пробелами), `zone`, `group`, `fp_text_box`, `render_cache`,
   `opacity`. Реализованы по коду, не проверены.
5. `render_cache` 7.0: для полигонов из stroke-глифов `formatPolyPts` вызывается с
   уровнем N+2, для outline-глифов — N+1 (дыры N+2) (`7.0/pcb_plugin.cpp:514-535`); по дереву
   эти случаи неразличимы. В `layout67.py` принято «первый `pts` N+1, остальные N+2».
6. `m_CompactSave = true` для 6.0/7.0 (4 точки на строку, отступ перед каждой точкой в 7.0,
   сброс `nested_level` в 0 в 6.0) и для Prettify 9.0/master — на реальных файлах не проверено.
7. `(data …)` встроенных файлов (9.0+) и `%1s` с пустой строкой (даёт пробел) — только по коду.
8. Ночные 5.99 до 20210108 (если такие файлы существуют в формате `footprint`) — не проверено.

---

## Приложение A. `prettify.py`

Порт `KICAD_FORMAT::Prettify` (8.0 / 9.0 / master) + токенизатор, однострочный сериализатор и чекер.
Запуск: `python prettify.py --mode=9.0 <каталог .pretty или файл>`. Функция `format_tree(tree, mode=..., final_newline=..., xy_limit=...)` — то, что должен делать форматтер kicadfp для KiCad 8+.

```python
#!/usr/bin/env python3
"""
1:1 port of KICAD_FORMAT::Prettify (common/io/kicad/kicad_io_utils.cpp) plus a minimal
S-expression tokenizer / one-line serializer and a byte-for-byte round-trip checker.

Ported versions (argument `mode`):
  "8.0"    - KiCad 8.0.x  : Prettify( std::string&, char aQuoteChar = '"' )   8.0/kicad_io_utils.cpp:65
  "9.0"    - KiCad 9.0.x  : Prettify( std::string&, bool aCompactSave )        9.0/kicad_io_utils.cpp:89
  "master" - KiCad 10-dev : Prettify( std::string&, FORMAT_MODE aMode )        master/kicad_io_utils.cpp:111

The C++ code works on std::string, i.e. on BYTES (UTF-8 encoded). `column` counts bytes, so
the algorithm is run on a latin-1 decoded str (1 char == 1 byte) and re-encoded as latin-1.

Usage (round-trip check: parse -> one-line -> prettify -> compare with the original bytes):
    python prettify.py [--mode=8.0|9.0|master] <dir-or-file> ...
"""
from __future__ import annotations

import collections
import glob
import os
import sys
from dataclasses import dataclass
from typing import List, Union

# ----------------------------------------------------------------------------------------------
# Minimal S-expression model: atoms are kept VERBATIM (quoted atoms keep quotes and escapes)
# ----------------------------------------------------------------------------------------------

Atom = str
Node = Union[Atom, List["Node"]]


def tokenize(src: str) -> Node:
    """Parse one top-level list. Atoms are kept verbatim (no unescaping)."""
    i, n = 0, len(src)
    stack: List[list] = []
    root = None
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            lst: list = []
            if stack:
                stack[-1].append(lst)
            stack.append(lst)
            i += 1
        elif c == ")":
            lst = stack.pop()
            if not stack:
                root = lst
            i += 1
        elif c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    break
                j += 1
            stack[-1].append(src[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and src[j] not in " \t\r\n()":
                j += 1
            stack[-1].append(src[i:j])
            i = j
    if root is None:
        raise ValueError("no complete top-level list")
    return root


def serialize_oneline(node: Node) -> str:
    """Pre-Prettify serialization: '(' + head; every ATOM (except the first item) is preceded
    by exactly one ' '; a sub-list is preceded by nothing; ')' closes.  Equivalent to what the
    KiCad 9 writer emits (m_out->Print("(tok %s)") calls simply concatenated)."""
    if isinstance(node, str):
        return node
    out = ["("]
    first = True
    for ch in node:
        if isinstance(ch, str):
            if not first:
                out.append(" ")
            out.append(ch)
        else:
            out.append(serialize_oneline(ch))
        first = False
    out.append(")")
    return "".join(out)


def serialize_spaced(node: Node) -> str:
    """Deliberately 'dirty' serialization (extra spaces / tabs / newlines everywhere) used only
    to prove that Prettify's output does not depend on input whitespace.
    NB: '(' must stay glued to the head atom and the head must be followed by a plain ' ',
    because isXY() tests the literal bytes "xy " after '(' and isShortForm() reads the token
    right after '('."""
    if isinstance(node, str):
        return node
    return "(" + "  \n\t ".join(serialize_spaced(ch) for ch in node) + " )"


# ----------------------------------------------------------------------------------------------
# Prettify
# ----------------------------------------------------------------------------------------------

WS = " \t\n\r"      # isWhitespace(): ' ', '\t', '\n', '\r'


def prettify(source: str, mode: str = "9.0", compact_save: bool = False,
             format_mode: str = "NORMAL", final_newline: bool = True,
             xy_limit: int = 99) -> str:
    """source        : raw writer output, str with 1 char == 1 byte (latin-1 view of UTF-8)
    mode          : "8.0" | "9.0" | "master"
    compact_save  : 9.0 only - ADVANCED_CFG::m_CompactSave (default false)
    format_mode   : master only - "NORMAL" | "COMPACT_TEXT_PROPERTIES" | "LIBRARY_TABLE"
                    (master's PRETTIFIED_FILE_OUTPUTFORMATTER turns NORMAL into
                    COMPACT_TEXT_PROPERTIES when m_CompactSave is set; richio.cpp:702)
    final_newline : False reproduces KiCad 8.0.0 / 8.0.1 (the trailing '\n' was added in 8.0.2)
    xy_limit      : 99 in KiCad. 0 emulates the kicad-footprint-generator style
                    (every (xy ...) on its own line) - NOT a KiCad behaviour.
    """
    quote_char = '"'
    indent_char = "\t"
    indent_size = 1
    xy_special_case_column_limit = xy_limit
    consecutive_token_wrap_threshold = 72

    if mode == "master":
        text_special_case = format_mode == "COMPACT_TEXT_PROPERTIES"
        lib_special_case = format_mode == "LIBRARY_TABLE"
        short_form_tokens = {"font", "stroke", "fill", "teardrop", "offset", "rotate", "scale"}
    elif mode == "9.0":
        text_special_case = compact_save
        lib_special_case = False
        short_form_tokens = {"font", "stroke", "fill", "offset", "rotate", "scale"}
    elif mode == "8.0":
        text_special_case = False
        lib_special_case = False
        short_form_tokens = set()
    else:
        raise ValueError(mode)

    out: List[str] = []
    n = len(source)

    list_depth = 0
    lib_depth = 0
    last_non_whitespace = "\0"
    in_quote = False
    has_inserted_space = False
    in_multi_line_list = False
    in_xy = False
    in_short_form = False
    in_lib_row = False
    short_form_depth = 0
    column = 0
    backslash_count = 0

    def next_non_whitespace(i: int) -> str:
        while i < n and source[i] in WS:
            i += 1
        return source[i] if i < n else "\0"

    def is_xy(i: int) -> bool:                       # literally "xy " after '('
        return source[i + 1:i + 4] == "xy "

    def alpha_token(i: int) -> str:                  # isalpha() run right after '('
        j = i + 1
        while j < n and source[j].isascii() and source[j].isalpha():
            j += 1
        return source[i + 1:j]

    def indent(depth: int) -> str:
        return indent_char * (depth * indent_size)

    for i in range(n):
        c = source[i]
        nxt = next_non_whitespace(i)

        if c in WS and not in_quote:
            if (not has_inserted_space              # Only permit one space between chars
                    and list_depth > 0              # Do not permit spaces in outer list
                    and last_non_whitespace != "("  # Remove extra space after start of list
                    and nxt != ")"                  # Remove extra space before end of list
                    and nxt != "("):                # Remove extra space before newline
                if in_xy or column < consecutive_token_wrap_threshold:
                    out.append(" ")
                    column += 1
                elif in_short_form or in_lib_row:   # (9.0: inShortForm only; 8.0: absent)
                    out.append(" ")                 # NB: column NOT incremented (sic)
                else:
                    out.append("\n" + indent(list_depth))
                    column = list_depth * indent_size
                    in_multi_line_list = True
                has_inserted_space = True
        else:
            has_inserted_space = False

            if c == "(" and not in_quote:
                current_is_xy = is_xy(i)
                current_is_short_form = text_special_case and alpha_token(i) in short_form_tokens
                current_is_lib = lib_special_case and alpha_token(i) == "lib"

                # 8.0: `if( listDepth == 0 )`, 9.0/master: `if( formatted.empty() )`
                first = (list_depth == 0) if mode == "8.0" else (not out)
                if first:
                    out.append("(")
                    column += 1
                elif in_xy and current_is_xy and column < xy_special_case_column_limit:
                    out.append(" (")                # List-of-points special case
                    column += 2
                elif in_short_form or in_lib_row:
                    out.append(" (")
                    column += 2
                else:
                    out.append("\n" + indent(list_depth) + "(")
                    column = list_depth * indent_size + 1

                in_xy = current_is_xy

                if current_is_short_form:
                    in_short_form = True
                    short_form_depth = list_depth
                elif current_is_lib:
                    in_lib_row = True
                    lib_depth = list_depth

                list_depth += 1

            elif c == ")" and not in_quote:
                if list_depth > 0:
                    list_depth -= 1

                if in_short_form:
                    out.append(")")
                    column += 1
                elif in_lib_row and list_depth == lib_depth:
                    out.append(")")                 # NB: column NOT incremented (sic)
                    in_lib_row = False
                elif last_non_whitespace == ")" or in_multi_line_list:
                    out.append("\n" + indent(list_depth) + ")")
                    column = list_depth * indent_size + 1
                    in_multi_line_list = False
                else:
                    out.append(")")
                    column += 1

                if short_form_depth == list_depth:  # (absent in 8.0; harmless there)
                    in_short_form = False
                    short_form_depth = 0

            else:
                # The output formatter escapes double-quotes (like \")
                # But a corner case is a sequence like \\"
                # therefore a '\' is attached to a '"' if a odd number of '\' is detected
                if c == "\\":
                    backslash_count += 1
                elif c == quote_char and (backslash_count & 1) == 0:
                    in_quote = not in_quote

                if c != "\\":
                    backslash_count = 0

                out.append(c)
                column += 1

            last_non_whitespace = c

    # newline required at end of line / file for POSIX compliance. Keeps git diffs clean.
    if final_newline:
        out.append("\n")
    return "".join(out)


def prettify_bytes(raw: bytes, **kw) -> bytes:
    return prettify(raw.decode("latin-1"), **kw).encode("latin-1")


def format_tree(tree: Node, **kw) -> bytes:
    """What a KiCad 8/9/10 writer would put on disk for `tree` (atoms given verbatim)."""
    return prettify_bytes(serialize_oneline(tree).encode("latin-1"), **kw)


# ----------------------------------------------------------------------------------------------
# Round-trip checker
# ----------------------------------------------------------------------------------------------

@dataclass
class Result:
    path: str
    cls: str            # exact | exact-no-final-nl | generator-xy-per-line | other
    first_diff: str


def first_difference(a: bytes, b: bytes) -> str:
    if a == b:
        return ""
    m = min(len(a), len(b))
    k = 0
    while k < m and a[k] == b[k]:
        k += 1
    line = a.count(b"\n", 0, k) + 1
    ls = a.rfind(b"\n", 0, k) + 1
    ea = a.find(b"\n", k)
    eb = b.find(b"\n", k)
    ctx_a = a[ls:ea if ea != -1 else len(a)]
    ctx_b = b[ls:eb if eb != -1 else len(b)]
    return f"line {line} off {k}: orig={ctx_a[:120]!r} ours={ctx_b[:120]!r}"


def check_file(path: str, mode: str) -> Result:
    raw = open(path, "rb").read()
    tree = tokenize(raw.decode("latin-1"))
    out = format_tree(tree, mode=mode)
    # invariance: dirty input whitespace must give identical output
    out2 = prettify_bytes(serialize_spaced(tree).encode("latin-1"), mode=mode)
    assert out == out2, f"whitespace-invariance violated: {path}"
    if out == raw:
        return Result(path, "exact", "")
    if format_tree(tree, mode=mode, final_newline=False) == raw:
        return Result(path, "exact-no-final-nl", "")
    if format_tree(tree, mode=mode, xy_limit=0) == raw:
        return Result(path, "generator-xy-per-line", "")
    return Result(path, "other", first_difference(raw, out))


def _worker(args):
    return check_file(*args)


def main(argv):
    from multiprocessing import Pool
    mode = "9.0"
    paths = []
    for a in argv:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "**", "*.kicad_mod"), recursive=True))
        else:
            paths.append(a)
    with Pool() as pool:
        results = pool.map(_worker, [(p, mode) for p in paths], chunksize=16)
    c = collections.Counter(r.cls for r in results)
    print(f"mode={mode} files={len(results)} " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))
    for r in [r for r in results if r.cls == "other"][:25]:
        print("  DIFF", r.path, "::", r.first_diff)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## Приложение B. `layout67.py`

Табличная раскладка writer'ов 5.1 / 5.99 / 6.0 / 7.0 и чекер. Зависит от `prettify.py` (`tokenize`, `first_difference`). Запуск: `python layout67.py <каталог>`; `format_tree(tree, writer, keepout_pads_space=False)` возвращает текст файла.

```python
#!/usr/bin/env python3
"""
Table-driven emulation of the whitespace layout produced by the KiCad footprint writers that
predate Prettify, for .kicad_mod files, plus a byte-for-byte round-trip checker:

  "5.1"  - pcbnew/kicad_plugin.cpp (KiCad 5.x, root "module")
  "5.99" - 6.0 development nightlies: like 6.0, but the whole header incl. (layer) on line 1
  "6.0"  - pcbnew/plugins/kicad/pcb_plugin.cpp 6.0.x (version 20211014)
           option keepout_pads_space=True reproduces 6.0.0..6.0.6 "(pads %s )"
  "7.0"  - pcbnew/plugins/kicad/pcb_plugin.cpp 7.0.x (version 20221018)

    python layout67.py [--writer=5.1|5.99|6.0|7.0|auto] <dir-or-file> ...

The tree comes from prettify.tokenize (atoms verbatim). Only the *layout* is emulated:
child order / presence is taken from the tree as-is. Files end with ")\n".
"""
from __future__ import annotations

import collections
import glob
import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prettify import tokenize, first_difference  # noqa: E402

IND = "  "          # OUTPUTFORMATTER::Print: NESTWIDTH = 2 spaces per nest level (richio.cpp)


def name_of(node) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def inline(node, writer: str = "6.0") -> str:
    """One-line rendering: '(' + items separated by single spaces + ')'.
    Mirrors Print( ..., "(tok %s (sub %s) ...)" ) format strings of the writers."""
    if isinstance(node, str):
        return node
    parts = [inline(ch, writer) for ch in node]
    s = "(" + " ".join(parts) + ")"
    if writer == "5.1" and name_of(node) == "rect_delta":
        s = s[:-1] + " )"          # 5.1: Print( 0, " (rect_delta %s )" ) — stray space (bug)
    return s


# ---------------------------------------------------------------------------
# Layout tables
# ---------------------------------------------------------------------------

# Node -> layout rule, per writer.  "inline" = the whole node on ONE line at the current nest
# (items separated by one space, no space before ')'), followed by "\n".
# The Formatter.child() dispatcher uses HANDLER; LAYOUT_RULES is the human-readable table.
HANDLER = {
    "fp_text": "fp_text",
    "fp_text_box": "fp_text_box",          # 7.0 only
    "fp_line": "shape", "fp_rect": "shape", "fp_circle": "shape", "fp_arc": "shape",
    "fp_curve": "shape",
    "fp_poly": "fp_poly",
    "pad": "pad",
    "zone": "zone",
    "group": "group",
    "model": "model",
    # everything else (at, descr, tags, property, path, autoplace_cost*, solder_*, clearance,
    # zone_connect, thermal_*, attr, private_layers, net_tie_pad_groups, ...) -> "inline"
}

LAYOUT_RULES = {
    "footprint/module": {
        "5.1":  '(module NAME[ locked][ placed] (layer L) (tedit T)[ (tstamp X)]\\n ; children @1 ; ")\\n"',
        "5.99": '(footprint NAME (version V) (generator pcbnew)[ locked][ placed] (layer L)\\n ; @1 (tedit T) (tstamp U)\\n',
        "6.0":  '(footprint NAME (version V) (generator pcbnew)\\n  [locked ][placed ](layer L)\\n ; @1 (tedit T)[ (tstamp U)]\\n',
        "7.0":  'as 6.0 but no tedit; [@1 (tstamp U)\\n] on its own line',
    },
    "inline children": {"all": "@1 (tok ...)\\n"},
    "fp_text": {
        "5.1/6.0": '@n (fp_text TYPE[ locked] TEXT (at X Y[ A])[ unlocked]) (layer L)[ hide]\\n ; @n+1 (effects ...)\\n ; [6.0: @n+1 (tstamp U)\\n] ; @n )\\n',
        "7.0": 'as 6.0 but (effects) @n+2 ; (tstamp) @n+1 ; [render_cache @n+1]',
    },
    "fp_line/rect/circle/arc/curve": {
        "5.1/6.0": "@n whole node inline",
        "7.0": '@n (fp_x[ locked] (start) (end)...\\n ; @n+1 (stroke ...)[ (fill ..)] (layer L) (tstamp U))\\n',
    },
    "fp_poly": {
        "5.1": '@n (fp_poly (pts (xy)x4 ; every 4th point: "\\n" @n+1 (xy) (xy)... ) (layer) (width))\\n',
        "6.0": '@n (fp_poly[ locked] (pts ; each point "\\n" @n+2 (xy) ; "\\n" @n+1 ")" then " (layer) (width) (fill) (tstamp))\\n"',
        "7.0": '@n (fp_poly[ locked]\\n ; @n+1 (pts\\n ; @n+2 (xy)\\n each ; @n+1 )\\n ; "\\n" (EMPTY LINE) ; @n+1 (stroke) (fill) (layer) (tstamp))\\n',
    },
    "pad": {
        "all": 'line 1: @n (pad N TYPE SHAPE[ locked] (at) (size) [(rect_delta)] [(drill)] [(property)] (layers) '
               '[(remove_unused_layers)] [(keep_end_layers)] [(zone_layer_connections)] [(roundrect_rratio)]',
        "6.0/7.0 chamfer": '"\\n" @n+1 (chamfer_ratio R) (chamfer ...)',
        "second line": '"\\n" @n+1 (net) (pinfunction) (pintype) (die_length) (solder_*) (clearance) (zone_connect) (thermal_*)',
        "custom": '"\\n" @n+1 (options ...) ; "\\n" @n+1 (primitives ; each prim "\\n" @n+2 ... ; "\\n" @n+1 ")"',
        "end": '[6.0/7.0: " (tstamp U)"] ")\\n"',
    },
    "model": {"all": '@n (model PATH[ hide]\\n ; [@n+1 (opacity X) - NO newline] ; @n+1 (offset|at (xyz))\\n ; @n+1 (scale ..)\\n ; @n+1 (rotate ..)\\n ; @n )\\n'},
    "group": {"6.0/7.0": '@n (group NAME[ locked] (id U)\\n ; @n+1 (members\\n ; @n+2 UUID\\n each ; @n+1 )\\n ; @n )\\n'},
    "zone": {"6.0/7.0": "see Formatter.zone()"},
}

# pad: children that go to the "second line" at nest+1 (StrPrintf(&output, ...) block)
PAD_SECOND_LINE = {
    "net", "pinfunction", "pintype", "die_length", "solder_mask_margin",
    "solder_paste_margin", "solder_paste_margin_ratio", "clearance", "zone_connect",
    "thermal_width", "thermal_gap",                      # 5.1 / 6.0 (thermal_gap also 7.0)
    "thermal_bridge_width", "thermal_bridge_angle",      # 7.0
}
PAD_CHAMFER_LINE = {"chamfer_ratio", "chamfer"}          # 6.0/7.0: "\n" + nest+1 + "(chamfer_ratio) (chamfer ...)"


class Formatter:
    def __init__(self, writer: str, keepout_pads_space: bool = False):
        self.w = writer
        # KiCad 6.0.0 .. 6.0.6: "(keepout (tracks %s) (vias %s) (pads %s ) (copperpour %s) ..."
        # (stray space, fixed in 6.0.7). Not representable in the tree -> writer option.
        self.keepout_pads_space = keepout_pads_space
        self.out: List[str] = []

    # -- helpers ---------------------------------------------------------
    def p(self, nest: int, s: str):
        self.out.append(IND * nest + s)

    # -- footprint -------------------------------------------------------
    def footprint(self, node, nest=0):
        w = self.w
        kids = node[1:]
        byname = collections.defaultdict(list)
        for k in kids:
            if isinstance(k, list):
                byname[name_of(k)].append(k)
        fpname = kids[0] if kids and isinstance(kids[0], str) else '""'
        flags = [k for k in kids if isinstance(k, str) and k in ("locked", "placed")]

        if w == "5.1":
            # 5.1: Print( nest, "(module %s" ); [" locked"][" placed"]; formatLayer -> " (layer %s)";
            #      " (tedit %lX)"; [" (tstamp %lX)"] "\n"
            line = "(module " + fpname
            for f in flags:
                line += " " + f
            line += " " + inline(byname["layer"][0], w)
            for t in byname.get("tedit", []):      # always written by 5.1; tolerate files without it
                line += " " + inline(t, w)
            for t in byname.get("tstamp", []):
                line += " " + inline(t, w)
            self.p(nest, line + "\n")
            consumed = {"layer", "tedit", "tstamp"}
        else:
            # 6.0/7.0: "(footprint %s" + " (version %d) (generator pcbnew)\n " +
            #          [" locked"][" placed"] + " (layer %s)" + "\n"
            line = "(footprint " + fpname
            line += " " + inline(byname["version"][0], w) + " " + inline(byname["generator"][0], w)
            if w != "5.99":
                # 5.99 nightlies up to commit 80c5b1ef (2021-11-13) had no "\n " here: the whole
                # header incl. (layer) was on line 1
                line += "\n "
            for f in flags:
                line += " " + f
            line += " " + inline(byname["layer"][0], w) + "\n"
            self.p(nest, line)
            consumed = {"version", "generator", "layer"}
            if w in ("5.99", "6.0"):
                # "(tedit %lX)" [" (tstamp %s)"] "\n"
                line = " ".join(inline(t, w) for t in byname.get("tedit", []) + byname.get("tstamp", []))
                self.p(nest + 1, line + "\n")
                consumed |= {"tedit", "tstamp"}
            else:  # 7.0: "(tstamp %s)\n" on its own line, no tedit
                for t in byname.get("tstamp", []):
                    self.p(nest + 1, inline(t, w) + "\n")
                consumed |= {"tstamp"}

        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n in consumed:
                continue
            self.child(k, nest + 1)
        self.p(nest, ")\n")

    # -- dispatcher -------------------------------------------------------
    def child(self, node, nest):
        h = HANDLER.get(name_of(node))
        if h is None:
            # descr, tags, attr, property, ... and anything unknown: one line
            self.p(nest, inline(node, self.w) + "\n")
        else:
            getattr(self, h)(node, nest)

    # -- fp_text ------------------------------------------------------------
    def fp_text(self, node, nest):
        # "(fp_text TYPE[ locked] TEXT (at ...)[ unlocked]) (layer L)[ hide]\n"
        #   nest+1: "(effects ...)\n"       (EDA_TEXT::Format, one line)
        #   nest+1: "(tstamp X)\n"          (6.0/7.0 only)
        #   [7.0: render_cache block]
        # nest: ")\n"
        head, rest = [], []
        for k in node[1:]:
            if isinstance(k, list) and name_of(k) in ("effects", "tstamp", "render_cache"):
                rest.append(k)
            else:
                head.append(k)
        self.p(nest, "(fp_text " + " ".join(inline(k, self.w) for k in head) + "\n")
        for k in rest:
            n = name_of(k)
            if n == "render_cache":
                self.render_cache(k, nest + 1)
            elif n == "effects" and self.w == "7.0":
                # 7.0: aText->EDA_TEXT::Format( m_out, aNestLevel + 1, ... ) -> printed at nest+2
                self.p(nest + 2, inline(k, self.w) + "\n")
            else:
                self.p(nest + 1, inline(k, self.w) + "\n")
        self.p(nest, ")\n")

    def fp_text_box(self, node, nest):
        # 7.0 PCB_PLUGIN::format(FP_TEXTBOX*):
        #   nest   "(fp_text_box[ locked] TEXT\n"
        #   RECT:  nest "(start ..) (end ..)"            (sic: aNestLevel, not +1)
        #   POLY:  formatPolyPts(nest, compact=true)      -> ends with ")\n", next items start at col 0
        #   [" (angle A)"] " (layer L)" " (tstamp U)" "\n"
        #   EDA_TEXT::Format(nest+1) -> nest+2 "(effects ...)\n"
        #   [stroke width>0] nest+1 "(stroke ...)"       (NO newline)
        #   [render_cache at nest+1]
        #   nest ")\n"
        # Not verified on real files (no 7.0 fixtures contain fp_text_box).
        kids = node[1:]
        head = [k for k in kids if isinstance(k, str)]
        self.p(nest, "(fp_text_box " + " ".join(head) + "\n")
        line = ""
        poly = False
        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n == "pts":
                self.poly_pts(k, nest, compact=True)
                poly = True
            elif n in ("start", "end"):
                line += (" " if line else "") + inline(k, self.w)
            elif n in ("angle", "layer", "tstamp"):
                line += " " + inline(k, self.w)
        self.out.append((IND * nest if not poly else "") + line + "\n")
        for k in kids:
            if name_of(k) == "effects":
                self.p(nest + 2, inline(k, self.w) + "\n")
        for k in kids:
            if name_of(k) == "stroke":
                self.p(nest + 1, inline(k, self.w))
        for k in kids:
            if name_of(k) == "render_cache":
                self.render_cache(k, nest + 1)
        self.p(nest, ")\n")

    def render_cache(self, node, nest):
        # 7.0 formatRenderCache: "(render_cache TEXT ANGLE\n" ; polygons: nest+1 "(polygon\n" formatPolyPts(nest+1|+2, compact=True) nest+1 ")\n" ; nest ")\n"
        self.p(nest, "(render_cache " + " ".join(inline(k, self.w) for k in node[1:3]) + "\n")
        for poly in node[3:]:
            self.p(nest + 1, "(polygon\n")
            for i, pts in enumerate(poly[1:]):
                self.poly_pts(pts, nest + 1 if i == 0 else nest + 2, compact=True)
            self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    # -- shapes ---------------------------------------------------------------
    def shape(self, node, nest):
        w = self.w
        if w in ("5.1", "5.99", "6.0"):
            self.p(nest, inline(node, w) + "\n")
            return
        # 7.0: "(fp_line[ locked] (start) (end)" "\n" ; nest+1 "(stroke ...)" [" (fill ..)"] " (layer ..)" " (tstamp ..)" ")\n"
        head, tail = [], []
        for k in node[1:]:
            if isinstance(k, list) and name_of(k) in ("stroke", "fill", "layer", "tstamp"):
                tail.append(k)
            else:
                head.append(k)
        self.p(nest, "(" + name_of(node) + " " + " ".join(inline(k, w) for k in head) + "\n")
        self.p(nest + 1, " ".join(inline(k, w) for k in tail) + ")\n")

    def poly_pts(self, pts, nest, compact=False):
        """7.0 formatPolyPts( outline, aNestLevel=nest, aCompact ): nest+1 "(pts\n", each point at
        nest+2 followed by "\n" (aCompact=false => every point), nest+1 ")\n"."""
        self.p(nest + 1, "(pts\n")
        pts_items = pts[1:]
        need_nl = False
        for i, pt in enumerate(pts_items, 1):
            self.p(nest + 2, inline(pt, self.w))
            need_nl = True
            if (i % 4 == 0) or not compact:
                self.out.append("\n")
                need_nl = False
        if need_nl:
            self.out.append("\n")
        self.p(nest + 1, ")\n")

    def fp_poly(self, node, nest):
        w = self.w
        kids = node[1:]
        flags = [k for k in kids if isinstance(k, str)]
        pts = next(k for k in kids if name_of(k) == "pts")
        tail = [k for k in kids if isinstance(k, list) and name_of(k) != "pts"]
        head = "(fp_poly" + "".join(" " + f for f in flags)
        if w == "5.1":
            # "(fp_poly (pts" ; points: " (xy)" ; every 4th point (ii && !(ii%4)): "\n" + nest+1 indent, no leading space
            line = head + " (pts"
            self.out.append(IND * nest + line)
            for i, pt in enumerate(pts[1:]):
                if i and i % 4 == 0:
                    self.out.append("\n" + IND * (nest + 1) + inline(pt, w))
                else:
                    self.out.append(" " + inline(pt, w))
            self.out.append(")")                                     # closes (pts
            self.out.append(" " + " ".join(inline(k, w) for k in tail) + ")\n")
        elif w in ("5.99", "6.0"):
            # "(fp_poly[ locked] (pts" ; each point: "\n" + nest+2 "(xy ..)" (m_CompactSave=false => every point)
            # then "\n" + nest+1 ")" ; then " (layer) (width) (fill) (tstamp))\n"
            self.out.append(IND * nest + head + " (pts")
            for pt in pts[1:]:
                self.out.append("\n" + IND * (nest + 2) + inline(pt, w))
            self.out.append("\n" + IND * (nest + 1) + ")")
            self.out.append(" " + " ".join(inline(k, w) for k in tail) + ")\n")
        else:
            # 7.0: "(fp_poly[ locked]\n" ; formatPolyPts(nest) ; "\n" (=> blank line!) ; nest+1 "(stroke ..) (fill ..) (layer ..) (tstamp ..))\n"
            self.p(nest, head + "\n")
            self.poly_pts(pts, nest, compact=False)
            self.out.append("\n")
            self.p(nest + 1, " ".join(inline(k, w) for k in tail) + ")\n")

    # -- pad ---------------------------------------------------------------
    def pad(self, node, nest):
        w = self.w
        kids = node[1:]
        first, chamfer, second, options, prims, tstamp = [], [], [], None, None, []
        for k in kids:
            n = name_of(k) if isinstance(k, list) else ""
            if n in PAD_SECOND_LINE:
                second.append(k)
            elif n in PAD_CHAMFER_LINE:
                chamfer.append(k)
            elif n == "options":
                options = k
            elif n == "primitives":
                prims = k
            elif n == "tstamp":
                tstamp.append(k)
            else:
                first.append(k)
        self.out.append(IND * nest + "(pad " + " ".join(inline(k, w) for k in first))
        if chamfer:
            self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in chamfer))
        if second:
            self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in second))
        if options is not None:
            self.out.append("\n" + IND * (nest + 1) + inline(options, w))
        if prims is not None:
            self.primitives(prims, nest)
        for t in tstamp:
            self.out.append(" " + inline(t, w))
        self.out.append(")\n")

    def primitives(self, prims, nest):
        """(primitives ...) of a custom pad. `nest` = nest level of the pad."""
        w = self.w
        self.out.append("\n" + IND * (nest + 1) + "(primitives")
        nested_level = nest + 2
        for prim in prims[1:]:
            self.out.append("\n")
            pn = name_of(prim)
            if w == "5.1":
                if pn == "gr_poly":
                    pts = next(k for k in prim[1:] if name_of(k) == "pts")
                    tail = [k for k in prim[1:] if isinstance(k, list) and name_of(k) != "pts"]
                    self.out.append(IND * nested_level + "(gr_poly (pts\n")
                    new_line = 0
                    for pt in pts[1:]:
                        if new_line == 0:
                            self.out.append(IND * (nested_level + 1) + " " + inline(pt, w))
                        else:
                            self.out.append(" " + inline(pt, w))
                        new_line += 1
                        if new_line > 4:
                            new_line = 0
                            self.out.append("\n")
                    self.out.append(")" + " " + " ".join(inline(k, w) for k in tail) + ")")
                else:
                    self.out.append(IND * nested_level + inline(prim, w))
                continue
            # 6.0 / 7.0
            head = [k for k in prim[1:] if not (isinstance(k, list) and name_of(k) in ("width", "fill", "pts"))]
            tail = [k for k in prim[1:] if isinstance(k, list) and name_of(k) in ("width", "fill")]
            if pn == "gr_poly":
                pts = next(k for k in prim[1:] if name_of(k) == "pts")
                if w in ("5.99", "6.0"):
                    # "(gr_poly (pts" ; each point "\n" + (nest+4) "(xy)" ; "\n" + (nest+3) ")" ;
                    # BUG: the loop overwrites `nested_level` (0 or nest+4) => later primitives are
                    # indented with nest+4 instead of nest+2.
                    self.out.append(IND * nested_level + "(gr_poly (pts")
                    for pt in pts[1:]:
                        nested_level = nest + 4
                        self.out.append("\n" + IND * nested_level + inline(pt, w))
                    self.out.append("\n" + IND * (nest + 3) + ")")
                else:
                    # 7.0: "(gr_poly\n" formatPolyPts(nested_level, compact) ; Print(nested_level, " ")
                    self.out.append(IND * nested_level + "(gr_poly\n")
                    self.poly_pts(pts, nested_level, compact=False)
                    self.out.append(IND * nested_level + " ")
            elif pn == "gr_curve":
                pts = next(k for k in prim[1:] if name_of(k) == "pts")
                self.out.append(IND * nested_level + "(gr_curve " + inline(pts, w))
            elif pn == "gr_arc" and w in ("5.99", "6.0"):
                # 6.0 BUG: Print( aNestLevel, "(gr_arc ..." ) — pad's nest level, not nested_level
                self.out.append(IND * nest + "(" + pn + " " + " ".join(inline(k, w) for k in head) + "")
            else:
                self.out.append(IND * nested_level + "(" + pn + " " + " ".join(inline(k, w) for k in head))
            for k in tail:
                self.out.append(" " + inline(k, w))
            self.out.append(")")
        self.out.append("\n" + IND * (nest + 1) + ")")

    # -- model ----------------------------------------------------------------
    def model(self, node, nest):
        w = self.w
        kids = node[1:]
        head = [k for k in kids if isinstance(k, str)]              # path, "hide"
        self.p(nest, "(model " + " ".join(head) + "\n")
        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n == "opacity":
                self.p(nest + 1, inline(k, w))                      # NO trailing newline (source)
            else:
                self.p(nest + 1, inline(k, w) + "\n")
        self.p(nest, ")\n")

    # -- group ----------------------------------------------------------------
    def group(self, node, nest):
        kids = node[1:]
        head = [inline(k, self.w) for k in kids if isinstance(k, str) or name_of(k) == "id"]
        self.p(nest, "(group " + " ".join(head) + "\n")
        for k in kids:
            if name_of(k) == "members":
                self.p(nest + 1, "(members\n")
                for m in k[1:]:
                    self.p(nest + 2, m + "\n")
                self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    # -- zone (6.0/7.0; no .kicad_mod fixtures of these versions contain zones) --
    def zone(self, node, nest):
        w = self.w
        kids = node[1:]
        line1, rest = [], []
        for k in kids:
            n = name_of(k) if isinstance(k, list) else ""
            if isinstance(k, str) or n in ("net", "net_name", "layer", "layers", "tstamp", "name", "hatch"):
                line1.append(k)
            else:
                rest.append(k)
        self.p(nest, "(zone " + " ".join(inline(k, w) for k in line1) + "\n")
        for k in rest:
            n = name_of(k)
            if n == "fill":
                self.zone_fill(k, nest + 1)
            elif n == "min_thickness":
                self.p(nest + 1, inline(k, w))
                self.out.append("\n")  # (filled_areas_thickness no) is a sibling in the tree -> handled below
            elif n == "filled_areas_thickness":
                # written on the min_thickness line: back-patch
                self.out[-1] = " " + inline(k, w) + "\n"
            elif n in ("polygon", "filled_polygon"):
                self.p(nest + 1, "(" + n + "\n")
                for sub in k[1:]:
                    if name_of(sub) == "pts":
                        if w in ("5.99", "6.0"):
                            self.out.append(IND * (nest + 2) + "(pts")
                            for pt in sub[1:]:
                                self.out.append("\n" + IND * (nest + 3) + inline(pt, w))
                            self.out.append("\n" + IND * (nest + 2) + ")\n")
                        else:
                            self.poly_pts(sub, nest + 1, compact=False)
                    else:
                        self.p(nest + 2, inline(sub, w) + "\n")
                self.p(nest + 1, ")\n")
            elif n == "keepout" and self.keepout_pads_space:
                txt = inline(k, w).replace("(pads allowed)", "(pads allowed )") \
                                  .replace("(pads not_allowed)", "(pads not_allowed )")
                self.p(nest + 1, txt + "\n")
            else:
                self.p(nest + 1, inline(k, w) + "\n")
        self.p(nest, ")\n")

    def zone_fill(self, node, nest):
        w = self.w
        line = "(fill"
        extra = []
        for k in node[1:]:
            n = name_of(k) if isinstance(k, list) else ""
            if n.startswith("hatch_"):
                extra.append(k)
            else:
                line += " " + inline(k, w)
        self.out.append(IND * nest + line)
        if extra:
            # hatch params: 2 or 3 lines at nest+1 (pairs: thickness/gap/orientation ; smoothing ; border/min_hole)
            groups = [[], [], []]
            for k in extra:
                n = name_of(k)
                gi = 0 if n in ("hatch_thickness", "hatch_gap", "hatch_orientation") else \
                     1 if n.startswith("hatch_smoothing") else 2
                groups[gi].append(k)
            for g in groups:
                if g:
                    self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in g))
        self.out.append(")\n")


def format_tree(tree, writer: str, keepout_pads_space: bool = False) -> str:
    f = Formatter(writer, keepout_pads_space)
    f.footprint(tree, 0)
    return "".join(f.out)


def detect_writer(tree) -> str:
    if name_of(tree) == "module":
        return "5.1"
    for k in tree[1:]:
        if name_of(k) == "version":
            v = int(k[1])
            if v < 20211014:
                return "5.99"          # 6.0 development nightlies (only header differs from 6.0)
            return "6.0" if v < 20221018 else "7.0"
    return "6.0"


def _meta(tree):
    d = {}
    for k in tree[1:]:
        if isinstance(k, list) and k and k[0] in ("version", "generator"):
            d[k[0]] = k[1]
    return d


def check_file(path: str, writer: str = "auto"):
    """Returns (path, writer_used, meta, class, diff). class is one of
    exact | exact-no-final-nl | header-only | other | EXC"""
    raw = open(path, "rb").read()
    tree = tokenize(raw.decode("utf-8"))
    meta = _meta(tree)
    w = detect_writer(tree) if writer == "auto" else writer
    candidates = [(w, False)]
    if w == "6.0":
        # 6.0.0-6.0.6 keepout stray space; 20211014 files written by nightlies 2021-10-15..11-13
        candidates += [(w, True), ("5.99", False), ("5.99", True)]
    try:
        best = None
        for cw, kps in candidates:
            out = format_tree(tree, cw, kps).encode("utf-8")
            if out == raw:
                return path, cw + (" +keepout-space" if kps else ""), meta, "exact", ""
            if out.rstrip(b"\n") == raw.rstrip(b"\n"):
                best = best or (cw + (" +keepout-space" if kps else ""), "exact-no-final-nl", "")
            if best is None and cw == w and not kps:
                first = out
        if best:
            return (path, best[0], meta, best[1], "")
    except Exception as e:  # noqa: BLE001
        return path, w, meta, "EXC", f"{type(e).__name__}: {e}"
    ro, oo = raw.split(b"\n"), first.split(b"\n")
    if b"\n".join(ro[2:]).rstrip(b"\n") == b"\n".join(oo[2:]).rstrip(b"\n"):
        return path, w, meta, "header-only", first_difference(raw, first)
    return path, w, meta, "other", first_difference(raw, first)


def _worker(a):
    return check_file(*a)


def main(argv):
    from multiprocessing import Pool
    writer = "auto"
    paths = []
    for a in argv:
        if a.startswith("--writer="):
            writer = a.split("=", 1)[1]
        elif os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "**", "*.kicad_mod"), recursive=True))
        else:
            paths.append(a)
    with Pool() as pool:
        res = pool.map(_worker, [(p, writer) for p in paths], chunksize=32)
    print(f"files={len(res)}")
    c = collections.Counter((r[1], r[2].get("version"), r[2].get("generator"), r[3]) for r in res)
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {v:6d}  writer={k[0]:<22} version={k[1]} generator={k[2]} -> {k[3]}")
    shown = 0
    for r in res:
        if r[3] in ("other", "header-only", "EXC") and shown < 15:
            print("  DIFF", r[3], r[0], "::", r[4][:260])
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Вспомогательные скрипты проверки (в `scratchpad/research/`, в документ не включены): `xyclass.py` (классификация Prettify-файлов по generator/стилю), `l67report.py`, `l67feat.py` (статистика и покрытие узлов для `layout67.py`), `atom_after_list.py` (поиск атомов после вложенных списков), `heads.py`.
