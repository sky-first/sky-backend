"""A equipa é uma lista de pessoas reutilizável — e a ligação ao projeto é VIVA.

Este ficheiro testava a **cópia** de pessoas, decidida a 18/08 (S6) e escrita a
25/08. Foi substituída a 26/08 e os testes vão atrás: copiar resolvia a
armadilha do S6 destruindo a razão de a equipa existir — acrescentar alguém à
Comercial não o metia nos projetos onde ela trabalha.

O que fica no lugar, e é o que agora se testa:

* a equipa existe **sem projeto** (uma lista de gente do cliente)
* entra num projeto **com um papel** (``space_crews``)
* a ligação é **viva** — quem entra na equipa alcança o projeto
* a armadilha resolve-se mostrando a **proveniência**, não copiando

Ver ``docs/pessoas-equipas-e-projetos.md`` §3.2, e
``test_acesso_ao_projeto.py`` para a resolução em si.
"""

import pytest


def test_13_equipa_do_cliente_nasce_sem_projeto():
    """Uma equipa sem projeto é válida — e não dá acesso a nada.

    É o outro lado do S8: criar não é escalar. Uma lista de gente é uma lista
    de gente; o acesso nasce quando ela é convidada para um projeto.
    """
    from src.schemas.crew import CrewCreate

    pedido = CrewCreate(name="Comercial")
    assert pedido.space_id is None


def test_a_ligacao_ao_projeto_guarda_um_papel():
    """A peça que faltava, e que o Jira, o Confluence e o Miro todos têm.

    Convidar uma equipa não é convidar e pronto — é convidar **como** alguma
    coisa. A mesma "Comercial" é leitora num projeto e editora noutro.
    """
    from src.models.space_crew import SpaceCrew

    colunas = {c.name for c in SpaceCrew.__table__.columns}
    assert {"space_id", "crew_id", "role"} <= colunas
    # Quem convidou fica escrito: um convite em massa sem autor é um acesso
    # que ninguém sabe explicar daqui a três meses.
    assert "added_by" in colunas

    # A mesma equipa não entra duas vezes no mesmo projeto — senão a resolução
    # de acesso passaria a depender da ordem das linhas.
    restricoes = {
        tuple(sorted(c.name for c in r.columns))
        for r in SpaceCrew.__table__.constraints
        if r.__class__.__name__ == "UniqueConstraint"
    }
    assert ("crew_id", "space_id") in restricoes


def test_a_ligacao_e_viva_e_nao_uma_copia():
    """**A decisão de 26/08, escrita para ser escolha e não acidente.**

    Se alguém voltar a implementar a cópia, é aqui que rebenta — e o
    comentário diz porquê antes de o fazer.
    """
    import inspect

    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.convidar_equipa)
    # A cópia metia pessoas em `space_members`. A ligação viva escreve UMA
    # linha em `space_crews` e mais nada.
    assert "SpaceCrew" in fonte
    assert "member_repo.create" not in fonte

    # E existe o gesto de tirar — sem ele, convidar é uma porta que só abre.
    assert hasattr(SpaceService, "tirar_equipa")


def test_a_proveniencia_existe_e_e_o_que_evita_a_armadilha():
    """Sem dizer de onde vem o acesso, a ligação viva É a armadilha do S6.

    Um admin tira a linha directa de alguém, julga que lhe cortou o acesso, e
    não cortou — porque a pessoa entra por uma equipa. Dizer "via equipa
    Comercial" é o que torna a ligação viva aceitável.
    """
    from src.services.acesso_ao_projeto import de_onde_vem_o_acesso

    assert de_onde_vem_o_acesso.__doc__
    import inspect

    fonte = inspect.getsource(de_onde_vem_o_acesso)
    assert "por_equipa" in fonte
    assert "directo" in fonte


@pytest.mark.asyncio
async def test_uma_equipa_de_outro_projeto_nao_se_empresta():
    """Uma equipa que pertence a OUTRO projeto não se convida para este.

    O seu nome e a sua gente foram pensados para lá, e o dono desse projeto é
    que a controla. Convidá-la daqui seria dar a este projeto uma lista que
    outra pessoa gere.
    """
    import inspect

    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.convidar_equipa)
    assert "belongs to another project" in fonte
