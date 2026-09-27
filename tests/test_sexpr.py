"""Тесты модуля kicadfp.sexpr: разбор, атомы, узлы, числа, строки, форматирование."""

import pytest

from kicadfp import sexpr
from kicadfp.sexpr import (
    Node,
    SexprSyntaxError,
    Str,
    Sym,
    diff,
    dumps,
    equal,
    format_number,
    parse,
    parse_all,
    prettify,
    quote,
    to_compact,
    unquote,
)

# ---------------------------------------------------------------------------
# Разбор
# ---------------------------------------------------------------------------


def test_parse_basic_atoms():
    n = parse('(pad "1" thru_hole rect (at 0 -1.5 90) (size 1.6 1.6))')
    assert n.name == "pad"
    assert n.atoms() == [Str("1"), Sym("thru_hole"), Sym("rect")]
    assert isinstance(n.atoms()[0], Str) and isinstance(n.atoms()[1], Sym)
    assert [c.name for c in n.nodes()] == ["at", "size"]
    assert n.find("at").atoms() == ["0", "-1.5", "90"]
    assert n.number("at", 1) == -1.5
    assert n.numbers("size") == [1.6, 1.6]
    assert n.value("size", 0) == "1.6" and isinstance(n.value("size", 0), Sym)
    assert n.value("nope", 0, default="x") == "x"
    assert n.number("nope") is None


def test_parse_positions_and_bom_crlf():
    text = "﻿(footprint \"X\"\r\n  (layer \"F.Cu\")\r\n  (pad \"1\" smd rect))\r\n"
    n = parse(text)
    assert n.line == 1 and n.col == 1
    assert n.find("layer").line == 2 and n.find("layer").col == 3
    assert n.find("pad").line == 3


def test_parse_comments_before_root_are_kept():
    text = "# comment one\n#second\n(footprint \"A\" (layer \"F.Cu\"))\n"
    n = parse(text)
    assert n.comments == ["# comment one", "#second"]
    assert dumps(n).startswith("# comment one\n#second\n(footprint")
    # решётка внутри строки или не в начале строки — обычный символ
    n2 = parse('(a "#x" b#c)')
    assert n2.atoms() == ["#x", "b#c"]


def test_parse_strings_escapes_roundtrip():
    samples = ['', 'plain', 'with space', 'quote"inside', 'back\\slash', 'new\nline', 'tab\tx',
               'юникод — текст', '${REFERENCE}', 'a(b)c', 'ends with backslash\\', 'cr\rx']
    for s in samples:
        q = quote(s)
        assert unquote(q) == s, s
        n = parse(f"(t {q})")
        assert n.atoms()[0] == s
        assert isinstance(n.atoms()[0], Str)
        assert to_compact(n) == f"(t {q})"


def test_unquote_kicad_escapes():
    assert unquote(r'"a\nb"') == "a\nb"
    assert unquote(r'"\x41\x42"') == "AB"
    assert unquote(r'"\101"') == "A"
    assert unquote(r'"\t\a\b\f\v\r"') == "\t\x07\x08\x0c\x0b\r"
    assert unquote(r'"\xZZ"') == "xZZ"  # «испорченный» hex — как в KiCad
    assert unquote(r'"\q"') == "\\q"  # неизвестная последовательность — обратная косая


def test_quote_only_escapes_four_chars():
    assert quote('a"b') == '"a\\"b"'
    assert quote("a\\b") == '"a\\\\b"'
    assert quote("a\nb\rc") == '"a\\nb\\rc"'
    assert quote("tab\there") == '"tab\there"'
    assert quote("") == '""'


@pytest.mark.parametrize(
    "text, line, col, fragment",
    [
        ("", 1, 1, "пустой"),
        ("   \n\n  ", 1, 1, "пустой"),
        ("(footprint \"X\"\n  (layer \"F.Cu\")\n", 3, 1, "незакрытая скобка"),
        ("(a (b)) )", 1, 9, "лишняя закрывающая"),
        ('(a "unterminated)', 1, 4, "незакрытая строка"),
        ('(a "multi\nline")', 1, 4, "незакрытая строка"),
        ("(a) (b)", 1, 5, "лишние данные"),
        ("(a) x", 1, 5, "вне корневого"),
        ("x (a)", 1, 1, "вне корневого"),
        ("( )", 1, 3, "имя узла"),
        ('("a" 1)', 1, 2, "имя узла"),
    ],
)
def test_parse_errors_have_positions(text, line, col, fragment):
    with pytest.raises(SexprSyntaxError) as ei:
        parse(text)
    e = ei.value
    assert e.line == line, str(e)
    assert e.col == col, str(e)
    assert fragment in e.msg
    assert str(e).startswith(f"строка {line}, позиция {col}: ")


def test_unclosed_paren_reports_open_node():
    with pytest.raises(SexprSyntaxError) as ei:
        parse('(footprint "X"\n  (pad "1" smd rect\n  (layer "F.Cu")\n')
    assert "pad" in ei.value.msg and "строке 2" in ei.value.msg
    assert ei.value.line == 4


def test_parse_all_multiple_roots():
    roots = parse_all("(a 1)\n(b 2)\n")
    assert [r.name for r in roots] == ["a", "b"]
    assert parse_all("") == []


# ---------------------------------------------------------------------------
# Node API
# ---------------------------------------------------------------------------


def test_node_set_replace_and_insert_with_order():
    n = parse("(pad \"1\" smd rect (at 0 0) (size 1 1) (layers \"F.Cu\") (uuid \"u\"))")
    order = ["at", "size", "drill", "layers", "roundrect_rratio", "net", "uuid"]
    # замена существующего
    n.set("size", 2.5, 1.25)
    assert to_compact(n.find("size")) == "(size 2.5 1.25)"
    # вставка нового по таблице порядка
    n.set("drill", 0.8, order=order)
    n.set("roundrect_rratio", 0.25, order=order)
    n.set("net", 1, "GND", order=order)
    assert [c.name for c in n.nodes()] == ["at", "size", "drill", "layers", "roundrect_rratio", "net", "uuid"]
    assert to_compact(n.find("net")) == '(net 1 "GND")'
    # подузлы сохраняются при замене атомов
    d = n.find("drill")
    d.append(Node("offset", [0.1, 0.2]))
    n.set("drill", Sym("oval"), 0.8, 1.2)
    assert to_compact(d) == "(drill oval 0.8 1.2(offset 0.1 0.2))"
    # без таблицы — в конец
    n.set("zzz", True)
    assert n.items[-1].name == "zzz" and n.items[-1].atoms() == ["yes"]


