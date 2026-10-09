# A voz, medida

> «testei o livetalk e está muito fraco, bugando muito… ele em quase
>  todas as vezes não está encontrando dados, apenas para perguntas
>  muito básicas»
>
> «quero a nível chatgpt, claude, gemini… melhor que o chat se possível,
>  não podemos ter isso a falhar»
>
> «existe uma fluidez que eu quero no nosso produto… o nosso está mais
>  como um pergunta resposta e muito mal. Se precisar trocar ferramenta,
>  ou modelo, ou forma de fazer, fique à vontade.»
>
> — Lucas, 08/10/2026

Este documento não propõe nada em abstracto. Tudo aqui foi medido contra
o `amazon.nova-2-5-sonic` em `eu-north-1`, na nossa conta de produção
(conta 032080729567, perfil `sky-production`), com a pergunta
*«¿Cuántas rutas incumplen el plazo de entrega?»* sintetizada no Polly e
injectada como se viesse de um microfone, em pedaços de 32 ms.

A sonda está em `scratchpad/sonic/` e é deliberadamente descartável.

---

## 1. O que temos hoje, e o que está mal

A voz é uma **cascata de três peças nossas**:

```
microfone → AWS Transcribe → sky-ai (LangGraph + SQL) → AWS Polly → auscultador
```

O que isso custa em tempo real, do fim da fala ao primeiro som: **8 a 90
segundos**. Noventa quando o SQL não acerta à primeira.

E há dois defeitos de natureza, que nenhum ajuste de parâmetros resolve:

