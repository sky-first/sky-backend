"""Convidar uma pessoa para um projeto — e ela aceitar.

> *"Clicamos em convidar e abre o modal para pesquisar pessoas dentro da
> empresa inteira, clicamos e enviamos um convite à pessoa, esta recebe uma
> notificação e aceita o projeto, e nós recebemos uma notificação que a
> pessoa aceitou o projeto."* — Lucas, 26/08/2026

O que estes testes fixam, por ordem de importância:

1. **Um convite pendente não é acesso.** É a única parte onde um erro sai
   caro: alguém a ver números de uma área que não é a sua sem ter dito que
   sim, e sem sequer saber que lá está.
2. **Só a pessoa convidada responde.** Nem quem convidou responde por ela — e
   quem não é o destinatário nem fica a saber que o convite existe.
3. A pesquisa mostra a empresa inteira **menos** quem já lá está.
4. As notificações vão traduzíveis, e não em inglês.

O caminho completo — convidar, não alcançar, aceitar, alcançar — está provado
contra a base a correr; estes testes são o que impede que volte atrás.
"""

import inspect
import uuid

import pytest


def test_um_convite_pendente_NAO_da_acesso():
    """**O teste que importa.**

    `acesso_ao_projeto` é o único sítio que decide quem alcança um projeto.
    Se alguma vez passar a ler `convites_ao_projeto`, um convite por responder
    passa a valer acesso — e o botão de aceitar passa a ser decoração sobre
    uma porta que já estava aberta.
    """
    from src.services import acesso_ao_projeto

    fonte = inspect.getsource(acesso_ao_projeto)
    assert "convite" not in fonte.lower(), (
        "acesso_ao_projeto passou a olhar para convites: um convite por "
        "responder passaria a dar acesso aos dados do projeto"
    )


def test_aceitar_entra_pela_geral_e_nao_por_uma_segunda_lista():
    """Um sítio só onde se procura gente.

    Ideia do Lucas, e simplifica o modelo: em vez de uma lista de "convidados
    directamente" ao lado das equipas, quem é convidado à unidade entra na
    **Geral**. A regra fica de uma frase — *se não veio por uma equipa sua,
    veio pela Geral*.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    assert "equipa_geral" in fonte
    assert "CrewMember(" in fonte


def test_quem_nao_e_o_destinatario_nem_sabe_que_o_convite_existe():
    """404, e não 403.

    Um 403 confirmaria que aquele convite existe — a quem não é dele. Com
    quatro tentativas descobria-se quem foi convidado para onde.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    i = fonte.index("convite.user_id != user.id")
    assert "NotFoundError" in fonte[i : i + 300]
    assert "ForbiddenError" not in fonte[i : i + 300]


def test_a_pesquisa_nao_filtra_por_status():
    """**A armadilha que quase entrou.**

    Na tabela `users`, `status` é presença — `active`/`away`/`offline` — e não
    estado de conta. Filtrar por `status == "active"` parecia a coisa certa e
    escondia toda a gente que não estivesse com a app aberta naquele instante:
    a pesquisa da empresa inteira devolveria quase sempre uma lista vazia.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.pessoas_para_convidar)
    assert 'User.status' not in fonte
    assert "User.deleted_at.is_(None)" in fonte


def test_a_pesquisa_esconde_quem_ja_esta_no_projeto():
    """E esconde-o pela mesma definição que decide o acesso.

    Uma segunda definição de "quem está no projeto" acabaria por divergir — e
    a divergência apareceria como convidar alguém que já lá está, para receber
    um erro a dizê-lo.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.pessoas_para_convidar)
    assert "quem_esta_no_projeto" in fonte
    assert "u.id not in ja_la" in fonte


def test_a_pesquisa_pede_mais_do_que_mostra():
    """Descartar depois de limitar devolveria menos do que o limite.

    Com dez pessoas já no projeto e um limite de vinte, pedir vinte e cortar
    dez deixava dez — e parecia que a empresa só tinha dez pessoas.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.pessoas_para_convidar)
    assert "limite + len(ja_la)" in fonte


def test_procura_por_nome_OU_email():
    """Procura-se pelo nome. Mas há homónimos, e há quem só saiba o email."""
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.pessoas_para_convidar)
    assert "or_(" in fonte
    assert "User.name.ilike" in fonte and "User.email.ilike" in fonte


def test_convidar_avisa_SO_a_pessoa_convidada():
    """O projeto fica a saber quando ela **entrar**.

    Anunciar ao projeto inteiro uma entrada que pode nunca acontecer é ruído,
    e ruído é o que faz as pessoas desligarem as notificações todas.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.convidar_pessoa)
    assert "notificar_o_projeto(" not in fonte
    assert "user_id=alvo_id" in fonte


