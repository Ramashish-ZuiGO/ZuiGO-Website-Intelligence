import logging
import traceback
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import JsonValue
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.errors.exceptions import ApplicationError
from app.errors.models import ErrorBody, ErrorResponse
from app.request_context import get_or_create_request_id

logger = logging.getLogger("app.errors")


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(HTTPException, http_error_handler)
    application.add_exception_handler(ApplicationError, application_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: JsonValue | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = get_or_create_request_id(request.scope)
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=response_headers,
    )


async def validation_error_handler(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    details: list[JsonValue] = []
    for error in exception.errors():
        field = ".".join(str(location) for location in error["loc"])
        details.append(
            {
                "field": field,
                "message": str(error["msg"]),
                "type": str(error["type"]),
            }
        )

    return error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details=details,
    )


async def http_error_handler(request: Request, exception: HTTPException) -> JSONResponse:
    status_code = exception.status_code
    code, message = normalized_http_error(status_code)
    return error_response(
        request,
        status_code=status_code,
        code=code,
        message=message,
        headers=exception.headers,
    )


async def application_error_handler(request: Request, exception: ApplicationError) -> JSONResponse:
    return error_response(
        request,
        status_code=exception.status_code,
        code=exception.code,
        message=exception.message,
        details=exception.details,
    )


async def unexpected_error_handler(request: Request, exception: Exception) -> JSONResponse:
    request_id = get_or_create_request_id(request.scope)
    traceback_frames = traceback.extract_tb(exception.__traceback__)
    sanitized_traceback = " <- ".join(
        f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in traceback_frames
    )
    logger.error(
        "unhandled_exception request_id=%s exception_type=%s traceback=%s",
        request_id,
        type(exception).__name__,
        sanitized_traceback,
    )
    return error_response(
        request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def normalized_http_error(status_code: int) -> tuple[str, str]:
    known_errors = {
        404: ("NOT_FOUND", "Resource not found."),
        405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
    }
    if status_code in known_errors:
        return known_errors[status_code]

    try:
        status = HTTPStatus(status_code)
    except ValueError:
        return "HTTP_ERROR", "Request failed."
    return status.name, f"{status.phrase}."
