"""Scan past sessions of every provider: log prompts, find and analyze corrections.

The live hooks only see sessions from the moment the coach was installed. A scan
backfills the same two logs from history, dated by each session's file time:
  events.jsonl   one event per human prompt, with the keyword hints that would
                 have fired, so auto-retire gets verdicts without waiting weeks;
  lessons.jsonl  a model verdict for every correction candidate.
Sessions already in the event log are not logged twice, and a candidate is
analyzed only if it has no lesson yet. So a re-run is safe, and it retries the
candidates whose model call failed last time.
"""

from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from coach import retire, store
from coach.checks import evaluate, prompt_hash
from coach.correction import TYPES, LLMError, analyze, is_candidate
from coach.session import Turn
from coach.sources import PROVIDERS, Source, read_source


@dataclass
class Candidate:
    source: Source
    turns: list[Turn]  # the session up to, not including, the correction
    prompt: str
    ts: int


@dataclass
class Plan:
    events: list[dict] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    sessions: collections.Counter = field(default_factory=collections.Counter)
    prompts: collections.Counter = field(default_factory=collections.Counter)


def build_plan(providers: list[str], since_ts: float = 0) -> Plan:
    seen = {e.get("session") for e in store.read_events()}
    analyzed = {(x.get("session"), x.get("hash")) for x in store.read_lessons()}
    rules = store.load_rules()
    plan = Plan()
    for provider in providers:
        for source in PROVIDERS[provider]():
            try:
                ts = int(source.path.stat().st_mtime)
            except OSError:
                continue
            if ts < since_ts:
                continue
            turns = read_source(source)
            humans = [i for i, t in enumerate(turns) if t.role == "human"]
            if not humans:
                continue
            new_session = source.session_id not in seen
            if new_session:
                plan.sessions[provider] += 1
            previous = None
            for i in humans:
                text = turns[i].text
                candidate = i > humans[0] and is_candidate(text)
                hits = evaluate(text, rules, previous_hash=previous)
                previous = prompt_hash(text)
                if new_session:
                    plan.prompts[provider] += 1
                    plan.events.append(
                        {
                            "ts": ts,
                            "session": source.session_id,
                            "provider": provider,
                            "source": "scan",
                            "hash": previous,
                            "chars": len(text),
                            "fired": [h.rule_id for h in hits],
                            "shown": None,
                            "correction_candidate": candidate,
                        }
                    )
                if candidate and (source.session_id, previous) not in analyzed:
                    plan.candidates.append(Candidate(source, turns[:i], text, ts))
    return plan


def summary(plan: Plan) -> str:
    per = collections.Counter(c.source.provider for c in plan.candidates)
    lines = ["new sessions to scan:"]
    for provider in sorted(set(plan.sessions) | set(PROVIDERS)):
        lines.append(
            f"  {provider:<7} sessions {plan.sessions[provider]:>4}  prompts {plan.prompts[provider]:>5}  "
            f"correction candidates {per[provider]:>4}"
        )
    lines.append(f"model calls needed: {len(plan.candidates)} (one per candidate not analyzed yet)")
    return "\n".join(lines)


@dataclass
class Result:
    lessons: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _analyze(candidate: Candidate) -> tuple[Candidate, dict | None, str | None]:
    try:
        return candidate, analyze(candidate.turns, candidate.prompt), None
    except LLMError as error:
        return candidate, None, str(error)
    except Exception as error:  # noqa: BLE001 — one failed call must not stop the scan
        return candidate, None, f"{type(error).__name__}: {error}"


def run(plan: Plan, workers: int = 4, progress=None) -> Result:
    for event in plan.events:
        store.append_event(event)
    result = Result()
    with ThreadPoolExecutor(workers) as pool:
        for done, (candidate, verdict, error) in enumerate(pool.map(_analyze, plan.candidates), 1):
            if progress:
                progress(done)
            if verdict is None:
                result.errors.append(error or "unknown error")
                store.log_error("scan", error or "unknown error")
                continue
            lesson = {
                "ts": candidate.ts,
                "session": candidate.source.session_id,
                "provider": candidate.source.provider,
                "source": "scan",
                "hash": prompt_hash(candidate.prompt),
                **verdict,
            }
            store.append_lesson(lesson)
            result.lessons.append(lesson)
    retire.refresh()
    return result


FAILURE_HINT = (
    "Неудавшиеся разборы повторятся при следующем запуске scan. Частые причины: песочница (sandbox) "
    "Claude Code закрывает команде сеть или запись в ~/.claude; `claude` не залогинен; модель sonnet "
    "недоступна на вашем аккаунте. Причина — в строках выше."
)


def report(result: Result, examples: int = 3) -> str:
    lessons = result.lessons
    real = [x for x in lessons if x.get("is_correction") and not x.get("agent_fault")]
    lines = []
    if result.errors:
        lines.append(f"FAILED {len(result.errors)} of {len(result.errors) + len(lessons)} analyses. Reasons:")
        for reason, n in collections.Counter(result.errors).most_common(3):
            lines.append(f"  {n} × {reason}")
        lines += [FAILURE_HINT, ""]
    lines += [
        f"analyzed {len(lessons)}: real corrections {sum(1 for x in lessons if x.get('is_correction'))}, "
        f"caused by the prompt {len(real)}, agent's fault {sum(1 for x in lessons if x.get('agent_fault'))}"
    ]
    by_provider = collections.Counter(x.get("provider") for x in real)
    lines.append("  by provider: " + ", ".join(f"{p} {n}" for p, n in by_provider.most_common()))
    for kind, n in collections.Counter(x["type"] for x in real).most_common():
        lines.append(f"  {n:>3}  {TYPES.get(kind, kind)}")
    for x in real[:examples]:
        lines += [
            "",
            f"[{x.get('provider')}] {TYPES.get(x['type'], x['type'])}",
            f"  Промпт: «{(x.get('corrected_prompt') or '')[:140]}»",
            f"  Не хватало: {x.get('missing', '')}",
            f"  Можно было: «{x.get('better_prompt', '')}»",
        ]
    return "\n".join(lines)
