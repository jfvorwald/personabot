"""Jack's word list, injected from the environment.

Kept in .env rather than persona.md because it changes far more often than the
character does - adding a word people started saying this week shouldn't mean
editing the personality.
"""

from __future__ import annotations

import persona


def test_empty_vocab_injects_nothing(monkeypatch):
    monkeypatch.setattr(persona, "VOCAB", [])
    assert persona.load_vocab() == ""


def test_words_are_listed(monkeypatch):
    monkeypatch.setattr(persona, "VOCAB", ["goyslop", "crashout"])
    block = persona.load_vocab()
    assert "- goyslop" in block
    assert "- crashout" in block


def test_multi_word_phrases_survive(monkeypatch):
    """Entries are comma-separated, so spaces inside one are fine."""
    monkeypatch.setattr(persona, "VOCAB", ["what the helliante"])
    assert "- what the helliante" in persona.load_vocab()


def test_block_forbids_checklist_use(monkeypatch):
    """A list of words handed to a model with no guidance gets crammed in."""
    monkeypatch.setattr(persona, "VOCAB", ["goyslop"])
    block = persona.load_vocab()
    assert "never work through them as a list" in block
    assert "Most\nmessages will contain none of these" in block


def test_parsing_strips_whitespace(monkeypatch):
    import config
    import importlib
    import os

    monkeypatch.setenv("VOCAB", " one , two ,, three ")
    importlib.reload(config)
    assert config.VOCAB == ["one", "two", "three"]
    monkeypatch.delenv("VOCAB")
    importlib.reload(config)


def test_vocab_is_a_separate_block_from_the_persona(bot_module, monkeypatch):
    """It must not be spliced into persona.md - the whole point is that the
    word list is editable without touching the character."""
    import persona as persona_mod

    monkeypatch.setattr(persona_mod, "VOCAB", ["testword"])
    assert "testword" not in persona_mod.load_persona()
    assert "testword" in persona_mod.load_vocab()
