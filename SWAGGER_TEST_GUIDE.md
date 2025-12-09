# 🧪 Guia Completo de Testes - Swagger UI

Este guia fornece exemplos funcionais prontos para copiar e colar no Swagger UI para testar **TODOS** os endpoints do backend.

**URL do Swagger:** http://localhost:8000/docs

**Credenciais de Teste:**
- Email: `test@example.com`
- Password: `test123`

---

## 📋 Índice

1. [Autenticação](#1-autenticação)
2. [Usuários](#2-usuários)
3. [Workspaces](#3-workspaces)
4. [Dashboards](#4-dashboards)
5. [Widgets](#5-widgets)
6. [Conexões de Dados](#6-conexões-de-dados)
7. [Spaces](#7-spaces)
8. [Crews](#8-crews)
9. [Permissões](#9-permissões)
10. [IA e Pipeline](#10-ia-e-pipeline)
11. [Templates](#11-templates)
12. [Configurações](#12-configurações)
13. [Upload e Arquivos](#13-upload-e-arquivos)
14. [Connector Registry](#14-connector-registry)

---

## 1. Autenticação

### 1.1 Login

**Endpoint:** `POST /api/v1/auth/login`

**Request Body:**
```json
{
  "email": "test@example.com",
  "password": "test123"
}
```

**Resposta esperada:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid-do-usuario",
    "email": "test@example.com",
    "name": "Test User"
  }
}
```

**⚠️ IMPORTANTE:** Copie o `access_token` e use no botão "Authorize" do Swagger!

---

### 1.2 Obter Usuário Atual

**Endpoint:** `GET /api/v1/auth/me`

**Request Body:** Nenhum (usa token do header)

---

### 1.3 Refresh Token

**Endpoint:** `POST /api/v1/auth/refresh`

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

### 1.4 Logout

**Endpoint:** `POST /api/v1/auth/logout`

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

### 1.5 Esqueci a Senha

**Endpoint:** `POST /api/v1/auth/forgot-password`

**Request Body:**
```json
{
  "email": "test@example.com"
}
```

---

### 1.6 Resetar Senha

**Endpoint:** `POST /api/v1/auth/reset-password`

**Request Body:**
```json
{
  "token": "reset-token-here",
  "new_password": "newpassword123"
}
```

---

### 1.7 Verificar Email

**Endpoint:** `POST /api/v1/auth/verify-email`

**Request Body:**
```json
{
  "token": "verification-token-here"
}
```

---

### 1.8 Obter Sessão

**Endpoint:** `GET /api/v1/auth/session`

**Request Body:** Nenhum (usa token do header)

---

## 2. Usuários

### 2.1 Listar Todos os Usuários (Admin)

**Endpoint:** `GET /api/v1/users`

**Query Parameters:**
- `skip`: 0
- `limit`: 100

---

### 2.2 Criar Usuário (Admin)

**Endpoint:** `POST /api/v1/users`

**Request Body:**
```json
{
  "email": "novo@example.com",
  "password": "senha123",
  "name": "Novo Usuário",
  "role": "user",
  "avatar": "https://example.com/avatar.jpg"
}
```

**Roles válidos:** `admin`, `user`, `viewer`

---

### 2.3 Obter Usuário por ID

**Endpoint:** `GET /api/v1/users/{user_id}`

**Path Parameter:** `user_id` (UUID)

---

### 2.4 Atualizar Usuário

**Endpoint:** `PUT /api/v1/users/{user_id}`

**Request Body:**
```json
{
  "name": "Nome Atualizado",
  "avatar": "https://example.com/new-avatar.jpg",
  "role": "admin"
}
```

---

### 2.5 Deletar Usuário (Admin)

**Endpoint:** `DELETE /api/v1/users/{user_id}`

**Path Parameter:** `user_id` (UUID)

---

### 2.6 Obter Permissões do Usuário

**Endpoint:** `GET /api/v1/users/{user_id}/permissions`

**Path Parameter:** `user_id` (UUID)

---

### 2.7 Atualizar Permissões do Usuário (Admin)

**Endpoint:** `PUT /api/v1/users/{user_id}/permissions`

**Request Body:**
```json
{
  "role": "admin"
}
```

---

### 2.8 Convidar Usuário (Admin)

**Endpoint:** `POST /api/v1/users/{user_id}/invite`

**Path Parameter:** `user_id` (UUID)

---

## 3. Workspaces

### 3.1 Listar Workspaces do Usuário

**Endpoint:** `GET /api/v1/workspaces`

**Request Body:** Nenhum

---

### 3.2 Criar Workspace

**Endpoint:** `POST /api/v1/workspaces`

**Request Body:**
```json
{
  "name": "Meu Workspace",
  "description": "Workspace de teste",
  "type": "personal",
  "color": "#3B82F6",
  "icon": "workspace-icon"
}
```

**Types válidos:** `personal`, `team`  
**Color:** Formato hexadecimal `#RRGGBB`

---

### 3.3 Obter Workspace por ID

**Endpoint:** `GET /api/v1/workspaces/{workspace_id}`

**Path Parameter:** `workspace_id` (UUID)

---

### 3.4 Atualizar Workspace

**Endpoint:** `PUT /api/v1/workspaces/{workspace_id}`

**Request Body:**
```json
{
  "name": "Workspace Atualizado",
  "description": "Nova descrição",
  "color": "#10B981"
}
```

---

### 3.5 Deletar Workspace

**Endpoint:** `DELETE /api/v1/workspaces/{workspace_id}`

**Path Parameter:** `workspace_id` (UUID)

---

### 3.6 Listar Membros do Workspace

**Endpoint:** `GET /api/v1/workspaces/{workspace_id}/members`

**Path Parameter:** `workspace_id` (UUID)

---

### 3.7 Adicionar Membro ao Workspace

**Endpoint:** `POST /api/v1/workspaces/{workspace_id}/members`

**Request Body:**
```json
{
  "user_id": "uuid-do-usuario",
  "role": "member"
}
```

**Roles válidos:** `owner`, `admin`, `member`, `viewer`

---

### 3.8 Remover Membro do Workspace

**Endpoint:** `DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}`

**Path Parameters:**
- `workspace_id` (UUID)
- `user_id` (UUID)

---

### 3.9 Atualizar Role do Membro

**Endpoint:** `PUT /api/v1/workspaces/{workspace_id}/members/{user_id}/role`

**Request Body:**
```json
{
  "role": "admin"
}
```

---

### 3.10 Listar Dashboards do Workspace

**Endpoint:** `GET /api/v1/workspaces/{workspace_id}/dashboards`

**Query Parameters:**
- `skip`: 0
- `limit`: 100

---

### 3.11 Trocar Workspace Ativo

**Endpoint:** `POST /api/v1/workspaces/{workspace_id}/switch`

**Path Parameter:** `workspace_id` (UUID)

---

## 4. Dashboards

### 4.1 Listar Dashboards

**Endpoint:** `GET /api/v1/dashboards`

**Query Parameters:**
- `workspace_id`: (UUID opcional)
- `skip`: 0
- `limit`: 100

---

### 4.2 Criar Dashboard

**Endpoint:** `POST /api/v1/dashboards`

**Request Body:**
```json
{
  "name": "Meu Dashboard",
  "description": "Dashboard de teste",
  "workspace_id": "uuid-do-workspace",
  "template_id": null
}
```

---

### 4.3 Obter Dashboard por ID

**Endpoint:** `GET /api/v1/dashboards/{dashboard_id}`

**Path Parameter:** `dashboard_id` (UUID)

---

### 4.4 Atualizar Dashboard

**Endpoint:** `PUT /api/v1/dashboards/{dashboard_id}`

**Request Body:**
```json
{
  "name": "Dashboard Atualizado",
  "description": "Nova descrição"
}
```

---

### 4.5 Deletar Dashboard

**Endpoint:** `DELETE /api/v1/dashboards/{dashboard_id}`

**Path Parameter:** `dashboard_id` (UUID)

---

### 4.6 Listar Widgets do Dashboard

**Endpoint:** `GET /api/v1/dashboards/{dashboard_id}/widgets`

**Path Parameter:** `dashboard_id` (UUID)

---

### 4.7 Criar Widget no Dashboard

**Endpoint:** `POST /api/v1/dashboards/{dashboard_id}/widgets`

**Request Body:**
```json
{
  "type": "chart",
  "title": "Meu Widget",
  "position": {
    "x": 0,
    "y": 0
  },
  "size": {
    "width": 400,
    "height": 300
  },
  "data": {},
  "config": {},
  "connection_id": null,
  "query_id": null
}
```

---

## 5. Widgets

### 5.1 Obter Widget por ID

**Endpoint:** `GET /api/v1/widgets/{widget_id}`

**Path Parameter:** `widget_id` (UUID)

---

### 5.2 Atualizar Widget

**Endpoint:** `PUT /api/v1/widgets/{widget_id}`

**Request Body:**
```json
{
  "title": "Widget Atualizado",
  "position": {
    "x": 100,
    "y": 100
  },
  "size": {
    "width": 500,
    "height": 400
  },
  "config": {
    "chartType": "line"
  }
}
```

---

### 5.3 Deletar Widget

**Endpoint:** `DELETE /api/v1/widgets/{widget_id}`

**Path Parameter:** `widget_id` (UUID)

---

### 5.4 Duplicar Widget

**Endpoint:** `POST /api/v1/widgets/{widget_id}/duplicate`

**Path Parameter:** `widget_id` (UUID)

---

### 5.5 Exportar Dados do Widget

**Endpoint:** `POST /api/v1/widgets/{widget_id}/export`

**Path Parameter:** `widget_id` (UUID)

---

### 5.6 Obter Dados do Widget

**Endpoint:** `GET /api/v1/widgets/{widget_id}/data`

**Path Parameter:** `widget_id` (UUID)

---

### 5.7 Atualizar Dados do Widget

**Endpoint:** `POST /api/v1/widgets/{widget_id}/refresh`

**Path Parameter:** `widget_id` (UUID)

---

## 6. Conexões de Dados

### 6.1 Listar Conexões

**Endpoint:** `GET /api/v1/connections`

**Query Parameters:**
- `skip`: 0
- `limit`: 100

---

### 6.2 Criar Conexão

**Endpoint:** `POST /api/v1/connections`

**Request Body:**
```json
{
  "name": "PostgreSQL Local",
  "type": "postgresql",
  "config": {
    "host": "localhost",
    "port": 5432,
    "database": "mydb",
    "username": "postgres",
    "password": "password"
  },
  "workspace_id": "uuid-do-workspace"
}
```

---

### 6.3 Obter Conexão por ID

**Endpoint:** `GET /api/v1/connections/{connection_id}`

**Path Parameter:** `connection_id` (UUID)

---

### 6.4 Atualizar Conexão

**Endpoint:** `PUT /api/v1/connections/{connection_id}`

**Request Body:**
```json
{
  "name": "Conexão Atualizada",
  "config": {
    "host": "newhost.com",
    "port": 5432
  }
}
```

---

### 6.5 Deletar Conexão

**Endpoint:** `DELETE /api/v1/connections/{connection_id}`

**Path Parameter:** `connection_id` (UUID)

---

### 6.6 Testar Conexão

**Endpoint:** `POST /api/v1/connections/{connection_id}/test`

**Path Parameter:** `connection_id` (UUID)

---

### 6.7 Sincronizar Metadados

**Endpoint:** `POST /api/v1/connections/{connection_id}/sync`

**Path Parameter:** `connection_id` (UUID)

---

### 6.8 Obter Metadados

**Endpoint:** `GET /api/v1/connections/{connection_id}/metadata`

**Path Parameter:** `connection_id` (UUID)

---

### 6.9 Listar Tabelas

**Endpoint:** `GET /api/v1/connections/{connection_id}/tables`

**Path Parameter:** `connection_id` (UUID)

---

### 6.10 Obter Tabela por Nome

**Endpoint:** `GET /api/v1/connections/{connection_id}/tables/{table_name}`

**Path Parameters:**
- `connection_id` (UUID)
- `table_name` (string)

---

### 6.11 Executar Query

**Endpoint:** `POST /api/v1/connections/{connection_id}/query`

**Request Body:**
```json
{
  "query": "SELECT * FROM users LIMIT 10",
  "parameters": {}
}
```

---

## 7. Spaces

### 7.1 Listar Spaces

**Endpoint:** `GET /api/v1/spaces`

**Request Body:** Nenhum

---

### 7.2 Criar Space

**Endpoint:** `POST /api/v1/spaces`

**Request Body:**
```json
{
  "name": "Meu Space",
  "description": "Space de teste",
  "workspace_id": "uuid-do-workspace"
}
```

---

### 7.3 Obter Space por ID

**Endpoint:** `GET /api/v1/spaces/{space_id}`

**Path Parameter:** `space_id` (UUID)

---

### 7.4 Atualizar Space

**Endpoint:** `PUT /api/v1/spaces/{space_id}`

**Request Body:**
```json
{
  "name": "Space Atualizado",
  "description": "Nova descrição"
}
```

---

### 7.5 Deletar Space

**Endpoint:** `DELETE /api/v1/spaces/{space_id}`

**Path Parameter:** `space_id` (UUID)

---

### 7.6 Listar Crews do Space

**Endpoint:** `GET /api/v1/spaces/{space_id}/crews`

**Path Parameter:** `space_id` (UUID)

---

## 8. Crews

### 8.1 Listar Crews

**Endpoint:** `GET /api/v1/crews`

**Request Body:** Nenhum

---

### 8.2 Criar Crew

**Endpoint:** `POST /api/v1/crews`

**Request Body:**
```json
{
  "name": "Meu Crew",
  "description": "Crew de teste",
  "space_id": "uuid-do-space"
}
```

---

### 8.3 Obter Crew por ID

**Endpoint:** `GET /api/v1/crews/{crew_id}`

**Path Parameter:** `crew_id` (UUID)

---

### 8.4 Atualizar Crew

**Endpoint:** `PUT /api/v1/crews/{crew_id}`

**Request Body:**
```json
{
  "name": "Crew Atualizado",
  "description": "Nova descrição"
}
```

---

### 8.5 Deletar Crew

**Endpoint:** `DELETE /api/v1/crews/{crew_id}`

**Path Parameter:** `crew_id` (UUID)

---

### 8.6 Listar Membros do Crew

**Endpoint:** `GET /api/v1/crews/{crew_id}/members`

**Path Parameter:** `crew_id` (UUID)

---

### 8.7 Adicionar Membro ao Crew

**Endpoint:** `POST /api/v1/crews/{crew_id}/members`

**Request Body:**
```json
{
  "user_id": "uuid-do-usuario",
  "role": "navigator"
}
```

**Roles válidos:** `commander`, `navigator`, `explorer`, `guest`

---

### 8.8 Remover Membro do Crew

**Endpoint:** `DELETE /api/v1/crews/{crew_id}/members/{user_id}`

**Path Parameters:**
- `crew_id` (UUID)
- `user_id` (UUID)

---

### 8.9 Atualizar Role do Membro

**Endpoint:** `PUT /api/v1/crews/{crew_id}/members/{user_id}/role`

**Request Body:**
```json
{
  "role": "commander"
}
```

---

## 9. Permissões

### 9.1 Listar Permissões de Conexão

**Endpoint:** `GET /api/v1/permissions/connections/{connection_id}`

**Path Parameter:** `connection_id` (UUID)

---

### 9.2 Criar Permissão de Conexão

**Endpoint:** `POST /api/v1/permissions/connections/{connection_id}`

**Request Body:**
```json
{
  "space_id": "uuid-do-space",
  "crew_id": null,
  "access_level": "read-only",
  "table_access": ["users", "orders"]
}
```

**Access levels válidos:** `full`, `read-only`, `custom`

---

### 9.3 Atualizar Permissão de Conexão

**Endpoint:** `PUT /api/v1/permissions/connections/{connection_id}/{permission_id}`

**Request Body:**
```json
{
  "access_level": "full",
  "table_access": null
}
```

---

### 9.4 Deletar Permissão de Conexão

**Endpoint:** `DELETE /api/v1/permissions/connections/{connection_id}/{permission_id}`

**Path Parameters:**
- `connection_id` (UUID)
- `permission_id` (UUID)

---

### 9.5 Verificar Permissão

**Endpoint:** `GET /api/v1/permissions/check`

**Query Parameters:**
- `resource`: `connection`
- `resource_id`: `uuid-da-conexao`
- `action`: `read`

---

## 10. IA e Pipeline

### 10.1 Processar Query de IA

**Endpoint:** `POST /api/v1/ai/query`

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas em janeiro?",
  "widget_id": null,
  "knowledge": ["connection-id-1"],
  "configure_data": {
    "question": "Qual foi o total de vendas em janeiro?",
    "creativity": 50,
    "length": 50,
    "knowledge": ["connection-id-1"]
  }
}
```

---

### 10.2 Enviar Mensagem no Chat

**Endpoint:** `POST /api/v1/ai/chat`

**Request Body:**
```json
{
  "message": "Pode me mostrar mais detalhes?",
  "widget_id": "uuid-do-widget",
  "context": {}
}
```

---

### 10.3 Obter Histórico de IA

**Endpoint:** `GET /api/v1/ai/history`

**Query Parameters:**
- `filter`: `today`, `week`, `pinned` (opcional)
- `search`: `vendas` (opcional)
- `category`: `Finance` (opcional)
- `skip`: 0
- `limit`: 100

---

### 10.4 Obter Item do Histórico

**Endpoint:** `GET /api/v1/ai/history/{history_id}`

**Path Parameter:** `history_id` (UUID)

---

### 10.5 Deletar Item do Histórico

**Endpoint:** `DELETE /api/v1/ai/history/{history_id}`

**Path Parameter:** `history_id` (UUID)

---

### 10.6 Fixar Item do Histórico

**Endpoint:** `POST /api/v1/ai/history/{history_id}/pin`

**Path Parameter:** `history_id` (UUID)

---

### 10.7 Desfixar Item do Histórico

**Endpoint:** `POST /api/v1/ai/history/{history_id}/unpin`

**Path Parameter:** `history_id` (UUID)

---

### 10.8 Exportar Histórico

**Endpoint:** `GET /api/v1/ai/history/export`

**Request Body:** Nenhum (retorna CSV)

---

### 10.9 Executar Pipeline

**Endpoint:** `POST /api/v1/ai/pipeline/execute`

**Request Body:**
```json
{
  "question": "Analise os dados de vendas",
  "knowledge": ["connection-id-1"],
  "configure_data": {
    "question": "Analise os dados de vendas",
    "creativity": 50,
    "length": 50,
    "knowledge": ["connection-id-1"]
  }
}
```

---

### 10.10 Obter Status do Pipeline

**Endpoint:** `GET /api/v1/ai/pipeline/{pipeline_id}/status`

**Path Parameter:** `pipeline_id` (UUID)

---

### 10.11 Obter Logs do Pipeline

**Endpoint:** `GET /api/v1/ai/pipeline/{pipeline_id}/logs`

**Path Parameter:** `pipeline_id` (UUID)

---

### 10.12 Gerar SQL

**Endpoint:** `POST /api/v1/ai/generate-sql`

**Request Body:**
```json
{
  "question": "Total de vendas por mês",
  "knowledge": ["connection-id"],
  "sql_instructions": "Use apenas tabelas de vendas",
  "creativity": 50
}
```

---

### 10.13 Gerar Resposta

**Endpoint:** `POST /api/v1/ai/generate-answer`

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas?",
  "knowledge": ["connection-id"],
  "context": {}
}
```

---

### 10.14 Analisar Pergunta

**Endpoint:** `POST /api/v1/ai/analyze-question`

**Request Body:**
```json
{
  "question": "Qual foi o total de vendas em janeiro?",
  "knowledge": ["connection-id"]
}
```

---

## 11. Templates

### 11.1 Listar Templates

**Endpoint:** `GET /api/v1/templates`

**Query Parameters:**
- `category`: `Sales` (opcional)
- `search`: `dashboard` (opcional)
- `popular`: `true` (opcional)
- `skip`: 0
- `limit`: 100

---

### 11.2 Obter Template por ID

**Endpoint:** `GET /api/v1/templates/{template_id}`

**Path Parameter:** `template_id` (UUID)

---

### 11.3 Criar Template (Admin)

**Endpoint:** `POST /api/v1/templates`

**Request Body:**
```json
{
  "name": "Sales Dashboard Template",
  "creator": "Admin User",
  "category": "Sales",
  "description": "Template for sales analytics",
  "thumbnail": "https://example.com/thumbnail.jpg",
  "question": "Show me sales data",
  "widgets": [
    {
      "type": "chart",
      "title": "Sales Chart",
      "position": {"x": 0, "y": 0},
      "size": {"width": 400, "height": 300}
    }
  ],
  "icon": "chart-icon",
  "color": "#3B82F6",
  "popular": true,
  "enterprise": false
}
```

---

### 11.4 Atualizar Template (Admin)

**Endpoint:** `PUT /api/v1/templates/{template_id}`

**Request Body:**
```json
{
  "name": "Template Atualizado",
  "popular": true
}
```

---

### 11.5 Deletar Template (Admin)

**Endpoint:** `DELETE /api/v1/templates/{template_id}`

**Path Parameter:** `template_id` (UUID)

---

### 11.6 Obter Categorias de Templates

**Endpoint:** `GET /api/v1/templates/categories`

**Request Body:** Nenhum

---

### 11.7 Aplicar Template a Dashboard

**Endpoint:** `POST /api/v1/templates/{template_id}/apply`

**Request Body:**
```json
{
  "dashboard_id": "uuid-do-dashboard",
  "position": {
    "x": 0,
    "y": 0
  }
}
```

---

## 12. Configurações

### 12.1 Obter Configurações

**Endpoint:** `GET /api/v1/settings`

**Request Body:** Nenhum

---

### 12.2 Atualizar Configurações

**Endpoint:** `PUT /api/v1/settings`

**Request Body:**
```json
{
  "theme": "dark",
  "language": "pt-BR",
  "notifications": {
    "email": true,
    "push": false
  },
  "preferences": {
    "timezone": "America/Sao_Paulo"
  }
}
```

---

### 12.3 Obter Configurações do Catálogo de Dados

**Endpoint:** `GET /api/v1/settings/data-catalog`

**Request Body:** Nenhum

---

### 12.4 Obter Configurações de Spaces

**Endpoint:** `GET /api/v1/settings/spaces`

**Request Body:** Nenhum

---

### 12.5 Obter Configurações de Crews

**Endpoint:** `GET /api/v1/settings/crews`

**Request Body:** Nenhum

---

### 12.6 Obter Configurações de Usuários (Admin)

**Endpoint:** `GET /api/v1/settings/users`

**Request Body:** Nenhum

---

### 12.7 Obter Configurações de Permissões (Admin)

**Endpoint:** `GET /api/v1/settings/permissions`

**Request Body:** Nenhum

---

### 12.8 Listar API Keys

**Endpoint:** `GET /api/v1/settings/api-keys`

**Request Body:** Nenhum

---

### 12.9 Criar API Key

**Endpoint:** `POST /api/v1/settings/api-keys`

**Request Body:**
```json
{
  "name": "My API Key",
  "permissions": ["read", "write"],
  "expires_at": "2025-12-31T23:59:59Z"
}
```

**⚠️ IMPORTANTE:** A key completa só é mostrada uma vez na resposta!

---

### 12.10 Deletar API Key

**Endpoint:** `DELETE /api/v1/settings/api-keys/{api_key_id}`

**Path Parameter:** `api_key_id` (UUID)

---

### 12.11 Listar Integrações

**Endpoint:** `GET /api/v1/settings/integrations`

**Request Body:** Nenhum

---

### 12.12 Criar Integração

**Endpoint:** `POST /api/v1/settings/integrations`

**Request Body:**
```json
{
  "name": "Slack Integration",
  "type": "slack",
  "config": {
    "webhook_url": "https://hooks.slack.com/services/...",
    "channel": "#notifications"
  },
  "enabled": true
}
```

---

### 12.13 Atualizar Integração

**Endpoint:** `PUT /api/v1/settings/integrations/{integration_id}`

**Request Body:**
```json
{
  "name": "Slack Integration Updated",
  "config": {
    "webhook_url": "https://hooks.slack.com/services/new...",
    "channel": "#alerts"
  },
  "enabled": false
}
```

---

### 12.14 Deletar Integração

**Endpoint:** `DELETE /api/v1/settings/integrations/{integration_id}`

**Path Parameter:** `integration_id` (UUID)

---

## 13. Upload e Arquivos

### 13.1 Upload Genérico

**Endpoint:** `POST /api/v1/files/upload`

**Request:** `multipart/form-data`
- `file`: (arquivo)
- `widget_id`: (UUID opcional)

**Nota:** No Swagger, use o botão "Choose File" para selecionar o arquivo.

---

### 13.2 Upload CSV

**Endpoint:** `POST /api/v1/files/upload/csv`

**Request:** `multipart/form-data`
- `file`: (arquivo CSV)

**Resposta inclui:**
- `data`: Dados parseados
- `columns`: Nomes das colunas
- `preview`: Primeiras 10 linhas

---

### 13.3 Upload Excel

**Endpoint:** `POST /api/v1/files/upload/excel`

**Request:** `multipart/form-data`
- `file`: (arquivo Excel .xlsx ou .xls)

**Resposta inclui:**
- `data`: Dados por sheet
- `sheets`: Nomes das sheets
- `columns`: Colunas por sheet
- `preview`: Preview por sheet

---

### 13.4 Upload Imagem

**Endpoint:** `POST /api/v1/files/upload/image`

**Request:** `multipart/form-data`
- `file`: (imagem: JPEG, PNG, GIF, WebP)
- `widget_id`: (UUID opcional)

**Tipos aceitos:** `image/jpeg`, `image/png`, `image/gif`, `image/webp`

---

### 13.5 Upload PDF

**Endpoint:** `POST /api/v1/files/upload/pdf`

**Request:** `multipart/form-data`
- `file`: (arquivo PDF)
- `widget_id`: (UUID opcional)

---

### 13.6 Obter Arquivo

**Endpoint:** `GET /api/v1/files/{file_id}`

**Path Parameter:** `file_id` (UUID)

---

### 13.7 Deletar Arquivo

**Endpoint:** `DELETE /api/v1/files/{file_id}`

**Path Parameter:** `file_id` (UUID)

---

## 14. Connector Registry

### 14.1 Listar Connectors

**Endpoint:** `GET /api/v1/connectors`

**Request Body:** Nenhum

**Resposta inclui:**
- `id`: ID do connector
- `name`: Nome
- `category`: Categoria (database, document, api, file)
- `description`: Descrição
- `fields`: Campos de configuração
- `auth_methods`: Métodos de autenticação
- `config_schema`: Schema de configuração

---

### 14.2 Obter Connector por ID

**Endpoint:** `GET /api/v1/connectors/{connector_id}`

**Path Parameter:** `connector_id` (string)

**IDs disponíveis:**
- `postgresql`
- `mysql`
- `mongodb`
- `google-sheets`
- `rest-api`

---

### 14.3 Obter Categorias de Connectors

**Endpoint:** `GET /api/v1/connectors/categories`

**Request Body:** Nenhum

**Resposta:** Lista de categorias: `["api", "database", "document", "file"]`

---

## 🔧 Como Usar Este Guia

1. **Autentique-se primeiro:**
   - Faça login em `POST /api/v1/auth/login`
   - Copie o `access_token`
   - Clique em "Authorize" no Swagger e cole o token

2. **Para cada endpoint:**
   - Encontre o endpoint no Swagger UI
   - Clique em "Try it out"
   - Cole o JSON do exemplo no campo "Request body"
   - Substitua UUIDs de exemplo pelos UUIDs reais do seu sistema
   - Clique em "Execute"

3. **Substitua UUIDs:**
   - Os exemplos usam `"uuid-do-workspace"`, `"uuid-do-dashboard"`, etc.
   - Substitua pelos UUIDs reais obtidos nas respostas anteriores

4. **Para uploads:**
   - Use o botão "Choose File" no Swagger
   - Selecione o arquivo desejado
   - Preencha campos opcionais se necessário

---

## ⚠️ Notas Importantes

- **Autenticação:** A maioria dos endpoints requer autenticação. Use o botão "Authorize" no Swagger.
- **UUIDs:** Sempre substitua os UUIDs de exemplo pelos UUIDs reais.
- **Permissões:** Alguns endpoints requerem permissões de admin.
- **Validação:** Os exemplos seguem as validações do schema. Ajuste conforme necessário.
- **Rate Limits:** Alguns endpoints têm rate limits (ex: upload: 5/minuto).

---

## 🐛 Troubleshooting

### Botão "Authorize" não aparece
- Verifique se o servidor está rodando
- Recarregue a página do Swagger
- Verifique os logs do backend

### Erro 401 Unauthorized
- Verifique se o token foi copiado corretamente
- Verifique se o token não expirou (15 minutos)
- Faça login novamente e atualize o token

### Erro 404 Not Found
- Verifique se o UUID está correto
- Verifique se o recurso existe no banco de dados

### Erro 403 Forbidden
- Verifique se você tem permissão para acessar o recurso
- Alguns endpoints requerem role de admin

---

**Última atualização:** 2025-12-03  
**Total de endpoints:** 91
