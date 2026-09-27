export const meta = {
  name: 'kicadfp-core',
  description: 'Реализация ядра kicadfp: sexpr, модель, io, слои, legacy, validate, генераторы, библиотека, render, CLI + тесты, с adversarial-ревью после каждой фазы',
  phases: [
    { title: 'Sexpr', detail: 'дерево S-выражений, prettify, layout 6/7, format_rules; параллельно layers.py' },
    { title: 'Review-Sexpr', detail: 'два ревьюера + исправление' },
    { title: 'Model', detail: 'представления Footprint/Pad/графика/Text/Model + io' },
    { title: 'Review-Model', detail: 'два ревьюера + исправление' },
    { title: 'Modules', detail: 'legacy, validate, generators, library, render параллельно' },
    { title: 'CLI', detail: 'cli.py + интеграция + __init__' },
    { title: 'Review-Core', detail: 'ревью всего ядра, покрытие, исправления' },
  ],
}

const REPO = (typeof args === 'object' && args && args.repo) || '/Users/juli/Desktop/Claude/kicadfp'  // передайте args: {repo: '<путь к репозиторию>'}
const PY = REPO + '/.venv/bin/python'
const SCRATCH = REPO + '/.cache/scratch'
const KSRC = REPO + '/refs/kicad-src'
const KFP = REPO + '/.cache/kfp'
const KICAD_CLI = 'kicad-cli'  // локально на Mac: kicad-cli; в облаке — если установлен

const COMMON = `
Проект: kicadfp — библиотека и редактор файлов посадочных мест KiCad (.kicad_mod / .pretty) на Python.
Репозиторий: ${REPO}. Python: ${PY} (venv, 3.12; pytest, pytest-cov, PySide6 установлены). Запуск тестов: cd ${REPO} && ${PY} -m pytest -q.
ОБЯЗАТЕЛЬНО перед работой прочитай целиком ${REPO}/docs/dev/architecture.md — это контракт API, которому должен соответствовать твой код (имена классов/функций/атрибутов, семантика). Если контракт неполон — принимай решение, совместимое с духом контракта, и запиши его в docstring; если контракт противоречит фактам формата — следуй фактам и ОБЯЗАТЕЛЬНО опиши отклонение в финальном ответе.
Спецификации форматов пишутся ПАРАЛЛЕЛЬНО другой группой агентов и могут ещё отсутствовать в docs/dev/ — если нужного .md нет, работай по исходникам KiCad, реальным файлам и docs/dev/token-inventory.json + layers.json (они уже есть); появившийся позже документ используй для сверки. Спецификации (прочитай те, что относятся к твоей задаче): ${REPO}/docs/dev/format-writer.md (порядок токенов writer'а KiCad по версиям), format-layout.md (раскладка пробелов: алгоритм Prettify 8/9 и таблица 6/7; содержит проверенный порт prettify на Python), format-tokens.md + token-inventory.json (все токены, примеры файлов), layers.md + layers.json (слои, цвета), legacy-mod.md (старый формат .mod), lab-generators.md (геометрия генераторов).
Исходники KiCad для сверки: ${KSRC}/{6.0,7.0,8.0,9.0,master}. Реальные библиотеки: фикстуры ${REPO}/tests/fixtures/{kicad5,kicad6,kicad8,kicad9,kicad10dev,legacy_mod}, полные клоны ${KFP}/{v6.0.0,v7.0.0,v8.0.0,v9.0.0,master} (тысячи файлов; переменная KICADFP_EXTRA_FIXTURES для расширенного прогона, см. tests/conftest.py). kicad-cli 10.0.6 доступен: ${KICAD_CLI} (fp upgrade, fp export svg) — можно использовать для проверки, что KiCad читает наши файлы.
Правила кода: Python >= 3.10, ядро (всё кроме kicadfp/gui и PNG) — ТОЛЬКО стандартная библиотека; идентификаторы английские, docstrings/комментарии/сообщения — на русском; type hints; from __future__ import annotations; без print в библиотечном коде; каждое публичное имя с docstring. Тесты — pytest, в ${REPO}/tests/, используют фикстуры из conftest.py. Не редактируй файлы, не относящиеся к твоей задаче (список ниже); если нужен фикс в чужом модуле — опиши в ответе, что и почему, а для своего модуля сделай обход. Не запускай git commit.
Критерий готовности: все твои тесты проходят (${PY} -m pytest -q tests/<твои файлы>), и общий прогон ${PY} -m pytest -q не ломается из-за тебя. Финальный ответ — резюме: что сделано, отклонения от контракта, известные ограничения, что нужно другим модулям.
`

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          file: { type: 'string' },
          line: { type: 'integer' },
          summary: { type: 'string' },
          evidence: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'file', 'summary', 'evidence', 'fix'],
      },
    },
    tests_pass: { type: 'boolean' },
    notes: { type: 'string' },
  },
  required: ['findings', 'tests_pass'],
}

