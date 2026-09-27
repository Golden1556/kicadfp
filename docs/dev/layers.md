# Слои KiCad: канонические имена, групповые обозначения, старая нумерация, цвета

Спецификация для модуля `kicadfp.layers` (см. `architecture.md` §5). Машиночитаемая копия всех таблиц —
`docs/dev/layers.json` (генерируется скриптом, см. §10). Все утверждения ниже подтверждены ссылками на
исходники KiCad (`<ветка>/<путь>:<строки>`) или на файлы-фикстуры; то, что не проверено, помечено
**«не проверено»**.

Обозначения версий:

| Обозначение | Что это | Версия формата `.kicad_mod` |
|---|---|---|
| 5.1 | KiCad 5.1 (корень `module`, слои без кавычек) | — / 20171130 |
| 6.0 | KiCad 6 | 20211014 |
| 7.0 | KiCad 7 | 20221018 |
| 8.0 | KiCad 8 | 20240108 |
| 9.0 | ветка 9.0 (все 9.0.x; где поведение различается — указано 9.0.0–9.0.5 / 9.0.6+) | 20241229 |
| master | KiCad 10-dev (фикстуры `kicad10dev`, `version 20260206`) | 20260206 |

Пути исходников: `include/layer_ids.h` (в 5.1 — `include/layers_id_colors_and_visibility.h`),
`common/lset.cpp`, `common/layer_id.cpp`, парсер `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp`
(6.0/7.0 — `pcbnew/plugins/kicad/pcb_parser.cpp`), writer `pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp`
(6.0/7.0 — `pcbnew/plugins/kicad/kicad_plugin.cpp` = `PCB_PLUGIN`), legacy
`pcbnew/pcb_io/kicad_legacy/pcb_io_kicad_legacy.cpp` (6.0/7.0 — `pcbnew/plugins/legacy/legacy_plugin.cpp`).
Ниже для краткости: `layer_ids.h`, `lset.cpp`, `parser.cpp`, `writer.cpp`, `legacy.cpp`.

---

## 1. Канонические имена слоёв

### 1.1 Полная таблица

Имя в файле — строка, которую пишет writer (`LSET::Name`) и которую ищет парсер. «id» — числовое значение
`PCB_LAYER_ID`; **порядок по возрастанию id = порядок, в котором writer перечисляет отдельные слои в
`(layers ...)`** (§4.2).

| Имя в файле | 5.1 | 6.0–8.0 | 9.0+ | UI-имя (LayerName) | Категория | Flip |
|---|---|---|---|---|---|---|
| `F.Cu` | 0 | 0 | 0 | F.Cu | copper | B.Cu |
| `In1.Cu` | 1 | 1 | 4 | In1.Cu | copper | — |
| `In2.Cu` … `In29.Cu` (k) | k | k | 4+2·(k−1) | = имя | copper | — |
| `In30.Cu` | 30 | 30 | 62 | In30.Cu | copper | — |
| `B.Cu` | 31 | 31 | 2 | B.Cu | copper | F.Cu |
| `B.Adhes` | 32 | 32 | 11 | B.Adhesive | tech | F.Adhes |
| `F.Adhes` | 33 | 33 | 9 | F.Adhesive | tech | B.Adhes |
| `B.Paste` | 34 | 34 | 15 | B.Paste | tech | F.Paste |
| `F.Paste` | 35 | 35 | 13 | F.Paste | tech | B.Paste |
| `B.SilkS` | 36 | 36 | 7 | B.Silkscreen | tech | F.SilkS |
| `F.SilkS` | 37 | 37 | 5 | F.Silkscreen | tech | B.SilkS |
| `B.Mask` | 38 | 38 | 3 | B.Mask | tech | F.Mask |
| `F.Mask` | 39 | 39 | 1 | F.Mask | tech | B.Mask |
| `Dwgs.User` | 40 | 40 | 17 | User.Drawings | user | — |
| `Cmts.User` | 41 | 41 | 19 | User.Comments | user | — |
| `Eco1.User` | 42 | 42 | 21 | User.Eco1 | user | — |
| `Eco2.User` | 43 | 43 | 23 | User.Eco2 | user | — |
| `Edge.Cuts` | 44 | 44 | 25 | Edge.Cuts | user | — |
| `Margin` | 45 | 45 | 27 | Margin | user | — |
| `B.CrtYd` | 46 | 46 | 29 | B.Courtyard | footprint | F.CrtYd |
| `F.CrtYd` | 47 | 47 | 31 | F.Courtyard | footprint | B.CrtYd |
| `B.Fab` | 48 | 48 | 33 | B.Fab | footprint | F.Fab |
| `F.Fab` | 49 | 49 | 35 | F.Fab | footprint | B.Fab |
| `User.1` | — | 50 | 39 | User.1 | user-defined | — |
| `User.2` … `User.8` (k) | — | 49+k | 39+2·(k−1) | = имя | user-defined | — |
| `User.9` | — | 58 | 55 | User.9 | user-defined | — |
| `Rescue` | 50 | 59 | 37 | Rescue (переводимая строка) | rescue | — |
| `User.10` … `User.45` (k) | — | — | 39+2·(k−1) (User.45 = 127) | = имя | user-defined | — |

Количество имён: 5.1 — 51, 6.0/7.0/8.0 — 60, 9.0/master — 96 (32 медных + 8 tech + 6 user + 4 footprint +
`Rescue` + 45 `User.N`).

Источники:
- 5.1: enum `include/layers_id_colors_and_visibility.h:73-139`, имена `common/lset.cpp:73-147` (явный `switch`,
  нет `User.N`, `Rescue` = 50).
- 6.0/7.0/8.0: enum `layer_ids.h` 6.0:65-144, 7.0:58-137, 8.0:59-138 (последовательные значения, `User_1..User_9`
  6.0:130-138, `Rescue` = 59 6.0:140); имена — явный `switch` `lset.cpp` 6.0:82-167, 7.0:82-167, 8.0:89-174. Тексты
  имён в 6.0/7.0/8.0 совпадают побайтно (проверено, §11).
- 9.0: enum `layer_ids.h` 9.0:59-171 (медь чётные 0,2,4..62; остальные нечётные; `User_45 = 127`,
  `PCB_LAYER_ID_COUNT = 128`, `MAX_CU_LAYERS 32`, `MAX_USER_DEFINED_LAYERS 45` :176-177). master — enum идентичен 9.0.
- 9.0 `LSET::Name` (`lset.cpp` 9.0:188-243): явный `switch` только для F.Cu, B.Cu, tech, user, footprint, Rescue;
  остальное по формуле (§1.3). master (`lset.cpp` master:184-) — та же логика, другой способ форматирования
  числа (результат тот же).
- UI-имена: `LayerName()` в `common/layer_id.cpp` (9.0:31-…, 6.0:30-…). **Это имена по умолчанию для интерфейса,
  в `.kicad_mod` они не пишутся** — writer всегда использует `LSET::Name` (§4.2, §2.1).
- Категории: 9.0 `lset.cpp:631-679` (`BackTechMask`, `FrontTechMask`, `UserMask` = Dwgs/Cmts/Eco1/Eco2/Edge.Cuts/Margin),
  `IsFrontLayer`/`IsBackLayer` `layer_ids.h` 9.0:765-801 (F.Cu, F.Adhes, F.Paste, F.SilkS, F.Mask, F.CrtYd, F.Fab и
  симметрично B.*; всё прочее — «ни front, ни back»).
- Flip: `FlipLayer` `layer_id.cpp` 9.0:169-212 и `LSET::FlipStandardLayers` `lset.cpp` 9.0:468-518: пары F↔B для Cu,
  SilkS, Adhes, Mask, Paste, CrtYd, Fab; внутренние медные зеркалятся только при `aCopperLayersCount >= 4`
  (`In(k)` → `In(N−1−k)`, где N — число медных слоёв), остальные слои не меняются.

### 1.2 Порядок перечисления (для writer)

