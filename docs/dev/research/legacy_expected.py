#!/usr/bin/env python3
"""Эталонный расчёт результата конвертации My_lib.mod (PCBNEW-LibModule-V1)
в модель KiCad 9 — воспроизводит логику
pcbnew/pcb_io/kicad_legacy/pcb_io_kicad_legacy.cpp (ветка 9.0) для библиотек.

Выводит Markdown-таблицы (pads/texts/shapes) в мм в форматировании KiCad
({:.10g} от нм/1e6) и проверяет подсказки из ТЗ.
"""
from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field

FIXTURE = "/Users/juli/Desktop/Claude/kicadfp/tests/fixtures/legacy_mod/My_lib.mod"

IU_PER_MM = 1_000_000.0
IU_PER_MILS = IU_PER_MM * 0.0254          # base_units.h:83 -> 25400
DECIMIL_TO_IU = IU_PER_MILS / 10          # init(): 2540 nm per 1/10000"


def kiround(v: float) -> int:             # math/util.h:100-103
    return int(v - 0.5) if v < 0 else int(v + 0.5)


def fmt_mm(iu: int) -> str:               # eda_units.cpp:170-200
    eng = iu / IU_PER_MM
    if eng != 0.0 and abs(eng) <= 0.0001:
        s = f"{eng:.10f}".rstrip("0").rstrip(".")
        return s
    return f"{eng:.10g}"


def fmt_angle(deg: float) -> str:         # eda_units.cpp:162-167
    return f"{deg:.10g}"


# ---------------------------------------------------------------- layers ---
# legacy numbers (pcb_io_kicad_legacy.cpp:102-136) -> 9.0 canonical names
LEG_TECH = {16: "B.Adhes", 17: "F.Adhes", 18: "B.Paste", 19: "F.Paste",
            20: "B.SilkS", 21: "F.SilkS", 22: "B.Mask", 23: "F.Mask",
            24: "Dwgs.User", 25: "Cmts.User", 26: "Eco1.User", 27: "Eco2.User",
            28: "Edge.Cuts"}

# PCB_LAYER_ID numeric values in 9.0 (include/layer_ids.h:64-124) — writer
# enumerates individual layers in this numeric order (pcb_io_kicad_sexpr.cpp:1422)
ORDER9 = {"F.Cu": 0, "F.Mask": 1, "B.Cu": 2, "B.Mask": 3, "F.SilkS": 5, "B.SilkS": 7,
          "F.Adhes": 9, "B.Adhes": 11, "F.Paste": 13, "B.Paste": 15, "Dwgs.User": 17,
          "Cmts.User": 19, "Eco1.User": 21, "Eco2.User": 23, "Edge.Cuts": 25,
          "B.CrtYd": 29, "F.CrtYd": 31, "B.Fab": 33, "F.Fab": 35}
for _i in range(1, 31):
    ORDER9[f"In{_i}.Cu"] = 4 + (_i - 1) * 2
ALL_CU = ["F.Cu", "B.Cu"] + [f"In{i}.Cu" for i in range(1, 31)]   # MAX_CU_LAYERS 32


def leg_layer2new(old: int, cu_count: int = 16) -> str:   # :311-364
    if 0 <= old <= 15:
        if old == 15:
            return "F.Cu"
        if old == 0:
            return "B.Cu"
        legacy_id = cu_count - 1 - old                   # BoardLayerFromLegacyId
        return f"In{legacy_id}.Cu"                       # layer_id.cpp:226-227
    return LEG_TECH.get(old, "Cmts.User")                # default -> Cmts_User


def leg_mask2new(mask: int, cu_count: int = 16) -> set[str]:   # :367-385
    ret: set[str] = set()
    if (mask & 0xFFFF) == 0xFFFF:
        ret |= set(ALL_CU)
        mask &= ~0xFFFF
    i = 0
    while mask:
        if mask & 1:
            ret.add(leg_layer2new(i, cu_count))
        mask >>= 1
        i += 1
    return ret


