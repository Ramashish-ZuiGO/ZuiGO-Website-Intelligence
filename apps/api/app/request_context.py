import re
import secrets

from starlette.types import Scope

safe_request_id = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def get_or_create_request_id(scope: Scope) -> str:
    state = scope.setdefault("state", {})
    existing_request_id = state.get("request_id")
    if isinstance(existing_request_id, str):
        return existing_request_id

    for name, value in scope.get("headers", []):
        if name.lower() != b"x-request-id":
            continue
        candidate = value.decode("ascii", errors="ignore")
        if safe_request_id.fullmatch(candidate):
            state["request_id"] = candidate
            return candidate

    request_id = secrets.token_hex(16)
    state["request_id"] = request_id
    return request_id