def test_node_insert_without_predecessors():
    n = parse('(footprint "X" (layer "F.Cu") (pad "1" smd rect))')
    order = ["version", "generator", "layer", "descr", "pad"]
    n.set("version", 20241229, order=order)
    n.set("descr", "text", order=order)
    assert [c.name for c in n.nodes()] == ["version", "layer", "descr", "pad"]
    assert n.items[0] == Str("X")  # атом имени остаётся первым


def test_node_flags_and_atoms():
    n = parse('(fp_text reference "REF**" (at 0 0) hide (layer "F.SilkS"))')
    assert n.has_flag("hide")
    n.set_flag("hide", False)
    assert not n.has_flag("hide")
    assert to_compact(n) == '(fp_text reference "REF**"(at 0 0)(layer "F.SilkS"))'
    n.set_flag("hide", True)
    # ставится после последнего атома
    assert to_compact(n) == '(fp_text reference "REF**" hide(at 0 0)(layer "F.SilkS"))'
    n.set_atom(1, "NEW")
    assert n.atom(1) == "NEW" and isinstance(n.atom(1), Str)
    n.set_atom(5, Sym("extra"))
    assert n.atoms()[-1] == "extra"
    assert n.atom(99) is None and n.atom(99, "d") == "d"


def test_node_remove_replace_copy_index():
    n = parse("(a (b 1) (c 2) (b 3) x)")
    assert n.remove("b") is True
    assert n.remove("b") is False
    assert [c.name for c in n.nodes()] == ["c"]
    c = n.find("c")
    n.replace_child(c, Node("d", [4]))
    assert to_compact(n) == "(a(d 4) x)"
    d = n.find("d")
    assert n.index(d) == 0
    n.remove_child(d)
    assert to_compact(n) == "(a x)"
    with pytest.raises(ValueError):
        n.index(d)
    m = parse("(a (b 1))")
    m.comments = ["#c"]
    k = m.copy()
    assert equal(m, k) and k.find("b") is not m.find("b") and k.comments == ["#c"]
    assert k.line == 0


def test_coerce_types():
    n = Node("t", [1, 2.5, True, False, "s", Sym("y"), -0.0, 0.1 + 0.2])
    assert to_compact(n) == '(t 1 2.5 yes no "s" y 0 0.3)'
    with pytest.raises(TypeError):
        Node("t", [object()])
    assert len(n) == 8 and list(iter(n)) == n.items
    assert repr(n).startswith("Node<(t 1 2.5")


# ---------------------------------------------------------------------------
# Числа
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.15, "0.15"), (1.6, "1.6"), (3.81, "3.81"), (0.000001, "0.000001"),
        (12.3456789, "12.345679"), (-0.05, "-0.05"), (1e-5, "0.00001"), (100, "100"),
        (0.1 + 0.2, "0.3"), (0.0001, "0.0001"), (0.00015, "0.00015"), (1234567.891, "1234567.891"),
        (1e-7, "0"), (2.5e-5, "0.000025"), (1 / 3, "0.333333"), (-0.0, "0"), (0, "0"),
        (2.0, "2"), (-180.0, "-180"), (1e10, "10000000000"), (7.62, "7.62"), (0.5, "0.5"),
    ],
)
def test_format_number(value, expected):
    assert format_number(value) == expected


def test_format_number_rejects_nan():
    with pytest.raises(ValueError):
        format_number(float("nan"))


def test_is_number():
    assert sexpr.is_number(Sym("1.5")) and sexpr.is_number(Sym("-2")) and sexpr.is_number(Str("3"))
    assert not sexpr.is_number(Sym("abc")) and not sexpr.is_number(Sym("")) and not sexpr.is_number(Sym("inf"))
    assert not sexpr.is_number(Node("a"))


# ---------------------------------------------------------------------------
# Prettify и стили
# ---------------------------------------------------------------------------

DIP_HEAD = (
    '(footprint "R" (version 20241229) (generator "pcbnew") (generator_version "9.0") (layer "F.Cu")'
    ' (property "Reference" "REF**" (at 0 -1 0) (layer "F.SilkS") (uuid "u1")'
    ' (effects (font (size 1 1) (thickness 0.15)))) (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6)'
    ' (drill 0.8) (layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "u2")))'
)
DIP_PRETTY = """(footprint "R"
\t(version 20241229)
\t(generator "pcbnew")
\t(generator_version "9.0")
\t(layer "F.Cu")
\t(property "Reference" "REF**"
\t\t(at 0 -1 0)
\t\t(layer "F.SilkS")
\t\t(uuid "u1")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1 1)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t)
\t)
\t(pad "1" thru_hole circle
\t\t(at 0 0)
\t\t(size 1.6 1.6)
\t\t(drill 0.8)
\t\t(layers "*.Cu" "*.Mask")
\t\t(remove_unused_layers no)
\t\t(uuid "u2")
\t)
)
"""


def test_prettify_matches_kicad_style():
    assert prettify(DIP_HEAD) == DIP_PRETTY
    # результат не зависит от пробелов во входе
    spaced = DIP_HEAD.replace(") (", ")   \n (").replace("(at", "( at")
    assert prettify(spaced) == DIP_PRETTY
    # dumps в стиле kicad8 даёт то же
    assert dumps(parse(DIP_HEAD), style="kicad8") == DIP_PRETTY
    assert dumps(parse(DIP_HEAD)) == DIP_PRETTY  # auto по версии


def test_prettify_compact_save_short_forms():
    out = prettify(DIP_HEAD, compact_save=True)
    assert "\t\t(effects\n\t\t\t(font (size 1 1) (thickness 0.15))\n\t\t)\n" in out


