# Dados externos: due diligence comercial (logística Ibéria)

Data: 10/10/2026 · Âmbito: licenças, preços e arquitetura das fontes do mundo para o Sky, e perguntas de venda · Complementa `ESTUDO_DADOS_PUBLICOS_2026-10.md` (anexos A, B, C). Não houve código nem git.

Pressupostos comerciais: planos Starter 490 € (1 fonte), Core 900 € (2), Plus 1.800 € (5), Enterprise sob proposta. Cada fonte pública conta como uma fonte do plano. As APIs do cliente (Solred, telemática) ligam-se como qualquer outra fonte. Não há add-on. Pode haver uma taxa de integração de ~100–200 € por fonte com trabalho à medida.

Legenda: ✅ uso comercial permitido · ⚠ permitido com condições ou por confirmar · ❌ não permitido sem pagar ou autorização. "Verificado" = página oficial lida a 10/10/2026. "Não verificado" = só fontes secundárias, ou a página não mostra o dado.

---

## Veredicto em 5 linhas

1. **Podemos usar comercialmente, de graça e com atribuição:** MITECO carburantes, DGT NAP DATEX II, AEMET, BOE (inclui restrições DGT), INE ES, CartoCiudad, BCE/Frankfurter.
2. **Têm de ser pagos ou substituídos:** Open-Meteo (Standard ~29 €/mês; Professional ~99 €/mês para histórico), Nager.Date (patrocínio de 10–20 $/mês, ou tabela própria a partir do BOE/DRE), OSRM demo (alojar nós ou usar TomTom), openrouteservice (plano pago sob proposta, ou alojar nós).
3. **Não usar até haver autorização escrita:** IPMA (só "sem fins lucrativos"), DGEG (não tem API nem licença), Infraestruturas de Portugal (não encontrei feed público).
4. **Nas APIs pagas, a melhor relação custo/valor é a TomTom:** perfil de camião e trânsito, 20 mil rotas e 20 mil geocodificações por mês grátis, depois 0,75 €/1.000 rotas. Isto dá menos de 3 € por cliente por mês ao nosso volume. A HERE serve para portagens em PT. Google e Mapbox ficam fora porque não têm perfil de camião.
5. **Arquitetura:** o passo 1 (esquema `mundo` partilhado, carregado por jobs) é a base de longo prazo e evolui para o passo 3. O passo 0 serve só para a demo e apenas com fontes de licença limpa.

---

## 1. Fontes públicas: uso comercial

