"""Quem está no projeto recebe o que acontece no projeto.

> *"Temos que garantir que todos daquele projeto receberam a notificação
> daquele projeto. Se você está dentro do projeto, você recebe a notificação
> dele."* — Lucas, 26/08/2026

**O que faltava.** As notificações existiam e eram escritas uma a uma, para
uma pessoa de cada vez — quem criou o agente, quem foi mencionado. Nada
avisava *o projeto*. Um achado aparecia a quem o agente pertencia e o resto da
equipa só o via se calhasse abrir o feed.

**Quem é "o projeto".** É a mesma resposta que decide o acesso aos dados, e
vem do mesmo sítio: `acesso_ao_projeto`. Uma segunda definição de "quem está
no projeto" acabaria por divergir da primeira — e a divergência apareceria
como alguém a receber notificações de dados a que já não chega, ou a não
receber as de dados que alcança.

**Traduzido, não em inglês.** Usa-se `title_key`/`title_params`, que a tabela
já tinha e ninguém usava: era por isso que as notificações diziam *"Receita
faturada found 1 new insight"* num telemóvel em português. A frase é
escolhida quando se lê, na língua de quem lê, e não quando se escreve.
"""

import logging
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import CrewMember
from src.models.space import Space, SpaceMember
from src.schemas.notification import NotificationCreate
from src.services.acesso_ao_projeto import equipas_que_alcancam

logger = logging.getLogger(__name__)


async def quem_esta_no_projeto(db: AsyncSession, space_id: UUID) -> List[UUID]:
    """Toda a gente que alcança este projeto — por qualquer via.

    Directos, por equipa, e quem o criou. É a audiência de tudo o que se passa
    lá dentro.
    """
    ids = {
        linha[0]
        for linha in (
            await db.execute(
                select(SpaceMember.user_id).where(SpaceMember.space_id == space_id)
            )
        ).all()
    }

    alcancam = await equipas_que_alcancam(db, space_id)
    if alcancam:
        ids |= {
            linha[0]
            for linha in (
                await db.execute(
                    select(CrewMember.user_id).where(
                        CrewMember.crew_id.in_(list(alcancam.keys()))
                    )
                )
            ).all()
        }

    espaco = (
        await db.execute(select(Space).where(Space.id == space_id))
    ).scalar_one_or_none()
    if espaco is not None:
        # Quem criou não depende de haver linha em `space_members` — ver
        # `acesso_ao_projeto.papel_no_projeto`.
        ids.add(espaco.created_by)

    return list(ids)


async def notificar_o_projeto(
    db: AsyncSession,
    space_id: UUID,
    *,
    tipo: str,
    title_key: str,
    title_params: Optional[Dict[str, str]] = None,
    description_key: Optional[str] = None,
    description_params: Optional[Dict[str, str]] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    excepto: Optional[UUID] = None,
) -> int:
    """Escreve a notificação para toda a gente do projeto. Devolve quantas.

    ``excepto`` serve para não avisar quem provocou o acontecimento: receber
    *"a Ana entrou no projeto"* por se ter acrescentado a Ana é ruído, e ruído
    é o que faz as pessoas desligarem as notificações todas.

    **Nunca rebenta o que a chamou.** Notificar é o remate de uma acção que já
    aconteceu; falhar aqui não pode desfazer a acção nem devolver um erro a
    quem a fez. Regista-se e segue.
    """
    from src.services.notification_service import NotificationService

    try:
        pessoas = await quem_esta_no_projeto(db, space_id)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("notificar_o_projeto: não consegui a audiência de %s: %s", space_id, exc)
        return 0

    servico = NotificationService(db)
    escritas = 0
    for uid in pessoas:
        if excepto is not None and uid == excepto:
            continue
        try:
            criada = await servico.create_notification(
                NotificationCreate(
                    user_id=uid,
                    type=tipo,
                    # `title` fica com a chave: as linhas antigas leem-se por
                    # `title`, e uma chave é melhor do que uma frase numa
                    # língua que talvez não seja a de quem lê.
                    title=title_key,
                    title_key=title_key,
                    title_params=title_params or {},
                    description_key=description_key,
                    description_params=description_params or {},
                    # Por omissão a entidade é o PROJETO. `entity_type` e
                    # `entity_id` são obrigatórios no esquema, e sem um valor
                    # honesto por omissão cada chamador teria de os inventar —
                    # e inventá-los-ia de forma diferente.
                    entity_type=entity_type or "space",
                    entity_id=entity_id or str(space_id),
                )
            )
            if criada is not None:
                escritas += 1
        except Exception as exc:  # pragma: no cover - defensivo
            # Uma pessoa com preferências estranhas não pode calar as outras.
            logger.warning("notificar_o_projeto: falhou para %s: %s", uid, exc)

    logger.info(
        "notificar_o_projeto: space=%s tipo=%s audiencia=%d escritas=%d",
        space_id,
        tipo,
        len(pessoas),
        escritas,
    )
    return escritas