def format_layers(lset: set[str]) -> str:   # pcb_io_kicad_sexpr.cpp:1345-1429, board == nullptr
    out: list[str] = []
    rest = set(lset)
    if set(ALL_CU) <= rest:
        out.append("*.Cu"); rest -= set(ALL_CU)
    elif rest & set(ALL_CU) == {"F.Cu", "B.Cu"}:
        out.append("*.Cu"); rest -= {"F.Cu", "B.Cu"}
    for wild, pair in (("*.Adhes", {"B.Adhes", "F.Adhes"}), ("*.Paste", {"B.Paste", "F.Paste"}),
                       ("*.SilkS", {"B.SilkS", "F.SilkS"}), ("*.Mask", {"B.Mask", "F.Mask"}),
                       ("*.CrtYd", {"B.CrtYd", "F.CrtYd"}), ("*.Fab", {"B.Fab", "F.Fab"})):
        if pair <= rest:
            out.append(wild); rest -= pair
    out += sorted(rest, key=lambda n: ORDER9[n])
    return "(layers " + " ".join(f'"{n}"' for n in out) + ")"


# -------------------------------------------------------------- geometry ---
def rotate_point(x: int, y: int, deg: float) -> tuple[int, int]:   # trigo.cpp:229-264
    a = deg % 360.0
    if a == 0:
        return x, y
    if a == 90:
        return y, -x
    if a == 180:
        return -x, -y
    if a == 270:
        return -y, x
    s, c = math.sin(math.radians(a)), math.cos(math.radians(a))
    return kiround(y * s + x * c), kiround(y * c - x * s)


def rotate_about(p, c, deg):
    rx, ry = rotate_point(p[0] - c[0], p[1] - c[1], deg)
    return rx + c[0], ry + c[1]


def vec_angle(v) -> float:            # eda_angle.h:72-110 (degrees)
    x, y = v
    if x == 0 and y == 0:
        return 0.0
    if y == 0:
        return 0.0 if x >= 0 else -180.0
    if x == 0:
        return 90.0 if y >= 0 else -90.0
    if x == y:
        return 45.0 if x >= 0 else -135.0
    if x == -y:
        return -45.0 if x >= 0 else 135.0
    return math.degrees(math.atan2(y, x))


def normalize720(a: float) -> float:  # eda_angle.h:279-288
    while a < -360.0:
        a += 360.0
    while a >= 360.0:
        a -= 360.0
    return a


def arc_from_legacy(center, start, angle_deg):
    """SetCenter/SetStart/SetArcAngleAndEnd(angle, true) (eda_shape.cpp:953-965)"""
    end = rotate_about(start, center, -normalize720(angle_deg))
    swapped = False
    if angle_deg < 0:
        start, end = end, start
        swapped = True
    # GetArcMid (eda_shape.cpp:811-822) / CalcArcAngles (:825-838)
    sa = vec_angle((start[0] - center[0], start[1] - center[1]))
    ea = vec_angle((end[0] - center[0], end[1] - center[1]))
    if ea == sa:
        ea = sa + 360.0
    while ea < sa:
        ea += 360.0
    arc_angle = ea - sa
    mid = rotate_about(start, center, -arc_angle / 2.0)
    return start, mid, end, arc_angle, swapped


# ----------------------------------------------------------------- model ---
@dataclass
class Pad:
    number: str = ""
    shape: str = "circle"
    size: tuple = (0, 0)
    delta: tuple = (0, 0)
    orient: float = 0.0
    drill: tuple = (0, 0)
    drill_oval: bool = False
    offset: tuple = (0, 0)
    attr: str = "thru_hole"
    layers: set = field(default_factory=set)
    mask_hex: str = ""
    pos: tuple = (0, 0)
    net: tuple = (0, "")


@dataclass
class Text:
    kind: int = 2
    text: str = ""
    pos: tuple = (0, 0)
    size: tuple = (0, 0)       # (x=width, y=height)
    angle: float = 0.0
    thickness: int = 0
    mirror: bool = False
    visible: bool = True
    italic: bool = False
    layer: str = "F.SilkS"


@dataclass
class Shape:
    kind: str = ""
    start: tuple = (0, 0)
    end: tuple = (0, 0)
    mid: tuple = (0, 0)
    center: tuple = (0, 0)
    angle: float = 0.0
    swapped: bool = False
    pts: list = field(default_factory=list)
    width: int = 0
    layer: str = "F.SilkS"
    raw_layer: int = 21


@dataclass
class Module:
    name: str = ""
    pos: tuple = (0, 0)
    orient: float = 0.0
    layer: str = "F.Cu"
    descr: str = ""
    tags: str = ""
    attrs: list = field(default_factory=list)
    pads: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    shapes: list = field(default_factory=list)
    models: list = field(default_factory=list)
    lines: int = 0


