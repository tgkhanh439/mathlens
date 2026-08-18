"""Rule engine for misconception detection.

The idea: rather than guessing what the student was thinking, the system
SIMULATES each faulty idea. Starting from the last valid step, every rule
produces the result a student WOULD write if they held that misconception.
A rule matches when its simulated result equals what the student actually wrote.

Two match tiers:
  - tier 1 (confident): the simulation equals the student's step exactly.
  - tier 2 (weak): it only matches after scaling both sides by a constant.

The payoff: every conclusion is explainable, testable, and free of any LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional

import sympy as sp

from .symbolic_checker import expr_equivalent

CONF_TIER1 = 0.85
CONF_TIER2 = 0.55
CONF_SOLUTION_SET = 0.7
CONF_ARITHMETIC = 0.45
CONF_UNKNOWN = 0.2


@dataclass
class RuleMatch:
    misconception_id: str
    confidence: float
    evidence: str = ""


MatchList = list[RuleMatch]
Mutator = Callable[[sp.Basic], Iterator[tuple[sp.Basic, str]]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_at_nodes(expr: sp.Basic, mutator: Mutator) -> list[tuple[sp.Basic, str]]:
    """Every variant of expr obtained by replacing ONE subnode via the mutator."""
    out: list[tuple[sp.Basic, str]] = []
    for node in sp.preorder_traversal(expr):
        try:
            produced = list(mutator(node))
        except Exception:  # noqa: BLE001
            continue
        for new, rule_id in produced:
            if new is None:
                continue
            try:
                cand = new if node == expr else expr.xreplace({node: new})
            except Exception:  # noqa: BLE001
                continue
            out.append((cand, rule_id))
    return out


def _terms(expr: sp.Basic) -> list[sp.Basic]:
    return list(expr.args) if isinstance(expr, sp.Add) else [expr]


def _split_factor_and_sum(node: sp.Basic):
    """Split a Mul into (outer factor, inner sum) when it looks like k*(a+b+...)."""
    if not isinstance(node, sp.Mul):
        return []
    args = list(node.args)
    results = []
    for i, a in enumerate(args):
        if isinstance(a, sp.Add):
            rest = sp.Mul(*(args[:i] + args[i + 1:]))
            if rest != 1:
                results.append((rest, a))
    return results


def _perfect_sqrt(e: sp.Basic) -> Optional[sp.Basic]:
    """Return the square root when e is a perfect square, otherwise None."""
    e = sp.sympify(e)
    if e.is_Number:
        if e.is_negative:
            return None
        r = sp.sqrt(e)
        return r if r.is_Rational else None
    if isinstance(e, sp.Pow) and e.exp.is_Integer and e.exp > 0 and e.exp % 2 == 0:
        return sp.Pow(e.base, e.exp // 2)
    if isinstance(e, sp.Mul):
        parts = [_perfect_sqrt(a) for a in e.args]
        if all(p is not None for p in parts):
            return sp.Mul(*parts)
    return None


# ---------------------------------------------------------------------------
# Expression-level rules, each yielding (simulated result, misconception id)
# ---------------------------------------------------------------------------

def _is_division(outer: sp.Basic) -> bool:
    """Treat 1/3 or 1/k as division rather than distributive multiplication."""
    outer = sp.sympify(outer)
    if isinstance(outer, sp.Pow) and outer.exp.is_negative:
        return True
    if outer.is_Rational and abs(outer) < 1:
        return True
    return False


def mut_distribute_partial(node):
    """3(x+2) -> 3x+2 ; -(x+2) -> -x+2 ; (3x+6)/3 -> x+6"""
    for outer, inner in _split_factor_and_sum(node):
        if outer == -1:
            rid = "ALG-DIST-02"
        elif _is_division(outer):
            rid = "ALG-FRAC-01"
        else:
            rid = "ALG-DIST-01"
        terms = list(inner.args)
        for i in range(len(terms)):
            kept = [t for j, t in enumerate(terms) if j != i]
            yield sp.Add(outer * terms[i], *kept), rid


def mut_pow_of_sum(node):
    """(x+2)^2 -> x^2+4 ; (x-2)^2 -> x^2-4 ; (x+y)^3 -> x^3+y^3"""
    if not (isinstance(node, sp.Pow) and isinstance(node.base, sp.Add)):
        return
    n = node.exp
    if not (n.is_Integer and n >= 2):
        return
    terms = [sp.sympify(t) for t in node.base.args]
    has_negative = any(t.could_extract_minus_sign() for t in terms)
    if n >= 3:
        rid = "ALG-POW-04"
    else:
        rid = "ALG-EXP-02" if has_negative else "ALG-EXP-01"

    yield sp.Add(*[sp.Pow(t, n) for t in terms]), rid
    if has_negative:
        signed = []
        for t in terms:
            if t.could_extract_minus_sign():
                signed.append(-sp.Pow(-t, n))
            else:
                signed.append(sp.Pow(t, n))
        yield sp.Add(*signed), rid


def mut_pow_add_exponents(node):
    """x^2 + x^3 -> x^5"""
    if not isinstance(node, sp.Add):
        return
    args = list(node.args)
    for i in range(len(args)):
        for j in range(i + 1, len(args)):
            b1, e1 = sp.sympify(args[i]).as_base_exp()
            b2, e2 = sp.sympify(args[j]).as_base_exp()
            if b1 == b2 and b1.free_symbols:
                rest = [t for k, t in enumerate(args) if k not in (i, j)]
                yield sp.Add(sp.Pow(b1, e1 + e2), *rest), "ALG-POW-01"


def mut_pow_multiply_exponents(node):
    """x^2 * x^3 -> x^6"""
    if not isinstance(node, sp.Mul):
        return
    args = list(node.args)
    for i in range(len(args)):
        for j in range(i + 1, len(args)):
            b1, e1 = sp.sympify(args[i]).as_base_exp()
            b2, e2 = sp.sympify(args[j]).as_base_exp()
            if b1 == b2 and b1.free_symbols and e1 != 1 and e2 != 1:
                rest = [t for k, t in enumerate(args) if k not in (i, j)]
                yield sp.Mul(sp.Pow(b1, e1 * e2), *rest), "ALG-POW-02"


def mut_pow_of_pow(node):
    """SymPy folds (x^2)^3 into x^6, so simulate the student writing x^5."""
    if isinstance(node, sp.Pow) and node.exp.is_Integer and node.exp >= 4:
        n = int(node.exp)
        for p in range(2, int(n ** 0.5) + 1):
            if n % p == 0:
                yield sp.Pow(node.base, p + n // p), "ALG-POW-03"


def mut_sqrt_of_sum(node):
    """sqrt(x+y) -> sqrt(x)+sqrt(y)"""
    if isinstance(node, sp.Pow) and node.exp == sp.Rational(1, 2):
        if isinstance(node.base, sp.Add):
            yield sp.Add(*[sp.sqrt(t) for t in node.base.args]), "ALG-RAD-01"


def mut_sqrt_square(node):
    """sqrt(x^2) -> x"""
    if isinstance(node, sp.Pow) and node.exp == sp.Rational(1, 2):
        base = node.base
        if isinstance(base, sp.Pow) and base.exp == 2:
            yield base.base, "ALG-RAD-02"


def mut_cancel_term(node):
    """(x+2)/x -> 2 ; (3x+6)/3 -> x+6"""
    try:
        num, den = sp.sympify(node).as_numer_denom()
    except Exception:  # noqa: BLE001
        return
    if den == 1 or not isinstance(num, sp.Add):
        return
    terms = list(num.args)
    for i, t in enumerate(terms):
        rest = [u for j, u in enumerate(terms) if j != i]
        if sp.simplify(t - den) == 0:
            yield sp.Add(*rest), "ALG-FRAC-01"
        try:
            ratio = sp.cancel(t / den)
            if ratio.is_polynomial() and sp.simplify(ratio * den - t) == 0:
                yield sp.Add(ratio, *rest), "ALG-FRAC-01"
        except Exception:  # noqa: BLE001
            continue


def mut_add_fractions_wrong(node):
    """a/b + c/d -> (a+c)/(b+d) ; 1/x + 1/y -> 1/(x+y)"""
    if not isinstance(node, sp.Add):
        return
    args = list(node.args)
    for i in range(len(args)):
        for j in range(i + 1, len(args)):
            n1, d1 = sp.sympify(args[i]).as_numer_denom()
            n2, d2 = sp.sympify(args[j]).as_numer_denom()
            if d1 == 1 and d2 == 1:
                continue
            rest = [t for k, t in enumerate(args) if k not in (i, j)]
            yield sp.Add((n1 + n2) / (d1 + d2), *rest), "ALG-FRAC-02"
            if n1 == 1 and n2 == 1:
                yield sp.Add(sp.Integer(1) / (d1 + d2), *rest), "ALG-FRAC-03"


def mut_diff_of_squares(node):
    """x^2-9 -> (x-3)^2 hoac (x+3)^2"""
    if not isinstance(node, sp.Add) or len(node.args) != 2:
        return
    a, b = [sp.sympify(t) for t in node.args]
    for p, q in ((a, b), (b, a)):
        if not q.could_extract_minus_sign():
            continue
        ra, rb = _perfect_sqrt(p), _perfect_sqrt(-q)
        if ra is None or rb is None:
            continue
        yield sp.Pow(ra - rb, 2), "ALG-FACT-01"
        yield sp.Pow(ra + rb, 2), "ALG-FACT-01"


EXPR_MUTATORS: list[Mutator] = [
    mut_distribute_partial,
    mut_pow_of_sum,
    mut_pow_add_exponents,
    mut_pow_multiply_exponents,
    mut_sqrt_of_sum,
    mut_sqrt_square,
    mut_cancel_term,
    mut_add_fractions_wrong,
    mut_diff_of_squares,
    mut_pow_of_pow,
]


# ---------------------------------------------------------------------------
# Equation-level rules
# ---------------------------------------------------------------------------

def mut_move_without_sign(eq: sp.Eq):
    """x+3=5 -> x=5+3"""
    lhs, rhs = eq.lhs, eq.rhs
    for t in _terms(lhs):
        yield sp.Eq(sp.expand(lhs - t), sp.expand(rhs + t)), "ALG-SIGN-01"
    for t in _terms(rhs):
        yield sp.Eq(sp.expand(lhs + t), sp.expand(rhs - t)), "ALG-SIGN-01"


def mut_partial_sign_flip(eq: sp.Eq):
    """-x+2=5 -> x+2=-5"""
    lhs, rhs = eq.lhs, eq.rhs
    lterms = _terms(lhs)
    if len(lterms) > 1:
        for i in range(len(lterms)):
            flipped = [t if j == i else -t for j, t in enumerate(lterms)]
            yield sp.Eq(sp.expand(sp.Add(*flipped)), sp.expand(-rhs)), "ALG-SIGN-02"
    rterms = _terms(rhs)
    if len(rterms) > 1:
        for i in range(len(rterms)):
            flipped = [t if j == i else -t for j, t in enumerate(rterms)]
            yield sp.Eq(sp.expand(-lhs), sp.expand(sp.Add(*flipped))), "ALG-SIGN-02"


def mut_partial_scaling(eq: sp.Eq):
    """2x+4=10 -> x+4=5"""
    lhs, rhs = eq.lhs, eq.rhs
    terms = _terms(lhs)
    if len(terms) < 2:
        return
    factors = set()
    for t in terms + _terms(rhs):
        c, _ = sp.sympify(t).as_coeff_Mul()
        if c.is_Number and abs(c) not in (0, 1):
            factors.add(abs(c))
    for k in factors:
        for i, t in enumerate(terms):
            rest = [u for j, u in enumerate(terms) if j != i]
            yield sp.Eq(sp.expand(sp.Add(t / k, *rest)), sp.expand(rhs / k)), "ALG-EQ-03"
            yield sp.Eq(sp.expand(sp.Add(t * k, *rest)), sp.expand(rhs * k)), "ALG-EQ-03"


def mut_product_rule_misuse(eq: sp.Eq):
    """(x-1)(x-2)=6 -> x-1=6"""
    lhs, rhs = sp.sympify(eq.lhs), sp.sympify(eq.rhs)
    if rhs == 0 or not isinstance(lhs, sp.Mul):
        return
    for f in lhs.args:
        if f.free_symbols:
            yield sp.Eq(f, rhs), "ALG-EQ-04"


def mut_drop_negative_root(eq: sp.Eq, symbol: Optional[sp.Symbol]):
    """x^2=9 -> x=3"""
    if symbol is None:
        return
    lhs, rhs = sp.sympify(eq.lhs), sp.sympify(eq.rhs)
    if isinstance(lhs, sp.Pow) and lhs.base == symbol and lhs.exp == 2:
        if rhs.is_number and rhs.is_positive:
            yield sp.Eq(symbol, sp.sqrt(rhs)), "ALG-QUAD-01"


EQ_MUTATORS = [
    mut_move_without_sign,
    mut_partial_sign_flip,
    mut_partial_scaling,
    mut_product_rule_misuse,
]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _diff(obj: sp.Basic) -> sp.Basic:
    return sp.expand(obj.lhs - obj.rhs) if isinstance(obj, sp.Eq) else sp.expand(obj)


def _match_tier(cand: sp.Basic, curr: sp.Basic) -> Optional[int]:
    """1 = exact match, 2 = match after constant scaling, None = no match."""
    try:
        dc, dt = _diff(cand), _diff(curr)
    except Exception:  # noqa: BLE001
        return None
    if expr_equivalent(dc, dt):
        return 1
    if isinstance(cand, sp.Eq) and isinstance(curr, sp.Eq):
        try:
            if dt != 0:
                ratio = sp.simplify(dc / dt)
                if ratio.is_number and ratio != 0:
                    return 2
        except Exception:  # noqa: BLE001
            return None
    return None


def _confidence(tier: int) -> float:
    return {1: CONF_TIER1, 2: CONF_TIER2, 3: CONF_SOLUTION_SET}.get(tier, CONF_UNKNOWN)


def _dedupe(items: list) -> list:
    out = []
    for it in items:
        if it is None:
            continue
        if not any(it is o or it == o for o in out):
            out.append(it)
    return out


def _expr_candidates(expr: sp.Basic) -> list[tuple[sp.Basic, str]]:
    out: list[tuple[sp.Basic, str]] = []
    for mutator in EXPR_MUTATORS:
        out.extend(_apply_at_nodes(expr, mutator))
    return out


def detect(prev, curr, symbol: Optional[sp.Symbol] = None,
           relation: str = "not_equivalent",
           prev_struct=None) -> MatchList:
    """Identify the misconception behind one invalid transformation.

    prev, curr : simplified SymPy objects for the previous and current step.
    prev_struct: structure-preserving parse of the previous step (evaluate=False),
                 needed because SymPy folds 3*(x+2) into 3x+6 on sight.
    relation   : verdict from the symbolic checker ("lost_roots", "extra_roots", ...).
    """
    best: dict[str, tuple[int, str]] = {}

    def record(mid: str, tier: int, evidence: str):
        if mid not in best or tier < best[mid][0]:
            best[mid] = (tier, evidence)

    prev_is_eq = isinstance(prev, sp.Eq)
    curr_is_eq = isinstance(curr, sp.Eq)
    sources = _dedupe([prev, prev_struct])

    if prev_is_eq and curr_is_eq:
        for src in sources:
            if not isinstance(src, sp.Eq):
                continue
            for cand, rid in mut_drop_negative_root(src, symbol):
                tier = _match_tier(cand, curr)
                if tier:
                    record(rid, tier, f"simulated: {sp.sstr(cand)}")
            for mutator in EQ_MUTATORS:
                try:
                    produced = list(mutator(src))
                except Exception:  # noqa: BLE001
                    continue
                for cand, rid in produced:
                    tier = _match_tier(cand, curr)
                    if tier:
                        record(rid, tier, f"simulated: {sp.sstr(cand)}")

            # Expression-level slip on one side while the other side is untouched
            for side in ("lhs", "rhs"):
                other = "rhs" if side == "lhs" else "lhs"
                if not expr_equivalent(getattr(src, other), getattr(curr, other)):
                    continue
                for cand, rid in _expr_candidates(getattr(src, side)):
                    if expr_equivalent(cand, getattr(curr, side)):
                        record(rid, 1, f"simulated {side}: {sp.sstr(cand)}")

        if relation == "lost_roots":
            record("ALG-EQ-01", 3, "solution set shrank at this step")
        elif relation == "extra_roots":
            record("ALG-EQ-02", 3, "a root appeared that the previous step did not have")

    if not prev_is_eq and not curr_is_eq:
        for src in sources:
            for cand, rid in _expr_candidates(src):
                if expr_equivalent(cand, curr):
                    record(rid, 1, f"simulated: {sp.sstr(cand)}")

    matches = [RuleMatch(mid, _confidence(tier), ev) for mid, (tier, ev) in best.items()]

    if not matches:
        slip = _arithmetic_slip(prev, curr, symbol)
        if slip:
            matches.append(RuleMatch("ALG-CALC-01", CONF_ARITHMETIC, slip))

    if not matches:
        try:
            diff = sp.simplify(_diff(prev) - _diff(curr))
            if diff.is_number and diff != 0:
                matches.append(
                    RuleMatch("ALG-CALC-01", CONF_ARITHMETIC,
                              f"constant discrepancy: {sp.sstr(diff)}")
                )
        except Exception:  # noqa: BLE001
            pass

    if not matches:
        matches.append(RuleMatch("ALG-UNK-00", CONF_UNKNOWN, "no rule in the taxonomy matched"))

    matches.sort(key=lambda m: -m.confidence)
    return matches


def _arithmetic_slip(prev, curr, symbol: Optional[sp.Symbol]) -> Optional[str]:
    """Test whether the step is wrong only because ONE number was miscomputed.

    Method: replace each constant in the student's step with an unknown k, solve
    for the value of k that would make the step valid, then verify. If such a
    value exists, the transformation rule was right and only the arithmetic slipped.
    """
    from .symbolic_checker import eq_relation

    numbers = [n for n in curr.atoms(sp.Number) if n not in (0, 1, -1)]
    if not numbers:
        return None
    k = sp.Dummy("k")

    if isinstance(prev, sp.Eq) and isinstance(curr, sp.Eq):
        if symbol is None:
            return None
        try:
            roots = sp.solve(sp.Eq(prev.lhs, prev.rhs), symbol)
        except Exception:  # noqa: BLE001
            return None
        if not roots or any(getattr(r, "free_symbols", set()) for r in roots):
            return None
        anchor = roots[0]
        for n in numbers:
            cand = sp.Eq(curr.lhs.subs(n, k), curr.rhs.subs(n, k))
            try:
                sols = sp.solve(sp.Eq(cand.lhs - cand.rhs, 0).subs(symbol, anchor), k)
            except Exception:  # noqa: BLE001
                continue
            for v in sols:
                if getattr(v, "free_symbols", set()) or v == n:
                    continue
                fixed = sp.Eq(curr.lhs.subs(n, v), curr.rhs.subs(n, v))
                if eq_relation(prev, fixed, symbol) == "equivalent":
                    return f"rule applied correctly, arithmetic slip: {sp.sstr(n)} should be {sp.sstr(v)}"
        return None

    if not isinstance(prev, sp.Eq) and not isinstance(curr, sp.Eq):
        syms = sorted(prev.free_symbols | curr.free_symbols, key=lambda s: s.name)
        probe = {s: sp.Integer(i + 2) for i, s in enumerate(syms)}
        for n in numbers:
            cand = curr.subs(n, k)
            try:
                sols = sp.solve(sp.Eq(cand.subs(probe), prev.subs(probe)), k)
            except Exception:  # noqa: BLE001
                continue
            for v in sols:
                if getattr(v, "free_symbols", set()) or v == n:
                    continue
                if expr_equivalent(curr.subs(n, v), prev):
                    return f"rule applied correctly, arithmetic slip: {sp.sstr(n)} should be {sp.sstr(v)}"
    return None
