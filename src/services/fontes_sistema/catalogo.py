"""Regras do catálogo de fontes do sistema.

Tudo o que aqui está é puro (sem I/O), para se testar sem base nenhuma.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

#: Tabelas do esquema ``mundo`` que NUNCA são dadas a um cliente.
#:
#: ``rotas_referencia`` guarda resultados da TomTom; os termos de cache e
#: armazenamento ainda não estão confirmados (L2). ``gasolineras_rota``
#: herda a licença desse traçado (L8). Até haver confirmação por escrito,
#: nem a reconciliação, nem um catálogo editado à mão, nem um engano numa
#: migração conseguem fazer um GRANT delas (S8).
TABELAS_PROIBIDAS = frozenset({"rotas_referencia", "gasolineras_rota"})

#: Tabela de metadados (licença, atribuição, hora do dado) dada a qualquer
#: papel de fonte: o sky-ai cita a fonte e a hora a partir dela.
TABELA_FRESCURA = "fontes"

#: A ligação gerida na base do cliente.
CONECTOR = "sky-world"

#: Os planos que existem (``src/services/planos.py``).
PLANOS = ("starter", "core", "plus", "enterprise")

_SLUG_CLIENTE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
_ID_FONTE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_NOME_TABELA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

#: Nomes da ligação, pela língua do cliente.
NOME_DA_LIGACAO = {"pt": "Dados públicos", "es": "Datos públicos", "en": "Public data"}


class FonteInvalidaError(ValueError):
    """O catálogo pediu uma coisa que não se pode fazer (licença, tabela, plano)."""

    def __init__(self, motivo: str, mensagem: str):
        super().__init__(mensagem)
        self.motivo = motivo


def papel_do_cliente(slug: str) -> str:
    """``wt_<slug>`` — o papel de login, só leitura, de um cliente.

    O slug é validado com a mesma regra do registo; ``-`` passa a ``_``.
    Rebenta com qualquer outra coisa: o nome vai para SQL como
    identificador, e um identificador não se passa por parâmetro.
    """
    if not slug or not _SLUG_CLIENTE.match(slug):
        raise FonteInvalidaError("slug_invalido", f"slug de cliente inválido: {slug!r}")
    return "wt_" + slug.replace("-", "_")


def papel_da_fonte(fonte_id: str) -> str:
    """``wsrc_<fonte>`` — o papel NOLOGIN com SELECT nas tabelas da fonte."""
    if not fonte_id or not _ID_FONTE.match(fonte_id):
        raise FonteInvalidaError("fonte_invalida", f"id de fonte inválido: {fonte_id!r}")
    return "wsrc_" + fonte_id


def tabelas_da_fonte(fonte: Any) -> List[str]:
    """As tabelas que a fonte dá, validadas. Rebenta com uma proibida."""
    tabelas = list(getattr(fonte, "tabelas", None) or [])
    saida: List[str] = []
    for t in tabelas:
        if not isinstance(t, str) or not _NOME_TABELA.match(t):
            raise FonteInvalidaError("tabela_invalida", f"nome de tabela inválido: {t!r}")
        if t in TABELAS_PROIBIDAS:
            raise FonteInvalidaError(
                "tabela_proibida",
                f"a tabela {t!r} não pode ser dada a clientes (termos da TomTom por confirmar)",
            )
        if t == TABELA_FRESCURA:
            continue
        saida.append(t)
    return saida


def validar_para_ativar(fonte: Any) -> None:
    """Uma fonte só pode estar activa num cliente se for comercial, A e activa no catálogo."""
    if fonte is None:
        raise FonteInvalidaError("fonte_desconhecida", "fonte desconhecida")
    if getattr(fonte, "estado", None) != "ativa":
        raise FonteInvalidaError(
            "fonte_nao_ativa", f"a fonte {fonte.id!r} não está activa no catálogo"
        )
    if not getattr(fonte, "uso_comercial", False):
        raise FonteInvalidaError(
            "sem_uso_comercial", f"a fonte {fonte.id!r} não tem licença de uso comercial"
        )
    if getattr(fonte, "tipo", "A") != "A":
        raise FonteInvalidaError(
            "tipo_nao_suportado", "as fontes de tipo B (APIs ao vivo) ainda não estão disponíveis"
        )
    if not tabelas_da_fonte(fonte):
        raise FonteInvalidaError("sem_tabelas", f"a fonte {fonte.id!r} não tem tabelas")


def plano_permite(fonte: Any, plano: Optional[str]) -> bool:
    """O plano do cliente pode ter esta fonte? Sem plano (um só cliente) → sim."""
    if plano is None:
        return True
    permitidos = getattr(fonte, "planos_permitidos", None)
    if not permitidos:
        return True
    return plano in permitidos


def tabelas_desejadas(fontes: Iterable[Any]) -> List[str]:
    """União ordenada das tabelas das fontes activas de um cliente."""
    vistas: set[str] = set()
    for f in fontes:
        vistas.update(tabelas_da_fonte(f))
    return sorted(vistas)


def nome_da_ligacao(lingua: Optional[str]) -> str:
    return NOME_DA_LIGACAO.get((lingua or "pt")[:2].lower(), NOME_DA_LIGACAO["pt"])
