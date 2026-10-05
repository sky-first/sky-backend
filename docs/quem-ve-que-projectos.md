# Quem vê que projectos

> Desenho e casos de stress, antes do código. 05/10/2026.

## O que está mal hoje

O Felipe é admin do `skyfirstlabs`. A barra lateral lista-lhe o projecto
**Remax**. Clica, e apanha um erro.

A causa está escrita no próprio `list_spaces`:

```python
# Tenant owner / admin / sky_operator see ALL non-deleted Spaces
# (including demo ones they didn't personally create or join). Lucas
# reported missing demo Spaces in his sidebar — he is owner of the
# tenant and should see every Space the demo flow has provisioned.
is_admin_like = user.role in ("admin", "owner", "super_admin") or user.is_sky_operator
if is_admin_like:
    spaces_data = await self.space_repo.get_all_with_stats(...)
```

A listagem tem um atalho para administradores; o **abrir** não tem. As
duas vias discordam, e quem está do lado errado da discordância vê uma
porta que não abre.

Não é um caso isolado nesta base de código. O `crew_service` tem o mesmo
defeito corrigido, com o comentário a dizê-lo:

```python
# SECURITY: previously this called get_all_with_stats which returned
# every crew in the tenant — a regular member saw the names + member
# counts of every team in the org.
```

## O que passa a valer

1. **Lista-se o que se abre.** Sem atalho para administradores. Toda a
   gente vê os projectos de que é membro — directamente, ou por
   pertencer a uma equipa dentro deles.

2. **Sem projectos, diz-se isso.** Em vez de uma lista vazia sem
   explicação, uma frase: ainda não está em nenhum projecto, peça a
   quem o gere.

3. **O projecto de demonstração é opcional, e auto-servido.** Nas
   definições, um interruptor. Ligado, a pessoa entra sozinha nos
   projectos marcados `is_demo` — sem convite, sem passar por ninguém.
   Desligado, sai.

## Porque é que o interruptor é uma adesão a sério, e não um filtro

Podia-se fazer o interruptor como um caso especial na listagem: «se a
preferência está ligada, acrescenta também os `is_demo`». Seria menos
código e seria errado.

Acrescentar à **lista** repõe exactamente o defeito que estamos a
corrigir: a pessoa veria o projecto e não o abriria, porque o `get_page`
e os painéis continuam a pedir pertença. Teríamos de abrir uma segunda
excepção no abrir, depois uma terceira nos widgets, e assim por diante —
é essa cadeia de excepções que produz o erro do Felipe.

O interruptor cria uma **linha de `SpaceMember`**. A partir daí todo o
resto do produto funciona sem saber que isto existe.

## Casos de stress

| # | Caso | O que tem de acontecer |
|---|---|---|
| 1 | Admin que nunca entrou num projecto | não o vê; vê a frase do vazio |
| 2 | Admin que **criou** um projecto | vê-o — o criador já é adicionado como membro (`role="owner"`) na criação |
| 3 | Membro de uma equipa dentro do projecto, sem ser membro do projecto | **vê-o** — é o caminho que o `add_crew_member` usa, e cortá-lo trancaria quem trabalha lá |
| 4 | O Lucas, dono do cliente, com as demonstrações semeadas por um Job | vê-as: o semeador cria o `SpaceMember` do dono |
| 5 | Pessoa com o interruptor ligado | entra nos `is_demo` e abre-os de facto |
| 6 | Pessoa que desliga o interruptor | sai dos `is_demo` — e **só** desses; não lhe tocamos nas outras pertenças |
| 7 | Desligar o interruptor num `is_demo` onde a pessoa também foi **convidada** | ⚠️ perderia um acesso que alguém lhe deu de propósito. A saída só remove pertenças que o interruptor criou |
| 8 | A Console, que gere clientes | não usa esta via; tem o seu próprio caminho de gestão e continua a ver tudo |
| 9 | Um projecto sem membro nenhum | fica invisível para toda a gente. É possível hoje (apagar o último membro), e passa a ser visível só pela Console — aceite |
| 10 | Dois interruptores em paralelo (web e telemóvel) | a criação de pertença é idempotente; a segunda não duplica |

## O caso 7, que é o que me preocupa

Se a saída apagar qualquer `SpaceMember` de um `is_demo`, uma pessoa que
tenha sido **convidada** para o projecto de demonstração — porque o
usamos para formação, por exemplo — perde o acesso ao desligar um
interruptor que ela julga ser só uma preferência de arrumação.

Por isso a pertença criada pelo interruptor leva uma marca
(`SpaceMember.origem = "auto_demo"`), e a saída só remove as que a
tenham. Uma pertença dada por alguém fica.

## O que isto NÃO resolve

Um administrador que precise de ver um projecto para o gerir — mudar o
nome, apagar — deixa de o ver na barra lateral. Isso é de propósito: a
gestão é na Console, e misturar «eu trabalho aqui» com «eu administro
isto» foi o que nos trouxe até aqui.
