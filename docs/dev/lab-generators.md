# Геометрия типовых корпусов для генераторов kicadfp

Лабораторные корпуса `dip14` / `mlt` / `snp8` и параметрические семейства (DIP, штыревые разъёмы,
выводные резисторы, конденсаторы, диоды, транзисторы TO-92).

Документ — спецификация для реализации `kicadfp/generators/` (`_common.py`, `dip.py`, `pin_header.py`,
`axial.py`, `radial.py`, `transistor.py`, `lab.py`, см. `architecture.md` §1, §11). Все размеры в
миллиметрах, углы в градусах, система координат KiCad: X вправо, **Y вниз**, положительный угол
текста — против часовой стрелки на экране.

Везде различаются два вида утверждений:

* **Факт KiCad** — подтверждён ссылкой `файл:строка` на исходники или конкретным файлом библиотеки
  и проверен скриптом (раздел «Проверено»).
* **Решение kicadfp** — выбор этого проекта там, где KiCad или ТЗ не дают однозначного ответа.
  Помечено словом «Решение».

Источники (пути относительно `scratchpad/`, если не указано иное):

| Обозначение | Что это |
|---|---|
| `ТЗ` | ТЗ kicadfp (`scratchpad/tz.txt`): п. 4.1.3, 8.2, прил. В.2, В.3, Г (сценарий 5) |
| `ЛР` | `/Users/juli/Downloads/Telegram Desktop/bzr2986/kicad-требования-и-задания.md`, §1.3б, §1.5, §3.2 |
| `gen2011` | `/Users/juli/Downloads/Telegram Desktop/kicad-2011-gen/kicadgen/mod.py` (функции `dip`, `two_pad`, `pin_rows`) и `gen_footprints.py` |
| `My_lib.mod` | `tests/fixtures/legacy_mod/My_lib.mod` (побайтно равен `kicad-2011-gen/examples/346_8/My_lib.mod`) |
| `bzr2986` | снапшот исходников KiCad 2011, `/Users/juli/Downloads/Telegram Desktop/bzr2986` |
| `kfp/vX` | клоны `kicad-footprints` тегов v8.0.0, v9.0.0, master; `research/kfp8/` — отдельно скачанные файлы v8 (Diode_THT, TO-92, MountingHole) |
| `KiCad 9.0 <path>` | исходники KiCad ветки 9.0 (`kicad-src/9.0/`, имя файла = путь с `/`→`_`) |
| `klt` | kicad-library-tools (gitlab `kicad/libraries/kicad-library-tools`, ветка `main`), копии в `research/gen/` |
| `KLC Fx.y` | KiCad Library Conventions, gitlab `kicad/libraries/klc`, `content/footprint/Fx/Fx.y.adoc`, копии в `research/klc/adoc/` |

Скрипты проверки: `research/labgen/` (`families_v8.py`, `hatch_check.py`, `spec_impl.py`,
`check_spec.py`, `bulk_spec.py`, `emit.py`). `spec_impl.py` — эталонная реализация правил этого
документа (не код kicadfp); таблицы ниже сгенерированы им.

---

## 1. Общие правила для всех генераторов

### 1.1. Константы

| Параметр | Значение | Источник |
|---|---|---|
| Толщина линий F.SilkS | 0.12 | KLC F5.1 (`F5.1.adoc:17-20`: 0.10…0.15, номинал 0.12); `klt config_KLCv3.0.yaml:40`, `klc_constants.py` `KLC_SILK_WIDTH = 0.12` |
| Толщина линий F.Fab | 0.10 | KLC F5.2 (`F5.2.adoc:15`); `footprint_global_properties.py:15` `lw_fab = 0.1` |
| Толщина линий F.CrtYd | 0.05 | KLC F5.3 (`F5.3.adoc:19`); `footprint_global_properties.py:16` |
| Шрифт Reference / Value / `${REFERENCE}` | size 1 × 1, thickness 0.15 | KLC F5.1 (`F5.1.adoc:15-16`), F5.2 (`:23-25`, `:33-35`); все файлы семейств ниже |
| Отступ courtyard | 0.25 (по умолчанию), 0.5 (разъёмы) | KLC F5.3 (`F5.3.adoc:28-30`); `config_KLCv3.0.yaml:55-57` |
| Сетка courtyard | 0.01, округление **наружу** | KLC F5.3 (`F5.3.adoc:20`); `config_KLCv3.0.yaml:54`; `drawing_tools.py:66-80` (`courtyardFromBoundingBox`: left/top — вниз, right/bottom — вверх) |
| Зазор шелкография → медь | 0.2 (от края линии до края площадки) | KLC F5.1 (`F5.1.adoc:21-23`); `config_KLCv3.0.yaml:41` `silk_pad_clearance: 0.2` |
| Смещение оси линии шелкографии от меди | 0.2 + 0.12/2 = **0.26** | `klt src/kilibs/config/global_config.py:392-411` (`silk_pad_offset = silk_pad_clearance + silk_line_width/2`) |
| Минимальная длина отрезка шелкографии | 0.2 | `config_KLCv3.0.yaml:43` `silk_line_length_min: 0.2` |
| Отступ текста от контура | 1.0 (центр текста на 1 мм дальше крайней линии) | `footprint_global_properties.py:19` `txt_offset = 1`; `footprint_scripts_DIP.py:141,150`; `footprint_scripts_resistorlike.py:235,243` |

Про «0.11»: `silk_fab_offset: 0.11` (`config_KLCv3.0.yaml:42`) — это расстояние между осями линий
F.SilkS и F.Fab в новых генераторах (master-библиотека, например PinHeader: шелкография на
−1.38 при корпусе −1.27). К зазору до площадок оно отношения не имеет. В библиотеках v8/v9
фактические смещения шелкографии от F.Fab: **0.06** у DIP и штыревых разъёмов, **0.12** у выводных
R/C/D и радиальных конденсаторов (проверено, §4).

### 1.2. Состав и порядок узлов генерируемого корпуса

Каждый генератор возвращает `Footprint` версии `DEFAULT_VERSION` (20241229) с узлами в том порядке,
в котором их пишет KiCad 9 (`KiCad 9.0 pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp:1083-1290`):

1. `(footprint "<name>"` `(version 20241229)` `(generator "kicadfp")` `(generator_version "0.1")` `(layer "F.Cu")`
2. `(descr "…")`, `(tags "…")` — только если непустые (`:1134-1138`).
3. `(property "Reference" "REF**" (at x y a) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))`
4. `(property "Value" "<name>" (at x y a) (layer "F.Fab") (effects …))`. Других свойств
   (Footprint/Datasheet/Description) генераторы не создают — так же выглядят файлы, созданные
   kicad-footprint-generator в библиотеке v9 (`kfp/v9.0.0/Package_DIP.pretty/DIP-14_W7.62mm.kicad_mod`:
   `property property attr fp_line …`).
5. `(attr through_hole)` — у всех корпусов этого документа (`:1213-1242`; KLC F7.1).
6. Графика, отсортированная как `FOOTPRINT::cmp_drawings` (`KiCad 9.0 pcbnew/footprint.cpp:3774-3848`):
   сначала все фигуры (`PCB_SHAPE_T`), затем тексты `fp_text` (`PCB_TEXT_T`; `include/core/typeinfo.h:88-92`);
   внутри — по номеру слоя (`include/layer_ids.h`: F.SilkS = 5, Cmts.User = 19, F.CrtYd = 31, F.Fab = 35),
   затем по типу фигуры (`include/eda_shape.h:42-51`: SEGMENT 0 < RECTANGLE 1 < ARC 2 < CIRCLE 3 < POLY 4),
   затем start.x, start.y, end.x, end.y (в нм), затем ширина. Для окружности «end» — точка на окружности.
7. Площадки, отсортированные как `FOOTPRINT::cmp_pads` (`footprint.cpp:3851-3894`): `StrNumCmp` по номеру
   (`common/string_utils.cpp:804`, группы цифр сравниваются как числа), затем x, затем y. Пустой номер
   (`""`, монтажное отверстие) идёт **первым** — так в файлах KiCad 9 (`kfp/v9.0.0/Package_TO_SOT_THT.pretty/TO-220-11_P3.4x5.08mm_StaggerOdd_Lead8.45mm_TabDown.kicad_mod`: `(pad "" np_thru_hole …` перед `(pad "1" …`).
8. `(embedded_fonts no)` — как пишет KiCad 9 (`:1298-1299`).
9. 3D-модель — **Решение:** не добавляется (параметра `model` у генераторов нет на этапе 1).

Порядок нужен, чтобы пересохранение сгенерированного файла в KiCad 9 не переставляло узлы
(на результат загрузки порядок не влияет). `uuid` — по общим правилам kicadfp (`architecture.md`);
**Решение (рекомендация):** детерминированный `uuid5` от `(имя корпуса, вид, индекс)`, чтобы повторная
генерация давала тот же файл.

Пример полного текста (lab_mlt, без uuid) — §2.4.

### 1.3. Площадки

| Вид | Узел |
|---|---|
| Сигнальная THT | `(pad "N" thru_hole <shape> (at x y) (size sx sy) (drill d) (layers "*.Cu" "*.Mask"))` |
| Монтажное отверстие | `(pad "" np_thru_hole circle (at x y) (size D D) (drill D) (layers "*.Cu" "*.Mask"))` |

* Типы и формы — ключевые слова писателя KiCad 9 (`pcb_io_kicad_sexpr.cpp:1441-1446` формы
  `circle`/`rect`/`oval`/`roundrect`; `:1459-1462` типы `thru_hole`/`np_thru_hole`; `:1487` `(pad %s %s %s` с номером в кавычках).
