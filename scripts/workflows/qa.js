export const meta = {
  name: 'kicadfp-qa',
  description: 'Приёмочные сценарии ТЗ (приложение Г), проверка kicad-cli, покрытие, итоговое adversarial-ревью до исчерпания дефектов',
  phases: [
    { title: 'Acceptance', detail: 'tests/test_acceptance.py по сценариям Г.1–Г.10 + kicad-cli' },
    { title: 'Coverage', detail: 'покрытие ядра ≥ 80 %, добор тестов' },
    { title: 'Hunt', detail: 'loop-until-dry: искатели дефектов → верификация → исправление' },
  ],
}

const REPO = (typeof args === 'object' && args && args.repo) || '/Users/juli/Desktop/Claude/kicadfp'  // передайте args: {repo: '<путь к репозиторию>'}
const PY = REPO + '/.venv/bin/python'
const SCRATCH = REPO + '/.cache/scratch'
const KFP = REPO + '/.cache/kfp'
const KICAD_CLI = 'kicad-cli'  // локально на Mac: kicad-cli; в облаке — если установлен

const COMMON = `
Проект: kicadfp — библиотека и редактор файлов посадочных мест KiCad на Python (ТЗ: чтение/запись .kicad_mod KiCad 6–9 без потерь, модель, проверка, генераторы, CLI, GUI PySide6, конвертер .mod). Репозиторий ${REPO}, Python ${PY}; тесты: cd ${REPO} && QT_QPA_PLATFORM=offscreen ${PY} -m pytest -q; kicad-cli 10.0.6: ${KICAD_CLI} (fp upgrade INPUT_DIR -o OUT_DIR читает .pretty и пересохраняет; fp export svg; ненулевой код/сообщения в stderr = KiCad не смог прочитать файл). Полные клоны библиотек: ${KFP}/{v6.0.0,v7.0.0,v8.0.0,v9.0.0,master}. Контракт: docs/dev/architecture.md; спецификации: docs/dev/*.md. Правила кода: ядро без сторонних зависимостей, русские docstrings/сообщения, английские идентификаторы; не запускай git commit.
`

const SCENARIOS = `
Сценарии приёмочных испытаний (ТЗ, приложение Г):
1. Открыть ≥200 корпусов стандартных библиотек KiCad 8, сохранить без изменений, сравнить деревья — совпадение для всех (плюс байт-в-байт для файлов, записанных KiCad).
2. Открыть корпус KiCad 6 (width, fp_text), сохранить; открыть в KiCad 8/9 (здесь: kicad-cli fp upgrade без ошибок, число площадок/графики после upgrade совпадает) — графика и тексты на месте.
3. В DIP-14 добавить неизвестный узел (example_token 1 2), изменить размер площадки 1, сохранить — узел сохранён без изменений, изменена только площадка 1 (diff деревьев).
4. У всех площадок: форма roundrect с rratio 0.25, слои F.Cu F.Mask F.Paste, тип smd, удалить отверстия — validate без ошибок; kicad-cli читает; attr smd.
5. Сгенерировать dip14, mlt, snp8 по параметрам лабораторной — площадки 1.3, отверстия 0.8, первая квадратная, шаг и контур по заданию; kicad-cli читает.
6. Площадке отверстие 1.5 при размере 1.3 → validate даёт error «отверстие больше площадки».
7. Файл с синтаксической ошибкой (незакрытая скобка) → сообщение с номером строки и позиции, модель не создаётся (load бросает SexprSyntaxError; CLI код 2).
8. GUI: переместить площадку мышью и в таблице, отменить, повторить, сохранить — значения совпадают, файл содержит итоговые координаты (есть в tests/test_gui_mainwindow.py — сослаться/дополнить).
9. Скопировать корпус из одной библиотеки .pretty в другую с переименованием — в целевой файл с новым именем и полем name, исходный не изменён.
10. Преобразовать библиотеку старого формата .mod в .pretty — каждый модуль отдельным файлом, единицы переведены из децимил в мм, kicad-cli читает.
`

