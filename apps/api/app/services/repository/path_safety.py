import os

from app.config import get_settings
from app.errors.exceptions import ApplicationError


def validate_repository_path(path_str: str, allowed_roots: list[str] | None = None) -> str:
    if allowed_roots is None:
        allowed_roots = get_settings().allowed_repository_roots

    if not os.path.exists(path_str):
        raise ApplicationError(
            code="INVALID_REPOSITORY_PATH",
            message=f"Repository path does not exist: {path_str}",
            status_code=400,
        )

    resolved = os.path.realpath(path_str)

    parent = os.path.dirname(resolved)
    if resolved == parent:
        raise ApplicationError(
            code="INVALID_REPOSITORY_PATH",
            message="Filesystem root directories are not allowed as repository paths",
            status_code=400,
        )

    resolved_check = resolved.lower() if os.name == "nt" else resolved
    sep = os.sep
    allowed = False
    for root in allowed_roots:
        root_real = os.path.realpath(root)
        root_check = root_real.lower() if os.name == "nt" else root_real
        if resolved_check == root_check or resolved_check.startswith(root_check + sep):
            allowed = True
            break

    if not allowed:
        raise ApplicationError(
            code="INVALID_REPOSITORY_PATH",
            message=f"Repository path is not within allowed roots: {resolved}",
            status_code=400,
        )

    return resolved


def is_git_repository(path_str: str) -> bool:
    resolved = validate_repository_path(path_str)
    git_dir = os.path.join(resolved, ".git")
    return os.path.isdir(git_dir)
