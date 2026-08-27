"""Two ways a scan can poison the thing it is supposed to improve.

Both of these happened. On 2026-08-26 a forced rescan wrote 1164 messages of
the counterpart bot up as a person, filed under the handle "unknown", because
BRAIN_EXCLUDE matches display names and his had become fullwidth characters
inside angle brackets. The same scan wrote a name from REDACT_TERMS into
somebody's profile.

The second is the quieter of the two. Nothing in a profile reaches Discord, so
nothing in a profile looked like it needed checking - but a profile goes into
the system prompt, so a forbidden name there reads as an instruction to say it,
and guard.find_leak then kills every reply that takes the hint. The symptom is
replies that vanish.
"""

from __future__ import annotations

import brain


# --- no bot is ever profiled -------------------------------------------------


def test_a_bot_is_never_profiled_whatever_the_list_says():
    """Discord hands us this flag for free. It beats a string we have to keep
    in step with somebody's nickname."""
    assert brain._is_excluded("999", "someone", "Someone", is_bot=True) is True


def test_the_counterpart_that_actually_got_through():
    """His real display name on the day it happened."""
    assert brain._is_excluded(
        "1531138949857411253", "unknown", "⟨ＡＧＥＮＴＩＣ ＢＥＮ⟩", is_bot=True
    ) is True


def test_a_renamed_bot_is_still_a_bot():
    """The whole failure was a name match going stale. is_bot cannot."""
    for display in ("Agentic Ben", "⟨ＡＧＥＮＴＩＣ ＢＥＮ⟩", "something else entirely"):
        assert brain._is_excluded("1", "unknown", display, is_bot=True) is True


def test_a_human_is_still_judged_on_the_list():
    assert brain._is_excluded("42", "stranger", "Stranger", is_bot=False) is False


def test_the_id_match_still_works():
    if brain.BRAIN_EXCLUDE:
        assert brain._is_excluded(brain.BRAIN_EXCLUDE[0], "x", "X") is True


def test_is_bot_defaults_to_false():
    """Callers that predate the parameter must not start excluding everyone."""
    assert brain._is_excluded("42", "stranger", "Stranger") is False


# --- a redacted name never reaches a profile ---------------------------------


def test_the_check_uses_the_same_terms_the_live_bot_does():
    import guard

    text = "they talk about " + (brain.REDACT_TERMS[0] if brain.REDACT_TERMS else "x")
    if brain.REDACT_TERMS:
        assert guard.find_leak(text, [], brain.REDACT_TERMS) is not None


def test_a_clean_profile_passes():
    import guard

    clean = "Posts cat pictures and argues about raid times."
    assert guard.find_leak(clean, [], brain.REDACT_TERMS) is None


def test_every_profile_on_disk_is_clean():
    """The regression check. These are gitignored, so nothing else watches
    them, and the last scan put a forbidden name in one."""
    import glob
    import os

    import guard

    found = []
    for path in sorted(glob.glob(os.path.join(brain.PEOPLE_DIR, "*.md"))):
        leak = guard.find_leak(open(path).read(), [], brain.REDACT_TERMS)
        if leak:
            found.append(f"{os.path.basename(path)} ({leak})")
    assert not found, f"profiles carrying a forbidden term: {found}"


def test_no_bot_has_a_profile_on_disk():
    import glob
    import json
    import os

    index_path = brain.INDEX_PATH
    if not os.path.exists(index_path):
        return
    index = json.load(open(index_path)).get("people", {})
    handles = {
        os.path.basename(p)[:-3] for p in glob.glob(os.path.join(brain.PEOPLE_DIR, "*.md"))
    }
    bots = {v.get("handle") for v in index.values() if v.get("is_bot")}
    assert not (handles & bots), f"a bot has a profile: {sorted(handles & bots)}"


# --- an unfilled block is not knowledge --------------------------------------


def test_the_starter_placeholder_is_not_treated_as_written():
    """write_profile stamps this on every new profile. It is addressed to
    Jack, and it was reaching the prompt under a heading that promises Jaq's
    read of somebody and then delivers a blank."""
    placeholder = (
        "## Jaq's read\n\n"
        "_Nothing yet. Write how Jaq feels about them here - it survives "
        "every future scan._"
    )
    assert brain._is_written(placeholder) is False


def test_real_notes_are_treated_as_written():
    assert brain._is_written("## Jaq's read\n\nHe is a menace and you like it.") is True


def test_an_empty_block_is_not_written():
    assert brain._is_written("") is False
    assert brain._is_written("\n\n   \n") is False


def test_headings_alone_are_not_written():
    """Same rule the personnel loader applies to an unfilled notes file."""
    assert brain._is_written("## Stance\n\n## Handling\n") is False


def test_one_real_sentence_under_headings_is_enough():
    assert brain._is_written("## Stance\n\nHe thinks you take orders.\n") is True
