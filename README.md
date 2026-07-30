# Awesome Audit Log for Django

[![PyPI version](https://img.shields.io/pypi/v/awesome-audit-log-django)](https://pypi.org/project/awesome-audit-log-django/)
[![codecov](https://codecov.io/github/AmooAti/awesome-audit-log-django/graph/badge.svg?token=D5SCFRSM7H)](https://codecov.io/github/AmooAti/awesome-audit-log-django)
![Python versions](https://img.shields.io/pypi/pyversions/awesome-audit-log-django)
![License](https://img.shields.io/pypi/l/awesome-audit-log-django)

Django audit logging that writes each model's history to its own `<table>_log` table, with optional async logging via Celery.

A per-model log table (instead of one shared audit table) keeps writes cheap, makes per-model queries fast, and lets you truncate or archive a single model's history in isolation. Logs can live in your default database or a dedicated one.

## Compatible With

- **Django**: 5.0, 5.1, 5.2, 6.0
- **Python**: 3.10, 3.11, 3.12, 3.13, 3.14
- **Databases**: SQLite, PostgreSQL, MySQL
- **Celery**: optional, for async logging

## Installation

Add the app and middleware, then configure it in settings:

```python
INSTALLED_APPS = [
    # ...
    "awesome_audit_log.apps.AwesomeAuditLogConfig",
]

MIDDLEWARE = [
    # ...
    "awesome_audit_log.middleware.RequestEntryPointMiddleware",
]
```

## Configuration

All settings live under the `AWESOME_AUDIT_LOG` dict. Defaults are shown below; you only need to set the keys you want to change.

```python
AWESOME_AUDIT_LOG = {
    "ENABLED": True,
    "DATABASE_ALIAS": "default",
    # PostgreSQL schema for audit tables (defaults to 'public')
    "PG_SCHEMA": None,
    # Log asynchronously via Celery (requires Celery configured in your project)
    "ASYNC": False,
    # "all", or a list like ["app_label.ModelA", "app.ModelB"]
    "AUDIT_MODELS": "all",
    # Opt-out list, useful when AUDIT_MODELS is "all"
    "NOT_AUDIT_MODELS": None,
    "CAPTURE_HTTP": True,
    "CAPTURE_COMMANDS": True,
    "CAPTURE_CELERY": True,
    # If the audit DB is unavailable: raise instead of skipping the log
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,
    # If the audit alias is missing/unavailable, fall back to 'default'
    # (requires RAISE_ERROR_IF_DB_UNAVAILABLE = False)
    "FALLBACK_TO_DEFAULT": False,
    # Rows per chunk when the bulk helpers snapshot and refetch a large queryset.
    # None derives it from the backend's placeholder limit: 500 on PostgreSQL/MySQL,
    # ~70 on SQLite.
    "BULK_CHUNK_SIZE": None,
}
```

## Table Resolution

An audit write costs a single `INSERT`. The package does not check whether the
`<table>_log` table exists first — it inserts, and only if the backend reports an
undefined table (PostgreSQL `42P01`, MySQL `1146`, SQLite `no such table`) does it
create the table and retry once. The retry runs under a savepoint when the write
happens inside an open transaction, so a failed attempt never poisons it.

Tables proven to exist are remembered per `(database alias, schema, table)` for the
life of the process. There is no expiry: the entry is dropped only when a write
shows it to be wrong.

If you drop `_log` tables at runtime — test fixtures, tear-down helpers, a
maintenance script in the same process — clear the cache afterwards:

```python
from awesome_audit_log.db import reset_table_cache

reset_table_cache()
```

Recovery is automatic even if you forget (the next write recreates the table), but
clearing keeps the behaviour explicit.

## Bulk Operations

Django's bulk operations bypass `save()`/`delete()` signals, so plain `bulk_create()`,
`bulk_update()`, and `QuerySet.update()` are **not** audited automatically. Use the
explicit helpers when a bulk operation should be logged — each call writes its audit
rows in a single batched insert:

```python
from awesome_audit_log.bulk import (
    audited_bulk_create,
    audited_bulk_update,
    audited_queryset_update,
)

widgets = audited_bulk_create(Widget.objects, [Widget(name="A", qty=10)])

audited_bulk_update(Widget.objects, widgets, fields=["qty"])

audited_queryset_update(Widget.objects.filter(qty__lt=10), qty=10)
```

For model-level opt-in, attach `AuditedBulkQuerySet` (or mix `AuditedBulkQuerySetMixin`
into your own queryset) so the standard bulk methods audit themselves:

```python
from awesome_audit_log.bulk import AuditedBulkQuerySet


class Widget(models.Model):
    objects = AuditedBulkQuerySet.as_manager()
```

```python
Widget.objects.bulk_create([Widget(name="A", qty=10)])
Widget.objects.filter(qty__lt=10).update(qty=100)
```

Notes:

- `bulk_update()` and `QuerySet.update()` log only the changed fields.
- `QuerySet.update()` snapshots the matched rows before the write and refetches them
  after it. Both passes run in chunks of `BULK_CHUNK_SIZE`, so neither the `IN` clause
  nor the batched audit insert grows with the size of the queryset. The `UPDATE` itself
  stays a single statement, so `F()` expressions are applied exactly once. The
  before-snapshot is still held in memory for the whole operation (one serialized dict
  per matched row) — that is what the audit rows are diffed against, and it cannot be
  streamed without `UPDATE ... RETURNING`.
- Pre-write snapshots are read from the alias the write will land on
  (`db_for_write`), not from `db_for_read`, so a primary/replica router can't make the
  `from` values stale.
- `bulk_create(..., update_conflicts=True)` is an upsert: rows that already existed are
  logged as `update` with a real `before`, and only genuinely new rows are logged as
  `insert`. This requires `unique_fields` so the helper can find the rows a conflict
  would hit. MySQL has no conflict target and therefore rejects `unique_fields`, so
  `update_conflicts=True` cannot be audited there — the helper raises
  `NotImplementedError` rather than recording an update as a creation.
- `bulk_create(..., ignore_conflicts=True)` returns objects without primary keys on most
  backends; those rows can't be audited and are skipped with a warning. If you pass
  objects that already carry a primary key, rows that were silently skipped because of a
  conflict are still logged as inserts.
- `QuerySet.delete()` is already covered by Django's delete signals.

Known limitations:

- **Race window.** Between the `UPDATE` and the refetch, a concurrent writer can change
  the same rows; its change is then attributed to this operation. Closing the window
  needs `UPDATE ... RETURNING` (PostgreSQL) or row locking, neither of which is
  implemented.
- **Bulk deletes are not batched.** `QuerySet.delete()` goes through `pre_delete` per
  row, so deleting 50k rows issues 50k audit inserts.
- **Fast delete is disabled globally.** The `pre_delete` receiver is connected for every
  model, so Django can never take its fast-delete path (a single `DELETE` with no
  per-object signals) anywhere in the project. That is a real cost on large deletes, and
  it applies to every model — including ones excluded via `NOT_AUDIT_MODELS`.

## Async Logging with Celery

Set `ASYNC = True` to offload audit writes to Celery. The package uses your existing
Celery setup (it does not configure Celery for you) and falls back to synchronous
logging if Celery isn't installed. Tasks are enqueued only after the surrounding
transaction commits, so a rolled-back change is never logged.

```python
# settings.py
CELERY_BROKER_URL = "redis://localhost:6379/0"
AWESOME_AUDIT_LOG = {"ASYNC": True}
```

Timestamps (`created_at`) are captured at event time, not at insert time, so they stay
accurate even with async delays. See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) if you're
upgrading from a version prior to 1.0.0.

## Entry Point Detection

Every log row records the `entry_point` it originated from:

- `http` — HTTP requests, via the middleware (`CAPTURE_HTTP`)
- `management_command` — Django management commands (`CAPTURE_COMMANDS`)
- `celery_task` — Celery tasks and Beat schedules (`CAPTURE_CELERY`)

HTTP rows also capture path, route, method, IP, user, and user agent.

## Development

```bash
poetry install

# Tests
poetry run pytest

# Lint
poetry run ruff check awesome_audit_log tests
poetry run ruff format --check awesome_audit_log tests
```
