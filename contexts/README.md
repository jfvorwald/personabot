# Picture contexts

Worlds a picture can be set in, one per markdown file.

A channel has recurring subjects, and a picture about one of them lands better
when it looks like it belongs to that subject. Rather than teach the persona
about every one, each is a file that says what the world looks like, what fires
it, and how often.

```
contexts/
  README.md     this, tracked
  example.md    the template, tracked - copy it
  yours.md      whatever your channel is actually about, gitignored
```

Your own contexts are gitignored for the same reason `persona.md` is: they
describe a specific group of people and their in-jokes, and this repo is
public. Only the template ships.

## Adding one

Copy `example.md`, rename it, fill it in. There is no registration step and no
code to change - `src/contexts.py` reads the directory fresh each time, so an
edit takes effect on the next picture without a restart.

```markdown
---
name: warcraft
when: wow, azeroth, raid, mythic, guild, loot, wipe
chance: 0.6
---

What this world looks like, in a few sentences.
```

## When one fires

Two gates, and both have to pass:

1. **A trigger word appears** in the recent conversation, matched as a whole
   word so `raid` does not fire on `afraid`.
2. **It wins its `chance` roll.** Below 1 on purpose. A context that fires
   every single time it could gives the channel a house style nobody chose,
   and the pictures stop being surprising.

Where several contexts fit at once, one is drawn at random rather than the
first alphabetically, so a file named early does not quietly own every overlap.

All of this only runs when a picture is *already* being offered, which is a
small fraction of replies. On an ordinary message nothing here is read.

## Why keywords rather than letting the model choose

The model would need the name and description of every context in its prompt on
every offered reply, and it reliably under-uses options presented that way -
the same reason this bot rolls its reply chance in code rather than asking the
model to decline. Keywords are free, tunable by editing markdown, and the log
says exactly why a context fired.

The cost is that a context only fires on words someone actually typed. Choose
trigger words that are specific to the world and rare in ordinary conversation:
too generic and every picture comes out in the same register, which is the one
failure worth watching for here.
