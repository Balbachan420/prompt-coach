"""Windows reads and writes stdio in the ANSI code page (cp1251 on a Russian
system). PYTHONIOENCODING=cp1251 makes a child Python behave the same way here."""

import json
import subprocess
import sys
from pathlib import Path

from coach import correction

REPO = Path(__file__).resolve().parent.parent
CP1251 = {"PYTHONIOENCODING": "cp1251", "PATH": "/usr/bin:/bin"}


def run(args, stdin_bytes: bytes, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], input=stdin_bytes, capture_output=True, cwd=REPO,
                          env={**CP1251, "PROMPT_COACH_HOME": str(home)}, timeout=15)


def test_hook_reads_utf8_json_and_prints_emoji_under_cp1251(tmp_path):
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "w",
               "prompt": "почисти кеши → освободи место − быстро"}
    out = run(["-m", "coach.hook"], json.dumps(payload, ensure_ascii=False).encode("utf-8"), tmp_path)
    assert out.returncode == 0
    message = json.loads(out.stdout.decode("utf-8"))["systemMessage"]
    assert message.startswith("💡 coach · R4")


def test_cli_prints_the_memo_under_cp1251(tmp_path):
    out = run(["-m", "coach", "help"], b"", tmp_path)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert "💡 Prompt Coach" in out.stdout.decode("utf-8")


def test_model_call_is_utf8_regardless_of_locale(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        kwargs["input"].encode(kwargs["encoding"])  # what failed on Windows with cp1251
        return subprocess.CompletedProcess(cmd, 0, stdout='{"is_correction": false}', stderr="")

    monkeypatch.setattr(correction.subprocess, "run", fake_run)
    correction.call_llm("было → стало, разница − 3")
    assert seen["encoding"] == "utf-8" and "text" not in seen


def test_model_command_is_resolved_through_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(correction.shutil, "which", lambda name: f"C:/npm/{name}.cmd")
    monkeypatch.setattr(correction.subprocess, "run",
                        lambda cmd, **kw: seen.setdefault("cmd", cmd) and subprocess.CompletedProcess(cmd, 0, "{}", ""))
    try:
        correction.call_llm("x")
    except correction.LLMError:
        pass
    assert seen["cmd"][0] == "C:/npm/claude.cmd"
