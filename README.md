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
heuristics and can be noisy, so they retire themselves. After a hint has fired 30
times, the coach checks whether a confirmed correction followed those prompts at least
1.5× more often than it follows your prompts in general. If not, the hint goes quiet.
A retired hint is still evaluated in the background, so it comes back if it starts to
predict corrections. `python3 -m coach status` shows the verdict for each hint.

The idea comes from *Coding Agents are Strong Prompt Optimizers*
([arXiv:2609.26261](https://arxiv.org/abs/2609.26261)). There, a coding agent reads a
corpus of past trajectories and writes evidence-backed rules. prompt-coach applies the
same idea to a human's own sessions.

> The interface language (hints and lessons) is currently **Russian**.

## Requirements

- Claude Code, logged in with a subscription or an API key.
- Python 3.9+, standard library only.
- Optional: Codex CLI. Your Codex history is scanned too, and lessons can appear live in Codex.
- Linux and macOS are tested. Windows: version 0.4.2 fixes the cp1251 encoding failures a
  Windows user hit in the scan; the live hooks have not been confirmed there yet.

## Install: Claude Code plugin (recommended)

Inside a Claude Code chat, run these two commands one after the other:

```
/plugin marketplace add Balbachan420/prompt-coach
/plugin install prompt-coach@prompt-coach
```

The second command opens the plugin's card. Choose **Install**, for yourself (user
scope).

Or, in a terminal, run one command, which installs right away:

```bash
claude plugin install prompt-coach --marketplace Balbachan420/prompt-coach
```

The plugin brings its own hooks, so `settings.json` is not edited, and updates arrive
through `/plugin`. In your next session the coach offers once to analyze your history.
The commands are:

- `/prompt-coach:scan`: analyze past Claude Code and Codex sessions (asks before calling the model)
- `/prompt-coach:status`: lessons by type, and each hint's auto-retire verdict
- `/prompt-coach:codex`: turn on live lessons in Codex too
- `/prompt-coach:help`: show this list again

Your first session after install opens with a short memo that lists these commands.

## Install: from a terminal

```bash
git clone https://github.com/Balbachan420/prompt-coach.git ~/prompt-coach
cd ~/prompt-coach
python3 -m coach install
```

This adds two hooks (`UserPromptSubmit` and `Stop`) to `~/.claude/settings.json`,
backs up the previous file next to it, and leaves your other hooks untouched. If Codex
is installed, the same hooks are added to it (`--no-codex` skips that). Then the
coach finds your past sessions, shows how many correction candidates they hold, and
asks once: press Enter and Sonnet analyzes them, then prints your corrections by
type with examples. `--no-scan` skips the offer. Open a **new** Claude Code session
afterwards.

Pick one install method. Using both runs every hook twice.

## Codex

Live lessons in Codex use Codex's own `UserPromptSubmit` and `Stop` hooks. They go
into `~/.codex/hooks.json`, or into `~/.codex/config.toml` if your hooks already live
there. **Codex runs a new hook only after you trust it.** Open Codex, run `/hooks`,
and trust the two prompt-coach hooks. The coach never does this for you. To remove
them, run `prompt-coach codex-uninstall`.

## Use

There is nothing to do: work as usual. To check on the coach:

```bash
python3 -m coach status            # hints fired, corrections analyzed, lessons by type
python3 -m coach check "текст"     # what the keyword hints say about a prompt
python3 -m coach mute R6           # silence one keyword hint (unmute to restore)
python3 -m coach uninstall         # remove the hooks
```

## Scan your history (Claude Code + Codex)

The hooks only see sessions from the moment you install the coach. To learn from
what came before, scan your past sessions in Claude Code (`~/.claude/projects`) and
Codex (`~/.codex/sessions`):

```bash
python3 -m coach scan --dry-run          # count sessions, prompts and correction candidates
python3 -m coach scan                    # analyze candidates with Sonnet (asks first)
python3 -m coach scan --provider codex --days 30
```

The scan prints your corrections by type and provider, with examples. It also gives
the keyword hints their auto-retire verdicts straight away. Programmatic runs
(`claude -p`, `codex exec`) are skipped. Sessions already scanned or seen live are
skipped too, so re-running is safe. Live lessons inside Codex need the Codex hooks above.

## Cost and privacy

- The model is called **only on candidate corrections**: a few per day for an active
  user. By default this is `claude -p --model sonnet`, which runs on your own Claude
  subscription limit (or API key). The command can be changed with
  `PROMPT_COACH_LLM_CMD`, but Sonnet is the only model the coach has been validated on.
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
