# Порядок и условия записи токенов writer'ом KiCad (`.kicad_mod`)

Спецификация для реализации записи/нормализации `.kicad_mod` в `kicadfp` (см. `architecture.md`,
модули `format_rules.py`, `sexpr.py`). Описано, **какие** токены пишет штатный writer KiCad, **в
каком порядке**, **при каком условии**, **с какими аргументами**, и что идёт в кавычках, а что —
голым символом. Раскладка пробелов/переводов строк сюда не входит — см. `format-layout.md`
(для 8.0+ её делает `KICAD_FORMAT::Prettify`, порт — `scratchpad/research/prettify.py`).

Основная версия — **KiCad 9.0**; для 10.0, 8.0, 7.0, 6.0 перечислены отличия. Каждое
утверждение снабжено ссылкой `файл:строка`; утверждения, подтверждённые на реальных файлах,
помечены ✔ (числа — в разделе «Проверено»). Всё, что не удалось подтвердить, помечено
**«не проверено»**.

---

## 0. Соглашения

### 0.1. Источники (сокращения)

Локальные копии: `scratchpad/kicad-src/<ветка>/<путь с '/' → '_'>`. Номера строк — по этим копиям.

| Сокр. | Файл в репозитории KiCad | Ветка |
|---|---|---|
| **W9** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp` | `9.0` (голова ветки; по поведению = тег 9.0.7, см. §7.4) |
| **W10** | то же | `10.0` (SEXPR 20260206 — версия файлов kicad-footprints `master`) |
| **W8** | то же | `8.0` |
| **W7** | `pcbnew/plugins/kicad/pcb_plugin.cpp` (класс `PCB_PLUGIN`) | `7.0` |
| **W6** | `pcbnew/plugins/kicad/pcb_plugin.cpp` (класс `PCB_PLUGIN`) | `6.0` |
| **W5** | `pcbnew/kicad_plugin.cpp` (класс `PCB_IO`, корень `module`) | `5.1` (только справочно, §12) |
| **Wm** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp` | `master` (11.0-dev, SEXPR 20260901; только §11) |
| **H6..H10, Hm** | соответствующие `.h` (`pcb_plugin.h` / `pcb_io_kicad_sexpr.h`) | |
| **T6..T10** | `common/eda_text.cpp` (`EDA_TEXT::Format`) | |
| **U8..U10** | `common/io/kicad/kicad_io_utils.cpp` (`FormatBool`, `FormatUuid`, `Prettify`) | |
| **SP7..SP10** | `common/stroke_params.cpp` | |
| **EU7..EU10** | `common/eda_units.cpp` (`FormatInternalUnits`, `FormatAngle`) | |
| **BU6** | `common/base_units.cpp` (то же для 6.0) | |
| **SU6..SU10** | `common/string_utils.cpp` (`FormatDouble2Str`/`Double2Str`, `StrNumCmp`, `EscapeString`) | |
| **RIO** | `common/richio.cpp` (`OUTPUTFORMATTER::Quotes/Quotew`) | |
| **LEX** | `common/dsnlexer.cpp` (`DSNLEXER`) | |
| **FP6..FP10** | `pcbnew/footprint.cpp` (компараторы сортировки) | |
| **TI6..TI10** | `include/core/typeinfo.h` (`KICAD_T`) | |
| **ES** | `include/eda_shape.h` (`SHAPE_T`) | |
| **P9** | `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp` | `9.0` |
| **CF9** | `include/ctl_flags.h` | `9.0` |
| **tags/9.0.x** | `scratchpad/kicad-src/tags/9.0.{0,4,5,6,7}-pcb_io_kicad_sexpr.cpp` | теги |

### 0.2. Наборы реальных файлов (kicad-footprints)

| Сокр. | Каталог | Файлы, записанные pcbnew | Версия формата |
|---|---|---|---|
| **K6** | `kfp/v7.0.0` | 1306 (`generator pcbnew`) | 20211014 = writer **6.0** |
| **K8** | `kfp/v8.0.0` | 1377 | 20240108 = writer 8.0 |
| **K9** | `kfp/v9.0.0` | 1860 (+1437 файлов генератора, 20240108) | 20241229 = writer 9.0 |
| **K10** | `kfp/master` | 643 (+4239 файлов генератора) | 20260206 = writer 10.0 |

Файлов, записанных writer'ом **7.0** (20221018), в наборах нет — всё про 7.0 проверено только
по исходнику. Кураторские фикстуры `tests/fixtures/{kicad6,kicad8,kicad9,kicad10dev}` — подмножества
тех же файлов; прогон на них — в «Проверено».

### 0.3. Обозначения форм аргументов

| Обозначение | Смысл | Где определено |
|---|---|---|
| `Q(s)` | строка **всегда** в двойных кавычках, с экранированием `\n \r \\ \"` | RIO9:509-556, §9.1 |
| `IU(v)` | `FormatInternalUnits`: целое в нм → текст в мм | EU9:170-200, §8.1 |
| `XY(p)` | `IU(p.x) IU(p.y)` через один пробел | EU9:203-208 |
| `ANG(a)` | `FormatAngle`: градусы, `%.10g` | EU9:162-167, §8.3 |
| `D2S(v)` | `FormatDouble2Str` (6.0: `Double2Str`, тот же алгоритм) | SU9:1372-1399, §8.2 |
| `BOOL(k,v)` | `(k yes)` / `(k no)` | U9:35-38 |
| `UUID` | 8.0+: `(uuid "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")` (в кавычках); 6.0/7.0: `(tstamp xxxxxxxx-…)` голый | U9:41-44, U8:36-42, W6:1066, W7:1114 |
| «голый» | символ без кавычек (bare token) | |
| `[…]` | необязательный элемент (условие — в таблице) | |

### 0.4. Режим записи библиотеки — что никогда не попадает в `.kicad_mod`

`FootprintSave()` выставляет `m_ctl = CTL_FOR_LIBRARY` (W9:2900), где
`CTL_FOR_LIBRARY = CTL_OMIT_PAD_NETS | CTL_OMIT_UUIDS | CTL_OMIT_PATH | CTL_OMIT_AT | CTL_OMIT_LIBNAME`
(H9:191-192; в 6.0/7.0 вместо `CTL_OMIT_UUIDS` — `CTL_OMIT_TSTAMPS`: H6:127-128, H7:160-161;
значения битов — CF9:27-46). Перед записью копия посадочного места поворачивается в 0° (W9:2963)
и, если она не на `F.Cu`, переворачивается (W9:2965-2973). Следствия для файла библиотеки:

* нет корневых `(uuid …)`/`(tstamp …)`, `(at …)`, `(path …)` ✔ (K6…K10: 0 файлов с ними);
* имя без `lib:` (только `LibItemName`);
* у падов нет `(net …)`, `(pinfunction …)`, `(pintype …)`; у пада нет `(zone_layer_connections …)`
  (пишется только при наличии платы, W9:1555);
* корневой `(layer "F.Cu")` ✔ (K6…K10: 100 %);
* `CTL_OMIT_INITIAL_COMMENTS` в набор **не входит** → сохранённые начальные комментарии пишутся (§1.1, п. 1);
* парсер при чтении посадочного места сбрасывает `locked` (P9:868-869 «Locking a footprint has no
  meaning outside of a board») → корневой `locked` в библиотеках на практике не встречается ✔.

### 0.5. Про пробелы в форматных строках 9.0+

С 9.0 writer печатает сплошной поток без переводов строк, а файл затем проходит `Prettify`
(`PRETTIFIED_FILE_OUTPUTFORMATTER`, W9:131). Некоторые форматные строки дают лишние пробелы:
`"(layer %s %s)"` с пустым вторым аргументом → `(layer "F.Cu" )`, `"(at %s %s)"` без угла →
`(at 0 0 )`, `"(tenting %s %s)"`. `Prettify` удаляет пробел перед `)` и схлопывает повторные
пробелы (проверено портом: `(layer "F.Cu" )` → `(layer "F.Cu")`, `(tenting front )` →
`(tenting front)`). Реализации достаточно порождать дерево и сериализовать его своим принтером.

---

## 1. Корневой узел `footprint`

### 1.1. KiCad 9.0 — `format(const FOOTPRINT*)`, W9:1083-1342

| № | Токен (форма) | Пишется если | Источник |
|---|---|---|---|
| 1 | строки начальных комментариев, каждая + `\n` | `!CTL_OMIT_INITIAL_COMMENTS` и они были прочитаны (строки `#…` перед корнем, P9:845) | W9:1085-1094 |
| 2 | `(footprint Q(name)` | всегда; `name` = `LibItemName` при `CTL_OMIT_LIBNAME` (библиотека), иначе `lib:name` | W9:1096-1105 |
| 3 | `(version 20241229)` — голое целое | `!CTL_OMIT_FOOTPRINT_VERSION` (в библиотеке всегда) | W9:1107-1112, H9:175 |
| 4 | `(generator "pcbnew")` — литерал в кавычках | то же | W9:1109 |
| 5 | `(generator_version Q("9.0"))` — `GetMajorMinorVersion()` | то же | W9:1109-1111 |
| 6 | `(locked yes)` | `IsLocked()` | W9:1114-1115 |
| 7 | `(placed yes)` | `IsPlaced()` | W9:1117-1118 |
| 8 | `(layer Q(слой))` | всегда | W9:1120 |
| 9 | `UUID` | `!CTL_OMIT_UUIDS` (в библиотеке — нет) | W9:1122-1123 |
| 10 | `(at XY [ANG])`, угол только если ориентация ≠ 0 | `!CTL_OMIT_AT` (в библиотеке — нет) | W9:1125-1132 |
| 11 | `(descr Q)` | описание непусто | W9:1134-1135 |
| 12 | `(tags Q)` | ключевые слова непусты | W9:1137-1138 |
| 13 | `(property Q(имя) Q(значение) …тело…)` — по одному на поле, тело §2.1 | для каждого `field` из `GetFields()`, `nullptr` пропускается | W9:1140-1153 |
| 14 | `(component_classes (class Q(имя))…)` | класс компонента есть и не пуст | W9:1155-1166 |
| 15 | `(property ki_fp_filters Q(фильтры))` — **имя голое** | фильтры непусты | W9:1168-1172 |
| 16 | `(path Q)` | `!CTL_OMIT_PATH` и путь непуст (в библиотеке — нет) | W9:1174-1175 |
| 17 | `(sheetname Q)` | непусто | W9:1177-1178 |
| 18 | `(sheetfile Q)` | непусто | W9:1180-1181 |
| 19 | `(solder_mask_margin IU)` | значение задано (`std::optional::has_value`; **0 тоже пишется**) | W9:1183-1187 |
| 20 | `(solder_paste_margin IU)` | has_value | W9:1189-1193 |
| 21 | `(solder_paste_margin_ratio D2S)` | has_value | W9:1195-1199 |
| 22 | `(clearance IU)` | has_value | W9:1201-1205 |
| 23 | `(zone_connect N)` — целое `%d` | `≠ INHERITED(-1)`; `NONE=0, THERMAL=1, FULL=2, THT_THERMAL=3` (`pcbnew/zones.h` 9.0:46-53) | W9:1207-1211 |
| 24 | `(attr f1 f2 …)` — флаги голые, порядок фиксирован: `smd through_hole board_only exclude_from_pos_files exclude_from_bom allow_missing_courtyard dnp allow_soldermask_bridges` | `GetAttributes() ≠ 0` | W9:1213-1243 |
| 25 | `(private_layers Q Q …)` — слои по возрастанию ID (`LSET::Seq()`) | есть приватные слои | W9:1245-1256 |
| 26 | `(net_tie_pad_groups Q Q …)` | `IsNetTie()` | W9:1258-1266 |
| 27 | графика (`fp_line`, `fp_rect`, `fp_arc`, `fp_circle`, `fp_poly`, `fp_curve`, `image`, `fp_text user`, `fp_text_box`, `table`, `dimension`) | в порядке `cmp_drawings` (§1.7) | W9:1273-1284 |
| 28 | `(pad …)` ×N | в порядке `cmp_pads` (§1.7) | W9:1271-1272, 1287-1288 |
| 29 | `(zone …)` ×N | в порядке `cmp_zones` | W9:1276-1277, 1291-1292 |
| 30 | `(group …)` ×N | в порядке `PCB_GROUP::ptr_cmp` (= `BOARD_ITEM::ptr_cmp`) | W9:1278-1279, 1295-1296 |
| 31 | `BOOL(embedded_fonts, …)` → `(embedded_fonts no)` | **всегда** | W9:1298-1299 |
| 32 | `(embedded_files …)` | есть встроенные файлы (структура — `WriteEmbeddedFiles`, не документируется) | W9:1301-1302 |
| 33 | `(model …)` ×N, §5 | для каждой модели с непустым именем, **в исходном порядке** | W9:1305-1339 |
| 34 | `)` | | W9:1341 |