def test_prettify_xy_wrapping_at_column_99():
    pts = " ".join(f"(xy {i} {i})" for i in range(40))
    out = prettify(f"(fp_poly (pts {pts}) (layer \"F.Cu\"))")
    lines = out.split("\n")
    xy_lines = [ln for ln in lines if "(xy" in ln]
    assert len(xy_lines) > 1
    assert all(len(ln.expandtabs(1)) <= 99 + 12 for ln in xy_lines)
    # первая строка точек начинается с (xy и содержит несколько точек
    assert xy_lines[0].strip().startswith("(xy 0 0) (xy 1 1)")


def test_prettify_long_token_list_wraps_after_72():
    members = " ".join(f'"{i:08d}-0000-0000-0000-000000000000"' for i in range(6))
    out = prettify(f"(group \"g\" (members {members}))")
    assert "\n\t(members " in out
    # после порога 72 колонок пробел превращается в перевод строки с отступом уровня списка
    assert '"\n\t\t"' in out
    assert out.endswith('"\n\t)\n)\n')


def test_prettify_quotes_with_escapes_not_broken():
    src = r'(a "x \" y (not a list)" (b 1))'
    out = prettify(src)
    assert out == '(a "x \\" y (not a list)"\n\t(b 1)\n)\n'
    src2 = r'(a "back\\" (b 1))'
    assert prettify(src2) == '(a "back\\\\"\n\t(b 1)\n)\n'


def test_prettify_unicode_columns_counted_in_bytes():
    # 30 кириллических символов = 60 байт; длинный список токенов переносится по байтам
    words = " ".join("абвгд" for _ in range(20))
    out = prettify(f"(a (b {words}))")
    assert "\n" in out.split("(b ")[1]


def test_dumps_legacy_style_kicad6(dip14_v6):
    text = dip14_v6.read_text(encoding="utf-8")
    n = parse(text)
    assert dumps(n) == text
    assert dumps(n, style="kicad6") == text


def test_dumps_legacy_style_kicad5(dip14_v5):
    text = dip14_v5.read_text(encoding="utf-8")
    n = parse(text)
    assert n.name == "module"
    assert dumps(n).rstrip("\n") == text.rstrip("\n")


def test_dumps_style_kicad7_layout():
    n = parse('(footprint "X" (version 20221018) (generator pcbnew) (layer "F.Cu") '
              '(fp_line (start 0 0) (end 1 0) (stroke (width 0.12) (type solid)) (layer "F.SilkS") (tstamp t)))')
    out = dumps(n)
    assert out == ('(footprint "X" (version 20221018) (generator pcbnew)\n  (layer "F.Cu")\n'
                   '  (fp_line (start 0 0) (end 1 0)\n'
                   '    (stroke (width 0.12) (type solid)) (layer "F.SilkS") (tstamp t))\n)\n')


def test_dumps_unknown_style():
    with pytest.raises(ValueError):
        dumps(parse("(a)"), style="weird")


def test_style_for_version():
    f = sexpr.style_for_version
    assert f(None, "module") == "kicad5"
    assert f(20211014) == "kicad6"
    assert f(20221018) == "kicad7"
    assert f(20231014) == "kicad8"
    assert f(20240108) == "kicad8"
    assert f(20241229) == "kicad8"


# ---------------------------------------------------------------------------
# Сравнение
# ---------------------------------------------------------------------------


def test_equal_and_diff():
    a = parse('(pad "1" smd rect (at 0 0.5) (size 1.6 1.6))')
    b = parse('(pad 1 smd rect (at 0.0 0.5000001) (size 1.6 1.6))')
    assert equal(a, b)
    assert not equal(a, b, ignore_quotes=False)
    assert diff(a, b) == []
    c = parse('(pad "1" smd rect (at 0 0.6) (size 1.6 1.6) (drill 1))')
    assert not equal(a, c)
    d = diff(a, c)
    assert any("at[0]" in line and "0.5 != 0.6" in line for line in d)
    assert any("число элементов" in line for line in d)
    e = parse('(pad "1" smd (at 0 0.5) rect (size 1.6 1.6))')
    assert not equal(a, e)
    assert diff(a, e)


@pytest.mark.parametrize("x, y", [('"01"', '"1"'), ('"1e3"', '"1000"'), ('"1.0000001"', '"1"'),
                                  ('"1.0"', "1"), ("1.0", '"1"')])
def test_equal_quoted_strings_are_never_numbers(x, y):
    """Регрессия: строка в кавычках — DSN_STRING, числовой допуск к ней не применяется."""
    a, b = parse(f"(pad {x} smd rect)"), parse(f"(pad {y} smd rect)")
    assert not equal(a, b)
    assert not equal(a, b, ignore_quotes=False)
    assert diff(a, b) and "атом 0" in diff(a, b)[0]


def test_equal_numeric_tolerance_only_for_bare_numbers():
    assert equal(parse("(at 1.0000001 -0.0)"), parse("(at 1 0)"))
    assert equal(parse("(at 1e3)"), parse("(at 1000)"))
    # ignore_quotes: одинаковый текст в кавычках и без — равен; форма записи — нет
    assert equal(parse('(pad "1")'), parse("(pad 1)"))
    assert not equal(parse('(pad "1")'), parse("(pad 1)"), ignore_quotes=False)
    assert equal(parse('(descr "x")'), parse('(descr "x")'), ignore_quotes=False)


# ===========================================================================
# Регрессии ревью: лексика DSNLEXER
# ===========================================================================


def test_string_backslash_before_newline_is_unterminated():
    # DSNLEXER читает строку в пределах строки файла: «\» + перевод строки — ошибка
    # «Un-terminated delimited string» (проверено kicad-cli 10.0.6), а не многострочная строка
    for text in ('(a "x\\\ny")', '(a "x\\\r\ny")', '(a "x\\'):
        with pytest.raises(SexprSyntaxError) as ei:
            parse(text)
        assert "незакрытая строка" in ei.value.msg
        assert (ei.value.line, ei.value.col) == (1, 4)
    # сырой \r внутри строки допустим (KiCad копирует его как есть)
    assert parse('(a "x\ry")').atoms() == ["x\ry"]


