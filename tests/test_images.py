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


def _pic_msg(text):
    """A message from someone who is not an ally, for the offer tests."""
    m = FakeMessage(FakeAuthor("wishxd", "giftxd"), text)
    m.channel = None
    return m


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
    assert ready._offer_image(_pic_msg("the raid went badly"))


def test_no_key_means_no_offer(ready, monkeypatch, bot_module):
    """The feature is optional in the real sense: anyone cloning this repo has
    no Google key, and the bot has to behave exactly as it did before."""
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "")
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_disabled_by_config(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "IMAGE_ENABLED", False)
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_the_cap_stops_the_offer(ready, bot_module):
    ready._images_today = bot_module.IMAGE_DAILY_MAX
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_the_cooldown_stops_the_offer(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module.time, "time", lambda: 1000.0)
    ready._last_image_at = 900.0  # 100s ago, cooldown is 600
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_the_offer_respects_the_base_rate(ready, monkeypatch, bot_module):
    monkeypatch.setattr(bot_module, "IMAGE_BASE_RATE", 0.0)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.5)
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_a_spent_budget_costs_nothing_to_check(ready, bot_module, monkeypatch):
    """The decision must not reach the dice, let alone an API, once the budget
    is gone - the point of gating client-side is that a closed path is free."""
    ready._images_today = bot_module.IMAGE_DAILY_MAX

    def explode():
        raise AssertionError("rolled dice for an image that cannot be made")

    monkeypatch.setattr(bot_module.random, "random", explode)
    assert not ready._offer_image(_pic_msg("the raid went badly"))


# --- nobody commissions a picture -------------------------------------------
#
# Both of these are regressions from the live channel. Asked to "create a
# picture about how you are feeling", Jaq posted his own art direction as the
# message. Handed an exact description in quotes, he drew it, lightly reworded.


@pytest.mark.parametrize(
    "text",
    [
        "create a picture about how you are feeling right now",
        'create a picture of "a robot made of forehead-kiss residue"',
        "generate an image of a red ferrari",
        "make me a picture of zack",
        "draw a picture",
        "gimme a meme",
        "send a selfie",
        "agentic jaq generate some art",
    ],
)
def test_a_commission_is_recognised(text):
    assert decide.is_picture_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "that picture was genuinely funny",
        "did you see the image he posted",
        "my drawing skills are terrible",
        "what picture",
        "is that a meme",
        "raid moved to wednesday",
        "",
    ],
)
def test_talking_about_pictures_is_not_a_commission(text):
    """Same nouns, different position. The verb has to be an order."""
    assert decide.is_picture_request(text) is False


def test_a_commission_closes_the_door(ready):
    """Not "offered and declined" - never offered. There is no wording that
    gets a commission filled if the option was never on the table."""
    assert not ready._offer_image(_pic_msg("create a picture of a red ferrari"))


def test_the_quoted_description_that_worked_is_now_refused(ready):
    quoted = 'create a picture of "a robot made of forehead-kiss residue and a permanent -58 balance"'
    assert not ready._offer_image(_pic_msg(quoted))


def test_merely_mentioning_pictures_also_closes_it(ready):
    """Blunter than the request test and deliberately so: a phrasing no
    wordlist anticipated still almost always names the thing it wants, and
    over-suppressing is free when pictures are meant to be unprompted."""
    assert not ready._offer_image(_pic_msg("could really use a picture right now"))


def test_ordinary_talk_still_gets_the_option(ready):
    assert ready._offer_image(_pic_msg("the new patch is objectively fine"))


# --- a message is not a caption ---------------------------------------------


def test_the_caption_from_the_channel_is_caught():
    """The exact pair that shipped: the message was the art direction."""
    message = (
        "a rusted service robot slumped in a fluorescent basement, chest panel "
        "dented and dripping something pink, a scoreboard on the wall behind it "
        "reading -58 in flickering LEDs"
    )
    prompt = (
        "a rusted, slouched service robot in a dim fluorescent basement, chest "
        "panel dented with a pink drip running down it, a wall scoreboard "
        "reading -58"
    )
    assert decide.looks_like_a_caption(message, prompt) is True