Замечания.

* Reference и Value в 9.0 — обычные поля (п. 13). Вызовы `Format(&Reference())`/`Format(&Value())`
  (W9:1268-1269) ничего не выводят: ветка `PCB_FIELD_T` в `Format()` пустая (W9:393-395).
* Порядок полей — порядок `GetFields()`. В реальных файлах ✔: 9.0 — `"Reference" "Value" "Datasheet"
  "Description"` (K9: по 1860), 10.0 — то же (K10: по 643), 8.0 — `"Reference" "Value" "Footprint"
  "Datasheet" "Description"` (K8: по 1377). Имя — `GetCanonicalName()`.
* Пример (K9, `CP_Elec_6.3x3.kicad_mod`, после Prettify):

```
(footprint "CP_Elec_6.3x3"
	(version 20241229)
	(generator "pcbnew")
	(generator_version "9.0")
	(layer "F.Cu")
	(descr "SMD capacitor, aluminum electrolytic, Nichicon, 6.3x3.0mm")
	(tags "capacitor electrolytic")
	(property "Reference" "REF**" …)
	…
	(attr smd)
	(fp_line …) … (fp_circle …) (fp_text user "${REFERENCE}" …)
	(pad "1" smd roundrect …) (pad "2" smd roundrect …)
	(embedded_fonts no)
	(model "${KICAD9_3DMODEL_DIR}/Capacitor_SMD.3dshapes/CP_Elec_6.3x3.wrl" …)
)
```

### 1.2. KiCad 10.0 — отличия (W10:1187-1547)

| Место | Изменение | Источник |
|---|---|---|
| после `sheetfile` | `(units (unit (name Q) (pins Q Q …))…)` если `GetUnitInfo()` непуст | W10:1286-1304 |
| `component_classes` | берётся `GetStaticComponentClass()`, имя класса — `GetName()` | W10:1258-1269 |
| `attr` | пишется, если `GetAttributes()≠0` **или** `AllowMissingCourtyard()` **или** `AllowSolderMaskBridges()`; порядок флагов тот же | W10:1337-1368 |
| после `attr` | `(stackup (layer Q)…)` если режим стека ≠ `EXPAND_INNER_LAYERS` | W10:1370-1383 |
| после `net_tie_pad_groups` | `BOOL(duplicate_pad_numbers_are_jumpers, …)` — **всегда** ✔ (K10: 643/643 `no`) | W10:1408-1409 |
| далее | `(jumper_pad_groups (Q Q …) …)` если есть; имена в группе — порядок `std::set<wxString>` | W10:1411-1428 |
| после графики | `(point (at XY) (size IU) (layer Q) UUID)` в порядке `PCB_POINT::cmp_points` | W10:1438-1452, 1157-1168 |
| после групп | `(variant (name Q) [BOOL(dnp)] [BOOL(exclude_from_bom)] [BOOL(exclude_from_pos_files)] [(field (name Q) (value Q))…])` — только отличия от базовых значений | W10:1466-1501 |
| `model` | `opacity` через `fmt::format("(opacity {:.4f})")` — тот же текст, что `%0.4f` | W10:1522-1523 |

Итоговый порядок 10.0: `version generator generator_version [locked] [placed] layer [uuid] [at]
[descr] [tags] property… [component_classes] [property ki_fp_filters] [path] [sheetname] [sheetfile]
[units] [solder_mask_margin] [solder_paste_margin] [solder_paste_margin_ratio] [clearance]
[zone_connect] [attr] [stackup] [private_layers] [net_tie_pad_groups] duplicate_pad_numbers_are_jumpers
[jumper_pad_groups] графика… point… pad… zone… group… variant… embedded_fonts [embedded_files] model…`
✔ (K10: 643/643).

### 1.3. KiCad 8.0 — отличия от 9.0 (W8:1099-1357)

* Нет `component_classes`, `embedded_fonts`, `embedded_files`.
* Маржины/зазор пишутся при `≠ 0` (не optional): `solder_mask_margin`, `solder_paste_margin`,
  `clearance` (W8:1203-1225); **на уровне footprint коэффициент называется `(solder_paste_ratio D2S)`**
  (W8:1215-1219). У пада — `solder_paste_margin_ratio` во всех версиях.
* `generator_version` печатается как `"%s"` вручную (W8:1126-1127) — результат тот же `"8.0"`.
* `private_layers`: каждое имя как `" \"%s\""` — кавычки вручную, без экранирования (W8:1272).
* `net_tie_pad_groups`: `" \"%s\""` с `EscapeString(group, CTX_QUOTED_STR)` — символ `"` заменяется на
  `{dblquote}`, прочее без экранирования (W8:1283; SU8:228-234).
* Флаги `attr` — тот же порядок, с `dnp` (W8:1234-1263).

### 1.4. KiCad 7.0 — отличия (W7:1138-1370)

| № | Токен | Условие / отличие | Источник |
|---|---|---|---|
| 1 | `(footprint Q(name)` | | W7:1153-1162 |
| 2 | `(version 20221018) (generator pcbnew)` — **generator голый**, нет `generator_version` | | W7:1164-1165, H7:136 |
| 3 | `locked` — **голый атом корня** | `IsLocked()` | W7:1167-1168 |
| 4 | `placed` — голый атом | `IsPlaced()` | W7:1170-1171 |
| 5 | `(layer Q)` | | W7:1173 |
| 6 | `(tstamp UUID-без-кавычек)` | `!CTL_OMIT_TSTAMPS` (в библиотеке — нет); `tedit` удалён (20220225) | W7:1177-1178 |
| 7 | `(at XY [ANG])` | как 9.0 | W7:1180-1189 |
| 8 | `(descr Q)`, `(tags Q)` | непусты | W7:1191-1201 |
| 9 | `(property Q Q)` — **без тела**, по одному на пару `GetProperties()` (`std::map` → по возрастанию ключа) | | W7:1203-1210 |
| 10 | `(path Q)` | | W7:1212-1216 |
| 11 | `(solder_mask_margin IU)`, `(solder_paste_margin IU)`, `(solder_paste_ratio D2S)`, `(clearance IU)` | `≠ 0` | W7:1218-1240 |
| 12 | `(zone_connect N)` | `≠ INHERITED` | W7:1242-1246 |
| 13 | `(attr …)`: `smd through_hole board_only exclude_from_pos_files exclude_from_bom allow_missing_courtyard allow_soldermask_bridges` (без `dnp`) | `≠ 0` | W7:1249-1275 |
| 14 | `(private_layers "…" …)` вручную в кавычках | | W7:1277-1288 |
| 15 | `(net_tie_pad_groups "…" …)` с `EscapeString(CTX_QUOTED_STR)` | | W7:1290-1301 |
| 16 | `(fp_text reference …)`, `(fp_text value …)` | всегда | W7:1303-1304 |
| 17 | графика, пады, зоны, группы (сортировки 7.0, §1.7) | | W7:1306-1331 |
| 18 | `(model …)` (голый `hide`, §5) | | W7:1334-1367 |

### 1.5. KiCad 6.0 — отличия (W6:1090-1287)

| № | Токен | Условие / отличие | Источник |
|---|---|---|---|
| 1 | `(footprint Q(name) (version 20211014) (generator pcbnew)` | | W6:1105-1113, H6:105 |
| 2 | `locked`, `placed` — голые | | W6:1115-1119 |
| 3 | `(layer Q)` | | W6:1121 |
| 4 | `(tedit HEX)` — **всегда**, `%lX`: заглавные hex без ведущих нулей, без кавычек | | W6:1124 |
| 5 | `(tstamp UUID)` | `!CTL_OMIT_TSTAMPS` (в библиотеке — нет) | W6:1126-1127 |
| 6 | `(at XY [ANG])`, `(descr Q)`, `(tags Q)`, `(property Q Q)…`, `(path Q)` | как 7.0 | W6:1131-1161 |
| 7 | `(autoplace_cost90 N)`, `(autoplace_cost180 N)` | `≠ 0` | W6:1163-1167 |
| 8 | `(solder_mask_margin IU)`, `(solder_paste_margin IU)`, `(solder_paste_ratio D2S)`, `(clearance IU)`, `(zone_connect N)` | `≠ 0` / `≠ INHERITED` | W6:1169-1187 |
| 9 | `(thermal_width IU)`, `(thermal_gap IU)` | `≠ 0` | W6:1189-1195 |
| 10 | `(attr …)`: `smd through_hole board_only exclude_from_pos_files exclude_from_bom` | `≠ 0` | W6:1198-1218 |
| 11 | `fp_text reference`, `fp_text value`, графика, пады, зоны (`BOARD_ITEM::ptr_cmp`), группы, модели | | W6:1220-1284 |

Пример (K6, `R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal.kicad_mod`):

```
(footprint "R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal" (version 20211014) (generator pcbnew)
  (layer "F.Cu")
  (tedit 5AE5139B)
  (descr "Resistor, Axial_DIN0204 series, …")
  (tags "Resistor Axial_DIN0204 series …")
  (attr through_hole)
  (fp_text reference "REF**" (at 2.54 -1.92) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15)))
    (tstamp ebea55fe-536f-4927-aa8d-6fcdfd78ce7a)
  )
  …
```

### 1.6. Сводка корневых токенов по версиям

| Токен | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 |
|---|---|---|---|---|---|
| `generator` | голый | голый | `"pcbnew"` | `"pcbnew"` | `"pcbnew"` |
| `generator_version` | — | — | `"8.0"` | `"9.0"` | `"10.0"` |
| `locked` / `placed` | голые | голые | `(locked yes)` / `(placed yes)` | то же | то же |
| `tedit` | всегда | — | — | — | — |
| корневой id (не в библиотеке) | `tstamp` | `tstamp` | `uuid "…"` | `uuid "…"` | `uuid "…"` |
| Reference/Value | `fp_text reference/value` | `fp_text …` | `property` | `property` | `property` |
| `property` прочие | `(property Q Q)` | `(property Q Q)` | поле с телом | поле с телом | поле с телом |
| `ki_fp_filters` | — | — | `(property ki_fp_filters Q)` | то же | то же |
| `sheetname`/`sheetfile` | — | — | есть | есть | есть |
| `component_classes` | — | — | — | есть | есть |
| `units` | — | — | — | — | есть |
| коэф. пасты | `solder_paste_ratio` | `solder_paste_ratio` | `solder_paste_ratio` | `solder_paste_margin_ratio` | `solder_paste_margin_ratio` |
| условие маржинов | `≠0` | `≠0` | `≠0` | has_value | has_value |
| `autoplace_cost*`, `thermal_width/gap` (корень) | есть | — | — | — | — |
| `attr: allow_missing_courtyard`, `allow_soldermask_bridges` | — | есть | есть | есть | есть |
| `attr: dnp` | — | — | есть | есть | есть |
| `private_layers`, `net_tie_pad_groups` | — | есть | есть | есть | есть |
| `stackup`, `duplicate_pad_numbers_are_jumpers`, `jumper_pad_groups`, `point`, `variant` | — | — | — | — | есть |
| `embedded_fonts` (всегда) | — | — | — | есть | есть |
| `model hide` | голый | голый | `(hide yes)` | `(hide yes)` | `(hide yes)` |

### 1.7. Сортировка при записи

Writer складывает элементы в `std::set<…, компаратор>` и выводит в порядке множества (W9:1271-1296).
`kicadfp` сохраняет исходный порядок, но генераторы/нормализатор должны знать этот порядок,
чтобы сохранённый ими файл совпадал с тем, что записал бы KiCad.

Важное следствие `std::set`: элементы, **эквивалентные** по компаратору, схлопываются (второй не
вставляется). На практике ключ дополняется UUID, поэтому это не происходит (см. п. про `StrNumCmp`).

**`cmp_drawings`, 8.0/9.0** (FP8:3193-3268, FP9:3774-3848) — ключи по очереди:

1. `Type()` (`KICAD_T`, TI9): `PCB_SHAPE_T`(12) < `PCB_REFERENCE_IMAGE_T`(13) < `PCB_FIELD_T`(14) <
   `PCB_GENERATOR_T`(15) < `PCB_TEXT_T`(16) < `PCB_TEXTBOX_T`(17) < `PCB_TABLE_T`(18, 9.0) < … <
   `PCB_DIM_*`. Итого: **вся графика, затем `image`, затем `fp_text user`, затем `fp_text_box`, `table`,
   размеры** ✔.
