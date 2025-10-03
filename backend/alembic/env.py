# backend/alembic/env.py
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# --- PATH: 'app' paketini görebilmesi için backend kökünü ekle ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Projenin engine ve Base'ini içe aktar
from app.core.config import engine       # ← kendi engine'ımız
from app.models import Base              # ← tüm tabloların metadata'sı

# Alembic config
config = context.config

# Log ayarları (opsiyonel)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic'in takip edeceği metadata
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline mode: bağlantı açmadan URL ile çalışır."""
    url = str(engine.url)  # ini yerine projedeki engine'dan URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: gerçek connection ile çalışır."""
    connectable = engine  # doğrudan projedeki engine kullan
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=False,  # SQLite için gerekirse True yapılabilir
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
