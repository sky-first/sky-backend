# -*- coding: utf-8 -*-
"""Quem decide que a pessoa acabou de falar — e quanto se espera por ela.

── O defeito ───────────────────────────────────────────────────────

> «¿Cuál es el precio del gasoil…» — e a Sky responde antes de ele
> acabar, numa pausa curta em que estava a pensar. — Lucas, 12/10/2026
> (segunda vez que o reporta).

O `endpointingSensitivity: LOW` já ia no `sessionStart`, no sítio e na
forma que a AWS documenta. Não chega, e a razão está medida em
`docs/a-voz-medida-nova-sonic.md`: **o fim de turno do Sonic é
SEMÂNTICO.** Uma frase que já soa completa («¿cuál es el precio del
gasoil?») fecha ~400 ms depois de a voz parar. O LOW só estica a espera
das frases que soam a meio, e mesmo essas até um tecto de ~2 s — é o
máximo que o modelo deixa configurar.

Ou seja: não há parâmetro do Sonic que dê a paciência pedida. Quem a dá
somos nós, controlando O QUE ele ouve.

── Como ───────────────────────────────────────────────────────────

O Sonic só pode fechar o turno num silêncio que ouviu. Então, a meio de
uma fala, as pausas **não lhe chegam inteiras**:

  * os primeiros `PASSAGEM_S` de cada pausa passam (uma pausa de
    respiração soa natural e fica abaixo do que ele precisa para fechar);
  * o resto fica RETIDO. Se a pessoa voltar a falar antes de a retenção
    acabar, o silêncio retido deita-se fora — para o Sonic foi uma frase
    só, com uma pausa curta;
  * quando a retenção acaba, o portão entrega `DESCARGA_S` de silêncio
    DIGITAL (zeros) e abre. O Sonic fecha o turno ~1,1 s depois.

Medido a 12/10 contra o Sonic verdadeiro (`scripts/sonda_a_paciencia.py`):

  * sem o portão, cortou «¿Cuál es el precio del gasoil…» com pausas de
    0,7 s e de 1,2 s — e respondeu duas vezes, uma a cada metade;
  * só abrir o portão (deixar o silêncio de sala passar ao vivo) não
    serve: ele fechou entre 0,3 s e 2,7 s depois, ao acaso. Com 0,3 s a
    retenção deixa de valer;
  * com a descarga fechou sempre ~1 s depois, fosse ela de 0,6, 1,2 ou
    2,2 s — consome o áudio ao ritmo real. Fica nos 2,2 s por estar acima
    dos 2 s do LOW: uma frase que lhe soe a meio («el precio de») também
    fecha.

A retenção é medida em tempo de ÁUDIO (amostras), não de relógio: isso
torna-a determinística nos testes e imune a um socket que entrega o
microfone aos solavancos.

── A paciência ────────────────────────────────────────────────────

Duas escolhas, nas definições de voz («Esperar antes de responder»).
O número é a pausa que se tolera sem cortar; o Sonic dá o turno por
fechado ~1,1 s depois (`REACCAO_DO_SONIC_S`) e o primeiro som chega
~0,7 s depois disso:

  * `normal`   — 1,0 s; 1,8 s depois de uma hesitação.
  * `patient`  — 1,4 s; 2,4 s depois de uma hesitação. **Por omissão.**

Medido (12/10, pergunta inteira com uma pausa de 0,7 s): sem portão o
primeiro som vinha a +1,3 s do fim da fala — mas da pergunta CORTADA. Com
o portão: `normal` +2,65 s, `patient` +3,2 s, e a pergunta inteira. É o
preço da paciência, e é por isso que a escolha existe.

«Hesitação» é a última palavra ouvida ser um bordão («eh», «em», «o
sea», «pues», «bueno»…) ou uma palavra que pede continuação («de»,
«en», «el», «la»…). Quem diz «el precio de…» e pára não acabou. As
palavras vêm da legenda ao vivo (Transcribe), que chega bem antes do fim
da paciência; sem legenda vale só a paciência base.

── O que isto NÃO toca ─────────────────────────────────────────────

O ditado (`push-to-talk` no fio). Lá a frase é da pessoa até ela largar,
e o Sonic só transcreve — nada aqui se aplica.
"""
from __future__ import annotations

import array
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List

HZ = 16000
#: 20 ms por janela — 320 amostras PCM16.
JANELA = 320
JANELA_S = JANELA / HZ

