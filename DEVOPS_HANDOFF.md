# 📋 Resolução do Erro 403 - Documentação para DevOps

**Data**: 2026-01-26  
**Status**: ✅ Pull Request Criado  
**Branch**: `fix/role-permissions-seed`  
**PR URL**: https://github.com/sky-first/sky-poc-backend/pull/new/fix/role-permissions-seed

---

## 🎯 Resumo Executivo

O erro 403 Forbidden foi causado pela **tabela `role_permissions` vazia** em produção. A solução foi implementada através de:

1. ✅ Script de seed criado (`scripts/seed_role_permissions.py`)
2. ✅ Integração automática no startup (`scripts/start.sh`)
3. ✅ Documentação completa para DevOps (`scripts/SEEDING.md`)
4. ✅ Testes passando (318 passed)
5. ✅ Coverage: **74%** (acima do requisito de 71%)
6. ✅ Lint: Todos os checks passaram

---

## 📦 Arquivos Modificados/Criados

```
sky-poc-backend/
├── scripts/
│   ├── seed_role_permissions.py     # 🆕 Script de seed (idempotente)
│   ├── SEEDING.md                   # 🆕 Documentação DevOps completa
│   └── start.sh                     # ✏️  Atualizado (seed automático)
└── RESOLUTION_403.md                # 🆕 Sumário executivo
```

---

## 🚀 Ações Imediatas Necessárias

### 1️⃣ Aprovar e Fazer Merge do PR

```bash
# Revisar o PR em:
https://github.com/sky-first/sky-poc-backend/pull/new/fix/role-permissions-seed

# Após aprovação, fazer merge para staging
```

### 2️⃣ Executar Seed em Staging (URGENTE)

**Opção A - Via kubectl exec (Mais Rápido):**
```bash
# Encontrar o pod do backend
kubectl get pods -n staging | grep backend

# Executar o seed
kubectl exec -n staging <backend-pod-name> -- \
  python3 scripts/seed_role_permissions.py
```

**Opção B - Via Kubernetes Job (Recomendado):**
```bash
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seed-role-permissions
  namespace: staging
spec:
  template:
    spec:
      containers:
      - name: seed
        image: <your-backend-image>:latest
        command: ["python3", "scripts/seed_role_permissions.py"]
        envFrom:
        - secretRef:
            name: backend-secrets
      restartPolicy: Never
  backoffLimit: 3
EOF

# Verificar status
kubectl get jobs -n staging
kubectl logs job/seed-role-permissions -n staging

# Limpar após sucesso
kubectl delete job seed-role-permissions -n staging
```

### 3️⃣ Verificar que o Erro 403 Foi Resolvido

```bash
# Verificar dados na tabela
kubectl exec -n staging <backend-pod> -- \
  psql $DATABASE_URL -c "SELECT role FROM role_permissions ORDER BY role;"

# Resultado esperado: 4 roles
# - commander
# - explorer
# - guest
# - navigator
```

### 4️⃣ Testar Endpoints

```bash
# Testar acesso ao dashboard (deve retornar 200, não 403)
curl -H "Authorization: Bearer <token>" \
  https://staging-api.example.com/api/v1/dashboards
```

---

## 📊 Detalhes Técnicos

### O que o Script Faz

O `seed_role_permissions.py` popula a tabela `role_permissions` com 4 roles padrão:

| Role | Permissões Principais |
|------|----------------------|
| **commander** | Full access (criar/editar/deletar planets, gerenciar crew, connections) |
| **navigator** | Most access (criar/editar planets, gerenciar spaces/crews, sem delete) |
| **explorer** | Read-only (visualizar planets, connections, ler tabelas) |
| **guest** | Minimal (apenas visualizar planets) |

### Características do Script

- ✅ **Idempotente**: Seguro executar múltiplas vezes
- ✅ **Atualiza roles existentes**: Não cria duplicatas
- ✅ **Insere roles faltantes**: Garante todos os 4 roles
- ✅ **Sem downtime**: Pode rodar com aplicação em execução

### Integração Automática

Após o merge, **futuros deploys executarão automaticamente** o seed via `scripts/start.sh`:

```bash
# Ordem de execução no startup:
1. Migrações (alembic upgrade head)
2. 🆕 Seed de permissões (seed_role_permissions.py)
3. Criação de usuário de teste
4. Iniciar servidor
```

---

## 🔄 Próximos Passos

### Para Staging (Hoje):
1. ✅ Merge do PR
2. ✅ Executar seed manualmente (Opção A ou B acima)
3. ✅ Verificar que erro 403 foi resolvido
4. ✅ Testar endpoints críticos

### Para Produção (Após validação em Staging):
1. Merge de staging → main
2. Deploy em produção
3. Executar seed em produção (mesmo comando, namespace diferente)
4. Verificação final

### Para CI/CD (Recomendado):
Adicionar step no pipeline de deploy:

```yaml
# Exemplo GitHub Actions
- name: Seed Role Permissions
  run: |
    kubectl exec -n $NAMESPACE deployment/backend -- \
      python3 scripts/seed_role_permissions.py
```

---

## 📚 Documentação Adicional

- **Documentação completa**: `scripts/SEEDING.md`
- **Troubleshooting**: Ver seção "Troubleshooting" em `SEEDING.md`
- **Detalhes técnicos**: `RESOLUTION_403.md`

---

## ✅ Checklist de Validação

- [ ] PR aprovado e merged
- [ ] Seed executado em staging
- [ ] Tabela `role_permissions` tem 4 roles
- [ ] Endpoints retornam 200 (não 403)
- [ ] Testes de integração passando
- [ ] Deploy em produção agendado

---

## 📞 Contato

Para dúvidas ou problemas:
- **Backend Team**: [seu-email]
- **Documentação**: Ver `scripts/SEEDING.md`
- **PR**: https://github.com/sky-first/sky-poc-backend/pull/new/fix/role-permissions-seed

---

**Nota Importante**: Este é um problema de **dados de aplicação**, não de infraestrutura. O DevOps diagnosticou corretamente que a solução deveria vir do time de desenvolvimento. ✅
