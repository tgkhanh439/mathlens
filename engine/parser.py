"""Normalise student input and parse it into SymPy objects.

Goal: accept the way students actually type maths (3(x+2), x^2, roots, Unicode
multiplication signs, comma decimals) while still returning clean SymPy objects
for the rest of the pipeline to work with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# Unicode characters that show up when students paste from Word or Google Docs.
UNICODE_MAP = {
    "\u2212": "-",   # minus sign
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u00d7": "*",   # multiplication sign
    "\u00b7": "*",   # middle dot
    "\u2217": "*",   # asterisk operator
    "\u00f7": "/",   # division sign
    "\u2044": "/",   # fraction slash
    "\u221a": "sqrt",
    "\u00b2": "^2",
    "\u00b3": "^3",
    "\u2260": "!=",
    "\u2264": "<=",
    "\u2265": ">=",
}

# Vietnamese keywords mapped to SymPy functions.
WORD_MAP = {
    "canbac2": "sqrt",
    "canbachai": "sqrt",
    "can": "sqrt",
    "cbh": "sqrt",
}

RESERVED = {"E", "I", "N", "O", "S", "beta", "gamma", "zeta", "lambda", "pi"}


@dataclass
class ParsedStep:
    """Result of parsing one line of student input."""

    raw: str
    kind: str = "expr"            # "expr" | "eq"
    obj: Optional[sp.Basic] = None       # simplified form, used for the maths
    struct: Optional[sp.Basic] = None    # structure-preserving form, used by the rule engine
    error: Optional[str] = None
    # Stable code so interfaces can show the message in their own language:
    # "empty" | "multiple_equals" | "unparsable"
    error_code: Optional[str] = None
    symbols: set = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return self.obj is not None

    @property
    def is_equation(self) -> bool:
        return self.kind == "eq"

    def pretty(self) -> str:
        if not self.ok:
            return self.raw
        if self.is_equation:
            return f"{sp.sstr(self.obj.lhs)} = {sp.sstr(self.obj.rhs)}"
        return sp.sstr(self.obj)


def normalize_text(text: str) -> str:
    """Clean up the raw string before handing it to SymPy."""
    s = text.strip()
    for src, dst in UNICODE_MAP.items():
        s = s.replace(src, dst)

    # Vietnamese decimal comma: 0,5 becomes 0.5, but only between two digits.
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)

    # Vietnamese keywords, lowercased before matching.
    lowered = s.lower()
    for word, fn in WORD_MAP.items():
        lowered = lowered.replace(word, fn)
    if lowered != s.lower():
        s = lowered

    # Collapse repeated whitespace.
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_raw(text: str) -> Optional[sp.Basic]:
    """Parse without evaluation so the written structure survives.

    SymPy simplifies eagerly: 3*(x+2) becomes 3x+6 and x^2*x^3 becomes x^5.
    The rule engine needs to see what the student WROTE, not just its value.
    """
    try:
        return parse_expr(text, transformations=TRANSFORMATIONS, evaluate=False)
    except Exception:  # noqa: BLE001
        return None


def parse_step(text: str) -> ParsedStep:
    """Parse one line, which may be an expression or an equation."""
    raw = text.strip()
    if not raw:
        return ParsedStep(raw=raw, error="Empty line", error_code="empty")

    s = normalize_text(raw)

    if "==" in s:
        s = s.replace("==", "=")

    if s.count("=") > 1:
        return ParsedStep(
            raw=raw,
            error="Each line may contain at most one '='. Split it into separate steps.",
            error_code="multiple_equals",
        )

    try:
        if "=" in s:
            lhs_txt, rhs_txt = s.split("=")
            lhs = parse_expr(lhs_txt.strip(), transformations=TRANSFORMATIONS)
            rhs = parse_expr(rhs_txt.strip(), transformations=TRANSFORMATIONS)
            obj = sp.Eq(lhs, rhs, evaluate=False)
            struct = sp.Eq(
                _parse_raw(lhs_txt.strip()) or lhs,
                _parse_raw(rhs_txt.strip()) or rhs,
                evaluate=False,
            )
            kind = "eq"
        else:
            obj = parse_expr(s, transformations=TRANSFORMATIONS)
            struct = _parse_raw(s) or obj
            kind = "expr"
    except Exception as exc:  # noqa: BLE001 - report to the student instead of crashing
        return ParsedStep(
            raw=raw,
            error=f"Could not read this expression: {exc}",
            error_code="unparsable",
        )

    return ParsedStep(raw=raw, kind=kind, obj=obj, struct=struct,
                      symbols=set(obj.free_symbols))


def parse_solution(text: str) -> list[ParsedStep]:
    """Parse a whole solution: every non-empty line is one step."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [parse_step(ln) for ln in lines]


def main_symbol(steps: list[ParsedStep]) -> Optional[sp.Symbol]:
    """Guess the main unknown: the most frequent symbol, preferring x."""
    counter: dict[sp.Symbol, int] = {}
    for st in steps:
        for sym in st.symbols:
            counter[sym] = counter.get(sym, 0) + 1
    if not counter:
        return None
    for sym in counter:
        if sym.name == "x":
            return sym
    return max(counter, key=lambda k: counter[k])
