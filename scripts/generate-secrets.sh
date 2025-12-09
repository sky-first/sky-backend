#!/bin/bash

# Script para gerar chaves secretas seguras

echo "🔐 Gerando chaves secretas seguras..."
echo ""

echo "# Adicione estas chaves ao seu .env.production:"
echo ""
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
echo "REDIS_PASSWORD=$(openssl rand -base64 32)"
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)"
echo ""

