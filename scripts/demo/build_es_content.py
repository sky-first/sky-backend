# -*- coding: utf-8 -*-
"""Gera os datasets em espanhol a partir dos ingleses.

    python scripts/demo/build_es_content.py
    python scripts/curate_demo_content.py --verify-sql --apply

── Porque se traduz em vez de se escrever de novo ──────────────────────

Os outros três construtores (`build_distribution_content.py` e irmãos)
escrevem o SQL e o texto ao mesmo tempo, com um `L(pt, en)` por frase. Para
o espanhol isso obrigaria a mexer nos três — e a mexer no SQL de passagem,
que é a maneira mais fácil de partir números que já estão certos.

Aqui o SQL não se toca: copia-se o dataset inglês inteiro, muda-se o
`locale`, e substitui-se **só** o texto que uma pessoa lê. O que sai tem
exactamente as mesmas consultas, portanto os mesmos valores depois do
`--apply`.

── O mapa é por frase inglesa, e tem de estar completo ─────────────────

`scripts/demo/es/{vertical}.json` é `{frase inglesa: frase espanhola}`. Se
faltar uma, este script **rebenta** em vez de deixar a frase em inglês. É a
mesma regra do `espanholCompleto.test.ts` da app, pela mesma razão: meia
tradução não se vê até estar à frente de um cliente.

── O `es` NÃO é o dataset por omissão ──────────────────────────────────

`is_default` fica sempre a falso nos espanhóis. O `demo_content_service`
usa o `is_default` para escolher quando não há vertical pedida, e ter dois
predefinidos na mesma língua-mãe dava um resultado que depende da ordem
das linhas na tabela.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ALVO = RAIZ / "scripts" / "demo" / "curated_content.json"
MAPAS = RAIZ / "scripts" / "demo" / "es"

# As chaves cujo valor é texto que alguém lê no ecrã. Tudo o resto — SQL,
# nomes de tabela, formatos, posições — passa intacto.
TRADUZIVEIS = {
    "name",
    "description",
    "agent_name",
    "title",
    "summary",
    "label",
    "question",
    "answer_markdown",
    "series_label",
    "x_label",
    "y_label",
}


def traduzir(no, mapa, faltam):
    if isinstance(no, dict):
        saida = {}
        for k, v in no.items():
            if k in TRADUZIVEIS and isinstance(v, str):
                if v not in mapa:
                    faltam.append(v)
                    saida[k] = v
                else:
                    saida[k] = mapa[v]
            else:
                saida[k] = traduzir(v, mapa, faltam)
        return saida
    if isinstance(no, list):
        return [traduzir(v, mapa, faltam) for v in no]
    return no


def main() -> None:
    doc = json.loads(ALVO.read_text(encoding="utf-8"))
    datasets = doc["datasets"]

    novos = []
    faltam_todas: dict[str, list[str]] = {}

    for base in [d for d in datasets if d["locale"] == "en"]:
        vertical = base["vertical"]
        caminho = MAPAS / f"{vertical}.json"
        if not caminho.exists():
            raise SystemExit(f"sem mapa espanhol para '{vertical}': {caminho}")
        mapa = json.loads(caminho.read_text(encoding="utf-8"))

        faltam: list[str] = []
        es = traduzir(copy.deepcopy(base), mapa, faltam)
        es["locale"] = "es"
        es["is_default"] = False
        if faltam:
            faltam_todas[vertical] = faltam
        novos.append(es)

    if faltam_todas:
        for vertical, fs in faltam_todas.items():
            print(f"\n{vertical}: {len(fs)} frases sem tradução")
            for f in fs:
                print("  " + json.dumps(f, ensure_ascii=False))
        raise SystemExit(
            "\nEspanhol incompleto — nada foi escrito. "
            "Acrescente as frases acima ao mapa e volte a correr."
        )

    # Substituir os espanhóis que já existissem, em vez de os duplicar.
    doc["datasets"] = [d for d in datasets if d["locale"] != "es"] + novos
    ALVO.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(novos)} datasets espanhóis escritos em {ALVO.name}")


if __name__ == "__main__":
    main()
