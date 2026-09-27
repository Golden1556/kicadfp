"""Запись проектного файла .pro (wxFileConfig / INI).

Структура и набор ключей взяты из реального файла, созданного KiCad
пользователя (testing_data/346_8.pro), а секция [eeschema] сверена с
SCH_EDIT_FRAME::GetProjectFileParameters (eeschema/eeschema_config.cpp:263-344).

Критично (common/projet_config.cpp:84-96): в группе приложения обязан быть
``version`` > 0, иначе файл целиком игнорируется и берётся шаблон kicad.pro.
Список библиотек: LibName1, LibName2, ... подряд, чтение до первого пустого
(common/projet_config.cpp:758-781).
"""

from __future__ import annotations

import io
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence

from .textio import kicad_date

# Стандартный список библиотек EESchema, который менеджер KiCad кладёт в новый
# проект (порядок из testing_data/346_8.pro).
DEFAULT_EESCHEMA_LIBS: List[str] = [
    'power', 'device', 'transistors', 'conn', 'linear', 'regul', '74xx', 'cmos4000',
    'adc-dac', 'memory', 'xilinx', 'special', 'microcontrollers', 'dsp', 'microchip',
    'analog_switches', 'motorola', 'texas', 'intel', 'audio', 'interface',
    'digital-audio', 'philips', 'display', 'cypress', 'siliconi', 'opto', 'atmel',
    'contrib', 'valves',
]

DEFAULT_PCBNEW_LIBS: List[str] = [
    'sockets', 'connect', 'discret', 'pin_array', 'divers', 'libcms', 'display',
    'valves', 'led', 'dip_sockets',
]

# Параметры [eeschema] в порядке GetProjectFileParameters (значения по умолчанию из кода).
EESCHEMA_PARAMS: List[tuple] = [
    ('LibDir', ''),
    ('NetFmt', '1'),        # NET_TYPE_PCBNEW (netlist_control.h:81)
    ('HPGLSpd', '20'),
    ('HPGLDm', '15'),
    ('HPGLNum', '1'),
    ('offX_A4', '0'), ('offY_A4', '0'),
    ('offX_A3', '0'), ('offY_A3', '0'),
    ('offX_A2', '0'), ('offY_A2', '0'),
    ('offX_A1', '0'), ('offY_A1', '0'),
    ('offX_A0', '0'), ('offY_A0', '0'),
    ('offX_A', '0'), ('offY_A', '0'),
    ('offX_B', '0'), ('offY_B', '0'),
    ('offX_C', '0'), ('offY_C', '0'),
    ('offX_D', '0'), ('offY_D', '0'),
    ('offX_E', '0'), ('offY_E', '0'),
    ('RptD_X', '0'),
    ('RptD_Y', '100'),
    ('RptLab', '1'),
    ('LabSize', '60'),      # DEFAULT_SIZE_TEXT
]

# Секции cvpcb/pcbnew — копия из файла пользователя (eeschema их не читает).
CVPCB_PARAMS: List[tuple] = [
    ('NetITyp', '0'), ('NetIExt', '.net'), ('PkgIExt', '.pkg'),
    ('NetDir', ''), ('LibDir', ''), ('NetType', '0'),
]

PCBNEW_PARAMS: List[tuple] = [
    ('PadDrlX', '320'), ('PadDimH', '600'), ('PadDimV', '600'), ('PadForm', '1'),
    ('PadMask', '14745599'), ('ViaDiam', '450'), ('ViaDril', '250'), ('Isol', '60'),
    ('Countlayer', '2'), ('Lpiste', '170'), ('RouteTo', '15'), ('RouteBo', '0'),
    ('TypeVia', '3'), ('Segm45', '1'), ('Racc45', '1'), ('Unite', '0'), ('SegFill', '1'),
    ('SegAffG', '0'), ('NewAffG', '1'), ('PadFill', '1'), ('PadAffG', '1'), ('PadSNum', '1'),
    ('ModAffC', '0'), ('ModAffT', '0'), ('PcbAffT', '0'), ('SgPcb45', '1'),
    ('TxtPcbV', '800'), ('TxtPcbH', '600'), ('TxtModV', '600'), ('TxtModH', '600'),
    ('TxtModW', '120'), ('HPGLnum', '1'), ('HPGdiam', '15'), ('HPGLSpd', '20'),
    ('HPGLrec', '2'), ('HPGLorg', '0'), ('GERBmin', '15'), ('VEgarde', '100'),
    ('DrawLar', '150'), ('EdgeLar', '150'), ('TxtLar', '120'), ('MSegLar', '150'),
    ('ForPlot', '1'), ('WpenSer', '10'), ('UserGrX', '0,01'), ('UserGrY', '0,01'),
    ('UserGrU', '1'), ('DivGrPc', '1'), ('TimeOut', '600'), ('MaxLnkS', '3'),
    ('ShowRat', '0'), ('ShowMRa', '1'),
]


