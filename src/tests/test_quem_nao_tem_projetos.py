"""Quem não está em projeto nenhum é dono do SEU mundo, não de tudo.

Encontrado a 18/08/2026 a testar a matriz de permissões com contas reais criadas
no sandbox, a pedido do Lucas — que perguntou se eu tinha mesmo testado com
owner, admin e member. Não tinha; ao ir fazê-lo, apareceu isto.

`_best_role_for_user_anywhere` devolve ``"owner"`` a quem não tem espaços nem
equipas, e a intenção está escrita no código: alguém acabado de entrar tem de
conseguir criar a primeira página. O problema é que esse "dono do mundo pessoal"
escorregava para permissões que não são do mundo pessoal.

Confirmado com contas reais em produção — um ``member`` sem um único projeto:

    connections.create      Authorization.can()=False   assert_permission()=SIM
    connections.sync        Authorization.can()=False   assert_permission()=SIM
    spaces.members.manage   Authorization.can()=False   assert_permission()=SIM

As duas vias de autorização discordavam, e a que as rotas usam era a permissiva.
`POST /connections` chama `assert_permission("connections.create")` **sem**
`space_id`, portanto era alcançável do browser por qualquer pessoa convidada.
Criar uma ligação é apontar a Sky a uma base de dados à escolha de quem a cria.

Estes testes guardam as duas metades, porque corrigir só uma parte o problema:
o member deixa de cunhar ligações **e** continua a poder arrancar sozinho.
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.rbac_service import RBACService


def _pessoa(nome: str, papel: str = "member") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{nome.lower()}@empresa-de-mentira.pt",
        role=papel,
        password_hash="x",
        name=nome,
    )


async def _recem_chegado(db) -> User:
    """Alguém acabado de convidar: sem projetos, sem equipas."""
    u = _pessoa("Novato")
    db.add(u)
    await db.flush()
    return u


# ── O buraco ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sem_projetos_nao_cunha_ligacoes(db_session):
    """A que interessa: criar uma ligação é apontar a Sky a uma base de dados.

    A rota `POST /connections` chama isto sem `space_id`. Se voltar a passar,
    qualquer pessoa convidada para o cliente pode ligar a Sky ao que quiser.
    """
    novato = await _recem_chegado(db_session)
    svc = RBACService(db_session)

    with pytest.raises(ForbiddenError):
        await svc.assert_permission(novato, "connections.create")
    with pytest.raises(ForbiddenError):
        await svc.assert_permission(novato, "connections.edit")
    with pytest.raises(ForbiddenError):
        await svc.assert_permission(novato, "connections.sync")


@pytest.mark.asyncio
async def test_sem_projetos_nao_administra_membros(db_session):
    """Gerir membros de um projeto — de qual? Não está em nenhum."""
    novato = await _recem_chegado(db_session)
    svc = RBACService(db_session)

    with pytest.raises(ForbiddenError):
        await svc.assert_permission(novato, "spaces.members.manage")


@pytest.mark.asyncio
async def test_sem_projetos_cria_o_seu_primeiro_projeto(db_session):
    """Invertido a 19/08, por decisão do Lucas.

    Este teste exigia o contrário, e escrevi-o eu ontem ao fechar o buraco do
    "sem projetos era dono de tudo". Estava certo para o modelo de então;
    deixou de estar.

    Quem chega hoje ao produto e não pertence a projeto nenhum tem de poder
    criar o primeiro — senão fica à espera de que alguém o convide, e o
    produto não arranca. O que continua fechado é o que interessa: **ligar
    dados** a esse projeto (ver o teste a seguir). Um projeto vazio não dá
    acesso a nada.
    """
    e = await _recem_chegado(db_session)
    svc = RBACService(db_session)

    await svc.assert_permission(e, "spaces.create")  # não levanta


@pytest.mark.asyncio
async def test_mas_continua_sem_poder_ligar_dados(db_session):
    """A metade que segura a inversão acima.

    Se esta cair, "qualquer um cria um projeto" passa a significar "qualquer
    um liga a base de dados que quiser", e o pedido de acesso deixa de ter
    razão de existir.
    """
    e = await _recem_chegado(db_session)
    svc = RBACService(db_session)

    for chave in ("connections.create", "connections.edit", "connections.delete"):
        with pytest.raises(ForbiddenError):
            await svc.assert_permission(e, chave)


# ── A metade que tem de continuar a funcionar ────────────────────────────────


@pytest.mark.asyncio
async def test_sem_projetos_continua_a_arrancar_sozinho(db_session):
    """A intenção original, que não se pode perder ao fechar o buraco.

    Quem entra hoje tem de conseguir criar a sua primeira página e o seu
    primeiro widget, senão fica a olhar para um ecrã vazio sem saída. Se este
    teste passar a falhar, a correcção foi longe de mais.
    """
    novato = await _recem_chegado(db_session)
    svc = RBACService(db_session)

    # `widgets.create` fica de fora: não existe em `PERMISSION_RULES` e cai em
    # "chave desconhecida" para toda a gente que não seja admin do cliente.
    # É anterior a isto e está anotado à parte — ver o resumo das 11 chaves
    # asseridas nas rotas sem regra. O mesmo vale para `ai.chat`.
    for chave in ("pages.create", "agents.create"):
        await svc.assert_permission(novato, chave)  # não levanta


# ── O admin não é afectado ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o_admin_continua_a_passar_sem_projetos(db_session):
    """O portão novo é para quem NÃO é admin do cliente.

    Um admin sem projetos continua a administrar — é o trabalho dele, e é assim
    que se monta um cliente do zero.
    """
    admin = _pessoa("Admin", "admin")
    db_session.add(admin)
    await db_session.flush()
    svc = RBACService(db_session)

    for chave in ("connections.create", "spaces.members.manage", "spaces.create"):
        await svc.assert_permission(admin, chave)  # não levanta


# ── Com projeto, a regra normal volta a mandar ───────────────────────────────


@pytest.mark.asyncio
async def test_com_projeto_vale_o_papel_no_projeto(db_session):
    """O portão novo só se aplica a quem não tem projeto nenhum.

    Assim que entra num, é o papel lá dentro que decide — que é o modelo. Sem
    este teste, a correcção podia estar a trancar toda a gente para sempre e os
    outros passavam na mesma.
    """
    dono = _pessoa("Dono", "member")
    membro = _pessoa("Membro", "member")
    db_session.add_all([dono, membro])
    await db_session.flush()

    projeto = Space(
        id=uuid.uuid4(),
        name="Financeiro",
        created_by=dono.id,
        privacy="private",
        sensitivity="internal",
        is_demo=False,
    )
    db_session.add(projeto)
    await db_session.flush()
    db_session.add(
        SpaceMember(id=uuid.uuid4(), space_id=projeto.id, user_id=membro.id, role="owner")
    )
    await db_session.flush()

    svc = RBACService(db_session)
    # Dono do projeto: administra os membros DESSE projeto.
    await svc.assert_permission(membro, "spaces.members.manage", space_id=projeto.id)
