#!/usr/bin/env python3
"""
Table-driven emulation of the whitespace layout produced by the KiCad footprint writers that
predate Prettify, for .kicad_mod files, plus a byte-for-byte round-trip checker:

  "5.1"  - pcbnew/kicad_plugin.cpp (KiCad 5.x, root "module")
  "5.99" - 6.0 development nightlies: like 6.0, but the whole header incl. (layer) on line 1
  "6.0"  - pcbnew/plugins/kicad/pcb_plugin.cpp 6.0.x (version 20211014)
           option keepout_pads_space=True reproduces 6.0.0..6.0.6 "(pads %s )"
  "7.0"  - pcbnew/plugins/kicad/pcb_plugin.cpp 7.0.x (version 20221018)

    python layout67.py [--writer=5.1|5.99|6.0|7.0|auto] <dir-or-file> ...

The tree comes from prettify.tokenize (atoms verbatim). Only the *layout* is emulated:
child order / presence is taken from the tree as-is. Files end with ")\n".
"""
from __future__ import annotations

import collections
import glob
import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prettify import tokenize, first_difference  # noqa: E402

IND = "  "          # OUTPUTFORMATTER::Print: NESTWIDTH = 2 spaces per nest level (richio.cpp)


def name_of(node) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def inline(node, writer: str = "6.0") -> str:
    """One-line rendering: '(' + items separated by single spaces + ')'.
    Mirrors Print( ..., "(tok %s (sub %s) ...)" ) format strings of the writers."""
    if isinstance(node, str):
        return node
    parts = [inline(ch, writer) for ch in node]
    s = "(" + " ".join(parts) + ")"
    if writer == "5.1" and name_of(node) == "rect_delta":
        s = s[:-1] + " )"          # 5.1: Print( 0, " (rect_delta %s )" ) — stray space (bug)
    return s


# ---------------------------------------------------------------------------
# Layout tables
# ---------------------------------------------------------------------------

# Node -> layout rule, per writer.  "inline" = the whole node on ONE line at the current nest
# (items separated by one space, no space before ')'), followed by "\n".
# The Formatter.child() dispatcher uses HANDLER; LAYOUT_RULES is the human-readable table.
HANDLER = {
    "fp_text": "fp_text",
    "fp_text_box": "fp_text_box",          # 7.0 only
    "fp_line": "shape", "fp_rect": "shape", "fp_circle": "shape", "fp_arc": "shape",
    "fp_curve": "shape",
    "fp_poly": "fp_poly",
    "pad": "pad",
    "zone": "zone",
    "group": "group",
    "model": "model",
    # everything else (at, descr, tags, property, path, autoplace_cost*, solder_*, clearance,
    # zone_connect, thermal_*, attr, private_layers, net_tie_pad_groups, ...) -> "inline"
}

