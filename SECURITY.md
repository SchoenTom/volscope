# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.** Use GitHub's
private security advisory (**Security → Report a vulnerability**). Expect an
acknowledgement within ~5 working days.

Include:

- Component affected (path, line number if possible).
- A minimal reproduction (steps + expected vs. actual).
- Your severity assessment.
- Whether a public advisory is appropriate when the fix lands.

## Severity rubric

VolScope is a local, single-user research app — it computes and visualises
volatility, holds no credentials for trading, and places no orders. The
realistic attack surface is the usual web/data-app one:

| Class | Examples | Response time |
|---|---|---|
| **Critical** | Remote code execution; a secret (`.env` / API key) committed or leaked into logs | 24 h |
| **High** | Untrusted-input code paths (e.g. unsafe YAML/`pickle` deserialisation), SQL injection via f-string queries | 5 days |
| **Medium** | Stored/reflected XSS in Streamlit-rendered HTML output | 2 weeks |
| **Low** | Information disclosure with no material impact | 4 weeks |

## What we promise

- A confidential fix on a named branch.
- A reasonable disclosure window before any public advisory.
- Acknowledgement in `CHANGELOG.md` if you'd like the credit.

## What we don't promise

- A bug bounty.
- Responses on weekends / holidays for non-critical reports.
- Backports — we maintain `main` only.
