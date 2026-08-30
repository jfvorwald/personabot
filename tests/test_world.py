"""Knowing that the world moved.

The gap this closes is small and specific: somebody's PC died in a storm and
Jaq had no idea a storm had happened. Not being able to discuss the news -
being unaware the week had one.

Nothing here is on the reply path. A failed fetch, a missing file and a stale
one all mean he does not know what happened today, which is a state real people
are in constantly, so every one of them has to cost the bot nothing.
"""

from __future__ import annotations

import os
import time

import pytest

import world
import prompts

# Written as an escape so this file does not contain the thing it tests for -
# tests/test_style.py scans the whole repo, including this line.
DASH = "\u2014"


@pytest.fixture
def digest(tmp_path, monkeypatch):
    """Point the loader at a file we control."""
    path = tmp_path / "world.md"
    monkeypatch.setattr(world, "path", lambda: str(path))
    return path


# --- absent, stale and broken all mean "he does not know" --------------------


def test_no_digest_is_not_an_error(digest):
    assert world.load() == ""
    assert world.age_hours() is None
    assert world.describe() == "none yet"


def test_a_fresh_digest_loads(digest):
    digest.write_text("- a container ship is sideways again\n")
    assert "container ship" in world.load()


def test_a_stale_digest_is_treated_as_absent(digest):
    """Yesterday's news presented as today's is the one failure here that a
    reader can catch, because they were there for it."""
    digest.write_text("- something that happened on tuesday\n")
    old = time.time() - 60 * 60 * 50
    os.utime(digest, (old, old))
    assert world.load(stale_hours=36) == ""
    assert world.load(stale_hours=0) != "", "0 should disable the check, not block everything"


def test_an_empty_digest_is_absent(digest):
    digest.write_text("   \n\n")
    assert world.load() == ""


def test_headings_with_nothing_under_them_are_absent(digest):
    """Third time this rule has been needed in this repo. A fetch that returned
    nothing usable must read as absent, not as a promise of news followed by a
    blank."""
    digest.write_text("# Today\n\n## World\n\n## Games\n")
    assert world.load() == ""


def test_one_real_line_makes_it_real(digest):
    digest.write_text("# Today\n\n- blizzard announced another classic server\n")
    assert world.load() != ""


def test_the_budget_is_enforced(digest):
    """One line longer than the entire budget is the only case cut mid-word.
    Whole-lines-only must not be able to mean no lines at all."""
    digest.write_text("- " + "x" * 5000)
    assert len(world.load(max_chars=500)) == 500


def test_an_unreadable_file_is_not_an_error(digest, monkeypatch):
    digest.write_text("- something")
    monkeypatch.setattr(world, "age_hours", lambda: 1.0)
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError))
    assert world.load() == ""


# --- the fetch never takes the bot down --------------------------------------


REAL = "- steam had an outage\n- blizzard announced a classic server\n- storms grounded flights"


def _client(raise_on_call=False, stop_reason="end_turn", text=REAL):
    class Msgs:
        async def create(self, **kw):
            if raise_on_call:
                raise RuntimeError("search is down")
            import types
            return types.SimpleNamespace(
                stop_reason=stop_reason,
                stop_details=None,
                content=[types.SimpleNamespace(type="text", text=text)],
            )
    import types
    return types.SimpleNamespace(messages=Msgs())


def test_a_failed_fetch_keeps_the_previous_digest(digest):
    import asyncio
    digest.write_text("- yesterday's still-good digest\n")
    ok = asyncio.run(world.refresh(_client(raise_on_call=True), "m", "p"))
    assert ok is False
    assert "yesterday" in digest.read_text(), "a failed fetch destroyed the old one"


def test_a_refusal_keeps_the_previous_digest(digest):
    import asyncio
    digest.write_text("- previous\n")
    ok = asyncio.run(world.refresh(_client(stop_reason="refusal"), "m", "p"))
    assert ok is False
    assert "previous" in digest.read_text()


def test_an_empty_response_keeps_the_previous_digest(digest):
    import asyncio
    digest.write_text("- previous\n")
    ok = asyncio.run(world.refresh(_client(text="   "), "m", "p"))
    assert ok is False
    assert "previous" in digest.read_text()


def test_a_good_fetch_writes(digest):
    import asyncio
    ok = asyncio.run(world.refresh(_client(text=REAL), "m", "p"))
    assert ok is True
    assert "steam" in digest.read_text()


# --- the guardrail, which is applied at fetch time ----------------------------


@pytest.mark.parametrize("banned", [
    "Politics", "War", "terrorism", "Disasters", "Crime", "death",
])
def test_the_prompt_excludes_the_heavy_categories(banned):
    """Filtered when the digest is WRITTEN, so the material never reaches a
    persona that treats everything as material. Same bargain guard.py makes:
    the cheapest control is having nothing there to find."""
    assert banned.lower() in prompts.WORLD_PROMPT.lower()


def test_the_prompt_says_never_whatever_the_search_returns():
    assert "NEVER include" in prompts.WORLD_PROMPT
    assert "whatever the search returns" in prompts.WORLD_PROMPT


def test_weather_is_allowed_until_somebody_is_hurt():
    """The one category with a line drawn through the middle of it."""
    assert "stops counting the moment anybody is hurt" in prompts.WORLD_PROMPT


