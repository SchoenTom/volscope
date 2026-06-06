.PHONY: setup test run start scrape convergence seed seed-starter seed-full seed-bot-universe seed-broad-universe quickstart quickstart-bot clean verify-all sectors \
        load-universe load-universe-resume design-lint \
        unlock kill-stale fresh warm repair-iv backup backup-encrypted restore-drill migrate

# ── Lock hygiene ────────────────────────────────────────────────────────
# The DuckDB exclusive lock is the single most common reason `make start`
# fails — usually because an autonomous launchd job (5 daily + 3 weekly)
# is in the middle of a scrape, or a previous Streamlit died without
# closing its connection. `make unlock` finds the holders and kills them.

unlock:
	@python scripts/ops/release_db_lock.py --force

kill-stale: unlock

# ── iCloud cache warmup ─────────────────────────────────────────────
# Touches every .py + .so in the repo + .venv so iCloud File Provider
# materialises them locally. Eliminates the 30-90s cold-import stall
# that kills pytest and Streamlit boot on Desktop-synced installs.
warm:
	@bash scripts/ops/keep_warm.sh

# ── Data repair ─────────────────────────────────────────────────────
# Fills iv_30d on rows where daily_scrape wrote NULL (chain fetch
# failed but row got upserted anyway). Walks back to last non-null
# iv_30d per ticker, falls back to HV-YZ × VRP proxy if no history.
# Idempotent — safe to run repeatedly.
repair-iv:
	python scripts/ops/repair_null_iv.py

# ── Quick Start ─────────────────────────────────────────────────────
# One command, zero decisions. Installs deps, releases any stale DB
# v0.9.11 — make quickstart now boots fast (target: ≤ 2 min).
# Seeds your existing watchlist tickers if any, falls back to SPY +
# QQQ as a sensible 2-ticker baseline. Operator can grow the universe
# from the sidebar's add-ticker form or by importing a TradingView
# watchlist (📥 Import on the Watchlist page).
#
# WHY this changed: the old quickstart ran seed-full (842 tickers,
# ~30 min). Operator hit the wall on 2026-05-19 ("ich finde der
# loader brauchst etwas lange... können wir das ursprünglich
# geladene set verkleinern dass volscope in so 1-2 min startet?").
#
# Three alternatives still available for bigger seeds:
#   - make quickstart-bot   → ~75 tickers, ~4 min
#   - make seed-broad       → ~280 tickers, ~10 min
#   - make seed-full        → ~842 tickers, ~30-45 min
quickstart:
	@echo "[1/4] installing dependencies …"
	pip install -q --upgrade pip
	pip install -q -r requirements.txt
	pip install -q -e .                                    # makes volscope importable from scripts/
	@test -f .env || (cp .env.example .env && echo "[2/4] created .env (read-only research mode — API keys optional)")
	@python scripts/ops/release_db_lock.py --force
	@echo "[3/4] seeding a starter universe (SPY + QQQ if no watchlist) …"
	$(MAKE) seed-watchlist
	@echo "[4/4] launching VolScope at http://localhost:8501 …"
	$(MAKE) run

# Legacy: full 842-ticker seed. Now an explicit opt-in.
quickstart-full:
	@bash scripts/ops/keep_warm.sh
	pip install -q -r requirements.txt
	pip install -q -e .
	@python scripts/ops/release_db_lock.py --force
	$(MAKE) seed-full
	$(MAKE) run

# Faster alternative for when 30+ min is too much — Bot Universe only.
quickstart-bot:
	@bash scripts/ops/keep_warm.sh
	pip install -q -r requirements.txt
	pip install -q -e .
	@python scripts/ops/release_db_lock.py --force
	$(MAKE) seed-broad-universe
	$(MAKE) run

# ── make quickstart-fast — 2-minute boot ────────────────────────────
# Operator feedback 2026-05-16: "VolScope sollte in 2 min ladbar sein".
# Seeds ONLY SPY (most-traded ETF, single-ticker baseline). The user
# then grows the universe from the sidebar's quick-add form or by
# importing a TradingView watchlist. Skips the dependency install
# step on the assumption it has already happened — if you need a
# from-scratch setup, run `make setup` first.
quickstart-fast:
	@python scripts/ops/release_db_lock.py --force
	python scripts/ops/seed_database.py --tickers SPY
	$(MAKE) run