**O turno fecha-se a cronómetro.** `SILENCIO_QUE_FECHA_O_TURNO` era 1,6 s
(hoje 2,5 s, corrigido no #713). Quem hesita a meio de uma pergunta longa
é cortado; quem acaba de falar espera 2,5 s por nada. Não existe um valor
certo — a decisão não é de tempo, é de SENTIDO.

**A fala durante o turno é deitada fora.** Enquanto `turn_active` está
ligado, o áudio do microfone é descartado. Interromper é impossível por
construção: não é um defeito, é o desenho.

O #713 corrigiu a razão pela qual ela «não encontrava dados» — mandava ao
motor 5 dos 11 campos que o chat manda, sem `connection_ids` de todas as
ligações e sem o glossário. Isso era um bug e está fechado. **A fluidez
não é um bug: é a arquitectura.**

---

## 2. Nova 2.5 Sonic — os números

Fala a fala (ASR → raciocínio → tool → TTS) dentro de um só modelo, por
um canal bidireccional. Existe na UE em **eu-north-1 (Estocolmo)**; o
nosso cluster está em eu-west-1 (Irlanda).

Âncora de todas as medições: o evento **`userSpeechEnd`** — o modelo a
dizer «a pessoa acabou de falar». É o instante em que a pessoa começa a
esperar, e não coincide com o fim do nosso envio.

| | corrida 1 | corrida 2 | corrida 3 |
|---|---|---|---|
| ligação estabelecida | 7 ms | 7 ms | 8 ms |
| 1.ª ferramenta pedida | 309 ms | 275 ms | 266 ms |
| 1.º texto | 642 ms | 618 ms | — |
| **1.º ÁUDIO** | **766 ms** | **735 ms** | — |

Com a ferramenta a responder em 3 ms. **De 8–90 s para ~0,75 s**, e a
variação entre corridas é de 30 ms.

Mais três coisas que apareceram sem se pedir:

- **O endpointing é dele, e é semântico.** Detectou o fim da pergunta
  ~400 ms depois de a fala acabar, sem cronómetro nosso. Os 2,5 s
  deixam de existir.
- **A transcrição vem de graça.** O primeiro `textOutput` com
  `role: USER` é o ASR da pergunta — `'¿cuántas rutas incumplen el plazo
  de entrega?'`, com os acentos certos. Hoje pagamos isso ao Transcribe
  à parte.
- **A interrupção é nativa.** Numa das sondas apareceu
  `{"interrupted": true}` sem termos pedido nada. O barge-in que não
  conseguimos construir é um evento do protocolo.

### Custo por turno

Medido no `usageEvent`: entrada 279 tokens de voz + ~900 de texto;
saída 118 de voz + ~70 de texto.

| | tokens | preço/1M | custo |
|---|---|---|---|
| voz, entrada | 279 | $3,00 | $0,00084 |
| texto, entrada | 900 | $0,33 | $0,00030 |
| voz, saída | 118 | $12,00 | $0,00142 |
| texto, saída | 70 | $2,75 | $0,00019 |
| | | | **≈ $0,0027** |

Contra a cascata de hoje, só a camada de voz: Transcribe streaming a
$0,024/min com mínimo de 15 s = $0,006, mais Polly neural ~$0,0014.
**≈ $0,0074.** O SQL fica igual nos dois casos.

Ou seja: **2,7× mais barato, e menos dois serviços para manter.**

⚠️ Os preços vêm de agregadores, não da página oficial da AWS. A ordem de
grandeza aguenta a decisão; antes de assinar qualquer compromisso de
margem, confirmar na consola. O que foi medido de verdade são os TOKENS.

---

## 3. O achado que decide o desenho

Os 766 ms são com a ferramenta a responder em 3 ms. **O nosso SQL leva 2
a 15 segundos.** Então a pergunta que importa não é a latência do modelo:
é o que ele faz enquanto espera por nós.

Três sondas, três respostas.

**(a) Com a ferramenta a demorar 4 s, ele cala-se.** Primeiro som a
4815 ms = 266 (ferramenta) + 4000 (nosso SQL) + ~550 (falar). Quatro
segundos de silêncio, exactamente o sintoma que o Lucas descreve.

**(b) Pedir-lhe que avise não funciona.** Com
«*antes de llamar a la herramienta, di en voz alta una frase corta…*» na
instrução de sistema, foi direito à ferramenta. Ignorou.

**(c) Duas ferramentas — uma rápida com o recado, outra com os dados —
também não.** Chamou as duas em cadeia sem falar, e no fim colou o recado
à resposta: *«Dejame ver los datos. Hay dos rutas que incumplen…»*. Ele
**não fala a meio de uma cadeia de ferramentas**.

**(d) Com NADA pendente, fala — em 662 ms.** Uma ferramenta só, que volta
de imediato com a frase a dizer: disse `'Dejame ver los datos.'` a 662 ms
do fim da pergunta. Mas empurrar os dados depois, como bloco de texto
novo, não abre turno nenhum — marcou o anterior `interrupted` e ficou-se.

### A conclusão, e é simples

> **O modelo resolve a latência da voz. O silêncio durante o nosso SQL
> continua a ser nosso para preencher — e preenche-se no cliente, não no
> modelo.**

O desenho que sai disto:

1. Uma ferramenta só, que é o nosso motor de SQL, e espera o que tiver de
   esperar.
2. No instante em que chega o `toolUse`, o servidor manda ao cliente um
   evento `a_pensar`. O cliente toca um recado curto, local, já gravado,
   na língua do perfil. Zero latência, zero custo, e é nosso.
3. Quando o SQL responde, o modelo fala a resposta: ~800 ms depois.
4. Interrupção e fim-de-turno passam a ser eventos do protocolo. O
   `SILENCIO_QUE_FECHA_O_TURNO` e o descarte durante `turn_active`
   desaparecem — não se afinam, apagam-se.

---

## 4. O que isto custa a montar, e os riscos

**O transporte tem de ser o CRT.** O `aws-sdk-bedrock-runtime` usa
`aiohttp` por omissão e o `aiohttp` **não faz event streaming
bidireccional** — a chamada é recusada com
`UnsupportedTransportError`. Exige `awscrt` (uma extensão compilada) na
imagem, e o `boto3` 1.34.28 que lá está não serve para nada disto: não
tem a operação.

### 🔴 E o SDK exige Python ≥ 3.12. Os dois serviços estão em 3.11.

Este é o obstáculo real, e não se vê na documentação do modelo.

```
aws-sdk-bedrock-runtime  TODAS as versões (0.0.1 → 0.11.0): Requires-Python >=3.12
sky-poc-backend          FROM python:3.11-slim   (CI: python-version '3.11')
sky-poc-ai               FROM python:3.11-slim   (CI: python-version '3.11')
```

O `awscrt` em si tem roda `cp311` e instalaria. O que não instala é o
SDK — e é ele que traz a operação bidireccional.

Três saídas, e a terceira é pior do que parece:

**(a) Subir o backend a 3.12.** O caminho honesto — e **medido**: os
**52 pinos exactos do `requirements.txt` têm todos roda para
`cp312`/`manylinux`**, verificados um a um com `pip download
--python-version 3.12 --only-binary=:all:`. Zero precisam de ser
levantados, o que mata o risco que havia aqui: o comentário no ficheiro
avisa que o resolvedor do pip já explodiu uma vez com intervalos, 53 min
de CI gastos.

Sobra o mecânico: duas linhas no `Dockerfile` e quatro
`python-version: '3.11'` nos workflows.

### 🔴 E os dois motores discordam sobre o `awscrt`

Este só apareceu quando a CI o apanhou — o levantamento das rodas foi
com `--no-deps` e, por construção, não podia ver conflitos entre
dependências.

```
amazon-transcribe 0.6.3/0.6.4  ->  awscrt~=0.26.1      (a voz de HOJE)
smithy-http[awscrt]            ->  awscrt~=0.32.0      (o Sonic)
```

Do lado do Sonic é real: o `smithy_http.aio.crt` importa
`awscrt.aio.http`, um módulo que **não existe** no 0.26.1. Com o CRT
antigo o cliente morre a ser construído, e com uma mensagem enganadora —
«awscrt is not installed», quando está.

Isto ameaçava o passo 5 da ordem de trabalho (o motor novo atrás de uma
bandeira, com o antigo intacto): sem conviverem no mesmo processo, não há
bandeira — e sem bandeira a passagem é uma porta de sentido único, num
produto que é demonstrado a clientes.

**Resolvido, e medido.** O pino do `amazon-transcribe` é conservadorismo
do empacotador: com `awscrt==0.37.0` ele faz uma transcrição em streaming
de verdade contra eu-west-1, em espanhol, e devolve o texto certo. Os
dois convivem — só o resolvedor do pip é que não deixa, porque lê o que
está declarado e não o que funciona.

Daí o `requirements-voz.txt`, instalado com `--no-deps` nos três sítios
que instalam (imagem, CI, red-team). A bandeira sobrevive.

Um efeito lateral que vale a pena: o `--no-deps` torna estruturalmente
impossível o acidente que o próprio `ci-pr-gate.yml` avisa — um `pip
install` sem versão depois do `requirements.txt` que actualizou o pytest
e rebentou a recolha dos testes. Nada mais no ambiente pode ser tocado.

**(b) Um serviço só para a ponte, em 3.12.** Isola a versão, mas é mais
uma imagem, mais uma aplicação no ArgoCD e um salto extra no caminho do
áudio (~1 ms dentro do cluster, irrelevante). Troca um dia de trabalho
por uma peça de infra para sempre. Não vale.

**(c) Sem SDK, só com `awscrt`.** Tentador, porque o `amazon-transcribe`
que já enviamos faz exactamente isto — event-stream da AWS, SigV4 e
HTTP/2 bidireccional, em Python 3.8+. A máquina existe no nosso
`requirements.txt`. Mas seria escrever à mão o enquadramento de um
protocolo que não controlamos, para poupar um `apt` de Python. É a opção
que parece esperta em Outubro e custa caro em Janeiro.

**Recomendação: (a).** E fazê-la **sozinha**, no seu próprio PR, antes
de qualquer código de voz — um salto de Python misturado com um motor
novo dá uma avaria que ninguém sabe de quem é.

**Duas regiões — medido, e a favor.** O cluster está em eu-west-1
(Irlanda) e o modelo em eu-north-1 (Estocolmo). A sonda correu do meu
portátil em Portugal, por isso a pergunta era se produção seria pior.

Aperto de mão TLS completo, mediana de 7, dos dois sítios:

| de | → eu-west-1 | → eu-north-1 |
|---|---|---|
| pod de produção (Irlanda) | 5,5 ms tcp / 19,8 ms tls | **40,0 ms tcp** / 87,7 ms tls |
| o meu portátil (Portugal) | 66,2 ms tcp / 188,4 ms tls | **74,3 ms tcp** / 212,7 ms tls |

**O pod está 34 ms mais PERTO de Estocolmo do que o meu portátil.** Os
735–766 ms medidos são, portanto, um tecto: em produção devem descer
umas dezenas de milissegundos, não subir.

Fica dito o que a travessia custa de verdade: ~35 ms de ida e volta a
mais do que se o modelo estivesse na Irlanda. Num turno de 750 ms, é 5%
— e não há alternativa na UE.

### Dois riscos já fechados: a língua e o vocabulário

Eram os dois que podiam matar o plano, e foram medidos com os termos
reais do glossário do projecto «Logística y Transporte» do sandbox —
não com termos inventados para a sonda.

**Português de Portugal — passa.**

```
perguntado   «Qual foi a percentagem de vazio de retorno no último
              trimestre, e qual a rota pior?»
ouviu        'qual foi a porcentagem de vazio de retorno no último
              trimestre e qual a rota pior?'
respondeu    'A percentagem de vazio de retorno no último trimestre foi
              de vinte três vírgula quatro por cento e a pior rota foi a
              de Badajoz para Mérida.'
1.º áudio    929 ms
```

Respondeu em pt-PT de verdade — «percentagem», «vírgula», e não
«porcentagem» nem «ponto». Com os dados a chegarem-lhe em espanhol, o
que era o risco real: a língua segue o PERFIL e não os dados, que é a
regra que já tínhamos decidido para o chat.

Um senão pequeno: a TRANSCRIÇÃO escreveu «porcentagem» (pt-BR) onde a
pessoa disse «percentagem». Não muda o sentido nem o argumento que foi
ao SQL, mas se algum dia mostrarmos a transcrição no ecrã, é por lá que
o pt-BR volta a entrar — e já nos entrou uma vez pelo dicionário.

**Vocabulário próprio — passa, e sem custom vocabulary.**

```
perguntado   «¿Cuál es el vacío de retorno de la ruta de Badajoz a
              Mérida, y cumple el plazo del cliente?»
ouviu        'cuál es el vacío de retorno de la ruta de badajoz a mérida
              y cumple el plazo del cliente?'
passou ao SQL 'cual es el vacio de retorno de la ruta de badajoz a
              merida y si cumple el plazo del cliente'
respondeu    'El vacío de retorno de la ruta es del treinta y uno por
              ciento y el cumplimiento del plazo es del ochenta y ocho
              coma cinco por ciento.'
1.º áudio    891 ms
```

«Vacío de retorno», «plazo del cliente», «Badajoz», «Mérida» — os
quatro inteiros, com acentos. O Sonic não tem equivalente ao *custom
vocabulary* do Transcribe e, para o nosso vocabulário, **não precisa**.

Perguntas longas custam ~150 ms a mais do que a curta (891–929 ms contra
735–766). Continua a ser outra ordem de grandeza.

**Riscos que ficam por fechar, por ordem:**

| risco | como se fecha |
|---|---|
| Sessões longas: a entrada é recobrada a cada turno | medir uma conversa de 10 turnos e ver a curva do `usageEvent` (nota: o silêncio entre turnos **não** conta — medido em S1) |
| O que acontece quando o SQL falha | hoje o turno cala-se (corrigido em parte no #713). Com o Sonic, o `toolResult` tem de levar o erro em texto para ele poder DIZER que falhou |
| Residência dos dados | eu-north-1 é UE. Confirmar que o Bedrock não retém, e que não precisamos de novo texto no RGPD |

---

## 5. Stress do desenho — onde é que isto parte

O que está em cima é a parte boa. Esta secção é o contrário: cada caso é
uma forma de o desenho falhar em produção, e o que fazer. Vem antes de
código de propósito.

A base é o `voice.py` de hoje. Trocar o motor **não** troca o protocolo
que o `voice_session_ws` fala com a web e com a app — e são dois clientes
que partem ao mesmo tempo se o protocolo mudar de baixo.

### 🔴 S1 — Silenciar o microfone mata a sessão

O `muted` de hoje para de alimentar o STT, e com o Transcribe isso está
certo. O Sonic desliga com `ValidationException` depois de **55 s** sem
áudio nem conteúdo interactivo — medido, com essas palavras na mensagem.

Quem silencia e vai beber um café volta a uma sessão morta. O `muted`
tem de passar a alimentar **silêncio**, não a parar de alimentar — é a
inversão exacta do que o código faz hoje.

**E o silêncio é de graça.** Medido: 90 segundos de silêncio (2812
pedaços de 32 ms), muito acima dos 55 do limite:

```
contador antes   input 279 voz / 840 texto   output 60 voz / 31 texto
contador depois  input 279 voz / 840 texto   output 60 voz / 31 texto
o silencio custou NADA
```

Nem um token. Ele tem o seu próprio VAD à entrada e descarta o silêncio
antes de contar. Isto fecha S1 e S9 ao mesmo tempo: a correcção é
alimentar silêncio, e não custa nada fazê-lo.

### 🟠 S2 — O contexto do cliente dentro do callback da ferramenta

Escrevi primeiro que uma task «não herda» o contexto, e **isso está
errado**. Fui medir:

```
tarefa criada ANTES  do set_current_tenant  ->  default      <-- a PLATAFORMA
tarefa criada DEPOIS do set_current_tenant  ->  gbtsolutions
neta, criada dentro da tarefa               ->  gbtsolutions
no próprio handler                          ->  gbtsolutions
```

As tasks herdam, e as netas também — é o PEP 567 a funcionar. O risco é
mais estreito **e mais traiçoeiro**: é de ORDEM. Uma task criada uma
linha antes do `set_current_tenant` fica presa ao `default` para toda a
vida, e o `default` é a base da PLATAFORMA.

E não há erro nenhum: o `_current_tenant` tem
`default=DEFAULT_TENANT_CONTEXT`, portanto `current_tenant()` devolve a
plataforma em silêncio. É exactamente assim que este defeito voltou sete
vezes — em `core/ingestion/service.py`, no `worker/scan_tasks.py`, nos
agentes, no mapa semântico, nas descobertas e na própria voz.

Para o Sonic isto é concreto: o ciclo de escuta é **uma** task criada uma
vez por sessão, e é dela que saem os callbacks das ferramentas. Nasce do
lado errado do `set_current_tenant` e a sessão inteira consulta a base
errada, sem uma linha nos registos.

**A boa notícia é que o padrão certo já existe no nosso código.** O
`voice.py` passa o `ctx` por ARGUMENTO ao `_voice_answer`, e só usa o
`set_current_tenant` como reforço para os serviços a jusante. O Sonic faz
igual: o `ctx` entra no objecto da sessão à entrada do WS, e o callback
usa o argumento. Assim a ordem deixa de poder estragar nada — em vez de
ter de estar certa.

### 🟠 S3 — Uma consulta longa mata o turno a meio

Os 55 s valem para a sessão inteira, não só para o arranque. O nosso SQL
leva 2 a 15 s e cabe. Um que leve 60 não cabe — e morre com a pessoa à
espera, o que é pior do que uma resposta lenta.

Enquanto a ferramenta corre, alguém tem de continuar a alimentar áudio
(é o que a app faz naturalmente, se não a mandarmos parar). Mas há um
tecto duro: **o timeout do nosso SQL tem de ficar abaixo de 55 s**, e
hoje o cliente HTTP tem 120.

### 🟠 S4 — Push-to-talk e o endpointing dele discordam

Em `ptt` o turno fecha quando a pessoa larga o botão. O Sonic decide
sozinho que a pessoa acabou de falar — e responde a meio do botão
premido. Os dois modos não podem coexistir sem se escolher um dono.

A resposta provável: em `ptt`, não abrir o bloco de áudio até ao
`start`, e fechá-lo no `stop`. Mas é uma decisão, não um detalhe, e tem
de ser tomada antes e não descoberta.

### 🟠 S5 — A interrupção nativa não tem como chegar ao cliente

A interrupção é um evento do protocolo (`{"interrupted": true}`), e é
ótimo. Mas o áudio que o cliente já recebeu está em buffer e vai tocar
de qualquer maneira: a Sky é interrompida no servidor e continua a falar
no auscultador.

Falta um evento `descarta_o_que_tens` no nosso protocolo, e um `flush` no
lado do cliente. **Nos dois clientes.** Sem isso, o barge-in que ganhámos
de graça ouve-se pior do que não o ter.

✅ **Feito** (#717 / sky-mobile#74): o `discard_audio` vai pelo mesmo
socket, logo atrás dos pedaços que já lá estavam, e o cliente limpa. Como
efeito lateral corrigiu um defeito de hoje — o áudio que já ia a caminho
quando a pessoa interrompia chegava depois e tocava.

### 🔴 S5-b — E não se pode ouvir enquanto ele pensa

Descoberto a correr a classe de produção contra o modelo, não nas sondas:
**mandar `audioInput` enquanto o modelo espera por um `toolResult`
invalida a sessão.** O erro é um `ValidationException: Invalid input
request, please fix your input and try again` que não diz qual é o
problema, e a sessão morre com a pessoa à espera.

Não vem em documentação nenhuma. As sondas não o apanharam **por sorte**:
nelas o envio de áudio acabava poucas centenas de milissegundos depois do
pedido. A classe alimentava silêncio durante a consulta inteira — que é o
que o produto faz — e partiu à primeira.

A consequência de produto é dura e vale a pena dizê-la antes de alguém a
prometer: **não há barge-in durante o «a pensar»**. Enquanto o nosso SQL
corre, a Sky está surda. Interromper só funciona enquanto ela fala.

É uma limitação do modelo, não uma escolha nossa — e é mais uma razão
para o prazo da ferramenta ser curto.

### 🟡 S5-c — A mesma frase chega duas vezes

Medido: o mesmo `content`, palavra por palavra, em dois eventos com
`contentId` diferente. Um é a legenda da fala, o outro a saída de texto,
e **não há campo que diga qual é qual**.

Sem tratamento, a legenda aparece a dobrar no ecrã. Comparar com a frase
anterior resolve-o sem falsos positivos: ninguém diz a mesma frase
inteira duas vezes de seguida dentro de um turno.

### 🟡 S6 — Quando o nosso SQL falha, ele fica pendurado

Hoje uma falha do motor vira `turn_failed` e a voz cala-se (metade
corrigido no #713). Com o Sonic, se a ferramenta não responder, ele
espera — até aos 55 s, e depois a sessão morre.

O erro tem de ir no `toolResult` **em texto**, para ele poder DIZER que
falhou: «não consegui chegar aos dados». Que é, aliás, melhor do que o
silêncio de hoje.

### 🟡 S7 — Ele reescreve a pergunta antes de nos chegar

Nas medições, o argumento que ele passou à ferramenta **não era o que a
pessoa disse**:

```
ouviu         '...e quala rota pior?'
passou ao SQL '...e qual a rota pior?'          (corrigiu o ASR — bom)

disse         '...y cumple el plazo del cliente?'
passou ao SQL '...y si cumple el plazo del cliente'   (parafraseou)
```

Nos dois casos saiu melhor ou igual. Mas é uma camada de reescrita nova
entre a pessoa e o nosso SQL, que antes não existia — o Transcribe
entregava o que ouvia e mais nada. Uma paráfrase que deixe cair uma
condição («só os de Janeiro») é uma resposta certa à pergunta errada, e
não há como dar por isso.

Mitigação: guardar os dois — o que ele ouviu e o que passou — e mostrar
o que ele ouviu no ecrã. Já temos `partial_transcript`.

### 🟡 S8 — A língua está presa no arranque da sessão

O `voiceId` e a configuração de saída vão no `promptStart`. Mudar de
língua a meio da conversa exige **sessão nova**. Hoje o `locale` é lido
por turno.

Não é grave — ninguém muda de língua a meio — mas o ecrã das Definições
permite-o, e a sessão aberta tem de ser reciclada quando isso acontece.

### ✅ S9 — Uma sessão esquecida: medida, e não custa

Era o risco de factura. **Não existe**: o silêncio não é facturado (ver
S1), e uma sessão parada não consome nada.

Fica ainda assim a valer um prazo nosso — fechar a sessão depois de N
minutos sem fala — mas por causa da quota de sessões concorrentes (S10),
não do custo.

### ⚪ S10 — Concorrência e quota

Uma sessão bidireccional por pessoa a falar, não por pedido. Vinte
pessoas em Live Talk são vinte sessões abertas contra a nossa quota em
eu-north-1, que não foi verificada. Para 20 clientes de ~450 €/mês isto
tem de ser medido antes de prometer.

### ⚪ S11 — O áudio atravessa uma região

Cluster em eu-west-1, modelo em eu-north-1. Está dentro da UE, e por
isso não é um problema de RGPD — mas é uma travessia nova que o texto de
privacidade não menciona, e um cliente que pergunte merece a resposta
certa.

---

## 6. A recomendação

Trocar. Não pela latência — pela latência também — mas porque os dois
defeitos de natureza (turno a cronómetro, impossibilidade de
interromper) deixam de ser problemas nossos para resolver e passam a ser
eventos de um protocolo. É menos código do que temos hoje, não mais.

O que **não** é verdade, e vale a pena dizer antes que alguém o assuma:
isto não torna a resposta mais certa. A qualidade do que ela diz continua
a ser do `sky-ai` e do glossário. O Sonic trata da conversa; os dados
continuam a ser o nosso problema — e o #713 foi a parte disso que estava
mesmo avariada.

---

*Sondas: `sonda.py` (base), `sonda_lenta.py` (ferramenta a 4 s),
`sonda_duas.py` (duas ferramentas), `sonda_empurra.py` (recado
imediato), `sonda_lingua.py` (pt-PT e vocabulário), `sonda_parada.py`
(sessão parada 90 s). Descartáveis — o que fica é este documento.*

---

## 7. A ordem de trabalho que sai disto

Nada aqui é código ainda, de propósito: a regra é validar → documentar →
stress → código, e o stress mudou a ordem.

| # | o quê | porquê primeiro |
|---|---|---|
| 1 | `awscrt` na imagem do backend, e o `boto3` a subir | sem isto não há chamada nenhuma; e é a alteração que mexe no `Dockerfile`, que é o que mais tarde dói |
| 2 | ~~Medir a latência de dentro do cluster~~ | ✅ **feito** — o pod está 34 ms mais perto de Estocolmo do que o portátil. Os 766 ms são um tecto |
| 3 | O contexto do cliente por ARGUMENTO, antes de existir callback | S2 — sétima vez do mesmo defeito. Escrever a assinatura certa antes de haver o que a violar |
| 4 | Eventos novos no protocolo do WS: `a_pensar` e `descarta_o_que_tens` | S5 e o recado do cliente. São dois clientes, e é melhor que o protocolo esteja pronto antes do motor |
| 5 | O motor novo atrás de uma bandeira **por CLIENTE**, com o antigo intacto | ver em baixo — escrevi isto como «uma variável de ambiente» e estava errado |
| 6 | `muted` a alimentar silêncio; prazo de sessão; timeout do SQL < 55 s | S1, S3, S10 |
| 7 | Decidir o `ptt` | S4 — decidido 08/10: sai, fica só mãos-livres |

### A bandeira tem de ser por cliente, porque NÃO HÁ STAGING

Escrevi o passo 5 como «não se troca o motor sem poder voltar atrás numa
variável de ambiente», e implementei-o assim. **Está errado, e a razão
estava à mão:** as máquinas de staging foram desligadas a 18/08 — a conta
ficou só para o ECR e o DNS de produção. O único ambiente a correr é
**produção**.

Uma bandeira por processo em produção é tudo-ou-nada. Ligá-la para
experimentar punha o motor novo em cima dos clientes — num produto que é
demonstrado a clientes. Era pedir para se testar com eles.

A correcção usa o `feature_flags` do registo, que o `auth.py` já lê:

```
tenant_registry.feature_flags = {"voice_engine": "sonic"}   -> só esse cliente
VOICE_ENGINE=sonic                                          -> todos
VOICE_ENGINE=cascata                                        -> travão geral
```

Liga-se no `sandbox`, ouve-se com a app na mão, e nenhum cliente nota. É
o degrau de teste que o ambiente não tem.

A ordem importa: a variável `cascata` ganha à bandeira do cliente. Uma
variável de ambiente mexe-se mais depressa do que uma linha numa base de
dados, e numa avaria é isso que conta.

O passo 2 era o que podia matar isto, e é por isso que foi feito
primeiro. Saiu a favor: **nada aqui está dependente de uma medição que
falte.** O que sobra é trabalho, e decisões de produto (o `ptt`).

---

## Adenda de 09/10/2026 — o que só se viu com a voz a correr

O documento acima foi escrito com medições feitas a mandar **texto** ao
modelo. Esse foi o seu limite, e custou dois defeitos que só apareceram
com o Lucas a falar para o telemóvel. Ficam aqui, porque a lição não é
sobre o Sonic — é sobre o que uma medição prova.

### 1. O `toolResult` tem de ser JSON, ou o canal FECHA

Nos registos de produção, **todas** as sessões:

```
ValidationException: ... Tool Response parsing error
voz/sonic: sessao fechada (cliente=skyfirstlabs, turnos=1, ...)
```

`turnos=1` em todas. O Bedrock recusa o `toolResult` e fecha o canal; a
app reabre o socket à pergunta seguinte, e por isso **cada pergunta
aparecia como uma conversa separada** na lista do Lucas. O
`Attempted to write to closed stream` que vinha a seguir era o eco disto,
não uma causa — e eu quase o persegui como se fosse.

A causa: o `content` ia em prosa. Os dois caminhos de **erro** já usavam
`json.dumps` e passavam; só o caminho bom mandava o texto tal e qual.

**Porque é que nenhuma medição o apanhou:** nenhuma delas chegou a chamar
a ferramenta a sério. O erro só acontece *depois* de uma primeira
pergunta respondida. Uma sessão que abre, troca duas frases e fecha
nunca lá chega — e foi exactamente isso que eu medi, três vezes, e dei
por bom.

### 2. Não há transcrição parcial

Medido com voz a sério (Polly → Sonic, `scripts/sonda_a_voz_a_serio.py`),
duas falas na mesma sessão:

```
 7,395 s  Ouvido   'quantos clientes temos?'
 7,916 s  Dito     'Temos cento e vinte e oito clientes activos.'
28,695 s  Ouvido   'e qual foi a faturação do mês passado?'
29,235 s  Dito     'Desculpe, não consegui encontrar...'
```

Duas falas → **exactamente dois** `Ouvido`, cada um no fim da frase. O
`textOutput` com `role: USER` chega uma vez por elocução, e não por
pedaços.

É isto que põe «...» no ecrã enquanto a pessoa fala: não há nada para
escrever. O vão dura o tempo da frase — 2 a 4 s numa pergunta curta, mais
de 10 s numa longa.

**A decisão em aberto:** para haver legenda ao vivo é preciso desdobrar o
PCM do microfone também para o Transcribe (~0,024 €/min), e deixar o
Sonic só com a conversa. O cliente de streaming já existe, do caminho da
cascata (`src/services/voice_aws.py`) — o trabalho é a bifurcação do
áudio, não um ASR novo. Degrada em segurança: se o Transcribe falhar,
perde-se a legenda e não a conversa.

### A lição

«Abri o canal em 3 ms» não provava que a voz funcionava, e eu escrevi-o
como se provasse. Uma medição só vale o caminho que percorre: para dizer
que a voz funciona, é preciso **falar, deixar o modelo chamar a
ferramenta, e falar outra vez**. É o que a sonda faz, e é por isso que
ela vive no repositório em vez de ter sido um comando descartável.

---

## Adenda 2 de 09/10/2026 — a equipa, e a legenda

### 3. A voz não dizia a que EQUIPAS a pessoa pertence

> «Perguntei: ¿Cuántos clientes tengo? Resposta: Lo siento, no he podido
>  encontrar esa información.»

Nos registos do `sky-ai`, para essa pergunta:

```
crew_role: "guest"   rag_chunks: 0   num_tables: 0
schema 0 · metrics 0 · questions 0 · glossary 0 · catalog 0
orchestrator_out_of_scope -> OUT_OF_SCOPE
```

Não era falta de dados. O motor não tinha **como os encontrar**: o
esquema, as métricas e o glossário vivem todos atrás da equipa, e o
`_voice_answer` não mandava `crew_ids`.

Está escrito no próprio cliente HTTP, e eu li-o ao contrário:

> `crew_ids` … Omitting it means "user is not in any crew"

O pior é que havia **uma decisão escrita** a justificar a omissão, no
`test_a_voz_recebe_o_mesmo_contexto_que_o_chat.py`:

```
"crew_ids": "o sky-ai recalcula-os e sem eles fica mais LARGO,
             não mais estreito"
```

Era o contrário. Sem eles fica *vazio*. A linha foi movida para a lista
da PARIDADE, com a correcção escrita onde a suposição estava.

A correcção usa **o mesmo ajudante que o chat escrito** usa quando não
há equipa activa (`_get_user_crew_ids`). Não alarga o acesso a ninguém:
as equipas são as da própria pessoa, e a voz passa a alcançar o que a
escrita já lhe dava.

### 4. A legenda ao vivo vem do Transcribe

Como o §2 mostrou que o Sonic não dá parciais, a legenda tem de vir de
outro lado. O mesmo PCM do microfone vai também para o Transcribe
(`src/services/voz_legenda_ao_vivo.py`), que devolve parciais em ~300 ms.

A transcrição que **conta** continua a ser a do Sonic: é essa que ele
ouviu, é sobre essa que respondeu, e é essa que fica guardada. A legenda
é substituída por ela assim que chega (`final: true`, que a app já trata).

Três regras, e as três estão em testes:

* **uma avaria aqui não cala a conversa** — se não abrir, ou rebentar a
  meio, perde-se a legenda e mais nada;
* **só vai o que vem do microfone** — a batida de silêncio que mantém a
  sessão do Sonic viva não passa por lá, senão pagava-se a sessão
  inteira em vez da fala;
* **no ditado não há legenda** — lá a transcrição do Sonic já é a
  resposta.

O custo, pela API de preços da AWS no dia: `EU-StreamingAudio` na
Irlanda a **0,0001667 USD/s = 0,010 USD/min**, sem escalões. Uma pergunta
falada tem 3–5 s; 500 perguntas por mês dão ~0,42 USD. (O valor de 0,024
que eu andei a citar era um escalão que já não existe.)

Estocolmo, onde vive o Sonic, **não serve streaming de STT** — só lote.
A legenda vem da Irlanda, e há um teste a fixar isso, porque a avaria
seria silenciosa.

Desliga-se com `VOICE_LIVE_CAPTION=0`, sem entrega.
