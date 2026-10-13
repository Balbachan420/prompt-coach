"""Retire keyword hints that do not predict corrections.

A hint earns its place only if a confirmed correction follows the prompts it
fires on noticeably more often than it follows prompts in general. "Follows" means
the next prompt in the same session was a correction that the model confirmed and
did not blame on the agent. Retired hints are still evaluated and logged, so one
that starts to predict corrections comes back on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from coach import store

MIN_FIRES = 30  # labeled fires before a hint is judged
MIN_CORRECTIONS = 5  # confirmed corrections overall before any hint is judged
MIN_LIFT = 1.5  # a hint stays if its correction rate is >= 1.5x the base rate


@dataclass(frozen=True)
class RuleStat:
    rule_id: str
    fires: int
    corrections: int
    base_rate: float
    verdict: str  # "pending" | "keep" | "retire"

    @property
    def rate(self) -> float:
        return self.corrections / self.fires if self.fires else 0.0


def corrected_keys(lessons: list[dict]) -> set[tuple[str, str]]:
    """(session, prompt hash) of prompts confirmed as corrections caused by the prompt."""
    return {
        (x.get("session"), x.get("hash"))
        for x in lessons
        if x.get("is_correction") and not x.get("agent_fault") and x.get("hash")
    }


def label_events(events: list[dict], lessons: list[dict]) -> list[tuple[dict, bool]]:
    """Pair each prompt event with: was the NEXT prompt of its session a correction.

    The last prompt of a session has no next prompt yet and is left out."""
    corrected = corrected_keys(lessons)
    last_by_session: dict[str, dict] = {}
    labeled = []
    for event in events:
        session = event.get("session")
        if not session:
            continue
        prev = last_by_session.get(session)
        if prev is not None:
            labeled.append((prev, (session, event.get("hash")) in corrected))
        last_by_session[session] = event
    return labeled


def judge(events: list[dict], lessons: list[dict], rule_ids: list[str]) -> list[RuleStat]:
    labeled = label_events(events, lessons)
    total_corrections = sum(1 for _, bad in labeled if bad)
    base = total_corrections / len(labeled) if labeled else 0.0
    stats = []
    for rule_id in rule_ids:
        outcomes = [bad for event, bad in labeled if rule_id in event.get("fired", [])]
        fires, corrections = len(outcomes), sum(outcomes)
        if fires < MIN_FIRES or total_corrections < MIN_CORRECTIONS:
            verdict = "pending"
        elif corrections / fires >= base * MIN_LIFT:
            verdict = "keep"
        else:
            verdict = "retire"
        stats.append(RuleStat(rule_id, fires, corrections, base, verdict))
    return stats


def refresh() -> list[RuleStat]:
    """Recompute verdicts from the local logs and store the retired set."""
    rules = store.load_rules()
    stats = judge(store.read_events(), store.read_lessons(), [r["id"] for r in rules])
    store.save_retired({s.rule_id for s in stats if s.verdict == "retire"})
    return stats
