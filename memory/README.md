# memory/ — Agent Knowledge Canon

Everything an agent needs to know about VolScope, sanitised for safe
collaboration and committed to git on purpose.

## Why this folder exists

VolScope is operated jointly by humans and Claude Code agents. Across
sessions, agents have no memory; they re-read this folder to pick up
the project's context, working philosophy, and current state.

If you are a new agent: **start with [`INDEX.md`](INDEX.md)** — it lists
the canonical reading order.

## Layout

```
memory/
├── README.md           # this file
├── INDEX.md            # reading order for new agents
├── project.md          # what VolScope is, who it serves, hard rules
├── leaps-lab.md        # LEAPS Lab subsystem context
├── chat-archive/       # raw session transcripts (compressed history)
├── ops/                # operational protocols (cron roster, loops)
├── signals/            # signal-direction notes
├── philosophy/         # working philosophy across sessions
├── research/           # research RTFs / PDFs (IV anomaly, strategy)
├── process/            # workflow notes (OPTIMALER-WORKFLOW)
└── roadmaps/           # historical + current roadmaps (bot-masterplan, etc.)
```

## Trade-off note: the chat-archive is 31 MB

`memory/chat-archive/` contains 31 MB of RTFs (raw chat transcripts and
the initial system prompt PDF). This is intentional: those files are the
project's institutional memory and are referenced by future autonomous
sessions. Git can handle the size; LFS not required at this scale.

If the archive grows past ~100 MB, switch to Git LFS or move it to a
dedicated `volscope-archive` repo.

## Sanitisation policy

Every `.md` file in this folder has been run through `_one_off/sanitize.py`
(not committed) to strip personal identifiers, holdings, and tax info.
Any future edit MUST preserve this — do not add names, emails, university
details, or specific position sizes back in.

The verification grep (configured in `_one_off/sanitize.py`)
must return zero matches at every commit boundary. CI's gitleaks job
enforces this on every push.
