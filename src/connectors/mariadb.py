"""MariaDB connector — wraps the MySQL driver.

MariaDB speaks the MySQL wire protocol; the only meaningful
difference at the connection layer is the default port (3306 same)
and that some MariaDB-specific features (e.g. ``RETURNING``) we
don't expose. Subclass + identity for clarity in audit logs.
"""

from __future__ import annotations

from src.connectors.mysql import MySQLConnector


class MariaDBConnector(MySQLConnector):
    """Identical to MySQLConnector — kept as a subclass so the audit
    trail can distinguish MariaDB rows from MySQL ones."""

    pass