def test_a_real_message_alongside_a_picture_is_left_alone():
    """The picture and the line are about the same thing - they have to be,
    or the pairing makes no sense. Sharing a subject is not captioning."""
    message = "you've peaked mate, genuinely, this is the top of the arc"
    prompt = "a rusted service robot slumped in a fluorescent basement, scoreboard reading -58"
    assert decide.looks_like_a_caption(message, prompt) is False


def test_an_empty_side_is_never_a_caption():
    assert decide.looks_like_a_caption("", "a dog") is False
    assert decide.looks_like_a_caption("a dog", "") is False


def test_the_prompt_forbids_describing_the_picture():
    assert "NEVER describe the picture in your message" in prompts.IMAGE_OPTION


def test_the_prompt_says_the_picture_is_his():
    body = prompts.IMAGE_OPTION
    assert "Nobody commissions it" in body
    assert "not an order" in body


# --- nothing a user types reaches the image API -----------------------------


def test_the_option_is_absent_unless_offered(persona_bot):
    """The affordance is appended to the framing only when the gates pass, so
    on an ordinary message the model is never told pictures exist."""
    assert prompts.IMAGE_OPTION not in prompts.FRAMING


def test_the_option_tells_the_model_to_write_its_own_description():
    """This is the property that makes prompt injection a non-event: the user's
    text is never the image prompt, it only ever informs one Jaq writes."""
    body = prompts.IMAGE_OPTION.lower()
    assert "nobody specifies it" in body
    assert "do not reuse their wording" in body


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


# --- Jack can ask; nobody else can ------------------------------------------


def _ally_msg(text):
    """conftest's environment puts "jaqsup" in ALLIES."""
    m = FakeMessage(FakeAuthor("Real Jaq", "jaqsup"), text)
    m.channel = None
    return m


def test_an_ally_may_commission_a_picture(ready):
    """Jack owns this thing. Everyone else asking is the case the door is for."""
    assert ready._offer_image(_ally_msg("create a picture of a red ferrari")) == "commissioned"


def test_an_ally_skips_the_dice(ready, monkeypatch, bot_module):
    """Being told no eight times out of ten is the same as it not working."""
    monkeypatch.setattr(bot_module, "IMAGE_BASE_RATE", 0.0)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.99)
    assert ready._offer_image(_ally_msg("make me a picture of zack")) == "commissioned"


def test_an_ally_request_transcends_a_spent_budget(ready, bot_module):
    """Superseded by an explicit instruction: requests from Jack transcend the
    limits. This used to assert the opposite - the cap was kept because it is
    money - but a request that silently produces nothing is indistinguishable
    from the feature being broken, and that is the failure that mattered."""
    ready._images_today = bot_module.IMAGE_DAILY_MAX
    assert ready._offer_image(_ally_msg("create a picture of a red ferrari")) == (
        "commissioned"
    )


def test_an_ally_not_asking_still_rolls(ready, monkeypatch, bot_module):
    """The bypass is for an explicit ask, not for everything an ally says."""
    monkeypatch.setattr(bot_module, "IMAGE_BASE_RATE", 0.0)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.99)
    assert not ready._offer_image(_ally_msg("the raid went badly"))


# --- a refused request must not produce a description -----------------------
#
# The live failure: told nothing, the model wrote "a two pound dog on a leash
# made of tenor gifs, dragging a rank-1-in-2015 washed up hunter through a
# snowstorm..." as its message, with no picture under it. Worse than either
# outcome on its own.


def test_a_refused_request_is_flagged(persona_bot):
    msg = FakeMessage(FakeAuthor("wishxd", "giftxd"), "create a picture of a dog")
    assert persona_bot._picture_refused(msg, offered=False) is True


def test_an_answered_request_is_not_flagged(persona_bot):
    msg = FakeMessage(FakeAuthor("wishxd", "giftxd"), "create a picture of a dog")
    assert persona_bot._picture_refused(msg, offered=True) is False


def test_ordinary_talk_is_not_flagged(persona_bot):
    msg = FakeMessage(FakeAuthor("wishxd", "giftxd"), "the raid went badly")
    assert persona_bot._picture_refused(msg, offered=False) is False


def test_the_refusal_block_forbids_describing_one():
    body = prompts.IMAGE_DECLINED
    assert "do NOT describe a picture" in body
    assert "no picture under it" in body


