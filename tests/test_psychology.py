"""Conversation-mechanics rules that the code (not the prompt) has to enforce.

Most of psychology.md is prompt material - the model executes it. One rule
isn't: adjacency pairs. A question aimed at Jaq makes an answer conditionally
relevant, and the drop used to happen during routing, before the model was ever
called, so no amount of prompting could have fixed it.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import FakeAuthor, FakeMessage
from test_identity import FakeChannel


# --- question detection -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "agentic jaq what do you think?",
        "agentic jaq, thoughts?",
        "what does agentix reckon",
        "is agentix around",
        "can agentix confirm this",
        "anyone know if agentix tried it",
        "how would agentix do it",
        "agentic jaq you seen this?",
    ],
)
def test_questions_aimed_at_jaq_are_detected(persona_bot, stranger, text):
    m = FakeMessage(stranger, text)
    m.channel = FakeChannel()
    assert persona_bot._direct_question(m) is True


@pytest.mark.parametrize(
    "text",
    [
        "agentix is right about that",
        "agentix already said this",
        "told agentix earlier",
    ],
)
def test_statements_about_jaq_are_not_questions(persona_bot, stranger, text):
    m = FakeMessage(stranger, text)
    m.channel = FakeChannel()
    assert persona_bot._direct_question(m) is False


def test_question_not_addressed_to_us_is_not_ours(persona_bot, stranger):
    """Someone else's question is not an adjacency pair we owe a half of."""
    assert persona_bot._direct_question(FakeMessage(stranger, "what time is it?")) is False


def test_mention_with_a_question_counts(persona_bot, stranger):
    m = FakeMessage(stranger, "thoughts?")
    m.mentions = [persona_bot.user]
    assert persona_bot._direct_question(m) is True


def test_empty_message_is_not_a_question(persona_bot, stranger):
    assert persona_bot._direct_question(FakeMessage(stranger, "   ")) is False


def test_leading_at_sign_is_stripped(persona_bot, stranger):
    assert persona_bot._direct_question(FakeMessage(stranger, "@agentix can you look")) is True


# --- the routing fix --------------------------------------------------------


def respond(bot, message, counterpart=False):
    return asyncio.run(bot._respond_like_a_person(message, counterpart))


@pytest.fixture
def never_posts(monkeypatch, bot_module, persona_bot):
    """Stop before any network call, recording how far routing got."""
    calls = {"hang_back": 0, "rolled": False}

    real_hang_back = persona_bot._hang_back

    def spy_hang_back(mine):
        calls["hang_back"] += 1
        return real_hang_back(mine)

    async def spy_chance(*a, **k):
        calls["rolled"] = True
        return 1.0  # always clears the roll

    async def stop_here(*a, **k):
        raise RuntimeError("reached the network")

    persona_bot._hang_back = spy_hang_back
    persona_bot._reply_chance = spy_chance
    persona_bot._recent_mix = lambda m: _immediate((0, 3))
    persona_bot._react_later = lambda *a, **k: None
    persona_bot.read_transcript = stop_here
    monkeypatch.setattr(bot_module.asyncio, "sleep", _instant)
    return calls


class _Channel:
    """Past the routing branches, the settle step re-reads the last message."""

    def history(self, limit=1):
        async def gen():
            return
            yield  # pragma: no cover - empty async generator

        return gen()


async def _instant(_):
    return None


def _immediate(value):
    async def coro():
        return value

    return coro()


def test_direct_question_skips_the_hang_back(persona_bot, stranger, never_posts):
    """The regression.

    _addressed_to_me was only consulted inside _reply_chance, which the
    hang-back branch never reached - so "jaq what do you think?" from a
    non-ally during a hang-back window was dropped without even rolling.
    """
    persona_bot._hang_back_target = 5
    persona_bot._messages_waited = 0

    with pytest.raises(RuntimeError, match="reached the network"):
        m = FakeMessage(stranger, "agentic jaq what do you think?")
        m.channel = _Channel()
        respond(persona_bot, m)

    assert never_posts["hang_back"] == 0, "a question must not be held back"
    assert never_posts["rolled"] is True


def test_ordinary_message_still_hangs_back(persona_bot, stranger, never_posts):
    persona_bot._hang_back_target = 5
    persona_bot._messages_waited = 0

    m = FakeMessage(stranger, "lol")
    m.channel = _Channel()
    assert respond(persona_bot, m) is False
    assert never_posts["hang_back"] == 1
    assert never_posts["rolled"] is False


def test_statement_naming_jaq_still_hangs_back(persona_bot, stranger, never_posts):
    """Only questions get the exemption - being mentioned in passing doesn't."""
    persona_bot._hang_back_target = 5
    persona_bot._messages_waited = 0

    m = FakeMessage(stranger, "agentix is right")
    m.channel = _Channel()
    assert respond(persona_bot, m) is False
    assert never_posts["hang_back"] == 1


# --- prompt assembly --------------------------------------------------------


def test_psychology_file_loads(bot_module):
    assert "conditionally relevant" in bot_module.load_psychology()


def test_missing_psychology_file_is_not_an_error(monkeypatch):
    """Patched on persona, which is where the loader now reads the name."""
    import persona

    monkeypatch.setattr(persona, "PSYCHOLOGY_FILE", "does-not-exist.md")
    assert persona.load_psychology() == ""


def test_psychology_is_a_separate_block_from_persona(bot_module):
    """It must not be merged into persona.md - the whole point is that the two
    stay independently editable."""
    text = bot_module.load_psychology()
    assert "persona.md" in text, "should point at the persona rather than restate it"
    assert "influence" in text.lower(), "should record why the persuasion half is out"
