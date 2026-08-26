"""Openers: when the bot starts a conversation nobody asked for.

The rule is triggered by quiet, which is the whole difficulty - the quietest a
channel ever gets is the middle of the night, so an untended threshold walks
itself there. Across the first 99 openers this bot posted, 35 landed between
23:00 and 08:00 and the busiest single hour of the day was 1am. These tests
pin the three things that were wrong: no waking-hours window, a flat threshold
that never grew, and a counterpart bot's reply counting as having been
answered so two bots held each other's counters at zero.
"""

from __future__ import annotations

import asyncio
import datetime
import types


import decide


UTC = datetime.timezone.utc


# --- the window, as a pure function -----------------------------------------


def test_a_daytime_window_is_half_open():
    assert decide.within_hours(9, 9, 23) is True
    assert decide.within_hours(22, 9, 23) is True
    assert decide.within_hours(23, 9, 23) is False, "end is exclusive"
    assert decide.within_hours(8, 9, 23) is False


def test_the_hours_that_were_the_problem_are_out():
    """1am was the single busiest opener hour under the old settings."""
    for hour in (23, 0, 1, 2, 3, 4, 5, 6, 7):
        assert decide.within_hours(hour, 9, 23) is False, hour


def test_a_window_may_wrap_past_midnight():
    """Someone will want a night owl, and 22-6 must not mean 'never'."""
    for hour in (22, 23, 0, 3, 5):
        assert decide.within_hours(hour, 22, 6) is True, hour
    for hour in (6, 12, 21):
        assert decide.within_hours(hour, 22, 6) is False, hour


def test_start_equal_to_end_is_the_whole_day():
    """A window nobody narrowed must not silently switch openers off."""
    for hour in range(24):
        assert decide.within_hours(hour, 0, 0) is True, hour


# --- the threshold backs off ------------------------------------------------


def test_an_unanswered_opener_makes_the_next_one_wait_longer(
    persona_bot, bot_module, monkeypatch
):
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MIN", 4.0)
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MAX", 4.0)
    monkeypatch.setattr(bot_module, "IDLE_BACKOFF", 2.0)

    persona_bot._unanswered_openers = 0
    persona_bot._draw_idle_target()
    assert persona_bot._idle_target == 4.0

    persona_bot._unanswered_openers = 1
    persona_bot._draw_idle_target()
    assert persona_bot._idle_target == 8.0

    persona_bot._unanswered_openers = 2
    persona_bot._draw_idle_target()
    assert persona_bot._idle_target == 16.0


def test_backoff_of_one_leaves_the_threshold_alone(
    persona_bot, bot_module, monkeypatch
):
    """1.0 is how you turn the backoff off without editing code."""
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MIN", 3.0)
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MAX", 3.0)
    monkeypatch.setattr(bot_module, "IDLE_BACKOFF", 1.0)
    persona_bot._unanswered_openers = 5
    persona_bot._draw_idle_target()
    assert persona_bot._idle_target == 3.0


# --- driving _maybe_open ----------------------------------------------------


class FakeChannel:
    """Only the handful of things _maybe_open touches."""

    def __init__(self, last=None):
        self._last = last
        self.sent = []

    def history(self, limit=1):
        last = self._last

        class _Cursor:
            def __aiter__(self):
                async def gen():
                    if last is not None:
                        yield last

                return gen()

        return _Cursor()

    def typing(self):
        class _Typing:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        return _Typing()

    async def send(self, text):
        self.sent.append(text)


def _message_from(author, hours_ago, now):
    return types.SimpleNamespace(
        author=author,
        created_at=now - datetime.timedelta(hours=hours_ago),
    )


