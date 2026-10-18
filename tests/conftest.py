"""Integration tests need the FalkorDB (:6391) and/or Gitea (:3300) containers; without them they are
reported as skipped ("blocked"), never as passed."""

import socket

import pytest

from pathmemory.config import settings


def _up(host, port):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    falkordb = _up(settings.falkordb_host, settings.falkordb_port)
    gitea = _up("localhost", int(settings.gitea_url.rsplit(":", 1)[-1].strip("/")))
    for item in items:
        if item.get_closest_marker("falkordb") and not falkordb:
            item.add_marker(pytest.mark.skip(reason="BLOCKED: FalkorDB not reachable"))
        if item.get_closest_marker("gitea") and not gitea:
            item.add_marker(pytest.mark.skip(reason="BLOCKED: Gitea not reachable"))
