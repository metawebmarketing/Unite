import os

from .base import *  # noqa: F403,F401

DEBUG = True
ALLOWED_HOSTS = ["*"]
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
UNITE_ALLOW_LOCAL_DEMO_RESET = True
UNITE_SENTIMENT_LOCAL_FILES_ONLY = True
UNITE_ENABLE_REMOTE_LINK_FETCH = True
EMAIL_BACKEND = os.getenv("UNITE_EMAIL_BACKEND", "django.core.mail.backends.filebased.EmailBackend")
EMAIL_FILE_PATH = BASE_DIR / "tmp" / "sent_emails"  # noqa: F405
EMAIL_FILE_PATH.mkdir(parents=True, exist_ok=True)
