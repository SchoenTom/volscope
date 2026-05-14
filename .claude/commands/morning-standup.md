---
description: Read progress.md + last 5 decisions + git log + CI status; report status in ≤10 lines.
---

# /morning-standup

Quick orientation at session start. Read these in order, then summarise:

1. `progress.md` — what shipped last session, what's queued.
2. `docs/decisions.md` — last 5 entries.
3. `git log --oneline -10`.
4. `gh run list --limit 3 --workflow ci.yml` — CI status.
5. Open tasks in `TaskList`.

Report in ≤10 lines:

```
## Standup — <YYYY-MM-DD HH:MM ET>

Last shipped: <one line>
Active phase: <Phase 2 scaffold | v0.5.0 in flight | ...>
CI: <green | red — link>
Open tasks: <count> (<top-3 by priority>)
Blockers: <none | one-line>
Recommended next: <one specific action>
```

Don't editorialise. Don't fix anything. Just orient.
