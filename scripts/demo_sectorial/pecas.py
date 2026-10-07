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
# Cinco filas, doze ranhuras, e a aritmética num sítio só.
#
#   A  y=80     h=190    kpi1 kpi2 kpi3 kpi4          4 números grandes
#   B  y=294    h=330    esq1 | dir1   (ou larga1)    2 peças de corpo
#   C  y=648    h=150    terco1a | terco1b | terco1c  3 blocos de texto
#   D  y=822    h=330    esq2 | dir2   (ou larga2)    2 peças de corpo
#   E  y=1176   h=300    larga3        (ou esq3|dir3) 1 peça larga
#
# ── Porque é que são doze e não seis ────────────────────────────────
#
# > «é necessário que os gráficos aqui sejam mais do que seis, tem que
# >  ser para ir 12. E tem que haver texto também… como se fosse um
# >  infográfico» — Lucas, 06/10/2026
#
# Seis widgets numa página de 1248 píxeis deixavam metade do ecrã
# vazio, e numa reunião o vazio lê-se como «não há mais nada para
# mostrar».
#
# ── E porque é que há uma fila só para texto ────────────────────────
#
# Um painel de números responde «quanto». Não responde «e então?» — e é
# essa a frase que se diz em voz alta a seguir a cada cartão. A fila de
# texto escreve-a no ecrã, para ela não depender de quem está a
# apresentar.
#
# A fila fica no MEIO de propósito: depois da primeira leitura dos
# dados e antes da segunda. É ali que, numa conversa, se para para
# dizer o que aquilo quer dizer.

_MARGEM_X = 60
_TOPO = 80
_ESPACO = 24

_LARG_KPI = 300
_ALT_KPI = 190

_LARG_METADE = 612
_ALT_CORPO = 330

_LARG_INTEIRA = 1248

#: Um bloco de texto é mais baixo do que um gráfico — são três ou
#: quatro linhas. Dar-lhe a altura de um gráfico punha três caixas
#: quase vazias no meio da página.
_LARG_TERCO = 400
_ALT_TERCO = 150

#: A fila E é mais baixa do que as outras duas de corpo: leva o quadro
#: de detalhe, que se lê a rolar, e não precisa de competir em altura
#: com o que está acima.
_ALT_LARGA = 300


def _altura_da_fila_de_corpo(n: int) -> float:
    """A altura da fila de corpo `n`.

    A partir da terceira as filas são mais baixas: levam os quadros de
    detalhe, que se leem a rolar, e não precisam de competir em altura
    com os gráficos de cima.
    """
    return float(_ALT_CORPO if n <= 2 else _ALT_LARGA)


def _y_da_fila_de_corpo(n: int) -> float:
    """O topo da fila de corpo `n` (1, 2, 3, …).

    Calculado por soma e não por multiplicação, por duas razões:

    * a fila dos textos fica **entre** a 1 e a 2, e tem altura própria.
      Com `n * (altura + espaço)` a fila 2 aterrava por cima dos textos
      — foi o primeiro erro deste desenho, e o
      `test_nenhum_widget_fica_por_cima_de_outro` apanhou-o;
    * as filas não têm todas a mesma altura (ver acima).

    Sem limite superior de propósito. Uma página que precise de uma
    quarta fila pede `esq4`/`dir4`/`larga4` e o número sai certo. A
    primeira versão parava nas três e a segunda página do sector — que
    já usava `larga1` e `larga2` — ficou sem sítio para os dois
    gráficos novos.
    """
    y = float(_TOPO + _ALT_KPI + _ESPACO)  # a primeira fila de corpo
    for i in range(1, n):
        y += _altura_da_fila_de_corpo(i) + _ESPACO
        if i == 1:
            y += _ALT_TERCO + _ESPACO  # a fila dos textos vem logo depois da 1ª
    return y


