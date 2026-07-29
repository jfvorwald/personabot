"""Knowing who is who.

Three failures sat behind "the bot forgets who I am": a guild nickname written
in fullwidth unicode that no ASCII substring match could ever hit, ally status
keyed on a display name that changed, and a persona whose name collides with a
real person's in the same channel.
"""

from __future__ import annotations

import pytest

from conftest import FakeAuthor, FakeMessage

# The bot's actual nickname in the server. Those are fullwidth code points
# (U+FF21 block), not the ASCII letters they resemble.
FULLWIDTH_NICK = "🤖 Ａｇｅｎｔｉｃ Ｊａｑ"


class FakeGuildMe:
    def __init__(self, display):
        self.display_name = display


class FakeGuild:
    def __init__(self, nick):
        self.me = FakeGuildMe(nick)
        self.emojis = []


class FakeChannel:
    def __init__(self, nick=FULLWIDTH_NICK):
        self.guild = FakeGuild(nick)


def addressed(bot, text, nick=FULLWIDTH_NICK):
    m = FakeMessage(FakeAuthor("wishxd", "giftxd"), text)
    m.channel = FakeChannel(nick)
    return bot._addressed_to_me(m)


# --- unicode folding --------------------------------------------------------


def test_fullwidth_folds_to_ascii(bot_module):
    assert bot_module.fold("Ｊａｑ") == "jaq"
    assert bot_module.fold("Ａｇｅｎｔｉｃ　Ｊａｑ") == "agentic jaq"


def test_fold_is_case_insensitive(bot_module):
    assert bot_module.fold("AGENTIC JAQ") == "agentic jaq"


def test_plain_text_is_unchanged(bot_module):
    assert bot_module.fold("agentic jaq") == "agentic jaq"


# --- being addressed --------------------------------------------------------


def test_fullwidth_nickname_is_recognised(persona_bot):
    """The regression.

    clean_content renders a mention as the guild nickname, which here is
    fullwidth. `"jaq" in text` was False against `ｊａｑ`, so addressing the bot
    by name registered as not addressing it at all - which also silently
    disabled the direct-question exemption.
    """
    assert addressed(persona_bot, f"@{FULLWIDTH_NICK} remember who I am") is True


def test_plain_nickname_is_recognised(persona_bot):
    assert addressed(persona_bot, "agentic jaq you around") is True


def test_alias_is_recognised(persona_bot):
    assert addressed(persona_bot, "agentix what do you think") is True


def test_bare_jaq_is_not_the_bot(persona_bot):
    """The persona and its creator share this name in this channel, so a bare
    "jaq" is ambiguous and usually means the human."""
    assert addressed(persona_bot, "jaq is right about that") is False


def test_unrelated_message_is_not_addressed(persona_bot):
    assert addressed(persona_bot, "anyone up for kara tonight") is False


def test_real_mention_always_wins(persona_bot):
    m = FakeMessage(FakeAuthor("wishxd", "giftxd"), "no name here at all")
    m.channel = FakeChannel()
    m.mentions = [persona_bot.user]
    assert persona_bot._addressed_to_me(m) is True


def test_nickname_question_reaches_the_question_path(persona_bot):
    """The two fixes have to compose: a nickname-addressed question must count
    as a direct question, or it can still be dropped by the hang-back."""
    m = FakeMessage(FakeAuthor("wishxd", "giftxd"), f"@{FULLWIDTH_NICK} what do you think?")
    m.channel = FakeChannel()
    assert persona_bot._direct_question(m) is True


# --- ally identification ----------------------------------------------------


def test_ally_by_user_id(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ALLY_IDS", {"131239045761204224"})
    author = FakeAuthor("Literally Anything", "renamed_twice")
    author.id = 131239045761204224
    assert persona_bot._is_ally(FakeMessage(author)) is True


def test_id_based_ally_survives_a_rename(persona_bot, bot_module, monkeypatch):
    """"Real Jaq" -> "Jaq" broke the name match. The id cannot break."""
    monkeypatch.setattr(bot_module, "ALLY_IDS", {"131239045761204224"})
    monkeypatch.setattr(bot_module, "ALLIES", ["real jaq"])  # now stale

    author = FakeAuthor("Jaq", "jaqsup")
    author.id = 131239045761204224
    assert persona_bot._is_ally(FakeMessage(author)) is True


def test_name_fallback_still_works(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ALLY_IDS", set())
    monkeypatch.setattr(bot_module, "ALLIES", ["jaqsup"])
    assert persona_bot._is_ally(FakeMessage(FakeAuthor("Jaq", "jaqsup"))) is True


def test_stranger_is_not_an_ally(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ALLY_IDS", {"131239045761204224"})
    assert persona_bot._is_ally(FakeMessage(FakeAuthor("wishxd", "giftxd"))) is False


def test_bot_with_an_ally_id_is_still_not_an_ally(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ALLY_IDS", {"5"})
    author = FakeAuthor("Agentic Ben", "agenticben", is_bot=True)
    author.id = 5
    assert persona_bot._is_ally(FakeMessage(author)) is False


# --- the profile ------------------------------------------------------------


def test_creator_profile_names_him_as_the_channel_shows_him():
    """The profile said "Goes by Real Jaq" while the transcript said "Jaq"."""
    body = open("brain/people/jaqsup.md").read()
    assert "appears in this channel as **Jaq**" in body
    assert "jaqsup" in body


def test_creator_profile_disambiguates_the_shared_name():
    body = open("brain/people/jaqsup.md").read()
    assert "that is him, not you" in body


def test_creator_profile_defers_without_fawning():
    body = open("brain/people/jaqsup.md").read()
    assert "His word is final" in body
    assert "Never fawn" in body
    assert "Keep roasting him" in body


def test_creator_profile_holds_no_identifying_details():
    """The terms come from REDACT_TERMS in the gitignored .env, never from here.

    This test used to list them literally - a partner's name, a child's name,
    an employer - which published the exact strings it exists to keep out, in
    a public repo, next to a real name. A privacy test that leaks is worse
    than no test.
    """
    import os

    from dotenv import dotenv_values

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    configured = dotenv_values(os.path.join(root, ".env")).get("REDACT_TERMS") or ""
    terms = [t.strip().lower() for t in configured.split(",") if t.strip()]
    if not terms:
        pytest.skip("no REDACT_TERMS configured; nothing to check against")

    body = open("brain/people/jaqsup.md").read().lower()
    for term in terms:
        assert term not in body, "a redacted term must never be in a profile"