class Reader:
    def __init__(self, text: str):
        self.lines = text.split("\n")
        self.i = 0
        self.scale = DECIMIL_TO_IU
        self.stats = {"crlf": sum(1 for l in self.lines if l.endswith("\r")),
                      "comments": sum(1 for l in self.lines if l.startswith("#")),
                      "lines": len(self.lines)}

    def readline(self):
        if self.i >= len(self.lines):
            return None
        l = self.lines[self.i]
        self.i += 1
        return l + "\n"

    def biu(self, tok: str) -> int:        # biuParse: strtod * diskToBiu, KiROUND
        return kiround(float(tok) * self.scale)

    @staticmethod
    def deg(tok: str) -> float:            # degParse: tenths of degree
        return float(tok) / 10.0


def testline(line: str, key: str) -> bool:   # TESTLINE macro
    return line[:len(key)].lower() == key.lower() and len(line) > len(key) and line[len(key)] in " \t\r\n"


def read_delimited(s: str) -> tuple[str, int]:   # ReadDelimitedText (string_utils.cpp:410-452)
    out = []
    inside = False
    i = 0
    while i < len(s):
        c = s[i]; i += 1
        if c == '"':
            if inside:
                break
            inside = True
        elif inside:
            if c == "\\":
                if i >= len(s):
                    break
                c = s[i]; i += 1
                if c not in '"\\':
                    out.append("\\")
                out.append(c)
            else:
                out.append(c)
    return "".join(out), i


def load(text: str):
    r = Reader(text)
    line = r.readline()
    assert line is not None and testline(line, "PCBNEW-LibModule-V1"), "not a legacy library"
    # ReadAndVerifyHeader: Units / $INDEX
    found_index = False
    while (line := r.readline()) is not None:
        if testline(line, "Units"):
            if line.split()[1] == "mm":
                r.scale = IU_PER_MM
        elif testline(line, "$INDEX"):
            found_index = True
            break
    # SkipIndex
    while line is not None and not testline(line, "$EndINDEX"):
        line = r.readline()
    # LoadModules
    mods = []
    while (line := r.readline()) is not None:
        if testline(line, "$MODULE"):
            m = Module(name=line[len("$MODULE"):].strip())
            mods.append(m)
            load_module(r, m)
    return mods, r.stats, found_index


def load_module(r: Reader, m: Module):
    start = r.i
    while (line := r.readline()) is not None:
        if line[0] == "D" and line[1] in "SCAP":
            load_shape(r, m, line)
        elif testline(line, "$PAD"):
            load_pad(r, m)
        elif line[0] == "T":
            load_text(r, m, line)
        elif testline(line, "Po"):
            t = line.split()
            m.pos = (r.biu(t[1]), r.biu(t[2]))
            m.orient = int(t[3]) / 10.0
            m.layer = leg_layer2new(int(t[4]))
        elif testline(line, "At"):
            if "SMD" in line:
                m.attrs = ["smd"]
            elif "VIRTUAL" in line:
                m.attrs = ["exclude_from_pos_files", "exclude_from_bom"]
            else:
                m.attrs = ["through_hole", "exclude_from_pos_files"]
        elif testline(line, "Cd"):
            m.descr = line[2:].strip()
        elif testline(line, "Kw"):
            m.tags = line[2:].strip()
        elif testline(line, "$SHAPE3D"):
            mdl = {}
            while (line := r.readline()) is not None and not testline(line, "$EndSHAPE3D"):
                k = line[:2]
                if k == "Na":
                    mdl["name"] = read_delimited(line[2:])[0]
                elif k in ("Sc", "Of", "Ro"):
                    mdl[k] = tuple(float(v) for v in line[2:].split()[:3])
            m.models.append(mdl)
        elif testline(line, "$EndMODULE"):
            m.lines = r.i - start + 1
            return
    raise ValueError("Missing $EndMODULE")


