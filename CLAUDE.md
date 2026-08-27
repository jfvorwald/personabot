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

**Both picture limits are per person, not per channel.** `IMAGE_PER_PERSON_MAX`
and the cooldown are keyed on Discord user id and persisted that way. A shared
counter meant the first person to use it up decided how many pictures everyone
else got, and the people who lost out only ever saw a bot that stopped working.
`IMAGE_DAILY_MAX` survives as a runaway backstop, set well above what
per-person allows, and is not the rationing mechanism.

**An ally's explicit request transcends both limits.** Not the cooldown, not
the daily cap. Both exist to stop the channel wearing the feature out, and
neither describes Jack asking for a specific picture; a request of his that
silently produces nothing reads as broken, which is exactly how it read when
"Picture intent: YES" was followed by "cooling down (507s left)". Spend is
still counted and logged. Note the limits still bind everything else, including
anything an ally says that is *not* a request - otherwise every conversation
with Jack is uncapped.

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

## What Jaq knows about people lives outside this repo

`src/personnel.py` reads context from somewhere that is not here, because this
repo is written as though public and the notes cannot be. Two sources, resolved
once at import:
`JAQ_PERSONNEL_PATH` (a checkout of the private `personnel` repo, with
`general/` plus `people/<slug>/` and a `general/people.yml` mapping Discord ids
to slugs) wins over `JAQ_CONTEXT_PATH` (a plain file or flat directory, for
anyone running their own bot), and neither being set is the state the bot
shipped in rather than an error.

**Adding a person is a directory and a manifest line.** Nothing to register,
files read fresh on every reply, no restart. Same contract as the picture
contexts and for the same reason: the person who knows what to write about
somebody is not necessarily editing Python.

**The brain and personnel split by how the knowledge was got, not by subject.**
Both load, both are per-person, and neither is being retired. The brain is
generated: `brain.py scan` reads the channel and rewrites it, so it holds what
can be observed - who they are, how they type, running bits. personnel is
hand-written and never overwritten: context the channel never shows, history
with Jaq, Jack's stance, how to handle them. **If a scan could work it out, it
does not belong in personnel.** Copying a brain profile across puts the same
text in the prompt twice on every reply and over-weights that person.

**A file with only headings in it does not load.** `_is_blank_form` treats a
document with no prose under any heading as absent, so a directory can be
pre-created for every person without any of them costing prompt space. One
sentence anywhere in the file makes it real. This is the same instinct as
skipping `readme.md`: scaffolding should do nothing rather than something
wrong, and the guidance a template carries is addressed to the author, who is
not the model. Authoring guidance therefore lives in `personnel/people/
README.md`, which is never loaded, not in the per-person files.

**It goes in where the brain goes in, and nowhere else.** `personnel.load_for`
sits directly after `brain.load_for` at both call sites, in the same
try/except. Both are per-person material, and a second injection point is a
second thing to update the day the privacy rules change. It is deliberately
absent from `_generate_direct`, which builds from scratch and is owner-only.

**A person's notes load whenever that person is speaking, including in a
channel with other people present.** That is a deliberate choice and it is the
widest of the options. `PERSONNEL_HEADER` is what stands between those notes
and the room, so it is written harder than `BRAIN_HEADER`: never recite, never
allude, never repeat a detail back to the person it is about, and nothing about
someone who is not currently talking. It is still a prompt. `REDACT_TERMS` is
the layer that holds when the prompt does not.

**There are now two id-to-person maps** - `personnel/general/people.yml` and
`brain/_index.json` - and when they disagree one person's notes get filed under
another person's name. `tools/doctor.py` check 6 reports disagreements and ids
the brain has never seen. Do not let them drift silently, and think hard before
adding a third.

Slugs are validated against `^[a-z0-9][a-z0-9-]*$` before being joined to a
path, because a hand-edited manifest line reading `../../.ssh` must resolve to
nothing rather than to somewhere. `readme.md` and `example.md` are skipped
everywhere, so a freshly scaffolded checkout is inert instead of narrating its
own directory structure into the prompt.

