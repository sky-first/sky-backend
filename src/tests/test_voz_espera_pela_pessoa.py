# -*- coding: utf-8 -*-
"""A Sky espera que a pessoa acabe — com áudio fabricado e um Sonic falso.

> «¿Cuál es el precio del gasoil…» — e a Sky responde a meio, numa
> pausa curta. — Lucas, 12/10/2026 (segunda vez).

O Sonic verdadeiro fecha uma frase que SOA completa ~400 ms depois de a
voz parar (medido, `docs/a-voz-medida-nova-sonic.md`), e o
`endpointingSensitivity: LOW` não muda isso. O `_SonicFalso` aqui faz o
mesmo: fecha o turno ao fim de N segundos de silêncio seguido depois de
voz. Com N = 0,4 é o pior caso (frase que soa acabada); com N = 2,0 é o
tecto do LOW (frase que soa a meio).

O que se prova:

  * uma pausa de 700 ms a meio da frase NÃO fecha o turno — nem com o
    Sonic no pior caso;
  * 1,6 s de silêncio depois de uma pergunta completa fecham-no;
  * um bordão («eh») ou uma preposição («de») no fim estica a espera;
  * a escolha «normal» responde mais cedo do que a «paciente»;
  * o ditado (`push-to-talk`) não passa pelo portão — fica como estava.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
from typing import Any, List, Optional

import pytest

from src.services import voz_paciencia as vp

HZ = vp.HZ
#: O microfone manda pedaços de 100 ms, como a app.
PEDACO_S = 0.1


def _fala(segundos: float) -> bytes:
    """Voz: um tom com amplitude de fala normal ao microfone."""
    n = int(HZ * segundos)
    amostras = (int(6000 * math.sin(2 * math.pi * 180 * i / HZ)) for i in range(n))
    return b"".join(int(a).to_bytes(2, "little", signed=True) for a in amostras)


def _silencio(segundos: float, ruido: int = 60) -> bytes:
    """Silêncio de sala: ruído baixo, não zeros — um telemóvel nunca dá zeros."""
    rnd = random.Random(7)
    n = int(HZ * segundos)
    return b"".join(rnd.randint(-ruido, ruido).to_bytes(2, "little", signed=True) for _ in range(n))


def _pedacos(pcm: bytes, segundos: float = PEDACO_S):
    passo = int(HZ * segundos) * 2
    for i in range(0, len(pcm), passo):
        yield pcm[i : i + passo]


class _SonicFalso:
    """Fecha o turno ao fim de `fecha_s` de silêncio depois de ter ouvido voz."""

    def __init__(self, fecha_s: float) -> None:
        self.fecha_s = fecha_s
        self._ouviu_voz = False
        self._silencio = 0.0
        self.fechou = False
        self.maior_pausa = 0.0

    def ouvir(self, pcm: bytes) -> None:
        for i in range(0, len(pcm) - 639, 640):
            janela = pcm[i : i + 640]
            if vp._rms(janela) > vp.LIMIAR_MINIMO:
                self._ouviu_voz = True
                self._silencio = 0.0
                continue
            if self._ouviu_voz and not self.fechou:
                self._silencio += vp.JANELA_S
                self.maior_pausa = max(self.maior_pausa, self._silencio)
                if self._silencio >= self.fecha_s - 1e-9:
                    self.fechou = True


def _conversa(
    partes: List[tuple],
    *,
    sonic_fecha_s: float,
    portao: Optional[vp.PortaoDaVez] = None,
) -> tuple:
    """Passa a conversa pelo portão (ou directa) e devolve (sonic, quando fechou).

    `partes`: ("fala", s) | ("pausa", s) | ("texto", legenda). `quando` é o
    instante, em segundos de microfone, em que o Sonic fechou o turno.
    """
    sonic = _SonicFalso(sonic_fecha_s)
    relogio = 0.0
    quando: Optional[float] = None
    for tipo, valor in partes:
        if tipo == "texto":
            if portao is not None:
                portao.ouvi_texto(valor)
            continue
        pcm = _fala(valor) if tipo == "fala" else _silencio(valor)
        for p in _pedacos(pcm):
            relogio += len(p) / 2 / HZ
            saida = portao.ouvir(p) if portao is not None else [p]
            for s in saida:
                sonic.ouvir(s)
            if sonic.fechou and quando is None:
                quando = relogio
    return sonic, quando


# ── O defeito, reproduzido ──────────────────────────────────────────


def test_sem_portao_o_sonic_corta_na_pausa_de_700_ms():
    """O que o Lucas viveu: sem o portão, a pausa a meio chega ao Sonic."""
    sonic, quando = _conversa(
        [("fala", 1.6), ("pausa", 0.7), ("fala", 0.9), ("pausa", 2.0)],
        sonic_fecha_s=0.4,
    )
    assert sonic.fechou
    assert quando is not None and quando < 1.6 + 0.7, "fechou a meio da frase"


# ── O que se pediu ──────────────────────────────────────────────────


@pytest.mark.parametrize("sonic_fecha_s", [0.4, 2.0])
def test_pausa_de_700_ms_a_meio_nao_fecha_o_turno(sonic_fecha_s):
    portao = vp.PortaoDaVez()
    sonic, _ = _conversa(
        [
            ("texto", "¿Cuál es el precio del gasoil"),
            ("fala", 1.6),
            ("pausa", 0.7),
            ("fala", 0.9),
        ],
        sonic_fecha_s=sonic_fecha_s,
        portao=portao,
    )
    assert not sonic.fechou
    assert portao.entregas == 0
    # O Sonic nunca ouviu mais do que a pausa de respiração.
    assert sonic.maior_pausa <= vp.PASSAGEM_S + 0.05


@pytest.mark.parametrize("paciencia", ["normal", "patient"])
@pytest.mark.parametrize("sonic_fecha_s", [0.4, 2.0])
def test_1_6_s_depois_de_uma_pergunta_completa_fecha_o_turno(paciencia, sonic_fecha_s):
    portao = vp.PortaoDaVez(paciencia=vp.paciencia_de(paciencia))
    sonic, quando = _conversa(
        [
            ("fala", 1.6),
            ("pausa", 0.7),
            ("fala", 0.9),
            ("texto", "¿Cuál es el precio del gasoil en Madrid?"),
            ("pausa", 1.6),
        ],
        sonic_fecha_s=sonic_fecha_s,
        portao=portao,
    )
    assert sonic.fechou
    assert portao.entregas == 1
    fim_da_fala = 1.6 + 0.7 + 0.9
    assert quando is not None and quando - fim_da_fala <= 1.6 + 1e-6


def test_a_pausa_inteira_nao_chega_ao_sonic_antes_da_paciencia():
    """1,3 s de pausa e volta a falar: com a paciente (1,4 s) é uma frase só."""
    portao = vp.PortaoDaVez()
    sonic, _ = _conversa(
        [("fala", 1.0), ("pausa", 1.3), ("fala", 0.8)],
        sonic_fecha_s=0.4,
        portao=portao,
    )
    assert not sonic.fechou


def test_normal_responde_mais_cedo_do_que_paciente():
    conversa = [("texto", "¿Cuántos pedidos hay?"), ("fala", 1.2), ("pausa", 3.0)]
    _, normal = _conversa(
        conversa, sonic_fecha_s=2.0, portao=vp.PortaoDaVez(paciencia=vp.paciencia_de("normal"))
    )
    _, paciente = _conversa(
        conversa, sonic_fecha_s=2.0, portao=vp.PortaoDaVez(paciencia=vp.paciencia_de("patient"))
    )
    assert normal is not None and paciente is not None
    assert normal < paciente
    assert normal - 1.2 == pytest.approx(vp.PACIENCIAS["normal"].base_s, abs=0.11)
    assert paciente - 1.2 == pytest.approx(vp.PACIENCIAS["patient"].base_s, abs=0.11)


@pytest.mark.parametrize(
    "legenda",
    [
        "¿Cuál es el precio del gasoil, eh",
        "Cuál es el precio del gasoil o sea",
        "¿Cuál es el precio del gasoil, pues",
        "Bueno",
        "¿Cuál es el precio de",
        "dame las ventas en",
        "¿Cuál es el",
        "quanto faturámos na semana, hum",
        "what was the revenue of",
    ],
)
def test_um_bordao_ou_preposicao_no_fim_estica_a_espera(legenda):
    """1,8 s de silêncio fecham uma pergunta acabada, mas não «…de» nem «…eh»."""
    assert vp.PACIENCIAS["patient"].base_s < 1.8 < vp.PACIENCIAS["patient"].hesitacao_s
    portao = vp.PortaoDaVez()
    sonic, _ = _conversa(
        [("fala", 1.4), ("texto", legenda), ("pausa", 1.8), ("fala", 0.8)],
        sonic_fecha_s=0.4,
        portao=portao,
    )
    assert not sonic.fechou, legenda
    assert portao.entregas == 0


def test_mesmo_a_hesitar_acaba_por_fechar():
    """Quem diz «eh» e se cala de vez não fica à espera para sempre."""
    portao = vp.PortaoDaVez()
    sonic, quando = _conversa(
        [("fala", 1.4), ("texto", "el precio del gasoil, eh"), ("pausa", 3.0)],
        sonic_fecha_s=2.0,
        portao=portao,
    )
    assert sonic.fechou
    assert quando is not None and quando - 1.4 == pytest.approx(
        vp.PACIENCIAS["patient"].hesitacao_s, abs=0.11
    )


@pytest.mark.parametrize(
    "texto, hesita",
    [
        ("¿Cuál es el precio del gasoil?", False),
        ("¿Vendimos más o no?", False),
        ("Quantos clientes temos?", False),
        ("el precio de", True),
        ("eh", True),
        ("o sea", True),
        ("Bueno.", True),
        ("", False),
    ],
)
def test_acaba_a_hesitar(texto, hesita):
    assert vp.acaba_a_hesitar(texto) is hesita


def test_paciencia_por_omissao_e_a_paciente():
    assert vp.paciencia_de(None) == vp.PACIENCIAS["patient"]
    assert vp.paciencia_de("qualquer") == vp.PACIENCIAS["patient"]
    assert vp.paciencia_de("paciente") == vp.PACIENCIAS["patient"]
    assert vp.paciencia_de("normal") == vp.PACIENCIAS["normal"]


def test_um_clique_na_pausa_nao_reabre_a_frase():
    """Uma janela de 20 ms com som (pancada na mesa) não conta como voz."""
    portao = vp.PortaoDaVez()
    pcm = _fala(1.0) + _silencio(0.8) + _fala(0.02) + _silencio(1.0)
    sonic = _SonicFalso(2.0)
    for p in _pedacos(pcm):
        for s in portao.ouvir(p):
            sonic.ouvir(s)
    assert portao.entregas == 1
    assert sonic.fechou


def test_o_audio_inteiro_passa_antes_de_a_pessoa_falar():
    """Antes da voz, tudo segue: é o que mantém a sessão do Sonic viva."""
    portao = vp.PortaoDaVez()
    pcm = _silencio(3.0)
    saiu = b"".join(b for p in _pedacos(pcm, 0.033) for b in portao.ouvir(p))
    assert saiu == pcm[: len(saiu)]
    assert len(pcm) - len(saiu) < 640


# ── Na sessão: o portão está no caminho da conversa, e não no ditado ──


class _Socket:
    def __init__(self, entrada: List[dict]) -> None:
        self._entrada = list(entrada)
        self.texto: List[dict] = []

    async def receive(self) -> dict:
        if self._entrada:
            return self._entrada.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_text(self, s: str) -> None:
        self.texto.append(json.loads(s))

    async def send_bytes(self, b: bytes) -> None:
        pass

    async def close(self, code: int = 1000) -> None:
        pass


class _Sessao:
    def __init__(self) -> None:
        from src.services import voz_fala_a_fala as falada

        self.microfone: List[bytes] = []
        self.conta = falada.ContaDeTokens()

    async def abrir(self, _c: Any) -> None:
        pass

    async def fechar(self) -> None:
        pass

    async def ouvir_microfone(self, pcm: bytes) -> None:
        self.microfone.append(pcm)

    async def silencio(self, segundos: float = 0.032) -> None:
        pass

    async def escutar(self) -> None:
        pass

    def eventos(self):
        async def gerar():
            if False:
                yield None

        return gerar()


async def _servir(monkeypatch, start: dict, pcm: bytes) -> _Sessao:
    from src.services import voz_sessao_sonic as sonic

    sessao = _Sessao()
    monkeypatch.setattr(sonic.falada, "SessaoFalada", lambda **_kw: sessao, raising=True)
    monkeypatch.setattr(sonic.legenda_viva, "esta_ligada", lambda: False, raising=True)
    entrada = [
        {"text": json.dumps({"type": "control", "action": "start", "locale": "es", **start})}
    ]
    entrada += [{"bytes": p} for p in _pedacos(pcm)]

    async def nada(*_a, **_k):
        return "x"

    async def cliente():
        return object()

    await asyncio.wait_for(
        sonic.servir(
            _Socket(entrada),
            user=type("U", (), {"id": "u", "preferences": {}})(),
            ctx=type("C", (), {"slug": "t"})(),
            responder=nada,
            persistir=nada,
            abrir_cliente=cliente,
        ),
        timeout=10,
    )
    return sessao


@pytest.mark.asyncio
async def test_na_conversa_a_pausa_de_700_ms_nao_chega_ao_sonic(monkeypatch):
    pcm = _fala(1.0) + _silencio(0.7) + _fala(0.6)
    sessao = await _servir(monkeypatch, {"mode": "hands-free"}, pcm)
    sonic = _SonicFalso(0.4)
    for p in sessao.microfone:
        sonic.ouvir(p)
    assert not sonic.fechou
    assert sum(len(p) for p in sessao.microfone) < len(pcm)


@pytest.mark.asyncio
async def test_premir_para_falar_ditado_fica_como_estava(monkeypatch):
    """O ditado não passa pelo portão: o Sonic ouve os bytes tal e qual."""
    pcm = _fala(1.0) + _silencio(0.7) + _fala(0.6) + _silencio(3.0)
    sessao = await _servir(monkeypatch, {"mode": "push-to-talk"}, pcm)
    assert b"".join(sessao.microfone) == pcm
    assert sessao.microfone == list(_pedacos(pcm))


@pytest.mark.asyncio
async def test_a_paciencia_viaja_no_start(monkeypatch):
    from src.services import voz_sessao_sonic as sonic

    criados: List[vp.PortaoDaVez] = []
    original = vp.PortaoDaVez

    def espiar(**kw):
        p = original(**kw)
        criados.append(p)
        return p

    monkeypatch.setattr(sonic.paciencia, "PortaoDaVez", espiar, raising=True)
    await _servir(monkeypatch, {"mode": "hands-free", "patience": "normal"}, _fala(0.2))
    await _servir(monkeypatch, {"mode": "hands-free"}, _fala(0.2))
    assert [p.paciencia for p in criados] == [vp.PACIENCIAS["normal"], vp.PACIENCIAS["patient"]]


def test_sem_patience_no_start_vale_a_gravada_na_conta():
    """A web não tem o ecrã das definições: segue a escolha feita no telemóvel."""

    class _U:
        preferences = {"voice": {"language": "Español", "patience": "normal"}}

    assert vp.paciencia_pedida({}, _U()) == "normal"
    assert vp.paciencia_pedida({"patience": "patient"}, _U()) == "patient"
    assert vp.paciencia_pedida({}, object()) is None
    assert vp.paciencia_pedida({}, type("U", (), {"preferences": {"voice": "x"}})()) is None
    assert vp.paciencia_de(vp.paciencia_pedida({}, object())) == vp.PACIENCIAS["patient"]