| Fonte | Comercial? | Licença / base | Atribuição obrigatória | Limites / SLA | Se não for comercial: alternativa e preço |
|---|---|---|---|---|---|
| **MITECO Geoportal carburantes** (REST `ServiciosRESTCarburantes`) | ✅ (⚠ não há licença nomeada) | Aviso legal MITECO: reutilização "sin necesidad de autorización expresa", ao abrigo da Lei 37/2007 e do RD 1495/2011. **Verificado** | Citar a fonte. Não alterar os metadados de data de atualização. Não insinuar patrocínio | Sem limite publicado. Sem SLA. Espanha inteira = 12,8 MB / 15 s (Anexo C) | — |
| **DGT NAP DATEX II v3.7** (incidências) | ✅ (⚠) | A ficha NAP diz **CC BY**, "Licence and Free of charge", atualização a 1 min. **Verificado**. ⚠ O aviso legal geral da DGT (2022) proíbe "comercialización" de obras do portal. A licença da ficha prevalece para o conjunto de dados. Confirmar por email ao NAP | "Fuente: DGT" | Sem chave. Sem SLA | — |
| **AEMET OpenData** | ✅ | Lei 37/2007 (modif. Lei 18/2015): reutilização "para fines comerciales y no comerciales". **Verificado** | "© AEMET" ou "Fuente: AEMET". Em serviço de valor acrescentado: "Información elaborada utilizando, entre otras, la obtenida de la Agencia Estatal de Meteorología". Manter a data de atualização | Chave grátis. Limites não publicados. API instável | — |
| **BOE** (inclui resoluções DGT de restrições a pesados) | ✅ | "Licencia tipo" do BOE (27/06/2024): uso comercial, mundial, gratuito. **Verificado** | Dado modificado: "Basado en datos de la Agencia Estatal Boletín Oficial del Estado" + link boe.es | — | — |
| **INE ES** | ✅ | Aviso legal: "podrá tener objeto comercial o no comercial". O rodapé diz CC BY-SA 4.0. **Verificado** | "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es" + data | — | — |
| **INE PT** | ⚠ | Não consegui abrir a página de condições (erro técnico). **Não verificado** | Previsivelmente "Fonte: INE" | — | Confirmar antes de usar |
| **CartoCiudad (IGN)** | ✅ | **CC BY 4.0**. **Verificado** | Citar IGN/CartoCiudad + licença | Limites **não publicados**. Só Espanha | PT: geocodificação TomTom |
| **BCE / Frankfurter** | ✅ | BCE: reproduzir com o "BCE citado como fonte". Se o dado entrar num produto **vendido**, o comprador tem de ser avisado de que o dado é gratuito no site do BCE. Frankfurter: "free for commercial use", sem quotas, pode ser alojado em Docker. **Verificado** | "Fuente: BCE (tipos de referencia, gratuitos en ecb.europa.eu)" | Fixing diário ~16:00 CET. O BCE desaconselha usar para transações. MAD não existe | Dirham: fornecedor pago (por escolher) |
| **Nager.Date** | ❌ grátis / ✅ pago | ToS: "For commercial purposes we require active sponsorship". Proíbe montar um portal de feriados concorrente. **Verificado** | — | Sem garantia | **GitHub Sponsors: Commercial Starter 10 $/mês (1 ano), Basic 20 $/mês (2 anos + Docker)**. Melhor ainda: tabela própria a partir do BOE/DRE (grátis, mais correta, com trasladações) |
| **Open-Meteo** | ❌ grátis / ✅ pago | Grátis "only for non-commercial purposes". Dados CC BY 4.0 em todos os planos. **Verificado** | CC BY 4.0, obrigatória mesmo nos planos pagos | Grátis: 10k/dia, 300k/mês. Standard 1 M/mês; Professional 5 M/mês. "99,9 % target", sem SLA contratual. **Standard não inclui a API histórica**; o Professional inclui | **Standard ~29 €/mês · Professional ~99 €/mês** (a página oficial **não mostra preços**; valores de [ki-syndikat, 06/2026] e do [Substack oficial: 29 $]). **Não verificado no portal** |
| **OSRM demo** (`router.project-osrm.org`) | ❌ | "restricted to reasonable, non-commercial use-cases", máx. 1 pedido/s, sem SLA. **Verificado** | ODbL (OSM) | — | Alojar nós: perfil car Ibéria em ~3–6 GB RAM (extrapolação da wiki OSRM) → **r7g.large eu-west-1 ≈ 0,12 $/h ≈ 88 $/mês** on-demand, ou um pod no EKS existente. **Não serve para camião** → usar TomTom |
| **openrouteservice** | ⚠ | API pública grátis com chave e atribuição "© openrouteservice.org by HeiGIT \| Map data © OpenStreetMap contributors". O plano Standard (comercial) tem preço **só sob proposta**. A página de planos não abriu. **Não verificado** | Obrigatória | Grátis ~2.000 rotas/dia (estudo §1.3) | Alojar nós (open-source, perfil `driving-hgv`): ~1 r7g.large/xlarge (88–176 $/mês). Plano B se a TomTom ficar cara |
| **IPMA** | ❌ | Uso "pessoal ou público desde que dessa utilização não decorram finalidades lucrativas". Pede email a webmaster@ipma.pt a explicar o uso. **Verificado** | Fonte + logótipo + link | Sem garantia | Previsão PT: Open-Meteo pago. Avisos oficiais PT: pedir autorização escrita ao IPMA |
| **DGEG preços PT** | ❌ | Não encontrei API documentada, conjunto em dados.gov.pt nem licença. **Verificado (ausência)** | — | — | Médias nacionais: EU Weekly Oil Bulletin (aberto). Preço real da frota: cartão do cliente (Galp Frota/Solred, BYO). Pedido formal à DGEG |
| **Infraestruturas de Portugal / NAP PT** (`nap-portugal.imt-ip.pt`) | ❌ por agora | Não encontrei feed DATEX II público. O portal não devolveu conteúdo. **Não verificado** | — | — | TomTom Traffic Incidents (2,5 mil/mês grátis; preço acima disto **não verificado**) |

**Regra de produto (sai das licenças):** cada linha de dado público guarda `fuente`, `licencia`, `actualizado_origen` e `cargado_en`, e a resposta cita fonte e hora. Isto cumpre as cláusulas de atribuição e de "não alterar metadados de data" da AEMET, do BOE, do MITECO e do INE.

