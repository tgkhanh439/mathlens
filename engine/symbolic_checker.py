"""Mathematical equivalence between two expressions or two equations.

Principle: the symbolic layer is what decides right from wrong. When simplify
cannot settle the question, fall back to random numeric substitution, so a
step is never called wrong merely because SymPy failed to simplify it.
"""

from __future__ import annotations

import random
from typing import Optional

import sympy as sp

RANDOM_TRIALS = 12
TOLERANCE = 1e-9


def _numeric_equivalent(a: sp.Basic, b: sp.Basic, trials: int = RANDOM_TRIALS) -> Optional[bool]:
    """Compare by random substitution. None means inconclusive."""
    syms = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
    rng = random.Random(20260812)
    checked = 0
    for _ in range(trials * 3):
        subs = {s: sp.Rational(rng.randint(2, 40), rng.randint(1, 7)) for s in syms}
        try:
            va = complex(sp.N(a.subs(subs), 20))
            vb = complex(sp.N(b.subs(subs), 20))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if any(map(lambda v: v != v or abs(v) == float("inf"), (va, vb))):
            continue
        checked += 1
        if abs(va - vb) > TOLERANCE * max(1.0, abs(va), abs(vb)):
            return False
        if checked >= trials:
            return True
    return True if checked else None


def expr_equivalent(a: sp.Basic, b: sp.Basic) -> bool:
    """Whether two expressions are equal for every value of their variables."""
    if a == b:
        return True
    try:
        diff = sp.simplify(sp.expand(sp.together(a - b)))
        if diff == 0:
            return True
        if diff.is_number and diff != 0:
            return False
    except Exception:  # noqa: BLE001
        pass
    numeric = _numeric_equivalent(a, b)
    return bool(numeric)


def solution_set(eq: sp.Eq, symbol: sp.Symbol) -> Optional[frozenset]:
    """Real solution set of an equation. None when it cannot be solved reliably."""
    if symbol is None:
        return None
    try:
        sols = sp.solve(sp.Eq(eq.lhs, eq.rhs), symbol, dict=False)
    except Exception:  # noqa: BLE001
        return None
    if sols is None:
        return None
    if isinstance(sols, bool):
        return None
    out = set()
    for s in sols:
        try:
            val = sp.nsimplify(sp.simplify(s))
        except Exception:  # noqa: BLE001
            val = s
        if val.free_symbols:
            return None          # root still contains a parameter, not comparable
        if val.is_real is False:
            continue             # v1.0 considers real roots only
        out.add(sp.simplify(val))
    return frozenset(out)


def eq_relation(prev: sp.Eq, curr: sp.Eq, symbol: sp.Symbol) -> str:
    """Relationship between two consecutive equations.

    Returns: "equivalent" | "lost_roots" | "extra_roots" | "not_equivalent"
             | "unknown"
    """
    if expr_equivalent(prev.lhs - prev.rhs, curr.lhs - curr.rhs):
        return "equivalent"

    s_prev = solution_set(prev, symbol)
    s_curr = solution_set(curr, symbol)
    if s_prev is None or s_curr is None:
        # Unsolvable: check whether one is a constant multiple of the other.
        try:
            ratio = sp.simplify((curr.lhs - curr.rhs) / (prev.lhs - prev.rhs))
            if ratio.is_number and ratio != 0:
                return "equivalent"
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    if s_prev == s_curr:
        return "equivalent"
    if s_curr < s_prev:
        return "lost_roots"
    if s_prev < s_curr:
        return "extra_roots"
    return "not_equivalent"


def same_solution_value(value: sp.Basic, expected: sp.Basic) -> bool:
    """Compare a final answer against the expected one."""
    try:
        return sp.simplify(value - expected) == 0
    except Exception:  # noqa: BLE001
        return False
