# Sky — especificação do produto (app móvel)

> Escrita a 21/08/2026 a pedido do Lucas, para servir de base à geração de
> ecrãs. **Não fala de desenho.** Não há aqui cores, tipos de letra, tamanhos,
> espaçamentos nem posições. Só: que superfícies existem, o que cada uma
> contém, e o que cada coisa é capaz de fazer.
>
> Tudo o que está aqui foi levantado do código, não de memória. Onde uma
> capacidade **não existe** ou **não funciona**, está dito.

---

## 0. O que o produto é

Uma pessoa faz uma pergunta em linguagem natural sobre os dados da sua empresa.
A Sky escreve o SQL, corre-o sobre as ligações do projeto, e responde. A
resposta fica visível à equipa, que a discute e pode voltar a perguntar
levando essa discussão como contexto.

Três eixos, e é o que decide tudo o resto:

| eixo | o que é |
|---|---|
| **Projeto** | o contentor. Decide **que dados** as perguntas alcançam |
| **Equipa** | pessoas dentro de um projeto. Não decide dados |
| **Privado** | modo pessoal. Lê os dados de **todos** os projetos da pessoa |

---

## 1. Entrada

### 1.1 Autenticação
- Campo de **email**, botão **Continuar**
- **Continuar com Google** (SSO)
- Nota legal: Termos de Utilização + Política de Privacidade
- Um cliente pode estar configurado como **só-SSO** (sem email/password)
- **MFA/TOTP** existe, com isenção por lista de emails

### 1.2 Resolução do cliente
- O cliente é deduzido do **domínio do email** ou do **anfitrião** do endereço
- Não há escolha manual de cliente

---

## 2. Objecto: PROJETO

Um projeto tem: **nome**, **contagem de pessoas**, **contagem de ligações de
dados**, **equipas**, **ligações de dados**, **documentos**, **conversas**,
**insights**, **agentes**.

### 2.1 Capacidades
| capacidade | quem |
|---|---|
| Listar os projetos a que pertenço | qualquer pessoa |
| Entrar num projeto | qualquer membro |
| **Criar** projeto | administrador do cliente (`spaces.create`) |
| Ligar/desligar fontes de dados | quem gere o projeto |
| Criar equipas dentro do projeto | quem gere o projeto |
| Pedir dados que faltam | qualquer membro |

### 2.2 Selecionar projeto
- Lista com: **Privado** (sempre primeiro) e depois os projetos
- Marca visual de qual está activo
- Acção **criar projeto** (só a quem pode)
- Entrar num projeto entra automaticamente na sua **equipa por omissão**

### 2.3 «O que este projeto sabe» — duas famílias distintas

| | **Dados ligados** | **Documentos** |
|---|---|---|
| o que é | ligações vivas (BigQuery, Postgres, MySQL, MongoDB, Google Sheets) | ficheiros carregados |
| formatos | tabelas e colunas | PDF, TXT, MD, CSV, DOCX, XLSX |
| como a IA usa | escreve **SQL** e corre | procura por semelhança e **cita** |
| frescura | o valor de agora | fotografia do momento do carregamento |
| aprovação | quem gere o projeto escolhe as tabelas | **Owner/Admin da plataforma** aprova cada ficheiro |

**Dados ligados** — por ligação: nome, tipo de conector, estado (ligada / não
responde). Acções: **acrescentar** ligação ao projeto, **remover** do projeto.

**Pedir dados que faltam** — campo de texto livre («descreva por palavras
suas»), botão de enviar, confirmação. Existe para quem bate na parede de não
ter a tabela.

**Documentos** — lista com nome, estado (**a indexar** / pronto / **falhou**),
número de passagens indexadas. Acções: **acrescentar documento**, **remover**.
Um ficheiro fica em **espera de aprovação** até um Owner/Admin o aprovar.

### 2.4 Equipas
- Lista de equipas do projeto, cada uma com contagem de pessoas
- Dentro de uma equipa: lista de membros (nome, email)
- Acções: **criar equipa**, **acrescentar pessoa**, **remover pessoa**
- Todo o projeto tem uma equipa por omissão («General»); ninguém entra solto

