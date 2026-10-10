# Planos e limites — desenho, lacunas e testes (10/10/2026)

> «Tudo isso tem que bloquear. Um plano foi estabelecido, tem que ser trocado
> só na consola. E também podemos trocar valores diferentes, dependendo se o
> cliente pagar.» — Lucas, 10/10/2026

Fonte dos números: proposta oficial (`Sky First Labs - Mopa ES.pdf`, pág. 13),
igual para todos os clientes.

## 1. As decisões (do Lucas, 10/10)

| # | Decisão |
|---|---|
| D1 | Uma tabela só de planos no código: Starter · Core · Plus · Enterprise. |
| D2 | **Todos os limites bloqueiam.** Nada de «avisamos e não cortamos». |
| D3 | Só a Consola (equipa SkyFirst) muda o plano. Nenhum utilizador do cliente, nem o super_admin. |
| D4 | A Consola pode dar a um cliente valores à medida («plano especial»: p.ex. Starter com 2 ligações). |
| D5 | O chat conta perguntas. |
| D6 | Há limite de GB, a propor (secção 3). |
| D7 | Tipos de ligação não são limitados por plano. |
| D8 | Utilizadores ilimitados em todos os planos (o documento promete-o). |

## 2. A tabela

| | Starter | Core | Plus | Enterprise |
|---|---|---|---|---|
| €/mês | 490 | 900 | 1.800 | contrato |
| Fontes de dados (ligações) | **1** | **2** | **5** | Consola |
| Áreas vigiadas (agentes) | **10** | **30** | **100** | Consola |
| Perguntas / mês (chat, voz, app, web **e** corridas de agentes) | **500** | **2.000** | **8.000** | Consola |
| Avisos: intervalo mínimo de um agente | **1 dia** | **1 hora** | **15 min** | Consola |
| Armazenamento (proposta, §3) | **10 GB** | **50 GB** | **200 GB** | Consola |
| Utilizadores | ilimitados | ilimitados | ilimitados | ilimitados |

«Avisos diários / diários e imediatos / contínuos» do documento traduz-se no
intervalo mínimo com que um agente pode correr. É a única forma de o fazer
cumprir: um agente do Starter não pode ser agendado de hora a hora.

Uma corrida de agente conta como uma pergunta: custa o mesmo, e contá-las à
parte convidava a contornar o limite criando agentes (já era a regra em
`tectos_do_plano.py`).

## 3. Proposta de GB

**O que fica connosco** (os dados do cliente ficam no servidor dele; nós só
lemos):
- a base de dados do cliente na nossa infraestrutura (conversas, achados dos
  agentes, páginas, glossário, metadados);
- os ficheiros carregados (anexos, documentos de conhecimento).

**Medida:** `pg_database_size` da base do cliente + soma de `file_uploads.size_bytes`.

**Custo:** armazenamento RDS gp3 em eu-west-1 ≈ 0,13 €/GB·mês, com cópias de
segurança incluídas até ao tamanho da base. Com o limite cheio:

| Plano | GB | Custo/mês com o limite cheio | % da mensalidade |
|---|---|---|---|
| Starter | 10 | ≈ 1,30 € | 0,3 % |
| Core | 50 | ≈ 6,50 € | 0,7 % |
| Plus | 200 | ≈ 26 € | 1,4 % |
| Enterprise | Consola (sugestão de partida: 500) | ≈ 65 € | — |

O custo não é o que limita; é a protecção contra um cliente que nos usa como
disco (o «terabyte» de que falaste). 10/50/200 dá folga larga a uso normal: a
base do sandbox, com 3 projectos de demonstração completos, tem hoje menos de
1 GB.

**O que bloqueia ao passar o limite:** carregar ficheiros e indexar
documentos (HTTP 402 com a mensagem do plano). As conversas continuam a
gravar-se: cortar o histórico a meio de uma conversa partia a aplicação, e o
crescimento por conversas é ínfimo.

## 4. O estado de hoje (medido em produção, só leitura)

| Cliente | Plano no registo | Plano que a aplicação aplica |
|---|---|---|
| sandbox | starter | **enterprise, sem limites** |
| skyfirstlabs | strategic | enterprise, sem limites |

**Nenhum cliente tem limite nenhum.** A causa é a mesma do fantasma de 03/10:
o `get_limits(db)` corre com a sessão já encaminhada para a **base do
cliente**, e lá cria sozinho uma linha `tenant_plan_limits` em «enterprise».
A Consola lê e grava a linha noutra base. São duas linhas para o mesmo
cliente, e quem bloqueia lê a errada.

## 5. Lacunas → correcção

