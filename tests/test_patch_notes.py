"""Patch notes: reading the commit log and deciding when to recite it.

The repo is the source of truth, so this is read-only and failure-tolerant by
design - a bot that crashes because git moved is worse than one with no news.
"""

from __future__ import annotations

import subprocess

import pytest

import changelog
import decide
from conftest import FakeAuthor, FakeMessage
from test_identity import FakeChannel


# --- detecting the ask ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "any updates?",
        "what's new",
        "patch notes",
        "release notes?",
        "sitrep",
        "got any updates",
        "what changed?",
        "anything new lately?",
        "what did they change?",
        "gimme the changelog",
    ],
)
def test_update_requests_are_recognised(text):
    assert decide.is_update_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "I updated my drivers last night",
        "the update broke my game",
        "new raid tonight",
        "lol",
        "",
        "that patch was rough on warriors",
    ],
)
def test_ordinary_talk_is_not_a_request(text):
    """Talking about an update is not asking for one."""
    assert decide.is_update_request(text) is False


# --- reading the log --------------------------------------------------------


def _repo(tmp_path, subjects):
    run = lambda *a: subprocess.run(a, cwd=tmp_path, capture_output=True, check=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    for s in subjects:
        (tmp_path / "f.txt").write_text(s)
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", s)
    return str(tmp_path)


def test_reads_commit_subjects(tmp_path):
    repo = _repo(tmp_path, ["first thing", "second thing"])
    assert changelog.recent_commits(24, cwd=repo) == ["second thing", "first thing"]


def test_housekeeping_is_filtered(tmp_path):
    repo = _repo(tmp_path, ["real change", "fix typo in readme", "bump version to 2"])
    assert changelog.recent_commits(24, cwd=repo) == ["real change"]


def test_window_excludes_older_commits(tmp_path):
    """A commit from years ago is not news. Ordered oldest-first, as real
    history is - a backdated commit sitting on top of a newer one confuses
    git's own date-ordered traversal."""
    import os

    run = lambda *a, **k: subprocess.run(a, cwd=str(tmp_path), check=True,
                                         capture_output=True, **k)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")

    ancient = dict(os.environ, GIT_COMMITTER_DATE="2020-01-01T00:00:00",
                   GIT_AUTHOR_DATE="2020-01-01T00:00:00")
    (tmp_path / "old.txt").write_text("x")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "ancient history", env=ancient)

    (tmp_path / "new.txt").write_text("y")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "recent thing")

    subjects = changelog.recent_commits(24, cwd=str(tmp_path))
    assert subjects == ["recent thing"]


def test_limit_is_respected(tmp_path):
    repo = _repo(tmp_path, [f"change {i}" for i in range(10)])
    assert len(changelog.recent_commits(24, cwd=repo, limit=3)) == 3


def test_not_a_repository_returns_nothing(tmp_path):
    """Never raise into a live bot over a joke feature."""
    assert changelog.recent_commits(24, cwd=str(tmp_path)) == []


def test_missing_git_returns_nothing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(changelog.subprocess, "run", boom)
    assert changelog.recent_commits(24) == []


def test_timeout_returns_nothing(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("git", 5)

    monkeypatch.setattr(changelog.subprocess, "run", slow)
    assert changelog.recent_commits(24) == []


# --- rendering --------------------------------------------------------------


def test_summarise_bullets_each_change():
    assert changelog.summarise(["a", "b"]) == "- a\n- b"


def test_summarise_is_empty_when_nothing_shipped():
    assert changelog.summarise([]) == ""


# --- routing ----------------------------------------------------------------


def _asking(bot, text):
    m = FakeMessage(FakeAuthor("dillon", "wurmz"), text)
    m.channel = FakeChannel()
    return bot._wants_patch_notes(m)


def test_addressed_request_wants_notes(persona_bot):
    assert _asking(persona_bot, "agentic jaq any updates?") is True


def test_request_not_addressed_to_us_is_ignored(persona_bot):
    """Someone asking the room about updates isn't asking us."""
    assert _asking(persona_bot, "any updates on the raid?") is False


def test_addressed_but_not_asking_is_not_notes(persona_bot):
    assert _asking(persona_bot, "agentix you around?") is False


def test_no_changes_falls_back_to_the_brush_off(persona_bot, monkeypatch):
    monkeypatch.setattr(changelog, "recent_commits", lambda *a, **k: [])
    instruction = persona_bot._patch_notes_instruction()
    assert "Nothing has" in instruction


def test_changes_are_handed_to_the_model(persona_bot, monkeypatch):
    monkeypatch.setattr(changelog, "recent_commits", lambda *a, **k: ["did a thing"])
    instruction = persona_bot._patch_notes_instruction()
    assert "did a thing" in instruction
    assert "patient here, not the surgeon" in instruction


def test_notes_prompt_forbids_naming_files(persona_bot, monkeypatch):
    """Patch notes are the one fourth-wall moment; they still must not turn
    into a repository tour."""
    monkeypatch.setattr(changelog, "recent_commits", lambda *a, **k: ["x"])
    assert "Do not name files" in persona_bot._patch_notes_instruction()
