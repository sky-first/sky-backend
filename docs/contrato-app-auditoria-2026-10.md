# Contrato backend ↔ app (auditoria da app, 12/10/2026)

O que mudou no backend e o que a app deve ler. Tudo é **aditivo**: nenhum campo
antigo desapareceu.

## 1. Push — o `data` que chega ao tocar

Todas as chaves são strings.

| Chave | Sempre? | Significado |
|---|---|---|
| `type` | sim | tipo da notificação (`agent_finding`, `comment_mention`, `space_invite`…) |
| `notification_id` | sim | id em `/notifications` (para marcar como lida) |
| `target` | sim | `insight` · `conversation` · `notifications` |
| `entity_type` / `entity_id` | sim | achado → `agent_finding` + id do achado; menção → `conversation` + id; convite → `space` + id do projeto |
| `deep_link` | às vezes | achado → `sky://insights/<finding_id>`; menção → `/page?id=…&conversation=…` |
| `finding_id`, `agent_id`, `conversation_id`, `space_id` | quando se aplicam | ids directos |

Routing recomendado na app: `target` primeiro (`insight` → `finding_id`,
`conversation` → `conversation_id`, `notifications` → ecrã de Avisos, onde se
aceita o convite). O `parseDeepLink` actual já abre achados e menções sem
mudanças (lê `entity_type`); só os convites (`target=notifications`) precisam
de um ramo novo.

Quem gera push: achados de agentes, **menções** (`comment_mention`) e
**convites para projeto** (`space_invite` com `title_key=notif.projectInvite`).
Respeita o modo concentração, os silêncios por categoria e — novo — as
preferências com `channel="push"`. O título vem na língua de
`preferences.language` da pessoa.

## 2. `POST /auth/logout`

```json
{ "refresh_token": "…", "push_token": "ExponentPushToken[…]" }
```

`push_token` é opcional; quando vem, o aparelho é desregistado do dono do
refresh token. Sem bearer, por isso a app tem de mandar `X-Tenant-Slug` (como
no `/auth/refresh`) para cair na base do cliente certo. Responde 200 sempre.

## 3. WS `/ws/chat/{page_id}?token=…`

Fecha com **1008** quando a pessoa não pode ver a página (ou ela não existe) e
com **4001** quando o token é inválido/expirado/revogado. Num 1008 a app **não
deve reconectar**.

## 4. `POST /ai/chat/stream` aceita `mentions`

`mentions: [user_id, …]` (opcional). As pessoas são avisadas quando o turno é
gravado (`persist` ou `conversation_id`). O servidor também resolve `@nome` do
texto sem acentos/maiúsculas, só contra quem está na conversa e só se o nome
apontar para uma pessoa — mas os ids continuam a ser o caminho certo.

## 5. `POST /agents/{id}/run` → `already_queued`

`true` quando a chamada não pôs nada na fila porque a estreia da criação já lá
estava (o primeiro `/run` até 2 min depois de `POST /agents/`). Para a app é
igual: o agente está a correr. A app pode simplesmente deixar de chamar `/run`
depois de criar.

## 6. `POST /auth/invite/generate` → `email_enviado`

Novo `email_enviado: bool` (e `access_email_sent`, o nome que a app já lê),
iguais a `email_sent`. `false` = a pessoa tem acesso mas o email não saiu.

## 7. `POST /tickets/{id}/escalate`

Quem abriu o pedido pode escalá-lo. Pedidos de outros: só admin/owner (403).
Um pedido resolvido/fechado tem de ser reaberto antes (400 para o reporter).

## 8. Equipas do cliente (sem projeto)

- Quem criou a equipa, um dono dela ou um admin podem acrescentar/tirar
  pessoas (`POST/DELETE /crews/{id}/members`).
- Novo `GET /crews/{id}/pessoas-para-acrescentar?procura=…&limite=20` →
  `[{id, name, email, avatar}]`, sem quem já está na equipa. Para o `TeamScreen`
  quando `crew.space_id` é `null`.

## 9. Projetos arquivados

`GET /spaces` devolve só os activos; `GET /spaces?archived=true` só os
arquivados. `SpaceResponse.archived_at` (`null` = activo) decide «Arquivar» vs
«Reabrir» (`POST /spaces/{id}/arquivar?reabrir=true`).

## 10. «Notificaciones · Encendido/Apagado»

`GET /settings` → `notifications.enabled` (= não está em pausa) e
`notifications.paused`, calculados do modo concentração. A linha actual da app
(`notifications.enabled`) passa a dizer a verdade sem mudanças. Também
`GET /notifications/preferences/pause` → `{paused, enabled}`.

## 11. Perfil

### Língua das respostas e tema: uma regra para os dois clientes (13/10)

- **`preferences.answer_language` vazio ou ausente = `"auto"`** («Segue a sua
  pergunta»). `GET /auth/me`, `GET /users/me` e `GET /settings` devolvem
  `"auto"` quando a conta nunca escolheu, por isso a web e a app marcam a
  mesma opção. Sem `locale` no pedido, `/ai/chat/stream`, `/ai/query` e
  `/ai/chat` deixam o motor detectar a língua da pergunta.
  - Voz: a resposta vem na língua falada (`locale` do `start`), que é a da
    pergunta.
  - Agentes e textos sem pergunta (agente na fila, SQL gerado): língua da
    interface, porque não há pergunta de onde a tirar.
  - A web ainda manda a língua da interface no `locale` quando a conta está
    vazia (`lib/api/ai.ts`): com o `"auto"` vindo do servidor, deixa de
    acontecer sem mudar código.
- **`preferences.theme` só guarda `light` ou `dark`.** «Sistema» (seguir o
  aparelho) fica em cada aparelho. Um `"system"` (ou outro valor) em
  `PUT /settings` (`theme` ou `preferences.theme`) ou `PUT /users/me` é
  **ignorado**: fica o claro/escuro que lá estava. Um `"system"` antigo não
  sai nas leituras e é limpo na próxima escrita. `theme: null` continua a
  apagar a chave. A app deve deixar de gravar «Sistema» na conta e de o
  aplicar vindo de lá.


`preferences.nickname` e `preferences.response_preferences` (texto, até 60 e
500 caracteres úteis) passam a ir para o motor nas `instructions` de
`/ai/chat/stream`, `/ai/query` e `/ai/chat`. O `nickname` também serve para
resolver `@apelido`. A saudação da app pode ler `preferences.nickname` de
`GET /auth/me`. A voz ainda não os usa.
