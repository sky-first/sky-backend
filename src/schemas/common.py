"""Common schemas."""

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessResponse(BaseModel):
    """Success response schema."""

    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: str
    message: str
    details: Optional[Any] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response schema."""

    items: List[T]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int = Field(ge=0)

    @classmethod
    def create(
        cls, items: List[T], total: int, page: int, page_size: int
    ) -> "PaginatedResponse[T]":
        """Create paginated response."""
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: str
