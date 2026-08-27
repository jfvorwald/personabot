"""Deliverables: someone asks for a spreadsheet and gets a spreadsheet.

The joke is the same one the ASCII overkill path tells - effort wildly out of
proportion, played straight - with one difference that decides the design. A
table is something Jaq can genuinely put in a message, so unlike a picture he
is allowed to say yes. That is also the trap: the moment he can plausibly
produce something, "sent it over" with nothing under it becomes believable,
and people go hunting for a file that was never there. IMAGE_DECLINED exists
because that already happened once with pictures.
"""

from __future__ import annotations

import types

import pytest

import decide
import prompts


# --- what counts as asking ---------------------------------------------------


@pytest.mark.parametrize(
    "text,shape",
    [
        ("build me a spreadsheet of the raid roster", "spreadsheet"),
        ("jaq make a spread sheet", "spreadsheet"),
        ("gimme an invoice", "invoice"),
        ("put together a tier list", "tier list"),
        ("write up an nda", "contract"),
        ("make a pitch deck", "deck"),
        ("throw together a gantt chart", "gantt"),
        ("create an org chart for this channel", "org chart"),
        ("generate a certificate", "certificate"),
    ],
)
def test_a_request_names_its_shape(text, shape):
    assert decide.wants_artifact(text) == shape


@pytest.mark.parametrize(
    "text",
    [
        "the spreadsheet is wrong",
        "can anyone make a table",
        "what deck are you running",
        "did you make the invoice",
        "how do i build a spreadsheet",
        "your schedule is insane",
        "is that a tier list",
        "",
        "hello",
    ],
)
def test_talking_about_one_is_not_asking_for_one(text):
    """Same discipline as is_art_request: the verb has to be an order."""
    assert decide.wants_artifact(text) is None


def test_words_that_mean_tell_me_are_left_out():
    """People ask for these meaning 'answer me', and words are the right reply."""
    for text in ("give me a summary", "make a list", "write some notes"):
        assert decide.wants_artifact(text) is None, text


# --- the older surface keeps its words ---------------------------------------


def test_ascii_art_still_owns_its_vocabulary(persona_bot, bot_module):
    """'draw me a chart' is the art path, and had these words first."""
    for text in ("draw me a chart", "sketch a diagram", "ascii of zack"):
        message = types.SimpleNamespace(
            clean_content=text, author=types.SimpleNamespace(id=7)
        )
        assert persona_bot._artifact_instruction(message) is None, text


def test_only_one_bit_can_arm_at_a_time(persona_bot, bot_module):
    """A message that trips the art path must not also build a document."""
    message = types.SimpleNamespace(
        clean_content="draw me a chart", author=types.SimpleNamespace(id=7)
    )
    assert persona_bot._artifact_instruction(message) is None
    assert bot_module.decide.is_art_request(message.clean_content) is True


# --- rationing ---------------------------------------------------------------


def _ask(who=7, text="build me a spreadsheet"):
    return types.SimpleNamespace(
        clean_content=text, author=types.SimpleNamespace(id=who)
    )


def test_a_request_is_honoured(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ARTIFACT_ENABLED", True)
    instruction = persona_bot._artifact_instruction(_ask())
    assert instruction is not None
    assert "spreadsheet" in instruction


def test_one_person_cannot_drain_the_channel(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ARTIFACT_PER_PERSON_MAX", 2)
    persona_bot._artifacts_by_person = {"7": 2}
    assert persona_bot._artifact_instruction(_ask(7)) is None
    # Somebody else is unaffected, which is the point of a per-person cap.
    assert persona_bot._artifact_instruction(_ask(8)) is not None


def test_the_channel_backstop_binds(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ARTIFACT_DAILY_MAX", 12)
    persona_bot._artifacts_today = 12
    assert persona_bot._artifact_instruction(_ask()) is None


def test_the_feature_can_be_switched_off(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module, "ARTIFACT_ENABLED", False)
    assert persona_bot._artifact_instruction(_ask()) is None


def test_a_new_day_refills_both_counters(persona_bot, bot_module, monkeypatch):
    import datetime

    monkeypatch.setattr(bot_module, "LIVE_UNLIMITED", True)
    persona_bot._save_day = lambda: None
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._artifacts_today = 12
    persona_bot._artifacts_by_person = {"7": 3}
    persona_bot._roll_day(datetime.date(2026, 8, 27))
    assert persona_bot._artifacts_today == 0
    assert persona_bot._artifacts_by_person == {}


# --- the rule that pictures had to learn the hard way ------------------------


def test_the_prompt_forbids_claiming_a_file():
    """The failure IMAGE_DECLINED was written for, on a surface where it is
    far more believable: he really can produce a table, so "sent it over"
    reads as true and people go looking."""
    text = prompts.ARTIFACT_PROMPT.lower()
    for banned in ("attached", "emailed", "exported", ".xlsx", ".csv", ".pdf"):
        assert banned in text, f"{banned} is not addressed at all"
    assert "never say it is attached" in text


def test_every_shape_has_its_own_shaping():
    """One generic instruction produced the same grid with different words."""
    seen = set(prompts.ARTIFACT_SHAPING.values())
    assert len(seen) == len(prompts.ARTIFACT_SHAPING), "two shapes share a line"
    for shape, line in prompts.ARTIFACT_SHAPING.items():
        assert len(line) > 40, f"{shape} is not shaped at all"


def test_every_reachable_shape_is_shaped():
    """A noun that resolves to a shape with no shaping falls back silently."""
    shapes = set(decide.ARTIFACT_NOUNS.values()) | set(
        decide.ARTIFACT_PHRASES.values()
    )
    missing = shapes - set(prompts.ARTIFACT_SHAPING)
    assert not missing, f"no shaping for {sorted(missing)}"


def test_the_prompt_renders_for_every_shape():
    for shape, shaping in prompts.ARTIFACT_SHAPING.items():
        out = prompts.ARTIFACT_PROMPT.format(shape=shape, shaping=shaping)
        assert shape in out and shaping in out
