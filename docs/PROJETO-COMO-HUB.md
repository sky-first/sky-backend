# O projeto como hub — modelo único, governança e privado

> Escrito a 20/08/2026 a partir do que o Lucas pediu, depois de ler o código dos
> três repositórios. **Documento primeiro, código depois** — é a regra dele para
> trabalho de desenho.
>
> Cada afirmação sobre o que existe hoje aponta o ficheiro. O que é proposta
> está marcado como **proposta**.

---

## 1. A lista — tudo o que o Lucas disse

| # | O que ele disse | Tipo |
|---|---|---|
| A1 | Ao abrir um projeto não há botão de **nova conversa** | defeito |
| A2 | O ecrã do projeto parece uma **tela de configuração** | desenho |
| A3 | «Dados» e «Base de Conhecimento» parecem a mesma coisa | desenho |
| A4 | Configuração devia ser um **botão**, abrindo dados + equipas | desenho |
| A5 | Pedir acesso devia estar **dentro de dados** | desenho |
| A6 | Ao abrir o projeto o que a equipa quer ver são as **conversas** | desenho |
| B1 | 50 conversas sem se saber quem criou, qual título, o que importa | governança |
| B2 | Teams/Slack fazem isto bem — precisamos de governança fluida | governança |
| B3 | O projeto deve ser um **hub** onde várias equipas trabalham juntas | modelo |
| C1 | Onde vejo o meu **privado**? Uma conversa só minha | lacuna |
| C2 | «Personal» passa a **«Privado»** | vocabulário |
| C3 | No privado, pesquisar sobre **todos os dados a que tenho acesso** | modelo |
| C4 | No projeto, só os dados **daquele** projeto | modelo |
| C5 | Criar algo **privado dentro de um projeto** e convidar pessoas depois | lacuna |
| C6 | Quem criou pode **ligar/desligar** privado ⇄ público | lacuna |
| D1 | Insights e agentes seguem o mesmo padrão: pertencem a projetos | modelo |
| E1 | Menu: **Conversas → Projetos → Lista de Projetos** | navegação |
| E2 | Manter o botão **Nova conversa** | navegação |
| F1 | Conversa **sem título ou sem texto** deve ser removida | defeito |
| G1 | Web e mobile têm de ter **um modelo só** | modelo |

---

## 2. O modelo único

### 2.1 O que hoje diverge — e é só uma coisa

Os dados são os mesmos nos dois: as mesmas tabelas, os mesmos endpoints. A
divergência real são as **sessões de chat** («Chat 1», «Chat 2»):

```
WEB      Projeto -> Página -> Sessão -> Conversa -> Mensagens
MOBILE   Projeto -> Página ->   (x)   -> Conversa -> Mensagens
```

| | listar | criar |
|---|---|---|
| Web | filtra pela sessão activa | grava na sessão activa |
| Mobile | `getConversations(pageId)` **sem filtro** | **sem sessão** → o servidor põe na «Chat 1» |

Fontes: `sky-mobile/apps/mobile/src/screens/ChatsHomeScreen.tsx:121` e `:148`;
`sky-poc-backend/src/services/chat_session_service.py:216` (`_ensure_session_id`).

Consequência, e é assimétrica:

- conversa começada **no telemóvel** só aparece na web se estiveres na «Chat 1»
- conversas de **todas** as sessões da web aparecem no telemóvel **misturadas**

Duas pessoas na mesma página, uma no computador e outra no telemóvel, não veem
a mesma lista. É isso que mina a confiança na ferramenta.

### 2.2 Proposta: tirar as sessões

```
Projeto -> Página -> Conversa -> Mensagens (+ discussão debaixo de cada resposta)
```

Porquê tirar em vez de implementar no mobile:

1. **Já há um contentor para «um assunto»: a conversa.** A sessão é um segundo
   contentor a fazer quase o mesmo trabalho, um nível acima. Dois contentores
   para a mesma ideia é o que faz perguntar «isto é reply ou thread?».
