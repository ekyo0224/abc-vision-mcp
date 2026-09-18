# -*- coding: utf-8 -*-
"""Rally detection as a job, because it cannot be a request.

``core.scan.scan`` is the OpenCV 5 pass over every sampled frame of a video.
Measured on 1080p60 footage it runs at **0.78-0.82x real time** -- a six-minute
clip takes about five minutes, and the engine's own default of 45 minutes takes
roughly 35. No MCP client waits that long, so this is submit / poll / fetch
rather than a single call.

Three behaviours of ``scan`` shape this module, all of them found by measuring
rather than by reading:

- **It does not reject non-video input.** Handed a text file it returns an empty
  rally list and a meta block containing ``fps: 25.0`` and a duration it made
  up, with no error. A caller cannot tell that apart from a video with no
  rallies in it, so the check happens here, before submitting.
- **Its output is large.** Each rally carries a ``track`` of up to ~1,500
  points; ten rallies is comfortably over 150 KB. Sent into a model's context
  that buries everything else, so tracks are stripped unless asked for.
- **It cannot be cancelled.** There is no cancellation token and the progress
  callback's return value is ignored. Once started, a job runs to completion.
  Saying so is better than implying a stop button exists.

``decoder`` and ``single_decode`` are not exposed. Both have caused regressions
(``core/scan.py:548-551``, 2026-08-19, pixel shift flipping rally verdicts;
``server.py:126``, 2026-09-03, frame-bus seek divergence) and neither belongs in
the hands of a caller who cannot see those notes.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from .identity import ENGINE_PATH

VIDEO_SUFFIXES = frozenset({
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv",
})

# Measured: 0.78-0.82x real time on 1080p60, six cores. Used only to give the
# caller an expectation, never to decide anything.
REALTIME_FACTOR = 0.8

_scan_mod: Any = None


def _engine_scan() -> Any:
    global _scan_mod
    if _scan_mod is not None:
        return _scan_mod
    import sys

    if ENGINE_PATH not in sys.path:
        sys.path.insert(0, ENGINE_PATH)
    from core import scan as scan_mod  # type: ignore

    _scan_mod = scan_mod
    return scan_mod


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

def _probe(video_path: str) -> dict[str, Any]:
    """Confirm this is a video and report its length, before committing minutes.

    ``cv2.VideoCapture`` opens almost anything and reports plausible-looking
    defaults for files it did not understand, so the frame count is checked too:
    a real video has frames.
    """
    if not os.path.isfile(video_path):
        return {"ok": False, "error": "file not found"}

    suffix = os.path.splitext(video_path)[1].lower()
    if suffix not in VIDEO_SUFFIXES:
        return {
            "ok": False,
            "error": "not a video file (%s). Scanning it would return an empty "
                     "rally list and invented metadata rather than an error."
                     % (suffix or "no extension"),
        }

    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return {"ok": False, "error": "could not be opened as video"}
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    finally:
        cap.release()

    if frames <= 0 or fps <= 0:
        return {"ok": False, "error": "opened, but reports no frames -- not a "
                                      "readable video"}
    return {"ok": True, "fps": round(fps, 2), "frames": int(frames),
            "duration_sec": round(frames / fps, 1)}


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

class ScanJob:
    def __init__(self, video_path: str, max_minutes: float,
                 airspace: list | None, probe: dict) -> None:
        self.id = "scan_" + uuid.uuid4().hex[:12]
        self.video_path = video_path
        self.max_minutes = max_minutes
        self.airspace = airspace
        self.probe = probe
        self.state = "queued"
        self.progress = 0.0
        self.submitted_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.rallies: list | None = None
        self.meta: dict | None = None
        self.error: str | None = None


JOBS: dict[str, ScanJob] = {}
_LOCK = threading.Lock()


def _run(job: ScanJob) -> None:
    job.state = "running"
    job.started_at = time.time()
    try:
        scan_mod = _engine_scan()

        def on_progress(pct, *_a, **_kw):
            try:
                job.progress = round(float(pct), 3)
            except Exception:  # noqa: BLE001
                pass

        rallies, meta = scan_mod.top_rallies(
            job.video_path,
            n=20,
            progress=on_progress,
            max_minutes=job.max_minutes,
            airspace=job.airspace,
        )
        job.rallies = list(rallies or [])
        job.meta = dict(meta or {})
        job.state = "done"
        job.progress = 1.0
    except Exception as exc:  # noqa: BLE001
        job.state = "failed"
        job.error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        job.finished_at = time.time()


def scan_submit(
    video_path: str,
    max_minutes: float = 10.0,
    airspace: list | None = None,
) -> dict[str, Any]:
    """Start a rally-detection pass and return a handle.

    ``max_minutes`` defaults to 10 rather than the engine's 45: at 0.8x real
    time, 45 is a 35-minute job, which is rarely what someone means on a first
    call.
    """
    probe = _probe(video_path)
    if not probe.get("ok"):
        return {"error": probe["error"], "video_accepted": False}

    scanned = min(float(max_minutes) * 60.0, probe["duration_sec"])
    job = ScanJob(video_path, float(max_minutes), airspace, probe)
    with _LOCK:
        JOBS[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()

    return {
        "job_id": job.id,
        "video_accepted": True,
        "video": {"duration_sec": probe["duration_sec"], "fps": probe["fps"]},
        "will_scan_sec": round(scanned, 1),
        "eta_sec": round(scanned * REALTIME_FACTOR, 1),
        "note": (
            "Measured at %.1fx real time. There is no way to cancel a scan once "
            "it starts, so choose max_minutes deliberately."
            % REALTIME_FACTOR
        ),
    }


def scan_status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        return {"error": "unknown job_id", "job_id": job_id}

    elapsed = (job.finished_at or time.time()) - (job.started_at or job.submitted_at)
    out: dict[str, Any] = {
        "job_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "elapsed_sec": round(elapsed, 1),
    }
    if job.state == "done":
        out["rallies_found"] = len(job.rallies or [])
        out["next"] = "call scan_result for the rallies"
    elif job.state == "failed":
        out["error"] = job.error
    else:
        remaining = max(0.0, (job.probe["duration_sec"] * REALTIME_FACTOR) - elapsed)
        out["eta_remaining_sec"] = round(remaining, 1)
    return out


def scan_result(job_id: str, include_track: bool = False,
                limit: int = 10) -> dict[str, Any]:
    """The rallies, newest-quality first.

    ``track`` -- the per-frame shuttle path, up to ~1,500 points per rally -- is
    omitted unless asked for. Ten rallies with tracks is over 150 KB, which in a
    model's context displaces everything worth reading.
    """
    job = JOBS.get(job_id)
    if job is None:
        return {"error": "unknown job_id", "job_id": job_id}
    if job.state != "done":
        return {"job_id": job_id, "state": job.state,
                "error": "not finished; poll scan_status"}

    rallies = []
    for r in (job.rallies or [])[:limit]:
        row = {k: v for k, v in r.items() if k != "track"}
        if include_track:
            row["track"] = r.get("track")
        rallies.append(row)

    found = len(job.rallies or [])
    return {
        "job_id": job_id,
        "rallies_found": found,
        "rallies_returned": len(rallies),
        "truncated": found > len(rallies),
        "rallies": rallies,
        "meta": job.meta,
        "track_included": include_track,
        "caveat": (
            "Rallies shorter than 2.0 s or below a confirmation density of 0.12 "
            "are dropped inside the engine and are not counted here. A video "
            "with no rallies and a video whose rallies were all filtered out "
            "produce the same empty result."
        ),
    }
