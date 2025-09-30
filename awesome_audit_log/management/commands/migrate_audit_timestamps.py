from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import ConnectionDoesNotExist

from awesome_audit_log.conf import get_setting
from awesome_audit_log.db import AuditDatabaseManager


class Command(BaseCommand):
    help = "Migrate audit log tables to fix timestamp accuracy for async logging"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making actual changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompts",
        )
        parser.add_argument(
            "--database",
            type=str,
            help="Database alias to migrate (defaults to configured audit database)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        database_alias = options.get("database") or get_setting("DATABASE_ALIAS")

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting audit log timestamp migration for database: {database_alias}"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        try:
            try:
                connection = connections[database_alias]
            except ConnectionDoesNotExist:
                if get_setting("FALLBACK_TO_DEFAULT"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Database '{database_alias}' not found, falling back to 'default'"
                        )
                    )
                    connection = connections["default"]
                    database_alias = "default"
                else:
                    raise CommandError(f"Database '{database_alias}' not found")

            audit_manager = AuditDatabaseManager()
            audit_manager._connection = connection
            vendor = audit_manager._get_vendor_for_connection()

            audit_tables = self._find_audit_tables(connection, vendor)

            if not audit_tables:
                self.stdout.write(
                    self.style.SUCCESS("No audit log tables found to migrate")
                )
                return

            self.stdout.write(f"Found {len(audit_tables)} audit log tables:")
            for table in audit_tables:
                self.stdout.write(f"  - {table}")

            if not force and not dry_run:
                confirm = input("\nProceed with migration? (y/N): ")
                if confirm.lower() != "y":
                    self.stdout.write("Migration cancelled")
                    return

            migrated_count = 0
            for table in audit_tables:
                if self._migrate_table(connection, table, dry_run):
                    migrated_count += 1

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"DRY RUN: Would migrate {migrated_count} tables"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully migrated {migrated_count} audit log tables"
                    )
                )

        except Exception as e:
            raise CommandError(f"Migration failed: {e}")

    def _find_audit_tables(self, connection, vendor):
        """Find all audit log tables in the database."""
        audit_tables = []

        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                # PostgreSQL: Look for tables ending with _log
                cursor.execute(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_name LIKE '%%_log'
                    """,
                    [vendor._get_schema()],
                )
            elif connection.vendor == "mysql":
                # MySQL: Look for tables ending with _log
                cursor.execute(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_name LIKE '%%_log'
                    """,
                    [connection.settings_dict["NAME"]],
                )
            elif connection.vendor == "sqlite":
                # SQLite: Look for tables ending with _log
                cursor.execute(
                    """
                    SELECT name 
                    FROM sqlite_master 
                    WHERE type = 'table' 
                    AND name LIKE '%%_log'
                    """
                )
            else:
                raise CommandError(f"Unsupported database vendor: {connection.vendor}")

            results = cursor.fetchall()
            audit_tables = [row[0] for row in results]

        return audit_tables

    def _migrate_table(self, connection, table_name, dry_run):
        """Migrate a single audit log table."""
        try:
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
                    # Check if table has DEFAULT constraint
                    cursor.execute(
                        """
                        SELECT column_default 
                        FROM information_schema.columns 
                        WHERE table_name = %s 
                        AND column_name = 'created_at'
                        """,
                        [table_name],
                    )
                    result = cursor.fetchone()
                    if result and result[0]:
                        if dry_run:
                            self.stdout.write(
                                f"  [DRY RUN] Would remove DEFAULT from {table_name}.created_at"
                            )
                        else:
                            # Remove DEFAULT constraint
                            cursor.execute(
                                f"ALTER TABLE {table_name} ALTER COLUMN created_at DROP DEFAULT"
                            )
                            self.stdout.write(
                                f"  ✓ Removed DEFAULT from {table_name}.created_at"
                            )

                elif connection.vendor == "mysql":
                    # Check if table has DEFAULT CURRENT_TIMESTAMP
                    cursor.execute(
                        """
                        SELECT column_default 
                        FROM information_schema.columns 
                        WHERE table_schema = %s 
                        AND table_name = %s 
                        AND column_name = 'created_at'
                        """,
                        [connection.settings_dict["NAME"], table_name],
                    )
                    result = cursor.fetchone()
                    if result and result[0] and "CURRENT_TIMESTAMP" in str(result[0]):
                        if dry_run:
                            self.stdout.write(
                                f"  [DRY RUN] Would remove DEFAULT from {table_name}.created_at"
                            )
                        else:
                            # Remove DEFAULT constraint
                            cursor.execute(
                                f"ALTER TABLE `{table_name}` MODIFY COLUMN `created_at` TIMESTAMP NOT NULL"
                            )
                            self.stdout.write(
                                f"  ✓ Removed DEFAULT from {table_name}.created_at"
                            )

                elif connection.vendor == "sqlite":
                    # SQLite requires table recreation - this is more complex
                    if dry_run:
                        self.stdout.write(
                            f"  [DRY RUN] Would recreate {table_name} without DEFAULT constraint"
                        )
                    else:
                        self.stdout.write(
                            f"  ⚠ SQLite table {table_name} requires manual migration"
                        )
                        self.stdout.write(
                            "    See MIGRATION_GUIDE.md for SQLite-specific instructions"
                        )
                        return False

                return True

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  ✗ Failed to migrate {table_name}: {e}")
            )
            return False
