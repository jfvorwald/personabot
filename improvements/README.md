# Self improvement

What Jaq is doing wrong, measured rather than guessed at, and proposals for
what to change about him.

The model cannot see its own habits. Every reply is a fresh single-turn call
with no memory of the last forty, so a verbal tic is invisible from the inside
and obvious from the outside. On the first evening this was measured, the word
"still" opened **37% of his messages** and nothing in the system could have
noticed.

## How it works

```
  LIVE BOT                          OFFLINE TOOL (tools/improve.py)
  ────────                          ──────────────────────────────
  appends one line per decision  ─▶  measures what was posted
  no API call, no model              asks for proposals
                                     writes them down, changes nothing
                                                │
                                                ▼
                                     Jack reads and decides
```

Two layers on purpose, the same split the output guard uses:

- **Measured**, in `src/improve.py`: repetition, opening habits, repeated
  phrases, length drift, how often anyone answered him. Pure functions, no
  Discord, no model. These are facts.
- **Judged**, by a model given those facts: what to change. Proposals only.

Nothing here ever takes effect. That is the same contract `brain.py` has, and
for the same reason - generated content derived from a private channel gets
reviewed by a human before it goes anywhere near the bot.

## Running it

```bash
.venv/bin/python tools/improve.py              # the last 24 hours
.venv/bin/python tools/improve.py --hours 72
.venv/bin/python tools/improve.py --dry-run    # measurements only, no model call
```

Start with `--dry-run`. The measurements are the useful half and they cost
nothing.

## What lands where

```
improvements/observations.jsonl   appended constantly by the live bot
improvements/log/YYYY-MM-DD.md    one entry per run, kept as written
improvements/BACKLOG.md           accumulated proposals, merged not replaced
```

The backlog accumulates on purpose. A snapshot rewritten each run means
anything not acted on immediately is gone by tomorrow, which quietly turns "I
will get to that later" into "that never happened".

- A proposal that comes back carries a **count** rather than becoming a
  duplicate, including when the model rewords it. "Suggested five times and
  still not done" is the most useful thing the file can tell you.
- Mark an item `[done]` or `[dropped]` to decide it. **A decision is never
  reopened**, even if the same suggestion turns up again - silently reversing
  a call you made is worse than losing a suggestion.
- Anything you write underneath an item is kept across merges.

All three are gitignored. They contain channel content and they describe how
Jaq works, which is exactly what the confidentiality directive exists to
protect. Only this README and the tooling are shared.

## The rule that matters

**The fitness signal is the humans in the room, not the counterpart bot.**

Two bots optimising against each other drift into a private register nobody
else enjoys, and the drift is invisible from inside it because both of them
are delighted. The counterpart is a source of technique. Whether something
worked is a question about the people.

## What it deliberately will not propose

Anything that makes him talk more, reply more often, or write longer messages.
The design goal is a person in a room rather than a service, and every one of
this project's regressions has come from adding instruction rather than
removing it - so the prompt is told to prefer taking something away.
