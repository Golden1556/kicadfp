#!/usr/bin/env python3
"""
1:1 port of KICAD_FORMAT::Prettify (common/io/kicad/kicad_io_utils.cpp) plus a minimal
S-expression tokenizer / one-line serializer and a byte-for-byte round-trip checker.

Ported versions (argument `mode`):
  "8.0"    - KiCad 8.0.x  : Prettify( std::string&, char aQuoteChar = '"' )   8.0/kicad_io_utils.cpp:65
  "9.0"    - KiCad 9.0.x  : Prettify( std::string&, bool aCompactSave )        9.0/kicad_io_utils.cpp:89
  "master" - KiCad 10-dev : Prettify( std::string&, FORMAT_MODE aMode )        master/kicad_io_utils.cpp:111

The C++ code works on std::string, i.e. on BYTES (UTF-8 encoded). `column` counts bytes, so
the algorithm is run on a latin-1 decoded str (1 char == 1 byte) and re-encoded as latin-1.

Usage (round-trip check: parse -> one-line -> prettify -> compare with the original bytes):
    python prettify.py [--mode=8.0|9.0|master] <dir-or-file> ...
"""
from __future__ import annotations

import collections
import glob
import os
import sys
from dataclasses import dataclass
from typing import List, Union

# ----------------------------------------------------------------------------------------------
# Minimal S-expression model: atoms are kept VERBATIM (quoted atoms keep quotes and escapes)
# ----------------------------------------------------------------------------------------------

Atom = str
Node = Union[Atom, List["Node"]]