2. `GetLayer()` — числовой `PCB_LAYER_ID` **своей версии** (`docs/dev/layers.json`, ключ `ids`).
   8.0: `F.Cu`=0…`B.Cu`=31, `B.Adhes`=32, `F.Adhes`=33, `B.Paste`=34, `F.Paste`=35, `B.SilkS`=36,
   `F.SilkS`=37, `B.Mask`=38, `F.Mask`=39, `Dwgs.User`=40, `Cmts.User`=41, `Eco1.User`=42, `Eco2.User`=43,
   `Edge.Cuts`=44, `Margin`=45, `B.CrtYd`=46, `F.CrtYd`=47, `B.Fab`=48, `F.Fab`=49.
   9.0: `F.Cu`=0, `F.Mask`=1, `B.Cu`=2, `B.Mask`=3, `F.SilkS`=5, `B.SilkS`=7, `F.Adhes`=9, `B.Adhes`=11,
   `F.Paste`=13, `B.Paste`=15, `Dwgs.User`=17, `Cmts.User`=19, `Eco1.User`=21, `Eco2.User`=23,
   `Edge.Cuts`=25, `Margin`=27, `B.CrtYd`=29, `F.CrtYd`=31, `B.Fab`=33, `F.Fab`=35 (внутренние медные —
   чётные 4…62).
3. только для `PCB_SHAPE`: `GetShape()` — `SEGMENT`(0, `fp_line`) < `RECTANGLE`(1, `fp_rect`) <
   `ARC`(2) < `CIRCLE`(3) < `POLY`(4) < `BEZIER`(5) (ES 9.0:42-51); затем для не-POLY:
   `start.x, start.y, end.x, end.y` (целые нм; у окружности start = центр, end = точка на окружности;
   у кривой — первая/последняя точка); затем ARC: `center.x, center.y`; BEZIER: `c1.x, c1.y, c2.x, c2.y`;
   POLY: число вершин, затем все вершины `x, y` по порядку; затем толщина линии (`stroke width`).
4. `m_Uuid` — `KIID::operator<` (побайтовое сравнение; эквивалентно сравнению строк UUID в нижнем
   регистре).
5. адрес объекта (недетерминированно, на практике не достигается).

10.0 (FP10:4346-4453): то же, плюс для `PCB_TEXT_T` (fp_text user): позиция, угол, размер,
толщина, bold, italic, mirror, межстрочный интервал, текст. 7.0 (FP7:2825-2863): те же ключи по
`FP_SHAPE_T` с «нулевыми» (относительными) координатами, но порядок типов другой:
`PCB_FP_TEXT_T`(16) < `PCB_FP_TEXTBOX_T`(17) < `PCB_FP_SHAPE_T`(18) (TI7) — **в 6.0/7.0
`fp_text user` идут перед графикой**. 6.0 (FP6:2199-2221): тип (`PCB_FP_TEXT_T`=16 <
`PCB_FP_SHAPE_T`=17, TI6), слой, вид фигуры, UUID — без координат.

**`cmp_pads`, 9.0** (FP9:3851-3894):

1. если номера различны — `StrNumCmp(a, b) < 0` (регистр учитывается);
2. позиция относительно footprint: `x`, затем `y`;
3. по каждому уникальному слою падстека («самого сложного» из двух): `size.x`, `size.y`, форма
   (`PAD_SHAPE`: `CIRCLE`0 `RECTANGLE`1 `OVAL`2 `TRAPEZOID`3 `ROUNDRECT`4 `CHAMFERED_RECT`5 `CUSTOM`6,
   `pcbnew/padstack.h` 9.0:51-63);
4. `GetLayerSet().Seq()` — лексикографически как вектор ID;
5. UUID.

8.0 (FP8:3270-3296): номер, позиция, `size.x`, `size.y`, форма, `Seq()` слоёв, UUID. 7.0 (FP7:2866-2879):
то же с `GetPos0()`. 6.0 (FP6:2224-2233): только номер (`StrNumCmp`) и UUID. 10.0 (FP10:4456-4497): как
9.0, слои сравниваются как `LSET`.

Особенность: при разных строках номера, для которых `StrNumCmp` возвращает 0 (например `"1"` и
`"01"` — числа равны, хвостов нет), компаратор даёт `false` в обе стороны — такие пады
эквивалентны для `std::set`, и второй при записи потерялся бы. **Не проверено** в KiCad.

`StrNumCmp` (SU9:804-883) — порт:

```python
def strnumcmp(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) and j < len(b):
        c1, c2 = a[i], b[j]
        if c1.isdigit() and c2.isdigit():          # wxIsdigit
            n1 = 0
            while True:
                n1 = n1 * 10 + ord(a[i]) - 48; i += 1
                if not (i < len(a) and a[i].isdigit()): break
            n2 = 0
            while True:
                n2 = n2 * 10 + ord(b[j]) - 48; j += 1
                if not (j < len(b) and b[j].isdigit()): break
            if n1 != n2: return -1 if n1 < n2 else 1
            c1 = a[i] if i < len(a) else "\0"
            c2 = b[j] if j < len(b) else "\0"
        if c1 != c2: return -1 if c1 < c2 else 1    # сравнение кодов символов
        if i < len(a): i += 1
        if j < len(b): j += 1
    if i >= len(a) and j < len(b): return -1
    if i < len(a) and j >= len(b): return 1
    return 0
```

**`cmp_zones`, 9.0** (FP9:3954-3977): приоритет, `Seq()` слоёв, число вершин контура, вершины, UUID.
6.0 — `BOARD_ITEM::ptr_cmp` (W6:1228). **Группы** — `BOARD_ITEM::ptr_cmp` (`pcbnew/board_item.cpp`
9.0:270-282): тип, `Seq()` слоёв, UUID. **Модели** не сортируются.

✔ Все файлы pcbnew K6 (1306), K8 (1377), K9 (1860), K10 (643) упорядочены ровно так
(`writer_check.py`, полный ключ `cmp_drawings`/`cmp_pads` соответствующей версии; для 10.0 ключ
текста упрощён до позиции+угла+UUID). Файлы генератора `kicad-footprint-generator` этому порядку
следуют не всегда (K9-gen: 8 файлов с неотсортированной графикой, 1 — падами; K10-gen: `point`
после `pad` в 326 файлах) — это не вывод KiCad.

---

## 2. Тексты: поля (`property`) и `fp_text`

### 2.1. KiCad 9.0 — `format(const PCB_TEXT*)`, W9:1956-2017

Одна функция пишет и поле (`PCB_FIELD`, наследник `PCB_TEXT`), и пользовательский текст. Для поля
заголовок `(property Q(имя) Q(значение)` и закрывающую `)` печатает `format(FOOTPRINT)` (W9:1146-1152),
а `format(PCB_TEXT)` пишет только тело.

| № | Токен | Пишется если | Источник |
|---|---|---|---|
| 0 | `(fp_text user Q(текст)` — тип **всегда** `user` (Reference/Value — поля) | не поле | W9:1968-1971, 1981-1986 |
| 0a | `(locked yes)` | не поле и `IsLocked()` | W9:1988-1989 |
| 1 | `(at XY ANG)` — **угол пишется всегда**, в т. ч. `0` | всегда | W9:1992-1994 |
| 2 | `(unlocked yes)` | есть родительский footprint и `!IsKeepUpright()` | W9:1996-1997 |
| 3 | `(layer Q [knockout])` — `knockout` голый | всегда; `knockout` при `IsKnockout()` | W9:1999, 458-463 |
| 4 | `(hide yes)` | **только поле** и `!IsVisible()` | W9:2001-2002 |
| 5 | `UUID` | всегда | W9:2004 |
| 6 | `(effects …)`, §2.2; флаги `CTL_OMIT_COLOR \| CTL_OMIT_HYPERLINK` | всегда | W9:2008-2010 |
| 7 | `(render_cache …)`, §2.6 | шрифт — outline (TrueType): `GetFont() && GetFont()->IsOutline()` | W9:2012-2013 |
| 8 | `)` | не поле | W9:2015-2016 |

* Позиция — относительно footprint: `pos − fp.pos`, затем поворот на `−fp.orientation` (W9:1973-1974).
  Угол — `GetTextAngle()` (абсолютный экранный угол, как исторически для `fp_text`).
* **Для `fp_text user` в 9.0/10.0 `hide` не пишется вовсе** (условие `field && …`), хотя парсер 9.0
  его принимает (P9:3509-3519). Следствие: скрытый пользовательский текст из файла 8.0 после
  пересохранения в 9.0 станет видимым — **по коду; в KiCad не проверено**. ✔ В K9/K10 у `fp_text`
  `hide` нет ни разу (2045 и 689 текстов).
* ✔ `(at x y a)` с тремя аргументами у всех полей и `fp_text` в K8 (6885 + 1377), K9 (7440 + 2045),
  K10 (2572 + 689). Порядок дочерних узлов `at unlocked layer hide uuid effects` — без нарушений.

Пример (K9):

```
	(property "Datasheet" ""
		(at 0 0 0)
		(unlocked yes)
		(layer "F.Fab")
		(hide yes)
		(uuid "58727d5f-bd35-4bad-a762-c481d20194c5")
		(effects
			(font
				(size 1.27 1.27)
				(thickness 0.15)
			)
		)
	)
	(fp_text user "${REFERENCE}"
		(at 0 0 0)
		(layer "F.Fab")
		(uuid "2f2c97a0-73e9-4a12-9e08-67733737c3c3")
		(effects (font (size 1 1) (thickness 0.15)))
	)
```

### 2.2. `effects` — `EDA_TEXT::Format`, T9:1053-1117

```
(effects
  (font [(face Q)] (size IU(высота) IU(ширина)) [(line_spacing D2S)] [(thickness IU)]
        [(bold yes)] [(italic yes)] [(color R G B D2S(a))])
  [(justify [left|right] [top|bottom] [mirror])]
  [(href Q)])
```

| Элемент | Условие | Источник |
|---|---|---|
| `(face Q(имя))` | шрифт задан и имя непусто (`NameAsToken()`) | T9:1059-1060 |
| `(size H W)` — **сначала высота, потом ширина** | всегда | T9:1063-1065 |
| `(line_spacing D2S)` | `≠ 1.0` | T9:1067-1071 |
| `(thickness IU)` | 9.0: `GetTextThickness() ≠ 0`; **10.0: `!GetAutoThickness()`** (T10:1058-1062) | T9:1073-1077 |
| `(bold yes)`, `(italic yes)` | только если истинно (`BOOL(…, true)`) | T9:1079-1083 |
| `(color r g b a)`; r,g,b = `KiROUND(c·255)` `%d`, a = `D2S` | цвет задан и нет `CTL_OMIT_COLOR` — writer PCB всегда передаёт `CTL_OMIT_COLOR` → **в `.kicad_mod` не пишется** | T9:1085-1092, W9:2008 |
| `(justify …)`: аргументы строго в порядке `left`/`right`, `top`/`bottom`, `mirror` | mirror или H-выравнивание ≠ center или V-выравнивание ≠ center | T9:1096-1111 |
| `(href Q)` | нет `CTL_OMIT_HYPERLINK` и есть ссылка — в `.kicad_mod` не пишется | T9:1113-1114 |

`hide` в `effects` в 9.0/10.0 не пишется никогда. ✔ Порядок `font justify` и `face size line_spacing
thickness bold italic color` без нарушений во всех наборах; `justify` встречен 1 раз (K10, `left bottom`).
Пример без толщины (K8, поле `"Footprint"`): `(effects (font (size 1.27 1.27)))`.

### 2.3. KiCad 8.0 — отличия (W8:1830-1895, T8:952-1021)

* `(hide yes)` пишется в теле для **любого** текста с родительским footprint (поля **и** `fp_text
  user`): `parentFP && !IsVisible()` (W8:1877-1878). Позиция — после `(layer …)`, перед `uuid`.
* `EDA_TEXT::Format` вызывается с `m_ctl | CTL_OMIT_HIDE | CTL_OMIT_COLOR | CTL_OMIT_HYPERLINK`
  (W8:1882-1888) → `(hide yes)` внутри `effects` (T8:1012-1013) в `.kicad_mod` не появляется.
* `face`: `" (face \"%s\")"` — кавычки вручную, **без экранирования** (T8:959).
* `bold`/`italic`: литералы `(bold yes)`/`(italic yes)` (T8:978-982).
* Остальное — как 9.0. ✔ K8: `(hide yes)` у 4131 из 6885 полей, `(unlocked yes)` у 4131.

### 2.4. KiCad 7.0 — `format(const FP_TEXT*)`, W7:1938-2003; `EDA_TEXT::Format` T7:811-880

```
(fp_text reference|value|user [locked] Q(текст) (at XY [ANG] [unlocked]) (layer Q [knockout]) [hide]
  (effects (font [(face "…")] (size H W) [(line_spacing D2S)] [(thickness IU)] [bold] [italic] [(color …)])
           [(justify …)] [(href Q)])
  (tstamp UUID)
  [(render_cache …)])
```

