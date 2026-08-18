"""Taxonomy loading, feedback generation and diagnostic-answer grading.

Feedback policy: never hand over the full worked solution. Report the first
invalid step, name the misconception, give one short explanation, and ask a
diagnostic question on the same concept to check whether the student has
actually fixed the underlying idea.

Every user-facing string exists in Vietnamese and English. The engine returns
both and lets the interface decide which one to show, so switching language
never requires a second analysis run.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import sympy as sp

from .parser import parse_step
from .symbolic_checker import expr_equivalent

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAXONOMY_PATH = DATA_DIR / "misconceptions.csv"

LANGUAGES = ("vi", "en")


@dataclass
class Misconception:
    id: str
    group: str
    group_en: str
    topic: str
    name_vi: str
    name_en: str
    definition_vi: str
    definition_en: str
    wrong_example: str
    correct_example: str
    feedback_vi: str
    feedback_en: str
    diagnostic_question: str
    diagnostic_question_en: str
    diagnostic_answer: str

    def bilingual(self) -> dict:
        """Shape used by the API: one object per field, keyed by language."""
        return {
            "id": self.id,
            "group": {"vi": self.group, "en": self.group_en},
            "name": {"vi": self.name_vi, "en": self.name_en},
            "definition": {"vi": self.definition_vi, "en": self.definition_en},
            "feedback": {"vi": self.feedback_vi, "en": self.feedback_en},
            "diagnostic_question": {
                "vi": self.diagnostic_question,
                "en": self.diagnostic_question_en,
            },
            "wrong_example": self.wrong_example,
            "correct_example": self.correct_example,
        }


# Sentences the engine itself produces, as opposed to taxonomy content.
MESSAGES = {
    "all_valid": {
        "vi": "Các bước biến đổi đều hợp lệ.",
        "en": "Every step is a valid transformation.",
    },
    "all_valid_detail": {
        "vi": "Hệ thống không phát hiện bước nào không tương đương với bước trước.",
        "en": "No step was found that fails to be equivalent to the one before it.",
    },
    "first_error": {
        "vi": "Bước sai đầu tiên: bước {n}.",
        "en": "First invalid step: step {n}.",
    },
    "not_equivalent": {
        "vi": "Bước này không tương đương với bước trước đó.",
        "en": "This step is not equivalent to the previous one.",
    },
}


@lru_cache(maxsize=1)
def load_taxonomy(path: str | None = None) -> dict[str, Misconception]:
    p = Path(path) if path else TAXONOMY_PATH
    out: dict[str, Misconception] = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["id"]] = Misconception(
                id=row["id"],
                group=row["group"],
                group_en=row["group_en"],
                topic=row["topic"],
                name_vi=row["name_vi"],
                name_en=row["name_en"],
                definition_vi=row["definition_vi"],
                definition_en=row["definition_en"],
                wrong_example=row["wrong_example"],
                correct_example=row["correct_example"],
                feedback_vi=row["feedback_vi"],
                feedback_en=row["feedback_en"],
                diagnostic_question=row["diagnostic_question"],
                diagnostic_question_en=row["diagnostic_question_en"],
                diagnostic_answer=row["diagnostic_answer"],
            )
    return out


def get(mid: str) -> Optional[Misconception]:
    return load_taxonomy().get(mid)


def build_feedback(result) -> dict:
    """Turn an AnalysisResult into a feedback package.

    Text fields are dicts of {"vi": ..., "en": ...}.
    """
    if not result.has_error:
        return {
            "status": "correct",
            "headline": dict(MESSAGES["all_valid"]),
            "detail": dict(MESSAGES["all_valid_detail"]),
            "misconception": None,
            "diagnostic_question": {"vi": "", "en": ""},
            "diagnostic_answer": "",
        }

    step_no = result.first_error_index + 1
    headline = {lang: MESSAGES["first_error"][lang].format(n=step_no) for lang in LANGUAGES}
    mis = get(result.misconception_id) if result.misconception_id else None

    if mis is None:
        return {
            "status": "error",
            "headline": headline,
            "detail": dict(MESSAGES["not_equivalent"]),
            "misconception": None,
            "diagnostic_question": {"vi": "", "en": ""},
            "diagnostic_answer": "",
        }

    return {
        "status": "error",
        "headline": headline,
        "detail": {"vi": mis.feedback_vi, "en": mis.feedback_en},
        "misconception": mis,
        "diagnostic_question": {
            "vi": mis.diagnostic_question,
            "en": mis.diagnostic_question_en,
        },
        "diagnostic_answer": mis.diagnostic_answer,
    }


def _answer_values(text: str) -> list:
    """Split an answer such as "x=4 or x=-4" into SymPy values."""
    cleaned = (
        text.replace("hoặc", "|")
        .replace("hoac", "|")
        .replace(";", "|")
        .replace(" or ", "|")
    )
    parts = [p.strip() for p in cleaned.split("|") if p.strip()]
    values = []
    for p in parts:
        st = parse_step(p)
        if not st.ok:
            continue
        values.append(st.obj.rhs if st.is_equation else st.obj)
    return values


def check_diagnostic(student_answer: str, expected_answer: str) -> Optional[bool]:
    """Grade a diagnostic answer symbolically rather than by string comparison."""
    if not expected_answer.strip() or not student_answer.strip():
        return None
    got = _answer_values(student_answer)
    want = _answer_values(expected_answer)
    if not got or not want:
        return None
    if len(got) != len(want):
        return False
    used = set()
    for w in want:
        found = False
        for i, g in enumerate(got):
            if i in used:
                continue
            try:
                if expr_equivalent(sp.sympify(g), sp.sympify(w)):
                    used.add(i)
                    found = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not found:
            return False
    return True
