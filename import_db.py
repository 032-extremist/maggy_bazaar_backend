import os
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ecommerce")
SQL_FILE = os.getenv(
    "SQL_FILE",
    str(BASE_DIR.parent / "database" / "schema_postgres.sql"),
)


def run():
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        with open(SQL_FILE, "r", encoding="utf-8") as f:
            sql = f.read()

        cursor.execute(sql)
        conn.commit()
        print("Import completed.")
    except Exception as exc:
        print("ERROR:", exc)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    run()
