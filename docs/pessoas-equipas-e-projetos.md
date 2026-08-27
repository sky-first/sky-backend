# Pessoas, Equipas e Projetos — o modelo completo

> Escrito a 26/08/2026, a pedido do Lucas, depois de ele encontrar o modelo
> incoerente a usar a app. Vem **antes** do código, como é regra para trabalho
> de modelo e segurança nesta base. Substitui a decisão S6 de
> `modelo-projeto-equipa-e-pedidos-de-acesso.md` §6 — e diz porquê.
>
> Cobre **web e telemóvel**. Uma configuração que só existe num dos dois é
> uma configuração em que não se pode confiar.

---

## 1. Onde estamos, e porque é que se lê mal

A palavra *equipa* faz hoje dois trabalhos:

1. **um grupo de pessoas da empresa** — a Comercial, os Dados
2. **o recorte de dados dentro de um projeto** — o que a `crew` era antes de
   `DATA_BOUNDARY=project`

O segundo trabalho **já acabou**. Com a fronteira no projeto, `crew_tables`
deixou de ser consultada e a equipa passou a ser só gente
(`models/crew.py`, `permission_service.py:727`). Mas o nome ficou, a interface
ficou, e o resultado é o que o Lucas descreveu: *"não estou entendendo muito
bem"*.

O que existe hoje, verificado na base:

```
spaces          (projetos)        deleted_at, is_demo, created_by
space_members   (pessoas)         role: owner | editor
space_connections                 os dados do projeto
crews           (equipas)         space_id AGORA opcional (25/08)
crew_members                      role: owner | editor | viewer
crew_tables / crew_connections    mortos com DATA_BOUNDARY=project
audit_events                      existe e é rico; a app não o mostra
```

**Dois vocabulários de papéis para a mesma ideia:** o projeto tem
`owner|editor`, a equipa tem `owner|editor|viewer`. Ninguém consegue explicar
a diferença, porque não há nenhuma.

---

## 2. O que os outros fazem

Não é apelo à autoridade — é que estas três resolveram o mesmo problema e
convergiram na mesma forma.

| | Grupo | Como entra no projeto |
|---|---|---|
| **Jira** | *Group* (da organização) | atribui-se-lhe um **project role** |
| **Confluence** | *Group* | *space permissions* por grupo |
| **Miro** | *Team* (da conta) | o projeto convida pessoas **ou** grupos |
| **Google Drive** | *Google Group* | partilha-se com o grupo, com um papel |

**A peça comum, e a que nos falta: a ligação grupo↔projeto guarda um papel.**
O mesmo grupo é leitor num projeto e editor noutro. Não se convida a Comercial
e pronto — convida-se **como** alguma coisa.

E todos usam **ligação viva**, não cópia: acrescentar alguém ao grupo dá-lhe
acesso a tudo onde o grupo está.

---

## 3. O modelo

```
   PESSOAS ──┐
             ├──► EQUIPA ──┐
   (do cliente)            ├──► ACESSO AO PROJETO ──► DADOS DO PROJETO
             └─────────────┘         (com papel)
              (directo)
```

**Pessoa** — existe no cliente. Provisionada por um admin; não há registo
público.

**Equipa** — uma lista de pessoas **do cliente**. Não tem projeto, não recorta
dados, não dá acesso a nada por si.

**Projeto** — tem dados e tem *acesso*. O acesso vem de duas origens, e é isso
que muda tudo:

| Origem | Como se remove |
|---|---|
| **por equipa** — a equipa X entra como *editor* | tirando a equipa, ou a pessoa da equipa |
| **directo** — a Ana entra como *leitor* | tirando a Ana |

Uma pessoa pode ter as duas. **Ganha o papel mais forte** — é o que o Jira faz,
e a alternativa (o mais fraco) leva a acessos que desaparecem por razões que
ninguém consegue explicar.

### 3.1 Um vocabulário de papéis, e só um

| Papel | O que pode | Onde se usa |
|---|---|---|
| **Dono** | tudo, incluindo apagar o projeto e mudar acessos | projeto |
| **Editor** | perguntar, criar agentes, escrever | projeto e equipa |
| **Leitor** | ver e perguntar; não escreve nada partilhado | projeto e equipa |

`space_members.role` passa a aceitar `viewer`. O vocabulário fica igual nos
dois sítios — hoje não fica, e é confusão gratuita.

### 3.2 Porque é que a ligação é VIVA, e não uma cópia

