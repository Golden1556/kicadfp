# Рабочий процесс: от ТЗ (PDF методички) до файлов KiCad

## 1. Извлечение данных из PDF

```bash
pdftotext -layout "методичка.pdf" out.txt          # текст: таблицы упаковки, имена, типы
pdftoppm -r 300 -png -f 11 -l 14 "методичка.pdf" p # страницы с рисунками (размеры в мм)
pdftoppm -r 300 -png -f 8 -l 8 -x 300 -y 250 -W 2000 -H 1300 "часть2.pdf" fig6   # crop схемы
```

Из текста берём: имена компонентов (латиницей, как требует методичка), префиксы
ссылок (микросхемы `DD`, резисторы `R`, разъёмы `X`), число секций, таблицы
«Секция / Имя вывода / Номер / Электрический тип», требования к видимости
Value, к общим невидимым выводам питания. Из рисунков: размеры корпуса и шаг
выводов в мм, какие выводы на какой стороне и в какой строке, форма (инверсия),
надписи внутри корпуса, топологию схемы (кто с кем соединён, где шина, где
метки, где junction).

## 2. Спецификация YAML

Полный пример — `examples/346_8.yaml`. Структура:

```yaml
project: "346_8"        # обязательно в кавычках (YAML читает 346_8 как число)
units: mm               # mm | mil — единицы всех размеров ниже
grid: 50                # мил; точки подключения и координаты снапятся к сетке
crlf: true
netlist: true           # писать <project>.net (список цепей, формат Pcbnew) вместе со схемой
extra_libraries: []     # дополнительные библиотеки в .pro (ставятся первыми, перед проектной и стоковыми)
library:
  name: My_lib          # имя файла библиотеки (по умолчанию = project)
  components: [...]
schematic: {...}        # необязательно
```

### Компоненты (`library.components[]`)

Общие ключи: `name`, `reference`, `units` (секций), `value_visible`,
`description`, `keywords`, `docfile`, `aliases`, `footprints`, `text_size`
(имя/номер вывода), `field_size`, `line_width`, `fields` (доп. поля
`{id, text, at, size, visible, name}`), `reference_at`, `value_at`.

`kind: box` — прямоугольный корпус с автораскладкой:

```yaml
- name: K555TB6
  kind: box
  reference: DD
  units: 2
  width: 20          # мм; если не задано — по числу выводов
  height: 25
  dividers: [-5, 5]  # вертикальные линии внутри корпуса (X в мм)
  pin_length: 5
  pitch: 5           # шаг выводов
  pin_name_offset: 40mil    # суффикс mil/mm переопределяет units
  texts: [{text: T, at: [0, 10], size: 2}]
  draw: [...]        # произвольные примитивы (см. kind: raw)
  pins:
    - {name: J, number: 1, side: left, type: input, unit: 1}
    - {name: Q, number: 3, side: right, type: output, unit: 1, row: 0}   # row — строка стороны
    - {name: "~Q", number: 2, side: right, type: output, unit: 1, shape: inverted, row: 3}
    - {name: Vcc, number: 14, side: top, type: power_in, unit: 0, visible: false}
    - {name: X, number: 9, at: [x, y], side: left}                       # явная позиция
```

`type`: input, output, bidi, tristate, passive, unspecified, power_in,
power_out, open_collector, open_emitter, nc (и русские «вход», «выход»,
«двунаправленный», «вход питания»). `shape`: line, inverted, clock,
inverted_clock, input_low, clock_low, output_low, falling_edge, nonlogic.
`unit`: число, `0`/`common`, или буква секции `A`/`B`.

`kind: two_pin` — горизонтальный двухвыводной элемент (`width`, `height`,
`pin_length`, `pins: [{name, number, type}, {…}]`).

`kind: table` — разъём-таблица Net/Pin (`rows: [[net, number], …]`, `width`,
`net_col_width`, `row_height`, `pin_length`, `pin_type`, `header`, `pins_side`).

`kind: power` — символ питания (`style: gnd | vcc | bar_up`, `net` — имя цепи
(= имя невидимого вывода), `bar` — ширина черты/галки, `height` — ножка от
точки подключения, `arm_height` — высота плеч галки, `bar_width` — толщина
черты, `pin_length`, `reference: "#PWR"`). Вывод всегда невидимый: только
невидимый вывод типа W создаёт глобальную цепь (`netlist.cpp:666-679`).

`kind: raw` — всё вручную: `draw:` список примитивов
`{rect: [[x1,y1],[x2,y2]]}`, `{line: [[x,y],…]}`, `{bezier: [...]}`,
`{circle: {at: [x,y], r: R}}`, `{arc: {at: [x,y], r: R, start: deg, end: deg}}`,
`{text: T, at: [x,y], size: S}`, `{pin: {name, number, at, side, type, …}}`;
у каждого можно задать `unit`, `convert`, `width`, `fill: none|fg|bg`.

### Корпуса (`footprints`, ЛР 2)

