"""Cifra as configs de ligação que ficaram EM CLARO na base.

── Porque existe ───────────────────────────────────────────────────────

Até esta correcção havia dois caminhos que gravavam credenciais sem cifra
em ``data_connections.config``:

* o ``PATCH /connections/{id}`` com ``config`` (era um TODO) — gravava o
  que vinha, tal e qual;
* qualquer escrita sem ``ENCRYPTION_KEY`` no pod — o ``encrypt_dict``
  devolvia o dicionário original em silêncio.

O código novo já não deixa entrar texto claro. Isto trata do que já lá
está: percorre a base da plataforma e a de CADA cliente (Modelo B) e cifra,
no sítio, todas as linhas cuja config não tem a marca ``__encrypted``.

── Garantias ───────────────────────────────────────────────────────────

* **Dry-run por omissão.** Só escreve com ``--apply``.
* **Idempotente.** Uma linha já cifrada é ignorada; correr duas vezes é
  inofensivo.
* **Nunca imprime valores.** Só contagens e ids das ligações.
* **Recusa sem chave.** Sem ``ENCRYPTION_KEY`` não há o que cifrar — e em
  dev o ``encrypt_dict`` devolveria texto claro e o script contaria uma
  cifra que não aconteceu. Por isso aborta antes de abrir qualquer base.
* **Prova antes de gravar.** Cada blob novo é decifrado e comparado com o
  original antes do ``UPDATE``; se não bater, a linha fica como estava.

Uso (dentro de um pod do sky-be, com o env de produção):

    python -m scripts.cifrar_configs_em_claro            # dry-run
    python -m scripts.cifrar_configs_em_claro --apply    # cifra
    python -m scripts.cifrar_configs_em_claro --cliente sandbox
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional

# Raiz do repositório no path, para correr como script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Resultado:
    """O que se encontrou numa base. Só ids — nunca valores."""

    total: int = 0
    ja_cifradas: int = 0
    em_claro: List[str] = field(default_factory=list)
    cifradas: List[str] = field(default_factory=list)
    ignoradas: List[str] = field(default_factory=list)  # config não é um dict
    falhadas: List[str] = field(default_factory=list)


def _precisa_de_cifra(config: Any) -> Optional[bool]:
    """True = em claro; False = já cifrada; None = não é um dict (ignorar)."""
    from src.utils.encryption import is_encrypted

    if not isinstance(config, dict):
        return None
    return not is_encrypted(config)


async def tratar_base(db, aplicar: bool) -> Resultado:
    """Encontra (e, com ``aplicar``, cifra) as configs em claro desta sessão.

    Inclui ligações apagadas em soft-delete: a credencial continua lá.
    Faz ``commit`` só se ``aplicar`` e houver alguma coisa cifrada.
    """
    from sqlalchemy import select, update

    from src.models.connection import DataConnection
    from src.utils.encryption import decrypt_dict, encrypt_dict, is_encrypted

    r = Resultado()
    linhas = (await db.execute(select(DataConnection.id, DataConnection.config))).all()
    for cid, config in linhas:
        r.total += 1
        estado = _precisa_de_cifra(config)
        if estado is None:
            r.ignoradas.append(str(cid))
            continue
        if estado is False:
            r.ja_cifradas += 1
            continue
        r.em_claro.append(str(cid))
        if not aplicar:
            continue

        try:
            blob = encrypt_dict(config)
            # Prova: o blob tem a marca e decifra para exactamente o original.
            if not is_encrypted(blob) or decrypt_dict(blob) != config:
                r.falhadas.append(str(cid))
                continue
            await db.execute(
                update(DataConnection).where(DataConnection.id == cid).values(config=blob)
            )
            r.cifradas.append(str(cid))
        except Exception as exc:  # noqa: BLE001
            # Só o tipo: a mensagem pode trazer pedaços da config.
            print(f"    ! {cid}: falhou ({type(exc).__name__})")
            r.falhadas.append(str(cid))

    if aplicar and r.cifradas:
        await db.commit()
    return r


def _imprimir(slug: str, r: Resultado, aplicar: bool) -> None:
    print(
        f"[{slug}] total={r.total} já_cifradas={r.ja_cifradas} "
        f"em_claro={len(r.em_claro)} cifradas={len(r.cifradas)} "
        f"ignoradas={len(r.ignoradas)} falhadas={len(r.falhadas)}"
    )
    if r.em_claro:
        rotulo = "cifradas agora" if aplicar else "por cifrar (dry-run)"
        ids = r.cifradas if aplicar else r.em_claro
        print(f"    {rotulo}: {', '.join(ids) or '-'}")
    if r.ignoradas:
        print(f"    config não-dict (ignoradas): {', '.join(r.ignoradas)}")
    if r.falhadas:
        print(f"    FALHADAS (ficaram como estavam): {', '.join(r.falhadas)}")


async def correr(aplicar: bool, so_cliente: Optional[str] = None) -> int:
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.tenant_context import current_tenant
    from src.utils.encryption import _get_fernet
    from src.workers.por_cada_cliente import clientes_activos, contexto_do_cliente

    if _get_fernet() is None:
        print("ERRO: ENCRYPTION_KEY não está definida — nada foi lido nem escrito.")
        return 2

    modo = "APPLY" if aplicar else "DRY-RUN"
    print(f"== cifrar configs em claro ({modo}) ==")

    slugs = await clientes_activos()
    if so_cliente:
        slugs = [s for s in slugs if s == so_cliente]
        if not slugs:
            print(f"ERRO: cliente {so_cliente!r} não está na lista de clientes activos.")
            return 2

    total_claro, total_cifradas, bases_falhadas, linhas_falhadas = 0, 0, 0, 0
    for slug in slugs:
        try:
            async with contexto_do_cliente(slug) as resolveu:
                if not resolveu:
                    print(f"[{slug}] não resolveu para uma base — SALTADO")
                    bases_falhadas += 1
                    continue
                async with tenant_connection_manager.session_for(current_tenant()) as db:
                    r = await tratar_base(db, aplicar)
        except Exception as exc:  # noqa: BLE001
            print(f"[{slug}] FALHOU a base ({type(exc).__name__}) — os outros seguem")
            bases_falhadas += 1
            continue
        _imprimir(slug, r, aplicar)
        total_claro += len(r.em_claro)
        total_cifradas += len(r.cifradas)
        linhas_falhadas += len(r.falhadas)

    print(
        f"== total: bases={len(slugs)} em_claro={total_claro} "
        f"cifradas={total_cifradas} linhas_falhadas={linhas_falhadas} "
        f"bases_falhadas={bases_falhadas} =="
    )
    if not aplicar and total_claro:
        print("Dry-run: nada foi escrito. Repetir com --apply para cifrar.")
    return 1 if (bases_falhadas or linhas_falhadas) else 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true", help="cifra de facto (por omissão é dry-run)")
    p.add_argument("--cliente", default=None, help="só este slug (ex.: sandbox, default)")
    args = p.parse_args()
    sys.exit(asyncio.run(correr(args.apply, args.cliente)))


if __name__ == "__main__":
    main()
