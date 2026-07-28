# personabot

## What this is

A Discord bot that plays a persona ("Jaq") in a private friend server, talking
to a second persona bot run by a friend. Python, `discord.py` + `anthropic`.
No framework, no database, no build step.

**The design goal is that it reads as a person rather than a request handler.**
Almost every mechanism in `src/bot.py` exists to serve that: it declines most
messages, hangs back before joining a conversation someone else started, waits
out bursts, types at human speed, and reacts instead of replying. When changing
behaviour, the question to ask is whether it becomes more or less
person-shaped - not whether it's faster or answers more.

```
src/       the bot's modules; run as `.venv/bin/python src/bot.py`
tools/     standalone operator scripts, never imported by the bot
tests/     the suite the deploy gate runs
brain/     profile data (contents gitignored)
```

- `src/bot.py` - the Discord client and the orchestration. Three modes:
  `--now`, `--live`, scheduled (no flag).
- `src/config.py` - every setting, read from the environment in one place.
- `src/decide.py` - whether to speak and whether to wait, as pure functions.
  **Imports no Discord, on purpose** - that is what makes it testable.
- `src/react.py` - reaction budget and emote selection.
- `src/prompts.py` - every fixed string the model is shown.
- `src/persona.py` - loads `persona.md`, `psychology.md`, and the post schedule.
- `src/brain.py` - what Jaq knows about the people here. Module + CLI.
- `src/changelog.py` - reads the git log for patch notes.
- Polls are native Discord polls (`discord.Poll`), needing the `send_polls`
  permission. Its own position is always the first option, which is how
  the bot knows later whether it lost.
- `src/paths.py` - where the repo root is. The only place that is written down.
- `tools/doctor.py`, `tools/setup_env.py` - run by a human, never imported.
- `persona.md` / `psychology.md` - content, at the root where you edit them.
  `persona.md` is untracked.
- `VOCAB` in `.env` - words to keep in rotation. Lives in config rather than
  the persona because it changes far more often than the character does.

Read `README.md` for the modes and the full config surface,
`brain/README.md` for the brain's architecture and the hand-written
marker, and `FUTURE.md` for the ranked roadmap of what's next.

## Working here

**Always `.venv/bin/python`, never bare `python`.** The dependencies are not
installed system-wide.

### Restart the bot. Every time. No exceptions.

**Every interaction that touches this repo ends with `./restart.sh`** - and
with its output shown, so the running process is never left behind what is on
disk. This is not a step to remember at the end; it is part of the change.

```bash
./restart.sh
```

If nothing was edited, run `./restart.sh status` instead and report it. Never
answer "is it live?" from memory - the status output compares file mtimes
against the process start time and answers it for real.

`./restart.sh` syntax-checks, runs the tests, refuses to deploy if either
fails, waits for the old process to actually exit, and prints the live config.
It is the verification, not just the deploy.

The one exception: `brain/people/*.md` and `brain/_index.json` are re-read from
disk on every reply and take effect immediately. Everything else - anything in `src/`, `persona.md`, `psychology.md`, `.env` - needs the restart.

Restarting is cheap and safe by design: the day's reply and reaction spend is
persisted to `.bot_state.json` and restored on connect, so deploying does not
hand the bot a fresh budget. `live.log` appends across restarts rather than
being truncated.

**Every change runs or updates the tests.** `./restart.sh` refuses to deploy
on a failing suite, and runs them before stopping the old process, so a red
suite can't take the bot down. `SKIP_TESTS=1 ./restart.sh` is the escape hatch.

```bash
.venv/bin/pytest tests/ -q
```

The suite is hermetic - no network, and it deliberately ignores the real `.env`
so it asserts against documented defaults rather than this machine's config.

**Verify against Discord, not just against the parser.**
`.venv/bin/python tools/doctor.py` checks each layer in order - env vars, Anthropic
round-trip, Discord login, channel access - and stops at the first failure.
`bot.py --now` posts one real message and exits.

## ASCII art only renders inside a code fence

Discord uses a proportional font everywhere else, so unfenced art collapses.
Emoji inside the fence are double-width and shear every line beneath them.
Testing showed the model handles row-based forms well - bar charts,
flowcharts, decision tables - and reliably misses by a character on anything
needing closed borders, so `src/prompts.py` steers toward the former.

## Commit messages are read out loud

When someone in the channel asks for an update, the bot answers with patch
notes generated from `git log` over the last 24 hours. Commit **subjects** are
handed to the model and paraphrased into the channel, so write them knowing
they may be repeated in front of everyone. Bodies are not used.

The prompt frames the changes as things done *to* Jaq rather than by him, which
is what keeps a fourth-wall feature in character, and forbids naming files.

## Never use an em dash

Not in code, comments, docs, commit messages, prompts, or replies. Use a hyphen.
This is absolute.

It matters twice over here: it is Jack's standing preference for everything
written, and an em dash in `persona.md`, `psychology.md`, or `src/prompts.py` is
worse than a style violation - those files are the model's context, so every
one in them teaches the bot the habit, and an em dash in a Discord message is
the most recognisable machine tell there is.

## Never commit

`.env`, `persona.md`, `brain/people/`, and `brain/_index.json` are gitignored
and must stay that way. They hold API keys and notes about real people, and
this repo is public. Check `git diff --cached --name-only` before committing.

## The privacy rule

`persona.md` carries hard limits: no real names, employer, city, family
members, or the pregnancy. **Brain profiles are bound by the same limits**,
because they are assembled into the same system prompt.

This has already failed once. An excluded account was profiled anyway after its
Discord display name changed, and the generated profile captured a partner's
name, a child's name, and an employer. Exclusion is keyed on Discord **user
ID** for exactly that reason - never re-key it on display name, and never
assume a name-based match is sufficient.
