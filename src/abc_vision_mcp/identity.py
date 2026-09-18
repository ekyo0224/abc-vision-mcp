# -*- coding: utf-8 -*-
"""The re-planning loop, exposed so an agent drives it instead of a for-loop.

``core.identity.lock.assign`` answers "which detection is the subject, in every
sample". It takes ``avoid_anchors``, and it writes the anchor it chose into
``trace``. Those two parameters together are, by accident of good design, an
agentic interface: call it, read which anchor it picked and how many rallies
that plan covered, and if the plan is poor, call it again with that anchor
excluded. The second call produces a materially different plan -- a different
anchor, a different set of claimed frames.

In production that loop is orchestrated inside ``core/analysis.py``. Here it is
deliberately *not* orchestrated. Each call is one tool call, so the loop runs in
the MCP message flow where it can be seen: propose, score, reject, propose
again. The competition asks for a trace showing that vision output changed a
later tool call; the message flow is that trace, rather than a document
claiming one exists.

The engine's own docstring states the principle this module is built to
preserve:

    Frames the chain cannot claim are simply absent, and the caller records a
    gap: on a measurement that decides someone's level, a gap is honest and a
    guess is not.

Four ways to use ``assign`` wrongly, all of which fail silently, are blocked
here rather than documented -- see ``_as_anchor_key``, ``_int_keys`` and the
guard in ``propose_identity``.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

# The engine lives outside this repository and is never vendored into it: it
# carries customer data and cannot be redistributed. Point ABC_ENGINE_PATH at a
# checkout to enable these tools.
ENGINE_PATH = os.environ.get("ABC_ENGINE_PATH", r"D:\BADMINTON_COACH_APP_V1")

_lock_mod: Any = None
_import_error: str | None = None


def engine() -> Any:
    """Import ``core.identity.lock`` lazily, and say plainly when it is absent.

    Only this one engine module is needed. ``core.analysis``, which wraps it in
    production, currently fails to import (``core/hw_decode.py`` is missing from
    both the working tree and git history), so depending on it would make these
    tools unavailable for a reason that has nothing to do with identity.
    """
    global _lock_mod, _import_error
    if _lock_mod is not None:
        return _lock_mod
    if _import_error is not None:
        raise RuntimeError(_import_error)
    try:
        if ENGINE_PATH not in sys.path:
            sys.path.insert(0, ENGINE_PATH)
        from core.identity import lock  # type: ignore

        _lock_mod = lock
        return lock
    except Exception as exc:  # noqa: BLE001
        _import_error = (
            "engine module core.identity.lock is unavailable from %r: %s: %s"
            % (ENGINE_PATH, type(exc).__name__, exc)
        )
        raise RuntimeError(_import_error) from exc


# --------------------------------------------------------------------------
# The silent-failure guards
# --------------------------------------------------------------------------

def _as_anchor_key(value: Any) -> tuple | None:
    """Coerce an anchor key back to a tuple.

    ``trace["anchor_key"]`` is a ``(first, last, length)`` tuple. Send it
    through JSON and it comes back a list. ``avoid_anchors`` only ever tests
    membership, and ``[0, 116, 30] != (0, 116, 30)``, so a list is accepted,
    matches nothing, and every round picks the same anchor again -- a loop that
    runs forever while looking like it is working.
    """
    if value is None:
        return None
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return None


def _int_keys(boxes: dict) -> dict:
    """Restore integer frame indices.

    ``assign`` returns ``{int frame_index: box}``. JSON object keys are strings,
    so a round-trip turns them into ``"116"``. ``usable_range_count`` looks up
    by integer, finds nothing, and returns 0 without complaint -- which reads as
    "this plan covered no rallies" rather than "the keys are the wrong type".
    """
    out = {}
    for k, v in (boxes or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def _tuples(samples: Any) -> list[tuple]:
    """JSON gives lists; ``assign`` unpacks four-element sequences."""
    fixed = []
    for s in samples or []:
        if isinstance(s, (list, tuple)) and len(s) == 4:
            fi, boxes, sigs, heights = s
            fixed.append((int(fi), list(boxes), list(sigs), list(heights)))
    return fixed


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------

# Mirrors core/analysis.py:78. Changing it changes what "covered" means, and
# the production coverage gate is defined in the same terms -- so it is stated
# here rather than inlined.
USABLE_RANGE_MIN_HITS = 4

# The fixed body bands scan_differences falls back to when two appearances do
# not differ measurably. Their presence in the returned weights is the only
# signal that the comparison found nothing.
FALLBACK_BANDS = frozenset({"torso", "lower", "feet"})


def _box_at(boxes: dict, frame: int, tol: int):
    """Nearest claimed box within ``tol`` frames, mirroring SubjectTrack.box_at.

    Detection runs every ``tol`` frames, so a claim that many frames away still
    counts as covering this one. Reimplemented rather than imported because it
    lives in ``core/analysis.py``, which does not currently import -- see
    ``engine``.
    """
    box = boxes.get(frame)
    if box is not None:
        return box
    for d in range(1, tol + 1):
        box = boxes.get(frame - d) or boxes.get(frame + d)
        if box is not None:
            return box
    return None


def usable_range_count(boxes: dict, ranges: list, fps: float, step: int) -> int:
    """How many rallies have enough claimed frames to produce numbers.

    The same test the production coverage gate applies, so a plan scored here
    is scored the way the shipping gate would score it.
    """
    boxes = _int_keys(boxes)
    tol = max(1, int(step))
    usable = 0
    for a, d in (ranges or []):
        frames = range(int(a * fps), int((a + d) * fps), tol)
        hits = sum(1 for f in frames if _box_at(boxes, f, tol) is not None)
        if hits >= USABLE_RANGE_MIN_HITS:
            usable += 1
    return usable


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------

class Session:
    """Per-video evidence, held server-side.

    Samples are large -- production runs carry a median of 561 of them, each
    with boxes and appearance signatures. Passing that through every tool call
    would dominate the message flow and bury the decisions, which are the part
    worth reading.
    """

    def __init__(self, samples, fps, enrolled_sig, enrolled_height,
                 rival_sigs=None, weights=None, ranges=None) -> None:
        self.id = "sess_" + uuid.uuid4().hex[:12]
        self.samples = _tuples(samples)
        self.fps = float(fps)
        self.enrolled_sig = enrolled_sig
        self.enrolled_height = enrolled_height
        self.rival_sigs = rival_sigs or []
        self.weights = weights
        self.ranges = [tuple(r) for r in (ranges or [])]
        self.created_at = time.time()
        self.plans: dict[str, dict] = {}


SESSIONS: dict[str, Session] = {}


def open_session(
    samples: list,
    fps: float,
    enrolled_sig: dict,
    enrolled_height: float | None = None,
    rival_sigs: list | None = None,
    weights: dict | None = None,
    ranges: list | None = None,
) -> dict[str, Any]:
    """Register one video's evidence and return a handle."""
    sess = Session(samples, fps, enrolled_sig, enrolled_height,
                   rival_sigs, weights, ranges)
    SESSIONS[sess.id] = sess
    return {
        "session_id": sess.id,
        "samples": len(sess.samples),
        "fps": sess.fps,
        "rallies": len(sess.ranges),
        "has_enrolled_signature": bool(enrolled_sig),
    }


