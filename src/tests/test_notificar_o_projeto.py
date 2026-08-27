"""Quem está no projeto recebe o que acontece no projeto.

> *"Temos que garantir que todos daquele projeto receberam a notificação
> daquele projeto."* — Lucas, 26/08/2026

As notificações existiam e iam para **uma** pessoa: quem criou o agente, quem
foi mencionado. Um achado sobre os dados de um projeto chegava a uma caixa e o
resto da equipa só o via se calhasse abrir o feed — e quem criou o agente pode
até já lá não estar.

O que estes testes fixam:

* a audiência é **toda a gente que alcança o projeto** — directos, por equipa,
  e quem o criou
* vem do **mesmo sítio** que decide o acesso aos dados, e não de uma segunda
  definição que acabaria por divergir
* quem provocou o acontecimento **não** é avisado do que acabou de fazer
* falhar a notificar **nunca** desfaz a acção que já aconteceu
"""

import uuid

import pytest

ESPACO = uuid.uuid4()
EQUIPA = uuid.uuid4()
DONO = uuid.uuid4()
DIRECTO = uuid.uuid4()
POR_EQUIPA = uuid.uuid4()


class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def all(self):
        return self._l

    def scalar_one_or_none(self):
        return self._l[0][0] if self._l else None


class _DB:
    def __init__(self, *, com_equipa=True):
        self.com_equipa = com_equipa

    async def execute(self, q):
        t = str(q)
        if "FROM spaces" in t:
            return _Res([(type("S", (), {"id": ESPACO, "created_by": DONO, "deleted_at": None})(),)])
        if "space_members" in t:
            return _Res([(DIRECTO,)])
        if "space_crews" in t:
            return _Res([(EQUIPA, "editor")] if self.com_equipa else [])
        if "FROM crews" in t and "crew_members" not in t:
            return _Res([])
        if "crew_members" in t:
            return _Res([(POR_EQUIPA,)] if self.com_equipa else [])
        return _Res([])


@pytest.mark.asyncio
async def test_a_audiencia_e_toda_a_gente_do_projeto():
    """Directos, por equipa, e quem o criou. Ninguém de fora, ninguém a menos."""
    from src.services.notificar_o_projeto import quem_esta_no_projeto

    pessoas = set(await quem_esta_no_projeto(_DB(), ESPACO))
    assert pessoas == {DONO, DIRECTO, POR_EQUIPA}


@pytest.mark.asyncio
async def test_quem_vem_so_por_equipa_conta():
    """**A parte que se esquece.**

    Quem não tem linha directa alcança o projeto pela equipa — e recebe as
    notificações dele. Contar só `space_members` deixaria metade da equipa às
    escuras sobre os seus próprios dados.
    """
    from src.services.notificar_o_projeto import quem_esta_no_projeto

    com = set(await quem_esta_no_projeto(_DB(com_equipa=True), ESPACO))
    sem = set(await quem_esta_no_projeto(_DB(com_equipa=False), ESPACO))
    assert POR_EQUIPA in com
    assert POR_EQUIPA not in sem


@pytest.mark.asyncio
async def test_quem_fez_a_accao_nao_e_avisado_dela(monkeypatch):
    """Receber *"a Ana entrou"* por se ter acrescentado a Ana é ruído.

    E ruído é o que faz as pessoas desligarem as notificações todas.
    """
    escritas = []

    class _Servico:
        def __init__(self, _db):
            pass

        async def create_notification(self, n):
            escritas.append(n.user_id)
            return n

    monkeypatch.setattr("src.services.notification_service.NotificationService", _Servico)

    from src.services.notificar_o_projeto import notificar_o_projeto

    await notificar_o_projeto(
        _DB(), ESPACO, tipo="system", title_key="notif.projectArchived", excepto=DONO
    )
    assert DONO not in escritas
    assert set(escritas) == {DIRECTO, POR_EQUIPA}


@pytest.mark.asyncio
async def test_falhar_a_notificar_nao_desfaz_a_accao(monkeypatch):
    """**Notificar é o remate, não a acção.**

    A equipa já foi convidada, o projeto já foi arquivado. Se o aviso falhar,
    não pode devolver um erro a quem fez o gesto — daria a entender que o
    gesto não se fez.
    """

    class _Servico:
        def __init__(self, _db):
            pass

        async def create_notification(self, n):
            raise RuntimeError("a caixa de correio explodiu")

    monkeypatch.setattr("src.services.notification_service.NotificationService", _Servico)

    from src.services.notificar_o_projeto import notificar_o_projeto

    # Não levanta. Devolve zero escritas, que é a verdade.
    assert await notificar_o_projeto(_DB(), ESPACO, tipo="system", title_key="x") == 0


def test_as_notificacoes_vao_TRADUZIVEIS_e_nao_em_ingles():
    """`title_key` + `title_params`, e não uma frase feita.

    O worker gravava *"{agente} found 3 new insights"* — a frase montada em
    inglês, com o plural do inglês, lida num telemóvel em português. A língua
    escolhe-se **quando se lê**, não quando se escreve; e a mesma equipa tem
    um português e um brasileiro.
    """
    import inspect

    from src.services.notificar_o_projeto import notificar_o_projeto

    fonte = inspect.getsource(notificar_o_projeto)
    assert "title_key=title_key" in fonte
    assert "title_params=title_params" in fonte


def test_o_achado_de_um_agente_chega_ao_projeto():
    """Ia só para quem criou o agente. Agora vai para o projeto todo."""
    import inspect

    from src.workers import agent_worker

    fonte = inspect.getsource(agent_worker)
    assert "notificar_o_projeto" in fonte
    # E não duplica para quem criou, que recebe pela via com `deep_link`.
    i = fonte.index("notificar_o_projeto(")
    assert "excepto=agent.created_by" in fonte[i : i + 1200]
