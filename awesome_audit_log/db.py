import logging
from abc import ABC, abstractmethod

from django.db import connections, models, transaction
from django.db.utils import ConnectionDoesNotExist, OperationalError

from awesome_audit_log.conf import get_setting

logger = logging.getLogger(__name__)


class AuditDBIsNotAvailable(Exception):
    pass


class AbstractDatabaseVendor(ABC):
    """Abstract base class for database vendor-specific operations."""

    @abstractmethod
    def _get_json_type(self) -> str:
        """Return the JSON type for this vendor."""
        pass

    @abstractmethod
    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        """Return a SQL statement to check if a table exists."""
        pass

    @abstractmethod
    def get_create_table_sql(self, table_name: str) -> str:
        """Return a SQL statement to create a new table."""
        pass

    def parse_table_strings(self, table_name: str) -> str:
        """Return database specific table/column name."""
        return table_name


class PostgresDatabaseVendor(AbstractDatabaseVendor):
    def __init__(self, connection=None):
        self.connection = connection

    def _get_json_type(self) -> str:
        return "JSONB"

    def _get_schema(self) -> str:
        """Get the schema from settings or default to 'public'."""
        configured_schema = get_setting("PG_SCHEMA")
        if configured_schema:
            return configured_schema

        return "public"

    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        schema = self._get_schema()
        query = """
                SELECT EXISTS (SELECT 1 \
                               FROM information_schema.tables \
                               WHERE table_schema = %s \
                                 AND table_name = %s); \
                """
        return query, (schema, table_name)

    def get_create_table_sql(self, table_name: str) -> str:
        json_type = self._get_json_type()
        schema = self._get_schema()
        # Include schema in table name if not default
        full_table_name = f"{schema}.{table_name}" if schema != "public" else table_name
        create_sql = f"""
                   CREATE TABLE IF NOT EXISTS {full_table_name} (
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
        return create_sql


class MySQlDatabaseVendor(AbstractDatabaseVendor):
    def __init__(self, connection):
        self.connection = connection

    def _get_json_type(self) -> str:
        return "JSON"

    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        query = """
                SELECT COUNT(*) > 0
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s; \
                """
        params = (self.connection.settings_dict["NAME"], table_name)
        return query, params

    def get_create_table_sql(self, table_name: str) -> str:
        json_type = self._get_json_type()
        t = self.parse_table_strings(table_name)
        create_sql = f"""
                   CREATE TABLE IF NOT EXISTS {t} (
                       `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
                       `action` VARCHAR(10) NOT NULL,
                       `object_pk` TEXT NOT NULL,
                       `before` {json_type},
                       `after` {json_type},
                       `changes` {json_type},
                       `entry_point` VARCHAR(20),
                       `route` TEXT,
                       `path` TEXT,
                       `method` VARCHAR(10),
                       `ip` TEXT,
                       `user_id` BIGINT,
                       `user_name` TEXT,
                       `user_agent` TEXT,
                       `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   ) ENGINE=InnoDB;
                   """
        return create_sql

    def parse_table_strings(self, table_name: str) -> str:
        return f"`{table_name}`"


class SQLiteDatabaseVendor(AbstractDatabaseVendor):
    def _get_json_type(self) -> str:
        return "TEXT"

    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        query = """
                SELECT EXISTS (SELECT 1 \
                               FROM sqlite_master \
                               WHERE type = 'table' \
                                 AND name = %s); \
                """
        params = (table_name,)
        return query, params

    def get_create_table_sql(self, table_name: str) -> str:
        json_type = self._get_json_type()
        create_sql = f"""
                   CREATE TABLE IF NOT EXISTS {table_name} (
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
        return create_sql


class AuditDatabaseManager:
    def __init__(self):
        self._connection = None
        self._vendor = None

    def _table_exists(self, table_name: str) -> bool:
        query, params = self._vendor.get_table_exist_query(table_name)

        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def _create_log_table(self, log_table: str):
        create_sql = self._vendor.get_create_table_sql(log_table)

        with self._connection.cursor() as cursor:
            cursor.execute(create_sql)

    def _get_vendor_for_connection(self):
        vendor_map = {
            "postgresql": lambda: PostgresDatabaseVendor(self._connection),
            "mysql": lambda: MySQlDatabaseVendor(self._connection),
            "sqlite": SQLiteDatabaseVendor,
        }

        vendor_class = vendor_map.get(self._connection.vendor, SQLiteDatabaseVendor)
        return vendor_class() if not callable(vendor_class) else vendor_class()

    def _get_connection(self):
        alias = get_setting("DATABASE_ALIAS")
        if self._connection is not None:
            return self._connection

        try:
            connection = connections[alias]
        except ConnectionDoesNotExist as e:
            if get_setting("RAISE_ERROR_IF_DB_UNAVAILABLE"):
                raise AuditDBIsNotAvailable from e
            if get_setting("FALLBACK_TO_DEFAULT"):
                logger.warning("Audit fall backed to default", exc_info=True)
                connection = connections["default"]
            else:
                logger.warning("Audit db is not available", exc_info=True)
                return None

        if not self._test_connection(connection):
            return None

        self._connection = connection
        self._vendor = self._get_vendor_for_connection()
        return connection

    def _test_connection(self, connection) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except OperationalError as e:
            if get_setting("RAISE_ERROR_IF_DB_UNAVAILABLE"):
                raise AuditDBIsNotAvailable from e
            if connection.alias != "default" and get_setting("FALLBACK_TO_DEFAULT"):
                logger.warning(
                    "Audit fall backed to default because of operational error",
                    exc_info=True,
                )
                connection = connections["default"]
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                    return True
                except OperationalError as e:
                    logger.critical(
                        "Unexpected error from audit db when fall backed to default",
                        exc_info=True,
                    )
                    return False
            else:
                logger.warning("Audit db is not available", exc_info=True)
                return False

    def ensure_log_table_for_model_exist(self, model: models.Model) -> str | None:
        connection = self._get_connection()
        if not connection:
            return None

        base_table = model._meta.db_table
        log_table = f"{base_table}_log"

        # Check if table already exists
        if self._table_exists(log_table):
            return log_table

        # Create log table if not exists
        self._create_log_table(log_table)

        return log_table

    def insert_log_row(self, model: models.Model, payload: dict):
        connection = self._get_connection()
        if not connection:
            return

        log_table = self._vendor.parse_table_strings(
            self.ensure_log_table_for_model_exist(model)
        )

        if not log_table:
            logger.warning(f"log_table {log_table} does not exist")
            return

        cols = [
            "action",
            "object_pk",
            "before",
            "after",
            "changes",
            "entry_point",
            "route",
            "path",
            "method",
            "ip",
            "user_id",
            "user_name",
            "user_agent",
        ]

        parsed_cols = [self._vendor.parse_table_strings(name) for name in cols]

        placeholders = ",".join(["%s"] * len(cols))

        sql = (
            f"INSERT INTO {log_table} ({','.join(parsed_cols)}) VALUES ({placeholders})"
        )

        values = [payload.get(c) for c in cols]

        # make sure we only write after the main tx commits
        def _do_insert():
            with connection.cursor() as cursor:
                cursor.execute(sql, values)

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(_do_insert)
        else:
            _do_insert()
