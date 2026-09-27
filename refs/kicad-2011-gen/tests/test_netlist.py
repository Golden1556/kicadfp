"""Тесты kicadgen.netlist — реплики BuildNetListBase / WriteNetListPCBNEW.

Запуск:  python3 -m unittest tests.test_netlist -v
"""

from __future__ import annotations

import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kicadgen import model as M                     # noqa: E402
from kicadgen import sch as S                        # noqa: E402
from kicadgen import netlist as N                    # noqa: E402
from kicadgen.reader_lib import load_library         # noqa: E402

EXAMPLE_DIR = os.path.join(ROOT, 'examples', '346_8')


# --- Тестовая библиотека ----------------------------------------------------------

def _pin(name, number, x, y, orient, etype, unit=1, visible=True):
    return M.Pin(name=name, number=number, x=x, y=y, length=100,
                 orient=M.PinOrient(orient), etype=M.PinType(etype), unit=unit, visible=visible)


def _lib() -> M.Library:
    res = M.Component('RES', reference='R', items=[
        _pin('1', '1', -100, 0, 'R', 'P'),
        _pin('2', '2', 100, 0, 'L', 'P'),
    ])
    # двухсекционная микросхема с общими невидимыми выводами питания
    ic = M.Component('IC2', reference='DD', unit_count=2, items=[
        _pin('A', '1', -100, 100, 'R', 'I', unit=1),
        _pin('B', '2', 100, 100, 'L', 'O', unit=1),
        _pin('C', '3', -100, 100, 'R', 'I', unit=2),
        _pin('D', '4', 100, 100, 'L', 'O', unit=2),
        _pin('VCC', '14', 0, 200, 'D', 'W', unit=0, visible=False),
        _pin('GND', '7', 0, -200, 'U', 'W', unit=0, visible=False),
    ])
    # деталь с ВИДИМЫМ выводом «Вход питания» — глобальной цепи не создаёт
    vis = M.Component('PWRVIS', reference='U', items=[
        _pin('VCC', '1', 0, 0, 'U', 'W', visible=True),
    ])
    pwr = M.Component('VCC', reference='#PWR', power=True, items=[
        _pin('VCC', '1', 0, 0, 'U', 'W', visible=False),
    ])
    lib = M.Library([res, ic, vis, pwr])
    for c in lib.components:
        c.ensure_mandatory_fields()
    lib.validate()
    return lib


_TS = [0x4D000000]


def _comp(lib_name, ref, x, y, unit=1, orientation='0') -> S.SchComponent:
    _TS[0] += 1
    c = S.SchComponent(lib_name, ref, x, y, unit=unit, orientation=orientation, timestamp=_TS[0])
    c.ensure_fields()
    return c


def _nets_by_pins(nets):
    """{frozenset('R1.2', ...): Net}"""
    return {frozenset(n.pin_names()): n for n in nets if n.pins}


def _net_of(nets, pin):
    for n in nets:
        if pin in n.pin_names():
            return n
    raise AssertionError('pin %s in no net' % pin)


# --- Связность --------------------------------------------------------------------

