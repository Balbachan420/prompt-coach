"""Local state under ~/.prompt-coach (PROMPT_COACH_HOME overrides).

  checks.json   personal rules, merged over coach/default_checks.json
  state.json    {"muted": [...]}
  events.jsonl  one line per prompt: ts, session, hash, length, fired ids.
                Never the prompt text.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from coach.checks import merge_rules

DEFAULT_CHECKS = Path(__file__).with_name("default_checks.json")


def home() -> Path:
    return Path(os.environ.get("PROMPT_COACH_HOME", "~/.prompt-coach")).expanduser()


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def load_rules() -> list[dict]:
    default = _read_json(DEFAULT_CHECKS, {}).get("rules", [])
    personal = _read_json(home() / "checks.json", {}).get("rules", [])
    return merge_rules(default, personal)


def _load_set(key: str) -> set[str]:
    return set(_read_json(home() / "state.json", {}).get(key, []))


def _save_set(key: str, values: set[str]) -> None:
    home().mkdir(parents=True, exist_ok=True)
    state = _read_json(home() / "state.json", {})
    state[key] = sorted(values)
    (home() / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_muted() -> set[str]:
    """Hints the user silenced by hand."""
    return _load_set("muted")


def save_muted(muted: set[str]) -> None:
    _save_set("muted", muted)


def load_retired() -> set[str]:
    """Hints silenced automatically because they do not predict corrections."""
    return _load_set("retired")


def save_retired(retired: set[str]) -> None:
    _save_set("retired", retired)


def append_event(event: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    with (home() / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time()), **event}) + "\n")


def read_events() -> list[dict]:
    try:
        lines = (home() / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def remember_root(root: Path) -> None:
    """Record where the coach code lives now. A plugin update moves it, and the
    Codex shim, which sits outside the plugin, finds the code through this file."""
    pointer = home() / "root"
    current = str(root)
    try:
        if pointer.read_text(encoding="utf-8") == current:
            return
    except OSError:
        pass
    home().mkdir(parents=True, exist_ok=True)
    pointer.write_text(current, encoding="utf-8")


def pending_path(session_id: str) -> Path:
    """A lesson waiting for the Stop hook of this session."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return home() / "pending" / f"{safe}.json"


def append_lesson(lesson: dict) -> None:
    """Lessons hold a short paraphrase of the corrected prompt; local only."""
    home().mkdir(parents=True, exist_ok=True)
    with (home() / "lessons.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time()), **lesson}, ensure_ascii=False) + "\n")


def read_lessons(days: int | None = None) -> list[dict]:
    try:
        lines = (home() / "lessons.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    since = time.time() - days * 86400 if days else 0
    lessons = []
    for line in lines:
        try:
            lesson = json.loads(line)
        except ValueError:
            continue
        if lesson.get("ts", 0) >= since:
            lessons.append(lesson)
    return lessons


def previous_hash(session_id: str | None) -> str | None:
    """Hash of the last prompt logged for this session, read from the log tail."""
    if not session_id:
        return None
    for event in reversed(read_events()[-200:]):
        if event.get("session") == session_id:
            return event.get("hash")
    return None
