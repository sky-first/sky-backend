"""A SEGUNDA tarefa do mesmo processo tem de correr como a primeira.

Nenhum agente do Lucas corria. Nos registos de produção, a partir da segunda
tarefa de cada worker:

    Agent execution failed: Task ... got Future ... attached to a different loop

Três falhas seguidas e o agente auto-pausa. Foi por isso que ele viu «Paused.
It won't look until you resume it» em agentes que nunca pausou.

**A causa.** Cada tarefa criava um laço de eventos novo, corria e fechava-o —
mas as ligações às bases dos clientes vivem numa cache global do processo, e
uma ligação do asyncpg fica presa ao laço onde nasceu. A tarefa seguinte
reutilizava-as num laço já morto.

**Porque é que isto passou meses despercebido.** A PRIMEIRA tarefa depois de
cada arranque do worker funciona sempre. Um teste que corre uma tarefa não vê
nada, e reiniciar o pod «resolve» o problema durante exactamente uma corrida.
É por isso que estes testes correm a coisa DUAS vezes: uma vez não prova nada.
"""

import asyncio

import pytest

from src.workers.laco_do_celery import correr


class MotorDeMentira:
    """Finge uma ligação presa a um laço, como as do asyncpg.

    Guarda o laço em que nasceu e recusa-se a ser usada noutro — que é
    exactamente o que o asyncpg faz, só que com uma mensagem mais obscura.
    """

    def __init__(self) -> None:
        self.laco = asyncio.get_event_loop()
        self.fechado = False

    async def usar(self) -> str:
        if self.laco is not asyncio.get_event_loop():
            raise RuntimeError("got Future attached to a different loop")
        return "ok"

    async def dispose(self) -> None:
        self.fechado = True


class CacheDeMentira:
    """A cache global de ligações por cliente, como a verdadeira."""

    def __init__(self) -> None:
        self._pools: dict = {}
        self.vezes_que_abriu = 0

    async def motor(self, slug: str = "cliente") -> MotorDeMentira:
        if slug not in self._pools:
            self._pools[slug] = MotorDeMentira()
            self.vezes_que_abriu += 1
        return self._pools[slug]

    async def dispose_all(self) -> None:
        for m in self._pools.values():
            await m.dispose()
        self._pools.clear()


@pytest.fixture
def cache(monkeypatch):
    c = CacheDeMentira()
    monkeypatch.setattr(
        "src.config.tenant_connection_manager.tenant_connection_manager", c
    )
    return c


def test_a_segunda_tarefa_tambem_corre(cache):
    """**O defeito exacto.** Duas tarefas seguidas, como no worker a sério."""

    async def tarefa():
        motor = await cache.motor()
        return await motor.usar()

    assert correr(tarefa()) == "ok"
    assert correr(tarefa()) == "ok", (
        "a segunda tarefa rebentou — é o «got Future attached to a "
        "different loop» que auto-pausou os agentes do Lucas"
    )


def test_e_a_terceira_e_a_quarta(cache):
    # Um agente por hora, doze agentes: o processo faz isto o dia todo.
    async def tarefa():
        motor = await cache.motor()
        return await motor.usar()

    for _ in range(4):
        assert correr(tarefa()) == "ok"


def test_as_ligacoes_sao_devolvidas_ao_sair(cache):
    async def tarefa():
        await cache.motor()

    correr(tarefa())
    assert cache._pools == {}, "ficaram ligações na cache presas a um laço morto"


def test_uma_ligacao_nova_por_tarefa(cache):
    """É o preço, e é assumido.

    Reabrir custa dezenas de milissegundos; um agente corre uma vez por hora
    na melhor das hipóteses. Manter um laço vivo por processo era mais rápido
    e guardava estado entre tarefas — a mesma família de defeito, mais difícil
    de ver.
    """

    async def tarefa():
        await cache.motor()

    correr(tarefa())
    correr(tarefa())
    assert cache.vezes_que_abriu == 2


def test_as_ligacoes_sao_devolvidas_mesmo_quando_a_tarefa_rebenta(cache):
    """Uma tarefa que falha não pode envenenar a seguinte.

    Sem isto, o primeiro agente com um erro qualquer deixava as ligações
    presas e derrubava todos os agentes a seguir — uma falha a virar doze.
    """

    async def tarefa_que_rebenta():
        await cache.motor()
        raise ValueError("qualquer coisa correu mal")

    with pytest.raises(ValueError):
        correr(tarefa_que_rebenta())
    assert cache._pools == {}

    async def tarefa_boa():
        motor = await cache.motor()
        return await motor.usar()

    assert correr(tarefa_boa()) == "ok"


def test_falhar_a_fechar_nao_perde_o_resultado(monkeypatch):
    """O trabalho já está feito quando a limpeza corre.

    Perder o resultado de um agente porque não se conseguiu fechar uma
    ligação seria trocar um problema pequeno por um grande.
    """

    class CacheQueNaoFecha:
        async def dispose_all(self):
            raise RuntimeError("não deu")

    monkeypatch.setattr(
        "src.config.tenant_connection_manager.tenant_connection_manager",
        CacheQueNaoFecha(),
    )

    async def tarefa():
        return "o resultado"

    assert correr(tarefa()) == "o resultado"
