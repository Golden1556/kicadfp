import re, glob, os, collections, sys
ROOT = "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp"

# minimal s-expr parser
def parse(txt):
    toks = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+', txt)
    pos = 0
    def rd():
        nonlocal pos
        t = toks[pos]; pos += 1
        if t == '(':
            lst = []
            while toks[pos] != ')':
                lst.append(rd())
            pos += 1
            return lst
        return t
    return rd()

def key(node):
    return node[0] if isinstance(node, list) else None

LAYER9 = {"F.Cu":0,"B.Cu":2,"F.Mask":1,"B.Mask":3,"F.SilkS":5,"B.SilkS":7,"F.Adhes":9,"B.Adhes":11,"F.Paste":13,"B.Paste":15,"Dwgs.User":17,"Cmts.User":19,"Eco1.User":21,"Eco2.User":23,"Edge.Cuts":25,"Margin":27,"B.CrtYd":29,"F.CrtYd":31,"B.Fab":33,"F.Fab":35}
for i in range(1,31): LAYER9["In%d.Cu"%i] = 2+2*i
for i in range(1,10): LAYER9["User.%d"%i] = 37+2*i
LAYER8 = {"F.Cu":0}
for i in range(1,31): LAYER8["In%d.Cu"%i] = i
for i,n in enumerate(["B.Cu","B.Adhes","F.Adhes","B.Paste","F.Paste","B.SilkS","F.SilkS","B.Mask","F.Mask","Dwgs.User","Cmts.User","Eco1.User","Eco2.User","Edge.Cuts","Margin","B.CrtYd","F.CrtYd","B.Fab","F.Fab"]): LAYER8[n] = 31+i
for i in range(1,10): LAYER8["User.%d"%i] = 49+i
SHAPE_ORDER = {"fp_line":0,"fp_rect":1,"fp_arc":2,"fp_circle":3,"fp_poly":4,"fp_curve":5}
# KICAD_T order 9.0: PCB_SHAPE_T < PCB_REFERENCE_IMAGE_T < PCB_FIELD_T < PCB_TEXT_T < PCB_TEXTBOX_T < PCB_TABLE_T < ... < PCB_DIM_*
TYPE_ORDER = {"fp_line":0,"fp_rect":0,"fp_arc":0,"fp_circle":0,"fp_poly":0,"fp_curve":0,"image":1,"fp_text":3,"fp_text_box":4,"table":5,"dimension":9}

ROOT_ORDER = ["version","generator","generator_version","locked","placed","layer","uuid","at","descr","tags","property","component_classes","path","sheetname","sheetfile","solder_mask_margin","solder_paste_margin","solder_paste_margin_ratio","solder_paste_ratio","clearance","zone_connect","attr","private_layers","net_tie_pad_groups","duplicate_pad_numbers_are_jumpers","jumper_pad_groups","DRAWING","point","pad","zone","group","embedded_fonts","embedded_files","model"]
PAD_ORDER = ["at","size","rect_delta","drill","property","layers","remove_unused_layers","keep_end_layers","zone_layer_connections","roundrect_rratio","chamfer_ratio","chamfer","net","pinfunction","pintype","die_length","solder_mask_margin","solder_paste_margin","solder_paste_margin_ratio","clearance","zone_connect","thermal_bridge_width","thermal_bridge_angle","thermal_gap","options","primitives","teardrops","tenting","uuid","padstack"]
TEXT_ORDER = ["locked","at","unlocked","layer","hide","uuid","effects","render_cache"]
SHAPE_ORDER9 = ["start","center","mid","end","pts","stroke","fill","locked","layer","layers","solder_mask_margin","net","uuid"]
SHAPE_ORDER8 = ["start","center","mid","end","pts","locked","stroke","fill","layer","net","uuid"]
EFFECTS_ORDER = ["font","justify","hide","href"]
FONT_ORDER = ["face","size","line_spacing","thickness","bold","italic","color"]
MODEL_ORDER = ["hide","opacity","offset","scale","rotate"]

def strnumcmp_key(s):
    # StrNumCmp: digit runs compare numerically, else char by char
    parts = re.findall(r'\d+|\D', s)
    return [(0,int(p)) if p.isdigit() else (1,ord(p)) for p in parts]

