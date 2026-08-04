"""Serviço do conteúdo curado da demo — BE-12.

Regra que governa este módulo: **o caminho crítico nunca toca no LLM**.

O primeiro ecrã e as três respostas sugeridas saem daqui já prontos. A
única função que fala com o motor de AI é :func:`ask`, e mesmo essa tem
um limite de tempo e um fallback determinista — nunca devolve erro ao
visitante.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.demo_content import DemoDataset, DemoInsight, DemoLead, DemoQA

logger = logging.getLogger(__name__)

# Quantas perguntas sugeridas aparecem sob o insight. Três é o que cabe
# sem competir com o herói.
SUGGESTED_LIMIT = 3

# Limite de tempo da geração ao vivo em ``ask``.
#
# A spec original propunha 8s. Medição em produção a 2026-08-03: uma
# pergunta real leva ~13,7s já com os embeddings corrigidos. Com 8s,
# 100% das perguntas cairiam em fallback e o caminho ao vivo seria
# teatro — pior, o visitante esperava 8s para receber conteúdo de
# exemplo. 20s dá margem real ao caminho ao vivo sem testar a paciência
# de ninguém.
#
# Baixar isto quando a latência do motor descer; é o número a vigiar.
LIVE_ANSWER_TIMEOUT_S = 20.0


async def get_dataset(
    db: AsyncSession, *, vertical: Optional[str] = None, locale: str = "en"
) -> Optional[DemoDataset]:
    """Dataset para a vertical pedida, com queda para o de omissão.

    Uma vertical desconhecida **não** é erro: quem chega por um link
    antigo ou com um parâmetro estragado tem de ver a demo na mesma. A
    alternativa — 404 — transformaria um detalhe em porta fechada.
    """
    if vertical:
        row = (
            await db.execute(
                select(DemoDataset).where(
                    DemoDataset.vertical == vertical, DemoDataset.locale == locale
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row

    row = (
        await db.execute(
            select(DemoDataset).where(
                DemoDataset.locale == locale, DemoDataset.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    # Locale sem conteúdo — cair para inglês antes de desistir.
    if locale != "en":
        return await get_dataset(db, vertical=vertical, locale="en")
    return None


async def get_insight(db: AsyncSession, dataset_id) -> Optional[DemoInsight]:
    return (
        await db.execute(
            select(DemoInsight)
            .where(DemoInsight.dataset_id == dataset_id)
            .order_by(DemoInsight.position)
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_suggested(
    db: AsyncSession, dataset_id, limit: int = SUGGESTED_LIMIT
) -> Sequence[DemoQA]:
    return (
        (
            await db.execute(
                select(DemoQA)
                .where(DemoQA.dataset_id == dataset_id, DemoQA.is_suggested.is_(True))
                .order_by(DemoQA.position)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def get_qa(db: AsyncSession, qa_id) -> Optional[DemoQA]:
    return (await db.execute(select(DemoQA).where(DemoQA.id == qa_id))).scalar_one_or_none()


async def _nearest_qa(db: AsyncSession, dataset_id, question: str) -> Optional[DemoQA]:
    """QA mais próxima da pergunta livre, para o fallback.

    Tenta pesquisa vectorial; se o provider de embeddings não estiver
    disponível — ou se as QA não tiverem embedding — cai para a primeira
    sugerida. Um fallback que também pode falhar não é fallback.

    **Hoje o ramo vectorial nunca corre.** ``src.ai.embeddings`` ainda
    não existe neste repo e o comando de curadoria deixa ``embedding``
    a NULL, portanto o ``ImportError`` é apanhado abaixo e serve-se
    sempre a primeira sugerida. Está escrito assim de propósito — o
    ramo fica pronto para quando o módulo existir (BE-15) sem que a
    demo dependa dele para funcionar — mas não confundir "código
    presente" com "comportamento activo": qualquer medição de qualidade
    do fallback hoje está a medir a primeira sugerida.
    """
    try:
        from src.ai.embeddings import embed_query  # type: ignore

        vec = await embed_query(question)
        if vec:
            row = (
                await db.execute(
                    select(DemoQA)
                    .where(
                        DemoQA.dataset_id == dataset_id,
                        DemoQA.embedding.isnot(None),
                    )
                    .order_by(DemoQA.embedding.cosine_distance(vec))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is not None:
                return row
    except Exception as exc:  # noqa: BLE001
        logger.info("demo_fallback_semantic_unavailable: %s", exc)

    rows = await get_suggested(db, dataset_id, limit=1)
    return rows[0] if rows else None


async def ask(
    db: AsyncSession,
    *,
    dataset_id,
    question: str,
    live_answer=None,
    timeout_s: float = LIVE_ANSWER_TIMEOUT_S,
) -> Tuple[Optional[DemoQA], Optional[Dict[str, Any]], bool]:
    """Responde a uma pergunta livre. **Nunca levanta.**

    Devolve ``(qa, live_payload, is_fallback)``:

    * caminho ao vivo bem sucedido → ``(None, payload, False)``
    * excedeu o tempo, falhou, ou não há motor → ``(qa, None, True)``

    ``live_answer`` é injectado para o teste não precisar do motor real.
    """
    if live_answer is not None:
        try:
            payload = await asyncio.wait_for(live_answer(question), timeout=timeout_s)
            if payload:
                return None, payload, False
        except asyncio.TimeoutError:
            logger.info("demo_ask_timeout after %.1fs — a servir fallback", timeout_s)
        except Exception as exc:  # noqa: BLE001
            # Qualquer falha do motor degrada para conteúdo curado. O
            # visitante não pode ver um ecrã de erro numa demo comercial.
            logger.warning("demo_ask_live_failed: %s", exc)

    return await _nearest_qa(db, dataset_id, question), None, True


async def record_lead(
    db: AsyncSession,
    *,
    email: str,
    dataset_id=None,
    questions_asked: Optional[List[str]] = None,
    vertical: Optional[str] = None,
    locale: Optional[str] = None,
    source: Optional[str] = None,
) -> DemoLead:
    """Guarda o contacto. Idempotente por email.

    Submeter duas vezes actualiza o registo em vez de duplicar — um lead
    por pessoa, não um por clique.
    """
    email = email.strip().lower()
    existing = (
        await db.execute(select(DemoLead).where(DemoLead.email == email))
    ).scalar_one_or_none()

    if existing is not None:
        if dataset_id is not None:
            existing.dataset_id = dataset_id
        if questions_asked:
            # Acumula em vez de substituir: a segunda visita não apaga o
            # que se aprendeu na primeira.
            merged = list(dict.fromkeys(list(existing.questions_asked or []) + questions_asked))
            existing.questions_asked = merged
        if vertical:
            existing.vertical = vertical
        if locale:
            existing.locale = locale
        await db.commit()
        return existing

    lead = DemoLead(
        email=email,
        dataset_id=dataset_id,
        questions_asked=questions_asked or [],
        vertical=vertical,
        locale=locale,
        source=source,
    )
    db.add(lead)
    await db.commit()
    return lead


__all__ = [
    "LIVE_ANSWER_TIMEOUT_S",
    "SUGGESTED_LIMIT",
    "ask",
    "get_dataset",
    "get_insight",
    "get_qa",
    "get_suggested",
    "record_lead",
]
