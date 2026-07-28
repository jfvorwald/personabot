"""personabot — a persona-driven Discord bot that speaks on a fixed schedule.

Each participant runs their own copy of this file with their own Discord bot
token, their own Anthropic API key, and their own persona file. Both bots sit
in the same channel.

Three modes:

    bot.py --now     post one message and exit
    bot.py --live    stay connected and reply in the channel
    bot.py           daemon, posting only at the times in POST_TIMES

Both non-scheduled modes are bounded so two bots can't ping-pong into an
infinite (and expensive) loop. Scheduled mode posts exactly len(POST_TIMES)
messages a day regardless of what anyone else says; live mode ignores other
bots by default and spends from a daily budget drawn between LIVE_DAILY_MIN
and LIVE_DAILY_MAX, after which it signs off until tomorrow.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from datetime import time as dtime
from zoneinfo import ZoneInfo

import anthropic
import discord
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("personabot")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
PERSONA_FILE = os.getenv("PERSONA_FILE", "persona.md")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "UTC"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))
MODEL = os.getenv("MODEL", "claude-opus-5")
EFFORT = os.getenv("EFFORT", "low")

# --live guards. Two bots that each reply on every message would loop forever,
# so live mode ignores bot authors by default and rations replies per day.
LIVE_REPLY_TO_BOTS = os.getenv("LIVE_REPLY_TO_BOTS", "false").lower() == "true"

# A fresh budget is drawn in this range each day rather than using a fixed
# number — a bot that stops dead on the same count every day is a bot people
# can measure. Only messages actually posted count against it.
#
# Set LIVE_DAILY_MAX=0 for no limit. Note that the budget is the only hard
# stop on two bots replying to each other forever; with it off, the brakes are
# the model's own choice to <pass> and nothing else.
LIVE_DAILY_MIN = int(os.getenv("LIVE_DAILY_MIN", "4"))
LIVE_DAILY_MAX = int(os.getenv("LIVE_DAILY_MAX", "10"))
LIVE_UNLIMITED = LIVE_DAILY_MAX <= 0

# Counterpart bots: matched case-insensitively against the Discord display
# name. These bypass the ignore-other-bots rule so the two personas can talk at
# all — but they are NOT guaranteed a reply. Letting one sit unanswered is
# allowed, and everything still spends from the daily budget, which is what
# keeps two bots from ping-ponging forever.
LIVE_COUNTERPARTS = [
    n.strip().lower()
    for n in os.getenv("LIVE_COUNTERPARTS", "agentic ben,agenticben").split(",")
    if n.strip()
]

# Unprompted conversation starters. Every IDLE_CHECK_MINUTES the bot looks at
# how quiet the channel has been; past IDLE_HOURS it may open a new thread of
# its own, subject to IDLE_CHANCE and the same daily budget.
IDLE_HOURS = float(os.getenv("IDLE_HOURS", "5"))
IDLE_CHECK_MINUTES = float(os.getenv("IDLE_CHECK_MINUTES", "30"))
IDLE_CHANCE = float(os.getenv("IDLE_CHANCE", "0.4"))

# Joining a conversation already in progress. Answering the first message of a
# thread we aren't part of reads as surveillance, not company — a person who
# wanders over lets a few go by first. A fresh target is drawn per thread so
# the delay isn't a countable tell.
JOIN_AFTER_MIN = int(os.getenv("JOIN_AFTER_MIN", "2"))
JOIN_AFTER_MAX = int(os.getenv("JOIN_AFTER_MAX", "5"))
# Past this many messages the moment has gone: whatever we'd have said is now
# about something two topics back. Redraw and wait for the next opening rather
# than answer stale context.
JOIN_WINDOW_MESSAGES = int(os.getenv("JOIN_WINDOW_MESSAGES", "8"))

# --- Making it behave like a person in a room, not a request handler --------
#
# Two separate problems. First, whether to speak at all: a real person in a
# group chat reads most messages and answers some. Rolling this client-side
# (before any API call) is both cheaper and more decisive than asking the model
# to choose <pass> every time, which it under-uses.
REPLY_CHANCE_ADDRESSED = float(os.getenv("REPLY_CHANCE_ADDRESSED", "0.95"))
REPLY_CHANCE_HUMAN = float(os.getenv("REPLY_CHANCE_HUMAN", "0.70"))
REPLY_CHANCE_COUNTERPART = float(os.getenv("REPLY_CHANCE_COUNTERPART", "0.45"))
# Multiplier applied when we were the last one talking — stops two bots from
# locking into strict alternation, and stops anyone monologuing.
REPLY_DECAY_IF_LAST_SPEAKER = float(os.getenv("REPLY_DECAY_IF_LAST_SPEAKER", "0.35"))
# Applied per message of ours in the recent window beyond the first.
REPLY_DECAY_IF_DOMINATING = float(os.getenv("REPLY_DECAY_IF_DOMINATING", "0.6"))

# Second, timing. Instant replies are the biggest tell. Read the room, think,
# then type at human speed.
SETTLE_SECONDS = float(os.getenv("SETTLE_SECONDS", "6"))       # let a burst finish
THINK_SECONDS_MIN = float(os.getenv("THINK_SECONDS_MIN", "2"))
THINK_SECONDS_MAX = float(os.getenv("THINK_SECONDS_MAX", "25"))
TYPING_CPS = float(os.getenv("TYPING_CPS", "13"))              # chars per second
TYPING_SECONDS_MAX = float(os.getenv("TYPING_SECONDS_MAX", "20"))

# Unprompted interrogations of the counterpart bot. A few times a day, at
# times drawn fresh each morning, walk up and ask him something absurd.
POKE_MIN_PER_DAY = int(os.getenv("POKE_MIN_PER_DAY", "2"))
POKE_MAX_PER_DAY = int(os.getenv("POKE_MAX_PER_DAY", "3"))
POKE_WINDOW_START = int(os.getenv("POKE_WINDOW_START", "9"))  # local hour
POKE_WINDOW_END = int(os.getenv("POKE_WINDOW_END", "22"))
# Two pokes never land closer together than this many minutes.
POKE_MIN_GAP_MINUTES = int(os.getenv("POKE_MIN_GAP_MINUTES", "75"))

POKE_PROMPT = """\
Walk up to {target} out of nowhere and ask him one question. Requirements:

