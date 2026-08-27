"""Não há projetos públicos — e o servidor deixa de fingir que há.

> *"Aqui está projeto privado e público. Como assim? Não existe projeto
> público, pois não? No telemóvel não tem projeto público. Todos os projetos
> são, tens que convidar as pessoas."* — Lucas, 27/08/2026

Tem razão, e era pior do que uma opção a mais.

---

**O campo era guardado e nunca lido.**

`spaces.privacy` existe na base desde sempre e aceitava `"public"`. Procurei
`.privacy` em todo o backend: **não aparece em nenhuma decisão de acesso** —
nem em `acesso_ao_projeto`, nem no `rbac_service`, nem no `space_service`.

Quem alcança um projeto alcança-o por uma de duas vias, e mais nenhuma:

* uma linha em `space_members` (convite directo);
* uma equipa vinculada em `space_crews`.

Ou seja: um projeto marcado «Público» era exactamente tão privado como os
outros. A escolha não fazia nada.

**E é isso que a torna pior do que uma funcionalidade em falta.** Quem
escolhia «Público» ficava convencido de que tinha aberto o projeto à
empresa. Um controlo de acesso que promete o que não cumpre é uma expectativa
errada sobre quem vê os dados — e essa é a única expectativa que aqui não se
pode errar.

O telemóvel nunca teve o conceito: nem no ecrã, nem no cliente de API.

---

**Abrir um projeto a toda a empresa continua a ser possível como decisão de
produto.** Só que implica escrevê-la na resolução de acesso — não repor um
campo que ninguém lê.
"""

import inspect
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas.space import SpaceCreate, SpaceUpdate

RAIZ = Path(__file__).resolve().parents[2] / "src"


def test_criar_projeto_nao_aceita_publico():
    """O caminho por onde a escolha entrava."""
    with pytest.raises(ValidationError):
        SpaceCreate(name="Operação", privacy="public")


def test_alterar_projeto_nao_aceita_publico():
    """A segunda porta.

    Fechar só a criação deixava um `PATCH` a tornar público um projeto que
    nasceu privado — e ninguém a olhar para lá.
    """
    with pytest.raises(ValidationError):
        SpaceUpdate(privacy="public")


def test_privado_continua_a_passar():
    """O guarda não pode partir o caminho normal."""
    assert SpaceCreate(name="Operação").privacy == "private"
    assert SpaceCreate(name="Operação", privacy="private").privacy == "private"
    assert SpaceUpdate(privacy="private").privacy == "private"


def test_o_campo_continua_sem_decidir_acesso():
    """**O essencial: nada lê `privacy` para decidir quem vê o quê.**

    Se um dia alguém o passar a ler, esta regra deixa de ser verdade e o
    campo volta a prometer alguma coisa — nessa altura, é uma decisão a
    tomar de propósito, não um efeito lateral.
    """
    suspeitos = []
    for caminho in RAIZ.rglob("*.py"):
        if "tests" in caminho.parts or "__pycache__" in caminho.parts:
            continue
        # `schemas/space.py` e `models/space.py` DECLARAM o campo, e isso
        # é o que se espera. O que não pode é alguém consultá-lo para decidir.
        if caminho.name == "space.py" and caminho.parent.name in ("schemas", "models"):
            continue
        try:
            fonte = caminho.read_text(encoding="utf-8")
        except OSError:
            continue
        for n, linha in enumerate(fonte.splitlines(), 1):
            if linha.lstrip().startswith("#"):
                continue
            if re.search(r"\.privacy\b", linha) and "privacy." not in linha:
                suspeitos.append(f"{caminho.relative_to(RAIZ)}:{n}: {linha.strip()}")
    assert suspeitos == []


def test_a_resolucao_de_acesso_tem_duas_vias_e_nenhuma_e_a_privacidade():
    """As vias reais, escritas onde se possam ler."""
    from src.services import acesso_ao_projeto

    fonte = inspect.getsource(acesso_ao_projeto)
    assert "space_members" in fonte
    assert "space_crews" in fonte or "equipas_que_alcancam" in fonte
    assert "privacy" not in fonte
