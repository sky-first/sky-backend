"""QA — a voz tem de ouvir na lingua em que se fala com ela.

O Lucas, depois de usar o live talk:

    «Estando a voz e a app em portugues, ainda so me escutou em ingles. E
    quando eu falei *one two three* apareceram os numeros e quase
    imediatamente gerou a resposta toda em ingles.»

O lado da app estava certo: deriva a lingua da voz da lingua da app e
manda-a no arranque. O problema estava no servidor, e eram tres quedas
silenciosas — nenhuma delas dava erro, todas acabavam em ingles.
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize

RAIZ = pathlib.Path(__file__).resolve().parents[2]
VOZ = RAIZ / "src" / "api" / "v1" / "voice.py"
FONTE = VOZ.read_text(encoding="utf-8")


def _codigo() -> str:
    """A fonte com os comentarios apagados **no lugar**.

    A primeira versao destes testes falhava por apanhar o proprio
    comentario que explicava o defeito — o que ensina a apagar
    comentarios para calar o teste.

    A segunda usou o tokenizador e juntou os pedacos com quebras de
    linha: `provider.start` passou a tres linhas, e as procuras por linha
    deixaram de encontrar o que quer que fosse. Um teste que nao encontra
    nada **passa**, e diz que esta tudo bem.

    Esta apaga cada comentario deixando espacos no seu lugar. As linhas,
    as colunas e o codigo ficam exactamente onde estavam. Usa-se o
    tokenizador para os achar, porque um `#` dentro de uma string nao e
    um comentario.
    """
    linhas = VOZ.read_text(encoding="utf-8").splitlines()
    with io.open(VOZ, encoding="utf-8") as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type != tokenize.COMMENT:
                continue
            (li, ci), (_, cf) = tok.start, tok.end
            l = linhas[li - 1]
            linhas[li - 1] = l[:ci] + " " * (cf - ci) + l[cf:]
    return "\n".join(linhas)


CODIGO = _codigo()


def test_a_falha_a_mudar_de_lingua_nao_e_engolida():
    """A transcricao arranca em ingles e so depois e reaberta na lingua
    certa. Isto era::

        try:
            await provider.start(voice_lang)
        except Exception:
            pass

    Se a reabertura falhasse, o `pass` apagava o erro e a sessao
    continuava a ouvir em ingles. Nem o utilizador ficava a saber — so
    sentia que «nao o entende» — nem ficava rasto para alguem investigar.
    """
    linhas = CODIGO.splitlines()
    inicios = [i for i, l in enumerate(linhas) if "provider.start" in l]
    assert inicios, "nao encontrei a reabertura da transcricao — mudou de forma?"

    engolidas = []
    for i in inicios:
        bloco = "\n".join(linhas[i : i + 12])
        # `except ...:` seguido de `pass` e nada mais
        if re.search(r"except\b[^\n]*\n\s*:?\s*\npass\b", bloco) or re.search(
            r"except\s*\n?\s*Exception\s*\n?\s*:\s*\npass", bloco
        ):
            engolidas.append(i + 1)

    assert not engolidas, (
        f"a mudanca de lingua falha em silencio perto das linhas {engolidas}: "
        "a sessao fica em ingles e nada o diz"
    )


def test_a_falha_deixa_rasto_nos_registos():
    """Nao basta nao engolir: tem de ficar escrito.

    Um `except` que so avisa o cliente resolve metade — quem investiga
    dias depois nao tem o cliente a frente.
    """
    assert "nao consegui reabrir a transcricao" in FONTE, (
        "a falha a mudar de lingua nao e registada"
    )


def test_a_falha_e_dita_a_quem_esta_a_falar():
    """E a outra metade: quem esta do outro lado merece saber porque e que
    de repente so o entendem em ingles."""
    assert "voice_language_fallback" in CODIGO, (
        "o cliente nao e avisado de que a sessao ficou em ingles"
    )


def test_a_lingua_desconhecida_nao_vira_ingles_em_silencio():
    """`{"pt": ..., "es": ...}.get(locale, "English")`.

    Um locale fora do mapa caia em ingles sem uma linha nos registos. No
    dia em que a app ganhasse uma lingua e este sitio nao, a voz respondia
    em ingles e parecia que «a lingua nao funciona».
    """
    quedas = [
        (n, l.strip())
        for n, l in enumerate(CODIGO.splitlines(), 1)
        if re.search(r'\.get\(\s*locale\s*,\s*"English"\s*\)', l)
    ]
    assert not quedas, (
        f"queda silenciosa para ingles em {quedas}: uma lingua nova na app "
        "e ignorada aqui sem nada falhar"
    )


def test_as_linguas_da_voz_sao_as_mesmas_da_app():
    """Duas listas de linguas que ninguem compara acabam por divergir.

    Foi assim que o espanhol desapareceu das sugestoes: tres copias, e a
    que discordava foi a que chegou ao ecra.
    """
    app = RAIZ.parent / "sky-mobile" / "apps" / "mobile" / "src" / "i18n.ts"
    if not app.exists():
        return  # a app nao esta ao lado; nada a comparar

    m = re.search(r'LINGUAS:\s*Lang\[\]\s*=\s*\[([^\]]*)\]', app.read_text(encoding="utf-8"))
    if not m:
        return
    da_app = set(re.findall(r'"(\w+)"', m.group(1)))

    mapa = re.search(r"_LINGUAS_DA_VOZ\s*=\s*\{([^}]*)\}", FONTE)
    assert mapa, "nao encontrei o mapa de linguas da voz"
    da_voz = set(re.findall(r'"(\w{2})"\s*:', mapa.group(1)))

    assert da_app <= da_voz, (
        f"a app fala {sorted(da_app)}, a voz conhece {sorted(da_voz)}: "
        f"falta {sorted(da_app - da_voz)}"
    )


def test_uma_sessao_sem_lingua_fica_registada():
    """O `locale = "en"` inicial e legitimo — clientes antigos nao o
    mandavam. O que nao pode e uma sessao inteira correr na lingua errada
    sem uma linha a dize-lo."""
    assert "nao mandou locale" in FONTE, (
        "uma sessao sem locale cai em ingles sem deixar rasto"
    )