---

## 2. Fontes pagas: preço ao nosso volume

**Volume por cliente (pressuposto):** ~300 rotas e ~3.000 geocodificações por mês. Combustível e trânsito são refrescados de 30 em 30 min e partilhados por todos os clientes.

| Fornecedor | Modelo e preço verificado | Grátis | Custo/cliente/mês (estimativa) | Quem paga | Valor no pitch | Veredicto |
|---|---|---|---|---|---|---|
| **TomTom** Routing (camião) + Geocoding + Traffic | Pay-as-you-grow, sem compromisso. Routing **0,75 €/1.000**. Matrix 2,50 €. Waypoint Optimization 4,00 € ([docs.tomtom.com/pricing]). Geocoding e Incidents por 1.000: **não verificado** | **Por mês e por conta:** 20k Routing, 20k Geocoding, 2,5k Traffic Incidents, 20k Traffic Flow | Rotas: grátis até ~66 clientes. Geocodificação: 3k × ~0,75 €/1.000 ≈ **2,25 €** (sem cache; com cache de moradas, <1 €) | Nós | Alto: ETA de camião com trânsito, ADR, peso | ✅ **Escolha principal.** Fixar preços: o anúncio diz que quem se registar até 31/12/2026 mantém as tarifas de julho de 2026 até 2028 (**confirmar**) |
| **HERE** Routing v8 truck (+ `return=tolls`) | Camião: **0–5.000 grátis; 2,75 $/1.000** até 200k (página "supplemental pricing" sem data; tabela em branco na leitura) | 5k camião/mês | 300 × 2,75 $/1.000 ≈ **0,83 $** (os primeiros ~16 clientes cabem no grátis) | Nós | Portagens PT por classe na mesma resposta | ⚠ Usar só para portagens PT. Confirmar se as portagens são faturadas à parte |
| **TollGuru** | Starter 80 $/5k transações · Basic 260 $/20k · Standard 900 $/100k · Corporate 4.000 $/500k. **Verificado**. Transações por rota: depende do endpoint (~5, segundo o Anexo B) | Trial 14 dias | 300 rotas × 5 = 1.500 tx ≈ **24–26 $** (rateado no Basic) | Nós | Médio (A-5 não tem portagem; PT tem) | ❌ Caro face à HERE. Só se a HERE falhar em ES/PT |
| **Google Routes** | Essentials 5 $/1.000 (10k grátis) · Pro 10 $/1.000 (5k grátis) · Geocoding 5 $/1.000. **Verificado** | sim | ~2–4 $ | Nós | **Sem perfil de camião** | ❌ |
| **Mapbox** Directions | ~2 $/1.000 após 100k/mês (fontes secundárias). Perfis: driving-traffic, driving, walking, cycling | 100k | ~0 | Nós | Sem camião | ❌ |
| **PTV Developer** | Free só para testes ("not intended for production"); pago "sob contrato", preço sob proposta. **Verificado (sem preço)** | quota de teste | n/d | Nós | Referência europeia de camião e otimização | ⏸ Só se um Enterprise exigir otimização de rotas |
| **Meteomatics** | Basic grátis "strictly for non-commercial use" (500/dia). Business sob proposta | não comercial | n/d (sob proposta) | Nós | Igual ao Open-Meteo para o nosso caso | ❌ Open-Meteo a 29–99 € chega |
| **Open-Meteo** Standard / Professional | ~29 € / ~99 € por mês (não verificado no portal) | — | Fixo ÷ n.º de clientes | Nós | Tempo na rota. O histórico (só no Professional) permite cruzar tempo com viagens passadas | ✅ Standard já. Professional quando houver pergunta histórica |
| **project44 / Shippeo** | Quem paga é o carregador. Transportistas aderem grátis (project44) | — | 0 | Cliente do cliente | Baixo para PME transportista | ❌ Não integrar agora |
| **Solred API Movimentos** | O cliente contrata o serviço e recebe credenciais; até ~18 meses de histórico. Custo não publicado (indício de "sin costes") | — | 0 para nós | **Cliente (BYO)** | **Muito alto:** litros, €, posto e cartão reais | ✅ Primeiro conector de combustível em ES |
| DKV, UTA Edenred, Moeve StarRessa, Galp Frota | **Sem API pública** encontrada: portais (DKV Cockpit, cartoes.galp.pt) com exportação | — | 0 | Cliente (CSV) | Alto | ✅ Importar CSV (taxa de integração) |
| **Webfleet** (WEBFLEET.connect) | Subscrição do cliente ~15–35 €/veículo/mês (terceiros). Acesso à API por contrato | — | 0 | Cliente | Muito alto: km, consumo, horas, tacógrafo | ✅ BYO |
| **Geotab** (MyGeotab SDK) | SDK grátis; API "fully available to MyGeotab customers" | — | 0 | Cliente | Alto (dados CAN) | ✅ BYO |
| **Samsara** | API para clientes; alguns endpoints exigem licença Premier | — | 0 | Cliente | Baixo na Ibéria | ⚠ BYO se aparecer |
| **Movildata** (Verizon Connect) / **Frotcom** | Movildata: sem docs públicas. Frotcom: API REST para clientes (IT do cliente) | — | 0 | Cliente | Alto (Movildata em ES; Frotcom em PT) | ✅ BYO; a Movildata é a mais burocrática |
| **Wtransnet / Timocom / Teleroute** | Wtransnet sem API pública (parceria Alpega). Timocom: API para clientes. Teleroute: T-Interface | — | 0 | Cliente / parceria | Alto: preço de mercado por corredor e retornos | ⚠ Timocom BYO. Wtransnet só por parceria |

