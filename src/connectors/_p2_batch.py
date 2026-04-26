"""Long-tail P2 connector pack — REST adapter declarations.

Each class wraps a provider with one declarative spec (BASE +
RESOURCE_MAP). The adapter handles auth + listing + the
BaseConnector contract. Coverage of the connectors advertised on
skyfirstlabs.com/platform/integrations:

  * Apps & CRM  — Intercom, Shopify, QuickBooks, Xero,
                  Mailgun-style senders, Microsoft Dynamics
  * API surfaces — Twilio, Twitter / X, Gmail, Outlook
  * Vector DBs  — Pinecone, Qdrant, Chroma, Weaviate
  * Warehouses  — SingleStore, Apache Druid, Amazon Athena
  * SQL/NoSQL extras — Supabase REST, PlanetScale, Neo4j, DuckDB,
                       Cosmos DB, Couchbase, etc.

Where a provider needs a more specialised driver (custom SQL drivers
for Cassandra / DynamoDB / Pinecone gRPC), the adapter still accepts
test_connection over a thin REST proxy and the team can replace
each one in place without changing the registry id.
"""

from __future__ import annotations

from typing import Any, Dict

from src.connectors._rest_adapter import RestAdapterConnector, _bearer_headers


def _basic_headers(config: Dict[str, Any]) -> Dict[str, str]:
    """Basic auth used by Mailgun, some legacy providers."""
    import base64

    auth = config.get("auth") or {}
    user = auth.get("user") or auth.get("username") or "api"
    pwd = auth.get("password") or auth.get("api_token") or ""
    creds = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {creds}"}


def _api_key_query_headers(config: Dict[str, Any]) -> Dict[str, str]:
    """Some providers want the key as a header named API-Key."""
    auth = config.get("auth") or {}
    headers = {"Accept": "application/json"}
    if auth.get("api_token"):
        headers["Api-Key"] = auth["api_token"]
    return headers


# ─── Apps & CRM ────────────────────────────────────────────────────────


class IntercomConnector(RestAdapterConnector):
    BASE = "https://api.intercom.io"
    DEFAULT_KIND = "contacts"
    PROBE_PATH = "/me"
    RESOURCE_MAP = {
        "contacts": "/contacts",
        "companies": "/companies",
        "conversations": "/conversations",
        "tags": "/tags",
        "teams": "/teams",
    }
    DATA_KEY = "data"


class ShopifyConnector(RestAdapterConnector):
    """Shopify storefront uses a {shop}.myshopify.com base — declare
    via config["base_url"] = "https://yourshop.myshopify.com/admin/api/2024-01".
    """

    BASE = ""
    DEFAULT_KIND = "products"
    RESOURCE_MAP = {
        "products": "/products.json",
        "orders": "/orders.json",
        "customers": "/customers.json",
        "inventory_items": "/inventory_items.json",
    }

    @staticmethod
    def AUTH_FN(config: Dict[str, Any]) -> Dict[str, str]:
        auth = config.get("auth") or {}
        token = auth.get("api_token") or auth.get("token") or ""
        return {"Accept": "application/json", "X-Shopify-Access-Token": token}


class QuickBooksConnector(RestAdapterConnector):
    """QuickBooks Online API — config["realm_id"] threaded into the
    base URL by the caller (or via explicit base_url override)."""

    BASE = "https://quickbooks.api.intuit.com/v3/company"
    DEFAULT_KIND = "customers"
    RESOURCE_MAP = {
        "customers": "/customers",
        "invoices": "/invoices",
        "items": "/items",
        "payments": "/payments",
    }


class XeroConnector(RestAdapterConnector):
    BASE = "https://api.xero.com/api.xro/2.0"
    DEFAULT_KIND = "contacts"
    PROBE_PATH = "/Organisations"
    RESOURCE_MAP = {
        "contacts": "/Contacts",
        "invoices": "/Invoices",
        "accounts": "/Accounts",
        "payments": "/Payments",
    }


class MicrosoftDynamicsConnector(RestAdapterConnector):
    """Dynamics 365 — config["base_url"] is the org-specific Web API."""

    BASE = ""
    DEFAULT_KIND = "accounts"
    RESOURCE_MAP = {
        "accounts": "/accounts",
        "contacts": "/contacts",
        "leads": "/leads",
        "opportunities": "/opportunities",
    }


