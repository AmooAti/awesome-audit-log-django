from pathlib import Path
import MySQLdb  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "test-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "awesome_audit_log.apps.AwesomeAuditLogConfig",
    "tests.fixtures.testapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "awesome_audit_log.middleware.RequestEntryPointMiddleware",
]

ROOT_URLCONF = "tests.fixtures.testapp.urls"
USE_TZ = True
TIME_ZONE = "UTC"

# Common audit log configuration
AWESOME_AUDIT_LOG = {
    "ENABLED": True,
    "DATABASE_ALIAS": "default",
    "ASYNC": False,
    # "all" or list like ["app_label.ModelA", "app.ModelB"]
    "AUDIT_MODELS": "all",
    "CAPTURE_HTTP": True,
    "CAPTURE_COMMANDS": True,
    "CAPTURE_CELERY": True,
    # set to False means if audit db is unavailable, silently skip logging (with a
    # warning) instead of raising
    "RAISE_ERROR_IF_DB_UNAVAILABLE": False,
    # if audit alias missing/unavailable, use 'default' intentionally, this requires
    # RAISE_ERROR_IF_DB_UNAVAILABLE is set to False
    "FALLBACK_TO_DEFAULT": False,
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "testdb.sqlite3"),
        "TEST": {
            "DEPENDENCIES": [],
        },
    },
    "mysql": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "test_audit_log",
        "USER": "root",
        "PASSWORD": "password",
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "charset": "utf8mb4",
        },
        "TEST": {
            "DEPENDENCIES": [],
        },
    },
    "postgres": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "test_audit_log",
        "USER": "postgres",
        "PASSWORD": "password",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "TEST": {
            "DEPENDENCIES": [],
        },
    },
    "postgres_with_different_schema": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "test_audit_log",
        "USER": "postgres",
        "PASSWORD": "password",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "TEST": {
            "DEPENDENCIES": [],
        },
        "OPTIONS": {"options": "-c search_path=public,audit_log"},
    },
}
