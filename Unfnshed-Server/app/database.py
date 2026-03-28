"""PostgreSQL database connection and utilities."""

from contextlib import contextmanager
from typing import Generator
import psycopg
from psycopg.rows import dict_row

from .config import get_settings


def get_connection() -> psycopg.Connection:
    """Create a new database connection."""
    settings = get_settings()
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    return conn


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
