"""personabot - a persona-driven Discord bot that speaks on a fixed schedule.

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
import json
import unicodedata
from collections import deque
import datetime
from datetime import time as dtime

import anthropic
import discord
from discord.ext import tasks

import brain
import changelog
import decide
import react
from decide import fold
from paths import ROOT, at_root
from persona import load_persona, load_post_times, load_psychology, load_vocab


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("personabot")

from config import *  # noqa: F403  (every setting, by name)

from prompts import (
    ART_OVERKILL_INSTRUCTION,
    ASCII_ART_PROMPT,
    BRUSH_OFF_PROMPT,
    NO_UPDATES_PROMPT,
    PATCH_NOTES_PROMPT,
    POLL_LOST_PROMPT,
    POLL_PROMPT,
    FALLBACK_BRUSH_OFF,
    FRAMING,
    MAX_DISCORD_CHARS,
    OPENER_PROMPT,
    PASS_TOKEN,
    POKE_PROMPT,
    REACT_PROMPT,
    SILENCE_OPTION,
)



class PersonaBot(discord.Client):
    def __init__(
        self,
        persona: str,
        post_times: list[dtime],
        post_now: bool = False,
        live: bool = False,
    ):
        intents = discord.Intents.default()
        # Privileged intent - must also be switched on in the Developer Portal.
        intents.message_content = True
        super().__init__(intents=intents)

        self.persona = persona
        self.psychology = load_psychology()
        self.vocab = load_vocab()
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
        self._reactions_today = 0
        self._art_today = 0
        self._polls_today = 0
        self._polls_today = 0
        self._open_polls: list[int] = []
        self._recent_reactions: deque = deque(maxlen=REACT_RECENT_MEMORY)
        self._pending: set = set()
        self._reset_hang_back()

    def _react_later(self, message, replied: bool = False) -> None:
        """Kick off a reaction without blocking the reply path.

        Reactions wait a while before landing, and _respond_like_a_person runs
        holding the one-at-a-time lock - awaiting that delay inline would stall
        a mention queued behind it for the length of the pause.
        """
        if not REACT_ENABLED:
            return
        task = asyncio.create_task(self._maybe_react(message, replied))
        # Hold a reference: the event loop only keeps weak ones, so an
        # un-stored task can be garbage collected mid-flight.
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _maybe_react(self, message, replied: bool) -> None:
        """React to a message instead of (or occasionally alongside) answering.

        Staying silent is the right call most of the time, but silence and
        absence look identical from the outside. A reaction is how a person
        signals they read something without taking the floor.
        """
        if not REACT_ENABLED:
            return
        chance = REACT_CHANCE_REPLIED if replied else REACT_CHANCE_PASSED
        if random.random() > chance:
            return
        if not react.within_budget(self._reactions_today, REACT_DAILY_MAX):
            return
        # Nothing to react to. Attachments and bare embeds come through with
        # empty text, and a reaction picked from no content is a coin flip.
        if not message.clean_content.strip():
            return

        guild = getattr(message.channel, "guild", None)
        custom = {e.name: e for e in (guild.emojis if guild else [])}
        names = react.offerable(custom, self._recent_reactions)
        if not names:
            return

        try:
            choice = await self._pick_reaction(message.channel, names)
        except Exception:
            log.exception("Reaction pick failed")
            return
        choice = react.parse_choice(choice, names)
        if not choice:
            return

        # Claim the slot before the delay, not after. Several reaction tasks
        # run concurrently; checking the budget and then sleeping up to
        # REACT_DELAY_MAX before incrementing lets every one of them pass the
        # same check and blow past the cap together.
        self._reactions_today += 1
        await asyncio.sleep(random.uniform(REACT_DELAY_MIN, REACT_DELAY_MAX))
        try:
            await message.add_reaction(custom.get(choice, choice))
        except discord.HTTPException:
            log.exception("Could not add reaction %s", choice)
            self._reactions_today -= 1  # hand the slot back
            return
        self._recent_reactions.append(choice)
        self._save_day()
        log.info(
            "Reacted %s (%d/%s today)",
            choice,
            self._reactions_today,
            REACT_DAILY_MAX or "∞",
        )

    async def _pick_reaction(self, channel, names: list[str]) -> str | None:
        """Ask for one emote name, or PASS. Small prompt - this is not a reply."""
        lines = []
        async for m in channel.history(limit=6):
            text = m.clean_content.strip()
            if not text:
                continue
            who = "You" if m.author.id == self.user.id else m.author.display_name
            lines.append(f"{who}: {text[:300]}")
        lines.reverse()
        if not lines:
            return None

        response = await self.claude.messages.create(
            model=MODEL,
            max_tokens=20,
            system=REACT_PROMPT.format(emotes=", ".join(names)),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        if response.stop_reason == "refusal":
            return None
        raw = "".join(
            b.text for b in response.content if b.type == "text"
        ).strip().strip(":")
        if not raw or raw.upper() == "PASS":
            return None
        return raw

    def _reset_hang_back(self) -> None:
        """Draw a fresh number of messages to sit out before joining in."""
        self._messages_waited = 0
        self._hang_back_target = random.randint(
            max(0, JOIN_AFTER_MIN), max(0, JOIN_AFTER_MAX)
        )

    def _state_path(self) -> str:
        return at_root(STATE_FILE)

    def _save_day(self) -> None:
        """Persist today's spend. Cheap, and it runs only when we post."""
        try:
            with open(self._state_path(), "w") as f:
                json.dump(
                    {
                        "day": str(self._reply_day),
                        "replies": self._replies_today,
                        "reactions": self._reactions_today,
                        "art": self._art_today,
                        "polls": self._polls_today,
                        "open_polls": self._open_polls,
                        "budget": self._daily_budget,
                        "brushed_off": self._brushed_off_today,
                    },
                    f,
                )
        except OSError:
            log.exception("Could not persist daily state")

    def _restore_day(self, today) -> bool:
        """Pick today's counters back up after a restart. False if it's a new day."""
        try:
            with open(self._state_path()) as f:
                state = json.load(f)
        except (OSError, ValueError):
            return False
        if state.get("day") != str(today):
            return False

        self._reply_day = today
        self._replies_today = state.get("replies", 0)
        self._reactions_today = state.get("reactions", 0)
        self._art_today = state.get("art", 0)
        self._polls_today = state.get("polls", 0)
        self._open_polls = state.get("open_polls", [])
        self._daily_budget = state.get("budget")
        self._brushed_off_today = state.get("brushed_off", False)
        log.info(
            "Resuming today: %d/%s replies and %d reactions already spent",
            self._replies_today,
            self._daily_budget if self._daily_budget is not None else "\u221e",
            self._reactions_today,
        )
        self._schedule_pokes(today)
        return True

    def _roll_day(self, today) -> None:
        """Start a new day with a fresh, randomly drawn reply budget."""
        self._reply_day = today
        self._replies_today = 0
        self._reactions_today = 0
        self._art_today = 0
        self._brushed_off_today = False
        if LIVE_UNLIMITED:
            self._daily_budget = None
            log.info("New day (%s): no reply limit", today)
        else:
            self._daily_budget = random.randint(
                max(1, LIVE_DAILY_MIN), LIVE_DAILY_MAX
            )
            log.info("New day (%s): budget is %d replies", today, self._daily_budget)
        self._save_day()
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
            # Slots already past - mid-day restart, or a late start - are
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
            log.info(
                "Allies: %s. Reactions: %s. Brain: %s.",
                ", ".join(ALLIES) or "(none)",
                f"{REACT_CHANCE_PASSED:.0%} of passes, max {REACT_DAILY_MAX}/day"
                if REACT_ENABLED
                else "off",
                f"{brain.profile_count()} profiles, core={','.join(brain.BRAIN_CORE) or '(none)'}"
                if BRAIN_ENABLED
                else "off",
            )
            # Restore today's spend if this is a restart rather than a new
            # day; only draw a fresh budget when the date has actually rolled.
            today = discord.utils.utcnow().astimezone(TIMEZONE).date()
            if not self._restore_day(today):
                self._roll_day(today)
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
                "Message from %s came through empty - MESSAGE CONTENT INTENT is "
                "probably off in the Developer Portal",
                message.author.display_name,
            )
            return

        today = message.created_at.astimezone(TIMEZONE).date()
        if today != self._reply_day:
            self._roll_day(today)

        mentioned = self._mentioned_me(message)

        # One at a time - otherwise fast consecutive messages race each other
        # and the bot answers the same context twice. A direct mention queues
        # for the lock instead of being dropped; being mid-sentence is not a
        # reason to ignore someone who asked us a question by name.
        if self._busy.locked() and not mentioned:
            log.info("Still writing the previous reply; skipping this one")
            return

        async with self._busy:
            # A human calling us by name is answered even when the day's budget
            # is gone, and so is an ally. The budget exists to stop two bots
            # looping forever; neither of those is that.
            human_mention = mentioned and not message.author.bot
            exempt = human_mention or self._is_ally(message)
            if self._out_of_budget() and not exempt:
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
            # Staying silent is free - only real messages spend the budget.
            if posted:
                self._replies_today += 1
                # We're in the conversation now; the next one starts a fresh
                # hang-back.
                self._reset_hang_back()
                self._save_day()
                log.info(
                    "Replies today: %d/%s",
                    self._replies_today,
                    self._daily_budget if self._daily_budget is not None else "∞",
                )

    def _mentioned_me(self, message: discord.Message) -> bool:
        """A real Discord @mention - an unambiguous request for an answer."""
        return self.user in message.mentions

    def _is_ally(self, message: discord.Message) -> bool:
        if message.author.bot:
            return False
        # Id first: it survives every rename. Names remain as a convenience for
        # anyone whose id isn't configured yet.
        if str(message.author.id) in ALLY_IDS:
            return True
        if not ALLIES:
            return False
        return decide.name_matches(
            {message.author.display_name, message.author.name or ""}, ALLIES
        )

    def _wants_patch_notes(self, message: discord.Message) -> bool:
        """Asking us what has changed about us lately."""
        return self._addressed_to_me(message) and decide.is_update_request(
            message.clean_content
        )

    def _wants_poll(self, message: discord.Message, transcript: str) -> bool:
        """Is this a moment to escalate an argument into a formal vote?

        Only when an argument already exists. Manufacturing one out of a quiet
        conversation is a bot being random, which is the opposite of the joke.
        """
        if not POLL_ENABLED:
            return False
        if decide.is_poll_request(message.clean_content):
            return True
        if POLL_DAILY_MAX and self._polls_today >= POLL_DAILY_MAX:
            return False
        if not decide.looks_like_a_dispute(transcript.splitlines()):
            return False
        return random.random() <= POLL_CHANCE

    async def _send_poll(self, channel, text: str) -> bool:
        """Turn a parsed reply into a real Discord poll. False if it wasn't one."""
        parsed = decide.parse_poll(text)
        if not parsed:
            log.info("Model did not return a usable poll; sending as text")
            return False
        question, answers = parsed

        poll = discord.Poll(
            question=question, duration=datetime.timedelta(hours=POLL_HOURS)
        )
        for answer in answers:
            poll.add_answer(text=answer)
        try:
            sent = await channel.send(poll=poll)
        except discord.HTTPException:
            log.exception("Discord rejected the poll")
            return False

        self._polls_today += 1
        # Remembered so we can be told about it when it goes against us.
        self._open_polls.append(sent.id)
        self._save_day()
        log.info("Posted poll %r with %d options", question[:60], len(answers))
        return True

    async def _check_polls(self, channel) -> None:
        """Notice when a poll we started has finished badly.

        Only losses are worth a message. Winning a vote you called yourself is
        not a story.
        """
        if not self._open_polls:
            return
        still_open = []
        for message_id in list(self._open_polls):
            try:
                message = await channel.fetch_message(message_id)
            except discord.HTTPException:
                continue  # deleted or unreachable; drop it
            poll = message.poll
            if poll is None:
                continue
            if not poll.is_finalised():
                still_open.append(message_id)
                continue

            winner = poll.victor_answer
            # Our position is always the first option, by construction.
            ours = poll.answers[0] if poll.answers else None
            if winner is None or ours is None or winner.id == ours.id:
                continue
            log.info("Lost a poll: %r beat %r", winner.text, ours.text)
            result = (
                f"{winner.text} ({winner.vote_count} votes) beat "
                f"{ours.text} ({ours.vote_count})"
            )
            transcript, speakers = await self.read_transcript(channel)
            line = await self.generate(
                transcript,
                instruction=POLL_LOST_PROMPT.format(result=result),
                speakers=speakers,
            )
            if line:
                await channel.send(line[:MAX_DISCORD_CHARS])
        self._open_polls = still_open
        self._save_day()

    def _art_instruction(self, message: discord.Message) -> str | None:
        """ASCII art, if this is the moment for it.

        Always on request. Unprompted it is rationed hard and only fires on a
        question trivial enough that a diagram in reply is absurd - the effort
        being out of all proportion is the whole joke, and it stops being
        disproportionate the second time in a day.
        """
        if not ART_ENABLED:
            return None
        text = message.clean_content

        if decide.is_art_request(text):
            log.info("ASCII art requested")
            return ASCII_ART_PROMPT.format(ask=f"They asked: {text.strip()}")

        if ART_DAILY_MAX and self._art_today >= ART_DAILY_MAX:
            return None
        if not decide.is_trivial_question(text, ART_TRIVIAL_MAX_WORDS):
            return None
        if random.random() > ART_OVERKILL_CHANCE:
            return None
        log.info("Answering a trivial question with a diagram (%d/%d today)",
                 self._art_today + 1, ART_DAILY_MAX)
        return ASCII_ART_PROMPT.format(ask=ART_OVERKILL_INSTRUCTION)

    def _patch_notes_instruction(self) -> str:
        """Real commits if there are any, otherwise the brush-off."""
        changes = changelog.summarise(
            changelog.recent_commits(PATCH_NOTES_HOURS, cwd=ROOT)
        )
        if not changes:
            log.info("Patch notes requested; nothing shipped in %dh", PATCH_NOTES_HOURS)
            return NO_UPDATES_PROMPT
        log.info("Patch notes requested; %d changes to report", changes.count("\n") + 1)
        return PATCH_NOTES_PROMPT.format(changes=changes)

    def _direct_question(self, message: discord.Message) -> bool:
        """Addressed to us, and shaped like a question."""
        if not self._addressed_to_me(message):
            return False
        return decide.is_question(message.clean_content, self._my_names(message))

    def _my_names(self, message: discord.Message) -> set[str]:
        """Every name this bot answers to in this channel.

        self.user.display_name is the global name; inside a guild the bot is
        usually addressed by its per-guild nickname, which is a different
        string entirely.
        """
        names = {fold(self.user.name or ""), fold(self.user.display_name)}
        guild = getattr(message.channel, "guild", None)
        me = getattr(guild, "me", None)
        if me is not None:
            names.add(fold(me.display_name))
        names |= {fold(a) for a in BOT_ALIASES}
        return {n for n in names if n}

    def _addressed_to_me(self, message: discord.Message) -> bool:
        if self._mentioned_me(message):
            return True
        text = fold(message.clean_content)
        return any(name in text for name in self._my_names(message))

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

        Only applies to conversations we aren't already in - once we've spoken,
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
        ally = self._is_ally(message)
        if self._addressed_to_me(message):
            base = REPLY_CHANCE_ADDRESSED
            reason = "addressed to me"
        elif ally:
            base = REPLY_CHANCE_ALLY
            reason = "ally"
        elif counterpart or message.author.bot:
            base = REPLY_CHANCE_COUNTERPART
            reason = "counterpart"
        else:
            base = REPLY_CHANCE_HUMAN
            reason = "human"

        if mine and others_since_me == 0 and not ally:
            reason += ", I spoke last"
        if mine > 1:
            reason += f", {mine}/6 recent are mine"

        base = decide.reply_chance(
            base=base,
            mine=mine,
            others_since_me=others_since_me,
            exempt_from_last_speaker=ally,
            decay_last_speaker=REPLY_DECAY_IF_LAST_SPEAKER,
            decay_dominating=REPLY_DECAY_IF_DOMINATING,
        )
        log.info("Reply chance %.2f (%s)", base, reason)
        return base

    async def _respond_like_a_person(self, message, counterpart: bool) -> bool:
        """Decide, wait, then answer - or quietly don't."""
        mine, others_since_me = await self._recent_mix(message)

        # A direct @mention is a question with our name on it. Answer it -
        # no dice roll, no hanging back, no decay for having just spoken.
        if self._mentioned_me(message):
            log.info("Directly mentioned; answering")
        elif self._is_ally(message):
            # Making a friend wait four messages to be acknowledged is the one
            # thing hanging back must never do.
            chance = await self._reply_chance(
                message, counterpart, mine, others_since_me
            )
            if random.random() > chance:
                log.info("Not engaging with this one")
                self._react_later(message)
                return False
        elif (
            self._direct_question(message)
            or self._wants_patch_notes(message)
            or (ART_ENABLED and decide.is_art_request(message.clean_content))
            or (POLL_ENABLED and decide.is_poll_request(message.clean_content))
        ):
            # Adjacency pairs: a question aimed at us makes an answer
            # conditionally relevant, and a missing second part is conspicuous.
            # Hanging back through one doesn't read as staying quiet, it reads
            # as dodging - so questions skip the wait and roll immediately.
            log.info("Direct question; not hanging back")
            chance = await self._reply_chance(
                message, counterpart, mine, others_since_me
            )
            if random.random() > chance:
                log.info("Not engaging with this one")
                self._react_later(message)
                return False
        elif self._hang_back(mine):
            # Hanging back and reacting is exactly right: we're reading the
            # room, just not taking the floor yet.
            self._react_later(message)
            return False
        else:
            chance = await self._reply_chance(
                message, counterpart, mine, others_since_me
            )
            if random.random() > chance:
                log.info("Not engaging with this one")
                self._react_later(message)
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
        transcript, speakers = await self.read_transcript(channel)
        if self._wants_poll(message, transcript):
            drafted = await self.generate(
                transcript, instruction=POLL_PROMPT, speakers=speakers
            )
            if drafted and await self._send_poll(channel, drafted):
                return True
            # Fell through: not a usable poll, so carry on as a normal reply.

        art = self._art_instruction(message)
        if self._wants_patch_notes(message):
            reply = await self.generate(
                transcript,
                instruction=self._patch_notes_instruction(),
                speakers=speakers,
            )
        elif art:
            reply = await self.generate(
                transcript, instruction=art, speakers=speakers
            )
            if reply:
                self._art_today += 1
        else:
            reply = await self.generate(
                transcript, may_stay_silent=True, speakers=speakers
            )
        if not reply:
            return False
        if reply.strip().startswith(PASS_TOKEN):
            log.info("Chose to stay silent")
            self._react_later(message)
            return False

        # Then "type" it at a human rate.
        typing_time = min(len(reply) / TYPING_CPS, TYPING_SECONDS_MAX)
        async with channel.typing():
            await asyncio.sleep(typing_time)
            await channel.send(reply[:MAX_DISCORD_CHARS])
        log.info("Posted %d chars after %.1fs typing", len(reply), typing_time)
        self._react_later(message, replied=True)
        return True

    async def _maybe_open(self):
        """Occasionally start a conversation when the channel has gone quiet."""
        if self._busy.locked():
            return
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)

        last = None
        async for msg in channel.history(limit=1):
            last = msg
        # Don't talk into the void twice in a row - if the last word was ours,
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
            log.info("Channel quiet %.1fh - skipping this opener", quiet_hours)
            return

        async with self._busy:
            log.info("Channel quiet %.1fh - opening a conversation", quiet_hours)
            try:
                async with channel.typing():
                    transcript, speakers = await self.read_transcript(channel)
                    line = await self.generate(
                        transcript, instruction=OPENER_PROMPT, speakers=speakers
                    )
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
            transcript, speakers = await self.read_transcript(channel)
            line = await self.generate(
                transcript, instruction=BRUSH_OFF_PROMPT, speakers=speakers
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
            transcript, speakers = await self.read_transcript(channel)
            line = await self.generate(
                transcript,
                instruction=POKE_PROMPT.format(target=target),
                speakers=speakers,
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

    async def _poll_tick(self):
        """Fold the finished-poll check into a timer that already exists."""
        try:
            channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(
                CHANNEL_ID
            )
            await self._check_polls(channel)
        except Exception:
            log.exception("Poll check failed")

    async def _idle_tick(self):
        # The finished-poll check rides the same timer rather than adding a
        # second loop; both want to run every IDLE_CHECK_MINUTES.
        await self._poll_tick()
        try:
            await self._maybe_open()
        except Exception:
            log.exception("Idle check failed; will retry next tick")

    async def _scheduled_post(self):
        try:
            await self.speak()
        except Exception:
            # Never let one bad turn kill the loop - it has to survive until tomorrow.
            log.exception("Scheduled post failed; will try again at the next slot")

    async def speak(self, may_stay_silent: bool = False) -> bool:
        """Post one in-character message. Returns True if something was sent."""
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)
        transcript, speakers = await self.read_transcript(channel)
        reply = await self.generate(transcript, may_stay_silent, speakers=speakers)
        if not reply:
            log.warning("Model returned no text; nothing posted")
            return False
        if may_stay_silent and reply.strip().startswith(PASS_TOKEN):
            log.info("Chose to stay silent")
            return False
        await channel.send(reply[:MAX_DISCORD_CHARS])
        log.info("Posted %d chars to #%s", len(reply), channel.name)
        return True

    async def read_transcript(self, channel) -> tuple[str, set[int]]:
        """Render recent history oldest-first, and note who's in the room.

        The author ids come back with the text so the brain can load profiles
        for exactly the people present, rather than everyone Jaq has ever met.
        """
        lines = []
        speakers: set[int] = set()
        async for msg in channel.history(limit=HISTORY_LIMIT):
            text = msg.clean_content.strip()
            if not text:
                continue
            if msg.author.id != self.user.id:
                speakers.add(msg.author.id)
                if BRAIN_ENABLED and brain.note_seen(
                    msg.author.id, msg.author.display_name, msg.author.name
                ):
                    log.info(
                        "First time meeting %s - noted for the next brain scan",
                        msg.author.display_name,
                    )
            who = "You" if msg.author.id == self.user.id else msg.author.display_name
            stamp = msg.created_at.astimezone(TIMEZONE).strftime("%a %H:%M")
            lines.append(f"[{stamp}] {who}: {text}")
        lines.reverse()
        return "\n".join(lines), speakers

    async def generate(
        self,
        transcript: str,
        may_stay_silent: bool = False,
        instruction: str | None = None,
        speakers: set[int] | None = None,
    ) -> str:
        framing = FRAMING + (SILENCE_OPTION if may_stay_silent else "")
        system = self.persona
        if self.psychology:
            system = f"{system}\n\n---\n\n{self.psychology}"
        if self.vocab:
            system = f"{system}\n\n---\n\n{self.vocab}"
        system = f"{system}\n\n---\n\n{framing}"
        if BRAIN_ENABLED:
            try:
                notes = brain.load_for(speakers or set())
            except Exception:
                log.exception("Brain failed to load; carrying on without it")
                notes = ""
            if notes:
                system = f"{system}\n\n---\n\n{notes}"
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
        log.error("Discord rejected the token - check DISCORD_TOKEN in .env")
        return 1
    except asyncio.CancelledError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
