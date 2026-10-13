import json

import pytest

from coach.checks import evaluate, first_shown, merge_rules, prompt_hash
from coach.store import DEFAULT_CHECKS

RULES = merge_rules(json.loads(DEFAULT_CHECKS.read_text(encoding="utf-8"))["rules"], [])


def fired(prompt, previous_hash=None):
    return [h.rule_id for h in evaluate(prompt, RULES, previous_hash=previous_hash)]


@pytest.mark.parametrize(
    "prompt, rule",
    [
        ("разбери мне что там в atom_v2.json", "R1"),
        ("посмотри логи бота за вчера", "R1"),
        ("почисти кеши на диске", "R4"),
        ("/home/user/project/ПРОМТ_ПЛАТНЫЙ_ПРОГОН.md", "R4P"),
        ("'docs/next_prompt.md'", "R4P"),
        ("запускай прогон на всех роликах", "R6"),
        ("что лучше взять? и сколько это стоит?", "R9"),
    ],
)
def test_weak_prompt_fires_its_rule(prompt, rule):
    assert rule in fired(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "разбери atom_v2.json, нужно для скелета сценария; на выходе список полей по одной строке",
        "посмотри логи бота, чтобы понять, почему упал онбординг",
        "почисти кеши, но сначала план и сколько места освободится",
        "ничего не удаляй, только посмотри, что занимает диск, чтобы освободить 20 ГБ",
        "/plugin:coach status",
        "запускай прогон, по завершении дай итог таблицей",
        "как прогон?",
        "1) что лучше взять? 2) сколько это стоит?",
        "да, делай",
        "/insights",
        "",
    ],
)
def test_good_or_neutral_prompt_is_silent(prompt):
    assert fired(prompt) == []


def test_repeat_previous_needs_same_session_hash():
    prompt = "прочитай README и скажи, что внутри, кратко"
    assert fired(prompt) == []
    assert fired(prompt, previous_hash=prompt_hash(prompt)) == ["R5"]
    assert fired(prompt, previous_hash=prompt_hash("другое")) == []


def test_hash_ignores_case_and_whitespace():
    assert prompt_hash("Да  делай\n") == prompt_hash("да делай")


def test_only_first_unmuted_hit_is_shown():
    hits = evaluate("почисти кеши и посмотри, что там с логами", RULES)
    assert [h.rule_id for h in hits][:1] == ["R4"]
    assert first_shown(hits, set()).rule_id == "R4"
    assert first_shown(hits, {"R4"}).rule_id == "R1"
    assert first_shown(hits, {"R4", "R1"}) is None


def test_personal_rule_overrides_default_by_id():
    rules = merge_rules(
        [{"id": "R1", "hint": "generic", "priority": 25}],
        [{"id": "R1", "evidence": "27 of 57"}, {"id": "X1", "hint": "mine", "priority": 1}],
    )
    assert [r["id"] for r in rules] == ["X1", "R1"]
    assert rules[1]["hint"] == "generic" and rules[1]["evidence"] == "27 of 57"


def test_evidence_is_appended_to_message():
    rules = merge_rules(RULES, [{"id": "R1", "evidence": "27 из 57 твоих поправок"}])
    (hit,) = evaluate("разбери мне что там в atom_v2.json", rules)
    assert "27 из 57" in hit.message
