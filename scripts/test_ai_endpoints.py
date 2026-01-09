#!/usr/bin/env python3
"""
Script para testar todos os endpoints da chatbox AI
Verifica se estão usando Real AI Service e retornando respostas reais
"""

import json
import os
import sys
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

load_dotenv()

# Configurações
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
TEST_EMAIL = os.getenv("TEST_EMAIL", "test@example.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "Test@2024!Secure")

# Perguntas de teste
TEST_QUESTIONS = [
    "Qual é a performance de faturamento mensal?",
    "Quais clientes geram mais faturamento?",
    "Como se distribui o faturamento por categoria de valor?",
    "Como evolui o faturamento ao longo do tempo?",
    "Qual é a análise de status das faturas?",
    "Qual é a performance de pagamentos mensal?",
    "Qual método de pagamento é mais utilizado?",
    "Em quais dias da semana há mais pagamentos?",
    "Qual é a análise de status dos pagamentos?",
    "Quais clientes fazem mais pagamentos?",
    "Qual é a performance de reembolsos mensal?",
    "Quais são as principais razões de reembolso?",
    "Qual é a performance de créditos mensal?",
    "Quais são as principais razões de crédito?",
]


def get_access_token() -> str:
    """Faz login e retorna access_token"""
    print("🔐 Fazendo login...")
    response = requests.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=10,
    )
    if response.status_code != 200:
        print(f"❌ Erro no login: {response.status_code}")
        print(response.text)
        sys.exit(1)

    data = response.json()
    token = data.get("access_token")
    if not token:
        print("❌ Token não encontrado na resposta")
        sys.exit(1)

    print("✅ Login realizado com sucesso")
    return token


def test_health_checks(token: str) -> bool:
    """Testa health checks do backend e AI service"""
    print("\n" + "=" * 80)
    print("1️⃣ TESTANDO HEALTH CHECKS")
    print("=" * 80)

    # Backend health
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Backend está rodando")
        else:
            print(f"⚠️  Backend retornou {response.status_code}")
    except Exception as e:
        print(f"❌ Erro ao conectar ao backend: {e}")
        return False

    # AI Service health
    try:
        response = requests.get(f"{AI_SERVICE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ AI Service está rodando")
        else:
            print(f"⚠️  AI Service retornou {response.status_code}")
    except Exception as e:
        print(f"❌ Erro ao conectar ao AI Service: {e}")
        print("   ⚠️  O backend vai usar mock AI se o serviço não estiver disponível")

    return True


def test_chat_bootstrap(token: str) -> Dict[str, Any]:
    """Testa GET /api/v1/ai/chat/bootstrap"""
    print("\n" + "=" * 80)
    print("2️⃣ TESTANDO GET /api/v1/ai/chat/bootstrap")
    print("=" * 80)

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(
            f"{BACKEND_URL}/api/v1/ai/chat/bootstrap",
            headers=headers,
            params={"max_suggestions": 4},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            print("✅ Bootstrap retornou sucesso")
            print(f"   Greeting: {data.get('greeting', 'N/A')[:50]}...")
            print(f"   Sugestões: {len(data.get('suggestions', []))}")
            return {"success": True, "data": data}
        else:
            print(f"❌ Erro {response.status_code}: {response.text[:200]}")
            return {"success": False, "error": response.text}
    except Exception as e:
        print(f"❌ Erro: {e}")
        return {"success": False, "error": str(e)}


def test_query_endpoint(token: str, question: str, question_num: int, total: int) -> Dict[str, Any]:
    """Testa POST /api/v1/ai/query"""
    print(f"\n{'='*80}")
    print(f"3️⃣.{question_num} TESTANDO POST /api/v1/ai/query")
    print(f"{'='*80}")
    print(f"Pergunta: {question}")

    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "question": question,
        "configure_data": {
            "question": question,
            "knowledge": [],
            "response_format": "text",
        },
        "is_personal": False,
    }

    try:
        response = requests.post(
            f"{BACKEND_URL}/api/v1/ai/query", headers=headers, json=payload, timeout=120
        )

        if response.status_code == 200:
            data = response.json()
            answer = data.get("answer", "")
            sql = data.get("sql", "")
            data_sample = data.get("data_sample", [])

            print(f"✅ Resposta recebida (length: {len(answer)})")
            print(f"   Answer preview: {answer[:100]}...")
            if sql:
                print(f"   SQL gerado: {sql[:100]}...")
            if data_sample:
                print(f"   Data sample: {len(data_sample)} linhas")

            # Verificar se é resposta real ou mock
            is_mock = "mock" in answer.lower() or "example" in answer.lower() or len(answer) < 50

            if is_mock:
                print("   ⚠️  Parece ser resposta MOCK (muito curta ou contém 'mock'/'example')")
            else:
                print("   ✅ Parece ser resposta REAL da AI")

            return {
                "success": True,
                "answer": answer,
                "sql": sql,
                "data_sample": data_sample,
                "is_mock": is_mock,
            }
        else:
            print(f"❌ Erro {response.status_code}: {response.text[:200]}")
            return {"success": False, "error": response.text}
    except Exception as e:
        print(f"❌ Erro: {e}")
        return {"success": False, "error": str(e)}


