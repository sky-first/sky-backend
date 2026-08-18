"""Cruzar projetos: livre para explorar, travado para publicar.

Opção C do modelo (``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §4).
Quem cruza já tem acesso a cada peça — o risco não é a leitura, é a
**agregação** e a **redistribuição**. Daí o travão estar na saída.

Os casos do §6 cobertos aqui:

* **S9** o resultado cruzado não se fixa numa página;
* **S10** a união é calculada a cada pergunta, nunca em cache — sair de um
  projeto tira-o do cruzamento já a seguir;
* **S11** a fonte marcada fica fora da união ao **construí-la**, não no ecrã.

Cenário: o Lucas está no Financeiro e no Marketing. O RH existe e ele não está
lá. Uma das ligações traz salários e está marcada.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.config.settings import settings
from src.core.exceptions import BadRequestError
from src.models.connection import DataConnection
from src.models.space import Space, SpaceMember, SpaceTable
from src.models.user import User
from src.services.permission_service import PermissionService


@pytest.fixture
def fronteira_no_projeto(monkeypatch):
    monkeypatch.setattr(settings, "DATA_BOUNDARY", "project")


def _pessoa(nome: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{nome.lower()}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name=nome,
    )


def _projeto(nome: str, dono: User) -> Space:
    return Space(
        id=uuid.uuid4(),
        name=nome,
        created_by=dono.id,
        privacy="private",
        sensitivity="internal",
        is_demo=False,
    )


async def _empresa(db):
    lucas, outra = _pessoa("Lucas"), _pessoa("Outra")
    db.add_all([lucas, outra])
    await db.flush()

    erp = DataConnection(
        id=uuid.uuid4(),
        name="ERP",
        connector_id="postgres",
        config={},
        created_by=outra.id,
    )
    db.add(erp)
    await db.flush()

    financeiro = _projeto("Financeiro", outra)
    marketing = _projeto("Marketing", outra)
    rh = _projeto("RH", outra)
    db.add_all([financeiro, marketing, rh])
    await db.flush()

    db.add_all(
        [
            SpaceMember(id=uuid.uuid4(), space_id=financeiro.id, user_id=lucas.id, role="editor"),
            SpaceMember(id=uuid.uuid4(), space_id=marketing.id, user_id=lucas.id, role="editor"),
            # No RH ele não entra.
            SpaceTable(space_id=financeiro.id, connection_id=erp.id, table_name="faturas"),
            SpaceTable(space_id=marketing.id, connection_id=erp.id, table_name="campanhas"),
            SpaceTable(space_id=rh.id, connection_id=erp.id, table_name="salarios"),
        ]
    )
    await db.flush()
    return {
        "lucas": lucas,
        "erp": erp,
        "financeiro": financeiro,
        "marketing": marketing,
        "rh": rh,
    }


# ── A união: exactamente o que ele alcança ───────────────────────────────────


@pytest.mark.asyncio
async def test_cruza_os_projetos_onde_esta(db_session, fronteira_no_projeto):
    """É o objectivo do modo: perguntar sobre Financeiro **e** Marketing de uma
    vez, sem ter de criar um projeto guarda-chuva."""
    e = await _empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, is_personal=True)
    assert visto == ["campanhas", "faturas"]


@pytest.mark.asyncio
async def test_o_que_nao_e_dele_fica_de_fora(db_session, fronteira_no_projeto):
    """Cruzar não é ganhar. O RH não é dele e continua a não ser."""
    e = await _empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, is_personal=True)
    assert "salarios" not in visto


# ── S10: nunca em cache ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sair_de_um_projeto_tira_o_da_uniao_ja_a_seguir(db_session, fronteira_no_projeto):
    """Se a união ficasse em cache, quem saísse de um projeto continuava a
    cruzá-lo até à sessão seguinte — e "até à sessão seguinte" é tempo a mais
    para uma pessoa que acabou de sair de uma equipa."""
    e = await _empresa(db_session)
    svc = PermissionService(db_session)

    antes = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, is_personal=True)
    assert "campanhas" in antes

    linha = (
        await db_session.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == e["marketing"].id,
                SpaceMember.user_id == e["lucas"].id,
            )
        )
    ).scalar_one()
    await db_session.delete(linha)
    await db_session.flush()

    depois = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, is_personal=True)
    assert "campanhas" not in depois
    assert "faturas" in depois


# ── S11: a marca aplica-se ao construir a união ──────────────────────────────


@pytest.mark.asyncio
async def test_fonte_marcada_nao_entra_no_cruzamento(db_session, fronteira_no_projeto):
    """A ligação marcada sai da união **antes** de qualquer query.

    Se a exclusão fosse feita no ecrã, o dado já teria sido lido, cruzado e
    resumido pelo modelo — esconder o resultado nessa altura não é segurança.
    """
    e = await _empresa(db_session)
    e["erp"].nao_cruzavel = True
    await db_session.flush()

    svc = PermissionService(db_session)
    visto = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, is_personal=True)
    assert visto == []


@pytest.mark.asyncio
async def test_a_marca_nao_afecta_o_projeto(db_session, fronteira_no_projeto):
    """Marcar como não cruzável tira do **cruzamento**, não do projeto.

    Quem trabalha no RH continua a ver os salários dentro do RH — senão a marca
    deixava de ser um travão ao cruzamento e passava a ser uma revogação.
    """
    e = await _empresa(db_session)
    e["erp"].nao_cruzavel = True
    db_session.add(
        SpaceMember(id=uuid.uuid4(), space_id=e["rh"].id, user_id=e["lucas"].id, role="viewer")
    )
    await db_session.flush()

    svc = PermissionService(db_session)
    dentro = await svc.get_authorized_tables(e["lucas"].id, e["erp"].id, space_id=e["rh"].id)
    assert dentro == ["salarios"]


# ── S9: o travão na saída ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uma_resposta_cruzada_nao_se_fixa(db_session):
    """O coração da opção C.

    Sem este travão, C é apenas B com mais texto: a pessoa cruza RH com Vendas
    e publica o resultado no projeto onde ninguém aprovou a combinação.
    """
    from src.services.message_service import MessageService

    class _MsgFalsa:
        role = "assistant"
        cruzou_projetos = True
        conversation_id = uuid.uuid4()
        pinned_widget_id = None
        id = uuid.uuid4()

    svc = MessageService(db_session)

    async def _repo_get(_id):
        return _MsgFalsa()

    async def _conversa_visivel(_conv_id, _user):
        """A verificação de acesso à conversa corre **antes** da nossa, e é a
        ordem certa: ninguém deve aprender nada sobre uma mensagem que não pode
        ver. Aqui damo-la por passada para isolar o travão do cruzamento."""
        return object()

    svc.repo.get_by_id = _repo_get  # type: ignore[assignment]
    svc._load_viewable_conversation = _conversa_visivel  # type: ignore[assignment]

    with pytest.raises(BadRequestError) as caiu:
        await svc.pin_message(_MsgFalsa.id, _pessoa("Lucas"), None)

    # A mensagem diz o caminho de saída, não só "não".
    assert "cruzou" in str(caiu.value).lower()
    assert "projeto" in str(caiu.value).lower()