* Слои `*.Cu *.Mask` у THT — во всех файлах семейств §3 (проверено); у `np_thru_hole` — так же:
  в `kfp/v9.0.0` 96 круглых NPTH из 97 имеют `(layers "*.Cu" "*.Mask")`, `MountingHole_3mm.kicad_mod`:
  `(pad "" np_thru_hole circle (at 0 0) (size 3 3) (drill 3) (layers "*.Cu" "*.Mask"))`; у NPTH size = drill.
* Первая площадка: KLC F7.3 (`F7.3.adoc:5-15`) — у полярных THT `rect` или `roundrect`
  (радиус 25 %, не более 0.25 мм), остальные `circle`/`oval`; у неполярных (резисторы) все формы одинаковые
  (в библиотеке v8 у R_Axial: `circle` + `oval`, 30/30 файлов).
* Поворот площадок у всех корпусов этого документа 0 (`(at x y)` без угла).

### 1.4. Courtyard

Прямоугольник `fp_rect` на F.CrtYd (у полярного радиального конденсатора — `fp_circle`):

```
bbox = объединение( bbox всех площадок (включая np_thru_hole), bbox контура F.Fab )
x1 = floor_g(bbox.x1 - off),  y1 = floor_g(bbox.y1 - off)
x2 = ceil_g (bbox.x2 + off),  y2 = ceil_g (bbox.y2 + off)
floor_g(v) = floor(v/0.01 + 1e-6)·0.01,  ceil_g(v) = ceil(v/0.01 - 1e-6)·0.01
```

`off` = 0.25 (KLC F5.3 п.5), 0.5 для разъёмов (п.7). Для DIP/осевых/дисковых формула эквивалентна
формулам KiCad (`footprint_scripts_DIP.py:65-83`, `footprint_scripts_resistorlike.py:114-117,1285-1286`).

Факт KiCad: в библиотеке v8 courtyard писался четырьмя `fp_line` и округлялся «от нуля» без защиты от
погрешности float: из 312 проверенных файлов (DIP, PinHeader v8+v9, R/C/D axial) 272 — на сетке 0.05,
40 — на сетке 0.01. Поэтому, например, у `DIP-14_W7.62mm` v8 courtyard `-1.1 -1.55 … 8.7 16.8`, у того же
файла v9 (`fp_rect`, сетка 0.01) `-1.06 -1.53 … 8.67 16.77` (−1.05 и 16.76 «съехали» из‑за float),
а по правилу kicadfp — `-1.05 -1.52 … 8.67 16.76`. **Решение:** kicadfp использует округление с защитой
1e-6; расхождение с файлами KiCad ≤ 0.05 мм допустимо в тестах.

### 1.5. Обрезка шелкографии у площадок (keepout)

**Решение** (основано на `klt drawing_tools.py:111-170` `getKeepoutsForPads` и KLC F5.1):

* для каждой площадки (включая `np_thru_hole`) строится зона запрета:
  `circle` → круг радиуса `max(sx, sy)/2 + 0.26`; любая другая форма → прямоугольник площадки,
  расширенный на 0.26 с каждой стороны;
* из каждого `fp_line` шелкографии вырезаются части, ось которых лежит **внутри** зоны
  (граница зоны допускается); из `fp_arc` — аналогично по углу; окружность, пересекающая зоны,
  заменяется дугами `fp_arc(start, mid, end)` (обход начинается с первого угла внутри зоны,
  середина — mid);
* оставшиеся куски короче 0.2 мм отбрасываются (кроме нетронутого исходного отрезка).

Результат: зазор «край линии — край меди» ≥ 0.2 (проверено для всех лабораторных корпусов, §4).
Исключения, где kicadfp повторяет KiCad буквально: штриховка полярного конденсатора (§3.6,
прямоугольные зоны с запасом 0.24) и DIP/штыревые разъёмы (контур строится формулой и площадок
не касается).

---

## 2. Часть 1. Лабораторные корпуса dip14, mlt, snp8 (эталон приёмки, ТЗ сценарий 5)

### 2.1. Требования

ТЗ, прил. Г, сценарий 5: «Сгенерировать dip14, mlt, snp8 по параметрам лабораторной работы, открыть
в KiCad → площадки 1,3 мм, отверстия 0,8 мм, первая площадка квадратная, шаг и контур соответствуют
заданию». ТЗ 8.2: «генерацию корпусов dip14, mlt, snp8 из лабораторных работ и сравнение с корпусами,
созданными вручную».

ЛР §1.5, §3.2: сетка 1.25 мм; площадки по умолчанию круглые 1.3 × 1.3, отверстие 0.8, тип
стандартный сквозной; первая площадка квадратная. ЛР §1.3б: все размеры корпусов кратны сетке
1.25 без округлений (2.5 = 2 клетки, 5 = 4, 7.5 = 6, 12.5 = 10, 25 = 20).

| Корпус | Требование (ЛР §3.2.x) |
|---|---|
| dip14 | 14 площадок, 2 ряда по 7, нумерация «U»: 1 слева вверху → вниз до 7, 8 справа внизу → вверх до 14; шаг 2.5; ряды 7.5 (по центрам); контур — прямоугольник шириной 5 между рядами, ключ — полукруглая выемка сверху; верхний/нижний отступ до контура 1.25; Ref сверху, Val внутри вертикально |
| mlt | 2 площадки, расстояние 10; контур 7.5 × 2.5 по центру, выводные линии от площадок к контуру; Ref сверху, Val снизу |
| snp8 | 8 площадок, 2 ряда по 4, шаг 2.5, ряды 5; первая квадратная слева вверху; контур 12.5 × 25 справа, правый ряд площадок на левой стороне контура; два монтажных отверстия Ø3 на вертикальной оси контура, центр нижнего в 2.5 от нижнего края, верхнее симметрично; не электрические; Ref сверху, Val снизу. **Неоднозначно:** нумерация и вертикальное положение ряда |

### 2.2. Общие решения для lab-генераторов

| # | Вопрос | Решение kicadfp | Основание / альтернатива |
|---|---|---|---|
| L1 | Начало координат | `origin="center"` (по умолчанию): центр блока площадок, как в `gen2011` и `My_lib.mod`; `origin="pin1"` сдвигает всё на −(x₁, y₁) площадки 1 | KLC F7.2 требует якорь в площадке 1 для THT (`F7.2.adoc:5`); по умолчанию выбран центр, чтобы генерация совпадала с `My_lib.mod` (ТЗ 8.2, сценарий 10) |
| L2 | Площадки | `thru_hole`, 1.3 × 1.3, drill 0.8, №1 `rect`, остальные `circle`, слои `"*.Cu" "*.Mask"` | ЛР §1.5; ТЗ сценарий 5 |
| L3 | Ширина линий шелкографии | 0.12 | KLC F5.1. В `gen2011` было 0.15 (`mod.py:809`, в `My_lib.mod` 59 деци-мил = 0.14986) |
| L4 | Тексты | Reference `"REF**"` на F.SilkS; Value = имя корпуса (`"dip14"` …) на F.Fab; шрифт 1 × 1, толщина 0.15 | KLC F5.1/F5.2. В `My_lib.mod`: `REF**`/`VAL**`, оба на слое 21 (F.SilkS), 394 × 394 деци-мил (1.00076 мм), толщина 59 (0.14986). Умолчания KiCad 2011: `TxtModV/TxtModH` = 500 деци-мил = 1.27 мм, `TxtModW` = 100 (0.254) (`bzr2986 pcbnew/pcbnew_config.cpp:213-218`); конструктор `TEXTE_MODULE` — 400/120 (`pcbnew/class_text_mod.cpp:33-34`) |
| L5 | Отступ контура и текстов | 1.25 (одна клетка): контур на 1.25 дальше крайнего центра площадки по вертикали (dip14), текст на 1.25 от контура | ЛР §3.2.1; `gen2011 mod.py:800` `SILK_CLEARANCE_MM = 1.25` (для mlt/snp8 — то же значение) |
| L6 | Шелкография поверх площадок | `clip=True` (по умолчанию): обрезка по §1.5. `clip=False` — линии как в задании/`My_lib.mod` | У mlt выводные линии начинаются в центре площадок, у snp8 левая сторона контура проходит через площадки 5–8 (зазор −0.71). KLC F5.1 запрещает шелкографию на меди |
| L7 | F.Fab | Прямоугольник корпуса `fp_rect` (тот же, что контур задания), у mlt ещё выводные линии F.Fab от центров площадок к корпусу | KLC F5.2 п.1; в `My_lib.mod` слоя F.Fab нет |
| L8 | F.CrtYd | `fp_rect` по §1.4, отступ 0.25 (dip14, mlt), 0.5 (snp8 — разъём) | KLC F5.3 п.5, п.7 |
| L9 | `${REFERENCE}` на F.Fab | **не создаётся** | У dip14 место в центре корпуса занято вертикальным Value (требование ЛР); для единообразия у всех трёх lab-корпусов его нет. Отклонение от `architecture.md` §11 |
| L10 | Атрибут | `(attr through_hole)` | KLC F7.1 |
| L11 | descr / tags | как в `My_lib.mod` (`Cd`/`Kw`): см. таблицы | `My_lib.mod`, `gen2011 examples/346_8.yaml` |

Сигнатуры (`kicadfp/generators/lab.py`):

