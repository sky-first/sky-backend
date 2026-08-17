# Segurança do SSO e isolamento entre clientes

> Estado: **rascunho para revisão do Lucas** — 13/08/2026
> Âmbito: autenticação por SSO, resolução de cliente e isolamento de dados
> entre clientes no plano de produção.

Este documento vem antes do código, por decisão do Lucas: mapear host →
cliente e decidir quem entra em que base de dados é o sítio onde um erro
expõe dados de um cliente a outro.

---

## 1. Como o produto está desenhado

Modelo B: front-end, back-end e serviço de IA **partilhados**; **base de
dados dedicada por cliente**. O pedido chega, o sistema decide de que
cliente é, e a sessão de base de dados passa a apontar para a base desse
cliente (`TenantConnectionManager.session_for`, `src/api/deps.py:26-48`).

A fronteira de isolamento é, portanto, **a escolha da base de dados**.
Tudo o resto depende de ela estar certa.

## 2. Modelo de ameaça

| Atacante | Capacidade | O que quer |
|---|---|---|
| Externo anónimo | Conhece os endereços públicos; tem uma conta Google qualquer | Entrar dentro de um cliente |
| Utilizador legítimo do cliente A | Credenciais válidas em A | Ler dados de B |
| Ex-colaborador de um cliente | Conta desativada, sabe os endereços | Recuperar acesso |

Fora de âmbito neste documento: comprometimento da conta AWS, acesso
direto ao RDS, ataques ao próprio fornecedor de identidade.

---

## 3. Achados

### A1 — O SSO cria utilizadores dentro de qualquer cliente
**Severidade: crítica. Ativa em produção.**

`src/services/auth0_service.py:473-487` (Google; Azure em :573, Okta em
:667 seguem o mesmo padrão):

```python
user = await self.get_user_from_auth0(google_id, provider="google")
if not user:
    user = await self.create_user_from_auth0(...)   # <-- cria
```

O retorno do SSO (`src/api/v1/auth.py:1330-1341`) corre contra a base do
cliente em que o pedido caiu. Não há verificação nenhuma de que o email
autenticado pertence àquele cliente. Qualquer conta Google — incluindo
`@gmail.com` — entra e fica com utilizador criado e espaço de trabalho
(`ensure_default_page_and_space`, :502).

Confirmado que o caminho está ligado em produção: uma sonda com código
inválido em `/api/v1/auth/sso/google/callback` recebeu `invalid_grant`
**do Google**, ou seja as credenciais estão configuradas e a troca é
tentada a sério.

Atenuante circunstancial, não desenho: como a resolução por host está
partida (ver A5), hoje a maior parte dos endereços cai na plataforma e
não num cliente. Deixa de atenuar no momento em que A5 for corrigido.

### A2 — `sso_domain_restriction` é um controlo que não controla
**Severidade: alta.**

O campo existe no modelo (`src/models/tenant.py`), é aceite pelo
Console e gravado (`src/services/console_service.py:229`). Procurado em
todo o `src/`: **nunca é lido no caminho do pedido**. Um operador que o
preencha fica convencido de que restringiu o acesso. Não restringiu.

### A3 — O `state` do OAuth é recebido e ignorado
**Severidade: alta.**

`src/api/v1/auth.py` declara `state` na assinatura do retorno e nunca o
usa. Consequências: sem proteção CSRF no fluxo de autorização, e sem
forma de ligar o retorno ao cliente onde o pedido começou.

### A4 — Ligação a conta existente sem exigir email verificado
**Severidade: alta.**

`src/services/auth0_service.py:244-251`:

```python
existing_user = await self.user_repo.get_by_email(email)
    existing_user.auth0_id = auth0_id
    existing_user.auth_provider = provider
```

Se já existe uma conta com aquele email, a identidade do SSO é **colada**
a ela. O `verified_email` devolvido pelo fornecedor é guardado em
`sso_metadata` mas nunca verificado. Um fornecedor que afirme um email
não verificado toma a conta de um utilizador que usa password.