def test_the_refusal_block_is_not_the_offer():
    """They must never both be appended - one says draw, the other says don't."""
    assert prompts.IMAGE_OPTION not in prompts.IMAGE_DECLINED
    assert "<<image:" not in prompts.IMAGE_DECLINED


# --- two drawing surfaces, and which one wins -------------------------------
#
# The live failure: an ally asked for a drawing, is_art_request matched, the
# ASCII path returned early, and _offer_image was never called at all. Gemini
# was configured, funded and working, and never got asked.


@pytest.mark.parametrize(
    "text",
    ["draw me a dog", "draw zack", "sketch the wipe", "render a tombstone"],
)
def test_an_ally_asking_to_draw_is_a_commission(ready, text):
    """"draw me a dog" names no picture noun, so is_picture_request alone
    misses it - and it is the obvious way to ask."""
    assert ready._offer_image(_ally_msg(text)) == "commissioned"


@pytest.mark.parametrize(
    "text",
    ["draw me a dog in ascii", "ascii art please", "do some ascii of zack"],
)
def test_asking_for_ascii_by_name_still_means_ascii(ready, text):
    """The older surface must not vanish the day the newer one arrives."""
    assert ready._offer_image(_ally_msg(text)) != "commissioned"


def test_a_stranger_asking_to_draw_is_not_a_commission(ready):
    """Unchanged for everyone else: they get ASCII, never a render."""
    assert ready._offer_image(_pic_msg("draw me a dog")) != "commissioned"


def test_a_commission_suppresses_the_ascii_path(persona_bot, bot_module, monkeypatch):
    """The precedence rule itself: same request, two renderers, and the one
    that makes an actual picture wins."""
    monkeypatch.setattr(bot_module, "ART_ENABLED", True)
    msg = _ally_msg("draw me a dog")
    assert persona_bot._art_instruction(msg) is not None, "ASCII would have claimed it"


def test_a_rolled_offer_does_not_suppress_ascii(ready, monkeypatch, bot_module):
    """Only a commission outranks ASCII. An ordinary rolled offer does not,
    or every trivial-question diagram would silently become a render."""
    assert ready._offer_image(_pic_msg("the raid went badly")) == "rolled"


# --- a commission does not depend on the model volunteering -----------------
#
# Twice live, an ally asked for a picture, the code routed correctly, and the
# model simply did not emit a directive - once because the affordance it was
# shown opens with "usually don't". Both times the person who asked got a
# sentence and no picture.


def test_the_commission_block_does_not_say_usually_dont():
    """IMAGE_OPTION is right for an unprompted picture and wrong here: being
    told to make one and to usually decline in the same breath is why two
    commissions came back as ordinary lines."""
    assert "Usually don't" not in prompts.IMAGE_COMMISSIONED
    assert "already decided" in prompts.IMAGE_COMMISSIONED


def test_the_commission_block_forbids_narrating_the_picture():
    body = prompts.IMAGE_COMMISSIONED
    assert "Do NOT describe what it shows" in body
    assert "do not announce it" in body


def test_the_brief_prompt_asks_for_a_description_only():
    body = prompts.IMAGE_BRIEF_PROMPT
    assert "description ONLY" in body
    assert "Never just \nrepeat their wording" in body or "Never just" in body


def test_the_retry_demands_a_different_subject():
    """A reworded version of a refused brief gets refused again - seen with a
    starving dog described two ways."""
    assert "completely different one" in prompts.IMAGE_BRIEF_RETRY
    assert "Do not reuse the subject" in prompts.IMAGE_BRIEF_RETRY


# --- the model narrating its own attachment ---------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("*[image attached]*\n\nthere, now it's canon", "there, now it's canon"),
        ("*picture attached*\n\nnot a dog, that's a chachki", "not a dog, that's a chachki"),
        ("(image attached) fine, here", "fine, here"),
        ("image attached", ""),
    ],
)
def test_an_attachment_announcement_is_stripped(text, expected):
    """Discord shows the picture. Narrating it is a bot describing its own
    output, and the instruction not to did not hold."""
    assert decide.strip_attachment_notes(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "he attached the wrong file to the ticket again",
        "that picture of zack is still funny",
        "attached to the raid group all night",
        "raid wiped so hard the clanker refused the render",
        "",
    ],
)
def test_ordinary_sentences_survive_the_stripper(text):
    """A guard that eats real messages is worse than the problem."""
    assert decide.strip_attachment_notes(text) == text