**Custo agregado de dados pagos (estimativa, sem cache):**

| Clientes | TomTom rotas | TomTom geocod. | HERE portagens (½ das rotas) | Open-Meteo | Total/mês | Por cliente |
|---|---|---|---|---|---|---|
| 10 | 0 € (3k < 20k) | 10k acima do grátis × 0,75 ≈ 7,5 € | 1,5k < 5k → 0 | 29 € | **≈ 37 €** | 3,7 € |
| 50 | 0 € (15k) | 130k × 0,75 ≈ 98 € | 7,5k − 5k = 2,5k × 2,75 $ ≈ 6 € | 99 € | **≈ 203 €** | 4,1 € |
| 100 | 10k × 0,75 ≈ 7,5 € | 280k × 0,75 ≈ 210 € | 10k × 2,75 $ ≈ 25 € | 99 € | **≈ 342 €** | 3,4 € |

Leitura: **as fontes de dados não são caras.** Por cliente custam menos de 1 % do Starter. O custo que pesa é o LLM (0,03 €/pergunta, memória do projeto). A geocodificação é a linha que mais cresce: com cache por morada normalizada (armazéns e clientes repetem-se), cai para menos de metade. **Confirmar se os termos da TomTom permitem essa cache** (secção de caching não verificada).

**Mais rentáveis para nós:** (1) os conectores BYO (telemática e cartão de combustível), com custo externo zero e o maior valor, porque são os dados reais do cliente; (2) o pacote público espanhol (MITECO, DGT, AEMET, BOE, INE), com custo zero; (3) TomTom + Open-Meteo Standard, por < 5 € por cliente. **Evitar:** Google, Mapbox, Meteomatics, PTV, TollGuru e project44.

**Nota sobre a contagem de fontes:** com "1 fonte pública = 1 fonte do plano", um cliente Starter que ligue os seus dados fica sem espaço para perguntas mistas, e as perguntas mistas são o pitch. Sugestão para o Lucas decidir: o catálogo "Datos públicos" conta como **1 fonte**, seja qual for o número de conjuntos.

**Taxa de integração:** 100–200 € cobre configurar uma API pronta (Solred, Geotab, Frotcom). Não cobre importar ficheiros DDD de tacógrafo, parsers de CSV por cartão nem a parceria Wtransnet. Para esses, manter os ~1.500 € do Anexo B.

---

## 3. As três opções do Anexo C a longo prazo

