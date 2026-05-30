"""Request body size limit middleware — allowlist coverage.

Lucas hit a silent 413 for avatar uploads on staging because the
``RequestSizeLimitMiddleware`` allowlist only covered ``/api/v1/file-upload``
and ``/api/v1/ingest``. The real avatar endpoint lives under
``/api/v1/files/upload/image`` (and ``/api/files/...`` on the legacy mount),
so anything ≥1 MiB was rejected at the middleware before reaching the
handler. This test pins the allowlist so the regression can't sneak back.
"""
from __future__ import annotations

import pytest

from src.middleware.request_limits import _LARGE_BODY_ALLOWLIST


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/files/upload/image",
        "/api/v1/files/upload",
        "/api/v1/files/upload/pdf",
        "/api/files/upload/image",
        "/api/v1/file-upload/something",
        "/api/v1/ingest/anything",
    ],
)
def test_known_large_body_routes_are_allowlisted(path: str) -> None:
    assert any(path.startswith(prefix) for prefix in _LARGE_BODY_ALLOWLIST), (
        f"{path} should be covered by the large-body allowlist but isn't; "
        f"current entries: {_LARGE_BODY_ALLOWLIST}"
    )


def test_unrelated_route_is_not_allowlisted() -> None:
    # Sanity: the allowlist isn't accidentally swallowing everything.
    path = "/api/v1/chat"
    assert not any(path.startswith(prefix) for prefix in _LARGE_BODY_ALLOWLIST)
