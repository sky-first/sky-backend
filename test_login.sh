#!/bin/bash

# Script para testar login
echo "🧪 Testando login..."

# Teste 1: Health check
echo ""
echo "1️⃣ Testando health check..."
curl -s http://localhost:8000/health | python3 -m json.tool || echo "❌ Backend não respondeu"

# Teste 2: Login sem CORS
echo ""
echo "2️⃣ Testando login (sem Origin)..."
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test@2024!Secure"}')

if echo "$RESPONSE" | grep -q "access_token"; then
    echo "✅ Login funcionou!"
    echo "$RESPONSE" | python3 -m json.tool | head -5
else
    echo "❌ Login falhou:"
    echo "$RESPONSE" | head -5
fi

# Teste 3: Login com CORS (simulando frontend)
echo ""
echo "3️⃣ Testando login com Origin (simulando frontend)..."
RESPONSE2=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:3000" \
  -d '{"email":"test@example.com","password":"Test@2024!Secure"}')

if echo "$RESPONSE2" | grep -q "access_token"; then
    echo "✅ Login com CORS funcionou!"
    echo "$RESPONSE2" | python3 -m json.tool | head -5
else
    echo "❌ Login com CORS falhou:"
    echo "$RESPONSE2" | head -5
fi

# Teste 4: Verificar CORS headers
echo ""
echo "4️⃣ Verificando CORS headers..."
CORS_HEADERS=$(curl -s -X OPTIONS http://localhost:8000/api/v1/auth/login \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  -v 2>&1 | grep -i "access-control")

if [ -z "$CORS_HEADERS" ]; then
    echo "⚠️  CORS headers não encontrados"
else
    echo "✅ CORS headers encontrados:"
    echo "$CORS_HEADERS"
fi

