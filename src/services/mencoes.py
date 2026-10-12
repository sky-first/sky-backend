"""Quem foi mencionado numa mensagem.

**Os ids que o cliente manda ganham sempre.** Vêm do selector do `@`, onde a
pessoa escolheu alguém concreto — é a única forma sem ambiguidade.

O texto é a rede de segurança. A app decidia «isto é uma menção» com
``@([a-zA-Z0-9_.-]+)``: «@Ángela» e «@Óscar» não casavam, a mensagem ia para
a Sky sem ``mentions``, e a pessoa nunca era avisada (auditoria da app,
12/10/2026). Aqui o ``@nome`` resolve-se sem acentos e sem maiúsculas — mas
**só** contra quem está na conversa (a equipa ou o projeto dela), e **só**
quando o nome aponta para uma pessoa. Dois candidatos para o mesmo nome =
ninguém: avisar a pessoa errada é pior do que não avisar.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: `@` no início ou depois de espaço (para «ana@empresa.com» não contar), e
#: letras de QUALQUER alfabeto — `\w` em Python é Unicode.
_MENCAO = re.compile(r"(?:^|(?<=\s))@([\w][\w.\-]*)", re.UNICODE)

#: Não são pessoas.
_RESERVADAS = {"sky", "all", "todos", "todas", "everyone", "equipa", "equipo", "team"}


def normalizar(texto: str) -> str:
    """«Ángela» → «angela». Sem acentos, sem maiúsculas, sem pontuação final."""
    base = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(c for c in base if not unicodedata.combining(c))
    return sem_acentos.casefold().strip(".-_")


def nomes_mencionados(texto: str) -> List[str]:
    """Os `@nome` do texto, já normalizados, sem repetidos e sem reservados."""
    vistos: List[str] = []
    for bruto in _MENCAO.findall(texto or ""):
        n = normalizar(bruto)
        if n and n not in _RESERVADAS and n not in vistos:
            vistos.append(n)
    return vistos


def _chaves_da_pessoa(name: Optional[str], email: Optional[str], nickname: Optional[str]) -> Set[str]:
    chaves: Set[str] = set()
    nome = normalizar(name or "")
    if nome:
        partes = nome.split()
        chaves.add(partes[0])  # primeiro nome: «@angela»
        chaves.add("".join(partes))  # nome colado: «@angelaruiz»
        chaves.add(".".join(partes))  # «@angela.ruiz»
        chaves.add("_".join(partes))
    if email:
        chaves.add(normalizar(email.split("@", 1)[0]))
    if nickname:
        chaves.add(normalizar(nickname).replace(" ", ""))
    chaves.discard("")
    return chaves


async def audiencia_da_conversa(db: AsyncSession, conv) -> List[UUID]:
    """Quem pode ver a conversa — a mesma regra do `_can_view`."""
    from src.models.crew import CrewMember

    if getattr(conv, "crew_id", None) is not None:
        rows = await db.execute(
            select(CrewMember.user_id).where(CrewMember.crew_id == conv.crew_id)
        )
        return [r[0] for r in rows.all()]
    if getattr(conv, "space_id", None) is not None:
        from src.services.notificar_o_projeto import quem_esta_no_projeto

        return list(await quem_esta_no_projeto(db, conv.space_id))
    return []


async def resolver_mencoes(
    db: AsyncSession,
    conv,
    conteudo: str,
    ids_do_cliente: Optional[Iterable[UUID]] = None,
) -> List[UUID]:
    """Ids a avisar: os do cliente, mais os `@nome` do texto que apontam para
    exactamente uma pessoa da conversa."""
    resultado: List[UUID] = []
    for i in ids_do_cliente or []:
        try:
            uid = i if isinstance(i, UUID) else UUID(str(i))
        except (ValueError, TypeError):
            continue
        if uid not in resultado:
            resultado.append(uid)

    nomes = nomes_mencionados(conteudo)
    if not nomes:
        return resultado

    audiencia = await audiencia_da_conversa(db, conv)
    if not audiencia:
        return resultado

    from src.models.user import User

    rows = await db.execute(
        select(User.id, User.name, User.email, User.preferences).where(
            User.id.in_(audiencia), User.deleted_at.is_(None)
        )
    )
    por_chave: Dict[str, Set[UUID]] = {}
    for uid, name, email, prefs in rows.all():
        apelido = prefs.get("nickname") if isinstance(prefs, dict) else None
        for chave in _chaves_da_pessoa(name, email, apelido):
            por_chave.setdefault(chave, set()).add(uid)

    for nome in nomes:
        candidatos = por_chave.get(nome) or set()
        if len(candidatos) == 1:
            uid = next(iter(candidatos))
            if uid not in resultado:
                resultado.append(uid)
    return resultado
