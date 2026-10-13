"""A ligação «Dados públicos» na base do CLIENTE.

Tudo aqui corre com uma sessão da base do cliente, dentro de
``contexto_do_cliente(slug)``. Nada aqui lê o contextvar para decidir a que
cliente fala com o sky-ai: o slug chega por argumento (S1).

- Uma ligação por cliente (``sistema = true``, ``connector_id = sky-world``),
  criada pelo **utilizador de sistema** — não por um admin humano, cujo
  apagamento levava a ligação atrás pelo ``ON DELETE CASCADE`` (S16).
- Em **todos** os projectos do cliente, incluindo os que se criarem depois
  (decisão do Lucas, 13/10/2026).
- ``space_tables`` = exactamente as tabelas das fontes activas + ``fontes``
  (licença e hora do dado). Com ``DATA_BOUNDARY=project`` é isto que torna
  uma tabela perguntável.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.connection import ConnectionMetadata, DataConnection
from src.models.space import Space, SpaceConnection, SpaceTable
from src.models.user import User
from src.services.fontes_sistema import credenciais
from src.services.fontes_sistema.catalogo import CONECTOR, TABELA_FRESCURA, nome_da_ligacao

logger = logging.getLogger(__name__)

#: O dono da ligação gerida. Sem login (``status = sistema`` é recusado no
#: login), escondido das listas de utilizadores, não apagável.
# Um subdomínio nosso que não recebe correio (um TLD `.invalid` é recusado
# pelos validadores de email das respostas).
EMAIL_SISTEMA = "dados-publicos@sistema.skyfirstlabs.com"
ESTADO_SISTEMA = "sistema"


async def garantir_utilizador_de_sistema(db: AsyncSession) -> User:
    u = (await db.execute(select(User).where(User.email == EMAIL_SISTEMA))).scalar_one_or_none()
    if u is not None:
        if u.status != ESTADO_SISTEMA:
            u.status = ESTADO_SISTEMA
        if getattr(u, "deleted_at", None) is not None:
            u.deleted_at = None
        return u
    from src.core.security import get_password_hash

    u = User(
        email=EMAIL_SISTEMA,
        # Password aleatória que ninguém conhece; o login recusa antes de a ver.
        password_hash=get_password_hash(secrets.token_urlsafe(32)),
        name="Sky — dados públicos",
        role="member",
        status=ESTADO_SISTEMA,
        email_verified=True,
        has_completed_onboarding=True,
    )
    db.add(u)
    await db.flush()
    return u


def _config(slug: str) -> dict:
    from src.utils.encryption import encrypt_dict

    # Sem password: só a referência ao segredo. Host/base/esquema estão aqui
    # para quem lê a config (sky-ai), mas o conector do backend ignora-os e
    # usa as settings (um PUT não consegue re-apontar a ligação).
    return encrypt_dict(
        {
            "credential_ref": credenciais.ref_do_cliente(slug),
            "host": settings.WORLD_DB_HOST,
            "port": settings.WORLD_DB_PORT,
            "database": settings.WORLD_DB_NAME,
            "schema": settings.WORLD_SCHEMA,
            "ssl_mode": settings.WORLD_SSL_MODE,
        }
    )


async def ligacao_do_sistema(db: AsyncSession) -> Optional[DataConnection]:
    return (
        await db.execute(
            select(DataConnection).where(
                DataConnection.sistema.is_(True), DataConnection.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def garantir_ligacao(
    db: AsyncSession, slug: str, dono: User, lingua: Optional[str] = None
) -> DataConnection:
    """A ligação gerida, criada se faltar. NÃO passa pelo limite do plano."""
    c = await ligacao_do_sistema(db)
    if c is None:
        c = DataConnection(
            name=nome_da_ligacao(lingua),
            connector_id=CONECTOR,
            description="Gerida pela Sky. Dados públicos activados na Consola.",
            config=_config(slug),
            status="inactive",
            tier="internal",
            nao_cruzavel=False,
            sistema=True,
            created_by=dono.id,
        )
        db.add(c)
        await db.flush()
        return c
    # Converge: dono, conector e referência certos, mesmo que alguém tenha
    # mexido na linha à mão.
    c.created_by = dono.id
    c.connector_id = CONECTOR
    c.config = _config(slug)
    return c


async def projetos(db: AsyncSession) -> List[Space]:
    return list((await db.execute(select(Space).where(Space.deleted_at.is_(None)))).scalars().all())


async def garantir_nos_projetos(db: AsyncSession, ligacao_id: UUID, spaces: Iterable[Space]) -> int:
    ja = set(
        (
            await db.execute(
                select(SpaceConnection.space_id).where(SpaceConnection.connection_id == ligacao_id)
            )
        )
        .scalars()
        .all()
    )
    novos = 0
    for s in spaces:
        if s.id not in ja:
            db.add(SpaceConnection(space_id=s.id, connection_id=ligacao_id))
            novos += 1
    await db.flush()
    return novos


async def acertar_tabelas(
    db: AsyncSession, ligacao_id: UUID, spaces: Iterable[Space], desejadas: Iterable[str]
) -> Set[str]:
    """``space_tables`` = ``desejadas`` em cada projecto. Devolve as que saíram."""
    esquema = settings.WORLD_SCHEMA
    alvo = set(desejadas)
    removidas: Set[str] = set()
    for s in spaces:
        linhas = (
            (
                await db.execute(
                    select(SpaceTable).where(
                        SpaceTable.space_id == s.id, SpaceTable.connection_id == ligacao_id
                    )
                )
            )
            .scalars()
            .all()
        )
        presentes = {l.table_name for l in linhas}
        for l in linhas:
            if l.table_name not in alvo:
                removidas.add(l.table_name)
                await db.delete(l)
        for t in sorted(alvo - presentes):
            db.add(
                SpaceTable(
                    space_id=s.id, connection_id=ligacao_id, table_name=t, schema_name=esquema
                )
            )
    await db.flush()
    return removidas


async def _existe(db: AsyncSession, tabela: str) -> bool:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return False
    return (await db.execute(text("SELECT to_regclass(:t)"), {"t": tabela})).scalar() is not None


async def limpar_indice(db: AsyncSession, ligacao_id: UUID, removidas: Set[str]) -> None:
    """Tira do índice da IA as tabelas que saíram (L4, do lado do backend).

    O discover do sky-ai acrescenta; não sabemos se apaga. Apagar aqui as
    linhas de ``table_metadata``/``embeddings`` dessas tabelas fecha a porta
    sem depender disso. Só onde as tabelas existem (bases antigas não as
    têm).
    """
    if not removidas:
        return
    nomes = sorted(removidas | {f"{settings.WORLD_SCHEMA}.{t}" for t in removidas})
    if await _existe(db, "embeddings") and await _existe(db, "table_metadata"):
        await db.execute(
            text(
                "DELETE FROM embeddings WHERE table_metadata_id IN (SELECT id FROM table_metadata "
                "WHERE data_connection_id = :c AND table_name = ANY(:n))"
            ),
            {"c": ligacao_id, "n": nomes},
        )
    if await _existe(db, "table_metadata"):
        await db.execute(
            text(
                "DELETE FROM table_metadata WHERE data_connection_id = :c AND table_name = ANY(:n)"
            ),
            {"c": ligacao_id, "n": nomes},
        )


async def invalidar_cache_semantica(db: AsyncSession) -> int:
    """Apaga as respostas guardadas do cliente (S7, L5).

    A cache semântica não tem índice por tabela; uma resposta mista (dados
    do cliente + públicos) fica guardada debaixo da ligação do cliente. No
    MVP limpa-se a cache inteira do cliente ao desligar uma fonte — custa
    umas perguntas mais lentas, e não se responde com dados de uma fonte
    que o cliente já não tem.
    """
    if not await _existe(db, "semantic_cache"):
        return 0
    r = await db.execute(text("DELETE FROM semantic_cache"))
    return int(getattr(r, "rowcount", 0) or 0)


async def sincronizar_metadados(db: AsyncSession, ligacao: DataConnection) -> List[str]:
    """Lê o catálogo de ``sky_world`` com o papel do cliente (filtrado por privilégio)."""
    from src.connectors.registry import get_connector
    from src.utils.encryption import decrypt_dict

    meta = await get_connector(CONECTOR).get_metadata(decrypt_dict(ligacao.config))
    tabelas = meta.get("tables", []) or []
    agora = datetime.now(timezone.utc)
    existente = (
        await db.execute(
            select(ConnectionMetadata).where(ConnectionMetadata.connection_id == ligacao.id)
        )
    ).scalar_one_or_none()
    if existente is None:
        db.add(
            ConnectionMetadata(
                connection_id=ligacao.id,
                tables=tabelas,
                schemas=meta.get("schemas", []),
                last_metadata_update=agora,
            )
        )
    else:
        existente.tables = tabelas
        existente.schemas = meta.get("schemas", [])
        existente.last_metadata_update = agora
    ligacao.last_sync = agora
    ligacao.last_metadata_update = agora
    ligacao.status = "active"
    ligacao.error = None
    await db.flush()
    return [t.get("name") for t in tabelas if isinstance(t, dict) and t.get("name")]


async def desligar(db: AsyncSession, ligacao: DataConnection) -> None:
    """Sem fontes activas: a ligação fica, sem tabelas e inactiva (histórico)."""
    ligacao.status = "inactive"
    await db.execute(
        delete(ConnectionMetadata).where(ConnectionMetadata.connection_id == ligacao.id)
    )
    await db.flush()


async def descobrir(
    ligacao_id: UUID, spaces: Iterable[Space], slug: str, tabelas: List[str]
) -> Dict[str, str]:
    """Discover síncrono por projecto, com ``X-Tenant-Slug`` explícito. Devolve falhas."""
    from src.ai.http_client import AIServiceHTTPClient

    cliente = AIServiceHTTPClient()
    falhas: Dict[str, str] = {}
    for s in spaces:
        try:
            await cliente.discover_connection(
                connection_id=str(ligacao_id),
                space_id=str(s.id),
                run_in_background=False,
                table_names=tabelas or None,
                tenant_slug=slug,
            )
        except Exception as exc:  # noqa: BLE001
            falhas[str(s.id)] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return falhas


async def tem_ligacao_do_sistema(db: AsyncSession) -> bool:
    return await ligacao_do_sistema(db) is not None


async def ligar_projeto_novo(db: AsyncSession, space_id: UUID) -> bool:
    """Hook da criação de projecto (S13): o projecto novo herda «Dados públicos».

    Copia as tabelas que os outros projectos já têm desta ligação e devolve
    ``True`` se ligou alguma coisa — quem chama enfileira a convergência
    para o discover do projecto novo.
    """
    if not settings.FONTES_SISTEMA_ENABLED:
        return False
    c = await ligacao_do_sistema(db)
    if c is None or c.status != "active":
        return False
    tabelas = set(
        (
            await db.execute(
                select(SpaceTable.table_name).where(SpaceTable.connection_id == c.id).distinct()
            )
        )
        .scalars()
        .all()
    )
    if not tabelas:
        return False
    space = await db.get(Space, space_id)
    if space is None:
        return False
    await garantir_nos_projetos(db, c.id, [space])
    await acertar_tabelas(db, c.id, [space], tabelas)
    return True


__all__ = [
    "EMAIL_SISTEMA",
    "TABELA_FRESCURA",
    "acertar_tabelas",
    "descobrir",
    "desligar",
    "garantir_ligacao",
    "garantir_nos_projetos",
    "garantir_utilizador_de_sistema",
    "invalidar_cache_semantica",
    "ligacao_do_sistema",
    "ligar_projeto_novo",
    "limpar_indice",
    "projetos",
    "sincronizar_metadados",
]
