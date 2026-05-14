# Security Policy

## Scope

VolScope is private at the time of this writing. The recipient list for
vulnerability reports is the repo owner only.

## Reporting a vulnerability

**Do not open a public issue.** Email the repo owner directly (the address
is in your collaborator invitation). Expect a response within 5 working
days.

Include:

- Component affected (path, line number if possible).
- A minimal reproduction (steps + expected vs. actual).
- Severity assessment (your view).
- Whether a public CVE is appropriate when the fix lands.

## Severity rubric

| Class | Examples | Response time |
|---|---|---|
| **Critical** | Remote code execution, IBKR-credential leak, kill-switch bypass | 24 h |
| **High** | Unauthenticated data exfiltration, signing-key compromise | 5 days |
| **Medium** | XSS in Streamlit-rendered output, deserialisation of untrusted YAML | 2 weeks |
| **Low** | Information disclosure that doesn't risk capital | 4 weeks |

## What we promise

- A confidential, named fix branch.
- A NotBeforeDate before any public disclosure post-flip-to-public.
- Acknowledgement in `CHANGELOG.md` if the reporter wants it.

## What we don't promise

- A bug bounty.
- A response on weekends / holidays for non-critical reports.
- Backports to old versions (we maintain `main` only).

## Defensive posture

The bot trades real money. Even a non-exploit bug that produces wrong
orders is treated as a security issue. Reports about anomalous bot
behaviour (signals firing when they shouldn't, kill switch failing to
trip) are welcome and get the same severity treatment.