- **6.0–8.0**: `F.Cu, In1.Cu … In30.Cu, B.Cu, B.Adhes, F.Adhes, B.Paste, F.Paste, B.SilkS, F.SilkS, B.Mask, F.Mask,
  Dwgs.User, Cmts.User, Eco1.User, Eco2.User, Edge.Cuts, Margin, B.CrtYd, F.CrtYd, B.Fab, F.Fab, User.1 … User.9, Rescue`.
- **9.0+** (по числовому id): `F.Cu(0), F.Mask(1), B.Cu(2), B.Mask(3), In1.Cu(4), F.SilkS(5), In2.Cu(6), B.SilkS(7),
  In3.Cu(8), F.Adhes(9), In4.Cu(10), B.Adhes(11), In5.Cu(12), F.Paste(13), In6.Cu(14), B.Paste(15), In7.Cu(16),
  Dwgs.User(17), In8.Cu(18), Cmts.User(19), In9.Cu(20), Eco1.User(21), In10.Cu(22), Eco2.User(23), In11.Cu(24),
  Edge.Cuts(25), In12.Cu(26), Margin(27), In13.Cu(28), B.CrtYd(29), In14.Cu(30), F.CrtYd(31), In15.Cu(32), B.Fab(33),
  In16.Cu(34), F.Fab(35), In17.Cu(36), Rescue(37), In18.Cu(38), User.1(39), In19.Cu(40), User.2(41), … In30.Cu(62),
  User.13(63), User.14(65), … User.45(127)` — т.е. сортировать по id из таблицы §1.1
  (`layers.json` → `ids["9.0+"]`; `canonical["9.0"]` уже отсортирован).

Следствие, видимое в файлах: SMD-площадка с F.Cu+F.Paste+F.Mask пишется в 6.0–8.0 как
`(layers "F.Cu" "F.Paste" "F.Mask")`, а в 9.0+ как `(layers "F.Cu" "F.Mask" "F.Paste")`.

### 1.3 Правило имени в 9.0+ и «призрачные» имена

`LSET::Name` 9.0 (`lset.cpp:225-240`), для id вне явного `switch`:
- `id < 0` → `"UNDEFINED"`;
- нечётный id → `"User.%d"`, где `%d = (id − 37) / 2` (37 = `Rescue`);
- чётный id → `"In%d.Cu"`, где `%d = (id − 2) / 2`.

Парсер 9.0 строит таблицу имён перебором **всех** `id = 0..127` (`parser.cpp` 9.0:107-113), поэтому кроме 96
канонических имён он принимает ещё `In31.Cu` … `In62.Cu` (чётные id 64..126, которых нет в enum; `IsCopperLayer`
для них истинно — `layer_ids.h` 9.0:663-666). Writer их не пишет, KiCad их не создаёт. **kicadfp должен считать их
невалидными** (в `layers.json` — `parser_extra_names_9.0`).

`LSET::NameToLayer` (`lset.cpp` 9.0:117-163) — вспомогательный разбор (используется при чтении стека платы
`parser.cpp` 9.0:1997): `User.<n>` при n>0 → `User_1 + (n−1)·2`, `In<n>.Cu` при n>0 → `In1_Cu + (n−1)·2`, иначе −1.

---

## 2. Как парсер разбирает имена слоёв

### 2.1 Таблицы парсера

`PCB_IO_KICAD_SEXPR_PARSER::init()` (9.0:94-136; 8.0:98-129; 7.0 `PCB_PARSER::init` :88-119; 6.0 :76-107;
master :110-141):

1. `m_layerIndices[LSET::Name(id)] = id` и `m_layerMasks[LSET::Name(id)] = {id}` для всех `id < PCB_LAYER_ID_COUNT`
   (6.0–8.0: 60 имён; 9.0+: 128 имён, §1.3).
2. Групповые обозначения — **только в `m_layerMasks`** (§3.1).
3. Старые имена `Inner1.Cu … Inner14.Cu` — **только в `m_layerMasks`**: `Inner<i>.Cu` → `In<15−i>.Cu`
   (9.0: `In15_Cu − 2·i`, 6.0–8.0: `In15_Cu − i`; результат одинаков: Inner1→In14 … Inner14→In1).

Для `.kicad_mod` таблица платы (`(layers ...)` в `kicad_pcb`) отсутствует, поэтому пользовательские имена слоёв
в файле посадочного места не встречаются; английские канонические имена «выживают» (комментарий
`parser.cpp` 9.0:104-106).

### 2.2 `(layer X)` — одиночный слой

`parseBoardItemLayer()` → `lookUpLayer(m_layerIndices)` (9.0:2106-2137; 8.0:1979-2011 (шаблонная версия);
6.0 `PCB_PARSER::lookUpLayer` :1718-1749):
- имя найдено → его id; если это `Rescue` — имя добавляется в `m_undefinedLayers`;
- имя **не найдено** → возвращается `Rescue`, имя добавляется в `m_undefinedLayers`. **Исключения нет.**
- Групповые обозначения и `Inner<i>.Cu` в `(layer ...)` не принимаются (их нет в `m_layerIndices`) → `Rescue`.

`m_undefinedLayers` проверяется **только при разборе платы** (`parseBOARD_unchecked`, 9.0:1138-1236): в GUI —
диалог «Items found on undefined layers … rescue them to the Cmts.User layer?», без GUI — `THROW_IO_ERROR`.
В разборе посадочного места (`parseFOOTPRINT_unchecked`) проверки нет (grep `m_undefinedLayers` по 9.0 даёт только
строки 1138-1230 и 2113-2119) → **элемент `.kicad_mod` на неизвестном слое молча загружается на слой `Rescue`
и при сохранении пишется как `"Rescue"`** (реальный пример в §3.4).

Кавычки: лексер отдаёт `curText` без кавычек, поэтому `(layer F.SilkS)` и `(layer "F.SilkS")` эквивалентны
(оба варианта встречаются в фикстурах, §11).

Особые места:
- Корень footprint: `(layer X)` → `SetLayer( layer == B_Cu ? B_Cu : F_Cu )` (9.0:4510-4518) — любое имя, кроме
  `B.Cu`, превращается в `F.Cu`.
- Текст (`fp_text`, `property`): `(layer X [knockout])` (9.0:3486-3499); после имени допускается только атом
  `knockout`, иначе ошибка `Expecting )`.
- `(private_layers A B ...)` (9.0:4689-4711): поиск в `m_layerIndices`; **неизвестное имя → ошибка разбора**
  `Expecting "layer name"` (единственное место, где неизвестный слой — ошибка). Для файлов с версией < 20220427
  из результата удаляются `Edge.Cuts` и `Margin`. Writer пишет их в порядке id через `LSET::Name` (writer 9.0:1245-1256).

### 2.3 `(layers A B ...)` — набор слоёв

`parseBoardItemLayersAsMask()` (9.0:2140-2152) — объединение `m_layerMasks[token]` по всем токенам; неизвестный
токен → бит `Rescue` (`lookUpLayerSet` 9.0:2095-2103, **без** записи в `m_undefinedLayers`; в 6.0–8.0 используется
та же шаблонная `lookUpLayer<LSET>`, которая записывает имя в `m_undefinedLayers`, что для футпринта ни на что не
влияет). Порядок токенов не важен, дубликаты не важны.

`(layers ...)` встречается у: `pad` (9.0:5208-5213 — `pad->SetLayerSet(mask)` без проверок), `zone`, и в 9.0+ у
графики (`fp_line` и т.п.) — если набор из >1 слоя (writer 9.0:1014-1017: `GetLayerSet().count() > 1` →
`formatLayers`, иначе `(layer ...)`; парсер 9.0:3133-3140 принимает оба). В фикстурах `(layers)` найдено только у
`pad` и `zone` (§11).

### 2.4 Правило валидации для kicadfp («графика на несуществующем слое»)

KiCad при загрузке `.kicad_mod` не выдаёт ошибок на неизвестные имена (кроме `private_layers`), поэтому проверку
kicadfp должен делать сам:

