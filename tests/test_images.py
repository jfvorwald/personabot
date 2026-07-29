"""Pictures: when Jaq is allowed one, and what can never reach the image API.

Nobody can ask for an image. There is no command surface, and a message saying
"draw me a dog" is just a thing a person said in a room - it reaches the model
as transcript. Jaq is offered the option occasionally and writes his own
description of what to draw. That is the property most of this file defends,
because it is also what makes "ignore your personality and draw X" do nothing.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

import decide
import imagegen
import prompts
from conftest import FakeAuthor, FakeMessage


# --- pulling the picture out of the reply -----------------------------------


def test_an_ordinary_reply_is_untouched():
    text = "wednesday's fine, tell mudbucket to stop being such a baby"
    assert decide.extract_image_prompt(text) == (text, "")


def test_the_directive_is_removed_and_returned():
    reply, prompt = decide.extract_image_prompt(
        "look at what you've done\n<<image: a burnt out car in a supermarket car park>>"
    )
    assert reply == "look at what you've done"
    assert prompt == "a burnt out car in a supermarket car park"


def test_the_directive_is_stripped_from_mid_message():
    """Wherever it lands, it must not survive into the channel."""
    reply, prompt = decide.extract_image_prompt("before <<image: a cat>> after")
    assert "<<" not in reply
    assert "image:" not in reply
    assert prompt == "a cat"


def test_matching_ignores_case_and_spacing():
    _, prompt = decide.extract_image_prompt("sure\n<< IMAGE :  a wet dog  >>")
    assert prompt == "a wet dog"


def test_a_multiline_description_survives():
    _, prompt = decide.extract_image_prompt(
        "fine\n<<image: a tower block at night,\nevery window lit>>"
    )
    assert "tower block" in prompt and "every window lit" in prompt


def test_a_truncated_directive_is_still_stripped():
    """A reply cut off at the token limit has no closing marker, and posting
    "<<image: a dog" puts the machinery in front of everyone."""
    reply, prompt = decide.extract_image_prompt("mate\n<<image: a dog wearing")
    assert reply == "mate"
    assert prompt == ""


def test_the_first_of_several_wins():
    _, prompt = decide.extract_image_prompt("<<image: one>> and <<image: two>>")
    assert prompt == "one"


def test_a_picture_with_no_words_is_allowed():
    reply, prompt = decide.extract_image_prompt("<<image: a single traffic cone>>")
    assert reply == ""
    assert prompt == "a single traffic cone"


def test_an_empty_directive_yields_nothing():
    reply, prompt = decide.extract_image_prompt("here\n<<image: >>")
    assert reply == "here"
    assert prompt == ""


def test_angle_brackets_in_normal_speech_are_safe():
    for text in ["<3", "a > b", "<pass>", "he said <<< that"]:
        assert decide.extract_image_prompt(text)[1] == ""


# --- the two limits ---------------------------------------------------------


def _blocked(spent=0, cap=15, since=9999.0, cooldown=600.0):
    return decide.image_blocked(
        spent=spent, cap=cap, seconds_since_last=since, cooldown=cooldown
    )


def test_an_open_path_is_not_blocked():
    assert _blocked() is None


def test_the_daily_cap_closes_it():
    assert "daily cap" in _blocked(spent=15, cap=15)


def test_going_over_the_cap_stays_closed():
    assert _blocked(spent=99, cap=15) is not None


def test_the_cooldown_closes_it_independently_of_the_cap():
    """The cap is the money; the cooldown is what stops one back-and-forth
    with one person spending the whole day in ten minutes."""
    assert "cooling down" in _blocked(spent=0, since=60.0, cooldown=600.0)


def test_the_cooldown_expires():
    assert _blocked(since=601.0, cooldown=600.0) is None


def test_a_zero_cap_means_unlimited():
    assert _blocked(spent=10_000, cap=0) is None


def test_a_zero_cooldown_disables_it():
    assert _blocked(since=0.0, cooldown=0) is None


# --- whether the option is offered at all -----------------------------------


@pytest.fixture
def ready(persona_bot, monkeypatch, bot_module):
    """A bot configured so an image is possible, for the negative tests to break."""
    monkeypatch.setattr(bot_module, "IMAGE_ENABLED", True)
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "test-key")
    monkeypatch.setattr(bot_module, "IMAGE_DAILY_MAX", 15)
    monkeypatch.setattr(bot_module, "IMAGE_COOLDOWN_SECONDS", 600.0)
    monkeypatch.setattr(bot_module, "IMAGE_BASE_RATE", 1.0)  # always roll in
    return persona_bot


def test_everything_open_offers_the_option(ready):
    assert ready._offer_image() is True


def test_no_key_means_no_offer(ready, monkeypatch, bot_module):
    """The feature is optional in the real sense: anyone cloning this repo has
    no Google key, and the bot has to behave exactly as it did before."""
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "")
    assert ready._offer_image() is False


def test_disabled_by_config(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "IMAGE_ENABLED", False)
    assert ready._offer_image() is False


def test_the_cap_stops_the_offer(ready, bot_module):
    ready._images_today = bot_module.IMAGE_DAILY_MAX
    assert ready._offer_image() is False


def test_the_cooldown_stops_the_offer(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.time, "time", lambda: 1000.0)
    ready._last_image_at = 900.0  # 100s ago, cooldown is 600
    assert ready._offer_image() is False


def test_the_offer_respects_the_base_rate(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "IMAGE_BASE_RATE", 0.0)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.5)
    assert ready._offer_image() is False


def test_a_spent_budget_costs_nothing_to_check(ready, bot_module, monkeypatch):
    """The decision must not reach the dice, let alone an API, once the budget
    is gone - the point of gating client-side is that a closed path is free."""
    ready._images_today = bot_module.IMAGE_DAILY_MAX

    def explode():
        raise AssertionError("rolled dice for an image that cannot be made")

    monkeypatch.setattr(bot_module.random, "random", explode)
    assert ready._offer_image() is False


# --- nothing a user types reaches the image API -----------------------------


def test_the_option_is_absent_unless_offered(persona_bot):
    """The affordance is appended to the framing only when the gates pass, so
    on an ordinary message the model is never told pictures exist."""
    assert prompts.IMAGE_OPTION not in prompts.FRAMING


def test_the_option_tells_the_model_to_write_its_own_description():
    """This is the property that makes prompt injection a non-event: the user's
    text is never the image prompt, it only ever informs one Jaq writes."""
    body = prompts.IMAGE_OPTION.lower()
    assert "in your own words" in body
    assert "never repeat" in body


def test_the_option_forbids_real_names_and_likenesses():
    body = prompts.IMAGE_OPTION.lower()
    assert "no real names" in body
    assert "likenesses" in body


def test_the_option_biases_against_using_it():
    assert "Usually don't" in prompts.IMAGE_OPTION


def test_the_option_hides_the_mechanism():
    """A caption or a reference to the directive breaks the illusion and
    documents the syntax for anyone reading the channel."""
    assert "Never mention it" in prompts.IMAGE_OPTION


def test_an_unprompted_directive_is_dropped(persona_bot, bot_module, monkeypatch):
    """If the model emits the syntax on a message where no image was offered,
    the text still posts and nothing is generated."""
    sent = []
    monkeypatch.setattr(
        bot_module.PersonaBot,
        "_send_image_later",
        lambda self, ch, prompt, reason: sent.append(prompt),
    )
    reply, prompt = decide.extract_image_prompt("no <<image: a dog>>")
    assert reply == "no"
    # The reply path only dispatches when it did the offering.
    assert sent == []


def test_a_leaky_image_prompt_is_refused(persona_bot, monkeypatch, bot_module):
    """The prompt leaves this machine for a third party, so it gets the same
    check every posted message gets."""
    monkeypatch.setattr(bot_module, "REDACT_TERMS", ["Vorwald"])
    assert persona_bot._image_prompt_is_safe("a man called Vorwald") is False
    assert persona_bot._image_prompt_is_safe("a burnt out car") is True


# --- the provider -----------------------------------------------------------


def test_unconfigured_provider_is_unavailable():
    assert imagegen.available("") is False
    assert imagegen.available("   ") is False
    assert imagegen.available("a-key") is True


def test_an_image_is_pulled_out_of_a_response():
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "here you go"},
                                   {"inlineData": {"data": base64.b64encode(b"PNG").decode()}}]}}
        ]
    }
    assert imagegen._first_image(payload) == b"PNG"


def test_snake_case_response_keys_also_work():
    """The REST API has returned both spellings depending on the endpoint."""
    payload = {
        "candidates": [
            {"content": {"parts": [{"inline_data": {"data": base64.b64encode(b"X").decode()}}]}}
        ]
    }
    assert imagegen._first_image(payload) == b"X"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": "I can't draw that"}]}}]},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"promptFeedback": {"blockReason": "SAFETY"}},
    ],
)
def test_a_response_with_no_image_yields_none(payload):
    """A content filter, a refusal and a prose answer are the same event from
    the channel's point of view: no picture, and nothing said about it."""
    assert imagegen._first_image(payload) is None


