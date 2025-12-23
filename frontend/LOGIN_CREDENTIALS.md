# 🔐 Credenciais de Login

## 👤 Usuário de Teste

Use estas credenciais para fazer login no sistema:

```
Email: test@example.com
Password: Test@2024!Secure
```

**✅ Status:** Usuário criado e pronto para uso!

## 🌐 URLs de Acesso

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

## 📝 Como Fazer Login

1. Acesse: http://localhost:3000
2. Você será redirecionado para a página de login
3. Digite:
   - **Email:** `test@example.com`
   - **Password:** `Test@2024!Secure`
4. Clique em "Login" ou pressione Enter

## ✅ Verificação

Após o login, você deve:
- Ver o dashboard principal
- Ter acesso a todas as funcionalidades
- Poder criar workspaces, dashboards, etc.

**✅ Status do Sistema:**
- ✅ Backend rodando em http://localhost:8000
- ✅ PostgreSQL rodando na porta 5433 (servidor remoto: 44.197.200.153)
- ✅ Redis rodando na porta 6379
- ✅ Login funcionando corretamente
- ✅ Tokens JWT sendo gerados com sucesso
- ✅ Senha atualizada para versão mais segura

## 🔧 Criar Novo Usuário

Se precisar criar outro usuário de teste, execute:

```bash
cd deploy
docker-compose exec backend python scripts/create-test-user.py
```

Ou crie manualmente via API:

```bash
curl -X POST http://localhost:8001/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "novo@example.com",
    "password": "senha123",
    "name": "Novo Usuário"
  }'
```

## 🐛 Troubleshooting

### Erro: "Invalid credentials"
- Verifique se o usuário foi criado: `docker-compose exec postgres psql -U postgres -d ai_saas_db -c "SELECT email FROM users;"`
- Recrie o usuário: `docker-compose exec backend python scripts/create-test-user.py`

### Erro: "User not found"
- O usuário não existe no banco
- Execute o script de criação de usuário

### Erro de conexão com backend
- Verifique se o backend está rodando: `docker-compose ps backend`
- Verifique os logs: `docker-compose logs backend`

