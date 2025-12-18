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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Calling AI service: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
            )
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def discover_connection(
        self, connection_id: str, space_id: str
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

        params = {"space_id": space_id}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(
                f"Discovering connection: {url} with connection_id={connection_id}, "
                f"space_id={space_id}"
            )
            response = await client.post(url, params=params)
            response.raise_for_status()
            return response.json()

