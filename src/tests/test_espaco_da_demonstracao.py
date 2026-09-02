"""O espaco primeiro, o dono depois — e nunca semear no espaco errado.

Os scripts de demonstracao procuravam uma conta fixa,
`rbac.owner@example.com`, e so depois os espacos dela. Essa conta e da
base local; na base do cliente `sandbox` nao existe, e o Job parava com
`Owner ... not found`.

Uma variavel de ambiente com o email so empurrava o problema: alguem tem
de saber qual e a conta certa, e ela muda de cliente para cliente. No
`sandbox` os quatro espacos tem DOIS criadores diferentes.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _carregar():
    caminho = RAIZ / "scripts" / "_espaco_da_demonstracao.py"
    spec = importlib.util.spec_from_file_location("_espaco_da_demonstracao", caminho)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_espaco_da_demonstracao"] = m
    spec.loader.exec_module(m)
    return m


class _Espaco:
    def __init__(self, nome, criador):
        self.name = nome
        self.created_by = criador
        self.id = f"id-{nome}"


class _Pessoa:
    def __init__(self, ident):
        self.id = ident
        self.email = f"{ident}@exemplo.pt"


class _Db:
    """Devolve espacos a primeira pergunta e a pessoa a segunda."""

    def __init__(self, espacos, pessoas):
        self._espacos = espacos
        self._pessoas = pessoas
        self._n = 0

    async def execute(self, _):
        self._n += 1
        dados = self._espacos if self._n == 1 else self._pessoas
        pai = self

        class _R:
            def scalars(self_inner):
                class _S:
                    def all(self_s):
                        return dados

                return _S()

            def scalar_one_or_none(self_inner):
                return dados[0] if dados else None

        return _R()


@pytest.mark.asyncio
@pytest.mark.parametrize("nome", ["Demo — Sky", "Demo - Sky", "Demo Sky"])
async def test_reconhece_as_variantes_do_nome(nome):
    """O travessao longo, o curto e nenhum — as tres existem no historico."""
    m = _carregar()
    espaco = _Espaco(nome, "u1")
    db = _Db([_Espaco("Teste", "u2"), espaco], [_Pessoa("u1")])

    achado, dono = await m.espaco_e_dono(db)

    assert achado is espaco
    assert dono.id == "u1"


@pytest.mark.asyncio
async def test_o_dono_vem_do_espaco_e_nao_de_um_email_fixo():
    """No sandbox o criador do espaco Demo nao e o das outras."""
    m = _carregar()
    db = _Db(
        [_Espaco("Teste", "outra-pessoa"), _Espaco("Demo Sky", "quem-criou-a-demo")],
        [_Pessoa("quem-criou-a-demo")],
    )

    _, dono = await m.espaco_e_dono(db)

    assert dono.id == "quem-criou-a-demo"


@pytest.mark.asyncio
async def test_sem_espaco_levanta_em_vez_de_escolher_outro():
    """Semear no espaco errado e pior do que nao semear: ninguem daria por isso."""
    m = _carregar()
    db = _Db([_Espaco("Teste", "u1"), _Espaco("123", "u1")], [_Pessoa("u1")])

    with pytest.raises(m.EspacoNaoEncontrado) as erro:
        await m.espaco_e_dono(db)

    # A mensagem tem de apontar a causa mais provavel, nao so o sintoma.
    assert "TENANT_SLUG" in str(erro.value)


@pytest.mark.asyncio
async def test_espaco_orfao_nao_passa_por_bom():
    m = _carregar()
    db = _Db([_Espaco("Demo Sky", "fantasma")], [])

    with pytest.raises(m.EspacoNaoEncontrado):
        await m.espaco_e_dono(db)