def load_pad(r: Reader, m: Module):
    p = Pad()
    while (line := r.readline()) is not None:
        if testline(line, "Sh"):
            name, n = read_delimited(line[3:])
            rest = line[3 + n:].split()
            p.number = name
            p.shape = {"C": "circle", "R": "rect", "O": "oval", "T": "trapezoid"}[rest[0]]
            p.size = (r.biu(rest[1]), r.biu(rest[2]))
            p.delta = (r.biu(rest[3]), r.biu(rest[4]))
            p.orient = r.deg(rest[5])
        elif testline(line, "Dr"):
            t = line.split()
            dx = r.biu(t[1]); dy = dx
            p.offset = (r.biu(t[2]), r.biu(t[3]))
            if len(t) > 4 and t[4][0] == "O":
                p.drill_oval = True
                dx, dy = r.biu(t[5]), r.biu(t[6])
            p.drill = (dx, dy)
        elif testline(line, "At"):
            t = line.split()
            p.attr = {"SMD": "smd", "CONN": "connect", "HOLE": "np_thru_hole"}.get(t[1], "thru_hole")
            p.mask_hex = t[3]
            p.layers = leg_mask2new(int(t[3], 16))
        elif testline(line, "Ne"):
            t = line.split(None, 2)
            p.net = (int(t[1]), read_delimited(t[2])[0] if len(t) > 2 else "")
        elif testline(line, "Po"):
            t = line.split()
            p.pos = (r.biu(t[1]), r.biu(t[2]))
        elif testline(line, "$EndPAD"):
            # PAD::SetAttribute side effects (pad.cpp:923-964)
            if p.attr in ("smd", "connect"):
                p.drill = (0, 0)
            if p.attr == "np_thru_hole":
                p.number = ""
            if p.size[0] > 0 and p.size[1] > 0:
                m.pads.append(p)
            return
    raise ValueError("Missing $EndPAD")


def load_text(r: Reader, m: Module, line: str):
    t = Text()
    body = line[1:]
    toks = body.split()
    t.kind = int(toks[0])
    t.pos = (r.biu(toks[1]), r.biu(toks[2]))
    size_y, size_x = r.biu(toks[3]), r.biu(toks[4])
    t.size = (size_x, size_y)
    t.angle = r.deg(toks[5])
    th = r.biu(toks[6])
    t.thickness = 0 if th < 1 else th
    txt, _ = read_delimited(body)
    txt = txt.replace("%V", "${VALUE}").replace("%R", "${REFERENCE}")
    t.text = txt
    t.mirror = toks[7][0] == "M"
    t.visible = not (toks[8][0] == "I")
    layer_num = int(toks[9]) if len(toks) > 9 and toks[9][0] not in '"' else 21
    t.italic = len(toks) > 10 and not toks[10].startswith('"') and toks[10][0] == "I"
    if layer_num < 0:
        layer_num = 0
    elif layer_num > 28:
        layer_num = 28
    elif layer_num == 0:
        layer_num = 20
    elif layer_num == 15:
        layer_num = 21
    elif layer_num < 15:
        layer_num = 21
    t.layer = leg_layer2new(layer_num)
    m.texts.append(t)


def load_shape(r: Reader, m: Module, line: str):
    s = Shape()
    kind = line[1]
    toks = line[2:].split()
    if kind == "A":
        s.kind = "fp_arc"
        center = (r.biu(toks[0]), r.biu(toks[1]))
        start = (r.biu(toks[2]), r.biu(toks[3]))
        s.angle = r.deg(toks[4])
        s.width = r.biu(toks[5]); s.raw_layer = int(toks[6])
        s.center = center
        s.start, s.mid, s.end, _, s.swapped = arc_from_legacy(center, start, s.angle)
    elif kind in "SC":
        s.kind = "fp_line" if kind == "S" else "fp_circle"
        s.start = (r.biu(toks[0]), r.biu(toks[1]))
        s.end = (r.biu(toks[2]), r.biu(toks[3]))
        s.width = r.biu(toks[4]); s.raw_layer = int(toks[5])
    elif kind == "P":
        s.kind = "fp_poly"
        n = int(toks[4]); s.width = r.biu(toks[5]); s.raw_layer = int(toks[6])
        for _ in range(n):
            l = r.readline()
            assert l and testline(l, "Dl")
            a, b = l.split()[1:3]
            s.pts.append((r.biu(a), r.biu(b)))
    layer = s.raw_layer
    if layer < 0 or layer > 28:
        layer = 21
    s.layer = leg_layer2new(layer)
    m.shapes.append(s)


# ---------------------------------------------------------------- report ---
def xy(p):
    return f"{fmt_mm(p[0])} {fmt_mm(p[1])}"