---

## 3. Objecto: CONVERSA

### 3.1 O que é
Um assunto. Nasce da **primeira mensagem** — nunca de um botão. O **título** é
derivado dessa primeira mensagem.

Campos: título, quem começou, quando foi actualizada, **arquivada**,
**resolvida**, **mensagem fixada**.

### 3.2 Tipos de mensagem
| tipo | quem pode | dispara a IA |
|---|---|---|
| **pergunta** | hoje: só quem começou a conversa (+ admin) | sim |
| **resposta da Sky** | a própria | — |
| **comentário** | qualquer pessoa que veja a conversa | não |

Cada mensagem tem: autor, conteúdo, **reacções** (emoji), e pode apontar ao
que responde.

### 3.3 Capacidades dentro de uma conversa
- **Responder** (comentário) a uma resposta ou a uma pergunta
- **Reagir** com emoji
- **Copiar** o texto de uma mensagem
- **Tentar outra vez** uma resposta
- **Fixar** uma mensagem no topo da conversa
- **Fixar como widget** numa página (a resposta vira um objecto reutilizável)
- **Mudar o nome** da conversa
- **Marcar como resolvida** / reabrir
- **Arquivar**
- **Levar a discussão à Sky**: os comentários pendentes são empacotados com a
  pergunta seguinte. Antes de enviar mostra-se **quantos comentários vão**;
  depois, cada comentário mostra **em que resposta entrou**

### 3.4 Compositor (a caixa de escrever)
Presente em todas as conversas. Contém:

| elemento | o que faz |
|---|---|
| campo de texto | cresce com o texto até um tecto |
| **`+` anexar** | abre folha com **Ficheiros** e **Biblioteca de Conhecimento** |
| **destino** | interruptor **Equipa ⇄ Sky** (só em projeto; no Privado há um só destino) |
| **`@` menções** | selector de pessoas da equipa; notifica quem for escolhido |
| **ditar** | fala → texto no campo, com barra de ditado (parar / descartar) |
| **conversa por voz** | abre o modo falado |

⚠️ **Câmara e Fotografias saíram de propósito**: a Sky não lê imagens (não há
OCR nem modelo com visão ligado). Voltam quando houver quem leia a imagem.

### 3.5 Anexo vs Biblioteca — a diferença que importa
- **Anexo de conversa**: relido a cada pergunta, morre com a conversa
- **Biblioteca**: indexado uma vez, disponível a **todas** as perguntas do seu
  âmbito, sem voltar a pagar contexto

---

## 4. Superfície: PRIVADO

- Lê a **união das tabelas de todos os projetos** onde a pessoa está
- Só a própria pessoa vê o que lá escreve
- ⚠️ **A resposta não se publica**: quem cruzou tinha acesso a cada peça, mas
  ninguém aprovou a combinação. Fixar está travado
- Não tem equipas nem dados próprios — não é um projeto, é a união deles

---

## 5. Superfície: INSIGHTS

- Feed de achados trazidos pelos agentes
- **Procurar** nos insights
- Cada achado: título, explicação, **origem** (que agente), marca de **ao vivo**
- Vazio: «os seus agentes vão trazer achados para aqui»

### 5.1 Um insight aberto
- Título, explicação, gráfico/indicadores quando existem
- **Perguntar à Sky sobre isto** — abre conversa já com o contexto
- **Marcar como revisto**
- **Fixar**

---

## 6. Superfície: AGENTES

Um agente é **uma pergunta que a Sky repete sozinha**.

Cada agente tem: **nome** (opcional — por omissão é a própria pergunta),
**pergunta**, **frequência**, **último resultado**, âmbito (projeto ou pessoal).

### 6.1 Capacidades
- **Criar agente**: pergunta + nome opcional + com que frequência
- **Correr agora**
- **Mudar a frequência**
- **Abrir a conversa** que ele gerou
- **Apagar**
- Estado quando nunca correu: «ainda não falou»
- Um agente pessoal: «é pessoal — só você vê o que ele encontra»

---

