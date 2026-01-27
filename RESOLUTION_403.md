# Resolução do Erro 403 - Tabela role_permissions Vazia

## Sumário Executivo

**Status**: ✅ Resolvido  
**Responsável**: Backend Developer  
**Data**: 2026-01-26  

## Problema Identificado
O DevOps identificou corretamente que a tabela `role_permissions` estava vazia em produção, causando erros 403 Forbidden em todos os endpoints protegidos.

## Causa Raiz
Faltava um **script de seed (inicialização de dados)** para popular a tabela `role_permissions` com as permissões padrão do sistema RBAC (Role-Based Access Control).

## Solução Implementada

### 1. Script de Seed Criado
📁 **Arquivo**: `scripts/seed_role_permissions.py`

- Popula 4 roles: `commander`, `navigator`, `explorer`, `guest`
- Idempotente (seguro executar múltiplas vezes)
- Atualiza roles existentes e insere novos

### 2. Integração Automática
📁 **Arquivo**: `scripts/start.sh` (atualizado)

O script de inicialização agora executa automaticamente:
1. Migrações do banco (`alembic upgrade head`)
2. **🆕 Seed de permissões** (`seed_role_permissions.py`)
3. Criação de usuário de teste

### 3. Documentação para DevOps
📁 **Arquivo**: `scripts/SEEDING.md`

Contém instruções completas para:
- Executar manualmente via kubectl
- Criar Kubernetes Jobs
- Integrar no CI/CD
- Troubleshooting

## Ações Necessárias do DevOps

### Opção A: Executar Manualmente (Rápido)
```bash
# Encontrar o pod do backend
kubectl get pods -n <namespace> | grep backend

# Executar o seed
kubectl exec -n <namespace> <backend-pod-name> -- \
  python3 scripts/seed_role_permissions.py
```

### Opção B: Criar Kubernetes Job (Recomendado)
```bash
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seed-role-permissions
  namespace: <your-namespace>
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
```

### Opção C: Redeploy (Automático)
Se o deployment usar `scripts/start.sh` como entrypoint, basta fazer um novo deploy. O seed será executado automaticamente.

## Verificação
Após executar o seed, verificar:

```bash
kubectl exec -n <namespace> <backend-pod> -- \
  psql $DATABASE_URL -c "SELECT COUNT(*) FROM role_permissions;"
```

**Resultado esperado**: 4 roles

## Próximos Passos (Recomendações)

### Para o DevOps:
1. ✅ Executar o seed em Staging
2. ✅ Verificar que o erro 403 foi resolvido
3. ✅ Executar o seed em Produção
4. 📋 Adicionar o seed ao pipeline de CI/CD (ver `SEEDING.md`)

### Para o Backend:
1. ✅ Script de seed criado e testado localmente
2. ✅ Integrado ao `start.sh` para deploys futuros
3. ✅ Documentação completa fornecida
4. 📋 Considerar criar uma migration de dados (Alembic) para garantir que o seed rode automaticamente

## Arquivos Modificados/Criados

```
sky-poc-backend/
├── scripts/
│   ├── seed_role_permissions.py     # 🆕 Script de seed
│   ├── SEEDING.md                   # 🆕 Documentação DevOps
│   └── start.sh                     # ✏️  Atualizado (adicionado seed)
└── RESOLUTION_403.md                # 🆕 Este arquivo
```

## Contato
Para dúvidas ou problemas, contatar o time de Backend.

---
**Nota**: Este é um problema de **dados de aplicação**, não de infraestrutura. O DevOps diagnosticou corretamente que a solução deveria vir do time de desenvolvimento.