class TestWireConnectivity(unittest.TestCase):
    def test_wires_connect_by_endpoints_only(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),      # pin2 -> (1100,1000)
            _comp('RES', 'R2', 2000, 1000),      # pin1 -> (1900,1000)
            _comp('RES', 'R3', 1600, 1000),      # pin1 -> (1500,1000): середина провода
            S.Wire(1100, 1000, 1900, 1000),
        ])
        nets = N.build_nets(sch, lib)
        self.assertIs(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))
        self.assertIsNot(_net_of(nets, 'R3.1'), _net_of(nets, 'R1.2'))
        # два КОЛЛИНЕАРНЫХ провода со стыком на выводе SchematicCleanUp склеивает
        # в один (sch_line.cpp:260-321) -> вывод снова в середине, не подключён
        sch.items[-1:] = [S.Wire(1100, 1000, 1500, 1000), S.Wire(1500, 1000, 1900, 1000)]
        nets = N.build_nets(sch, lib)
        self.assertIsNot(_net_of(nets, 'R3.1'), _net_of(nets, 'R1.2'))
        # с Connection на стыке — подключён
        nets = N.build_nets(S.Schematic(items=sch.items + [S.Junction(1500, 1000)]), lib)
        self.assertIs(_net_of(nets, 'R3.1'), _net_of(nets, 'R1.2'))
        self.assertIs(_net_of(nets, 'R3.1'), _net_of(nets, 'R2.1'))
        # угол (не коллинеарные провода) на выводе: три конца в точке, без junction
        sch.items[-2:] = [S.Wire(1100, 1000, 1500, 1000), S.Wire(1500, 1000, 1500, 1200)]
        nets = N.build_nets(sch, lib)
        self.assertIs(_net_of(nets, 'R3.1'), _net_of(nets, 'R1.2'))

    def test_one_mil_off_is_a_break(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),
            _comp('RES', 'R2', 2000, 1000),
            S.Wire(1100, 1000, 1901, 1000),
        ])
        nets = N.build_nets(sch, lib)
        self.assertIsNot(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))

    def test_t_connection_needs_junction(self):
        lib = _lib()
        base = [
            _comp('RES', 'R1', 900, 2000),       # pin2 -> (1000,2000)
            _comp('RES', 'R2', 1700, 2600),      # pin1 -> (1600,2600)
            S.Wire(1000, 2000, 2000, 2000),      # горизонталь
            S.Wire(1500, 2000, 1500, 2600),      # конец в середине горизонтали
            S.Wire(1500, 2600, 1600, 2600),
        ]
        nets = N.build_nets(S.Schematic(items=list(base)), lib)
        self.assertIsNot(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))
        nets = N.build_nets(S.Schematic(items=base + [S.Junction(1500, 2000)]), lib)
        self.assertIs(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))

    def test_junction_on_wire_middle_connects_crossing_wires(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 900, 2000),       # pin2 (1000,2000)
            _comp('RES', 'R2', 1500, 2700),      # pin1 (1400,2700)
            S.Wire(1000, 2000, 2000, 2000),
            S.Wire(1500, 1500, 1500, 2700),      # пересекает первый провод в (1500,2000)
            S.Wire(1500, 2700, 1400, 2700),
            S.Junction(1500, 2000),
        ])
        nets = N.build_nets(sch, lib)
        self.assertIs(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))


class TestLabels(unittest.TestCase):
    def test_same_label_merges_case_insensitive_and_names_net(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),      # pin2 (1100,1000)
            _comp('RES', 'R2', 3000, 1000),      # pin1 (2900,1000)
            S.Wire(1100, 1000, 1500, 1000),
            S.Wire(2500, 1000, 2900, 1000),
            S.Label(1300, 1000, 'net_a'),        # якорь внутри провода
            S.Label(2700, 1000, 'NET_A'),
        ])
        nets = N.build_nets(sch, lib)
        net = _net_of(nets, 'R1.2')
        self.assertIs(net, _net_of(nets, 'R2.1'))
        # FindBestNetName: одинаковый приоритет -> wxString::Cmp -> 'NET_A' < 'net_a'
        self.assertEqual(net.label, 'NET_A')
        self.assertEqual(net.name, '/NET_A')     # локальная метка с префиксом пути листа

    def test_label_off_wire_does_not_connect(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),
            _comp('RES', 'R2', 3000, 1000),
            S.Wire(1100, 1000, 1500, 1000),
            S.Wire(2500, 1000, 2900, 1000),
            S.Label(1300, 1050, 'X'),            # рядом, но не на проводе
            S.Label(2700, 1000, 'X'),
        ])
        nets = N.build_nets(sch, lib)
        self.assertIsNot(_net_of(nets, 'R1.2'), _net_of(nets, 'R2.1'))

    def test_global_label_beats_local_in_name(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),
            _comp('RES', 'R2', 1400, 1000),      # pin1 (1300,1000)
            S.Wire(1100, 1000, 1300, 1000),
            S.Label(1200, 1000, 'AAA'),
            S.GlobalLabel(1250, 1000, 'ZZZ'),
        ])
        net = _net_of(N.build_nets(sch, lib), 'R1.2')
        self.assertEqual(net.name, 'ZZZ')        # глобальная — без префикса

    def test_single_pin_net_is_unconnected_even_with_label(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),
            S.Wire(1100, 1000, 1500, 1000),
            S.Label(1300, 1000, 'ALONE'),
        ])
        net = _net_of(N.build_nets(sch, lib), 'R1.2')
        self.assertFalse(net.connected)
        self.assertEqual(net.name, '')           # в файле -> '?'


