"""Profile storage, exclusion, and prompt assembly.

Two of these guard bugs that already shipped: exclusion that a display-name
change silently defeated, and a "new material" watermark computed from
window-relative counts that froze every profile after the first scan.
"""

from __future__ import annotations

import json
import os

import pytest

import brain


@pytest.fixture(autouse=True)
def isolated_brain(tmp_path, monkeypatch):
    """Point the brain at a scratch directory, never the real one."""
    monkeypatch.setattr(brain, "BRAIN_DIR", str(tmp_path))
    monkeypatch.setattr(brain, "PEOPLE_DIR", str(tmp_path / "people"))
    monkeypatch.setattr(brain, "INDEX_PATH", str(tmp_path / "_index.json"))
    monkeypatch.setattr(brain, "_SEEN_CACHE", {})  # module-global; leaks between tests
    yield


# --- the hand-written barrier ----------------------------------------------


def test_handwritten_section_survives_regeneration():
    """The load-bearing promise of the whole profile format."""
    stance = "## Jaq's read\n\nEnemy and friend. Slam dunk on sight."
    brain.write_profile("zack", "Zack", "## Who they are\n\nFirst pass.", stance)

    _, kept = brain.read_profile("zack")
    assert kept == stance

    brain.write_profile("zack", "Zack", "## Who they are\n\nTotally rewritten.", kept)
    generated, kept_again = brain.read_profile("zack")

    assert "Totally rewritten" in generated
    assert kept_again == stance, "hand-written stance must survive byte for byte"


def test_regeneration_does_not_leak_into_generated_half():
    brain.write_profile("zack", "Zack", "observed", "## Jaq's read\n\nmine")
    generated, _ = brain.read_profile("zack")
    assert "mine" not in generated


def test_missing_profile_reads_empty():
    assert brain.read_profile("nobody") == ("", "")


def test_new_profile_gets_a_stance_placeholder():
    brain.write_profile("new", "New", "observed", "")
    _, handwritten = brain.read_profile("new")
    assert "Jaq's read" in handwritten


# --- exclusion --------------------------------------------------------------


def test_excluded_by_user_id(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["131239045761204224"])
    assert brain._is_excluded("131239045761204224", "jaqsup", "Jaq") is True


def test_excluded_by_handle(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["jaqsup"])
    assert brain._is_excluded("999", "jaqsup", "Whatever") is True


def test_excluded_by_display_name(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["real jaq"])
    assert brain._is_excluded("999", "someone", "Real Jaq") is True


def test_rename_defeats_a_name_only_exclusion(monkeypatch):
    """The privacy bug, reproduced.

    BRAIN_EXCLUDE listed the display name. The account renamed itself, the
    match stopped firing, and the next scan profiled someone who was supposed
    to be permanently off-limits. This asserts the hole is real, which is why
    the id must also be listed and why the flag is persisted per-id.
    """
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["real jaq"])
    assert brain._is_excluded("131239045761204224", "jaqsup", "Real Jaq") is True
    # Same human, same account, new display name:
    assert brain._is_excluded("131239045761204224", "jaqsup", "Jaq") is False


def test_id_based_exclusion_survives_a_rename(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["131239045761204224", "real jaq"])
    assert brain._is_excluded("131239045761204224", "jaqsup", "Jaq") is True


def test_unrelated_person_is_not_excluded(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_EXCLUDE", ["real jaq"])
    assert brain._is_excluded("555", "slaymakerlol", "Zack Kross") is False


# --- note_seen --------------------------------------------------------------


def test_note_seen_reports_new_people():
    assert brain.note_seen(42, "Newcomer") is True


def test_note_seen_is_idempotent():
    brain.note_seen(42, "Newcomer")
    assert brain.note_seen(42, "Newcomer") is False


def test_note_seen_persists_to_the_index():
    brain.note_seen(42, "Newcomer", "newcomer")
    index = json.load(open(brain.INDEX_PATH))
    assert index["people"]["42"]["display"] == "Newcomer"
    assert index["people"]["42"]["handle"] == "newcomer"


def test_note_seen_avoids_disk_on_the_common_path(monkeypatch):
    """It runs once per message of every transcript read — it cannot be a
    file read each time, which is what the docstring used to claim falsely."""
    brain.note_seen(42, "Newcomer")

    reads = []
    real = brain.load_index
    monkeypatch.setattr(brain, "load_index", lambda: (reads.append(1), real())[1])

    for _ in range(30):
        brain.note_seen(42, "Newcomer")
    assert reads == [], "cached lookups must not touch the index"


def test_note_seen_notices_a_rename():
    brain.note_seen(42, "Old Name")
    assert brain.note_seen(42, "New Name") is False  # known id, not a new person
    index = json.load(open(brain.INDEX_PATH))
    assert index["people"]["42"]["display"] == "New Name"


# --- prompt assembly --------------------------------------------------------


def _seed(handle, uid, display, stance="## Jaq's read\n\nstance"):
    brain.write_profile(handle, display, f"## Who they are\n\n{display} notes.", stance)
    index = brain.load_index()
    index.setdefault("people", {})[str(uid)] = {"handle": handle, "display": display}
    brain.save_index(index)


def test_core_profiles_load_with_nobody_present(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", ["zack"])
    _seed("zack", 1, "Zack")
    out = brain.load_for(set())
    assert "Zack notes" in out


def test_situational_profile_loads_when_present(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", [])
    _seed("dillon", 2, "dillon")
    assert "dillon notes" in brain.load_for({2})


def test_absent_person_is_not_loaded(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", [])
    _seed("dillon", 2, "dillon")
    assert "dillon notes" not in brain.load_for({999})


def test_never_recite_rule_is_always_attached(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", ["zack"])
    _seed("zack", 1, "Zack")
    out = brain.load_for(set())
    assert "Never recite them" in out


def test_empty_brain_injects_nothing(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", [])
    assert brain.load_for(set()) == ""


def test_situational_profiles_are_capped(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", [])
    monkeypatch.setattr(brain, "BRAIN_MAX_PROFILES", 2)
    for i in range(5):
        _seed(f"p{i}", i, f"Person{i}")
    out = brain.load_for(set(range(5)))
    assert sum(f"Person{i} notes" in out for i in range(5)) == 2


def test_hand_written_stance_reaches_the_prompt(monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_CORE", ["zack"])
    _seed("zack", 1, "Zack", "## Jaq's read\n\nSlam dunk on sight.")
    assert "Slam dunk on sight" in brain.load_for(set())


def test_profile_count_matches_files():
    assert brain.profile_count() == 0
    _seed("a", 1, "A")
    _seed("b", 2, "B")
    assert brain.profile_count() == 2
