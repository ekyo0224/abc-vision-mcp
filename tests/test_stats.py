# -*- coding: utf-8 -*-
"""Lock the production figures that the technical report quotes.

Every number asserted here was verified by hand against the de-identified
export before it was written down, and each one is destined for a submission
that judges may check. So these are not really unit tests: they are a tripwire.
If the export is refreshed or the aggregation changes, these fail loudly, and
that is the signal that the report needs updating too -- rather than the report
quietly disagreeing with the code that produced it.

Cross-check: the same figures were computed independently by the project's own
analysis (reported as "56% given a level, 30% tracked under 45s" over the
report-producing denominator) and matched to within rounding.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp import stats  # noqa: E402


# --------------------------------------------------------------------------
# The export itself
# --------------------------------------------------------------------------

def test_export_is_present_and_the_expected_size():
    rows = stats.load_rows()
    assert len(rows) == 1117
    assert min(r["date"] for r in rows) == "2026-09-06"
    assert max(r["date"] for r in rows) == "2026-09-17"


def test_export_carries_no_identifying_columns():
    """The whole point of the de-identified export."""
    rows = stats.load_rows()
    banned = {"device_id", "filename", "video_path", "nickname",
              "email", "subject", "subject_id", "job_id", "user_id"}
    present = set(rows[0].keys())
    assert not (present & banned), "identifying column present: %s" % (present & banned)


# --------------------------------------------------------------------------
# Headline figures
# --------------------------------------------------------------------------

def test_since_0915_matches_the_hand_verified_counts():
    out = stats.outcome_breakdown(since="2026-09-15")
    d = out["denominators"]
    assert d["all_jobs"] == 244
    assert d["jobs_that_produced_a_report"] == 215

    h = out["headline"]
    assert h["published_a_level"] == 120
    # 120/215 = 55.8%, which is the figure to quote. Over all 244 jobs the same
    # count is 49.2% -- both correct, which is exactly why neither is reported
    # without its denominator.
    assert h["published_a_level_pct_of_reported"] == 55.8


def test_full_window_is_stable_across_the_two_periods():
    """The refusal rate holding steady across periods is itself evidence.

    A gate whose behaviour swings week to week would be hard to present as a
    property of the system rather than of the week's uploads.
    """
    out = stats.outcome_breakdown()
    assert out["denominators"]["all_jobs"] == 1117
    assert out["denominators"]["jobs_that_produced_a_report"] == 705
    assert out["headline"]["published_a_level"] == 390
    assert out["headline"]["published_a_level_pct_of_reported"] == 55.3


def test_every_outcome_reports_both_denominators():
    out = stats.outcome_breakdown()
    for row in out["outcomes"]:
        assert "pct_of_all" in row
        assert "pct_of_reported" in row
        if row["outcome"] != stats.NO_REPORT:
            assert row["pct_of_reported"] is not None
        else:
            # a job that never produced a report is not a share of the reported
            # denominator, so this must stay None rather than 0.0
            assert row["pct_of_reported"] is None


def test_no_report_is_excluded_from_the_reported_denominator():
    rows = stats.load_rows()
    out = stats.outcome_breakdown()
    no_report = sum(1 for r in rows if r["outcome"] == stats.NO_REPORT)
    assert no_report == 412
    assert out["denominators"]["jobs_that_produced_a_report"] == len(rows) - no_report


# --------------------------------------------------------------------------
# Decline taxonomy
# --------------------------------------------------------------------------

def test_leading_decline_reason_is_insufficient_tracking():
    out = stats.decline_reasons(since="2026-09-15")
    top = out["reasons"][0]
    assert top["outcome"] == "tracked_seconds_under_45"
    assert top["jobs"] == 64


def test_every_decline_reason_has_a_plain_language_meaning():
    """Judges read the meaning, not the enum."""
    out = stats.decline_reasons()
    for row in out["reasons"]:
        assert row["meaning"] != row["outcome"], (
            "no plain-language label for %r" % row["outcome"]
        )


# --------------------------------------------------------------------------
# The human-approval branch
# --------------------------------------------------------------------------

def test_human_approval_dropoff_matches_hand_verified_counts():
    out = stats.human_approval_dropoff()
    assert out["jobs_without_a_report"] == 412
    assert out["human_approval_requested_then_abandoned"] == 110
    assert out["by_platform"] == {"android": 59, "ios": 51}


def test_abandoned_uploads_are_not_short_ones():
    """These are not 30-second clips.

    If they were, the drop-off would just be bad uploads. The median is a shade
    under five minutes and half clear it.

    This docstring used to add "which is the length band that most often
    produces a level". That was false -- see
    ``test_long_uploads_did_not_in_fact_yield_levels`` below -- and it is
    recorded in docs/CORRECTIONS.md.
    """
    out = stats.human_approval_dropoff()
    assert out["video_seconds_median"] == pytest.approx(290.9, abs=0.1)
    assert out["at_least_five_minutes"] == 54
    assert out["at_least_five_minutes_pct"] == pytest.approx(49.1, abs=0.1)


def test_long_uploads_did_not_in_fact_yield_levels():
    """The measurement that contradicted what this project used to claim.

    Long uploads were described as the length band that most often yields a
    level. In this export they are the band that never does -- on a denominator
    of ten, which is why the reading says so rather than calling it a rule.
    """
    out = stats.human_approval_dropoff()
    assert out["long_uploads_in_export"] == 68
    assert out["long_uploads_that_produced_a_report"] == 10
    assert out["long_uploads_that_yielded_a_level"] == 0


def test_reading_quotes_the_figures_beside_it():
    """The reading must be composed from the data, not written alongside it.

    The claim that failed was possible only because the sentence was a fixed
    string sitting next to numbers it never consulted. Every quantity it states
    must appear in the same payload.
    """
    out = stats.human_approval_dropoff()
    reading = out["reading"]
    for key in ("human_approval_requested_then_abandoned",
                "long_uploads_in_export",
                "long_uploads_that_produced_a_report",
                "long_uploads_that_yielded_a_level"):
        assert str(out[key]) in reading, "%s is not quoted in the reading" % key


def test_reading_makes_no_claim_the_data_does_not_support():
    """Guard against the specific sentences that were withdrawn.

    Two claims were removed: that five minutes is the length that most often
    yields a level (contradicted by the export), and that the perception
    succeeded on these jobs (never measured -- they produced no report, so the
    identity work on them was never scored).
    """
    reading = stats.human_approval_dropoff()["reading"].lower()
    for withdrawn in ("most often yields a level",
                      "not in the vision",
                      "the perception worked",
                      "the vision worked"):
        assert withdrawn not in reading, "withdrawn claim is back: %r" % withdrawn
    assert "we cannot say" in reading
    assert "we do not know" in reading


def test_median_is_the_true_median_not_the_upper_middle():
    """Regression guard.

    An earlier version indexed lengths[n // 2]. With 110 values that returns
    the upper of the two middle elements -- 295 where the median is 290.9. The
    report quotes this figure, so the two must not be allowed to drift apart.
    """
    out = stats.human_approval_dropoff()
    assert out["video_seconds_median"] != 295.0
