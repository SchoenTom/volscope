# Developer Guide

## Setup (first checkout)

```bash
git clone <your-fork> volscope
cd volscope
uv sync --all-extras                  # creates .venv, installs runtime + dev + bot deps
cp .env.example .env                   # fill in IBKR / Telegram / Finnhub keys
uv run pre-commit install              # hook ruff + mypy + gitleaks + fast tests
```

The runtime DB lives at `~/Library/Application Support/VolScope/volscope.db`
on macOS (XDG_DATA_HOME on Linux). Override with `VOLSCOPE_DATA_DIR`.

## Common commands

| Task | Command |
|---|---|
| Run the UI | `make run` (or `streamlit run volscope/ui/app.py`) |
| Daily scrape | `make scrape` |
| Quickstart from zero | `make quickstart` |
| Run all tests | `make test` |
| Fast tests only | `pytest -m "not slow and not integration and not perf"` |
| Run perf smoke | `pytest -m perf` |
| End-to-end verify | `make verify-all` |
| Release DB lock | `make unlock` |

## Branch workflow

- `main` is protected. No direct pushes.
- Create a branch: `feat/<short-name>` / `fix/<short-name>` /
  `refactor/<short-name>` / `docs/<short-name>` / `test/<short-name>` /
  `chore/<short-name>`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(signals): add HMM regime gate`, `fix(ui): rotation page empty join`.
- Open a PR. CI must pass + 1 reviewer approval (CODEOWNERS for
  `volscope/{analytics,risk,execution,lifecycle}/`).
- Merge via "Squash and merge" — preserves Conventional-Commit history
  on `main`.

## Test pyramid

```
slow / integration  ← few; nightly; real DB, real IBKR paper, real network
perf                ← perf smoke; signal gen <200 ms; nightly
fast unit           ← many; ms each; run on every commit + every keystroke in --watch
```

Markers (in `pyproject.toml [tool.pytest.ini_options]`):
- `slow` — > 5s per test
- `integration` — needs external service
- `ibkr` — needs IBKR paper connection
- `perf` — performance benchmark

CI fast path: `pytest -m "not slow and not integration and not perf"`.

## Adding a new strategy

1. Add config block in `config/strategies.yaml`.
2. Create `volscope/strategies/<name>.py` extending `BaseStrategy`.
3. Register in `volscope/strategies/registry.py`.
4. Tests in `tests/test_strategy_<name>.py`.
5. Backtest in Phase 3 stack before paper-engine deployment.

## Debugging tips

- **Streamlit hangs at startup**: `make unlock` — likely a stale DB lock.
- **Plotly fillcolor error**: rgba() helper exists at
  `volscope/ui/styles/theme.py:15` — use it instead of raw hex.
- **iCloud-cold subprocess stall**: project must live at `~/Desktop/VolScope`
  (not the iCloud mirror); first-import of large deps can stall 25-90s on
  fresh shells. `scripts/ops/keep_warm.sh` warms the cache.
- **`make verify-all` fails after script reorg**: every `scripts/<file>`
  path moved in v0.2.0 → check `Makefile` references match the new
  `scripts/<group>/<file>` layout.
