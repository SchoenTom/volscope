---
description: Run the hash-chained audit log verifier. Reports the seq of the first break (if any). Should exit 0 on every clean DB; exit 1 means tampering or a bug in append().
---

# /audit-chain-verify

Run the SHA-256 chain verifier over `bot_audit_chain`.

## Command

```bash
.venv/bin/python -m scripts.audit.verify_chain
```

## Exit codes

- `0` — CHAIN VALID. All rows verify.
- `1` — CHAIN BROKEN. Prints the seq of the first break.
- `2` — DB unreadable.

## When to run

- **Daily** — anchor the latest hash to a git tag for the public audit trail.
- **Before any pre-merge check.**
- **After any restore from backup.**
- **As part of monthly /restore-drill.**

## On break detected

1. Capture the break_seq.
2. `SELECT * FROM bot_audit_chain WHERE seq >= <break_seq>` —
   list of suspect rows. Save the output.
3. **Do not delete** any rows. Forensic value is in keeping them intact.
4. Surface to operator with red banner in Bot Dashboard.
5. Operator decides: was this a deliberate tampering attempt? A bug?
   A bad migration?
6. Restore from most recent known-good backup; append a `kill_trip`
   row to the new chain with `reason="chain break at seq=<break_seq>;
   restored from <date>"`.
7. Post-mortem in `docs/post-mortems/`.

## Daily anchor pattern

```bash
HEAD_HASH=$(.venv/bin/python -m scripts.audit.verify_chain --print-latest 2>/dev/null)
git tag "audit-anchor-$(date +%Y-%m-%d)" -m "audit chain head: $HEAD_HASH"
git push --tags
```

(The `--print-latest` flag is a v0.6.0 addition; v0.5.0 prints chain
status only.)

## See also

- `volscope/persistence/audit_chain.py` — the implementation.
- `.claude/skills/audit-chain-verifier/SKILL.md` — when to use, how
  to interpret breaks, allowed kinds.
