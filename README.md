# Awesome Audit Log for Django

This is an awesome package to have your models logs in corresponding _log tables.

Having a single model/table as audit storage can cause heavy db operation and useless for large applications.

With this package you will have each model log in a separate table which can be beneficial if you want to truncate a specific model logs or run a query on them.

Supported DBs to store logs:
1. PostgreSQL
2. MySQL
3. SQLite

This package is in its early stage development and the following features will be added ASAP:
1. Fix dependencies versioning
2. linter
3. github actions
4. Utilizing celery tasks to store audit logs
5. Release it!
6. For now, you just can opt-in models with app_label. We should add a feature for opt-out and also using module path
7. Log rotation
8. Mongo DB support
9. Add management, shell, celery as entry point of logs
10. Document page!

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
    "ASYNC": False,
    "AUDIT_MODELS": "all", # "all" or list like ["app_label.ModelA", "app.ModelB"]
    "CAPTURE_HTTP": True,
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,  # set to False means if audit db is unavailable, silently skip logging (with a warning) instead of raising
    "FALLBACK_TO_DEFAULT": False,  # if audit alias missing/unavailable, use 'default' intentionally, this requires RAISE_ERROR_IF_DB_UNAVAILABLE is set to False
}
```