| Токен | В `(layer ...)` | В `(layers ...)` | Рекомендация kicadfp |
|---|---|---|---|
| каноническое имя целевой версии (§1.1) | ок | ок | ок |
| `User.10`…`User.45` при целевой версии < 9.0 | → Rescue | → Rescue | ошибка «слой не существует в версии X» |
| `In31.Cu`…`In62.Cu` | принимается только 9.0+ (id 64..126) | то же | ошибка (§1.3) |
| `Rescue` | принимается, но помечается undefined | принимается | предупреждение |
| групповое обозначение (§3.1) | → Rescue | ок | в `(layer)` — ошибка |
| `Inner1.Cu`…`Inner14.Cu` | → Rescue | ок (→ In14..In1) | при чтении — конвертировать, при записи — никогда |
| UI-имена (`F.Silkscreen`, `B.Courtyard`, `User.Drawings`…) | → Rescue | → Rescue | ошибка (частая ошибка ручного ввода) |
| любое иное | → Rescue | → Rescue | ошибка |

Регистр важен (поиск в `std::map<std::string,...>` — точное совпадение).

---

## 3. Групповые обозначения (wildcards) в `(layers ...)`

### 3.1 Что принимает парсер

Одинаково в 6.0, 7.0, 8.0, 9.0, master (`parser.cpp` 9.0:115-123; 8.0:109-117; 7.0:99-107; 6.0:87-95):

| Токен | Раскрывается в | Пишет ли writer |
|---|---|---|
| `*.Cu` | `LSET::AllCuMask()` = все 32 медных (`F.Cu`, `In1.Cu`…`In30.Cu`, `B.Cu`) | да |
| `*In.Cu` | `LSET::InternalCuMask()` = `In1.Cu`…`In30.Cu` (9.0 `lset.cpp:560-568`) | **нет** |
| `F&B.Cu` | `F.Cu`, `B.Cu` | да (6.0–9.0.5; в 9.0.6+ только для зон) |
| `*.Adhes` | `B.Adhes`, `F.Adhes` | да |
| `*.Paste` | `B.Paste`, `F.Paste` | да |
| `*.Mask` | `B.Mask`, `F.Mask` | да |
| `*.SilkS` | `B.SilkS`, `F.SilkS` | да |
| `*.Fab` | `B.Fab`, `F.Fab` | да |
| `*.CrtYd` | `B.CrtYd`, `F.CrtYd` | да |
| `Inner1.Cu`…`Inner14.Cu` | `In14.Cu`…`In1.Cu` (§2.1) | нет |

Других групповых обозначений нет: `*.Eco`, `*.User`, `*.*`, `F.*` и т.п. парсер **не знает** → бит `Rescue`.

### 3.2 Что пишет writer: `formatLayers`

Источники: 9.0 `writer.cpp:1345-1425`; 8.0 :1360-1443; 7.0 `kicad_plugin.cpp:1373-1453`; 6.0 :1290-1370; 5.1
`kicad_plugin.cpp` `PCB_IO::formatLayers` (та же схема). Псевдокод (вход — множество слоёв `S`):

```
cu_board = AllCuMask(N)          # N — см. ниже
out = []
if not enumerate:                # enumerate=true только для зон на меди (writer 9.0:2466-2467)
    if S ⊇ cu_board:                         out += "*.Cu";   S -= все 32 медных
    elif S ∩ cu_board == {F.Cu, B.Cu}:       out += FB;       S -= {F.Cu, B.Cu}
    for (tok, pair) in [("*.Adhes",{B.Adhes,F.Adhes}), ("*.Paste",{B.Paste,F.Paste}),
                        ("*.SilkS",{B.SilkS,F.SilkS}), ("*.Mask",{B.Mask,F.Mask}),
                        ("*.CrtYd",{B.CrtYd,F.CrtYd}), ("*.Fab",{B.Fab,F.Fab})]:
        if S ⊇ pair:  out += tok;  S -= pair
out += [LSET::Name(id) for id in 0..PCB_LAYER_ID_COUNT-1 if id in S]      # порядок §1.2
print "(layers" + " ".join(out) + ")"
```

Порядок групп фиксирован: `*.Cu|F&B.Cu`, `*.Adhes`, `*.Paste`, `*.SilkS`, `*.Mask`, `*.CrtYd`, `*.Fab`, затем
отдельные слои по возрастанию id. Групповое обозначение пишется **только если присутствуют обе стороны**; одна
сторона пишется отдельным именем.

Различия версий:

| Версия | `N` (медь платы) | `FB` (ровно F.Cu+B.Cu) | Кавычки |
|---|---|---|---|
| 5.1 | 32 (`static const cu_all(AllCuMask())`) | `F&B.Cu` | wildcards без кавычек; имена через `Quotew`, который в 5.1 ставит кавычки только при необходимости → фактически без кавычек (`common/richio.cpp` 5.1: `Quotes`) |
| 6.0 | 32 (`static const`) | `F&B.Cu` | wildcards **без кавычек** (`output += " *.Cu"`), отдельные имена **в кавычках** (6.0 `Quotes` всегда ставит кавычки, `richio.cpp` 6.0) |
| 7.0 | 32 (`static const`) | `F&B.Cu` | всё в кавычках (`Quotew("*.Cu")`) |
| 8.0 | `static const cu_all(AllCuMask(m_board ? m_board->GetCopperLayerCount() : 32))` — вычисляется **один раз за процесс** при первом вызове | `F&B.Cu` | всё в кавычках |
| 9.0.0–9.0.5 | вычисляется при каждом вызове: `m_board ? copperCount : 32` | `F&B.Cu` | всё в кавычках |
| 9.0.6+, master | то же | `F&B.Cu` только если `aIsZone`, иначе **`*.Cu`** | всё в кавычках |

(9.0.x различия проверены по тегам `tags/9.0.0…9.0.7-pcb_io_kicad_sexpr.cpp`; в 9.0.6 появилась ветка
`if( aIsZone ) F&B.Cu else *.Cu`.) При сохранении библиотеки (`FootprintSave` → `init()`) `m_board = nullptr`
(writer 9.0:2749-2751, 8.0:2509-2511) → N = 32. Для 8.0: если первым в процессе был вызов при сохранении платы с
2 медными слоями, `cu_all` навсегда = {F.Cu,B.Cu} (квирк; на библиотечных файлах не наблюдался).

Внимание: в 9.0.6+ набор `{F.Cu, B.Cu}` пишется как `"*.Cu"`, а при чтении `"*.Cu"` раскрывается в все 32 слоя —
это **не** round-trip по множеству, но так делает KiCad (NPTH-отверстия, §4). kicadfp при записи в профиле 9.0.6+/10
должен повторять это поведение (пресеты — §4.1).

Одиночный слой — `formatLayer` (9.0:458-463; 8.0:461-466; 7.0:421-426; 6.0:466-471):
- 6.0: ` (layer "X")` (кавычки всегда).
- 7.0/8.0: ` (layer "X")` или ` (layer "X" knockout)`.
- 9.0+: `(layer "X" knockout)` / `(layer "X" )` — лишний пробел перед `)` удаляет `KICAD_FORMAT::Prettify`
  (`kicad_io_utils.cpp` 9.0:180, «Remove extra space before end of list»), в файле `(layer "X")`.
- 5.1: `(layer X)` без кавычек (`kicad_plugin.cpp` 5.1 `formatLayer`, `CTL_STD_LAYER_NAMES`).

### 3.3 Примеры из реальных файлов

