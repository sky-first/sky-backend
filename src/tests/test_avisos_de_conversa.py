"""Quem participa numa conversa é avisado quando ela se mexe.

Escrito depois de percorrer os fluxos de três pessoas
(``docs/FLUXOS-TRES-PESSOAS.md``, fluxo 3). O buraco de maior dano que lá
encontrei não era de ecrã:

    A Sofia comenta a resposta do Rui. O Rui **nunca fica a saber**.

Só a menção explícita (``@nome``) notificava. Comentar a resposta de alguém não
avisava ninguém — e se essa pessoa tinha fechado a app, a observação morria ali.

E ao escrever isto encontrei uma segunda camada do mesmo problema: o
``_notificar_mencionados`` importava ``src.i18n.messages``, **um módulo que não
existe**. Todos os outros ficheiros importam de ``src.core.locale``. Como o
import vive dentro de um ``try/except`` que apenas regista um aviso, a menção
falhava em silêncio a cada uso — ou seja, **nunca funcionou**.

É por isso que o primeiro teste aqui parece trivial: ele existe precisamente
porque um import morto dentro de um `except` não se vê de outra maneira. Nem o
`tsc` equivalente, nem os testes de fluxo o apanhavam; só olhar para o módulo.
"""

import pytest

from src.core.locale import NOTIFICATION_KEYS, get_message
from src.models.notification import NotificationType


class TestAsMensagensExistem:
    """As chaves e o módulo de onde elas vêm.

    Um `get_message` importado do sítio errado explode dentro do `try` e o
    utilizador nunca recebe nada. Isto fixa o contrato.
    """

    def test_o_modulo_de_traducao_e_o_que_existe(self) -> None:
        import inspect

        import src.services.message_service as ms

        fonte = inspect.getsource(ms)
        assert "src.i18n.messages" not in fonte, (
            "src.i18n.messages não existe — o import vive dentro de um try/except "
            "e falha em silêncio, portanto nenhuma notificação é criada"
        )
        assert "from src.core.locale import get_message" in fonte

    @pytest.mark.parametrize("locale", ["pt", "en"])
    def test_o_titulo_diz_quem_escreveu_e_onde(self, locale: str) -> None:
        # Numa conversa de três pessoas, saber o autor decide se vale a pena
        # abrir agora. Um "alguém respondeu" obriga a abrir para descobrir.
        modelo = get_message("notif_conversation_reply_title", locale)
        assert "{autor}" in modelo
        assert "{conversa}" in modelo
        texto = modelo.format(autor="Sofia", conversa="Custo por canal")
        assert "Sofia" in texto and "Custo por canal" in texto

    @pytest.mark.parametrize("locale", ["pt", "en"])
    def test_a_descricao_leva_o_excerto(self, locale: str) -> None:
        modelo = get_message("notif_conversation_reply_desc", locale)
        assert "{snippet}" in modelo

    def test_as_chaves_estao_registadas(self) -> None:
        # Sem estar em NOTIFICATION_KEYS a notificação não é re-traduzida na
        # língua de quem lê — ficava congelada na língua de quem escreveu.
        assert "notif_conversation_reply_title" in NOTIFICATION_KEYS
        assert "notif_conversation_reply_desc" in NOTIFICATION_KEYS

    def test_o_tipo_e_distinto_da_mencao(self) -> None:
        # "Mencionaram-me" e "a conversa mexeu-se" são coisas diferentes: uma é
        # dirigida a mim, a outra é informação. Misturá-las tira à pessoa a
        # possibilidade de silenciar uma e manter a outra.
        assert NotificationType.CONVERSATION_REPLY.value == "conversation_reply"
        assert NotificationType.CONVERSATION_REPLY != NotificationType.COMMENT_MENTION

    def test_a_categoria_tambem_e_distinta(self) -> None:
        """E não basta o tipo ser diferente — a CATEGORIA também tem de ser.

        A categoria é o que a pessoa silencia nas preferências. Se a resposta de
        conversa caísse em `mentions`, calar o burburinho de uma conversa
        movimentada calava também o ser chamado pelo nome.

        (O CI apanhou-me a esquecer esta entrada por completo — há um teste que
        exige categoria para cada tipo. É desse género que se quer mais.)
        """
        from src.models.notification import NOTIFICATION_CATEGORY

        assert NOTIFICATION_CATEGORY["conversation_reply"] == "conversations"
        assert (
            NOTIFICATION_CATEGORY["conversation_reply"]
            != NOTIFICATION_CATEGORY["comment_mention"]
        )


