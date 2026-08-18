"""MathLens web API.

Run:  uvicorn web.server:app --reload
Then open http://localhost:8000

The backend does one job: call the engine and return JSON. Every mathematical
decision stays in engine/. The frontend never reasons about maths itself.

Text is returned in both Vietnamese and English as {"vi": ..., "en": ...}, so
switching language in the interface never needs another round trip.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import sympy as sp
from fastapi import Cookie, FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import feedback_engine, storage  # noqa: E402
from engine.parser import parse_solution  # noqa: E402
from engine.step_checker import STATUS_ERROR, STATUS_PARSE_ERROR, analyze  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
PROBLEMS_PATH = ROOT / "data" / "problems.csv"
SESSION_COOKIE = "mathlens_session"

app = FastAPI(title="MathLens API", version="0.1")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_latex(step) -> str:
    """LaTeX for one step, preferring the form the student actually wrote."""
    obj = step.struct if getattr(step, "struct", None) is not None else step.obj
    if obj is None:
        return ""
    try:
        out = sp.latex(obj)
    except Exception:  # noqa: BLE001
        return ""
    out = re.sub(r"(?<![\d.])1 \\frac", r"\\frac", out)   # drop redundant coefficient 1
    return out


def session_id_from(cookie: Optional[str]) -> str:
    return cookie if cookie else storage.new_session_id()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    solution: str
    problem_id: str = ""
    topic: str = ""


class DiagnosticRequest(BaseModel):
    attempt_id: str
    answer: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/problems")
def problems() -> list[dict]:
    df = pd.read_csv(PROBLEMS_PATH)
    return df[["problem_id", "topic", "subtopic", "difficulty", "question"]].to_dict("records")


@app.get("/api/taxonomy")
def taxonomy() -> list[dict]:
    return [
        m.bilingual()
        for m in feedback_engine.load_taxonomy().values()
        if m.id != "ALG-UNK-00"
    ]


@app.post("/api/analyze")
def analyze_solution(req: AnalyzeRequest, response: Response,
                     mathlens_session: Optional[str] = Cookie(default=None)) -> dict:
    session = session_id_from(mathlens_session)
    result = analyze(req.solution)
    fb = feedback_engine.build_feedback(result)
    parsed = parse_solution(req.solution)

    steps = []
    for i, s in enumerate(result.steps):
        steps.append({
            "index": s.index + 1,
            "raw": s.raw,
            "latex": to_latex(parsed[i]) if i < len(parsed) else "",
            "status": s.status,
            "error_code": s.error_code,
            "detail": s.note,
            "relation": s.relation,
            "is_first_error": s.status == STATUS_ERROR and s.index == result.first_error_index,
        })

    attempt_id = storage.log_attempt(
        session, req.solution, result, problem_id=req.problem_id, topic=req.topic
    )
    response.set_cookie(SESSION_COOKIE, session, max_age=60 * 60 * 24 * 30, samesite="lax")

    mis = fb.get("misconception")
    return {
        "attempt_id": attempt_id,
        "session_id": session,
        "steps": steps,
        "first_error_step": None if result.first_error_index is None
        else result.first_error_index + 1,
        "headline": fb["headline"],
        "detail": fb["detail"],
        "has_parse_error": any(s["status"] == STATUS_PARSE_ERROR for s in steps),
        "misconception": None if mis is None else mis.bilingual(),
        "diagnostic_question": fb["diagnostic_question"],
        "evidence": [
            {"id": m.misconception_id, "confidence": round(m.confidence, 2), "note": m.evidence}
            for m in result.ranked
        ],
    }


@app.post("/api/diagnostic")
def check_diagnostic(req: DiagnosticRequest) -> dict:
    """Grade the diagnostic answer server side so the key never reaches the browser."""
    attempt = storage.get_attempt(req.attempt_id)
    if attempt is None or not attempt.get("misconception_id"):
        return {"status": "unknown"}
    mis = feedback_engine.get(attempt["misconception_id"])
    if mis is None or not mis.diagnostic_answer:
        return {"status": "unknown"}

    ok = feedback_engine.check_diagnostic(req.answer, mis.diagnostic_answer)
    if ok is None:
        return {"status": "unreadable"}
    storage.set_diagnostic_result(req.attempt_id, ok)
    return {"status": "correct" if ok else "incorrect"}


@app.get("/api/profile")
def profile(mathlens_session: Optional[str] = Cookie(default=None)) -> dict:
    if not mathlens_session:
        return {"total_attempts": 0, "clean_attempts": 0, "by_misconception": []}
    data = storage.profile(mathlens_session)
    tax = feedback_engine.load_taxonomy()
    for item in data["by_misconception"]:
        mis = tax.get(item["id"])
        item["name"] = {"vi": mis.name_vi, "en": mis.name_en} if mis else {"vi": item["id"], "en": item["id"]}
        item["group"] = {"vi": mis.group, "en": mis.group_en} if mis else {"vi": "", "en": ""}
    return data
