# Renovar a sessão sem se expulsar a si próprio

**Data:** 30/09/2026 · **Estado:** desenho, antes de código
**Sensível:** mexe em rotação de tokens e detecção de roubo. Ler o §4 antes de aprovar.

---

## 1. O que aconteceu, com a prova

O Lucas fez uma pergunta na app e falhou. Nos registos do ingress:

```
28/Set 18:22:15  POST /api/v1/auth/refresh   401   (×4, no MESMO segundo)
...
29/Set 09:49:52  GET  /api/v1/presence/{id}  403
29/Set 09:49:52  GET  /api/v1/ws/chat/{id}   403   (×4)
29/Set 09:50:18  GET  /api/v1/voice/session  403
```

O token que a app enviava a 29/09 às 09:49 tinha sido emitido **a 28/09 às
18:23** e expirado às **18:53**. Quinze horas depois, a app continuava a
apresentá-lo — porque nunca conseguiu trocá-lo.

O access token dura **30 minutos** (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30`).

## 2. A causa — uma tesoura de dois lados

Nenhum dos lados sozinho causa o problema. Juntos, garantem-no.

### Lado do cliente: não há protecção contra renovações simultâneas

`packages/api-client/src` tem **um** sítio a chamar `tryRefresh()`, dentro
do `request()`. Ou seja: cada pedido que apanha 401 chama-a por si.

Quando a app volta do segundo plano, vários ecrãs pedem ao mesmo tempo —
presença, conversas, websocket, voz. Todos apanham 401. **Todos chamam
`tryRefresh()` em paralelo, com o mesmo refresh token.**

### Lado do servidor: TOCTOU, e o perdedor destrói a família

Está escrito no código, como risco aceite:

```python
# TODO(BE-09): TOCTOU on concurrent refresh. Two simultaneous refreshes
# with the same token can both read it as active before either revokes,
# so the loser trips the reuse detector and nukes a healthy family by
# mistake. Harden with a row lock (SELECT ... FOR UPDATE) + a short
# grace window, plus a concurrency test. Accepted for now (BE-05).
```

O que acontece na prática:

1. quatro pedidos lêem a mesma linha, todos a vêem activa;
2. o primeiro roda o token, revoga o antigo, emite um novo;
3. o segundo chega com o token agora revogado;
4. o detector de reutilização dispara — e `_revoke_token_family` **revoga
   a família inteira**, incluindo o token que o primeiro acabou de emitir;
5. a sessão fica morta, mesmo tendo sido renovada com sucesso um
   milissegundo antes.

E o cliente, ao ver o 401 sobreviver à renovação, limpa os tokens e manda
a pessoa para o login.

## 3. O que se corrige, e porquê nos dois lados

**Cliente — uma renovação de cada vez.** Guardar a promessa em curso e
devolvê-la a quem chegar entretanto. Quatro pedidos a precisar de renovar
passam a produzir **uma** chamada e a partilhar o resultado.

**Servidor — a janela de graça.** Corrigir só o cliente deixava o buraco
aberto para a web, para outra app, ou para dois aparelhos da mesma pessoa.
E um bloqueio de linha resolve a corrida dentro do mesmo processo mas não
o caso legítimo de dois aparelhos.

A regra passa a ser: um token **acabado de rodar** (dentro de uma janela
curta) que volte a ser apresentado devolve **o mesmo filho** em vez de
disparar o alarme. Fora da janela, o alarme mantém-se tal como está.

## 4. ⚠️ Segurança — o que esta mudança custa

A detecção de reutilização existe para um caso real: alguém roubou um
refresh token e usa-o depois de a vítima já o ter rodado. Hoje isso mata a
família toda, que é o comportamento certo.

**A janela de graça abre uma fresta.** Um atacante que roube o token e o
use *dentro de segundos* da rotação legítima recebe o mesmo filho que a
vítima, em vez de ser detectado.

Porque é aceitável:

* a janela é curta — **10 segundos** — e não renovável: conta-se a partir
  da rotação, não do último uso;
* quem rouba um refresh token normalmente usa-o **mais tarde**, não no
  mesmo segundo em que a vítima o roda; esse caso continua detectado;
* o custo do que temos hoje é **certo e diário**: toda a gente é expulsa;
  o custo da fresta é hipotético e estreito;
* o token roubado **não ganha vida própria**: a próxima rotação legítima
  volta a separar as duas cadeias, e aí o alarme dispara.

**O que NÃO muda:** um token revogado fora da janela continua a matar a
família. Um token desconhecido continua a ser recusado. A troca de
inquilino continua verificada. Nada disto é relaxado.

**Alternativa considerada e rejeitada:** só o bloqueio de linha
(`SELECT … FOR UPDATE`), sem janela. Resolve a corrida dentro de um
processo, mas serializa — o segundo pedido espera, lê o token já revogado,
e dispara o alarme na mesma. Não resolve nada sozinho.

## 5. Como se verifica

1. quatro renovações em paralelo com o mesmo token → **uma** rotação, todas
   recebem um token válido, **a família sobrevive**;
2. o mesmo token apresentado **após** a janela → alarme, família revogada
   (comportamento de hoje, intacto);
3. um token desconhecido → 401, sem tocar em família nenhuma;
4. um token de outro inquilino → 401 por incompatibilidade;
5. no cliente: quatro pedidos a apanhar 401 → **uma** chamada a
   `/auth/refresh`;
6. se a renovação falhar mesmo, a sessão termina como hoje — sem laços.

## 6. O que fica por medir

A janela de 10 segundos é um palpite informado, não um número medido. O
que a justifica é a ordem de grandeza: os quatro pedidos do Lucas
aconteceram **no mesmo segundo**. Se aparecer um caso legítimo mais largo
— uma rede muito lenta, por exemplo — o número sobe com dados, não com
opinião.