def test_chat_endpoint(token: str, question: str, question_num: int, total: int) -> Dict[str, Any]:
    """Testa POST /api/v1/ai/chat"""
    print(f"\n{'='*80}")
    print(f"4️⃣.{question_num} TESTANDO POST /api/v1/ai/chat")
    print(f"{'='*80}")
    print(f"Pergunta: {question}")

    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "message": question,
        "widget_id": None,
        "context": {
            "knowledge": [],
            "space_id": None,
            "is_personal": False,
        },
    }

    try:
        response = requests.post(
            f"{BACKEND_URL}/api/v1/ai/chat", headers=headers, json=payload, timeout=120
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("content", "")

            print(f"✅ Resposta recebida (length: {len(content)})")
            print(f"   Content preview: {content[:100]}...")

            # Verificar se é resposta real ou mock
            is_mock = "mock" in content.lower() or "example" in content.lower() or len(content) < 50

            if is_mock:
                print("   ⚠️  Parece ser resposta MOCK (muito curta ou contém 'mock'/'example')")
            else:
                print("   ✅ Parece ser resposta REAL da AI")

            return {"success": True, "content": content, "is_mock": is_mock}
        else:
            print(f"❌ Erro {response.status_code}: {response.text[:200]}")
            return {"success": False, "error": response.text}
    except Exception as e:
        print(f"❌ Erro: {e}")
        return {"success": False, "error": str(e)}


def main():
    """Executa todos os testes"""
    print("=" * 80)
    print("🧪 TESTE COMPLETO DOS ENDPOINTS DA CHATBOX AI")
    print("=" * 80)
    print(f"\nConfigurações:")
    print(f"  Backend URL: {BACKEND_URL}")
    print(f"  AI Service URL: {AI_SERVICE_URL}")
    print(f"  Test Email: {TEST_EMAIL}")

    # Login
    token = get_access_token()

    # Health checks
    if not test_health_checks(token):
        print("\n❌ Health checks falharam. Abortando testes.")
        sys.exit(1)

    # Test bootstrap
    bootstrap_result = test_chat_bootstrap(token)

    # Test query endpoint (primeira pergunta)
    query_results = []
    if TEST_QUESTIONS:
        query_result = test_query_endpoint(token, TEST_QUESTIONS[0], 1, len(TEST_QUESTIONS))
        query_results.append(query_result)

    # Test chat endpoint (primeira pergunta)
    chat_results = []
    if TEST_QUESTIONS:
        chat_result = test_chat_endpoint(token, TEST_QUESTIONS[0], 1, len(TEST_QUESTIONS))
        chat_results.append(chat_result)

    # Resumo
    print("\n" + "=" * 80)
    print("📊 RESUMO DOS TESTES")
    print("=" * 80)

    print(f"\n✅ Bootstrap: {'OK' if bootstrap_result.get('success') else 'FALHOU'}")
    print(
        f"✅ Query Endpoint: {'OK' if query_results and query_results[0].get('success') else 'FALHOU'}"
    )
    print(
        f"✅ Chat Endpoint: {'OK' if chat_results and chat_results[0].get('success') else 'FALHOU'}"
    )

    # Verificar se estão usando Real AI
    print("\n🔍 VERIFICAÇÃO DE REAL AI:")
    if query_results and query_results[0].get("success"):
        is_mock = query_results[0].get("is_mock", True)
        print(f"   Query Endpoint: {'⚠️  MOCK' if is_mock else '✅ REAL AI'}")

    if chat_results and chat_results[0].get("success"):
        is_mock = chat_results[0].get("is_mock", True)
        print(f"   Chat Endpoint: {'⚠️  MOCK' if is_mock else '✅ REAL AI'}")

    print("\n💡 DICA: Verifique os logs do backend para confirmar:")
    print("   - Procure por '[send_chat_message] Calling real AI service'")
    print("   - Procure por 'Calling real AI service with connection_id='")
    print("   - Se não aparecer, o backend está usando MOCK")


if __name__ == "__main__":
    main()