| # | Lacuna | Gravidade | Correcção |
|---|---|---|---|
| L1 | O plano aplicado vive na base do cliente e nasce «enterprise» | 🔴 | Plano e tectos **só na base da plataforma** (`tenant_plan_limits` da plataforma, chave `tenant_id`). Todas as verificações abrem uma sessão da plataforma; a linha na base do cliente deixa de ser lida |
| L2 | Ligações não têm limite | 🔴 | `max_connections` + verificação em **todos** os caminhos que criam ligações |
| L3 | Perguntas só contadas, nunca bloqueadas | 🔴 | Reserva atómica antes de responder: `UPDATE … SET n = n+1 WHERE n < max RETURNING`. Sem linha devolvida = 402 |
| L4 | `/ai/chat`, stream da app, voz e agentes não contam | 🔴 | Contam todos, pela mesma função |
| L5 | O super_admin muda o próprio plano (`PUT /tenant-plan`) | 🔴 | Rota fechada a quem não é da equipa SkyFirst |
| L6 | `/agents/insight` não verifica o limite de agentes | 🟠 | Verificação no serviço, não na rota (pega nos 4 caminhos) |
| L7 | 5 tabelas de planos que não batem certo | 🟠 | `planos.py` é a única; as outras passam a derivar dela ou saem |
| L8 | Armazenamento não bloqueia | 🟠 | Verificação no upload e na indexação |
| L9 | Intervalo dos agentes não depende do plano | 🟠 | Verificação ao criar e ao editar o agendamento |
| L10 | Limite de utilizadores conta pertenças a projectos | 🟡 | Sai: utilizadores ilimitados (D8) |
| L11 | «Beats» por utilizador com números próprios | 🟡 | Deixa de bloquear; a quota é a de perguntas do plano |
| L12 | Consola: «% de fontes» calculado sobre utilizadores; `capacity_used` nunca escrito | 🟡 | O painel lê os contadores reais (contagens vivas + linha da plataforma) |
| L13 | Sem plano especial | 🟠 | A Consola edita cada tecto de um cliente; a linha fica marcada `personalizado` |

## 6. Testes (cada um prova um comportamento, não uma linha de código)

1. **Starter não cria a 2.ª ligação** (402, mensagem com o plano e o seguinte), e a 1.ª cria-se.
2. Apagar a ligação liberta o lugar. Uma ligação apagada (soft delete) não conta.
3. **Duas criações em simultâneo** com 0 de 1 usada: só uma passa.
4. Plano especial: Starter com `max_connections=2` na Consola cria a 2.ª e falha a 3.ª.
5. Pergunta 501 de um Starter: 402 no chat, na app (stream), na web e na voz (a Sky diz-o em voz alta, não fica muda). A 500.ª passa.
6. Uma pergunta que falha (erro do modelo) não gasta quota.
7. **Corridas de agentes contam** e param quando a quota acaba; o agente fica com o motivo visível, não «avariado».
8. Viragem do mês repõe o contador (fuso Europe/Lisbon e Europe/Madrid, não UTC à meia-noite errada).
9. Agente do Starter com intervalo de 1 hora: 422 ao criar **e** ao editar.
10. 11.º agente de um Starter: 402 em `/agents` **e** em `/agents/insight`.
11. Upload que passaria os 10 GB de um Starter: 402. O que cabe, passa.
12. **super_admin do cliente não muda o plano** (`PUT /tenant-plan` → 403). A equipa SkyFirst muda-o.
13. Consola: baixar de Plus para Starter com 3 ligações activas → 422 com o que excede (sem perder dados).
14. A base do cliente com uma linha `tenant_plan_limits` «enterprise» (o caso de hoje) **não** dá limites ilimitados.
15. Um cliente sem linha na plataforma recebe os tectos do plano do registo, não «enterprise».
16. Enterprise: valores da Consola; `null` só quando a Consola o põe explicitamente.

## 7. Revisão crítica (como isto pode falhar)

| Ataque / falha | Defesa |
|---|---|
| Criar ligações por outro caminho (seed de demonstração, ligar uma API, Google Sheets, provisionamento da Consola) | A verificação vive no **serviço** que insere em `data_connections`, não nas rotas. Teste que percorre os caminhos que inserem |
| Corrida: dois pedidos ao mesmo tempo | Ligações e agentes: `pg_advisory_xact_lock(tenant)` na base da plataforma durante verificar + inserir. Perguntas: reserva atómica num só `UPDATE` |
| Contar duas vezes (retry do cliente, stream que reabre) | A reserva leva o id do pedido; um retry com o mesmo id não reserva de novo |
| Base da plataforma indisponível | Falha **fechada** (503): sem plataforma também não há login. Nunca «ilimitado por omissão» — foi assim que chegámos aqui |
| Pedido no contexto da plataforma (semente `sky`, tarefas internas) | Não há cliente a quem cobrar: o plano não se aplica. Um pedido de cliente mal resolvido também cairia aqui — a defesa é o resolvedor, que já encaminha a base de dados (sem ele o pedido nem vê os dados do cliente) |
| Plano desconhecido no registo | A Consola só aceita os 4 planos. Na migração, os nomes antigos mapeiam (strategic/advanced → enterprise, pilot → starter, foundation → core, scale → plus) |
| O cliente mexe na sua própria base (linha `tenant_plan_limits` local) | Deixa de ser lida (L1). Teste 14 |
| Agente agendado por API directa, contornando o ecrã | A verificação do intervalo está no serviço e no agendador, que recusa correr um agente abaixo do mínimo do plano |
| Mudança de plano a meio do mês | Os contadores mantêm-se; os tectos mudam no instante seguinte (cache do resolvedor limpa) |
| Interface antiga (app sem OTA) recebe 402 | A app e a web mostram a mensagem do servidor; o texto vem pronto do backend, na língua de quem pede |

## 8. Fora deste trabalho

- Cobrança automática (Stripe): a mudança de plano continua manual na Consola.
- Medição real do custo por pergunta (Langfuse) para rever os números do plano.
