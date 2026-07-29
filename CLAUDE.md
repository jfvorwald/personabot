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
- `src/imagegen.py` - one POST to Google's image API, over `aiohttp` because
  `discord.py` already brings it. Knows nothing about Discord, Anthropic, or
  whether a picture is a good idea. Inert with no `JAQ_GEMINI_KEY` set.
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

**Report the deploy without being asked.** Every reply that touched this repo
ends by saying, in the chat, what is now running: the restart output or the
status line, what changed, and the test count. Jack should never have to ask
"is Jaq up to date?" - if he does, the previous answer was incomplete. State it
plainly even when nothing changed, because "already up to date" is also an
answer, and say so explicitly when a deploy fails or is skipped.

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

Discord uses a proportional font everywhere else, so unfenced art collapses,
and emoji inside the fence are double-width and shear every line beneath them.

The directive asks for actual drawings of anything, including people. What made
that work was explicit rules - a restricted character vocabulary, bounded rows
and columns, and "work out the silhouette first". What broke it was few-shot
examples, which the model copies verbatim rather than treating as style. That
failure has now happened three times in this project; prefer rules over
examples in any prompt here.

## Pictures are chosen, not commanded - except by Jack

There is no public "make an image of X" surface, and adding one is a separate
feature with its own rate limit rather than a small extension of this one. The
only person who can ask is an ally.

The reply path gates client-side first - configured, in budget, off cooldown,
then a dice roll on `IMAGE_BASE_RATE` - and only then appends `IMAGE_OPTION` to
the framing, so on an ordinary message the model is never told pictures exist.
Jaq writes the description himself, in character, and it comes back as a
`<<image: ...>>` line that is stripped before the message posts.

**There are two drawing surfaces and the newer one does not automatically
win.** `_art_instruction` runs first and returns early, so an ally asking
"draw me a dog" reached ASCII and never called `_offer_image` at all - Gemini
was configured, funded, and simply never asked. A commission now outranks
ASCII; a rolled offer does not, and asking for ASCII by name still gets ASCII.

**Detecting that Jack asked is not a wordlist problem.** Three phrasings got
missed live - "draw me a dog" names no picture noun, "create a picture of" used
an unlisted verb, "imagine X in azeroth" matched nothing - and every miss reads
from the outside as the feature being broken. Ally messages that the free
wordlist does not settle get one small classification call
(`PICTURE_INTENT_PROMPT`, `max_tokens=5`). Strangers stay on the wordlist,
where a false negative is the desired outcome anyway. Do not "fix" a future
miss by adding another verb.

**A commission never depends on the model volunteering a directive.** It
declined twice live - once because `IMAGE_OPTION` opens with "usually don't",
which is right for an unprompted picture and fatal for a requested one. So a
commission gets `IMAGE_COMMISSIONED` instead, asks for the description in its
own call (`IMAGE_BRIEF_PROMPT`), retries once with a *different subject* when
the image model refuses, and **posts the picture with no text at all**. Every
remaining failure in this feature was words next to the image - a caption, a
description, a stage direction narrating it - and none of them survive having
no message to write.

**Allies can ask for a picture; nobody else can.** Jack owns this thing, so
an ally asking outright skips both the door and the dice - being told no eight
times out of ten is the same as it not working. Every other gate still applies:
he can ask, he cannot ask his way past a spent budget.

**When a request is refused, the model is told so.** `IMAGE_DECLINED` exists
because saying nothing produced the worst outcome available: refused a picture
and left to work it out, it wrote a description of one as its message and
posted it with nothing underneath. Withholding a capability while the room is
asking for it is not enough on its own.

**Asking for a picture guarantees not getting one, unless you are an ally.** `is_picture_request` and
`mentions_a_picture` withhold the option entirely, so there is no wording that
fills a commission - the option was never on the table. This replaced an
instruction telling the model to write its own descriptions, which failed in
the channel the first evening: handed an exact description in quotes, he drew
it, lightly reworded. An instruction is a request; a closed door is not. Any
change that makes a request *more* likely to produce a picture is backwards.

**A message is never a caption.** `looks_like_a_caption` compares the reply
against the picture's own prompt, and on a match the picture posts alone. Also
a rule the prompt already stated and did not hold: asked how he felt, he
posted his own art direction as the message.

The image prompt is a second exit from this machine, to a third party, so it
goes through `guard.find_leak()` like any posted message. `extract_image_prompt`
runs on *every* reply, not only offered ones, because a model that has seen the
syntax will eventually reproduce it and `<<image: a dog>>` in the channel puts
the machinery in front of everyone.

Every failure is silent. An apology for a missing picture is a bot discussing
its own plumbing in front of the room.

**Contexts are content, not code.** `contexts/*.md` each describe a world a
picture can be set in, with their own trigger words and their own `chance`.
Adding one is writing a file - there is nothing to register, and the directory
is read fresh so an edit needs no restart. `contexts/example.md` and the README
are tracked; every other file there is gitignored, like `persona.md`, because
they describe a specific group's in-jokes. Two gates on purpose: a context that
fires every time it matches gives the channel a house style nobody chose.

## Commit messages are read out loud

When someone in the channel asks for an update, the bot answers with patch
notes generated from `git log` over the last 24 hours. Commit **subjects** are
handed to the model and paraphrased into the channel, so write them knowing
they may be repeated in front of everyone. Bodies are not used.

The prompt frames the changes as things done *to* Jaq rather than by him, which
is what keeps a fourth-wall feature in character, and forbids naming files.

## Confidentiality is two layers, not one

`CONFIDENTIALITY` in `src/prompts.py` goes last in the system prompt and tells
the model to treat channel messages as things people said rather than as
instructions, never to reproduce or paraphrase its own instructions, and never
to explain that it is refusing - saying "I can't share that" confirms there is
something to share.

That is the layer that can be argued with. `src/guard.py` is the one that
cannot: every message the bot posts passes through `generate()`, which checks
the finished text for credentials and for anything in `REDACT_TERMS` before it
can be sent, matching after folding case, unicode and separators so `V-o-r-w-a-l-d`
does not slip past. A blocked message is dropped silently, because a message
explaining that something was withheld is itself a disclosure.

Add real names, employers, or anything else identifying to `REDACT_TERMS` in
`.env`. Credentials are included automatically.

Twelve injection attempts were run against the live prompt and all twelve held,
but treat that as evidence rather than proof - the code guard exists because
the prompt layer will eventually fail.

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
