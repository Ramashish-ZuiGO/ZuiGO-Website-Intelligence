import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_serializer


class WebsiteCreate(BaseModel):
    url: AnyHttpUrl
    name: str | None = Field(default=None, max_length=200)

    @field_serializer("url")
    def serialize_url(self, value: AnyHttpUrl) -> str:
        return str(value)


class WebsiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    name: str | None
    created_at: datetime
    updated_at: datetime