def report(mods, stats, found_index):
    print(f"file lines={stats['lines']} crlf_lines={stats['crlf']} comment_lines={stats['comments']} index={found_index}")
    for m in mods:
        print(f"\n### {m.name}  (block lines={m.lines}, descr={m.descr!r}, tags={m.tags!r}, attr={m.attrs or '—'})")
        print(f"pads={len(m.pads)} texts={len(m.texts)} shapes={len(m.shapes)} models={len(m.models)}")
        print("\n| # | type | shape | at (mm) | size (mm) | drill | layers |")
        print("|---|---|---|---|---|---|---|")
        for p in m.pads:
            drill = ""
            if p.drill[0] > 0 or p.drill[1] > 0:
                drill = ("oval " if p.drill_oval else "") + fmt_mm(p.drill[0])
                if p.drill[1] > 0 and p.drill[1] != p.drill[0]:
                    drill += " " + fmt_mm(p.drill[1])
            print(f'| "{p.number}" | {p.attr} | {p.shape} | {xy(p.pos)} | {xy(p.size)} | {drill or "—"} | {format_layers(p.layers)} |')
        print("\n| T | text | at (mm) | angle | size h w (mm) | thickness | layer | flags |")
        print("|---|---|---|---|---|---|---|---|")
        for t in m.texts:
            flags = ",".join(f for f, v in (("mirror", t.mirror), ("hide", not t.visible), ("italic", t.italic)) if v) or "—"
            name = {0: "Reference", 1: "Value"}.get(t.kind, "user")
            print(f'| {name} | "{t.text}" | {xy(t.pos)} | {fmt_angle(t.angle)} | {fmt_mm(t.size[1])} {fmt_mm(t.size[0])} | {fmt_mm(t.thickness)} | {t.layer} | {flags} |')
        print("\n| shape | start | mid/end | end | width | layer |")
        print("|---|---|---|---|---|---|")
        for s in m.shapes:
            if s.kind == "fp_arc":
                print(f"| fp_arc (DA angle {fmt_angle(s.angle)}, swapped={s.swapped}, center {xy(s.center)}) | {xy(s.start)} | mid {xy(s.mid)} | {xy(s.end)} | {fmt_mm(s.width)} | {s.layer} |")
            elif s.kind == "fp_poly":
                print(f"| fp_poly | pts {' / '.join(xy(p) for p in s.pts)} | | | {fmt_mm(s.width)} | {s.layer} |")
            else:
                print(f"| {s.kind} | {xy(s.start)} | | {xy(s.end)} | {fmt_mm(s.width)} | {s.layer} |")


def main():
    text = open(FIXTURE, "rb").read().decode("utf-8")
    mods, stats, found_index = load(text)
    report(mods, stats, found_index)

    print("\n### checks")
    for raw, exp in ((512, "1.30048"), (315, "0.8001"), (984, "2.49936"), (1476, "3.74904"),
                     (3937, "9.99998"), (394, "1.00076"), (59, "0.14986"), (3445, "8.7503"),
                     (295, "0.7493"), (1181, "2.99974"), (1969, "5.00126"), (2953, "7.50062"),
                     (5906, "15.00124"), (492, "1.24968"), (5413, "13.74902"), (4921, "12.49934")):
        got = fmt_mm(kiround(raw * DECIMIL_TO_IU))
        print(f"{raw} deci-mil -> {raw * 2540} nm -> {got} mm  {'OK' if got == exp else 'MISMATCH exp ' + exp}")
    print("\n### masks")
    for hx in ("00E0FFFF", "00808000", "00888000", "00E00001", "0000FFFF", "00008001", "00C08000"):
        ls = leg_mask2new(int(hx, 16))
        print(f"{hx}: {len(ls)} layers -> {format_layers(ls)}")
    print("\n### arc examples")
    for c, s, a in (((0, -3445), (295, -3445), -180.0), ((0, -3445), (295, -3445), 180.0),
                    ((0, 0), (1000, 0), 90.0), ((0, 0), (1000, 0), -90.0), ((0, 0), (1000, 0), 45.0),
                    ((0, 0), (1000, 0), 360.0)):
        st, mid, en, ang, sw = arc_from_legacy(c, s, a)
        print(f"center={c} start={s} angle={a}: start={st} mid={mid} end={en} arc_angle={ang} swapped={sw}")
    # inner layers table
    print("\n### inner copper mapping (cu_count=16)")
    print(", ".join(f"{n}->{leg_layer2new(n)}" for n in range(0, 16)))
    print("\n### text layer mapping")
    print(", ".join(f"{n}->{leg_layer2new(n)}" for n in range(16, 29)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
