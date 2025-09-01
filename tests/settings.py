from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "test-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "awesome_audit_log.apps.AwesomeAuditLogConfig",
    "tests.testapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "awesome_audit_log.middleware.RequestEntryPointMiddleware",
]

ROOT_URLCONF = "tests.testapp.urls"
USE_TZ = True
TIME_ZONE = "UTC"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "testdb.sqlite3"),
    }
}

# Keep Step 1 defaults; audit all models by default
AWESOME_AUDIT_LOG = {
    "DATABASE_ALIAS": "default",
    "ASYNC": False,
    "AUDIT_MODELS": "all",
    "CAPTURE_HTTP": True,
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]