"""Fixtures for every test suite.

This file has to sit in ``tests/``: pytest applies a ``conftest.py`` to its own
directory and below, and ``tests/config/`` -- where the clean-up fixture used to
live -- holds no test modules, so nothing it defined ever ran.
"""

import pytest
from django.db import connections

from awesome_audit_log.db import reset_table_cache
from tests.helpers import LOG_TABLE_REGEX

# Schemas PostgreSQL owns. Log tables never land in them, and a DROP against one
# would fail on permissions rather than do anything useful.
_PG_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


def _aliases_under_test(request) -> list[str]:
    """The database aliases this test is allowed to touch.

    Django fences off every alias a test class leaves out of ``databases`` and
    raises on the first cursor, so the declared set is what can be cleaned. A
    ``SimpleTestCase`` declares none and gets nothing, which is the point.
    """
    databases = getattr(request.cls, "databases", None)
    if databases is None or databases == "__all__":
        return list(connections)
    return [alias for alias in databases if alias in connections.databases]


def _log_tables(cursor, vendor: str) -> list[str]:
    """Return the ``*_log`` tables on this connection, ready to drop."""
    if vendor == "sqlite":
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return [
            name for (name,) in cursor.fetchall() if LOG_TABLE_REGEX.fullmatch(name)
        ]

    if vendor == "postgresql":
        # Every non-system schema, not just ``public``: one alias runs with
        # ``audit_log`` on its search_path, and an unqualified DROP there reaches
        # whichever schema happens to hold the name first. The names come back
        # schema-qualified so each table is dropped where it actually lives.
        schemas = ", ".join(f"'{schema}'" for schema in _PG_SYSTEM_SCHEMAS)
        cursor.execute(
            f"SELECT schemaname, tablename FROM pg_tables "
            f"WHERE schemaname NOT IN ({schemas})"
        )
        return [
            f'"{schema}"."{table}"'
            for schema, table in cursor.fetchall()
            if LOG_TABLE_REGEX.fullmatch(table)
        ]

    if vendor == "mysql":
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            """
        )
        return [
            f"`{name}`"
            for (name,) in cursor.fetchall()
            if LOG_TABLE_REGEX.fullmatch(name)
        ]

    return []


@pytest.fixture(autouse=True)
def _drop_dynamic_log_tables(request, db):
    """Hand every test a database with no dynamically created log tables."""
    # ``awesome_audit_log.db`` remembers "this table exists" for the life of the
    # process, and a DROP here has no way of reaching that. The write path digs
    # itself out -- it re-creates on a failed INSERT -- but
    # ``ensure_log_table_for_model_exist()`` trusts the cache and returns without
    # creating anything, so the drop is only honest once the cache is cleared.
    reset_table_cache()

    for alias in _aliases_under_test(request):
        try:
            connection = connections[alias]
            with connection.cursor() as cursor:
                for table in _log_tables(cursor, connection.vendor):
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            # The integration databases only exist under ``docker compose up``,
            # and an alias can still be fenced off here. Neither is a reason to
            # fail the test that only wanted a clean slate.
            continue

    yield
