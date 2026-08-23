"""Uma frase falada não acaba na primeira pausa.

O Lucas fez uma pergunta longa em voz alta e a Sky recebeu **«reven»** — o
primeiro pedaço, e mais nada. A resposta que veio a seguir era sobre receita,
por acaso, mas não era à pergunta dele.

**A causa.** O Transcribe emite SEGMENTOS e fecha um a cada pausa de fala —
uma vírgula chega. Cada fecho vem marcado ``final``, e o código tratava o
primeiro ``final`` como o fim do turno: mandava a primeira fatia para a Sky e,
a partir daí, ``turn_active`` mandava deitar fora tudo o resto que ele dissesse.

``final`` do Transcribe quer dizer «fechei esta frase», não «esta pessoa
acabou de falar». São coisas diferentes e o código lia uma pela outra — e
quanto mais devagar e mais bem articulada a pergunta, pior o estrago.

Estes testes conduzem o WebSocket com um fornecedor que emite dois segmentos,
que é o que o Transcribe faz com qualquer frase com uma pausa no meio.
"""

import asyncio
import json
import types
from typing import AsyncIterator, Dict, List

import pytest

from src.api.v1.voice import VOICE_SUBPROTOCOL

_UID = "00000000-0000-0000-0000-000000000001"

#: Os dois pedaços de UMA pergunta, como o Transcribe os entrega: dois eventos,
#: os dois marcados `final`, separados por uma pausa de respiração.
PRIMEIRO = "quanto foi a receita"
SEGUNDO = "no mês passado por cliente"


def _mock_auth(monkeypatch):
    monkeypatch.setattr(
        "src.core.security.verify_token",
        lambda token, token_type="access": {"sub": _UID},
    )

    async def _get_by_id(self, uid):
        return types.SimpleNamespace(id=_UID)

    monkeypatch.setattr("src.repositories.user.UserRepository.get_by_id", _get_by_id)