#: Quanto de cada pausa o Sonic ouve. Abaixo do que ele precisa para
#: fechar uma frase que soa completa (sem o portão, cortou numa pausa de
#: 0,7 s — medido).
PASSAGEM_S = 0.20
#: O silêncio que se entrega quando a paciência acaba: zeros, acima dos
#: 2 s do `endpointingSensitivity: LOW`, para ele fechar SEMPRE.
DESCARGA_S = 2.2
#: Em pedaços de 0,5 s, como o `manter_viva` já mandava.
PEDACO_DA_DESCARGA_S = 0.5
#: Quanto o Sonic leva a fechar o turno depois da descarga. Medido a
#: 12/10 (1,0–1,1 s). Só para a documentação — o portão não o usa.
REACCAO_DO_SONIC_S = 1.1

#: Voz a voltar: duas janelas seguidas acima do limiar (40 ms). Um clique
#: ou uma pancada na mesa não reabrem a frase.
JANELAS_PARA_VOLTAR = 2

#: O limiar de voz. Absoluto em baixo (um microfone em silêncio digital
#: não pode fazer do ruído voz) e relativo ao ruído de fundo medido.
#:
#: ── Porque desceu de 350 para 200, e porque há dois (16/10) ─────────
#:
#: > «¿Qué tienda tuvo más?» — e ele tinha dito «¿Qué tienda tuvo más
#: >  pedidos el último mes?». — Lucas, 16/10, Android.
#:
#: O microfone do Android chega BAIXO (a app multiplica o nível por 8 só
#: para a onda se ver). Com a fala a ~360–730 de RMS, um limiar fixo de
#: 350 — e 3× o ruído a meio da frase — fazia das sílabas fracas e do fim
#: das palavras «silêncio». Esse «silêncio» era RETIDO e deitado fora, e
#: ao fim da paciência o portão entregava a descarga: o Sonic ouvia meia
#: pergunta e fechava o turno. Medido com o Polly a 0,15× (fala ~360,
#: ruído 60): 52 % da fala perdida e o turno entregue antes do fim.
#:
#: Agora: para COMEÇAR a frase, 200 ou 3× o ruído; DENTRO da frase basta
#: 100 ou 2× o ruído (histerese — uma vez a falar, uma sílaba fraca
#: continua a ser fala).
LIMIAR_MINIMO = 200.0
FACTOR_SOBRE_O_RUIDO = 3.0
LIMIAR_A_MEIO_DA_FALA = 100.0
FACTOR_A_MEIO_DA_FALA = 2.0
RUIDO_INICIAL = 150.0
RUIDO_MAXIMO = 2500.0

#: Quando a voz volta depois de uma pausa retida, o fim do que se reteve
#: que JÁ era som (acima de 1,5× o ruído — o arranque fraco de «pedidos»)
#: segue à frente dela. Silêncio de sala não segue: o Sonic continua a
#: ouvir só a pausa de respiração.
FACTOR_DO_ARRANQUE = 1.5
ARRANQUE_MAXIMO_S = 0.3


@dataclass(frozen=True)
class Paciencia:
    """Quanto silêncio se RETÉM antes de o Sonic o ouvir."""

    base_s: float
    hesitacao_s: float


PACIENCIAS: Dict[str, Paciencia] = {
    "normal": Paciencia(base_s=1.0, hesitacao_s=1.8),
    "patient": Paciencia(base_s=1.4, hesitacao_s=2.4),
}
PACIENCIA_POR_OMISSAO = "patient"


def paciencia_pedida(inicio: Dict[str, Any], user: Any) -> object:
    """A paciência desta sessão: a do `start`, ou a gravada na conta.

    A app manda-a no `start`. A web não tem o ecrã das definições de voz,
    e uma app antiga não a manda — as duas ficam com a que a pessoa
    escolheu no telemóvel (`preferences.voice.patience`, onde a app a
    grava). `getattr` e tudo defensivo: uma preferência nunca pode impedir
    a voz de abrir.
    """
    if inicio.get("patience"):
        return inicio.get("patience")
    try:
        prefs = getattr(user, "preferences", None) or {}
        voz = prefs.get("voice") if isinstance(prefs, dict) else None
        return voz.get("patience") if isinstance(voz, dict) else None
    except Exception:  # noqa: BLE001
        return None


