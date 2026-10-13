import json
import subprocess
import sys
from pathlib import Path

import pytest

from coach import retire, store

REPO = Path(__file__).resolve().parent.parent


def build_log(n_sessions: int, fire_rule, corrected_after) -> tuple[list[dict], list[dict]]:
    """n sessions of two prompts each: p0 (maybe fires a rule), then p1.

    `corrected_after(i)` says whether p1 of session i was a confirmed correction."""
    events, lessons = [], []
    for i in range(n_sessions):
        s = f"s{i}"
        events.append({"session": s, "hash": f"{s}-p0", "fired": fire_rule(i)})
        events.append({"session": s, "hash": f"{s}-p1", "fired": []})
        if corrected_after(i):
            lessons.append({"session": s, "hash": f"{s}-p1", "is_correction": True, "agent_fault": False})
    return events, lessons


def verdict(events, lessons, rule="R1"):
    (stat,) = retire.judge(events, lessons, [rule])
    return stat


def test_rule_that_predicts_corrections_is_kept():
    # R1 fires in sessions 0..39; corrections follow 20 of them and 2 of the other 60.
    events, lessons = build_log(100, lambda i: ["R1"] if i < 40 else [], lambda i: i < 20 or i in (50, 60))
    stat = verdict(events, lessons)
    assert stat.fires == 40 and stat.corrections == 20
    assert stat.verdict == "keep"


def test_rule_with_no_lift_is_retired():
    # R1 fires everywhere but corrections are spread evenly: no lift over the base.
    events, lessons = build_log(100, lambda i: ["R1"] if i % 2 == 0 else [], lambda i: i % 10 == 0 or i % 10 == 5)
    stat = verdict(events, lessons)
    assert stat.verdict == "retire"


def test_not_enough_fires_stays_pending():
    events, lessons = build_log(100, lambda i: ["R1"] if i < retire.MIN_FIRES - 1 else [], lambda i: i % 10 == 0)
    assert verdict(events, lessons).verdict == "pending"


def test_not_enough_corrections_overall_stays_pending():
    events, lessons = build_log(100, lambda i: ["R1"], lambda i: i < retire.MIN_CORRECTIONS - 1)
    assert verdict(events, lessons).verdict == "pending"


def test_agent_fault_and_rejected_candidates_do_not_count():
    events, lessons = build_log(40, lambda i: ["R1"], lambda i: False)
    lessons = [
        {"session": f"s{i}", "hash": f"s{i}-p1", "is_correction": True, "agent_fault": True} for i in range(20)
    ] + [{"session": f"s{i}", "hash": f"s{i}-p1", "is_correction": False} for i in range(20, 40)]
    assert retire.label_events(events, lessons) and not any(bad for _, bad in retire.label_events(events, lessons))


def test_last_prompt_of_a_session_is_not_labeled_yet():
    events = [{"session": "a", "hash": "1", "fired": ["R1"]}]
    assert retire.label_events(events, []) == []


def test_correction_in_another_session_does_not_leak():
    events = [
        {"session": "a", "hash": "a0", "fired": ["R1"]},
        {"session": "b", "hash": "b0", "fired": []},
        {"session": "a", "hash": "a1", "fired": []},
        {"session": "b", "hash": "b1", "fired": []},
    ]
    lessons = [{"session": "b", "hash": "b1", "is_correction": True, "agent_fault": False}]
    labeled = {e["hash"]: bad for e, bad in retire.label_events(events, lessons)}
    assert labeled == {"a0": False, "b0": True}


# --- the retired set reaches the hook and comes back when the evidence changes ----


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPT_COACH_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def write_logs(home: Path, events, lessons):
    home.mkdir(parents=True, exist_ok=True)
    (home / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (home / "lessons.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lessons))


def test_retired_rule_is_silent_in_hook_and_revives(home):
    noisy = build_log(100, lambda i: ["R1"] if i % 2 == 0 else [], lambda i: i % 10 in (0, 5))
    write_logs(home, *noisy)
    retire.refresh()
    assert store.load_retired() == {"R1"}

    out = subprocess.run(
        [sys.executable, "-m", "coach.hook"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "new", "prompt": "разбери мне что там в atom_v2.json"}, ensure_ascii=False),
        capture_output=True, text=True, cwd=REPO,
        env={"PROMPT_COACH_HOME": str(home), "PATH": "/usr/bin:/bin"}, timeout=10,
    )
    assert out.stdout == ""
    assert store.read_events()[-1]["fired"] == ["R1"]  # still evaluated and logged

    useful = build_log(100, lambda i: ["R1"] if i < 40 else [], lambda i: i < 20 or i in (50, 60))
    write_logs(home, *useful)
    retire.refresh()
    assert store.load_retired() == set()


def test_retired_and_muted_are_kept_apart(home):
    store.save_muted({"R9"})
    store.save_retired({"R1"})
    assert store.load_muted() == {"R9"} and store.load_retired() == {"R1"}
