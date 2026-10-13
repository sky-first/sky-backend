"""Idempotency middleware using Redis to prevent duplicate processing of mutations.

── Guarda o estado e o id, nunca o corpo (13/10/2026) ──────────────

Até aqui guardava-se o CORPO inteiro da resposta no Redis, durante o
`IDEMPOTENCY_TTL_SECONDS`. Uma mutação que devolvesse dados — um widget
com as linhas, uma resposta da IA — deixava uma cópia dos dados do
cliente no Redis, fora de qualquer regra de acesso. Decisão do Lucas:
nunca guardamos as linhas do cliente.

Agora guarda-se só o que a idempotência precisa: o estado HTTP e o id do
recurso criado. Uma repetição com a mesma chave recebe o mesmo estado e
`{"id": ..., "idempotent_replay": true}` — e quem quiser o recurso pede-o
pelo id, passando pelas regras de acesso de sempre. Guardam-se todos os
identificadores do topo da resposta (`id`, `job_id`, `widget_id`…), para
uma repetição de `POST /pages/ai/build-async` continuar a trazer o `job_id`.
"""

import json
import logging
from typing import Any, Callable, cast

from fastapi import Request, Response
from starlette.concurrency import iterate_in_threadpool

from src.config.redis import get_redis
from src.config.settings import settings

logger = logging.getLogger(__name__)


async def idempotency_middleware(request: Request, call_next: Callable) -> Response:
    """
    Idempotency middleware.

    Checks for 'Idempotency-Key' header in mutations (POST, PUT, PATCH, DELETE).
    If found, checks Redis for a cached response for that key + user_id.
    """
    idempotency_key = request.headers.get("Idempotency-Key")

    # Only apply to mutations and if header is present
    if not idempotency_key or request.method == "GET":
        return cast(Response, await call_next(request))

    try:
        redis = await get_redis()
        if redis is None:
            # Redis not available, skip idempotency
            logger.debug("Redis not available, skipping idempotency")
            return cast(Response, await call_next(request))

        # User ID should be set by auth_middleware which executes BEFORE this
        user_id = (
            getattr(request.state, "user_id", None)
            if hasattr(request.state, "user_id")
            else "anonymous"
        )

        # Unique key per user + idempotency key
        redis_key = f"idempotency:{user_id}:{idempotency_key}"

        # 1. Check if we have a cached response
        cached_data = await redis.get(redis_key)
        if cached_data:
            logger.info(f"Idempotency HIT for key: {idempotency_key}, user: {user_id}")
            try:
                data = json.loads(cached_data)
                return resposta_de_repeticao(data)
            except Exception as e:
                logger.warning(
                    f"Failed to parse cached idempotency data for key {idempotency_key}: {e}"
                )

        # 2. Process request normally if no cache hit
        response = cast(Response, await call_next(request))

        # 3. Cache successful (2xx) responses — o estado e o id, nunca o corpo
        if 200 <= response.status_code < 300:
            try:
                res_any = cast(Any, response)
                full_body_bytes = b""
                if getattr(res_any, "body_iterator", None) is not None:
                    try:
                        response_body = [section async for section in res_any.body_iterator]
                        res_any.body_iterator = iterate_in_threadpool(iter(response_body))
                        full_body_bytes = b"".join(response_body)
                    except Exception as body_err:
                        logger.warning(f"Could not iterate body for idempotency: {body_err}")
                        return response
                elif hasattr(res_any, "body"):
                    full_body_bytes = res_any.body or b""

                await redis.setex(
                    redis_key,
                    settings.IDEMPOTENCY_TTL_SECONDS,
                    json.dumps(
                        {
                            "status_code": response.status_code,
                            "ids": ids_do_recurso(full_body_bytes),
                        }
                    ),
                )
            except Exception as cache_error:
                logger.error(f"Idempotency cache persistence error: {str(cache_error)}")

        return response

    except Exception as e:
        logger.error(f"Idempotency middleware error (continuing without idempotency): {str(e)}")
        # On middleware internal failure (before call_next), allow request to proceed
        return cast(Response, await call_next(request))


def ids_do_recurso(corpo: bytes) -> dict:
    """Os identificadores da resposta — `id` e qualquer `*_id` (`job_id`,
    `widget_id`, `query_id`…) no topo ou em `data` — e nada mais.

    É a única coisa do corpo que se guarda: um id não é dado do cliente, e é
    o que quem repete precisa (ex.: o `job_id` de uma construção assíncrona
    para a seguir pelo estado). O resto pode ter linhas do cliente.
    """
    try:
        dados = json.loads(corpo.decode("utf-8")) if corpo else None
    except Exception:
        return {}
    if not isinstance(dados, dict):
        return {}

    def _ids(d: dict) -> dict:
        return {
            k: v
            for k, v in d.items()
            if (k == "id" or k.endswith("_id")) and isinstance(v, (str, int))
            and not isinstance(v, bool)
        }

    saida = _ids(dados)
    interno = dados.get("data")
    if not saida and isinstance(interno, dict):
        saida = _ids(interno)
    return saida


def id_do_recurso(corpo: bytes) -> Any:
    """O `id` do recurso (compatibilidade: o primeiro identificador)."""
    ids = ids_do_recurso(corpo)
    return ids.get("id") if "id" in ids else next(iter(ids.values()), None)


def resposta_de_repeticao(guardado: dict) -> Response:
    """A resposta a uma repetição: o mesmo estado, os ids, e nada mais."""
    from fastapi.responses import JSONResponse

    corpo: dict = {"idempotent_replay": True}
    ids = guardado.get("ids")
    if isinstance(ids, dict):
        corpo.update(ids)
    elif guardado.get("resource_id") is not None:
        corpo["id"] = guardado["resource_id"]
    return JSONResponse(
        content=corpo,
        status_code=int(guardado.get("status_code") or 200),
        headers={"X-Idempotency-Cache": "HIT"},
    )
