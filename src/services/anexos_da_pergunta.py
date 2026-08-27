"""Os documentos que a pessoa anexou a uma pergunta.

> *"Os ficheiros estão a funcionar, tanto mobile quanto web?"* — Lucas

Estavam a meio: o telemóvel anexa um documento a uma pergunta; a web não
tinha a funcionalidade de todo. E o bloqueio não era só de interface — o
`/ai/chat`, que é o endpoint da web, **não lia anexos nenhuns**. Só o
`/chat/stream`, que a web não usa.

Este módulo é esse bloco, tirado de dentro do `/chat/stream` para que os
dois o possam chamar. Duas cópias da mesma leitura de ficheiros seria a
garantia de que uma delas ficava para trás — e a que fica para trás nestas
coisas é sempre a que decide o que o modelo vê.

---

## O que aqui se guarda

**O dono.** Cada ficheiro é lido com `user_id == quem_pergunta`. Sem isso,
saber um `file_id` chegava para ler o documento de outra pessoa através de
uma pergunta. É a linha mais importante do ficheiro.

**A ordem.** Os documentos entram na ordem em que foram anexados. Juntá-los
ao contrário dava ao modelo «o segundo, e antes dele o primeiro» — que é
outra coisa, quando a pessoa anexa um contrato e depois o aditamento.

**O silêncio.** Um ficheiro que não existe, ou de outra pessoa, ou sem texto
extraído, é simplesmente ignorado. A pergunta segue sem ele em vez de
rebentar — mas quem chama fica a saber quantos entraram, para o poder dizer.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, List

logger = logging.getLogger(__name__)

# Quanto de cada documento vai no prompt. Um PDF de 300 páginas não cabe, e
# cortar é melhor do que estourar a janela e perder a pergunta com ele.
MAX_CARACTERES_POR_ANEXO = 100_000


async def leads_dos_anexos(db, ctx: Any, quem_pergunta) -> List[str]:
    """O texto de cada anexo, pronto a pôr à frente da pergunta.

    Devolve uma lista — vazia quando não há anexos legíveis — na ordem em
    que foram anexados.
    """
    from src.api.v1.ai import attachment_ids
    from src.models.file import FileUpload

    leads: List[str] = []
    for file_id in attachment_ids(ctx):
        try:
            fu = await db.get(FileUpload, _uuid.UUID(str(file_id)))
            # **O dono.** Sem esta comparação, um `file_id` conhecido lia o
            # documento de outra pessoa.
            if fu is None or fu.user_id != quem_pergunta.id:
                continue
            texto = ((fu.parsed_data or {}).get("text") or "").strip()
            if not texto:
                # Imagens caem aqui: sobem, mas não há OCR nem modelo com
                # visão, por isso não têm texto nenhum. Ver `file_extract`.
                continue
            leads.append(
                f'The user attached a document named "{fu.original_name}". '
                f'Use its contents to answer:\n"""\n'
                f"{texto[:MAX_CARACTERES_POR_ANEXO]}\n\"\"\""
            )
        except Exception as err:  # noqa: BLE001 — um anexo mau não trava a pergunta
            logger.debug("anexo ignorado (%s): %s", file_id, err)
    return leads


def juntar_aos_dados(leads: List[str], instrucoes: str | None) -> str | None:
    """Põe os documentos **antes** das instruções que já existiam.

    À frente e não atrás: o que vem primeiro no prompt é o que enquadra a
    leitura do resto.
    """
    if not leads:
        return instrucoes
    junto = "\n\n".join(leads)
    return f"{junto}\n\n{instrucoes}" if instrucoes else junto