class TestPowerPins(unittest.TestCase):
    def test_invisible_power_in_pin_is_global_label(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('IC2', 'DD1', 5000, 5000, unit=1),
            _comp('RES', 'R1', 1000, 1000),      # pin1 (900,1000)
            _comp('VCC', '#PWR01', 700, 1000),   # вывод в (700,1000)
            S.Wire(900, 1000, 700, 1000),
            _comp('PWRVIS', 'U1', 3000, 3000),   # видимый W-вывод VCC, отдельно
        ])
        nets = N.build_nets(sch, lib)
        net = _net_of(nets, 'R1.1')
        self.assertIs(net, _net_of(nets, 'DD1.14'))
        self.assertEqual(net.name, 'VCC')
        self.assertTrue(net.connected)
        self.assertIsNot(_net_of(nets, 'U1.1'), net)
        # невидимый GND без символа питания — одиночная цепь, «не подключена»
        gnd = _net_of(nets, 'DD1.7')
        self.assertFalse(gnd.connected)
        self.assertEqual(gnd.label, 'GND')

    def test_power_symbol_excluded_from_component_list(self):
        lib = _lib()
        sch = S.Schematic(items=[
            _comp('RES', 'R1', 1000, 1000),
            _comp('VCC', '#PWR01', 700, 1000),
            S.Wire(900, 1000, 700, 1000),
        ])
        text = N.write_netlist_pcbnew(sch, lib, date='D')
        self.assertNotIn('#PWR01', text)
        self.assertIn(' ( /4D', text)
        self.assertIn('  R1 RES {Lib=RES}', text)


class TestMultiUnit(unittest.TestCase):
    def _sch(self):
        return S.Schematic(items=[
            _comp('IC2', 'DD1', 2000, 2000, unit=1),   # A1 (1900,1900) B2 (2100,1900)
            _comp('IC2', 'DD1', 2000, 4000, unit=2),   # C3 (1900,3900) D4 (2100,3900)
            S.Wire(2100, 1900, 2500, 1900),
            S.Wire(2500, 1900, 2500, 3900),
            S.Wire(2500, 3900, 2100, 3900),            # B2 -> D4
            _comp('VCC', '#PWR01', 1000, 1000),
            _comp('RES', 'R1', 1200, 1000),            # pin1 (1100,1000)
            S.Wire(1100, 1000, 1000, 1000),
        ])

    def test_pins_of_both_units_looked_up_and_deduplicated(self):
        lib = _lib()
        text = N.write_netlist_pcbnew(self._sch(), lib, date='D')
        self.assertEqual(text.count(' DD1 IC2 {Lib=IC2}'), 1)
        block = text.split('  DD1 IC2 {Lib=IC2}\n', 1)[1].split('\n )\n', 1)[0]
        nums = [ln.split()[1] for ln in block.splitlines()]
        self.assertEqual(nums, ['1', '2', '3', '4', '7', '14'])
        self.assertIn('  (   14 VCC )', block)
        # два экземпляра -> два скрытых GND-вывода в одной цепи (PINLABEL) -> PAD_CONNECT
        self.assertIn('  (    7 GND )', block)
        # выход B (2) и выход D (4) соединены: имя цепи из счётчика
        b = [ln for ln in block.splitlines() if ln.split()[1] == '2'][0].split()[2]
        d = [ln for ln in block.splitlines() if ln.split()[1] == '4'][0].split()[2]
        self.assertEqual(b, d)
        self.assertRegex(b, r'^N-\d{6}$')

    def test_pin_list_by_nets_lists_hidden_pin_once(self):
        lib = _lib()
        text = N.write_netlist_pcbnew(self._sch(), lib, date='D')
        tail = text.split('{ Pin List by Nets\n', 1)[1]
        self.assertIn('Net ', tail)
        self.assertEqual(tail.count(' DD1 14\n'), 1)
        self.assertEqual(tail.count(' DD1 7\n'), 0)     # одиночная цепь не печатается


