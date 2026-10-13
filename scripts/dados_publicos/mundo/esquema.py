# -*- coding: utf-8 -*-
"""
Esquema ``mundo``: tabelas planas, uma por conjunto, com chave natural.

Os comentários das colunas vão para o Postgres (``COMMENT ON``) e o conector
Postgres do Sky lê-os como descrições — por isso estão escritos para quem
pergunta, não para quem programa.

Convenções:
- Datas/horas em UTC (``DateTime(timezone=True)``); datas civis em ``Date``.
- Preços em €/litro com 3 casas (``Numeric(6,3)``), como o MITECO publica.
- Nomes de cidades iguais aos da sementeira «Logística y Transporte»
  (``ops.routes.origin/destination``: Lisboa, Porto, Coimbra, Braga, Viseu,
  Badajoz, Mérida, Almendralejo, Sevilla, Madrid) para os JOIN funcionarem.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
)

ESQUEMA = "mundo"
meta = MetaData(schema=ESQUEMA)


def _preco(nome, comentario):
    return Column(nome, Numeric(6, 3, asdecimal=False), comment=comentario)


def _ts(nome, comentario, **kw):
    return Column(nome, DateTime(timezone=True), comment=comentario, **kw)


fontes = Table(
    "fontes",
    meta,
    Column("nome", Text, primary_key=True, comment="Identificador da fonte (usado em --so)"),
    Column("descricao", Text, comment="O que a fonte dá"),
    Column("url", Text, comment="Endereço oficial dos dados"),
    Column("licenca", Text, comment="Licença / termos de reutilização"),
    Column(
        "uso_comercial",
        Boolean,
        comment="True se os dados desta fonte que estão nas tabelas podem ser usados comercialmente",
    ),
    Column("atribuicao", Text, comment="Texto de atribuição a mostrar com o dado"),
    Column("frequencia", Text, comment="Cadência de refresco recomendada"),
    _ts("ultima_actualizacao", "Quando o carregador correu esta fonte pela última vez (UTC)"),
    _ts("dado_de", "Hora do dado segundo a própria fonte (UTC), quando a fonte a publica"),
    Column("linhas", Integer, comment="Linhas escritas na última corrida"),
    Column(
        "estado",
        Text,
        comment="ok | erro | sem_chave (fonte paga sem chave configurada: não correu, ficam as linhas anteriores) "
        "| termos_por_confirmar (não se pode guardar na base partilhada sky_world)",
    ),
    Column("erro", Text, comment="Mensagem de erro da última corrida (NULL se ok)"),
    Column("duracao_ms", Integer, comment="Duração da última corrida em milissegundos"),
    comment="Uma linha por fonte pública: frescura, licença e estado da última carga.",
)

gasolineras_precio = Table(
    "gasolineras_precio",
    meta,
    Column("id_estacion", Integer, primary_key=True, comment="IDEESS do MITECO"),
    Column("rotulo", Text, comment="Marca / rótulo do posto"),
    Column("direccion", Text),
    Column("cp", Text, comment="Código postal"),
    Column("localidad", Text),
    Column("municipio", Text),
    Column("provincia", Text, comment="Província (maiúsculas, como no MITECO)"),
    Column("cod_provincia", Text, comment="Código INE da província (06 = Badajoz)"),
    Column("lat", Float),
    Column("lon", Float),
    Column(
        "carretera", Text, comment="Estrada extraída da morada (heurística; NULL se não aparece)"
    ),
    Column("pk", Float, comment="Ponto quilométrico extraído da morada (heurística)"),
    Column("margen", Text, comment="Margem da via: D direita, I esquerda, N não aplicável"),
    Column("horario", Text),
    Column("tipo_venta", Text, comment="P = venda ao público, R = restringida"),
    _preco("precio_gasoleo_a", "Gasóleo A, €/l, preço de bomba publicado"),
    _preco("precio_gasoleo_premium", "Gasóleo Premium, €/l"),
    _preco("precio_gasoleo_b", "Gasóleo B (agrícola), €/l"),
    _preco("precio_gasolina_95", "Gasolina 95 E5, €/l"),
    _preco("precio_adblue", "AdBlue, €/l (poucos postos publicam)"),
    _ts(
        "actualizado_em",
        "Campo Fecha do MITECO (UTC). Atenção: é a hora do PEDIDO, não do preço; "
        "o MITECO refresca os preços de 30 em 30 min",
    ),
    Column("fonte", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Postos de combustível de Espanha (MITECO), preço actual. Preço de bomba, não de cartão de frota.",
)

gasolineras_rota = Table(
    "gasolineras_rota",
    meta,
    Column("origem", Text, primary_key=True, comment="Cidade de origem (= ops.routes.origin)"),
    Column(
        "destino", Text, primary_key=True, comment="Cidade de destino (= ops.routes.destination)"
    ),
    Column("id_estacion", Integer, primary_key=True, comment="FK gasolineras_precio.id_estacion"),
    Column("dist_km", Float, comment="Distância do posto ao traçado da rota (km, até 5)"),
    Column("km_desde_origem", Float, comment="Km aproximado da rota onde o posto fica"),
    _ts("calculado_em", "Quando a proximidade foi calculada (UTC)"),
    Column("fonte", Text, comment="MITECO (postos) + fonte do traçado da rota"),
    Column(
        "licenca",
        Text,
        comment="Licença do traçado usado (= rotas_referencia.licenca); demo-nao-comercial se veio do OSRM público",
    ),
    comment="Postos espanhóis a ≤5 km do traçado de cada rota da demo (traçado de rotas_referencia).",
)

gasoleo_historico_diario = Table(
    "gasoleo_historico_diario",
    meta,
    Column("data", Date, primary_key=True),
    Column("provincia", Text, primary_key=True, comment="Província em maiúsculas; ESPAÑA = total"),
    Column("n_postos", Integer, comment="Postos com preço de Gasóleo A nesse dia"),
    _preco("minimo", "Gasóleo A, mínimo do dia, €/l"),
    _preco("media", "Gasóleo A, média simples, €/l"),
    _preco("mediana", "Gasóleo A, mediana, €/l"),
    _preco("maximo", "Gasóleo A, máximo, €/l"),
    Column(
        "origem",
        Text,
        comment="historico (MITECO, 00:00 do dia) | actual (fotografia do dia corrente)",
    ),
    Column("fonte", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Gasóleo A por província e dia (MITECO).",
)

gasoleo_ue_semanal = Table(
    "gasoleo_ue_semanal",
    meta,
    Column("data", Date, primary_key=True, comment="Segunda-feira de referência do boletim"),
    Column("pais", Text, primary_key=True, comment="ES | PT | EU"),
    _preco("gasoleo_eur_l", "Gasóleo rodoviário, média nacional com impostos, €/l"),
    _preco("gasolina95_eur_l", "Euro-super 95, média nacional com impostos, €/l"),
    Column("fonte", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Weekly Oil Bulletin (Comissão Europeia): médias nacionais semanais. Única fonte aberta para PT.",
)

incidencias_trafico = Table(
    "incidencias_trafico",
    meta,
    Column("id", Text, primary_key=True, comment="situationRecord id do DATEX II"),
    Column("versao", Integer),
    Column("id_situacao", Text),
    Column("tipo", Text, comment="Tipo DATEX II (ex. RoadOrCarriagewayOrLaneManagement)"),
    Column("subtipo", Text, comment="Ex. narrowLanes, roadClosed, vehicleStuck"),
    Column("causa", Text, comment="causeType (ex. roadMaintenance, accident)"),
    Column("causa_detalhe", Text),
    Column("carretera", Text, comment="Ex. A-5, N-430"),
    Column("pk", Float, comment="Ponto quilométrico inicial"),
    Column("pk_fim", Float),
    Column("sentido", Text, comment="both | positive | negative | unknown"),
    Column("municipio", Text),
    Column("provincia", Text),
    Column("comunidade", Text),
    Column("lat", Float),
    Column("lon", Float),
    _ts("inicio", "Início (UTC)"),
    _ts("fim", "Fim previsto (UTC), se publicado"),
    Column("gravidade", Text, comment="severity / overallSeverity (highest, high, medium…)"),
    Column("estado", Text, comment="validityStatus: active | suspended…"),
    Column("activa", Boolean, comment="True se veio na última publicação"),
    _ts("actualizado_em", "publicationTime do feed (UTC)"),
    _ts("visto_em", "Última vez que o carregador a viu (UTC)"),
    Column("fonte", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Incidências DGT (DATEX II v3.7). Guardam-se 30 dias; activa=false quando saem do feed.",
)

festivos = Table(
    "festivos",
    meta,
    Column("chave", Text, primary_key=True, comment="pais|regiao|data (regiao NAC = nacional)"),
    Column("data", Date),
    Column("pais", Text, comment="ES | PT"),
    Column("regiao", Text, comment="ISO 3166-2 (ES-EX, ES-MD…); NULL = nacional"),
    Column("nome", Text, comment="Nome local"),
    Column("nome_en", Text),
    Column("dia_semana", Text, comment="seg…dom"),
    Column("nota", Text),
    Column("fonte", Text, comment="Diploma oficial (BOE / Diário da República), com referência"),
    Column("licenca", Text, comment="BOE — Licencia tipo BOE | DRE — legislação pública"),
    comment="Feriados nacionais e regionais ES (BOE) e nacionais PT (Código do Trabalho, DRE). Sem municipais.",
)

cambio_eur = Table(
    "cambio_eur",
    meta,
    Column("data", Date, primary_key=True, comment="Dia do fixing BCE (sem fins de semana)"),
    Column("moeda", Text, primary_key=True, comment="ISO 4217"),
    Column("taxa", Numeric(14, 6, asdecimal=False), comment="Unidades da moeda por 1 EUR"),
    Column("fonte", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Câmbios de referência do BCE (via Frankfurter), últimos 90 dias.",
)

tempo_cidades = Table(
    "tempo_cidades",
    meta,
    Column("cidade", Text, primary_key=True, comment="= ops.routes.origin/destination"),
    Column("data", Date, primary_key=True),
    Column("pais", Text),
    Column("lat", Float),
    Column("lon", Float),
    Column("temp_min", Float, comment="°C"),
    Column("temp_max", Float, comment="°C"),
    Column("precipitacao_mm", Float),
    Column("vento_max_kmh", Float),
    Column("rajada_max_kmh", Float),
    Column("codigo", Integer, comment="Código WMO"),
    Column("descricao", Text),
    _ts(
        "actualizado_em",
        "Hora do dado (UTC): «elaborado» da AEMET; no Open-Meteo, a hora do pedido (não publica a da corrida)",
    ),
    Column("licenca", Text),
    Column("fonte", Text),
    comment="Previsão diária 7 dias nas cidades das rotas da demo: AEMET (ES) e Open-Meteo com subscrição. Sem chave, não se carrega.",
)

portagens = Table(
    "portagens",
    meta,
    Column(
        "corredor", Text, primary_key=True, comment="Autoestrada / autovia (ex. A-5, A1, A2/A6)"
    ),
    Column("origem", Text, primary_key=True),
    Column("destino", Text, primary_key=True),
    Column(
        "classe", Text, primary_key=True, comment="ligeiro | pesado_2_3_eixos | pesado_4_mais_eixos"
    ),
    Column("pais", Text, primary_key=True),
    Column("km", Float),
    Column("preco_eur", Numeric(8, 2, asdecimal=False), comment="NULL = não verificado (ver nota)"),
    Column("gratuita", Boolean, comment="True se o troço não tem portagem"),
    Column("rota_demo", Boolean, comment="True se origem/destino é um par de ops.routes"),
    Column("valido_de", Date),
    Column("fonte", Text),
    Column("nota", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Portagens de referência (tabela manual, tarifas 2026). NULL quando não foi possível verificar.",
)

restricoes_pesados = Table(
    "restricoes_pesados",
    meta,
    Column("data", Date, primary_key=True),
    Column("carretera", Text, primary_key=True),
    Column("pk_inicio", Float, primary_key=True),
    Column("pk_fim", Float, primary_key=True),
    Column(
        "sentido", Text, primary_key=True, comment="Ambos sentidos | Entrada Madrid | Salida Madrid"
    ),
    Column("hora_inicio", Text, comment="HH:MM hora local"),
    Column("hora_fim", Text, comment="HH:MM hora local (24:00 = fim do dia)"),
    Column("troco", Text, comment="Descrição do troço"),
    Column("ambito", Text, comment="Veículos abrangidos"),
    Column("motivo", Text),
    Column("valido_de", Date),
    Column("valido_ate", Date),
    Column("confianca", Text, comment="lido_no_pdf | inferido_do_padrao"),
    Column("fonte", Text),
    Column("nota", Text),
    Column("licenca", Text, comment="Licença da fonte desta linha (ver fontes.licenca)"),
    comment="Restrições DGT 2026 a >7.500 kg (Anexo II), corredores da demo. Informativo; confirmar no BOE.",
)

rotas_referencia = Table(
    "rotas_referencia",
    meta,
    Column("origem", Text, primary_key=True, comment="= ops.routes.origin"),
    Column("destino", Text, primary_key=True, comment="= ops.routes.destination"),
    Column("km", Float, comment="Distância da rota (TomTom perfil camião; OSRM perfil automóvel)"),
    Column(
        "duracao_carro_min", Float, comment="Duração automóvel (só OSRM; NULL com TomTom camião)"
    ),
    Column(
        "conducao_camiao_min",
        Float,
        comment="Condução de camião: tempo TomTom perfil camião; com OSRM, km a 80 km/h",
    ),
    Column("pausas_45min", Integer, comment="Pausas obrigatórias de 45 min (Reg. 561/2006, 4h30)"),
    Column(
        "duracao_camiao_estimada_min",
        Float,
        comment="Condução + pausas de 45 min (Reg. 561/2006)",
    ),
    Column("geometria_json", Text, comment="Traçado simplificado [[lat,lon],…] (~1 ponto/km)"),
    _ts("actualizado_em", "Hora do pedido ao roteador (UTC)"),
    Column("fonte", Text),
    Column(
        "licenca",
        Text,
        comment="comercial (TomTom) | demo-nao-comercial (OSRM público, linhas antigas ou teste local)",
    ),
    Column("nota", Text),
    comment="Distância e tempo de referência para os pares origem–destino da demo.",
)

TABELAS = {
    t.name: t
    for t in (
        fontes,
        gasolineras_precio,
        gasolineras_rota,
        gasoleo_historico_diario,
        gasoleo_ue_semanal,
        incidencias_trafico,
        festivos,
        cambio_eur,
        tempo_cidades,
        portagens,
        restricoes_pesados,
        rotas_referencia,
    )
}
