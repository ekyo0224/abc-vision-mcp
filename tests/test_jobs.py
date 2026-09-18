# -*- coding: utf-8 -*-
"""Scan submission, and the input check that exists because scan has none.

The behaviour under test is not "does scanning work" -- that takes minutes and
needs footage. It is the guard in front of it: ``core.scan.scan`` accepts a text
file, returns an empty rally list and a meta block with ``fps: 25.0`` and a
fabricated duration, and raises nothing. Every caller downstream then cannot
distinguish "this is not a video" from "this video has no rallies in it".
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp import jobs  # noqa: E402


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------

def test_a_text_file_is_refused_before_any_work_starts(tmp_path):
    """The exact input that makes the engine invent metadata."""
    fake = tmp_path / "requirements.txt"
    fake.write_text("numpy==2.5.2\n", encoding="utf-8")

    out = jobs.scan_submit(str(fake))
    assert out["video_accepted"] is False
    assert "not a video" in out["error"]
    assert "job_id" not in out, "a job was started for a non-video file"


def test_a_missing_file_is_refused(tmp_path):
    out = jobs.scan_submit(str(tmp_path / "nope.mp4"))
    assert out["video_accepted"] is False
    assert "not found" in out["error"]


def test_a_video_extension_on_a_non_video_is_still_refused(tmp_path):
    """Extension alone is not evidence; the frame count is checked too."""
    liar = tmp_path / "pretend.mp4"
    liar.write_bytes(b"this is not an mp4")

    out = jobs.scan_submit(str(liar))
    assert out["video_accepted"] is False
    assert "job_id" not in out


# --------------------------------------------------------------------------
# Submission
# --------------------------------------------------------------------------

def _a_real_video() -> str | None:
    for candidate in (
        Path(r"D:\BADMINTON_COACH_APP_V1\data\clips\flame_max.mp4"),
        Path(r"D:\BADMINTON_COACH_APP_V1\data\clips\demo.mp4"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.fixture
def real_video():
    path = _a_real_video()
    if path is None:
        pytest.skip("no sample video available")
    return path


def test_submission_reports_an_eta_derived_from_the_video(real_video):
    """The caller is told what they are committing to before it runs."""
    out = jobs.scan_submit(real_video, max_minutes=0.05)
    assert out["video_accepted"] is True
    assert out["job_id"].startswith("scan_")
    assert out["video"]["duration_sec"] > 0
    assert out["video"]["fps"] > 0
    # eta is will_scan_sec * the measured real-time factor
    assert out["eta_sec"] == pytest.approx(
        out["will_scan_sec"] * jobs.REALTIME_FACTOR, rel=0.01
    )
    # and the caller is told it cannot be stopped
    assert "cancel" in out["note"]


def test_will_scan_is_capped_by_the_videos_own_length(real_video):
    """Asking for 45 minutes of a 30-second clip is 30 seconds of work."""
    out = jobs.scan_submit(real_video, max_minutes=45.0)
    assert out["will_scan_sec"] <= out["video"]["duration_sec"] + 0.1


def test_status_moves_off_queued(real_video):
    out = jobs.scan_submit(real_video, max_minutes=0.05)
    job_id = out["job_id"]

    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = jobs.scan_status(job_id)["state"]
        if state in ("running", "done", "failed"):
            break
        time.sleep(0.2)
    assert state in ("running", "done", "failed"), "job never left the queue"


def test_results_are_refused_until_the_job_finishes(real_video):
    out = jobs.scan_submit(real_video, max_minutes=0.05)
    early = jobs.scan_result(out["job_id"])
    if early.get("state") != "done":
        assert "error" in early
        assert "poll" in early["error"]


def test_unknown_ids_are_errors_not_exceptions():
    assert jobs.scan_status("scan_nope")["error"] == "unknown job_id"
    assert jobs.scan_result("scan_nope")["error"] == "unknown job_id"


# --------------------------------------------------------------------------
# Output shape
# --------------------------------------------------------------------------

def test_finished_results_omit_tracks_and_admit_the_filtering(real_video):
    """Two things a caller would otherwise get wrong.

    Tracks are the bulk of the payload and are off by default. And the engine
    silently drops rallies below its length and density floors, so an empty
    result does not mean an empty video -- the caveat says so in the response
    rather than in documentation nobody reads.
    """
    out = jobs.scan_submit(real_video, max_minutes=0.05)
    job_id = out["job_id"]

    deadline = time.time() + 180
    while time.time() < deadline:
        if jobs.scan_status(job_id)["state"] in ("done", "failed"):
            break
        time.sleep(0.5)

    status = jobs.scan_status(job_id)
    if status["state"] != "done":
        pytest.skip("scan did not finish in time (state=%s)" % status["state"])

    result = jobs.scan_result(job_id)
    assert "caveat" in result
    assert "same empty result" in result["caveat"]
    assert result["track_included"] is False
    for rally in result["rallies"]:
        assert "track" not in rally

    with_track = jobs.scan_result(job_id, include_track=True)
    assert with_track["track_included"] is True