def test_the_digest_is_raw_material_not_a_message():
    """It goes into a prompt that will write in character. If the digest is
    already in character, the persona gets applied twice."""
    body = prompts.WORLD_PROMPT.lower()
    assert "do not editorialise" in body
    assert "not a message" in body


# --- how it is used ----------------------------------------------------------


def test_the_header_does_not_ask_him_to_bring_things_up():
    """A bot that works the news into conversation is performing an awareness
    rather than having one, which is the exact failure the tone work fixed."""
    body = prompts.WORLD_HEADER.lower()
    assert "only where it genuinely fits" in body
    assert "most replies will not touch it" in body
    assert "never work one in because it is there" in body


def test_the_header_forbids_announcing_it():
    assert "never announce that you have been keeping up" in prompts.WORLD_HEADER.lower()


# --- prose is not a digest ----------------------------------------------------


def test_an_apology_is_not_a_digest():
    """The first live fetch hit the search tool's usage limit, and the model,
    unable to comply, wrote a paragraph addressed to a person. That is prose,
    so the blank-check passed it, and it was written to the file - it would
    have been injected under a heading promising world events."""
    apology = (
        "I tried to pull fresh headlines just now, but the web search tool hit\n"
        "its usage limit for this session, and every retry has failed.\n\n"
        "Rather than guess at what is going on and risk feeding you outdated\n"
        "specifics, I would rather be straight with you.\n\n"
        "Want me to give it another shot?"
    )
    assert world.is_digest(apology) is False


def test_a_real_digest_is_accepted():
    assert world.is_digest(
        "- steam had an outage on thursday\n"
        "- blizzard announced another classic server\n"
        "- storms across the northeast, flights grounded\n"
    ) is True


def test_headings_around_bullets_are_fine():
    assert world.is_digest(
        "# Today\n- one thing\n- another thing\n- a third thing\n"
    ) is True


def test_a_couple_of_bullets_is_not_enough():
    """Two bullets and a paragraph is the shape a partial failure takes."""
    assert world.is_digest("- one thing\n- another\nand then it all went wrong") is False


def test_bullets_buried_in_prose_are_rejected():
    text = (
        "Here is what I found, though the search was patchy and I could not\n"
        "verify most of it, so treat the following with some caution please.\n"
        "- a thing\n- another thing\n- a third\n"
        "I would recommend checking these yourself before relying on them.\n"
        "Let me know if you would like me to try again later on.\n"
    )
    assert world.is_digest(text) is False


def test_prose_does_not_overwrite_a_good_digest(digest):
    import asyncio
    digest.write_text("- yesterday's perfectly good digest\n")
    ok = asyncio.run(world.refresh(
        _client(text="I could not run the search, sorry about that. Shall I retry?"),
        "m", "p",
    ))
    assert ok is False
    assert "yesterday" in digest.read_text()


def test_em_dashes_never_reach_the_file(digest):
    """The digest goes into the system prompt, where an em dash is not a style
    violation but a lesson - every one the model reads teaches it the habit.
    This file is generated, so tests/test_style.py never sees it."""
    import asyncio
    asyncio.run(world.refresh(
        _client(text=f"- a thing {DASH} with an em dash\n- another\n- a third"),
        "m", "p",
    ))
    assert DASH not in digest.read_text()


# --- the model narrating itself is not news -----------------------------------


def test_preamble_before_the_first_bullet_is_dropped():
    """A live fetch opened with "Good, I have the earlier results saved. Let me
    parse and inspect all of them now instead of making new search calls." -
    process narration, then a lead-in sentence. The bullets outnumbered it so
    the shape check passed, and it would have reached the prompt under a
    heading promising world events."""
    text = (
        "Good, I have the earlier results saved. Let me parse them now.\n"
        "Here's what's actually happening right now:\n"
        "- rockstar showed 30 minutes of the next gta\n"
        "- gpu prices are rising again\n"
        "- wow nerfed a set bonus in a hotfix\n"
    )
    out = world._from_first_bullet(text)
    assert out.startswith("- rockstar")
    assert "Let me parse" not in out
    assert "Here's what's actually" not in out


def test_a_clean_digest_is_untouched():
    text = "- one\n- two\n- three"
    assert world._from_first_bullet(text) == text


def test_a_heading_above_the_bullets_is_dropped_too():
    """Harmless, but the header already says what this is."""
    assert world._from_first_bullet("# Today\n- one\n- two").startswith("- one")


def test_the_preamble_is_stripped_on_write(digest):
    import asyncio
    asyncio.run(world.refresh(
        _client(text="Let me check my earlier results.\n- a thing\n- another\n- a third"),
        "m", "p",
    ))
    assert digest.read_text().startswith("- a thing")


# --- the budget cuts whole lines ----------------------------------------------


def test_the_budget_cuts_on_a_line_boundary(digest):
    """A bullet cut off mid-word reads as a broken prompt rather than a short
    one. Seen live: the last entry ended on "advancing roboti"."""
    digest.write_text("- aaaa\n- bbbb\n- cccc\n- dddd\n")
    out = world.load(max_chars=16)
    assert not out.endswith(("a", "b", "c", "d")) or out.count("\n") + 1 == len(
        [l for l in out.splitlines() if l]
    )
    for line in out.splitlines():
        assert line in "- aaaa\n- bbbb\n- cccc\n- dddd".splitlines()
