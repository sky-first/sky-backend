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


# ── Feriados oficiais (tabela própria; o Nager.Date grátis é não-comercial) ──

F_BOE_2026 = (
    "BOE-A-2025-21667 — Resolución de 17/10/2025 de la Dirección General de Trabajo, fiestas laborales 2026 "
    "(BOE núm. 259, 28/10/2025): https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-21667"
)
F_RD_2001_1983 = (
    "Art. 45 RD 2001/1983 + art. 37.2 Estatuto de los Trabajadores (fiestas nacionales no sustituibles); "
    "resolución BOE 2027 ainda não publicada a 10/10/2026"
)
F_CT_PT = (
    "Código do Trabalho, art. 234.º (Lei 7/2009, redacção da Lei 8/2016), Diário da República: "
    "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2009-34546475"
)
LIC_OFICIAL = "oficial-reutilizavel (BOE: licencia tipo; DRE: legislação pública)"
_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _fer(pais, regiao, dia, nome, fonte, nota=None):
    d = dt.date.fromisoformat(dia)
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
        licenca=LIC_OFICIAL,
    )


def festivos_oficiais():
    """ES 2026 (BOE-A-2025-21667: nacionais + Extremadura, Madrid, Andalucía),
    ES 2027 (só nacionais não substituíveis, provisório), PT 2026–2027 (art. 234.º CT).

    regiao=None = nacional. As fiestas «**» do BOE (nacionais que cada CCAA
    pode substituir) vão por região, porque nem todas as CCAA as têm.
    """
    L = []
    # Espanha 2026 — nacionais não substituíveis («*» no anexo)
    for dia, nome in [
        ("2026-01-01", "Año Nuevo"),
        ("2026-04-03", "Viernes Santo"),
        ("2026-05-01", "Fiesta del Trabajo"),
        ("2026-08-15", "Asunción de la Virgen"),
        ("2026-10-12", "Fiesta Nacional de España"),
        ("2026-12-08", "Inmaculada Concepción"),
        ("2026-12-25", "Natividad del Señor"),
    ]:
        L.append(_fer("ES", None, dia, nome, F_BOE_2026))
    # Espanha 2026 — por comunidade («**» e «***» no anexo)
    comuns = [
        ("2026-01-06", "Epifanía del Señor", None),
        ("2026-04-02", "Jueves Santo", None),
        (
            "2026-11-02",
            "Lunes siguiente a Todos los Santos",
            "Todos los Santos (01/11) cai a domingo; trasladado",
        ),
        (
            "2026-12-07",
            "Lunes siguiente al Día de la Constitución",
            "06/12 cai a domingo; trasladado",
        ),
    ]
    proprias = {
        "ES-AN": [("2026-02-28", "Día de Andalucía")],
        "ES-EX": [("2026-09-08", "Día de Extremadura")],
        "ES-MD": [("2026-05-02", "Fiesta de la Comunidad de Madrid")],
    }
    for reg, extra in proprias.items():
        for dia, nome, nota in comuns:
            L.append(_fer("ES", reg, dia, nome, F_BOE_2026, nota))
        for dia, nome in extra:
            L.append(_fer("ES", reg, dia, nome, F_BOE_2026))
    # Espanha 2027 — provisório
    prov = "Provisório: resolução de fiestas laborales 2027 por publicar; regionais 2027 em falta"
    for dia, nome in [
        ("2027-01-01", "Año Nuevo"),
        ("2027-03-26", "Viernes Santo"),
        ("2027-05-01", "Fiesta del Trabajo"),
        ("2027-08-15", "Asunción de la Virgen"),
        ("2027-10-12", "Fiesta Nacional de España"),
        ("2027-11-01", "Todos los Santos"),
        ("2027-12-06", "Día de la Constitución Española"),
        ("2027-12-08", "Inmaculada Concepción"),
        ("2027-12-25", "Natividad del Señor"),
    ]:
        nota = prov + (" · cai a domingo" if dt.date.fromisoformat(dia).weekday() == 6 else "")
        L.append(_fer("ES", None, dia, nome, F_RD_2001_1983, nota))
    # Portugal — feriados obrigatórios (art. 234.º CT). Páscoa 2026: 05/04; 2027: 28/03.
    for ano, sexta, pascoa, corpo in [
        (2026, "2026-04-03", "2026-04-05", "2026-06-04"),
        (2027, "2027-03-26", "2027-03-28", "2027-05-27"),
    ]:
        for dia, nome in [
            (f"{ano}-01-01", "Ano Novo"),
            (sexta, "Sexta-feira Santa"),
            (pascoa, "Domingo de Páscoa"),
            (f"{ano}-04-25", "Dia da Liberdade"),
            (f"{ano}-05-01", "Dia do Trabalhador"),
            (corpo, "Corpo de Deus"),
            (f"{ano}-06-10", "Dia de Portugal, de Camões e das Comunidades Portuguesas"),
            (f"{ano}-08-15", "Assunção de Nossa Senhora"),
            (f"{ano}-10-05", "Implantação da República"),
            (f"{ano}-11-01", "Dia de Todos os Santos"),
            (f"{ano}-12-01", "Restauração da Independência"),
            (f"{ano}-12-08", "Imaculada Conceição"),
            (f"{ano}-12-25", "Natal"),
        ]:
            L.append(
                _fer("PT", None, dia, nome, F_CT_PT, "Em PT não há trasladação para segunda-feira")
            )
    return L