# --------------------------------------------------------------------------
# The loop, one step at a time
# --------------------------------------------------------------------------

def propose_identity(
    session_id: str,
    avoid_anchors: list | None = None,
    anchor_pref: str | None = None,
) -> dict[str, Any]:
    """One plan for who the subject is, given anchors already ruled out.

    Returns the anchor this plan rests on, how much of the video it claims, and
    how many rallies it covers -- enough for the caller to decide whether to
    accept it or exclude this anchor and ask again.
    """
    sess = SESSIONS.get(session_id)
    if sess is None:
        return {"error": "unknown session_id", "session_id": session_id}

    # Guard the one failure mode that produces a confident wrong answer rather
    # than a refusal: with no enrolled signature but a height present, assign
    # silently falls back to comparing box heights and returns a full,
    # plausible-looking assignment. Everything else here fails loudly.
    if not sess.enrolled_sig:
        return {
            "error": "no_enrolled_signature",
            "detail": (
                "Without an appearance signature the engine would fall back to "
                "matching on box height alone and return an answer that looks "
                "confident. Refusing instead."
            ),
        }

    lock = engine()
    avoid = {k for k in (_as_anchor_key(a) for a in (avoid_anchors or [])) if k}
    trace: dict[str, Any] = {}

    started = time.time()
    boxes = lock.assign(
        sess.samples,
        sess.fps,
        sess.enrolled_sig,
        sess.enrolled_height,
        weights=sess.weights,
        rival_sigs=sess.rival_sigs,
        trace=trace,
        avoid_anchors=avoid or None,
        anchor_pref=anchor_pref,
    )
    elapsed_ms = round((time.time() - started) * 1000.0, 1)

    anchor = _as_anchor_key(trace.get("anchor_key"))
    covered = (
        usable_range_count(boxes, sess.ranges, sess.fps, 1)
        if sess.ranges else None
    )

    plan_id = "plan_" + uuid.uuid4().hex[:10]
    sess.plans[plan_id] = {"boxes": boxes, "anchor": anchor, "covered": covered}

    if not boxes:
        return {
            "plan_id": plan_id,
            "session_id": session_id,
            "outcome": "no_plan",
            "reason": (
                "No tracklet was confident enough to anchor on"
                + (", and %d anchor(s) were excluded" % len(avoid) if avoid else "")
            ),
            "anchor_key": None,
            "claimed_frames": 0,
            "rallies_covered": 0,
            "anchors_excluded": [list(a) for a in avoid],
            "elapsed_ms": elapsed_ms,
            "next": "Exclude nothing further; either accept that this video "
                    "cannot be identified automatically, or ask the player.",
        }

    return {
        "plan_id": plan_id,
        "session_id": session_id,
        "outcome": "plan",
        # a list, because this crosses JSON; feed it straight back into
        # avoid_anchors and it will be coerced to a tuple on the way in
        "anchor_key": list(anchor) if anchor else None,
        "claimed_frames": len(boxes),
        "sample_coverage_pct": round(100.0 * len(boxes) / max(1, len(sess.samples)), 1),
        "rallies_covered": covered,
        "rallies_total": len(sess.ranges) or None,
        "anchors_excluded": [list(a) for a in avoid],
        "elapsed_ms": elapsed_ms,
        "next": (
            "If rallies_covered is lower than you need, call propose_identity "
            "again with this anchor_key appended to avoid_anchors. The engine "
            "will anchor somewhere else and produce a different plan."
        ),
    }


