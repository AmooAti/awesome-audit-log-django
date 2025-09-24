# Awesome Audit Log for Django
[![PyPI version](https://img.shields.io/pypi/v/awesome-audit-log-django)](https://pypi.org/project/awesome-audit-log-django/)
[![codecov](https://codecov.io/github/AmooAti/awesome-audit-log-django/graph/badge.svg?token=D5SCFRSM7H)](https://codecov.io/github/AmooAti/awesome-audit-log-django)
![Python versions](https://img.shields.io/pypi/pyversions/awesome-audit-log-django)
![License](https://img.shields.io/pypi/l/awesome-audit-log-django)


This is an awesome package to have your models logs in corresponding _log tables.

Having a single model/table as audit storage can cause heavy db operation and useless for large applications.

With this package you will have each model log in a separate table which can be beneficial if you want to truncate a specific model logs or run a query on them.

You can choose between having logs table in your default database or adding a new backend db as logs db.

Supported DBs to store logs:
1. PostgreSQL
2. MySQL
3. SQLite

This package is in its early stage development and the following features will be added ASAP:
1. Utilizing celery tasks to store audit logs
2. Release it!
3. Log rotation
4. Mongo DB support
5. Add management, shell, celery as entry point of logs
6. Document page!

## Compatible With 

This package works on the below listed Django, Python versions and Databases.

- **Django versions**: 4.2, 5.0, 5.1
- **Python versions**: 3.10, 3.11, 3.12
- **Databases**: SQLite, PostgreSQL, MySQL


## Installation

1. Add App
```python
INSTALLED_APPS = [
    # ...
    'awesome_audit_log.apps.AwesomeAuditLogConfig',
]
```
2. Add Middleware
```python
MIDDLEWARE = [
    # ...
    "awesome_audit_log.middleware.RequestEntryPointMiddleware",
]
```
3. Settings
```python
AWESOME_AUDIT_LOG = {
    "ENABLED": True,
    "DATABASE_ALIAS": "default",
    # PostgreSQL schema for audit tables (defaults to 'public')
    "PG_SCHEMA": None,
    "ASYNC": False,
    # "all" or list like ["app_label.ModelA", "app.ModelB"]
    "AUDIT_MODELS": "all",
    # like AUDIT_MODELS but for opt-out, useful when AUDIT_MODELS set to all
    "NOT_AUDIT_MODELS": None,
    "CAPTURE_HTTP": True,
    # set to False means if audit db is unavailable, silently skip logging (with a warning) instead of raising
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,
    # if audit alias missing/unavailable, use 'default' intentionally, this requires RAISE_ERROR_IF_DB_UNAVAILABLE is set to False
    "FALLBACK_TO_DEFAULT": False,
}
```

## Development

### Preparation

```bash
# Install dependencies
poetry install
```

### Running Tests and Linter Locally

```bash
# Run tests
poetry run pytest

# Run linting
poetry run ruff check awesome_audit_log tests
poetry run ruff format --check awesome_audit_log tests
```