class ServiceNowConnector(RestAdapterConnector):
    """config["base_url"] = https://<instance>.service-now.com/api/now/table"""

    BASE = ""
    DEFAULT_KIND = "incident"
    RESOURCE_MAP = {
        "incident": "/incident",
        "problem": "/problem",
        "change_request": "/change_request",
        "cmdb_ci": "/cmdb_ci",
    }
    AUTH_FN = staticmethod(_basic_headers)


class NetSuiteConnector(RestAdapterConnector):
    """Oracle NetSuite SuiteQL REST. config["base_url"] is account-specific."""

    BASE = ""
    DEFAULT_KIND = "customer"
    RESOURCE_MAP = {
        "customer": "/customer",
        "vendor": "/vendor",
        "salesorder": "/salesorder",
        "invoice": "/invoice",
    }


class WorkdayConnector(RestAdapterConnector):
    """Workday RaaS / REST — base_url is tenant-specific."""

    BASE = ""
    DEFAULT_KIND = "workers"
    RESOURCE_MAP = {
        "workers": "/workers",
        "organizations": "/organizations",
        "positions": "/positions",
    }


class SapODataConnector(RestAdapterConnector):
    """SAP OData — base_url is the OData service root."""

    BASE = ""
    DEFAULT_KIND = "BusinessPartners"
    RESOURCE_MAP = {
        "BusinessPartners": "/BusinessPartners",
        "Products": "/Products",
        "SalesOrders": "/SalesOrders",
    }


# ─── API surfaces ──────────────────────────────────────────────────────


class TwilioConnector(RestAdapterConnector):
    """Twilio — Basic auth with AccountSid:AuthToken. Sub-account /
    messaging / voice resources keyed by Account SID in the path."""

    BASE = "https://api.twilio.com/2010-04-01"
    DEFAULT_KIND = "messages"
    RESOURCE_MAP = {
        "messages": "/Messages.json",
        "calls": "/Calls.json",
        "accounts": "/Accounts.json",
        "phone_numbers": "/IncomingPhoneNumbers.json",
    }
    AUTH_FN = staticmethod(_basic_headers)


class TwitterConnector(RestAdapterConnector):
    BASE = "https://api.twitter.com/2"
    DEFAULT_KIND = "users"
    PROBE_PATH = "/users/me"
    RESOURCE_MAP = {
        "users": "/users/me",
        "tweets": "/tweets/search/recent",
    }


class GmailConnector(RestAdapterConnector):
    """Gmail — Google OAuth bearer. Read-only message + thread surface."""

    BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
    DEFAULT_KIND = "messages"
    PROBE_PATH = "/profile"
    RESOURCE_MAP = {
        "messages": "/messages",
        "threads": "/threads",
        "labels": "/labels",
    }


class OutlookConnector(RestAdapterConnector):
    """Microsoft Graph mailbox surface."""

    BASE = "https://graph.microsoft.com/v1.0/me"
    DEFAULT_KIND = "messages"
    RESOURCE_MAP = {
        "messages": "/messages",
        "mailFolders": "/mailFolders",
        "events": "/events",
    }


class TeamsConnector(RestAdapterConnector):
    """Microsoft Teams via Graph."""

    BASE = "https://graph.microsoft.com/v1.0"
    DEFAULT_KIND = "teams"
    RESOURCE_MAP = {
        "teams": "/teams",
        "chats": "/me/chats",
    }


class EvernoteConnector(RestAdapterConnector):
    """Evernote — bearer token, REST for notes + notebooks."""

    BASE = "https://www.evernote.com/api"
    DEFAULT_KIND = "notes"
    RESOURCE_MAP = {
        "notes": "/notes",
        "notebooks": "/notebooks",
        "tags": "/tags",
    }


# ─── Vector DBs ────────────────────────────────────────────────────────


class PineconeConnector(RestAdapterConnector):
    """Pinecone control plane — list indexes + collections.
    Index queries hit a separate index host; this surface is the
    project-level metadata that the AI ingest worker uses to know
    what's available."""

    BASE = "https://api.pinecone.io"
    DEFAULT_KIND = "indexes"
    PROBE_PATH = "/indexes"
    RESOURCE_MAP = {"indexes": "/indexes", "collections": "/collections"}
    AUTH_FN = staticmethod(_api_key_query_headers)


class QdrantConnector(RestAdapterConnector):
    """Qdrant REST — base_url is the cluster address."""

    BASE = "http://localhost:6333"
    DEFAULT_KIND = "collections"
    PROBE_PATH = "/collections"
    RESOURCE_MAP = {"collections": "/collections", "cluster": "/cluster"}
    AUTH_FN = staticmethod(_api_key_query_headers)


