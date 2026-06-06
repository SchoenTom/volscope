---
description: Run ruff + mypy strict (new modules) + pytest fast + gitleaks. Block on any fail. Use before every commit to main or a release tag.
---

# /pre-merge-check

The gate. Must exit 0 across every step before you commit / push:

```bash
# 1. Ruff
.venv/bin/ruff check . && .venv/bin/ruff format --check .

# 2. Mypy (strict on core packages)
.venv/bin/mypy --strict --ignore-missing-imports \
    volscope/persistence volscope/analytics

# 3. Fast pytest
.venv/bin/python -m pytest \
    -m "not slow and not integration and not perf and not ibkr" \
    --tb=short -q

# 4. Gitleaks (full history)
gitleaks detect --no-banner --no-git -v
```

Any non-zero exit = REJECT. Surface the offending step's output to the
operator; do NOT auto-fix and re-run silently.

Pre-commit hooks should run a subset of this on every `git commit`,
but `/pre-merge-check` is the manual full sweep before pushing main.
