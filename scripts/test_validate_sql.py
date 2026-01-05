#!/usr/bin/env python3
"""Script de teste para o endpoint de validação SQL."""

import asyncio
import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schemas.ai import ValidateSQLRequest, ValidateSQLResponse


def test_schemas():
    """Testa se os schemas estão corretos."""
    print("🧪 Testando schemas...")
    
    # Test ValidateSQLRequest
    request = ValidateSQLRequest(
        connection_id="test-connection-id",
        sql="SELECT * FROM users LIMIT 5",
        space_id="test-space-id",
        user_id="test-user-id",
        is_personal=False
    )
    assert request.connection_id == "test-connection-id"
    assert request.sql == "SELECT * FROM users LIMIT 5"
    print("✅ ValidateSQLRequest schema OK")
    
    # Test ValidateSQLResponse
    response = ValidateSQLResponse(
        is_valid=True,
        error=None,
        preview_data=[{"id": 1, "name": "Test"}],
        num_rows=1,
        execution_time_ms=123.45,
        columns=["id", "name"]
    )
    assert response.is_valid is True
    assert response.num_rows == 1
    print("✅ ValidateSQLResponse schema OK")
    
    print("\n✅ Todos os schemas estão corretos!")


if __name__ == "__main__":
    try:
        test_schemas()
        print("\n🎉 Testes de schemas passaram com sucesso!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erro nos testes: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