LAYOUT_RULES = {
    "footprint/module": {
        "5.1":  '(module NAME[ locked][ placed] (layer L) (tedit T)[ (tstamp X)]\\n ; children @1 ; ")\\n"',
        "5.99": '(footprint NAME (version V) (generator pcbnew)[ locked][ placed] (layer L)\\n ; @1 (tedit T) (tstamp U)\\n',
        "6.0":  '(footprint NAME (version V) (generator pcbnew)\\n  [locked ][placed ](layer L)\\n ; @1 (tedit T)[ (tstamp U)]\\n',
        "7.0":  'as 6.0 but no tedit; [@1 (tstamp U)\\n] on its own line',
    },
    "inline children": {"all": "@1 (tok ...)\\n"},
    "fp_text": {
        "5.1/6.0": '@n (fp_text TYPE[ locked] TEXT (at X Y[ A])[ unlocked]) (layer L)[ hide]\\n ; @n+1 (effects ...)\\n ; [6.0: @n+1 (tstamp U)\\n] ; @n )\\n',
        "7.0": 'as 6.0 but (effects) @n+2 ; (tstamp) @n+1 ; [render_cache @n+1]',
    },
    "fp_line/rect/circle/arc/curve": {
        "5.1/6.0": "@n whole node inline",
        "7.0": '@n (fp_x[ locked] (start) (end)...\\n ; @n+1 (stroke ...)[ (fill ..)] (layer L) (tstamp U))\\n',
    },
    "fp_poly": {
        "5.1": '@n (fp_poly (pts (xy)x4 ; every 4th point: "\\n" @n+1 (xy) (xy)... ) (layer) (width))\\n',
        "6.0": '@n (fp_poly[ locked] (pts ; each point "\\n" @n+2 (xy) ; "\\n" @n+1 ")" then " (layer) (width) (fill) (tstamp))\\n"',
        "7.0": '@n (fp_poly[ locked]\\n ; @n+1 (pts\\n ; @n+2 (xy)\\n each ; @n+1 )\\n ; "\\n" (EMPTY LINE) ; @n+1 (stroke) (fill) (layer) (tstamp))\\n',
    },
    "pad": {
        "all": 'line 1: @n (pad N TYPE SHAPE[ locked] (at) (size) [(rect_delta)] [(drill)] [(property)] (layers) '
               '[(remove_unused_layers)] [(keep_end_layers)] [(zone_layer_connections)] [(roundrect_rratio)]',
        "6.0/7.0 chamfer": '"\\n" @n+1 (chamfer_ratio R) (chamfer ...)',
        "second line": '"\\n" @n+1 (net) (pinfunction) (pintype) (die_length) (solder_*) (clearance) (zone_connect) (thermal_*)',
        "custom": '"\\n" @n+1 (options ...) ; "\\n" @n+1 (primitives ; each prim "\\n" @n+2 ... ; "\\n" @n+1 ")"',
        "end": '[6.0/7.0: " (tstamp U)"] ")\\n"',
    },
    "model": {"all": '@n (model PATH[ hide]\\n ; [@n+1 (opacity X) - NO newline] ; @n+1 (offset|at (xyz))\\n ; @n+1 (scale ..)\\n ; @n+1 (rotate ..)\\n ; @n )\\n'},
    "group": {"6.0/7.0": '@n (group NAME[ locked] (id U)\\n ; @n+1 (members\\n ; @n+2 UUID\\n each ; @n+1 )\\n ; @n )\\n'},
    "zone": {"6.0/7.0": "see Formatter.zone()"},
}

# pad: children that go to the "second line" at nest+1 (StrPrintf(&output, ...) block)
PAD_SECOND_LINE = {
    "net", "pinfunction", "pintype", "die_length", "solder_mask_margin",
    "solder_paste_margin", "solder_paste_margin_ratio", "clearance", "zone_connect",
    "thermal_width", "thermal_gap",                      # 5.1 / 6.0 (thermal_gap also 7.0)
    "thermal_bridge_width", "thermal_bridge_angle",      # 7.0
}
PAD_CHAMFER_LINE = {"chamfer_ratio", "chamfer"}          # 6.0/7.0: "\n" + nest+1 + "(chamfer_ratio) (chamfer ...)"


