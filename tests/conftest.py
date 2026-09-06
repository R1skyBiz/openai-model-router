"""Default tests cannot use credentials or reach the network."""

import os
import socket

import pytest


@pytest.fixture(autouse=True)
def offline_by_default(request, monkeypatch):
    if request.node.get_closest_marker("live_openai"):
        if os.environ.get("RUN_LIVE_OPENAI_TESTS") != "1":
            pytest.skip("live OpenAI checks require explicit opt-in")
        return
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RUN_LIVE_OPENAI_TESTS", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("network access is forbidden in default tests")

    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
