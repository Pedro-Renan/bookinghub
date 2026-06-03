"""
BookingHub — api/utils/db.py
Gerenciamento de conexão com o PostgreSQL via psycopg2.
Sem ORM — SQL puro conforme requisito do trabalho.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://booking:secret@localhost:5432/bookinghub"
)


def get_connection():
    """Retorna uma conexão nova com autocommit=False."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_db():
    """
    Dependência FastAPI: abre conexão, injeta no endpoint e fecha ao final.
    O commit/rollback é responsabilidade de cada endpoint.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