```python
def lab_dip14(name: str = "dip14", pins: int = 14, pitch: float = 2.5, row_pitch: float = 7.5,
              body_width: float = 5.0, pad_size: float = 1.3, drill: float = 0.8,
              notch_radius: float = 0.75, clip: bool = True, origin: str = "center") -> Footprint
def lab_mlt(name: str = "mlt", pitch: float = 10.0, body_length: float = 7.5, body_width: float = 2.5,
            pad_size: float = 1.3, drill: float = 0.8, clip: bool = True, origin: str = "center") -> Footprint
def lab_snp8(name: str = "snp8", rows: int = 2, per_row: int = 4, pitch: float = 2.5, row_pitch: float = 5.0,
             body_width: float = 12.5, body_height: float = 25.0, hole: float = 3.0, hole_inset: float = 2.5,
             pads_offset_y: float = 0.0, numbering: str = "by_row", pad_size: float = 1.3, drill: float = 0.8,
             clip: bool = True, origin: str = "center") -> Footprint
```

`origin` ∈ {`"center"`, `"pin1"`}; `numbering` ∈ {`"by_row"`, `"zigzag"`}. Все значения по умолчанию
совпадают с `gen2011` (`mod.py:860,895,918`) и ТЗ ЛР §3.2.

### 2.3. dip14

Формулы (n = pins/2, y₀ = (n−1)·pitch/2, bx = body_width/2, by = y₀ + 1.25, r = notch_radius):

* площадка i = 1…n: (−row_pitch/2, −y₀ + (i−1)·pitch); площадка n+j, j = 1…n: (+row_pitch/2, y₀ − (j−1)·pitch);
  №1 `rect`, остальные `circle` (нумерация «U» = против часовой стрелки при виде сверху, как у KiCad DIP);
* F.SilkS: верхняя сторона разорвана выемкой: (−bx,−by)→(−r,−by) и (r,−by)→(bx,−by); стороны
  (bx,−by)→(bx,by), (bx,by)→(−bx,by), (−bx,by)→(−bx,−by); дуга выемки **внутрь корпуса**
  start (r, −by) mid (0, −by + r) end (−r, −by) — как `DIPRectT` в KiCad (`klt drawing_tools.py:943-970`,
  в библиотеке `DIP-14_W7.62mm`: start (4.81,−1.33) mid (3.81,−0.33) end (2.81,−1.33));
* F.Fab: `fp_rect` (−bx,−by)–(bx,by); F.CrtYd: §1.4 с off = 0.25;
* Reference (0, −(by + 1.25), 0°); Value (0, 0, **90°**).

Радиус выемки 0.75 — значение `gen2011` (`mod.py:812`, «не задан в ТЗ численно»); концы выемки
(±0.75) — единственные точки lab-корпусов вне сетки 1.25.

Ожидаемый результат `lab_dip14()`:

| # | номер | тип | форма | x | y | size | drill | layers |
|---|---|---|---|---|---|---|---|---|
| 1 | `"1"` | `thru_hole` | `rect` | -3.75 | -7.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 2 | `"2"` | `thru_hole` | `circle` | -3.75 | -5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 3 | `"3"` | `thru_hole` | `circle` | -3.75 | -2.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 4 | `"4"` | `thru_hole` | `circle` | -3.75 | 0 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 5 | `"5"` | `thru_hole` | `circle` | -3.75 | 2.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 6 | `"6"` | `thru_hole` | `circle` | -3.75 | 5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 7 | `"7"` | `thru_hole` | `circle` | -3.75 | 7.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 8 | `"8"` | `thru_hole` | `circle` | 3.75 | 7.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 9 | `"9"` | `thru_hole` | `circle` | 3.75 | 5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 10 | `"10"` | `thru_hole` | `circle` | 3.75 | 2.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 11 | `"11"` | `thru_hole` | `circle` | 3.75 | 0 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 12 | `"12"` | `thru_hole` | `circle` | 3.75 | -2.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 13 | `"13"` | `thru_hole` | `circle` | 3.75 | -5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 14 | `"14"` | `thru_hole` | `circle` | 3.75 | -7.5 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |

| узел | слой | ширина | геометрия |
|---|---|---|---|
| `fp_line` | `F.SilkS` | 0.12 | start (-2.5, -8.75) end (-0.75, -8.75) |
| `fp_line` | `F.SilkS` | 0.12 | start (0.75, -8.75) end (2.5, -8.75) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, -8.75) end (2.5, 8.75) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, 8.75) end (-2.5, 8.75) |
| `fp_line` | `F.SilkS` | 0.12 | start (-2.5, 8.75) end (-2.5, -8.75) |
| `fp_arc` | `F.SilkS` | 0.12 | start (0.75, -8.75) mid (0, -8) end (-0.75, -8.75) |
| `fp_rect` | `F.Fab` | 0.1 | start (-2.5, -8.75) end (2.5, 8.75) |
| `fp_rect` | `F.CrtYd` | 0.05 | start (-4.65, -9) end (4.65, 9) |

| узел | текст | at (x, y, угол) | слой | size | thickness |
|---|---|---|---|---|---|
| `property "Reference"` | `REF**` | 0 -10 0 | `F.SilkS` | 1 × 1 | 0.15 |
| `property "Value"` | `dip14` | 0 0 90 | `F.Fab` | 1 × 1 | 0.15 |

descr `"Корпус К555ТВ6 DIP14"`, tags `"dip14 K555TB6"`. Минимальный зазор шелкография–медь 0.54
(обрезка не срабатывает).

### 2.4. mlt

Формулы (x = pitch/2, bx = body_length/2, by = body_width/2):

* площадки: 1 `rect` (−x, 0), 2 `circle` (x, 0);
* F.SilkS: прямоугольник четырьмя `fp_line` (−bx,−by)→(bx,−by)→(bx,by)→(−bx,by)→(−bx,−by);
  выводные линии (−x,0)→(−bx,0) и (bx,0)→(x,0), **после обрезки** §1.5: (−x + 0.65 + 0.26, 0)→(−bx, 0)
  (прямоугольная зона площадки 1) и (bx, 0)→(x − 0.91, 0) (круглая зона площадки 2);
* F.Fab: `fp_rect` (−bx,−by)–(bx,by) и выводные линии (−x,0)–(−bx,0), (bx,0)–(x,0) (как `R_Axial` KiCad);
* Reference (0, −(by + 1.25)); Value (0, by + 1.25).

| # | номер | тип | форма | x | y | size | drill | layers |
|---|---|---|---|---|---|---|---|---|
| 1 | `"1"` | `thru_hole` | `rect` | -5 | 0 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 2 | `"2"` | `thru_hole` | `circle` | 5 | 0 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |

| узел | слой | ширина | геометрия |
|---|---|---|---|
| `fp_line` | `F.SilkS` | 0.12 | start (-3.75, -1.25) end (3.75, -1.25) |
| `fp_line` | `F.SilkS` | 0.12 | start (3.75, -1.25) end (3.75, 1.25) |
| `fp_line` | `F.SilkS` | 0.12 | start (3.75, 1.25) end (-3.75, 1.25) |
| `fp_line` | `F.SilkS` | 0.12 | start (-3.75, 1.25) end (-3.75, -1.25) |
| `fp_line` | `F.SilkS` | 0.12 | start (-4.09, 0) end (-3.75, 0) |
| `fp_line` | `F.SilkS` | 0.12 | start (3.75, 0) end (4.09, 0) |
| `fp_rect` | `F.Fab` | 0.1 | start (-3.75, -1.25) end (3.75, 1.25) |
| `fp_line` | `F.Fab` | 0.1 | start (-5, 0) end (-3.75, 0) |
| `fp_line` | `F.Fab` | 0.1 | start (3.75, 0) end (5, 0) |
| `fp_rect` | `F.CrtYd` | 0.05 | start (-5.9, -1.5) end (5.9, 1.5) |

| узел | текст | at (x, y, угол) | слой | size | thickness |
|---|---|---|---|---|---|
| `property "Reference"` | `REF**` | 0 -2.5 0 | `F.SilkS` | 1 × 1 | 0.15 |
| `property "Value"` | `mlt` | 0 2.5 0 | `F.Fab` | 1 × 1 | 0.15 |

descr `"Корпус резистора МЛТ"`, tags `"mlt resistor"`. С `clip=False` выводные линии шелкографии —
(−5,0)→(−3.75,0) и (3.75,0)→(5,0), как в `My_lib.mod`.

Полный текст `lab_mlt()` в стиле KiCad 9 (порядок §1.2, форматирование — порт `Prettify` 9.0
`research/prettify.py`; uuid опущены):

```
(footprint "mlt"
	(version 20241229)
	(generator "kicadfp")
	(generator_version "0.1")
	(layer "F.Cu")
	(descr "Корпус резистора МЛТ")
	(tags "mlt resistor")
	(property "Reference" "REF**"
		(at 0 -2.5 0)
		(layer "F.SilkS")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(property "Value" "mlt"
		(at 0 2.5 0)
		(layer "F.Fab")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(attr through_hole)
	(fp_line
		(start -4.09 0)
		(end -3.75 0)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_line
		(start -3.75 -1.25)
		(end 3.75 -1.25)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_line
		(start -3.75 1.25)
		(end -3.75 -1.25)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_line
		(start 3.75 -1.25)
		(end 3.75 1.25)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_line
		(start 3.75 0)
		(end 4.09 0)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_line
		(start 3.75 1.25)
		(end -3.75 1.25)
		(stroke
			(width 0.12)
			(type solid)
		)
		(layer "F.SilkS")
	)
	(fp_rect
		(start -5.9 -1.5)
		(end 5.9 1.5)
		(stroke
			(width 0.05)
			(type solid)
		)
		(fill no)
		(layer "F.CrtYd")
	)
	(fp_line
		(start -5 0)
		(end -3.75 0)
		(stroke
			(width 0.1)
			(type solid)
		)
		(layer "F.Fab")
	)
	(fp_line
		(start 3.75 0)
		(end 5 0)
		(stroke
			(width 0.1)
			(type solid)
		)
		(layer "F.Fab")
	)
	(fp_rect
		(start -3.75 -1.25)
		(end 3.75 1.25)
		(stroke
			(width 0.1)
			(type solid)
		)
		(fill no)
		(layer "F.Fab")
	)
	(pad "1" thru_hole rect
		(at -5 0)
		(size 1.3 1.3)
		(drill 0.8)
		(layers "*.Cu" "*.Mask")
	)
	(pad "2" thru_hole circle
		(at 5 0)
		(size 1.3 1.3)
		(drill 0.8)
		(layers "*.Cu" "*.Mask")
	)
	(embedded_fonts no)
)
```