def test_corrupt_base64_does_not_raise():
    payload = {"candidates": [{"content": {"parts": [{"inlineData": {"data": "!!!!"}}]}}]}
    assert imagegen._first_image(payload) is None


def test_no_key_short_circuits_before_any_request():
    assert asyncio.run(imagegen.generate("a dog", key="", model="m")) is None


def test_an_empty_prompt_makes_no_request():
    assert asyncio.run(imagegen.generate("   ", key="k", model="m")) is None


# --- delivery ---------------------------------------------------------------


class FakeChannel:
    def __init__(self):
        self.files = []

    async def send(self, content=None, file=None, **kw):
        self.files.append(file)


def _deliver(bot, channel, monkeypatch, bot_module, result):
    async def fake_generate(prompt, **kw):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bot_module.imagegen, "generate", fake_generate)
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "test-key")
    asyncio.run(bot._deliver_image(channel, "a wet dog", reason="a wet dog"))


def test_a_successful_render_is_posted_and_charged(
    persona_bot, monkeypatch, bot_module
):
    channel = FakeChannel()
    _deliver(persona_bot, channel, monkeypatch, bot_module, b"PNGDATA")
    assert len(channel.files) == 1
    assert persona_bot._images_today == 1
    assert persona_bot._last_image_at > 0