* Тип (`reference`/`value`/`user`) — голый; **`locked` голый между типом и текстом** (W7:1949-1955).
* Угол: `orient = (угол текста + ориентация footprint).Normalize720()`; пишется **только если ≠ 0**
  (W7:1960-1982). В библиотеке ориентация footprint = 0.
* `unlocked` — голый атом **внутри** `(at …)` после угла (W7:1984-1985).
* `hide` — голый атом после `(layer …)` (W7:1990-1991).
* `bold`, `italic` — голые атомы внутри `font` (T7:837-841); `color` пишется, если задан (без флага
  подавления, T7:843-850); `href` — если есть ссылка (T7:874-877).
* **`tstamp` идёт после `effects`** (W7:1995-1997), `render_cache` — после `tstamp` (W7:1999-2000).

### 2.5. KiCad 6.0 — W6:1806-1868; T6:539-591

```
(fp_text reference|value|user [locked] Q(текст) (at XY [ANG] [unlocked]) (layer Q) [hide]
  (effects (font (size H W) [(thickness IU)] [bold] [italic]) [(justify …)])
  (tstamp UUID))
```

Нет `knockout`, `face`, `line_spacing`, `color`, `href`, `render_cache`. Угол —
`NormalizeAngle360Min(угол + ориентация)`, пишется если ≠ 0 (W6:1828-1850).
✔ K6: 3918 `fp_text`; `(at x y)` — 3634, `(at x y угол)` — 284, угла `0` нет ни разу. Голых `hide`,
`unlocked`, `locked`, `bold`, `italic` в K6 нет (0 вхождений) — формы подтверждены только исходником.

Пример (K6): `(fp_text user "${REFERENCE}" (at 2.77 40.64 90) (layer "F.Fab")` …

### 2.6. `render_cache` (W9:501-526)

`(render_cache Q(отображаемый текст) ANG(угол отрисовки) (polygon (pts (xy …)…))…)` — по одному
`polygon` на контур глифа; `pts` форматируется `formatPolyPts` без родителя (абсолютные координаты).
Пишется только для outline-шрифтов. В наборах не встречается — **не проверено**.

### 2.7. `fp_text_box` (кратко)

9.0 (W9:2020-2087): `(fp_text_box Q(текст) [(locked yes)] (start XY) (end XY) | (pts …)
(margins IU IU IU IU) [(angle ANG)] (layer Q) UUID (effects …) BOOL(border) (stroke …) [(render_cache …)])`.
Угол — `угол − ориентация footprint`, `Normalize720`, пишется если ≠ 0. 10.0: после `stroke` —
`BOOL(knockout)` (W10:2394). 8.0 (W8:1898-1954): `effects` с `CTL_OMIT_HIDE`, `(margins …)` нет.
7.0 (W7:2006-2051): `(fp_text_box [locked] Q …)`, `(tstamp …)` после `(layer …)`, `stroke` только
при ширине > 0. В наборах не встречается — **не проверено**.

---

## 3. Графика `PCB_SHAPE` (`fp_line`, `fp_rect`, `fp_circle`, `fp_arc`, `fp_poly`, `fp_curve`)

### 3.1. KiCad 9.0 — W9:935-1032

Заголовок и координаты (все точки — относительно footprint: `formatInternalUnits(coord, parentFP)`,
W9:445-455):

| Фигура | Начало узла |
|---|---|
| `SEGMENT` | `(fp_line (start XY) (end XY)` |
| `RECTANGLE` | `(fp_rect (start XY) (end XY)` |
| `CIRCLE` | `(fp_circle (center XY) (end XY)` — `center` = `GetStart()`, `end` = точка на окружности |
| `ARC` | `(fp_arc (start XY) (mid XY) (end XY)` |
| `POLY` | `(fp_poly (pts …)` — контур 0; если полигон невалиден, **узел не пишется вовсе** (W9:980-983) |
| `BEZIER` | `(fp_curve (pts (xy старт) (xy c1) (xy c2) (xy конец))` |

Далее по порядку:

| № | Токен | Пишется если | Источник |
|---|---|---|---|
| 1 | `(stroke (width IU) (type T) [(color R G B A)])`; `T` ∈ `solid dash dot dash_dot dash_dot_dot default` | всегда; `color` — если задан | W9:1001, SP9:237-252, 280-300 |
| 2 | `BOOL(fill, …)` → `(fill yes)` / `(fill no)` | только `POLY`, `RECTANGLE`, `CIRCLE` | W9:1003-1009 |
| 3 | `(locked yes)` | `IsLocked()` | W9:1011-1012 |
| 4 | `(layer Q)` **или** `(layers Q Q …)` | `(layers …)` если набор слоёв фигуры > 1 (медная фигура с маской: `F.Cu` + `F.Mask`, `pcb_shape.cpp` 9.0:224-238) | W9:1014-1017 |
| 5 | `(solder_mask_margin IU)` | `HasSolderMask()` и маржин задан и слой — внешняя медь | W9:1019-1025 |
| 6 | `(net N)` | `netcode > 0` (в библиотеке цепей нет) | W9:1027-1028 |
| 7 | `UUID` | всегда | W9:1030 |

`formatPolyPts` (W9:466-498): `(pts` + для каждой вершины контура: если вершина не принадлежит
дуге — `(xy XY)`; если принадлежит дуге — один раз `(arc (start XY) (mid XY) (end XY))` и все
остальные вершины той же дуги пропускаются; затем `)`.

✔ Порядок `start/center mid end pts stroke fill locked layer(s) solder_mask_margin net uuid` — без
нарушений (K9: 74468 фигур). `stroke` всегда содержит ровно `width type` (цвет не встречен).

Пример (K9):

```
	(fp_poly
		(pts (xy 10.75 7.25) (xy -10.85 7.25) … (xy 10.75 -7.25))
		(stroke (width 0.05) (type solid))
		(fill no)
		(layer "F.CrtYd")
		(uuid "a68bd57b-c261-4a5f-bc75-15aef0b04eb5")
	)
```

### 3.2. KiCad 10.0 — отличия (W10:1001-1122)

* `fp_rect`: сразу после `(end …)` — `(radius IU)` если радиус скругления > 0 (W10:1021-1022).
* Заливка: `(fill hatch)` / `(fill reverse_hatch)` / `(fill cross_hatch)` / `(fill yes)` / `(fill no)`
  (W10:1072-1099).
* Цепь: `(net Q(имя))` при `!CTL_OMIT_PAD_NETS && netcode > 0` (W10:1117-1118) — в библиотеке нет.

### 3.3. KiCad 8.0 — отличия (W8:944-1032)

Координаты → **`(locked yes)`** (если заблокирована; **до** `stroke`, W8:1011-1012) → `stroke` →
**`(fill solid)` / `(fill none)`** (W8:1017-1022) → `(layer Q)` (всегда один слой) → `(net N)` →
`(uuid "…")`. ✔ K8: `fp_poly` `solid` 347 / `none` 2, `fp_circle none` 257, `fp_rect none` 6.

### 3.4. KiCad 7.0 — `format(const FP_SHAPE*)`, W7:1032-1117

`(fp_line [locked] (start …) (end …)` — **`locked` голый сразу после имени узла** → `stroke` →
`(fill solid|none)` (для poly/rect/circle) → `(layer Q)` → `(tstamp UUID)`. Координаты — `*0`
(относительные).

### 3.5. KiCad 6.0 — `format(const FP_SHAPE*)`, W6:939-1069

`(fp_xxx [locked] координаты… (layer Q) (width IU) [(fill solid|none)] (tstamp UUID))` —
**`layer` перед `width`**, толщина — `(width …)` вместо `stroke`. ✔ K6: 67607 фигур, порядок
`start/center mid end pts layer width fill tstamp` без нарушений; `fp_circle (fill none)` 257.

Пример (K6): `(fp_circle (center 0 0) (end 2.62 0) (layer "F.SilkS") (width 0.12) (fill none) (tstamp ff1c43e4-b972-4ccb-b251-d0bc7e0c8006))`,
`(fp_arc (start 4.81 -1.33) (mid 3.81 -0.33) (end 2.81 -1.33) (layer "F.SilkS") (width 0.12) (tstamp …))`.

Дуги start/mid/end — с версии 20211014 (H9: `LEGACY_ARC_FORMATTING 20210925` — «последние со
старым форматом дуг»); в KiCad 5 — `(fp_arc (start ЦЕНТР) (end НАЧАЛО) (angle ГРАДУСЫ) …)` (W5:906-910).

### 3.6. Формы `fill` по версиям

| Версия | Фигуры (`fp_poly/rect/circle`) | Примитивы пада (`gr_poly/rect/circle`) | ✔ |
|---|---|---|---|
| 6.0 | `(fill solid)` / `(fill none)` (W6:1055-1064) | `(fill yes)` / `(fill none)` (W6:1731-1739) | K6: shapes `none` 257; prim `yes` 6 |
| 7.0 | `(fill solid)` / `(fill none)` (W7:1101-1110) | `(fill yes)` / `(fill none)` (W7:1806-1814) | — |
| 8.0 | `(fill solid)` / `(fill none)` (W8:1017-1022) | `BOOL` → `(fill yes)` / `(fill no)` (W8:1804-1809) | K8: `solid` 347, `none` 265; prim `yes` 6 |
| 9.0 | `BOOL` → `(fill yes)` / `(fill no)` | `(fill yes)` / `(fill no)` (W9:1783-1788) | K9: `yes` 405, `no` 963; prim `yes` 352 |
| 10.0 | + `hatch`, `reverse_hatch`, `cross_hatch` | `(fill yes\|no)` по `IsSolidFill()` | K10: `yes` 460, `no` 236 |

Парсер 9.0 принимает для фигур `yes|solid` → залито, `no|none` → не залито (P9:3169-3194).
`fp_line`, `fp_arc`, `fp_curve` узла `fill` не имеют ни в одной версии.

### 3.7. Примитивы custom-пада (`primitives`), 9.0 — W9:1702-1794

Для каждого примитива: `gr_line` (`gr_vector`, если прокси-элемент), `gr_rect` (`gr_bbox` для
прокси), `gr_arc (start)(mid)(end)`, `gr_circle (center)(end)`, `gr_curve (pts …4 xy)`,
`gr_poly (pts …)` (невалидный полигон пропускается, но `(width)`/`)` всё равно пишутся — W9:1763-1790);
координаты **собственные** (без пересчёта относительно footprint); затем `(width IU)` если не
прокси; затем `(fill yes|no)` для poly/rect/circle; `)`. 10.0: у `gr_rect` `(radius IU)` при
радиусе > 0 (W10:1989-1995). ✔ Встреченные формы: `gr_poly: pts width fill`,
`gr_circle: center end width fill`, `gr_arc: start mid end width` (K9/K10).

---

## 4. Пад (`pad`)

### 4.1. KiCad 9.0 — `format(const PAD*)`, W9:1432-1932

Заголовок: `(pad Q(номер) ТИП ФОРМА` (W9:1487-1490) — номер всегда в кавычках (✔ 100 %, в т. ч.
`""` у NPTH), ТИП и ФОРМА голые:

| ТИП (W9:1457-1467) | ФОРМА для `ALL_LAYERS` (W9:1436-1453) |
|---|---|
| `thru_hole` (PTH), `smd`, `connect` (CONN), `np_thru_hole` (NPTH) | `circle`, `rect`, `oval`, `trapezoid`, `roundrect` (**и для CHAMFERED_RECT**), `custom` |

Тело по порядку:

