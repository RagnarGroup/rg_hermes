"""What /mcp and ``GET /api/mcp`` report for the active profile: every configured MCP server with
its cached runtime status (never connects) plus the ``conectar_app`` apps (``pantera.mcp_permitidos``)
and whether the profile already holds OAuth tokens for each. Call inside the profile's scope."""

from __future__ import annotations

import logging
from typing import Any

from agent.i18n import t

logger = logging.getLogger(__name__)

_STATUS_ICONS = {"connected": "🟢", "lazy": "🟢", "connecting": "🟡", "failed": "🔴",
                 "disabled": "⚪", "configured": "⚪"}


def mcp_summary() -> dict[str, Any]:
    from tools.mcp_tool_discovery import get_mcp_status
    try:
        servers = get_mcp_status()
    except Exception:
        logger.exception("mcp summary: status read failed")
        servers = []
    apps: list[dict[str, Any]] = []
    try:
        from tools.pantera_conexiones import _conectado, _pantera_config
        permitidos, _redirect = _pantera_config()
        apps = [{"app": name, "conectada": _conectado(name)} for name in sorted(permitidos)]
    except Exception:
        logger.exception("mcp summary: conectar_app state read failed")
    return {"servers": [{key: entry[key] for key in ("name", "transport", "status", "tools", "error") if key in entry}
                        for entry in servers],
            "apps": apps}


def mcp_summary_lines(summary: dict[str, Any]) -> list[str]:
    lines = [t("gateway.mcp_list.header")]
    if summary["servers"]:
        for server in summary["servers"]:
            icon = _STATUS_ICONS.get(server["status"], "⚪")
            status = t(f"gateway.mcp_list.status_{server['status']}")
            tools = t("gateway.mcp_list.tools", count=server["tools"]) if server.get("tools") else ""
            lines.append(f"{icon} {server['name']} — {status}{tools}")
    else:
        lines.append(t("gateway.mcp_list.none"))
    if summary["apps"]:
        lines.append(t("gateway.mcp_list.apps_header"))
        for app in summary["apps"]:
            key = "gateway.mcp_list.app_connected" if app["conectada"] else "gateway.mcp_list.app_missing"
            lines.append(t(key, app=app["app"]))
        lines.append(t("gateway.mcp_list.apps_hint"))
    return lines
