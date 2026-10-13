"""Read one Claude Code session transcript into a compact human/agent dialogue.

The transcript format is not a contract, so every access is defensive and
unknown records are skipped. Tool output is the bulk of a session and says
nothing about prompting, so tool calls collapse to their names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_PREFIXES = (
    "<command-name>",
    "<local-command",
    "<system-reminder>",
    "<task-notification>",
    "<bash-input>",
    "<bash-stdout>",
    "Caveat:",
)
INTERRUPT = "[Request interrupted"


@dataclass
class Turn:
    role: str  # "human" | "agent" | "interrupt"
    text: str = ""
    tools: list[str] = field(default_factory=list)


def _human_text(record: dict) -> str | None:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
            return None
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return None


def read_turns(path: str | Path) -> list[Turn]:
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
        if not isinstance(record, dict) or record.get("isSidechain") or record.get("isMeta"):
            continue
        kind = record.get("type")
        if kind == "user":
            text = (_human_text(record) or "").strip()
            if not text or text.startswith(HARNESS_PREFIXES) or record.get("isCompactSummary"):
                continue
            turns.append(Turn("interrupt") if text.startswith(INTERRUPT) else Turn("human", text))
        elif kind == "assistant":
            content = (record.get("message") or {}).get("content") or []
            if not isinstance(content, list):
                continue
            if not turns or turns[-1].role != "agent":
                turns.append(Turn("agent"))
            agent = turns[-1]
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    agent.text = (agent.text + "\n" + block["text"]).strip()
                elif block.get("type") == "tool_use":
                    agent.tools.append(block.get("name", "?"))
    return [t for t in turns if t.role != "agent" or t.text or t.tools]


def render(turns: list[Turn], max_chars: int = 1500) -> str:
    """Plain-text dialogue for the model; long agent replies keep head and tail."""
    out = []
    for t in turns:
        if t.role == "interrupt":
            out.append("[human interrupted the agent]")
            continue
        text = t.text
        if len(text) > max_chars:
            half = max_chars // 2
            text = f"{text[:half]}\n[…]\n{text[-half:]}"
        if t.role == "agent" and t.tools:
            names = sorted(set(t.tools), key=t.tools.index)
            text = f"[tools used: {', '.join(names)}]\n{text}".strip()
        out.append(f"{t.role.upper()}: {text}")
    return "\n\n".join(out)
