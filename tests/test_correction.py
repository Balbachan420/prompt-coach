import json
import subprocess
import sys
from pathlib import Path

import pytest

from coach.correction import build_context, is_candidate, lesson_text, parse_verdict
from coach.session import Turn, read_turns

REPO = Path(__file__).resolve().parent.parent
VERDICT = {
    "is_correction": True,
    "agent_fault": False,
    "type": "goal",
    "corrected_prompt": "разбери atom_v2.json",
    "missing": "зачем нужен разбор и в каком виде",
    "better_prompt": "нужно для скелета; на выходе список полей по строке",
}


def write_transcript(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return path


def human(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def agent(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


SESSION = [
    human("Продолжаем проект скелета сценариев"),
    agent({"type": "text", "text": "Понял, читаю контекст."}),
    human("разбери atom_v2.json"),
    agent({"type": "tool_use", "name": "Read", "input": {}}),
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * 5000}]}},
    agent({"type": "text", "text": "Вот все 95 ключей с весами…"}),
    human("<system-reminder>ignore me</system-reminder>"),
    {"type": "user", "isMeta": True, "message": {"content": "meta"}},
    {"type": "user", "isSidechain": True, "message": {"content": "subagent prompt"}},
    human("[Request interrupted by user]"),
    "not json at all",
]


def test_read_turns_keeps_dialogue_and_drops_harness_noise(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in SESSION))
    turns = read_turns(path)
    assert [t.role for t in turns] == ["human", "agent", "human", "agent", "interrupt"]
    assert turns[3].tools == ["Read"] and "95 ключей" in turns[3].text
    assert not any("x" * 100 in t.text for t in turns)


def test_read_turns_missing_file_is_empty():
    assert read_turns("/nonexistent/session.jsonl") == []


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("нет, всё не то, очень глубоко", True),
        ("мы же решили, что источник только YouTube", True),
        ("ничего не понял, проще", True),
        ("да, делай", False),
        ("закоммить и обнови промт новой сессии", False),
    ],
)
def test_candidate_filter(prompt, expected):
    assert is_candidate(prompt) is expected


def test_build_context_keeps_opening_and_one_copy_of_correction():
    turns = [Turn("human", "ОТКРЫВАЮЩИЙ промпт")] + [Turn("agent", f"ответ {i}") for i in range(20)]
    turns.append(Turn("human", "нет, не так"))
    context = build_context(turns, "нет, не так", last_turns=4)
    assert "ОТКРЫВАЮЩИЙ" in context
    assert context.count("нет, не так") == 1
    assert context.rstrip().endswith("HUMAN: нет, не так")


@pytest.mark.parametrize(
    "raw, ok",
    [
        (json.dumps(VERDICT), True),
        ("Sure! ```json\n" + json.dumps(VERDICT) + "\n```", True),
        ('{"is_correction": "yes"}', False),
        ("no json here", False),
        ("{broken", False),
    ],
)
def test_parse_verdict(raw, ok):
    assert (parse_verdict(raw) is not None) is ok


def test_unknown_type_falls_back_to_goal():
    assert parse_verdict(json.dumps({**VERDICT, "type": "weird"}))["type"] == "goal"


def test_lesson_text_counts_repeats():
    text = lesson_text(VERDICT, 3)
    assert "3-я такая" in text and "Не хватало" in text and "Можно было" in text
    assert "-я такая" not in lesson_text(VERDICT, 1)


# --- end to end through the hook process, with a fake model -----------------


@pytest.fixture
def env(tmp_path):
    fake = tmp_path / "fake_llm.py"
    log = tmp_path / "llm_calls.txt"
    fake.write_text(
        "import sys, json, os\n"
        f"open({str(log)!r}, 'a').write(os.environ.get('PROMPT_COACH_INNER', '-') + '\\n')\n"
        "sys.stdin.read()\n"
        f"print({json.dumps(json.dumps(VERDICT, ensure_ascii=False))})\n"
    )
    return {
        "PROMPT_COACH_HOME": str(tmp_path / "home"),
        "PROMPT_COACH_LLM_CMD": f"{sys.executable} {fake}",
        "PROMPT_COACH_SYNC": "1",
        "PATH": "/usr/bin:/bin",
        "_log": str(log),
    }


def hook(payload: dict, env: dict, **extra) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "coach.hook"],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=REPO,
        env={k: v for k, v in {**env, **extra}.items() if not k.startswith("_")},
        timeout=30,
    )
    assert out.returncode == 0
    return out.stdout


def test_correction_lesson_arrives_at_stop_once(tmp_path, env):
    transcript = write_transcript(tmp_path / "s.jsonl", SESSION[:6])
    base = {"session_id": "s1", "transcript_path": str(transcript)}

    hook({**base, "hook_event_name": "UserPromptSubmit", "prompt": "нет, всё не то, очень глубоко"}, env)
    assert Path(env["_log"]).read_text().split() == ["1"]  # model called once, marked inner

    first = hook({**base, "hook_event_name": "Stop", "stop_hook_active": False}, env)
    message = json.loads(first)["systemMessage"]
    assert "цель, объём или формат" in message and "Можно было" in message
    assert hook({**base, "hook_event_name": "Stop", "stop_hook_active": False}, env) == ""

    jobs = Path(env["PROMPT_COACH_HOME"]) / "jobs"
    assert not list(jobs.glob("*.json"))  # job file with the prompt text is cleaned up


def test_non_candidate_prompt_never_calls_model(tmp_path, env):
    transcript = write_transcript(tmp_path / "s.jsonl", SESSION[:6])
    hook({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "transcript_path": str(transcript), "prompt": "да, делай"}, env)
    assert not Path(env["_log"]).exists()


def test_inner_session_is_skipped(tmp_path, env):
    transcript = write_transcript(tmp_path / "s.jsonl", SESSION[:6])
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "transcript_path": str(transcript), "prompt": "нет, не так"}
    assert hook(payload, env, PROMPT_COACH_INNER="1") == ""
    assert not Path(env["_log"]).exists()


def test_agent_fault_gives_no_lesson(tmp_path, env):
    fake = tmp_path / "fault.py"
    fake.write_text(f"import sys; sys.stdin.read(); print({json.dumps(json.dumps({**VERDICT, 'agent_fault': True}))})\n")
    transcript = write_transcript(tmp_path / "s.jsonl", SESSION[:6])
    base = {"session_id": "s1", "transcript_path": str(transcript)}
    env = {**env, "PROMPT_COACH_LLM_CMD": f"{sys.executable} {fake}"}
    hook({**base, "hook_event_name": "UserPromptSubmit", "prompt": "нет, не так"}, env)
    assert hook({**base, "hook_event_name": "Stop"}, env) == ""
    lessons = (Path(env["PROMPT_COACH_HOME"]) / "lessons.jsonl").read_text()
    assert '"agent_fault": true' in lessons
