"""The three loaders that read the character off disk.

These exist because the refactor broke one of them and the suite said nothing:
load_post_times lost its TIMEZONE import, and since main() is the only caller
and no test exercised main(), 141 tests passed against a bot that could not
start. Import errors are exactly what a unit test is cheapest at catching.
"""

from __future__ import annotations

import datetime

import pytest

import persona


# --- post times -------------------------------------------------------------


def test_post_times_parse(monkeypatch):
    monkeypatch.setenv("POST_TIMES", "09:00,13:15,19:30")
    times = persona.load_post_times()
    assert [(t.hour, t.minute) for t in times] == [(9, 0), (13, 15), (19, 30)]


def test_post_times_are_timezone_aware(monkeypatch):
    """The bug: TIMEZONE was referenced but never imported, so this raised
    NameError the moment the bot tried to start."""
    monkeypatch.setenv("POST_TIMES", "09:00")
    assert persona.load_post_times()[0].tzinfo is not None


def test_post_times_tolerate_whitespace(monkeypatch):
    monkeypatch.setenv("POST_TIMES", " 09:00 , 13:15 ")
    assert len(persona.load_post_times()) == 2


def test_empty_post_times_is_an_error(monkeypatch):
    monkeypatch.setenv("POST_TIMES", "   ")
    with pytest.raises(ValueError):
        persona.load_post_times()


def test_post_times_default_when_unset(monkeypatch):
    monkeypatch.delenv("POST_TIMES", raising=False)
    assert len(persona.load_post_times()) == 1


# --- persona and psychology -------------------------------------------------


def test_persona_loads():
    text = persona.load_persona()
    assert len(text) > 500, "persona.md should be substantial"
    assert "Jaq" in text


def test_psychology_loads():
    assert "conditionally relevant" in persona.load_psychology()


def test_missing_psychology_is_not_fatal(monkeypatch):
    monkeypatch.setattr(persona, "PSYCHOLOGY_FILE", "no-such-file.md")
    assert persona.load_psychology() == ""


# --- every module imports cleanly ------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["config", "prompts", "decide", "react", "persona", "brain", "guard",
     "changelog", "imagegen", "bot"],
)
def test_module_imports(name):
    """A missing import in any module is a bot that will not start.

    Cheap insurance: the refactor that split these apart is exactly when a name
    goes missing from the module that used to own it.
    """
    __import__(name)