```yaml
pad_defaults: {size: 1.3, drill: 0.8}    # площадки по умолчанию в .pro [pcbnew] (ТЗ §1.5)
footprints:
  - {name: dip14, kind: dip, pins: 14, pitch: 2.5, rows: 7.5, body_w: 5.0}
  - {name: mlt,   kind: two_pad, spacing: 10.0, body_w: 7.5, body_h: 2.5}
  - {name: snp8,  kind: pin_rows, rows: 2, per_row: 4, pitch: 2.5, row_gap: 5.0,
     body_w: 12.5, body_h: 25.0, hole: 3.0}
```

Размеры в мм (единицы pcbnew — 1/10000 дюйма, пересчёт внутри). Первая
площадка квадратная, остальные круглые 1,3 мм со сверлом 0,8 мм; нумерация
DIP «буквой U»; у `pin_rows` монтажные отверстия — площадки типа `HOLE` без
номера. Библиотека `<library.name>.mod` подключается первой в
`[pcbnew/libraries]`. У компонента символа ключ `footprint: dip14` заполняет
поле F2 — оно попадает в `.sch` и в `.net` (как после назначения в Cvpcb).

### Схема (`schematic`)

```yaml
schematic:
  page: A4
  title: "..."
  place:
    - {ref: X1,  lib: CONNECT, at: [40, 80]}                  # координаты листа в мм
    - {ref: DD1, lib: K555TB6, unit: 1, at: [160, 50], orientation: 0}   # 0|90|180|270[MX|MY]
    - {ref: "#PWR01", lib: GND, at: [70, 55], orientation: 180}
  buses: [[[105, 30], [105, 140]]]
  bus_entries:
    - {from_bus: 105, to: {ref: X1.2, x: 100}}   # ввод 45° от шины к концу провода
  connect:              # путь из точек; между точками — H/V отрезки (сначала горизонталь)
    - [X1.1, x=70, "#PWR01.1"]
    - [X1.3, x=125, {ref: DD1.13, x: 125}, DD1.13]
  labels:
    - {text: "1", at: {ref: X1.2, x: 90}}        # kind: local|global|hier|note, orient, size
  noconnect: [DD1.2, DD1.6]
  junctions: []         # явные; авто-junction ставится на T-стыках и концах внутри проводов
  sheets:
    - {name: sub, file: sub.sch, at: [200, 150], size: [30, 20],
       pins: [{name: IN, shape: Input, side: L, at: [200, 155]}]}
```

Точка в схеме: `[x, y]` (мм), `"REF.PIN"` (точка подключения вывода
размещённого компонента; для секций — по номеру вывода), `{ref: REF.PIN, x: …}`
(Y вывода, X задан), `"x=…"`/`"y=…"` в пути (сдвиг от предыдущей точки).
Так провода гарантированно попадают на выводы, а метки — на провода.

## 3. Генерация и проверка

```bash
python3 -m kicadgen gen examples/346_8.yaml -o examples/346_8      # .lib .dcm .pro .sch -cache.lib .net + строгая проверка
python3 -m kicadgen check examples/346_8/346_8.lib examples/346_8/346_8.sch examples/346_8/346_8.pro
python3 -m kicadgen render examples/346_8/346_8.lib -o /tmp/lib.svg   # картинка всех символов
python3 -m kicadgen render examples/346_8/346_8.sch -o /tmp/sch.svg   # картинка схемы
rsvg-convert -w 2000 /tmp/sch.svg -o /tmp/sch.png                     # для просмотра
python3 -m unittest discover -s tests
```

`check` повторяет логику загрузчика KiCad bzr2986: всё, что он отвергнет,
отвергается и здесь, с тем же текстом ошибки; дополнительно предупреждает об
UB (пропущенная заливка, длинные номера выводов, строка `Ti`).

## 4. Проверка в KiCad (у пользователя)

1. Открыть `<проект>.pro` менеджером KiCad → EESchema.
2. Редактор библиотек: выбрать библиотеку проекта, просмотреть каждый символ и
   каждую секцию; «Тест дублирования выводов».
3. EESchema: схема открывается без диалогов ошибок; «Выполнить проверку ERC»;
   «Сформировать список цепей» — сравнить с нашим `<проект>.net` (совпадают
   цепи; временные метки `/XXXXXXXX` у KiCad свои).
4. Пересохранить библиотеку из редактора и сравнить с сгенерированной
   (`diff` — только дата).

## 5. Чек-лист по методичкам РГРТУ

- Имена компонентов латиницей: `K555TB6`, `REZ`, `CONNECT`, `GND`, `VCC`.
- Value невидимо у всех пяти символов.
- Vcc/GND микросхемы — общие (`unit 0`), невидимые, «Вход питания» (`W`).
- Секция B — свои номера выводов (8, 9, 11, 10, 5, 6 для К555ТВ6).
- Резистор и разъём — выводы «Двунаправленный» (`B`).
- «Земля» и «питание» — флаг «Символ питания» (`P`), вывод `W`.
- Схема: шина с метками цепей; `Connection` на T-стыке; неиспользуемые `~Q` —
  `NoConn`; проект сохранён под номером бригады.