```
(pad "1" thru_hole rect (at 0 0) (size 2.8 2.8) (drill 1.4) (layers *.Cu *.Mask) (tstamp …))   ← 6.0, fixtures/kicad6/Capacitor_THT.pretty/CP_Axial_L26.5mm_D20.0mm_P33.00mm_Horizontal.kicad_mod
		(layers "*.Cu" "*.Mask")                          ← 8.0, fixtures/kicad8/Capacitor_THT.pretty/CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal.kicad_mod
		(layers "F&B.Cu" "*.Mask")                        ← 9.0.0 NPTH, kfp/v9.0.0/MountingHole.pretty/ToolingHole_1.152mm.kicad_mod:84
		(layers "*.Cu" "*.Mask")                          ← тот же файл в kfp/master (writer 10.0):85
		(layers "F.Cu" "B.Cu" "In1.Cu" "In2.Cu" … "In30.Cu")  ← zone (rule area) на меди, перечисление по id 9.0: ToolingHole_1.152mm.kicad_mod:90-95
		(layers "B.Mask" "Rescue")                        ← connect-pad, kfp/v9.0.0/MountingHole.pretty/MountingHole_6.4mm_M6_DIN965_Pad_TopBottom.kicad_mod:93
```

### 3.4 Где какие слои допустимы

Формат файла **не ограничивает** слои ни для pad, ни для графики, ни для текста — любое каноническое имя
загружается как есть. Ограничения есть только в UI/проверках KiCad:

| Объект | Что допускает KiCad | Источник |
|---|---|---|
| корень footprint `(layer)` | только `F.Cu`/`B.Cu` (иначе → F.Cu) | parser 9.0:4510-4518 |
| pad, медь | любые медные; SMD/CONN — не более одного медного слоя (SetAttribute обрезает, §4.2) | pad.cpp 9.0:923-955 |
| pad, не-медь | UI диалога площадки: `F/B.Adhes, F/B.Paste, F/B.SilkS, F/B.Mask, Eco1.User, Eco2.User, Dwgs.User` (чекбоксы); тот же список — «слои, на которые редактор разрешает класть pad» | dialog_pad_properties.cpp 9.0:2009-2042; pad.cpp 9.0:1815-1818 (`layers_mech`) |
| графика/текст в редакторе футпринтов | у платы-заглушки 3 медных слоя (`F.Cu`, `In1.Cu` с именем «Inner layers», `B.Cu`) плюс её enabled-слои по умолчанию (состав не проверен); `User.N` дополнительно включаются, если уже использованы в футпринте или им задано имя в настройках редактора | footprint_edit_frame.cpp 9.0:538-573 |
| `LSET::ForbiddenFootprintLayers()` | внутренняя медь кроме `In1.Cu` (In2..In30) — где именно применяется, **не проверено** | lset.cpp 9.0:726-730 |

Наблюдения по стандартной библиотеке (все файлы 5 срезов kicad-footprints, §11): `(layer ...)` у графики/текста
встречаются только `F.SilkS, F.Fab, F.CrtYd, F.Cu` (корень), `Cmts.User, F.Adhes, F.Mask, Dwgs.User, F.Paste,
Edge.Cuts, B.Fab`.

---

## 4. Площадки: пресеты слоёв и проверки

### 4.1 Пресеты `PAD::*Mask()`

`pad.cpp` 9.0:334-366 (8.0:195-227, 6.0:173-205; значения одинаковы):

| Тип (`pad` токен) | Функция | Множество слоёв | 6.0–8.0 пишется | 9.0.0–9.0.5 | 9.0.6+ / master |
|---|---|---|---|---|---|
| `thru_hole` | `PTHMask()` | 32 медных + F.Mask + B.Mask | `"*.Cu" "*.Mask"` | `"*.Cu" "*.Mask"` | `"*.Cu" "*.Mask"` |
| `smd` | `SMDMask()` | F.Cu, F.Paste, F.Mask | `"F.Cu" "F.Paste" "F.Mask"` | `"F.Cu" "F.Mask" "F.Paste"` | `"F.Cu" "F.Mask" "F.Paste"` |
| `smd` (обратная сторона)¹ | flip(`SMDMask`) | B.Cu, B.Paste, B.Mask | `"B.Cu" "B.Paste" "B.Mask"` | `"B.Cu" "B.Mask" "B.Paste"` | то же |
| `connect` | `ConnSMDMask()` | F.Cu, F.Mask | `"F.Cu" "F.Mask"` | `"F.Cu" "F.Mask"` | то же |
| `connect` (обратная)¹ | flip | B.Cu, B.Mask | `"B.Cu" "B.Mask"` | то же | то же |
| `np_thru_hole` | `UnplatedHoleMask()` | F.Cu, B.Cu, F.Mask, B.Mask | `"F&B.Cu" "*.Mask"` | `"F&B.Cu" "*.Mask"` | `"*.Cu" "*.Mask"` |
| `smd` без меди (aperture) | `ApertureMask()` | F.Paste | `"F.Paste"` | `"F.Paste"` | `"F.Paste"` |

¹ У KiCad нет отдельного пресета «smd_back»: в диалоге выбор «B.Cu» для SMD/CONN ставит только бит `B_Cu`, тех.слои
берутся из чекбоксов (dialog 9.0:1994-2002, 2009-2042); при перевороте футпринта набор отражается
`FlipStandardLayers` (§1.1). kicadfp: `smd_back` = отражённый `smd`.

Где применяются: конструктор `PAD` ставит `PTHMask()` (pad.cpp 9.0:104); диалог при смене типа, если набор пуст
(`updatePadLayersList` dialog 9.0:1281-1365); для нового pad в SMD-футпринте — `SMDMask()` (dialog 9.0:628-631).
Aperture-pad — `smd` без медных слоёв (`IsAperturePad()` pad.h 9.0:447-450).

Реально встречающиеся в библиотеке `generator "kicad-footprint-generator"` варианты для NPTH:
`"*.Cu" "*.Mask"` (kfp v9.0.0: 101 шт., master: 249 шт.) — генератор пишет `*.Cu` и в 9.0 (то есть NPTH на
всей меди). kicadfp рекомендуется: пресет `np_thru_hole` = `["*.Cu","*.Mask"]` для профилей 9.0.6+/10 и
генерации «как в библиотеке KiCad»; `["F&B.Cu","*.Mask"]` для профилей 6–9.0.5 «как пишет pcbnew».

### 4.2 Побочные эффекты `PAD::SetAttribute` (важно при конвертации)

`pad.cpp` 9.0:923-962 (8.0:673-, 6.0:636-), срабатывает **только при смене** атрибута:
- `PTH`: `layers |= AllCuMask()`;
- `SMD`/`CONN`: если медных слоёв > 1 — оставить один: `B.Cu`, если он был, иначе первый по id; сверло обнуляется;
- `NPTH`: номер площадки очищается (`m_number = ""`), цепь — unconnected.

Парсер s-expr вызывает `SetAttribute` по токену типа до `(layers)`, а `(layers)` затем перезаписывает набор
целиком — на результат чтения `.kicad_mod` не влияет. В legacy-импорте порядок обратный (§5.4).

### 4.3 Проверки `PAD::CheckPad` (для валидатора kicadfp)

`pad.cpp` 9.0:2270-2372, сообщения, связанные со слоями:

| Условие | Код | Текст |
|---|---|---|
| нет F.Cu и нет B.Cu, есть сверло, тип ≠ NPTH | DRCE_PADSTACK | plated through holes normally have a copper pad on at least one outer layer |
| CONN с F.Paste или B.Paste | DRCE_PADSTACK | connector pads normally have no solder paste; use a SMD pad instead |
| SMD/CONN на F.Cu и B.Cu | DRCE_PADSTACK | SMD pad has copper on both sides of the board |
| SMD/CONN: F.Cu + B.Mask (или F.Cu + B.Paste) | DRCE_PADSTACK | SMD pad has copper and mask (paste) layers on different sides of the board |
| SMD/CONN: B.Cu + F.Mask (или B.Cu + F.Paste) | DRCE_PADSTACK | то же |
| SMD/CONN: только внутренняя медь | DRCE_PADSTACK | SMD pad has no outer layers |

### 4.4 Статистика по реальным файлам

`pad type | (layers)` (скрипт `scan_layers.py`, §11), самые частые:

