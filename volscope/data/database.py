"""DuckDB persistence layer for VolScope."""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from volscope.config import DB_PATH


# Process-wide lock that serialises every execute() on the shared
# Streamlit @st.cache_resource connection. Multiple browser tabs
# (or Playwright sessions) share ONE underlying connection because
# @st.cache_resource is process-global; without serialisation DuckDB
# raises ``RuntimeError: mutex lock failed: Invalid argument`` mid-
# query (observed in /tmp/vs.log during the 2026-05-16 live audit).
# A simple lock + monkey-patched execute() keeps it correct without
# touching the dozens of call sites.
_EXEC_LOCK = threading.Lock()


class _LockedResult:
    """Wraps a DuckDB result; lock stays held until fetch is consumed."""

    __slots__ = ("_res", "_held")

    def __init__(self, res) -> None:
        self._res = res
        self._held = True

    def _release(self):
        if self._held:
            try:
                _EXEC_LOCK.release()
            except RuntimeError:
                pass
            self._held = False

    def fetchdf(self, *a, **kw):
        try:
            return self._res.fetchdf(*a, **kw)
        finally:
            self._release()

    def fetchall(self, *a, **kw):
        try:
            return self._res.fetchall(*a, **kw)
        finally:
            self._release()

    def fetchone(self, *a, **kw):
        try:
            return self._res.fetchone(*a, **kw)
        finally:
            self._release()

    def fetchmany(self, *a, **kw):
        try:
            return self._res.fetchmany(*a, **kw)
        finally:
            self._release()

    def df(self, *a, **kw):
        try:
            return self._res.df(*a, **kw)
        finally:
            self._release()

    def arrow(self, *a, **kw):
        try:
            return self._res.arrow(*a, **kw)
        finally:
            self._release()

    def __getattr__(self, name):
        # Any unproxied attribute access (e.g. a fetch variant we didn't
        # wrap) terminates use of this result, so release the exec lock
        # before delegating — otherwise the lock leaks and the next
        # execute() on this connection deadlocks.
        self._release()
        return getattr(self._res, name)

    def __del__(self):
        try:
            self._release()
        except Exception:
            pass


class _LockedConnection:
    """Wrap a DuckDBPyConnection so execute→fetch is mutex-serialised.

    Pattern: caller writes ``db.con.execute(sql, params).fetchdf()``.
    The execute() acquires the global lock, runs the statement, and
    returns a _LockedResult that releases the lock when fetched.
    Retries once on transient mutex errors.
    """

    __slots__ = ("_con",)

    def __init__(self, con: "duckdb.DuckDBPyConnection") -> None:
        self._con = con

    def execute(self, *args, **kwargs):
        import time
        for attempt in range(3):
            _EXEC_LOCK.acquire()
            try:
                res = self._con.execute(*args, **kwargs)
                return _LockedResult(res)
            except RuntimeError as exc:
                # Release before retry — mutex error means the call
                # never reached "ownership" inside DuckDB.
                try: _EXEC_LOCK.release()
                except RuntimeError: pass
                if "mutex lock failed" in str(exc) and attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
            except Exception:
                try: _EXEC_LOCK.release()
                except RuntimeError: pass
                raise

    def __getattr__(self, name):
        return getattr(self._con, name)