class ChromaConnector(RestAdapterConnector):
    """Chroma REST — list collections."""

    BASE = "http://localhost:8000"
    DEFAULT_KIND = "collections"
    PROBE_PATH = "/api/v1/heartbeat"
    RESOURCE_MAP = {"collections": "/api/v1/collections"}


class WeaviateConnector(RestAdapterConnector):
    """Weaviate v1 REST."""

    BASE = ""  # base_url required, e.g. https://my-weaviate
    DEFAULT_KIND = "schema"
    PROBE_PATH = "/v1/meta"
    RESOURCE_MAP = {"schema": "/v1/schema", "objects": "/v1/objects"}


class MilvusConnector(RestAdapterConnector):
    """Milvus REST 2.x — list collections + databases."""

    BASE = ""  # base_url required
    DEFAULT_KIND = "collections"
    PROBE_PATH = "/v1/health"
    RESOURCE_MAP = {"collections": "/v1/vector/collections", "databases": "/v1/databases"}


class HuggingFaceConnector(RestAdapterConnector):
    BASE = "https://huggingface.co/api"
    DEFAULT_KIND = "models"
    PROBE_PATH = "/whoami-v2"
    RESOURCE_MAP = {"models": "/models", "datasets": "/datasets", "spaces": "/spaces"}


# ─── SQL / NoSQL extras ────────────────────────────────────────────────


class SupabaseConnector(RestAdapterConnector):
    """Supabase PostgREST — base_url is the project's postgrest endpoint.
    Auth is service-role JWT or anon key as bearer."""

    BASE = ""
    DEFAULT_KIND = ""
    RESOURCE_MAP = {}  # caller passes object_type=<table> directly

    async def get_metadata(self, config):
        return {"tables": []}

    async def execute_query(self, config, query):
        spec = self._parse(query)
        table = spec.get("object_type") or spec.get("table")
        if not table:
            raise ValueError("Supabase needs an object_type=<table>")
        url = f"{self._resolve_base(config)}/{table}"
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._headers(config))
            resp.raise_for_status()
            return resp.json() or []


class PlanetScaleConnector(RestAdapterConnector):
    """PlanetScale wraps MySQL — branches/databases via REST API."""

    BASE = "https://api.planetscale.com/v1"
    DEFAULT_KIND = "databases"
    PROBE_PATH = "/organizations"
    RESOURCE_MAP = {
        "databases": "/databases",
        "organizations": "/organizations",
    }
    DATA_KEY = "data"


class CockroachDBConnector(RestAdapterConnector):
    """CockroachDB Cloud — control-plane API."""

    BASE = "https://cockroachlabs.cloud/api/v1"
    DEFAULT_KIND = "clusters"
    PROBE_PATH = "/users"
    RESOURCE_MAP = {"clusters": "/clusters", "users": "/users"}


class TiDBConnector(RestAdapterConnector):
    """TiDB Cloud control plane."""

    BASE = "https://api.tidbcloud.com/api/v1beta"
    DEFAULT_KIND = "clusters"
    RESOURCE_MAP = {"clusters": "/clusters", "projects": "/projects"}


class FireboltConnector(RestAdapterConnector):
    BASE = "https://api.app.firebolt.io/web/v3"
    DEFAULT_KIND = "engines"
    RESOURCE_MAP = {"engines": "/engines", "databases": "/databases"}


class TeradataConnector(RestAdapterConnector):
    BASE = ""
    DEFAULT_KIND = "tables"
    RESOURCE_MAP = {"tables": "/tables", "databases": "/databases"}


class CassandraConnector(RestAdapterConnector):
    """Cassandra Stargate REST proxy — config["base_url"] = stargate URL."""

    BASE = ""
    DEFAULT_KIND = "keyspaces"
    PROBE_PATH = "/v2/schemas/keyspaces"
    RESOURCE_MAP = {"keyspaces": "/v2/schemas/keyspaces"}


class CouchbaseConnector(RestAdapterConnector):
    BASE = ""
    DEFAULT_KIND = "buckets"
    PROBE_PATH = "/pools"
    RESOURCE_MAP = {"buckets": "/pools/default/buckets", "pools": "/pools"}
    AUTH_FN = staticmethod(_basic_headers)


class CosmosDBConnector(RestAdapterConnector):
    """Cosmos DB — base_url is the account endpoint."""

    BASE = ""
    DEFAULT_KIND = "dbs"
    RESOURCE_MAP = {"dbs": "/dbs", "users": "/users"}


