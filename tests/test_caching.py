"""Prompt caching: splitting the system prompt without changing it.

Caching is a prefix match, so the only thing that makes it work is that the
first half is byte-identical on every reply. Two things can go wrong and
neither one raises. Splitting a string at a join and dropping the join
rewrites the prompt while every test still passes. And a later change that
puts something varying into the stable half stops the prefix matching, so
every request pays the 1.25x write premium instead of the 0.1x read discount,
silently, for as long as nobody checks.

These tests pin the split. The log line pins the rest.
"""

from __future__ import annotations

import bot


STABLE = "persona text"
VOLATILE = "\n\n---\n\nframing text\n\n---\n\nconfidentiality"


# --- the prompt itself must not change ---------------------------------------


def test_the_blocks_concatenate_to_the_original_prompt(monkeypatch):
    """The whole point: same bytes, differently packaged."""
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    blocks = bot._system_blocks(STABLE, VOLATILE)
    assert "".join(b["text"] for b in blocks) == STABLE + VOLATILE


def test_turning_caching_off_returns_exactly_the_old_string(monkeypatch):
    """The flag has to be a real escape hatch, not a different prompt."""
    monkeypatch.setattr(bot, "CACHE_PROMPT", False)
    assert bot._system_blocks(STABLE, VOLATILE) == STABLE + VOLATILE


def test_the_separator_lives_on_the_volatile_side(monkeypatch):
    """If the stable half ended with the join, the two halves would still
    concatenate correctly but the cached bytes would end in a dangling rule."""
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    blocks = bot._system_blocks(STABLE, VOLATILE)
    assert not blocks[0]["text"].endswith("-")
    assert blocks[1]["text"].startswith("\n\n---\n\n")


# --- the breakpoint goes in exactly one place --------------------------------


def test_the_breakpoint_is_on_the_stable_half(monkeypatch):
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    blocks = bot._system_blocks(STABLE, VOLATILE)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1], "caching the varying half is the surcharge"


def test_only_one_breakpoint_is_ever_placed(monkeypatch):
    """Four are allowed per request. Spending more than one here would mean
    caching something that changes."""
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    blocks = bot._system_blocks(STABLE, VOLATILE)
    assert sum("cache_control" in b for b in blocks) == 1


def test_an_empty_volatile_half_still_caches(monkeypatch):
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    blocks = bot._system_blocks(STABLE, "")
    assert len(blocks) == 1 and "cache_control" in blocks[0]


def test_an_empty_persona_is_not_cached(monkeypatch):
    """Below the model's minimum nothing caches anyway, and a breakpoint on
    nothing is just a malformed request."""
    monkeypatch.setattr(bot, "CACHE_PROMPT", True)
    assert bot._system_blocks("", VOLATILE) == VOLATILE


# --- ttl ---------------------------------------------------------------------


def test_the_default_ttl_is_left_unstated(monkeypatch):
    """Five minutes is the API default; sending it explicitly is not accepted
    everywhere."""
    monkeypatch.setattr(bot, "CACHE_TTL", "5m")
    assert bot._cache_control() == {"type": "ephemeral"}


def test_a_longer_ttl_is_stated(monkeypatch):
    monkeypatch.setattr(bot, "CACHE_TTL", "1h")
    assert bot._cache_control() == {"type": "ephemeral", "ttl": "1h"}


# --- the standing check ------------------------------------------------------


def test_cache_activity_is_logged(caplog):
    """The costly failure is silent, so the numbers get logged every reply
    rather than checked once when this was written."""
    usage = type("U", (), {
        "cache_read_input_tokens": 8222,
        "cache_creation_input_tokens": 0,
        "input_tokens": 700,
    })()
    with caplog.at_level("INFO"):
        bot._log_cache(usage)
    assert "8222 read" in caplog.text


def test_nothing_is_logged_when_the_model_reports_no_cache(caplog):
    usage = type("U", (), {
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "input_tokens": 700,
    })()
    with caplog.at_level("INFO"):
        bot._log_cache(usage)
    assert "Cache:" not in caplog.text


def test_missing_usage_fields_do_not_raise():
    """Older responses and third-party gateways may not carry these."""
    bot._log_cache(type("U", (), {})())