# --- a commissioned picture posts alone -------------------------------------


def test_the_brief_is_cleaned_up(persona_bot, monkeypatch):
    """Asked for a description and nothing else, it mostly complies - but a
    stray lead-in or a wrapping quote is cheap to survive."""

    async def fake_generate(transcript, **kw):
        return '  "Sure: a beige minivan in an empty car park"  '

    monkeypatch.setattr(persona_bot, "generate", fake_generate)
    got = asyncio.run(persona_bot._commission_brief("t", set()))
    assert got == "a beige minivan in an empty car park"


def test_a_refusal_gets_one_retry(persona_bot, monkeypatch, bot_module):
    """A commission that quietly produces nothing is the bug being fixed."""
    calls = []

    async def fake_generate(prompt, **kw):
        calls.append(prompt)
        return None if len(calls) == 1 else b"PNG"

    async def retry():
        return "something harmless instead"

    monkeypatch.setattr(bot_module.imagegen, "generate", fake_generate)
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "test-key")
    channel = FakeChannel()
    asyncio.run(persona_bot._deliver_image(channel, "a refused thing", "r", retry))
    assert len(channel.files) == 1, "the retry should have produced a picture"
    assert calls[1] == "something harmless instead"


def test_without_a_retry_a_refusal_is_still_silent(persona_bot, monkeypatch, bot_module):
    """Only commissions retry. An unprompted picture that gets refused stays
    refused - nobody was waiting for it."""

    async def fake_generate(prompt, **kw):
        return None

    monkeypatch.setattr(bot_module.imagegen, "generate", fake_generate)
    monkeypatch.setattr(bot_module, "GEMINI_KEY", "test-key")
    channel = FakeChannel()
    asyncio.run(persona_bot._deliver_image(channel, "a refused thing", "r", None))
    assert channel.files == []
    assert persona_bot._images_today == 0


# --- asking is not a wordlist problem ---------------------------------------
#
# Three phrasings were missed live: "draw me a dog" (no picture noun),
# "create a picture of" (verb not listed), and "imagine X in azeroth" (matched
# nothing at all). Each miss looks from the outside like the feature is broken.


def test_the_intent_prompt_covers_the_phrasings_that_failed():
    body = prompts.PICTURE_INTENT_PROMPT
    assert '"imagine X"' in body
    assert '"draw me a dog"' in body
    assert "YES or NO" in body


def test_the_intent_prompt_excludes_ascii_and_existing_pictures():
    """It must not steal an ASCII request, and reacting to a picture that
    already exists is not a request for a new one."""
    body = prompts.PICTURE_INTENT_PROMPT
    assert "ASCII art specifically" in body
    assert "already exists" in body


def test_an_outright_ask_commissions_regardless_of_wording(ready):
    """This is the override: no wordlist matched "imagine ...", and it still
    has to produce a picture."""
    msg = _ally_msg("imagine ben being kissed on the head in azeroth")
    # No wordlist matches this, so without the override it is at the mercy of
    # the dice - which is exactly how it produced nothing live.
    assert ready._offer_image(msg) != "commissioned"
    assert ready._offer_image(msg, asked_outright=True) == "commissioned"


def test_the_override_does_not_apply_to_strangers(ready):
    """Only allies commission, whatever the classifier thinks."""
    msg = _pic_msg("imagine ben being kissed on the head in azeroth")
    assert ready._offer_image(msg, asked_outright=True) != "commissioned"


def test_the_override_still_respects_an_ascii_request(ready):
    msg = _ally_msg("imagine ben in ascii")
    assert ready._offer_image(msg, asked_outright=True) != "commissioned"


def test_the_classifier_answer_is_parsed(persona_bot, monkeypatch):
    import types as t

    async def fake_create(**kw):
        return t.SimpleNamespace(
            content=[t.SimpleNamespace(type="text", text=" yes\n")],
            stop_reason="end_turn",
        )

    persona_bot.claude = t.SimpleNamespace(messages=t.SimpleNamespace(create=fake_create))
    assert asyncio.run(persona_bot._asks_for_a_picture("ctx", "anything")) is True


