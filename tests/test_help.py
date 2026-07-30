"""Real help, when someone actually wants it.

The research says getting this wrong is worse than not doing it: advice nobody
asked for produces contrary behaviour rather than indifference. So the question
is not "did they say the word help" but "is this a concrete solvable problem" -
because in a group like this the request almost never arrives as a request.
"""

from __future__ import annotations

import pytest

import decide
import prompts


# --- the free pre-filter ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "anyone know why wow keeps crashing on alt tab",
        "my addons all broke after the update",
        "cant get my mic working in discord",
        "the raid timer is showing the wrong count",
        "is this supposed to happen",
    ],
)
def test_possible_trouble_reaches_the_real_check(text):
    assert decide.might_need_help(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "lol",
        "ben kiss mari",
        "wednesday",
        "",
        "that was genuinely funny",
    ],
)
def test_plain_banter_never_costs_a_call(text):
    """The classification is what decides; this only avoids paying for it on
    messages that are obviously not a problem."""
    assert decide.might_need_help(text) is False


def test_the_prefilter_is_loose_on_purpose():
    """A false positive costs one small call. A false negative costs somebody
    the answer they needed, so the asymmetry is deliberate."""
    assert decide.might_need_help("why is zack like this") is True


# --- the judgement ----------------------------------------------------------


def test_the_test_is_solvable_not_interrogative():
    """Most people here never ask outright - it arrives as a flat statement of
    the problem and nothing else."""
    body = prompts.HELP_INTENT_PROMPT
    assert "CONCRETE AND SOLVABLE" in body
    assert "even with no question anywhere in it" in body


def test_a_general_lament_is_excluded_by_example():
    """The one place an example earns its place: the line between "everything I
    touch breaks" and "my addons broke" is the whole discriminator."""
    assert "not a problem with a fix" in prompts.HELP_INTENT_PROMPT


def test_bad_news_is_never_treated_as_a_problem_to_solve():
    """Offering to fix someone's redundancy or their marriage is the worst
    possible misfire, so it is ruled out explicitly rather than left to
    judgement."""
    assert "do not offer to solve a life" in prompts.HELP_INTENT_PROMPT


def test_asking_about_jaq_is_not_a_help_request():
    assert "asking what YOU think" in prompts.HELP_INTENT_PROMPT


# --- what helping looks like ------------------------------------------------


def test_help_mode_demands_the_why_not_just_the_what():
    """Autonomy-oriented rather than dependency-oriented help. "Do X" leaves
    them dependent next time; the reason does not."""
    body = prompts.HELP_MODE
    assert "Explain the why, not only the what" in body
    assert "leaves them dependent on you next" in body


def test_help_mode_forbids_guessing():
    """Confident wrong help is worse than no help, because it gets acted on."""
    assert "look it up" in prompts.HELP_MODE
    assert "Confident wrong" in prompts.HELP_MODE


def test_help_mode_does_not_let_it_become_a_favour():
    """The moment helping becomes a thing you did for them, it costs them."""
    body = prompts.HELP_MODE
    assert "Do not comment on the fact that they asked" in body
    assert "into a" in body and "favour" in body


def test_help_mode_says_it_once():
    """Repeating advice converts it into pressure, and pressure is what
    produces the reactance backlash."""
    assert "do not repeat the advice" in prompts.HELP_MODE


def test_help_mode_keeps_the_character():
    """A helpful stranger is a worse outcome than a friend who knows the
    answer."""
    body = prompts.HELP_MODE
    assert "Stay yourself" in body
    assert "not a help desk" in body


def test_help_mode_forbids_being_funny_instead_of_useful():
    assert "funny instead of being useful" in prompts.HELP_MODE


# --- the psychology it consults ---------------------------------------------


def test_the_psychology_file_carries_the_helping_research():
    import os

    from paths import at_root

    with open(at_root("psychology.md"), encoding="utf-8") as f:
        body = f.read()
    assert "Helping, when someone actually wants it" in body
    # The four findings the behaviour is built on.
    assert "autonomy" in body.lower() and "dependency" in body.lower()
    assert "reactance" in body.lower()
    assert "costs the asker" in body
    assert "Match the kind of support" in body


def test_the_psychology_is_cited_rather_than_invented():
    from paths import at_root

    with open(at_root("psychology.md"), encoding="utf-8") as f:
        body = f.read()
    for name in ("Nadler", "Addis", "reactance to unsolicited"):
        assert name in body, f"{name} should be credited"


def test_helping_is_kept_distinct_from_influence():
    """The persuasion half of the original material is still excluded, and the
    distinction needs stating or the next person will assume it crept back."""
    from paths import at_root

    with open(at_root("psychology.md"), encoding="utf-8") as f:
        body = f.read()
    assert "deliberately excluded" in body
    assert "not the same subject" in body


# --- not understanding is different from being stuck ------------------------
#
# The first version was built entirely around broken things, and every request
# for an explanation reached nothing: "what actually is a vpn" failed both the
# pre-filter and the judgement.


@pytest.mark.parametrize(
    "text",
    [
        "what actually is a vpn, like what does it do",
        "i dont understand how any of this ai stuff works",
        "whats the difference between ddr4 and ddr5, does it matter",
        "someone explain what a gpu even does",
        "is a nas worth it over just an external drive",
        "eli5 what a container actually is",
    ],
)
def test_explanation_requests_reach_the_real_check(text):
    assert decide.might_need_help(text) is True


def test_both_kinds_of_yes_are_named():
    body = prompts.HELP_INTENT_PROMPT
    assert "being STUCK" in body
    assert "not\nUNDERSTANDING something" in body or "UNDERSTANDING something" in body


def test_the_subject_decides_not_the_tone():
    """"what does a gpu even do" is someone who does not know what a gpu does.
    The same shape aimed at a person is a dig."""
    body = prompts.HELP_INTENT_PROMPT
    assert "LOOK AT THE SUBJECT, NOT THE TONE" in body
    assert "aimed at a PERSON" in body


def test_borderline_resolves_toward_helping_except_for_a_life():
    """The tie-break that recovered the misses, with the one exception that
    must never be traded away."""
    body = prompts.HELP_INTENT_PROMPT
    assert "BORDERLINE, ANSWER YES" in body
    assert "it is absolute" in body


def test_help_mode_explains_at_their_level():
    body = prompts.HELP_MODE
    assert "Start from what they already know" in body
    assert "One concrete comparison" in body


def test_help_mode_forbids_talking_down():
    """Being talked down to is worse than being unanswered."""
    body = prompts.HELP_MODE
    assert "never explain what they clearly \\\nalready know" in body or "already know" in body
    assert "talking down" in body


# --- the persona claims the competence --------------------------------------


def test_the_persona_establishes_technical_expertise():
    """It established none at all, so a technical question landed on a
    character with no reason to know the answer."""
    from paths import at_root

    try:
        with open(at_root("persona.md"), encoding="utf-8") as f:
            body = f.read()
    except OSError:
        pytest.skip("persona.md is untracked; nothing to check on a fresh clone")
    assert "You actually know technology" in body
    assert "Pitch it at them" in body
    # Competence without performance: the explanation is the demonstration.
    assert "Do not perform expertise" in body
    # Unimpressed is in character; unhelpful is not.
    assert "still answer it" in body
