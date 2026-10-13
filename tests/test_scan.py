import json
import os
import sys
from pathlib import Path

import pytest

from coach import cli, scan, store
from coach.sources import claude_sources, codex_sources, read_codex_turns

VERDICT = {
    "is_correction": True,
    "agent_fault": False,
    "type": "goal",
    "corrected_prompt": "разбери atom_v2.json",
    "missing": "зачем и в каком виде",
    "better_prompt": "нужно для скелета; на выходе список полей",
}


def jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return path


def claude_session(entrypoint="cli"):
    meta = {"type": "user", "entrypoint": entrypoint, "message": {"content": "разбери atom_v2.json"}}
    return [
        meta,
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Вот все 95 ключей"}]}},
        {"type": "user", "entrypoint": entrypoint, "message": {"content": "нет, всё не то, очень глубоко"}},
    ]


def codex_session(source="cli", originator="codex-tui", sid="codex-1"):
    return [
        {"type": "session_meta", "payload": {"id": sid, "originator": originator, "source": source}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md injected"}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "посмотри логи бота"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": "{}"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "В логах 3 ошибки"}},
        {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "мы же решили смотреть только онбординг"}},
    ]


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    claude, codex = tmp_path / "claude", tmp_path / "codex"
    monkeypatch.setenv("PROMPT_COACH_CLAUDE_DIR", str(claude))
    monkeypatch.setenv("PROMPT_COACH_CODEX_DIR", str(codex))
    monkeypatch.setenv("PROMPT_COACH_HOME", str(tmp_path / "home"))
    jsonl(claude / "proj" / "c-live.jsonl", claude_session("cli"))
    jsonl(claude / "proj" / "c-sdk.jsonl", claude_session("sdk-cli"))
    jsonl(claude / "proj" / "c-live" / "subagents" / "agent-1.jsonl", claude_session("cli"))
    jsonl(codex / "2026" / "10" / "01" / "rollout-a.jsonl", codex_session())
    jsonl(codex / "2026" / "10" / "02" / "rollout-b.jsonl", codex_session("exec", "codex_exec", "codex-exec"))
    return tmp_path


@pytest.fixture
def fake_llm(tmp_path, monkeypatch):
    fake = tmp_path / "fake_llm.py"
    fake.write_text(f"import sys; sys.stdin.read(); print({json.dumps(json.dumps(VERDICT, ensure_ascii=False))})\n")
    monkeypatch.setenv("PROMPT_COACH_LLM_CMD", f"{sys.executable} {fake}")


def test_discovery_skips_programmatic_and_subagent_sessions(dirs):
    assert [s.session_id for s in claude_sources()] == ["c-live"]
    assert [s.session_id for s in codex_sources()] == ["codex-1"]


def test_codex_reader_uses_typed_text_not_injected_context(dirs):
    path = next(codex_sources()).path
    turns = read_codex_turns(path)
    assert [t.role for t in turns] == ["human", "agent", "interrupt", "human"]
    assert turns[0].text == "посмотри логи бота"
    assert turns[1].tools == ["exec_command"] and "3 ошибки" in turns[1].text
    assert not any("AGENTS.md" in t.text for t in turns)


