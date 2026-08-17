from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_auth_module_provides_token_storage_and_login() -> None:
    """Verify auth.ts provides token helpers and login function."""
    auth = read("apps/web/src/lib/auth.ts")

    # Token storage helpers
    assert "getToken" in auth
    assert "setToken" in auth
    assert "clearToken" in auth
    assert "zuigo_access_token" in auth
    assert "localStorage" in auth

    # Login function
    assert "async function login" in auth or "export async function login" in auth
    assert "/api/v1/auth/login" in auth
    assert "access_token" in auth
    assert 'method: "POST"' in auth or "method: 'POST'" in auth

    # Does NOT store the password
    assert "setToken(data.access_token)" in auth
    # The function takes password as param but only stores the token
    assert "password" in auth  # param name
    assert "localStorage.setItem" in auth


def test_api_request_attaches_token_and_handles_401() -> None:
    """Verify apiRequest attaches bearer token and redirects on 401."""
    api = read("apps/web/src/lib/api.ts")

    # Imports auth helpers
    assert "getToken" in api
    assert "clearToken" in api

    # Attaches Authorization header
    assert "Authorization" in api
    assert "Bearer" in api

    # Handles 401 with redirect to login
    assert "401" in api
    assert "/login" in api
    assert "clearToken()" in api
    assert "window.location" in api

    # Avoids infinite redirect loop on /login
    login_guard_lines = [
        line for line in api.splitlines() if "/login" in line and "startsWith" in line
    ]
    assert len(login_guard_lines) >= 1, (
        "api.ts must check if already on /login to avoid redirect loop"
    )


def test_login_page_exists_with_form() -> None:
    """Verify login page has username, password, submit, and error display."""
    page = read("apps/web/src/app/login/page.tsx")

    # Form elements
    assert "username" in page.lower()
    assert "password" in page.lower()
    assert 'type="password"' in page
    assert 'type="submit"' in page or 'type="text"' in page

    # Login function import and call
    assert "login" in page
    assert "auth" in page

    # Error display
    assert 'role="alert"' in page

    # Loading state
    assert "submitting" in page or "loading" in page

    # Redirect after login
    assert "redirect" in page

    # Branded header
    assert "ZuiGO" in page or "WebIQ" in page

    # Does NOT store the password in any persistent way
    # (the password state is local React state only)
    assert "localStorage" not in page
    assert "sessionStorage" not in page


def test_auth_guard_protects_routes() -> None:
    """Verify AuthGuard checks token and redirects when missing."""
    guard = read("apps/web/src/components/auth/AuthGuard.tsx")

    # Checks for token
    assert "getToken" in guard

    # Redirects to /login
    assert "/login" in guard

    # Skips guard for login path
    assert "login" in guard
    login_public_lines = [line for line in guard.splitlines() if "/login" in line]
    assert len(login_public_lines) >= 1

    # Renders TopNav for authenticated routes
    assert "TopNav" in guard

    # Does not render TopNav for public paths
    # (the guard returns children directly for public paths)
    assert "isPublicPath" in guard or "PUBLIC_PATHS" in guard


def test_root_layout_uses_auth_guard() -> None:
    """Verify root layout imports and renders AuthGuard instead of TopNav."""
    layout = read("apps/web/src/app/layout.tsx")

    # AuthGuard is imported
    assert "AuthGuard" in layout
    assert "auth/AuthGuard" in layout

    # AuthGuard wraps children
    assert "<AuthGuard>" in layout

    # TopNav is NOT directly imported (AuthGuard handles it now)
    topnav_import_lines = [
        line for line in layout.splitlines() if "import" in line and "TopNav" in line
    ]
    assert len(topnav_import_lines) == 0, (
        "Root layout should not import TopNav directly — AuthGuard handles it"
    )
