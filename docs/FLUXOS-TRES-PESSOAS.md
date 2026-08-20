# Três pessoas a trabalhar juntas — os fluxos, e onde eles partem

> Companheiro de `PROJETO-COMO-HUB.md`. O Lucas pediu para eu percorrer casos de
> uso e ver se o produto faz sentido para três pessoas trabalharem juntas.
>
> Não é uma lista de desejos: cada passo diz **o que acontece hoje**, com o
> ficheiro, e marca 🔴 onde parte. Os buracos estão numerados e resumidos no fim.

## As três pessoas

| | quem | onde está |
|---|---|---|
| **Ana** | admin do cliente | em todos os projetos |
| **Rui** | analista | Marketing e Vendas |
| **Sofia** | entrou esta semana | só Marketing |

---

## Fluxo 1 — A Ana monta o projeto

1. Cria o projeto Marketing.
2. Escolhe que tabelas ele vê.
3. Cria a equipa e convida o Rui e a Sofia.

**Hoje:** funciona. É a ordem em que o ecrã já está montado, e é a ordem certa —
escolher dados é a decisão séria, convidar é dar o que já foi escolhido.

⚠️ Mas a Ana faz isto num ecrã que **é só isto**. Depois de montado, o projeto
continua a abrir na configuração, que é trabalho que se faz uma vez.
→ **Buraco 6**

---

## Fluxo 2 — O Rui faz a primeira pergunta

1. Abre Marketing, escreve «qual foi o custo por canal em Julho?»
2. A Sky responde com os dados **daquele** projeto.

**Hoje:** funciona. A conversa ganha título a partir da pergunta
(`message_service.py:196`), e a resposta fica visível a toda a gente do projeto.

---

## Fluxo 3 — A Sofia discute a resposta

1. A Sofia lê a resposta e comenta: «este número não inclui o afiliado».
2. O comentário fica debaixo da resposta (`kind="comment"`, `parent_message_id`).

**Hoje:** o comentário grava-se e aparece a quem estiver com o ecrã aberto
(WebSocket).

🔴 **O Rui nunca fica a saber.** As notificações só disparam por **menção
explícita** — `_notificar_mencionados` (`message_service.py:571`) só notifica quem
foi apanhado em `mentions`. Comentar a resposta de alguém **não avisa ninguém**.

Se o Rui fechou a app, a observação da Sofia morre ali. E isto não é um detalhe:
é a diferença entre uma ferramenta colaborativa e um mural onde cada um fala
sozinho.
→ **Buraco 1**

---

## Fluxo 4 — A Sofia quer levar a discussão de volta à Sky

1. Depois de dois comentários, a Sofia quer perguntar outra vez, agora
   considerando o que se disse.

**Hoje:** o `/ask-ai` que empacota os comentários é **só do dono da conversa**
(`api/v1/messages.py`, «owner only — chat-threads PR2»).

🔴 A Sofia não pode. Tem de esperar pelo Rui.

Isto **parte o modelo colaborativo por desenho**: convidámos as pessoas a
discutir e depois só uma pode agir sobre a discussão. E o Rui vira um
estrangulamento — de férias, a conversa congela.

O travão faz sentido como controlo de **custo**, não de **papel**. Custo
controla-se com quota; papel controla-se com quem pertence ao projeto.
→ **Buraco 2** *(decisão do Lucas)*

---

## Fluxo 5 — A Ana fixa a resposta

1. A resposta boa passa a widget numa página (`pinned_widget_id`).
2. Um comentário sobre o widget pode abrir um pedido de alteração
   (`change_requests`, chat-threads PR3).

**Hoje:** existe e é uma boa ponte entre discussão e artefacto.

⚠️ Se a resposta veio do **Privado** cross-project, não se fixa —
`cruzou_projetos` trava (`ai.py:1048`). Correcto e deliberado: quem cruzou tinha
acesso a cada peça, mas ninguém aprovou a combinação. Só falta **dizê-lo** no
momento em que a pessoa tenta fixar, em vez de o botão não fazer nada.
→ **Buraco 7** (pequeno)

---

## Fluxo 6 — O Rui trabalha no seu Privado

1. Está em Marketing e Vendas. Quer cruzar os dois.
2. Vai ao Privado e pergunta.

**Hoje:** funciona, e é exactamente o que o Lucas descreveu. Com
`DATA_BOUNDARY=project`, o modo pessoal lê a união das tabelas de todos os
projetos onde ele está (`permission_service.py:700`).

⚠️ Faltava o **nome**: chamava-se «Personal» / «TODOS OS MEUS PROJETOS».
Entregue em sky-frontend #646 e sky-mobile #26.

---

## Fluxo 7 — O Rui quer rascunhar em privado dentro do projeto

1. Quer explorar uma ideia em Marketing sem que a equipa veja.
2. Quando estiver apresentável, convida os outros.

🔴 **Não existe.** A `Conversation` não tem campo de visibilidade — quem vê é
derivado do `space_id`/`crew_id`. Estás no projeto, vês tudo o que lá está.

