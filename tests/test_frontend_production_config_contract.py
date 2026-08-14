"""Frontend production configuration safety.

NEXT_PUBLIC_* values are inlined at build time, so a production build with
NEXT_PUBLIC_API_URL unset would ship a bundle pointing every customer's browser
at their own machine. The build must fail instead of falling back silently.
"""

from pathlib import Path

API_MODULE = Path("apps/web/src/lib/api.ts")


def test_production_build_refuses_a_silent_localhost_api_fallback() -> None:
    source = API_MODULE.read_text(encoding="utf-8")

    assert 'process.env.NODE_ENV === "production"' in source
    assert "throw new Error(" in source
    assert "NEXT_PUBLIC_API_URL must be set for production builds" in source


def test_localhost_default_survives_only_for_local_development() -> None:
    source = API_MODULE.read_text(encoding="utf-8")

    # The default must be reached only after the production guard has run.
    guard_index = source.index('process.env.NODE_ENV === "production"')
    fallback_index = source.index('?? "http://127.0.0.1:8000"')
    assert guard_index < fallback_index


def test_environment_template_documents_the_required_api_url() -> None:
    template = Path("apps/web/.env.local.example").read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_API_URL=" in template
