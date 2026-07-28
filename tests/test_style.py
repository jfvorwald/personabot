"""No em dashes. Anywhere.

Enforced rather than remembered, because the rule is easy to keep by hand and
easy to lose the moment anything is generated or pasted.

It matters twice. It is a standing preference for everything written here, and
separately the prompt files are the model's own context - an em dash in
persona.md or prompts.py is not a style slip, it is teaching the bot a habit
that reads as machine-written the instant it lands in the channel.
"""

from __future__ import annotations

import glob
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Written as an escape so this file does not trip its own check.
EM_DASH = "\u2014"

# Files whose contents are handed to the model verbatim. A stray em dash in one
# of these does not just look wrong, it demonstrates the habit.
PROMPT_FILES = ["persona.md", "psychology.md", "prompts.py"]


def _paths(patterns):
    out = []
    for pattern in patterns:
        out.extend(glob.glob(os.path.join(ROOT, pattern)))
    return sorted(p for p in out if os.path.isfile(p))


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_no_em_dash_in_anything_the_model_reads(name):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} is optional and absent")
    text = open(path, encoding="utf-8").read()
    assert EM_DASH not in text, (
        f"{name} contains an em dash. It goes into the system prompt verbatim, "
        f"so it teaches the model to use them."
    )


@pytest.mark.parametrize(
    "path",
    _paths(["*.py", "tests/*.py", "*.md", "brain/*.md", "*.sh"]),
    ids=lambda p: os.path.relpath(p, ROOT),
)
def test_no_em_dash_in_the_repo(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    if EM_DASH not in text:
        return
    lines = [
        f"  line {i}: {line.strip()[:70]}"
        for i, line in enumerate(text.splitlines(), 1)
        if EM_DASH in line
    ]
    pytest.fail(
        f"{os.path.relpath(path, ROOT)} contains em dashes; use a hyphen:\n"
        + "\n".join(lines[:5])
    )


# --- the persona keeps its permissions --------------------------------------


def test_persona_permits_profanity():
    """Guards a permission that has been accidentally walked back before.

    Two separate brakes once suppressed it: a "profanity is seasoning, not the
    meal" caution in persona.md, and register-convergence in psychology.md
    telling it to match a clean-sounding room.
    """
    body = open(os.path.join(ROOT, "persona.md"), encoding="utf-8").read().lower()
    assert "you swear constantly" in body
    assert "if someone asks you to swear, swear" in body


def test_register_convergence_excludes_swearing():
    path = os.path.join(ROOT, "psychology.md")
    body = open(path, encoding="utf-8").read()
    assert "does not cover" in body and "how you swear" in body, (
        "psychology.md must carve profanity out of register matching, or a "
        "clean-sounding channel quietly instructs the bot to clean up too"
    )
