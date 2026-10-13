"""python3 -m coach install|uninstall|check|mute|unmute|status"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
import time
from pathlib import Path

from coach import store
from coach.checks import evaluate, first_shown
from coach.correction import TYPES

MARKER = "prompt-coach"
EVENTS = ("UserPromptSubmit", "Stop")
REPO = Path(__file__).resolve().parent.parent


def hook_command() -> str:
    # The marker comment lets install/uninstall find our entry among other hooks.
    return f'cd "{REPO}" && "{sys.executable}" -m coach.hook  # {MARKER}'


def _ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def install(settings_path: Path) -> str:
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    hooks = settings.setdefault("hooks", {})
    missing = [ev for ev in EVENTS if not any(_ours(e) for e in hooks.get(ev, []))]
    if not missing:
        return "already installed"
    if settings_path.exists():
        shutil.copy2(settings_path, settings_path.with_name(f"{settings_path.name}.bak-{MARKER}-{int(time.time())}"))
    for event in missing:
        hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": hook_command(), "timeout": 5}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"installed {', '.join(missing)} into {settings_path}"


def uninstall(settings_path: Path) -> str:
    if not settings_path.exists():
        return "nothing to remove"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})
    removed = []
    for event in EVENTS:
        before = hooks.get(event, [])
        after = [e for e in before if not _ours(e)]
        if len(after) == len(before):
            continue
        removed.append(event)
        if after:
            hooks[event] = after
        else:
            hooks.pop(event)
    if not removed:
        return "nothing to remove"
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"removed {', '.join(removed)} from {settings_path}"


def check(prompt: str) -> str:
    hits = evaluate(prompt, store.load_rules())
    shown = first_shown(hits, store.load_muted())
    if not hits:
        return "silent: no rule fired"
    lines = [f"{'→' if h is shown else ' '} {h.rule_id}: {h.message}" for h in hits]
    return "\n".join(lines)


def status() -> str:
    events = store.read_events()
    fired = collections.Counter(r for e in events for r in e.get("fired", []))
    shown = sum(1 for e in events if e.get("shown"))
    muted = store.load_muted()
    lines = [f"prompts seen: {len(events)}, hints shown: {shown}"]
    for rule in store.load_rules():
        flag = " (muted)" if rule["id"] in muted else ""
        lines.append(f"  {rule['id']:<4} fired {fired[rule['id']]:>4}  {rule.get('title', '')}{flag}")
    lessons = store.read_lessons(days=30)
    real = [x for x in lessons if x.get("is_correction") and not x.get("agent_fault")]
    candidates = sum(1 for e in events if e.get("correction_candidate"))
    lines.append(
        f"corrections, last 30 days: {candidates} candidates, {len(lessons)} analyzed, "
        f"{len(real)} lessons (agent's fault: {sum(1 for x in lessons if x.get('agent_fault'))})"
    )
    for kind, n in collections.Counter(x["type"] for x in real).most_common():
        lines.append(f"  {n:>3}  {TYPES.get(kind, kind)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coach")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--settings", type=Path, default=Path("~/.claude/settings.json").expanduser())
    sub.add_parser("check").add_argument("prompt")
    sub.add_parser("mute").add_argument("rule_id")
    sub.add_parser("unmute").add_argument("rule_id")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    if args.cmd == "install":
        print(install(args.settings))
    elif args.cmd == "uninstall":
        print(uninstall(args.settings))
    elif args.cmd == "check":
        print(check(args.prompt))
    elif args.cmd in ("mute", "unmute"):
        muted = store.load_muted()
        (muted.add if args.cmd == "mute" else muted.discard)(args.rule_id)
        store.save_muted(muted)
        print(f"muted: {', '.join(sorted(muted)) or 'none'}")
    elif args.cmd == "status":
        print(status())
    return 0
