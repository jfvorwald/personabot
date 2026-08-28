"""GIFs from a curated pool.

This began as a Tenor client, which was dead on arrival - Tenor stopped issuing
keys in January 2026 and started erroring in June, and Discord's own picker is
client-side and not callable by a bot.

The pool suits the problem better than search ever did. The hard part was never
finding *a* GIF, it was that a bad one is far more conspicuous than none: a
reaction that nearly fits reads worse than words, because everyone can see what
was aimed at. Searching an index gambles on that every time. These tests defend
the properties that make a curated pool not gamble.
"""

from __future__ import annotations

import pytest

import decide
import gifs
import prompts


POOL = """
# my pool, with a comment

- https://t/shrug.gif | shrug, dont care, whatever
- https://t/facepalm.gif | facepalm, disbelief
- https://t/nod.gif
not a list item at all
- broken line with no url | shrug
"""


# --- reading a file a person maintains by hand ------------------------------


def test_entries_and_tags_are_parsed():
    pool = gifs.parse(POOL)
    assert len(pool) == 3
    assert pool[0].url == "https://t/shrug.gif"
    assert pool[0].tags == ["shrug", "dont care", "whatever"]


def test_comments_and_prose_are_ignored():
    """The file is documentation as much as data - notes must be free."""
    assert all("not a list item" not in g.url for g in gifs.parse(POOL))


def test_a_malformed_line_costs_that_line_only():
    """Somebody maintains this by pasting links into it."""
    assert len(gifs.parse(POOL)) == 3


def test_an_entry_with_no_tags_survives_parsing():
    assert gifs.parse(POOL)[2].tags == []


def test_an_empty_or_missing_pool_is_survivable():
    assert gifs.parse("") == []
    assert gifs.parse(None) == []


# --- the menu the model sees ------------------------------------------------


def test_the_catalogue_is_numbered_tags():
    menu = gifs.catalogue(gifs.parse(POOL))
    assert "1. shrug, dont care, whatever" in menu
    assert "2. facepalm, disbelief" in menu


def test_the_catalogue_never_contains_a_url():
    """A URL in the prompt is a URL the model can paste directly, bypassing
    every budget and cooldown."""
    menu = gifs.catalogue(gifs.parse(POOL))
    assert "http" not in menu


def test_untagged_entries_are_not_offered():
    """It is picked on tags alone, so an untagged GIF can never be chosen."""
    menu = gifs.catalogue(gifs.parse(POOL))
    assert "3." not in menu


def test_the_catalogue_is_bounded():
    """A pool of a thousand is a prompt of a thousand lines."""
    big = "\n".join(f"- https://t/{i}.gif | tag{i}" for i in range(200))
    assert len(gifs.catalogue(gifs.parse(big), limit=60).splitlines()) == 60


# --- resolving a pick -------------------------------------------------------


def test_a_valid_pick_resolves():
    pool = gifs.parse(POOL)
    assert gifs.choose(pool, 2).url == "https://t/facepalm.gif"


@pytest.mark.parametrize("number", [0, -1, 99, 4])
def test_an_invalid_pick_is_a_miss_not_a_fallback(number):
    """A GIF nobody chose is exactly the approximate reaction this feature
    exists to avoid, so out of range posts nothing."""
    assert gifs.choose(gifs.parse(POOL), number) is None


def test_by_tag_finds_a_match():
    assert gifs.by_tag(gifs.parse(POOL), "facepalm").url == "https://t/facepalm.gif"


def test_by_tag_declines_rather_than_approximating():
    assert gifs.by_tag(gifs.parse(POOL), "elephant") is None
    assert gifs.by_tag(gifs.parse(POOL), "") is None


# --- pulling the pick out of a reply ----------------------------------------


def test_a_pick_is_extracted_and_the_line_stays():
    text, pick = decide.extract_gif_terms("thats you mate\n<<gif: 4>>")
    assert text == "thats you mate"
    assert pick == 4


def test_a_gif_on_its_own_is_allowed():
    """Usually the stronger move - the GIF is the reply."""
    text, pick = decide.extract_gif_terms("<<gif: 2>>")
    assert text == "" and pick == 2


def test_an_ordinary_reply_is_untouched():
    assert decide.extract_gif_terms("just talking") == ("just talking", 0)


def test_a_truncated_directive_is_still_stripped():
    text, pick = decide.extract_gif_terms("mate\n<<gif: ")
    assert text == "mate" and pick == 0


