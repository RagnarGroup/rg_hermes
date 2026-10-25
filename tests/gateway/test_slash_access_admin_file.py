"""File-backed slash admins (``allow_admin_from_file``), WhatsApp phone/LID alias matching and /cmds."""
from __future__ import annotations

import json
import os

import pytest

from gateway.config import Platform
from gateway.slash_access import policy_from_extra
from tests.gateway.test_slash_access_dispatch import _make_event, _make_runner, _make_source


def _write(path, admins):
    path.write_text(json.dumps({"admins": admins, "allowed_users": ["x"]}), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


def test_admin_file_gates_and_tracks_rewrites(tmp_path):
    path = tmp_path / "allowlist.json"
    _write(path, ["111"])
    extra = {"allow_admin_from_file": str(path), "user_allowed_commands": ["new"]}
    policy = policy_from_extra(extra, "dm")
    assert policy.enabled and policy.is_admin("111") and not policy.is_admin("222")
    assert policy.can_run("222", "new") and policy.can_run("222", "cmds") and not policy.can_run("222", "restart")

    _write(path, ["222"])
    policy = policy_from_extra(extra, "dm")
    assert policy.is_admin("222") and not policy.is_admin("111")


def test_admin_file_missing_or_broken_fails_closed_then_keeps_last_list(tmp_path):
    path = tmp_path / "allowlist.json"
    policy = policy_from_extra({"allow_admin_from_file": str(path)}, "dm")
    assert policy.enabled and not policy.is_admin("111")

    _write(path, ["111"])
    assert policy_from_extra({"allow_admin_from_file": str(path)}, "dm").is_admin("111")
    path.write_text("{not json", encoding="utf-8")
    assert policy_from_extra({"allow_admin_from_file": str(path)}, "dm").is_admin("111")


def test_whatsapp_admin_matches_lid_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    session = tmp_path / "platforms" / "whatsapp" / "session"
    session.mkdir(parents=True)
    (session / "lid-mapping-51914101182.json").write_text(json.dumps("251161533747302@lid"), encoding="utf-8")
    (session / "lid-mapping-251161533747302_reverse.json").write_text(json.dumps("51914101182"), encoding="utf-8")

    whatsapp = policy_from_extra({"allow_admin_from": ["+51914101182"]}, "dm", "whatsapp")
    assert whatsapp.is_admin("251161533747302@lid")
    assert whatsapp.is_admin("51914101182@s.whatsapp.net")
    assert not whatsapp.is_admin("166653958615179@lid")
    assert not policy_from_extra({"allow_admin_from": ["51914101182"]}, "dm").is_admin("251161533747302@lid")


@pytest.mark.asyncio
async def test_cmds_lists_only_runnable_commands_for_users():
    runner = _make_runner(
        platform=Platform.WHATSAPP,
        platform_extra={"allow_admin_from": ["111"], "user_allowed_commands": ["new", "status"]},
    )
    user = await runner._handle_cmds_command(
        _make_event("/cmds", _make_source(platform=Platform.WHATSAPP, user_id="999")))
    assert "/new " in user and "/status " in user and "/cmds " in user
    assert "/restart " not in user and "/update " not in user

    admin = await runner._handle_cmds_command(
        _make_event("/cmds", _make_source(platform=Platform.WHATSAPP, user_id="111")))
    assert "/restart " in admin and "/new " in admin


@pytest.mark.asyncio
async def test_cmds_is_reachable_for_gated_users_through_dispatch():
    runner = _make_runner(platform_extra={"allow_admin_from": ["111"]})
    result = await runner._handle_message(_make_event("/cmds", _make_source(user_id="999")))
    assert "/cmds" in result and "/restart " not in result
