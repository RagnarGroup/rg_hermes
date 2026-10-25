"""``gateway.profile_routes_file``: profile routes owned by an external process.

The file is JSON with a ``profile_routes`` list in the same shape as ``gateway.profile_routes``
in config.yaml. The served-profile watcher calls ``refresh_profile_routes`` every tick; when the
file signature changes, ``config.profile_routes`` becomes the config.yaml routes plus the file's,
most-specific-first (equal scores keep config.yaml first). Every consumer reads that list, so a
routing change applies without restarting the gateway.

A file that never existed contributes nothing. One that disappears or turns unreadable later keeps
the last good routes: dropping them would send those senders to the default profile.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from gateway.profile_routing import parse_profile_routes
from utils import file_signature

logger = logging.getLogger(__name__)


class ProfileRoutesFile:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self._signature: Optional[tuple] = None
        self._raw: list[dict[str, Any]] = []

    def load(self) -> Optional[list[dict[str, Any]]]:
        """The file's raw route dicts when they changed since the last call, else ``None``."""
        try:
            signature = file_signature(os.stat(self.path))
            if signature == self._signature:
                return None
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            raw = data["profile_routes"]
            if not isinstance(raw, list) or not all(isinstance(entry, dict) for entry in raw):
                raise ValueError("profile_routes must be a list of objects")
        except FileNotFoundError:
            if self._signature is not None:
                logger.warning("profile_routes_file %s disappeared; keeping the last routes", self.path)
                self._signature = ()
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("profile_routes_file %s unreadable (%s); keeping the last routes", self.path, exc)
            return None
        self._signature = signature
        self._raw = raw
        return raw


def refresh_profile_routes(runner) -> bool:
    """Re-merge ``runner.config.profile_routes`` when the routes file changed; True when it did."""
    config = getattr(runner, "config", None)
    path = getattr(config, "profile_routes_file", None)
    if not path:
        return False
    tracker = getattr(runner, "_profile_routes_file", None)
    if tracker is None or tracker.path != Path(path).expanduser():
        tracker = ProfileRoutesFile(path)
        runner._profile_routes_file = tracker
        runner._static_profile_routes = list(config.profile_routes)
    raw = tracker.load()
    if raw is None:
        return False
    merged = list(runner._static_profile_routes) + parse_profile_routes(raw)
    merged.sort(key=lambda route: route.specificity, reverse=True)
    config.profile_routes = merged
    logger.info("Profile routes reloaded from %s: %d route(s)", tracker.path, len(merged))
    return True
