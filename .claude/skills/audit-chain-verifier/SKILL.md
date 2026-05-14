---
name: audit-chain-verifier
description: This skill should be used when working with the hash-chained audit log — appending entries, verifying integrity, or interpreting a chain break.
---

# Audit chain — SHA-256 prev_hash + orjson canonical

## Invariant

Every load-bearing bot event (signal emit, order intent, fill, kill
trip / reset) appends one row to `bot_audit_chain` with:

```
entry_hash = SHA-256(orjson.dumps(payload, OPT_SORT_KEYS) || prev_hash)
```

Tampering with any row breaks the chain at that seq and every seq
after. `verify_chain()` replays from row 1 to find the first break.

## Allowed kinds (CHAIN_KINDS in audit_chain.py)

- `signal` — composite-scored signal emitted by the ranker
- `order_intent` — pre-trade UUID-keyed intent created
- `order_submitted` — paper engine or live broker accepted
- `fill` — leg fills came back
- `kill_trip` — kill switch tripped (manual or auto)
- `kill_reset` — operator reset with the literal token

Adding a new kind requires updating `CHAIN_KINDS` in
`volscope/persistence/audit_chain.py` + an ADR justifying the addition.

## How to append

```python
from volscope.persistence.audit_chain import append
entry_hash = append(db, kind="signal", payload={
    "ticker": "SPY",
    "direction": "short_vol",
    "composite_score": 82.5,
    "reason": "TRIPLE_RICH + p_calm 0.81",
})
```

**Payload must be JSON-serialisable.** orjson handles `datetime`, `Decimal`,
`numpy.float64` natively; do NOT pre-serialize. Custom types: convert
to dict first.

## How to verify

```python
from volscope.persistence.audit_chain import verify_chain
ok, break_seq = verify_chain(db)
if not ok:
    # break_seq is the FIRST row that fails. Everything after seq is suspect.
    ...
```

CLI: `python -m scripts.audit.verify_chain` — exits 0 on valid, 1 on
break, 2 on DB unreadable.

## What breaks the chain

- Manual UPDATE / DELETE on `bot_audit_chain` rows.
- Inserting rows out of order (DuckDB sequence guarantees order; don't
  override `seq`).
- Changing `prev_hash` or `entry_hash` columns directly.
- Replacing the orjson library with a non-deterministic JSON
  serializer (the canonical-key-sort invariant is what makes hashes
  reproducible).

## What does NOT break the chain

- Adding new rows via `append()` (genesis is fine; chain grows).
- Reading rows.
- Backing up + restoring (hashes survive).
- Changing the CHAIN_KINDS set (existing rows still verify).

## Operator response to a break

1. Capture `break_seq` from the verifier.
2. `SELECT * FROM bot_audit_chain WHERE seq >= <break_seq>` — list of
   suspect rows.
3. **Do not delete them.** Forensic value is in keeping the broken
   chain intact.
4. Surface in operator dashboard with red banner.
5. Create a new chain from a known-good prior export by:
   - `EXPORT DATABASE` the suspect DB for forensics.
   - Restore from the most recent verified-OK backup.
   - Append a `kill_trip` row with `reason="chain break detected at
     seq=<break_seq>"`.
6. Open a Post-Mortem entry in `docs/post-mortems/`.

## Daily git-tag anchor (operational pattern)

```bash
HASH=$(python -m scripts.audit.verify_chain --print-latest)
git tag "audit-anchor-$(date +%Y-%m-%d)" -m "audit chain head: $HASH"
git push --tags
```

This makes the chain head publicly anchorable in immutable git
history — useful for tax + dispute defense (§147 AO 10-year rule).
