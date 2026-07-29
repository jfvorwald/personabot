"""The day's spend has to survive a restart.

_roll_day ran unconditionally on connect, so every deploy zeroed the counters
and re-drew the budget. That was harmless when deploys were rare and became a
hole the moment restarting on every change became the workflow: LIVE_DAILY_MAX
only ever bounded a single process.
"""

from __future__ import annotations

import datetime
import json

import pytest


@pytest.fixture
def stateful_bot(persona_bot, bot_module, tmp_path, monkeypatch):
    monkeypatch.setattr(bot_module, "STATE_FILE", str(tmp_path / "state.json"))
    persona_bot._state_path = lambda: str(tmp_path / "state.json")
    persona_bot._schedule_pokes = lambda today: None
    # The shared fixture stubs _save_day out so unrelated tests don't touch
    # disk; these tests are about persistence, so put the real one back.
    persona_bot._save_day = bot_module.PersonaBot._save_day.__get__(persona_bot)
    return persona_bot


TODAY = datetime.date(2026, 7, 28)
YESTERDAY = datetime.date(2026, 7, 27)


def test_nothing_to_restore_on_a_fresh_install(stateful_bot):
    assert stateful_bot._restore_day(TODAY) is False


def test_spend_survives_a_restart(stateful_bot):
    stateful_bot._reply_day = TODAY
    stateful_bot._replies_today = 12
    stateful_bot._reactions_today = 5
    stateful_bot._daily_budget = 30
    stateful_bot._save_day()

    # Simulate the process dying and coming back.
    stateful_bot._replies_today = 0
    stateful_bot._reactions_today = 0
    stateful_bot._daily_budget = None

    assert stateful_bot._restore_day(TODAY) is True
    assert stateful_bot._replies_today == 12
    assert stateful_bot._reactions_today == 5
    assert stateful_bot._daily_budget == 30


def test_budget_is_not_redrawn_on_restart(stateful_bot):
    """The whole point: ten deploys in a day must not buy ten budgets."""
    stateful_bot._reply_day = TODAY
    stateful_bot._replies_today = 29
    stateful_bot._daily_budget = 30
    stateful_bot._save_day()

    for _ in range(10):
        stateful_bot._replies_today = 0
        stateful_bot._daily_budget = None
        assert stateful_bot._restore_day(TODAY) is True

    assert stateful_bot._replies_today == 29
    assert stateful_bot._daily_budget == 30
    assert stateful_bot._out_of_budget() is False  # one left, then done


def test_a_new_day_does_not_restore(stateful_bot):
    stateful_bot._reply_day = YESTERDAY
    stateful_bot._replies_today = 30
    stateful_bot._daily_budget = 30
    stateful_bot._save_day()

    assert stateful_bot._restore_day(TODAY) is False, "a new day gets a fresh budget"


def test_exhausted_budget_stays_exhausted_across_a_restart(stateful_bot):
    stateful_bot._reply_day = TODAY
    stateful_bot._replies_today = 30
    stateful_bot._daily_budget = 30
    stateful_bot._brushed_off_today = True
    stateful_bot._save_day()

    stateful_bot._replies_today = 0
    stateful_bot._brushed_off_today = False
    stateful_bot._restore_day(TODAY)

    assert stateful_bot._out_of_budget() is True
    assert stateful_bot._brushed_off_today is True, "don't re-send the sign-off"


def test_unlimited_budget_round_trips(stateful_bot):
    stateful_bot._reply_day = TODAY
    stateful_bot._daily_budget = None
    stateful_bot._replies_today = 400
    stateful_bot._save_day()

    stateful_bot._daily_budget = 7
    stateful_bot._restore_day(TODAY)
    assert stateful_bot._daily_budget is None
    assert stateful_bot._out_of_budget() is False


def test_corrupt_state_is_survivable(stateful_bot, tmp_path):
    (tmp_path / "state.json").write_text("{ this is not json")
    assert stateful_bot._restore_day(TODAY) is False


