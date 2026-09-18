# -*- coding: utf-8 -*-
"""ABC Vision MCP server.

Exposes a production badminton video-analysis engine as MCP tools over
Streamable HTTP, and records at every branch point how a measured visual result
changed what the system did next.

Transport note: the Alexa+ track requires "a self-hosted MCP server (spec
2025-11-25 or later, Streamable HTTP)". The installed SDK advertises protocol
version 2026-07-28, which satisfies it; ``protocol_info`` reports the version
actually in use rather than the one this comment claims.

Run:
    python -m abc_vision_mcp.server                      # stdio, for local clients
    python -m abc_vision_mcp.server --http               # Streamable HTTP on :8931
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import LATEST_PROTOCOL_VERSION

from . import identity, jobs, stats
from .trace import DecisionTrace

INSTRUCTIONS = """\
Tools for analysing badminton match video and for inspecting how often the
analysis refuses to answer.

Read this before using the tools: this engine is built to decline. It withholds
a skill level when the evidence is thin, and it records why. When a tool returns
a refusal, that is a result, not an error -- do not retry it with the same input
hoping for a different answer, and do not present a withheld level as if it were
low. If you need to know how often this happens and for what reasons, call
production_outcomes first; it reports measured rates from 1,117 real jobs.

Percentages from this engine are ambiguous without a denominator. Tools here
always return both "of all jobs" and "of jobs that produced a report". Quote the
one you mean, by name.
"""

server = MCPServer(
    name="abc-vision",
    title="ABC Vision — badminton analysis with a refusal to guess",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)


# --------------------------------------------------------------------------
# Production evidence -- no engine or video required
# --------------------------------------------------------------------------

@server.tool(
    title="Production outcomes",
    description=(
        "How often the analysis published a skill level and how often it "
        "declined, measured over real jobs run between 2026-09-06 and "
        "2026-09-17. Returns both denominators (all jobs, and jobs that "
        "produced a report) because the two give different percentages and "
        "quoting one without naming it is misleading. Optional 'since' "
        "(YYYY-MM-DD) narrows the window."
    ),
)
def production_outcomes(since: str | None = None) -> dict[str, Any]:
    return stats.outcome_breakdown(since=since)


@server.tool(
    title="Why the analysis declined",
    description=(
        "The failure taxonomy from production: when the engine refused to "
        "publish a skill level, what the reason was, ranked by frequency. "
        "Use this to explain a refusal in terms of what was actually missing "
        "-- tracking time, usable rallies, a stable camera -- rather than "
        "guessing."
    ),
)
def decline_reasons(since: str | None = None) -> dict[str, Any]:
    return stats.decline_reasons(since=since)


@server.tool(
    title="Human-approval drop-off",
    description=(
        "Jobs where the vision could not identify the player on its own, so "
        "the system asked the player to confirm -- and the player never came "
        "back before the request expired. This is the perception-decision-"
        "action loop's human-approval branch, measured where it fails. Note "
        "that half of these uploads are five minutes or longer, i.e. the "
        "length that most often succeeds: the failure is in the hand-off, not "
        "in the vision."
    ),
)
def human_approval_dropoff() -> dict[str, Any]:
    return stats.human_approval_dropoff()


# --------------------------------------------------------------------------
# Rally detection: the OpenCV 5 pass, as a job
# --------------------------------------------------------------------------

@server.tool(
    title="Start rally detection",
    description=(
        "Run the OpenCV 5 pass that finds rallies in a match video. This is "
        "submit-and-poll, not a single call: the scan runs at roughly 0.8x "
        "real time, so a ten-minute clip is about eight minutes of work.\n\n"
        "The response tells you how long it will take before it starts. There "
        "is no way to cancel a scan once running, so pick max_minutes "
        "deliberately rather than defaulting to the whole video.\n\n"
        "Non-video files are refused here. The engine itself would accept one "
        "and return an empty rally list with invented metadata, which is "
        "indistinguishable from a real video containing no rallies."
    ),
)
def scan_submit(
    video_path: str,
    max_minutes: float = 10.0,
    airspace: list | None = None,
) -> dict[str, Any]:
    return jobs.scan_submit(video_path, max_minutes=max_minutes,
                            airspace=airspace)


@server.tool(
    title="Check a scan",
    description=(
        "Progress of a submitted scan, with an estimate of the time left. "
        "Poll this rather than blocking."
    ),
)
def scan_status(job_id: str) -> dict[str, Any]:
    return jobs.scan_status(job_id)


@server.tool(
    title="Fetch scan results",
    description=(
        "The rallies a finished scan found, ranked. Each carries its timing, "
        "shot count, and the confidence figures behind it.\n\n"
        "Per-frame shuttle tracks are omitted unless include_track is true: "
        "they run to ~1,500 points per rally and ten rallies of them exceed "
        "150 KB, which would crowd out everything else you are reading.\n\n"
        "Rallies below the engine's length and density floors are dropped "
        "before they reach you. An empty result therefore does not prove the "
        "video had no rallies."
    ),
)
def scan_result(job_id: str, include_track: bool = False,
                limit: int = 10) -> dict[str, Any]:
    return jobs.scan_result(job_id, include_track=include_track, limit=limit)


# --------------------------------------------------------------------------
# Identity: the re-planning loop, one tool call per step
# --------------------------------------------------------------------------
#
# These four tools exist as four tools on purpose. The engine can run this loop
# internally, but then the search is invisible and the only evidence that vision
# changed the outcome is a claim in a document. Split like this, the loop runs in
# the MCP message flow: propose a plan, see which anchor it rested on and how
# much it covered, rule that anchor out, propose again, compare. The transcript
# is the evidence.

@server.tool(
    title="Open an identity session",
    description=(
        "Register one video's detections and appearance signatures, and get a "
        "session handle. Samples are held here rather than passed on every "
        "call -- a production run carries a median of 561 of them, which would "
        "bury the decisions that are the interesting part. 'ranges' are the "
        "rallies, as [start_seconds, duration_seconds] pairs."
    ),
)
def open_identity_session(
    samples: list,
    fps: float,
    enrolled_sig: dict,
    enrolled_height: float | None = None,
    rival_sigs: list | None = None,
    ranges: list | None = None,
) -> dict[str, Any]:
    return identity.open_session(
        samples=samples, fps=fps, enrolled_sig=enrolled_sig,
        enrolled_height=enrolled_height, rival_sigs=rival_sigs, ranges=ranges,
    )


@server.tool(
    title="Propose who the subject is",
    description=(
        "One plan for which detection is the subject in each sample. Returns "
        "the anchor the plan rests on, how many frames it claims, and how many "
        "rallies it covers.\n\n"
        "To search rather than accept: if the coverage is too low, call this "
        "again with the returned anchor_key appended to avoid_anchors. The "
        "engine will anchor somewhere else and produce a materially different "
        "plan. That second call is the point -- a visual result changed which "
        "plan gets tried next.\n\n"
        "An outcome of 'no_plan' means no tracklet was confident enough to "
        "anchor on. That is an answer, not a failure: do not retry it "
        "unchanged."
    ),
)
def propose_identity(
    session_id: str,
    avoid_anchors: list | None = None,
    anchor_pref: str | None = None,
) -> dict[str, Any]:
    return identity.propose_identity(
        session_id, avoid_anchors=avoid_anchors, anchor_pref=anchor_pref
    )


@server.tool(
    title="Score a plan's rally coverage",
    description=(
        "How many rallies a proposed plan actually covers, using the same "
        "definition the production coverage gate applies: a rally counts once "
        "at least four of its sampled frames are claimed. Use this to decide "
        "whether a plan is good enough or whether to exclude its anchor and "
        "look again."
    ),
)
def score_identity_plan(session_id: str, plan_id: str) -> dict[str, Any]:
    return identity.score_plan(session_id, plan_id)


@server.tool(
    title="Compare the plans tried so far",
    description=(
        "Every plan proposed in this session, ranked by rallies covered. This "
        "is the search laid out: which anchors were tried, what each one was "
        "worth, and which won."
    ),
)
def compare_identity_plans(session_id: str) -> dict[str, Any]:
    return identity.compare_plans(session_id)


@server.tool(
    title="Explain what separates two people",
    description=(
        "Which body regions actually distinguish the subject from someone "
        "else, and by how much. Show this to a person when asking them to "
        "confirm an identity -- it turns 'I think it is you' into something "
        "they can check.\n\n"
        "Read 'degraded_to_defaults' before quoting the result: when it is "
        "true the engine found nothing that separates the two appearances, and "
        "any identity decision resting on it is weak."
    ),
)
def explain_identity_difference(
    target_sig: dict,
    other_sigs: list,
    keep: int = 4,
) -> dict[str, Any]:
    return identity.explain_difference(target_sig, other_sigs, keep=keep)


# --------------------------------------------------------------------------
# Introspection
# --------------------------------------------------------------------------

@server.tool(
    title="Protocol and build info",
    description=(
        "The MCP protocol version and library versions this server is "
        "actually running, read at call time. Useful for verifying a "
        "deployment matches what a report claims rather than trusting the "
        "report."
    ),
)
def protocol_info() -> dict[str, Any]:
    import importlib.metadata as md

    def ver(pkg: str) -> str:
        try:
            return md.version(pkg)
        except Exception:  # noqa: BLE001
            return "not installed"

    # Two different version numbers live in this SDK and conflating them
    # overstates what the server does. `initialize` negotiates a *handshake*
    # version, and that is the one the Alexa+ track's "spec 2025-11-25 or
    # later" refers to. LATEST_PROTOCOL_VERSION is the transport revision and
    # is always the higher number, which makes it the tempting one to quote.
    # Our own conformance checker caught this being reported as the protocol
    # version; see docs/CORRECTIONS.md.
    try:
        from mcp.client.session import (
            HANDSHAKE_PROTOCOL_VERSIONS,
            LATEST_HANDSHAKE_VERSION,
        )
        handshake = LATEST_HANDSHAKE_VERSION
        supported = list(HANDSHAKE_PROTOCOL_VERSIONS)
    except Exception:  # noqa: BLE001
        handshake, supported = "unknown", []

    info: dict[str, Any] = {
        "negotiated_protocol_version": handshake,
        "supported_protocol_versions": supported,
        "transport_revision": LATEST_PROTOCOL_VERSION,
        "note": (
            "negotiated_protocol_version is what initialize agrees with a "
            "client, and is the figure to quote. transport_revision is a "
            "different, higher number and is not the protocol version."
        ),
        "mcp_sdk": ver("mcp"),
        "server_name": server.name,
        "server_version": server.version,
    }
    try:
        import cv2

        info["opencv_version"] = cv2.__version__
        info["opencv_module"] = cv2.__file__
    except Exception as exc:  # noqa: BLE001
        # The vision tools are not wired up yet in every deployment; say so
        # rather than letting the absence look like a passing check.
        info["opencv_version"] = "unavailable: %s" % type(exc).__name__
    return info


@server.tool(
    title="Start a decision trace",
    description=(
        "Open a trace for one analysis run. Every subsequent branch point is "
        "recorded with the evidence that drove it and the alternatives that "
        "were not taken, so the chain can be audited afterwards. Returns the "
        "run id to pass to later calls."
    ),
)
def start_trace() -> dict[str, Any]:
    trace = DecisionTrace()
    _TRACES[trace.run_id] = trace
    return {"run_id": trace.run_id, "started_at": trace.started_at}


@server.tool(
    title="Read a decision trace",
    description=(
        "The recorded decisions for a run. 'branching_decisions' counts only "
        "branch points that had an alternative -- a decision with no "
        "alternative did not branch on anything and is not evidence that the "
        "vision changed the outcome."
    ),
)
def read_trace(run_id: str) -> dict[str, Any]:
    trace = _TRACES.get(run_id)
    if trace is None:
        return {"error": "unknown run_id", "run_id": run_id}
    return trace.to_dict()


# In-process trace store. Adequate for a single-worker deployment; a shared
# store is needed before this runs behind more than one process.
_TRACES: dict[str, DecisionTrace] = {}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ABC Vision MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve MCP over Streamable HTTP instead of stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8931)
    parser.add_argument(
        "--path",
        default="/mcp",
        help="URL path the Streamable HTTP endpoint is served on",
    )
    args = parser.parse_args()

    if args.http:
        # host and port are keyword arguments to run(), which forwards them to
        # run_streamable_http_async. They are NOT attributes of server.settings
        # -- assigning there is silently accepted and has no effect, so the
        # server would quietly ignore --host and --port.
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
