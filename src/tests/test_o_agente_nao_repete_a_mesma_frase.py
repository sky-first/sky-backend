# -*- coding: utf-8 -*-
"""A mesma frase trinta vezes é uma frase, não trinta.

> «temos muitas mensagens dessas repetidas… Está feio e isso precisa
>  arrumar» — Lucas, 06/10/2026

── O que estava certo, e que isto não desfaz ───────────────────────

Um agente que não encontra nada **tem** de o dizer. Está escrito no
``test_um_agente_responde_sempre`` e custou uma sessão a descobrir: uma
corrida calada é indistinguível de uma avaria, e foi assim que o Lucas
leu o silêncio em Agosto.

Só que dizê-lo de hora a hora enche o fio, e um fio cheio da mesma
frase esconde a única coisa que lá importa — a mensagem em que o agente
*encontrou* algo. O ruído não é um problema de estética: é perda de
sinal.

── A escolha: contar, não calar ────────────────────────────────────

A mensagem fica uma e conta as corridas. Ninguém perde informação: o
``created_at`` diz desde quando, o ``ultima_repeticao_em`` diz até
quando, e o número diz quantas. Trinta cartões iguais dizem menos do
que um a dizer «30 vezes», porque ninguém conta cartões.

── E o contrapeso, que é a parte que se parte ──────────────────────

O colapso é PEDIDO, com a chave do catálogo, e nunca inferido do texto.
Se fosse inferido, duas descobertas iguais em dias diferentes
fundiam-se numa — e aí sim perdia-se um facto, que é exactamente o que
um agente existe para dar.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.locale import get_message
from src.services import agent_conversation_service as svc
from src.workers import agent_worker


# ── As frases ───────────────────────────────────────────────────────


class TestAsFrasesTemLingua:
    def test_as_duas_estao_no_catalogo_nas_tres_linguas(self):
        """Estavam cravadas em português no worker.

        O worker corre sozinho: não sabe se quem vai ler é o Lucas ou um
        cliente de Badajoz. A chave viaja com a mensagem e o cliente
        escolhe a língua na altura de mostrar, que é a única altura em
        que ela se sabe.
        """
        for chave in ("agent_nothing_to_report", "agent_could_not_run"):
            frases = {lg: get_message(chave, lg) for lg in ("pt", "en", "es")}
            assert len(set(frases.values())) == 3, f"{chave}: {frases}"
            for lingua, frase in frases.items():
                assert frase != chave, f"{chave} não tem {lingua}"

    def test_o_worker_le_as_frases_do_catalogo(self):
        """Uma fonte só para as palavras.

        Se o worker guardasse a sua cópia, corrigir o português num sítio
        deixava o outro atrasado — e o ecrã mostrava a cópia velha.
        """
        assert agent_worker.NADA_A_ASSINALAR == get_message("agent_nothing_to_report")
        assert agent_worker.NAO_CONSEGUI == get_message("agent_could_not_run")

    def test_e_continuam_a_ser_duas_coisas_diferentes(self):
        # O que o `test_um_agente_responde_sempre` já protegia: uma avaria
        # nossa não se disfarça de «não há nada nos seus dados».
        assert agent_worker.NAO_CONSEGUI != agent_worker.NADA_A_ASSINALAR
        assert "nosso" in agent_worker.NAO_CONSEGUI.lower()
        assert "próxima" in agent_worker.NADA_A_ASSINALAR.lower()


class TestOWorkerPedeOColapso:
    def test_as_duas_mensagens_de_estado_levam_chave(self):
        fonte = inspect.getsource(agent_worker)
        i = fonte.index("if finding_da_corrida is not None:")
        bloco = fonte[i : i + 3500]
        assert "agent_could_not_run" in bloco
        assert "agent_nothing_to_report" in bloco

    def test_e_uma_resposta_a_serio_nao_leva(self):
        """O contrapeso no sítio onde ele se parte.

        O ramo sem achado serve dois casos: o motor devolveu um texto seu
        (é uma resposta — vale mensagem nova, mesmo que saia igual à de
        ontem) e o motor não devolveu nada (é estado — colapsa). Se a
        chave fosse posta nos dois, duas respostas iguais fundiam-se.
        """
        fonte = inspect.getsource(agent_worker)
        i = fonte.index("tem_texto_proprio")
        bloco = fonte[i : i + 900]
        assert "None if tem_texto_proprio" in bloco


# ── O colapso ───────────────────────────────────────────────────────


class _MsgFalsa(SimpleNamespace):
    pass


class _RepoDeMensagensFalso:
    """Conta as criações e devolve a mensagem criada."""

    def __init__(self, registo):
        self._registo = registo

    async def create(self, **kw):
        msg = _MsgFalsa(
            id=uuid4(),
            role=kw.get("role"),
            content=kw.get("content"),
            chave_de_texto=None,
            repeticoes=1,
            ultima_repeticao_em=None,
            created_at=datetime.now(timezone.utc),
            deleted_at=None,
        )
        self._registo.append(msg)
        return msg


class _RepoDeConversasFalso:
    def __init__(self):
        self.updates = []

    async def update(self, conv_id, **kw):
        self.updates.append((conv_id, kw))


class _DbFalsa:
    async def flush(self):
        return None


AGENTE = SimpleNamespace(id=uuid4(), name="Rutas", scope="crew", scope_id=uuid4())


@pytest.fixture
def cenario(monkeypatch):
    """O ``post_agent_answer`` com os arredores substituídos.

    O que interessa testar é a decisão — criar mensagem nova ou somar à
    anterior. A conversa, a página e o repositório são caminho.
    """
    criadas: list = []
    conv_id = uuid4()
    ultima: dict = {"msg": None}

    async def _ensure(db, agent):
        return conv_id

    async def _ultima(db, cid):
        return ultima["msg"]

    conversas = _RepoDeConversasFalso()
    monkeypatch.setattr(svc, "ensure_agent_conversation", _ensure)
    monkeypatch.setattr(svc, "_ultima_mensagem", _ultima)
    monkeypatch.setattr(svc, "MessageRepository", lambda db: _RepoDeMensagensFalso(criadas))
    monkeypatch.setattr(svc, "ConversationRepository", lambda db: conversas)
    return SimpleNamespace(criadas=criadas, ultima=ultima, conversas=conversas, conv_id=conv_id)


def _assistente(chave, repeticoes=1, horas=1):
    return _MsgFalsa(
        id=uuid4(),
        role="assistant",
        chave_de_texto=chave,
        repeticoes=repeticoes,
        ultima_repeticao_em=None,
        created_at=datetime.now(timezone.utc) - timedelta(hours=horas),
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_a_primeira_vez_escreve_uma_mensagem(cenario):
    await svc.post_agent_answer(
        _DbFalsa(),
        agent=AGENTE,
        answer="Olhei e não há nada.",
        chave_de_texto="agent_nothing_to_report",
    )
    assert len(cenario.criadas) == 1
    # E a chave fica gravada — sem ela a segunda corrida não a reconhece
    # e o colapso nunca acontece.
    assert cenario.criadas[0].chave_de_texto == "agent_nothing_to_report"


@pytest.mark.asyncio
async def test_a_segunda_soma_a_primeira_em_vez_de_escrever(cenario):
    anterior = _assistente("agent_nothing_to_report")
    cenario.ultima["msg"] = anterior

    devolvido = await svc.post_agent_answer(
        _DbFalsa(),
        agent=AGENTE,
        answer="Olhei e não há nada.",
        chave_de_texto="agent_nothing_to_report",
    )

    assert cenario.criadas == [], "escreveu mensagem nova em vez de somar"
    assert devolvido == anterior.id
    assert anterior.repeticoes == 2
    assert anterior.ultima_repeticao_em is not None
    # E o fio sobe na lista da sala: senão a prova de que o agente está
    # vivo deixava de se ver, que é o problema original ao contrário.
    assert cenario.conversas.updates


@pytest.mark.asyncio
async def test_uma_resposta_a_serio_nunca_colapsa(cenario):
    """Duas descobertas iguais são dois factos.

    O caso que o colapso por texto estragaria: a margem caiu 3% ontem e
    caiu 3% hoje. A frase é a mesma; o facto é outro.
    """
    anterior = _assistente(None)
    cenario.ultima["msg"] = anterior

    await svc.post_agent_answer(
        _DbFalsa(), agent=AGENTE, answer="A margem caiu 3%.", finding_id=uuid4()
    )
    assert len(cenario.criadas) == 1
    assert anterior.repeticoes == 1


@pytest.mark.asyncio
async def test_uma_avaria_nao_colapsa_para_dentro_de_um_nada_a_assinalar(cenario):
    """Chaves diferentes não se fundem.

    Se se fundissem, uma avaria nossa somava-se a «não há nada nos seus
    dados» e desaparecia — é a mentira tranquilizadora que o teste de
    Agosto existe para impedir, agora por outra porta.
    """
    anterior = _assistente("agent_nothing_to_report", repeticoes=4, horas=4)
    cenario.ultima["msg"] = anterior

    await svc.post_agent_answer(
        _DbFalsa(),
        agent=AGENTE,
        answer="Não consegui.",
        chave_de_texto="agent_could_not_run",
    )
    assert len(cenario.criadas) == 1
    assert anterior.repeticoes == 4


@pytest.mark.asyncio
async def test_se_alguem_falou_no_fio_a_mensagem_nova_vai_para_o_fim(cenario):
    """Mexer numa mensagem antiga reescreveria o passado.

    Alguém da equipa respondeu «e o camião 14?» depois do último «não há
    nada». Somar à mensagem de antes punha a contagem acima da pergunta
    e o fio passava a mentir sobre a ordem em que as coisas foram ditas.
    """
    cenario.ultima["msg"] = _MsgFalsa(
        id=uuid4(),
        role="user",
        chave_de_texto=None,
        repeticoes=1,
        ultima_repeticao_em=None,
        created_at=datetime.now(timezone.utc),
        deleted_at=None,
    )

    await svc.post_agent_answer(
        _DbFalsa(),
        agent=AGENTE,
        answer="Olhei e não há nada.",
        chave_de_texto="agent_nothing_to_report",
    )
    assert len(cenario.criadas) == 1


@pytest.mark.asyncio
async def test_um_fio_vazio_nao_rebenta(cenario):
    # A primeira corrida de um agente novo: `_ultima_mensagem` devolve
    # None e o caminho do colapso não pode tropeçar nisso.
    cenario.ultima["msg"] = None
    await svc.post_agent_answer(
        _DbFalsa(),
        agent=AGENTE,
        answer="Olhei e não há nada.",
        chave_de_texto="agent_nothing_to_report",
    )
    assert len(cenario.criadas) == 1
