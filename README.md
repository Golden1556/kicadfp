# kicadfp

Библиотека и редактор файлов посадочных мест KiCad (`.kicad_mod`, библиотеки `.pretty`)
на языке Python. Этап 1: работа с корпусами компонентов.

* чтение и запись файлов KiCad 6, 7, 8, 9 (и 10-dev) **без потерь** — неизвестные узлы,
  атрибуты и порядок сохраняются; файлы, записанные KiCad 8+, воспроизводятся байт в байт;
* объектная модель `Footprint` / `Pad` / `Line` / `Rect` / `Circle` / `Arc` / `Poly` /
  `Text` / `Model` как представления над деревом S-выражений;
* проверка корректности (`validate`), генераторы типовых корпусов (DIP, штыревые разъёмы,
  резисторы, конденсаторы, диоды, транзисторы, корпуса лабораторных работ);
* интерфейс командной строки `kicadfp` и графический интерфейс на PySide6;
* чтение и преобразование библиотек старого формата `.mod` (PCBNEW-LibModule-V1).

Ядро не имеет зависимостей, кроме стандартной библиотеки Python ≥ 3.10.

## Установка

```bash
pip install .            # ядро, API и CLI
pip install ".[gui]"     # + графический интерфейс (PySide6)
pip install ".[dev]"     # + тесты
```

## Быстрый старт

```python
import kicadfp

fp = kicadfp.load("Package_DIP.pretty/DIP-14_W7.62mm.kicad_mod")
for pad in fp.pads:
    pad.size_x = pad.size_y = 1.3
    pad.drill.diameter = 0.8
fp.pad("1").shape = "rect"
fp.name = "dip14"
for issue in fp.validate():
    print(issue.level, issue.code, issue.message)
lib = kicadfp.Library("br8_timer.pretty", create=True)
lib.add(fp)
lib.save_all()
```

```bash
kicadfp info dip14.kicad_mod
kicadfp pads dip14.kicad_mod
kicadfp set dip14.kicad_mod "pad[*].drill" 0.8 --write
kicadfp validate br8_timer.pretty --strict
kicadfp gen dip --pins 14 --pitch 2.5 --row-pitch 7.5 -o br8_timer.pretty/dip14.kicad_mod
kicadfp fmt br8_timer.pretty --write
kicadfp convert old_lib.mod -o old_lib.pretty
kicadfp gui
```

Документация: `docs/` (описание программы, руководство пользователя, руководство
программиста, программа и методика испытаний).
