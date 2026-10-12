# -*- coding: utf-8 -*-
"""
Tabelas de referência escritas à mão (refresco anual): portagens e restrições
DGT a pesados. Regra: se um preço/horário não foi verificado numa fonte, fica
NULL com nota — nunca um número inventado.

Verificado a 10/10/2026.
"""

import datetime as dt

VALIDO_2026 = dt.date(2026, 1, 1)

F_ES_PEAJES = (
    "administracion.gob.es — Peajes y viñetas (lista oficial de autopistas de peaje): "
    "https://administracion.gob.es/pag_Home/es/Tu-espacio-europeo/derechos-obligaciones/ciudadanos/"
    "vehiculos/normas-trafico-viales/peajes-vinetas"
)
F_BRISA_2026 = (
    "Brisa, actualização de tarifas 2026 (+2,29 % médio), noticiada por RTP "
    "https://www.rtp.pt/noticias/economia/portagens-sobem-45-centimos-entre-lisboa-e-porto-e-50-centimos-entre-lisboa-e-algarve_n1707053 "
    "e DN https://www.dn.pt/economia/portagens-sobem-45-cntimos-entre-lisboa-e-porto-e-50-cntimos-entre-lisboa-e-algarve"
)
F_EX_SCUT = "Lei n.º 37/2024 (abolição de portagens nas ex-SCUT desde 01/01/2025)"
F_LEI_6_2026 = (
    "Lei 6/2026: isenção de pesados classes 3 e 4 na A41/CREP, A19 e A8 desde 01/01/2026 "
    "(ESTUDO_DADOS_PUBLICOS_2026-10.md, §C.3)"
)
F_AP6_2024 = (
    "El Español 03/01/2024 (tarifas 2024 AP-6): "
    "https://elespanol.com/castilla-y-leon/region/20240103/nuevos-precios-autopistas-castilla-leon-euros-madrid-campomanesaleon/822167814_0.html"
)
F_PEAJES_2026 = (
    "Ordem anual do Ministerio de Transportes 2026 (+3,64 % a +4,68 %), Bolsamanía: "
    "https://www.bolsamania.com/noticias/empresas/economia--transportes-aprueba-la-actualizacion-de-los-peajes-de-las-autopistas-para-2026-con-un-alza-de-hasta-el-468--21439215.html"
)

CLASSES = ("ligeiro", "pesado_2_3_eixos", "pesado_4_mais_eixos")


def _linhas(
    corredor, origem, destino, pais, km, precos, fonte, nota, rota_demo=False, gratuita=False
):
    """precos: dict classe→preço (ou None). Gera uma linha por classe."""
    out = []
    for c in CLASSES:
        p = 0.0 if gratuita else precos.get(c)
        out.append(
            dict(
                corredor=corredor,
                origem=origem,
                destino=destino,
                classe=c,
                pais=pais,
                km=km,
                preco_eur=p,
                gratuita=gratuita,
                rota_demo=rota_demo,
                valido_de=VALIDO_2026,
                fonte=fonte,
                nota=nota,
            )
        )
    return out