def paciencia_de(valor: object) -> Paciencia:
    """O que veio no `start` → a paciência. Desconhecido ou ausente: a paciente."""
    chave = str(valor or "").strip().lower()
    # Aceita os nomes da app em pt/es também — o fio é inglês, mas um
    # cliente que mande «paciente» não deve cair no normal por engano.
    if chave in {"paciente", "mas_paciente", "more_patient"}:
        chave = "patient"
    return PACIENCIAS.get(chave, PACIENCIAS[PACIENCIA_POR_OMISSAO])


# ── Hesitações ──────────────────────────────────────────────────────

#: Bordões: quem os diz está a pensar, não acabou.
BORDOES = {
    # es
    "eh",
    "ehh",
    "em",
    "emm",
    "ehm",
    "mm",
    "mmm",
    "hmm",
    "este",
    "pues",
    "bueno",
    "osea",
    "o sea",
    "digamos",
    "a ver",
    "entonces",
    "tipo",
    # pt
    "hum",
    "humm",
    "ah",
    "ahn",
    "pronto",
    "entao",
    "portanto",
    "ou seja",
    "quer dizer",
    "olha",
    "sei la",
    # en
    "uh",
    "um",
    "umm",
    "erm",
    "er",
    "like",
    "so",
    "well",
    "you know",
    "i mean",
}

#: Palavras que pedem continuação: artigos, preposições, conjunções.
PEDEM_CONTINUACAO = {
    # es
    "de",
    "del",
    "en",
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "al",
    "a",
    "con",
    "por",
    "para",
    "que",
    "y",
    "o",
    "e",
    "u",
    "entre",
    "sobre",
    "desde",
    "hasta",
    "mi",
    "mis",
    "su",
    "sus",
    "cual",
    "cuales",
    # pt
    # «no» fica de fora: em castelhano fecha perguntas («¿…o no?»).
    "do",
    "da",
    "dos",
    "das",
    "na",
    "nos",
    "nas",
    "os",
    "um",
    "uma",
    "com",
    "pelo",
    "pela",
    "pelos",
    "pelas",
    "num",
    "numa",
    "ao",
    "aos",
    "meu",
    "minha",
    "seu",
    "sua",
    "qual",
    "quais",
    # en
    "the",
    "an",
    "of",
    "to",
    "in",
    "for",
    "and",
    "or",
    "with",
    "on",
    "at",
    "from",
    "my",
    "our",
    "their",
    "which",
}


