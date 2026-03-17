"""Real AI service implementation using HTTP client."""

import logging
from typing import Any, Dict, List, Optional

from src.ai.http_client import AIServiceHTTPClient
from src.config.settings import settings

logger = logging.getLogger(__name__)


class RealAIService:
    """Real AI service that calls the AI service (ia-do-projeto) via HTTP."""

    def __init__(self, http_client: Optional[AIServiceHTTPClient] = None):
        """
        Initialize real AI service.

        Args:
            http_client: Optional HTTP client (creates new one if not provided)
        """
        self.http_client = http_client or AIServiceHTTPClient()

    async def process_query(
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
    ) -> Dict[str, Any]:
        """
        Process a query using the real AI service.

        Args:
            connection_id: Connection ID
            question: User question
            user_id: User ID
            space_id: Space ID
            crew_ids: Optional list of crew IDs
            thread_id: Optional thread ID
            is_personal: Optional personal mode flag
            selected_datasets: Optional list of table names to force
            instructions: Optional custom instructions for the AI

        Returns:
            Dict with answer, data_sample, sql, and other metadata

        Raises:
            Exception: If AI service call fails
        """
        try:
            # Avoid running discover on every query:
            # 1) Ask AI service if metadata exists / is stale
            # 2) Only trigger discover when needed
            try:
                ttl = settings.AI_METADATA_TTL_SECONDS
                status = await self.http_client.metadata_status(
                    connection_id=connection_id,
                    space_id=space_id,
                    ttl_seconds=ttl,
                )
                should_discover = bool(status.get("should_discover"))
                logger.info(
                    "AI metadata status: connection_id=%s space_id=%s should_discover=%s tables=%s rows=%s last_update=%s",
                    connection_id,
                    space_id,
                    should_discover,
                    status.get("tables_discovered"),
                    status.get("metadata_rows"),
                    status.get("last_metadata_update"),
                )

                if should_discover:
                    await self.http_client.discover_connection(
                        connection_id=connection_id,
                        space_id=space_id,
                    )
                    logger.info(
                        "Triggered metadata discovery for connection %s in AI service (should_discover=True)",
                        connection_id,
                    )
            except Exception as meta_check_error:
                # If status endpoint fails, fall back to previous behavior (best-effort discover)
                logger.warning(
                    "AI metadata status check failed for connection %s: %s. Falling back to best-effort discover.",
                    connection_id,
                    str(meta_check_error),
                )
                try:
                    await self.http_client.discover_connection(
                        connection_id=connection_id,
                        space_id=space_id,
                    )
                    logger.info(
                        "Triggered metadata discovery for connection %s in AI service (fallback)",
                        connection_id,
                    )
                except Exception as discover_error:
                    logger.warning(
                        "Metadata discovery failed for connection %s: %s",
                        connection_id,
                        str(discover_error),
                    )

            response = await self.http_client.query_connection(
                connection_id=connection_id,
                question=question,
                user_id=user_id,
                space_id=space_id,
                crew_ids=crew_ids,
                thread_id=thread_id,
                is_personal=is_personal,
                selected_datasets=selected_datasets,
                authorized_tables=authorized_tables,
                instructions=instructions,
                response_format=response_format,
            )

            # Map response from AI service to our format
            meta = response.get("meta", {})
            chosen_table = meta.get("chosen_table")
            chosen_datasets = meta.get("chosen_datasets")

            # Debug log
            logger.info(
                f"AI service response: meta_keys={list(meta.keys())}, "
                f"chosen_table={chosen_table}, chosen_datasets={chosen_datasets}, "
                f"response_keys={list(response.keys())}"
            )

            # Use chosen_datasets from meta if available, otherwise fallback to chosen_table
            final_chosen_datasets = (
                chosen_datasets
                if chosen_datasets
                else ([chosen_table] if chosen_table else [])
            )

            logger.info(f"Mapped to final_chosen_datasets: {final_chosen_datasets}")

            return {
                "answer": response.get("answer", ""),
                "data_sample": response.get("data_sample", []),
                "sql": meta.get("sql"),
                # NEW: dynamic title generated by AI service during execution
                "title": meta.get("title"),
                "chosen_table": chosen_table,
                "chosen_datasets": final_chosen_datasets,
                "detected_language": meta.get("detected_language"),
                "num_rows": meta.get("num_rows", 0),
                "error": meta.get("error"),
            }
        except Exception as e:
            logger.error(f"Error calling AI service: {str(e)}", exc_info=True)
            raise

    async def generate_sql(self, question: str, context: Dict[str, Any]) -> str:
        """
        Generate SQL from natural language question.

        Note: This is a simplified version. In production, you might want
        to call a dedicated SQL generation endpoint if available.

        Args:
            question: Natural language question
            context: Context (tables, schemas, etc.)

        Returns:
            str: Generated SQL query
        """
        # For now, return a placeholder. In production, you might want
        # to call a dedicated SQL generation endpoint
        tables = context.get("tables", [])
        if tables:
            table_names = ", ".join([t.get("name", "") for t in tables])
            return f"SELECT * FROM {table_names} LIMIT 1000;"
        return "SELECT 1;"

    async def generate_answer(
        self,
        question: str,
        knowledge: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate natural language answer.

        Note: This requires a connection_id. For now, we'll use the first
        connection from knowledge if available.

        Args:
            question: Original question
            knowledge: List of connection IDs or table names
            context: Optional context

        Returns:
            str: Generated answer
        """
        # If we have connection IDs in knowledge, use the first one
        # Otherwise, return a placeholder
        if knowledge and len(knowledge) > 0:
            # Assume first item is a connection_id
            connection_id = knowledge[0]
            # This would need user_id and space_id from context
            # For now, return placeholder
            return (
                f"Generated answer for: '{question}' using connection {connection_id}"
            )

        return f"Generated answer for: '{question}'"

    async def process_pipeline(
        self, query_id: str, configure_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process AI pipeline.

        Note: This is a simplified version. The real pipeline processing
        happens in the AI service. This method simulates the pipeline steps.

        Args:
            query_id: Query ID
            configure_data: Configuration data

        Returns:
            Dict with pipeline steps and status
        """
        question = configure_data.get("question", "")

        # If we have a connection_id in knowledge, we can process it
        # For now, return a simplified pipeline response
        steps = [
            {
                "id": "1",
                "name": "Question",
                "kind": "question",
                "status": "COMPLETED",
                "content": question,
            },
            {
                "id": "2",
                "name": "Orchestrator",
                "kind": "orchestrator",
                "status": "COMPLETED",
                "content": "Processing...",
            },
            {
                "id": "3",
                "name": "Project",
                "kind": "project",
                "status": "COMPLETED",
                "content": "Projected data",
            },
            {
                "id": "4",
                "name": "SQL",
                "kind": "sql",
                "status": "COMPLETED",
                "content": "SQL generated",
            },
            {
                "id": "5",
                "name": "Tables",
                "kind": "tables",
                "status": "COMPLETED",
                "content": "Tables processed",
            },
            {
                "id": "6",
                "name": "Answer",
                "kind": "answer",
                "status": "COMPLETED",
                "content": "Answer generated",
            },
        ]

        return {"status": "completed", "steps": steps}

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
        """
        return await self.http_client.generate_infographic(
            question=question,
            answer=answer,
            data_sample=data_sample,
            language=language,
            style=style,
        )
