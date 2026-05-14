"""
Hash-chained tamper-evident audit log — v0.5.0.

Every load-bearing event in the bot loop (signal emit, order intent
created, order submitted, fill received, kill-switch trip or reset)
calls ``append()``. Each row stores:

    seq        — autoincrementing primary key
    ts         — UTC timestamp
    kind       — categorical tag
    payload    — full event body, serialised via orjson with OPT_SORT_KEYS
    prev_hash  — hex SHA-256 of the previous row's entry_hash
    entry_hash — hex SHA-256 of (canonical_payload || prev_hash)

Tampering with any row breaks the chain at that seq and every seq
after it; ``verify_chain()`` replays to find the first break.

Genesis row uses prev_hash = "0" * 64.

References:
- SHA-256 audit-log pattern is the SEC 17a-4 "Write-Once Read-Many"
  approximation in storage-agnostic form.
- Deterministic JSON via orjson OPT_SORT_KEYS is the only way to
  reproduce the same hash across machines + languages.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import orjson

GENESIS_PREV_HASH = "0" * 64
"""Hash used by the first row of every fresh chain."""

CHAIN_KINDS = frozenset({
    "signal",
    "order_intent",
    "order_submitted",
    "fill",
    "kill_trip",
    "kill_reset",
})


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """orjson with sorted keys — same input always yields same bytes."""
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_NAIVE_UTC)


def _compute_hash(payload_bytes: bytes, prev_hash: str) -> str:
    h = hashlib.sha256()
    h.update(payload_bytes)
    h.update(prev_hash.encode("ascii"))
    return h.hexdigest()


def append(db, *, kind: str, payload: dict[str, Any]) -> str:
    """
    Append one row to ``bot_audit_chain``.

    Returns the new row's ``entry_hash`` so the caller can log /
    expose it for git-tag anchoring.

    Raises ``ValueError`` if ``kind`` is not in ``CHAIN_KINDS``.
    """
    if kind not in CHAIN_KINDS:
        raise ValueError(f"unknown audit kind: {kind!r} (allowed: {sorted(CHAIN_KINDS)})")

    payload_bytes = _canonical_bytes(payload)
    payload_str = payload_bytes.decode("utf-8")

    # Single SQL trip: read prev_hash + insert atomically. DuckDB's
    # default isolation is serializable for a single connection so we
    # don't need an explicit transaction wrapper.
    row = db.con.execute("""
        SELECT entry_hash FROM bot_audit_chain
        ORDER BY seq DESC LIMIT 1
    """).fetchone()
    prev_hash = row[0] if row else GENESIS_PREV_HASH

    entry_hash = _compute_hash(payload_bytes, prev_hash)
    ts = datetime.now(tz=timezone.utc)

    db.con.execute("""
        INSERT INTO bot_audit_chain (ts, kind, payload, prev_hash, entry_hash)
        VALUES (?, ?, ?, ?, ?)
    """, [ts, kind, payload_str, prev_hash, entry_hash])
    return entry_hash


def verify_chain(db) -> tuple[bool, int | None]:
    """
    Replay the chain from row 1; verify every entry_hash matches.

    Returns:
        (True, None) if the whole chain is valid.
        (False, seq) where ``seq`` is the first row that fails.
    """
    rows = db.con.execute("""
        SELECT seq, payload, prev_hash, entry_hash
        FROM bot_audit_chain
        ORDER BY seq
    """).fetchall()
    if not rows:
        return True, None

    expected_prev = GENESIS_PREV_HASH
    for seq, payload_str, prev_hash, entry_hash in rows:
        if prev_hash != expected_prev:
            return False, int(seq)
        try:
            payload_dict = orjson.loads(payload_str)
        except orjson.JSONDecodeError:
            return False, int(seq)
        recomputed = _compute_hash(_canonical_bytes(payload_dict), prev_hash)
        if recomputed != entry_hash:
            return False, int(seq)
        expected_prev = entry_hash
    return True, None


def latest_hash(db) -> str:
    """Hex SHA-256 of the most recent row's entry_hash; genesis if empty."""
    row = db.con.execute("""
        SELECT entry_hash FROM bot_audit_chain ORDER BY seq DESC LIMIT 1
    """).fetchone()
    return row[0] if row else GENESIS_PREV_HASH


def length(db) -> int:
    """Count rows in the chain (for diagnostics + drill reports)."""
    return int(db.con.execute(
        "SELECT COUNT(*) FROM bot_audit_chain"
    ).fetchone()[0])
