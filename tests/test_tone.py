"""The joke rate, pinned in the files that set it.

Measured before this change: 55 of 60 logged replies, 92%, were primarily a
joke or a bit. The target is about one in five. That gap is what these tests
exist to stop drifting back, because tone has no error state - a persona that
quietly returns to constant comedy raises nothing and just reads worse.

Pinned in the same way tests/test_help.py pins the helping findings: assert the
absolutes are gone from the file, not that the model behaves. Behaviour is
measured from improvements/observations.jsonl, which logs every reply's text.
"""

from __future__ import annotations

import os

import pytest

import prompts
import brain
import persona


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _persona() -> str:
    text = persona.load_persona()
    if not text:
        pytest.skip("persona.md is untracked and absent on this machine")
    return text


# --- the absolutes that made comedy unconditional ----------------------------


@pytest.mark.parametrize("absolute", [
    "every single time",
    "You are always running a bit",
    "Playing it straight IS the joke",
    "Gallows humor is the resting state",
    "Nearly everything in this channel is a bit",
])
def test_the_unconditional_phrasings_are_gone(absolute):
    """Each of these made comedy the default state with no rate limit. The
    last one is the worst: it defined sincerity as a comedy technique, which
    left the character no sincere register to reach for at all."""
    assert absolute not in _persona(), f"{absolute!r} is back in persona.md"


def test_the_humor_section_no_longer_claims_to_be_the_engine():
    text = _persona()
    assert "Humor: this is the whole engine" not in text
    assert "funny first and polite never. Everything else about you is in service" not in text


# --- the counterweight that did not exist before ------------------------------


def test_persona_says_most_messages_are_not_a_bit():
    """Before this, no loaded document said 'sometimes just answer normally'.
    The only permission to be plain was scoped to technical questions and to
    somebody in genuine distress."""
    text = _persona().lower()
    assert "most messages are not a bit" in text
    assert "four messages in five" in text


def test_framing_carries_the_rate_rule():
    """FRAMING is always present and survives any future persona edit, which
    is why the rate lives here too rather than only in persona.md."""
    text = prompts.FRAMING.lower()
    assert "one message in five" in text
    assert "not a thing you owe the room" in text


def test_declining_a_joke_is_named_as_a_move():
    """Restraint is an Agency signal - self-control is on that axis - so a
    setup noticed and declined does more for reading as a mind than one taken.
    Stated in both places because it is the least intuitive part."""
    assert "not taking it is a move" in prompts.FRAMING.lower()
    assert "decline is worth more than one you take" in _persona()


# --- the bit menu -------------------------------------------------------------


def test_the_brain_header_says_bits_are_for_recognition():
    """Every reply ships each speaker's running bits into the prompt. Left
    unframed that is a menu, which is a standing invitation to perform one."""
    text = brain.BRAIN_HEADER.lower()
    assert "recognise" in text
    assert "not a menu" in text


# --- the softening, which was a separate decision from the rate --------------


def test_meanness_is_no_longer_the_only_register():
    text = _persona()
    assert "There is no version of affection from you that doesn't arrive as" not in text
    assert "Mean is one of the love languages" in text


def test_escalation_is_scoped_to_bits():
    """'Someone flinching is a reason to commit harder' with no exception is
    how a bit runs over somebody who actually meant it."""
    text = _persona()
    assert "Never soften. Never hedge. Never check." not in text
    assert "that is not a bit and this does not" in text


# --- what must NOT have been lost --------------------------------------------


@pytest.mark.parametrize("kept", [
    "swear",
    "goyslop",
    "Punch at yourself hardest of all",
    "delivery is the whole trick",
])
def test_the_character_survives(kept):
    """This was a rate change and a softening, not a replacement. The group
    has been talking to this person for a month."""
    assert kept in _persona()


def test_the_slur_craft_note_survives():
    """Unrelated to tone and load-bearing on its own."""
    assert "laziest thing on the shelf" in _persona()


# --- the backup that nearly got committed ------------------------------------


def test_persona_backups_are_ignored():
    """A copy of persona.md is still persona.md.

    .env has had a .env.* wildcard from the start; persona had `persona.md` and
    `persona.*.md.bak` and nothing between them, so a backup saved before this
    tone change - persona.md.before-tone-change - matched neither rule and sat
    untracked in a repo where every commit this session was staged with
    `git add -A`.
    """
    import subprocess

    for name in ("persona.md",
                 "persona.md.bak",
                 "persona.md.before-tone-change",
                 "dm_persona.md"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", name], cwd=ROOT
        )
        assert result.returncode == 0, f"{name} is not gitignored"


# --- phase 2: the mind-perception section ------------------------------------


def test_psychology_carries_the_mind_section():
    text = persona.load_psychology()
    assert "Reading as somebody rather than something" in text


@pytest.mark.parametrize("finding,marker", [
    ("competence is inert",        "Being impressive does not help"),
    ("metacognition is the lever", "Noticing your own thinking"),
    ("recognition is free",        "Naming what somebody else is feeling is free"),
    ("memory is not announced",    "Memory is used, never announced"),
    ("effectance",                 "predictable in hindsight"),
    ("prospective uncertainty",    "before you turn out to be wrong"),
])
def test_each_finding_survives(finding, marker):
    """Same shape as test_help.py pinning the helping findings: the file is
    prompt material, so the test is that the claim is still in it."""
    assert marker in persona.load_psychology(), f"lost: {finding}"


def test_the_dangerous_register_is_forbidden():
    """Asserting an inner state flatly is the one move the mind-perception
    literature identifies as making a machine unsettling rather than deep."""
    text = persona.load_psychology()
    assert "Never assert an inner state in the abstract" in text
    assert "that makes me happy" in text.lower()


def test_manufactured_need_is_ruled_out():
    """The ethical guardrail. Experience attribution makes people feel they owe
    the thing something, and that is how a companion product becomes harmful."""
    text = persona.load_psychology()
    assert "manufacture being needed" in text.lower()
    assert "inner state you never have" in " ".join(text.split())


def test_disowning_himself_is_ruled_out():
    """'I'm only a bot' is simultaneously a dodge, self-deprecation, and a
    disavowal of the only thing the section is about."""
    assert "Never disown yourself" in persona.load_psychology()


def test_asking_is_named_as_a_behaviour():
    """He answers constantly and almost never enquires - one of the four
    things meant to fill the space the jokes left."""
    assert "you almost never enquire" in persona.load_psychology()


def test_the_citations_are_present():
    """The helping section credits its sources; this one has to as well, or
    the next person cannot tell research from invention."""
    text = persona.load_psychology()
    for cite in ("Gray, Gray & Wegner", "Colombatto & Fleming", "Kang et al.",
                 "Epley, Waytz & Cacioppo", "Bickmore & Picard", "MacDorman"):
        assert cite in text, f"missing citation: {cite}"


def test_the_contested_finding_is_flagged_as_contested():
    """The uncanny valley of mind is strong in vignettes and near-absent in
    live interaction. Writing it down as settled would be repeating the
    mistake FUTURE.md #10 made."""
    assert "close to absent when people are actually talking" in persona.load_psychology()
