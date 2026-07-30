# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases before 1.3.0 predate this file; see the git history for those.

## [1.3.0] - 2026-07-30

### Added
- Audited bulk helpers: `audited_bulk_create`, `audited_bulk_update`,
  `audited_queryset_update`, and `AuditedBulkQuerySet` — Django's bulk operations bypass
  signals and were previously not captured at all. PostgreSQL, MariaDB and SQLite 3.35+;
  see Known limitations for MySQL.
- `BULK_CHUNK_SIZE` setting. Defaults to the backend's placeholder limit.

### Changed
- Audit writes cost 1 round trip instead of 3. Table existence is cached at module
  level, keyed on `(alias, schema, table)`, and the per-write `SELECT 1` ping is gone.
- PostgreSQL existence checks use `to_regclass` instead of `information_schema`, which
  returns zero rows — a false "absent" — for a role without privileges on the log table.
- A missing log table is now handled by retrying the `INSERT` after `CREATE`, so writing
  no longer requires read privilege on the log table.

### Known limitations
- MySQL is not supported by the bulk helpers yet. `audited_bulk_create` records no rows,
  and `bulk_create(update_conflicts=True)` raises `NotImplementedError` rather than
  guess. Same applies to SQLite < 3.35. Signal-based auditing (`save`, `delete`) is
  unaffected on every backend.
- `bulk_create(ignore_conflicts=True)` logs skipped rows as inserts.
- Bulk deletes are not batched; fast delete is disabled project-wide.
