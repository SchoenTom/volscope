# Contributing

VolScope is a small project. Process matches the scale — no committees,
but a few non-negotiables that protect a system trading real money.

## Branch workflow

- `main` is protected. No direct pushes. Branch protection enforced via
  `gh api`.
- Branch names: `feat/<short>`, `fix/<short>`, `refactor/<short>`,
  `docs/<short>`, `test/<short>`, `chore/<short>`.
- Open a PR. CI must pass + at least one CODEOWNER approval for
  critical paths (`volscope/{analytics,risk,execution,lifecycle}/` and
  `config/risk.yaml`).
- Merge via "Squash and merge" — keeps `main` history as a clean
  Conventional-Commit log.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short imperative>

<body explaining why, not what>

<footer with BREAKING CHANGE: ... or fixes #N>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Examples:
- `feat(signals): add HMM regime gate`
- `fix(ui): rotation page empty join`
- `refactor(scripts): bundle into subgroups by purpose`

## Pre-commit

```bash
uv run pre-commit install
```

Hooks installed:

- `ruff` (autofix + format)
- `mypy --strict` on new packages (`signals`, `risk`, `lifecycle`,
  `execution`, `scheduler`, `persistence`)
- `gitleaks` (full-history scan on push)
- `pytest` (fast subset, on push)

**Do not bypass hooks.** If a hook fails, fix the underlying issue.

## Tests

Markers (configured in `pyproject.toml`):

- `slow` — > 5s per test
- `integration` — needs external service
- `ibkr` — needs IBKR paper connection
- `perf` — performance benchmark

Default CI run: `pytest -m "not slow and not integration and not perf"`.

New code needs tests. Coverage gate is **65%** on push. If you can't
hit it on a single PR, split the work or backfill tests in a follow-up
PR (open the follow-up at the same time so it's not forgotten).

## Risky changes

These need explicit operator approval BEFORE the PR is opened:

- Anything in `volscope/risk/`.
- Anything in `volscope/execution/` once Phase 2.5 is live.
- `config/risk.yaml` or `config/strategies.yaml` edits.
- New dependencies in `pyproject.toml`.
- Anything that touches the WORM audit-log invariant (see
  `docs/ARCHITECTURE.md`).

For risky changes, attach the operator's go-ahead message (or link to
a Discussions thread) in the PR body.

## Broken initial commit?

Branch protection blocks force-pushes. If you push something bad to
`main`:

1. Do NOT `git reset --hard origin/main` and `git push --force`.
2. Create a `chore/initial-fixup` branch.
3. Open a PR with the fix.
4. Merge via squash.

The history will be slightly noisier but truthful. Truthful history is
the whole point of branch protection.

## Releasing

- Update `CHANGELOG.md` under `[Unreleased]` as you go.
- When ready: bump version in `pyproject.toml`, move `[Unreleased]` to
  `[X.Y.Z]` with today's date, tag the merge commit `vX.Y.Z`, and
  `gh release create vX.Y.Z` with the changelog excerpt as the body.
- We follow [SemVer](https://semver.org/): breaking → MAJOR, feature →
  MINOR, fix → PATCH.

## Questions

- For day-to-day questions: GitHub Discussions (enabled once the repo
  flips to public; before then, ping the owner directly).
- For architecture questions: open an ADR. It's a low-friction way to
  document a debate, and the artefact lives forever.
