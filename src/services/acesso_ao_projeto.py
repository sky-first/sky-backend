"""Quem alcança um projeto, e com que papel — **num sítio só**.

> *"Um projeto de operação com gente de operação não pode ver dados
> financeiros."* — Lucas, 26/08/2026

Esta é a única resposta a essa pergunta em toda a base. Nenhum chamador
calcula acesso por si: foi por não ser assim que nasceu o #634, e é a premissa
de segurança do produto — **a nossa aplicação É o perímetro**, porque nos
ligamos às fontes do cliente com uma credencial única e não há uma segunda
rede por baixo a validar por pessoa.

O acesso a um projeto vem de duas origens, e é isso que muda tudo:

* **directo** — a pessoa está em ``space_members``
* **por equipa** — a pessoa está numa equipa que ``space_crews`` ligou ao
  projeto, com um papel

Quem tem as duas fica com o **papel mais forte**. É o que o Jira faz; a
alternativa (o mais fraco) leva a acessos que desaparecem por razões que
ninguém consegue explicar.

Ver ``docs/pessoas-equipas-e-projetos.md`` §3 e §4.2.
"""

import logging
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import Crew, CrewMember
from src.models.space import Space, SpaceMember
from src.models.space_crew import SpaceCrew

logger = logging.getLogger(__name__)

#: Por ordem de poder. O índice é a força: comparar papéis é comparar índices.
PAPEIS = ["viewer", "editor", "owner"]


def papel_mais_forte(*papeis: Optional[str]) -> Optional[str]:
    """O maior de vários papéis. ``None`` quando não há nenhum.

    Papéis desconhecidos contam como o mais fraco em vez de rebentarem: uma
    linha antiga com um valor que já não se usa não pode fechar o acesso a
    quem legitimamente o tem, nem abri-lo a quem não tem.
    """
    forca = -1
    escolhido: Optional[str] = None
    for p in papeis:
        if not p:
            continue
        i = PAPEIS.index(p) if p in PAPEIS else 0
        if i > forca:
            forca, escolhido = i, p
    return escolhido


async def equipas_que_alcancam(db: AsyncSession, space_id: UUID) -> Dict[UUID, str]:
    """As equipas com acesso a este projeto → o papel de cada uma.

    Duas origens, unidas de propósito:

    * ``space_crews`` — o modelo novo: a equipa é do cliente e foi convidada
      **com um papel**.
    * ``crews.space_id`` — o modelo antigo, em que a equipa nascia dentro do
      projeto. Continua a valer para as que já existem; não se migra ninguém à
      força, e ignorá-las aqui cortaria acesso a quem o tem hoje.
    """
    papeis: Dict[UUID, str] = {}

    for crew_id, papel in (
        await db.execute(
            select(SpaceCrew.crew_id, SpaceCrew.role).where(SpaceCrew.space_id == space_id)
        )
    ).all():
        papeis[crew_id] = papel_mais_forte(papeis.get(crew_id), papel) or papel

    for (crew_id,) in (
        await db.execute(
            select(Crew.id).where(Crew.space_id == space_id, Crew.deleted_at.is_(None))
        )
    ).all():
        # A equipa que nasceu no projeto tem lá o poder de sempre.
        papeis[crew_id] = papel_mais_forte(papeis.get(crew_id), "editor") or "editor"

    return papeis


async def equipas_da_pessoa_no_projeto(
    db: AsyncSession, user_id: UUID, space_id: UUID
) -> List[UUID]:
    """As equipas desta pessoa que dão acesso a este projeto.

    É o que alimenta o recorte de dados: as tabelas vêm do projeto, mas saber
    **se** a pessoa lá chega passa por aqui.
    """
    alcancam = await equipas_que_alcancam(db, space_id)
    if not alcancam:
        return []
    minhas = {
        row[0]
        for row in (
            await db.execute(select(CrewMember.crew_id).where(CrewMember.user_id == user_id))
        ).all()
    }
    return [c for c in alcancam if c in minhas]


async def papel_no_projeto(
    db: AsyncSession, user_id: UUID, space_id: UUID
) -> Optional[str]:
    """O papel desta pessoa neste projeto — ``None`` se não lá chega.

    **Esta função decide tudo o resto.** Um `None` aqui é a diferença entre
    responder e calar.
    """
    espaco = (
        await db.execute(
            select(Space).where(Space.id == space_id, Space.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if espaco is None:
        return None

    # Quem criou o projeto é dono dele. Não depende de haver linha em
    # `space_members`: um projeto cujo criador perdeu a linha ficaria sem
    # ninguém que o pudesse gerir.
    if espaco.created_by == user_id:
        return "owner"

    directo = (
        await db.execute(
            select(SpaceMember.role).where(
                SpaceMember.space_id == space_id, SpaceMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    alcancam = await equipas_que_alcancam(db, space_id)
    por_equipa: Optional[str] = None
    if alcancam:
        minhas = {
            row[0]
            for row in (
                await db.execute(
                    select(CrewMember.crew_id).where(
                        CrewMember.user_id == user_id,
                        CrewMember.crew_id.in_(list(alcancam.keys())),
                    )
                )
            ).all()
        }
        # `.get` e não `[]`: só contam as equipas que de facto alcançam este
        # projeto. O SQL já filtra, mas depender disso é confiar que o
        # filtro nunca muda — e um `KeyError` aqui seria um 500 no caminho
        # que decide acesso, que é o pior sítio para rebentar.
        por_equipa = papel_mais_forte(*(alcancam.get(c) for c in minhas)) if minhas else None

    return papel_mais_forte(directo, por_equipa)


async def de_onde_vem_o_acesso(
    db: AsyncSession, user_id: UUID, space_id: UUID
) -> Dict[str, object]:
    """De onde vem o acesso desta pessoa — para a interface o poder dizer.

    **É isto que substitui a cópia de pessoas do S6.** A ligação é viva; a
    armadilha (*tirar alguém da equipa e julgar que se lhe cortou o acesso*)
    resolve-se mostrando a proveniência, não copiando:

        Ana Silva     Editor · via equipa Comercial
        Bruno Costa   Leitor · convidado directamente

    Quem lê isto sabe onde mexer.
    """
    directo = (
        await db.execute(
            select(SpaceMember.role).where(
                SpaceMember.space_id == space_id, SpaceMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    alcancam = await equipas_que_alcancam(db, space_id)
    vias = []
    if alcancam:
        for crew_id, nome in (
            await db.execute(
                select(Crew.id, Crew.name).where(
                    Crew.id.in_(list(alcancam.keys())),
                    Crew.deleted_at.is_(None),
                    Crew.id.in_(
                        select(CrewMember.crew_id).where(CrewMember.user_id == user_id)
                    ),
                )
            )
        ).all():
            vias.append({"crew_id": str(crew_id), "crew_name": nome, "role": alcancam[crew_id]})

    return {
        "papel": await papel_no_projeto(db, user_id, space_id),
        "directo": directo,
        "por_equipa": vias,
    }
