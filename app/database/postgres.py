
import psycopg
from psycopg import Connection

from app.config import get_settings


def get_connection() -> Connection:
    """Create a PostgreSQL connection.

    The caller is responsible for managing its lifetime.
    """
    settings = get_settings()

    return psycopg.connect(settings.database_url)
