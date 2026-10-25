"""``gateway.profile_routes_file``: routes written by an external process join the config.yaml routes
live, so routing a new WhatsApp sender to their profile needs no restart; an unreadable rewrite keeps
the last good routes instead of dropping senders to the default profile."""

import json
import os
from types import SimpleNamespace

from gateway.config import GatewayConfig
from gateway.profile_routes_file import refresh_profile_routes
from gateway.profile_routing import match_profile_route

GRUPO = "120363410436176059@g.us"


def _runner(routes_file):
    config = GatewayConfig.from_dict({
        "profile_routes_file": str(routes_file),
        "profile_routes": [
            {"name": "grupo", "platform": "whatsapp", "chat_id": GRUPO, "profile": "default"},
            {"name": "resto", "platform": "whatsapp", "profile": "pantera-espera"},
        ],
    })
    return SimpleNamespace(config=config)


def _write(path, routes, *, bump=0):
    path.write_text(json.dumps({"allowed_users": [], "profile_routes": routes}), encoding="utf-8")
    if bump:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + bump))


def _profile_for(runner, chat_id):
    route = match_profile_route(runner.config.profile_routes, "whatsapp", chat_id=chat_id)
    return route.profile if route else None


def test_file_routes_join_config_routes_and_win_by_specificity(tmp_path):
    routes_file = tmp_path / "allowlist.json"
    _write(routes_file, [{"name": "c7", "platform": "whatsapp", "chat_id": "51987654321", "profile": "cliente-7"}])
    runner = _runner(routes_file)

    assert refresh_profile_routes(runner) is True
    assert _profile_for(runner, "51987654321") == "cliente-7"
    assert _profile_for(runner, GRUPO) == "default"
    assert _profile_for(runner, "51911111111") == "pantera-espera"
    assert refresh_profile_routes(runner) is False


def test_rewrite_applies_live_and_removed_routes_fall_to_the_catch_all(tmp_path):
    routes_file = tmp_path / "allowlist.json"
    _write(routes_file, [{"name": "c7", "platform": "whatsapp", "chat_id": "51987654321", "profile": "cliente-7"}])
    runner = _runner(routes_file)
    refresh_profile_routes(runner)

    _write(routes_file, [{"name": "c8", "platform": "whatsapp", "chat_id": "51955512345", "profile": "cliente-8"}],
           bump=1_000_000)
    assert refresh_profile_routes(runner) is True
    assert _profile_for(runner, "51955512345") == "cliente-8"
    assert _profile_for(runner, "51987654321") == "pantera-espera"


def test_unreadable_or_missing_file_keeps_the_last_good_routes(tmp_path):
    routes_file = tmp_path / "allowlist.json"
    _write(routes_file, [{"name": "c7", "platform": "whatsapp", "chat_id": "51987654321", "profile": "cliente-7"}])
    runner = _runner(routes_file)
    refresh_profile_routes(runner)

    routes_file.write_text("{roto", encoding="utf-8")
    assert refresh_profile_routes(runner) is False
    assert _profile_for(runner, "51987654321") == "cliente-7"

    routes_file.unlink()
    assert refresh_profile_routes(runner) is False
    assert _profile_for(runner, "51987654321") == "cliente-7"


def test_without_the_key_or_the_file_nothing_changes(tmp_path):
    runner = _runner(tmp_path / "no-existe.json")
    before = list(runner.config.profile_routes)
    assert refresh_profile_routes(runner) is False
    assert runner.config.profile_routes == before

    plain = SimpleNamespace(config=GatewayConfig.from_dict({}))
    assert plain.config.profile_routes_file is None
    assert refresh_profile_routes(plain) is False


def test_invalid_profile_names_in_the_file_are_skipped(tmp_path):
    routes_file = tmp_path / "allowlist.json"
    _write(routes_file, [{"name": "malo", "platform": "whatsapp", "chat_id": "51987654321", "profile": "../default"}])
    runner = _runner(routes_file)
    refresh_profile_routes(runner)
    assert _profile_for(runner, "51987654321") == "pantera-espera"
