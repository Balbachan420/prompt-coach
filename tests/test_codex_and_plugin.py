import json
import subprocess
import sys
from pathlib import Path

import pytest

from coach import codex_install, store

REPO = Path(__file__).resolve().parent.parent

EXISTING_TOML = """model = "gpt-5.5"

[features]
hooks = true

[[hooks.SessionStart]]

[[hooks.SessionStart.hooks]]
type = "command"
command = "/opt/session-start.sh"

[hooks.state]

[hooks.state."/x/config.toml:session_start:0:0"]
trusted_hash = "sha256:abc"
"""


@pytest.fixture
def codex(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PROMPT_COACH_HOME", str(tmp_path / "coach"))
    return home


def test_inline_hooks_get_a_marked_block_that_parses_and_reverts(codex):
    tomllib = pytest.importorskip("tomllib")
    config = codex / "config.toml"
    config.write_text(EXISTING_TOML)

    assert "added to" in codex_install.install()
    data = tomllib.loads(config.read_text())
    assert data["hooks"]["state"]["/x/config.toml:session_start:0:0"]["trusted_hash"] == "sha256:abc"
    for event in ("UserPromptSubmit", "Stop"):
        assert "prompt-coach" in data["hooks"][event][0]["hooks"][0]["command"]
    assert not (codex / "hooks.json").exists()  # one layer, no merge warning
    assert list(codex.glob("config.toml.bak-prompt-coach-*"))

    assert "already installed" in codex_install.install()
    assert config.read_text().count("[[hooks.Stop]]") == 1

    assert "removed" in codex_install.uninstall()
    assert config.read_text().strip() == EXISTING_TOML.strip()


def test_no_inline_hooks_uses_hooks_json(codex):
    (codex / "config.toml").write_text('model = "x"\n')
    other = {"hooks": [{"type": "command", "command": "other.sh"}]}
    (codex / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [other]}}))

    codex_install.install()
    data = json.loads((codex / "hooks.json").read_text())
    assert len(data["hooks"]["Stop"]) == 2 and len(data["hooks"]["UserPromptSubmit"]) == 1
    assert (codex / "config.toml").read_text() == 'model = "x"\n'

    codex_install.uninstall()
    data = json.loads((codex / "hooks.json").read_text())
    assert data["hooks"] == {"Stop": [other]}


def test_missing_codex_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    assert "skipped" in codex_install.install()


def test_shim_runs_the_hook_as_codex_via_root_pointer(codex, tmp_path):
    (codex / "config.toml").write_text("")
    codex_install.install()
    shim = codex_install.shim_path()
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "x"}}) + "\n")
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "cx", "transcript_path": str(rollout),
               "prompt": "разбери мне что там в atom_v2.json"}
    out = subprocess.run([sys.executable, str(shim)], input=json.dumps(payload, ensure_ascii=False),
                         capture_output=True, text=True, cwd=tmp_path, timeout=10,
                         env={"PROMPT_COACH_HOME": str(store.home()), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0 and "R1" in json.loads(out.stdout)["systemMessage"]
    assert store.read_events()[-1]["provider"] == "codex"


def test_shim_is_silent_when_code_moved_away(codex, tmp_path):
    (codex / "config.toml").write_text("")
    codex_install.install()
    (store.home() / "root").write_text(str(tmp_path / "gone"))
    out = subprocess.run([sys.executable, str(codex_install.shim_path())], input="{}", capture_output=True,
                         text=True, timeout=10, env={"PROMPT_COACH_HOME": str(store.home()), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0 and out.stdout == ""


# --- plugin entry points -------------------------------------------------------


def run_bin(args, stdin="", home=None):
    return subprocess.run([sys.executable, str(REPO / "bin" / "prompt-coach"), *args], input=stdin,
                          capture_output=True, text=True, cwd="/", timeout=10,
                          env={"PROMPT_COACH_HOME": str(home), "PATH": "/usr/bin:/bin"})


def test_plugin_hooks_file_points_at_bin(tmp_path):
    hooks = json.loads((REPO / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "Stop", "SessionStart"}
    for entries in hooks.values():
        assert entries[0]["hooks"][0]["command"].endswith('/bin/prompt-coach" hook claude')


def test_bin_runs_hook_from_any_cwd_and_records_root(tmp_path):
    home = tmp_path / "coach"
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "почисти кеши на диске"}
    out = run_bin(["hook", "claude"], json.dumps(payload, ensure_ascii=False), home)
    assert "R4" in json.loads(out.stdout)["systemMessage"]
    assert (home / "root").read_text() == str(REPO)


def test_session_start_offers_scan_once(tmp_path):
    home = tmp_path / "coach"
    start = json.dumps({"hook_event_name": "SessionStart", "session_id": "s"})
    first = run_bin(["hook", "claude"], start, home)
    assert "/prompt-coach:scan" in json.loads(first.stdout)["systemMessage"]
    assert run_bin(["hook", "claude"], start, home).stdout == ""


def test_session_start_silent_after_a_scan(tmp_path):
    home = tmp_path / "coach"
    home.mkdir()
    (home / "events.jsonl").write_text(json.dumps({"session": "old", "source": "scan", "fired": []}) + "\n")
    start = json.dumps({"hook_event_name": "SessionStart", "session_id": "s"})
    assert run_bin(["hook", "claude"], start, home).stdout == ""


def test_manifests_agree_on_name():
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["name"] == market["plugins"][0]["name"] == "prompt-coach"
    assert market["plugins"][0]["source"] == "./"
