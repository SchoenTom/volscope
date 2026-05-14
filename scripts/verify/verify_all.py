#!/usr/bin/env python
"""
``make verify-all`` orchestrator.

Runs every verification stage in sequence and writes a single JSON report
to ``data/verify/latest.json``. Exit code 0 if every gate passes, 1 if
any correctness gate fails. Reliability gates (network-bound page tests,
backtest CI) report status but do not change the exit code.

Stages
------
1. **Pytest** — full test suite passes
2. **External BSM** — VolScope BSM matches py_vollib to 1e-10
3. **LEAPS render**  — Lab Index + Dossier render with all 9 visual checks
4. **Numeric consistency** — 9 invariants on the live PYPL row
5. **Data quality** — composite_quality failure rate ≤ 5 % over universe
6. **Sector aggregator** — sector_daily non-empty after fresh aggregate
7. **Backtest** — walk-forward runs without error (CI/p-value reported)

Usage
-----
    make verify-all
or
    python scripts/verify_all.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

OUT_DIR = _ROOT / "data" / "verify"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GREEN = "\033[32m"
RED   = "\033[31m"
AMBER = "\033[33m"
RESET = "\033[0m"


def _run(cmd: list[str], timeout: int = 600) -> tuple[bool, str, float]:
    """Run a subprocess; return (passed, last-line-of-output, elapsed-sec)."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(_ROOT),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s", time.time() - t0
    elapsed = time.time() - t0
    out = proc.stdout.strip().splitlines()
    last = out[-1] if out else ""
    return proc.returncode == 0, last, elapsed


# ── Stage implementations ────────────────────────────────────────────────

def stage_pytest() -> dict:
    ok, last, elapsed = _run([
        sys.executable, "-m", "pytest",
        "tests/test_leaps_convergence.py",
        "tests/test_leaps_sizing.py",
        "tests/test_leaps_scenarios.py",
        "tests/test_leaps_pretrade.py",
        "tests/test_leaps_backtest.py",
        "tests/test_leaps_pdf.py",
        "tests/test_leaps_watchlist.py",
        "tests/test_leaps_dossier_smoke.py",
        "tests/test_bsm_external_validation.py",
        "tests/test_black_scholes.py",
        "tests/test_historical_vol.py",
        "tests/test_vol_metrics.py",
        "-q", "--no-header",
    ])
    return {"name": "pytest", "passed": ok, "summary": last, "elapsed": round(elapsed, 1)}


def stage_external_bsm() -> dict:
    ok, last, elapsed = _run([
        sys.executable, "-m", "pytest",
        "tests/test_bsm_external_validation.py", "-q", "--no-header",
    ])
    return {"name": "external_bsm", "passed": ok, "summary": last, "elapsed": round(elapsed, 1)}


def stage_leaps_render() -> dict:
    ok, last, elapsed = _run(
        [sys.executable, "-u", "scripts/verify_leaps_pages.py"],
        timeout=300,
    )
    return {"name": "leaps_render", "passed": ok, "summary": last, "elapsed": round(elapsed, 1)}


def stage_numeric_consistency() -> dict:
    """Verify 9 invariants on the live PYPL row."""
    try:
        import duckdb
        from volscope.config import DB_PATH
        from volscope.data.database import VolScopeDB
        from volscope.analytics.leaps_convergence import (
            compute_convergence, suggest_leaps,
        )
        from volscope.analytics.leaps_sizing import size_position
        from volscope.analytics.leaps_scenarios import (
            build_risk_table, build_scenario_matrix, build_vega_gain_table,
        )
    except Exception as exc:
        return {"name": "numeric_consistency", "passed": False,
                "summary": f"import failed: {exc}", "elapsed": 0}

    t0 = time.time()
    try:
        db = VolScopeDB()
        latest = db.get_all_latest()
        sub = latest[latest["ticker"] == "PYPL"]
        if sub.empty:
            return {"name": "numeric_consistency", "passed": False,
                    "summary": "PYPL not in latest snapshot",
                    "elapsed": round(time.time() - t0, 1)}
        row = sub.iloc[0]
        spot = float(row["spot_price"])
        iv30 = float(row["iv_30d"])
        sug = suggest_leaps("PYPL", spot, iv30 / 100.0)
        plan = size_position(sug, budget=3000.0)
        rt = build_risk_table(sug, plan.capital_deployed)
        mat = build_scenario_matrix(sug, spot_multipliers=(1.0,), month_horizons=(0,))
        vg = build_vega_gain_table(sug, targets=(sug.iv,))

        invariants = [
            ("strike",         abs(sug.strike - round(spot * 1.75, 0)) < 0.01),
            ("BE = K + p",     abs((sug.strike + sug.est_premium) - sug.breakeven) <= 0.01),
            ("deployed",       abs(plan.capital_deployed - plan.contracts * sug.est_premium * 100) < 0.01),
            ("budget cap",     plan.capital_deployed <= plan.budget),
            ("residual",       abs((plan.budget - plan.capital_deployed) - plan.capital_residual) < 0.01),
            ("invalidation",   abs(rt.invalidation_spot - round(spot * 0.80, 2)) <= 0.01),
            ("scenario t=0",   abs(mat.cells[0][0].premium - sug.est_premium) < 0.05),
            ("vega self",      abs(vg.rows[0].pnl_per_share) < 0.05),
            ("max loss",       rt.max_loss_dollars == plan.capital_deployed),
        ]
        violations = [name for name, ok in invariants if not ok]
        ok = not violations
        summary = (
            f"{len(invariants)} invariants checked, {len(violations)} violations"
            + (f" — {violations}" if violations else "")
        )
    except Exception as exc:
        ok, summary = False, f"crashed: {exc}"
    return {"name": "numeric_consistency", "passed": ok,
            "summary": summary, "elapsed": round(time.time() - t0, 1)}


