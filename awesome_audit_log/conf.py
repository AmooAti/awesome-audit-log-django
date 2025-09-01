from django.conf import settings

DEFAULTS = {
    "ENABLED": True,
    "DATABASE_ALIAS": "default",
    "ASYNC": False,
    # "all" or list like ["app_label.ModelA", "app.ModelB"]
    "AUDIT_MODELS": "all",
    "CAPTURE_HTTP": True,
    # set to False means if audit db is unavailable,
    # silently skip logging (with a warning) instead of raising
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,
    # if audit alias missing/unavailable, use 'default' intentionally,
    # this requires RAISE_ERROR_IF_DB_UNAVAILABLE is set to False
    "FALLBACK_TO_DEFAULT": False,
}

def get_setting(key):
    return getattr(settings, 'AWESOME_AUDIT_LOG', {}).get(key, DEFAULTS[key])