class Formatter:
    def __init__(self, writer: str, keepout_pads_space: bool = False):
        self.w = writer
        # KiCad 6.0.0 .. 6.0.6: "(keepout (tracks %s) (vias %s) (pads %s ) (copperpour %s) ..."
        # (stray space, fixed in 6.0.7). Not representable in the tree -> writer option.
        self.keepout_pads_space = keepout_pads_space
        self.out: List[str] = []

    # -- helpers ---------------------------------------------------------
    def p(self, nest: int, s: str):
        self.out.append(IND * nest + s)

    # -- footprint -------------------------------------------------------
    def footprint(self, node, nest=0):
        w = self.w
        kids = node[1:]
        byname = collections.defaultdict(list)
        for k in kids:
            if isinstance(k, list):
                byname[name_of(k)].append(k)
        fpname = kids[0] if kids and isinstance(kids[0], str) else '""'
        flags = [k for k in kids if isinstance(k, str) and k in ("locked", "placed")]

        if w == "5.1":
            # 5.1: Print( nest, "(module %s" ); [" locked"][" placed"]; formatLayer -> " (layer %s)";
            #      " (tedit %lX)"; [" (tstamp %lX)"] "\n"
            line = "(module " + fpname
            for f in flags:
                line += " " + f
            line += " " + inline(byname["layer"][0], w)
            for t in byname.get("tedit", []):      # always written by 5.1; tolerate files without it
                line += " " + inline(t, w)
            for t in byname.get("tstamp", []):
                line += " " + inline(t, w)
            self.p(nest, line + "\n")
            consumed = {"layer", "tedit", "tstamp"}
        else:
            # 6.0/7.0: "(footprint %s" + " (version %d) (generator pcbnew)\n " +
            #          [" locked"][" placed"] + " (layer %s)" + "\n"
            line = "(footprint " + fpname
            line += " " + inline(byname["version"][0], w) + " " + inline(byname["generator"][0], w)
            if w != "5.99":
                # 5.99 nightlies up to commit 80c5b1ef (2021-11-13) had no "\n " here: the whole
                # header incl. (layer) was on line 1
                line += "\n "
            for f in flags:
                line += " " + f
            line += " " + inline(byname["layer"][0], w) + "\n"
            self.p(nest, line)
            consumed = {"version", "generator", "layer"}
            if w in ("5.99", "6.0"):
                # "(tedit %lX)" [" (tstamp %s)"] "\n"
                line = " ".join(inline(t, w) for t in byname.get("tedit", []) + byname.get("tstamp", []))
                self.p(nest + 1, line + "\n")
                consumed |= {"tedit", "tstamp"}
            else:  # 7.0: "(tstamp %s)\n" on its own line, no tedit
                for t in byname.get("tstamp", []):
                    self.p(nest + 1, inline(t, w) + "\n")
                consumed |= {"tstamp"}

        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n in consumed:
                continue
            self.child(k, nest + 1)
        self.p(nest, ")\n")

    # -- dispatcher -------------------------------------------------------
    def child(self, node, nest):
        h = HANDLER.get(name_of(node))
        if h is None:
            # descr, tags, attr, property, ... and anything unknown: one line
            self.p(nest, inline(node, self.w) + "\n")
        else:
            getattr(self, h)(node, nest)

    # -- fp_text ------------------------------------------------------------
    def fp_text(self, node, nest):
        # "(fp_text TYPE[ locked] TEXT (at ...)[ unlocked]) (layer L)[ hide]\n"
        #   nest+1: "(effects ...)\n"       (EDA_TEXT::Format, one line)
        #   nest+1: "(tstamp X)\n"          (6.0/7.0 only)
        #   [7.0: render_cache block]
        # nest: ")\n"
        head, rest = [], []
        for k in node[1:]:
            if isinstance(k, list) and name_of(k) in ("effects", "tstamp", "render_cache"):
                rest.append(k)
            else:
                head.append(k)
        self.p(nest, "(fp_text " + " ".join(inline(k, self.w) for k in head) + "\n")
        for k in rest:
            n = name_of(k)
            if n == "render_cache":
                self.render_cache(k, nest + 1)
            elif n == "effects" and self.w == "7.0":
                # 7.0: aText->EDA_TEXT::Format( m_out, aNestLevel + 1, ... ) -> printed at nest+2
                self.p(nest + 2, inline(k, self.w) + "\n")
            else:
                self.p(nest + 1, inline(k, self.w) + "\n")
        self.p(nest, ")\n")

    def fp_text_box(self, node, nest):
        # 7.0 PCB_PLUGIN::format(FP_TEXTBOX*):
        #   nest   "(fp_text_box[ locked] TEXT\n"
        #   RECT:  nest "(start ..) (end ..)"            (sic: aNestLevel, not +1)
        #   POLY:  formatPolyPts(nest, compact=true)      -> ends with ")\n", next items start at col 0
        #   [" (angle A)"] " (layer L)" " (tstamp U)" "\n"
        #   EDA_TEXT::Format(nest+1) -> nest+2 "(effects ...)\n"
        #   [stroke width>0] nest+1 "(stroke ...)"       (NO newline)
        #   [render_cache at nest+1]
        #   nest ")\n"
        # Not verified on real files (no 7.0 fixtures contain fp_text_box).
        kids = node[1:]
        head = [k for k in kids if isinstance(k, str)]
        self.p(nest, "(fp_text_box " + " ".join(head) + "\n")
        line = ""
        poly = False
        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n == "pts":
                self.poly_pts(k, nest, compact=True)
                poly = True
            elif n in ("start", "end"):
                line += (" " if line else "") + inline(k, self.w)
            elif n in ("angle", "layer", "tstamp"):
                line += " " + inline(k, self.w)
        self.out.append((IND * nest if not poly else "") + line + "\n")
        for k in kids:
            if name_of(k) == "effects":
                self.p(nest + 2, inline(k, self.w) + "\n")
        for k in kids:
            if name_of(k) == "stroke":
                self.p(nest + 1, inline(k, self.w))
        for k in kids:
            if name_of(k) == "render_cache":
                self.render_cache(k, nest + 1)
        self.p(nest, ")\n")

    def render_cache(self, node, nest):
        # 7.0 formatRenderCache: "(render_cache TEXT ANGLE\n" ; polygons: nest+1 "(polygon\n" formatPolyPts(nest+1|+2, compact=True) nest+1 ")\n" ; nest ")\n"
        self.p(nest, "(render_cache " + " ".join(inline(k, self.w) for k in node[1:3]) + "\n")
        for poly in node[3:]:
            self.p(nest + 1, "(polygon\n")
            for i, pts in enumerate(poly[1:]):
                self.poly_pts(pts, nest + 1 if i == 0 else nest + 2, compact=True)
            self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    # -- shapes ---------------------------------------------------------------
    def shape(self, node, nest):
        w = self.w
        if w in ("5.1", "5.99", "6.0"):
            self.p(nest, inline(node, w) + "\n")
            return
        # 7.0: "(fp_line[ locked] (start) (end)" "\n" ; nest+1 "(stroke ...)" [" (fill ..)"] " (layer ..)" " (tstamp ..)" ")\n"
        head, tail = [], []
        for k in node[1:]:
            if isinstance(k, list) and name_of(k) in ("stroke", "fill", "layer", "tstamp"):
                tail.append(k)
            else:
                head.append(k)
        self.p(nest, "(" + name_of(node) + " " + " ".join(inline(k, w) for k in head) + "\n")
        self.p(nest + 1, " ".join(inline(k, w) for k in tail) + ")\n")

    def poly_pts(self, pts, nest, compact=False):
        """7.0 formatPolyPts( outline, aNestLevel=nest, aCompact ): nest+1 "(pts\n", each point at
        nest+2 followed by "\n" (aCompact=false => every point), nest+1 ")\n"."""
        self.p(nest + 1, "(pts\n")
        pts_items = pts[1:]
        need_nl = False
        for i, pt in enumerate(pts_items, 1):
            self.p(nest + 2, inline(pt, self.w))
            need_nl = True
            if (i % 4 == 0) or not compact:
                self.out.append("\n")
                need_nl = False
        if need_nl:
            self.out.append("\n")
        self.p(nest + 1, ")\n")

    def fp_poly(self, node, nest):
        w = self.w
        kids = node[1:]
        flags = [k for k in kids if isinstance(k, str)]
        pts = next(k for k in kids if name_of(k) == "pts")
        tail = [k for k in kids if isinstance(k, list) and name_of(k) != "pts"]
        head = "(fp_poly" + "".join(" " + f for f in flags)
        if w == "5.1":
            # "(fp_poly (pts" ; points: " (xy)" ; every 4th point (ii && !(ii%4)): "\n" + nest+1 indent, no leading space
            line = head + " (pts"
            self.out.append(IND * nest + line)
            for i, pt in enumerate(pts[1:]):
                if i and i % 4 == 0:
                    self.out.append("\n" + IND * (nest + 1) + inline(pt, w))
                else:
                    self.out.append(" " + inline(pt, w))
            self.out.append(")")                                     # closes (pts
            self.out.append(" " + " ".join(inline(k, w) for k in tail) + ")\n")
        elif w in ("5.99", "6.0"):
            # "(fp_poly[ locked] (pts" ; each point: "\n" + nest+2 "(xy ..)" (m_CompactSave=false => every point)
            # then "\n" + nest+1 ")" ; then " (layer) (width) (fill) (tstamp))\n"
            self.out.append(IND * nest + head + " (pts")
            for pt in pts[1:]:
                self.out.append("\n" + IND * (nest + 2) + inline(pt, w))
            self.out.append("\n" + IND * (nest + 1) + ")")
            self.out.append(" " + " ".join(inline(k, w) for k in tail) + ")\n")
        else:
            # 7.0: "(fp_poly[ locked]\n" ; formatPolyPts(nest) ; "\n" (=> blank line!) ; nest+1 "(stroke ..) (fill ..) (layer ..) (tstamp ..))\n"
            self.p(nest, head + "\n")
            self.poly_pts(pts, nest, compact=False)
            self.out.append("\n")
            self.p(nest + 1, " ".join(inline(k, w) for k in tail) + ")\n")

    # -- pad ---------------------------------------------------------------
    def pad(self, node, nest):
        w = self.w
        kids = node[1:]
        first, chamfer, second, options, prims, tstamp = [], [], [], None, None, []
        for k in kids:
            n = name_of(k) if isinstance(k, list) else ""
            if n in PAD_SECOND_LINE:
                second.append(k)
            elif n in PAD_CHAMFER_LINE:
                chamfer.append(k)
            elif n == "options":
                options = k
            elif n == "primitives":
                prims = k
            elif n == "tstamp":
                tstamp.append(k)
            else:
                first.append(k)
        self.out.append(IND * nest + "(pad " + " ".join(inline(k, w) for k in first))
        if chamfer:
            self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in chamfer))
        if second:
            self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in second))
        if options is not None:
            self.out.append("\n" + IND * (nest + 1) + inline(options, w))
        if prims is not None:
            self.primitives(prims, nest)
        for t in tstamp:
            self.out.append(" " + inline(t, w))
        self.out.append(")\n")

    def primitives(self, prims, nest):
        """(primitives ...) of a custom pad. `nest` = nest level of the pad."""
        w = self.w
        self.out.append("\n" + IND * (nest + 1) + "(primitives")
        nested_level = nest + 2
        for prim in prims[1:]:
            self.out.append("\n")
            pn = name_of(prim)
            if w == "5.1":
                if pn == "gr_poly":
                    pts = next(k for k in prim[1:] if name_of(k) == "pts")
                    tail = [k for k in prim[1:] if isinstance(k, list) and name_of(k) != "pts"]
                    self.out.append(IND * nested_level + "(gr_poly (pts\n")
                    new_line = 0
                    for pt in pts[1:]:
                        if new_line == 0:
                            self.out.append(IND * (nested_level + 1) + " " + inline(pt, w))
                        else:
                            self.out.append(" " + inline(pt, w))
                        new_line += 1
                        if new_line > 4:
                            new_line = 0
                            self.out.append("\n")
                    self.out.append(")" + " " + " ".join(inline(k, w) for k in tail) + ")")
                else:
                    self.out.append(IND * nested_level + inline(prim, w))
                continue
            # 6.0 / 7.0
            head = [k for k in prim[1:] if not (isinstance(k, list) and name_of(k) in ("width", "fill", "pts"))]
            tail = [k for k in prim[1:] if isinstance(k, list) and name_of(k) in ("width", "fill")]
            if pn == "gr_poly":
                pts = next(k for k in prim[1:] if name_of(k) == "pts")
                if w in ("5.99", "6.0"):
                    # "(gr_poly (pts" ; each point "\n" + (nest+4) "(xy)" ; "\n" + (nest+3) ")" ;
                    # BUG: the loop overwrites `nested_level` (0 or nest+4) => later primitives are
                    # indented with nest+4 instead of nest+2.
                    self.out.append(IND * nested_level + "(gr_poly (pts")
                    for pt in pts[1:]:
                        nested_level = nest + 4
                        self.out.append("\n" + IND * nested_level + inline(pt, w))
                    self.out.append("\n" + IND * (nest + 3) + ")")
                else:
                    # 7.0: "(gr_poly\n" formatPolyPts(nested_level, compact) ; Print(nested_level, " ")
                    self.out.append(IND * nested_level + "(gr_poly\n")
                    self.poly_pts(pts, nested_level, compact=False)
                    self.out.append(IND * nested_level + " ")
            elif pn == "gr_curve":
                pts = next(k for k in prim[1:] if name_of(k) == "pts")
                self.out.append(IND * nested_level + "(gr_curve " + inline(pts, w))
            elif pn == "gr_arc" and w in ("5.99", "6.0"):
                # 6.0 BUG: Print( aNestLevel, "(gr_arc ..." ) — pad's nest level, not nested_level
                self.out.append(IND * nest + "(" + pn + " " + " ".join(inline(k, w) for k in head) + "")
            else:
                self.out.append(IND * nested_level + "(" + pn + " " + " ".join(inline(k, w) for k in head))
            for k in tail:
                self.out.append(" " + inline(k, w))
            self.out.append(")")
        self.out.append("\n" + IND * (nest + 1) + ")")

    # -- model ----------------------------------------------------------------
    def model(self, node, nest):
        w = self.w
        kids = node[1:]
        head = [k for k in kids if isinstance(k, str)]              # path, "hide"
        self.p(nest, "(model " + " ".join(head) + "\n")
        for k in kids:
            if isinstance(k, str):
                continue
            n = name_of(k)
            if n == "opacity":
                self.p(nest + 1, inline(k, w))                      # NO trailing newline (source)
            else:
                self.p(nest + 1, inline(k, w) + "\n")
        self.p(nest, ")\n")

    # -- group ----------------------------------------------------------------
    def group(self, node, nest):
        kids = node[1:]
        head = [inline(k, self.w) for k in kids if isinstance(k, str) or name_of(k) == "id"]
        self.p(nest, "(group " + " ".join(head) + "\n")
        for k in kids:
            if name_of(k) == "members":
                self.p(nest + 1, "(members\n")
                for m in k[1:]:
                    self.p(nest + 2, m + "\n")
                self.p(nest + 1, ")\n")
        self.p(nest, ")\n")

    # -- zone (6.0/7.0; no .kicad_mod fixtures of these versions contain zones) --
    def zone(self, node, nest):
        w = self.w
        kids = node[1:]
        line1, rest = [], []
        for k in kids:
            n = name_of(k) if isinstance(k, list) else ""
            if isinstance(k, str) or n in ("net", "net_name", "layer", "layers", "tstamp", "name", "hatch"):
                line1.append(k)
            else:
                rest.append(k)
        self.p(nest, "(zone " + " ".join(inline(k, w) for k in line1) + "\n")
        for k in rest:
            n = name_of(k)
            if n == "fill":
                self.zone_fill(k, nest + 1)
            elif n == "min_thickness":
                self.p(nest + 1, inline(k, w))
                self.out.append("\n")  # (filled_areas_thickness no) is a sibling in the tree -> handled below
            elif n == "filled_areas_thickness":
                # written on the min_thickness line: back-patch
                self.out[-1] = " " + inline(k, w) + "\n"
            elif n in ("polygon", "filled_polygon"):
                self.p(nest + 1, "(" + n + "\n")
                for sub in k[1:]:
                    if name_of(sub) == "pts":
                        if w in ("5.99", "6.0"):
                            self.out.append(IND * (nest + 2) + "(pts")
                            for pt in sub[1:]:
                                self.out.append("\n" + IND * (nest + 3) + inline(pt, w))
                            self.out.append("\n" + IND * (nest + 2) + ")\n")
                        else:
                            self.poly_pts(sub, nest + 1, compact=False)
                    else:
                        self.p(nest + 2, inline(sub, w) + "\n")
                self.p(nest + 1, ")\n")
            elif n == "keepout" and self.keepout_pads_space:
                txt = inline(k, w).replace("(pads allowed)", "(pads allowed )") \
                                  .replace("(pads not_allowed)", "(pads not_allowed )")
                self.p(nest + 1, txt + "\n")
            else:
                self.p(nest + 1, inline(k, w) + "\n")
        self.p(nest, ")\n")

    def zone_fill(self, node, nest):
        w = self.w
        line = "(fill"
        extra = []
        for k in node[1:]:
            n = name_of(k) if isinstance(k, list) else ""
            if n.startswith("hatch_"):
                extra.append(k)
            else:
                line += " " + inline(k, w)
        self.out.append(IND * nest + line)
        if extra:
            # hatch params: 2 or 3 lines at nest+1 (pairs: thickness/gap/orientation ; smoothing ; border/min_hole)
            groups = [[], [], []]
            for k in extra:
                n = name_of(k)
                gi = 0 if n in ("hatch_thickness", "hatch_gap", "hatch_orientation") else \
                     1 if n.startswith("hatch_smoothing") else 2
                groups[gi].append(k)
            for g in groups:
                if g:
                    self.out.append("\n" + IND * (nest + 1) + " ".join(inline(k, w) for k in g))
        self.out.append(")\n")


