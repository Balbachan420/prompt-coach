"""Coach at the moment of correction.

A cheap regex picks candidate corrections ("нет, не так", "мы же решили"). In the
first corpus it gave 110 candidates for 57 real corrections, so a model reading
the session decides. The model gets the session's opening prompt plus the last
few exchanges, and says what the corrected prompt lacked.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess

from coach.session import Turn, render

CANDIDATE = re.compile(
    r"(не так|не то\b|не туда|не понял|не понимаю|непонятно|ничего не понял|"
    r"я же (говорил|сказал|писал|просил)|мы же (решили|договорились|фиксировали)|"
    r"ты (забыл|опять|снова)|опять|снова не|зачем ты|почему ты|стоп\b|погоди|"
    r"не (нужно|надо)\b|неправильно|все не то|всё не то|^нет\b|"
    r"that's not|not what i|i said|we agreed|wrong|\bstop\b)",
    re.IGNORECASE,
)
TYPES = {
    "goal": "цель, объём или формат",
    "context": "факт, который знал только ты",
    "decision": "забытое решение",
    "comprehension": "непонятный ответ агента",
    "unrequested_action": "самовольное действие",
}
DEFAULT_LLM_CMD = "claude -p --model sonnet"
INNER_ENV = "PROMPT_COACH_INNER"

INSTRUCTION = """You are NOT the agent in the session below and must not continue it.
You are a reviewer. You read the session and return a JSON verdict about it.

The LAST human message may be a correction of the agent. Decide:

1. is_correction: does the last human message say the agent got something WRONG
   and must redo or change it? These are NOT corrections:
   - a question about the agent's answer ("а не нужно пересобрать?", "это что?");
   - a new or narrower task given after a good answer;
   - pasted text from elsewhere;
   - a status question or a plain "stop, wait" with no claim of error.
2. agent_fault: was the human's earlier prompt clear enough, so the agent simply
   erred? Then the lesson is not about prompting.
3. type: one of goal | context | decision | comprehension | unrequested_action
   goal = agent misread goal, scope or output format;
   context = agent lacked a fact only the human knew;
   decision = agent ignored a decision made earlier;
   comprehension = the human could not understand the agent's answer;
   unrequested_action = agent did something it was not asked to do.
4. corrected_prompt: quote (shortened) the human prompt that led to the mistake.
5. missing: what that prompt lacked, one short sentence, in Russian.
6. better_prompt: how that prompt could have been written, max 2 lines, in Russian,
   in the human's own voice.

If is_correction is false, the other fields may be empty strings.
"""
OUTPUT_FORMAT = """
Now return the verdict on the session above: ONE JSON object and nothing else.
{"is_correction": true, "agent_fault": false, "type": "goal",
 "corrected_prompt": "...", "missing": "...", "better_prompt": "..."}"""


def build_prompt(context: str) -> str:
    return f"{INSTRUCTION}\n<session>\n{context}\n</session>\n{OUTPUT_FORMAT}"


def is_candidate(prompt: str) -> bool:
    return bool(CANDIDATE.search(prompt[:400]))


def build_context(turns: list[Turn], correction: str, last_turns: int = 8) -> str:
    """Opening prompt + the tail of the session + the correction itself.

    At submit time the correction may already be the last transcript record, so it
    is dropped from the tail and appended explicitly to keep exactly one copy."""
    turns = list(turns)
    if turns and turns[-1].role == "human" and turns[-1].text.strip() == correction.strip():
        turns.pop()
    opening = next((t for t in turns if t.role == "human"), None)
    tail = turns[-last_turns:]
    parts = []
    if opening is not None and opening not in tail:
        parts += [render([opening], max_chars=1200), "[… earlier part of the session …]"]
    parts += [render(tail), render([Turn("human", correction)])]
    return "\n\n".join(parts)


def parse_verdict(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        verdict = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("is_correction"), bool):
        return None
    if verdict.get("type") not in TYPES:
        verdict["type"] = "goal"
    return verdict


class LLMError(RuntimeError):
    """The model call failed or did not return a verdict. The message is short
    and meant for the user: it is what tells a sandbox from a login problem."""


def _tail(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else "…" + text[-limit:]


def call_llm(prompt: str, timeout: int = 180) -> str:
    """Run the configured model CLI with the prompt on stdin.

    INNER_ENV marks the child, so the hooks that this inner session fires skip
    themselves instead of recursing."""
    cmd = shlex.split(os.environ.get("PROMPT_COACH_LLM_CMD", DEFAULT_LLM_CMD))
    # Resolve through PATH and PATHEXT: on Windows an npm install is `claude.cmd`,
    # which a bare "claude" does not reach.
    cmd[0] = shutil.which(cmd[0]) or cmd[0]
    env = {**os.environ, INNER_ENV: "1"}
    try:
        # Explicit UTF-8 both ways: the default is the ANSI code page on Windows,
        # which cannot encode "→" or "−" from the session text.
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        raise LLMError(f"command not found: {cmd[0]}") from None
    except subprocess.TimeoutExpired:
        raise LLMError(f"no answer within {timeout}s") from None
    if result.returncode != 0 or not result.stdout.strip():
        raise LLMError(f"{cmd[0]} exited {result.returncode}: {_tail(result.stderr or result.stdout) or 'no output'}")
    return result.stdout


def analyze(turns: list[Turn], correction: str) -> dict:
    raw = call_llm(build_prompt(build_context(turns, correction)))
    verdict = parse_verdict(raw)
    if verdict is None:
        raise LLMError(f"answer was not a JSON verdict: {_tail(raw, 160)}")
    return verdict


def lesson_text(verdict: dict, same_type_count: int) -> str:
    label = TYPES[verdict["type"]]
    nth = f" — {same_type_count}-я такая за 30 дней" if same_type_count > 1 else ""
    lines = [f"💡 coach · поправка: {label}{nth}"]
    if verdict.get("corrected_prompt"):
        lines.append(f"   Промпт: «{verdict['corrected_prompt'][:160]}»")
    if verdict.get("missing"):
        lines.append(f"   Не хватало: {verdict['missing']}")
    if verdict.get("better_prompt"):
        lines.append(f"   Можно было: «{verdict['better_prompt']}»")
    return "\n".join(lines)
