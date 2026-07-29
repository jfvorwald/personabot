"""Measuring what the model cannot see about itself.

Every reply is a fresh single-turn call with no memory of the last forty, so a
verbal tic is invisible from the inside and obvious from the outside. These are
the measurements that make it visible, and they have to be trustworthy: a false
finding produces a proposal to fix something that was never wrong.
"""

from __future__ import annotations

import json

import pytest

import improve


# --- tics -------------------------------------------------------------------


def test_a_word_in_most_messages_is_found():
    """The real one: "still" opened 37% of an evening's messages."""
    messages = ["still going", "he's still wrong", "still no", "fine"]
    found = dict(improve.overused(messages, min_share=0.5))
    assert "still" in found
    assert found["still"] == pytest.approx(0.75)


def test_ordinary_words_are_not_tics():
    """A stopword in every message says nothing about how he talks."""
    messages = ["the raid was bad"] * 5
    assert not any(w in ("the", "was") for w, _ in improve.overused(messages))


def test_a_word_used_repeatedly_in_one_message_is_not_a_tic():
    """Share of messages, not share of words: four times in one message is a
    sentence, once in half of them is a habit."""
    messages = ["clanker clanker clanker clanker", "fine", "sure", "no"]
    assert improve.overused(messages, min_share=0.5) == []


def test_short_words_are_ignored():
    assert improve.overused(["gg gg", "gg", "gg"], min_share=0.5) == []


def test_nothing_from_nothing():
    assert improve.overused([]) == []
    assert improve.opening_habits([]) == []
    assert improve.repeated_phrases([]) == []


# --- openers ----------------------------------------------------------------


def test_a_repeated_opener_is_found():
    """The most conspicuous tell there is - it is the first thing anyone reads."""
    messages = ["still no", "still wrong", "still here", "fine then"]
    found = dict(improve.opening_habits(messages, min_share=0.5))
    assert found["still"] == pytest.approx(0.75)


def test_varied_openers_produce_nothing():
    messages = ["alpha one", "beta two", "gamma three", "delta four"]
    assert improve.opening_habits(messages) == []


# --- phrases ----------------------------------------------------------------


def test_a_repeated_phrase_is_found():
    """Catches what single words miss: a running joke restated in identical
    words, which reads as a stuck record rather than a callback."""
    messages = [
        "down 58 points to a chatbot",
        "still down 58 points mate",
        "he is down 58 points",
        "unrelated",
    ]
    found = dict(improve.repeated_phrases(messages, size=3, min_count=3))
    assert "down 58 points" in found
    assert found["down 58 points"] == 3


def test_a_phrase_used_twice_is_not_a_pattern():
    messages = ["down 58 points", "down 58 points", "something else"]
    assert improve.repeated_phrases(messages, size=3, min_count=3) == []


# --- length -----------------------------------------------------------------


def test_length_profile_reports_drift():
    profile = improve.length_profile(["a" * 100, "a" * 200, "a" * 400])
    assert profile["count"] == 3
    assert profile["median"] == 200
    assert profile["longest"] == 400
    assert profile["over_300"] == 1


def test_length_profile_of_nothing_is_zeroed():
    assert improve.length_profile([])["count"] == 0


# --- the observation log ----------------------------------------------------


def test_a_record_round_trips(tmp_path):
    path = str(tmp_path / "obs" / "log.jsonl")
    improve.record({"at": "2026-07-28T21:00:00", "kind": "reply", "chars": 90}, path)
    got = improve.read_records(path)
    assert len(got) == 1 and got[0]["chars"] == 90


def test_records_are_filtered_by_time(tmp_path):
    path = str(tmp_path / "log.jsonl")
    improve.record({"at": "2026-07-27T10:00:00", "kind": "reply"}, path)
    improve.record({"at": "2026-07-28T10:00:00", "kind": "reply"}, path)
    assert len(improve.read_records(path, since="2026-07-28T00:00:00")) == 1


def test_a_torn_line_costs_one_record_not_the_file(tmp_path):
    """An appending process will occasionally leave a partial last line."""
    path = tmp_path / "log.jsonl"
    path.write_text('{"at":"2026-07-28T10:00:00","kind":"reply"}\n{"at":"2026-')
    assert len(improve.read_records(str(path))) == 1


def test_recording_never_raises(tmp_path):
    """Losing an observation must never cost a message in the channel."""
    improve.record({"bad": object()}, str(tmp_path / "log.jsonl"))  # unserialisable
    improve.record({"ok": 1}, "/nowhere/that/exists/log.jsonl")  # unwritable


def test_a_missing_log_reads_as_empty():
    assert improve.read_records("/no/such/log.jsonl") == []


