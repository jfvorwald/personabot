"""Whether to speak, and whether to wait.

These lock in behaviour that has already been wrong once: the decay multipliers
used to apply to direct @mentions, so @-ing the bot right after it spoke
resolved to a 33% chance of an answer.
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import FakeMessage


def chance(bot, message, counterpart=False, mine=0, others_since_me=3):
    return asyncio.run(bot._reply_chance(message, counterpart, mine, others_since_me))


# --- base rates -------------------------------------------------------------


def test_human_base_rate(persona_bot, bot_module, stranger):
    assert chance(persona_bot, FakeMessage(stranger)) == pytest.approx(
        bot_module.REPLY_CHANCE_HUMAN
    )


def test_ally_beats_human(persona_bot, bot_module, jack, stranger):
    ally = chance(persona_bot, FakeMessage(jack))
    human = chance(persona_bot, FakeMessage(stranger))
    assert ally == pytest.approx(bot_module.REPLY_CHANCE_ALLY)
    assert ally > human


def test_counterpart_is_lowest(persona_bot, bot_module, ben_bot):
    c = chance(persona_bot, FakeMessage(ben_bot), counterpart=True)
    assert c == pytest.approx(bot_module.REPLY_CHANCE_COUNTERPART)
    assert c < bot_module.REPLY_CHANCE_HUMAN


def test_name_in_text_counts_as_addressed(persona_bot, bot_module, stranger):
    c = chance(persona_bot, FakeMessage(stranger, "anyone seen jaq lately"))
    assert c == pytest.approx(bot_module.REPLY_CHANCE_ADDRESSED)


# --- decay ------------------------------------------------------------------


def test_last_speaker_decay_applies_to_non_allies(persona_bot, bot_module, stranger):
    fresh = chance(persona_bot, FakeMessage(stranger), mine=0, others_since_me=3)
    spoke_last = chance(persona_bot, FakeMessage(stranger), mine=1, others_since_me=0)
    assert spoke_last == pytest.approx(fresh * bot_module.REPLY_DECAY_IF_LAST_SPEAKER)


def test_ally_is_exempt_from_last_speaker_decay(persona_bot, bot_module, jack):
    fresh = chance(persona_bot, FakeMessage(jack), mine=0, others_since_me=3)
    spoke_last = chance(persona_bot, FakeMessage(jack), mine=1, others_since_me=0)
    assert spoke_last == pytest.approx(fresh)


def test_ally_still_pays_dominating_decay(persona_bot, bot_module, jack):
    """Being a friend is not a licence to monologue."""
    fresh = chance(persona_bot, FakeMessage(jack), mine=0, others_since_me=3)
    dominating = chance(persona_bot, FakeMessage(jack), mine=3, others_since_me=0)
    assert dominating < fresh


def test_dominating_decay_compounds(persona_bot, bot_module, stranger):
    two = chance(persona_bot, FakeMessage(stranger), mine=2, others_since_me=1)
    three = chance(persona_bot, FakeMessage(stranger), mine=3, others_since_me=1)
    assert three == pytest.approx(two * bot_module.REPLY_DECAY_IF_DOMINATING)


# --- mentions ---------------------------------------------------------------


def test_mention_is_recognised(persona_bot, stranger):
    m = FakeMessage(stranger, "oi")
    m.mentions = [persona_bot.user]
    assert persona_bot._mentioned_me(m) is True


def test_plain_message_is_not_a_mention(persona_bot, stranger):
    assert persona_bot._mentioned_me(FakeMessage(stranger, "unrelated")) is False


def test_mention_never_decays(persona_bot, bot_module, stranger):
    """The regression this suite exists for.

    A direct @mention used to run through the same decay as anything else, so
    @-ing the bot straight after it spoke resolved to REPLY_CHANCE_ADDRESSED *
    REPLY_DECAY_IF_LAST_SPEAKER = ~0.33. Mentions now bypass the roll entirely
    in _respond_like_a_person, so the decayed value must never be consulted.
    """
    m = FakeMessage(stranger, "oi")
    m.mentions = [persona_bot.user]
    assert persona_bot._mentioned_me(m) is True
    # Guard the arithmetic that made the old path wrong.
    decayed = bot_module.REPLY_CHANCE_ADDRESSED * bot_module.REPLY_DECAY_IF_LAST_SPEAKER
    assert decayed < 0.5, "decay would have made a mention a coin flip"


# --- allies -----------------------------------------------------------------


def test_ally_matched_on_display_name(persona_bot, jack):
    assert persona_bot._is_ally(FakeMessage(jack)) is True


def test_ally_matched_on_username(persona_bot):
    from conftest import FakeAuthor

    renamed = FakeAuthor("Jaq", "jaqsup")  # display name changed, username same
    assert persona_bot._is_ally(FakeMessage(renamed)) is True


def test_non_ally_is_not_matched(persona_bot, zack):
    assert persona_bot._is_ally(FakeMessage(zack)) is False


def test_bots_are_never_allies(persona_bot, ben_bot):
    assert persona_bot._is_ally(FakeMessage(ben_bot)) is False


# --- hanging back -----------------------------------------------------------


def test_hang_back_holds_until_target(persona_bot):
    persona_bot._hang_back_target = 3
    persona_bot._messages_waited = 0
    assert persona_bot._hang_back(mine=0) is True   # 1
    assert persona_bot._hang_back(mine=0) is True   # 2
    assert persona_bot._hang_back(mine=0) is False  # 3 -> eligible


def test_hang_back_skipped_once_in_the_conversation(persona_bot):
    persona_bot._hang_back_target = 5
    persona_bot._messages_waited = 0
    assert persona_bot._hang_back(mine=1) is False


def test_hang_back_resets_past_the_join_window(persona_bot, bot_module):
    persona_bot._hang_back_target = 1
    persona_bot._messages_waited = bot_module.JOIN_WINDOW_MESSAGES
    assert persona_bot._hang_back(mine=0) is True
    assert persona_bot._messages_waited == 0, "counter should have redrawn"


def test_hang_back_disabled_by_zero_target(persona_bot):
    persona_bot._hang_back_target = 0
    persona_bot._messages_waited = 0
    assert persona_bot._hang_back(mine=0) is False


def test_reset_draws_within_configured_range(persona_bot, bot_module):
    for _ in range(50):
        persona_bot._reset_hang_back()
        assert (
            bot_module.JOIN_AFTER_MIN
            <= persona_bot._hang_back_target
            <= bot_module.JOIN_AFTER_MAX
        )
        assert persona_bot._messages_waited == 0
