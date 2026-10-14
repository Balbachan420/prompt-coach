# Roadmap

## Next: an on-demand prompt reviewer (agent inside the plugin)

**Status:** to be worked out, not started. Recorded 2026-10-14.

### Why

The plugin stays as it is: hooks are the only way to watch prompts and deliver a
lesson without the user doing anything, and they also work in Codex. A Claude Code
subagent cannot replace them, since it runs only when called and never sees the
user's prompts. But an agent fits as an addition: a command the user calls
deliberately before a big task.

### Shape

- A command such as `/prompt-coach:review <draft prompt>`, backed by an agent
  shipped in the plugin (`agents/`).
- It reads the current session and the user's profile from the scan (top
  correction types with real examples from `lessons.jsonl`) and answers: what is
  missing (goal, context, earlier decision, format), plus a rewritten prompt.
- This is the manual version of the real-time judge below. It needs no ceiling
  measurement: the user calls it when in doubt, so false alarms do not annoy.

### Open questions

- Command plus a plugin agent, or a skill only? Which needs less setup and works
  without the plugin (terminal install)?
- How much of the session to read, and how to point the agent at it.
- Codex equivalent (no plugin agents there): a terminal command
  `python3 -m coach review`?
- How to measure usefulness: does a reviewed prompt lead to fewer corrections?

## Then: judge the prompt itself in real time, before any correction

**Status:** research, not started. Recorded 2026-10-13.

### Why

Today the coach teaches only *after* the user corrects the agent. Everything the
history scan learns (for example, "most of your corrections are about a missing goal
or output format") stays unused until the next correction. The goal is to flag a
weak prompt at the moment it is sent, before the agent goes the wrong way.

### What we already know

- **Keyword rules do not work.** On the author's 2,109 prompts (Claude Code +
  Codex), all six keyword hints fired with a correction rate equal to the base rate
  (3–5% against 4%). Five of them auto-retired. Wording does not reveal what is
  missing: "посмотри что в папке" is fine mid-session and "разбери atom_v2.json" is
  not, yet the two look the same.
- **What makes a prompt weak is missing context**: the goal, a fact only the user
  knows, an earlier decision, or a deictic reference ("тут", "как в прошлый раз")
  with nothing to point at. Seeing that requires the session context, not just the
  prompt text.
- **A labeled dataset exists.** `coach scan` produced per-prompt outcomes: 81
  prompt-caused corrections, each with a type, the corrected prompt, and "what was
  missing". `events.jsonl` links every prompt (by hash) to whether a correction came
  next.

### Question to answer first

**Is a correction predictable from the prompt plus the context before it?** Measure
a ceiling before building anything.

Experiment: for each labeled prompt, give Sonnet *only* the session up to and
including that prompt, never what followed. Ask: "Will the agent likely
misunderstand this? If so, what is missing?" Compare with the labels.

- Metric: correction rate among flagged prompts against the base rate (lift), with
  the alert rate capped at about 5%. Also check whether the predicted "missing"
  agrees with the scan's "missing".
- Split by time: tune on older sessions, test on newer ones.
- Read 20 flags by hand: is the flag useful, not just correct?
- If the lift is below about 2× even for Sonnet with full context, real-time
  prompt judging is not worth building. Stop and move to the tip-at-session-start
  path instead.

### Candidate designs, if the ceiling is good

1. **LLM judge on submit.** Sonnet reads the prompt, the recent turns and the user's
   personal profile (their top correction types with examples). Most precise. Cost:
   a few seconds per prompt. Variant: run it non-blocking and show the hint while the
   agent is already working ("you may want to stop and add X").
2. **Learned scorer.** Embed the prompt and the recent context, then train a small
   classifier on the scan labels. Runs in milliseconds and locally. Risk: few
   positives (around 80 per user), so it may need pooling across users or an
   LLM-labeled augmentation.
3. **Context-gap checks.** Deterministic checks against the session state: a deictic
   reference with no antecedent, a new task with no goal sentence when the session
   has none either, or a reference to a decision missing from the visible context.
   Cheap, explainable, and probably high precision on a narrow slice.
4. **Two stages.** (2) or (3) filters cheaply, and (1) runs only on high-risk prompts.
   Most likely the final shape: precision of the LLM at the cost of the filter.

### Constraints

- Never block or noticeably delay a prompt by default. A blocking mode is opt-in.
- Provider-agnostic: Claude Code and Codex share the hook shape (`UserPromptSubmit`).
- Sonnet is the only validated model.
- Privacy is unchanged: prompt text stays local, and only the user's own model sees it.

## Later

- A tip at session start: one line a day from the user's most frequent correction
  type, with a real before/after example from their history.
- An optional note for the agent: add the user's top gaps to the agent's
  instructions ("ask one short question when the goal or format is missing").
- Cursor and ZCode history readers.
- Windows support.
