from logging.config import fileConfig
import logging
from alembic import context
from db_config import (
    create_configured_engine,
    get_database_schema,
    get_database_url,
    get_set_search_path_sql,
)
from models import Base
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# .env 파일에서 환경 변수 로드
load_dotenv()
DB_URL = get_database_url()
DB_SCHEMA = get_database_schema(DB_URL)
logger.info(
    "Alembic database configuration loaded for %s%s",
    "sqlite" if DB_URL.startswith("sqlite") else "postgresql",
    f" schema={DB_SCHEMA}" if DB_SCHEMA else "",
)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # URL에서 직접 context를 구성
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=DB_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    try:
        engine = create_configured_engine(DB_URL)
        
        logger.info("SQLAlchemy 엔진 생성됨")
        
        with engine.connect() as connection:
            if DB_SCHEMA:
                connection.exec_driver_sql(get_set_search_path_sql(DB_SCHEMA))
                connection.commit()
                connection.dialect.default_schema_name = DB_SCHEMA

            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table_schema=DB_SCHEMA,
            )

            with context.begin_transaction():
                context.run_migrations()
    except Exception as e:
        logger.error(f"마이그레이션 오류: {e}")
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