def test_hex_and_octal_escapes_are_utf8_bytes():
    # \xHH и \ooo дают байты, строка затем декодируется как UTF-8 (wxString::FromUTF8)
    assert parse(r'(a "\xC3\xA9")').atoms() == ["é"]
    assert parse(r'(a "\303\251")').atoms() == ["é"]
    assert parse(r'(a "x\xd0\xb6\x41")').atoms() == ["xжA"]
    assert unquote(r'"\xE2\x82\xAC"') == "€"
    # восьмеричное значение усекается до байта: \777 -> 0xFF
    assert unquote(r'"\101\777"') == "A\xff"
    # некорректный UTF-8: KiCad дал бы пустую строку, здесь — побайтно latin-1 (без потерь)
    assert unquote(r'"a\xFFb"') == "a\xffb"
    assert unquote(r'"\xC3"') == "\xc3"
    # байты < 0x80 — те же символы
    assert unquote(r'"\x41\x7e\0"') == "A~\x00"
    # «испорченные» последовательности
    assert unquote(r'"\x"') == "x"
    assert unquote(r'"\xg"') == "xg"
    assert unquote(r'"\8\z"') == "\\8\\z"


def test_whitespace_set_matches_dsnlexer():
    # isSpace(): ' ', \t, \n, \r и \0; \v и \f — часть голого токена (kicad-cli: (descr foo\vbar))
    assert parse("(a foo\x0bbar x\x0cy)").atoms() == ["foo\x0bbar", "x\x0cy"]
    assert parse("(a b\x00c)").atoms() == ["b", "c"]
    assert parse("(a\x00(b 1)\x00)").nodes()[0].name == "b"
    # неразрывный пробел и прочие юникодные пробелы — тоже часть символа
    assert parse("(a b c)").atoms() == ["b c"]


def test_node_name_may_follow_newlines_and_comment_lines():
    n = parse('(\n  footprint "A" (layer "F.Cu"))')
    assert n.name == "footprint" and (n.line, n.col) == (1, 1)
    n = parse('(\n# комментарий\n\tfootprint "A")')
    assert n.name == "footprint" and n.atoms() == ["A"]
    with pytest.raises(SexprSyntaxError) as ei:
        parse('(\n"a" 1)')
    assert "строкой" in ei.value.msg and (ei.value.line, ei.value.col) == (2, 1)
    with pytest.raises(SexprSyntaxError) as ei:
        parse("(a (\n))")
    assert "имя узла" in ei.value.msg and (ei.value.line, ei.value.col) == (2, 1)
    with pytest.raises(SexprSyntaxError) as ei:
        parse("(a (")
    assert "имя узла" in ei.value.msg and (ei.value.line, ei.value.col) == (1, 5)


def test_comment_lines():
    # строка-комментарий хранится целиком (с начальными пробелами), без CR/LF — как
    # DSNLEXER::ReadCommentLines (kicad-cli 10.0.6 сохраняет «   # leading comment»)
    n = parse("   # первая\r\n\t#вторая\r\n\r\n(footprint \"A\")\r\n")
    assert n.comments == ["   # первая", "\t#вторая"]
    # комментарий — вся строка, даже со скобками и кавычками; внутри узла отбрасывается
    n = parse('(a (b 1)\n   # (c 2) "x\n  (d 3))')
    assert [c.name for c in n.nodes()] == ["b", "d"] and n.comments == []
    # «#» не в начале строки — обычный символ; в строке — часть строки
    n = parse('(a #b "#c" (d #e))')
    assert n.atoms() == ["#b", "#c"] and n.find("d").atoms() == ["#e"]
    # комментарии после корня и между корнями не прикрепляются
    roots = parse_all("# c1\n(a)\n# c2\n(b)\n")
    assert roots[0].comments == ["# c1"] and roots[1].comments == []


def test_symbol_and_string_boundaries():
    # кавычка внутри голого токена — обычный символ; строка, за которой сразу символ
    n = parse('(a b"c d "e"f)')
    assert n.atoms() == [Sym('b"c'), Sym("d"), Str("e"), Sym("f")]
    # «|» (DSN_BAR 9.0+) остаётся частью символа: исходный текст данных сохраняется
    n = parse("(data |AAAA BBBB|)")
    assert n.atoms() == ["|AAAA", "BBBB|"]
    assert prettify(to_compact(n)) == "(data |AAAA BBBB|)\n"
    # скобки внутри строки не влияют на структуру
    n = parse('(a "(b (c" (d ")"))')
    assert n.atoms() == ["(b (c"] and n.find("d").atoms() == [")"]


def test_bom_only_at_start():
    assert parse("﻿(a 1)").name == "a"
    # BOM не в начале — обычный символ (часть токена)
    assert parse("(a ﻿b)").atoms() == ["﻿b"]


# ===========================================================================
# Числа: is_number, number(), форматирование (эталон — C printf, см. kfmt.c в отчёте)
# ===========================================================================


@pytest.mark.parametrize(
    "text, expected",
    [("1", True), ("-2.5", True), ("+1", True), (".5", True), ("5.", True), ("1e5", True),
     ("-1.5E-3", True), ("5E888720", True), ("1_0", False), ("inf", False), ("-inf", False),
     ("nan", False), ("+nan", False), ("1e", False), ("-", False), (".", False), ("", False),
     ("0x10", False), ("1.5.5", False), (" 1", False), ("1 ", False), ("１", False)],
)
def test_is_number_follows_dsnlexer(text, expected):
    assert sexpr.is_number(Sym(text)) is expected
    assert sexpr.is_number(Str(text)) is expected


def test_number_accessors_use_dsnlexer_syntax():
    n = parse("(a (b 1_0 inf 2.5 nan -1) (c 1e2))")
    assert n.number("b") is None and n.number("b", default=7.0) == 7.0
    assert n.number("b", 2) == 2.5 and n.number("c") == 100.0
    assert n.numbers("b") == [2.5, -1.0]
    assert not equal(parse("(a 1_0)"), parse("(a 10)"))
    assert equal(parse("(a 1e3 .5)"), parse("(a 1000 0.5)"))


