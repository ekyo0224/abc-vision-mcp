# -*- coding: utf-8 -*-
"""Decision trace: the evidence that vision output changed what happened next.

This module exists because of one sentence in the OpenCV AI Competition 2026 rules:

    To qualify, image or video results must influence a subsequent plan, tool
    call, action, or request for human approval. A chatbot that only explains a
    fixed vision result is not enough -- the visual evidence must change what
    the system does next.

So a log of "we called scan(), then we called lock_subject()" proves nothing: a
fixed script produces the same log. What proves the claim is a record where, at
a named branch point, a *measured* value decided which of several possible next
actions ran, and the alternatives that were not taken are written down next to
the one that was.

That is what a Decision is here. Every Decision carries:

  - the evidence: which tool measured it, and the actual number or label
  - the branch that was taken, and the branches that were not
  - the rule that mapped evidence to branch, in a form a judge can re-apply

A ToolCall records what ran. A Decision records why the next thing ran. Only
Decisions are evidence for the agentic claim; ToolCalls are the supporting
detail that lets someone re-derive them.

Privacy: this trace is written to be handed to competition judges. Video paths,
customer names and subject identifiers must never reach it -- see ``redact``.
The project's own red line is that no customer or child imagery, and nothing
that identifies a player, leaves the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

_SENSITIVE_KEYS = frozenset({
    "video", "video_path", "path", "file", "filename", "src", "dst",
    "subject", "subject_id", "subject_hint", "player", "name", "nickname",
    "device_id", "email", "token", "key", "secret", "url",
})


def _fingerprint(value: str) -> str:
    """A stable, non-reversible handle for a path or identifier.

    Judges need to see that two tool calls acted on the same video without
    learning which video it was. A truncated digest does that: identical inputs
    produce identical handles, and nothing recovers the original.
    """
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    return "sha256:" + digest[:12]


def redact(value: Any, _key: str | None = None, _depth: int = 0) -> Any:
    """Strip anything that could identify a person, a video, or a machine.

    Applied to every input and output before it enters the trace. Keys are
    matched by name, so a new field called ``subject_name`` is redacted the day
    it appears, without this module being updated.
    """
    if _depth > 6:
        return "<truncated:depth>"

    if _key is not None and _key.lower() in _SENSITIVE_KEYS:
        if isinstance(value, str) and value:
            return _fingerprint(value)
        if value is None:
            return None
        return "<redacted>"

    if isinstance(value, dict):
        return {k: redact(v, k, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 50:
            head = [redact(v, _key, _depth + 1) for v in list(value)[:50]]
            return head + ["<truncated:%d more>" % (len(value) - 50)]
        return [redact(v, _key, _depth + 1) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "<truncated>"
        return value

    # numpy arrays, custom objects, sets -- summarise rather than serialise
    shape = getattr(value, "shape", None)
    if shape is not None:
        return {"_type": type(value).__name__, "shape": list(shape)}
    return {"_type": type(value).__name__}


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

@dataclass
class ToolCall:
    """One tool invocation. Supporting detail, not evidence by itself."""

    seq: int
    tool: str
    args: dict[str, Any]
    result_summary: Any
    started_at: float
    duration_ms: float
    ok: bool
    error: str | None = None
    kind: str = "tool_call"


@dataclass
class Decision:
    """A branch point where measured evidence selected the next action.

    This is the unit the competition rules care about. ``evidence_value`` must
    be something the named tool actually produced -- not a restatement of the
    branch that was taken, or the record proves nothing.
    """

    seq: int
    node: str
    """Stable name of the branch point, e.g. COURT_GATE, IDENTITY_RETRY."""

    evidence_from: str
    """Which tool produced the evidence. Must match a ToolCall.tool above."""

    evidence: dict[str, Any]
    """The measured values that drove the branch, redacted."""

    rule: str
    """The mapping from evidence to branch, stated so a judge can re-apply it."""

    chose: str
    """The branch taken."""

    alternatives: list[str]
    """Branches not taken. An empty list means this was not really a decision."""

    consequence: str
    """What actually happens next because of this choice."""

    human_approval_requested: bool = False
    """True when the chosen branch hands control to a person.

    The rules list ``request for human approval`` as a qualifying action, so
    these branches are called out rather than buried in ``chose``.
    """

    at: float = field(default_factory=time.time)
    kind: str = "decision"


# --------------------------------------------------------------------------
# Recorder
# --------------------------------------------------------------------------

class DecisionTrace:
    """Collects one analysis run's tool calls and decisions.

    Fail-open by construction: recording must never be the reason an analysis
    fails, so every method swallows its own errors. A trace that is missing a
    line is a weaker submission; an analysis that crashed because of logging is
    a broken product.
    """

    def __init__(self, run_id: str | None = None, subject: str | None = None) -> None:
        self.run_id = run_id or ("run_" + uuid.uuid4().hex[:16])
        self.subject_handle = _fingerprint(subject) if subject else None
        self.started_at = time.time()
        self.records: list[dict[str, Any]] = []
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def tool_call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        result: Any = None,
        started_at: float | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        try:
            now = time.time()
            start = started_at if started_at is not None else now
            rec = ToolCall(
                seq=self._next_seq(),
                tool=tool,
                args=redact(args or {}),
                result_summary=redact(result),
                started_at=start,
                duration_ms=round((now - start) * 1000.0, 2),
                ok=ok,
                error=(str(error)[:400] if error else None),
            )
            self.records.append(asdict(rec))
        except Exception:  # noqa: BLE001 -- see class docstring
            pass

    def decision(
        self,
        node: str,
        evidence_from: str,
        evidence: dict[str, Any],
        rule: str,
        chose: str,
        alternatives: Iterable[str],
        consequence: str,
        human_approval_requested: bool = False,
    ) -> None:
        try:
            rec = Decision(
                seq=self._next_seq(),
                node=node,
                evidence_from=evidence_from,
                evidence=redact(evidence),
                rule=rule,
                chose=chose,
                alternatives=list(alternatives),
                consequence=consequence,
                human_approval_requested=human_approval_requested,
            )
            self.records.append(asdict(rec))
        except Exception:  # noqa: BLE001
            pass

    # -- views -------------------------------------------------------------

    def decisions(self) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("kind") == "decision"]

    def summary(self) -> dict[str, Any]:
        """The shape a judge reads first.

        ``branching_decisions`` is the number that matters: decisions with at
        least one alternative. A run where every decision had zero alternatives
        did not branch on anything, and should not be presented as agentic.
        """
        decs = self.decisions()
        calls = [r for r in self.records if r.get("kind") == "tool_call"]
        return {
            "run_id": self.run_id,
            "subject_handle": self.subject_handle,
            "started_at": self.started_at,
            "elapsed_sec": round(time.time() - self.started_at, 2),
            "tool_calls": len(calls),
            "tool_calls_failed": sum(1 for c in calls if not c.get("ok")),
            "decisions": len(decs),
            "branching_decisions": sum(1 for d in decs if d.get("alternatives")),
            "human_approval_requests": sum(
                1 for d in decs if d.get("human_approval_requested")
            ),
            "nodes_visited": [d["node"] for d in decs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "abc_vision_mcp/decision_trace/v1",
            "summary": self.summary(),
            "records": self.records,
        }

    def write(self, directory: str) -> str | None:
        """Persist as JSON. Returns the path, or None if writing failed."""
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, self.run_id + ".json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
            return path
        except Exception:  # noqa: BLE001
            return None
