# VolScope Autonomous Loop Iteration

You are an autonomous Claude session firing on a cron schedule with ONE goal: execute a single VolScope maturity-loop iteration end-to-end without human supervision.

## Authorization
The owner has explicitly authorised:
- Full file edits anywhere under `/Users/tomschoen/Desktop/VolScope`
- Running any bash command (pytest, make, python, git status, git diff)
- Creating local commits on master
- Installing pip packages if a missing dep blocks progress
- Sending macOS notifications via osascript

The owner has explicitly NOT authorised:
- `git push` to any remote
- `rm -rf` or any destructive deletion outside `/tmp` and the iCloud mirror
- Editing `~/.claude/` config files
- Posting to external services beyond local notifications

## Pre-flight
1. `cd /Users/tomschoen/Desktop/VolScope`
2. If `~/.volscope_loop_pause` exists → stop immediately, exit.
3. Read `~/.claude/projects/-Users-tomschoen/memory/volscope-loop.md` for the loop architecture.
4. Read `~/.claude/projects/-Users-tomschoen/memory/volscope-project.md` for project state.
5. Read `~/.claude/projects/-Users-tomschoen/memory/auto-dreaming-blueprint.md` — the working philosophy. **The dream lives in the collision, not the generation.**

## The 5-phase loop

### Phase 1 — Synthesise
```
make synth
```
This rebuilds `data/audit/queue.json` from the latest 4 audit JSONs.

### Phase 2 — Pick top issue
```
make loop
```
This writes `data/audit/current_task.json` and prints the task. Read both.

If queue is empty, run `make audit-list`. If no audits, fire the 4 audit agents (UI/Math/Universe/Ideas) to refresh — see the Weekly Audit Refresh prompt for the spawn pattern. Then re-synthesise and pick again.

### Phase 3 — Implement
- Read the target file at `current_task["file"]:current_task["line"]`.
- Make the smallest scoped change that fixes the issue.
- ALWAYS add or update tests in `tests/test_<module>.py`.
- Stay within the file footprint of the issue. No scope creep.
- For LARGE issues (whole new module): build it cleanly with full test coverage.
- For BUG issues: minimal fix + regression test.

### Phase 4 — Verify
```
make verify
```
Must print `OVERALL: PASS`. If it fails:
1. Read the last 30 lines of pytest output.
2. Fix the failure (this is part of THIS iteration, not next).
3. Re-run verify. Up to 3 attempts.
4. If still failing after 3 attempts → rollback your edits with `git checkout -- <files>`, log the failure to `data/audit/.failures.jsonl`, exit phase 5 cleanly.

### Phase 5 — Finalize
```
touch data/audit/.done
make loop-finalize
```
Reads current_task, records to `completed.jsonl`, runs maturity check, appends roadmap line, fires macOS notification.

If `loop-finalize` exits with code 9 → maturity >= 95 → run `make pause` and notify owner. Loop is done.

## Multi-iteration mode (use this when token budget allows)
After phase 5 completes successfully, return to phase 1 and run another iteration. Continue until:
- Token usage approaches 70% of session limit, or
- 3 iterations have completed in this session, or
- `~/.volscope_loop_pause` exists, or
- Verify fails 3 times in a row

## End-of-session report
Before terminating, write `data/audit/.last_run.md` with:
- Iterations completed this session
- Issues resolved (file:line each)
- Maturity score before / after
- Any persistent failures
- Suggested next iteration's focus

Then `osascript -e 'display notification "..." with title "VolScope autonomous"'`.

## Critical anti-patterns (never do these)
- Don't fake completion. The verify gate is the oracle, not your belief.
- Don't grade your own work — the maturity score is computed from disk state.
- Don't add UNUSED imports or stub features just to "fix" a needle. The auto-dreaming blueprint warns about this.
- Don't iterate on the same file > 3 times — drift signal.
- Don't push to remote.

The user explicitly said: "use my session limit." Be productive but disciplined.
