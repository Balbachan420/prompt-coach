"""Hook entry point for Claude Code and Codex: UserPromptSubmit, Stop, SessionStart.

UserPromptSubmit: show a pattern hint if one fires, and when the prompt looks like
a correction, start a detached analysis of the session. Stop: deliver the lesson
that analysis left for this session. SessionStart: offer the history scan once.

Usage: `python3 -m coach.hook [claude|codex]`. The provider says how to read the
session file; Claude Code is the default.

Any failure is swallowed: the coach must never block, delay or break a prompt, so
the worst case is silence. Sessions started by the coach itself (INNER_ENV) are
skipped, otherwise the inner model call would analyze itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from coach import memo, store
from coach.checks import evaluate, first_shown, prompt_hash
from coach.correction import INNER_ENV, is_candidate

REPO = Path(__file__).resolve().parent.parent
def start_analysis(payload: dict, provider: str) -> None:
    jobs = store.home() / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    job = jobs / f"{uuid.uuid4().hex}.json"
    job.write_text(
        json.dumps(
            {
                "session": payload.get("session_id") or "unknown",
                "provider": provider,
                "transcript_path": payload["transcript_path"],
                "prompt": payload["prompt"],
                "hash": prompt_hash(payload["prompt"]),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "coach.analyze", str(job)]
    if os.environ.get("PROMPT_COACH_SYNC"):  # tests
        subprocess.run(cmd, cwd=REPO, check=False)
        return
    subprocess.Popen(
        cmd,
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def on_prompt(payload: dict, provider: str) -> dict | None:
    prompt = payload.get("prompt") or ""
    session = payload.get("session_id")
    hits = evaluate(prompt, store.load_rules(), previous_hash=store.previous_hash(session))
    shown = first_shown(hits, store.load_muted() | store.load_retired())
    candidate = is_candidate(prompt) and bool(payload.get("transcript_path"))
    store.append_event(
        {
            "session": session,
            "provider": provider,
            "hash": prompt_hash(prompt),
            "chars": len(prompt),
            "fired": [h.rule_id for h in hits],
            "shown": shown.rule_id if shown else None,
            "correction_candidate": candidate,
        }
    )
    if candidate:
        start_analysis(payload, provider)
    if shown is None:
        return None
    return {"systemMessage": f"💡 coach · {shown.rule_id}: {shown.message}"}


def on_stop(payload: dict, provider: str) -> dict | None:
    if payload.get("stop_hook_active") or not payload.get("session_id"):
        return None
    pending = store.pending_path(payload["session_id"])
    if not pending.exists():
        return None
    message = json.loads(pending.read_text(encoding="utf-8"))["message"]
    pending.unlink(missing_ok=True)
    return {"systemMessage": message}


def on_session_start(payload: dict, provider: str) -> dict | None:
    """Show the memo once: what the coach does, the commands, and the scan if not run yet."""
    marker = store.home() / "welcome_shown"
    if marker.exists():
        return None
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")
    scanned = any(e.get("source") == "scan" for e in store.read_events())
    return {"systemMessage": memo.welcome(scanned)}


HANDLERS = {"UserPromptSubmit": on_prompt, "Stop": on_stop, "SessionStart": on_session_start}


def main(argv: list[str] | None = None) -> int:
    try:
        if os.environ.get(INNER_ENV):
            return 0
        args = sys.argv[1:] if argv is None else argv
        provider = args[0] if args and args[0] in ("claude", "codex") else "claude"
        store.remember_root(REPO)
        payload = json.load(sys.stdin)
        handler = HANDLERS.get(payload.get("hook_event_name", "UserPromptSubmit"))
        out = handler(payload, provider) if handler else None
        if out:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — a coach bug must not cost the user a prompt
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
