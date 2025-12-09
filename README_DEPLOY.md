# 🚀 Guia de Deploy - Resumo Executivo

## ⚡ Deploy Rápido (3 Passos)

### 1. Gerar Chaves Secretas

```bash
./scripts/generate-secrets.sh
```

Copie as chaves geradas.

### 2. Configurar Ambiente

```bash
cp .env.production.example .env.production
nano .env.production  # Cole as chaves geradas
```

### 3. Deploy

```bash
./scripts/deploy.sh
```

**Pronto!** Sistema rodando em:
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API Docs: http://localhost:8000/docs

## 📋 Checklist Pré-Deploy

- [ ] Docker instalado e rodando
- [ ] Portas 3000, 8000, 5432, 6379 disponíveis
- [ ] `.env.production` configurado
- [ ] Senhas e chaves secretas alteradas
- [ ] CORS configurado corretamente

## 🛠️ Comandos Úteis

```bash
# Ver status
docker-compose -f docker-compose.prod.yml ps

# Ver logs
docker-compose -f docker-compose.prod.yml logs -f

# Parar
docker-compose -f docker-compose.prod.yml down

# Reiniciar
docker-compose -f docker-compose.prod.yml restart

# Rebuild
docker-compose -f docker-compose.prod.yml up -d --build
```

## 📚 Documentação Completa

- **DEPLOY.md** - Guia completo de deploy
- **DEPLOY_QUICK.md** - Guia rápido
- **.env.production.example** - Exemplo de configuração

## 🆘 Problemas?

1. Verifique os logs: `docker-compose -f docker-compose.prod.yml logs`
2. Verifique o status: `docker-compose -f docker-compose.prod.yml ps`
3. Consulte a seção Troubleshooting em `DEPLOY.md`