### 2.5. snp8

Формулы (y₀ = (per_row−1)·pitch/2, xs = (rows−1)·row_pitch, L = xs/2, R = L + body_width, cx = (L+R)/2,
by = body_height/2, dy = pads_offset_y):

* площадки ряда c = 0…rows−1, позиции k = 0…per_row−1: (−xs/2 + c·row_pitch, −y₀ + k·pitch + dy);
  номер `by_row`: c·per_row + k + 1 (1–4 левый ряд сверху вниз, 5–8 правый); `zigzag`: k·rows + c + 1
  (как `PinHeader_2xNN` KiCad); №1 `rect`, остальные `circle`;
* монтажные отверстия: `np_thru_hole`, номер `""`, `circle`, size = drill = hole, в (cx, −(by − hole_inset))
  и (cx, by − hole_inset); слои `"*.Cu" "*.Mask"` (§1.3);
* контур задания: прямоугольник (L,−by)–(R,by); левая сторона совпадает с правым рядом площадок (x = L);
* F.SilkS: 4 стороны `fp_line` (верх, правая, низ, левая), левая сторона после обрезки §1.5 разбита
  на 5 кусков; F.Fab: `fp_rect` контура; F.CrtYd: §1.4 с off = 0.5 (отверстия входят в bbox);
* Reference (cx, −(by + 1.25)); Value (cx, by + 1.25).

Ожидаемый результат `lab_snp8()`:

| # | номер | тип | форма | x | y | size | drill | layers |
|---|---|---|---|---|---|---|---|---|
| 1 | `""` | `np_thru_hole` | `circle` | 8.75 | -10 | 3 × 3 | 3 | `"*.Cu" "*.Mask"` |
| 2 | `""` | `np_thru_hole` | `circle` | 8.75 | 10 | 3 × 3 | 3 | `"*.Cu" "*.Mask"` |
| 3 | `"1"` | `thru_hole` | `rect` | -2.5 | -3.75 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 4 | `"2"` | `thru_hole` | `circle` | -2.5 | -1.25 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 5 | `"3"` | `thru_hole` | `circle` | -2.5 | 1.25 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 6 | `"4"` | `thru_hole` | `circle` | -2.5 | 3.75 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 7 | `"5"` | `thru_hole` | `circle` | 2.5 | -3.75 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 8 | `"6"` | `thru_hole` | `circle` | 2.5 | -1.25 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 9 | `"7"` | `thru_hole` | `circle` | 2.5 | 1.25 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |
| 10 | `"8"` | `thru_hole` | `circle` | 2.5 | 3.75 | 1.3 × 1.3 | 0.8 | `"*.Cu" "*.Mask"` |

| узел | слой | ширина | геометрия |
|---|---|---|---|
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, -12.5) end (15, -12.5) |
| `fp_line` | `F.SilkS` | 0.12 | start (15, -12.5) end (15, 12.5) |
| `fp_line` | `F.SilkS` | 0.12 | start (15, 12.5) end (2.5, 12.5) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, 12.5) end (2.5, 4.66) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, 2.84) end (2.5, 2.16) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, 0.34) end (2.5, -0.34) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, -2.16) end (2.5, -2.84) |
| `fp_line` | `F.SilkS` | 0.12 | start (2.5, -4.66) end (2.5, -12.5) |
| `fp_rect` | `F.Fab` | 0.1 | start (2.5, -12.5) end (15, 12.5) |
| `fp_rect` | `F.CrtYd` | 0.05 | start (-3.65, -13) end (15.5, 13) |

| узел | текст | at (x, y, угол) | слой | size | thickness |
|---|---|---|---|---|---|
| `property "Reference"` | `REF**` | 8.75 -13.75 0 | `F.SilkS` | 1 × 1 | 0.15 |
| `property "Value"` | `snp8` | 8.75 13.75 0 | `F.Fab` | 1 × 1 | 0.15 |

descr `"Корпус разъёма СНП 8 контактов с двумя монтажными отверстиями 3 мм"`, tags `"snp8 connector"`.
Порядок площадок в таблице — порядок записи (§1.2 п.7: `""` первыми).

#### Неоднозначности snp8 и принятые решения

1. **Нумерация.** ЛР §3.2.3: «по столбцам 1–4 слева и 5–8 справа или “змейкой”», по умолчанию — столбцами.
   Решение: `numbering="by_row"` (как `gen2011 mod.py:918-935`); `"zigzag"` даёт 1 (−2.5,−3.75), 2 (2.5,−3.75),
   3 (−2.5,−1.25), 4 (2.5,−1.25) … — нумерацию `PinHeader_2x04` KiCad.
2. **Вертикальное положение ряда относительно контура** не задано. Решение `gen2011`
   (`pads_offset_y=0`): блок площадок по центру контура, от центра крайней площадки до края
   контура 8.75 (7 клеток) сверху и снизу. Альтернатива из ТЗ прил. В.2 (см. ниже):
   `pads_offset_y=-1.25` — ряд на 1.25 выше центра (7.5 = 6 клеток сверху, 10 = 8 клеток снизу).
   Для этого варианта площадки y = −5, −2.5, 0, 2.5, отверстия и контур не меняются; левая сторона
   шелкографии режется на куски 12.5…3.41, 1.59…0.91, −0.91…−1.59, −3.41…−4.09, −5.91…−12.5.
3. **Слои монтажного отверстия.** В `My_lib.mod` маска `00E00001` (`At HOLE N 00E00001`) — при
   конвертации KiCad 9 это `B.Cu F.SilkS *.Mask` (`research/legacy_expected.out`, раздел masks) — артефакт
   умолчания KiCad 2011 (`mod.py:62 PAD_HOLE_DEFAULT_LAYERS`). Решение: `"*.Cu" "*.Mask"`, как в
   `MountingHole.pretty` (§1.3).

#### Расшифровка примера ТЗ прил. В.2

```python
pin_header(rows=2, cols=4, pitch=2.5, row_pitch=5.0, pad_size=1.3, drill=0.8, first_square=True,
           mounting_holes=[(11.25, -5.0, 3.0), (11.25, 15.0, 3.0)], name="snp8")
```

* Начало координат — центр площадки 1 (как у всех THT-генераторов kicadfp и KiCad, KLC F7.2);
  **ряд** (row) — вертикальная линия из `cols` = 4 площадок с шагом `pitch` = 2.5 вниз (+Y);
  ряды идут вправо (+X) через `row_pitch` = 5.0. Это совпадает с формулировкой ЛР «два ряда по 4, шаг
  2,5 в ряду, расстояние между рядами 5» и с именем KiCad `PinHeader_2x04` (2 ряда × 4).
* Площадки: левый ряд x = 0, правый x = 5, y = 0, 2.5, 5, 7.5.
* Отверстия x = 11.25 = 5 + 12.5/2 — центр контура шириной 12.5, левая сторона которого на правом
  ряду (x = 5). Расстояние между отверстиями 20 = 25 − 2·2.5 → контур по y от −7.5 до 17.5, центр y = 5.
  Центр блока площадок y = 3.75, т. е. ряд смещён на 1.25 **вверх** относительно центра контура —
  это вариант `pads_offset_y=-1.25` (п. 2 выше), а не вариант `gen2011`.
* Согласование с Частью 1: `lab_snp8(origin="pin1", pads_offset_y=-1.25)` даёт те же площадки и
  отверстия, что вызов В.2 (проверено, §4); `lab_snp8(origin="pin1")` — отверстия (11.25, −6.25),
  (11.25, 13.75). Вызов В.2 **не** строит контур 12.5 × 25 (у `pin_header` нет параметра корпуса),
  его шелкография/F.Fab — стандартный контур штыревого разъёма (§3.3), нумерация по умолчанию
  `zigzag`. Поэтому эталоном сценария 5 служит `lab_snp8()`, а В.2 — пример API.

Результат вызова В.2 по правилам §3.3 (для тестов `pin_header`):

| номер | тип | форма | x | y |
|---|---|---|---|---|
| `""` | np_thru_hole | circle Ø3, drill 3 | 11.25 | -5 |
| `""` | np_thru_hole | circle Ø3, drill 3 | 11.25 | 15 |
| `"1"` | thru_hole | rect 1.3 | 0 | 0 |
| `"2"` | thru_hole | oval 1.3 | 5 | 0 |
| `"3"` | thru_hole | oval 1.3 | 0 | 2.5 |
| `"4"` | thru_hole | oval 1.3 | 5 | 2.5 |
| `"5"` | thru_hole | oval 1.3 | 0 | 5 |
| `"6"` | thru_hole | oval 1.3 | 5 | 5 |
| `"7"` | thru_hole | oval 1.3 | 0 | 7.5 |
| `"8"` | thru_hole | oval 1.3 | 5 | 7.5 |

