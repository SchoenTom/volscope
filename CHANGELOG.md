# Changelog

All notable changes to VolScope. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org/).

## [Unreleased]

(nothing yet)

## [0.2.0] — 2026-05-14

### Added

- **Repo hygiene**: `git init`, private GitHub repo, branch protection.
- **Memory canon**: `memory/` folder collecting agent-readable context
  (project notes, roadmaps, ops protocols, philosophy, raw chat
  archives). Sanitised — no personal identifiers committed.
- **Documentation**: `docs/ARCHITECTURE.md` (Mermaid module diagram,
  WORM audit-log invariant), `docs/DEVELOPER_GUIDE.md`,
  `docs/OPERATOR_GUIDE.md`, `docs/BACKUPS.md`,
  `docs/GOING_PUBLIC_CHECKLIST.md`, ADRs 0001–0005, roadmap docs.
- **Phase 0 bug fixes**: Pre-Trade `fillcolor` now uses `rgba()` helper
  consistently; "keyboard" Material-Symbols ghost text suppressed via
  `font-size: 0` fallback; `st.metric` truncation replaced with
  `kpi_grid_html`; sector heatmap densified with forward/backward fill;
  Rotation page tautology removed.
- **Phase 1 scaffold**: `config/` YAMLs (strategies, risk, tickers,
  calendar), `volscope/signals/` (factors, composite, filters),
  `volscope/analytics/regime.py` (2-state Gaussian HMM scaffold),
  `volscope/persistence/migrations/001_init.sql` (5 bot_* tables +
  idempotent runner), Bot Dashboard view (read-only).
- **Phase 1 finishing** (this release): `volscope/analytics/garch.py`
  (arch-library wrapper), `volscope/execution/ibkr_stub.py` (ib_async
  connectivity scaffold), `volscope/signals/ranking.py` (composite-score
  ranker with universe + risk caps).
- **Phase 2 core scaffold**: `volscope/lifecycle/machine.py` (11-state
  trade lifecycle via `transitions` library), `volscope/scheduler/jobs.py`
  (APScheduler 3.11 with America/New_York timezone + healthchecks
  heartbeat stub), `volscope/risk/kill_switch.py` (3 manual + 5 auto
  trip paths + sticky reset). Migration `002_killswitch.sql`.
- **Script reorganisation**: 30 flat scripts grouped into `scrape/`,
  `verify/`, `audit/`, `compute/`, `backtest/`, `ops/`, `_dev/`.
  Makefile + in-code references updated.
- **Operations scaffolds**: `scripts/ops/preflight.py` (pre-startup
  gate) and `scripts/ops/reconcile.py` (DB↔IBKR diff stub).
- **CI + tooling**: `pyproject.toml` (replaces `requirements.txt`),
  `.pre-commit-config.yaml` (ruff, mypy strict on new packages,
  gitleaks, pytest-fast), `.github/workflows/ci.yml` (Ubuntu Python
  3.11+3.12), Dependabot, CODEOWNERS, issue + PR templates.
- **Tests**: 8 new test modules covering factors, composite, filters,
  ranking, regime, garch, machine, scheduler, kill_switch, migrations,
  and a perf smoke benchmark.

### Changed

- `requirements.txt` retained as auto-generated mirror; `pyproject.toml`
  is now the source of truth.
- `Makefile`: 30+ script paths updated for the new subgroup layout.
- `README.md`: full overhaul (hero, status badges, Mermaid, citations).
- `CLAUDE.md`: appended a "memory/ canon" pointer + `WELCOME-AGENT.md`
  reference.

### Sanitised

- All personal identifiers (real names, emails, university details,
  thesis advisor names, specific position sizes, tax IDs) stripped from
  `memory/` and `docs/` via `_one_off/sanitize.py`. Hard-gate `grep`
  passes with zero hits before every commit.

### Security

- Pre-commit `gitleaks` hook on push.
- CI gitleaks job runs full-history scan on every PR.
- CI pip-audit job runs CVE checks on locked deps (warn-only until
  v0.3.0; will tighten to fail-on-critical).

### Known issues

- Coverage gate set at 65%; if local backfill doesn't clear it for a
  PR, the PR ships in two parts (feature + tests) per CONTRIBUTING.md.
- Live IBKR wiring is NOT in this release — `ibkr_stub.py` is a
  scaffold that returns False on connect failure rather than raising.
  Wiring lands in Phase 2.5.
