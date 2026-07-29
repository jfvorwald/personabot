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
import io
import logging
import os
import random
import signal
import sys
import json
import time
import unicodedata
from collections import deque
import datetime
from datetime import time as dtime

import anthropic
import discord
from discord.ext import tasks

import brain
import changelog
import contexts
import decide
import guard
import imagegen
import improve
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
    CONFIDENTIALITY,
    PATCH_NOTES_PROMPT,
    POLL_LOST_PROMPT,
    POLL_PROMPT,
    FALLBACK_BRUSH_OFF,
    FRAMING,
    IMAGE_BRIEF_PROMPT,
    IMAGE_BRIEF_RETRY,
    IMAGE_COMMISSIONED,
    IMAGE_CONTEXT,
    IMAGE_DECLINED,
    IMAGE_OPTION,
    MAX_DISCORD_CHARS,
    OBEY_PROMPT,
    PICTURE_INTENT_PROMPT,
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
        # Per-person spend for today, keyed by Discord user id as a string
        # because that is what survives a round trip through JSON.
        self._replies_by_person: dict[str, int] = {}
        self._reply_day = None
        self._daily_budget = 0
        self._brushed_off_today = False
        self._busy = asyncio.Lock()
        self._hang_back_target = 0
        self._messages_waited = 0
        self._reactions_today = 0
        self._art_today = 0
        self._polls_today = 0
        self._open_polls: list[int] = []
        self._openers_today = 0
        self._unanswered_openers = 0
        self._images_today = 0
        # Per person, keyed by Discord user id as a string - a shared counter
        # means the first person to use it up decides how many pictures
        # everyone else gets, and they never find out why.
        self._images_by_person: dict[str, int] = {}
        # Epoch seconds, not monotonic: the cooldown has to survive a restart,
        # and a monotonic clock restarts with the process.
        self._last_image_at = 0.0
        self._last_image_by_person: dict[str, float] = {}
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
        """Persist today's spend. Cheap, and it runs only when we post.

        Refuses to write before a day has been established. `str(None)` is a
        perfectly valid JSON string that matches no date, so a save from a bot
        that never restored or rolled leaves a file the next startup silently
        rejects - and a rejected file means a fresh budget mid-day. A one-off
        script did exactly that and reset an evening's counters.
        """
        if self._reply_day is None:
            log.warning("Refusing to save state before the day is set")
            return
        try:
            with open(self._state_path(), "w") as f:
                json.dump(
                    {
                        "day": str(self._reply_day),
                        "replies": self._replies_today,
                        "by_person": self._replies_by_person,
                        "reactions": self._reactions_today,
                        "art": self._art_today,
                        "polls": self._polls_today,
                        "open_polls": self._open_polls,
                        "openers": self._openers_today,
                        "images": self._images_today,
                        "images_by_person": self._images_by_person,
                        "last_image_at": self._last_image_at,
                        "last_image_by_person": self._last_image_by_person,
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
        self._replies_by_person = state.get("by_person", {}) or {}
        self._reactions_today = state.get("reactions", 0)
        self._art_today = state.get("art", 0)
        self._polls_today = state.get("polls", 0)
        self._open_polls = state.get("open_polls", [])
        self._openers_today = state.get("openers", 0)
        self._images_today = state.get("images", 0)
        self._images_by_person = state.get("images_by_person", {}) or {}
        self._last_image_by_person = state.get("last_image_by_person", {}) or {}
        # Carried across the restart so redeploying is not a way to skip the
        # cooldown, the same reason the reply budget is persisted at all.
        self._last_image_at = state.get("last_image_at", 0.0)
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
        self._replies_by_person = {}
        self._reactions_today = 0
        self._art_today = 0
        # Was omitted here, so the poll budget only ever refilled on a restart:
        # a process that stayed up for a week got two polls for the week.
        self._polls_today = 0
        self._openers_today = 0
        self._unanswered_openers = 0
        self._images_today = 0
        self._images_by_person = {}
        # Deliberately NOT cleared: a picture at 23:58 should not be followed
        # by another at 00:01 just because the date rolled.
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

    def _hard_capped(self, message=None) -> bool:
        """Past the ceiling that a mention does not cross.

        The daily budget is soft on purpose - being @mentioned by name and
        being spoken to by a friend both bypass it, which is what stops the
        rationing from ever reading as blanking someone. The cost is that a
        busy day has no upper bound at all, and one ran 60% over.

        Allies are the exception, and the only one. Jack owns this thing, and
        a ceiling meant to stop a room full of people running up a bill should
        not be the reason the person who built it gets ignored.
        """
        if message is not None and self._is_ally(message):
            return False
        if self._daily_budget is None or LIVE_HARD_CAP_MULTIPLIER <= 0:
            return False
        return self._replies_today >= self._daily_budget * LIVE_HARD_CAP_MULTIPLIER

    def _person_capped(self, message) -> bool:
        """Has this one person already had their share of the day?

        Every other cap is shared, so one person in a long back-and-forth can
        drain the day and leave everyone else with a bot that has nothing left
        for them. This one is per-person, so running out is something you do
        to yourself rather than to the room.
        """
        if LIVE_PER_PERSON_MAX <= 0 or self._is_ally(message):
            return False
        spent = self._replies_by_person.get(str(message.author.id), 0)
        return spent >= LIVE_PER_PERSON_MAX

    async def setup_hook(self):
        """Catch SIGTERM so a deploy does not kill a reply in progress.

        Restarting on every change is the workflow here, so this collides with
        the bot constantly: it was three seconds into generating a picture Jack
        had asked for when a deploy killed it, and from the channel that looked
        exactly like the feature being broken again.

        discord.py installs no handler of its own, so SIGTERM terminates the
        process wherever it happens to be.
        """
        loop = asyncio.get_running_loop()
        for name in ("SIGTERM", "SIGINT"):
            try:
                loop.add_signal_handler(
                    getattr(signal, name), lambda: asyncio.create_task(self._wind_down())
                )
            except (NotImplementedError, AttributeError, ValueError):
                # Windows, or a loop that will not take handlers. The old
                # behaviour - dying immediately - is the fallback.
                pass

    async def _wind_down(self) -> None:
        """Finish what is in flight, then close. Bounded, so a stuck reply
        cannot hold a deploy open forever."""
        if getattr(self, "_closing", False):
            return
        self._closing = True
        if self._busy.locked():
            log.info("Shutdown: waiting for the reply in progress")
            try:
                await asyncio.wait_for(self._busy.acquire(), timeout=SHUTDOWN_GRACE)
                self._busy.release()
                log.info("Shutdown: in-flight reply finished")
            except asyncio.TimeoutError:
                log.warning(
                    "Shutdown: reply still running after %gs; closing anyway",
                    SHUTDOWN_GRACE,
                )
        # Pictures render outside the lock, so wait on them separately.
        pending = [t for t in self._pending if not t.done()]
        if pending:
            log.info("Shutdown: waiting for %d background task(s)", len(pending))
            await asyncio.wait(pending, timeout=SHUTDOWN_GRACE)
        log.info("Shutdown: closing")
        await self.close()

    async def on_ready(self):
        log.info(
            "Logged in as %s (id=%s) running %s",
            self.user,
            self.user.id,
            changelog.version(cwd=ROOT),
        )
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
                "Mentions: answered past the budget, up to %s. "
                "Joining: after %d-%d messages, giving up past %d.",
                "no limit" if LIVE_UNLIMITED or LIVE_HARD_CAP_MULTIPLIER <= 0
                else f"{LIVE_HARD_CAP_MULTIPLIER:g}x the day's budget",
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
            log.info(
                "Pictures: %s",
                f"{GEMINI_IMAGE_MODEL}, offered on {IMAGE_BASE_RATE:.0%} of "
                f"replies, max {IMAGE_PER_PERSON_MAX or '∞'}/person/day "
                f"({IMAGE_DAILY_MAX or '∞'} channel backstop), "
                f"{IMAGE_COOLDOWN_SECONDS:.0f}s apart per person"
                if IMAGE_ENABLED and imagegen.available(GEMINI_KEY)
                else "off (no JAQ_GEMINI_KEY)"
                if IMAGE_ENABLED
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
                    "%.0f%% chance, max %s/day, %d unanswered in a row",
                    IDLE_CHECK_MINUTES,
                    IDLE_HOURS,
                    IDLE_CHANCE * 100,
                    IDLE_DAILY_MAX or "∞",
                    IDLE_MAX_UNANSWERED,
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
            # One person having spent their own share is not the room running
            # out, so it is silent - there is no sign-off owed to someone who
            # has already had a dozen replies today.
            ordered = self._ordered(message)
            if ordered:
                log.info("ORDER from %s; complying", message.author.display_name)
            if not ordered and self._person_capped(message):
                log.info(
                    "%s has had their %d for today; ignoring",
                    message.author.display_name,
                    LIVE_PER_PERSON_MAX,
                )
                return
            if not ordered and (
                self._hard_capped(message) or (self._out_of_budget() and not exempt)
            ):
                capped = self._hard_capped(message)
                if self._brushed_off_today:
                    log.info(
                        "%s for today (%d replies); ignoring",
                        "Hard capped" if capped else "Out of replies",
                        self._replies_today,
                    )
                    return
                # A day spent entirely on mentions and allies never trips the
                # soft cap, so this can be the first thing anyone hears about
                # it. Say something once, then go quiet.
                self._brushed_off_today = True
                log.info(
                    "%s at %d replies; sending sign-off",
                    "Hard cap reached" if capped else f"Budget of {self._daily_budget} used up",
                    self._replies_today,
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
                who = str(message.author.id)
                self._replies_by_person[who] = self._replies_by_person.get(who, 0) + 1
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

    def _ordered(self, message) -> bool:
        """A direct order, from the one account allowed to give them.

        Two conditions, both required. Id first, because ids never change and
        display names do - a rule keyed on a name silently stopped matching in
        this project once already, and that one leaked a profile.
        """
        if message is None or not decide.is_obey_order(message.clean_content):
            return False
        author = message.author
        if OBEY_IDS and str(author.id) in OBEY_IDS:
            return True
        if OBEY_IDS:
            # Ids are configured and this is not one of them. A handle match
            # would be a way around the id check, so there isn't one.
            return False
        return decide.name_matches(
            {getattr(author, "name", ""), getattr(author, "display_name", "")},
            OBEY_HANDLES,
        )

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

    def _offer_image(self, message, asked_outright: bool = False) -> str:
        """Should this reply even be allowed to carry a picture?

        Jaq is the author of his pictures, not a renderer people can operate.
        The strongest form of that is structural: a message that asks for a
        picture is never offered one, so there is no wording that gets a
        commission filled, because the option was never on the table.

        That rule exists because the softer version failed in the channel.
        Told in the prompt to describe pictures in his own terms, he was given
        an exact description in quotes and drew it, lightly reworded. An
        instruction is a request; a closed door is not.

        Jack is the exception and the only one. He owns this thing, so when he
        asks he gets one, and he skips the dice as well as the door - being
        told no eight times out of ten is the same as it not working.

        Gates run cheapest first and all close before any money is spent:
        configured at all, nobody else angling for one, budget, cooldown, then
        a dice roll. Only past all of them does the model learn the option
        exists, and it still usually declines - which is the point.
        """
        if not (IMAGE_ENABLED and imagegen.available(GEMINI_KEY)):
            return ""

        asked = message.clean_content if message is not None else ""
        ally = message is not None and self._is_ally(message)
        # An ally asking outright is the one case that bypasses both the door
        # and the dice. Everything below still applies: he can ask, he cannot
        # conjure budget that is spent.
        #
        # is_art_request as well as is_picture_request, because "draw me a dog"
        # names no picture noun and is the obvious way to ask. Asking for ASCII
        # by name still means ASCII - the older surface must not vanish the day
        # the newer one arrives.
        commissioned = (
            ally
            and not decide.wants_ascii(asked)
            and (
                asked_outright
                or decide.is_picture_request(asked)
                or decide.is_art_request(asked)
            )
        )
        if not commissioned:
            if decide.is_picture_request(asked):
                log.info("Someone asked for a picture, so there won't be one")
                return ""
            if decide.mentions_a_picture(asked):
                log.info("Message is about pictures; not offering one")
                return ""

        # Both limits are per person. A shared counter means the first person
        # to use it up decides how many pictures everyone else gets, and the
        # people who lose out never find out why - they just see a bot that
        # stopped working. Waiting out somebody else's cooldown is the same
        # complaint in miniature.
        #
        # Neither limit describes Jack asking for a specific picture, so a
        # commission clears both. A request of his that silently produces
        # nothing cannot be told apart from the thing being broken, which is
        # how it read when "Picture intent: YES" was followed immediately by
        # "cooling down (507s left)". Spend is still counted and still logged.
        who = str(message.author.id) if message is not None else ""
        last = self._last_image_by_person.get(who, 0.0)
        since = time.time() - last if last else float("inf")
        blocked = (
            None
            if commissioned
            else decide.image_blocked(
                spent=self._images_by_person.get(who, 0),
                cap=IMAGE_PER_PERSON_MAX,
                seconds_since_last=since,
                cooldown=IMAGE_COOLDOWN_SECONDS,
            )
        )
        # An overall backstop against a runaway, not the rationing mechanism.
        if (
            blocked is None
            and not commissioned
            and IMAGE_DAILY_MAX
            and self._images_today >= IMAGE_DAILY_MAX
        ):
            blocked = f"channel backstop reached ({self._images_today}/{IMAGE_DAILY_MAX})"
        if blocked:
            # Logged at debug when nobody asked: at a ten minute cooldown that
            # is the common case and would otherwise be most of the log. When
            # someone did ask, the silence needs explaining.
            log.log(
                logging.INFO if commissioned else logging.DEBUG,
                "No picture offered - %s", blocked,
            )
            return ""
        if not commissioned and random.random() > IMAGE_BASE_RATE:
            return ""
        log.info(
            "Offering a picture on this reply%s (%s has spent %d/%s today)",
            " (asked for it)" if commissioned else "",
            getattr(message.author, "display_name", "?") if message else "?",
            self._images_by_person.get(who, 0),
            IMAGE_PER_PERSON_MAX or "∞",
        )
        # The caller needs to know which of these it is: a commission outranks
        # the ASCII path, a rolled offer does not.
        return "commissioned" if commissioned else "rolled"

    async def _asks_for_a_picture(self, transcript: str, asked: str) -> bool:
        """Is the last message asking for a picture? Allies only.

        Wordlists cannot cover how people ask. Three phrasings were missed
        live - "draw me a dog" names no picture noun, "create a picture of"
        used a verb that was not listed, "imagine X in azeroth" matched
        nothing at all - and every miss looks from the outside like the
        feature is broken rather than like a rule being applied.

        So for the one person allowed to commission a picture, the question
        gets asked properly. One small call, a handful of tokens, on ally
        messages only. Strangers stay on the wordlist, where a false negative
        is the desired outcome anyway.
        """
        # The message being judged has to be named explicitly. The transcript
        # is read after the think delay, so anything said in those seconds is
        # now its last line - which is how a request got judged as "no", the
        # classifier having been shown somebody else's message.
        content = (
            f"Conversation so far, for context only:\n\n{transcript[-2000:]}\n\n"
            f"---\n\nThe message to judge:\n\n{asked.strip()[:800]}"
        )
        try:
            response = await self.claude.messages.create(
                model=MODEL,
                max_tokens=5,
                system=PICTURE_INTENT_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            log.exception("Picture-intent check failed; assuming no")
            return False
        answer = "".join(
            b.text for b in response.content if b.type == "text"
        ).strip().upper()
        wants = answer.startswith("YES")
        # Always logged: a silent no is indistinguishable from the feature
        # being broken, which is exactly how this looked from the channel.
        log.info(
            "Picture intent: %s for %r", "YES" if wants else "no", asked.strip()[:90]
        )
        return wants

    async def _commission_brief(self, transcript: str, speakers, retry: bool = False) -> str:
        """Ask for the picture's description on its own.

        A commission cannot depend on the model volunteering a `<<image:>>`
        line inside a chat message. It declined to, twice - once because the
        affordance it was shown opens with "usually don't" - and the person who
        asked got an ordinary sentence and no picture.

        So for an explicit request the description is its own call with its own
        instruction, and the only way it produces nothing is a refusal or the
        guard. Costs one extra Anthropic call on a path that is ally-only and
        rate-limited, which is the right thing to spend to make it reliable.
        """
        instruction = IMAGE_BRIEF_PROMPT + (IMAGE_BRIEF_RETRY if retry else "")
        brief = await self.generate(
            transcript, instruction=instruction, speakers=speakers
        )
        # It was asked for a description and nothing else, but a stray "Sure -"
        # or a wrapping quote is cheap to survive.
        brief = brief.strip().strip('"').strip()
        if brief.lower().startswith(("sure", "here", "okay", "ok,")):
            _, _, rest = brief.partition(":")
            brief = (rest or brief).strip()
        return " ".join(brief.split())

    def _observe(self, kind: str, **fields) -> None:
        """Note what just happened, for the daily self-improvement pass.

        Deliberately cheap: a dict and an appended line, no API call and no
        model. It records the things the channel history cannot show later -
        which path a reply took, what the dice decided, whether the guard
        blocked something - because by tomorrow all that survives in Discord
        is the text.
        """
        if not IMPROVE_ENABLED:
            return
        event = {
            "at": datetime.datetime.now(TIMEZONE).isoformat(timespec="seconds"),
            "kind": kind,
        }
        event.update(fields)
        improve.record(event, at_root(IMPROVE_LOG))

    def _picture_refused(self, message, offered: bool) -> bool:
        """Did someone ask for a picture they are not getting?

        The model needs telling. Left to work it out, it wrote a description of
        a picture as its message and posted it with nothing underneath, which
        is worse than either outcome on its own and is how this failed live.
        """
        if offered or message is None:
            return False
        return decide.is_picture_request(message.clean_content)

    def _image_context(self, transcript: str) -> str:
        """A world to set the picture in, if the room is talking about one.

        Only reached when a picture is already on the table, so the files are
        read on a small fraction of replies rather than on every message.
        Never fatal: a broken context file costs a picture its setting, not the
        reply.
        """
        try:
            chosen = contexts.pick(transcript)
        except Exception:
            log.exception("Context lookup failed; carrying on without one")
            return ""
        if not chosen:
            return ""
        log.info("Picture context: %s", chosen.name)
        return IMAGE_CONTEXT.format(context=chosen.body)

    def _send_image_later(
        self, channel, prompt: str, reason: str, retry=None, who: str = ""
    ) -> None:
        """Render and post a picture without blocking the reply.

        Generation takes tens of seconds. _respond_like_a_person holds the
        one-at-a-time lock, so waiting inline would stall an @mention queued
        behind it for the whole render - the same reason reactions are
        dispatched this way.
        """
        task = asyncio.create_task(
            self._deliver_image(channel, prompt, reason, retry, who)
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _deliver_image(
        self, channel, prompt: str, reason: str, retry=None, who: str = ""
    ) -> None:
        # Claim the slot before the render, not after. Several of these can be
        # in flight at once, and checking the budget then spending a minute
        # generating lets every one of them pass the same check.
        now = time.time()
        self._images_today += 1
        self._last_image_at = now
        if who:
            self._images_by_person[who] = self._images_by_person.get(who, 0) + 1
            self._last_image_by_person[who] = now
        self._save_day()
        log.info(
            "Generating a picture: %s | %s has spent %s, channel %d",
            reason,
            who or "?",
            f"{self._images_by_person.get(who, 0)}/{IMAGE_PER_PERSON_MAX or '∞'}",
            self._images_today,
        )

        data = None
        try:
            data = await imagegen.generate(
                prompt,
                key=GEMINI_KEY,
                model=GEMINI_IMAGE_MODEL,
                timeout=IMAGE_TIMEOUT,
            )
        except Exception:
            log.exception("Image generation raised")

        if not data and retry is not None:
            # The image model refuses some briefs outright. On a commission
            # somebody is waiting for a picture, so a refusal gets exactly one
            # more attempt at a version that survives the filter.
            log.info("Refused; asking for a tamer brief and trying once more")
            try:
                second = await retry()
            except Exception:
                log.exception("Retry brief failed")
                second = ""
            if second and self._image_prompt_is_safe(second):
                log.info("Retry brief: %s", second[:120])
                try:
                    data = await imagegen.generate(
                        second,
                        key=GEMINI_KEY,
                        model=GEMINI_IMAGE_MODEL,
                        timeout=IMAGE_TIMEOUT,
                    )
                except Exception:
                    log.exception("Image generation raised on retry")

        if not data:
            # Hand the daily slot back - nothing was produced, so nothing
            # should be charged for it. The cooldown stands, which stops a run
            # of content-filter refusals turning into a retry loop.
            self._images_today -= 1
            if who and self._images_by_person.get(who):
                self._images_by_person[who] -= 1
            self._save_day()
            log.info("No picture this time; the message went out on its own")
            return

        try:
            await channel.send(
                file=discord.File(io.BytesIO(data), filename="jaq.png")
            )
        except discord.HTTPException:
            # Most likely a missing attach_files permission, or an image over
            # the guild's upload limit. Still silent in the channel.
            log.exception("Could not upload the picture")
            self._images_today -= 1
            if who and self._images_by_person.get(who):
                self._images_by_person[who] -= 1
            self._save_day()
            return
        log.info("Posted a picture (%d KB)", len(data) // 1024)
        self._observe("image", kb=len(data) // 1024, prompt=prompt[:300], who=who)

    def _image_prompt_is_safe(self, prompt: str) -> bool:
        """The image prompt leaves this machine, so it gets the same check.

        Everything the bot says in the channel passes through the guard on the
        way out. This is a second exit, to a third party, carrying text derived
        from a transcript of real people talking - so it is held to the same
        rule rather than trusted for being internal.
        """
        leak = guard.find_leak(
            prompt,
            [DISCORD_TOKEN, os.getenv("ANTHROPIC_API_KEY", ""), GEMINI_KEY],
            REDACT_TERMS,
        )
        if leak is None:
            return True
        log.error("BLOCKED an image prompt containing a %s", leak)
        return False

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
        if self._ordered(message):
            # No roll, no hang-back, no decay. An order that gets dice rolled
            # against it is not an order.
            log.info("Answering an order")
        elif self._mentioned_me(message):
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
        # Decided before the branches so the dice are rolled exactly once, and
        # so a commission can outrank the ASCII path below.
        patch_notes = self._wants_patch_notes(message)
        # Only allies can commission one, so only ally messages are worth the
        # classification call - and only when the free wordlist did not already
        # settle it.
        asked_outright = False
        if (
            not patch_notes
            and IMAGE_ENABLED
            and imagegen.available(GEMINI_KEY)
            and self._is_ally(message)
            and not decide.wants_ascii(message.clean_content)
            and not decide.is_picture_request(message.clean_content)
            and not decide.is_art_request(message.clean_content)
        ):
            asked_outright = await self._asks_for_a_picture(
                transcript, message.clean_content
            )
        image_mode = (
            "" if patch_notes else self._offer_image(message, asked_outright)
        )
        offered_image = bool(image_mode)
        if art and image_mode == "commissioned":
            # Same request, two renderers. The one that makes an actual picture
            # wins; asking for ASCII by name is handled inside _offer_image.
            log.info("Asked for a drawing and can render one; skipping ASCII")
            art = None
        if patch_notes:
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
            # Only ordinary replies can carry a picture. Patch notes and ASCII
            # art are each already a bit with its own shape, and stacking two
            # on one message is a bot showing off what it can do.
            commissioned = image_mode == "commissioned"
            reply = await self.generate(
                transcript,
                may_stay_silent=not commissioned,
                speakers=speakers,
                offer_image=offered_image,
                refuse_image=self._picture_refused(message, offered_image),
                commissioned=commissioned,
                ordered=self._ordered(message),
            )
        # Always strip, even when nothing was offered: models reuse a syntax
        # they have been shown, and "<<image: a dog>>" in the channel would put
        # the machinery in front of everyone.
        reply, image_prompt = decide.extract_image_prompt(reply)

        if image_mode == "commissioned" and not image_prompt:
            # The whole point of a commission: it does not depend on the model
            # deciding to attach something. It was asked for, so it happens.
            image_prompt = await self._commission_brief(transcript, speakers)
            if image_prompt:
                log.info("Commissioned brief: %s", image_prompt[:120])
            else:
                log.warning("Commissioned a picture but got no brief back")

        if not reply and not image_prompt:
            return False

        if image_mode == "commissioned" and image_prompt:
            # Someone asked for a picture, so they get a picture and nothing
            # else. Every remaining failure in this feature has been the model
            # putting words next to the image - a caption, a description, a
            # stage direction narrating it - and none of those survive having
            # no message to write. The picture is the reply.
            if reply:
                log.info("Commissioned: posting the picture on its own")
            reply = ""
        if image_prompt and not offered_image:
            log.info("Model asked for a picture unprompted; dropping it")
            image_prompt = ""
        if image_prompt and not self._image_prompt_is_safe(image_prompt):
            image_prompt = ""
        if image_prompt and reply:
            # Discord shows the picture; narrating it is a bot describing its
            # own output, and the instruction not to has not held.
            trimmed = decide.strip_attachment_notes(reply)
            if trimmed != reply:
                log.info("Stripped an attachment announcement from the reply")
                reply = trimmed
        if image_prompt and reply and decide.looks_like_a_caption(reply, image_prompt):
            # He wrote the art direction out loud instead of saying something.
            # The picture is the good half, so send that on its own - which is
            # how anyone posts a picture anyway.
            log.info("Reply was a caption; posting the picture without it")
            reply = ""

        if reply.strip().startswith(PASS_TOKEN):
            log.info("Chose to stay silent")
            self._observe("pass", to=message.author.display_name)
            self._react_later(message)
            return False
        if not reply and not image_prompt:
            return False

        if reply:
            # Then "type" it at a human rate.
            typing_time = min(len(reply) / TYPING_CPS, TYPING_SECONDS_MAX)
            async with channel.typing():
                await asyncio.sleep(typing_time)
                await channel.send(reply[:MAX_DISCORD_CHARS])
            log.info("Posted %d chars after %.1fs typing", len(reply), typing_time)
            self._observe(
                "reply",
                chars=len(reply),
                path="commission" if image_mode == "commissioned"
                else "art" if art else "patch" if patch_notes else "normal",
                to=message.author.display_name,
                mention=self._mentioned_me(message),
                ally=self._is_ally(message),
                text=reply[:400],
            )
        if image_prompt:
            # Follows a moment later, the way a person sends the picture after
            # the line rather than holding the line back until it renders.
            retry = None
            if image_mode == "commissioned":
                async def retry():
                    return await self._commission_brief(transcript, speakers, retry=True)
            self._send_image_later(
                channel,
                image_prompt,
                reason=image_prompt[:120],
                retry=retry,
                who=str(message.author.id),
            )
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
        # Speaking into the void is allowed, but not indefinitely. A person who
        # has gone unanswered twice stops; the old rule stopped after one,
        # which meant a channel quiet overnight got a single opener and then
        # silence no matter how long it stayed quiet.
        if last is not None and last.author.id == self.user.id:
            if self._unanswered_openers >= IDLE_MAX_UNANSWERED:
                return
        else:
            self._unanswered_openers = 0

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
        # Openers spend their own budget, not the day's replies. Sharing one
        # meant a busy afternoon left nothing to open the evening with.
        if IDLE_DAILY_MAX and self._openers_today >= IDLE_DAILY_MAX:
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
                self._openers_today += 1
                self._unanswered_openers += 1
                self._observe("opener", quiet_hours=round(quiet_hours, 1), chars=len(line))
                log.info(
                    "Opened a thread (%d/%s openers today, %d unanswered)",
                    self._openers_today,
                    IDLE_DAILY_MAX or "∞",
                    self._unanswered_openers,
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

    def _safe_to_send(self, text: str) -> bool:
        """Refuse to post anything carrying a credential or a forbidden name.

        The prompt asks the model to keep these back. This is what happens when
        asking is not enough, which over a long enough run it will not be.
        Silence is the correct failure here - a message explaining that
        something was withheld is itself a disclosure.
        """
        leak = guard.find_leak(text, [DISCORD_TOKEN, os.getenv("ANTHROPIC_API_KEY", "")],
                               REDACT_TERMS)
        if leak is None:
            return True
        log.error("BLOCKED an outgoing message containing a %s", leak)
        self._observe("blocked", what=leak)
        return False

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
        offer_image: bool = False,
        refuse_image: bool = False,
        commissioned: bool = False,
        ordered: bool = False,
    ) -> str:
        # "You may decline to answer" and "carry this out now" cannot both be
        # in one prompt, so an order replaces the silence option rather than
        # sitting next to it.
        framing = FRAMING + ("" if ordered else SILENCE_OPTION if may_stay_silent else "")
        framing += OBEY_PROMPT if ordered else ""
        if commissioned:
            framing += IMAGE_COMMISSIONED
        elif offer_image:
            framing += IMAGE_OPTION + self._image_context(transcript)
        elif refuse_image:
            framing += IMAGE_DECLINED
        system = self.persona
        if self.psychology:
            system = f"{system}\n\n---\n\n{self.psychology}"
        if self.vocab:
            system = f"{system}\n\n---\n\n{self.vocab}"
        system = f"{system}\n\n---\n\n{framing}"
        system = f"{system}\n\n---\n\n{CONFIDENTIALITY}"
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

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        # Single choke point: every message the bot posts, of every kind, comes
        # back through here, so the guard only has to be applied once.
        if not self._safe_to_send(text):
            return ""
        return text


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