### A5 — Resolução falhada não recusa, cai na plataforma
**Severidade: alta.**

`src/api/deps.py:48`: sem cliente resolvido, a sessão usa
`DEFAULT_TENANT_CONTEXT` — a base da plataforma. Um pedido de
autenticação que não resolve cliente **autentica contra a plataforma**
em vez de ser recusado. Foi este comportamento que produziu o incidente
do `MULTI_TENANT_ENABLED` desligado.

Adjacente: a resolução por host exige prefixo `workspace-`/`api-` ou
sufixo `-stg` (`src/api/v1/auth.py:76-78`), pelo que a convenção de
produção `{slug}.skyfirstlabs.com` não é reconhecida.

### A6 — Google ligado por omissão em todo o cliente novo
**Severidade: média.**

`DEFAULT_AUTH_METHODS` (`src/models/tenant.py:62-67`) é
`{"password": False, "google": True, ...}`. Cada cliente criado nasce com
a superfície do A1 aberta, sem ninguém a escolher isso.

### A7 — Chaves de Redis sem prefixo de cliente
**Severidade: baixa (defesa em profundidade).**

Três dos quatro usos isolam por UUID e não por cliente: idempotência
(`idempotency:{user_id}:{chave}`), revogação de tokens
(`auth:revoke_before:{user_id}`) e cursores (`cursors:{context_id}`).
Só os limites de tráfego levam `tenant:` explícito
(`src/rate_limit/core.py:132`). O isolamento fica a depender de os UUIDs
não colidirem, em vez de uma fronteira declarada.

**Não é um achado:** o cache semântico das respostas da IA vive na base
de cada cliente (pgvector), não no Redis. Não há caminho de fuga de
respostas entre clientes por cache.

**Não é um achado:** `_is_sky_team_email`
(`src/services/auth0_service.py:171-178`) usa
`endswith("@skyfirstlabs.com")`, **com arroba**. `x@evil-skyfirstlabs.com`
não casa. Não há escalada para operador da Sky por sufixo de domínio.

---

## 4. Desenho da correção

### R1 — O SSO deixa de criar utilizadores
Só entra quem já existe na base daquele cliente. Sem conta prévia →
403 `sso_user_not_provisioned`, sem revelar se o email existe.

Provisionamento automático passa a ser opção **por cliente**, desligada
por omissão: `feature_flags.sso_jit_provisioning`. Quando ligada, só
cria se o domínio do email passar no R3.

### R2 — O retorno do SSO fica preso ao cliente onde começou
O `state` passa a ser um token assinado (HMAC, TTL curto) com
`{tenant_slug, nonce, iat}`. No retorno: verificar assinatura, verificar
que não expirou, verificar que o `tenant_slug` do `state` **é igual** ao
cliente resolvido no pedido. Diferente → 400, sem tocar na base.

Resolve o A3 (CSRF) e o A2/A1 (ligação ao cliente) com a mesma peça.

### R3 — Aplicar a restrição de domínio
Antes de aceitar o utilizador: o domínio do email tem de constar em
`sso_domain_restriction` **ou** em `tenant_domains` daquele cliente. Sem
correspondência → 403.

Se ambos estiverem vazios, o comportamento seguro é **recusar** o SSO
para esse cliente, não aceitar tudo. Um cliente sem domínios declarados
não tem SSO.

### R4 — Exigir email verificado antes de ligar a conta
Só colar a identidade do SSO a uma conta existente se o fornecedor
afirmar o email como verificado. Caso contrário, recusar.

### R5 — Recusar em vez de adivinhar
Nos caminhos de autenticação, se não houver cliente resolvido, responder
400 `tenant_unresolved`. Nunca cair na base da plataforma. O acesso à
plataforma faz-se pelo endereço da plataforma, que resolve
explicitamente.