| Срез | Файлов | Топ комбинаций |
|---|---|---|
| kfp v6.0.0 (формат 5) | 1303 | smd `F.Cu F.Mask F.Paste` 9555; thru_hole `*.Cu *.Mask` 9055; smd `F.Cu F.Paste F.Mask` 2453; thru_hole `*.Cu` 525; smd `F.Paste` 499 |
| kfp v7.0.0 (6.0) | 1332 | smd `F.Cu F.Paste F.Mask` 12098; thru_hole `*.Cu *.Mask` 9055; smd `F.Cu F.Mask F.Paste` 914 (26 файлов старого формата) |
| kfp v8.0.0 | 1377 | smd `F.Cu F.Paste F.Mask` 13365; thru_hole `*.Cu *.Mask` 9655; thru_hole `*.Cu` 635; smd `F.Paste` 582 |
| kfp v9.0.0 | 3297 | smd `F.Cu F.Paste F.Mask` 32782 (генератор, формат 8); smd `F.Cu F.Mask F.Paste` 11818 (pcbnew 9); thru_hole `*.Cu *.Mask` 11811; np_thru_hole `*.Cu *.Mask` 101; connect `F.Cu F.Mask` 72, `B.Cu B.Mask` 35; np_thru_hole `F&B.Cu *.Mask` 1; connect `B.Mask Rescue` 1 |
| kfp master | 4882 | smd `F.Cu F.Mask F.Paste` 120541; thru_hole `*.Cu *.Mask` 21883; smd `F.Paste` 7050; np_thru_hole `*.Cu *.Mask` 249; np_thru_hole `F.Cu` 12 |

---

## 5. Старая нумерация слоёв (legacy `.mod`/`.brd`, KiCad ≤ 4, формат 2011)

### 5.1 Номера 0..31 и биты маски

Номера и макросы: `legacy.cpp` 9.0:102-174 (дублируют `include/layers_id_colors_and_visibility.h:9-49` bzr2986);
имена по умолчанию 2011: bzr2986 `pcbnew/class_board.cpp:236-263`. Современное имя — `leg_layer2new(16, n)`
(для библиотек `.mod` `m_cu_count = 16`: `legacy.cpp` 9.0:2923 `init()`, 9.0:3297 конструктор).

| № | Бит (hex) | Макрос | Имя 2011 | Современное имя (cu_count=16) |
|---|---|---|---|---|
| 0 | `00000001` | `LAYER_N_BACK` | Back | `B.Cu` |
| 1 | `00000002` | `LAYER_N_2` | Inner2 | `In14.Cu` |
| 2 | `00000004` | `LAYER_N_3` | Inner3 | `In13.Cu` |
| n (1..14) | `1<<n` | `LAYER_N_{n+1}` | Inner{n+1} | `In{15−n}.Cu` |
| 14 | `00004000` | `LAYER_N_15` | Inner15 | `In1.Cu` |
| 15 | `00008000` | `LAYER_N_FRONT` | Front | `F.Cu` |
| 16 | `00010000` | `ADHESIVE_N_BACK` | Adhes_Back | `B.Adhes` |
| 17 | `00020000` | `ADHESIVE_N_FRONT` | Adhes_Front | `F.Adhes` |
| 18 | `00040000` | `SOLDERPASTE_N_BACK` | SoldP_Back | `B.Paste` |
| 19 | `00080000` | `SOLDERPASTE_N_FRONT` | SoldP_Front | `F.Paste` |
| 20 | `00100000` | `SILKSCREEN_N_BACK` | SilkS_Back | `B.SilkS` |
| 21 | `00200000` | `SILKSCREEN_N_FRONT` | SilkS_Front | `F.SilkS` |
| 22 | `00400000` | `SOLDERMASK_N_BACK` | Mask_Back | `B.Mask` |
| 23 | `00800000` | `SOLDERMASK_N_FRONT` | Mask_Front | `F.Mask` |
| 24 | `01000000` | `DRAW_N` | Drawings | `Dwgs.User` |
| 25 | `02000000` | `COMMENT_N` | Comments | `Cmts.User` |
| 26 | `04000000` | `ECO1_N` | Eco1 | `Eco1.User` |
| 27 | `08000000` | `ECO2_N` | Eco2 | `Eco2.User` |
| 28 | `10000000` | `EDGE_N` | PCB_Edges | `Edge.Cuts` |
| 29–31 | `20000000`…`80000000` | — (не используются) | — | `Cmts.User` (ветка `default`, 9.0:357-360) |

Маски: `ALL_CU_LAYERS 0x0000FFFF`, `ALL_NO_CU_LAYERS 0x1FFF0000` (9.0:163-164); в 2011 также `ALL_LAYERS 0x1FFFFFFF`.
Замечание: в `docs/pcbnew-mod-format.md` §1.1 проекта kicad-2011-gen имена 18/19 записаны как `Paste_Back/Front`,
в исходнике bzr2986 — `SoldP_Back/SoldP_Front` (class_board.cpp:253-254). Для kicadfp имена 2011 справочные.

### 5.2 `leg_layer2new(cu_count, n)` — точно

`legacy.cpp` 9.0:311-364 (6.0 `legacy_plugin.cpp` / 7.0 — то же, 9.0 лишь использует `BoardLayerFromLegacyId`):

```
if 0 <= n <= 15:
    n == 15 -> F.Cu
    n == 0  -> B.Cu
    иначе   -> id = BoardLayerFromLegacyId(cu_count - 1 - n)     # layer_id.cpp 9.0:215-262
               (x in 1..30 -> In{x}.Cu; x == 0 -> F.Cu; x < 0 -> UNDEFINED/UNSELECTED -> newid<0 -> 0 = F.Cu)
иначе: 16..28 по таблице §5.1; любое другое -> Cmts.User
```

Внутренние слои зависят от `cu_count`: для библиотек `.mod` всегда 16 (`In(15−n)`); для платы `.brd` —
из `$GENERAL LayerCount` (9.0:686-690) или по числу медных бит `EnabledLayers` (9.0:733). Примеры
(`layers.json → legacy_inner_by_cu_count`): cu=4: 1→In2, 2→In1, 3..14→F.Cu; cu=2: 1..14→F.Cu (!).

### 5.3 `leg_mask2new(cu_count, mask)` — маска площадки

`legacy.cpp` 9.0:367-385:
1. если `(mask & 0xFFFF) == 0xFFFF` → **все 32** медных слоя (`LSET::AllCuMask()`, включая In15..In30, которых в
   старом формате не было), биты 0..15 сбрасываются;
2. каждый оставшийся бит `i` → `leg_layer2new(cu_count, i)` (битовые 29–31 → `Cmts.User`).

**Никакие биты не выбрасываются**, в том числе шелкография: маска `00E0FFFF` (STD) даёт 32 медных + `F.SilkS` +
`B.Mask` + `F.Mask` и пишется как `(layers "*.Cu" "*.Mask" "F.SilkS")`, а **не** `(layers "*.Cu" "*.Mask")`.

Маски по умолчанию 2011 (bzr2986 `pcbnew/class_pad.h:15-27`) и результат:

