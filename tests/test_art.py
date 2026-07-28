"""ASCII art: when it fires, and how hard it is rationed.

Always available on request. Unprompted it is a commitment bit - a two-word
question answered with a diagram - so it is capped at roughly one a day. The
second time in a day the effort stops being disproportionate and becomes a tic.
"""

from __future__ import annotations

import pytest

import decide
from conftest import FakeAuthor, FakeMessage
from test_identity import FakeChannel


# --- detecting a request ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "draw a tombstone",
        "draw zack",
        "agentic jaq draw ben",
        "make me a chart of my spending",
        "give us a graph",
        "diagram the raid",
        "plot the boss timers",
        "ascii art please",
        "sketch the wipe",
    ],
)
def test_requests_are_recognised(text):
    assert decide.is_art_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "what chart are you using",
        "can someone chart a course",
        "the chart looks wrong",
        "my diagram is fine",
        "is that a diagram",
        "map is bugged again",
        "are you coming wednesday?",
        "",
    ],
)
def test_talk_about_pictures_is_not_a_request(text):
    """Same verbs, different position. "draw" is a request; "the draw" is not."""
    assert decide.is_art_request(text) is False


# --- trivial enough for the joke to work ------------------------------------


@pytest.mark.parametrize(
    "text", ["are you coming?", "wednesday?", "is ben going", "what time"]
)
def test_short_questions_are_trivial(text):
    assert decide.is_trivial_question(text, 8) is True


def test_a_long_question_is_not_trivial():
    """Answering a real question thoroughly is just answering it - there is no
    disproportion to be funny about."""
    long_q = "what do you actually think about the way the guild handles loot these days?"
    assert decide.is_trivial_question(long_q, 8) is False


def test_a_statement_is_not_a_trivial_question():
    assert decide.is_trivial_question("raid moved to wednesday", 8) is False


# --- when the bot reaches for it --------------------------------------------


def _msg(text):
    m = FakeMessage(FakeAuthor("dillon", "wurmz"), text)
    m.channel = FakeChannel()
    return m


def test_a_request_always_produces_art(persona_bot):
    assert persona_bot._art_instruction(_msg("draw zack")) is not None


def test_a_request_ignores_the_daily_cap(persona_bot, bot_module):
    """Someone asking is not the rationed case; the unprompted bit is."""
    persona_bot._art_today = bot_module.ART_DAILY_MAX + 5
    assert persona_bot._art_instruction(_msg("draw zack")) is not None


def test_ordinary_talk_produces_nothing(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)  # always roll in
    assert persona_bot._art_instruction(_msg("raid moved to wednesday")) is None


def test_trivial_question_can_trigger_overkill(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._art_today = 0
    assert persona_bot._art_instruction(_msg("are you coming?")) is not None


def test_overkill_respects_the_roll(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 1.0)  # always roll out
    persona_bot._art_today = 0
    assert persona_bot._art_instruction(_msg("are you coming?")) is None


def test_overkill_stops_at_the_daily_cap(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._art_today = bot_module.ART_DAILY_MAX
    assert persona_bot._art_instruction(_msg("are you coming?")) is None


def test_long_question_never_triggers_overkill(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    persona_bot._art_today = 0
    long_q = "what do you actually think about how the guild handles loot lately?"
    assert persona_bot._art_instruction(_msg(long_q)) is None


def test_disabled_by_config(persona_bot, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "ART_ENABLED", False)
    assert persona_bot._art_instruction(_msg("draw zack")) is None


# --- the prompt carries the constraints that make it render -----------------


def test_prompt_demands_a_code_fence(persona_bot):
    """Outside a code block Discord uses a proportional font and art collapses."""
    out = persona_bot._art_instruction(_msg("draw zack"))
    assert "triple-backtick" in out


def test_prompt_bans_emoji_inside_the_block(persona_bot):
    """Emoji are double-width and shear every line beneath them."""
    out = persona_bot._art_instruction(_msg("draw zack"))
    assert "No emoji" in out


def test_prompt_steers_away_from_forms_that_need_alignment(persona_bot):
    """Testing showed figures and closed boxes come out a character off and
    read as broken; row-based forms tolerate it."""
    out = persona_bot._art_instruction(_msg("draw zack"))
    assert "bar charts" in out
    assert "symmetrical boxes" in out


# --- the count survives a restart -------------------------------------------


def test_art_count_persists(persona_bot, bot_module, tmp_path, monkeypatch):
    import datetime

    monkeypatch.setattr(bot_module, "STATE_FILE", str(tmp_path / "s.json"))
    persona_bot._state_path = lambda: str(tmp_path / "s.json")
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._save_day = bot_module.PersonaBot._save_day.__get__(persona_bot)

    today = datetime.date(2026, 7, 28)
    persona_bot._reply_day = today
    persona_bot._art_today = 1
    persona_bot._save_day()

    persona_bot._art_today = 0
    assert persona_bot._restore_day(today) is True
    assert persona_bot._art_today == 1, "a restart must not refill the art budget"