def portagens():
    L = []
    # ── Rotas da demo inteiramente em Espanha: autovías sem portagem ──────────
    livres_es = [
        (
            "A-5",
            "Badajoz",
            "Madrid",
            400,
            "A-5 (Autovía del Suroeste) é autovía do Estado, sem portagem.",
        ),
        ("A-5", "Badajoz", "Mérida", 65, "A-5, autovía sem portagem."),
        (
            "A-66",
            "Badajoz",
            "Sevilla",
            220,
            "A-5 Badajoz–Mérida + A-66 (Ruta de la Plata) até Sevilla: autovías sem portagem.",
        ),
        ("A-66", "Mérida", "Almendralejo", 30, "A-66, autovía sem portagem."),
        ("A-66", "Almendralejo", "Sevilla", 170, "A-66, autovía sem portagem."),
        ("A-5/EX-A3", "Badajoz", "Almendralejo", 55, "Autovías autonómicas/estatais sem portagem."),
        ("A-66", "Mérida", "Sevilla", 195, "A-66, autovía sem portagem."),
    ]
    for corr, o, d, km, nota in livres_es:
        L += _linhas(corr, o, d, "ES", km, {}, F_ES_PEAJES, nota, rota_demo=True, gratuita=True)

    # ── Portugal: troços com preço Classe 1 verificado (2026) ──────────────────
    L += _linhas(
        "A1",
        "Lisboa",
        "Porto",
        "PT",
        300,
        {"ligeiro": 25.05},
        F_BRISA_2026,
        "Classe 1 = 25,05 € (2026, +0,45 €). Classes 2–4 não publicadas nas fontes consultadas: "
        "usar o calculador oficial da Brisa/IP. Mapa: pesado 2–3 eixos ≈ classes 2/3 PT; 4+ eixos = classe 4.",
        rota_demo=True,
    )
    L += _linhas(
        "A2/A6",
        "Marateca",
        "Caia",
        "PT",
        147,
        {"ligeiro": 15.40},
        F_BRISA_2026,
        "Troço Marateca–Caia (fronteira de Elvas/Badajoz), Classe 1 = 15,40 € (2026, +0,35 €; uma fonte diz +0,25 €). "
        "Classes 2–4 não verificadas.",
    )
    # ── Portugal: rotas da demo com troço pago sem preço total verificado ─────
    pt_parciais = [
        (
            "A2/A6",
            "Lisboa",
            "Badajoz",
            230,
            "Inclui Marateca–Caia (15,40 € classe 1) + Ponte 25 de Abril/A2 Lisboa–Marateca (não verificado).",
        ),
        (
            "A2/A6 + A-5",
            "Lisboa",
            "Madrid",
            625,
            "Parte PT como Lisboa–Caia (parcial: 15,40 € classe 1 Marateca–Caia); parte ES pela A-5 = 0 €.",
        ),
        (
            "A2/A6 + A-66",
            "Lisboa",
            "Mérida",
            300,
            "Parte PT como Lisboa–Caia; parte ES (A-5) = 0 €.",
        ),
        (
            "A2/A6 + A-66",
            "Lisboa",
            "Sevilla",
            460,
            "Itinerário depende (A6+A-66 vs A22/A-49); parte ES sem portagem pela A-66.",
        ),
        ("A1", "Porto", "Coimbra", 120, "A1 Porto–Coimbra: preço 2026 não verificado."),
        ("A1", "Coimbra", "Lisboa", 200, "A1 Coimbra–Lisboa: preço 2026 não verificado."),
        ("A3", "Porto", "Braga", 55, "A3 Porto–Braga (Brisa): preço 2026 não verificado."),
        ("A3/A1", "Braga", "Coimbra", 175, "A3 + A1: preço 2026 não verificado."),
        (
            "A1/A25 + A-62",
            "Porto",
            "Madrid",
            560,
            "A25 é ex-SCUT sem portagem desde 2025; troço A1/A29 até à A25 e parte ES (A-62 livre; AP-6/AP-51 com portagem se usadas) não verificados.",
        ),
        (
            "A1/A25/A24",
            "Porto",
            "Viseu",
            130,
            "A25 e A24 ex-SCUT sem portagem desde 2025 ("
            + F_EX_SCUT
            + "); troço A1/A29 não verificado.",
        ),
        (
            "A23 + A6",
            "Coimbra",
            "Badajoz",
            310,
            "A23 ex-SCUT sem portagem desde 2025; percurso exacto até Caia não verificado.",
        ),
        (
            "A1/A23 + A6",
            "Porto",
            "Badajoz",
            400,
            "Inclui troços A1 (pagos) e A23 (livre desde 2025); total não verificado.",
        ),
    ]
    for corr, o, d, km, nota in pt_parciais:
        L += _linhas(
            corr, o, d, "PT", km, {}, F_BRISA_2026 + " · " + F_EX_SCUT, nota, rota_demo=True
        )

    # ── Portugal: ex-SCUT livres e isenção de pesados (Lei 6/2026) ────────────
    for corr, o, d in [
        ("A23", "Torres Novas", "Guarda"),
        ("A25", "Aveiro", "Vilar Formoso"),
        ("A24", "Viseu", "Chaves"),
        ("A22", "Lagos", "Vila Real de Santo António"),
        ("A4", "Amarante", "Quintanilha"),
        ("A13", "Atalaia", "Coimbra"),
        ("A28", "Porto", "Caminha"),
    ]:
        L += _linhas(
            corr,
            o,
            d,
            "PT",
            None,
            {},
            F_EX_SCUT,
            "Ex-SCUT sem portagem desde 01/01/2025.",
            gratuita=True,
        )
    for corr, o, d in [
        ("A41/CREP", "Espinho", "Matosinhos"),
        ("A19", "Leiria", "Batalha"),
        ("A8", "Lisboa", "Leiria"),
    ]:
        for c in CLASSES:
            L.append(
                dict(
                    corredor=corr,
                    origem=o,
                    destino=d,
                    classe=c,
                    pais="PT",
                    km=None,
                    preco_eur=0.0 if c != "ligeiro" else None,
                    gratuita=c != "ligeiro",
                    rota_demo=False,
                    valido_de=VALIDO_2026,
                    fonte=F_LEI_6_2026,
                    nota="Pesados (classes 3 e 4) isentos desde 01/01/2026; ligeiros pagam (preço não verificado). "
                    "Classe 2 (2 eixos) pode não estar abrangida — confirmar.",
                )
            )

    # ── Espanha: autopistas de peaje relevantes (preço 2026 não verificado) ───
    L += _linhas(
        "AP-6",
        "Villalba",
        "Adanero",
        "ES",
        70,
        {},
        F_AP6_2024 + " · " + F_PEAJES_2026,
        "2024: ligeros 14,60 € · pesados 1 29,30 € · pesados 2 32,85 €. 2026 = +3,64–4,68 % sobre 2025, "
        "valor exacto não verificado → NULL.",
    )
    for corr, o, d, nota in [
        (
            "AP-61",
            "San Rafael",
            "Segovia",
            "Ramal da AP-6 (Castellana de Autopistas). Preço 2026 não verificado.",
        ),
        ("AP-51", "Villacastín", "Ávila", "Ramal da AP-6. Preço 2026 não verificado."),
        (
            "AP-7",
            "Alicante",
            "Cartagena",
            "AP-7 sul (SEITT). Preço 2026 não verificado; troços AP-7 norte liberados em 2020–2021.",
        ),
        ("AP-68", "Bilbao", "Zaragoza", "Preço 2026 não verificado."),
        ("AP-9", "Ferrol", "Tui", "Autopista del Atlántico. Preço 2026 não verificado."),
        ("AP-4", "Sevilla", "Cádiz", "Liberada em 2020 (fim da concessão): sem portagem."),
    ]:
        gratis = "Liberada" in nota
        L += _linhas(
            corr, o, d, "ES", None, {}, F_ES_PEAJES + " · " + F_PEAJES_2026, nota, gratuita=gratis
        )
    return L


