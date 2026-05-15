.PHONY: setup test run start scrape convergence seed seed-starter seed-full seed-bot-universe seed-broad-universe quickstart clean verify verify-all sectors \
        audit audit-list audit-schema synth maturity loop loop-pick loop-finalize loop-forever pause unpause \
        simulate validate autonomy-status autonomy-pause autonomy-unpause autonomy-test autonomy-logs \
        load-universe load-universe-resume design-lint backtest-leaps \
        unlock kill-stale fresh warm repair-iv

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
# lock, seeds the Broad Universe (75 tickers: Bot Universe + S&P-500
# big-cap representatives + S&P-400 mid-cap names with liquid options),
# launches the UI in headless mode (no stdin block, no telemetry).
# Total runtime on a fresh checkout: ~4 minutes.
quickstart:
	@bash scripts/ops/keep_warm.sh
	pip install -q -r requirements.txt
	pip install -q -e .                                    # makes volscope importable from anywhere
	@python scripts/ops/release_db_lock.py --force
	$(MAKE) seed-broad-universe
	$(MAKE) run

# ── Individual stages ───────────────────────────────────────────────
setup:
	pip install -r requirements.txt
	pip install -e .                                       # editable install: scripts/ can `import volscope`

test:
	python -m pytest tests/ -v --tb=short

verify:
	python scripts/verify/verify.py

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

# Walk-forward backtest of the LEAPS-convergence rule.
# Default: 365-day hold, monthly resampling, full universe.
backtest-leaps:
	python scripts/backtest/run_leaps_backtest.py

# Aggregate daily_vol into sector_daily and classify regimes.
# Run after each daily scrape to keep Rotation page current.
sectors:
	python scripts/compute/compute_sector_rotation.py

clean:
	rm -f data/volscope.db

# ── Maturity Loop ───────────────────────────────────────────────────
# Self-perpetuating audit + improve cycle. See plans/beginne-nun-mit-dem-cheeky-noodle.md
# for the design.

# Emit the 4 audit-agent prompt templates.
audit:
	python scripts/backtest/run_audits.py --emit

audit-list:
	python scripts/backtest/run_audits.py --list

audit-schema:
	python scripts/backtest/run_audits.py --schema

# Re-rank queue from latest audit JSONs.
synth:
	python scripts/ops/loop_iteration.py --synthesize-only

# Compute and persist a maturity score.
maturity:
	python scripts/audit/maturity_check.py

# Single iteration — pick top issue, print instruction, exit. Implementer
# (Claude or human) edits code, runs `make verify`, then `make loop-finalize`.
loop:
	python scripts/ops/loop_iteration.py --phase pick

loop-pick:
	python scripts/ops/loop_iteration.py --phase pick

# After implementation: run verify + maturity + record.
loop-finalize:
	@touch data/audit/.done
	python scripts/ops/loop_iteration.py --phase finalize

# Outer while-loop. Stops at maturity ≥ 95 OR pause-marker present OR
# verify failure. Implementer must signal completion via `touch data/audit/.done`
# between iterations (this is the pure-bash variant; Claude-driven variants
# use the ralph-loop plugin instead).
loop-forever:
	@while true; do \
	  if [ -f $$HOME/.volscope_loop_pause ]; then \
	    echo "[loop] paused — exiting"; break; \
	  fi; \
	  python scripts/ops/loop_iteration.py --phase pick || break; \
	  echo "[loop] waiting for implementation (touch data/audit/.done to continue) ..."; \
	  while [ ! -f data/audit/.done ]; do sleep 5; done; \
	  python scripts/ops/loop_iteration.py --phase finalize; \
	  rc=$$?; \
	  if [ $$rc -eq 9 ]; then echo "[loop] MATURE — stopping"; break; fi; \
	  if [ $$rc -ne 0 ]; then echo "[loop] iteration failed (rc=$$rc) — stopping"; break; fi; \
	done

pause:
	@touch $$HOME/.volscope_loop_pause
	@echo "[loop] paused — file created at ~/.volscope_loop_pause"

