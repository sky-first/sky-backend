# -*- coding: utf-8 -*-
"""Dois defeitos do live talk do Lucas a 16/10/2026, no servidor.

1. > «A voz continua a falar depois de pausar ou sair do Live Talk.»
   Depois do `end` (ou de o socket cair) o fecho espera que a fila se
   esvazie — e o som que estava em voo seguia para a app. E uma app antiga
   que pausa só manda `mute`: a resposta continuava a chegar.

2. > «a voz diz bem "veintiocho mil" mas a legenda escreve 20.000 e depois
   >  8.000»
   A legenda chega aos pedaços e cada pedaço era convertido sozinho.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.services import voz_fala_a_fala as falada
from src.services import voz_sessao_sonic as sonic
from src.services.numeros_falados import AlgarismosEmFluxo, em_algarismos

_FALA = bytes(120)


class _Ctx:
    slug = "cliente-de-teste"


class _User:
    id = "user-1"
    preferences: Dict[str, Any] = {}


class _Socket:
    """Entrega (espera, mensagem) pela ordem; guarda o que recebe, com a hora."""

    def __init__(self, entrada: List[Tuple[float, Dict[str, Any]]], fica: float = 0.3) -> None:
        self._entrada = list(entrada)
        self._fica = fica
        self.texto: List[Dict[str, Any]] = []
        self.binario: List[bytes] = []
        self.linha: List[str] = []

    async def receive(self) -> Dict[str, Any]:
        if self._entrada:
            espera, msg = self._entrada.pop(0)
            await asyncio.sleep(espera)
            if msg.get("text"):
                self.linha.append("cliente:" + json.loads(msg["text"]).get("action", "?"))
            return msg
        await asyncio.sleep(self._fica)
        return {"type": "websocket.disconnect"}

    async def send_text(self, s: str) -> None:
        m = json.loads(s)
        self.texto.append(m)
        self.linha.append(m["type"])

    async def send_bytes(self, b: bytes) -> None:
        self.binario.append(b)
        self.linha.append("som")

    async def close(self, code: int = 1000) -> None:
        pass


class _Sessao:
    """Dá os eventos com esperas: (segundos, evento)."""

    def __init__(self, eventos: List[Tuple[float, falada.Evento]]) -> None:
        self.eventos_a_dar = list(eventos)
        self.conta = falada.ContaDeTokens()
        self._fila: asyncio.Queue = asyncio.Queue()
        self.fechada = asyncio.Event()

    async def abrir(self, _c: Any) -> None:
        pass

    async def fechar(self) -> None:
        self.fechada.set()

    async def ouvir_microfone(self, _pcm: bytes) -> None:
        pass

    async def silencio(self, _s: float = 0.032) -> None:
        pass

    async def escutar(self) -> None:
        for espera, ev in self.eventos_a_dar:
            await asyncio.sleep(espera)
            await self._fila.put(ev)
        await self.fechada.wait()
        await self._fila.put(None)

    def eventos(self):
        async def gerar():
            while True:
                ev = await self._fila.get()
                if ev is None:
                    break
                yield ev

        return gerar()


def _ctrl(accao: str, **kw: Any) -> Dict[str, Any]:
    return {"text": json.dumps({"type": "control", "action": accao, **kw})}


async def _servir(monkeypatch, entrada, eventos, fica: float = 0.3) -> Tuple[_Socket, list]:
    sessao = _Sessao(eventos)
    monkeypatch.setattr(sonic.falada, "SessaoFalada", lambda **_kw: sessao, raising=True)
    monkeypatch.setattr(sonic.legenda_viva, "esta_ligada", lambda: False, raising=True)
    s = _Socket([(0, _ctrl("start", page_id="p", space_id="e", locale="es"))] + entrada, fica)
    guardado: list = []

    async def guardar(**kw):
        guardado.extend(kw["turnos"])
        return "conv-1"

    async def nada(*_a, **_k):
        return "x"

    async def cliente():
        return object()

    await asyncio.wait_for(
        sonic.servir(
            s,
            user=_User(),
            ctx=_Ctx(),
            responder=nada,
            persistir=guardar,
            abrir_cliente=cliente,
        ),
        timeout=8,
    )
    return s, guardado


# ── 1. Sair e pausar calam a Sky ────────────────────────────────────


@pytest.mark.asyncio
async def test_depois_do_end_nao_sai_mais_som_mas_o_texto_e_o_final_chegam(monkeypatch):
    eventos = [
        (0.02, falada.Dito(texto="Tenéis doce tiendas.")),
        (0.0, falada.Audio(pcm=_FALA)),
        (0.15, falada.Audio(pcm=_FALA)),  # chega depois do `end`
        (0.0, falada.Dito(texto="Y treinta y siete empleados.")),
        (0.0, falada.Audio(pcm=_FALA)),
    ]
    s, guardado = await _servir(monkeypatch, [(0.08, _ctrl("end"))], eventos)
    fim = s.linha.index("cliente:end")
    assert "som" in s.linha[:fim]
    assert "som" not in s.linha[fim:]
    # O texto não se perde: nem no ecrã nem no fio.
    assert {"type": "sky_text", "text": "Y 37 empleados."} in s.texto
    assert ("sky", "Y 37 empleados.") in guardado
    assert [m["type"] for m in s.texto][-2:] == ["final", "state"]


@pytest.mark.asyncio
async def test_pausar_com_a_sky_a_falar_cala_a_resposta(monkeypatch):
    """Uma app antiga só manda `mute`."""
    eventos = [
        (0.02, falada.Dito(texto="La tienda de Madrid.")),
        (0.0, falada.Audio(pcm=_FALA)),
        (0.15, falada.Audio(pcm=_FALA)),  # depois da pausa
        (0.0, falada.Dito(texto="Y la de Valencia.")),
    ]
    s, _ = await _servir(monkeypatch, [(0.08, _ctrl("mute"))], eventos)
    pausa = s.linha.index("cliente:mute")
    assert "discard_audio" in s.linha[pausa:]
    assert "som" not in s.linha[pausa:]
    assert {"type": "sky_text", "text": "Y la de Valencia."} not in s.texto


@pytest.mark.asyncio
async def test_pausar_sem_a_sky_a_falar_so_silencia(monkeypatch):
    s, _ = await _servir(monkeypatch, [(0.02, _ctrl("mute"))], [])
    assert "discard_audio" not in s.linha


@pytest.mark.asyncio
async def test_depois_de_a_vez_voltar_pausar_ja_nao_descarta(monkeypatch):
    eventos = [
        (0.0, falada.Audio(pcm=_FALA)),
        (0.0, falada.VezDaPessoa()),
    ]
    s, _ = await _servir(monkeypatch, [(0.1, _ctrl("mute"))], eventos)
    assert "discard_audio" not in s.linha


# ── 2. A legenda aos pedaços ────────────────────────────────────────


@pytest.mark.asyncio
async def test_um_numero_partido_entre_dois_pedacos_sai_inteiro(monkeypatch):
    eventos = [
        (0.0, falada.Dito(texto="La tienda tuvo veinte")),
        (0.0, falada.Audio(pcm=_FALA)),
        (0.0, falada.Dito(texto="y ocho mil pedidos.")),
        (0.0, falada.Audio(pcm=_FALA)),
        (0.0, falada.VezDaPessoa()),
    ]
    s, guardado = await _servir(monkeypatch, [], eventos)
    legendas = [m["text"] for m in s.texto if m["type"] == "sky_text"]
    assert legendas == ["La tienda tuvo", "28.000 pedidos."]
    # A app junta-as com um espaço: é o que fica no ecrã.
    assert " ".join(legendas) == "La tienda tuvo 28.000 pedidos."
    assert [t for q, t in guardado if q == "sky"] == legendas


@pytest.mark.asyncio
async def test_a_cauda_retida_sai_antes_de_a_vez_voltar(monkeypatch):
    eventos = [
        (0.0, falada.Dito(texto="Facturó veintiocho mil")),
        (0.0, falada.Audio(pcm=_FALA)),
        (0.0, falada.VezDaPessoa()),
    ]
    s, _ = await _servir(monkeypatch, [], eventos)
    i_legenda = next(
        i for i, m in enumerate(s.texto) if m == {"type": "sky_text", "text": "28.000"}
    )
    i_vez = max(
        i for i, m in enumerate(s.texto) if m == {"type": "state", "value": "user_speaking"}
    )
    assert i_legenda < i_vez


FRASES = [
    ("La tienda tuvo veintiocho mil pedidos el último mes.", "es"),
    ("Facturó veinte y ocho mil dólares, un siete coma tres por ciento más.", "es"),
    ("Tuvo veintiún mil clientes y treinta y uno mil pedidos.", "es"),
    ("Tienes treinta y cinco mil clientes y doscientos mil euros.", "es"),
    ("Vendió doscientas mil unidades, ciento ochenta y dos mil trescientos cuatro euros.", "es"),
    ("El último pedido fue el uno de agosto de dos mil veintiséis.", "es"),
    ("La Tienda cero uno registró ventas por ciento ochenta y dos mil euros.", "es"),
    ("A loja teve vinte e oito mil encomendas e cento e vinte mil euros.", "pt"),
    ("Faturou duzentos mil euros, sete vírgula três por cento mais.", "pt"),
]


@pytest.mark.parametrize("frase,lingua", FRASES)
def test_letra_a_letra_da_o_mesmo_que_a_frase_inteira(frase, lingua):
    f = AlgarismosEmFluxo(lingua, separador="")
    saida = "".join(f.pedaco(c) for c in frase) + f.fim()
    assert saida == em_algarismos(frase, lingua)


@pytest.mark.parametrize("frase,lingua", FRASES)
def test_partida_em_cada_espaco_da_o_mesmo_que_a_frase_inteira(frase, lingua):
    """Os pedaços do Sonic acabam em palavras inteiras; a app junta-os com espaço."""
    palavras = frase.split(" ")
    for corte in range(1, len(palavras)):
        f = AlgarismosEmFluxo(lingua)
        pedacos = [" ".join(palavras[:corte]), " ".join(palavras[corte:])]
        saida = [x for x in (f.pedaco(p) for p in pedacos) if x]
        resto = f.fim()
        if resto:
            saida.append(resto)
        assert " ".join(saida) == em_algarismos(frase, lingua), pedacos


@pytest.mark.parametrize(
    "dito,lingua,esperado",
    [
        ("veintiocho mil", "es", "28.000"),
        ("veinte y ocho mil", "es", "28.000"),
        ("veintiún mil", "es", "21.000"),
        ("veintidós mil", "es", "22.000"),
        ("treinta y uno", "es", "31"),
        ("treinta y cinco mil", "es", "35.000"),
        ("doscientos mil", "es", "200.000"),
        ("vinte e oito mil", "pt", "28.000"),
        ("cento e vinte e um mil", "pt", "121.000"),
    ],
)
def test_os_compostos_sao_um_numero_so(dito, lingua, esperado):
    assert em_algarismos(dito, lingua) == esperado


def test_um_pedaco_so_de_numero_fica_todo_retido():
    f = AlgarismosEmFluxo("es")
    assert f.pedaco("veinte") == ""
    assert f.pedaco("y ocho") == ""
    assert f.pedaco("mil euros.") == "28.000 euros."
    assert f.fim() == ""


def test_dolares_em_formato_americano_vao_por_extenso_e_voltam():
    from src.services.numeros_falados import numeros_no_formato, por_extenso

    dito = por_extenso(numeros_no_formato("Ingresos de $28,000 en total", "es"), "es")
    assert dito == "Ingresos de veintiocho mil dólares en total"
    assert em_algarismos(dito, "es") == "Ingresos de 28.000 dólares en total"
    # Sem moeda nem grupos a mais, «28,000» pode ser um decimal europeu: fica.
    assert numeros_no_formato("El 7,3 % y 28,000", "es") == "El 7,3 % y 28,000"
