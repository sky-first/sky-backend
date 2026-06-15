"""Response schemas for first-setup knowledge suggestions.

These shape the output of ``POST /glossary/suggest-from-connection`` and
``POST /metrics/suggest-from-connection`` — first-pass glossary terms and
metrics derived faithfully from a connection's discovered schema. Every
item carries provenance (``source_table`` / ``source_column``) and is
flagged ``source="auto"`` / ``reviewed=False`` so the FE renders them as
unreviewed proposals the user must curate.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class GlossarySuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    term: str
    definition: str
    source_table: str
    source_column: Optional[str] = None
    source: str = "auto"
    reviewed: bool = False


class MetricSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    aggregation: str
    formula_text: str
    source_table: str
    source_column: Optional[str] = None
    description: Optional[str] = None
    source: str = "auto"
    reviewed: bool = False


class GlossarySuggestionsResponse(BaseModel):
    connection_id: str
    suggestions: List[GlossarySuggestionRead] = []


class MetricSuggestionsResponse(BaseModel):
    connection_id: str
    suggestions: List[MetricSuggestionRead] = []