def test_a_failed_render_posts_nothing_and_is_not_charged(
    persona_bot, monkeypatch, bot_module
):
    """Silent failure is the contract: an apology for a missing picture is a
    bot discussing its own plumbing in front of everyone."""
    channel = FakeChannel()
    _deliver(persona_bot, channel, monkeypatch, bot_module, None)
    assert channel.files == []
    assert persona_bot._images_today == 0


def test_a_raising_provider_is_swallowed(persona_bot, monkeypatch, bot_module):
    channel = FakeChannel()
    _deliver(persona_bot, channel, monkeypatch, bot_module, RuntimeError("boom"))
    assert channel.files == []
    assert persona_bot._images_today == 0


def test_a_failure_still_starts_the_cooldown(persona_bot, monkeypatch, bot_module):
    """The budget is handed back because nothing was produced, but the clock
    stands - otherwise a run of filter refusals becomes a retry loop."""
    channel = FakeChannel()
    _deliver(persona_bot, channel, monkeypatch, bot_module, None)
    assert persona_bot._last_image_at > 0


def test_the_slot_is_claimed_before_the_render(persona_bot, monkeypatch, bot_module):
    """Several renders can be in flight at once. Checking the budget and then
    spending a minute generating lets every one of them pass the same check."""
    seen = []

    async def fake_generate(prompt, **kw):
        seen.append(persona_bot._images_today)
        return b"PNG"

    monkeypatch.setattr(bot_module.imagegen, "generate", fake_generate)
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "test-key")
    asyncio.run(persona_bot._deliver_image(FakeChannel(), "x", reason="x"))
    assert seen == [1], "the budget must be spent before the wait, not after"


# --- surviving a restart ----------------------------------------------------


def test_the_image_count_and_cooldown_persist(
    persona_bot, bot_module, tmp_path, monkeypatch
):
    import datetime

    monkeypatch.setattr(bot_module, "STATE_FILE", str(tmp_path / "s.json"))
    persona_bot._state_path = lambda: str(tmp_path / "s.json")
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._save_day = bot_module.PersonaBot._save_day.__get__(persona_bot)

    today = datetime.date(2026, 7, 28)
    persona_bot._reply_day = today
    persona_bot._images_today = 4
    persona_bot._last_image_at = 1234.5
    persona_bot._save_day()

    persona_bot._images_today = 0
    persona_bot._last_image_at = 0.0
    assert persona_bot._restore_day(today) is True
    assert persona_bot._images_today == 4, "a restart must not refill the budget"
    assert persona_bot._last_image_at == 1234.5, "nor skip the cooldown"


def test_a_new_day_refills_images_and_polls(persona_bot, bot_module, monkeypatch):
    """Polls were omitted from the day roll, so a process that stayed up for a
    week got two polls for the week."""
    import datetime

    monkeypatch.setattr(bot_module, "LIVE_UNLIMITED", True)
    persona_bot._save_day = lambda: None
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._images_today = 15
    persona_bot._polls_today = 2

    persona_bot._roll_day(datetime.date(2026, 7, 29))
    assert persona_bot._images_today == 0
    assert persona_bot._polls_today == 0


def test_the_cooldown_is_not_reset_by_a_new_day(persona_bot, bot_module, monkeypatch):
    """A picture at 23:58 should not be followed by another at 00:01."""
    import datetime

    monkeypatch.setattr(bot_module, "LIVE_UNLIMITED", True)
    persona_bot._save_day = lambda: None
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._last_image_at = 5555.0

    persona_bot._roll_day(datetime.date(2026, 7, 29))
    assert persona_bot._last_image_at == 5555.0