| № | Токен | Пишется если | Источник |
|---|---|---|---|
| 1 | `(at XY [ANG])` — позиция относительно footprint | всегда; угол — только если ориентация ≠ 0 | W9:1492-1496 |
| 2 | `(size XY)` | всегда | W9:1498 |
| 3 | `(rect_delta XY)` | дельта ≠ (0,0) | W9:1500-1505 |
| 4 | `(drill [oval] [IU(x)] [IU(y)] [(offset XY)])` | `drill.x>0 ∨ drill.y>0 ∨ offset≠0 ∨ forceShapeOffsetOutput`; `oval` — сверло OBLONG; `x` — если >0; `y` — если >0 и ≠x; `(offset …)` — если смещение ≠ 0 или у слоёв падстека разные смещения | W9:1507-1539 |
| 5 | `(property pad_prop_…)` — голый: `pad_prop_bga`, `pad_prop_fiducial_glob`, `pad_prop_fiducial_loc`, `pad_prop_testpoint`, `pad_prop_heatsink`, `pad_prop_castellated`, `pad_prop_mechanical` | свойство ≠ NONE | W9:1469-1485, 1541-1543 |
| 6 | `(layers …)` — §7.2, без перечисления (`aEnumerateLayers=false`) | всегда | W9:1545 |
| 7 | `BOOL(remove_unused_layers, …)` | **только PTH, всегда** (yes/no) | W9:1547-1549 |
| 8 | `BOOL(keep_end_layers, …)` | PTH и `remove_unused_layers` = yes | W9:1551-1553 |
| 9 | `(zone_layer_connections Q…)` | PTH, remove = yes и есть плата (в библиотеке — нет) | W9:1555-1566 |
| 10 | `(roundrect_rratio D2S)` | форма ROUNDRECT или CHAMFERED_RECT | W9:1574-1579 |
| 11 | `(chamfer_ratio D2S)` `(chamfer [top_left] [top_right] [bottom_left] [bottom_right])` | CHAMFERED_RECT | W9:1582-1602 |
| 12 | `(net N Q(имя))` | `!CTL_OMIT_PAD_NETS` и цепь ≠ 0 (в библиотеке — нет) | W9:1610-1615 |
| 13 | `(pinfunction Q)`, `(pintype Q)` | `!CTL_OMIT_PAD_NETS` и непусто (в библиотеке — нет) | W9:1617-1626 |
| 14 | `(die_length IU)` | ≠ 0 | W9:1628-1632 |
| 15 | `(solder_mask_margin IU)` | has_value | W9:1634-1638 |
| 16 | `(solder_paste_margin IU)` | has_value | W9:1640-1644 |
| 17 | `(solder_paste_margin_ratio D2S)` | has_value | W9:1646-1650 |
| 18 | `(clearance IU)` | has_value | W9:1652-1656 |
| 19 | `(zone_connect N)` | ≠ INHERITED | W9:1658-1662 |
| 20 | `(thermal_bridge_width IU)` | has_value | W9:1664-1668 |
| 21 | `(thermal_bridge_angle ANG)` | угол ≠ умолчания; умолчание **45°** для `circle` и для `custom` с якорем `circle`, иначе **90°** | W9:1670-1683 |
| 22 | `(thermal_gap IU)` | has_value | W9:1685-1689 |
| 23 | `(options (clearance outline\|convexhull) (anchor rect\|circle))` затем `(primitives …)` (§3.7) | форма CUSTOM | W9:1796-1812 |
| 24 | `(teardrops …)` | параметры ≠ умолчаний | W9:1814-1815, 714-748 |
| 25 | `(tenting …)` | см. ниже | W9:1817, 1935-1953 |
| 26 | `UUID` | всегда | W9:1819 |
| 27 | `(padstack (mode …) (layer Q …)…)` | режим падстека ≠ NORMAL | W9:1898-1929 |
| 28 | `)` | | W9:1931 |

* **`tenting`** (W9:1935-1953): пишется, только если у передней или задней стороны задано
  `has_solder_mask`. Если хотя бы одна сторона = true → `(tenting [front] [back])` (голые слова,
  только для истинных сторон); иначе → `(tenting none)`.
* **`teardrops`** (W9:730-748): `(teardrops (best_length_ratio D2S) (max_length IU) (best_width_ratio D2S)
  (max_width IU) BOOL(curved_edges) (filter_ratio D2S) BOOL(enabled) BOOL(allow_two_segments)
  BOOL(prefer_zone_connections))`; `prefer_zone_connections` = `!m_TdOnPadsInZones`. Умолчания
  (`pcbnew/teardrop/teardrop_parameters.h` 9.0:50-61): max_length 1 мм, max_width 2 мм,
  best_length_ratio 0.5, best_width_ratio 1.0, filter_ratio 0.9, curved_edges false, enabled false,
  allow_two_segments true, on_pads_in_zones false.
* **`padstack`** (W9:1822-1929): `(padstack (mode front_inner_back) (layer "Inner" …) (layer "B.Cu" …))`
  или `(padstack (mode custom) (layer Q(In1.Cu…B.Cu) …)…)` — для custom перебираются медные слои
  `LAYER_RANGE(F_Cu, B_Cu, число слоёв)` кроме `F.Cu` (в библиотеке — 32 слоя). Тело слоя:
  `(shape S) (size XY) [(rect_delta XY)] [(offset XY)] [roundrect_rratio/chamfer…]
  [custom: (options (anchor …)) (primitives …)] [(thermal_bridge_angle ANG)] [(thermal_gap IU)]
  [(thermal_bridge_width IU)] [(clearance IU)] [(zone_connect N)]` — порядок **отличается** от
  основного тела (gap раньше width).
* В .kicad_mod нет `locked` у пада: с 8.0 блокировка пада — настройка сессии; парсер читает и
  отбрасывает (P9:5506-5508).

✔ K9: 22482 пада, порядок без нарушений; `(remove_unused_layers no)` у всех 8162 `thru_hole`
(`keep_end_layers` нет, т.к. везде `no`); `(at x y 0)` — ни разу (2112 падов с углом, все ≠ 0);
`(drill (offset …))` без диаметра — 4 SMD-пада; `thermal_bridge_angle 45` — 306 (у не-круглых падов).

Примеры (K9):

```
	(pad "1" thru_hole rect
		(at 0 0)
		(size 1.6 1.6)
		(drill 0.8)
		(layers "*.Cu" "*.Mask")
		(remove_unused_layers no)
		(uuid "58dc6923-37f6-4694-bb02-342c1b108456")
	)
	(pad "1" smd roundrect
		(at -2.7 0)
		(size 3.5 1.6)
		(layers "F.Cu" "F.Mask" "F.Paste")
		(roundrect_rratio 0.15625)
		(uuid "397155f9-c4a6-4b61-85f7-7a7aa26be5de")
	)
```

### 4.2. KiCad 10.0 — отличия

| Место | Изменение | Источник |
|---|---|---|
| `property` | добавлено `pad_prop_pressfit` | W10:1684 |
| после `drill` | `(backdrill (size IU) (layers Q Q))` при размере > 0; `(tertiary_drill (size IU) (layers Q Q))`; `(front_post_machining counterbore\|countersink [(size IU)] [(depth IU)] [(angle D2S(угол/10))])`, `(back_post_machining …)` — если режим задан и ≠ NOT_POST_MACHINED | W10:1745-1785 |
| `net` | `(net Q(имя))` — без номера; при `netcode > 0` (в библиотеке нет) | W10:1857-1858 |
| после `die_length` | `(die_delay IU_времени)` при ≠ 0 | W10:1877-1881 |
| `tenting` | `(tenting (front yes\|no\|none) (back yes\|no\|none))` — `FormatOptBool`, если хоть одна сторона задана | W10:2071-2082, U10:40-46 |
| `primitives` | `gr_rect` с `(radius IU)`; `fill` по `IsSolidFill()` | W10:1989-1995, 2042 |

### 4.3. KiCad 8.0 — отличия (W8:1450-1827)

* Одна форма (нет падстеков, нет `padstack`, `tenting`), нет `forceShapeOffsetOutput` (W8:1517-1538).
* `remove_unused_layers`/`keep_end_layers` — как 9.0 (`BOOL`, W8:1546-1567). ✔ K8: `(remove_unused_layers no)`
  у всех 10290 `thru_hole`.
* Маржины, зазор, `thermal_bridge_width`, `thermal_gap` — при **`≠ 0`** (W8:1627-1687).
* `teardrops` (W8:765-784): `(teardrops (best_length_ratio D2S) (max_length IU) (best_width_ratio D2S)
  (max_width IU) (curve_points N) (filter_ratio D2S) BOOL(enabled) BOOL(allow_two_segments)
  BOOL(prefer_zone_connections))`.
* `(uuid "…")` последним (W8:1825).

### 4.4. KiCad 7.0 — отличия (W7:1459-1826)

* `(pad Q ТИП ФОРМА [locked]` — **голый `locked` после формы** (W7:1514-1515).
* PTH: **только если включено** — `(remove_unused_layers)` (пустой список!), затем при keep —
  `(keep_end_layers)`; `(zone_layer_connections …)` — с платой (W7:1558-1580). При выключенном — ничего.
* `roundrect_rratio`, `chamfer…`, `net`, `pinfunction`, `pintype`, `die_length`, маржины (≠ 0),
  `zone_connect`, `(thermal_bridge_width IU)` (≠ 0), `thermal_bridge_angle` (та же логика умолчания),
  `(thermal_gap IU)` (≠ 0), `options`/`primitives` (`fill yes|none`), `(tstamp UUID)` последним.
  Нет `teardrops`.

### 4.5. KiCad 6.0 — отличия (W6:1376-1751)

* `[locked]` голый после формы (W6:1430-1431); `remove_unused_layers`/`keep_end_layers` — как 7.0
  (W6:1474-1483), без `zone_layer_connections`.
* Нет `thermal_bridge_angle`; ширина спицы — **`(thermal_width IU)`** (W6:1579-1583), `(thermal_gap IU)`.
* `roundrect_rratio`/`chamfer_ratio` через `Double2Str`. `(tstamp UUID)` последним (W6:1748).
* ✔ K6: 22357 падов, порядок без нарушений; `remove_unused_layers` не встречается ни разу
  (у всех 9580 `thru_hole` выключено).

Пример (K6): `(pad "1" smd roundrect (at -4.6625 -4.25) (size 1.475 0.3) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25) (tstamp 4a68cd22-6121-41ba-8d31-634519e89e53))`,
`(pad "1" thru_hole rect (at 0 0) (size 1.6 1.6) (drill 0.8) (layers *.Cu *.Mask) (tstamp 6eb219cb-…))`.

### 4.6. Сводка форм токенов пада

| Токен | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 |
|---|---|---|---|---|---|
| `locked` | голый после формы | голый | не пишется | не пишется | не пишется |
| `remove_unused_layers` | `(remove_unused_layers)` если вкл. | то же | `(… yes\|no)` всегда у PTH | то же | то же |
| `keep_end_layers` | `(keep_end_layers)` если вкл. | то же | `(… yes\|no)` если remove | то же | то же |
| ширина спицы | `thermal_width` | `thermal_bridge_width` | `thermal_bridge_width` | `thermal_bridge_width` | то же |
| `thermal_bridge_angle` | — | есть | есть | есть | есть |
| `teardrops` | — | — | с `curve_points N` | с `curved_edges yes\|no` | как 9.0 |
| `tenting` | — | — | — | `front`/`back`/`none` голые | `(front yes\|no\|none) (back …)` |
| `padstack` | — | — | — | есть | есть |
| условие маржинов | ≠ 0 | ≠ 0 | ≠ 0 | has_value | has_value |
| id | `(tstamp UUID)` | `(tstamp UUID)` | `(uuid "…")` | `(uuid "…")` | `(uuid "…")` |
| `net` (не в библиотеке) | `(net N Q)` | `(net N Q)` | `(net N Q)` | `(net N Q)` | `(net Q)` |

---

## 5. 3D-модель (`model`)

### 5.1. KiCad 9.0 — W9:1305-1339

```
(model Q(путь) [(hide yes)] [(opacity 0.NNNN)]
  (offset (xyz D2S D2S D2S))
  (scale (xyz D2S D2S D2S))
  (rotate (xyz D2S D2S D2S)))
```

| Токен | Условие | Источник |
|---|---|---|
| весь узел | имя файла непусто; модели — в исходном порядке списка | W9:1308-1312 |
| `(hide yes)` (`BOOL(hide, !m_Show)`) | модель скрыта | W9:1314-1315 |
| `(opacity %0.4f)` — 4 знака после точки, напр. `0.5000` | `m_Opacity ≠ 1.0` | W9:1317-1318 |
| `offset`, `scale`, `rotate` — **всегда все три**, каждая с `(xyz x y z)`; offset в мм, rotate в градусах | всегда | W9:1320-1333 |

Значения — `D2S`, поэтому возможен текст `-0` (для `-0.0`) ✔ (K10: 6 токенов `-0` в `xyz` в 2 файлах).
✔ K9: 1693 модели, из них 1 с `(hide yes)`; порядок `hide offset scale rotate`. 8.0 (W8:1319-1354) — то же.
10.0 — то же (`opacity` через `fmt::format("{:.4f}")`, W10:1522-1523).

### 5.2. KiCad 7.0 / 6.0

`(model Q(путь)[ hide]` — **голый `hide` сразу после пути** (W7:1341-1343, W6:1258-1260), далее
`opacity`, `offset`, `scale`, `rotate` как в 9.0 (`Double2Str` в 6.0). ✔ K6: 1306 моделей
`offset scale rotate`.

### 5.3. `at` вместо `offset` (KiCad 5 и старше)

KiCad 5.1 пишет `(at (xyz …))`, если смещение нулевое, иначе `(offset (xyz …))` (W5:1109-1133,
комментарий «4.0.x wrote "at" which was actually in inches»). ✔ `kfp/v6.0.0` (формат KiCad 5):
`(at (xyz` — 1300, `(offset (xyz` — 3. Парсер 9.0 читает `(at (xyz x y z))` как **дюймы**:
`значение × 25.4f` (P9:721-736, case `T_at`), где `25.4f` — константа `float` (= 25.399999618530273); поэтому
`(at (xyz 0.1 0 0))` после пересохранения даст `(offset (xyz 2.539999962 0 0))` (вычислено портом
`D2S`; в KiCad **не проверено**). Нули не меняются.