### R6 — Fechar o Google por omissão
`DEFAULT_AUTH_METHODS` passa a `{"password": True, "google": False, ...}`.
Quem quer SSO liga-o e declara os domínios — o que aciona o R3.

### R7 — Prefixo de cliente nas chaves de Redis
`t:{tenant}:` à frente das chaves de idempotência, revogação e cursores.

---

## 5. Matriz de testes

Cada linha é um teste automático. `sandbox` e `outro` são dois clientes.

| # | Cenário | Esperado |
|---|---|---|
| T1 | SSO Google com email de fora, cliente sem JIT | 403, **nenhuma** linha nova em `users` |
| T2 | Idem, com JIT ligado e domínio fora da lista | 403, nenhuma linha nova |
| T3 | Idem, com JIT ligado e domínio na lista | 200, utilizador criado |
| T4 | `state` de `outro` usado no retorno de `sandbox` | 400, nenhuma escrita |
| T5 | `state` adulterado (assinatura inválida) | 400 |
| T6 | `state` expirado | 400 |
| T7 | Retorno sem `state` | 400 |
| T8 | Fornecedor afirma email existente com `verified_email=false` | 403, conta **não** ligada |
| T9 | Idem com `verified_email=true` | 200, conta ligada |
| T10 | `/auth/login` num host que não resolve cliente | 400 `tenant_unresolved`, **não** consulta a plataforma |
| T11 | Utilizador de `sandbox` tenta password em `outro` | 401, sem revelar existência |
| T12 | Cliente sem domínios declarados, SSO ligado | 403 |
| T13 | Cliente novo criado pelo Console | `google=False`, `password=True` |
| T14 | Duas chaves de idempotência iguais em clientes diferentes | não se veem uma à outra |
| T15 | Utilizador desativado entra por SSO | 403 |

## 6. Stress adversarial — o que pode correr mal com a própria correção

**"Recusar em vez de adivinhar" parte o que já funciona.** O GBT está vivo
em produção. Se o R5 entrar antes de a resolução por host cobrir o
endereço deles, deixam de conseguir entrar. → Verificar por que endereço
o GBT entra hoje **antes** de aplicar o R5, e cobrir esse caso primeiro.

**Fechar o Google por omissão não afeta clientes já criados** — o defeito
só se aplica a novos. Mas o `sandbox` e o `sky` já nasceram com Google
ligado e sem domínios declarados; com o R3, o SSO deles passa a recusar.
Intencional, mas tem de ser dito, não descoberto.

**O `state` assinado precisa de um segredo.** Se usar o `JWT_SECRET_KEY`,
fica ligado à rotação desse segredo; um `state` emitido antes da rotação
falha depois dela. TTL curto (5 min) torna isso irrelevante na prática.

**Exigir email verificado pode bloquear Okta/Azure** se esses
fornecedores não devolverem o campo. → Tratar ausência do campo como
**não verificado** e testar com um retorno real de cada fornecedor antes
de ligar em produção.

**O prefixo de Redis invalida o que lá está.** Chaves antigas ficam
órfãs: idempotência perde-se (pedidos repetidos podem duplicar) e
revogações de token deixam de ser vistas (um token revogado volta a
valer até expirar). → Aplicar numa janela de baixo tráfego e forçar
expiração das chaves antigas.

## 7. Ordem de aplicação

1. R2 + R1 + R4 — fecham o A1, que é o que está aberto agora
2. R3 + R6 — restringem quem pode usar SSO
3. R5 — só depois de confirmar por onde entra o GBT
4. R7 — janela de baixo tráfego

Cada passo com os testes da secção 5 a passar antes de seguir.

---

# 8. A app nativa e o host neutro (17/08/2026)

## O que se partiu, e porquê

Com o A3 fechado, o `state` passou a ser **assinado e preso ao cliente**, e o
retorno passou a ser verificado contra o cliente do *callback*:

