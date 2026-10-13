import json
import subprocess
import sys
from pathlib import Path

import pytest

from coach import cli, store

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def coach_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPT_COACH_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def run_hook(stdin: str, coach_home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "coach.hook"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PROMPT_COACH_HOME": str(coach_home), "PATH": "/usr/bin:/bin"},
        timeout=10,
    )


def payload(prompt, session="s1"):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": prompt})


def test_weak_prompt_prints_system_message(coach_home):
    out = run_hook(payload("разбери мне что там в atom_v2.json"), coach_home)
    assert out.returncode == 0
    assert "R1" in json.loads(out.stdout)["systemMessage"]


def test_good_prompt_prints_nothing(coach_home):
    out = run_hook(payload("да, делай"), coach_home)
    assert out.returncode == 0 and out.stdout == ""


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"prompt": 5}'])
def test_garbage_input_is_silent_exit_zero(stdin, coach_home):
    out = run_hook(stdin, coach_home)
    assert out.returncode == 0 and out.stdout == ""


def test_event_log_never_stores_prompt_text(coach_home):
    secret = "посмотри что там в ключе sk-very-secret-123"
    run_hook(payload(secret), coach_home)
    log = (coach_home / "events.jsonl").read_text(encoding="utf-8")
    assert "secret" not in log and "посмотри" not in log
    (event,) = [json.loads(line) for line in log.splitlines()]
    assert event["fired"] == ["R1"] and event["chars"] == len(secret)


def test_repeat_in_same_session_fires_r5_but_not_across_sessions(coach_home):
    prompt = "прочитай README и скажи, что внутри, кратко"
    run_hook(payload(prompt, "s1"), coach_home)
    assert run_hook(payload(prompt, "s2"), coach_home).stdout == ""
    assert "R5" in run_hook(payload(prompt, "s2"), coach_home).stdout


def test_muted_rule_is_logged_but_not_shown(coach_home):
    store.save_muted({"R1"})
    out = run_hook(payload("разбери мне что там в atom_v2.json"), coach_home)
    assert out.stdout == ""
    assert store.read_events()[-1]["fired"] == ["R1"]


def test_install_is_idempotent_keeps_other_hooks_and_uninstalls(tmp_path):
    settings = tmp_path / "settings.json"
    other = {"hooks": [{"type": "command", "command": "other.sh"}]}
    settings.write_text(json.dumps({"model": "x", "hooks": {"UserPromptSubmit": [other]}}))

    assert cli.install(settings).startswith("installed")
    assert cli.install(settings) == "already installed"
    data = json.loads(settings.read_text())
    assert data["model"] == "x" and len(data["hooks"]["UserPromptSubmit"]) == 2
    assert list(tmp_path.glob("settings.json.bak-prompt-coach-*"))

    assert cli.uninstall(settings).startswith("removed")
    assert json.loads(settings.read_text())["hooks"]["UserPromptSubmit"] == [other]
    assert cli.uninstall(settings) == "nothing to remove"