# Minimal NDX-only seed (single ticker QQQ) — even faster alternative.
seed-minimal:
	python scripts/ops/seed_database.py --tickers QQQ

# Seed from your existing watchlists (whatever tickers you've added).
# Falls back to SPY if no watchlists exist yet.
seed-watchlist:
	python scripts/ops/seed_from_watchlist.py

# ── Individual stages ───────────────────────────────────────────────
setup:
	pip install -r requirements.txt
	pip install -e .                                       # editable install: scripts/ can `import volscope`

test:
	python -m pytest tests/ -v --tb=short

# ── verify-all ──────────────────────────────────────────────────────────
# Runs every correctness + reliability gate in sequence and writes a
# JSON report to data/verify/latest.json. Exit 0 only if every
# correctness gate passes. The single command that proves VolScope works.
verify-all:
	python scripts/verify/verify_all.py

run:
	@# Hardened start — disables Streamlit's first-run email prompt (which blocks
	@# on stdin if not yet acknowledged) and the telemetry beacon. These two
	@# together caused silent hangs where the server appeared to start but never
	@# served a request. See CLAUDE.md "Streamlit headless ritual".
	streamlit run volscope/ui/app.py \
		--server.headless true \
		--browser.gatherUsageStats false \
		</dev/null

# `make start` — daily ritual.  Three steps, every time:
#   1. release any stale DB lock (autonomous launchd job, dead streamlit)
#   2. refresh today's snapshot (incremental — fast if already fresh)
#   3. boot the UI in hardened headless mode
# Replaces the user's manual "kill the lock, scrape, run" sequence.
start:
	@python scripts/ops/release_db_lock.py --force
	@$(MAKE) -s scrape || echo '[start] scrape skipped (network or upstream issue) — booting on existing data'
	$(MAKE) run

# `make fresh` — destructive refresh. Force a full re-scrape even when
# today's data already exists. Use after a partial scrape, after a Yahoo
# outage, or any time you want a clean snapshot.
fresh:
	@python scripts/ops/release_db_lock.py --force
	python scripts/scrape/daily_scrape.py
	python scripts/compute/compute_convergence_daily.py
	$(MAKE) run

# Minimal 8-ticker seed — legacy entrypoint kept for back-compat with
# external docs and existing setups. Prefer `seed-bot-universe`.
seed-starter:
	python scripts/ops/seed_database.py --tickers SPY,QQQ,AAPL,NVDA,TSLA,META,GLD,TLT

# Bot Universe seed (19 tickers, ~70 s) — what the trading bot is allowed
# to touch:
#   - Tier-1 ETFs (SPY/QQQ/IWM): index proxies, always tradable
#   - Tier-2 megacap tech (AAPL/MSFT/AMZN/NVDA/GOOGL/META/AMD/QCOM/MU):
#     statistical IV mean-reversion confirmed (Castillo & Mira-McWilliams 2026)
#   - Tier-3 sector ETFs (XLE/XLF/XLK/XLV/EWZ): broad sector exposure
#   - Macro anchors (GLD/TLT): gold + duration for regime context
# Source-of-truth: config/tickers.yaml. SPX/XSP intentionally excluded
# from the seed since Yahoo OHLCV for indices is unreliable; the bot
# trades them via IBKR chains separately.
seed-bot-universe:
	python scripts/ops/seed_database.py --tickers SPY,QQQ,IWM,AAPL,MSFT,AMZN,NVDA,GOOGL,META,AMD,QCOM,MU,XLE,XLF,XLK,XLV,EWZ,GLD,TLT

