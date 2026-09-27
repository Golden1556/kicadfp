import sys, time, glob, os, re
sys.path.insert(0, '/Users/juli/Desktop/Claude/kicadfp')
from kicadfp import sexpr
dirs = sys.argv[1:]
XY_LINE = re.compile(r'\n\t+\(xy ')
for d in dirs:
    files = sorted(glob.glob(os.path.join(d, '**', '*.kicad_mod'), recursive=True))
    t0 = time.time(); n = eq = exact = exact_nl = xyline = errs = 0; shown = 0
    for f in files:
        raw = open(f, 'rb').read(); text = raw.decode('utf-8')
        try:
            tree = sexpr.parse(text)
            out = sexpr.dumps(tree)
            tree2 = sexpr.parse(out)
        except Exception as e:
            errs += 1
            if shown < 5: print('  ERR', f, repr(e)[:200]); shown += 1
            continue
        n += 1
        if sexpr.equal(tree, tree2): eq += 1
        elif shown < 5: print('  NEQ', f, sexpr.diff(tree, tree2)[:3]); shown += 1
        ob = out.encode('utf-8')
        if ob == raw: exact += 1; exact_nl += 1
        elif ob.rstrip(b'\n') == raw.rstrip(b'\n'): exact_nl += 1
        elif XY_LINE.search(text) and '(xy' in out: xyline += 1
        elif shown < 5:
            a, b = raw, ob; k = 0
            while k < min(len(a), len(b)) and a[k] == b[k]: k += 1
            print('  DIFF', f, 'off', k, repr(a[max(0,k-40):k+60]), '|||', repr(b[max(0,k-40):k+60])); shown += 1
    print(f'{d.split("/")[-1]}: files={n} errors={errs} tree_equal={eq} exact={exact} exact_ignoring_final_nl={exact_nl} xy_per_line_style={xyline} other={n-exact_nl-xyline} time={time.time()-t0:.1f}s')
