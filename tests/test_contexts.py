"""Worlds a picture can be set in, loaded from markdown.

Two gates, and the second one matters as much as the first: a context that
fires every time it could gives the channel a house style nobody chose, and
the pictures stop being surprising. The tests below defend both, and defend
the failure modes of hand-written files - because these are written by someone
describing a world, not filling in a form.
"""

from __future__ import annotations

import pytest

import contexts


WARCRAFT = """\
---
name: warcraft
when: wow, azeroth, raid, wipe
chance: 0.6
---

Heavy plate armour and torchlit stone keeps.
"""


@pytest.fixture
def context_dir(tmp_path, monkeypatch):
    """Point the loader at a directory we control."""
    monkeypatch.setattr(contexts, "at_root", lambda *_: str(tmp_path))
    return tmp_path


def _write(directory, name, text):
    (directory / name).write_text(text, encoding="utf-8")


# --- reading the files ------------------------------------------------------


def test_a_context_is_loaded(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    loaded = contexts.load_all()
    assert len(loaded) == 1
    assert loaded[0].name == "warcraft"
    assert loaded[0].chance == 0.6
    assert "torchlit stone keeps" in loaded[0].body
    assert "wipe" in loaded[0].triggers


def test_the_template_never_fires(context_dir):
    """A fresh clone must not render everything like the example."""
    _write(context_dir, "example.md", WARCRAFT)
    _write(context_dir, "README.md", "# not a context")
    assert contexts.load_all() == []


def test_the_name_falls_back_to_the_filename(context_dir):
    _write(context_dir, "fishing.md", "---\nwhen: fish\n---\n\nA cold lake.")
    assert contexts.load_all()[0].name == "fishing"


def test_a_missing_chance_means_always(context_dir):
    _write(context_dir, "a.md", "---\nwhen: fish\n---\n\nA cold lake.")
    assert contexts.load_all()[0].chance == 1.0


def test_chance_is_clamped(context_dir):
    _write(context_dir, "a.md", "---\nwhen: fish\nchance: 9\n---\n\nA lake.")
    _write(context_dir, "b.md", "---\nwhen: golf\nchance: -3\n---\n\nA course.")
    assert sorted(c.chance for c in contexts.load_all()) == [0.0, 1.0]


def test_a_missing_directory_is_not_fatal(monkeypatch):
    monkeypatch.setattr(contexts, "at_root", lambda *_: "/no/such/place")
    assert contexts.load_all() == []


# --- hand-written files break in predictable ways ---------------------------


@pytest.mark.parametrize(
    "text",
    [
        "no metadata block at all",                      # no marker
        "---\nwhen: fish\n\nnever closed",               # unterminated
        "---\nwhen: fish\n---\n\n",                      # no body
        "---\nname: x\nchance: 1\n---\n\nBody.",         # no triggers
        "---\nwhen: \n---\n\nBody.",                     # empty triggers
    ],
)
def test_a_broken_file_is_skipped_not_fatal(context_dir, text):
    """A malformed context costs a picture its setting, never the bot."""
    _write(context_dir, "broken.md", text)
    assert contexts.load_all() == []


def test_a_broken_file_does_not_take_the_good_ones_with_it(context_dir):
    _write(context_dir, "broken.md", "no metadata")
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert [c.name for c in contexts.load_all()] == ["warcraft"]


def test_an_unreadable_chance_falls_back(context_dir):
    _write(context_dir, "a.md", "---\nwhen: fish\nchance: soon\n---\n\nA lake.")
    assert contexts.load_all()[0].chance == 1.0


def test_non_markdown_is_ignored(context_dir):
    _write(context_dir, "notes.txt", WARCRAFT)
    assert contexts.load_all() == []


# --- matching ---------------------------------------------------------------


def test_a_trigger_word_matches(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert contexts.load_all()[0].matches("that raid was a disaster") is True


def test_matching_ignores_case(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert contexts.load_all()[0].matches("AZEROTH again") is True


def test_a_substring_is_not_a_match(context_dir):
    """"raid" must not fire on "afraid" - a context that matches inside
    ordinary words fires constantly, which is how every picture ends up in
    the same register."""
    _write(context_dir, "warcraft.md", WARCRAFT)
    ctx = contexts.load_all()[0]
    assert ctx.matches("I'm afraid that's wrong") is False
    assert ctx.matches("wowzers") is False


def test_an_unrelated_conversation_matches_nothing(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert contexts.load_all()[0].matches("anyone watching the football") is False


# --- picking ----------------------------------------------------------------


def test_a_match_that_wins_its_roll_is_returned(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    chosen = contexts.pick("that raid was a disaster", roll=0.1)
    assert chosen is not None and chosen.name == "warcraft"


def test_a_match_that_loses_its_roll_is_not(context_dir):
    """The second gate. Firing every time it could is how a channel acquires
    a house style nobody chose."""
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert contexts.pick("that raid was a disaster", roll=0.9) is None


def test_nothing_matching_returns_nothing(context_dir):
    _write(context_dir, "warcraft.md", WARCRAFT)
    assert contexts.pick("anyone watching the football", roll=0.0) is None


def test_no_contexts_at_all_is_fine(context_dir):
    assert contexts.pick("that raid was a disaster", roll=0.0) is None


def test_one_of_several_matches_is_chosen(context_dir, monkeypatch):
    """Drawn at random rather than first alphabetically, so a file named
    early does not quietly own every overlap."""
    _write(context_dir, "a_warcraft.md", WARCRAFT)
    _write(context_dir, "z_other.md", "---\nwhen: raid\nchance: 1\n---\n\nElsewhere.")
    monkeypatch.setattr(contexts.random, "choice", lambda seq: seq[-1])
    chosen = contexts.pick("that raid was a disaster", roll=0.0)
    assert chosen.body == "Elsewhere."


# --- the wiring -------------------------------------------------------------


def test_the_bot_appends_a_matching_context(persona_bot, bot_module, monkeypatch):
    ctx = contexts.Context("warcraft", ["raid"], 1.0, "Torchlit stone keeps.")
    monkeypatch.setattr(bot_module.contexts, "pick", lambda text: ctx)
    out = persona_bot._image_context("[Mon] zack: that raid was a disaster")
    assert "Torchlit stone keeps." in out
    assert "set it in this world" in out


def test_no_match_adds_nothing(persona_bot, bot_module, monkeypatch):
    monkeypatch.setattr(bot_module.contexts, "pick", lambda text: None)
    assert persona_bot._image_context("anything at all") == ""


def test_a_raising_loader_does_not_break_the_reply(persona_bot, bot_module, monkeypatch):
    def explode(text):
        raise OSError("disk gone")

    monkeypatch.setattr(bot_module.contexts, "pick", explode)
    assert persona_bot._image_context("that raid was a disaster") == ""


def test_the_shipped_template_is_parseable():
    """It is documentation, but it is also the thing people copy - if it does
    not parse, every context derived from it starts broken."""
    import os

    from paths import at_root

    path = os.path.join(at_root("contexts"), "example.md")
    with open(path, encoding="utf-8") as f:
        parsed = contexts._parse(f.read(), "copied.md")
    assert parsed is not None
    assert parsed.triggers and parsed.body
