"""CLI: python -m kicadgen <spec.yaml> -o <outdir> | python -m kicadgen check <files...>"""

from __future__ import annotations

import argparse
import os
import sys


def _cmd_gen(args) -> int:
    from .spec import load_spec, generate
    from .reader_lib import load_library
    from .reader_pro import read_project, check_project
    from .sch import load_schematic
    from .spec import SpecError
    from .model import ValidationError
    spec = load_spec(args.spec)
    out = args.out or os.path.dirname(os.path.abspath(args.spec))
    try:
        files = generate(spec, out, date=args.date)
    except (SpecError, ValidationError) as e:
        print('spec error: %s' % e)
        return 1
    rc = 0
    for f in files:
        print('wrote', f)
    if not args.no_check:
        rc = _check(files)
    return rc


def _check(files) -> int:
    from .reader_lib import load_library, LibLoadError
    from .reader_pro import read_project, check_project
    from .sch import load_schematic, SchLoadError
    rc = 0
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        try:
            if ext == '.lib':
                lib, w = load_library(f, strict=True)
                print('OK  %s: %d components%s' % (f, len(lib.components), '' if not w else ' (warnings below)'))
                for x in w:
                    print('    warning:', x)
            elif ext in ('.dcm', '.net'):
                continue   # .dcm проверяется вместе с .lib; .net — выход, не вход
            elif ext == '.mod':
                from .mod import load_modlib, ModLoadError
                try:
                    ml = load_modlib(f)
                except ModLoadError as e:
                    print('BAD %s: %s' % (f, e)); rc = 1; continue
                print('OK  %s: %d footprints (%s)' % (f, len(ml.footprints), ', '.join(m.name for m in ml.footprints)))
            elif ext == '.pro':
                cfg = read_project(f)
                ok, notes = check_project(cfg)
                print('%s  %s: eeschema libs = %s' % ('OK ' if ok else 'BAD', f, ', '.join(cfg.get('eeschema/libraries', {}).values())))
                for x in notes:
                    print('    note:', x)
                if not ok:
                    rc = 1
            elif ext == '.sch':
                sch, w = load_schematic(f)
                print('OK  %s: %d items, %d components' % (f, len(sch.items), len(sch.components())))
                for x in w:
                    print('    warning:', x)
            else:
                print('??  %s: unknown extension' % f)
        except (LibLoadError, SchLoadError) as e:
            print('BAD %s: %s' % (f, e))
            rc = 1
    return rc


def _render(args) -> int:
    from . import render
    from .reader_lib import load_library
    from .sch import load_schematic
    from . import model as M
    ext = os.path.splitext(args.file)[1].lower()
    out = args.out or os.path.splitext(args.file)[0] + '.svg'
    if ext == '.lib':
        lib, _ = load_library(args.file)
        svg = render.render_library(lib)
    elif ext == '.sch':
        lib = M.Library()
        libs = list(args.lib)
        base = os.path.splitext(args.file)[0]
        for cand in (base + '-cache.lib', base + '.lib'):
            if not libs and os.path.exists(cand):
                libs.append(cand)
        for l in libs:
            sub, _ = load_library(l)
            lib.components.extend(sub.components)
        sch, _ = load_schematic(args.file)
        svg = render.render_schematic(sch, lib)
    elif ext == '.mod':
        from .mod import load_modlib
        svg = render.render_modlib(load_modlib(args.file))
    else:
        print('render: expected .lib, .sch or .mod')
        return 2
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(svg)
    print('wrote', out)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='kicadgen', description=__doc__)
    sub = p.add_subparsers(dest='cmd')
    g = sub.add_parser('gen', help='generate project files from YAML spec')
    g.add_argument('spec')
    g.add_argument('-o', '--out')
    g.add_argument('--date', help='date string for headers (default: now, ru locale style)')
    g.add_argument('--no-check', action='store_true')
    r = sub.add_parser('render', help='render .lib (all symbols), .sch or .mod (footprints) to SVG for visual inspection')
    r.add_argument('file')
    r.add_argument('-l', '--lib', action='append', default=[], help='library .lib for schematic symbols (repeatable)')
    r.add_argument('-o', '--out', help='output .svg (default: alongside)')
    c = sub.add_parser('check', help='strictly validate .lib/.dcm/.pro/.sch files as KiCad 2011 would load them')
    c.add_argument('files', nargs='+')
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ('gen', 'check', 'render', '-h', '--help'):
        argv.insert(0, 'gen')
    args = p.parse_args(argv)
    if args.cmd == 'gen':
        return _cmd_gen(args)
    if args.cmd == 'check':
        return _check(args.files)
    if args.cmd == 'render':
        return _render(args)
    p.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
