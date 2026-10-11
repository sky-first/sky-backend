# -*- coding: utf-8 -*-
"""«Todo lo que ve este proyecto»: um plano de análise pequeno e limitado.

> «Quero que seja inteligente: que olhe para o negócio através dos dados do
>  projeto e traga melhorias, alertas, ameaças e oportunidades — com números
>  concretos e o passo seguinte.» — Lucas, 11/10/2026

Antes, o modo «contexto» mandava uma pergunta só, que obrigava o motor a
**contar as linhas de cada tabela**. O resultado era um «tabla_x_count: 1204»
que não diz nada a ninguém sobre o negócio.

Agora cada corrida é um plano de no máximo `MAX_PERGUNTAS_POR_CORRIDA`
perguntas, cada uma virada para um ângulo (oportunidades, alertas, ameaças,
melhorias) e ancorada, quando o catálogo o permite, numa tabela que o dono do
agente pode ver. As respostas juntam-se numa mensagem só, com uma secção por
ângulo — e **só** as secções que trouxeram evidência (um número).

Tudo o que aqui está é puro (sem base, sem rede), excepto `catalogo_do_ambito`,
que lê o catálogo e o recorta pelo que o dono alcança. É de propósito: o plano
e a síntese são a parte com regras, e as regras testam-se sem motor nenhum.

Porque é que a síntese não é outra chamada ao modelo: cada chamada ao `sky-ai`
passa pela porta que gasta uma pergunta do plano, e não existe lá um endpoint
de «resumir texto» que não corra SQL. Juntar secções que já vêm com o número e
o passo seguinte não precisa de um modelo — precisa de não inventar.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

#: O tecto de perguntas de UMA corrida do modo «contexto». Cada uma gasta uma
#: pergunta do plano do cliente — quatro chega para os quatro ângulos.
MAX_PERGUNTAS_POR_CORRIDA = 4

#: Quantas fontes se lêem do catálogo para escolher temas. O catálogo só
#: serve para ancorar perguntas; ler cinquenta ligações não melhora nada.
_MAX_FONTES_NO_CATALOGO = 5

#: Os quatro ângulos, pela ordem em que aparecem na mensagem.
ANGULOS = ("oportunidades", "alertas", "ameacas", "melhorias")

#: O que o motor responde quando a pergunta não tem nada nos dados. Igual nas
#: três línguas para ser fácil de reconhecer — e reconhecem-se também as
#: traduções que um modelo «prestável» às vezes faz.
SEM_EVIDENCIA = "NO_EVIDENCE"
_SEM_EVIDENCIA_VARIANTES = ("no_evidence", "no evidence", "sin_evidencia", "sem_evidencia")

_TITULOS = {
    "pt": {
        "oportunidades": "Oportunidades",
        "alertas": "Alertas",
        "ameacas": "Ameaças",
        "melhorias": "Melhorias",
    },
    "es": {
        "oportunidades": "Oportunidades",
        "alertas": "Alertas",
        "ameacas": "Amenazas",
        "melhorias": "Mejoras",
    },
    "en": {
        "oportunidades": "Opportunities",
        "alertas": "Alerts",
        "ameacas": "Threats",
        "melhorias": "Improvements",
    },
}

_PASSO_SEGUINTE = {"pt": "Próximo passo", "es": "Siguiente paso", "en": "Next step"}

_INTRO = {
    "pt": "O que vi nos dados deste projeto:",
    "es": "Lo que he visto en los datos de este proyecto:",
    "en": "What I saw in this project's data:",
}

#: Duas variantes por ângulo. Um objectivo que só pede um ângulo
#: («Oportunidades de negocio») recebe as duas; o objectivo por omissão
#: recebe a primeira de cada um. `{tema}` é « em «Encomendas»» ou vazio.
_PERGUNTAS = {
    "es": {
        "oportunidades": (
            "¿Dónde está creciendo el negocio{tema}? Compara los últimos 30 días con "
            "los 30 anteriores y dime qué cliente, producto, zona o canal crece más, "
            "con la cifra y el % de cambio.",
            "¿Qué oportunidad de negocio no se está aprovechando{tema}? Busca clientes "
            "o productos de alto valor con poco volumen, o clientes que compraban y han "
            "dejado de hacerlo, y dime cuántos son y cuánto valen.",
        ),
        "alertas": (
            "¿Qué está fallando en la operación{tema}? Busca retrasos, incumplimientos, "
            "errores o valores fuera de lo normal en los últimos 30 días y dime cuántos "
            "son y cuánto pesan sobre el total.",
            "¿Qué indicador de la operación{tema} se ha desviado más de su valor "
            "habitual en la última semana? Dame el valor actual, el habitual y la "
            "diferencia.",
        ),
        "ameacas": (
            "¿Qué amenaza al negocio{tema}? Busca caídas de volumen o de ingresos, "
            "dependencia de pocos clientes o proveedores, o tendencias que empeoran, "
            "con la cifra.",
            "¿Qué parte del negocio{tema} lleva más tiempo empeorando? Dame la "
            "tendencia de los últimos meses con las cifras de cada mes.",
        ),
        "melhorias": (
            "¿Dónde se puede mejorar{tema}? Encuentra la mayor diferencia entre el "
            "mejor y el peor (zona, equipo, producto o canal) y cuánto se ganaría "
            "acercando el peor a la media.",
            "¿Qué coste, tiempo o desperdicio se podría reducir{tema}? Dame la cifra "
            "actual y cuánto se ahorraría con una mejora realista.",
        ),
    },
    "pt": {
        "oportunidades": (
            "Onde é que o negócio está a crescer{tema}? Compara os últimos 30 dias "
            "com os 30 anteriores e diz-me que cliente, produto, zona ou canal cresce "
            "mais, com o número e a % de variação.",
            "Que oportunidade de negócio não está a ser aproveitada{tema}? Procura "
            "clientes ou produtos de alto valor com pouco volume, ou clientes que "
            "compravam e deixaram de comprar, e diz-me quantos são e quanto valem.",
        ),
        "alertas": (
            "O que está a falhar na operação{tema}? Procura atrasos, incumprimentos, "
            "erros ou valores fora do normal nos últimos 30 dias e diz-me quantos são "
            "e quanto pesam no total.",
            "Que indicador da operação{tema} se desviou mais do habitual na última "
            "semana? Dá-me o valor actual, o habitual e a diferença.",
        ),
        "ameacas": (
            "O que ameaça o negócio{tema}? Procura quedas de volume ou de receita, "
            "dependência de poucos clientes ou fornecedores, ou tendências a piorar, "
            "com o número.",
            "Que parte do negócio{tema} está a piorar há mais tempo? Dá-me a "
            "tendência dos últimos meses com os números de cada mês.",
        ),
        "melhorias": (
            "Onde é que se pode melhorar{tema}? Encontra a maior diferença entre o "
            "melhor e o pior (zona, equipa, produto ou canal) e quanto se ganharia a "
            "aproximar o pior da média.",
            "Que custo, tempo ou desperdício se podia reduzir{tema}? Dá-me o número "
            "actual e quanto se pouparia com uma melhoria realista.",
        ),
    },
    "en": {
        "oportunidades": (
            "Where is the business growing{tema}? Compare the last 30 days with the "
            "previous 30 and tell me which customer, product, region or channel grows "
            "the most, with the figure and the % change.",
            "Which business opportunity is not being used{tema}? Look for high-value "
            "customers or products with low volume, or customers who used to buy and "
            "stopped, and tell me how many and how much they are worth.",
        ),
        "alertas": (
            "What is failing in the operation{tema}? Look for delays, missed "
            "deadlines, errors or out-of-range values in the last 30 days and tell me "
            "how many and how much they weigh on the total.",
            "Which operational indicator{tema} deviated the most from its usual value "
            "last week? Give me the current value, the usual one and the difference.",
        ),
        "ameacas": (
            "What threatens the business{tema}? Look for drops in volume or revenue, "
            "dependence on few customers or suppliers, or worsening trends, with the "
            "figure.",
            "Which part of the business{tema} has been getting worse for longest? "
            "Give me the trend over recent months with each month's figure.",
        ),
        "melhorias": (
            "Where can things improve{tema}? Find the biggest gap between the best and "
            "the worst (region, team, product or channel) and how much would be gained "
            "by bringing the worst up to the average.",
            "Which cost, time or waste could be reduced{tema}? Give me the current "
            "figure and how much a realistic improvement would save.",
        ),
    },
}

_TEMA = {"es": " en «{t}»", "pt": " em «{t}»", "en": " in “{t}”"}

_INSTRUCOES = {
    "es": (
        "Esta pregunta es UNA de las partes de un análisis del negocio. Responde en "
        "2 o 3 frases: el hallazgo con la cifra concreta y el periodo. Termina con "
        "una línea que empiece por «Siguiente paso:» con una acción concreta. Si los "
        "datos no muestran nada relevante para esta pregunta, responde solo: "
        f"{SEM_EVIDENCIA}. No inventes cifras."
    ),
    "pt": (
        "Esta pergunta é UMA das partes de uma análise do negócio. Responde em 2 ou "
        "3 frases: o achado com o número concreto e o período. Termina com uma linha "
        "que comece por «Próximo passo:» com uma acção concreta. Se os dados não "
        "mostrarem nada relevante para esta pergunta, responde só: "
        f"{SEM_EVIDENCIA}. Não inventes números."
    ),
    "en": (
        "This question is ONE part of a business analysis. Answer in 2 or 3 "
        "sentences: the finding with the concrete figure and the period. End with a "
        "line starting with “Next step:” and one concrete action. If the data shows "
        "nothing relevant for this question, answer only: "
        f"{SEM_EVIDENCIA}. Do not make up figures."
    ),
}

_ANTERIOR = {
    "es": "En la ejecución anterior el análisis decía: «{a}». Señala lo que ha cambiado.",
    "pt": "Na corrida anterior a análise dizia: «{a}». Assinala o que mudou.",
    "en": "In the previous run the analysis said: “{a}”. Point out what changed.",
}

#: Palavras do objectivo → ângulos. Sem acentos e em minúsculas (ver
#: `_normalizar`). As sugestões da app são «Oportunidades de negocio»,
#: «Fallos en mi operación», «Formas de mejorar», «Amenazas y alertas».
_PALAVRAS = (
    ("oportunidades", ("oportunidad", "oportunidade", "opportunit", "crecer", "crescer", "grow")),
    ("alertas", ("fallo", "falha", "fail", "alerta", "alert", "anomal", "operacion", "operacao")),
    ("ameacas", ("amenaza", "ameaca", "threat", "riesgo", "risco", "risk", "peligro", "perigo")),
    ("melhorias", ("mejor", "melhor", "improv", "eficien", "ahorr", "poupa", "optimi", "otimi")),
)


def _normalizar(texto: str) -> str:
    sem_acentos = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acentos if not unicodedata.combining(c)).lower()


def _lingua(lingua: Optional[str]) -> str:
    return lingua if lingua in _PERGUNTAS else "pt"


def angulos_do_objetivo(objetivo_escrito: Optional[str]) -> "tuple[List[str], Optional[str]]":
    """Que ângulos o objectivo pede — e o texto livre, se não pedir nenhum.

    * vazio (ou a frase de omissão) → os quatro, sem texto livre;
    * «Oportunidades de negocio» → só `oportunidades`;
    * «Amenazas y alertas» → `alertas` e `ameacas`;
    * texto livre sem nenhuma destas palavras → os quatro, e o texto vai como
      a primeira pergunta do plano (é o que a pessoa quer saber).
    """
    escrito = (objetivo_escrito or "").strip()
    if not escrito:
        return list(ANGULOS), None
    n = _normalizar(escrito)
    pedidos = [angulo for angulo, palavras in _PALAVRAS if any(p in n for p in palavras)]
    if pedidos:
        return [a for a in ANGULOS if a in pedidos], None
    return list(ANGULOS), escrito


@dataclass
class Tabela:
    """Uma tabela do catálogo, com o que interessa para escolher temas."""

    nome: str
    descricao: str = ""
    linhas: int = 0
    tem_data: bool = False
    tem_numero: bool = False

    @property
    def tema(self) -> str:
        """O nome que se põe na pergunta — a descrição curta, ou o nome legível."""
        d = (self.descricao or "").strip().split("\n")[0]
        d = re.split(r"(?<=[.;])\s", d)[0].rstrip(".;").strip()
        if d and len(d) <= 60:
            return d
        return self.nome.rsplit(".", 1)[-1].replace("_", " ").strip()

    @property
    def pontos(self) -> int:
        """Quanto vale como tema: descrita, com datas, com números, com linhas."""
        return (
            (4 if self.descricao else 0)
            + (3 if self.tem_data else 0)
            + (2 if self.tem_numero else 0)
            + (1 if self.linhas else 0)
        )


_TIPOS_DE_DATA = ("date", "time", "timestamp")
_TIPOS_DE_NUMERO = ("int", "numeric", "decimal", "float", "double", "real", "number", "money")


def tabelas_do_catalogo(tabelas_json: Iterable, autorizadas: Optional[set] = None) -> List[Tabela]:
    """`ConnectionMetadata.tables` → `Tabela`, só as `autorizadas` (se dadas)."""
    fora: List[Tabela] = []
    for t in tabelas_json or []:
        if not isinstance(t, dict):
            continue
        nome = str(t.get("name") or "").strip()
        if not nome:
            continue
        if autorizadas is not None and nome not in autorizadas:
            continue
        tipos = [
            str((c or {}).get("type") or "").lower()
            for c in (t.get("columns") or [])
            if isinstance(c, dict)
        ]
        try:
            linhas = int(t.get("row_count") or 0)
        except (TypeError, ValueError):
            linhas = 0
        fora.append(
            Tabela(
                nome=nome,
                descricao=str(t.get("description") or "").strip(),
                linhas=linhas,
                tem_data=any(any(k in tp for k in _TIPOS_DE_DATA) for tp in tipos),
                tem_numero=any(any(k in tp for k in _TIPOS_DE_NUMERO) for tp in tipos),
            )
        )
    return fora


@dataclass
class Pergunta:
    angulo: Optional[str]  # None = a pergunta livre do objectivo
    texto: str


def plano_de_analise(
    objetivo_escrito: Optional[str],
    lingua: Optional[str],
    tabelas: Optional[List[Tabela]] = None,
    maximo: int = MAX_PERGUNTAS_POR_CORRIDA,
) -> List[Pergunta]:
    """As perguntas desta corrida, no máximo `maximo`.

    Cada ângulo pedido recebe a 1.ª variante; se sobrar espaço (um objectivo
    com um ou dois ângulos), recebe também a 2.ª. As perguntas ancoram-se nas
    tabelas mais «falantes» do catálogo, uma diferente por pergunta enquanto
    houver — senão ficam genéricas e o motor escolhe as tabelas.
    """
    lingua = _lingua(lingua)
    maximo = max(1, int(maximo or 1))
    angulos, livre = angulos_do_objetivo(objetivo_escrito)

    escolhidas = sorted(tabelas or [], key=lambda t: (-t.pontos, -t.linhas, t.nome))
    escolhidas = [t for t in escolhidas if t.pontos > 0] or escolhidas

    def _tema(i: int) -> str:
        if not escolhidas:
            return ""
        return _TEMA[lingua].format(t=escolhidas[i % len(escolhidas)].tema)

    plano: List[Pergunta] = []
    if livre:
        plano.append(Pergunta(angulo=None, texto=livre))

    pares = [(a, 0) for a in angulos] + [(a, 1) for a in angulos]
    for angulo, variante in pares:
        if len(plano) >= maximo:
            break
        texto = _PERGUNTAS[lingua][angulo][variante].format(tema=_tema(len(plano)))
        plano.append(Pergunta(angulo=angulo, texto=texto))
    return plano[:maximo]


def instrucoes_da_pergunta(lingua: Optional[str], resposta_anterior: Optional[str] = None) -> str:
    """O que se acrescenta às instruções do agente em cada pergunta do plano."""
    lingua = _lingua(lingua)
    partes = [_INSTRUCOES[lingua]]
    anterior = (resposta_anterior or "").strip()
    if anterior:
        partes.append(_ANTERIOR[lingua].format(a=anterior[:400]))
    return "\n".join(partes)


_DIGITO = re.compile(r"\d")
_LINHA_DO_PASSO = re.compile(
    r"^\s*[-*•]?\s*\**\s*(siguiente paso|pr[oó]ximo passo|next step)\s*\**\s*[:：]\s*\**\s*(.*)$",
    re.IGNORECASE,
)


def tem_evidencia(resposta: Optional[str]) -> bool:
    """Uma resposta conta se tem texto, não é «sem evidência» e traz um número.

    O número é a regra que o Lucas pôs: sem ele, é opinião — e uma secção
    «Oportunidades» com uma opinião é pior do que nenhuma secção.
    """
    texto = (resposta or "").strip()
    if not texto:
        return False
    n = _normalizar(texto)
    if any(v in n for v in _SEM_EVIDENCIA_VARIANTES):
        return False
    return bool(_DIGITO.search(texto))


def _arrumar_resposta(resposta: str, lingua: str) -> str:
    """A resposta, com a linha do passo seguinte escrita sempre da mesma forma."""
    linhas = []
    for linha in resposta.strip().splitlines():
        m = _LINHA_DO_PASSO.match(linha)
        if m:
            passo = m.group(2).strip().strip("*").strip()
            if passo:
                linhas.append(f"**{_PASSO_SEGUINTE[lingua]}:** {passo}")
            continue
        linhas.append(linha.rstrip())
    return "\n".join(linhas).strip()


@dataclass
class Sintese:
    texto: str
    titulo: str
    seccoes: List[str] = field(default_factory=list)


def sintetizar(
    respostas: List["tuple[Pergunta, str]"],
    lingua: Optional[str],
    objetivo_escrito: Optional[str] = None,
) -> Optional[Sintese]:
    """UMA mensagem com as secções que trouxeram evidência. `None` se nenhuma.

    A ordem é fixa (Oportunidades, Alertas, Ameaças, Melhorias), seja qual for
    a ordem das perguntas — quem lê o fio todos os dias encontra as coisas no
    mesmo sítio. A pergunta livre do objectivo vai à frente, com o próprio
    objectivo como título.
    """
    lingua = _lingua(lingua)
    por_angulo: dict = {}
    for pergunta, resposta in respostas:
        if not tem_evidencia(resposta):
            continue
        por_angulo.setdefault(pergunta.angulo, []).append(_arrumar_resposta(resposta, lingua))

    if not por_angulo:
        return None

    blocos: List[str] = []
    titulos: List[str] = []
    if None in por_angulo:
        t = (objetivo_escrito or "").strip()
        t = t if len(t) <= 80 else t[:79].rstrip() + "…"
        titulos.append(t)
        blocos.append(f"### {t}\n" + "\n\n".join(por_angulo[None]))
    for angulo in ANGULOS:
        if angulo in por_angulo:
            t = _TITULOS[lingua][angulo]
            titulos.append(t)
            blocos.append(f"### {t}\n" + "\n\n".join(por_angulo[angulo]))

    texto = _INTRO[lingua] + "\n\n" + "\n\n".join(blocos)
    return Sintese(texto=texto, titulo=" · ".join(titulos), seccoes=titulos)


async def catalogo_do_ambito(
    db,
    agent,
    connection_ids: List[uuid.UUID],
    crew_ids: Optional[List[str]],
    pessoal: bool,
) -> List[Tabela]:
    """As tabelas do catálogo que o DONO do agente pode ver neste âmbito.

    O recorte é o mesmo do «Executar» interactivo (`PermissionService.
    get_authorized_tables`), com as equipas já resolvidas pelo worker. Os nomes
    das tabelas acabam escritos na pergunta — e a pergunta fica gravada no
    achado — por isso uma tabela fora do recorte não pode servir de tema.

    **Nunca levanta e fecha em caso de dúvida**: qualquer falha dá a lista
    vazia, e as perguntas saem genéricas (o motor escolhe as tabelas com o
    recorte dele).
    """
    if not agent.created_by or not connection_ids:
        return []
    try:
        from sqlalchemy import select

        from src.models.connection import ConnectionMetadata
        from src.services.permission_service import PermissionService

        projeto = None
        ambito = (agent.scope or "").lower()
        if ambito == "space" and agent.scope_id:
            projeto = uuid.UUID(str(agent.scope_id))
        elif ambito == "crew" and agent.scope_id:
            from src.models.crew import Crew

            projeto = (
                await db.execute(
                    select(Crew.space_id).where(Crew.id == uuid.UUID(str(agent.scope_id)))
                )
            ).scalar_one_or_none()

        equipas = [uuid.UUID(str(c)) for c in (crew_ids or [])] or None
        if pessoal:
            from src.services.ai_service import AIService

            todas = await AIService(db)._get_user_crew_ids(  # noqa: SLF001
                agent.created_by, None, all_spaces=True
            )
            equipas = [uuid.UUID(str(c)) for c in (todas or [])] or None

        perms = PermissionService(db)
        fora: List[Tabela] = []
        for cid in connection_ids[:_MAX_FONTES_NO_CATALOGO]:
            meta = (
                await db.execute(
                    select(ConnectionMetadata.tables).where(ConnectionMetadata.connection_id == cid)
                )
            ).scalar_one_or_none()
            if not meta:
                continue
            autorizadas = set(
                await perms.get_authorized_tables(
                    agent.created_by,
                    cid,
                    space_id=None if pessoal else projeto,
                    crew_ids=equipas,
                    is_personal=pessoal,
                )
                or []
            )
            fora.extend(tabelas_do_catalogo(meta, autorizadas))
        return fora
    except Exception as exc:  # noqa: BLE001 — o catálogo é ajuda, não requisito
        logger.warning("Agent %s: catálogo indisponível para o plano: %s", agent.id, exc)
        return []
