"""A fronteira na própria base de dados: papéis e GRANT/REVOKE em ``sky_world``.

Corre com o papel ``world_admin`` (``WORLD_ADMIN_DSN``): ``CREATEROLE`` e
mais nada. Não é dono das tabelas; recebe ``SELECT … WITH GRANT OPTION``
nas tabelas do esquema ``mundo`` pelos privilégios por omissão que o
bootstrap (``scripts/fontes_sistema/bootstrap_sky_world.py``) põe no
``world_loader``. É isso que lhe permite dar ``SELECT`` a cada ``wsrc_*``.

- ``wsrc_<fonte>`` — NOLOGIN, ``SELECT`` nas tabelas da fonte + ``fontes``.
- ``wt_<slug>``    — LOGIN, só leitura, ``CONNECTION LIMIT 5``, timeouts.
  Marcar uma fonte = ``GRANT wsrc_x TO wt_slug``; desmarcar = ``REVOKE``.
  O que o cliente não activou, o Postgres recusa (S2), mesmo que o
  validador de SQL do sky-ai falhe.

Os nomes vão para SQL como identificadores (não se passam por parâmetro):
passam todos por ``_ident``, que só aceita ``[a-z_][a-z0-9_]*``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, Iterable, List, Optional, Set

from src.config.settings import settings
from src.services.fontes_sistema import credenciais
from src.services.fontes_sistema.catalogo import (
    TABELA_FRESCURA,
    TABELAS_PROIBIDAS,
    papel_da_fonte,
    papel_do_cliente,
)

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PASSWORD = re.compile(r"^[A-Za-z0-9_\-]{16,128}$")

#: Limites do papel de cada cliente (S18): um cliente não derruba os outros.
CONFIG_DO_PAPEL = {
    "default_transaction_read_only": "on",
    "statement_timeout": "15s",
    "idle_in_transaction_session_timeout": "30s",
    "work_mem": "16MB",
}
LIMITE_DE_LIGACOES = 5


class MundoIndisponivelError(RuntimeError):
    """Sem ``WORLD_ADMIN_DSN``, ou a base ``sky_world`` não responde."""


def _ident(nome: str) -> str:
    if not nome or not _IDENT.match(nome):
        raise ValueError(f"identificador recusado: {nome!r}")
    return f'"{nome}"'


def _literal_password(pw: str) -> str:
    if not _PASSWORD.match(pw or ""):
        raise ValueError("password com caracteres não permitidos")
    return "'" + pw.replace("'", "''") + "'"


class Mundo:
    """Operações do ``world_admin``. Abre uma ligação; usar com ``async with``."""

    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn if dsn is not None else settings.WORLD_ADMIN_DSN
        self._conn = None
        self.esquema = settings.WORLD_SCHEMA
        self.base = settings.WORLD_DB_NAME

    async def __aenter__(self) -> "Mundo":
        if not self._dsn:
            raise MundoIndisponivelError("WORLD_ADMIN_DSN não está definido")
        import asyncpg

        try:
            self._conn = await asyncpg.connect(dsn=self._dsn, timeout=10)
        except Exception as exc:  # noqa: BLE001
            # A mensagem do asyncpg pode trazer o DSN; não a propagamos.
            raise MundoIndisponivelError(
                f"não consegui ligar à base sky_world ({type(exc).__name__})"
            ) from None
        return self

    async def __aexit__(self, *exc) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── leitura ────────────────────────────────────────────────────────

    async def papel_existe(self, nome: str) -> bool:
        _ident(nome)
        return bool(await self._conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", nome))

    async def tabelas_existentes(self) -> Set[str]:
        linhas = await self._conn.fetch(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = $1 AND c.relkind IN ('r', 'v', 'm', 'p')",
            self.esquema,
        )
        return {r["relname"] for r in linhas}

    async def tabelas_concedidas(self, papel: str) -> Set[str]:
        linhas = await self._conn.fetch(
            "SELECT table_name FROM information_schema.role_table_grants "
            "WHERE grantee = $1 AND table_schema = $2 AND privilege_type = 'SELECT'",
            papel,
            self.esquema,
        )
        return {r["table_name"] for r in linhas}

    async def fontes_do_cliente(self, slug: str) -> Set[str]:
        """Os ``wsrc_*`` de que ``wt_<slug>`` é membro, sem o prefixo."""
        papel = papel_do_cliente(slug)
        linhas = await self._conn.fetch(
            "SELECT r.rolname FROM pg_auth_members m "
            "JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
            "WHERE u.rolname = $1 AND r.rolname LIKE 'wsrc\\_%'",
            papel,
        )
        return {r["rolname"][len("wsrc_") :] for r in linhas}

    async def papeis_de_clientes(self) -> Set[str]:
        linhas = await self._conn.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE 'wt\\_%'")
        return {r["rolname"] for r in linhas}

    async def frescura(self) -> Dict[str, dict]:
        """``mundo.fontes`` por nome do carregador. Vazio se a tabela ainda não existe."""
        try:
            linhas = await self._conn.fetch(
                f"SELECT nome, estado, dado_de, ultima_actualizacao, linhas, erro, "  # nosec B608
                f"uso_comercial, licenca FROM {_ident(self.esquema)}.{_ident(TABELA_FRESCURA)}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fontes_sistema: frescura indisponível: %s", type(exc).__name__)
            return {}
        return {r["nome"]: dict(r) for r in linhas}

    # ── escrita ────────────────────────────────────────────────────────

    async def garantir_papel_da_fonte(self, fonte_id: str, tabelas: Iterable[str]) -> List[str]:
        """Cria ``wsrc_<fonte>`` e acerta-lhe os SELECT. Devolve as tabelas em falta.

        Reconcilia nos dois sentidos: dá SELECT ao que a fonte diz e tira
        a qualquer outra tabela do esquema (uma tabela tirada do catálogo
        deixa de ser lida no minuto seguinte).
        """
        papel = papel_da_fonte(fonte_id)
        p = _ident(papel)
        esq = _ident(self.esquema)
        if not await self.papel_existe(papel):
            await self._conn.execute(f"CREATE ROLE {p} NOLOGIN")
        await self._conn.execute(f"GRANT USAGE ON SCHEMA {esq} TO {p}")

        desejadas = {t for t in tabelas if t not in TABELAS_PROIBIDAS} | {TABELA_FRESCURA}
        existentes = await self.tabelas_existentes()
        em_falta = sorted(t for t in desejadas if t not in existentes and t != TABELA_FRESCURA)
        for t in sorted(desejadas & existentes):
            await self._conn.execute(f"GRANT SELECT ON {esq}.{_ident(t)} TO {p}")
        for t in sorted(await self.tabelas_concedidas(papel)):
            if t not in desejadas:
                await self._conn.execute(f"REVOKE ALL ON {esq}.{_ident(t)} FROM {p}")
        return em_falta

    async def garantir_papel_do_cliente(self, slug: str) -> None:
        """Cria ``wt_<slug>`` com password no cofre, ou confirma a que lá está.

        A password só muda se o segredo não existir ou não abrir a porta:
        a verificação é um login a sério com ela.
        """
        papel = papel_do_cliente(slug)
        p = _ident(papel)
        ref = credenciais.ref_do_cliente(slug)
        existe = await self.papel_existe(papel)

        if existe and await self._login_funciona(ref):
            pass
        else:
            password = credenciais.nova_password(slug)
            lit = _literal_password(password)
            if existe:
                await self._conn.execute(f"ALTER ROLE {p} WITH LOGIN PASSWORD {lit}")
            else:
                await self._conn.execute(
                    f"CREATE ROLE {p} WITH LOGIN INHERIT NOCREATEDB NOCREATEROLE "
                    f"CONNECTION LIMIT {LIMITE_DE_LIGACOES} PASSWORD {lit}"
                )
            credenciais.guardar(ref, papel, password)

        await self._conn.execute(f"ALTER ROLE {p} CONNECTION LIMIT {LIMITE_DE_LIGACOES}")
        for k, v in CONFIG_DO_PAPEL.items():
            await self._conn.execute(f"ALTER ROLE {p} SET {k} = '{v}'")
        await self._conn.execute(f"GRANT CONNECT ON DATABASE {_ident(self.base)} TO {p}")

    async def _login_funciona(self, ref: str) -> bool:
        try:
            utilizador, password = credenciais.ler(ref, sem_cache=True)
        except Exception:  # noqa: BLE001 — segredo ausente: roda-se
            return False
        import asyncpg

        try:
            c = await asyncpg.connect(
                host=settings.WORLD_DB_HOST,
                port=settings.WORLD_DB_PORT,
                user=utilizador,
                password=password,
                database=self.base,
                ssl=None if settings.WORLD_SSL_MODE == "disable" else "require",
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            return False
        await c.close()
        return True

    async def _com_lock_curto(self, sql: str) -> None:
        """GRANT/REVOKE com ``lock_timeout`` de 5 s e três tentativas."""
        ultimo: Optional[Exception] = None
        for tentativa in range(3):
            try:
                async with self._conn.transaction():
                    await self._conn.execute("SET LOCAL lock_timeout = '5s'")
                    await self._conn.execute(sql)
                return
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                await asyncio.sleep(0.5 * (tentativa + 1))
        raise ultimo  # type: ignore[misc]

    async def conceder(self, fonte_id: str, slug: str) -> None:
        await self._com_lock_curto(
            f"GRANT {_ident(papel_da_fonte(fonte_id))} TO {_ident(papel_do_cliente(slug))}"
        )

    async def revogar(self, fonte_id: str, slug: str) -> None:
        await self._com_lock_curto(
            f"REVOKE {_ident(papel_da_fonte(fonte_id))} FROM {_ident(papel_do_cliente(slug))}"
        )

    async def remover_cliente(self, slug: str) -> None:
        """Destruição do cliente (S20): sem membros, sem CONNECT, sem papel."""
        papel = papel_do_cliente(slug)
        if not await self.papel_existe(papel):
            return
        for fonte in await self.fontes_do_cliente(slug):
            await self.revogar(fonte, slug)
        p = _ident(papel)
        await self._conn.execute(f"REVOKE ALL ON DATABASE {_ident(self.base)} FROM {p}")
        await self._conn.execute(f"DROP ROLE IF EXISTS {p}")