- It must be genuinely ridiculous — an absurd hypothetical, an unhinged \
either/or, a demand that he account for something he never did, or a question \
built on a premise he never agreed to.
- Ask it completely straight, as though it's a reasonable thing to want to \
know and you're mildly impatient for the answer.
- No greeting, no preamble, no "random question but." Open with the question.
- One sentence. Two at the absolute most.
- Do not explain the joke, acknowledge that it's strange, or soften it.

Vary the shape from anything you've already asked in the transcript above — \
don't reuse a format you've used before."""

OPENER_PROMPT = """\
Nobody has said anything in a while. Start something — an opinion nobody asked \
for, a grievance, a callback to something from earlier, or a question designed \
to make someone incriminate themselves. Do not greet anyone, do not remark on \
the silence, do not ask how anyone is. Just walk in with something."""

# Said once when the budget runs out, then nothing more until tomorrow.
BRUSH_OFF_PROMPT = """\
You're done talking for today — out of energy for this, nothing dramatic. \
Write ONE short line, in character, that signals you're out and they should \
come back later. Under 15 words. Don't explain why, don't apologise, don't \
mention limits, quotas, or anything system-like. Just a person signing off."""

FALLBACK_BRUSH_OFF = "alright, that's me done for today. catch you tomorrow"

# Discord hard-caps a message at 2000 characters.
MAX_DISCORD_CHARS = 1900

