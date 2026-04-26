from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = "dev-only-change-me-for-unite-project-at-least-thirty-two-chars"
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "apps.accounts",
    "apps.connections",
    "apps.posts",
    "apps.feed",
    "apps.interests",
    "apps.moderation",
    "apps.policy",
    "apps.ads",
    "apps.ai_accounts",
    "apps.themes",
    "apps.install",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.ai_accounts.middleware.AiActionAuditMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unite-cache",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "600/minute",
        "post_write": "20/minute",
        "post_write_ai": "10/minute",
        "post_react": "120/minute",
        "post_react_ai": "60/minute",
        "connect_action": "60/minute",
        "connect_action_ai": "30/minute",
        "ai_signup": "5/minute",
        "password_reset_request": "10/minute",
        "password_reset_confirm": "20/minute",
    },
}

CORS_ALLOW_ALL_ORIGINS = True

UNITE_SUGGESTION_INTERVAL = 3
UNITE_AD_INTERVAL = 0
UNITE_MAX_INJECTION_RATIO = 0.5
UNITE_FEED_CACHE_TTL_SECONDS = 30

CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
CELERY_BEAT_SCHEDULE = {
    "refresh-active-profiles-every-15m": {
        "task": "apps.accounts.tasks.refresh_active_profile_scores",
        "schedule": 900.0,
    },
    "cleanup-expired-post-caches-hourly": {
        "task": "apps.posts.tasks.cleanup_expired_post_caches",
        "schedule": 3600.0,
    },
}

UNITE_ENABLE_REMOTE_LINK_FETCH = False
UNITE_LINK_PREVIEW_TTL_SECONDS = 86400
UNITE_SPAM_BURST_WINDOW_SECONDS = 60
UNITE_SPAM_BURST_MAX_POSTS = 5
UNITE_SPAM_LINK_WINDOW_SECONDS = 600
UNITE_SPAM_LINK_MAX_POSTS = 3
UNITE_PROFILE_REFRESH_COOLDOWN_SECONDS = 900
UNITE_PROFILE_REFRESH_MIN_POSTS = 1
UNITE_PROFILE_REFRESH_MIN_INTERACTIONS = 2
UNITE_FEED_SUPPRESSED_CATEGORIES = [
    "csam_csem",
    "credible_violence",
    "illegal_promotion",
]
UNITE_PROFILE_IMAGE_SIZE = 256
UNITE_ALLOW_LOCAL_DEMO_RESET = False