function reviewPrompt(scope, files, lens) {
  return COMMON + `
РОЛЬ: adversarial-ревьюер (линза: ${lens}). Область: ${scope}. Файлы: ${files.join(', ')}.
Твоя цель — НАЙТИ РЕАЛЬНЫЕ ДЕФЕКТЫ, а не похвалить. Прочитай код и тесты целиком, сверь с контрактом architecture.md и спецификациями docs/dev/*.md, ЗАПУСТИ тесты (${PY} -m pytest -q), напиши собственные проверочные скрипты в ${SCRATCH}/review/ (создай) на реальных фикстурах (в т.ч. полных клонах ${KFP}) и найди: несоответствия спецификации/контракту, ошибки round-trip (потеря данных, изменение неизменённых узлов, различие байт там, где должно совпадать), ошибки в граничных случаях (экранирование строк, unicode, CRLF, BOM, числа вида 1. .5 -0 +1 1e-5, пустые строки "", вложенные кавычки, пустые списки, отсутствующие необязательные токены, KiCad 5 «module», версия без generator), неверное форматирование чисел, неправильную вставку новых токенов (порядок), падения на реальных файлах, слабые/ложные тесты. Каждое утверждение подтверди воспроизводимым доказательством (команда + вывод). НИЧЕГО НЕ ИСПРАВЛЯЙ в репозитории — только отчёт. Не сообщай стилистику и вкусовщину. Верни структурированный список findings (severity high = потеря данных/неверный файл/падение на реальных данных/нарушение контракта; medium = неверное поведение в редком случае; low = мелочи).`
}

function fixPrompt(scope, files, findings) {
  return COMMON + `
РОЛЬ: исправитель. Область: ${scope}. Файлы, которые можно менять: ${files.join(', ')} (+ соответствующие тесты). Ниже — подтверждённые замечания ревьюеров. Для КАЖДОГО: воспроизведи, исправь код, добавь регрессионный тест; если замечание ошибочно — докажи (команда + вывод) и пропусти. После всех исправлений прогони весь набор тестов. Верни отчёт: по каждому замечанию — «исправлено (тест X)» или «отклонено (причина)».
ЗАМЕЧАНИЯ:
${JSON.stringify(findings, null, 1)}`
}

async function reviewAndFix(scope, files, phaseName, rounds = 2) {
  for (let r = 1; r <= rounds; r++) {
    const lenses = ['корректность и соответствие контракту/спецификации', 'round-trip на реальных данных и граничные случаи входа']
    const reviews = (await parallel(lenses.map((lens, i) => () =>
      agent(reviewPrompt(scope, files, lens), { label: `review:${scope}:${i + 1}:r${r}`, phase: phaseName, schema: REVIEW_SCHEMA, effort: 'high', model: 'opus' })
    ))).filter(Boolean)
    const findings = reviews.flatMap(x => x.findings || []).filter(f => f.severity !== 'low')
    log(`${scope}: раунд ${r}: ${findings.length} замечаний (high: ${findings.filter(f => f.severity === 'high').length})`)
    if (!findings.length) return { rounds: r, fixed: [] }
    const fix = await agent(fixPrompt(scope, files, findings), { label: `fix:${scope}:r${r}`, phase: phaseName, effort: 'high', model: 'opus' })
    if (r === rounds) return { rounds: r, lastFix: fix, remaining: findings.length }
  }
}

