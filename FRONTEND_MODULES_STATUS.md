# Status de Implementação dos Módulos Frontend

## 📊 Resumo Geral

Este documento lista todos os módulos do backend e seu status de implementação no frontend.

---

## ✅ Módulos Implementados e Conectados

### 1. **Autenticação (Auth)** ✅
- **Backend:** `/api/v1/auth/*`
- **Frontend:** `src/lib/api/auth.ts`
- **Store:** `src/store/user-store.ts`
- **Status:** ✅ Completo
- **Endpoints conectados:**
  - ✅ `POST /auth/login`
  - ✅ `POST /auth/logout`
  - ✅ `POST /auth/refresh`
  - ✅ `GET /auth/me`
  - ✅ `GET /auth/session`
  - ✅ `POST /auth/forgot-password`
  - ✅ `POST /auth/reset-password`
  - ✅ `POST /auth/verify-email`

### 2. **Planets (Workspaces)** ✅
- **Backend:** `/api/v1/planets/*`
- **Frontend:** `src/lib/api/planets.ts`
- **Store:** `src/store/planet-store.ts`
- **Status:** ✅ Completo
- **Endpoints conectados:**
  - ✅ `GET /planets` (list)
  - ✅ `GET /planets/{id}`
  - ✅ `POST /planets` (create)
  - ✅ `PUT /planets/{id}` (update)
  - ✅ `DELETE /planets/{id}`
  - ✅ `GET /planets/{id}/members`
  - ✅ `POST /planets/{id}/members`
  - ✅ `DELETE /planets/{id}/members/{user_id}`
  - ✅ `PUT /planets/{id}/members/{user_id}/role`
  - ✅ `GET /planets/{id}/dashboards`
  - ✅ `POST /planets/{id}/switch`

