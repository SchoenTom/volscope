"""
Strategy preset persistence — CRUD over the ``strategy_presets`` table.

Each preset captures a *future-resolvable* trade idea: ticker, strategy
template name, leg specification (strikes / expiries / qty), thesis,
and a scaling plan. Stored as JSON in DuckDB so the catalogue can
evolve without schema churn. Loaded on demand by the Options Lab
sidebar.

The store is intentionally tiny: presets are a personal trade journal,
not a transaction log.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

log = logging.getLogger(__name__)


# ── Dataclasses ─────────────────────────────────────────────────────

@dataclass
class ScalingTranche:
    """One layer of a multi-stage entry plan.

    Attributes
    ----------
    trigger : human-readable rule that decides when the tranche fires
              ("now", "PYPL < 60", "VIX > 25", "-15 % drawdown").
    qty_pct : fraction of total position size (sums to 1.0 across all
              tranches in a plan).
    notes   : free-form one-liner for journaling.
    """
    trigger:  str
    qty_pct:  float
    notes:    str = ""


@dataclass
class StrategyPreset:
    """One saved trade idea. ``id`` is the human-readable slug."""
    id:             str
    ticker:         str
    strategy_name:  str
    legs_spec:      dict[str, Any]       # template-specific knobs
    thesis:         str
    scaling_plan:   list[ScalingTranche] = field(default_factory=list)
    created_at:     Optional[datetime]   = None
    notes:          str = ""


# ── JSON helpers ────────────────────────────────────────────────────

def _legs_to_json(legs_spec: dict[str, Any]) -> str:
    return json.dumps(legs_spec, default=str)


def _plan_to_json(plan: list[ScalingTranche]) -> str:
    return json.dumps([asdict(t) for t in plan])


def _legs_from_json(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _plan_from_json(raw: Optional[str]) -> list[ScalingTranche]:
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        return []
    out: list[ScalingTranche] = []
    for r in rows:
        try:
            out.append(ScalingTranche(
                trigger=str(r.get("trigger", "")),
                qty_pct=float(r.get("qty_pct", 0.0)),
                notes=str(r.get("notes", "")),
            ))
        except Exception:
            continue
    return out


# ── CRUD ────────────────────────────────────────────────────────────

def upsert_preset(db, preset: StrategyPreset, *, overwrite: bool = False) -> None:
    """Insert or replace a preset row.

    By default the seeder calls this with ``overwrite=False`` and the
    INSERT OR IGNORE keeps the row stable so user-edited thesis text
    doesn't get clobbered. The UI's "save preset" call passes
    ``overwrite=True``.
    """
    payload = (
        preset.id,
        preset.ticker,
        preset.strategy_name,
        _legs_to_json(preset.legs_spec),
        preset.thesis,
        _plan_to_json(preset.scaling_plan),
        preset.notes,
    )
    if overwrite:
        db.con.execute(
            """
            INSERT OR REPLACE INTO strategy_presets
                (id, ticker, strategy_name, legs_spec_json,
                 thesis, scaling_plan_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        return
    # INSERT OR IGNORE keyword is unsupported by some DuckDB builds —
    # use ON CONFLICT for portability.
    db.con.execute(
        """
        INSERT INTO strategy_presets
            (id, ticker, strategy_name, legs_spec_json,
             thesis, scaling_plan_json, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        payload,
    )


def get_preset(db, preset_id: str) -> Optional[StrategyPreset]:
    df = db.con.execute(
        "SELECT * FROM strategy_presets WHERE id = ?", [preset_id],
    ).fetchdf()
    if df.empty:
        return None
    return _row_to_preset(df.iloc[0])


def list_presets(db, *, ticker: Optional[str] = None) -> list[StrategyPreset]:
    if ticker is not None:
        df = db.con.execute(
            "SELECT * FROM strategy_presets WHERE ticker = ? ORDER BY created_at DESC",
            [ticker],
        ).fetchdf()
    else:
        df = db.con.execute(
            "SELECT * FROM strategy_presets ORDER BY created_at DESC",
        ).fetchdf()
    return [_row_to_preset(r) for _, r in df.iterrows()]


def delete_preset(db, preset_id: str) -> None:
    db.con.execute("DELETE FROM strategy_presets WHERE id = ?", [preset_id])


def _row_to_preset(row: pd.Series) -> StrategyPreset:
    return StrategyPreset(
        id=str(row["id"]),
        ticker=str(row["ticker"]),
        strategy_name=str(row["strategy_name"]),
        legs_spec=_legs_from_json(row.get("legs_spec_json")),
        thesis=str(row.get("thesis") or ""),
        scaling_plan=_plan_from_json(row.get("scaling_plan_json")),
        created_at=(
            pd.to_datetime(row.get("created_at")).to_pydatetime()
            if row.get("created_at") is not None and pd.notna(row.get("created_at"))
            else None
        ),
        notes=str(row.get("notes") or ""),
    )