def test_aceitar_avisa_o_projeto_inteiro():
    """Incluindo quem convidou, que é quem espera a resposta.

    Um acesso novo aos dados de um projeto não é assunto privado entre quem
    convida e quem é convidado.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    i = fonte.index("if aceitar:", fonte.index("await self.db.commit()"))
    trecho = fonte[i : i + 800]
    assert "notificar_o_projeto(" in trecho
    assert "excepto=user.id" in trecho


def test_as_notificacoes_do_convite_vao_traduziveis():
    """`title_key`, e não uma frase inglesa montada no servidor.

    A língua escolhe-se quando se lê. A mesma equipa tem um português e um
    brasileiro, e o servidor não sabe a língua de quem vai abrir a caixa.
    """
    from src.services.space_service import SpaceService

    for metodo in (SpaceService.convidar_pessoa, SpaceService.responder_ao_convite):
        fonte = inspect.getsource(metodo)
        for linha in fonte.splitlines():
            if "title=" in linha and "title_key" not in linha:
                assert "notif." in linha, f"título em prosa: {linha.strip()}"


def test_um_convite_vivo_de_cada_vez_mas_quem_recusou_pode_ser_reconvidado():
    """O estado entra na chave única.

    Sem ele, quem recusasse uma vez nunca mais podia ser convidado: a segunda
    tentativa chocava com o registo da primeira. Com ele, os convites
    respondidos ficam guardados e a segunda tentativa passa.
    """
    from src.models.convite_ao_projeto import ConviteAoProjeto

    restricoes = [
        c for c in ConviteAoProjeto.__table_args__ if getattr(c, "name", "") == "uq_convite_vivo"
    ]
    assert restricoes, "falta a chave única do convite vivo"
    colunas = [c.name for c in restricoes[0].columns]
    assert colunas == ["space_id", "user_id", "estado"]


def test_responder_duas_vezes_nao_passa():
    """Aceitar um convite já aceite não pode voltar a notificar o projeto."""
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    assert 'convite.estado != "pendente"' in fonte
    assert "BadRequestError" in fonte


def test_as_rotas_do_convite_nao_vivem_debaixo_de_space_id():
    """**A colisão que já aconteceu.**

    `/spaces/{space_id}` apanha qualquer segmento a seguir a `/spaces`:
    `/spaces/meus-convites` era lido como *o projeto chamado "meus-convites"*
    e morria em `422` antes de chegar à função. Dava para resolver com a ordem
    de declaração — e partia-se na primeira vez que alguém arrumasse o
    ficheiro.
    """
    from src.main import app

    caminhos = [
        r.path for r in app.routes if "convite" in getattr(r, "path", "") and "/api/v1" in r.path
    ]
    assert caminhos, "as rotas de convites desapareceram"
    for p in caminhos:
        if p.startswith("/api/v1/spaces/"):
            # Sob /spaces só é seguro o que vem depois de {space_id}.
            assert "{space_id}" in p, f"{p} colide com /spaces/{{space_id}}"


@pytest.mark.parametrize("papel", ["owner", "editor", "viewer"])
def test_o_convite_leva_o_papel_e_nao_o_inventa_ao_aceitar(papel):
    """Quem convida escolhe o papel; ao aceitar, é esse que vale.

    Se o papel nascesse no momento de aceitar, convidar alguém como leitor e
    ele entrar como editor era uma questão de tempo.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    assert "role=convite.papel" in fonte
    assert papel in inspect.getsource(SpaceService.convidar_pessoa)


def test_um_projeto_antigo_sem_geral_ainda_deixa_aceitar():
    """Recusar deixaria o convite impossível de aceitar.

    E por uma razão que não é da pessoa que o recebeu: o projeto ter sido
    criado antes desta regra existir.
    """
    from src.services.space_service import SpaceService

    fonte = inspect.getsource(SpaceService.responder_ao_convite)
    i = fonte.index("if geral is None:")
    assert "crew_repo.create" in fonte[i : i + 500]


def test_o_id_do_convite_e_um_uuid_e_nao_um_contador():
    """Um contador deixava adivinhar convites alheios pelo id seguinte."""
    from src.models.convite_ao_projeto import ConviteAoProjeto

    coluna = ConviteAoProjeto.__table__.c.id
    assert "UUID" in str(coluna.type).upper()
    assert coluna.default is not None, "sem `default`, o id vinha do cliente"
