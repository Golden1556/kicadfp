"""Чтение и проверка .pro (wxFileConfig / INI) глазами EESchema bzr2986."""

from __future__ import annotations

import io
from collections import OrderedDict
from typing import List, Tuple

ProjectConfig = 'OrderedDict[str, OrderedDict[str, str]]'


class ProLoadError(Exception):
    pass


def parse_project(text: str) -> 'OrderedDict[str, OrderedDict[str, str]]':
    """Разбор INI с сохранением порядка и регистра ключей. Секция '' — корень."""
    cfg: 'OrderedDict[str, OrderedDict[str, str]]' = OrderedDict()
    cfg[''] = OrderedDict()
    cur = cfg['']
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip().strip('/')
            cur = cfg.setdefault(name, OrderedDict())
            continue
        if '=' not in line:
            raise ProLoadError('malformed line: %r' % raw)
        k, v = line.split('=', 1)
        cur[k.strip()] = v.strip()
    return cfg


def read_project(path: str) -> 'OrderedDict[str, OrderedDict[str, str]]':
    with io.open(path, 'rb') as fh:
        data = fh.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('cp1251')
    return parse_project(text)


def eeschema_libraries(cfg) -> List[str]:
    """PARAM_CFG_LIBNAME_LIST::ReadParam (projet_config.cpp:758-781):
    LibName1, LibName2, ... до первого отсутствующего/пустого."""
    sec = cfg.get('eeschema/libraries', {})
    out = []
    i = 1
    while True:
        v = sec.get('LibName%d' % i, '')
        if not v:
            break
        out.append(v)
        i += 1
    return out


def check_project(cfg) -> Tuple[bool, List[str]]:
    """Возвращает (eeschema_будет_читать_файл, замечания)."""
    notes: List[str] = []
    ok = True
    ee = cfg.get('eeschema')
    if ee is None:
        ok = False
        notes.append('no [eeschema] section: ReCreatePrjConfig reads version=0 and discards the file')
    else:
        try:
            ver = int(ee.get('version', '0'))
        except ValueError:
            ver = 0
        if ver <= 0:
            ok = False
            notes.append('[eeschema] version missing or <= 0: whole .pro is ignored, kicad.pro template used instead')
    libs = eeschema_libraries(cfg)
    sec = cfg.get('eeschema/libraries', {})
    declared = [k for k in sec if k.startswith('LibName')]
    if len(libs) < len(declared):
        notes.append('LibName numbering has a gap: only %d of %d entries are read' % (len(libs), len(declared)))
    if not libs:
        notes.append('no libraries listed: EESchema will force-load "power"')
    for l in libs:
        if l.lower().endswith('.lib'):
            notes.append('library %r: extension is forced to .lib by EESchema (double extension .lib.lib)' % l)
        if '\\' in l:
            notes.append('library %r: paths must use "/" (stored in Unix notation)' % l)
    return ok, notes
