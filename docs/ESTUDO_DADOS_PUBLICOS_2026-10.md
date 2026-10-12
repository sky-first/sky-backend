# Estudo de viabilidade — "Dados do mundo" no Sky (logística Ibéria)

Data: 10/10/2026 · Âmbito: transporte, logística e distribuição em Espanha e Portugal · Estado: estudo, sem código

> Pergunta: o Sky pode responder a "que tempo faz amanhã na A-5?", "quanto demoro de Badajoz a Madrid com um camião de 40 t?" ou "onde está o gasóleo mais barato no caminho?" sem dados do cliente?
> **Resposta curta: sim, e a maior parte é gratuita.** Há três armadilhas: licenças "só não-comercial" (Open-Meteo, ORS, GraphHopper e possivelmente IPMA), Portugal sem API oficial de combustíveis nem de incidentes, e responsabilidade pelas respostas legais.

---

## 1. Catálogo de fontes

Legenda de risco: 🟢 baixo · 🟡 médio · 🔴 alto. Preços verificados na web a 10/10/2026. Onde não foi possível confirmar, diz "a confirmar".

### 1.1 Tempo, calendário, feriados

| Fonte | O que dá | Licença / uso comercial | Custo | Limites | Frescura | Risco |
|---|---|---|---|---|---|---|
| Relógio do servidor + `zoneinfo` | Data, hora e fuso (Europe/Madrid, Europe/Lisbon, Atlantic/Canary, Atlantic/Azores) | n/a | 0 € | n/a | Tempo real | 🟢 |
| [Nager.Date](https://date.nager.at) | Feriados nacionais e regionais (campo `counties`, ex. ES-MD, PT-?) | Código MIT; termos da API pública não confirmados | 0 € | Sem limite declarado | Anual | 🟡 Cobertura regional ES incompleta; **feriados municipais PT/ES não existem** |
| BOE / DRE (fonte oficial) | Calendário laboral oficial ES (resolução anual) e feriados PT | Dados públicos | 0 € | — | Anual | 🟢 Carregar 1×/ano à mão ou por script |

**Recomendação:** tabela própria `feriados` (país, região, município, data) semeada com Nager.Date e corrigida a partir do BOE/DRE. São ~200 linhas/ano por país. Nada de chamada ao vivo.

### 1.2 Meteorologia

| Fonte | O que dá | Licença / uso comercial | Custo | Limites | Risco |
|---|---|---|---|---|---|
| [Open-Meteo](https://open-meteo.com/en/pricing) | Previsão horária 16 dias por coordenada, histórico, todo o mundo. JSON limpo, sem chave no plano grátis | Grátis **só não-comercial** ([termos](https://open-meteo.com/en/terms)); dados CC BY 4.0 | Grátis: 10.000/dia. Standard (1 M/mês, comercial) e Professional (5 M/mês): preço só no portal; terceiros indicam ~29–99 $/mês ([Substack](https://openmeteo.substack.com/p/api-subscriptions-for-commercial)) | 10k/dia, 5k/h, 600/min | 🟢 Técnico; 🟡 tem de se pagar em produção |
| [AEMET OpenData](https://opendata.aemet.es) | Previsão municipal ES, avisos (Meteoalerta), observação | Reutilização **comercial permitida** com atribuição ([catálogo](https://www.aemet.es/es/datos_abiertos/catalogo), [nota legal](https://www.aemet.es/es/nota_legal)) | 0 € (chave por email) | Não publicado; API de 2 passos (pede URL, depois descarrega) e instável | 🟡 Qualidade da API |
| [IPMA](https://api.ipma.pt) | Previsão 5 dias por capital de distrito/concelho, avisos | Pública, sem chave; termos comerciais **ambíguos** ("direitos reservados" vs CC BY no catálogo de Lisboa) | 0 € | n/d | 🟡 Licença a confirmar por email ao IPMA |

**Recomendação:** Open-Meteo pago (plano Standard) como motor único de previsão por coordenada ao longo da rota. AEMET/IPMA apenas para **avisos oficiais** (vento, neve, nevoeiro), que é onde dão valor que o Open-Meteo não dá.

### 1.3 Rotas e tempo de viagem para camião

| Fonte | Perfil camião (peso, altura, eixos, ADR) | Uso comercial | Custo | Limites | Risco |
|---|---|---|---|---|---|
| [OSRM](https://project-osrm.org) self-hosted | Não nativo (só perfil car adaptado) | Sim (BSD; dados OSM ODbL) | Só infra (~1 VM 32–64 GB p/ Ibéria) | Os nossos | 🟡 Sem restrições de camião = respostas erradas |
| [openrouteservice](https://openrouteservice.org/plans/) | `driving-hgv` com peso/altura/largura | API grátis: 2.000 rotas/dia, 40/min; termos comerciais ambíguos e sem suporte comercial grátis ([restrições](https://openrouteservice.org/restrictions/)) | 0 € API; self-host grátis | 2.000/dia | 🟡 Self-host resolve limites e licença |
| [GraphHopper](https://www.graphhopper.com/pricing/) | `truck` nos planos pagos | Grátis só não-comercial | Premium ~384 €/mês (50k créditos/dia); planos base a confirmar | Por créditos | 🟡 Caro para o volume |
| [TomTom Routing](https://developer.tomtom.com/pricing) | `travelMode=truck`, `vehicleCommercial`, peso por eixo, ADR, **trânsito em tempo real** | **Freemium permite uso comercial** | 2.500 pedidos/dia grátis (partilhados por todas as APIs); depois 0,75 $/1.000 | Sem limite diário no Pay As You Grow | 🟢 Melhor relação custo/qualidade |
| [HERE Routing v8](https://developer.here.com/pricing) | Camião completo + portagens na mesma resposta | Sim | Free tier citado por terceiros (250k/mês, 1.000/dia "Limited"); preço camião não publicado | — | 🟡 Preço opaco |
| [Google Routes](https://developers.google.com/maps/billing-and-pricing/pricing) | **Sem perfil de camião** | Sim | 5–15 $/1.000 após 1–10k grátis/mês | — | 🔴 Não serve para camião |

**Recomendação:** TomTom para MVP (comercial no plano grátis, perfil de camião, trânsito incluído, 2.500/dia chega para dezenas de clientes). Plano B: ORS self-hosted quando o volume justificar. Google fora.

### 1.4 Combustível

| Fonte | O que dá | Licença | Custo | Frescura | Risco |
|---|---|---|---|---|---|
| ES — [MITECO Geoportal Gasolineras, REST](https://www.datos.gob.es/es/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas) (`sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/`) | Todas as ~12.000 estações ES com coordenadas, horário e preço por produto (Gasóleo A, Gasóleo Premium, AdBlue não) | Dados abertos, reutilização comercial | 0 € | Várias vezes/dia | 🟢 JSON com vírgulas decimais; não há pedido por estação → descarregar tudo (~10 MB) |
| PT — [DGEG Preços dos Combustíveis Online](https://precoscombustiveis.dgeg.gov.pt) | Preço por posto em Portugal continental (obrigação legal, DL 243/2008) | **Sem API documentada nem licença publicada** | 0 € | Diária | 🔴 Endpoints internos não oficiais; pedir acesso formal a estatistica@dgeg.pt |
| ES/PT — Boletim Petrolífero UE ([Weekly Oil Bulletin](https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en)) | Médias nacionais semanais de gasóleo | Aberta | 0 € | Semanal | 🟢 Para tendências |

**Nota de produto:** postos de camião (bombas de alto débito, cartões de frota Solred/Galp Frota/DKV) não estão marcados no dataset público. O preço de bomba ≠ preço que a frota paga com desconto do cartão. Dizer isto na resposta.

### 1.5 Portagens

| Fonte | Cobertura | Custo | Risco |
|---|---|---|---|
| [HERE Routing](https://developer.here.com/pricing) com `return=tolls` | ES + PT, por classe de veículo | Incluído no pedido de rota | 🟡 |
| [TollGuru API](https://tollguru.mapup.ai/toll-calculator-europe) | ES + PT, camiões até 9 eixos | ~40–2.000 $/mês ([GetApp](https://www.getapp.com/transportation-logistics-software/a/tollguru/)) | 🟡 Preço por confirmar |
| Tabela própria | ES: poucas autopistas ainda com portagem ([lista oficial](https://administracion.gob.es/pag_Home/es/Tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas)), subida 3,64–4,68% em 2026 ([Bolsamanía](https://www.bolsamania.com/noticias/empresas/economia--transportes-aprueba-la-actualizacion-de-los-peajes-de-las-autopistas-para-2026-con-un-alza-de-hasta-el-468--21439215.html)). PT: Brisa/IP/concessões, ex-SCUT em mudança | Trabalho manual anual | 🟡 |

Badajoz–Madrid pela A-5 é autovía sem portagem — exemplo bom para demo, porque a resposta certa é "0 €".

### 1.6 Trânsito, incidentes, restrições

| Fonte | O que dá | Licença | Frescura | Risco |
|---|---|---|---|---|
| [DGT NAP — Incidencias DATEX2 v3.7](https://nap.dgt.es/en/dataset/incidencias-dgt-datex2-v3-7) | Incidentes, obras, cortes na rede estatal (exceto País Basco e Catalunha) | Gratuita (Reg. UE 886/2013, [SRTI](https://nap.dgt.es/en/dataset/incidencias-de-trafico-srti-en-formato-lod-datex-ii)) | 1 min | 🟢 Os feeds antigos foram descontinuados a 12/01/2026 — usar v3.7 |
| País Basco ([DT-GV](https://nap.dgt.es/en/dataset/incidencias-dt-gv)) e Catalunha (SCT) | Idem, regional | Licenças próprias | 5–9 min | 🟡 |
| PT — Infraestruturas de Portugal / NAP IMT | Existe obrigação UE, mas **não encontrei feed DATEX II público** | — | — | 🔴 Lacuna; usar trânsito TomTom |
| [DGT — restrições a pesados 2026](https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/estado-del-trafico/restricciones/2026/report_Resolucion_DGT_Medidas_circulacion-2026-copia.pdf) | Dias/horas/troços proibidos a >7,5 t, ADR, proibição de ultrapassar (novo 3.1) | Pública (BOE) | Anual + resoluções avulsas (ex. [BOE-A-2026-16665](https://www.boe.es/boe/dias/2026/07/31/pdfs/BOE-A-2026-16665.pdf), eclipse) | 🟡 PDF → tabela à mão; resoluções regionais à parte |
| PT — restrições a pesados (IMT, feriados/épocas) | Sobretudo ADR e pontes (25 de Abril) | Pública | Pontual | 🟡 |

### 1.7 Conhecimento legal estático

| Tema | Fonte | Formato no Sky |
|---|---|---|
| Tempos de condução e repouso | [Reg. (CE) 561/2006](https://eur-lex.europa.eu/eli/reg/2006/561/oj) + Pacote Mobilidade (Reg. 2020/1054): 9 h/dia (10 h 2×/semana), 56 h/semana, 90 h/2 semanas, pausa 45 min após 4h30, repouso diário 11 h (9 h reduzido 3×) | Documento curado + regras como funções determinísticas |
| Tacógrafo | Reg. (UE) 165/2014 | Documento curado |
| Portagens, ADR, dimensões | BOE / DRE | Documento curado com data de revisão |

Não deixar o LLM "lembrar-se" disto. Texto curado, com data e link, citado na resposta.

### 1.8 Câmbio, macro, geocodificação

| Fonte | O que dá | Licença | Custo / limites | Risco |
|---|---|---|---|---|
| [BCE Data Portal (EXR)](https://data.ecb.europa.eu) / [Frankfurter](https://frankfurter.dev) | Câmbios de referência diários (16h CET), sem fim-de-semana | Reutilização livre com atribuição | 0 €, sem chave | 🟢 |
| [INE ES](https://www.ine.es/dyngs/DataLab/manual.html?cid=45) / [INE PT](https://www.ine.pt) / [Eurostat API](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access) | IPC, índices de transporte, produção industrial | Abertas | 0 € | 🟢 Valor baixo para o camionista, alto para o diretor financeiro |
| Nominatim público | Morada → coordenadas | **Máx. 1 pedido/s, proibido uso pesado, acesso pode ser retirado a apps comerciais** ([política](https://operations.osmfoundation.org/policies/nominatim/)) | 0 € | 🔴 Não usar em produção |
| Geocoding TomTom/HERE, ou Nominatim/Photon self-hosted | Idem | Comercial | Dentro dos 2.500/dia TomTom | 🟢 |

---

## 2. Arquitetura

### Ponto de partida (trivial, fazer já)
Injetar em **todos** os prompts (texto, agentes agendados e voz Nova Sonic):

```
Agora: 2026-10-10T14:32 Europe/Madrid (sábado). Utilizador: fuso Europe/Lisbon, país PT.
```

Resolve "que dia é hoje", "ontem", "esta semana", "dia útil?" (com a tabela de feriados). Custo zero, ~30 tokens. Lembrete: os dados de demonstração acabam a 01/08/2026 — sem data correta no prompt, "ontem" já falha hoje.

### Opções

| | (a) Ferramentas ao vivo (function calling) | (b) Dataset partilhado read-only, refrescado por jobs | (c) Híbrido |
|---|---|---|---|
| Como funciona | O LLM chama `get_weather(lat,lon,date)`, `route_truck(...)` | Celery Beat descarrega para schema `world_es` / `world_pt` numa base partilhada; o sky-ai gera SQL como faz para os dados do cliente | Dados lentos em tabelas; dados por pedido em ferramentas |
| Encaixe no Sky atual | Novo: o caminho de texto gera SQL, não tem ciclo de tools genérico | **Natural**: é só mais uma "ligação" com metadata/glossário | Ambos |
| Cruzar com dados do cliente ("entregas de amanhã com chuva") | Difícil: o LLM tem de juntar em memória | **Fácil: JOIN em SQL** | Fácil para o que está em tabela |
| Rotas por pedido (origem/destino arbitrários) | Sim | **Impossível** pré-calcular | Sim |
| Latência voz (Nova Sonic) | 1 chamada externa extra (~300–800 ms) | Consulta local rápida | Ok |
| Custo | Por pergunta (escala com uso) | Fixo (jobs) | Controlado |
| Multi-tenant (BD dedicada por cliente) | Sem impacto | Dados **não** vão para cada BD de cliente: 1 base partilhada read-only, ligada a todos os tenants como ligação de sistema | Idem |

### Recomendação: (c) híbrido

**Em tabelas (job, base partilhada `sky_world`, read-only para o sky-ai):**
- Feriados ES/PT; restrições a pesados DGT; regras 561/2006 (como tabela de parâmetros).
- Preços combustível ES (refresh 2–4×/dia, guardar histórico → dá "tendência" de graça); PT quando houver acesso.
- Câmbios BCE (diário); séries INE/Eurostat (mensal).
- Incidentes DGT (refresh 5 min, guardar só ativos + 30 dias).
- Previsão meteorológica para **uma grelha fixa**: capitais de província/distrito + nós dos principais corredores (A-5, A-4, A-2, A-1, A-6, AP-7, A1, A2, A6, IP2...). ~150 pontos × 1 chamada/h = 3.600/dia, dentro do Open-Meteo.

**Em ferramentas (ao vivo):**
- `route_truck(origem, destino, veículo, hora_partida)` → TomTom: distância, duração com trânsito, polilinha.
- `weather_along_route(polilinha, hora_partida)` → amostra pontos e cruza com Open-Meteo.
- `fuel_along_route(polilinha, raio_km, produto)` → consulta à tabela de combustíveis com PostGIS `ST_DWithin` (rápida, sem chamada externa).
- `geocode(texto)` → TomTom.

Porquê: o que é igual para todos os clientes e muda devagar fica em SQL (barato, cruzável com dados do cliente, já é o caminho que o sky-ai sabe fazer). O que depende de origem/destino arbitrários não pode ser pré-calculado. A voz já tem um `toolSpec` (`voz_fala_a_fala.py`): acrescentar 2–3 ferramentas ao mesmo canal, com resultado em **JSON** (prosa no toolResult fecha o canal do Sonic — já aprendido).

Riscos de arquitetura:
- A base partilhada **não pode** herdar o filtro por equipa/projeto como se fosse dado do cliente; tratá-la como ligação de sistema visível a todos, sem escrita.
- O sky-ai atual escolhe uma ligação por pergunta; para JOIN entre "entregas do cliente" e "sky_world" é preciso: (i) foreign data wrapper / schema anexado na BD do tenant, ou (ii) duas consultas e junção em Python. Recomendo (ii) no MVP; (i) depois.

---

## 3. Produto e empacotamento

### Incluído em todos os planos (custo marginal ~0)
Data/hora/fuso · feriados · restrições DGT · regras 561/2006 · combustíveis ES (e PT se a DGEG autorizar) · câmbios BCE · INE/Eurostat · incidentes DGT · tempo na grelha de corredores.

### Add-on "Sky Rota" (custo variável)
Rotas de camião com trânsito, tempo ao longo da rota, combustível ao longo da rota, portagens, geocodificação. Custo estimado: TomTom 0,75 $/1.000 após 2.500/dia grátis + Open-Meteo Standard + eventual TollGuru/HERE. A 0,03 €/pergunta de LLM, uma pergunta de rota fica em ~0,035 €. Proposta: incluído com quota (ex. 300 rotas/mês no Pro, ilimitado-justo no Enterprise), ou +50–100 €/mês no Starter. **Medir antes de fixar preço.**

### Marketing
- Nome: "O Sky já sabe o mundo — tu só lhe dás a tua empresa."
- Mostrar sempre a fonte e a hora do dado ("Fonte: MITECO, atualizado 13:05"). Vende confiança e protege juridicamente.
- Não prometer "o mais barato": prometer "o mais barato publicado no Geoportal oficial".

### 10 perguntas "uau"

| # | Pergunta | Fontes |
|---|---|---|
| 1 | "Saio de Badajoz para Madrid amanhã às 6h com um 40 t. A que horas chego e preciso de parar?" | TomTom truck + regra 561 (4h30 → pausa 45 min) + data |
| 2 | "Onde abasteço mais barato entre Mérida e Madrid, a menos de 2 km da A-5?" | TomTom (polilinha) + MITECO |
| 3 | "Vai chover ou haver vento forte no meu percurso de amanhã?" | Open-Meteo ao longo da rota + avisos AEMET |
| 4 | "Posso circular com o semirreboque na N-V no domingo, 12 de outubro?" | Restrições DGT + feriados (12/10 é feriado nacional ES) |
| 5 | "Há acidentes ou obras agora na A-4 entre Madrid e Despeñaperros?" | DGT DATEX2 v3.7 |
| 6 | "Quanto gastei a mais em gasóleo este trimestre face à média de Espanha?" | Dados do cliente + histórico MITECO / Weekly Oil Bulletin |
| 7 | "Quais das entregas de amanhã caem em feriado local no destino?" | Dados do cliente + tabela feriados (regionais) |
| 8 | "Quanto pago de portagens de Lisboa a Valência com 5 eixos?" | HERE/TollGuru |
| 9 | "Quanto vale em euros a fatura de 12.000 USD do cliente marroquino, ao câmbio de hoje?" | BCE + dados do cliente |
| 10 | "O motorista X fez 10 h ontem — está dentro da lei?" | Dados de tacógrafo do cliente + regras 561/2006 |

---

## 4. Esforço e fases

| Fase | Duração | Conteúdo | Custo mensal externo |
|---|---|---|---|
| **0** | 1 dia | Data/hora/fuso em todos os prompts (texto, agentes, voz) + teste "que dia é hoje" nos 3 caminhos | 0 € |
| **1 — MVP** | 1–2 semanas (1 dev) | Base `sky_world` + jobs Celery: feriados ES/PT, combustíveis MITECO (com histórico), câmbios BCE, incidentes DGT. Registo como ligação de sistema com glossário e descrições de colunas. 10 perguntas de teste por fonte | 0 € |
| **2 — Rota** | 2–3 semanas | Ferramentas `route_truck`, `geocode`, `fuel_along_route` (TomTom + PostGIS), tempo ao longo da rota (Open-Meteo pago), ferramentas no canal Nova Sonic | ~30–100 €/mês |
| **3 — Legal e restrições** | 1–2 semanas | Restrições DGT 2026 em tabela; documento 561/2006 + tacógrafo curado e revisto por jurista; aviso na resposta | Revisão jurídica pontual |
| **4 — Portugal completo** | Depende de terceiros | Acordo DGEG para preços; IPMA (licença); incidentes PT; portagens (HERE/TollGuru) | 0–200 €/mês |

### Riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Usar plano grátis "não-comercial" em produção (Open-Meteo, ORS, GraphHopper) | Alta se não houver regra | Alto (licença) | Lista de fontes aprovadas; Open-Meteo pago desde o 1.º cliente |
| DGEG sem API oficial → scraping | Alta | Médio (bloqueio, ilegalidade) | Pedido formal; até lá, PT só com médias semanais UE |
| Resposta legal errada (tempos de condução, restrições) → multa ao cliente | Média | Alto (responsabilidade) | Texto curado, citação obrigatória, aviso "informativo, não substitui o tacógrafo", cláusula nos termos de serviço |
| LLM inventa dado do mundo quando a fonte falha | Média | Alto (confiança) | Ferramenta devolve erro explícito; prompt obriga a dizer "não consegui obter" |
| Explosão de custos (agentes agendados a pedir rotas em ciclo) | Média | Médio | Quota por tenant, cache de rotas (origem/destino/hora arredondada, 15 min), alerta a 80% |
| APIs públicas instáveis (AEMET, MITECO) | Alta | Baixo (há tabela em cache) | Servir último valor com carimbo de hora |
| Feriados municipais em falta | Alta | Baixo | Assumir explicitamente "feriados nacionais e regionais" |
| Precisão "mais barato" vs preço real de frota | Alta | Médio | Dizer "preço de bomba publicado"; mais tarde, importar tabela do cartão de frota do cliente |

---

## Fontes principais
- Open-Meteo: https://open-meteo.com/en/pricing · https://open-meteo.com/en/terms
- AEMET: https://www.aemet.es/es/datos_abiertos/catalogo · https://www.aemet.es/es/nota_legal
- IPMA: https://api.ipma.pt
- MITECO carburantes: https://www.datos.gob.es/es/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas
- DGEG: https://precoscombustiveis.dgeg.gov.pt
- openrouteservice: https://openrouteservice.org/plans/ · https://openrouteservice.org/restrictions/
- TomTom: https://developer.tomtom.com/pricing
- HERE: https://developer.here.com/pricing
- Google Maps Platform: https://developers.google.com/maps/billing-and-pricing/pricing
- GraphHopper: https://www.graphhopper.com/pricing/
- DGT NAP: https://nap.dgt.es/en/dataset/incidencias-dgt-datex2-v3-7
- DGT restrições 2026: https://www.dgt.es/export/sites/web-DGT/.galleries/downloads/estado-del-trafico/restricciones/2026/report_Resolucion_DGT_Medidas_circulacion-2026-copia.pdf
- Portagens ES: https://administracion.gob.es/pag_Home/es/Tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas
- TollGuru: https://tollguru.mapup.ai/toll-calculator-europe
- Frankfurter / BCE: https://frankfurter.dev · https://data.ecb.europa.eu
- Nominatim: https://operations.osmfoundation.org/policies/nominatim/
- Nager.Date: https://date.nager.at
- Reg. 561/2006: https://eur-lex.europa.eu/eli/reg/2006/561/oj

### Por confirmar antes de decidir
1. Preço atual Open-Meteo Standard (portal do cliente).
2. Termos comerciais IPMA e DGEG (email formal).
3. Preço HERE/TollGuru para portagens de camião ES+PT.
4. Existência de feed DATEX II público da Infraestruturas de Portugal.
5. Estado atual das portagens ex-SCUT em Portugal.

---

## Anexo A — Provas com scripts (10/10/2026)

Scripts em `sky-poc-backend/scripts/dados_publicos/` (stdlib + `requests`, sem chaves). Correr com `.venv\Scripts\python.exe <script>.py`. Saída real de 10/10/2026, ~18:35 (hora de Madrid). Latências medidas a partir do portátil, em Portugal.

| Script | Fonte | Resultado | Latência | Estado |
|---|---|---|---|---|
| `miteco_gasoleo_a5.py` | MITECO REST (províncias 06, 10, 45, 28) | 1.543 postos com Gasóleo A; dado de 10/10/2026 18:35. **≤15 km de Badajoz (38 postos):** 1,780–2,169 €/l (spread 38,9 cênt.). **≤3 km da rota (269 postos):** mín 1,689 (Petroprix/Ballenoil, Móstoles) · mediana 1,949 · máx 2,169 €/l. Mais barato por troço: 0–100 km 1,720 (El Prado) · 100–200 1,769 (Navalmoral) · 200–300 1,739 (Casarrubios) · 300–400 1,689 (Móstoles). 600 l no mais barato vs mais caro = **288 €** | 4,8–6,5 s (4 pedidos, ~300 KB cada) | ✅ |
| `osrm_rota_badajoz_madrid.py` | OSRM demo (router.project-osrm.org) | **402,8 km · 4h28** (automóvel). Estimativa camião (heurística 78 km/h + 1 pausa de 45 min, Reg. 561/2006): 5h10 de condução → **5h55, chegada ~11:55** saindo às 06:00. openrouteservice sem chave: **HTTP 401 "Authorization field missing"** → exige chave gratuita (não testado) | 0,8–2,8 s | ✅ OSRM · ❌ ORS sem chave |
| `feriados_es_pt.py` | Nager.Date v3 | 11/10/2026 (domingo) não é feriado em ES/Extremadura/Madrid/PT, **mas é véspera da Fiesta Nacional (12/10)**. Próximos: ES 12/10, 01/11 e 06/12 (**ambos a domingo → as trasladações regionais não aparecem na API**), 08/12; PT 01/11, 01/12, 08/12 | 0,6–0,7 s | ✅ (lacunas: trasladações e municipais) |
| `bce_cambios.py` | BCE Data Portal SDMX (EXR) | 1 EUR = **1,1206 USD** · **0,8476 GBP** (referência de 09/10/2026; ao fim de semana não há fixing). 12.000 USD = **10.708,55 €**. **MAD: série parada desde 30/10/2020 ("Indicative rate")** → o BCE não serve para o dirham | ~1,0 s | ✅ USD/GBP · ❌ MAD |
| `openmeteo_tempo_rota.py` | Open-Meteo (7 pontos num só pedido) | Partida 11/10 06:00: 10–14 °C, pouco nublado a encoberto, 0,0 mm, rajada máx. 9 km/h, visibilidade ≥20 km → sem alertas | 1,0–6,6 s (variável) | ✅ técnico · ⚠ licença não-comercial |
| `dgt_incidencias_a5.py` | DGT NAP DATEX2 v3.7 (XML 3,2 MB) | 732 registos ativos em ES. **A-5: 1** (obstáculo/veículo parado, PK 332,5, Trujillanos, desde 18:30). Província de Badajoz: 4 (2 obras na BA-075 desde 29/06; 2 obstáculos). ≤1 km da rota: 3 (A-5 Trujillanos, A-42 Madrid, M-40 Leganés — as duas últimas são estradas que cruzam; filtrar por estrada) | 0,7–4,0 s | ✅ |
| `demo_badajoz_madrid.py` | As 5 acima, em paralelo | Resposta completa a "Voy de Badajoz a Madrid mañana a las 6 con un camión…" (abaixo) | **8,7–9,1 s total** | ✅ |

AEMET não foi testada: exige chave (pedida por email). Fica para a fase 1, só para avisos oficiais.

**Saída do `demo_badajoz_madrid.py` (resumo):**
> 🚛 403 km pela A-5 (sem portagens). Ligeiro 4h28; camião ~5h10 + 1×45 min → chegada ~11:54.
> ⛽ Mais barato a ≤3 km da rota: 1,689 €/l Petroprix / Ballenoil (Móstoles, 24 h). Diferença na rota: 48 cênt./l (≈288 € em 600 l).
> 🌦 10–14 °C, encoberto/pouco nublado, sem chuva, rajada máx. 9 km/h. Sem alertas.
> 📅 11/10 não é feriado; ⚠ véspera de feriado nacional (12/10) e domingo → confirmar restrições DGT a pesados.
> 🚧 3 incidências DGT a ≤1 km da rota (A-5 PK 332, Trujillanos — obstáculo desde 18:30).

**O que as provas mudam no estudo:**
1. **Latência para voz:** 9 s em paralelo é demasiado para o Nova Sonic. MITECO (≈6 s, 4 pedidos) e DGT (XML de 3 MB) têm de vir de tabela local (`sky_world`, refresh por job), como já recomendado no §2. Ao vivo, só rota + tempo (~1–3 s). O cálculo "postos a ≤3 km da rota" em Python puro leva ~2,3 s → em produção, PostGIS `ST_DWithin` (milissegundos).
2. **Câmbio MAD:** não existe no BCE desde 2020. Para clientes com Marrocos é preciso outra fonte (Bank Al-Maghrib) ou fornecedor pago — junta-se à lista "por confirmar".
3. **Feriados:** a API não aplica as trasladações de 01/11 e 06/12/2026 (domingos). Confirma a recomendação de tabela própria corrigida pelo BOE.
4. **Incidências:** o filtro "perto da rota" apanha estradas que cruzam a rota; filtrar também pelo nome da estrada (A-5).
5. **TomTom (correção ao §1.3):** a página de preços atual ([docs.tomtom.com/pricing](https://docs.tomtom.com/pricing)) mostra o free tier do Routing como **20.000 pedidos/mês** (não 2.500/dia) e Traffic Incidents **2.500/mês**. Há tabela de preços nova ([anúncio](https://docs.tomtom.com/pricing/price-announcement)). O preço de 0,75 $/€ por 1.000 continua a ser citado, mas **não aparece na página** — confirmar. O free tier é por conta (a nossa), partilhado por todos os clientes.

---

## Anexo B — APIs pagas do sector

Dois modelos de integração:
- **Conta do cliente (BYO):** o cliente já paga ao fornecedor; nós só ligamos a API à conta dele. Custo externo 0 para nós; o trabalho é integrar e manter.
- **Revenda:** o contrato é nosso, pagamos o consumo e cobramos no add-on.

| Fornecedor / API | O que acrescenta ao Sky | Modelo de preço (indicativo) | BYO / Revenda | Relevância Ibéria | Esforço | Fonte |
|---|---|---|---|---|---|---|
| **TomTom Routing (camião) + Traffic** | Rota de camião (peso, eixos, ADR), ETA com trânsito real | Free 20K rotas/mês e 2,5K incidências/mês; depois ~0,75 $/1.000 (a confirmar) | Revenda | Alta | Baixo (REST) | [docs.tomtom.com/pricing](https://docs.tomtom.com/pricing) |
| **HERE Routing v8 (camião + portagens)** | Rota de camião **e portagens na mesma resposta** | Camião: 0–5K grátis; 2,75 $/1.000 até 200K; +6 % desde 01/04/2026 em contratos novos | Revenda | Alta (ES+PT) | Baixo | [developers.here.com/plans](https://developers.here.com/plans) |
| PTV Developer | Routing de camião de referência na Europa; otimização de rotas | Sob proposta (2021: grátis até 100K transações/mês — desatualizado) | Revenda | Média | Médio | [ptvlogistics.com](https://www.ptvlogistics.com/en/product_description_ptv_developer) |
| Google Routes | ETA ligeiros, geocodificação | 5–15 $/1.000 | — | **Sem perfil camião → não serve** | — | estudo §1.3 |
| **TollGuru** | Portagens ES+PT por classe/eixos, com IVA | 80 $/5K transações · 260 $/20K · 900 $/100K (1 rota ≈ 5 transações) | Revenda | Média (A-5 sem portagens; PT sim) | Baixo | [tollguru.mapup.ai](https://tollguru.mapup.ai/toll-api-pricing-plans) |
| Via-T / Bip&Drive / Via Verde | Gasto real de portagens do cliente | Sem API pública encontrada → importar extrato CSV | BYO (ficheiro) | Alta | Baixo | a confirmar |
| **Solred (Repsol) — API Movimentos** | **Litros, €, posto e cartão/matrícula por transação** → custo/km e custo/motorista reais | Sem custo publicado (área "Mi Solred"); REST + OAuth2 | BYO | **Muito alta (líder em ES)** | Médio | [repsol.es — API Movimentos](https://www.repsol.es/autonomos-y-empresas/solred/mi-solred/api-movimientos/) |
| DKV, UTA Edenred, Moeve StarRessa, Galp Frota | Idem | **Sem API pública encontrada**; portais com exportação | BYO (CSV/XLS, ou parceria) | Alta | Baixo (ficheiro) / Alto (parceria) | [UTA](https://web.uta.com/en/fuel-card) · [StarRessa](https://starressa.moeveglobal.com/en/products-and-services/starressa-cards) |
| **Webfleet (Bridgestone) — WEBFLEET.connect** | Posições, km, viagens, consumo, estilo de condução, tacógrafo | API para clientes; telemática ~15–35 €/veículo/mês | BYO | Muito alta | Médio | [webfleet.com — integration](https://www.webfleet.com/webfleet/partners/integration) |
| **Geotab (MyGeotab SDK)** | Idem + dados do motor (CAN) | SDK grátis; cliente paga ~30–40 $/veículo/mês | BYO | Alta (via revendedores) | Médio | [geotab.com](https://www.geotab.com/uk/fleet-management-solutions/software-integration/) |
| Verizon Connect Reveal (inclui **Movildata**) | Idem; Movildata tem ~1.900 clientes em ES | Credenciais por cliente via Marketplace | BYO | Alta em ES | Médio-alto (acesso burocrático) | [CCJ](https://www.ccjdigital.com/business/article/14936351/verizon-telematics-acquires-movildata-to-expand-in-europe) · [supergood](https://supergood.ai/docs/verizon-connect-api) |
| Frotcom (Frotcom Lusitana) | Idem; forte em PT; já integra Shippeo, FourKites, TIS-Web | API existe, sem documentação pública | BYO | Alta em PT | Médio | [frotcom.com](https://www.frotcom.com/blog/2021/07/jani-co-logistic-optimizes-fleet-productivity-using-frotcoms-api) |
| Samsara | Idem | API para todos os clientes; 200 pedidos/s | BYO | Baixa na Ibéria | Médio | [developers.samsara.com](https://developers.samsara.com/changelog/new-endpoint-level-rate-limits-starting-october-23rd) |
| Michelin Connected Fleet (ex-Masternaut), Inelo/Optidrive | Idem | Não verificado | BYO | Média | a confirmar | — |
| Tacógrafo (VDO TIS-Web, TachoMaster, Teltonika TachoSync) | Ficheiros DDD → tempos de condução reais por motorista (pergunta "uau" n.º 10) | TachoSync com API; TIS-Web e TachoMaster sem API pública (entram via telemática) | BYO | Alta (obrigação legal) | Alto (DDD é binário) | [Teltonika](https://teltonika-gps.com/solutions/tachosync) · [Continental](https://continental.com/en/press/press-releases/vdo-tis) |
| **Wtransnet** (Alpega, líder ES/PT) | Ofertas de carga/camião; preço de mercado por corredor | Sem API pública; importação Excel; integração TMS por parceria | BYO / parceria | **Muito alta** | Alto (parceria Alpega) | [blog Wtransnet](https://blog.wtransnet.com/en/?p=126) |
| Timocom | Ofertas, ordens de transporte, tracking (3 APIs) | API para clientes; pesquisas genéricas exigem autorização | BYO | Média | Médio | [timocom.co.uk](https://www.timocom.co.uk/api-integration-guide) |
| Teleroute (Alpega) | Publicar e pesquisar cargas a partir do TMS | "T-Interface" sem custo extra para clientes (dado de 2020) | BYO | Média | Médio | [Alpega](https://www.alpegagroup.com/de-de/unternehmen/neuigkeiten/teleroute-launches-an-api-new-mobile-app/) |
| project44 / Shippeo / FourKites | Visibilidade e ETA para o **carregador** (cliente do cliente) | Enterprise, sob proposta; transportadores aderem grátis (project44) | — | Baixa para a Mopa (é transportista) | — | [project44](https://www.project44.com/carriers/) · [G2 Shippeo](https://www.g2.com/products/shippeo/pricing) |
| EcoTransIT World | CO₂ por envio (GLEC / ISO 14083), pedido pelos carregadores | Licença API sob proposta | Revenda | Média-alta (relatórios CSRD dos clientes deles) | Baixo | [netzerocompare](https://netzerocompare.com/software/ecotransit-world) |
| Open-Meteo Standard / Meteomatics | Tempo comercial por coordenada | Open-Meteo ~29–99 $/mês (estudo §1.2); Meteomatics sob proposta | Revenda | Média | Baixo | estudo §1.2 · [rfp.wiki](https://www.rfp.wiki/specialty-industries/energy-utilities-software/weather-data-solutions-for-energy-and-utilities/meteomatics/tomorrow-io) |
| AEMET OpenData | Avisos oficiais | Grátis com chave | Incluído | Alta | Baixo | estudo §1.2 |
| CartoCiudad (IGN) | Geocodificação ES (morada; estrada + PK) | Grátis, CC BY 4.0 no catálogo; limites não publicados | Incluído | Alta em ES | Baixo | [datos.gob.es](https://datos.gob.es/es/catalogo/e0dat0002-servicio-rest-de-geocodificacion-de-espana-cartociudad) |

**Leitura:** para a Mopa (custo/rota, margem/entrega, custo/km, custo/motorista), o valor está nos dados **dela** — telemática (km, horas), cartão de combustível (litros, €) e tacógrafo — e não nas APIs de mapas. Quase tudo isto é **BYO**: custo externo zero para nós; o trabalho é integrar. As APIs de revenda (rota de camião, portagens, CO₂) são o extra para perguntas de planeamento.

### Proposta de empacotamento

| Camada | O que inclui | Planos | Preço |
|---|---|---|---|
| **Sky Mundo** | Data/hora/fuso, feriados ES/PT, restrições DGT, regras 561/2006, combustíveis MITECO, incidências DGT, câmbios BCE, INE/Eurostat, avisos AEMET, CartoCiudad, tempo na grelha de corredores | Todos (Starter 490 € · Core 900 € · Plus 1.800 € · Enterprise) | Incluído (custo ~0) |
| **Conectores da frota (BYO)** | Telemática (Webfleet / Geotab / Movildata / Frotcom), cartão (Solred API ou import CSV DKV/UTA/StarRessa/Galp), import Via-T/Via Verde | Core: 1 conector · Plus: 3 · Enterprise: ilimitado | Instalação 1.500 € por conector sem API pronta (tacógrafo DDD, Wtransnet) |
| **Add-on "Sky Logística"** (revenda) | Rota de camião com trânsito (TomTom; HERE quando houver portagens PT), tempo ao longo da rota (Open-Meteo pago), combustível ao longo da rota, portagens (TollGuru/HERE), CO₂ por viagem (EcoTransIT, fase 2) | Core e Plus; incluído no Enterprise | **390 €/mês**, 3.000 rotas/mês incluídas; depois 0,05 €/rota |

**Conta da margem do add-on (por cliente, 3.000 rotas/mês):**

| Custo | Estimativa/mês |
|---|---|
| TomTom (acima do free tier partilhado) | 3.000 × 0,75 $/1.000 ≈ 2 € |
| HERE camião + portagens (metade das rotas) | 1.500 × 2,75 $/1.000 ≈ 4 € |
| TollGuru (se usado em vez do HERE) | Basic 260 $ / 20K transações (~4.000 rotas) ≈ 60 € |
| Open-Meteo Standard (partilhado) | 30–100 € ÷ n.º de clientes ≈ 10 € |
| LLM (0,03 €/pergunta × 3.000) | 90 € |
| **Total** | **≈ 105–165 €** |

A 390 €: margem bruta **58–73 %**, a subir com escala (Open-Meteo e free tiers rateados). Abaixo de ~300 € a margem cai para menos de 50 % se o TollGuru for usado. EcoTransIT só entra com preço confirmado. Esta proposta afina o "Sky Rota" do §3 (+50–100 € no Starter), escrito antes dos planos atuais; o Starter fica sem add-on.

**Por confirmar antes de vender:**
1. Preço TomTom por 1.000 na tabela nova (a página não o mostra).
2. Termos da API Movimentos Solred para terceiros (SkyFirst como integrador).
3. Se a Wtransnet/Alpega aceita parceria de API (bolsa líder em ES/PT).
4. Que telemática e que cartão a Mopa usa — decide o primeiro conector.
5. Preço EcoTransIT API (info@ecotransit.world) e TollGuru para camião na Europa.

Fontes do Anexo B (consultadas a 10/10/2026): https://docs.tomtom.com/pricing · https://docs.tomtom.com/pricing/price-announcement · https://developers.here.com/plans · https://www.ptvlogistics.com/en/product_description_ptv_developer · https://tollguru.mapup.ai/toll-api-pricing-plans · https://www.repsol.es/autonomos-y-empresas/solred/mi-solred/api-movimientos/ · https://www.repsol.es/autonomos-y-empresas/asesoramiento/apis-de-solred/ · https://web.uta.com/en/fuel-card · https://starressa.moeveglobal.com/en/products-and-services/starressa-cards · https://www.webfleet.com/webfleet/partners/integration · https://www.geotab.com/uk/fleet-management-solutions/software-integration/ · https://supergood.ai/docs/verizon-connect-api · https://www.ccjdigital.com/business/article/14936351/verizon-telematics-acquires-movildata-to-expand-in-europe · https://www.frotcom.com/blog/2021/07/jani-co-logistic-optimizes-fleet-productivity-using-frotcoms-api · https://developers.samsara.com/changelog/new-endpoint-level-rate-limits-starting-october-23rd · https://teltonika-gps.com/solutions/tachosync · https://continental.com/en/press/press-releases/vdo-tis · https://blog.wtransnet.com/en/?p=126 · https://www.timocom.co.uk/api-integration-guide · https://www.alpegagroup.com/de-de/unternehmen/neuigkeiten/teleroute-launches-an-api-new-mobile-app/ · https://www.project44.com/carriers/ · https://www.g2.com/products/shippeo/pricing · https://netzerocompare.com/software/ecotransit-world · https://datos.gob.es/es/catalogo/e0dat0002-servicio-rest-de-geocodificacion-de-espana-cartociudad

---

## Anexo C — Ligar as APIs públicas à plataforma (prova)

Data: 10/10/2026, 21:10–21:15 (hora de Madrid). Sem escrita em produção, sem alterações ao código da aplicação. Scripts descartáveis fora do repositório (`prova_be_rest.py` com o `.venv` do backend; `prova_ai_apisource.py` com o `venv` do sky-ai), só pedidos GET.

Modelo comercial assumido: cada fonte pública ligada conta como uma das "fontes de dados" do plano (Starter 1 · Core 2 · Plus 5). Não é add-on.

### C.1 Como uma API chega hoje a uma resposta (cadeia real)

| Passo | Onde | O que acontece | Consequência |
|---|---|---|---|
| 1. Criar ligação | Web: `studio-create-panel.tsx` (tipo `rest-api`; campos `base_url`, `auth_type`, `auth_header`, `auth_value` + editor de *endpoints* `{name, method, path, description}`) | Config gravada cifrada | ⚠ ver defeito D1 (autenticação) |
| 2. Testar | BE `RestAPIConnector.test_connection` | GET ao `base_url`; aceita qualquer código < 500 | Passa mesmo com 401 |
| 3. Metadados | BE `get_metadata` | Cada *endpoint* declarado vira uma "tabela" **sem colunas** | Nada é descoberto da resposta |
| 4. Descoberta | sky-ai `core/ingestion/db_metadata.py` | Grava 1 linha âncora `column_name="*"` com a descrição; o caminho vai para `extra.endpoint`, **que ninguém lê** | ⚠ D2: o modelo só vê nome + descrição |
| 5. Pergunta | sky-ai `core/data_sources/factory.py` (`rest-api` → `api`) → `specialist.py` ramo NoSQL | O LLM escreve `{"endpoint": "...", "params": {...}}`; o `APISource` faz o pedido **ao vivo**, em cada pergunta | Frescura = a da API. Não há cópia nem histórico |
| 6. Normalização | `APISource.run_query` | Lista → linhas. Objecto → procura `data/items/results/records/users/orders`; senão **1 linha com tudo aninhado**. Não-JSON → **erro** | ⚠ D3 |
| 7. Resposta | `core/llm/formatter.py` | Só as **primeiras 15 linhas** entram no prompt (`data[:15]`), serializadas com `indent=2`. Nenhuma agregação sobre o resto | ⚠ D4 |
| 8. Refresco | `connections.sync_frequency` (cron) | Gravado e `next_sync` calculado, mas **nenhuma tarefa do Beat o lê**; e o `sync_data` REST só conta linhas, não guarda nada | Não há materialização em lado nenhum |

Conclusão: o `rest-api` é **chamada ao vivo, sem materialização**. Serve para APIs pequenas, JSON, sem chave, com parâmetros que o LLM consiga preencher. Não serve para conjuntos grandes, XML/CSV, ou fontes com chave.

Web e app usam o mesmo motor (`/ai/query`, *stream*), por isso o veredicto vale para os dois. A ligação Open-Meteo já foi provada até ao motor a 31/08 (`{"temperature_2m": 25.4}`); o passo da frase final não corre em local (fornecedor LLM local devolve 404).

### C.2 Prova contra as APIs reais

**Backend (`RestAPIConnector`: test → metadata → execute_query):**

| Fonte / pedido | test | Resultado | Tamanho | Tempo |
|---|---|---|---|---|
| MITECO, Espanha inteira `/EstacionesTerrestres/` | ✅ | 1 linha: `Fecha`, `ListaEESSPrecio` = **11.512 postos** aninhados, preços em texto com vírgula (`"1,749"`) | **12,8 MB** | 15,3 s |
| MITECO, Badajoz + Gasóleo A `/FiltroProvinciaProducto/06/4` | ✅ | 1 linha com **277 postos** aninhados | 112 KB | 1,7 s |
| Open-Meteo `/forecast` (lat/lon/hourly) | ✅ | 1 linha; `hourly` em colunas (`time[]`, `temperature_2m[]`…) | 2 KB | 1,7 s |
| OSRM `/route/v1/driving/{lon,lat;lon,lat}` | ✅ | 1 linha: `routes[1]` com `distance` (m) e `duration` (s) | 1 KB | 1,7 s |
| Nager `/PublicHolidays/2026/ES` | ✅ | **32 linhas** limpas (`date`, `localName`, `counties`) | 7 KB | 1,5 s |
| Frankfurter (dados BCE) `/latest` | ✅ | 1 linha, `rates{29}`, `date=2026-10-09` | <1 KB | 1,4 s |
| BCE SDMX (`jsondata` / `csvdata`) | ✅ | `[{"text": …}]` — o tipo `application/vnd.sdmx…` não é `application/json` | — | 1,8 s |
| DGT DATEX2 v3.7 (XML) | ✅ | `[{"text": "<?xml…"}]` cortado a 2.000 caracteres | 2,97 MB na origem | 1,7 s |
| AEMET sem chave | ✅ (401 conta como "acessível") | `[{"text": ""}]` | — | 1,6 s |

**Motor (`APISource` do sky-ai, com o JSON que o especialista geraria) — o que chega ao prompt da resposta:**

| Fonte | Resultado | Prompt do formatter |
|---|---|---|
| MITECO Badajoz Gasóleo A | 1 linha com 277 postos | **≈153 KB ≈ 39.000 tokens** — e o LLM teria de ordenar preços em texto |
| Open-Meteo diário (3 dias, Madrid) | 1 linha | ≈185 tokens ✅ |
| OSRM Badajoz→Madrid | 1 linha | ≈250 tokens ✅ |
| Nager `/PublicHolidays/2026/ES` | 32 linhas → **só as 15 primeiras** (até 04/06/2026) | O 12/10 **não chega ao modelo** ❌ |
| Nager `/NextPublicHolidays/ES` | 32 linhas, a começar em 12/10/2026 | ✅ (contorna o corte) |
| Frankfurter `/latest?symbols=USD,GBP` | 1 linha | ≈35 tokens ✅ |
| DGT DATEX2 (XML) | **`JSONDecodeError`** | ❌ |
| BCE `csvdata` | **`JSONDecodeError`** | ❌ |
| AEMET com chave em `headers` | 401 com chave falsa (o caminho do cabeçalho funciona); o 2.º passo (`datos` → URL) não é seguido | ❌ |

### C.3 Veredicto por fonte

| Fonte | Hoje com `rest-api` (zero código) | Falta | Frescura medida | Licença / limites / custo | Refresco necessário |
|---|---|---|---|---|---|
| **Open-Meteo** (tempo) | ✅ Funciona, se a descrição levar o caminho e os parâmetros (D2) | Coordenadas: o LLM tem de as saber (capitais ok). Uso comercial exige chave paga (`&apikey=` na query → D1) | ECMWF IFS 0,25°: corrida 06 UTC disponível 13:06 UTC; ICON e ARPEGE: corrida 12 UTC disponível ~15:31 UTC; `update_interval` 6 h | Grátis só não-comercial; 10.000/dia. **Um vídeo de vendas é uso comercial** → plano Standard antes de gravar | Ao vivo serve. Para cruzar com rotas: grelha por cidade, 1×/h |
| **OSRM** (rota) | ✅ Funciona (coordenadas no caminho) | Perfil **automóvel**, não camião; servidor demo sem SLA nem uso comercial | Dados OSM; sem carimbo na resposta | Demo: uso leve, ~1 pedido/s; produção → self-host ou TomTom | Ao vivo |
| **Nager.Date** (feriados) | ✅ com `/NextPublicHolidays/{país}`; ❌ com `/PublicHolidays/{ano}` (corte das 15 linhas) | Trasladações e municipais em falta (Anexo A) | Anual | Grátis, sem chave | Tabela anual corrigida pelo BOE/DRE é melhor |
| **Frankfurter / BCE** (câmbio) | ✅ Frankfurter. ❌ SDMX directo (não-JSON / JSON aninhado) | MAD não existe (Anexo A) | `date=2026-10-09` (sexta; fixing ~16:00 CET, sem fim-de-semana) | Grátis, sem chave | Diário, 16:30 CET |
| **MITECO** (gasóleo) | ❌ Ao vivo não serve: 277 postos por província = 39k tokens; Espanha = 12,8 MB; o formatter só vê 15 linhas | Materializar em tabela (preço numérico, coordenadas, distância ao corredor) | O campo `Fecha` é **a hora do pedido**, não do preço (21:11:35 e 21:12:41 em pedidos com 66 s de intervalo). Histórico diário existe: `/EstacionesTerrestresHist/FiltroProvinciaProducto/01-10-2026/06/4` → `Fecha 01/10/2026 0:00` | Dados abertos, uso comercial; sem limite publicado | Actual: 30 min. Histórico: 1×/dia (dá "tendência" e cruza com viagens passadas) |
| **DGT DATEX2 v3.7** (incidências) | ❌ XML | Parser + tabela | `publicationTime` avança a cada minuto (21:11:10 → 21:12:10); 692 registos activos | Gratuita (Reg. UE 886/2013) | 5 min; guardar activos + 30 dias |
| **AEMET** (avisos) | ❌ | Chave (D1) + pedido em 2 passos | n/d (sem chave) | Comercial permitido com atribuição | 1 h |
| **Portagens ES/PT** | ❌ **Não há API pública gratuita** em nenhum dos países | Tabela manual: ES a partir da Ordem anual do Ministério (subidas 3,64–4,68 % em 2026; SEITT +2 %); PT a partir dos tarifários das concessionárias (Brisa +2,29 % médio em 2026; **pesados classes 3–4 isentos na A41/CREP, A19 e A8 desde 01/01/2026**, Lei 6/2026) | Anual + leis avulsas | Público | Anual. API paga só se necessário (TollGuru/HERE, Anexo B) |
| **DGT restrições a pesados** | ❌ PDF/BOE | Tabela manual (dias × horas × troços × tipo de veículo) | Página DGT actualizada a 31/07/2026 | Público | Anual + resoluções avulsas |
| **Histórico de combustível** | ❌ ao vivo | MITECO histórico (acima) e Weekly Oil Bulletin (XLSX, ES vs PT) para tabela | Semanal (WOB) | Aberta | Semanal |
| **TomTom** (camião + trânsito) | ❌ | Chave na query string (`?key=`) — D1; o LLM não pode ver a chave | — | Freemium comercial, 20.000 rotas/mês | Ao vivo |
| **APIs do cliente** (Solred, telemática) | ⚠ Só se JSON pequeno e com Bearer configurado por API, não pela web (D1) | OAuth2 (Solred), paginação, envelopes | — | BYO | Ao vivo ou materializado |

### C.4 Defeitos encontrados no caminho `rest-api`

| # | Defeito | Evidência | Esforço |
|---|---|---|---|
| D1 | **A autenticação escrita pela web não é lida por ninguém.** A web grava `auth_type/auth_header/auth_value`; o backend lê `config["auth"]` (`type/token/header_name`); o sky-ai lê `api_key` (vira `Bearer`) ou `headers`. Nenhum lê os campos da web. Não há chave na query string (TomTom, Open-Meteo pago) | `studio-create-panel.tsx` l. 381–386 · `rest_api.py` `_build_auth_headers` · `api_source.py` `__init__` | 0,5–1 dia |
| D2 | O caminho do *endpoint* não chega ao LLM se houver descrição: vai para `extra.endpoint`, que nenhum código lê | `db_metadata.py` l. 440–468 | 0,5 dia |
| D3 | Respostas não-JSON rebentam (XML, CSV); envelopes fora da lista fixa (`ListaEESSPrecio`, `routes`) ficam numa linha aninhada | `api_source.py` | 0,5 dia (`records_path` configurável) + 1–2 dias (CSV/XML) |
| D4 | O formatter só vê 15 linhas e não agrega: "o mais barato", "o próximo feriado" ou "quantos" sobre listas grandes ficam errados sem aviso | `formatter.py` `data[:15]` | 1–2 dias (passar linhas da API pelo DuckDB que o merger já usa) |
| D5 | `sync_frequency` é gravado e nunca executado; o `sync_data` REST não guarda dados | `connection_service.py` `_calculate_next_sync`; `celery_app.py` sem tarefa | Ver C.5 |
| D6 | `test_connection` dá ✅ com 401 (AEMET sem chave) | `rest_api.py` `< 500` | 0,5 h |

### C.5 Caminho mínimo para a demonstração

**Princípio:** o que é pequeno e depende da pergunta fica ao vivo (`rest-api`); o que é grande, XML ou precisa de histórico vai para **tabelas Postgres**, ligadas com o conector Postgres que já funciona de ponta a ponta (descoberta de colunas, SQL, gráficos, widgets).

| Passo | O quê | Código da aplicação | Esforço |
|---|---|---|---|
| **0 — zero código** | 4 ligações `rest-api` no projecto "Logística y Transporte": Open-Meteo `/forecast`, OSRM `/route/v1/driving/{coords}`, Nager `/NextPublicHolidays/{país}`, Frankfurter `/latest`. **Regra:** nome do endpoint = caminho, e a descrição leva caminho + parâmetros + unidades (ex.: *"GET /forecast?latitude=&longitude=&daily=temperature_2m_max,precipitation_sum,wind_gusts_10m_max&timezone=Europe/Madrid — previsión por coordenada, 16 días"*). Testar 5 perguntas por fonte na web e na app | Nenhum | 2–3 h |
| **1 — carregador "Datos públicos"** | Estender `scripts/dados_publicos/` com `carregar_mundo.py` → esquema `mundo` na base de demonstração: `gasolineras` (MITECO actual, preço numérico, lat/lon, `dist_a5_km` / `corredor`), `gasoleo_hist` (MITECO diário, 4 províncias × 365 dias — os dados de demo cobrem os últimos 12 meses desde a sementeira de 04/10), `incidencias_dgt` (DATEX2 → linhas, filtrada por estrada), `feriados` (Nager + correcções BOE/DRE), `peajes` (manual: corredores da demo, A-5 = 0 €), `restricciones_dgt` (manual), `wob_gasoleo` (ES vs PT semanal), `tiempo_ciudades` (Open-Meteo, 20 cidades das rotas). Comentários `COMMENT ON` em todas as colunas (o conector Postgres lê-os como descrições). CronJob no `sky-infra`: MITECO 30 min, DGT 5 min, tempo 1 h, histórico/câmbio diário | Nenhum (script + manifest) | **3–4 dias** |
| **2 — corrigir `rest-api`** | D1, D2, D3 (`records_path`), D6 → ligar APIs de clientes (Solred, telemática) sem engenharia por cliente | Sim | **3–4 dias** |
| **3 — produto** | Tipo de ligação **"Datos públicos"** gerido por nós: catálogo de conjuntos, base partilhada `sky_world` (§2), refresco por Celery Beat a honrar `sync_frequency`, ligação de sistema só-leitura. D4 (DuckDB sobre linhas da API) | Sim | 1,5–2 semanas (= Fase 1 do §4) |

**Recomendação:** passos 0 + 1 para gravar os vídeos (≈1 semana, zero código da aplicação); passo 2 antes do primeiro cliente com API própria; passo 3 quando houver o 2.º cliente de logística.

**Decisões para o Lucas:**
1. **Perguntas mistas (cliente + público).** O motor tem caminho multi-ligação (`dispatch_map` + merger DuckDB, `connection_query.py` l. 4345), mas a sementeira sectorial evita de propósito junções ao vivo entre ligações ("prometer uma junção ao vivo que o produto hoje não faz…", `transportes.py`). Opções: (A) ligação separada "Datos públicos" e validar o merger pergunta a pergunta; (B) escrever as tabelas `mundo` também no esquema `ops` da demo, para cada pergunta mista correr numa só ligação. **Recomendo B para os vídeos, A para o produto.**
2. **Contagem de fontes.** Se o carregador junta 8 conjuntos numa ligação Postgres, conta como 1 fonte ou 8? Com "1 por conjunto", o Starter (1 fonte) não chega para nenhuma demo mista.
3. **Licença Open-Meteo** para gravar: pagar o Standard (chave na query → passo 1 ou D1) ou usar os dados já materializados.

### C.6 Conteúdo para os vídeos (tenant `skyfirstlabs`)

Projecto já semeado no `skyfirstlabs` e no `sandbox` pelo Job 17: **"Logística y Transporte"**, com as ligações **Flota** (`fleet`), **Operaciones** (`ops`) e **Carga** (`freight`). Rotas da demo: Lisboa, Porto, Coimbra, Braga, Viseu ↔ Badajoz, Mérida, Almendralejo, Sevilla, Madrid. 18 viaturas (semirremolque, frigorífico, ligero), 280 viagens/veículo em 12 meses. Acrescentar a ligação **"Datos públicos"** (C.5 passo 1) e as 4 `rest-api` (passo 0).

⚠ Os dados sintéticos imputam portagem a todas as rotas (`toll_cost = km × 0,072`): Badajoz–Madrid aparece com 28,80 € e a A-5 não tem portagem. Ou se corrige na sementeira, ou se transforma na pergunta 4.

| # | Pregunta (ES) | Datos del cliente | Datos públicos | Estilo de respuesta esperado (números **ilustrativos** — recalcular com os dados reais antes de gravar) | Nota PT |
|---|---|---|---|---|---|
| 1 | «¿Cuánto nos habríamos ahorrado en septiembre en Badajoz–Madrid repostando en el surtidor más barato a menos de 3 km de la A-5?» | `ops.trips` (litros) + `ops.routes` | `mundo.gasoleo_hist` + `gasolineras` | «Septiembre: 14 viajes, 4.120 l. A la media de Badajoz (1,82 €/l) = 7.498 €; en el más barato del corredor (1,69 €/l, Móstoles) = 6.963 €. **Ahorro: 535 €/mes.** Fuente: MITECO, 01–30/09.» | Pergunta-estrela. Mista → decisão 1 |
| 2 | «¿Dónde reposto hoy más barato entre Mérida y Madrid sin salir de la A-5?» | — | `mundo.gasolineras` | Top 3 con municipio, €/l, horario y «actualizado 21:10» | Só pública; funciona com 1 ligação |
| 3 | «¿Qué rutas de esta semana tienen lluvia o rachas de más de 50 km/h en origen o destino?» | `ops.routes` | `mundo.tiempo_ciudades` / Open-Meteo | Tabla ruta × día con semáforo | Ao vivo só para 1 cidade; para todas → tabela |
| 4 | «¿Estamos imputando peajes que no existen?» | `ops.routes.toll_cost` | `mundo.peajes` | «Badajoz–Madrid (A-5): imputamos 28,80 €, la tarifa pública es 0 €. 6 rutas sin peaje real: 1.940 €/año sobrevalorados.» | Usa o defeito dos dados a favor |
| 5 | «¿Hay ahora incidencias de la DGT en las carreteras de nuestras rutas a Madrid y Sevilla?» | `ops.routes` (+ tabla ruta→carreteras) | `mundo.incidencias_dgt` | Lista: carretera, PK, tipo, desde qué hora | Refresco 5 min; dizer a hora do dado |
| 6 | «¿Cuántos viajes hicimos en festivo el último año y cuánto nos costaron en horas de conductor?» | `ops.trips` + `fleet.drivers.cost_per_hour` | `mundo.feriados` (nacionales + regionales) | «23 viajes en festivo, 212 h, 4.030 €. Más en Extremadura (8 sep.).» | Mista |
| 7 | «¿Puede salir un semirremolque de Badajoz a Madrid el próximo festivo nacional por la mañana?» | `fleet.vehicles.class` | Nager `/NextPublicHolidays/ES` + `mundo.restricciones_dgt` | «Próximo festivo: 01/11 (domingo). La DGT restringe >7,5 t en … de 8:00 a 15:00. Salir antes de las 8:00 o por la tarde.» + aviso «informativo» | Texto legal curado (§1.7) |
| 8 | «¿Cuánto ha subido el gasóleo en Extremadura en 3 meses y cuánto nos cuesta al mes?» | `ops.trips` (litros/mes) | `mundo.gasoleo_hist` | Gráfico de línea + «+6,1 cént./l ≈ +1.150 €/mes en la flota» | Widget candidato |
| 9 | «¿Cuántos km y horas hay de Porto a Madrid, y cumplimos ese tiempo?» | `ops.routes.standard_minutes` + `ops.trips` | OSRM ao vivo | «560 km; turismo 5h20; camión estimado ~6h40 + pausa 45 min. Nuestro estándar: 8h12; llegamos tarde en el 31 % de los viajes.» | OSRM é perfil automóvel — dizer «estimado» |
| 10 | «¿Repostar en Portugal o en España en Lisboa–Madrid?» | `ops.trips` (rutas transfronterizas) | `mundo.wob_gasoleo` (ES vs PT) | «Esta semana el gasóleo es 0,21 €/l más barato en España: repostar después de Badajoz ahorra ~126 € por depósito de 600 l.» | Muito ibérico; WOB é semanal |

**Páginas / widgets (2–3):**

| Página | Widgets |
|---|---|
| **«Gasóleo en ruta»** | KPI precio medio hoy (Badajoz, Madrid) · KPI «ahorro posible este mes» · tabla top 10 surtidores ≤3 km de la A-5 · línea 90 días España vs Portugal (MITECO + WOB) · coste de gasóleo de la flota a precio real |
| **«Riesgos de hoy en nuestras rutas»** | Tabla ruta × (tiempo mañana, incidencias DGT activas, festivo/restricción) con semáforo · KPI rutas en rojo · texto «actualizado HH:MM, fuentes» |
| **«Coste real por ruta»** | Peaje imputado vs tarifa pública · €/km total (gasóleo a precio real + peaje + horas de conductor) · margen por cliente recalculado |

**Regras de apresentação:** mostrar sempre fonte e hora do dado; "precio de surtidor publicado", não "precio de la flota"; testar cada pergunta 2× seguidas na web **e** na app antes de gravar; dados de demo recalculados a partir da data da sementeira (04/10/2026).


---

## Anexo D — Carregador «mundo» (prova)

Data: 10/10/2026, 22:27–22:35 (hora de Madrid). Passo 1 do §C.5 construído e corrido a sério contra as fontes reais, em modo SQLite (não há Docker nem Postgres local). Sem git, sem escrita em produção, sem alterações ao código da aplicação. Licenças revistas com `DADOS_EXTERNOS_COMERCIAL_2026-10.md`.

### D.1 O que existe

| Ficheiro | Papel |
|---|---|
| `scripts/dados_publicos/carregar_mundo.py` | Ponto de entrada (`--dsn` / `MUNDO_DSN`, `--sqlite`, `--so`, `--dias-historico`, `--semanas-ue`, `--permitir-nao-comercial`; até 10/10 havia `--festivos-nager`, removido) |
| `scripts/dados_publicos/mundo/esquema.py` | 12 tabelas SQLAlchemy no esquema `mundo`, com `COMMENT` por coluna (o conector Postgres lê-os como descrições) |
| `scripts/dados_publicos/mundo/transformar.py` | Transformações puras (JSON/XML/XLSX → linhas): MITECO, DATEX II (iterparse, independente de prefixos), Nager, Frankfurter, Open-Meteo, AEMET, OSRM, WOB (XLSX só com stdlib), regra 561/2006, postos perto da rota (grelha 0,05°, sem PostGIS) |
| `scripts/dados_publicos/mundo/referencia.py` | Tabelas manuais: portagens 2026, restrições DGT 2026 (A-5), feriados oficiais BOE/Código do Trabalho |
| `scripts/dados_publicos/mundo/carregar.py` | Pedidos com *timeout* e 3 tentativas (429/5xx), *upsert* `ON CONFLICT` (Postgres e SQLite), isolamento por fonte, registo em `mundo.fontes`, resumo |
| `scripts/dados_publicos/mundo/README.md` | Como correr, cadências, licenças/atribuição, CronJob proposto (não aplicado) |
| `scripts/dados_publicos/mundo/fixtures/` | Respostas reais gravadas a 10/10 (cortadas) + 1 fixture AEMET **sintética** |
| `src/tests/test_mundo_*.py` (5 ficheiros) | 25 testes sem rede |

Decisões de licença aplicadas (o vídeo de vendas é uso comercial):
- **Feriados:** tabela própria a partir do BOE-A-2025-21667 (ES 2026: nacionais + Extremadura, Madrid, Andalucía, com as trasladações de 02/11 e 07/12) e do art. 234.º do Código do Trabalho (PT 2026–2027). ES 2027 só com as nacionais não substituíveis, marcado provisório: a resolução de 2027 ainda não saiu. Nager.Date só com `--festivos-nager`, linhas `licenca = nao-comercial`.
- **OSRM:** `rotas_referencia.licenca = demo-nao-comercial`, nota a apontar TomTom (perfil camião, 20.000 rotas/mês grátis).

**Actualização 12/10/2026 (só fontes comerciais em produção):** feriados ES com o anexo completo do BOE-A-2025-21667 (17 CCAA + Ceuta e Melilla) e PT calculados da Páscoa (art. 234.º CT, DRE); **Nager.Date removido**. Tempo: AEMET (`AEMET_API_KEY`) + Open-Meteo **de cliente** (`OPEN_METEO_API_KEY`, `customer-api.open-meteo.com`). Rotas: **TomTom** perfil camião (`TOMTOM_API_KEY`). Sem chave a fonte não corre (`fontes.estado = sem_chave`, linhas anteriores ficam com a licença); Open-Meteo grátis e OSRM demo só com `--permitir-nao-comercial`, recusado no Kubernetes. `fontes.uso_comercial` reflecte o que está na tabela; todas as tabelas têm `licenca` por linha. Ver `scripts/dados_publicos/mundo/README.md`. Os parágrafos abaixo descrevem o estado de 10/10.
- **Open-Meteo:** `tempo_cidades.licenca = nao-comercial (Open-Meteo Standard ~29€/mês para uso comercial)`. Adaptador **AEMET** pronto: corre só com `AEMET_API_KEY` e substitui as 5 cidades espanholas. Não testado contra a API real (sem chave); testado com fixture sintética.
- **BCE/Frankfurter, MITECO, DGT, WOB, BOE:** atribuição obrigatória escrita em `mundo.fontes.atribuicao`; DGT com nota «confirmar por email ao NAP».

### D.2 Corrida real (SQLite, `--dias-historico 30`)

| Fonte (`--so`) | Estado | Linhas | Tempo | Hora do dado (fonte) | Frescura medida |
|---|---|---|---|---|---|
| rotas (OSRM) | ✅ | 20 | 24,0 s (1 pedido/s) | pedido 22:28 | ao vivo; sem carimbo na resposta |
| gasolineras (MITECO) | ✅ | 11.514 postos + 1.976 ligações posto–rota | 19,8–21,0 s | `Fecha` 22:33:xx = hora do pedido | preço da última meia hora; o MITECO não publica a hora do preço |
| gasoleo_historico | ✅ | 1.590 (30 dias × ~53 províncias) + 53 da fotografia de hoje | 160 s (30 × ~5 s) | último dia fechado 09/10 00:00 | D-1 |
| gasoleo_ue (WOB) | ✅ | 156 (52 semanas × ES/PT/UE) | 2,8 s | semana de 05/10/2026 | 5 dias (boletim semanal) |
| incidencias (DGT) | ✅ | 649 → 665 após 2.ª corrida (654 activas, 11 saídas do feed) | 1,6–2,8 s | `publicationTime` 22:33 | < 1 min |
| festivos | ✅ | 57 (ES 31, PT 26) | 15 ms | tabela 2026 | anual |
| cambio (BCE) | ✅ | 1.914 (63 fixings × 30 moedas) | 1,0 s | fixing de 09/10 (16:00 CET) | D-1 útil (sábado sem fixing) |
| tempo (Open-Meteo) | ✅ | 70 (10 cidades × 7 dias) | 1,0 s | pedido 22:33 | modelo de 6 em 6 h |
| portagens | ✅ | 114 | 32 ms | tarifas 2026 | anual |
| restricoes | ✅ | 12 | 14 ms | resolução de 14/01/2026 | anual |

**Idempotência verificada:** 2.ª corrida de `gasolineras incidencias tempo festivos portagens` manteve as contagens (11.513 → 11.514 por 1 posto novo no MITECO; 57, 70, 114 iguais); nos testes, duas corridas seguidas dão contagens idênticas. **Isolamento verificado** em teste: DGT simulada em baixo → `fontes.estado = erro`, as outras 4 fontes carregam.

**Postgres:** não houve base local. O DDL das 12 tabelas e o `INSERT … ON CONFLICT (…) DO UPDATE` compilam para o dialecto `postgresql` (verificado); falta a corrida real contra um Postgres. Comando:

```bash
cd sky-poc-backend
MUNDO_DSN=postgresql://USER:PASS@HOST:5432/BASE .venv/Scripts/python.exe scripts/dados_publicos/carregar_mundo.py --dias-historico 90
```

### D.3 Perguntas do Anexo C respondidas em SQL (saída real)

Consultas em SQLite (sem o prefixo `mundo.`; em Postgres acrescenta-se `mundo.`). Horas em UTC (+2 h para Madrid).

### Q1 Gasóleo A mais barato a ≤3 km da rota Badajoz→Madrid (A-5)

| eur_l | rotulo | municipio | provincia | km_rota | dist_km | carretera | horario | actualizado_utc |
|---|---|---|---|---|---|---|---|---|
| 1.689 | PETROPRIX | Móstoles | MADRID | 376.9 | 1.33 |  | L-D: 24H | 2026-10-10 20:33 |
| 1.689 | BALLENOIL | Móstoles | MADRID | 376.9 | 1.32 |  | L-D: 24H | 2026-10-10 20:33 |
| 1.699 | BALLENOIL | Móstoles | MADRID | 377.4 | 0.32 |  | L-D: 24H | 2026-10-10 20:33 |
| 1.709 | PLENERGY | Alcorcón | MADRID | 377.4 | 2.43 | M-506 | L-D: 24H | 2026-10-10 20:33 |
| 1.709 | PLENERGY | Alcorcón | MADRID | 377.4 | 2.3 |  | L-D: 24H | 2026-10-10 20:33 |

### Q2 Mais barato por troço de 100 km (Badajoz→Madrid, ≤3 km) e spread

| troco_km | postos | min_eur_l | max_eur_l | dif_600l_eur |
|---|---|---|---|---|
| 0 | 62 | 1.72 | 2.169 | 269.0 |
| 100 | 20 | 1.74 | 2.029 | 173.0 |
| 200 | 36 | 1.769 | 2.02 | 151.0 |
| 300 | 153 | 1.689 | 2.069 | 228.0 |

### Q3 Incidências DGT activas agora na A-5

| carretera | pk | pk_fim | sentido | causa | subtipo | municipio | provincia | inicio_utc | gravidade | feed_utc |
|---|---|---|---|---|---|---|---|---|---|---|
| A-5 | 39.064 |  | positive | vehicleObstruction | vehicleStuck | Casarrubios del Monte | Toledo | 2026-10-10 20:32 |  | 2026-10-10 20:33 |
| A-5 | 209.035 |  | positive | vehicleObstruction | vehicleStuck | Romangordo | Cáceres | 2026-10-10 20:30 |  | 2026-10-10 20:33 |

### Q4 Próximo feriado em ES-EX / ES-MD (desde 10/10/2026) e restrição a pesados na A-5

| data | nome | ambito | dia_semana | restricao_a5 |
|---|---|---|---|---|
| 2026-10-12 | Fiesta Nacional de España | nacional | seg | Salida Madrid 16:00-24:00 PK 15.6→126.0 | Entrada Madrid 16:00-24:00 PK 126.0→11.8 |
| 2026-11-02 | Lunes siguiente a Todos los Santos | ES-EX | seg | Salida Madrid 16:00-24:00 PK 15.6→126.0 | Entrada Madrid 16:00-24:00 PK 126.0→11.8 |
| 2026-11-02 | Lunes siguiente a Todos los Santos | ES-MD | seg | Salida Madrid 16:00-24:00 PK 15.6→126.0 | Entrada Madrid 16:00-24:00 PK 126.0→11.8 |
| 2026-12-07 | Lunes siguiente al Día de la Constitución | ES-EX | seg | sem restrição Anexo II na A-5 |

### Q5 Restrições A-5 na véspera/ponte do 12/10 (sexta 09 a segunda 12)

| data | sentido | hora_inicio | hora_fim | troco | confianca |
|---|---|---|---|---|---|
| 2026-10-09 | Ambos sentidos | 16:00 | 22:00 | Madrid (enlace M-50, PK 15,6) – Talavera de la Reina (PK 106) | inferido_do_padrao |
| 2026-10-10 | Ambos sentidos | 08:00 | 15:00 | Madrid (enlace M-50, PK 15,6) – Talavera de la Reina (PK 106) | lido_no_pdf |
| 2026-10-12 | Entrada Madrid | 16:00 | 24:00 | Talavera de la Reina (PK 126) – Madrid (enlace M-40, PK 11,8) | lido_no_pdf |
| 2026-10-12 | Salida Madrid | 16:00 | 24:00 | Madrid (enlace M-50, PK 15,6) – Talavera de la Reina (PK 126) | lido_no_pdf |

### Q6 Espanha vs Portugal: gasóleo em Badajoz (MITECO hoje) vs médias nacionais WOB

| onde | n | min | media | semana |
|---|---|---|---|---|
| Badajoz cidade (MITECO, agora) | 39 | 1.78 | 1.887 |  |
| Média nacional ES (WOB) |  |  | 1.918 | 2026-10-05 |
| Média nacional PT (WOB) |  |  | 2.155 | 2026-10-05 |

### Q7 Gasóleo A, província de Badajoz: 30 dias (MITECO histórico)

| data | n_postos | minimo | mediana | media | maximo | origem |
|---|---|---|---|---|---|---|
| 2026-09-10 | 275 | 1.654 | 1.839 | 1.82 | 2.129 | historico |
| 2026-10-07 | 276 | 1.694 | 1.899 | 1.894 | 2.169 | historico |
| 2026-10-08 | 278 | 1.694 | 1.899 | 1.889 | 2.169 | historico |
| 2026-10-09 | 277 | 1.694 | 1.899 | 1.889 | 2.169 | historico |
| 2026-10-10 | 277 | 1.694 | 1.905 | 1.895 | 2.169 | actual |

### Q8 Portagem imputada na demo (km×0,072) vs tarifa pública (classe 4+ eixos)

| rota | corredor | km | imputado_demo | tarifa_publica | nota |
|---|---|---|---|---|---|
| Badajoz - Madrid | A-5 | 400.0 | 28.8 | 0 | sem portagem |
| Badajoz - Sevilla | A-66 | 220.0 | 15.84 | 0 | sem portagem |
| Mérida - Sevilla | A-66 | 195.0 | 14.04 | 0 | sem portagem |
| Almendralejo - Sevilla | A-66 | 170.0 | 12.24 | 0 | sem portagem |
| Badajoz - Mérida | A-5 | 65.0 | 4.68 | 0 | sem portagem |
| Badajoz - Almendralejo | A-5/EX-A3 | 55.0 | 3.96 | 0 | sem portagem |
| Mérida - Almendralejo | A-66 | 30.0 | 2.16 | 0 | sem portagem |
| Lisboa - Madrid | A2/A6 + A-5 | 625.0 | 45.0 |  | Parte PT como Lisboa–Caia (parcial: 15,40 € classe 1 Maratec |
| Porto - Madrid | A1/A25 + A-62 | 560.0 | 40.32 |  | A25 é ex-SCUT sem portagem desde 2025; troço A1/A29 até à A2 |
| Lisboa - Sevilla | A2/A6 + A-66 | 460.0 | 33.12 |  | Itinerário depende (A6+A-66 vs A22/A-49); parte ES sem porta |
| Porto - Badajoz | A1/A23 + A6 | 400.0 | 28.8 |  | Inclui troços A1 (pagos) e A23 (livre desde 2025); total não |
| Coimbra - Badajoz | A23 + A6 | 310.0 | 22.32 |  | A23 ex-SCUT sem portagem desde 2025; percurso exacto até Cai |
| Lisboa - Porto | A1 | 300.0 | 21.6 |  | Classe 1 = 25,05 € (2026, +0,45 €). Classes 2–4 não publicad |
| Lisboa - Mérida | A2/A6 + A-66 | 300.0 | 21.6 |  | Parte PT como Lisboa–Caia; parte ES (A-5) = 0 €. |
| Lisboa - Badajoz | A2/A6 | 230.0 | 16.56 |  | Inclui Marateca–Caia (15,40 € classe 1) + Ponte 25 de Abril/ |
| Coimbra - Lisboa | A1 | 200.0 | 14.4 |  | A1 Coimbra–Lisboa: preço 2026 não verificado. |
| Braga - Coimbra | A3/A1 | 175.0 | 12.6 |  | A3 + A1: preço 2026 não verificado. |
| Porto - Viseu | A1/A25/A24 | 130.0 | 9.36 |  | A25 e A24 ex-SCUT sem portagem desde 2025 (Lei n.º 37/2024 ( |
| Porto - Coimbra | A1 | 120.0 | 8.64 |  | A1 Porto–Coimbra: preço 2026 não verificado. |
| Porto - Braga | A3 | 55.0 | 3.96 |  | A3 Porto–Braga (Brisa): preço 2026 não verificado. |

### Q9 Rotas da demo: carro (OSRM) vs camião estimado (80 km/h + 45 min/4h30)

| origem | destino | km | carro_min | conducao_min | pausas_45min | camiao_min | licenca |
|---|---|---|---|---|---|---|---|
| Lisboa | Madrid | 629.4 | 410.6 | 472.0 | 1 | 517.0 | demo-nao-comercial |
| Porto | Madrid | 555.3 | 379.2 | 416.5 | 1 | 461.5 | demo-nao-comercial |
| Badajoz | Madrid | 402.8 | 268.4 | 302.1 | 1 | 347.1 | demo-nao-comercial |
| Lisboa | Porto | 314.2 | 206.3 | 235.7 | 0 | 235.7 | demo-nao-comercial |

### Q10 Tempo: cidades com chuva ≥1 mm ou rajada ≥50 km/h nos próximos 7 dias

| cidade | data | temp_min | temp_max | precipitacao_mm | rajada_max_kmh | descricao |
|---|---|---|---|---|---|---|
| (sem linhas) |

### Q11 12.000 USD em EUR ao último fixing BCE

| data | taxa | eur |
|---|---|---|
| 2026-10-09 | 1.1206 | 10708.55 |

### Q12 Frescura por fonte (mundo.fontes)

| nome | estado | linhas | dado_de_utc | carregado_utc | duracao_ms | uso_comercial |
|---|---|---|---|---|---|---|
| cambio | ok | 1914 | 2026-10-09 14:00 | 2026-10-10 20:32 | 1008 | 1 |
| festivos | ok | 57 |  | 2026-10-10 20:33 | 15 | 1 |
| gasoleo_historico | ok | 1590 | 2026-10-08 22:00 | 2026-10-10 20:31 | 160419 | 1 |
| gasoleo_ue | ok | 156 | 2026-10-05 00:00 | 2026-10-10 20:31 | 2757 | 1 |
| gasolineras | ok | 11514 | 2026-10-10 20:33 | 2026-10-10 20:33 | 19771 | 1 |
| incidencias | ok | 654 | 2026-10-10 20:33 | 2026-10-10 20:33 | 1551 | 1 |
| portagens | ok | 114 | 2026-10-10 00:00 | 2026-10-10 20:33 | 32 | 1 |
| restricoes | ok | 12 | 2026-01-14 00:00 | 2026-10-10 20:32 | 14 | 1 |
| rotas | ok | 20 | 2026-10-10 20:28 | 2026-10-10 20:28 | 24020 | 0 |
| tempo | ok | 70 | 2026-10-10 20:33 | 2026-10-10 20:33 | 961 | 0 |

SQL de duas delas (as outras seguem o mesmo padrão):

```sql
-- Q1: mais barato a ≤3 km da A-5 entre Badajoz e Madrid
SELECT g.precio_gasoleo_a, g.rotulo, g.municipio, r.km_desde_origem, r.dist_km, g.actualizado_em
FROM mundo.gasolineras_rota r JOIN mundo.gasolineras_precio g USING (id_estacion)
WHERE r.origem = 'Badajoz' AND r.destino = 'Madrid' AND r.dist_km <= 3
ORDER BY g.precio_gasoleo_a LIMIT 5;

-- Q4: próximo feriado em Extremadura/Madrid e se restringe pesados na A-5
SELECT f.data, f.nome, COALESCE(f.regiao, 'nacional'), r.sentido, r.hora_inicio, r.hora_fim
FROM mundo.festivos f
LEFT JOIN mundo.restricoes_pesados r ON r.data = f.data AND r.carretera = 'A-5'
WHERE f.pais = 'ES' AND f.data >= CURRENT_DATE AND (f.regiao IS NULL OR f.regiao IN ('ES-EX', 'ES-MD'))
ORDER BY f.data LIMIT 4;
```

**Leitura para a demo:**
- Q1/Q2 reproduzem o Anexo A (1,689 €/l em Móstoles) mas agora em milissegundos e cruzáveis com `ops.routes` pelo par origem/destino. Diferença máxima num troço de 100 km: 269 € em 600 l.
- Q4/Q5: o 12/10 (segunda) restringe a A-5 entre Madrid e Talavera de 16:00 a 24:00 nos dois sentidos; na sexta 09/10 e sábado 10/10 também. Um semirreboque Badajoz→Madrid no 12/10 que chegue a Talavera antes das 16:00 passa; depois das 16:00 não.
- Q6: em Badajoz o gasóleo está a 1,887 €/l (média, 39 postos), 27 cênt./l abaixo da média nacional portuguesa da semana (2,155 €/l, WOB). Abastecer depois da fronteira poupa ~160 € em 600 l. Comparação local ES vs nacional PT: não há preço por posto em Portugal (DGEG sem API).
- Q8 dá a pergunta 4 do Anexo C: as 7 rotas espanholas imputam 81,72 € por viagem a portagens que são 0 €.

### D.4 Limitações

| # | Limitação | Impacto | Próximo passo |
|---|---|---|---|
| L1 | Não corrido contra Postgres (sem Docker local) | DDL e *upsert* compilam, mas falta prova real, incl. `COMMENT ON` e permissões | Correr o comando de D.2 contra a base da demo |
| L2 | `actualizado_em` do MITECO é a hora do pedido, não a do preço | «Actualizado 22:33» é verdade para a carga, não para o preço | Dizer «precios publicados en el Geoportal, consulta de las 22:33» |
| L3 | Proximidade posto–rota usa traçado OSRM de **automóvel** e distância a vértices (0,5 km) | Pode incluir postos de vias paralelas (ex.: Alcorcón, M-506) | Em Postgres, PostGIS `ST_DWithin` + filtro por `carretera`; traçado TomTom camião |
| L4 | `carretera` dos postos é heurística sobre a morada: 2.874 de 11.514 têm estrada | Filtrar por estrada perde postos | Usar `gasolineras_rota` (geometria), não `carretera` |
| L5 | Portagens: só A1 Lisboa–Porto (25,05 €) e Marateca–Caia (15,40 €) em classe 1 verificados; classes de pesados PT e autopistas ES 2026 ficam NULL | A pergunta «quanto pago com 5 eixos em Portugal» não tem resposta | Calculador Brisa/IP à mão (1×/ano) ou HERE/TollGuru |
| L6 | Restrições DGT: só o corredor A-5 e as pontes Out.–Dez.; 5 das 12 linhas são `inferido_do_padrao` (a extracção do PDF desalinhou a coluna da estrada) | Informativo; pode falhar uma linha | Rever as 5 linhas no PDF original; alargar a A-66/A-2/A-4 |
| L7 | Feriados ES 2027 sem regionais; sem municipais | «É feriado em Badajoz?» só para nacionais/regionais | Carregar a resolução BOE 2027 quando sair (fim de Outubro) |
| L8 | `rotas_referencia` e `tempo_cidades` vinham de fontes **não-comerciais** | Não podem aparecer num vídeo de vendas | ✅ 12/10: só correm com `AEMET_API_KEY` / `OPEN_METEO_API_KEY` / `TOMTOM_API_KEY`; sem chave, `sem_chave` e linhas antigas marcadas |
| L9 | Adaptador AEMET não provado contra a API real; a previsão municipal diária não dá mm de chuva | `precipitacao_mm` NULL nas cidades ES com AEMET | Pedir chave e gravar fixture real |
| L10 | Histórico MITECO: 1 pedido de 4,4 MB por dia (~5 s) | 365 dias ≈ 30 min na 1.ª carga | Carga inicial única; depois só D-1 |
