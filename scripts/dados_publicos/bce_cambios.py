# -*- coding: utf-8 -*-
"""
Prova 4 — Câmbios de referência do BCE: EUR -> USD, GBP, MAD.

Fonte:    Banco Central Europeu, ECB Data Portal, API SDMX 2.1, série EXR
          (https://data-api.ecb.europa.eu/service/data/EXR/D.{moeda}.EUR.SP00.A).
          Documentação: https://data.ecb.europa.eu/help/api/overview
Licença:  reutilização livre com indicação da fonte (política de reutilização do BCE).
          Sem chave, sem limite publicado.
Prova:    que respondemos "quanto vale em euros a fatura de 12.000 USD ao câmbio de hoje"
          e mostramos a DATA do câmbio (o BCE publica ~16h CET em dias úteis TARGET,
          não publica ao fim de semana).
Limite:   o BCE deixou de publicar o dirham marroquino (MAD); a última observação é
          "indicativa". O script deteta e avisa — para MAD é preciso outra fonte
          (Bank Al-Maghrib) ou um fornecedor pago.
"""
import csv
import datetime as dt
import io

import requests

from _comum import UA, Cronometro

URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/D.{moedas}.EUR.SP00.A"
    "?lastNObservations=1&format=csvdata"
)
MAX_DIAS = 5  # mais velho do que isto = série parada


def cambios(moedas=("USD", "GBP", "MAD")):
    """Devolve {moeda: (taxa, data, comentario)} e ms."""
    with Cronometro("bce") as c:
        r = requests.get(URL.format(moedas="+".join(moedas)), headers=UA, timeout=30)
        r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        out[row["CURRENCY"]] = (
            float(row["OBS_VALUE"]),
            dt.date.fromisoformat(row["TIME_PERIOD"]),
            row.get("OBS_COM", ""),
        )
    return out, c.ms


def eur(v):
    """Formato europeu: 10.708,55 €"""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def main():
    taxas, ms = cambios()
    hoje = dt.date.today()
    print(f"BCE EXR (SDMX) · {ms} ms")
    for moeda in ("USD", "GBP", "MAD"):
        if moeda not in taxas:
            print(f"  EUR→{moeda}: sem dados")
            continue
        taxa, data, com = taxas[moeda]
        idade = (hoje - data).days
        aviso = (
            f"  ⚠ SÉRIE PARADA há {idade} dias ({com or 'sem comentário'}) — não usar"
            if idade > MAX_DIAS
            else ""
        )
        print(f"  1 EUR = {taxa:.4f} {moeda}  (referência de {data:%d/%m/%Y}){aviso}")
    if "USD" in taxas:
        usd, data, _ = taxas["USD"]
        print(f"\nFatura de 12.000 USD = {eur(12000 / usd)} ao câmbio BCE de {data:%d/%m/%Y}")
    print("Nota: câmbio de referência informativo; o banco do cliente aplica o seu próprio câmbio.")


if __name__ == "__main__":
    main()
