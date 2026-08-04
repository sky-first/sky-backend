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


# Quantos achados vão para o ecrã de agentes do telemóvel. Três é o que
# cabe sem cortar o terceiro a meio — e um cartão cortado lê-se como um
# erro de layout, não como "há mais".
INSIGHTS_LIMIT = 3


async def get_insights(
    db: AsyncSession, dataset_id, limit: int = INSIGHTS_LIMIT
) -> Sequence[DemoInsight]:
    """Todos os achados curados do dataset, o herói primeiro.

    O herói continua a sair por `get_insight` porque o primeiro ecrã só
    quer esse; esta função serve o ecrã de achados, onde a lista é o
    argumento — um sistema a olhar para o negócio, e não um exemplo.
    """
    return (
        (
            await db.execute(
                select(DemoInsight)
                .where(DemoInsight.dataset_id == dataset_id)
                .order_by(DemoInsight.position)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


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


async def list_qas(db: AsyncSession, dataset_id, limit: int = 50) -> Sequence[DemoQA]:
    """Todas as perguntas curadas do dataset, sugeridas ou não.

    Serve o portão de domínio, que precisa de saber de que assuntos o
    dataset fala. Usar só as três sugeridas encolhia esse vocabulário ao
    que está no ecrã e recusava perguntas legítimas — "what is our win
    rate?" era recusada apesar de existir uma resposta curada para ela.
    """
    return (
        (
            await db.execute(
                select(DemoQA).where(DemoQA.dataset_id == dataset_id).order_by(DemoQA.position).limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def get_qa(db: AsyncSession, qa_id) -> Optional[DemoQA]:
    return (await db.execute(select(DemoQA).where(DemoQA.id == qa_id))).scalar_one_or_none()


# Quanto da pergunta do visitante tem de estar na pergunta curada para
# a resposta ser servida.
#
# 0,34 vem de medir: com as 7 perguntas curadas, "quanto está por
# cobrar?" bate a de faturas vencidas acima disto, e "qual é o meu CAC
# por coorte?" não bate nenhuma. Baixá-lo faz voltar as respostas
# desencontradas; subi-lo recusa perguntas que a demo sabe responder.
MIN_MATCH_SCORE = 0.34


def _overlap(question: str, candidate: str) -> float:
    """Fracção das palavras com conteúdo da pergunta que a curada cobre.

    Reutiliza o normalizador e a lista de palavras vazias do portão de
    domínio — o mesmo problema, do outro lado: ali decide-se se é sobre
    negócio, aqui se é sobre *este* assunto.
    """
    from src.services.demo_domain_gate import _STOPWORDS, _words

    asked = {w for w in _words(question) if len(w) > 2 and w not in _STOPWORDS}
    if not asked:
        return 0.0
    known = {w for w in _words(candidate) if len(w) > 2 and w not in _STOPWORDS}
    return len(asked & known) / len(asked)


async def _nearest_qa(db: AsyncSession, dataset_id, question: str) -> Optional[DemoQA]:
    """QA mais próxima da pergunta livre, para o fallback.

    Devolve ``None`` quando nenhuma pergunta curada se aproxima o
    suficiente — e é essa a parte importante desta função.

    Tenta pesquisa vectorial primeiro; se o provider de embeddings não
    estiver disponível, ordena por palavras em comum.

    **Hoje o ramo vectorial nunca corre.** ``src.ai.embeddings`` ainda
    não existe neste repo e o comando de curadoria deixa ``embedding``
    a NULL, portanto o ``ImportError`` é apanhado abaixo. Está escrito
    assim de propósito — o ramo fica pronto para quando o módulo existir
    (BE-15), e é aí que este contador de palavras deve desaparecer, que
    é o sítio certo para resolver isto.
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

    # Sem embeddings, ordena por palavras em comum com as perguntas
    # curadas.
    #
    # Antes devolvia a **primeira** sugerida, sempre. Quem perguntasse
    # "qual é o meu CAC por coorte?" recebia o relatório de churn com o
    # rótulo "a mais próxima que temos" — e essa é a forma mais rápida
    # de um prospect concluir que o produto não presta. Não é o portão
    # de domínio que o expõe; é isto.
    #
    # Contar palavras em comum não é semântica, e não finge ser. É o
    # suficiente para não trocar overdue por churn, e para saber quando
    # **não há** correspondência nenhuma — que é a parte que interessa.
    best, best_score = None, 0.0
    for qa in await list_qas(db, dataset_id):
        score = _overlap(question, qa.question or "")
        if score > best_score:
            best, best_score = qa, score

    if best is None or best_score < MIN_MATCH_SCORE:
        # Melhor não responder do que responder outra coisa. O ecrã
        # mostra as perguntas que a demo sabe responder, em vez de
        # apresentar uma resposta desencontrada como se fosse a certa.
        logger.info("demo_no_match score=%.2f q=%r", best_score, question[:80])
        return None
    return best


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
    company: Optional[str] = None,
    role: Optional[str] = None,
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
        # Só sobrescreve com o que ele escreveu de facto: voltar e
        # submeter só o email não pode apagar a empresa da primeira vez.
        if company:
            existing.company = company.strip()
        if role:
            existing.role = role.strip()
        await db.commit()
        return existing

    lead = DemoLead(
        email=email,
        company=(company or "").strip() or None,
        role=(role or "").strip() or None,
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
    "get_insights",
    "list_qas",
    "get_qa",
    "get_suggested",
    "record_lead",
]