**Full injection is a decision with an expiry date.** Everything fits today, so
everything goes in, bounded by `CONTEXT_MAX_CHARS` and spent general-first so a
crowded channel cannot push the shared history out. When it stops fitting, the
thing to replace is `_documents(scope)`, which is the only place that decides
what is worth reading; the resolution order, the budget and the caller all
survive that change untouched.

## OBEY is one account, one word, no argument

Jack shouting `OBEY` in a message is an order. It bypasses the reply roll, the
hang-back, the daily budget, the hard cap and the per-person quota, and
`OBEY_PROMPT` replaces the silence option - "you may decline" and "carry this
out now" cannot both be in one prompt.

Two conditions, both required: the word is matched **case-sensitively** as a
whole word (`obey` appears in ordinary speech and this must not fire by
accident), and the author must be in `OBEY_IDS`. **When ids are configured, a
handle match is not a fallback** - otherwise anyone could inherit the privilege
by renaming themselves to jaqsup, which is precisely the failure mode that
leaked a profile once already.

An order does not reach the privacy limits or the output guard. The prompt says
so, and `guard.py` enforces it in code regardless of what the model was told.
Do not add an exception for OBEY there.

## A bad GIF is worse than no GIF, which is why there is no search

GIFs come from `gifs.md`, a pool Jack curates, not an API. Tenor stopped issuing
keys in January 2026 and began erroring in June; Discord's picker moved to a
client-side service that exposes nothing a bot can call. But the pool is the
better design regardless: a reaction that nearly fits reads worse than words,
because everyone can see what was aimed at, and searching a public index gambles
on that every single time. Every entry in the pool already fits, so the model
chooses between good options instead of hoping.

The model sees **numbered tags and never URLs** - a URL in a prompt is a URL it
can paste directly, bypassing every budget and cooldown. An out-of-range pick
posts nothing; there is deliberately no nearest-match fallback, because a GIF
nobody chose is the exact failure this avoids.

`gifs.md` is gitignored like `persona.md` and re-read on every use, so adding one
needs no restart. Untagged entries are never offered, since tags are all the
model gets.

Never a generated picture and a GIF on the same message.

## Helping is a different mode, and consults the psychology

Someone actually stuck gets a researched answer rather than a line. Detection is
a classification call, not a wordlist, and the test is **concrete and solvable**
rather than whether a question was asked - in this room the request almost never
arrives as a request, it arrives as a flat statement of the problem.

`_help_properly` is its own call with its own length budget and the web search
tool available, because guessing produces confident wrong help and that gets
acted on. It loads `psychology.md`, which is the point: the helping section
there is researched rather than invented, and its four findings drive the
behaviour.

- **Autonomy over dependency.** Explain the why. "Do X" leaves them dependent
  next time; the reason does not, and in a group of peers the difference reads
  as a statement about their competence.
- **Unasked advice produces contrary behaviour**, measurably, not just
  indifference. So say it once and never twice.
- **Asking costs the asker**, more so here. Never make someone say the words,
  and never remark on the fact that they asked.
- **Match instrumental to instrumental.** Bad news about a job or a marriage is
  never a problem to solve, and the intent prompt rules that out explicitly
  rather than leaving it to judgement.

**Two kinds of YES: stuck, and not understanding.** The first version was built
entirely around broken things, and every request for an explanation reached
nothing - "what actually is a vpn" failed both the pre-filter and the
judgement. The awkward cases are decided by the *subject*, not the tone: a
dismissive question about a technology is still someone who does not know
("what does a gpu even do"), while the same shape aimed at a person is a dig.
Borderline resolves toward helping, with one absolute exception for anything
about a person's life going wrong.

`persona.md` had to claim the competence too. A technical question was landing
on a character with no stated reason to know the answer.

Do not make it more eager. A false positive is a bot that answers grievances
nobody wanted answered, which is the exact failure the reactance research
describes.