def test_state_file_is_readable(stateful_bot, tmp_path):
    stateful_bot._reply_day = TODAY
    stateful_bot._replies_today = 3
    stateful_bot._reactions_today = 1
    stateful_bot._daily_budget = 20
    stateful_bot._save_day()

    written = json.loads((tmp_path / "state.json").read_text())
    assert written["day"] == "2026-07-28"
    assert written["replies"] == 3
    assert written["reactions"] == 1


# --- the ceiling on a soft budget -------------------------------------------
#
# The daily budget is deliberately soft: an @mention from a human and anything
# an ally says are answered past it, because rationing must never read as
# blanking a friend. The cost is that a busy day has no upper bound - one ran
# 51 replies against a budget of 32. This is the bound.


def _capped(bot, replies, budget=32, multiplier=3.0, bot_module=None, monkeypatch=None):
    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", multiplier)
    bot._daily_budget = budget
    bot._replies_today = replies
    return bot._hard_capped()


def test_under_the_ceiling_is_not_capped(persona_bot, bot_module, monkeypatch):
    assert _capped(persona_bot, 95, bot_module=bot_module, monkeypatch=monkeypatch) is False


def test_the_ceiling_is_three_times_the_budget(persona_bot, bot_module, monkeypatch):
    assert _capped(persona_bot, 96, bot_module=bot_module, monkeypatch=monkeypatch) is True


def test_well_past_the_ceiling_stays_capped(persona_bot, bot_module, monkeypatch):
    assert _capped(persona_bot, 500, bot_module=bot_module, monkeypatch=monkeypatch) is True


def test_the_soft_budget_still_bites_first(persona_bot, bot_module, monkeypatch):
    """Ordinary traffic stops at the budget; only exempt traffic gets as far
    as the ceiling, which is the whole point of having two numbers."""
    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", 3.0)
    persona_bot._daily_budget = 32
    persona_bot._replies_today = 40
    assert persona_bot._out_of_budget() is True
    assert persona_bot._hard_capped() is False


def test_an_unlimited_budget_has_no_ceiling(persona_bot, bot_module, monkeypatch):
    """LIVE_DAILY_MAX=0 means no limit, and three times no limit is no limit."""
    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", 3.0)
    persona_bot._daily_budget = None
    persona_bot._replies_today = 10_000
    assert persona_bot._hard_capped() is False


def test_a_zero_multiplier_disables_the_ceiling(persona_bot, bot_module, monkeypatch):
    assert _capped(
        persona_bot, 10_000, multiplier=0, bot_module=bot_module, monkeypatch=monkeypatch
    ) is False


def test_the_multiplier_is_configurable(persona_bot, bot_module, monkeypatch):
    assert _capped(
        persona_bot, 64, multiplier=2.0, bot_module=bot_module, monkeypatch=monkeypatch
    ) is True
    assert _capped(
        persona_bot, 63, multiplier=2.0, bot_module=bot_module, monkeypatch=monkeypatch
    ) is False


# --- Jack is not queueing behind his own quota ------------------------------


def test_an_ally_crosses_the_hard_cap(persona_bot, bot_module, monkeypatch, jack):
    """A ceiling meant to stop a room running up a bill should not be the
    reason the person who built it gets ignored."""
    from conftest import FakeMessage

    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", 3.0)
    persona_bot._daily_budget = 32
    persona_bot._replies_today = 500  # far past 3x
    assert persona_bot._hard_capped(FakeMessage(jack, "still here")) is False


def test_a_stranger_does_not_cross_it(persona_bot, bot_module, monkeypatch, stranger):
    from conftest import FakeMessage

    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", 3.0)
    persona_bot._daily_budget = 32
    persona_bot._replies_today = 96
    assert persona_bot._hard_capped(FakeMessage(stranger, "hi")) is True


