"""Rule engine: match one prompt against the user's known weak patterns.

Pure: no I/O, no LLM. The hook and the CLI load the rules and the session history,
this module only decides. A rule is a dict from checks.json; its `kind` picks the
matcher:

  pattern         `when_any` matches and no `unless_any` matches
  multi_question  at least `min_questions` "?" and the questions are not numbered
  bare_path       the whole prompt is a single path to a file
  repeat_previous the prompt equals the previous prompt of the same session
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

FLAGS = re.IGNORECASE | re.UNICODE
NUMBERED = re.compile(r"(^|\n)\s*(\d+[.)]|[-•*])\s", FLAGS)
BARE_PATH = re.compile(r"""^['"]?(~|\.{0,2})?/?[\w./\- ]+\.\w{1,5}['"]?$""", FLAGS)
# Slash commands (/insights, /plugin:cmd), harness tags and shell escapes are not
# prompts. A leading "/" alone is not enough: "/home/x/plan.md" is a prompt.
NOT_A_PROMPT = re.compile(r"^(/[\w:-]+(\s|$)|<|!)")


@dataclass(frozen=True)
class Hit:
    rule_id: str
    message: str


def normalize(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def prompt_hash(prompt: str) -> str:
    return hashlib.sha1(normalize(prompt).encode("utf-8")).hexdigest()[:16]


def merge_rules(default: list[dict], personal: list[dict]) -> list[dict]:
    """Personal rules override default ones field by field, matched by id."""
    by_id = {r["id"]: dict(r) for r in default}
    for r in personal:
        by_id[r["id"]] = {**by_id.get(r["id"], {}), **r}
    return sorted(by_id.values(), key=lambda r: r.get("priority", 100))


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, FLAGS) for p in patterns)


def _matches(rule: dict, prompt: str, previous_hash: str | None) -> bool:
    kind = rule.get("kind", "pattern")
    if len(prompt) < rule.get("min_chars", 0):
        return False
    if kind == "pattern":
        return _any(rule.get("when_any", []), prompt) and not _any(
            rule.get("unless_any", []), prompt
        )
    if kind == "multi_question":
        return prompt.count("?") >= rule.get("min_questions", 2) and not NUMBERED.search(
            prompt
        )
    if kind == "bare_path":
        return bool(BARE_PATH.match(prompt.strip())) and "/" in prompt
    if kind == "repeat_previous":
        return previous_hash is not None and previous_hash == prompt_hash(prompt)
    return False


def evaluate(prompt: str, rules: list[dict], previous_hash: str | None = None) -> list[Hit]:
    """All rules that fire, in priority order. Muted rules are evaluated too, so
    the event log still counts them; `first_shown` decides what the user sees."""
    text = prompt.strip()
    if not text or NOT_A_PROMPT.match(text):
        return []
    hits = []
    for rule in rules:
        if rule.get("enabled", True) and _matches(rule, text, previous_hash):
            message = rule["hint"]
            if rule.get("evidence"):
                message += f"\n   ({rule['evidence']})"
            hits.append(Hit(rule["id"], message))
    return hits


def first_shown(hits: list[Hit], muted: set[str]) -> Hit | None:
    return next((h for h in hits if h.rule_id not in muted), None)