const KNOWN_GAPS = `
Известные пробелы/решения из критики спецификаций (проверь, что реализовано, иначе исправь и добавь тесты):
- KiCad отвергает неизвестные токены при чтении (parseFOOTPRINT → Expecting), поэтому файл сценария 3 с (example_token 1 2) сама Программа сохраняет без изменений (это и требуется), но KiCad его не откроет — в отчёте/документации это должно быть отмечено, а проверка kicad-cli для сценария 3 выполняется на файле БЕЗ неизвестного узла.
- validate: коды PAD_NPTH_NUMBER, PAD_EMPTY_NUMBER, LAYER_RESCUE, VERSION_TOO_NEW, PAD_THT_NO_COPPER; COURTYARD_MISSING не выдаётся при attr allow_missing_courtyard; на реальных библиотеках kicad8/kicad9/special нет ложных error.
- legacy: параметр compat="kicad9"|"fixed" (3D-смещение Of: KiCad 9 пишет дюймы как мм), LegacyFormatError с номером строки; Model: старая форма (at (xyz)) читается в дюймах ×25.4.
- F&B.Cu: в 9.0.6+ KiCad пишет "*.Cu" вместо "F&B.Cu"; наша программа сохраняет исходную форму, expand() должен понимать обе.
- fill: 6.0–8.0 пишут solid/none, 9.0+ yes/no; у примитивов custom-пада — yes/none в 6/7 и yes/no с 8.0: чтение всех форм, запись по профилю версии.
- hide у fp_text user в 9.0+ writer не пишет (парсер превращает скрытый fp_text в скрытое поле) — Text.hide setter на fp_text в 9.0-файле должен всё же писать (hide yes), т.к. парсер 9.0 это принимает.
- Числа: углы < 1e-4 KiCad пишет с экспонентой (FormatAngle без ветки), мы — без; лексер принимает оба.
- Фикстуры tests/fixtures/special/* (221 файл редких конструкций) должны проходить round-trip (уже проходят) и model-тесты (каждое представление читается без исключений на каждом файле).
`

phase('Acceptance')
const acc = await agent(COMMON + SCENARIOS + KNOWN_GAPS + `
ЗАДАЧА: написать ${REPO}/tests/test_acceptance.py — по одному (или несколько) автоматическому тесту на КАЖДЫЙ сценарий 1–10 (для 8 — ссылка на GUI-тест плюс не-GUI проверка через FootprintDocument offscreen), с говорящими именами test_scenario_N_*. Тесты, требующие kicad-cli, используют фикстуру kicad_cli из conftest (KICAD_CLI в env; запусти сам с KICAD_CLI=${KICAD_CLI}). Дополнительно: tests/test_kicad_cli.py — для ВСЕХ фикстур kicad5/kicad6/kicad8/kicad9 (по выборке: каждый 5-й файл, чтобы уложиться в ~2 мин) сохранить через kicadfp в tmp .pretty и прогнать kicad-cli fp upgrade — 0 ошибок; для всех генераторов и результата convert — то же. Также напиши scripts/acceptance_report.py, который выполняет сценарии и печатает отчёт в Markdown (docs/acceptance_report.md) с фактическими числами (файлов проверено, совпадений, версии, время) — запусти его. Все тесты должны проходить; если сценарий выявил дефект в ядре — исправь минимально (с описанием) и добавь регрессионный тест.`,
  { label: 'qa:acceptance', phase: 'Acceptance', effort: 'max', model: 'opus' })

phase('Coverage')
const cov = await agent(COMMON + `
ЗАДАЧА: покрытие. Запусти QT_QPA_PLATFORM=offscreen ${PY} -m pytest -q --cov=kicadfp --cov-report=term-missing (gui исключён в pyproject; отдельно посчитай и с gui). Требование ТЗ: ≥ 80 % по ядру. Для каждого модуля с покрытием < 85 % добавь целевые тесты на непокрытые ветви (ошибки, редкие формы токенов, CLI-ветки, legacy-ветки, render формы площадок). Не пиши бессмысленные тесты «ради процентов» — каждый тест проверяет конкретное поведение с осмысленным assert. Итог: таблица покрытия по модулям в ответе; сохрани отчёт в docs/coverage.md (кратко) — и обнови, если он уже есть.`,
  { label: 'qa:coverage', phase: 'Coverage', effort: 'high', model: 'opus' })