---

## 6. Зоны и группы внутри footprint (кратко — `kicadfp` их только сохраняет)

### 6.1. `zone`, KiCad 9.0 — W9:2443-2661

```
(zone (net N) (net_name Q) [(locked yes)] (layer Q) | (layers …) UUID [(name Q)]
  (hatch none|edge|full IU) [(priority N)] [(attr (teardrop (type padvia|track_end)))]
  (connect_pads [thru_hole_only|yes|no] (clearance IU))
  (min_thickness IU) (filled_areas_thickness no)
  [(keepout (tracks allowed|not_allowed) (vias …) (pads …) (copperpour …) (footprints …))
   (placement BOOL(enabled) [(sheetname Q) | (component_class Q)])]
  (fill [yes] [(mode hatch)] (thermal_gap IU) (thermal_bridge_width IU)
        [(smoothing chamfer|fillet) [(radius IU)]]
        [(island_removal_mode N) (island_area_min IU)]
        [(hatch_thickness IU) (hatch_gap IU) (hatch_orientation D2S)
         [(hatch_smoothing_level N) (hatch_smoothing_value D2S)]
         (hatch_border_algorithm hatch_thickness|min_thickness) (hatch_min_hole_area D2S)])
  (polygon (pts …))…
  (filled_polygon (layer Q) [(island)] (pts …))…)
```

* Для rule area и некопперных зон `(net 0) (net_name "")` (W9:2450-2454).
* Слои: если > 1 — `formatLayers(layers, enumerate = IsOnCopperLayer(), isZone = true)`: у медных зон
  все слои перечисляются поимённо (без `*.Cu`), у немедных возможны маски-шаблоны, пара F/B меди →
  `F&B.Cu` (W9:2466-2469).
* `island_removal_mode`/`island_area_min` — если режим ≠ ALWAYS (W9:2600-2605).
* Контур — `formatPolyPts(chain)` **без** пересчёта относительно footprint (W9:2632-2636) — в библиотеке
  footprint в (0,0) и 0°, поэтому совпадает с относительными.
* ✔ K9: 1 зона — `net net_name layers uuid hatch connect_pads min_thickness filled_areas_thickness
  keepout placement fill polygon`.

10.0 (W10:2868-…): `(zone` без `net`/`net_name` в библиотеке (`(net Q)` только для медной зоны с
цепью и без `CTL_OMIT_PAD_NETS`, W10:2872-2876); UUID и имя не пишутся для teardrop-зон;
`filled_areas_thickness` нет; `(island_removal_mode N)` всегда, `(island_area_min …)` только для
режима AREA (W10:3026-3033); у `filled_polygon` — `(island yes)` (W10:3087). ✔ K10: 10 зон, формы
`layer|layers uuid [name] hatch connect_pads min_thickness keepout placement fill polygon`; у медной
зоны на всех слоях слои перечислены `"F.Cu" "B.Cu" "In1.Cu" … "In30.Cu"` (порядок ID 9.0+).

8.0 (W8:2203-…) — как 9.0. 6.0/7.0: `(zone [locked] (net N) (net_name Q) (layer …) (tstamp UUID) [(name Q)] (hatch …) …`
(W6:1971-1996, W7:2172-2200) — `locked` голый.

### 6.2. `group`

| Версия | Форма | Источник |
|---|---|---|
| 9.0 | `(group Q(имя) UUID [(locked yes)] (members Q(uuid) Q(uuid) …))` — члены: строки UUID, `wxArrayString::Sort()` (по возрастанию); пустые группы не пишутся | W9:2143-2170 |
| 10.0 | + `(lib_id "…")` после `locked`, если есть связь с design block; группа не пишется, если нет валидных членов | W10:2459-2510 |
| 8.0 | как 9.0 (кавычки вручную `"\"%s\""`) | W8:1957-1984 |
| 6.0/7.0 | `(group Q(имя)[ locked] (id UUID) (members UUID UUID …))` — `locked` и UUID голые | W6:1778-1803, W7:1910-1935 |

✔ K9: 4 группы `(group "" (uuid …) (members …))`.

---

## 7. Слои: `formatLayer` и `formatLayers`

Имена слоёв — `LSET::Name()` (канонические английские имена; таблицы по версиям —
`docs/dev/layers.json`, ключи `canonical`, `ids`, `wildcards`, `writer_individual_order`).

### 7.1. Один слой — `(layer …)`

| Версия | Форма | Источник |
|---|---|---|
| 5.1 | `(layer ИМЯ)` — `Quotew` версии 5.1 кавычит только при необходимости (§9.1) → на практике голое | W5:455-466 |
| 6.0 | `(layer Q)` — всегда в кавычках | W6:466-471 |
| 7.0, 8.0 | `(layer Q[ knockout])` | W7:421-426, W8:461-466 |
| 9.0, 10.0 | `"(layer %s %s)"` → после Prettify `(layer Q)` / `(layer Q knockout)` | W9:458-463, W10:481-486 |

`knockout` передаётся только из `format(PCB_TEXT)` (тексты, поля). ✔ Корневой `(layer "F.Cu")` в
кавычках: K6…K10 — 100 %; в KiCad 5 (`kfp/v6.0.0`) — голый.

### 7.2. Набор слоёв — `(layers …)`, KiCad 9.0 (W9:1345-1429)

Вход: маска `M`, `enumerate` (перечислять поимённо), `isZone`.

1. `cu_board = AllCuMask(плата ? число медных слоёв платы : MAX_CU_LAYERS)` — в библиотеке все 32
   медных слоя (W9:1356).
2. Если `!enumerate`:
   1. если `M ∩ cu_board == cu_board` → `"*.Cu"`, и из `M` удаляются **все** медные биты (W9:1363-1371);
   2. иначе если `M ∩ cu_board == {F.Cu, B.Cu}` → `isZone ? "F&B.Cu" : "*.Cu"`, из `M` удаляются F.Cu и
      B.Cu (W9:1372-1380). **До 9.0.5 включительно — всегда `"F&B.Cu"`** (§7.4);
   3. затем пары, строго в этом порядке, каждая — только если в `M` оба слоя пары, с удалением обоих:
      `{B.Adhes,F.Adhes}` → `"*.Adhes"`, `{B.Paste,F.Paste}` → `"*.Paste"`, `{B.SilkS,F.SilkS}` → `"*.SilkS"`,
      `{B.Mask,F.Mask}` → `"*.Mask"`, `{B.CrtYd,F.CrtYd}` → `"*.CrtYd"`, `{B.Fab,F.Fab}` → `"*.Fab"`
      (W9:1382-1416).
3. Оставшиеся слои — поимённо, по **возрастанию числового `PCB_LAYER_ID` своей версии** (W9:1422-1426).
   9.0+: `F.Cu`(0) `F.Mask`(1) `B.Cu`(2) `B.Mask`(3) `In1.Cu`(4) `F.SilkS`(5) `In2.Cu`(6) `B.SilkS`(7) …
   `F.Paste`(13) … `F.CrtYd`(31) … `F.Fab`(35) … `User.1`(39) …
4. Всё — через `Quotew` (в кавычках). Итог: `(layers T1 T2 …)` (W9:1428).

`enumerate = true` (медные зоны) — шаблоны не используются вовсе, только п. 3.

Следствие п. 2.2 в 9.0.6+/10.0: пад только на `F.Cu`+`B.Cu` пишется как `"*.Cu"`, а парсер читает
`*.Cu` как все медные слои — набор слоёв меняется при круговом цикле. ✔ Один и тот же NPTH-пад
`MountingHole.pretty/ToolingHole_1.152mm`: в K9 `(layers "F&B.Cu" "*.Mask")`, в K10
`(layers "*.Cu" "*.Mask")`.

### 7.3. Отличия других версий

| Версия | Отличие | Источник |
|---|---|---|
| 8.0 | пара F/B меди → всегда `"F&B.Cu"`; `cu_all` объявлен `static const` и инициализируется **один раз за процесс** числом слоёв первой платы (или 32 без платы) — **поведение в сессии не проверено**; индивидуальные слои — по старой нумерации: `F.Cu`0, `In1..In30` 1..30, `B.Cu`31, `B.Adhes`32, `F.Adhes`33, `B.Paste`34, `F.Paste`35, `B.SilkS`36, `F.SilkS`37, `B.Mask`38, `F.Mask`39, `Dwgs.User`40 … `F.Fab`49, `User.1..9` 50..58 | W8:1360-1447 |
| 7.0 | `cu_all = AllCuMask()` (32), `"F&B.Cu"`, всё в кавычках, нумерация как 8.0 | W7:1373-1456 |
| 6.0 | **шаблоны голые** (`*.Cu`, `F&B.Cu`, `*.Mask`, …), отдельные слои — в кавычках: `(layers *.Cu *.Mask)`, `(layers "F.Cu" "F.Paste" "F.Mask")` | W6:1290-1373 |
| 5.1 | всё голое | W5:1153-1244 |

Типичные наборы пада «как записано» ✔:

| Пад | 6.0 (K6) | 8.0 (K8) | 9.0 (K9) | 10.0 (K10) |
|---|---|---|---|---|
| SMD | `"F.Cu" "F.Paste" "F.Mask"` ×12098 | то же ×13365 | `"F.Cu" "F.Mask" "F.Paste"` ×11810 | то же ×17987 |
| THT | `*.Cu *.Mask` ×9055 | `"*.Cu" "*.Mask"` ×9655 | то же ×7278 | то же ×1020 |
| paste-апертура | `"F.Paste"` ×499 | ×582 | ×1605 | ×1604 |
| connect | — | — | `"F.Cu" "F.Mask"` ×72 | — |

✔ Во всех 91520 падах pcbnew (K6+K8+K9+K10) шаблоны идут первыми в порядке п. 2, отдельные слои — по
возрастанию ID соответствующей версии. В K8+ все имена в кавычках; в K6 — 9581 набор с голыми
шаблонами, 12776 полностью в кавычках.

### 7.4. Изменения внутри ветки 9.0 (без смены версии формата)

| Тег | `F&B.Cu` → `*.Cu` для не-зон | `forceShapeOffsetOutput` в `drill` |
|---|---|---|
| 9.0.0, 9.0.4, 9.0.5 | нет (всегда `F&B.Cu`) | нет |
| 9.0.6 | да | нет |
| 9.0.7, голова 9.0 | да | да |

(поиск `aIsZone` и `forceShapeOffsetOutput` в `tags/9.0.x-pcb_io_kicad_sexpr.cpp`). Файлы с одной и той
же `(version 20241229)` могут отличаться этим.

### 7.5. Прочие списки слоёв

* `private_layers` (9.0): имена `Q`, по возрастанию ID (W9:1249-1253). 7.0/8.0: `"…"` вручную.
* `zone_layer_connections`, `padstack … (layer Q …)`, `filled_polygon (layer Q)`, `backdrill (layers Q Q)`,
  `stackup (layer Q)` — по одному имени в кавычках.

---

## 8. Форматирование чисел

### 8.1. `FormatInternalUnits` — координаты и длины (EU9:170-200; идентично EU7:142-172, EU8:169-199, EU10:194-225; 6.0 — BU6:480-512 через `snprintf`)

Внутренние единицы — целые нанометры (`pcbIUScale.IU_PER_MM = 1e6`). Алгоритм:

```python
def format_internal_units(iu: int) -> str:
    mm = iu / 1e6
    if mm != 0.0 and abs(mm) <= 0.0001:
        s = ("%.10f" % mm).rstrip("0")        # 1 нм -> "0.0000010000" -> "0.000001"
        return s[:-1] if s.endswith(".") else s
    return "%.10g" % mm                        # без хвостовых нулей, целые без точки
```

`fmt::format("{:.10g}")` (7.0+) и `snprintf("%.10g")` (6.0) дают тот же текст, что Python `"%.10g"`
✔ (§13). Экспонента невозможна: `|int32| ≤ 2147.483647 мм`. `-0` невозможен (целое 0 → `"0"`).

При чтении парсер переводит мм в нм: `KiROUND(clamp(parseDouble() * 1e6))` (P9:195-209), где
`KiROUND(v) = (int)(v < 0 ? v - 0.5 : v + 0.5)` — округление половины **от нуля**
(`libs/kimath/include/math_util.h` 9.0:100-103), а не банковское `round()` Python:

```python
def kiround(v: float) -> int:
    return int(v - 0.5) if v < 0 else int(v + 0.5)
```

### 8.2. `FormatDouble2Str` — безразмерные и 3D (SU9:1372-1399; SU7:1108-1135, SU8:1367-1394, SU10:1445-1472; 6.0 `Double2Str` SU6:1065-1092)