// ---------------- Phase 1: sexpr + format_rules (+ layers параллельно) ----------------
phase('Sexpr')
const [sexprResult, layersResult] = await parallel([
  () => agent(COMMON + `
ЗАДАЧА: kicadfp/sexpr.py и kicadfp/format_rules.py УЖЕ РЕАЛИЗОВАНЫ (вместе с tests/test_sexpr.py и tests/test_roundtrip.py; все тесты проходят; round-trip на 12 191 файле полных клонов даёт 100 % равенство деревьев и байт-в-байт для файлов, записанных самим KiCad). Твоя роль — adversarial-ревьюер и «закалка» этих двух модулей: прочитай их целиком вместе с architecture.md §3–4, docs/dev/format-layout.md и format-writer.md (если уже появились), исходники Prettify (${KSRC}/9.0 и 8.0 kicad_io_utils.cpp), dsnlexer.cpp и richio.cpp (${KSRC}/9.0), writer 6.0/7.0 (pcb_plugin.cpp). Ищи РЕАЛЬНЫЕ дефекты: расхождения с DSNLEXER (что считается символом, экранирование, комментарии, CR/LF, BOM, «\\» в конце строки, пустые строки, вложенные скобки в строках), расхождения порта Prettify с C++ (сравни построчно), ошибки Node.set/insert/set_flag при вставке по таблице порядка (напиши тесты на все ветки: предшественники есть/нет, неизвестные узлы между ними, атомы после узлов), format_number на граничных значениях (сравни с выводом C printf через ctypes или с таблицей из numfmt_check.py в ${SCRATCH}/research/), equal/diff, производительность (профилируй parse на 1400 файлах kicad8; цель < 4 мс/файл; если можно ускорить в 2 раза без усложнения — сделай), полноту таблиц *_ORDER в format_rules.py против writer'а 9.0/8.0/7.0/6.0 (каждый токен, который пишет KiCad, должен быть в таблице в правильной позиции; сверь с docs/dev/token-inventory.json: все имена дочерних узлов footprint/pad/fp_text/property/fp_*/model из реальных файлов должны быть в KNOWN_FOOTPRINT_CHILDREN или соответствующих таблицах), пороги версий в profile_for (проверь по token-inventory.json/фикстурам: с какой версии uuid вместо tstamp, (hide yes), кавычки в layers, property вместо fp_text, stroke, generator_version; исправь пороги, если фактические данные противоречат). Всё найденное ИСПРАВЬ прямо в коде (минимально, не переписывая архитектуру и публичный API) и добавь регрессионные тесты в tests/test_sexpr.py / tests/test_format_rules.py (создай). Прогони tests/test_roundtrip.py и расширенный прогон KICADFP_EXTRA_FIXTURES="${KFP}/v8.0.0:${KFP}/v9.0.0:${KFP}/master:${KFP}/v7.0.0:${KFP}/v6.0.0" ${PY} -m pytest tests/test_roundtrip.py -q -m slow — ничего не должно сломаться. В ответе: список найденных дефектов (с доказательством) и что исправлено.
Можно менять только: kicadfp/sexpr.py, kicadfp/format_rules.py, tests/test_sexpr.py, tests/test_format_rules.py, tests/test_roundtrip.py.`,
    { label: 'harden:sexpr', phase: 'Sexpr', effort: 'max', model: 'opus' }),
  () => agent(COMMON + `
ЗАДАЧА: реализовать ${REPO}/kicadfp/layers.py по architecture.md §5 на основе docs/dev/layers.md и docs/dev/layers.json (данные — в код как константы, без чтения json во время выполнения; json остаётся справочным). Включи: COPPER_LAYERS, TECH_LAYERS, USER_LAYERS (в т.ч. User.1..User.9 и расширенные слои 9.0 если они есть в спецификации), ALL_LAYERS, WILDCARDS, PAD_LAYER_PRESETS, COLORS (hex, все слои + служебные ключи background/grid/pad_th/hole/npth/selection/anchor/cursor), DRAW_ORDER, LEGACY_INDEX, LEGACY_MASK_BITS, функции is_valid_layer (канонические имена + групповые обозначения + учёт того, что парсер KiCad 9 принимает), expand, legacy_mask_to_layers(mask, pad_type) (алгоритм из legacy-mod.md/layers.md — точная реплика legacy plugin), is_copper/is_front/is_back/flip_layer (F.Cu<->B.Cu, F.SilkS<->B.SilkS, ..., In-слои для 2-слойной платы остаются), layer_side(name) -> "F"|"B"|None, display_name(name) (русское/человекочитаемое имя для GUI, напр. «F.SilkS (шелкография, верх)»). Тесты tests/test_layers.py: полнота списков против layers.json, все групповые обозначения из инвентаризации token-inventory.json (все значения layers, встречающиеся в реальных файлах, валидны), пресеты, flip, legacy mask для 00E0FFFF/00808000/00888000/00E00001 (ожидания из legacy-mod.md). Можно менять только kicadfp/layers.py и tests/test_layers.py.`,
    { label: 'impl:layers', phase: 'Sexpr', effort: 'high', model: 'opus' }),
])

