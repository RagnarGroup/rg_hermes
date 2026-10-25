"""/mcp, GET /api/commands and GET /api/mcp."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import Platform, PlatformConfig
from gateway.mcp_summary import mcp_summary, mcp_summary_lines
from gateway.platforms.api_server import APIServerAdapter
from tests.gateway.test_slash_access_dispatch import _make_event, _make_runner, _make_source

_STATUS = [
    {"name": "google", "transport": "http", "tools": 42, "connected": True, "disabled": False, "status": "connected"},
    {"name": "canva", "transport": "http", "tools": 0, "connected": False, "disabled": False,
     "status": "failed", "error": "401"},
]


def _patched_summary():
    return (patch("tools.mcp_tool_discovery.get_mcp_status", return_value=_STATUS),
            patch("tools.pantera_conexiones._pantera_config",
                  return_value=({"google": {"url": "https://g"}, "canva": {"url": "https://c"}}, "")),
            patch("tools.pantera_conexiones._conectado", side_effect=lambda name: name == "google"))


def test_summary_merges_servers_and_apps():
    a, b, c = _patched_summary()
    with a, b, c:
        summary = mcp_summary()
    assert summary["servers"][0] == {"name": "google", "transport": "http", "status": "connected", "tools": 42}
    assert summary["servers"][1]["error"] == "401"
    assert summary["apps"] == [{"app": "canva", "conectada": False}, {"app": "google", "conectada": True}]
    text = "\n".join(mcp_summary_lines(summary))
    assert "google" in text and "42" in text and "canva" in text


def test_summary_without_servers_or_apps():
    with patch("tools.mcp_tool_discovery.get_mcp_status", return_value=[]), \
            patch("tools.pantera_conexiones._pantera_config", return_value=({}, "")):
        summary = mcp_summary()
    assert summary == {"servers": [], "apps": []}
    assert len(mcp_summary_lines(summary)) == 2


@pytest.mark.asyncio
async def test_mcp_command_is_open_to_gated_users():
    runner = _make_runner(platform=Platform.WHATSAPP, platform_extra={"allow_admin_from": ["111"]})
    a, b, c = _patched_summary()
    with a, b, c:
        result = await runner._handle_message(
            _make_event("/mcp", _make_source(platform=Platform.WHATSAPP, user_id="999")))
    assert "google" in result


def _app(extra):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "k", **extra}))
    app = web.Application()
    app.router.add_get("/api/commands", adapter._handle_commands)
    app.router.add_get("/api/mcp", adapter._handle_mcp)
    return app


@pytest.mark.asyncio
async def test_commands_endpoint_scopes():
    async with TestClient(TestServer(_app({"user_allowed_commands": ["new"]}))) as cli:
        assert (await cli.get("/api/commands")).status == 401
        headers = {"Authorization": "Bearer k"}
        user = await (await cli.get("/api/commands", headers=headers)).json()
        names = {entry["name"] for entry in user["data"]}
        assert {"new", "cmds", "mcp", "help"} <= names and "restart" not in names
        admin = await (await cli.get("/api/commands?scope=admin", headers=headers)).json()
        assert "restart" in {entry["name"] for entry in admin["data"]}
        assert (await cli.get("/api/commands?scope=root", headers=headers)).status == 400


@pytest.mark.asyncio
async def test_mcp_endpoint():
    a, b, c = _patched_summary()
    with a, b, c:
        async with TestClient(TestServer(_app({}))) as cli:
            data = await (await cli.get("/api/mcp", headers={"Authorization": "Bearer k"})).json()
    assert data["servers"][0]["name"] == "google"
    assert data["apps"][1] == {"app": "google", "conectada": True}
