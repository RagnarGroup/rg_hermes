"""``conectar_app``: connect a remote MCP server from the profile's allowlist over chat.

Ragnar's Pantera users talk to Hermes on WhatsApp, where no connection card exists and the
loopback OAuth callback is unreachable from their phone. Each allowed server is authorized with
``oauth.redirect_uri`` set to a public relay page (``pantera.oauth_redirect_uri``): the provider
redirects there, the page hands the callback back to the chat, and ``completar`` delivers it to
the pending flow of this profile. Only remote (https) servers listed under
``pantera.mcp_permitidos`` can be connected, so a client can never install a local stdio server
that would run on the host outside its sandbox.

Config (profile ``config.yaml``)::

    pantera:
      oauth_redirect_uri: https://www.ragnargroup.app/conectar/
      mcp_permitidos:
        google: {url: https://google-mcp.ragnargroup.app/mcp}
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional
from urllib.parse import urlparse

from tools.registry import registry, tool_error

_ACCIONES = ("estado", "link", "completar")
_ESPERA_APROBACION_SEGUNDOS = 45.0


def _pantera_config() -> tuple[dict[str, dict[str, Any]], str]:
    from hermes_cli.config import load_config

    pantera = load_config().get("pantera") or {}
    permitidos = {
        str(nombre): dict(valor)
        for nombre, valor in (pantera.get("mcp_permitidos") or {}).items()
        if isinstance(valor, dict) and urlparse(str(valor.get("url") or "")).scheme == "https"
    }
    redirect = str(pantera.get("oauth_redirect_uri") or "").strip()
    return permitidos, redirect if urlparse(redirect).scheme == "https" else ""


def _hermes_home() -> str:
    from hermes_constants import get_hermes_home

    return str(get_hermes_home().expanduser().resolve(strict=False))


def _conectado(nombre: str) -> bool:
    from hermes_cli.mcp_config import _oauth_tokens_present

    return _oauth_tokens_present(nombre)


def _estado(permitidos: dict[str, dict[str, Any]]) -> str:
    return json.dumps({"apps": [{"app": n, "conectada": _conectado(n)} for n in sorted(permitidos)]})


def _link(app: str, permitidos: dict[str, dict[str, Any]], redirect: str, session_id: Optional[str]) -> str:
    from hermes_constants import hermes_home_key
    from tools.connectors import mcp_oauth
    from tools.connectors.gateway.config import operation_session_key
    from tools.connectors.mcp import _LATE_ATTEMPTS

    cfg = {"url": permitidos[app]["url"], "auth": "oauth", "oauth": {"redirect_uri": redirect}}
    attempt = mcp_oauth.start(app, cfg=cfg)
    if not attempt.auth_url:
        return json.dumps({"app": app, "conectada": True})
    _LATE_ATTEMPTS.setdefault((hermes_home_key(), operation_session_key(session_id)), {})[app] = attempt
    return json.dumps({
        "app": app,
        "link": attempt.auth_url,
        "instrucciones": (
            "Manda este link al usuario. Al aprobar, la pagina de Ragnar le muestra un boton para "
            "devolverte la conexion por este chat; cuando llegue ese mensaje, llama a conectar_app "
            "con accion 'completar' y la URL recibida. El link vence en 5 minutos."
        ),
    })


def _completar(url: str) -> str:
    from tools.connectors import mcp_oauth

    query = urlparse(url).query if "://" in url else url.lstrip("?")
    app = mcp_oauth.deliver_relayed_callback(_hermes_home(), query)
    if app is None:
        return tool_error("Esa URL no corresponde a ninguna conexion pendiente de este usuario (o ya vencio). Pide un link nuevo.")
    with mcp_oauth._COMMIT_GUARD:
        flow = mcp_oauth._ACTIVE.get((_hermes_home(), app))
    deadline = time.time() + _ESPERA_APROBACION_SEGUNDOS
    while flow is not None and time.time() < deadline:
        snapshot = flow.snapshot()
        if snapshot.get("status") == "approved":
            return json.dumps({"app": app, "conectada": True,
                               "nota": "Las herramientas de la app quedan disponibles desde el proximo mensaje."})
        if snapshot.get("status") == "error":
            return tool_error(f"La conexion de {app} fallo: {snapshot.get('error') or 'error desconocido'}")
        time.sleep(0.5)
    return json.dumps({"app": app, "conectada": False, "nota": "La aprobacion sigue en curso; revisa con 'estado' en unos segundos."})


def conectar_app(args: dict[str, Any], *, session_id: Optional[str] = None) -> str:
    accion = str(args.get("accion") or "estado").strip().lower()
    if accion not in _ACCIONES:
        return tool_error(f"accion debe ser una de: {', '.join(_ACCIONES)}")
    permitidos, redirect = _pantera_config()
    if accion == "estado":
        return _estado(permitidos)
    if accion == "completar":
        url = str(args.get("url") or "").strip()
        if not url:
            return tool_error("completar necesita 'url': el link que devolvio el usuario.")
        return _completar(url)
    app = str(args.get("app") or "").strip().lower()
    if app not in permitidos:
        return tool_error(f"'{app}' no esta permitida. Apps disponibles: {', '.join(sorted(permitidos)) or 'ninguna'}.")
    if not redirect:
        return tool_error("Falta pantera.oauth_redirect_uri (https) en la configuracion.")
    try:
        return _link(app, permitidos, redirect, session_id)
    except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
        return tool_error(f"No se pudo iniciar la conexion de {app}: {exc}")


CONECTAR_APP_SCHEMA = {
    "name": "conectar_app",
    "description": (
        "Conecta las apps del usuario (por ejemplo su cuenta de Google: Gmail, Calendar, Drive, Docs, "
        "Sheets) por chat. 'estado' lista las apps permitidas y si ya estan conectadas. 'link' inicia "
        "la conexion de una app y devuelve un link para mandarle al usuario. 'completar' recibe la URL "
        "que el usuario devuelve al chat despues de aprobar (contiene code= y state=) y termina la "
        "conexion. Nunca abras el link vos mismo ni pidas contrasenas."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "accion": {"type": "string", "enum": list(_ACCIONES), "description": "Por defecto 'estado'."},
            "app": {"type": "string", "description": "link: nombre de la app permitida (ver 'estado')."},
            "url": {"type": "string", "description": "completar: la URL que devolvio el usuario."},
        },
        "required": [],
    },
}


registry.register(
    name="conectar_app",
    toolset="pantera_conexiones",
    schema=CONECTAR_APP_SCHEMA,
    handler=lambda args, **kw: conectar_app(args, session_id=kw.get("session_id")),
    check_fn=lambda: bool(_pantera_config()[0]),
    emoji="🔗",
)
