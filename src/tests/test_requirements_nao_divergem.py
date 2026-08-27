"""Os ficheiros de dependências não podem fixar versões diferentes.

**O que aconteceu a 26/08/2026.** Doze testes de MFA falhavam com::

    ImportError: The version of cryptography does not match the loaded shared
    object. ... Loaded python version: 48.0.1, shared object version: 42.0.2

A mensagem manda criar um ambiente novo, e a causa não estava na máquina:

    requirements.txt      cryptography==48.0.1
    requirements-dev.txt  cryptography==42.0.2

Quem instalasse os dois ficava com os metadados de uma versão e o binário
nativo da outra. Mais cinco pacotes divergiam em silêncio — `sqlalchemy`
2.0.25 contra 2.0.36, `python-jose` 3.3.0 contra 3.4.0 — e quem desenvolvia
testava contra bibliotecas que não eram as de produção.

O `requirements-dev.txt` passou a herdar (`-r requirements.txt`). Este teste
impede que volte a ser uma segunda lista.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

#: Um pino do tipo `pacote==versão`, com extras opcionais.
PINO = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==(.+)$")


def _pinos(nome: str) -> dict[str, str]:
    ficheiro = RAIZ / nome
    encontrados: dict[str, str] = {}
    for linha in ficheiro.read_text(encoding="utf-8").splitlines():
        sem_comentario = linha.split("#")[0].strip()
        m = PINO.match(sem_comentario)
        if m:
            encontrados[m.group(1).lower()] = m.group(3)
    return encontrados


def test_os_ficheiros_existem_e_tem_pinos():
    """Sem esta âncora, um erro na leitura aprovava tudo em silêncio."""
    assert len(_pinos("requirements.txt")) > 30


def test_o_dev_herda_o_base_em_vez_de_o_copiar():
    """**A correcção estrutural.**

    Enquanto o `dev` herdar, não há duas versões da mesma coisa para
    divergirem. Se alguém voltar a copiar a lista, isto falha aqui e não
    daqui a três semanas com um `ImportError` que culpa a máquina.
    """
    dev = (RAIZ / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in dev, (
        "o requirements-dev.txt deixou de herdar o de produção — e volta a "
        "poder divergir dele"
    )


def test_nenhum_pacote_tem_duas_versoes():
    """A verificação directa, para o caso de a herança se perder."""
    base = _pinos("requirements.txt")
    dev = _pinos("requirements-dev.txt")
    divergem = {k: (base[k], dev[k]) for k in set(base) & set(dev) if base[k] != dev[k]}
    assert divergem == {}, (
        "estes pacotes estão fixados em duas versões diferentes — quem "
        f"instalar os dois ficheiros fica com um ambiente partido: {divergem}"
    )


@pytest.mark.parametrize("pacote", ["pytest", "black", "isort", "flake8", "mypy", "faker"])
def test_as_ferramentas_de_trabalho_vem_de_um_sitio_so(pacote):
    """O `requirements-dev.txt` diz que estas vêm do ficheiro de produção.

    Se deixarem de lá estar, o comentário do ficheiro passa a mentir e quem
    instalar só o `dev` fica sem elas.
    """
    assert pacote in _pinos("requirements.txt")