F.Fab: (0.625,−1.25)→(6.25,−1.25)→(6.25,8.75)→(−1.25,8.75)→(−1.25,0.625)→(0.625,−1.25) (скос 7.5/4 = 1.875);
F.SilkS: (−1.31,−1.31)–(0,−1.31), (−1.31,0)–(−1.31,−1.31), (−1.31,1.25)–(−1.31,8.81), (−1.31,1.25)–(2.5,1.25),
(−1.31,8.81)–(6.31,8.81), (2.5,−1.31)–(6.31,−1.31), (2.5,1.25)–(2.5,−1.31), (6.31,−1.31)–(6.31,8.81);
F.CrtYd `fp_rect` (−1.75,−7)–(13.25,17); Reference (2.5,−2.31), Value `"snp8"` (2.5,9.81),
`${REFERENCE}` (2.5,3.75, 90°). Имя задано явно (`name="snp8"`); без него было бы
`PinHeader_2x04_P2.50mm_Vertical_W5.0mm`.

### 2.6. Сравнение с `My_lib.mod` (корпусами «созданными вручную»)

`My_lib.mod` — результат `gen2011` в 1/10000 дюйма; перевод ×0.00254 (`legacy_expected.out` —
точный расчёт по `KiCad 9.0 pcb_io_kicad_legacy.cpp`). Округление до деци-мил даёт отклонения до
0.00127 мм.

| Величина | Точно (мм) | В `My_lib.mod` | → мм |
|---|---|---|---|
| площадка | 1.3 | 512 | 1.30048 |
| отверстие | 0.8 | 315 | 0.8001 |
| ряды dip14 ±3.75 / шаг 2.5 | 3.75 / 2.5, 5, 7.5 | 1476 / 984, 1969, 2953 | 3.74904 / 2.49936, 5.00126, 7.50062 |
| контур dip14 ±2.5 × ±8.75 | 2.5 / 8.75 | 984 / 3445 | 2.49936 / 8.7503 |
| mlt площадки ±5, контур ±3.75 × ±1.25 | 5 / 3.75 / 1.25 | 1969 / 1476 / 492 | 5.00126 / 3.74904 / 1.24968 |
| snp8 контур x 2.5…15, y ±12.5 | 2.5 / 15 / 12.5 | 984 / 5906 / 4921 | 2.49936 / 15.00124 / 12.49934 |
| snp8 отверстие Ø3 в (8.75, ±10) | 3 / 8.75 / 10 | 1181 / 3445 / 3937 | 2.99974 / 8.7503 / 9.99998 |
| текст 1 мм / толщина | 1.0 / 0.15 (L4) | 394 / 59 | 1.00076 / 0.14986 |

Что **совпадает** (с допуском 0.00127 мм): номера, типы (`STD`→`thru_hole`, `HOLE`→`np_thru_hole`,
`pcb_io_kicad_legacy.cpp:1502-1503`), формы (`R`→`rect`, `C`→`circle`), координаты, размеры и
отверстия всех площадок; положения и углы Reference/Value; отрезки контуров dip14 (кроме верхней
стороны), mlt (кроме выводных линий при `clip=True`), snp8 (кроме левой стороны при `clip=True`).

Что **отличается по решению** kicadfp: слои площадок (`00E0FFFF` → `"*.Cu" "*.Mask" "F.SilkS"`,
`00E00001` → `"*.Mask" "B.Cu" "F.SilkS"` — у kicadfp `"*.Cu" "*.Mask"`), толщина линий (0.15 → 0.12),
Value (`"VAL**"` на F.SilkS → имя корпуса на F.Fab), добавлены F.Fab и F.CrtYd, обрезка шелкографии,
**выемка dip14**.

Выемка dip14 в `My_lib.mod`: `DA 0 -3445 295 -3445 -1800 59 21` при непрерывной верхней стороне.
KiCad 9 импортирует её как дугу start (−0.7493, −8.7503) mid (0, −9.4996) end (0.7493, −8.7503)
(`pcb_io_kicad_legacy.cpp:1632-1645` → `EDA_SHAPE::SetArcAngleAndEnd`, `common/eda_shape.cpp:953-965`;
середина по `GetArcMid`, `:811-821`; расчёт `research/legacy_expected.out`): полуокружность **наружу**
(выше края корпуса), т. е. «выступ», а не «выемка». Та же геометрия получается в KiCad 2011:
`EDGE_MODULE::Draw` (`bzr2986 pcbnew/class_edge_mod.cpp:228-231`) → `GRArc` (`common/gr_basic.cpp:1161-1198`)
→ `wxDC::DrawArc` от угла 0 к углу −180 (направление `DrawArc` — против часовой стрелки на экране,
по документации wxWidgets; запуском не проверено). Решение kicadfp: выемка внутрь с разрывом
верхней стороны (§2.3), как у всех DIP KiCad; для точного повторения `My_lib.mod` нужен отдельный
режим, которого нет (открытый вопрос 2).

### 2.7. Требования к тестам lab-генераторов

* Все площадки — по таблицам §2.3–2.5 (номер, тип, форма, x, y, size, drill, layers) с допуском 1e-9;
  все координаты площадок кратны 1.25 (и при `origin="pin1"`).
* Площадка с номером `"1"` — `rect`, остальные сигнальные — `circle`, size 1.3 × 1.3, drill 0.8
  (ТЗ сценарий 5).
* Шаг: |y(i+1) − y(i)| = 2.5 внутри ряда; расстояние между рядами 7.5 (dip14), 5 (snp8); между
  площадками mlt 10.
* Контур: F.Fab `fp_rect` = (−2.5,−8.75)–(2.5,8.75), (−3.75,−1.25)–(3.75,1.25), (2.5,−12.5)–(15,12.5);
  F.SilkS по таблицам.
* Сравнение с `convert(My_lib.mod)`: площадки и Reference/Value совпадают с допуском **0.00127** мм
  (кроме слоёв и текста Value).
* Зазор шелкография–медь ≥ 0.2 − 1e-6 (при `clip=True`); courtyard содержит все площадки и F.Fab,
  координаты courtyard кратны 0.01.

---

## 3. Часть 2. Параметрические семейства

### 3.1. Правила библиотеки KiCad v8 и что из них берёт kicadfp

Файлы стандартной библиотеки v8 созданы kicad-footprint-generator (ныне `klt`); формулы
восстановлены по коду `klt` и проверены на **всех** файлах семейства (§4). Геометрию v8 kicadfp
воспроизводит, кроме пунктов, отмеченных «Решение».

| Семейство (эталон v8) | Скрипт `klt` | pad 1 / остальные | Смещение F.SilkS от F.Fab | Courtyard |
|---|---|---|---|---|
| DIP (`DIP-14_W7.62mm`) | `src/generators/tools/footprint/footprint_scripts_DIP.py:36-270` | `rect` / `oval` 1.6 × 1.6, drill 0.8 (LongPads 2.4 × 1.6) | 0.06 | +0.25 |
| PinHeader (`PinHeader_1x04_…`, `2x04`) | `src/generators/connector/pin_header_socket/def_makePinHeadStraight.py` | `rect` / `oval` 1.7 × 1.7, drill 1.0 | 0.06 | +0.5 |
| R/C axial (`R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal`) | `footprint_scripts_resistorlike.py:58-640` (`makeResistorAxialHorizontal`) | `circle` / `oval`, size = 2·drill | 0.12 | +0.25 |
| Диод axial (`D_DO-35_SOD27_P7.62mm_Horizontal`) | то же, `deco="diode"` | `rect` / `oval`, size = 2·drill | 0.12 | +0.25 |
| C disc (`C_Disc_D5.0mm_W2.5mm_P5.00mm`) | `footprint_scripts_resistorlike.py:1133-…` (`makeResistorRadial`, `type="disc"`) | `circle` / `circle`, 2·drill | 0.12 | +0.25 |
| CP radial (`CP_Radial_D5.0mm_P2.50mm`) | то же, `type="round"`, `deco="elco"` | `rect` / `circle`, 2·drill | диаметр +0.24 | окружность +0.25 |
| TO-92 (`TO-92_Inline`) | не генерируется (ручной) | `rect` / `oval` 1.05 × 1.5, drill 0.75 | 0.12 по радиусу | +0.25 |

Отличия более новых библиотек (для сведения; kicadfp их **не** воспроизводит, кроме отмеченных):

* v9 (`kfp/v9.0.0`): DIP (0 из 63 файлов совпадает с правилами v8) — площадка 1 `roundrect` `(roundrect_rratio 0.15625)` (= 0.25/1.6: радиус
  min(25 %, 0.25 мм), KLC F7.3, `config_KLCv3.0.yaml:67-68`), остальные `circle`; courtyard `fp_rect`
  на сетке 0.01; `${REFERENCE}` повёрнут на 90° (`footprint_scripts_DIP.py:136`:
  `0 if (w_fab > h_fab) else 90`) — **это правило kicadfp берёт** (KLC F5.2 п.3 «ориентация по большей оси»).
  PinHeader, R/C axial, C_Disc, CP_Radial, D_DO-35, TO-92_Inline в v9 геометрически равны v8 (§4).
* master (`kfp/master`): PinHeader — площадки 2…n `circle`, шелкография на 0.11 от F.Fab (−1.38),
  Reference на −2.38; R — обе площадки `circle`, прямоугольники `fp_rect`; появилось свойство
  `KiLib_Generator`.

### 3.2. `dip`

```python
def dip(pins: int = 14, pitch: float = 2.54, row_pitch: float = 7.62,
        pad_size: float | tuple[float, float] = (1.6, 1.6), drill: float = 0.8,
        body_width: float | None = None, first_square: bool = True, pad_shape: str = "oval",
        name: str | None = None) -> Footprint
```