# ── Restrições DGT 2026 a veículos >7.500 kg (Anexo II), corredor A-5 ────────

F_DGT_2026 = (
    "Resolución DGT de medidas especiales de regulación del tráfico 2026, Anexo II "
    "(assinada 14/01/2026, CSV GEN-6e69-d2a3-a54c-70e2-3c39-7a1c-d462-e4b3): "
    "https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/estado-del-trafico/restricciones/2026/"
    "report_Resolucion_DGT_Medidas_circulacion-2026-copia.pdf"
)
AMBITO = (
    ">7.500 kg MMA/MMC (mercancías en general, B.1.1). Exentos (B.1.2): gado vivo, perecíveis ATP "
    "(≥50 % da carga), Correos L–V, fundentes em vialidade invernal, auxílio rodoviário"
)


def _r(dia, km_i, km_f, troco, sentido, hi, hf, motivo, confianca, nota=None):
    return dict(
        data=dt.date.fromisoformat(dia),
        carretera="A-5",
        pk_inicio=km_i,
        pk_fim=km_f,
        sentido=sentido,
        hora_inicio=hi,
        hora_fim=hf,
        troco=troco,
        ambito=AMBITO,
        motivo=motivo,
        valido_de=dt.date.fromisoformat(dia),
        valido_ate=dt.date.fromisoformat(dia),
        confianca=confianca,
        fonte=F_DGT_2026,
        nota=nota
        or "Informativo. Fora deste troço (Talavera–Badajoz) a A-5 não tem restrição nesta data no Anexo II. "
        "Confirmar sempre no BOE/DGT.",
    )


