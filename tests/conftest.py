import json, re
from typing import List, Dict

import pytest
from django.db import connection, connections

LOG_TABLE_REGEX = re.compile(r".*_log$")

@pytest.fixture(autouse=True)
def _truncate_dynamic_log_tables(db):
    """Automatically clean up audit log tables before each test."""
    # Clean up before the test runs
    for alias, conn in connections.databases.items():
        with connections[alias].cursor() as c:
            vendor = connections[alias].vendor
            if vendor == "sqlite":
                c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in c.fetchall()]
            elif vendor == "postgresql":
                c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                tables = [row[0] for row in c.fetchall()]
            elif vendor == "mysql":
                c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
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
    
    yield

def fetch_logs_for(base_table: str) -> List[Dict]:
    table = f"{base_table}_log"
    sql = f"""
          SELECT action, object_pk, before, after, changes,
                 entry_point, route, path, method, ip, user_id, user_name, user_agent
          FROM {table}
          ORDER BY rowid DESC
        """
    try:
        with connection.cursor() as c:
            c.execute(sql)
            cols = [col[0] for col in c.cursor.description] if hasattr(c, 'cursor') else [d[0] for d in c.cursor.description]
            rows = c.fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        rec = dict(zip(cols, r))
        for k in ('before', 'after', 'changes'): # , 'entry_point', 'route', 'path', 'method',)
            v = rec.get(k)
            if isinstance(v, str):
                try:
                    rec[k] = json.loads(v)
                except Exception:
                    pass
        out.append(rec)
    return out
