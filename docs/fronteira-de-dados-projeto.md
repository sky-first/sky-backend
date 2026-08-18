# A fronteira de dados passa da equipa para o projeto

> Decisão do Lucas, 18/08/2026. Este documento vem **antes** do código, como é
> regra para trabalho de segurança nesta base: primeiro o que está lá hoje,
> depois as brechas, depois os casos de teste, e só então a alteração.

## 1. O modelo decidido

```
Projeto (era Space)  ── escolhe QUE DADOS se podem ver
  └── Equipa (era Crew) ── só pessoas
        └── pessoas (ninguém existe fora de uma equipa)
```

A confusão que se desfaz: a *crew* era ao mesmo tempo um grupo de pessoas **e**
um recorte de dados. Ninguém a conseguia explicar sem desenhar. O recorte sobe
para o projeto; a equipa fica a ser gente.

## 2. O que o código faz hoje

`PermissionService.get_authorized_tables()` decide, para um utilizador e uma
ligação, que tabelas a IA pode ver. Em contexto colaborativo:

```python
if crew_ids:
    return await self._get_crew_table_names(connection_id, crew_ids)
```

Ou seja: **a equipa é a fronteira**. As tabelas vêm de `crew_tables`, e sem
linha não há acesso.

Duas notas sobre o que já foi verificado, para não se andar a corrigir o que
não está partido:

- O *docstring* do modelo (`src/models/crew.py`) diz que uma equipa com ligação
  e sem linhas em `crew_tables` **herda todas as tabelas do projeto**. Isso é
  falso desde a reescrita fail-closed: `_get_crew_table_names` devolve `[]`.
  O comentário é que está velho, não o comportamento. Corrige-se o comentário.
- O `perm.access_level == "full"` ao nível do projeto devolve tudo — mas só é
  alcançado quando **não** há `crew_ids`, porque o ramo da equipa faz `return`
  antes. Não é um caminho de fuga no modelo actual.

## 3. A brecha real: `crew_ids` é acreditado

`get_authorized_tables` aceita `crew_ids` de quem a chama e **nunca verifica
que o utilizador pertence a essas equipas**. Hoje os dois chamadores tapam-na
por fora:

| Chamador | Como resolve as equipas | Seguro? |
|---|---|---|
| `api/v1/ai.py` (chat) | valida explicitamente contra as equipas do utilizador; se não pertencer, cai nas dele | sim |
| `api/v1/agents.py` (agentes) | usa o âmbito do agente — que passou a ser verificado no RBAC em #634 | sim, desde #634 |

Isto é seguro **por acidente de chamada**, não por construção. Um terceiro
chamador que passe o `crew_id` que lhe vier do pedido abre a porta outra vez —
foi exactamente esse o defeito #634. A verificação tem de descer para dentro
do serviço.

## 4. O que muda, e o que isso custa

Passar a fronteira para o projeto **alarga** o acesso: hoje um membro vê a
intersecção (projeto ∩ equipa); amanhã vê o projeto inteiro. Para um cliente
vivo que tenha equipas com recortes estreitos, isto é exposição nova de dados
reais — não é uma alteração cosmética e não pode entrar em produção sozinha.

Por isso vai atrás de um interruptor, `DATA_BOUNDARY`, com dois valores:

- `crew` — o que existe hoje. **Por omissão.**
- `project` — o modelo decidido.

Para saber o que muda em cada cliente antes de virar o interruptor, corre-se
na base do cliente (só leitura):

```sql
-- Equipas cujo recorte é MAIS ESTREITO do que o do projeto: são estas, e só
-- estas, as pessoas que passam a ver mais.
SELECT s.name AS projeto, c.name AS equipa,
       count(DISTINCT ct.table_name) AS tabelas_da_equipa,
       (SELECT count(DISTINCT st.table_name)
          FROM space_tables st WHERE st.space_id = s.id) AS tabelas_do_projeto
  FROM crews c
  JOIN spaces s ON s.id = c.space_id
  LEFT JOIN crew_tables ct ON ct.crew_id = c.id
 GROUP BY s.id, s.name, c.id, c.name
HAVING count(DISTINCT ct.table_name) <
       (SELECT count(DISTINCT st.table_name)
          FROM space_tables st WHERE st.space_id = s.id);
```

Linhas zero significa que virar o interruptor não muda nada para esse cliente.

## 5. Os casos que os testes têm de cobrir

Com `DATA_BOUNDARY=crew` (hoje):

1. Membro de equipa com recorte → vê só o recorte.
2. Membro de equipa sem linhas em `crew_tables` → não vê nada (fail-closed).
3. Duas equipas → união dos recortes.

Com `DATA_BOUNDARY=project`:

4. Membro de qualquer equipa do projeto → vê as tabelas do projeto.
5. Duas equipas diferentes no mesmo projeto → vêem o mesmo. É o objectivo.
6. Projeto sem tabelas escolhidas → não vê nada (fail-closed, não "tudo").

Em ambos, e é aqui que mora a brecha do §3:

7. **`crew_ids` de uma equipa a que o utilizador não pertence → ignorado.**
8. **`space_id` de um projeto onde o utilizador não está → nada.**
9. Modo pessoal continua aditivo (é a caixa dele, não um projeto partilhado).
10. Quem **criou** a equipa (ou o projeto) conta como estando lá, mesmo sem
    linha em `crew_members` / `space_members` — foi essa pessoa que escolheu o
    recorte, e recusá-la não fecha brecha nenhuma.

11. Quem chama sem `space_id` mas com equipa: o projeto tira-se da equipa, para
    a resposta não mudar conforme a porta de entrada. Equipas de projetos
    diferentes na mesma chamada → não se elege nenhum.

Estão em `src/tests/test_fronteira_de_dados_projeto.py` (10) e
`src/tests/test_quem_ve_o_que_no_projeto.py` (9).

## 6. O que fica de fora, e porquê

"Nenhum membro sem equipa" continua a ser convenção da interface, não regra do
servidor: a app não deixa criar gente solta, mas a API deixa. Fechar isso é
uma migração de dados (o que se faz a quem já lá está solto?) e merece decisão
à parte. Fica escrito para não passar por esquecido.
