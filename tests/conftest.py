import pytest


@pytest.fixture(autouse=True)
def isolate_from_real_homes(tmp_path_factory, monkeypatch):
    """No test may read or write the real ~/.codex, ~/.claude or ~/.prompt-coach.
    Tests that need these dirs point them at their own tmp paths after this runs."""
    sandbox = tmp_path_factory.mktemp("sandbox")
    monkeypatch.setenv("CODEX_HOME", str(sandbox / "codex-absent"))
    monkeypatch.setenv("PROMPT_COACH_CODEX_DIR", str(sandbox / "codex-sessions-absent"))
    monkeypatch.setenv("PROMPT_COACH_CLAUDE_DIR", str(sandbox / "claude-absent"))
    monkeypatch.setenv("PROMPT_COACH_HOME", str(sandbox / "coach-home"))