```python
def format_double2str(v: float) -> str:
    if v != 0.0 and abs(v) <= 0.0001:
        s = ("%.16f" % v).rstrip("0")
        return s[:-1] if s.endswith(".") else s
    return "%.10g" % v                         # для -0.0 даёт "-0"
```

### 8.3. `FormatAngle` — углы (EU9:162-167; EU7:134-139, EU8:161-166, EU10:186-191)

`"%.10g" % градусы` (`EDA_ANGLE::AsDegrees()`). 6.0 (BU6:515-522): угол хранится в десятых
градуса, выводится `"%.10g" % (decideg / 10.0)`. Для `-0.0` — `"-0"` (в наборах не встречено).

### 8.4. Прочие форматы

| Форма | Где | Источник |
|---|---|---|
| `%d` | `version`, `zone_connect`, `priority`, `curve_points` (8.0), `island_removal_mode`, `(net N …)`, `color r g b`, `span`, `column_count`, `autoplace_cost*` | W9 passim |
| `%0.4f` | `opacity` модели (`0.5` → `0.5000`) | W9:1318; W10:1523 (`{:.4f}`) |
| `%g` | `scale` изображения (`image`) | W9:1052 |
| `%lX` | `tedit` (6.0) | W6:1124 |

### 8.5. Какой форматтер у какого токена

| Форматтер | Токены |
|---|---|
| `IU` | все координаты (`at`, `start`, `mid`, `end`, `center`, `xy`, `offset`), `size`, `rect_delta`, `drill`, `width`/`stroke width`, `thickness`, `solder_mask_margin`, `solder_paste_margin`, `clearance`, `thermal_*` (длины), `die_length`, `margins`, `radius`, зоны (`min_thickness`, `hatch` шаг, `thermal_gap`, …), `teardrops max_length/max_width` |
| `D2S` | `roundrect_rratio`, `chamfer_ratio`, `solder_paste_margin_ratio`/`solder_paste_ratio`, `line_spacing`, `xyz` модели, коэффициенты `teardrops`, альфа в `color`, `hatch_orientation`, `hatch_smoothing_value`, `hatch_min_hole_area`, `angle` post-machining (10.0) |
| `ANG` | углы в `(at …)` (footprint, пад, текст), `thermal_bridge_angle`, `angle` текстбокса, угол `render_cache` |

### 8.6. Примеры (вычислены портом; IU = `kiround(мм·1e6)`)

| Вход (мм) | IU | `IU(...)` | `D2S(мм)` |
|---|---|---|---|
| 0.15 | 150000 | `0.15` | `0.15` |
| 1.6 | 1600000 | `1.6` | `1.6` |
| 3.81 | 3810000 | `3.81` | `3.81` |
| 0.000001 | 1 | `0.000001` | `0.000001` |
| 12.3456789 | 12345679 | `12.345679` | `12.3456789` |
| -0.05 | -50000 | `-0.05` | `-0.05` |
| 1e-5 | 10 | `0.00001` | `0.00001` |
| 100 | 100000000 | `100` | `100` |
| 0.1+0.2 (=0.30000000000000004) | 300000 | `0.3` | `0.3` |
| ±0.0000005 | ±1 | `±0.000001` | `±0.0000005` |
| 2147.483647 | 2147483647 | `2147.483647` | `2147.483647` |

Углы: `0`→`0`, `90`→`90`, `-90`→`-90`, `45.5`→`45.5`, `359.9999999999`→`360`, `1/3`→`0.3333333333`.
Реальные примеры ✔: `(roundrect_rratio 0.1666666667)`, `(roundrect_rratio 0.2083333333)`,
`(roundrect_rratio 0.05494505495)`.

---

## 9. Строки: кавычки, экранирование, лексер

### 9.1. `OUTPUTFORMATTER::Quotes` / `Quotew` (RIO 9.0:509-556)

* `Quotew(wxString)` = `Quotes(UTF-8 байты)`.
* Результат **всегда** в двойных кавычках (6.0…10.0; тексты функций совпадают дословно — проверено
  `diff`).
* Экранируются **ровно 4 символа**: `\n` → `\n` (обратная косая + `n`), `\r` → `\r`, `\` → `\\`,
  `"` → `\"`. Всё прочее, включая `\t`, прочие управляющие и не-ASCII байты UTF-8, — как есть.

```python
def quotes(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'
```

(порядок замен важен: сначала `\`). ✔ Пример K8/K9: `(descr "8-Lead, 300\\\" Wide, …")` — значение
`300\"` (обратная косая + кавычка), `(descr "… 3/8\" x 3/8\" …")`.

**Где кавычки ставятся вручную, без экранирования:** 7.0/8.0 `face` (`"\"%s\""`, T7:818, T8:959);
7.0/8.0 `private_layers`; 7.0/8.0 `net_tie_pad_groups` (`"` → `{dblquote}`); 8.0 `generator_version`;
8.0 `FormatUuid` и члены группы; 10.0 `(lib_id "%s")` группы; литерал `(generator "pcbnew")`.
**Голые (никогда не в кавычках):** ключевые слова, числа, `tstamp`/`id`/члены групп/`tedit` в 6.0/7.0,
`generator pcbnew` в 6.0/7.0, `ki_fp_filters`, `pad_prop_*`, тип/форма пада, флаги `attr`, шаблоны
слоёв в 6.0.

**KiCad 5.1** (RIO 5.1:433-479): кавычит, только если строка пустая, начинается с `#` или `"`,
или содержит пробел, `\t`, `(`, `)`, `\n`, `\r`; иначе возвращает как есть.

### 9.2. Лексер `DSNLEXER` (LEX 9.0:452-833; 6.0 — та же логика без `|`; 10.0 — та же логика, дополнительно запоминает разделители `curSeparator`)

| Правило | Описание | Источник |
|---|---|---|
| пробельные | байты `' '`, `\n`, `\r`, `\t`, `\0`; байты ≥ 0x80 — **не** пробельные | LEX:452-470 |
| разделители | пробельные, `(`, `)`, и `\|`, если лексер «знает черту» | LEX:480-483 |
| `\|` | парсер PCB включает `SetKnowsBar(version >= 20240706)` (P9:1423, 4477) — в файлах 9.0+ `\|` разрывает голый токен (используется во встроенных файлах) | |
| комментарий | строка, чей **первый непробельный** символ — `#`; целиком до конца строки; после других токенов на той же строке не распознаётся | LEX:571-599 |
| строка | начинается с `"` в позиции начала токена; читается до неэкранированной `"` **в пределах текущей строки файла** (буфер строки); сырой перевод строки внутри кавычек → ошибка «Un-terminated delimited string» | LEX:637-733 |
| голый токен | максимальная последовательность неразделителей (может содержать `"` не в начале, напр. `a"b`) | LEX:805-810 |
| число | голый токен, целиком соответствующий `[+-]? D* (\. D*)? ([eE][+-]? D+)?` с хотя бы одной цифрой в мантиссе (`.5`, `5.`, `+1`, `1e5` — числа; `1e`, `-`, `.` — нет) | LEX:495-542, 812-816 |
| прочее | ключевое слово (таблица `pcb.keywords`) или `DSN_SYMBOL` | LEX:824 |

Экранирование внутри строки (LEX:652-715):

