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
imagem do backend, e o `boto3` 1.34.28 que lá está não serve para nada
disto: não tem a operação.

**Duas regiões.** O cluster está em eu-west-1 e o modelo em eu-north-1.
A sonda correu do meu portátil em Portugal, por isso os 766 ms incluem
mais salto do que produção terá — mas é ruído do mesmo lado da conta, não
a favor. Falta medir de dentro do cluster.

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
| Sessões longas: a entrada é recobrada a cada turno | medir uma conversa de 10 turnos e ver a curva do `usageEvent` |
| O que acontece quando o SQL falha | hoje o turno cala-se (corrigido em parte no #713). Com o Sonic, o `toolResult` tem de levar o erro em texto para ele poder DIZER que falhou |
| Residência dos dados | eu-north-1 é UE. Confirmar que o Bedrock não retém, e que não precisamos de novo texto no RGPD |

---

## 5. A recomendação

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
imediato), `sonda_lingua.py` (pt-PT e vocabulário). Descartáveis — o que
fica é este documento.*