def tokenize(src: str) -> Node:
    """Parse one top-level list. Atoms are kept verbatim (no unescaping)."""
    i, n = 0, len(src)
    stack: List[list] = []
    root = None
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            lst: list = []
            if stack:
                stack[-1].append(lst)
            stack.append(lst)
            i += 1
        elif c == ")":
            lst = stack.pop()
            if not stack:
                root = lst
            i += 1
        elif c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    break
                j += 1
            stack[-1].append(src[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and src[j] not in " \t\r\n()":
                j += 1
            stack[-1].append(src[i:j])
            i = j
    if root is None:
        raise ValueError("no complete top-level list")
    return root


def serialize_oneline(node: Node) -> str:
    """Pre-Prettify serialization: '(' + head; every ATOM (except the first item) is preceded
    by exactly one ' '; a sub-list is preceded by nothing; ')' closes.  Equivalent to what the
    KiCad 9 writer emits (m_out->Print("(tok %s)") calls simply concatenated)."""
    if isinstance(node, str):
        return node
    out = ["("]
    first = True
    for ch in node:
        if isinstance(ch, str):
            if not first:
                out.append(" ")
            out.append(ch)
        else:
            out.append(serialize_oneline(ch))
        first = False
    out.append(")")
    return "".join(out)


def serialize_spaced(node: Node) -> str:
    """Deliberately 'dirty' serialization (extra spaces / tabs / newlines everywhere) used only
    to prove that Prettify's output does not depend on input whitespace.
    NB: '(' must stay glued to the head atom and the head must be followed by a plain ' ',
    because isXY() tests the literal bytes "xy " after '(' and isShortForm() reads the token
    right after '('."""
    if isinstance(node, str):
        return node
    return "(" + "  \n\t ".join(serialize_spaced(ch) for ch in node) + " )"


# ----------------------------------------------------------------------------------------------
# Prettify
# ----------------------------------------------------------------------------------------------

WS = " \t\n\r"      # isWhitespace(): ' ', '\t', '\n', '\r'


def prettify(source: str, mode: str = "9.0", compact_save: bool = False,
             format_mode: str = "NORMAL", final_newline: bool = True,
             xy_limit: int = 99) -> str:
    """source        : raw writer output, str with 1 char == 1 byte (latin-1 view of UTF-8)
    mode          : "8.0" | "9.0" | "master"
    compact_save  : 9.0 only - ADVANCED_CFG::m_CompactSave (default false)
    format_mode   : master only - "NORMAL" | "COMPACT_TEXT_PROPERTIES" | "LIBRARY_TABLE"
                    (master's PRETTIFIED_FILE_OUTPUTFORMATTER turns NORMAL into
                    COMPACT_TEXT_PROPERTIES when m_CompactSave is set; richio.cpp:702)
    final_newline : False reproduces KiCad 8.0.0 / 8.0.1 (the trailing '\n' was added in 8.0.2)
    xy_limit      : 99 in KiCad. 0 emulates the kicad-footprint-generator style
                    (every (xy ...) on its own line) - NOT a KiCad behaviour.
    """
    quote_char = '"'
    indent_char = "\t"
    indent_size = 1
    xy_special_case_column_limit = xy_limit
    consecutive_token_wrap_threshold = 72

    if mode == "master":
        text_special_case = format_mode == "COMPACT_TEXT_PROPERTIES"
        lib_special_case = format_mode == "LIBRARY_TABLE"
        short_form_tokens = {"font", "stroke", "fill", "teardrop", "offset", "rotate", "scale"}
    elif mode == "9.0":
        text_special_case = compact_save
        lib_special_case = False
        short_form_tokens = {"font", "stroke", "fill", "offset", "rotate", "scale"}
    elif mode == "8.0":
        text_special_case = False
        lib_special_case = False
        short_form_tokens = set()
    else:
        raise ValueError(mode)

    out: List[str] = []
    n = len(source)

    list_depth = 0
    lib_depth = 0
    last_non_whitespace = "\0"
    in_quote = False
    has_inserted_space = False
    in_multi_line_list = False
    in_xy = False
    in_short_form = False
    in_lib_row = False
    short_form_depth = 0
    column = 0
    backslash_count = 0

    def next_non_whitespace(i: int) -> str:
        while i < n and source[i] in WS:
            i += 1
        return source[i] if i < n else "\0"

    def is_xy(i: int) -> bool:                       # literally "xy " after '('
        return source[i + 1:i + 4] == "xy "

    def alpha_token(i: int) -> str:                  # isalpha() run right after '('
        j = i + 1
        while j < n and source[j].isascii() and source[j].isalpha():
            j += 1
        return source[i + 1:j]

    def indent(depth: int) -> str:
        return indent_char * (depth * indent_size)

    for i in range(n):
        c = source[i]
        nxt = next_non_whitespace(i)

        if c in WS and not in_quote:
            if (not has_inserted_space              # Only permit one space between chars
                    and list_depth > 0              # Do not permit spaces in outer list
                    and last_non_whitespace != "("  # Remove extra space after start of list
                    and nxt != ")"                  # Remove extra space before end of list
                    and nxt != "("):                # Remove extra space before newline
                if in_xy or column < consecutive_token_wrap_threshold:
                    out.append(" ")
                    column += 1
                elif in_short_form or in_lib_row:   # (9.0: inShortForm only; 8.0: absent)
                    out.append(" ")                 # NB: column NOT incremented (sic)
                else:
                    out.append("\n" + indent(list_depth))
                    column = list_depth * indent_size
                    in_multi_line_list = True
                has_inserted_space = True
        else:
            has_inserted_space = False

            if c == "(" and not in_quote:
                current_is_xy = is_xy(i)
                current_is_short_form = text_special_case and alpha_token(i) in short_form_tokens
                current_is_lib = lib_special_case and alpha_token(i) == "lib"

                # 8.0: `if( listDepth == 0 )`, 9.0/master: `if( formatted.empty() )`
                first = (list_depth == 0) if mode == "8.0" else (not out)
                if first:
                    out.append("(")
                    column += 1
                elif in_xy and current_is_xy and column < xy_special_case_column_limit:
                    out.append(" (")                # List-of-points special case
                    column += 2
                elif in_short_form or in_lib_row:
                    out.append(" (")
                    column += 2
                else:
                    out.append("\n" + indent(list_depth) + "(")
                    column = list_depth * indent_size + 1

                in_xy = current_is_xy

                if current_is_short_form:
                    in_short_form = True
                    short_form_depth = list_depth
                elif current_is_lib:
                    in_lib_row = True
                    lib_depth = list_depth

                list_depth += 1

            elif c == ")" and not in_quote:
                if list_depth > 0:
                    list_depth -= 1

                if in_short_form:
                    out.append(")")
                    column += 1
                elif in_lib_row and list_depth == lib_depth:
                    out.append(")")                 # NB: column NOT incremented (sic)
                    in_lib_row = False
                elif last_non_whitespace == ")" or in_multi_line_list:
                    out.append("\n" + indent(list_depth) + ")")
                    column = list_depth * indent_size + 1
                    in_multi_line_list = False
                else:
                    out.append(")")
                    column += 1

                if short_form_depth == list_depth:  # (absent in 8.0; harmless there)
                    in_short_form = False
                    short_form_depth = 0

            else:
                # The output formatter escapes double-quotes (like \")
                # But a corner case is a sequence like \\"
                # therefore a '\' is attached to a '"' if a odd number of '\' is detected
                if c == "\\":
                    backslash_count += 1
                elif c == quote_char and (backslash_count & 1) == 0:
                    in_quote = not in_quote

                if c != "\\":
                    backslash_count = 0

                out.append(c)
                column += 1

            last_non_whitespace = c

    # newline required at end of line / file for POSIX compliance. Keeps git diffs clean.
    if final_newline:
        out.append("\n")
    return "".join(out)


def prettify_bytes(raw: bytes, **kw) -> bytes:
    return prettify(raw.decode("latin-1"), **kw).encode("latin-1")


def format_tree(tree: Node, **kw) -> bytes:
    """What a KiCad 8/9/10 writer would put on disk for `tree` (atoms given verbatim)."""
    return prettify_bytes(serialize_oneline(tree).encode("latin-1"), **kw)


# ----------------------------------------------------------------------------------------------
# Round-trip checker
# ----------------------------------------------------------------------------------------------

@dataclass
class Result:
    path: str
    cls: str            # exact | exact-no-final-nl | generator-xy-per-line | other
    first_diff: str


def first_difference(a: bytes, b: bytes) -> str:
    if a == b:
        return ""
    m = min(len(a), len(b))
    k = 0
    while k < m and a[k] == b[k]:
        k += 1
    line = a.count(b"\n", 0, k) + 1
    ls = a.rfind(b"\n", 0, k) + 1
    ea = a.find(b"\n", k)
    eb = b.find(b"\n", k)
    ctx_a = a[ls:ea if ea != -1 else len(a)]
    ctx_b = b[ls:eb if eb != -1 else len(b)]
    return f"line {line} off {k}: orig={ctx_a[:120]!r} ours={ctx_b[:120]!r}"


def check_file(path: str, mode: str) -> Result:
    raw = open(path, "rb").read()
    tree = tokenize(raw.decode("latin-1"))
    out = format_tree(tree, mode=mode)
    # invariance: dirty input whitespace must give identical output
    out2 = prettify_bytes(serialize_spaced(tree).encode("latin-1"), mode=mode)
    assert out == out2, f"whitespace-invariance violated: {path}"
    if out == raw:
        return Result(path, "exact", "")
    if format_tree(tree, mode=mode, final_newline=False) == raw:
        return Result(path, "exact-no-final-nl", "")
    if format_tree(tree, mode=mode, xy_limit=0) == raw:
        return Result(path, "generator-xy-per-line", "")
    return Result(path, "other", first_difference(raw, out))


def _worker(args):
    return check_file(*args)


def main(argv):
    from multiprocessing import Pool
    mode = "9.0"
    paths = []
    for a in argv:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif os.path.isdir(a):
            paths += sorted(glob.glob(os.path.join(a, "**", "*.kicad_mod"), recursive=True))
        else:
            paths.append(a)
    with Pool() as pool:
        results = pool.map(_worker, [(p, mode) for p in paths], chunksize=16)
    c = collections.Counter(r.cls for r in results)
    print(f"mode={mode} files={len(results)} " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))
    for r in [r for r in results if r.cls == "other"][:25]:
        print("  DIFF", r.path, "::", r.first_diff)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
