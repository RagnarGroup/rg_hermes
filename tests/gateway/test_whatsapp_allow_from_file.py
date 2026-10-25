"""``whatsapp.allow_from_file``: an external process owns the DM allowlist and rewrites a JSON file;
every live check re-reads it on change, so adding or removing a user needs no gateway restart."""

import json
import os

from gateway.config import PlatformConfig


def _adapter(allow_file):
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter
    return WhatsAppAdapter(PlatformConfig(enabled=True, extra={"dm_policy": "allowlist", "allow_from_file": str(allow_file)}))


def _write(path, ids, *, bump=0):
    path.write_text(json.dumps({"allowed_users": ids}), encoding="utf-8")
    if bump:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + bump))


def test_missing_file_admits_nobody_until_it_appears(tmp_path):
    allow_file = tmp_path / "allowlist.json"
    adapter = _adapter(allow_file)
    assert adapter._is_dm_allowed("15551234567") is False

    _write(allow_file, ["15551234567"])
    assert adapter._is_dm_allowed("15551234567") is True
    assert adapter._is_dm_allowed("15559876543") is False


def test_rewrites_apply_live_and_revocations_take_effect(tmp_path):
    allow_file = tmp_path / "allowlist.json"
    _write(allow_file, ["15551234567"])
    adapter = _adapter(allow_file)
    assert adapter._is_dm_allowed("15551234567") is True

    _write(allow_file, ["15559876543"], bump=1_000_000)
    assert adapter._is_dm_allowed("15559876543") is True
    assert adapter._is_dm_allowed("15551234567") is False


def test_unreadable_rewrite_keeps_the_last_good_list(tmp_path):
    allow_file = tmp_path / "allowlist.json"
    _write(allow_file, ["15551234567"])
    adapter = _adapter(allow_file)
    assert adapter._is_dm_allowed("15551234567") is True

    allow_file.write_text("{not json", encoding="utf-8")
    assert adapter._is_dm_allowed("15551234567") is True
    allow_file.write_text(json.dumps({"allowed_users": "15559876543"}), encoding="utf-8")
    assert adapter._is_dm_allowed("15559876543") is False
    allow_file.unlink()
    assert adapter._is_dm_allowed("15551234567") is True


def test_file_outranks_env_and_config_lists(tmp_path, monkeypatch):
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "15550000000")
    allow_file = tmp_path / "allowlist.json"
    _write(allow_file, ["15551234567"])
    adapter = WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "dm_policy": "allowlist", "allow_from_file": str(allow_file), "allow_from": ["15550000001"]}))

    assert adapter._live_dm_allow_from() == {"15551234567"}
    assert adapter._allow_from == {"15551234567"}


def test_yaml_key_reaches_extra_without_becoming_an_env_var(monkeypatch):
    from plugins.platforms.whatsapp.adapter import _apply_yaml_config

    seeded = _apply_yaml_config({}, {"allow_from_file": "/var/lib/pantera/allowlist.json"})

    assert seeded == {"allow_from_file": "/var/lib/pantera/allowlist.json"}
    assert not any("ALLOW_FROM_FILE" in key for key in os.environ)