def build_project(project_libs: Sequence[str],
                  standard_libs: Optional[Sequence[str]] = None,
                  pcb_libs: Optional[Sequence[str]] = None,
                  date: Optional[str] = None,
                  last_client: str = 'kicad',
                  eeschema_overrides: Optional[Dict[str, str]] = None,
                  lib_dir: str = '', project_first: bool = True,
                  pcbnew_overrides: Optional[Dict[str, str]] = None) -> 'OrderedDict[str, OrderedDict[str, str]]':
    """Собирает содержимое .pro как OrderedDict {section: {key: value}}.
    Секция '' — ключи верхнего уровня. Библиотеки проекта ставятся ПЕРВЫМИ:
    CMP_LIBRARY::FindLibraryComponent (class_library.cpp:957-973) берёт первое
    совпадение имени в порядке LibName1..N (кеш всегда последний), а стоковая
    power.lib содержит GND/VCC — иначе они перекроют символы проекта."""
    std = list(DEFAULT_EESCHEMA_LIBS if standard_libs is None else standard_libs)
    pcb = list(DEFAULT_PCBNEW_LIBS if pcb_libs is None else pcb_libs)
    cfg: 'OrderedDict[str, OrderedDict[str, str]]' = OrderedDict()
    cfg[''] = OrderedDict([('update', date or kicad_date()), ('version', '1'),
                           ('last_client', last_client)])
    cfg['cvpcb'] = OrderedDict([('version', '1')] + CVPCB_PARAMS)
    cfg['cvpcb/libraries'] = OrderedDict([('EquName1', 'devcms')])
    pcb_sec = OrderedDict([('version', '1')] + PCBNEW_PARAMS)
    for k, v in (pcbnew_overrides or {}).items():
        pcb_sec[k] = str(v)
    cfg['pcbnew'] = pcb_sec
    cfg['pcbnew/libraries'] = OrderedDict([('LibDir', '')] +
                                          [('LibName%d' % (i + 1), n) for i, n in enumerate(pcb)])
    ee = OrderedDict([('version', '1')] + EESCHEMA_PARAMS)
    ee['LibDir'] = lib_dir.replace('\\', '/')
    for k, v in (eeschema_overrides or {}).items():
        ee[k] = str(v)
    cfg['eeschema'] = ee
    if project_first:
        pcb = [l for l in pcb if l not in project_libs and l in DEFAULT_PCBNEW_LIBS] if pcb_libs is None else pcb
        libs = list(project_libs) + [l for l in std if l not in project_libs]
    else:   # как делает диалог «Добавить» в KiCad: проектная библиотека последней (небезопасно при совпадении имён)
        libs = std + [l for l in project_libs if l not in std]
    cfg['eeschema/libraries'] = OrderedDict(
        [('LibName%d' % (i + 1), n.replace('\\', '/')) for i, n in enumerate(libs)])
    cfg['general'] = OrderedDict([('version', '1')])
    return cfg


def format_project(cfg: 'OrderedDict[str, OrderedDict[str, str]]') -> str:
    """Сериализация в стиле wxFileConfig: [section] и key=value, без пробелов."""
    out: List[str] = []
    for section, items in cfg.items():
        if section:
            out.append('[%s]' % section)
        for k, v in items.items():
            out.append('%s=%s' % (k, v))
    return '\n'.join(out) + '\n'


def write_project(project_name: str, extra_libs: Sequence[str] = (), **kw) -> str:
    """Текст .pro для проекта ``project_name``: его библиотека <name>.lib
    подключается первой (после ``extra_libs``), затем стандартный список."""
    libs = list(extra_libs) + [project_name]
    return format_project(build_project(libs, **kw))


def save_project(path: str, project_name: Optional[str] = None, crlf: bool = True, **kw) -> str:
    import os
    if not path.lower().endswith('.pro'):
        path += '.pro'
    name = project_name or os.path.splitext(os.path.basename(path))[0]
    text = write_project(name, **kw)
    data = text.replace('\n', '\r\n') if crlf else text
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(data)
    return path
