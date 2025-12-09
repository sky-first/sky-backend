# Próximos Passos - Módulo de Workspaces

## ✅ O que já está implementado

1. **API Wrapper completo** (`lib/api/workspaces.ts`)
   - Todos os endpoints conectados
   - Tipos TypeScript definidos

2. **Store atualizado** (`store/workspace-store.ts`)
   - Integração com API
   - Conversão automática de cores (hex ↔ nome)
   - Estados de loading e error

3. **Componentes conectados**
   - WorkspacesSidebar
   - WorkspacesDialog
   - DashboardLayout (carrega workspaces automaticamente)

4. **Utilitários de cores** (`lib/utils/workspace-colors.ts`)
   - Conversão entre nomes de cores e hex
   - Mapeamento de cores padrão

---

## 🔧 Passos para tornar funcional

### 1. Rebuild do Frontend (OBRIGATÓRIO)

Como você está usando Docker, precisa rebuildar o frontend:

```bash
cd deploy
docker-compose build frontend
docker-compose up -d --force-recreate frontend
```

### 2. Verificar Backend está rodando

```bash
# Verificar se backend está acessível
curl http://localhost:8000/health

# Verificar se endpoint de workspaces existe
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/v1/workspaces
```

### 3. Testar no Navegador

1. **Fazer login**
   - Acesse `http://localhost:3000/login`
   - Faça login com credenciais válidas

2. **Verificar carregamento de workspaces**
   - Após login, o dashboard deve carregar workspaces automaticamente
   - Abra o console do navegador (F12) e verifique se há erros

3. **Testar sidebar de workspaces**
   - Clique no menu de workspaces (se houver)
   - Deve mostrar workspaces reais da API

4. **Testar troca de workspace**
   - Clique em um workspace diferente
   - Deve chamar o endpoint `/workspaces/{id}/switch`

---

## 🐛 Possíveis Problemas e Soluções

### Problema 1: Workspaces não carregam

**Sintomas:**
- Lista vazia ou erro no console
- Erro 401 (não autenticado)

**Soluções:**
1. Verificar se está autenticado:
   ```javascript
   // No console do navegador
   localStorage.getItem('access_token')
   ```

2. Verificar se o token é válido:
   - Faça logout e login novamente
   - Verifique se o refresh token está funcionando

3. Verificar logs do backend:
   ```bash
   docker logs ai_saas_backend_prod -f
   ```

### Problema 2: Erro de CORS

**Sintomas:**
- Erro no console: "CORS policy"
- Requisições bloqueadas

**Solução:**
- Verificar `CORS_ORIGINS` no backend
- Deve incluir `http://localhost:3000`

### Problema 3: Cores não aparecem corretamente

**Sintomas:**
- Workspaces aparecem sem cor ou com cor errada

**Solução:**
- O sistema já converte automaticamente entre hex e nomes
- Se o backend retornar uma cor hex que não está no mapeamento, será usado "blue" como padrão

### Problema 4: Erro ao trocar workspace

**Sintomas:**
- Erro ao clicar em workspace
- Workspace não muda

**Soluções:**
1. Verificar se o endpoint `/workspaces/{id}/switch` existe no backend
2. Verificar permissões (usuário deve ser membro do workspace)
3. Verificar logs do backend para erro específico

---

## 📋 Checklist de Funcionalidades

### Funcionalidades Básicas (Já implementadas)
- [x] Listar workspaces
- [x] Carregar workspaces ao autenticar
- [x] Trocar workspace ativo
- [x] Filtrar por tipo (personal/team)
- [x] Buscar workspaces

### Funcionalidades Pendentes (Precisam de UI)
- [ ] Criar workspace (precisa de formulário)
- [ ] Editar workspace (precisa de formulário)
- [ ] Deletar workspace (precisa de confirmação)
- [ ] Adicionar membro (precisa de UI)
- [ ] Remover membro (precisa de UI)
- [ ] Alterar role de membro (precisa de UI)
- [ ] Ver membros do workspace (precisa de UI)

---

## 🎯 Próximas Implementações Recomendadas

### 1. Criar Workspace (Prioridade Alta)

**O que precisa:**
- Formulário de criação
- Campos: nome, descrição, tipo, cor
- Validação de campos
- Feedback visual (loading, success, error)

**Onde implementar:**
- Adicionar botão "Criar Workspace" no WorkspacesDialog
- Criar componente `CreateWorkspaceDialog`

### 2. Editar Workspace (Prioridade Média)

**O que precisa:**
- Formulário de edição (similar ao de criação)
- Botão de editar em cada workspace card
- Validação de permissões (apenas owner/admin pode editar)

### 3. Gerenciar Membros (Prioridade Média)

**O que precisa:**
- Lista de membros do workspace
- Adicionar membro (buscar por email)
- Remover membro
- Alterar role (admin, member, viewer)

---

## 🔍 Como Debugar

### 1. Verificar Requisições HTTP

Abra o DevTools (F12) → Network tab:
- Verifique se as requisições estão sendo feitas
- Verifique status code (200, 401, 404, etc.)
- Verifique o payload das requisições

### 2. Verificar Estado do Store

No console do navegador:
```javascript
// Ver workspaces no store
import { useWorkspaceStore } from '@/store/workspace-store'
const store = useWorkspaceStore.getState()
console.log('Workspaces:', store.workspaces)
console.log('Current:', store.currentWorkspace)
console.log('Loading:', store.isLoading)
console.log('Error:', store.error)
```

### 3. Verificar Logs do Backend

```bash
# Ver logs em tempo real
docker logs -f ai_saas_backend_prod

# Ver últimas 50 linhas
docker logs --tail 50 ai_saas_backend_prod
```

### 4. Testar Endpoints Manualmente

```bash
# 1. Obter token (fazer login primeiro)
TOKEN="seu_token_aqui"

# 2. Listar workspaces
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workspaces

# 3. Obter workspace específico
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workspaces/{workspace_id}

# 4. Trocar workspace
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/workspaces/{workspace_id}/switch
```

---

## ✅ Teste Completo

Execute este teste passo a passo:

1. **Rebuild frontend**
   ```bash
   cd deploy && docker-compose build frontend && docker-compose up -d --force-recreate frontend
   ```

2. **Acessar aplicação**
   - Abrir `http://localhost:3000`
   - Fazer login

3. **Verificar carregamento**
   - Abrir DevTools → Console
   - Verificar se não há erros
   - Verificar se workspaces foram carregados

4. **Testar sidebar**
   - Abrir sidebar de workspaces
   - Verificar se lista aparece
   - Clicar em um workspace diferente

5. **Verificar troca**
   - Verificar se workspace ativo mudou
   - Verificar se UI atualizou

---

## 📝 Notas Importantes

1. **Cores**: O sistema converte automaticamente entre nomes (frontend) e hex (backend)
2. **Permissões**: Algumas operações requerem permissões específicas (owner/admin)
3. **Cache**: Workspaces são persistidos no localStorage, mas são recarregados da API
4. **Erros**: Todos os erros são logados no console e no estado do store

---

## 🚀 Quando estiver funcionando

Após confirmar que tudo está funcionando:
1. Teste criar um workspace manualmente via API
2. Teste trocar entre workspaces
3. Verifique se o workspace ativo persiste após reload
4. Se tudo OK, podemos seguir para o **Módulo 3: Dashboards**

