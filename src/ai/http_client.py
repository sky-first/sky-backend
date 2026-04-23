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

    async def query_connection(
        self,
        connection_id: str,
        question: str,
        user_id: str,
        space_id: str,
        crew_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        is_personal: Optional[bool] = None,
        selected_datasets: Optional[List[str]] = None,
        authorized_tables: Optional[List[str]] = None,
        instructions: Optional[str] = None,
        response_format: Optional[str] = None,
        security_config: Optional[Dict[str, Any]] = None,
        ai_tone: Optional[str] = None,
        ai_style: Optional[str] = None,
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Calling AI service: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
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

        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"Streaming AI service: {url} for connection {connection_id}")
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield line

    async def discover_connection(
        self,
        connection_id: str,
        space_id: str,
        run_in_background: Optional[bool] = None,
        table_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Discover tables/metadata for a connection.

        Args:
            connection_id: Connection ID
            space_id: Space ID
            run_in_background: Optional background execution flag
            table_names: Optional list of table names to filter discovery

        Returns:
            Dict with discovery results

        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}/connections/{connection_id}/discover"

        params: Dict[str, Any] = {"space_id": space_id}
        if run_in_background is not None:
            params["run_in_background"] = bool(run_in_background)
        if table_names:
            params["table_names"] = table_names

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Discovering connection: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
            timeout=60.0
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
            timeout=25.0
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

        async with httpx.AsyncClient(timeout=25.0) as client:
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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Ingesting into Knowledge Graph: {url} payload_id={payload.get('id')}")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # type: ignore