```python
callback_tenant = _slug_from_request(request)
verify_state(state, callback_tenant)
```

Isso fecha o A3 para a **web**, onde o callback cai numa página do Next.js e o
frontend consegue mandar `X-Tenant-Slug` no pedido seguinte.

Para a **app nativa** não fecha nada: fecha a porta.

A app fala com um host neutro por desenho — `api.skyfirstlabs.com`, um só para
todos os clientes, porque o cliente é descoberto pelo domínio do email. No
arranque do SSO a app declara o cliente em `?tenant=`, e o `_slug_from_request`
lê-o. **Mas a Google não devolve esse parâmetro no retorno.** No callback:

| fonte de cliente | no callback da app |
|---|---|
| subdomínio `workspace-`/`api-` | não — o host é neutro |
| cabeçalho `X-Tenant-Slug` | não — é uma navegação do browser |
| claim do JWT | não — ainda não há sessão |
| `?tenant=` na query | não — a Google só devolve o que ela própria põe |

Logo `callback_tenant` é sempre `None`, o `state` diz `skyfirstlabs`, e o
retorno é recusado **em 100% das tentativas**. Nos registos de produção:

```
SSO callback recusado (provider=google, tenant=<plataforma>):
    state pertence a outro cliente
```

Há um segundo defeito por baixo do primeiro, e é o mais perigoso: mesmo que a
verificação passasse, a sessão de base de dados aberta pelo middleware num host
neutro é a da **plataforma**. O `handle_google_callback` procuraria o utilizador
na base errada — que é exactamente o achado A1 outra vez, por outro caminho.

## A correção

**Num host que não resolve cliente nenhum, a autoridade sobre o cliente passa a
ser o `state` assinado.** Não é uma excepção à regra do A3: é a mesma regra, com
a fonte que existe naquele caminho.

```python
callback_tenant = _slug_from_request(request) or tenant_from_state(state)
verify_state(state, callback_tenant)
```

E, quando o cliente veio do `state`, o handler **abre uma sessão na base desse
cliente** em vez de usar a da plataforma.

O `state` é HMAC com o nosso segredo, tem TTL de 5 minutos e nonce. Confiar nele
é o mesmo que confiar num claim de JWT — que é, de resto, a fonte nº 4 que o
resolvedor já aceita para clientes sem subdomínio.

## Porque é que isto não reabre o A1/A3

O que o A3 impede é **um `state` obtido num sítio servir para entrar noutro
cliente**. Isso mantém-se:

- Num host **de cliente** (`workspace-x.`, `api-x.`), o host continua a mandar.
  Um `state` de outro cliente continua a ser recusado — a nova fonte só entra
  quando não há host que resolva.
- Um `state` **forjado** morre na assinatura, antes de qualquer leitura.
- Um `state` **expirado** morre no TTL.
- Um `state` **legítimo de outro cliente** leva quem se autentica à base desse
  cliente — que é o comportamento correcto e desejado: é o cliente que ele
  próprio declarou no arranque. Para entrar, continua a ter de existir lá **e**
  passar o `sso_domain_restriction`.

O que muda em risco: quem consiga arrancar um login declarando o slug de outro
cliente obtém um `state` para esse cliente. Já era assim antes desta alteração —
o `?tenant=` no arranque é público. O que o impede de entrar não é o `state`, é
não existir conta nesse cliente e a restrição de domínio.

## Casos que os testes têm de cobrir

1. Host neutro + `state` válido → resolve o cliente do `state` e usa a base dele.
2. Host neutro + `state` forjado → recusa (assinatura).
3. Host neutro + `state` expirado → recusa (TTL).
4. Host neutro + **sem** `state` → recusa.
5. Host **de cliente** + `state` de outro cliente → recusa (o host manda).
6. Host de cliente + `state` do mesmo cliente → aceita, como hoje.
7. O `sky_code` do retorno leva o cliente certo, não `""`.
