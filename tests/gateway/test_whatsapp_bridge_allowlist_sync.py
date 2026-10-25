"""The Node bridge gates DMs before the adapter sees them, so a live allowlist change (pairing
approve/revoke, ``/reload``) must reach it too — otherwise the bridge keeps its spawn-time snapshot,
dropping newly approved users and forwarding revoked ones until a restart.
"""

import asyncio
from contextlib import asynccontextmanager

from gateway.config import PlatformConfig


class _FakeResponse:
    def __init__(self, status):
        self.status = status


def _adapter_recording_posts(status=200):
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    adapter = WhatsAppAdapter(PlatformConfig(enabled=True, extra={"dm_policy": "allowlist"}))
    posts = []

    @asynccontextmanager
    async def fake_req(method, path, timeout, **kwargs):
        posts.append((method, path, kwargs.get("json")))
        yield _FakeResponse(status)

    adapter._bridge_req = fake_req
    return adapter, posts


def test_live_env_allowlist_change_is_pushed_to_the_bridge_once(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "15551234567")
    adapter, posts = _adapter_recording_posts()

    asyncio.run(adapter._sync_bridge_allowlist())
    asyncio.run(adapter._sync_bridge_allowlist())
    assert posts == [("post", "allowlist", {"allowedUsers": ["15551234567"]})]

    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "15551234567,15559876543")
    asyncio.run(adapter._sync_bridge_allowlist())
    assert posts[-1] == ("post", "allowlist", {"allowedUsers": ["15551234567", "15559876543"]})

    monkeypatch.delenv("WHATSAPP_ALLOWED_USERS")
    asyncio.run(adapter._sync_bridge_allowlist())
    assert posts[-1] == ("post", "allowlist", {"allowedUsers": []})
    assert len(posts) == 3


def test_bridge_without_the_endpoint_is_not_retried_every_poll(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "15551234567")
    adapter, posts = _adapter_recording_posts(status=404)

    asyncio.run(adapter._sync_bridge_allowlist())
    asyncio.run(adapter._sync_bridge_allowlist())
    assert len(posts) == 1
