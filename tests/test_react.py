"""Reaction budget, rotation, and the guards around picking one."""

from __future__ import annotations

import asyncio
import types

import pytest

from conftest import FakeMessage


class FakeEmoji:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return f"<:{self.name}:1>"


class FakeGuild:
    def __init__(self, names):
        self.emojis = [FakeEmoji(n) for n in names]


class FakeChannel:
    def __init__(self, names=("kek", "bcb", "jfv", "rip")):
        self.guild = FakeGuild(names)


def message_in_guild(author, content="something happened", names=None):
    m = FakeMessage(author, content)
    m.channel = FakeChannel(names) if names is not None else FakeChannel()
    m.added = []

    async def add_reaction(emoji):
        m.added.append(str(emoji))

    m.add_reaction = add_reaction
    return m


def run_react(bot, message, replied=False, pick="kek", delays=True):
    """Drive _maybe_react with the model call and the sleep stubbed out."""
    async def fake_pick(channel, names):
        message.offered = list(names)
        return pick

    bot._pick_reaction = fake_pick
    if not delays:
        pass
    return asyncio.run(bot._maybe_react(message, replied))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch, bot_module):
    """Reactions deliberately wait up to REACT_DELAY_MAX before landing."""
    async def instant(_):
        return None

    monkeypatch.setattr(bot_module.asyncio, "sleep", instant)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)  # always react


# --- guards -----------------------------------------------------------------


def test_empty_message_is_never_reacted_to(persona_bot, stranger):
    """Attachments and bare embeds arrive with no text; a reaction chosen from
    nothing is a coin flip."""
    m = message_in_guild(stranger, content="   ")
    run_react(persona_bot, m)
    assert m.added == []


def test_reaction_lands_on_a_normal_message(persona_bot, stranger):
    m = message_in_guild(stranger)
    run_react(persona_bot, m)
    assert len(m.added) == 1


def test_pass_from_the_model_reacts_with_nothing(persona_bot, stranger):
    m = message_in_guild(stranger)
    run_react(persona_bot, m, pick=None)
    assert m.added == []


def test_unknown_emote_is_rejected(persona_bot, stranger):
    """The model can answer with something that isn't on the menu."""
    m = message_in_guild(stranger)
    run_react(persona_bot, m, pick="not_a_real_emote")
    assert m.added == []


def test_disabled_by_config(persona_bot, stranger, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "REACT_ENABLED", False)
    m = message_in_guild(stranger)
    run_react(persona_bot, m)
    assert m.added == []


# --- budget -----------------------------------------------------------------


def test_reaction_spends_budget(persona_bot, stranger):
    persona_bot._reactions_today = 0
    run_react(persona_bot, message_in_guild(stranger))
    assert persona_bot._reactions_today == 1


def test_budget_exhaustion_stops_reactions(persona_bot, stranger, bot_module):
    persona_bot._reactions_today = bot_module.REACT_DAILY_MAX
    m = message_in_guild(stranger)
    run_react(persona_bot, m)
    assert m.added == []


def test_failed_reaction_hands_the_slot_back(persona_bot, stranger, bot_module):
    """The slot is claimed before the delay, so a failure has to release it or
    the budget leaks on every error."""
    import discord

    m = message_in_guild(stranger)

    async def boom(_):
        # HTTPException formats status/reason off the response object.
        response = types.SimpleNamespace(status=403, reason="Forbidden")
        raise discord.HTTPException(response, "missing permissions")

    m.add_reaction = boom
    persona_bot._reactions_today = 0
    run_react(persona_bot, m)
    assert persona_bot._reactions_today == 0


def test_budget_claimed_before_the_delay(persona_bot, stranger, bot_module, monkeypatch):
    """Concurrent reactions must not all pass the same budget check.

    The cap used to be checked, then the task slept up to REACT_DELAY_MAX
    before incrementing - so every in-flight task saw the same count.
    """
    seen_during_sleep = []

    async def spy_sleep(_):
        seen_during_sleep.append(persona_bot._reactions_today)

    monkeypatch.setattr(bot_module.asyncio, "sleep", spy_sleep)
    persona_bot._reactions_today = 0
    run_react(persona_bot, message_in_guild(stranger))

    assert seen_during_sleep == [1], "slot must already be claimed while waiting"


# --- rotation ---------------------------------------------------------------


def test_recent_picks_are_remembered(persona_bot, stranger):
    run_react(persona_bot, message_in_guild(stranger), pick="kek")
    assert "kek" in persona_bot._recent_reactions


def test_recent_picks_are_withheld_from_the_model(persona_bot, stranger):
    """Custom emote names are opaque, so left to itself the model reaches for
    the one it recognises and stamps it on everything."""
    persona_bot._recent_reactions.extend(["kek", "bcb"])
    m = message_in_guild(stranger)
    run_react(persona_bot, m, pick="jfv")
    assert "kek" not in m.offered
    assert "bcb" not in m.offered
    assert "jfv" in m.offered


def test_recency_memory_is_bounded(persona_bot, bot_module):
    for i in range(50):
        persona_bot._recent_reactions.append(f"e{i}")
    assert len(persona_bot._recent_reactions) == bot_module.REACT_RECENT_MEMORY


def test_standard_emoji_offered_alongside_custom(persona_bot, stranger):
    m = message_in_guild(stranger)
    run_react(persona_bot, m, pick="kek")
    assert "💀" in m.offered, "stock fallbacks should still be on the menu"


def test_custom_emotes_are_offered(persona_bot, stranger):
    m = message_in_guild(stranger, names=["brigade", "icecoldmilk"])
    run_react(persona_bot, m, pick="brigade")
    assert "brigade" in m.offered and "icecoldmilk" in m.offered
