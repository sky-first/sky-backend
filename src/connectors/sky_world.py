"""Conector ``sky-world``: a ligação gerida «Dados públicos».

Herda do Postgres. Duas diferenças, e são ambas de segurança:

1. **Sem password na config.** A config só traz ``credential_ref``; a
   password resolve-se em ``credenciais.ler`` — e só se a referência for
   a do cliente em contexto (S15). Uma ligação re-apontada para o segredo
   de outro cliente rebenta aqui, antes de se pedir o segredo.
2. **Host, base e esquema vêm das settings, não da config.** Um PUT que
   mudasse o host para um servidor do atacante levaria a nossa
   credencial para lá. A config não manda nisso; e as mutações de uma
   ligação do sistema já dão 403 antes de chegar aqui.

A descoberta herda o filtro por privilégios do conector Postgres
(``has_table_privilege``): só aparecem as tabelas das fontes activas (S3).
"""

from __future__ import annotations

from typing import Any, Dict

from src.config.settings import settings
from src.connectors.postgresql import PostgreSQLConnector


def _slug_em_contexto() -> str | None:
    from src.core.tenant_context import current_tenant

    ctx = current_tenant()
    if ctx is None or ctx.is_default:
        return None
    return ctx.slug


class SkyWorldConnector(PostgreSQLConnector):
    """Postgres em ``sky_world``, com o papel só-leitura do cliente."""

    def _get_connection_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        from src.services.fontes_sistema import credenciais

        ref = credenciais.validar_ref(config.get("credential_ref"), _slug_em_contexto())
        utilizador, password = credenciais.ler(ref)
        efectiva = {
            "host": settings.WORLD_DB_HOST,
            "port": settings.WORLD_DB_PORT,
            "database": settings.WORLD_DB_NAME,
            "username": utilizador,
            "password": password,
            "ssl_mode": settings.WORLD_SSL_MODE,
            "timeout": 10.0,
        }
        return super()._get_connection_params(efectiva)

    def _schema(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {**config, "schema": settings.WORLD_SCHEMA}

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return await super().get_metadata(self._schema(config))

    async def execute_query(self, config: Dict[str, Any], query: str):
        return await super().execute_query(self._schema(config), query)