Hoje o Rui só tem duas escolhas más: rascunhar no Privado pessoal (mas aí a
resposta cruza projetos e **não se pode publicar**), ou rascunhar à vista de
todos.
→ **Buraco 3** *(precisa de coluna nova — ver §4.2 do outro documento)*

---

## Fluxo 8 — A Sofia precisa de dados que o projeto não tem

1. Pergunta sobre afiliados; a tabela não está ligada ao projeto.
2. Pede acesso.

**Hoje:** existe no telemóvel (`components/PedirDados.tsx`).

⚠️ Está no ecrã de configuração do projeto, não onde a falta se sente — que é no
momento em que a resposta sai incompleta. O Lucas disse o mesmo: pedir devia
estar **dentro de dados**, e eu acrescento: também **junto da resposta que não
chegou**.
→ **Buraco 8**

---

## Fluxo 9 — A Sofia sai da equipa

1. Sai do projeto Marketing.
2. As perguntas e comentários dela ficam.

**Hoje:** as mensagens ficam (é o correcto — são o registo do projeto) e ela
deixa de ver o projeto.

⚠️ **Por verificar:** o nome dela continua a aparecer ao lado do que escreveu?
Se o utilizador deixar de ser resolúvel, cai-se no caso do avatar sem nome — que
era o que desenhava a bolha com «?». Corrigi o desenho em sky-mobile #26, mas a
causa a montante ainda não está confirmada, e **esta é a hipótese mais provável**.
→ **Buraco 9** *(a confirmar com dados reais)*

---

## Fluxo 10 — Passaram três meses: 50 conversas

1. A Sofia abre Marketing.
2. Vê 50 conversas.

🔴 O que ela **não** consegue fazer:

- ver o que é novo desde ontem — **não há estado de lido**
- procurar — **não há procura**
- ver o que é importante — **fixar não está na lista**
- arrumar — **arquivar e resolver existem no modelo e não têm ecrã**
- saber quem começou — **`created_by` existe e não se mostra**

É o cenário que o Lucas descreveu, e a resposta é quase toda «expor o que já
está construído». Só *por ler* e *procurar* são trabalho novo.
→ **Buraco 4**

---

## Fluxo 11 — A Ana no computador, o Rui no telemóvel

1. A Ana cria uma conversa na «Chat 2» da página.
2. O Rui abre o telemóvel.

🔴 Eles **não veem a mesma lista**:

- o telemóvel lista **sem filtro de sessão** → mostra as conversas de todas as
  sessões misturadas
- o telemóvel cria **sem sessão** → o servidor põe na «Chat 1»
  (`_ensure_session_id`), portanto a conversa do Rui **desaparece** para a Ana
  enquanto ela estiver na «Chat 2»

Duas pessoas na mesma página a ver coisas diferentes é o defeito que mais depressa
faz perder a confiança numa ferramenta de equipa.
→ **Buraco 5** *(decisão do Lucas: tirar as sessões ou implementá-las)*

---

## Fluxo 12 — Alguém abre uma conversa e não escreve nada

**Hoje:** fica lá. Para sempre. Sem título, porque o título só é posto quando a
primeira mensagem chega. Não há limpeza nenhuma.
→ **Buraco 10**

---

## Os buracos, por ordem de dano

| # | Buraco | Dano | Custo |
|---|---|---|---|
| 1 | Comentar não avisa ninguém (só `@menção`) | **mata a colaboração em silêncio** | médio |
| 2 | Só o dono pode levar a discussão à Sky | convida a discutir e proíbe de agir | baixo (decisão) |
| 5 | Sessões: web e mobile mostram listas diferentes | duas pessoas, duas verdades | médio |
| 3 | Não há privado dentro do projeto | obriga a escolher entre expor ou não poder publicar | alto |
| 4 | Sem por-ler, procura, fixar, arquivar à vista | 50 conversas viram ruído | médio |
| 10 | Conversas vazias e sem título ficam para sempre | suja a lista todos os dias | **baixo** |
| 9 | Autor por resolver depois de sair | bolha «?» — a hipótese mais provável | baixo |
| 6 | Projeto abre na configuração | esconde o trabalho atrás da montagem | baixo |
| 8 | Pedir dados longe de onde a falta se sente | o pedido não se faz | baixo |
| 7 | Fixar uma resposta cruzada falha em silêncio | parece avariado | muito baixo |

## Conclusão honesta

Para **uma** pessoa o produto funciona. Para **três**, parte em dois sítios que
não são de ecrã, são de desenho:

1. **Ninguém é avisado** de nada que não seja uma menção directa (buraco 1).
2. **Quem discute não pode agir** sobre a discussão (buraco 2).

Sem esses dois, o resto da colaboração é decoração: as pessoas podem escrever
umas às outras, mas não se encontram, e quem escreve não pode fazer nada com o
que escreveu.

Os buracos 10, 6, 8 e 7 são baratos e entram já. O 3 e o 5 são decisões do
Lucas. O 4 é o maior em esforço e o que mais se nota ao fim de um mês.
