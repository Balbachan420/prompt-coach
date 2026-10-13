"""The user-facing memo: what the coach does and which commands to use.

Shown once on the first plugin session, at the end of a terminal install, after
a scan ("what next") and on demand through `help`. Plugin users get slash
commands; terminal users get `python3 -m coach …`.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

COMMANDS = [
    ("scan", "разобрать прошлую историю Claude Code и Codex: из-за чего ты чаще всего поправляешь агента (один раз, спросит перед запуском)"),
    ("status", "твоя статистика: поправки по типам и какие подсказки работают"),
    ("codex", "включить уроки и в Codex"),
    ("help", "показать эту памятку снова"),
]
TERMINAL = {"codex": "codex-install"}


def is_plugin() -> bool:
    """Plugin installs live in Claude Code's plugin cache."""
    return "/plugins/cache/" in REPO.as_posix()


def command(name: str, plugin: bool | None = None) -> str:
    plugin = is_plugin() if plugin is None else plugin
    return f"/prompt-coach:{name}" if plugin else f"python3 -m coach {TERMINAL.get(name, name)}"


def _command_lines(plugin: bool) -> list[str]:
    width = max(len(command(n, plugin)) for n, _ in COMMANDS)
    return [f"  {command(n, plugin):<{width}}  {text}" for n, text in COMMANDS]


def welcome(scanned: bool, plugin: bool | None = None) -> str:
    plugin = is_plugin() if plugin is None else plugin
    lines = [
        "💡 Prompt Coach установлен.",
        "Что он делает: когда ты поправляешь агента («нет, не так», «мы же решили»), коуч разбирает,",
        "чего не хватило в твоём промпте, и после ответа агента показывает урок: что упустил и как можно было написать.",
        "",
        "Команды:",
        *_command_lines(plugin),
    ]
    if not scanned:
        lines += ["", f"Начни с {command('scan', plugin)}: сразу увидишь свою картину ошибок."]
    if not plugin:
        lines.append("Команды запускаются из папки коуча (cd ~/prompt-coach).")
    return "\n".join(lines)


def next_steps(plugin: bool | None = None) -> str:
    plugin = is_plugin() if plugin is None else plugin
    return "\n".join(
        [
            "Что дальше:",
            "  Работай как обычно. Когда поправишь агента, после его ответа появится урок.",
            f"  Прогресс и статистика: {command('status', plugin)}",
            f"  Если работаешь и в Codex: {command('codex', plugin)}",
        ]
    )
