# .claude/ — Project-local Claude Code configuration

This directory holds project-specific extensions for Claude Code
sessions on VolScope. Each subdirectory has a single purpose; all are
discoverable by future Claude sessions via `WELCOME-AGENT.md` →
`memory/INDEX.md` → here.

## Subdirectories

| Directory | Purpose | When to add files |
|---|---|---|
| `agents/` | Custom subagent definitions (.md files with frontmatter). | When a workflow needs a specialised agent (e.g. `code-reviewer.md`, `pii-scrubber.md`). |
| `skills/` | User-invocable skills (slash commands or named flows). | When you find yourself running the same multi-step task often (e.g. "ship-pr"). |
| `commands/` | Slash-command definitions (e.g. `/loop`, `/maturity`). | When a one-line shortcut is more ergonomic than a full chat exchange. |
| `rules/` | Project-specific decision rules / policies. | When you want to formalise a guideline (e.g. "never run live IBKR orders"). |

## What's here today

Empty. The structure is reserved for v0.4.0+ when we customise the
session experience.

## Why empty subdirs are committed

Git doesn't track empty directories. Each subdir has a `.gitkeep` so
the structure survives clone. Once we add real content, `.gitkeep`
gets removed.

## How to add an agent / skill / command / rule

Each file is a self-describing markdown with YAML frontmatter. See
the existing definitions in `~/.claude/agents/` (Claude Code's
built-in agents) for the format. Project-local definitions override
user-level ones.

Resources:
- [Claude Code subagent documentation](https://docs.claude.com/en/docs/claude-code/sub-agents)
- [Skill plugin spec](https://docs.claude.com/en/docs/claude-code/skills)