# (значение, FormatInternalUnits(KiROUND(v*1e6)), FormatAngle, FormatDouble2Str) — вывод C
# printf (clang, macOS) по коду KiCad 9.0 (eda_units.cpp, string_utils.cpp, math_util.h)
_C_REFERENCE = [
    (0.15, "0.15", "0.15", "0.15"),
    (1e-06, "0.000001", "1e-06", "0.000001"),
    (12.3456789, "12.345679", "12.3456789", "12.3456789"),
    (1e-05, "0.00001", "1e-05", "0.00001"),
    (0.30000000000000004, "0.3", "0.3", "0.3"),
    (0.0001, "0.0001", "0.0001", "0.0001"),
    (1e-07, "0", "1e-07", "0.0000001"),
    (0.3333333333333333, "0.333333", "0.3333333333", "0.3333333333"),
    (-180.0, "-180", "-180", "-180"),
    (2147.483647, "2147.483647", "2147.483647", "2147.483647"),
    (-2147.483648, "-2147.483648", "-2147.483648", "-2147.483648"),
    (5e-07, "0.000001", "5e-07", "0.0000005"),
    (-5e-07, "-0.000001", "-5e-07", "-0.0000005"),
    (1.5e-06, "0.000002", "1.5e-06", "0.0000015"),
    (2.5e-06, "0.000003", "2.5e-06", "0.0000025"),
    (1.0000005, "1.000001", "1.0000005", "1.0000005"),
    (210.1910385, "210.191039", "210.1910385", "210.1910385"),
    (-1374.5489635, "-1374.548964", "-1374.548963", "-1374.548963"),
    (347.5977155, "347.597716", "347.5977155", "347.5977155"),
    (99.9999995, "100", "99.9999995", "99.9999995"),
    (1234.5678905, "1234.567891", "1234.56789", "1234.56789"),
    (0.000100001, "0.0001", "0.000100001", "0.000100001"),
    (51.42857142857143, "51.428571", "51.42857143", "51.42857143"),
    (359.9999999999, "360", "360", "360"),
    (0.2083333333333333, "0.208333", "0.2083333333", "0.2083333333"),
    (0.05494505494505494, "0.054945", "0.05494505495", "0.05494505495"),
    (0.2249999962, "0.225", "0.2249999962", "0.2249999962"),
    (1e-09, "0", "1e-09", "0.000000001"),
    (3.3e-12, "0", "3.3e-12", "0.0000000000033"),
    (0.00012345678901, "0.000123", "0.000123456789", "0.000123456789"),
    (-412.4110305, "-412.411031", "-412.4110305", "-412.4110305"),
    (-1080.4792495, "-1080.47925", "-1080.479249", "-1080.479249"),
    (983.6807545, "983.680755", "983.6807545", "983.6807545"),
    (-1068.7982885, "-1068.798288", "-1068.798288", "-1068.798288"),
]


@pytest.mark.parametrize("value, iu, angle, dbl", _C_REFERENCE)
def test_number_formats_match_kicad_c_reference(value, iu, angle, dbl):
    assert format_number(value) == iu
    # FormatAngle/FormatDouble2Str без экспоненты: там, где %.10g дал бы «1e-06»,
    # пишется десятичная запись того же значения
    for got, ref in ((sexpr.format_angle(value), angle), (sexpr.format_double(value), dbl)):
        assert "e" not in got
        if "e" in ref:
            assert float(got) == float(ref)
        else:
            assert got == ref


def test_format_number_rounds_half_away_from_zero_like_kiround():
    # round() Python дал бы 210.191038 и 0 — KiCad (KiROUND(v*1e6)) пишет иначе
    assert format_number(210.1910385) == "210.191039"
    assert format_number(0.0000005) == "0.000001"
    assert format_number(-0.0000005) == "-0.000001"
    assert format_number(0.00000049) == "0"
    assert format_number(-0.0000004) == "0"  # не «-0»
    # огромные значения (вне диапазона KiCad) не вызывают переполнения
    assert format_number(1e303).startswith("1000000000") and "e" not in format_number(-1e300)


def test_format_angle_and_double_extra():
    fa, fd = sexpr.format_angle, sexpr.format_double
    assert fa(-0.0) == "0" and fd(-0.0) == "0" and fd(-1e-20) == "0"
    assert fa(90) == "90" and fa(-45.5) == "-45.5" and fa(1e10) == "10000000000"
    assert fa(1.2345e-5) == "0.000012345" and fa(1.5e-7) == "0.00000015"
    assert fd(1e-17) == "0" and fd(1.25e10) == "12500000000"
    for f in (fa, fd, format_number):
        with pytest.raises(ValueError):
            f(float("inf"))


def test_python_printf_equals_c_printf_semantics():
    # Python «%» использует корректное округление, как printf libc: сверка ключевых форм
    assert "%.10g" % 2.675 == "2.675" and "%.10f" % 1e-5 == "0.0000100000"
    assert "%.10g" % 0.1 == "0.1" and "%.16f" % 5e-7 == "0.0000005000000000"


# ===========================================================================
# Prettify: режим 8.0 и эквивалентность построчному порту
# ===========================================================================


