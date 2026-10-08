# -*- coding: utf-8 -*-
"""A coreografia do WebSocket servido pelo Sonic.

Verificada com um socket falso, sem AWS e sem base de dados — tudo o que
vem de fora vem por argumento, e foi para isto que vem.

── O que aqui pode correr mal, e porque dói ───────────────────────

**A sessão morrer calada aos 55 s.** O modelo desliga sem áudio, e
«ninguém fala» inclui o caso em que a pessoa silenciou o microfone e foi
beber um café. Silenciar tem de ser parar de MANDAR O MICROFONE, não
parar de alimentar.

**Abrir sem saber o projecto.** Sem o `start` não se sabe de que
projecto é a pergunta, e adivinhar foi exactamente o defeito do #713 —
perguntar dentro de um projecto sem dados respondia com os dados de
outro.

**Fechar sem guardar, ou não fechar por não conseguir guardar.** Perder
a gravação é mau; derrubar o fecho por causa disso deixava a app sem o
`final`, à espera para sempre.

**A cascata ser tocada.** A bandeira desligada tem de levar ao caminho
de hoje, sem passar por nada disto.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

from src.services import voz_fala_a_fala as falada
from src.services import voz_sessao_sonic as sonic


class _Ctx:
    slug = "cliente-de-teste"


class _User:
    id = "user-1"
    preferences: Dict[str, Any] = {}


# ── Um socket falso ─────────────────────────────────────────────────


class _Socket:
    """Entrega as mensagens que lhe dermos e guarda o que lhe mandarem."""

    def __init__(self, entrada: List[Dict[str, Any]]) -> None:
        self._entrada = list(entrada)
        self.texto: List[Dict[str, Any]] = []
        self.binario: List[bytes] = []
        self.fechado_com: Optional[int] = None

    async def receive(self) -> Dict[str, Any]:
        if self._entrada:
            return self._entrada.pop(0)
        # Sem mais nada: a pessoa desligou.
        return {"type": "websocket.disconnect"}

    async def send_text(self, s: str) -> None:
        self.texto.append(json.loads(s))

    async def send_bytes(self, b: bytes) -> None:
        self.binario.append(b)

    async def close(self, code: int = 1000) -> None:
        self.fechado_com = code


def _start(**kw: Any) -> Dict[str, Any]:
    base = {
        "type": "control",
        "action": "start",
        "page_id": "pagina-1",
        "space_id": "projeto-1",
        "locale": "pt",
    }
    base.update(kw)
    return {"text": json.dumps(base)}


class _SessaoFalsa:
    """Uma `SessaoFalada` de mentira, para medir a coreografia."""

    def __init__(self, eventos: List[falada.Evento] | None = None) -> None:
        self.eventos_a_dar = list(eventos or [])
        self.microfone: List[bytes] = []
        self.silencios: List[float] = []
        self.aberta = False
        self.fechada = False
        self.conta = falada.ContaDeTokens()
        self._fila: asyncio.Queue = asyncio.Queue()

    async def abrir(self, _cliente: Any) -> None:
        self.aberta = True

    async def fechar(self) -> None:
        self.fechada = True

    async def ouvir_microfone(self, pcm: bytes) -> None:
        self.microfone.append(pcm)

    async def silencio(self, segundos: float = 0.032) -> None:
        self.silencios.append(segundos)

    async def escutar(self) -> None:
        for ev in self.eventos_a_dar:
            await self._fila.put(ev)
        await self._fila.put(None)

    def eventos(self):
        async def gerar():
            while True:
                ev = await self._fila.get()
                if ev is None:
                    break
                yield ev

        return gerar()


def _montar(monkeypatch, sessao: _SessaoFalsa) -> None:
    monkeypatch.setattr(sonic.falada, "SessaoFalada", lambda **_kw: sessao, raising=True)


async def _servir(
    monkeypatch,
    entrada: List[Dict[str, Any]],
    sessao: _SessaoFalsa,
    *,
    responder=None,
    persistir=None,
) -> _Socket:
    _montar(monkeypatch, sessao)
    s = _Socket(entrada)

    async def responder_nada(*_a, **_k):
        return "x"

    async def guardar(**_k):
        return "conv-1"

    async def cliente():
        return object()

    await asyncio.wait_for(
        sonic.servir(
            s,
            user=_User(),
            ctx=_Ctx(),
            responder=responder or responder_nada,
            persistir=persistir or guardar,
            abrir_cliente=cliente,
        ),
        timeout=5,
    )
    return s


# ── A bandeira ──────────────────────────────────────────────────────


class TestACascataNaoEToacada:
    def test_a_bandeira_desligada_leva_ao_caminho_de_hoje(self, monkeypatch):
        """A bifurcação está ANTES de tudo o que é da cascata.

        É o que permite voltar atrás numa variável de ambiente, num
        produto que é demonstrado a clientes.
        """
        import inspect

        from src.api.v1 import voice

        fonte = inspect.getsource(voice.voice_session_ws)
        i = fonte.index("esta_ligada()")
        # Depois do `accept` (já há socket) e antes de a cascata ARRANCAR
        # o seu provedor, que é o que não deve acontecer.
        #
        # `build_voice_provider()` com parênteses: a primeira versão
        # procurou o nome sem eles e apanhou o `import` lá em cima — o
        # teste chumbava a dizer que a bifurcação estava no sítio errado
        # quando estava no sítio certo.
        assert fonte.index("websocket.accept") < i
        assert i < fonte.index("provider = build_voice_provider()")

    def test_e_o_caminho_do_sonic_devolve_sem_correr_a_cascata(self):
        import inspect

        from src.api.v1 import voice

        fonte = inspect.getsource(voice.voice_session_ws)
        i = fonte.index("esta_ligada()")
        bloco = fonte[i : fonte.index("async def send", i)]
        assert "return" in bloco, (
            "sem o `return`, a cascata corre DEPOIS do Sonic no mesmo "
            "socket — duas máquinas de estado a falar para a mesma app"
        )


# ── O arranque ──────────────────────────────────────────────────────


class TestSemStartNaoSeAbre:
    @pytest.mark.asyncio
    async def test_desiste_e_fecha(self, monkeypatch):
        """Sem o `start` não se sabe de que projecto é a pergunta.

        Abrir sem isso era voltar ao defeito do #713: perguntar dentro de
        um projecto sem dados respondia com os dados de outro.
        """
        monkeypatch.setattr(sonic, "PRAZO_DO_START", 0.05)
        sessao = _SessaoFalsa()
        s = await _servir(monkeypatch, [], sessao)
        assert s.fechado_com == 1002
        assert not sessao.aberta

    @pytest.mark.asyncio
    async def test_o_audio_que_chega_antes_e_deitado_fora(self, monkeypatch):
        """E está certo: ainda não se sabe para onde vai."""
        sessao = _SessaoFalsa()
        await _servir(
            monkeypatch,
            [{"bytes": b"\x01\x02"}, _start(), {"type": "websocket.disconnect"}],
            sessao,
        )
        assert sessao.microfone == []


class TestOArranqueQueFalha:
    @pytest.mark.asyncio
    async def test_diz_que_falhou_em_vez_de_calar(self, monkeypatch):
        """O silêncio já foi corrigido três vezes neste produto."""
        sessao = _SessaoFalsa()

        async def rebenta(_c):
            raise RuntimeError("sem credenciais")

        sessao.abrir = rebenta  # type: ignore[assignment]
        s = await _servir(monkeypatch, [_start()], sessao)
        erros = [m for m in s.texto if m.get("type") == "error"]
        assert erros and erros[0]["code"] == "voice_unavailable"
        assert s.fechado_com == 1011


# ── O microfone e o silêncio ────────────────────────────────────────


class TestOMicrofone:
    @pytest.mark.asyncio
    async def test_o_audio_segue_para_a_sessao(self, monkeypatch):
        sessao = _SessaoFalsa()
        await _servir(
            monkeypatch,
            [_start(), {"bytes": b"\x01\x02"}, {"bytes": b"\x03\x04"}],
            sessao,
        )
        assert sessao.microfone == [b"\x01\x02", b"\x03\x04"]

    @pytest.mark.asyncio
    async def test_silenciar_para_de_mandar_o_MICROFONE(self, monkeypatch):
        sessao = _SessaoFalsa()
        await _servir(
            monkeypatch,
            [
                _start(),
                {"text": json.dumps({"type": "control", "action": "mute"})},
                {"bytes": b"\x01\x02"},
                {"text": json.dumps({"type": "control", "action": "unmute"})},
                {"bytes": b"\x03\x04"},
            ],
            sessao,
        )
        assert sessao.microfone == [b"\x03\x04"], "mandou o microfone com a sessão silenciada"

    def test_mas_a_batida_do_silencio_cabe_no_limite(self):
        """O que impede a sessão de morrer calada aos 55 s.

        «Ninguém fala» inclui o caso em que a pessoa silenciou o
        microfone e foi beber um café. E o silêncio não é facturado —
        medido — por isso não há razão para ser avarento.
        """
        assert sonic.BATIDA_DO_SILENCIO < falada.LIMITE_SEM_AUDIO / 10


# ── Os controles antigos ────────────────────────────────────────────


class TestOsControlesQueOsClientesAntIGOSMandam:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("accao", ["stop", "end_turn", "barge_in"])
    async def test_nao_fecham_a_sessao(self, monkeypatch, accao):
        """Sem OTA, um cliente antigo anda por aí semanas.

        O `stop`/`end_turn` eram o fim de turno do premir-para-falar, que
        já não existe. Aqui o turno fecha-se por si — e se estes o
        fechassem, a sessão caía à primeira.
        """
        sessao = _SessaoFalsa()
        s = await _servir(
            monkeypatch,
            [
                _start(),
                {"text": json.dumps({"type": "control", "action": accao})},
                {"bytes": b"\x01"},
            ],
            sessao,
        )
        assert sessao.microfone == [
            b"\x01"
        ], f"`{accao}` fechou a sessão — o áudio depois dele não passou"
        assert s.fechado_com is None

    @pytest.mark.asyncio
    async def test_mas_o_end_fecha(self, monkeypatch):
        sessao = _SessaoFalsa()
        await _servir(
            monkeypatch,
            [
                _start(),
                {"text": json.dumps({"type": "control", "action": "end"})},
                {"bytes": b"\x01"},
            ],
            sessao,
        )
        assert sessao.microfone == []
        assert sessao.fechada


# ── O que sai para a app ────────────────────────────────────────────


class TestOQueAAppRecebe:
    @pytest.mark.asyncio
    async def test_a_transcricao_e_a_legenda_chegam(self, monkeypatch):
        sessao = _SessaoFalsa(
            [
                falada.Ouvido(texto="quantas rotas?"),
                falada.Dito(texto="São duas."),
            ]
        )
        s = await _servir(monkeypatch, [_start()], sessao)
        tipos = [m["type"] for m in s.texto]
        assert "partial_transcript" in tipos
        assert "sky_text" in tipos

    @pytest.mark.asyncio
    async def test_o_audio_vai_em_BINARIO(self, monkeypatch):
        """Em base64 num JSON era inflá-lo por nada."""
        sessao = _SessaoFalsa([falada.Audio(pcm=b"\x01\x02\x03")])
        s = await _servir(monkeypatch, [_start()], sessao)
        assert s.binario == [b"\x01\x02\x03"]

    @pytest.mark.asyncio
    async def test_e_acaba_sempre_com_final_e_ended(self, monkeypatch):
        """Sem o `final`, a app fica à espera para sempre."""
        sessao = _SessaoFalsa()
        s = await _servir(monkeypatch, [_start()], sessao)
        tipos = [m["type"] for m in s.texto]
        assert tipos[-2:] == ["final", "state"]
        assert s.texto[-1]["value"] == "ended"


# ── Guardar a conversa ──────────────────────────────────────────────


class TestGuardarAConversa:
    @pytest.mark.asyncio
    async def test_os_dois_lados_vao_para_a_gravacao(self, monkeypatch):
        guardados: List[Any] = []

        async def guardar(**kw):
            guardados.append(kw["turnos"])
            return "conv-9"

        sessao = _SessaoFalsa(
            [
                falada.Ouvido(texto="quantas rotas?"),
                falada.Dito(texto="São duas."),
            ]
        )
        s = await _servir(monkeypatch, [_start()], sessao, persistir=guardar)
        assert guardados == [[("user", "quantas rotas?"), ("sky", "São duas.")]]
        final = [m for m in s.texto if m["type"] == "final"][0]
        assert final["message_id"] == "conv-9"

    @pytest.mark.asyncio
    async def test_e_nao_se_guarda_uma_conversa_vazia(self, monkeypatch):
        chamou = False

        async def guardar(**_kw):
            nonlocal chamou
            chamou = True
            return "x"

        await _servir(monkeypatch, [_start()], _SessaoFalsa(), persistir=guardar)
        assert not chamou

    @pytest.mark.asyncio
    async def test_falhar_a_guardar_NAO_derruba_o_fecho(self, monkeypatch):
        """Perder a gravação é mau; deixar a app à espera é pior."""

        async def rebenta(**_kw):
            raise RuntimeError("a base não respondeu")

        sessao = _SessaoFalsa([falada.Ouvido(texto="olá")])
        s = await _servir(monkeypatch, [_start()], sessao, persistir=rebenta)
        finais = [m for m in s.texto if m["type"] == "final"]
        assert finais and finais[0]["message_id"] is None
        assert s.texto[-1] == {"type": "state", "value": "ended"}


# ── A voz e a língua ────────────────────────────────────────────────


class TestAVozEALingua:
    @pytest.mark.parametrize("locale,esperada", [("pt", "ines"), ("es", "lupe"), ("en", "matthew")])
    def test_cada_lingua_tem_a_sua_voz(self, locale, esperada):
        assert sonic.voz_do_locale(locale) == esperada

    def test_uma_lingua_desconhecida_cai_num_valor_VALIDO(self):
        """Cair num id que o modelo não conhece fazia a abertura FALHAR."""
        assert sonic.voz_do_locale("zz") in sonic.VOZES.values()

    def test_uma_voz_do_catalogo_do_POLLY_e_ignorada(self):
        """O ecrã de definições guarda «Inês», «Lúcia» — nomes do Polly.

        Mandá-los ao Sonic fazia a abertura falhar, e o sintoma seria «a
        voz não funciona» sem nada que o explicasse.
        """
        assert sonic.voz_do_locale("pt", "Inês") == "ines"
        assert sonic.voz_do_locale("pt", "Joanna") == "ines"

    def test_mas_uma_voz_do_catalogo_do_SONIC_vale(self):
        assert sonic.voz_do_locale("pt", "lupe") == "lupe"

    @pytest.mark.parametrize("locale", ["pt", "es", "en"])
    def test_a_instrucao_pede_a_lingua_e_proibe_listas(self, locale):
        """Listas e números enumerados ditos em voz alta são péssimos."""
        texto = sonic.instrucao_de_sistema(locale)
        assert "consultar_dados" in texto
        assert "listas" in texto or "lists" in texto
        assert "invent" in texto.lower()
