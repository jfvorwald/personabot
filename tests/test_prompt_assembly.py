"""Actually build a system prompt, all the way through.

This file exists because 878 tests passed while the bot threw
`UnboundLocalError` on every single reply for two hours. Prompt assembly had
no test that ran it - the pieces were all covered, the function that puts them
together was not - so a refactor that renamed a variable in one branch and not
another was green the whole way to production.

Nothing here asserts anything clever. It calls the real path with a stubbed
API client and checks that a prompt comes out. That is the coverage that was
missing.
"""

from __future__ import annotations

import asyncio
import types

import pytest

import bot


class FakeMessages:
    """Captures the kwargs `generate` sends, and returns a plausible reply."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            stop_reason="end_turn",
            content=[types.SimpleNamespace(type="text", text="sure")],
            usage=types.SimpleNamespace(
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
                input_tokens=10,
            ),
        )


@pytest.fixture
def wired(persona_bot, monkeypatch):
    """A bot with enough attached to build a prompt for real."""
    persona_bot.persona = "PERSONA BODY"
    persona_bot.psychology = "PSYCHOLOGY BODY"
    persona_bot.vocab = "VOCAB BODY"
    fake = FakeMessages()
    persona_bot.claude = types.SimpleNamespace(messages=fake)
    persona_bot._safe_to_send = lambda text, direct=False: True
    monkeypatch.setattr(bot, "BRAIN_ENABLED", True)
    monkeypatch.setattr(bot.brain, "load_for", lambda ids: "BRAIN NOTES")
    monkeypatch.setattr(bot.personnel, "load_for", lambda ids: "PERSONNEL NOTES")
    return persona_bot, fake


def _run(coro):
    return asyncio.run(coro)


# --- the reply path ----------------------------------------------------------


def test_an_ordinary_reply_builds_a_prompt(wired):
    """The exact call that raised UnboundLocalError in production."""
    b, fake = wired
    out = _run(b.generate("someone said something", speakers={7}))
    assert out == "sure"
    assert len(fake.calls) == 1


def test_every_piece_reaches_the_prompt(wired):
    """A branch that silently stops contributing is the other half of the same
    bug: no error, just a prompt quietly missing what it was told to carry."""
    b, fake = wired
    _run(b.generate("someone said something", speakers={7}))
    system = fake.calls[0]["system"]
    whole = "".join(block["text"] for block in system)
    for piece in ("PERSONA BODY", "PSYCHOLOGY BODY", "VOCAB BODY",
                  "BRAIN NOTES", "PERSONNEL NOTES"):
        assert piece in whole, f"{piece} never made it into the prompt"


def test_the_person_specific_half_is_not_cached(wired):
    """Brain and personnel move with who is speaking. Caching them would mean
    paying the write premium on every distinct set of speakers."""
    b, fake = wired
    _run(b.generate("hello", speakers={7}))
    system = fake.calls[0]["system"]
    cached = system[0]["text"]
    assert "BRAIN NOTES" not in cached
    assert "PERSONNEL NOTES" not in cached
    assert "PERSONA BODY" in cached


@pytest.mark.parametrize("kwargs", [
    {"may_stay_silent": True},
    {"ordered": True},
    {"offer_image": True},
    {"refuse_image": True},
    {"commissioned": True},
    {"offer_gif": True},
    {"instruction": "Open the conversation."},
])
def test_every_branch_of_the_framing_assembles(wired, kwargs):
    """Each of these appends something different, and the refactor that broke
    this only touched one branch. Walk all of them."""
    b, fake = wired
    assert _run(b.generate("hello", speakers={7}, **kwargs)) == "sure"


def test_it_still_builds_with_no_speakers_and_no_notes(wired, monkeypatch):
    b, fake = wired
    monkeypatch.setattr(bot.brain, "load_for", lambda ids: "")
    monkeypatch.setattr(bot.personnel, "load_for", lambda ids: "")
    assert _run(b.generate("hello")) == "sure"


def test_a_failing_brain_does_not_take_the_reply_down(wired, monkeypatch):
    def boom(ids):
        raise RuntimeError("brain is broken")
    monkeypatch.setattr(bot.brain, "load_for", boom)
    b, fake = wired
    assert _run(b.generate("hello", speakers={7})) == "sure"


def test_a_failing_personnel_does_not_take_the_reply_down(wired, monkeypatch):
    def boom(ids):
        raise RuntimeError("personnel is broken")
    monkeypatch.setattr(bot.personnel, "load_for", boom)
    b, fake = wired
    assert _run(b.generate("hello", speakers={7})) == "sure"


def test_caching_off_sends_a_plain_string(wired, monkeypatch):
    monkeypatch.setattr(bot, "CACHE_PROMPT", False)
    b, fake = wired
    _run(b.generate("hello", speakers={7}))
    assert isinstance(fake.calls[0]["system"], str)


def test_the_same_prompt_comes_out_either_way(wired, monkeypatch):
    """Turning caching on must not change a byte of what the model reads."""
    b, fake = wired
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    _run(b.generate("hello", speakers={7}))
    cached = "".join(x["text"] for x in fake.calls[0]["system"])
    monkeypatch.setattr(bot, "CACHE_PROMPT", False)
    _run(b.generate("hello", speakers={7}))
    assert fake.calls[1]["system"] == cached