def score_plan(session_id: str, plan_id: str) -> dict[str, Any]:
    """How many rallies a plan actually covers -- the engine's own yardstick.

    Same definition the production coverage gate uses: a rally counts once at
    least ``USABLE_RANGE_MIN_HITS`` of its frames are claimed.
    """
    sess = SESSIONS.get(session_id)
    if sess is None:
        return {"error": "unknown session_id"}
    plan = sess.plans.get(plan_id)
    if plan is None:
        return {"error": "unknown plan_id"}
    if not sess.ranges:
        return {"error": "session has no rallies to score against"}

    boxes = _int_keys(plan["boxes"])
    covered = usable_range_count(boxes, sess.ranges, sess.fps, 1)
    return {
        "plan_id": plan_id,
        "rallies_covered": covered,
        "rallies_total": len(sess.ranges),
        "coverage_pct": round(100.0 * covered / max(1, len(sess.ranges)), 1),
        "claimed_frames": len(boxes),
    }


def compare_plans(session_id: str) -> dict[str, Any]:
    """Every plan proposed so far, ranked. The search, laid out."""
    sess = SESSIONS.get(session_id)
    if sess is None:
        return {"error": "unknown session_id"}

    rows = [
        {
            "plan_id": pid,
            "anchor_key": list(p["anchor"]) if p["anchor"] else None,
            "claimed_frames": len(p["boxes"]),
            "rallies_covered": p["covered"],
        }
        for pid, p in sess.plans.items()
    ]
    rows.sort(key=lambda r: (r["rallies_covered"] or 0, r["claimed_frames"]),
              reverse=True)
    return {
        "session_id": session_id,
        "plans_tried": len(rows),
        "ranked": rows,
        "best": rows[0] if rows else None,
    }


def explain_difference(
    target_sig: dict,
    other_sigs: list,
    keep: int = 4,
    floor: float = 0.02,
) -> dict[str, Any]:
    """Which body regions actually separate these two people.

    This is what turns "I think it is this person" into something a human can
    check -- and it is what a request for human approval should show alongside
    the question.

    Two states mean the comparison found nothing, and both are reported as
    degraded because an identity decision resting on either is weak:

    - ``other_sigs`` was empty or shared no regions, so the engine returned its
      fixed torso/lower/feet weights (measured: ``{'torso': 1.0, 'lower': 1.0,
      'feet': 0.35}`` with no evidence at all).
    - The appearances differ, but by less than ``floor``. Measured on flat
      synthetic signatures: identical gives a largest gap of 0.0, one hue step
      apart gives 0.0048, and clearly different people give 0.3865. An entry
      still comes back in the first two cases, so the presence of evidence is
      not by itself a sign that anything was distinguished.
    """
    lock = engine()
    weights, evidence = lock.scan_differences(
        target_sig, other_sigs, keep=keep, floor=floor
    )
    weights = dict(weights)
    evidence = [dict(e) for e in evidence]

    gaps = [e.get("gap", 0.0) for e in evidence]
    max_gap = max(gaps) if gaps else 0.0
    fell_back = bool(FALLBACK_BANDS & set(weights))
    degraded = fell_back or max_gap < floor

    return {
        "weights": weights,
        "evidence": evidence,
        "regions_used": len(evidence),
        "largest_gap": round(max_gap, 4),
        "floor": floor,
        "degraded_to_defaults": degraded,
        "degraded_because": (
            "no comparable appearance was supplied, so fixed body-band weights "
            "were used" if fell_back else
            "the largest difference found (%.4f) is below the floor (%.2f), so "
            "these two appearances are not meaningfully distinguishable"
            % (max_gap, floor) if degraded else None
        ),
        "note": (
            "Treat an identity decision made in this state as weak: the "
            "engine did not find a region that separates these two people."
            if degraded else
            "Each entry is a body region and how far apart the two appearances "
            "are there. These are the regions the identity decision rests on."
        ),
    }