def stage_data_quality() -> dict:
    """Composite-quality failure rate over latest snapshot must be ≤ 5 %."""
    try:
        from volscope.data.database import VolScopeDB
        from volscope.analytics.data_quality import composite_quality
    except Exception as exc:
        return {"name": "data_quality", "passed": False,
                "summary": f"import failed: {exc}", "elapsed": 0}
    t0 = time.time()
    try:
        db = VolScopeDB()
        latest = db.get_all_latest()
        if latest.empty:
            return {"name": "data_quality", "passed": False,
                    "summary": "no rows", "elapsed": round(time.time() - t0, 1)}
        n_total = len(latest)
        n_failures = 0
        for _, row in latest.iterrows():
            try:
                cq = composite_quality(row, history=None)
                if cq.overall_level in ("SUSPECT",):
                    n_failures += 1
            except Exception:
                n_failures += 1
        rate = n_failures / max(1, n_total)
        ok = rate <= 0.05
        summary = f"{n_failures}/{n_total} suspect ({rate*100:.1f}%) — gate ≤ 5 %"
    except Exception as exc:
        ok, summary = False, f"crashed: {exc}"
    return {"name": "data_quality", "passed": ok,
            "summary": summary, "elapsed": round(time.time() - t0, 1)}


def stage_sector_aggregator() -> dict:
    ok, last, elapsed = _run([
        sys.executable, "scripts/compute_sector_rotation.py",
    ], timeout=120)
    return {"name": "sector_aggregator", "passed": ok, "summary": last, "elapsed": round(elapsed, 1)}


def stage_backtest() -> dict:
    """Reliability gate — does the backtest run + produce a CI?"""
    try:
        import duckdb
        from volscope.config import DB_PATH
        from volscope.analytics.leaps_backtest import (
            add_bootstrap_ci, run_backtest, summarise,
        )
    except Exception as exc:
        return {"name": "backtest", "passed": False,
                "summary": f"import failed: {exc}", "elapsed": 0}
    t0 = time.time()
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        panel = con.execute("SELECT * FROM daily_vol").fetchdf()
        bench = con.execute("SELECT * FROM daily_vol WHERE ticker = 'SPY'").fetchdf()
        con.close()
        result = run_backtest(
            panel=panel, benchmark_panel=bench,
            horizon_days=180, sample_every_n_days=30,
        )
        if result.n_trades > 0:
            result = add_bootstrap_ci(result, n_samples=500)
        ok = True
        summary = summarise(result)
    except Exception as exc:
        ok, summary = False, f"crashed: {exc}"
    return {"name": "backtest", "passed": ok,
            "summary": summary, "elapsed": round(time.time() - t0, 1)}


# ── Orchestrator ─────────────────────────────────────────────────────────

# (stage, is_correctness_gate)
STAGES = [
    (stage_pytest,                 True),
    (stage_external_bsm,           True),
    (stage_leaps_render,           True),
    (stage_numeric_consistency,    True),
    (stage_data_quality,           True),
    (stage_sector_aggregator,      True),
    (stage_backtest,               False),
]


def main() -> int:
    print(f"VolScope verify-all — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    results = []
    for stage_fn, is_gate in STAGES:
        name = stage_fn.__name__.replace("stage_", "")
        print(f"  … {name:24s} ", end="", flush=True)
        result = stage_fn()
        result["is_correctness_gate"] = is_gate
        flag = (
            f"{GREEN}✓ PASS{RESET}" if result["passed"]
            else f"{RED}✗ FAIL{RESET}" if is_gate
            else f"{AMBER}∼ WARN{RESET}"
        )
        print(f"{flag}  ({result['elapsed']:.1f}s)  {result['summary'][:80]}")
        results.append(result)

    print("=" * 80)
    n_pass = sum(1 for r in results if r["passed"])
    n_gate_fail = sum(1 for r in results if r["is_correctness_gate"] and not r["passed"])
    n_warn = sum(1 for r in results if not r["is_correctness_gate"] and not r["passed"])

    color = GREEN if n_gate_fail == 0 else RED
    print(f"{color}PASS {n_pass}{RESET} · "
          f"{RED}FAIL {n_gate_fail}{RESET} · "
          f"{AMBER}WARN {n_warn}{RESET} · "
          f"TOTAL {len(results)}")

    out = {
        "ts":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_pass":      n_pass,
        "n_gate_fail": n_gate_fail,
        "n_warn":      n_warn,
        "stages":      results,
    }
    out_path = OUT_DIR / "latest.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"  → {out_path.relative_to(_ROOT)}")

    return 0 if n_gate_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
