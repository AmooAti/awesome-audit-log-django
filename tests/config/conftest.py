import json
import re

import pytest
from django.db import connection, connections
from awesome_audit_log.conf import get_setting

LOG_TABLE_REGEX = re.compile(r".*_log$")


@pytest.fixture(autouse=True)
def _truncate_dynamic_log_tables(db):
    """Automatically clean up audit log tables before each test."""
    # Clean up before the test runs
    for alias, _conn in connections.databases.items():
        # Skip unavailable or improperly configured database backends
        try:
            conn = connections[alias]
            vendor = conn.vendor
        except Exception:
            continue

        try:
            with conn.cursor() as c:
                if vendor == "sqlite":
                    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in c.fetchall()]
                elif vendor == "postgresql":
                    c.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                    tables = [row[0] for row in c.fetchall()]
                elif vendor == "mysql":
                    c.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                        """
                    )
                    tables = [row[0] for row in c.fetchall()]
                else:
                    tables = []

                for t in tables:
                    if LOG_TABLE_REGEX.fullmatch(t):
                        try:
                            # Drop the table completely to ensure clean state
                            if vendor == "postgresql":
                                c.execute(f'DROP TABLE IF EXISTS "{t}"')
                            else:
                                c.execute(f"DROP TABLE IF EXISTS {t}")
                        except Exception:
                            pass  # Table might not exist
        except Exception:
            # Ignore errors from unavailable databases
            continue

    yield


def fetch_logs_for(base_table: str) -> list[dict]:
    table = f"{base_table}_log"

    # Choose the audit connection based on settings, fall back to default
    alias = get_setting("DATABASE_ALIAS")
    conn = connections[alias] if alias in connections.databases else connection

    # Use different ORDER BY clauses based on database vendor
    vendor = conn.vendor
    if vendor == "sqlite":
        order_clause = "ORDER BY rowid DESC"
    elif vendor == "postgresql":
        order_clause = "ORDER BY id DESC"
    elif vendor == "mysql":
        order_clause = "ORDER BY id DESC"
    else:
        order_clause = "ORDER BY id DESC"

    if vendor == "mysql":
        select_cols = (
            "`action`, `object_pk`, `before`, `after`, `changes`, "
            "`entry_point`, `route`, `path`, `method`, `ip`, `user_id`, `user_name`, `user_agent`"
        )
        table_ident = f"`{table}`"
    else:
        select_cols = (
            "action, object_pk, before, after, changes, "
            "entry_point, route, path, method, ip, user_id, user_name, user_agent"
        )
        table_ident = table

    sql = f"""
          SELECT {select_cols}
          FROM {table_ident}
          {order_clause}
        """
    try:
        with conn.cursor() as c:
            c.execute(sql)
            cols = (
                [col[0] for col in c.cursor.description]
                if hasattr(c, "cursor")
                else [d[0] for d in c.cursor.description]
            )
            rows = c.fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        rec = dict(zip(cols, r, strict=False))
        for k in (
            "before",
            "after",
            "changes",
            "entry_point",
            "route",
            "path",
            "method",
        ):
            v = rec.get(k)
            if isinstance(v, str):
                try:
                    rec[k] = json.loads(v)
                except Exception:
                    pass
        out.append(rec)
    return out
