"""VolScope verification — independent auditor that can't be gamed.

Runs four gates:
    1. Spec-conformance: every 'done' task in progress.json has its module
       importable with the expected public symbols.
    2. Regression: full pytest suite passes.
    3. Golden values: BSM prices and HV recovery vs independent ground truth.
    4. Runtime smoke: streamlit app boots headless.

Exits non-zero if anything fails. Meant to be run BETWEEN Ralph iterations.
"""
from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
sys.path.insert(0, str(ROOT))


# (phase, task_key) -> (module path, list of required attributes)
SPEC: dict[tuple[str, str], tuple[str, list[str]]] = {
    ("P1_foundation", "T02_config"): (
        "volscope.config",
        ["DB_PATH", "TRADING_DAYS_PER_YEAR", "DEFAULT_HV_SHORT"],
    ),
    ("P1_foundation", "T03_black_scholes"): (
        "volscope.analytics.black_scholes",
        ["bs_price", "bs_vega", "bs_delta", "bs_gamma", "bs_theta", "implied_volatility"],
    ),
    ("P1_foundation", "T05_historical_vol"): (
        "volscope.analytics.historical_vol",
        ["hv_close_to_close", "hv_parkinson", "hv_garman_klass", "hv_yang_zhang"],
    ),
    ("P1_foundation", "T07_vol_metrics"): (
        "volscope.analytics.vol_metrics",
        ["iv_rank", "iv_percentile", "vol_regime", "iv_hv_spread"],
    ),
    ("P2_data", "T09_database_schema"): ("volscope.data.database", ["VolScopeDB"]),
    ("P2_data", "T10_ticker_universe"): (
        "volscope.data.ticker_universe",
        ["TICKER_UNIVERSE", "all_tickers", "sector_of"],
    ),
    ("P2_data", "T11_price_fetcher"): (
        "volscope.data.price_fetcher",
        ["fetch_ohlcv"],
    ),
    ("P2_data", "T13_options_scraper"): (
        "volscope.data.options_scraper",
        ["scrape_options_chain"],
    ),
    ("P2_data", "T15_seed_script"): ("scripts.seed_database", []),
    ("P2_data", "T16_data_validation"): (
        "volscope.data.data_validation",
        ["validate_iv", "validate_daily_row"],
    ),
    ("P3_analytics", "T17_spread_analysis"): (
        "volscope.analytics.spread_analysis",
        ["compute_iv_hv_timeseries", "detect_spread_extremes"],
    ),
    ("P3_analytics", "T18_opportunity_engine"): (
        "volscope.analytics.opportunity",
        ["find_cheapest_vol", "find_richest_premium", "find_daily_outliers"],
    ),
    ("P3_analytics", "T19_crowded_trades"): (
        "volscope.analytics.crowded_trades",
        ["compute_crowded_score"],
    ),
    ("P4_ui", "T21_theme_css"): ("volscope.ui.styles.theme", ["inject_theme", "COLORS"]),
    ("P4_ui", "T22_chart_builders"): (
        "volscope.ui.components.chart_builders",
        ["create_iv_hv_chart", "create_spread_chart", "create_percentile_chart"],
    ),
    ("P4_ui", "T23_metric_components"): (
        "volscope.ui.components.metric_components",
        ["render_kpi_row", "render_percentile_pill"],
    ),
    ("P4_ui", "T24_scope_page"): ("volscope.ui.views.scope_page", ["render_scope_page"]),
    ("P4_ui", "T25_scan_page"): ("volscope.ui.views.scan_page", ["render_scan_page"]),
    ("P4_ui", "T26_discover_page"): (
        "volscope.ui.views.discover_page",
        ["render_discover_page"],
    ),
    ("P4_ui", "T27_app_main"): ("volscope.ui.app", ["main"]),
    ("P4_ui", "T28_sidebar"): ("volscope.ui.components.sidebar", ["render_sidebar"]),
}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")


def gate_spec_conformance() -> bool:
    progress_path = ROOT / "progress.json"
    if not progress_path.exists():
        _fail("progress.json missing")
        return False
    progress = json.loads(progress_path.read_text())
    ok = True
    for (phase, task), (module_name, attrs) in SPEC.items():
        status = progress["phases"].get(phase, {}).get("tasks", {}).get(task)
        if status != "done":
            continue
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            _fail(f"{task}: cannot import {module_name}: {exc}")
            ok = False
            continue
        for attr in attrs:
            if not hasattr(mod, attr):
                _fail(f"{task}: {module_name}.{attr} missing")
                ok = False
    return ok


