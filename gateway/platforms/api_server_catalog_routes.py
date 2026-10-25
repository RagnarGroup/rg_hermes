"""``GET /api/commands`` and ``GET /api/mcp`` for :class:`APIServerAdapter` (and ``/p/<profile>/``).

``/api/commands`` is the /cmds catalog: ``?scope=user`` (default) limits it to the slash-access floor
plus this listener's ``user_allowed_commands``, ``?scope=admin`` returns every gateway command; the
caller (a trusted backend holding API_SERVER_KEY) decides which scope a person gets. ``/api/mcp`` is
the /mcp summary of the served profile. Both are read-only and never connect anything.
"""

from __future__ import annotations

import logging

from gateway.platforms.api_server_auth import _require_auth

try:
    from aiohttp import web
except ImportError:  # pragma: no cover - mirrors api_server's optional import
    web = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class CatalogRoutesMixin:
    def _request_profile_api_extra(self) -> dict:
        """``api_server`` extra of the profile this request is for. Under multiplex the default's
        adapter serves every ``/p/<profile>/`` itself, so its own ``config`` is the wrong one there;
        a served profile without a cached config or api_server block gets ``{}`` (floor only)."""
        from gateway.config import Platform
        from gateway.platforms.api_server import _api_request_profile
        profile = _api_request_profile.get()
        runner = getattr(self, "gateway_runner", None)
        if not profile or profile == (getattr(runner, "_primary_profile_name", None) or "default"):
            return getattr(self.config, "extra", None) or {}
        config = (getattr(runner, "_profile_configs", None) or {}).get(profile)
        platform_config = config.platforms.get(Platform.API_SERVER) if config is not None else None
        return (getattr(platform_config, "extra", None) or {}) if platform_config is not None else {}

    @_require_auth
    async def _handle_commands(self, request: web.Request) -> web.Response:
        from gateway.platforms.api_server import _error_response
        scope = request.query.get("scope", "user")
        if scope not in ("user", "admin"):
            return _error_response("scope must be 'user' or 'admin'", 400, err_type="invalid_request_error")
        try:
            from gateway.slash_access import _ALWAYS_ALLOWED_FOR_USERS, policy_from_extra
            from hermes_cli.commands import gateway_cmds_entries
            allowed = None
            if scope == "user":
                policy = policy_from_extra(self._request_profile_api_extra(), "dm")
                allowed = {*_ALWAYS_ALLOWED_FOR_USERS, *policy.user_allowed_commands}
            data = gateway_cmds_entries(allowed)
        except Exception:
            logger.exception("GET /api/commands failed")
            return _error_response("Failed to list commands", 500, err_type="server_error")
        return web.json_response({"object": "list", "scope": scope, "data": data})

    @_require_auth
    async def _handle_mcp(self, request: web.Request) -> web.Response:
        from gateway.platforms.api_server import _error_response
        try:
            from gateway.mcp_summary import mcp_summary
            summary = mcp_summary()
        except Exception:
            logger.exception("GET /api/mcp failed")
            return _error_response("Failed to read MCP status", 500, err_type="server_error")
        return web.json_response(summary)