class TestQuemEAvisado:
    """A regra de quem recebe — a parte que decide se isto é útil ou ruído."""

    def test_o_metodo_existe_e_e_chamado_ao_criar_mensagem(self) -> None:
        import inspect

        from src.services.message_service import MessageService

        assert hasattr(MessageService, "_notificar_participantes")
        fonte = inspect.getsource(MessageService.create)
        assert "_notificar_participantes" in fonte, (
            "o método existe mas ninguém o chama — seria código morto a fingir "
            "que o problema estava resolvido"
        )

    def test_nao_avisa_duas_vezes_pela_mesma_mensagem(self) -> None:
        import inspect

        from src.services.message_service import MessageService

        fonte = inspect.getsource(MessageService.create)
        # Quem foi mencionado já recebeu o seu aviso; não pode receber o
        # segundo. O `ja_avisados` é o que garante isso, e a ordem importa:
        # os mencionados primeiro, os participantes depois e a saber quem eles
        # são.
        assert "ja_avisados=set(payload.mentions or [])" in fonte
        assert fonte.index("_notificar_mencionados") < fonte.index("_notificar_participantes")

    def test_nao_avisa_o_proprio_autor(self) -> None:
        import inspect

        from src.services.message_service import MessageService

        fonte = inspect.getsource(MessageService._notificar_participantes)
        assert "destinatarios -= {autor.id}" in fonte

    def test_avisa_so_quem_ja_escreveu_ou_comecou(self) -> None:
        """Não é o projeto inteiro — é quem demonstrou interesse.

        Avisar toda a gente do projeto sobre cada mensagem transformava isto em
        ruído, e a primeira coisa que uma pessoa faz com ruído é desligá-lo
        todo — incluindo os avisos que lhe interessavam.
        """
        import inspect

        from src.services.message_service import MessageService

        fonte = inspect.getsource(MessageService._notificar_participantes)
        assert "_Message.conversation_id == conv.id" in fonte
        assert "conv.created_by" in fonte

    def test_falhar_o_aviso_nao_derruba_a_mensagem(self) -> None:
        # A mensagem já está gravada quando isto corre. Perder o texto de
        # alguém por causa de um aviso seria trocar o essencial pelo acessório.
        import inspect

        from src.services.message_service import MessageService

        fonte = inspect.getsource(MessageService._notificar_participantes)
        assert "except Exception" in fonte
        assert "logger.warning" in fonte


class TestOAvisoAcontecebMesmo:
    """O teste que faltava — e que teria apanhado o import morto.

    O ``test_mencoes_notificam.py`` inteiro verifica o TEXTO do código: que o
    método é chamado, que contém ``normalize_locale``, que apanha excepções.
    Nunca **executa** a notificação. Por isso ficou verde durante todo o tempo
    em que o ``from src.i18n.messages import get_message`` — um módulo que não
    existe — a fazia rebentar dentro do ``try`` a cada uso.

    Uma guarda de código-fonte diz que a peça está montada. Só correr a peça
    diz que ela funciona.
    """

    @pytest.mark.asyncio
    async def test_escrever_numa_conversa_cria_uma_notificacao_para_o_outro(
        self, db_session
    ) -> None:
        import uuid

        from sqlalchemy import select

        from src.models.conversation import Conversation, Message
        from src.models.notification import Notification
        from src.models.user import User
        from src.services.message_service import MessageService

        rui = User(
            id=uuid.uuid4(),
            email="rui@exemplo.pt",
            password_hash="x",
            name="Rui",
        )
        sofia = User(
            id=uuid.uuid4(),
            email="sofia@exemplo.pt",
            password_hash="x",
            name="Sofia",
        )
        db_session.add_all([rui, sofia])

        # O Rui começou a conversa e escreveu lá.
        conv = Conversation(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            created_by=rui.id,
            title="Custo por canal",
        )
        db_session.add(conv)
        await db_session.flush()
        db_session.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                role="user",
                kind="question",
                content="qual foi o custo por canal em Julho?",
                user_id=rui.id,
            )
        )
        await db_session.commit()

        # A Sofia comenta. Sem mencionar ninguém.
        await MessageService(db_session)._notificar_participantes(
            sofia, conv, "este número não inclui o afiliado", ja_avisados=set()
        )
        await db_session.commit()

        avisos = (
            (await db_session.execute(select(Notification).where(Notification.user_id == rui.id)))
            .scalars()
            .all()
        )
        assert len(avisos) == 1, "o Rui tem de ser avisado de que lhe responderam"
        assert "Sofia" in avisos[0].title
        assert "Custo por canal" in avisos[0].title
        assert str(conv.id) in avisos[0].deep_link

        # E a Sofia não recebe aviso do que ela própria escreveu.
        dela = (
            (await db_session.execute(select(Notification).where(Notification.user_id == sofia.id)))
            .scalars()
            .all()
        )
        assert dela == []
