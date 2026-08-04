"""A demo tem de saber dizer que não.

O bug que isto fecha não fazia a demo falhar — fazia-a parecer estúpida.
Perguntar *"qual é a capital da França?"* devolvia um relatório de
churn, com a pergunta do visitante como título por cima da resposta de
outra pessoa. E a razão era pior do que parecia: sem embeddings, o
fallback devolvia **a primeira pergunta da lista**, sempre. Não a mais
próxima — a primeira. Qualquer pergunta do mundo dava o mesmo texto.

Um ecrã de erro perde-se; parecer burro não se recupera. Num pitch é a
diferença entre "isto ainda não está pronto" e "isto não presta".

O portão é grosseiro de propósito: o erro caro é o falso positivo.
Recusar uma pergunta de negócio legítima é chato — quem for recusado
recebe um convite a reformular. Responder com dados de negócio a quem
perguntou pela capital da França é ridículo, e o ridículo custa a venda.
"""

from __future__ import annotations

import pytest

from src.services.demo_domain_gate import dataset_vocabulary, is_in_domain


# ─── o que tem de ser recusado ──────────────────────────────────────


@pytest.mark.parametrize(
    "pergunta",
    [
        "qual é a capital da França?",
        "what is the capital of France?",
        "quem foi Napoleão?",
        "who is the president of Portugal?",
        "conta-me uma piada",
        "tell me a joke",
        "escreve um poema sobre o mar",
        "write a poem about the sea",
        "traduz isto para inglês",
        "que horas são?",
        "como está o tempo hoje?",
    ],
)
def test_conhecimento_geral_e_recusado(pergunta):
    assert not is_in_domain(pergunta), pergunta


def test_receita_de_bolo_nao_conta_como_receita():
    """'Receita' significa duas coisas em português, e a colisão é
    exactamente o tipo de falso positivo que faz o produto parecer
    desatento."""
    assert not is_in_domain("qual é a receita de bolo de chocolate?")


def test_pergunta_vazia_ou_curta_de_mais():
    for p in ("", "   ", "vendas", "?"):
        assert not is_in_domain(p), repr(p)


# ─── o que tem de passar ────────────────────────────────────────────


@pytest.mark.parametrize(
    "pergunta",
    [
        "que clientes estão em risco de cancelar?",
        "quanta receita está parada em faturas vencidas?",
        "qual foi a margem por região no último trimestre?",
        "which customers are most likely to churn?",
        "how much revenue is in overdue invoices?",
        "que canal de marketing traz mais vendas?",
        "os meus custos subiram este mês?",
        "quantas encomendas ficaram por entregar?",
        "que produtos vendem mais mas dão menos lucro?",
        "como evoluiu a utilização de licenças?",
    ],
)
def test_perguntas_de_negocio_passam(pergunta):
    assert is_in_domain(pergunta), pergunta


def test_acentos_nao_impedem_reconhecimento():
    """'utilização' tem de bater com 'utilizacao' — senão metade das
    perguntas escritas em português correcto são recusadas."""
    assert is_in_domain("como está a utilização das licenças?")
    assert is_in_domain("como esta a utilizacao das licencas?")


# ─── vocabulário do próprio dataset ─────────────────────────────────


class _FakeInsight:
    sources = [
        {"table": "crm.accounts"},
        {"table": "product_usage.account_health"},
    ]


class _FakeQA:
    def __init__(self, question):
        self.question = question


def test_termos_que_estao_no_ecra_sao_reconhecidos():
    """Quem usa as palavras que a demo lhe mostrou não pode ser
    recusado — seria castigá-lo por ter lido."""
    vocab = dataset_vocabulary(
        _FakeInsight(), [_FakeQA("Which accounts have low seat utilisation?")]
    )

    assert is_in_domain("show me account_health for enterprise", vocab)
    assert is_in_domain("what about seat utilisation?", vocab)


def test_vocabulario_do_dataset_nao_abre_a_porta_a_tudo():
    """Acrescentar vocabulário não pode transformar o portão numa
    passagem livre."""
    vocab = dataset_vocabulary(_FakeInsight(), [_FakeQA("Which accounts churn?")])

    assert not is_in_domain("qual é a capital da França?", vocab)
    assert not is_in_domain("conta-me uma piada", vocab)


def test_vocabulario_aguenta_dataset_vazio():
    assert dataset_vocabulary(None, None) == set()
    assert dataset_vocabulary(None, []) == set()


# ── o vocabulário do dataset não pode furar o portão ────────────────


class _FakeQA:
    def __init__(self, question: str):
        self.question = question


def test_stopwords_of_the_curated_questions_do_not_open_the_gate():
    """O bug que isto fecha: *what* estava no vocabulário do dataset.

    As perguntas curadas são frases inteiras — "What is the win rate…",
    "How much revenue…" — e o vocabulário do dataset engolia as palavras
    de ligação delas. A partir daí qualquer frase em inglês partilhava
    uma palavra com o dataset e era tratada como pergunta de negócio.

    O Lucas perguntou "What's my name?" e recebeu um relatório de churn.
    """
    vocab = dataset_vocabulary(
        None,
        [
            _FakeQA("Which customers are most likely to churn, and what revenue is at stake?"),
            _FakeQA("What is the win rate, and how long does a deal take to close?"),
        ],
    )
    assert "what" not in vocab
    assert "how" not in vocab
    assert "is" not in vocab
    # …e as palavras que interessam continuam lá.
    assert "customers" in vocab
    assert "churn" in vocab


def test_identity_questions_are_refused():
    """Não sabemos o nome dele, e não há nada curado que se pareça."""
    for question in ("What's my name?", "Qual é o meu nome?", "who am i?"):
        assert not is_in_domain(question, {"customers", "churn", "revenue"})


def test_at_stake_does_not_make_football_a_business_question():
    """'jogo' entra no vocabulário por "que receita está em jogo".

    Um saco de palavras não distingue as duas acepções; o padrão sim. E
    a pergunta legítima continua a passar.
    """
    vocab = dataset_vocabulary(None, [_FakeQA("Que clientes vão sair, e que receita está em jogo?")])
    assert not is_in_domain("quem ganhou o jogo ontem?", vocab)
    assert is_in_domain("que receita está em jogo?", vocab)
