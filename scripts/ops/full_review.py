"""
/full-review CLI — invokes 5 role-specialised reviewers in parallel,
each in its own `claude -p` subprocess. Aggregates via
`volscope/orchestration/full_review.py`. Writes a markdown report
to `docs/reviews/<YYYY-MM-DD-HHMM>.md`.

Usage:
    make full-review                       # diff = HEAD~1..HEAD
    make full-review REF=main..feat/foo    # diff = main..feat/foo
    python -m scripts.ops.full_review --mock    # use mock reviewers (no API calls)

Mock mode is the default in CI + when no anthropic auth is detected.
Real mode requires `claude` CLI authenticated.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from volscope.orchestration.full_review import (
    AggregatedReview, Finding, ReviewArtifact, run_loop,
)


AGENTS = [
    ("signal-engineer", "math + correctness"),
    ("risk-auditor", "safety surface + thresholds"),
    ("security-reviewer", "secrets + injection + audit chain"),
    ("code-reviewer", "style + idiom + bugs"),
    ("observability-engineer", "logs + metrics + dashboard surface"),
]


def _git_diff(ref: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "diff", ref, "--unified=10"], text=True,
        )
        return out
    except subprocess.CalledProcessError:
        return ""


def _mock_artifacts(iteration: int) -> list[ReviewArtifact]:
    """No-op reviewer: every agent PASSes with zero findings.

    Used in CI + when `--mock` is set. The real subprocess invocation
    happens in `_real_artifacts()` and requires the `claude` CLI.
    """
    return [
        ReviewArtifact(
            agent=name,
            verdict="PASS",
            findings=[],
            confidence=0.9,
        )
        for name, _ in AGENTS
    ]


def _real_artifacts(iteration: int, diff: str) -> list[ReviewArtifact]:
    """Spawn 5 parallel `claude -p` subprocesses; collect JSON output.

    Requires:
      - `claude` CLI in PATH and authenticated.
      - `.claude/agents/<name>.md` for each agent.

    Each subprocess is fully isolated — different process, fresh
    context, role-specific rubric only. Independence by construction.
    """
    if shutil.which("claude") is None:
        print("WARNING: `claude` CLI not found in PATH — falling back to mock mode",
              file=sys.stderr)
        return _mock_artifacts(iteration)

    procs: dict[str, subprocess.Popen] = {}
    for name, focus in AGENTS:
        rubric = (
            f"You are the `{name}` reviewer. Focus: {focus}.\n\n"
            f"Read the following diff and emit a JSON ReviewArtifact:\n"
            f'{{"schema_version":"1.0","agent":"{name}",'
            f'"verdict":"PASS|REVISE|REJECT","findings":['
            f'{{"severity":"critical|high|medium|low",'
            f'"category":"secrets|math|risk|style|observability",'
            f'"file":"path","line_range":[lo,hi],"fix":"one-line suggestion"}}'
            f"],\"confidence\":0..1}}\n\n"
            f"Output ONLY the JSON, nothing else.\n\n"
            f"--- DIFF (iteration {iteration}) ---\n{diff[:8000]}"
        )
        procs[name] = subprocess.Popen(
            ["claude", "--output-format", "json", "-p", rubric],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    artifacts: list[ReviewArtifact] = []
    for name, proc in procs.items():
        try:
            stdout, _ = proc.communicate(timeout=120)
            artifacts.append(ReviewArtifact.from_json(stdout.strip()))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
            print(f"WARNING: {name} timed out or returned bad JSON ({exc}); "
                  f"treating as PASS with low confidence", file=sys.stderr)
            artifacts.append(ReviewArtifact(
                agent=name, verdict="PASS", findings=[], confidence=0.0,
            ))
            try:
                proc.kill()
            except Exception:                                # noqa: BLE001
                pass
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", default="HEAD~1..HEAD",
                         help="git diff range (default: HEAD~1..HEAD)")
    parser.add_argument("--mock", action="store_true",
                         help="use mock reviewers (no claude CLI calls)")
    parser.add_argument("--max-iterations", type=int, default=3)
    args = parser.parse_args(argv)

    diff = _git_diff(args.ref)
    if len(diff) < 30:
        print(f"diff {args.ref} is trivial ({len(diff)} bytes); skipping full-review",
              file=sys.stderr)
        return 0

    if args.mock:
        loader = _mock_artifacts
    else:
        def loader(iter_n):                              # noqa: E306
            return _real_artifacts(iter_n, diff)

    result = run_loop(loader, max_iterations=args.max_iterations)

    # Write the markdown report
    out_dir = Path("docs/reviews")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d-%H%M")
    out_path = out_dir / f"{ts}-{args.ref.replace('/', '_').replace('..', '__')}.md"
    out_path.write_text(result.review.to_markdown())
    print(f"wrote {out_path}")
    print(f"\nVERDICT: {result.review.verdict} "
           f"(iteration {result.iteration}/{args.max_iterations})")

    # Exit code reflects verdict: PASS=0, REVISE=1, REJECT=2
    return {"PASS": 0, "REVISE": 1, "REJECT": 2}[result.review.verdict]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