| Последовательность | Результат |
|---|---|
| `\"` `\\` | `"` `\` |
| `\a` `\b` `\f` `\n` `\r` `\t` `\v` | 0x07 0x08 0x0C 0x0A 0x0D 0x09 0x0B |
| `\x` + 1–2 hex-цифры | байт; `\x` без hex-цифр → символ `x` |
| `\` + 1–3 восьмеричные цифры | байт (`\101` → `A`) |
| `\` + любой другой символ | сам `\`; следующий символ читается обычным образом (`\z` → `\z`, `\8` → `\8`) |

Числа при разборе: `parseDouble` (`std::from_chars`/`strtod`, LEX:859-…), мм → нм через `KiROUND`.

✔ Порт «разэкранирование + `quotes`» воспроизводит байт-в-байт все строки в кавычках файлов pcbnew:
K6 141368, K8 288902, K9 296867, K10 142150 строк.

---

## 10. Булевы значения и флаги

* 8.0+: `KICAD_FORMAT::FormatBool` → `(ключ yes)` / `(ключ no)` (U9:35-38; U8:29-33). 10.0: плюс
  `FormatOptBool` → `(ключ yes|no|none)` (U10:40-46).
* 6.0/7.0: голые флаги (присутствие = истина) или пустые списки `(remove_unused_layers)`.
* Многие флаги 8.0+ пишутся **только при истине**, поэтому `(x no)` для них не встречается:
  `locked`, `placed`, `hide`, `unlocked`, `bold`, `italic`.
* **Всегда** пишутся (yes/no): `remove_unused_layers` (у PTH), `fill` у фигур 9.0+, `embedded_fonts`
  (9.0+), `duplicate_pad_numbers_are_jumpers` (10.0), булевы внутри `teardrops`, `border` текстбокса,
  `placement (enabled …)` зоны.
* Парсер 9.0: `parseMaybeAbsentBool(default)` (P9:241-262) принимает голое `hide` → истина, `(hide)` →
  умолчание, `(hide yes|true)`, `(hide no|false)`; `parseBool()` (P9:223-235) — только `yes|no`.
  `FIRST_NORMALIZED_VERISON 20230924` (H9:182) — с этой версии булевы нормализованы.

| Токен | 5.1 | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 |
|---|---|---|---|---|---|---|
| footprint `locked`/`placed` | голые после имени | голые после `generator` | то же | `(locked yes)`/`(placed yes)` | то же | то же |
| скрытие текста | голый `hide` после `(layer)` | то же | то же | `(hide yes)` после `(layer)` (поля и `fp_text`) | `(hide yes)` **только у полей** | то же |
| `unlocked` (не держать вертикально) | голый в `(at …)` | то же | то же | `(unlocked yes)` после `(at)` | то же | то же |
| `bold`, `italic` | голые в `font` | то же | то же | `(bold yes)`, `(italic yes)` | то же | то же |
| `knockout` | — | — | голый в `(layer …)` | то же | то же | то же |
| `locked` у фигуры | — | голый после имени узла | то же | `(locked yes)` **до** `stroke` | `(locked yes)` **после** `fill` | то же |
| `fill` у фигуры | — | `solid`/`none` | то же | то же | `yes`/`no` | + `hatch`… |
| `fill` у примитива пада | — | `yes`/`none` | то же | `yes`/`no` | то же | то же |
| `locked` у текста | — | голый после типа | то же | `(locked yes)` после текста | то же | то же |
| `locked` у пада | не пишется (W5) | голый после формы | то же | не пишется | не пишется | не пишется |
| `remove_unused_layers` | — | `(remove_unused_layers)` если вкл. | то же | `(… yes\|no)` у PTH всегда | то же | то же |
| `keep_end_layers` | — | `(keep_end_layers)` если вкл. | то же | `(… yes\|no)` если remove | то же | то же |
| `hide` модели | — | голый после пути | то же | `(hide yes)` | то же | то же |
| `locked` у группы | — | голый после имени | то же | `(locked yes)` после `uuid` | то же | то же |
| `locked` у зоны | не пишется (W5) | голый после `zone` | то же | `(locked yes)` | то же | то же |
| `island` у `filled_polygon` | — | `(island)` (W6:2202) | `(island)` (W7:2377) | `(island)` (W8:2411) | `(island)` (W9:2651) | `(island yes)` (W10:3087) |
| `tenting` | — | — | — | — | `(tenting front back)`/`(tenting none)` | `(tenting (front …) (back …))` |
| teardrop кривизна | — | — | — | `(curve_points N)` | `(curved_edges yes\|no)` | то же |

✔ Подтверждено на файлах: 6.0 — `(fill none)` 257, `(fill yes)` у примитивов 6, отсутствие
`remove_unused_layers`; 8.0 — `(hide yes)` 4131, `(unlocked yes)` 4131, `(remove_unused_layers no)`
10290, `(fill solid|none)`; 9.0 — `(hide yes)` 3721, `(unlocked yes)` 3727, `(remove_unused_layers no)`
8162, `(fill yes|no)`, `(embedded_fonts no)` 1860/1860, `(hide yes)` у модели 1; 10.0 —
`(duplicate_pad_numbers_are_jumpers no)` 643/643. Голые формы 6.0/7.0 (`hide`, `unlocked`, `locked`,
`bold`, `italic`, `knockout`) в наборах не встречаются — только по исходнику.

---

## 11. Версии формата и что пишет KiCad

### 11.1. Сводка

| `(version …)` | KiCad | Ключевые признаки вывода writer'а в `.kicad_mod` | ✔ |
|---|---|---|---|
| — (нет `version`) | 5.1 | корень `module`, всё голое, `tedit`, `fp_text reference/value/user`, `fp_arc (start ц.) (end) (angle)`, `(width …)`, без uuid/tstamp у элементов, без сортировки, модель `at`/`offset` (§12) | `kfp/v6.0.0` |
| 20211014 | 6.0 | `footprint`, `(generator pcbnew)`, `tedit`, `tstamp` у всех элементов (голый), `fp_text`, дуги start/mid/end, `(layer "…")`, шаблоны слоёв голые, `(width …)`, `(fill solid\|none)`, голые флаги | K6 |
| 20221018 | 7.0 | нет `tedit`; `(stroke (width)(type))`; `knockout`; шаблоны слоёв в кавычках; `thermal_bridge_width/angle`; `private_layers`, `net_tie_pad_groups`, `fp_text_box`; голые флаги | только исходник |
| 20240108 | 8.0 | `(generator "pcbnew") (generator_version "8.0")`; Reference/Value/… — `property` с телом; `(uuid "…")`; `BOOL`-формы (`(hide yes)`, `(locked yes)`, `(remove_unused_layers no)`); `fill solid\|none` у фигур; `teardrops (curve_points)`; `sheetname/sheetfile`, `ki_fp_filters`, `dnp` | K8 |
| 20241229 | 9.0 | `(fill yes\|no)`; `locked` фигуры после `fill`; маржины optional (0 пишется), `solder_paste_margin_ratio` у footprint; новая нумерация слоёв (порядок `"F.Cu" "F.Mask" "F.Paste"`); `embedded_fonts` всегда; `tenting`, `padstack`, `component_classes`; `(layers …)` у фигур с маской; `hide` только у полей; `curved_edges` | K9 |
| 20260206 | 10.0 | `duplicate_pad_numbers_are_jumpers` всегда; `units`, `stackup`, `jumper_pad_groups`, `point`, `variant`; `(net "имя")` без номера; `fill hatch…`; `fp_rect (radius)`; `tenting (front …)(back …)`; `backdrill`, post-machining, `die_delay`, `pad_prop_pressfit`; `island yes`; зоны без `net/net_name/filled_areas_thickness` | K10 |
| 20260901 | master (11.0-dev) | вне объёма; по Wm: `(transform (translate …) (rotate …) (scale …))` вместо `(at …)`, флаг `exclude_from_sim` в `attr`, экструдированные модели `(model (type extruded) …)`; **не проверено** | — |

### 11.2. Вехи истории, относящиеся к `.kicad_mod` (комментарии в H9:67-175, H10:183-204)

| Версия | Изменение | Строка |
|---|---|---|
| 20201115 | `module` → `footprint`, новый синтаксис `fill` | H9:110 |
| 20201116 | `version` и `generator` в файлах footprint | H9:111 |
| 20210108 | блокировка перенесена с footprint на пады | H9:113 |
| 20210424 | `locked` без скобок (голый) | H9:116 |
| 20210925 | `locked` у `fp_text`; последняя версия со старым форматом дуг (`LEGACY_ARC_FORMATTING`) | H9:121, 179 |
| 20211014 | дуги `start/mid/end` (KiCad 6.0) | H9:122 |
| 20211229 | `stroke` вместо `width` | H9:127 |
| 20220225 | удалён `tedit` | H9:133 |
| 20220308 | `knockout`, сохранение `locked` у графического текста | H9:134 |
| 20221018 | `zone_layer_connections` (KiCad 7.0) | H9:143 |
| 20230620 | поля PCB (`property` вместо `fp_text reference/value`) | H9:147 |
| 20230924 | `FIRST_NORMALIZED_VERISON` — нормализованные булевы | H9:182 |
| 20231014 | «V8 file format normalization» | H9:153 |
| 20231212 | «footprint boolean format» (`(locked yes)` и т. п.) | H9:154 |
| 20231231 | `uuid` вместо `id` у групп | H9:155 |
| 20240108 | булевы в `teardrops` (KiCad 8.0) | H9:156 |
| 20240201 | nullable-переопределения (0 ≠ «наследовать»; парсер для ≤ 20240201 трактует 0 как «не задано», P9:4724-4758, 5270-5303) | H9:158 |
| 20240225 | `solder_paste_margin_ratio` (вместо `solder_paste_ratio`) | H9:160 |
| 20240609 | `tenting` | H9:161 |
| 20240706 | встроенные файлы (`embedded_fonts`, `embedded_files`; лексер знает `\|`) | H9:164 |
| 20240928 / 20240929 | `component_classes` / сложные падстеки | H9:166-167 |
| 20241010 | маска/маржин у графических фигур | H9:171 |
| 20241129 | нормализация `fill` (`yes\|no`) | H9:173 |
| 20241228 | `curve_points` → `curved_edges` | H9:174 |
| 20241229 | произвольное число User-слоёв (KiCad 9.0) | H9:175 |
| 20250210 … 20260206 | knockout у текстбоксов; штриховка фигур; jumper-пады; time-domain (`die_delay`); `lib_id` групп; `(island yes/no)`; press-fit; стек слоёв footprint (`stackup`); скругление прямоугольников; точки; `units`; отказ от номеров цепей; backdrill; варианты | H10:183-204 |

Точная версия перехода `tstamp` → `(uuid "…")` у элементов и кавычек у `generator` по комментариям
не установлена (между 20221018 и 20240108; вероятно, 20231014) — **не проверено**. Парсер 9.0 принимает
оба токена (`case T_tstamp: case T_uuid:`, P9:3162-3163, 3502-3503).

---

## 12. Приложение: KiCad 5.1 (`module`), кратко — W5

`(module ИМЯ [locked] [placed] (layer ИМЯ) (tedit HEX) [(tstamp HEX)]` (W5:985-1019), затем `(at)` (не
в библиотеке), `descr`, `tags`, `path`, `autoplace_cost90/180`, маржины (`solder_paste_ratio`),
`clearance`, `zone_connect`, `thermal_width`, `thermal_gap`, `(attr smd|virtual)` (W5:1020-1087),
`fp_text reference`, `fp_text value`, графика **в порядке списка** (без сортировки), пады в порядке
списка, модели (W5:1089-1150). Кавычки — только по необходимости (§9.1). `fp_text`: `(fp_text ТИП
ТЕКСТ (at XY [ANG] [unlocked]) (layer L) [hide] (effects …))` без `tstamp` (W5:1489-1548).
`fp_arc (start ЦЕНТР) (end НАЧАЛО) (angle ГРАД)`, `(width W)` после `(layer)` (W5:890-964). ✔
`kfp/v6.0.0`: 1298 файлов начинаются с `(module ИМЯ (layer F.Cu) (tedit HEX)`; имена, `REF**`, номера
падов, слои — голые (`(pad 1 thru_hole circle … (layers *.Cu *.Mask))`).

---

## 13. Проверено

Скрипты (только чтение, в `scratchpad/research/`): `writer_check.py` → `writer_check.out`,
`numfmt_check.py`, `order_check.py`, `refimpl_check.py` → `refimpl_check.out`, `prettify.py`.

1. **Порядок корневых дочерних узлов** по таблицам §1 (6.0/8.0/9.0/10.0): без нарушений в K6 1306/1306,
   K8 1377/1377, K9 1860/1860, K10 643/643; фикстуры kicad6 217/217, kicad8 1377/1377, kicad9 194/194,
   kicad10dev 31/31 (файлы pcbnew).
2. **Отсутствие в библиотеке** корневых `uuid`/`tstamp`/`at`: 0 во всех наборах; корневой слой `"F.Cu"` — 100 %.
3. **Поля/тексты**: порядок `at unlocked layer hide uuid effects` — без нарушений (K8 6885, K9 7440, K10 2572
   полей; `fp_text` 1377/2045/689); `(at x y a)` всегда с углом в 8.0+; в K6 угол только ≠ 0 (3634 без угла,
   284 с углом, `0` — ни разу); `hide` у `fp_text` в K9/K10 — 0; `(hide yes)` у полей K8 4131, K9 3721, K10 1287.
   Порядок `effects`/`font`/`justify` — без нарушений (K6 3918, K8 8262, K9 9485, K10 3261 блоков `effects`).
4. **Фигуры**: порядок дочерних узлов — K6 67607, K8 68900, K9 74468, K10 10393 без нарушений; формы
   `fill` (§3.6); `stroke` всегда `(width)(type)`; типы линий `solid`/`default`; `width` вместо `stroke` — только K6.
5. **Пады**: порядок — K6 22357, K8 24443, K9 22482, K10 22238 без нарушений; нулевой угол в `(at)` — 0;
   `remove_unused_layers`: K6 — 0, K8 `no` 10290 (= все THT), K9 `no` 8162, K10 `no` 1796; номера — всегда
   в кавычках; формы `drill` (`N`, `oval N N`, `N (offset)`, `(offset)`); порядок слоёв в `(layers)` = ID
   версии и шаблоны первыми — все 91520 падов.
6. **Сортировка**: графика по `cmp_drawings` и пады по `cmp_pads` своей версии — K6 1306, K8 1377, K9 1860,
   K10 643 файлов без нарушений.
7. **Кавычки**: `uuid` — всегда в кавычках в 8.0+ (все фигуры и пады), `tstamp` голый в K6; `generator`
   голый в K6, в кавычках в K8+; `generator_version` `"8.0"`/`"9.0"`/`"10.0"`; `(layers)` K6 — шаблоны голые
   (9581), K8+ — всё в кавычках.
8. **Числа**: все числовые токены файлов pcbnew воспроизводятся `IU`/`D2S`-портом (объединением двух
   форматтеров): K6 474019, K8 518580, K9 553950, K10 181577 — 0 расхождений, экспонент нет (`numfmt_check.py`).
9. **Строки**: разэкранирование (§9.2) + `quotes` (§9.1) восстанавливают байт-в-байт все строки в кавычках
   файлов pcbnew: K6 141368, K8 288902, K9 296867, K10 142150.
10. **Версионные признаки**: `embedded_fonts no` K9 1860/1860, K10 643/643; `duplicate_pad_numbers_are_jumpers no`
    K10 643/643; `F&B.Cu` → `*.Cu` на одном и том же файле (K9 → K10); `-0` в `xyz` модели — K10 (6 токенов);
    `(hide yes)` у модели — K9 1, K10 2.
11. **Изменения в ветке 9.0** (§7.4) — сравнением текстов тегов 9.0.0/9.0.4/9.0.5/9.0.6/9.0.7.
12. Идентичность `OUTPUTFORMATTER::Quotes` в 6.0/7.0/8.0/9.0/10.0 и `DSNLEXER::NextTok` (с оговорками §9.2) —
    `diff` исходников.
13. Файлы `kicad-footprint-generator` (K9-gen 1437, K10-gen 4239) — не вывод KiCad: у них нет `uuid`,
    есть отклонения от порядка/сортировки (8 и 1 файл в K9-gen; `point` после `pad` в 326 файлах K10-gen;
    маржины перед `property` в 129 файлах K10-gen).

## 14. Открытые вопросы

1. **Writer 7.0** (20221018) не проверен на реальных файлах — их нет в наборах.
2. Голые формы 6.0/7.0 (`hide`, `unlocked` в `at`, `locked` текста/фигуры/пада, `bold`, `italic`,
   `knockout`, пустые `(remove_unused_layers)`/`(keep_end_layers)`) в наборах не встречаются — только
   по исходнику.
3. Не встречаются в наборах, описаны только по исходнику: `render_cache`, `fp_text_box`, `table`, `dimension`,
   `image`, `padstack`, `tenting`, `teardrops`, `private_layers`, `component_classes`, `embedded_files`,
   `units`, `stackup`, `jumper_pad_groups`, `point`, `variant`, `face`, `line_spacing`, цвет в `stroke`.
4. Точная версия появления `(uuid "…")` у элементов, кавычек у `generator` и `generator_version` (§11.2).
5. `static const LSET cu_all` в `formatLayers` 8.0 — зависимость вывода от первой платы в сессии не проверялась.
6. Потеря пада при записи для номеров, равных по `StrNumCmp` (`"1"` и `"01"`) — вывод из семантики
   `std::set`, в KiCad не проверено.
7. Потеря `hide` у `fp_text user` при пересохранении файла 8.0 в 9.0 (§2.1) — в KiCad не проверено.
8. Пересчёт модели `(at (xyz …))` из дюймов с `25.4f` (§5.3) — вычислено, в KiCad не проверено.
9. Для 10.0 ключ сортировки текстов (`cmp_drawings`) проверен упрощённо (позиция, угол, UUID).
10. Как `Prettify` обрабатывает строки начальных комментариев (`#…`) — не проверено.
11. `master` (11.0-dev, 20260901) — не разбирался (кроме списка из §11.1).
12. Порядок и форма `(embedded_files …)` (`WriteEmbeddedFiles`) не документированы.
