---
paths:
  - "**/.env*"
  - "**/*.yaml"
  - "**/*.yml"
  - volscope/**/*.py
  - scripts/**/*.py
description: Secrets-management invariants. Applies on every file that could carry credentials or tokens.
---

# Rules for files that could carry secrets

## Never commit secrets

The committed `.env.example` is a TEMPLATE. The real `.env` is in
`.gitignore` and stays local.

Pre-commit `gitleaks` blocks any commit that matches secret patterns.
CI also runs `gitleaks-action` on every PR — full-history scan.

## Always `pydantic.SecretStr` for credentials

```python
from pydantic import BaseModel, SecretStr

class TelegramSettings(BaseModel):
    bot_token: SecretStr | None = None
```

Reading the value requires `.get_secret_value()`. Logging the model
shows `**********`. Defense in depth.

## Specific patterns to NEVER hardcode

| Pattern | Where it leaks |
|---|---|
| `IBKR_HOST=...`, `IBKR_PORT=...` | Use `.env`, load via pydantic-settings |
| `TELEGRAM__BOT_TOKEN=bot...` | `.env` only |
| `FINNHUB_API_KEY=...` | `.env` only |
| `POLYGON_API_KEY=...` | `.env` only |
| `VOLSCOPE_BACKUP_KEY=...` | `.env` only; never log |

## No f-string SQL on user input

```python
db.con.execute(f"SELECT * FROM t WHERE x = '{user_input}'")    # REJECT
db.con.execute("SELECT * FROM t WHERE x = ?", [user_input])    # OK
```

The security-reviewer auto-REJECTS any f-string SQL.

## No `shell=True` in subprocess

```python
subprocess.run("foo bar", shell=True)              # REJECT
subprocess.run(["foo", "bar"])                     # OK
```

Auto-REJECT.

## Logging redaction

structlog must include `_redact_secrets` processor that catches keys
matching `password|api_key|secret|token|account|authorization`.

Even with `SecretStr`, double-check that custom log lines never dump
raw credentials.

## Backup key handling

`VOLSCOPE_BACKUP_KEY` (for DuckDB encryption, v0.5.0 F) must be stored
in 1Password / Bitwarden / system keychain — NOT in `.env`. The env
var is only set at backup/restore time via:

```bash
export VOLSCOPE_BACKUP_KEY=$(security find-generic-password -s VolScopeBackup -w)
```

Loss of this key = no recovery from encrypted backups. Document the
storage location in `docs/BACKUPS.md`.

## German tax data

Anlage KAP entries, IBKR statement files, Steuernummer: NEVER in this
repo. Operator's local archive only.

## Sanitization

`_one_off/sanitize.py` runs at every commit boundary (via the
operator). Verification grep at `_one_off/sanitize.py::main` must
return ZERO hits before `git add` ever runs.

If you spot a personal identifier (name, email, holding, advisor
name) anywhere in a committed file — that's an immediate post-mortem.
