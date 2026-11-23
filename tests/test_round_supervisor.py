"""The round supervisor's policy: completion, carry-safe recycling and the no-endless-wait bound."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import round_supervisor as rs

CFG = rs.Config()
T0 = 1_000_000.0


def tracker(**kw: object) -> rs.Tracker:
    base: dict[str, object] = {"round": 4, "started": T0, "last_progress": T0}
    return rs.Tracker(**{**base, **kw})  # type: ignore[arg-type]


def obs(after: float, **kw: object) -> rs.Observation:
    base: dict[str, object] = {
        "now": T0 + after,
        "status": "idle",
        "sentinel": None,
        "activity": T0 + after,
    }
    return rs.Observation(**{**base, **kw})  # type: ignore[arg-type]


def test_idle_without_sentinel_is_not_completion() -> None:
    assert rs.decide(CFG, tracker(), obs(60, status="idle")).kind == "wait"


def test_sentinel_completes_the_round_once_settled() -> None:
    done = {"outcome": "continue"}
    assert rs.decide(CFG, tracker(), obs(60, sentinel=done)).kind == "next"
    t = tracker()
    assert rs.decide(CFG, t, obs(60, sentinel=done, status="working")).kind == "wait"
    late = obs(60 + CFG.settle_s, sentinel=done, status="working")
    assert rs.decide(CFG, t, late).kind == "next"


def test_requested_halts_win_over_the_next_round() -> None:
    assert rs.decide(CFG, tracker(), obs(1, sentinel={"outcome": "halt"})).kind == "halt"
    after = obs(1, sentinel={"outcome": "continue"}, stop_after_round=True)
    assert rs.decide(CFG, tracker(), after).kind == "halt"
    assert rs.decide(CFG, tracker(), obs(1, stop_now=True)).kind == "halt"
    assert rs.decide(CFG, tracker(), obs(1, stop_after_round=True)).kind == "wait"


def test_silence_nudges_after_the_threshold_only() -> None:
    assert rs.decide(CFG, tracker(), obs(CFG.silence_s - 1, activity=T0)).kind == "wait"
    assert rs.decide(CFG, tracker(), obs(CFG.silence_s, activity=T0)).kind == "nudge_silent"


def test_a_heartbeating_session_with_no_outward_progress_still_terminates() -> None:
    """Transcript writes alone must not extend the round forever."""
    t = tracker()
    kinds: list[str] = []
    elapsed = 0
    while elapsed < CFG.round_cap_s and "recycle" not in kinds:
        elapsed += CFG.poll_s
        action = rs.decide(CFG, t, obs(elapsed))  # activity is always "just now"
        kinds.append(action.kind)
        if action.kind.startswith("nudge"):
            t.nudges += 1
            t.last_nudge = T0 + elapsed
    assert kinds.count("nudge_progress") == CFG.max_nudges
    assert kinds[-1] == "recycle"


def test_round_cap_recycles_a_busy_round() -> None:
    t = tracker(last_progress=T0 + CFG.round_cap_s)
    assert rs.decide(CFG, t, obs(CFG.round_cap_s)).kind == "recycle"


def test_vanished_agent_recycles() -> None:
    assert rs.decide(CFG, tracker(), obs(5, status=None)).kind == "recycle"


def test_an_unanswered_dialog_is_refused_never_approved() -> None:
    t = tracker()
    assert rs.decide(CFG, t, obs(10, status="blocked")).kind == "wait"
    assert rs.decide(CFG, t, obs(10 + CFG.blocked_s, status="blocked")).kind == "deny"


def test_usage_limit_waits_without_nudging_but_only_for_a_bounded_time() -> None:
    t = tracker()
    assert rs.decide(CFG, t, obs(CFG.silence_s, activity=T0, limited=True)).reason == "usage limit"
    assert t.nudges == 0
    late = obs(CFG.silence_s + CFG.limit_max_s, activity=T0, limited=True)
    assert rs.decide(CFG, t, late).reason != "usage limit"


def test_breaker_halts_on_repeated_recycles_and_on_a_frozen_main() -> None:
    t = tracker(main_at_start="a")
    assert rs.after_round(CFG, t, recycled=True, main_sha="b") is None
    assert (stop := rs.after_round(CFG, t, recycled=True, main_sha="c")) is not None
    assert stop.kind == "halt"
    t = tracker(main_at_start="a")
    assert rs.after_round(CFG, t, recycled=False, main_sha="a") is None
    assert rs.after_round(CFG, t, recycled=False, main_sha="a") is None
    assert rs.after_round(CFG, t, recycled=False, main_sha="a") is not None
    t = tracker(main_at_start="a", recycles=1, no_advance=2)
    assert rs.after_round(CFG, t, recycled=False, main_sha="b") is None
    assert (t.recycles, t.no_advance) == (0, 0)


def test_failed_probe_counts_as_no_change() -> None:
    assert rs.fingerprint(lambda _cmd, _t: (1, "")) is None


def test_a_round_manifest_write_counts_as_outward_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    manifest = tmp_path / ".agent-runs" / "R-1" / "round.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("a")
    probe = lambda _cmd, _t: (0, "abc refs/heads/main")  # noqa: E731
    before = rs.fingerprint(probe)
    os.utime(manifest, ns=(1, 1))
    assert rs.fingerprint(probe) != before


class FakeHerdr(rs.Herdr):
    """Records which tab is closed; the agent list is scripted."""

    def __init__(self, agents: list[dict[str, object]]) -> None:
        super().__init__(lambda _cmd, _t: (0, "{}"))
        self.listed = agents
        self.closed: list[str] = []

    def agents(self) -> list[dict[str, object]]:  # type: ignore[override]
        return self.listed

    def close_tab(self, tab: str) -> None:
        self.closed.append(tab)


def test_ending_a_round_closes_only_its_own_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs.time, "sleep", lambda _s: None)
    live = {"name": "live-val082", "agent": "claude", "tab_id": "wC:t11"}
    herdr = FakeHerdr([live])
    sup = rs.Supervisor(CFG, (), herdr)
    sup.tab = "wC:t99"
    sup.end_session()
    assert herdr.closed == ["wC:t99"]


def test_every_supervised_session_starts_in_auto_mode() -> None:
    calls: list[list[str]] = []

    def record(cmd: object, _timeout: float) -> tuple[int, str]:
        calls.append(list(cmd))  # type: ignore[call-overload]
        return 0, '{"result": {}}'

    sup = rs.Supervisor(CFG, ("--verbose",), rs.Herdr(record))
    sup.herdr.start("wC:p9", "uuid", 1, sup.extra)
    assert calls[0][-3:] == ["--permission-mode", "auto", "--verbose"]


def test_the_orchestrator_tab_inherits_the_supervised_root() -> None:
    calls: list[list[str]] = []

    def record(cmd: object, _timeout: float) -> tuple[int, str]:
        calls.append(list(cmd))  # type: ignore[call-overload]
        return 0, '{"result": {"tab": {"tab_id": "t"}, "root_pane": {"pane_id": "p"}}}'

    assert rs.Herdr(record).new_tab() == ("t", "p")
    assert f"ROUND_SUPERVISOR_ROOT={rs.ROOT}" in calls[0]


def test_overrides_shorten_timers_and_reject_unknown_keys() -> None:
    assert rs.with_overrides(CFG, ["silence_s=60"]).silence_s == 60
    with pytest.raises(TypeError):
        rs.with_overrides(CFG, ["nope=1"])


def test_a_note_must_be_a_tldr_and_open_items_need_a_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    assert rs.note("result", "x" * (rs.NOTE_MAX + 1), "", "") == 2
    assert rs.note("open", "needs a ruling", "", "") == 2
    assert rs.read_news() == []


def test_owed_items_stay_listed_until_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    assert rs.note("open", "Rule on X-01", "X-01", "") == 0
    assert rs.note("open", "Rule on X-02", "X-02", "") == 0
    assert rs.note(None, "", "", "X-01") == 0
    assert [i["ref"] for i in rs.open_items(rs.read_news())] == ["X-02"]


def test_deadline_requests_a_stop_only_once_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    assert not rs.stop_requested()
    rs.set_deadline("1h30m")
    assert not rs.stop_requested(rs.time.time() + 5000)
    assert rs.stop_requested(rs.time.time() + 5500)
    with pytest.raises(ValueError):
        rs.parse_duration("soon")


def test_phase_shows_a_dead_supervisor_and_a_halt() -> None:
    assert rs.phase_of(halt=None, alive=False, stopping=False)[0] == "SUPERVISOR DOWN"
    assert rs.phase_of(halt={"reason": "r"}, alive=False, stopping=False) == ("HALTED", "r")
    assert rs.phase_of(halt=None, alive=True, stopping=True)[0] == "STOPPING"


def _view(news: list[dict[str, object]]) -> dict[str, object]:
    return {
        "now": T0, "phase": ("RUNNING", ""), "round": 3, "started": T0 - 600, "deadline": None,
        "lanes": [("live-val082", "idle")], "news": news,
    }  # fmt: skip


def test_render_fits_the_screen_keeps_status_and_scrolls_the_news() -> None:
    news = [
        {"at": T0 - i, "round": 3, "kind": "result", "text": f"item {i}", "ref": ""}
        for i in reversed(range(50))  # the file is append-only, oldest first
    ]
    first = rs.render(_view(news), 80, 24, 0)
    assert len(first) == 24 and "RUNNING" in first[0] and "item 0" in "".join(first)
    scrolled = "".join(rs.render(_view(news), 80, 24, 30))
    assert "RUNNING" in scrolled and "item 30" in scrolled and "item 0 " not in scrolled


def test_stage_is_shown_in_the_header_not_the_feed() -> None:
    stage = {"at": T0, "round": 3, "kind": "stage", "text": "merge-round", "ref": ""}
    lines = rs.render(_view([stage]), 80, 24, 0)
    assert "merge-round" in lines[0] and "merge-round" not in "".join(lines[1:])


def test_preflight_refuses_another_working_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "wC:me")
    other = {"agent": "claude", "cwd": str(rs.ROOT), "pane_id": "wC:p1", "agent_status": "working"}
    sup = rs.Supervisor(CFG, (), FakeHerdr([other]))
    with pytest.raises(SystemExit):
        sup.preflight(allow_other=False)
    sup.preflight(allow_other=True)


def _open_round(tmp_path: Path, started: float) -> None:
    (tmp_path / "current.json").write_text(json.dumps({"round": 7, "started": started}))


def test_complete_requires_a_handoff_from_this_round(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    _open_round(tmp_path, 2_000_000_000.0)  # after any file written now
    (tmp_path / "HANDOFF.md").write_text("x")
    assert rs.complete("continue", "", lambda _c, _t: (0, "")) == 1
    assert not (tmp_path / "complete.json").exists()


def test_complete_records_the_round(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rs, "STATE", tmp_path)
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    _open_round(tmp_path, 1.0)
    (tmp_path / "HANDOFF.md").write_text("x")
    assert rs.complete("continue", "", lambda _c, _t: (1, "bad")) == 1
    assert rs.complete("continue", "", lambda _c, _t: (0, "")) == 0
    sentinel = rs.read_sentinel(7)
    assert sentinel is not None and sentinel["outcome"] == "continue"
    assert rs.read_sentinel(8) is None


def test_check_handoff_requires_sections(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text(
        "# Handoff\nGenerated-UTC: 2026-11-23T08:00:00Z\nMain-SHA: " + "a" * 40 + "\n\n## Round delta\nmerged A1\n\n"
        "## Open work\nnone\n\n## Next action\nplan round 2\n"
    )
    assert rs.check_handoff(good) == 0
    bad = tmp_path / "bad.md"
    bad.write_text("# Handoff\nGenerated-UTC: t\nMain-SHA: a\n\n## Round delta\n<!-- x -->\n")
    assert rs.check_handoff(bad) == 1

    assert rs.check_handoff(Path("templates/handoff.md")) == 1  # placeholders are not content

