"""Amazon Redshift connector.

Redshift speaks the PostgreSQL wire protocol, so the simplest honest
implementation is a thin subclass of ``PostgreSQLConnector`` with the
Redshift default port and a distinct name in the registry. Keeping it
as a separate class (rather than aliasing ``PostgreSQLConnector``
directly) leaves room for Redshift-specific metadata tweaks (e.g.
``SVV_EXTERNAL_TABLES`` for Spectrum) without touching the Postgres
code.

Config::

    {
        "host": "example.abc123.us-east-1.redshift.amazonaws.com",
        "port": 5439,
        "database": "dev",
        "username": "admin",
        "password": "***",
    }
"""

from __future__ import annotations

from typing import Any, Dict

from src.connectors.postgresql import PostgreSQLConnector


class RedshiftConnector(PostgreSQLConnector):
    async def _noop(self) -> None:  # pragma: no cover - placeholder hook
        return None

    def _get_connection_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Override the default port. Everything else matches Postgres."""
        params = super()._get_connection_params(config)
        # Redshift listens on 5439 by default, not 5432.
        if not config.get("port"):
            params["port"] = 5439
        return params
