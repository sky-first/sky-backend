# -*- coding: utf-8 -*-
"""Quem abre a sessão global tem de estar nesta lista.

── Porque é que a marca que já existia não chegava ─────────────────

O `test_multi_tenant_isolation` conta as ocorrências de
`AsyncSessionLocal()` em `src/` e exige que o número não suba. É um
tecto, e um tecto tem um buraco: **não distingue plataforma de
cliente**.

Hoje encontrei dez caminhos que serviam dados de CLIENTE com a sessão
da plataforma, e todos estavam dentro da marca — verdes desde sempre.
Pior: corrigir um deles liberta uma vaga, e o próximo caminho errado
entra sem a marca se mexer.

── O que isto faz em vez disso ─────────────────────────────────────

Lista os FICHEIROS onde a sessão global é legítima, com a razão de
cada um. Um ficheiro fora da lista falha, mesmo que o total desça.

A diferença importa: «o número não subiu» não quer dizer nada quando o
que mudou foi QUEM está lá dentro.

── Como falha, e o que fazer ───────────────────────────────────────

Se falhar com um ficheiro novo: ou ele serve dados de um cliente — e
então usa-se `tenant_connection_manager.session_for(current_tenant())`
— ou é mesmo da plataforma, e acrescenta-se aqui **com a razão**. Uma
lista que se possa engordar sem justificar não vale nada.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PADRAO = re.compile(r"\bAsyncSessionLocal\s*\(\s*\)")

#: Ficheiro → porque é que a sessão da plataforma é a certa ali.
#:
#: Regra para entrar: o código tem de correr ANTES de haver cliente
#: (resolução de quem é), ou operar sobre dados que vivem mesmo na
#: plataforma (registo, provisionamento, facturação, métricas).
DA_PLATAFORMA: dict[str, str] = {
    "config/database.py": (
        "a fábrica. É aqui que a sessão global é definida."
    ),
    "config/tenant_connection_manager.py": (
        "o recurso do próprio gestor quando não há cliente. É o desenho."
    ),
    "api/middleware/tenant_resolver.py": (
        "resolve QUEM é o cliente. Corre antes de haver um, e não pode "
        "pedir o contexto que ainda vai produzir."
    ),
    "api/v1/auth.py": (
        "descobre o cliente pelo domínio do email, no registo da "
        "plataforma. Mesma razão do resolvedor."
    ),
    "services/rbac_service.py": (
        "o portão de consentimento compara o domínio contra o registo."
    ),
    "workers/provisioning_worker.py": (
        "cria e destrói clientes. O `ProvisioningJob` é da plataforma — "
        "a base do cliente pode ainda não existir."
    ),
    "workers/pricing_worker.py": (
        "os limites de plano e os contadores por cliente vivem na "
        "plataforma, de propósito: é ela que cobra."
    ),
    "workers/llm_metrics_worker.py": (
        "percorre o registo e grava instantâneos agregados."
    ),
    "workers/por_cada_cliente.py": (
        "lê a tabela de clientes. É a peça que os DESCOBRE."
    ),
    "workers/agent_worker.py": (
        "o laço de topo lê o registo para saber por que clientes passar; "
        "o trabalho de cada um já abre a sessão dele."
    ),
    "workers/insight_agent_worker.py": (
        "mesmo laço de topo, mesma razão."
    ),
    # ── Por rever. Não são «OK»: são «ainda não investigados». ───────
    #
    # Entraram aqui para o teste poder passar hoje sem fingir que estão
    # bem. Cada linha é dívida escrita, não absolvição.
    "api/v1/presence.py": (
        "POR REVER — procura o utilizador e grava o estado de presença "
        "na plataforma. Se o utilizador vive na base do cliente, o "
        "socket fecha e ninguém aparece online."
    ),
    "api/deps.py": (
        "POR REVER — `_track_activity` escreve `last_active_at`. Baixa "
        "gravidade, mesma raiz."
    ),
    "api/v1/console.py": (
        "POR REVER — a Console é plano de plataforma, mas desde 16/08 a "
        "equipa SkyFirst é um cliente e os operadores vivem na base dele."
    ),
    "services/auth_service.py": (
        "POR REVER — a tarefa de onboarding cria o projecto e a página "
        "por omissão. Se for na plataforma, nascem órfãos."
    ),
    "workers/cache_warming_worker.py": (
        "POR REVER — lê ligações e histórico para aquecer a cache. Na "
        "plataforma não há nenhum: diz sempre «0 candidatos»."
    ),
}


def _ficheiros_com_sessao_global() -> dict[str, int]:
    achados: dict[str, int] = {}
    for caminho in RAIZ.rglob("*.py"):
        rel = caminho.relative_to(RAIZ).as_posix()
        if rel.startswith("tests/"):
            continue
        try:
            fonte = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = len(PADRAO.findall(fonte))
        if n:
            achados[rel] = n
    return achados


def test_nenhum_ficheiro_novo_abre_a_sessao_global():
    """O que a marca numérica não via.

    Um caminho de cliente novo entra sem o total subir, desde que
    alguém tenha corrigido outro no mesmo PR.
    """
    novos = sorted(set(_ficheiros_com_sessao_global()) - set(DA_PLATAFORMA))
    assert not novos, (
        "ficheiros a abrir a sessão GLOBAL sem estarem declarados: "
        f"{novos}\n\n"
        "Se servem dados de um cliente (spaces, agentes, achados, "
        "widgets, conversas, documentos, embeddings), use "
        "`tenant_connection_manager.session_for(current_tenant())` — "
        "senão lê e escreve na base da plataforma, SEM ERRO NENHUM.\n"
        "Se é mesmo da plataforma, acrescente a `DA_PLATAFORMA` com a "
        "razão."
    )


def test_a_lista_nao_tem_ficheiros_que_ja_nao_existem():
    """O contrapeso.

    Uma lista de excepções que ninguém poda cresce até deixar de
    significar alguma coisa — e um ficheiro corrigido que continue
    listado dá licença ao próximo erro no mesmo sítio.
    """
    atuais = _ficheiros_com_sessao_global()
    mortos = sorted(f for f in DA_PLATAFORMA if f not in atuais)
    assert not mortos, (
        f"já não abrem a sessão global, tire-os da lista: {mortos}"
    )


def test_cada_excepcao_tem_razao_escrita():
    curtas = [f for f, razao in DA_PLATAFORMA.items() if len(razao) < 30]
    assert not curtas, f"excepções sem razão a sério: {curtas}"


def test_os_caminhos_corrigidos_hoje_nao_voltam():
    """Afirmados pelo nome, porque foram encontrados um a um.

    O achado de uma corrida à mão, a construção de páginas pela IA e o
    processamento de documentos. Os três escreviam na base errada.
    """
    atuais = _ficheiros_com_sessao_global()
    for f in (
        "api/v1/agents.py",
        "workers/ai_worker.py",
        "workers/knowledge_worker.py",
    ):
        assert f not in atuais, f"{f} voltou a abrir a sessão global"


def test_a_varredura_encontra_alguma_coisa():
    # Senão o regex partiu-se e isto aprova o repositório inteiro.
    assert len(_ficheiros_com_sessao_global()) >= 8