def test_a_non_numeric_pick_is_no_pick():
    """It was given a numbered menu. Anything else is a misunderstanding, and
    guessing at what it meant would post a GIF nobody chose."""
    assert decide.extract_gif_terms("<<gif: something funny>>")[1] == 0


def test_it_survives_the_other_directives():
    """All three parsers run on every reply and must not eat each other."""
    text = "look\n<<image: a dog>>\n<<gif: 3>>\n<<reply>>"
    body, wants_reply = decide.wants_reply_to(text)
    body, pick = decide.extract_gif_terms(body)
    body, prompt = decide.extract_image_prompt(body)
    assert wants_reply is True and pick == 3 and prompt == "a dog"
    assert body == "look"


@pytest.mark.parametrize("text", ["a > b", "<3", "<pass>", "gif of a dog", ""])
def test_ordinary_text_is_not_a_directive(text):
    assert decide.extract_gif_terms(text)[1] == 0


# --- the rule that keeps it rare and honest ---------------------------------


def test_the_option_says_there_is_no_searching():
    """It has a fixed list. Without saying so it will try to invent one."""
    assert "there is \nno searching" in prompts.GIF_OPTION or "no searching" in prompts.GIF_OPTION


def test_the_option_says_to_decline_when_nothing_fits():
    """A near-miss reads worse than words. The rule survived a rewrite that
    changed its wording, so the test is on the behaviour and not the sentence."""
    body = prompts.GIF_OPTION.lower()
    assert "has to actually fit" in body
    assert "no searching for a better one" in body
    assert "use words" in body


def test_the_option_prefers_the_gif_alone():
    body = prompts.GIF_OPTION.lower()
    assert "can be your whole reply" in body
    assert "send \nnothing with it" in body or "send nothing with it" in body


def test_the_option_forbids_explaining_it():
    body = prompts.GIF_OPTION.lower()
    assert "no caption, no explanation" in body


def test_the_option_leads_with_permission_not_warning():
    """It was offered twenty-one times and taken zero. The first version spent
    three of five bullets discouraging it and closed on "everyone can see that
    you missed" - IMAGE_OPTION had already failed this exact way once, opening
    with "usually don't". A block that opens by talking you out of the thing
    talks you out of the thing."""
    first = prompts.GIF_OPTION.strip().splitlines()[0].lower()
    for deterrent in ("worse", "missed", "not", "avoid", "rarely"):
        assert deterrent not in first, f"opens with a deterrent: {first!r}"
    assert "can be your whole reply" in first


def test_the_option_carries_the_catalogue():
    """Without the menu substituted in, it is an instruction to invent one."""
    assert "{catalogue}" in prompts.GIF_OPTION
    filled = prompts.GIF_OPTION.format(catalogue="1. shrug")
    assert "1. shrug" in filled


# --- documentation is not data ------------------------------------------------


def test_the_worked_example_is_not_parsed_as_pool_entries():
    """gifs.md ships as its own instructions, and the format section shows
    three sample entries inside a fenced block with URLs xxxxx, yyyyy, zzzzz.
    Parsed as data they are a pool of dead links that reports as populated -
    which is what happened for a month, with load() returning four entries for
    a file containing no real GIFs at all."""
    text = """# The GIF pool

## Format

```
- https://media.tenor.com/xxxxx/shrug.gif | shrug, dont care
- https://media.tenor.com/yyyyy/facepalm.gif | facepalm, disbelief
```

## Pool

- https://media.tenor.com/real/actual.gif | real, usable
"""
    pool = gifs.parse(text)
    assert len(pool) == 1, [g.url for g in pool]
    assert pool[0].url.endswith("actual.gif")


def test_an_unclosed_fence_does_not_eat_the_pool():
    """A missing closing fence should cost the rest of the file, not silently
    return an empty pool that looks like 'GIFs are switched off'."""
    text = "```\n- https://x/a.gif | a\n"
    assert gifs.parse(text) == []


def test_the_real_pool_file_has_no_placeholder_links():
    """A placeholder posts a dead image into the channel, which is worse than
    posting nothing - the whole reason there is no search API behind this."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "gifs.md")
    if not os.path.exists(path):
        pytest.skip("gifs.md is gitignored and absent on this machine")
    for gif in gifs.parse(open(path).read()):
        assert "PLACEHOLDER" not in gif.url.upper(), (
            f"{gif.url} is a placeholder - gifs.md still needs real links"
        )