`pins` чётное ≥ 2. Обозначения: n = pins/2, p = pitch, W = row_pitch, (px, py) = pad_size.

* **Тело:** `bw = body_width` или по таблице KiCad (`klt src/generators/package/DIP/legacy/footprint.py:44-121`):
  W = 7.62 → 6.35; 10.16 → 6.35 (при pins 22, 24 → 9.14); 15.24 → 14.73; 22.86 → 22.35; 25.4 → 24.89;
  иначе **Решение:** W − 1.27. Выступ тела за крайние площадки `over = p/2` (KiCad: 1.27 при p = 2.54,
  `legacy/footprint.py:34-35`).
* **Площадки:** i = 1…n в (0, (i−1)·p); n+i в (W, (n−i)·p). №1 `rect` (если `first_square`), остальные
  `pad_shape`. Нумерация «U» (против часовой стрелки сверху), якорь в площадке 1 (KLC F7.2).
* **F.Fab** (`footprint_scripts_DIP.py:48-51,154`, `drawing_tools.py:692-716`): h = (n−1)·p + 2·over,
  l = (W − bw)/2, t = −over, скос b = min(1, 0.25·min(bw, h)) (KLC F5.2 п.2; у всех DIP KiCad = 1);
  ломаная (l+b, t)→(l+bw, t)→(l+bw, t+h)→(l, t+h)→(l, t+b)→(l+b, t) — 5 `fp_line`.
* **F.SilkS** (`:58-64,160`, `drawing_tools.py:943-970` `DIPRectT`, `marker_size=2`): so = 0.06,
  hs = h + 0.12, ws = min(bw + 0.12, W − px − 0.72), ls = (W − ws)/2, ts = −over − 0.06, cx = W/2;
  ломаная (cx−1, ts)→(ls, ts)→(ls, ts+hs)→(ls+ws, ts+hs)→(ls+ws, ts)→(cx+1, ts) — 5 `fp_line`;
  выемка `fp_arc` start (cx+1, ts) mid (cx, ts+1) end (cx−1, ts).
* **F.CrtYd:** §1.4, off 0.25.
* **Тексты** (`:136-151`): Reference (cx, ts − 1); Value (cx, ts + hs + 1); `${REFERENCE}` (cx, t + h/2),
  угол 0 если bw > h, иначе 90 (Решение, см. §3.1).
* **Имя** (`:94-97`): `f"DIP-{pins}_W{round(W, 2)}mm"` (Python `str` числа: 7.62 → `W7.62mm`, 7.5 →
  `W7.5mm`); **Решение:** при p ≠ 2.54 добавляется `f"_P{round(p, 2)}mm"` (у KiCad такого нет).
* **descr** (`:99`, v9): `f"{pins}-lead though-hole mounted DIP package, row spacing {round(W,2)}mm ({int(W/2.54*100)} mils)"`
  (v8 писал `row spacing 7.62 mm` с пробелом); **tags** (`:103`): `f"THT DIP DIL PDIP {p}mm {W}mm {int(W/2.54*100)}mil"`.

Пример: `dip()` = `DIP-14_W7.62mm` v8 полностью, кроме угла `${REFERENCE}` (90 вместо 0) и courtyard
(−1.05, −1.52)–(8.67, 16.76). ТЗ прил. В.3 `kicadfp gen dip --pins 14 --pitch 2.5 --row-pitch 7.5` →
имя `DIP-14_W7.5mm_P2.5mm`, bw = 6.23, площадки 1.6/0.8 (если не заданы), шелкография x 1.16…6.34,
y −1.31…16.31, выемка (4.75,−1.31)/(3.75,−0.31)/(2.75,−1.31), F.Fab x 0.635…6.865, y −1.25…16.25,
courtyard (−1.05,−1.5)–(8.55,16.5), Reference (3.75,−2.31), Value (3.75,17.31), `${REFERENCE}` (3.75,7.5,90°).

### 3.3. `pin_header`

```python
def pin_header(rows: int = 1, cols: int = 4, pitch: float = 2.54, row_pitch: float | None = None,
               pad_size: float | tuple[float, float] = 1.7, drill: float = 1.0, first_square: bool = True,
               pad_shape: str = "oval", numbering: str = "zigzag",
               mounting_holes: list[tuple[float, float, float]] | None = None,
               name: str | None = None) -> Footprint
```

Смысл параметров — как в ТЗ прил. В.2 (§2.5): `rows` рядов вдоль X через `row_pitch`
(по умолчанию = `pitch`), в ряду `cols` площадок вдоль Y через `pitch`. KiCad `PinHeader_{rows}x{cols:02}`.

* **Площадки:** ряд r = 0…rows−1, позиция k = 0…cols−1 в (r·rp, k·p). Номер: `zigzag` — k·rows + r + 1
  (KiCad, 80/80 файлов); `by_row` — r·cols + k + 1. №1 `rect`, остальные `pad_shape`.
* **Монтажные отверстия** `mounting_holes=[(x, y, d), …]` — координаты в системе корпуса (от площадки 1):
  `np_thru_hole` §1.3; входят в bbox courtyard; шелкография обрезается вокруг них (§1.5).
* **F.Fab:** bw = (rows−1)·rp + p; l = (rows−1)·rp/2 − bw/2 (= −p/2); t = −p/2; r = l + bw;
  b = (cols−1)·p + p/2; скос ch = bw/4 (v8: 0.635 у 1×, 1.27 у 2×; `def_makePinHeadStraight.py:196`);
  ломаная (l+ch,t)→(r,t)→(r,b)→(l,b)→(l,t+ch)→(l+ch,t).
* **F.SilkS** (so = 0.06): L = l−so, T = t−so, R = r+so, B = b+so. Отрезки: (L,T)–(0,T); (L,0)–(L,T);
  (L,p/2)–(L,B); при rows = 1: (L,p/2)–(R,p/2), (L,B)–(R,B), (R,p/2)–(R,B); при rows ≥ 2:
  (L,p/2)–(rp/2,p/2), (L,B)–(R,B), (rp/2,T)–(R,T), (rp/2,p/2)–(rp/2,T), (R,T)–(R,B).
  (Угол-маркер у площадки 1 + контур, начинающийся ниже/правее неё.)
* **F.CrtYd:** §1.4, off **0.5** (разъём).
* **Тексты:** xc = (rows−1)·rp/2; Reference (xc, T − 1); Value (xc, B + 1); `${REFERENCE}` (xc, (cols−1)·p/2) угол 90.
* **Имя:** `f"PinHeader_{rows}x{cols:02d}_P{p:.2f}mm_Vertical"`; **Решение:** при rp ≠ p добавляется
  `f"_W{round(rp, 2)}mm"`. **descr:** `f"Through hole straight pin header, {rows}x{cols:02d}, {p:.2f}mm pitch, {kind}"`,
  **tags:** `f"Through hole pin header THT {rows}x{cols:02d} {p:.2f}mm {kind_t}"`, где kind = `single row` /
  `double rows`, kind_t = `single row` / `double row` (как в файлах v8); для rows > 2 — `"{rows} rows"` / `"{rows} row"` (Решение).

Пример 1x04: площадки (0, 0/2.54/5.08/7.62); F.Fab (−1.27,−0.635)…(−0.635,−1.27)…(1.27,8.89);
F.SilkS (−1.33,−1.33)–(0,−1.33), (−1.33,0)–(−1.33,−1.33), (−1.33,1.27)–(−1.33,8.95), (−1.33,1.27)–(1.33,1.27),
(−1.33,8.95)–(1.33,8.95), (1.33,1.27)–(1.33,8.95); courtyard (−1.77,−1.77)–(1.77,9.39) (v8: ±1.8, 9.4);
Reference (0,−2.33), Value (0,9.95), `${REFERENCE}` (0,3.81,90°) — совпадает с v8 и v9 (кроме courtyard).

### 3.4. `resistor`, `capacitor_axial`, `diode` (выводные, горизонтальный монтаж)

```python
def resistor(pitch: float = 10.16, body_length: float = 6.3, body_diameter: float = 2.5,
             drill: float = 0.8, pad_size: float | None = None, first_square: bool = False,
             series: str = "Axial", name: str | None = None) -> Footprint
def capacitor_axial(pitch: float = 7.5, body_length: float = 3.8, body_diameter: float = 2.6,
                    drill: float = 0.8, pad_size: float | None = None, first_square: bool = False,
                    series: str = "Axial", name: str | None = None) -> Footprint
def diode(pitch: float = 7.62, body_length: float = 4.0, body_diameter: float = 2.0,
          drill: float = 0.8, pad_size: float | None = None, series: str = "DO-35_SOD27",
          name: str | None = None) -> Footprint
```

Умолчания = `R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal` (без серии в имени),
`C_Axial_L3.8mm_D2.6mm_P7.50mm_Horizontal`, `D_DO-35_SOD27_P7.62mm_Horizontal`.
Обозначения: rm = pitch, L = body_length, D = body_diameter, pd = pad_size или 2·drill
(`footprint_scripts_resistorlike.py:90`; во всех R/C/D файлах size = 2·drill), so = 0.12, lw = 0.12.

* **Площадки:** 1 в (0,0): `circle` (R, C; `rect` при `first_square`), у диода `rect` (катод);
  2 в (rm,0) `oval` (v8/v9, 91/91 файл). Размер pd × pd.
