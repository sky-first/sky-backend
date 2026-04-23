"""Unit tests for src/security/filesystem_paths.py — CR-003."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from src.security.filesystem_paths import (
    UnsafePathError,
    validate_sqlite_path,
)


@pytest.mark.parametrize(
    "path",
    [
        "../../../../etc/passwd",
        "..%2f..%2f..%2f..%2fetc%2fpasswd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..\\..\\..\\..\\windows\\win.ini",  # also hits backslash reject
        "....//....//....//etc/passwd",
        "..;/..;/..;/etc/passwd",
    ],
)
def test_rejects_traversal_payloads(path):
    with pytest.raises(UnsafePathError):
        validate_sqlite_path(path)


def test_rejects_nullbyte_truncation():
    with pytest.raises(UnsafePathError):
        validate_sqlite_path("/tmp/safe.db\x00.jpg")
    with pytest.raises(UnsafePathError):
        validate_sqlite_path("/tmp/safe.db%00.jpg")


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/etc/./passwd",
        "/proc/self/environ",
        "/sys/class",
        "/root/.ssh/id_rsa",
        "/home/someone/secret.db",
    ],
)
def test_rejects_sensitive_prefixes(path):
    with pytest.raises(UnsafePathError):
        validate_sqlite_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/var/data/sales.db",
        "/tmp/scratch.sqlite",
        "./local.db",
        "customers.db",
    ],
)
def test_accepts_reasonable_paths_without_allowlist(path):
    """With no SQLITE_ALLOWED_PREFIXES env, the guard relies on
    traversal / sensitive-prefix rejection only."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SQLITE_ALLOWED_PREFIXES", None)
        assert validate_sqlite_path(path) == path


def test_allowlist_accepts_matching_realpath(tmp_path):
    target = tmp_path / "db.sqlite"
    target.write_text("")
    with mock.patch.dict(os.environ, {"SQLITE_ALLOWED_PREFIXES": str(tmp_path)}):
        assert validate_sqlite_path(str(target)) == str(target)


def test_allowlist_rejects_outside_realpath(tmp_path):
    outside = "/var/data/other.db"
    with mock.patch.dict(os.environ, {"SQLITE_ALLOWED_PREFIXES": str(tmp_path)}):
        with pytest.raises(UnsafePathError):
            validate_sqlite_path(outside)


def test_empty_path_is_rejected():
    with pytest.raises(UnsafePathError):
        validate_sqlite_path("")
