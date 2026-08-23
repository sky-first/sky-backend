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

#: Uma voz, como o ecrã a mostra e como o Polly a conhece.
#:
#: `id` é o que viaja entre a app e o servidor — nunca o nome do Polly, para
#: se poder trocar a voz subjacente sem partir as preferências já guardadas.
class Voz:
    __slots__ = ("id", "nome", "gene", "polly", "lingua")

    def __init__(self, id: str, nome: str, gene: str, polly: str, lingua: str):
        self.id = id
        self.nome = nome
        #: "f" | "m". No ecrã aparece por extenso e traduzido; aqui fica curto
        #: porque é uma chave, não um rótulo.
        self.gene = gene
        self.polly = polly
        self.lingua = lingua

    def como_json(self) -> dict:
        return {"id": self.id, "name": self.nome, "gender": self.gene}


#: O catálogo, por língua. A PRIMEIRA de cada língua é a de omissão.
#:
#: Duas por língua e não seis: uma lista longa num ecrã de telemóvel é uma
#: lista que ninguém percorre, e o que falta mesmo é poder escolher entre uma
#: voz de mulher e uma de homem.
CATALOGO: Dict[str, List[Voz]] = {
    "Portuguese": [
        Voz("ines", "Inês", "f", "Ines", "pt-PT"),
        Voz("cristiano", "Cristiano", "m", "Cristiano", "pt-PT"),
    ],
    "Español": [
        Voz("lucia", "Lucía", "f", "Lucia", "es-ES"),
        Voz("sergio", "Sergio", "m", "Sergio", "es-ES"),
    ],
    "English": [
        Voz("ruth", "Ruth", "f", "Ruth", "en-US"),
        Voz("matthew", "Matthew", "m", "Matthew", "en-US"),
    ],
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


def voz_polly(lingua: str, voz_id: Optional[str]) -> str:
    """O nome Polly a usar. Uma escolha desconhecida cai na omissão da língua.

    Nunca rebenta: uma preferência antiga («Clara», «Suave») ou de uma versão
    futura tem de continuar a dar voz a alguém. Ficar sem som porque a
    definição envelheceu seria pior do que a voz não ser a preferida.
    """
    lista = vozes_de(lingua)
    for v in lista:
        if v.id == (voz_id or "").lower():
            return v.polly
    return lista[0].polly


def catalogo_como_json() -> dict:
    """O catálogo inteiro, para a app desenhar o ecrã a partir do servidor."""
    return {
        lingua: [v.como_json() for v in vozes]
        for lingua, vozes in CATALOGO.items()
    }
