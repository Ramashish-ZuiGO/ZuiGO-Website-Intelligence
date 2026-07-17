from app.db import Base, SessionLocal, engine


def test_database_foundation_uses_psycopg_without_product_tables() -> None:
    assert engine.url.drivername == "postgresql+psycopg"
    assert SessionLocal.kw["bind"] is engine
    assert not Base.metadata.tables
