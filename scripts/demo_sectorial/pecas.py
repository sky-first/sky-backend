# -*- coding: utf-8 -*-
"""As peças com que um sector se descreve: páginas, widgets e agentes.

Um sector é dados — não código. Este ficheiro dá-lhe a forma, e
`motor.py` transforma-a em linhas na base do cliente.

── Porque é que o widget traz o SQL ────────────────────────────────

Cada widget declara a consulta que o preenche, e o motor corre-a contra
a base sintética **no momento da sementeira**, guardando o resultado em
`widget.data`. O painel abre instantâneo e não depende de nada em
tempo de execução.

É a mesma lição da demo pública, que chegou a ter o LLM no caminho
crítico do primeiro contacto e demorava ~13,7s por pergunta quando não
estourava de todo. Numa reunião com um cliente, um painel que demora
treze segundos a aparecer já perdeu o argumento que estava a tentar
fazer.

Os agentes são o contrário, e de propósito: correm ao vivo, contra a
ligação real. É isso que se está a vender.

── A geometria é por ranhuras ──────────────────────────────────────

As posições no canvas são livres (x, y em píxeis). Escrever os números
à mão em cada widget torna qualquer alteração de layout num exercício
de aritmética, e foi assim que o primeiro esboço ficou com dois
widgets sobrepostos. As ranhuras resolvem isso: pede-se a posição, não
se calcula.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── A grelha ────────────────────────────────────────────────────────
#
# Quatro colunas no topo para os números grandes, e duas metades por
# baixo para os quadros e os gráficos. Tudo em píxeis de canvas.

_MARGEM_X = 60
_TOPO = 80
_ESPACO = 24

_LARG_KPI = 300
_ALT_KPI = 190

_LARG_METADE = 612
_ALT_CORPO = 330

_LARG_INTEIRA = 1248


def _ranhura(nome: str) -> tuple[dict, dict]:
    """(position, size) para uma ranhura com nome.

    `kpi1`..`kpi4` — a fila de números grandes, em cima.
    `esq1`/`dir1`  — a primeira fila de corpo, duas metades.
    `esq2`/`dir2`  — a segunda fila.
    `larga1`/`larga2` — uma peça a toda a largura, na mesma fila.
    """
    if nome.startswith("kpi"):
        i = int(nome[3:]) - 1
        x = _MARGEM_X + i * (_LARG_KPI + _ESPACO)
        return {"x": float(x), "y": float(_TOPO)}, {
            "width": float(_LARG_KPI),
            "height": float(_ALT_KPI),
        }

    fila = int(nome[-1]) - 1
    y = _TOPO + _ALT_KPI + _ESPACO + fila * (_ALT_CORPO + _ESPACO)

    if nome.startswith("larga"):
        return {"x": float(_MARGEM_X), "y": float(y)}, {
            "width": float(_LARG_INTEIRA),
            "height": float(_ALT_CORPO),
        }

    x = _MARGEM_X if nome.startswith("esq") else _MARGEM_X + _LARG_METADE + _ESPACO
    return {"x": float(x), "y": float(y)}, {
        "width": float(_LARG_METADE),
        "height": float(_ALT_CORPO),
    }


# ── Widgets ─────────────────────────────────────────────────────────


@dataclass
class Widget:
    """Um widget e a consulta que o enche.

    `dados` recebe as linhas devolvidas pelo `sql` e devolve o que vai
    para `widget.data`. O formato não é livre: é o que o frontend sabe
    ler, e cada construtor aqui em baixo conhece o seu.
    """

    tipo: str
    titulo: str
    ranhura: str
    esquema: str  # qual das ligações do sector o alimenta
    sql: str
    dados: Callable[[list[dict]], dict]
    config: dict = field(default_factory=dict)

    def geometria(self) -> tuple[dict, dict]:
        return _ranhura(self.ranhura)


def _primeiro_valor(linhas: list[dict]) -> Any:
    if not linhas:
        return None
    return next(iter(linhas[0].values()))


def kpi(
    titulo: str,
    ranhura: str,
    esquema: str,
    sql: str,
    *,
    legenda: str,
    formato: Optional[str] = None,
) -> Widget:
    """Um número grande.

    O frontend lê `data.value` directamente (`extractRawValue`, caso 1)
    e o subtítulo de `data.config.label`. O `sql` tem de devolver uma
    linha com uma coluna.

    ── `formato` tem dois valores e os dois tinham armadilha ────────

    `"eur"` → o `KpiWidget` formata moeda com `cfg.currency || "USD"`.
    Sem dizer a moeda, um custo por quilómetro de 1,20 € aparecia como
    **$1.20** — dólares, numa demonstração em castelhano para uma
    transportadora ibérica. Vai sempre com `currency: "EUR"`.

    `"pct"` → o componente usa `Intl` com `style: "percent"`, que espera
    o valor na gama **0–1**. Passar 19,7 dava **1 970%**. O valor é
    dividido aqui, e não no SQL, para a consulta continuar a devolver o
    número que uma pessoa lê quando a executa à mão.

    Nenhuma das duas rebenta: dão um número errado com ar de certo, que
    é a única coisa que uma demonstração não pode fazer. Confirmei as
    duas no próprio `Intl` antes de corrigir.

    As duas grafias são aceites — `"eur"`/`"currency"` e `"pct"`/
    `"percent"` — e não por generosidade. A primeira versão desta
    correcção só tratava os apelidos curtos, e os dois sectores
    escreviam os nomes longos: o código novo nunca corria e os cartões
    continuavam em dólares. Uma função que depende de o chamador
    escolher a palavra certa entre duas igualmente razoáveis está a
    pedir exactamente este erro.

    O `sufixo` saiu: escrevia uma chave `suffix` que o componente não lê.
    Configuração morta é pior do que configuração nenhuma — parece que
    alguém tratou do assunto.
    """

    def monta(linhas: list[dict]) -> dict:
        valor = _primeiro_valor(linhas)
        cfg: dict[str, Any] = {"label": legenda}
        if formato in ("eur", "currency"):
            cfg["format"] = "currency"
            cfg["currency"] = "EUR"
            # Sem abreviar, e com os cêntimos só onde eles dizem alguma
            # coisa.
            #
            # O componente abrevia a partir de 10 000 e usa duas casas
            # por omissão. Sozinhos, os dois davam «€1.9M» para a
            # facturação e «€1,862,227.00» quando não abreviava. Nenhum
            # dos dois serve: numa demonstração o número É o argumento, e
            # 50 090 € de mercadoria a caducar lido como «€50.1K» perde
            # metade da força.
            #
            # O corte nos 100 € é o mesmo do formatador da demo pública,
            # e pela mesma razão: abaixo dessa ordem de grandeza os
            # cêntimos carregam o sentido (1,20 €/km contra 1,49 €/km),
            # acima dela são ruído.
            cfg["abbreviate"] = False
            if isinstance(valor, (int, float)):
                cfg["decimals"] = 2 if abs(valor) < 100 else 0
        elif formato in ("pct", "percent"):
            cfg["format"] = "percent"
            cfg["decimals"] = 1
            if isinstance(valor, (int, float)):
                # Arredondado para não guardar `0.19699999999999998` na
                # base. O `Intl` arredondaria na mesma, mas o que fica
                # gravado também se lê — em registos, em exportações, e
                # na próxima pessoa que abra a tabela.
                valor = round(valor / 100.0, 5)
        elif formato:
            cfg["format"] = formato
        return {"value": valor, "config": cfg}

    return Widget("kpi", titulo, ranhura, esquema, sql, monta)


def grafico(
    titulo: str,
    ranhura: str,
    esquema: str,
    sql: str,
    *,
    variante: str = "bar",
    x: str,
    y: str,
) -> Widget:
    """Um gráfico.

    O frontend aceita `{type, data:[linhas], mapping:{x,y}}` — ver
    `widget-container.tsx`, onde `dataArray` e `mapping` são lidos de
    `widget.data`. As chaves do `mapping` têm de existir nas linhas, ou
    o componente recusa desenhar e diz-o na consola.
    """

    def monta(linhas: list[dict]) -> dict:
        return {"type": variante, "data": linhas, "mapping": {"x": x, "y": y}}

    return Widget("chart", titulo, ranhura, esquema, sql, monta)


def tabela(titulo: str, ranhura: str, esquema: str, sql: str) -> Widget:
    """Um quadro. As colunas saem das chaves da primeira linha."""

    def monta(linhas: list[dict]) -> dict:
        return {"data": linhas}

    return Widget("table", titulo, ranhura, esquema, sql, monta)


# ── Páginas e agentes ───────────────────────────────────────────────


@dataclass
class Pagina:
    nome: str
    descricao: str
    icone: str
    cor: str
    widgets: list[Widget]


@dataclass
class Agente:
    """Um agente corre AO VIVO. Não se pré-calcula nada.

    `foco` é a pergunta em linguagem natural — é o que o utilizador lê
    e edita. `sql` é opcional: com ele o agente é determinista
    (`monitor_type='sql'`), sem ele responde pelo caminho normal.

    ── `tabelas` não é decoração ───────────────────────────────────

    Declara as tabelas de que a pergunta precisa, com esquema. Não vai
    para a base: serve para o teste poder verificar, a sério, que o
    agente consegue responder com a ligação que tem.

    Sem isto o teste era inútil e eu não tinha dado por isso. Ele
    procurava nomes de tabelas no texto do `foco` — e um `foco` é uma
    pergunta em castelhano escrita para uma pessoa, não SQL. Nenhum
    agente real nomeia tabelas, portanto o teste passava sempre, com
    qualquer agente, incluindo um que pedisse uma junção impossível.

    Era um teste que fixava o código em vez do comportamento. A
    declaração torna a intenção explícita, e explícito é o que se pode
    verificar.
    """

    nome: str
    foco: str
    esquema: str
    tabelas: list[str] = field(default_factory=list)
    frequencia: str = "daily"
    sql: Optional[str] = None
    arquetipo: str = "custom"


@dataclass
class Pergunta:
    """Uma pergunta e a sua resposta, como um fio de conversa.

    ── Porque é que a resposta não é um texto ──────────────────────

    Porque o cliente vai repetir a pergunta ao vivo.

    Uma resposta escrita à mão fica certa no dia em que se escreve e
    passa a mentir no dia seguinte — os dados mudam, o número do fio
    fica. E a mentira é da pior espécie: é o produto a contradizer-se a
    si mesmo à frente de quem está a decidir se compra.

    Por isso a resposta é uma função do resultado do `sql`. A mesma
    consulta que o motor corre para gravar o fio é a que a aplicação
    corre quando alguém pergunta outra vez.

    ── `esquemas`, no plural, ao contrário do agente ──────────────

    Uma pergunta na conversa pode atravessar ligações; um agente não.

    A diferença está no código: o `_get_all_connections_for_space`
    entrega à conversa **todas** as ligações do projecto, e o
    `connection_ids` segue com mais do que uma. O agente, não — guarda
    uma só em `connection_ids`, e é por isso que o `Agente` declara um
    esquema e esta declara uma lista.

    A lista não é decoração: o teste exige que cubra todos os esquemas
    que o SQL lê. Uma pergunta que leia um esquema fora das ligações do
    projecto é respondida uma vez — agora, pelo semeador, que fala com
    a base inteira — e nunca mais.
    """

    texto: str
    esquemas: list[str]
    sql: str
    resposta: Callable[[list[dict]], str]
    # A página onde o fio fica pendurado, pelo nome.
    #
    # Estavam todas na primeira página do sector, porque o motor usava
    # `sector.paginas[0]` para todas. As outras três abriam sem conversa
    # nenhuma, e numa demonstração é exactamente onde se vai a seguir:
    # mostra-se o painel da merma e pergunta-se sobre a merma.
    #
    # Vazio mantém o comportamento antigo — a primeira página.
    pagina: str = ""


@dataclass
class Sector:
    """Tudo o que define uma demonstração sectorial."""

    chave: str
    nome_do_projecto: str
    descricao: str
    # {sufixo da ligação: (nome visível, esquema em skydemo, descrição)}
    ligacoes: dict[str, tuple[str, str, str]]
    paginas: list[Pagina]
    agentes: list[Agente]
    perguntas: list[Pergunta] = field(default_factory=list)
