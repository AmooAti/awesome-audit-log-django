import logging
from abc import ABC, abstractmethod

from django.db import connections, models, transaction
from django.db.utils import ConnectionDoesNotExist, OperationalError

from awesome_audit_log.conf import get_setting

logger = logging.getLogger(__name__)

# Vendor codes for "the relation you named does not exist".
_PG_UNDEFINED_TABLE = "42P01"
_MYSQL_NO_SUCH_TABLE = 1146

# ``(alias, schema, table)`` triples that are known to exist. Positive entries are
# kept for the life of the process Entries are dropped when a write proves one wrong,
# and by ``reset_table_cache()``.
_TABLE_CACHE = set()

# ``alias -> vendor class``. The vendor of an alias cannot change at runtime, but
# the *instance* is rebuilt per use so a connection from another thread is never
# retained (Django's connections are thread-local).
_VENDOR_CACHE = {}


def reset_table_cache() -> None:
    """Forget every cached table and vendor resolution."""
    _TABLE_CACHE.clear()
    _VENDOR_CACHE.clear()


def _exception_chain(exc: BaseException):
    """Yield ``exc`` and the driver exceptions it wraps.

    Django re-raises driver errors as ``django.db.utils.*`` with the original on
    ``__cause__``, so the vendor's error code usually lives one link down.
    """
    depth = 0
    while exc is not None and depth < 5:
        yield exc
        exc = exc.__cause__
        depth += 1


def _sqlstate(exc: BaseException):
    # psycopg3 exposes .sqlstate, psycopg2 .pgcode, and both carry .diag.sqlstate.
    return (
        getattr(exc, "sqlstate", None)
        or getattr(exc, "pgcode", None)
        or getattr(getattr(exc, "diag", None), "sqlstate", None)
    )


class AuditDBIsNotAvailable(Exception):
    pass


class LogTableMissing(Exception):
    """An INSERT reported that the log table does not exist.

    ``pending`` holds the statements that still need to run so a retry after
    ``CREATE TABLE`` does not replay rows that already landed.
    """

    def __init__(self, pending):
        super().__init__()
        self.pending = pending


class AbstractDatabaseVendor(ABC):
    """Abstract base class for database vendor-specific operations."""

    def __init__(self, connection=None):
        self.connection = connection

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

    def _get_schema(self):
        """Schema the log tables live in, or None for vendors without one."""
        return

    def is_undefined_table_error(self, exc: BaseException) -> bool:
        """Whether ``exc`` means the table being written to does not exist."""
        return False

    def parse_table_strings(self, table_name: str) -> str:
        """Return database specific table/column name."""
        return table_name


class PostgresDatabaseVendor(AbstractDatabaseVendor):
    def _get_json_type(self) -> str:
        return "JSONB"

    def _get_schema(self) -> str:
        """Get the schema from settings or default to 'public'."""
        configured_schema = get_setting("PG_SCHEMA")
        if configured_schema:
            return configured_schema

        return "public"

    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        # to_regclass() reads pg_catalog and returns NULL for a missing relation.
        # information_schema.tables is filtered by privilege.
        schema = self._get_schema()
        return "SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.{table_name}",)

    def is_undefined_table_error(self, exc: BaseException) -> bool:
        return any(
            _sqlstate(err) == _PG_UNDEFINED_TABLE for err in _exception_chain(exc)
        )

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
                       created_at TIMESTAMPTZ NOT NULL
                   );
                   """
        return create_sql


class MySQlDatabaseVendor(AbstractDatabaseVendor):
    def _get_json_type(self) -> str:
        return "JSON"

    def get_table_exist_query(self, table_name: str) -> tuple[str, tuple]:
        # MySQL offers no privilege-independent catalog: information_schema and
        # SHOW TABLES are both filtered by privilege, so a locked-down role can
        # get a false negative here. The write path does not depend on it -- it
        # inserts first and only creates the table if MySQL reports errno 1146.
        query = """
                SELECT COUNT(*) > 0
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s; \
                """
        params = (self.connection.settings_dict["NAME"], table_name)
        return query, params

    def is_undefined_table_error(self, exc: BaseException) -> bool:
        for err in _exception_chain(exc):
            args = getattr(err, "args", ())
            if args and isinstance(args[0], int) and args[0] == _MYSQL_NO_SUCH_TABLE:
                return True
        return False

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
                       `created_at` TIMESTAMP NOT NULL
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

    def is_undefined_table_error(self, exc: BaseException) -> bool:
        return any(
            isinstance(err, OperationalError) and "no such table" in str(err).lower()
            for err in _exception_chain(exc)
        )

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
                       created_at TEXT NOT NULL
                   );
                   """
        return create_sql


_VENDOR_CLASSES = {
    "postgresql": PostgresDatabaseVendor,
    "mysql": MySQlDatabaseVendor,
    "sqlite": SQLiteDatabaseVendor,
}


def _vendor_for(connection) -> AbstractDatabaseVendor:
    vendor_class = _VENDOR_CACHE.get(connection.alias)
    if vendor_class is None:
        vendor_class = _VENDOR_CLASSES.get(connection.vendor, SQLiteDatabaseVendor)
        _VENDOR_CACHE[connection.alias] = vendor_class
    return vendor_class(connection)


