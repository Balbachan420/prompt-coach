"""Where past sessions live, per provider, and how to read them into turns.

Only sessions a human typed into are kept. Programmatic runs (Claude Code
`sdk-*` entrypoints such as `claude -p`, Codex `exec`) are skipped: their prompts
were written by scripts, and that includes the coach's own model calls.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from coach.session import Turn, read_turns


@dataclass(frozen=True)
class Source:
    provider: str  # "claude" | "codex"
    session_id: str
    path: Path


def claude_dir() -> Path:
    return Path(os.environ.get("PROMPT_COACH_CLAUDE_DIR", "~/.claude/projects")).expanduser()


def codex_dir() -> Path:
    default = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "sessions"
    return Path(os.environ.get("PROMPT_COACH_CODEX_DIR", str(default))).expanduser()


def _first_value(path: Path, key: str, max_lines: int = 50):
    """The first `key` found in the opening records of a JSONL file."""
    try:
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    if key in record:
                        return record[key]
                    payload = record.get("payload")
                    if isinstance(payload, dict) and key in payload:
                        return payload[key]
    except OSError:
        return None
    return None


def claude_sources() -> Iterator[Source]:
    # Top level of each project dir only: subagent transcripts live one level deeper.
    for path in sorted(claude_dir().glob("*/*.jsonl")):
        entrypoint = _first_value(path, "entrypoint") or ""
        if entrypoint.startswith("sdk"):
            continue
        yield Source("claude", path.stem, path)


def codex_sources() -> Iterator[Source]:
    for path in sorted(codex_dir().rglob("*.jsonl")):
        if _first_value(path, "source") == "exec" or _first_value(path, "originator") == "codex_exec":
            continue
        yield Source("codex", _first_value(path, "id") or path.stem, path)


PROVIDERS = {"claude": claude_sources, "codex": codex_sources}


def read_codex_turns(path: str | Path) -> list[Turn]:
    """Codex rollout -> turns. Human text comes from `user_message` events, which
    hold exactly what was typed. The `message` items with role user also carry
    injected AGENTS.md and environment context, so they are not used."""
    turns: list[Turn] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return turns
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            continue
        kind = (record.get("type"), payload.get("type"))
        if kind == ("event_msg", "user_message"):
            text = (payload.get("message") or "").strip()
            if text:
                turns.append(Turn("human", text))
        elif kind == ("event_msg", "turn_aborted"):
            turns.append(Turn("interrupt"))
        elif kind == ("event_msg", "agent_message"):
            if not turns or turns[-1].role != "agent":
                turns.append(Turn("agent"))
            turns[-1].text = (turns[-1].text + "\n" + (payload.get("message") or "")).strip()
        elif record.get("type") == "response_item" and payload.get("type") in (
            "function_call",
            "custom_tool_call",
            "local_shell_call",
            "web_search_call",
        ):
            if not turns or turns[-1].role != "agent":
                turns.append(Turn("agent"))
            turns[-1].tools.append(payload.get("name") or payload["type"].replace("_call", ""))
    return turns


def read_source(source: Source) -> list[Turn]:
    return read_codex_turns(source.path) if source.provider == "codex" else read_turns(source.path)
