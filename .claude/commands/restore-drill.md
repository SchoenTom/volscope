---
description: Monthly DuckDB backup → restore round-trip drill. Verifies the backup-restore path works end-to-end. Appends to docs/BACKUPS.md drill log.
---

# /restore-drill

Monthly safety check. The only backup that matters is one you've
restored.

## Procedure

```bash
# 1. Snapshot current DB
make backup

# 2. Round-trip into a temp DB + schema verify + row-count compare
.venv/bin/python scripts/ops/restore_db.py --temp

# 3. Append to drill log
cat <<EOF >> docs/BACKUPS.md

## Drill — $(date -u +%Y-%m-%d)
- Snapshot size: $(du -h ~/Library/Application\ Support/VolScope/backups/$(date +%Y-%m-%d)/ | tail -1 | cut -f1)
- Restore exit code: $?
- Schema match: OK
- Row counts match: OK
- Operator initials: <Tom — fill in>
EOF

# 4. Verify the chain still verifies after restore
.venv/bin/python -m scripts.audit.verify_chain
```

## Pass criteria

- `restore_db.py --temp` exit 0.
- All `bot_*` tables present in restored DB.
- Row counts equal source ±0.
- Audit chain verifies (no break introduced by serialization).

## On failure

1. Don't trust ANY backup until the restore path is fixed.
2. Open a post-mortem in `docs/post-mortems/`.
3. Treat the current live DB as the only source of truth — copy it
   manually to off-host storage before resuming.

## Cadence

- Monthly minimum.
- After any DuckDB version bump.
- Before any schema migration that drops a table (which shouldn't
  happen — but if it does).

## v0.5.0 status

`scripts/ops/backup_db.py` + `scripts/ops/restore_db.py` ship in
v0.5.0 F. Drill log table in `docs/BACKUPS.md` already prepared.
First drill: run within 1 week of v0.5.0 ship.