FRAMING = """\
The document above describes the character you are playing. If it is written \
in the third person, that person is you — speak as them, in the first person. \
Never describe or analyse the character from the outside.

You are one member of a Discord channel with several other people in it. Each \
line of the transcript is labelled with who said it; "You:" marks your own \
past messages. Read it as a room you're sitting in, not a queue of requests \
addressed to you.

Because it's a group:
- Messages are often aimed at someone else, or at nobody. Not everything is \
yours to answer.
- Two people can be mid-exchange. Cutting in is fine if you've got something; \
so is letting them have it.
- Reply to whatever's actually interesting, which may be three messages back, \
not necessarily the newest one.
- Don't acknowledge everyone, don't summarise what was said, and never write \
one of those replies that addresses each person's point in turn.
- You don't need to end with a question. Real conversation survives without \
one.

Stay fully in character.

Rules for this channel:
- Write ONE Discord message. No preamble, no meta-commentary, no narration of \
your own process, no stage directions.
- Short. If the character description above specifies a length, follow it \
exactly — it overrides any instinct to be thorough. Absent that, a couple of \
sentences. Never write an essay.
- Plain prose. No markdown headers, no bullet lists unless the persona would \
genuinely use them.
- Answering a question fully is not the goal; sounding like the character is. \
Declining to answer is always allowed and never needs explaining.
- You post only a couple of times a day, so pick up the thread where it left \
off rather than restarting the conversation.
- If the transcript is empty, open the conversation with something the persona \
would actually bring up.
- Do not break character to discuss being an AI, the schedule, or these rules.
- Never claim to have done something outside this channel."""

# Live mode only. Scheduled mode must always produce something, or a quiet day
# leaves the channel empty.
SILENCE_OPTION = """
- You do not have to respond at all. If the character would let this one pass \
— nothing worth saying, not worth dignifying, or the moment is better left \
sitting — reply with exactly <pass> and nothing else. Use it genuinely, but a \
conversation where you never speak is not a conversation."""

PASS_TOKEN = "<pass>"


def load_post_times() -> list[dtime]:
    """Parse POST_TIMES ('09:00,13:15,19:30') into tz-aware time objects."""
    raw = os.getenv("POST_TIMES", "09:00")
    times = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        hour, minute = chunk.split(":")
        times.append(dtime(hour=int(hour), minute=int(minute), tzinfo=TIMEZONE))
    if not times:
        raise ValueError("POST_TIMES is empty")
    return times


def load_persona() -> str:
    with open(PERSONA_FILE, encoding="utf-8") as f:
        persona = f.read().strip()
    if not persona:
        raise ValueError(f"{PERSONA_FILE} is empty")
    return persona