def format_tree(tree, writer: str, keepout_pads_space: bool = False) -> str:
    f = Formatter(writer, keepout_pads_space)
    f.footprint(tree, 0)
    return "".join(f.out)


def detect_writer(tree) -> str:
    if name_of(tree) == "module":
        return "5.1"
    for k in tree[1:]:
        if name_of(k) == "version":
            v = int(k[1])
            if v < 20211014:
                return "5.99"          # 6.0 development nightlies (only header differs from 6.0)
            return "6.0" if v < 20221018 else "7.0"
    return "6.0"


def _meta(tree):
    d = {}
    for k in tree[1:]:
        if isinstance(k, list) and k and k[0] in ("version", "generator"):
            d[k[0]] = k[1]
    return d


def check_file(path: str, writer: str = "auto"):
    """Returns (path, writer_used, meta, class, diff). class is one of
    exact | exact-no-final-nl | header-only | other | EXC"""
    raw = open(path, "rb").read()
    tree = tokenize(raw.decode("utf-8"))
    meta = _meta(tree)
    w = detect_writer(tree) if writer == "auto" else writer
    candidates = [(w, False)]
    if w == "6.0":
        # 6.0.0-6.0.6 keepout stray space; 20211014 files written by nightlies 2021-10-15..11-13
        candidates += [(w, True), ("5.99", False), ("5.99", True)]
    try:
        best = None
        for cw, kps in candidates:
            out = format_tree(tree, cw, kps).encode("utf-8")
            if out == raw:
                return path, cw + (" +keepout-space" if kps else ""), meta, "exact", ""
            if out.rstrip(b"\n") == raw.rstrip(b"\n"):
                best = best or (cw + (" +keepout-space" if kps else ""), "exact-no-final-nl", "")
            if best is None and cw == w and not kps:
                first = out
        if best:
            return (path, best[0], meta, best[1], "")
    except Exception as e:  # noqa: BLE001
        return path, w, meta, "EXC", f"{type(e).__name__}: {e}"
    ro, oo = raw.split(b"\n"), first.split(b"\n")
    if b"\n".join(ro[2:]).rstrip(b"\n") == b"\n".join(oo[2:]).rstrip(b"\n"):
        return path, w, meta, "header-only", first_difference(raw, first)
    return path, w, meta, "other", first_difference(raw, first)


def _worker(a):
    return check_file(*a)


def main(argv):
    from multiprocessing import Pool
    writer = "auto"
    paths = []
    for a in argv:
        if a.startswith("--writer="):
            writer = a.split("=", 1)[1]
        elif os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "**", "*.kicad_mod"), recursive=True))
        else:
            paths.append(a)
    with Pool() as pool:
        res = pool.map(_worker, [(p, writer) for p in paths], chunksize=32)
    print(f"files={len(res)}")
    c = collections.Counter((r[1], r[2].get("version"), r[2].get("generator"), r[3]) for r in res)
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {v:6d}  writer={k[0]:<22} version={k[1]} generator={k[2]} -> {k[3]}")
    shown = 0
    for r in res:
        if r[3] in ("other", "header-only", "EXC") and shown < 15:
            print("  DIFF", r[3], r[0], "::", r[4][:260])
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
