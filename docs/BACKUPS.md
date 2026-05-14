# Backups

## What we back up

The single source of truth is `~/Library/Application Support/VolScope/volscope.db`.
A daily snapshot is kept for 30 days.

## What we DON'T back up

- `.venv/` — reproducible from `pyproject.toml` + `uv lock`.
- `data/` — empty placeholder.
- Logs older than 30 days — rotated by the logger config.

## Backup procedure (daily, scheduled)

A launchd plist (or cron entry on Linux) runs nightly at 02:00 local time:

```bash
SRC="$HOME/Library/Application Support/VolScope/volscope.db"
DST_DIR="$HOME/Library/Application Support/VolScope/backups"
mkdir -p "$DST_DIR"
DST="$DST_DIR/volscope-$(date +%Y%m%d).db"
cp "$SRC" "$DST"
# Retention: 30 days
find "$DST_DIR" -name 'volscope-*.db' -mtime +30 -delete
```

Add to launchd as `de.volscope.backup-daily.plist` modelled on
`memory/ops/cron-roster.md` entry format.

## Restore procedure (tested quarterly)

1. Stop any running VolScope process (Streamlit UI, scheduler).
2. `make unlock` to release the DuckDB lock.
3. `cp $DST_DIR/volscope-YYYYMMDD.db "$SRC"` (back-rename).
4. `pytest tests/test_persistence_db.py -q` — smoke that the schema
   loads.
5. Start the UI: `make run`.

## Pre-restore safety

Always `cp $SRC $SRC.prerestore-$(date +%Y%m%d%H%M)` before overwriting,
so you can revert if the chosen backup is itself corrupt.

## Tested? When?

| Date | Tested by | Result |
|---|---|---|
| _TBD_ | _TBD_ | _Initial test scheduled in Phase 2 go-live week_ |
