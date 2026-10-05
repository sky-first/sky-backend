# -*- coding: utf-8 -*-
"""Transforma um `Sector` em linhas na base de um cliente.

O que fica criado, por sector:

    Projecto (Space)
      └── Equipa "General" (Crew)
            ├── N ligações a `skydemo`, uma por esquema
            ├── 4 páginas, cada uma com os seus widgets já preenchidos
            └── 5 agentes, apontados às ligações

── Idempotente por construção ──────────────────────────────────────

Todos os identificadores são `uuid5` derivados do nome do sector e do
nome da peça. Correr duas vezes actualiza as mesmas linhas em vez de
criar um segundo projecto com o mesmo nome — que é o que acontece com
semeadores que procuram por nome e falham quando alguém renomeia.

Também é o que torna possível corrigir um widget e voltar a correr sem
limpar nada à mão.

── Os widgets vêm preenchidos; os agentes não ─────────────────────

O SQL dos widgets corre aqui, contra `skydemo`, e o resultado fica
gravado. O painel abre instantâneo.

Os agentes ficam apontados às ligações e correm ao vivo. É a diferença
que se está a demonstrar, e por isso não se pré-calcula.

── A base de destino é confirmada antes de se escrever ─────────────

Semear no sítio errado é pior do que não semear: fica lá, parece certo,
e ninguém dá por isso. O `--confirmar-base` existe para o chamador ter
de dizer em voz alta qual é a base, e o motor recusa se não bater certo
com o `DATABASE_URL`.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm.attributes import flag_modified

from scripts.demo_sectorial.pecas import Sector
from src.models.agent import Agent
from src.models.connection import DataConnection
from src.models.conversation import Conversation, Message
from src.models.crew import Crew, CrewConnection, CrewMember
from src.models.page import Page
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.space_crew import SpaceCrew
from src.models.user import User
from src.models.widget import Widget as WidgetRow
from src.utils.encryption import encrypt_dict

# Espaço de nomes fixo. Mudá-lo cria um segundo projecto em vez de
# actualizar o primeiro — por isso não se muda.
NS = uuid.UUID("b7a1f3c2-5d64-4e18-9a0b-2c6f8e4d1a97")


def _id(*partes: str) -> uuid.UUID:
    return uuid.uuid5(NS, "|".join(partes))


class SementeiraRecusada(RuntimeError):
    """Parou antes de escrever. A mensagem diz porquê."""


# ── a base sintética ────────────────────────────────────────────────


def _dsn_da_demo() -> str:
    host = os.environ.get("DEMO_PG_HOST", "")
    user = os.environ.get("DEMO_PG_USER", "")
    pwd = os.environ.get("DEMO_PG_PASSWORD", "")
    if not (host and user and pwd):
        raise SementeiraRecusada(
            "faltam DEMO_PG_HOST / DEMO_PG_USER / DEMO_PG_PASSWORD — "
            "são a base sintética de onde saem os números dos painéis."
        )
    porta = os.environ.get("DEMO_PG_PORT", "5432")
    base = os.environ.get("DEMO_PG_DB", "skydemo")
    ssl = os.environ.get("DEMO_PG_SSL_MODE", "require")
    return (
        f"postgresql+asyncpg://{user}:{pwd}@{host}:{porta}/{base}"
        f"?ssl={'require' if ssl != 'disable' else 'disable'}"
    )


def _config_da_ligacao(esquema: str) -> dict:
    return {
        "host": os.environ.get("DEMO_PG_HOST", ""),
        "port": int(os.environ.get("DEMO_PG_PORT", "5432")),
        "database": os.environ.get("DEMO_PG_DB", "skydemo"),
        "username": os.environ.get("DEMO_PG_USER", ""),
        "password": os.environ.get("DEMO_PG_PASSWORD", ""),
        "schema": esquema,
        "ssl_mode": os.environ.get("DEMO_PG_SSL_MODE", "require"),
    }


def _converter(v):
    """Um valor do Postgres no tipo que o JSON do widget precisa.

    `Decimal` e `date` não são serializáveis, e um número guardado como
    texto faz o gráfico desistir sem dizer nada.

    O `float` entra na mesma conta, e não por simetria: `ROUND()` sobre
    um `bigint` devolve `double precision`, não `numeric`, portanto não
    tem `quantize` e escapava por aqui. A coluna "Km" de um quadro saía
    `69830.0` — não está errada, e fica mal num ecrã que o cliente lê.

    O booleano vem primeiro porque em Python `True == 1` e `isinstance(
    True, int)` é verdadeiro: sem o atalho, um `TRUE` chegava ao widget
    como `1`.
    """
    if v is None or isinstance(v, bool):
        return v
    if hasattr(v, "quantize") or isinstance(v, float):
        f = float(v)
        return int(f) if f.is_integer() else round(f, 3)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def _linhas(motor, sql: str) -> list[dict]:
    async with motor.connect() as c:
        res = await c.execute(text(sql))
        colunas = list(res.keys())
        return [{k: _converter(v) for k, v in zip(colunas, linha)} for linha in res.fetchall()]


# ── o dono ──────────────────────────────────────────────────────────


async def _dono(db: AsyncSession, email: Optional[str]) -> User:
    if email:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            raise SementeiraRecusada(
                f"não há nenhum utilizador {email!r} nesta base. "
                "Numa base de cliente o dono é alguém dessa equipa."
            )
        return u

    u = (
        (await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.created_at)))
        .scalars()
        .first()
    )
    if u is None:
        raise SementeiraRecusada("esta base não tem utilizadores — base errada?")
    return u


# ── a sementeira ────────────────────────────────────────────────────


async def semear(
    db: AsyncSession,
    sector: Sector,
    *,
    email_do_dono: Optional[str] = None,
    relatar=print,
) -> dict[str, Any]:
    dono = await _dono(db, email_do_dono)
    relatar(f"dono: {dono.email}")

    espaco_id = _id(sector.chave, "space")
    espaco = await db.get(Space, espaco_id)
    if espaco is None:
        espaco = Space(
            id=espaco_id,
            name=sector.nome_do_projecto,
            description=sector.descricao,
            created_by=dono.id,
            privacy="private",
            sensitivity="internal",
            is_demo=True,
        )
        db.add(espaco)
        relatar(f"projecto criado: {sector.nome_do_projecto!r}")
    else:
        espaco.name = sector.nome_do_projecto
        espaco.description = sector.descricao
        espaco.deleted_at = None
        relatar(f"projecto actualizado: {sector.nome_do_projecto!r}")
    await db.flush()

    if not await db.get(SpaceMember, _id(sector.chave, "space_member")):
        db.add(
            SpaceMember(
                id=_id(sector.chave, "space_member"),
                space_id=espaco.id,
                user_id=dono.id,
                role="owner",
            )
        )

    # A equipa. Ninguém fica sem equipa — é o modelo decidido, e sem ela
    # o projecto abre sem dados visíveis.
    equipa_id = _id(sector.chave, "crew")
    equipa = await db.get(Crew, equipa_id)
    if equipa is None:
        equipa = Crew(
            id=equipa_id,
            name="General",
            description="Equipa por omissão do projecto de demonstração.",
            space_id=espaco.id,
            created_by=dono.id,
        )
        db.add(equipa)
        relatar("equipa 'General' criada")
    else:
        equipa.deleted_at = None
    await db.flush()

    if not await db.get(SpaceCrew, _id(sector.chave, "space_crew")):
        db.add(
            SpaceCrew(
                id=_id(sector.chave, "space_crew"),
                space_id=espaco.id,
                crew_id=equipa.id,
                role="editor",
                added_by=dono.id,
            )
        )
    if not await db.get(CrewMember, _id(sector.chave, "crew_member")):
        db.add(
            CrewMember(
                id=_id(sector.chave, "crew_member"),
                crew_id=equipa.id,
                user_id=dono.id,
                role="owner",
            )
        )
    await db.flush()

    # ── as ligações ─────────────────────────────────────────────────
    ligacoes: dict[str, DataConnection] = {}
    for sufixo, (nome, esquema, descricao) in sector.ligacoes.items():
        lid = _id(sector.chave, "conn", sufixo)
        conn = await db.get(DataConnection, lid)
        cfg = encrypt_dict(_config_da_ligacao(esquema))
        if conn is None:
            conn = DataConnection(
                id=lid,
                name=nome,
                connector_id="postgresql",
                description=descricao,
                status="active",
                config=cfg,
                created_by=dono.id,
                tier="internal",
            )
            db.add(conn)
            relatar(f"  ligação {nome!r} → esquema {esquema}")
        else:
            conn.name = nome
            conn.description = descricao
            conn.config = cfg
            conn.status = "active"
            conn.deleted_at = None
        await db.flush()
        ligacoes[sufixo] = conn

        # Chave primária composta nestas duas — não têm `id`, por isso o
        # `db.get` leva o par e não um uuid5.
        if not await db.get(SpaceConnection, (espaco.id, conn.id)):
            db.add(SpaceConnection(space_id=espaco.id, connection_id=conn.id))
        if not await db.get(CrewConnection, (equipa.id, conn.id)):
            db.add(CrewConnection(crew_id=equipa.id, connection_id=conn.id))
    await db.flush()

    # ── as páginas ──────────────────────────────────────────────────
    motor_demo = create_async_engine(_dsn_da_demo(), pool_pre_ping=True)
    try:
        n_widgets = 0
        for indice, pagina in enumerate(sector.paginas):
            pid = _id(sector.chave, "page", pagina.nome)
            pag = await db.get(Page, pid)
            if pag is None:
                pag = Page(
                    id=pid,
                    name=pagina.nome,
                    description=pagina.descricao,
                    type="team",
                    color=pagina.cor,
                    icon=pagina.icone,
                    owner_id=dono.id,
                    crew_id=equipa.id,
                    space_id=espaco.id,
                    is_active=(indice == 0),
                )
                db.add(pag)
            else:
                pag.name = pagina.nome
                pag.description = pagina.descricao
                pag.color = pagina.cor
                pag.icon = pagina.icone
                pag.deleted_at = None
            await db.flush()

            for w in pagina.widgets:
                conn = ligacoes[w.esquema]
                linhas = await _linhas(motor_demo, w.sql)
                if not linhas:
                    raise SementeiraRecusada(
                        f"{pagina.nome} / {w.titulo}: a consulta não devolveu "
                        "nenhuma linha. Um widget vazio num painel de "
                        "demonstração é pior do que um painel com menos um "
                        "widget — recusa-se a gravar."
                    )
                wid = _id(sector.chave, "widget", pagina.nome, w.titulo)
                pos, tam = w.geometria()
                linha = await db.get(WidgetRow, wid)
                dados = w.dados(linhas)
                if linha is None:
                    linha = WidgetRow(
                        id=wid,
                        page_id=pag.id,
                        type=w.tipo,
                        title=w.titulo,
                        position=pos,
                        size=tam,
                        data=dados,
                        config=w.config or {},
                        connection_id=conn.id,
                        created_by=dono.id,
                        source="demo_sectorial",
                    )
                    db.add(linha)
                else:
                    linha.page_id = pag.id
                    linha.type = w.tipo
                    linha.title = w.titulo
                    linha.position = pos
                    linha.size = tam
                    linha.data = dados
                    linha.config = w.config or {}
                    linha.connection_id = conn.id
                    # ⚠️ Sem isto, uma correcção aos dados pode nunca
                    # chegar à base.
                    #
                    # O SQLAlchemy decide se emite UPDATE comparando o
                    # valor novo com o antigo, e em Python
                    # `{"Km": 69830} == {"Km": 69830.0}` é **True**.
                    # Foi exactamente o caso: a conversão de `double`
                    # para inteiro foi corrigida, o semeador voltou a
                    # correr, disse "gravado", e o `.0` continuou lá —
                    # porque o dicionário novo comparava igual ao velho.
                    #
                    # Vale para qualquer alteração que mexa só no TIPO de
                    # um número, que é a mais fácil de dar por certa sem
                    # olhar. `flag_modified` tira a decisão da comparação.
                    flag_modified(linha, "data")
                n_widgets += 1
            relatar(f"  página {pagina.nome!r}: {len(pagina.widgets)} widgets")
            await db.flush()
    finally:
        await motor_demo.dispose()

    # ── os agentes ──────────────────────────────────────────────────
    #
    # As tabelas que cada agente declara têm de existir mesmo. O teste
    # unitário confirma que pertencem ao esquema certo; só aqui, contra
    # a base, se apanha um nome mal escrito — e um agente apontado a uma
    # tabela que não existe não rebenta: responde que não encontrou
    # dados, ao vivo, à frente do cliente.
    async with create_async_engine(_dsn_da_demo()).connect() as c:
        existentes = {
            f"{e}.{t}"
            for e, t in (
                await c.execute(
                    text("SELECT table_schema, table_name FROM information_schema.tables")
                )
            ).fetchall()
        }
    em_falta = {
        f"{ag.nome}: {t}" for ag in sector.agentes for t in ag.tabelas if t not in existentes
    }
    if em_falta:
        raise SementeiraRecusada(
            "tabelas declaradas que não existem na base sintética:\n  "
            + "\n  ".join(sorted(em_falta))
        )

    for ag in sector.agentes:
        aid = _id(sector.chave, "agent", ag.nome)
        conn = ligacoes[ag.esquema]
        linha = await db.get(Agent, aid)
        campos = dict(
            name=ag.nome,
            archetype=ag.arquetipo,
            scope="crew",
            scope_id=str(equipa.id),
            scope_name=equipa.name,
            status="active",
            monitor_type="sql" if ag.sql else "question",
            focus=ag.foco,
            custom_sql=ag.sql,
            frequency=ag.frequencia,
            depth="standard",
            connection_ids=[conn.id],
            created_by=dono.id,
        )
        if linha is None:
            db.add(Agent(id=aid, **campos))
        else:
            for k, v in campos.items():
                setattr(linha, k, v)
    relatar(f"  {len(sector.agentes)} agentes")
    await db.flush()

    # ── as perguntas ────────────────────────────────────────────────
    #
    # Cada uma é um fio: a pergunta como mensagem do utilizador e a
    # resposta como mensagem do assistente. A resposta é calculada agora,
    # a partir da mesma consulta que a aplicação volta a correr se
    # alguém perguntar outra vez — ver a nota em `pecas.Pergunta`.
    #
    # Ficam penduradas na primeira página do sector. Uma conversa sem
    # `page_id` existe mas não se abre de lado nenhum: o ecrã lista as
    # conversas de uma página, e um fio órfão seria trabalho feito que
    # ninguém vê.
    n_perguntas = 0
    if sector.perguntas:
        # Uma página declarada que não existe põe o fio num espaço de
        # nomes que ninguém abre — e o `uuid5` não se queixa, gera um
        # identificador perfeitamente válido para uma página inexistente.
        nomes_das_paginas = {pg.nome for pg in sector.paginas}
        enganos = {
            pq.pagina for pq in sector.perguntas if pq.pagina and pq.pagina not in nomes_das_paginas
        }
        if enganos:
            raise SementeiraRecusada(
                "perguntas apontadas a páginas que não existem: " + ", ".join(sorted(enganos))
            )
        primeira = sector.paginas[0].nome
        motor_demo = create_async_engine(_dsn_da_demo(), pool_pre_ping=True)
        try:
            for pq in sector.perguntas:
                linhas = await _linhas(motor_demo, pq.sql)
                texto_da_resposta = pq.resposta(linhas)
                cid = _id(sector.chave, "conv", pq.texto)
                conv = await db.get(Conversation, cid)
                if conv is None:
                    conv = Conversation(
                        id=cid,
                        page_id=_id(sector.chave, "page", pq.pagina or primeira),
                        space_id=espaco.id,
                        crew_id=equipa.id,
                        title=pq.texto,
                        created_by=dono.id,
                    )
                    db.add(conv)
                else:
                    conv.title = pq.texto
                    # ⚠️ A página também, e não só o título.
                    #
                    # Sem esta linha, a segunda passagem encontrava o fio
                    # pelo `uuid5(sector, "conv", texto)` e deixava-o onde
                    # estava. Mudei as perguntas de página, voltei a
                    # semear, e as cinco continuaram todas na primeira —
                    # com o semeador a dizer «gravado» e a não gravar
                    # isto.
                    conv.page_id = _id(sector.chave, "page", pq.pagina or primeira)
                await db.flush()

                # Duas mensagens com identificadores derivados, para a
                # segunda passagem actualizar em vez de acrescentar um
                # par novo ao mesmo fio.
                for papel, conteudo in (
                    ("user", pq.texto),
                    ("assistant", texto_da_resposta),
                ):
                    mid = _id(sector.chave, "msg", pq.texto, papel)
                    msg = await db.get(Message, mid)
                    if msg is None:
                        db.add(
                            Message(
                                id=mid,
                                conversation_id=cid,
                                role=papel,
                                content=conteudo,
                                user_id=dono.id if papel == "user" else None,
                                # `ck_messages_origin` só aceita `text`
                                # ou `voice`. O `"chat"` que aqui estava
                                # primeiro passava no Python e morria na
                                # base — e numa transacção que já tinha
                                # feito metade do trabalho.
                                origin="text",
                            )
                        )
                    else:
                        msg.content = conteudo
                n_perguntas += 1
            await db.flush()
        finally:
            await motor_demo.dispose()
        relatar(f"  {n_perguntas} perguntas respondidas")

    return {
        "ligacoes_criadas": [str(c.id) for c in ligacoes.values()],
        "espaco_id": str(espaco.id),
        "equipa_id": str(equipa.id),
        "ligacoes": len(ligacoes),
        "paginas": len(sector.paginas),
        "widgets": n_widgets,
        "agentes": len(sector.agentes),
        "perguntas": n_perguntas,
    }


async def sincronizar_metadados(
    ids: list[str], url: str, email_do_dono: Optional[str] = None
) -> int:
    """Introspecciona cada ligação e grava as tabelas e colunas.

    ── Sem isto o projecto parece completo e não responde ───────────

    Os widgets nascem preenchidos — os números são calculados aqui e
    gravados — por isso um projecto sem metadados abre bonito. O que não
    funciona é tudo o que é ao vivo: a conversa e os agentes.

    O `sky-ai` responde `404` ao `/connections/<id>/query` quando não
    encontra metadados, e o backend traduz esse 404 — que não é 400, nem
    429, nem 5xx — em «The AI service rejected the request». A mensagem
    não tem nada a ver com a causa, e manda procurar um defeito no
    serviço de IA que está bom.

    Aconteceu em produção a 03/10/2026, à frente do Lucas, com os três
    projectos acabados de semear. O `seed_demo_connections.py` já tinha
    este passo e o aviso escrito por cima dele; o meu semeador não o
    copiou.

    ── Sessão nova, de propósito ───────────────────────────────────

    A introspecção tem de correr contra linhas **já gravadas**. Na
    sessão do semeador as ligações ainda estão por confirmar, e o
    serviço lê-as de volta da base.

    ── ⚠️ `url` é obrigatório, e foi por faltar que isto falhou ────

    A primeira versão abria a sessão com o `AsyncSessionLocal`, que vem
    do `DATABASE_URL` — **a base da plataforma**. As ligações vivem na
    base do cliente. Em produção deu, nas três:

        AVISO: metadados por sincronizar em 611b5fb0…: Connection not found
        metadados: 0/3 ligações

    Em local tinha passado, e passou por acidente: aí o `DATABASE_URL`
    aponta directamente para a base do cliente, por isso as duas eram a
    mesma coisa. O caminho com `TENANT_SLUG` — que é o do Job — nunca
    chegou a ser exercido antes de chegar lá.

    Agora recebe o URL que o semeador usou. Não tem valor por omissão:
    um `AsyncSessionLocal` em segundo plano é precisamente como este
    defeito entrou, e a chamada tem de dizer onde escreve.

    Devolve quantas sincronizaram. Uma que falhe não derruba as outras:
    ficar com duas ligações boas e uma por sincronizar é melhor do que
    ficar com zero.
    """
    if not ids:
        return 0

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.services.connection_service import ConnectionService

    feitas = 0
    motor_do_cliente = create_async_engine(url, pool_pre_ping=True)
    try:
        sessao = async_sessionmaker(motor_do_cliente, expire_on_commit=False)
        async with sessao() as db:
            dono = await _dono(db, email_do_dono)
            servico = ConnectionService(db)
            for cid in ids:
                try:
                    await servico.sync_connection(uuid.UUID(cid), dono)
                    feitas += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  AVISO: metadados por sincronizar em {cid}: {exc}")
    finally:
        await motor_do_cliente.dispose()
    return feitas
