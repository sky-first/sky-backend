# -*- coding: utf-8 -*-
"""Escreve `scripts/demo/es/transport.json` a partir das frases inglesas.

As chaves são lidas do `curated_content.json`, não escritas à mão: um mapa
cujas chaves foram copiadas por alguém falha em silêncio na primeira vírgula
que mudar de sítio, e o `build_es_content.py` só diz "sem tradução" sem
dizer que a culpa é de um espaço a mais.

    python scripts/demo/build_transport_content.py
    python scripts/demo/_es_transport_pairs.py
    python scripts/demo/build_es_content.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CONTEUDO = RAIZ / "scripts" / "demo" / "curated_content.json"
SAIDA = RAIZ / "scripts" / "demo" / "es" / "transport.json"

TRADUZIVEIS = {
    "name", "description", "agent_name", "title", "summary", "label",
    "question", "answer_markdown", "series_label", "x_label", "y_label",
}

# Pela mesma ordem em que aparecem no dataset inglês. O `assert` no fim é
# que garante que continuam a ser as mesmas 48.
ES = [
    # 0
    "Transportes Guadiana — 18 vehículos",
    "Transportista ibérico con 18 vehículos, 20 rutas entre Portugal y España "
    "y 12 meses de viajes.",
    "Flota",
    "Tres vehículos cuestan por kilómetro casi lo que ingresan",
    "Son los más viejos, y se les sigue asignando carga porque ya están pagados. "
    "El renting terminó, así que el coste fijo es bajo — y es ese número bajo el "
    "que hace parecer que compensa mantenerlos.\n\n"
    "Lo que no aparece en ninguna parte es la suma de lo demás: gastan un tercio "
    "más de gasóleo por kilómetro, entran en el taller varias veces al año, y pasan "
    "semanas fuera de la carretera. Cada parte vive en un sistema distinto — tarjeta "
    "de combustible, factura del taller, cuadro de servicio — y ninguna de ellas, "
    "por sí sola, parece un problema.\n\n"
    "Esto es ingreso menos coste por kilómetro, vehículo a vehículo. No es el "
    "beneficio de la empresa: la estructura no está aquí. Es lo que cada camión "
    "aporta después de pagar lo que él mismo consume.",
    "Coste medio por km",
    "Ingreso medio por km",
    "El peor de todos",
    "El vehículo, y lo que cuesta tenerlo",
    "Cada viaje: km, gasóleo, horas, llegada",
    # 10
    "Taller: avería, preventivo, días parado",
    "La carga que salió, y por cuánto",
    "Tráfico",
    "Uno de cada cinco kilómetros se hace sin carga alguna",
    "El vacío de retorno es el coste más invisible de este sector. Aparece entero en "
    "el gasóleo y no aparece en absoluto en la facturación — así que no hay ningún "
    "informe donde sea una línea.\n\n"
    "Nadie lo niega y nadie sabe cuánto es. El número solo existe cruzando los viajes "
    "con la carga: el viaje está en el cuadro de servicio, la carga está en la carta "
    "de porte, y es la ausencia de una frente a la otra lo que lo define.\n\n"
    "Por trayecto, porque así es como se resuelve: un retorno vacío repetido en el "
    "mismo sentido es un retorno sin vender, no una casualidad.",
    "Kilómetros en vacío",
    "Gasóleo quemado sin carga",
    "El trayecto con más vacío",
    "Distancia, tiempo estándar y peajes",
    "Servicio",
    # 20
    "Dos rutas incumplen la hora en más de la mitad de los viajes",
    "La puntualidad media de la operación es buena, y justamente por eso estas dos "
    "rutas nunca llegaron a una reunión: la media las tapa.\n\n"
    "Lo que hace honesto el número es medir contra la tolerancia contratada de cada "
    "cliente y no contra una hora fija. Los mismos cuarenta minutos son irrelevantes "
    "en una carga de construcción y una penalización en una de frío.\n\n"
    "Cuando una ruta falla casi siempre, el problema no es el tráfico — es el tiempo "
    "estándar, estimado una vez y nunca vuelto a mirar.",
    "Dentro del plazo del cliente",
    "Portes fuera de plazo",
    "La peor ruta",
    "Quién paga, y con qué tolerancia contratada",
    "¿Qué vehículos cuestan más por kilómetro de lo que ingresan?",
    "**Los más viejos — y son los que nadie cuestiona**, porque ya no tienen cuota.\n\n"
    "El coste por kilómetro suma cuatro cosas que viven en cuatro sistemas: gasóleo, "
    "horas de conductor, peajes y taller, más el coste fijo del vehículo. El ingreso "
    "sale de la carta de porte. La cuenta es trivial; lo que no es trivial es tener "
    "las cuatro partes en el mismo sitio.\n\n"
    "La tabla está ordenada por aportación en euros y no por porcentaje: un vehículo "
    "que rueda mucho y gana poco por kilómetro cuesta más que uno que rueda poco y "
    "pierde en cada uno — y es el primero el que vale la pena resolver.",
    "Diferencia entre las dos mitades de la flota",
    "¿Cuántos kilómetros hacemos en vacío, y en qué trayectos?",
    # 30
    "**Alrededor de una quinta parte de todo lo que rueda la flota.** Gasóleo, "
    "conductor y peajes pagados; facturación cero.\n\n"
    "No hay ningún sistema donde exista esta línea, porque se define por una ausencia: "
    "un viaje registrado sin ninguna carga asociada. El viaje está en el cuadro de "
    "servicio y la carga está en la carta de porte; hacen falta los dos para ver el "
    "agujero.\n\n"
    "Por trayecto, y ordenado por gasóleo quemado, porque así es como se actúa: un "
    "trayecto que vuelve vacío todas las semanas es un retorno sin vender, y tiene "
    "nombre y sentido.",
    "Del total recorrido",
    "¿Qué rutas llegan fuera del plazo acordado con el cliente?",
    "**Dos, y fallan casi siempre.** El resto de la operación se mueve entre el 6 y el "
    "8 por ciento, que es ruido normal.\n\n"
    "La media de la empresa es buena — y es exactamente por eso que estas dos nunca "
    "llegaron a una reunión. Una ruta que falla el 60% de las veces desaparece dentro "
    "de una media del 89%.\n\n"
    "La medición es contra la tolerancia contratada de cada cliente, no contra una "
    "hora fija: cuarenta minutos no es lo mismo en una carga de cerámica que en una "
    "de fruta.\n\n"
    "Cuando una ruta falla sistemáticamente, la causa casi nunca es el tráfico — es "
    "el tiempo estándar, estimado una vez y nunca revisado.",
    "¿Qué clientes pagan mejor por kilómetro?",
    "**Por euro facturado dividido entre los kilómetros que hubo que rodar para "
    "facturarlo** — que no es lo mismo que quién factura más.\n\n"
    "Un cliente grande que obliga a cruzar el país con carga media vacía puede rendir "
    "menos por kilómetro que uno pequeño a la puerta del almacén. La facturación total "
    "no dice eso; el euro por kilómetro sí.\n\n"
    "La columna de incidencias está al lado a propósito: mercancía dañada y fallo de "
    "temperatura cuestan dinero que nunca aparece en la tarifa.",
    "Mejor cliente por km",
    "Facturado en el periodo",
    "Incidencias de carga",
    "¿Cuánto nos costó el taller, y qué vehículos tiran de él?",
    # 40
    "**La factura del taller es la mitad de la historia; los días fuera de la "
    "carretera son la otra mitad** — y solo la primera tiene un documento.\n\n"
    "Un camión parado sigue teniendo renting, seguro e impuesto, y la carga que no "
    "hizo o se rechazó o se subcontrató. Ese coste no tiene factura ninguna, y por eso "
    "no entra en ninguna cuenta.\n\n"
    "Separar avería de preventivo es lo que importa: demasiado preventivo es caro, "
    "demasiado poco es más caro.",
    "Taller en el periodo",
    "Días fuera de la carretera",
    "Averías",
    "¿Qué conductores acumulan más horas al volante?",
    "**Antes de ser un coste, es un riesgo de tacógrafo.** Los tiempos de conducción "
    "son materia de multa y de responsabilidad, y el cuadro lo hace quien tiene la "
    "carga delante, no quien tiene la hoja de horas.\n\n"
    "La columna de cumplimiento del tiempo estándar está al lado para evitar la "
    "lectura equivocada: quien acumula horas no es necesariamente quien trabaja más "
    "despacio — puede ser quien siempre coge las rutas largas.\n\n"
    "Sale de cruzar los viajes con el registro de conductores.",
    "Más horas al volante",
    "Viajes completados",
]


def frases_inglesas() -> list[str]:
    doc = json.loads(CONTEUDO.read_text(encoding="utf-8"))
    base = next(
        d for d in doc["datasets"]
        if d["vertical"] == "transport" and d["locale"] == "en"
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
