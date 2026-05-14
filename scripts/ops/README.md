# scripts/ops/

Operational scripts: setup, locks, autonomous loop.

- `seed_database.py` — initial DB hydration.
- `load_universe.py` — ticker universe loader.
- `release_db_lock.py` — emergency DB-lock release.
- `keep_warm.sh` — warm iCloud-cold .py caches.
- `loop_iteration.py` — autonomous Maturity Loop driver.
- `preflight.py` (Phase 2) — pre-startup gate.
- `reconcile.py` (Phase 2) — DB ↔ IBKR state diff.
