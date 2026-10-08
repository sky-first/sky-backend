# -*- coding: utf-8 -*-
"""Uma conversa falada, num modelo só (Nova 2.5 Sonic).

── Porque isto não é um `VoiceProvider` ────────────────────────────

O `VoiceProvider` do `voice_pipeline.py` tem uma forma: dá-se-lhe áudio,
sai TEXTO (`transcripts()`), nós chamamos o motor de SQL, e depois
pede-se-lhe para LER a resposta (`synthesize(text)`). Três peças nossas
com o raciocínio no meio.

O Sonic não tem essa forma. Ele ouve, pensa, **chama a nossa ferramenta
a meio**, e fala — tudo dentro de um canal bidireccional. Não há um
momento em que lhe damos uma frase para ler.

Forçá-lo no `VoiceProvider` significaria mentir na interface — um
`synthesize()` que ignora o texto que recebe. Daí uma classe própria, e
o `voice.py` a escolher entre as duas pela bandeira.

── O que isto é, e o que não é ─────────────────────────────────────

É o dono de UMA sessão: abre o canal, deixa empurrar áudio, devolve
eventos já traduzidos para o nosso vocabulário, e chama de volta quando
o modelo quer dados.

**Não** fala WebSocket, não conhece o protocolo BE-07 e não sabe o que é
um `page_id`. Isso é do `voice.py`. Aqui dentro não há nada que precise
de saber que existe um utilizador a olhar para um ecrã — o que o torna
testável sem AWS e sem socket.

── A regra que está no topo deste ficheiro por uma razão ───────────

**O contexto do cliente entra por ARGUMENTO.** Nunca lido de uma
variável de contexto aqui dentro.

Isto não é preferência de estilo: é a sétima vez do mesmo defeito. O
`current_tenant()` tem `default=DEFAULT_TENANT_CONTEXT`, que é a base da
PLATAFORMA, e devolve-a **em silêncio** quando ninguém pôs nada. Uma
tarefa criada uma linha antes do `set_current_tenant` fica presa a esse
default para toda a vida — medido, em
`test_a_heranca_do_cliente_entre_tarefas.py`.

E aqui isso seria fatal, não irritante: o ciclo de escuta é UMA tarefa
criada uma vez por sessão, e é dela que saem as chamadas à ferramenta.
Nasce do lado errado e a sessão inteira consulta a base de outro
cliente, sem uma linha nos registos.

Ver `docs/a-voz-medida-nova-sonic.md`, caso S2.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

#: A região da UE onde o modelo existe. O cluster está em eu-west-1; a
#: travessia custa ~35 ms de ida e volta, medidos de um pod de produção,
#: e não há alternativa na UE.
REGIAO = os.getenv("SONIC_REGION", "eu-north-1")

MODELO = os.getenv("SONIC_MODEL", "amazon.nova-2-5-sonic")

#: 16 kHz, 16 bit, mono à entrada — o que o cliente já manda hoje para o
#: Transcribe, portanto a app não muda.
ENTRADA_HZ = 16000
#: 24 kHz à saída, que é o que o modelo produz.
SAIDA_HZ = 24000

#: O modelo desliga a sessão com `ValidationException` depois de 55 s sem
#: áudio nem conteúdo interactivo. **Medido.** Daí duas regras:
#:
#:   * silenciar o microfone tem de passar a alimentar SILÊNCIO, não a
#:     parar de alimentar (e o silêncio não é facturado — também medido);
#:   * qualquer espera nossa, incluindo o SQL, tem de ficar bem abaixo
#:     disto.
LIMITE_SEM_AUDIO = 55.0

#: O tecto que damos à ferramenta. Abaixo dos 55 s com margem larga: o
#: que interessa é a sessão sobreviver para poder DIZER que falhou.
PRAZO_DA_FERRAMENTA = float(os.getenv("SONIC_TOOL_TIMEOUT", "30"))


# ── O que sai daqui ─────────────────────────────────────────────────
#
# Eventos no nosso vocabulário, não no da AWS. O `voice.py` traduz estes
# para o protocolo BE-07; se a AWS mudar os nomes dos seus, só este
# ficheiro muda.


@dataclass(frozen=True)
class Ouvido:
    """Transcrição do que a PESSOA disse. Vem de graça com o modelo."""

    texto: str


@dataclass(frozen=True)
class Dito:
    """Texto que a Sky está a dizer — a legenda do áudio."""

    texto: str


@dataclass(frozen=True)
class Audio:
    """Um pedaço de fala da Sky, PCM16 mono a `SAIDA_HZ`."""

    pcm: bytes


@dataclass(frozen=True)
class FalaAcabou:
    """O modelo deu a fala da pessoa por acabada (endpointing dele).

    É a âncora de todas as medições de latência, e é também o instante
    em que a pessoa começa a esperar. ~400 ms depois de a fala acabar de
    verdade, sem cronómetro nosso.
    """


@dataclass(frozen=True)
class Interrompido:
    """O modelo detectou que a pessoa o cortou.

    Não é preciso pedir: aparece sozinho no fluxo. O `voice.py` responde
    a isto mandando `discard_audio` ao cliente — sem isso o áudio já
    enviado toca de qualquer maneira e ouve-se pior do que não ter
    interrupção nenhuma (caso S5).
    """


@dataclass(frozen=True)
class APensar:
    """O modelo pediu dados. A partir daqui há silêncio até responder.

    **Medido: ele cala-se enquanto a ferramenta corre, e não há como o
    convencer a avisar** — nem por instrução de sistema, nem com duas
    ferramentas em cadeia, nem empurrando os dados depois. O recado
    («deixa-me ver») tem de vir do CLIENTE, e é para isso que este
    evento existe.
    """

    pergunta: str


@dataclass(frozen=True)
class Falhou:
    """A sessão morreu. `porque` vai para os registos, não para o ouvido."""

    porque: str


Evento = Ouvido | Dito | Audio | FalaAcabou | Interrompido | APensar | Falhou

#: A ferramenta: recebe a pergunta em linguagem natural, devolve o que
#: encontrou. No produto é o nosso motor de SQL; nos testes é uma função.
#:
#: Devolver texto de ERRO em vez de levantar excepção é deliberado — ver
#: `_responder_ferramenta`.
Ferramenta = Callable[[str], Awaitable[str]]


@dataclass
class ContaDeTokens:
    """O que o `usageEvent` diz, para a factura não ser uma surpresa."""

    voz_entrada: int = 0
    voz_saida: int = 0
    texto_entrada: int = 0
    texto_saida: int = 0

    def atualizar(self, total: Dict[str, Any]) -> None:
        ent = total.get("input") or {}
        sai = total.get("output") or {}
        self.voz_entrada = ent.get("speechTokens", self.voz_entrada)
        self.texto_entrada = ent.get("textTokens", self.texto_entrada)
        self.voz_saida = sai.get("speechTokens", self.voz_saida)
        self.texto_saida = sai.get("textTokens", self.texto_saida)


def ferramenta_declarada(nome: str, descricao: str) -> Dict[str, Any]:
    """A declaração que o modelo lê para decidir se chama a ferramenta.

    A descrição é o prompt que decide se ele a usa. Vale a pena ser
    concreto — «números, clientes, rotas, custos» funcionou melhor nas
    sondas do que «consulta os dados».
    """
    return {
        "toolSpec": {
            "name": nome,
            "description": descricao,
            "inputSchema": {
                "json": json.dumps(
                    {
                        "type": "object",
                        "properties": {
                            "pergunta": {
                                "type": "string",
                                "description": ("A pergunta da pessoa, em linguagem natural."),
                            }
                        },
                        "required": ["pergunta"],
                    }
                )
            },
        }
    }


@dataclass
class SessaoFalada:
    """Uma conversa. Um canal bidireccional, do início ao fim.

    O `ctx` é o primeiro argumento de propósito: é o contexto do cliente,
    e tem de vir de fora. Ver o cabeçalho do módulo.
    """

    ctx: Any
    ferramenta: Ferramenta
    instrucao: str
    voz: str
    #: Declaração da ferramenta. Separada do callback para o prompt poder
    #: mudar sem tocar no código que a executa.
    declaracao: Dict[str, Any] = field(
        default_factory=lambda: ferramenta_declarada(
            "consultar_dados",
            "Consulta os dados da empresa. Usa isto para qualquer pergunta "
            "sobre números, clientes, rotas, custos, vendas ou prazos.",
        )
    )
    conta: ContaDeTokens = field(default_factory=ContaDeTokens)

    _fluxo: Any = None
    _prompt: str = ""
    _conteudo_audio: str = ""
    _eventos: asyncio.Queue = field(default_factory=asyncio.Queue)
    _aberta: bool = False
    #: As consultas em curso.
    #:
    #: Guardadas por duas razões, e as duas doem. A primeira é que uma
    #: task sem dono pode ser recolhida pelo coletor de lixo a meio —
    #: a consulta desaparecia e o modelo ficava à espera para sempre.
    #:
    #: A segunda apareceu num teste: o ciclo de leitura terminava a fila
    #: de eventos enquanto uma consulta ainda corria, e o `APensar`
    #: dessa consulta chegava DEPOIS do fim. Ninguém o via — e é esse o
    #: evento que faz o cliente dizer «deixa-me ver». A última pergunta
    #: de cada sessão ficava sem recado.
    _consultas: set = field(default_factory=set)
    #: A última frase que a Sky disse, para não a repetir no ecrã.
    _ultimo_dito: str = ""

    # ── Abrir e fechar ──────────────────────────────────────────────

    async def abrir(self, cliente: Any) -> None:
        """Abre o canal e manda a abertura.

        O `cliente` entra por argumento para os testes poderem passar um
        duplo — e porque construí-lo aqui obrigaria este módulo a saber
        resolver credenciais, que não é trabalho dele.
        """
        from aws_sdk_bedrock_runtime.client import InvokeModelWithBidirectionalStreamOperationInput

        self._fluxo = await cliente.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=MODELO)
        )
        self._prompt = str(uuid.uuid4())
        self._aberta = True

        await self._mandar(
            {
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": 1024,
                            "topP": 0.9,
                            "temperature": 0.7,
                        }
                    }
                }
            }
        )
        await self._mandar(
            {
                "event": {
                    "promptStart": {
                        "promptName": self._prompt,
                        "textOutputConfiguration": {"mediaType": "text/plain"},
                        "audioOutputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": SAIDA_HZ,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "voiceId": self.voz,
                            "encoding": "base64",
                            "audioType": "SPEECH",
                        },
                        "toolUseOutputConfiguration": {"mediaType": "application/json"},
                        "toolConfiguration": {"tools": [self.declaracao]},
                    }
                }
            }
        )
        await self._bloco_de_texto("SYSTEM", self.instrucao)
        await self._abrir_audio()

    async def fechar(self) -> None:
        self._aberta = False
        for ev in (
            {
                "event": {
                    "contentEnd": {"promptName": self._prompt, "contentName": self._conteudo_audio}
                }
            },
            {"event": {"promptEnd": {"promptName": self._prompt}}},
            {"event": {"sessionEnd": {}}},
        ):
            try:
                await self._mandar(ev)
            except Exception:
                # A fechar, uma falha no meio não deve esconder as
                # seguintes nem rebentar para quem chamou.
                logger.debug("voz: falha a fechar a sessão", exc_info=True)
        try:
            await self._fluxo.input_stream.close()
        except Exception:
            logger.debug("voz: falha a fechar o canal", exc_info=True)

    # ── Falar para dentro ───────────────────────────────────────────

    async def ouvir_microfone(self, pcm: bytes) -> None:
        """Um pedaço do microfone, PCM16 mono a `ENTRADA_HZ`.

        ── Enquanto uma consulta está pendente, NÃO se manda áudio ────

        Isto não vem na documentação e só apareceu numa chamada a sério:
        mandar `audioInput` enquanto o modelo espera por um `toolResult`
        **invalida a sessão**, com um `ValidationException: Invalid input
        request` que não diz qual é o problema. A sessão morre e a pessoa
        fica sem resposta.

        As sondas não o apanharam por sorte: nelas o envio de áudio
        acabava poucas centenas de milissegundos depois do pedido. Esta
        classe alimentava silêncio durante a consulta inteira — que é o
        que o produto faz — e partiu logo.

        **O que isto custa, e fica dito:** não se pode ouvir a pessoa
        enquanto a consulta corre, portanto **não há barge-in durante o
        «a pensar»**. É uma limitação do modelo, não uma escolha nossa, e
        é mais uma razão para o `PRAZO_DA_FERRAMENTA` ser curto.
        """
        if not self._aberta or self._consultas:
            return
        await self._mandar(
            {
                "event": {
                    "audioInput": {
                        "promptName": self._prompt,
                        "contentName": self._conteudo_audio,
                        "content": base64.b64encode(pcm).decode(),
                    }
                }
            }
        )

    async def silencio(self, segundos: float = 0.032) -> None:
        """Alimenta silêncio — e **é obrigatório** enquanto não houver fala.

        O modelo desliga depois de `LIMITE_SEM_AUDIO` sem nada. Quem
        silencia o microfone e vai beber um café volta a uma sessão
        morta, a menos que alguém continue a alimentar.
        """
        amostras = int(ENTRADA_HZ * segundos)
        await self.ouvir_microfone(bytes(amostras * 2))

    # ── Ouvir de volta ──────────────────────────────────────────────

    def eventos(self) -> AsyncIterator[Evento]:
        """Os eventos da sessão, já no nosso vocabulário."""

        async def gerar() -> AsyncIterator[Evento]:
            while True:
                ev = await self._eventos.get()
                if ev is None:
                    break
                yield ev

        return gerar()

    async def escutar(self) -> None:
        """O ciclo que lê o canal. Corre como tarefa, até a sessão fechar.

        ⚠️ Esta tarefa tem de nascer **depois** de o contexto do cliente
        estar posto, se alguém a jusante o ler de uma variável de
        contexto. Aqui dentro não lemos — usamos `self.ctx` — e é essa a
        defesa: a ordem deixa de poder estragar nada.
        """
        try:
            _, saida = await self._fluxo.await_output()
            while True:
                res = await saida.receive()
                if res is None or res.value is None:
                    break
                await self._traduzir(json.loads(res.value.bytes_.decode("utf-8")).get("event", {}))
        except Exception as exc:
            logger.warning(
                "voz: sessão caiu (cliente=%s): %s",
                getattr(self.ctx, "slug", "?"),
                exc,
            )
            await self._eventos.put(Falhou(porque=f"{type(exc).__name__}: {exc}"))
        finally:
            # As consultas em curso ainda têm eventos para pôr — o
            # `APensar`, no mínimo. Terminar a fila antes delas fazia-os
            # chegar depois do fim, onde ninguém os vê.
            #
            # Com prazo: uma consulta pendurada não pode impedir a sessão
            # de fechar. O `PRAZO_DA_FERRAMENTA` já as corta uma a uma; a
            # margem aqui é para o caso de alguém o subir sem pensar
            # nisto.
            if self._consultas:
                try:
                    await asyncio.wait(
                        list(self._consultas),
                        timeout=PRAZO_DA_FERRAMENTA + 1,
                    )
                except Exception:
                    logger.debug("voz: falha a esperar consultas", exc_info=True)
            await self._eventos.put(None)

    # ── Tradução dos eventos da AWS para os nossos ──────────────────

    async def _traduzir(self, ev: Dict[str, Any]) -> None:
        if "textOutput" in ev:
            texto = ev["textOutput"].get("content", "") or ""
            # O papel decide o que isto é: `USER` é a TRANSCRIÇÃO da
            # pergunta (o ASR que hoje pagamos ao Transcribe), qualquer
            # outro é a Sky a falar.
            if ev["textOutput"].get("role") == "USER":
                await self._eventos.put(Ouvido(texto=texto))
            elif texto and texto != self._ultimo_dito:
                # ── A mesma frase chega DUAS vezes ────────────────────
                #
                # Medido numa chamada real: o mesmo `content`, palavra por
                # palavra, em dois eventos com `contentId` diferente — um
                # é a legenda da fala, o outro a saída de texto. Não há
                # campo que diga qual é qual.
                #
                # Sem isto, a legenda no ecrã aparece a dobrar. Comparar
                # com a anterior resolve-o e não tem falsos positivos:
                # ninguém diz a mesma frase inteira duas vezes de seguida
                # dentro de um turno.
                self._ultimo_dito = texto
                await self._eventos.put(Dito(texto=texto))

        if "audioOutput" in ev:
            await self._eventos.put(Audio(pcm=base64.b64decode(ev["audioOutput"]["content"])))

        if "userSpeechEnd" in ev:
            await self._eventos.put(FalaAcabou())

        if ev.get("interrupted") or "interruption" in ev:
            await self._eventos.put(Interrompido())

        if "usageEvent" in ev:
            self.conta.atualizar((ev["usageEvent"].get("details") or {}).get("total") or {})

        if "toolUse" in ev:
            # À parte, de propósito: esperar aqui bloqueava a leitura do
            # canal e perdíamos tudo o que o modelo mandasse entretanto
            # — incluindo o `interrupted`, que é o que precisamos de ver
            # mais depressa.
            #
            # Mas guardada: ver `_consultas`. Uma task sem referência
            # pode desaparecer a meio, e o fim do ciclo não pode chegar
            # antes dela.
            tarefa = asyncio.create_task(self._responder_ferramenta(ev["toolUse"]))
            self._consultas.add(tarefa)
            tarefa.add_done_callback(self._consultas.discard)

    async def _responder_ferramenta(self, pedido: Dict[str, Any]) -> None:
        pergunta = ""
        try:
            pergunta = json.loads(pedido.get("content") or "{}").get("pergunta") or ""
        except Exception:
            pergunta = str(pedido.get("content") or "")
        await self._eventos.put(APensar(pergunta=pergunta))

        try:
            resposta = await asyncio.wait_for(
                self.ferramenta(pergunta), timeout=PRAZO_DA_FERRAMENTA
            )
        except asyncio.TimeoutError:
            # **O erro vai em TEXTO, não como excepção.**
            #
            # Se não respondermos, o modelo espera — até ao limite dos
            # 55 s — e a sessão morre com a pessoa à espera. Mandar o
            # erro deixa-o DIZER que não conseguiu, que é melhor do que
            # o silêncio que a voz tem hoje.
            resposta = json.dumps({"erro": "A consulta demorou demasiado e foi cancelada."})
            logger.warning(
                "voz: ferramenta esgotou o prazo (cliente=%s, pergunta=%r)",
                getattr(self.ctx, "slug", "?"),
                pergunta[:120],
            )
        except Exception as exc:
            resposta = json.dumps({"erro": "Não consegui chegar aos dados neste momento."})
            logger.exception(
                "voz: ferramenta falhou (cliente=%s): %s",
                getattr(self.ctx, "slug", "?"),
                exc,
            )

        nome = str(uuid.uuid4())
        try:
            await self._mandar(
                {
                    "event": {
                        "contentStart": {
                            "promptName": self._prompt,
                            "contentName": nome,
                            "type": "TOOL",
                            "interactive": False,
                            "role": "TOOL",
                            "toolResultInputConfiguration": {
                                "toolUseId": pedido["toolUseId"],
                                "type": "TEXT",
                                "textInputConfiguration": {"mediaType": "text/plain"},
                            },
                        }
                    }
                }
            )
            await self._mandar(
                {
                    "event": {
                        "toolResult": {
                            "promptName": self._prompt,
                            "contentName": nome,
                            "content": resposta,
                        }
                    }
                }
            )
            await self._mandar(
                {"event": {"contentEnd": {"promptName": self._prompt, "contentName": nome}}}
            )
        except Exception:
            logger.exception(
                "voz: não consegui entregar o resultado da ferramenta " "(cliente=%s)",
                getattr(self.ctx, "slug", "?"),
            )

    # ── Canalização ─────────────────────────────────────────────────

    async def _mandar(self, evento: Dict[str, Any]) -> None:
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalInputPayloadPart,
            InvokeModelWithBidirectionalStreamInputChunk,
        )

        await self._fluxo.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=json.dumps(evento).encode("utf-8"))
            )
        )

    async def _bloco_de_texto(self, papel: str, texto: str) -> None:
        nome = str(uuid.uuid4())
        await self._mandar(
            {
                "event": {
                    "contentStart": {
                        "promptName": self._prompt,
                        "contentName": nome,
                        "type": "TEXT",
                        "interactive": True,
                        "role": papel,
                        "textInputConfiguration": {"mediaType": "text/plain"},
                    }
                }
            }
        )
        await self._mandar(
            {
                "event": {
                    "textInput": {
                        "promptName": self._prompt,
                        "contentName": nome,
                        "content": texto,
                    }
                }
            }
        )
        await self._mandar(
            {"event": {"contentEnd": {"promptName": self._prompt, "contentName": nome}}}
        )

    async def _abrir_audio(self) -> None:
        """Abre UM bloco de áudio para a sessão toda.

        Não um por turno: o modelo faz o seu próprio endpointing sobre o
        fluxo contínuo, e é isso que dá o fim de turno semântico. Fechar
        e reabrir por turno seria voltar a decidir nós quando a pessoa
        acabou de falar — que é o defeito que isto vem resolver.
        """
        self._conteudo_audio = str(uuid.uuid4())
        await self._mandar(
            {
                "event": {
                    "contentStart": {
                        "promptName": self._prompt,
                        "contentName": self._conteudo_audio,
                        "type": "AUDIO",
                        "interactive": True,
                        "role": "USER",
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": ENTRADA_HZ,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "audioType": "SPEECH",
                            "encoding": "base64",
                        },
                    }
                }
            }
        )


async def abrir_cliente() -> Any:
    """O cliente do Bedrock, com o transporte que isto exige.

    **O transporte tem de ser o CRT.** O `aws-sdk-bedrock-runtime` usa
    `aiohttp` por omissão, e o `aiohttp` não faz event streaming
    bidireccional — a chamada é recusada com `UnsupportedTransportError`.
    """
    from aws_sdk_bedrock_runtime.client import AsyncBedrockRuntimeClient, AsyncBedrockRuntimeConfig
    from smithy_http.aio.crt import AWSCRTHTTPClient

    return AsyncBedrockRuntimeClient(
        config=await AsyncBedrockRuntimeConfig.resolve(region=REGIAO, transport=AWSCRTHTTPClient())
    )


def esta_ligada() -> bool:
    """A bandeira. Desligada por omissão — a cascata fica intacta.

    O Live Talk é demonstrado a clientes: não se troca o motor sem poder
    voltar atrás numa variável de ambiente.
    """
    return os.getenv("VOICE_ENGINE", "").strip().lower() == "sonic"
