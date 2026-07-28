"""Choosing a reaction.

The budget arithmetic and emote selection, separated from the Discord calls
that apply them. Pure enough to test without a gateway; the client-side half
(fetching guild emotes, adding the reaction) stays in bot.py where the message
object lives.
"""

from __future__ import annotations

# The stock unicode reactions skew warm, which is the wrong register for this
# persona entirely. This set is deliberately unfriendly.
STANDARD_EMOJI = ["💀", "👀", "🫡", "🤨",
                  "😐", "🔥", "⚰️", "🥀"]


def offerable(custom_names, recent) -> list[str]:
    """Which emotes to put in front of the model.

    Custom emote names are opaque - nobody can infer what ":bcb:" depicts - so
    left to itself the model reaches for the one or two it recognises and
    reacts identically every time, which is a louder tell than not reacting at
    all. Withholding the recent picks forces rotation without the model needing
    to understand any individual emote.
    """
    recent = set(recent)
    return [n for n in list(custom_names) + STANDARD_EMOJI if n not in recent]


def parse_choice(raw: str | None, valid) -> str | None:
    """Read the model's answer, or None if it declined or invented one."""
    if not raw:
        return None
    choice = raw.strip().strip(":")
    if not choice or choice.upper() == "PASS":
        return None
    return choice if choice in set(valid) else None


def within_budget(spent: int, cap: int) -> bool:
    """cap of 0 means no limit."""
    return not cap or spent < cap
