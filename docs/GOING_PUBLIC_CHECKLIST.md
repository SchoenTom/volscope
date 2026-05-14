# Going-Public Checklist

The repo starts **private**. Flip to public only after every box ticks.

## Pre-flip gates

- [ ] **Sanitisation grep returns ZERO** across the FULL git history.
      Use the same regex set defined in `_one_off/sanitize.py` (do not
      duplicate the strings here — keep the canonical list in one place).
      If history contains any leak, history-rewrite with `git filter-repo`
      BEFORE flipping.
- [ ] **`gitleaks detect --source . --no-banner`** clean on full history.
- [ ] **`trufflehog filesystem .`** clean.
- [ ] **README polish**:
      - Remove "private — flip later" note.
      - Add MIT badge.
      - Add a clear scope statement ("research dashboard + paper-only
        signal engine") and a prominent disclaimer.
- [ ] **NOTICE → LICENSE swap**: replace `NOTICE` with full MIT
      `LICENSE` text.
- [ ] **All `(thesis position — outside bot scope)` placeholders
      reviewed**: confirm none accidentally became hostile to public
      reading.
- [ ] **CHANGELOG entry**: `v0.X.0 — N-N-NN: repository visibility:
      private → public`.
- [ ] **Kill-switch fire drill executed**: pick a paper-account state,
      trip each of 8 paths, document timing in
      `docs/post-mortems/firedrill-YYYY-MM-DD.md`.
- [ ] **CODEOWNERS**: add at least one co-maintainer or remove the file
      so single-maintainer reality is honest.
- [ ] **Issue / PR templates** include "no live-trading help" guardrail:
      strangers ask for paper-strategy help; live-trading config never
      discussed publicly.
- [ ] **GH Discussions enabled** as the contributor Q&A forum (off-PRs).

## Flip command

```bash
gh repo edit --visibility public --accept-visibility-change-consequences
```

Then immediately re-enable branch protection (visibility flip resets it):

```bash
gh api repos/{owner}/volscope/branches/main/protection --method PUT ...
```

## Post-flip

- [ ] Pin a "Read this first" Discussions thread linking to
      `WELCOME-AGENT.md` + `docs/OPERATOR_GUIDE.md`.
- [ ] Announce on whichever channel (no specific person required —
      use the abstract "operator" framing).
- [ ] First week: triage every issue, set up labels, document a
      response-time expectation.

## Hard "no" conditions

Do NOT flip if any of these are true:

- Any commit in history contains your real name, email, or thesis
  position.
- The `bot_*` tables on your live DB contain real-money trade records
  that haven't been tax-reported yet.
- You are inside a regulatory window (e.g. open SEC inquiry, IBKR
  margin call) where increased visibility could hurt.