MADRID_TALAVERA_106 = "Madrid (enlace M-50, PK 15,6) – Talavera de la Reina (PK 106)"
TALAVERA_126_MADRID = "Talavera de la Reina (PK 126) – Madrid (enlace M-40, PK 11,8)"
MADRID_TALAVERA_126 = "Madrid (enlace M-50, PK 15,6) – Talavera de la Reina (PK 126)"
NOTA_INF = (
    "A extracção do PDF desalinhou a coluna da estrada nesta data; a linha segue o padrão "
    "lido nas datas equivalentes (mesmo troço/horas). Confirmar no PDF original."
)


def restricoes_pesados():
    P, I = "lido_no_pdf", "inferido_do_padrao"
    pilar, todos, const = (
        "Fiesta Nacional / El Pilar (12/10)",
        "Todos los Santos (01/11)",
        "Constitución e Inmaculada (06–08/12)",
    )
    return [
        _r(
            "2026-10-09",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "16:00",
            "22:00",
            pilar,
            I,
            NOTA_INF,
        ),
        _r(
            "2026-10-10",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "08:00",
            "15:00",
            pilar,
            P,
        ),
        _r(
            "2026-10-12",
            126,
            11.8,
            TALAVERA_126_MADRID,
            "Entrada Madrid",
            "16:00",
            "24:00",
            pilar,
            P,
        ),
        _r(
            "2026-10-12",
            15.6,
            126,
            MADRID_TALAVERA_126,
            "Salida Madrid",
            "16:00",
            "24:00",
            pilar,
            P,
        ),
        _r(
            "2026-10-30",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "16:00",
            "22:00",
            todos,
            I,
            NOTA_INF,
        ),
        _r(
            "2026-10-31",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "08:00",
            "15:00",
            todos,
            P,
        ),
        _r(
            "2026-11-02",
            126,
            11.8,
            TALAVERA_126_MADRID,
            "Entrada Madrid",
            "16:00",
            "24:00",
            todos,
            I,
            NOTA_INF,
        ),
        _r(
            "2026-11-02",
            15.6,
            126,
            MADRID_TALAVERA_126,
            "Salida Madrid",
            "16:00",
            "24:00",
            todos,
            I,
            NOTA_INF,
        ),
        _r(
            "2026-12-04",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "16:00",
            "22:00",
            const,
            P,
        ),
        _r(
            "2026-12-05",
            15.6,
            106,
            MADRID_TALAVERA_106,
            "Ambos sentidos",
            "08:00",
            "15:00",
            const,
            I,
            NOTA_INF,
        ),
        _r(
            "2026-12-08",
            126,
            11.8,
            TALAVERA_126_MADRID,
            "Entrada Madrid",
            "16:00",
            "24:00",
            const,
            P,
        ),
        _r(
            "2026-12-08",
            15.6,
            126,
            MADRID_TALAVERA_126,
            "Salida Madrid",
            "16:00",
            "24:00",
            const,
            P,
        ),
    ]