## 7. Superfície: VOZ

- Dois modos: **mãos-livres** e **carregar para falar**
- Estados: a ligar / à escuta / a Sky está a pensar
- **Silenciar** / retomar
- **Tocar para interromper** a Sky a meio
- A conversa aparece **por escrito** enquanto decorre — o nível do microfone é
  sinal de vida, não conteúdo
- Definições próprias: **modo**, **língua**, **ritmo**

---

## 8. Superfície: NOTIFICAÇÕES

- Lista, com marca de **por ler**
- Vazio: «nada de novo»

### 8.1 O que gera notificação
| evento | estado |
|---|---|
| mencionaram-me (`@`) | ✅ |
| escreveram numa conversa em que participo | ✅ (novo, 21/08) |
| achado de agente / agente falhou / pausado | ✅ |
| entrei num projeto ou equipa, mudança de papel, convite | ✅ |
| ligação de dados falhou / recuperou / tabela nova | ✅ |

### 8.2 Preferências
- **Pausar tudo**
- Silenciar **por categoria**: agentes, painéis, páginas, menções, conversas,
  colaboração, ligações, sistema

---

## 9. Superfície: DEFINIÇÕES

| secção | conteúdo |
|---|---|
| **Conta** | nome, email |
| **Perfil** | nome próprio, «como lhe devemos chamar», preferências aplicadas a todas as conversas |
| **Aparência** | modo de cor (sistema / claro / escuro), estilo de letra |
| **Voz** | modo, língua, ritmo |
| **Notificações** | pausar, silenciar por categoria |
| **Idioma** | da app |
| **Resposta táctil** | ligar/desligar |
| **Privacidade** | permissões, política |
| **Pessoas** | quem está no cliente |
| **Dados de demonstração** | ligar dados de exemplo |
| **Ajuda e suporte** | |
| **Sobre a Sky** | versão, termos |
| **Partilhar a Sky** | |
| **Terminar sessão** | com confirmação |

---

## 10. Papéis e o que cada um pode

| papel | alcance |
|---|---|
| **Owner / Admin da plataforma** | tudo no cliente; **aprova documentos** |
| **Admin do cliente** | cria projetos, gere pessoas |
| **Dono de projeto/equipa** | gere dados, equipas, membros |
| **Editor** | escreve, cria conteúdo |
| **Leitor** | vê e comenta |

**Regra de fundo:** quem gere a estrutura não vê automaticamente o **conteúdo**
(conversas, agentes, insights, dados). É preciso pertencer.

---

## 11. Estados que qualquer superfície pode ter

Cada lista precisa de saber desenhar cinco coisas, e nenhuma é opcional:

1. **a carregar**
2. **vazio** — dizendo o que fazer a seguir, não só «não há nada»
3. **com conteúdo**
4. **erro**, com **tentar outra vez**
5. **sem permissão** — a acção não aparece a quem não pode

---

## 12. Multilingue

Português e inglês, escolhidos nas Definições, com o idioma do telemóvel por
omissão. **Todo o texto visível passa pelo dicionário** — incluindo estados
vazios, erros, etiquetas de acessibilidade e contagens (que precisam de
singular e plural separados).

---

## 13. O que NÃO existe hoje

Dito para não ser desenhado por engano:

| | |
|---|---|
| Ler imagens | sem OCR nem modelo com visão |
| Estado de **por ler** por conversa | não existe |
| **Procurar** transversal a conversas | não existe |
| **Privado dentro de um projeto** | falta o campo de visibilidade |
| Qualquer pessoa levar a discussão à Sky | hoje só quem começou a conversa |
| Arquivar/resolver **na lista** | os campos existem, o ecrã não |

---

## 14. Fluxo mínimo, do zero ao valor

1. Entrar
2. Escolher projeto (ou Privado)
3. Perguntar
4. Ler a resposta
5. A equipa comenta
6. Alguém leva a discussão de volta à Sky
7. A resposta boa é fixada e passa a objecto reutilizável
8. Um agente passa a repetir a pergunta sozinho
9. O que ele encontrar aparece nos Insights e avisa quem interessa