def gate_regression() -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        print(proc.stderr[-1000:])
        _fail("pytest suite has failures")
        return False
    return True


def gate_golden_values() -> bool:
    """Hand-computed BSM ground truth (external to volscope code)."""
    from volscope.analytics.black_scholes import bs_price, implied_volatility
    from volscope.analytics.historical_vol import hv_close_to_close
    import numpy as np
    import pandas as pd

    # ATM call: S=K=100, T=1, r=0.05, σ=0.20 → 10.4506 (textbook)
    p = bs_price(100, 100, 1.0, 0.05, 0.20, option_type="call")
    if abs(p - 10.4506) > 0.01:
        _fail(f"golden BSM call price off: {p:.4f}")
        return False

    # Deep ITM call: S=150, K=100, T=1, r=0.05, σ=0.20 → 54.9701 (textbook)
    p2 = bs_price(150, 100, 1.0, 0.05, 0.20, option_type="call")
    if abs(p2 - 54.9701) > 0.01:
        _fail(f"golden ITM call off: {p2:.4f}")
        return False

    # IV recovery round-trip
    recovered = implied_volatility(p, 100, 100, 1.0, 0.05, option_type="call")
    if recovered is None or abs(recovered - 0.20) > 1e-6:
        _fail(f"IV recovery failed: {recovered}")
        return False

    # HV recovery on independently-seeded GBM (different seed than project tests)
    rng = np.random.default_rng(1337)
    n = 600
    sigma = 0.30
    dt = 1 / 252
    z = rng.standard_normal(n)
    log_r = (0.05 - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z
    close = pd.Series(100.0 * np.exp(np.cumsum(log_r)))
    hv = hv_close_to_close(close, window=60).dropna().tail(200).mean()
    if not (20.0 < hv < 40.0):
        _fail(f"HV recovery off: {hv:.2f}% (expected ~30%)")
        return False

    return True


def gate_runtime_smoke() -> bool:
    """
    Boot the Streamlit app headless on an isolated temporary DB and confirm
    it serves the "You can now view" banner. Uses a dedicated VOLSCOPE_DATA_DIR
    so this gate never touches the user's real database, and spawns streamlit
    in its own process group so we can SIGTERM the entire tree on teardown —
    otherwise a stale streamlit child keeps the DB lock and breaks the next
    `make run`.
    """
    import os
    import signal
    import tempfile
    import time

    tmp_data_dir = tempfile.mkdtemp(prefix="volscope-verify-")
    env = os.environ.copy()
    env["VOLSCOPE_DATA_DIR"] = tmp_data_dir

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "volscope/ui/app.py",
            "--server.headless",
            "true",
            "--server.port",
            "8801",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        start_new_session=True,  # own process group → signal the whole tree
    )

    started = False
    deadline = time.time() + 20
    try:
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            if "You can now view" in line:
                started = True
                break
    finally:
        # Kill the entire process group — streamlit spawns a tornado child
        # that won't die from proc.terminate() alone.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        # Clean up the isolated data dir + anything DuckDB wrote.
        try:
            import shutil

            shutil.rmtree(tmp_data_dir, ignore_errors=True)
        except Exception:
            pass

    if not started:
        _fail("streamlit did not boot within 20s")
    return started


def gate_design_drift() -> bool:
    """Pillar D — design-token linter with frozen baseline.

    Passes when current violation count <= the baseline (70 today).
    Future PRs that ADD inline hex / off-ladder values fail; clean code
    is rewarded by lowering the baseline over time.
    """
    out = subprocess.run(
        [sys.executable, "scripts/audit_design_drift.py", "--max", "70"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        print(out.stdout[-800:])
        print(out.stderr[-400:], file=sys.stderr)
    return out.returncode == 0


def main() -> int:
    gates = [
        ("Spec conformance", gate_spec_conformance),
        ("Regression (pytest)", gate_regression),
        ("Golden values", gate_golden_values),
        ("Runtime smoke", gate_runtime_smoke),
        ("Design drift", gate_design_drift),
    ]
    all_ok = True
    for name, fn in gates:
        print(f"[verify] {name} ...", flush=True)
        ok = fn()
        print(f"[verify] {name}: {'OK' if ok else 'FAIL'}")
        all_ok &= ok
    print(f"[verify] OVERALL: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
