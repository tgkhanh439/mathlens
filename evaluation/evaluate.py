"""Evaluate MathLens on a fixed test set.

Run:  python evaluation/evaluate.py [path_to_jsonl]

Reports:
  - accuracy of FIRST INVALID STEP detection, including correct solutions
  - misconception accuracy over the labelled samples
  - per-label precision, recall, F1 and the macro-F1
  - the list of mispredicted samples, for error analysis
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.step_checker import analyze  # noqa: E402

DEFAULT_DATA = ROOT / "data" / "seed_samples.jsonl"
OUT_DIR = ROOT / "research"


def load_samples(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main(path: Path = DEFAULT_DATA) -> dict:
    samples = load_samples(path)
    step_hit = 0
    mis_total = 0
    mis_hit = 0
    mis_topk = 0
    errors: list[dict] = []
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)

    for s in samples:
        result = analyze(s["student_solution"])
        pred_step = None if result.first_error_index is None else result.first_error_index + 1
        gold_step = s.get("first_incorrect_step")
        pred_mis = result.misconception_id
        gold_mis = s.get("misconception_id")
        topk = [m.misconception_id for m in result.ranked[:3]]

        if pred_step == gold_step:
            step_hit += 1
        else:
            errors.append({
                "sample_id": s["sample_id"], "kind": "first step",
                "gold": gold_step, "pred": pred_step,
                "solution": s["student_solution"].replace("\n", " | "),
            })

        if gold_mis:
            mis_total += 1
            if pred_mis == gold_mis:
                mis_hit += 1
                tp[gold_mis] += 1
            else:
                fn[gold_mis] += 1
                if pred_mis:
                    fp[pred_mis] += 1
                errors.append({
                    "sample_id": s["sample_id"], "kind": "misconception",
                    "gold": gold_mis, "pred": pred_mis,
                    "solution": s["student_solution"].replace("\n", " | "),
                })
            if gold_mis in topk:
                mis_topk += 1

    labels = sorted(set(tp) | set(fp) | set(fn))
    per_label = {}
    for lb in labels:
        per_label[lb] = prf(tp[lb], fp[lb], fn[lb])
    macro_f1 = sum(v[2] for v in per_label.values()) / len(per_label) if per_label else 0.0

    n = len(samples)
    report = {
        "n_samples": n,
        "first_error_accuracy": step_hit / n if n else 0.0,
        "misconception_accuracy": mis_hit / mis_total if mis_total else 0.0,
        "misconception_top3": mis_topk / mis_total if mis_total else 0.0,
        "macro_f1": macro_f1,
        "per_label": per_label,
        "errors": errors,
    }

    print(f"Samples                       : {n}")
    print(f"First invalid step correct    : {report['first_error_accuracy']:.1%} ({step_hit}/{n})")
    print(f"Misconception correct (top-1) : {report['misconception_accuracy']:.1%} ({mis_hit}/{mis_total})")
    print(f"Misconception correct (top-3) : {report['misconception_top3']:.1%}")
    print(f"Macro-F1                      : {macro_f1:.3f}")
    print()
    print(f"{'Label':<16}{'P':>8}{'R':>8}{'F1':>8}{'support':>9}")
    for lb, (p, r, f) in per_label.items():
        print(f"{lb:<16}{p:>8.2f}{r:>8.2f}{f:>8.2f}{tp[lb] + fn[lb]:>9}")

    if errors:
        print("\nMispredicted samples:")
        for e in errors:
            print(f"  [{e['sample_id']}] {e['kind']}: gold={e['gold']} pred={e['pred']} | {e['solution']}")
    else:
        print("\nNo mispredictions on this test set.")

    OUT_DIR.mkdir(exist_ok=True)
    with open(OUT_DIR / "evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport written to: {OUT_DIR / 'evaluation_report.json'}")
    return report


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA)
