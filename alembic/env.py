from logging.config import fileConfig
import logging
from alembic import context
from sqlalchemy import engine_from_config, pool, create_engine
from models import Base
import os
from dotenv import load_dotenv
import urllib.parse

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# .env 파일에서 환경 변수 로드
load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
logger.info(f"원본 DB_URL: {DB_URL}")

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
        include_schemas=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    try:
        # URL을 직접 사용하여 엔진 생성
        # 이미 URL 인코딩이 되어 있으므로 그대로 사용
        engine = create_engine(
            DB_URL,
            pool_size=10, 
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True
        )
        
        logger.info("SQLAlchemy 엔진 생성됨")
        
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata
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
