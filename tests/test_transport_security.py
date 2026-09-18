# -*- coding: utf-8 -*-
"""The protection that switches itself off when you deploy.

The MCP SDK enables DNS rebinding protection automatically -- but only when the
bind address is loopback. A container binds 0.0.0.0, so the protection is
present during development and absent in production, with nothing in the log to
say so. Measured against this server, same build, same code path:

    bound to 127.0.0.1, Host: attacker.example.com  ->  421
    bound to 0.0.0.0,   Host: attacker.example.com  ->  200

These tests pin the behaviour this repository chose instead: an explicit
allowlist is honoured wherever it is bound, and a public bind without one says
so on stderr rather than passing quietly.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp.server import _env_list, _transport_security  # noqa: E402


# --------------------------------------------------------------------------
# The allowlist
# --------------------------------------------------------------------------

def test_an_allowlist_turns_protection_on_even_on_a_public_bind():
    s = _transport_security("0.0.0.0", ["abc.example.com"], [])
    assert s is not None
    assert s.enable_dns_rebinding_protection is True
    assert s.allowed_hosts == ["abc.example.com"]


def test_origins_alone_are_enough_to_turn_it_on():
    s = _transport_security("0.0.0.0", [], ["https://abc.example.com"])
    assert s is not None
    assert s.allowed_origins == ["https://abc.example.com"]


# --------------------------------------------------------------------------
# The silence this file exists to break
# --------------------------------------------------------------------------

def test_a_public_bind_without_an_allowlist_warns(capsys):
    assert _transport_security("0.0.0.0", [], []) is None
    err = capsys.readouterr().err
    assert "WARNING" in err
    # the warning has to name the consequence, not just the setting
    assert "any Host header is accepted" in err
    # and it has to say what to do about it
    assert "--allowed-host" in err


def test_loopback_without_an_allowlist_is_quiet():
    """The SDK already protects loopback; warning there would be noise."""
    for host in ("127.0.0.1", "localhost", "::1"):
        assert _transport_security(host, [], []) is None


def test_loopback_is_quiet_on_stderr(capsys):
    _transport_security("127.0.0.1", [], [])
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# Environment parsing
# --------------------------------------------------------------------------

def test_env_list_splits_and_strips(monkeypatch):
    monkeypatch.setenv("PROBE_HOSTS", " a.example.com , b.example.com ")
    assert _env_list("PROBE_HOSTS") == ["a.example.com", "b.example.com"]


def test_env_list_of_an_unset_or_empty_var_is_empty(monkeypatch):
    monkeypatch.delenv("PROBE_HOSTS", raising=False)
    assert _env_list("PROBE_HOSTS") == []
    monkeypatch.setenv("PROBE_HOSTS", "  ,  ,")
    assert _env_list("PROBE_HOSTS") == []
