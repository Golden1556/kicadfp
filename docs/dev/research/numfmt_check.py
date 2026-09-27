import re, glob, os, collections, math
ROOT = "/private/tmp/claude-501/-Users-juli-Desktop-Claude/ec137c75-6d2e-4a41-bb2c-d385126baef6/scratchpad/kfp"

def fmt_iu(v_mm: float) -> str:
    """Python port of EDA_UNIT_UTILS::FormatInternalUnits (9.0 eda_units.cpp:170-200) operating on mm double."""
    if v_mm != 0.0 and abs(v_mm) <= 0.0001:
        s = "%.10f" % v_mm
        s = s.rstrip("0")
        if s.endswith("."):
            s = s[:-1]
        return s
    return "%.10g" % v_mm

def fmt_double2str(v: float) -> str:
    """Port of FormatDouble2Str (string_utils.cpp)."""
    if v != 0.0 and abs(v) <= 0.0001:
        s = "%.16f" % v
        s = s.rstrip("0")
        if s.endswith("."):
            s = s[:-1]
        return s
    return "%.10g" % v

def fmt_iu_int(iu: int) -> str:
    return fmt_iu(iu / 1e6)

print("== requested samples (FormatInternalUnits on mm values; IU = round(mm*1e6)) ==")
for v in [0.15, 1.6, 3.81, 0.000001, 12.3456789, -0.05, 1e-5, 100, 0.1+0.2, 0.0001, 0.00015, 1234567.891, 1e-7, 2.5e-5, 0.3333333333333, 1e10, 123456789012]:
    iu = round(v*1e6)
    print("%-18r IU=%-14d FormatInternalUnits=%-16s FormatDouble2Str(mm)=%s" % (v, iu, fmt_iu_int(iu), fmt_double2str(v)))

# Round-trip check on real files: every number token written by pcbnew must be reproduced.
num_re = re.compile(r'(?<=[\s(])(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?=[\s)])')
for d in ["v8.0.0", "v9.0.0", "master", "v7.0.0"]:
    files = glob.glob(os.path.join(ROOT, d, "**", "*.kicad_mod"), recursive=True)
    total = ok = 0; bad = collections.Counter(); nfiles = 0; version_tok = 0; expo = collections.Counter()
    for f in files:
        txt = open(f, encoding="utf-8", errors="replace").read()
        if '(generator "pcbnew")' not in txt and '(generator pcbnew)' not in txt:
            continue
        nfiles += 1
        # strip quoted strings so uuids/text are not scanned
        stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', txt)
        # drop (tedit HEX) and (version N)
        stripped = re.sub(r'\(tedit [0-9A-Fa-f]+\)', '', stripped)
        stripped = re.sub(r'\(version \d+\)', '', stripped)
        stripped = re.sub(r'\(tstamp [0-9a-f-]+\)', '', stripped)
        stripped = re.sub(r'\(zone_connect \d\)', '', stripped)
        stripped = re.sub(r'\(net \d+ ""\)', '', stripped)
        for m in num_re.finditer(stripped):
            s = m.group(1)
            total += 1
            v = float(s)
            if 'e' in s or 'E' in s:
                expo[s] += 1
            if fmt_iu(v) == s or fmt_double2str(v) == s:
                ok += 1
            else:
                bad[(s, fmt_iu(v))] += 1
    print("\n== %s: pcbnew files=%d numeric tokens=%d reproduced=%d mismatched=%d" % (d, nfiles, total, ok, total-ok))
    print("   exponent tokens seen:", dict(expo.most_common(8)))
    print("   mismatches (token, python):", bad.most_common(12))
