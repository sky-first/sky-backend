# 🤖 Endpoints de IA - Documentação Completa

Todos os endpoints de IA estão disponíveis em `/api/v1/ai/*`

## 📋 Lista de Endpoints

### 1. Processar Query de IA
**POST** `/api/v1/ai/query`

Processa uma pergunta em linguagem natural e gera uma resposta.

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas no último mês?",
  "widget_id": "uuid-do-widget-opcional",
  "knowledge": ["connection-id-1", "table-name-1"],
  "configure_data": {
    "question": "Qual foi o total de vendas no último mês?",
    "creativity": 50,
    "length": 50,
    "knowledge": ["connection-id-1"],
    "sql_instructions": "Use apenas dados do último mês"
  }
}
```

**Response 201:**
```json
{
  "id": "uuid",
  "question": "Qual foi o total de vendas no último mês?",
  "answer": "Resposta gerada pela IA...",
  "status": "completed",
  "pipeline_id": "uuid",
  "created_at": "2025-01-15T12:00:00Z",
  "updated_at": "2025-01-15T12:00:00Z"
}
```

---

### 2. Enviar Mensagem no Chat
**POST** `/api/v1/ai/chat`

Envia uma mensagem no chat com a IA e recebe uma resposta.

**Request Body:**
```json
{
  "message": "Explique melhor esses dados",
  "widget_id": "uuid-do-widget",
  "context": {
    "previous_messages": [],
    "widget_data": {}
  }
}
```

**Response 201:**
```json
{
  "id": "uuid",
  "type": "assistant",
  "content": "Resposta da IA...",
  "timestamp": "2025-01-15T12:00:00Z"
}
```

---

### 3. Obter Histórico de IA
**GET** `/api/v1/ai/history`

Obtém o histórico de interações com a IA.

**Query Parameters:**
- `filter_type` (opcional): `today`, `week`, `pinned`
- `search` (opcional): Busca por texto
- `category` (opcional): Filtro por categoria
- `skip` (opcional): Número de registros para pular (padrão: 0)
- `limit` (opcional): Número máximo de registros (padrão: 100, máximo: 100)

**Response 200:**
```json
[
  {
    "id": "uuid",
    "query": "Qual foi o total de vendas?",
    "preview": "Resumo da resposta...",
    "answer": "Resposta completa...",
    "date": "2025-01-15T12:00:00Z",
    "tags": ["sales", "finance"],
    "category": "Finance",
    "pinned": false,
    "created_at": "2025-01-15T12:00:00Z",
    "updated_at": "2025-01-15T12:00:00Z"
  }
]
```

**Exemplo de uso:**
```
GET /api/v1/ai/history?filter_type=pinned&search=vendas&category=Finance&skip=0&limit=20
```

---

### 4. Obter Item do Histórico
**GET** `/api/v1/ai/history/{history_id}`

Obtém um item específico do histórico por ID.

**Response 200:**
```json
{
  "id": "uuid",
  "query": "Qual foi o total de vendas?",
  "preview": "Resumo...",
  "answer": "Resposta completa...",
  "date": "2025-01-15T12:00:00Z",
  "tags": [],
  "category": "Finance",
  "pinned": false,
  "created_at": "2025-01-15T12:00:00Z",
  "updated_at": "2025-01-15T12:00:00Z"
}
```

---

### 5. Deletar Item do Histórico
**DELETE** `/api/v1/ai/history/{history_id}`

Deleta um item do histórico.

**Response 200:**
```json
{
  "success": true,
  "message": "History item deleted successfully"
}
```

---

### 6. Fixar Item do Histórico
**POST** `/api/v1/ai/history/{history_id}/pin`

Fixar um item do histórico.

**Response 200:**
```json
{
  "success": true,
  "message": "History item pinned successfully"
}
```

---

### 7. Desfixar Item do Histórico
**POST** `/api/v1/ai/history/{history_id}/unpin`

Desfixar um item do histórico.

**Response 200:**
```json
{
  "success": true,
  "message": "History item unpinned successfully"
}
```

---

### 8. Gerar SQL
**POST** `/api/v1/ai/generate-sql`

Gera uma query SQL a partir de uma pergunta em linguagem natural.

**Request Body:**
```json
{
  "question": "Mostre todas as vendas do último mês agrupadas por produto",
  "knowledge": ["sales_table", "products_table"],
  "sql_instructions": "Use apenas dados do último mês",
  "creativity": 50
}
```

**Response 200:**
```json
{
  "sql": "SELECT product_id, SUM(amount) as total FROM sales WHERE date >= NOW() - INTERVAL '1 month' GROUP BY product_id;",
  "explanation": "Generated SQL query"
}
```

---

### 9. Executar Pipeline
**POST** `/api/v1/ai/pipeline/execute`

Executa o pipeline completo de IA (6 etapas).

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas no último mês?",
  "knowledge": ["connection-id-1"],
  "configure_data": {
    "question": "Qual foi o total de vendas no último mês?",
    "description": "Análise de vendas mensais",
    "instructions": "Use apenas dados do último mês",
    "response_format": "text",
    "creativity": 50,
    "length": 50,
    "knowledge": ["connection-id-1"],
    "sql_instructions": "Agrupe por mês"
  }
}
```

