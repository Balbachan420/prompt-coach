# prompt-coach

A coach for your own prompting. It sits next to a coding agent, checks every prompt
you send against your personal weak patterns, and shows a one-line hint when the
prompt matches one. v0 supports Claude Code only, through a `UserPromptSubmit` hook.

## Layout

- `coach/checks.py`: the rule engine, which is pure and makes no I/O or LLM calls.
- `coach/default_checks.json`: generic rules that ship with the repo. Never put a
  user's personal evidence here.
- `~/.prompt-coach/checks.json`: personal rules for the same ids. They override the
  defaults and carry the user's evidence ("27 of your 57 corrections").
- `coach/hook.py`: the entry point for both hooks. It reads hook JSON on stdin and
  writes `{"systemMessage": ...}`. On `UserPromptSubmit` it shows keyword hints and,
  if the prompt looks like a correction, starts `coach/analyze.py` detached. On
  `Stop` it delivers the pending lesson. It must never block or break a prompt, so
  every error ends in a silent exit 0.
- `coach/session.py`: turns a transcript into a human/agent dialogue, with tool
  output collapsed to tool names.
- `coach/correction.py`: the candidate regex, the reviewer prompt and the call to the
  model CLI (`PROMPT_COACH_LLM_CMD`, default `claude -p --model sonnet`). The child
  process gets `PROMPT_COACH_INNER=1`, so its own hooks skip it.
- `coach/cli.py`: `python3 -m coach install|uninstall|check|mute|unmute|status`.

## Rules

- Prompt text never leaves the machine and is never written to disk. The event log
  stores only a hash, the length and the ids of the rules that fired.
- At most one hint is shown per prompt. A good prompt gets silence.
- No absolute paths in the repo. `PROMPT_COACH_HOME` overrides `~/.prompt-coach`.

## Verification

```bash
python3 -m pytest -q
```