| Critério | Passo 0 — `rest-api` ao vivo | Passo 1 — esquema `mundo` partilhado, jobs + SQL | Passo 3 — ligação gerida "Datos públicos" (base `sky_world`) |
|---|---|---|---|
| **Exposição de licença** | 🔴 Alta. Chama a API a cada pergunta com a nossa chave, ou sem chave. As chamadas grátis "não-comerciais" (Open-Meteo, OSRM, Nager) entram em produção sem ninguém notar. Não há sítio para guardar a atribuição | 🟢 Baixa. Só se carregam fontes de licença limpa, com colunas `fuente/licencia/actualizado_origen`. Os resultados TomTom/HERE **não** se guardam (termos de cache por confirmar) | 🟢 A mais baixa. Catálogo curado, com licença por conjunto, aprovado uma vez |
| **Custo com mais clientes** | 🔴 Cresce com perguntas × clientes, e os free tiers esgotam-se | 🟢 Fixo: um job serve todos | 🟢 Fixo + quotas por tenant nas ferramentas pagas |
| **Frescura / consistência** | Frescura da origem, mas cada cliente vê um instante diferente. O MITECO `Fecha` é a hora do pedido, não do preço | 30 min (MITECO), 5 min (DGT), 1 h (tempo). O mesmo valor para todos, com carimbo de hora. **Dá histórico** (tendência, cruzar com viagens passadas) | Igual ao passo 1, com `sync_frequency` honrado e alerta de atraso |
| **Segurança multi-tenant** | 🟢 Não toca na base do cliente, mas as chaves vivem na config da ligação de cada tenant (defeito D1) | 🟡 Se a base partilhada for uma ligação de sistema só-leitura: 🟢. Se se **copiar** o `mundo` para o `ops` de cada tenant (opção B do Anexo C): N cópias, N jobs, divergências | 🟢 Base partilhada só com dados públicos e papel só-leitura. A junção é feita no sky-ai (merger DuckDB, em memória por pedido) ou por `postgres_fdw` **da** base do tenant **para** `sky_world`. Os dados do cliente nunca são escritos na base partilhada |
| **Fiabilidade (falhas a montante)** | 🔴 Se a AEMET ou o MITECO caem, a pergunta falha ou o LLM inventa | 🟢 Serve o último valor com hora ("actualizado 13:05") | 🟢 Igual, mais uma página de estado por conjunto |
| **Latência para voz (<2 s)** | 🔴 1,4–15,3 s por chamada; a demo paralela deu 8,7–9,1 s (Anexos A e C) | 🟢 SQL local em milissegundos (PostGIS `ST_DWithin`) | 🟢 Igual. Ao vivo só a rota TomTom (~1 s) |
| **Dependência de fornecedor** | 🔴 O LLM conhece o formato de cada API; trocar de fonte obriga a reescrever descrições | 🟢 Esquema nosso, normalizado: trocar a origem não muda as perguntas | 🟢 O mesmo |
| **Esforço** | 2–3 h | 3–4 dias | 1,5–2 semanas |

**Recomendação:** o **passo 1 é a fundação** e deve ser construído já com o desenho do passo 3: base `sky_world` própria, papel só-leitura, colunas de licença e hora, jobs no Beat ou CronJob. O passo 0 fica **só** para a demo e só com fontes de licença limpa. As APIs pagas por pedido (rota e geocodificação TomTom) entram como **ferramentas do servidor** com a chave guardada no backend, cache de 15 min e quota por tenant. Nunca como `rest-api` com chave na config do cliente.

**Caminho de migração:**

| Quando | O quê | Custo externo/mês |
|---|---|---|
| Vídeos (esta semana) | Passo 0 só com Frankfurter, mais Open-Meteo **com chave Standard**. O **vídeo de vendas é uso comercial**: não usar OSRM demo, Nager grátis nem Open-Meteo grátis. Passo 1 com MITECO, DGT, feriados (BOE/DRE), WOB e portagens manuais. Opção B (tabelas também no `ops` da demo) **só na demo** | ~29 € |
| 1.º cliente de logística | `sky_world` partilhada, só-leitura, ligada como ligação de sistema. Ferramentas TomTom (rota de camião + geocodificação) no servidor. Corrigir D1–D3 e D6 para os conectores BYO (Solred, telemática) | ~30–40 € |
| 2.º cliente | Passo 3: tipo "Datos públicos", catálogo, `sync_frequency` real, D4 (DuckDB sobre linhas de API), junções por merger ou FDW, alertas de frescura | ~40–100 € |
| > 50 clientes, ou TomTom > ~150 €/mês | Alojar ORS `driving-hgv` como segunda opção (~88–176 $/mês). Professional Open-Meteo para histórico. HERE para portagens PT | ~200–350 € |

---

## 4. Perguntas estratégicas para chamadas de descoberta (ES)