def _prettify_reference(source: str, mode: str) -> str:
    """Построчный порт KICAD_FORMAT::Prettify 8.0/9.0 (compact_save=False) — эталон."""
    source = source.encode("utf-8").decode("latin-1")
    formatted: list[str] = []
    n = len(source)
    depth, last, in_quote, ins, multi, in_xy, col, bs = 0, "\0", False, False, False, False, 0, 0
    ws = " \t\n\r"
    for i, c in enumerate(source):
        k = i
        while k < n and source[k] in ws:
            k += 1
        nxt = source[k] if k < n else "\0"
        if c in ws and not in_quote:
            if not ins and depth > 0 and last != "(" and nxt != ")" and nxt != "(":
                if in_xy or col < 72:
                    formatted.append(" ")
                    col += 1
                else:
                    formatted.append("\n" + "\t" * depth)
                    col = depth
                    multi = True
                ins = True
            continue
        ins = False
        if c == "(" and not in_quote:
            cur_xy = source.startswith("xy ", i + 1)
            first = depth == 0 if mode == "8.0" else not formatted
            if first:
                formatted.append("(")
                col += 1
            elif in_xy and cur_xy and col < 99:
                formatted.append(" (")
                col += 2
            else:
                formatted.append("\n" + "\t" * depth + "(")
                col = depth + 1
            in_xy = cur_xy
            depth += 1
        elif c == ")" and not in_quote:
            depth = max(depth - 1, 0)
            if last == ")" or multi:
                formatted.append("\n" + "\t" * depth + ")")
                col = depth + 1
                multi = False
            else:
                formatted.append(")")
                col += 1
        else:
            if c == "\\":
                bs += 1
            elif c == '"' and bs % 2 == 0:
                in_quote = not in_quote
            if c != "\\":
                bs = 0
            formatted.append(c)
            col += 1
        last = c
    formatted.append("\n")
    return "".join(formatted).encode("latin-1").decode("utf-8")


def test_prettify_mode_8_first_paren_rule():
    # 8.0: «(» без перевода строки, пока listDepth == 0; 9.0/10: только в начале вывода
    assert prettify("(a)(b)", mode="8.0") == "(a)(b)\n"
    assert prettify("(a)(b)", mode="9.0") == "(a)\n(b)\n"
    assert prettify("(a)(b)", mode="10") == "(a)\n(b)\n"


def test_prettify_equals_line_by_line_port_fuzz():
    import random

    rnd = random.Random(20260927)
    alphabet = ["(", ")", " ", "\n", "\t", '"', "\\", "xy ", "(xy ", "a", "bc", "1.5", "é",
                "(font ", '"x y"', '\\"', "\\\\", "  ", "\r\n"]
    for _ in range(3000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 30)))
        for mode in ("8.0", "9.0"):
            assert prettify(s, mode=mode) == _prettify_reference(s, mode), (s, mode)
    # и на длинном списке атомов (перенос по колонке 72) и точек xy (колонка 99)
    s = "(a " + " ".join(f'"{i:030d}"' for i in range(10)) + " (pts " + \
        " ".join(f"(xy {i}.123456 {i}.654321)" for i in range(20)) + "))"
    assert prettify(s) == _prettify_reference(s, "9.0")


def test_quote_unquote_roundtrip_fuzz():
    import random

    rnd = random.Random(7)
    chars = ['a', '"', "\\", "\n", "\r", "\t", "é", " ", "(", ")", "#", "\x00", "\x07", "€"]
    for _ in range(2000):
        s = "".join(rnd.choice(chars) for _ in range(rnd.randint(0, 12)))
        q = quote(s)
        assert q.count("\n") == 0 and q.count("\r") == 0
        assert unquote(q) == s
        assert parse(f"(t {q})").atoms() == [s]


# ===========================================================================
# Node.set / insert / set_flag: все ветки вставки по таблице порядка
# ===========================================================================

_ORDER = ("a", "b", "c", "d", "e")


def _names(n: Node) -> list[str]:
    return [x.name if isinstance(x, Node) else str(x) for x in n.items]


@pytest.mark.parametrize(
    "src, name, expected",
    [
        # предшественники есть: после последнего из них (даже если он стоит не по порядку)
        ("(n X (a) (c))", "b", ["X", "a", "b", "c"]),
        ("(n X (a) (b) (b) (d))", "b", ["X", "a", "b", "b", "b", "d"]),  # set() правит первый b
        ("(n X (c) (a))", "b", ["X", "c", "a", "b"]),
        # неизвестные узлы между предшественником и последователем: сразу после предшественника
        ("(n X (a) (u1) (u2) (d))", "c", ["X", "a", "c", "u1", "u2", "d"]),
        # предшественников нет: после ведущих атомов и перед первым последователем
        ("(n X Y (d) (e))", "b", ["X", "Y", "b", "d", "e"]),
        ("(n X (u1) (d))", "a", ["X", "u1", "a", "d"]),
        ("(n (d))", "a", ["a", "d"]),
        # атомы после узлов (флаги 6/7): вставка перед первым последователем, флаг остаётся
        ("(n X (a) flag (d))", "c", ["X", "a", "c", "flag", "d"]),
        ("(n X (d) flag)", "b", ["X", "b", "d", "flag"]),
        # ни предшественников, ни последователей: после ведущих атомов (перед неизвестными)
        ("(n X (u1))", "c", ["X", "c", "u1"]),
        ("(n)", "c", ["c"]),
        # имени нет в таблице — в конец
        ("(n X (a) (e))", "zz", ["X", "a", "e", "zz"]),
    ],
)
def test_node_insert_by_order_all_branches(src, name, expected):
    n = parse(src)
    n.insert(Node(name, [1]), order=_ORDER)
    assert _names(n) == expected
    m = parse(src)
    existed = m.find(name) is not None
    m.set(name, 1, order=_ORDER)
    if existed:  # set() меняет атомы существующего узла на месте
        assert _names(m) == _names(parse(src))
    else:
        assert _names(m) == expected


def test_node_set_existing_keeps_position_and_subnodes():
    n = parse("(n (a 1) (b 2 (s 1) 3) (c))")
    b = n.find("b")
    assert n.set("b", 5, order=_ORDER) is b
    assert to_compact(n) == "(n(a 1)(b 5(s 1))(c))"
    n.set("a")  # без значений — атомы удаляются
    assert to_compact(n.find("a")) == "(a)"