def check_order(children, order, name, viol, seen_set=None):
    idx = []
    for c in children:
        k = key(c)
        if k is None: continue
        if k in SHAPE_ORDER: k = "DRAWING"
        if k == "fp_text" or k == "fp_text_box": k = "DRAWING"
        if k not in order:
            viol[(name, "unknown:"+k)] += 1; continue
        idx.append(order.index(k))
    for a, b in zip(idx, idx[1:]):
        if b < a:
            viol[(name, "%s>%s" % (order[a], order[b]))] += 1
            break

def run(d, layer_map, shape_order_list, want_gen):
    files = glob.glob(os.path.join(ROOT, d, "**", "*.kicad_mod"), recursive=True)
    viol = collections.Counter(); n = 0; ndraw_sorted = 0; ndraw = 0; npads = 0; npads_sorted = 0
    fields = collections.Counter(); pad_at_zero_angle = 0; pad_at_angle = 0; text_at_args = collections.Counter()
    for f in files:
        txt = open(f, encoding="utf-8", errors="replace").read()
        if want_gen not in txt: continue
        n += 1
        tree = parse(txt)
        ch = tree[2:] if tree[0] in ("footprint", "module") else []
        check_order(ch, ROOT_ORDER, "root", viol)
        # fields
        for c in ch:
            if key(c) == "property" and len(c) > 2 and isinstance(c[1], str):
                fields[c[1]] += 1
                check_order(c[3:], TEXT_ORDER, "property", viol)
                eff = [x for x in c if key(x) == "effects"]
                for e in eff:
                    check_order(e[1:], EFFECTS_ORDER, "effects", viol)
                    for fo in e:
                        if key(fo) == "font": check_order(fo[1:], FONT_ORDER, "font", viol)
                at = [x for x in c if key(x) == "at"]
                if at: text_at_args[len(at[0])-1] += 1
            if key(c) == "fp_text":
                check_order(c[3:], TEXT_ORDER, "fp_text", viol)
            if key(c) in SHAPE_ORDER:
                check_order(c[1:], shape_order_list, key(c), viol)
            if key(c) == "pad":
                check_order(c[4:], PAD_ORDER, "pad", viol)
                at = [x for x in c if key(x) == "at"][0]
                if len(at) == 3: pad_at_zero_angle += 1
                else:
                    pad_at_angle += 1
                    if at[3] == "0": viol[("pad","at angle 0 written")] += 1
            if key(c) == "model":
                check_order(c[2:], MODEL_ORDER, "model", viol)
        # drawings sort: (type order, layer id, shape order)
        draws = [c for c in ch if key(c) in SHAPE_ORDER or key(c) == "fp_text"]
        def dkey(c):
            k = key(c)
            layer = [x for x in c if key(x) == "layer"]
            lname = layer[0][1].strip('"') if layer else ""
            return (TYPE_ORDER.get(k, 50), layer_map.get(lname, 999), SHAPE_ORDER.get(k, 0))
        ks = [dkey(c) for c in draws]
        ndraw += 1
        if ks == sorted(ks): ndraw_sorted += 1
        else: viol[("drawings","not sorted by (type,layerId,shape)")] += 1
        pads = [c for c in ch if key(c) == "pad"]
        pn = [strnumcmp_key(c[1].strip('"')) for c in pads]
        npads += 1
        if pn == sorted(pn): npads_sorted += 1
        else: viol[("pads","not sorted by StrNumCmp(number)")] += 1
    print("== %s (%s): files=%d; drawings sorted=%d/%d; pads sorted=%d/%d; pad (at) w/o angle=%d with angle=%d" % (d, want_gen, n, ndraw_sorted, ndraw, npads_sorted, npads, pad_at_zero_angle, pad_at_angle))
    print("   property names:", dict(fields))
    print("   property (at) arg counts:", dict(text_at_args))
    print("   violations:", viol.most_common(15) or "none")

run("v9.0.0", LAYER9, SHAPE_ORDER9, '(generator "pcbnew")')
run("master", LAYER9, SHAPE_ORDER9, '(generator "pcbnew")')
run("v8.0.0", LAYER8, SHAPE_ORDER8, '(generator "pcbnew")')
run("v9.0.0", LAYER9, SHAPE_ORDER9, '(generator "kicad-footprint-generator")')
