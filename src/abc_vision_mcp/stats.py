# -*- coding: utf-8 -*-
"""Production outcomes: what the honesty gate actually did, over 1,117 jobs.

The de-identified export in ``data/deidentified/`` is one row per analysis job
run between 2026-09-06 and 2026-09-17, with every identifier removed before it
left the production host -- no device id, no filename, no nickname, no email,
no video path.

It matters because the product's central claim is that it declines to answer
when it is not sure, and this is the file that says how often that happened and
why. A claim like "confidence-aware" is a slogan until someone can point at the
refusal rate.

One warning that belongs next to every number computed here: **the denominator
is a choice, and it changes the answer.** 120 of 244 jobs since 2026-09-15 were
given a level. Over all jobs that is 49.2%; over jobs that produced a report at
all it is 55.8%. Both are true. Neither is meaningful without saying which one
it is, so every function here returns both and names them.
"""

from __future__ import annotations

import csv
import io
import os
import statistics
from collections import Counter
from typing import Any

DEFAULT_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "deidentified", "production_outcomes_deidentified_20260918.csv",
)

# Rows where the pipeline never produced a report -- expired, failed, or still
# running. They are real outcomes and belong in the total, but they are not
# analyses that reached the gate, so they are excluded from the report-based
# denominator rather than silently counted as refusals.
NO_REPORT = "no_report_produced"

OUTCOME_LABELS = {
    "given_level": "a skill level was published",
    "tracked_seconds_under_45": "declined: too little of the player could be tracked",
    "no_usable_rallies": "declined: no usable rallies were found",
    "camera_shake": "declined: the camera moved too much",
    "identity_no_anchor": "declined: the player could not be identified",
    "serve_split_unreliable": "declined: serve segmentation was not trustworthy",
    "insufficient_other": "declined: other insufficiency",
    "other": "other",
    NO_REPORT: "no report produced (expired, failed, or still running)",
}


def load_rows(path: str | None = None) -> list[dict[str, str]]:
    src = path or DEFAULT_CSV
    if not os.path.isfile(src):
        raise FileNotFoundError("de-identified export not found: %s" % src)
    with io.open(src, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def outcome_breakdown(
    since: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Distribution of job outcomes, with both denominators stated.

    Args:
        since: ISO date (YYYY-MM-DD). Only jobs on or after it are counted.

    Returns a dict whose ``outcomes`` entries each carry ``pct_of_all`` and
    ``pct_of_reported`` -- never a bare percentage, because a bare percentage
    here is ambiguous by construction.
    """
    rows = load_rows(path)
    if since:
        rows = [r for r in rows if (r.get("date") or "") >= since]

    total = len(rows)
    reported = sum(1 for r in rows if r.get("outcome") != NO_REPORT)
    counts = Counter(r.get("outcome") or "unknown" for r in rows)

    declined = sum(
        v for k, v in counts.items()
        if k not in (NO_REPORT, "given_level", "other")
    )

    return {
        "window": {
            "since": since,
            "first_date": min((r["date"] for r in rows), default=None),
            "last_date": max((r["date"] for r in rows), default=None),
        },
        "denominators": {
            "all_jobs": total,
            "jobs_that_produced_a_report": reported,
            "note": (
                "Percentages differ by denominator. A job that expired before "
                "anyone opened it never reached the gate, so it is counted in "
                "all_jobs but not in jobs_that_produced_a_report."
            ),
        },
        "headline": {
            "published_a_level": counts.get("given_level", 0),
            "published_a_level_pct_of_reported": _pct(counts.get("given_level", 0), reported),
            "declined_to_publish": declined,
            "declined_to_publish_pct_of_reported": _pct(declined, reported),
        },
        "outcomes": [
            {
                "outcome": name,
                "meaning": OUTCOME_LABELS.get(name, name),
                "jobs": n,
                "pct_of_all": _pct(n, total),
                "pct_of_reported": (
                    _pct(n, reported) if name != NO_REPORT else None
                ),
            }
            for name, n in counts.most_common()
        ],
    }


def human_approval_dropoff(path: str | None = None) -> dict[str, Any]:
    """Jobs where the system asked a person to confirm, and nobody came back.

    The competition rules count ``request for human approval`` as a qualifying
    action in a perception-decision-action loop. This is that branch measured
    in production -- and it is the branch that fails most often, which is worth
    more to a technical report than a branch that always succeeds.

    ``PICK_ABANDONED`` means: the analysis finished, the system could not
    identify the player on its own, it asked the player to tap themselves, and
    the player never returned before the hold expired.
    """
    rows = load_rows(path)
    no_report = [r for r in rows if r.get("outcome") == NO_REPORT]
    abandoned = [
        r for r in no_report
        if "PICK_ABANDONED" in (r.get("error_code") or "")
    ]

    lengths = sorted(
        float(r["video_sec"]) for r in abandoned
        if (r.get("video_sec") or "").strip()
    )
    # statistics.median, not lengths[n//2]: with an even count the latter picks
    # the upper of the two middle values and reports 295 where the true median
    # is 291. A technical report that quotes the same figure two ways is worse
    # than one that quotes it once.
    median = statistics.median(lengths) if lengths else None
    five_min_plus = sum(1 for s in lengths if s >= 300)

    return {
        "jobs_without_a_report": len(no_report),
        "human_approval_requested_then_abandoned": len(abandoned),
        "pct_of_jobs_without_a_report": _pct(len(abandoned), len(no_report)),
        "by_platform": dict(Counter(r.get("platform") or "unknown" for r in abandoned)),
        "video_seconds_median": median,
        "at_least_five_minutes": five_min_plus,
        "at_least_five_minutes_pct": _pct(five_min_plus, len(lengths)) if lengths else 0.0,
        "reading": (
            "These are not bad uploads. Half of them are five minutes or "
            "longer -- the length that most often yields a level. The loop "
            "asked for human confirmation and the request did not reach the "
            "person in time. The failure is in the hand-off, not in the vision."
        ),
    }


def decline_reasons(since: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Why the gate declined, ranked. The failure taxonomy, straight from production."""
    rows = load_rows(path)
    if since:
        rows = [r for r in rows if (r.get("date") or "") >= since]

    declined = [
        r for r in rows
        if r.get("outcome") not in (NO_REPORT, "given_level", "other")
    ]
    counts = Counter(r.get("outcome") for r in declined)
    return {
        "declined_jobs": len(declined),
        "reasons": [
            {
                "outcome": name,
                "meaning": OUTCOME_LABELS.get(name, name),
                "jobs": n,
                "pct_of_declined": _pct(n, len(declined)),
            }
            for name, n in counts.most_common()
        ],
    }