**Base de cálculo (estimativa, frota de 30 camiões; 20 camiões = ×0,67; 50 camiões = ×1,67):** 120.000 km/camião/ano → 3,6 M km. Consumo de 32 l/100 km → **1.152.000 l/ano**. Gasóleo a ~1,90 €/l (mediana medida na A-5 a 10/10: 1,949 €/l, Anexo A). Custo do Observatório MITMA T1 2026: **1,79 €/km em carga, 1,52 €/km em vazio, 182.809 €/ano por articulado** (via [trans.info], não verificado na fonte oficial). Faturação ≈ custo ≈ 5,5 M€/ano. Hora de motorista ~22 €/h (pressuposto).

| # | Pregunta (ES) | Qué revela | Datos del cliente + fuente pública | Impacto orientativo (30 camiones, **estimación**) |
|---|---|---|---|---|
| 1 | «¿Cuánto os cuesta al año repostar en la estación equivocada dentro de vuestras rutas habituales?» | Mostra a margem perdida em cada abastecimento; a diferença na A-5 chegou a 48 cént./l num só dia | Tarjeta (Solred/DKV: litros, posto, preço) + MITECO histórico e postos ≤3 km da rota | Captar 4 cént./l em 50 % dos litros: 576.000 × 0,04 = **≈ 23.000 €/año** (20 cam.: 15k; 50: 38k) |
| 2 | «¿Estáis facturando la revisión del precio por gasóleo que el RDL 9/2026 hace obligatoria, separada en la factura y en los dos sentidos?» | Mostra a receita legal não cobrada. O art. 38 da Lei 15/2009 é obrigatório desde o RDL 3/2022 e "ineludible" desde o RDL 9/2026 | Contratos/faturas por cliente + índice semanal oficial do gasóleo sem impostos (Ministério/BOE) | 30 % da faturação sem cláusula × peso do gasóleo 0,4 × subida de 10 %: 5,5 M × 0,3 × 0,4 × 0,10 = **≈ 66.000 €/año** |
| 3 | «¿Habéis pedido todas las ayudas al gasóleo profesional de julio a septiembre (RDL 18/2026: 0,10/0,15/0,20 €/l)?» | Mostra dinheiro esquecido na AEAT: a ajuda só se aplica a abastecimentos em Espanha com o cartão de gasóleo profissional | Litros por matrícula e por país (cartão) + importes AEAT/BOE + limite de 50.000 l/veículo/ano | 30 × 3.200 l/mes × 3 meses × 0,15 € = **≈ 43.000 €** só no 3.º trimestre (se nada foi pedido) |
| 4 | «En Lisboa–Madrid, ¿os sale mejor repostar antes o después de la frontera esta semana, contando la ayuda española?» | Transforma o preço ES/PT, que muda todas as semanas, numa regra de abastecimento por rota | Viagens transfronteiriças + litros + WOB semanal ES vs PT + ajudas ES/PT | 40 % dos litros transfronteiriços × 10 cént./l de diferença: 460.000 × 0,10 = **≈ 46.000 €/año** (sinal e valor mudam todas as semanas) |
| 5 | «¿Cuántos km hacéis en vacío y cuánto os cuestan frente al Observatorio de costes del Ministerio?» | Mostra os km vazios, a maior fuga de margem, com uma referência oficial para negociar | Telemática (km com e sem carga) + Observatório MITMA (1,52 €/km em vazio) | Baixar 2 p.p. de vazio: 3,6 M km × 0,02 × 1,52 = **≈ 109.000 €/año** |
| 6 | «¿Qué clientes os pagan por encima de 60 días y cuánto os cuesta financiar su gasóleo?» | Mostra o custo financeiro dos maus pagadores e o direito a juros e à indemnização legal (Lei 3/2004: taxa BCE + 8 p.p.; 40 €/fatura) | Faturas e cobranças + taxa BCE (Frankfurter/BCE) + taxa de mora semestral do BOE | DSO 85 vs 60 dias: 25/365 × 5,5 M = 377.000 € em dívida × ~10 % = **≈ 38.000 €/año** reclamáveis ou de custo |
| 7 | «¿Cuántas horas de conductor perdisteis el último año por viajes que cayeron en festivo o en restricción DGT?» | Mostra o planeamento cego ao calendário regional e às restrições a pesados | Viagens planeadas e reais + feriados BOE/DRE + resolução DGT 2026 (BOE) | 9 camiões × 12 dias × 4 h × 22 €/h = **≈ 9.500 €/año**, mais entregas falhadas |
| 8 | «¿Vuestros tiempos estándar por ruta son reales o los pagáis en horas extra y penalizaciones?» | Compara o tempo orçamentado com o real e com a ETA de camião com trânsito | `standard_minutes` + viagens reais + TomTom truck/trânsito + incidências DGT | 8.400 viagens × 20 % com +1 h × 22 € = **≈ 37.000 €/año**, mais penalizações por atraso |
| 9 | «¿Estáis cotizando peajes que ya no pagáis, por ejemplo la A-5, que es autovía, o en Portugal las A41/A19/A8, exentas para clase 3–4 desde 2026?» | Mostra preços errados que fazem perder concursos (ou margem, no sentido inverso) | Custos padrão por rota + tabela de portagens ES/PT (Ordem anual; Lei 6/2026 PT; ver Anexo C) | Demo: 28,80 € imputados em Badajoz–Madrid vs 0 € reais. 6 rotas ≈ **1.900 €/año** só na demo; numa frota real, sobretudo efeito no preço proposto |
| 10 | «¿Qué viajes de la semana tienen viento fuerte, lluvia o calor extremo, y cuánto os cuesta en consumo y en frío?» | Liga o tempo ao consumo, ao frio do frigorífico e à segurança (rajadas com caixa vazia) | Viagens + telemática (consumo) + Open-Meteo na rota + avisos AEMET | +3 % de consumo em ~60 dias/ano: 1.152.000 × 60/365 × 0,03 × 1,90 = **≈ 10.800 €/año** |

