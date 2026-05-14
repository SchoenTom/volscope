## What
<!-- One line: what does this PR change? -->

## Why
<!-- The problem this solves. Link to issue / ADR / roadmap item if applicable. -->

## How
<!-- Implementation notes worth flagging. Architecture choices. Trade-offs. -->

## Testing
- [ ] Unit tests added / updated
- [ ] `pytest -m "not slow and not integration and not perf"` green locally
- [ ] `pre-commit run --all-files` green
- [ ] Streamlit app starts (`make run`)
- [ ] Mypy strict passes on touched new-package files

## Risk
- [ ] No live-trading code changed without explicit human approval
- [ ] No `volscope/analytics/` changes without test updates
- [ ] No secrets committed (gitleaks pre-commit verified)
- [ ] No `--force` or `--amend` used (Conventional Commits preserved)

## CHANGELOG
<!-- If user-facing, add an entry to CHANGELOG.md under [Unreleased]. -->
