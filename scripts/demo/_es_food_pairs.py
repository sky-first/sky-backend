# -*- coding: utf-8 -*-
"""Escreve `scripts/demo/es/food.json` a partir das frases inglesas.

Mesma razão do `_es_transport_pairs.py`: as chaves são lidas do
`curated_content.json`, não escritas à mão. Um mapa com as chaves
copiadas falha na primeira vírgula que mude de sítio, e o
`build_es_content.py` só diz "sem tradução".

    python scripts/demo/build_food_content.py
    python scripts/demo/_es_food_pairs.py
    python scripts/demo/build_es_content.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CONTEUDO = RAIZ / "scripts" / "demo" / "curated_content.json"
SAIDA = RAIZ / "scripts" / "demo" / "es" / "food.json"

TRADUZIVEIS = {
    "name", "description", "agent_name", "title", "summary", "label",
    "question", "answer_markdown", "series_label", "x_label", "y_label",
}

ES = [
    # 0
    "Distribuidora Guadiana — alimentación selecta y vinos",
    "Distribuidora a hostelería con 72 referencias, 360 lotes y 18 meses de pedidos.",
    "Almacén",
    "Hay mercancía caducando que todavía se vendía — y otra que ya no",
    "El stock se mira por referencia. La fecha está en el lote. Son dos vistas de la "
    "misma caja y solo una tiene la fecha — por eso la pregunta «qué caduca este mes» "
    "no tiene respuesta en ninguno de los dos sitios por separado.\n\n"
    "La distinción que importa no es entre bueno y malo: es entre lo que todavía se "
    "puede dar salida y lo que ya se perdió. Lo primero es una campaña con dos semanas "
    "de aviso; lo segundo es una merma que solo se descubre al inventariar.\n\n"
    "El vino de guarda queda fuera de esta cuenta a propósito. No caduca — envejece — "
    "y meterlo aquí inventaba un problema que no existe.",
    "Ya caducado en almacén",
    "Caduca en los próximos 60 días",
    "La familia más expuesta",
    "El lote: cuándo entró, cuándo caduca",
    "Cuánto queda de cada lote, y en qué zona",
    # 10
    "Referencia, familia, coste y precio de tarifa",
    "Margen",
    "El margen bruto es igual en todos los canales. El neto no.",
    "El rappel acordado se aplica sobre el acumulado, a final de año, y no aparece en "
    "ninguna línea de factura. Por eso el informe de ventas muestra el mismo margen en "
    "todos los canales — y está bien, hasta el día en que no lo está.\n\n"
    "El número solo existe cruzando lo vendido con el porcentaje que está en el "
    "contrato de cada cliente. Uno de los dos vive en facturación, el otro vive en una "
    "carpeta.\n\n"
    "La diferencia entre las dos columnas es dinero ya prometido y todavía sin contar.",
    "Margen bruto",
    "Margen neto tras rappel",
    "Lo que cuesta el rappel",
    "Lo que salió, de qué lote, y por cuánto",
    "Canal, plaza, y el rappel acordado",
    "Inventario",
    # 20
    "Capital parado por estrategia y capital parado por olvido",
    "En una hoja de stock los dos son la misma línea: mercancía que no se ha movido. "
    "Pero un vino de guarda que no se mueve está haciendo su trabajo, y una referencia "
    "que entró para un cliente que entretanto cerró está ocupando dinero y "
    "estantería.\n\n"
    "Lo que los separa no es la cantidad ni el tiempo — es si alguna vez se vendió. Esa "
    "columna no existe en el stock; existe en facturación.\n\n"
    "Las referencias que nunca tuvieron una sola venta son el caso extremo, y existen "
    "en cualquier catálogo.",
    "Parado sin ser de guarda",
    "De guarda — a propósito",
    "Referencias sin una sola venta",
    "¿Qué está caducando, y cuánto vale?",
    "**Separado entre lo que todavía se vende y lo que ya se perdió.** Son dos "
    "problemas distintos y solo uno tiene solución.\n\n"
    "Lo que caduca en las próximas semanas es una campaña: hay tiempo de darle salida "
    "con descuento, de proponerlo al cliente adecuado, de cambiar de plaza. Lo que ya "
    "pasó de fecha es una merma — queda decidir cómo se contabiliza.\n\n"
    "La lista viene por lote y no por referencia, porque es el lote el que lleva la "
    "fecha. Con el stock por referencia esta pregunta no tiene respuesta: la misma "
    "referencia tiene lotes de meses distintos.",
    "Ya caducado",
    "Caduca en 60 días",
    "Lotes en riesgo",
    # 30
    "¿Cuánto me está costando realmente el rappel?",
    "**Más en el canal que mejor negocia, como era de esperar — y la diferencia no "
    "aparece en ninguna parte hasta diciembre.**\n\n"
    "El margen bruto es prácticamente igual en todos los canales: la tarifa es la "
    "misma. El neto los separa, y la separación es el contrato, no la venta.\n\n"
    "La tabla pone los dos uno al lado del otro por canal. La última columna es el euro "
    "ya prometido y todavía sin apuntar — y es esa la que decide si merece la pena "
    "crecer en ese canal.",
    "Margen neto",
    "¿Qué capital tengo parado, y cuánto de él es a propósito?",
    "**La separación es la respuesta.** El total por sí solo no sirve para decidir "
    "nada, porque mezcla dos cosas opuestas.\n\n"
    "El vino de guarda está parado porque debe estarlo — es el modelo de negocio. El "
    "resto está parado porque alguien compró y nadie volvió a mirar.\n\n"
    "El caso extremo son las referencias sin una sola venta: entraron para un cliente "
    "concreto, ese cliente cambió, y se quedaron. No aparecen en ningún informe de "
    "rotación porque rotación cero no genera líneas.",
    "De guarda",
    "Sin una sola venta",
    "¿Qué familias dejan menos después del rappel?",
    "**Por margen neto, que es el orden que decide el catálogo.** El bruto ordena casi "
    "siempre de otra manera.\n\n"
    "Una familia con buen margen de tarifa que se vende sobre todo al canal con más "
    "rappel acaba por debajo de otra con peor tarifa y clientes que no negocian. Eso no "
    "se ve en la ficha del producto.",
    "Facturado en el periodo",
    # 40
    "Referencias en el catálogo",
    "¿Qué clientes pesan más, y cuáles dejan más?",
    "**Son listas distintas, y esa es la utilidad de verlas juntas.**\n\n"
    "El cliente que más factura suele ser el que más negocia — así llegó a ese volumen. "
    "La columna de margen neto al lado de la facturación dice cuánto de ese volumen "
    "llega al final.\n\n"
    "No es un argumento para perderlo. Es un argumento para saber cuánto cuesta "
    "mantenerlo, antes de la próxima negociación.",
    "Clientes activos",
    "Pedidos servidos",
    "El canal que menos deja",
    "¿Qué plazas compran más, y cuáles compensan?",
    "**Facturación y margen neto por plaza, uno al lado del otro.** La plaza que más "
    "factura no es siempre la que más deja.\n\n"
    "En una zona donde se entrega dos veces por semana a clientes pequeños, el volumen "
    "es bajo y el rappel también. En otra, media docena de cuentas grandes hacen el "
    "número y se llevan el margen con ellas.\n\n"
    "Es la cuenta que decide dónde merece la pena poner un comercial más.",
    "La plaza que más factura",
]


def frases_inglesas() -> list[str]:
    doc = json.loads(CONTEUDO.read_text(encoding="utf-8"))
    base = next(
        d for d in doc["datasets"]
        if d["vertical"] == "food" and d["locale"] == "en"
    )
    vistas: list[str] = []

    def anda(no):
        if isinstance(no, dict):
            for k, v in no.items():
                if k in TRADUZIVEIS and isinstance(v, str):
                    if v not in vistas:
                        vistas.append(v)
                else:
                    anda(v)
        elif isinstance(no, list):
            for v in no:
                anda(v)

    anda(base)
    return vistas


def main() -> None:
    en = frases_inglesas()
    if len(en) != len(ES):
        raise SystemExit(
            f"o dataset inglês tem {len(en)} frases e o espanhol tem {len(ES)}. "
            "Acrescentar ou retirar frases ao construtor obriga a mexer aqui — "
            "é de propósito, para meia tradução não chegar a um cliente."
        )
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(
        json.dumps(dict(zip(en, ES)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(en)} frases escritas em es/{SAIDA.name}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
