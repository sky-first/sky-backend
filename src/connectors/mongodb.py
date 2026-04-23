"""MongoDB connector — first real NoSQL source.

pymongo 4.x is already in requirements.txt. We expose collection
documents as tabular rows via the standard `find` / `aggregate` ops so
agents, chat and widgets keep the same contract they use for SQL.

Config:

    {
        "uri": "mongodb://user:pass@host:27017",   # required
        "database": "mydb",                         # required
        "collections": [                            # optional "tables"
            {"name": "orders", "collection": "orders", "filter": {"status": "open"}}
        ]
    }

execute_query:
  - plain string = collection name; returns up to 100 docs
  - JSON {"collection": "...", "filter": {...}, "projection": {...}, "limit": 50}
  - JSON {"collection": "...", "pipeline": [{"$match": {...}}, ...]}  (aggregation)

Blocking pymongo is wrapped in `asyncio.to_thread` so the async event
loop isn't stalled. Small responses only — long-running aggregations
should route through the scheduler, not the live agent path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT_MS = 8000


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten BSON `_id` (ObjectId) and dates into strings so the
    downstream JSON serializer doesn't choke."""
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if k == "_id":
            out["_id"] = str(v)
        else:
            # Keep datetimes as ISO strings, pass the rest through —
            # pymongo gives us python-native types for everything else.
            try:
                out[k] = v.isoformat() if hasattr(v, "isoformat") else v
            except Exception:
                out[k] = v
    return out


def _client(config: Dict[str, Any]) -> MongoClient:
    uri = config.get("uri")
    if not uri:
        raise ValueError("MongoDB connector requires uri")
    return MongoClient(uri, serverSelectionTimeoutMS=DEFAULT_TIMEOUT_MS)


class MongoDBConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            return await asyncio.to_thread(self._test_sync, config)
        except ValueError:
            return False

    def _test_sync(self, config: Dict[str, Any]) -> bool:
        try:
            client = _client(config)
        except ValueError:
            return False
        try:
            # `ismaster` / `hello` is the cheapest ping. Returns in one
            # round-trip when reachable.
            client.admin.command("ping")
            return True
        except PyMongoError as exc:
            logger.info("MongoDB test_connection failed: %s", exc)
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._metadata_sync, config)
        except Exception as exc:
            logger.warning("MongoDB get_metadata failed: %s", exc)
            return {"tables": [], "schemas": []}

    def _metadata_sync(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        db_name = config.get("database")
        # User-declared collections first — stable + no extra round-trip.
        for c in config.get("collections") or []:
            tables.append({
                "name": c.get("name") or c.get("collection") or "collection",
                "kind": "mongo_collection",
                "columns": [],
                "metadata": {
                    "collection": c.get("collection") or c.get("name"),
                    "database": db_name,
                    "filter": c.get("filter") or {},
                },
            })
        # Supplement with live list_collection_names when possible.
        if db_name and not tables:
            try:
                client = _client(config)
                names = client[db_name].list_collection_names()
                for name in names:
                    tables.append({
                        "name": name,
                        "kind": "mongo_collection",
                        "columns": [],
                        "metadata": {"collection": name, "database": db_name},
                    })
                client.close()
            except Exception as exc:
                logger.info("MongoDB list_collection_names failed: %s", exc)
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._query_sync, config, query)
        except ValueError:
            raise

    def _query_sync(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        db_name = config.get("database")
        if not db_name:
            raise ValueError("MongoDB connector requires database")

        collection_name: str
        filter_doc: Dict[str, Any] = {}
        projection: Optional[Dict[str, int]] = None
        pipeline: Optional[List[Dict[str, Any]]] = None
        limit = DEFAULT_LIMIT

        q = (query or "").strip()
        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid MongoDB query JSON: {exc}") from exc
            collection_name = parsed.get("collection") or ""
            filter_doc = parsed.get("filter") or {}
            projection = parsed.get("projection")
            pipeline = parsed.get("pipeline")
            limit = int(parsed.get("limit") or DEFAULT_LIMIT)
        elif q:
            collection_name = q
        else:
            raise ValueError("MongoDB execute_query requires a collection name or descriptor")

        if not collection_name:
            raise ValueError("MongoDB query must include 'collection'")

        client = _client(config)
        try:
            coll = client[db_name][collection_name]
            if pipeline:
                cursor = coll.aggregate(pipeline)
                docs = list(cursor)
            else:
                cursor = coll.find(filter_doc, projection)
                if limit:
                    cursor = cursor.limit(max(1, min(1000, limit)))
                docs = list(cursor)
            return [_normalize(d) for d in docs]
        finally:
            try:
                client.close()
            except Exception:
                pass

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_collection: Dict[str, int] = {}
        for c in config.get("collections") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "collection": c.get("collection") or c.get("name"),
                        "filter": c.get("filter") or {},
                        "limit": 100,
                    }),
                )
                rows_by_collection[c.get("name") or c.get("collection") or "collection"] = len(rows)
            except Exception as exc:
                logger.warning("MongoDB sync %s failed: %s", c, exc)
                rows_by_collection[c.get("name") or "collection"] = 0
        return {"success": True, "rows_by_collection": rows_by_collection}
