# ADR-0001: Record architecture decisions

## Status

Accepted — 2026-05-14.

## Context

VolScope is moving from a single-developer research project into a
production-grade autonomous trading bot that risks real money. As scope
grows and more contributors / agents touch the codebase, the "why" of
load-bearing decisions risks getting lost. Code documents WHAT;
ADRs document WHY.

## Decision

We will record architecturally significant decisions in this
`docs/adr/` directory using the [Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
format:

- One Markdown file per decision, numbered `NNNN-short-name.md`.
- Status: Proposed → Accepted → (eventually) Superseded by ADR-NNNN.
- Each ADR captures: Context, Decision, Consequences (positive and
  negative).

ADRs are write-once after acceptance. Superseding a decision means
adding a new ADR that references the old one and changes its status
to "Superseded by ADR-NNNN" — never editing the original.

## Consequences

- **Positive**: any new contributor can read the ADR set in 30 minutes
  and understand the load-bearing choices.
- **Positive**: when we revisit a decision later ("should we switch to
  Postgres?"), we have the full original rationale.
- **Negative**: discipline cost — every architecturally significant
  decision needs an ADR. Acceptable.

## Initial decisions to record

- ADR-0002: DuckDB over Postgres for the bot DB.
- ADR-0003: `ib_async` (not `ib_insync`) as the IBKR client library.
- ADR-0004: Quarter-Kelly position sizing as the production-safe start.
- ADR-0005: 21-DTE mechanical close for short-vol trades.
