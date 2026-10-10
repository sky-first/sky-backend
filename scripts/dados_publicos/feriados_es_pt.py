# -*- coding: utf-8 -*-
"""
Prova 3 — Feriados: Espanha (nacionais + Extremadura + Madrid) e Portugal.

Fonte:    Nager.Date API pública v3 (https://date.nager.at/api/v3/PublicHolidays/{ano}/{país}).
          Código MIT; termos da API pública não publicados -> em produção, semear
          uma tabela própria 1x/ano e corrigir com BOE (ES) e DRE (PT).
Licença:  ver acima; sem chave.
Prova:    que respondemos "¿mañana es festivo en origen o destino?" e listamos os
          próximos feriados relevantes para uma rota ES<->PT.
Limites:  só nacionais e regionais (campo "counties"); NÃO tem feriados municipais
          (ex. San Juan em Badajoz, San Isidro em Madrid cidade, feriados municipais PT).
          Não aplica as trasladações das CCAA quando o feriado cai a domingo
          (ver aviso no fim). Datas dependem do BOE do ano.

Uso:  python feriados_es_pt.py [AAAA-MM-DD]   (omissão: amanhã)
"""
import datetime as dt
import sys

import requests

from _comum import UA, Cronometro

URL = "https://date.nager.at/api/v3/PublicHolidays/{ano}/{pais}"
REGIOES = {"ES-EX": "Extremadura", "ES-MD": "Madrid"}


def feriados(ano, pais):
    with Cronometro("nager") as c:
        r = requests.get(URL.format(ano=ano, pais=pais), headers=UA, timeout=20)
        r.raise_for_status()
    return r.json(), c.ms


def aplica(h, regiao):
    """True se o feriado h vale na região (None = nacional)."""
    return h.get("global") or not h.get("counties") or (regiao in (h.get("counties") or []))


def e_feriado(dia, pais, regiao=None):
    lista, _ = feriados(dia.year, pais)
    return [h["localName"] for h in lista if h["date"] == dia.isoformat() and aplica(h, regiao)]


def main():
    alvo = (
        dt.date.fromisoformat(sys.argv[1])
        if len(sys.argv) > 1
        else dt.date.today() + dt.timedelta(days=1)
    )
    ano = alvo.year
    es, ms_es = feriados(ano, "ES")
    pt, ms_pt = feriados(ano, "PT")
    print(f"Nager.Date: ES {len(es)} entradas ({ms_es} ms) · PT {len(pt)} entradas ({ms_pt} ms)")

    print(
        f"\n== {alvo:%d/%m/%Y} ({['seg','ter','qua','qui','sex','sáb','dom'][alvo.weekday()]}) =="
    )
    for nome, pais, reg in [
        ("Espanha nacional", "ES", None),
        ("Extremadura", "ES", "ES-EX"),
        ("Madrid", "ES", "ES-MD"),
        ("Portugal", "PT", None),
    ]:
        lst = es if pais == "ES" else pt
        hits = [
            h["localName"]
            for h in lst
            if h["date"] == alvo.isoformat()
            and (h.get("global") if reg is None else aplica(h, reg))
        ]
        print(f"  {nome:17}: {', '.join(hits) if hits else 'não é feriado'}")
    seguinte = (alvo + dt.timedelta(days=1)).isoformat()
    for pais, lst in (("ES", es), ("PT", pt)):
        for h in lst:
            if h["date"] == seguinte and h.get("global"):
                print(f"  ⚠ {pais}: é VÉSPERA de feriado nacional ({h['localName']}, {seguinte})")

    fim = alvo + dt.timedelta(days=60)
    print(f"\n== Próximos 60 dias ({alvo:%d/%m} → {fim:%d/%m/%Y}) ==")
    for pais, lst in (("ES", es), ("PT", pt)):
        for h in lst:
            d = dt.date.fromisoformat(h["date"])
            if not (alvo <= d <= fim):
                continue
            regs = h.get("counties")
            if regs and not any(r in REGIOES for r in regs):
                continue
            ambito = "nacional" if not regs else "/".join(REGIOES[r] for r in regs if r in REGIOES)
            dom = (
                "  ⚠ cai a DOMINGO: verificar trasladação no BOE/CCAA"
                if d.weekday() == 6 and pais == "ES"
                else ""
            )
            print(f"  {pais} {d:%d/%m/%Y} {h['localName'][:38]:38} [{ambito}]{dom}")

    print(
        "\nNota: sem feriados municipais. Restrições DGT a pesados aplicam-se também a domingos e véspera de feriado."
    )


if __name__ == "__main__":
    main()