2. **Não é um contentor, é um filtro de vista** — está escrito no próprio tipo:
   *«o canvas da página é partilhado por todas as sessões; trocar de sessão só
   troca a linha do tempo»* (`sky-poc-frontend/src/lib/api/chat-threads.ts:37`).
3. No telemóvel **tinha sempre um item** — está escrito por quem o tirou.

**Antes de decidir:** contar em produção quantas páginas têm mais de uma sessão.
Se forem quase nenhumas, tirá-las não custa a ninguém.

---

## 3. Governança das conversas

O medo do Lucas: 50 conversas e ninguém sabe quem criou nem o que importa.

### 3.1 O que já existe no modelo (e não se vê)

`Conversation` (`sky-poc-backend/src/models/conversation.py`):

| campo | serve para |
|---|---|
| `title` | vem da primeira pergunta (`message_service.py:196`) |
| `created_by` | quem começou |
| `archived_at` | arrumar sem apagar |
| `resolved_at` | dar por fechado |
| `pinned_message_id` | destacar a mensagem que interessa |

`Message`: `reactions` (emoji), `pinned_widget_id`, `parent_message_id`,
`incorporated_in_message_id`.

**As peças da governança estão construídas e não estão à vista.**

### 3.2 O que falta — proposta

Do que o Slack e o Teams fazem bem, o que se aplica aqui:

| peça | porquê | existe? |
|---|---|---|
| Título sempre | uma lista de «sem título» não é uma lista | só depois da 1.ª mensagem |
| Nunca criar conversa vazia | ver §7 | não |
| Autor visível na lista | «quem começou isto?» | campo sim, ecrã não |
| Ordenar por actividade | o que mexe fica em cima | parcial |
| **Fixar** no topo | o que importa não desce | não, na lista |
| **Arquivar** | 50 passam a 8 sem perder nada | campo sim, ecrã não |
| **Resolvido** | fecha sem arquivar | campo sim, ecrã não |
| Por ler | «o que é novo desde ontem» | não |
| Procurar | acima de ~20 conversas é a única saída | não |

O caro é **por ler** e **procurar**. Tudo o resto é expor campos que já existem —
é governança quase de graça.

### 3.3 A regra que evita as 50

Não é uma funcionalidade, é uma omissão bem escolhida: **a conversa nasce da
primeira mensagem, nunca de um botão.** O mobile já faz assim e está escrito
porquê no topo do `ChatsHomeScreen.tsx`. A web tem um «+» que cria conversas
vazias — é daí que vêm as «sem título».

---

## 4. Privado — três níveis, e só um existe

O Lucas descreveu três coisas diferentes com a mesma palavra. Separá-las é
metade do trabalho.

### 4.1 Privado pessoal (cross-project) — **já existe e faz o que ele quer**

`mode: "personal"`. Com `DATA_BOUNDARY=project` (ligado em produção), a pergunta
lê **a união das tabelas de todos os projetos onde a pessoa está**
(`permission_service.py:700` → `_tabelas_dos_meus_projetos`).

É exactamente o «estou em 10 projetos com 100 datasets e quero pesquisar sobre
todos». **Já funciona hoje.** O que falta é o nome — «Privado» — e vê-lo no menu.

⚠️ E a metade que o nome esconde: a resposta daqui **não se publica**
(`cruzou_projetos`, `ai.py:1048`). Quem cruzou tinha acesso a cada peça; o que
ninguém aprovou foi a combinação. Por isso há sempre uma legenda ao lado do nome.

### 4.2 Privado dentro de um projeto — **não existe**

A `Conversation` **não tem campo de visibilidade nenhum**. Quem vê é derivado do
`space_id`/`crew_id`: se és do projeto, vês tudo o que lá está.

Logo, «criar uma coisa privada dentro do projeto e convidar pessoas depois» não é
um ecrã em falta — **é uma coluna em falta**.

**Proposta:**

