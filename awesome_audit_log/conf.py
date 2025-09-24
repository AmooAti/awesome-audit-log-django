from django.conf import settings

DEFAULTS = {
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
    # set to False means if audit db is unavailable,
    # silently skip logging (with a warning) instead of raising
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,
    # if audit alias missing/unavailable, use 'default' intentionally,
    # this requires RAISE_ERROR_IF_DB_UNAVAILABLE is set to False
    "FALLBACK_TO_DEFAULT": False,
}


def get_setting(key):
    return getattr(settings, "AWESOME_AUDIT_LOG", {}).get(key, DEFAULTS[key])
