"""
VolScope Loop Iteration — single-iteration orchestrator.

This is the heartbeat of the maturity loop. One invocation = one iteration.
It does NOT itself execute the implementation phase — that requires Claude
Code (which can write files and run tests). Instead, it:

  1. Checks the pause-marker (~/.volscope_loop_pause). If present → exit 2.
  2. Loads the ranked queue (data/audit/queue.json).
  3. Picks the top issue and writes data/audit/current_task.json.
  4. Prints a clear instruction block for the implementer (Claude or human).
  5. After the implementer signals completion (touch data/audit/.done),
     it runs `make verify`, then `scripts/maturity_check.py`.
  6. Appends a Roadmap line, increments progress.json::P6_loop counter.
  7. On verify-PASS → exit 0 (caller may re-trigger). On FAIL → exit 1.
  8. If maturity ≥ 95 → exit 9 ("MATURE — stop the outer loop").

Modes
-----
- ``--phase pick``      Just pick the top issue, print it, exit 0
- ``--phase finalize``  Run verify + maturity + record (assumes implement done)
- ``--phase full``      pick → wait-for-done → finalize  (default)
- ``--synthesize-only`` Recompute queue.json from latest audit JSONs and exit
- ``--dry-run``         Print what would happen, change nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT          = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
DATA          = ROOT / "data"
AUDIT_DIR     = DATA / "audit"
QUEUE_JSON    = AUDIT_DIR / "queue.json"
TASK_JSON     = AUDIT_DIR / "current_task.json"
DONE_MARKER   = AUDIT_DIR / ".done"
COMPLETED_LOG = AUDIT_DIR / "completed.jsonl"
PAUSE_MARKER  = Path.home() / ".volscope_loop_pause"
PROGRESS_JSON = ROOT / "progress.json"
ROADMAP       = Path.home() / ".claude" / "plans" / "volscope-roadmap.md"
LATEST_JSON   = DATA / "maturity_latest.json"

EXIT_OK       = 0
EXIT_FAIL     = 1
EXIT_PAUSED   = 2
EXIT_NO_QUEUE = 3
EXIT_MATURE   = 9

log = logging.getLogger("loop")
logging.basicConfig(format="[loop] %(message)s", level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────
# Synthesis — collapse 4 audit JSONs into one ranked queue
# ─────────────────────────────────────────────────────────────────────────

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _load_completed_keys() -> set[tuple[str, str]]:
    """Return set of (file, description) tuples for already-completed items."""
    if not COMPLETED_LOG.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for line in COMPLETED_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        f = str(entry.get("file") or "")
        d = str(entry.get("description") or "")
        keys.add((f, d))
    return keys


def synthesize_queue() -> list[dict]:
    """Read the latest audit JSON for each agent and produce a ranked queue.
    Items already present in completed.jsonl are skipped.
    Returns the queue list and writes it to data/audit/queue.json."""
    if not AUDIT_DIR.exists():
        return []

    completed_keys = _load_completed_keys()
    queue: list[dict] = []
    for agent in ["ui", "math", "universe", "ideas"]:
        latest = _latest_audit(agent)
        if latest is None:
            continue
        try:
            data = json.loads(latest.read_text())
        except Exception as exc:
            log.warning("audit %s unreadable: %s", latest.name, exc)
            continue
        for key, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                desc = (
                    item.get("description")
                    or item.get("problem")
                    or item.get("name")
                    or ""
                )
                dedupe_key = (str(item.get("file") or ""), str(desc))
                if dedupe_key in completed_keys:
                    continue
                queue.append({
                    "agent":      agent,
                    "category":   key,
                    "severity":   str(item.get("severity", "medium")).lower(),
                    "file":       item.get("file"),
                    "line":       item.get("line"),
                    "description": (
                        item.get("description")
                        or item.get("problem")
                        or item.get("name")
                        or ""
                    ),
                    "fix_sketch": item.get("fix_sketch") or item.get("implementation_sketch"),
                    "estimate_minutes": item.get("estimate_minutes")
                                       or (item.get("estimate_hours") or 0) * 60,
                    "raw":        item,
                })

    # Rank: severity desc, then by smallest effort (so we drain quick wins
    # before tackling multi-day refactors).
    def _key(it: dict) -> tuple:
        sev_score = SEVERITY_RANK.get(it["severity"], 0)
        eff = it["estimate_minutes"] or 999
        return (-sev_score, eff)

    queue.sort(key=_key)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_JSON.write_text(json.dumps({
        "synthesized_at": datetime.now().isoformat(timespec="seconds"),
        "n_items":        len(queue),
        "items":          queue,
    }, indent=2))

    return queue


def _latest_audit(agent: str) -> Optional[Path]:
    if not AUDIT_DIR.exists():
        return None
    files = sorted(AUDIT_DIR.glob(f"{agent}_*.json"))
    return files[-1] if files else None


# ─────────────────────────────────────────────────────────────────────────
# Phase: pick
# ─────────────────────────────────────────────────────────────────────────

def pick_top() -> Optional[dict]:
    """Read queue, pick top item, write current_task.json."""
    if not QUEUE_JSON.exists():
        log.warning("no queue.json — run --synthesize-only first")
        return None
    payload = json.loads(QUEUE_JSON.read_text())
    items = payload.get("items", [])
    if not items:
        log.info("queue is empty")
        return None
    top = items[0]
    TASK_JSON.write_text(json.dumps(top, indent=2))
    DONE_MARKER.unlink(missing_ok=True)
    return top


def print_instructions(item: dict) -> None:
    """Pretty-print the picked item for the implementer."""
    print()
    print("=" * 70)
    print("  NEXT TASK FOR IMPLEMENTER")
    print("=" * 70)
    print(f"  agent:       {item.get('agent')}")
    print(f"  category:    {item.get('category')}")
    print(f"  severity:    {item.get('severity')}")
    if item.get("file"):
        print(f"  file:line:   {item['file']}:{item.get('line', '?')}")
    print(f"  description: {item.get('description')}")
    if item.get("fix_sketch"):
        print(f"  fix sketch:  {item['fix_sketch']}")
    print()
    print(f"  When done, touch {DONE_MARKER.relative_to(ROOT)} and re-run:")
    print(f"    python scripts/loop_iteration.py --phase finalize")
    print("=" * 70)
    print()


# ─────────────────────────────────────────────────────────────────────────
# Phase: finalize (verify + maturity + record)
# ─────────────────────────────────────────────────────────────────────────

def run_verify() -> bool:
    log.info("running make verify ...")
    out = subprocess.run(
        ["make", "verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    text = out.stdout + out.stderr
    passed = "OVERALL: PASS" in text
    if not passed:
        # Print last 30 lines of output so the implementer sees what failed
        tail = "\n".join(text.splitlines()[-30:])
        log.warning("verify FAILED — tail of output:\n%s", tail)
    return passed


def run_maturity(iteration: int) -> Optional[float]:
    log.info("running maturity check ...")
    out = subprocess.run(
        ["python", "scripts/maturity_check.py",
         "--assume-verified",   # we just ran make verify and it passed
         "--iteration", str(iteration),
         "--quiet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if out.returncode != 0:
        log.warning("maturity check failed: %s", out.stderr)
        return None
    try:
        data = json.loads(out.stdout.strip())
        return float(data.get("score", 0.0))
    except Exception as exc:
        log.warning("could not parse maturity output: %s", exc)
        return None


def increment_iteration() -> int:
    """Bump progress.json::phases.P6_loop.iterations and return new value."""
    if not PROGRESS_JSON.exists():
        return 1
    data = json.loads(PROGRESS_JSON.read_text())
    phases = data.setdefault("phases", {})
    p6 = phases.setdefault("P6_loop", {"tasks": {}, "iterations": 0})
    p6["iterations"] = int(p6.get("iterations", 0)) + 1
    PROGRESS_JSON.write_text(json.dumps(data, indent=2))
    return p6["iterations"]


def append_roadmap(item: dict, score: Optional[float], iteration: int) -> None:
    """Append a Roadmap line under 'Discovered Issues' / 'Run Log'."""
    if not ROADMAP.exists():
        log.warning("roadmap not found at %s — skipping", ROADMAP)
        return
    today = datetime.now().strftime("%Y-%m-%d")
    desc  = (item.get("description") or "")[:80]
    score_str = f" — maturity={score:.1f}" if score is not None else ""
    line = (
        f"| {today} | Loop iter #{iteration} | "
        f"{item.get('agent', '?')}/{item.get('category', '?')} — {desc}{score_str} |\n"
    )
    with ROADMAP.open("a") as f:
        f.write(line)


# ─────────────────────────────────────────────────────────────────────────
# Pause-marker helpers
# ─────────────────────────────────────────────────────────────────────────

def is_paused() -> bool:
    return PAUSE_MARKER.exists()


# ─────────────────────────────────────────────────────────────────────────
# Notification
# ─────────────────────────────────────────────────────────────────────────

def notify_macos(title: str, body: str) -> None:
    """Best-effort macOS notification. Silent on failure."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body}" with title "{title}"'],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="VolScope loop iteration")
    p.add_argument("--phase", choices=["pick", "finalize", "full"], default="full")
    p.add_argument("--synthesize-only", action="store_true",
                   help="recompute queue.json and exit")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-wait", type=int, default=0,
                   help="seconds to wait for .done marker in 'full' mode (0 = no wait)")
    args = p.parse_args()

    if is_paused():
        log.info("paused (~/.volscope_loop_pause exists) — exiting")
        return EXIT_PAUSED

    if args.synthesize_only:
        queue = synthesize_queue()
        log.info("synthesized %d items into %s", len(queue), QUEUE_JSON.relative_to(ROOT))
        return EXIT_OK

    # Phase: pick
    if args.phase in ("pick", "full"):
        # Always re-synthesize before picking so latest audits feed the queue.
        queue = synthesize_queue()
        if not queue:
            log.info("queue empty after synthesis — nothing to pick")
            return EXIT_NO_QUEUE
        top = pick_top()
        if top is None:
            return EXIT_NO_QUEUE
        if args.dry_run:
            log.info("[dry-run] would pick: %s", top.get("description")[:60])
        else:
            print_instructions(top)
        if args.phase == "pick":
            return EXIT_OK

    # Phase: full → wait for .done
    if args.phase == "full" and args.max_wait > 0:
        log.info("waiting up to %ds for .done marker ...", args.max_wait)
        deadline = time.time() + args.max_wait
        while time.time() < deadline and not DONE_MARKER.exists():
            time.sleep(2)
        if not DONE_MARKER.exists():
            log.info("timeout waiting for implementer; exiting OK")
            return EXIT_OK

    # Phase: finalize
    if args.phase in ("finalize", "full"):
        if args.phase == "full" and not DONE_MARKER.exists() and args.max_wait == 0:
            log.info("phase=full, no max_wait, no .done — stopping after pick")
            return EXIT_OK

        if args.dry_run:
            log.info("[dry-run] would run verify + maturity + record")
            return EXIT_OK

        passed = run_verify()
        if not passed:
            return EXIT_FAIL

        iteration = increment_iteration()
        score = run_maturity(iteration)

        # Load current task to record what was done
        if TASK_JSON.exists():
            current = json.loads(TASK_JSON.read_text())
            append_roadmap(current, score, iteration)
            # Mark this task as completed so the queue skips it next synth.
            COMPLETED_LOG.touch(exist_ok=True)
            with COMPLETED_LOG.open("a") as f:
                f.write(json.dumps({
                    "iteration":   iteration,
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "file":        current.get("file"),
                    "description": current.get("description"),
                    "agent":       current.get("agent"),
                    "category":    current.get("category"),
                    "score_after": score,
                }) + "\n")
        else:
            current = {"description": "(no current_task.json)"}

        DONE_MARKER.unlink(missing_ok=True)

        notify_macos(
            "VolScope iter #{}".format(iteration),
            "score={} · {}".format(
                f"{score:.1f}" if score is not None else "?",
                (current.get("description") or "")[:50],
            ),
        )

        log.info("iteration #%d complete · score=%s", iteration, score)
        if score is not None and score >= 95.0:
            log.info("MATURITY ≥ 95 — outer loop should stop")
            return EXIT_MATURE

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