phase('Review-Sexpr')
const rSexpr = await reviewAndFix('sexpr', ['kicadfp/sexpr.py', 'kicadfp/format_rules.py', 'kicadfp/layers.py'], 'Review-Sexpr', 1)

// ---------------- Phase 2: model + io ----------------
phase('Model')
const modelResult = await agent(COMMON + `
ВНИМАНИЕ: kicadfp/model.py уже частично написан предыдущим агентом, прерванным из-за сбоя API (около 1000 строк, модуль импортируется, тестов к нему нет). Прочитай его целиком, оцени качество и соответствие контракту и ПРОДОЛЖИ/ДОРАБОТАЙ его, а не переписывай с нуля без веской причины (если качество плохое — можно переписать, обоснуй в ответе). ЗАДАЧА: реализовать ${REPO}/kicadfp/model.py и ${REPO}/kicadfp/io.py по architecture.md §6–7 поверх готовых kicadfp/sexpr.py, kicadfp/format_rules.py, kicadfp/layers.py, kicadfp/geometry.py (прочитай их код и docstrings: используй ИМЕННО их API). Спецификации: format-writer.md (условия записи токенов — например угол в (at) пишется только если != 0; hide/locked формы по версии; layers в кавычках по версии), format-tokens.md (какие формы принимать на чтение: fp_text reference/value/user; property с эффектами; (at x y [angle] [unlocked]); width vs stroke; fill формы; tstamp/uuid; KiCad 5 «module»: unquoted атрибуты, fp_arc с angle, model (at (xyz)), fp_text hide голый и т.д.), legacy-mod.md не нужен.
Ключевые требования:
1. Представления не копируют данные; setter меняет ТОЛЬКО свой токен (тест: diff дерева до/после присваивания одного атрибута содержит ровно один узел). Не пересоздавай узел целиком при изменении одного значения; не переупорядочивай существующие токены; новые токены вставляй по *_ORDER.
2. Версионность: FormatProfile от версии корня (fp.version; для «module» — 0). Footprint.new создаёт по DEFAULT_VERSION в стиле KiCad 9 (generator "kicadfp", generator_version = __version__ первые две цифры). Pad.new/Text.new/... принимают profile; Footprint.add(view) при добавлении представления с другим профилем — конвертирует узел под профиль корпуса (минимум: uuid/tstamp, stroke/width, кавычки layers, hide-формы). uuid для новых элементов — uuid4 (Str).
3. Text над fp_text И над property (8+): kind по имени/первому атому; text для property — второй атом. Footprint.texts включает property-узлы с текстовыми атрибутами (at/layer/effects); Footprint.properties — все property. reference/value — свойства с поиском в обоих формах. Footprint.new создаёт Reference/Value в форме профиля (8+: property).
4. Drill: (drill [oval] w [h] [(offset x y)]) — все формы; drill присвоение float/tuple/None/Drill.
5. Pad.layers, set_layers(preset), is_tht/is_smd; Pad.rotate вращает и положение вокруг origin, и собственный угол; Pad.bbox с учётом формы/поворота (rect/roundrect/oval/circle/trapezoid — описанный прямоугольник; custom — по anchor size + primitives bbox приближённо).
6. Graphic: Line/Rect/Circle/Arc/Poly/Curve — kind, координаты, width (stroke/width по узлу: если в узле есть stroke — менять его; иначе width; если ни того ни другого — создать по профилю), stroke_type, fill (чтение всех форм: yes/no/solid/none/отсутствует; запись по профилю: 8+ (fill yes|no); 6/7 (fill solid|none)), move/rotate/mirror/bbox/length/points; Arc: чтение обоих форм (start/mid/end и KiCad 5 start=центр/end/angle — через geometry.arc_three_points с учётом знака), setters на KiCad 5-узле конвертируют узел в start/mid/end (единственный случай перестройки узла, задокументировать); center/radius/start_angle/end_angle вычисляемые. Poly.points setter переписывает pts.
7. Footprint: name (Str в 6+, Sym в module), version/generator/generator_version/layer/descr/tags/attrs (set-подобный объект AttrSet с add/discard/clear/__contains__/__iter__/__len__, запись атомов в порядке KiCad)/properties (MutableMapping)/clearance/... /uuid/locked/placed/tedit/path/autoplace_cost90/180/private_layers/net_tie_pad_groups/at; pads/graphics/texts/models/zones/groups/unknown; pad(number)/pads_by_number; add/remove (по идентичности узла; add вставляет в конец своей группы через insert_in_group); new_pad/new_line/new_rect/new_circle/new_arc/new_poly/new_text/new_model; bbox(layers=None, include_texts=False) — объединение bbox площадок (всех) и графики на указанных слоях (по умолчанию все, кроме текстов); move/rotate/flip (семантика flip по контракту: x -> -x, слои F<->B у всех элементов и у корпуса, justify mirror у текстов, углы текстов/площадок при отражении: как KiCad — angle -> -angle? Проверь в footprint.cpp FOOTPRINT::Flip и PAD::Flip (скачай pcbnew/footprint.cpp и pcbnew/pad.cpp 9.0 при необходимости) и реализуй так же); renumber_pads(rule, start, order); validate() — ленивый импорт kicadfp.validate (модуль появится позже: если ImportError — вернуть []); to_sexpr; dumps; copy; upgrade(version) — реализуй базово: tedit удалить, tstamp->uuid, fp_text->property для reference/value, width->stroke, (fill none/solid)->(fill no/yes), голые hide/locked -> (hide yes)/(locked yes), layers в кавычки, generator в кавычки, version/generator_version обновить, (angle) дуги -> mid, model (at)->(offset) — с тестом на KiCad 6 и KiCad 5 фикстурах: после upgrade dumps() даёт файл в стиле 9.0, который читает kicad-cli (${KICAD_CLI} fp upgrade на копии в каталоге .pretty — проверь сам хотя бы на одном файле; kicad-cli пишет в stderr при ошибках).
8. io.py: load/loads/save/dumps/ValidationError по контракту: определение формата по началу текста (после BOM/пробелов): "(footprint"/"(module" -> sexpr; "PCBNEW-LibModule" -> ленивый импорт kicadfp.legacy (если модуль отсутствует — понятная ошибка); иначе SexprSyntaxError. save: атомарно (tempfile в том же каталоге + os.replace), UTF-8, LF, strict через ленивый импорт validate. dumps(fp, style) -> sexpr.dumps(fp.node, style=style, version=fp.version).
9. kicadfp/__init__.py: экспорт load, loads, save, dumps, Footprint, Pad, Drill, Line, Rect, Circle, Arc, Poly, Curve, Text, Model, BBox, SexprSyntaxError, __version__; Library/validate/Issue/generators — добавит интеграционный агент позже (оставь комментарий-заглушку; можно сделать ленивый __getattr__ для Library/validate/Issue, чтобы import kicadfp работал до появления модулей).
10. Тесты: tests/test_model_footprint.py, test_model_pad.py, test_model_graphics.py, test_model_text.py, test_model_model3d.py, test_io.py: чтение всех атрибутов на DIP-14 всех версий (kicad5/6/8/9) с конкретными ожидаемыми значениями; каждый setter: изменение ровно одного токена (через sexpr.diff), отсутствие изменений в остальном файле (dumps до/после отличаются ровно одной строкой для 8+), корректная форма нового токена по версии; создание нового корпуса Footprint.new + new_pad + ... -> dumps -> parse -> equal и чтение kicad-cli (${KICAD_CLI} fp upgrade на временной .pretty копии — тест с маркером kicad_cli, пропускается без KICAD_CLI; conftest уже даёт фикстуру kicad_cli, задай KICAD_CLI в env при запуске сам); move/rotate/flip/renumber; bbox на DIP-14 (ожидаемо ~ -1.06..8.67 × -1.53..16.77 по CrtYd v8); io: атомарная запись (после save файл читается и равен), ошибка синтаксиса содержит строку/позицию, BOM/CRLF читаются, save strict. Сценарий 3 из ТЗ: добавить в DIP-14 неизвестный узел (example_token 1 2) в текст, load, изменить pad 1 size, save -> узел на месте без изменений, diff деревьев = только pad 1.
Можно менять только: kicadfp/model.py, kicadfp/io.py, kicadfp/__init__.py, tests/test_model_*.py, tests/test_io.py. Если найдёшь баг в sexpr.py/format_rules.py/layers.py/geometry.py — исправь минимально и опиши в ответе (с тестом).`,
  { label: 'impl:model', phase: 'Model', effort: 'max', model: 'opus' })

