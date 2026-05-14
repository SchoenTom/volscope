# Operator Guide

For the human running VolScope. Not for agents — agents read `WELCOME-AGENT.md`
and `memory/INDEX.md`.

## Starting the bot

```bash
# Pre-flight check (DB connectable, IBKR reachable, kill switch clear, ...)
python scripts/ops/preflight.py
# If exit code 0, start the scheduler
uv run python -m volscope.scheduler.cli start --mode paper
```

A green pre-flight means:

1. DuckDB connects + bot_* tables present.
2. IBKR Gateway/TWS reachable on configured port.
3. Kill switch NOT tripped (file flag, env var, DB row all clear).
4. No open positions with earnings in the next 14 days.
5. No `bot_trades` rows in mid-state from a prior dirty shutdown.

Any of these failing → exit non-zero and the bot refuses to start.

## Reading the dashboard

The Bot Dashboard (sidebar → DECISIONS → Bot) shows, top to bottom:

| Section | What to look at |
|---|---|
| Account strip | NLV, BPR%, cash reserve. Cash reserve <40% is yellow; <20% is red. |
| Greek strip | Portfolio Δ should be near zero for delta-neutral short-vol. Watch Vega — too negative means too short vol. |
| Regime | `p_calm > 0.7` = green light for short-vol entries. <0.4 = no new shorts. |
| Live signals | Sorted by composite score. Green = pass all gates; red = blocked (hover for reason). |
| Open trades | %-of-PT-reached + DTE remaining. 21-DTE is the hard close trigger. |
| Equity curve | Daily NLV from `bot_pnl_daily`. |

## Tripping the kill switch

Three manual paths — use whichever is fastest:

```bash
# Path 1: file flag (no DB required)
touch /var/run/volscope/KILL

# Path 2: env var (next process inherits)
export BOT_KILL=1

# Path 3: DB flag (works from any python shell)
python -c "from volscope.risk.kill_switch import KillSwitch; \
           KillSwitch(sticky_path=Path('/var/run/volscope/KILL')).trip('manual')"
```

On trip, the running scheduler:

1. Calls `ib.reqGlobalCancel()` — every open order cancelled.
2. Closes undefined-risk positions selectively (per config policy).
3. Sends a Telegram alert (if `TELEGRAM__BOT_TOKEN` is set).
4. Writes a sticky file at `/var/run/volscope/KILLED` with the reason.

The bot **will not auto-reset**. You must explicitly clear it.

## Resetting the kill switch

```bash
python -c "from volscope.risk.kill_switch import KillSwitch; \
           from pathlib import Path; \
           from datetime import date; \
           KillSwitch(sticky_path=Path('/var/run/volscope/KILL')).reset( \
               human_confirmation=f'I-RESET-VOLSCOPE-{date.today():%Y%m%d}')"
```

The literal `I-RESET-VOLSCOPE-<YYYYMMDD>` is required. Any other string
refused. This is intentional: typing the date forces you to acknowledge
"yes, today, I am resuming live trading."

## Post-mortem template

After any kill-switch trip or > 3% daily loss, write a post-mortem the
next morning (Sunday review window if it's a weekday):

```markdown
# Post-mortem — YYYY-MM-DD

## What happened
<1 sentence>

## Trigger
- Auto: drawdown / VIX / daily loss / IBKR disconnect / term inversion
- Manual: file / env / DB row

## Timeline (ET)
- HH:MM — first signal
- HH:MM — kill triggered
- HH:MM — orders cancelled / positions closed

## P&L impact
- Realized: $...
- Slippage on forced closes: $... ($/leg avg)

## Root cause
<1 paragraph>

## Action items
- [ ] Config change (mark for next Sunday review)
- [ ] Code fix (link PR)
- [ ] Process change (link to CONTRIBUTING update)
```

Commit post-mortems to `docs/post-mortems/YYYY-MM-DD.md`.

## Things you must NEVER do

1. **Roll a losing undefined-risk position** to defer realized loss.
   (Karen Bruton rule — SEC v. Hope Advisors 2016.)
2. **Change parameters intraday.** Config edits happen only in the
   Sunday 18:00 review window. The bot refuses parameter reloads at
   any other time.
3. **Force-push to main.** Branch protection forbids it; CONTRIBUTING.md
   documents the recovery procedure.
4. **Skip pre-flight.** If `preflight.py` exits non-zero, fix the issue
   — do not start the scheduler with `--skip-preflight`.
