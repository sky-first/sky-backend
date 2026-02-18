import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MockAIService:
    """Mock implementation of AI processing for development and testing."""

    async def generate_answer(
        self, question: str, knowledge: List[str], context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Mock answer generation."""
        await asyncio.sleep(0.5)
        return (
            f"This is a mock answer for the question: '{question}' based on knowledge: {knowledge}"
        )

    async def process_query(self, query_id: str, configure_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock query processing."""
        await asyncio.sleep(1)
        return {
            "id": query_id,
            "answer": f"Mock answer for {configure_data.get('question', 'query')}",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def process_pipeline(
        self, query_id: str, configure_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mock pipeline processing with 6 steps."""
        await asyncio.sleep(0.2)
        steps = [
            {
                "name": "Question",
                "kind": "question",
                "status": "COMPLETED",
                "content": configure_data.get("question", ""),
            },
            {
                "name": "Orchestrator",
                "kind": "orchestrator",
                "status": "COMPLETED",
                "content": "Analyzing intent...",
            },
            {
                "name": "Project",
                "kind": "project",
                "status": "COMPLETED",
                "content": "Schema mapping...",
            },
            {
                "name": "SQL",
                "kind": "sql",
                "status": "COMPLETED",
                "content": "SELECT * FROM mock_table;",
            },
            {
                "name": "Tables",
                "kind": "tables",
                "status": "COMPLETED",
                "content": "Processing results...",
            },
            {
                "name": "Answer",
                "kind": "answer",
                "status": "COMPLETED",
                "content": f"Mock summary for {configure_data.get('question', 'query')}",
            },
        ]
        return {
            "id": query_id,
            "status": "completed",
            "steps": steps,
        }

    async def generate_sql(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Mock SQL generation."""
        await asyncio.sleep(0.3)
        return "SELECT count(*) FROM users WHERE created_at > '2025-01-01';"

    async def analyze_question(self, question: str, knowledge: List[str]) -> Dict[str, Any]:
        """Mock question analysis."""
        await asyncio.sleep(0.2)
        return {"intent": "query", "entities": ["users", "sales"], "complexity": "simple"}

    async def generate_infographic(
        self,
        question: str,
        answer: str,
        data_sample: Optional[List[Dict[str, Any]]] = None,
        language: str = "en",
        style: str = "mix",
    ) -> Dict[str, Any]:
        """Mock infographic generation."""
        await asyncio.sleep(0.5)

        # Simple style variation for mock
        prefix = f"[{style.upper()}] " if style != "mix" else ""
        return {
            "title": f"{prefix}Mock Infographic Title",
            "subtitle": f"Analysis based on mock data ({style})",
            "mainValue": "$1.2M",
            "mainValueLabel": "Total Revenue",
            "summary": "This is a mock summary for visualization testing.",
            "highlightedValue": "+15%",
            "marginLabel": "Gross Margin",
            "marginValue": "45%",
            "cacLabel": "CAC",
            "cacValue": "$120",
            "trajectoryTitle": "Growth Trajectory",
            "trajectoryData": [
                {"name": "Jan", "value": 100},
                {"name": "Feb", "value": 120},
                {"name": "Mar", "value": 150},
            ],
            "recordHighLabel": "All-time High",
            "drivers": [
                {
                    "name": "New Product Launch",
                    "impact": "High",
                    "description": "Successful launch of V2 product line.",
                },
                {
                    "name": "Market Expansion",
                    "impact": "Medium",
                    "description": "Entry into new regional markets.",
                },
            ],
            "whyTitle": "Why is this happening?",
            "whyContent": "Mock explanation for trends.",
            "strategicTitle": "Strategic Outlook",
            "strategicContent": "Focus on retention and upselling.",
            "outlookTitle": "Forecast",
            "outlookContent": "Stable growth expected.",
        }