phase('Hunt')
const BUGS_SCHEMA = {
  type: 'object',
  properties: { bugs: { type: 'array', items: { type: 'object', properties: {
    title: { type: 'string' }, file: { type: 'string' }, severity: { type: 'string', enum: ['high', 'medium', 'low'] },
    repro: { type: 'string' }, expected: { type: 'string' }, actual: { type: 'string' } },
    required: ['title', 'file', 'severity', 'repro', 'expected', 'actual'] } } },
  required: ['bugs'],
}
const VERDICT = { type: 'object', properties: { real: { type: 'boolean' }, reason: { type: 'string' } }, required: ['real', 'reason'] }
const HUNTERS = [
  'round-trip и сохранение без потерь на редких конструкциях из полных клонов (custom pads, zones, groups, dimension, fp_text_box, image, teardrops, padstack, чужие генераторы, юникод)',
  'модель: каждый setter каждого класса представления на файлах всех версий (kicad5 module, 6, 8, 9): меняется ровно один токен, форма токена соответствует версии, kicad-cli читает результат',
  'CLI: все команды и опции, пути-каталоги, ошибки, --json, коды возврата, юникод в путях и текстах, set с разными селекторами и типами значений',
  'генераторы и validate: граничные параметры (pins=2, rows=1, отрицательные/нулевые), сравнение с KLC и стандартной библиотекой, ложные срабатывания validate на реальных библиотеках',
  'legacy .mod: реальные старые библиотеки (скачай 2–3 .mod из https://github.com/KiCad/kicad-library/tree/master/modules или иных источников KiCad 4, если сеть доступна; иначе синтетика по спецификации), сравнение с тем, как их читает kicad-cli (kicad-cli 10 умеет читать .mod? проверь: kicad-cli fp upgrade на .mod-файле — если да, сравни площадки/графику с нашим convert численно)',
]
const seen = new Set()
let dry = 0, round = 0
const confirmed = []
while (dry < 2 && round < 4) {
  round++
  const found = (await parallel(HUNTERS.map((h, i) => () => agent(COMMON + `
РОЛЬ: искатель дефектов #${i + 1}, раунд ${round}. Направление: ${h}. Уже известные (не повторяй): ${JSON.stringify([...seen])}. Пиши скрипты в ${SCRATCH}/hunt/r${round}_${i + 1}/ (создай), запускай на реальных данных, ищи РЕАЛЬНЫЕ дефекты (потеря данных, неверный файл, падение, нарушение ТЗ/контракта). Ничего не исправляй. Каждый bug — с точным repro (команда/скрипт) и фактическим выводом.`,
    { label: `hunt:${round}:${i + 1}`, phase: 'Hunt', schema: BUGS_SCHEMA, effort: 'high', model: 'opus' })))).filter(Boolean).flatMap(r => r.bugs || [])
  const fresh = found.filter(b => !seen.has(b.title) && b.severity !== 'low')
  log(`Раунд ${round}: найдено ${found.length}, новых ${fresh.length}`)
  if (!fresh.length) { dry++; continue }
  dry = 0
  fresh.forEach(b => seen.add(b.title))
  const judged = await parallel(fresh.map(b => () =>
    agent(COMMON + `\nРОЛЬ: судья. Проверь заявленный дефект, воспроизведи repro. Дефект: ${JSON.stringify(b)}. Реальный ли он (нарушение ТЗ/контракта/потеря данных/падение), а не вкусовщина? По умолчанию при сомнении — real=false.`,
      { label: `judge:${round}`, phase: 'Hunt', schema: VERDICT, effort: 'medium', model: 'opus' }).then(v => ({ b, real: v && v.real }))))
  const real = judged.filter(j => j.real).map(j => j.b)
  confirmed.push(...real)
  if (real.length) {
    await agent(COMMON + `\nРОЛЬ: исправитель. Исправь подтверждённые дефекты (минимально, с регрессионными тестами), прогони все тесты. Отчёт по каждому.\n${JSON.stringify(real, null, 1)}`,
      { label: `fix:${round}`, phase: 'Hunt', effort: 'high', model: 'opus' })
  }
}
return { acceptance: String(acc).slice(0, 3000), coverage: String(cov).slice(0, 3000), confirmed }
