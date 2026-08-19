"""O rate limiting não pode engolir os erros da aplicação.

Apanhado a varrer produção: um member a pedir um projeto onde não está
recebia

    500 {"error":"Internal Server Error","message":"Request failed"}

em vez do 403 que o serviço levanta. E o registo dizia
*"Rate limiting error (continuing without rate limit)"*, o que manda quem
investiga para o sítio errado.

A causa: o `call_next` — a chamada à aplicação inteira — estava dentro do
`try` do rate limiting. Qualquer excepção da aplicação era apanhada ali,
`response` continuava a None, e o middleware **chamava `call_next` outra
vez**. O próprio comentário do ficheiro avisava que o canal ASGI já foi
consumido; a segunda tentativa rebentava e saía o 500 opaco.

Três consequências, por ordem de gravidade:

  1. o pedido corria **duas vezes** — efeitos secundários incluídos;
  2. o estado certo (403, 404, 409...) virava 500;
  3. o registo culpava o rate limiting.
"""

from __future__ import annotations

import re
from pathlib import Path

FONTE = Path("src/api/middleware/rate_limit.py").read_text(encoding="utf-8")


def _corpo_do_try() -> str:
    """O bloco de rate limiting propriamente dito."""
    i = FONTE.index("    resposta_de_limite: Response | None = None")
    j = FONTE.index("    except _SemRateLimit:", i)
    return FONTE[i:j]


def test_a_aplicacao_nao_e_chamada_dentro_do_try():
    """O defeito, na sua forma mais directa."""
    assert "call_next" not in _corpo_do_try(), (
        "o `call_next` voltou para dentro do bloco de rate limiting — uma "
        "excepção da aplicação volta a virar 500 e a correr o pedido 2x"
    )


def test_o_call_next_do_fluxo_normal_acontece_uma_so_vez():
    depois = FONTE[FONTE.index("    except _SemRateLimit:") :]
    assert depois.count("await call_next(request)") == 1, (
        "há mais do que uma chamada à aplicação depois do rate limiting; o "
        "canal ASGI só pode ser consumido uma vez"
    )


def test_ja_nao_existe_o_500_fabricado_aqui():
    """Este middleware não tem informação para decidir que algo é um 500.

    A resposta sem `correlation_id` que ele fabricava era, além de errada,
    impossível de correlacionar com o que se via nos registos.
    """
    assert '"message": "Request failed"' not in FONTE


def test_as_saidas_antecipadas_continuam_a_devolver_uma_so_chamada():
    """A outra metade: os caminhos que saltam o rate limiting (OPTIONS,
    /health, /auth/) chamam a aplicação e devolvem logo. Se algum deles
    deixasse de o fazer, o pedido nunca chegava à aplicação."""
    antes = FONTE[: FONTE.index("    resposta_de_limite: Response | None = None")]
    saidas = re.findall(r"return cast\(Response, await call_next\(request\)\)", antes)
    assert len(saidas) >= 4, "as saídas antecipadas desapareceram"


def test_o_erro_do_redis_continua_a_deixar_passar():
    """Fechar de mais era pior: se o Redis cair, ninguém entra."""
    assert "except Exception as e:" in FONTE
    assert "continuing without rate limit" in FONTE
    assert "resposta_de_limite = None" in FONTE
