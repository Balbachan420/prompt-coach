"""Force UTF-8 on the standard streams.

On Windows, Python reads and writes pipes and the console in the ANSI code page
(cp1251 on a Russian system). Hook JSON from Claude Code and Codex is UTF-8, and
hints carry "💡", "→", "−". Without this, a hook decodes its input as mojibake and
crashes on printing, and the crash is swallowed. The user sees nothing.
"""

from __future__ import annotations

import sys


def force_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