# ── Feriados oficiais (BOE e Diário da República; sem APIs de terceiros) ────
#
# Espanha: a Dirección General de Trabajo publica no BOE, em Outubro, a
# relação de fiestas laborales do ano seguinte (nacionais + 17 CCAA + Ceuta
# e Melilla). A tabela de 2026 abaixo é o anexo de BOE-A-2025-21667,
# transcrito do HTML oficial a 12/10/2026 (verificado: 12 dias por
# território; Canarias 11 + 1 insular, ver nota). A resolução de 2027 ainda
# não saiu a 12/10/2026: para 2027 e seguintes só se carregam as nacionais
# que a lei fixa (art. 37.2 ET + art. 45 RD 2001/1983), marcadas
# provisórias e sem regionais. Quando a resolução sair, transcrever o anexo
# para ES_<ano>_* e ligá-lo em festivos_es().
#
# Portugal: art. 234.º do Código do Trabalho — 13 feriados obrigatórios,
# iguais em todo o território; os móveis (Sexta-feira Santa, Páscoa, Corpo de
# Deus) calculam-se da Páscoa. Carnaval e feriados municipais (art. 235.º)
# são facultativos e não entram.

F_BOE_2026 = (
    "BOE-A-2025-21667 — Resolución de 17/10/2025 de la Dirección General de Trabajo, fiestas laborales 2026 "
    "(BOE núm. 259, 28/10/2025): https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-21667"
)
F_ES_PROVISORIO = (
    "Art. 37.2 Estatuto de los Trabajadores + art. 45 RD 2001/1983 (BOE-A-1983-20906): fiestas nacionales "
    "fijadas por ley. Resolución BOE de fiestas laborales {ano} por publicar a 12/10/2026"
)
F_CT_PT = (
    "DRE — Código do Trabalho, art. 234.º (Lei 7/2009, redacção da Lei 8/2016): "
    "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2009-34546475"
)
LIC_BOE = "BOE — Licencia tipo BOE (reutilización, también comercial, citando la fuente)"
LIC_DRE = "DRE — legislação pública (Diário da República), reutilização livre"
_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# ISO 3166-2:ES, pela ordem das colunas do anexo do BOE.
CCAA = {
    "ES-AN": "Andalucía",
    "ES-AR": "Aragón",
    "ES-AS": "Asturias",
    "ES-IB": "Illes Balears",
    "ES-CN": "Canarias",
    "ES-CB": "Cantabria",
    "ES-CM": "Castilla-La Mancha",
    "ES-CL": "Castilla y León",
    "ES-CT": "Cataluña",
    "ES-EX": "Extremadura",
    "ES-GA": "Galicia",
    "ES-MD": "Comunidad de Madrid",
    "ES-MC": "Región de Murcia",
    "ES-NC": "C. Foral de Navarra",
    "ES-PV": "País Vasco",
    "ES-RI": "La Rioja",
    "ES-VC": "Comunitat Valenciana",
    "ES-CE": "Ciudad de Ceuta",
    "ES-ML": "Ciudad de Melilla",
}
_TODAS = tuple(CCAA)

