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

`persona.md`'s hard limits forbid disclosing employer, city, family, or the
pregnancy. Convincing impersonation needs the opposite - a person who can't
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

**Open question:** exemplars go in the *stable* part of the prompt if selected
once per restart, or the *volatile* part if selected per-reply. Per-reply is
better output; restart-stable is better for caching (see #10).

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

## 10. Prompt caching (ops, low priority)

The brain injection currently lands situational profiles inside the system
prompt, so the prefix changes whenever a different person is in the window and
nothing downstream caches. Correct ordering is stable content first (persona +
framing + core profiles) with the cache breakpoint there, and situational
profiles after it.

**Worth roughly pennies per month at 15-40 messages/day** - most requests fall
outside the 5-minute cache TTL anyway, so the write premium isn't recovered.
Do it as cleanup, not as a priority. Relevant numbers on `claude-sonnet-5`:
1024-token minimum cacheable prefix (the system prompt is ~5-6k, so it
qualifies), cache reads ~0.1x, writes 1.25x at the 5-minute TTL.

## 14. ASCII art: the forms that don't work yet

Shipped for row-based forms (charts, flowcharts, tables). Figures, faces and
anything with a closed border still come out a character misaligned, which
reads as broken rather than as a drawing. If that is worth fixing, the route is
a small curated library of hand-checked pieces the model picks from rather than
generates - fresh generation is what makes alignment unreliable.

## 11. Link and media behavior

A large share of how this group actually communicates is links, Tenor GIFs, and
custom emotes with no comment attached. The bot only ever produces prose, which
makes it the most verbose participant in the channel by a wide margin.

Hardest item here to do well - posting a *relevant* link requires either a
curated pool or search, and a bad link is far more conspicuous than no link.
Re-sharing something from the channel's own history is the cheap version and
fits the callback behavior in #5.
