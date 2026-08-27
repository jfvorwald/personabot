# Future enhancements

Ranked by leverage per unit of work. The goal driving this list: make the
persona indistinguishable from Jaq in voice, timing, and recall - inside a
channel where everyone knows it's a bot.

> ## ⏭️ NEXT UP: #1, few-shot exemplars
>
> **This is the single biggest quality jump still on the table, and most of the
> machinery already exists.** Start here when picking this back up.

---

## The disclosure line

Everything below is about being *convincing*, not about being *undisclosed*.
The bot posts as `agentix`, alongside `Agentic Ben` and `Agentic Maria`, in a
server where the group knows what those accounts are. That's the setup these
features are built for.

The line: posting from Jack's own account, or under a display name engineered
to be mistaken for him, where people don't know they're talking to a bot. Voice
cloning (#9) is the first item on this list where that stops being theoretical,
so decide the disclosure question before building it, not after.

## The unresolved tension

`persona.md`'s hard limits forbid disclosing employer, city, or family.
Anything identifying, in other words. Convincing impersonation needs the opposite - a person who can't
mention anything about their life reads as evasive over a long enough window.

Right now the bot is a **character who shares Jaq's sense of humor**. A real
impersonation would need to know his actual life. That's a decision to make
deliberately, not a feature to build. Nothing below depends on resolving it
except in how far #5 (recall) is allowed to go.

---

## 1. Few-shot exemplars from real messages ⏭️

**The biggest remaining lever.** `persona.md` *describes* the voice in prose;
40-60 real messages *demonstrate* it. Few-shot beats description decisively for
voice - it's the difference between "dry, deadpan, sparse punctuation" and
seeing twenty actual examples of it.

Most of this is already built:

- 669 messages from `jaqsup` are already indexed in the brain
- `brain.py` already knows how to pull a person's messages from Discord
- The system prompt already has a place to put them

**Design sketch:**

- Harvest Jaq's own messages, filter out links/one-word replies, keep the ones
  with actual voice in them.
- Select by **similarity to the current conversation**, not at random - so the
  model sees him being funny about *this* topic, not a fixed sample. Keyword
  overlap against the live transcript is enough; embeddings are better but add
  a dependency.
- Inject as exemplars ahead of the transcript, clearly framed as "here is how
  you have written before," not as conversation history.
- Cap at ~40 to keep the prompt bounded.

**Open question, now cheaper to answer:** exemplars go in the *stable* part of
the prompt if selected once per restart, or the *volatile* part if selected
per-reply. Per-reply is better output; restart-stable is better for caching.
Since #10 shipped there is a real number on that tradeoff rather than a guess -
the stable half is 8222 tokens and is read back at 0.1x on 61% of calls, so
per-reply selection of ~40 exemplars would sit in the volatile half and be paid
for in full every time. Measure it against the cached alternative before
choosing; the logging added in #10 is what makes that measurable.

## 2. Reactions ✅ SHIPPED

Real people react far more often than they reply. Implemented: the bot reacts
to messages it chose *not* to reply to, using the server's own custom emotes,
on its own budget separate from replies. See `README.md` → live mode.

**Not yet done, worth adding later:** reacting to *older* messages (people
scroll up and react to something from an hour ago), and reacting to its own
counterpart's messages as a form of acknowledgement without spending a reply.

## 3. Multi-message bursts

Jaq and Zack both fire 2-3 short messages in a row; the bot always sends
exactly one. This is a tell present in *every single message it sends*.

Split generated replies on natural boundaries (sentence breaks, topic shifts)
and send them as separate messages with a realistic inter-message delay and a
typing indicator between each. Should be probabilistic - most replies stay
single, bursts happen when the content naturally splits.

## 4. Posting rhythm from real history

Idle openers and pokes currently sample **uniformly at random** inside a window.
Real posting activity is nothing like uniform - it clusters around specific
hours and differs on weekends.

Derive an hour-of-day (and day-of-week) histogram from Jaq's actual `#general`
history and sample from that instead. Cheap to build, and it fixes a tell that
only shows up in aggregate - which is exactly the kind nobody notices they're
producing.

## 5. Long-term recall and real callbacks

**The largest structural gap.** `HISTORY_LIMIT=30` is a hard ceiling on memory.
Meanwhile `persona.md` says:

> *"Callbacks are the payoff... a detail they mentioned earlier, returned
> deadpan at the worst possible moment."*
> *"You're collecting. Everything is admissible later."*

It cannot do either. The persona describes a memory the architecture doesn't
have. This is the difference between a bot that *sounds* like Jaq and one that
*knows things*.

**Design sketch:**

- Index the channel archive (message ID, author, text, timestamp).
- On each reply, retrieve the top-k older exchanges relevant to the current
  conversation and inject them as "things you remember."
- Keyword/BM25 overlap needs no new dependencies. Local embeddings would be
  meaningfully better and cost one small model.
- Keep it clearly separated from the live transcript so the model doesn't
  mistake old context for current.

## 6. Self-consistency ledger

`persona.md` says *"you commit past all reason... you never wink, you never
break."* The bot has no record of what it committed to, so it can contradict a
bit it ran yesterday - which is the one failure that kills a bit permanently.

Track asserted opinions and running bits in a small append-only file; inject
the active ones. Natural companion to #5 and could share its storage.

## 7. Typos and corrections

`persona.md`: *"Let a typo through now and then. Don't fix it."* Models won't do
this reliably no matter how it's phrased - clean text is too strong an
attractor.

Needs to be post-processing: occasionally introduce a realistic slip
(transposition, dropped letter, missing apostrophe) and sometimes follow with a
`*correction` message a few seconds later. The follow-up correction is the
more human half of this.

## 8. Evaluation harness

The item that's easy to skip and shouldn't be. Right now "does this sound like
Jaq" is vibes, and there's no way to tell whether any change on this list
actually helped or quietly made things worse.

Blind A/B: present real messages and generated ones unlabeled, score them.
Either self-scored or - better - handed to the group as a game, which is both
a real eval and a decent bit in its own right.

Build this before #1 if you want to *measure* #1's impact rather than assume it.

## 9. Voice

The group lives in voice chat. A bot that joins and speaks in a cloned voice is
the largest impersonation jump available, by a wide margin - and the point
where the disclosure question at the top stops being theoretical. Large lift:
voice connection, TTS, turn-taking, interruption handling.

Decide the disclosure question *before* building this one.

## 12. The influence half of the psychology material

`psychology.md` carries the conversational-mechanics half of a behavioral
ruleset. The other half - motivational interviewing, reactance, Cialdini's
triggers, warmth/competence trust-building, framing ethics - was deliberately
left out, and should stay out unless the bot's job changes.

It is written for an assistant that serves a user and wants to influence them.
Jaq does neither. Three of its rules directly contradict `persona.md`: lead with
warmth (vs "funny first and polite never"), validate before advising (vs "mean
is the love language"), and scale politeness to the imposition (vs deliberately
impolite). Loading contradictory instructions is what made the persona bland in
the first place.

Revisit only if the bot ever acquires a job where persuasion is the point.

## 13. Known bug: restart.sh startup wait can match a previous run

`start()` waits for the bot to come up by grepping the last 40 lines of
`live.log` for `Live mode:`. Since the log now appends across deploys instead
of being truncated, that tail can contain the *previous* run's startup line -
so the wait returns before the new process has logged anything, and
`./restart.sh` can report success a moment early. Self-corrects on the next
status call; harmless but wrong.

The fix is a single `current_run()` helper - awk from the last `===== started`
marker to the end - shared by both the startup wait and `status`, so the two
cannot disagree about which run they are reading.

## 10. Prompt caching ✅ SHIPPED (v0.11.0)

Shipped, and the entry below was wrong about the two things that decided it.
Both errors came from estimating rather than measuring, which is the part
worth keeping.

**"Most requests fall outside the 5-minute TTL, so the write premium isn't
recovered."** Measured across 730 real API calls in `live.log`: the median gap
between calls is **1.8 minutes**, and **61% arrive within five minutes** of the
previous one. The traffic is bursty conversation, which is the exact shape
caching is built for, and a cache read refreshes the entry's timer for free so
a busy afternoon keeps one entry alive the whole way. The 1-hour TTL covers 79%
but costs 2x to write, netting 51% off the prefix against 45% - not worth
doubling the write price to be marginally better on an estimate.

**"The system prompt is ~5-6k."** The stable half alone is **8222 tokens**,
69% of it.

**The reordering this entry called for turned out not to be needed.** Persona,
psychology and vocabulary are read once at `__init__` and are byte-identical on
every reply, so the breakpoint goes straight after them with the prompt left
exactly as it was. Pulling the framing and confidentiality blocks into the
cached half as well was measured: it buys 14% more cached tokens, which does
not justify touching the document that defines how he talks.

**Automatic caching is the wrong tool here** and would have cost money. The
top-level form places the breakpoint on the last cacheable block, and the last
block is the transcript, which differs on every request - so every call writes
an entry at 1.25x and never reads one back. Automatic is for a conversation
that grows across turns and reuses a lengthening prefix. This bot sends one
fresh user message each time.

Every reply now logs `Cache: N read, N written, N fresh`. The failure mode is
silent - a later change to prompt assembly stops the prefix matching and
nothing errors - so it is logged every time rather than checked once.

## 14. ASCII art: what the research actually showed

Resolved. The first version steered toward charts because figures came out
misaligned, but that was generalising from the two hardest cases - a likeness
of a specific person, and closed borders. Comparing four prompting strategies
on ordinary subjects showed the model draws recognisable pictures fine.

What won: explicit rules. Restrict the character vocabulary, bound rows and
columns, say "work out the silhouette first", demand nothing but the art.

What lost, and it is worth remembering: **few-shot examples.** Shown three
sample drawings and asked for a dog, the model returned the cat from the
examples. That is the third time in this project examples in a prompt were
copied verbatim rather than used as register - it also happened with the
swearing examples and the compassion line. Rules generalise; examples get
reproduced.

### The render-then-convert engine, tabled on cost

Typed art is still mediocre, so the next version was built and tested: have the
model draw a black silhouette with PIL primitives in Anthropic's code execution
sandbox, then reduce the raster to characters through a ten-step ramp. The
conversion is arithmetic, so alignment stops being something the model has to
get right by eye, and inside the sandbox it sees its own render and revises it -
observed noticing resampling artefacts and redrawing at a higher supersample
without being asked.

**It works and it is far better looking. It was dropped on price.** Measured
end to end on `claude-opus-5` with `code_execution_20260521`:

| subject         | time | output tokens |
| --------------- | ---- | ------------- |
| whiskey bottle  | 42s  | 2,503         |
| cow head        | 64s  | 3,822         |
| dog             | 153s | 8,984         |

Bounding it to a single revision brought the dog to 82s / ~5k with quality
intact, so the real figure is **40-85 seconds and $0.06-0.12 a drawing** -
roughly a hundred times an ordinary reply, for a bit that fires once a day.
Not worth it at this channel's volume.

The sandbox is a requirement, not a nicety, if this is ever picked back up:
the subject comes from a Discord message, so untrusted input is shaping the
code being run, and that does not execute in the bot's process.

What it would take to make this viable: a cheaper model for the drawing step,
a cache keyed on subject so repeat requests are free, and running it as a
background task like reactions so an 80-second render cannot hold the reply
lock and stall an `@mention`.

## 11. Link and media behavior

A large share of how this group actually communicates is links, Tenor GIFs, and
custom emotes with no comment attached. The bot only ever produces prose, which
makes it the most verbose participant in the channel by a wide margin.

Hardest item here to do well - posting a *relevant* link requires either a
curated pool or search, and a bad link is far more conspicuous than no link.
Re-sharing something from the channel's own history is the cheap version and
fits the callback behavior in #5.

## 15. A tool that interviews Jack and writes the notes ⏭️

**The highest-value data in the system is 96% empty, and no bot feature moves
that number.** `personnel/general/people.yml` maps 26 people. One of them,
slaymakerlol, has notes with prose in them. Six more have directories holding
a blank form. The brain can only ever produce the observable half, and the
half that actually distinguishes this from a generic shitposter - stance,
handling, history, grudges - exists nowhere but in Jack's head.

The bottleneck is not storage, retrieval, or budget. It is that writing five
paragraphs about a friend from a cold start is work, and it stays undone.

**Design sketch:**

- `tools/interview.py <slug>`. Reads the brain profile for observed material
  and the existing notes for what is already answered.
- Drafts three to five specific questions from what the scan saw, not generic
  ones. "The scan says he is guildmaster and runs the raid schedule. Is the
  authority the thing you go after, or is that too easy?" beats "what do you
  think of him?" every time, because the first can be answered in a sentence.
- Takes the answers as free prose, in any order, and writes `notes.md` in the
  register the slaymakerlol file established.
- Never invents. An unanswered heading is left out entirely, per the blank
  form rule.

Worth building before anything that consumes personnel content more cleverly.
Better retrieval over an empty directory retrieves nothing.

## 16. Instrumentation: what actually got injected

**There is currently no way to answer "did writing Zack's notes change
anything?"** The prompt assembles a persona, a psychology document, core
profiles, situational profiles and personnel notes, and logs none of it. The
only line on the subject is one at startup naming the provider.

`_observe` records six kinds of event - blocked, dm, gif, image, opener, pass -
and ordinary replies are not among them. The one thing the bot does most is
the one thing it does not write down.

**Design sketch:**

- Log the slugs injected per reply and the character cost of each block.
- Add a `reply` observation carrying which sources were in the prompt.
- That is enough to answer: which profiles are actually reaching prompts, what
  the split between generated and hand-written content costs, and whether a
  person's notes correlate with anything.

Cheap, no model call, and it is the precondition for #8 meaning anything. An
eval harness that cannot see what went into the prompt can only score outputs
against vibes, which is what #8 exists to replace.

## 17. Doctor check for profile health

A scan now refuses to write a profile that is truncated or carries a term from
`REDACT_TERMS`. Refusing means the previous file stays, so **a bad profile
written before those guards existed persists silently and forever.**
`wurmz.md` is truncated mid-sentence right now, and nothing surfaces it - it
was found by grepping the last line of every file by hand.

`check_7_brain` alongside the personnel check, failing nothing, reporting:
generated halves that end mid-sentence, any file matching `REDACT_TERMS`, a
handle with `is_bot` true that still has a file, and profiles older than the
last scan by a wide margin. `brain/people/` is gitignored, so nothing else is
watching it at all.

## 18. Documents that remember they had a previous version

The artifact path writes `v4.2 FINAL FINAL` on a spreadsheet, which is funny
once and implies a history that does not exist. Ask twice and you get two
unrelated documents that both claim to be revisions of nothing.

**A registry of what he has produced** - shape, subject, date, and one line of
what was in it - lets him refer back. "That is covered in the attendance
ledger, row 4, which you are not allowed to edit" is a better joke than the
ledger was, and it costs one line of storage per document.

Natural companion to #6, and probably the same file. Both are the same problem:
the persona claims a continuity the architecture does not have.

## 19. Knowing who is actually in the room

Distinct from #4, which is about *when* to post. This is about *who* to
address. The bot names people freely with no model of whether they are around,
so it can open by needling someone who has not spoken in six hours - a thing a
person in a group chat does not do, because they can see the sidebar.

Discord exposes presence and the transcript already carries who spoke recently.
Cheap version: never address by name anyone absent from the last N messages
unless replying to them directly. Better version: weight who gets named by how
recently they spoke.

Also the missing input for #3 and for openers. An opener aimed at nobody in
particular reads differently from one aimed at a person who is not there.

## 20. Unprompted deliverables, rationed hard

The ASCII path has an overkill mode: answer a trivial question with a full
diagram, once a day, because the disproportion is the joke. The artifact path
has no equivalent, and only ever fires when asked.

The unprompted version is stronger, and riskier. Somebody says "we should
sort out raid times" and gets back a scheduling document nobody asked for.
It needs the same discipline the art path uses - a trigger narrow enough that
it only fires on something genuinely offhand, and a budget of about one a day -
because a bot that produces documents at people unprompted is the exact failure
the on-request-only rule was written to avoid.

Build after #16, so there is a way to tell whether it landed.