class TestHelpers(unittest.TestCase):
    def test_refdes_compare_order(self):
        import functools
        pins = ['A10', '2', 'a2', '10', '1', 'A1', 'B1']
        pins.sort(key=functools.cmp_to_key(N.refdes_compare))
        self.assertEqual(pins, ['1', '2', '10', 'A1', 'a2', 'A10', 'B1'])

    def test_bus_label(self):
        self.assertEqual(N.is_bus_label('DATA[0..3]'), (4, 0, 3, 4))
        self.assertEqual(N.is_bus_label('D[7..5]'), (3, 5, 7, 1))
        self.assertEqual(N.is_bus_label('PLAIN'), (0, 0, 0, 0))

    def test_bus_members_created(self):
        lib = _lib()
        sch = S.Schematic(items=[S.Bus(100, 100, 100, 900), S.Label(100, 500, 'D[0..2]')])
        objs, _, _ = N.build_net_objects(sch, lib)
        members = [o for o in objs if o.type == N.NetType.BUSLABELMEMBER]
        self.assertEqual(sorted(o.label for o in members), ['D0', 'D1', 'D2'])
        self.assertEqual(sorted(o.member for o in members), [0, 1, 2])
        # все члены сидят на одной шине (общий BusNetCode), но в разных цепях
        self.assertEqual(len({o.bus_net for o in members}), 1)
        self.assertEqual(len({o.net for o in members}), 3)

    def test_segment_intersect(self):
        self.assertTrue(N._segment_intersect((0, 0), (100, 0), (50, 0)))
        self.assertTrue(N._segment_intersect((0, 0), (100, 0), (0, 0)))
        self.assertTrue(N._segment_intersect((0, 0), (100, 0), (100, 0)))
        self.assertFalse(N._segment_intersect((0, 0), (100, 0), (101, 0)))
        self.assertFalse(N._segment_intersect((0, 0), (100, 0), (-1, 0)))
        self.assertFalse(N._segment_intersect((0, 0), (100, 0), (50, 1)))

    def test_schematic_cleanup_merges_collinear(self):
        items = [S.Wire(0, 0, 100, 0), S.Wire(0, 0, 100, 0), S.Wire(100, 0, 200, 0),
                 S.Wire(200, 0, 200, 100), S.Junction(5, 5)]
        out = N.schematic_cleanup(items)
        wires = [(w.x1, w.y1, w.x2, w.y2) for w in out if isinstance(w, S.Wire)]
        self.assertEqual(wires, [(0, 0, 200, 0), (200, 0, 200, 100)])
        self.assertEqual(len(out), 3)
        # исходный список не тронут
        self.assertEqual((items[0].x2, items[0].y2), (100, 0))
        self.assertEqual(len(items), 5)

    def test_schematic_cleanup_partial_overlap_quirk(self):
        # MergeOverlap с частично перекрывающим дубликатом УКОРАЧИВАЕТ провод
        # (общее начало -> EXCHG концов -> m_End = aLine->m_End); повторяем как есть
        out = N.schematic_cleanup([S.Wire(0, 0, 200, 0), S.Wire(0, 0, 100, 0)])
        self.assertEqual([(w.x1, w.y1, w.x2, w.y2) for w in out], [(200, 0, 100, 0)])

    def test_unannotated_is_error(self):
        lib = _lib()
        sch = S.Schematic(items=[_comp('RES', 'R?', 1000, 1000)])
        with self.assertRaises(N.NetlistError):
            N.write_netlist_pcbnew(sch, lib, date='D')
        self.assertTrue(N.write_netlist_pcbnew(sch, lib, date='D', check=False).startswith('# '))

    def test_sheet_path_formats(self):
        root = N.SheetPath()
        self.assertEqual(root.path(), '/')
        self.assertEqual(root.human(), '/')
        sub = root.push(S.Sheet(0, 0, 100, 100, 'sub', 'sub.sch', timestamp=0x4DBA0001), S.Schematic())
        self.assertEqual(sub.path(), '/4DBA0001/')
        self.assertEqual(sub.human(), '/sub/')
        self.assertEqual(root.cmp(sub), -1)


# --- Пример 346_8 -------------------------------------------------------------------

EXPECTED_346_8 = {
    'GND': {'X1.1', 'DD1.7', 'R1.1'},
    'Vcc': {'X1.8', 'DD1.14'},
    '/1': {'X1.2', 'DD1.1'},
    '/2': {'X1.4', 'DD1.8'},
    '/3': {'X1.5', 'DD1.4'},
    'N-000001': {'X1.3', 'DD1.13'},
    'N-000002': {'X1.6', 'DD1.12', 'DD1.9'},
    'N-000006': {'DD1.3', 'DD1.11'},
    'N-000007': {'X1.7', 'DD1.5'},
    'N-000009': {'DD1.10', 'R1.2'},
}

