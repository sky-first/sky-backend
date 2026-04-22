"""Mock AI service — DEACTIVATED.

The product no longer falls back to fake data when the real AI backend
is unavailable; users must see a clear error instead of "Mock summary
for X". Every method on this class now raises ServiceUnavailableError,
which the global exception handler maps to a 503 with a
`SERVICE_UNAVAILABLE` code. The frontend error banner picks that up
and shows a proper "AI service unavailable — please retry or contact
support" message.

The class + file + method signatures are preserved so existing call
sites in ai_service.py still type-check and import cleanly. Once the
fallback call sites are removed from ai_service.py, this file can go
too.
"""

from typing import Any, Dict, List, Optional

from src.core.exceptions import ServiceUnavailableError

_MESSAGE = (
    "AI service is not available. Either the real AI backend (Ollama / "
    "remote LLM) is unreachable, or AI_SERVICE_TYPE is not set to "
    "'real'. Fake mock responses are intentionally disabled so users "
    "never see fabricated data."
)


def _unavailable() -> None:
    raise ServiceUnavailableError(_MESSAGE)


class MockAIService:
    """Placeholder that preserves the MockAIService import surface but
    refuses to return mock content. See module docstring."""

    async def generate_answer(
        self,
        question: str,
        knowledge: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        _unavailable()
        return ""  # unreachable, satisfies type checker

    async def process_query(
        self, query_id: str, configure_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        _unavailable()
        return {}

    async def process_pipeline(
        self, query_id: str, configure_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        _unavailable()
        return {}

    async def generate_sql(
        self, question: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        _unavailable()
        return ""

    async def analyze_question(
        self, question: str, knowledge: List[str]
    ) -> Dict[str, Any]:
        _unavailable()
        return {}

    async def generate_infographic(
        self,
        question: str,
        answer: str,
        data_sample: Optional[List[Dict[str, Any]]] = None,
        language: str = "en",
        style: str = "mix",
    ) -> Dict[str, Any]:
        _unavailable()
        return {}