def _arm(bot_obj, bot_module, monkeypatch, *, channel, hour, target=1.0):
    """Wire a bot up so _maybe_open can run without a gateway."""
    now = datetime.datetime(2026, 8, 25, hour, 30, tzinfo=UTC)
    monkeypatch.setattr(bot_module, "TIMEZONE", UTC)
    monkeypatch.setattr(bot_module.discord.utils, "utcnow", lambda: now)
    monkeypatch.setattr(bot_module, "IDLE_CHANCE", 1.0)
    monkeypatch.setattr(bot_module, "IDLE_DAILY_MAX", 99)
    monkeypatch.setattr(bot_module, "IDLE_WINDOW_START", 9)
    monkeypatch.setattr(bot_module, "IDLE_WINDOW_END", 23)
    monkeypatch.setattr(bot_module, "IDLE_MAX_UNANSWERED", 2)

    bot_obj._busy = asyncio.Lock()
    bot_obj._reply_day = now.date()
    bot_obj._idle_target = target
    bot_obj.get_channel = lambda _id: channel
    bot_obj._observe = lambda *a, **k: None

    async def read_transcript(_channel):
        return "transcript", set()

    async def generate(*a, **k):
        return "so anyway"

    bot_obj.read_transcript = read_transcript
    bot_obj.generate = generate
    return now


def test_no_opener_outside_the_window(persona_bot, bot_module, monkeypatch, jack):
    """The 1am case, which no threshold tuning can reach."""
    now = datetime.datetime(2026, 8, 25, 1, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(jack, hours_ago=9, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=1)

    asyncio.run(persona_bot._maybe_open())
    assert channel.sent == [], "opened a conversation at 1:30am"


def test_the_same_silence_inside_the_window_does_open(
    persona_bot, bot_module, monkeypatch, jack
):
    """Same nine hours of quiet, different hour of the day."""
    now = datetime.datetime(2026, 8, 25, 10, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(jack, hours_ago=9, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=10)

    asyncio.run(persona_bot._maybe_open())
    assert channel.sent == ["so anyway"]
    assert persona_bot._openers_today == 1
    assert persona_bot._unanswered_openers == 1


def test_the_counterpart_answering_does_not_count_as_an_answer(
    persona_bot, bot_module, monkeypatch, ben_bot
):
    """Two bots must not hold each other's unanswered counters at zero.

    This is how three openers landed between midnight and 4am: every opener
    drew a reply from the other bot, which cleared the count each time.
    """
    now = datetime.datetime(2026, 8, 25, 14, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(ben_bot, hours_ago=5, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=14)
    persona_bot._unanswered_openers = 2

    asyncio.run(persona_bot._maybe_open())
    assert channel.sent == [], "spoke again after two unanswered, into bot chatter"
    assert persona_bot._unanswered_openers == 2


def test_a_human_speaking_clears_the_count_and_the_backoff(
    persona_bot, bot_module, monkeypatch, zack
):
    """The room woke up, so the next quiet spell starts from scratch."""
    now = datetime.datetime(2026, 8, 25, 14, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(zack, hours_ago=5, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=14)
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MIN", 3.0)
    monkeypatch.setattr(bot_module, "IDLE_HOURS_MAX", 3.0)
    monkeypatch.setattr(bot_module, "IDLE_BACKOFF", 2.0)
    persona_bot._unanswered_openers = 2
    persona_bot._idle_target = 12.0  # backed off from the dead stretch

    asyncio.run(persona_bot._maybe_open())
    # Redrawn at the base rate the moment the count cleared, rather than
    # judging this silence by how dead the previous one was.
    assert persona_bot._unanswered_openers == 1, "one fired, from a cleared count"
    assert channel.sent == ["so anyway"]


def test_quiet_shorter_than_the_threshold_stays_quiet(
    persona_bot, bot_module, monkeypatch, jack
):
    now = datetime.datetime(2026, 8, 25, 14, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(jack, hours_ago=1, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=14, target=6.0)

    asyncio.run(persona_bot._maybe_open())
    assert channel.sent == []


def test_the_daily_cap_binds(persona_bot, bot_module, monkeypatch, jack):
    """It never did before: the old 24 sat well above the 5-7 actually used."""
    now = datetime.datetime(2026, 8, 25, 14, 30, tzinfo=UTC)
    channel = FakeChannel(_message_from(jack, hours_ago=9, now=now))
    _arm(persona_bot, bot_module, monkeypatch, channel=channel, hour=14)
    monkeypatch.setattr(bot_module, "IDLE_DAILY_MAX", 3)
    persona_bot._openers_today = 3

    asyncio.run(persona_bot._maybe_open())
    assert channel.sent == []
