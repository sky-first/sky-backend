"""«Em pausa» quer dizer «nao vas ver por tua conta», nao «recusa-te quando eu
te pergunto».

O worker recusava QUALQUER corrida de um agente que nao estivesse `active`.
Com a correcao do «Perguntar agora» — que passou a abrir a conversa do agente
em vez de mostrar um aviso — isso ficou pior do que antes: a app abre o fio, o
worker deita a tarefa fora em silencio, e a mensagem nunca chega. Do lado de
quem carregou le-se como avariado.

E ha uma armadilha por cima: os agentes do Lucas foram AUTO-PAUSADOS por um
defeito nosso (o laco de eventos do Celery), nao por decisao dele. Recusar o
pedido manual deixava-os presos numa pausa que ninguem escolheu e que nada
desfazia — nem sequer carregar no botao.
"""

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers import agent_worker


class _Agente:
    def __init__(self, status):
        self.id = "11111111-1111-1111-1111-111111111111"
        self.status = status
        self.name = "Margem por categoria"


def _sessao_com(agente):
    """Uma sessao que devolve este agente, e o `db` para se poder ver o que
    lhe foi feito.

    **O que se mede e o `db.add`.** A primeira versao destes testes so
    verificava que a chamada nao rebentava — e passava com o codigo velho,
    porque o codigo velho tambem nao rebenta: faz `return` em silencio. Um
    teste que passa nos dois lados do defeito nao guarda nada, e e o terceiro
    que escrevo assim neste projecto.

    Logo a seguir ao guarda, uma corrida a serio cria o registo de execucao —
    `db.add(...)`. E o primeiro sinal observavel de que o guarda deixou passar.
    """
    db = AsyncMock()
    db.add = MagicMock()
    resultado = MagicMock()
    resultado.scalar_one_or_none.return_value = agente
    db.execute = AsyncMock(return_value=resultado)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db


@pytest.mark.asyncio
async def test_o_agendador_nao_acorda_um_agente_em_pausa():
    """A pausa continua a valer para quem corre sozinho. E o ponto dela."""
    agente = _Agente("paused")
    # No modulo do `tenant_connection_manager` e nao no do worker: ele
    # importa-o DENTRO da funcao, portanto o nome so existe la em tempo de
    # execucao. Remenda-lo no worker nao apanha nada.
    ctx, db = _sessao_com(agente)
    with patch(
        "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
        return_value=ctx,
    ):
        await agent_worker._execute_agent_async(str(agente.id))
    # Nao criou execucao nenhuma: a sessao so foi usada para o ir buscar.
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_pedir_directamente_a_um_agente_em_pausa_NAO_e_ignorado():
    """**O defeito exacto.**

    Antes: `return` em silencio. A app abria o fio e ficava vazio para sempre.

    Aqui so se mede que o guarda deixa PASSAR — o que vem a seguir precisa de
    ligacoes a serio e rebenta neste duplo, o que e a prova de que passou.
    """
    agente = _Agente("paused")
    ctx, db = _sessao_com(agente)
    with patch(
        "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
        return_value=ctx,
    ):
        try:
            await agent_worker._execute_agent_async(str(agente.id), a_pedido=True)
        except Exception:
            # Rebenta mais a frente, onde precisa de ligacoes a serio. O que
            # interessa ja aconteceu ou nao aconteceu.
            pass
    db.add.assert_called()  # criou o registo de execucao => o guarda deixou passar


def test_a_rota_marca_o_pedido_como_manual():
    """Sem isto, a correccao nao chega a lado nenhum.

    Le-se o codigo em vez de montar uma app inteira: o que se quer garantir e
    que a chamada leva `a_pedido=True`, e isso vive numa linha so.
    """
    import inspect

    from src.api.v1 import agents as rota

    fonte = inspect.getsource(rota.run_agent_now)
    sem_comentarios = "\n".join(
        l for l in fonte.split("\n") if not l.strip().startswith("#")
    )
    assert "a_pedido=True" in sem_comentarios


def test_a_tarefa_do_celery_aceita_o_parametro():
    """O `.delay(id, a_pedido=True)` tem de ter onde aterrar.

    Um parametro que a rota manda e a tarefa nao aceita da um erro de
    argumento dentro do worker — visivel so nos registos, e a mensagem
    continuava a nao chegar.
    """
    import inspect

    assinatura = inspect.signature(agent_worker.execute_agent)
    assert "a_pedido" in assinatura.parameters