unpause:
	@rm -f $$HOME/.volscope_loop_pause
	@echo "[loop] unpaused"

# Strategy backtest simulation — produces calibrated hit-rates for Kelly sizer.
simulate:
	python scripts/backtest/run_strategy_simulation.py

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

# Data validator (Pillar 2) — runs 5-check validator over universe + persists.
validate:
	python scripts/backtest/run_validation.py

# ── Autonomy (launchd) ──────────────────────────────────────────────
# Cross-session autonomous loops via macOS launchd plists.
# See ~/.claude/projects/-Users-tomschoen/memory/volscope-cron-roster.md.

autonomy-status:
	@echo "── Loaded launchd jobs:"
	@launchctl list | grep volscope | sort || echo "  (none)"
	@echo ""
	@echo "── Last-run summaries:"
	@ls -1 $$HOME/.claude/volscope-cron-logs/*-last.summary 2>/dev/null \
	  | xargs -I {} sh -c 'echo "$$(basename {}):" && cat {} && echo' \
	  || echo "  (no summaries yet)"
	@echo ""
	@echo "── Pause marker:"
	@if [ -f $$HOME/.volscope_loop_pause ]; then \
	  echo "  PAUSED ($$HOME/.volscope_loop_pause exists)"; \
	else \
	  echo "  active"; \
	fi

autonomy-pause:
	@touch $$HOME/.volscope_loop_pause
	@echo "[autonomy] paused — all future cron fires will exit immediately"

autonomy-unpause:
	@rm -f $$HOME/.volscope_loop_pause
	@echo "[autonomy] unpaused — next cron fire resumes work"

# Foreground test invocation. Default mode=loop. Override: make autonomy-test MODE=audit
MODE ?= loop
autonomy-test:
	@$$HOME/.claude/volscope-cron-prompt.sh $(MODE)

autonomy-logs:
	@ls -lt $$HOME/.claude/volscope-cron-logs/ | head -20

# ── v0.5.0 operational targets ──────────────────────────────────
backup:
	@.venv/bin/python -m scripts.ops.backup_db

backup-encrypted:
	@.venv/bin/python -m scripts.ops.backup_db --encrypt

restore-drill:
	@.venv/bin/python -m scripts.ops.restore_db --temp

audit-verify:
	@.venv/bin/python -m scripts.audit.verify_chain

pre-merge-check:
	@echo "── ruff ──" && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	@echo "── mypy (new packages) ──" && .venv/bin/mypy --strict --ignore-missing-imports \
		volscope/signals volscope/risk volscope/lifecycle \
		volscope/execution volscope/scheduler volscope/persistence || true
	@echo "── pytest fast ──" && .venv/bin/python -m pytest \
		-m "not slow and not integration and not perf and not ibkr" \
		--tb=short -q
	@echo "── audit-chain verify ──" && \
		(.venv/bin/python -m scripts.audit.verify_chain 2>&1 || echo "(no DB yet — OK on fresh)")
	@echo "── risk-thresholds unchanged ──" && \
		.venv/bin/python scripts/audit/check_risk_thresholds_unchanged.py

# ── v0.6.0 data foundation + math gate + agent orchestration ──
migrate:
	@.venv/bin/python -m scripts.ops.apply_migrations

migrate-dry-run:
	@.venv/bin/python -m scripts.ops.apply_migrations --dry-run

scrape-chains:
	@.venv/bin/python -m scripts.scrape.scrape_chains

full-review:
	@.venv/bin/python -m scripts.ops.full_review $(if $(REF),--ref $(REF))

compute-sectors:
	@.venv/bin/python -m scripts.compute.compute_sector_rotation

# ── v0.6.1 IV robustness ─────────────────────────────────────
compute-iv-quality:
	@.venv/bin/python -m scripts.compute.compute_iv_quality

quality-audit:
	@.venv/bin/python -m scripts.compute.compute_iv_quality --dry-run --verbose