**Response 201:**
```json
{
  "pipeline_id": "uuid",
  "status": "processing"
}
```

**Status possíveis:**
- `processing`: Pipeline em execução
- `completed`: Pipeline concluído
- `error`: Erro no pipeline

---

### 10. Obter Pipeline
**GET** `/api/v1/ai/pipeline/{pipeline_id}`

Obtém os detalhes de um pipeline por ID.

**Response 200:**
```json
{
  "id": "uuid",
  "query_id": "uuid",
  "status": "completed",
  "steps": [
    {
      "id": "1",
      "name": "Question",
      "kind": "question",
      "status": "COMPLETED",
      "content": "Qual foi o total de vendas no último mês?",
      "logs": null,
      "started_at": "2025-01-15T12:00:00Z",
      "completed_at": "2025-01-15T12:00:01Z"
    },
    {
      "id": "2",
      "name": "Orchestrator",
      "kind": "orchestrator",
      "status": "COMPLETED",
      "content": "Processing...",
      "logs": null,
      "started_at": "2025-01-15T12:00:01Z",
      "completed_at": "2025-01-15T12:00:02Z"
    },
    {
      "id": "3",
      "name": "Project",
      "kind": "project",
      "status": "COMPLETED",
      "content": "Projected data",
      "logs": null,
      "started_at": "2025-01-15T12:00:02Z",
      "completed_at": "2025-01-15T12:00:03Z"
    },
    {
      "id": "4",
      "name": "SQL",
      "kind": "sql",
      "status": "COMPLETED",
      "content": "SELECT * FROM sales WHERE date >= NOW() - INTERVAL '1 month';",
      "logs": null,
      "started_at": "2025-01-15T12:00:03Z",
      "completed_at": "2025-01-15T12:00:04Z"
    },
    {
      "id": "5",
      "name": "Tables",
      "kind": "tables",
      "status": "COMPLETED",
      "content": "Tables processed",
      "logs": null,
      "started_at": "2025-01-15T12:00:04Z",
      "completed_at": "2025-01-15T12:00:05Z"
    },
    {
      "id": "6",
      "name": "Answer",
      "kind": "answer",
      "status": "COMPLETED",
      "content": "O total de vendas no último mês foi de R$ 150.000,00",
      "logs": null,
      "started_at": "2025-01-15T12:00:05Z",
      "completed_at": "2025-01-15T12:00:06Z"
    }
  ],
  "current_step": null,
  "errors": null,
  "started_at": "2025-01-15T12:00:00Z",
  "completed_at": "2025-01-15T12:00:06Z",
  "created_at": "2025-01-15T12:00:00Z",
  "updated_at": "2025-01-15T12:00:06Z"
}
```

**Tipos de Steps (kind):**
- `question`: Processamento da pergunta
- `orchestrator`: Orquestração do pipeline
- `project`: Projeção de dados
- `sql`: Geração e execução de SQL
- `tables`: Processamento de tabelas
- `answer`: Geração da resposta final

**Status dos Steps:**
- `COMPLETED`: Etapa concluída
- `PROCESSING`: Etapa em processamento
- `PENDING`: Etapa pendente
- `ERROR`: Erro na etapa

---

### 11. Obter Status do Pipeline
**GET** `/api/v1/ai/pipeline/{pipeline_id}/status`

Obtém apenas o status atual do pipeline.

**Response 200:**
```json
{
  "status": "completed",
  "current_step": null
}
```

---

## 🔐 Autenticação

**Todos os endpoints requerem autenticação JWT.**

Inclua o token no header:
```
Authorization: Bearer <access_token>
```

## 📝 Notas

- Atualmente usando **MockAIService** para desenvolvimento
- Em produção, será integrado com OpenAI, Anthropic, etc.
- O pipeline processa 6 etapas sequencialmente
- Histórico é salvo automaticamente após cada query
- SQL gerado pode ser executado nas conexões configuradas

## 🧪 Testar

### Exemplo com cURL:

```bash
# 1. Fazer login primeiro
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123"}' \
  | jq -r '.access_token')

# 2. Processar query
curl -X POST http://localhost:8000/api/v1/ai/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Qual foi o total de vendas?",
    "knowledge": ["sales"]
  }'

# 3. Obter histórico
curl -X GET "http://localhost:8000/api/v1/ai/history?filter_type=pinned" \
  -H "Authorization: Bearer $TOKEN"
```

## 📚 Documentação Interativa

Acesse a documentação interativa em:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

