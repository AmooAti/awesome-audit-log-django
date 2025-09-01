from django.conf import settings

DEFAULTS = {
    "ENABLED": True,
    "DATABASE_ALIAS": "default",
    "ASYNC": False,
    "AUDIT_MODELS": "all", # "all" or list like ["app.ModelA", "app.ModelB"]
    "CAPTURE_HTTP": True,

    "FALLBACK_TO_DEFAULT": False,  # if audit alias missing/unavailable, use 'default' intentionally
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,  # if unavailable, silently skip logging (with a warning) instead of raising
}

def get_setting(key):
    return getattr(settings, 'AWESOME_AUDIT_LOG', {}).get(key, DEFAULTS[key])
