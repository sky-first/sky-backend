"""Tests for inline (base64 data URI) file upload fallback.

These tests exercise the avatar-upload code path used by the frontend when
no S3/GCS bucket is configured. The service should encode the upload as a
``data:image/...;base64,...`` URI and persist it as the file's URL.
"""

import io

import pytest
from fastapi import UploadFile

from src.core.exceptions import BadRequestError
from src.services.file_upload_service import FileUploadService


# Smallest possible valid PNG (1x1 transparent pixel).
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload_file(content: bytes, filename: str, mime: str) -> UploadFile:
    """Build a FastAPI UploadFile around an in-memory buffer."""
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers={"content-type": mime},
    )


class TestInlineImageUpload:
    """``FileUploadService.upload_image`` with inline storage backend."""

    @pytest.mark.asyncio
    async def test_upload_png_returns_base64_data_uri(
        self, db_session, test_user: dict, monkeypatch
    ):
        """Valid PNG under the size cap is encoded as a data: URI."""
        service = FileUploadService(db_session)
        monkeypatch.setattr(service, "storage_type", "inline")

        upload = _upload_file(_PNG_1x1, "avatar.png", "image/png")
        response = await service.upload_image(test_user["user"], upload)

        assert response.url.startswith("data:image/png;base64,")
        assert response.type == "image/png"
        assert response.size == len(_PNG_1x1)

    @pytest.mark.asyncio
    async def test_upload_rejects_invalid_mime_type(
        self, db_session, test_user: dict, monkeypatch
    ):
        """Non-image MIME types return 400 before any storage work happens."""
        service = FileUploadService(db_session)
        monkeypatch.setattr(service, "storage_type", "inline")

        upload = _upload_file(b"not really an image", "evil.exe", "application/octet-stream")
        with pytest.raises(BadRequestError) as excinfo:
            await service.upload_image(test_user["user"], upload)

        assert "not allowed" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_upload_rejects_over_inline_size_limit(
        self, db_session, test_user: dict, monkeypatch
    ):
        """Images above MAX_INLINE_SIZE are rejected with 400."""
        service = FileUploadService(db_session)
        monkeypatch.setattr(service, "storage_type", "inline")

        oversized = _PNG_1x1 + b"\x00" * (FileUploadService.MAX_INLINE_SIZE + 1)
        upload = _upload_file(oversized, "huge.png", "image/png")

        with pytest.raises(BadRequestError) as excinfo:
            await service.upload_image(test_user["user"], upload)

        assert "inline" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_unknown_storage_falls_back_to_inline(
        self, db_session, test_user: dict, monkeypatch
    ):
        """When storage type is set but cloud bucket is not configured, we
        still succeed via the inline fallback instead of returning the old
        "S3/GCS storage not implemented yet" error."""
        service = FileUploadService(db_session)
        # Simulate someone setting STORAGE_TYPE=s3 without configuring a bucket.
        monkeypatch.setattr(service, "storage_type", "s3")
        from src.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "AWS_S3_BUCKET", "", raising=False)

        upload = _upload_file(_PNG_1x1, "avatar.png", "image/png")
        response = await service.upload_image(test_user["user"], upload)

        assert response.url.startswith("data:image/png;base64,")
