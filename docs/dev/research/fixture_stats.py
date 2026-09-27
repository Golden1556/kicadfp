import re, sys, os, glob, collections
ROOT = "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp"
CHECKS = [
 ("(hide yes)", r"\(hide yes\)"),
 ("bare hide (space-delimited, not '(hide')", r"(?<![(\w])hide(?=[\s)])"),
 ("(fill solid)", r"\(fill solid\)"),
 ("(fill none)", r"\(fill none\)"),
 ("(fill yes)", r"\(fill yes\)"),
 ("(fill no)", r"\(fill no\)"),
 ('(layers "*.Cu"', r'\(layers "\*\.Cu"'),
 ("(layers *.Cu unquoted", r"\(layers \*\.Cu"),
 ('"F&B.Cu"', r'F&B\.Cu'),
 ('(layer "F.SilkS")', r'\(layer "F\.SilkS"\)'),
 ("(layer F.SilkS) unquoted", r"\(layer F\.SilkS\)"),
 ("(solder_paste_ratio", r"\(solder_paste_ratio "),
 ("(solder_paste_margin_ratio", r"\(solder_paste_margin_ratio "),
 ("(generator pcbnew) bare", r"\(generator pcbnew\)"),
 ('(generator "pcbnew")', r'\(generator "pcbnew"\)'),
 ("(generator_version", r"\(generator_version "),
 ("(tedit", r"\(tedit "),
 ("(tstamp", r"\(tstamp "),
 ("(uuid", r"\(uuid "),
 ("fp_text reference", r"\(fp_text reference"),
 ('(property "Reference"', r'\(property "Reference"'),
 ("(property ki_fp_filters", r"\(property ki_fp_filters"),
 ('(property "ki_fp_filters"', r'\(property "ki_fp_filters"'),
 ("(width  in fp_line (6.0 form)", r"\(fp_line[^\n]*\n?[^\n]*\(width "),
 ("(stroke (width", r"\(stroke \(width"),
 ("(remove_unused_layers) 7.0 bare list", r"\(remove_unused_layers\)"),
 ("(remove_unused_layers no)", r"\(remove_unused_layers no\)"),
 ("(remove_unused_layers yes)", r"\(remove_unused_layers yes\)"),
 ("(keep_end_layers", r"\(keep_end_layers"),
 ("(tenting", r"\(tenting"),
 ("(padstack", r"\(padstack"),
 ("(thermal_bridge_angle", r"\(thermal_bridge_angle"),
 ("(thermal_width  (6.0)", r"\(thermal_width "),
 ("(thermal_bridge_width", r"\(thermal_bridge_width"),
 ("(embedded_fonts", r"\(embedded_fonts"),
 ("(model ... hide bare", r'\(model "[^"]*" hide'),
 ("(model (hide yes)", r"\(model[^\n]*\n\s*\(hide yes\)"),
 ("(opacity", r"\(opacity "),
 ("(model (at (xyz", r"\(at \(xyz"),
 ("(offset (xyz", r"\(offset \(xyz"),
 ("unlocked bare in at", r"\(at [^()]*unlocked\)"),
 ("(unlocked yes)", r"\(unlocked yes\)"),
 ("locked bare after fp_text/fp_line", r"\((?:fp_text|fp_line|fp_rect|fp_circle|fp_arc|fp_poly|pad)[^()]* locked"),
 ("(locked yes)", r"\(locked yes\)"),
 ("(attr smd", r"\(attr smd"),
 ("(attr through_hole", r"\(attr through_hole"),
 ("(attr virtual (v5)", r"\(attr virtual"),
 ("(attr exclude_from_pos_files", r"\(attr[^)]*exclude_from_pos_files"),
 ("(attr ...exclude_from_bom", r"\(attr[^)]*exclude_from_bom"),
 ("(attr ... allow_missing_courtyard", r"\(attr[^)]*allow_missing_courtyard"),
 ("(attr ... dnp", r"\(attr[^)]*\bdnp\b"),
 ("(justify", r"\(justify"),
 ("(justify mirror", r"\(justify[^)]*mirror"),
 ("bold bare in font", r"\(font[^)]*\bbold\b"),
 ("(bold yes)", r"\(bold yes\)"),
 ("(italic yes)", r"\(italic yes\)"),
 ("(line_spacing", r"\(line_spacing"),
 ("(face ", r"\(face "),
 ("(render_cache", r"\(render_cache"),
 ("knockout", r"knockout"),
 ("(zone ", r"\(zone "),
 ("(group ", r"\(group "),
 ("(net_tie_pad_groups", r"\(net_tie_pad_groups"),
 ("(private_layers", r"\(private_layers"),
 ("(clearance ", r"\(clearance "),
 ("(zone_connect", r"\(zone_connect"),
 ("(solder_mask_margin", r"\(solder_mask_margin"),
 ("(solder_paste_margin ", r"\(solder_paste_margin "),
 ("(die_length", r"\(die_length"),
 ("(property pad_prop_", r"\(property pad_prop_"),
 ("(chamfer ", r"\(chamfer "),
 ("(roundrect_rratio", r"\(roundrect_rratio"),
 ("(options", r"\(options"),
 ("(primitives", r"\(primitives"),
 ("(gr_poly in primitives", r"\(gr_poly"),
 ("(drill oval", r"\(drill oval"),
 ("(drill ... (offset", r"\(drill[^)]*\(offset"),
 ("(rect_delta", r"\(rect_delta"),
 ("(pinfunction", r"\(pinfunction"),
 ("(pintype", r"\(pintype"),
 ("(net ", r"\(net "),
 ("(fp_curve", r"\(fp_curve"),
 ("(fp_rect", r"\(fp_rect"),
 ("(fp_poly", r"\(fp_poly"),
 ("(fp_arc", r"\(fp_arc"),
 ("(fp_circle", r"\(fp_circle"),
 ("(arc (start in pts", r"\(pts[^\n]*\n?[^\n]*\(arc \(start"),
 ("(descr", r"\(descr "),
 ("(tags", r"\(tags "),
 ("(path", r"\(path "),
 ("(placed", r"\(placed"),
 ("(sheetname", r"\(sheetname"),
 ("(component_classes", r"\(component_classes"),
 ("(duplicate_pad_numbers_are_jumpers", r"\(duplicate_pad_numbers_are_jumpers"),
 ("(jumper_pad_groups", r"\(jumper_pad_groups"),
 ("(point ", r"\(point "),
 ("(transform", r"\(transform"),
 ("(layer \"F.Cu\") on footprint", r"\(layer \"F\.Cu\"\)"),
 ("(at x y) 2-arg on property/fp_text", r"\((?:fp_text|property)[^\n]*\(at -?[\d.]+ -?[\d.]+\)"),
 ("(at x y angle) 3-arg on property", r"\(property \"[^\"]*\" \"[^\"]*\"\s*\n?\s*\(at -?[\d.]+ -?[\d.]+ -?[\d.]+\)"),
 ("(at x y 0) explicit zero angle", r"\(at -?[\d.]+ -?[\d.]+ 0\)"),
 ("(thickness", r"\(thickness"),
 ("(effects", r"\(effects"),
 ('(type default)', r"\(type default\)"),
 ('(type solid)', r"\(type solid\)"),
 ("(net 0", r"\(net 0 "),
 ("exponent in number e-", r"[\d]e-\d"),
 ("tab char", "\t"),
 ("CRLF", "\r\n"),
 ("(version 20211014", r"\(version 20211014\)"),
 ("(version 20221018", r"\(version 20221018\)"),
 ("(version 20240108", r"\(version 20240108\)"),
 ("(version 20241229", r"\(version 20241229\)"),
 ("(version 20260206", r"\(version 20260206\)"),
 ("(module (v5 root)", r"^\(module "),
 ("(footprint root", r"^\(footprint "),
]
dirs = sys.argv[1:] or ["v6.0.0","v7.0.0","v8.0.0","v9.0.0","master"]
res = {}
nfiles = {}
versions = {}
generators = {}
for d in dirs:
    files = glob.glob(os.path.join(ROOT, d, "**", "*.kicad_mod"), recursive=True)
    nfiles[d] = len(files)
    counts = collections.Counter()
    vers = collections.Counter(); gens = collections.Counter()
    for f in files:
        txt = open(f, encoding="utf-8", errors="replace").read()
        for name, pat in CHECKS:
            if re.search(pat, txt, re.M):
                counts[name] += 1
        m = re.search(r"\(version (\d+)\)", txt)
        vers[m.group(1) if m else "-"] += 1
        m = re.search(r"\(generator[_ ][^)]*\)", txt)
        gens[m.group(0) if m else "-"] += 1
    res[d] = counts; versions[d] = vers; generators[d] = gens
print("files:", nfiles)
print("versions:", {d: dict(versions[d].most_common(4)) for d in dirs})
print("generators:", {d: dict(generators[d].most_common(3)) for d in dirs})
print()
print("%-48s" % "check (files containing)", *["%9s" % d for d in dirs])
for name, _ in CHECKS:
    print("%-48s" % name, *["%9d" % res[d][name] for d in dirs])
