"""HTTP client for AI service."""

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)


class AIServiceHTTPClient:
    """HTTP client for AI service (ia-do-projeto)."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize AI service HTTP client.

        Args:
            base_url: Base URL of AI service (defaults to settings.AI_SERVICE_URL)
        """
        self.base_url = (base_url or settings.AI_SERVICE_URL).rstrip("/")
        # Previously 25s, which was shorter than the time a real Claude call
        # plus metadata/retrieval takes for a medium-complexity question.
        # 90s fits inside the frontend's 120s withTimeout budget and aligns
        # with the AI service's own 300s Ollama ceiling. Configurable via
        # AI_SERVICE_HTTP_TIMEOUT so ops can dial it without a deploy.
        self.timeout = float(getattr(settings, "AI_SERVICE_HTTP_TIMEOUT", None) or 90.0)

    def _tenant_headers(self) -> Dict[str, str]:
        """Per-request headers forwarded to the AI service.

        Carries the resolved tenant slug (``X-Tenant-Slug``) so the AI
        service can route its DB sessions to the tenant's own database
        (Model B / Phase 5). Returns an empty dict for the default /
        single-tenant context, so non-tenant traffic is byte-for-byte
        unchanged and nothing breaks while the AI side is still rolling
        out the routing. Never raises — an AI call must not fail because
        the tenant contextvar was unset on some background path.
        """
        try:
            from src.core.tenant_context import current_tenant

            ctx = current_tenant()
            if ctx is not None and not ctx.is_default and ctx.slug:
                return {"X-Tenant-Slug": ctx.slug}
        except Exception:  # pragma: no cover — defensive
            pass
        return {}

    async def classificar_achado(
        self,
        *,
        answer: str,
        title: str = "",
        question: str | None = None,
    ) -> dict:
        """Risco, oportunidade ou achado — e o quanto pesa.

        Todos os achados nasciam iguais: o worker gravava `type="insight"` e
        `severity="medium"` cravados no código, e por isso os filtros «Risco»
        e «Oportunidade» — que existem nas duas interfaces — estavam sempre a
        zero para achados a sério.

        **NUNCA rebenta.** Um classificador que rebenta faz perder o achado
        que estava a classificar, e o achado vale mais do que a etiqueta. Em
        qualquer falha devolve o que o worker gravava antes: o pior caso é
        ficar como estava.

        Chamada curta e com prazo curto: isto é uma etiqueta, e uma etiqueta
        não pode atrasar a corrida de um agente.
        """
        import httpx

        # `medium` e nao `med` — o esquema da API so aceita
        # `low|medium|high|critical`, e um `med` gravado rebenta o detalhe do
        # agente com um 500. Ver `_gravidade_valida` no `agent_worker`.
        de_omissao = {"type": "insight", "severity": "medium", "classified": False}
        try:
            async with httpx.AsyncClient(
                timeout=20.0, headers=self._tenant_headers()
            ) as client:
                r = await client.post(
                    f"{self.base_url}/findings/classify",
                    json={"answer": answer, "title": title, "question": question},
                )
                r.raise_for_status()
                return r.json() or de_omissao
        except Exception as exc:  # noqa: BLE001
            logger.warning("classificar_achado falhou: %s", exc)
            return de_omissao

    async def query_connection(
        self,
        connection_id: str,
        question: str,
        user_id: str,
        space_id: str,
        crew_ids: Optional[List[str]] = None,
        space_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        is_personal: Optional[bool] = None,
        selected_datasets: Optional[List[str]] = None,
        authorized_tables: Optional[List[str]] = None,
        instructions: Optional[str] = None,
        response_format: Optional[str] = None,
        security_config: Optional[Dict[str, Any]] = None,
        ai_tone: Optional[str] = None,
        ai_style: Optional[str] = None,
        locale: Optional[str] = None,
        mentioned_file_ids: Optional[List[str]] = None,
        agent_mode: Optional[str] = None,
        sql_instructions: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Query a connection using the AI service.

        Args:
            connection_id: Connection ID
            question: User question
            user_id: User ID
            space_id: Space ID
            crew_ids: Optional list of crew IDs
            thread_id: Optional thread ID for conversation context
            is_personal: Optional personal mode flag
            selected_datasets: Optional list of table names to force
            instructions: Optional custom instructions for the AI
            sql_instructions: Optional SQL template for the specialist to follow
        """
        url = f"{self.base_url}/connections/{connection_id}/query"

        payload: Dict[str, Any] = {
            "question": question,
            "user_id": user_id,
            "space_id": space_id,
        }

        # Envio correto de variáveis isoladas
        if selected_datasets:
            payload["selected_datasets"] = selected_datasets
        if authorized_tables:
            payload["authorized_tables"] = authorized_tables

        if crew_ids:
            payload["crew_ids"] = crew_ids
        if space_ids:
            # Personal mode: caller's full Space membership. Lets the
            # AI RAG surface space-scoped rows from every Space the
            # caller belongs to (vector_store OR-clause keyed on
            # `caller_space_ids`). Outside Personal this is None.
            payload["space_ids"] = space_ids
        if thread_id:
            payload["thread_id"] = thread_id
        if is_personal is not None:
            payload["is_personal"] = bool(is_personal)
        if instructions:
            payload["instructions"] = instructions
        if response_format:
            payload["response_format"] = response_format
        if security_config:
            payload["security_config"] = security_config
        if ai_tone:
            payload["ai_tone"] = ai_tone
        if ai_style:
            payload["ai_style"] = ai_style
        if locale:
            payload["locale"] = locale
        if mentioned_file_ids:
            payload["mentioned_file_ids"] = mentioned_file_ids
        if agent_mode:
            payload["agent_mode"] = agent_mode
        if sql_instructions:
            payload["sql_instructions"] = sql_instructions
        if connection_ids:
            # Extra connections whose metadata the AI service will merge so the
            # orchestrator can build cross-schema queries (multi-source path).
            payload["connection_ids"] = connection_ids

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                f"Calling AI service: {url} with connection_id={connection_id}, "
                f"space_id={space_id}, extra_connection_ids={connection_ids}"
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def stream_query_connection(
        self,
        connection_id: str,
        question: str,
        user_id: str,
        space_id: str,
        instructions: Optional[str] = None,
        is_personal: Optional[bool] = None,
        selected_context: Optional[Dict[str, List[str]]] = None,
        crew_ids: Optional[List[str]] = None,
        authorized_tables: Optional[List[str]] = None,
        agent_mode: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
        selected_datasets: Optional[List[str]] = None,
        sql_instructions: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a query to the AI service via SSE.
        Yields raw SSE lines (data: {...}) as they arrive.

        ``selected_context`` lets the caller restrict retrieval to
        specific context entity IDs ({kind: [id, ...]}). The AI service
        treats empty dict / missing kinds as "no filter".

        ``crew_ids`` is the list of crews the asking user belongs to in
        ``space_id`` (collaborative mode) — the RAG uses it to restrict
        retrieval to embeddings whose ``crew_id`` is either NULL (space-
        wide) or in that list. Omitting it means "user is not in any
        crew", so the RAG only surfaces crew_id-NULL rows. Without this
        parameter a Space member would silently miss their own Crew's
        embeddings (bug found in collaborative RAG audit).
        """
        url = f"{self.base_url}/connections/{connection_id}/query/stream"

        payload: Dict[str, Any] = {
            "question": question,
            "user_id": user_id,
            "space_id": space_id,
        }
        if instructions:
            payload["instructions"] = instructions
        if is_personal is not None:
            payload["is_personal"] = bool(is_personal)
        if selected_context:
            payload["selected_context"] = selected_context
        if crew_ids:
            payload["crew_ids"] = crew_ids
        # Sent even when empty: [] is a real answer (fail-closed — the user is
        # authorized for no tables on this connection), distinct from None
        # (not computed → AI falls back to its own permission filter).
        if authorized_tables is not None:
            payload["authorized_tables"] = authorized_tables
        if agent_mode:
            payload["agent_mode"] = agent_mode
        if connection_ids:
            payload["connection_ids"] = connection_ids
        if selected_datasets:
            payload["selected_datasets"] = selected_datasets
        if sql_instructions:
            payload["sql_instructions"] = sql_instructions
        if locale:
            payload["locale"] = locale

        async with httpx.AsyncClient(timeout=120.0, headers=self._tenant_headers()) as client:
            logger.info(f"Streaming AI service: {url} for connection {connection_id}")
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield line

    # Sentinel for shared/global indexing. Use this instead of None
    # so a forgotten kwarg can't silently turn a tenant-private
    # connection into a globally-readable index.
    SHARED_INDEX = "__shared__"

    async def discover_connection(
        self,
        connection_id: str,
        space_id: str,  # required: pass an actual space UUID, or SHARED_INDEX
        run_in_background: Optional[bool] = None,
        table_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Discover tables/metadata for a connection.

        ``space_id`` is REQUIRED to make the caller's intent explicit:

          • Pass the visitor/owner Space UUID to scope the indexing
            per-Space — embeddings get stamped with that space_id.
            This is the right behaviour for tenant-private connections.

          • Pass ``AIServiceHTTPClient.SHARED_INDEX`` to opt in to
            "every Space that has this connection bridged sees the same
            index" — embeddings land with ``space_id IS NULL`` and the
            RAG's ``space_id IN (caller, NULL)`` filter surfaces them
            for every authorised caller. The demo dataset uses this.

        The sentinel exists because the previous signature
        (``space_id: Optional[str] = None``) was a footgun: any caller
        that forgot to pass the kwarg would silently fall through to
        the shared branch and index a tenant-private connection as
        globally-readable across the tenant's spaces. Lucas's 2026-05-05
        adversarial review.

        Raises:
            ValueError: If ``space_id`` is empty/None — pass an actual
                UUID or ``SHARED_INDEX`` explicitly.
            httpx.HTTPError: If request fails.
        """
        if not space_id:
            raise ValueError(
                "discover_connection requires an explicit space_id — pass a "
                "Space UUID for per-Space indexing, or "
                "AIServiceHTTPClient.SHARED_INDEX for shared/global indexing."
            )

        url = f"{self.base_url}/connections/{connection_id}/discover"

        params: Dict[str, Any] = {}
        if space_id != self.SHARED_INDEX:
            params["space_id"] = space_id
        if run_in_background is not None:
            params["run_in_background"] = bool(run_in_background)
        if table_names:
            params["table_names"] = table_names

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                f"Discovering connection: {url} with connection_id={connection_id}, "
                f"space_id={space_id if space_id != self.SHARED_INDEX else '(shared/global)'}"
            )
            response = await client.post(url, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def list_tables(
        self,
        connection_id: str,
        space_id: str,
        user_id: Optional[str] = None,
        crew_ids: Optional[List[str]] = None,
        is_personal: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        List available tables for a connection (AI Engine catalog).

        Endpoint (ia-do-projeto):
          GET /connections/{connection_id}/tables?space_id=...&user_id=...&crew_ids=...&is_personal=...
        """
        url = f"{self.base_url}/connections/{connection_id}/tables"
        params: Dict[str, Any] = {"space_id": space_id}
        if user_id is not None:
            params["user_id"] = user_id
        if crew_ids:
            params["crew_ids"] = crew_ids
        if is_personal is not None:
            params["is_personal"] = bool(is_personal)

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                "Calling AI list tables: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def metadata_status(
        self,
        connection_id: str,
        space_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get metadata status from AI service to avoid running discover on every query.

        Endpoint (ia-do-projeto):
          GET /connections/{connection_id}/metadata-status?space_id=...&ttl_seconds=...
        """
        url = f"{self.base_url}/connections/{connection_id}/metadata-status"
        params: Dict[str, Any] = {"space_id": space_id}
        if ttl_seconds is not None:
            params["ttl_seconds"] = ttl_seconds

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                "Calling AI metadata status: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def chat_bootstrap(
        self,
        connection_id: str,
        user_id: str,
        space_id: str,
        crew_ids: Optional[List[str]] = None,
        language: Optional[str] = None,
        max_suggestions: int = 4,
        is_personal: Optional[bool] = None,
        authorized_tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate greeting + suggestion cards for a new chat session.

        Endpoint (ia-do-projeto):
          POST /connections/{connection_id}/chat/bootstrap
        """
        url = f"{self.base_url}/connections/{connection_id}/chat/bootstrap"
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "space_id": space_id,
            "max_suggestions": max_suggestions,
        }
        if crew_ids:
            payload["crew_ids"] = crew_ids

        # Envio correto de variáveis isoladas
        if authorized_tables:
            payload["authorized_tables"] = authorized_tables

        if language:
            payload["language"] = language
        if is_personal is not None:
            payload["is_personal"] = bool(is_personal)

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                "Calling AI chat bootstrap: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def dashboard_plan(
        self,
        connection_id: str,
        user_id: str,
        space_id: str,
        goal: str,
        original_question: Optional[str] = None,
        crew_ids: Optional[List[str]] = None,
        language: Optional[str] = "en",
        max_widgets: int = 6,
        logical_tables_override: Optional[List[str]] = None,
        schema_summary_override: Optional[str] = None,
        initial_ai_response: Optional[str] = None,
        context_spaces: Optional[List[str]] = None,
        context_crews: Optional[List[str]] = None,
        context_tables: Optional[List[str]] = None,
        authorized_tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a dashboard plan ("Davinci") for a given connection.

        Endpoint (ia-do-projeto):
          POST /connections/{connection_id}/dashboards/plan
        """
        url = f"{self.base_url}/connections/{connection_id}/dashboards/plan"
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "space_id": space_id,
            "goal": goal,
            "max_widgets": max_widgets,
            "language": language or "en",
        }
        # AI service supports (and prefers) original_question to drive widget planning
        if original_question:
            payload["original_question"] = original_question

        # Envio correto de variáveis isoladas
        if authorized_tables:
            payload["authorized_tables"] = authorized_tables

        if crew_ids:
            payload["crew_ids"] = crew_ids
        if logical_tables_override:
            payload["logical_tables_override"] = logical_tables_override
        if schema_summary_override:
            payload["schema_summary_override"] = schema_summary_override
        if initial_ai_response:
            payload["initial_ai_response"] = initial_ai_response
        if context_spaces:
            payload["context_spaces"] = context_spaces
        if context_crews:
            payload["context_crews"] = context_crews
        if context_tables:
            payload["context_tables"] = context_tables

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(
                "Calling AI dashboard plan: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def validate_sql(
        self,
        connection_id: str,
        sql: str,
        user_id: str,
        space_id: str,
        crew_ids: Optional[List[str]] = None,
        is_personal: Optional[bool] = None,
        include_explanation: Optional[bool] = None,
        question: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate SQL by executing a test query (LIMIT 5).

        Endpoint (ia-do-projeto):
          POST /connections/{connection_id}/validate-sql

        Args:
            connection_id: Connection ID
            sql: SQL to validate
            user_id: User ID
            space_id: Space ID
            crew_ids: Optional list of crew IDs
            is_personal: Optional personal mode flag

        Returns:
            Dict with validation result (is_valid, error, preview_data, etc.)

        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}/connections/{connection_id}/validate-sql"
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "space_id": space_id,
            "sql": sql,
        }
        if crew_ids:
            payload["crew_ids"] = crew_ids
        if is_personal is not None:
            payload["is_personal"] = bool(is_personal)
        if include_explanation is not None:
            payload["include_explanation"] = bool(include_explanation)
        if question:
            payload["question"] = question

        async with httpx.AsyncClient(
            timeout=60.0, headers=self._tenant_headers()
        ) as client:  # Timeout aumentado para 60s (warehouses podem demorar)
            logger.info(
                "Calling AI validate SQL: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def suggest_widget_title(
        self,
        question: str,
        data_sample: Optional[List[Dict[str, Any]]] = None,
        answer: Optional[str] = None,
        current_title: Optional[str] = None,
        language: str = "pt",
    ) -> str:
        """
        Sugere um título melhor para um widget baseado nos dados retornados.
        Endpoint (ia-do-projeto):
          POST /widgets/suggest-title
        Args:
            question: Pergunta original do widget
            data_sample: Amostra dos dados retornados (máx. 5 linhas)
            answer: Resposta textual da IA (opcional)
            current_title: Título atual do widget (opcional)
            language: Idioma para o título (pt, en, es)
        Returns:
            Título sugerido pela IA
        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}/widgets/suggest-title"
        payload: Dict[str, Any] = {
            "question": question,
            "language": language,
        }
        if data_sample:
            # Limitar a 5 linhas para não sobrecarregar
            payload["data_sample"] = data_sample[:5]
        if answer:
            # Limitar resposta a 500 caracteres
            payload["answer"] = answer[:500]
        if current_title:
            payload["current_title"] = current_title

        async with httpx.AsyncClient(
            timeout=25.0, headers=self._tenant_headers()
        ) as client:  # Timeout failsafe para sugestão de título
            logger.info(
                "Calling AI suggest widget title: %s question=%s",
                url,
                str(question)[:100],
            )
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                suggested_title = data.get("title", current_title or "Widget")
                logger.info(
                    "Widget title suggested: '%s' -> '%s'",
                    current_title or "N/A",
                    suggested_title,
                )
                return str(suggested_title)
            except httpx.HTTPError as e:
                logger.warning(
                    "Failed to suggest widget title: %s. Using current title.",
                    str(e)[:200],
                )
                # Fallback: retornar título atual ou genérico
                return current_title or "Widget"

    async def generate_infographic(
        self,
        question: str,
        answer: str,
        data_sample: Optional[List[Dict[str, Any]]] = None,
        language: str = "en",
        style: str = "mix",
    ) -> Dict[str, Any]:
        """
        Generate structured data for an infographic based on question, answer and data.

        Endpoint (ia-do-projeto):
          POST /widgets/infographic
        """
        url = f"{self.base_url}/widgets/infographic"
        payload: Dict[str, Any] = {
            "question": question,
            "answer": answer,
            "language": language,
            "style": style,
        }
        if data_sample:
            payload["data_sample"] = data_sample

        async with httpx.AsyncClient(timeout=25.0, headers=self._tenant_headers()) as client:
            logger.info(f"Calling AI generate infographic: {url}")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore

    async def ingest_knowledge_graph(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ingest an entity into the Knowledge Graph.

        Endpoint: POST /knowledge-graph/ingest
        """
        url = f"{self.base_url}/knowledge-graph/ingest"

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._tenant_headers()
        ) as client:
            logger.info(f"Ingesting into Knowledge Graph: {url} payload_id={payload.get('id')}")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore
