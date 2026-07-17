from pydantic import BaseModel, JsonValue


class ErrorBody(BaseModel):
    code: str
    message: str
    details: JsonValue | None = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody
