"""Walk a solution step by step and locate the FIRST INVALID STEP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sympy as sp

from . import rule_engine
from .parser import ParsedStep, main_symbol, parse_solution, parse_step
from .symbolic_checker import eq_relation, expr_equivalent

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_PARSE_ERROR = "parse_error"
STATUS_UNCHECKED = "unchecked"
STATUS_AFTER_ERROR = "after_error"

ML_FALLBACK_THRESHOLD = 0.5   # below this confidence the ML layer is consulted
_CLASSIFIER = None
_CLASSIFIER_LOADED = False


def _get_classifier():
    global _CLASSIFIER, _CLASSIFIER_LOADED
    if not _CLASSIFIER_LOADED:
        _CLASSIFIER_LOADED = True
        try:
            from .misconception_classifier import MisconceptionClassifier
            _CLASSIFIER = MisconceptionClassifier.load()
        except Exception:  # noqa: BLE001
            _CLASSIFIER = None
    return _CLASSIFIER


@dataclass
class StepResult:
    index: int
    raw: str
    pretty: str
    status: str
    relation: str = ""
    note: str = ""
    error_code: str = ""
    matches: list = field(default_factory=list)


@dataclass
class AnalysisResult:
    steps: list[StepResult]
    first_error_index: Optional[int] = None
    misconception_id: Optional[str] = None
    confidence: float = 0.0
    ranked: list = field(default_factory=list)
    final_answer_correct: Optional[bool] = None
    symbol: Optional[sp.Symbol] = None

    @property
    def has_error(self) -> bool:
        return self.first_error_index is not None


def _compare(prev: ParsedStep, curr: ParsedStep, symbol) -> tuple[bool, str]:
    """Return (is_valid, relation)."""
    if prev.is_equation and curr.is_equation:
        rel = eq_relation(prev.obj, curr.obj, symbol)
        return rel in ("equivalent", "unknown"), rel
    if not prev.is_equation and not curr.is_equation:
        ok = expr_equivalent(prev.obj, curr.obj)
        return ok, "equivalent" if ok else "not_equivalent"
    return True, "unchecked"


def analyze(solution_text: str, correct_answer: Optional[str] = None) -> AnalysisResult:
    """Analyse a whole solution, one step per line."""
    steps = parse_solution(solution_text)
    symbol = main_symbol([s for s in steps if s.ok])
    results: list[StepResult] = []
    first_error: Optional[int] = None
    ranked: list = []

    prev_valid: Optional[ParsedStep] = None

    for i, st in enumerate(steps):
        if not st.ok:
            results.append(StepResult(
                i, st.raw, st.raw, STATUS_PARSE_ERROR,
                note=st.error or "", error_code=st.error_code or "unparsable",
            ))
            continue

        if prev_valid is None:
            results.append(StepResult(i, st.raw, st.pretty(), STATUS_OK))
            prev_valid = st
            continue

        ok, rel = _compare(prev_valid, st, symbol)

        if ok:
            status = STATUS_AFTER_ERROR if first_error is not None else STATUS_OK
            results.append(StepResult(i, st.raw, st.pretty(), status, relation=rel))
        else:
            matches = rule_engine.detect(
                prev_valid.obj, st.obj, symbol, rel, prev_struct=prev_valid.struct
            )
            matches = _augment_with_ml(matches, prev_valid.obj, st.obj)
            status = STATUS_ERROR
            results.append(
                StepResult(i, st.raw, st.pretty(), status, relation=rel, matches=matches)
            )
            if first_error is None:
                first_error = i
                ranked = matches

        prev_valid = st

    final_ok = None
    if correct_answer:
        final_ok = _check_final(steps, correct_answer, symbol)

    return AnalysisResult(
        steps=results,
        first_error_index=first_error,
        misconception_id=ranked[0].misconception_id if ranked else None,
        confidence=ranked[0].confidence if ranked else 0.0,
        ranked=ranked,
        final_answer_correct=final_ok,
        symbol=symbol,
    )


def _augment_with_ml(matches, prev, curr):
    """Consult the ML layer when the rule engine reaches no confident verdict.

    ML only RANKS suggestions. It never overrides the symbolic right/wrong call.
    """
    if matches and matches[0].confidence >= ML_FALLBACK_THRESHOLD:
        return matches
    clf = _get_classifier()
    if clf is None:
        return matches
    known = {m.misconception_id for m in matches}
    for mid, prob in clf.predict_topk(prev, curr):
        if mid not in known:
            matches.append(rule_engine.RuleMatch(mid, prob, "suggested by the ML model"))
    matches.sort(key=lambda m: -m.confidence)
    return matches


def _check_final(steps: list[ParsedStep], correct_answer: str, symbol) -> Optional[bool]:
    """Compare the final step against the expected answer."""
    valid = [s for s in steps if s.ok]
    if not valid:
        return None
    last = valid[-1]
    expected = parse_step(correct_answer)
    if not expected.ok:
        return None
    try:
        if last.is_equation and expected.is_equation:
            return eq_relation(last.obj, expected.obj, symbol) == "equivalent"
        if last.is_equation and not expected.is_equation:
            return expr_equivalent(last.obj.rhs, expected.obj)
        if not last.is_equation and expected.is_equation:
            return expr_equivalent(last.obj, expected.obj.rhs)
        return expr_equivalent(last.obj, expected.obj)
    except Exception:  # noqa: BLE001
        return None