**Total que ressoa num "discovery":** as perguntas 1+2+3+5 somam **> 200.000 €/ano** numa frota de 30 camiões, ou seja, ~4 % da faturação. Dizer sempre "estimación con vuestros datos de ejemplo; con los reales lo calcula Sky en minutos".

### 2 perguntas "killer" para o vídeo (multi-salto)

| Pregunta | Saltos | Resposta esperada (ilustrativa, recalcular com os dados da demo) |
|---|---|---|
| **K1.** «Del último trimestre, ¿cuánto dinero nos dejamos en la mesa entre gasóleo mal repostado, revisión de precio por gasóleo que no facturamos y ayudas al gasóleo profesional que no pedimos?» | Litros e postos (cartão) → MITECO histórico na rota → índice oficial RDL 9/2026 × faturas por cliente → litros ES × ajuda RDL 18/2026 | «≈ 65.000 €: 5.800 € de repostaje, 16.500 € de revisión no facturada (3 clientes), 43.200 € de ayudas sin pedir. Fuentes: MITECO, BOE, AEAT; actualizado 10/10 13:05.» |
| **K2.** «¿Qué entregas de mañana van a llegar tarde, por festivo en destino, restricción DGT, viento o una incidencia en ruta, y a qué clientes aviso hoy, ordenados por penalización?» | Entregas de amanhã → feriados regionais (BOE/DRE) → restrições DGT → Open-Meteo na rota → incidências DGT ativas → contratos (penalização) | Tabela entrega × motivo × atraso estimado × € de penalização + texto de aviso pronto a enviar |

**Avisos ao apresentar:** dizer "precio de surtidor publicado", não "precio de vuestra flota". Usar texto legal curado com data (RDL 9/2026, 18/2026; Lei 3/2004) e a frase "informativo, no sustituye asesoría". Os importes de ajudas e as isenções de portagem PT foram vistos em fontes secundárias: **validar no BOE/DRE antes de gravar.**

---

## Por confirmar (antes de vender)

1. Preço oficial do Open-Meteo Standard/Professional (o portal não o mostra).
2. Termos de cache/armazenamento da TomTom (secção "caching") e preço por 1.000 de Geocoding e Traffic Incidents.
3. Se a HERE fatura portagens à parte do Routing truck. A página "supplemental pricing" (01/04/2026) mostrou tabelas em branco.
4. Licença da DGT NAP: email a confirmar que a CC BY da ficha prevalece sobre o aviso legal geral.
5. IPMA e DGEG: pedidos formais de autorização. INE PT: condições.
6. Preço do plano comercial do openrouteservice (HeiGIT).
7. Tipo ordinário de devolução do gasóleo profissional ES em 2026, e se houve prorrogação das ajudas depois de setembro. Ajudas PT depois de 30/06/2026.
8. Valores oficiais do Observatório de custos MITMA (só os vi via trans.info).

## Fontes (consultadas a 10/10/2026)