@pytest.mark.parametrize(
    "src, flag, order, expected",
    [
        # по таблице: после последнего элемента с рангом не больше
        ('(t ref "R" (at 0 0) (layer L) (effects))', "hide", ("at", "layer", "hide", "effects"),
         ["ref", "R", "at", "layer", "hide", "effects"]),
        # хвостовой неизвестный атом не утаскивает флаг в конец
        ('(t ref "R" (at 0 0) (layer L) (effects) weird)', "hide", ("at", "layer", "hide", "effects"),
         ["ref", "R", "at", "layer", "hide", "effects", "weird"]),
        # голые флаги в таблице (font 6/7): bold после thickness, italic после bold
        ("(font (size 1 1) (thickness 0.1) italic)", "bold",
         ("face", "size", "line_spacing", "thickness", "bold", "italic", "color"),
         ["size", "thickness", "bold", "italic"]),
        # флаг первым (locked у графики 6/7)
        ("(fp_line (start 0 0) (end 1 1))", "locked", ("locked", "start", "end"),
         ["locked", "start", "end"]),
        # неизвестные подузлы нейтральны
        ("(t X (u) (a) (u2) (c))", "b", ("a", "b", "c"), ["X", "u", "a", "b", "u2", "c"]),
        # без order — после последнего атома
        ("(pad 1 smd rect (at 0 0))", "locked", None, ["1", "smd", "rect", "locked", "at"]),
    ],
)
def test_set_flag_positions(src, flag, order, expected):
    n = parse(src)
    n.set_flag(flag, True, order=order)
    assert _names(n) == expected
    n.set_flag(flag, True, order=order)  # повторно — без дубля
    assert _names(n) == expected
    n.set_flag(flag, False)
    assert flag not in _names(n)


def test_flags_skip_positional_atoms_kicad5_text():
    """Регрессия: текст fp_text KiCad 5 без кавычек («hide») — значение, а не флаг."""
    src = '(fp_text user hide (at 0 0) (layer F.Fab) (effects (font (size 1 1) (thickness 0.15))))'
    t = parse(src)
    assert not t.has_flag("hide")
    t.set_flag("hide", True, order=("at", "unlocked", "layer", "knockout", "hide", "effects"))
    assert to_compact(t) == ("(fp_text user hide(at 0 0)(layer F.Fab) hide"
                             "(effects(font(size 1 1)(thickness 0.15))))")
    assert t.has_flag("hide")
    t.set_flag("hide", False)
    assert to_compact(t) == to_compact(parse(src))  # текст «hide» не потерян
    t2 = parse('(fp_text user hide (at 0 0) (layer F.Fab) hide (effects (font (size 1 1))))')
    assert t2.has_flag("hide")
    t2.set_flag("hide", False)
    assert to_compact(t2) == "(fp_text user hide(at 0 0)(layer F.Fab)(effects(font(size 1 1))))"
    # skip=0 — старое поведение: все голые символы считаются флагами
    assert parse(src).has_flag("hide", skip=0)


@pytest.mark.parametrize(
    "src, flag, has",
    [
        ("(pad locked smd rect (at 0 0))", "locked", False),          # номер площадки «locked»
        ("(pad 1 smd rect locked (at 0 0))", "locked", True),
        ("(model hide (at (xyz 0 0 0)))", "hide", False),             # путь модели «hide»
        ("(model a.wrl hide (at (xyz 0 0 0)))", "hide", True),
        ("(module locked (layer F.Cu))", "locked", False),             # имя корпуса «locked»
        ("(module X locked (layer F.Cu))", "locked", True),
        ('(fp_text reference locked "REF**" (at 0 0))', "locked", True),   # флаг KiCad 6/7
        ("(fp_text user locked (at 0 0))", "locked", False),          # текст «locked» (KiCad 5)
        ('(property "hide" "hide" (at 0 0))', "hide", False),
        ('(fp_text_box locked "t" (start 0 0))', "locked", True),
        ("(effects (font (size 1 1)) hide)", "hide", True),           # узлы вне таблицы
    ],
)
def test_has_flag_positional_table(src, flag, has):
    assert parse(src).has_flag(flag) is has


def test_set_flag_locked_slot_fp_text():
    t = parse('(fp_text reference "REF**" (at 0 0) (layer "F.SilkS") (effects))')
    t.set_flag("locked", True)
    assert to_compact(t).startswith('(fp_text reference locked "REF**"(at 0 0)')
    assert t.has_flag("locked")
    t.set_flag("locked", True)
    assert to_compact(t).count("locked") == 1
    t.set_flag("locked", False)
    assert to_compact(t).startswith('(fp_text reference "REF**"(at')
    # текст «locked» KiCad 5 не удаляется и не считается флагом
    k5 = parse("(fp_text user locked (at 0 0) (layer F.Fab))")
    k5.set_flag("locked", False)
    assert to_compact(k5) == "(fp_text user locked(at 0 0)(layer F.Fab))"
    tb = parse('(fp_text_box "t" (start 0 0))')
    tb.set_flag("locked", True)
    assert to_compact(tb).startswith('(fp_text_box locked "t"(start')



# ===========================================================================
# Раскладка KiCad 5/6/7: без потерь для любых деревьев
# ===========================================================================


def test_legacy_zone_filled_areas_thickness_not_lost():
    # (filled_areas_thickness) не после (min_thickness) раньше затирал предыдущую строку
    text = ('(footprint "X" (version 20211014) (generator pcbnew)\n  (layer "F.Cu")\n  (tedit 0)\n'
            '  (zone (net 0) (net_name "") (layers "F.Cu") (tstamp 1) (hatch edge 0.508)\n'
            '    (connect_pads (clearance 0))\n    (filled_areas_thickness no)\n'
            '    (min_thickness 0.254) (filled_areas_thickness no)\n'
            '    (keepout (tracks not_allowed))\n  )\n)\n')
    n = parse(text)
    assert dumps(n) == text


def test_legacy_kicad7_fp_text_effects_indent():
    # writer 7.0: EDA_TEXT::Format(aNestLevel + 1) — effects на 2 уровня глубже fp_text
    # (75 файлов version 20221018 в kicad-footprints 7.0.0 — байт в байт)
    text = ('(footprint "A" (version 20221018) (generator pcbnew)\n  (layer "F.Cu")\n  (attr smd)\n'
            '  (fp_text reference "REF**" (at 0 -2.5) (layer "F.SilkS")\n'
            '      (effects (font (size 1 1) (thickness 0.15)))\n'
            '    (tstamp 17bab7e4-a5c5-4974-832d-5bcbbde0d6bb)\n  )\n'
            '  (fp_line (start 0 0) (end 1 0)\n'
            '    (stroke (width 0.12) (type solid)) (layer "F.SilkS") (tstamp t))\n)\n')
    assert dumps(parse(text)) == text
    assert dumps(parse(text), style="kicad6").count("\n    (effects") == 1


