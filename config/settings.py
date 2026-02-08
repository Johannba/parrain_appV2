"""
Django settings for config project.
Compatible Django 4.2/5.x

– Charge .env.local (prioritaire) puis .env
– Basculer DEV/PROD via DEBUG
– Sécurité/CSRF/SSL corrects selon l’environnement
"""

from pathlib import Path
import os
import dj_database_url

# ======================================================================
# BASE & ENV
# ======================================================================
BASE_DIR = Path(__file__).resolve().parent.parent

def _load_env():
    """Charge .env.local en priorité puis .env (si disponibles)."""
    try:
        from dotenv import load_dotenv
        for name in (".env.local", ".env"):
            p = BASE_DIR / name
            if p.exists():
                load_dotenv(p, override=True)
                break
    except Exception:
        pass

_load_env()

def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}

def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

# ======================================================================
# CORE FLAGS
# ======================================================================
DEBUG = env_bool("DEBUG", True)

SECRET_KEY = (os.getenv("SECRET_KEY") or ("dev-secret" if DEBUG else ""))
if not DEBUG and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY manquant en production.")

# Hôtes & CSRF
if DEBUG:
    ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost,http://127.0.0.1")
else:
    ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "chuchote.com,www.chuchote.com")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "https://chuchote.com,https://www.chuchote.com")

# ======================================================================
# APPS
# ======================================================================
INSTALLED_APPS = [
    # Apps projet
    "legal",
    "core",
    "public",
    "rewards.apps.RewardsConfig",
    "entreprises",
    "accounts.apps.AccountsConfig",
    "dashboard",

    # Django
    "django.contrib.sites",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Libs
    "widget_tweaks",
]

SITE_ID = int(os.getenv("SITE_ID", "1"))

# ======================================================================
# MIDDLEWARE & TEMPLATES
# ======================================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ======================================================================
# DATABASE
# ======================================================================
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'dev.sqlite3'}"),
        conn_max_age=600,
        ssl_require=env_bool("DB_SSL_REQUIRE", False),
    )
}

# ======================================================================
# AUTH / PASSWORDS
# ======================================================================
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "accounts.backends.CaseInsensitiveModelBackend",  # hérite de ModelBackend
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "accounts:login"

# ======================================================================
# I18N / TZ
# ======================================================================
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Paris")
USE_I18N = True
USE_TZ = True

# ======================================================================
# STATIC / MEDIA
# ======================================================================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

if DEBUG:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        }
    }
else:
    STORAGES = {
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
        }
    }
    
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ======================================================================
# EMAIL (Brevo par défaut)
# ======================================================================
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp-relay.brevo.com")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)  # True => 465 ; sinon STARTTLS 587
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465" if EMAIL_USE_SSL else "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@chuchote.com")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "15"))
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", str(60 * 60 * 24 * 2)))  # 2 jours

# ======================================================================
# SMS (SMSMode)
# ======================================================================
SMSMODE = {
    "API_KEY": os.getenv("SMSMODE_API_KEY", ""),
    "SENDER": os.getenv("SMSMODE_SENDER", ""),
    "BASE_URL": os.getenv("SMSMODE_BASE_URL", "https://rest.smsmode.com"),
    "DRY_RUN": env_bool("SMSMODE_DRY_RUN", False),
    "TIMEOUT": 10,
}
SMS_DEFAULT_REGION = os.getenv("SMS_DEFAULT_REGION", "FR")

# ======================================================================
# SÉCURITÉ / PROXY
# ======================================================================
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_DOMAIN = None
    CSRF_COOKIE_DOMAIN = None
else:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", ".chuchote.com")
    CSRF_COOKIE_DOMAIN = os.getenv("CSRF_COOKIE_DOMAIN", ".chuchote.com")

# ======================================================================
# LOGGING
# ======================================================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "DEBUG"},
    "loggers": {
        "rewards.services.smsmode": {"handlers": ["console"], "level": "INFO"},
        "dashboard": {"handlers": ["console"], "level": "INFO"},
        "dashboard.views": {"handlers": ["console"], "level": "INFO"},
    },
}

# ======================================================================
# DÉBOGAGE EMAIL (envoi immédiat au lieu de queue)
# ======================================================================
DEBUG_EMAIL_IMMEDIATE = env_bool("DEBUG_EMAIL_IMMEDIATE", DEBUG)
