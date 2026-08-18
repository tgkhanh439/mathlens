---
title: MathLens
emoji: 🔍
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# MathLens v0.1

A step-by-step analyser for school algebra. It locates the **first invalid step**
in a student's solution, names the **misconception** behind it, and asks a
**diagnostic question** on the same concept to check whether the idea has been fixed.

This is a running implementation of the v1.0 scope from the project plan: parser,
symbolic checker, step checker, rule engine, an ML fallback layer, a bilingual web
interface, a seed dataset and an evaluation harness.

The interface is bilingual, Vietnamese and English, with a switch in the header.
Code comments and documentation are in English; taxonomy content exists in both.

## Run it

```bash
pip install -r requirements-dev.txt
uvicorn web.server:app --reload
```

`requirements.txt` holds only what the running site needs, so free hosting tiers can
install it. `requirements-dev.txt` adds the Streamlit view, the ML layer and evaluation.

Open http://localhost:8000

Three screens: **Grade** (enter a solution, read the marking sheet), **Error
catalogue** (the taxonomy), **Profile** (per-session error statistics).

Deployment is covered in `DEPLOY.md`. Short version: GitHub Pages cannot host this
because the maths runs server side; deploy to Render's free tier from the GitHub
repository, and no domain purchase is needed.

```bash
docker build -t mathlens . && docker run -p 8000:8000 mathlens
```

Tests and evaluation:

```bash
python -m unittest discover -s tests -v
python evaluation/evaluate.py
python -m engine.misconception_classifier   # retrain the ML layer
```

Using the engine directly:

```python
from engine import analyze
r = analyze("3(x+2)=12\n3x+2=12\n3x=10")
print(r.first_error_index + 1, r.misconception_id)   # 2 ALG-DIST-01
```

## Layout

```
mathlens/
├── web/
│   ├── server.py                   # FastAPI: /api/analyze, /api/diagnostic, /api/profile
│   └── static/                     # plain HTML, CSS and JS, no build step
│       ├── i18n.js                 # interface strings for both languages
│       └── app.js                  # rendering and language switching
├── app/streamlit_app.py            # internal Streamlit view for debugging the engine
├── engine/
│   ├── parser.py                   # input normalisation; keeps a structure-preserving parse
│   ├── symbolic_checker.py         # expression equivalence, solution-set comparison
│   ├── step_checker.py             # locates the first invalid step
│   ├── rule_engine.py              # simulates each faulty idea
│   ├── misconception_classifier.py # ML fallback (TF-IDF + logistic regression)
│   ├── feedback_engine.py          # taxonomy, bilingual feedback, diagnostic grading
│   └── storage.py                  # anonymous SQLite logging
├── data/
│   ├── misconceptions.csv          # taxonomy, 23 labels, Vietnamese and English
│   ├── problems.csv                # problem bank
│   ├── seed_samples.jsonl          # labelled dataset
│   └── labeling_guideline.md       # annotation rules (Vietnamese, for the annotators)
├── evaluation/evaluate.py          # metrics and error analysis
└── tests/test_engine.py            # unit tests
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/problems` | problem bank |
| `POST /api/analyze` | per-step analysis with LaTeX, first invalid step, misconception, evidence |
| `POST /api/diagnostic` | grades a diagnostic answer; the key never reaches the browser |
| `GET /api/taxonomy` | the error catalogue |
| `GET /api/profile` | statistics for the session cookie |

Every text field is returned as `{"vi": ..., "en": ...}`, so switching language in
the interface re-renders from the payload already in memory instead of refetching.
The frontend performs no mathematical reasoning of its own.

## How the engine works

What separates this from an ordinary answer checker is the **rule engine**.

Rather than guessing what the student was thinking, it **simulates each faulty idea**.
Starting from the last valid step, every rule produces the result a student *would*
write if they held that misconception. A rule matches when its simulated result equals
what the student actually wrote.

For `3(x+2)=12`:

| Simulated rule | Simulated result | Student wrote | Match |
|---|---|---|---|
| ALG-DIST-01 incomplete distribution | `3x+2=12` | `3x+2=12` | yes |
| ALG-SIGN-01 moving a term without flipping its sign | `3x=12+6` | | no |

Every piece of feedback therefore carries checkable evidence and needs no LLM.

Four implementation details worth knowing when a teacher or a judge asks:

1. **SymPy simplifies eagerly.** `3*(x+2)` becomes `3x+6` at parse time, which destroys
   the structure the student wrote. The parser therefore keeps two forms: the simplified
   one for the maths and an `evaluate=False` one for the rule engine.
2. **Solution-set comparison** catches two errors that pure equivalence checking misses:
   roots lost by dividing both sides by an expression containing the unknown, and
   extraneous roots created by squaring.
3. **Two match tiers.** An exact match (0.85) outranks a match that only holds after
   scaling by a constant (0.55). Without tiers, `x+2=-5` gets mislabelled as a
   sign-moving error, because multiplying an equation by `-1` still yields an
   equivalent equation.
4. **Arithmetic-slip detection.** If replacing one constant in the student's step with an
   unknown yields a solvable value that makes the step valid, then the transformation
   rule was correct and only the arithmetic slipped. This is the boundary between
   `ALG-CALC-01` and a genuine misconception.

The ML layer runs only when no rule matched, and its confidence is capped below the
rule engine's. It never decides whether a step is right or wrong.

## Current results

On `data/seed_samples.jsonl`, 40 samples of which 24 carry a misconception label:

| Metric | Result |
|---|---|
| First invalid step identified | 40/40 |
| Misconception, top-1 | 24/24 |
| Macro-F1 | 1.000 |

**These numbers are not a benchmark.** The seed set was written by the same person who
wrote the rules, so the system is being scored on exactly what it was built to catch.
For figures worth putting in the report, an independent test set is required: solutions
written by other students, or labelled by a teacher who has not seen the rule list. Do
this before expanding the taxonomy.

## Adding a misconception

The taxonomy is data, not code, so teachers can edit `data/misconceptions.csv` directly.
Add one row with the code, group, name, definition, wrong example, correct example,
feedback, diagnostic question and its answer, in both languages.

To make the system detect that label automatically, add a simulation function to
`engine/rule_engine.py`:

```python
def mut_your_error(node):
    """Describe the mistake: input -> what the student would write"""
    if <node matches the shape you want to catch>:
        yield <simulated expression>, "YOUR-LABEL"
```

Register it in `EXPR_MUTATORS` (expression-level errors) or `EQ_MUTATORS`
(equation-level errors) and add a case to `tests/test_engine.py`.

## Known limitations

- Algebra only, within the declared scope. No geometry, no OCR.
- One step per line, at most one equals sign per line. A student writing
  `x=3 or x=-3` on a single line gets a parse error.
- When several misconceptions explain the same invalid step, the system shows the most
  confident label and lists the rest under the evidence panel. Some label pairs still
  overlap (partial division versus cancelling a term in a fraction) and a teacher should
  settle where the definitions meet.
- The ML layer is trained on 24 samples. It exists to prove the pipeline runs; it carries
  no statistical weight yet.

## Next steps from the plan

- Weeks 1-2: extend the taxonomy and the problem bank, send v0 to the supervising
  teacher before writing more rules.
- Week 3: widen the parser to accept more input styles.
- Week 4: build an independent test set, then rerun `evaluation/evaluate.py` for figures
  that mean something.
