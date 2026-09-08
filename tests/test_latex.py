"""Tests for the LaTeX repair/validation module."""
from __future__ import annotations

from ocrqp.latex import (
    balance_braces,
    katex_available,
    sanitize_document,
    sanitize_text,
    split_math,
    validate_katex,
)


def test_unicode_replaced():
    out, _ = sanitize_text("$-3<x≤2$")
    assert "\\leq" in out and "≤" not in out


def test_dropped_opening_dollar_fixed():
    out, _ = sanitize_text("their $\\frac{1}{x}$ oe\n20x+80=7x^{2}+28x$ oe")
    # second line's math region should now be wrapped
    assert "$20x+80=7x^{2}+28x$" in out


def test_balance_braces():
    assert balance_braces("\\frac{256}{3}\\pi}{8^{3}}").count("}") == \
        balance_braces("\\frac{256}{3}\\pi}{8^{3}}").count("{")


def test_split_math_alternates():
    segs = split_math("a $x$ b $y$ c")
    assert segs == [(False, "a "), (True, "x"), (False, " b "), (True, "y"), (False, " c")]


def test_sanitize_document_valid():
    ds = {"questions": [
        {"id": "1", "text": "$3\\frac{1}{2}$", "answer": "$\\frac{7}{2}$",
         "working": "$x=5$", "notes": "M1 for $2x=10$"},
        {"id": "2", "text": "bad $x^{2}$ and 7x^{2}+28x$", "answer": "",
         "working": "", "notes": ""},
    ]}
    out, _ = sanitize_document(ds, validate=katex_available())
    assert out["questions"][0]["text"] == "$3\\frac{1}{2}$"
    if katex_available():
        # every math segment in the output must be KaTeX-valid
        segs = [c for q in out["questions"] for f in ("text", "answer", "working", "notes")
                for m, c in split_math(q.get(f) or "") if m]
        results = validate_katex(segs)
        assert all(ok for ok, _ in results), "output contains invalid KaTeX"
