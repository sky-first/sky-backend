"""Fronteira de domínio das perguntas da demo.

O bug que isto fecha era o pior da demo, porque não a fazia falhar —
fazia-a parecer estúpida. Perguntar *"qual é a capital da França?"*
devolvia um relatório de churn, com a pergunta do visitante como título
por cima da resposta de outra. Pior do que a aparência: sem embeddings,
o fallback devolve **a primeira pergunta da lista**, sempre. Não a mais
próxima — a primeira. Qualquer pergunta do mundo dava o mesmo texto.

Um ecrã de erro perde-se; parecer burro não se recupera. Num pitch é a
diferença entre "isto não está pronto" e "isto não presta".

A correcção não é melhorar a semelhança — é **saber dizer que não**. E
dizê-lo posiciona o produto em vez de o envergonhar:

    A Sky responde sobre os dados do teu negócio. Não é um assistente
    geral — não sabe a capital da França, sabe que clientes te vão
    deixar.

Como se decide: sem modelo, por sobreposição de vocabulário. É
grosseiro de propósito. O erro caro é o falso positivo (dar uma
resposta de negócio a uma pergunta que não é de negócio), portanto na
dúvida o portão recusa. Uma pergunta de negócio legítima que caia fora
recebe um convite a reformular — chato, mas honesto; o inverso é
ridículo.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Set

# Vocabulário de negócio que a demo cobre. PT e EN juntos porque a
# pergunta pode vir em qualquer um dos dois independentemente do idioma
# da interface — alguém a navegar em português escreve "churn".
DOMAIN_TERMS: Set[str] = {
    # dinheiro
    "receita",
    "faturacao",
    "faturamento",
    "fatura",
    "faturas",
    "margem",
    "lucro",
    "custo",
    "custos",
    "preco",
    "precos",
    "desconto",
    "mrr",
    "arr",
    "revenue",
    "invoice",
    "invoices",
    "margin",
    "profit",
    "cost",
    "pricing",
    "billing",
    "cash",
    "dinheiro",
    "euros",
    "valor",
    "ticket",
    # clientes
    "cliente",
    "clientes",
    "conta",
    "contas",
    "customer",
    "customers",
    "account",
    "accounts",
    "subscricao",
    "subscricoes",
    "subscription",
    "renovacao",
    "renewal",
    "churn",
    "cancelamento",
    "cancelou",
    "retencao",
    "retention",
    "risco",
    "risk",
    # vendas
    "venda",
    "vendas",
    "sales",
    "pipeline",
    "negocio",
    "negocios",
    "deal",
    "deals",
    "oportunidade",
    "oportunidades",
    "opportunity",
    "lead",
    "leads",
    "conversao",
    "conversion",
    "funil",
    "funnel",
    "proposta",
    "quota",
    # marketing
    "campanha",
    "campanhas",
    "campaign",
    "canal",
    "canais",
    "channel",
    "marketing",
    "trafego",
    "traffic",
    "cac",
    "roi",
    "anuncio",
    "ads",
    # produto / uso
    "utilizacao",
    "uso",
    "usage",
    "adocao",
    "adoption",
    "licenca",
    "licencas",
    "lugares",
    "seats",
    "funcionalidade",
    "feature",
    "engagement",
    "login",
    # operações
    "stock",
    "inventario",
    "inventory",
    "encomenda",
    "encomendas",
    "order",
    "orders",
    "entrega",
    "delivery",
    "fornecedor",
    "supplier",
    "producao",
    "devolucao",
    "refund",
    "projeto",
    "projecto",
    "project",
    "horas",
    "hours",
    # equipa
    "equipa",
    "equipe",
    "team",
    "colaborador",
    "funcionario",
    "employee",
    "vendedor",
    "rep",
    "regiao",
    "region",
    "mercado",
    "market",
    # analítica genérica
    "tendencia",
    "trend",
    "crescimento",
    "growth",
    "queda",
    "quebra",
    "comparar",
    "evolucao",
    "previsao",
    "forecast",
    "kpi",
    "metrica",
    "metricas",
    "metric",
    "dashboard",
    "relatorio",
    "report",
    "segmento",
    "trimestre",
    "quarter",
    "mes",
    "meses",
    "month",
    "ano",
    "semana",
    "top",
    "melhores",
    "piores",
    "media",
    "total",
    "percentagem",
}

# Termos que faltavam e apanhavam perguntas legítimas de lado nenhum:
# "what is our win rate?" não tem uma única palavra de negócio na lista
# fixa, e só passava por acaso, se o dataset em uso tivesse uma pergunta
# curada com as mesmas palavras.
DOMAIN_TERMS = DOMAIN_TERMS | {
    "win", "wins", "won", "rate", "rates", "trend", "trends", "trended",
    "trending", "business", "deal", "deals", "pipeline", "funnel", "quota",
    "negocio", "negocios", "taxa", "taxas", "tendencia", "tendencias",
    "ganhos", "fecho", "fechados",
}

# Perguntas cuja forma denuncia conhecimento geral. Servem para recusar
# depressa e com uma mensagem melhor, mesmo quando por acaso partilham
# uma palavra com o vocabulário acima.
GENERAL_KNOWLEDGE_PATTERNS = (
    r"\bcapital d[eoa]\b",
    r"\bquem (foi|e|era)\b",
    r"\bwho (is|was)\b",
    r"\bwhat is the capital\b",
    r"\bquantos habitantes\b",
    r"\bpopulation of\b",
    r"\btraduz\b",
    r"\btranslate\b",
    r"\bescreve um[a]? (poema|texto|email|carta)\b",
    r"\bwrite (a|an) (poem|essay|email|letter)\b",
    r"\bconta[- ]me uma piada\b",
    r"\btell me a joke\b",
    r"\bque horas sao\b",
    r"\bcomo (esta|estas) (o tempo|tu)\b",
    r"\bweather\b",
    r"\breceita de\b",  # "receita de bolo" — colide com receita/revenue
    # Identidade do visitante. Não sabemos o nome dele, e a demo não tem
    # nada que se pareça com uma resposta — mas "what's my name?" partilha
    # o *what* com metade das perguntas curadas e passava.
    r"\b(o )?meu nome\b",
    r"\bmy name\b",
    r"\bquem sou eu\b",
    r"\bwho am i\b",
    # Desporto. "jogo" está no vocabulário do dataset por causa de
    # "que receita está em jogo" — um saco de palavras não distingue as
    # duas acepções, e este padrão distingue.
    r"\bquem (ganhou|venceu)\b",
    r"\bo jogo de\b",
    r"\bjogo de (ontem|hoje|amanha)\b",
    r"\bwho won\b",
    r"\bthe (game|match)\b",
)

MIN_QUESTION_WORDS = 2


def _fold(text: str) -> str:
    """Minúsculas sem acentos, para 'utilização' bater com 'utilizacao'."""
    norm = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in norm if unicodedata.category(c) != "Mn").lower()


def _words(text: str) -> Iterable[str]:
    return re.findall(r"[a-z0-9_]+", _fold(text))


def is_in_domain(question: str, extra_terms: Optional[Iterable[str]] = None) -> bool:
    """A pergunta é sobre dados de negócio?

    ``extra_terms`` recebe o vocabulário do próprio dataset — nomes de
    tabelas e colunas — para que uma pergunta que use os termos do
    cliente conte como do domínio mesmo que não esteja na lista fixa.
    """
    folded = _fold(question)
    if not folded.strip():
        return False

    for pattern in GENERAL_KNOWLEDGE_PATTERNS:
        if re.search(pattern, folded):
            return False

    words = set(_words(question))
    if len(words) < MIN_QUESTION_WORDS:
        # "vendas?" sozinho não é uma pergunta que se possa responder
        # bem, e responder mal é o que estamos a tentar evitar.
        return False

    vocabulary = set(DOMAIN_TERMS)
    for term in extra_terms or ():
        vocabulary.update(_words(term))

    return bool(words & vocabulary)


# Palavras de ligação que aparecem no conteúdo curado e não dizem nada
# sobre o assunto.
#
# Sem esta lista o portão fica inútil, e ficou: as perguntas curadas
# começam por "What is…", "How much…", portanto *what*, *is* e *how*
# entravam no vocabulário do dataset e qualquer frase em inglês passava.
# "What's my name?" foi respondida com um relatório de churn por causa
# disto — a palavra que a deixou passar foi *what*.
_STOPWORDS = {
    # inglês
    "a", "about", "actually", "all", "and", "any", "are", "as", "at", "be",
    "but", "by", "can", "close", "did", "do", "does", "doing", "for", "from",
    "get", "give", "had", "has", "have", "how", "in", "into", "is", "it",
    "its", "just", "long", "many", "me", "much", "my", "no", "not", "of",
    "on", "only", "or", "our", "out", "over", "same", "should", "since",
    "so", "some", "take", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "up", "us", "use",
    "used", "using", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "why", "will", "with", "you", "your",
    # português
    "com", "como", "da", "das", "de", "do", "dos", "e", "em", "entre", "essa",
    "esse", "esta", "este", "eu", "foi", "há", "isso", "isto", "já", "mais",
    "mas", "me", "meu", "minha", "muito", "na", "nas", "no", "nos", "nossa",
    "nosso", "num", "numa", "o", "os", "ou", "para", "pelo", "por", "posso",
    "qual", "quais", "quando", "quanto", "quantos", "que", "quem", "se",
    "sem", "ser", "seu", "sua", "são", "também", "tem", "tenho", "ter",
    "teu", "tua", "um", "uma", "vai", "você",
}


def dataset_vocabulary(insight, qas) -> Set[str]:
    """Vocabulário do dataset: nomes de tabelas e texto das perguntas.

    Assim, um visitante que use os termos que a demo mostra no ecrã —
    'seats', 'account_health' — é sempre reconhecido, sem que esses
    termos tenham de estar na lista fixa.

    **Só palavras com conteúdo.** Uma pergunta curada é uma frase
    inteira, e deixar entrar as palavras de ligação dela transformava o
    portão numa peneira: bastava a pergunta do visitante partilhar um
    *what* para ser tratada como sendo sobre o negócio dele.
    """
    terms: Set[str] = set()
    for source in getattr(insight, "sources", None) or []:
        table = (source or {}).get("table") if isinstance(source, dict) else None
        if table:
            terms.update(_words(table.replace(".", " ")))
    for qa in qas or ():
        terms.update(_words(getattr(qa, "question", "") or ""))
    return {term for term in terms if len(term) > 2 and term not in _STOPWORDS}


__all__ = ["DOMAIN_TERMS", "dataset_vocabulary", "is_in_domain"]