def test_dry_run_counts_without_writing(dirs, capsys):
    assert cli.main(["scan", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "claude  sessions    1  prompts     2  correction candidates    1" in out
    assert "codex   sessions    1  prompts     2  correction candidates    1" in out
    assert not (Path(os.environ["PROMPT_COACH_HOME"]) / "events.jsonl").exists()


def test_scan_writes_dated_events_and_lessons_and_is_idempotent(dirs, fake_llm, capsys):
    os.utime(next(codex_sources()).path, (1_700_000_000, 1_700_000_000))
    assert cli.main(["scan", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "caused by the prompt 2" in out and "Можно было" in out

    events = store.read_events()
    assert len(events) == 4 and {e["provider"] for e in events} == {"claude", "codex"}
    assert all("посмотри" not in json.dumps(e, ensure_ascii=False) for e in events)
    codex_events = [e for e in events if e["provider"] == "codex"]
    assert all(e["ts"] == 1_700_000_000 for e in codex_events)
    assert codex_events[0]["fired"] == ["R1"]

    lessons = store.read_lessons()
    assert {x["provider"] for x in lessons} == {"claude", "codex"}
    assert all(x["hash"] for x in lessons)

    plan = scan.build_plan(["claude", "codex"])
    assert plan.events == [] and plan.candidates == []


@pytest.fixture
def claude_on_path(monkeypatch):
    real_which = cli.shutil.which
    monkeypatch.setattr(cli.shutil, "which", lambda name, *a, **k: "/usr/bin/claude" if name == "claude" else real_which(name, *a, **k))


def test_scan_asks_before_model_calls(dirs, fake_llm, claude_on_path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert cli.main(["scan"]) == 1
    assert "skipped" in capsys.readouterr().out
    assert store.read_events() == [] and store.read_lessons() == []


def test_scan_skips_sessions_already_seen_live(dirs):
    store.append_event({"session": "c-live", "hash": "x", "fired": []})
    plan = scan.build_plan(["claude"])
    assert plan.sessions["claude"] == 0


def test_install_offers_scan_and_enter_means_yes(dirs, fake_llm, claude_on_path, monkeypatch, capsys, tmp_path):
    asked = []
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "")
    assert cli.main(["install", "--settings", str(tmp_path / "settings.json")]) == 0
    out = capsys.readouterr().out
    assert asked and "[Y/n]" in asked[0]
    assert "analyzed 2/2" in out and "caused by the prompt 2" in out
    assert "Что дальше" in out and "Команды" in out
    assert len(store.read_lessons()) == 2


def test_install_without_terminal_skips_model_calls(dirs, fake_llm, claude_on_path, monkeypatch, capsys, tmp_path):
    def no_tty(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_tty)
    assert cli.main(["install", "--settings", str(tmp_path / "settings.json")]) == 0
    assert "Run `python3 -m coach scan` any time" in capsys.readouterr().out
    assert store.read_lessons() == []


def test_install_without_claude_cli_explains(dirs, fake_llm, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not ask"))
    assert cli.main(["install", "--settings", str(tmp_path / "settings.json")]) == 0
    assert "`claude` is not on PATH" in capsys.readouterr().out


def test_install_no_scan_flag(dirs, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not ask"))
    assert cli.main(["install", "--no-scan", "--settings", str(tmp_path / "settings.json")]) == 0
    assert "Looking for your past sessions" not in capsys.readouterr().out


def failing_llm(tmp_path, monkeypatch, body):
    fake = tmp_path / "bad_llm.py"
    fake.write_text("import sys; sys.stdin.read()\n" + body)
    monkeypatch.setenv("PROMPT_COACH_LLM_CMD", f"{sys.executable} {fake}")


def test_failed_model_calls_are_reported_and_retried(dirs, tmp_path, claude_on_path, monkeypatch, capsys):
    failing_llm(tmp_path, monkeypatch, "sys.stderr.write('Error: connect EPERM api.anthropic.com (sandbox)'); sys.exit(1)\n")
    assert cli.main(["scan", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "FAILED 2 of 2" in out and "EPERM api.anthropic.com" in out and "sandbox" in out
    assert store.read_lessons() == []
    assert len(store.read_events()) == 4
    assert len(store.read_errors()) == 2

    plan = scan.build_plan(["claude", "codex"])
    assert plan.events == [] and len(plan.candidates) == 2  # retried, not logged twice

    fake = tmp_path / "good_llm.py"
    fake.write_text(f"import sys; sys.stdin.read(); print({json.dumps(json.dumps(VERDICT, ensure_ascii=False))})\n")
    monkeypatch.setenv("PROMPT_COACH_LLM_CMD", f"{sys.executable} {fake}")
    assert cli.main(["scan", "--yes"]) == 0
    assert len(store.read_lessons()) == 2 and len(store.read_events()) == 4
    assert scan.build_plan(["claude", "codex"]).candidates == []


def test_non_json_answer_is_a_reported_failure(dirs, tmp_path, claude_on_path, monkeypatch, capsys):
    failing_llm(tmp_path, monkeypatch, "print('Sure, I will continue the session for you…')\n")
    cli.main(["scan", "--yes"])
    assert "answer was not a JSON verdict" in capsys.readouterr().out


def test_missing_model_command_is_a_reported_failure(dirs, claude_on_path, monkeypatch, capsys):
    monkeypatch.setenv("PROMPT_COACH_LLM_CMD", "definitely-not-a-command-xyz -p")
    cli.main(["scan", "--yes"])
    assert "command not found: definitely-not-a-command-xyz" in capsys.readouterr().out