```sql
ALTER TABLE conversations
  ADD COLUMN visibility TEXT NOT NULL DEFAULT 'project';
  -- 'project' | 'private'
```

Regras:

- `private` → só o `created_by` lê e escreve, mesmo sendo os outros do projeto.
- **Publicar** (`private` → `project`): do criador, ou de quem manda no projeto.
- **Despublicar** (`project` → `private`): **só se mais ninguém tiver escrito lá.**
  Senão estaríamos a tirar de baixo dos olhos das pessoas uma conversa em que
  elas participaram, e a decisão de as remover não é de quem abriu o assunto.
  *(O Lucas pediu ligar **e** desligar. Esta é a ressalva que eu levanto —
  decide ele.)*
- Os **dados** de uma conversa privada dentro do projeto continuam a ser os do
  projeto. Privado é sobre **quem lê a conversa**, nunca sobre a que dados ela
  chega. Sem esta regra abria-se um caminho para cruzar dados sem ninguém ver.

### 4.3 Privado não é um terceiro sítio

Não haverá uma «área privada» separada. Há:

- **Privado** no topo do menu — o cross-project pessoal (§4.1)
- dentro de cada projeto, conversas marcadas `private` (§4.2)

---

## 5. Dados vs Base de Conhecimento — não é o mesmo

A confusão do Lucas é legítima e aponta um problema real de desenho. Mas as duas
coisas são mesmo diferentes:

| | **Dados** | **Conhecimento** |
|---|---|---|
| o que é | ligações vivas (BigQuery, Postgres) | ficheiros que alguém carregou |
| forma | tabelas e colunas | PDF, XLSX, notas |
| como a IA usa | escreve **SQL** e corre | procura por semelhança e **cita** |
| frescura | o valor de agora | uma fotografia do dia do carregamento |
| quem aprova | quem manda no projeto escolhe as tabelas | **Owner/Admin da plataforma**, sempre |

A última linha é a diferença que interessa: um ficheiro é **citado como facto**,
por isso passa por `pending_approval` e um Owner/Admin tem de o aprovar — nem o
commander aprova o seu próprio carregamento
(`sky-poc-backend/docs/knowledge-library-security.md`).

**Proposta:** manter as duas, mas debaixo de um cabeçalho só —
**«O que este projeto sabe»** — com dois grupos: *Dados ligados* e *Documentos*.
Um sítio para olhar, e a diferença dita por palavras em vez de deixada ao
adivinhar.

---

## 6. O ecrã do projeto

### Hoje

Três secções de configuração: Dados, Equipas, Conhecimento. Sem conversas. Sem
botão de nova conversa. (`sky-mobile/apps/mobile/src/screens/ProjectScreen.tsx`)

### Proposta

```
+--------------------------------------+
|  <                             (cfg) |   cfg = dados, equipas, documentos
|                                      |
|  Marketing                           |   nome grande
|  4 pessoas · 12 tabelas              |
|                                      |
|  [ Procurar nas conversas         ]  |
|                                      |
|  -- FIXADAS ----------------------   |
|  Orçamento Q4           Ana · 2 d    |
|  -- ABERTAS -----------------------  |
|  * Custo por canal      Rui · 3 h    |   * = por ler
|    Fugas no funil       Ana · ontem  |
|  -- MINHAS PRIVADAS ---------------  |
|  (lock) Rascunho margens    só eu    |
|                                      |
|                   ( + Nova conversa )|
+--------------------------------------+
```

O projeto passa a ser o **hub**: abre no trabalho, não na configuração. A
configuração fica a um toque.

---

## 6-bis. ⚠️ A conversa ainda vive na EQUIPA, não no projeto

Descoberto ao tentar montar o ecrã do §6. É a peça que falta para o projeto poder
ser um hub, e não é um ecrã — é arquitectura.

```
sky-mobile/apps/mobile/src/context/store.ts:79  (pageFor)

  modo crew + crewId   -> ensureCrewPage(crewId)     <- a conversa mora AQUI
  modo crew + spaceId  -> ensureSpacePage(spaceId)
  modo pessoal         -> a página do próprio
```