- Open-Meteo: https://open-meteo.com/en/pricing · https://open-meteo.com/en/terms · preço (secundário): https://www.ki-syndikat.de/tools/open-meteo/ · https://openmeteo.substack.com/p/api-subscriptions-for-commercial
- OSRM demo: https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server · memória: https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements · EC2: https://www.doit.com/compute/spot/eu-west-1/r7g.large
- openrouteservice: https://openrouteservice.org/?p=940 · https://apis.io/plans/openrouteservice/openrouteservice-plans-pricing/
- Nager.Date: https://nagerholidays.com/legal/termsofservice · https://github.com/sponsors/nager
- Frankfurter: https://frankfurter.dev · BCE: https://www.ecb.europa.eu/home/disclaimer/html/index.en.html · https://www.ecb.europa.eu/stats/exchange/eurofxref/html/index.en.html
- AEMET: https://www.aemet.es/es/nota_legal
- MITECO aviso legal: https://www.miteco.gob.es/es/atencion-al-ciudadano/aviso-legal.html · condições históricas: https://datos.gob.es/es/noticias/reutilizacion-de-informacion-del-sector-publico-apps-de-combustible
- DGT NAP: https://nap.dgt.es/en/dataset/incidencias-dgt-datex2-v3-7 · DGT aviso legal: https://www.dgt.es/contenido/aviso-legal/
- BOE: https://www.boe.es/informacion/aviso_legal/index.php
- INE ES: https://www.ine.es/ss/Satellite?L=es_ES&c=Page&cid=1254735849170&p=1254735849170&pagename=Ayuda%2FINELayout
- CartoCiudad: https://datos.gob.es/es/catalogo/e0dat0002-servicio-rest-de-geocodificacion-de-espana-cartociudad
- IPMA: https://api.ipma.pt
- DGEG: https://precoscombustiveis.dgeg.gov.pt · DL 243/2008: https://diariodarepublica.pt/dr/detalhe/decreto-lei/243-2008-443909
- NAP PT: https://nap-portugal.imt-ip.pt
- TomTom: https://docs.tomtom.com/pricing · https://docs.tomtom.com/pricing/price-announcement
- HERE: https://www.here.com/pricing/supplemental-pricing · https://developers.here.com/plans
- TollGuru: https://tollguru.com/toll-api-pricing-plans
- Google: https://developers.google.com/maps/billing-and-pricing/pricing
- Mapbox: https://docs.mapbox.com/api/navigation/directions/ · https://www.woosmap.com/blog/mapbox-pricing
- PTV: https://support.ptvlogistics.com/hc/en-001/articles/28245624022940
- Meteomatics: https://meteomatics.com/en/sign-up-weather-api-free-basic-account
- Solred: https://www.repsol.es/autonomos-y-empresas/solred/mi-solred/api-movimientos/
- Geotab: https://www.geotab.com/au/fleet-management-solutions/software-integration/ · Samsara: https://kb.samsara.com/hc/en-us/articles/20572537516557 · Frotcom: https://frotcom.com/features/api-integration-external-software
- project44: https://www.project44.com/carriers/
- RDL 9/2026 (cláusula gasóleo): https://periscopiofiscalylegal.pwc.es/real-decreto-ley-9-2026-de-14-de-abril-de-medidas-urgentes-en-materia-de-transporte/ · https://www.penningtonslaw.com/insights/novedades-en-la-revision-del-precio-del-transporte-por-carretera-impacto-de-los-rdl-7-2026-y-9-2026/
- RDL 18/2026 (ajudas gasóleo profissional): https://sede.agenciatributaria.gob.es/Sede/todas-gestiones/beneficios-fiscales-autorizaciones/medidas-tributari_____ica-derivada-conflicto-belico-medio/ayuda-sufragar-precio-gasoleo-consumido-devolucion/nota-informativa-18.html · limite 50.000 l: https://administracion.gob.es/pag_Home/Tu-espacio-europeo/derechos-obligaciones/empresas/impuestos/especiales/hidrocarburos.html
- Observatório de custos T1 2026 (secundário): https://trans.info/es/costes-al-alza-y-caida-de-la-actividad-en-el-transporte-por-carretera-en-espana-en-el-primer-trimestre-de-2026-486232
- Gasóleo profissional PT 2026 (secundário): https://www.noticiasaominuto.com/economia/2025774/gasoleo-profissional-governo-lanca-apoio-de-17-centimoslitro

<!-- fim do documento -->
