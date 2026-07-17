import logging

import pytest
from app.errors import ApplicationError
from app.main import create_app
from fastapi.testclient import TestClient

error_test_app = create_app()


@error_test_app.get("/_test/validation")
def validation_route(count: int) -> dict[str, int]:
    return {"count": count}


@error_test_app.get("/_test/known-error")
def known_error_route() -> None:
    raise ApplicationError(
        code="KNOWN_APPLICATION_ERROR",
        message="A known application error occurred.",
        status_code=409,
        details={"field": "safe_value"},
    )


@error_test_app.get("/_test/unexpected-error")
def unexpected_error_route() -> None:
    raise RuntimeError("internal failure containing verification-secret")


client = TestClient(error_test_app, raise_server_exceptions=False)


def assert_request_id_matches(response: object) -> None:
    response_with_data = response
    request_id = response_with_data.headers["X-Request-ID"]
    assert request_id
    assert response_with_data.json()["error"]["request_id"] == request_id


def test_unknown_route_returns_standardized_404() -> None:
    response = client.get("/unknown", headers={"X-Request-ID": "known-request-id"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "known-request-id"
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Resource not found.",
            "details": None,
            "request_id": "known-request-id",
        }
    }


def test_validation_error_returns_safe_field_details() -> None:
    response = client.get("/_test/validation?count=invalid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"] == "Request validation failed."
    assert response.json()["error"]["details"] == [
        {
            "field": "query.count",
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]
    assert_request_id_matches(response)


def test_known_application_error_is_standardized() -> None:
    response = client.get("/_test/known-error")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "KNOWN_APPLICATION_ERROR"
    assert response.json()["error"]["details"] == {"field": "safe_value"}
    assert_request_id_matches(response)


def test_unexpected_error_is_safe_and_logged_with_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.errors"):
        response = client.get(
            "/_test/unexpected-error",
            headers={"X-Request-ID": "unexpected-request-id"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
            "request_id": "unexpected-request-id",
        }
    }
    assert "verification-secret" not in response.text
    assert "RuntimeError" not in response.text
    assert "unexpected-request-id" in caplog.text
    assert "verification-secret" not in caplog.text
    assert "traceback=" in caplog.text


def test_invalid_request_id_is_replaced() -> None:
    response = client.get("/unknown", headers={"X-Request-ID": "invalid request id"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert_request_id_matches(response)