# Broad Universe seed (75 tickers, ~3 min) — Bot Universe + S&P-500
# Big-Cap representatives across sectors + S&P-400 Mid-Cap names with
# liquid options. This is what `make quickstart` uses so Discover /
# Heatmap have meaningful breadth on a fresh checkout.
#
#   Big Cap additions (31): financials, healthcare, staples, energy,
#   industrials, communications, semis — sector-diversified beyond the
#   Tier-2 megacap-tech list. Includes PYPL so the operator can see the
#   thesis LEAPS context out of the box.
#
#   Mid Cap additions (25): high-beta names with liquid weekly options
#   — fintech, cloud, security, airlines, materials. Cover the
#   risk-on / risk-off spectrum that the bot's regime classifier needs.
#
# `blocked` tickers from config/tickers.yaml (TSLA / BNTX / MRNA /
# MSTR / GME) are intentionally OUT — they don't IV-mean-revert.
seed-broad-universe:
	python scripts/ops/seed_database.py --tickers \
SPY,QQQ,IWM,XLE,XLF,XLK,XLV,EWZ,GLD,TLT,\
AAPL,MSFT,AMZN,NVDA,GOOGL,META,AMD,QCOM,MU,\
BRK-B,V,JPM,JNJ,WMT,PG,MA,UNH,HD,BAC,\
XOM,CVX,KO,PEP,ABBV,AVGO,COST,MRK,NFLX,ADBE,\
CRM,ORCL,PYPL,INTC,IBM,T,VZ,DIS,MCD,NKE,BA,\
SNAP,ROKU,ABNB,SHOP,PLTR,COIN,HOOD,AFRM,NET,DDOG,\
SNOW,MDB,CRWD,PANW,ZS,FTNT,OKTA,ANET,DAL,UAL,\
AAL,F,GE,CAT,DE

# Full universe seed — all 280+ curated tickers. Takes several minutes.
seed-full:
	python scripts/ops/seed_database.py

# Alias — `make seed` keeps its historical meaning (full seed) so existing
# users and cron setups don't break.
seed: seed-full

# Daily scrape — fetches live options chains and upserts IV into the DB.
# Always preceded by an automatic lock-release so the user never sees
# the "Conflicting lock" duckdb error on a normal start. Always followed
# by `convergence` so the alert engine and the LEAPS Lab see fresh
# scores in the same session.
scrape:
	@python scripts/ops/release_db_lock.py --force
	python scripts/scrape/daily_scrape.py
	$(MAKE) convergence

# Recompute convergence scores for the latest snapshot. Idempotent.
convergence:
	python scripts/compute/compute_convergence_daily.py

# Aggregate daily_vol into sector_daily and classify regimes.
# Run after each daily scrape to keep Rotation page current.
sectors:
	python scripts/compute/compute_sector_rotation.py

clean:
	rm -f data/volscope.db

# Robust bulk universe loader (Pillar A) — idempotent, retry, resume.
load-universe:
	python scripts/ops/load_universe.py

load-universe-resume:
	python scripts/ops/load_universe.py --resume

# Design-token drift linter (Pillar D). Baseline 70 = current legacy
# inline-hex usage frozen; new code MUST be clean. Any PR that pushes
# the count above 70 fails.
design-lint:
	python scripts/audit/audit_design_drift.py --max 70

# ── v0.5.0 operational targets ──────────────────────────────────
backup:
	@.venv/bin/python -m scripts.ops.backup_db

backup-encrypted:
	@.venv/bin/python -m scripts.ops.backup_db --encrypt

restore-drill:
	@.venv/bin/python -m scripts.ops.restore_db --temp

pre-merge-check:
	@echo "── ruff ──" && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	@echo "── mypy (core packages) ──" && .venv/bin/mypy --ignore-missing-imports \
		volscope/analytics volscope/data || true
	@echo "── pytest fast ──" && .venv/bin/python -m pytest \
		-m "not slow and not integration and not perf and not ibkr" \
		--tb=short -q

# ── v0.6.0 data foundation + math gate + agent orchestration ──
migrate:
	@.venv/bin/python -m scripts.ops.apply_migrations

migrate-dry-run:
	@.venv/bin/python -m scripts.ops.apply_migrations --dry-run

scrape-chains:
	@.venv/bin/python -m scripts.scrape.scrape_chains

compute-sectors:
	@.venv/bin/python -m scripts.compute.compute_sector_rotation

# ── v0.6.1 IV robustness ─────────────────────────────────────
compute-iv-quality:
	@.venv/bin/python -m scripts.compute.compute_iv_quality

quality-audit:
	@.venv/bin/python -m scripts.compute.compute_iv_quality --dry-run --verbose