EXPECTED_346_8_NET = """# EESchema Netlist Version 1.1 created  Ср 02.09.26 19:52:23
(
 ( /6A9862BD snp8  X1 CONNECT {Lib=CONNECT}
  (    1 GND )
  (    2 /1 )
  (    3 N-000001 )
  (    4 /2 )
  (    5 /3 )
  (    6 N-000002 )
  (    7 N-000007 )
  (    8 Vcc )
 )
 ( /6A9862BE dip14  DD1 K555TB6 {Lib=K555TB6}
  (    1 /1 )
  (    2 ? )
  (    3 N-000006 )
  (    4 /3 )
  (    5 N-000007 )
  (    6 ? )
  (    7 GND )
  (    8 /2 )
  (    9 N-000002 )
  (   10 N-000009 )
  (   11 N-000006 )
  (   12 N-000002 )
  (   13 N-000001 )
  (   14 Vcc )
 )
 ( /6A9862C0 mlt  R1 REZ {Lib=REZ}
  (    1 GND )
  (    2 N-000009 )
 )
)
*
{ Pin List by Nets
Net 1 "" ""
 X1 3
 DD1 13
Net 2 "" ""
 X1 6
 DD1 12
 DD1 9
Net 3 "GND" "GND"
 X1 1
 DD1 7
 R1 1
Net 4 "Vcc" "Vcc"
 X1 8
 DD1 14
Net 6 "" ""
 DD1 3
 DD1 11
Net 7 "" ""
 X1 7
 DD1 5
Net 9 "" ""
 DD1 10
 R1 2
Net 10 "/1" "1"
 X1 2
 DD1 1
Net 11 "/2" "2"
 X1 4
 DD1 8
Net 12 "/3" "3"
 X1 5
 DD1 4
}
#End
"""


@unittest.skipUnless(os.path.exists(os.path.join(EXAMPLE_DIR, '346_8.sch')), 'example not generated')
class TestExample346_8(unittest.TestCase):
    def setUp(self):
        self.sch, _ = S.load_schematic(os.path.join(EXAMPLE_DIR, '346_8.sch'))
        self.lib, _ = load_library(os.path.join(EXAMPLE_DIR, 'My_lib.lib'))

    def test_nets_match_tz_3_3(self):
        nets = N.build_nets(self.sch, self.lib)
        named = {n.name: set(n.pin_names()) for n in nets if n.connected}
        self.assertEqual(named, EXPECTED_346_8)
        loose = [n for n in nets if not n.connected and n.pins]
        self.assertEqual(sorted(n.pin_names()[0] for n in loose), ['DD1.2', 'DD1.6'])
        for n in loose:                       # NoConn присутствует
            self.assertTrue(any(o.type == N.NetType.NOCONNECT for o in n.objects))

    @staticmethod
    def _norm(text):
        import re
        return re.sub(r'/[0-9A-F]{8}', '/TIMESTAMP', text)

    def test_file_text(self):
        text = N.write_netlist_pcbnew(self.sch, self.lib, date='Ср 02.09.26 19:52:23')
        self.assertEqual(self._norm(text), self._norm(EXPECTED_346_8_NET))

    def test_generated_file_is_crlf_and_current(self):
        path = os.path.join(EXAMPLE_DIR, '346_8.net')
        if not os.path.exists(path):
            self.skipTest('346_8.net not generated')
        with io.open(path, 'rb') as fh:
            data = fh.read()
        self.assertIn(b'\r\n', data)
        self.assertNotIn(b'\n\n', data.replace(b'\r\n', b'\n').replace(b'\n\n', b'\n\n'))
        text = data.decode('utf-8').replace('\r\n', '\n')
        head, body = text.split('\n', 1)
        self.assertTrue(head.startswith('# EESchema Netlist Version 1.1 created  '))
        self.assertEqual(self._norm(body), self._norm(EXPECTED_346_8_NET.split('\n', 1)[1]))

    def test_orcad_variant(self):
        text = N.write_netlist_pcbnew(self.sch, self.lib, date='D', with_pcbnew=False)
        self.assertTrue(text.startswith('( { EESchema Netlist Version 1.1 created  D }\n'))
        self.assertNotIn('{Lib=', text)
        self.assertNotIn('Pin List', text)
        self.assertTrue(text.endswith(')\n*\n'))


if __name__ == '__main__':
    unittest.main()
