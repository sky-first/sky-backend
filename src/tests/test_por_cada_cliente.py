"""Os agendadores tem de percorrer a base de CADA cliente.

**O defeito.** Os tres agendadores — agentes, insights, varredura de orfaos —
abriam `AsyncSessionLocal()`, que e a base da PLATAFORMA. No modelo B os
agentes de cada cliente vivem na base dedicada dele, e na da plataforma nao ha
agente nenhum de cliente nenhum.

Ligar o `celery beat` sem isto daria um agendador que corre, escreve «0
agentes vencidos» nos registos, e nao poe nada a correr. **Pior do que nao
haver agendador**, porque parece que funciona: ha um pod de pe, ha linhas nos
registos, e zero e indistinguivel de «nao ha nada a fazer».
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers import por_cada_cliente as mod


class _Cliente:
    def __init__(self, slug, com_base=True):
        self.slug = slug
        self.db_host = "h" if com_base else None
        self.db_name = "d" if com_base else None


def _registo_com(*clientes):
    db = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(clientes)
    db.execute = AsyncMock(return_value=r)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_a_plataforma_vem_sempre():
    """Ha instalacoes de um cliente so, e nessas os agentes vivem mesmo la.

    Excluir a plataforma fazia o agendador ignorar exactamente esse caso.
    """
    with patch("src.config.database.AsyncSessionLocal", _registo_com()):
        slugs = await mod.clientes_activos()
    assert slugs and slugs[0] == "default"


@pytest.mark.asyncio
async def test_cada_cliente_com_base_dedicada_entra():
    with patch(
        "src.config.database.AsyncSessionLocal",
        _registo_com(_Cliente("gbtsolutions"), _Cliente("sandbox")),
    ):
        slugs = await mod.clientes_activos()
    assert "gbtsolutions" in slugs
    assert "sandbox" in slugs


@pytest.mark.asyncio
async def test_um_cliente_sem_base_dedicada_nao_entra_duas_vezes():
    """Os dados dele estao na base da plataforma, que ja la esta.

    Soma-lo outra vez enfileirava tudo a dobrar para esse cliente.
    """
    with patch(
        "src.config.database.AsyncSessionLocal",
        _registo_com(_Cliente("pequeno", com_base=False)),
    ):
        slugs = await mod.clientes_activos()
    assert slugs == ["default"]


@pytest.mark.asyncio
async def test_sem_registo_de_clientes_ainda_se_serve_a_plataforma():
    """Devolver lista vazia parava TUDO por causa de uma consulta."""
    quebrado = MagicMock(side_effect=RuntimeError("sem registo"))
    with patch("src.config.database.AsyncSessionLocal", quebrado):
        slugs = await mod.clientes_activos()
    assert slugs == ["default"]


@pytest.mark.asyncio
async def test_a_passagem_corre_uma_vez_por_cliente():
    vistos = []

    async def passagem(slug):
        vistos.append(slug)
        return 1, 0

    with patch.object(mod, "clientes_activos", AsyncMock(return_value=["default", "gbt"])):
        with patch.object(mod, "contexto_do_cliente", MagicMock(return_value=_vazio())):
            a, b = await mod.por_cada_cliente(passagem)
    assert vistos == ["default", "gbt"]
    assert (a, b) == (2, 0)


@pytest.mark.asyncio
async def test_um_cliente_que_rebenta_nao_trava_os_outros():
    """Uma base indisponivel e UM cliente sem agentes durante cinco minutos.

    Sem esta guarda era toda a gente sem agentes ate alguem reparar.
    """
    vistos = []

    async def passagem(slug):
        vistos.append(slug)
        if slug == "mau":
            raise RuntimeError("base em baixo")
        return 1, 0

    with patch.object(
        mod, "clientes_activos", AsyncMock(return_value=["mau", "bom"])
    ):
        with patch.object(mod, "contexto_do_cliente", MagicMock(return_value=_vazio())):
            a, _ = await mod.por_cada_cliente(passagem)
    assert vistos == ["mau", "bom"]
    assert a == 1


def _vazio():
    """Um contexto que RESOLVEU. O `True` nao e decoracao: o ciclo salta os
    clientes que nao resolvem, e um `None` aqui fazia estes testes verem
    zero passagens."""
    c = MagicMock()
    c.__aenter__ = AsyncMock(return_value=True)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


class TestOsTresAgendadoresForamMudados:
    """Guardas de fonte: os tres deixaram de olhar para a base da plataforma.

    E a mesma familia de defeito que ja mordeu tres vezes (PRs #569/#570/#571):
    codigo escrito antes do modelo B que continua a olhar para a base da
    plataforma como se fosse a unica. Uma varredura evita a quarta.
    """

    def _sem_comentarios(self, caminho):
        import io

        linhas = io.open(caminho, encoding="utf-8").read().split("\n")
        return "\n".join(l for l in linhas if not l.strip().startswith("#"))

    @pytest.mark.parametrize(
        "ficheiro",
        [
            "src/workers/agent_worker.py",
            "src/workers/insight_agent_worker.py",
            "src/workers/agent_revocation_worker.py",
        ],
    )
    def test_usa_a_base_do_cliente(self, ficheiro):
        """**Nenhuma sessao contra a base da plataforma.**

        A primeira versao deste guarda so exigia que `session_for` APARECESSE
        no ficheiro — e o `agent_worker` ja o usava noutro sitio, portanto
        reverter o agendador nao acendia nada. Um guarda satisfeito por outra
        linha do ficheiro e um guarda desligado.

        Passa a proibir o padrao errado em vez de exigir a presenca do certo.
        """
        fonte = self._sem_comentarios(ficheiro)
        assert "session_for(current_tenant())" in fonte
        assert "AsyncSessionLocal() as db" not in fonte

    @pytest.mark.parametrize(
        "ficheiro",
        [
            "src/workers/agent_worker.py",
            "src/workers/insight_agent_worker.py",
            "src/workers/agent_revocation_worker.py",
        ],
    )
    def test_percorre_todos_os_clientes(self, ficheiro):
        fonte = self._sem_comentarios(ficheiro)
        assert "por_cada_cliente" in fonte


class TestOContextoResolveDeDentroDoLaco:
    """**O defeito que custou dinheiro.**

    O `_resolve_worker_side` faz `asyncio.run(...)`, que rebenta com «cannot
    be called from a running event loop» quando ja ha um laco — e a excepcao
    e engolida por um `except` largo que devolve o contexto por omissao.

    Visto em producao: os tres clientes resolviam todos para «default», o
    `session_for` devolvia a base da PLATAFORMA aos tres, e os mesmos 10
    agentes corriam TRES VEZES. Custo a triplicar, e os agentes dos clientes
    a nao correr de todo.

    Apanhei-o a olhar para os registos: `agent-scheduler[sky]: 9`,
    `[sandbox]: 9`, `[skyfirstlabs]: 9` — tres contagens identicas e 10 ids
    distintos em 31 arranques.
    """

    def test_nao_usa_o_resolve_worker_side(self):
        """Ele esta certo onde nasceu — no `task_prerun`, que corre FORA do
        laco. So nao serve de dentro de um.

        Le o CODIGO, com comentarios e docstrings fora: a primeira versao
        deste guarda acendeu por causa da propria explicacao do modulo, que
        cita `asyncio.run` para dizer porque nao se usa. Ver `_sem_prosa`.
        """
        from src.tests._sem_prosa import sem_prosa

        codigo = sem_prosa(mod)
        assert "_resolve_worker_side" not in codigo
        assert "asyncio.run" not in codigo

    @pytest.mark.asyncio
    async def test_um_cliente_que_nao_resolve_e_SALTADO(self):
        """Nunca cair no default em silencio.

        Correr os agentes da plataforma a pensar que sao os de um cliente e
        pior do que nao correr nada: gasta tokens e grava achados no sitio
        errado.
        """
        correu = []

        async def passagem(slug):
            correu.append(slug)
            return 1, 0

        with patch.object(
            mod, "clientes_activos", AsyncMock(return_value=["default", "fantasma"])
        ), patch.object(mod, "_resolver", AsyncMock(return_value=None)):
            a, _ = await mod.por_cada_cliente(passagem)

        assert correu == ["default"], correu
        assert a == 1

    @pytest.mark.asyncio
    async def test_um_cliente_que_resolve_corre(self):
        from unittest.mock import MagicMock as _M

        ctx = _M()
        ctx.is_default = False
        ctx.slug = "gbt"
        correu = []

        async def passagem(slug):
            correu.append(slug)
            return 2, 0

        with patch.object(
            mod, "clientes_activos", AsyncMock(return_value=["gbt"])
        ), patch.object(mod, "_resolver", AsyncMock(return_value=ctx)):
            a, _ = await mod.por_cada_cliente(passagem)

        assert correu == ["gbt"]
        assert a == 2
