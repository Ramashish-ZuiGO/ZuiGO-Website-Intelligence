import importlib.util

import pytest


def test_page_analysis_migration_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "page_analysis_migration",
        "apps/api/alembic/versions/20260723_0009_page_analysis.py",
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Operations:
        def __init__(self) -> None:
            self.created_tables: list[str] = []
            self.dropped_tables: list[str] = []
            self.added_columns: list[str] = []
            self.dropped_columns: list[str] = []
            self.created_indexes: list[str] = []
            self.dropped_indexes: list[str] = []

        def create_table(self, name: str, *args: object, **kwargs: object) -> None:
            self.created_tables.append(name)

        def drop_table(self, name: str) -> None:
            self.dropped_tables.append(name)

        def add_column(self, table: str, *args: object, **kwargs: object) -> None:
            self.added_columns.append(table)

        def drop_column(self, table: str, *args: object, **kwargs: object) -> None:
            self.dropped_columns.append(table)

        def create_index(self, name: str, *args: object, **kwargs: object) -> None:
            self.created_indexes.append(name)

        def drop_index(self, name: str, *args: object, **kwargs: object) -> None:
            self.dropped_indexes.append(name)

        def create_unique_constraint(self, *args: object, **kwargs: object) -> None:
            pass

        def create_foreign_key(self, *args: object, **kwargs: object) -> None:
            pass

        def create_primary_key(self, *args: object, **kwargs: object) -> None:
            pass

        def drop_constraint(self, name: str, table: str, **kwargs: object) -> None:
            pass

        def execute(self, sql: str) -> None:
            pass

    operations = Operations()
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    assert "page_analysis_runs" in operations.created_tables
    assert "website_pages" in operations.added_columns
    assert "uq_page_analysis_runs_page_level_exec" in operations.created_indexes
    assert "ix_page_analysis_runs_execution_id" in operations.created_indexes

    migration.downgrade()
    assert "page_analysis_runs" in operations.dropped_tables
    assert "website_pages" in operations.dropped_columns