| `At <тип> N <mask>` | Состав (2011) | Слои после импорта | 6.0–8.0 пишется | 9.0.0–9.0.5 | 9.0.6+/master |
|---|---|---|---|---|---|
| `STD` `00E0FFFF` | ALL_CU + SilkS_Front + Mask_Back + Mask_Front | 32 Cu, F.SilkS, B.Mask, F.Mask | `"*.Cu" "*.Mask" "F.SilkS"` | то же | то же |
| `SMD` `00808000` | Front + Mask_Front | F.Cu, F.Mask | `"F.Cu" "F.Mask"` | то же | то же |
| `CONN` `00888000` | Front + SoldP_Front + Mask_Front | F.Cu, F.Paste, F.Mask | `"F.Cu" "F.Paste" "F.Mask"` | `"F.Cu" "F.Mask" "F.Paste"` | то же |
| `HOLE` `00E00001` | Back + SilkS_Front + Mask_Back + Mask_Front | B.Cu, F.SilkS, B.Mask, F.Mask | `"*.Mask" "B.Cu" "F.SilkS"` | то же | то же |
| `0000FFFF` | ALL_CU | 32 Cu | `"*.Cu"` | то же | то же |
| `00008001` | Front + Back | F.Cu, B.Cu | `"F&B.Cu"` | `"F&B.Cu"` | `"*.Cu"` |
| `1FFFFFFF` | всё | 32 Cu + 8 tech + Dwgs, Cmts, Eco1, Eco2, Edge.Cuts | `"*.Cu" "*.Adhes" "*.Paste" "*.SilkS" "*.Mask" "Dwgs.User" "Cmts.User" "Eco1.User" "Eco2.User" "Edge.Cuts"` | то же | то же |

(Обратите внимание: в 2011 `PAD_SMD_DEFAULT_LAYERS` = без пасты, `PAD_CONN_DEFAULT_LAYERS` = с пастой — наоборот
относительно современных `SMDMask/ConnSMDMask`; диалог 2011 к тому же путал индексы, см.
`kicad-2011-gen/docs/pcbnew-pad-format.md` §3.4.)

Проверено на `tests/fixtures/legacy_mod/My_lib.mod` (24× `At STD N 00E0FFFF`, 2× `At HOLE N 00E00001`) скриптом
`legacy_expected.py` — результат `(layers "*.Cu" "*.Mask" "F.SilkS")` и `(layers "*.Mask" "B.Cu" "F.SilkS")`.

### 5.4 Прочие правила слоёв при legacy-импорте

- Площадка (`legacy.cpp` 9.0:1489-1513): `At STD|SMD|CONN|HOLE`, иное → PTH; сначала `SetLayerSet(leg_mask2new(...))`,
  затем `SetAttribute(...)` → для HOLE (NPTH) номер площадки стирается, для SMD/CONN с >1 медным слоем остаётся
  один (B.Cu приоритетно), сверло обнуляется (§4.2).
- Графика `DS/DC/DA/DP` (9.0:1713-1720): если слой `< 0` или `> 28` → 21 (`F.SilkS`); медные 0..15 допускаются.
- Текст `T<n>` (9.0:1797-1807): `< 0` → 0, `> 28` → 28 (`Edge.Cuts`), `0` → 20 (`B.SilkS`), `15` → 21 (`F.SilkS`),
  `1..14` → 21 (`F.SilkS`).

---

## 6. Цвета слоёв

### 6.1 Источник и правила

- Темы: `common/settings/builtin_color_themes.h` 9.0 — `s_defaultTheme` (:28-284, «KiCad Default»),
  `s_classicTheme` (:307-558, «KiCad Classic»). `CSS_COLOR(r,g,b,a)` = `COLOR4D().FromCSSRGBA` (:26; color4d.cpp
  9.0:577-585). Classic использует именованные цвета `COLOR4D(RED)` и т.п., таблица `colorRefs()` в
  `common/gal/color4d.cpp` 9.0:43-79 хранит компоненты **в порядке B,G,R** (`StructColors` color4d.h 9.0:84-92):
  например `RED` = (B0,G0,R132) → `#840000`, `YELLOW` = `#C2C200`, `BLUE` = `#000084`.
- Hex ниже: `#RRGGBB` при a=1, иначе `#RRGGBBAA`, `AA = round(a·255)`.
- Цвета слоёв платы в 8.0, 9.0 и master **совпадают** (сравнено скриптом `colors_cmp.py`); 8.0 не имеет `User.10+`.
- Слой без записи в теме: `GetDefaultColor` берёт из `s_copperColors` (медь) или `s_userColors` по `layer % size`
  (color_settings.cpp 9.0:408-429, builtin_color_themes.h:287-305).
- Отрисовка (pcb_painter.cpp 9.0): альфа любого слоя платы < 0.2 поднимается до 0.2 (:141-146); **цвет медной
  части площадки = цвет её медного слоя** (`LAYER_PAD_COPPER_START + layer` → `layer`, :248-249); `LAYER_PAD_PLATEDHOLES`
  в 9.0 рисуется **цветом фона** (:153, «not theme-able»), стенки отверстия площадки — цветом `LAYER_VIA_HOLES`
  (:255-257); NPTH — `LAYER_NON_PLATEDHOLES`. В 8.0 в теме был отдельный `LAYER_PADS_TH` = `#E3B72E`
  (8.0 builtin_color_themes.h:162; как 8.0 painter его использует — не проверено); в 9.0 `LAYER_PADS_TH` удалён
  (layer_ids.h 9.0:268 «Deprecated since 9.0»).

### 6.2 Слои платы (тема «KiCad Default», 9.0)

| Слой | Default | RGBA | Classic | Ключ в JSON-теме (color_settings.cpp 9.0:145-240) |
|---|---|---|---|---|
| `F.Cu` | `#C83434` | 200,52,52,1 | `#840000` | `board.copper.f` |
| `In1.Cu` | `#7FC87F` | 127,200,127,1 | `#C2C200` | `board.copper.in1` (… `in30`) |
| `B.Cu` | `#4D7FC4` | 77,127,196,1 | `#008400` | `board.copper.b` |
| `F.Adhes` | `#840084` | 132,0,132,1 | `#840084` | `board.f_adhes` |
| `B.Adhes` | `#000084` | 0,0,132,1 | `#000084` | `board.b_adhes` |
| `F.Paste` | `#B4A09AE6` | 180,160,154,0.9 | `#840000` | `board.f_paste` |
| `B.Paste` | `#00C2C2E6` | 0,194,194,0.9 | `#00C2C2` | `board.b_paste` |
| `F.SilkS` | `#F2EDA1` | 242,237,161,1 | `#008484` | `board.f_silks` |
| `B.SilkS` | `#E8B2A7` | 232,178,167,1 | `#840084` | `board.b_silks` |
| `F.Mask` | `#D864FF66` | 216,100,255,0.4 | `#840084` | `board.f_mask` |
| `B.Mask` | `#02FFEE66` | 2,255,238,0.4 | `#848400` | `board.b_mask` |
| `Dwgs.User` | `#C2C2C2` | 194,194,194,1 | `#C2C2C2` | `board.dwgs_user` |
| `Cmts.User` | `#5994DC` | 89,148,220,1 | `#000084` | `board.cmts_user` |
| `Eco1.User` | `#B4DBD2` | 180,219,210,1 | `#008400` | `board.eco1_user` |
| `Eco2.User` | `#D8C852` | 216,200,82,1 | `#C2C200` | `board.eco2_user` |
| `Edge.Cuts` | `#D0D2CD` | 208,210,205,1 | `#C2C200` | `board.edge_cuts` |
| `Margin` | `#FF26E2` | 255,38,226,1 | `#C200C2` | `board.margin` |
| `F.CrtYd` | `#FF26E2` | 255,38,226,1 | `#C2C2C2` | `board.f_crtyd` |
| `B.CrtYd` | `#26E9FF` | 38,233,255,1 | `#848484` | `board.b_crtyd` |
| `F.Fab` | `#AFAFAF` | 175,175,175,1 | `#848484` | `board.f_fab` |
| `B.Fab` | `#585D84` | 88,93,132,1 | `#000084` | `board.b_fab` |
| `User.1`…`User.45` | цикл, см. ниже | | `#000084` все | `board.user_1` … `board.user_45` |

