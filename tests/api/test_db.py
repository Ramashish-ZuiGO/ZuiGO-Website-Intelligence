from app.db import Base, SessionLocal, engine


def test_database_foundation_uses_psycopg_with_mvp_tables() -> None:
    assert engine.url.drivername == "postgresql+psycopg"
    assert SessionLocal.kw["bind"] is engine
    assert set(Base.metadata.tables) == {
        "action_generation_executions",
        "action_groups",
        "action_items",
        "action_status_history",
        "action_matching_executions",
        "action_repository_matches",
        "analysis_findings",
        "analysis_diagnostics",
        "analysis_interpretations",
        "analysis_results",
        "analysis_runs",
        "analysis_scores",
        "detected_technologies",
        "discovery_runs",
        "page_analysis_runs",
        "projects",
        "repository_connections",
        "repository_file_index",
        "repository_scan_executions",
        "website_pages",
        "websites",
    }
