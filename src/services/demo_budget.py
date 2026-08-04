"""Tecto diário de gasto do motor na demo pública.

O limite por IP não limita gasto — limita **um** IP. Quem quiser queimar
o orçamento roda endereços, e isso custa cêntimos a quem ataca. Num
produto que expõe um LLM à internet sem autenticação, o único
mecanismo que põe um número máximo na fatura é um contador global.

Por isso este ficheiro é a última linha, não a primeira: o limite por
IP continua a existir e trata do visitante distraído; este trata do
adversário e do bug. Um ciclo infinito no frontend de um cliente faz
tanto estrago como um atacante, e nenhum limite por IP o apanha.

Falha **fechada** quando o Redis não responde. É a decisão oposta à do
resto da demo, e é deliberada: em toda a experiência do visitante
preferimos degradar a recusar, porque o custo de recusar é uma visita
perdida. Aqui o custo de deixar passar é dinheiro real e sem tecto, e
uma demo temporariamente sem perguntas ao vivo continua a mostrar todo
o conteúdo curado e o diagnóstico do ficheiro dele — que corre no
browser e não depende disto para nada.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Perguntas ao vivo por dia, somando todos os visitantes.
#
# A conta que sustenta o número: cada pergunta são alguns cêntimos de
# Bedrock, portanto mil por dia é um tecto de dezenas de euros diários
# no pior caso. Tráfego legítimo numa demo comercial não chega perto —
# se chegar, é uma notícia excelente e sobe-se o número à mão.
DEFAULT_DAILY_CAP = 1000

_KEY_PREFIX = "demo:llm:daily"


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


def _cap() -> int:
    return int(getattr(settings, "DEMO_LLM_DAILY_CAP", 0) or DEFAULT_DAILY_CAP)


def consume(cost: int = 1) -> tuple[bool, Optional[int]]:
    """Regista uma pergunta ao vivo e diz se ainda cabe no orçamento.

    Devolve ``(permitido, restantes)``. ``restantes`` é ``None`` quando
    não há forma de contar — caso em que ``permitido`` é ``False``.
    """
    try:
        import redis  # type: ignore

        url = getattr(settings, "REDIS_URL", "")
        if not url:
            # Sem Redis configurado não há contador partilhado entre
            # pods, e um contador por processo multiplica o tecto pelo
            # número de réplicas — ou seja, não é um tecto.
            logger.error("demo_budget: REDIS_URL vazio, a recusar perguntas ao vivo")
            return False, None

        r = redis.from_url(url, decode_responses=True, socket_timeout=1)
        key = f"{_KEY_PREFIX}:{_today()}"
        used = r.incrby(key, cost)
        if used == cost:
            # Duas vezes o dia, para o contador sobreviver a uma
            # diferença de fuso entre pods sem nunca crescer sem fim.
            r.expire(key, 172_800)
        cap = _cap()
        return used <= cap, max(0, cap - int(used))
    except Exception as exc:  # noqa: BLE001
        logger.error("demo_budget indisponível, a recusar perguntas ao vivo: %s", exc)
        return False, None


def remaining() -> Optional[int]:
    """Quanto resta hoje, para observabilidade. ``None`` se não der para saber."""
    try:
        import redis  # type: ignore

        url = getattr(settings, "REDIS_URL", "")
        if not url:
            return None
        r = redis.from_url(url, decode_responses=True, socket_timeout=1)
        used = int(r.get(f"{_KEY_PREFIX}:{_today()}") or 0)
        return max(0, _cap() - used)
    except Exception:  # noqa: BLE001
        return None


__all__ = ["DEFAULT_DAILY_CAP", "consume", "remaining"]
