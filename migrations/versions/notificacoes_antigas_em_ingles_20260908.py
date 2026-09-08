"""Traduzir as notificacoes que ficaram gravadas em ingles.

O Lucas abriu as notificacoes na app, em portugues, e leu:

    «Vendas do dia found 1 new insight»                 — 22 de Agosto

O mecanismo esta certo desde entao: o worker grava uma **chave**
(``title_key``) e os seus valores (``title_params``), e a app monta a
frase na lingua de quem le. Uma notificacao pode ser vista por pessoas
com linguas diferentes — ja acontece numa equipa com um portugues e um
brasileiro — e escolher a lingua no momento em que se grava e escolhe-la
no momento errado.

Mas as linhas gravadas **antes** dessa correccao so tem o ``title``, em
ingles. A app faz o que deve: sem chave, mostra o texto que la esta.
Portanto ficam em ingles para sempre, a espera de que alguem repare.

Esta migracao le esse texto e recupera a chave que ele ja implica.

── Porque e seguro ─────────────────────────────────────────────────

Toca so em linhas que ao mesmo tempo:

* nao tem ``title_key`` — as novas ja o tem, e nao se lhes mexe;
* batem certo com o padrao exacto que o worker escrevia.

O ``title`` fica **como esta**. E a rede de seguranca para clientes
antigos que ainda leiam o texto em vez da chave, e apaga-lo trocava um
problema visivel por um ecra vazio.

Se o padrao nao bater, a linha nao e tocada. Uma notificacao em ingles e
melhor do que uma notificacao com o nome do agente errado.

Revision ID: notificacoes_antigas_20260908
Revises: apagar_e_editar_mensagem_20260826
Create Date: 2026-09-08
"""

from __future__ import annotations

import json
import re

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "notificacoes_antigas_20260908"
down_revision = "apagar_e_editar_mensagem_20260826"
branch_labels = None
depends_on = None


#: O que o worker escrevia, palavra por palavra::
#:
#:     f"{agent.name} found {n} new insight{'s' if n > 1 else ''}"
#:
#: O nome do agente e livre — pode ter espacos, acentos, e a palavra
#: «found». Por isso ancora-se no FIM: e o sufixo que e fixo, e o que
#: sobra a esquerda e o nome.
_PADRAO = re.compile(r"^(?P<agente>.+) found (?P<conta>\d+) new insights?$")


def upgrade() -> None:
    ligacao = op.get_bind()

    linhas = ligacao.execute(
        sa.text(
            """
            SELECT id, title
              FROM notifications
             WHERE title_key IS NULL
               AND title LIKE '%% found %% new insight%%'
            """
        )
    ).fetchall()

    convertidas = 0
    for linha in linhas:
        m = _PADRAO.match((linha.title or "").strip())
        if not m:
            # Nao bate certo: deixa-se como esta. Ver a nota la em cima.
            continue

        ligacao.execute(
            sa.text(
                """
                UPDATE notifications
                   SET title_key = :chave,
                       title_params = CAST(:valores AS JSON)
                 WHERE id = :id
                """
            ),
            {
                "chave": "notif_agent_findings_title",
                "valores": json.dumps(
                    {"agent": m.group("agente"), "count": int(m.group("conta"))}
                ),
                "id": linha.id,
            },
        )
        convertidas += 1

    print(
        f"notificacoes: {convertidas} de {len(linhas)} passaram a ter chave de "
        f"traducao; as restantes nao batiam certo com o padrao e ficaram como "
        f"estavam."
    )


def downgrade() -> None:
    """Tira a chave as linhas que esta migracao converteu.

    Nao se distingue uma linha convertida de uma escrita ja com chave —
    e por isso **nao se apaga nada**. Reverter aqui significaria apagar a
    chave de notificacoes novas, que ficariam sem forma de ser
    traduzidas.

    O `title` nunca foi tocado, portanto voltar atras nao perde nada: as
    linhas antigas continuam a ter o texto ingles que sempre tiveram.
    """
