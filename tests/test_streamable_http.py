# -*- coding: utf-8 -*-
"""End-to-end proof that the Streamable HTTP transport actually serves MCP.

The Alexa+ track requires "a self-hosted MCP server (spec 2025-11-25 or later,
Streamable HTTP)". Registering tools in-process proves none of that: it does not
show the transport works, and it does not show which protocol version is
negotiated on the wire.

So this test starts the real server in a subprocess, connects a real client over
Streamable HTTP, and asserts against what came back across the socket. It is the
one test that, if it passes, means the submission requirement is met.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

anyio = pytest.importorskip("anyio")

MIN_PROTOCOL = "2025-11-25"  # the floor the Alexa+ track sets


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_listening(port: int, proc: subprocess.Popen, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() if proc.stdout else b"") or b""
            raise RuntimeError(
                "server exited early (code %s):\n%s"
                % (proc.returncode, out.decode("utf-8", "replace")[-2000:])
            )
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError("server did not start listening on port %d" % port)


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [sys.executable, "-m", "abc_vision_mcp.server",
         "--http", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_until_listening(port, proc)
        yield "http://127.0.0.1:%d/mcp" % port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _ask(url, fn):
    """Run ``fn(session)`` against a live server and return its result.

    Deliberately not an async generator: yielding the session out of the
    ``async with`` blocks means the transport's task group is torn down in a
    different task than it was entered in, and anyio rejects that with
    "Attempted to exit cancel scope in a different task". Everything the caller
    needs must happen inside the one scope, so the callable comes in rather than
    the session going out.
    """

    async def run():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    return anyio.run(run)


def test_server_serves_mcp_over_streamable_http(live_server):
    """The transport works and the tools are reachable across the wire."""

    async def listing(session):
        result = await session.list_tools()
        return {t.name for t in result.tools}

    names = _ask(live_server, listing)
    assert "production_outcomes" in names
    assert "protocol_info" in names
    assert len(names) >= 6


def test_negotiated_protocol_meets_the_alexa_floor(live_server):
    """Not just "a version" -- one at or after the required 2025-11-25."""

    async def version(session):
        return session.protocol_version

    negotiated = _ask(live_server, version)
    assert negotiated is not None
    # ISO dates compare correctly as strings
    assert str(negotiated) >= MIN_PROTOCOL, (
        "negotiated %s, which is older than the required %s"
        % (negotiated, MIN_PROTOCOL)
    )


def test_a_tool_call_returns_real_production_figures(live_server):
    """Round-trips an actual call, not just the tool listing."""

    async def call(session):
        return await session.call_tool("production_outcomes",
                                       {"since": "2026-09-15"})

    result = _ask(live_server, call)
    assert not result.is_error

    payload = result.structured_content
    assert payload is not None, "tool returned no structured content"
    assert payload["denominators"]["all_jobs"] == 244
    assert payload["denominators"]["jobs_that_produced_a_report"] == 215
    assert payload["headline"]["published_a_level"] == 120


def test_server_reports_opencv_5_over_the_wire(live_server):
    """OpenCV 5 is a hard entry requirement; prove it from the running server."""

    async def call(session):
        return await session.call_tool("protocol_info", {})

    result = _ask(live_server, call)
    assert not result.is_error
    info = result.structured_content
    assert info["opencv_version"].startswith("5."), (
        "server is not running OpenCV 5: %r" % info["opencv_version"]
    )
