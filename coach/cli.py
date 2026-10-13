"""python3 -m coach install|uninstall|check|mute|unmute|status"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
import time
from pathlib import Path

from coach import codex_install, memo, retire, scan, store
from coach.checks import evaluate, first_shown
from coach.correction import TYPES
from coach.sources import PROVIDERS

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
    verdicts = {s.rule_id: s for s in retire.refresh()}
    lines = [f"prompts seen: {len(events)}, hints shown: {shown}"]
    for rule in store.load_rules():
        stat = verdicts[rule["id"]]
        if rule["id"] in muted:
            note = "muted by you"
        elif stat.verdict == "pending":
            note = f"judging: {stat.fires}/{retire.MIN_FIRES} labeled fires"
        else:
            note = (
                f"{'kept' if stat.verdict == 'keep' else 'RETIRED'}: corrections after it "
                f"{stat.rate:.0%} vs base {stat.base_rate:.0%}"
            )
        lines.append(f"  {rule['id']:<4} fired {fired[rule['id']]:>4}  {rule.get('title', '')}  [{note}]")
    lessons = store.read_lessons(days=30)
    real = [x for x in lessons if x.get("is_correction") and not x.get("agent_fault")]
    candidates = sum(1 for e in events if e.get("correction_candidate"))
    lines.append(
        f"corrections, last 30 days: {candidates} candidates, {len(lessons)} analyzed, "
        f"{len(real)} lessons (agent's fault: {sum(1 for x in lessons if x.get('agent_fault'))})"
    )
    for kind, n in collections.Counter(x["type"] for x in real).most_common():
        lines.append(f"  {n:>3}  {TYPES.get(kind, kind)}")
    errors = store.read_errors(days=7)
    if errors:
        lines.append(f"model call failures, last 7 days: {len(errors)}; latest: {errors[-1]['error']}")
    return "\n".join(lines)


def run_scan(providers: list[str], since: float = 0, assume_yes: bool = False, default_yes: bool = False) -> int:
    """Count, ask once, analyze. Prompts without candidates are logged without asking:
    that costs nothing. Without an interactive terminal the model calls are skipped."""
    plan = scan.build_plan(providers, since)
    print(scan.summary(plan))
    if not plan.events and not plan.candidates:
        return 0
    if plan.candidates and not assume_yes:
        if not shutil.which("claude"):
            print("`claude` is not on PATH, so corrections cannot be analyzed yet. Run `python3 -m coach scan` later.")
            return 1
        hint = "[Y/n]" if default_yes else "[y/N]"
        try:
            answer = input(f"Analyze {len(plan.candidates)} corrections with Sonnet on your Claude limit? {hint} ").strip().lower()
        except EOFError:
            answer = "n"
        if not answer and default_yes:
            answer = "y"
        if answer not in ("y", "yes", "д", "да"):
            print("skipped, nothing written. Run `python3 -m coach scan` any time.")
            return 1
    total = len(plan.candidates)

    def progress(done: int) -> None:
        print(f"\r  analyzed {done}/{total}", end="" if done < total else "\n", flush=True)

    result = scan.run(plan, progress=progress if total else None)
    print(scan.report(result))
    print("\n" + memo.next_steps())
    return 1 if result.errors and not result.lessons else 0


def scan_cmd(args) -> int:
    providers = list(PROVIDERS) if args.provider == "all" else [args.provider]
    since = time.time() - args.days * 86400 if args.days else 0
    if args.dry_run:
        print(scan.summary(scan.build_plan(providers, since)))
        return 0
    return run_scan(providers, since, assume_yes=args.yes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coach")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--settings", type=Path, default=Path("~/.claude/settings.json").expanduser())
    sub.choices["install"].add_argument("--no-scan", action="store_true", help="do not offer to scan history")
    sub.choices["install"].add_argument("--no-codex", action="store_true", help="do not add hooks to Codex")
    sub.add_parser("codex-install", help="add live hooks to Codex")
    sub.add_parser("codex-uninstall", help="remove the hooks from Codex")
    sub.add_parser("check").add_argument("prompt")
    sub.add_parser("mute").add_argument("rule_id")
    sub.add_parser("unmute").add_argument("rule_id")
    sub.add_parser("status")
    sub.add_parser("help", help="what the coach does and its commands")
    p = sub.add_parser("scan", help="analyze past sessions of Claude Code and Codex")
    p.add_argument("--provider", choices=["all", *PROVIDERS], default="all")
    p.add_argument("--days", type=int, default=None, help="only sessions from the last N days")
    p.add_argument("--dry-run", action="store_true", help="count only, no model calls")
    p.add_argument("--yes", action="store_true", help="do not ask before the model calls")
    args = parser.parse_args(argv)

    if args.cmd == "install":
        print(install(args.settings))
        store.remember_root(REPO)
        if not args.no_codex and codex_install.codex_home().exists():
            print(codex_install.install())
        if not args.no_scan:
            print("\nLooking for your past sessions in Claude Code and Codex…")
            run_scan(list(PROVIDERS), default_yes=True)
        scanned = any(e.get("source") == "scan" for e in store.read_events())
        print("\n" + memo.welcome(scanned))
        print("\nОткрой новую сессию Claude Code, и коуч заработает.")
    elif args.cmd == "uninstall":
        print(uninstall(args.settings))
        print(codex_install.uninstall())
    elif args.cmd == "codex-install":
        print(codex_install.install())
    elif args.cmd == "codex-uninstall":
        print(codex_install.uninstall())
    elif args.cmd == "check":
        print(check(args.prompt))
    elif args.cmd in ("mute", "unmute"):
        muted = store.load_muted()
        (muted.add if args.cmd == "mute" else muted.discard)(args.rule_id)
        store.save_muted(muted)
        print(f"muted: {', '.join(sorted(muted)) or 'none'}")
    elif args.cmd == "status":
        print(status())
    elif args.cmd == "help":
        scanned = any(e.get("source") == "scan" for e in store.read_events())
        print(memo.welcome(scanned))
    elif args.cmd == "scan":
        return scan_cmd(args)
    return 0
