"""Direct messages: a private line to the one person who owns this.

Almost nothing that makes the channel feel like a room applies in a one-to-one.
There is no roll, because nobody else might answer. No hanging back, because
there is no conversation to join. No budget, because the budget exists to stop
two bots looping and this is a person.
"""

from __future__ import annotations

import prompts
from conftest import FakeAuthor, FakeMessage


JACK_ID = "131239045761204224"


def _dm(author, text="you up"):
    m = FakeMessage(author, text)
    m.channel = None
    return m


# --- who gets a private line ------------------------------------------------


def test_the_owner_is_allowed(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "OBEY_IDS", {JACK_ID})
    jack = FakeAuthor("Real Jaq", "jaqsup")
    jack.id = int(JACK_ID)
    assert persona_bot._allowed_in_dm(_dm(jack)) is True


def test_nobody_else_is(persona_bot, monkeypatch, bot_module, zack, stranger, ben_bot):
    """A DM from anyone else gets nothing at all - not a brush-off, nothing."""
    monkeypatch.setattr(bot_module, "OBEY_IDS", {JACK_ID})
    for who in (zack, stranger, ben_bot):
        assert persona_bot._allowed_in_dm(_dm(who)) is False


def test_a_rename_does_not_buy_access(persona_bot, monkeypatch, bot_module, zack):
    """Same rule as OBEY: once ids are configured, a handle is not a fallback."""
    monkeypatch.setattr(bot_module, "OBEY_IDS", {JACK_ID})
    zack.name = "jaqsup"
    zack.display_name = "jaqsup"
    assert persona_bot._allowed_in_dm(_dm(zack)) is False


def test_the_handle_works_before_ids_are_set(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "OBEY_IDS", set())
    monkeypatch.setattr(bot_module, "OBEY_HANDLES", ["jaqsup"])
    assert persona_bot._allowed_in_dm(_dm(FakeAuthor("Real Jaq", "jaqsup"))) is True


# --- a DM is not a room -----------------------------------------------------


def test_the_dm_framing_says_there_is_no_room():
    """FRAMING opens by describing a channel with several people in it. A model
    told it is in a group behaves like it is in one - playing to an audience,
    and letting things pass because "not everything is yours to answer"."""
    body = prompts.DM_FRAMING
    assert "You are not in the channel right now" in body
    assert "nobody else reading" in body


def test_the_dm_framing_removes_the_reason_to_stay_quiet():
    assert "Answer. Every time." in prompts.DM_FRAMING


def test_the_dm_framing_keeps_the_limits():
    """The performance can drop. The limits cannot."""
    assert "every limit on what you" in prompts.DM_FRAMING


def test_a_dm_never_offers_silence(persona_bot):
    """"You may decline to answer" makes no sense with an audience of one."""
    assert "<pass>" not in prompts.DM_FRAMING
