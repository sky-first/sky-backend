"""Unit tests for src/security/url_allowlist.py.

Regression for red-team CR-002 (2026-04-23): REST connector accepted
cloud-metadata URLs. This module is the single choke-point; if it
breaks, the SSRF comes back.
"""

from __future__ import annotations

import pytest

from src.security.url_allowlist import (
    UnsafeURLError,
    validate_outbound_url,
)


# --- Accepted ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://example.com/v1",
        "https://example.com:8080/path",
    ],
)
def test_accepts_public_https_urls(url):
    """example.com is guaranteed by IANA to resolve publicly — safe
    and stable for unit tests. Real customer URLs are validated by
    integration tests, not here."""
    assert validate_outbound_url(url) == url


# --- Rejected: schemes ---------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///proc/self/environ",
        "gopher://127.0.0.1:6379/_FLUSHALL",
        "dict://127.0.0.1:11211/stat",
        "ftp://example.com/",
        "javascript:alert(1)",
    ],
)
def test_rejects_non_http_schemes(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


# --- Rejected: cloud metadata (the primary attacker target) --------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/metadata/instance?api-version=2021-02-01",
        "http://169.254.170.2/v2/credentials/",  # ECS
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_rejects_cloud_metadata(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


# --- Rejected: private / loopback ranges ---------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/internal",
        "http://10.0.0.1/",
        "http://192.168.0.1/",
        "http://172.17.0.1/",  # default Docker gateway
        "http://[::1]:8000/",
    ],
)
def test_rejects_internal_hosts(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


# --- Rejected: userinfo (phishing trick) ---------------------------------


def test_rejects_userinfo_in_url():
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("https://user@evil.example/")


# --- allow_private knob --------------------------------------------------


def test_allow_private_lets_internal_hosts_through():
    """On-prem integrations need to reach RFC1918; the service layer
    that sets ``allow_private=True`` must still gate that behind an
    explicit feature flag + audit log. We only verify the knob works."""
    assert validate_outbound_url("http://10.0.0.5/api", allow_private=True) \
        == "http://10.0.0.5/api"