### 3. **Dashboards** ✅
- **Backend:** `/api/v1/dashboards/*`
- **Frontend:** ✅ `src/lib/api/dashboards.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/dashboard-store.ts` - **CONECTADO AO BACKEND**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /dashboards` (list, com filtro por planet_id)
  - ✅ `GET /dashboards/{dashboard_id}`
  - ✅ `POST /dashboards` (create)
  - ✅ `PUT /dashboards/{dashboard_id}` (update)
  - ✅ `DELETE /dashboards/{dashboard_id}`
  - ✅ `GET /dashboards/{dashboard_id}/widgets`
  - ✅ `POST /dashboards/{dashboard_id}/widgets` (create widget)
  - ✅ `GET /dashboards/{dashboard_id}/export` - Exportar dashboard com widgets e connections
  - ✅ `POST /dashboards/{dashboard_id}/duplicate` - Duplicar dashboard com todos os widgets
  - ✅ `POST /dashboards/{dashboard_id}/lock` - Bloquear dashboard
  - ✅ `POST /dashboards/{dashboard_id}/unlock` - Desbloquear dashboard
- **Funcionalidades:**
  - ✅ Listagem de dashboards com filtro por planet_id
  - ✅ Criação de dashboards
  - ✅ Atualização de dashboards (incluindo lock/unlock via campo is_locked)
  - ✅ Deleção de dashboards
  - ✅ Obtenção de widgets de um dashboard
  - ✅ Criação de widgets em dashboards
  - ✅ Integração completa com componentes (dashboard/page.tsx)
  - ✅ Persistência de dashboard atual no store
  - ✅ Criação automática de dashboard padrão se não existir
  - ✅ Exportação de dashboards (com widgets e connections)
  - ✅ Duplicação de dashboards (com todos os widgets)
  - ✅ Lock/Unlock de dashboards

**Prioridade:** 🔴 **ALTA** - Core da aplicação

---

### 4. **Widgets** ✅
- **Backend:** `/api/v1/widgets/*`
- **Frontend:** ✅ `src/lib/api/widgets.ts` - **IMPLEMENTADO**
- **Store:** `src/store/widget-store.ts` - **CONECTADO AO BACKEND**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `PUT /widgets/{widget_id}` (update) - com debounce de 500ms
  - ✅ `DELETE /widgets/{widget_id}`
  - ✅ `POST /widgets/{widget_id}/duplicate`
  - ✅ `GET /widgets/{widget_id}/export`
  - ✅ `GET /widgets/{widget_id}/data`
  - ✅ `POST /widgets/{widget_id}/refresh`
- **Funcionalidades:**
  - ✅ Criação de widgets via `dashboardsApi.createWidget()` (endpoint `/dashboards/{id}/widgets`)
  - ✅ Atualização com debounce para evitar muitas chamadas durante drag/resize
  - ✅ Remoção de widgets
  - ✅ Duplicação de widgets
  - ✅ Refresh de dados de widgets
  - ✅ Export de widgets
  - ✅ Integração completa com componentes (canvas, toolbar, ai-search-bar, templates-dialog, text-toolbar-floating)

**Prioridade:** 🔴 **ALTA** - Core da aplicação

---

### 5. **Connections (Data Connections)** ✅
- **Backend:** `/api/v1/connections/*`
- **Frontend:** ✅ `src/lib/api/connections.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/connection-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /connections` (list) - com filtros opcionais (status, connector_id, paginação)
  - ✅ `GET /connections/{connection_id}`
  - ✅ `POST /connections` (create)
  - ✅ `PUT /connections/{connection_id}` (update)
  - ✅ `DELETE /connections/{connection_id}`
  - ✅ `POST /connections/{connection_id}/test`
  - ✅ `POST /connections/{connection_id}/sync`
  - ✅ `GET /connections/{connection_id}/metadata`
  - ✅ `GET /connections/{connection_id}/tables`
  - ✅ `GET /connections/{connection_id}/schemas`
  - ✅ `GET /connections/{connection_id}/status`
  - ✅ `POST /connections/{connection_id}/validate`
- **Funcionalidades:**
  - ✅ Listagem de conexões com filtros
  - ✅ Criação, atualização e remoção de conexões
  - ✅ Teste de conexão
  - ✅ Sincronização de metadados
  - ✅ Obtenção de metadados, tabelas e schemas
  - ✅ Verificação de status
  - ✅ Validação de configuração
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Persistência de conexão atual

**Prioridade:** 🟡 **MÉDIA** - Necessário para widgets funcionarem com dados reais

---

### 6. **Templates** ✅
- **Backend:** `/api/v1/templates/*`
- **Frontend:** ✅ `src/lib/api/templates.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/templates-store.ts` - **CONECTADO AO BACKEND**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /templates` (list) - com filtros opcionais (category, search, popular, paginação)
  - ✅ `GET /templates/{template_id}`
  - ✅ `POST /templates` (create) - Admin only
  - ✅ `PUT /templates/{template_id}` (update) - Admin only
  - ✅ `DELETE /templates/{template_id}` - Admin only
  - ✅ `GET /templates/categories`
  - ✅ `POST /templates/{template_id}/apply` - Aplicar template a um dashboard
- **Funcionalidades:**
  - ✅ Listagem de templates com filtros (categoria, busca, popular)
  - ✅ Obtenção de categorias do backend
  - ✅ Criação, atualização e remoção de templates (Admin)
  - ✅ Aplicação de templates a dashboards
  - ✅ Integração com `templates-dialog.tsx` - carrega templates do backend
  - ✅ Fallback para templates hardcoded (temporário)
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Persistência de UI state (categoria selecionada, busca)

**Prioridade:** 🟡 **MÉDIA** - Melhora UX mas não é crítico

---

### 7. **AI** ✅
- **Backend:** `/api/v1/ai/*`
- **Frontend:** ✅ `src/lib/api/ai.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/ai-history-store.ts` e `src/store/pipeline-store.ts` - **CONECTADOS AO BACKEND**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `POST /ai/query` (process AI query)
  - ✅ `POST /ai/chat` (send chat message)
  - ✅ `POST /ai/generate-sql` (generate SQL from question)
  - ✅ `POST /ai/generate-answer` (generate answer)
  - ✅ `POST /ai/analyze-question` (analyze question)
  - ✅ `GET /ai/history` (get AI history with filters)
  - ✅ `GET /ai/history/{history_id}` (get history item by ID)
  - ✅ `DELETE /ai/history/{history_id}` (delete history item)
  - ✅ `POST /ai/history/{history_id}/pin` (pin history item)
  - ✅ `POST /ai/history/{history_id}/unpin` (unpin history item)
  - ✅ `GET /ai/history/export` (export history as CSV)
  - ✅ `POST /ai/pipeline/execute` (execute pipeline)
  - ✅ `GET /ai/pipeline/{pipeline_id}/status` (get pipeline status)
  - ✅ `GET /ai/pipeline/{pipeline_id}/logs` (get pipeline logs)
- **Funcionalidades:**
  - ✅ Processamento de queries AI
  - ✅ Chat em widgets
  - ✅ Geração de SQL a partir de linguagem natural
  - ✅ Geração de respostas
  - ✅ Análise de perguntas
  - ✅ Histórico de interações AI (com filtros, busca, categorias)
  - ✅ Pin/Unpin de itens do histórico
  - ✅ Exportação de histórico como CSV
  - ✅ Execução e monitoramento de pipelines AI
  - ✅ Integração completa com componentes (ai-search-bar, pipeline-overlay, ai-history)
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Conversão automática de dados da API para formato do store

**Prioridade:** 🟡 **MÉDIA** - Feature diferenciada mas não crítica

---

### 8. **Spaces** ✅
- **Backend:** `/api/v1/spaces/*`
- **Frontend:** ✅ `src/lib/api/spaces.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/space-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /spaces` (list, com paginação)
  - ✅ `GET /spaces/{space_id}`
  - ✅ `POST /spaces` (create)
  - ✅ `PUT /spaces/{space_id}` (update)
  - ✅ `DELETE /spaces/{space_id}`
  - ✅ `GET /spaces/{space_id}/crews`
  - ✅ `GET /spaces/{space_id}/connections`
  - ✅ `GET /spaces/{space_id}/members` (get space members)
  - ✅ `POST /spaces/{space_id}/members` (add member)
  - ✅ `DELETE /spaces/{space_id}/members/{user_id}` (remove member)
- **Funcionalidades:**
  - ✅ Listagem de spaces com paginação
  - ✅ Criação de spaces
  - ✅ Atualização de spaces
  - ✅ Deleção de spaces
  - ✅ Obtenção de crews de um space
  - ✅ Obtenção de connections de um space
  - ✅ Adição de membros a um space
  - ✅ Remoção de membros de um space
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Persistência de space atual no store
  - ✅ Cache de crews, connections e members por space

**Prioridade:** 🟢 **BAIXA** - Feature secundária

---

### 9. **Crews** ✅
- **Backend:** `/api/v1/crews/*`
- **Frontend:** ✅ `src/lib/api/crews.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/crew-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /crews` (list, com filtro opcional por space_id e paginação)
  - ✅ `GET /crews/{crew_id}`
  - ✅ `POST /crews` (create)
  - ✅ `PUT /crews/{crew_id}` (update)
  - ✅ `DELETE /crews/{crew_id}`
  - ✅ `GET /crews/{crew_id}/members` (get crew members)
  - ✅ `POST /crews/{crew_id}/members` (add member)
  - ✅ `DELETE /crews/{crew_id}/members/{user_id}` (remove member)
  - ✅ `PUT /crews/{crew_id}/members/{user_id}/role` (update member role)
- **Funcionalidades:**
  - ✅ Listagem de crews com filtro por space_id e paginação
  - ✅ Criação de crews
  - ✅ Atualização de crews
  - ✅ Deleção de crews
  - ✅ Obtenção de membros de um crew
  - ✅ Adição de membros a um crew (com role: commander, navigator, explorer, guest)
  - ✅ Remoção de membros de um crew
  - ✅ Atualização de role de membros
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Persistência de crew atual no store
  - ✅ Cache de members por crew

**Prioridade:** 🟢 **BAIXA** - Feature secundária

---

### 10. **Users Management** ✅
- **Backend:** `/api/v1/users/*`
- **Frontend:** ✅ `src/lib/api/users.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/users-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /users` (list users, admin only, com paginação)
  - ✅ `GET /users/{user_id}`
  - ✅ `POST /users` (create user, admin only)
  - ✅ `PUT /users/{user_id}` (update)
  - ✅ `DELETE /users/{user_id}` (admin only, soft delete)
  - ✅ `GET /users/{user_id}/permissions` (get user permissions)
  - ✅ `PUT /users/{user_id}/permissions` (update permissions by role, admin only)
  - ✅ `POST /users/{user_id}/invite` (send invitation email, admin only)
- **Funcionalidades:**
  - ✅ Listagem de users com paginação (admin only)
  - ✅ Criação de users (admin only)
  - ✅ Atualização de users
  - ✅ Deleção de users (admin only, soft delete)
  - ✅ Obtenção de permissões de um user
  - ✅ Atualização de permissões através da mudança de role (admin only)
  - ✅ Envio de convite por email (admin only)
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Cache de permissões por user
  - ✅ Sincronização automática de role quando permissões são atualizadas

**Prioridade:** 🟡 **MÉDIA** - Necessário para gestão de usuários

---

### 11. **Permissions** ✅
- **Backend:** `/api/v1/permissions/*`
- **Frontend:** ✅ `src/lib/api/permissions.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/permissions-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /permissions/connections/{connection_id}` (get connection permissions)
  - ✅ `POST /permissions/connections/{connection_id}` (create connection permission)
  - ✅ `PUT /permissions/{permission_id}` (update permission)
  - ✅ `DELETE /permissions/{permission_id}` (delete permission)
  - ✅ `GET /permissions/spaces/{space_id}` (get space permissions)
  - ✅ `GET /permissions/crews/{crew_id}` (get crew permissions)
  - ✅ `POST /permissions/validate` (validate user permission)
- **Funcionalidades:**
  - ✅ Listagem de permissões por connection
  - ✅ Criação de permissões para connections (com space_id e/ou crew_id opcionais)
  - ✅ Atualização de permissões (access_level e table_access)
  - ✅ Deleção de permissões
  - ✅ Listagem de permissões por space
  - ✅ Listagem de permissões por crew
  - ✅ Validação de permissões de usuário para acessar connections
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Cache de permissões por connection, space e crew
  - ✅ Sincronização automática entre caches quando permissões são criadas/atualizadas/deletadas
  - ✅ Suporte para três níveis de acesso: full, read-only, custom (com table_access)

**Prioridade:** 🟡 **MÉDIA** - Necessário para controle de acesso

---

### 12. **Settings** ✅
- **Backend:** `/api/v1/settings/*`
- **Frontend:** ✅ `src/lib/api/settings.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/settings-store.ts` - **ATUALIZADO E CONECTADO AO BACKEND**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /settings` (get user settings)
  - ✅ `PUT /settings` (update user settings)
  - ✅ `GET /settings/data-catalog` (get data catalog settings)
  - ✅ `GET /settings/spaces` (get spaces settings)
  - ✅ `GET /settings/crews` (get crews settings)
  - ✅ `GET /settings/users` (get users settings, admin only)
  - ✅ `GET /settings/permissions` (get permissions settings, admin only)
  - ✅ `GET /settings/api-keys` (get user API keys)
  - ✅ `POST /settings/api-keys` (create API key, key shown only once)
  - ✅ `DELETE /settings/api-keys/{api_key_id}` (delete API key)
  - ✅ `GET /settings/integrations` (get user integrations)
  - ✅ `POST /settings/integrations` (create integration)
  - ✅ `PUT /settings/integrations/{integration_id}` (update integration)
  - ✅ `DELETE /settings/integrations/{integration_id}` (delete integration)
- **Funcionalidades:**
  - ✅ Obtenção e atualização de settings do usuário (theme, language, notifications, preferences)
  - ✅ Obtenção de configurações de data catalog (auto_sync, sync_interval, enabled_connectors)
  - ✅ Obtenção de configurações de spaces (default_role, allow_public_spaces, max_spaces_per_user)
  - ✅ Obtenção de configurações de crews (default_role, max_crews_per_user, allow_public_crews)
  - ✅ Obtenção de configurações de users (admin only: allow_registration, require_email_verification, default_role)
  - ✅ Obtenção de configurações de permissions (admin only: rbac_enabled, default_permissions)
  - ✅ Gerenciamento completo de API keys (list, create, delete)
  - ✅ Gerenciamento completo de integrations (list, create, update, delete)
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Persistência de UI state e user settings
  - ✅ Cache de configurações por categoria
  - ✅ Mantém funcionalidade de UI (abrir/fechar dialog, categoria selecionada, busca)

**Prioridade:** 🟡 **MÉDIA** - Melhora UX

---

### 13. **Files** ✅
- **Backend:** `/api/v1/files/*`
- **Frontend:** ✅ `src/lib/api/files.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/files-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `POST /files/upload` (upload generic file, com widget_id opcional)
  - ✅ `POST /files/upload/csv` (upload e parse CSV)
  - ✅ `POST /files/upload/excel` (upload e parse Excel)
  - ✅ `POST /files/upload/image` (upload image, com widget_id opcional)
  - ✅ `POST /files/upload/pdf` (upload PDF, com widget_id opcional)
  - ✅ `GET /files/{file_id}` (get file information)
  - ✅ `DELETE /files/{file_id}` (delete file)
- **Funcionalidades:**
  - ✅ Upload de arquivos genéricos com progress tracking
  - ✅ Upload e parsing de CSV (retorna data, columns, preview)
  - ✅ Upload e parsing de Excel (retorna data por sheet, columns, preview)
  - ✅ Upload de imagens com widget_id opcional
  - ✅ Upload de PDFs com widget_id opcional
  - ✅ Obtenção de informações de arquivo
  - ✅ Deleção de arquivos
  - ✅ Obtenção de URL de download (via file.url)
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Tracking de progresso de upload por arquivo
  - ✅ Cache de arquivos carregados
  - ✅ Suporte para FormData e XMLHttpRequest para uploads com progress

**Prioridade:** 🟡 **MÉDIA** - Necessário para upload de arquivos

---

### 14. **Connectors** ✅
- **Backend:** `/api/v1/connectors/*`
- **Frontend:** ✅ `src/lib/api/connectors.ts` - **IMPLEMENTADO**
- **Store:** ✅ `src/store/connectors-store.ts` - **IMPLEMENTADO**
- **Status:** ✅ **IMPLEMENTADO E CONECTADO**
- **Endpoints implementados:**
  - ✅ `GET /connectors` (list available connectors)
  - ✅ `GET /connectors/{connector_id}` (get connector details)
  - ✅ `GET /connectors/categories` (get connector categories)
- **Funcionalidades:**
  - ✅ Listagem de todos os connectors disponíveis
  - ✅ Obtenção de detalhes de um connector específico
  - ✅ Obtenção de categorias de connectors
  - ✅ Gerenciamento de estado com Zustand
  - ✅ Cache de connectors por ID para acesso rápido
  - ✅ Helpers para buscar connector por ID e filtrar por categoria
  - ✅ Suporte para campos de configuração (ConnectorField)
  - ✅ Suporte para métodos de autenticação (AuthMethod)
  - ✅ Suporte para schemas de configuração e metadados

**Prioridade:** 🟡 **MÉDIA** - Necessário para criar connections

---

## 📋 Plano de Implementação Sugerido

### Fase 1: Core da Aplicação (Prioridade ALTA) 🔴
1. **Dashboards** - Base para tudo funcionar
2. **Widgets** - Componentes visuais dos dashboards

### Fase 2: Funcionalidades Essenciais (Prioridade MÉDIA) 🟡
3. **Connections** - Para widgets terem dados reais
4. **Connectors** - Para criar connections
5. **Templates** - Melhora UX na criação de dashboards
6. **Users Management** - Gestão de usuários
7. **Permissions** - Controle de acesso
8. **Settings** - Configurações do usuário
9. **Files** - Upload de arquivos

### Fase 3: Features Avançadas (Prioridade BAIXA) 🟢
10. **AI** - Features de IA
11. **Spaces** - Organização secundária
12. **Crews** - Colaboração avançada

---

## 📝 Notas Importantes

1. **Stores Existentes mas Não Conectados:**
   - `widget-store.ts` - Usa dados mock, precisa conectar ao backend
   - `templates-store.ts` - Apenas UI state, precisa conectar ao backend
   - `ai-history-store.ts` - Não conecta ao backend
   - `pipeline-store.ts` - Não conecta ao backend
   - `settings-store.ts` - Não conecta ao backend

2. **Arquivos Antigos Removidos:**
   - ✅ `src/lib/api/workspaces.ts` (removido - substituído por `planets.ts`)
   - ✅ `src/store/workspace-store.ts` (removido - substituído por `planet-store.ts`)
   - ✅ `src/lib/utils/workspace-colors.ts` (removido - substituído por `planet-colors.ts`)

3. **Componentes que Precisam de Integração:**
   - Componentes de dashboard precisam usar API de dashboards
   - Componentes de widgets precisam usar API de widgets
   - Componentes de templates precisam usar API de templates

---

## 🎯 Próximos Passos Recomendados

1. ✅ **Implementar Dashboards API e Store** - **CONCLUÍDO**
2. ✅ **Implementar Widgets API e conectar ao store existente** - **CONCLUÍDO**
3. ✅ **Implementar Connections API e Store** - **CONCLUÍDO**
4. ✅ **Implementar Templates API e conectar ao store existente** - **CONCLUÍDO**
5. **Implementar Settings API e conectar ao store existente**
6. **Implementar Connectors API**
7. **Implementar Users API e Store**
8. **Implementar Permissions API e Store**
9. **Implementar Files API e Store**
10. **Implementar AI API e conectar aos stores existentes**
11. **Implementar Spaces API e Store**
12. **Implementar Crews API e Store**