* **F.Fab:** lf = (rm − L)/2; `fp_rect` (lf, −D/2)–(lf+L, D/2); выводы (0,0)–(lf,0) и (rm,0)–(lf+L,0).
* **F.SilkS** (`:103-117,438-510`): hs = D + 0.24, ws = L + 0.24, ls = lf − 0.12, ts = −hs/2,
  lim = pd/2 + 0.24.
  * если ls ≥ lim: `fp_rect` (ls, ts)–(ls+ws, ts+hs) (v8 писал 4 `fp_line`);
  * если ls < lim и ts < −(pd/2 + 0.24): две скобки (ls, −y₀)→(ls, ts)→(ls+ws, ts)→(ls+ws, −y₀) и зеркальная снизу,
    y₀ = pd/2 + 0.24;
  * если ls < lim иначе: только две горизонтали (ls, ts)–(ls+ws, ts), (ls, ts+hs)–(ls+ws, ts+hs);
  * выводные линии, если lim < ls: (lim, 0)–(ls, 0) и (rm − lim, 0)–(ls + ws, 0).
  Зазор до меди у KiCad 0.24 − 0.06 = **0.18** (меньше рекомендуемых 0.2) — kicadfp воспроизводит.
* **Диод — полоса катода** (`:136,343-367,510-544`): xb = lf + 0.15·L; F.Fab `fp_line` на x = xb − 0.1, xb, xb + 0.1
  (от −D/2 до D/2); F.SilkS на x = xb − 0.12, xb, xb + 0.12 (от ts до ts + hs); `fp_text user "K"` в (0, −pd/2 − 1)
  на F.SilkS и на F.Fab (шрифт 1/0.15).
* **F.CrtYd:** §1.4, off 0.25 (= KiCad `:114-117`).
* **Тексты:** Reference (rm/2, ts − 1); Value (rm/2, hs/2 + 1); `${REFERENCE}` в (rm/2, 0), у диода
  (rm/2 + 0.075·L, 0); размер `${REFERENCE}` (`:121-128`): 1/0.15, но если L ≤ 5 или D ≤ 1:
  s = min(0.8·D, L/5), t = 0.15·s; затем s = max(0.25, s), t = max(0.0375, t) (DO-35: 0.8/0.12).
* **Имена** (`:151-163`): `f"R_{series}_L{L:.1f}mm_D{D:.1f}mm_P{rm:.2f}mm_Horizontal"`, для C — `C_…`,
  для диода `f"D_{series}_P{rm:.2f}mm_Horizontal"`. **descr/tags (Решение, по образцу `:196`):**
  `f"Resistor, {series}, Horizontal, pin pitch={rm}mm, length*diameter={L}*{D}mm^2"` /
  `f"Resistor {series} Horizontal pin pitch {rm}mm length {L}mm diameter {D}mm"` (для C — `Capacitor`,
  для D — `Diode`).

Пример `resistor(series="Axial_DIN0207")`: F.SilkS rect (1.81,−1.37)–(8.35,1.37), выводы (1.04,0)–(1.81,0),
(9.12,0)–(8.35,0); F.Fab (1.93,−1.25)–(8.23,1.25); courtyard (−1.05,−1.5)–(11.21,1.5); Reference (5.08,−2.37),
Value (5.08,2.37) — совпадает с v8. Диод DO-35: полосы F.SilkS x = 2.29/2.41/2.53, F.Fab 2.31/2.41/2.51,
`K` (0,−1.8), `${REFERENCE}` (4.11,0) 0.8/0.12, courtyard (−1.05,−1.25)–(8.67,1.25).

### 3.5. `capacitor_radial` (неполярный, дисковый)

```python
def capacitor_radial(pitch: float = 5.0, diameter: float = 5.0, width: float = 2.5, drill: float = 0.8,
                     pad_size: float | None = None, polarized: bool = False, hatch: bool = True,
                     name: str | None = None) -> Footprint
```

При `polarized=False` — корпус «диск» (`C_Disc_D5.0mm_W2.5mm_P5.00mm`). rm = pitch, W = diameter,
H = width, pd = pad_size или 2·drill, cx = rm/2.

* Площадки 1 (0,0) и 2 (rm,0) — обе `circle` (неполярный; 39/39 файлов v8).
* F.Fab `fp_rect` (cx − W/2, −H/2)–(cx + W/2, H/2).
* F.SilkS: прямоугольник 4 `fp_line` со смещением 0.12, обрезанный по §1.5. (KiCad v8 резал с
  собственной аппроксимацией зоны: концы разрыва ±1.055 вместо ±1.0532 у kicadfp.)
* F.CrtYd: §1.4 off 0.25 (= KiCad: w = max(W, rm + pd) + 0.5, h = max(H, pd) + 0.5, центр (cx, 0), `:1285-1286`).
* Reference (cx, top(crtyd) − 1) и Value (cx, bottom(crtyd) + 1) — от courtyard, а не от шелкографии
  (`:1402`); `${REFERENCE}` (cx, 0), размер по правилу §3.4 с L = W, D = H.
* Имя (`:1344`): `f"C_Disc_D{W:.1f}mm_W{H:.1f}mm_P{rm:.2f}mm"`.

### 3.6. `capacitor_radial(polarized=True)` (электролитический, круглый)

Эталон `CP_Radial_D5.0mm_P2.50mm`. D = diameter, rs = (D + 0.24)/2 (`:1282`), cx = rm/2.

* Площадки: 1 `rect` (0,0) (v8; v9+ `roundrect`), 2 `circle` (rm,0), pd × pd.
* F.Fab `fp_circle` центр (cx,0), радиус D/2.
* F.SilkS `fp_circle` радиус rs; если пересекает зоны §1.5 — заменяется дугами.
* F.CrtYd `fp_circle` радиус r = max(D/2 + 0.25, hypot(rm/2 + pd/2 + 0.06, pd/2 + 0.06) + 0.25),
  округлённый вверх на 0.01 (`:1699-1712`; v8 — на 0.05).
* Знак «+» (`:1516-1540,1671-1700`), ps = D/10:
  F.Fab — центр (cx − k·cos30°, −k·sin30°), k = (D − 0.05 − ps)/2 − ps/10;
  F.SilkS — k = (2·rs + 0.06 + ps)/2 + ps/10; каждый «+» — два `fp_line` длиной ps (горизонталь и вертикаль).
* Штриховка отрицательной половины (`hatch=True`, `:1625-1634`): x = 0; пока x < rs: отрезок F.SilkS
  x' = cx + x от −hc до hc, hc = sqrt(rs² − x²) − 0.04, из которого вырезаны квадраты вокруг площадок
  со стороной pd + 0.48 (`addKeepoutRect`, `:1547`); x += 0.04 (накопительно). Координаты
  (локальные x, y) округляются на 0.001 **от нуля**, затем прибавляется cx — так получаются значения
  вида 1.971, −5.03 в файлах KiCad (5029 отрезков в 26 файлах, §4).
* Тексты: Reference (cx, −(max(D, pd) + 0.5)/2 − 1), Value — симметрично; `${REFERENCE}` (cx, 0),
  размер по §3.4 с L = D = D.
* Имя (`:1342`): `f"CP_Radial_D{D:.1f}mm_P{rm:.2f}mm"`.
* KLC F5.3 п.8 (`F5.3.adoc:31`) требует для «canned capacitors» отступ 0.5, но все 26 файлов
  `CP_Radial` v8 имеют 0.25 — kicadfp следует библиотеке (открытый вопрос 6).

### 3.7. `transistor` (TO-92, выводы в линию)

```python
def transistor(pitch: float = 1.27, pad_size: float | tuple[float, float] | None = None,
               drill: float | None = None, body_radius: float = 2.48, name: str | None = None) -> Footprint
```

Эталоны `TO-92_Inline` (pitch 1.27) и `TO-92_Inline_Wide` (2.54) — файлы нарисованы вручную
(нет генератора в `klt`), поэтому это **Решение** с проверкой по файлам:

* Площадки: 3 шт. в (0,0), (p,0), (2p,0); №1 `rect`; p = 1.27: остальные `oval`, 1.05 × 1.5, drill 0.75;
  p = 2.54: остальные `circle`, 1.5 × 1.5, drill 0.8 (как в файлах).
* Корпус: центр C = (p, 0), R = body_radius = 2.48, плоская сторона внизу. F.Fab: дуги
  start C + R(−cos45°, sin45°) mid C + R(cos157.5°, −sin157.5°) end (p, −R) и
  start (p, −R) mid C + R(cos22.5°, −sin22.5°) end C + R(cos45°, sin45°); хорда `fp_line` между концами
  на y = R·sin45° = 1.7536. F.SilkS — то же с Rs = R + 0.12 = 2.6 (хорда y = 1.8385), обрезка §1.5
  (у Wide дуги режутся у площадок 1 и 3).
  У `TO-92_Inline` дуги F.Fab и F.SilkS совпадают с файлом KiCad до 6 знаков (silk start (−0.568478, 1.838478)
  mid (−1.132087, −0.994977) end (1.27, −2.6)); у `TO-92_Inline_Wide` совпадают дуги F.Fab, а разрезанные дуги
  F.SilkS отличаются (KiCad режет с большим запасом: конец дуги (0.1836, −1.0988) в 0.35 от края площадки 1 против 0.26 у kicadfp). **Хорды у KiCad не замкнуты**: F.Fab y = 1.75, x −0.5…3.0,
  F.SilkS y = 1.85, x −0.53…3.07 — kicadfp строит замкнутый контур.
* F.CrtYd: §1.4 off 0.25 по bbox(окружность корпуса до хорды, площадки) → (−1.46,−2.73)–(4,2.01) — как в файле.
* Тексты: Reference (p, top(crtyd) − 0.83), Value (p, bottom(crtyd) + 0.78) — подобраны так, чтобы
  совпасть с файлами (−3.56 / 2.79); `${REFERENCE}` (p, 0).
