# -*- coding: utf-8 -*-
"""Um pedido novo avisa alguém — sem quebrar o portão de privacidade.

── O que o Lucas disse ─────────────────────────────────────────────

> «eu tenho que fazer alguma coisa com os alertas. Eles vão ficar ali e
>  pronto? Como é que eu recebo eles? imagina um cliente envia alguma
>  coisa lá e eu não respondo ele em minutos?» — 05/10/2026

── E o que ele tinha dito antes ────────────────────────────────────

O `create` não notificava ninguém, e isso estava escrito no código como
decisão dele, de 29/04/2026:

    # Privacy gate (Lucas's 2026-04-29 demo review): ticket creation
    # NEVER posts to a Sky-managed Slack channel.

As duas coisas são verdadeiras ao mesmo tempo: o conteúdo não pode sair
do cliente, e alguém tem de saber que o pedido existe.

── A separação ─────────────────────────────────────────────────────

**Para quem gere o cliente:** email com o pedido completo. São os dados
dele, na caixa dele.

**Para a SKY:** um aviso sem conteúdo nenhum — cliente, categoria,
gravidade, identificador. Chega para saber que existe e em quanto tempo
é preciso lá ir. Para o ler continua a ser preciso escalar.

É este segundo que estes testes guardam. Se um dia alguém acrescentar o
`subject` «só para dar contexto», o portão cai sem ninguém dar por isso.
"""

from __future__ import annotations

import inspect

import pytest


def test_o_aviso_a_sky_nao_leva_conteudo():
    """O guarda principal.

    Verificado na fonte porque o que interessa é o que **não** está lá,
    e um teste de integração só prova a ausência dos campos que alguém
    se lembrou de verificar.
    """
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_a_sky_sem_conteudo)
    corpo = fonte.split('"""')[-1]
    for campo in ("subject", "body", "context", "reporter", "email"):
        assert f"ticket.{campo}" not in corpo, (
            f"o aviso à SKY passou a levar `{campo}` — o portão de "
            "privacidade de 29/04/2026 caiu"
        )


def test_o_aviso_a_sky_leva_o_que_precisa():
    """O contrapeso: um aviso vazio também não serve.

    Sem o cliente e a categoria, quem o recebe não sabe onde ir nem com
    que urgência — e um alerta que não diz nada é ignorado ao fim de
    dois dias.
    """
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_a_sky_sem_conteudo)
    for campo in ("cliente", "categoria", "gravidade", "ticket_id"):
        assert f'"{campo}"' in fonte


def test_sem_webhook_configurado_nao_se_tenta_nada():
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_a_sky_sem_conteudo)
    assert "if not url:" in fonte
    assert "return" in fonte


def test_o_email_ao_cliente_leva_o_pedido_inteiro():
    """O outro lado: a quem gere o cliente não se esconde nada.

    O portão existe para o conteúdo não chegar à SKY, não para o
    esconder de quem o recebeu.
    """
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_quem_gere_o_cliente)
    assert "ticket.subject" in fonte
    assert "ticket.body" in fonte
    assert "reporter.email" in fonte


def test_o_email_vai_so_para_quem_gere():
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_quem_gere_o_cliente)
    assert '"owner", "admin", "super_admin"' in fonte
    # Contas apagadas não recebem.
    assert "deleted_at.is_(None)" in fonte


def test_um_destinatario_morto_nao_cala_os_outros():
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service._avisar_quem_gere_o_cliente)
    # O try/except está DENTRO do laço, não à volta dele.
    indice_laco = fonte.index("for email in destinatarios:")
    assert "try:" in fonte[indice_laco:]


def test_um_aviso_que_falha_nao_perde_o_pedido():
    """O pedido já está gravado quando os avisos correm.

    Se o SMTP estiver em baixo, quem escreveu não pode receber um erro:
    fez a parte dele e o pedido existe.
    """
    from src.services import ticket_service

    fonte = inspect.getsource(ticket_service.TicketService.create)
    indice = fonte.index("_avisar_quem_gere_o_cliente")
    depois = fonte[indice:]
    assert "except Exception" in depois
    assert "return TicketResponse" in depois


@pytest.mark.parametrize(
    "categoria,esperado",
    [
        ("bug", "Avaria reportada"),
        ("feature_request", "Sugestão de funcionalidade"),
        ("other", "Comentário"),
        ("qualquer_coisa", "Novo pedido"),
    ],
)
def test_o_assunto_do_email_diz_do_que_se_trata(categoria: str, esperado: str):
    # «[Sky] Ticket» numa caixa de entrada é indistinguível de ruído.
    from src.services.ticket_service import _assunto_por_categoria

    assert _assunto_por_categoria(categoria) == esperado
