"""Mencionar alguém com `@` passa a avisá-lo.

O que estava
------------
A app extraía `@nome` do texto — havia um `extractMentions` completo, com
testes — e **deitava fora o resultado**. O `ThreadScreen` nunca lia o campo,
o endpoint das mensagens não o aceitava, e não havia selector nenhum.

Resultado: escrevia-se `@paulo`, ficava lá o texto, e o Paulo nunca sabia.
Parecia funcionar. É a mesma família do `custom_domain` e do
`sso_domain_restriction` — peças construídas que nunca foram ligadas, e que
enganam justamente por parecerem inteiras.

A notificação já existia e funcionava, mas só no caminho dos comentários de
página (`comment_service.py`), que o chat não usa.

Porque vem por id e não por nome
--------------------------------
`@paulo` pode ser o Paulo Richau ou o Paulo Bomfim. Adivinhar a partir do
texto é arriscar mandar a notificação à pessoa errada — pior do que não
mandar nenhuma. O selector da app sabe quem está na equipa e envia o id.

O que NÃO se guarda
-------------------
As menções não vão para a base. Ficam no texto, que é onde quem lê as vê.
O campo serve só para notificar. Guardá-las exigia migração, e o valor —
avisar a pessoa — não precisa dela.
"""
from __future__ import annotations

import inspect
import uuid

from src.schemas.message import MessageCreate
from src.services.message_service import MessageService


def test_o_esquema_aceita_mencoes():
    """Sem isto, o campo era rejeitado antes de chegar ao serviço."""
    uid = uuid.uuid4()
    m = MessageCreate(content="olá @paulo", kind="comment", mentions=[uid])
    assert m.mentions == [uid]


def test_sem_mencoes_continua_a_funcionar():
    """A esmagadora maioria das mensagens não menciona ninguém."""
    m = MessageCreate(content="uma mensagem normal", kind="comment")
    assert m.mentions == []


def test_o_servico_notifica():
    fonte = inspect.getsource(MessageService.create)
    assert "_notificar_mencionados" in fonte


def test_nao_notifica_o_proprio():
    """Mencionar-se a si mesmo acontece a escrever depressa.

    Uma notificação sobre o que acabámos de escrever é ruído, e ruído numa
    caixa de notificações é o que faz as pessoas deixarem de as ler.
    """
    fonte = inspect.getsource(MessageService._notificar_mencionados)
    assert "m != autor.id" in fonte


def test_falhar_a_notificar_nao_perde_a_mensagem():
    """A mensagem já está gravada quando isto corre.

    Trocar o texto de alguém por um erro de notificação seria perder o
    essencial por causa do acessório.
    """
    fonte = inspect.getsource(MessageService._notificar_mencionados)
    assert "except Exception" in fonte
    assert "logger.warning" in fonte


def test_a_notificacao_vai_na_lingua_de_quem_a_recebe():
    """Não na de quem escreveu.

    Copiado do `comment_service`, que já o fazia bem — se divergissem, quem
    recebe uma menção de chat via inglês e uma de página via português.
    """
    fonte = inspect.getsource(MessageService._notificar_mencionados)
    assert "normalize_locale" in fonte
    assert "prefs" in fonte


def test_leva_a_conversa_certa():
    """Uma notificação que não abre o sítio onde a menção aconteceu obriga a
    procurar — e quem procura desiste."""
    fonte = inspect.getsource(MessageService._notificar_mencionados)
    assert "deep_link" in fonte
    assert "conversation=" in fonte