* Имя: `TO-92_Inline` / `TO-92_Inline_Wide`; descr как в файлах: `"TO-92 leads in-line, narrow, oval pads, drill 0.75mm (see NXP sot054_po.pdf)"`
  / `"TO-92 leads in-line, wide, drill 0.75mm (see NXP sot054_po.pdf)"` (sic: drill у Wide 0.8); tags `"to-92 sc-43 sc-43a sot54 PA33 transistor"`.

### 3.8. Реестр CLI

`GENERATORS` (`architecture.md` §11): `dip`, `pin_header`, `resistor`, `capacitor_radial`,
`capacitor_axial`, `diode`, `transistor`, `lab_dip14`, `lab_mlt`, `lab_snp8`. Параметры CLI —
имена аргументов с `_` → `-` (`--row-pitch`, `--pad-size`, `--first-square`); `mounting_holes` — только
через JSON (`[[x, y, d], …]`).

---

## 4. Проверено

Все скрипты — `research/labgen/`, запуск `/Users/juli/Desktop/Claude/kicadfp/.venv/bin/python <скрипт>`.

1. **Формулы библиотеки v8** (`families_v8.py`, сравнение множеств элементов с точностью 1e-4, courtyard
   на сетке 0.05 или 0.01 «от нуля»):
   * `Package_DIP/DIP-N_W*mm[_LongPads]` v8: **62 / 63** (исключение `DIP-32_W7.62mm` — особые размеры
     тела 7.11, выступ 1.33);
   * `PinHeader_{1,2}xNN_P2.54mm_Vertical`: v8 **80 / 80**, v9 **80 / 80** (включая 1x01, 2x01);
   * `R_Axial_*_Horizontal` v8 **30 / 30**; `C_Axial_*_Horizontal` v8 **28 / 28**;
   * `D_*_Horizontal` (Diode_THT v9, 33 файла) **32 / 33** (`D_DO-201_P12.70mm`: courtyard 2.86 vs 2.9 и
     погрешность 1e-4 у `${REFERENCE}`);
   * `C_Disc_*` v8: **34 / 39** по F.Fab, F.CrtYd, площадкам, текстам и габариту шелкографии (5 файлов —
     отклонение габарита шелкографии 0.001 или частичная шелкография у D3.0);
   * `CP_Radial_D*mm_P*mm` v8: **26 / 26** (площадки, тексты, окружности, «+»); штриховка
     (`hatch_check.py`): 26 файлов, 5029 отрезков, 19 файлов точно, 7 — отдельные концы ±0.001;
   * те же проверки на v9: R_Axial 30 / 30, C_Axial 28 / 28, C_Disc 34 / 39 (те же 5), CP_Radial 26 / 26,
     DIP 0 / 63 (v9 перегенерирован: `roundrect`, `circle`, `fp_rect`, угол `${REFERENCE}`);
     `TO-92_Inline` и `D_DO-35_SOD27_P7.62mm_Horizontal` v8 (`research/kfp8`) и v9 совпадают поэлементно;
   * courtyard: 272 файла на сетке 0.05, 40 — на 0.01.
2. **Правила kicadfp против библиотеки** (`bulk_spec.py`: площадки, тексты, дуги, окружности, линии
   F.SilkS+F.Fab точно; courtyard ±0.05): DIP v8 62 / 63 (тексты не сравнивались: у 59 файлов угол
   `${REFERENCE}` 0 против 90 по правилу v9); PinHeader v8 80 / 80, v9 80 / 80; R 30 / 30; C_Axial 28 / 28;
   D (v9) 33 / 33; C_Disc 19 / 39 (у 20 — только концы разрывов шелкографии, §3.5); CP_Radial 25 / 26
   (`CP_Radial_D10.0mm_P7.50mm`: KiCad оставляет одну дугу с разрывом у площадки 1, kicadfp — две дуги).
3. **Отдельные эталоны** (`check_spec.py`): `dip()` = `DIP-14_W7.62mm` v8 кроме угла `${REFERENCE}`;
   `dip()` vs v9 — отличаются только формы площадок (`roundrect`/`circle` в v9); `pin_header(1,4)`,
   `(2,4)`, `(2,20)`, `resistor`×2, `capacitor_axial`, `diode` — полностью; `capacitor_radial(polarized)`
   D5 P2.5 и D10 P5 — полностью, включая штриховку; `TO-92_Inline` — площадки, дуги, тексты, courtyard
   (хорды отличаются по решению); `TO-92_Inline_Wide` — площадки, дуги F.Fab, тексты, courtyard.
4. **Лабораторные корпуса против `My_lib.mod`** (`check_spec.py`): номера/типы/формы/координаты/размеры/
   отверстия площадок — max |Δ| 0.00126 (dip14, mlt), 0.00096 (snp8) ≤ 0.00127; Reference/Value —
   max |Δ| 0.00002 / 0.00064 / 0.00098, углы совпадают.
5. **Лабораторные корпуса, самопроверка**: все площадки на сетке 1.25 (и при `origin="pin1"`); зазор
   шелкография–медь: dip14 0.54, mlt 0.200, snp8 0.200 (без обрезки mlt и snp8 −0.71); courtyard
   содержит площадки и F.Fab, координаты кратны 0.01.
6. **В.2**: результат `pin_header(...)` из ТЗ — отверстия (11.25,−5), (11.25,15), courtyard
   (−1.75,−7)–(13.25,17), зазор шелкографии 0.54; `lab_snp8(origin="pin1", pads_offset_y=-1.25)` даёт
   отверстия (11.25,−5), (11.25,15), F.Fab (5,−7.5)–(17.5,17.5); `lab_snp8(origin="pin1")` — (11.25,−6.25),
   (11.25,13.75).
7. **Монтажные отверстия**: в `kfp/v9.0.0` 102 NPTH: 96 `circle` и 5 `oval` со слоями `"*.Cu" "*.Mask"`,
   1 `circle` со слоями `"F&B.Cu" "*.Mask"` (`ToolingHole_1.152mm`); у всех номер `""`; в master — 231 `circle`
   и 18 `oval` со слоями `"*.Cu" "*.Mask"` (+ 12 `circle` `"F.Cu"` в QFN). `MountingHole_3.2mm_M3` (v8, v9) и
   `MountingHole_3mm` (v9): size = drill, `(attr exclude_from_pos_files exclude_from_bom)`, окружность Cmts.User
   радиусом = диаметру отверстия, courtyard-окружность +0.25.
8. **Порядок записи** (`emit.py`): сортировка по `cmp_drawings`/`cmp_pads` сверена с порядком узлов в
   файлах v8, сохранённых pcbnew (`DIP-14_W7.62mm`: линии F.SilkS по возрастанию start.x, дуга после
   отрезков, затем F.CrtYd, F.Fab, `fp_text`; `TO-220-*`: `""` перед `"1"`).
9. **Выемка dip14 в `My_lib.mod`**: расчёт импорта KiCad 9 (`research/legacy_expected.out`, раздел
   «arc examples»): mid (0, −9.4996) — дуга наружу.

Не проверено: открытие сгенерированных файлов в KiCad 8/9 и DRC/Footprint Checker (KiCad в среде нет);
направление `wxDC::DrawArc` в KiCad 2011 запуском; KLC-проверка `klt/library_utils/klc-check` не запускалась
(нужен KicadModTree); файлы Diode_THT/TO-92/MountingHole v8 взяты поштучно (`research/kfp8`), семейство
диодов проверено по v9.

## 5. Открытые вопросы

1. **snp8: нумерация и положение ряда.** Выбрано `by_row` и центрирование (`gen2011`); ТЗ В.2
   соответствует смещению −1.25. Нужен рис. 11б методички или решение преподавателя; оба варианта
   параметризованы.
2. **Форма ключа dip14.** `My_lib.mod` содержит дугу наружу при сплошной верхней стороне; kicadfp рисует
   выемку внутрь с разрывом стороны. Если «сравнение с корпусами, созданными вручную» (ТЗ 8.2) будет
   побайтным по шелкографии, понадобится режим `notch="legacy"`.
3. **Начало координат lab-корпусов** (`center` против KLC F7.2 `pin1`). Выбран `center` ради совпадения
   с `My_lib.mod`.
4. **Обрезка шелкографии на площадках** в lab-корпусах: задание требует линию контура snp8 по центрам
   площадок; KLC запрещает шелкографию на меди. Выбрано `clip=True`, полный контур остаётся на F.Fab.
5. **`${REFERENCE}` в lab-корпусах** не создаётся (конфликт с вертикальным Value dip14) — отступление
   от `architecture.md` §11.
6. **Отступ courtyard полярных конденсаторов:** KLC F5.3 п.8 — 0.5, библиотека v8 — 0.25; выбрано 0.25.
7. **Поколение библиотеки:** kicadfp повторяет v8 (площадка 1 `rect`, остальные `oval`, шелкография DIP/
   разъёмов на 0.06 от F.Fab), а не v9/master (`roundrect` rratio 0.15625, `circle`, 0.11). Если заказчику
   нужен стиль KiCad 9 — достаточно `pad_shape="circle"` и параметра формы площадки 1 (сейчас только
   `first_square`).
8. **Суффиксы имён для нестандартных параметров** (`_P2.5mm` у DIP, `_W5.0mm` у PinHeader, descr/tags
   резисторов) — собственные правила kicadfp, у KiCad аналога нет.
9. **TO-92**: положения Reference/Value (−0.83/+0.78 от courtyard) подобраны под два файла, общей формулы
   KiCad нет; незамкнутые хорды KiCad не воспроизводятся.
10. **uuid генерируемых элементов:** случайные (как KiCad) или детерминированные `uuid5` — решить
    в `architecture.md`.
