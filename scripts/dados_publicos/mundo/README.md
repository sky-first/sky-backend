# Carregador «mundo» — dados públicos em tabelas

Descarrega fontes públicas, transforma-as em tabelas planas e faz *upsert* por chave natural no esquema Postgres `mundo`. Idempotente: correr duas vezes dá o mesmo resultado. Cada fonte corre isolada: se uma falha, as outras continuam e o erro fica em `mundo.fontes`.

Contexto e decisões: `docs/ESTUDO_DADOS_PUBLICOS_2026-10.md` (Anexos C e D) e `docs/DADOS_EXTERNOS_COMERCIAL_2026-10.md` (licenças).

## Como correr

```bash
cd sky-poc-backend

# Postgres (cria o esquema e as tabelas se não existirem)
.venv/Scripts/python.exe scripts/dados_publicos/carregar_mundo.py --dsn postgresql://USER:PASS@HOST:5432/BASE
# ou
MUNDO_DSN=postgresql://USER:PASS@HOST:5432/BASE .venv/Scripts/python.exe scripts/dados_publicos/carregar_mundo.py

# Só algumas fontes
... carregar_mundo.py --so gasolineras --so incidencias

# Teste local sem Docker (SQLite, tabelas sem prefixo «mundo.»)
... carregar_mundo.py --sqlite mundo.sqlite --dias-historico 30
```

Opções: `--dias-historico N` (histórico MITECO, omissão 7; 1 pedido de ~4,4 MB por dia, ~5 s cada), `--semanas-ue N` (Weekly Oil Bulletin, omissão 52), `--festivos-nager` (completa feriados com Nager.Date — **licença não-comercial**, só para testes), `-v`.

Variáveis de ambiente: `MUNDO_DSN`, `AEMET_API_KEY` (se existir, a previsão AEMET substitui o Open-Meteo nas 5 cidades espanholas).

Saída: tabela-resumo com estado, linhas, duração e hora do dado por fonte. Código de saída 1 só se **todas** as fontes falharem.

## Tabelas

| Tabela | Chave | Fonte | Notas |
|---|---|---|---|
| `fontes` | nome | — | Licença, atribuição, uso comercial, última carga, hora do dado, linhas, erro |
| `gasolineras_precio` | id_estacion | MITECO | Espanha inteira (~11.500 postos). `actualizado_em` = campo `Fecha`, que é a **hora do pedido** (o MITECO refresca de 30 em 30 min). Postos que saem da fotografia são apagados. `carretera`/`pk` por heurística sobre a morada |
| `gasolineras_rota` | origem, destino, id_estacion | MITECO + traçado OSRM | Postos a ≤5 km de cada rota da demo, com `dist_km` e `km_desde_origem` (substitui o PostGIS na demo) |
| `gasoleo_historico_diario` | data, provincia | MITECO histórico | Mín/média/mediana/máx do Gasóleo A por província + `ESPAÑA`. `origem` = historico (00:00 do dia) ou actual (fotografia de hoje) |
| `gasoleo_ue_semanal` | data, pais | Weekly Oil Bulletin | ES, PT e UE, €/l com impostos. Única fonte aberta com preço de Portugal |
| `incidencias_trafico` | id | DGT DATEX II v3.7 | `activa=false` quando sai do feed; apagadas ao fim de 30 dias |
| `festivos` | chave (`pais|regiao|data`) | BOE-A-2025-21667, Código do Trabalho art. 234.º | ES 2026 nacionais + Extremadura, Madrid, Andalucía (com trasladações 02/11 e 07/12); ES 2027 provisório (só nacionais não substituíveis); PT 2026–2027. `regiao` NULL = nacional |
| `cambio_eur` | data, moeda | BCE via Frankfurter | 90 dias, ~30 moedas |
| `tempo_cidades` | cidade, data | Open-Meteo (ou AEMET) | 7 dias, 10 cidades da demo |
| `portagens` | corredor, origem, destino, classe, pais | Tabela manual | 2026. **NULL quando o preço não foi verificado** (ver `nota`). Rotas 100 % espanholas da demo = 0 € (A-5, A-66) |
| `restricoes_pesados` | data, carretera, pk_inicio, pk_fim, sentido | Resolução DGT 2026, Anexo II | Corredor A-5 (Madrid–Talavera) nas pontes de Out./Nov./Dez. `confianca` = lido_no_pdf ou inferido_do_padrao |
| `rotas_referencia` | origem, destino | OSRM demo | 20 pares da sementeira. Camião = km a 80 km/h + 45 min por cada 4h30 (Reg. 561/2006) |

Os nomes das cidades são **exactamente** os de `ops.routes.origin/destination` (Lisboa, Porto, Coimbra, Braga, Viseu, Badajoz, Mérida, Almendralejo, Sevilla, Madrid), para os JOIN funcionarem.

## Licenças e atribuição (o vídeo de vendas é uso comercial)

