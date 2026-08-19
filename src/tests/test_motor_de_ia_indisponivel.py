"""O motor de IA em baixo não pode parecer a plataforma partida.

Apanhado a correr os testes com o `.env.local` a apontar para um sky-ai que
não estava de pé: 12 chamadas a `/ai/query` devolveram

    500 {"error":"Internal Server Error","message":"Request failed"}

A excepção do cliente HTTP subia ao handler genérico. Quem está do outro lado
vê uma aplicação avariada e não sabe se a culpa é da pergunta, dos dados ou do
produto — que é exactamente o que o Lucas quer evitar.

Passa a devolver 200 com `status="error"` e uma frase honesta. A frase é
**diferente** da de "não encontrei dados" de propósito: houve uma avaria, não
uma ausência, e dizer "não há dados" manda a pessoa procurar um problema que
não existe.
"""

from __future__ import annotations

import re
from pathlib import Path

FONTE = Path("src/api/v1/ai.py").read_text(encoding="utf-8")


def _bloco_do_process_query() -> str:
    i = FONTE.index("response = await ai_service.process_query")
    return FONTE[i - 2000 : i + 2000]


def test_a_chamada_ao_motor_esta_protegida():
    bloco = _bloco_do_process_query()
    assert "try:" in bloco.split("await ai_service.process_query")[0][-200:], (
        "a chamada ao motor de IA não está dentro de um try — uma falha de "
        "infraestrutura volta a sair como 500 genérico"
    )


def test_erros_de_negocio_continuam_a_passar():
    """Sem isto, o `except` engolia 403/404/429 e transformava uma recusa de
    permissão numa mensagem de 'indisponível' — que é mentira e esconde o
    problema real de quem administra."""
    bloco = _bloco_do_process_query()
    assert "except (BaseAPIException, RateLimitExceeded):" in bloco
    assert re.search(r"except \(BaseAPIException, RateLimitExceeded\):\s*\n(\s*#[^\n]*\n)*\s*raise", bloco), (
        "os erros de negócio têm de ser relançados, não convertidos"
    )


def test_a_resposta_de_avaria_e_200_com_status_error():
    bloco = _bloco_do_process_query()
    assert 'status="error"' in bloco
    assert "AIQueryResponse(" in bloco


def test_a_frase_nao_diz_que_faltam_dados():
    """A distinção que o Lucas pediu: avaria ≠ ausência de dados.

    Se alguém um dia unificar as frases, isto avisa.
    """
    bloco = _bloco_do_process_query()
    i = bloco.index("answer=(")
    frase = bloco[i : bloco.index("),", i)]
    assert "indisponível" in frase
    for proibido in ("não encontrei dados", "sem dados", "nenhum dado"):
        assert proibido not in frase.lower(), (
            f"a frase de avaria não pode sugerir falta de dados: {proibido!r}"
        )
