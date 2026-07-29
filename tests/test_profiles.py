"""Which version of himself Jaq is being.

Two contexts today and more later, so the question is asked in one place and
answered from a table - rather than an `if dm:` that has to be found and edited
in five places the first time a third context turns up.
"""

from __future__ import annotations

import profiles


def _resolve(**over):
    args = dict(
        is_dm=False,
        author_id="131239045761204224",
        channel_id=1531128503527932055,
        home_channel=1531128503527932055,
        private_ids={"131239045761204224"},
        channel_document="the channel character",
        private_document="the private one",
    )
    args.update(over)
    return profiles.resolve(**args)


def test_the_home_channel_gets_the_room_profile():
    got = _resolve()
    got.mode == profiles.ROOM
    assert got.mode == profiles.ROOM
    assert got.document == "the channel character"
    assert got.is_private is False


def test_the_owners_dm_gets_the_private_profile():
    got = _resolve(is_dm=True)
    assert got.mode == profiles.PRIVATE
    assert got.document == "the private one"
    assert got.is_private is True


def test_a_stranger_dm_gets_nothing():
    """Not a default, not a fallback character. Silence."""
    assert _resolve(is_dm=True, author_id="999") is None


def test_an_unknown_channel_gets_nothing():
    """A channel it was added to by accident is not an invitation to improvise
    which character to perform."""
    assert _resolve(channel_id=42) is None


def test_the_two_modes_are_not_the_same_document():
    """They are different characters, not one character at two volumes - which
    is the whole reason this is a table rather than a tone setting."""
    assert _resolve().document != _resolve(is_dm=True).document


def test_adding_a_context_needs_no_new_mode():
    """A second private line is a row, not a code change."""
    got = _resolve(is_dm=True, author_id="222", private_ids={"131239045761204224", "222"})
    assert got is not None and got.is_private