| Fonte | Comercial | Atribuição a mostrar | Nota |
|---|---|---|---|
| MITECO carburantes | ✅ | «Fuente: Ministerio para la Transición Ecológica» | Lei 37/2007, RD 1495/2011. Não alterar a data de actualização |
| DGT DATEX II | ✅ (⚠) | «Fuente: DGT» | Ficha NAP diz CC BY; confirmar por email ao NAP que prevalece sobre o aviso legal geral da DGT |
| BOE (feriados ES, restrições DGT) | ✅ | «Basado en datos de la Agencia Estatal Boletín Oficial del Estado» + boe.es | Licencia tipo do BOE |
| Diário da República (feriados PT) | ✅ | «Fonte: Diário da República» | Legislação pública |
| BCE / Frankfurter | ✅ | «Fuente: BCE (tipos de referencia, gratuitos en ecb.europa.eu)» | Se o dado entra num produto vendido, o comprador deve saber que é gratuito no BCE; não usar para transacções |
| Weekly Oil Bulletin | ✅ | «Fonte: Comissão Europeia, Weekly Oil Bulletin» | Reutilização com citação |
| AEMET OpenData | ✅ | «Fuente: AEMET» / «Información elaborada utilizando, entre otras, la obtenida de la Agencia Estatal de Meteorología» | Chave grátis; só corre com `AEMET_API_KEY` |
| Open-Meteo grátis | ❌ | «Weather data by Open-Meteo.com (CC BY 4.0)» | `licenca = nao-comercial (Open-Meteo Standard ~29€/mês para uso comercial)` |
| OSRM demo | ❌ | «© OpenStreetMap contributors» | `licenca = demo-nao-comercial`; produção: TomTom Routing (perfil camião, 20.000 rotas/mês grátis) |
| Nager.Date | ❌ sem patrocínio | — | Só com `--festivos-nager`; linhas marcadas `nao-comercial` |

O mesmo texto está em `mundo.fontes` (colunas `licenca`, `atribuicao`, `uso_comercial`), para a resposta do Sky citar fonte e hora.

## Cadência de refresco

| Fonte (`--so`) | Cadência | Porquê |
|---|---|---|
| gasolineras | 30 min | O MITECO refresca preços de meia em meia hora |
| incidencias | 5 min | Feed DGT muda ao minuto; 5 min chega e poupa pedidos |
| tempo | 6 h | `update_interval` dos modelos (ECMWF/ICON) |
| cambio | diária, 16:30 CET | Fixing BCE ~16:00 CET, sem fins de semana |
| gasoleo_historico | diária, 01:00 | Dia anterior fechado |
| gasoleo_ue | semanal (quinta) | Boletim semanal |
| festivos | mensal | Muda 1×/ano; verificar a resolução BOE de Outubro |
| portagens, restricoes | anual (Janeiro) + resoluções avulsas | Tabelas manuais |
| rotas | mensal | Rede viária muda pouco; em produção trocar por TomTom |

## CronJob Kubernetes (proposta — não aplicado)

Um CronJob por cadência, com a imagem do backend e o DSN num Secret. Exemplo para o MITECO (30 min):

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mundo-gasolineras
  namespace: sky
spec:
  schedule: "*/30 * * * *"
  timeZone: "Europe/Madrid"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 2
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 600
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: carregar
              image: <ECR>/sky-backend:<tag>
              command: ["python", "scripts/dados_publicos/carregar_mundo.py", "--so", "gasolineras"]
              env:
                - name: MUNDO_DSN
                  valueFrom:
                    secretKeyRef: { name: sky-mundo-db, key: dsn }
              resources:
                requests: { cpu: 100m, memory: 256Mi }
                limits: { memory: 512Mi }
```

Os outros: `incidencias` `*/5 * * * *`; `tempo` `0 */6 * * *`; `cambio` `30 16 * * 1-5`; `gasoleo_historico` `0 1 * * *` com `--dias-historico 2`; `gasoleo_ue` `0 9 * * 4`; `festivos rotas` `0 3 1 * *`; `portagens restricoes` `0 4 2 1 *`. `rotas` corre antes de `gasolineras` no primeiro arranque (a proximidade posto-rota lê o traçado gravado).

O utilizador do DSN precisa de `CREATE` no esquema `mundo` (só na 1.ª corrida) e de escrita nas tabelas; o sky-ai liga-se com um papel só-leitura.

## Testes

```bash
.venv/Scripts/python.exe -m pytest src/tests/test_mundo_miteco.py --no-cov -p no:cacheprovider
```

Ficheiros `src/tests/test_mundo_*.py`, sem rede, com respostas gravadas em `fixtures/` (MITECO, DATEX II, Nager, Frankfurter, Open-Meteo, OSRM). `fixtures/aemet_diaria_SINTETICO.json` foi escrito à mão segundo o formato documentado (sem chave AEMET não houve resposta real para gravar).
