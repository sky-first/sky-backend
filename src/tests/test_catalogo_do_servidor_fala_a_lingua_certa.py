"""O catálogo de frases do servidor.

O `src/core/locale.py` é a cópia do servidor dos textos que o utilizador
lê. Tinha três defeitos ao mesmo tempo, e nenhum deles dava erro.

── 1. Estava em português do Brasil ─────────────────────────────────

    «Você foi mencionado em um comentário»
    «Mencionaram você: …»
    «na aba Editar, ou mude…»  ·  «Adicione uma conexão»
    «Pensando...»

A web e a app já tinham sido corrigidas (26/08). Este ficheiro é a cópia
do servidor e ficou para trás.

── 2. Usava o vocabulário antigo ────────────────────────────────────

    «Você foi adicionado ao espaço 'X'»

Hoje chama-se **projeto** em toda a aplicação. O próprio ficheiro já
dizia «Este projeto ainda não tem dados» vinte linhas acima.

── 3. Não conhecia espanhol — e isso era pior do que ficar em inglês ─

`_ALLOWED` era `{"en", "pt"}`. `normalize_locale("es")` não caía no
inglês: caía no `DEFAULT_LOCALE`, que é `pt`. **Um cliente espanhol
recebia português.**

── Porque é que isto se vê no ecrã ──────────────────────────────────

Poder-se-ia argumentar que o `title` é só uma rede de segurança, porque
o cliente traduz a partir do `title_key`. Só que a app **não conhece
estas seis chaves** — o `tituloDaNotificacao` cai no `default:`, que
devolve o `title` do servidor tal e qual.

Ou seja: numa app cuja interface inteira diz «projeto», a lista de
notificações dizia «Você foi adicionado ao espaço 'X'».
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

#: A raiz DESTE repositorio — `src/tests/x.py` → dois niveis acima.
#:
#: ⚠️ Estava escrito a contar a partir da pasta que esta acima de todos os
#: repositorios, com o nome «sky-poc-backend» cravado. Aqui a pasta local
#: chama-se assim; na integracao o checkout chama-se «sky-backend», que e o
#: nome do repositorio. Passava localmente e chumbava la.
REPO = Path(__file__).resolve().parents[2]

#: A pasta que contem os varios repositorios — pode nao existir na
#: integracao, onde so este e clonado.
LADO_A_LADO = REPO.parent

_spec = importlib.util.spec_from_file_location(
    "_locale_sob_teste", REPO / "src" / "core" / "locale.py"
)
locale = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(locale)

LINGUAS = ("pt", "en", "es")


# ---------------------------------------------------------------------------
# Completude
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chave", sorted(locale._MESSAGES))
def test_cada_frase_existe_nas_tres_linguas(chave):
    faltam = [lang for lang in LINGUAS if lang not in locale._MESSAGES[chave]]
    assert not faltam, f"{chave} não existe em {faltam}"


@pytest.mark.parametrize("lingua", LINGUAS)
def test_a_lingua_e_reconhecida(lingua):
    assert locale.normalize_locale(lingua) == lingua


def test_o_espanhol_nao_cai_no_portugues():
    """O defeito exacto: `es` dava `pt`, não `en`.

    Receber inglês quando se pediu espanhol é uma falha honesta. Receber
    português é a plataforma a afirmar uma coisa errada com confiança.
    """
    for pedido in ("es", "es-ES", "es-MX", "es-419"):
        assert locale.normalize_locale(pedido) == "es", pedido


def test_uma_lingua_que_nao_falamos_continua_a_cair_no_padrao():
    assert locale.normalize_locale("fr") == locale.DEFAULT_LOCALE
    assert locale.normalize_locale("de") == locale.DEFAULT_LOCALE
    assert locale.normalize_locale(None) == locale.DEFAULT_LOCALE


# ---------------------------------------------------------------------------
# Português de Portugal
# ---------------------------------------------------------------------------

def _so_o_que_se_le(frase: str) -> str:
    """A frase sem os {parametros}.

    O nome de um parametro nao aparece no ecra: `{crew}` e o que o codigo
    passa, nao o que a pessoa le. Sem isto, o teste do vocabulario
    chumbava em «Foi adicionado a equipa «{crew}»» — que esta certa.
    """
    return re.sub(r"\{[^}]*\}", " ", frase)


#: Palavras que só existem no português do Brasil, ou que em Portugal se
#: dizem de outra maneira. Cada uma destas esteve mesmo neste ficheiro.
BRASILEIRISMOS = {
    r"\bvocê\b": "em Portugal a frase é impessoal («Foi adicionado»)",
    r"\bconexão\b": "«ligação»",
    r"\bconexões\b": "«ligações»",
    r"\baba\b": "«separador»",
    r"\busuário": "«utilizador»",
    r"\btela\b": "«ecrã»",
    r"\bcelular\b": "«telemóvel»",
    r"\btime\b": "«equipa»",
    r"\bem um\b": "«num»",
    r"\bem uma\b": "«numa»",
}


@pytest.mark.parametrize("padrao,certo", sorted(BRASILEIRISMOS.items()))
def test_o_portugues_e_o_de_portugal(padrao, certo):
    maus = [
        (chave, v["pt"])
        for chave, v in locale._MESSAGES.items()
        if re.search(padrao, _so_o_que_se_le(v.get("pt", "")), re.IGNORECASE)
    ]
    assert not maus, f"{padrao} — devia ser {certo}: {maus}"


def test_o_vocabulario_e_o_novo():
    """«espaço» e «crew» são os nomes antigos.

    Hoje é **projeto** e **equipa**, em toda a aplicação.
    """
    maus = [
        (chave, v["pt"])
        for chave, v in locale._MESSAGES.items()
        if re.search(
            r"\bespaços?\b|\bcrews?\b", _so_o_que_se_le(v.get("pt", "")), re.IGNORECASE
        )
    ]
    assert not maus, f"vocabulário antigo: {maus}"


# ---------------------------------------------------------------------------
# Sincronia com a web
# ---------------------------------------------------------------------------
def _dicionario_da_web(lang: str) -> dict[str, str]:
    # Na integração só este repositório é clonado, por isso a comparação
    # com a web só corre na máquina de quem desenvolve. Não é ideal — mas
    # o alternativo era não a ter de todo.
    caminho = LADO_A_LADO / "sky-poc-frontend" / "messages" / f"{lang}.json"
    if not caminho.exists():  # pragma: no cover - repositório sozinho
        pytest.skip("o repositório da web não está ao lado deste")

    achatado: dict[str, str] = {}

    def _desce(o):
        for k, v in o.items():
            if isinstance(v, dict):
                _desce(v)
            else:
                achatado[k] = v

    _desce(json.loads(caminho.read_text(encoding="utf-8")))
    return achatado


@pytest.mark.parametrize("lingua", LINGUAS)
def test_as_notificacoes_dizem_o_mesmo_dos_dois_lados(lingua):
    """A mesma chave não pode dar frases diferentes conforme o cliente.

    Era exactamente o que acontecia: a web dizia «Foi adicionado ao
    projeto «X»» e o servidor gravava «Você foi adicionado ao espaço
    'X'». Quem abrisse a web via uma coisa e quem abrisse a app via
    outra — da MESMA notificação.

    Isto compara só as chaves que existem dos dois lados. O servidor pode
    ter frases que a web nunca mostra (as do chat), e a web tem centenas
    que o servidor não conhece.
    """
    web = _dicionario_da_web(lingua)

    diferentes = []
    for chave in sorted(locale.NOTIFICATION_KEYS):
        no_servidor = locale._MESSAGES.get(chave, {}).get(lingua)
        na_web = web.get(chave)
        if no_servidor is None or na_web is None:
            continue
        if no_servidor != na_web:
            diferentes.append((chave, no_servidor, na_web))

    assert not diferentes, "\n".join(
        f"  {c}\n    servidor: {s!r}\n    web     : {w!r}" for c, s, w in diferentes
    )


def test_a_comparacao_com_a_web_nao_esta_vazia():
    """Uma comparação de zero chaves passa sempre, e não prova nada.

    Já me aconteceu hoje noutro teste: procurava um bloco que saía vazio,
    passava, e não verificava coisa nenhuma.
    """
    web = _dicionario_da_web("pt")
    comuns = [c for c in locale.NOTIFICATION_KEYS if c in web]
    assert len(comuns) >= 6, (
        f"só {len(comuns)} chaves em comum com a web — a comparação não está "
        "a ver nada"
    )
