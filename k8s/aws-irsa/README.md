# Permissões AWS para a pipeline de voz

A pipeline de voz chama **Amazon Transcribe** (STT) e **Amazon Polly** (TTS) em
`eu-west-1`. Este ficheiro é a política de permissões que o backend precisa
para o fazer sem as credenciais SSO temporárias de 4 horas que hoje se exportam
à mão.

## A cloud é AWS — sem ambiguidade

A versão anterior deste README perguntava se a produção corria em Azure ou AWS,
por causa dos manifestos Azure na pasta `k8s/`. A dúvida era legítima e a
resposta é: **AWS EKS, eu-west-1**.

A pasta `k8s/` deste repositório **está morta** — não é por aí que a produção
faz deploy. O deploy real é GitOps via ArgoCD a partir do repositório
`sky-infra`, branch `main`, em `gitops/bootstrap/production-aws/backend.yaml`.
Os manifestos Azure são resto de outra era; existe inclusive um repositório
`sky-first-sky-infra-azure-archive` marcado *"no longer active — do not apply"*.

## Não é preciso ServiceAccount nova

Esta pasta chegou a ter um `serviceaccount.yaml` e um `iam-trust-policy.json`.
**Foram removidos**, e é importante perceber porquê antes de alguém os
reintroduzir:

O backend de produção **já tem** uma ServiceAccount com IRSA, criada pelo chart
via GitOps, a assumir a role:

```
arn:aws:iam::032080729567:role/sky-be-prd-platform-tenants-access
```

Aplicar uma segunda ServiceAccount com `kubectl` criava um recurso fora do
GitOps. O ArgoCD tem `selfHeal` e `prune` ligados: ou a desfazia, ou ficavam
duas identidades a competir pelo mesmo pod. A relação de confiança com o
provedor OIDC do EKS também já está estabelecida — não há nada a recriar.

## O que falta, então

Uma única coisa: **acrescentar as permissões de voz à role que já existe.**

```
aws iam put-role-policy \
  --role-name sky-be-prd-platform-tenants-access \
  --policy-name sky-voice \
  --policy-document file://iam-voice-permissions.json \
  --profile sky-production
```

Verificar dentro de um pod:

```
aws sts get-caller-identity   # deve mostrar .../sky-be-prd-platform-tenants-access
```

A partir daí uma sessão de voz funciona **sem** credenciais SSO exportadas e sem
andar a mexer no `VOICE_STT_PROVIDER`.

`Resource: "*"` é o esperado: estas ações do Transcribe e do Polly não aceitam
ARNs de recurso.

## `MFA_EXEMPT_EMAILS` — atenção ao ambiente

Também é preciso, para o revisor da loja entrar só com email + password (um
pedido de TOTP bloqueia a revisão, e é a causa nº1 de rejeição):

```
MFA_EXEMPT_EMAILS = demo@skyfirstlabs.com
```

⚠️ **Vai em produção, não em staging.** O cluster de staging está desligado
para não duplicar custos enquanto não há clientes — a produção é o único
backend de pé, é lá que vive a demo pública, e é contra produção que o revisor
da Apple e da Google vai autenticar-se. Pôr isto só em staging não tinha
qualquer efeito na revisão.

O risco fica contido pelo desenho: a isenção é avaliada **depois** de a password
ser verificada, salta apenas o segundo fator, e só para uma lista explícita que
está vazia por omissão. A regra a respeitar é uma — essa conta só pode ver dados
de demonstração, nunca de um cliente real.

## Seed da conta de revisão

⚠️ **Não usar o `seed_demo.py` para isto.** Uma versão anterior deste README
mandava fazê-lo, e estava errado — o erro veio de eu ter repetido a instrução
sem ler o script.

Aquele script existe para desenvolvimento local e tem uma guarda que o impede
de correr contra uma base não local. A guarda está certa: ele criava um
utilizador `role="admin"` com password em código e um **segredo TOTP fixo**,
também em código. Um segredo TOTP no repositório não é MFA — quem tem o
ficheiro gera códigos válidos para sempre. Em produção seria uma porta de
administrador com a chave publicada. Contorná-la com
`ALLOW_REMOTE_DEMO_SEED=1` seria desligar de propósito a proteção.

Usar `scripts/seed_review_account.py`, escrito para produção:

```
command: ["python", "scripts/seed_review_account.py"]
env:
  - name: REVIEW_ACCOUNT_PASSWORD
    valueFrom:
      secretKeyRef:
        name: sky-be-prd-aws-common-app-secrets
        key: review_account_password
```

Diferenças que interessam:

* password **pelo ambiente**, vinda do Secrets Manager — recusa arrancar sem ela
* **não inscreve MFA nenhum**; o revisor entra só com email + password porque o
  endereço está em `MFA_EXEMPT_EMAILS`, que é para isso que essa lista serve
* papel **`member`**, não `admin`
* idempotente, e avisa se o tenant de demonstração ainda não existir

Corre **depois das migrações** e depois dos Jobs que semeiam o conteúdo de
demonstração (`gitops/manifests/demo-seed` no `sky-infra`, aplicados pela
Application `sky-demo-seed`) — sem conteúdo, o revisor entra e não vê nada.