A 18/08 decidimos o contrário (S6): convidar uma equipa **copiava** as pessoas,
para evitar a armadilha de *tirar alguém da equipa e julgar que se lhe cortou o
acesso*. Implementei isso a 25/08.

**Está errado, e mudo-o aqui.** A cópia resolve a armadilha destruindo a razão
de existir da equipa: acrescentar alguém à Comercial não o mete nos oito
projetos onde a Comercial trabalha, e volta-se ao trabalho manual que a equipa
existia para poupar. Foi exactamente a queixa do Lucas.

A armadilha resolve-se de outra maneira, e é a que os outros usam:
**mostrar a proveniência**.

```
Ana Silva      Editor · via equipa Comercial
Bruno Costa    Leitor · convidado directamente
```

Quem lê isto sabe onde mexer. E ao tirar alguém de uma equipa, a interface diz
quantos projetos isso afecta **antes** de confirmar.

---

## 4. O que passa a existir

### 4.1 Ligação equipa↔projeto

```sql
CREATE TABLE space_crews (
    id          uuid PRIMARY KEY,
    space_id    uuid NOT NULL REFERENCES spaces(id)  ON DELETE CASCADE,
    crew_id     uuid NOT NULL REFERENCES crews(id)   ON DELETE CASCADE,
    role        varchar(20) NOT NULL,       -- owner | editor | viewer
    added_by    uuid NOT NULL REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (space_id, crew_id)
);
```

`added_by` não é enfeite: um convite em massa sem autor é um acesso que
ninguém sabe explicar daqui a três meses.

### 4.2 A resolução de acesso, num sítio só

```
acesso(pessoa, projeto) =
    max_papel(
        space_members.role      onde user_id = pessoa,
        space_crews.role        onde crew_id ∈ equipas(pessoa)
    )
```

**Uma função, um sítio.** `PermissionService.get_authorized_tables` continua a
ser o único caminho para dados; esta resolução alimenta-o. Nenhum chamador
calcula acesso por si — foi por não ser assim que nasceu o #634.

### 4.3 Ciclo de vida do projeto

| Gesto | O que faz | Quem |
|---|---|---|
| **Arquivar** | sai das listas; dados e conversas ficam; nada corre | dono |
| **Reabrir** | volta | dono |
| **Apagar** | soft delete, com o nome escrito à mão para confirmar | dono |
| **Sair** | tira-se a si próprio | qualquer membro directo |
| **Duplicar** | novo projeto com as mesmas ligações e acessos, **sem conversas** | dono |

`spaces` ganha `archived_at timestamptz NULL`. Arquivar **pausa os agentes** do
projeto — um projeto arquivado que continua a gastar tokens é uma fatura que
ninguém percebe.

### 4.4 Quem fez o quê

`audit_events` já existe e é rico. Falta escrever-lhe estes gestos e mostrá-los
no projeto:

```
crew.added_to_space · crew.removed_from_space · space.member.added
space.member.removed · space.member.role_changed · space.archived
space.deleted · space.duplicated · connection.linked · connection.unlinked
```

---

## 5. Onde isto parte (stress adversarial)

**A1 — Escalada por equipa.** Alguém com `crews.members.manage` numa equipa
mete-se nela e ganha o que a equipa alcança em oito projetos.
→ Gerir os membros de uma equipa exige **admin do cliente**, não o papel de
dono da equipa. Uma equipa é uma chave-mestra; não se entrega a chave a quem
só usa uma porta.

**A2 — O último dono desaparece.** O dono despromove-se, ou sai, ou é apagado.
→ Já travado na equipa (25/08). Falta **no projeto** e no gesto de *sair*: a
saída do último dono é recusada com a mesma frase.

**A3 — Amplificação silenciosa.** Acrescentar alguém à Comercial dá-lhe acesso
a oito projetos de uma vez, sem ninguém no ecrã dos projetos ver nada.
→ Ao acrescentar alguém a uma equipa, dizer **a que projetos isso dá acesso**,
antes de confirmar. É o preço da ligação viva, e paga-se aqui.

**A4 — Remoção que não remove.** Tirar a Ana do projeto quando ela lá está pela
equipa Comercial.
→ A interface **não deixa** tirar por essa via; explica que o acesso vem da
Comercial e oferece as duas saídas reais: tirar a equipa, ou tirar a Ana da
equipa. Remover-lhe a linha directa quando ela nem a tem é o gesto que dá a
falsa sensação de ter cortado.