class VolScopeDB:
    """Thin wrapper around a DuckDB connection for VolScope tables."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        auto_migrate: bool = True,
        read_only: bool = False,
    ):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        if read_only:
            raw = duckdb.connect(self.db_path, read_only=True)
            self.con = _LockedConnection(raw)
        else:
            raw = duckdb.connect(self.db_path)
            self.con = _LockedConnection(raw)
            self._create_tables()
        if auto_migrate and not read_only:
            # Silent fix: legacy rows where iv_30d == hv_20d (the old buggy
            # seed) get their IV recomputed from YZ × VRP on first open. No
            # banner, no button, no user action needed.
            try:
                self.migrate_legacy_flat_spread()
            except Exception:
                pass  # never let a migration failure block startup

    def _create_tables(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_vol (
                ticker VARCHAR NOT NULL,
                date DATE NOT NULL,
                spot_price DOUBLE,
                iv_30d DOUBLE,
                iv_60d DOUBLE,
                iv_90d DOUBLE,
                iv_180d DOUBLE,
                iv_skew_25d DOUBLE,
                hv_20d DOUBLE,
                hv_60d DOUBLE,
                hv_yz_20d DOUBLE,
                hv_yz_30d DOUBLE,
                iv_rank DOUBLE,
                iv_percentile DOUBLE,
                iv_hv_spread DOUBLE,
                iv_hv_spread_matched DOUBLE,
                put_call_ratio DOUBLE,
                total_call_volume BIGINT,
                total_put_volume BIGINT,
                total_open_interest BIGINT,
                sector VARCHAR,
                company_name VARCHAR,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        # Backfill for pre-existing DBs — DuckDB's IF NOT EXISTS on ADD COLUMN.
        for _col, _type in [
            ("company_name", "VARCHAR"),
            ("iv_90d", "DOUBLE"),
            ("iv_180d", "DOUBLE"),
            ("iv_skew_25d", "DOUBLE"),
            ("convergence_score", "DOUBLE"),
            ("convergence_mispricing", "DOUBLE"),
            ("convergence_neglect", "DOUBLE"),
            ("convergence_reversal", "DOUBLE"),
            # v0.7.1 — matched-horizon HV + spread (Yang-Zhang at 30d).
            ("hv_yz_30d", "DOUBLE"),
            ("iv_hv_spread_matched", "DOUBLE"),
            # v0.9.0 — 6-state Vol Regime label + posterior probabilities.
            ("vol_regime", "VARCHAR"),
            ("p_vol_crushed", "DOUBLE"),
            ("p_vol_cheap",   "DOUBLE"),
            ("p_vol_fair",    "DOUBLE"),
            ("p_vol_rich",    "DOUBLE"),
            ("p_vol_extreme", "DOUBLE"),
            ("p_vol_crisis",  "DOUBLE"),
            # v0.6.1 — IV quality / robustness columns (migration
            # 006_iv_quality.sql). VolScopeDB.__init__ doesn't run the
            # persistence/migrations system, so we mirror those ADD
            # COLUMN statements here to keep the UI schema consistent
            # on every open. Without this, scope_page reads from
            # iv_recommendation and gets a "column does not exist" on
            # a DB that bypassed the bot migration runner.
            ("iv_quality_score",          "INTEGER"),
            ("iv_recommendation",         "VARCHAR"),
            ("iv_warnings",               "VARCHAR"),
            ("contamination_level",       "VARCHAR"),
            ("ivr_ivp_divergence",        "DOUBLE"),
            ("robust_iv_rank",            "DOUBLE"),
            ("structural_break_date",     "DATE"),
            ("structural_break_days_ago", "INTEGER"),
            ("structural_break_magnitude", "DOUBLE"),
        ]:
            try:
                self.con.execute(
                    f"ALTER TABLE daily_vol ADD COLUMN IF NOT EXISTS {_col} {_type}"
                )
            except Exception as _add_exc:                          # noqa: BLE001
                # ALTER may fail on race with another writer or if the
                # column was added by the bot-side migration runner; both
                # are non-fatal. Log so a real schema break surfaces.
                import logging as _lg
                _lg.getLogger("volscope.data.database").debug(
                    "ALTER daily_vol ADD %s %s failed: %s", _col, _type, _add_exc,
                )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS earnings (
                ticker VARCHAR NOT NULL,
                earnings_date DATE NOT NULL,
                PRIMARY KEY (ticker, earnings_date)
            )
            """
        )
        # Earnings Hub v1 (2026-05-13) — meta columns for BMO/AMC timing,
        # consensus estimates, and last-quarter actual-vs-implied
        # calibration. All optional, all populated by the
        # `scrape_earnings_meta.py` CLI; tiles fall back to "—" when
        # missing.
        for _col, _type in [
            ("time_of_day",       "VARCHAR"),  # 'bmo' | 'amc' | 'during' | 'unknown'
            ("eps_estimate",      "DOUBLE"),
            ("revenue_estimate",  "DOUBLE"),
            ("last_reaction_pct", "DOUBLE"),   # actual 1d move at prior ER
            ("last_implied_pct",  "DOUBLE"),   # reconstructed implied move at prior ER
            ("market_cap",        "DOUBLE"),   # captured at scrape time for sorting
            ("meta_updated_at",   "TIMESTAMP"),
        ]:
            try:
                self.con.execute(
                    f"ALTER TABLE earnings ADD COLUMN IF NOT EXISTS {_col} {_type}"
                )
            except Exception:
                pass
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS options_snapshots (
                ticker VARCHAR NOT NULL,
                snapshot_date DATE NOT NULL,
                expiry DATE NOT NULL,
                strike DOUBLE NOT NULL,
                option_type VARCHAR NOT NULL,
                bid DOUBLE,
                ask DOUBLE,
                last_price DOUBLE,
                volume BIGINT,
                open_interest BIGINT,
                iv DOUBLE,
                PRIMARY KEY (ticker, snapshot_date, expiry, strike, option_type)
            )
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                entry_date DATE NOT NULL,
                entry_iv_30d DOUBLE,
                entry_iv_percentile DOUBLE,
                entry_vrp DOUBLE,
                notes VARCHAR,
                active BOOLEAN DEFAULT true,
                option_type VARCHAR,
                strike DOUBLE,
                expiry DATE,
                instrument_type VARCHAR,
                barrier DOUBLE,
                contracts INTEGER,
                entry_premium DOUBLE,
                spot_at_entry DOUBLE,
                wkn VARCHAR,
                issuer VARCHAR
            )
            """
        )
        # Backfill columns on existing DBs (DuckDB supports ADD COLUMN IF NOT EXISTS).
        for _col, _type in [
            ("option_type", "VARCHAR"),
            ("strike", "DOUBLE"),
            ("expiry", "DATE"),
            ("instrument_type", "VARCHAR"),
            ("barrier", "DOUBLE"),
            ("contracts", "INTEGER"),
            ("entry_premium", "DOUBLE"),
            ("spot_at_entry", "DOUBLE"),
            ("wkn", "VARCHAR"),
            ("issuer", "VARCHAR"),
            # Paper-trader v2 (2026-05-11): multi-leg strategy linkage
            ("strategy_group_id", "VARCHAR"),
            ("strategy_template", "VARCHAR"),
            ("action", "VARCHAR"),         # 'buy' | 'sell' — sign of the leg
        ]:
            try:
                self.con.execute(
                    f"ALTER TABLE positions ADD COLUMN IF NOT EXISTS {_col} {_type}"
                )
            except Exception:
                pass
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS sector_daily (
                sector VARCHAR NOT NULL,
                date DATE NOT NULL,
                median_iv DOUBLE,
                median_perc DOUBLE,
                median_hv DOUBLE,
                mean_pcr DOUBLE,
                total_oi BIGINT,
                total_vol BIGINT,
                n_tickers INTEGER,
                regime VARCHAR,
                regime_z DOUBLE,
                flow_score DOUBLE,
                PRIMARY KEY (sector, date)
            )
            """
        )
        try:
            self.con.execute(
                "ALTER TABLE sector_daily ADD COLUMN IF NOT EXISTS flow_score DOUBLE"
            )
        except Exception:
            pass
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                metric VARCHAR NOT NULL,
                operator VARCHAR NOT NULL,
                threshold DOUBLE NOT NULL,
                channel VARCHAR NOT NULL DEFAULT 'log',
                label VARCHAR NOT NULL,
                enabled BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY,
                rule_id INTEGER,
                fired_at TIMESTAMP,
                ticker VARCHAR,
                metric VARCHAR,
                metric_value DOUBLE,
                message VARCHAR
            )
            """
        )
        # Pillar 2 — data-validator outputs persist here for cross-day trend
        # tracking and sidebar-badge surface.
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS validation_log (
                ticker         VARCHAR NOT NULL,
                date           DATE    NOT NULL,
                overall_level  VARCHAR NOT NULL,
                n_passes       INTEGER NOT NULL,
                n_flags        INTEGER NOT NULL,
                n_fails        INTEGER NOT NULL,
                details_json   VARCHAR,
                PRIMARY KEY (ticker, date)
            )
            """
        )
        # Pillar B — onboarding-complete flag + future user prefs.
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                key    VARCHAR PRIMARY KEY,
                value  VARCHAR
            )
            """
        )
        # Paper-trader v2 (2026-05-11) — every buy/close logged.
        # Single audit table keyed by event_ts so the Trade Journal can
        # reconstruct the user's actions chronologically. Position rows
        # in `positions` carry the live state; this table is the ledger.
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                event_id          INTEGER PRIMARY KEY,
                event_ts          TIMESTAMP NOT NULL,
                event_type        VARCHAR NOT NULL,    -- 'buy' | 'close'
                strategy_group_id VARCHAR,
                strategy_template VARCHAR,
                ticker            VARCHAR,
                legs_json         VARCHAR,             -- snapshot of leg list
                net_cash          DOUBLE,              -- + = debit (paid), - = credit (received)
                realized_pl       DOUBLE,              -- only set on close
                cash_after        DOUBLE,
                notes             VARCHAR
            )
            """
        )
        # Signals v2 (2026-05-14) — journal of every signal generated by
        # the Signal Engine. One row per (date, ticker, signal_type). Used
        # for future "signal performance history" view + nightly cron
        # capture so we can audit the system over time.
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_log (
                snapshot_date DATE NOT NULL,
                ticker        VARCHAR NOT NULL,
                direction     VARCHAR NOT NULL,
                signal_type   VARCHAR NOT NULL,
                strategy      VARCHAR NOT NULL,
                confidence    DOUBLE,
                iv_30d        DOUBLE,
                iv_rank       DOUBLE,
                iv_percentile DOUBLE,
                spot_price    DOUBLE,
                reason        VARCHAR,
                earnings_warning BOOLEAN,
                PRIMARY KEY (snapshot_date, ticker, signal_type)
            )
            """
        )
        # Phase-6 Options Lab presets — idempotent CLI seed populates
        # 3 starter trades (PYPL, EWZ, JD). Primary key is the slug so
        # re-running the seed is a no-op (INSERT OR IGNORE).
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_presets (
                id                 VARCHAR PRIMARY KEY,
                ticker             VARCHAR NOT NULL,
                strategy_name      VARCHAR NOT NULL,
                legs_spec_json     VARCHAR NOT NULL,
                thesis             VARCHAR,
                scaling_plan_json  VARCHAR,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes              VARCHAR
            )
            """
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_vol_date ON daily_vol(date)"
        )
        # Composite (ticker, date) — without it every per-ticker query
        # (get_ticker_history, upsert pre-read, the alert scan) does a full
        # sequential scan of the whole daily_vol table. ~7.5x speedup.
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_vol_ticker_date "
            "ON daily_vol(ticker, date)"
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings(earnings_date)"
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_sector_daily_date ON sector_daily(date)"
        )

    _DAILY_FIELDS = (
        "spot_price",
        "iv_30d",
        "iv_60d",
        "iv_90d",
        "iv_180d",
        "iv_skew_25d",
        "hv_20d",
        "hv_60d",
        "hv_yz_20d",
        # v0.7.1 — matched-horizon HV at 30 trading days (Yang-Zhang)
        # plus the academically-correct IV-HV spread that uses it.
        "hv_yz_30d",
        "iv_rank",
        "iv_percentile",
        "iv_hv_spread",
        "iv_hv_spread_matched",
        "put_call_ratio",
        "total_call_volume",
        "total_put_volume",
        "total_open_interest",
        "sector",
        "company_name",
        # v0.8 — Bayesian vol-regime label + posterior probabilities.
        # Without these in the whitelist upsert_daily silently dropped them,
        # so compute_vol_regime's writes never persisted and the Vol Regime
        # feature (charts + ribbons) read NULL forever.
        "vol_regime",
        "p_vol_crushed",
        "p_vol_cheap",
        "p_vol_fair",
        "p_vol_rich",
        "p_vol_extreme",
        "p_vol_crisis",
    )

    @staticmethod
    def _to_py_scalar(v):
        """Cast numpy/pandas scalars to native Python for DuckDB binding.

        DuckDB's Python client rejects numpy.int64 / numpy.float64 with
        NotImplementedException: "Unable to transform python value of
        type 'numpy.int64'". The merge-upsert below re-binds existing-
        row values pulled from a pandas DataFrame (typical case:
        total_open_interest / total_call_volume / total_put_volume
        carry numpy-int from prior scrapes), so without this cast every
        upsert can fail on a row that has any of those columns.
        """
        if v is None:
            return None
        if pd.isna(v):
            return None
        import numpy as _np
        if isinstance(v, _np.integer):
            return int(v)
        if isinstance(v, _np.floating):
            return float(v)
        if isinstance(v, _np.bool_):
            return bool(v)
        return v

    def upsert_daily(self, ticker: str, date, **kwargs) -> None:
        """
        Merge-upsert a daily_vol row. Fields not passed in kwargs preserve their
        existing value (so a daily IV scrape does not wipe HV columns written by
        the seed script).

        v0.9.6 — replaced the prior DELETE+INSERT pattern with a single
        atomic INSERT ... ON CONFLICT (ticker, date) DO UPDATE. The
        DELETE+INSERT path could throw
            "Invalid Input Error: Failed to delete all rows from index.
             Only deleted 0 out of 1 rows"
        on rows where the unique index state had drifted (rare but
        observed in seed-full runs of 800+ tickers). DuckDB marks the
        whole connection FATAL on that error — every subsequent
        upsert in the same seed loop then fails identically with
        "database has been invalidated". Result: ~50 % ticker
        coverage on the full universe seed. ON CONFLICT is one
        atomic statement, no index-state-drift window.
        """
        existing = self.con.execute(
            "SELECT * FROM daily_vol WHERE ticker = ? AND date = ?",
            [ticker, date],
        ).fetchdf()

        merged: dict = {"ticker": ticker, "date": date}
        for col in self._DAILY_FIELDS:
            if col in kwargs and kwargs[col] is not None:
                merged[col] = self._to_py_scalar(kwargs[col])
            elif not existing.empty and col in existing.columns:
                merged[col] = self._to_py_scalar(existing[col].iloc[0])
            else:
                merged[col] = None

        cols = list(merged.keys())
        cols_csv = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        # Update-set: every non-PK column → excluded.<col>
        update_cols = [c for c in cols if c not in ("ticker", "date")]
        update_set = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO daily_vol ({cols_csv}) VALUES ({placeholders}) "
            f"ON CONFLICT (ticker, date) DO UPDATE SET {update_set}"
        )
        try:
            self.con.execute(sql, list(merged.values()))
        except duckdb.Error as exc:
            # If DuckDB ever enters fatal state on this path, surface
            # a clean RuntimeError instead of letting the silent cascade
            # break the rest of the seed loop. The caller (seed_database)
            # catches this and reconnects.
            raise RuntimeError(
                f"upsert_daily({ticker}, {date}) failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Positions (trade journal)
    # ------------------------------------------------------------------

    def add_position(
        self,
        ticker: str,
        entry_date,
        entry_iv_30d: Optional[float] = None,
        entry_iv_percentile: Optional[float] = None,
        entry_vrp: Optional[float] = None,
        notes: str = "",
        # New rich-position fields (all optional for backwards compat):
        option_type: Optional[str] = None,
        strike: Optional[float] = None,
        expiry=None,
        instrument_type: Optional[str] = None,
        barrier: Optional[float] = None,
        contracts: Optional[int] = None,
        entry_premium: Optional[float] = None,
        spot_at_entry: Optional[float] = None,
        wkn: str = "",
        issuer: str = "",
        # Paper-trader v2: multi-leg linkage
        strategy_group_id: Optional[str] = None,
        strategy_template: Optional[str] = None,
        action: Optional[str] = None,
    ) -> int:
        """Insert a new position row; returns the auto-assigned id.

        The legacy 4-arg form (ticker, date, iv_30d, percentile, vrp, notes)
        still works — the new fields default to None so old callers and
        existing rows are unaffected. The Portfolio Assistant uses the
        rich form to model Optionsscheine.

        ``strategy_group_id`` ties multiple leg rows together (one UUID
        per paper-buy event). ``strategy_template`` is the human-readable
        template name ("Long Straddle"). ``action`` is "buy" or "sell".
        """
        next_id = self.con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM positions"
        ).fetchone()[0]
        self.con.execute(
            """
            INSERT INTO positions
                (id, ticker, entry_date, entry_iv_30d, entry_iv_percentile,
                 entry_vrp, notes, active,
                 option_type, strike, expiry, instrument_type,
                 barrier, contracts, entry_premium, spot_at_entry, wkn, issuer,
                 strategy_group_id, strategy_template, action)
            VALUES (?, ?, ?, ?, ?, ?, ?, true,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?)
            """,
            [next_id, ticker, entry_date, entry_iv_30d, entry_iv_percentile,
             entry_vrp, notes,
             option_type, strike, expiry, instrument_type,
             barrier, contracts, entry_premium, spot_at_entry, wkn, issuer,
             strategy_group_id, strategy_template, action],
        )
        return next_id

    def close_position(self, position_id: int) -> None:
        """Mark a position inactive (closed). Position remains in the DB
        for trade-journal history; use delete_position to remove fully."""
        self.con.execute(
            "UPDATE positions SET active = false WHERE id = ?", [position_id]
        )

    def delete_position(self, position_id: int) -> None:
        """Permanently remove a position row from the DB.

        Use when the user logged a position by mistake. For routine
        trade closure use ``close_position`` instead so the entry stays
        in the journal for retrospective entry-quality analysis.
        """
        self.con.execute(
            "DELETE FROM positions WHERE id = ?", [position_id]
        )

    def get_positions(self, ticker: Optional[str] = None, active_only: bool = False) -> pd.DataFrame:
        """Return positions, optionally filtered by ticker and/or active status."""
        query = "SELECT * FROM positions WHERE 1=1"
        params: list = []
        if ticker is not None:
            query += " AND ticker = ?"
            params.append(ticker)
        if active_only:
            query += " AND active = true"
        query += " ORDER BY entry_date DESC"
        return self.con.execute(query, params).fetchdf()

    def get_ticker_history(self, ticker: str, start=None, end=None) -> pd.DataFrame:
        query = "SELECT * FROM daily_vol WHERE ticker = ?"
        params: list = [ticker]
        if start is not None:
            query += " AND date >= ?"
            params.append(start)
        if end is not None:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"
        return self.con.execute(query, params).fetchdf()

    def get_recent_for_tickers(
        self, tickers: list[str], lookback_days: int = 60
    ) -> dict[str, pd.DataFrame]:
        """
        Bulk fetch: return `{ticker: history_df}` for every ticker in `tickers`,
        each limited to the most recent `lookback_days` rows.

        Uses a single grouped SQL query instead of N per-ticker queries — the
        Discover page's movers + crowded panels were hammering the DB with ~80
        reads on every render.
        """
        if not tickers:
            return {}
        placeholders = ",".join(["?"] * len(tickers))
        try:
            df = self.con.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY ticker ORDER BY date DESC
                        ) AS rn
                    FROM daily_vol
                    WHERE ticker IN ({placeholders})
                )
                SELECT * FROM ranked WHERE rn <= ?
                ORDER BY ticker, date
                """,
                [*tickers, lookback_days],
            ).fetchdf()
        except Exception:
            return {}
        if df.empty:
            return {t: pd.DataFrame() for t in tickers}
        return {t: sub.drop(columns=["rn"]) for t, sub in df.groupby("ticker")}

    def get_all_latest(self) -> pd.DataFrame:
        return self.con.execute(
            """
            SELECT d.*
            FROM daily_vol d
            INNER JOIN (
                SELECT ticker, MAX(date) AS max_date
                FROM daily_vol
                GROUP BY ticker
            ) m ON d.ticker = m.ticker AND d.date = m.max_date
            """
        ).fetchdf()

    def get_available_tickers(self) -> list[str]:
        df = self.con.execute(
            "SELECT DISTINCT ticker FROM daily_vol ORDER BY ticker"
        ).fetchdf()
        return df["ticker"].tolist() if not df.empty else []

    def get_last_scrape_date(self):
        """Most recent date across all rows in daily_vol, or None if empty."""
        try:
            df = self.con.execute(
                "SELECT MAX(date) AS max_date FROM daily_vol"
            ).fetchdf()
        except Exception:
            return None
        if df.empty:
            return None
        val = df["max_date"].iloc[0]
        if val is None or pd.isna(val):
            return None
        try:
            return pd.Timestamp(val).date()
        except Exception:
            return None

    def migrate_legacy_flat_spread(
        self, ticker: Optional[str] = None, vrp_mult: float = 1.12
    ) -> int:
        """
        In-place migration: recompute iv_30d = hv_yz_20d * vrp_mult for every
        row where the old seed stored iv_30d == hv_20d exactly. This fixes the
        flat IV-HV spread bug without requiring the user to stop Streamlit and
        run a separate script — the migration runs on the current DB handle.

        If `ticker` is given, only that ticker's rows are touched. Otherwise
        the migration runs across the whole table.

        Returns the number of rows updated.
        """
        where_clause = (
            "iv_30d IS NOT NULL "
            "AND hv_20d IS NOT NULL "
            "AND hv_yz_20d IS NOT NULL "
            "AND ABS(iv_30d - hv_20d) < 1e-9"
        )
        params: list = [vrp_mult, vrp_mult]
        if ticker is not None:
            where_clause += " AND ticker = ?"
            params.append(ticker)
        try:
            count_row = self.con.execute(
                f"SELECT COUNT(*) FROM daily_vol WHERE {where_clause}",
                params[2:] if ticker else [],
            ).fetchone()
            n = int(count_row[0]) if count_row else 0
            if n == 0:
                return 0
            self.con.execute(
                f"""
                UPDATE daily_vol
                SET iv_30d = hv_yz_20d * ?,
                    iv_hv_spread = (hv_yz_20d * ?) - hv_20d
                WHERE {where_clause}
                """,
                params,
            )
            return n
        except Exception:
            return 0

    def get_company_name(self, ticker: str) -> Optional[str]:
        """Most recent non-null company_name for `ticker`, or None."""
        try:
            df = self.con.execute(
                "SELECT company_name FROM daily_vol "
                "WHERE ticker = ? AND company_name IS NOT NULL "
                "ORDER BY date DESC LIMIT 1",
                [ticker],
            ).fetchdf()
        except Exception:
            return None
        if df.empty:
            return None
        val = df["company_name"].iloc[0]
        return None if val is None or pd.isna(val) else str(val)

    def upsert_earnings(self, ticker: str, earnings_date) -> None:
        self.con.execute(
            "DELETE FROM earnings WHERE ticker = ? AND earnings_date = ?",
            [ticker, earnings_date],
        )
        self.con.execute(
            "INSERT INTO earnings (ticker, earnings_date) VALUES (?, ?)",
            [ticker, earnings_date],
        )

    def get_upcoming_earnings(self, ticker: str, from_date) -> pd.DataFrame:
        return self.con.execute(
            "SELECT * FROM earnings WHERE ticker = ? AND earnings_date >= ? ORDER BY earnings_date",
            [ticker, from_date],
        ).fetchdf()

    # ------------------------------------------------------------------
    # Sector rotation
    # ------------------------------------------------------------------

    def upsert_sector_daily(self, sector: str, date, **kwargs) -> None:
        """Merge-upsert one sector_daily row (atomic ON CONFLICT).

        Fields not passed in kwargs preserve their existing value (so a
        partial aggregation does not wipe yesterday's clean columns).
        """
        _SECTOR_FIELDS = (
            "median_iv", "median_perc", "median_hv", "mean_pcr",
            "total_oi", "total_vol", "n_tickers", "regime", "regime_z", "flow_score",
        )
        existing = self.con.execute(
            "SELECT * FROM sector_daily WHERE sector = ? AND date = ?",
            [sector, date],
        ).fetchdf()

        row: dict = {"sector": sector, "date": date}
        for col in _SECTOR_FIELDS:
            if col in kwargs and kwargs[col] is not None:
                row[col] = self._to_py_scalar(kwargs[col])
            elif not existing.empty and col in existing.columns:
                row[col] = self._to_py_scalar(existing[col].iloc[0])
            else:
                row[col] = None

        cols = list(row.keys())
        cols_csv = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        update_cols = [c for c in cols if c not in ("sector", "date")]
        update_set = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO sector_daily ({cols_csv}) VALUES ({placeholders}) "
            f"ON CONFLICT (sector, date) DO UPDATE SET {update_set}"
        )
        try:
            self.con.execute(sql, list(row.values()))
        except duckdb.Error as exc:
            raise RuntimeError(
                f"upsert_sector_daily({sector}, {date}) failed: {exc}"
            ) from exc

    def reconnect(self) -> None:
        """Force-reopen the DuckDB connection.

        Called by long-running batch jobs (seed_database, daily_scrape)
        after they hit a per-row error that may have left the
        connection in DuckDB's FATAL state. Without this, every
        subsequent operation in the same loop fails with
        "database has been invalidated because of a previous fatal error".
        """
        try:
            self.con.close()
        except Exception:
            pass
        # Re-wrap in _LockedConnection — a raw duckdb handle here would
        # drop the cross-thread mutex and re-expose the multi-tab
        # "mutex lock failed" crash that _LockedConnection prevents
        # (mirrors __init__ at lines 141-145).
        raw = duckdb.connect(self.db_path, read_only=self.read_only)
        self.con = _LockedConnection(raw)

    def get_sector_history(self, sector: Optional[str] = None, lookback_days: int = 365) -> pd.DataFrame:
        """Return sector_daily rows, optionally filtered by sector, most recent `lookback_days`."""
        if sector is not None:
            return self.con.execute(
                """
                SELECT * FROM sector_daily
                WHERE sector = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                [sector, lookback_days],
            ).fetchdf().iloc[::-1].reset_index(drop=True)
        return self.con.execute(
            """
            SELECT * FROM sector_daily
            ORDER BY date, sector
            """,
        ).fetchdf()

    def get_sector_latest(self) -> pd.DataFrame:
        """Return the most recent sector_daily row per sector."""
        return self.con.execute(
            """
            SELECT s.*
            FROM sector_daily s
            INNER JOIN (
                SELECT sector, MAX(date) AS max_date
                FROM sector_daily
                GROUP BY sector
            ) m ON s.sector = m.sector AND s.date = m.max_date
            ORDER BY s.median_perc
            """
        ).fetchdf()

    def get_all_vol_history_for_sectors(self) -> pd.DataFrame:
        """Return all daily_vol rows that have a non-null sector, for sector aggregation."""
        return self.con.execute(
            """
            SELECT date, sector, iv_30d, iv_percentile, hv_20d,
                   put_call_ratio, total_call_volume, total_put_volume, total_open_interest
            FROM daily_vol
            WHERE sector IS NOT NULL
            ORDER BY date, sector
            """
        ).fetchdf()

    # ------------------------------------------------------------------
    # Alert rules
    # ------------------------------------------------------------------

    def add_alert_rule(
        self,
        ticker: str,
        metric: str,
        operator: str,
        threshold: float,
        channel: str = "log",
        label: str = "",
        enabled: bool = True,
    ) -> int:
        """Insert a new alert rule; returns the auto-assigned id."""
        next_id = self.con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM alert_rules"
        ).fetchone()[0]
        if not label:
            label = f"{ticker} {metric} {operator} {threshold}"
        self.con.execute(
            """
            INSERT INTO alert_rules
                (id, ticker, metric, operator, threshold, channel, label, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [next_id, ticker, metric, operator, threshold, channel, label, enabled],
        )
        return next_id

    def delete_alert_rule(self, rule_id: int) -> None:
        """Hard-delete an alert rule by id."""
        self.con.execute("DELETE FROM alert_rules WHERE id = ?", [rule_id])

    def set_alert_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        """Enable or disable an alert rule without deleting it."""
        self.con.execute(
            "UPDATE alert_rules SET enabled = ? WHERE id = ?", [enabled, rule_id]
        )

    def get_alert_rules(self, ticker: Optional[str] = None) -> pd.DataFrame:
        """Return alert rules, optionally filtered by ticker (includes wildcard '*')."""
        if ticker is not None:
            return self.con.execute(
                "SELECT * FROM alert_rules WHERE ticker = ? OR ticker = '*' ORDER BY id",
                [ticker],
            ).fetchdf()
        return self.con.execute(
            "SELECT * FROM alert_rules ORDER BY id"
        ).fetchdf()

    def log_alert_fired(
        self,
        rule_id: int,
        fired_at: str,
        ticker: str,
        metric: str,
        metric_value: float,
        message: str,
    ) -> None:
        """Append one fired-alert row to alert_log."""
        next_id = self.con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM alert_log"
        ).fetchone()[0]
        self.con.execute(
            """
            INSERT INTO alert_log
                (id, rule_id, fired_at, ticker, metric, metric_value, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [next_id, rule_id, fired_at, ticker, metric, metric_value, message],
        )

    def get_alert_log(self, limit: int = 100) -> pd.DataFrame:
        """Return the most recent fired-alert log entries."""
        return self.con.execute(
            "SELECT * FROM alert_log ORDER BY fired_at DESC LIMIT ?", [limit]
        ).fetchdf()

    # ── Validation log (Pillar 2) ─────────────────────────────────────

    def upsert_validation_report(
        self,
        ticker:        str,
        target_date,
        overall_level: str,
        n_passes:      int,
        n_flags:       int,
        n_fails:       int,
        details_json:  str = "",
    ) -> None:
        """Insert-or-replace one ticker's validation outcome for a given date."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO validation_log
                (ticker, date, overall_level, n_passes, n_flags, n_fails, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [ticker, target_date, overall_level, n_passes, n_flags, n_fails, details_json],
        )

    def get_validation_summary(self, target_date=None) -> pd.DataFrame:
        """Counts per overall_level for a date (defaults to today)."""
        target_date = target_date or date.today()
        return self.con.execute(
            """
            SELECT overall_level, COUNT(*) AS n
            FROM validation_log
            WHERE date = ?
            GROUP BY overall_level
            """,
            [target_date],
        ).fetchdf()

    # ── User settings (Pillar B) ──────────────────────────────────────

    def get_user_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read one user_settings value. Returns ``default`` when missing."""
        row = self.con.execute(
            "SELECT value FROM user_settings WHERE key = ?", [key]
        ).fetchone()
        return row[0] if row is not None else default

    def set_user_setting(self, key: str, value: str) -> None:
        """Insert-or-replace one user_settings entry."""
        self.con.execute(
            "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
            [key, value],
        )

    def get_validation_log(
        self, target_date=None, limit: int = 200
    ) -> pd.DataFrame:
        """Return the validation rows for a given date, newest-first by ticker."""
        target_date = target_date or date.today()
        return self.con.execute(
            """
            SELECT *
            FROM validation_log
            WHERE date = ?
            ORDER BY
                CASE overall_level
                  WHEN 'FAIL' THEN 0
                  WHEN 'FLAG' THEN 1
                  ELSE 2 END,
                ticker
            LIMIT ?
            """,
            [target_date, limit],
        ).fetchdf()

    def close(self) -> None:
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
