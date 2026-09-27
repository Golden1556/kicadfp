"""Генератор библиотеки посадочных мест для ЛР2 (ТЗ §3.2): dip14, mlt, snp8.

Запуск: `python3 -m kicadgen.gen_footprints` из корня kicad-2011-gen — пишет
examples/346_8/My_lib.mod (CRLF), перечитывает его строгим read_modlib и
печатает таблицу площадок каждого посадочного места.
"""

from __future__ import annotations

import os

from .mod import ModLibrary, dip, two_pad, pin_rows, save_modlib, load_modlib, pcb_to_mm


def build_lab2_library() -> ModLibrary:
    """dip14 (К555ТВ6), mlt (резистор), snp8 (разъём) — со значениями по
    умолчанию из ТЗ §3.2.1-3.2.3 (это же и значения по умолчанию у dip/
    two_pad/pin_rows)."""
    lib = ModLibrary()
    lib.add(dip(name='dip14'))
    lib.add(two_pad(name='mlt'))
    lib.add(pin_rows(name='snp8'))
    return lib


def _print_pad_table(lib: ModLibrary) -> None:
    for fp in lib.footprints:
        print('%s:' % fp.name)
        for p in fp.pads:
            print('  pad=%-4r shape=%s x=%7.3fmm y=%7.3fmm size=%.3fx%.3fmm '
                  'drill=%.3fmm attr=%s' % (
                      p.number, p.shape,
                      pcb_to_mm(p.x), pcb_to_mm(p.y),
                      pcb_to_mm(p.size_x), pcb_to_mm(p.size_y),
                      pcb_to_mm(p.drill), p.attribute))


if __name__ == '__main__':
    out_dir = os.path.join(os.path.dirname(__file__), os.pardir, 'examples', '346_8')
    out_path = os.path.join(out_dir, 'My_lib.mod')

    library = build_lab2_library()
    save_modlib(library, out_path, crlf=True)
    print('wrote %s' % os.path.abspath(out_path))

    reread = load_modlib(out_path)
    print('reread %d footprints: %s' % (
        len(reread.footprints), ', '.join(f.name for f in reread.footprints)))
    _print_pad_table(reread)
