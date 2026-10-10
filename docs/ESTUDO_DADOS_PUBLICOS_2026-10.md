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