**A5 — Duplicar como fuga.** Duplicar um projeto copia as ligações de dados;
quem duplica passa a ter um projeto com dados a que talvez não devesse chegar.
→ Duplicar exige **as mesmas permissões que ligar cada fonte**. Se não podes
ligar, o duplicado nasce sem essa fonte, e diz-se quais ficaram de fora.

**A6 — Arquivar para esconder.** Arquivar tira das listas; alguém arquiva para
tapar um projeto sob escrutínio.
→ Arquivar é auditado e reversível, e os projetos arquivados continuam
visíveis ao admin com um filtro. Nunca desaparecem para quem manda.

**A7 — Apagar por engano.** «Apagar» ao lado de «Arquivar».
→ Escrever o nome do projeto à mão. É o travão que o GitHub usa e funciona.

**A8 — Papel mais forte por acumulação.** A Ana é leitora directa e a Comercial
é editora. Fica editora.
→ É a decisão do §3, e está escrita para ser escolha e não acidente. O ecrã
mostra as duas origens, para ninguém se enganar sobre o porquê.

**A9 — Equipa apagada com projetos a apontar-lhe.** `ON DELETE CASCADE` tira o
acesso a toda a gente que só lá estava por ela.
→ É o comportamento certo, mas **silencioso**. Apagar uma equipa diz quantas
pessoas perdem acesso e a que projetos, antes de confirmar.

**A10 — Sair do próprio projeto e perdê-lo.** Uma pessoa sai de um projeto que
só ela via.
→ Se é o último dono, recusa-se (A2). Se não é, sai — e o projeto continua a
ter dono.

---

## 6. Casos de teste

Acesso:
1. Pessoa só por equipa vê o projeto; tirada da equipa, deixa de ver **na
   pergunta seguinte**, não na sessão seguinte.
2. Pessoa com acesso directo e por equipa fica com o papel mais forte.
3. Tirar a linha directa não tira o acesso que vem da equipa — e o ecrã diz.
4. Equipa sem projeto nenhum não dá acesso a nada.
5. Projeto sem dados devolve zero, nunca "tudo".

Papéis:
6. O último dono do projeto não se despromove.
7. O último dono não sai do projeto.
8. Leitor não cria agentes nem escreve.
9. Gerir membros de uma equipa exige admin do cliente. *(A1)*

Ciclo de vida:
10. Projeto arquivado sai das listas, **pausa os agentes**, e reabre inteiro.
11. Apagar exige o nome escrito; sem isso, recusa.
12. Duplicar leva ligações e acessos, **não leva conversas**.
13. Duplicar sem permissão numa fonte deixa-a de fora e **diz qual**. *(A5)*

Amplificação:
14. Acrescentar alguém a uma equipa mostra os projetos afectados antes. *(A3)*
15. Apagar uma equipa mostra quem perde acesso e onde. *(A9)*

Registo:
16. Cada gesto do §4.4 escreve em `audit_events` com actor e alvo.

---

## 7. O que fica de fora da v1, escrito para não passar por esquecido

- **Papéis por fonte dentro do projeto** (a Comercial vê Vendas, não Salários).
  O `space_tables` suporta-o; a interface não. Fica.
- **Grupos aninhados** (uma equipa dentro de outra). O Jira tem; complica a
  resolução de acesso e ninguém no-lo pediu.
- **Convites por link**. Todo o acesso passa por alguém que o dá.
- **Row/column level security**. Existe na web, não vem para o telemóvel.

---

## 8. Ordem de execução

Cada fatia entra com os seus testes, e nenhuma entra sem o §5 respondido.

1. **Vocabulário** — `viewer` no projeto, papéis traduzidos, «Geral». *Feito
   em parte a 25/08.*
2. **`space_crews` + resolução de acesso num sítio** — é a fatia de segurança;
   é a que leva os testes 1 a 5.
3. **Proveniência na interface** — «via equipa Comercial». Sem isto a ligação
   viva é a armadilha do S6 outra vez.
4. **Convidar pessoa isolada** — com procura e confirmação.
5. **Ciclo de vida** — arquivar, reabrir, apagar, sair, duplicar.
6. **Avisos de amplificação** — A3 e A9.
7. **Registo no projeto** — ler o `audit_events` que já existe.

A web e o telemóvel entram **na mesma fatia**. Não se fecha uma fatia com um
dos dois por fazer.
