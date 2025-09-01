import logging

logger = logging.getLogger(__name__)

from django.db import models, connections, transaction
from django.db.utils import ConnectionDoesNotExist, OperationalError

from awesome_audit_log.conf import get_setting

class AuditDBIsNotAvailable(Exception):
    pass

def _json_type_for(vendor: str) -> str:
    if vendor == 'postgresql':
        return 'JSONB'
    elif vendor == 'mysql':
        return 'JSON'
    return "TEXT"

def _get_connection():
    alias = get_setting('DATABASE_ALIAS')
    connection = None
    try:
        connection = connections[alias]
    except ConnectionDoesNotExist as e:
        if get_setting('RAISE_ERROR_IF_DB_UNAVAILABLE'):
            raise AuditDBIsNotAvailable from e
        if get_setting("FALLBACK_TO_DEFAULT"):
            logger.warning("Audit fall backed to default", exc_info=True)
            connection = connections['default']
        else:
            logger.warning("Audit db is not available", exc_info=True)
            return connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError as e:
        if get_setting('RAISE_ERROR_IF_DB_UNAVAILABLE'):
            raise AuditDBIsNotAvailable from e
        if connection.alias != 'default' and get_setting("FALLBACK_TO_DEFAULT"):
            logger.warning("Audit fall backed to default because of operational error", exc_info=True)
            connection = connections['default']
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except OperationalError as e:
                logger.critical("Unexpected error from audit db when fall backed to default", exc_info=True)
                return None
        else:
            logger.warning("Audit db is not available", exc_info=True)
            return None

    return connection


def ensure_log_table_for_model_exist(model: models.Model) -> str | None:
    connection = _get_connection()
    if not connection:
        return None

    vendor = connection.vendor
    base_table = model._meta.db_table
    log_table = f"{base_table}_log"
    json_type = _json_type_for(vendor)

    # Check if log table already exist
    if vendor == "mysql":
        # MySQL needs a database (schema) filter
        query = """
                SELECT COUNT(*) > 0
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s; \
                """
        params = (connection.settings_dict["NAME"], log_table)

    elif vendor == "postgresql":
        # Default to 'public' unless you use multiple schemas
        query = """
                SELECT EXISTS (SELECT 1 \
                               FROM information_schema.tables \
                               WHERE table_schema = %s \
                                 AND table_name = %s); \
                """
        params = ("public", log_table)

    else:  # sqlite
        # SQLite uses sqlite_master and '?' placeholders
        query = """
                SELECT EXISTS (SELECT 1 \
                               FROM sqlite_master \
                               WHERE type = 'table' \
                                 AND name = %s); \
                """
        params = (log_table,)


    with connection.cursor() as cursor:
        cursor.execute(query, params)
        if cursor.fetchone()[0]:
            return log_table

    if vendor == "postgresql":
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {log_table} (
                id BIGSERIAL PRIMARY KEY,
                action VARCHAR(10) NOT NULL,
                object_pk TEXT NOT NULL,
                before {json_type},
                after {json_type},
                changes {json_type},
                entry_point VARCHAR(20),
                route TEXT,
                path TEXT,
                method VARCHAR(10),
                ip TEXT,
                user_id BIGINT,
                user_name TEXT,
                user_agent TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
    elif vendor == "mysql":
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {log_table} (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                action VARCHAR(10) NOT NULL,
                object_pk TEXT NOT NULL,
                before {json_type},
                after {json_type},
                changes {json_type},
                entry_point VARCHAR(20),
                route TEXT,
                path TEXT,
                method VARCHAR(10),
                ip TEXT,
                user_id BIGINT,
                user_name TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
            """
    else:  # sqlite fallback
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {log_table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                object_pk TEXT NOT NULL,
                before {json_type},
                after {json_type},
                changes {json_type},
                entry_point TEXT,
                route TEXT,
                path TEXT,
                method TEXT,
                ip TEXT,
                user_id INTEGER,
                user_name TEXT,
                user_agent TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """

    with connection.cursor() as cursor:
        cursor.execute(create_sql)

    return log_table

def insert_log_row(model: models.Model, payload: dict):
    connection = _get_connection()
    if not connection:
        return

    log_table = ensure_log_table_for_model_exist(model)
    if not log_table:
        return

    cols = [
        "action", "object_pk", "before", "after", "changes",
        "entry_point", "route", "path", "method", "ip",
        "user_id", "user_name", "user_agent"
    ]
    placeholders = ",".join(["%s"] * len(cols))

    sql = f"INSERT INTO {log_table} ({','.join(cols)}) VALUES ({placeholders})"

    values = [payload.get(c) for c in cols]

    # make sure we only write after the main tx commits
    def _do_insert():
        with connection.cursor() as cursor:
            cursor.execute(sql, values)

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_do_insert)
    else:
        _do_insert()