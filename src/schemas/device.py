"""Device (push registry) schemas — BE-06."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["ios", "android"]
Provider = Literal["expo", "apns", "fcm"]


class DeviceRegister(BaseModel):
    """Payload to register (upsert) a push token for the current device."""

    platform: Platform
    push_token: str = Field(min_length=1, max_length=512)
    # Which transport the token is for. Defaults to Expo (the app ships on
    # Expo/RN); prod may send raw APNs/FCM tokens instead.
    provider: Provider = "expo"


class DeviceResponse(BaseModel):
    """A registered device."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: Platform
    provider: Provider
    push_token: str
    last_seen_at: datetime
    created_at: datetime