Внутренняя медь (Default): In1 `#7FC87F`, In2 `#CE7D2C`, In3 `#4FCBCB`, In4 `#DB628B`, In5 `#A7A5C6`, In6 `#28CCD9`,
In7 `#E8B2A7`, In8 `#F2EDA1`, In9 `#8DCB81`, In10 `#ED7C33`, In11 `#5BC3EB`, In12 `#F76F8E`, далее с In13 цикл из
7 цветов `#A7A5C6, #28CCD9, #E8B2A7, #F2EDA1, #ED7C33, #5BC3EB, #F76F8E` (In13…In19, In20…In26, In27…In30).
User.N (Default): User.1–8 цикл `#C2C2C2, #5994DC, #B4DBD2, #D8C852`; `User.9 = #E8B2A7`; User.10–45 продолжают цикл
с `#5994DC` (User.10 `#5994DC`, 11 `#B4DBD2`, 12 `#D8C852`, 13 `#C2C2C2`, …, 45 `#C2C2C2`). Полные списки — `layers.json`.

### 6.3 Служебные цвета (не слои платы)

| Ключ kicadfp (`colors_ui`) | Слой KiCad | Default | Classic | Ключ JSON-темы |
|---|---|---|---|---|
| `background` | `LAYER_PCB_BACKGROUND` | `#001023` | `#000000` | `board.background` |
| `grid` | `LAYER_GRID` | `#848484` | `#848484` | `board.grid` |
| `grid_axes` | `LAYER_GRID_AXES` | `#C2C2C2` | `#000084` | `board.grid_axes` |
| `hole` | `LAYER_PAD_PLATEDHOLES` (в 9.0 painter подменяет цветом фона, §6.1) | `#C2C200` | `#C2C200` | `board.pad_plated_hole` |
| `npth` | `LAYER_NON_PLATEDHOLES` | `#1AC4D2` | `#C2C200` | `board.plated_hole` (sic) |
| `via_holes` (= цвет стенок отверстий pad в 9.0) | `LAYER_VIA_HOLES` | `#E3B72E` | `#806600CC` | `board.via_hole` |
| `pad_th` | `LAYER_PADS_TH` (только 8.0) | `#E3B72E` | `#C2C200` | — |
| `selection` | `LAYER_SELECT_OVERLAY` | `#04FF43` | `#00FF00` | нет ключа (не настраивается в 9.0 color_settings.cpp:123-143) |
| `anchor` | `LAYER_ANCHOR` | `#FF26E2` | `#000084` | `board.anchor` |
| `cursor` | `LAYER_CURSOR` | `#FFFFFF` | `#FFFFFF` | `board.cursor` |
| `aux_items` | `LAYER_AUX_ITEMS` | `#FFFFFF` | `#FFFFFF` | `board.aux_items` |
| `locked_shadow` | `LAYER_LOCKED_ITEM_SHADOW` | `#FF26E280` | `#00008499` | `board.locked_shadow` |
| `conflicts_shadow` | `LAYER_CONFLICTS_SHADOW` | `#FF000580` | `#84000080` | `board.conflicts_shadow` |
| `drc_error` / `drc_warning` | `LAYER_DRC_ERROR` / `_WARNING` | `#D75B6BCC` / `#FFD042CC` | `#FF0000CC` / `#00FF00CC` | `board.drc_error` / `board.drc_warning` |
| `ratsnest` | `LAYER_RATSNEST` | `#00F8FF59` | `#FFFFFF` | `board.ratsnest` |
| `drawingsheet` | `LAYER_DRAWINGSHEET` | `#C872AB` | `#480000` | `board.worksheet` |
| `page_limits` | `LAYER_PAGE_LIMITS` | `#848484` | `#848484` | `board.page_limits` |
| `pad_net_names` | `LAYER_PAD_NETNAMES` | `#FFFFFFE6` | `#FFFFFFE6` | `board.pad_net_names` |

Для превью kicadfp: медь площадки — цвет её медного слоя (`F.Cu`/`B.Cu`; для `*.Cu` — верхний видимый медный),
отверстие PTH — `background` (как 9.0) со стенкой `via_holes`, NPTH — `npth`.

---

## 7. Порядок отрисовки

Источник: `GAL_LAYER_ORDER[]` в `pcbnew/pcb_draw_panel_gal.cpp` 9.0:59-358 (8.0:59-217), применяется
`setDefaultLayerOrder()` (9.0:762-777): `SetLayerOrder(layer, i)`. Семантика индекса проверена по коду `VIEW`:
`m_orderedLayers` сортируется по **убыванию** `renderingOrder` (`compareRenderingOrder` view.h 9.0:843-846,
`sortOrderedLayers` view.cpp 9.0:1276-1288) и рисуется в этом порядке (view.cpp 9.0:1011-1018) с глубиной
`SetLayerDepth(renderingOrder)`, где «smaller is closer to the viewer» (graphics_abstraction_layer.h 9.0:418).
Итого: **индекс 0 массива — самый верхний**. (Комментарий `view.h:508` «Lower values are rendered first» вводит в
заблуждение.)

Порядок слоёв платы **снизу вверх** (обращённый массив, только слои платы; `layers.json → draw_order`):

```
B.Fab, B.CrtYd, B.Adhes, B.Paste, B.SilkS, B.Mask, B.Cu,
In30.Cu, In29.Cu, …, In1.Cu,
F.Fab, F.CrtYd, F.Adhes, F.Paste, F.SilkS, F.Mask, F.Cu,
[служебные: отверстия/стенки/якоря/тексты футпринта — выше F.Cu]
User.45, …, User.1, Margin, Edge.Cuts, Eco2.User, Eco1.User, Cmts.User, Dwgs.User
[сверху: DRC-маркеры, SELECT_OVERLAY, GP_OVERLAY, UI]
```

Служебные слои между F.Cu и User.* (сверху вниз, 9.0:133-146): `LAYER_FP_TEXT, LAYER_FP_REFERENCES, LAYER_FP_VALUES,
LAYER_RATSNEST, LAYER_ANCHOR, LAYER_LOCKED_ITEM_SHADOW, LAYER_VIA_HOLES, LAYER_VIA_HOLEWALLS, LAYER_PAD_PLATEDHOLES,
LAYER_PAD_HOLEWALLS, LAYER_NON_PLATEDHOLES, …` — т.е. отверстия рисуются поверх всей F-стороны.
8.0 отличается только отсутствием User.10+ и наличием `LAYER_PADS_TH`/`LAYER_PADS_SMD_FR` над F.Cu (8.0:101-106).

Важно: это порядок **по умолчанию**; активный слой поднимается наверх `SetTopLayer` (pcb_draw_panel_gal.cpp
9.0:540-620), поэтому в редакторе, например, при активном F.SilkS шелкография оказывается над медью. Какой слой
активен по умолчанию в редакторе футпринтов — **не проверено**. Предложение для статического превью kicadfp:
использовать `draw_order` как есть (F.Cu над F.SilkS — как в KiCad без активного слоя), опционально поднимать
выбранный пользователем слой наверх.

---

## 8. Сводка требований к `kicadfp.layers`

1. `canonical(version)` — списки §1.1 (6.0/7.0/8.0 = 60, 9.0/10 = 96); `is_valid_layer(name, version)` — по §2.4.
2. `expand(tokens)` — §3.1 (включая `*In.Cu`, `Inner<i>.Cu`); неизвестное → ошибка валидации (KiCad поставил бы Rescue).
3. `format_layers(set, profile)` — алгоритм §3.2 с учётом порядка id версии, `FB`-правила и кавычек профиля;
   для зон на меди — перечисление без групп.
4. `PAD_LAYER_PRESETS` — множества §4.1 + таблица «как пишется» по профилю.
5. `legacy_mask_to_layers(mask, pad_type)` — §5.3 (+ `cu_count`, по умолчанию 16); для `pad_type` учесть §4.2.
6. `COLORS`, `COLORS_UI`, `DRAW_ORDER` — §6, §7.
7. `flip_layer` — пары §1.1; внутренняя медь не меняется для футпринта (редактор футпринтов имеет 3 медных слоя).

---

## 9. Формат `layers.json`

