# Public-Launch Master Plan

> Operator: "we are close to launching it online on github, publicly,
> prepare volscope for this HUGE STEP!" — 2026-05-19.

## Scope of work

A public GitHub launch means strangers will (a) read the README,
(b) `git clone` the repo, (c) run the install path you advertise,
(d) open issues when something breaks, (e) submit PRs. The repo has
to survive each of those steps without making the operator look
foolish or leak anything they don't want public.

Four pillars, in priority order:

1. **No secrets, no PII, no hardcoded local paths.** A single token
   in git history or a `/Users/tomschoen/...` in production code
   is an instant credibility break.
2. **The advertised install path works.** Every command in the
   README must succeed on a clean machine. If `make quickstart`
   crashes, you lose 60% of would-be users in minute one.
3. **The UI doesn't crash on first open.** Onboarding wizard fires,
   default page renders, no red traceback boxes.
4. **The repo looks like a serious project.** LICENSE, CONTRIBUTING,
   CODE_OF_CONDUCT, issue templates, badges, screenshots,
   description, topics.

## Pre-launch checklist

### A — Hygiene (must pass before push)

A1. **gitleaks full-history scan** — exit 0
A2. **No `/Users/` paths in code under `volscope/` or `scripts/`** —
    grep clean (sole exception: the cron-log path inside `~/`-prefixed
    user-space, which is correct)
A3. **No personal names, emails, or German tax data in any tracked
    file** (operator's name is fine in commit history but not in
    code comments)
A4. **`.env` not in tracking** — `.env.example` only
A5. **gitignore covers**: `.env`, `*.duckdb`, `data/`, `__pycache__/`,
    `.venv/`, `.DS_Store`, `*.log`, `.streamlit/secrets.toml`
A6. **DB file is NOT in the repo** (DuckDB files are user state,
    not source)

### B — Documentation

B1. **README** reads top-to-bottom: hook → install → use → modes
B2. **LICENSE** present (operator wants MIT per CLAUDE.md note)
B3. **CONTRIBUTING.md** present with at minimum: how to run tests,
    how to format/lint, how to submit a PR
B4. **CODE_OF_CONDUCT.md** present (CC pattern boilerplate ok)
B5. **CHANGELOG.md** with version history, or at least a Releases
    page populated on GitHub
B6. **A SCREENSHOT in README** — operators decide in 3 seconds
    whether to keep reading
B7. **Working CI badges** — pytest, coverage, license

### C — User journey (live-tested)

For each step, must work on a clean checkout:

C1. `git clone` succeeds
C2. `python3 -m venv .venv && source .venv/bin/activate` succeeds
C3. `pip install -r requirements.txt && pip install -e .` succeeds
C4. `cp .env.example .env` succeeds (no required-key crash on default)
C5. `make quickstart` finishes ≤ 5 min (the README says "1-2 min" —
    fast-quickstart now seeds watchlist tickers, so this is realistic)
C6. UI opens at http://localhost:8501, renders Command / Discover
    without exception
C7. Sidebar shows nav buttons, all clickable, each lands on a page
    that renders
C8. Onboarding wizard fires for fresh DB
C9. Watchlist page → Create new → ticker appears → Configure alerts
    → Save works
C10. Scope page → Add SPY to watchlist popover → creates watchlist
C11. No ghost `expand_more` / `keyboard_arrow_*` text leaks
C12. Help page references core glossary terms (BSM, HMM, etc.)

### D — Code-quality safety net

D1. **pytest -x** exit 0 for at least the high-value test slices:
    - `tests/properties/` (BSM round-trip, put-call parity)
    - `tests/test_audit_chain.py`
    - `tests/golden/` (if exists)
D2. **No `print()` leftover statements in `volscope/` non-test code**
    (use the structlog logger)
D3. **Ruff/Black clean** on `volscope/ui/`, `volscope/data/`,
    `volscope/analytics/`
D4. **No `TODO: secret`, `XXX: HACK`, `FIXME: critical` markers**
    in tracked code
D5. **Top-of-file docstrings exist** for every page in
    `volscope/ui/views/`

### E — Repo polish

E1. **GitHub topics**: `options`, `volatility`, `streamlit`,
    `quantitative-finance`, `duckdb`, `python`, `trading`,
    `black-scholes`, `iv-rank`
E2. **Repo description**: one-line — "Volatility-research workbench
    for options traders. Live IV/HV/skew/regime + paper-trading
    engine. Streamlit + DuckDB + yfinance."
E3. **Pin a discussion / pinned issue** with the value-prop
E4. **`docs/` folder navigable** from README links

## Execution order

```
1. Hygiene scan (A1-A6) → fix violations
2. Code-quality safety net (D1-D5) → fix violations
3. Documentation (B1-B7) → write what's missing
4. User-journey live test (C1-C12) → fix any crash
5. Repo polish (E1-E4) → manual GitHub UI work after push
```

## What MUST be true at launch time

The single highest-leverage check: **a stranger can clone, install,
and reach a non-crashed UI in 5 minutes**. Everything else is gravy.

The single highest-leverage de-risk: **gitleaks clean on full
history + no `/Users/tomschoen/` in any tracked file under
`volscope/` or `scripts/`**. One leak = brand damage that
can't be unposted.

Live-browser simulation after every fix step. Atomic commits.
Push at the end.
