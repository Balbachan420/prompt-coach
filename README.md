# prompt-coach

A coach for your own prompting in **Claude Code**. It runs next to your sessions
and teaches at the moment you correct the agent.

When you write something like *"нет, не так"* / *"that's not what I meant"*, the coach
reads the current session in the background. It decides whether this really is a
correction, and if your earlier prompt caused it, it shows a short lesson once the
agent has replied:

```
💡 coach · поправка: цель, объём или формат — 3-я такая за 30 дней
   Промпт: «какие сценарии собрали больше всего просмотров?»
   Не хватало: реальная цель — отсеять сценарии, которые работают у многих блогеров
   Можно было: «Мне нужно отсеять сценарии, которые набирают просмотры у многих блогеров…»
```

If the agent simply made a mistake on a clear prompt, you get no lesson; it is only
logged. Your prompt is never delayed or blocked.

The coach also has a few keyword hints that fire as you submit (a bare file path, a
destructive action with no "ask me first", the same prompt sent twice). These are
heuristics and can be noisy, so mute any that do not help you.

The idea comes from *Coding Agents are Strong Prompt Optimizers*
([arXiv:2609.26261](https://arxiv.org/abs/2609.26261)). There, a coding agent reads a
corpus of past trajectories and writes evidence-backed rules. prompt-coach applies the
same idea to a human's own sessions.

> The interface language (hints and lessons) is currently **Russian**.

## Requirements

- Claude Code, logged in with a subscription or an API key. `claude` must be on your PATH.
- Python 3.9+, standard library only.
- Linux or macOS. Windows is untested.

## Install

```bash
git clone https://github.com/Balbachan420/prompt-coach.git ~/prompt-coach
cd ~/prompt-coach
python3 -m coach install
```

This adds two hooks (`UserPromptSubmit` and `Stop`) to `~/.claude/settings.json`,
backs up the previous file next to it, and leaves your other hooks untouched. Open a
**new** Claude Code session afterwards.

## Use

There is nothing to do: work as usual. To check on the coach:

```bash
python3 -m coach status            # hints fired, corrections analyzed, lessons by type
python3 -m coach check "текст"     # what the keyword hints say about a prompt
python3 -m coach mute R6           # silence one keyword hint (unmute to restore)
python3 -m coach uninstall         # remove the hooks
```

## Cost and privacy

- The model is called **only on candidate corrections**: a few per day for an active
  user. By default this is `claude -p --model sonnet`, which runs on your own Claude
  subscription limit (or API key). To use another model, set
  `PROMPT_COACH_LLM_CMD`, for example `claude -p --model haiku`.
- What the model receives: the opening prompt of the session, the last ~8 turns
  (long tool output collapsed to tool names) and your correction. It goes to the same
  Claude you are already working with, and nowhere else.
- Local state lives in `~/.prompt-coach/` (override with `PROMPT_COACH_HOME`):
  - `events.jsonl`: a hash and the length of each prompt, plus which hints fired.
    It never stores prompt text.
  - `lessons.jsonl`: the lessons, which include a short paraphrase of the corrected
    prompt.
  - `checks.json` (optional): your personal overrides for the keyword hints.

## How well does it work

These are the author's own numbers, from 65 sessions and 845 prompts:

- The keyword filter catches about 70% of real corrections. Corrections written
  without typical words ("не так", "мы же решили", "опять"…) are missed.
- Sonnet confirmed 34 of the 40 labeled corrections it was shown. It also found 16
  more that the manual labeling had missed. It marked 12 as the agent's fault, with
  no lesson.
- The keyword hints on their own did **not** predict corrections: the correction rate
  after a hint was about the same as the base rate. That is why the lesson-at-correction
  path is the main one.

## Develop

```bash
python3 -m pytest -q
```

## License

MIT
