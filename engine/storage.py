"""Anonymous logging of analysis results (SQLite).

Only a random session code is stored. No names, no personal details.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Many free hosts only allow writes to /tmp, so the DB path comes from the environment.
DB_PATH = Path(
    os.environ.get("MATHLENS_DB", Path(__file__).resolve().parent.parent / "data" / "mathlens.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id        TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    problem_id        TEXT,
    topic             TEXT,
    solution_text     TEXT NOT NULL,
    n_steps           INTEGER,
    first_error_step  INTEGER,
    misconception_id  TEXT,
    confidence        REAL,
    ranked_json       TEXT,
    diagnostic_correct INTEGER
);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_mis ON attempts(misconception_id);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    return conn


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def log_attempt(session_id: str, solution_text: str, result,
                problem_id: str = "", topic: str = "",
                db_path: Path | str = DB_PATH) -> str:
    attempt_id = uuid.uuid4().hex
    ranked = [
        {"id": m.misconception_id, "confidence": m.confidence, "evidence": m.evidence}
        for m in getattr(result, "ranked", [])
    ]
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO attempts (attempt_id, session_id, created_at, problem_id, topic,
                                     solution_text, n_steps, first_error_step,
                                     misconception_id, confidence, ranked_json, diagnostic_correct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                session_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                problem_id,
                topic,
                solution_text,
                len(result.steps),
                None if result.first_error_index is None else result.first_error_index + 1,
                result.misconception_id,
                result.confidence,
                json.dumps(ranked, ensure_ascii=False),
                None,
            ),
        )
    return attempt_id


def set_diagnostic_result(attempt_id: str, correct: Optional[bool],
                          db_path: Path | str = DB_PATH) -> None:
    if correct is None:
        return
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE attempts SET diagnostic_correct=? WHERE attempt_id=?",
            (1 if correct else 0, attempt_id),
        )


def profile(session_id: str, db_path: Path | str = DB_PATH) -> dict:
    """Student profile: recurring error groups and how often feedback fixed them."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT misconception_id, COUNT(*) AS n,
                      SUM(CASE WHEN diagnostic_correct=1 THEN 1 ELSE 0 END) AS fixed,
                      SUM(CASE WHEN diagnostic_correct IS NOT NULL THEN 1 ELSE 0 END) AS answered
               FROM attempts
               WHERE session_id=? AND misconception_id IS NOT NULL
               GROUP BY misconception_id ORDER BY n DESC""",
            (session_id,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        clean = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE session_id=? AND first_error_step IS NULL",
            (session_id,),
        ).fetchone()[0]
    return {
        "total_attempts": total,
        "clean_attempts": clean,
        "by_misconception": [
            {"id": r[0], "count": r[1], "fixed": r[2] or 0, "answered": r[3] or 0}
            for r in rows
        ],
    }


def get_attempt(attempt_id: str, db_path: Path | str = DB_PATH) -> Optional[dict]:
    """Look up one attempt, used when grading a diagnostic answer server side."""
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT attempt_id, session_id, misconception_id, first_error_step
               FROM attempts WHERE attempt_id=?""",
            (attempt_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "attempt_id": row[0],
        "session_id": row[1],
        "misconception_id": row[2],
        "first_error_step": row[3],
    }
