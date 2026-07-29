"""Which version of himself Jaq is being right now.

There are two contexts today - the Team Slayer channel, and a private line with
the person who built him - and they are genuinely different characters rather
than one character at two volumes. There will be more: another server, another
person's DM, a channel where the room does not know him.

So the question "who am I here" is asked in one place and answered from a
table, rather than being an `if dm: ... else: ...` that has to be found and
edited in five places the first time a third context turns up.

A profile is two things:

    document   who he is here. A file, so it is edited without touching code.
    mode       how the machinery behaves here. Not a style setting - it decides
               whether the room exists at all.

The two modes are meaningfully different, which is why this is not a single
persona file with a tone knob:

    room       an audience. Dice rolls, hanging back, daily budgets, the
               confidentiality directive, channel vocabulary, notes on the
               other people present.
    private    one person, who knows exactly what he is. None of the above:
               answer every time, no performance, nothing withheld about his
               own construction.

Adding a context is adding a row. Adding a *third mode* would be real work, and
should be resisted until something genuinely does not fit these two.
"""

from __future__ import annotations

ROOM = "room"
PRIVATE = "private"


class Profile:
    def __init__(self, name: str, mode: str, document: str):
        self.name = name
        self.mode = mode
        self.document = document

    @property
    def is_private(self) -> bool:
        return self.mode == PRIVATE

    def __repr__(self) -> str:  # shows up in logs and test failures
        return f"Profile({self.name!r}, {self.mode!r}, {len(self.document)} chars)"


def resolve(
    *,
    is_dm: bool,
    author_id: str,
    channel_id: int,
    home_channel: int,
    private_ids: set[str],
    channel_document: str,
    private_document: str,
) -> Profile | None:
    """Who to be for this message, or None if this message is not ours.

    Returning None rather than a default is deliberate. An unrecognised context
    is not a reason to improvise: a DM from a stranger and a channel the bot was
    added to by accident should both produce silence, not a guess at which
    character to perform.
    """
    if is_dm:
        if author_id in private_ids:
            return Profile("owner", PRIVATE, private_document)
        return None
    if channel_id == home_channel:
        return Profile("home", ROOM, channel_document)
    return None