class FornecedorDeDoisSegmentos:
    """Um Transcribe de mentira que parte a frase ao meio, como o verdadeiro.

    Emite os dois segmentos assim que chega áudio. Não sintetiza nada de útil
    — o que se está a medir é o que chega à Sky, não o que sai dos altifalantes.
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        self._closed = False
        self._ja = False

    async def start(self, lang: str) -> None:  # noqa: D102
        pass

    async def feed_audio(self, chunk: bytes) -> None:
        if self._ja:
            return
        self._ja = True
        await self._q.put({"text": PRIMEIRO, "final": True})
        # A pausa de respiração no meio da frase. Bem abaixo do silêncio que
        # fecha o turno — é essa a diferença que o código tem de saber ver.
        await asyncio.sleep(0.05)
        await self._q.put({"text": SEGUNDO, "final": True})

    async def flush(self) -> None:  # noqa: D102
        pass

    async def restart_stt(self) -> None:  # noqa: D102
        pass

    async def transcripts(self) -> AsyncIterator[Dict]:
        while not self._closed:
            ev = await self._q.get()
            if ev is None:
                break
            yield ev

    async def synthesize(self, text: str, voice: str) -> AsyncIterator[bytes]:
        yield b"\x00\x01" * 8

    async def close(self) -> None:
        self._closed = True
        await self._q.put(None)


@pytest.fixture
def perguntas_recebidas(monkeypatch):
    """O que chegou à Sky. É a única coisa que este ficheiro mede."""
    recebidas: List[str] = []

    async def _resposta(user, page_id, text, ctx, locale="en"):
        recebidas.append(text)
        return "Foram 1.234,00 €."

    monkeypatch.setattr("src.api.v1.voice._voice_answer", _resposta)
    # No `voice_pipeline` e não no `voice`: o `build_voice_provider` é
    # importado DENTRO do handler, portanto o nome no módulo da rota só existe
    # depois de a ligação abrir — remendá-lo lá não apanha nada.
    monkeypatch.setattr(
        "src.services.voice_pipeline.build_voice_provider",
        lambda: FornecedorDeDoisSegmentos(),
    )
    # 60 ms em vez de 1,6 s: um teste que espera o tempo real é um teste que
    # alguém acaba por apagar. A pausa do fornecedor (50 ms) fica por baixo.
    monkeypatch.setattr("src.api.v1.voice.SILENCIO_QUE_FECHA_O_TURNO", 0.35)
    return recebidas


def _falar(ws, quadros: int = 4) -> None:
    alto = (4000).to_bytes(2, "little", signed=True) * 160
    for _ in range(quadros):
        ws.send_bytes(alto)


def _escutar(ws, ate: float = 3.0):
    """Lê mensagens até a Sky começar a falar, ou até se esgotar a paciência."""
    vistos = []
    for _ in range(60):
        m = ws.receive()
        if m.get("type") == "websocket.close":
            break
        if m.get("bytes") is not None:
            continue
        d = json.loads(m["text"])
        vistos.append(d)
        if d.get("type") == "state" and d.get("value") == "speaking":
            break
    return vistos


def test_a_pergunta_chega_inteira(client, monkeypatch, perguntas_recebidas):
    """**As duas metades, e não só a primeira.**

    É o defeito exacto: uma pergunta longa chegava cortada na primeira pausa.
    """
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start", "locale": "pt"}))
        _falar(ws)
        _escutar(ws)
        ws.send_text(json.dumps({"type": "control", "action": "end"}))

    assert perguntas_recebidas, "a Sky não recebeu pergunta nenhuma"
    pergunta = perguntas_recebidas[0]
    assert PRIMEIRO in pergunta
    assert SEGUNDO in pergunta, (
        "só chegou a primeira metade — é o defeito do «reven»: "
        f"recebido {pergunta!r}"
    )


def test_a_sky_so_responde_uma_vez(client, monkeypatch, perguntas_recebidas):
    """Dois segmentos são UMA pergunta, não duas.

    Sem a espera pelo silêncio, o remendo óbvio seria mandar cada segmento à
    Sky — e ela responderia duas vezes à mesma pergunta partida ao meio.
    """
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start", "locale": "pt"}))
        _falar(ws)
        _escutar(ws)
        ws.send_text(json.dumps({"type": "control", "action": "end"}))

    assert len(perguntas_recebidas) == 1, perguntas_recebidas


def test_o_ecra_mostra_o_que_ja_foi_dito(client, monkeypatch, perguntas_recebidas):
    """O que se vê a escrever não pode desaparecer a cada pausa.

    O ecrã mostrava só o segmento em curso. Ao fechar um segmento, o texto
    anterior sumia e ficava «Listening…» com nada por baixo — que é o outro
    sintoma que o Lucas apontou: «aparece listening mas não vejo ele a escutar
    nada».
    """
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start", "locale": "pt"}))
        _falar(ws)
        vistos = _escutar(ws)
        ws.send_text(json.dumps({"type": "control", "action": "end"}))

    textos = [d["text"] for d in vistos if d.get("type") == "partial_transcript"]
    # Nenhum dos textos mostrados pode ser SÓ a segunda metade: quando a
    # segunda chega, a primeira tem de continuar lá.
    assert not any(t.strip() == SEGUNDO for t in textos), textos


def test_silenciar_deita_fora_a_frase_a_meio(client, monkeypatch, perguntas_recebidas):
    """**Silenciar é dizer «esquece o que eu estava a dizer».**

    O Lucas silenciou a meio e a pergunta partida foi à mesma. Silenciar tem
    de limpar o que estava em curso, senão o botão do microfone não desliga o
    microfone — só o esconde.
    """
    _mock_auth(monkeypatch)
    with client.websocket_connect(
        "/api/v1/voice/session", subprotocols=[VOICE_SUBPROTOCOL, "tok"]
    ) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start", "locale": "pt"}))
        _falar(ws, quadros=1)
        # Silenciar ANTES de o silêncio fechar o turno.
        ws.send_text(json.dumps({"type": "control", "action": "mute"}))
        # `end` já a seguir, e drenar até fechar. NÃO ficar à espera de um
        # «speaking» que não deve chegar: um teste que espera pelo sintoma que
        # está a proibir bloqueia para sempre quando o código está certo — e
        # foi o que aconteceu à primeira versão deste.
        ws.send_text(json.dumps({"type": "control", "action": "end"}))
        for _ in range(30):
            m = ws.receive()
            if m.get("type") == "websocket.close":
                break

    assert perguntas_recebidas == [], (
        "silenciou-se e a frase a meio foi na mesma para a Sky: "
        f"{perguntas_recebidas}"
    )
