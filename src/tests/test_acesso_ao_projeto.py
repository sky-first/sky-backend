"""Quem alcança um projeto — e, sobretudo, quem NÃO alcança.

> *"Um projeto de operação com gente de operação não pode ver dados
> financeiros."* — Lucas, 26/08/2026

Os casos 1 a 5 e 8 de ``docs/pessoas-equipas-e-projetos.md`` §6.

Aqui não se testa a interface: testa-se a **função que decide**. Se ela
responder mal, nada do que estiver por cima a salva — e é por isso que existe
num sítio só. Dois sítios a decidir acesso é o caminho para dois resultados
diferentes.
"""

import uuid

import pytest

from src.services.acesso_ao_projeto import papel_mais_forte


class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def all(self):
        return self._l

    def scalar_one_or_none(self):
        return self._l[0][0] if self._l else None


class _DB:
    """A base reduzida ao que a resolução de acesso pergunta.

    ``ligacoes`` é a tabela `space_crews`, ``nativas`` são as equipas que
    nasceram dentro de um projeto (modelo antigo), e ``pertence`` diz em que
    equipas cada pessoa está.
    """

    def __init__(self, *, espaco, criador, directos=None, ligacoes=None, nativas=None, pertence=None):
        self.espaco, self.criador = espaco, criador
        self.directos = directos or {}
        self.ligacoes = ligacoes or {}
        self.nativas = nativas or {}
        self.pertence = pertence or {}
        self._pessoa = None

    async def execute(self, q):
        t = str(q)
        if "FROM spaces" in t:
            e = type("S", (), {"id": self.espaco, "created_by": self.criador, "deleted_at": None})()
            return _Res([(e,)])
        if "space_crews" in t:
            return _Res([(c, p) for c, p in self.ligacoes.items()])
        if "FROM crews" in t and "crew_members" not in t:
            return _Res([(c,) for c, s in self.nativas.items() if s == self.espaco])
        if "space_members" in t:
            return _Res([(self.directos.get(self._pessoa),)] if self._pessoa in self.directos else [])
        if "crew_members" in t:
            return _Res([(c,) for c in self.pertence.get(self._pessoa, [])])
        return _Res([])


async def _papel(db, pessoa, espaco):
    """Chama a função real, dizendo à base falsa de quem se está a falar."""
    from src.services import acesso_ao_projeto as m

    db._pessoa = pessoa

    # `Space` vem por `scalar_one_or_none` sobre um objecto, não sobre uma
    # tupla — a base falsa devolve tuplas, por isso adapta-se aqui.
    class _R2(_Res):
        def scalar_one_or_none(self):
            v = self._l[0][0] if self._l else None
            return v

    original = db.execute

    async def execute(q):
        r = await original(q)
        return _R2(r._l)

    db.execute = execute
    try:
        return await m.papel_no_projeto(db, pessoa, espaco)
    finally:
        db.execute = original


ESPACO_OP = uuid.uuid4()
ESPACO_FIN = uuid.uuid4()
EQUIPA_OP = uuid.uuid4()
EQUIPA_FIN = uuid.uuid4()
JOAO = uuid.uuid4()      # só operação
MARIA = uuid.uuid4()     # só finanças
DONO = uuid.uuid4()


def test_a_forca_dos_papeis():
    """Duas origens, fica a mais forte. É a regra do §3, escrita para ser
    escolha e não acidente."""
    assert papel_mais_forte("viewer", "editor") == "editor"
    assert papel_mais_forte("editor", "owner") == "owner"
    assert papel_mais_forte(None, "viewer") == "viewer"
    assert papel_mais_forte(None, None) is None
    # Um valor antigo que já não se usa não pode abrir nem fechar nada.
    assert papel_mais_forte("navigator", "editor") == "editor"


@pytest.mark.asyncio
async def test_1_operacao_nao_alcanca_financas():
    """**O caso que o Lucas nomeou.**

    O João está na equipa de Operação, que foi convidada para o projeto de
    Operação. O projeto de Finanças tem outra equipa. O João não lá chega —
    e não chega por omissão, sem ninguém ter de o proibir.
    """
    db = _DB(
        espaco=ESPACO_FIN,
        criador=DONO,
        ligacoes={EQUIPA_FIN: "editor"},
        pertence={JOAO: [EQUIPA_OP], MARIA: [EQUIPA_FIN]},
    )
    assert await _papel(db, JOAO, ESPACO_FIN) is None
    assert await _papel(db, MARIA, ESPACO_FIN) == "editor"


@pytest.mark.asyncio
async def test_2_papel_mais_forte_entre_directo_e_equipa():
    """Leitora directa + equipa editora = editora."""
    db = _DB(
        espaco=ESPACO_OP,
        criador=DONO,
        directos={JOAO: "viewer"},
        ligacoes={EQUIPA_OP: "editor"},
        pertence={JOAO: [EQUIPA_OP]},
    )
    assert await _papel(db, JOAO, ESPACO_OP) == "editor"


@pytest.mark.asyncio
async def test_3_tirar_a_linha_directa_nao_tira_o_acesso_da_equipa():
    """**A armadilha do S6, agora explícita.**

    Sem a linha directa, o João continua a alcançar o projeto pela equipa. É
    isto que a interface tem de dizer — e é por isto que a ligação viva é
    aceitável.
    """
    db = _DB(
        espaco=ESPACO_OP,
        criador=DONO,
        directos={},
        ligacoes={EQUIPA_OP: "editor"},
        pertence={JOAO: [EQUIPA_OP]},
    )
    assert await _papel(db, JOAO, ESPACO_OP) == "editor"


@pytest.mark.asyncio
async def test_4_equipa_sem_projeto_nenhum_nao_da_acesso_a_nada():
    """Uma lista de gente é uma lista de gente. O acesso nasce no projeto."""
    db = _DB(espaco=ESPACO_OP, criador=DONO, ligacoes={}, pertence={JOAO: [EQUIPA_OP]})
    assert await _papel(db, JOAO, ESPACO_OP) is None


@pytest.mark.asyncio
async def test_5_equipa_nativa_do_projeto_continua_a_valer():
    """O modelo antigo não se migra à força.

    Uma equipa que nasceu dentro do projeto continua a dar acesso lá. Ignorá-la
    cortaria o acesso a quem o tem hoje — e uma migração que tira acesso a
    quem trabalha é uma migração que não se pode fazer a meio da tarde.
    """
    db = _DB(
        espaco=ESPACO_OP,
        criador=DONO,
        nativas={EQUIPA_OP: ESPACO_OP},
        pertence={JOAO: [EQUIPA_OP]},
    )
    assert await _papel(db, JOAO, ESPACO_OP) == "editor"


@pytest.mark.asyncio
async def test_quem_criou_o_projeto_e_dono_dele():
    """Mesmo sem linha em `space_members`.

    Um projeto cujo criador perdeu a linha ficaria sem ninguém que o pudesse
    gerir — e a recuperação exigia alguém a mexer na base de dados.
    """
    db = _DB(espaco=ESPACO_OP, criador=DONO)
    assert await _papel(db, DONO, ESPACO_OP) == "owner"


@pytest.mark.asyncio
async def test_estranho_nao_alcanca_nada():
    """Fecha por omissão. Sem origem nenhuma, não há acesso."""
    db = _DB(espaco=ESPACO_OP, criador=DONO, ligacoes={EQUIPA_OP: "editor"})
    assert await _papel(db, uuid.uuid4(), ESPACO_OP) is None