class AuditDatabaseManager:
    LOG_COLUMNS = [
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
        "created_at",
    ]

    def __init__(self):
        self._connection = None
        self._vendor = None

    def _cache_key(self, connection, table_name: str) -> tuple:
        return connection.alias, self._vendor._get_schema(), table_name

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
        return _vendor_for(self._connection)

    def _adopt(self, connection):
        self._connection = connection
        self._vendor = self._get_vendor_for_connection()

    def _get_connection(self):
        if self._connection is not None:
            return self._connection

        alias = get_setting("DATABASE_ALIAS")
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

        self._adopt(connection)
        return connection

    def _ping(self, connection) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except OperationalError:
            return False

    def _verify_or_fallback(self, connection):
        """Return a usable connection or None.

        Only reached once a write has already failed; it is no longer on the
        happy path. Pings ``connection`` and, when it is unreachable, falls back
        to the ``default`` alias if allowed. The working connection is returned
        so the caller actually adopts the fallback instead of the broken alias.
        """
        if self._ping(connection):
            return connection

        if get_setting("RAISE_ERROR_IF_DB_UNAVAILABLE"):
            raise AuditDBIsNotAvailable

        if connection.alias != "default" and get_setting("FALLBACK_TO_DEFAULT"):
            logger.warning(
                "Audit fall backed to default because of operational error",
                exc_info=True,
            )
            default = connections["default"]
            if self._ping(default):
                return default
            logger.critical(
                "Unexpected error from audit db when fall backed to default",
                exc_info=True,
            )
            return None

        logger.warning("Audit db is not available", exc_info=True)
        return None

    def ensure_log_table_for_model_exist(self, model: models.Model) -> str | None:
        connection = self._get_connection()
        if not connection:
            return None

        base_table = model._meta.db_table
        log_table = f"{base_table}_log"
        key = self._cache_key(connection, log_table)
        if key in _TABLE_CACHE:
            return log_table

        if not self._table_exists(log_table):
            self._create_log_table(log_table)

        _TABLE_CACHE.add(key)
        return log_table

    def insert_log_row(self, model: models.Model, payload: dict):
        self.insert_log_rows(model, [payload])

    def insert_log_rows(self, model: models.Model, payloads: list[dict]):
        """Insert one or more audit rows for ``model`` in as few statements as
        the backend's parameter limit allows, after the current tx commits."""
        if not payloads:
            return

        connection = self._get_connection()
        if not connection:
            return

        log_table = f"{model._meta.db_table}_log"

        # make sure we only write after the main tx commits
        def _do_insert():
            self._write_rows(log_table, payloads)

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(_do_insert)
        else:
            _do_insert()

    def _write_rows(self, log_table: str, payloads: list[dict]):
        connection = self._connection
        try:
            self._insert_rows(connection, log_table, payloads)
            return
        except OperationalError:
            fallback = self._verify_or_fallback(connection)
            if fallback is None:
                return
            if fallback is connection:
                # The connection answers fine, so this was a genuine write error.
                raise
            self._adopt(fallback)

        self._insert_rows(self._connection, log_table, payloads)

    def _insert_rows(self, connection, log_table: str, payloads: list[dict]):
        statements = self._build_insert_statements(connection, log_table, payloads)
        key = self._cache_key(connection, log_table)
        try:
            self._attempt_insert(connection, statements)
        except LogTableMissing as missing:
            _TABLE_CACHE.discard(key)
            self._create_log_table(log_table)
            try:
                self._execute(connection, missing.pending)
            except LogTableMissing as still_missing:
                raise still_missing.__cause__ or still_missing
        _TABLE_CACHE.add(key)

    def _attempt_insert(self, connection, statements):
        if not connection.in_atomic_block:
            self._execute(connection, statements)
            return

        try:
            with transaction.atomic(using=connection.alias, savepoint=True):
                self._execute(connection, statements)
        except LogTableMissing as missing:
            raise LogTableMissing(statements) from missing

    def _execute(self, connection, statements):
        with connection.cursor() as cursor:
            for index, (sql, values) in enumerate(statements):
                try:
                    cursor.execute(sql, values)
                except Exception as exc:
                    if self._vendor.is_undefined_table_error(exc):
                        raise LogTableMissing(statements[index:]) from exc
                    raise

    def _build_insert_statements(self, connection, log_table: str, payloads: list):
        table = self._vendor.parse_table_strings(log_table)
        cols = self.LOG_COLUMNS
        parsed_cols = ",".join(self._vendor.parse_table_strings(name) for name in cols)
        row_placeholder = "(" + ",".join(["%s"] * len(cols)) + ")"
        batch_size = self._insert_batch_size(connection, len(cols))

        statements = []
        for start in range(0, len(payloads), batch_size):
            chunk = payloads[start : start + batch_size]
            sql = (
                f"INSERT INTO {table} ({parsed_cols}) "
                f"VALUES {','.join([row_placeholder] * len(chunk))}"
            )
            values = [payload.get(c) for payload in chunk for c in cols]
            statements.append((sql, values))
        return statements

    @staticmethod
    def _insert_batch_size(connection, num_cols: int) -> int:
        """Max rows per INSERT, bounded by the backend's placeholder limit."""
        max_params = getattr(connection.features, "max_query_params", None)
        if max_params:
            return max(1, max_params // num_cols)
        # Backends without a known limit (PostgreSQL, MySQL): stay well within
        # their generous caps while still batching aggressively.
        return 500
