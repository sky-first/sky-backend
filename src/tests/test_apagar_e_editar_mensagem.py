"""Apagar e editar uma mensagem.

> *"Não dá para apagar uma mensagem (perguntou no projeto errado)."*
> *"Não dá para editar e reenviar (erro de escrita)."* — Lucas, 4.3 e 4.4

**A razão importa, e muda o desenho.** O Lucas não quer apagar por vergonha
de uma pergunta: quer apagar porque perguntou **no projeto errado**. E uma
pergunta feita no projeto errado traz uma resposta com dados desse projeto —
por isso apagar a pergunta tem de levar a resposta atrás. Apagar só a
pergunta era deixar exactamente o que interessa tirar.

O mesmo vale para editar: se a pergunta muda, a resposta que estava lá deixou
de ser resposta àquilo, e deixá-la é pior do que não ter nenhuma — porque
parece que é.

Provado contra a base a 26/08, em oito passos.
"""

import inspect

from src.models.conversation import Message
from src.repositories.message import MessageRepository
from src.services.message_service import MessageService


def test_a_mensagem_sabe_ser_apagada_e_editada():
    """Sem as colunas, tudo o resto aqui é decoração."""
    colunas = Message.__table__.c
    assert "deleted_at" in colunas
    assert "edited_at" in colunas


def test_apagar_e_MARCAR_e_nao_remover():
    """Uma resposta aponta para a pergunta; apagar a linha parte o fio.

    E há reacções, fixações e widgets pendurados nas mensagens. Marcar
    tira-a de todas as vistas e deixa o histórico para quem o tiver de
    auditar.
    """
    fonte = inspect.getsource(MessageService.apagar)
    assert "deleted_at = agora" in fonte
    assert "db.delete" not in fonte


def test_apagar_uma_pergunta_LEVA_A_RESPOSTA():
    """**O ponto todo.**

    Se ficasse só a pergunta apagada, a resposta com os dados do projeto
    errado continuava no ecrã — que é o que se estava a tentar tirar.
    """
    fonte = inspect.getsource(MessageService.apagar)
    assert "Message.parent_message_id == msg.id" in fonte
    assert "filha.deleted_at = agora" in fonte


def test_editar_TAMBEM_leva_a_resposta():
    """A resposta antiga já não responde à pergunta nova."""
    fonte = inspect.getsource(MessageService.editar)
    assert "Message.parent_message_id == msg.id" in fonte
    assert "filha.deleted_at = agora" in fonte


def test_editar_marca_que_foi_editada():
    """Uma mensagem que muda sem o dizer é pior do que uma com um erro.

    Numa conversa partilhada, alguém respondeu à versão anterior.
    """
    assert "edited_at = agora" in inspect.getsource(MessageService.editar)


def test_so_quem_escreveu():
    """**Nem o dono do projeto.**

    São palavras de outra pessoa, e um dono que possa reescrever a conversa
    alheia transforma o histórico em algo que não se pode acreditar. Quem
    tem de tirar alguém tira-lhe o acesso, não as frases.
    """
    fonte = inspect.getsource(MessageService._minha_mensagem)
    assert "msg.user_id != user.id" in fonte
    # E não há porta de administrador nenhuma neste caminho.
    assert "is_tenant_admin" not in fonte


def test_a_quem_nao_e_dela_diz_404_e_nao_403():
    """Um 403 confirmava que a mensagem existe.

    Com um identificador ao calhas, isso é informação.
    """
    fonte = inspect.getsource(MessageService._minha_mensagem)
    i = fonte.index("msg.user_id != user.id")
    assert "NotFoundError" in fonte[i : i + 200]
    assert "ForbiddenError" not in fonte


def test_quem_perdeu_o_acesso_a_conversa_nao_mexe_la_dentro():
    """Ser o autor não chega: tem de continuar a poder ver a conversa."""
    assert "_load_viewable_conversation" in inspect.getsource(MessageService._minha_mensagem)


def test_nao_se_edita_a_resposta_da_IA():
    """Seria pôr palavras na boca da máquina e guardá-las como se fossem dela."""
    fonte = inspect.getsource(MessageService.editar)
    assert 'msg.role != "user"' in fonte


def test_nao_se_edita_para_vazio():
    """Uma mensagem vazia é uma mensagem apagada a fingir que não é."""
    assert "A message cannot be empty." in inspect.getsource(MessageService.editar)


def test_apagada_nao_aparece_em_NENHUMA_consulta():
    """**Quatro consultas leem mensagens de uma conversa.**

    Deixar uma de fora fazia a mensagem apagada reaparecer num sítio — e o
    pior sítio de todos seria o contexto que vai à IA, onde a pergunta feita
    no projeto errado voltaria a entrar no prompt depois de apagada.
    """
    fonte = inspect.getsource(MessageRepository)
    assert fonte.count("deleted_at.is_(None)") >= 4, (
        "alguma consulta de mensagens deixou de excluir as apagadas"
    )


def test_o_contexto_da_IA_e_uma_delas():
    """O caso nomeado, para não se perder na contagem acima."""
    fonte = inspect.getsource(MessageRepository.list_up_to)
    assert "deleted_at.is_(None)" in fonte
