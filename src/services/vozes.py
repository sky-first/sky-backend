"""As vozes da Sky: quais existem, como soam, e qual é que fala.

**Dois defeitos, e o segundo é o pior.**

1. Só havia vozes femininas. «Clara» e «Suave» eram os dois nomes no ecrã, e
   nenhum dizia se era homem ou mulher — porque eram as duas mulheres. Quem
   quisesse uma voz masculina não tinha por onde.

2. **A escolha não chegava cá.** O servidor escolhia o Polly só pela LÍNGUA:

       {"Portuguese": "Camila", "Español": "Lucia"}.get(voice_lang, "Ruth")

   Escolher «Suave» em vez de «Clara» não mudava rigorosamente nada. O ecrã
   de definições era decoração: guardava a preferência, mostrava a marca de
   escolhido, e a voz que respondia era sempre a mesma.

   O Lucas foi ao ecrã, escolheu, e reparou que não ouvia diferença nenhuma.
   Não ouvia porque não havia.

── Porque é aqui e não no cliente ───────────────────────────────────────────

Num telemóvel a voz é sintetizada NO SERVIDOR e chega pelo WebSocket. O
cliente não tem sintetizador nenhum no caminho, portanto o catálogo tem de
viver deste lado — e o ecrã limita-se a mostrar o que o servidor sabe fazer.

A app tem uma cópia da lista para desenhar o ecrã sem esperar pela rede. Se as
duas divergirem, ganha esta: o `voz_polly` só devolve vozes que existem, e uma
escolha desconhecida cai na voz de omissão da língua em vez de rebentar.

── Vozes neurais, e porquê estas ────────────────────────────────────────────

Todas as escolhidas são neurais e existem em `eu-west-1`, que é onde o Polly
é chamado. Uma voz standard ao lado de uma neural ouve-se logo — e a pessoa
não iria pensar «esta é standard», iria pensar que a Sky está avariada.

Português de Portugal e não do Brasil: a Camila que lá estava é pt-BR, e o
Lucas escreve e fala pt-PT. Foi mais um sítio onde a app dizia «português» e
entregava outra coisa.
"""

from __future__ import annotations

from typing import Dict, List, Optional


#: Uma voz, como o ecrã a mostra, como o Sonic a conhece, e o Polly mais
#: parecido.
#:
#: ── 10/10: o catálogo passou a ser o do SONIC ────────────────────────────
#:
#: > «tem duas vozes, Lucía e Sérgio. Mas nenhuma das duas é a que está a
#: >  ser usada… parece que existe uma terceira voz» — Lucas
#:
#: Tinha razão. O ecrã oferecia vozes do Polly (Lucía, Sergio), a pré-escuta
#: tocava o Polly, e quem respondia era o Sonic — que não as conhece e caía
#: sempre na `lupe`. Agora as vozes do ecrã SÃO as do Sonic; o Polly fica só
#: para o recado de espera, com a voz dele que mais se parece.
#:
#: `id` é o que viaja entre a app e o servidor.
class Voz:
    __slots__ = ("id", "nome", "gene", "sonic", "polly", "lingua", "sotaque")

    def __init__(
        self,
        id: str,
        nome: str,
        gene: str,
        sonic: str,
        polly: str,
        lingua: str,
        sotaque: str = "",
    ):
        self.id = id
        self.nome = nome
        #: "f" | "m". No ecrã aparece por extenso e traduzido.
        self.gene = gene
        #: O `voiceId` do Nova Sonic — a voz que responde.
        self.sonic = sonic
        #: A voz do Polly mais parecida, para o recado de espera.
        self.polly = polly
        self.lingua = lingua
        #: Mostra-se quando o sotaque não é o óbvio para a língua.
        self.sotaque = sotaque

    def como_json(self) -> dict:
        d = {"id": self.id, "name": self.nome, "gender": self.gene}
        if self.sotaque:
            d["accent"] = self.sotaque
        return d


#: O catálogo, por língua. A PRIMEIRA de cada língua é a de omissão.
#:
#: As vozes que o Sonic tem (doc da AWS «Language support», Nova 2):
#: es-US lupe/carlos, pt-BR carolina/leo, en-US tiffany/matthew. A `ines`
#: (pt-PT) não está na tabela, mas responde — verificada numa chamada real.
#: Não há voz masculina de Portugal: o par português é Portugal + Brasil, e
#: o sotaque diz-se. O castelhano do Sonic é latino-americano (as duas vozes,
#: por isso não se mostra — só se diz onde muda dentro da língua).
CATALOGO: Dict[str, List[Voz]] = {
    "Portuguese": [
        Voz("ines", "Inês", "f", "ines", "Ines", "pt-PT", "Portugal"),
        Voz("leo", "Leo", "m", "leo", "Thiago", "pt-BR", "Brasil"),
    ],
    "Español": [
        Voz("lupe", "Lupe", "f", "lupe", "Lupe", "es-US"),
        Voz("carlos", "Carlos", "m", "carlos", "Pedro", "es-US"),
    ],
    "English": [
        # Matthew primeiro: era a voz inglesa de omissão e continua a ser.
        Voz("matthew", "Matthew", "m", "matthew", "Matthew", "en-US"),
        Voz("tiffany", "Tiffany", "f", "tiffany", "Ruth", "en-US"),
    ],
}

#: Escolhas guardadas antes de 10/10 (vozes do Polly) → a voz do Sonic do
#: mesmo género. Sem isto quem tinha escolhido «Sergio» ouvia uma mulher.
ANTIGAS = {
    "lucia": "lupe",
    "sergio": "carlos",
    "thiago": "leo",
    "ruth": "tiffany",
    "clara": "",
    "suave": "",
}


#: A frase que se ouve ao escolher uma voz. Curta de propósito: o que se está
#: a avaliar é o timbre, e ninguém quer ouvir um parágrafo duas vezes seguidas.
AMOSTRA: Dict[str, str] = {
    "Portuguese": "Olá, sou a Sky. É assim que soo.",
    "Español": "Hola, soy Sky. Así es como sueno.",
    "English": "Hi, I'm Sky. This is how I sound.",
}


def vozes_de(lingua: str) -> List[Voz]:
    return CATALOGO.get(lingua) or CATALOGO["English"]


def _escolhida(lingua: str, voz_id: Optional[str]) -> Voz:
    lista = vozes_de(lingua)
    pedido = (voz_id or "").lower()
    pedido = ANTIGAS.get(pedido, pedido)
    for v in lista:
        if pedido in (v.id, v.sonic):
            return v
    return lista[0]


def voz_polly(lingua: str, voz_id: Optional[str]) -> str:
    """O nome Polly a usar. Uma escolha desconhecida cai na omissão da língua.

    Nunca rebenta: uma preferência antiga ou de uma versão futura tem de
    continuar a dar voz a alguém.
    """
    return _escolhida(lingua, voz_id).polly


def voz_sonic(lingua: str, voz_id: Optional[str]) -> str:
    """O `voiceId` do Sonic para esta escolha — a voz que responde."""
    return _escolhida(lingua, voz_id).sonic


def polly_da_sonic(sonic_id: str) -> Optional[str]:
    """O Polly mais parecido com uma voz do Sonic (para o recado)."""
    for vozes in CATALOGO.values():
        for v in vozes:
            if v.sonic == sonic_id:
                return v.polly
    return None


def catalogo_como_json() -> dict:
    """O catálogo inteiro, para a app desenhar o ecrã a partir do servidor."""
    return {lingua: [v.como_json() for v in vozes] for lingua, vozes in CATALOGO.items()}
