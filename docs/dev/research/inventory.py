#!/usr/bin/env python3
"""Empirical token inventory of KiCad .kicad_mod files.

Minimal S-expression parser (no dependencies) + statistics collector.
Usage: inventory.py OUT.json  LABEL=DIR [LABEL=DIR ...]
"""
import sys, os, json, re, collections

# ---------------------------------------------------------------- S-expr parser
# Atom = (kind, text): kind in 'n' (bare numeric), 'y' (bare symbol), 's' (quoted string)
# List = python list whose items are atoms or lists.

NUM_RE = re.compile(r'^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$')


class ParseError(Exception):
    pass


def tokenize(text):
    i, n = 0, len(text)
    comments = []
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '(':
            yield ('(', None); i += 1
        elif c == ')':
            yield (')', None); i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    buf.append(text[j:j + 2]); j += 2
                else:
                    buf.append(text[j]); j += 1
            if j >= n:
                raise ParseError('unterminated string')
            yield ('s', ''.join(buf)); i = j + 1
        elif c == '#' and text[text.rfind('\n', 0, i) + 1:i].strip(' \t\r') == '':
            # like DSNLEXER::NextTok: '#' is a comment only as first non-blank char of a line
            j = text.find('\n', i)
            if j < 0:
                j = n
            comments.append(text[i:j])
            yield ('#', text[i:j]); i = j
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tok = text[i:j]
            yield ('n' if NUM_RE.match(tok) else 'y', tok)
            i = j


def parse(text):
    stack = [[]]
    comments = []
    for kind, val in tokenize(text):
        if kind == '(':
            stack.append([])
        elif kind == ')':
            if len(stack) < 2:
                raise ParseError('unbalanced )')
            node = stack.pop()
            stack[-1].append(node)
        elif kind == '#':
            comments.append(val)
        else:
            stack[-1].append((kind, val))
    if len(stack) != 1:
        raise ParseError('unbalanced (')
    return stack[0], comments


def serialize(node, limit=None):
    if isinstance(node, tuple):
        k, v = node
        return '"%s"' % v if k == 's' else v
    s = '(' + ' '.join(serialize(x) for x in node) + ')'
    if limit and len(s) > limit:
        s = s[:limit] + '...'
    return s


def name_of(node):
    if isinstance(node, list) and node and isinstance(node[0], tuple) and node[0][0] == 'y':
        return node[0][1]
    return None


# ---------------------------------------------------------------- statistics
MAXV = 60          # distinct values kept per position
MAXEX = 3          # raw examples per key
MAXFILES = 3       # example files per key
LAYER_TOKENS = {'layer', 'layers', 'private_layers', 'zone_layer_connections'}


def new_node_stat():
    return {
        'count': 0,
        'files': set(),
        'arity': collections.Counter(),          # number of positional atoms before first sublist
        'positions': {},                          # pos -> {'kinds': Counter, 'values': Counter, 'distinct': set}
        'bare_syms': collections.Counter(),       # bare symbol atoms anywhere (any position)
        'bare_syms_after_list': collections.Counter(),  # bare symbols appearing after a sublist
        'children': collections.Counter(),
        'children_files': {},                     # child -> set(files)
        'examples': [],                           # [(sig, file, raw)]
        'example_sigs': set(),
    }


