"""HTTP client for AI service."""

import logging
from typing import Any, Dict, List, Optional

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
        self.timeout = 300.0  # 5 minutes timeout for AI queries

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

        Returns:
            Dict with answer, data_sample, and meta information

        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}/connections/{connection_id}/query"

        payload = {
            "question": question,
            "user_id": user_id,
            "space_id": space_id,
        }

        if crew_ids:
            payload["crew_ids"] = crew_ids
        if thread_id:
            payload["thread_id"] = thread_id
        if is_personal is not None:
            payload["is_personal"] = bool(is_personal)
        if selected_datasets:
            payload["selected_datasets"] = selected_datasets

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Calling AI service: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def discover_connection(
        self,
        connection_id: str,
        space_id: str,
        run_in_background: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Discover tables/metadata for a connection.

        Args:
            connection_id: Connection ID
            space_id: Space ID

        Returns:
            Dict with discovery results

        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}/connections/{connection_id}/discover"

        params: Dict[str, Any] = {"space_id": space_id}
        if run_in_background is not None:
            params["run_in_background"] = bool(run_in_background)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Discovering connection: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
            )
            response = await client.post(url, params=params)
            response.raise_for_status()
            return response.json()

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
            return response.json()

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
            return response.json()

    async def chat_bootstrap(
        self,
        connection_id: str,
        user_id: str,
        space_id: str,
        crew_ids: Optional[List[str]] = None,
        language: Optional[str] = None,
        max_suggestions: int = 4,
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
        if language:
            payload["language"] = language

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                "Calling AI chat bootstrap: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def dashboard_plan(
        self,
        connection_id: str,
        user_id: str,
        space_id: str,
        goal: str,
        crew_ids: Optional[List[str]] = None,
        language: Optional[str] = "en",
        max_widgets: int = 6,
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
        if crew_ids:
            payload["crew_ids"] = crew_ids

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                "Calling AI dashboard plan: %s connection_id=%s space_id=%s",
                url,
                connection_id,
                space_id,
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

