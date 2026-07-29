---
name: example
when: put, your, trigger, words, here
chance: 0.6
---

Copy this file, rename it, and fill it in. It will not fire as it stands - the
trigger words above are placeholders, and a file named `example.md` is skipped
on purpose so a fresh clone does not start rendering every picture like this
one.

Everything below the second `---` is the context itself, and it is shown to the
model as guidance while it decides what a picture should look like. Write it
the way you would explain a running joke to someone new: what the world is,
what it looks like, and what makes a picture belong to it.

What works here:

- **A look, not a subject.** "Washed-out fluorescent lighting, everything
  slightly too brown" shapes every picture. "A dog" only shapes one.
- **The register.** Is this world grand and taking itself seriously, or shabby
  and disappointing? That decision does more than any amount of visual detail.
- **What recurs.** The place everyone ends up, the object that keeps coming
  back, the thing that is always broken.
- **What to avoid.** Worth stating outright, because it is the part the model
  will otherwise reach for. If you never want a logo, or a face, say so.

Keep it short. A few sentences beats a page: this is added to a prompt that
already contains a persona, and a long context starts arguing with it.

## The fields at the top

| Field | What it does |
|---|---|
| `name` | What shows in the log when it fires. Defaults to the filename |
| `when` | Comma-separated trigger words, matched as whole words against the recent conversation. This is what makes a context fire only where it belongs |
| `chance` | 0 to 1, rolled after a match. Below 1 so the same world does not claim every picture it could |

Pick trigger words that are specific to the world and rare elsewhere. A word
that appears in ordinary conversation makes the context fire constantly, which
is the failure that makes a channel's pictures all look the same.

Set `chance` lower for a world that comes up all the time and higher for one
that rarely does, so no single context dominates.