def test_legacy_5_99_nightly_header():
    text = ('(footprint "A" (version 20210722) (generator pcbnew) (layer "F.Cu")\n  (tedit 614EEA64)\n'
            '  (attr through_hole)\n)\n')
    assert dumps(parse(text)) == text


def test_legacy_layout_keeps_nonstandard_trees():
    # нестандартный порядок/состав: каждый узел, который табличная раскладка исказила бы,
    # пишется одной строкой, заголовок — в общем виде; дерево не меняется
    samples = [
        '(footprint "X" (layer "F.Cu") (version 20211014) (generator pcbnew) (attr smd))',
        '(footprint "X" (version 20211014) (generator pcbnew) weird locked (layer "F.Cu"))',
        '(footprint (version 20211014) (layer "F.Cu"))',
        '(footprint "X" (version 20221018) (generator pcbnew) (layer "F.Cu")'
        ' (fp_text_box "t" (start 0 0) (end 1 1) (margins 1 1 1 1) (layer "F.SilkS") (uuid "u")'
        ' (effects (font (size 1 1))) (render_cache "t" 0 (polygon (pts (xy 0 0) (xy 1 1))))))',
        '(footprint "X" (version 20211014) (generator pcbnew) (layer "F.Cu")'
        ' (group "" (id 1) (uuid "u") (members a b)) (pad "1" smd rect (at 0 0) (size 1 1)'
        ' (options (a)) (options (b)) (layers "F.Cu")))',
        '(module X (layer F.Cu) (tedit 0) (fp_poly (pts (xy 0 0)) (pts (xy 1 1)) (layer F.SilkS)))',
        '(kicad_pcb (version 20211014) x (general) y)',
    ]
    for src in samples:
        tree = parse(src)
        for style in ("kicad5", "kicad6", "kicad7", "kicad8"):
            out = dumps(tree, style=style)
            assert sexpr._same_tree(parse(out), tree), (style, src, out)


def _mutate(tree: Node, rnd) -> Node:
    """Случайная правка дерева: перестановка, неизвестные узлы и атомы, удаление, копия."""
    t = tree.copy()
    nodes = [t]
    stack = [t]
    while stack:
        x = stack.pop()
        for k in x.nodes():
            nodes.append(k)
            stack.append(k)
    for _ in range(rnd.randint(1, 4)):
        target = rnd.choice(nodes)
        op = rnd.randrange(5)
        if op == 0 and len(target.items) > 1:
            i, j = rnd.randrange(len(target.items)), rnd.randrange(len(target.items))
            target.items[i], target.items[j] = target.items[j], target.items[i]
        elif op == 1:
            target.items.insert(rnd.randint(0, len(target.items)), Node("unknown_tok", [1, "s"]))
        elif op == 2:
            target.items.insert(rnd.randint(0, len(target.items)),
                                rnd.choice([Sym("flag"), Str("q q"), Sym("#h"), Sym('a"b'), Str("")]))
        elif op == 3 and target.items:
            del target.items[rnd.randrange(len(target.items))]
        else:
            kids = target.nodes()
            if kids:
                target.items.append(rnd.choice(kids).copy())
    return t


def test_all_styles_lossless_on_mutated_fixtures():
    import random

    from tests.conftest import fixture_files

    rnd = random.Random(5)
    files = fixture_files("kicad5", "kicad6", "kicad8", "kicad9")
    files = files[:: max(1, len(files) // 25)]
    for path in files:
        tree = parse(path.read_text(encoding="utf-8"))
        for _ in range(3):
            m = _mutate(tree, rnd)
            for style in ("kicad5", "kicad6", "kicad7", "kicad8"):
                out = dumps(m, style=style)
                assert sexpr._same_tree(parse(out), m), (path.name, style)


def test_prettify_style_symbols_with_quote_or_backslash():
    # голые «q"r» и «x\\» (DSNLEXER читает их как символы) сбивали отслеживание строк в
    # Prettify: пробелы в следующей строке в кавычках схлопывались ("s t   u" -> "s t u")
    for src in ('(a x\\ "s t   u" (b 1))', '(a q"r (b "x y  z") (c 1))', '(a\\ "x  y")',
                '(a "\x01" q"r "t  t")'):
        tree = parse(src)
        out = dumps(tree, style="kicad8")
        assert sexpr._same_tree(parse(out), tree), (src, out)
    assert dumps(parse('(a q"r (b "x y  z"))'), style="kicad8") == '(a q"r\n\t(b "x y  z")\n)\n'


def test_hash_symbol_never_starts_a_line():
    # голый «#…» из файла после переноса Prettify (колонка 72) или на своей строке в общей
    # раскладке читался бы как комментарий — данные терялись
    t = parse("(a (members " + " ".join(f"abcdefghij{i}" for i in range(6)) + " #hash tail))")
    samples = [t, parse('(footprint "X" (layer "F.Cu") (version 20211014) #weird (attr smd))')]
    for tree in samples:
        for style in ("kicad5", "kicad6", "kicad7", "kicad8"):
            out = dumps(tree, style=style)
            assert sexpr._same_tree(parse(out), tree), (style, out)
            assert not any(line.lstrip(" \t").startswith("#") for line in out.split("\n"))
    t.comments = ["# комментарий"]
    assert dumps(t).startswith("# комментарий\n(a")


def test_dumps_uses_root_name_in_legacy_header():
    fp = parse('(footprint "X" (version 20211014) (generator pcbnew) (layer "F.Cu"))')
    assert dumps(fp, style="kicad5").startswith("(footprint ")
    mod = parse("(module X (layer F.Cu) (tedit 0))")
    assert dumps(mod, style="kicad6").startswith("(module ")
