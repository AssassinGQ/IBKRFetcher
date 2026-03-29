"""Pytest fixtures: auto-start/stop mock IBKR gateway for integration tests."""

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mock_gateway.ibkr_mock_server import MockIBKRServer

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 14002  # non-standard port to avoid conflicts


@pytest.fixture(scope="session")
def mock_gateway_port():
    """Return the port the mock gateway is listening on."""
    return MOCK_PORT


@pytest.fixture(scope="session", autouse=True)
def _mock_gateway():
    """Start mock IBKR gateway in a background thread for the test session."""
    server = MockIBKRServer(MOCK_HOST, MOCK_PORT)
    loop = asyncio.new_event_loop()

    import threading
    started = threading.Event()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True, name="mock-ibkr-gateway")
    thread.start()
    started.wait(timeout=5)

    time.sleep(0.2)
    yield server

    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=3)