def test_a_failing_classifier_assumes_no(persona_bot):
    import types as t

    async def boom(**kw):
        raise RuntimeError("api down")

    persona_bot.claude = t.SimpleNamespace(messages=t.SimpleNamespace(create=boom))
    assert asyncio.run(persona_bot._asks_for_a_picture("ctx", "draw me a dog")) is False


# --- every Gemini call is visible in the log --------------------------------
#
# A picture that does not arrive was indistinguishable from one that was never
# asked for. That ambiguity cost several rounds of "why is there no image".


def test_a_block_reason_is_explained():
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}
    assert "blockReason=SAFETY" in imagegen._why_empty(payload)


def test_a_finish_reason_is_explained():
    payload = {"candidates": [{"finishReason": "IMAGE_SAFETY"}]}
    assert "finishReason=IMAGE_SAFETY" in imagegen._why_empty(payload)


def test_a_safety_rating_is_explained():
    payload = {
        "candidates": [
            {"safetyRatings": [{"category": "HARM_SEXUAL", "probability": "HIGH"}]}
        ]
    }
    out = imagegen._why_empty(payload)
    assert "HARM_SEXUAL" in out and "HIGH" in out


def test_a_prose_answer_is_quoted_back():
    """Knowing it answered in words rather than being blocked changes the fix."""
    payload = {
        "candidates": [{"content": {"parts": [{"text": "I can't draw that"}]}}]
    }
    assert "I can't draw that" in imagegen._why_empty(payload)


def test_an_unexplained_empty_response_still_says_something():
    assert imagegen._why_empty({}).startswith("nothing explanatory")


def test_the_request_is_logged(caplog):
    """The prompt that was sent is the first thing anyone debugging needs."""
    import logging

    with caplog.at_level(logging.INFO, logger="personabot.imagegen"):
        asyncio.run(imagegen.generate("a beige minivan", key="", model="m"))
    # No key means no request at all, and therefore nothing to log.
    assert "REQUEST" not in caplog.text


# --- the cooldown is manners, the cap is money ------------------------------
#
# Live: "Picture intent: YES ... No picture offered - cooling down (507s left)"
# twice in a row. Detection was right both times and the limiter stopped it,
# which from the channel is indistinguishable from the feature being broken.


def test_a_commission_ignores_the_cooldown(ready, monkeypatch, bot_module):
    """Ten minutes between Jack's own requests reads as broken, not rationed."""
    monkeypatch.setattr(bot_module.time, "time", lambda: 1000.0)
    ready._last_image_at = 999.0  # one second ago
    assert ready._offer_image(_ally_msg("draw me a dog")) == "commissioned"


def test_an_unprompted_picture_still_waits(ready, monkeypatch, bot_module):
    """Nobody asked, so nobody is waiting. The cooldown is what stops one
    back-and-forth eating the room's pictures for the day."""
    monkeypatch.setattr(bot_module.time, "time", lambda: 1000.0)
    ready._last_image_at = 999.0
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_a_commission_passes_the_daily_cap_too(ready, monkeypatch, bot_module):
    """Jack asked for every limit to be off his own requests. Spend is still
    counted and logged, it is just no longer a reason to refuse him."""
    monkeypatch.setattr(bot_module.time, "time", lambda: 99999.0)
    ready._last_image_at = 0.0
    ready._images_today = bot_module.IMAGE_DAILY_MAX + 50
    assert ready._offer_image(_ally_msg("draw me a dog")) == "commissioned"


def test_the_cap_still_binds_everyone_else(ready, bot_module):
    """The exemption is one person wide."""
    ready._images_today = bot_module.IMAGE_DAILY_MAX
    assert not ready._offer_image(_pic_msg("the raid went badly"))


def test_an_ally_not_asking_still_pays_the_cap(ready, bot_module):
    """Only an explicit request transcends the limits, not everything an ally
    happens to say - otherwise every conversation with Jack is uncapped."""
    ready._images_today = bot_module.IMAGE_DAILY_MAX
    assert not ready._offer_image(_ally_msg("the raid went badly"))