# Anexo BOE-A-2025-21667. «*» = nacional não substituível (regiao NULL);
# «**» (nacional que a CCAA manteve) e «***» (da CCAA) = uma linha por região.
ES_2026_NACIONAIS = [
    ("2026-01-01", "Año Nuevo"),
    ("2026-04-03", "Viernes Santo"),
    ("2026-05-01", "Fiesta del Trabajo"),
    ("2026-08-15", "Asunción de la Virgen"),
    ("2026-10-12", "Fiesta Nacional de España"),
    ("2026-12-08", "Inmaculada Concepción"),
    ("2026-12-25", "Natividad del Señor"),
]
_NOTA_CN = (
    "Canarias tem ainda 1 festivo insular (Decreto 61/2025, BOC 05/05/2025): El Hierro 24/09, "
    "Fuerteventura 18/09, Gran Canaria 08/09, La Gomera 05/10, La Palma 05/08, "
    "Lanzarote e La Graciosa 15/09, Tenerife 02/02"
)
ES_2026_REGIONAIS = [
    ("2026-01-06", "Epifanía del Señor", _TODAS, None),
    ("2026-02-28", "Día de Andalucía", ("ES-AN",), None),
    (
        "2026-03-02",
        "Lunes siguiente al Día de les Illes Balears",
        ("ES-IB",),
        "01/03 cai a domingo; trasladado",
    ),
    ("2026-03-19", "San José", ("ES-GA", "ES-MC", "ES-NC", "ES-PV", "ES-VC"), None),
    ("2026-03-20", "Fiesta del Eid Fitr", ("ES-ML",), None),
    ("2026-04-02", "Jueves Santo", tuple(r for r in _TODAS if r not in ("ES-CT", "ES-VC")), None),
    (
        "2026-04-06",
        "Lunes de Pascua",
        ("ES-IB", "ES-CM", "ES-CT", "ES-NC", "ES-PV", "ES-RI", "ES-VC"),
        None,
    ),
    ("2026-04-23", "San Jorge / Día de Aragón", ("ES-AR",), None),
    ("2026-04-23", "Fiesta de Castilla y León", ("ES-CL",), None),
    ("2026-05-02", "Fiesta de la Comunidad de Madrid", ("ES-MD",), None),
    ("2026-05-27", "Fiesta del Sacrificio (Eidul Adha)", ("ES-CE",), None),
    ("2026-05-27", "Fiesta del Sacrificio (Aid al Adha)", ("ES-ML",), None),
    ("2026-05-30", "Día de Canarias", ("ES-CN",), _NOTA_CN),
    ("2026-06-04", "Corpus Christi", ("ES-CM",), None),
    ("2026-06-09", "Día de la Región de Murcia", ("ES-MC",), None),
    ("2026-06-09", "Día de La Rioja", ("ES-RI",), None),
    ("2026-06-24", "San Juan", ("ES-CT", "ES-GA", "ES-VC"), None),
    ("2026-07-25", "Santiago Apóstol / Día Nacional de Galicia", ("ES-GA", "ES-PV"), None),
    ("2026-07-28", "Día de las Instituciones de Cantabria", ("ES-CB",), None),
    ("2026-08-05", "Nuestra Señora de África", ("ES-CE",), None),
    ("2026-09-02", "Día de Ceuta", ("ES-CE",), None),
    ("2026-09-08", "Día de Asturias", ("ES-AS",), None),
    ("2026-09-08", "Día de Extremadura", ("ES-EX",), None),
    ("2026-09-11", "Fiesta Nacional de Cataluña", ("ES-CT",), None),
    ("2026-09-15", "La Bien Aparecida", ("ES-CB",), None),
    ("2026-10-09", "Día de la Comunitat Valenciana", ("ES-VC",), None),
    (
        "2026-11-02",
        "Día siguiente a Todos los Santos",
        ("ES-AN", "ES-AR", "ES-AS", "ES-CN", "ES-CM", "ES-CL", "ES-EX", "ES-MD", "ES-NC"),
        "Todos los Santos (01/11) cai a domingo; trasladado",
    ),
    (
        "2026-12-07",
        "Lunes siguiente al Día de la Constitución Española",
        ("ES-AN", "ES-AR", "ES-AS", "ES-CB", "ES-CL", "ES-EX", "ES-MD", "ES-MC", "ES-RI", "ES-ML"),
        "06/12 cai a domingo; trasladado",
    ),
    (
        "2026-12-26",
        "San Esteban",
        ("ES-IB", "ES-CT"),
        "Em Arán (Cataluña) substituído por 17/06, Fiesta de Arán (Orden EMT/66/2025)",
    ),
]