phase('Review-Model')
const rModel = await reviewAndFix('model', ['kicadfp/model.py', 'kicadfp/io.py', 'kicadfp/__init__.py'], 'Review-Model', 2)

// ---------------- Phase 3: modules in parallel ----------------
phase('Modules')
const MODULES = [
  { key: 'legacy', files: ['kicadfp/legacy.py', 'tests/test_legacy.py'], prompt: `
ЗАДАЧА: kicadfp/legacy.py по architecture.md §8 и docs/dev/legacy-mod.md (точная реплика чтения PCBNEW-LibModule-V1 современным KiCad: единицы deci-mils/mm по заголовку, округление, слои по маскам, тексты, графика (DA -> start/mid/end через geometry.arc_three_points с правильным знаком), $PAD -> Pad (типы STD/SMD/CONN/HOLE), $SHAPE3D -> model, Cd/Kw/At/.SolderMask.../Op). Результат — Footprint версии DEFAULT_VERSION через model API (Footprint.new + new_pad/new_line/...), с новыми uuid, generator "kicadfp". read_library/loads_library/convert/is_legacy. Тесты tests/test_legacy.py: фикстура tests/fixtures/legacy_mod/My_lib.mod — 3 модуля, ожидаемые значения из legacy-mod.md (таблицы pad/тексты/графика), convert -> каталог .pretty с 3 файлами, каждый читается load() и проходит round-trip, и читается kicad-cli (маркер kicad_cli); синтетические тесты: Units mm, овальное сверло, HOLE, SMD с маской, DA дуга, DP полигон, T2 текст с зеркалом/невидимостью, экранированные кавычки в Cd, CRLF, несколько модулей, отсутствие $INDEX, ошибки формата (нет заголовка -> понятное исключение LegacyFormatError с номером строки).` },
  { key: 'validate', files: ['kicadfp/validate.py', 'tests/test_validate.py'], prompt: `
ЗАДАЧА: kicadfp/validate.py по architecture.md §10 (Issue, реестр правил через декоратор rule(code, level), validate(fp, strict=False), has_errors). Все правила из ТЗ 4.1.5 с кодами и русскими сообщениями, включающими идентификатор элемента (номер площадки, тип графики и слой, координаты). Слои проверяй через kicadfp.layers.is_valid_layer; перечисления — PAD_TYPES/PAD_SHAPES/attr-флаги/fill/stroke type/слой корпуса F.Cu|B.Cu. Правило дублей — warning с текстом о том, что в KiCad одинаковые номера означают один вывод. Отверстие больше площадки — по каждой оси с учётом овального сверла и offset. Дополнительные разумные правила (warning): площадка с нулевым номером у thru_hole/smd (не для np_thru_hole — там пустой номер норма), пустое descr/tags — НЕ надо. Каждое правило независимо (исключение в одном не роняет остальные — оборачивай, превращай в Issue level error код RULE_CRASH). Тесты: на всех фикстурах kicad8 validate() не даёт error (только warnings допускаются — проверь и, если реальные библиотеки дают error по какому-то правилу, разберись, кто прав: скорее правило слишком строгое); синтетические случаи для каждого правила (сценарий 6 ТЗ: drill 1.5 при size 1.3 -> error «отверстие больше площадки»); strict-сохранение через io.save(strict=True) -> ValidationError.` },
  { key: 'generators', files: ['kicadfp/generators/*.py', 'tests/test_generators.py'], prompt: `
ЗАДАЧА: пакет kicadfp/generators по architecture.md §11 и docs/dev/lab-generators.md: _common.py (тексты Reference/Value/\${REFERENCE}, courtyard по bbox с отступом и округлением к 0.01, контуры silk/fab, helper для добавления pad-рядов), dip.py (dip(pins, pitch=2.54, row_pitch=7.62, pad_size=(1.6,1.6), drill=0.8, first_square=True, name=None, body_width=None, body_length=None, ...)), pin_header.py (pin_header(rows, cols, pitch=2.54, row_pitch=None, pad_size=1.7, drill=1.0, first_square=True, mounting_holes=None, name=None, numbering="column"|"row"|"zigzag")), axial.py (resistor(pitch, body_length, body_diameter, pad_size, drill, name), diode(..., cathode_band=True)), radial.py (capacitor_radial(pitch, diameter, pad_size, drill, polarized=False, name)), transistor.py (transistor_inline(pins=3, pitch=1.27 или 2.54, pad_size, drill, body_width, name) — TO-92 inline), lab.py (lab_dip14(), lab_mlt(), lab_snp8() — ТОЧНО по lab-generators.md: площадки 1.3, отверстия 0.8, шаг 2.5, ряды 7.5/5.0, первая квадратная, контуры по методичке, монтажные отверстия 3 мм). __init__.py: экспорт + GENERATORS реестр {имя: функция} + describe(name) -> список параметров (имя, тип, умолчание, описание из docstring) для CLI/GUI; from_json(kind, params_dict). Пример В.2 ТЗ должен работать буквально: pin_header(rows=2, cols=4, pitch=2.5, row_pitch=5.0, pad_size=1.3, drill=0.8, first_square=True, mounting_holes=[(11.25,-5.0,3.0),(11.25,15.0,3.0)], name="snp8"). Все генераторы: attr through_hole, descr/tags осмысленные, Reference F.SilkS над корпусом, Value F.Fab под, \${REFERENCE} на F.Fab по центру, F.SilkS контур (0.12), F.Fab контур (0.1), F.CrtYd прямоугольник (0.05) с отступом 0.25 (округление 0.01), uuid везде. Тесты: каждый генератор -> validate() без error и с CrtYd; dumps -> parse -> equal; lab_*: точные координаты/размеры площадок и первая квадратная (по таблицам lab-generators.md); dip(14) сравнить с DIP-14_W7.62mm из kicad8 по положению площадок (совпадение x/y всех 14 площадок); pin_header 1x4 и 2x4 — с PinHeader_1x04/2x04_P2.54mm_Vertical по площадкам; from_json; kicad-cli читает результат (маркер kicad_cli).` },
  { key: 'library', files: ['kicadfp/library.py', 'tests/test_library.py'], prompt: `
ЗАДАЧА: kicadfp/library.py по architecture.md §9 (Library: names/list/get/add/save/save_all/remove/rename/copy_to/path_of/validate_all/__iter__/__len__/__contains__, create=True). Имена файлов: <name>.kicad_mod; при add/rename поле name внутри корпуса синхронизируется с именем; недопустимые для файловой системы символы в имени (/, \\, :, *, ?, ", <, >, |) — как KiCad: LIB_ID::FixIllegalChars заменяет на '_' — реализуй sanitize_name с тем же поведением и ValueError при пустом имени. Запись через io.save (атомарно). Тесты: tmp_lib фикстура; сценарий 9 ТЗ (copy_to с переименованием: в целевой появился файл с новым именем и полем name, исходный файл байт-в-байт не изменился); add/overwrite/FileExistsError; rename; remove; list на kicad8/Package_DIP.pretty (281 имя); get кэш; validate_all.` },
  { key: 'render', files: ['kicadfp/render.py', 'tests/test_render.py'], prompt: `
ЗАДАЧА: kicadfp/render.py по architecture.md §12: render_svg на stdlib (xml.etree или ручная сборка строк): фон, сетка (опционально), элементы по слоям в порядке layers.DRAW_ORDER цветами layers.COLORS: графика (line/rect/circle/arc через geometry.arc_points или SVG arc path/poly/curve — с шириной stroke и fill), площадки (thru_hole: медь на *.Cu цветом pad_th, отверстие; smd: цвет слоя F.Cu/B.Cu; формы circle/rect/oval/roundrect (rx)/trapezoid/custom (anchor + primitives)); повороты через transform; тексты (Reference/Value/user) простым <text> с размером шрифта = font_size_y и учётом hide/mirror/justify/угла; модель не рисуется; viewBox по bbox с полями; масштаб scale px/мм. Параметр layers — фильтр. save_svg; save_png через PySide6 (QtSvg QSvgRenderer -> QImage -> save), при отсутствии PySide6 — RuntimeError с подсказкой pip install kicadfp[png]. Тесты: SVG валидный XML (ElementTree.fromstring), содержит нужное число элементов для DIP-14 (14 площадок), фильтр слоёв, PNG создаётся (если PySide6 доступен, QT_QPA_PLATFORM=offscreen), рендер всех фикстур kicad8 без исключений (быстро — не открывать PNG).` },
]
const modResults = await parallel(MODULES.map(m => () =>
  agent(COMMON + `\nМожно менять только: ${m.files.join(', ')} (создать). Ядро уже реализовано: kicadfp/sexpr.py, format_rules.py, layers.py, geometry.py, model.py, io.py — прочитай их и используй их API.` + m.prompt,
    { label: 'impl:' + m.key, phase: 'Modules', effort: 'high', model: 'opus' }).then(r => ({ key: m.key, result: r }))
))

