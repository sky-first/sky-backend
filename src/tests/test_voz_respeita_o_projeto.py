"""A voz tem de responder DO PROJETO onde a pessoa está.

O defeito, encontrado a 25/08/2026 com a app no telemóvel do Lucas: perguntar
pela voz dentro do projeto "Felipe e Lucas" — que tinha **zero ligações** e
dizia no ecrã "Ainda sem dados, este projeto não consegue responder a nada" —
respondia "o total de clientes é 46". Os dados vinham de outro projeto.

A causa estava aqui no servidor, em duas linhas::

    conn_id = await AIService(db)._get_first_active_connection(user.id)
    ...
    space_id="default"

A primeira ligação activa da pessoa, fosse ela de que projeto fosse. Isto
contorna o modelo inteiro — os dados pertencem ao projeto, o acesso vem da
equipa — e o chat escrito respeita-o. A voz era uma porta ao lado que dava
para todas as salas.

Estes testes fixam o COMPORTAMENTO, não a implementação: o que se verifica é
que uma pergunta num projeto sem alcance **não recebe resposta nenhuma**, e
que uma ligação de fora do projeto **não é aceite** mesmo quando o ajudante
que a escolhe a devolve.
"""

import pytest

from src.api.v1 import voice as voice_module


class _ServicoFalso:
    """O AIService, reduzido às três perguntas que a voz lhe faz."""

    def __init__(self, permitidas, escolhida, primeira="conn-de-outro-projeto"):
        self._permitidas = permitidas
        self._escolhida = escolhida
        self._primeira = primeira
        self.pediu_a_primeira = False

    async def _get_all_connections_for_space(self, user_id, space_id):
        return list(self._permitidas)

    async def _get_first_active_connection_for_space(self, user_id, space_id, question=None):
        return self._escolhida

    async def _get_first_active_connection(self, user_id):
        self.pediu_a_primeira = True
        return self._primeira


class _Utilizador:
    id = "user-1"


@pytest.fixture
def montar(monkeypatch):
    """Põe o `_voice_answer` a correr contra um serviço nosso.

    Nada de base de dados nem de motor de IA: o que está em causa é a decisão
    de ÂMBITO, que acontece antes de qualquer das duas.
    """

    def _montar(servico):
        import contextlib

        @contextlib.asynccontextmanager
        async def _sessao(_ctx):
            yield object()

        monkeypatch.setattr(
            "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
            _sessao,
        )
        monkeypatch.setattr("src.services.ai_service.AIService", lambda _db: servico)

        chamadas = []

        class _ClienteFalso:
            def stream_query_connection(self, **kw):
                chamadas.append(kw)

                async def _vazio():
                    return
                    yield  # pragma: no cover

                return _vazio()

        monkeypatch.setattr("src.ai.http_client.AIServiceHTTPClient", _ClienteFalso)
        return chamadas

    return _montar


@pytest.mark.asyncio
async def test_projeto_sem_ligacoes_nao_responde(montar):
    """**O caso que o Lucas apanhou.**

    Zero ligações alcançáveis: a resposta certa é o silêncio. Cair na
    "primeira ligação activa" era exactamente a fuga.
    """
    servico = _ServicoFalso(permitidas=[], escolhida=None)
    chamadas = montar(servico)

    resposta = await voice_module._voice_answer(
        _Utilizador(), "pagina-1", "Quantos clientes temos?", ctx=object(),
        locale="pt", space_id="projeto-vazio",
    )

    assert resposta == ""
    # E — o que mais importa — nem sequer se chegou a perguntar ao motor.
    assert chamadas == []
    # Nem se foi buscar a primeira ligação da pessoa pela porta das traseiras.
    assert servico.pediu_a_primeira is False


@pytest.mark.asyncio
async def test_ligacao_de_fora_do_projeto_e_recusada(montar):
    """O ajudante que escolhe a ligação **cai na primeira do utilizador** quando
    não encontra nada no projeto. Isso é a mesma fuga com outro nome, por isso
    só se aceita o que estiver no conjunto alcançável.
    """
    servico = _ServicoFalso(
        permitidas=["conn-do-projeto"],
        escolhida="conn-de-outro-projeto",  # veio de fora
    )
    chamadas = montar(servico)

    resposta = await voice_module._voice_answer(
        _Utilizador(), "pagina-1", "Quantos clientes temos?", ctx=object(),
        locale="pt", space_id="projeto-1",
    )

    assert resposta == ""
    assert chamadas == []


@pytest.mark.asyncio
async def test_o_projeto_vai_ao_motor(montar):
    """Com uma ligação legítima, a pergunta segue — e leva o projeto consigo.

    O `space_id="default"` fixo dizia ao motor "responde do que quiseres".
    """
    servico = _ServicoFalso(
        permitidas=["conn-do-projeto"],
        escolhida="conn-do-projeto",
    )
    chamadas = montar(servico)

    await voice_module._voice_answer(
        _Utilizador(), "pagina-1", "Quantos clientes temos?", ctx=object(),
        locale="pt", space_id="projeto-1",
    )

    assert len(chamadas) == 1
    assert chamadas[0]["connection_id"] == "conn-do-projeto"
    assert chamadas[0]["space_id"] == "projeto-1"


@pytest.mark.asyncio
async def test_sem_projeto_continua_a_ser_o_modo_pessoal(montar):
    """Falar sem projeto nenhum é legítimo — é o modo pessoal, onde a primeira
    ligação da própria pessoa É o âmbito certo. Fechar isto também partia uma
    coisa que funcionava.
    """
    servico = _ServicoFalso(permitidas=[], escolhida=None, primeira="conn-pessoal")
    chamadas = montar(servico)

    await voice_module._voice_answer(
        _Utilizador(), "pagina-1", "Quantos clientes temos?", ctx=object(),
        locale="pt", space_id=None,
    )

    assert servico.pediu_a_primeira is True
    assert len(chamadas) == 1
    assert chamadas[0]["connection_id"] == "conn-pessoal"
    assert chamadas[0]["space_id"] == "default"
