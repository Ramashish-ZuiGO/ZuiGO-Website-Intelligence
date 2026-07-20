from app.db import Base, SessionLocal, engine


def test_database_foundation_uses_psycopg_with_mvp_tables() -> None:
    assert engine.url.drivername == "postgresql+psycopg"
    assert SessionLocal.kw["bind"] is engine
    assert set(Base.metadata.tables) == {
        "analysis_findings",
        "analysis_diagnostics",
        "analysis_interpretations",
        "analysis_results",
        "analysis_runs",
        "analysis_scores",
        "projects",
        "websites",
    }
