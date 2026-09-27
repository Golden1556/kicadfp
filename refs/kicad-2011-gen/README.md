# kicad-2011-gen

Генератор и строгий валидатор файлов **KiCad 2011 (bzr2986)** для лабораторных
по «САПР печатных плат KiCAD» (РГРТУ): компонентные библиотеки `.lib`/`.dcm`
(ЛР 1), библиотеки корпусов `.mod` (ЛР 2), проектные файлы `.pro`, схемы
`.sch` и списки цепей `.net` (ЛР 3).

Формат восстановлен из исходников `../bzr2986/eeschema` и подтверждён на
реальных файлах из `../testing_data` (перечитываются и записываются
байт в байт).

```
docs/kicad-2011-formats.md   справочник по форматам со ссылками на код
docs/conventions.md          соглашения по символам, схемам, проекту
docs/workflow.md             ТЗ (PDF) -> YAML -> файлы -> проверка; формат YAML
docs/pcbnew-mod-format.md    формат библиотек корпусов pcbnew (.mod), из исходников
docs/pcbnew-pad-format.md    формат блока $PAD, монтажные отверстия, единицы pcbnew
docs/netlist-format.md       формат .net (Pcbnew) и алгоритм связности eeschema
kicadgen/                    пакет (Python ≥ 3.8, зависимости: pyyaml)
  model.py                   модель .lib с валидацией
  writer_lib.py / reader_lib.py   запись/чтение .lib и .dcm (реплика Save/Load)
  writer_pro.py / reader_pro.py   .pro
  sch.py                     модель, запись и чтение .sch, матрицы ориентации
  netlist.py                 связность (реплика netlist.cpp) и запись .net
  mod.py                     библиотеки корпусов .mod: модель, запись/чтение, dip/two_pad/pin_rows
  gen_footprints.py          корпуса ЛР 2 (dip14, mlt, snp8) отдельным скриптом
  helpers.py                 построители символов (корпус, 2-выводной, таблица, питание)
  spec.py                    YAML-спецификация -> проект
  render.py                  SVG-рендер для визуальной проверки
  cli.py                     python -m kicadgen gen|check|render (.lib/.sch/.mod)
examples/346_8.yaml          ЛР 1 + ЛР 2 + ЛР 3 по ТЗ (бригада 346_8)
examples/346_8/              сгенерированный проект: My_lib.lib/.dcm/.mod, 346_8.pro/.sch/.net, -cache.lib, SVG/PNG
examples/demo.yaml           синтетический проект: DeMorgan, дуги, поля, лист
tests/                       python3 -m unittest discover -s tests
```

Быстрый старт:

```bash
python3 -m kicadgen gen examples/346_8.yaml -o examples/346_8
python3 -m kicadgen check examples/346_8/*.lib examples/346_8/*.mod examples/346_8/*.sch examples/346_8/*.pro
python3 -m kicadgen render examples/346_8/346_8.sch -o /tmp/sch.svg
python3 -m kicadgen render examples/346_8/My_lib.mod -o /tmp/mod.svg
python3 -m unittest discover -s tests
```
