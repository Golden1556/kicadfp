"""Минимальный эмулятор sscanf(3) для форматов, которые встречаются в
загрузчиках EESchema: %d, %c, %s, %X/%lX, %[^"], пробелы и литералы.

Возвращает (values, count) — как C: количество успешно выполненных
преобразований; разбор останавливается на первом несовпадении.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_WS = ' \t\n\r\f\v'
_INT = re.compile(r'[+-]?\d+')
_HEX = re.compile(r'(?:0[xX])?[0-9a-fA-F]+')


def sscanf(src: str, fmt: str) -> Tuple[List[Any], int]:
    vals: List[Any] = []
    i = 0          # позиция в src
    j = 0          # позиция в fmt
    n = len(src)
    m = len(fmt)

    def skip_ws():
        nonlocal i
        while i < n and src[i] in _WS:
            i += 1

    while j < m:
        fc = fmt[j]
        if fc in _WS:
            skip_ws()
            j += 1
            continue
        if fc != '%':
            if i < n and src[i] == fc:
                i += 1
                j += 1
                continue
            return vals, len(vals)
        # директива
        j += 1
        # модификатор длины (l, ll, h) — игнорируем
        while j < m and fmt[j] in 'lh':
            j += 1
        if j >= m:
            raise ValueError('bad format')
        conv = fmt[j]
        j += 1
        if conv == 'd':
            skip_ws()
            mt = _INT.match(src, i)
            if not mt:
                return vals, len(vals)
            vals.append(int(mt.group()))
            i = mt.end()
        elif conv in 'Xx':
            skip_ws()
            mt = _HEX.match(src, i)
            if not mt:
                return vals, len(vals)
            vals.append(int(mt.group(), 16))
            i = mt.end()
        elif conv == 'c':
            if i >= n:
                return vals, len(vals)
            vals.append(src[i])
            i += 1
        elif conv == 's':
            skip_ws()
            start = i
            while i < n and src[i] not in _WS:
                i += 1
            if i == start:
                return vals, len(vals)
            vals.append(src[start:i])
        elif conv == '[':
            # только вид %[^X]
            end = fmt.index(']', j)
            spec = fmt[j:end]
            j = end + 1
            if not spec.startswith('^'):
                raise ValueError('only negated scansets are supported')
            stop = spec[1:]
            start = i
            while i < n and src[i] not in stop:
                i += 1
            if i == start:
                return vals, len(vals)
            vals.append(src[start:i])
        else:
            raise ValueError('unsupported conversion %%%s' % conv)
    return vals, len(vals)
