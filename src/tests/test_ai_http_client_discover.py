"""Pin the footgun-protection on ``AIServiceHTTPClient.discover_connection``
that Lucas's 2026-05-05 review caught.

Before: ``space_id: Optional[str] = None`` — any caller that forgot
the kwarg would fall through to "shared/global" indexing, which is
correct for the demo dataset but a tenant-private connection
indexed shared becomes globally readable across that tenant's
spaces.

After: ``space_id`` is required (raises ValueError on empty), and
explicit "shared" intent uses the ``SHARED_INDEX`` sentinel.
"""

from __future__ import annotations

import pytest

from src.ai.http_client import AIServiceHTTPClient


def test_discover_connection_rejects_empty_space_id():
    client = AIServiceHTTPClient()
    import asyncio

    async def _go():
        await client.discover_connection(connection_id="abc", space_id="")

    with pytest.raises(ValueError, match="explicit space_id"):
        asyncio.run(_go())


def test_discover_connection_rejects_none_space_id():
    """A caller that passes None explicitly (not just forgot the
    kwarg) still gets the explicit error so the intent stays loud."""
    client = AIServiceHTTPClient()
    import asyncio

    async def _go():
        # type: ignore[arg-type] — exercising defence at runtime.
        await client.discover_connection(connection_id="abc", space_id=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="explicit space_id"):
        asyncio.run(_go())


def test_shared_index_sentinel_is_a_distinct_value():
    """The sentinel must be a string that no real Space UUID could
    collide with — `__shared__` doubles as a ValueError-resistant
    marker and a self-documenting label in logs/params."""
    assert isinstance(AIServiceHTTPClient.SHARED_INDEX, str)
    assert AIServiceHTTPClient.SHARED_INDEX == "__shared__"
    # Real UUIDs never start with __, so a misuse like
    # `space_id=AIServiceHTTPClient.SHARED_INDEX` is clearly distinct
    # from any legitimate space_id.
    assert AIServiceHTTPClient.SHARED_INDEX.startswith("__")
