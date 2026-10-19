"""Fixtures for the live smoke tests, which call the real iRail API.

Every test below tests/live is marked ``live`` and excluded from ordinary runs
(see ``addopts`` in pyproject.toml). Run them with ``pytest -m live``.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import ClientSession
import pytest

from pyrail.irail import IRail
from tests.live.live_api import REQUEST_TIMEOUT, LiveApi


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test in this directory as live so ordinary runs deselect it."""
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)


@pytest.fixture
async def live() -> AsyncIterator[LiveApi]:
    """Provide a LiveApi backed by a session with a bounded request timeout.

    The client's own retries are disabled because LiveApi retries with a longer backoff,
    which keeps the number of requests and the total runtime per endpoint bounded.
    """
    async with ClientSession(timeout=REQUEST_TIMEOUT) as session, IRail(session=session, max_retries=0) as client:
        yield LiveApi(client)


@pytest.fixture(scope="session")
def travel_date() -> tuple[str, str]:
    """Tomorrow at noon in Belgium as (DDMMYY, HHMM).

    A fixed daytime slot on a future date keeps liveboards, connections and vehicles
    populated regardless of when the suite runs, unlike the current time at night.
    """
    tomorrow = datetime.now(ZoneInfo("Europe/Brussels")) + timedelta(days=1)
    return tomorrow.strftime("%d%m%y"), "1200"
