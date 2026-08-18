"""Optional ML layer sitting behind the rule engine.

Its only job is to RANK candidate misconceptions when no rule matched.
Symbolic checking plus rules remain the arbiter of right and wrong. The model
is never allowed to call a valid step invalid, or the other way round.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Optional

import sympy as sp

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "misconception_clf.pkl"
DATA_PATH = ROOT / "data" / "seed_samples.jsonl"
MAX_ML_CONFIDENCE = 0.5   # always below the rule engine confidence levels


def step_features(prev: sp.Basic, curr: sp.Basic) -> str:
    """Represent a step pair as a feature string for TF-IDF."""
    def desc(e):
        e = sp.sympify(e)
        heads = sorted({type(n).__name__ for n in sp.preorder_traversal(e)})
        return f"{sp.sstr(e)} || {' '.join(heads)}"

    try:
        d_prev, d_curr = desc(prev), desc(curr)
        if isinstance(prev, sp.Eq) and isinstance(curr, sp.Eq):
            delta = sp.sstr(sp.expand((prev.lhs - prev.rhs) - (curr.lhs - curr.rhs)))
        else:
            delta = sp.sstr(sp.expand(sp.sympify(prev) - sp.sympify(curr)))
    except Exception:  # noqa: BLE001
        return ""
    return f"PREV {d_prev} CURR {d_curr} DELTA {delta}"


class MisconceptionClassifier:
    def __init__(self, pipeline=None, labels: Optional[list] = None):
        self.pipeline = pipeline
        self.labels = labels or []

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> Optional["MisconceptionClassifier"]:
        if not Path(path).exists():
            return None
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            return cls(obj["pipeline"], obj["labels"])
        except Exception:  # noqa: BLE001
            return None

    def predict_topk(self, prev, curr, k: int = 3) -> list[tuple[str, float]]:
        if self.pipeline is None:
            return []
        feats = step_features(prev, curr)
        if not feats:
            return []
        try:
            probs = self.pipeline.predict_proba([feats])[0]
        except Exception:  # noqa: BLE001
            return []
        pairs = sorted(zip(self.pipeline.classes_, probs), key=lambda t: -t[1])[:k]
        return [(lb, min(float(p), MAX_ML_CONFIDENCE)) for lb, p in pairs if p > 0.05]


def train_from_jsonl(data_path: Path = DATA_PATH, model_path: Path = MODEL_PATH) -> dict:
    """Train a TF-IDF plus logistic regression baseline on the labelled dataset."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    from .parser import parse_solution

    X, y = [], []
    with open(data_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gold_step = row.get("first_incorrect_step")
            label = row.get("misconception_id")
            if not gold_step or not label:
                continue
            steps = [s for s in parse_solution(row["student_solution"]) if s.ok]
            if gold_step - 1 >= len(steps) or gold_step < 2:
                continue
            prev, curr = steps[gold_step - 2], steps[gold_step - 1]
            feats = step_features(prev.obj, curr.obj)
            if feats:
                X.append(feats)
                y.append(label)

    if len(set(y)) < 2:
        return {"trained": False, "reason": "not enough distinct labels to train", "n": len(X)}

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1)),
        ("clf", LogisticRegression(max_iter=2000, C=4.0)),
    ])
    pipeline.fit(X, y)

    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump({"pipeline": pipeline, "labels": sorted(set(y))}, f)
    return {"trained": True, "n": len(X), "n_labels": len(set(y)), "path": str(model_path)}


if __name__ == "__main__":
    print(train_from_jsonl())
