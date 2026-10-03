# Demonstrações sectoriais — folha de apresentação

Três projectos prontos a abrir numa reunião, em castelhano, sem o nome
de nenhuma empresa. Os dados são sintéticos e não pertencem a ninguém.

Cada projecto tem **3 ligações, 4 páginas, 24 widgets, 5 agentes e 5
perguntas já respondidas**. Os números dos cartões estão calculados; as
perguntas são fios de conversa que se abrem e se lêem.

| Projecto | Mercado | Período |
|---|---|---|
| Logística y Transporte | Transporte de mercadorias | 12 meses, 18 viaturas, 5.040 viagens |
| Alimentación Selecta y Vinos | Distribuição alimentar e vinhos | 2.318 pedidos, 90 clientes |
| Restauración — Operación de tiendas | Restauração rápida | 90 dias, 12 lojas, 158.712 pedidos |

Os três semeiam-se com o mesmo comando, e voltar a correr não duplica
nada:

```bash
python scripts/semear_demo_sectorial.py transportes --confirmar-base tenant_<slug> --aplicar
```

---

## 1. Logística y Transporte

**Ligações:** Flota (`fleet`) · Operaciones (`ops`) · Carga (`freight`)

### O que abrir, e por que ordem

| Página | O argumento |
|---|---|
| Rentabilidad de flota | 2 de 18 viaturas custam mais por quilómetro do que rendem |
| Vacío de retorno | 118.784 € de gasóleo queimado sem carga — uma linha que não existe em nenhum sistema |
| Plazos y servicio | 88,6 % dentro do prazo *do cliente*, não de um padrão interno |
| Clientes y taller | 140 dias fora da estrada, que não aparecem em factura nenhuma |

### Os números que ficam

- Facturado no período: **1.911.229 €**
- Receita média por km **1,53 €** contra custo médio **1,22 €**
- Diferença entre a metade boa e a metade má da frota: **18.946 €**
- 19,7 % do rodado é em vazio — **246.900 km**
- Oficina: **204.542 €**

### As cinco perguntas

1. ¿Qué vehículos no se pagan?
2. ¿Cuánto gasóleo quemamos en vacío, y en qué trayectos?
3. ¿Qué rutas incumplen el plazo del cliente?
4. ¿Qué clientes dejan más por kilómetro?
5. ¿Qué vehículos se nos están comiendo el taller?

> A quarta é a que costuma mudar a conversa: os clientes rendem entre
> **1,66 e 2,21 €/km**, e o maior em facturação não é o melhor por
> quilómetro.

### Os cinco agentes

Rentabilidade por viatura · vazio de retorno · cumprimento de prazos ·
rentabilidade por cliente · oficina e dias parado.

---

## 2. Alimentación Selecta y Vinos

**Ligações:** Catálogo (`assortment`) · Almacén (`warehouse`) · Comercial (`trade`)

### O que abrir, e por que ordem

| Página | O argumento |
|---|---|
| Caducidad por lote | 50.090 € a caducar em 60 dias, e 32.982 € já caducados em armazém |
| Capital parado | 196.273 € parados **sem serem de guarda** — a distinção que o balanço não faz |
| Margen real | A margem cai de 26,6 % para 22,2 % depois do rappel |
| Clientes y plaza | Quem factura muito e deixa pouco |

### Os números que ficam

- Capital em armazém: **442.111 €**, dos quais **245.838 € de guarda**
  (lá porque têm de estar) e **196.273 € porque não se venderam**
- 114 lotes afectados; a família mais exposta é o **queijo**
- Rappel: **126.110 €** no período
- **4 referências sem uma única venta**, 16.715 € de capital
- Facturado: **2.846.487 €**

### As cinco perguntas

1. ¿Qué mercancía caduca en los próximos 60 días?
2. ¿Cuánto capital tengo parado en almacén, y cuánto es de guarda?
3. ¿Qué referencias no han tenido ni una sola venta?
4. ¿Cuánto me come el rappel, y en qué canal?
5. ¿Qué clientes facturan mucho y dejan poco?

> A quarta mostra que o rappel não está repartido por igual: o canal
> distribuidor passa de **27,0 % de margem bruta a 18,0 % de líquida**,
> enquanto a loja passa de 26,6 % para 25,1 %.

### Os cinco agentes

Validades por lote · capital parado · margem depois do rappel ·
referências sem rotação · concentração de clientes.

---

## 3. Restauración — Operación de tiendas

**Ligações:** Tiendas (`restaurant`) · Servicio (`service`) · Cocina (`kitchen`)

### O que abrir, e por que ordem

| Página | O argumento |
|---|---|
| Velocidad de servicio | Duas lojas falham o prazo em 6 de cada 10 pedidos no pico; as outras dez em 2 |
| Coste de personal | 37,5 % das vendas à noite contra 13,2 % ao jantar — ao contrário do instinto |
| Merma | 9.846 € por validade contra 2.237 € por preparar a mais: dois problemas diferentes |
| Canal y carta | A entrega traz o talão (54,61 €); o balcão traz o volume |

### Os números que ficam

- Tempo médio de entrega: **3m 24s**; 21,1 % acima dos quatro minutos,
  **28,9 % na hora de ponta**
- A loja mais lenta falha **64,1 %** no pico, contra ~22 % das normais
- Pessoal: **1.022.112 €**, 16,6 % das vendas
- Merma total **13.269 €**; a família mais perdida são os hambúrgueres
- Margem média de carta: **68,8 %**

### As cinco perguntas

1. ¿En qué tiendas se nos va el tiempo de servicio en hora punta?
2. ¿Cuánto me cuesta la hora de personal por cada euro que vendo?
3. ¿Qué estamos tirando, y es por caducidad o por preparar de más?
4. ¿Qué canal trae el importe y cuál trae el ticket?
5. ¿Qué familias de la carta sostienen el margen?

> A primeira é a demonstração inteira num ecrã: a média da rede é
> 21,1 %, e a média é exactamente o número que não manda ninguém a lado
> nenhum. Duas lojas estão a 64 % e dez estão a 22 %.

### Os cinco agentes

Tempos de serviço no pico · canais que sobem e descem · merma por
motivo · margem de carta por família · horas de pessoal por loja.

---

## Como isto chega a um cliente

Os dados sintéticos vivem na base `skydemo`, semeados pelo Job 11. Os
projectos são criados pelo Job 17 (`17-job-demos-sectoriais-prd.yaml`),
que corre os três em ensaio antes de aplicar — se alguma consulta
estiver partida, falha com a base do cliente intacta.

A ordem importa: o Job corre com a imagem que está em produção, por
isso o backend tem de ser promovido antes de o manifesto entrar.

## O que foi verificado

- As 72 consultas dos widgets correram contra um Postgres real; nenhum
  widget ficou sem dados
- Os 48 cartões foram formatados com o mesmo formatador do
  `KpiWidget` e lidos um a um
- As 15 respostas foram lidas como o cliente as vai ler
- 79 testes no backend, 3.701 no frontend, `tsc` limpo
- Semear duas vezes dá os mesmos 12 páginas / 72 widgets / 15 agentes /
  15 conversas

**O que não foi verificado:** os três projectos não foram abertos num
browser. A verificação é ao nível dos dados e do conteúdo gravado, não
do ecrã montado.
