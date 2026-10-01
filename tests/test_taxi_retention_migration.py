import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


class _PostgresBind:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()


class TaxiRetentionMigrationTests(unittest.TestCase):
    def test_daily_cleanup_is_locked_batched_and_scheduled_for_4am_kst(self):
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/e5d6e7f8a9b0_update_taxi_chat_retention.py"
        )
        spec = importlib.util.spec_from_file_location("taxi_retention_migration", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        statements: list[str] = []

        with patch.object(module.op, "get_bind", return_value=_PostgresBind()), patch.object(
            module.op, "execute", side_effect=statements.append
        ):
            module.upgrade()

        sql = "\n".join(statements).lower()
        self.assertIn("pg_try_advisory_lock", sql)
        self.assertIn("limit 1000", sql)
        self.assertIn("commit", sql)
        self.assertIn("interval '48 hours'", sql)
        self.assertIn("'0 19 * * *'", sql)  # 19:00 UTC = 04:00 Asia/Seoul
        self.assertIn("call public.cleanup_expired_taxi_messages()", sql)


if __name__ == "__main__":
    unittest.main()
