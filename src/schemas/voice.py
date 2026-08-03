"""Voice session persistence (BE-07 slice).

When a voice session ends, the finished transcript is persisted server-side as
a normal Conversation with ``origin='voice'`` messages, so it appears in
History (screen 04) and reopens as a transcript (screen 08) — exactly the
ChatGPT-voice-mode behaviour the masterplan §8 calls for. Writing the
assistant turns is a server-only operation (a client cannot impersonate the
assistant), which is why this lives in the backend.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VoiceTurn(BaseModel):
    role: str = Field(..., pattern="^(user|sky)$")
    text: str = Field(..., min_length=1, max_length=100_000)


class VoiceSessionCreate(BaseModel):
    page_id: UUID
    turns: List[VoiceTurn]
    duration_ms: Optional[int] = Field(None, ge=0)


class VoiceSessionResponse(BaseModel):
    conversation_id: UUID
    title: Optional[str] = None
    message_count: int
