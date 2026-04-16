import unittest

from db_config import (
    _apply_search_path,
    get_database_schema,
    get_database_url,
    get_engine_kwargs,
    get_set_search_path_sql,
)


class DatabaseConfigTests(unittest.TestCase):
    class _FakeCursor:
        def __init__(self) -> None:
            self.executed_sql: list[str] = []
            self.closed = False

        def execute(self, sql: str) -> None:
            self.executed_sql.append(sql)

        def close(self) -> None:
            self.closed = True

    class _FakeConnection:
        def __init__(self, autocommit: bool = False) -> None:
            self.autocommit = autocommit
            self.cursor_instance = DatabaseConfigTests._FakeCursor()

        def cursor(self) -> "DatabaseConfigTests._FakeCursor":
            return self.cursor_instance

    def test_sqlite_url_bypasses_password_requirement(self):
        self.assertEqual(
            get_database_url({"SUPABASE_URL": "sqlite:///:memory:"}),
            "sqlite:///:memory:",
        )

    def test_postgres_url_normalizes_scheme_and_encodes_password(self):
        resolved = get_database_url(
            {
                "SUPABASE_URL": "postgres://postgres.test:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require",
                "SUPABASE_PASSWORD": "p@ss word:/?#[]",
            }
        )

        self.assertEqual(
            resolved,
            "postgresql+psycopg2://postgres.test:p%40ss%20word%3A%2F%3F%23%5B%5D@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require",
        )

    def test_postgresql_url_normalizes_scheme(self):
        resolved = get_database_url(
            {
                "SUPABASE_URL": "postgresql://postgres.test:[YOUR-PASSWORD]@example.com:5432/postgres",
                "SUPABASE_PASSWORD": "secret",
            }
        )

        self.assertTrue(resolved.startswith("postgresql+psycopg2://"))

    def test_postgres_url_requires_placeholder(self):
        with self.assertRaises(RuntimeError) as exc:
            get_database_url(
                {
                    "SUPABASE_URL": "postgresql://postgres.test:secret@example.com:5432/postgres",
                    "SUPABASE_PASSWORD": "secret",
                }
            )

        self.assertIn("[YOUR-PASSWORD]", str(exc.exception))

    def test_engine_kwargs_include_bus_service_search_path_for_postgres(self):
        kwargs = get_engine_kwargs(
            "postgresql+psycopg2://postgres.test:[YOUR-PASSWORD]@example.com:5432/postgres"
        )

        self.assertEqual(kwargs["connect_args"]["options"], "-csearch_path=bus_service")

    def test_database_schema_can_be_overridden(self):
        self.assertEqual(
            get_database_schema(
                "postgresql+psycopg2://postgres.test:[YOUR-PASSWORD]@example.com:5432/postgres",
                {"DATABASE_SCHEMA": "custom_schema"},
            ),
            "custom_schema",
        )

    def test_set_search_path_sql_quotes_schema_name(self):
        self.assertEqual(
            get_set_search_path_sql('bus_service'),
            'SET search_path TO "bus_service"',
        )

    def test_apply_search_path_executes_sql_and_restores_autocommit(self):
        connection = self._FakeConnection(autocommit=False)

        _apply_search_path(connection, 'SET search_path TO "bus_service"')

        self.assertFalse(connection.autocommit)
        self.assertEqual(
            connection.cursor_instance.executed_sql,
            ['SET search_path TO "bus_service"'],
        )
        self.assertTrue(connection.cursor_instance.closed)


if __name__ == "__main__":
    unittest.main()
