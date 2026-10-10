# -*- coding: utf-8 -*-
"""A sessão falada, verificada sem AWS e sem socket.

O `SessaoFalada` fala com o Bedrock por um canal bidireccional. Um teste
que precisasse disso a sério não correria na CI — e o que aqui importa
não é a AWS: é o que NÓS fazemos com o que ela manda, e o que mandamos
de volta.

Daí um canal falso: guarda tudo o que lhe enviamos e devolve os eventos
que lhe dermos. As medições contra o modelo verdadeiro estão em
`docs/a-voz-medida-nova-sonic.md`; isto protege o comportamento.

── O que cada bloco protege, e porque dói se se perder ────────────

**O contexto do cliente.** Sétima vez do mesmo defeito. Se alguém trocar
o argumento por um `current_tenant()`, a sessão passa a consultar a base
da plataforma em silêncio.

**O erro da ferramenta em texto.** Se o nosso SQL falhar e não
respondermos, o modelo ESPERA — até aos 55 s — e a sessão morre com a
pessoa à espera. Mandar o erro deixa-o dizer que não conseguiu.

**A ferramenta à parte do ciclo de leitura.** Esperar dentro do ciclo
cega-nos durante os segundos do SQL, e é logo nesse intervalo que chega
o `interrupted`.

**O silêncio.** O modelo desliga depois de 55 s sem áudio. Silenciar o
microfone tem de passar a alimentar silêncio, não a parar.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from src.core.tenant_context import TenantContext
from src.services import voz_fala_a_fala as voz

UM_CLIENTE = TenantContext(slug="cliente-de-teste", id=uuid4(), tier="pro", display_name="Cliente")


# ── O canal falso ───────────────────────────────────────────────────


class _Entrada:
    def __init__(self) -> None:
        self.enviados: List[Dict[str, Any]] = []
        self.fechado = False

    async def send(self, pedaco: Any) -> None:
        self.enviados.append(json.loads(pedaco.value.bytes_.decode("utf-8")))

    async def close(self) -> None:
        self.fechado = True


class _Saida:
    def __init__(self, eventos: List[Dict[str, Any]]) -> None:
        self._fila = list(eventos)

    async def receive(self) -> Any:
        if not self._fila:
            return None

        class _Res:
            def __init__(self, d: Dict[str, Any]) -> None:
                class _V:
                    bytes_ = json.dumps(d).encode("utf-8")

                self.value = _V()

        return _Res(self._fila.pop(0))


class _Fluxo:
    def __init__(self, eventos: List[Dict[str, Any]]) -> None:
        self.input_stream = _Entrada()
        self._saida = _Saida(eventos)

    async def await_output(self):
        return (None, self._saida)


class _Cliente:
    def __init__(self, eventos: List[Dict[str, Any]] | None = None) -> None:
        self.eventos = eventos or []
        self.fluxo: _Fluxo | None = None

    async def invoke_model_with_bidirectional_stream(self, _entrada: Any) -> _Fluxo:
        self.fluxo = _Fluxo(self.eventos)
        return self.fluxo


async def _sessao(eventos=None, ferramenta=None) -> tuple:
    async def nada(_p: str) -> str:
        return "{}"

    s = voz.SessaoFalada(
        ctx=UM_CLIENTE,
        ferramenta=ferramenta or nada,
        instrucao="Eres Sky.",
        voz="lupe",
    )
    cliente = _Cliente(eventos)
    await s.abrir(cliente)
    return s, cliente


def _eventos_enviados(cliente: _Cliente) -> List[str]:
    """Os NOMES dos eventos que mandámos, por ordem."""
    return [k for e in cliente.fluxo.input_stream.enviados for k in (e.get("event") or {})]


# ── O contexto do cliente ───────────────────────────────────────────


class TestOContextoVemDeFora:
    def test_e_o_primeiro_argumento(self):
        """Não é estilo: é o que impede a sétima repetição do defeito."""
        import inspect

        campos = list(inspect.signature(voz.SessaoFalada.__init__).parameters)
        assert campos[1] == "ctx", f"a ordem mudou: {campos[:3]}"

    def test_e_o_modulo_nao_le_a_variavel_de_contexto(self):
        """O `current_tenant()` devolve a PLATAFORMA em silêncio.

        Uma tarefa criada do lado errado do `set_current_tenant` fica
        presa a esse default para toda a vida — e o ciclo de escuta é
        exactamente uma tarefa dessas. Ver
        `test_a_heranca_do_cliente_entre_tarefas.py`.

        Verifica-se pelos IMPORTS e não por uma procura de texto: o que
        não se importa não se pode chamar, e uma procura de texto tropeça
        nas explicações — a primeira versão deste teste chumbou por
        apanhar a menção ao defeito no cabeçalho do módulo.
        """
        import ast
        import inspect

        arvore = ast.parse(inspect.getsource(voz))
        importados = {
            alias.name
            for no in ast.walk(arvore)
            if isinstance(no, ast.ImportFrom)
            for alias in no.names
        }
        proibidos = importados & {"current_tenant", "DEFAULT_TENANT_CONTEXT"}
        assert not proibidos, (
            f"o módulo importou {proibidos} — o `ctx` entra por "
            "argumento, e a razão está no cabeçalho do módulo"
        )


# ── A abertura ──────────────────────────────────────────────────────


class TestAAbertura:
    @pytest.mark.asyncio
    async def test_manda_a_abertura_pela_ordem_certa(self):
        _, cliente = await _sessao()
        nomes = _eventos_enviados(cliente)
        assert nomes[0] == "sessionStart"
        assert nomes[1] == "promptStart"
        # Instrução de sistema, depois o bloco de áudio.
        assert "contentStart" in nomes[2:]
        assert "textInput" in nomes

    @pytest.mark.asyncio
    async def test_declara_a_ferramenta(self):
        _, cliente = await _sessao()
        inicio = next(
            e["event"]["promptStart"]
            for e in cliente.fluxo.input_stream.enviados
            if "promptStart" in (e.get("event") or {})
        )
        ferramentas = inicio["toolConfiguration"]["tools"]
        assert ferramentas, "sem ferramenta o modelo não chega aos dados"
        assert ferramentas[0]["toolSpec"]["name"] == "consultar_dados"

    @pytest.mark.asyncio
    async def test_abre_UM_bloco_de_audio_para_a_sessao_toda(self):
        """E não um por turno.

        O fim de turno semântico vem de o modelo ouvir um fluxo contínuo.
        Fechar e reabrir por turno era voltar a decidir NÓS quando a
        pessoa acabou de falar — o defeito que isto vem resolver.
        """
        s, cliente = await _sessao()
        audios = [
            e["event"]["contentStart"]
            for e in cliente.fluxo.input_stream.enviados
            if (e.get("event") or {}).get("contentStart", {}).get("type") == "AUDIO"
        ]
        assert len(audios) == 1
        assert audios[0]["contentName"] == s._conteudo_audio  # noqa: SLF001


# ── A tradução dos eventos ──────────────────────────────────────────


class TestOQueChegaDeLa:
    @pytest.mark.asyncio
    async def test_a_transcricao_e_a_resposta_nao_se_confundem(self):
        """O `role` decide: `USER` é o ASR da pergunta, o resto é a Sky.

        Trocá-los punha a pergunta da pessoa no ecrã como se fosse a
        resposta — e vinda da Sky.
        """
        s, _ = await _sessao(
            [
                {"event": {"textOutput": {"role": "USER", "content": "quantas rutas?"}}},
                {"event": {"textOutput": {"role": "ASSISTANT", "content": "São duas."}}},
            ]
        )
        await s.escutar()
        saidos = [e async for e in s.eventos()]
        assert isinstance(saidos[0], voz.Ouvido)
        assert saidos[0].texto == "quantas rutas?"
        assert isinstance(saidos[1], voz.Dito)
        assert saidos[1].texto == "São duas."

    @pytest.mark.asyncio
    async def test_o_audio_chega_descodificado(self):
        pcm = b"\x01\x02\x03\x04"
        s, _ = await _sessao(
            [{"event": {"audioOutput": {"content": base64.b64encode(pcm).decode()}}}]
        )
        await s.escutar()
        saidos = [e async for e in s.eventos()]
        assert isinstance(saidos[0], voz.Audio)
        assert saidos[0].pcm == pcm

    @pytest.mark.asyncio
    async def test_o_fim_da_fala_e_a_interrupcao_passam(self):
        s, _ = await _sessao(
            [
                {"event": {"userSpeechEnd": {}}},
                {"event": {"interrupted": True}},
            ]
        )
        await s.escutar()
        tipos = [type(e) async for e in s.eventos()]
        assert voz.FalaAcabou in tipos
        assert voz.Interrompido in tipos, (
            "sem isto o cliente não sabe descartar o áudio já enviado, e "
            "a Sky continua a falar depois de ser cortada"
        )

    @pytest.mark.asyncio
    async def test_a_conta_de_tokens_acompanha(self):
        s, _ = await _sessao(
            [
                {
                    "event": {
                        "usageEvent": {
                            "details": {
                                "total": {
                                    "input": {"speechTokens": 279, "textTokens": 895},
                                    "output": {"speechTokens": 118, "textTokens": 73},
                                }
                            }
                        }
                    }
                },
            ]
        )
        await s.escutar()
        [_ async for _ in s.eventos()]
        assert s.conta.voz_entrada == 279
        assert s.conta.voz_saida == 118


# ── A ferramenta ────────────────────────────────────────────────────


class TestAFerramenta:
    @pytest.mark.asyncio
    async def test_a_pergunta_chega_a_ferramenta_e_a_resposta_volta(self):
        vistas: List[str] = []

        async def consultar(pergunta: str) -> str:
            vistas.append(pergunta)
            # PROSA, que e o que o `_voice_answer` devolve a serio. O duplo
            # devolvia JSON e por isso este teste passava enquanto a
            # producao morria — ver o teste a seguir.
            return "Temos 2 rotas activas."

        s, cliente = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": json.dumps({"pergunta": "quantas rutas?"}),
                        }
                    }
                }
            ],
            ferramenta=consultar,
        )
        await s.escutar()
        [_ async for _ in s.eventos()]
        await asyncio.sleep(0)  # deixa a tarefa da ferramenta correr
        await asyncio.sleep(0)

        assert vistas == ["quantas rutas?"]
        resultados = [
            e["event"]["toolResult"]
            for e in cliente.fluxo.input_stream.enviados
            if "toolResult" in (e.get("event") or {})
        ]
        assert resultados, "o resultado não foi entregue — o modelo fica à espera"
        corpo = json.loads(resultados[0]["content"])
        assert corpo["resultado"] == "Temos 2 rotas activas."
        # E a instrução para o dizer tal e qual — sem ela o Sonic resumia um
        # «não existe X; o mais próximo é Y» em «não encontrei» (10/10).
        assert "fiel" in corpo["como_dizer"]

    @pytest.mark.asyncio
    async def test_o_resultado_da_ferramenta_e_sempre_json(self):
        """O `content` do `toolResult` tem de ser JSON. Sempre.

        ── O que aconteceu em producao ─────────────────────────────

        A 09/10/2026, no telemovel do Lucas, **todas** as sessoes de voz
        morriam depois da primeira pergunta respondida:

            ValidationException: ... Tool Response parsing error
            voz/sonic: sessao fechada (..., turnos=1, ...)

        O Bedrock recusa o `toolResult` e FECHA o canal. A app reabria o
        socket, e por isso cada pergunta aparecia como uma conversa
        separada na lista dele.

        A causa era o `content` ir em prosa. Os caminhos de ERRO ja
        usavam `json.dumps` e passavam; o caminho que funciona mandava o
        texto tal e qual. E o teste de cima nao apanhava nada, porque o
        duplo devolvia JSON — fixava o codigo, nao o comportamento.

        Aqui a assercao e a garantia: **seja o que for que a ferramenta
        devolva**, o que sai pelo canal tem de ser JSON valido.
        """

        async def consultar(pergunta: str) -> str:
            # O pior caso realista: prosa com acentos, aspas e chavetas.
            return 'Sao 2 rotas: a "Norte" e a {Sul}, com 14% de atraso.'

        s, cliente = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": json.dumps({"pergunta": "quantas rotas?"}),
                        }
                    }
                }
            ],
            ferramenta=consultar,
        )
        await s.escutar()
        [_ async for _ in s.eventos()]
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        resultados = [
            e["event"]["toolResult"]
            for e in cliente.fluxo.input_stream.enviados
            if "toolResult" in (e.get("event") or {})
        ]
        assert resultados, "o resultado não foi entregue — o modelo fica à espera"
        # Isto levanta se nao for JSON, que e exactamente o que o Bedrock faz.
        corpo = json.loads(resultados[0]["content"])
        assert isinstance(corpo, dict)
        assert 'Sao 2 rotas: a "Norte" e a {Sul}, com 14% de atraso.' in corpo.values()

    @pytest.mark.asyncio
    async def test_anuncia_que_esta_a_pensar(self):
        """O evento que o cliente usa para tocar o recado.

        **Medido:** o modelo cala-se enquanto a ferramenta corre, e não
        há como o convencer a avisar. O «deixa-me ver» tem de vir do
        cliente, e precisa de saber quando.
        """
        s, _ = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": json.dumps({"pergunta": "o que foi?"}),
                        }
                    }
                }
            ]
        )
        await s.escutar()
        saidos = [e async for e in s.eventos()]
        pensa = [e for e in saidos if isinstance(e, voz.APensar)]
        assert pensa and pensa[0].pergunta == "o que foi?"

    @pytest.mark.asyncio
    async def test_uma_ferramenta_que_REBENTA_responde_em_texto(self):
        """O detalhe que decide se a sessão sobrevive a uma falha.

        Sem resposta, o modelo espera até aos 55 s e a sessão morre com a
        pessoa à espera. Com o erro em texto, ele DIZ que não conseguiu —
        melhor do que o silêncio que a voz tem hoje.
        """

        async def rebenta(_p: str) -> str:
            raise RuntimeError("o SQL explodiu")

        s, cliente = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": "{}",
                        }
                    }
                }
            ],
            ferramenta=rebenta,
        )
        await s.escutar()
        [_ async for _ in s.eventos()]
        for _ in range(4):
            await asyncio.sleep(0)

        resultados = [
            e["event"]["toolResult"]
            for e in cliente.fluxo.input_stream.enviados
            if "toolResult" in (e.get("event") or {})
        ]
        assert resultados, "rebentou e não respondeu — a sessão vai morrer calada"
        assert "erro" in json.loads(resultados[0]["content"])

    @pytest.mark.asyncio
    async def test_uma_ferramenta_LENTA_tambem(self, monkeypatch):
        """Pelo mesmo motivo, e com um prazo bem abaixo dos 55 s."""
        monkeypatch.setattr(voz, "PRAZO_DA_FERRAMENTA", 0.01)

        async def lenta(_p: str) -> str:
            await asyncio.sleep(5)
            return "{}"

        s, cliente = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": "{}",
                        }
                    }
                }
            ],
            ferramenta=lenta,
        )
        await s.escutar()
        [_ async for _ in s.eventos()]
        await asyncio.sleep(0.1)

        resultados = [
            e["event"]["toolResult"]
            for e in cliente.fluxo.input_stream.enviados
            if "toolResult" in (e.get("event") or {})
        ]
        assert resultados and "erro" in json.loads(resultados[0]["content"])

    def test_o_prazo_fica_bem_abaixo_do_limite_da_sessao(self):
        assert voz.PRAZO_DA_FERRAMENTA < voz.LIMITE_SEM_AUDIO, (
            "um prazo acima do limite da sessão não é um prazo: a sessão "
            "morre antes de o cancelamento servir para alguma coisa"
        )

    @pytest.mark.asyncio
    async def test_a_ferramenta_NAO_bloqueia_a_leitura(self):
        """Esperar dentro do ciclo cega-nos durante os segundos do SQL.

        E é logo nesse intervalo que chega o `interrupted` — a pessoa
        cansa-se de esperar e fala. Se estivéssemos bloqueados, não o
        veríamos.

        A propriedade é «continua a ler **enquanto** a ferramenta corre»,
        e é assim que se escreve: a ferramenta fica presa num portão, e
        só o abrimos depois de o `Interrompido` ter chegado. Se a leitura
        estivesse bloqueada, ele nunca chegava e isto pendurava — que é o
        que o `wait_for` apanha.
        """
        portao = asyncio.Event()
        começou = asyncio.Event()

        async def presa(_p: str) -> str:
            começou.set()
            await portao.wait()
            return "{}"

        s, _ = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": "{}",
                        }
                    }
                },
                {"event": {"interrupted": True}},
            ],
            ferramenta=presa,
        )

        escuta = asyncio.create_task(s.escutar())
        vistos: List[type] = []

        async def consumir() -> None:
            async for e in s.eventos():
                vistos.append(type(e))
                # Chegou com a ferramenta ainda presa: é isto que se
                # quer provar. Agora pode seguir.
                if isinstance(e, voz.Interrompido):
                    assert not portao.is_set()
                    portao.set()

        await asyncio.wait_for(asyncio.gather(escuta, consumir()), timeout=5)
        assert voz.Interrompido in vistos
        assert começou.is_set()
        assert voz.APensar in vistos


# ── O silêncio, que mantém a sessão viva ────────────────────────────


class TestOQueSoUmaChamadaASerioRevelou:
    """Dois achados que o canal falso nunca teria mostrado.

    Estão aqui porque os descobri a correr a classe de produção contra
    eu-north-1 — e porque sem um teste voltam na primeira refactorização.
    """

    @pytest.mark.asyncio
    async def test_nao_manda_audio_enquanto_a_consulta_corre(self):
        """Mandar áudio com uma consulta pendente MATA a sessão.

        Não vem na documentação. O modelo recusa com um
        `ValidationException: Invalid input request` que não diz qual é o
        problema, e a sessão morre com a pessoa à espera.

        As sondas não o apanharam por sorte — nelas o envio de áudio
        acabava poucas centenas de milissegundos depois do pedido. A
        classe alimentava silêncio durante a consulta inteira, que é o
        que o produto faz, e partiu logo.

        **O custo, e fica dito:** não há barge-in durante o «a pensar».
        É limitação do modelo, não escolha nossa.
        """
        portao = asyncio.Event()

        async def presa(_p: str) -> str:
            await portao.wait()
            return "{}"

        s, cliente = await _sessao(
            [
                {
                    "event": {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "toolName": "consultar_dados",
                            "content": "{}",
                        }
                    }
                }
            ],
            ferramenta=presa,
        )
        escuta = asyncio.create_task(s.escutar())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        antes = len(cliente.fluxo.input_stream.enviados)
        await s.ouvir_microfone(b"\x01\x02" * 100)
        await s.silencio()
        assert len(cliente.fluxo.input_stream.enviados) == antes, (
            "mandou áudio com uma consulta pendente — a sessão a sério "
            "morre aqui, com um erro que não diz porquê"
        )

        portao.set()
        await asyncio.wait_for(escuta, timeout=2)
        [_ async for _ in s.eventos()]

        # E volta a aceitar quando a consulta acaba.
        antes = len(cliente.fluxo.input_stream.enviados)
        await s.silencio()
        assert len(cliente.fluxo.input_stream.enviados) > antes

    @pytest.mark.asyncio
    async def test_a_mesma_frase_nao_vai_duas_vezes_para_o_ecra(self):
        """O modelo manda a MESMA frase em dois eventos.

        Medido: `content` igual palavra por palavra, `contentId`
        diferente — um é a legenda da fala, o outro a saída de texto, e
        não há campo que diga qual é qual. Sem isto, a legenda aparece a
        dobrar no ecrã.
        """
        frase = "Hay dos rutas que incumplen el plazo."
        s, _ = await _sessao(
            [
                {
                    "event": {
                        "textOutput": {"role": "ASSISTANT", "content": frase, "contentId": "a"}
                    }
                },
                {
                    "event": {
                        "textOutput": {"role": "ASSISTANT", "content": frase, "contentId": "b"}
                    }
                },
            ]
        )
        await s.escutar()
        ditos = [e async for e in s.eventos() if isinstance(e, voz.Dito)]
        assert len(ditos) == 1, f"a frase foi {len(ditos)} vezes para o ecrã"

    @pytest.mark.asyncio
    async def test_mas_uma_frase_NOVA_passa(self):
        """O contrapeso: comparar com a anterior não pode calar o resto."""
        s, _ = await _sessao(
            [
                {"event": {"textOutput": {"role": "ASSISTANT", "content": "Primeira."}}},
                {"event": {"textOutput": {"role": "ASSISTANT", "content": "Primeira."}}},
                {"event": {"textOutput": {"role": "ASSISTANT", "content": "Segunda."}}},
            ]
        )
        await s.escutar()
        ditos = [e.texto async for e in s.eventos() if isinstance(e, voz.Dito)]
        assert ditos == ["Primeira.", "Segunda."]


class TestOSilencio:
    @pytest.mark.asyncio
    async def test_alimentar_silencio_manda_audio_de_verdade(self):
        """Silenciar não pode ser parar de alimentar.

        O modelo desliga depois de `LIMITE_SEM_AUDIO` sem nada. Quem
        silencia e vai beber um café volta a uma sessão morta.
        """
        s, cliente = await _sessao()
        antes = len(cliente.fluxo.input_stream.enviados)
        await s.silencio(0.064)
        mandados = cliente.fluxo.input_stream.enviados[antes:]
        assert len(mandados) == 1
        audio = mandados[0]["event"]["audioInput"]
        pcm = base64.b64decode(audio["content"])
        assert pcm == bytes(len(pcm)), "o silêncio tem de ser silêncio"
        assert len(pcm) == int(voz.ENTRADA_HZ * 0.064) * 2

    def test_e_o_limite_esta_escrito_onde_se_ve(self):
        assert voz.LIMITE_SEM_AUDIO == 55.0


# ── A bandeira ──────────────────────────────────────────────────────


def _cliente_com(bandeiras: dict):
    return TenantContext(
        slug="um-cliente",
        id=uuid4(),
        tier="pro",
        display_name="Um",
        feature_flags=bandeiras,
    )


class TestABandeira:
    """Por CLIENTE, e não por processo — porque não há staging.

    As máquinas de staging foram desligadas a 18/08; o único ambiente a
    correr é produção. Uma bandeira por processo em produção é
    tudo-ou-nada, e ligá-la para experimentar punha o motor novo em cima
    dos clientes — num produto que é demonstrado a clientes.

    Com o `feature_flags` do registo liga-se no `sandbox` e mais nada
    muda. É o degrau de teste que o ambiente não tem.
    """

    def test_desligada_por_omissao(self, monkeypatch):
        monkeypatch.delenv("VOICE_ENGINE", raising=False)
        assert voz.esta_ligada() is False
        assert voz.esta_ligada(_cliente_com({})) is False

    def test_liga_SO_no_cliente_que_a_tem(self, monkeypatch):
        """O que permite testar em produção sem tocar em clientes."""
        monkeypatch.delenv("VOICE_ENGINE", raising=False)
        assert voz.esta_ligada(_cliente_com({"voice_engine": "sonic"})) is True
        assert voz.esta_ligada(_cliente_com({"voice_engine": "cascata"})) is False
        assert voz.esta_ligada(_cliente_com({"outra_coisa": "sonic"})) is False

    @pytest.mark.parametrize("valor", ["sonic", "SONIC", " sonic "])
    def test_a_variavel_liga_para_TODOS(self, monkeypatch, valor):
        """Para o dia em que for o motor de omissão."""
        monkeypatch.setenv("VOICE_ENGINE", valor)
        assert voz.esta_ligada() is True
        assert voz.esta_ligada(_cliente_com({})) is True

    def test_e_desliga_para_todos_MESMO_com_o_cliente_ligado(self, monkeypatch):
        """O travão de emergência, e a ordem importa.

        Uma variável de ambiente mexe-se mais depressa do que uma linha
        numa base de dados. Numa avaria é isso que conta — e se a
        bandeira do cliente ganhasse a esta, o travão não travava nada.
        """
        monkeypatch.setenv("VOICE_ENGINE", "cascata")
        assert voz.esta_ligada(_cliente_com({"voice_engine": "sonic"})) is False

    def test_um_feature_flags_estranho_nao_derruba_a_voz(self, monkeypatch):
        """Cai no caminho que funciona hoje, com uma linha nos registos."""
        monkeypatch.delenv("VOICE_ENGINE", raising=False)

        class _Mau:
            @property
            def feature_flags(self):
                raise RuntimeError("coluna corrompida")

        assert voz.esta_ligada(_Mau()) is False
        assert voz.esta_ligada("isto nem é um contexto") is False
