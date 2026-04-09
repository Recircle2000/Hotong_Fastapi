import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


DEFAULT_DATABASE_SCHEMA = "bus_service"
PASSWORD_PLACEHOLDER = "[YOUR-PASSWORD]"


def get_database_url(env: Mapping[str, str] | None = None) -> str:
    if env is None:
        env = os.environ

    raw_url = env.get("SUPABASE_URL")
    if not raw_url:
        raise RuntimeError("SUPABASE_URL is not set.")

    if raw_url.startswith("sqlite"):
        return raw_url

    normalized_url = _normalize_sqlalchemy_postgres_url(raw_url)
    if PASSWORD_PLACEHOLDER not in normalized_url:
        raise RuntimeError(
            "SUPABASE_URL must contain the [YOUR-PASSWORD] placeholder for Postgres connections."
        )

    password = env.get("SUPABASE_PASSWORD")
    if not password:
        raise RuntimeError("SUPABASE_PASSWORD is not set.")

    encoded_password = quote(password, safe="")
    return normalized_url.replace(PASSWORD_PLACEHOLDER, encoded_password)


def get_database_schema(
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    if env is None:
        env = os.environ

    resolved_url = database_url or env.get("SUPABASE_URL", "")
    if resolved_url.startswith("sqlite"):
        return None

    return env.get("DATABASE_SCHEMA", DEFAULT_DATABASE_SCHEMA)


def get_engine_kwargs(database_url: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    database_schema = get_database_schema(database_url, env)
    connect_args: dict[str, Any] = {}
    if database_schema:
        connect_args["options"] = f"-csearch_path={database_schema}"

    return {
        "connect_args": connect_args,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    }


def create_configured_engine(
    database_url: str,
    env: Mapping[str, str] | None = None,
) -> Engine:
    engine = create_engine(database_url, **get_engine_kwargs(database_url, env))
    database_schema = get_database_schema(database_url, env)
    if database_schema and not database_url.startswith("sqlite"):
        _attach_search_path_handler(engine, database_schema)
    return engine


def get_set_search_path_sql(schema_name: str) -> str:
    safe_schema = schema_name.replace('"', '""')
    return f'SET search_path TO "{safe_schema}"'


def _normalize_sqlalchemy_postgres_url(raw_url: str) -> str:
    if raw_url.startswith("postgresql+psycopg2://"):
        return raw_url
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw_url


def _attach_search_path_handler(engine: Engine, schema_name: str) -> None:
    search_path_sql = get_set_search_path_sql(schema_name)

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection: Any, _connection_record: Any) -> None:
        _apply_search_path(dbapi_connection, search_path_sql)

    @event.listens_for(engine, "checkout")
    def ensure_search_path(
        dbapi_connection: Any,
        _connection_record: Any,
        _connection_proxy: Any,
    ) -> None:
        _apply_search_path(dbapi_connection, search_path_sql)


def _apply_search_path(dbapi_connection: Any, search_path_sql: str) -> None:
    previous_autocommit = getattr(dbapi_connection, "autocommit", None)
    has_autocommit = previous_autocommit is not None

    if has_autocommit:
        dbapi_connection.autocommit = True

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(search_path_sql)
    finally:
        cursor.close()
        if has_autocommit:
            dbapi_connection.autocommit = previous_autocommit