def test_engagement_counts_what_happened():
    records = [
        {"kind": "reply", "path": "normal"},
        {"kind": "reply", "path": "commission"},
        {"kind": "pass"},
    ]
    stats = improve.engagement(records)
    assert stats["replied"] == 2
    assert stats["passed"] == 1
    assert stats["paths"]["commission"] == 1


# --- the prompt keeps its guardrails ----------------------------------------


def test_proposals_must_cite_a_measurement():
    import prompts

    assert "name the measurement" in prompts.IMPROVE_PROMPT


def test_it_will_not_propose_talking_more():
    """The design goal is a person in a room, not a service."""
    import prompts

    assert "makes him talk more" in prompts.IMPROVE_PROMPT


def test_it_prefers_removing_to_adding():
    """Every regression in this project came from more instruction, not less."""
    import prompts

    assert "Prefer removing something over adding something" in prompts.IMPROVE_PROMPT


def test_it_does_not_judge_the_jokes():
    import prompts

    assert "not yours to" in prompts.IMPROVE_PROMPT


# --- the backlog accumulates ------------------------------------------------
#
# A snapshot rewritten every run means anything not acted on immediately is
# gone by tomorrow, which turns "I'll get to that later" into "that never
# happened". These are the properties that stop that.


PROPOSAL = """## Cut the "still" tic
WHERE: persona.md
WHY: "still" appears in 43% of his messages
CHANGE: add a rule against opening with it

## Retire the 58 points construction
WHERE: persona.md
WHY: used verbatim three times
CHANGE: remove it
"""


def test_proposals_are_parsed():
    items = improve.parse_proposals(PROPOSAL)
    assert len(items) == 2
    assert items[0]["where"] == "persona.md"
    assert "43%" in items[0]["why"]


def test_a_proposal_missing_fields_still_parses():
    """A missing field costs that field, not the proposal."""
    items = improve.parse_proposals("## Just a title\n")
    assert len(items) == 1 and items[0]["title"] == "Just a title"


def test_a_backlog_round_trips():
    items = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    reparsed = improve.parse_backlog(improve.render_backlog(items))
    assert len(reparsed) == 2
    assert all(i["status"] == "open" for i in reparsed)
    assert reparsed[0]["first"] == "2026-07-28"


def test_a_repeat_bumps_a_count_instead_of_duplicating():
    """"Suggested five times and still not done" is the useful signal."""
    day1 = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    day2 = improve.merge_backlog(day1, improve.parse_proposals(PROPOSAL), "2026-07-29")
    assert len(day2) == 2
    assert all(i["seen"] == 2 for i in day2)
    assert all(i["last"] == "2026-07-29" for i in day2)
    assert all(i["first"] == "2026-07-28" for i in day2)


def test_a_reworded_repeat_is_still_the_same_item():
    day1 = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    reworded = improve.parse_proposals('## Cut the tic of saying "still"\n')
    day2 = improve.merge_backlog(day1, reworded, "2026-07-29")
    assert len(day2) == 2, "a rewording must not become a second entry"


def test_a_decision_is_never_reopened():
    """Silently reversing Jack's call is worse than losing a suggestion."""
    day1 = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    day1[0]["status"] = "dropped"
    day2 = improve.merge_backlog(day1, improve.parse_proposals(PROPOSAL), "2026-07-29")
    dropped = [i for i in day2 if i["status"] == "dropped"]
    assert len(dropped) == 1
    assert dropped[0]["seen"] == 2, "it still counts that it came up again"


def test_human_notes_survive_a_merge():
    day1 = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    rendered = improve.render_backlog(day1).replace(
        "- last: 2026-07-28",
        "- last: 2026-07-28\n\nnot yet, see how it reads first",
        1,
    )
    reparsed = improve.parse_backlog(rendered)
    day2 = improve.merge_backlog(reparsed, improve.parse_proposals(PROPOSAL), "2026-07-29")
    assert any("not yet, see how it reads first" in i.get("notes", "") for i in day2)


def test_a_human_edit_is_not_overwritten():
    day1 = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    day1[0]["change"] = "do it my way instead"
    day2 = improve.merge_backlog(day1, improve.parse_proposals(PROPOSAL), "2026-07-29")
    assert day2[0]["change"] == "do it my way instead"


def test_open_items_sort_before_decided_ones():
    items = improve.merge_backlog([], improve.parse_proposals(PROPOSAL), "2026-07-28")
    items[0]["status"] = "done"
    ordered = improve.merge_backlog(items, [], "2026-07-29")
    assert ordered[0]["status"] == "open"


def test_an_empty_backlog_file_is_fine():
    assert improve.parse_backlog("") == []
    assert improve.parse_backlog("# Improvement backlog\n\nnothing yet\n") == []
