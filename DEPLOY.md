# Deploying MathLens

## Do you need to buy a domain?

No. Every platform below hands you a free address, for example
`huggingface.co/spaces/<your-name>/mathlens` or `mathlens.onrender.com`.
Buying a domain is cosmetic and can be attached later without touching any code.

## Why GitHub Pages does not work

GitHub Pages serves static files only. MathLens needs Python and SymPy running on a
server to check mathematical equivalence, so the page would load but the Grade button
would do nothing. You need somewhere that runs a container or a Python process.

## Step 1: push the code to GitHub

One-time git setup, if this is a new machine:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Inside the project folder:

```bash
cd mathlens
git init
git add .
git commit -m "MathLens v0.1"
git branch -M main
```

Create the repository at github.com/new. Name it `mathlens`, leave **Add a README**
and every other initialise option **unticked**, otherwise the first push is rejected
for having unrelated histories. Then:

```bash
git remote add origin https://github.com/<your-username>/mathlens.git
git push -u origin main
```

GitHub no longer accepts your account password here. When prompted, the username is
your GitHub name and the password is a **personal access token**: Settings →
Developer settings → Personal access tokens → Tokens (classic) → Generate new token,
tick the `repo` scope, copy it once and paste it as the password.

Later updates are three commands:

```bash
git add .
git commit -m "what changed"
git push
```

`.gitignore` already excludes `__pycache__`, the SQLite file and the trained model, so
no local database or cache is uploaded. The model is regenerated with
`python -m engine.misconception_classifier`; without it the ML fallback simply stays
off and the rule engine handles everything.

## Step 2: deploy on Render

Hugging Face Spaces used to be the easy route, but since July 2026 Docker and Gradio
Spaces require a paid plan and only Static Spaces remain free. Static cannot run Python,
so it is no longer an option for this project. Render is the current free route: no
credit card, native Python, and it deploys straight from the GitHub repository.

1. Create an account at render.com and connect it to GitHub.
2. Choose **New → Web Service** and pick the `mathlens` repository.
3. Render reads `render.yaml` from the repo, so the settings should already be filled
   in. Confirm they read:
   - Runtime: **Python**
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn web.server:app --host 0.0.0.0 --port $PORT`
   - Instance type: **Free**
4. Click Create Web Service and watch the build log. The first build takes a few
   minutes. The site then lives at `https://mathlens.onrender.com` or whatever name
   the service was given.

From then on, every `git push` to `main` redeploys automatically.

A free instance sleeps after about fifteen minutes without traffic, and the first
request afterwards waits roughly thirty seconds while it wakes. Before a classroom
session, open the site once yourself so students do not all hit the cold start.

### Dependencies are split for this reason

`requirements.txt` holds only what the site needs to serve traffic: SymPy, FastAPI and
uvicorn. `requirements-dev.txt` adds pandas, scikit-learn and Streamlit, which are used
by the Streamlit debug view, the ML fallback and offline evaluation. A free instance has
512 MB of memory, and installing the full set is what usually makes these builds fail.
Install the dev set locally:

```bash
pip install -r requirements-dev.txt
```

### If you get a paid plan later

The `Dockerfile` and the YAML block at the top of `README.md` are still correct for
Hugging Face Spaces. With a PRO account, create a Docker Space and push:

```bash
git remote add space https://huggingface.co/spaces/<your-hf-username>/mathlens
git push space main
```

## Other options

| Host | Good | Less good |
|---|---|---|
| Render | free, no card, deploys from GitHub on every push | sleeps after ~15 minutes idle, ~30 s cold start |
| Hugging Face Spaces | good build logs, simple Docker deploys | Docker Spaces need a paid plan since July 2026 |
| Railway, Fly.io, Google Cloud Run | fast and stable | credit card required |

## Pilot data: read this before students use it

Free tiers give you an ephemeral disk. The `Dockerfile` writes SQLite to `/tmp`, which
means **the data disappears on every rebuild or restart**. That is fine for showing a
teacher, but losing the data from a pilot with 20-30 students means losing the
evaluation half of the project.

Two ways to handle it:

- Move to a free Postgres instance on Neon or Supabase, port `engine/storage.py` to
  `psycopg`, and keep the same schema.
- Or stay on SQLite and download `/tmp/mathlens.db` immediately after each session.

The first option is safer once the pilot runs across several sessions.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `7860` | port uvicorn binds to; Render sets this for you |
| `MATHLENS_DB` | `data/mathlens.db` | SQLite path, point it at `/tmp` on hosts with a read-only filesystem |

## If you still want GitHub Pages

There is one path: run SymPy inside the browser with Pyodide, drop the backend entirely,
and the site becomes fully static. The trade-offs:

- The first visit downloads roughly 10-20 MB and takes several seconds before the page
  is usable.
- No central data collection, since everything runs on the student's machine. Section 9
  of the project plan needs the MathLens Dataset from the pilot, so this is a real loss.

Deploy to Spaces first and keep Pyodide in reserve for an offline demo.