def _normal(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def acaba_a_hesitar(texto: str) -> bool:
    """A última coisa dita é um bordão ou uma palavra que pede mais?

    Uma pergunta que acaba em «?» na legenda pode ainda assim acabar em
    «de» — a pontuação do Transcribe é palpite, as palavras não.
    """
    palavras = _normal(texto).split()
    if not palavras:
        return False
    ultima = palavras[-1]
    duas = " ".join(palavras[-2:])
    return ultima in BORDOES or duas in BORDOES or ultima in PEDEM_CONTINUACAO


# ── O portão ────────────────────────────────────────────────────────


def _rms(janela: bytes) -> float:
    a = array.array("h")
    a.frombytes(janela[: len(janela) - (len(janela) % 2)])
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


@dataclass
class PortaoDaVez:
    """Decide que áudio do microfone chega ao Sonic, e quando.

    `ouvir(pcm)` devolve os pedaços a mandar JÁ, por ordem. Não fala com
    o Sonic nem com o socket — é puro, para se poder testar com áudio
    fabricado.
    """

    paciencia: Paciencia = field(default_factory=lambda: PACIENCIAS[PACIENCIA_POR_OMISSAO])

    #: A pessoa começou a falar e o turno ainda não foi entregue.
    a_meio_da_fala: bool = False
    #: Silêncio seguido desde a última voz, em segundos de áudio.
    silencio_s: float = 0.0
    #: As últimas palavras ouvidas (legenda ao vivo).
    ultimas_palavras: str = ""
    #: Quantas vezes se entregou o turno (para os registos e os testes).
    entregas: int = 0

    _ruido: float = RUIDO_INICIAL
    #: O pedaço de janela que ainda não chegou a 20 ms (para medir).
    _resto: bytes = b""
    #: Quantos bytes desse pedaço já seguiram para o Sonic.
    _resto_enviado: int = 0
    #: Janelas com voz a seguir, enquanto se espera para confirmar que voltou.
    _a_voltar: List[bytes] = field(default_factory=list)
    #: O fim do que está retido (até `ARRANQUE_MAXIMO_S`), com o nível de
    #: cada janela: se a voz voltar, o arranque fraco segue à frente dela.
    _retido: List[tuple] = field(default_factory=list)

    # ── O que se mede, para o registo do turno (16/10) ──────────────
    #: Segundos de áudio com voz que seguiram para o Sonic neste turno.
    fala_s: float = 0.0
    #: Segundos retidos e NUNCA entregues (pausas — ou fala que se perdeu).
    retido_s: float = 0.0
    #: O nível mais alto de voz ouvido neste turno (RMS de 20 ms).
    pico_da_fala: float = 0.0

    # ── O que se lê de fora ─────────────────────────────────────────

    def ouvi_texto(self, texto: str) -> None:
        """A legenda ao vivo: as palavras mais recentes do turno."""
        if texto and texto.strip():
            self.ultimas_palavras = texto

    def espera_s(self) -> float:
        """Quanto silêncio fecha o turno, AGORA."""
        if acaba_a_hesitar(self.ultimas_palavras):
            return self.paciencia.hesitacao_s
        return self.paciencia.base_s

    def fechou_se(self) -> None:
        """O Sonic fechou o turno por conta própria (ou já está a responder).

        Não devia acontecer com as pausas retidas, mas se acontecer o
        portão não pode ficar «a meio da fala» de um turno que já acabou —
        entregava-lhe uma descarga de silêncio por cima da resposta.
        """
        self.a_meio_da_fala = False
        self.silencio_s = 0.0
        self._a_voltar.clear()
        self._retido.clear()

    def medidas(self) -> Dict[str, float]:
        """O que o turno teve, para o registo — sem conteúdo nenhum."""
        return {
            "fala_s": round(self.fala_s, 2),
            "retido_s": round(self.retido_s, 2),
            "pico": round(self.pico_da_fala),
            "ruido": round(self._ruido),
        }

    def recomecar_medidas(self) -> None:
        self.fala_s = self.retido_s = self.pico_da_fala = 0.0

    # ── O áudio ─────────────────────────────────────────────────────

    def silencio(self, segundos: float) -> List[bytes]:
        """Silêncio fabricado (o `manter_viva`) passa pelo mesmo portão."""
        return self.ouvir(bytes(int(HZ * segundos) * 2))

    def _a_deixar_passar(self) -> bool:
        """O que chegar agora passa? (Fora de uma pausa retida.)"""
        return not self.a_meio_da_fala or (self.silencio_s <= PASSAGEM_S and not self._a_voltar)

    def ouvir(self, pcm: bytes) -> List[bytes]:
        """O áudio do microfone → o que segue JÁ para o Sonic, por ordem.

        Mede-se em janelas de 20 ms, mas o que passa não espera pela
        janela fechar: um pedaço que chega a meio de uma janela segue logo
        se o portão estiver aberto (senão um microfone que mande pedaços
        pequenos ganhava 20 ms de atraso, e os testes da sessão viam o
        áudio desaparecer).
        """
        dados = self._resto + pcm
        n = len(dados) - (len(dados) % (JANELA * 2))
        saida: List[bytes] = []
        ja_foi = self._resto_enviado
        for i in range(0, n, JANELA * 2):
            janela = dados[i : i + JANELA * 2]
            for p in self._janela(janela):
                if ja_foi and p is janela:
                    p = janela[ja_foi:]
                saida.append(p)
            ja_foi = 0
        resto = dados[n:]
        self._resto = resto
        self._resto_enviado = 0
        if resto and self._a_deixar_passar():
            # A parte já enviada do pedaço anterior não vai outra vez.
            novo = resto[min(len(resto), ja_foi) :] if ja_foi else resto
            if novo:
                saida.append(novo)
            self._resto_enviado = len(resto)
        elif resto:
            self._resto_enviado = min(len(resto), ja_foi)
        return _juntar(saida)

    def _e_voz(self, nivel: float) -> bool:
        if self.a_meio_da_fala:
            # Histerese: a meio da frase uma sílaba fraca continua a ser fala.
            limiar = max(LIMIAR_A_MEIO_DA_FALA, self._ruido * FACTOR_A_MEIO_DA_FALA)
        else:
            limiar = max(LIMIAR_MINIMO, self._ruido * FACTOR_SOBRE_O_RUIDO)
        voz = nivel > limiar
        # O ruído de fundo DESCE depressa e SOBE devagar. Antes subia 5 %
        # por janela com tudo o que não passava o limiar — e com o
        # microfone baixo isso incluía sílabas fracas: o ruído subia para o
        # nível da fala, o limiar (3×) subia acima dela, e o resto da frase
        # passava a «silêncio». Agora só a parte de baixo o puxa para cima.
        if nivel < self._ruido:
            self._ruido = 0.8 * self._ruido + 0.2 * nivel
        elif not voz and nivel < self._ruido * FACTOR_A_MEIO_DA_FALA:
            self._ruido = min(RUIDO_MAXIMO, 0.99 * self._ruido + 0.01 * nivel)
        return voz

    def _reter(self, janela: bytes, nivel: float) -> None:
        self._retido.append((janela, nivel))
        if len(self._retido) * JANELA_S > ARRANQUE_MAXIMO_S + 1e-9:
            self._retido.pop(0)

    def _arranque(self) -> List[bytes]:
        """O fim do retido que já era som: o arranque fraco da palavra."""
        limiar = max(LIMIAR_A_MEIO_DA_FALA / 2, self._ruido * FACTOR_DO_ARRANQUE)
        k = len(self._retido)
        while k > 0 and self._retido[k - 1][1] > limiar:
            k -= 1
        arranque = [j for j, _n in self._retido[k:]]
        self.retido_s = max(0.0, self.retido_s - JANELA_S * len(arranque))
        self._retido.clear()
        return arranque

    def _janela(self, janela: bytes) -> List[bytes]:
        nivel = _rms(janela)
        voz = self._e_voz(nivel)
        if voz:
            self.pico_da_fala = max(self.pico_da_fala, nivel)

        if not self.a_meio_da_fala:
            # Antes de a pessoa falar (ou depois de o turno ser entregue),
            # tudo passa: o silêncio aqui não fecha nada, e é o que mantém
            # a sessão do Sonic viva.
            if voz:
                self.a_meio_da_fala = True
                self.silencio_s = 0.0
                self.ultimas_palavras = ""
                self._retido.clear()
                self.fala_s += JANELA_S
            return [janela]

        if voz:
            if self.silencio_s <= PASSAGEM_S:
                # Pausa curta, já toda entregue: a frase continua.
                self.silencio_s = 0.0
                self._a_voltar.clear()
                self._retido.clear()
                self.fala_s += JANELA_S
                return [janela]
            # A meio de uma pausa retida: confirma que é voz a sério.
            self._a_voltar.append(janela)
            if len(self._a_voltar) >= JANELAS_PARA_VOLTAR:
                voltou, self._a_voltar = self._a_voltar, []
                self.silencio_s = 0.0
                self.fala_s += JANELA_S * len(voltou)
                return self._arranque() + voltou
            return []

        # Silêncio a meio da fala.
        if self._a_voltar:
            # Era um clique, não a voz a voltar: conta como silêncio.
            self.silencio_s += JANELA_S * len(self._a_voltar)
            for j in self._a_voltar:
                self._reter(j, _rms(j))
                self.retido_s += JANELA_S
            self._a_voltar.clear()
        self.silencio_s += JANELA_S
        if self.silencio_s >= self.espera_s():
            return self._entregar()
        if self.silencio_s <= PASSAGEM_S:
            return [janela]
        self._reter(janela, nivel)
        self.retido_s += JANELA_S
        return []  # retido

    def _entregar(self) -> List[bytes]:
        """A paciência acabou: o Sonic ouve silêncio que chegue para fechar."""
        self.a_meio_da_fala = False
        self.silencio_s = 0.0
        self._a_voltar.clear()
        self._retido.clear()
        self.entregas += 1
        pedaco = bytes(int(HZ * PEDACO_DA_DESCARGA_S) * 2)
        total = int(HZ * DESCARGA_S) * 2
        saida: List[bytes] = []
        while total > 0:
            saida.append(pedaco[: min(len(pedaco), total)])
            total -= len(pedaco)
        return saida


def _juntar(pedacos: List[bytes]) -> List[bytes]:
    """Janelas seguidas num só envio — 20 ms por evento seria um exagero.

    Os pedaços da descarga (0,5 s cada) ficam como estão.
    """
    saida: List[bytes] = []
    atual = bytearray()
    for p in pedacos:
        if len(p) > JANELA * 2:
            if atual:
                saida.append(bytes(atual))
                atual = bytearray()
            saida.append(p)
        else:
            atual.extend(p)
    if atual:
        saida.append(bytes(atual))
    return saida
