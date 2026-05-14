---
name: VolScope Autonomous System (launchd)
description: Cross-session autonomous loops via macOS launchd plists — 8 jobs that perfect VolScope without a Claude session being open
type: project
originSessionId: 716ba485-d808-4974-bcf7-dfef50adc832
---
**Activated 2026-05-01.** Owner explicitly authorised cross-session autonomy. Architecture is **macOS launchd plists** (NOT Claude's CronCreate, which is session-only). Each plist invokes `~/.claude/volscope-cron-prompt.sh <mode>`, which spawns a fresh Claude CLI session with the appropriate prompt file.

## The 8 launchd jobs

| Plist | Local time | Mode | Prompt file |
|-------|-----------|------|-------------|
| `com.tomschoen.volscope.loop0647` | 06:47 daily | loop | `scripts/autonomous/loop_iteration_prompt.md` |
| `com.tomschoen.volscope.loop1017` | 10:17 daily | loop | same |
| `com.tomschoen.volscope.loop1343` | 13:43 daily | loop | same |
| `com.tomschoen.volscope.loop1751` | 17:51 daily | loop | same |
| `com.tomschoen.volscope.loop2123` | 21:23 daily | loop | same |
| `com.tomschoen.volscope.audit_sun` | Sun 11:23 | audit | `scripts/autonomous/audit_refresh_prompt.md` |
| `com.tomschoen.volscope.backtest_sat` | Sat 06:47 | backtest | `scripts/autonomous/backtest_refresh_prompt.md` |
| `com.tomschoen.volscope.renewal_fri` | Fri 22:13 | renewal | `scripts/autonomous/self_renewal_prompt.md` |

All plists live under `~/Library/LaunchAgents/`. Verify with `launchctl list | grep volscope`.

## Dispatcher

`~/.claude/volscope-cron-prompt.sh <mode>` is the single entry point.
- Reads `~/.volscope_loop_pause` first; exits if present.
- Picks the mode-specific prompt file under `<repo>/scripts/autonomous/`.
- Pipes a wrapper prompt into `claude --dangerously-skip-permissions -p`.
- Streams output to `~/.claude/volscope-cron-logs/<mode>-<ts>.log`.
- Sends macOS notification on completion.

Dangerously-skip-permissions is on because cron sessions can't answer prompts.
The pause-marker is the safety net: any-mode immediately exits if it exists.

## Pause / resume

- `make autonomy-pause`  → `touch ~/.volscope_loop_pause`. All future cron fires exit silently.
- `make autonomy-unpause` → `rm -f ~/.volscope_loop_pause`. Next fire resumes.
- `make autonomy-status` → shows `launchctl list | grep volscope` + last-run summary per mode.
- `make autonomy-test MODE=loop` → run the dispatcher manually (foreground) for debug.

## Where to look

- Logs: `~/.claude/volscope-cron-logs/<mode>-<ts>.log`
- Last-run summary: `~/.claude/volscope-cron-logs/<mode>-last.summary`
- Maturity history: `<repo>/data/maturity_history.jsonl`
- Failures: `<repo>/data/audit/.failures.jsonl`

## Operational notes

- launchd jobs survive Claude restart, machine restart, and login/logout.
- Renewal cron exists for symmetry with the design but launchd plists do NOT auto-expire — renewal mostly re-validates and is a no-op unless plists were manually removed.
- The old single-cron plist `com.tomschoen.volscope.cron1143` from prior sessions has been moved to `/tmp` and unloaded.
- Session-only CronCreate jobs from earlier turns (8 of them, all `[session-only]`) die when the current Claude session exits — that's expected and OK.

## How to apply
When Operator asks "are the loops running" → `launchctl list | grep volscope`.
When Operator asks "what did the loops do today" → `ls ~/.claude/volscope-cron-logs/ | tail`.
When Operator asks "stop the loops" → `make autonomy-pause`.
When Operator asks "test the loop manually" → `~/.claude/volscope-cron-prompt.sh loop`.