class Inventory:
    def __init__(self):
        self.nodes = {}           # key "parent/name" -> stat
        self.paths = collections.Counter()
        self.roots = collections.Counter()
        self.versions = collections.Counter()
        self.generators = collections.Counter()
        self.generator_versions = collections.Counter()
        self.layer_names = collections.defaultdict(collections.Counter)   # token -> Counter(name)
        self.layer_quoted = collections.Counter()   # (token, quoted?) -> count
        self.files = 0
        self.errors = []
        self.comment_files = 0
        self.file_flags = collections.defaultdict(set)   # flag -> set(files)
        self.num_total = 0
        self.num_decimals = collections.Counter()
        self.num_forms = collections.Counter()
        self.num_form_examples = {}
        self.str_total = 0
        self.str_forms = collections.Counter()
        self.str_form_examples = {}
        self.property_names = collections.Counter()
        self.first_child_order = collections.Counter()

    def stat(self, key):
        st = self.nodes.get(key)
        if st is None:
            st = self.nodes[key] = new_node_stat()
        return st

    def walk(self, node, parent, path, fname):
        name = name_of(node)
        if name is None:
            return
        key = parent + '/' + name
        st = self.stat(key)
        st['count'] += 1
        st['files'].add(fname)
        self.paths[path + '/' + name] += 1
        seen_list = False
        pos = 0
        sig = [name]
        for item in node[1:]:
            if isinstance(item, list):
                seen_list = True
                cname = name_of(item)
                st['children'][cname] += 1
                st['children_files'].setdefault(cname, set()).add(fname)
                sig.append('(' + str(cname) + ')')
                self.walk(item, name, path + '/' + name, fname)
            else:
                k, v = item
                self.atom_stats(k, v, name, fname)
                if not seen_list:
                    pos += 1
                p = pos if not seen_list else 'after'
                ps = st['positions'].get(p)
                if ps is None:
                    ps = st['positions'][p] = {'kinds': collections.Counter(), 'values': collections.Counter(), 'distinct': set()}
                ps['kinds'][k] += 1
                ps['distinct'].add(v)
                if k != 'n' and len(ps['values']) < MAXV or v in ps['values']:
                    ps['values'][v] += 1
                if k == 'y':
                    st['bare_syms'][v] += 1
                    if seen_list:
                        st['bare_syms_after_list'][v] += 1
                sig.append(k if k == 'n' else (k + ':' + v if k == 'y' else 's'))
        st['arity'][pos] += 1
        sigt = tuple(sig[:12])
        if sigt not in st['example_sigs'] and len(st['examples']) < MAXEX:
            st['example_sigs'].add(sigt)
            st['examples'].append((fname, serialize(node, 220)))
        # layer names
        if name in LAYER_TOKENS:
            for item in node[1:]:
                if isinstance(item, tuple) and item[0] != 'n':
                    self.layer_names[name][item[1]] += 1
                    self.layer_quoted[(name, item[0] == 's')] += 1
                elif isinstance(item, tuple) and name == 'layer':
                    self.layer_names[name][item[1]] += 1
        if parent == 'padstack' and name == 'layer' and len(node) > 1 and isinstance(node[1], tuple):
            self.layer_names['padstack/layer'][node[1][1]] += 1
        # flags
        self.flag(name, node, parent, fname)

    NUM_FORMS = [
        ('exponent', re.compile(r'[eE]')),
        ('leading_plus', re.compile(r'^\+')),
        ('leading_dot', re.compile(r'^[-+]?\.')),
        ('trailing_dot', re.compile(r'\.$')),
        ('negative_zero', re.compile(r'^-0(\.0*)?$')),
        ('trailing_zero_fraction', re.compile(r'\.\d*0$')),
        ('leading_zero_int', re.compile(r'^-?0\d')),
    ]

    def atom_stats(self, k, v, parent, fname):
        if k == 'n':
            self.num_total += 1
            if '.' in v:
                dec = len(v.split('.', 1)[1].split('e')[0].split('E')[0])
                self.num_decimals[dec] += 1
            else:
                self.num_decimals[0] += 1
            for form, rx in self.NUM_FORMS:
                if rx.search(v):
                    self.num_forms[form] += 1
                    ex = self.num_form_examples.setdefault(form, [])
                    if len(ex) < MAXEX:
                        ex.append({'file': fname, 'parent': parent, 'raw': v})
        elif k == 's':
            self.str_total += 1
            if v == '':
                self.str_forms['empty'] += 1
            if '\\' in v:
                for esc in re.findall(r'\\(.)', v):
                    key = 'escape_\\' + esc
                    self.str_forms[key] += 1
                    ex = self.str_form_examples.setdefault(key, [])
                    if len(ex) < MAXEX:
                        ex.append({'file': fname, 'parent': parent, 'raw': v[:120]})
            if any(ord(c) > 127 for c in v):
                self.str_forms['non_ascii'] += 1
                ex = self.str_form_examples.setdefault('non_ascii', [])
                if len(ex) < MAXEX:
                    ex.append({'file': fname, 'parent': parent, 'raw': v[:120]})
            if '\n' in v or '\t' in v:
                self.str_forms['raw_newline_or_tab'] += 1
        else:
            if re.match(r'^[-+]?\d', v):
                self.str_forms['bare_symbol_starting_with_digit'] += 1
                ex = self.str_form_examples.setdefault('bare_symbol_starting_with_digit', [])
                if len(ex) < MAXEX:
                    ex.append({'file': fname, 'parent': parent, 'raw': v[:120]})

    def flag(self, name, node, parent, fname):
        F = self.file_flags
        atoms = [x for x in node[1:] if isinstance(x, tuple)]
        lists = [x for x in node[1:] if isinstance(x, list)]
        cn = collections.Counter(name_of(x) for x in lists)
        if name == 'pad':
            if 'net' in cn: F['pad_with_net'].add(fname)
            if 'primitives' in cn: F['pad_custom_primitives'].add(fname)
            if 'chamfer' in cn: F['pad_chamfer'].add(fname)
            if 'chamfer_ratio' in cn: F['pad_chamfer_ratio'].add(fname)
            if 'options' in cn: F['pad_options'].add(fname)
            if 'padstack' in cn: F['pad_padstack'].add(fname)
            if 'tenting' in cn: F['pad_tenting'].add(fname)
            if 'teardrops' in cn: F['pad_teardrops'].add(fname)
            if 'property' in cn: F['pad_property'].add(fname)
            if 'rect_delta' in cn: F['pad_rect_delta'].add(fname)
            if 'roundrect_rratio' in cn: F['pad_roundrect_rratio'].add(fname)
            if 'die_length' in cn: F['pad_die_length'].add(fname)
            if 'pinfunction' in cn: F['pad_pinfunction'].add(fname)
            if 'pintype' in cn: F['pad_pintype'].add(fname)
            if 'zone_connect' in cn: F['pad_zone_connect'].add(fname)
            if 'clearance' in cn: F['pad_clearance'].add(fname)
            if 'solder_mask_margin' in cn: F['pad_solder_mask_margin'].add(fname)
            if 'solder_paste_margin' in cn: F['pad_solder_paste_margin'].add(fname)
            if 'solder_paste_margin_ratio' in cn: F['pad_solder_paste_margin_ratio'].add(fname)
            if 'thermal_bridge_width' in cn or 'thermal_width' in cn: F['pad_thermal_width'].add(fname)
            if 'thermal_bridge_angle' in cn: F['pad_thermal_bridge_angle'].add(fname)
            if 'thermal_gap' in cn: F['pad_thermal_gap'].add(fname)
            if 'remove_unused_layers' in cn: F['pad_remove_unused_layers'].add(fname)
            if 'keep_end_layers' in cn: F['pad_keep_end_layers'].add(fname)
            if 'zone_layer_connections' in cn: F['pad_zone_layer_connections'].add(fname)
            if 'tstamp' in cn: F['pad_tstamp'].add(fname)
            if 'uuid' in cn: F['pad_uuid'].add(fname)
            if any(a[0] == 'y' and a[1] == 'locked' for a in atoms): F['pad_bare_locked'].add(fname)
            if 'locked' in cn: F['pad_list_locked'].add(fname)
            if len(atoms) >= 3:
                F['pad_type_' + atoms[1][1]].add(fname)
                F['pad_shape_' + atoms[2][1]].add(fname)
                F['pad_number_' + ('quoted' if atoms[0][0] == 's' else 'bare')].add(fname)
                if atoms[0][1] == '': F['pad_number_empty'].add(fname)
            at = [x for x in lists if name_of(x) == 'at']
            if at and len(at[0]) >= 4: F['pad_at_with_angle'].add(fname)
        elif name == 'drill' and parent == 'pad':
            if any(a[0] == 'y' and a[1] == 'oval' for a in atoms): F['drill_oval'].add(fname)
            if 'offset' in cn: F['drill_offset'].add(fname)
            if len([a for a in atoms if a[0] == 'n']) == 0: F['drill_no_size'].add(fname)
        elif name in ('footprint', 'module'):
            F['root_' + name].add(fname)
            for c in cn:
                F['fp_child_' + str(c)].add(fname)
            for a in atoms[1:]:          # atoms[0] is the footprint name
                if a[0] == 'y':
                    F['fp_bare_' + a[1]].add(fname)
            if atoms and atoms[0][0] == 'y': F['fp_name_bare'].add(fname)
            if atoms and atoms[0][0] == 's': F['fp_name_quoted'].add(fname)
            if not lists or 'version' not in cn: F['fp_no_version'].add(fname)
        elif name == 'property' and parent in ('footprint', 'module'):
            if atoms:
                self.property_names[('"%s"' if atoms[0][0] == 's' else '%s') % atoms[0][1]] += 1
            if lists: F['property_with_effects'].add(fname)
            else: F['property_bare'].add(fname)
            if atoms and atoms[0][1].startswith('ki_'): F['property_ki_' + atoms[0][1][3:]].add(fname)
            if atoms and atoms[0][1] in ('Reference', 'Value', 'Footprint', 'Datasheet', 'Description'):
                F['property_' + atoms[0][1]].add(fname)
            elif atoms and not atoms[0][1].startswith('ki_'):
                F['property_user'].add(fname)
        elif name == 'fp_text':
            if atoms: F['fp_text_' + atoms[0][1]].add(fname)
            if any(a[0] == 'y' and a[1] == 'hide' for a in atoms): F['fp_text_bare_hide'].add(fname)
            if any(a[0] == 'y' and a[1] == 'locked' for a in atoms): F['fp_text_bare_locked'].add(fname)
            if 'hide' in cn: F['fp_text_list_hide'].add(fname)
            if 'unlocked' in cn: F['fp_text_list_unlocked'].add(fname)
            if 'locked' in cn: F['fp_text_list_locked'].add(fname)
            at = [x for x in lists if name_of(x) == 'at']
            if at:
                aa = [x for x in at[0][1:] if isinstance(x, tuple)]
                if any(x[0] == 'y' and x[1] == 'unlocked' for x in aa): F['fp_text_at_unlocked'].add(fname)
                if len([x for x in aa if x[0] == 'n']) >= 3: F['fp_text_at_angle'].add(fname)
        elif name == 'at' and parent in ('footprint', 'module'):
            if len([x for x in atoms if x[0] == 'n']) >= 3: F['fp_at_angle'].add(fname)
        elif name == 'at' and parent == 'property':
            if any(x[0] == 'y' and x[1] == 'unlocked' for x in atoms): F['property_at_unlocked'].add(fname)
        elif name == 'effects':
            if any(a[0] == 'y' and a[1] == 'hide' for a in atoms): F['effects_bare_hide'].add(fname)
            if 'hide' in cn: F['effects_list_hide'].add(fname)
        elif name == 'font':
            for c in cn: F['font_' + str(c)].add(fname)
            for a in atoms:
                if a[0] == 'y': F['font_bare_' + a[1]].add(fname)
        elif name == 'justify':
            F['justify_' + '_'.join(sorted(a[1] for a in atoms))].add(fname)
        elif name == 'fill':
            if atoms: F['fill_' + atoms[0][1]].add(fname)
            for c in cn: F['fill_list_' + str(c)].add(fname)
        elif name == 'stroke':
            t = [x for x in lists if name_of(x) == 'type']
            if t and len(t[0]) > 1: F['stroke_type_' + t[0][1][1]].add(fname)
        elif name == 'width' and parent.startswith('fp_'):
            F['shape_legacy_width'].add(fname)
        elif name == 'angle' and parent == 'fp_arc':
            F['fp_arc_legacy_angle'].add(fname)
        elif name == 'mid' and parent == 'fp_arc':
            F['fp_arc_mid'].add(fname)
        elif name == 'pts':
            if 'arc' in cn: F['pts_with_arc'].add(fname)
        elif name == 'layer' and parent in ('fp_line', 'fp_rect', 'fp_circle', 'fp_arc', 'fp_poly', 'fp_curve', 'fp_text', 'property'):
            if any(a[0] == 'y' and a[1] == 'knockout' for a in atoms): F['layer_knockout'].add(fname)
        elif name == 'attr':
            F['attr_' + '_'.join(a[1] for a in atoms)].add(fname)
            for a in atoms: F['attr_flag_' + a[1]].add(fname)
        elif name == 'model':
            for c in cn: F['model_' + str(c)].add(fname)
            for a in atoms[1:]:
                if a[0] == 'y': F['model_bare_' + a[1]].add(fname)
            if atoms and atoms[0][0] == 'y': F['model_path_bare'].add(fname)
        elif name in ('zone', 'group', 'dimension', 'fp_text_box', 'image', 'table', 'point', 'embedded_files',
                      'teardrops', 'padstack', 'tenting', 'net_tie_pad_groups', 'private_layers', 'component_classes',
                      'jumper_pad_groups', 'duplicate_pad_numbers_are_jumpers', 'render_cache', 'fp_curve', 'fp_rect',
                      'fp_poly', 'fp_arc', 'fp_circle', 'sheetname', 'sheetfile', 'path', 'tedit', 'tstamp', 'uuid',
                      'autoplace_cost90', 'autoplace_cost180', 'solder_paste_ratio', 'solder_paste_margin_ratio',
                      'solder_mask_margin', 'solder_paste_margin', 'clearance', 'zone_connect', 'thermal_width',
                      'thermal_gap', 'embedded_fonts', 'locked', 'placed', 'generator_version', 'descr', 'tags',
                      'net', 'stackup', 'transform', 'units', 'variant', 'custom_property', 'barcode', 'constraint'):
            F[parent + '/' + name].add(fname)
        if name == 'layers':
            for a in atoms:
                if a[1] in ('*.Cu', 'F&B.Cu', '*In.Cu', '*.Mask', '*.Paste', '*.SilkS', '*.Adhes', '*.Fab', '*.CrtYd'):
                    F['layers_wildcard_' + a[1]].add(fname)
            F['layers_' + ('quoted' if atoms and atoms[0][0] == 's' else 'bare')].add(fname)
        if name == 'layer' and atoms:
            F['layer_' + ('quoted' if atoms[0][0] == 's' else 'bare')].add(fname)
            if atoms[0][1] in ('B.Cu', 'B.SilkS', 'B.Fab', 'B.CrtYd', 'B.Mask', 'B.Paste') and parent in ('footprint', 'module'):
                F['fp_layer_back'].add(fname)

    def add_file(self, path, shortname):
        self.files += 1
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            tree, comments = parse(text)
        except Exception as e:
            self.errors.append((shortname, str(e)))
            return
        if comments:
            self.comment_files += 1
            self.file_flags['leading_comments'].add(shortname)
        if len(tree) != 1:
            self.errors.append((shortname, 'top-level node count %d' % len(tree)))
        for root in tree:
            rn = name_of(root)
            self.roots[rn] += 1
            self.walk(root, '<root>', '', shortname)
            seq = []
            for item in root[1:]:
                if isinstance(item, list):
                    n = name_of(item)
                    if not seq or seq[-1] != n:
                        seq.append(n)
                    if n == 'version' and len(item) > 1:
                        self.versions[item[1][1]] += 1
                    elif n == 'generator' and len(item) > 1:
                        self.generators[serialize(item[1])] += 1
                    elif n == 'generator_version' and len(item) > 1:
                        self.generator_versions[serialize(item[1])] += 1
            self.first_child_order[' '.join(str(x) for x in seq)] += 1

    def to_json(self):
        nodes = {}
        for key, st in sorted(self.nodes.items()):
            positions = {}
            for p, ps in st['positions'].items():
                positions[str(p)] = {
                    'kinds': dict(ps['kinds']),
                    'distinct': len(ps['distinct']),
                    'values': dict(ps['values'].most_common(MAXV)),
                }
            nodes[key] = {
                'count': st['count'],
                'files': len(st['files']),
                'arity': {str(k): v for k, v in sorted(st['arity'].items())},
                'positions': positions,
                'bare_symbols': dict(st['bare_syms'].most_common(MAXV)),
                'bare_symbols_after_sublist': dict(st['bare_syms_after_list'].most_common(MAXV)),
                'children': {c: {'count': n, 'files': len(st['children_files'][c])} for c, n in st['children'].most_common()},
                'examples': [{'file': f, 'raw': r} for f, r in st['examples']],
                'example_files': sorted(st['files'])[:MAXFILES],
            }
        return {
            'files': self.files,
            'parse_errors': self.errors,
            'files_with_leading_comments': self.comment_files,
            'roots': dict(self.roots),
            'versions': dict(self.versions.most_common()),
            'generators': dict(self.generators.most_common()),
            'generator_versions': dict(self.generator_versions.most_common()),
            'layer_names': {t: dict(c.most_common()) for t, c in self.layer_names.items()},
            'layer_quoting': {t + ('_quoted' if q else '_bare'): n for (t, q), n in self.layer_quoted.items()},
            'paths': dict(self.paths.most_common()),
            'nodes': nodes,
            'flags': {k: {'files': len(v), 'examples': sorted(v)[:MAXFILES]} for k, v in sorted(self.file_flags.items())},
            'property_names': dict(self.property_names.most_common()),
            'footprint_child_sequences': dict(self.first_child_order.most_common(20)),
            'numbers': {'total': self.num_total,
                        'decimals': {str(k): v for k, v in sorted(self.num_decimals.items())},
                        'forms': dict(self.num_forms), 'form_examples': self.num_form_examples},
            'strings': {'total': self.str_total, 'forms': dict(self.str_forms),
                        'form_examples': self.str_form_examples},
        }


def run(label, d):
    inv = Inventory()
    for root, dirs, files in os.walk(d):
        dirs.sort()
        for fn in sorted(files):
            if fn.endswith('.kicad_mod'):
                p = os.path.join(root, fn)
                inv.add_file(p, os.path.relpath(p, d))
    return inv


def main():
    out = sys.argv[1]
    result = {}
    for arg in sys.argv[2:]:
        label, d = arg.split('=', 1)
        inv = run(label, d)
        result[label] = inv.to_json()
        print('%s: %d files, %d errors, %d node keys' % (label, inv.files, len(inv.errors), len(inv.nodes)), file=sys.stderr)
    with open(out, 'w') as f:
        json.dump(result, f, indent=1, ensure_ascii=False, sort_keys=False)


if __name__ == '__main__':
    main()
