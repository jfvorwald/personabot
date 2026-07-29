"""Discord's reply feature: rare, and only when the target has to be visible.

Left to a dice roll this would fire on ordinary remarks and miss the burns,
because whether a line needs its target attached is a judgement about the line.
So the model asks for it - and because the model asks, over-use is a real risk,
which is why the share of replies using it is measured rather than assumed.
"""

from __future__ import annotations

import pytest

import decide
import improve
import prompts


# --- parsing the flag -------------------------------------------------------


def test_the_flag_is_found_and_removed():
    text, wants = decide.wants_reply_to("worst take all week\n<<reply>>")
    assert wants is True
    assert text == "worst take all week"


def test_an_ordinary_message_is_untouched():
    assert decide.wants_reply_to("just talking") == ("just talking", False)


def test_the_flag_is_stripped_from_mid_message():
    """Wherever it lands it must not survive into the channel - a model that
    has seen the syntax will eventually reproduce it."""
    text, wants = decide.wants_reply_to("before <<reply>> after")
    assert "<<" not in text and "reply>>" not in text
    assert wants is True


@pytest.mark.parametrize("text", ["<< REPLY >>", "<<Reply>>", "<<  reply  >>"])
def test_spacing_and_case_do_not_matter(text):
    assert decide.wants_reply_to("line\n" + text)[1] is True


@pytest.mark.parametrize("text", ["a > b", "<3", "<pass>", "reply to me", ""])
def test_ordinary_punctuation_is_not_the_flag(text):
    assert decide.wants_reply_to(text)[1] is False


def test_it_does_not_collide_with_the_image_directive():
    """Both directives can appear on one message and each must survive the
    other's parser."""
    text = "look at this\n<<image: a dog>>\n<<reply>>"
    stripped, wants = decide.wants_reply_to(text)
    assert wants is True
    body, prompt = decide.extract_image_prompt(stripped)
    assert prompt == "a dog"
    assert body == "look at this"


# --- the rule that keeps it rare --------------------------------------------


def test_the_rule_says_rarely_and_why():
    body = prompts.FRAMING
    assert "Use it rarely and on purpose" in body
    assert "A burn needs its target attached" in body


def test_the_rule_states_the_default():
    """Without an explicit default the model treats an available tool as one
    to use."""
    assert "Default to not using it" in prompts.FRAMING


def test_the_rule_gives_the_reason_not_just_the_limit():
    """A rule with the reason attached generalises to cases the wording did
    not anticipate; a bare limit does not."""
    assert "a room nobody can follow" in prompts.FRAMING


# --- over-use is measured, not assumed --------------------------------------


def test_quote_reply_share_is_counted():
    records = [
        {"kind": "reply", "as_reply": True},
        {"kind": "reply", "as_reply": False},
        {"kind": "reply", "as_reply": False},
        {"kind": "reply", "as_reply": False},
        {"kind": "pass"},
    ]
    stats = improve.engagement(records)
    assert stats["quote_replied"] == 1
    assert stats["quote_reply_share"] == 0.25


def test_no_replies_is_not_a_division_by_zero():
    stats = improve.engagement([{"kind": "pass"}])
    assert stats["quote_reply_share"] == 0.0