// ---------------- Phase 4: CLI + integration ----------------
phase('CLI')
const cliResult = await agent(COMMON + `
ЗАДАЧА: (1) kicadfp/cli.py по architecture.md §13 — все команды info/list/validate/set/pads/gen/fmt/convert/render/gui, --version, --json где указано, коды возврата (0 ок, 1 замечания/различия, 2 ошибка входа/разбора), русские сообщения; set: селекторы по контракту (pad[N] по НОМЕРУ площадки (строка), pad[*], pad[#i] по индексу; text[reference|value|user:N]; graphic[i]; model[i]; footprint.<attr>), значение приводится к типу атрибута (float/int/bool/str/список через запятую); без --write/-o — печать результата в stdout (dumps) и сообщение, что файл не изменён; путь-каталог .pretty — применить ко всем корпусам. gen: параметры из generators.describe(name) -> argparse-опции --pins/--pitch/--row-pitch..., --params file.json, --list. fmt: --check/--write/--style. render: -o .svg/.png. gui: ленивый импорт kicadfp.gui.main. (2) Интеграция: kicadfp/__init__.py — добавить экспорт Library, validate, Issue, ValidationError, generators (модуль), legacy (модуль), render (модуль); убедиться, что import kicadfp работает без PySide6. (3) Прогнать ВЕСЬ набор тестов; исправить межмодульные несоответствия (например, generators ожидали другой API model) — минимальные правки в любом модуле ядра с описанием в ответе. (4) tests/test_cli.py: каждая команда через subprocess (${PY} -m kicadfp ...) и через cli.main([...]) с capsys: info/pads/list/validate (+--json), set --write и -o (сценарий: kicadfp set dip14 "pad[*].drill" 0.8 --write), gen dip --pins 14 --pitch 2.5 --row-pitch 7.5 -o ..., fmt --check/--write (на kicad8 файле fmt --check возвращает 0), convert My_lib.mod -o tmp.pretty, render -o svg, --version печатает kicadfp X.Y.Z, ошибка синтаксиса -> код 2 и «строка N, позиция M». Добавь kicadfp/__main__.py (python -m kicadfp). (5) Покрытие: ${PY} -m pytest --cov=kicadfp --cov-report=term-missing -q — приведи итоговый процент в ответе; если < 80 % по ядру (без gui) — добавь тесты на непокрытые ветви.
Можно менять: kicadfp/cli.py, kicadfp/__main__.py, kicadfp/__init__.py, tests/test_cli.py, + минимальные правки в других модулях ядра при интеграции (с описанием).`,
  { label: 'impl:cli+integration', phase: 'CLI', effort: 'max', model: 'opus' })

phase('Review-Core')
const rCore = await reviewAndFix('core', ['kicadfp/*.py', 'kicadfp/generators/*.py'], 'Review-Core', 2)

return { sexpr: String(sexprResult).slice(0, 3000), layers: String(layersResult).slice(0, 1500), rSexpr, model: String(modelResult).slice(0, 3000), rModel, modules: modResults.filter(Boolean).map(m => ({ key: m.key, result: String(m.result).slice(0, 1500) })), cli: String(cliResult).slice(0, 3000), rCore }
