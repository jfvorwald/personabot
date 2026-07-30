"""GIFs: how this room already talks, and the easiest thing to get wrong.

FUTURE.md flagged it as the hardest link behaviour to do well and the reason
holds - a bad GIF is far more conspicuous than no GIF. A reaction that nearly
fits reads worse than words, because everyone can see what was aimed at and
missed. So it is rarer than pictures, and it declines rather than settling.
"""

from __future__ import annotations

import asyncio

import pytest

import decide
import gifs
import prompts


# --- pulling the search terms out of a reply --------------------------------


def test_terms_are_extracted_and_the_line_stays():
    text, terms = decide.extract_gif_terms(
        "thats you mate\n<<gif: guy walking away disappointed>>"
    )
    assert text == "thats you mate"
    assert terms == "guy walking away disappointed"


def test_a_gif_on_its_own_is_allowed():
    """Usually the stronger move - the GIF is the reply."""
    text, terms = decide.extract_gif_terms("<<gif: shrug>>")
    assert text == "" and terms == "shrug"


def test_an_ordinary_reply_is_untouched():
    assert decide.extract_gif_terms("just talking") == ("just talking", "")


def test_a_truncated_directive_is_still_stripped():
    """A reply cut off at the token limit must not post "<<gif: cut off"."""
    text, terms = decide.extract_gif_terms("mate\n<<gif: cut off")
    assert text == "mate" and terms == ""


def test_it_survives_the_other_directives():
    """All three parsers run on every reply and must not eat each other."""
    text = "look\n<<image: a dog>>\n<<gif: dog running>>\n<<reply>>"
    body, wants_reply = decide.wants_reply_to(text)
    body, terms = decide.extract_gif_terms(body)
    body, prompt = decide.extract_image_prompt(body)
    assert wants_reply is True
    assert terms == "dog running"
    assert prompt == "a dog"
    assert body == "look"


@pytest.mark.parametrize("text", ["a > b", "<3", "<pass>", "gif of a dog", ""])
def test_ordinary_text_is_not_a_directive(text):
    assert decide.extract_gif_terms(text)[1] == ""


# --- the provider -----------------------------------------------------------


def test_unconfigured_is_inert():
    assert gifs.available("") is False
    assert gifs.available("  ") is False
    assert gifs.available("a-key") is True


def test_no_key_makes_no_request():
    assert asyncio.run(gifs.find("shrug", key="")) is None


def test_empty_terms_make_no_request():
    assert asyncio.run(gifs.find("   ", key="k")) is None


def test_a_url_is_picked_from_the_results():
    payload = {
        "results": [
            {"media_formats": {"gif": {"url": "https://media.tenor.co/one.gif"}}},
            {"media_formats": {"tinygif": {"url": "https://media.tenor.co/two.gif"}}},
        ]
    }
    assert gifs._pick(payload) in (
        "https://media.tenor.co/one.gif",
        "https://media.tenor.co/two.gif",
    )


def test_the_preferred_format_wins_per_result():
    payload = {
        "results": [
            {
                "media_formats": {
                    "tinygif": {"url": "https://t/small.gif"},
                    "gif": {"url": "https://t/full.gif"},
                }
            }
        ]
    }
    assert gifs._pick(payload) == "https://t/full.gif"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": []},
        {"results": [{}]},
        {"results": [{"media_formats": {}}]},
        {"results": [{"media_formats": {"mp4": {"url": "https://t/x.mp4"}}}]},
    ],
)
def test_nothing_usable_yields_nothing(payload):
    """Declining is correct. Settling for an approximate reaction is the
    failure this whole feature has to avoid."""
    assert gifs._pick(payload) is None


def test_only_the_top_results_are_considered():
    """Tenor ranks by relevance, so anything past the top handful is a worse
    fit than saying nothing at all."""
    payload = {
        "results": [
            {"media_formats": {"gif": {"url": f"https://t/{i}.gif"}}}
            for i in range(40)
        ]
    }
    for _ in range(30):
        picked = gifs._pick(payload)
        index = int(picked.rsplit("/", 1)[1].split(".")[0])
        assert index < gifs.CANDIDATES


def test_the_content_filter_defaults_below_off():
    """The character is crude by design. Tenor's content is not the character's,
    and an unexpectedly graphic result is somebody else's material appearing
    under his name in a friend's server."""
    import inspect

    signature = inspect.signature(gifs.find)
    assert signature.parameters["content_filter"].default == "medium"


# --- the rule that keeps it rare -------------------------------------------


def test_the_option_asks_for_search_terms_not_a_description():
    body = prompts.GIF_OPTION
    assert "Search terms, not a description" in body
    assert "Not a \nsentence" in body or "not a" in body


def test_the_option_prefers_the_gif_alone():
    assert "usually the stronger move" in prompts.GIF_OPTION


def test_the_option_says_to_decline_when_unsure():
    """The specific failure: a reaction that nearly fits is worse than words,
    because everyone can see what was being aimed at."""
    body = prompts.GIF_OPTION
    assert "nearly fits is worse than words" in body
    assert "just talk" in body


def test_the_option_forbids_explaining_it():
    assert "never explain what it is" in prompts.GIF_OPTION