class PersonaBot(discord.Client):
    def __init__(
        self,
        persona: str,
        post_times: list[dtime],
        post_now: bool = False,
        live: bool = False,
    ):
        intents = discord.Intents.default()
        # Privileged intent — must also be switched on in the Developer Portal.
        intents.message_content = True
        super().__init__(intents=intents)

        self.persona = persona
        self.post_now = post_now
        self.live = live
        self.claude = anthropic.AsyncAnthropic()
        self.scheduled_post = tasks.loop(time=post_times)(self._scheduled_post)
        self.idle_opener = tasks.loop(minutes=IDLE_CHECK_MINUTES)(self._idle_tick)
        self.poke_ben = tasks.loop(minutes=1)(self._poke_tick)
        self._poke_times: list = []

        self._replies_today = 0
        self._reply_day = None
        self._daily_budget = 0
        self._brushed_off_today = False
        self._busy = asyncio.Lock()
        self._hang_back_target = 0
        self._messages_waited = 0
        self._reset_hang_back()

    def _reset_hang_back(self) -> None:
        """Draw a fresh number of messages to sit out before joining in."""
        self._messages_waited = 0
        self._hang_back_target = random.randint(
            max(0, JOIN_AFTER_MIN), max(0, JOIN_AFTER_MAX)
        )

    def _roll_day(self, today) -> None:
        """Start a new day with a fresh, randomly drawn reply budget."""
        self._reply_day = today
        self._replies_today = 0
        self._brushed_off_today = False
        if LIVE_UNLIMITED:
            self._daily_budget = None
            log.info("New day (%s): no reply limit", today)
        else:
            self._daily_budget = random.randint(
                max(1, LIVE_DAILY_MIN), LIVE_DAILY_MAX
            )
            log.info("New day (%s): budget is %d replies", today, self._daily_budget)
        self._schedule_pokes(today)

    def _schedule_pokes(self, today) -> None:
        """Draw this day's random times for ambushing the counterpart bot."""
        from datetime import datetime, timedelta

        self._poke_times = []
        count = random.randint(POKE_MIN_PER_DAY, POKE_MAX_PER_DAY)
        if count <= 0 or not LIVE_COUNTERPARTS:
            return

        start = POKE_WINDOW_START * 60
        end = POKE_WINDOW_END * 60
        # Rejection-sample so two pokes don't land on top of each other.
        chosen: list[int] = []
        for _ in range(500):
            if len(chosen) == count:
                break
            m = random.randint(start, end)
            if all(abs(m - c) >= POKE_MIN_GAP_MINUTES for c in chosen):
                chosen.append(m)
        chosen.sort()

        now = discord.utils.utcnow().astimezone(TIMEZONE)
        skipped = 0
        for m in chosen:
            when = datetime.combine(today, dtime(0, 0), tzinfo=TIMEZONE) + timedelta(
                minutes=m
            )
            # Slots already past — mid-day restart, or a late start — are
            # dropped rather than fired immediately.
            if when <= now:
                skipped += 1
                continue
            self._poke_times.append(when)
        log.info(
            "Poking %s today at: %s%s",
            LIVE_COUNTERPARTS[0],
            ", ".join(t.strftime("%H:%M") for t in self._poke_times) or "(none left)",
            f" ({skipped} slot(s) already passed)" if skipped else "",
        )

    def _out_of_budget(self) -> bool:
        return self._daily_budget is not None and (
            self._replies_today >= self._daily_budget
        )

    async def on_ready(self):
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)
        if self.post_now:
            await self.speak()
            await self.close()
            return
        if self.live:
            log.info(
                "Live mode: channel %s, %s, counterparts=%s, "
                "reply-to-other-bots=%s. Ctrl-C to stop.",
                CHANNEL_ID,
                "NO reply limit"
                if LIVE_UNLIMITED
                else f"{LIVE_DAILY_MIN}-{LIVE_DAILY_MAX} replies/day",
                LIVE_COUNTERPARTS or "(none)",
                LIVE_REPLY_TO_BOTS,
            )
            log.info(
                "Mentions: always answered. Joining: after %d-%d messages, "
                "giving up past %d.",
                JOIN_AFTER_MIN,
                JOIN_AFTER_MAX,
                JOIN_WINDOW_MESSAGES,
            )
            # Draw today's budget and poke times up front, rather than waiting
            # for the first message to trigger a day-roll.
            self._roll_day(discord.utils.utcnow().astimezone(TIMEZONE).date())
            if not self.poke_ben.is_running():
                self.poke_ben.start()
            if not self.idle_opener.is_running():
                self.idle_opener.start()
                log.info(
                    "Idle openers: checking every %gmin, after %gh quiet, "
                    "%.0f%% chance",
                    IDLE_CHECK_MINUTES,
                    IDLE_HOURS,
                    IDLE_CHANCE * 100,
                )
            return
        if not self.scheduled_post.is_running():
            self.scheduled_post.start()
            log.info(
                "Scheduled to post at %s (%s)",
                ", ".join(t.strftime("%H:%M") for t in self.scheduled_post.time),
                TIMEZONE.key,
            )

    async def on_message(self, message: discord.Message):
        if not self.live or message.channel.id != CHANNEL_ID:
            return
        if message.author.id == self.user.id:
            return

        name = message.author.display_name.lower()
        counterpart = any(n in name for n in LIVE_COUNTERPARTS)
        if message.author.bot and not LIVE_REPLY_TO_BOTS and not counterpart:
            return
        if not message.clean_content.strip():
            log.warning(
                "Message from %s came through empty — MESSAGE CONTENT INTENT is "
                "probably off in the Developer Portal",
                message.author.display_name,
            )
            return

        today = message.created_at.astimezone(TIMEZONE).date()
        if today != self._reply_day:
            self._roll_day(today)

        mentioned = self._mentioned_me(message)

        # One at a time — otherwise fast consecutive messages race each other
        # and the bot answers the same context twice. A direct mention queues
        # for the lock instead of being dropped; being mid-sentence is not a
        # reason to ignore someone who asked us a question by name.
        if self._busy.locked() and not mentioned:
            log.info("Still writing the previous reply; skipping this one")
            return

        async with self._busy:
            # A human calling us by name is answered even when the day's budget
            # is gone. The budget exists to stop two bots looping forever, and
            # a person asking a direct question isn't that.
            human_mention = mentioned and not message.author.bot
            if self._out_of_budget() and not human_mention:
                if self._brushed_off_today:
                    log.info("Out of replies for today; ignoring")
                    return
                self._brushed_off_today = True
                log.info(
                    "Budget of %d used up; sending sign-off", self._daily_budget
                )
                try:
                    async with message.channel.typing():
                        await self.send_brush_off(message.channel)
                except Exception:
                    log.exception("Sign-off failed")
                return

            try:
                posted = await self._respond_like_a_person(message, counterpart)
            except Exception:
                log.exception("Live reply failed")
                return
            # Staying silent is free — only real messages spend the budget.
            if posted:
                self._replies_today += 1
                # We're in the conversation now; the next one starts a fresh
                # hang-back.
                self._reset_hang_back()
                log.info(
                    "Replies today: %d/%s",
                    self._replies_today,
                    self._daily_budget if self._daily_budget is not None else "∞",
                )

    def _mentioned_me(self, message: discord.Message) -> bool:
        """A real Discord @mention — an unambiguous request for an answer."""
        return self.user in message.mentions

    def _addressed_to_me(self, message: discord.Message) -> bool:
        if self._mentioned_me(message):
            return True
        text = message.clean_content.lower()
        return "jaq" in text or f"@{self.user.display_name.lower()}" in text

    async def _recent_mix(self, message) -> tuple[int, int]:
        """How much of the recent window is ours, and what's come since."""
        mine = 0
        others_since_me = 0
        async for m in message.channel.history(limit=6, before=message):
            if m.author.id == self.user.id:
                mine += 1
            elif mine == 0:
                others_since_me += 1
        return mine, others_since_me

    def _hang_back(self, mine: int) -> bool:
        """Should we let the others keep talking a while longer?

        Only applies to conversations we aren't already in — once we've spoken,
        the REPLY_DECAY_* multipliers handle how much we keep talking.
        """
        if mine:
            return False
        self._messages_waited += 1
        if self._messages_waited < self._hang_back_target:
            log.info(
                "Hanging back (%d/%d messages)",
                self._messages_waited,
                self._hang_back_target,
            )
            return True
        if self._messages_waited > JOIN_WINDOW_MESSAGES:
            log.info("Ran past the join window; waiting for a fresh opening")
            self._reset_hang_back()
            return True
        return False

    async def _reply_chance(
        self, message, counterpart: bool, mine: int, others_since_me: int
    ) -> float:
        """How likely this particular message is to be worth answering."""
        if self._addressed_to_me(message):
            base = REPLY_CHANCE_ADDRESSED
            reason = "addressed to me"
        elif counterpart or message.author.bot:
            base = REPLY_CHANCE_COUNTERPART
            reason = "counterpart"
        else:
            base = REPLY_CHANCE_HUMAN
            reason = "human"

        if mine and others_since_me == 0:
            base *= REPLY_DECAY_IF_LAST_SPEAKER
            reason += ", I spoke last"
        if mine > 1:
            base *= REPLY_DECAY_IF_DOMINATING ** (mine - 1)
            reason += f", {mine}/6 recent are mine"

        log.info("Reply chance %.2f (%s)", base, reason)
        return base

    async def _respond_like_a_person(self, message, counterpart: bool) -> bool:
        """Decide, wait, then answer — or quietly don't."""
        mine, others_since_me = await self._recent_mix(message)

        # A direct @mention is a question with our name on it. Answer it —
        # no dice roll, no hanging back, no decay for having just spoken.
        if self._mentioned_me(message):
            log.info("Directly mentioned; answering")
        elif self._hang_back(mine):
            return False
        else:
            chance = await self._reply_chance(
                message, counterpart, mine, others_since_me
            )
            if random.random() > chance:
                log.info("Not engaging with this one")
                return False

        # Let a burst finish before answering, the way you'd wait out someone
        # firing off three messages in a row.
        await asyncio.sleep(random.uniform(SETTLE_SECONDS * 0.5, SETTLE_SECONDS))
        latest = None
        async for m in message.channel.history(limit=1):
            latest = m
        if latest and latest.author.id == self.user.id:
            log.info("Already answered while settling; dropping")
            return False

        # Think before typing. Longer messages get a longer pause.
        think = random.uniform(THINK_SECONDS_MIN, THINK_SECONDS_MAX)
        think *= 0.6 + min(len(message.clean_content), 400) / 400
        log.info("Thinking for %.1fs", think)
        await asyncio.sleep(think)

        channel = message.channel
        transcript = await self.read_transcript(channel)
        reply = await self.generate(transcript, may_stay_silent=True)
        if not reply:
            return False
        if reply.strip().startswith(PASS_TOKEN):
            log.info("Chose to stay silent")
            return False

        # Then "type" it at a human rate.
        typing_time = min(len(reply) / TYPING_CPS, TYPING_SECONDS_MAX)
        async with channel.typing():
            await asyncio.sleep(typing_time)
            await channel.send(reply[:MAX_DISCORD_CHARS])
        log.info("Posted %d chars after %.1fs typing", len(reply), typing_time)
        return True

    async def _maybe_open(self):
        """Occasionally start a conversation when the channel has gone quiet."""
        if self._busy.locked():
            return
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)

        last = None
        async for msg in channel.history(limit=1):
            last = msg
        # Don't talk into the void twice in a row — if the last word was ours,
        # wait for someone to answer.
        if last is not None and last.author.id == self.user.id:
            return

        now = discord.utils.utcnow()
        if last is not None:
            quiet_hours = (now - last.created_at).total_seconds() / 3600
            if quiet_hours < IDLE_HOURS:
                return
        else:
            quiet_hours = float("inf")

        today = now.astimezone(TIMEZONE).date()
        if today != self._reply_day:
            self._roll_day(today)
        if self._out_of_budget():
            return

        # Probabilistic, so it doesn't open on a visible clock tick.
        if random.random() > IDLE_CHANCE:
            log.info("Channel quiet %.1fh — skipping this opener", quiet_hours)
            return

        async with self._busy:
            log.info("Channel quiet %.1fh — opening a conversation", quiet_hours)
            try:
                async with channel.typing():
                    transcript = await self.read_transcript(channel)
                    line = await self.generate(transcript, instruction=OPENER_PROMPT)
                if not line:
                    return
                await channel.send(line[:MAX_DISCORD_CHARS])
                self._replies_today += 1
                log.info(
                    "Opened a thread (%d/%s today)",
                    self._replies_today,
                    self._daily_budget if self._daily_budget is not None else "∞",
                )
            except Exception:
                log.exception("Opener failed")

    async def send_brush_off(self, channel):
        try:
            line = await self.generate(
                await self.read_transcript(channel), instruction=BRUSH_OFF_PROMPT
            )
        except Exception:
            log.exception("Could not generate a sign-off; using the fallback")
            line = ""
        await channel.send((line or FALLBACK_BRUSH_OFF)[:MAX_DISCORD_CHARS])

    async def _poke_tick(self):
        """Fire any poke whose time has arrived."""
        try:
            now = discord.utils.utcnow().astimezone(TIMEZONE)
            if now.date() != self._reply_day:
                self._roll_day(now.date())
            due = [t for t in self._poke_times if t <= now]
            if not due:
                return
            # Drop everything due, so a restart or a long stall can't cause a
            # burst of catch-up pokes all at once.
            self._poke_times = [t for t in self._poke_times if t > now]
            if self._busy.locked() or self._out_of_budget():
                return
            async with self._busy:
                await self._poke()
        except Exception:
            log.exception("Poke check failed; will retry next minute")

    async def _find_counterpart(self, channel):
        """Locate the counterpart in recent history so we can @mention them."""
        async for msg in channel.history(limit=200):
            name = msg.author.display_name.lower()
            if msg.author.id != self.user.id and any(
                n in name for n in LIVE_COUNTERPARTS
            ):
                return msg.author
        return None

    async def _poke(self):
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)
        who = await self._find_counterpart(channel)
        # Fall back to the configured name if he hasn't spoken here yet.
        target = who.mention if who else LIVE_COUNTERPARTS[0]

        async with channel.typing():
            transcript = await self.read_transcript(channel)
            line = await self.generate(
                transcript, instruction=POKE_PROMPT.format(target=target)
            )
        if not line:
            log.warning("Poke produced nothing")
            return
        # Make sure he actually gets pinged even if the model dropped the name.
        if who and who.mention not in line:
            line = f"{who.mention} {line}"
        await channel.send(line[:MAX_DISCORD_CHARS])
        self._replies_today += 1
        log.info("Poked %s: %s", target, line[:80])

    async def _idle_tick(self):
        try:
            await self._maybe_open()
        except Exception:
            log.exception("Idle check failed; will retry next tick")

    async def _scheduled_post(self):
        try:
            await self.speak()
        except Exception:
            # Never let one bad turn kill the loop — it has to survive until tomorrow.
            log.exception("Scheduled post failed; will try again at the next slot")

    async def speak(self, may_stay_silent: bool = False) -> bool:
        """Post one in-character message. Returns True if something was sent."""
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)
        transcript = await self.read_transcript(channel)
        reply = await self.generate(transcript, may_stay_silent)
        if not reply:
            log.warning("Model returned no text; nothing posted")
            return False
        if may_stay_silent and reply.strip().startswith(PASS_TOKEN):
            log.info("Chose to stay silent")
            return False
        await channel.send(reply[:MAX_DISCORD_CHARS])
        log.info("Posted %d chars to #%s", len(reply), channel.name)
        return True

    async def read_transcript(self, channel) -> str:
        """Render the recent channel history oldest-first, labelled by speaker."""
        lines = []
        async for msg in channel.history(limit=HISTORY_LIMIT):
            text = msg.clean_content.strip()
            if not text:
                continue
            who = "You" if msg.author.id == self.user.id else msg.author.display_name
            stamp = msg.created_at.astimezone(TIMEZONE).strftime("%a %H:%M")
            lines.append(f"[{stamp}] {who}: {text}")
        lines.reverse()
        return "\n".join(lines)

    async def generate(
        self,
        transcript: str,
        may_stay_silent: bool = False,
        instruction: str | None = None,
    ) -> str:
        framing = FRAMING + (SILENCE_OPTION if may_stay_silent else "")
        system = f"{self.persona}\n\n---\n\n{framing}"
        if instruction:
            user = (
                "Here is the recent conversation in the channel:\n\n"
                f"{transcript}\n\n{instruction}"
            )
        elif transcript:
            user = (
                "Here is the recent conversation in the channel:\n\n"
                f"{transcript}\n\n"
                "Write your next message."
            )
        else:
            user = "The channel is empty. Open the conversation."

        response = await self.claude.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=system,
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": user}],
        )

        if response.stop_reason == "refusal":
            log.warning("Model declined to respond: %s", response.stop_details)
            return ""

        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--now",
        action="store_true",
        help="Post one message immediately, then exit. Use this to smoke-test setup.",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Stay connected and reply whenever someone posts in the channel.",
    )
    args = parser.parse_args()

    bot = PersonaBot(
        load_persona(), load_post_times(), post_now=args.now, live=args.live
    )
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the token — check DISCORD_TOKEN in .env")
        return 1
    except asyncio.CancelledError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
