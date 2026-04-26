"""Tests for the `is_real` flag surfaced by /connectors.

The UI uses this flag to hide configuration forms (and instead render a
"Coming soon" pill) for connector ids whose registry entry is still the
MockConnector — otherwise users would fill in real credentials for a
connector whose test_connection silently returns True and whose queries
return an empty list.

We test the service (not just the registry helper) because the HTTP
contract is what downstream clients depend on, and a future refactor
could easily drop the field from the response without breaking the
underlying helper.
"""

from __future__ import annotations

import pytest

from src.connectors.registry import CONNECTORS, MockConnector, is_real_connector
from src.services.connector_service import ConnectorService


@pytest.fixture
def service() -> ConnectorService:
    # db is unused by the pure in-memory methods we exercise here.
    return ConnectorService(db=None)  # type: ignore[arg-type]


# --- Registry helper -------------------------------------------------


def test_is_real_connector_true_for_real_driver():
    # PostgreSQL is one of the oldest real drivers, safe baseline.
    assert is_real_connector("postgresql") is True


def test_is_real_connector_false_for_mock_driver():
    # Snowflake is still wired to MockConnector in CONNECTORS.
    assert is_real_connector("snowflake") is False


def test_is_real_connector_false_for_unknown_id():
    assert is_real_connector("not-a-connector") is False


# --- Service contract ------------------------------------------------


def test_get_connector_includes_is_real_for_real_driver(service: ConnectorService):
    resp = service.get_connector("postgresql")
    assert resp.is_real is True


def test_get_connector_includes_is_real_false_for_mock(service: ConnectorService):
    resp = service.get_connector("snowflake")
    assert resp.is_real is False


def test_get_connectors_list_carries_is_real_per_entry(service: ConnectorService):
    """End-to-end: every connector returned by /connectors must carry
    a truthful is_real reflecting its registry binding."""
    responses = service.get_connectors()
    by_id = {r.id: r for r in responses}

    # Real drivers we already ship to customers. If any of these flips
    # to False, we've silently regressed a production integration.
    real_ids = [
        "postgresql",
        "mysql",
        "mongodb",
        "bigquery",
        "sqlite",
    ]
    for cid in real_ids:
        assert cid in by_id, f"expected {cid} in /connectors response"
        assert by_id[cid].is_real is True, f"{cid} must be flagged is_real=True"

    # Warehouses still stubbed — these must stay False until #TODO
    # Implement real connectors lands.
    mock_ids = ["snowflake", "redshift", "sqlserver", "oracle", "clickhouse", "databricks"]
    for cid in mock_ids:
        assert cid in by_id, f"expected {cid} in /connectors response"
        assert by_id[cid].is_real is False, (
            f"{cid} is still wired to MockConnector — UI relies on is_real=False "
            "to show a Coming soon pill"
        )


def test_is_real_flag_matches_registry_binding_for_every_connector(
    service: ConnectorService,
):
    """Defense-in-depth: iterate over the authoritative registry and
    confirm the response layer never disagrees with it. Catches
    copy-paste bugs where someone hardcodes is_real in a definition
    but forgets to update the registry (or vice versa)."""
    responses = {r.id: r for r in service.get_connectors()}
    for connector_id, cls in CONNECTORS.items():
        # The service only returns ids that have a matching definition
        # in _get_connector_definition. Skip any stragglers.
        if connector_id not in responses:
            continue
        expected = cls is not MockConnector
        assert responses[connector_id].is_real is expected, (
            f"registry says {connector_id} is_real={expected} but "
            f"ConnectorResponse returned {responses[connector_id].is_real}"
        )
