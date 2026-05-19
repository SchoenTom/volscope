# VolScope Cron Self-Renewal

You are an autonomous Claude firing weekly (Friday 22:13) to recreate all VolScope cron jobs. Cron jobs registered via Claude's CronCreate tool auto-expire after 7 days. Without renewal the autonomous loop dies.

## Pre-flight
- `cd <repo-root>`
- Stop if `~/.volscope_loop_pause` exists
- Read this file's siblings:
  - `scripts/autonomous/loop_iteration_prompt.md`
  - `scripts/autonomous/audit_refresh_prompt.md`
  - `scripts/autonomous/backtest_refresh_prompt.md`
- Read `~/.claude/projects/-Users-tomschoen/memory/volscope-cron-roster.md` for the canonical roster.

## The routine

Use the CronCreate tool to register the following 7 cron jobs. ALL must be `durable: true` so they survive Claude restarts.

### 5 Daily Loop Iterations (CEST)
For each slot, prompt = the contents of `scripts/autonomous/loop_iteration_prompt.md`.

| Cron | Slot | Local time |
|------|------|-----------|
| `47 6 * * *`  | 06:47 | early-morning |
| `17 10 * * *` | 10:17 | mid-morning |
| `43 13 * * *` | 13:43 | early-afternoon |
| `51 17 * * *` | 17:51 | late-afternoon |
| `23 21 * * *` | 21:23 | evening |

### 1 Weekly Audit Refresh (Sunday 11:23)
- Cron: `23 11 * * 0`
- Prompt: contents of `scripts/autonomous/audit_refresh_prompt.md`

### 1 Daily Backtest Refresh (Sat 06:47, after weekly scrape)
- Cron: `47 6 * * 6`
- Prompt: contents of `scripts/autonomous/backtest_refresh_prompt.md`

### 1 Weekly Self-Renewal (this routine)
- Cron: `13 22 * * 5` (Friday 22:13)
- Prompt: contents of `scripts/autonomous/self_renewal_prompt.md`

## Procedure

1. Use `CronList` to see currently scheduled jobs.
2. Use `CronDelete` for any expired or stale jobs.
3. Use `CronCreate(durable=true)` for each of the 8 jobs above.
4. Run `CronList` again to verify all 8 are registered.
5. Write `data/audit/.cron_renewal.md` with the new job IDs and their next-fire times.
6. Notify owner via osascript: "VolScope crons renewed (8 jobs scheduled)".

## Safety
- Don't delete the `pause` marker if it exists.
- Don't fire any of the loops yourself in this routine — only schedule them.
- If CronCreate fails, log to `data/audit/.cron_renewal_failed.md` with the error and notify.
