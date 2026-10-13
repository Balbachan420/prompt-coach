"""Install the coach's live hooks into Codex.

Codex reads hooks from ~/.codex/hooks.json and from inline [hooks] tables in
~/.codex/config.toml, and warns at startup when one layer has both. So: if
config.toml already has inline hooks, our block is appended there between marker
comments; otherwise our entries go to hooks.json.

The hook command runs a small shim in ~/.prompt-coach that finds the coach code
through ~/.prompt-coach/root. A plugin update moves the code, and the Codex
config, which sits outside the plugin, never has to change.

Codex skips new hooks until the user trusts them in `/hooks`. That step stays
with the user on purpose; the coach never writes trust records.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from coach import store

MARK_START = "# >>> prompt-coach (managed block, remove with: prompt-coach codex-uninstall)"
MARK_END = "# <<< prompt-coach"
MARKER = "prompt-coach"
EVENTS = ("UserPromptSubmit", "Stop")
REPO = Path(__file__).resolve().parent.parent
INLINE_HOOKS = re.compile(r"^\s*\[\[?\s*hooks[.\]]", re.MULTILINE)
TRUST_NOTE = (
    "Codex runs new hooks only after you trust them: open Codex, run /hooks, "
    "and trust the two prompt-coach hooks (UserPromptSubmit, Stop)."
)

SHIM = '''"""prompt-coach Codex hook shim. Finds the coach code via ~/.prompt-coach/root."""
import os
import sys
from pathlib import Path

home = Path(os.environ.get("PROMPT_COACH_HOME", "~/.prompt-coach")).expanduser()
try:
    root = (home / "root").read_text(encoding="utf-8").strip()
    sys.path.insert(0, root)
    from coach.hook import main
except Exception:
    sys.exit(0)
sys.exit(main(["codex"]))
'''


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def shim_path() -> Path:
    return store.home() / "codex_hook.py"


def hook_command() -> str:
    return f'"{sys.executable}" "{shim_path()}"  # {MARKER}'


def _toml_block() -> str:
    lines = [MARK_START]
    for event in EVENTS:
        lines += [
            f"[[hooks.{event}]]",
            "",
            f"[[hooks.{event}.hooks]]",
            'type = "command"',
            f"command = {json.dumps(hook_command())}",
            "timeout = 5",
            "",
        ]
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def _check_toml(text: str) -> None:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        return
    data = tomllib.loads(text)
    for event in EVENTS:
        commands = [h.get("command", "") for e in data["hooks"][event] for h in e.get("hooks", [])]
        if not any(MARKER in c for c in commands):
            raise ValueError(f"{event} hook missing after edit")


def _backup(path: Path) -> None:
    shutil.copy2(path, path.with_name(f"{path.name}.bak-{MARKER}-{int(time.time())}"))


def install() -> str:
    home = codex_home()
    if not home.exists():
        return f"Codex not found ({home}), skipped"
    store.home().mkdir(parents=True, exist_ok=True)
    shim_path().write_text(SHIM, encoding="utf-8")
    store.remember_root(REPO)

    config = home / "config.toml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    if INLINE_HOOKS.search(text):
        if MARK_START in text:
            return f"Codex hooks already installed in {config}\n{TRUST_NOTE}"
        new = text.rstrip("\n") + "\n\n" + _toml_block()
        _check_toml(new)  # never leave Codex with a config it cannot parse
        _backup(config)
        config.write_text(new, encoding="utf-8")
        return f"Codex hooks added to {config}\n{TRUST_NOTE}"

    hooks_json = home / "hooks.json"
    data = json.loads(hooks_json.read_text(encoding="utf-8")) if hooks_json.exists() else {}
    events = data.setdefault("hooks", {})
    added = []
    for event in EVENTS:
        entries = events.setdefault(event, [])
        if not any(MARKER in h.get("command", "") for e in entries for h in e.get("hooks", [])):
            entries.append({"hooks": [{"type": "command", "command": hook_command(), "timeout": 5}]})
            added.append(event)
    if not added:
        return f"Codex hooks already installed in {hooks_json}\n{TRUST_NOTE}"
    if hooks_json.exists():
        _backup(hooks_json)
    hooks_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"Codex hooks added to {hooks_json}\n{TRUST_NOTE}"


def uninstall() -> str:
    home, removed = codex_home(), []
    config = home / "config.toml"
    if config.exists():
        text = config.read_text(encoding="utf-8")
        if MARK_START in text:
            start = text.index(MARK_START)
            end = text.index(MARK_END, start) + len(MARK_END)
            config.write_text(text[:start].rstrip("\n") + "\n" + text[end:].lstrip("\n"), encoding="utf-8")
            removed.append(str(config))
    hooks_json = home / "hooks.json"
    if hooks_json.exists():
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        events = data.get("hooks", {})
        changed = False
        for event in EVENTS:
            before = events.get(event, [])
            after = [e for e in before if not any(MARKER in h.get("command", "") for h in e.get("hooks", []))]
            if len(after) != len(before):
                changed = True
                if after:
                    events[event] = after
                else:
                    events.pop(event)
        if changed:
            hooks_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            removed.append(str(hooks_json))
    return f"Codex hooks removed from {', '.join(removed)}" if removed else "no Codex hooks to remove"