def _ranhura(nome: str) -> tuple[dict, dict]:
    """(position, size) para uma ranhura com nome.

    `kpi1`..`kpi4`                    — a fila de números grandes (A).
    `esq1`/`dir1`, `esq2`/`dir2`      — metades, filas B e D.
    `esq3`/`dir3`                     — metades, fila E.
    `larga1`/`larga2`/`larga3`        — toda a largura, nas mesmas filas.
    `terco1a`/`terco1b`/`terco1c`     — terços, fila C (os textos).

    Um nome desconhecido levanta, em vez de aterrar em (0,0) — dois
    widgets sem posição ficariam um por cima do outro e a página
    parecia ter um widget a menos.
    """
    if nome.startswith("kpi"):
        i = int(nome[3:]) - 1
        x = _MARGEM_X + i * (_LARG_KPI + _ESPACO)
        return {"x": float(x), "y": float(_TOPO)}, {
            "width": float(_LARG_KPI),
            "height": float(_ALT_KPI),
        }

    if nome.startswith("terco"):
        # `terco1a` — a fila é sempre a C; a letra diz a coluna.
        coluna = "abc".index(nome[-1])
        x = _MARGEM_X + coluna * (_LARG_TERCO + _ESPACO)
        y = _y_da_fila_de_corpo(1) + _ALT_CORPO + _ESPACO
        return {"x": float(x), "y": y}, {
            "width": float(_LARG_TERCO),
            "height": float(_ALT_TERCO),
        }

    if not (nome.startswith("esq") or nome.startswith("dir") or nome.startswith("larga")):
        raise ValueError(f"ranhura desconhecida: {nome!r}")

    fila = int(nome[-1])
    y = _y_da_fila_de_corpo(fila)
    altura = _altura_da_fila_de_corpo(fila)

    if nome.startswith("larga"):
        return {"x": float(_MARGEM_X), "y": y}, {
            "width": float(_LARG_INTEIRA),
            "height": float(altura),
        }

    x = _MARGEM_X if nome.startswith("esq") else _MARGEM_X + _LARG_METADE + _ESPACO
    return {"x": float(x), "y": y}, {
        "width": float(_LARG_METADE),
        "height": float(altura),
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


# ── Os blocos de texto ──────────────────────────────────────────────
#
# > «E tem que haver texto também… como se fosse um infográfico»
# > — Lucas, 06/10/2026
#
# Três cores, e só três. A paleta é curta de propósito: doze widgets
# numa página já são muita informação, e dar a cada um a sua cor
# transforma o painel num mostruário de cores em vez de um argumento.
#
# Cada cor quer dizer uma coisa, e sempre a mesma:

#: O que está a correr bem, ou o que o cliente já ganha.
VERDE = {"fundo": "#ecfdf5", "texto": "#065f46"}
#: O que custa dinheiro agora. É a cor que se usa mais — é o argumento.
AMBAR = {"fundo": "#fffbeb", "texto": "#92400e"}
#: Contexto: o que o número quer dizer, de onde vem, o que não diz.
AZUL = {"fundo": "#eff6ff", "texto": "#1e40af"}


def paragrafos(*partes: str) -> str:
    """Junta parágrafos, com uma linha em branco entre eles.

    Existe para os corpos dos blocos de texto não terem de escrever
    `\\n\\n` à mão. Não é só estética: um `\\n` a menos cola duas ideias
    numa parede de texto, e um a mais abre um buraco no meio do cartão —
    e nenhuma das duas coisas se vê a ler o código.

    Parágrafos vazios são deixados de fora, para um `corpo` poder omitir
    uma frase condicionalmente sem deixar o espaço dela.
    """
    return "\n\n".join(p for p in partes if p and p.strip())


def texto(
    titulo: str,
    ranhura: str,
    esquema: str,
    sql: str,
    *,
    corpo: Callable[[list[dict]], str],
    cor: dict = AZUL,
) -> Widget:
    """Um bloco de texto que diz o que os números querem dizer.

    ── Porque é que o texto também vem do SQL ──────────────────────

    Pela mesma razão que a resposta de uma `Pergunta` vem do SQL: uma
    frase escrita à mão fica certa no dia em que se escreve.

    «Dos camiões não se pagam» é verdade até alguém voltar a semear os
    dados. E a contradição é visível no mesmo ecrã — o cartão ao lado
    diz 3 e o texto diz 2 — à frente de quem está a decidir se compra.
    Era o pior sítio possível para guardar um número à mão.

    Por isso o `corpo` recebe as linhas e escreve a frase. O SQL é o
    mesmo tipo de consulta dos outros widgets e corre na sementeira.

    ── O título vai no corpo, não no cabeçalho ─────────────────────

    O `TextWidget` desenha-se cru no canvas: sem cartão, sem moldura e
    **sem cabeçalho** (ver `widget-container.tsx` — o ramo do `text` é
    o único que não leva `Card`). Um `titulo` passado a este widget
    não aparece em lado nenhum.

    Fica mesmo assim como argumento, porque o motor e os testes
    identificam widgets pelo título e um widget sem nome não se
    consegue nomear num erro. Quem quiser o título à vista escreve-o
    na primeira linha do `corpo`.
    """

    def monta(linhas: list[dict]) -> dict:
        return {
            "content": corpo(linhas),
            # 15px: um pouco menor do que o corpo de 16 por omissão. É
            # texto de apoio, e tem de se ler como apoio.
            "fontSize": 15,
            "fontWeight": "normal",
            "textAlign": "left",
            "textColor": cor["texto"],
            "backgroundColor": cor["fundo"],
        }

    return Widget("text", titulo, ranhura, esquema, sql, monta)


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