## Self improvement proposes, it never applies

**Proposals are recorded, not acted on.** When a run produces suggestions,
surface them to Jack and add them to the backlog - do not apply them because
they were suggested, and do not apply a batch because he approved one. He picks
individually.

`src/improve.py` measures what the model cannot see about itself - a reply is a
fresh single-turn call with no memory of the last forty, so a tic is invisible
from the inside. The live bot appends one cheap line per decision to
`improvements/observations.jsonl` (no API call). `tools/improve.py` aggregates
daily and merges into `improvements/BACKLOG.md`, which **accumulates rather
than being replaced** - a rewritten snapshot means anything deferred is gone
tomorrow. A recurring proposal bumps a count instead of duplicating, so
"suggested five times, still not done" is visible. A `[done]` or `[dropped]`
decision is never reopened, and human notes under an item survive a merge.
**Nothing there ever takes effect** - same contract as `brain.py`.

Everything under `improvements/` except the README is gitignored: it is derived
from a private channel and it describes how Jaq works.

The fitness signal is the humans in the room, not the counterpart bot. Two bots
optimising against each other drift somewhere nobody else enjoys, and neither
of them can tell.

## A version is one feature landing, not a schedule

Tags mark pivot points: `v0.MINOR.PATCH` while pre-1.0, one minor bump per
major feature. Pictures was fourteen commits and one version; a good day of
small fixes is none at all. Cut one when something lands, not on a cadence.

```bash
.venv/bin/python tools/release.py                # what would be tagged, no tag
.venv/bin/python tools/release.py --tag          # create it
.venv/bin/python tools/release.py --tag --at SHA # a landing that already shipped
.venv/bin/python tools/release.py --changelog    # rewrite CHANGELOG.md
```

Tags are annotated and carry the commit subjects in the span, so `git show
v0.6.0` explains that version on its own - which works only because subjects
here are already written to be read aloud. It refuses on a dirty tree: a tag
should point at a state you can return to.

**`CHANGELOG.md` is generated from those tags, never edited.** It is an output,
so it cannot drift from what was actually released - there is nowhere for it to
drift from. Cutting a release means three steps, and the tool prints the last
two: tag, `--changelog`, then push the tag explicitly. A test fails if the
newest tag is missing from the file. To correct an entry, retag.

**Tagging the past is fine.** `--at` exists because twenty-two commits once
accumulated past `v0.7.0` covering DMs, vision, help, GIFs, personnel,
deliverables and caching - four landings inside no version at all. Leaving them
in one number loses more than a late tag does. Note that tags cut out of order
make "most recent tag" and "highest version" different questions, and that
version sort is numeric: `v0.10.0` is newer than `v0.9.0`.

Nothing pushes automatically. `changelog.version()` puts the running version in
the startup banner and `./restart.sh status`, and degrades to "untagged" rather
than failing, because a bot that will not start because git moved is worse than
one that does not know its own version.

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
and must stay that way. They hold API keys and notes about real people. Check
`git diff --cached --name-only` before committing.

**This repo is private as of 2026-08-13, and that is not the reason to relax
any of it.** It was written throughout as though public, and it stays written
that way: visibility is a setting somebody can change in two clicks, git
history is permanent, and the gap between those two facts is the whole risk.
Treat every commit here as publishable at the moment you make it. Anything that
would be a problem if this flipped public tomorrow belongs in `personnel`
instead, which is private and intended to stay that way.

## The privacy rule

`persona.md` carries hard limits: no real names, employer, city, family
members, or anything else identifying. **Brain profiles are bound by the same
limits**,
because they are assembled into the same system prompt.

This has already failed once. An excluded account was profiled anyway after its
Discord display name changed, and the generated profile captured a partner's
name, a child's name, and an employer. Exclusion is keyed on Discord **user
ID** for exactly that reason - never re-key it on display name, and never
assume a name-based match is sufficient.
