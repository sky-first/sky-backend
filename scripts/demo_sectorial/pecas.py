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
            "width": float(_LARG_KPI), "height": float(_ALT_KPI)
        }

    fila = int(nome[-1]) - 1
    y = _TOPO + _ALT_KPI + _ESPACO + fila * (_ALT_CORPO + _ESPACO)

    if nome.startswith("larga"):
        return {"x": float(_MARGEM_X), "y": float(y)}, {
            "width": float(_LARG_INTEIRA), "height": float(_ALT_CORPO)
        }

    x = _MARGEM_X if nome.startswith("esq") else _MARGEM_X + _LARG_METADE + _ESPACO
    return {"x": float(x), "y": float(y)}, {
        "width": float(_LARG_METADE), "height": float(_ALT_CORPO)
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
    esquema: str          # qual das ligações do sector o alimenta
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
    sufixo: Optional[str] = None,
) -> Widget:
    """Um número grande.

    O frontend lê `data.value` directamente (`extractRawValue`, caso 1)
    e o subtítulo de `data.config.label`. O `sql` tem de devolver uma
    linha com uma coluna.
    """

    def monta(linhas: list[dict]) -> dict:
        cfg: dict[str, Any] = {"label": legenda}
        if formato:
            cfg["format"] = formato
        if sufixo:
            cfg["suffix"] = sufixo
        return {"value": _primeiro_valor(linhas), "config": cfg}

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
class Sector:
    """Tudo o que define uma demonstração sectorial."""

    chave: str
    nome_do_projecto: str
    descricao: str
    # {sufixo da ligação: (nome visível, esquema em skydemo, descrição)}
    ligacoes: dict[str, tuple[str, str, str]]
    paginas: list[Pagina]
    agentes: list[Agente]