def pascoa(ano):
    """Domingo de Páscoa, calendário gregoriano (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return dt.date(ano, n // 31, n % 31 + 1)


def _fer(pais, regiao, dia, nome, fonte, licenca, nota=None):
    d = dia if isinstance(dia, dt.date) else dt.date.fromisoformat(dia)
    return dict(
        chave=f"{pais}|{regiao or 'NAC'}|{d.isoformat()}",
        data=d,
        pais=pais,
        regiao=regiao,
        nome=nome,
        nome_en=None,
        dia_semana=_DIAS[d.weekday()],
        nota=nota,
        fonte=fonte,
        licenca=licenca,
    )


def festivos_es(ano):
    """Espanha: anexo do BOE quando transcrito; senão só as nacionais da lei (provisório)."""
    if ano == 2026:  # único ano com o anexo do BOE transcrito
        L = [_fer("ES", None, d, n, F_BOE_2026, LIC_BOE) for d, n in ES_2026_NACIONAIS]
        for d, n, regioes, nota in ES_2026_REGIONAIS:
            L += [_fer("ES", r, d, n, F_BOE_2026, LIC_BOE, nota) for r in regioes]
        return L
    fonte = F_ES_PROVISORIO.format(ano=ano)
    prov = f"Provisório: resolución BOE de fiestas laborales {ano} por publicar; regionais em falta"
    L = []
    for d, n in [
        (dt.date(ano, 1, 1), "Año Nuevo"),
        (pascoa(ano) - dt.timedelta(days=2), "Viernes Santo"),
        (dt.date(ano, 5, 1), "Fiesta del Trabajo"),
        (dt.date(ano, 8, 15), "Asunción de la Virgen"),
        (dt.date(ano, 10, 12), "Fiesta Nacional de España"),
        (dt.date(ano, 11, 1), "Todos los Santos"),
        (dt.date(ano, 12, 6), "Día de la Constitución Española"),
        (dt.date(ano, 12, 8), "Inmaculada Concepción"),
        (dt.date(ano, 12, 25), "Natividad del Señor"),
    ]:
        nota = prov
        if d.weekday() == 6:
            nota += " · cai a domingo: as CCAA podem trasladar para segunda (ver BOE)"
        L.append(_fer("ES", None, d, n, fonte, LIC_BOE, nota))
    return L


def festivos_pt(ano):
    """Portugal: os 13 feriados obrigatórios do art. 234.º CT; móveis a partir da Páscoa."""
    p = pascoa(ano)
    nota = "Em PT não há trasladação para segunda-feira"
    return [
        _fer("PT", None, d, n, F_CT_PT, LIC_DRE, nota)
        for d, n in [
            (dt.date(ano, 1, 1), "Ano Novo"),
            (p - dt.timedelta(days=2), "Sexta-feira Santa"),
            (p, "Domingo de Páscoa"),
            (dt.date(ano, 4, 25), "Dia da Liberdade"),
            (dt.date(ano, 5, 1), "Dia do Trabalhador"),
            (p + dt.timedelta(days=60), "Corpo de Deus"),
            (dt.date(ano, 6, 10), "Dia de Portugal, de Camões e das Comunidades Portuguesas"),
            (dt.date(ano, 8, 15), "Assunção de Nossa Senhora"),
            (dt.date(ano, 10, 5), "Implantação da República"),
            (dt.date(ano, 11, 1), "Dia de Todos os Santos"),
            (dt.date(ano, 12, 1), "Restauração da Independência"),
            (dt.date(ano, 12, 8), "Imaculada Conceição"),
            (dt.date(ano, 12, 25), "Natal"),
        ]
    ]


def festivos_oficiais(anos=(2026, 2027)):
    """ES (BOE) e PT (Código do Trabalho / DRE) para os anos pedidos. regiao NULL = nacional."""
    L = []
    for ano in sorted(set(anos)):
        L += festivos_es(ano) + festivos_pt(ano)
    return L
