"""REST API connector.

First real non-SQL data source (Bug 5). Lets the user register a
generic HTTP endpoint as a "connection" so the rest of the platform
(agents, chat, dashboards) can treat it the same way it treats a
database.

Contract:
    config = {
        "base_url": "https://api.example.com",
        "headers": { "Authorization": "Bearer ..." },   # optional
        "auth": { "type": "bearer" | "basic" | "apikey" | "none",
                  "token": "...",          # bearer / apikey
                  "username": "...",       # basic
                  "password": "...",       # basic
                  "header_name": "X-API-Key",    # apikey
                  "in": "header" | "query", "param_name": "key" },
        # What the web form saves (same meaning, see _api_payload.resolve_auth):
        "auth_type": "none" | "api_key" | "bearer_token" | "basic_auth",
        "auth_header": "X-API-Key" | "?key",   # "?key" = query string
        "auth_value": "...",
        "records_path": "ListaEESSPrecio",     # optional, where the list is
        "endpoints": [
            { "name": "orders", "path": "/orders", "method": "GET",
              "records_path": "data.items" }   # optional per endpoint
        ]   # optional — acts as the "tables" list
    }

    execute_query(config, query) — ``query`` is a JSON-encoded dict
    ``{"path": "/orders", "method": "GET", "params": {...}, "body": {...}}``
    or a plain path string. Returns a list of dicts (normalised from
    the JSON response).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors._api_payload import (
    json_records,
    parse_records,
    records_path_for,
    redact,
    resolve_auth,
)
from src.connectors.base import BaseConnector
from src.security.url_allowlist import UnsafeURLError, validate_outbound_url

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 15.0


def _build_auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    """Normalise the auth config into a request header dict."""
    return resolve_auth(config)[0]


def _auth_params(config: Dict[str, Any]) -> Dict[str, str]:
    """API key that goes in the query string (TomTom ``?key=``)."""
    return resolve_auth(config)[1]


def _basic_auth_tuple(config: Dict[str, Any]) -> Optional[tuple[str, str]]:
    return resolve_auth(config)[2]


def _secrets(config: Dict[str, Any]) -> List[str]:
    return resolve_auth(config)[3]


async def _request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    basic: Optional[tuple[str, str]],
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(
            method.upper(),
            url,
            headers=headers,
            auth=basic,
            params=params,
            json=body if body is not None else None,
        )


class RestAPIConnector(BaseConnector):
    """Treat an HTTP endpoint like a data source."""

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        base_url = (config.get("base_url") or "").rstrip("/")
        if not base_url:
            return False
        # Defence in depth: the schema validator already rejects
        # IMDS / internal / non-HTTP schemes at create time, but a row
        # persisted before this landed could still hold a dangerous
        # URL. Re-validate at fetch time so an old row cannot suddenly
        # SSRF when someone exercises the connection.
        try:
            validate_outbound_url(base_url)
        except UnsafeURLError as exc:
            logger.warning("rest_api blocked unsafe base_url %s: %s", base_url, exc)
            return False
        secrets = _secrets(config)
        has_credentials = bool(secrets or _basic_auth_tuple(config))
        # Sonda-se o primeiro endpoint GET declarado sem {marcadores}: é lá
        # que a chave é verificada (a raiz do AEMET responde sem chave; a do
        # DGT dá 403 a qualquer um porque não lista a pasta).
        probe_url = base_url
        for ep in config.get("endpoints") or []:
            path = str(ep.get("path") or "")
            if path and "{" not in path and (ep.get("method") or "GET").upper() == "GET":
                probe_url = f"{base_url}{path if path.startswith('/') else '/' + path}"
                break
        try:
            resp = await _request(
                "GET",
                probe_url,
                headers=_build_auth_headers(config),
                basic=_basic_auth_tuple(config),
                params=_auth_params(config) or None,
            )
            code = resp.status_code
            # 401 = credenciais recusadas (antes contava como «acessível» e o
            # AEMET sem chave passava — Anexo C, D6). 403 também, quando se sondou um
            # endpoint ou há credenciais; na raiz nua, sem credenciais, é só
            # «não se lista esta pasta».
            refused = code == 401 or (code == 403 and (probe_url != base_url or has_credentials))
            if refused:
                logger.info(
                    "rest_api test_connection: %s recusou as credenciais (%s)", base_url, code
                )
                return False
            # 2xx / 3xx / 400 / 404 mean "reachable" — many API roots
            # redirect, have nothing at "/" or want parameters. 5xx is what
            # we treat as "server is sick".
            return code < 500
        except Exception as exc:
            logger.info(
                "rest_api test_connection failed for %s: %s", base_url, redact(exc, secrets)
            )
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Expose user-declared endpoints as "tables".

        We don't crawl the API — most aren't OpenAPI-typed and probing
        is brittle. The user declares endpoints at registration time;
        the RAG treats each endpoint as a table-like artifact so agents
        can pick specific ones via DataSourcePicker.
        """
        endpoints = config.get("endpoints") or []
        tables: List[Dict[str, Any]] = []
        for ep in endpoints:
            name = ep.get("name") or ep.get("path") or "endpoint"
            tables.append(
                {
                    "name": name,
                    "columns": [],  # unknown until first response; RAG will learn.
                    "kind": "rest_endpoint",
                    "metadata": {
                        "path": ep.get("path") or "/",
                        "method": (ep.get("method") or "GET").upper(),
                        "description": ep.get("description") or "",
                        **({"records_path": ep["records_path"]} if ep.get("records_path") else {}),
                    },
                }
            )
        return {"tables": tables, "schemas": []}

    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Run the query.

        `query` may be:
          - a plain path string ("/orders")
          - a JSON string describing method / path / params / body
        The response is normalised to a list of dicts. Arrays pass
        through; single objects become a 1-element list; non-JSON
        responses become [{"text": "..."}] so downstream code always
        sees a tabular shape.
        """
        base_url = (config.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ValueError("REST API connector requires base_url")
        # Same runtime check as test_connection — see note there.
        try:
            validate_outbound_url(base_url)
        except UnsafeURLError as exc:
            raise ValueError(f"REST API base_url rejected: {exc}")

        method = "GET"
        path = ""
        params: Optional[Dict[str, Any]] = None
        body: Optional[Dict[str, Any]] = None

        q = (query or "").strip()
        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                method = (parsed.get("method") or "GET").upper()
                path = parsed.get("path") or ""
                params = parsed.get("params")
                body = parsed.get("body")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid REST query JSON: {exc}") from exc
        else:
            path = q

        url = f"{base_url}{path if path.startswith('/') else '/' + path}" if path else base_url

        auth_params = _auth_params(config)
        if auth_params:
            # A chave da ligação ganha a qualquer valor vindo da pergunta.
            params = {**(params or {}), **auth_params}
        secrets = _secrets(config)

        resp = await _request(
            method,
            url,
            headers=_build_auth_headers(config),
            basic=_basic_auth_tuple(config),
            params=params,
            body=body,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if secrets and any(sec in str(exc) for sec in secrets):
                # O httpx põe o URL (com ``?key=``) na mensagem.
                raise ValueError(redact(exc, secrets)) from None
            raise

        # JSON, XML (DGT DATEX2) e CSV (BCE SDMX) viram linhas; a lista
        # principal é encontrada sozinha (MITECO ``ListaEESSPrecio``) ou
        # indicada por ``records_path`` (Anexo C, D3).
        content_type = (resp.headers.get("content-type") or "").lower()
        rp = records_path_for(config, path)
        if "json" in content_type:
            try:
                return json_records(resp.json(), rp)
            except json.JSONDecodeError:
                pass  # Content-Type a mentir: decide pelo conteúdo.
        raw = getattr(resp, "content", None)
        if not isinstance(raw, (bytes, str)) or not raw:
            raw = resp.text or ""
        return parse_records(raw, content_type, rp)

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """For APIs, sync == ping every declared endpoint and surface
        row counts. Keeps the same contract as SQL connectors so the
        scheduler doesn't need to special-case REST.

        Nota (Anexo C, D5): ``connections.sync_frequency`` é gravado e o
        ``next_sync`` calculado, mas nenhuma tarefa do Beat o lê — este
        método só corre a pedido e não guarda linhas. As respostas às
        perguntas são sempre ao vivo.
        """
        rows_by_endpoint: Dict[str, int] = {}
        for ep in config.get("endpoints") or []:
            try:
                result = await self.execute_query(config, ep.get("path") or "/")
                rows_by_endpoint[ep.get("name") or ep.get("path") or "endpoint"] = len(result)
            except Exception as exc:
                logger.warning("REST sync — endpoint %s failed: %s", ep, exc)
                rows_by_endpoint[ep.get("name") or "endpoint"] = 0
        return {"success": True, "rows_by_endpoint": rows_by_endpoint}