Ou seja: os **dados** subiram para o projeto a 18/08 (`DATA_BOUNDARY=project`),
mas as **conversas** ficaram na equipa. Um projeto com três equipas tem as suas
conversas espalhadas por três páginas diferentes, e não existe nada a que se
possa chamar «as conversas deste projeto».

É a mesma contradição que já se viu no selector: a equipa deixou de decidir dados
mas continua a decidir onde as coisas moram.

**As duas saídas:**

| | o quê | custo |
|---|---|---|
| **A** | A conversa passa a viver na página do **projeto**. A equipa fica só como pessoas, a sério. | migração de dados; é a limpa |
| **B** | O hub **junta** as páginas das equipas do projeto a que a pessoa pertence. | sem migração; N pedidos; a contradição fica |

Recomendo **A** por coerência com a decisão de 18/08 — mas mexe em dados
existentes e é decisão do Lucas.

**Entretanto:** o ecrã do §6 pode ser feito com **B**, que não fecha portas. Na
prática cada projeto tem quase sempre uma equipa («General»), por isso o custo
dos N pedidos é hoje teórico.

---

## 7. Conversas vazias e sem título

**Causa:** a conversa é criada **antes** da primeira mensagem, e o título só é
posto quando essa mensagem chega (`message_service.py:196`). Se ninguém escrever,
fica sem título para sempre. **Não há limpeza nenhuma** — procurei e não existe.

**Proposta, por esta ordem:**

1. **Não criar vazias.** A conversa nasce com a primeira mensagem, nas duas
   plataformas. Tira a causa em vez de limpar o efeito.
2. **Varrer as que já existem**: sem mensagens e com mais de 24 h → apagar. Uma
   vez, e depois em rotina.
3. **Nunca mostrar «sem título»** numa lista. Sem título é um defeito, não um
   estado para desenhar.

---

## 8. Insights e agentes

O Lucas quer o mesmo padrão: pertencem a projetos. **Por verificar** — ainda não
li como estão delimitados hoje. Fica marcado como buraco deste documento, não
como conclusão.

---

## 9. Navegação

```
Privado            <- o cross-project pessoal (§4.1)
Projetos           <- lista -> dentro, o hub (§6)
Insights
Agentes
```

O **Nova conversa** fica, como ele pediu — e pergunta onde vai viver (Privado ou
um projeto), que é o modal já entregue em sky-mobile #26.

---

## 10. Casos de uso com três pessoas

Ver `FLUXOS-TRES-PESSOAS.md`.

---

## 11. Ordem de execução proposta

| | o quê | risco |
|---|---|---|
| 1 | Não criar conversas vazias + varrer as existentes | baixo |
| 2 | Ecrã do projeto: conversas à frente, configuração a um toque | baixo |
| 3 | Menu: Privado / Projetos | baixo |
| 4 | Expor a governança que já existe (autor, fixar, arquivar, resolver) | médio |
| 5 | «O que este projeto sabe» (dados + documentos juntos) | médio |
| 6 | `visibility` na conversa (privado dentro do projeto) | **alto — segurança** |
| 7 | Decidir e executar as sessões de chat | médio |
| 8 | Por ler + procurar | alto (esforço) |

O ponto 6 mexe em quem vê o quê. Não entra sem os casos de stress escritos e sem
o Lucas de acordo.

---

## 12. Decisões que só o Lucas toma

1. **Sessões de chat**: tirar (é o que recomendo) ou implementar no mobile?
2. **Despublicar** uma conversa onde já escreveram — permitir ou travar?
3. **Quem pode perguntar à Sky** dentro de uma discussão? Hoje é só o dono da
   conversa (`/ask-ai`, owner-only), o que parte o modelo colaborativo.
4. A segunda linha da lista de projetos: **«N pessoas · N ligações»** (o que está)
   ou **«Editado <data>»** (como na imagem que ele mandou)?
