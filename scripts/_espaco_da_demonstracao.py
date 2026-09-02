"""Encontra o espaço de demonstração — e deduz o dono a partir dele.

Os scripts de demonstração procuravam primeiro uma conta fixa,
``rbac.owner@example.com``, e só depois os espaços dela. Essa conta é da
base de demonstração local; na base do cliente ``sandbox`` não existe, e
os scripts paravam com

    Owner rbac.owner@example.com not found — run seed_demo_connections.py first

O `seed_demo_connections.py` já tinha contornado isto com um
``DEMO_OWNER_EMAIL``, mas uma variável de ambiente só empurra o problema:
alguém tem de saber qual é a conta certa, e ela muda de cliente para
cliente. No ``sandbox`` os quatro espaços têm **dois** criadores
diferentes.

A ordem certa é a inversa. O que se procura é o espaço; o dono é uma
consequência dele. Assim funciona em qualquer base, sem configuração.
"""

from __future__ import annotations


class EspacoNaoEncontrado(RuntimeError):
    """Não há espaço de demonstração nesta base."""


def _e_de_demonstracao(nome: str | None) -> bool:
    """`Demo — Sky`, `Demo - Sky`, `Demo Sky` — todas as variantes vistas.

    O travessão longo e o curto aparecem os dois no historico, e no
    ``sandbox`` o espaco chama-se `Demo Sky`, sem nenhum deles.
    """
    return bool(nome) and nome.startswith("Demo") and "Sky" in nome


async def espaco_e_dono(db):
    """(espaço, dono) da demonstração, pela ordem certa.

    Levanta ``EspacoNaoEncontrado`` em vez de devolver o primeiro espaço
    que aparecer: semear no espaço errado é pior do que não semear, e
    passaria despercebido.
    """
    from sqlalchemy import select

    from src.models.space import Space
    from src.models.user import User

    espacos = (await db.execute(select(Space))).scalars().all()
    espaco = next((e for e in espacos if _e_de_demonstracao(e.name)), None)
    if espaco is None:
        nomes = ", ".join(repr(e.name) for e in espacos) or "nenhum"
        raise EspacoNaoEncontrado(
            f"não há espaço de demonstração nesta base (espaços: {nomes}). "
            f"Se estás à espera do cliente e não da plataforma, falta o TENANT_SLUG."
        )

    dono = (await db.execute(select(User).where(User.id == espaco.created_by))).scalar_one_or_none()
    if dono is None:
        raise EspacoNaoEncontrado(
            f"o espaço {espaco.name!r} aponta para um criador que não existe "
            f"({espaco.created_by}) — a base está inconsistente."
        )

    return espaco, dono


async def ligacoes_da_base(db):
    """Todas as ligações vivas.

    **Sem filtrar pelo criador**, de propósito. Numa base de cliente todas
    as ligações são desse cliente, e filtrar pelo dono do espaço perdia as
    que outra pessoa da equipa tivesse criado — que foi o que aconteceu no
    ``sandbox``, onde os espaços têm dois criadores diferentes.
    """
    from sqlalchemy import select

    from src.models.connection import DataConnection

    return (
        (await db.execute(select(DataConnection).where(DataConnection.deleted_at.is_(None))))
        .scalars()
        .all()
    )
