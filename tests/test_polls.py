"""Polls: when to call a vote, and what Discord will actually accept.

A poll is an escalation of an argument that already exists. Manufacturing one
out of a quiet conversation is a bot being random, which is the opposite of the
joke - so the trigger requires a dispute in the transcript, not just an
opportunity.
"""

from __future__ import annotations

import pytest

import decide
from conftest import FakeAuthor, FakeMessage
from test_identity import FakeChannel


# --- being asked outright ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["put it to a vote", "poll it", "let's vote", "make a poll", "poll the channel"],
)
def test_poll_requests_are_recognised(text):
    assert decide.is_poll_request(text) is True


@pytest.mark.parametrize(
    "text", ["I voted yesterday", "the polls were wrong", "", "vote kick him"]
)
def test_ordinary_talk_is_not_a_request(text):
    assert decide.is_poll_request(text) is False


# --- is anyone actually arguing --------------------------------------------


def test_a_dispute_is_detected():
    assert decide.looks_like_a_dispute(
        ["zack: you're wrong about the timer", "ben: prove it"]
    ) is True


def test_agreement_is_not_a_dispute():
    """A poll dropped into a conversation nobody is arguing about is noise."""
    assert decide.looks_like_a_dispute(
        ["zack: raid is wednesday", "ben: works for me", "dillon: same"]
    ) is False


def test_empty_transcript_is_not_a_dispute():
    assert decide.looks_like_a_dispute([]) is False


def test_only_recent_lines_count():
    """An argument twenty messages ago is over."""
    old_row = ["zack: you're wrong"] + [f"filler {i}" for i in range(10)]
    assert decide.looks_like_a_dispute(old_row) is False


# --- parsing, against Discord's real limits ---------------------------------


def test_a_well_formed_poll_parses():
    q, a = decide.parse_poll("Q: who wiped it\n- ben\n- also ben")
    assert q == "who wiped it"
    assert a == ["ben", "also ben"]


def test_asterisk_bullets_work_too():
    _, a = decide.parse_poll("Q: x\n* one\n* two")
    assert a == ["one", "two"]


def test_prose_is_rejected():
    """A malformed poll must degrade to an ordinary message, not a failed send."""
    assert decide.parse_poll("I reckon it was ben, obviously") is None


def test_a_single_option_is_rejected():
    assert decide.parse_poll("Q: x\n- only one") is None


def test_too_many_options_are_rejected():
    body = "Q: x\n" + "\n".join(f"- opt {i}" for i in range(12))
    assert decide.parse_poll(body) is None


def test_an_overlong_answer_is_rejected():
    """Discord rejects the whole message rather than truncating the answer."""
    assert decide.parse_poll("Q: x\n- " + "a" * 60 + "\n- b") is None


def test_an_overlong_question_is_rejected():
    assert decide.parse_poll("Q: " + "a" * 320 + "\n- yes\n- no") is None


def test_a_missing_question_is_rejected():
    assert decide.parse_poll("- yes\n- no") is None


def test_blank_answers_are_rejected():
    assert decide.parse_poll("Q: x\n- \n- b") is None


def test_surrounding_prose_is_ignored():
    """The model sometimes adds a line despite being told not to."""
    parsed = decide.parse_poll("settling this now\nQ: who wiped it\n- ben\n- ben again")
    assert parsed is not None
    assert parsed[0] == "who wiped it"


# --- when the bot reaches for one -------------------------------------------


def _msg(text):
    m = FakeMessage(FakeAuthor("dillon", "wurmz"), text)
    m.channel = FakeChannel()
    return m


ARGUING = "zack: you're wrong\nben: prove it"
QUIET = "zack: raid is wednesday\nben: cool"


def test_a_request_always_polls(persona_bot):
    assert persona_bot._wants_poll(_msg("poll it"), QUIET) is True


def test_a_request_ignores_the_daily_cap(persona_bot, bot_module):
    persona_bot._polls_today = bot_module.POLL_DAILY_MAX + 3
    assert persona_bot._wants_poll(_msg("put it to a vote"), QUIET) is True


def test_a_dispute_can_trigger_a_poll(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._polls_today = 0
    assert persona_bot._wants_poll(_msg("anyway"), ARGUING) is True


def test_a_quiet_channel_never_triggers_one(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._polls_today = 0
    assert persona_bot._wants_poll(_msg("anyway"), QUIET) is False


def test_the_roll_is_respected(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 1.0)
    persona_bot._polls_today = 0
    assert persona_bot._wants_poll(_msg("anyway"), ARGUING) is False


def test_the_daily_cap_stops_unprompted_polls(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._polls_today = bot_module.POLL_DAILY_MAX
    assert persona_bot._wants_poll(_msg("anyway"), ARGUING) is False


def test_disabled_by_config(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "POLL_ENABLED", False)
    assert persona_bot._wants_poll(_msg("poll it"), ARGUING) is False


# --- losing one -------------------------------------------------------------


def test_the_prompt_puts_our_side_first(bot_module):
    """_check_polls compares the winner against answers[0], so the prompt has
    to guarantee that is our position."""
    assert "Your position is always the first option" in bot_module.POLL_PROMPT


def test_the_loss_prompt_refuses_to_concede(bot_module):
    body = bot_module.POLL_LOST_PROMPT
    assert "Do not concede" in body
    assert "pretend it didn't happen" in body  # phrase spans a line wrap
