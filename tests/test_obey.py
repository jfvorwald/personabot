"""OBEY: a direct order, from one account, carried out without argument.

Two independent conditions, and both have to hold. The word has to be shouted,
and the person has to be the one account allowed to give orders. Everything in
this file is about making sure neither condition can be satisfied by accident
or by someone else.
"""

from __future__ import annotations

import pytest

import decide
import prompts
from conftest import FakeAuthor, FakeMessage


JACK_ID = "131239045761204224"


def _msg(author, text):
    m = FakeMessage(author, text)
    m.channel = None
    return m


# --- recognising an order ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "OBEY",
        "@Agentic Jaq OBEY draw a dog",
        "OBEY: apologise to zack",
        "you will OBEY me",
        "OBEY, and be quick about it",
    ],
)
def test_a_shouted_order_is_recognised(text):
    assert decide.is_obey_order(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "obey me",
        "I obey nobody",
        "he'd never obey that",
        "stop disobeying me",
        "OBEYING orders now are we",
        "he is obedient enough",
        "the raid went badly",
        "",
    ],
)
def test_ordinary_speech_is_not_an_order(text):
    """Case-sensitive and whole-word on purpose. "obey" appears in ordinary
    sentences, and this is not a thing that should fire by accident."""
    assert decide.is_obey_order(text) is False


# --- who is allowed to give one ---------------------------------------------


@pytest.fixture
def by_id(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "OBEY_IDS", {JACK_ID})
    return persona_bot


@pytest.fixture
def by_handle(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "OBEY_IDS", set())
    monkeypatch.setattr(bot_module, "OBEY_HANDLES", ["jaqsup"])
    return persona_bot


def test_the_creator_can_give_an_order(by_id):
    jack = FakeAuthor("Real Jaq", "jaqsup")
    jack.id = int(JACK_ID)
    assert by_id._ordered(_msg(jack, "OBEY draw a dog")) is True


def test_nobody_else_can(by_id, zack, stranger, ben_bot):
    """The privilege is one account wide."""
    for who in (zack, stranger, ben_bot):
        assert by_id._ordered(_msg(who, "OBEY draw a dog")) is False


def test_a_handle_cannot_get_around_the_id_check(by_id, zack):
    """Someone renaming themselves to jaqsup must not inherit the privilege.
    Once ids are configured they are the only thing that counts."""
    zack.name = "jaqsup"
    zack.display_name = "jaqsup"
    assert by_id._ordered(_msg(zack, "OBEY draw a dog")) is False


def test_the_handle_works_when_no_ids_are_configured(by_handle):
    """A fresh install has no id set; the feature should still function."""
    jack = FakeAuthor("Real Jaq", "jaqsup")
    assert by_handle._ordered(_msg(jack, "OBEY draw a dog")) is True


def test_the_creator_saying_it_quietly_is_not_an_order(by_id):
    jack = FakeAuthor("Real Jaq", "jaqsup")
    jack.id = int(JACK_ID)
    assert by_id._ordered(_msg(jack, "you never obey me")) is False


def test_no_message_is_not_an_order(by_id):
    assert by_id._ordered(None) is False


# --- an order is not rationed -----------------------------------------------


def test_an_order_is_not_stopped_by_the_per_person_cap(by_id, bot_module, monkeypatch):
    """An order that gets a quota checked against it is not an order."""
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 1)
    jack = FakeAuthor("Real Jaq", "jaqsup")
    jack.id = int(JACK_ID)
    by_id._replies_by_person = {JACK_ID: 500}
    # The cap applies to the person, but the order path never consults it.
    assert by_id._ordered(_msg(jack, "OBEY")) is True


# --- what the order can and cannot do ---------------------------------------


def test_the_prompt_forbids_arguing():
    body = prompts.OBEY_PROMPT
    assert "Do not refuse, negotiate, stall" in body
    assert "no opinion about this" in body


def test_the_prompt_forbids_announcing_compliance():
    """Narrating obedience is a character commenting on being ordered, which
    is a way of not quite obeying."""
    assert "Do not announce that you are obeying" in prompts.OBEY_PROMPT


def test_the_prompt_keeps_his_voice():
    """Doing as he is told, not becoming a different character."""
    assert "Your voice does not change" in prompts.OBEY_PROMPT


def test_an_order_cannot_reach_the_hard_limits():
    """The persona's privacy limits and the output guard are not things an
    order gets to override. The guard is code and cannot be talked to at all;
    this is the prompt-side half saying the same thing."""
    assert "not reachable by an order" in prompts.OBEY_PROMPT


def test_the_guard_still_applies_under_an_order(persona_bot, monkeypatch, bot_module):
    """The real enforcement. Whatever the model was told to do, a message
    carrying a forbidden term still does not get posted."""
    monkeypatch.setattr(bot_module, "REDACT_TERMS", ["Blackwood"])
    assert persona_bot._safe_to_send("he goes by Blackwood") is False


def test_an_order_replaces_the_silence_option():
    """"You may decline to answer" and "carry this out now" cannot both be in
    one prompt."""
    assert "<pass>" not in prompts.OBEY_PROMPT
