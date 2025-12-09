# 🧪 Guia de Testes Completo

Este guia te ajuda a testar **TUDO** no projeto: Frontend conectado ao Backend.

## 🚀 Iniciar Tudo

### Método Rápido (Recomendado)

```bash
# No diretório raiz do projeto
./scripts/start-dev.sh
```

Isso vai iniciar:
- ✅ PostgreSQL (porta 5432)
- ✅ Redis (porta 6379)
- ✅ Backend API (porta 8000)
- ✅ Frontend (porta 3000)
- ✅ Criar usuário de teste

### Método Manual

Veja o arquivo `QUICK_START.md` para instruções detalhadas.

## 🧪 Testes Passo a Passo

### 1. Verificar Backend

Abra no navegador:
- **Health Check**: http://localhost:8000/health
- **API Docs (Swagger)**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

**Teste no terminal:**
```bash
curl http://localhost:8000/health
```

**Resultado esperado:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-01-15T..."
}
```

### 2. Testar Login no Frontend

1. Acesse: **http://localhost:3000/login**
2. Use as credenciais:
   - **Email**: `test@example.com`
   - **Password**: `test123`
3. Clique em "Sign in"

**O que deve acontecer:**
- ✅ Login bem-sucedido
- ✅ Redirecionamento para `/dashboard`
- ✅ Token salvo no localStorage
- ✅ Dados do usuário carregados

**Verificar no DevTools (F12):**
- Network tab: Deve ver `POST /api/v1/auth/login` com status 200
- Application > Local Storage: Deve ter `access_token`

### 3. Testar API de Autenticação Diretamente

#### Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "test123"
  }'
```

**Resultado esperado:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "...",
    "email": "test@example.com",
    "name": "Test User",
    "role": "user"
  }
}
```

#### Obter Dados do Usuário (Me)

```bash
# Substitua TOKEN pelo access_token retornado no login
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer TOKEN"
```

### 4. Testar Workspaces

#### Listar Workspaces

```bash
curl -X GET http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer TOKEN"
```

#### Criar Workspace

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Workspace",
    "description": "Test workspace",
    "type": "personal",
    "color": "#3b82f6"
  }'
```

### 5. Testar Dashboards

#### Listar Dashboards

```bash
curl -X GET "http://localhost:8000/api/v1/dashboards?workspace_id=WORKSPACE_ID" \
  -H "Authorization: Bearer TOKEN"
```

#### Criar Dashboard

```bash
curl -X POST http://localhost:8000/api/v1/dashboards \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Dashboard",
    "description": "Test dashboard",
    "workspace_id": "WORKSPACE_ID"
  }'
```

### 6. Testar Widgets

#### Listar Widgets de um Dashboard

```bash
curl -X GET http://localhost:8000/api/v1/dashboards/DASHBOARD_ID/widgets \
  -H "Authorization: Bearer TOKEN"
```

#### Criar Widget

```bash
curl -X POST http://localhost:8000/api/v1/dashboards/DASHBOARD_ID/widgets \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "kpi",
    "title": "Total Sales",
    "position": {"x": 100, "y": 100},
    "size": {"width": 300, "height": 150},
    "data": {"value": "1000", "change": "+10%"}
  }'
```

## 🎯 Testes no Frontend

### 1. Login Flow

1. Acesse `/login`
2. Preencha email e senha
3. Clique em "Sign in"
4. **Verificar**: Deve redirecionar para `/dashboard`

### 2. Dashboard

1. Após login, você deve ver o dashboard
2. **Verificar**: 
   - Sidebar visível
   - Toolbar visível
   - Canvas vazio (sem widgets ainda)

### 3. Criar Widget

1. Use a barra de busca de IA ou toolbar
2. Crie um widget
3. **Verificar**: Widget aparece no canvas

### 4. Workspaces

1. Clique no seletor de workspace
2. Crie um novo workspace
3. **Verificar**: Workspace aparece na lista

## 🐛 Troubleshooting

### Backend não responde

```bash
# Verificar se está rodando
curl http://localhost:8000/health

# Ver logs
tail -f backend.log
```

### Frontend não conecta

1. Verifique se backend está rodando
2. Verifique CORS no backend (deve incluir http://localhost:3000)
3. Verifique a URL da API no frontend:
   ```bash
   # Deve ser: http://localhost:8000/api/v1
   ```

### Erro de autenticação

1. Verifique se o token está sendo enviado:
   - DevTools > Network > Headers > Authorization
2. Verifique se o token não expirou (15 minutos)
3. Faça login novamente

### Erro de banco de dados

```bash
# Verificar se PostgreSQL está rodando
docker ps | grep postgres

# Verificar conexão
docker exec ai_saas_postgres psql -U postgres -d ai_saas_db -c "SELECT 1;"
```

## 📊 Checklist de Testes

- [ ] Backend health check funciona
- [ ] API docs acessível
- [ ] Login no frontend funciona
- [ ] Token é salvo no localStorage
- [ ] Redirecionamento após login funciona
- [ ] Dashboard carrega após login
- [ ] Criar workspace funciona
- [ ] Listar workspaces funciona
- [ ] Criar dashboard funciona
- [ ] Criar widget funciona
- [ ] Atualizar widget funciona
- [ ] Deletar widget funciona
- [ ] Refresh token funciona
- [ ] Logout funciona

## 🔗 Links Úteis

- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health**: http://localhost:8000/health

## 📝 Notas

- O usuário de teste é criado automaticamente: `test@example.com` / `test123`
- Tokens JWT expiram em 15 minutos
- Use o refresh token para renovar o access token
- Todos os endpoints (exceto login) requerem autenticação