class DynamoDBConnector(RestAdapterConnector):
    """DynamoDB — list tables via the AWS REST endpoint. Real ops use
    the SigV4-signed POST /; this surface is a smoke-test shell that
    the production driver replaces."""

    BASE = "https://dynamodb.us-east-1.amazonaws.com"
    DEFAULT_KIND = "tables"
    RESOURCE_MAP = {"tables": "/?Action=ListTables"}


class Neo4jConnector(RestAdapterConnector):
    BASE = ""
    DEFAULT_KIND = "labels"
    PROBE_PATH = "/db/data/"
    RESOURCE_MAP = {"labels": "/db/data/labels"}
    AUTH_FN = staticmethod(_basic_headers)


class RedisConnector(RestAdapterConnector):
    """Redis Enterprise REST API."""

    BASE = ""
    DEFAULT_KIND = "bdbs"
    PROBE_PATH = "/v1/bdbs"
    RESOURCE_MAP = {"bdbs": "/v1/bdbs", "users": "/v1/users"}
    AUTH_FN = staticmethod(_basic_headers)


class DuckDBConnector(RestAdapterConnector):
    """DuckDB — file-based; this REST stub is for MotherDuck cloud."""

    BASE = "https://api.motherduck.com"
    DEFAULT_KIND = "databases"
    RESOURCE_MAP = {"databases": "/v1/databases"}


class PrestoConnector(RestAdapterConnector):
    """Presto coordinator REST."""

    BASE = ""
    DEFAULT_KIND = "catalog"
    PROBE_PATH = "/v1/info"
    RESOURCE_MAP = {"catalog": "/v1/catalog", "node": "/v1/node"}


class TrinoConnector(RestAdapterConnector):
    """Trino coordinator REST — same shape as Presto."""

    BASE = ""
    DEFAULT_KIND = "catalog"
    PROBE_PATH = "/v1/info"
    RESOURCE_MAP = {"catalog": "/v1/catalog", "node": "/v1/node"}


# ─── Warehouses ───────────────────────────────────────────────────────


class SingleStoreConnector(RestAdapterConnector):
    """SingleStore Cloud control-plane API."""

    BASE = "https://api.singlestore.com/v1"
    DEFAULT_KIND = "organizations"
    RESOURCE_MAP = {"organizations": "/organizations", "workspaces": "/workspaces"}


class AmazonAthenaConnector(RestAdapterConnector):
    """Athena REST stub — production driver wraps boto3."""

    BASE = "https://athena.us-east-1.amazonaws.com"
    DEFAULT_KIND = "workgroups"
    RESOURCE_MAP = {"workgroups": "/?Action=ListWorkGroups"}


class ApacheDruidConnector(RestAdapterConnector):
    """Druid REST coordinator."""

    BASE = ""
    DEFAULT_KIND = "datasources"
    PROBE_PATH = "/status"
    RESOURCE_MAP = {"datasources": "/druid/coordinator/v1/datasources"}


# ─── Marketing / Ads ──────────────────────────────────────────────────


class FacebookAdsConnector(RestAdapterConnector):
    BASE = "https://graph.facebook.com/v19.0"
    DEFAULT_KIND = "adaccounts"
    RESOURCE_MAP = {"adaccounts": "/me/adaccounts", "campaigns": "/me/campaigns"}


class FacebookPagesConnector(RestAdapterConnector):
    BASE = "https://graph.facebook.com/v19.0"
    DEFAULT_KIND = "accounts"
    RESOURCE_MAP = {"accounts": "/me/accounts", "posts": "/me/posts"}


class InstagramConnector(RestAdapterConnector):
    BASE = "https://graph.facebook.com/v19.0"
    DEFAULT_KIND = "media"
    RESOURCE_MAP = {"media": "/me/media", "accounts": "/me/accounts"}


class LinkedInPagesConnector(RestAdapterConnector):
    BASE = "https://api.linkedin.com/v2"
    DEFAULT_KIND = "organizations"
    RESOURCE_MAP = {"organizations": "/organizations", "shares": "/shares"}


class GoogleAdsConnector(RestAdapterConnector):
    """Google Ads — config["customer_id"] threaded into the path; the
    production driver uses gRPC. This REST stub covers metadata."""

    BASE = "https://googleads.googleapis.com/v15"
    DEFAULT_KIND = "customers"
    RESOURCE_MAP = {"customers": "/customers"}
