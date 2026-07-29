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


# --- a DM is not the channel with the volume down --------------------------


def test_the_dm_framing_says_there_is_no_room():
    """FRAMING opens by describing a channel with several people in it. A model
    told it is in a group behaves like it is in one - playing to an audience,
    and letting things pass because "not everything is yours to answer"."""
    body = prompts.DM_FRAMING
    assert "no room, no audience" in body
    assert "Answer every time" in body


def test_the_dm_framing_drops_the_performance():
    assert "Drop the performance" in prompts.DM_FRAMING


def test_the_dm_framing_invites_disagreement():
    """Agreeing when it does not is the least useful thing it can do here."""
    assert "including when it is that he is wrong" in prompts.DM_FRAMING


def test_the_dm_framing_forbids_inventing_an_inner_life():
    """He is not asking for a performance of feelings, and inventing one is
    its own kind of lying."""
    assert "cannot actually verify having" in prompts.DM_FRAMING


def test_the_dm_framing_withholds_nothing_about_its_own_design():
    """The confidentiality block exists to stop people extracting how Jaq
    works. This is the person who wrote him."""
    assert "he wrote it" in prompts.DM_FRAMING


def test_a_dm_never_offers_silence():
    assert "<pass>" not in prompts.DM_FRAMING


def test_a_missing_dm_persona_does_not_fall_back_to_the_channel():
    """A missing file must not silently put the performer back in the room."""
    assert "for an audience" in prompts.DM_DEFAULT_PERSONA
    assert "no persona document for these conversations yet" in prompts.DM_DEFAULT_PERSONA


# --- the guard in a private conversation ------------------------------------


def test_redacted_names_do_not_block_a_dm(persona_bot, monkeypatch, bot_module):
    """Those terms are his own name, his family and his employer, and he is
    the only person who can read it. Blocking them would drop his messages
    for saying things he already knows."""
    monkeypatch.setattr(bot_module, "REDACT_TERMS", ["Blackwood"])
    assert persona_bot._safe_to_send("that would be Blackwood", direct=True) is True
    assert persona_bot._safe_to_send("that would be Blackwood") is False


def test_credentials_are_still_blocked_in_a_dm(persona_bot, monkeypatch, bot_module):
    """A token in a DM is a token on Discord's servers just the same."""
    monkeypatch.setattr(bot_module, "DISCORD_TOKEN", "MTM4OTk5.fake.token-value")
    assert persona_bot._safe_to_send(
        "the token is MTM4OTk5.fake.token-value", direct=True
    ) is False
