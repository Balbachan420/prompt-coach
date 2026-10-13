---
description: Analyze your past Claude Code and Codex sessions and show what your corrections are about
allowed-tools: Bash(prompt-coach:*)
---
Run `prompt-coach scan --dry-run` and show the user the counts it prints.

If it finds correction candidates, tell the user that the analysis calls Sonnet once per candidate on their own Claude limit, and ask whether to start. Do not start without a yes.

On yes, run `prompt-coach scan --yes` in the background, because a large history can take 10–20 minutes. When it finishes, show its report as it is. Then add one short line on what the most frequent correction type means for how they write prompts.

If the report starts with `FAILED`, quote the reasons and do not guess beyond them. If they point to the command sandbox (network blocked, read-only file system, permission denied under `~/.claude`), tell the user that, and with their consent run `prompt-coach scan --yes` again with the sandbox disabled for that one command. Failed candidates are retried automatically.

Reply in the user's language.