def test_no_message_still_answers_the_question(persona_bot, bot_module, monkeypatch):
    """Callers that have no message - the idle opener, pokes - still need a
    truthful answer about the ceiling."""
    monkeypatch.setattr(bot_module, "LIVE_HARD_CAP_MULTIPLIER", 3.0)
    persona_bot._daily_budget = 32
    persona_bot._replies_today = 96
    assert persona_bot._hard_capped() is True


# --- everyone gets their own share ------------------------------------------


def _from(author, text="hello"):
    from conftest import FakeMessage

    return FakeMessage(author, text)


def test_a_person_under_their_quota_is_fine(persona_bot, bot_module, monkeypatch, stranger):
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 12)
    persona_bot._replies_by_person = {str(stranger.id): 11}
    assert persona_bot._person_capped(_from(stranger)) is False


def test_a_person_at_their_quota_is_capped(persona_bot, bot_module, monkeypatch, stranger):
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 12)
    persona_bot._replies_by_person = {str(stranger.id): 12}
    assert persona_bot._person_capped(_from(stranger)) is True


def test_one_person_running_out_does_not_affect_anyone_else(
    persona_bot, bot_module, monkeypatch, stranger, zack
):
    """The whole point: running out is something you do to yourself rather
    than to the room."""
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 12)
    persona_bot._replies_by_person = {str(stranger.id): 40}
    assert persona_bot._person_capped(_from(stranger)) is True
    assert persona_bot._person_capped(_from(zack)) is False


def test_allies_have_no_per_person_quota(persona_bot, bot_module, monkeypatch, jack):
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 12)
    persona_bot._replies_by_person = {str(jack.id): 500}
    assert persona_bot._person_capped(_from(jack)) is False


def test_a_zero_quota_disables_it(persona_bot, bot_module, monkeypatch, stranger):
    monkeypatch.setattr(bot_module, "LIVE_PER_PERSON_MAX", 0)
    persona_bot._replies_by_person = {str(stranger.id): 500}
    assert persona_bot._person_capped(_from(stranger)) is False


def test_per_person_spend_survives_a_restart(stateful_bot):
    stateful_bot._replies_by_person = {"123": 7, "456": 2}
    stateful_bot._save_day()
    stateful_bot._replies_by_person = {}
    assert stateful_bot._restore_day(stateful_bot._reply_day) is True
    assert stateful_bot._replies_by_person == {"123": 7, "456": 2}


def test_a_new_day_clears_per_person_spend(persona_bot, bot_module, monkeypatch):
    import datetime

    monkeypatch.setattr(bot_module, "LIVE_UNLIMITED", True)
    persona_bot._save_day = lambda: None
    persona_bot._schedule_pokes = lambda today: None
    persona_bot._replies_by_person = {"123": 40}
    persona_bot._roll_day(datetime.date(2026, 7, 29))
    assert persona_bot._replies_by_person == {}


def test_saving_before_the_day_is_set_is_refused(persona_bot, tmp_path, bot_module):
    """str(None) is a valid JSON string that matches no date, so such a file
    is silently rejected on the next startup and the budget refills mid-day.
    A throwaway script did exactly that and reset an evening's counters."""
    path = tmp_path / "s.json"
    persona_bot._state_path = lambda: str(path)
    persona_bot._save_day = bot_module.PersonaBot._save_day.__get__(persona_bot)

    persona_bot._reply_day = None
    persona_bot._save_day()
    assert not path.exists(), "a dayless save must not touch the state file"


def test_an_existing_file_is_not_clobbered_by_a_dayless_save(
    persona_bot, tmp_path, bot_module
):
    import datetime
    import json

    path = tmp_path / "s.json"
    path.write_text(json.dumps({"day": "2026-07-28", "replies": 58}))
    persona_bot._state_path = lambda: str(path)
    persona_bot._save_day = bot_module.PersonaBot._save_day.__get__(persona_bot)

    persona_bot._reply_day = None
    persona_bot._save_day()
    assert json.loads(path.read_text())["replies"] == 58
