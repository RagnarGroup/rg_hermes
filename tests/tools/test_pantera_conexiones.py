"""``conectar_app`` and the relayed OAuth callback: a WhatsApp user approves on their phone, the
provider redirects to a public relay page, and the callback comes back through the chat to the
pending flow of that same profile only. Only allowlisted https servers can be connected."""

import json
from types import SimpleNamespace

import pytest

from tools import pantera_conexiones as pc
from tools.connectors import mcp_oauth


class _FakeFlow:
    def __init__(self, state):
        self.expected_state = state
        self.delivered = None
        self.redirect_uri = ""

    def deliver_callback(self, *, code, state, error, iss=None):
        self.delivered = (code, state, error, iss)

    def snapshot(self):
        return {"status": "approved" if self.delivered else "pending"}


@pytest.fixture
def active(monkeypatch):
    registro = {}
    monkeypatch.setattr(mcp_oauth, "_ACTIVE", registro)
    return registro


def test_https_redirect_uri_is_used_without_a_loopback_listener():
    flow = _FakeFlow("s")
    cfg = {"url": "https://mcp.example.com/mcp", "oauth": {"redirect_uri": "https://www.ragnargroup.app/conectar/"}}

    assert mcp_oauth.choose_callback_receiver(flow, cfg) is None
    assert flow.redirect_uri == "https://www.ragnargroup.app/conectar/"


def test_relayed_callback_only_reaches_a_flow_of_the_same_home(active):
    propio, ajeno = _FakeFlow("estado-propio"), _FakeFlow("estado-ajeno")
    active[("/home/a", "google")] = propio
    active[("/home/b", "google")] = ajeno

    assert mcp_oauth.deliver_relayed_callback("/home/a", "code=c1&state=estado-ajeno") is None
    assert ajeno.delivered is None
    assert mcp_oauth.deliver_relayed_callback("/home/a", "code=c1&state=otro") is None
    assert mcp_oauth.deliver_relayed_callback("/home/a", "code=c1&state=estado-propio&iss=https://accounts.google.com") == "google"
    assert propio.delivered == ("c1", "estado-propio", None, "https://accounts.google.com")


def test_only_allowlisted_https_servers_are_offered(monkeypatch):
    monkeypatch.setattr(pc, "_pantera_config", lambda: ({"google": {"url": "https://g/mcp"}}, "https://r/conectar/"))
    monkeypatch.setattr(pc, "_conectado", lambda nombre: False)

    assert json.loads(pc.conectar_app({"accion": "estado"})) == {"apps": [{"app": "google", "conectada": False}]}
    assert "no esta permitida" in pc.conectar_app({"accion": "link", "app": "filesystem"})


def test_allowlist_drops_non_https_entries(monkeypatch):
    from hermes_cli import config

    monkeypatch.setattr(config, "load_config", lambda: {"pantera": {
        "oauth_redirect_uri": "https://r/conectar/",
        "mcp_permitidos": {"google": {"url": "https://g/mcp"}, "local": {"command": "npx"}, "plano": {"url": "http://x/mcp"}},
    }})
    permitidos, redirect = pc._pantera_config()
    assert list(permitidos) == ["google"]
    assert redirect == "https://r/conectar/"


def test_link_starts_the_flow_with_the_relay_redirect(monkeypatch):
    from tools.connectors import mcp

    monkeypatch.setattr(pc, "_pantera_config", lambda: ({"google": {"url": "https://g/mcp"}}, "https://r/conectar/"))
    monkeypatch.setattr(mcp, "_LATE_ATTEMPTS", {})
    vistos = {}

    def falso_start(nombre, cfg=None, **_):
        vistos["cfg"] = cfg
        return SimpleNamespace(auth_url="https://accounts.example/authorize?x=1", flow=None)

    monkeypatch.setattr(mcp_oauth, "start", falso_start)
    salida = json.loads(pc.conectar_app({"accion": "link", "app": "google"}, session_id="s1"))

    assert salida["link"] == "https://accounts.example/authorize?x=1"
    assert vistos["cfg"] == {"url": "https://g/mcp", "auth": "oauth", "oauth": {"redirect_uri": "https://r/conectar/"}}
    assert any("google" in intentos for intentos in mcp._LATE_ATTEMPTS.values())


def test_completar_accepts_the_full_relay_url(monkeypatch, active):
    flow = _FakeFlow("st")
    monkeypatch.setattr(pc, "_hermes_home", lambda: "/home/a")
    monkeypatch.setattr(pc, "_pantera_config", lambda: ({"google": {"url": "https://g/mcp"}}, "https://r/conectar/"))
    active[("/home/a", "google")] = flow

    salida = json.loads(pc.conectar_app({"accion": "completar", "url": "https://r/conectar/?code=abc&state=st"}))
    assert salida["conectada"] is True
    assert flow.delivered[0] == "abc"

    assert "no corresponde" in pc.conectar_app({"accion": "completar", "url": "https://r/conectar/?code=x&state=nada"})