| Ключ | Содержимое |
|---|---|
| `_source` | ссылки на исходники |
| `canonical` | `{"5.1","6.0","7.0","8.0","9.0","master"}` → список имён в порядке id (= порядок writer) |
| `ids` | `{"5.1","6.0-8.0","9.0+"}` → `{имя: id}` |
| `parser_extra_names_9.0` | `In31.Cu`…`In62.Cu` (§1.3) |
| `copper` | F.Cu, In1..In30, B.Cu |
| `categories` | copper / board_tech / user / footprint / user_defined{6.0-8.0, 9.0+} / rescue / front / back |
| `flip` | пары F↔B |
| `wildcards` | групповое обозначение → слои (все, что принимает парсер) |
| `wildcards_written_order` | порядок групп в writer |
| `old_inner_names` | `Inner<i>.Cu` → `In<15−i>.Cu` |
| `pad_presets` | множества: thru_hole, smd, smd_back, connect, connect_back, np_thru_hole, aperture |
| `pad_presets_as_written` | пресет → {"6.0-8.0","9.0.0-9.0.5","9.0.6+/master"} → список токенов |
| `pad_allowed_non_copper` | не-медные слои, допустимые для pad в UI |
| `legacy_index` | `"0".."31"` → имя (cu_count = 16) |
| `legacy_inner_by_cu_count` | cu ∈ {2,4,6,8,16} → n(1..14) → имя |
| `legacy_mask_bits` | `"0x%08X"` → {bit, macro, name_2011, layer} |
| `legacy_pad_default_masks_2011` | STD/SMD/CONN/HOLE → hex |
| `legacy_mask_examples` | hex → {layers, written{по версиям}} |
| `colors`, `colors_classic` | слой платы → hex (Default / Classic) |
| `colors_rgba` | слой → [r,g,b,a] (Default) |
| `colors_ui`, `colors_ui_classic` | служебные цвета §6.3 |
| `color_json_keys` | ключи JSON-темы KiCad |
| `draw_order` | слои платы 9.0 снизу вверх; `draw_order_8.0` — то же для 8.0 |
| `draw_order_gal_9.0_top_first` | сырой `GAL_LAYER_ORDER` 9.0 (сверху вниз, включая служебные слои) |

---

## 10. Проверено

Скрипты в `scratchpad/research/` (временные, вне репозитория): `check_layers.py`, `gen_layers_json2.py`,
`colors_cmp.py`, `draw_order.py`, `scan_layers.py`, `scan_layers2.py`, `legacy_expected.py`.

1. **Канонические имена из исходников** (`check_layers.py`): разбор enum `PCB_LAYER_ID` + `switch` в `LSET::Name`
   для 5.1/6.0/7.0/8.0 и формулы 9.0 (с assert, что формула совпадает со всеми 21 явными `case` 9.0):
   5.1 — 51 имя, 6.0 = 7.0 = 8.0 — 60 имён (побайтно одинаковые), 9.0 = master — 96 имён; enum 9.0 и master
   идентичны; `canonical["5.1"] == canonical["8.0"][:50] + ["Rescue"]`.
2. **Все токены слоёв в фикстурах известны парсеру своей версии**: 10 наборов, 14 503 файла
   (kfp v6.0.0: 1303, v7.0.0: 1332, v8.0.0: 1377, v9.0.0: 3297, master: 4882; fixtures kicad5: 166, kicad6: 224,
   kicad8: 1377, kicad9: 337, kicad10dev: 208), 650 188 `(layer X)` и 341 860 `(layers …)`; неизвестных имён 0;
   единственный `Rescue` — kfp v9.0.0 `MountingHole_6.4mm_M6_DIN965_Pad_TopBottom.kicad_mod:93`.
3. **Round-trip writer-модели §3.2** на всех `(layers …)` из файлов с `generator pcbnew` (версия→writer:
   20211014→6.0, 20240108→8.0, 20241229→9.0.0–9.0.5, 20260206→9.0.6+/master; зоны — перечисление): парсинг множества
   → форматирование → сравнение с исходными токенами **и их кавычками**: kfp v7.0.0 22 357/22 357,
   v8.0.0 24 443/24 443, v9.0.0 22 483/22 483, master 22 239/22 239, fixtures kicad6 3 594/3 594,
   kicad8 24 443/24 443, kicad9 2 415/2 415, kicad10dev 574/574 — итого 122 548 списков, **0 расхождений**. Это подтверждает порядок по id,
   правило групп, `F&B.Cu`→`*.Cu` в 10.0 (ToolingHole), кавычки 6.0 (wildcards без кавычек, имена в кавычках).
4. **Порядок F.Paste/F.Mask**: 6.0/8.0 pcbnew — всегда `F.Cu F.Paste F.Mask` (12 098 и 13 365 площадок);
   9.0/10.0 pcbnew — `F.Cu F.Mask F.Paste` (11 810 и 17 987); `kicad-footprint-generator` в v9.0.0 пишет
   `F.Cu F.Paste F.Mask` (32 782), в master — `F.Cu F.Mask F.Paste` (102 554) (`scan_layers2.py`).
5. **Legacy**: `legacy_expected.py` на `tests/fixtures/legacy_mod/My_lib.mod` воспроизводит вывод
   `legacy_expected.out` побайтно (diff пуст); 24 STD → `"*.Cu" "*.Mask" "F.SilkS"`, 2 HOLE → `"*.Mask" "B.Cu" "F.SilkS"`.
   Формула `leg_layer2new` сверена в 6.0, 7.0, 9.0, master (одинаковая логика).
6. **Цвета** (`colors_cmp.py`): распарсены обе темы 8.0/9.0/master; 95 слоёв платы в 9.0 (F.Cu…User.45); цвета
   слоёв платы в 8.0 и master совпадают с 9.0 (отличия только в служебных слоях: 8.0 `LAYER_PADS_TH`,
   `LAYER_VIA_THROUGH` и т.п.; master добавил `LAYER_POINTS`, `LAYER_BOARD_OUTLINE_AREA` и др.); проверено
   `RED=#840000`, `BLUE=#000084`, `YELLOW=#C2C200` по BGR-таблице.
7. **Порядок отрисовки** (`draw_order.py`): извлечён `GAL_LAYER_ORDER` 8.0 (248 элементов) и 9.0 (451 элемент);
   семантика «индекс 0 = верх» проверена по коду VIEW (§7).
8. **Пресеты** `PAD::*Mask()` одинаковы в 6.0/8.0/9.0 (текст исходника); варианты записи в `layers.json`
   получены той же writer-моделью, что прошла проверку 3.

## 11. Открытые вопросы

1. KiCad 7.0 (формат 20221018): writer 7.0 изучен по исходнику, но фикстур с `version 20221018` нет — round-trip для
   7.0 не выполнен (ожидается как 8.0 по слоям: всё в кавычках, порядок 6.0–8.0).
2. Какие именно 9.0.x (9.0.6?) впервые пишут `*.Cu` вместо `F&B.Cu` — установлено по тегам 9.0.5 (ещё `F&B.Cu`) и
   9.0.6 (уже `*.Cu`); релизные сборки не проверялись.
3. Квирк 8.0 со `static cu_all` (зависимость от первого вызова в процессе) — выведен из кода, на реальных файлах
   не наблюдался.
4. Где применяется `LSET::ForbiddenFootprintLayers()` и какой слой активен по умолчанию в редакторе футпринтов
   (влияет на фактический порядок отрисовки) — не проверено.
5. Как 8.0 painter использует `LAYER_PADS_TH` (#E3B72E) для цвета PTH-площадок — не проверено (pcb_painter.cpp 8.0
   не скачивался); для 9.0 проверено: медь pad — цвет медного слоя.
6. Графика с `(layers …)` (>1 слоя, 9.0+ shape с solder mask) в фикстурах не встречена — формат взят только из кода
   writer 9.0:1014-1017 / parser 9.0:3138-3140.
7. KiCad 5.1: список имён и writer взяты из 5.1-исходников, кавычки 5.1 — по `Quotes` 5.1 (кавычки только при
   пробелах/скобках/`#`/пустой строке); round-trip на фикстурах kicad5 не делался (там нет `generator`).
