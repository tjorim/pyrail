"""Fixtures for the live smoke tests, which call the real iRail API.

Every test below tests/live is marked ``live`` and excluded from ordinary runs
(see ``addopts`` in pyproject.toml). Run them with ``pytest -m live``.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import ClientSession
import pytest
import pytest_asyncio

from pyrail.irail import iRail
from tests.live.live_api import REQUEST_TIMEOUT, LiveApi


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test in this directory as live so ordinary runs deselect it."""
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)


@pytest_asyncio.fixture
async def live() -> AsyncIterator[LiveApi]:
    """Provide a LiveApi backed by a session with a bounded request timeout."""
    async with ClientSession(timeout=REQUEST_TIMEOUT) as session, iRail(session=session) as client:
        yield LiveApi(client)


@pytest.fixture(scope="session")
def travel_date() -> tuple[str, str]:
    """Tomorrow at noon in Belgium as (DDMMYY, HHMM).

    A fixed daytime slot on a future date keeps liveboards, connections and vehicles
    populated regardless of when the suite runs, unlike the current time at night.
    """
    tomorrow = datetime.now(ZoneInfo("Europe/Brussels")) + timedelta(days=1)
    return tomorrow.strftime("%d%m%y"), "1200"
