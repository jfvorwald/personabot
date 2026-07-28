# personabot

## What this is

A Discord bot that plays a persona ("Jaq") in a private friend server, talking
to a second persona bot run by a friend. Python, `discord.py` + `anthropic`.
No framework, no database, no build step.

**The design goal is that it reads as a person rather than a request handler.**
Almost every mechanism in `bot.py` exists to serve that: it declines most
messages, hangs back before joining a conversation someone else started, waits
out bursts, types at human speed, and reacts instead of replying. When changing
behaviour, the question to ask is whether it becomes more or less
person-shaped - not whether it's faster or answers more.

- `bot.py` - the bot. Three modes: `--now`, `--live`, scheduled (no flag).
- `brain.py` - what Jaq knows about the people in the channel. Module + CLI.
- `persona.md` - who Jaq is, dropped into the system prompt verbatim. Untracked.
- `psychology.md` - how conversation works. A separate prompt block on
  purpose, so the two stay independently editable.
- `restart.sh` - deploy / status / stop / logs for the live process.

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
disk on every reply and take effect immediately. Everything else - `bot.py`,
`brain.py`, `persona.md`, `psychology.md`, `.env` - needs the restart.

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
`.venv/bin/python doctor.py` checks each layer in order - env vars, Anthropic
round-trip, Discord login, channel access - and stops at the first failure.
`bot.py --now` posts one real message and exits.

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
