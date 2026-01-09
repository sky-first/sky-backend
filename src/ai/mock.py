"""Mock AI service for development."""

import asyncio
from typing import Any, Dict, List

from src.config.settings import settings


class MockAIService:
    """Mock AI service for development and testing."""

    async def generate_sql(self, question: str, context: Dict[str, Any]) -> str:
        """
        Generate SQL from natural language question.

        Args:
            question: Natural language question
            context: Context (tables, schemas, etc.)

        Returns:
            str: Generated SQL query
        """
        await asyncio.sleep(0.5)  # Simulate processing time
        tables = context.get("tables", [])
        if tables:
            table_names = ", ".join([t.get("name", "") for t in tables])
            return f"SELECT * FROM {table_names} LIMIT 1000;"
        return "SELECT 1;"

    async def generate_answer(
        self, question: str, sql_result: List[Dict[str, Any]], config: Dict[str, Any]
    ) -> str:
        """
        Generate natural language answer from SQL results.

        Args:
            question: Original question
            sql_result: SQL query results
            config: Configuration (creativity, length, etc.)

        Returns:
            str: Generated answer
        """
        await asyncio.sleep(1.0)  # Simulate processing time
        return f"Esta é uma resposta gerada para: '{question}'\n\nAqui está uma análise detalhada com insights relevantes e recomendações baseadas nos dados disponíveis."

    async def process_pipeline(
        self, query_id: str, configure_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process AI pipeline.

        Args:
            query_id: Query ID
            configure_data: Configuration data

        Returns:
            Dict[str, Any]: Pipeline result
        """
        await asyncio.sleep(2.0)  # Simulate processing time
        return {
            "status": "completed",
            "steps": [
                {
                    "id": "1",
                    "name": "Question",
                    "kind": "question",
                    "status": "COMPLETED",
                    "content": configure_data.get("question", ""),
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
                    "content": "SELECT * FROM tables LIMIT 1000;",
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
            ],
        }
